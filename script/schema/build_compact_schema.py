"""Compile the compact MySQL schema from reviewed SQL sources without running SQL.

Local use is a source build only. Actual DDL, data migration and application
verification must run on ECS. The compiler deliberately rejects compatibility
views, extra tables, destructive statements and references to legacy tables.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
PARTS = ('10-core.sql', '20-content.sql', '25-agent.sql', '30-operations.sql',
         '35-runtime-guards.sql', '36-identity-guards.sql', '37-audit-guards.sql', '38-quota-guards.sql', '39-workflow-guards.sql', '40-relations.sql')
RUNTIME_GUARDS = {'compact_runtime_protect_delete': 'DELETE',
                  'compact_runtime_protect_update': 'UPDATE'}
IDENTITY_GUARDS = {'compact_identity_protect_delete': 'DELETE',
                   'compact_identity_protect_update': 'UPDATE'}
QUOTA_GUARDS = {'compact_quota_history_protect_delete': 'DELETE',
                'compact_quota_history_protect_update': 'UPDATE'}
AUDIT_GUARDS = {'compact_audit_model_reference_insert': 'INSERT',
                'compact_audit_model_reference_update': 'UPDATE',
                'compact_audit_identity_evidence_delete': 'DELETE'}
WORKFLOW_GUARDS = {'compact_workflow_chat_reference_insert': 'INSERT',
                   'compact_workflow_chat_reference_update': 'UPDATE',
                   'compact_workflow_identity_receipt_delete': 'DELETE'}
GUARD_RESOURCES = {'35-runtime-guards.sql': ('runtime_state', RUNTIME_GUARDS),
                   '36-identity-guards.sql': ('users', IDENTITY_GUARDS),
                   '37-audit-guards.sql': ('audit_event', AUDIT_GUARDS),
                   '38-quota-guards.sql': ('llm_quota', QUOTA_GUARDS),
                   '39-workflow-guards.sql': ('workflow_instance', WORKFLOW_GUARDS)}
LEGACY_CLOCK_TABLES = ('content_asset', 'content_revision', 'content_link', 'agent_run',
                       'agent_connector', 'runtime_state', 'workflow_instance', 'audit_event')
LEGACY_CLOCK_GUARDS = {}
for clock_table, clock_parent in ([(name, False) for name in LEGACY_CLOCK_TABLES]
                                  + [(name, True) for name in ('model_management', 'chat_session', 'users')]):
    prefix = 'compact_legacy_clock_' + ('parent_' if clock_parent else '') + clock_table
    filename = '35-legacy-clock-' + ('parent-' if clock_parent else '') + clock_table.replace('_', '-') + '.sql'
    guards = {prefix + '_update': 'UPDATE', prefix + '_delete': 'DELETE'}
    LEGACY_CLOCK_GUARDS.update(guards)
    GUARD_RESOURCES[filename] = (clock_table, guards)
PARTS = (*PARTS[:-1], *(name for name in GUARD_RESOURCES if name.startswith('35-legacy-clock-')), PARTS[-1])
IDENT = r'`?([a-z][a-z0-9_]*)`?'


def without_comments(sql):
    """Preserve strings, quoted identifiers and line offsets while masking comments."""
    chars = list(sql)
    quote = None
    i = 0
    while i < len(sql):
        c = sql[i]
        if quote:
            if c == '\\':
                i += 2
                continue
            if c == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if c in "'\"`":
            quote = c
            i += 1
            continue
        end = None
        if sql.startswith('--', i) and (i + 2 == len(sql) or sql[i + 2].isspace()) or c == '#':
            end = sql.find('\n', i)
            if end < 0:
                end = len(sql)
        elif sql.startswith('/*', i):
            if sql.startswith('/*!', i):
                raise ValueError('Executable comment directives are not allowed in the baseline')
            close = sql.find('*/', i + 2)
            if close < 0:
                raise ValueError('Unclosed SQL comment')
            end = close + 2
        if end is None:
            i += 1
        else:
            for position in range(i, end):
                if chars[position] not in '\r\n':
                    chars[position] = ' '
            i = end
    if quote:
        raise ValueError('Unclosed SQL string or identifier')
    return ''.join(chars)


def split_top_level(sql, delimiter):
    quote = None
    depth = 0
    begin = i = 0
    while i < len(sql):
        c = sql[i]
        if quote:
            if c == '\\':
                i += 2
                continue
            if c == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    i += 2
                    continue
                quote = None
        elif c in "'\"`":
            quote = c
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth < 0:
                raise ValueError('Unbalanced SQL parentheses at line ' + str(sql.count('\n', 0, i) + 1))
        elif c == delimiter and depth == 0:
            if sql[begin:i].strip():
                yield sql[begin:i].strip()
            begin = i + 1
        i += 1
    if quote or depth:
        raise ValueError('Unbalanced SQL expression')
    if sql[begin:].strip():
        yield sql[begin:].strip()


def identifiers(text):
    result = []
    for item in split_top_level(text, ','):
        match = re.fullmatch(IDENT, item, re.I)
        if not match:
            raise ValueError('Key must reference whole named columns: ' + item)
        result.append(match.group(1).lower())
    return result


def validate_check_tail(field, table):
    """A CHECK must end at its own closing parenthesis, never absorb a column."""
    match = re.match(r'(?:CONSTRAINT\s+`?\w+`?\s+)?CHECK\s*\(', field, re.I)
    if not match:
        return
    depth, quote, index = 1, None, match.end()
    while index < len(field):
        char = field[index]
        if quote:
            if char == '\\':
                index += 2
                continue
            if char == quote:
                if index + 1 < len(field) and field[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                tail = field[index + 1:].strip()
                if tail and not re.fullmatch(r'(?:NOT\s+)?ENFORCED', tail, re.I):
                    raise ValueError(table + ' CHECK has trailing SQL; check generated section separators')
                return
        index += 1
    raise ValueError(table + ' has an unclosed CHECK')


def parse_table(statement, source):
    match = re.fullmatch(r'CREATE\s+TABLE\s+' + IDENT + r'\s*\((.*)\)\s*(ENGINE\s*=.*)',
                         statement, re.I | re.S)
    if not match:
        raise ValueError('Baseline requires plain CREATE TABLE with explicit engine: ' + source)
    name, body, options = match.groups()
    name = name.lower()
    if not re.search(r'\bENGINE\s*=\s*InnoDB\b', options, re.I):
        raise ValueError(name + ' must use InnoDB')
    if not re.search(r'\b(?:DEFAULT\s+)?(?:CHARSET|CHARACTER\s+SET)\s*=\s*utf8mb4\b', options, re.I):
        raise ValueError(name + ' must declare utf8mb4')
    table_collation = re.search(r'\bCOLLATE\s*=\s*(\w+)', options, re.I)
    columns, constraints, primary, unique = {}, [], [], []
    for field in split_top_level(body, ','):
        if re.match(r'(?:CONSTRAINT|PRIMARY|UNIQUE|KEY|INDEX|FOREIGN|CHECK|FULLTEXT|SPATIAL)\b', field, re.I):
            validate_check_tail(field, name)
            constraints.append(field)
            continue
        column = re.match(IDENT + r'\s+([a-z]+(?:\s*\([^)]*\))?(?:\s+UNSIGNED)?)', field, re.I)
        if not column:
            raise ValueError(name + ' has an unrecognized column: ' + field)
        column_name, data_type = column.groups()
        column_name = column_name.lower()
        if column_name in columns:
            raise ValueError(name + ' repeats column ' + column_name)
        collation = re.search(r'\bCOLLATE\s+(\w+)', field, re.I)
        columns[column_name] = {'type': re.sub(r'\s+', ' ', data_type.upper()), 'declaration': field,
                                'collation': collation.group(1).lower() if collation else (
                                    table_collation.group(1).lower() if table_collation else None),
                                'generatedVirtual': bool(re.search(r'\bGENERATED\b', field, re.I)
                                                         and not re.search(r'\bSTORED\b', field, re.I))}
        if re.search(r'\bPRIMARY\s+KEY\b', field, re.I):
            primary.append([column_name])
        elif re.search(r'\bUNIQUE\b', field, re.I):
            unique.append([column_name])
    for constraint in constraints:
        bare = re.sub(r'^CONSTRAINT\s+`?\w+`?\s+', '', constraint, flags=re.I)
        key = re.match(r'PRIMARY\s+KEY\s*\(([^)]+)\)', bare, re.I)
        if key:
            primary.append(identifiers(key.group(1)))
        key = re.match(r'UNIQUE\s+(?:(?:KEY|INDEX)\s+)?(?:`?\w+`?\s*)?\(([^)]+)\)', bare, re.I)
        if key:
            unique.append(identifiers(key.group(1)))
    if len(primary) != 1:
        raise ValueError(name + ' requires exactly one primary key')
    for key in primary + unique:
        if not set(key) <= columns.keys():
            raise ValueError(name + ' key refers to an absent column: ' + str(key))
    if len(columns) > 1017:
        raise ValueError(name + ' exceeds the InnoDB column limit')
    return {'name': name, 'source': source, 'columns': columns, 'primaryKey': primary[0],
            'uniqueKeys': unique, 'constraints': constraints, 'options': options}


def compile_schema():
    contract_path = ROOT / 'docs/database/compact-schema-contract.json'
    contract = json.loads(contract_path.read_text(encoding='utf-8'))
    if contract.get('status') == 'REQUIRES_DOMAIN_REDESIGN':
        raise ValueError('The first schema draft is withdrawn: redesign the domain boundaries before building candidate DDL')
    expected = contract['expectedTargetTables']
    if contract['maximumBusinessTables'] != 30 or len(expected) > 30 or len(expected) != len(set(expected)):
        raise ValueError('The compact contract cannot exceed or redefine the 30-table budget')
    actual_parts = {path.name for path in (ROOT / 'sql/mysql/compact/baseline').glob('*.sql')}
    if actual_parts != set(PARTS):
        raise ValueError('Baseline directory contains missing or unregistered SQL parts: ' + str(sorted(actual_parts ^ set(PARTS))))
    tables, foreign_keys, constraint_names, parts, output, triggers = {}, [], [], [], [], []
    for part in PARTS:
        path = ROOT / 'sql/mysql/compact/baseline' / part
        body = path.read_text(encoding='utf-8')
        parts.append({'file': str(path.relative_to(ROOT)).replace('\\', '/'),
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        if part in GUARD_RESOURCES:
            # Guard resources are also loaded by JDBC with separator=$$. The CLI
            # artifact supplies DELIMITER without weakening the table-DDL grammar.
            clean = without_comments(body).strip()
            guard_table, expected_guards = GUARD_RESOURCES[part]
            if not clean.endswith('$$') or guard_table not in tables:
                raise ValueError('Persistence guards require their table and explicit $$ terminators: ' + part)
            found = {}
            for declaration in clean[:-2].split('$$'):
                match = re.fullmatch(
                    r'\s*CREATE\s+TRIGGER\s+' + IDENT
                    + r'\s+BEFORE\s+(INSERT|DELETE|UPDATE)\s+ON\s+' + guard_table
                    + r'\s+FOR\s+EACH\s+ROW\s+BEGIN\s+(.*)\s+END\s*',
                    declaration, re.I | re.S)
                if not match:
                    raise ValueError('Unexpected runtime guard declaration')
                name, event, trigger_body = match.groups()
                name, event = name.lower(), event.upper()
                if expected_guards.get(name) != event or name in found:
                    raise ValueError('Unexpected or repeated runtime guard: ' + name)
                executable = re.sub(r"'(?:''|\\.|[^'\\])*'", "''", trigger_body)
                if re.search(r'\b(CREATE|DROP|ALTER|TRUNCATE|INSERT|DELETE|UPDATE|CALL|EXECUTE|GRANT|REVOKE|REPLACE)\b', executable, re.I):
                    raise ValueError('Runtime guard may reject mutations but cannot execute nested DDL/DML')
                if not re.search(r"SIGNAL\s+SQLSTATE\s+'45000'", trigger_body, re.I):
                    raise ValueError('Runtime guard has no rejection signal: ' + name)
                found[name] = event
                triggers.append({'name': name, 'table': guard_table, 'timing': 'BEFORE', 'event': event,
                                 'source': part})
            if found != expected_guards:
                raise ValueError('Protected persistence state requires both guards: ' + part)
            output.append('-- Source: ' + parts[-1]['file'] + '\nDELIMITER $$\n' + body.rstrip()
                          + '\nDELIMITER ;\n')
            continue
        statements = list(split_top_level(without_comments(body), ';'))
        for statement in statements:
            if re.fullmatch(r'SET\s+NAMES\s+utf8mb4(?:\s+COLLATE\s+utf8mb4_0900_ai_ci)?', statement, re.I):
                continue
            table_match = re.match(r'CREATE\s+TABLE\b', statement, re.I)
            if table_match:
                table = parse_table(statement, part)
                name = table['name']
                if name in tables:
                    raise ValueError('Duplicate CREATE TABLE: ' + name)
                tables[name] = table
                fields = table['constraints']
            else:
                alteration = re.fullmatch(r'ALTER\s+TABLE\s+' + IDENT + r'\s+(.*)', statement, re.I | re.S)
                if not alteration or alteration.group(1).lower() not in tables:
                    raise ValueError('Only CREATE TABLE and post-create ADD CONSTRAINT are allowed: ' + statement[:140])
                name = alteration.group(1).lower()
                fields = list(split_top_level(alteration.group(2), ','))
                if not all(re.match(r'ADD\s+CONSTRAINT\b', field, re.I) for field in fields):
                    raise ValueError('Baseline ALTER is limited to named constraints: ' + name)
                fields = [re.sub(r'^ADD\s+', '', field, flags=re.I) for field in fields]
                tables[name]['constraints'].extend(fields)
            for field in fields:
                named = re.match(r'CONSTRAINT\s+' + IDENT, field, re.I)
                if named:
                    constraint_names.append(named.group(1).lower())
                foreign = re.search(r'FOREIGN\s+KEY\s*\(([^)]+)\)\s+REFERENCES\s+' + IDENT
                                    + r'\s*\(([^)]+)\)', field, re.I)
                if foreign:
                    local, parent, remote = foreign.groups()
                    if parent.lower() not in tables:
                        raise ValueError('Defer foreign key until referenced table is created: ' + name + ' -> ' + parent)
                    foreign_keys.append({'table': name, 'columns': identifiers(local),
                                         'parent': parent.lower(), 'parentColumns': identifiers(remote),
                                         'declaration': field})
        output.append('-- Source: ' + parts[-1]['file'] + '\n' + body.rstrip() + '\n')
    repeated = [name for name, count in Counter(constraint_names).items() if count > 1]
    if repeated:
        raise ValueError('Constraint names must be unique within the schema: ' + ', '.join(repeated))
    if set(tables) != set(expected) or len(tables) > 30:
        raise ValueError('Actual CREATE TABLE catalog differs from contract: missing=' +
                         str(sorted(set(expected) - tables.keys())) + ' unexpected=' + str(sorted(tables.keys() - set(expected))))
    for foreign in foreign_keys:
        child, parent = tables[foreign['table']], tables[foreign['parent']]
        if len(foreign['columns']) != len(foreign['parentColumns']):
            raise ValueError('Foreign-key arity mismatch: ' + foreign['declaration'])
        if foreign['parentColumns'] not in [parent['primaryKey'], *parent['uniqueKeys']]:
            raise ValueError('Foreign key must reference an explicit complete unique key: ' + foreign['declaration'])
        for local, remote in zip(foreign['columns'], foreign['parentColumns']):
            if local not in child['columns'] or remote not in parent['columns']:
                raise ValueError('Foreign key references an absent column: ' + foreign['declaration'])
            left, right = child['columns'][local], parent['columns'][remote]
            if left['generatedVirtual'] or right['generatedVirtual']:
                raise ValueError('Virtual generated columns cannot participate in a foreign key')
            # MySQL requires equal size/sign for fixed-precision types, while
            # string lengths may differ. Preserve legacy widths instead of
            # shortening a column merely to make a source check pass.
            # https://dev.mysql.com/doc/refman/8.4/en/create-table-foreign-keys.html
            left_string = re.fullmatch(r'(VARCHAR|CHAR|VARBINARY|BINARY)\(\d+\)', left['type'])
            right_string = re.fullmatch(r'(VARCHAR|CHAR|VARBINARY|BINARY)\(\d+\)', right['type'])
            compatible_strings = left_string and right_string and left_string.group(1) == right_string.group(1)
            if left['type'] != right['type'] and not compatible_strings:
                raise ValueError('Foreign-key type mismatch: ' + foreign['table'] + '.' + local + ' -> ' + foreign['parent'] + '.' + remote)
            if re.match(r'(?:VAR)?CHAR\b', left['type']) and left['collation'] != right['collation']:
                raise ValueError('Foreign-key collation mismatch: ' + foreign['declaration'])
    sql = '-- Generated source build. Execute only on an admitted empty ECS candidate database.\n' + '\n'.join(output)
    catalog = {'status': 'SOURCE_COMPILED_MYSQL_EXECUTION_NOT_PROVEN',
               'designStatus': contract['status'],
               'createdAtUtc': datetime.now(timezone.utc).isoformat(), 'tableCount': len(tables),
               'contractSha256': hashlib.sha256(contract_path.read_bytes()).hexdigest(),
               'sqlSha256': hashlib.sha256(sql.encode('utf-8')).hexdigest(), 'parts': parts,
               'tables': tables, 'foreignKeys': foreign_keys, 'triggers': triggers,
               'requiresEcsValidation': ['MySQL DDL execution and row/index limits', 'CHECK and uniqueness semantics',
                                        'model/identity protection triggers and least-privilege application grants',
                                        'real source data migration', 'application behavior and query plans']}
    return sql, catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='New absolute build directory under checkout/work')
    args = parser.parse_args()
    path = args.output
    if not path.is_absolute() or not path.resolve().is_relative_to(ROOT / 'work') or path.exists():
        raise ValueError('Output must be a new absolute directory under checkout/work')
    sql, catalog = compile_schema()
    path.mkdir(parents=True)
    (path / 'schema.sql').write_text(sql, encoding='utf-8', newline='\n')
    (path / 'catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': catalog['status'], 'tables': catalog['tableCount'], 'output': str(path)}))


if __name__ == '__main__':
    main()
