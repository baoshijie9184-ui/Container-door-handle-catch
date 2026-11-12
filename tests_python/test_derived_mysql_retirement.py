"""Closed, owned test-replica retirement. Executed by Jenkins on ECS only."""
import importlib.util
import json
import os
from pathlib import Path
import stat
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


@pytest.mark.parametrize('request', [
    {'phase': 'inventory', 'batch': retirement.BATCH, 'path': '/var/lib/mysql'},
    {'phase': 'delete-anything', 'batch': retirement.BATCH},
    {'phase': 'inventory', 'batch': 'all-databases'},
])
def test_privileged_worker_refuses_extra_arguments_or_another_operation(root_identity, request):
    with pytest.raises(ValueError):
        retirement.root_worker(request)


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
