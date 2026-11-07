"""Author closed MySQL JSON schemas from existing workbench records; never execute SQL.

The generated checks enforce the existing Java protocol, not an alternate runtime
representation. Draft 4 schemas are inline constants as required by MySQL 8.4.
"""
from pathlib import Path
from copy import deepcopy
import json
import re

ROOT = Path(__file__).resolve().parents[2]
JAVA = ROOT / 'doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/workbench/WorkbenchProtocol.java'
BASELINE = ROOT / 'sql/mysql/compact/baseline/30-operations.sql'
BOUNDS = {'parentId': 64, 'parentTaskId': 128, 'logicalTaskId': 128, 'runId': 128,
          'instance': 36, 'specialist': 100, 'role': 24, 'modelId': 160,
          'modelDefault': 160, 'callId': 160}
MEASUREMENTS = {'modelConfigVersion', 'durationMs', 'firstContentMs', 'inputTokens',
                'outputTokens', 'cachedTokens', 'systemTokens', 'toolsTokens',
                'messageTokens', 'beforeMessages', 'beforeChars', 'afterMessages', 'afterChars'}


def nullable(schema):
    return {'anyOf': [schema, {'type': 'null'}]}


def object_schema(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False}


def field_schema(kind, name):
    if kind == 'String':
        result = {'type': 'string'}
        if name in BOUNDS:
            result['maxLength'] = BOUNDS[name]
        return nullable(result)
    if kind in ('Long', 'Integer'):
        return nullable({'type': 'integer', 'minimum': 0 if name in MEASUREMENTS else (-9223372036854775808 if kind == 'Long' else -2147483648),
                         'maximum': 9223372036854775807 if kind == 'Long' else 2147483647})
    if kind == 'Boolean':
        return nullable({'type': 'boolean'})
    if kind == 'Object' and name == 'answer':
        return {'anyOf': [{'type': 'null'}, {'type': 'string'},
                          {'type': 'array', 'items': {'type': 'string'}}]}
    if kind == 'List<String>':
        result = {'type': 'array', 'items': {'type': 'string'}}
        if name == 'followups':
            result['maxItems'] = 4
        return nullable(result)
    if kind == 'List<TaskV1>':
        task = object_schema({'title': {'type': 'string'},
                              'status': {'enum': ['pending', 'in_progress', 'completed', 'failed']},
                              'evidenceCallId': nullable({'type': 'string'}),
                              'evidenceRunId': nullable({'type': 'string'})})
        return nullable({'type': 'array', 'maxItems': 30, 'items': task})
    if kind == 'List<ModelChangeV1>':
        return nullable({'type': 'array', 'items': object_schema({
            'fromVersion': nullable({'type': 'integer'}), 'fromModel': nullable({'type': 'string'}),
            'toVersion': nullable({'type': 'integer'}), 'toModel': nullable({'type': 'string'}),
            'previousRunId': nullable({'type': 'string'})})})
    if kind == 'List<AgentWorkbenchApi.Item>':
        return {'type': 'array', 'items': {'type': 'object'}}
    raise ValueError('Unreviewed workbench protocol field: ' + kind + ' ' + name)


def main():
    java = JAVA.read_text(encoding='utf-8-sig')
    classes = dict(re.findall(r'@JsonSubTypes\.Type\(value=(\w+)\.class,name="([A-Z_]+)"\)', java))
    records = dict(re.findall(r'record\s+(\w+)\(([^()]*)\)\s+implements\s+ItemData', java, re.S))
    if len(classes) != 14 or set(classes) - records.keys():
        raise ValueError('Workbench protocol variants changed; review the generated schema vocabulary')
    checks = []
    legacy = nullable(object_schema({name: {'type': 'string'} for name in
                                    ('payloadJson', 'createdAt', 'updatedAt', 'sourceUtcOffset')}))
    for record, variant in classes.items():
        fields = []
        for item in records[record].split(','):
            parts = item.strip().rsplit(None, 1)
            if len(parts) != 2:
                raise ValueError('Unrecognized workbench record declaration')
            fields.append(parts)
        data = {'type': {'enum': [variant]}}
        data.update({name: field_schema(kind, name) for kind, name in fields})
        if variant == 'QUESTION':
            data['questionType'] = {'enum': ['TEXT', 'SINGLE', 'MULTIPLE']}
            data['options'] = {'type': 'array', 'items': {'type': 'string'}}
        if variant == 'TURN':
            data['throughMessageId'] = {'type': 'integer', 'minimum': 1, 'maximum': 9223372036854775807}
        schema = object_schema({'schemaVersion': {'enum': [1]}, 'data': object_schema(data),
                                'presentFields': {'type': 'array', 'uniqueItems': True,
                                                  'items': {'enum': [name for _, name in fields]}},
                                'legacy': legacy})
        encoded = json.dumps(schema, ensure_ascii=True, separators=(',', ':')).replace('\\', '\\\\').replace("'", "''")
        unknown = deepcopy(schema)
        unknown['properties']['schemaVersion'] = {'enum': [2]}
        unknown['properties']['legacy'] = object_schema({name: {'type': 'string'} for name in
            ('payloadJson', 'createdAt', 'updatedAt')})
        unknown['properties']['legacy']['required'].append('sourceUtcOffset')
        unknown['properties']['legacy']['properties']['sourceUtcOffset'] = {'type': 'null'}
        unknown_encoded = json.dumps(unknown, ensure_ascii=True, separators=(',', ':')).replace('\\', '\\\\').replace("'", "''")
        checks.append(f" CONSTRAINT ck_workbench_json_{variant.lower()} CHECK (kind<>'WORKBENCH_{variant}' OR ((legacy_clock_json IS NULL AND COALESCE(JSON_SCHEMA_VALID('{encoded}',CAST(payload_json AS JSON)),0)=1) OR (legacy_clock_json IS NOT NULL AND COALESCE(JSON_SCHEMA_VALID('{unknown_encoded}',CAST(payload_json AS JSON)),0)=1))),")
    start = ' -- BEGIN GENERATED WORKBENCH JSON CHECKS'
    end = ' -- END GENERATED WORKBENCH JSON CHECKS'
    section = start + '\n' + '\n'.join(checks) + '\n' + end + '\n'
    for path in (BASELINE, ROOT / 'sql/mysql/compact/baseline-fixed-clock/30-operations.sql'):
        sql = path.read_text(encoding='utf8')
        if start in sql:
            sql = re.sub(re.escape(start) + r'.*?' + re.escape(end) + r'\n', lambda _: section, sql, flags=re.S)
        else:
            sql = re.sub(r'(?m)^ CONSTRAINT ck_workbench_json_[a-z_]+ CHECK .*\n', '', sql)
            anchor = ' CONSTRAINT ck_workflow_workbench_command CHECK'
            if sql.count(anchor) != 1:
                raise ValueError('Expected one workbench constraint insertion point')
            sql = sql.replace(anchor, section + anchor)
        path.write_bytes(sql.encode('utf8'))
    print(json.dumps({'status': 'SOURCE_AUTHORED_NOT_SQL_EXECUTED', 'workbenchJsonChecks': len(checks)}))


if __name__ == '__main__':
    main()
