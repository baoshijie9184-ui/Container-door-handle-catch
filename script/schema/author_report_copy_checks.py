"""Author full report-copy reconciliation from reviewed INSERT projections; never execute SQL.

Source semantics remain in copy/34. This author checks every assigned field against
its source expression and every unassigned ordinary field against its DDL default.
It does not prove those projections are semantically correct: the ECS suite exercises
historical source facts, public API replay and deliberate target corruption separately.
"""
from pathlib import Path
import importlib.util
import json
import re

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('compact_parser', ROOT / 'script/schema/build_compact_schema.py')
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)
PATH = ROOT / 'sql/mysql/compact/copy/34-quality-report-workflow.sql'
BEGIN = '-- BEGIN complete report field reconciliation'
END = '-- END complete report field reconciliation'
META_BEGIN = '-- BEGIN exact report source metadata'
META_END = '-- END exact report source metadata'


def quote(value):
    return 'NULL' if value is None else "'" + str(value).replace("'", "''") + "'"


def source_metadata():
    # Read the actual historical CREATE/ALTER statements, including V30 additions.
    definitions = {}
    for file in ('migration-V21-quality-report-approval.sql', 'migration-V22-agent-report-origin.sql', 'migration-V30-report-event-delivery.sql'):
        for statement in parser.split_top_level(parser.without_comments((ROOT / 'sql/mysql' / file).read_text(encoding='utf-8')), ';'):
            create = re.match(r'CREATE TABLE IF NOT EXISTS ([a-z_]+)\b', statement)
            alter = re.fullmatch(r'ALTER TABLE ([a-z_]+) ADD COLUMN (.*)', statement, re.S)
            index = re.fullmatch(r'CREATE INDEX ([a-z_]+) ON ([a-z_]+)\(([^)]+)\)', statement)
            if create:
                definitions[create.group(1)] = statement.replace('CREATE TABLE IF NOT EXISTS', 'CREATE TABLE', 1)
            elif alter or index:
                name = alter.group(1) if alter else index.group(2)
                field = alter.group(2) if alter else f'KEY {index.group(1)} ({index.group(3)})'
                definitions[name] = re.sub(r'\)\s*ENGINE=', ',\n' + field + '\n) ENGINE=', definitions[name])
            else:
                raise ValueError('Unreviewed report source DDL: ' + statement)
    columns, indexes = [], []
    for name, ddl in definitions.items():
        table = parser.parse_table(ddl, 'V21/V22/V30')
        for position, (field, definition) in enumerate(table['columns'].items(), 1):
            declaration = definition['declaration']
            match = re.search(r"\bDEFAULT\s+(NULL|CURRENT_TIMESTAMP|[0-9]+|'(?:''|[^'])*')(?=\s|$)", declaration, re.I)
            value = match.group(1) if match else None
            if value and value.startswith("'"):
                value = value[1:-1].replace("''", "'")
            elif value and value.upper() == 'NULL':
                value = None
            elif value and value.upper() == 'CURRENT_TIMESTAMP':
                value = 'current_timestamp'
            nullable = 'NO' if field in table['primaryKey'] or 'NOT NULL' in declaration.upper() else 'YES'
            extra = 'auto_increment' if 'AUTO_INCREMENT' in declaration.upper() else 'default_generated' if value == 'current_timestamp' else ''
            collation = definition['collation'] if re.match(r'(?:CHAR|VARCHAR|TEXT|MEDIUMTEXT)', definition['type']) else None
            columns.append((name, field, position, definition['type'].lower(), nullable, collation, value, extra))
        keys = [('PRIMARY', 0, table['primaryKey'])]
        for constraint in table['constraints']:
            match = re.fullmatch(r'(UNIQUE\s+)?KEY\s+([a-z_]+)\s*\(([^)]+)\)', constraint, re.I)
            if match:
                keys.append((match.group(2), 0 if match.group(1) else 1, parser.identifiers(match.group(3))))
        indexes += [(name, key, position, field, non_unique) for key, non_unique, fields in keys for position, field in enumerate(fields, 1)]
    names = ','.join(map(quote, definitions))
    statements = [META_BEGIN,
        'CREATE TEMPORARY TABLE compact_report_columns(table_name VARCHAR(64),column_name VARCHAR(64),position_no INT,column_type VARCHAR(64),nullable VARCHAR(3),collation_name VARCHAR(64),default_value VARCHAR(64),extra VARCHAR(64),PRIMARY KEY(table_name,column_name)) ENGINE=InnoDB;',
        'INSERT INTO compact_report_columns VALUES\n' + ',\n'.join('(' + ','.join(map(quote, row)) + ')' for row in columns) + ';',
        'CREATE TEMPORARY TABLE compact_report_indexes(table_name VARCHAR(64),index_name VARCHAR(64),position_no INT,column_name VARCHAR(64),non_unique INT,PRIMARY KEY(table_name,index_name,position_no)) ENGINE=InnoDB;',
        'INSERT INTO compact_report_indexes VALUES\n' + ',\n'.join('(' + ','.join(map(quote, row)) + ')' for row in indexes) + ';']
    conditions = [
        "(SELECT COUNT(DISTINCT privilege_type) FROM information_schema.schema_privileges WHERE BINARY table_schema=BINARY '__SOURCE_SCHEMA__' AND privilege_type IN ('SELECT','TRIGGER') AND grantee=CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',1)),'@',QUOTE(SUBSTRING_INDEX(CURRENT_USER(),'@',-1))))=2",
        f"(SELECT COUNT(*) FROM information_schema.tables WHERE BINARY table_schema=BINARY '__SOURCE_SCHEMA__' AND table_name IN ({names}) AND table_type='BASE TABLE' AND engine='InnoDB' AND BINARY table_collation=BINARY 'utf8mb4_unicode_ci')=8",
        f"NOT EXISTS(SELECT 1 FROM information_schema.columns a LEFT JOIN compact_report_columns e ON BINARY e.table_name=BINARY a.table_name AND BINARY e.column_name=BINARY a.column_name WHERE BINARY a.table_schema=BINARY '__SOURCE_SCHEMA__' AND a.table_name IN ({names}) AND e.column_name IS NULL)",
        "NOT EXISTS(SELECT 1 FROM compact_report_columns e LEFT JOIN information_schema.columns a ON BINARY a.table_schema=BINARY '__SOURCE_SCHEMA__' AND BINARY a.table_name=BINARY e.table_name AND BINARY a.column_name=BINARY e.column_name WHERE a.column_name IS NULL OR a.ordinal_position<>e.position_no OR NOT(BINARY LOWER(a.column_type)<=>BINARY e.column_type) OR NOT(BINARY a.is_nullable<=>BINARY e.nullable) OR NOT(BINARY a.collation_name<=>BINARY e.collation_name) OR NOT(BINARY a.character_set_name<=>BINARY IF(e.collation_name IS NULL,NULL,'utf8mb4')) OR NOT(BINARY (CASE WHEN e.extra='default_generated' THEN REPLACE(LOWER(a.column_default),'()','') ELSE a.column_default END)<=>BINARY e.default_value) OR NOT(BINARY LOWER(a.extra)<=>BINARY e.extra) OR a.generation_expression<>'')",
        f"NOT EXISTS(SELECT 1 FROM information_schema.statistics a LEFT JOIN compact_report_indexes e ON BINARY e.table_name=BINARY a.table_name AND BINARY e.index_name=BINARY a.index_name AND e.position_no=a.seq_in_index WHERE BINARY a.table_schema=BINARY '__SOURCE_SCHEMA__' AND a.table_name IN ({names}) AND e.index_name IS NULL)",
        "NOT EXISTS(SELECT 1 FROM compact_report_indexes e LEFT JOIN information_schema.statistics a ON BINARY a.table_schema=BINARY '__SOURCE_SCHEMA__' AND BINARY a.table_name=BINARY e.table_name AND BINARY a.index_name=BINARY e.index_name AND a.seq_in_index=e.position_no WHERE a.index_name IS NULL OR NOT(BINARY a.column_name<=>BINARY e.column_name) OR a.non_unique<>e.non_unique OR a.sub_part IS NOT NULL OR a.expression IS NOT NULL OR a.index_type<>'BTREE' OR a.collation<>'A' OR a.is_visible<>'YES')",
        f"NOT EXISTS(SELECT 1 FROM information_schema.triggers WHERE BINARY event_object_schema=BINARY '__SOURCE_SCHEMA__' AND event_object_table IN ({names}))",
        f"NOT EXISTS(SELECT 1 FROM information_schema.table_constraints WHERE BINARY table_schema=BINARY '__SOURCE_SCHEMA__' AND table_name IN ({names}) AND constraint_type IN ('FOREIGN KEY','CHECK'))"]
    statements += ['INSERT INTO compact_report_guard SELECT IF(' + condition + ',1,0);' for condition in conditions]
    statements += ['DROP TEMPORARY TABLE compact_report_indexes;', 'DROP TEMPORARY TABLE compact_report_columns;', META_END]
    return '\n'.join(statements) + '\n', len(columns)


def source_clause(select):
    quote = None
    depth = 0
    i = 0
    while i < len(select):
        char = select[i]
        if quote:
            if char == '\\':
                i += 2
                continue
            if char == quote:
                if i + 1 < len(select) and select[i + 1] == quote:
                    i += 2
                    continue
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif depth == 0 and re.match(r'\sFROM\s', select[i:], re.I):
            return select[:i].strip(), re.sub(r'\s+ORDER BY a\.id\s*$', '', select[i:].strip()[5:])
        i += 1
    raise ValueError('Report INSERT must have an explicit source SELECT')


tables = {}
for statement in parser.split_top_level(parser.without_comments((ROOT / 'sql/mysql/compact/baseline/30-operations.sql').read_text(encoding='utf-8')), ';'):
    if statement.startswith('CREATE TABLE '):
        table = parser.parse_table(statement, '30-operations.sql')
        tables[table['name']] = table

sql = PATH.read_text(encoding='utf-8')
if META_BEGIN in sql:
    sql = sql[:sql.index(META_BEGIN)] + sql[sql.index(META_END) + len(META_END):].removeprefix('\n')
if BEGIN in sql:
    sql = sql[:sql.index(BEGIN)] + sql[sql.index(END) + len(END):].removeprefix('\n')
elif '-- Exact response/event strings' in sql:
    # Replace the old two partial checks; the preceding seven source-count checks stay.
    sql = sql[:sql.index('-- Exact response/event strings')] + sql[sql.index('COMMIT;'):]
checks = []
sources = set()
for statement in parser.split_top_level(parser.without_comments(sql), ';'):
    match = re.fullmatch(r'INSERT INTO (workflow_instance|audit_event|runtime_state)\(([^)]+)\)\s+SELECT\s+(.*)', statement, re.S)
    if not match:
        continue
    name, columns, select = match.groups()
    values, source = source_clause(select)
    names = list(parser.identifiers(columns))
    expressions = list(parser.split_top_level(values, ','))
    if len(names) != len(expressions):
        raise ValueError(f'{name}: projection arity mismatch')
    assigned = dict(zip(names, expressions))
    if len(assigned) != len(names) or not assigned.keys() <= tables[name]['columns'].keys():
        raise ValueError(f'{name}: duplicate or unknown assignment')
    source_name = re.match(r'`__SOURCE_SCHEMA__`\.([a-z_]+)\s', source).group(1)
    if source_name in sources:
        raise ValueError('Duplicate report source ' + source_name)
    sources.add(source_name)
    fields = []
    for field, definition in tables[name]['columns'].items():
        declaration = definition['declaration']
        if re.search(r'\b(AUTO_INCREMENT|GENERATED)\b', declaration, re.I):
            continue
        expected = assigned.get(field)
        if expected is None:
            default = re.search(r"\bDEFAULT\s+(NULL|[0-9]+|'(?:''|[^'])*')(?=\s|$)", declaration, re.I)
            if default:
                expected = default.group(1)
            elif re.search(r'\bDEFAULT\b|\bNOT NULL\b', declaration, re.I):
                raise ValueError(f'{name}.{field} requires a reviewed explicit default')
            else:
                expected = 'NULL'
        string = bool(re.match(r'(?:CHAR|VARCHAR|TEXT|LONGTEXT|MEDIUMTEXT|JSON)\b', definition['type']))
        actual = f't.{field}'
        fields.append(f'NOT(BINARY {actual}<=>BINARY ({expected}))' if string else f'NOT({actual}<=>({expected}))')
    keys = ['workflow_id'] if name == 'workflow_instance' else ['event_id'] if name == 'audit_event' else tables[name]['primaryKey']
    join = ' AND '.join(f'BINARY t.{key}=BINARY ({assigned[key]})' for key in keys)
    checks.append(f'-- {source_name}: all ordinary target fields, including NULL/default state.\n'
                  f'INSERT INTO compact_report_guard SELECT IF(COUNT(*)=0,1,0) FROM {source}\n'
                  f' LEFT JOIN {name} t ON {join}\n WHERE t.{keys[0]} IS NULL\n OR ' + '\n OR '.join(fields) + ';')

expected_sources = {'detection_report_command', 'detection_report_confirmation', 'detection_report_agent_origin',
                    'detection_report_outbox', 'detection_report_event_receipt', 'detection_report_audit', 'detection_report_event_state'}
if sources != expected_sources:
    raise ValueError('Report source coverage changed: ' + repr(sources))
block = BEGIN + '\n' + '\n'.join(checks) + '\n' + END + '\n'
if sql.count('COMMIT;') != 1:
    raise ValueError('Expected one atomic report copy transaction')
sql = sql.replace('COMMIT;', block + 'COMMIT;')
metadata, column_count = source_metadata()
sql = sql.replace('START TRANSACTION;\n', 'START TRANSACTION;\n' + metadata, 1)
PATH.write_text(sql, encoding='utf-8')
print(json.dumps({'status': 'SOURCE_AUTHORED_NOT_EXECUTED', 'sourceTables': len(sources), 'sourceColumnsIncludingMainReport': column_count, 'targetTables': 3}))
