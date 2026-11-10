"""Build reviewed collaboration constraints in source SQL only; never connect to a database."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[2]


def bounded(kind, maximum):
    return {'type': kind, 'maxLength': maximum}


def nullable(rule):
    return {'anyOf': [rule, {'type': 'null'}]}


def object_schema(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def schema_sql(schema):
    return json.dumps(schema, separators=(',', ':'), ensure_ascii=True).replace("'", "''")


def build():
    path = ROOT / 'sql/mysql/compact/baseline/30-operations.sql'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r"(CONSTRAINT ck_workflow_kind CHECK \(kind IN \()'", r"\1'BUSINESS_COMMAND','", text, count=1) if "'BUSINESS_COMMAND','CONVERSATION_INPUT'" not in text else text
    if ' operation_resource_type ' not in text:
        anchor = ' operation_scope VARCHAR(16)'
        text = text.replace(anchor, " operation_resource_type VARCHAR(64) COLLATE utf8mb4_bin GENERATED ALWAYS AS\n        (CASE WHEN kind='OPERATIONS' THEN CASE WHEN payload_version=1 THEN 'OPERATIONS' ELSE JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.resourceType')) END ELSE NULL END) VIRTUAL,\n" + anchor, 1)
    text = text.replace('uk_audit_operation_receipt (actor_user_id,operation_domain,action,resource_id,request_id,operation_result)',
                        'uk_audit_operation_receipt (actor_user_id,operation_domain,operation_resource_type,action,resource_id,request_id,operation_result)')
    if ' operation_actor_key ' not in text:
        text = text.replace(' operation_resource_type VARCHAR(64)',
            " operation_actor_key VARCHAR(96) COLLATE utf8mb4_bin GENERATED ALWAYS AS\n"
            "        (CASE WHEN kind='OPERATIONS' THEN CASE WHEN payload_version=3 THEN CONCAT('SYSTEM:',JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.component'))) ELSE CONCAT('USER:',actor_user_id) END ELSE NULL END) VIRTUAL,\n operation_resource_type VARCHAR(64)", 1)
    text = text.replace('uk_audit_operation_receipt (actor_user_id,operation_domain,operation_resource_type,action,resource_id,request_id,operation_result)',
                        'uk_audit_operation_receipt (operation_actor_key,operation_domain,operation_resource_type,action,resource_id,request_id,operation_result)')
    if 'ix_audit_operation_resource ' not in text:
        text = text.replace(' KEY ix_audit_operation_domain (kind,operation_domain,id),',
                            ' KEY ix_audit_operation_domain (kind,operation_domain,id),\n KEY ix_audit_operation_resource (kind,operation_domain,operation_resource_type,resource_id,id),')
    if 'ix_audit_operation_time ' not in text:
        text = text.replace(' KEY ix_audit_operation_domain (kind,operation_domain,id),',
                            ' KEY ix_audit_operation_domain (kind,operation_domain,id),\n KEY ix_audit_operation_time (kind,occurred_at,id),')
    text = re.sub(r'(CONSTRAINT ck_audit_operations CHECK [^\n]*?)payload_version=1 AND', r'\1payload_version IN (1,2) AND', text, count=1)
    old_actor = 'owner_user_id IS NOT NULL AND actor_user_id IS NOT NULL AND owner_user_id=actor_user_id'
    actor = "((payload_version IN (1,2) AND " + old_actor + ") OR (payload_version=3 AND owner_user_id IS NULL AND actor_user_id IS NULL AND operation_scope='ENTERPRISE'))"
    text = re.sub(r'(CONSTRAINT ck_audit_operations CHECK [^\n]*?)' + re.escape(old_actor),
                  lambda match: match.group(1) + actor, text, count=1) if actor not in text else text
    text = re.sub(r'(CONSTRAINT ck_audit_operations CHECK [^\n]*?)payload_version IN \(1,2\) AND operation_scope',
                  r'\1payload_version IN (1,2,3) AND operation_scope', text, count=1)
    scalar = {'anyOf': [bounded('string', 512), {'type': 'number'}, {'type': 'boolean'}, {'type': 'null'}]}
    revision = nullable({'type': 'integer', 'minimum': 0, 'maximum': 9223372036854775807})
    base = {'scope': {'enum': ['ENTERPRISE', 'PRIVATE']}, 'domain': bounded('string', 48), 'result': bounded('string', 40), 'resourceVersion': revision}
    # V1 accepted every signed Java Long. Negative legacy revisions remain valid.
    old_base = dict(base, resourceVersion=nullable({'type': 'integer', 'minimum': -9223372036854775808,
                                                  'maximum': 9223372036854775807}))
    v1 = object_schema(dict(old_base, legacyId=nullable(bounded('string', 128)), legacyCreatedAt=nullable(bounded('string', 128))))
    change = object_schema({'field': bounded('string', 64), 'label': bounded('string', 80),
                            'operation': {'enum': ['ADD', 'REMOVE', 'REPLACE', 'CHANGED']},
                            'before': scalar, 'after': scalar, 'valueType': nullable(bounded('string', 32)), 'redacted': {'type': 'boolean'}})
    # MySQL validates draft-04; if/then belongs to a later draft and must not be relied upon.
    change['anyOf'] = [{'properties': {'redacted': {'enum': [False]}}},
                       {'properties': {'redacted': {'enum': [True]}, 'before': {'type': 'null'},
                                       'after': {'type': 'null'}, 'operation': {'enum': ['CHANGED']}}}]
    v2 = object_schema(dict(base, resourceType=bounded('string', 64), actorUsername=bounded('string', 128),
                           actorDisplayName=nullable(bounded('string', 128)), actorRole={'enum': ['SUPERVISOR', 'INSPECTOR']},
                           beforeVersion=revision, causationRequestId=bounded('string', 128),
                           changes={'type': 'array', 'maxItems': 64, 'items': change}))
    initiator = object_schema({'userId': nullable({'type': 'integer', 'minimum': 1, 'maximum': 9223372036854775807}),
                              'username': nullable(dict(bounded('string', 128), minLength=1))})
    initiator['anyOf'] = [{'properties': {'userId': {'type': 'integer'}}}, {'properties': {'username': {'type': 'string'}}}]
    v3 = object_schema(dict(base, scope={'enum': ['ENTERPRISE']}, result={'enum': ['APPLIED']},
                           resourceVersion={'type': 'integer', 'minimum': 0, 'maximum': 9223372036854775807},
                           resourceType=bounded('string', 64), source={'enum': ['SYSTEM']},
                           component={'enum': ['DETECTION_WORKER', 'IMAGE_DETECTION_ASYNC', 'IMAGE_DETECTION']},
                           sourceEventId=dict(bounded('string', 128), minLength=1), initiator=nullable(initiator),
                           beforeVersion=revision, causationRequestId=bounded('string', 128),
                           changes={'type': 'array', 'minItems': 1, 'maxItems': 64, 'items': change}))
    audit = " CONSTRAINT ck_audit_operation_versions CHECK (kind<>'OPERATIONS' OR COALESCE((payload_version=1 AND JSON_SCHEMA_VALID('%s',CAST(payload_json AS JSON))) OR (payload_version=2 AND OCTET_LENGTH(payload_json)<=262144 AND JSON_SCHEMA_VALID('%s',CAST(payload_json AS JSON)) AND BINARY JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.causationRequestId'))=BINARY request_id) OR (payload_version=3 AND OCTET_LENGTH(payload_json)<=262144 AND JSON_SCHEMA_VALID('%s',CAST(payload_json AS JSON)) AND BINARY JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.sourceEventId'))=BINARY request_id AND BINARY JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.causationRequestId'))=BINARY request_id AND (JSON_TYPE(JSON_EXTRACT(payload_json,'$.beforeVersion'))='NULL' OR CAST(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.resourceVersion')) AS DECIMAL(20,0))=CAST(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.beforeVersion')) AS DECIMAL(20,0))+1)),0)=1)," % (schema_sql(v1), schema_sql(v2), schema_sql(v3))
    text = re.sub(r'^ CONSTRAINT ck_audit_operation_versions CHECK .*\n', '', text, flags=re.M)
    text = text.replace(' CONSTRAINT ck_audit_operations CHECK', audit + '\n CONSTRAINT ck_audit_operations CHECK', 1)
    command = object_schema({'domain': bounded('string', 48), 'action': bounded('string', 64)})
    clause = " CONSTRAINT ck_workflow_business_command CHECK (kind<>'BUSINESS_COMMAND' OR COALESCE((owner_user_id>0 AND actor_user_id IS NOT NULL AND actor_user_id=owner_user_id AND idempotency_scope=CONCAT('OWNER:',owner_user_id) AND resource_type IS NOT NULL AND resource_type='BUSINESS_COMMAND' AND resource_id IS NULL AND resource_revision IS NULL AND payload_version=1 AND request_sha256 REGEXP '^[a-f0-9]{64}$' AND JSON_SCHEMA_VALID('%s',CAST(payload_json AS JSON)) AND status IN ('STARTED','SUCCEEDED') AND parent_workflow_id IS NULL AND session_id IS NULL AND run_id IS NULL AND claim_token IS NULL AND expires_at IS NULL AND legacy_source IS NULL AND legacy_key IS NULL AND legacy_clock_json IS NULL AND ((status='STARTED' AND revision=0 AND finished_at IS NULL AND result_json IS NULL) OR (status='SUCCEEDED' AND revision=1 AND finished_at IS NOT NULL AND result_version=1 AND result_json IS NOT NULL AND result_sha256=SHA2(result_json,256)))),0)=1)," % schema_sql(command)
    text = re.sub(r'^ CONSTRAINT ck_workflow_business_command CHECK .*\n', '', text, flags=re.M)
    text = text.replace(' CONSTRAINT ck_workflow_kind CHECK', clause + '\n CONSTRAINT ck_workflow_kind CHECK', 1)
    path.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    build()
