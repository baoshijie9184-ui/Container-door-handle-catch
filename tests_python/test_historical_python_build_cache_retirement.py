"""Pure control checks; Jenkins executes these on ECS, never real Docker."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('historical_python_build_cache', ROOT / 'script/jenkins/retire-failed-native-jar-duplicates.py')
cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cache)
IDENTITY = {'instanceId': 'i-2zeieuov2aum486jm1ek', 'machineId': '1ebe8f77e3104ab6a49a9386e38abd20', 'executionLocation': 'ECS'}
CURRENT = {'release': 'ci-200-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}


def checksum(value):
    return hashlib.sha256(value).hexdigest()


def fixture_objects(root, release):
    iid, tag, cid = cache.PYTHON_CACHE_APPROVED[release]
    token = tag.rsplit('-', 1)[1] + 'a' * 12
    owner = {'release': release, 'commit': release.rsplit('-', 1)[1] + 'f' * 28,
             'sourceSha256': checksum(release.encode()), 'identity': IDENTITY, 'ownerToken': token,
             'containerName': 'doorhandle-ci-python-' + token, 'baseImageId': cache.PYTHON_CACHE_BASE,
             'diskReserveBytes': 2 * 1024 ** 3, 'diskOvershootBytes': 256 * 1024 ** 2, 'maximumGrowthBytes': 2 * 1024 ** 3,
             'sourceFiles': {cache.PYTHON_CACHE_RECIPE: 'c' * 64, cache.PYTHON_CACHE_REQUIREMENTS: 'd' * 64}}
    command = ['-I', '-B', '-c', 'print("synthetic public installer")', '{"pytest": "8.4.2"}']
    source = {'archive': {'sha256': owner['sourceSha256']}, 'installerCommandSha256': checksum(cache.canonical(command))}
    folder = root / 'inbox' / release / 'python-tools'
    cfg = {'Image': cache.PYTHON_CACHE_BASE, 'User': '0:0', 'Entrypoint': ['/usr/local/bin/python'],
           'Cmd': command, 'WorkingDir': '/', 'Healthcheck': {'Test': ['NONE']}, 'Volumes': None,
           'Labels': {'io.doorhandle.ci-tool-preparation': token, 'io.doorhandle.release': release,
                      'io.doorhandle.source': owner['sourceSha256']}}
    host = {'Privileged': False, 'ReadonlyRootfs': False, 'Memory': 2 * 1024 ** 3, 'MemorySwap': 2 * 1024 ** 3,
            'NanoCpus': 2 * 10 ** 9, 'PidsLimit': 256, 'NetworkMode': 'bridge', 'PidMode': '', 'IpcMode': 'private',
            'UTSMode': '', 'UsernsMode': '', 'RestartPolicy': {'Name': 'no', 'MaximumRetryCount': 0},
            'Tmpfs': {'/tmp': 'rw,nosuid,nodev,size=268435456'}, 'CapDrop': ['ALL'],
            'SecurityOpt': ['no-new-privileges:true'], 'LogConfig': {'Type': 'json-file', 'Config': {'max-file': '1', 'max-size': '10m'}}}
    container = {'Id': cid, 'Name': '/' + owner['containerName'], 'Image': cache.PYTHON_CACHE_BASE,
        'Config': cfg, 'HostConfig': host, 'State': {'Status': 'exited', 'Running': False, 'Restarting': False,
        'Paused': False, 'Dead': False, 'Pid': 0, 'FinishedAt': '2026-11-07T20:00:00Z'}, 'SizeRw': 1024,
        'Mounts': [{'Type': 'bind', 'Source': str(folder / 'python-test-requirements.txt'),
                    'Destination': '/ci-input/requirements.txt', 'RW': False, 'Propagation': 'rprivate'},
                   {'Type': 'bind', 'Source': str(folder / 'reports'), 'Destination': '/ci-report', 'RW': True, 'Propagation': 'rprivate'}]}
    image_cfg = {'User': '1000:1000', 'Entrypoint': ['/usr/local/bin/python'], 'Cmd': ['--version'], 'WorkingDir': '/',
                 'Healthcheck': {'Test': ['NONE']}, 'Volumes': None,
                 'Labels': {'io.doorhandle.ci-tools': 'python-v1', 'io.doorhandle.source': owner['sourceSha256'],
                     'io.doorhandle.commit': owner['commit'], 'io.doorhandle.ci-tools-recipe-sha256': 'c' * 64,
                     'io.doorhandle.ci-tools-requirements-sha256': 'd' * 64}}
    image = {'Id': iid, 'RepoTags': [tag], 'Os': 'linux', 'Architecture': 'amd64', 'Size': 8192,
             'Config': image_cfg, 'RootFS': {'Layers': ['sha256:' + '1' * 64, 'sha256:' + '2' * 64]}}
    return owner, source, container, image


@pytest.fixture
def state(tmp_path, monkeypatch):
    root = tmp_path / 'ecs'; root.mkdir(mode=0o700)
    (root / 'inbox' / CURRENT['release']).mkdir(parents=True, mode=0o700)
    owners, sources, containers, images, usage = {}, {}, {}, {}, {}
    for release in cache.PYTHON_CACHE_APPROVED:
        # The real locks need both real historical directories, even in a fake.
        (root / 'inbox' / release / 'python-tools').mkdir(parents=True, mode=0o700)
        (root / 'verification' / release / 'checkout').mkdir(parents=True, mode=0o700)
        owner, source, container, image = fixture_objects(root, release)
        owners[release] = owner; sources[release] = source
        containers[container['Id']] = container; images[image['Id']] = image
        usage[image['Id']] = {'Size': 8192, 'SharedSize': 4096, 'Containers': 0}
    protected = {'imageIds': sorted(cache.PYTHON_CACHE_PROTECTED_IMAGES), 'container97InspectSha256': 'e' * 64,
                 'baseLayers': ['sha256:' + '1' * 64]}
    value = SimpleNamespace(root=root, owners=owners, sources=sources, containers=containers, images=images, usage=usage,
                            protected=protected, commands=[], fail_at=None, references=[], drift_after_plan=False)
    monkeypatch.setattr(cache, '_python_cache_owner_source', lambda _root, release, _identity: (copy.deepcopy(owners[release]), copy.deepcopy(sources[release])))
    monkeypatch.setattr(cache, '_python_cache_inspect', lambda identifier, image=False: copy.deepcopy((images if image else containers)[identifier]))
    monkeypatch.setattr(cache, '_python_cache_image_ids', lambda: set(images) | set(cache.PYTHON_CACHE_PROTECTED_IMAGES))
    monkeypatch.setattr(cache, 'builder_container_ids', lambda: list(containers) + [cache.PYTHON_CACHE_PROTECTED_CONTAINER])
    monkeypatch.setattr(cache, '_python_cache_protected', lambda: copy.deepcopy(protected))
    monkeypatch.setattr(cache, '_python_cache_references', lambda: copy.deepcopy(value.references))
    monkeypatch.setattr(cache, '_python_cache_usage', lambda: copy.deepcopy(usage))
    monkeypatch.setattr(cache, '_python_cache_available', lambda _root: 10 ** 10 + len(value.commands) * 1024)
    def docker(*args):
        value.commands.append(args)
        if value.fail_at == len(value.commands): raise cache.RetirementError('SYNTHETIC_DOCKER_REFUSAL')
        if args[0] == 'rm': containers.pop(args[1])
        else:
            assert args[:2] == ('image', 'rm')
            images.pop(args[2])
        return (args[-1] + '\n').encode()
    monkeypatch.setattr(cache, 'builder_docker', docker)
    value.modules = {'cleanup': SimpleNamespace(process_references=lambda _checkout: None)}
    return value


def plan(state):
    value = cache.plan_python_build_cache(state.root, expected_current=CURRENT, identity=IDENTITY, modules=state.modules)
    assert value['skipped'] == [], value['skipped']
    assert len(value['containers']) == len(value['images']) == 7
    return value


def apply(state, value):
    return cache.apply_python_build_cache(state.root, value, plan_sha256=checksum(cache.canonical(value)),
                                         expected_current=CURRENT, identity=IDENTITY, modules=state.modules)


def test_closed_allowlist_retains_97_cached_base_maven_and_node():
    assert {int(tag.split('-')[1]) for tag in cache.PYTHON_CACHE_APPROVED} == {88, 89, 90, 92, 94, 95, 96}
    assert len(cache.PYTHON_CACHE_PROTECTED_IMAGES) == 4
    assert not {row[0] for row in cache.PYTHON_CACHE_APPROVED.values()} & cache.PYTHON_CACHE_PROTECTED_IMAGES
    assert cache.PYTHON_CACHE_PROTECTED_CONTAINER not in {row[2] for row in cache.PYTHON_CACHE_APPROVED.values()}


def test_positive_plan_apply_uses_full_ids_no_force_and_retains_originals(state):
    value = plan(state); receipt = apply(state, value)
    assert receipt['status'] == 'REMOVED' and receipt['failure'] is None
    assert len(receipt['removedContainers']) == len(receipt['removedImages']) == 7
    assert receipt['availableBytesAfter'] > receipt['availableBytesBefore']
    assert all(args[0] == 'rm' and len(args) == 2 and len(args[1]) == 64 or
               args[:2] == ('image', 'rm') and len(args) == 3 and len(args[2]) == 71 for args in state.commands)
    assert all('-f' not in args and '-v' not in args for args in state.commands)
    assert receipt['cachedInputsPreserved'] and receipt['businessDataVolumesDirectoriesSourcesReportsPreserved']
    assert not receipt['testsRunByRetirement'] and not receipt['automaticResumeAllowed']
    assert len(list((state.root / 'inbox' / CURRENT['release'] / 'native-python-build-cache-inspect').glob('*.json'))) == 14
    assert all((state.root / 'inbox' / tag / 'python-tools').is_dir() for tag in cache.PYTHON_CACHE_APPROVED)
    journal = (state.root / 'inbox' / CURRENT['release'] / 'native-python-build-cache-journal.jsonl').read_bytes()
    assert checksum(journal) == receipt['journalSha256'] and b'CONTAINER_REMOVE_STARTED' in journal and b'IMAGE_REMOVED' in journal


@pytest.mark.parametrize('damage', ['cid', 'release', 'source', 'mount', 'running', 'pid', 'network', 'privileged', 'command'])
def test_container_source_mount_runtime_and_identity_drift_are_refused(state, damage):
    release = next(iter(cache.PYTHON_CACHE_APPROVED)); owner = state.owners[release]
    row = copy.deepcopy(state.containers[cache.PYTHON_CACHE_APPROVED[release][2]])
    if damage == 'cid': row['Id'] = cache.PYTHON_CACHE_PROTECTED_CONTAINER
    elif damage in ('release', 'source'): row['Config']['Labels']['io.doorhandle.' + damage] = 'different'
    elif damage == 'mount': row['Mounts'][0]['RW'] = True
    elif damage == 'running': row['State']['Running'] = True
    elif damage == 'pid': row['State']['Pid'] = 123
    elif damage == 'network': row['HostConfig']['NetworkMode'] = 'host'
    elif damage == 'privileged': row['HostConfig']['Privileged'] = True
    else: row['Config']['Cmd'] = ['--version']
    with pytest.raises(cache.RetirementError): cache.python_cache_container_descriptor(state.root, row, owner, state.sources[release])


def test_image_referenced_after_plan_blocks_image_removal(state):
    value = plan(state)
    state.references.append({'Id': 'f' * 64, 'Image': value['images'][0]['imageId'], 'Name': '/other', 'HostConfig': {}, 'Mounts': []})
    result = apply(state, value)
    assert result['status'] == 'FAILED_OR_UNKNOWN' and not result['removedImages']
    assert not state.commands
    assert result['failure']['reason'] == 'PYTHON_CACHE_PLANNED_IMAGE_NEW_REFERENCE'


@pytest.mark.parametrize('damage', ['protected', 'source', 'inspection'])
def test_plan_bound_protection_source_and_inspection_change_stop_before_delete(state, damage):
    value = plan(state)
    if damage == 'protected': state.protected['container97InspectSha256'] = 'f' * 64
    elif damage == 'source': state.sources[value['containers'][0]['release']]['archive']['sha256'] = 'f' * 64
    else:
        reference = value['containers'][0]['inspection']
        (state.root / reference['path']).write_bytes(b'{}')
    result = apply(state, value)
    assert result['status'] == 'FAILED_OR_UNKNOWN' and result['failure'] and not state.commands


def test_partial_docker_failure_keeps_journal_originals_and_remaining_objects(state):
    value = plan(state); state.fail_at = 2
    result = apply(state, value)
    assert result['status'] == 'FAILED_OR_UNKNOWN' and len(result['removedContainers']) == 1
    assert not result['removedImages'] and len(state.containers) == 6 and len(state.images) == 7
    assert (state.root / value['containers'][0]['inspection']['path']).exists()
    assert b'FAILED_OR_UNKNOWN' in (state.root / 'inbox' / CURRENT['release'] / 'native-python-build-cache-journal.jsonl').read_bytes()


def test_public_inspection_projection_never_records_environment_or_foreign_label_values(state):
    row = copy.deepcopy(next(iter(state.containers.values())))
    row['Config']['Env'] = ['PYTHONNOUSERSITE=1']
    row['Config']['Labels']['foreign.label'] = 'must-not-be-copied'
    raw = cache.canonical(cache._python_cache_projection(row))
    assert b'PYTHONNOUSERSITE' not in raw and b'must-not-be-copied' not in raw
    row['Config']['Env'] = ['API_KEY=synthetic-secret']
    with pytest.raises(cache.RetirementError): cache._python_cache_projection(row)


def test_source_proof_binds_whole_archive_pax_and_retained_member_bytes(tmp_path):
    root = tmp_path / 'ecs'; release = next(iter(cache.PYTHON_CACHE_APPROVED))
    folder = root / 'inbox' / release / 'python-tools'; folder.mkdir(parents=True, mode=0o700)
    owner, _, _, _ = fixture_objects(root, release)
    recipe = b'INSTALL = "print(123)"\n'; requirements = b'pytest==8.4.2\n'
    contents = {cache.PYTHON_CACHE_RECIPE: recipe, cache.PYTHON_CACHE_REQUIREMENTS: requirements}
    for name, raw in contents.items():
        path = folder / Path(name).name; path.write_bytes(raw); path.chmod(0o600 if name.endswith('.py') else 0o444)
    archive = folder.parent / 'source.tar.gz'
    with tarfile.open(archive, mode='w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': owner['commit']}) as stream:
        for name, raw in contents.items():
            entry = tarfile.TarInfo(name); entry.size = len(raw); stream.addfile(entry, io.BytesIO(raw))
    archive.chmod(0o600); owner['sourceSha256'] = checksum(archive.read_bytes())
    owner['sourceFiles'] = {name: checksum(raw) for name, raw in contents.items()}
    result = cache.python_cache_source_proof(root, owner)
    assert result['archive']['sha256'] == owner['sourceSha256']
    owner['commit'] = owner['commit'][:12] + '0' * 28
    with pytest.raises(cache.RetirementError, match='COMMIT_AND_CLOSURE'): cache.python_cache_source_proof(root, owner)


def test_missing_real_historical_lock_directory_is_reported_not_created(state):
    release = next(iter(cache.PYTHON_CACHE_APPROVED))
    checkout = state.root / 'verification' / release / 'checkout'; checkout.rmdir(); checkout.parent.rmdir()
    value = cache.plan_python_build_cache(state.root, expected_current=CURRENT, identity=IDENTITY, modules=state.modules)
    assert len(value['skipped']) == 2 and all(row['release'] == release for row in value['skipped'])
    assert len(value['containers']) == len(value['images']) == 6 and not checkout.parent.exists()
