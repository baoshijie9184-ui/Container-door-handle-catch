"""ECS-only dependency-cache contracts. No Maven/network/application is executed."""
import copy
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fixed_maven_cache_contract', ROOT / 'script/jenkins/ecs-tool-runtime.py')
tools = importlib.util.module_from_spec(spec); spec.loader.exec_module(tools)


@pytest.fixture
def cache(tmp_path):
    commit = 'a' * 40; tag = 'ci-60-' + commit[:12]
    folder = tmp_path / 'inbox' / tag / 'tool-runtime'; folder.mkdir(parents=True)
    checkout = tmp_path / 'verification' / tag / 'checkout'; checkout.mkdir(parents=True)
    pom = checkout / 'pom.xml'; pom.write_bytes(b'<project>fixed release dependencies</project>\r\n')
    value = {'directory': str(folder), 'checkout': str(checkout), 'images': {'maven': 'sha256:' + '1' * 64},
        'release': tag, 'commit': commit, 'sourceSha256': 'b' * 64, 'identity': {'instanceId': 'i-fixture', 'machineId': 'c' * 32}}
    catalog = [{'path': 'pom.xml', 'bytes': pom.stat().st_size, 'sha256': tools.digest(pom)}]
    value['mavenCache'] = tools.maven_cache_definition(tmp_path, value['images']['maven'], catalog)
    tools.initialize_maven_cache(value)
    return value


def release_artifact(value):
    repository = Path(value['mavenCache']['repository'])
    path = repository / 'org/example/library/1.2.3/library-1.2.3.jar'; path.parent.mkdir(parents=True)
    path.write_bytes(b'opaque third-party release artifact fixture')
    Path(str(path) + '.sha1').write_text(hashlib.sha1(path.read_bytes()).hexdigest() + '\n')
    return path


def commit_downloads(value):
    before = tools.maven_cache_inventory(value)
    path = release_artifact(value)
    after = tools.maven_cache_inventory(value)
    proof = tools.persist_maven_cache(value, before, after)
    return path, proof


@pytest.mark.parametrize('change', ['pom-bytes', 'mvn-config-bytes', 'maven-image'])
def test_cache_key_binds_every_original_maven_input_and_immutable_jdk_image(cache, change):
    catalog = copy.deepcopy(cache['mavenCache']['inputs']); image = cache['images']['maven']
    if change == 'pom-bytes': catalog[0]['sha256'] = hashlib.sha256(b'<project>fixed release dependencies</project>\n').hexdigest()
    if change == 'mvn-config-bytes': catalog.insert(0, {'path': '.mvn/jvm.config', 'bytes': 4, 'sha256': hashlib.sha256(b'-Xmx').hexdigest()})
    if change == 'maven-image': image = 'sha256:' + '2' * 64
    changed = tools.maven_cache_definition(Path(cache['directory']).parents[2], image, catalog)
    assert changed['key'] != cache['mavenCache']['key']


def test_source_commit_changes_with_identical_poms_can_reuse_the_same_dependency_key(cache):
    root = Path(cache['directory']).parents[2]
    same = tools.maven_cache_definition(root, cache['images']['maven'], copy.deepcopy(cache['mavenCache']['inputs']))
    assert same == cache['mavenCache']
    cache['commit'] = 'e' * 40
    assert tools.registered_maven_cache(cache) == same


@pytest.mark.parametrize('field', ['directory', 'repository', 'key', 'mavenImage'])
def test_registration_rejects_any_redirected_root_or_identity(cache, field):
    cache['mavenCache'][field] = '/data/production' if field in ('directory', 'repository') else 'f' * 64
    with pytest.raises(ValueError): tools.registered_maven_cache(cache)


@pytest.mark.parametrize('arguments', [
    ['-Dmaven.repo.local=/data/production', 'verify'], ['-D', 'maven.repo.local=/data/production', 'verify'],
    ['-s', '/tmp/settings.xml', 'verify'], ['install'], ['deploy'],
    ['org.apache.maven.plugins:maven-install-plugin:3.1.3:install'], ['-Dmaven.home=/foreign', 'verify'],
])
def test_maven_arguments_cannot_choose_an_external_repository_or_install_reactor_outputs(cache, arguments):
    with pytest.raises(ValueError): tools.maven_arguments(cache, arguments)


def test_maven_arguments_pin_exact_cache_and_enforce_repository_checksums(cache):
    result = tools.maven_arguments(cache, ['-B', 'verify'])
    assert result[:2] == ['-C', '-Dmaven.repo.local=' + cache['mavenCache']['repository']]
    assert result[-2:] == ['-B', 'verify']
    expected = '-Dmaven.repo.local=' + cache['mavenCache']['repository']
    with pytest.raises(ValueError): tools.maven_arguments(cache, [expected, expected, 'verify'])


@pytest.mark.parametrize('change', ['bytes', 'extra-config'])
def test_execution_rechecks_materialized_pom_and_config_bytes(cache, change):
    checkout = Path(cache['checkout'])
    if change == 'bytes': (checkout / 'pom.xml').write_bytes(b'other fixed release dependency inputs')
    else:
        (checkout / '.mvn').mkdir(); (checkout / '.mvn/maven.config').write_text('-B')
    with pytest.raises(ValueError): tools.maven_arguments(cache, ['verify'])


def test_reusable_release_bytes_have_exact_checksums_and_a_source_receipt(cache):
    path, proof = commit_downloads(cache)
    current = tools.maven_cache_inventory(cache); tools.verify_maven_cache_state(cache, current)
    assert proof['artifactCount'] == 1 and proof['reusedArtifacts'] == 0
    assert proof['scope'] == 'SHARED_THIRD_PARTY_RELEASE_DEPENDENCIES'
    assert current['artifacts'][0] == [path.relative_to(cache['mavenCache']['repository']).as_posix(), path.stat().st_size, tools.digest(path)]
    reused = tools.persist_maven_cache(cache, current, current)
    assert reused['reusedArtifacts'] == 1 and reused['allocatedGrowthBytes'] == 0
    assert tools.public_maven_cache(cache, reused) == dict(sorted(reused.items()))


@pytest.mark.parametrize('bad', ['reactor', 'snapshot', 'unchecked', 'mismatch', 'class-file', 'hardlink', 'symlink'])
def test_reactor_snapshot_unchecked_or_linked_bytes_never_become_ready(cache, bad, tmp_path):
    path = release_artifact(cache); repository = Path(cache['mavenCache']['repository'])
    if bad == 'reactor':
        path = repository / 'com/ruanzhu/app/1.0/app-1.0.jar'; path.parent.mkdir(parents=True); path.write_bytes(b'app')
    if bad == 'snapshot':
        path = repository / 'org/example/library/1.0-SNAPSHOT/library-1.0-SNAPSHOT.jar'; path.parent.mkdir(parents=True); path.write_bytes(b'snapshot')
    if bad == 'unchecked': Path(str(path) + '.sha1').unlink()
    if bad == 'mismatch': path.write_bytes(b'changed dependency')
    if bad == 'class-file': (path.parent / 'Application.class').write_bytes(b'compiled application')
    if bad == 'hardlink': os.link(path, path.parent / 'another.jar')
    if bad == 'symlink':
        protected = tmp_path / 'protected'; protected.write_bytes(b'keep source bytes'); (repository / 'foreign').symlink_to(protected)
    with pytest.raises(ValueError): tools.maven_cache_inventory(cache)


def test_recomputed_sidecar_does_not_hide_idle_dependency_tampering(cache):
    path, _ = commit_downloads(cache)
    path.write_bytes(b'changed bytes with a recomputed sidecar')
    Path(str(path) + '.sha1').write_text(hashlib.sha1(path.read_bytes()).hexdigest())
    current = tools.maven_cache_inventory(cache)
    with pytest.raises(ValueError, match='outside their serial command receipt'):
        tools.verify_maven_cache_state(cache, current)


def test_known_partial_markers_are_removed_only_inside_the_registered_generated_cache(cache, tmp_path):
    path = release_artifact(cache); partial = path.parent / 'library-1.2.3.jar.lastUpdated'
    partial.write_text('failed resolver metadata')
    protected = tmp_path / 'protected-business-original'; protected.write_bytes(b'keep')
    tools.discard_maven_transients(cache)
    assert not partial.exists() and path.exists() and protected.read_bytes() == b'keep'
    assert tools.maven_cache_inventory(cache)['artifacts']


def test_a_cache_lease_is_nonblocking_and_serializes_the_same_key(cache):
    with tools.maven_cache_lock(cache):
        with pytest.raises(ValueError, match='already in use'):
            with tools.maven_cache_lock(cache): pytest.fail('parallel Maven cache write admitted')


def test_public_dependency_evidence_rejects_private_paths_or_arbitrary_extra_fields(cache):
    _, proof = commit_downloads(cache); proof['sourcePath'] = '/private/source/original'
    with pytest.raises(ValueError): tools.public_maven_cache(cache, proof)


def test_resource_probes_measure_shared_growth_separately_from_owned_checkout(cache, monkeypatch):
    release_artifact(cache)
    monkeypatch.setattr(tools, 'resource_probe', lambda _: {'capturedAtUnix': 1,
        'diskAvailableBytes': tools.DISK_FLOOR + 1, 'memoryAvailableBytes': tools.MEMORY_FLOOR + 1})
    record = {'tool': 'mvn'}; tools.observe_resources(cache, record, Path(cache['directory']) / 'probe.json')
    shared = record['resourceMonitoring']['sharedMavenDependencyCache']
    assert shared['scope'] == 'SHARED_THIRD_PARTY_RELEASE_DEPENDENCIES' and shared['bytes'] > 0
    assert shared['allocatedBytes'] > 0 and shared['key'] == cache['mavenCache']['key']


def test_archive_catalog_and_commit_bind_maven_execution_before_cache_access(cache):
    archive = Path(cache['directory']).parent / 'source.tar.gz'
    raw = (Path(cache['checkout']) / 'pom.xml').read_bytes()
    with tarfile.open(archive, 'w:gz', pax_headers={'comment': cache['commit']}) as package:
        entry = tarfile.TarInfo('pom.xml'); entry.size = len(raw); package.addfile(entry, io.BytesIO(raw))
    cache['sourceSha256'] = tools.digest(archive); tools.verify_maven_source(cache)
    archive.write_bytes(b'changed fixed source archive')
    with pytest.raises(ValueError, match='archive changed'): tools.verify_maven_source(cache)
