"""ECS-only byte-custody and isolated SQL recovery contracts; no local execution."""
import copy
import gzip
import hashlib
import importlib.util
import json
import os
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


@pytest.mark.parametrize('damage', ['partial', 'credential-side-file', 'missing-file', 'raw-changed', 'identity-unverified',
    'source-row-hash-claim', 'remaining-agent-schema', 'remaining-model-schema', 'new-export-worker'])
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
        # New authorised exports have their own evidence and must never be
        # promoted by relabelling the original 45-table custody protocol.
        if damage == 'remaining-agent-schema': value['sourceSchema'] = 'doorhandle_agent_verify_ef8d5844c1'
        if damage == 'remaining-model-schema': value['sourceSchema'] = 'doorhandle_model_verify_22e4bc5566'
        if damage == 'new-export-worker':
            value['scriptSha256'] = custody.digest(ROOT / 'script/jenkins/export-legacy-local-mysql.ps1')
            assert value['scriptSha256'] != custody.EXPORT_SCRIPT_SHA
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
                     'script/schema/build_compact_schema.py', 'script/schema/compact_clock_policy.py',
                     'script/schema/compact_ddl_policy.py', 'scripts/ecs_execution.py'):
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


@pytest.mark.parametrize('damage', ['extra-member', 'link-member', 'duplicate-member', 'changed-member',
    'pax-header', 'global-pax-header', 'raw-sparse-type', 'contiguous-type'])
def test_byte_recovery_rejects_unreviewed_tar_structure_or_same_size_content(export_fixture, monkeypatch, damage):
    source = export_fixture; custody.pack(source.export, source.control, source.output)
    archive_path = source.output / 'originals.tar.gz'
    with tarfile.open(archive_path, 'r:gz') as archive:
        entries = [(member, archive.extractfile(member).read()) for member in archive]
    import io
    with tarfile.open(archive_path, 'w:gz', format=tarfile.GNU_FORMAT if damage == 'raw-sparse-type' else tarfile.PAX_FORMAT,
                      pax_headers={'comment': 'opaque'} if damage == 'global-pax-header' else None) as archive:
        for index, (member, body) in enumerate(entries):
            if damage == 'changed-member' and member.name == 'schema-before.sql': body = b'X' * len(body)
            if damage == 'pax-header' and index == 0: member.pax_headers = {'comment': 'opaque'}
            if damage == 'raw-sparse-type' and index == 0: member.type = tarfile.GNUTYPE_SPARSE
            if damage == 'contiguous-type' and index == 0: member.type = tarfile.CONTTYPE
            archive.addfile(member, io.BytesIO(body))
        if damage in ('extra-member', 'link-member', 'duplicate-member'):
            member, body = entries[0]
            if damage == 'extra-member': member = tarfile.TarInfo('credentials.env'); member.size = len(body)
            if damage == 'link-member':
                member = tarfile.TarInfo('outside'); member.type = tarfile.SYMTYPE; member.linkname = '/original'; member.size = 0
            archive.addfile(member, None if member.issym() else io.BytesIO(body))
    if 'pax-header' in damage:
        with gzip.open(archive_path, 'rb') as raw:
            header = tarfile.TarInfo.frombuf(raw.read(512), 'utf-8', 'strict')
        assert header.type == (tarfile.XGLTYPE if damage == 'global-pax-header' else tarfile.XHDTYPE)
        assert 0 < header.size < 65536  # SQL custody admits no PAX, even small.
    elif damage in ('raw-sparse-type', 'contiguous-type'):
        with gzip.open(archive_path, 'rb') as raw:
            header = tarfile.TarInfo.frombuf(raw.read(512), 'utf-8', 'strict')
        assert header.type == (tarfile.GNUTYPE_SPARSE if damage == 'raw-sparse-type' else tarfile.CONTTYPE)
        assert header.name in custody.MEMBERS and 0 < header.size <= custody.MAX_BYTES
    manifest = custody.read(source.output / 'custody.json')
    manifest.update(archiveBytes=archive_path.stat().st_size, archiveSha256=custody.digest(archive_path))
    (source.output / 'custody.json').write_bytes(custody.encoded(manifest))
    args, work = prepared_recovery_fixture(source, monkeypatch)
    if 'pax-header' in damage:
        monkeypatch.setattr(tarfile.TarInfo, '_proc_pax',
            lambda *unused: pytest.fail('SQL custody must reject PAX before decoding any payload'))
    elif damage in ('raw-sparse-type', 'contiguous-type'):
        monkeypatch.setattr(tarfile.TarInfo, '_proc_sparse' if damage == 'raw-sparse-type' else '_proc_builtin',
            lambda *unused: pytest.fail('SQL custody must reject the raw type before member processing'))
    raw_header_rejected = 'pax-header' in damage or damage in ('raw-sparse-type', 'contiguous-type')
    with pytest.raises(ValueError, match='Unreviewed TAR header' if raw_header_rejected else None):
        custody.verify_restore(args)
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


@pytest.fixture
def retained_sql_fixture(export_fixture, monkeypatch):
    """Real closed bytes/logical receipts; the existing CI envelope guard is isolated."""
    source = export_fixture; custody.pack(source.export, source.control, source.output)
    root = source.output.parent / 'remote-root'; old_tag = 'ci-7-' + 'a' * 12; new_tag = 'ci-8-' + 'b' * 12
    old_work = root / 'verification' / old_tag / 'checkout/work'; old_work.mkdir(parents=True)
    new_work = root / 'verification' / new_tag / 'checkout/work'; new_work.mkdir(parents=True)
    inbox = root / 'inbox' / old_tag; (inbox / 'tool-runtime').mkdir(parents=True)
    (inbox / 'source.tar.gz').write_bytes(b'closed synthetic source bytes, never executed')
    (inbox / 'tool-runtime/manifest.json').write_bytes(b'{"synthetic":"tool binding"}')
    driver = old_work.parent / 'driver.log'; driver.write_bytes(b'')  # Empty CI logs are legitimate.
    python_xml = old_work / 'ci-evidence/python.xml'; python_xml.parent.mkdir(mode=0o700)
    python_xml.write_bytes(b'<testsuite><testcase classname="tests_python.test_synthetic" name="original"/></testsuite>\n')
    identity = {'instanceId': 'i-fixture', 'machineId': 'c' * 32, 'executionLocation': 'ECS'}
    record = {'schema': 1, 'kind': 'doorhandle-ecs-ci', 'release': old_tag, 'commit': 'a' * 40,
        'sourceSha256': custody.digest(inbox / 'source.tar.gz'), 'identity': identity, 'scope': 'source',
        'status': 'PASS', 'verificationExitCode': 0, 'finishedAt': 'synthetic-finished', 'lifecycle': 'managed-outside-jenkins',
        'toolRuntime': {'manifestSha256': custody.digest(inbox / 'tool-runtime/manifest.json')},
        'reportFiles': [{'path': 'driver.log', 'bytes': 0, 'sha256': custody.digest(driver)},
            {'path': 'reports/python.xml', 'bytes': python_xml.stat().st_size, 'sha256': custody.digest(python_xml)}]}
    custody.write(old_work.parents[1] / 'verification-receipt.json', record)
    old_context = {'version': 1, 'kind': custody.KIND, 'profile': custody.PROFILE,
        **{key: record[key] for key in ('release', 'commit', 'sourceSha256', 'identity')},
        'verificationReceiptSha256': custody.digest(old_work.parents[1] / 'verification-receipt.json')}
    context = dict(old_context, release=new_tag, commit='b' * 40, sourceSha256='d' * 64, verificationReceiptSha256='e' * 64)
    utility = custody.common(); utility.resource_guard = lambda *args: None
    monkeypatch.setattr(custody, 'common', lambda: utility)
    monkeypatch.setattr(custody, 'admit', lambda args: (old_work, old_context))
    bindings = {'manifest_sha256': custody.digest(source.output / 'custody.json'),
        'manifest_bytes': (source.output / 'custody.json').stat().st_size,
        'archive_sha256': custody.digest(source.output / 'originals.tar.gz'),
        'archive_bytes': (source.output / 'originals.tar.gz').stat().st_size}
    args = SimpleNamespace(root=root, tag=new_tag, commit='b' * 40, source_sha256='d' * 64,
        instance_id=identity['instanceId'], machine_id=identity['machineId'], source_snapshot_directory=old_work / custody.SNAPSHOT, **bindings)
    custody.prepare(args)
    for name in ('custody.json', 'originals.tar.gz'):
        (old_work / custody.SNAPSHOT / name).write_bytes((source.output / name).read_bytes())
    custody.verify_restore(args)
    directory = old_work / 'local-mysql-recovery'; directory.mkdir(mode=0o700)
    first, second = snapshots(); servers = []
    for ordinal, value in zip(('a', 'b'), (first, second)):
        value['metadataSha256'] = custody.sha(value['metadata'])
        folder = directory / ordinal; folder.mkdir(mode=0o700)
        custody.write(folder / 'full-recovery-private.json', value)
        servers.append({**{key: value[key] for key in ('containerId', 'serverUuid', 'volume')}, 'ordinal': ordinal,
            'stopped': True, 'exitCode': 0, 'oomKilled': False, 'containerRemoved': True, 'volumeRemoved': True})
    (directory / 'resource-probes.jsonl').write_bytes(b'{"syntheticMeasured":true}\n')
    controller = object.__new__(recovery.Recovery); controller.work = old_work; controller.directory = directory
    controller.bytes = custody; controller.utility = utility; controller.context = old_context
    controller.state = {'servers': servers}
    owner = {**old_context, 'directory': str(directory), 'originalContainerId': 'f' * 64,
             'servers': servers, 'status': 'SQL_DOUBLE_RESTORED_VERIFIED',
             'byteReceiptSha256': custody.digest(old_work / custody.RESTORE / 'restore-receipt.json')}
    public = {**old_context, 'status': 'SQL_DOUBLE_RESTORED_VERIFIED', 'tableCount': 45, 'restoredRows': 45,
        'rawSqlSha256': custody.RAW_SHA, 'gzipSha256': custody.GZIP_SHA, 'allOriginalRowsPreserved': True,
        'liveSourceRowHashesVerified': False, 'productionMerged': False, 'retirementAllowed': False,
        'eventsExecuted': False, 'paidModelCalls': 0, 'cleanup': 'STOPPED',
        'snapshotSha256': first['snapshot']['snapshotSha256'], 'metadataSha256': first['metadataSha256'],
        'byteReceiptSha256': owner['byteReceiptSha256'], 'resourceProbeSha256': custody.digest(directory / 'resource-probes.jsonl')}
    def seal():
        owner['cleanupEvidence'] = {name: custody.digest(old_work / name) for name in catalogue_names}
        public['logicalEvidenceCatalogueSha256'] = custody.sha(owner['cleanupEvidence'])
        (directory / 'public-recovery.json').write_bytes(custody.encoded(public))
        owner['publicRecoverySha256'] = custody.digest(directory / 'public-recovery.json')
        (old_work / 'local-mysql-recovery-owner.json').write_bytes(custody.encoded(owner))
        for path in (directory / 'public-recovery.json', old_work / 'local-mysql-recovery-owner.json'): path.chmod(0o600)
    # Build the same raw evidence catalogue without running either recovery DB.
    for path in root.rglob('*'):
        path.chmod(0o700 if path.is_dir() else 0o600)
    root.chmod(0o700); python_xml.chmod(0o644)
    catalogue_names = controller.evidence_bindings(); seal()
    stopped = {**old_context, 'status': 'STOPPED', 'containers': [node['containerId'] for node in servers],
        'originalsChanged': False, 'derivedContainersRemoved': 2, 'derivedVolumesRemoved': 2,
        'derivedVolumesRetained': 0, 'recoveryVolumesRetained': False}
    custody.write(directory / 'public-cleanup.json', stopped)
    cleanup = load('sql_reuse_quiescence_contract', 'script/jenkins/cleanup-ecs-builds.py')
    state = SimpleNamespace(rows=[], calls=[], root=root, old_work=old_work, new_work=new_work, args=args,
        owner=owner, public=public, stopped=stopped, directory=directory, seal=seal, report=python_xml)
    monkeypatch.setattr(cleanup, 'docker_snapshot', lambda: state.rows)
    monkeypatch.setattr(cleanup, 'process_references', lambda path: state.calls.append(('process', path)))
    guard = load('sql_reuse_terminal_contract', 'script/jenkins/reuse-legacy-source.py')
    def terminal(root, attempt, actual, observed, cleaner, verifier):
        state.calls.append(('terminal', attempt)); assert actual == record and observed == identity
        binding = {'checkout': old_work.parent, 'token': '9' * 24}
        cleaner.quiescent(binding, old_tag, cleaner.docker_snapshot()); return binding
    monkeypatch.setattr(guard, 'terminal_build', terminal)
    monkeypatch.setattr(custody, 'reuse_modules', lambda args: (guard, SimpleNamespace(MAX_FILE_BYTES=32 * custody.MIB), cleanup))
    monkeypatch.setattr(custody, 'admit', lambda args: (new_work, context))
    return state


def test_ecs_sql_description_and_same_fd_copy_restore_every_byte_without_database(retained_sql_fixture):
    value = retained_sql_fixture; old = value.old_work / custody.SNAPSHOT
    before = {name: custody.digest(old / name) for name in ('custody.json', 'originals.tar.gz')}
    report_before = value.report.read_bytes()
    assert value.report.stat().st_mode & 0o777 == 0o644
    description = custody.describe(value.args)
    value.args.source_receipt_sha256 = description['sourceCustodyReceiptSha256']
    result = custody.reuse(value.args)
    assert description['status'] == 'DESCRIBED' and description['files'] == 13
    assert result['status'] == 'BYTES_RESTORED_VERIFIED' and result['databasesOpened'] == 0
    assert result['sqlDoubleRestoreVerified'] is False and result['retirementAllowed'] is False and result['productionMerged'] is False
    for name, checksum in before.items():
        assert custody.digest(old / name) == checksum == custody.digest(value.new_work / custody.SNAPSHOT / name)
    assert (value.new_work / custody.RESTORE / 'database.sql').read_bytes() == (value.old_work / custody.RESTORE / 'database.sql').read_bytes()
    assert value.report.read_bytes() == report_before and value.report.stat().st_mode & 0o777 == 0o644
    assert len([call for call in value.calls if call[0] == 'terminal']) == 2


@pytest.mark.parametrize('damage', ['same-build', 'future-build', 'outside-root', 'extra-snapshot-file', 'archive', 'member',
    'double-row', 'same-server', 'unremoved', 'retained-volume', 'cleanup-pair', 'byte-claim', 'logical-claim',
    'missing-logical-file', 'source-archive', 'raw-report', 'owned-container', 'checkout-bind'])
def test_ecs_sql_reuse_requires_complete_older_bytes_double_restore_and_quiescence(retained_sql_fixture, damage):
    value = retained_sql_fixture; old = value.old_work / custody.SNAPSHOT
    if damage == 'same-build': value.args.tag = 'ci-7-' + 'a' * 12
    if damage == 'future-build': value.args.tag = 'ci-6-' + 'b' * 12
    if damage == 'outside-root': value.args.source_snapshot_directory = value.new_work
    if damage == 'extra-snapshot-file': (old / 'unknown').write_bytes(b'unreviewed')
    if damage == 'archive': (old / 'originals.tar.gz').write_bytes(b'X' * (old / 'originals.tar.gz').stat().st_size)
    if damage == 'member': (value.old_work / custody.RESTORE / 'database.sql').write_bytes(b'X' * custody.RAW_BYTES)
    if damage in ('double-row', 'same-server'):
        path = value.directory / 'b/full-recovery-private.json'; document = custody.read(path)
        if damage == 'double-row': document['snapshot']['tables']['table_0']['rowsSha256'] = '0' * 64
        else:
            document['containerId'] = value.owner['servers'][0]['containerId']; value.owner['servers'][1]['containerId'] = document['containerId']
            value.stopped['containers'] = [node['containerId'] for node in value.owner['servers']]
            (value.directory / 'public-cleanup.json').write_bytes(custody.encoded(value.stopped))
        path.write_bytes(custody.encoded(document)); value.seal()
    if damage == 'unremoved': value.owner['servers'][1]['volumeRemoved'] = False; value.seal()
    if damage == 'retained-volume': value.stopped['derivedVolumesRetained'] = 1
    if damage == 'cleanup-pair': value.stopped['containers'] = ['0' * 64, '1' * 64]
    if damage in ('retained-volume', 'cleanup-pair'): (value.directory / 'public-cleanup.json').write_bytes(custody.encoded(value.stopped))
    if damage == 'byte-claim':
        path = value.old_work / custody.PUBLIC; document = custody.read(path); document['retirementAllowed'] = True
        path.write_bytes(custody.encoded(document))
    if damage == 'logical-claim': value.public['productionMerged'] = True; value.seal()
    if damage == 'missing-logical-file': (value.directory / 'b/full-recovery-private.json').unlink()
    if damage == 'source-archive': (value.root / 'inbox' / ('ci-7-' + 'a' * 12) / 'source.tar.gz').write_bytes(b'changed')
    if damage == 'raw-report': (value.old_work.parent / 'driver.log').write_bytes(b'changed')
    if damage == 'owned-container': value.rows = [('a' * 64, False, False, 0, 'ci-7-' + 'a' * 12, '', [])]
    if damage == 'checkout-bind': value.rows = [('a' * 64, False, False, 0, 'foreign', '', [{'Type': 'bind', 'Source': str(value.old_work.parent)}])]
    with pytest.raises((ValueError, OSError, custody.common().CustodyError)): custody.describe(value.args)
    assert not (value.new_work / custody.SNAPSHOT).exists()


@pytest.mark.parametrize('damage', ['description', 'manifest-size', 'archive-sha', 'existing-target'])
def test_sql_reuse_never_overwrites_or_accepts_drift_after_description(retained_sql_fixture, damage):
    value = retained_sql_fixture; description = custody.describe(value.args)
    value.args.source_receipt_sha256 = description['sourceCustodyReceiptSha256']
    if damage == 'description':
        path = value.old_work / custody.PUBLIC; path.write_bytes(path.read_bytes() + b'\n')
    if damage == 'manifest-size': value.args.manifest_bytes += 1
    if damage == 'archive-sha': value.args.archive_sha256 = '0' * 64
    if damage == 'existing-target':
        target = value.new_work / custody.SNAPSHOT; target.mkdir(mode=0o700); (target / 'unknown').write_bytes(b'keep')
    with pytest.raises(ValueError): custody.reuse(value.args)
    assert not (value.new_work / custody.PUBLIC).exists()
    if damage == 'existing-target': assert (value.new_work / custody.SNAPSHOT / 'unknown').read_bytes() == b'keep'


@pytest.mark.parametrize('damage', ['symlink', 'hardlink', 'fifo', 'writable', 'during-copy'])
def test_old_sql_files_need_stable_private_regular_single_link_fds(retained_sql_fixture, monkeypatch, damage):
    value = retained_sql_fixture; description = custody.describe(value.args)
    value.args.source_receipt_sha256 = description['sourceCustodyReceiptSha256']
    path = value.old_work / custody.SNAPSHOT / 'originals.tar.gz'
    if damage == 'symlink':
        target = path.with_suffix('.retained'); path.rename(target); path.symlink_to(target)
    if damage == 'hardlink': os.link(path, value.old_work / 'extra-alias')
    if damage == 'fifo': path.unlink(); os.mkfifo(path, 0o600)
    if damage == 'writable': path.chmod(0o666)
    if damage == 'during-copy':
        fired = []
        def drift(_path, additional=0):
            if additional == 0 and not fired:
                fired.append(True); before = path.stat(); os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1))
        monkeypatch.setattr(custody.common(), 'resource_guard', drift)
    with pytest.raises((ValueError, OSError, custody.common().CustodyError)): custody.reuse(value.args)
    assert not (value.new_work / custody.PUBLIC).exists()


@pytest.mark.parametrize('damage', ['changed-source', 'missing-member', 'linked-source'])
def test_sql_reuse_guards_cannot_be_imported_before_their_fixed_archive_hashes_match(tmp_path, monkeypatch, damage):
    utility = custody.common(); original_root = custody.ROOT
    root = tmp_path / 'ci'; tag = 'ci-9-' + 'a' * 12; checkout = root / 'verification' / tag / 'checkout'
    names = ('reuse-legacy-source.py', 'verify-remote.py', 'cleanup-ecs-builds.py')
    for name in names:
        path = checkout / 'script/jenkins' / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((original_root / 'script/jenkins' / name).read_bytes())
    archive = root / 'inbox' / tag / 'source.tar.gz'; archive.parent.mkdir(parents=True)
    with tarfile.open(archive, 'x:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': 'a' * 40}) as package:
        for name in names:
            if damage != 'missing-member' or name != names[-1]: package.add(checkout / 'script/jenkins' / name, arcname='script/jenkins/' + name)
    target = checkout / 'script/jenkins' / names[-1]
    if damage == 'changed-source': target.write_bytes(target.read_bytes() + b'\n# changed guard\n')
    if damage == 'linked-source':
        retained = target.with_suffix('.saved'); target.rename(retained); target.symlink_to(retained)
    monkeypatch.setattr(custody, 'ROOT', checkout); monkeypatch.setattr(custody, 'common', lambda: utility)
    monkeypatch.setattr(custody, 'module', lambda *args: pytest.fail('Unverified reuse code must never be imported'))
    with pytest.raises((ValueError, KeyError, OSError, utility.CustodyError)):
        custody.reuse_modules(SimpleNamespace(root=root, tag=tag))


def held_binding(path, role=None):
    value = {'bytes': path.stat().st_size, 'sha256': custody.digest(path), 'maximum': custody.MAX_BYTES}
    if role is not None: value['role'] = role
    return value


def test_original_ci_report_644_is_read_from_the_same_fd_without_changing_bytes_or_mode(retained_sql_fixture):
    value = retained_sql_fixture; path = value.report; original = path.read_bytes()
    assert os.getuid() == os.geteuid() == path.stat().st_uid == 1000
    before = path.stat(); binding = held_binding(path, 'ORIGINAL_CI_REPORT')
    with custody.held_reuse_files({path: binding}, value.root) as (held, verify):
        stream = held[path]
        assert stream.read() == original
        assert (os.fstat(stream.fileno()).st_dev, os.fstat(stream.fileno()).st_ino) == (before.st_dev, before.st_ino)
        assert os.fstat(stream.fileno()).st_mode & 0o777 == 0o644
        verify()
    assert stream.closed and path.read_bytes() == original and path.stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize('member,role', [('sql', None), ('sql', 'PRIVATE_SQL_EVIDENCE'),
    ('source', None), ('tool-manifest', None)])
def test_private_sql_source_and_tool_bindings_keep_owner_only_permissions(retained_sql_fixture, member, role):
    value = retained_sql_fixture; old_tag = value.old_work.parents[1].name
    path = {'sql': value.old_work / custody.RESTORE / 'database.sql',
        'source': value.root / 'inbox' / old_tag / 'source.tar.gz',
        'tool-manifest': value.root / 'inbox' / old_tag / 'tool-runtime/manifest.json'}[member]
    original = path.read_bytes(); binding = held_binding(path, role); path.chmod(0o644)
    with pytest.raises(custody.common().CustodyError, match='owner-only unlinked custody resource'):
        with custody.held_reuse_files({path: binding}, value.root):
            pytest.fail('Private SQL/source/tool evidence cannot use report permissions')
    assert path.read_bytes() == original and path.stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize('damage,reason', [
    ('group-write', 'Original CI report owner/type/link/mode is invalid'),
    ('hardlink', 'Original CI report owner/type/link/mode is invalid'),
    ('symlink', 'Linked custody paths are refused'),
    ('replacement', 'Old SQL custody file identity changed'),
    ('mode-drift', 'Old SQL custody file identity changed'),
])
def test_original_report_role_still_refuses_writes_links_and_held_file_identity_changes(retained_sql_fixture, damage, reason):
    value = retained_sql_fixture; path = value.report; original = path.read_bytes()
    binding = held_binding(path, 'ORIGINAL_CI_REPORT')
    if damage == 'group-write': path.chmod(0o664)
    if damage == 'hardlink': os.link(path, path.with_name('unreviewed-report-alias.xml'))
    if damage == 'symlink':
        retained = path.with_name('retained-original.xml'); path.rename(retained); path.symlink_to(retained)
    with pytest.raises((ValueError, OSError, custody.common().CustodyError), match=reason):
        with custody.held_reuse_files({path: binding}, value.root) as (held, verify):
            assert held[path].read() == original
            if damage == 'replacement':
                path.rename(path.with_name('retained-original.xml'))
                path.write_bytes(original); path.chmod(0o644)
                assert custody.digest(path) == binding['sha256']
            elif damage == 'mode-drift': path.chmod(0o600)
            else: pytest.fail('Unsafe report must be refused before yielding a file descriptor')
            verify()


@pytest.mark.parametrize('damage,reason', [('unknown-role', 'Unknown closed SQL reuse file role'),
    ('sql-as-report', 'Original CI report role requires a fixed report path')])
def test_report_permission_role_is_closed_and_cannot_be_applied_to_sql_outside_the_report_tree(retained_sql_fixture, damage, reason):
    value = retained_sql_fixture
    path = value.report if damage == 'unknown-role' else value.old_work / custody.RESTORE / 'database.sql'
    role = 'UNREVIEWED_ROLE' if damage == 'unknown-role' else 'ORIGINAL_CI_REPORT'
    original = path.read_bytes(); binding = held_binding(path, role)
    with pytest.raises(ValueError, match=reason):
        with custody.held_reuse_files({path: binding}, value.root):
            pytest.fail('Only original catalogued report paths may receive the report role')
    assert path.read_bytes() == original


def test_sql_pack_cli_keeps_stdout_protocol_and_adds_only_bounded_own_locations_on_stderr(export_fixture):
    source = export_fixture; source.output.mkdir(mode=0o700)
    sentinel = source.output / 'keep-original'; sentinel.write_bytes(b'pre-existing output must remain untouched')
    script = ROOT / 'script/jenkins/preserve-local-mysql.py'
    launcher = ('from pathlib import Path\nimport sys\n'
        'script=Path(sys.argv[1]); root=Path(sys.argv[2]); export,control,output=sys.argv[3:]\n'
        'scope={"__name__":"synthetic_sql_cli_contract","__file__":str(script)}\n'
        'exec(compile(script.read_bytes(),str(script),"exec"),scope)\n'
        'scope["LOCAL_ROOT"]=root\n'
        'sys.argv=[str(script),"pack","--export-directory",export,"--control-receipt",control,"--output",output]\n'
        'raise SystemExit(scope["main"]())\n')
    result = subprocess.run([sys.executable, '-I', '-B', '-c', launcher, str(script), str(custody.LOCAL_ROOT),
        str(source.export), str(source.control), str(source.output)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    expected = {'kind': custody.KIND, 'status': 'FAILED', 'phase': 'pack', 'errorType': 'ValueError', 'sourceDeleted': False}
    assert json.loads(result.stdout) == expected
    private = json.loads(result.stderr)
    assert set(private) == set(expected) | {'locations'}
    assert {key: private[key] for key in expected} == expected
    assert 1 <= len(private['locations']) <= 8
    assert {'main', 'pack', 'need'} <= {row['function'] for row in private['locations']}
    assert all(set(row) == {'function', 'line'} and type(row['line']) is int and row['line'] > 0 for row in private['locations'])
    assert str(source.export) not in result.stderr and str(script) not in result.stderr
    assert sentinel.read_bytes() == b'pre-existing output must remain untouched'
    assert {path.name for path in source.output.iterdir()} == {'keep-original'}


def test_sql_failure_locations_filter_foreign_payload_frames_and_keep_only_the_last_eight_own_locations():
    foreign = {'payload': 'PRIVATE_SQL_DIAGNOSTIC /home/private/originals.sql password=PRIVATE_SENTINEL'}
    exec(compile('def need():\n    raise ValueError(payload)\n', '<foreign-sql-diagnostic>', 'exec'), foreign)
    own = {'foreign_guard': foreign['need']}
    program = ('def need(depth):\n'
        '    if depth: return need(depth - 1)\n'
        '    return unreviewed_sql_diagnostic_frame()\n'
        'def unreviewed_sql_diagnostic_frame():\n'
        '    return foreign_guard()\n')
    assert 'unreviewed_sql_diagnostic_frame' not in custody._failure_source_metadata(custody.LOADED_SOURCE)[0]
    exec(compile(program, custody.__file__, 'exec'), own)
    with pytest.raises(ValueError) as caught: own['need'](16)
    locations = custody.failure_locations(caught.value)
    assert locations == [{'function': 'need', 'line': 2}] * 7 + [{'function': 'need', 'line': 3}]
    raw = json.dumps(locations)
    assert 'PRIVATE_SQL_DIAGNOSTIC' not in raw and '/home/private' not in raw and 'PRIVATE_SENTINEL' not in raw
    assert custody.__file__ not in raw and 'foreign-sql-diagnostic' not in raw
