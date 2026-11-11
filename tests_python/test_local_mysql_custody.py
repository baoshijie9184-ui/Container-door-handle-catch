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

# Pure gates used by the separately acknowledged, fixed nonadministrator export.
import io as nonadmin_io

nonadmin_spec = importlib.util.spec_from_file_location('nonadmin_fixed_mysql_policy_contract', ROOT / 'script/jenkins/nonadmin-local-mysql-policy.py')
nonadmin_policy = importlib.util.module_from_spec(nonadmin_spec)
nonadmin_spec.loader.exec_module(nonadmin_policy)

@pytest.fixture
def nonadmin_source():
    historical = {'expectedServerUuid': '11111111-2222-3333-4444-555555555555', 'expectedDataDirectory': nonadmin_policy.DATA_DIRECTORY, 'sourceIniSha256': 'a' * 64, 'sourceUuidMetadataSha256': 'b' * 64}
    command = '"' + nonadmin_policy.EXECUTABLE + '" "' + nonadmin_policy.DEFAULTS + '" MySQL83'
    parent = {'processId': 1000, 'parentProcessId': 500, 'name': 'mysqld.exe', 'createdAtUtc': '2026-11-10T01:00:00.1234567+00:00', 'executablePath': None, 'commandLine': None}
    worker = {**parent, 'processId': 1001, 'parentProcessId': 1000, 'createdAtUtc': '2026-11-10T01:00:01.1234567+00:00'}
    endpoint = {'localAddress': '127.0.0.1', 'localPort': 3306, 'remoteAddress': '0.0.0.0', 'remotePort': 0, 'owningProcess': 1001, 'state': 0}
    record = {'service': {'name': 'MySQL83', 'state': 'Running', 'processId': 1000, 'pathName': command}, 'serviceProcess': parent, 'worker': worker, 'endpoints': [endpoint], 'hostName': 'TEST-WINDOWS'}
    return SimpleNamespace(record=record, historical=historical, command=command)

@pytest.fixture
def nonadmin_history(nonadmin_source, tmp_path, monkeypatch):
    folder = tmp_path / 'fixed-history'
    folder.mkdir(mode=448)
    path = folder / 'history-pins-private.json'
    ownership = {schema: {'matchesPreviouslyInventoriedSchema': True,
        'evidence': [{'path': 'work/fixture-metadata/' + str(index) + '-' + str(number) + '.json', 'sha256': 'f' * 64}
                     for number in range(2 if schema == 'doorhandledb' else 3)]}
        for index, schema in enumerate(nonadmin_policy.SCHEMA_ORDER)}
    bundle = {'kind': 'doorhandle-local-mysql-history-pin-bundle', 'schemaVersion': 1,
        'configuration': nonadmin_source.historical, 'schemas': list(nonadmin_policy.SCHEMA_ORDER),
        'ownership': ownership, 'originalEvidenceSha256': dict(nonadmin_policy.ORIGINAL_EVIDENCE_PINS)}
    raw = nonadmin_policy.encoded(bundle); path.write_bytes(raw)
    monkeypatch.setattr(nonadmin_policy, 'HISTORY_BUNDLE', path)
    monkeypatch.setattr(nonadmin_policy, 'HISTORY_BUNDLE_SHA256', hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(nonadmin_policy, 'HISTORY_CANONICAL_SHA256', nonadmin_policy.checksum(bundle))
    monkeypatch.setattr(nonadmin_policy, 'OWNERSHIP_SHA256', nonadmin_policy.checksum(ownership))
    return SimpleNamespace(path=path, bundle=bundle, raw=raw)

def test_nonadmin_complete_fresh_source_keeps_unknown_truthful_and_hashes_full_observations(nonadmin_source):
    before = copy.deepcopy(nonadmin_source.record)
    result = nonadmin_policy.validate_source(nonadmin_source.record, nonadmin_source.historical)
    assert nonadmin_source.record == before and result['configuration'] == nonadmin_source.historical
    assert result['sourceSeenState'] == [0] and result['tcpEvidenceKind'] == 'UNKNOWN_OWNER_BOUND_ENDPOINT'
    assert result['worker']['processId'] == 1001 and result['serviceProcessId'] == 1000
    visible = copy.deepcopy(nonadmin_source.record)
    visible['worker'].update(executablePath=nonadmin_policy.EXECUTABLE, commandLine=nonadmin_source.command)
    assert nonadmin_policy.validate_source(visible, nonadmin_source.historical)['processObservationSha256'] != result['processObservationSha256']
    listen = copy.deepcopy(nonadmin_source.record)
    listen['endpoints'][0]['state'] = 2
    listen['endpoints'].append({**listen['endpoints'][0], 'localAddress': '::', 'remoteAddress': '::'})
    first = nonadmin_policy.validate_source(listen, nonadmin_source.historical)
    listen['endpoints'].reverse()
    second = nonadmin_policy.validate_source(listen, nonadmin_source.historical)
    assert first == second and first['tcpEvidenceKind'] == 'REPORTED_LISTEN_OWNER_BOUND_ENDPOINT'
    assert first['endpointBindingsSha256'] != result['endpointBindingsSha256']

def test_nonadmin_incomplete_records_and_untyped_service_metadata_cannot_become_source_proof(nonadmin_source):
    for damage in ('missing-service', 'extra-secret', 'missing-host', 'missing-state', 'bool-pid', 'zero-pid', 'wrong-name', 'stopped'):
        value = copy.deepcopy(nonadmin_source.record)
        if damage == 'missing-service':
            value.pop('service')
        elif damage == 'extra-secret':
            value['password'] = 'synthetic-never-output'
        elif damage == 'missing-host':
            value.pop('hostName')
        elif damage == 'missing-state':
            value['service'].pop('state')
        elif damage == 'bool-pid':
            value['service']['processId'] = True
        elif damage == 'zero-pid':
            value['service']['processId'] = 0
        elif damage == 'wrong-name':
            value['service']['name'] = 'OtherMySQL'
        else:
            value['service']['state'] = 'Stopped'
        with pytest.raises(nonadmin_policy.PolicyError):
            nonadmin_policy.validate_source(value, nonadmin_source.historical)

def test_nonadmin_server_command_accepts_only_the_reviewed_quoted_defaults_and_no_overrides(nonadmin_source):
    nonadmin_policy.command(nonadmin_source.command)
    nonadmin_policy.command('"' + nonadmin_policy.EXECUTABLE + '" --defaults-file="C:\\ProgramData\\MySQL\\MySQL Server 8.3\\my.ini"')
    for value in (nonadmin_source.command + ' --port=3307', nonadmin_source.command + ' --datadir=D:\\other', nonadmin_source.command.replace('my.ini', 'foreign.ini'), nonadmin_source.command.replace('mysqld.exe', 'other.exe'), nonadmin_source.command.replace(' MySQL83', ' OtherService'), nonadmin_source.command + '\n', '"' + nonadmin_policy.EXECUTABLE + '""' + nonadmin_policy.DEFAULTS + '"', nonadmin_source.command.replace('"', '\\"')):
        with pytest.raises(nonadmin_policy.PolicyError):
            nonadmin_policy.command(value)

def test_nonadmin_parent_child_identity_and_every_visible_process_field_are_required_to_agree(nonadmin_source):
    for damage in ('missing-pid', 'bad-parent', 'other-name', 'missing-creation', 'bad-creation', 'non-utc', 'older-child', 'other-exe', 'command-override', 'extra-field', 'service-pid-mismatch'):
        value = copy.deepcopy(nonadmin_source.record)
        if damage == 'missing-pid':
            value['worker'].pop('processId')
        elif damage == 'bad-parent':
            value['worker']['parentProcessId'] = 500
        elif damage == 'other-name':
            value['worker']['name'] = 'other.exe'
        elif damage == 'missing-creation':
            value['worker']['createdAtUtc'] = None
        elif damage == 'bad-creation':
            value['worker']['createdAtUtc'] = '2026-99-99T01:00:00Z'
        elif damage == 'non-utc':
            value['worker']['createdAtUtc'] = '2026-11-10T01:00:00+08:00'
        elif damage == 'older-child':
            value['worker']['createdAtUtc'] = '2026-11-09T01:00:00Z'
        elif damage == 'other-exe':
            value['worker']['executablePath'] = 'D:\\unreviewed\\mysqld.exe'
        elif damage == 'command-override':
            value['worker']['commandLine'] = nonadmin_source.command + ' --port=3307'
        elif damage == 'extra-field':
            value['worker']['unreviewed'] = 1
        else:
            value['serviceProcess']['processId'] = 900
        with pytest.raises(nonadmin_policy.PolicyError):
            nonadmin_policy.validate_source(value, nonadmin_source.historical)
    direct = copy.deepcopy(nonadmin_source.record)
    direct['worker'] = copy.deepcopy(direct['serviceProcess'])
    direct['endpoints'][0]['owningProcess'] = direct['service']['processId']
    assert nonadmin_policy.validate_source(direct, nonadmin_source.historical)['worker']['processId'] == 1000
    direct['worker']['parentProcessId'] += 1
    with pytest.raises(nonadmin_policy.PolicyError):
        nonadmin_policy.validate_source(direct, nonadmin_source.historical)

def test_nonadmin_endpoint_owner_state_port_and_membership_cannot_be_relaxed(nonadmin_source):
    for damage in ('no-endpoints', 'bool-state', 'other-state', 'other-port', 'wrong-owner', 'other-address', 'connected-peer', 'missing-field', 'other-owner', 'duplicate'):
        value = copy.deepcopy(nonadmin_source.record)
        endpoint = value['endpoints'][0]
        if damage == 'no-endpoints':
            value['endpoints'] = []
        elif damage == 'bool-state':
            endpoint['state'] = False
        elif damage == 'other-state':
            endpoint['state'] = 5
        elif damage == 'other-port':
            endpoint['localPort'] = 3307
        elif damage == 'wrong-owner':
            endpoint['owningProcess'] = 99
        elif damage == 'other-address':
            endpoint['localAddress'] = '192.0.2.1'
        elif damage == 'connected-peer':
            endpoint['remotePort'] = 12345
        elif damage == 'missing-field':
            endpoint.pop('owningProcess')
        elif damage == 'other-owner':
            value['endpoints'].append({**endpoint, 'owningProcess': 99})
        else:
            value['endpoints'].append(copy.deepcopy(endpoint))
        with pytest.raises(nonadmin_policy.PolicyError):
            nonadmin_policy.validate_source(value, nonadmin_source.historical)

def test_nonadmin_fixed_history_bundle_closes_identity_ownership_schemas_and_exact_sha(nonadmin_history, nonadmin_source, monkeypatch):
    reads = []; original_reader = nonadmin_policy.read_fixed_json
    def observed(path, pin):
        reads.append(path); return original_reader(path, pin)
    monkeypatch.setattr(nonadmin_policy, 'read_fixed_json', observed)
    assert nonadmin_policy.load_historical() == nonadmin_source.historical
    assert reads == [nonadmin_history.path]
    assert nonadmin_policy.validate_history(nonadmin_history.bundle) == nonadmin_source.historical
    for (field, changed) in [('expectedServerUuid', 'not-a-uuid'), ('expectedDataDirectory', 'D:\\other'), ('sourceIniSha256', 'short')]:
        value = {**nonadmin_source.historical, field: changed}
        with pytest.raises(nonadmin_policy.PolicyError):
            nonadmin_policy.validate_source(nonadmin_source.record, value)
    for damage in ('kind', 'bool-version', 'extra-schema', 'ownership', 'evidence-path', 'original-sha', 'uuid'):
        value = copy.deepcopy(nonadmin_history.bundle)
        if damage == 'kind': value['kind'] = 'unreviewed-history'
        elif damage == 'bool-version': value['schemaVersion'] = True
        elif damage == 'extra-schema': value['schemas'].append('other_project')
        elif damage == 'ownership': value['ownership']['doorhandledb']['matchesPreviouslyInventoriedSchema'] = False
        elif damage == 'evidence-path': value['ownership']['doorhandledb']['evidence'][0]['path'] = '../private.json'
        elif damage == 'original-sha': value['originalEvidenceSha256']['public-manifest.json'] = 'e' * 64
        else: value['configuration']['expectedServerUuid'] = '99999999-2222-3333-4444-555555555555'
        with pytest.raises(nonadmin_policy.PolicyError): nonadmin_policy.validate_history(value)
    nonadmin_history.path.write_bytes(b'{"changed":true}')
    with pytest.raises(nonadmin_policy.PolicyError, match='HISTORY_PIN_MISMATCH'):
        nonadmin_policy.load_historical()

def test_nonadmin_history_reader_rejects_links_oversize_and_same_fd_changes_without_writing_source(tmp_path, monkeypatch):
    path = tmp_path / 'receipt.json'
    path.write_bytes(b'{}')
    pin = hashlib.sha256(b'{}').hexdigest()
    assert nonadmin_policy.read_fixed_json(path, pin) == {} and path.read_bytes() == b'{}'
    link = tmp_path / 'hardlink'
    os.link(path, link)
    with pytest.raises(nonadmin_policy.PolicyError):
        nonadmin_policy.read_fixed_json(path, pin)
    link.unlink()
    alias = tmp_path / 'symlink'
    alias.symlink_to(path)
    with pytest.raises(nonadmin_policy.PolicyError, match='HISTORY_LINK'):
        nonadmin_policy.read_fixed_json(alias, pin)
    oversized = tmp_path / 'oversized.json'
    oversized.write_bytes(b'x' * (nonadmin_policy.MAXIMUM + 1))
    with pytest.raises(nonadmin_policy.PolicyError):
        nonadmin_policy.read_fixed_json(oversized, 'a' * 64)
    original = nonadmin_policy.os.fstat
    calls = []

    def changed(descriptor):
        value = original(descriptor)
        calls.append(True)
        if len(calls) == 1:
            return value
        return SimpleNamespace(**{key: getattr(value, key) for key in ('st_dev', 'st_ino', 'st_size', 'st_ctime_ns', 'st_mode', 'st_nlink')}, st_mtime_ns=value.st_mtime_ns + 1)
    monkeypatch.setattr(nonadmin_policy.os, 'fstat', changed)
    with pytest.raises(nonadmin_policy.PolicyError, match='HISTORY_CHANGED_DURING_READ'):
        nonadmin_policy.read_fixed_json(path, pin)

def test_nonadmin_source_cli_uses_fixed_history_and_never_echoes_invalid_input_values(nonadmin_history, nonadmin_source, monkeypatch, capsys):
    monkeypatch.setattr(nonadmin_policy.sys, 'stdin', nonadmin_io.StringIO(json.dumps(nonadmin_source.record)))
    assert nonadmin_policy.main(['source']) == 0
    assert json.loads(capsys.readouterr().out) == nonadmin_policy.validate_source(nonadmin_source.record, nonadmin_source.historical)
    marker = 'synthetic-value-must-never-be-echoed'
    for (arguments, raw) in [(['source'], json.dumps({**nonadmin_source.record, 'password': marker})), (['source', marker], '{}'), (['source'], '{"key":1,"key":2}'), (['source'], '{invalid-' + marker), (['source'], 'x' * (nonadmin_policy.MAXIMUM + 1))]:
        monkeypatch.setattr(nonadmin_policy.sys, 'stdin', nonadmin_io.StringIO(raw))
        assert nonadmin_policy.main(arguments) == 1
        output = capsys.readouterr()
        assert marker not in output.out + output.err
        assert json.loads(output.out)['status'] == 'REFUSED' and (not output.err)

def test_nonadmin_direct_global_or_schema_grants_prove_the_requested_export_without_account_values():
    for schema in nonadmin_policy.SCHEMAS:
        all_grants = {'schema': schema, 'grants': [{'scope': '*.*', 'privileges': ['ALL PRIVILEGES']}]}
        split = {'schema': schema, 'grants': [{'scope': '*.*', 'privileges': ['SELECT']}, {'scope': schema + '.*', 'privileges': ['TRIGGER', 'EVENT']}]}
        expected = {'scope': schema, 'select': True, 'trigger': True, 'event': True, 'routines': True, 'directGrantsVerified': True}
        assert nonadmin_policy.validate_privileges(all_grants) == nonadmin_policy.validate_privileges(split) == expected

def test_nonadmin_privilege_scope_roles_and_missing_global_select_cannot_authorize_routine_export():
    schema = 'doorhandledb'
    good = {'schema': schema, 'grants': [{'scope': '*.*', 'privileges': ['SELECT', 'TRIGGER', 'EVENT']}]}
    for damage in ('schema', 'schema-type', 'no-global-select', 'show-routine-only', 'no-event', 'foreign-scope', 'role-only', 'unknown-field', 'lowercase', 'duplicate'):
        value = copy.deepcopy(good)
        if damage == 'schema':
            value['schema'] = 'other_project'
        elif damage == 'schema-type':
            value['schema'] = []
        elif damage == 'no-global-select':
            value['grants'][0]['scope'] = schema + '.*'
        elif damage == 'show-routine-only':
            value['grants'][0]['privileges'] = ['SHOW_ROUTINE', 'TRIGGER', 'EVENT']
        elif damage == 'no-event':
            value['grants'][0]['privileges'].remove('EVENT')
        elif damage == 'foreign-scope':
            value['grants'].append({'scope': 'other_project.*', 'privileges': ['ALL PRIVILEGES']})
        elif damage == 'role-only':
            value['grants'] = [{'role': 'not-direct'}]
        elif damage == 'unknown-field':
            value['grants'][0]['username'] = 'not-accepted'
        elif damage == 'lowercase':
            value['grants'][0]['privileges'] = ['select', 'TRIGGER', 'EVENT']
        else:
            value['grants'][0]['privileges'].append('SELECT')
        with pytest.raises(nonadmin_policy.PolicyError):
            nonadmin_policy.validate_privileges(value)


def test_nonadmin_dotnet_creation_times_work_with_the_existing_pre311_interpreter(nonadmin_source, monkeypatch):
    real_datetime = nonadmin_policy.dt.datetime
    parsed = []

    class LegacyDateTime:
        @staticmethod
        def fromisoformat(value):
            # Python 3.9, used by the Windows producer, rejects .NET's seven
            # fractional digits. The ECS interpreter alone cannot expose it.
            parsed.append(value)
            if '.' in value:
                raise ValueError('Legacy parser refuses seven-digit fractions')
            return real_datetime.fromisoformat(value)

    monkeypatch.setattr(nonadmin_policy, 'dt', SimpleNamespace(datetime=LegacyDateTime))
    result = nonadmin_policy.validate_source(nonadmin_source.record, nonadmin_source.historical)
    assert result['serviceCreatedAtUtc'] == nonadmin_source.record['serviceProcess']['createdAtUtc']
    assert result['worker']['createdAtUtc'] == nonadmin_source.record['worker']['createdAtUtc']
    assert parsed == ['2026-11-10T01:00:00+00:00', '2026-11-10T01:00:01+00:00']


@pytest.mark.parametrize('parent,worker,admitted', [
    ('00.1234567Z', '00.1234566+00:00', False),
    ('00.1234567Z', '00.1234567+00:00', True),
    ('00.1234567Z', '00.1234568+00:00', True),
    ('00.1Z', '00.1000000+00:00', True),
    ('00Z', '00.0000000+00:00', True),
    ('01Z', '00.9999999Z', False),
    ('00.9999999Z', '01Z', True),
])
def test_nonadmin_process_ordering_preserves_all_100ns_ticks(nonadmin_source, parent, worker, admitted):
    value = copy.deepcopy(nonadmin_source.record)
    value['serviceProcess']['createdAtUtc'] = '2026-11-10T01:00:' + parent
    value['worker']['createdAtUtc'] = '2026-11-10T01:00:' + worker
    if admitted:
        result = nonadmin_policy.validate_source(value, nonadmin_source.historical)
        assert result['worker']['createdAtUtc'] == value['worker']['createdAtUtc']
    else:
        with pytest.raises(nonadmin_policy.PolicyError, match='NONADMIN_LISTENER_PARENT_BINDING_DIFFERS'):
            nonadmin_policy.validate_source(value, nonadmin_source.historical)


@pytest.mark.parametrize('stamp', [
    '2026-02-29T01:00:00.1234567Z', '2026-11-10T01:00:60.1234567Z',
    '2026-11-10T01:00:00.12345678Z', '2026-11-10T01:00:00.1234567+08:00',
])
def test_nonadmin_portable_creation_parser_keeps_the_original_calendar_utc_and_precision_limits(nonadmin_source, stamp):
    value = copy.deepcopy(nonadmin_source.record['worker']); value['createdAtUtc'] = stamp
    with pytest.raises(nonadmin_policy.PolicyError, match='NONADMIN_PROCESS_CREATION_REQUIRED'):
        nonadmin_policy.process(value)


def test_nonadmin_powershell_refusal_codes_are_exactly_the_policy_value_free_literals():
    import ast
    import re

    source = (ROOT / 'script/jenkins/nonadmin-local-mysql-policy.py').read_text(encoding='utf-8-sig')
    tree = ast.parse(source)
    codes = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
             and isinstance(node.value, str) and re.fullmatch('NONADMIN_[A-Z0-9_]+', node.value)}
    adapter = (ROOT / 'script/jenkins/nonadmin-local-mysql-source.ps1').read_text(encoding='utf-8-sig')
    refusal = adapter.split('function Get-NonAdminPolicyRefusalCode', 1)[1].split('function Invoke-NonAdminMetadataPolicy', 1)[0]
    admitted = set(re.findall("'(NONADMIN_[A-Z0-9_]+)'", refusal)) - {'NONADMIN_METADATA_REFUSED'}
    assert admitted == codes
    assert '\\A' in refusal and '\\z' in refusal and '$Matches[1] -cin $codes' in refusal
    invoke = adapter.split('function Invoke-NonAdminMetadataPolicy', 1)[1].split('function Convert-NonAdminProcess', 1)[0]
    assert "$process.ExitCode -eq 1" in invoke and 'Get-NonAdminPolicyRefusalCode $answer' in invoke
    assert "Require-Export $false 'Source metadata policy refused the observation.' $refusal" in invoke
    assert '[void]$write.GetAwaiter().GetResult(); $process.StandardInput.Close()' in invoke
    assert invoke.index("'NONADMIN_POLICY_CHANGED'", invoke.index('$answer =')) < invoke.index('Get-NonAdminPolicyRefusalCode $answer')
    assert 'Write-Output $answer' not in invoke and 'Write-Output $diagnostic' not in invoke


def test_worker_failure_survives_terminating_pipeline_without_widening_success_custody_protocol():
    import re

    worker = (ROOT / 'script/jenkins/export-legacy-local-mysql.ps1').read_text(encoding='utf-8-sig')
    batch = (ROOT / 'script/jenkins/export-remaining-local-mysql.ps1').read_text(encoding='utf-8-sig')
    adapter = (ROOT / 'script/jenkins/nonadmin-local-mysql-source.ps1').read_text(encoding='utf-8-sig')
    capture = batch.split('function Get-BatchWorkerFailure', 1)[1].split('Require-Batch ($IsWindows', 1)[0]
    codes = set(re.findall("'(NONADMIN_[A-Z0-9_]+|EXPORT_[A-Z0-9_]+|[A-Z_]*AUTHORIZATION_REQUIRED|"
                           "FIXED_SOURCE_SCHEMA_REQUIRED|INSUFFICIENT_PROCESS_METADATA|NO_REVIEWED_TCP_ENDPOINT|ADMINISTRATOR_TOKEN_REQUIRED)'", worker + adapter))
    # AUTHORIZATION_REQUIRED is a phase, not a reason emitted by a guard.
    codes -= {'AUTHORIZATION_REQUIRED'}
    delegated = adapter.split('function Get-NonAdminPolicyRefusalCode', 1)[1].split('function Invoke-NonAdminMetadataPolicy', 1)[0]
    batch_codes = set(re.findall("'([A-Z][A-Z0-9_]+)'", capture))
    assert codes <= batch_codes | set(re.findall("'(NONADMIN_[A-Z0-9_]+)'", delegated))
    assert "$workerFailure.Data['ExportFailurePublicJson'] = $publicFailureJson" in worker
    assert worker.index("$workerFailure.Data['ExportFailurePublicJson']") < worker.index('throw $workerFailure')
    assert '$depth -lt 8' in capture and 'GetByteCount($raw) -gt 4096' in capture
    assert 'ConvertFrom-Json -InputObject $raw -AsHashtable -Depth 8' in capture
    assert '($value.Keys | Sort-Object)' in capture and '$value.phase -cnotin $phases' in capture
    assert all('$value.' + name + ' -isnot [string]' in capture for name in ('kind', 'status', 'phase', 'sourceMode', 'reasonCode'))
    assert "$knownReason = $value.reasonCode -cin $codes" in capture
    assert "Get-NonAdminPolicyRefusalCode $envelope" in capture
    assert "if ($value.errorType -cnotin $types) { $value.errorType = 'UnclassifiedExportFailure' }" in capture
    assert '$Failure.Message' not in capture and '$candidate.Message' not in capture and '$_.Exception | ConvertTo-Json' not in batch
    assert 'Get-BatchWorkerFailure $_.Exception ([bool]$NonAdministratorReadOnlyExport)' in batch
    assert "if ($failureType) {\n    $receipt['workerFailureDetailsStatus']" in batch
    assert "automaticRetryAllowed = $false" in batch


@pytest.fixture
def supervised_sql(tmp_path, monkeypatch):
    controller = object.__new__(recovery.Recovery)
    controller.work = tmp_path; controller.directory = tmp_path / 'local-mysql-recovery'
    controller.owner_file = tmp_path / 'local-mysql-recovery-owner.json'
    controller.context = {'version': 1, 'kind': 'synthetic-custody', 'profile': 'local-mysql-export45-v1',
        'release': 'ci-1-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64,
        'identity': {'instanceId': 'i-synthetic', 'machineId': 'c' * 32, 'executionLocation': 'ECS'},
        'verificationReceiptSha256': 'd' * 64}
    controller.bytes = custody; controller.utility = SimpleNamespace(owner_path=lambda p: p)
    controller.state = None; calls = []
    controller.run = lambda: calls.append('run') or {'status': 'SQL_DOUBLE_RESTORED_VERIFIED'}
    controller.cleanup = lambda: calls.append('cleanup') or {'status': 'STOPPED'}
    monkeypatch.setattr(recovery, 'process_start', lambda _: '5678')
    def claim(status=None):
        supervisor_file, terminal_file = controller.supervision_paths()
        supervisor = {**controller.context, 'supervisionKind': 'doorhandle-sql-recovery-supervisor',
            'executionId': 'e' * 32, 'pid': 4321, 'startTicks': '5678',
            'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'startedAtUnix': int(recovery.time.time())}
        custody.write(supervisor_file, supervisor)
        if status:
            controller.publish_terminal(terminal_file, {**controller.context,
                'supervisionKind': 'doorhandle-sql-recovery-terminal', 'executionId': 'e' * 32,
                'status': status, 'result': {'status': 'SQL_DOUBLE_RESTORED_VERIFIED'} if status == 'PASS' else None,
                'errorType': None if status == 'PASS' else 'ValueError'})
        return supervisor_file, terminal_file
    return SimpleNamespace(controller=controller, calls=calls, claim=claim)


def test_sql_run_registers_one_original_supervisor_and_publishes_original_success(supervised_sql):
    value = supervised_sql; result = value.controller.run_supervised()
    supervisor, terminal = value.controller.supervision_paths()
    assert value.calls == ['run'] and custody.read(terminal)['result'] == result
    assert custody.read(terminal)['executionId'] == custody.read(supervisor)['executionId']
    before = {p.name: p.read_bytes() for p in value.controller.work.iterdir()}
    with pytest.raises(ValueError, match='already started'): value.controller.run_supervised()
    assert value.calls == ['run'] and before == {p.name: p.read_bytes() for p in value.controller.work.iterdir()}


@pytest.mark.parametrize('failure', [ValueError, KeyboardInterrupt])
def test_sql_real_failure_or_explicit_signal_cleans_before_publishing_failed_terminal(supervised_sql, failure):
    value = supervised_sql; value.controller.state = {'owned': True}
    def fail(): raise failure('synthetic owned failure')
    def cleanup():
        assert not value.controller.supervision_paths()[1].exists()
        value.calls.append('cleanup')
    value.controller.run = fail; value.controller.cleanup = cleanup
    with pytest.raises(failure): value.controller.run_supervised()
    terminal = custody.read(value.controller.supervision_paths()[1])
    assert value.calls == ['cleanup'] and terminal['status'] == 'FAILED' and terminal['result'] is None
    assert terminal['errorType'] == failure.__name__


@pytest.mark.parametrize('status', ['PASS', 'FAILED'])
def test_sql_observe_preserves_original_terminal_outcome_and_never_runs_or_cleans(supervised_sql, status):
    value = supervised_sql; value.claim(status)
    before = {p.name: p.read_bytes() for p in value.controller.work.iterdir()}
    result = value.controller.observe()
    assert result['status'] == status and result['terminal'] is True and result['executionId'] == 'e' * 32
    assert value.calls == [] and before == {p.name: p.read_bytes() for p in value.controller.work.iterdir()}


@pytest.mark.parametrize('field', ['release','sourceSha256','identity','bootId'])
def test_sql_observe_refuses_a_foreign_original_supervisor(supervised_sql, field):
    value = supervised_sql; supervisor, _ = value.claim()
    record = custody.read(supervisor); record[field] = 'different-execution'
    supervisor.write_bytes(custody.encoded(record))
    with pytest.raises(ValueError, match='another execution'): value.controller.observe()
    assert value.calls == []


def test_sql_observe_refuses_terminal_from_another_execution_id(supervised_sql):
    value = supervised_sql; _, terminal = value.claim('PASS')
    record = custody.read(terminal); record['executionId'] = 'f' * 32; terminal.write_bytes(custody.encoded(record))
    with pytest.raises(ValueError, match='terminal evidence'): value.controller.observe()
    assert value.calls == []


@pytest.mark.parametrize('state', ['reused-pid','dead-pid'])
def test_sql_observe_does_not_follow_reused_or_dead_processes_without_terminal(supervised_sql, monkeypatch, state):
    value = supervised_sql; value.claim()
    def changed(_):
        if state == 'dead-pid': raise FileNotFoundError('original supervisor exited')
        return '9999'
    monkeypatch.setattr(recovery, 'process_start', changed)
    with pytest.raises(ValueError, match='without terminal evidence'): value.controller.observe()
    assert value.calls == [] and not (value.controller.work / value.controller.cancel_name).exists()


def test_sql_observe_waits_only_for_its_original_live_run(supervised_sql, monkeypatch, capsys):
    value = supervised_sql; _, terminal = value.claim(); sleeps = []
    def finish(seconds):
        sleeps.append(seconds); value.controller.publish_terminal(terminal, {**value.controller.context,
            'supervisionKind': 'doorhandle-sql-recovery-terminal', 'executionId': 'e' * 32,
            'status': 'PASS', 'result': {'status': 'SQL_DOUBLE_RESTORED_VERIFIED'}, 'errorType': None})
    monkeypatch.setattr(recovery.time, 'sleep', finish)
    assert value.controller.observe()['status'] == 'PASS' and sleeps == [5] and value.calls == []
    assert json.loads(capsys.readouterr().out)['status'] == 'RUNNING'


@pytest.mark.parametrize('run_requested', [False, True])
def test_sql_observe_proves_not_started_only_before_a_run_request_was_issued(supervised_sql, run_requested):
    value = supervised_sql; value.controller.args=SimpleNamespace(run_requested=run_requested)
    result = value.controller.observe()
    assert result['status'] == ('PENDING' if run_requested else 'NOT_STARTED')
    assert result['terminal'] is (not run_requested) and result['executionId'] is None
    assert not list(value.controller.work.iterdir()) and value.calls == []


@pytest.mark.parametrize('partial', ['owner','directory'])
def test_sql_observe_retains_unsupervised_partial_recovery(supervised_sql, partial):
    value = supervised_sql
    if partial == 'owner': value.controller.owner_file.write_bytes(b'preserved original ownership')
    else: value.controller.directory.mkdir()
    with pytest.raises(ValueError, match='no supervisor proof'): value.controller.observe()
    assert value.calls == []


def test_sql_observation_deadline_does_not_cancel_or_restart_the_original_run(supervised_sql, monkeypatch):
    value = supervised_sql; value.claim(); ticks = iter([0, recovery.OBSERVATION_TIMEOUT + 1])
    monkeypatch.setattr(recovery.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(ValueError, match='observation timed out'): value.controller.observe()
    assert value.calls == []


def test_sql_broken_ssh_stdout_is_not_a_recovery_failure(monkeypatch):
    redirected = []
    def broken(*_, **__): raise BrokenPipeError('closed transport')
    monkeypatch.setattr('builtins.print', broken)
    monkeypatch.setattr(recovery.os, 'dup2', lambda source, target: redirected.append(target))
    recovery.emit({'status':'PASS'})
    assert redirected == [1]


def test_sql_controller_observes_original_run_before_automatic_cleanup_and_never_retries_run():
    script = (ROOT / 'script/jenkins/preserve-local-mysql.ps1').read_text()
    observer = script.split('function Observe-SqlRecovery {',1)[1].split('function Collect-SqlCleanup',1)[0]
    assert "'$recovery' observe $context" in observer and "'$recovery' run" not in observer
    cleanup = script.split('function Collect-SqlCleanup {',1)[1].split("if ($Mode -eq 'Cleanup')",1)[0]
    assert cleanup.index('$null=Observe-SqlRecovery') < cleanup.index("'$recovery' cleanup")
    assert '$failed -and $LASTEXITCODE -eq 255' in script and '$result=$observed.result; $failed=$null' in script
    assert 'artifacts/local-mysql-run-request.json' in script and '$requested=Test-SqlRunRequested' in observer
    assert '--run-requested' in observer and "$value.status -ceq 'PENDING'" in observer
    assert "(-not $requested -or $value.status -cne 'NOT_STARTED')" in observer
    assert script.index('Set-Content -LiteralPath $sqlRunRequest') < script.index("'$recovery' run")
    request = script.split('function Test-SqlRunRequested {',1)[1].split('function Observe-SqlRecovery',1)[0]
    assert all('$request.'+name in request for name in ('release','commit','sourceSha256','verificationReceiptSha256','identity','runAttempted'))


@pytest.mark.parametrize('operation', ['run','observe'])
def test_sql_outer_cli_does_not_cancel_work_when_registration_or_observation_is_unknown(monkeypatch, capsys, operation):
    calls = []
    class Controller:
        state = {'owned': True}
        def __init__(self, _): pass
        def run_supervised(self): raise ValueError('original execution is already registered')
        def observe(self): raise ValueError('original outcome is not yet known')
        def cleanup(self): calls.append('wrong implicit cancellation')
    argv = ['restore-local-mysql.py', operation]
    for name, value in {'root':'/home/ecs-user/ci','tag':'ci-1-'+'a'*12,'commit':'a'*40,
        'source-sha256':'b'*64,'instance-id':'i-synthetic','machine-id':'c'*32}.items(): argv += ['--'+name,value]
    monkeypatch.setattr(sys, 'argv', argv); monkeypatch.setattr(recovery, 'Recovery', Controller)
    monkeypatch.setattr(recovery.signal, 'signal', lambda *_: None)
    assert recovery.main() == 2 and calls == []
    assert json.loads(capsys.readouterr().out)['status'] == 'FAILED'


def test_sql_observe_does_not_treat_a_pending_supervisor_publication_as_not_started(supervised_sql):
    value = supervised_sql; supervisor, _ = value.controller.supervision_paths()
    supervisor.with_name(supervisor.name + '.pending').write_bytes(b'original supervisor still publishing')
    with pytest.raises(ValueError, match='publication is incomplete'): value.controller.observe()
    assert value.calls == []
