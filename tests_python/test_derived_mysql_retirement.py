"""Closed, owned test-replica retirement. Executed by Jenkins on ECS only."""
import importlib.util
import ast
from contextlib import nullcontext
from fnmatch import fnmatchcase
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
RECENT_RELEASE = 'ci-250-6444cbc36a65'
BATCHES = (retirement.BATCH, retirement.RECENT_BATCH)
POLICIES = ('DerivedMysql221222235238247', 'DerivedMysql250253256259264268')


def test_batch_has_only_the_five_explicitly_approved_replicas():
    assert {int(key.split('-')[1]) for key in retirement.TARGETS} == {221, 222, 235, 238, 247}
    assert set(retirement.BACKUP_MANIFESTS) == set(retirement.TARGETS)
    assert all(len(value[1]) == 40 for value in retirement.TARGETS.values())
    with pytest.raises(ValueError, match='CLOSED_BATCH_TARGET_REQUIRED'):
        retirement.data_path('ci-266-f6e062edc7b6')


@pytest.mark.parametrize('batch,numbers', [(BATCHES[0], {221, 222, 235, 238, 247}),
                                         (BATCHES[1], {250, 253, 256, 259, 264, 268})])
def test_closed_batches_never_union_targets_or_admit_the_oom_replica(batch, numbers):
    targets, manifests, metadata = retirement.batch_configuration(batch)
    assert {int(key.split('-')[1]) for key in targets} == numbers
    assert set(targets) == set(manifests) == set(metadata)
    for release in targets:
        assert retirement.data_path(release, batch).parts[-1] == 'mysql-data'
        assert len(targets[release][1]) == 40 and len(manifests[release]) == 64
    other = retirement.RECENT_TARGETS if batch == retirement.BATCH else retirement.TARGETS
    for release in (*other, 'ci-266-f6e062edc7b6'):
        with pytest.raises(ValueError, match='CLOSED_BATCH_TARGET_REQUIRED'):
            retirement.data_path(release, batch)


@pytest.fixture
def root_identity(monkeypatch):
    original = Path
    monkeypatch.setattr(retirement.os, 'getuid', lambda: 0)
    monkeypatch.setattr(retirement, 'Path', lambda value: SimpleNamespace(read_text=lambda: retirement.MACHINE)
                        if str(value) == '/etc/machine-id' else original(value))


@pytest.mark.parametrize('batch', BATCHES)
@pytest.mark.parametrize('release', ['ci-266-f6e062edc7b6', '../mysql', 'production'])
def test_privileged_worker_rejects_every_other_release(root_identity, release, batch):
    with pytest.raises(ValueError, match='CLOSED_BATCH_TARGET_REQUIRED'):
        retirement.root_worker({'phase': 'remove', 'batch': batch, 'target': {'release': release}})


@pytest.mark.parametrize('batch', BATCHES)
def test_root_inventory_selects_the_exact_batch_and_rejects_cross_batch_removal(root_identity, monkeypatch, batch):
    selected = retirement.batch_configuration(batch)[0]
    calls = []
    def measured(release, actual_batch):
        calls.append((release, actual_batch)); return {'release': release}
    monkeypatch.setattr(retirement, 'tree', measured)
    monkeypatch.setattr(retirement, 'process_references', lambda rows: {'status': 'QUIESCENT'})
    result = retirement.root_worker({'phase': 'inventory', 'batch': batch})
    assert [row['release'] for row in result['targets']] == list(selected)
    assert calls == [(release, batch) for release in selected]
    other = RECENT_RELEASE if batch == retirement.BATCH else RELEASE
    with pytest.raises(ValueError, match='CLOSED_BATCH_TARGET_REQUIRED'):
        retirement.root_worker({'phase': 'remove', 'batch': batch, 'target': {'release': other}})


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
    monkeypatch.setattr(retirement, 'data_path', lambda _release, _batch=retirement.BATCH: path)
    monkeypatch.setattr(retirement, 'tree', lambda _release, _batch=retirement.BATCH: item)
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
    monkeypatch.setattr(retirement, 'data_path', lambda _, _batch=retirement.BATCH: path)
    monkeypatch.setattr(retirement, 'tree', lambda _, _batch=retirement.BATCH: item)
    with pytest.raises(ValueError, match='LINKED_DELETION_REFUSED'):
        retirement.remove_tree(item)
    assert link.is_symlink() and outside.read_bytes() == b'keep'


def test_worker_cannot_replace_the_closed_target_path_inside_a_valid_release(owned_tree):
    changed = dict(owned_tree.item, path='/var/lib/mysql')
    with pytest.raises(ValueError, match='DERIVED_TREE_CHANGED_AFTER_PLAN'):
        retirement.remove_tree(changed)
    assert owned_tree.path.exists() and owned_tree.keeper.exists()


@pytest.fixture(params=BATCHES)
def keeper_documents(monkeypatch, request):
    batch = request.param
    targets, manifests, _ = retirement.batch_configuration(batch)
    release = next(iter(targets))
    sql = b'complete original source SQL'
    manifest = {'snapshotSha256': retirement.SOURCE_SNAPSHOT,
                'tables': {str(index): {} for index in range(131)},
                'data': {'file': 'data.sql', 'bytes': len(sql), 'sha256': retirement.digest(sql)}}
    token = '123456789a'
    owner = {'release': release, 'commit': targets[release][1], 'phase': 'OWNED_SERVER_STOPPED',
             'dataDirectory': str(retirement.data_path(release, batch)), 'sourceTableCount': 131,
             'sourceSha256': 'a' * 64, 'sourceClone': 'doorhandle_migration_verify_' + token, 'token': token,
             'containerId': 'b' * 64, 'sourceContainerId': 'c' * 64,
             'sourceSnapshotSha256': retirement.SOURCE_SNAPSHOT, 'sourceCloneSnapshotSha256': retirement.SOURCE_SNAPSHOT,
             'rootPassword': 'never-output-this-secret'}
    cleanup = {'status': 'STOPPED', 'errors': [], 'containerId': owner['containerId'],
               'dataDirectoryRetained': owner['dataDirectory'], 'sourceDumpAndEvidenceRetained': True}
    def refresh():
        owner['sourceBackupSha256'] = retirement.digest(retirement.encoded(manifest))
        monkeypatch.setitem(manifests, release, owner['sourceBackupSha256'])
    refresh()
    def read(path, maximum=0):
        if path.name == 'compact-fixtures-owner.json': return retirement.encoded(owner)
        if path.name == 'cleanup-receipt.json': return retirement.encoded(cleanup)
        if path.name == 'manifest.json': return retirement.encoded(manifest)
        assert path.name == 'data.sql'; return sql
    monkeypatch.setattr(retirement, 'read', read)
    return SimpleNamespace(owner=owner, cleanup=cleanup, manifest=manifest, refresh=refresh, batch=batch, release=release)


def test_complete_original_sql_binding_omits_private_password(keeper_documents):
    state = keeper_documents
    result = retirement.keeper_binding(state.release, state.batch)
    assert result['sourceSqlBytes'] == len(b'complete original source SQL')
    assert 'never-output-this-secret' not in json.dumps(result)
    other = retirement.RECENT_BATCH if state.batch == retirement.BATCH else retirement.BATCH
    with pytest.raises(ValueError, match='CLOSED_BATCH_TARGET_REQUIRED'):
        retirement.keeper_binding(state.release, other)


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
    with pytest.raises(ValueError): retirement.keeper_binding(state.release, state.batch)


def test_pipeline_requires_the_explicit_closed_batch_and_keeps_old_defaults():
    root = FILE.parents[2]
    for relative in ('Jenkinsfile.ecs-monolith', 'script/jenkins/pipeline.ps1', 'script/jenkins/configure-local.groovy'):
        text = (root / relative).read_text(encoding='utf-8-sig')
        assert all(name in text for name in POLICIES) and 'FailedNative' in text
    wrapper = (root / 'script/jenkins/retire-derived-mysql-data.ps1').read_text(encoding='utf-8-sig')
    for policy, batch, count in zip(POLICIES, BATCHES, (5, 6)):
        assert f"{policy}=@{{batch='{batch}';count={count}}}" in wrapper
    assert 'reclaim-build-outputs' in wrapper
    assert 'Remove-Item' not in wrapper and 'plan-sha256' in wrapper
    assert '$value.batch -cne $batch' in wrapper and '$observed.batch -cne $batch' in wrapper
    assert '@($plan.targets).Count -ne $targetCount' in wrapper and '@($receipt.removed).Count -eq $targetCount' in wrapper
    assert 'batch=$batch;targetCount=$targetCount' in wrapper
    pipeline = (root / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf-8-sig')
    post = pipeline.split('\n    post {\n', 1)[1]
    maintenance = re.search(r"^                if \(params.ACTION == 'reclaim-build-outputs'\) \{(.*?)"
                            r"^                \} else \{", post, re.MULTILINE | re.DOTALL)
    assert maintenance is not None, 'The dedicated maintenance post branch must exist.'
    archive = re.search(r"archiveArtifacts artifacts: '([^']+)'", maintenance[1])
    assert archive is not None, 'Maintenance must archive its own evidence.'
    patterns = archive[1].split(',')
    assert 'artifacts/derived-mysql-*.json' in patterns
    producer = re.search(r"foreach\(\$name in @\(([^)]+)\)\)", wrapper)
    assert producer is not None
    outputs = ast.literal_eval('(' + producer[1] + ',)')
    assert outputs == ('derived-mysql-plan.json', 'derived-mysql-receipt.json', 'derived-mysql-controller.json')
    assert all(any(fnmatchcase('artifacts/' + output, pattern) for pattern in patterns) for output in outputs)


@pytest.fixture(params=BATCHES)
def observation_attempt(tmp_path, monkeypatch, request):
    args = SimpleNamespace(phase='status', batch=request.param, tag='ci-280-' + 'a' * 12,
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


@pytest.mark.parametrize('damage', ['source', 'batch'])
def test_observation_rejects_another_source_terminal(observation_attempt, damage):
    attempt = observation_attempt
    changed = {'sourceSha256': '0' * 64} if damage == 'source' else {
        'batch': retirement.RECENT_BATCH if attempt.args.batch == retirement.BATCH else retirement.BATCH}
    (attempt.output / 'receipt.json').write_bytes(retirement.encoded(
        {**attempt.binding, 'status': 'COMPLETE', **changed}))
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


@pytest.mark.parametrize('policy', ['FailedNative', 'RetiredCopies194', 'RetiredCopies203', 'PublicCaches221224235', *POLICIES])
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
    guarded = re.search(r"if \(\$nativeRetentionPolicy -cin @\(([^)]+)\)\) \{\s*\$maintenancePaths \+= '([^']+)'\s*\}", block)
    assert guarded and guarded[2] == 'script/jenkins/retire-derived-mysql-data.py'
    selected_policies = ast.literal_eval('(' + guarded[1] + ',)')
    assert selected_policies == POLICIES
    assert ") + $maintenancePaths" in block and "Invoke-Checked 'git.exe' $archiveArguments" in block
    call = re.search(r"^if \(\$Action -ceq 'ReclaimBuildOutputs'.*?\n\}", text, re.MULTILINE | re.DOTALL)
    assert call is not None and "Get-PinnedSourceFile 'script/jenkins/retire-derived-mysql-data.py'" in call[0]
    assert guarded[0].split(' {', 1)[0] in call[0] and '& ./script/jenkins/retire-derived-mysql-data.ps1' in call[0]
    if policy in selected_policies: paths.append(guarded[2])
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz', pax_headers={'comment': state.args.commit}) as archive:
        for path in paths:
            local = state.inbox / path.rsplit('/', 1)[-1]
            body = local.read_bytes() if local.is_file() else b'# retained unrelated maintenance helper\n'
            entry = tarfile.TarInfo(path); entry.size = len(body); archive.addfile(entry, io.BytesIO(body))
    raw = data.getvalue(); (state.inbox / 'cleanup-source.tar.gz').write_bytes(raw)
    state.args.source_sha256 = retirement.digest(raw)
    if policy in selected_policies:
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


@pytest.mark.parametrize('batch', BATCHES)
def test_privileged_payload_uses_only_the_admitted_loaded_bytes(monkeypatch, batch):
    approved = b'# admitted fixed worker\n'; captured = []
    monkeypatch.setattr(retirement, 'LOADED_SOURCE', approved)
    monkeypatch.setattr(retirement, 'read', lambda *_: approved)
    def executed(command, **options):
        captured.append((command, options['input']))
        return SimpleNamespace(returncode=0, stdout=b'{"status":"synthetic"}')
    monkeypatch.setattr(retirement.subprocess, 'run', executed)
    payload = {'phase': 'inventory', 'batch': batch}
    result = retirement.privileged(payload)
    assert result['status'] == 'synthetic' and len(captured) == 1
    assert captured[0][1].startswith(approved)
    assert retirement.encoded(payload).decode() in captured[0][1].decode()
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


@pytest.mark.parametrize('batch', BATCHES)
def test_real_plan_apply_flow_removes_only_the_owned_synthetic_replica(tmp_path, monkeypatch, batch):
    args = SimpleNamespace(phase='plan', batch=batch,
        tag='ci-280-' + 'a' * 12, commit='a' * 40, source_sha256='b' * 64, plan_sha256=None)
    root = tmp_path / 'ci'; (root / 'inbox' / args.tag).mkdir(parents=True)
    identity = {'instanceId': retirement.INSTANCE, 'machineId': retirement.MACHINE, 'executionLocation': 'ECS'}
    selected = retirement.batch_configuration(batch)[0]
    all_releases = [*retirement.TARGETS, *retirement.RECENT_TARGETS, 'ci-266-f6e062edc7b6']
    states = {}
    for release in all_releases:
        parent = root / 'verification' / release / 'checkout/work/compact-fixtures'; parent.mkdir(parents=True)
        path = parent / 'mysql-data'; path.mkdir(); (path / 'table.ibd').write_bytes(b'synthetic replica')
        sql = parent / 'source-backup.sql'; sql.write_bytes(b'original SQL remains')
        rows = [{'path': 'table.ibd', 'metadata': retirement.signature((path / 'table.ibd').stat())}]
        item = {'release': release, 'path': str(path), 'rootMetadata': retirement.signature(path.stat()),
                'entries': rows, 'inventorySha256': retirement.digest(retirement.encoded(rows)),
                'allocatedBytes': 4096, 'files': 1}
        states[release] = SimpleNamespace(path=path, sql=sql, item=item)
    calls = []
    monkeypatch.setattr(retirement, 'ROOT', root)
    monkeypatch.setattr(retirement, 'fixed_helpers', lambda _: {'verify-remote.py':
        SimpleNamespace(ecs_identity=lambda *_: identity), 'cleanup-ecs-builds.py':
        SimpleNamespace(docker_snapshot=lambda: [], quiescent=lambda *_args, **_kw: calls.append('quiescent'))})
    def keeper(release, selected_batch):
        assert selected_batch == batch and release in selected
        return {'release': release, 'token': 'a' * 10, 'sourceSqlSha256': 'c' * 64}
    def measured(release, selected_batch):
        assert selected_batch == batch and release in selected
        return states[release].item
    monkeypatch.setattr(retirement, 'keeper_binding', keeper)
    monkeypatch.setattr(retirement, 'tree', measured)
    monkeypatch.setattr(retirement, 'lock', lambda _: nullcontext())
    monkeypatch.setattr(retirement, 'attempt_lock', lambda _: nullcontext())
    def privileged(payload):
        assert payload['batch'] == batch
        calls.append(payload['phase'])
        proof = {'status': 'QUIESCENT', 'scope': 'ALL_UIDS_CLOSED_DATA_DIRECTORIES', 'processesChecked': 1, 'uidsChecked': [999]}
        with monkeypatch.context() as root_context:
            root_context.setattr(retirement.os, 'getuid', lambda: 0)
            root_context.setattr(retirement, 'Path', lambda value: SimpleNamespace(read_text=lambda: retirement.MACHINE)
                                 if str(value) == '/etc/machine-id' else Path(value))
            root_context.setattr(retirement, 'process_references', lambda _: proof)
            return retirement.root_worker(payload)
    monkeypatch.setattr(retirement, 'privileged', privileged)
    planned = retirement.run(args); args.phase = 'apply'; args.plan_sha256 = planned['privatePlanSha256']
    public_plan = json.loads(Path(planned['file']).read_bytes())
    assert public_plan['batch'] == batch and [row['release'] for row in public_plan['targets']] == list(selected)
    # A validly hashed plan from the other closed batch cannot authorize this apply.
    private = Path(planned['file']).with_name('plan-private.json'); original = private.read_bytes()
    wrong = json.loads(original); wrong['batch'] = retirement.RECENT_BATCH if batch == retirement.BATCH else retirement.BATCH
    private.write_bytes(retirement.encoded(wrong)); args.plan_sha256 = retirement.digest(private.read_bytes())
    with pytest.raises(ValueError, match='PLAN_OR_KEEPERS_CHANGED'): retirement.run(args)
    assert all(state.path.exists() for state in states.values())
    private.write_bytes(original); args.plan_sha256 = planned['privatePlanSha256']
    result = retirement.run(args)
    assert result['status'] == 'COMPLETE' and result['removedDirectories'] == len(selected)
    assert all(state.path.exists() == (release not in selected) for release, state in states.items())
    assert all(state.sql.read_bytes() == b'original SQL remains' for state in states.values())
    receipt = json.loads(Path(result['file']).read_bytes())
    assert receipt['batch'] == batch and receipt['sourceSqlAndReportsRetained'] is True
    assert [row['release'] for row in receipt['removed']] == list(selected)
    assert [value for value in calls if value != 'quiescent'] == ['inventory', 'inventory', *['remove'] * len(selected)]
