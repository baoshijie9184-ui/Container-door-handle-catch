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
import sys
import tarfile
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

FILE = Path(__file__).resolve().parents[1] / 'script/jenkins/retire-derived-mysql-data.py'
spec = importlib.util.spec_from_file_location('derived_mysql_retirement', FILE)
retirement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retirement)
RELEASE = 'ci-221-8c30776fcd95'
RECENT_RELEASE = 'ci-250-6444cbc36a65'
BATCHES = (retirement.BATCH, retirement.RECENT_BATCH, retirement.FOLLOWUP_BATCH)
POLICIES = ('DerivedMysql221222235238247', 'DerivedMysql250253256259264268', 'DerivedMysql281283')


def _task_flow_xml(context):
    root = ET.Element('flow-build')
    parameters = ET.SubElement(ET.SubElement(ET.SubElement(root, 'actions'), 'hudson.model.ParametersAction'), 'parameters')
    for name, value in [('ACTION', 'verify'), ('DOORHANDLE_CI_SCOPE', 'mysql'),
                        ('TRUSTED_COMMIT', context['commit']), ('PRODUCTION_RELEASE_ENABLED', 'false')]:
        parameter = ET.SubElement(parameters, 'hudson.model.StringParameterValue')
        ET.SubElement(parameter, 'name').text = name; ET.SubElement(parameter, 'value').text = value
    ET.SubElement(root, 'result').text = 'FAILURE'; ET.SubElement(root, 'completed').text = 'true'
    ET.SubElement(ET.SubElement(root, 'execution'), 'done').text = 'true'
    return b"<?xml version='1.1' encoding='UTF-8'?>\n" + ET.tostring(root, encoding='utf-8')


def test_batch_has_only_the_five_explicitly_approved_replicas():
    assert {int(key.split('-')[1]) for key in retirement.TARGETS} == {221, 222, 235, 238, 247}
    assert set(retirement.BACKUP_MANIFESTS) == set(retirement.TARGETS)
    assert all(len(value[1]) == 40 for value in retirement.TARGETS.values())
    for release in (*retirement.RECENT_TARGETS, *retirement.FOLLOWUP_TARGETS, 'ci-266-f6e062edc7b6'):
        with pytest.raises(ValueError, match='CLOSED_BATCH_TARGET_REQUIRED'):
            retirement.data_path(release)


@pytest.mark.parametrize('batch,numbers', [(BATCHES[0], {221, 222, 235, 238, 247}),
                                         (BATCHES[1], {250, 253, 256, 259, 264, 268}),
                                         (BATCHES[2], {281, 283})])
def test_closed_batches_never_union_targets_or_admit_the_oom_replica(batch, numbers):
    targets, manifests, metadata = retirement.batch_configuration(batch)
    assert {int(key.split('-')[1]) for key in targets} == numbers
    assert set(targets) == set(manifests) == set(metadata)
    for release in targets:
        assert retirement.data_path(release, batch).parts[-1] == 'mysql-data'
        assert len(targets[release][1]) == 40 and len(manifests[release]) == 64
    other = [release for other_batch in BATCHES if other_batch != batch
             for release in retirement.batch_configuration(other_batch)[0]]
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
    for other_batch in BATCHES:
        if other_batch == batch: continue
        other = next(iter(retirement.batch_configuration(other_batch)[0]))
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
    for other in BATCHES:
        if other == state.batch: continue
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
    for policy, batch, count in zip(POLICIES, BATCHES, (5, 6, 2)):
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
    args = SimpleNamespace(phase='status', batch=request.param, tag='ci-286-' + 'a' * 12,
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
    changes = [{'sourceSha256': '0' * 64}] if damage == 'source' else [
        {'batch': other} for other in BATCHES if other != attempt.args.batch]
    for changed in changes:
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
        tag='ci-286-' + 'a' * 12, commit='a' * 40, source_sha256='b' * 64, plan_sha256=None)
    root = tmp_path / 'ci'; (root / 'inbox' / args.tag).mkdir(parents=True)
    identity = {'instanceId': retirement.INSTANCE, 'machineId': retirement.MACHINE, 'executionLocation': 'ECS'}
    selected = retirement.batch_configuration(batch)[0]
    all_releases = [*retirement.TARGETS, *retirement.RECENT_TARGETS, *retirement.FOLLOWUP_TARGETS, 'ci-266-f6e062edc7b6']
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
    for other in BATCHES:
        if other == batch: continue
        wrong = json.loads(original); wrong['batch'] = other
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


@pytest.mark.parametrize('text,expected', [('287', ['287']), ('287,289', ['287', '289'])])
def test_task_build_selection_is_explicit_and_bounded(text, expected):
    assert retirement.task_numbers(text, 300) == expected


@pytest.mark.parametrize('text', ['', '266', '286', '300', '301', '0287', '287,287', '287, 289',
    '287,', '../287', '287;289', '٢٨٧', '287\n', '287,\n289',
    '287,288,289,290,291,292,293,294,295,296,297,298,299,300,301,302,303'])
def test_task_build_selection_rejects_protected_current_implicit_or_injected_values(text):
    with pytest.raises(ValueError):
        retirement.task_numbers(text, 300)


@pytest.fixture
def task_request_document(monkeypatch):
    rows = [{'release': 'ci-' + number + '-' + character * 12, 'commit': character * 40,
             'sourceSha256': 'b' * 64, 'controls': {role: {'bytes': 10, 'sha256': 'c' * 64} for role in
             ('buildXml', 'release', 'localBuild', 'fixtureCleanupPublic', 'preparation', 'transport')}}
            for number, character in [('287', 'a'), ('289', 'd')]]
    value = {'schemaVersion': 1, 'kind': 'doorhandle-authorized-failed-mysql-data-request',
        'current': {'release': 'ci-300-' + 'f' * 12, 'commit': 'f' * 40, 'sourceSha256': 'e' * 64},
        'identity': {'instanceId': retirement.INSTANCE, 'machineId': retirement.MACHINE, 'executionLocation': 'ECS'},
        'authorization': {'taskThreadId': retirement.TASK_ID, 'sourceSha256': 'a' * 64,
                          'endsWithTask': True, 'allowArbitraryPath': False},
        'builds': ['287', '289'], 'candidates': rows}
    binding = {'tag': value['current']['release'], 'commit': value['current']['commit'],
        'sourceSha256': value['current']['sourceSha256'], 'requestSha256': '', 'failedBuilds': '287,289'}
    def refresh():
        raw = retirement.encoded(value); binding['requestSha256'] = retirement.digest(raw)
        monkeypatch.setattr(retirement, 'read', lambda _path, _maximum=0: raw)
    refresh()
    return SimpleNamespace(value=value, binding=binding, refresh=refresh)


def test_task_request_preserves_exact_two_selectors_without_accepting_paths(task_request_document):
    state = task_request_document
    assert retirement.task_request(state.binding) == state.value
    assert 'path' not in retirement.encoded(state.value).decode()


@pytest.mark.parametrize('damage', ['kind', 'current', 'identity', 'task', 'authorization', 'ended',
    'builds', 'tag', 'commit', 'extra-path', 'missing-control', 'control-path', 'control-sha'])
def test_task_request_rejects_every_cross_scope_or_arbitrary_path(task_request_document, damage):
    state = task_request_document; value = state.value; row = value['candidates'][0]
    if damage == 'kind': value['kind'] = 'anything'
    elif damage == 'current': value['current']['commit'] = '0' * 40
    elif damage == 'identity': value['identity']['instanceId'] = 'another-instance'
    elif damage == 'task': value['authorization']['taskThreadId'] = 'another-task'
    elif damage == 'authorization': value['authorization']['allowArbitraryPath'] = True
    elif damage == 'ended': value['authorization']['endsWithTask'] = False
    elif damage == 'builds': value['builds'] = ['266', '289']
    elif damage == 'tag': row['release'] = 'ci-266-' + 'a' * 12
    elif damage == 'commit': row['commit'] = '0' * 40
    elif damage == 'extra-path': row['path'] = '/var/lib/mysql'
    elif damage == 'missing-control': row['controls'].pop('transport')
    elif damage == 'control-path': row['controls']['buildXml']['path'] = '/etc/passwd'
    else: row['controls']['buildXml']['sha256'] = 'not-a-checksum'
    state.refresh()
    with pytest.raises(ValueError): retirement.task_request(state.binding)


@pytest.mark.parametrize('damage', ['device', 'mode', 'uid', 'gid', 'missing', 'extra'])
def test_task_root_configuration_rejects_changed_directory_identity(task_request_document, damage):
    value = task_request_document.value
    roots = {row['release']: [64771, 1234, stat.S_IFDIR | 0o700, 999, 1000] for row in value['candidates']}
    keepers = [{'release': row['release'], 'backupManifestSha256': 'b' * 64} for row in value['candidates']]
    first = value['candidates'][0]['release']
    if damage == 'device': roots[first][0] = 42
    elif damage == 'mode': roots[first][2] = stat.S_IFLNK | 0o777
    elif damage == 'uid': roots[first][3] = 0
    elif damage == 'gid': roots[first][4] = 0
    elif damage == 'missing': roots.pop(first)
    else: roots['ci-266-' + 'c' * 12] = list(roots[first])
    with pytest.raises(ValueError): retirement.task_configuration(value, keepers, roots)


def test_task_root_configuration_computes_only_canonical_data_paths(task_request_document):
    value = task_request_document.value
    roots = {row['release']: [64771, 1234, stat.S_IFDIR | 0o700, 999, 1000] for row in value['candidates']}
    keepers = [{'release': row['release'], 'backupManifestSha256': 'b' * 64} for row in value['candidates']]
    batch = retirement.task_configuration(value, keepers, roots)
    assert isinstance(batch, retirement.TaskBatch)
    for row in value['candidates']:
        assert retirement.data_path(row['release'], batch) == retirement.ROOT / 'verification' / row['release'] / 'checkout/work/compact-fixtures/mysql-data'
    with pytest.raises(ValueError): retirement.data_path('ci-266-' + 'a' * 12, batch)
    with pytest.raises(ValueError): retirement.batch_configuration({'targets': batch.targets})


@pytest.mark.parametrize('payload', [
    {'phase': 'task-inventory', 'binding': {}, 'roots': {}, 'path': '/var/lib/mysql'},
    {'phase': 'task-remove', 'binding': {}, 'roots': {}, 'target': {}, 'command': 'rm'},
    {'phase': 'task-inventory', 'binding': {}},
])
def test_task_privileged_worker_refuses_extra_or_missing_arguments(root_identity, payload):
    with pytest.raises(ValueError, match='ARBITRARY_TASK_ROOT_ARGUMENT_REFUSED'):
        retirement.root_worker(payload)


@pytest.mark.parametrize('changed', [False, True])
def test_task_real_plan_apply_preserves_sql_reports_and_protected_266(tmp_path, monkeypatch, changed):
    args = SimpleNamespace(phase='plan', batch=retirement.TASK_BATCH, tag='ci-300-' + 'f' * 12,
        commit='f' * 40, source_sha256='e' * 64, request_sha256='d' * 64, failed_builds='287,289', plan_sha256=None)
    root = tmp_path / 'ci'; output = root / 'inbox' / args.tag / 'derived-failed-mysql-retirement'; output.mkdir(parents=True)
    tags = ['ci-287-' + 'a' * 12, 'ci-289-' + 'b' * 12]
    protected = root / 'verification/ci-266-cccccccccccc/checkout/work/compact-fixtures/mysql-data'
    protected.mkdir(parents=True); (protected / 'keep.ibd').write_bytes(b'recovery point')
    states = {}
    for tag in tags:
        parent = root / 'verification' / tag / 'checkout/work/compact-fixtures'; parent.mkdir(parents=True)
        path = parent / 'mysql-data'; path.mkdir(); file = path / 'table.ibd'; file.write_bytes(b'synthetic replica')
        (parent / 'data.sql').write_bytes(b'original SQL'); (parent / 'report.xml').write_bytes(b'original report')
        rows = [{'path': file.name, 'metadata': retirement.signature(file.stat())}]
        item = {'release': tag, 'path': str(path), 'rootMetadata': retirement.signature(path.stat()), 'entries': rows,
                'allocatedBytes': 4096, 'files': 1, 'inventorySha256': retirement.digest(retirement.encoded(rows))}
        states[tag] = SimpleNamespace(path=path, parent=parent, file=file, item=item)
    identity = {'instanceId': retirement.INSTANCE, 'machineId': retirement.MACHINE, 'executionLocation': 'ECS'}
    value = {'candidates': [{'release': tag, 'commit': tag[-12:] + '0' * 28} for tag in tags]}
    keepers = [{'release': tag, 'token': 'a' * 10, 'backupManifestSha256': 'c' * 64} for tag in tags]
    helpers = {'verify-remote.py': SimpleNamespace(ecs_identity=lambda *_: identity),
               'cleanup-ecs-builds.py': SimpleNamespace(docker_snapshot=lambda: [], quiescent=lambda *_a, **_k: None)}
    monkeypatch.setattr(retirement, 'ROOT', root); monkeypatch.setattr(retirement.os, 'getuid', lambda: 1000)
    monkeypatch.setattr(retirement, 'task_helpers', lambda _: helpers)
    monkeypatch.setattr(retirement, 'task_request', lambda _: value)
    monkeypatch.setattr(retirement, 'task_admitted', lambda *_a, **_k: keepers)
    monkeypatch.setattr(retirement, 'task_configuration', lambda *_: retirement.TaskBatch(
        {tag: (states[tag].item['rootMetadata'][1], 'a' * 40) for tag in tags}, {tag: 'b' * 64 for tag in tags}))
    monkeypatch.setattr(retirement, 'tree', lambda tag, _batch: states[tag].item)
    monkeypatch.setattr(retirement, 'lock', lambda _: nullcontext()); monkeypatch.setattr(retirement, 'attempt_lock', lambda _: nullcontext())
    calls = []
    def privileged(payload):
        calls.append(payload['phase'])
        with monkeypatch.context() as context:
            context.setattr(retirement.os, 'getuid', lambda: 0)
            context.setattr(retirement, 'Path', lambda path: SimpleNamespace(read_text=lambda: retirement.MACHINE)
                            if str(path) == '/etc/machine-id' else Path(path))
            context.setattr(retirement, 'process_references', lambda _: {'status': 'QUIESCENT', 'uidsChecked': [0, 999, 1000]})
            return retirement.root_worker(payload)
    monkeypatch.setattr(retirement, 'privileged', privileged)
    planned = retirement.run(args); args.phase = 'apply'; args.plan_sha256 = planned['planSha256']
    if changed:
        states[tags[0]].file.write_bytes(b'changed after planning')
        with pytest.raises(ValueError, match='ENTRY_CHANGED_AFTER_PLAN'): retirement.run(args)
        assert all(state.path.exists() for state in states.values())
    else:
        assert retirement.run(args)['status'] == 'COMPLETE'
        assert all(not state.path.exists() for state in states.values())
        for state in states.values():
            marker = json.loads((state.parent / 'derived-mysql-retired-task.json').read_text())
            assert marker['taskThreadId'] == retirement.TASK_ID and marker['status'] == 'REMOVED'
        assert calls == ['task-inventory', 'task-inventory', 'task-remove', 'task-remove']
    assert (protected / 'keep.ibd').read_bytes() == b'recovery point'
    for state in states.values():
        assert (state.parent / 'data.sql').read_bytes() == b'original SQL'
        assert (state.parent / 'report.xml').read_bytes() == b'original report'


def test_task_interface_keeps_closed_batches_and_requires_private_authorization():
    root = FILE.parents[2]
    pipeline = (root / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf-8-sig')
    config = (root / 'script/jenkins/configure-local.groovy').read_text(encoding='utf-8-sig')
    producer = (root / 'script/jenkins/pipeline.ps1').read_text(encoding='utf-8-sig')
    controller = (root / 'script/jenkins/retire-task-failed-mysql-data.ps1').read_text(encoding='utf-8-sig')
    native = (root / 'script/jenkins/retire-failed-native-jar-duplicates.ps1').read_text(encoding='utf-8-sig')
    assert "name: 'FAILED_MYSQL_DATA_BUILDS', defaultValue: ''" in pipeline
    assert 'DOORHANDLE_FAILED_MYSQL_DATA_TASK_ID' in pipeline and 'dataBuilds.toSet().size()' in pipeline
    assert 'authorization.completed != true && authorization.revoked != true' in config
    assert producer.index('-FailedNativeBuildNumber $failedNativeBuildNumber') < producer.index('-FailedBuildNumbers $failedMysqlDataBuilds')
    assert 'Read-TaskDataAuthorization' in controller and 'CollectDataControls' in controller
    assert 'if ($CollectDataControls)' in native and native.index('if ($CollectDataControls)', native.index('$local=')) < native.index('$spec=')
    assert 'Remove-Item' not in controller and 'rm -' not in controller


@pytest.fixture
def task_keeper_documents(monkeypatch):
    native_spec = importlib.util.spec_from_file_location('task_native_validator_test', FILE.with_name('retire-failed-native-jar-duplicates.py'))
    native = importlib.util.module_from_spec(native_spec); native_spec.loader.exec_module(native)
    root = Path('/home/ecs-user/doorhandle-ci-synthetic-retirement')
    monkeypatch.setattr(retirement, 'ROOT', root)
    tag = 'ci-287-' + 'a' * 12
    context = {'release': tag, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    identity = {'instanceId': retirement.INSTANCE, 'machineId': retirement.MACHINE, 'executionLocation': 'ECS'}
    work = root / 'verification' / tag / 'checkout/work/compact-fixtures'
    sql = b'complete synthetic source SQL'
    manifest = {'snapshotSha256': 'f' * 64, 'tables': {str(i): {} for i in range(131)},
                'data': {'file': 'data.sql', 'bytes': len(sql), 'sha256': retirement.digest(sql)}}
    local_build = {'schemaVersion': 1, 'release': tag, 'commit': context['commit'], 'status': 'PASS', 'exitCode': 0,
                   'testsExecuted': False, 'skipTests': True, 'applicationJarSha256': 'c' * 64, 'applicationJarBytes': 10}
    owner = {'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-owner', **context, 'identity': identity,
             'phase': 'OWNED_SERVER_STOPPED', 'token': '123456789a', 'work': str(work),
             'sourceContainerId': 'd' * 64, 'containerId': 'e' * 64, 'dataDirectory': str(work / 'mysql-data'),
             'sourceTableCount': 131, 'sourceClone': 'doorhandle_migration_verify_123456789a',
             'sourceSnapshotSha256': 'f' * 64, 'sourceCloneSnapshotSha256': 'f' * 64,
             'sourceBackupSha256': retirement.digest(retirement.encoded(manifest)), 'rootPassword': 'never-output-test-password'}
    cleanup = {'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-cleanup', **context, 'identity': identity,
               'status': 'STOPPED', 'errors': [], 'containerId': owner['containerId'],
               'sourceContainerUntouched': owner['sourceContainerId'], 'dataDirectoryRetained': owner['dataDirectory'],
               'sourceDumpAndEvidenceRetained': True}
    documents = {
        'release.json': {**context, 'applicationJarSha256': 'c' * 64, 'localBuildReceiptSha256': retirement.digest(retirement.encoded(local_build))},
        'local-build.json': local_build,
        'build-artifacts.json': {'schema': 1, 'kind': 'doorhandle-compact-fixture-artifacts', **context,
                                'applicationJarSha256': 'c' * 64, 'applicationJarBytes': 10},
        'compact-fixtures-owner.json': owner, 'cleanup-receipt.json': cleanup,
        'fixture-cleanup.json': {'release': tag, 'commit': context['commit'], 'status': 'STOPPED',
            'cleanupReceipt': str(work / 'cleanup-receipt.json'), 'cleanupReceiptSha256': retirement.digest(retirement.encoded(cleanup))},
        'ecs-tool-preparation.json': {'kind': 'doorhandle-ecs-tool-preparation', **context, 'identity': identity,
            'status': 'PREPARED', 'sourceFiles': {'script/jenkins/prepare-ecs-tools.py': native.DATABASE_VERIFY_TOOL_PREPARATION_SOURCE}},
        'ecs-tool-preparation-transport.json': {'schema': 1, 'kind': 'doorhandle-ecs-tool-preparation-transport', **context,
            'instanceId': retirement.INSTANCE, 'machineId': retirement.MACHINE, 'status': 'PREPARED',
            'prepareCandidateBuilder': False, 'finalExitCode': 0}, 'manifest.json': manifest,
    }
    xml = _task_flow_xml(context)
    role_names = {**native.UPLOADED_NAMES, 'preparation': 'ecs-tool-preparation.json', 'transport': 'ecs-tool-preparation-transport.json'}
    row = {**context, 'controls': {}}
    value = {'identity': identity, 'candidates': [row]}
    binding = {'tag': 'ci-300-' + 'f' * 12}
    state = SimpleNamespace(documents=documents, owner=owner, manifest=manifest, row=row, value=value, binding=binding,
                            sql=sql, xml=xml, native=native, reads=[])
    def refresh():
        raw = {name: retirement.encoded(document) for name, document in documents.items()}
        raw.update({'build.xml': state.xml, 'data.sql': state.sql})
        row['controls'] = {role: {'bytes': len(raw[name]), 'sha256': retirement.digest(raw[name])} for role, name in role_names.items()}
        def read(path, _maximum=0):
            state.reads.append(path.name)
            return raw[path.name]
        monkeypatch.setattr(retirement, 'read', read)
    refresh(); state.refresh = refresh
    monkeypatch.setattr(retirement, 'task_source_recipe', lambda *_: {'sourceSha256': 'b' * 64})
    monkeypatch.setattr(retirement, 'task_reports', lambda *_a, **_k: {'reportFiles': 1})
    monkeypatch.setattr(native, 'canonical_publication_refs', lambda *_: [])
    state.helpers = {'retire-failed-native-jar-duplicates.py': native, 'verify-remote.py': SimpleNamespace()}
    return state


@pytest.mark.parametrize('metadata_only', [False, True])
def test_task_keepers_authenticate_originals_without_exposing_password_or_reading_data_as_root(task_keeper_documents, metadata_only):
    state = task_keeper_documents
    result = retirement.task_admitted(state.binding, state.value, state.helpers, metadata_only=metadata_only)
    assert result[0]['sourceSqlSha256'] == state.manifest['data']['sha256']
    assert ('data.sql' in state.reads) is not metadata_only
    assert b'never-output-test-password' not in retirement.encoded(result)


@pytest.mark.parametrize('damage', ['runtime', 'success', 'production', 'owner-phase', 'source-container',
    'data-path', 'clone', 'tables', 'sql', 'snapshot', 'builder', 'transport-host'])
def test_task_keepers_reject_success_runtime_business_or_incomplete_backup(task_keeper_documents, damage):
    state = task_keeper_documents
    if damage == 'runtime': state.xml = state.xml.replace(b'<value>verify</value>', b'<value>verify-runtime</value>')
    elif damage == 'success': state.xml = state.xml.replace(b'<result>FAILURE</result>', b'<result>SUCCESS</result>')
    elif damage == 'production': state.xml = state.xml.replace(b'<name>PRODUCTION_RELEASE_ENABLED</name><value>false</value>', b'<name>PRODUCTION_RELEASE_ENABLED</name><value>true</value>')
    elif damage == 'owner-phase': state.owner['phase'] = 'PREPARED'
    elif damage == 'source-container': state.owner['containerId'] = state.owner['sourceContainerId']
    elif damage == 'data-path': state.owner['dataDirectory'] = '/var/lib/mysql'
    elif damage == 'clone': state.owner['sourceClone'] = 'business_database'
    elif damage == 'tables': state.manifest['tables'].pop('130')
    elif damage == 'sql': state.sql = b'changed source SQL'
    elif damage == 'snapshot': state.owner['sourceCloneSnapshotSha256'] = '0' * 64
    elif damage == 'builder': state.documents['ecs-tool-preparation-transport.json']['prepareCandidateBuilder'] = True
    else: state.documents['ecs-tool-preparation-transport.json']['instanceId'] = 'another-instance'
    state.refresh()
    with pytest.raises((ValueError, state.native.RetirementError)):
        retirement.task_admitted(state.binding, state.value, state.helpers)


@pytest.mark.parametrize('damage', [None, 'passing', 'bytes', 'missing', 'extra', 'receipt', 'link', 'claim'])
def test_task_report_preservation_validates_the_complete_original_archive(tmp_path, monkeypatch, damage):
    module_path = FILE.with_name('verify-remote.py')
    module_spec = importlib.util.spec_from_file_location('task_report_verifier_test', module_path)
    verifier = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(verifier)
    root = tmp_path / 'ci'; tag = 'ci-287-' + 'a' * 12
    inbox = root / 'inbox' / tag; inbox.mkdir(parents=True)
    attempt = root / 'verification' / tag; attempt.mkdir(parents=True)
    row = {'release': tag, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    body = b'original driver failure report'
    receipt = {'schema': 1, 'kind': 'doorhandle-ecs-ci', **row, 'attempt': 'c' * 32, 'scope': 'mysql',
        'identity': {'instanceId': retirement.INSTANCE, 'machineId': retirement.MACHINE, 'executionLocation': 'ECS'},
        'status': 'FAILED', 'verificationExitCode': 1, 'lifecycle': 'managed-outside-jenkins',
        'fixtureReadinessValidated': True,
        'reportFiles': [{'path': 'driver.log', 'bytes': len(body), 'sha256': retirement.digest(body)}]}
    if damage == 'passing': receipt.update(status='PASS', verificationExitCode=0)
    raw = retirement.encoded(receipt)
    (attempt / 'verification-receipt.json').write_bytes(raw)
    claim = {'schema': 1, 'kind': 'doorhandle-ci-claim', **row, 'attempt': 'c' * 32,
             'identity': receipt['identity'], 'scope': 'mysql'}
    if damage == 'claim': claim['attempt'] = 'd' * 32
    (attempt / '.verification-claimed').mkdir()
    (attempt / '.verification-claimed/claim.json').write_bytes(retirement.encoded(claim))
    with tarfile.open(inbox / 'verification-evidence.tar.gz', 'w:gz') as archive:
        def add(name, value, *, link=False):
            member = tarfile.TarInfo(name); member.size = len(value)
            if link: member.type = tarfile.SYMTYPE; member.linkname = '/etc/passwd'; member.size = 0
            archive.addfile(member, None if link else io.BytesIO(value))
        add('verification-receipt.json', raw + (b' ' if damage == 'receipt' else b''))
        if damage != 'missing': add('driver.log', b'changed driver log' if damage == 'bytes' else body, link=damage == 'link')
        if damage == 'extra': add('extra.log', b'unlisted')
    (inbox / 'verification-evidence.tar.gz').chmod(0o600)
    monkeypatch.setattr(retirement, 'ROOT', root)
    if damage and damage != 'passing':
        with pytest.raises((ValueError, verifier.VerificationError)):
            retirement.task_reports(row, verifier)
    else:
        assert retirement.task_reports(row, verifier)['reportFiles'] == 1


@pytest.mark.parametrize('damage', [None, 'archive-sha', 'own-bytes', 'commit', 'missing', 'link', 'oversize', 'duplicate'])
def test_task_helper_closure_is_bound_to_current_git_archive_without_path_import(monkeypatch, damage):
    tag = 'ci-300-' + 'f' * 12; own = FILE.read_bytes()
    bodies = {'retire-derived-mysql-data.py': own, 'retire-failed-native-jar-duplicates.py': b'VALUE=1\n',
              'cleanup-ecs-builds.py': b'VALUE=1\n', 'verify-remote.py': b'VALUE=1\n'}
    if damage == 'missing': bodies.pop('verify-remote.py')
    if damage == 'oversize': bodies['verify-remote.py'] = b'#' * (retirement.MIB + 1)
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode='w:gz', format=tarfile.PAX_FORMAT,
                      pax_headers={'comment': ('0' * 40 if damage == 'commit' else 'f' * 40)}) as archive:
        for name, body in bodies.items():
            member = tarfile.TarInfo('script/jenkins/' + name); member.size = len(body)
            if damage == 'link' and name == 'verify-remote.py': member.type = tarfile.SYMTYPE; member.linkname = '/etc/passwd'
            archive.addfile(member, None if member.issym() else io.BytesIO(body))
        if damage == 'duplicate':
            member = tarfile.TarInfo('script/jenkins/verify-remote.py'); member.size = 1
            archive.addfile(member, io.BytesIO(b'x'))
    raw = archive_bytes.getvalue()
    binding = {'tag': tag, 'commit': 'f' * 40, 'sourceSha256': retirement.digest(raw),
               'requestSha256': 'a' * 64, 'failedBuilds': '287,289'}
    if damage == 'archive-sha': binding['sourceSha256'] = '0' * 64
    monkeypatch.setattr(retirement, 'read', lambda path, _maximum=0: raw if path.name == 'cleanup-source.tar.gz'
                        else b'changed executor' if damage == 'own-bytes' else own)
    if damage:
        with pytest.raises(ValueError): retirement.task_helpers(binding)
    else:
        result = retirement.task_helpers(binding)
        assert set(result) == set(bodies) - {'retire-derived-mysql-data.py'}
        assert all(module.VALUE == 1 for module in result.values())


@pytest.mark.parametrize('partial', [None, 'claim', 'helper', 'archive'])
def test_task_report_absence_only_accepts_proven_not_started_state(tmp_path, monkeypatch, partial):
    root = tmp_path / 'ci'; tag = 'ci-287-' + 'a' * 12
    attempt = root / 'verification' / tag; attempt.mkdir(parents=True)
    inbox = root / 'inbox' / tag; inbox.mkdir(parents=True)
    if partial == 'claim': (attempt / '.verification-claimed').write_text('claimed')
    elif partial == 'helper': (inbox / 'verify-remote.py').write_text('# started upload')
    elif partial == 'archive': (inbox / 'verification-evidence.tar.gz').write_bytes(b'archive')
    monkeypatch.setattr(retirement, 'ROOT', root)
    if partial:
        with pytest.raises(ValueError, match='UNKNOWN_OR_PARTIAL_VERIFICATION_REPORT_STATE'):
            retirement.task_reports({'release': tag}, SimpleNamespace())
    else:
        assert retirement.task_reports({'release': tag}, SimpleNamespace()) == {
            'status': 'NOT_STARTED', 'originalJenkinsControlsRetained': True}


@pytest.mark.parametrize('data_only', [False, True])
def test_task_original_reader_does_not_replay_binary_retirement_or_scan_builds(tmp_path, monkeypatch, capsys, data_only):
    controller = FILE.with_name('retire-failed-native-jar-duplicates.ps1').read_text(encoding='utf-8-sig')
    reader = controller.split("$reader=@'\n", 1)[1].split("\n'@", 1)[0]
    jhome = tmp_path / 'jhome'; builds = jhome / 'jobs/doorhandle-java/builds'
    build = builds / '287'; originals = build / 'archive/artifacts'; originals.mkdir(parents=True)
    retained = tmp_path / 'retained'; retained.mkdir()
    context = {'release': 'ci-287-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    (build / 'build.xml').write_bytes(_task_flow_xml(context))
    (originals / 'release.json').write_bytes(retirement.encoded({**context, 'applicationJarSha256': 'c' * 64}))
    (originals / 'local-build.json').write_bytes(retirement.encoded({'kind': 'synthetic local build'}))
    (originals / 'fixture-cleanup.json').write_bytes(retirement.encoded({'status': 'STOPPED', 'release': context['release'], 'commit': context['commit']}))
    for name in ('ecs-tool-preparation.json', 'ecs-tool-preparation-transport.json'):
        value = {**context, 'status': 'PREPARED'}
        if name.endswith('-transport.json'): value.update(prepareCandidateBuilder=False, finalExitCode=0)
        (originals / name).write_bytes(retirement.encoded(value))
    source = tmp_path / 'current-source.tar.gz'
    with tarfile.open(source, 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': 'f' * 40}) as archive:
        for name in ('script/jenkins/retire-failed-native-jar-duplicates.py', 'script/jenkins/cleanup-ecs-builds.py',
                     'script/jenkins/verify-remote.py', 'script/docker/compact-build-resources.py'):
            member = tarfile.TarInfo(name); member.size = 1; archive.addfile(member, io.BytesIO(b'x'))
    previous = Path.iterdir
    def no_build_scan(path):
        if path == builds: raise AssertionError('An explicit selector must not scan other builds')
        return previous(path)
    monkeypatch.setattr(Path, 'iterdir', no_build_scan)
    arguments = ['reader', str(source), 'f' * 40, str(retained), str(jhome), '/home/ecs-user/doorhandle-ci',
                 'ci-300-' + 'f' * 12, 'FailedNative', 'retired-195-198-201', '287']
    if data_only: arguments.append('data-controls-only')
    monkeypatch.setattr(sys, 'argv', arguments)
    if data_only:
        exec(compile(reader, 'actual-data-control-reader', 'exec'), {})
        result = json.loads(capsys.readouterr().out)
        assert len(result['rows']) == 1 and result['skipped'] == [] and len(result['builderFiles']) == 2
        assert result['rows'][0]['release'] == context['release']
    else:
        with pytest.raises(ValueError, match='EXACT_SELECTED_FAILED_NATIVE_BUILD_REQUIRED'):
            exec(compile(reader, 'actual-binary-control-reader', 'exec'), {})
    assert not (originals / 'application.jar').exists()


@pytest.mark.parametrize('when', ['before-load', 'after-load'])
def test_task_real_cleanup_root_probe_keeps_authenticated_archive_bytes(tmp_path, monkeypatch, when):
    tag = 'ci-300-' + 'f' * 12; root = tmp_path / 'ci'; inbox = root / 'inbox' / tag; inbox.mkdir(parents=True)
    own = FILE.read_bytes(); cleanup = FILE.with_name('cleanup-ecs-builds.py').read_bytes()
    drifted = cleanup + b'\n# unreviewed on-disk replacement\n'
    disk = inbox / 'cleanup-ecs-builds.py'; disk.write_bytes(drifted if when == 'before-load' else cleanup); disk.chmod(0o600)
    bodies = {'retire-derived-mysql-data.py': own, 'cleanup-ecs-builds.py': cleanup,
              'retire-failed-native-jar-duplicates.py': b'VALUE=1\n', 'verify-remote.py': b'VALUE=1\n'}
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': 'f' * 40}) as archive:
        for name, body in bodies.items():
            member = tarfile.TarInfo('script/jenkins/' + name); member.size = len(body); archive.addfile(member, io.BytesIO(body))
    raw = stream.getvalue()
    monkeypatch.setattr(retirement, 'ROOT', root)
    monkeypatch.setattr(retirement, 'read', lambda path, _maximum=0: raw if path.name == 'cleanup-source.tar.gz' else own)
    helpers = retirement.task_helpers({'tag': tag, 'commit': 'f' * 40, 'sourceSha256': retirement.digest(raw),
                                     'requestSha256': 'a' * 64, 'failedBuilds': '287,289'})
    loaded = helpers['cleanup-ecs-builds.py']
    assert loaded.LOADED_SOURCE == cleanup
    if when == 'after-load': disk.write_bytes(drifted)
    monkeypatch.setattr(loaded.os, 'getuid', lambda: 1000); monkeypatch.setattr(loaded.os, 'geteuid', lambda: 1000)
    monkeypatch.setattr(loaded, 'checked_probe_checkout', lambda path: path)
    monkeypatch.setattr(loaded.subprocess, 'run', lambda *_a, **_k: pytest.fail('Changed source must never reach sudo'))
    with pytest.raises(ValueError, match='LOADED_PROCESS_PROBE_SOURCE_CHANGED'):
        loaded.privileged_process_probe(root / 'verification' / ('ci-287-' + 'a' * 12) / 'checkout', 123, Path('/proc'))
