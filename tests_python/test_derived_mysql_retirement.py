"""Closed, owned test-replica retirement. Executed by Jenkins on ECS only."""
import importlib.util
import ast
from contextlib import nullcontext
import io
import json
import os
import re
from pathlib import Path
import stat
import tarfile
from types import SimpleNamespace

import pytest

FILE = Path(__file__).resolve().parents[1] / 'script/jenkins/retire-derived-mysql-data.py'
spec = importlib.util.spec_from_file_location('derived_mysql_retirement', FILE)
retirement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retirement)
RELEASE = 'ci-221-8c30776fcd95'


def test_batch_has_only_the_five_explicitly_approved_replicas():
    assert {int(key.split('-')[1]) for key in retirement.TARGETS} == {221, 222, 235, 238, 247}
    assert set(retirement.BACKUP_MANIFESTS) == set(retirement.TARGETS)
    assert all(len(value[1]) == 40 for value in retirement.TARGETS.values())
    with pytest.raises(ValueError, match='CLOSED_BATCH_TARGET_REQUIRED'):
        retirement.data_path('ci-266-f6e062edc7b6')


@pytest.fixture
def root_identity(monkeypatch):
    original = Path
    monkeypatch.setattr(retirement.os, 'getuid', lambda: 0)
    monkeypatch.setattr(retirement, 'Path', lambda value: SimpleNamespace(read_text=lambda: retirement.MACHINE)
                        if str(value) == '/etc/machine-id' else original(value))


@pytest.mark.parametrize('release', ['ci-266-f6e062edc7b6', '../mysql', 'production'])
def test_privileged_worker_rejects_every_other_release(root_identity, release):
    with pytest.raises(ValueError, match='CLOSED_BATCH_TARGET_REQUIRED'):
        retirement.root_worker({'phase': 'remove', 'batch': retirement.BATCH, 'target': {'release': release}})


@pytest.mark.parametrize('payload', [
    {'phase': 'inventory', 'batch': retirement.BATCH, 'path': '/var/lib/mysql'},
    {'phase': 'delete-anything', 'batch': retirement.BATCH},
    {'phase': 'inventory', 'batch': 'all-databases'},
])
def test_privileged_worker_refuses_extra_arguments_or_another_operation(root_identity, payload):
    with pytest.raises(ValueError):
        retirement.root_worker(payload)


@pytest.fixture
def owned_tree(tmp_path, monkeypatch):
    parent = tmp_path / 'compact-fixtures'; parent.mkdir()
    path = parent / 'mysql-data'; path.mkdir()
    (path / 'table.ibd').write_bytes(b'synthetic test bytes')
    child = path / 'schema'; child.mkdir(); (child / 'row.ibd').write_bytes(b'more synthetic bytes')
    keeper = parent / 'source-backup.sql'; keeper.write_bytes(b'original SQL remains')
    rows = []
    def collect(directory, prefix=''):
        for item in sorted(directory.iterdir()):
            info = item.lstat(); relative = prefix + item.name
            rows.append({'path': relative, 'metadata': retirement.signature(info)})
            if item.is_dir() and not item.is_symlink(): collect(item, relative + '/')
    collect(path)
    item = {'release': RELEASE, 'path': str(path), 'rootMetadata': retirement.signature(path.stat()),
            'entries': rows, 'inventorySha256': retirement.digest(retirement.encoded(rows)),
            'allocatedBytes': 4096, 'files': 2}
    monkeypatch.setattr(retirement, 'data_path', lambda _release: path)
    monkeypatch.setattr(retirement, 'tree', lambda _release: item)
    return SimpleNamespace(path=path, parent=parent, keeper=keeper, item=item)


def test_descriptor_relative_removal_preserves_sql_and_parent(owned_tree):
    state = owned_tree
    retirement.remove_tree(state.item)
    assert not state.path.exists() and state.parent.is_dir()
    assert state.keeper.read_bytes() == b'original SQL remains'


def test_changed_file_is_not_removed_under_old_plan(owned_tree):
    state = owned_tree; (state.path / 'table.ibd').write_bytes(b'changed')
    with pytest.raises(ValueError, match='ENTRY_CHANGED_AFTER_PLAN'):
        retirement.remove_tree(state.item)
    assert (state.path / 'table.ibd').read_bytes() == b'changed'
    assert state.keeper.read_bytes() == b'original SQL remains'


def test_changed_root_inode_is_never_removed(owned_tree):
    state = owned_tree; old = state.parent / 'old'; state.path.rename(old); state.path.mkdir()
    with pytest.raises(ValueError, match='ROOT_CHANGED_AFTER_PLAN'):
        retirement.remove_tree(state.item)
    assert state.path.is_dir() and old.is_dir() and state.keeper.exists()


def test_symlink_entry_is_never_followed_or_unlinked_as_a_database_file(tmp_path, monkeypatch):
    path = tmp_path / 'mysql-data'; path.mkdir()
    outside = tmp_path / 'outside'; outside.write_bytes(b'keep')
    link = path / 'linked'; link.symlink_to(outside)
    item = {'release': RELEASE, 'rootMetadata': retirement.signature(path.stat()),
            'entries': [{'path': 'linked', 'metadata': retirement.signature(link.lstat())}]}
    monkeypatch.setattr(retirement, 'data_path', lambda _: path)
    monkeypatch.setattr(retirement, 'tree', lambda _: item)
    with pytest.raises(ValueError, match='LINKED_DELETION_REFUSED'):
        retirement.remove_tree(item)
    assert link.is_symlink() and outside.read_bytes() == b'keep'


def test_worker_cannot_replace_the_closed_target_path_inside_a_valid_release(owned_tree):
    changed = dict(owned_tree.item, path='/var/lib/mysql')
    with pytest.raises(ValueError, match='DERIVED_TREE_CHANGED_AFTER_PLAN'):
        retirement.remove_tree(changed)
    assert owned_tree.path.exists() and owned_tree.keeper.exists()


@pytest.fixture
def keeper_documents(monkeypatch):
    sql = b'complete original source SQL'
    manifest = {'snapshotSha256': retirement.SOURCE_SNAPSHOT,
                'tables': {str(index): {} for index in range(131)},
                'data': {'file': 'data.sql', 'bytes': len(sql), 'sha256': retirement.digest(sql)}}
    token = '123456789a'
    owner = {'release': RELEASE, 'commit': retirement.TARGETS[RELEASE][1], 'phase': 'OWNED_SERVER_STOPPED',
             'dataDirectory': str(retirement.data_path(RELEASE)), 'sourceTableCount': 131,
             'sourceSha256': 'a' * 64, 'sourceClone': 'doorhandle_migration_verify_' + token, 'token': token,
             'containerId': 'b' * 64, 'sourceContainerId': 'c' * 64,
             'sourceSnapshotSha256': retirement.SOURCE_SNAPSHOT, 'sourceCloneSnapshotSha256': retirement.SOURCE_SNAPSHOT,
             'rootPassword': 'never-output-this-secret'}
    cleanup = {'status': 'STOPPED', 'errors': [], 'containerId': owner['containerId'],
               'dataDirectoryRetained': owner['dataDirectory'], 'sourceDumpAndEvidenceRetained': True}
    def refresh():
        owner['sourceBackupSha256'] = retirement.digest(retirement.encoded(manifest))
        monkeypatch.setitem(retirement.BACKUP_MANIFESTS, RELEASE, owner['sourceBackupSha256'])
    refresh()
    def read(path, maximum=0):
        if path.name == 'compact-fixtures-owner.json': return retirement.encoded(owner)
        if path.name == 'cleanup-receipt.json': return retirement.encoded(cleanup)
        if path.name == 'manifest.json': return retirement.encoded(manifest)
        assert path.name == 'data.sql'; return sql
    monkeypatch.setattr(retirement, 'read', read)
    return SimpleNamespace(owner=owner, cleanup=cleanup, manifest=manifest, refresh=refresh)


def test_complete_original_sql_binding_omits_private_password(keeper_documents):
    result = retirement.keeper_binding(RELEASE)
    assert result['sourceSqlBytes'] == len(b'complete original source SQL')
    assert 'never-output-this-secret' not in json.dumps(result)


@pytest.mark.parametrize('damage', ['phase', 'source-container', 'clone', 'path', 'tables', 'sql-hash', 'snapshot', 'cleanup'])
def test_missing_or_drifted_original_keeper_never_authorizes_retirement(keeper_documents, damage):
    state = keeper_documents
    if damage == 'phase': state.owner['phase'] = 'PREPARED'
    elif damage == 'source-container': state.owner['sourceContainerId'] = state.owner['containerId']
    elif damage == 'clone': state.owner['sourceClone'] = 'business_database'
    elif damage == 'path': state.owner['dataDirectory'] = '/var/lib/mysql'
    elif damage == 'tables': state.manifest['tables'].pop('130'); state.refresh()
    elif damage == 'sql-hash': state.manifest['data']['sha256'] = '0' * 64; state.refresh()
    elif damage == 'snapshot': state.owner['sourceSnapshotSha256'] = '0' * 64
    else: state.cleanup['sourceDumpAndEvidenceRetained'] = False
    with pytest.raises(ValueError): retirement.keeper_binding(RELEASE)


def test_pipeline_requires_the_explicit_closed_batch_and_keeps_old_defaults():
    root = FILE.parents[2]; name = 'DerivedMysql221222235238247'
    for relative in ('Jenkinsfile.ecs-monolith', 'script/jenkins/pipeline.ps1', 'script/jenkins/configure-local.groovy'):
        text = (root / relative).read_text(encoding='utf-8-sig')
        assert name in text and 'FailedNative' in text
    wrapper = (root / 'script/jenkins/retire-derived-mysql-data.ps1').read_text(encoding='utf-8-sig')
    assert name in wrapper and 'reclaim-build-outputs' in wrapper
    assert 'Remove-Item' not in wrapper and 'plan-sha256' in wrapper
    pipeline = (root / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf-8-sig')
    post = pipeline.split('\n    post {\n', 1)[1]
    maintenance = re.search(r"^                if \(params.ACTION == 'reclaim-build-outputs'\) \{(.*?)"
                            r"^                \} else \{", post, re.MULTILINE | re.DOTALL)
    assert maintenance is not None, 'The dedicated maintenance post branch must exist.'
    archive = re.search(r"archiveArtifacts artifacts: '([^']+)'", maintenance[1])
    assert archive is not None, 'Maintenance must archive its own evidence.'
    assert 'artifacts/derived-mysql-*.json' in archive[1].split(',')


@pytest.fixture
def observation_attempt(tmp_path, monkeypatch):
    args = SimpleNamespace(phase='status', batch=retirement.BATCH, tag='ci-273-' + 'a' * 12,
                           commit='a' * 40, source_sha256='b' * 64, plan_sha256=None)
    identity = {'instanceId': retirement.INSTANCE, 'machineId': retirement.MACHINE, 'executionLocation': 'ECS'}
    monkeypatch.setattr(retirement, 'ROOT', tmp_path)
    monkeypatch.setattr(retirement, 'fixed_helpers', lambda _: {
        'verify-remote.py': SimpleNamespace(ecs_identity=lambda *_: identity), 'cleanup-ecs-builds.py': object()})
    monkeypatch.setattr(retirement, 'privileged', lambda _: pytest.fail('Observation cannot run a root operation'))
    output = tmp_path / 'inbox' / args.tag / 'derived-mysql-retirement'; output.mkdir(parents=True)
    binding = {'batch': args.batch, 'release': args.tag, 'commit': args.commit,
               'sourceSha256': args.source_sha256, 'identity': identity}
    return SimpleNamespace(args=args, output=output, binding=binding)


@pytest.mark.parametrize('state', ['COMPLETE', 'FAILED_OR_UNKNOWN', 'RUNNING', 'UNKNOWN'])
def test_observation_reports_only_the_existing_execution_without_replay(observation_attempt, state):
    attempt = observation_attempt
    if state in ('COMPLETE', 'FAILED_OR_UNKNOWN'):
        (attempt.output / 'receipt.json').write_bytes(retirement.encoded({**attempt.binding, 'status': state}))
    elif state == 'RUNNING':
        value = {**attempt.binding, 'pid': os.getpid(),
                 'startTicks': Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19],
                 'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
        (attempt.output / 'execution.json').write_bytes(retirement.encoded(value))
    result = retirement.run(attempt.args)
    assert result['status'] == state and result['terminal'] is (state in ('COMPLETE', 'FAILED_OR_UNKNOWN'))
    assert not (attempt.output / 'plan-private.json').exists()


def test_observation_rejects_another_source_terminal(observation_attempt):
    attempt = observation_attempt
    (attempt.output / 'receipt.json').write_bytes(retirement.encoded(
        {**attempt.binding, 'status': 'COMPLETE', 'sourceSha256': '0' * 64}))
    with pytest.raises(ValueError, match='TERMINAL_BINDING_DIFFERS'):
        retirement.run(attempt.args)


@pytest.fixture
def fixed_maintenance_source(tmp_path, monkeypatch):
    args = SimpleNamespace(tag='ci-273-' + 'a' * 12, commit='a' * 40)
    inbox = tmp_path / 'inbox' / args.tag; inbox.mkdir(parents=True)
    bodies = {'retire-derived-mysql-data.py': b'# approved closed worker\n',
              'cleanup-ecs-builds.py': b'SENTINEL = "cleanup"\n', 'verify-remote.py': b'SENTINEL = "verifier"\n'}
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz', pax_headers={'comment': args.commit}) as archive:
        for name, body in bodies.items():
            entry = tarfile.TarInfo('script/jenkins/' + name); entry.size = len(body)
            archive.addfile(entry, io.BytesIO(body)); (inbox / name).write_bytes(body)
    raw = data.getvalue(); (inbox / 'cleanup-source.tar.gz').write_bytes(raw)
    args.source_sha256 = retirement.digest(raw)
    monkeypatch.setattr(retirement, 'ROOT', tmp_path)
    monkeypatch.setattr(retirement, '__file__', str(inbox / 'retire-derived-mysql-data.py'))
    monkeypatch.setattr(retirement, 'LOADED_SOURCE', bodies['retire-derived-mysql-data.py'])
    return SimpleNamespace(args=args, inbox=inbox)


def test_fixed_helper_admission_uses_the_actual_maintenance_transport(fixed_maintenance_source):
    state = fixed_maintenance_source
    assert not (state.inbox / 'source.tar.gz').exists()
    helpers = retirement.fixed_helpers(state.args)
    assert helpers['cleanup-ecs-builds.py'].SENTINEL == 'cleanup'
    assert helpers['verify-remote.py'].SENTINEL == 'verifier'


@pytest.mark.parametrize('policy', ['FailedNative', 'RetiredCopies194', 'RetiredCopies203', 'PublicCaches221224235', 'DerivedMysql221222235238247'])
def test_real_maintenance_package_selection_supplies_the_closed_batch_consumer(fixed_maintenance_source, policy):
    state = fixed_maintenance_source
    text = (FILE.parent / 'pipeline.ps1').read_text(encoding='utf-8-sig')
    # Earlier elseif guards mention these actions but do not package source.
    package = re.search(r"^if \(\$Action -ceq 'PackageSourceOnly'\) \{(.*?)"
                        r"^if \(\$Action -ceq 'PackageControls'\)", text, re.MULTILINE | re.DOTALL)
    assert package is not None, 'The top-level maintenance packaging block must exist.'
    block = package[1]
    declaration = re.search(r'\$maintenancePaths\s*=\s*@\(([^)]*)\)', block)
    assert declaration is not None, 'Maintenance packaging must declare its helper paths.'
    paths = list(ast.literal_eval('(' + declaration[1] + ',)'))
    assert paths == ['script/jenkins/cleanup-ecs-builds.py', 'script/jenkins/verify-remote.py',
                     'script/jenkins/retire-failed-native-jar-duplicates.py', 'script/docker/compact-build-resources.py']
    guarded = re.search(r"if \(\$nativeRetentionPolicy -ceq 'DerivedMysql221222235238247'\) \{\s*\$maintenancePaths \+= '([^']+)'\s*\}", block)
    assert guarded and guarded[1] == 'script/jenkins/retire-derived-mysql-data.py'
    assert ") + $maintenancePaths" in block and "Invoke-Checked 'git.exe' $archiveArguments" in block
    if policy == 'DerivedMysql221222235238247': paths.append(guarded[1])
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz', pax_headers={'comment': state.args.commit}) as archive:
        for path in paths:
            local = state.inbox / path.rsplit('/', 1)[-1]
            body = local.read_bytes() if local.is_file() else b'# retained unrelated maintenance helper\n'
            entry = tarfile.TarInfo(path); entry.size = len(body); archive.addfile(entry, io.BytesIO(body))
    raw = data.getvalue(); (state.inbox / 'cleanup-source.tar.gz').write_bytes(raw)
    state.args.source_sha256 = retirement.digest(raw)
    if policy == 'DerivedMysql221222235238247':
        assert retirement.fixed_helpers(state.args)['cleanup-ecs-builds.py'].SENTINEL == 'cleanup'
    else:
        with pytest.raises(ValueError, match='FIXED_HELPER_CLOSURE_MISSING'):
            retirement.fixed_helpers(state.args)


@pytest.mark.parametrize('damage', ['commit', 'helper', 'loaded-source'])
def test_fixed_helper_rejects_changed_archive_context_or_execution_bytes(fixed_maintenance_source, monkeypatch, damage):
    state = fixed_maintenance_source
    if damage == 'commit': state.args.commit = 'b' * 40
    elif damage == 'helper': (state.inbox / 'cleanup-ecs-builds.py').write_bytes(b'# replaced')
    else: monkeypatch.setattr(retirement, 'LOADED_SOURCE', b'# another loaded revision')
    with pytest.raises(ValueError): retirement.fixed_helpers(state.args)


def test_privileged_payload_uses_only_the_admitted_loaded_bytes(monkeypatch):
    approved = b'# admitted fixed worker\n'; captured = []
    monkeypatch.setattr(retirement, 'LOADED_SOURCE', approved)
    monkeypatch.setattr(retirement, 'read', lambda *_: approved)
    def executed(command, **options):
        captured.append((command, options['input']))
        return SimpleNamespace(returncode=0, stdout=b'{"status":"synthetic"}')
    monkeypatch.setattr(retirement.subprocess, 'run', executed)
    result = retirement.privileged({'phase': 'inventory', 'batch': retirement.BATCH})
    assert result['status'] == 'synthetic' and len(captured) == 1
    assert captured[0][1].startswith(approved)
    assert captured[0][0][:6] == ['sudo', '-n', 'timeout', '--signal=TERM', '--kill-after=2s', '90s']


def test_changed_helper_never_becomes_a_new_privileged_payload(monkeypatch):
    monkeypatch.setattr(retirement, 'LOADED_SOURCE', b'# admitted')
    monkeypatch.setattr(retirement, 'read', lambda *_: b'# unapproved replacement')
    monkeypatch.setattr(retirement.subprocess, 'run', lambda *_args, **_kw: pytest.fail('No privilege escalation after drift'))
    with pytest.raises(ValueError, match='ADMITTED_PRIVILEGED_SOURCE_CHANGED'):
        retirement.privileged({'phase': 'inventory', 'batch': retirement.BATCH})


@pytest.fixture
def synthetic_proc(tmp_path, owned_tree, monkeypatch):
    proc = tmp_path / 'proc'; proc.mkdir()
    entry = proc / '98765'; entry.mkdir(); (entry / 'fd').mkdir()
    outside = tmp_path / 'outside-cwd'; outside.mkdir()
    (entry / 'cwd').symlink_to(outside); (entry / 'root').symlink_to(outside)
    fields = ['0'] * 20; fields[0] = 'S'; fields[19] = '12345'
    (entry / 'stat').write_text('98765 (synthetic) ' + ' '.join(fields))
    (entry / 'cmdline').write_bytes(b'synthetic-holder\0'); (entry / 'maps').write_bytes(b'')
    monkeypatch.setattr(retirement.os, 'getuid', lambda: 0)
    original = Path.stat
    uid = [999]
    def stat_with_uid(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == entry:
            values = list(info); values[4] = uid[0]
            return os.stat_result(values)
        return info
    monkeypatch.setattr(Path, 'stat', stat_with_uid)
    return SimpleNamespace(proc=proc, entry=entry, uid=uid, tree=owned_tree)


@pytest.mark.parametrize('uid', [0, 999, 1000])
def test_root_process_probe_checks_every_uid_instead_of_filtering_1000(synthetic_proc, uid):
    state = synthetic_proc; state.uid[0] = uid
    result = retirement.process_references([state.tree.item], state.proc)
    assert result['status'] == 'QUIESCENT' and result['processesChecked'] == 1 and result['uidsChecked'] == [uid]


@pytest.mark.parametrize('uid', [0, 999, 1000])
def test_root_or_mysql_file_holders_block_retirement(synthetic_proc, uid):
    state = synthetic_proc; state.uid[0] = uid
    (state.entry / 'fd/3').symlink_to(state.tree.path / 'table.ibd')
    with pytest.raises(ValueError, match='ACTIVE_PROCESS_FILE_REFERENCE'):
        retirement.process_references([state.tree.item], state.proc)
    assert state.tree.path.exists() and state.tree.keeper.exists()


@pytest.mark.parametrize('reference', ['cwd', 'argv', 'mapped-inode-alias'])
def test_process_directories_arguments_and_namespace_inode_aliases_are_fenced(synthetic_proc, reference):
    state = synthetic_proc
    if reference == 'cwd':
        (state.entry / 'cwd').unlink(); (state.entry / 'cwd').symlink_to(state.tree.path)
    elif reference == 'argv':
        (state.entry / 'cmdline').write_bytes(b'holder\0--datadir=' + os.fsencode(state.tree.path) + b'\0')
    else:
        info = (state.tree.path / 'table.ibd').stat()
        (state.entry / 'maps').write_text(f'1000-2000 r--p 00000000 {os.major(info.st_dev):x}:{os.minor(info.st_dev):x} {info.st_ino} /namespace-alias/file\n')
    with pytest.raises(ValueError): retirement.process_references([state.tree.item], state.proc)
    assert state.tree.path.exists() and state.tree.keeper.exists()


def test_real_plan_apply_flow_removes_only_the_owned_synthetic_replica(tmp_path, owned_tree, monkeypatch):
    state = owned_tree; args = SimpleNamespace(phase='plan', batch=retirement.BATCH,
        tag='ci-273-' + 'a' * 12, commit='a' * 40, source_sha256='b' * 64, plan_sha256=None)
    root = tmp_path / 'ci'; (root / 'inbox' / args.tag).mkdir(parents=True)
    identity = {'instanceId': retirement.INSTANCE, 'machineId': retirement.MACHINE, 'executionLocation': 'ECS'}
    calls = []; keeper = {'release': RELEASE, 'token': 'a' * 10, 'sourceSqlSha256': 'c' * 64}
    monkeypatch.setattr(retirement, 'ROOT', root)
    monkeypatch.setattr(retirement, 'TARGETS', {RELEASE: retirement.TARGETS[RELEASE]})
    monkeypatch.setattr(retirement, 'fixed_helpers', lambda _: {'verify-remote.py':
        SimpleNamespace(ecs_identity=lambda *_: identity), 'cleanup-ecs-builds.py':
        SimpleNamespace(docker_snapshot=lambda: [], quiescent=lambda *_args, **_kw: calls.append('quiescent'))})
    monkeypatch.setattr(retirement, 'keeper_binding', lambda _: dict(keeper))
    monkeypatch.setattr(retirement, 'lock', lambda _: nullcontext())
    monkeypatch.setattr(retirement, 'attempt_lock', lambda _: nullcontext())
    def privileged(payload):
        calls.append(payload['phase'])
        proof = {'status': 'QUIESCENT', 'scope': 'ALL_UIDS_CLOSED_DATA_DIRECTORIES', 'processesChecked': 1, 'uidsChecked': [999]}
        if payload['phase'] == 'inventory': return {'targets': [state.item], 'processProbe': proof}
        retirement.remove_tree(payload['target'])
        return {'release': RELEASE, 'status': 'REMOVED', 'allocatedBytesBefore': 4096, 'processProbe': proof}
    monkeypatch.setattr(retirement, 'privileged', privileged)
    planned = retirement.run(args); args.phase = 'apply'; args.plan_sha256 = planned['privatePlanSha256']
    result = retirement.run(args)
    assert result['status'] == 'COMPLETE' and result['removedDirectories'] == 1
    assert not state.path.exists() and state.keeper.read_bytes() == b'original SQL remains'
    receipt = json.loads(Path(result['file']).read_bytes())
    assert receipt['sourceSqlAndReportsRetained'] is True and len(receipt['removed']) == 1
    assert [value for value in calls if value != 'quiescent'] == ['inventory', 'inventory', 'remove']
