"""ECS-only byte-custody and isolated SQL recovery contracts; no local execution."""
import copy
import gzip
import hashlib
import importlib.util
from pathlib import Path
import shutil
import select
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


custody = load('fresh_mysql_custody_contract', 'script/jenkins/preserve-local-mysql.py')
recovery = load('fresh_mysql_recovery_contract', 'script/jenkins/restore-local-mysql.py')


@pytest.fixture
def export_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(custody, 'LOCAL_ROOT', tmp_path)
    export = tmp_path / 'work/data-migration-20261107' / custody.EXPORT_DIRECTORY
    export.mkdir(parents=True)
    control = tmp_path / 'work/jenkins' / custody.CONTROL_DIRECTORY / 'control-result.json'
    control.parent.mkdir(parents=True)
    raw = b'-- private synthetic original SQL byte fixture, never executed\n'
    compressed = gzip.compress(raw)
    monkeypatch.setattr(custody, 'RAW_BYTES', len(raw)); monkeypatch.setattr(custody, 'RAW_SHA', hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(custody, 'GZIP_BYTES', len(compressed)); monkeypatch.setattr(custody, 'GZIP_SHA', hashlib.sha256(compressed).hexdigest())
    for name in custody.MEMBERS - {'public-manifest.json', 'export-control-private.json'}:
        (export / name).write_bytes(raw if name == 'database.sql' else compressed if name == 'database.sql.gz' else b'{}\n')
    public = {'schemaVersion': 1, 'kind': 'doorhandle-local-mysql-export', 'status': 'LOCAL_EXPORT_COMPLETE_RESTORE_PENDING',
        'sourceSchema': 'doorhandledb', 'sourceEndpoint': '127.0.0.1:3306', 'tableCount': 45,
        'scriptSha256': custody.EXPORT_SCRIPT_SHA, 'rawSqlSha256': custody.RAW_SHA, 'rawSqlBytes': len(raw),
        'gzipSha256': custody.GZIP_SHA, 'gzipBytes': len(compressed), 'actualClientIdentityVerified': True,
        'privateInputFilesRemoved': True, 'credentialsArchived': False, 'gzipByteReadbackVerified': True,
        'sourceDeleted': False, 'servicesChanged': False, 'testsExecuted': False, 'cloudUploaded': False,
        'backupRestoreVerified': False, 'retirementAllowed': False,
        'rowEvidence': 'BEFORE_AFTER_OBSERVATIONS_NOT_THE_DUMP_TRANSACTION',
        'files': {path.name: {'bytes': path.stat().st_size, 'sha256': custody.digest(path)} for path in export.iterdir()}}
    custody.write(export / 'public-manifest.json', public)
    custody.write(control, {'status': 'SCRIPT_COMPLETED', 'scriptSha256': custody.EXPORT_SCRIPT_SHA,
        'credentialInputRemoved': True, 'servicesChanged': False, 'sourceDeleted': False})
    monkeypatch.setattr(custody, 'EXPORT_SHA', custody.digest(export / 'public-manifest.json'))
    monkeypatch.setattr(custody, 'CONTROL_SHA', custody.digest(control))
    output = export.parent / 'local-mysql-custody-synthetic-contract'
    return SimpleNamespace(export=export, control=control, output=output, public=public, raw=raw)


def test_byte_pack_preserves_the_complete_closed_export_and_originals(export_fixture):
    source = export_fixture
    before = {path.name: path.read_bytes() for path in source.export.iterdir()}
    result = custody.pack(source.export, source.control, source.output)
    manifest = custody.read(source.output / 'custody.json')
    assert result['status'] == 'PACKED' and result['databasesOpened'] == 0 and result['files'] == 13
    assert manifest['archiveEncoding'] == 'TAR_GZIP' and custody.validate_package(manifest)
    with tarfile.open(source.output / 'originals.tar.gz', 'r:gz') as package:
        assert set(package.getnames()) == custody.MEMBERS
        for member in package:
            expected = source.control.read_bytes() if member.name == 'export-control-private.json' else before[member.name]
            assert package.extractfile(member).read() == expected
    assert {path.name: path.read_bytes() for path in source.export.iterdir()} == before


@pytest.mark.parametrize('damage', ['partial', 'credential-side-file', 'missing-file', 'raw-changed', 'identity-unverified', 'source-row-hash-claim'])
def test_pack_refuses_incomplete_or_unreviewed_source_before_reporting_success(export_fixture, monkeypatch, damage):
    source = export_fixture
    if damage == 'credential-side-file': (source.export / 'temporary-client-private.ini').write_text('never archived')
    elif damage == 'missing-file': (source.export / 'schema-after.sql').unlink()
    elif damage == 'raw-changed': (source.export / 'database.sql').write_bytes(b'changed private source')
    else:
        value = custody.read(source.export / 'public-manifest.json')
        if damage == 'partial': value['status'] = 'FAILED'
        if damage == 'identity-unverified': value['actualClientIdentityVerified'] = False
        if damage == 'source-row-hash-claim': value['rowEvidence'] = 'SAME_TRANSACTION_SOURCE_ROW_HASHES'
        (source.export / 'public-manifest.json').write_bytes(custody.encoded(value))
        monkeypatch.setattr(custody, 'EXPORT_SHA', custody.digest(source.export / 'public-manifest.json'))
    with pytest.raises(ValueError): custody.pack(source.export, source.control, source.output)
    assert not source.output.exists()


@pytest.mark.parametrize('damage', ['omission', 'duplicate', 'secret-member', 'raw-hash', 'permission-field'])
def test_closed_package_catalogue_rejects_omission_replacement_or_secret_metadata(export_fixture, damage):
    source = export_fixture; custody.pack(source.export, source.control, source.output)
    value = custody.read(source.output / 'custody.json')
    if damage == 'omission': value['files'].pop()
    if damage == 'duplicate': value['files'][1] = copy.deepcopy(value['files'][0])
    if damage == 'secret-member': value['files'][0]['member'] = 'credentials.env'
    if damage == 'raw-hash': next(row for row in value['files'] if row['member'] == 'database.sql')['sha256'] = '0' * 64
    if damage == 'permission-field': value['files'][0]['permissions']['secret'] = 'unreviewed'
    value['catalogSha256'] = custody.catalogue(value['files'])
    with pytest.raises(ValueError): custody.validate_package(value)


def test_gzip_sql_byte_verification_rejects_extra_expanded_bytes(export_fixture):
    path = export_fixture.export / 'database.sql.gz'; path.write_bytes(gzip.compress(export_fixture.raw + b'changed'))
    with pytest.raises(ValueError): custody.verify_gzip(path)


def snapshots():
    tables = {f'table_{index}': {'rows': 1, 'rowsSha256': 'a' * 64, 'autoIncrement': '2',
        'columns': [{'name': 'id', 'type': 'bigint unsigned', 'nullable': 'NO'}], 'indexes': [{'name': 'PRIMARY'}]}
        for index in range(45)}
    first = {'snapshot': {'snapshotSha256': 'b' * 64, 'tables': tables}, 'metadata': {'checks': [], 'foreignKeys': []},
        'extraObjects': {'routines': [], 'events': []}, 'findings': [], 'observedCountsMatch': True,
        'serverUuid': '1' * 36, 'containerId': '1' * 64, 'volume': 'owned-a'}
    second = copy.deepcopy(first); second.update(serverUuid='2' * 36, containerId='2' * 64, volume='owned-b')
    return first, second


def test_independent_double_restore_can_preserve_and_report_original_constraint_defects():
    first, second = snapshots()
    issue = {'kind': 'FOREIGN_KEY', 'table': 'table_0', 'constraint': 'fk_original', 'violations': 2}
    first['findings'] = [issue]; second['findings'] = [copy.deepcopy(issue)]
    recovery.compare_recoveries(first, second)
    assert first['snapshot']['tables']['table_0']['rows'] == 1 and first['findings'][0]['violations'] == 2


@pytest.mark.parametrize('damage', ['same-server', 'same-container', 'same-volume', 'same-count-row-change', 'column-type',
    'index', 'high-water', 'constraint', 'object-definition', 'observation-counts'])
def test_second_recovery_rejects_same_count_changes_or_reusing_the_first_server(damage):
    first, second = snapshots()
    if damage == 'same-server': second['serverUuid'] = first['serverUuid']
    if damage == 'same-container': second['containerId'] = first['containerId']
    if damage == 'same-volume': second['volume'] = first['volume']
    if damage == 'same-count-row-change': second['snapshot']['tables']['table_0']['rowsSha256'] = 'c' * 64
    if damage == 'column-type': second['snapshot']['tables']['table_0']['columns'][0]['type'] = 'varchar(64)'
    if damage == 'index': second['snapshot']['tables']['table_0']['indexes'] = []
    if damage == 'high-water': second['snapshot']['tables']['table_0']['autoIncrement'] = '9'
    if damage == 'constraint': second['metadata']['checks'] = [{'clause': 'id > 0'}]
    if damage == 'object-definition': second['extraObjects']['routines'] = [{'body': 'changed'}]
    if damage == 'observation-counts': second['observedCountsMatch'] = False
    with pytest.raises(ValueError): recovery.compare_recoveries(first, second)


def test_fk_and_check_findings_are_read_only_and_preserve_source_rows():
    queries = []
    class Client:
        def single(self, sql): queries.append(sql); return {'n': 2}
    metadata = {'foreignKeys': [{'table': 'child', 'name': 'fk_child', 'ordinal': 1, 'column': 'parent_id',
        'parent': 'parent', 'parentColumn': 'id', 'parentSchema': '$SELF'}],
        'checks': [{'table': 'child', 'name': 'ck_child', 'clause': 'value > 0', 'enforced': 'YES'}]}
    frozen = copy.deepcopy(metadata); result = recovery.findings(Client(), metadata)
    assert [row['kind'] for row in result] == ['FOREIGN_KEY', 'CHECK'] and all(row['violations'] == 2 for row in result)
    assert metadata == frozen and all(query.startswith('SELECT ') and '`doorhandledb`.' in query for query in queries)
    assert all('DELETE ' not in query and 'UPDATE ' not in query and 'ALTER ' not in query for query in queries)


def test_external_fk_dependency_is_reported_without_querying_another_project():
    metadata = {'foreignKeys': [{'table': 'child', 'name': 'fk_external', 'ordinal': 1, 'column': 'parent_id',
        'parent': 'parent', 'parentColumn': 'id', 'parentSchema': 'other_project'}], 'checks': []}
    result = recovery.findings(SimpleNamespace(single=lambda sql: pytest.fail('No external-schema query is allowed')), metadata)
    assert result[0]['kind'] == 'EXTERNAL_FOREIGN_KEY' and result[0]['unverified'] and metadata['foreignKeys']


def test_original_database_container_is_rejected_before_any_docker_operation():
    controller = object.__new__(recovery.Recovery); controller.original = 'a' * 64
    controller.docker_call = lambda *args: pytest.fail('The original DB must not be inspected/queried as a recovery target')
    with pytest.raises(ValueError): controller.inspect('a' * 64)


def test_owned_sql_client_never_regenerates_dump_or_switches_to_another_schema(tmp_path):
    runtime = recovery.load_runtime()
    controller = object.__new__(recovery.Recovery)
    controller.runtime = runtime; controller.docker = Path('/usr/bin/docker'); inspected = []
    controller.guard = lambda: None; controller.inspect = lambda cid: inspected.append(cid)
    client = controller.sql_client('b' * 64, tmp_path)
    command, prefix = client.command('doorhandledb')
    assert command[:4] == ['/usr/bin/docker', 'exec', '-i', 'b' * 64] and prefix == b''
    assert '--binary-mode' in command and '--local-infile=0' in command
    assert all('MYSQL_ROOT_PASSWORD=' not in argument for argument in command)
    with pytest.raises(ValueError): client.command('other_project')
    with pytest.raises(ValueError): client.command('doorhandledb', dump=True)
    assert inspected


def test_isolated_launcher_imports_only_fixed_checkout_snapshot_helpers_without_database(tmp_path):
    checkout = tmp_path / 'separate-checkout'; checkout.mkdir()
    for relative in ('script/jenkins/restore-local-mysql.py', 'script/schema/compact_migration_runtime.py',
                     'script/schema/build_compact_schema.py', 'script/schema/compact_clock_policy.py', 'scripts/ecs_execution.py'):
        target = checkout / relative; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    # Run the real -I launcher with a distinct CWD and no PYTHONPATH. Importing
    # these source primitives must neither open a DB nor invoke ECS metadata.
    program = """
import importlib.util, pathlib, sys
helper=pathlib.Path(sys.argv[1])
spec=importlib.util.spec_from_file_location('isolated_owned_recovery',helper)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
runtime=module.load_runtime()
assert module.ROOT==helper.parents[2]
assert pathlib.Path(runtime.__file__).is_relative_to(module.ROOT)
assert callable(runtime.schema_snapshot) and callable(runtime.Mysql.row_hashes)
print('FIXED_CHECKOUT_IMPORT_OK')
"""
    result = subprocess.run([sys.executable, '-I', '-B', '-c', program, str(checkout / 'script/jenkins/restore-local-mysql.py')],
        cwd=tmp_path, env={}, capture_output=True, timeout=20)
    assert result.returncode == 0 and result.stdout == b'FIXED_CHECKOUT_IMPORT_OK\n' and not result.stderr


@pytest.mark.parametrize('damage', ['foreign-owner', 'foreign-image', 'foreign-source', 'bridge-network',
    'published-port', 'privileged', 'unbounded-memory', 'original-volume', 'extra-bind'])
def test_recovery_target_rejects_original_or_weakened_isolation_before_any_sql(damage):
    controller = object.__new__(recovery.Recovery)
    cid = 'b' * 64; controller.original = 'a' * 64
    controller.args = SimpleNamespace(tag='ci-999-' + 'c' * 12, source_sha256='d' * 64)
    controller.state = {'owner': 'e' * 24, 'mysqlImage': 'sha256:' + 'f' * 64,
        'servers': [{'containerId': cid, 'volume': 'new-owned-data'}]}
    labels = {recovery.LABEL: controller.state['owner'], 'io.doorhandle.release': controller.args.tag,
        'io.doorhandle.source': controller.args.source_sha256}
    row = {'Id': cid, 'Image': controller.state['mysqlImage'], 'Config': {'Labels': labels},
        'HostConfig': {'NetworkMode': 'none', 'Privileged': False, 'PortBindings': {},
            'Memory': recovery.MEMORY, 'MemorySwap': recovery.MEMORY, 'RestartPolicy': {'Name': 'no'}},
        'Mounts': [{'Type': 'volume', 'Name': 'new-owned-data', 'Destination': '/var/lib/mysql', 'RW': True}]}
    if damage == 'foreign-owner': labels[recovery.LABEL] = 'unowned'
    if damage == 'foreign-image': row['Image'] = 'sha256:' + '0' * 64
    if damage == 'foreign-source': labels['io.doorhandle.source'] = '0' * 64
    if damage == 'bridge-network': row['HostConfig']['NetworkMode'] = 'bridge'
    if damage == 'published-port': row['HostConfig']['PortBindings'] = {'3306/tcp': [{'HostPort': '3306'}]}
    if damage == 'privileged': row['HostConfig']['Privileged'] = True
    if damage == 'unbounded-memory': row['HostConfig']['Memory'] = 0
    if damage == 'original-volume': row['Mounts'][0]['Name'] = 'actual-original-volume'
    if damage == 'extra-bind': row['Mounts'].append({'Type': 'bind', 'Source': '/original', 'Destination': '/extra', 'RW': True})
    controller.docker_call = lambda *args: custody.encoded([row])
    with pytest.raises(ValueError): controller.inspect(cid)


def prepared_recovery_fixture(source, monkeypatch):
    work = source.output.parent / 'isolated-byte-recovery'; work.mkdir(mode=0o700)
    work.chmod(0o755)  # Existing CI workspace; only our new children are private.
    context = {'release': 'synthetic-byte-recovery', 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    monkeypatch.setattr(custody, 'admit', lambda args: (work, context))
    utility = custody.common(); utility.resource_guard = lambda *args: None
    monkeypatch.setattr(custody, 'common', lambda: utility)
    args = SimpleNamespace(manifest_sha256=custody.digest(source.output / 'custody.json'),
        archive_sha256=custody.digest(source.output / 'originals.tar.gz'),
        manifest_bytes=(source.output / 'custody.json').stat().st_size,
        archive_bytes=(source.output / 'originals.tar.gz').stat().st_size)
    custody.prepare(args)
    for name in ('custody.json', 'originals.tar.gz'):
        (work / custody.SNAPSHOT / name).write_bytes((source.output / name).read_bytes())
    return args, work


@pytest.mark.parametrize('mode,accepted', [(0o755, True), (0o775, False)])
def test_fixed_source_admission_accepts_real_ci_work_permissions_without_changing_them(tmp_path, monkeypatch, mode, accepted):
    root = tmp_path / 'ecs-root'; checkout = root / 'verification' / ('ci-999-' + 'a' * 12) / 'checkout'
    work = checkout / 'work'; work.mkdir(mode=0o755, parents=True); work.chmod(mode)
    members = ('script/jenkins/preserve-local-mysql.py', 'script/jenkins/restore-local-mysql.py',
        'script/jenkins/preserve-local-artifacts.py', 'script/schema/compact_migration_runtime.py',
        'script/schema/build_compact_schema.py', 'script/schema/compact_clock_policy.py',
        'script/docker/compact-schema-guard.py', 'scripts/ecs_execution.py')
    for name in members:
        target = checkout / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / name, target)
    archive_file = root / 'inbox' / ('ci-999-' + 'a' * 12) / 'source.tar.gz'; archive_file.parent.mkdir(parents=True)
    with tarfile.open(archive_file, 'x:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': 'a' * 40}) as archive:
        for name in members: archive.add(checkout / name, arcname=name, recursive=False)
    identity = {'instanceId': 'i-fixture', 'machineId': 'b' * 32, 'executionLocation': 'ECS'}
    args = SimpleNamespace(root=root, tag='ci-999-' + 'a' * 12, commit='a' * 40,
        source_sha256=custody.digest(archive_file), instance_id='i-fixture', machine_id='b' * 32)
    utility = custody.common(); utility.identity = lambda *unused: identity
    monkeypatch.setattr(custody, 'ROOT', checkout); monkeypatch.setattr(custody, 'common', lambda: utility)
    custody.write(checkout.parent / 'verification-receipt.json', {'status': 'PASS', 'verificationExitCode': 0,
        'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256, 'identity': identity})
    if accepted:
        actual, context = custody.admit(args)
        assert actual == work and context['identity'] == identity
    else:
        with pytest.raises(Exception): custody.admit(args)
    assert work.stat().st_mode & 0o777 == mode


def test_byte_recovery_independently_reads_every_restored_original_without_opening_sql(export_fixture, monkeypatch):
    source = export_fixture; custody.pack(source.export, source.control, source.output)
    args, work = prepared_recovery_fixture(source, monkeypatch)
    result = custody.verify_restore(args)
    assert result['status'] == 'BYTES_RESTORED_VERIFIED' and result['files'] == 13 and result['databasesOpened'] == 0
    assert result['sqlDoubleRestoreVerified'] is False and result['retirementAllowed'] is False
    for name in custody.MEMBERS:
        original = source.control if name == 'export-control-private.json' else source.export / name
        assert (work / custody.RESTORE / name).read_bytes() == original.read_bytes()


@pytest.mark.parametrize('damage', ['extra-member', 'link-member', 'duplicate-member', 'changed-member'])
def test_byte_recovery_rejects_unreviewed_tar_structure_or_same_size_content(export_fixture, monkeypatch, damage):
    source = export_fixture; custody.pack(source.export, source.control, source.output)
    archive_path = source.output / 'originals.tar.gz'
    with tarfile.open(archive_path, 'r:gz') as archive:
        entries = [(member, archive.extractfile(member).read()) for member in archive]
    import io
    with tarfile.open(archive_path, 'w:gz', format=tarfile.PAX_FORMAT) as archive:
        for member, body in entries:
            if damage == 'changed-member' and member.name == 'schema-before.sql': body = b'X' * len(body)
            archive.addfile(member, io.BytesIO(body))
        if damage != 'changed-member':
            member, body = entries[0]
            if damage == 'extra-member': member = tarfile.TarInfo('credentials.env'); member.size = len(body)
            if damage == 'link-member':
                member = tarfile.TarInfo('outside'); member.type = tarfile.SYMTYPE; member.linkname = '/original'; member.size = 0
            archive.addfile(member, None if member.issym() else io.BytesIO(body))
    manifest = custody.read(source.output / 'custody.json')
    manifest.update(archiveBytes=archive_path.stat().st_size, archiveSha256=custody.digest(archive_path))
    (source.output / 'custody.json').write_bytes(custody.encoded(manifest))
    args, work = prepared_recovery_fixture(source, monkeypatch)
    with pytest.raises(ValueError): custody.verify_restore(args)
    assert not (work / custody.PUBLIC).exists() and not (work / custody.RESTORE / 'restore-receipt.json').exists()


def cleanup_fixture(source, monkeypatch):
    custody.pack(source.export, source.control, source.output)
    args, work = prepared_recovery_fixture(source, monkeypatch); custody.verify_restore(args)
    controller = object.__new__(recovery.Recovery)
    controller.bytes = custody; controller.utility = custody.common(); controller.work = work
    controller.pressure = None
    controller.context = {'release': 'synthetic-byte-recovery', 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    controller.directory = work / 'local-mysql-recovery'; controller.directory.mkdir(mode=0o700)
    first, second = snapshots(); servers = []
    for ordinal, value in zip(('a', 'b'), (first, second)):
        directory = controller.directory / ordinal; directory.mkdir(mode=0o700)
        custody.write(directory / 'full-recovery-private.json', value)
        servers.append({'ordinal': ordinal, 'containerId': value['containerId'], 'volume': value['volume'], 'serverUuid': value['serverUuid']})
    (controller.directory / 'resource-probes.jsonl').write_bytes(b'{"actualProbe":"synthetic pure fixture"}\n')
    (controller.directory / 'resource-probes.jsonl').chmod(0o600)
    controller.state = {'owner': 'c' * 24, 'servers': servers, 'status': 'SQL_DOUBLE_RESTORED_VERIFIED'}
    controller.args = SimpleNamespace(tag=controller.context['release'], source_sha256=controller.context['sourceSha256'])
    controller.state['cleanupEvidence'] = controller.evidence_bindings()
    custody.write(controller.directory / 'public-recovery.json', {'status': 'SQL_DOUBLE_RESTORED_VERIFIED'})
    controller.state['publicRecoverySha256'] = custody.digest(controller.directory / 'public-recovery.json')
    controller.load = lambda: None; controller.docker_call = lambda *unused: b''
    controller.stop = lambda node: node.update(stopped=True)
    return controller


@pytest.mark.parametrize('damage', ['archive', 'raw-original', 'manifest-original', 'same-count-row',
    'server-identity', 'resource-evidence', 'public-receipt'])
def test_derived_cleanup_refuses_missing_or_changed_original_or_logical_evidence(export_fixture, monkeypatch, damage):
    controller = cleanup_fixture(export_fixture, monkeypatch)
    controller.remove_derived = lambda node: pytest.fail('No derived resource can be deleted before its evidence closes')
    if damage == 'archive': path = controller.work / custody.SNAPSHOT / 'originals.tar.gz'
    elif damage == 'raw-original': path = controller.work / custody.RESTORE / 'database.sql'
    elif damage == 'manifest-original': path = controller.work / custody.RESTORE / 'public-manifest.json'
    elif damage == 'resource-evidence': path = controller.directory / 'resource-probes.jsonl'
    elif damage == 'public-receipt': path = controller.directory / 'public-recovery.json'
    else:
        path = controller.directory / 'b/full-recovery-private.json'; value = custody.read(path)
        if damage == 'same-count-row': value['snapshot']['tables']['table_0']['rowsSha256'] = '0' * 64
        if damage == 'server-identity': value['containerId'] = '0' * 64
        path.write_bytes(custody.encoded(value))
        path = None
    if path is not None: path.write_bytes(b'X' * path.stat().st_size)
    with pytest.raises(ValueError): controller.cleanup()
    assert not (controller.directory / 'public-cleanup.json').exists()


def test_successful_derived_cleanup_keeps_originals_and_receipts_for_independent_retirement_review(export_fixture, monkeypatch):
    controller = cleanup_fixture(export_fixture, monkeypatch); removed = []
    def remove(node):
        removed.append(node['volume']); node.update(containerRemoved=True, volumeRemoved=True)
    controller.remove_derived = remove
    result = controller.cleanup()
    assert result['status'] == 'STOPPED' and result['derivedContainersRemoved'] == result['derivedVolumesRemoved'] == 2
    assert result['originalsChanged'] is False and result['recoveryVolumesRetained'] is False and len(removed) == 2
    assert (controller.work / custody.SNAPSHOT / 'originals.tar.gz').is_file()
    assert (controller.work / custody.RESTORE / 'database.sql').read_bytes() == export_fixture.raw
    assert all((controller.directory / ordinal / 'full-recovery-private.json').is_file() for ordinal in ('a', 'b'))


@pytest.mark.parametrize('damage', ['other-reference-before-rm', 'other-reference-after-rm', 'foreign-volume-owner'])
def test_volume_removal_refuses_foreign_labels_or_any_other_container_reference(damage):
    controller = object.__new__(recovery.Recovery); cid = 'b' * 64
    controller.state = {'owner': 'c' * 24}; controller.args = SimpleNamespace(tag='ci-999-' + 'd' * 12, source_sha256='e' * 64)
    controller.persist = lambda: None
    controller.inspect = lambda unused: {'State': {'Running': False, 'Pid': 0, 'ExitCode': 0, 'OOMKilled': False}}
    node = {'containerId': cid, 'volume': 'new-owned-data'}; calls = []
    if damage != 'other-reference-before-rm': node['containerRemoved'] = True
    def docker(*args):
        calls.append(args)
        if args[0] == 'ps':
            return b'' if 'id=' + cid in args else (cid + '\n' + 'a' * 64 + '\n').encode()
        if args[:2] == ('volume', 'inspect'):
            labels = {recovery.LABEL: 'foreign' if damage == 'foreign-volume-owner' else 'c' * 24,
                'io.doorhandle.release': controller.args.tag, 'io.doorhandle.source': controller.args.source_sha256}
            return custody.encoded([{'Name': node['volume'], 'Driver': 'local', 'Options': {}, 'Labels': labels}])
        pytest.fail('A foreign-referenced or unowned derived resource must not be deleted')
    controller.docker_call = docker
    with pytest.raises(ValueError): controller.remove_derived(node)
    assert not any(call[0] == 'rm' or call[:2] == ('volume', 'rm') for call in calls)


def test_failed_container_create_reports_the_owned_intent_volume_as_retained(tmp_path):
    controller = object.__new__(recovery.Recovery); volume = 'doorhandle-new-intent-only-data'
    controller.work = controller.directory = tmp_path; controller.context = {}; controller.bytes = custody
    controller.utility = custody.common(); controller.load = lambda: None
    controller.args = SimpleNamespace(tag='ci-999-' + 'd' * 12, source_sha256='e' * 64)
    controller.state = {'owner': 'c' * 24, 'status': 'PREPARING', 'servers': [],
        'containerIntents': [{'name': 'doorhandle-new-intent-only', 'volume': volume, 'ordinal': 'a'}]}
    calls = []
    def docker(*args):
        calls.append(args)
        if args[0] == 'ps': return b''
        if args[:2] == ('volume', 'ls'): return (volume + '\n').encode()
        if args[:2] == ('volume', 'inspect'):
            return custody.encoded([{'Name': volume, 'Driver': 'local', 'Options': {},
                'Labels': {recovery.LABEL: 'c' * 24, 'io.doorhandle.release': controller.args.tag,
                    'io.doorhandle.source': controller.args.source_sha256}}])
        pytest.fail('Failed container creation must retain its derived volume')
    controller.docker_call = docker
    result = controller.cleanup()
    assert result['status'] == 'STOPPED' and result['derivedVolumesRetained'] == 1
    assert result['recoveryVolumesRetained'] is True and result['derivedVolumesRemoved'] == 0
    assert not any(call[0] == 'rm' or call[:2] == ('volume', 'rm') for call in calls)


def uncreated_cleanup(tmp_path):
    controller = object.__new__(recovery.Recovery)
    controller.state = None; controller.work = tmp_path; controller.directory = tmp_path / 'local-mysql-recovery'
    controller.owner_file = tmp_path / 'local-mysql-recovery-owner.json'
    controller.bytes = custody; controller.utility = custody.common()
    controller.context = {'release': 'ci-999-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64,
        'identity': {'instanceId': 'i-test-only', 'machineId': 'c' * 32, 'executionLocation': 'ECS'}}
    controller.docker_call = lambda *unused: pytest.fail('No database/container can be touched for a genuinely absent recovery')
    return controller


def test_admitted_but_never_created_cleanup_is_idempotent_without_fabricating_an_owner(tmp_path):
    controller = uncreated_cleanup(tmp_path)
    first = controller.cleanup(); second = controller.cleanup()
    assert first == second and first['status'] == 'NOT_CREATED' and first['containers'] == []
    assert first['originalsChanged'] is False and first['derivedVolumesRetained'] == 0
    assert not controller.owner_file.exists() and not controller.directory.exists() and controller.state is None
    assert (tmp_path / 'local-mysql-recovery-not-created.json').is_file()


@pytest.mark.parametrize('partial', ['unreceipted-directory', 'broken-owner-link', 'linked-directory'])
def test_unknown_partial_cleanup_cannot_report_not_created_or_fabricate_state(tmp_path, partial):
    controller = uncreated_cleanup(tmp_path)
    if partial == 'unreceipted-directory': controller.directory.mkdir(mode=0o700)
    elif partial == 'broken-owner-link': controller.owner_file.symlink_to(tmp_path / 'absent-foreign-owner')
    else:
        other = tmp_path / 'foreign-directory'; other.mkdir(mode=0o700); controller.directory.symlink_to(other, target_is_directory=True)
    with pytest.raises(Exception): controller.cleanup()
    assert not (tmp_path / 'local-mysql-recovery-not-created.json').exists() and controller.state is None


def test_cleanup_cancellation_prevents_a_late_second_container_create(export_fixture, monkeypatch):
    controller = cleanup_fixture(export_fixture, monkeypatch)
    controller.remove_derived = lambda node: node.update(containerRemoved=True, volumeRemoved=True)
    assert controller.cleanup()['status'] == 'STOPPED'
    controller.create_registered = lambda ordinal: pytest.fail('A cancelled remote creator must not create another resource')
    with pytest.raises(ValueError, match='cancelled'): controller.start('late')


def test_active_interprocess_creator_causes_bounded_unknown_instead_of_false_stopped(tmp_path):
    controller = uncreated_cleanup(tmp_path); lock = tmp_path / 'local-mysql-recovery-create.lock'
    program = """
import fcntl,os,sys
with open(sys.argv[1],'x+b') as stream:
    os.chmod(sys.argv[1],0o600)
    fcntl.flock(stream,fcntl.LOCK_EX)
    print('OWNED_CREATOR_LOCKED',flush=True)
    sys.stdin.buffer.read(1)
"""
    process = subprocess.Popen([sys.executable, '-I', '-B', '-c', program, str(lock)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={})
    try:
        assert select.select([process.stdout], [], [], 5)[0]
        assert process.stdout.readline() == b'OWNED_CREATOR_LOCKED\n'
        with pytest.raises(recovery.CleanupNotQuiescent):
            with controller.creation_lock(timeout=0.1): pytest.fail('A live creator lock cannot be ignored')
        assert not (tmp_path / 'local-mysql-recovery-not-created.json').exists()
    finally:
        _, errors = process.communicate(b'x', timeout=5)
    assert process.returncode == 0 and not errors
