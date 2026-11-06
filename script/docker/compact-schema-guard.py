#!/usr/bin/env python3
"""Read-only compact schema and migration/recovery admission for application releases.

Metadata functions are shared by migration and recovery. Business rows are not read here:
initial cutover separately revalidates the frozen source and target data snapshots.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from urllib.request import Request, ProxyHandler, build_opener

LABEL = 'io.doorhandle.business-schema'
FORMAT = 'compact29-v1'
SHA = re.compile(r'[a-f0-9]{64}')


def require(value, message):
    if not value:
        raise ValueError(message)


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def normalize_self_references(value, schema):
    """Normalize schema identifiers followed by a dot, preserving SQL string literals."""
    result, index = [], 0
    while index < len(value):
        start, char = index, value[index]
        if value.startswith('/*', index) or char == '#' or (value.startswith('--', index)
                and (index + 2 == len(value) or value[index + 2].isspace())):
            if value.startswith('/*', index):
                close = value.find('*/', index + 2)
                end = len(value) if close < 0 else close + 2
            else:
                end = value.find('\n', index)
                if end < 0:
                    end = len(value)
            result.append(value[index:end])
            index = end
            continue
        if char in ("'", '"'):
            quote = char
            index += 1
            while index < len(value):
                if value[index] == '\\':
                    index += 2
                elif value[index] == quote:
                    index += 1
                    if index < len(value) and value[index] == quote:
                        index += 1
                    else:
                        break
                else:
                    index += 1
            result.append(value[start:index])
            continue
        if char == '`':
            index += 1
            while index < len(value):
                if value[index] == '`':
                    index += 1
                    if index < len(value) and value[index] == '`':
                        index += 1
                    else:
                        break
                else:
                    index += 1
            token = value[start:index]
            name = token[1:-1].replace('``', '`')
        elif char.isalnum() or char in ('_', '$'):
            index += 1
            while index < len(value) and (value[index].isalnum() or value[index] in ('_', '$')):
                index += 1
            token = name = value[start:index]
        else:
            result.append(char)
            index += 1
            continue
        following = index
        while following < len(value) and value[following].isspace():
            following += 1
        result.append('`$SELF`' if name == schema and following < len(value) and value[following] == '.' else token)
    return ''.join(result)


def metadata_snapshot(query_json_rows):
    """Canonical MySQL metadata, independent of the chosen schema's spelling or row data."""
    queries = {
        'catalog': "SELECT JSON_OBJECT('name',TABLE_NAME,'type',TABLE_TYPE,'engine',ENGINE,'collation',TABLE_COLLATION) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME",
        'columns': "SELECT JSON_OBJECT('table',TABLE_NAME,'ordinal',ORDINAL_POSITION,'name',COLUMN_NAME,'type',COLUMN_TYPE,'nullable',IS_NULLABLE,'default',COLUMN_DEFAULT,'extra',EXTRA,'charset',CHARACTER_SET_NAME,'collation',COLLATION_NAME,'expression',GENERATION_EXPRESSION) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME,ORDINAL_POSITION",
        'indexes': "SELECT JSON_OBJECT('table',TABLE_NAME,'name',INDEX_NAME,'ordinal',SEQ_IN_INDEX,'column',COLUMN_NAME,'expression',EXPRESSION,'nonUnique',NON_UNIQUE,'prefix',SUB_PART,'nullable',NULLABLE,'type',INDEX_TYPE,'visible',IS_VISIBLE,'collation',COLLATION) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX",
        'checks': "SELECT JSON_OBJECT('table',t.TABLE_NAME,'name',t.CONSTRAINT_NAME,'clause',c.CHECK_CLAUSE,'enforced',t.ENFORCED) FROM information_schema.TABLE_CONSTRAINTS t JOIN information_schema.CHECK_CONSTRAINTS c ON c.CONSTRAINT_SCHEMA=t.CONSTRAINT_SCHEMA AND c.CONSTRAINT_NAME=t.CONSTRAINT_NAME WHERE t.CONSTRAINT_SCHEMA=DATABASE() AND t.CONSTRAINT_TYPE='CHECK' ORDER BY t.TABLE_NAME,t.CONSTRAINT_NAME",
        'foreignKeys': "SELECT JSON_OBJECT('table',k.TABLE_NAME,'name',k.CONSTRAINT_NAME,'ordinal',k.ORDINAL_POSITION,'column',k.COLUMN_NAME,'parentSchema',IF(k.REFERENCED_TABLE_SCHEMA=DATABASE(),'$SELF',k.REFERENCED_TABLE_SCHEMA),'parent',k.REFERENCED_TABLE_NAME,'parentColumn',k.REFERENCED_COLUMN_NAME,'update',r.UPDATE_RULE,'delete',r.DELETE_RULE) FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r ON r.CONSTRAINT_SCHEMA=k.CONSTRAINT_SCHEMA AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME WHERE k.CONSTRAINT_SCHEMA=DATABASE() AND k.REFERENCED_TABLE_NAME IS NOT NULL ORDER BY k.TABLE_NAME,k.CONSTRAINT_NAME,k.ORDINAL_POSITION",
        'triggers': "SELECT JSON_OBJECT('name',TRIGGER_NAME,'table',EVENT_OBJECT_TABLE,'timing',ACTION_TIMING,'event',EVENT_MANIPULATION,'statement',ACTION_STATEMENT,'sqlMode',SQL_MODE,'definer',DEFINER,'charset',CHARACTER_SET_CLIENT,'collation',COLLATION_CONNECTION) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE() ORDER BY TRIGGER_NAME",
    }
    database_rows = query_json_rows("SELECT JSON_OBJECT('schema',DATABASE());")
    require(len(database_rows) == 1 and isinstance(database_rows[0].get('schema'), str), 'Explicit metadata schema is required')
    database = database_rows[0]['schema']
    result = {}
    for name, sql in queries.items():
        rows = query_json_rows(sql + ';')
        require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), 'Metadata query did not return JSON objects')
        require(len(rows) <= 20000, 'Metadata catalog exceeds its reviewed limit')
        if name in ('columns', 'checks', 'triggers'):
            for row in rows:
                for field in ('expression', 'clause', 'statement'):
                    if isinstance(row.get(field), str):
                        row[field] = normalize_self_references(row[field], database)
        result[name] = rows
    return result


def metadata_sha256(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf8')).hexdigest()


def ecs_identity(expected):
    require(sys.platform == 'linux' and isinstance(expected, dict)
            and expected.get('instanceId') == 'i-2zeieuov2aum486jm1ek'
            and re.fullmatch(r'[a-f0-9]{32}', expected.get('machineId', '')),
            'Explicit admitted monolith ECS identity is required')
    require(Path('/etc/machine-id').read_text().strip() == expected['machineId'], 'Deployment machine identity differs')
    opener = build_opener(ProxyHandler({}))
    base = 'http://100.100.100.200/latest/'
    with opener.open(Request(base + 'api/token', data=b'', method='PUT', headers={
            'X-aliyun-ecs-metadata-token-ttl-seconds': '60'}), timeout=3) as response:
        token = response.read(4096).decode()
    with opener.open(Request(base + 'meta-data/instance-id', headers={
            'X-aliyun-ecs-metadata-token': token}), timeout=3) as response:
        require(response.read(256).decode().strip() == expected['instanceId'], 'Deployment instance identity differs')
    return {'instanceId': expected['instanceId'], 'machineId': expected['machineId'], 'executionLocation': 'ECS'}


def read_private(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path, 'Admission receipt must be an explicit canonical path')
    value = path.stat()
    require(stat.S_ISREG(value.st_mode) and value.st_uid in (0, os.geteuid()) and value.st_nlink == 1
            and not value.st_mode & 0o077 and value.st_size <= 16*1024*1024, 'Admission receipt must be a bounded private file')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Repeated admission receipt field')
            result[key] = value
        return result
    data = path.read_bytes()
    return json.loads(data, object_pairs_hook=pairs), hashlib.sha256(data).hexdigest()


def child_receipt(parent, reference):
    require(isinstance(reference, dict) and isinstance(reference.get('file'), str)
            and SHA.fullmatch(reference.get('sha256', '')), 'Invalid evidence reference')
    relative = PurePosixPath(reference['file'])
    require(not relative.is_absolute() and '..' not in relative.parts and '\\' not in reference['file'], 'Evidence reference escaped its private attempt')
    path = Path(parent).parent.joinpath(*relative.parts)
    value, sha = read_private(path)
    require(sha == reference['sha256'], 'Evidence file checksum differs')
    return value


def validate_migration_receipts(path, *, contract_sha, sql_sha, server_uuid, target_schema, live_metadata_sha,
                                scope='production-migration'):
    """Validate the non-circular evidence/proof chain; never trust a readiness flag."""
    receipt, receipt_sha = read_private(path)
    require(receipt.get('kind') == 'doorhandle-compact-migration' and receipt.get('schemaVersion') == 1
            and receipt.get('status') == 'VERIFIED', 'A verified complete migration is required')
    expected = {'contractSha256': contract_sha, 'sqlSha256': sql_sha, 'serverUuid': server_uuid,
                'targetSchema': target_schema, 'targetMetadataSha256': live_metadata_sha}
    require(all(receipt.get(name) == value for name, value in expected.items()), 'Migration receipt does not match the current schema and source build')
    require(receipt.get('scope') == scope and receipt.get('sourceTableCount') == 131
            and receipt.get('targetTableCount') == 29 and receipt.get('foreignKeysValidated') is True,
            'Migration has not proved the complete source and target scope')
    evidence = child_receipt(path, receipt.get('evidence'))
    require(evidence.get('kind') == 'doorhandle-compact-migration-evidence' and evidence.get('status') == 'COPY_VERIFIED'
            and evidence.get('scope') == scope
            and all(evidence.get(name) == value for name, value in expected.items()), 'Migration evidence context differs')
    require(receipt.get('sourceSchema') == evidence.get('sourceSchema')
            and receipt.get('attempt') == evidence.get('attempt')
            and receipt.get('ecs') == evidence.get('ecs')
            and receipt.get('copyPlanSha256') == evidence.get('copyPlanSha256')
            and receipt.get('freezeEvidenceSha256') == evidence.get('freezeEvidenceSha256')
            and receipt.get('sourceSnapshotSha256') == evidence.get('sourceSnapshotSha256')
            and receipt.get('targetSnapshotSha256') == evidence.get('targetSnapshotSha256'), 'Migration provenance chain differs')
    recovery = receipt.get('recovery')
    require(isinstance(recovery, dict) and set(recovery) == {'source', 'target'}, 'Both source and target restoration proofs are required')
    for purpose in ('source', 'target'):
        proof = child_receipt(path, recovery[purpose])
        original = receipt.get('sourceSchema') if purpose == 'source' else target_schema
        require(proof.get('kind') == 'doorhandle-compact-recovery' and proof.get('schemaVersion') == 1
                and proof.get('status') == 'VERIFIED' and proof.get('purpose') == purpose
                and proof.get('originalSchema') == original
                and proof.get('migrationEvidenceSha256') == receipt['evidence']['sha256'], 'Restoration proof is not bound to this migration attempt')
        require(proof.get('contractSha256') == contract_sha and proof.get('sqlSha256') == sql_sha
                and proof.get('targetMetadataSha256') == live_metadata_sha
                and SHA.fullmatch(proof.get('expectedSnapshotSha256', ''))
                and proof.get('expectedSnapshotSha256') == proof.get('restoredSnapshotSha256')
                and proof['expectedSnapshotSha256'] == receipt.get(purpose + 'SnapshotSha256')
                and proof.get('restoredTableCount') == (131 if purpose == 'source' else 29), 'Restoration verification is incomplete')
        require(all(proof.get(name) == receipt.get(name) for name in
                    ('attempt', 'ecs', 'serverUuid', 'sourceSchema', 'targetSchema', 'copyPlanSha256')),
                'Restoration proof belongs to a different migration provenance')
        if purpose == 'target':
            require(proof.get('restoredMetadataSha256') == live_metadata_sha, 'Restored target structure differs from the admitted compact schema')
        else:
            require(SHA.fullmatch(receipt.get('sourceMetadataSha256', ''))
                    and proof.get('restoredMetadataSha256') == receipt['sourceMetadataSha256'],
                    'Restored source structure differs from the original complete schema')
    return {'migrationReceiptSha256': receipt_sha, 'attempt': receipt['attempt'], 'ecs': receipt['ecs'],
            'sourceSchema': receipt['sourceSchema'], **expected}


def source_catalog(source_root):
    source = Path(source_root).resolve(strict=True)
    compiler = module('compact_deploy_source_compiler', source/'script/schema/build_compact_schema.py')
    _, catalog = compiler.compile_schema()
    require(catalog['tableCount'] == 29 and len(catalog['tables']) == 29, 'Unexpected compact source table catalog')
    return source, catalog


def inspect_database(mysql, source_root, *, require_quiescent=False):
    common = module('compact_schema_common', Path(__file__).with_name('assignment-compat.py'))
    source, catalog = source_catalog(source_root)
    def query(sql):
        return [json.loads(line) for line in common.db(mysql, sql).splitlines()]
    info = query("SELECT JSON_OBJECT('serverUuid',@@server_uuid,'database',DATABASE());")
    require(len(info) == 1 and info[0]['database'], 'Actual database identity is unavailable')
    snapshot = metadata_snapshot(query)
    require(len(snapshot['catalog']) == 29 and {item['name'] for item in snapshot['catalog']} == set(catalog['tables'])
            and all(item['type'] == 'BASE TABLE' and item['engine'] == 'InnoDB' for item in snapshot['catalog']), 'Actual schema is not exactly the reviewed 29 InnoDB base tables')
    require({(item['name'], item['table'], item['timing'], item['event']) for item in snapshot['triggers']}
            == {(item['name'], item['table'], item['timing'], item['event']) for item in catalog['triggers']}, 'Compact database protection trigger catalog differs')
    require(common.db(mysql, "SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA=DATABASE();") == '0'
            and common.db(mysql, "SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE();") == '0',
            'Unregistered database events or routines prevent complete compact admission and recovery')
    if require_quiescent:
        statements = (
            "SELECT COUNT(*) FROM workflow_instance WHERE kind='CONVERSATION_INPUT' AND status IN ('QUEUED','STARTED');",
            "SELECT COUNT(*) FROM workflow_instance WHERE (kind='WORKBENCH_EXECUTION' AND status IN ('RUNNING','READY')) OR (kind='WORKBENCH_CHILD' AND status IN ('QUEUED','RUNNING'));",
            "SELECT COUNT(*) FROM workflow_instance WHERE kind='MCP_INSTALL_JOB' AND status IN ('QUEUED','RUNNING');",
            "SELECT COUNT(*) FROM workflow_instance WHERE kind='MCP_EXECUTION' AND (status IN ('OPENING','RUNNING','NEEDS_REVIEW') OR (status='EXITED' AND COALESCE(mcp_exit_verified,FALSE)=FALSE));",
            "SELECT COUNT(*) FROM workflow_instance WHERE (kind='MCP_INSTALL_WORKER' AND status='RUNNING') OR (kind='MCP_EXECUTION_COMMAND' AND status='STARTED');")
        require(all(common.db(mysql, sql) == '0' for sql in statements), 'Copied executable work must be reconciled before rehearsal startup')
    require(metadata_snapshot(query) == snapshot, 'Database metadata changed during compact admission')
    return {'serverUuid': info[0]['serverUuid'], 'targetSchema': info[0]['database'], 'tableCount': 29,
            'contractSha256': catalog['contractSha256'], 'sqlSha256': catalog['sqlSha256'],
            'metadataSha256': metadata_sha256(snapshot)}


def compact_image(reference, common):
    rows = json.loads(common.docker('image', 'inspect', reference))
    require(len(rows) == 1 and common.DIGEST.fullmatch(rows[0].get('Id', ''))
            and (rows[0].get('Config', {}).get('Labels') or {}).get(LABEL) == FORMAT,
            'Application image does not declare the reviewed compact schema reader')
    return rows[0]['Id']


def application_grants(mysql, environment, common):
    user = environment.get('DB_USERNAME', '')
    password = environment.get('DB_PASSWORD', '')
    require(isinstance(user, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', user)
            and user.lower() != 'root' and isinstance(password, str) and password,
            'An explicit non-root compact application account is required')
    identity = "SUBSTRING_INDEX(GRANTEE,'@',1)=CONCAT(CHAR(39),'" + user + "',CHAR(39))"
    require(common.db(mysql, 'SELECT COUNT(*) FROM information_schema.USER_PRIVILEGES WHERE ' + identity
                      + " AND PRIVILEGE_TYPE<>'USAGE';") == '0', 'Application account must not have global privileges')
    require(common.db(mysql, 'SELECT COUNT(*) FROM information_schema.SCHEMA_PRIVILEGES WHERE ' + identity
                      + " AND (TABLE_SCHEMA<>DATABASE() OR PRIVILEGE_TYPE NOT IN ('SELECT','INSERT','UPDATE','DELETE')); ") == '0',
            'Application account must have no old-schema, DDL or administrative grants')
    require(common.db(mysql, 'SELECT COUNT(*) FROM information_schema.TABLE_PRIVILEGES WHERE ' + identity
                      + " AND (TABLE_SCHEMA<>DATABASE() OR PRIVILEGE_TYPE NOT IN ('SELECT','INSERT','UPDATE','DELETE')); ") == '0',
            'Application table grants exceed compact runtime privileges')
    require(common.db(mysql, 'SELECT COUNT(DISTINCT PRIVILEGE_TYPE) FROM information_schema.SCHEMA_PRIVILEGES WHERE '
                      + identity + " AND TABLE_SCHEMA=DATABASE() AND PRIVILEGE_TYPE IN ('SELECT','INSERT','UPDATE','DELETE');") == '4',
            'Compact runtime requires direct schema-wide DML grants')
    require(common.db(mysql, "SELECT COUNT(*) FROM mysql.role_edges WHERE TO_USER='" + user + "';") == '0'
            and common.db(mysql, "SELECT COUNT(*) FROM mysql.proxies_priv WHERE User='" + user + "';") == '0',
            'Compact runtime cannot inherit administrative or source privileges through roles or proxies')
    require(common.db(mysql, 'SELECT @@GLOBAL.mandatory_roles;') in ('', 'NONE'),
            'Unreviewed mandatory roles prevent a DML-only compact runtime account proof')


def connection_binding(state, config, migration_receipt=None):
    state = Path(state)
    binding, _ = read_private(state/'compact-connection.json')
    overlay_file = state/'compact-connection.override.yml'
    overlay, overlay_sha = read_private(overlay_file)  # JSON is the required YAML subset.
    require(binding.get('schemaVersion') == 1 and binding.get('overlaySha256') == overlay_sha,
            'Compact connection overlay is not bound to the cutover journal')
    receipt_path = Path(binding.get('migrationReceiptFile', ''))
    _, receipt_sha = read_private(receipt_path)
    require(binding.get('migrationReceiptSha256') == receipt_sha
            and (migration_receipt is None or Path(migration_receipt) == receipt_path), 'Compact connection uses different migration evidence')
    services = overlay.get('services', {})
    require(set(services) == {'backend', 'detection-worker'}
            and all(set(value) == {'environment'} for value in services.values()), 'Compact overlay may only override application database connections')
    expected = {'backend': {'DB_URL', 'DB_USERNAME', 'DB_PASSWORD', 'APP_BUSINESS_SEED_ENABLED'},
                'detection-worker': {'DETECTION_RECEIPT_DB_DATABASE', 'DETECTION_RECEIPT_DB_USER', 'DETECTION_RECEIPT_DB_PASSWORD'}}
    for service, fields in expected.items():
        environment = services[service].get('environment', {})
        actual = config.get('services', {}).get(service, {}).get('environment', {})
        require(set(environment) == fields and all(actual.get(key) == value or
                (key == 'APP_BUSINESS_SEED_ENABLED' and value is False and actual.get(key) == 'false')
                for key, value in environment.items()), 'Resolved application connection differs from the private cutover overlay')
    require(services['backend']['environment']['APP_BUSINESS_SEED_ENABLED'] in (False, 'false'), 'Legacy startup seed may not be enabled by a cutover overlay')
    return binding, receipt_path


def guard(state, config, source_root, migration_receipt=None, recovery_receipt=None, *, project='doorhandlecatch-monolith', write_receipt=True, allow_cutover=False):
    # recovery_receipt is deliberately not accepted as an unbound shortcut: both proofs
    # must occur in the final migration receipt's checksummed evidence chain.
    common = module('compact_release_common', Path(__file__).with_name('assignment-compat.py'))
    binding, migration_receipt = connection_binding(state, config, migration_receipt)
    require(binding.get('phase') == 'ACTIVE' or allow_cutover and binding.get('phase') in ('MIGRATED', 'ACTIVATING'),
            'The first compact cutover has not completed its health and publication checks')
    original, _ = read_private(migration_receipt)
    admitted_ecs = ecs_identity(original.get('ecs'))
    backend = config.get('services', {}).get('backend', {})
    environment = backend.get('environment', {})
    require(isinstance(environment, dict) and not common.boolean(environment, 'APP_BUSINESS_SEED_ENABLED'), 'Legacy startup business seeding must remain disabled')
    target = compact_image(backend.get('image'), common)
    mysql = common.selected_mysql(common.container(project, 'mysql'), environment)
    observed = inspect_database(mysql, source_root)
    require(binding.get('targetSchema') == observed['targetSchema'] and binding.get('serverUuid') == observed['serverUuid'],
            'Actual compact database differs from the cutover connection journal')
    application_grants(mysql, environment, common)
    worker = config.get('services', {}).get('detection-worker', {}).get('environment', {})
    compact_image(config['services']['detection-worker'].get('image'), common)
    require(worker.get('DETECTION_RECEIPT_DB_HOST') == 'mysql'
            and str(worker.get('DETECTION_RECEIPT_DB_PORT')) == '3306'
            and worker.get('DETECTION_RECEIPT_DB_DATABASE') == observed['targetSchema'],
            'Worker receipt storage must target the same owned compact MySQL endpoint')
    application_grants(mysql, {'DB_USERNAME': worker.get('DETECTION_RECEIPT_DB_USER'),
                              'DB_PASSWORD': worker.get('DETECTION_RECEIPT_DB_PASSWORD')}, common)
    if not allow_cutover:
        live_worker = common.container(project, 'detection-worker')
        live_environment = common.environment(live_worker)
        require(live_worker['Image'] == compact_image(config['services']['detection-worker'].get('image'), common)
                and live_worker['State']['Running'] and live_worker['State'].get('Health', {}).get('Status') == 'healthy'
                and all(str(live_environment.get(name)) == str(worker.get(name)) for name in (
                    'DETECTION_WORKER_RECEIPTS_ENABLED', 'DETECTION_RECEIPT_DB_HOST', 'DETECTION_RECEIPT_DB_PORT',
                    'DETECTION_RECEIPT_DB_DATABASE', 'DETECTION_RECEIPT_DB_USER', 'DETECTION_RECEIPT_DB_PASSWORD')),
                'Running worker identity or actual receipt database binding differs from the pinned compact runtime')
    proof = validate_migration_receipts(migration_receipt, contract_sha=observed['contractSha256'],
                                      sql_sha=observed['sqlSha256'], server_uuid=observed['serverUuid'],
                                      target_schema=observed['targetSchema'], live_metadata_sha=observed['metadataSha256'],
                                      scope='production-migration' if project == 'doorhandlecatch-monolith' else 'ecs-disposable-migration')
    require(proof['ecs'] == admitted_ecs, 'Migration ECS binding changed during admission')
    result = {'schemaVersion': 1, 'kind': 'doorhandle-compact-deployment', 'project': project,
              'targetImage': target, 'tableCount': 29, 'status': 'VERIFIED', **proof}
    if write_receipt:
        common.write_json(common.private_state(state)/'compact-schema-admission.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--migration-receipt')
    parser.add_argument('--project', default='doorhandlecatch-monolith')
    args = parser.parse_args()
    try:
        require(sys.platform == 'linux', 'Compact release admission runs on ECS Linux only')
        raw = sys.stdin.buffer.read(8*1024*1024+1)
        require(len(raw) <= 8*1024*1024, 'Compose metadata exceeded its reviewed bound')
        config = json.loads(raw)
        result = guard(Path(args.state), config, Path(args.source), Path(args.migration_receipt) if args.migration_receipt else None, project=args.project)
        print(json.dumps(result))
    except Exception:
        print('Compact schema or migration/recovery evidence could not be verified; no activation approved.', file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
