"""Actual post-business recovery of this runtime's owned compact schema and key.

Reuses the complete migration backup/restore primitives, without manufacturing a
legacy migration receipt. Source schemas, failed clones and private evidence are
retained. A failure leaves ingress and writers stopped, never pointed backwards.
"""
import base64
import copy
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import time
import urllib.parse


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def memory_revision(ctx):
    script = """import json,os,urllib.request
r=urllib.request.Request('http://127.0.0.1:8081/internal/model-config/status',headers={'x-doorhandle-memory-token':os.environ['MEM0_BRIDGE_TOKEN']})
with urllib.request.urlopen(r,timeout=10) as s: print(s.read().decode())
"""
    value = json.loads(ctx.ops.docker('exec', ctx.row('mem0')['Id'], 'python', '-B', '-c', script, timeout=15))
    require(type(value.get('revision')) is int and value['revision'] > 0,
            'Wrong-key acceptance requires an actually persisted encrypted memory model revision')
    return value['revision']


def business_readback(ctx):
    task = ctx.request('inspector', 'GET', '/api/detection/tasks/' + ctx.report_task_id)
    require(task['status'] == 'COMPLETED' and task['successfulImages'] > 0 and task['failedImages'] == 0,
            'Recovered runtime cannot read its actual completed worker task')
    descriptor = ctx.owner['scenarios']['report-draft-review-export-delivery']
    relative = Path(descriptor['file'])
    require(not relative.is_absolute() and '..' not in relative.parts, 'Report evidence escaped its runtime')
    artifact = ctx.attempt / relative
    require(artifact.resolve(strict=True) == artifact and artifact.is_relative_to(ctx.directory)
            and digest(artifact) == descriptor['sha256'], 'Actual report scenario evidence changed')
    report_evidence, _ = ctx.guard.read_private(artifact)
    require(report_evidence.get('status') == 'PASS' and report_evidence.get('identity') == ctx.identity,
            'Report evidence belongs to another execution')
    report_id = report_evidence['observations']['reportId']
    report = ctx.request('inspector', 'GET', '/api/detection/reports/' + report_id)
    require(report['status'] == 'APPROVED' and report['taskId'] == ctx.report_task_id
            and report['snapshotSha256'] == report_evidence['observations']['snapshotSha256'],
            'Recovered approval lost its immutable actual report snapshot')
    memory = ctx.request('inspector', 'GET', '/api/agent/memories/' + ctx.owner['memoryId'])
    require(memory['lifecycle']['state'] == 'EXCLUDED' and re.fullmatch(r'[a-f0-9]{64}', memory['digest']),
            'Recovered memory lost its actual governed state')
    run = ctx.request('inspector', 'GET', '/api/agent/runs/' + ctx.sdk_source_run_id)
    require(run['status'] == 'COMPLETED' and run['entryPoint'] == 'CHILD',
            'Recovered SDK source is not the persisted real specialist execution')
    configuration = ctx.request('supervisor', 'GET', '/api/agent/model-config')
    require(configuration['activeRevision'] == ctx.owner['modelRevision'], 'Recovered active model revision changed')
    return {'taskId': ctx.report_task_id, 'taskStatus': task['status'], 'successfulImages': task['successfulImages'],
            'reportId': report_id, 'reportVersion': report['version'], 'reportSnapshotSha256': report['snapshotSha256'],
            'memoryId': ctx.owner['memoryId'], 'memoryDigest': memory['digest'], 'memoryState': memory['lifecycle']['state'],
            'sdkRunId': ctx.sdk_source_run_id, 'sdkRunStatus': run['status'],
            'activeModelRevision': configuration['activeRevision'], 'memoryModelRevision': memory_revision(ctx)}


def stopped(ctx, names):
    result = []
    for name in names:
        row = ctx.row(name)
        require(not row['State']['Running'] and not row['State'].get('Restarting') and row['State']['Pid'] == 0,
                'A runtime writer or ingress is still alive during recovery')
        result.append({'service': name, 'containerId': row['Id'], 'image': row['Image'], 'pid': 0})
    return result


def rows_preserved(before, after):
    require(set(before['tables']) == set(after['tables']), 'A failed key attempt changed the restored table catalog')
    for name, original in before['tables'].items():
        current = after['tables'][name]
        require(current['rows'] == original['rows'] and current['rowsSha256'] == original['rowsSha256'],
                'A wrong-key process changed restored business records')
        # Duplicate INSERT attempts can reserve auto ids during failed startup.
        # Preserve and report these actual reservations; never reset backwards.
        if original['autoIncrement'] is not None:
            require(current['autoIncrement'] is not None and int(current['autoIncrement']) >= int(original['autoIncrement']),
                    'A wrong-key process lowered a restored identity high-water mark')


def restore_clone(ctx, manifest_path, schema, context):
    """Same backup and physical restore algorithm, with an independent runtime purpose."""
    m = ctx.migration; mysql = ctx.db.mysql
    manifest_path, manifest, manifest_sha = m.private_json(manifest_path)
    require(manifest['kind'] == 'doorhandle-mysql-private-backup' and manifest['purpose'] == 'runtime-post-business'
            and manifest['migrationContext'] == context and manifest['serverUuid'] == ctx.owner['serverUuid']
            and manifest['schema'] == ctx.owner['targetSchema'] and len(manifest['tables']) == 29,
            'Post-business backup is not bound to this exact runtime and server')
    restoration_policy = m.snapshot_ddl_policy(manifest)
    require(m.sha_json(m.snapshot_hash_payload(manifest)) == manifest['snapshotSha256'],
            'Post-business backup snapshot or its explicit DDL policy digest differs')
    data = manifest_path.parent / manifest['data']['file']
    require(data.name == 'data.sql' and data.resolve(strict=True) == data and data.is_file()
            and data.stat().st_size == manifest['data']['bytes'] and digest(data) == manifest['data']['sha256'],
            'Post-business data backup is incomplete or changed')
    m.new_schema(mysql, schema)
    foreign = []
    for table in sorted(manifest['tables']):
        ddl = manifest['createTables'][table]
        backed_up_ddl = m.ddl_policy.normalize_ddl(ddl, manifest['schema'], manifest['tables'][table]['columns'],
                                                  policy=restoration_policy or m.ddl_policy.RAW_POLICY)
        require(hashlib.sha256(backed_up_ddl.encode()).hexdigest()
                == manifest['tables'][table]['ddlSha256'], 'Backed-up post-business DDL changed')
        ddl = m.normalize_self(ddl, manifest['schema'], schema)
        create, relations = m.remove_inline_foreign_keys(ddl, schema)
        mysql.script(create + ';', database=schema, label='runtime-restore-create')
        foreign.extend(relations)
    m.restore_data(mysql, schema, manifest, data)
    for table, details in manifest['tables'].items():
        sequence = details['autoIncrement']
        if sequence is not None:
            require(re.fullmatch(r'[0-9]{1,20}', sequence), 'Backed-up identity high-water is malformed')
            mysql.script('ALTER TABLE ' + m.quoted(table) + ' AUTO_INCREMENT=' + sequence + ';',
                         database=schema, label='runtime-restore-sequence')
    m.install_relations(mysql, schema, foreign)
    current_user = mysql.single("SELECT JSON_OBJECT('user',CURRENT_USER());")['user']
    expected_definer = 'mig_' + ctx.fixture_owner['token'] + '@%'
    for definer in {item['definer'] for item in manifest['triggers']}:
        if definer == current_user:
            continue
        require(definer == expected_definer, 'Restored guards have an unowned or unexpected definer')
        user, host = definer.rsplit('@', 1)
        grantee = "CONCAT(QUOTE(" + m.literal(user) + "),'@',QUOTE(" + m.literal(host) + '))'
        grants = mysql.json_rows("SELECT JSON_OBJECT('p',privilege_type) FROM information_schema.schema_privileges WHERE table_schema="
            + m.literal(manifest['schema']) + ' AND grantee=' + grantee + ';')
        require({'SELECT', 'TRIGGER'} <= {item['p'] for item in grants}, 'The original owned trigger definer has no direct source authority')
        mysql.script('GRANT SELECT,TRIGGER ON ' + m.quoted(schema) + '.* TO ' + m.literal(user) + '@' + m.literal(host) + ';',
                     label='runtime-restore-definer')
    m.install_triggers(mysql, schema, manifest['schema'], manifest['triggers'])
    snapshot = m.schema_snapshot(mysql, schema, manifest['tables'], ddl_hash_policy=restoration_policy)
    _, meta = m.metadata_snapshot(mysql, schema)
    require(snapshot['snapshotSha256'] == manifest['snapshotSha256'] and meta == manifest['metadataSha256'],
            'The actual restored 29-table rows, NULLs, DDL, guards, foreign keys or high-water marks differ')
    return snapshot, meta, manifest_sha


def switch_database(ctx, schema, credentials):
    candidate = copy.deepcopy(ctx.config)
    backend = candidate['services']['backend']['environment']
    previous = urllib.parse.urlsplit(backend['DB_URL'][5:])
    require(previous.hostname == 'mysql' and previous.port == ctx.owner['mysqlPort']
            and previous.path == '/' + ctx.db.schema, 'Runtime database endpoint changed before restore cutover')
    backend.update(DB_URL='jdbc:' + urllib.parse.urlunsplit(previous._replace(path='/' + schema)),
                   DB_USERNAME=credentials['app']['username'], DB_PASSWORD=credentials['app']['password'])
    worker = candidate['services']['detection-worker']['environment']
    worker.update(DETECTION_RECEIPT_DB_DATABASE=schema, DETECTION_RECEIPT_DB_USER=credentials['worker']['username'],
                  DETECTION_RECEIPT_DB_PASSWORD=credentials['worker']['password'])
    # Persist ownership and desired endpoints before any new process can write.
    ctx.owner['preRecoverySchema'] = ctx.owner['targetSchema']
    ctx.owner['targetSchema'] = schema
    ctx.db.schema = schema
    ctx.mysql_row['_doorhandle_database'] = schema
    ctx.config = candidate
    ctx.validate_config(candidate)
    ctx.common.write_json(ctx.directory / 'compose.json', candidate)
    ctx.save('RECOVERY_CONNECTION_SELECTED')
    ctx.clients = {}


def wrong_key(ctx, snapshot, folder):
    original = ctx.master_key
    require(len(base64.b64decode(original.strip(), validate=True)) == 32
            and ctx.key_reference.read_bytes() == original, 'The owned external key reference changed')
    invalid = base64.b64encode(secrets.token_bytes(32)) + b'\n'
    require(invalid != original, 'Wrong-key scenario did not select a different key')
    evidence = {}
    try:
        ctx.install_key(invalid)
        ctx.dc('up', '-d', '--no-deps', '--force-recreate', '--no-build', '--pull', 'never', 'backend', 'mem0', timeout=150)
        deadline = time.monotonic() + 180
        while True:
            found = dict(evidence)
            for name in ('backend', 'mem0'):
                if name in found:
                    continue
                node = ctx.row(name)
                # Docker sends a container's stderr to its own stderr; preserve
                # both streams privately, including Python startup exceptions.
                logged = subprocess.run([str(ctx.db.mysql.program), 'logs', '--tail', '250', node['Id']],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20, check=True,
                    env=ctx.migration.Mysql.environment())
                raw = logged.stdout
                require(len(raw) <= 4 * 1024 * 1024, 'Wrong-key diagnostic exceeds its private bound')
                text = raw.decode('utf8', errors='replace')
                rejected = ('模型配置完整性校验失败' in text and 'ModelConfigCipher' in text) if name == 'backend' else 'Encrypted model configuration is invalid' in text
                if rejected:
                    require(not ctx.ops.healthy(node['Id']), 'A process accepted a mismatched model key')
                    file = folder / (name + '-wrong-key.log')
                    with file.open('xb') as stream:
                        file.chmod(0o600); stream.write(raw)
                    found[name] = {'containerId': node['Id'], 'image': node['Image'], 'logSha256': digest(file),
                                   'keyIntegrityRejected': True, 'healthy': False}
            evidence = found
            if len(found) == 2:
                break
            require(time.monotonic() < deadline, 'Wrong-key startup did not produce actual cipher rejection evidence')
            time.sleep(2)
    finally:
        # No healthy ingress is allowed during either failure or key repair.
        ctx.stop_writers()
        ctx.install_key(original)
    after = ctx.migration.schema_snapshot(ctx.db.mysql, ctx.db.schema, snapshot['tables'])
    _, metadata = ctx.migration.metadata_snapshot(ctx.db.mysql, ctx.db.schema)
    rows_preserved(snapshot, after)
    return evidence, after, metadata


def run(ctx):
    m = ctx.migration
    require(ctx.guard.ecs_identity(ctx.identity) == ctx.identity, 'Runtime recovery identity changed')
    source = ctx.db.schema
    require(source == ctx.owner['targetSchema'] and re.fullmatch(r'doorhandle_compact_candidate_[a-f0-9]{10}', source)
            and source != ctx.settings['sourceSchema']
            and ctx.owner['mysqlContainerId'] != ctx.settings['sourceMysqlContainerId'],
            'Recovery requires this attempt\'s disposable candidate, never the old business source')
    require(m.sha_file(Path(ctx.owner['migrationReceiptFile'])) == ctx.owner['migrationReceiptSha256'],
            'The original migration evidence changed before post-business recovery')
    baseline = business_readback(ctx)
    require(baseline['memoryModelRevision'] == ctx.owner['modelRevision'], 'Memory key history is not the actually published owned model revision')
    folder = ctx.directory / 'post-business-recovery'; folder.mkdir(mode=0o700)
    m.write_json(folder / 'application-before.json', ctx.config)
    config_sha = digest(folder / 'application-before.json')
    restore_schema = 'doorhandle_compact_candidate_' + secrets.token_hex(5)
    require(restore_schema != source, 'Recovery clone must be distinct')
    context = {**ctx.context(), 'project': ctx.project, 'serverUuid': ctx.owner['serverUuid'],
               'mysqlContainerId': ctx.owner['mysqlContainerId'], 'originalSchema': source, 'restoreSchema': restore_schema,
               'originalMigrationReceiptSha256': ctx.owner['migrationReceiptSha256'], 'applicationBackupSha256': config_sha}
    ctx.owner['postBusinessRecovery'] = {'restoreSchema': restore_schema, 'phase': 'FREEZING'}; ctx.save()
    try:
        ctx.stop_writers()
        writers = stopped(ctx, [name for name in ('nginx', 'backend', 'detection-worker', 'mem0', 'mcp-runner') if name in ctx.config['services']])
        _, catalog, _, _, _ = m.compiled_target_parts()
        server = ctx.db.mysql.admitted_server()
        with ctx.db.mysql.source_lock(source, catalog['tables']):
            snapshot = m.schema_snapshot(ctx.db.mysql, source, catalog['tables'])
            _, metadata = m.metadata_snapshot(ctx.db.mysql, source)
            require(len(snapshot['tables']) == 29, 'Post-business backup must cover all 29 tables')
            ctx.admit_backup_phase(snapshot)
            native_backup = ctx.native.snapshot_runtime(ctx, folder / 'native-volumes')
            backup = m.backup_schema(ctx.db.mysql, snapshot, folder / 'backup', purpose='runtime-post-business', migration_context=context)
            ctx.admit_restore_phase(backup)
            restored, restored_meta, backup_sha = restore_clone(ctx, backup, restore_schema, context)
            require(restored_meta == metadata and m.schema_snapshot(ctx.db.mysql, source, catalog['tables'])['snapshotSha256'] == snapshot['snapshotSha256'],
                    'Recovery changed the original owned business schema')
        ctx.owner['postBusinessRecovery'].update(phase='ROWS_RESTORED', backupManifestSha256=backup_sha,
            originalSnapshotSha256=snapshot['snapshotSha256'], restoredSnapshotSha256=restored['snapshotSha256'])
        ctx.save()
        credentials = ctx.create_dml_accounts(restore_schema)
        switch_database(ctx, restore_schema, credentials)
        native_materialization = ctx.native.restore_runtime(ctx, native_backup)
        m.write_json(folder / 'application-restored.json', ctx.config)
        config_restored_sha = digest(folder / 'application-restored.json')
        rejected, after_failure, after_meta = wrong_key(ctx, restored, folder)
        require(after_meta == metadata, 'Wrong-key startup changed the restored schema structure')
        require(ctx.db.mysql.admitted_server() == server, 'Owned MySQL identity changed during recovery')
        ctx.dc('up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '300',
               'mcp-runner', 'mem0', 'backend', 'detection-worker', 'nginx', timeout=420)
        for name in ('backend', 'mem0', 'detection-worker', 'nginx', 'mcp-runner'):
            require(ctx.ops.healthy(ctx.row(name)['Id']), 'A restored candidate writer did not become healthy with the original key')
        require(ctx.key_reference.read_bytes() == ctx.master_key, 'The original external key reference was replaced')
        ctx.clients = {}
        actual_backend = ctx.common.environment(ctx.row('backend'))
        actual_worker = ctx.common.environment(ctx.row('detection-worker'))
        require(urllib.parse.urlsplit(actual_backend['DB_URL'][5:]).path == '/' + restore_schema
                and actual_worker['DETECTION_RECEIPT_DB_DATABASE'] == restore_schema,
                'Actual running processes did not select the restored schema')
        readback = business_readback(ctx)
        require(readback == baseline, 'Actual restored application readback differs from the pre-backup business evidence')
        native_readback = ctx.native.verify_runtime(ctx, 'after-volume-restore')
        monitoring_readback = ctx.observability.verify(ctx, 'after-volume-restore')
        require(m.schema_snapshot(ctx.db.mysql, source, snapshot['tables'])['snapshotSha256'] == snapshot['snapshotSha256']
                and m.metadata_snapshot(ctx.db.mysql, source)[1] == metadata,
                'The retained original owned schema changed after application connection recovery')
        result = {**context, 'schemaVersion': 1, 'kind': 'doorhandle-runtime-post-business-recovery', 'status': 'VERIFIED',
            'sourceSnapshotSha256': snapshot['snapshotSha256'], 'restoredSnapshotSha256': restored['snapshotSha256'],
            'metadataSha256': metadata, 'restoredMetadataSha256': restored_meta, 'backupManifestSha256': backup_sha,
            'applicationBackupSha256': config_sha, 'applicationRestoredSha256': config_restored_sha,
            'restoredTableCount': 29, 'frozenWriters': writers, 'wrongKeyRejections': rejected,
            'postWrongKeySnapshotSha256': after_failure['snapshotSha256'],
            'postWrongKeyAutoIncrement': {name: row['autoIncrement'] for name, row in after_failure['tables'].items()},
            'keyReferenceSha256': digest(ctx.key_reference), 'applicationReadback': readback,
            'nativeRecoveryProofSha256': digest(native_backup / 'native-recovery.json'),
            'nativeMaterialization': native_materialization, 'nativeReadback': native_readback,
            'observabilityReadback': monitoring_readback,
            'originalSourceRetained': True, 'finishedAtUtc': m.utc_now()}
        file = folder / 'recovery-receipt.json'; m.write_json(file, result)
        ctx.owner['postBusinessRecovery'].update(phase='VERIFIED', receiptFile=str(file), receiptSha256=digest(file)); ctx.save('RUNNING')
        return ctx.record('compact-application-upgrade-recovery', {'originalSchema': source, 'restoredSchema': restore_schema,
            'postBusinessRecoveryReceiptSha256': digest(file), 'backupManifestSha256': backup_sha,
            'postBusinessSnapshotSha256': snapshot['snapshotSha256'], 'restoredSnapshotSha256': restored['snapshotSha256'],
            'restoredMetadataSha256': restored_meta, 'restoredTableCount': 29, 'wrongKeyRejectedServices': sorted(rejected),
            'applicationReadback': readback, 'actualProcessesUseRestoredSchema': True})
    except BaseException:
        ctx.owner['postBusinessRecovery']['phase'] = 'FAILED_OR_UNKNOWN_STOPPED'
        ctx.save()
        ctx.stop_writers()
        raise
