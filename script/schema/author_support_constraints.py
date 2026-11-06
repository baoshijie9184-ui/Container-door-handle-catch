"""Author remaining compact protocol invariants offline, without executing SQL."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[2]


def relax(sql, name, exception):
    pattern = re.compile(r'(?m)^(\s*CONSTRAINT ' + re.escape(name) + r' CHECK \()(.*)(\),?\s*)$')
    found = pattern.search(sql)
    if not found:
        raise ValueError('Missing source invariant: ' + name)
    if exception in found.group(2):
        return sql
    return sql[:found.start()] + found.group(1) + '(' + found.group(2) + ') OR (' + exception + ')' + found.group(3) + sql[found.end():]


def literal(value):
    return "'" + value.replace('\\', '\\\\').replace("'", "''") + "'"


def schema(properties):
    return {'type': 'object', 'additionalProperties': False, 'required': list(properties), 'properties': properties}


def string(width=None, nullable=False):
    value = {'type': ['string', 'null'] if nullable else 'string'}
    if width:
        value['maxLength'] = width
    return value


def integer(nullable=False):
    return {'type': ['integer', 'null'] if nullable else 'integer', 'minimum': -9223372036854775808, 'maximum': 9223372036854775807}


def validated(column, properties):
    return 'COALESCE(JSON_SCHEMA_VALID(' + literal(json.dumps(schema(properties), separators=(',', ':'))) + ',' + column + '),0)=1'


def block(sql, table, label, additions):
    found = re.search(r'(CREATE TABLE ' + table + r' \()(.*?)(\n\) ENGINE=)', sql, re.S)
    if not found:
        raise ValueError('Missing target table: ' + table)
    body = re.sub(r'[ \t\r\n]*,\r?\n -- BEGIN ' + label + r'.*?\n -- END ' + label, '', found.group(2), flags=re.S).rstrip()
    # Separators must not be appended to a preceding SQL line comment.
    body = re.sub(r'(?m)^(\s*-- END GENERATED [^\r\n,]+),\s*$', r'\1\n ,', body)
    body += '\n ,\n -- BEGIN ' + label + '\n ' + ',\n '.join(additions) + '\n -- END ' + label
    return sql[:found.start()] + found.group(1) + body + found.group(3) + sql[found.end():]


def main():
    path = ROOT / 'sql/mysql/compact/baseline/30-operations.sql'
    sql = path.read_text(encoding='utf8')
    fingerprint = ("namespace='DETECTION_FINGERPRINT' AND owner_id=0 AND scope_key REGEXP '^[a-f0-9]{64}$' "
                   "AND payload_version=1 AND payload_json IS NOT NULL AND " + validated('payload_json', {
                       'originalId': {'type': 'integer', 'minimum': 1, 'maximum': 9223372036854775807},
                       'sourceOwnerKey': string(64, True)}))
    owner_locks = "namespace IN ('RESEARCH_STORAGE','SKILL_DOWNLOAD') AND owner_id>0 AND scope_key='' AND revision=0 AND payload_json IS NULL AND state_code IS NULL AND current_ref IS NULL AND counter_value IS NULL"
    sql = relax(sql, 'ck_runtime_updated', owner_locks)
    sql = block(sql, 'runtime_state', 'GENERATED SUPPORT', [
        "CONSTRAINT ck_runtime_fingerprint CHECK (namespace<>'DETECTION_FINGERPRINT' OR COALESCE((" + fingerprint + " AND revision<=2147483647 AND state_code IS NOT NULL AND CHAR_LENGTH(state_code)<=32 AND (current_ref IS NULL OR CHAR_LENGTH(current_ref)<=64)),0)=1)",
        "CONSTRAINT ck_runtime_digest_control CHECK (namespace<>'DIGEST_CONTROL' OR (owner_id=0 AND scope_key='1' AND revision=0 AND payload_json IS NULL AND state_code IS NULL AND current_ref IS NULL AND counter_value IS NULL AND created_at IS NULL))"])
    imported = "legacy_key IS NOT NULL AND ((kind='DIGEST_RUN' AND BINARY legacy_source=BINARY 'quality_digest_run') OR (kind='DIGEST_COMMAND' AND BINARY legacy_source=BINARY 'quality_digest_command'))"
    sql = relax(sql, 'ck_workflow_updated_time', imported)
    sql = relax(sql, 'ck_workflow_receipt', "kind='DIGEST_COMMAND' AND status='COMPLETED' AND claim_token IS NULL AND lease_expires_at IS NULL AND legacy_key IS NOT NULL AND BINARY legacy_source=BINARY 'quality_digest_command' AND digest_legacy_row_json IS NOT NULL")
    run = {'id': integer(), 'run_id': string(64), 'schedule_id': string(64), 'owner_user_id': integer(),
           'request_key': string(100), 'scheduled_for': string(26), 'report_date': string(10), 'status': string(16),
           'claim_token': string(64, True), 'lease_until': string(26, True), 'snapshot_json': string(nullable=True),
           'snapshot_sha256': string(64, True), 'error_code': string(64, True), 'created_at': string(26), 'finished_at': string(26, True)}
    command = {'actor_user_id': integer(), 'request_id': string(64), 'request_sha256': string(64), 'schedule_id': string(64), 'created_at': string(26)}
    sql = block(sql, 'workflow_instance', 'GENERATED DIGEST', [
        'digest_legacy_row_json LONGTEXT NULL',
        "digest_scope VARCHAR(160) COLLATE utf8mb4_0900_ai_ci GENERATED ALWAYS AS (CASE WHEN kind IN ('DIGEST_COMMAND','DIGEST_RUN') THEN idempotency_scope ELSE NULL END) VIRTUAL",
        "digest_request_id VARCHAR(128) COLLATE utf8mb4_0900_ai_ci GENERATED ALWAYS AS (CASE WHEN kind IN ('DIGEST_COMMAND','DIGEST_RUN') THEN request_id ELSE NULL END) VIRTUAL",
        "digest_schedule_id VARCHAR(180) COLLATE utf8mb4_0900_ai_ci GENERATED ALWAYS AS (CASE WHEN kind='DIGEST_RUN' THEN resource_id ELSE NULL END) VIRTUAL",
        "digest_workflow_id VARCHAR(64) COLLATE utf8mb4_0900_ai_ci GENERATED ALWAYS AS (CASE WHEN kind='DIGEST_RUN' THEN workflow_id ELSE NULL END) VIRTUAL",
        'UNIQUE KEY uk_workflow_digest_request(kind,digest_scope,digest_request_id)',
        'UNIQUE KEY uk_workflow_digest_external(digest_workflow_id)',
        'KEY ix_workflow_digest_schedule(kind,digest_schedule_id,owner_user_id,id)',
        "CONSTRAINT ck_workflow_digest_raw CHECK (COALESCE(((digest_legacy_row_json IS NULL AND NOT(COALESCE((" + imported + "),0)=1)) OR (digest_legacy_row_json IS NOT NULL AND legacy_key IS NOT NULL AND ((kind='DIGEST_RUN' AND BINARY legacy_source=BINARY 'quality_digest_run' AND " + validated('digest_legacy_row_json', run) + ") OR (kind='DIGEST_COMMAND' AND BINARY legacy_source=BINARY 'quality_digest_command' AND " + validated('digest_legacy_row_json', command) + ')))),0)=1)',
        "CONSTRAINT ck_workflow_digest_payload CHECK ((kind NOT IN ('DIGEST_RUN','DIGEST_COMMAND')) OR COALESCE((payload_version=1 AND resource_type='SCHEDULE' AND resource_id IS NOT NULL AND CHAR_LENGTH(resource_id)<=64 AND ((kind='DIGEST_RUN' AND " + validated('payload_json', {'scheduleId': string(64), 'scheduledFor': string(29), 'reportDate': string(10)}) + " AND effective_date IS NOT NULL AND scheduled_for IS NOT NULL AND (status='RUNNING' OR (claim_token IS NULL AND lease_expires_at IS NULL))) OR (kind='DIGEST_COMMAND' AND " + validated('payload_json', {'scheduleId': string(64)}) + '))),0)=1)'])
    sql = sql.replace('plan_id VARCHAR(64) COLLATE utf8mb4_bin NOT NULL', 'plan_id VARCHAR(64) COLLATE utf8mb4_0900_ai_ci NOT NULL')
    sql = block(sql, 'audit_event', 'GENERATED DIGEST', [
        'digest_legacy_detail_json LONGTEXT NULL',
        "CONSTRAINT ck_audit_digest_raw CHECK (COALESCE(((digest_legacy_detail_json IS NULL AND NOT(kind='DIGEST' AND COALESCE(BINARY legacy_source=BINARY 'quality_digest_audit',0)=1)) OR (digest_legacy_detail_json IS NOT NULL AND kind='DIGEST' AND BINARY legacy_source=BINARY 'quality_digest_audit' AND legacy_key IS NOT NULL AND JSON_VALID(digest_legacy_detail_json))),0)=1)",
        "CONSTRAINT ck_audit_digest_payload CHECK (kind<>'DIGEST' OR (payload_version=1 AND " + validated('payload_json', {'cron': string(100, True), 'enabled': {'type': ['boolean', 'null']}, 'runId': string(64, True), 'reportDate': string(10, True), 'format': string(16, True), 'snapshotSha256': string(64, True)}) + '))'])
    path.write_text(sql, encoding='utf8', newline='\n')
    print(json.dumps({'status': 'SOURCE_AUTHORED_NOT_SQL_EXECUTED'}))


if __name__ == '__main__':
    main()
