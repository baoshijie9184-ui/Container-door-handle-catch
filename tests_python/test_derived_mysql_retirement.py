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
import subprocess
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
ALL_POLICIES = (*POLICIES, 'DerivedMysqlHistorical15')


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
    maintenance = re.search(r"^                (?:\} else )?if \(params.ACTION == 'reclaim-build-outputs'\) \{(.*?)"
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


@pytest.mark.parametrize('policy', ['FailedNative', 'RetiredCopies194', 'RetiredCopies203', 'PublicCaches221224235', *ALL_POLICIES])
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
    assert selected_policies == ALL_POLICIES
    assert ") + $maintenancePaths" in block and "Invoke-Checked 'git.exe' $archiveArguments" in block
    call = re.search(r"^if \(\$Action -ceq 'ReclaimBuildOutputs'.*?\n\}", text, re.MULTILINE | re.DOTALL)
    assert call is not None and "Get-PinnedSourceFile 'script/jenkins/retire-derived-mysql-data.py'" in call[0]
    assert all(name in call[0] for name in ALL_POLICIES)
    assert '& ./script/jenkins/retire-derived-mysql-data.ps1' in call[0]
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


@pytest.mark.parametrize('batch', (*BATCHES, retirement.HISTORICAL_BATCH))
def test_real_plan_apply_flow_removes_only_the_owned_synthetic_replica(tmp_path, monkeypatch, batch):
    args = SimpleNamespace(phase='plan', batch=batch,
        tag='ci-400-' + 'a' * 12, commit='a' * 40, source_sha256='b' * 64, plan_sha256=None)
    root = tmp_path / 'ci'; (root / 'inbox' / args.tag).mkdir(parents=True)
    identity = {'instanceId': retirement.INSTANCE, 'machineId': retirement.MACHINE, 'executionLocation': 'ECS'}
    selected = retirement.batch_configuration(batch)[0]
    all_releases = [*retirement.TARGETS, *retirement.RECENT_TARGETS, *retirement.FOLLOWUP_TARGETS,
                    *retirement.HISTORICAL_ORIGINALS, 'ci-266-f6e062edc7b6']
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
    history_checks = []
    def historical(release, current, value):
        assert batch == retirement.HISTORICAL_BATCH and current == args.tag and release in selected
        history_checks.append(release)
        return {'buildXmlSha256': 'd' * 64}
    monkeypatch.setattr(retirement, 'historical_originals', historical)
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
    if batch == retirement.HISTORICAL_BATCH:
        assert set(history_checks) == set(selected) and len(history_checks) > len(selected) * 2
    else:
        assert history_checks == []


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


@pytest.mark.parametrize('changed,objects,finished', [
    (changed, objects, finished) for changed in (False, True)
    for objects in ('absent', 'stopped', 'remove-failed') for finished in (False, True)
] + [(False, 'builder-changed', True), (False, 'fixture-reappeared', True), (False, 'completed-binaries', True)])
def test_task_real_plan_apply_preserves_sql_reports_and_protected_266(tmp_path, monkeypatch, changed, objects, finished):
    args = SimpleNamespace(phase='plan', batch=retirement.FINISHED_BATCH if finished else retirement.TASK_BATCH, tag='ci-300-' + 'f' * 12,
        commit='f' * 40, source_sha256='e' * 64, request_sha256='d' * 64, failed_builds='287,289', plan_sha256=None)
    root = tmp_path / 'ci'; output = root / 'inbox' / args.tag / 'derived-failed-mysql-retirement'; output.mkdir(parents=True)
    tags = ['ci-287-' + 'a' * 12, 'ci-289-' + 'b' * 12]
    if objects == 'completed-binaries': tags = tags[:1]; args.failed_builds = '287'
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
    if objects == 'completed-binaries':
        keepers[0]['completedBinaryRetirement'] = {'completedAttempt': 'ci-299-' + 'e' * 12, 'alreadyRetiredJarBytes': 8192}
    remaining = set(tags) if objects not in ('absent', 'completed-binaries') else set()
    def strict_quiescent(*_args, **_kwargs):
        assert not remaining, 'Data removal must never ignore an existing fixture object'
    helpers = {'verify-remote.py': SimpleNamespace(ecs_identity=lambda *_: identity),
               'cleanup-ecs-builds.py': SimpleNamespace(docker_snapshot=lambda: [], quiescent=strict_quiescent)}
    monkeypatch.setattr(retirement, 'ROOT', root); monkeypatch.setattr(retirement.os, 'getuid', lambda: 1000)
    monkeypatch.setattr(retirement, 'task_helpers', lambda _: helpers)
    monkeypatch.setattr(retirement, 'task_request', lambda _: value)
    monkeypatch.setattr(retirement, 'task_admitted', lambda *_a, **_k: keepers)
    builder_generation = [0]
    monkeypatch.setattr(retirement, 'task_fixture_candidates', lambda *_: [
        {'historical': {'context': {'release': tag}}, 'fixture': {'containerId': str(i) * 64} if tag in remaining else None,
         **({'preservedBuilder': {'containerId': 'c' * 64, 'preservedVolume': 'owned-independent-state',
                                 'generation': builder_generation[0]}} if finished else {})}
        for i, tag in enumerate(tags, 1)])
    monkeypatch.setattr(retirement, 'task_fixture_quiescence', lambda *_: None)
    monkeypatch.setattr(retirement, 'task_configuration', lambda *_: retirement.TaskBatch(
        {tag: (states[tag].item['rootMetadata'][1], 'a' * 40) for tag in tags}, {tag: 'b' * 64 for tag in tags}))
    def live_inventory(tag, _batch):
        # Substitute the fixture's UID/device admission, not the live inventory:
        # task-inventory must observe changes before any container is retired.
        state = states[tag]; before = state.path.stat()
        rows = [{'path': path.name, 'metadata': retirement.signature(path.stat())}
                for path in sorted(state.path.iterdir())]
        return {'release': tag, 'path': str(state.path), 'rootMetadata': retirement.signature(before),
                'entries': rows, 'files': len(rows),
                'allocatedBytes': before.st_blocks * 512 + sum(row['metadata'][9] * 512 for row in rows),
                'inventorySha256': retirement.digest(retirement.encoded(rows))}
    monkeypatch.setattr(retirement, 'tree', live_inventory)
    monkeypatch.setattr(retirement, 'lock', lambda _: nullcontext()); monkeypatch.setattr(retirement, 'attempt_lock', lambda _: nullcontext())
    calls = []
    if finished:
        jar_targets = [] if objects == 'completed-binaries' else [{'path': tag + '/' + name} for tag in tags for name in ('copy.jar', 'canonical.jar')]
        monkeypatch.setattr(retirement, 'finished_jar_targets', lambda *_: jar_targets)
        def remove_jars(_output, targets, _helpers, quiescent, receipt):
            assert not remaining and all(state.path.exists() for state in states.values())
            quiescent(); calls.append('remove-jars'); receipt['jarRetirements'].extend(targets)
        monkeypatch.setattr(retirement, 'finished_remove_jars', remove_jars)
    def remove_fixture(candidate, _helpers):
        tag = candidate['historical']['context']['release']
        assert all(state.path.exists() for state in states.values())
        if objects == 'remove-failed': raise ValueError('TASK_FIXTURE_CHANGED_AFTER_PLAN')
        if tag in remaining:
            calls.append('remove-stopped-object'); remaining.remove(tag)
        if not remaining:
            if objects == 'builder-changed': builder_generation[0] += 1
            elif objects == 'fixture-reappeared': remaining.add(tags[0])
        return {'release': tag, 'status': 'REMOVED' if candidate['fixture'] else 'ALREADY_ABSENT'}
    monkeypatch.setattr(retirement, 'task_remove_fixture', remove_fixture)
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
        with pytest.raises(ValueError, match='TASK_TARGETS_CHANGED_AFTER_PLAN'): retirement.run(args)
        assert all(state.path.exists() for state in states.values())
        assert remaining == (set(tags) if objects != 'absent' else set())
        assert calls == ['task-inventory', 'task-inventory']
        receipt = json.loads((output / 'receipt.json').read_bytes())
        assert receipt['removed'] == receipt['fixtureRetirements'] == []
        assert receipt['reasonCode'] == 'TASK_TARGETS_CHANGED_AFTER_PLAN'
    elif objects == 'remove-failed':
        with pytest.raises(ValueError, match='TASK_FIXTURE_CHANGED_AFTER_PLAN'): retirement.run(args)
        receipt = json.loads((output / 'receipt.json').read_bytes())
        assert receipt['status'] == 'FAILED_OR_UNKNOWN' and receipt['removed'] == []
        assert receipt['reasonCode'] == 'TASK_FIXTURE_CHANGED_AFTER_PLAN'
        assert all(state.path.exists() for state in states.values()) and remaining == set(tags)
    elif objects in ('builder-changed', 'fixture-reappeared'):
        code = ('FINISHED_PRESERVED_BUILDER_CHANGED_AFTER_PLAN' if objects == 'builder-changed'
                else 'FINISHED_FIXTURE_REAPPEARED_AFTER_REMOVAL')
        with pytest.raises(ValueError, match=code): retirement.run(args)
        receipt = json.loads((output / 'receipt.json').read_bytes())
        assert receipt['reasonCode'] == code and receipt['removed'] == receipt['jarRetirements'] == []
        assert len(receipt['fixtureRetirements']) == 2
        assert all(state.path.exists() for state in states.values())
        assert calls == ['task-inventory', 'task-inventory', 'remove-stopped-object', 'remove-stopped-object']
    else:
        assert retirement.run(args)['status'] == 'COMPLETE'
        assert all(not state.path.exists() for state in states.values())
        for state in states.values():
            marker = json.loads((state.parent / 'derived-mysql-retired-task.json').read_text())
            assert marker['taskThreadId'] == (retirement.FINISHED_TASK_ID if finished else retirement.TASK_ID) and marker['status'] == 'REMOVED'
        assert calls == ['task-inventory', 'task-inventory',
                         *(['remove-stopped-object'] * 2 if objects == 'stopped' else []),
                         *(['remove-jars'] if finished else []), *(['task-remove'] * len(tags))]
        final = json.loads((output / 'receipt.json').read_bytes())
        assert len(final['fixtureRetirements']) == len(tags)
        if objects == 'completed-binaries':
            assert final['jarRetirements'] == []
            assert final['completedBinaryRetirements'] == [keepers[0]['completedBinaryRetirement']]
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
    legacy = producer[producer.index("    & ./script/jenkins/reclaim-build-outputs.ps1 -Mode Maintenance -SshOptions", producer.index("if ($Action -ceq 'ReclaimBuildOutputs'")):]
    assert legacy.index('-FailedNativeBuildNumber $failedNativeBuildNumber') < legacy.index('-FailedBuildNumbers $failedMysqlDataBuilds')
    assert 'Read-TaskDataAuthorization' in controller and 'CollectDataControls' in controller
    assert 'if ($CollectDataControls)' in native and native.index('if ($CollectDataControls)', native.index('$local=')) < native.index('$spec=')
    assert 'Remove-Item' not in controller and 'rm -' not in controller


@pytest.mark.parametrize('recipe_kind', ['legacy', 'current', 'legacy-new-helper', 'current-old-helper',
                                       'unreviewed-publication', 'unreviewed-helper'])
def test_task_source_recipe_binds_all_three_reviewed_producers(monkeypatch, recipe_kind):
    native_spec = importlib.util.spec_from_file_location('task_recipe_native_test', FILE.with_name('retire-failed-native-jar-duplicates.py'))
    native = importlib.util.module_from_spec(native_spec); native_spec.loader.exec_module(native)
    names = ('Jenkinsfile.ecs-monolith', 'script/jenkins/pipeline.ps1', 'script/jenkins/prepare-ecs-tools.py')
    old = (b'old reviewed Jenkinsfile', b'old reviewed pipeline', b'old reviewed preparer')
    new = (b'new reviewed Jenkinsfile', b'new reviewed pipeline', b'new reviewed preparer')
    old_shas = tuple(retirement.digest(body) for body in old)
    new_shas = tuple(retirement.digest(body) for body in new)
    monkeypatch.setattr(native, 'DATABASE_VERIFY_PUBLICATION_RECIPES', frozenset({old_shas[:2]}))
    monkeypatch.setattr(native, 'DATABASE_VERIFY_TOOL_PREPARATION_SOURCE', old_shas[2])
    monkeypatch.setattr(native, 'DATABASE_VERIFY_REVIEWED_RECIPES', frozenset({new_shas}))
    selected = {'legacy': old, 'current': new, 'legacy-new-helper': (*old[:2], new[2]),
                'current-old-helper': (*new[:2], old[2]),
                'unreviewed-publication': (new[0], b'unknown pipeline', new[2]),
                'unreviewed-helper': (*new[:2], b'unknown preparer')}[recipe_kind]
    row = {'release': 'ci-322-' + 'a' * 12, 'commit': 'a' * 40}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz', format=tarfile.PAX_FORMAT,
                      pax_headers={'comment': row['commit']}) as archive:
        for name, body in zip(names, selected):
            member = tarfile.TarInfo(name); member.size = len(body)
            archive.addfile(member, io.BytesIO(body))
    raw = buffer.getvalue(); row['sourceSha256'] = retirement.digest(raw)
    def read(path, maximum):
        assert path == retirement.ROOT / 'inbox' / row['release'] / 'source.tar.gz'
        assert maximum == 128 * retirement.MIB
        return raw
    monkeypatch.setattr(retirement, 'read', read)
    if recipe_kind not in ('legacy', 'current'):
        with pytest.raises(ValueError, match='REVIEWED_VERIFY_ONLY_TASK_SOURCE_REQUIRED'):
            retirement.task_source_recipe(native, row)
    else:
        proof = retirement.task_source_recipe(native, row)
        assert proof == {'sourceSha256': row['sourceSha256'],
                         'publicationRecipe': [retirement.digest(body) for body in selected[:2]],
                         'toolPreparationHelperSha256': retirement.digest(selected[2])}


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
                            sql=sql, xml=xml, native=native, reads=[],
                            recipe={'sourceSha256': 'b' * 64,
                                    'toolPreparationHelperSha256': native.DATABASE_VERIFY_TOOL_PREPARATION_SOURCE})
    def refresh():
        raw = {name: retirement.encoded(document) for name, document in documents.items()}
        raw.update({'build.xml': state.xml, 'data.sql': state.sql})
        row['controls'] = {role: {'bytes': len(raw[name]), 'sha256': retirement.digest(raw[name])} for role, name in role_names.items()}
        def read(path, _maximum=0):
            state.reads.append(path.name)
            return raw[path.name]
        monkeypatch.setattr(retirement, 'read', read)
    refresh(); state.refresh = refresh
    monkeypatch.setattr(retirement, 'task_source_recipe', lambda *_: state.recipe)
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


@pytest.mark.parametrize('receipt_matches_source', [False, True])
def test_task_keepers_bind_preparation_receipt_to_authenticated_recipe(task_keeper_documents, receipt_matches_source):
    state = task_keeper_documents
    reviewed = next(iter(state.native.DATABASE_VERIFY_REVIEWED_RECIPES))
    state.recipe.update(publicationRecipe=list(reviewed[:2]), toolPreparationHelperSha256=reviewed[2])
    if receipt_matches_source:
        state.documents['ecs-tool-preparation.json']['sourceFiles']['script/jenkins/prepare-ecs-tools.py'] = reviewed[2]
    state.refresh()
    if not receipt_matches_source:
        with pytest.raises(ValueError, match='VERIFY_ONLY_TASK_WITHOUT_CANDIDATE_BUILDER_REQUIRED'):
            retirement.task_admitted(state.binding, state.value, state.helpers)
    else:
        result = retirement.task_admitted(state.binding, state.value, state.helpers)
        assert result[0]['sourceRecipe'] == state.recipe
        assert result[0]['sourceSqlSha256'] == state.manifest['data']['sha256']
        assert result[0]['reports'] == {'reportFiles': 1}


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
              'cleanup-ecs-builds.py': b'VALUE=1\n', 'verify-remote.py': b'VALUE=1\n',
              'compact-build-resources.py': b'VALUE=1\n'}
    if damage == 'missing': bodies.pop('verify-remote.py')
    if damage == 'oversize': bodies['verify-remote.py'] = b'#' * (retirement.MIB + 1)
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode='w:gz', format=tarfile.PAX_FORMAT,
                      pax_headers={'comment': ('0' * 40 if damage == 'commit' else 'f' * 40)}) as archive:
        for name, body in bodies.items():
            prefix = 'script/docker/' if name == 'compact-build-resources.py' else 'script/jenkins/'
            member = tarfile.TarInfo(prefix + name); member.size = len(body)
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


def test_task_original_reader_uses_stdin_in_both_modes_without_changing_positional_inputs():
    controller = FILE.with_name('retire-failed-native-jar-duplicates.ps1').read_text(encoding='utf-8-sig')
    calls = re.findall(r'\$local=\(Invoke-NativeJar \$python @\(([^)]*)\)([^|\n]*)\|', controller)
    expected = ["'-I'", "'-B'", "'-'", '$archive', '$Commit', '$RetainedControlRoot', '$jenkinsHome',
                '$RemoteRoot', '$Tag', '$CanonicalBatch', '$RetiredCopyBatch', '$FailedNativeBuildNumber']
    assert len(calls) == 2
    assert [arguments.split(',') for arguments, _ in calls] == [expected + ["'data-controls-only'"], expected]
    assert all(transport.strip() == '-InputText $reader' for _, transport in calls)
    assert not re.search(r"Invoke-NativeJar \$python[^\n]*'-c',\$reader", controller)
    invoke = controller.split('function Invoke-NativeJar(', 1)[1].split('\nRequire-NativeJar', 1)[0]
    assert "$PSBoundParameters.ContainsKey('InputText')" in invoke
    assert '$InputText | & $Executable @Arguments' in invoke


def test_task_original_reader_size_does_not_consume_the_windows_process_argument_budget():
    controller = FILE.with_name('retire-failed-native-jar-duplicates.ps1').read_text(encoding='utf-8-sig')
    reader = controller.split("$reader=@'\n", 1)[1].split("\n'@", 1)[0]
    windows_limit = 32767
    oversized_reader = reader + '\n#' + 'x' * windows_limit
    project = 'D:/AI/lunwen1/DoorHandleCatch'
    values = {'$archive': project + '/work/jenkins/ci-workspaces/monolith/artifacts/source.tar.gz',
              '$Commit': 'f' * 40, '$RetainedControlRoot': project + '/work/jenkins/data-residency-20261107',
              '$jenkinsHome': 'C:/Users/19771/.jenkins', '$RemoteRoot': '/home/ecs-user/doorhandle-ci',
              '$Tag': 'ci-332-' + 'f' * 12, '$CanonicalBatch': 'FailedNative',
              '$RetiredCopyBatch': 'retired-195-198-201', '$FailedNativeBuildNumber': '322'}
    calls = re.findall(r'\$local=\(Invoke-NativeJar \$python @\(([^)]*)\) -InputText \$reader', controller)
    assert len(calls) == 2
    for arguments in calls:
        tokens = arguments.split(',')
        def argv_for(body):
            bindings = {**values, '$reader': body}
            return [project + '/.venv/Scripts/python.exe'] + [
                token[1:-1] if token.startswith("'") else bindings[token] for token in tokens]
        argv = argv_for(reader)
        assert argv == argv_for('') == argv_for(oversized_reader) and reader not in argv
        assert len(subprocess.list2cmdline(argv).encode('utf-16-le')) // 2 + 1 < windows_limit
        old_argv = [*argv[:3], '-c', oversized_reader, *argv[4:]]
        assert len(subprocess.list2cmdline(old_argv).encode('utf-16-le')) // 2 + 1 > windows_limit


@pytest.fixture
def task_retained_original_reader(tmp_path, monkeypatch):
    controller = FILE.with_name('retire-failed-native-jar-duplicates.ps1').read_text(encoding='utf-8-sig')
    reader = controller.split("$reader=@'\n", 1)[1].split("\n'@", 1)[0]
    jhome = tmp_path / 'jhome'; builds = jhome / 'jobs/doorhandle-java/builds'
    build = builds / '287'; build.mkdir(parents=True)
    originals = build / 'archive/artifacts'
    retained = tmp_path / 'retained'; folder = retained / 'ci-287-raw-receipts'; folder.mkdir(parents=True)
    old_source = b'preserved historical source; controller reads metadata only'
    context = {'release': 'ci-287-' + 'a' * 12, 'commit': 'a' * 40,
               'sourceSha256': retirement.digest(old_source)}
    xml = _task_flow_xml(context); (build / 'build.xml').write_bytes(xml); (folder / 'build.xml').write_bytes(xml)
    documents = {
        'release.json': {**context, 'applicationJarSha256': 'c' * 64},
        'local-build.json': {'kind': 'synthetic local build'},
        'fixture-cleanup.json': {'status': 'STOPPED', 'release': context['release'], 'commit': context['commit']},
        'ecs-tool-preparation.json': {**context, 'status': 'PREPARED'},
        'ecs-tool-preparation-transport.json': {**context, 'status': 'PREPARED',
                                              'prepareCandidateBuilder': False, 'finalExitCode': 0},
    }
    raw_files = {name: retirement.encoded(value) for name, value in documents.items()}
    raw_files['source.tar.gz'] = old_source
    manifest = {'build': 287, 'commit': context['commit'], 'result': 'FAILURE',
                'buildXmlSha256': retirement.digest(xml), 'files': []}
    for name, raw in raw_files.items():
        (folder / name).write_bytes(raw)
        manifest['files'].append({'path': name, 'original': str(originals / name),
            'preserved': str(folder / name), 'bytes': len(raw), 'sha256': retirement.digest(raw)})
    def preserve(): (folder / 'preservation.json').write_bytes(retirement.encoded(manifest))
    preserve()
    source = tmp_path / 'current-source.tar.gz'
    with tarfile.open(source, 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': 'f' * 40}) as archive:
        for name in ('script/jenkins/retire-failed-native-jar-duplicates.py', 'script/jenkins/cleanup-ecs-builds.py',
                     'script/jenkins/verify-remote.py', 'script/docker/compact-build-resources.py'):
            member = tarfile.TarInfo(name); member.size = 1; archive.addfile(member, io.BytesIO(b'x'))
    original_open, original_iterdir = Path.open, Path.iterdir
    def no_big_original_reads(path, *args, **kwargs):
        assert path not in (folder / 'source.tar.gz', folder / 'application.jar', originals / 'application.jar')
        return original_open(path, *args, **kwargs)
    def no_build_scan(path):
        assert path != builds, 'An explicit data selector must not discover other builds'
        return original_iterdir(path)
    monkeypatch.setattr(Path, 'open', no_big_original_reads)
    monkeypatch.setattr(Path, 'iterdir', no_build_scan)
    arguments = ['reader', str(source), 'f' * 40, str(retained), str(jhome), '/home/ecs-user/doorhandle-ci',
                 'ci-300-' + 'f' * 12, 'FailedNative', 'retired-195-198-201', '287', 'data-controls-only']
    monkeypatch.setattr(sys, 'argv', arguments)
    return SimpleNamespace(reader=reader, arguments=arguments, build=build, originals=originals, folder=folder,
                           context=context, manifest=manifest, preserve=preserve, raw_files=raw_files)


@pytest.mark.parametrize('state', ['archive-expired', 'build-expired', 'member-bytes', 'source-origin',
                                 'preserved-path', 'xml-binding', 'existing-c-differs', 'ordinary-native'])
def test_task_original_reader_uses_one_bound_preserved_bundle_only_for_explicit_data_cleanup(
        task_retained_original_reader, capsys, state):
    fixture = task_retained_original_reader
    if state == 'build-expired':
        (fixture.build / 'build.xml').unlink(); fixture.build.rmdir()
    elif state == 'member-bytes':
        path = fixture.folder / 'ecs-tool-preparation.json'; path.write_bytes(path.read_bytes() + b' ')
    elif state == 'source-origin':
        next(row for row in fixture.manifest['files'] if row['path'] == 'source.tar.gz')['original'] = str(
            fixture.originals.parent / 'another-build/source.tar.gz')
        fixture.preserve()
    elif state == 'preserved-path':
        next(row for row in fixture.manifest['files'] if row['path'] == 'release.json')['preserved'] = str(
            fixture.folder.parent / 'ci-266-protected/release.json')
        fixture.preserve()
    elif state == 'xml-binding':
        fixture.manifest['buildXmlSha256'] = '0' * 64; fixture.preserve()
    elif state == 'existing-c-differs':
        fixture.originals.mkdir(parents=True)
        (fixture.originals / 'release.json').write_bytes(fixture.raw_files['release.json'] + b' ')
    elif state == 'ordinary-native': fixture.arguments.pop()
    if state not in ('archive-expired', 'build-expired'):
        reason = {'member-bytes': 'TASK_DATA_CUSTODY_MEMBER_BYTES_DIFFER',
                  'source-origin': 'TASK_DATA_CUSTODY_MEMBER_ORIGIN_DIFFERS',
                  'preserved-path': 'TASK_DATA_CUSTODY_MEMBER_ORIGIN_DIFFERS',
                  'xml-binding': 'TASK_DATA_TERMINAL_CUSTODY_DIFFERS',
                  'existing-c-differs': 'TASK_DATA_C_AND_D_ORIGINALS_DIFFER',
                  'ordinary-native': 'EXACT_SELECTED_FAILED_NATIVE_BUILD_REQUIRED'}[state]
        with pytest.raises(ValueError, match='^' + reason + '$'):
            exec(compile(fixture.reader, 'actual-preserved-data-control-reader', 'exec'), {})
        assert capsys.readouterr().out == ''
        return
    exec(compile(fixture.reader, 'actual-preserved-data-control-reader', 'exec'), {})
    result = json.loads(capsys.readouterr().out)
    assert result['skipped'] == [] and len(result['rows']) == 1 and len(result['builderFiles']) == 2
    row = result['rows'][0]
    assert {key: row[key] for key in fixture.context} == fixture.context
    assert {value['source'] for value in row['files'].values()} == {
        str(fixture.folder / name) for name in ('build.xml', 'release.json', 'local-build.json', 'fixture-cleanup.json')}
    assert {value['source'] for value in result['builderFiles']} == {
        str(fixture.folder / name) for name in ('ecs-tool-preparation.json', 'ecs-tool-preparation-transport.json')}
    proof = (fixture.folder / 'preservation.json').read_bytes()
    custody = result['custody'][0]
    assert custody['preservationSha256'] == retirement.digest(proof)
    descriptors = custody['preservedOriginals']
    assert set(descriptors) == {'origin', 'preservation', 'sourceArchive', 'files'}
    assert descriptors['origin'] == 'PRESERVED_JENKINS_TASK_DATA_ORIGINAL'
    assert descriptors['preservation'] == {'source': str(fixture.folder / 'preservation.json'),
                                         'bytes': len(proof), 'sha256': retirement.digest(proof)}
    source_descriptor = next(item for item in fixture.manifest['files'] if item['path'] == 'source.tar.gz')
    assert descriptors['sourceArchive'] == {'source': source_descriptor['preserved'],
                                           'original': source_descriptor['original'],
                                           'bytes': len(fixture.raw_files['source.tar.gz']),
                                           'sha256': fixture.context['sourceSha256']}
    assert set(descriptors['files']) == {'build.xml', *fixture.raw_files.keys()} - {'source.tar.gz'}
    for name, descriptor in descriptors['files'].items():
        body = (fixture.folder / name).read_bytes()
        original = fixture.build / 'build.xml' if name == 'build.xml' else fixture.originals / name
        assert descriptor == {'source': str(fixture.folder / name), 'original': str(original),
                              'bytes': len(body), 'sha256': retirement.digest(body)}
    assert not (fixture.folder / 'application.jar').exists() and not (fixture.originals / 'application.jar').exists()


@pytest.mark.parametrize('when', ['before-load', 'after-load'])
def test_task_real_cleanup_root_probe_keeps_authenticated_archive_bytes(tmp_path, monkeypatch, when):
    tag = 'ci-300-' + 'f' * 12; root = tmp_path / 'ci'; inbox = root / 'inbox' / tag; inbox.mkdir(parents=True)
    own = FILE.read_bytes(); cleanup = FILE.with_name('cleanup-ecs-builds.py').read_bytes()
    drifted = cleanup + b'\n# unreviewed on-disk replacement\n'
    disk = inbox / 'cleanup-ecs-builds.py'; disk.write_bytes(drifted if when == 'before-load' else cleanup); disk.chmod(0o600)
    bodies = {'retire-derived-mysql-data.py': own, 'cleanup-ecs-builds.py': cleanup,
              'retire-failed-native-jar-duplicates.py': b'VALUE=1\n', 'verify-remote.py': b'VALUE=1\n',
              'compact-build-resources.py': b'VALUE=1\n'}
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': 'f' * 40}) as archive:
        for name, body in bodies.items():
            prefix = 'script/docker/' if name == 'compact-build-resources.py' else 'script/jenkins/'
            member = tarfile.TarInfo(prefix + name); member.size = len(body); archive.addfile(member, io.BytesIO(body))
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


TASK_DIAGNOSTIC_CONTROLLER = FILE.with_name('retire-task-failed-mysql-data.ps1').read_text(encoding='utf-8-sig')


def test_task_mysql_remote_streams_are_preserved_separately_before_diagnostic_projection():
    capture = TASK_DIAGNOSTIC_CONTROLLER.split('function Invoke-TaskDataRemote(', 1)[1].split('function Copy-TaskDataEvidence(', 1)[0]
    assert "'artifacts/derived-mysql-{0}-{1:D2}'" in capture
    assert 'stdout="$stem.stdout.txt";stderr="$stem.stderr.txt"' in capture
    assert capture.count('[IO.FileMode]::CreateNew') == 2
    assert '$process.StartInfo.RedirectStandardOutput=$true;$process.StartInfo.RedirectStandardError=$true' in capture
    assert '$process.StandardOutput.BaseStream.CopyToAsync($output)' in capture
    assert '$process.StandardError.BaseStream.CopyToAsync($errorOutput)' in capture
    assert capture.index('$stderrCopy=') < capture.index('$process.WaitForExit()')
    assert capture.index('$process.WaitForExit()') < capture.index('$stdoutCopy.GetAwaiter().GetResult()')
    assert capture.index('$errorOutput.Dispose()') < capture.index('Get-TaskDataRemoteDiagnostic $Phase')
    assert '$process.StartInfo.UseShellExecute=$false' in capture
    assert '$process.StartInfo.ArgumentList.Add($argument)' in capture
    assert '2>&1' not in capture and 'ReadToEnd' not in capture


def test_task_mysql_remote_and_evidence_functions_emit_only_their_result_object():
    capture = TASK_DIAGNOSTIC_CONTROLLER.split('function Invoke-TaskDataRemote(', 1)[1].split('function Copy-TaskDataEvidence(', 1)[0]
    await_results = re.findall(r'(?:\[void\]\s*)?\$(?:stdoutCopy|stderrCopy)\.GetAwaiter\(\)\.GetResult\(\)', capture)
    assert len(await_results) == 2 and all(item.startswith('[void]') for item in await_results)
    assert re.search(r'\[void\]\s*\$process\.StartInfo\.ArgumentList\.Add\(\$argument\)', capture)
    assert re.search(r'\[void\]\s*\$remoteCalls\.Add\(\$row\)', capture)
    assert capture.count('return $row') == 1
    evidence = TASK_DIAGNOSTIC_CONTROLLER.split('function Copy-TaskDataEvidence(', 1)[1].split('\ntry {', 1)[0]
    assert re.search(r'\$null\s*=\s*& scp\.exe\b', evidence)
    assert 'if($LASTEXITCODE -ne 0){return $null}' in evidence
    assert evidence.count('return $value') == 1 and '2>&1' not in evidence


def test_task_mysql_plan_and_authorization_gates_precede_the_single_apply_attempt():
    controller = TASK_DIAGNOSTIC_CONTROLLER
    ordered = ["$planned=Invoke-TaskDataRemote 'plan'",
               'Require-TaskData ($planned.exitCode -eq 0)',
               "$plan=Copy-TaskDataEvidence 'plan.json'",
               'Require-TaskData ($null -ne $plan -and @($plan.targets).Count -eq $numbers.Count',
               'Require-TaskData ((Read-TaskDataAuthorization) -ceq $authorizationSha)',
               '$attempted=$true', "$applied=Invoke-TaskDataRemote 'apply'"]
    offsets = [controller.index(value) for value in ordered]
    assert offsets == sorted(offsets) and len(set(offsets)) == len(offsets)
    assert controller.count("Invoke-TaskDataRemote 'apply'") == 1
    assert controller.count('$attempted=$true') == 1


@pytest.mark.parametrize('phase', ['plan', 'apply', 'status'])
def test_task_mysql_each_remote_phase_uses_original_stream_capture_without_apply_replay(phase):
    calls = re.findall(r"Invoke-TaskDataRemote '(plan|apply|status)'", TASK_DIAGNOSTIC_CONTROLLER)
    assert calls.count(phase) == 1
    assert not re.search(r'& ssh\.exe[^\n]*python3[^\n]*\b' + phase + r'\b', TASK_DIAGNOSTIC_CONTROLLER)
    observation = TASK_DIAGNOSTIC_CONTROLLER.split('if($applyExit -eq 255){', 1)[1].split('}catch{\n    $failure=$_', 1)[0]
    assert "Invoke-TaskDataRemote 'status'" in observation
    assert "Invoke-TaskDataRemote 'apply'" not in observation
    assert '$state.terminal -eq $true -and $state.status -ceq \'COMPLETE\'' in observation


def test_task_mysql_only_fixed_safe_remote_diagnostic_fields_reach_controller_receipt():
    projection = TASK_DIAGNOSTIC_CONTROLLER.split('function Get-TaskDataRemoteDiagnostic(', 1)[1].split('function Invoke-TaskDataRemote(', 1)[0]
    assert 'if($ExitCode -eq 0){return $null}' in projection
    assert '.Length -gt 1048576' in projection
    assert '[Text.UTF8Encoding]::new($false,$true)' in projection
    assert "$value.status -cne 'FAILED_OR_UNKNOWN' -or $value.phase -cne $Phase" in projection
    assert "$value.errorType -cnotmatch '\\A[A-Za-z][A-Za-z0-9]{0,63}\\z'" in projection
    assert "$value.reasonCode -cnotmatch '\\A[A-Z][A-Z0-9_]{1,160}\\z'" in projection
    assert 'return @{errorType=$value.errorType;reasonCode=$value.reasonCode;phase=$Phase}' in projection
    assert 'catch{return $fallback}' in projection
    assert 'Exception.Message' not in projection and '$value.message' not in projection


def test_task_mysql_local_diagnostic_has_only_safe_coordinates_and_never_replaces_remote_failure():
    projection = TASK_DIAGNOSTIC_CONTROLLER.split('function Get-TaskDataControllerDiagnostic(', 1)[1].split('function Get-TaskDataRemoteDiagnostic(', 1)[0]
    assert "$exceptionType -cnotmatch '\\A[A-Za-z][A-Za-z0-9]{0,95}\\z'" in projection
    assert "$exceptionType='ControllerException'" in projection
    assert '$sourceFile=$null;$sourceLine=$null' in projection
    assert '$Record.InvocationInfo.ScriptName -ceq $PSCommandPath -and $Record.InvocationInfo.ScriptLineNumber -gt 0' in projection
    assert "$sourceFile='script/jenkins/retire-task-failed-mysql-data.ps1'" in projection
    assert '$sourceLine=$Record.InvocationInfo.ScriptLineNumber' in projection
    assert set(re.findall(r'\$Record\.([A-Za-z0-9_.]+)', projection)) == {
        'Exception.GetType', 'InvocationInfo.ScriptName', 'InvocationInfo.ScriptLineNumber'}
    assert "return @{errorType='ControllerError';reasonCode='CONTROLLER_OPERATION_FAILED';phase=$Phase;step=$Step;" in projection
    assert 'exceptionType=$exceptionType;sourceFile=$sourceFile;sourceLine=$sourceLine}' in projection
    steps = set(re.findall(r"'([^']+)'", re.search(r'\[ValidateSet\(([^)]*)\)\]', projection).group(1)))
    assert steps == {'PLAN_REMOTE', 'PLAN_EVIDENCE', 'PLAN_VALIDATE', 'AUTHORIZATION_RECHECK',
                     'APPLY_REMOTE', 'STATUS_REMOTE', 'STATUS_VALIDATE'}
    assert all("$currentStep='" + step + "'" in TASK_DIAGNOSTIC_CONTROLLER for step in steps)
    assert 'if($null -eq $failureDiagnostic){$failureDiagnostic=Get-TaskDataControllerDiagnostic $_ $currentPhase $currentStep}' in TASK_DIAGNOSTIC_CONTROLLER
    assert 'if($planned.exitCode -ne 0){$failureDiagnostic=$planned.diagnostic}' in TASK_DIAGNOSTIC_CONTROLLER
    assert 'if($applyExit -ne 0){$failureDiagnostic=$applied.diagnostic}' in TASK_DIAGNOSTIC_CONTROLLER


def test_task_mysql_final_collection_cannot_replace_primary_failure_or_claim_partial_success():
    final = TASK_DIAGNOSTIC_CONTROLLER.split('}finally{\n    foreach($evidence', 1)[1]
    assert '$failure=$_' not in final and '$failureDiagnostic=$_' not in final
    assert "$secondaryFailures.Add(@{errorType='ControllerError';reasonCode='EVIDENCE_COLLECTION_FAILED'" in final
    assert "$secondaryFailures.Add(@{errorType='ControllerError';reasonCode='EVIDENCE_UNAVAILABLE'" in final
    assert '$null -eq $failure -and $secondaryFailures.Count -eq 0' in final
    assert '$receipt.status -ceq \'COMPLETE\'' in final
    assert '$receipt.planSha256 -ceq $plan.planSha256' in final
    assert '@($receipt.removed).Count -eq $numbers.Count' in final
    assert 'if(-not $ok -and $null -eq $failureDiagnostic)' in final
    assert 'failure=$failureDiagnostic;secondaryFailures=@($secondaryFailures.ToArray());remoteCalls=@($remoteCalls.ToArray())' in final


def test_task_mysql_original_streams_are_archived_by_the_existing_maintenance_entry():
    pipeline = (FILE.parents[2] / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf-8-sig')
    assert 'artifacts/derived-mysql-*.json' in pipeline
    assert 'artifacts/derived-mysql-*.txt' in pipeline


def test_task_mysql_original_custody_is_retained_before_any_remote_staging():
    controller = TASK_DIAGNOSTIC_CONTROLLER
    assert 'custody=$local.custody;builderFiles=$local.builderFiles' in controller
    freshness = controller.index("foreach($name in @('derived-mysql-request.json'")
    output = controller.index('Set-Content -LiteralPath artifacts/derived-mysql-original-custody.json')
    remote = controller.index('& ssh.exe @SshOptions -p $PortText $Destination $prepare')
    assert freshness < output < remote
    guard = controller[freshness:output]
    assert "'derived-mysql-original-custody.json'" in guard
    assert 'Require-TaskData (-not(Test-Path -LiteralPath "artifacts/$name"))' in guard
    assert "kind='doorhandle-task-data-original-custody'" in guard
    assert 'release=$Tag;commit=$Commit;sourceSha256=$SourceSha256' in guard
    assert 'taskThreadId=$task;authorizationSha256=$authorizationSha;candidates=$originalCustody' in guard


@pytest.mark.parametrize('message,expected', [
    ('TASK_FIXTURE_CHANGED_AFTER_PLAN', 'TASK_FIXTURE_CHANGED_AFTER_PLAN'),
    ('/home/private/credential: password=secret', 'UNCLASSIFIED_ERROR'),
    ('PRIVATE_SECRET', 'UNCLASSIFIED_ERROR'),
])
def test_task_main_preserves_only_literal_failure_codes_and_phase(monkeypatch, capsys, message, expected):
    monkeypatch.setattr(sys, 'argv', ['retirement', 'plan', '--batch', retirement.TASK_BATCH,
        '--tag', 'ci-300-' + 'f' * 12, '--commit', 'f' * 40, '--source-sha256', 'e' * 64])
    monkeypatch.setattr(retirement.signal, 'signal', lambda *_: None)
    def failed(_args): raise ValueError(message)
    monkeypatch.setattr(retirement, 'run', failed)
    assert retirement.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ''
    diagnostic = json.loads(captured.err)
    locations = diagnostic.pop('failureLocations')
    assert diagnostic == {'status': 'FAILED_OR_UNKNOWN', 'errorType': 'ValueError',
                          'reasonCode': expected, 'phase': 'plan'}
    assert locations and all(row['file'] == FILE.name and row['function'] == 'main' for row in locations)


def test_task_failure_reason_preserves_loaded_cleanup_literal_without_arbitrary_messages():
    spec = importlib.util.spec_from_file_location('task_diagnostic_cleanup', FILE.with_name('cleanup-ecs-builds.py'))
    cleanup = importlib.util.module_from_spec(spec); spec.loader.exec_module(cleanup)
    try:
        cleanup.require(False, 'OLD_BUILD_CONTAINER_STILL_PRESENT')
    except ValueError as error:
        assert retirement.failure_reason_code(error) == 'OLD_BUILD_CONTAINER_STILL_PRESENT'
    assert retirement.failure_reason_code(OSError('private path or credentials')) == 'UNCLASSIFIED_ERROR'


def _finished_selection():
    return {'policy': retirement.FINISHED_BATCH, 'publicationRecipe': ['1' * 64, '2' * 64, '3' * 64],
            'jarSha256': 'c' * 64, 'jarBytes': 10, 'dataIdentity': [64771, 1234],
            'jarIdentities': [[64771, 1235], [64771, 1236]]}


@pytest.mark.parametrize('damage', [None, 'old-authorization', 'old-entry', 'missing-manifest',
    'arbitrary-path', 'generic-policy', 'bad-recipe', 'same-inode', 'protected-build'])
def test_finished_request_has_independent_authority_and_exact_resource_selection(task_request_document, damage):
    state = task_request_document
    state.binding['batch'] = retirement.FINISHED_BATCH
    state.value['kind'] = 'doorhandle-authorized-pre-runtime-outputs-request'
    state.value['authorization'].update(taskThreadId=retirement.FINISHED_TASK_ID, manifestSha256='d' * 64)
    for row in state.value['candidates']: row['retirement'] = _finished_selection()
    item = state.value['candidates'][0]['retirement']
    if damage == 'old-authorization': state.value['authorization']['taskThreadId'] = retirement.TASK_ID
    elif damage == 'old-entry': state.binding.pop('batch')
    elif damage == 'missing-manifest': state.value['authorization'].pop('manifestSha256')
    elif damage == 'arbitrary-path': item['path'] = '/var/lib/mysql'
    elif damage == 'generic-policy': item['policy'] = 'all-finished-builds'
    elif damage == 'bad-recipe': item['publicationRecipe'][1] = 'unknown'
    elif damage == 'same-inode': item['jarIdentities'][0] = item['dataIdentity']
    elif damage == 'protected-build': state.value['builds'][0] = '266'; state.binding['failedBuilds'] = '266,289'
    state.refresh()
    if damage:
        with pytest.raises(ValueError): retirement.task_request(state.binding)
    else:
        assert retirement.task_request(state.binding) == state.value


@pytest.fixture
def finished_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(retirement, 'ROOT', tmp_path)
    row = {'release': 'ci-344-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    identity = {'instanceId': retirement.INSTANCE, 'machineId': retirement.MACHINE, 'executionLocation': 'ECS'}
    tools = {'kind': 'doorhandle-candidate-build-tools', 'status': 'PREPARED', **row,
             'identity': identity, 'imageId': 'sha256:' + 'c' * 64}
    raw = retirement.encoded(tools)
    path = tmp_path / 'inbox' / row['release'] / 'candidate-build-tools/tools.json'
    preparation = {'kind': 'doorhandle-ecs-tool-preparation', 'status': 'PREPARED', **row,
        'identity': identity, 'testsExecuted': False, 'sourceFiles': {'script/jenkins/prepare-ecs-tools.py': 'd' * 64},
        'candidateBuilderTools': {'file': str(path), 'status': 'PREPARED', 'sha256': retirement.digest(raw), 'imageId': tools['imageId']},
        'buildkitArchive': {'file': 'shared-buildkit-archive', 'sha256': 'e' * 64, 'bytes': 100}}
    transport = {'kind': 'doorhandle-public-build-input-transport', 'status': 'AVAILABLE', **row,
                 'buildkitArchive': preparation['buildkitArchive']}
    monkeypatch.setattr(retirement, 'read', lambda actual: raw if actual == path else pytest.fail('Unexpected tool read'))
    return SimpleNamespace(row=row, identity=identity, preparation=preparation, transport=transport,
        recipe={'toolPreparationHelperSha256': 'd' * 64}, raw=raw, root=tmp_path)


@pytest.mark.parametrize('damage', [None, 'release', 'execution', 'failure', 'acceptance', 'runtime-work',
    'candidate-work', 'migration', 'symlink', 'tools-sha', 'preparation-sha', 'transport', 'builder-missing'])
def test_finished_entry_requires_prepared_tools_but_no_application_candidate_or_runtime(finished_tools, damage):
    state = finished_tools; base = state.root / 'verification' / state.row['release']
    paths = {'release': state.root / 'releases' / state.row['release'], 'execution': base / 'runtime-execution.json',
        'failure': base / 'runtime-failure.json', 'acceptance': base / 'runtime-acceptance.json',
        'runtime-work': base / 'checkout/work/runtime-acceptance', 'candidate-work': base / 'checkout/work/candidate-build-resources',
        'migration': base / 'checkout/work/compact-fixtures/runtime-migration.json'}
    if damage in paths:
        paths[damage].parent.mkdir(parents=True, exist_ok=True); paths[damage].touch()
    elif damage == 'symlink':
        paths['execution'].parent.mkdir(parents=True); paths['execution'].symlink_to(state.root / 'missing')
    elif damage == 'tools-sha': state.preparation['candidateBuilderTools']['sha256'] = 'f' * 64
    elif damage == 'preparation-sha': state.preparation['sourceFiles']['script/jenkins/prepare-ecs-tools.py'] = 'f' * 64
    elif damage == 'transport': state.transport['status'] = 'UNKNOWN'
    elif damage == 'builder-missing': state.preparation.pop('candidateBuilderTools')
    arguments = (state.row, state.preparation, state.transport, state.recipe, state.identity)
    if damage:
        with pytest.raises(ValueError): retirement.finished_runtime_absence(*arguments)
    else:
        assert retirement.finished_runtime_absence(*arguments) == {
            'toolsSha256': retirement.digest(state.raw), 'candidateRuntimeEntered': False}


@pytest.mark.parametrize('replaced', [False, True])
def test_finished_binary_plan_keeps_copy_before_canonical_and_binds_observed_inodes(replaced):
    row = {'release': 'ci-344-' + 'a' * 12, 'retirement': _finished_selection()}
    canonical = {'metadata': [64771, 1235], 'kind': 'canonical'}
    copy = {'metadata': [64771, 9999 if replaced else 1236], 'kind': 'copy'}
    native = SimpleNamespace(describe_duplicate=lambda *_: copy, describe_canonical_jar=lambda *_a, **_k: canonical)
    arguments = ({'candidates': [row]}, {'retire-failed-native-jar-duplicates.py': native})
    if replaced:
        with pytest.raises(ValueError, match='MANIFEST_JAR_INODE_REPLACED'): retirement.finished_jar_targets(*arguments)
    else:
        assert retirement.finished_jar_targets(*arguments) == [copy, canonical]


@pytest.mark.parametrize('failure', [None, 'quiescence', 'copy', 'canonical'])
def test_finished_binary_deletion_reuses_capture_primitives_and_preserves_partial_journal(tmp_path, failure):
    events = []; receipt = {'planSha256': 'a' * 64, 'requestSha256': 'b' * 64, 'jarRetirements': []}
    targets = [{'kind': name, 'release': 'ci-344-' + 'c' * 12, 'path': name + '.jar'} for name in ('copy', 'canonical')]
    def quiescent():
        if failure == 'quiescence': raise ValueError('REFERENCED')
        events.append('quiescent')
    def remove(_root, target, _quarantine, *, quiescence, **options):
        quiescence(); events.append(target['kind'])
        if failure == target['kind']: raise ValueError('CHANGED')
        assert options == ({'failed_native': True} if target['kind'] == 'canonical' else {})
        return {'path': target['path']}
    native = SimpleNamespace(JAR_COPY_KIND='copy', CANONICAL_JAR_KIND='canonical',
        reserve_quarantine=lambda *_: {'path': 'private-quarantine/candidate-app.jar'},
        remove_duplicate=remove, remove_canonical_jar=remove)
    arguments = (tmp_path, targets, {'retire-failed-native-jar-duplicates.py': native}, quiescent, receipt)
    if failure:
        with pytest.raises(ValueError): retirement.finished_remove_jars(*arguments)
    else: retirement.finished_remove_jars(*arguments)
    journal = [json.loads(line) for line in (tmp_path / 'jar-journal.jsonl').read_text().splitlines()]
    assert journal[0]['phase'] == 'STARTED'
    if failure:
        assert journal[-1]['phase'] != 'FINISHED'
        assert len(receipt['jarRetirements']) == (1 if failure == 'canonical' else 0)
    else:
        assert [event for event in events if event != 'quiescent'] == ['copy', 'canonical']
        assert journal[-1] == {'phase': 'FINISHED', 'deletedFiles': 2}


def test_finished_controller_preserves_exact_authority_and_journal_without_generic_cleanup():
    controller = TASK_DIAGNOSTIC_CONTROLLER
    assert "$finished=-not [string]::IsNullOrWhiteSpace($finishedManifest)" in controller
    assert "else{'01a1a46b-d37a-7fb2-8638-afe345c73531'}" in controller
    assert "else{'current-task-failed-verify-mysql-v1'}" in controller
    assert "@($authorization.acceptedActions).Count -eq 1 -and $authorization.acceptedActions[0] -ceq 'verify'" in controller
    producer = (FILE.parents[2] / 'script/jenkins/pipeline.ps1').read_text(encoding='utf-8-sig')
    branch = producer.split("if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable('CI_FINISHED_OUTPUTS_MANIFEST'))) {", 1)[1].split('\n    }', 1)[0]
    assert '-Mode Maintenance -PrepareOnly' in branch and '-FailedBuildNumbers $failedMysqlDataBuilds' in branch
    assert 'FailedNativeBuildNumber' not in branch and branch.rstrip().endswith('return')
    assert 'cleanup-authorization-20261115.json' in controller and 'ACTUAL_GUARDED_RECOVERY_PUBLIC_RECEIPT' in controller
    assert 'authorizationSha256 -ceq $authorizationSha' in controller and 'manifestSha256=$manifestSha' in controller
    assert controller.index("$currentStep='AUTHORIZATION_RECHECK'") < controller.index('$attempted=$true')
    assert 'derived-mysql-user-authorization.json' in controller and 'derived-mysql-finished-manifest.json' in controller
    pipeline = (FILE.parents[2] / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf-8-sig')
    assert 'artifacts/derived-mysql-*.jsonl' in pipeline
    gate = producer.split("if ($failedMysqlDataBuilds -cne '') {", 1)[1].split('\n}', 1)[0]
    assert "[string]::IsNullOrWhiteSpace($finishedOutputsManifest) -and $env:DOORHANDLE_FAILED_MYSQL_DATA_TASK_ID" in gate
    assert "$failedNativeBuildNumber -cne ''" in gate


def test_finished_controller_accepts_unset_or_empty_selector_without_accepting_whitespace():
    # Windows Jenkins can omit an empty parameter from the process environment.
    # Bind the actual PowerShell guard to the .NET null/empty contract, not -ceq ''.
    guard = next(line for line in TASK_DIAGNOSTIC_CONTROLLER.splitlines()
                 if 'Finished outputs require a separate exact manifest' in line)
    assert '[string]::IsNullOrEmpty($env:FAILED_NATIVE_BUILD_NUMBER)' in guard
    assert "$env:FAILED_NATIVE_BUILD_NUMBER -ceq ''" not in guard
    assert 'IsNullOrWhiteSpace($env:FAILED_NATIVE_BUILD_NUMBER)' not in guard
    assert "[IO.Path]::IsPathFullyQualified($finishedManifest)" in guard
    assert "$env:GENERATED_ARTIFACTS_ONLY -cne 'true'" in guard


@pytest.mark.parametrize('damage', [None, 'wrong-action', 'wrong-jar'])
def test_finished_admission_uses_runtime_terminal_without_borrowing_verify_authority(task_keeper_documents, monkeypatch, damage):
    state = task_keeper_documents
    state.binding['batch'] = retirement.FINISHED_BATCH
    state.row['retirement'] = _finished_selection()
    if damage != 'wrong-action':
        state.xml = state.xml.replace(b'<value>verify</value>', b'<value>verify-runtime</value>')
    if damage == 'wrong-jar': state.row['retirement']['jarBytes'] = 11
    state.refresh()
    transport = retirement.encoded(state.documents['ecs-tool-preparation-transport.json'])
    state.row['controls']['transport'] = {'bytes': len(transport), 'sha256': retirement.digest(transport)}
    read = retirement.read
    monkeypatch.setattr(retirement, 'read', lambda path, maximum=0:
        transport if path.name == 'candidate-build-tools-transport.json' else read(path, maximum))
    calls = []
    def absence(*args):
        calls.append(args)
        return {'toolsSha256': 'e' * 64, 'candidateRuntimeEntered': False}
    monkeypatch.setattr(retirement, 'finished_runtime_absence', absence)
    if damage:
        with pytest.raises((ValueError, state.native.RetirementError)):
            retirement.task_admitted(state.binding, state.value, state.helpers)
    else:
        result = retirement.task_admitted(state.binding, state.value, state.helpers)
        assert len(calls) == 1 and result[0]['preRuntimeAbsence']['candidateRuntimeEntered'] is False
        assert result[0]['reports'] == {'reportFiles': 1}
        assert result[0]['sourceSqlSha256'] == state.manifest['data']['sha256']


def test_finished_mysql_root_must_still_be_the_exact_inventoried_inode(task_request_document):
    row = task_request_document.value['candidates'][0]
    row['retirement'] = _finished_selection()
    value = {'candidates': [row]}; keepers = [{'release': row['release'], 'backupManifestSha256': 'b' * 64}]
    roots = {row['release']: [64771, 1234, stat.S_IFDIR | 0o700, 999, 1000]}
    assert retirement.task_configuration(value, keepers, roots).targets[row['release']][0] == 1234
    roots[row['release']][1] += 1
    with pytest.raises(ValueError, match='MANIFEST_DATA_DIRECTORY_REPLACED'):
        retirement.task_configuration(value, keepers, roots)


@pytest.fixture
def finished_builder_controls(tmp_path, monkeypatch):
    from tests_python import test_historical_builder_retirement as builder_cases
    state = builder_cases.fixture_state(('ci-344-' + 'a' * 12, 'a' * 40, '1' * 64, 'b' * 24))
    # The control container mounts only its synthetic test workspace, not the
    # host CI tree. Satisfy the real path/owner guards inside that workspace.
    state.root = tmp_path / 'ci'
    checkout = state.root / 'verification' / state.context['release'] / 'checkout'
    inbox = state.root / 'inbox' / state.context['release']
    for path in (state.root, checkout.parent.parent, checkout.parent, checkout, inbox.parent, inbox):
        path.mkdir(mode=0o700)
    directory = inbox / 'candidate-build-tools'
    state.tools['licenseFile'] = str(directory / 'LICENSE')
    state.tools['resourceEvidence']['file'] = str(directory / 'resource-summary.json')
    builder = builder_cases.resources
    spec = importlib.util.spec_from_file_location('derived_finished_native', FILE.with_name('retire-failed-native-jar-duplicates.py'))
    native = importlib.util.module_from_spec(spec); spec.loader.exec_module(native)
    native.LOADED_SOURCE = FILE.with_name('retire-failed-native-jar-duplicates.py').read_bytes()
    spec = importlib.util.spec_from_file_location('derived_finished_cleanup', FILE.with_name('cleanup-ecs-builds.py'))
    cleanup = importlib.util.module_from_spec(spec); spec.loader.exec_module(cleanup)
    source = {'path': 'inbox/' + state.context['release'] + '/source.tar.gz', 'sha256': state.context['sourceSha256'],
        'failedNativePolicy': 'failed-native-retention-v1', 'mysqlFixtureStartSourceSha256': builder.LEGACY_MYSQL_START_SOURCE,
        'builderHelperSha256': state.helpers}
    historical = {'context': state.context, 'finishedOutputsPolicy': retirement.FINISHED_BATCH,
        'preparedToolsSha256': retirement.digest(builder_cases.raw(state.tools)), 'sourceArchive': source,
        'evidence': {'identity': state.identity, 'ownerToken': 'c' * 10}}
    fixture = {'containerId': '2' * 64, 'ownerToken': 'c' * 10}
    fixture_row = {'Id': fixture['containerId'], 'Name': '/doorhandle-compact-fixture-' + fixture['ownerToken'],
        'State': {'Running': False, 'Restarting': False, 'Pid': 0},
        'Config': {'Labels': {'io.doorhandle.release': state.context['release']}}, 'HostConfig': {}, 'Mounts': []}
    rows = {state.row['Id']: state.row, fixture_row['Id']: fixture_row}; commands = []; probes = []
    names = {'tools.json': 'tools', 'resource-summary.json': 'summary', 'official-layer-measurements.json': 'measurement'}
    def held(root, path, maximum):
        assert root == state.root and path.parent == directory and maximum == native.MAX_CONTROL
        return nullcontext((io.BytesIO(builder_cases.raw(getattr(state, names[path.name]))), [0] * 10))
    def docker(*args):
        commands.append(args)
        assert len(args) == 2 and args[0] == 'inspect', 'Preserved builders and volumes must never be removed'
        return retirement.encoded([rows[args[1]]])
    def snapshot():
        return [(cid, row['State']['Running'], row['State']['Restarting'], row['State']['Pid'],
            row['Config']['Labels'].get('io.doorhandle.release'), row['Config']['Labels'].get(builder.LABEL), row['Mounts'])
            for cid, row in rows.items()]
    # Exercise the real process-reference parser against one synthetic /proc
    # record, never the host process table or an unconditional quiet stub.
    proc = tmp_path / 'proc'; process = proc / str(os.getpid() + 10_000_000)
    process.mkdir(parents=True, mode=0o700)
    (process / 'cwd').symlink_to(tmp_path, target_is_directory=True)
    (process / 'fd').mkdir(mode=0o700)
    (process / 'cmdline').write_bytes(b'synthetic-worker\0')
    (process / 'maps').write_bytes(b'')
    process_references = cleanup.process_references
    def probe(actual_checkout, **options):
        assert actual_checkout == checkout and options == {'include_inbox': True}
        probes.append(options)
        return process_references(actual_checkout, proc=proc, **options)
    monkeypatch.setattr(retirement, 'ROOT', state.root)
    monkeypatch.setattr(native, 'held_file', held)
    monkeypatch.setattr(native, 'builder_docker', docker)
    monkeypatch.setattr(native, 'builder_container_ids', lambda: list(rows))
    monkeypatch.setattr(native, 'canonical_publication_refs', lambda *_: probes.append('publication'))
    monkeypatch.setattr(cleanup, 'docker_snapshot', snapshot)
    monkeypatch.setattr(cleanup, 'process_references', probe)
    helpers = {'retire-failed-native-jar-duplicates.py': native, 'compact-build-resources.py': builder,
               'cleanup-ecs-builds.py': cleanup}
    return SimpleNamespace(state=state, historical=historical, fixture=fixture, rows=rows, native=native,
                           cleanup=cleanup, builder=builder, helpers=helpers, commands=commands, probes=probes,
                           checkout=checkout, inbox=inbox, process=process)


@pytest.mark.parametrize('fixture_present', [False, True])
@pytest.mark.parametrize('builder_present', [False, True])
def test_finished_retains_only_authenticated_independent_builder_in_all_reference_paths(
        finished_builder_controls, fixture_present, builder_present):
    state = finished_builder_controls
    if not fixture_present: state.rows.pop(state.fixture['containerId'])
    if not builder_present: state.rows.pop(state.state.row['Id'])
    descriptor = retirement.finished_preserved_builder(state.historical, state.helpers)
    candidate = {'historical': state.historical, 'fixture': state.fixture if fixture_present else None,
                 'preservedBuilder': descriptor}
    retirement.task_fixture_quiescence([{'release': state.state.context['release']}], [candidate], state.helpers)
    assert {'include_inbox': True} in state.probes
    if builder_present:
        assert descriptor['preservedVolume'] == state.state.volume and descriptor['volumesPreserved'] is True
        assert descriptor['controlSha256']['tools'] == state.historical['preparedToolsSha256']
    else: assert descriptor is None
    assert all(command[0] == 'inspect' for command in state.commands)
    for referenced in (state.checkout, state.inbox):
        (state.process / 'cmdline').write_bytes(os.fsencode(referenced) + b'\0')
        with pytest.raises(ValueError, match='ACTIVE_PROCESS_REFERENCES_OLD_CHECKOUT'):
            retirement.task_candidate_references(candidate, state.helpers)


@pytest.mark.parametrize('damage', ['tools', 'summary', 'measurement', 'source', 'helper', 'cid', 'token',
    'running', 'pid', 'restart', 'exec', 'bind', 'volume', 'source-label'])
def test_finished_builder_cannot_gain_an_exclusion_from_labels_or_incomplete_controls(finished_builder_controls, damage):
    case = finished_builder_controls; state = case.state
    if damage == 'tools': state.tools['status'] = 'UNKNOWN'
    elif damage == 'summary': state.summary['cleanup']['builderStopped'] = False
    elif damage == 'measurement': state.measurement['compressedBytes'] += 1
    elif damage == 'source': case.historical['sourceArchive']['sha256'] = 'f' * 64
    elif damage == 'helper': case.historical['sourceArchive']['builderHelperSha256'] = {}
    elif damage == 'cid': state.row['Id'] = 'f' * 64
    elif damage == 'token': state.row['Config']['Labels'][case.builder.LABEL] = 'f' * 24
    elif damage == 'running': state.row['State']['Running'] = True
    elif damage == 'pid': state.row['State']['Pid'] = 1234
    elif damage == 'restart': state.row['HostConfig']['RestartPolicy']['Name'] = 'always'
    elif damage == 'exec': state.row['ExecIDs'] = ['active-exec']
    elif damage == 'bind': state.row['Mounts'].append({'Type': 'bind', 'Source': str(state.root / 'inbox')})
    elif damage == 'volume': state.row['Mounts'][0]['Name'] = 'another-volume'
    elif damage == 'source-label': state.row['Config']['Labels']['io.doorhandle.source'] = 'f' * 64
    with pytest.raises(ValueError): retirement.finished_preserved_builder(case.historical, case.helpers)
    assert all(command[0] == 'inspect' for command in case.commands)


@pytest.mark.parametrize('damage', ['same-release', 'checkout-bind', 'inbox-bind', 'namespace', 'changed-inspect', 'vanished', 'unplanned-builder'])
def test_finished_reference_rechecks_keep_all_other_objects_and_plan_identity(finished_builder_controls, damage):
    case = finished_builder_controls
    if damage == 'unplanned-builder': case.rows.pop(case.state.row['Id'])
    candidate = {'historical': case.historical, 'fixture': case.fixture,
                 'preservedBuilder': retirement.finished_preserved_builder(case.historical, case.helpers)}
    row = {'Id': '3' * 64, 'Name': '/unrelated', 'State': {'Running': False, 'Restarting': False, 'Pid': 0},
           'Config': {'Labels': {}}, 'HostConfig': {}, 'Mounts': []}
    if damage == 'same-release': row['Config']['Labels']['io.doorhandle.release'] = case.state.context['release']
    elif damage in ('checkout-bind', 'inbox-bind'):
        path = (case.state.root / 'verification' / case.state.context['release'] / 'checkout' if damage == 'checkout-bind'
                else case.state.root / 'inbox' / case.state.context['release'])
        row['Mounts'] = [{'Type': 'bind', 'Source': str(path)}]
    elif damage == 'namespace': row['HostConfig']['NetworkMode'] = 'container:' + case.state.row['Id']
    elif damage == 'changed-inspect': case.state.row['State']['StartedAt'] = '2026-11-15T00:00:00Z'
    elif damage == 'vanished': case.rows.pop(case.state.row['Id'])
    elif damage == 'unplanned-builder': case.rows[case.state.row['Id']] = case.state.row
    case.rows[row['Id']] = row
    with pytest.raises(ValueError): retirement.task_candidate_references(candidate, case.helpers)
    assert all(command[0] == 'inspect' for command in case.commands)


def test_finished_fixture_remove_uses_the_same_rebound_preserved_builder_callback(finished_builder_controls, monkeypatch):
    case = finished_builder_controls
    candidate = {'historical': case.historical, 'fixture': {**case.fixture, 'dataDirectory': '/synthetic/mysql-data'},
                 'preservedBuilder': retirement.finished_preserved_builder(case.historical, case.helpers)}
    def remove(fixture, _inspect, _remove, _list, references, _data):
        case.state.row['State']['Running'] = True
        references(fixture['containerId'])
        pytest.fail('Changed preserved builder must stop the removal callback')
    monkeypatch.setattr(case.builder, 'historical_mysql_fixture_remove', remove)
    with pytest.raises(ValueError): retirement.task_remove_fixture(candidate, case.helpers)
    assert all(command[0] == 'inspect' for command in case.commands)


@pytest.mark.parametrize('fixture_present', [False, True])
def test_old_verify_only_quiescence_never_excludes_a_builder(finished_builder_controls, fixture_present):
    case = finished_builder_controls; case.historical.pop('finishedOutputsPolicy')
    if not fixture_present: case.rows.pop(case.fixture['containerId'])
    candidate = {'historical': case.historical, 'fixture': case.fixture if fixture_present else None}
    with pytest.raises(ValueError, match='OLD_BUILD_CONTAINER_STILL_PRESENT'):
        retirement.task_candidate_references(candidate, case.helpers)


def test_task_diagnostic_preserves_the_actual_nested_stopped_builder_guard(finished_builder_controls):
    case = finished_builder_controls
    candidate = {'historical': case.historical, 'fixture': case.fixture}
    try:
        case.native.recent_fixture_references(retirement.ROOT, candidate, case.cleanup, case.builder)
    except ValueError as error:
        assert retirement.failure_reason_code(error) == 'HISTORICAL_OBJECTS_NOT_QUIESCENT_OLD_BUILD_CONTAINER_STILL_PRESENT'
    else: pytest.fail('Unadmitted stopped builder must remain a real rejection')


@pytest.mark.parametrize('private', ['PRIVATE_SECRET', '/home/private/password=secret'])
def test_task_diagnostic_never_publishes_an_unvalidated_wrapped_suffix(finished_builder_controls, monkeypatch, private):
    case = finished_builder_controls
    def reject(*_args, **_kwargs): raise ValueError(private)
    monkeypatch.setattr(case.cleanup, 'quiescent', reject)
    monkeypatch.setattr(case.cleanup, 'failure_guard_code', lambda _error: private)
    try:
        case.native.recent_fixture_references(retirement.ROOT,
            {'historical': case.historical, 'fixture': case.fixture}, case.cleanup, case.builder)
    except ValueError as error:
        assert retirement.failure_reason_code(error) == 'UNCLASSIFIED_ERROR'
    else: pytest.fail('Expected private inner refusal')


def test_task_diagnostic_preserves_direct_static_helper_guard(finished_builder_controls):
    case = finished_builder_controls
    try: case.native.terminal_xml(b'not xml', case.state.context)
    except ValueError as error:
        assert retirement.failure_reason_code(error) == 'INVALID_TERMINAL_XML'
    else: pytest.fail('Invalid terminal must fail before admission')


def test_task_diagnostic_normalizes_only_the_authenticated_builder_guard(finished_builder_controls, monkeypatch):
    builder = finished_builder_controls.builder
    monkeypatch.setattr(builder, 'LOADED_SOURCE', (FILE.parents[1] / 'docker/compact-build-resources.py').read_bytes(), raising=False)
    try: builder.require(False, 'Historical builder has an unexpected bind mount or volume')
    except ValueError as error:
        assert retirement.failure_reason_code(error) == 'HISTORICAL_BUILDER_HAS_AN_UNEXPECTED_BIND_MOUNT_OR_VOLUME'
    else: pytest.fail('Invalid builder mount must fail before exclusion')


@pytest.mark.parametrize('finished', [False, True])
def test_task_fixture_source_selects_builder_helpers_only_for_independent_finished_policy(monkeypatch, finished):
    row = {'release': 'ci-344-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    if finished: row['retirement'] = _finished_selection()
    owner = retirement.encoded({'containerId': '1' * 64}); cleanup = retirement.encoded({'status': 'STOPPED'})
    keeper = {**{key: row[key] for key in ('release', 'commit', 'sourceSha256')}, 'token': 'c' * 10,
              'ownerSha256': retirement.digest(owner), 'cleanupSha256': retirement.digest(cleanup),
              'preRuntimeAbsence': {'toolsSha256': 'e' * 64}}
    calls = []
    def source(*args, **options):
        calls.append((args, options)); return {'fixed': True}
    native = SimpleNamespace(MAX_CONTROL=1024, decode=json.loads, fixture_owner_projection=lambda value: value,
        source_proof=source, capture_fixture=lambda *_args, **_options: None,
        held_file=lambda _root, path, _limit: nullcontext((io.BytesIO(owner if path.name == 'compact-fixtures-owner.json' else cleanup), [])))
    descriptor = {'containerId': '2' * 64}
    def preserve(historical, _helpers):
        assert historical['finishedOutputsPolicy'] == retirement.FINISHED_BATCH
        assert historical['preparedToolsSha256'] == keeper['preRuntimeAbsence']['toolsSha256']
        return descriptor
    monkeypatch.setattr(retirement, 'finished_preserved_builder', preserve)
    value = {'candidates': [row], 'identity': {'executionLocation': 'ECS'}}
    result = retirement.task_fixture_candidates(value, [keeper], {
        'retire-failed-native-jar-duplicates.py': native, 'compact-build-resources.py': object()})
    assert calls[0][1] == {'canonical_jar': True, 'failed_native': True, **(
        {'pre_runtime_recipe': row['retirement']['publicationRecipe'], 'builder_helpers': True}
        if finished else {'database_verification': True})}
    if finished: assert result[0]['preservedBuilder'] == descriptor
    else: assert 'preservedBuilder' not in result[0] and 'finishedOutputsPolicy' not in result[0]['historical']


def test_historical_batch_is_exactly_fifteen_and_never_changes_old_task_selection():
    targets, manifests, metadata = retirement.batch_configuration(retirement.HISTORICAL_BATCH)
    assert {int(tag.split('-')[1]) for tag in targets} == {
        154, 160, 162, 166, 168, 173, 187, 188, 189, 195, 198, 201, 204, 223, 224}
    assert set(targets) == set(manifests) == set(metadata) and set(metadata.values()) == {None}
    for tag, row in retirement.HISTORICAL_ORIGINALS.items():
        assert targets[tag] == (row['inode'], row['commit']) and row['inode'] > 0
        assert manifests[tag] == row['backupManifestSha256']
        assert all(retirement.SHA.fullmatch(row[key]) for key in row if key.endswith('Sha256'))
    for number in (132, 134, 137, 139, 141, 143, 145, 156, 182, 117, 266):
        with pytest.raises(ValueError, match='CLOSED_BATCH_TARGET_REQUIRED'):
            retirement.data_path(f'ci-{number}-' + 'a' * 12, retirement.HISTORICAL_BATCH)
    with pytest.raises(ValueError, match='ONLY_EARLIER_TASK_FAILED_BUILDS_ALLOWED'):
        retirement.task_numbers('224', 400)


@pytest.fixture
def historical_documents(tmp_path, monkeypatch):
    release = next(iter(retirement.HISTORICAL_ORIGINALS)); original = dict(retirement.HISTORICAL_ORIGINALS[release])
    original['action'] = 'verify'
    monkeypatch.setitem(retirement.HISTORICAL_ORIGINALS, release, original)
    current = 'ci-400-' + 'f' * 12
    controls = tmp_path / 'inbox' / current / 'historical-derived-controls'
    (controls / release).mkdir(parents=True)
    authorization = b'fixed synthetic user authorization'
    (controls / 'authorization.json').write_bytes(authorization)
    monkeypatch.setattr(retirement, 'HISTORICAL_AUTHORIZATION_SHA256', retirement.digest(authorization))
    build = controls / release / 'build.xml'; build.write_bytes(_task_flow_xml(original))
    context = {'release': release, 'commit': original['commit']}
    names = ('script/jenkins/prepare-compact-fixtures.py', 'script/schema/compact_migration_runtime.py',
             'docs/database/compact-schema-contract.json')
    source = tmp_path / 'inbox' / release / 'source.tar.gz'; source.parent.mkdir()
    members = [(names[0], b'# synthetic producer'), (names[1], b'# synthetic schema runtime'),
               (names[2], retirement.encoded({'sourceTables': [f'table_{index}' for index in range(131)]}))]
    def archive(*, commit=None, entries=None, linked=False):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz', pax_headers={'comment': commit or original['commit']}) as output:
            for index, (name, body) in enumerate(members if entries is None else entries):
                item = tarfile.TarInfo(name); item.size = len(body)
                if linked and index == 0: item.type = tarfile.SYMTYPE; item.linkname = '/not-a-producer'; item.size = 0
                output.addfile(item, io.BytesIO(body))
        source.write_bytes(data.getvalue()); original['sourceSha256'] = retirement.digest(data.getvalue())
    def refresh():
        original['buildXmlSha256'] = retirement.digest(build.read_bytes())
        context['sourceSha256'] = original['sourceSha256']
        raw = retirement.encoded(context); (controls / release / 'release.json').write_bytes(raw)
        original['releaseSha256'] = retirement.digest(raw)
    archive(); refresh()
    monkeypatch.setattr(retirement, 'ROOT', tmp_path)
    monkeypatch.setattr(retirement, 'read', lambda path, maximum=0: Path(path).read_bytes())
    def check():
        return retirement.historical_originals(release, current, original)
    return SimpleNamespace(release=release, original=original, current=current, controls=controls, build=build,
                           source=source, members=members, context=context, archive=archive, refresh=refresh, check=check)


@pytest.mark.parametrize('action', ['verify', 'verify-runtime'])
@pytest.mark.parametrize('terminal', ['FAILURE', 'ABORTED'])
def test_historical_originals_bind_the_actual_stopped_producer_without_requiring_invented_public_cleanup(historical_documents, action, terminal):
    case = historical_documents
    case.original['action'] = action
    case.build.write_bytes(case.build.read_bytes().replace(b'<value>verify</value>', f'<value>{action}</value>'.encode()))
    case.build.write_bytes(case.build.read_bytes().replace(b'<result>FAILURE</result>', f'<result>{terminal}</result>'.encode()))
    case.refresh()
    proof = case.check()
    assert proof == {key: case.original[key] for key in ('buildXmlSha256', 'releaseSha256')} | {
        'authorizationSha256': retirement.HISTORICAL_AUTHORIZATION_SHA256}
    assert not (case.controls / case.release / 'fixture-cleanup.json').exists()


@pytest.mark.parametrize('damage', ['authorization', 'build-bytes', 'release-bytes', 'source-bytes',
    'source-commit', 'missing-producer', 'duplicate-producer', 'linked-producer', 'table-contract',
    'release-context', 'owner', 'cleanup', 'backup'])
def test_historical_originals_reject_drift_and_incomplete_producer(historical_documents, damage):
    case = historical_documents
    if damage == 'authorization': (case.controls / 'authorization.json').write_bytes(b'other approval')
    elif damage == 'build-bytes': case.build.write_bytes(case.build.read_bytes() + b' ')
    elif damage == 'release-bytes': (case.controls / case.release / 'release.json').write_bytes(b'{}')
    elif damage == 'source-bytes': case.source.write_bytes(b'other source')
    elif damage in ('owner', 'cleanup', 'backup'):
        keeper = dict(case.original)
        keeper[{'owner': 'ownerSha256', 'cleanup': 'cleanupSha256', 'backup': 'backupManifestSha256'}[damage]] = '0' * 64
        with pytest.raises(ValueError, match='HISTORICAL_KEEPER_IDENTITY_CHANGED'):
            retirement.historical_originals(case.release, case.current, keeper)
        return
    elif damage == 'release-context': case.context['commit'] = '0' * 40; case.refresh()
    else:
        if damage == 'source-commit': case.archive(commit='0' * 40)
        elif damage == 'missing-producer': case.archive(entries=case.members[1:])
        elif damage == 'duplicate-producer': case.archive(entries=[*case.members, case.members[0]])
        elif damage == 'linked-producer': case.archive(linked=True)
        else: case.archive(entries=[*case.members[:2], (case.members[2][0], b'{"sourceTables":[]}')])
        case.refresh()
    with pytest.raises(ValueError): case.check()


@pytest.mark.parametrize('damage', ['running', 'success', 'unfinished', 'execution', 'action', 'scope', 'commit',
    'production', 'duplicate-parameter', 'doctype', 'duplicate-result'])
def test_historical_terminal_refuses_nonterminal_or_changed_original_contract(historical_documents, damage):
    case = historical_documents
    root = ET.fromstring(case.build.read_bytes())
    if damage in ('running', 'success'): root.find('result').text = 'RUNNING' if damage == 'running' else 'SUCCESS'
    elif damage == 'unfinished': root.find('completed').text = 'false'
    elif damage == 'execution': root.find('execution/done').text = 'false'
    elif damage == 'duplicate-result': ET.SubElement(root, 'result').text = 'FAILURE'
    elif damage == 'duplicate-parameter':
        params = root.find('./actions/hudson.model.ParametersAction/parameters')
        params.append(ET.fromstring(ET.tostring(params[0])))
    elif damage != 'doctype':
        field = {'action': 'ACTION', 'scope': 'DOORHANDLE_CI_SCOPE', 'commit': 'TRUSTED_COMMIT',
                 'production': 'PRODUCTION_RELEASE_ENABLED'}[damage]
        next(item for item in root.findall('./actions/hudson.model.ParametersAction/parameters/*')
             if item.findtext('name') == field).find('value').text = 'other'
    raw = ET.tostring(root)
    case.build.write_bytes((b'<!DOCTYPE flow-build []>' if damage == 'doctype' else b'') + raw)
    case.refresh()
    with pytest.raises(ValueError): case.check()


def test_historical_policy_stages_only_its_closed_batch_before_generic_cleanup():
    pipeline = (FILE.parent / 'pipeline.ps1').read_text(encoding='utf-8-sig')
    branch = pipeline.split("if ($nativeRetentionPolicy -ceq 'DerivedMysqlHistorical15') {", 1)[1].split('\n    }', 1)[0]
    assert '-Mode Maintenance -PrepareOnly ' in branch and 'return' in branch
    assert '-FailedBuildNumbers' not in branch and '$failedNativeBuildNumber -cne' in branch
    wrapper = (FILE.parent / 'retire-derived-mysql-data.ps1').read_text(encoding='utf-8-sig')
    assert "DerivedMysqlHistorical15=@{batch='derived-mysql-historical-15-v1';count=15}" in wrapper
    assert wrapper.index("'stage-historical-derived-custody.ps1'") < wrapper.index("plan $binding")
    for name in ('Jenkinsfile.ecs-monolith', 'script/jenkins/configure-local.groovy'):
        assert "'DerivedMysqlHistorical15'" in (FILE.parents[2] / name).read_text(encoding='utf-8-sig')


@pytest.mark.parametrize('gate', ['complete-local-first', 'closed-paths', 'retained-binaries',
    'original-digests', 'private-remote', 'no-delete'])
def test_historical_custody_staging_preserves_existing_original_formats_and_private_boundary(gate):
    source = (FILE.parent / 'stage-historical-derived-custody.ps1').read_text(encoding='utf-8-sig')
    if gate == 'complete-local-first':
        assert source.index('foreach($target in $manifest.targets)') < source.index('$remote=') < source.index('& ssh.exe')
        assert 'foreach($entry in $custody.files)' in source and 'Assert-HistoricalDigest "$folder/$name"' in source
    elif gate == 'closed-paths':
        declaration = re.search(r'\$releases=@\((.*?)\n\)', source, re.DOTALL)
        assert declaration and set(ast.literal_eval('(' + declaration[1] + ')')) == set(retirement.HISTORICAL_ORIGINALS)
        assert "$project='D:/AI/lunwen1/DoorHandleCatch'" in source
        assert 'historical-derived-mysql-15-manifest.json' in source and 'ReparsePoint' in source
        assert "@('.','..')" in source and 'Assert-HistoricalExactPath $target.custodyManifest' in source
    elif gate == 'retained-binaries':
        assert "if($name -cin @('application.jar','source.tar.gz')){continue}" in source
        assert "'ci-204-collaboration-raw'" in source and "'sha256-manifest.json'" in source
        assert "-ceq 'build.xml,release.json'" in source
    elif gate == 'original-digests':
        assert "$custody.buildXmlSha256" in source and 'The original terminal XML bindings disagree.' in source
        assert retirement.HISTORICAL_AUTHORIZATION_SHA256 in source
        assert 'Get-FileHash -LiteralPath $Path -Algorithm SHA256' in source and '$entry.bytes -eq $file.bytes' in source
    elif gate == 'private-remote':
        assert 'StrictHostKeyChecking=yes' in source and 'HostKeyAlias=doorhandle-bj' in source
        assert retirement.MACHINE in source and 'test "$(id -u)" = 1000' in source
        assert 'mkdir -m 700' in source and 'chmod 600' in source and "test ! -L '$destinationPath'" in source
        assert "$env:NATIVE_RETENTION_POLICY -ceq 'DerivedMysqlHistorical15'" in source
    else:
        assert 'Remove-Item' not in source and 'rm -' not in source and 'sudo' not in source
        assert 'fixture-cleanup.json' not in source and 'Set-Content' not in source
        assert 'authorization.json' in source and 'sourceDump' not in source


@pytest.fixture
def completed_binary_attempt(tmp_path, monkeypatch):
    """Synthetic prior failed operation, not a real maintenance receipt copy."""
    tag = 'ci-383-5400127dd813'; attempt = 'ci-385-74a0f42e52f3'
    approved = dict(retirement.FINISHED_DB_CONTINUATIONS[tag])
    row = {'release': tag, 'commit': '5' * 40, 'sourceSha256': 'a' * 64,
           'controls': {'synthetic': True}, 'retirement': {**_finished_selection(), 'completedAttempt': attempt}}
    binding = {'tag': 'ci-390-' + 'f' * 12}
    original = tmp_path / 'inbox' / attempt
    directory = original / 'derived-failed-mysql-retirement'
    copy = 'verification/' + tag + '/checkout/work/compact-fixtures/candidate-app.jar'
    canonical = 'inbox/' + tag + '/application.jar'
    source = b'fixed synthetic maintenance source archive'
    approved['sourceSha256'] = retirement.digest(source)
    selection = {**row, 'retirement': {key: value for key, value in row['retirement'].items() if key != 'completedAttempt'}}
    request = {'candidates': [selection], 'builds': ['383'], 'current': {'release': attempt,
        'commit': approved['commit'], 'sourceSha256': approved['sourceSha256']}}
    plan = {'roots': {tag: [*_finished_selection()['dataIdentity'], stat.S_IFDIR | 0o700, 999, 1000]},
            'jarTargets': [{'path': copy}, {'path': canonical}]}
    retired = [{'path': copy, 'allocatedBytes': 4096}, {'path': canonical, 'allocatedBytes': 4096}]
    receipt = {'status': 'FAILED_OR_UNKNOWN', 'removed': [], 'jarRetirements': retired}
    terminal = '<flow-build><result>FAILURE</result><completed>true</completed><execution><done>true</done></execution></flow-build>'
    paths = {'sourceSha256': original / 'cleanup-source.tar.gz', 'requestSha256': directory / 'request.json',
        'planSha256': directory / 'plan-private.json', 'receiptSha256': directory / 'receipt.json',
        'journalSha256': directory / 'jar-journal.jsonl', 'buildXmlSha256': tmp_path / 'inbox' / binding['tag'] /
            'failed-mysql-data-controls' / tag / 'completed-maintenance-build.xml'}
    state = SimpleNamespace(row=row, binding=binding, approved=approved, paths=paths,
        request=request, plan=plan, receipt=receipt, terminal=terminal, root=tmp_path, journal=None)
    def refresh():
        raw = {'sourceSha256': source, 'requestSha256': retirement.encoded(request),
               'planSha256': retirement.encoded(plan), 'buildXmlSha256': state.terminal.encode()}
        approved.update({key: retirement.digest(body) for key, body in raw.items()})
        receipt.update(requestSha256=approved['requestSha256'], planSha256=approved['planSha256'])
        journal = [{'phase': 'STARTED', 'planSha256': approved['planSha256'], 'requestSha256': approved['requestSha256']}]
        for item in retired: journal.extend([{'phase': 'DELETE_STARTED', 'path': item['path']}, {'phase': 'DELETE_FINISHED', **item}])
        journal.append({'phase': 'FINISHED', 'deletedFiles': 2})
        state.journal = journal
        raw.update(receiptSha256=retirement.encoded(receipt),
                   journalSha256=b'\n'.join(retirement.encoded(event) for event in journal) + b'\n')
        for key, body in raw.items():
            approved[key] = retirement.digest(body); paths[key].parent.mkdir(parents=True, exist_ok=True); paths[key].write_bytes(body)
    state.refresh = refresh; refresh()
    monkeypatch.setattr(retirement, 'ROOT', tmp_path)
    monkeypatch.setattr(retirement, 'FINISHED_DB_CONTINUATIONS', {tag: approved})
    def read(path, maximum=2 * retirement.MIB):
        assert path in paths.values() and maximum == 8 * retirement.MIB
        return path.read_bytes()
    monkeypatch.setattr(retirement, 'read', read)
    return state


@pytest.mark.parametrize('tampered', [None, 'sourceSha256', 'requestSha256', 'planSha256',
                                    'receiptSha256', 'journalSha256', 'buildXmlSha256'])
def test_completed_binary_continuation_binds_every_original_before_omitting_jars(completed_binary_attempt, tampered):
    state = completed_binary_attempt
    if tampered: state.paths[tampered].write_bytes(b'changed preserved original')
    if tampered:
        with pytest.raises(ValueError, match='ORIGINAL_CONTINUATION_EVIDENCE_CHANGED'):
            retirement.finished_completed_binaries(state.binding, state.row)
    else:
        proof = retirement.finished_completed_binaries(state.binding, state.row)
        assert proof['completedAttempt'] == state.approved['attempt'] and proof['alreadyRetiredJarBytes'] == 8192
        native = SimpleNamespace(describe_duplicate=lambda *_: pytest.fail('Never reconstruct a retired duplicate'),
                                 describe_canonical_jar=lambda *_a, **_k: pytest.fail('Never reconstruct a retired canonical JAR'))
        assert retirement.finished_jar_targets({'candidates': [state.row]}, {'retire-failed-native-jar-duplicates.py': native}) == []


@pytest.mark.parametrize('damage', ['terminal', 'selection', 'data-inode', 'complete', 'already-removed',
                                   'journal-incomplete', 'journal-path', 'jar-reappeared', 'jar-symlink'])
def test_completed_binary_continuation_rejects_wrong_state_even_with_bound_input_bytes(completed_binary_attempt, damage):
    state = completed_binary_attempt
    if damage == 'terminal': state.terminal = state.terminal.replace('FAILURE', 'SUCCESS')
    elif damage == 'selection': state.request['candidates'] = []
    elif damage == 'data-inode': state.plan['roots'][state.row['release']][1] += 1
    elif damage == 'complete': state.receipt['status'] = 'COMPLETE'
    elif damage == 'already-removed': state.receipt['removed'] = [{'status': 'REMOVED'}]
    state.refresh()
    if damage in ('journal-incomplete', 'journal-path'):
        journal = state.journal
        if damage == 'journal-incomplete': journal.pop()
        else: journal[2]['path'] = 'inbox/another/application.jar'
        raw = b'\n'.join(retirement.encoded(event) for event in journal)
        state.paths['journalSha256'].write_bytes(raw); state.approved['journalSha256'] = retirement.digest(raw)
    if damage in ('jar-reappeared', 'jar-symlink'):
        path = state.root / state.plan['jarTargets'][0]['path']; path.parent.mkdir(parents=True)
        if damage == 'jar-reappeared': path.write_bytes(b'new candidate must be protected')
        else: path.symlink_to(state.root / 'missing')
    with pytest.raises(ValueError): retirement.finished_completed_binaries(state.binding, state.row)


@pytest.mark.parametrize('damage', ['another-attempt', 'another-target', 'protected-target'])
def test_partial_finished_recovery_is_one_closed_registered_pair(damage):
    row = {'release': 'ci-383-5400127dd813', 'retirement': {**_finished_selection(), 'completedAttempt': 'ci-385-74a0f42e52f3'}}
    if damage == 'another-attempt': row['retirement']['completedAttempt'] = 'ci-384-' + 'a' * 12
    elif damage == 'another-target': row['release'] = 'ci-381-' + 'a' * 12
    else: row['release'] = 'ci-266-' + 'a' * 12
    with pytest.raises(ValueError, match='UNREGISTERED_FINISHED_DB_CONTINUATION'): retirement.validate_finished_selection(row)


def test_partial_recovery_controller_keeps_failed_terminal_and_counts_only_new_deletions():
    source = TASK_DIAGNOSTIC_CONTROLLER
    assert "$candidate.retirement.completedAttempt -ceq 'ci-385-74a0f42e52f3'" in source
    assert "$prior.result -ceq 'FAILURE'" in source and "$prior.executionDone -eq $true" in source
    assert "file='completed-maintenance-build.xml'" in source
    assert source.index("file='completed-maintenance-build.xml'") < source.index('& scp.exe')
    assert 'else{$expectedNewJarCount+=2}' in source and '$count=$expectedNewJarCount' in source
    assert '@($plan.jarTargets).Count -eq $expectedNewJarCount' in source
    assert '@($receipt.completedBinaryRetirements).Count -eq 1' in source


def test_empty_new_binary_plan_writes_zero_deletion_journal_without_native_calls(tmp_path):
    receipt = {'planSha256': 'a' * 64, 'requestSha256': 'b' * 64, 'jarRetirements': []}
    retirement.finished_remove_jars(tmp_path, [], {'retire-failed-native-jar-duplicates.py': SimpleNamespace()},
        lambda: pytest.fail('There is no new JAR operation'), receipt)
    events = [json.loads(line) for line in (tmp_path / 'jar-journal.jsonl').read_text().splitlines()]
    assert events == [{'phase': 'STARTED', 'planSha256': 'a' * 64, 'requestSha256': 'b' * 64},
                      {'phase': 'FINISHED', 'deletedFiles': 0}]
    assert receipt['jarRetirements'] == []


@pytest.mark.parametrize('guard', ['LIVE_PROCESS_METADATA_DISAPPEARED', 'PROCESS_DESCRIPTOR_CHANGED_DURING_SCAN'])
def test_authenticated_direct_process_guard_survives_older_wrapper_codec(finished_builder_controls, monkeypatch, guard):
    case = finished_builder_controls
    # The loaded helper contains these direct ValueError literals. This reproduces
    # the old diagnostic codec's omission, without asserting which one hit #385.
    def reject(*_args, **_kwargs): raise ValueError(guard)
    monkeypatch.setattr(case.cleanup, 'quiescent', reject)
    try:
        case.native.recent_fixture_references(retirement.ROOT,
            {'historical': case.historical, 'fixture': case.fixture}, case.cleanup, case.builder)
    except ValueError as error:
        # Synthetic rejection must carry the authenticated helper source just as
        # the real process scanner's globals do.
        reject.__globals__['LOADED_SOURCE'] = case.cleanup.LOADED_SOURCE
        try: assert retirement.failure_reason_code(error) == 'HISTORICAL_OBJECTS_NOT_QUIESCENT_' + guard
        finally: reject.__globals__.pop('LOADED_SOURCE', None)
    else: pytest.fail('The real rejection must remain a failure')


@pytest.fixture
def pre_driver_reports(tmp_path, monkeypatch):
    """Five synthetic lifecycle originals; no real environment or SQL is copied."""
    module_spec = importlib.util.spec_from_file_location('pre_driver_report_verifier', FILE.with_name('verify-remote.py'))
    verifier = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(verifier)
    tool_spec = importlib.util.spec_from_file_location('pre_driver_actual_tool_producer', FILE.with_name('ecs-tool-runtime.py'))
    tool_producer = importlib.util.module_from_spec(tool_spec); tool_spec.loader.exec_module(tool_producer)
    root = tmp_path / 'ci'
    legacy = {'release': 'ci-387-d0b540e67ab0', 'commit': 'd0b540e67ab0f17a4539b2f69d557b7b73846933',
              'sourceSha256': '8e2c062f3c8194b334c0fd5be6f449cf606a89b2e8f11d808f8ed54179a70534'}
    state = SimpleNamespace(root=root, verifier=verifier, raw_change=None, omitted=None, catalog_omit=None)
    def prepare(modern):
        context = {'release': 'ci-400-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64} if modern else legacy.copy()
        row = {**context, 'retirement': {'policy': retirement.FINISHED_BATCH}}
        identity = {'instanceId': retirement.INSTANCE, 'machineId': retirement.MACHINE, 'executionLocation': 'ECS'}
        shared = {**context, 'identity': identity}
        # Use the real public producer, not a guessed shared report schema.
        # These files are synthetic; evidence() never starts Docker or a tool.
        tool_folder = root / 'synthetic-tool-originals' / row['release']
        (tool_folder / 'receipts').mkdir(parents=True)
        tool_value = {**shared, 'directory': str(tool_folder), 'token': 'e' * 24,
                      'images': {name: 'sha256:' + digit * 64 for name, digit in
                                 [('maven', '5'), ('node', '6'), ('python', '7')]}}
        tool_producer.write_json(tool_folder / 'manifest.json', tool_value)
        manifest_sha = tool_producer.digest(tool_folder / 'manifest.json')
        command = {**context, 'kind': 'doorhandle-ecs-tool-command', 'tool': 'java', 'containerId': '8' * 64,
                   'argumentsSha256': '9' * 64, 'status': 'EXITED', 'exitCode': 0,
                   'runtimeLimits': tool_producer.runtime_limits('java'),
                   'cleanup': {'containerId': '8' * 64, 'image': tool_value['images']['maven'],
                               'pid': 0, 'exitCode': 0, 'removed': True}}
        tool_producer.write_json(tool_folder / 'receipts' / ('doorhandle-ci-tool-' + 'e' * 24 + '-' + 'f' * 12 + '.json'), command)
        tools = tool_producer.evidence(tool_value, {'status': 'STOPPED', 'remaining': [], 'containers': [],
                                                   'release': row['release'], 'manifestSha256': manifest_sha})
        fixture = {**shared, 'version': 1, 'kind': 'doorhandle-fixture-runtime', 'containerId': '1' * 64,
                   'status': 'STOPPED', 'watchStopped': True, 'stopScope': 'OWNED_ATTEMPT_ONLY'}
        reports = {'reports/tool-runtime.json': tools, 'reports/fixture-runtime.json': fixture}
        receipt = {'schema': 1, 'kind': 'doorhandle-ecs-ci', **shared, 'attempt': 'c' * 32, 'scope': 'mysql',
            'status': 'FAILED', 'verificationExitCode': None, 'lifecycle': 'managed-outside-jenkins',
            'fixtureReadinessValidated': True, 'fixtureManifestProvided': True, 'errorType': 'ValueError',
            'fixtureRuntime': {'required': True, 'containerId': '1' * 64},
            'toolRuntime': {'manifestSha256': manifest_sha, 'cleanupStatus': 'STOPPED'}}
        for field, name, number in [('middlewareFixture', 'middleware', '2'),
                                    ('observabilityFixture', 'observability', '3'), ('redisFixture', 'redis', '4')]:
            reports['reports/' + name + '-fixture.json'] = {**shared, 'kind': 'doorhandle-' + name + '-fixture',
                'status': 'STOPPED', 'cleanupConfirmed': True,
                **({'schemaVersion': 1, 'containers': []} if name == 'observability'
                   else {'version': 1, 'containerId': number * 64})}
            receipt[field] = {'required': True, 'status': 'STOPPED', 'cleanupConfirmed': True,
                              **({} if name == 'observability' else {'containerId': number * 64})}
        reports['reports/observability-fixture.json']['cleanupErrors'] = []
        # Metrics acceptance remains FAILED; resource closure must not turn it into PASS.
        reports['reports/observability-fixture.json']['metricsAcceptance'] = 'FAILED'
        if modern:
            receipt['driverStart'] = {'requested': False, 'blockedBy': 'FIXTURE_MEMORY_ADMISSION'}
            receipt['fixtureRuntime']['memoryAdmission'] = {'capacityVerdict': 'REJECTED',
                'hostMemoryAvailableBytes': 100, 'requiredAvailableMemoryBytes': 101, 'memoryShortfallBytes': 1,
                'creditPolicy': 'OWNED_ANONYMOUS_ONLY', 'fullAcceptanceResourcesMeasured': False}
        else:
            source = 'script/jenkins/prepare-compact-fixtures.py'
            receipt['failureLocation'] = {'source': source, 'line': 1859}
            receipt['failureLocations'] = [{'source': source, 'line': 1859, 'function': 'admit'},
                                           {'source': source, 'line': 817, 'function': 'require'}]
        attempt = root / 'verification' / row['release']; inbox = root / 'inbox' / row['release']
        (attempt / '.verification-claimed').mkdir(parents=True); inbox.mkdir(parents=True)
        checkout = attempt / 'checkout'; (checkout / 'work/ci-evidence').mkdir(parents=True)
        claim = {'schema': 1, 'kind': 'doorhandle-ci-claim', **shared, 'attempt': receipt['attempt'], 'scope': 'mysql'}
        state.row, state.receipt, state.reports, state.claim = row, receipt, reports, claim
        state.attempt, state.inbox, state.checkout = attempt, inbox, checkout
        state.fixture_container_id = '1' * 64
    def refresh():
        bodies = {name: retirement.encoded(value) for name, value in state.reports.items()}
        state.receipt['reportFiles'] = [{'path': name, 'bytes': len(body), 'sha256': retirement.digest(body)}
            for name, body in bodies.items() if name != state.catalog_omit]
        for field, name in [('toolRuntime', 'tool-runtime'), ('middlewareFixture', 'middleware-fixture'),
                            ('observabilityFixture', 'observability-fixture'), ('redisFixture', 'redis-fixture')]:
            state.receipt[field]['evidenceSha256'] = retirement.digest(bodies['reports/' + name + '.json'])
        raw = retirement.encoded(state.receipt)
        (state.attempt / 'verification-receipt.json').write_bytes(raw)
        (state.attempt / '.verification-claimed/claim.json').write_bytes(retirement.encoded(state.claim))
        with tarfile.open(state.inbox / 'verification-evidence.tar.gz', 'w:gz') as archive:
            for name, body in [('verification-receipt.json', raw), *bodies.items()]:
                if name == state.omitted: continue
                if name == state.raw_change: body += b' '
                member = tarfile.TarInfo(name); member.size = len(body); archive.addfile(member, io.BytesIO(body))
        (state.inbox / 'verification-evidence.tar.gz').chmod(0o600)
    state.prepare = prepare; state.refresh = refresh
    monkeypatch.setattr(retirement, 'ROOT', root)
    return state


@pytest.mark.parametrize('modern', [False, True])
@pytest.mark.parametrize('metadata_only', [False, True])
def test_finished_pre_driver_rejection_preserves_failed_null_and_all_lifecycle_originals(pre_driver_reports, modern, metadata_only):
    case = pre_driver_reports; case.prepare(modern); case.refresh()
    tools = case.reports['reports/tool-runtime.json']
    assert 'identity' not in tools and tools['schema'] == 1 and len(tools['commands']) == 1
    assert tools['manifestSha256'] == case.receipt['toolRuntime']['manifestSha256']
    assert 'containerId' not in case.reports['reports/observability-fixture.json']
    before = (case.attempt / 'verification-receipt.json').read_bytes()
    result = retirement.task_reports(case.row, case.verifier, metadata_only=metadata_only,
                                     fixture_container_id=case.fixture_container_id)
    assert result['verificationStatus'] == 'FAILED' and result['verificationExitCode'] is None
    assert result['reportFiles'] == 5 and result['driverStarted'] is False
    assert result['failureStage'] == 'FIXTURE_MEMORY_ADMISSION'
    assert (case.attempt / 'verification-receipt.json').read_bytes() == before
    assert not (case.checkout / 'driver.log').exists()


@pytest.mark.parametrize('damage', [
    'old-policy', 'legacy-source', 'legacy-location', 'legacy-memory-admitted', 'unknown-null',
    'driver-requested', 'other-blocker', 'admitted', 'shortfall-arithmetic', 'boolean-memory',
    'driver-file', 'driver-symlink', 'business-receipt', 'missing-report', 'extra-report',
    'changed-original', 'missing-original', 'report-context', 'tools-running', 'tools-remaining',
    'watch-running', 'watch-scope', 'owner-id', 'watch-id', 'middleware-running',
    'redis-running', 'observability-running', 'observability-errors',
])
def test_finished_pre_driver_path_rejects_unknown_execution_or_unclosed_originals(pre_driver_reports, damage):
    case = pre_driver_reports; case.prepare(not damage.startswith('legacy-'))
    receipt, reports = case.receipt, case.reports
    if damage == 'old-policy': case.row.pop('retirement')
    elif damage == 'legacy-source': case.row['sourceSha256'] = receipt['sourceSha256'] = case.claim['sourceSha256'] = 'f' * 64
    elif damage == 'legacy-location': receipt['failureLocation']['line'] = 1860
    elif damage == 'legacy-memory-admitted': receipt['fixtureRuntime']['memoryAdmission'] = {'capacityVerdict': 'ADMITTED'}
    elif damage == 'unknown-null': receipt.pop('driverStart')
    elif damage == 'driver-requested': receipt['driverStart'] = {'requested': True}
    elif damage == 'other-blocker': receipt['driverStart']['blockedBy'] = 'UNKNOWN'
    elif damage == 'admitted': receipt['fixtureRuntime']['memoryAdmission']['capacityVerdict'] = 'ADMITTED'
    elif damage == 'shortfall-arithmetic': receipt['fixtureRuntime']['memoryAdmission']['memoryShortfallBytes'] = 2
    elif damage == 'boolean-memory': receipt['fixtureRuntime']['memoryAdmission']['memoryShortfallBytes'] = True
    elif damage == 'driver-file': (case.checkout / 'driver.log').write_bytes(b'Popen could have been requested')
    elif damage == 'driver-symlink': (case.checkout / 'driver.log').symlink_to(case.root / 'absent')
    elif damage == 'business-receipt': (case.checkout / 'work/ci-evidence/receipt.json').write_text('{}')
    elif damage == 'missing-report': case.catalog_omit = 'reports/fixture-runtime.json'
    elif damage == 'extra-report': reports['driver.log'] = {'unexpected': True}
    elif damage == 'changed-original': case.raw_change = 'reports/fixture-runtime.json'
    elif damage == 'missing-original': case.omitted = 'reports/fixture-runtime.json'
    elif damage == 'report-context': reports['reports/fixture-runtime.json']['commit'] = 'f' * 40
    elif damage == 'tools-running': reports['reports/tool-runtime.json']['cleanup']['status'] = 'RUNNING'
    elif damage == 'tools-remaining': reports['reports/tool-runtime.json']['cleanup']['remaining'] = ['owned-tool']
    elif damage == 'watch-running': reports['reports/fixture-runtime.json']['watchStopped'] = False
    elif damage == 'watch-scope': reports['reports/fixture-runtime.json']['stopScope'] = 'UNKNOWN'
    elif damage == 'owner-id': case.fixture_container_id = 'f' * 64
    elif damage == 'watch-id': reports['reports/fixture-runtime.json']['containerId'] = 'f' * 64
    elif damage.endswith('-running'): reports['reports/' + damage.removesuffix('-running') + '-fixture.json']['status'] = 'RUNNING'
    else: reports['reports/observability-fixture.json']['cleanupErrors'] = ['unresolved']
    case.refresh()
    # Root's metadata-only recheck still has to read these five bounded originals.
    with pytest.raises((ValueError, case.verifier.VerificationError)):
        retirement.task_reports(case.row, case.verifier, metadata_only=True, fixture_container_id=case.fixture_container_id)


@pytest.mark.parametrize('damage', ['release', 'commit', 'sourceSha256', 'manifestSha256',
                                   'cleanup-manifest', 'schema', 'declared-other-identity',
                                   'fixture-identity', 'middleware-identity', 'observability-identity',
                                   'redis-identity'])
def test_real_tool_report_shape_does_not_weaken_its_source_or_other_reports_host_binding(pre_driver_reports, damage):
    case = pre_driver_reports; case.prepare(False)
    tools = case.reports['reports/tool-runtime.json']
    assert 'identity' not in tools
    if damage in ('release', 'commit', 'sourceSha256', 'manifestSha256'): tools[damage] = 'other-source'
    elif damage == 'cleanup-manifest': tools['cleanup']['manifestSha256'] = 'f' * 64
    elif damage == 'schema': tools['schema'] = 2
    elif damage == 'declared-other-identity': tools['identity'] = {'executionLocation': 'OTHER_HOST'}
    else:
        name = damage.removesuffix('-identity')
        path = 'reports/fixture-runtime.json' if name == 'fixture' else 'reports/' + name + '-fixture.json'
        case.reports[path]['identity'] = {'executionLocation': 'OTHER_HOST'}
    # Rebind the synthetic archive/catalog: the semantic gate, not a stale hash,
    # must refuse each inconsistent original.
    case.refresh()
    with pytest.raises((ValueError, case.verifier.VerificationError)):
        retirement.task_reports(case.row, case.verifier, metadata_only=True, fixture_container_id=case.fixture_container_id)
