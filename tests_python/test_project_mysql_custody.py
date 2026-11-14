"""Synthetic byte/restore contracts; execute only through Jenkins on ECS."""
import ast
import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
from types import SimpleNamespace
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'script/jenkins' / file)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


packet = load('project_custody_contract', 'project-mysql-custody.py')
restore = load('project_restore_contract', 'restore-project-mysql.py')


def write(path, value):
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()); path.chmod(0o600)


@pytest.fixture
def exported(tmp_path, monkeypatch):
    project = tmp_path / 'project'; (project / 'work/jenkins').mkdir(parents=True)
    base = project / 'work/data-migration-20261107'; base.mkdir()
    batch_dir = project / 'work/jenkins/remaining-local-mysql-export-synthetic'; batch_dir.mkdir()
    monkeypatch.setattr(packet, 'PROJECT', project)
    producers = {name: (ROOT / 'script/jenkins' / file).read_bytes() for name, file in packet.PRODUCERS.items()}
    hashes = {name: hashlib.sha256(body).hexdigest() for name, body in producers.items()}
    dependency = {name: hashes[name] for name in ('sourceHelper', 'policy')}; dependency['interpreter'] = 'a' * 64
    authorization = {'kind': 'doorhandle-nonadmin-remaining-local-mysql-export-authorization',
        'sourceSchemas': list(packet.SCHEMAS), 'newOneTimeReadOnlyExceptionAcknowledged': True,
        'includeLegacyBusinessSource': True, 'userAuthorizationReference': 'synthetic-authorized-export',
        'workerScriptSha256': hashes['worker'], 'batchScriptSha256': hashes['batch'], 'dependencySha256': dependency}
    entries = []; manifests = {}
    for schema in packet.SCHEMAS:
        directory = base / ('local-mysql-export-synthetic-' + schema); directory.mkdir()
        for name in packet.EXPORT_MEMBERS - {'public-manifest.json'}: (directory / name).write_bytes(b'{}')
        identity = {'schema': schema, 'serverUuid': '11111111-1111-1111-1111-111111111111', 'version': '8.3.0', 'port': 3306,
                    'dataDirectory': 'C:/synthetic-owned-project-only', 'hostName': 'synthetic', 'currentAccount': 'root@localhost'}
        credential_sha = '97c366105bd23057d4733636b05766eb36e03da1a07af6e8b37dd0c4c90e6b2b'
        write(directory / 'authorization-private.json', {
            'kind': 'doorhandle-nonadmin-local-mysql-export-authorization', 'sourceSchema': schema,
            'userAuthorizationReference': authorization['userAuthorizationReference'], 'oneTimeReadOnlyExceptionAcknowledged': True,
            'additionalFixtureReadOnlyExceptionAcknowledged': True, 'sourceMode': 'PINNED_HISTORY_FRESH_SERVICE_TCP',
            'credentialSourceSha256': credential_sha, 'sourceProcess': {'configuration': {
                'expectedServerUuid': identity['serverUuid'], 'expectedDataDirectory': identity['dataDirectory']}}})
        write(directory / 'credential-handle-private.json', {'kind': 'doorhandle-fixed-credential-read-observation',
            'sourceContentModified': False, 'sourceAclModified': False, 'credentialValuesIncluded': False, 'sourceSha256': credential_sha})
        for phase in ('before', 'after'):
            write(directory / (phase + '-identity-private.json'), identity)
            (directory / (phase + '-catalog-private.jsonl')).write_bytes(b'{"table":"records","kind":"BASE TABLE","engine":"InnoDB"}\n')
            (directory / (phase + '-row-counts-private.jsonl')).write_bytes(b'{"table":"records","rows":1}\n')
            write(directory / (phase + '-privileges-private.json'), {'scope': schema, 'select': True, 'trigger': True,
                'event': True, 'routines': True, 'directGrantsVerified': True})
        sql = b'CREATE TABLE records(id BIGINT PRIMARY KEY);\nINSERT INTO records VALUES(1);\n'
        (directory / 'database.sql').write_bytes(sql); compressed = gzip.compress(sql); (directory / 'database.sql.gz').write_bytes(compressed)
        (directory / 'schema-before.sql').write_bytes(sql.split(b'INSERT')[0])
        (directory / 'schema-after.sql').write_bytes(sql.split(b'INSERT')[0])
        manifest = {'schemaVersion': 2, 'kind': 'doorhandle-nonadmin-local-mysql-export',
            'status': 'LOCAL_EXPORT_COMPLETE_RESTORE_PENDING', 'sourceSchema': schema, 'sourceEndpoint': '127.0.0.1:3306',
            'sourceMode': 'PINNED_HISTORY_FRESH_SERVICE_TCP', 'scriptSha256': hashes['worker'],
            'sourceHelperSha256': hashes['sourceHelper'], 'policySha256': hashes['policy'], 'policyInterpreterSha256': dependency['interpreter'],
            'rowEvidence': 'BEFORE_AFTER_OBSERVATIONS_NOT_THE_DUMP_TRANSACTION', 'ddlEvidence': 'MATCHING_RESTRICTED_BEFORE_AFTER_DDL',
            'dumpConsistency': 'MYSQLDUMP_SINGLE_TRANSACTION_INNODB', 'tableCount': 1, 'observedRowsBefore': 1, 'observedRowsAfter': 1,
            'rawSqlSha256': hashlib.sha256(sql).hexdigest(), 'rawSqlBytes': len(sql),
            'gzipSha256': hashlib.sha256(compressed).hexdigest(), 'gzipBytes': len(compressed)}
        manifest['credentialSourceSha256'] = credential_sha
        manifest.update({key: True for key in ('restorePending', 'historicalConfigurationPinVerified', 'freshServiceEndpointVerified',
            'freshDirectPrivilegesVerified', 'actualClientIdentityVerified', 'privateInputFilesRemoved', 'gzipByteReadbackVerified')})
        manifest.update({key: False for key in ('sourceConfigurationVerified', 'credentialsArchived', 'sourceDeleted', 'servicesChanged',
            'testsExecuted', 'cloudUploaded', 'backupRestoreVerified', 'retirementAllowed')})
        manifest['files'] = {name: {'bytes': (directory / name).stat().st_size, 'sha256': packet.digest(directory / name)}
                            for name in packet.EXPORT_MEMBERS - {'public-manifest.json'}}
        write(directory / 'public-manifest.json', manifest); manifests[schema] = manifest
        entry = {'sourceSchema': schema, 'status': manifest['status'], 'exportDirectory': str(directory),
            **{key: manifest[key] for key in ('tableCount', 'observedRowsBefore', 'observedRowsAfter', 'rawSqlSha256', 'gzipSha256')},
            'manifestSha256': packet.digest(directory / 'public-manifest.json'), 'backupRestoreVerified': False, 'retirementAllowed': False}
        entries.append(entry); write(batch_dir / (schema + '-result.json'), entry)
    batch = {'kind': 'doorhandle-nonadmin-remaining-local-mysql-export', 'schemaVersion': 2,
        'status': 'LOCAL_EXPORTS_COMPLETE_ECS_RESTORE_PENDING', 'sourceSchemas': list(packet.SCHEMAS), 'completedSchemas': list(packet.SCHEMAS),
        'sourceMode': 'PINNED_HISTORY_FRESH_SERVICE_TCP', 'restorePending': True, 'exports': entries, 'failedSchema': None, 'errorType': None,
        'userAuthorizationReference': authorization['userAuthorizationReference'], 'workerScriptSha256': hashes['worker'], 'dependencySha256': dependency}
    batch.update({key: False for key in ('sourceMutationsRequested', 'servicesChanged', 'testsExecuted', 'cloudUploaded',
        'backupRestoreVerified', 'retirementAllowed', 'automaticRetryAllowed')})
    write(batch_dir / 'authorization-private.json', authorization); write(batch_dir / 'batch-result-private.json', batch)
    return SimpleNamespace(project=project, batch_dir=batch_dir, batch=batch, authorization=authorization,
        manifests=manifests, producer=producers, batch_sha=packet.digest(batch_dir / 'batch-result-private.json'),
        output=base / 'project-mysql-custody-synthetic')


def test_actual_packet_preserves_all_export_members_and_producer_bytes(exported):
    result = packet.pack(exported.batch_dir, exported.batch_sha, exported.output)
    manifest = packet.read(exported.output / 'custody.json')
    assert result['status'] == 'PACKED_RESTORE_PENDING' and result['databasesOpened'] == 0
    assert result['retirementAllowed'] is False and manifest['liveSourceRowHashesVerified'] is False
    assert set(manifest['schemas']) == set(packet.SCHEMAS)
    assert manifest['schemas'][packet.SCHEMAS[1]]['purpose'] == 'FIXTURE_ARCHIVE_ONLY'
    with tarfile.open(exported.output / 'originals.tar.gz', 'r:gz') as archive:
        assert set(archive.getnames()) == packet.MEMBERS
        for key, file in packet.PRODUCERS.items(): assert archive.extractfile('producer/' + file).read() == exported.producer[key]


@pytest.mark.parametrize('mutation', ['missing-schema', 'wrong-source', 'partial', 'source-hash-claim', 'credential-sidefile',
    'dependency-drift', 'authorization-drift', 'foreign-schema', 'version1'])
def test_closed_source_contract_refuses_partial_or_relabelled_exports(exported, mutation):
    source = exported; batch = copy.deepcopy(source.batch); auth = copy.deepcopy(source.authorization); manifests = copy.deepcopy(source.manifests)
    public = manifests[packet.SCHEMAS[0]]
    if mutation == 'missing-schema': batch['completedSchemas'].pop()
    if mutation == 'wrong-source': public['sourceSchema'] = packet.SCHEMAS[1]
    if mutation == 'partial': batch['status'] = 'PARTIAL_OR_FAILED'
    if mutation == 'source-hash-claim': public['rowEvidence'] = 'SAME_TRANSACTION_SOURCE_ROW_HASHES'
    if mutation == 'credential-sidefile': public['files']['client-private.ini'] = {'bytes': 5, 'sha256': 'a' * 64}
    if mutation == 'dependency-drift': batch['dependencySha256']['policy'] = 'b' * 64
    if mutation == 'authorization-drift': auth['includeLegacyBusinessSource'] = False
    if mutation == 'foreign-schema': batch['sourceSchemas'][-1] = 'another_project'
    if mutation == 'version1': public['schemaVersion'] = 1
    with pytest.raises(ValueError): packet.validate_exports(batch, auth, manifests, source.batch_sha, source.producer)


def test_actual_pack_refuses_changed_raw_sql_or_unapproved_batch(exported):
    with pytest.raises(ValueError): packet.pack(exported.batch_dir, 'b' * 64, exported.output)
    source = Path(exported.batch['exports'][0]['exportDirectory'])
    (source / 'database.sql').write_bytes(b'changed SQL')
    with pytest.raises(ValueError): packet.pack(exported.batch_dir, exported.batch_sha, exported.output)
    assert not exported.output.exists()


def test_real_packet_extraction_closes_all_original_bytes_again_on_ecs(exported, tmp_path, monkeypatch):
    result = packet.pack(exported.batch_dir, exported.batch_sha, exported.output)
    work = tmp_path / 'ecs-owned-work'; work.mkdir(mode=0o700)
    context = {'release': 'ci-1-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    monkeypatch.setattr(packet, 'admit', lambda _args: (work, context))
    args = SimpleNamespace(batch_receipt_sha256=exported.batch_sha, manifest_sha256=result['manifestSha256'],
        manifest_bytes=result['manifestBytes'], archive_sha256=result['archiveSha256'], archive_bytes=result['archiveBytes'])
    prepared = packet.prepare_transfer(args)
    snapshot = work / packet.SNAPSHOT
    assert prepared['status'] == 'TRANSFER_DIRECTORY_PREPARED' and prepared['sqlRecoveryStarted'] is False
    assert prepared['inputs'] == packet.sealed_input_bindings(args)
    assert prepared['transferReceiptSha256'] == packet.digest(work / 'project-mysql-transfer.json')
    with pytest.raises(ValueError, match='Fresh ECS'): packet.prepare_transfer(args)
    assert snapshot.stat().st_mode & 0o777 == 0o700
    for name in ('custody.json', 'originals.tar.gz'):
        assert (snapshot / name).stat().st_mode & 0o777 == 0o600 and (snapshot / name).stat().st_size == 0
        # Ordinary scp writes the already private existing destination.
        shutil.copyfile(exported.output / name, snapshot / name)
        assert (snapshot / name).stat().st_mode & 0o777 == 0o600
    recovered = packet.restore_bytes(args)
    assert recovered['status'] == 'BYTES_RESTORED_VERIFIED' and recovered['sqlDoubleRestoreVerified'] is False
    assert recovered['databasesOpened'] == 0 and recovered['retirementAllowed'] is False
    manifest = packet.read(snapshot / 'custody.json')
    for row in manifest['files']: assert packet.digest(work / packet.RESTORE / row['member']) == row['sha256']
    with pytest.raises(ValueError, match='fresh ECS'): packet.restore_bytes(args)


def test_windows_producer_raw_hashes_are_kept_while_only_git_line_endings_may_differ(exported):
    source = exported; producer = {key: body.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n') for key, body in source.producer.items()}
    batch = copy.deepcopy(source.batch); auth = copy.deepcopy(source.authorization); manifests = copy.deepcopy(source.manifests)
    digests = {key: hashlib.sha256(body).hexdigest() for key, body in producer.items()}
    batch['workerScriptSha256'] = auth['workerScriptSha256'] = digests['worker']; auth['batchScriptSha256'] = digests['batch']
    for name in ('sourceHelper', 'policy'): batch['dependencySha256'][name] = auth['dependencySha256'][name] = digests[name]
    for value in manifests.values():
        value['scriptSha256'] = digests['worker']; value['sourceHelperSha256'] = digests['sourceHelper']; value['policySha256'] = digests['policy']
    packet.validate_exports(batch, auth, manifests, source.batch_sha, producer)
    producer['worker'] += b'\nWrite-Output "changed behavior"\n'
    with pytest.raises(ValueError): packet.validate_exports(batch, auth, manifests, source.batch_sha, producer)


def test_cross_schema_fk_is_actually_checked_inside_the_closed_three_schema_pair():
    queries = []
    class Mysql:
        def single(self, query): queries.append(query); return {'n': 2}
    foreign = {'table': 'child', 'name': 'fk_parent', 'parentSchema': packet.SCHEMAS[1],
        'ordinal': 1, 'parent': 'parent', 'column': 'parent_id', 'parentColumn': 'id'}
    findings = restore.constraint_findings(Mysql(), packet.SCHEMAS[0], {'foreignKeys': [foreign], 'checks': []})
    assert findings == [{'kind': 'FOREIGN_KEY', 'table': 'child', 'constraint': 'fk_parent', 'violations': 2}]
    assert '`' + packet.SCHEMAS[1] + '`.`parent`' in queries[0]
    foreign['parentSchema'] = 'unrelated_project'
    assert restore.constraint_findings(Mysql(), packet.SCHEMAS[0], {'foreignKeys': [foreign], 'checks': []})[0]['unverified'] is True
    assert len(queries) == 1


def test_three_schema_cleanup_uses_separate_ownership_paths_and_reuses_original_sandbox_controls():
    assert restore.Recovery.cancel_name != restore.existing.Recovery.cancel_name
    assert restore.Recovery.lock_name != restore.existing.Recovery.lock_name
    assert restore.Recovery.not_created_name != restore.existing.Recovery.not_created_name
    for name in ('watch', 'inspect', 'stop', 'remove_derived', 'cleanup_locked'):
        assert getattr(restore.Recovery, name) is getattr(restore.existing.Recovery, name)


def test_second_server_is_refused_while_first_owned_server_is_still_running():
    controller = object.__new__(restore.Recovery); controller.state = {'servers': [{'containerId': 'a' * 64}]}
    controller.inspect = lambda _cid: {'State': {'Running': True}}
    with pytest.raises(ValueError, match='At most one'): controller.create_registered('b')


def test_fresh_cleanup_controller_loads_runtime_before_rechecking_completed_pair(tmp_path, monkeypatch):
    context = {'release': 'ci-1-' + 'a' * 12}; work = tmp_path / 'work'; work.mkdir(mode=0o700)
    utility = SimpleNamespace(safe=lambda path: Path(path), owner_path=lambda path: Path(path))
    monkeypatch.setattr(restore.packet, 'admit', lambda _args: (work, context))
    monkeypatch.setattr(restore.packet, 'common', lambda: utility)
    monkeypatch.setattr(restore.packet, 'verified_inputs', lambda _args, _work: {
        'schemas': {schema: {'rawSqlSha256': 'a' * 64} for schema in packet.SCHEMAS}})
    monkeypatch.setattr(restore.shutil, 'which', lambda _name: '/reviewed/docker')
    runtime = SimpleNamespace(keyed_row_inventory=lambda *_args: {'checked': True})
    monkeypatch.setattr(restore.existing, 'load_runtime', lambda: runtime)
    args = SimpleNamespace(tag=context['release'], source_sha256='b' * 64, manifest_sha256='c' * 64, batch_receipt_sha256='d' * 64)
    # This constructor is new; run() was never called on it.
    controller = restore.Recovery(args); controller.directory.mkdir(mode=0o700)
    public = controller.directory / 'public-recovery.json'; write(public, {'status': 'PROJECT_SQL_DOUBLE_RESTORED_VERIFIED'})
    binding_calls = []
    def evidence():
        binding_calls.append(controller.runtime.keyed_row_inventory(None)); return {'raw-original': 'e' * 64}
    controller.evidence_bindings = evidence
    state = {'owner': 'synthetic', 'status': 'SQL_DOUBLE_RESTORED_VERIFIED', 'cleanupEvidence': {'raw-original': 'e' * 64},
        'publicRecoverySha256': restore.packet.digest(public), 'containerIntents': [],
        'servers': [{'ordinal': name, 'containerId': name * 64, 'volume': name + '-volume'} for name in ('a', 'b')]}
    write(controller.owner_file, state)
    def load_owner(): controller.state = state
    controller.load = load_owner; controller.stop = lambda _node: None
    controller.docker_call = lambda *_args: b''
    removed = []; controller.remove_derived = lambda node: removed.append(node['containerId'])
    result = controller.cleanup_locked()
    assert result['status'] == 'STOPPED' and len(removed) == 2 and binding_calls == [{'checked': True}]
    assert result['projectSqlSha256'] == {schema: 'a' * 64 for schema in packet.SCHEMAS}


@pytest.mark.parametrize('mutation', ['same-server', 'missing-fixture', 'changed-row', 'changed-clock', 'changed-ddl', 'changed-routine', 'unmatched-count'])
def test_three_schema_pair_cannot_pass_narrow_or_changed_recovery_evidence(mutation):
    schemas = {name: {'snapshot': {'tables': {'records': {'rows': 1, 'rowsSha256': 'a' * 64,
        'columns': [{'name': 'created_at', 'type': 'datetime(6)'}], 'ddlSha256': 'b' * 64}}},
        'metadata': {'foreignKeys': [], 'checks': []}, 'extraObjects': {'routines': [], 'events': []},
        'observedCountsMatch': True} for name in packet.SCHEMAS}
    first = {'containerId': 'a' * 64, 'volume': 'first', 'serverUuid': 'first', 'schemas': schemas}
    second = copy.deepcopy(first); second.update(containerId='b' * 64, volume='second', serverUuid='second')
    restore.compare_recoveries(first, second)
    schema = second['schemas'][packet.SCHEMAS[0]]
    if mutation == 'same-server': second['serverUuid'] = first['serverUuid']
    if mutation == 'missing-fixture': second['schemas'].pop(packet.SCHEMAS[1])
    if mutation == 'changed-row': schema['snapshot']['tables']['records']['rowsSha256'] = 'c' * 64
    if mutation == 'changed-clock': schema['snapshot']['tables']['records']['columns'][0]['type'] = 'datetime'
    if mutation == 'changed-ddl': schema['snapshot']['tables']['records']['ddlSha256'] = 'c' * 64
    if mutation == 'changed-routine': schema['extraObjects']['routines'].append({'body': 'changed'})
    if mutation == 'unmatched-count': schema['observedCountsMatch'] = False
    with pytest.raises(ValueError): restore.compare_recoveries(first, second)


@pytest.mark.parametrize('unowned_partial_directory', [False, True])
def test_fresh_cleanup_before_sql_does_not_require_a_complete_transferred_packet(tmp_path, monkeypatch, unowned_partial_directory):
    work = tmp_path / 'work'; work.mkdir(mode=0o700)
    monkeypatch.setattr(restore.packet, 'admit', lambda _args: (work, {'release': 'ci-1-' + 'a' * 12}))
    monkeypatch.setattr(restore.packet, 'verified_inputs', lambda *_args: pytest.fail('Partial transfer cannot admit SQL or inspect incomplete source bytes'))
    monkeypatch.setattr(restore.shutil, 'which', lambda _name: str(Path(sys.executable).resolve()))
    monkeypatch.setattr(restore.existing, 'load_runtime', lambda: SimpleNamespace())
    if unowned_partial_directory: (work / 'project-mysql-recovery').mkdir(mode=0o700)
    args = SimpleNamespace(action='cleanup', manifest_sha256='a' * 64, batch_receipt_sha256='b' * 64)
    if unowned_partial_directory:
        with pytest.raises(ValueError, match='unowned partial'): restore.Recovery(args)
    else:
        result = restore.Recovery(args).cleanup_locked()
        assert result['status'] == 'NOT_CREATED' and result['containers'] == []
        assert result['projectSqlSha256'] == {} and result['derivedVolumesRemoved'] == 0


def embedded_reader(name):
    script = ROOT / 'script/jenkins/preserve-project-mysql.ps1'
    bodies = re.findall(r"(?ms)^[ \t]*\$" + name + r" = @'\r?\n(.*?)\r?\n'@$", script.read_text(encoding='utf8'))
    assert len(bodies) == 1
    return bodies[0], script


def test_project_controller_archive_reader_resolves_all_actual_source_dependencies(tmp_path, monkeypatch, capsys):
    body, script = embedded_reader('projectArchiveReader')
    tree = ast.parse(body)
    paths = []
    # Read literal declarations without inventing a second dependency list.
    declaration = next(node for node in tree.body if isinstance(node, ast.Assign)
                       and any(getattr(target, 'id', '') == 'paths' for target in node.targets))
    names = ast.literal_eval(declaration.value.generators[0].iter)
    paths += ['script/jenkins/' + name for name in names]
    for node in tree.body:
        if isinstance(node, ast.AugAssign):
            if isinstance(node.value, ast.ListComp):
                paths += ['script/schema/' + name for name in ast.literal_eval(node.value.generators[0].iter)]
            else: paths += ast.literal_eval(node.value)
    archive_path = tmp_path / 'fixed-source.tar.gz'; hashes = {}
    with tarfile.open(archive_path, 'x:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': 'a' * 40}) as archive:
        for path in paths:
            source = ROOT / path; hashes[path] = hashlib.sha256(source.read_bytes()).hexdigest()
            archive.add(source, arcname=path, recursive=False)
    with monkeypatch.context() as patch:
        patch.setattr(sys, 'argv', ['fixed-reader', str(archive_path), 'a' * 40]); exec(compile(body, str(script), 'exec'), {})
    assert json.loads(capsys.readouterr().out) == hashes and len(hashes) == 16
    assert 'script/schema/compact_ddl_policy.py' in hashes and 'script/schema/build_compact_schema.py' in hashes
    assert 'foreach($property in $hashes.PSObject.Properties)' in script.read_text(encoding='utf8')


@pytest.mark.parametrize('wrong_explicit_digest', [False, True])
def test_actual_controller_input_reader_pins_both_original_files_and_computes_byte_sizes(exported, monkeypatch, capsys, wrong_explicit_digest):
    result = packet.pack(exported.batch_dir, exported.batch_sha, exported.output)
    body, script = embedded_reader('projectInputReader')
    arguments = ['input-reader', str(exported.output), 'b' * 64 if wrong_explicit_digest else result['manifestSha256'], result['archiveSha256']]
    with monkeypatch.context() as patch:
        patch.setattr(sys, 'argv', arguments)
        if wrong_explicit_digest:
            with pytest.raises(AssertionError): exec(compile(body, str(script), 'exec'), {})
        else:
            exec(compile(body, str(script), 'exec'), {})
            actual = json.loads(capsys.readouterr().out)
            assert actual == {'batchReceiptSha256': exported.batch_sha, 'inputs': {
                'custody.json': {'sha256': result['manifestSha256'], 'bytes': result['manifestBytes']},
                'originals.tar.gz': {'sha256': result['archiveSha256'], 'bytes': result['archiveBytes']}}}


@pytest.mark.parametrize('operation', ['run', 'cleanup', 'observe'])
def test_controller_flags_are_accepted_by_the_real_receiver_cli(operation, monkeypatch, capsys):
    flags = {'root': '/home/ecs-user/doorhandle-ci', 'tag': 'ci-1-' + 'a' * 12, 'commit': 'a' * 40,
        'source-sha256': 'b' * 64, 'instance-id': 'i-synthetic', 'machine-id': 'c' * 32, 'batch-receipt-sha256': 'd' * 64,
        'manifest-sha256': 'e' * 64, 'manifest-bytes': '100', 'archive-sha256': 'f' * 64, 'archive-bytes': '200',
        'fixture-settings': '/home/ecs-user/private/fixtures.json'}
    received = []
    class Controller:
        def __init__(self, args): received.append(args)
        def run_supervised(self): return {'status': 'synthetic-run'}
        def cleanup(self): return {'status': 'synthetic-cleanup'}
        def observe(self): return {'status': 'synthetic-observe'}
    arguments = ['restore-project-mysql.py', operation]
    for name, value in flags.items(): arguments += ['--' + name, value]
    if operation == 'observe': arguments += ['--run-requested']
    monkeypatch.setattr(sys, 'argv', arguments); monkeypatch.setattr(restore, 'Recovery', Controller)
    monkeypatch.setattr(restore.signal, 'signal', lambda *_args: None)
    assert restore.main() == 0 and json.loads(capsys.readouterr().out)['status'] == 'synthetic-' + operation
    assert received[0].action == operation and received[0].manifest_bytes == 100 and received[0].archive_bytes == 200
    assert received[0].run_requested is (operation == 'observe')
    assert received[0].fixture_settings == flags['fixture-settings'] and received[0].batch_receipt_sha256 == flags['batch-receipt-sha256']


def test_standard_jenkins_entry_wires_explicit_inputs_and_fresh_post_cleanup_after_full_verification():
    pipeline = (ROOT / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf8')
    configure = (ROOT / 'script/jenkins/configure-local.groovy').read_text(encoding='utf8')
    controller = (ROOT / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    helper = (ROOT / 'script/jenkins/preserve-project-mysql.ps1').read_text(encoding='utf8')
    for name in ('PROJECT_MYSQL_SNAPSHOT', 'PROJECT_MYSQL_MANIFEST_SHA256', 'PROJECT_MYSQL_ARCHIVE_SHA256'):
        assert len(re.findall(r"string\(name: '" + name + "'", pipeline)) == 1
        assert len(re.findall(r"new StringParameterDefinition\('" + name + "'", configure)) == 1
        assert '$env:' + name in controller
    assert "projectSqlInputs.any { it } && !projectSqlInputs.every { it }" in pipeline
    assert "params.ACTION in ['verify', 'verify-runtime']" in pipeline
    assert 'def anySqlCustody = env.LOCAL_MYSQL_SNAPSHOT || env.LOCAL_MYSQL_ECS_SNAPSHOT || env.PROJECT_MYSQL_SNAPSHOT' in pipeline
    assert pipeline.index("stage('Recover approved three-schema MySQL packet on ECS')") > pipeline.index('-Action VerifyEcs')
    assert '-Action PreserveProjectMySql' in pipeline and '-Action CleanupProjectMySql' in pipeline
    post = pipeline.split("if (env.CI_PROJECT_MYSQL_ATTEMPTED == 'true')", 1)[1]
    assert post.index('-Action CleanupProjectMySql') < post.index('-Action CleanupFixtures') < post.index('-Action CleanupTools')
    assert 'Collect-ProjectSqlCleanup' in helper.split('finally {', 1)[1]
    assert "$env:CI_ECS_VERIFIED -ceq 'true'" in helper and "$accepted.scope -ceq 'mysql'" in helper
    assert "--fixture-settings '$FixtureSettings'" in helper and 'verificationReceiptSha256' in helper
    assert "Collect-ProjectSqlReceipt 'project-mysql-originals/restore-receipt.json'" in helper
    assert 'project-mysql-inputs.json' in helper and '$descriptor.inputs' in helper


def test_complete_top_level_stage_order_restores_sql_before_expanding_legacy_bytes():
    pipeline = (ROOT / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf8')
    # Match complete direct stages, not an action mention inside an earlier guard.
    matches = re.findall(r"(?ms)^        stage\('([^'\n]+)'\) \{\n(.*?)^        \}\n", pipeline)
    names = [name for name, _body in matches]
    assert names == [
        'Trusted checkout', 'Configuration gate', 'Build locally without tests', 'Package pinned source',
        'Collect existing verification evidence', 'Maintain proven old build outputs', 'Prepare temporary ECS tools', 'Preflight control scripts on ECS',
        'Prepare isolated ECS fixtures', 'Verify free embedding component on ECS', 'Verify on ECS over SSH',
        'Repair registered prior CI evidence permissions', 'Reclaim proven old build outputs',
        'Recover approved local MySQL export on ECS', 'Recover approved three-schema MySQL packet on ECS',
        'Preserve legacy source bytes on ECS', 'Preserve additional business artifacts on ECS',
        'Preserve historical cold stores on ECS', 'Preserve additional historical test stores on ECS',
        'Preserve remaining system data on ECS', 'Prepare preserved legacy data candidate on ECS',
        'Rehearse application', 'Accept candidate application on ECS', 'Deploy or rollback',
        'First compact migration and cutover',
    ]
    stages = dict(matches)
    assert len(stages) == len(names)
    verified = stages['Verify on ECS over SSH']
    assert verified.index('-Action VerifyEcs') < verified.index("env.CI_ECS_VERIFIED = 'true'")
    recoveries = [
        ('Recover approved local MySQL export on ECS', 'CI_LOCAL_MYSQL_ATTEMPTED', 'PreserveLocalMySql',
         "!(params.ACTION in ['rollback', 'reclaim-build-outputs', 'verify-controls']) && (env.LOCAL_MYSQL_SNAPSHOT || env.LOCAL_MYSQL_ECS_SNAPSHOT)"),
        ('Recover approved three-schema MySQL packet on ECS', 'CI_PROJECT_MYSQL_ATTEMPTED', 'PreserveProjectMySql',
         "params.ACTION in ['verify', 'verify-runtime'] && env.PROJECT_MYSQL_SNAPSHOT"),
    ]
    for name, attempted, operation, condition in recoveries:
        stage = stages[name]
        assert 'when { expression { ' + condition + ' } }' in stage
        assert stage.count("env." + attempted + " = 'true'") == 1
        assert re.findall(r"(?m)^ +pwsh '& ./script/jenkins/pipeline.ps1 -Action ([A-Za-z]+)'$", stage) == [operation]
        assert stage.index("env." + attempted) < stage.index('-Action ' + operation)
        assert "sshUserPrivateKey(credentialsId: 'doorhandle-ecs-ssh'" in stage
        assert "file(credentialsId: 'doorhandle-ecs-known-hosts'" in stage
    assert '-Action PreserveLegacy' in stages['Preserve legacy source bytes on ECS']
    candidate = stages['Prepare preserved legacy data candidate on ECS']
    assert "when { expression { params.ACTION in ['verify-runtime', 'compact-cutover'] } }" in candidate
    assert '-Action PrepareLegacyCandidate' in candidate and "env.CI_LEGACY_CANDIDATE_PREPARED = 'true'" in candidate


def test_three_schema_recovery_reuses_the_exact_base_supervision_and_read_only_observer():
    for name in ('run_supervised', 'observe', 'publish_terminal', 'supervision_paths'):
        assert getattr(restore.Recovery, name) is getattr(restore.existing.Recovery, name)
    source = (ROOT / 'script/jenkins/restore-project-mysql.py').read_text()
    assert "in ('cleanup', 'observe') and not self.owner_file.exists()" in source
    assert "if args.action == 'cleanup' and controller and controller.state" in source
    assert "signal.SIG_IGN if args.action == 'run'" in source


def test_three_schema_controller_observes_same_run_before_finally_and_post_cleanup():
    source = (ROOT / 'script/jenkins/preserve-project-mysql.ps1').read_text()
    observer = source.split('function Observe-ProjectSqlRecovery {', 1)[1].split('function Collect-ProjectSqlReceipt',1)[0]
    assert "'$recovery' observe $context $inputFlags" in observer and "'$recovery' run" not in observer
    assert 'Assert-ProjectSqlContext $value' in observer and '$value.executionId' in observer and '$value.terminal' in observer
    cleanup = source.split('function Collect-ProjectSqlCleanup {',1)[1].split("if($Mode -ceq 'Preserve')",1)[0]
    assert cleanup.index('$null=Observe-ProjectSqlRecovery') < cleanup.index("$recovery 'cleanup'")
    assert "$Operation -cne 'run' -or $LASTEXITCODE -ne 255" in source
    assert '$observed=Observe-ProjectSqlRecovery' in source and 'return $observed.result' in source
    assert 'artifacts/project-mysql-run-request.json' in source and '$requested=Test-ProjectSqlRunRequested' in observer
    assert '--run-requested' in observer and "$value.status -ceq 'PENDING'" in observer
    assert "(-not $requested -or $value.status -cne 'NOT_STARTED')" in observer
    invoke=source.split('function Invoke-ProjectSqlRemote',1)[1].split('function Observe-ProjectSqlRecovery',1)[0]
    assert invoke.index('Set-Content -LiteralPath $projectRunRequest') < invoke.index('$lines=@(Invoke-ProjectSql $ssh')
    request=source.split('function Test-ProjectSqlRunRequested {',1)[1].split('function Collect-ProjectSqlReceipt',1)[0]
    assert all('$request.'+name in request for name in ('release','commit','sourceSha256','verificationReceiptSha256','identity','batchReceiptSha256','manifestSha256','archiveSha256','runAttempted'))


@pytest.mark.parametrize('run_requested',[False, True])
def test_three_schema_observer_can_wait_for_a_supervised_creator_before_owner_publication(tmp_path, monkeypatch, run_requested):
    work = tmp_path / 'work'; work.mkdir(); (work / 'project-mysql-recovery').mkdir()
    monkeypatch.setattr(restore.packet, 'admit', lambda _: (work, {'release':'ci-1-'+'a'*12}))
    monkeypatch.setattr(restore.packet, 'verified_inputs', lambda *_: pytest.fail('observer must not start SQL admission'))
    monkeypatch.setattr(restore.shutil, 'which', lambda _: str(Path(sys.executable).resolve()))
    monkeypatch.setattr(restore.existing, 'load_runtime', lambda: SimpleNamespace())
    controller = restore.Recovery(SimpleNamespace(action='observe',run_requested=run_requested))
    assert controller.state is None and controller.manifest is None and controller.specifications == {}
    if run_requested:
        result=controller.observe()
        assert result['status']=='PENDING' and result['terminal'] is False
    else:
        with pytest.raises(ValueError, match='no supervisor proof'): controller.observe()


def test_three_schema_observation_failure_does_not_implicitly_cancel_original_sql(monkeypatch, capsys):
    calls = []
    class Controller:
        state = {'owned':True}
        def __init__(self, _): pass
        def observe(self): raise ValueError('unknown original operation')
        def cleanup(self): calls.append('wrong cancellation')
    argv=['restore-project-mysql.py','observe']
    values={'root':'/home/ecs-user/ci','tag':'ci-1-'+'a'*12,'commit':'a'*40,'source-sha256':'b'*64,
        'instance-id':'i-synthetic','machine-id':'c'*32,'batch-receipt-sha256':'d'*64,
        'manifest-sha256':'e'*64,'archive-sha256':'f'*64,'manifest-bytes':'100','archive-bytes':'200',
        'fixture-settings':'/home/ecs-user/private/fixtures.json'}
    for name,value in values.items():argv+=['--'+name,value]
    monkeypatch.setattr(sys,'argv',argv);monkeypatch.setattr(restore,'Recovery',Controller)
    monkeypatch.setattr(restore.signal,'signal',lambda *_:None)
    assert restore.main()==2 and calls==[]
    assert json.loads(capsys.readouterr().out)['status']=='FAILED_OR_UNKNOWN'
