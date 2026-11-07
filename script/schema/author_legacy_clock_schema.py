"""Author strict historical clock DDL/guards from the reviewed typed source map."""
from __future__ import annotations

import json
import re

from author_legacy_clock_copy import (COPIES, PROTOCOL, ROOT, TABLE_FILES, catalog,
                                      parsed_insert, q)
from build_compact_schema import split_top_level, without_comments


def object_schema(properties):
    return {'type': 'object', 'additionalProperties': False,
            'required': list(properties), 'properties': properties}


def scalar(column):
    kind = column['type'].upper()
    if re.match(r'(?:TINYINT|SMALLINT|MEDIUMINT|INT|INTEGER|BIGINT)\b', kind):
        unsigned = 'UNSIGNED' in kind
        return {'type': 'integer', 'minimum': 0 if unsigned else -9223372036854775808,
                'maximum': 18446744073709551615 if unsigned else 9223372036854775807}
    return {'type': 'string'}


def source_schema(name, source):
    key = object_schema({column: scalar(source['columns'][column]) for column in source['primaryKey']})
    times = object_schema({column: {'type': ['string', 'null'],
                                   'pattern': r'^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?$'}
                           for column, value in source['columns'].items()
                           if value['type'].upper().startswith(('DATETIME', 'TIMESTAMP'))})
    digest = {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}
    return object_schema({'protocol': {'enum': [PROTOCOL]}, 'status': {'enum': ['UNRESOLVED']},
                          'sourceTable': {'enum': [name]}, 'sourceKey': key,
                          'sourceSnapshotSha256': digest, 'sourceRowSha256': digest,
                          'sourceWallTimes': times})


def source_key_expression(source, alias, expression):
    pattern = r'(?<![A-Za-z0-9_])' + re.escape(alias) + r'\.`?([a-z_]+)`?'
    columns = set(re.findall(pattern, expression))
    if not columns or not columns <= set(source['primaryKey']):
        return None
    def replace(match):
        column = match[1]
        value = "JSON_UNQUOTE(JSON_EXTRACT(legacy_clock_json,'$.sourceKey." + column + "'))"
        if scalar(source['columns'][column])['type'] == 'integer':
            value = 'CAST(' + value + ' AS DECIMAL(20,0))'
        return value
    return re.sub(pattern, replace, expression)


def routes(sources):
    result = {table: [] for table in TABLE_FILES}
    for filename in COPIES:
        text = (ROOT / 'sql/mysql/compact/copy-fixed-clock' / filename).read_text('utf8')
        for statement in split_top_level(without_comments(text), ';'):
            parsed = parsed_insert(statement)
            if not parsed:
                continue
            table, columns, expressions, _, origin, alias, _, _ = parsed
            if not any(v['type'].upper().startswith(('DATETIME', 'TIMESTAMP')) for v in sources[origin]['columns'].values()):
                continue
            mapping = dict(zip(columns, expressions))
            checks = ["BINARY JSON_UNQUOTE(JSON_EXTRACT(legacy_clock_json,'$.sourceTable'))=BINARY " + q(origin)]
            for discriminator in ('kind', 'asset_kind', 'link_kind', 'namespace', 'legacy_source'):
                value = mapping.get(discriminator)
                if value and re.fullmatch(r"'[A-Za-z_]+\'", value):
                    checks.append('BINARY ' + discriminator + '=BINARY ' + value)
            for column, original in mapping.items():
                if column not in ('created_at', 'updated_at', 'occurred_at', 'payload_json', 'manifest_json'):
                    value = source_key_expression(sources[origin], alias, original)
                    if value:
                        checks.append('BINARY ' + column + '<=>BINARY ' + value)
            result[table].append((origin, ' AND '.join('(' + value + ')' for value in checks)))
    kinds = ('EXECUTION', 'CHILD', 'PLAN', 'QUESTION', 'TASKS', 'TOOL', 'CHECKPOINT',
             'MODEL_SELECTION', 'TURN', 'FORK_SNAPSHOT', 'ARTIFACT', 'USAGE', 'CONTEXT', 'TOOL_TIMING')
    common = "BINARY JSON_UNQUOTE(JSON_EXTRACT(legacy_clock_json,'$.sourceTable'))=BINARY 'agent_workbench_item'"
    result['workflow_instance'].append(('agent_workbench_item', '(' + common + ') AND (kind IN ('
        + ','.join(q('WORKBENCH_' + kind) for kind in kinds) + ") OR kind='WORKBENCH_LOGICAL_TASK') AND legacy_key IS NOT NULL AND BINARY legacy_key=BINARY JSON_UNQUOTE(JSON_EXTRACT(legacy_clock_json,'$.sourceKey.id'))"))
    result['audit_event'].append(('agent_workbench_audit', "kind='WORKBENCH' AND legacy_source='agent_workbench_audit' AND "
        "BINARY JSON_UNQUOTE(JSON_EXTRACT(legacy_clock_json,'$.sourceTable'))=BINARY 'agent_workbench_audit' AND BINARY legacy_key=BINARY JSON_UNQUOTE(JSON_EXTRACT(legacy_clock_json,'$.sourceKey.id'))"))
    return result


def replace_checks(body, table):
    fields = list(split_top_level(body, ','))
    columns = {}
    for field in fields:
        match = re.match(r'`?([a-z_]+)`?\s+(DATETIME(?:\([0-9]+\))?|TIMESTAMP(?:\([0-9]+\))?)', field, re.I)
        if match:
            columns[match[1]] = match[2]
    nullable = []
    output = []
    for field in fields:
        match = re.match(r'`?([a-z_]+)`?\s+', field)
        name = match[1] if match else None
        if name in columns and re.search(r'\bNOT NULL\b', field, re.I):
            field = re.sub(r'\bNOT NULL\b', 'NULL', field, count=1, flags=re.I)
            nullable.append(name)
        if re.match(r'CONSTRAINT\s+\w+\s+CHECK\s*\(', field, re.I):
            # Only the time atom is relaxed. Ownership, digests, versions,
            # discriminator and business-state requirements remain in force.
            for column in columns:
                if column in ('legacy_created_at', 'mcp_source_created_at', 'mcp_source_updated_at'):
                    continue
                field = re.sub(r'(?<![A-Za-z0-9_.])' + re.escape(column) + r'\s+IS\s+NOT\s+NULL',
                    '(' + column + ' IS NOT NULL OR legacy_clock_json IS NOT NULL)', field, flags=re.I)
            if field.startswith('CONSTRAINT ck_content_revision_workspace '):
                marker = 'manifest_json IS NOT NULL AND JSON_LENGTH(manifest_json)=3'
                position = field.find(marker)
                if position < 0:
                    raise ValueError('Workspace v1 manifest contract changed')
                # The last two parentheses close the kind branch and CHECK.
                old = field[position:-2]
                schema = object_schema({'protocolVersion': {'enum': [2]}, 'folder': {'type': 'string', 'maxLength': 32},
                    'createdAtSource': {'type': 'string'}, 'clockStatus': {'enum': ['UNRESOLVED']}})
                v2 = "legacy_clock_json IS NOT NULL AND COALESCE(JSON_SCHEMA_VALID(" + q(json.dumps(schema, separators=(',', ':')))
                v2 += ",CAST(manifest_json AS JSON)),0)=1 AND BINARY JSON_UNQUOTE(JSON_EXTRACT(legacy_clock_json,'$.sourceTable'))=BINARY 'agent_workspace_file' AND BINARY JSON_UNQUOTE(JSON_EXTRACT(manifest_json,'$.createdAtSource'))=BINARY JSON_UNQUOTE(JSON_EXTRACT(legacy_clock_json,'$.sourceWallTimes.created_at'))"
                field = field[:position] + '((legacy_clock_json IS NULL AND ' + old + ') OR (' + v2 + '))))'
            if field.startswith('CONSTRAINT ck_content_link_workspace_clock '):
                old = field[field.index('CHECK (') + 7:-1]
                extra = "legacy_clock_json IS NOT NULL AND legacy_created_at IS NOT NULL AND legacy_utc_offset IS NULL AND legacy_id IS NOT NULL AND ((link_kind='WORKSPACE_FILE' AND legacy_source='agent_workspace_file_ref') OR (link_kind='WORKSPACE_BUSINESS' AND legacy_source='agent_workspace_business_ref'))"
                field = field[:field.index('CHECK (') + 7] + '(' + old + ') OR (' + extra + '))'
        output.append(field)
    if 'legacy_clock_json' not in [re.match(r'`?([a-z_]+)`?', field)[1] for field in output if re.match(r'`?([a-z_]+)`?', field)]:
        output.insert(0, 'legacy_clock_json JSON NULL')
    for name in nullable:
        output.append('CONSTRAINT ck_legacy_' + table + '_' + name + ' CHECK (' + name + ' IS NOT NULL OR legacy_clock_json IS NOT NULL)')
    for name in ('legacy_utc_offset', 'mcp_source_utc_offset'):
        if any(re.match(name + r'\s+', field) for field in output):
            output.append('CONSTRAINT ck_legacy_' + table + '_' + name + ' CHECK (legacy_clock_json IS NULL OR ' + name + ' IS NULL)')
    return output


def build():
    sources = catalog(); bindings = routes(sources)
    generated = {}
    for filename in sorted(set(TABLE_FILES.values())):
        path = ROOT / 'sql/mysql/compact/baseline' / filename
        source = ROOT / 'sql/mysql/compact/baseline-fixed-clock' / filename
        statements = list(split_top_level(without_comments(source.read_text('utf8')), ';'))
        rendered = []
        for statement in statements:
            match = re.fullmatch(r'(CREATE TABLE\s+([a-z_]+)\s*)\((.*)\)(\s*ENGINE.*)', statement, re.I | re.S)
            if not match or match[2] not in TABLE_FILES:
                rendered.append(statement); continue
            table = match[2]
            fields = replace_checks(match[3], table)
            fields = [field for field in fields if not re.match(r'CONSTRAINT ck_legacy_clock_(?:shape|binding)_', field)]
            names = sorted({name for name, _ in bindings[table]})
            schema = {'anyOf': [source_schema(name, sources[name]) for name in names]}
            fields.append('CONSTRAINT ck_legacy_clock_shape_' + table + ' CHECK (legacy_clock_json IS NULL OR COALESCE(JSON_SCHEMA_VALID('
                + q(json.dumps(schema, separators=(',', ':'))) + ',legacy_clock_json),0)=1)')
            conditions = sorted({condition for _, condition in bindings[table]})
            fields.append('CONSTRAINT ck_legacy_clock_binding_' + table + ' CHECK (legacy_clock_json IS NULL OR COALESCE(('
                + ' OR '.join('(' + condition + ')' for condition in conditions) + '),0)=1)')
            rendered.append(match[1] + '(\n ' + ',\n '.join(fields) + '\n)' + match[4])
            guard_file = '35-legacy-clock-' + table.replace('_', '-') + '.sql'
            triggers = []
            for event in ('UPDATE', 'DELETE'):
                name = 'compact_legacy_clock_' + table + '_' + event.lower()
                condition = ('NOT(CAST(NEW.legacy_clock_json AS CHAR CHARACTER SET utf8mb4)<=>CAST(OLD.legacy_clock_json AS CHAR CHARACTER SET utf8mb4))'
                             if event == 'UPDATE' else 'OLD.legacy_clock_json IS NOT NULL')
                triggers.append('CREATE TRIGGER ' + name + '\nBEFORE ' + event + ' ON ' + table + ' FOR EACH ROW\nBEGIN\n    IF ' + condition
                    + " THEN\n        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Original legacy clock evidence must be retained unchanged';\n    END IF;\nEND$$")
            generated[ROOT / 'sql/mysql/compact/baseline' / guard_file] = '\n\n'.join(triggers) + '\n'
        generated[path] = '-- Clock protocol authored by author_legacy_clock_schema.py; ECS validation required.\n' + ';\n\n'.join(rendered) + ';\n'
    parents = {
        'model_management': ("EXISTS(SELECT 1 FROM audit_event e WHERE e.detection_model_id=OLD.model_id AND e.legacy_clock_json IS NOT NULL)", 'NOT(NEW.model_id<=>OLD.model_id)'),
        'chat_session': ("EXISTS(SELECT 1 FROM workflow_instance w WHERE w.chat_action_session_id=OLD.session_id AND w.legacy_clock_json IS NOT NULL)", 'NOT(BINARY NEW.session_id<=>BINARY OLD.session_id)'),
        'users': ("EXISTS(SELECT 1 FROM chat_session s JOIN workflow_instance w ON w.chat_action_session_id=s.session_id WHERE (s.user_id=OLD.id OR s.username=OLD.username) AND w.legacy_clock_json IS NOT NULL)", 'NOT(NEW.id<=>OLD.id) OR NOT(BINARY NEW.username<=>BINARY OLD.username)'),
    }
    for table, (references, changed) in parents.items():
        body = []
        for event in ('UPDATE', 'DELETE'):
            condition = '(' + references + ')' + (' AND (' + changed + ')' if event == 'UPDATE' else '')
            body.append('CREATE TRIGGER compact_legacy_clock_parent_' + table + '_' + event.lower()
                + '\nBEFORE ' + event + ' ON ' + table + ' FOR EACH ROW\nBEGIN\n    IF ' + condition
                + " THEN\n        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='A cascade would remove or rekey original legacy clock evidence';\n    END IF;\nEND$$")
        generated[ROOT / 'sql/mysql/compact/baseline' / ('35-legacy-clock-parent-' + table.replace('_', '-') + '.sql')] = '\n\n'.join(body) + '\n'
    return generated, bindings


def main():
    generated, bindings = build()
    for path, value in generated.items():
        path.write_bytes(value.encode('utf8'))
    contract = {'protocol': PROTOCOL, 'status': 'SOURCE_AUTHORED_NOT_ECS_VALIDATED',
        'algorithm': 'MYSQL_JSON_SHA256_V1', 'tables': {table: sorted({name for name, _ in rows}) for table, rows in bindings.items()},
        'guardResources': {path.name: {'table': re.search(r' ON ([a-z_]+) FOR EACH ROW', value)[1],
            'triggers': re.findall(r'CREATE TRIGGER ([a-z_]+)', value)}
                          for path, value in generated.items() if path.name.startswith('35-legacy-clock-')}}
    (ROOT / 'docs/database/legacy-clock-protocol.json').write_bytes((json.dumps(contract, indent=2) + '\n').encode('utf8'))
    print(json.dumps({'status': 'SOURCE_AUTHORED_NOT_EXECUTED', 'tables': 8, 'files': len(generated)}))


if __name__ == '__main__':
    main()
