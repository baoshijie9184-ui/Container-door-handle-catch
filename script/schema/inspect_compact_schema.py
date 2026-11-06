"""Read actual MySQL objects on ECS and check the whole compact-schema table budget.

This proves only the object-count gate, not data migration or functional correctness.
Credentials come from an explicitly provided private MySQL option file; no .env,
login-path, local database fallback, SQL mutation, or bill query is performed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / 'docs/database/compact-schema-contract.json'
IDENTIFIER = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')
SYSTEM_SCHEMAS = {'mysql', 'sys', 'performance_schema', 'information_schema'}


def validate_client_options(path):
    # MySQL option files may contain init-command, include directives and output
    # redirection. A read-only catalog tool must reject those before connecting.
    allowed = {'host', 'port', 'user', 'password', 'protocol', 'socket',
               'ssl-mode', 'ssl-ca', 'ssl-capath', 'ssl-cert', 'ssl-key',
               'ssl-cipher', 'tls-version', 'tls-ciphersuites', 'connect-timeout'}
    group = None
    seen = set()
    for line in path.read_text(encoding='utf-8').splitlines():
        text = line.strip()
        if not text or text.startswith(('#', ';')):
            continue
        if text.startswith('[') and text.endswith(']'):
            group = text[1:-1]
            if group not in ('client', 'mysql'):
                raise ValueError('Only client/mysql option groups are accepted')
            continue
        match = re.match(r'([a-zA-Z][a-zA-Z0-9_-]*)\s*=', text)
        if group is None or not match or match.group(1).replace('_', '-') not in allowed:
            raise ValueError('Client options must contain only explicit connection settings')
        key = (group, match.group(1).replace('_', '-'))
        if key in seen:
            raise ValueError('Repeated client connection option')
        seen.add(key)


def load_contract():
    contract = json.loads(CONTRACT.read_text(encoding='utf-8'))
    if contract.get('status') == 'REQUIRES_DOMAIN_REDESIGN':
        raise ValueError('The first schema draft is withdrawn: it cannot be used as the acceptance catalog')
    targets = contract['expectedTargetTables']
    sources = contract['sourceTables']
    mapped = [name for group in contract['mapping'] for name in group['sources']]
    if contract['maximumBusinessTables'] != 30 or len(targets) > 30:
        raise ValueError('The user table budget is 30; a manifest cannot relax it')
    if len(set(targets)) != len(targets) or not all(IDENTIFIER.fullmatch(x) for x in targets):
        raise ValueError('Invalid or repeated target table names')
    if Counter(mapped) != Counter(sources) or any(n != 1 for n in Counter(sources).values()):
        raise ValueError('Every observed source table needs exactly one primary mapping')
    if {group['target'] for group in contract['mapping']} != set(targets):
        raise ValueError('Target tables and source mapping disagree')
    return contract


def assess_objects(contract, rows):
    tables = [row for row in rows if row['type'] == 'BASE TABLE']
    counts = Counter(row['name'] for row in tables)
    expected = set(contract['expectedTargetTables'])
    findings = {
        'businessBaseTableCount': len(tables),
        'missingTables': sorted(expected - set(counts)),
        'unexpectedTables': sorted(set(counts) - expected),
        'repeatedTablesAcrossSchemas': sorted(name for name, count in counts.items() if count > 1),
        'nonTableObjects': [row for row in rows if row['type'] != 'BASE TABLE'],
        'nonInnoDbTables': [row for row in tables if row['engine'] != 'InnoDB'],
    }
    passed = len(tables) <= 30 and not any(value for key, value in findings.items()
                                          if key != 'businessBaseTableCount')
    return {'passed': passed, **findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mysql', required=True, type=Path, help='Existing ECS mysql client executable')
    parser.add_argument('--defaults-file', required=True, type=Path, help='Private explicit client options')
    parser.add_argument('--database', required=True, action='append', help='Every active business schema; repeat for split databases')
    parser.add_argument('--expected-server-uuid', required=True)
    parser.add_argument('--output', required=True, type=Path, help='Fresh absolute JSON path below checkout/work')
    args = parser.parse_args()
    contract = load_contract()
    sys.path.insert(0, str(ROOT / 'scripts'))
    from ecs_execution import require_ecs_execution
    identity = require_ecs_execution()
    databases = sorted(set(args.database))
    if len(databases) != len(args.database) or not all(IDENTIFIER.fullmatch(db) for db in databases):
        raise ValueError('Explicit, distinct business schema names are required')
    if set(databases) & SYSTEM_SCHEMAS:
        raise ValueError('System schemas are outside the business schema count')
    if not re.fullmatch(r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}', args.expected_server_uuid):
        raise ValueError('A previously observed MySQL server UUID is required')
    for path in (args.mysql, args.defaults_file):
        if not path.is_absolute() or not path.is_file():
            raise ValueError('Executable and credential paths must be existing absolute files')
    if stat.S_IMODE(args.defaults_file.stat().st_mode) & 0o077:
        raise ValueError('Client credential file must not be readable by group or other users')
    validate_client_options(args.defaults_file)
    output = args.output
    if not output.is_absolute() or not output.resolve().is_relative_to(ROOT / 'work') or output.exists():
        raise ValueError('Use a fresh absolute output path below this checkout/work')
    env = {key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')}
    command = [str(args.mysql), '--defaults-file=' + str(args.defaults_file), '--no-login-paths',
               '--batch', '--raw', '--skip-column-names', '--default-character-set=utf8mb4',
               '--connect-timeout=10', '--database=' + databases[0]]

    def query(sql, *, json_rows=True):
        result = subprocess.run(command, input='SET SESSION TRANSACTION READ ONLY;\n' + sql,
                                text=True, encoding='utf-8', capture_output=True, timeout=45, env=env)
        if result.returncode:
            # Do not copy client configuration, arbitrary option-file commands or credentials to evidence.
            raise RuntimeError(f'MySQL read failed (exit {result.returncode}); inspect the private client configuration')
        lines = result.stdout.splitlines()
        return [json.loads(line) for line in lines if line] if json_rows else lines

    def server():
        value = query("SELECT JSON_OBJECT('serverUuid',@@server_uuid,'version',@@version);")[0]
        if value['serverUuid'].lower() != args.expected_server_uuid.lower():
            raise RuntimeError('Actual MySQL UUID differs from the admitted server')
        if not value['version'].startswith('8.4.'):
            raise RuntimeError('This schema contract currently targets MySQL 8.4')
        return value

    actual_server = server()
    grants = query('SHOW GRANTS FOR CURRENT_USER;', json_rows=False)
    for database in databases:
        # Table-scoped grants can hide extra legacy tables in information_schema.
        # Require direct schema/global SELECT visibility instead of accepting a partial catalog.
        visible = False
        for grant in grants:
            match = re.match(r'GRANT (.+) ON (.+) TO ', grant)
            if not match:
                continue
            privileges, scope = match.groups()
            if scope in ('*.*', '`' + database + '`.*') and (
                    privileges == 'ALL PRIVILEGES' or 'SELECT' in [x.strip() for x in privileges.split(',')]):
                visible = True
        if not visible:
            raise RuntimeError('Direct schema-wide SELECT visibility is required for a complete catalog: ' + database)
    schema_list = ','.join("'" + name + "'" for name in databases)
    objects_sql = ("SELECT JSON_OBJECT('schema',TABLE_SCHEMA,'name',TABLE_NAME,'type',TABLE_TYPE,'engine',ENGINE) "
                   'FROM information_schema.tables WHERE TABLE_SCHEMA IN (' + schema_list + ') '
                   'ORDER BY TABLE_SCHEMA,TABLE_NAME;')
    rows = query(objects_sql)
    columns_sql = ("SELECT JSON_OBJECT('schema',TABLE_SCHEMA,'table',TABLE_NAME,'name',COLUMN_NAME,"
                    "'type',COLUMN_TYPE,'nullable',IS_NULLABLE,'default',COLUMN_DEFAULT,'extra',EXTRA) "
                    'FROM information_schema.columns WHERE TABLE_SCHEMA IN (' + schema_list + ') '
                    'ORDER BY TABLE_SCHEMA,TABLE_NAME,ORDINAL_POSITION;')
    indexes_sql = ("SELECT JSON_OBJECT('schema',TABLE_SCHEMA,'table',TABLE_NAME,'name',INDEX_NAME,"
                    "'column',COLUMN_NAME,'sequence',SEQ_IN_INDEX,'nonUnique',NON_UNIQUE) "
                    'FROM information_schema.statistics WHERE TABLE_SCHEMA IN (' + schema_list + ') '
                    'ORDER BY TABLE_SCHEMA,TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX;')
    columns = query(columns_sql)
    indexes = query(indexes_sql)
    if (server() != actual_server or query(objects_sql) != rows
            or query(columns_sql) != columns or query(indexes_sql) != indexes):
        raise RuntimeError('Server, tables, columns or indexes changed during inspection; do not accept this receipt')
    assessment = assess_objects(contract, rows)
    primary_keys = {(row['schema'], row['table']) for row in indexes if row['name'] == 'PRIMARY'}
    missing_primary = [row for row in rows if row['type'] == 'BASE TABLE'
                       and (row['schema'], row['name']) not in primary_keys]
    if missing_primary:
        assessment['passed'] = False
    receipt = {'observedAtUtc': datetime.now(timezone.utc).isoformat(), 'ecs': identity,
               'server': actual_server, 'businessSchemas': databases,
               'contractSha256': hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
               'status': 'TABLE_BUDGET_PASS' if assessment['passed'] else 'TABLE_BUDGET_FAIL',
               'assessment': assessment, 'missingPrimaryKeys': missing_primary,
               'objects': rows, 'columns': columns, 'indexes': indexes,
               'doesNotProve': ['data preservation', 'application correctness', 'rollback', 'cloud stopped state']}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        os.chmod(output, 0o600)
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'status': receipt['status'], 'baseTables': assessment['businessBaseTableCount'],
                      'receipt': str(output)}))
    return 0 if assessment['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
