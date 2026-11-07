"""ECS-only contracts for immutable executors and bounded owned-output cleanup."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'script/jenkins' / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


tools = module('isolated_tool_runtime_contract', 'ecs-tool-runtime.py')
verifier = module('isolated_tool_cleanup_contract', 'verify-ecs.py')
remote = module('isolated_tool_evidence_contract', 'verify-remote.py')
preparer = module('isolated_tool_fixture_contract', 'prepare-compact-fixtures.py')


@pytest.fixture
def registration(tmp_path):
    commit, source_sha = 'a' * 40, 'b' * 64
    tag = 'ci-52-' + commit[:12]
    folder = tmp_path / 'inbox' / tag / 'tool-runtime'
    checkout = tmp_path / 'verification' / tag / 'checkout'
    folder.mkdir(parents=True); checkout.mkdir(parents=True)
    (folder / 'receipts').mkdir()
    source = checkout / 'script/jenkins/ecs-tool-runtime.py'
    source.parent.mkdir(parents=True)
    source.write_bytes(Path(tools.__file__).read_bytes())
    files = {}
    for name in ('executor.py', *tools.BINARIES):
        file = folder / name
        file.write_bytes(source.read_bytes() if name == 'executor.py' else b'owned wrapper')
        file.chmod(0o500); files[name] = tools.digest(file)
    value = {'schema': 1, 'kind': 'doorhandle-ecs-tool-runtime', 'release': tag,
             'commit': commit, 'sourceSha256': source_sha,
             'identity': {'instanceId': 'i-tooltest', 'machineId': 'd' * 32, 'executionLocation': 'ECS'},
             'directory': str(folder), 'checkout': str(checkout), 'token': 'c' * 24,
             'uid': os.getuid(), 'gid': os.getgid(), 'docker': '/usr/bin/docker',
             'images': {'maven': 'sha256:' + '1' * 64, 'node': 'sha256:' + '2' * 64,
                        'python': 'sha256:' + '3' * 64}, 'files': files}
    manifest = folder / 'manifest.json'
    tools.write_json(manifest, value)
    return value, manifest, dict(root=tmp_path, tag=tag, commit=commit, source_sha=source_sha,
                                identity=value['identity'], source=checkout)


def row(value):
    folder = value['directory']
    return {'Id': 'e' * 64, 'Image': value['images']['maven'],
            'Name': '/doorhandle-ci-tool-' + value['token'] + '-123456789abc',
            'Config': {'Labels': {tools.LABEL: value['token'], 'io.doorhandle.release': value['release'],
                                 'io.doorhandle.source': value['sourceSha256'], 'io.doorhandle.tool': 'mvn'},
                       'User': str(value['uid']) + ':' + str(value['gid']), 'Entrypoint': [tools.BINARIES['mvn']]},
            'HostConfig': {'RestartPolicy': {'Name': 'no'}, 'NetworkMode': 'host',
                           'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                           'Memory': 4 * 1024 ** 3, 'MemorySwap': 4 * 1024 ** 3,
                           'SecurityOpt': ['no-new-privileges:true']},
            'Mounts': [{'Type': 'bind', 'Source': source, 'Destination': target, 'RW': writable}
                       for source, target, writable in (
                           (folder, folder, False), (folder + '/receipts', folder + '/receipts', True),
                           ('/etc/machine-id', '/etc/machine-id', False),
                           (value['checkout'], value['checkout'], True))],
            'State': {'Running': False, 'Paused': False, 'Restarting': False, 'Pid': 0, 'ExitCode': 0}}


def test_registration_binds_immutable_source_owner_images_and_paths(registration):
    value, manifest, context = registration
    admitted, checksum = tools.admit(manifest, **context)
    assert admitted == value and checksum == tools.digest(manifest)
    for key, replacement in (('commit', 'f' * 40), ('source_sha', 'f' * 64), ('tag', 'ci-53-' + 'a' * 12)):
        with pytest.raises(ValueError):
            tools.admit(manifest, **{**context, key: replacement})


def test_registration_rejects_mutable_images_and_changed_launchers(registration):
    value, manifest, context = registration
    value['images']['maven'] = 'maven:latest'
    tools.write_json(manifest, value)
    with pytest.raises(ValueError, match='immutable'):
        tools.admit(manifest, **context)
    value['images']['maven'] = 'sha256:' + '1' * 64
    tools.write_json(manifest, value)
    (Path(value['directory']) / 'mvn').chmod(0o700)
    (Path(value['directory']) / 'mvn').write_text('changed')
    with pytest.raises(ValueError, match='launcher changed'):
        tools.admit(manifest, **context)


def test_private_registration_rejects_link_and_public_mode(registration):
    _, manifest, _ = registration
    manifest.chmod(0o644)
    with pytest.raises(ValueError, match='private'):
        tools.private_json(manifest)
    manifest.chmod(0o600)
    linked = manifest.with_name('linked.json'); linked.symlink_to(manifest)
    with pytest.raises(ValueError, match='links'):
        tools.private_json(linked)


def test_maven_executor_drops_business_credentials_and_writes_only_owned_paths(registration):
    value, _, _ = registration
    command, _ = tools.command(value, 'mvn', ['-B', 'verify'], Path(value['checkout']), {
        'DB_PASSWORD': 'never-forward', 'AWS_SECRET_ACCESS_KEY': 'never-forward',
        'DOORHANDLE_COMPACT_MIGRATION_CONFIG': value['checkout'] + '/work/private.json',
        'JAVA_TOOL_OPTIONS': '-Xmx1536m', 'PATH': '/unsafe/profile'})
    text = '\n'.join(command)
    assert 'never-forward' not in text and '/unsafe/profile' not in text
    assert value['images']['maven'] in command and command[-2:] == ['-B', 'verify']
    assert '--read-only' in command and '--cap-drop' in command and 'ALL' in command
    assert not any('docker.sock' in item for item in command)
    assert 'type=bind,src=/etc/machine-id,dst=/etc/machine-id,readonly' in command
    assert 'DOORHANDLE_COMPACT_MIGRATION_CONFIG=' + value['checkout'] + '/work/private.json' in command


def test_tool_outside_checkout_admits_only_version_without_creating_attempt(registration, tmp_path):
    value, _, _ = registration
    with pytest.raises(ValueError, match='version admission'):
        tools.command(value, 'java', ['-jar', 'business.jar'], tmp_path, {})
    command, _ = tools.command(value, 'java', ['-version'], tmp_path, {})
    assert command[-1] == '-version' and str(Path(value['directory']) / 'probe') in command


def release_registration(registration):
    value, manifest, context = registration
    root = context['root']; inbox = manifest.parent.parent
    release = root / 'releases' / value['release']; work = release / 'work'; work.mkdir(parents=True)
    relative = 'script/jenkins/ecs-tool-runtime.py'
    fixed = release / relative; fixed.parent.mkdir(parents=True)
    raw = Path(tools.__file__).read_bytes(); fixed.write_bytes(raw)
    archive = inbox / 'source.tar.gz'
    with tarfile.open(archive, 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': value['commit']}) as target:
        entry = tarfile.TarInfo(relative); entry.size = len(raw); target.addfile(entry, io.BytesIO(raw))
    value['sourceSha256'] = tools.digest(archive); tools.write_json(manifest, value)
    jar = work / 'candidate-app.jar'; jar.write_bytes(b'same immutable Jenkins jar'); jar.chmod(0o600)
    (inbox / 'application.jar').write_bytes(jar.read_bytes())
    artifact = {'schema': 1, 'kind': 'doorhandle-compact-fixture-artifacts', 'release': value['release'],
        'commit': value['commit'], 'sourceSha256': value['sourceSha256'],
        'applicationJarBytes': jar.stat().st_size, 'applicationJarSha256': tools.digest(jar)}
    tools.write_json(inbox / 'build-artifacts.json', artifact)
    build = {'schemaVersion': 1, 'kind': 'doorhandle-compact-candidate-build', 'status': 'BUILT',
        'release': value['release'], 'commit': value['commit'], 'sourceSha256': value['sourceSha256'], 'ecs': value['identity'],
        'buildArtifactPlanSha256': tools.digest(inbox / 'build-artifacts.json'),
        'applicationJarBytes': jar.stat().st_size, 'applicationJarSha256': tools.digest(jar)}
    tools.write_json(release / 'candidate-build.json', build)
    return value, release, jar


def migration_arguments(jar, config, output):
    return ['-Dloader.main=com.ruanzhu.doorhandle.module.ai.workbench.CompactWorkbenchMigrationCli',
            '-cp', str(jar), 'org.springframework.boot.loader.launch.PropertiesLauncher',
            '--config', str(config), '--output', str(output)]


def test_java_release_binds_exact_source_candidate_and_jenkins_jar(registration):
    value, release, jar = release_registration(registration)
    tools.admit_release(value, release / 'candidate-build.json')
    config = release / 'work/private.json'; config.write_text('{}')
    arguments = migration_arguments(jar, config, release / 'work/receipt.json')
    command, _ = tools.command(value, 'java', arguments, release, {})
    assert 'type=bind,src=' + str(release) + ',dst=' + str(release) + ',readonly' in command
    assert 'type=bind,src=' + str(release / 'work') + ',dst=' + str(release / 'work') in command
    assert not any('docker.sock' in part for part in command)
    assert any('-Djava.io.tmpdir=' + str(release / 'work/home/tmp') in part for part in command)
    with pytest.raises(ValueError, match='overwrite'): tools.admit_release(value, release / 'candidate-build.json')


@pytest.mark.parametrize('mutation', ['jar', 'archive', 'candidate', 'source', 'manifest'])
def test_java_release_rejects_any_changed_pinned_input(registration, mutation):
    value, release, jar = release_registration(registration)
    tools.admit_release(value, release / 'candidate-build.json')
    folder = Path(value['directory'])
    if mutation == 'jar': jar.write_bytes(b'another jar')
    if mutation == 'archive': (folder.parent / 'source.tar.gz').write_bytes(b'another archive')
    if mutation == 'candidate':
        build = tools.private_json(release / 'candidate-build.json'); build['commit'] = 'e' * 40
        tools.write_json(release / 'candidate-build.json', build)
    if mutation == 'source': (release / 'script/jenkins/ecs-tool-runtime.py').write_bytes(b'changed fixed source')
    if mutation == 'manifest':
        changed = dict(value, token='d' * 24); tools.write_json(folder / 'manifest.json', changed)
    with pytest.raises(ValueError): tools.java_release(value)


def test_release_cwd_rejects_other_tools_entrypoints_and_external_inputs(registration, tmp_path):
    value, release, jar = release_registration(registration)
    tools.admit_release(value, release / 'candidate-build.json')
    config = release / 'work/private.json'; config.write_text('{}')
    valid = migration_arguments(jar, config, release / 'work/receipt.json')
    for tool, arguments in [('python', ['-c', 'print(1)']), ('java', ['-jar', str(jar)]),
                            ('java', migration_arguments(jar, config, tmp_path / 'foreign.json'))]:
        with pytest.raises(ValueError): tools.command(value, tool, arguments, release, {})
    assert tools.release_arguments(tools.java_release(value), valid) == release / 'work'


def test_python_executor_owns_mem0_data_and_accepts_only_registered_nested_java(registration, monkeypatch):
    value, _, _ = registration
    socket = Path(value['checkout']) / 'fake-docker-socket'; socket.touch()
    monkeypatch.setattr(tools, 'docker_socket', lambda: socket)
    java = str(Path(value['directory']) / 'java')
    command, _ = tools.command(value, 'python', ['-m', 'pytest'], Path(value['checkout']), {
        'MEM0_DATA_DIR': '/production/data', 'DOORHANDLE_MIGRATION_JAVA': java})
    assert 'DOORHANDLE_MIGRATION_JAVA=' + java in command
    assert 'MEM0_DATA_DIR=' + value['checkout'] + '/work/tool-home/mem0' in command
    assert not any('/production/data' in part for part in command)
    assert 'type=bind,src=' + value['docker'] + ',dst=' + value['docker'] + ',readonly' in command
    assert 'type=bind,src=' + str(socket) + ',dst=/var/run/docker.sock' in command
    assert command[command.index('--memory') + 1] == command[command.index('--memory-swap') + 1]
    with pytest.raises(ValueError, match='immutable registration wrapper'):
        tools.command(value, 'python', ['-m', 'pytest'], Path(value['checkout']), {'DOORHANDLE_MIGRATION_JAVA': '/tmp/java'})


def test_resource_floor_fails_before_execution_and_retains_actual_probe(registration, monkeypatch):
    value, _, _ = registration
    file = Path(value['directory']) / 'resource-failure.json'
    monkeypatch.setattr(tools, 'resource_probe', lambda value: {
        'capturedAtUnix': 1, 'diskAvailableBytes': tools.DISK_FLOOR - 1,
        'memoryAvailableBytes': tools.MEMORY_FLOOR + 1})
    record = {}
    with pytest.raises(RuntimeError, match='resource floor'):
        tools.observe_resources(value, record, file)
    proof = tools.private_json(file)
    assert proof['resourceLimitTriggered'] is True
    assert proof['resourceMonitoring']['latestProbe']['diskAvailableBytes'] == tools.DISK_FLOOR - 1
    assert proof['resourceMonitoring']['capacityVerdict'] == 'CONTROLLED_MEASUREMENT'


@pytest.mark.parametrize('mutation', ['owner', 'source', 'writable-identity', 'foreign-bind', 'privileged'])
def test_cleanup_refuses_foreign_or_changed_container_before_any_stop(registration, monkeypatch, mutation):
    value, _, _ = registration
    observed = row(value)
    if mutation == 'owner': observed['Config']['User'] = '0:0'
    if mutation == 'source': observed['Config']['Labels']['io.doorhandle.source'] = 'f' * 64
    if mutation == 'writable-identity': observed['Mounts'][2]['RW'] = True
    if mutation == 'foreign-bind': observed['Mounts'].append({'Type': 'bind', 'Source': '/data', 'Destination': '/data', 'RW': True})
    if mutation == 'privileged': observed['HostConfig']['Privileged'] = True
    calls = []
    def operation(program, *args, **kwargs):
        calls.append(args)
        assert args[0] == 'inspect'
        return json.dumps([observed]).encode()
    monkeypatch.setattr(tools, 'docker', operation)
    with pytest.raises(ValueError):
        tools.stop_container('/usr/bin/docker', value, 'e' * 64)
    assert len(calls) == 1


def test_cleanup_requires_actual_empty_owned_inventory(registration, monkeypatch):
    value, _, _ = registration
    monkeypatch.setattr(tools, 'identity_guard', lambda identity: None)
    monkeypatch.setattr(tools, 'canonical', lambda path, **kwargs: Path(path))
    calls = []
    def operation(program, *args, **kwargs):
        calls.append(args)
        return b''
    monkeypatch.setattr(tools, 'docker', operation)
    result = tools.cleanup(value)
    assert result['status'] == 'STOPPED' and result['remaining'] == [] and len(calls) == 2


def test_tool_report_exports_only_hashes_exits_and_actual_cleanup(registration):
    value, _, _ = registration
    receipt = {'kind': 'doorhandle-ecs-tool-command', 'release': value['release'], 'commit': value['commit'],
               'sourceSha256': value['sourceSha256'], 'tool': 'java', 'containerId': 'e' * 64,
               'argumentsSha256': hashlib.sha256(b'private argument bytes').hexdigest(),
               'status': 'EXITED', 'exitCode': 0, 'privateSentinel': 'do-not-export',
               'cleanup': {'containerId': 'e' * 64, 'image': value['images']['maven'], 'pid': 0,
                           'exitCode': 0, 'removed': True}}
    file = Path(value['directory']) / 'receipts' / ('doorhandle-ci-tool-' + value['token'] + '-123456789abc.json')
    tools.write_json(file, receipt)
    report = tools.evidence(value, {'status': 'STOPPED', 'remaining': []})
    assert len(report['commands']) == 1 and 'do-not-export' not in json.dumps(report)
    assert remote.allowed_evidence('reports/tool-runtime.json')


def test_owned_java_cleanup_preserves_archived_reports_and_private_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(verifier, 'ROOT', tmp_path)
    output = tmp_path / 'work/evidence'; output.mkdir(parents=True)
    build = output / 'java-suites/suite-001'; build.mkdir(parents=True)
    (build / 'compiled.class').write_bytes(b'compiled')
    report = output / 'java/module/TEST-suite.xml'; report.parent.mkdir(parents=True); report.write_text('<testsuite/>')
    private = output / 'tmp/migration/private.json'; private.parent.mkdir(parents=True); private.write_text('retained')
    result = verifier.remove_owned_build(build, output)
    assert result['status'] == 'REMOVED' and not build.exists()
    assert report.read_text() == '<testsuite/>' and private.read_text() == 'retained'


def test_cleanup_rejects_redirected_top_level_and_unlinks_nested_npm_link(tmp_path, monkeypatch):
    monkeypatch.setattr(verifier, 'ROOT', tmp_path)
    frontend = tmp_path / 'frontend'; frontend.mkdir()
    external = tmp_path / 'protected'; external.mkdir(); (external / 'keep').write_text('original')
    linked = frontend / 'node_modules'; linked.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match='redirected'):
        verifier.remove_owned_build(linked, frontend, allow_links=True)
    linked.unlink(); linked.mkdir(); (linked / 'external-link').symlink_to(external, target_is_directory=True)
    verifier.remove_owned_build(linked, frontend, allow_links=True)
    assert (external / 'keep').read_text() == 'original'


def test_frontend_artifact_hash_changes_with_same_size_content(tmp_path):
    file = tmp_path / 'bundle.js'; file.write_bytes(b'first')
    before = verifier.tree_inventory(tmp_path, hash_files=True)
    file.write_bytes(b'other')
    after = verifier.tree_inventory(tmp_path, hash_files=True)
    assert before['bytes'] == after['bytes'] and before['sha256'] != after['sha256']


def test_fixture_java_keeps_explicit_existing_executable(registration):
    value, _, _ = registration
    file = Path(value['directory']) / 'java'
    assert preparer.fixture_java_executable(str(file), root=None, inbox=None, archive=None,
        tag=None, commit=None, source_sha=None, identity=None) == file


@pytest.mark.parametrize('mutation', ['none', 'uploaded-bytes', 'archive-commit', 'manifest-source'])
def test_fixture_java_sentinel_independently_rechecks_archive_before_import(registration, mutation):
    value, manifest, context = registration
    inbox = Path(value['directory']).parent
    archive = inbox / 'source.tar.gz'
    raw = Path(tools.__file__).read_bytes()
    with tarfile.open(archive, 'w:gz', pax_headers={'comment': 'f' * 40 if mutation == 'archive-commit' else value['commit']}) as package:
        entry = tarfile.TarInfo('script/jenkins/ecs-tool-runtime.py'); entry.size = len(raw)
        package.addfile(entry, io.BytesIO(raw))
    source_sha = tools.digest(archive)
    uploaded = inbox / 'ecs-tool-runtime.py'; uploaded.write_bytes(raw)
    value['sourceSha256'] = 'f' * 64 if mutation == 'manifest-source' else source_sha
    tools.write_json(manifest, value)
    if mutation == 'uploaded-bytes':
        uploaded.write_bytes(b'raise RuntimeError("must never import altered code")')
    arguments = dict(root=context['root'], inbox=inbox, archive=archive, tag=value['release'],
        commit=value['commit'], source_sha=source_sha, identity=value['identity'])
    if mutation == 'none':
        assert preparer.fixture_java_executable('ecs-tool-runtime', **arguments) == Path(value['directory']) / 'java'
    else:
        with pytest.raises(ValueError):
            preparer.fixture_java_executable('ecs-tool-runtime', **arguments)
