"""Execute only on ECS: real SQLite/Chroma fixtures and owned-boundary contracts."""
import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


candidate = load('legacy_candidate_preparation_contract', 'script/jenkins/prepare-legacy-candidate.py')
cutover = load('legacy_native_release_contract', 'script/docker/compact-cutover.py')


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = tmp_path / 'source'; root.mkdir()
    with sqlite3.connect(root / 'opaque.sqlite3') as database:
        database.execute('CREATE TABLE facts(id INTEGER PRIMARY KEY,value TEXT)')
        database.execute("INSERT INTO facts VALUES(1,'opaque fixture')")
    (root / 'index.bin').write_bytes(bytes(range(256)))
    monkeypatch.setattr(candidate, 'source_read_only', lambda _: True)
    monkeypatch.setattr(candidate.os, 'statvfs', lambda _: SimpleNamespace(f_bavail=8 * 1024 ** 3, f_frsize=1))
    return root


def test_online_snapshot_independently_restores_all_files_and_sqlite(source, tmp_path):
    before = candidate.file_inventory(source)
    result = candidate.snapshot_volume(source, tmp_path / 'snapshot', {'instanceId': 'i-test', 'machineId': 'a' * 32}, os.getuid(), os.getgid())
    assert result['status'] == 'RESTORED_VERIFIED' and result['fullVolume'] is True
    assert result['consistency'] == 'ALL_FILES_STABLE_AND_TWO_IDENTICAL_ONLINE_SQLITE_BACKUPS'
    assert candidate.file_inventory(source) == before == candidate.file_inventory(tmp_path / 'snapshot/restored-originals')
    with sqlite3.connect(tmp_path / 'snapshot/data/opaque.sqlite3') as database:
        assert database.execute('SELECT value FROM facts WHERE id=1').fetchone()[0] == 'opaque fixture'


@pytest.mark.parametrize('mutation', ['sqlite-copy', 'source-inventory'])
def test_moving_sources_fail_without_a_completed_receipt(source, tmp_path, monkeypatch, mutation):
    if mutation == 'sqlite-copy':
        original = candidate.sqlite_copy; calls = []
        def changed(origin, target):
            original(origin, target); calls.append(target)
            if len(calls) == 2:
                with sqlite3.connect(target) as database: database.execute("UPDATE facts SET value='different snapshot'")
        monkeypatch.setattr(candidate, 'sqlite_copy', changed)
    else:
        original = candidate.file_inventory; calls = []
        def changed(path):
            result = original(path)
            if path == source:
                calls.append(path)
                if len(calls) == 2: result['index.bin'] = {**result['index.bin'], 'sha256': '0' * 64}
            return result
        monkeypatch.setattr(candidate, 'file_inventory', changed)
    with pytest.raises(ValueError):
        candidate.snapshot_volume(source, tmp_path / 'refused', {}, os.getuid(), os.getgid())
    assert not (tmp_path / 'refused/snapshot-receipt.json').exists()


@pytest.mark.parametrize('kind', ['empty', 'no-sqlite'])
def test_empty_or_unproven_volume_is_not_a_full_cloud_snapshot(tmp_path, monkeypatch, kind):
    root = tmp_path / 'source'; root.mkdir()
    monkeypatch.setattr(candidate, 'source_read_only', lambda _: True)
    if kind == 'no-sqlite': (root / 'ordinary.bin').write_bytes(b'not a database')
    with pytest.raises(ValueError): candidate.snapshot_volume(root, tmp_path / 'refused', {}, os.getuid(), os.getgid())


@pytest.mark.parametrize('mounts', [
    '1 0 0:1 / / rw - overlay overlay rw\n2 1 0:2 / /source rw - ext4 /dev/x rw',
    '1 0 0:1 / / ro - overlay overlay ro',
    '1 0 0:1 / / rw - overlay overlay rw'])
def test_helper_requires_exact_readonly_source_mount(monkeypatch, mounts):
    original = Path.read_text
    monkeypatch.setattr(Path, 'read_text', lambda path, *args, **kwargs: mounts if path == Path('/proc/self/mountinfo') else original(path, *args, **kwargs))
    with pytest.raises(ValueError): candidate.source_read_only(Path('/source'))


def test_helper_accepts_measured_exact_readonly_mount(monkeypatch):
    original = Path.read_text
    mounts = '1 0 0:1 / / rw - overlay overlay rw\n2 1 0:2 / /source ro - ext4 /dev/x rw'
    monkeypatch.setattr(Path, 'read_text', lambda path, *args, **kwargs: mounts if path == Path('/proc/self/mountinfo') else original(path, *args, **kwargs))
    assert candidate.source_read_only(Path('/source')) is True


def helper_row():
    return {'Name': '/owned-helper', 'Image': 'sha256:' + 'a' * 64,
        'Config': {'User': '0:0', 'Entrypoint': ['python'], 'Labels': {candidate.LABEL: 'token', 'io.doorhandle.release': 'tag'}},
        'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False,
            'Memory': 256 * candidate.MIB, 'MemorySwap': 256 * candidate.MIB, 'RestartPolicy': {'Name': 'no'},
            'CapDrop': ['ALL'], 'CapAdd': ['DAC_READ_SEARCH', 'DAC_OVERRIDE', 'CHOWN', 'FOWNER']},
        'Mounts': [{'Type': 'volume', 'Name': 'original-source', 'Destination': '/source', 'RW': False},
                   {'Type': 'bind', 'Source': '/checkout', 'Destination': '/checkout', 'RW': True}]}


@pytest.mark.parametrize('mutation', ['source-rw', 'image', 'user', 'privileged', 'foreign-bind', 'capability'])
def test_cleanup_refuses_changed_helper_before_any_stop(mutation):
    row = copy.deepcopy(helper_row())
    if mutation == 'source-rw': row['Mounts'][0]['RW'] = True
    if mutation == 'image': row['Image'] = 'sha256:' + 'b' * 64
    if mutation == 'user': row['Config']['User'] = '1000:1000'
    if mutation == 'privileged': row['HostConfig']['Privileged'] = True
    if mutation == 'foreign-bind': row['Mounts'][1]['Source'] = '/foreign'
    if mutation == 'capability': row['HostConfig']['CapAdd'].append('SYS_ADMIN')
    with pytest.raises(ValueError): candidate.owned_snapshot_helper(row, token='token', tag='tag', name='owned-helper',
        image='sha256:' + 'a' * 64, volume='original-source', checkout=Path('/checkout'))


def test_materialization_never_overwrites_an_existing_volume(tmp_path):
    source, destination = tmp_path / 'source', tmp_path / 'target'; source.mkdir(); destination.mkdir()
    (source / 'file').write_bytes(b'admitted'); (destination / 'existing').write_bytes(b'keep')
    with pytest.raises(ValueError, match='empty newly-owned'):
        candidate.install_volume(source, destination, os.getuid(), os.getgid())
    assert (destination / 'existing').read_bytes() == b'keep'


def test_file_inventory_rejects_links_without_following_them(tmp_path):
    source = tmp_path / 'source'; source.mkdir(); foreign = tmp_path / 'foreign'; foreign.write_bytes(b'private')
    (source / 'linked').symlink_to(foreign)
    with pytest.raises(ValueError, match='links'): candidate.file_inventory(source)


def test_file_inventory_cannot_silently_omit_an_unreadable_subtree(tmp_path, monkeypatch):
    source = tmp_path / 'source'; source.mkdir()
    def denied(*args, **kwargs):
        kwargs['onerror'](PermissionError('unreadable owned fixture'))
        return iter(())
    monkeypatch.setattr(candidate.os, 'walk', denied)
    with pytest.raises(PermissionError): candidate.file_inventory(source)


@pytest.mark.parametrize('proof', [{}, {'legacyData': {'localMem0SemanticStatus': 'NOT_ACTIVATED_SEMANTIC_NOT_VERIFIED', 'productionPromotionAllowed': False}},
    {'legacyData': {'localMem0SemanticStatus': 'NOT_ACTIVATED_SEMANTIC_NOT_VERIFIED', 'productionPromotionAllowed': True}}])
def test_original_archive_or_fixture_namespace_cannot_admit_a_production_cutover(proof):
    with pytest.raises(ValueError, match='not release-admitted'): cutover.require_native_release(proof)


def test_complete_catalogue_preserves_multiple_real_collections(tmp_path):
    from chromadb import PersistentClient
    from chromadb.config import Settings
    migration = load('legacy_chroma_catalogue_read_contract', 'script/memory/migrate_legacy_stores.py')
    client = PersistentClient(path=str(tmp_path), settings=Settings(anonymized_telemetry=False))
    for name, vector in [('alpha', [1.0, 0.0]), ('beta', [0.0, 1.0])]:
        collection = client.create_collection(name, embedding_function=None)
        collection.add(ids=[name + '-id'], documents=[name], metadatas=[{'source': name, 'title': name}], embeddings=[vector])
    result = candidate.complete_chroma(tmp_path, migration)
    assert {value['name'] for value in result.values()} == {'alpha', 'beta'}
    for value in result.values():
        assert value['recordsSha256'] == candidate.sha(value['records'])
        assert len(value['records']) == 1
        assert next(iter(value['records'].values()))['vectorSha256'] in {
            hashlib.sha256(migration.vector_bytes([1.0, 0.0])).hexdigest(), hashlib.sha256(migration.vector_bytes([0.0, 1.0])).hexdigest()}
    client._system.stop()


def test_nonempty_other_native_collection_cannot_hide_behind_empty_personal_collection():
    before = {'collections': {'personal': {'id': 'p', 'name': 'doorhandle_memories', 'records': {}},
                             'other': {'id': 'o', 'name': 'another_cloud_collection', 'records': {'existing': {'vectorSha256': 'a' * 64}}}},
              'sqlite': {'collections': {'p': {'records': 0}, 'o': {'records': 1}}}}
    with pytest.raises(ValueError, match='Any nonempty'): candidate.require_empty_native_collections(before)


def test_cleanup_uses_label_filter_and_retains_safe_failure_summary(tmp_path, monkeypatch):
    import json
    tag, commit, source_sha = 'ci-11-' + 'a' * 12, 'a' * 40, 'b' * 64
    checkout = tmp_path / 'verification' / tag / 'checkout'; work = checkout / 'work/legacy-candidate'
    work.mkdir(parents=True)
    identity = {'instanceId': 'i-fixture', 'machineId': 'c' * 32}
    candidate.write(work / 'owner.json', {'identity': identity, 'checkout': str(checkout), 'release': tag,
        'commit': commit, 'sourceSha256': source_sha, 'token': 'fixed-token', 'pythonImage': 'sha256:' + 'd' * 64, 'sources': {}})
    candidate.write(work / 'public-summary.json', {'status': 'FAILED', 'errorType': 'ValueError'})
    monkeypatch.setattr(candidate, 'module', lambda *args: SimpleNamespace(ecs_identity=lambda *values: identity))
    calls = []
    def docker(arguments, **kwargs):
        calls.append(arguments)
        assert arguments[:5] == ['docker', 'ps', '-aq', '--no-trunc', '--filter']
        assert arguments[5] == 'label=' + candidate.LABEL + '=fixed-token'
        return b''
    monkeypatch.setattr(candidate.subprocess, 'check_output', docker)
    result = candidate.cleanup(SimpleNamespace(root=str(tmp_path), tag=tag, commit=commit, source_sha256=source_sha,
        instance_id=identity['instanceId'], machine_id=identity['machineId']))
    assert len(calls) == 2 and result['status'] == 'STOPPED' and result['sourceVolumesPreserved'] is True
    assert result['hasPublicSummary'] is True and result['publicSummarySha256'] == candidate.digest(work / 'public-summary.json')
    assert json.loads((work / 'public-summary.json').read_text()) == {'status': 'FAILED', 'errorType': 'ValueError'}


def test_cleanup_without_owner_never_queries_or_stops_a_container(tmp_path, monkeypatch):
    tag = 'ci-12-' + 'a' * 12
    (tmp_path / 'verification' / tag / 'checkout').mkdir(parents=True)
    identity = {'instanceId': 'i-fixture', 'machineId': 'c' * 32}
    monkeypatch.setattr(candidate, 'module', lambda *args: SimpleNamespace(ecs_identity=lambda *values: identity))
    monkeypatch.setattr(candidate.subprocess, 'check_output', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('no Docker action without ownership')))
    result = candidate.cleanup(SimpleNamespace(root=str(tmp_path), tag=tag, commit='a' * 40, source_sha256='b' * 64,
        instance_id=identity['instanceId'], machine_id=identity['machineId']))
    assert result['status'] == 'NO_RESOURCES' and result['sourceVolumesPreserved'] is True and result['hasPublicSummary'] is False
