"""ECS-only dependency-cache contracts. No Maven/network/application is executed."""
import copy
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import tarfile
from types import SimpleNamespace

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


REACTOR_MODULES = ('doorhandle-module-system', 'doorhandle-module-ai')


def register_reactor_inputs(value):
    checkout = Path(value['checkout'])
    catalog = sorted(({'path': path.relative_to(checkout).as_posix(), 'bytes': path.stat().st_size,
                       'sha256': tools.digest(path)} for path in checkout.rglob('pom.xml')), key=lambda row: row['path'])
    value['mavenCache'] = tools.maven_cache_definition(Path(value['directory']).parents[2], value['images']['maven'], catalog)


@pytest.fixture
def reactor_cache(cache):
    checkout = Path(cache['checkout'])
    (checkout / 'pom.xml').write_text('<project xmlns="http://maven.apache.org/POM/4.0.0"><modules>'
        + ''.join('<module>' + module + '</module>' for module in REACTOR_MODULES) + '</modules></project>')
    for module in REACTOR_MODULES:
        directory = checkout / module; directory.mkdir()
        (directory / 'pom.xml').write_text('<project><artifactId>' + module + '</artifactId></project>')
    register_reactor_inputs(cache)
    return cache


@pytest.mark.parametrize('module', REACTOR_MODULES)
def test_one_bound_direct_module_can_be_selected_as_the_exact_trailing_triplet(reactor_cache, module):
    arguments = ['-B', '-ntp', '-Ddoorhandle.operations.mysql.config=/owned/fixture.json', 'test', '-pl', module, '-am']
    result = tools.maven_arguments(reactor_cache, arguments)
    assert result == ['-C', '-Dmaven.repo.local=' + reactor_cache['mavenCache']['repository'], *arguments]
    assert result[-3:] == ['-pl', module, '-am']


@pytest.mark.parametrize('arguments', [
    ['test', '-pl', REACTOR_MODULES[0]],
    ['test', '-am'],
    ['test', '-pl', REACTOR_MODULES[0], '-am', '-B'],
    ['test', '-pl', REACTOR_MODULES[0], '-am', '-pl', REACTOR_MODULES[1], '-am'],
    ['test', '-pl=' + REACTOR_MODULES[0], '-am'],
    ['test', '-pl', REACTOR_MODULES[0] + '/nested', '-am'],
    ['test', '-pl', '../' + REACTOR_MODULES[0], '-am'],
    ['test', '-pl', '/tmp/' + REACTOR_MODULES[0], '-am'],
    ['test', '-pl', ','.join(REACTOR_MODULES), '-am'],
    ['test', '-pl', ':' + REACTOR_MODULES[0], '-am'],
    ['test', REACTOR_MODULES[0]],
    ['test', '-pl', 'doorhandle-module-foreign', '-am'],
])
def test_module_selection_never_admits_repeated_nested_nontrailing_or_arbitrary_values(reactor_cache, arguments):
    with pytest.raises(ValueError): tools.maven_arguments(reactor_cache, arguments)


@pytest.mark.parametrize('extra', [
    ['-f', '/foreign/pom.xml'], ['--fail-never'], ['-DignoreTestFailure=true'],
    ['-Dsurefire.testFailureIgnore=true'], ['-Dmaven.test.failure.ignore=true'],
])
def test_selected_module_cannot_redirect_its_pom_or_ignore_test_failures(reactor_cache, extra):
    arguments = ['test', *extra, '-pl', REACTOR_MODULES[0], '-am']
    with pytest.raises(ValueError): tools.maven_arguments(reactor_cache, arguments)


@pytest.mark.parametrize('damage', ['undeclared', 'profile-only', 'duplicate', 'malformed', 'entity'])
def test_selection_requires_one_explicit_direct_module_in_the_bound_root_pom(reactor_cache, damage):
    module = REACTOR_MODULES[0]; checkout = Path(reactor_cache['checkout'])
    declaration = '<modules><module>' + module + '</module></modules>'
    if damage == 'undeclared': body = '<project><modules><module>' + REACTOR_MODULES[1] + '</module></modules></project>'
    elif damage == 'profile-only': body = '<project><profiles><profile>' + declaration + '</profile></profiles></project>'
    elif damage == 'duplicate': body = '<project><modules><module>' + module + '</module><module>' + module + '</module></modules></project>'
    elif damage == 'malformed': body = '<project><modules>'
    else: body = '<!DOCTYPE project [<!ENTITY selected "' + module + '">]><project><modules><module>&selected;</module></modules></project>'
    (checkout / 'pom.xml').write_text(body); register_reactor_inputs(reactor_cache)
    with pytest.raises(ValueError): tools.maven_arguments(reactor_cache, ['test', '-pl', module, '-am'])


@pytest.mark.parametrize('linked', ['module-directory', 'module-pom'])
def test_selected_module_and_its_pom_cannot_be_redirected_by_a_symlink(reactor_cache, tmp_path, linked):
    module = REACTOR_MODULES[0]; directory = Path(reactor_cache['checkout']) / module
    target = directory if linked == 'module-directory' else directory / 'pom.xml'
    preserved = tmp_path / ('original-module' if linked == 'module-directory' else 'original-pom.xml')
    target.rename(preserved); target.symlink_to(preserved, target_is_directory=linked == 'module-directory')
    with pytest.raises(ValueError): tools.maven_arguments(reactor_cache, ['test', '-pl', module, '-am'])
    assert preserved.exists()


def test_selected_module_still_rejects_changed_root_pom_bytes_without_cache_reregistration(reactor_cache):
    checkout = Path(reactor_cache['checkout']); pom = checkout / 'pom.xml'
    pom.write_bytes(pom.read_bytes() + b'\n')
    with pytest.raises(ValueError): tools.maven_arguments(reactor_cache, ['test', '-pl', REACTOR_MODULES[0], '-am'])


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


@pytest.fixture
def failed_cache(cache, monkeypatch):
    artifact, _ = commit_downloads(cache)
    directory = Path(cache['mavenCache']['directory']); state = directory / 'state.json'
    original = tools.private_json(state); source = directory / 'receipts' / original['receipt']
    before = tools.maven_cache_inventory(cache)
    monkeypatch.setattr(tools, 'MAVEN_CACHE_RECOVERY_PINS', {
        cache['mavenCache']['key']: {tools.digest(source): before['catalogSha256']}})
    tools.write_json(state, {'status': 'FAILED_OR_UNKNOWN', 'key': cache['mavenCache']['key'], 'errorType': 'ValueError'})
    cache['commit'] = 'e' * 40; cache['release'] = 'ci-70-' + cache['commit'][:12]
    return SimpleNamespace(value=cache, directory=directory, state=state, source=source, before=before,
        failed=state.read_bytes(), artifact=artifact,
        originals={path: path.read_bytes() for path in (directory / 'receipts').iterdir()},
        repository={path: path.read_bytes() for path in Path(cache['mavenCache']['repository']).rglob('*') if path.is_file()})


def test_unknown_cache_recovers_only_authenticated_unchanged_bytes_under_one_lock(failed_cache, monkeypatch):
    item = failed_cache; inventory = tools.maven_cache_inventory; calls = []
    def observed(value):
        with pytest.raises(ValueError, match='already in use'):
            with tools.maven_cache_lock(value): pytest.fail('recovery inventory ran without its cache lease')
        calls.append(1)
        return inventory(value)
    monkeypatch.setattr(tools, 'maven_cache_inventory', observed)
    tools.initialize_maven_cache(item.value)
    assert len(calls) == 2
    assert all(path.read_bytes() == raw for path, raw in item.originals.items())
    assert all(path.read_bytes() == raw for path, raw in item.repository.items())
    state = tools.private_json(item.state)
    ready = tools.private_json(item.directory / 'receipts' / state['receipt'])
    proofs = list((item.directory / 'recoveries').iterdir()); assert len(proofs) == 1
    recovery = tools.private_json(proofs[0])
    assert recovery['status'] == 'RECOVERY_VALIDATED'
    assert recovery['failedStateBytesHex'] == item.failed.hex()
    assert recovery['failedStateSha256'] == hashlib.sha256(item.failed).hexdigest()
    assert recovery['sourceReceiptSha256'] == ready['previousReceiptSha256'] == tools.digest(item.source)
    assert ready['recoveryReceiptSha256'] == tools.digest(proofs[0])
    assert ready['release'] == item.value['release'] and ready['commit'] == item.value['commit']
    assert ready['catalog'] == item.before['records']
    tools.verify_maven_cache_state(item.value, item.before)


def test_ready_initialization_does_not_search_or_create_recovery_evidence(cache, monkeypatch):
    def forbidden(*_): pytest.fail('an already READY cache entered recovery')
    monkeypatch.setattr(tools, 'recover_maven_cache', forbidden)
    tools.initialize_maven_cache(cache)
    assert not (Path(cache['mavenCache']['directory']) / 'recoveries').exists()


def test_equal_verified_content_can_recover_despite_different_historical_directory_allocation(failed_cache, monkeypatch):
    item = failed_cache; proof = tools.private_json(item.source)
    proof['allocatedBytes'] += 4096
    tools.write_json(item.source, proof)
    monkeypatch.setattr(tools, 'MAVEN_CACHE_RECOVERY_PINS', {
        item.value['mavenCache']['key']: {tools.digest(item.source): item.before['catalogSha256']}})
    tools.initialize_maven_cache(item.value)
    assert tools.private_json(item.state)['allocatedBytes'] == item.before['allocatedBytes']


def test_failure_writing_ready_retains_unknown_state_and_only_validated_inputs_evidence(failed_cache, monkeypatch):
    item = failed_cache
    def refused(*args, **kwargs): raise OSError('synthetic exhausted storage')
    monkeypatch.setattr(tools, 'persist_maven_cache', refused)
    with pytest.raises(OSError, match='synthetic exhausted storage'):
        tools.initialize_maven_cache(item.value)
    proofs = list((item.directory / 'recoveries').iterdir())
    assert len(proofs) == 1 and tools.private_json(proofs[0])['status'] == 'RECOVERY_VALIDATED'
    assert item.state.read_bytes() == item.failed
    assert all(path.read_bytes() == raw for path, raw in item.originals.items())


@pytest.mark.parametrize('damage', ['wrong-key', 'wrong-status', 'extra-field', 'unregistered-key', 'unregistered-digest', 'wrong-pinned-catalog'])
def test_unknown_recovery_requires_exact_failure_and_independent_source_approval(failed_cache, monkeypatch, damage):
    item = failed_cache; failed = tools.private_json(item.state)
    if damage == 'wrong-key': failed['key'] = 'f' * 64
    if damage == 'wrong-status': failed['status'] = 'FAILED'
    if damage == 'extra-field': failed['unreviewed'] = True
    if damage in ('wrong-key', 'wrong-status', 'extra-field'): tools.write_json(item.state, failed)
    if damage == 'unregistered-key': monkeypatch.setattr(tools, 'MAVEN_CACHE_RECOVERY_PINS', {})
    if damage == 'unregistered-digest':
        monkeypatch.setattr(tools, 'MAVEN_CACHE_RECOVERY_PINS', {item.value['mavenCache']['key']: {'0' * 64: item.before['catalogSha256']}})
    if damage == 'wrong-pinned-catalog':
        monkeypatch.setattr(tools, 'MAVEN_CACHE_RECOVERY_PINS', {item.value['mavenCache']['key']: {tools.digest(item.source): '0' * 64}})
    raw = item.state.read_bytes()
    with pytest.raises(ValueError): tools.initialize_maven_cache(item.value)
    assert item.state.read_bytes() == raw and not (item.directory / 'recoveries').exists()
    assert all(path.read_bytes() == original for path, original in item.repository.items())


@pytest.mark.parametrize('field', ['key', 'inputsSha256', 'mavenImage', 'identity', 'release', 'commit', 'catalog', 'afterCatalogSha256'])
def test_even_a_pinned_receipt_must_match_identity_source_name_and_every_dependency(failed_cache, monkeypatch, field):
    item = failed_cache; proof = tools.private_json(item.source)
    if field == 'identity': proof[field] = {**proof[field], 'instanceId': 'i-other'}
    elif field == 'catalog': proof[field] = proof[field][:-1]
    elif field == 'release': proof[field] = 'ci-61-' + proof['commit'][:12]
    elif field == 'commit': proof[field] = 'f' * 40
    elif field == 'mavenImage': proof[field] = 'sha256:' + 'f' * 64
    else: proof[field] = 'f' * 64
    tools.write_json(item.source, proof)
    monkeypatch.setattr(tools, 'MAVEN_CACHE_RECOVERY_PINS', {
        item.value['mavenCache']['key']: {tools.digest(item.source): item.before['catalogSha256']}})
    with pytest.raises(ValueError): tools.initialize_maven_cache(item.value)
    assert item.state.read_bytes() == item.failed and not (item.directory / 'recoveries').exists()


@pytest.mark.parametrize('damage', ['hardlink', 'symlink', 'permissions', 'owner', 'oversize', 'too-many'])
def test_recovery_refuses_unbounded_or_nonprivate_original_receipts(failed_cache, monkeypatch, damage):
    item = failed_cache
    if damage == 'hardlink': os.link(item.source, item.directory / 'linked-original')
    if damage == 'symlink':
        original = item.directory / 'original.json'; item.source.rename(original); item.source.symlink_to(original)
    if damage == 'permissions': item.source.chmod(0o644)
    if damage == 'owner': monkeypatch.setattr(tools.os, 'getuid', lambda: os.stat(item.source).st_uid + 1)
    if damage == 'oversize':
        with item.source.open('ab') as stream: stream.truncate(16 * 1024 ** 2 + 1)
    if damage == 'too-many':
        folder = item.directory / 'receipts'; original = Path.iterdir
        monkeypatch.setattr(Path, 'iterdir', lambda path: iter([item.source] * 1025) if path == folder else original(path))
    with pytest.raises(ValueError): tools.initialize_maven_cache(item.value)
    assert item.state.read_bytes() == item.failed and not (item.directory / 'recoveries').exists()


def test_recovery_checks_newest_build_first_without_rehashing_repository_per_candidate(failed_cache, monkeypatch):
    item = failed_cache; observed = []; read = tools.read_maven_recovery_json
    # These unapproved older files must not be opened once the pinned ci-60 proof matches.
    for build in (9, 10):
        tools.write_json(item.directory / 'receipts' / ('ci-' + str(build) + '-' + 'a' * 12 + '-' + '0' * 12 + '.json'), {})
    def tracked(path, limit):
        observed.append(Path(path))
        return read(path, limit)
    monkeypatch.setattr(tools, 'read_maven_recovery_json', tracked)
    tools.initialize_maven_cache(item.value)
    assert not any(path.name.startswith(('ci-9-', 'ci-10-')) for path in observed)


@pytest.mark.parametrize('changed', ['inventory', 'source-receipt', 'failed-state'])
def test_recovery_rechecks_dependency_and_original_evidence_before_committing(failed_cache, monkeypatch, changed):
    item = failed_cache; inventory = tools.maven_cache_inventory; calls = []
    def altered(value):
        current = inventory(value); calls.append(1)
        if len(calls) == 2:
            if changed == 'inventory': current = {**current, 'catalogSha256': 'f' * 64}
            elif changed == 'source-receipt': item.source.write_bytes(item.source.read_bytes() + b'\n')
            else: item.state.write_bytes(item.failed + b'\n')
        return current
    monkeypatch.setattr(tools, 'maven_cache_inventory', altered)
    with pytest.raises(ValueError, match='changed'): tools.initialize_maven_cache(item.value)
    assert not (item.directory / 'recoveries').exists()


def test_recovery_original_reader_rejects_metadata_changes_on_the_same_descriptor(failed_cache, monkeypatch):
    original = tools.os.fstat; calls = []
    def changed(fd):
        info = original(fd); calls.append(1)
        if len(calls) == 2:
            fields = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
            return SimpleNamespace(**{field: getattr(info, field) + (field == 'st_mtime_ns') for field in fields})
        return info
    monkeypatch.setattr(tools.os, 'fstat', changed)
    with pytest.raises(ValueError, match='changed while reading'):
        tools.read_maven_recovery_json(failed_cache.source, 16 * 1024 ** 2)


def test_ci224_interrupted_cache_uses_only_its_preserved_ready_receipt_and_original_catalog():
    assert tools.MAVEN_CACHE_RECOVERY_PINS['f13cd293e255d7189142b63cd6f195ef14217810cb755aa017c924ddfd16ada5'] == {
        '1d00eac2f5129848a756860b373190a1d928960822e01a884dc169e70acf63d5':
        'd3d549812de43946e8e5a48357c15cd4a6f121c1c16f4f14a179572f39f32d6a'}
