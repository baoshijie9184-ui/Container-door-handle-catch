"""Short-lived, fixed-image ECS tool executors; never a Jenkins agent or production exec.

System Python controls Docker. Maven/JDK, Node/npm and Python test dependencies
remain in explicit immutable images. Only this build's checkout is writable;
its original host identity and Docker client are mounted read-only. The socket
is required by the trusted migration tests, not an untrusted-code sandbox.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import time
from urllib.request import ProxyHandler, Request, build_opener


LABEL = 'io.doorhandle.ci-tool-runtime'
SHA = re.compile(r'[a-f0-9]{64}')
IMAGE = re.compile(r'sha256:[a-f0-9]{64}')
TAG = re.compile(r'ci-[0-9]+-[a-f0-9]{12}')
BINARIES = {'java': '/opt/java/openjdk/bin/java', 'mvn': '/usr/share/maven/bin/mvn',
            'node': '/usr/local/bin/node', 'npm': '/usr/local/bin/npm', 'python': '/usr/local/bin/python'}
ENVIRONMENT = {'LANG', 'LC_ALL', 'PYTHONDONTWRITEBYTECODE',
               'PYTHONNOUSERSITE', 'PYTHON_DOTENV_DISABLED', 'DOORHANDLE_ECS_INSTANCE_ID',
               'DOORHANDLE_ECS_MACHINE_ID', 'DOORHANDLE_COMPACT_MIGRATION_TESTS',
               'DOORHANDLE_COMPACT_MIGRATION_CONFIG', 'DOORHANDLE_CI_EVIDENCE_DIR',
               'DOORHANDLE_WORKER_MYSQL_TESTS', 'DOORHANDLE_WORKER_MYSQL_CONFIG',
               'DOORHANDLE_MIGRATION_JAVA'}
MEMORY = {'java': 2, 'mvn': 4, 'node': 2, 'npm': 3, 'python': 4}
DISK_FLOOR = (2 * 1024 + 256) * 1024 ** 2
MEMORY_FLOOR = 1024 ** 3


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def canonical(path, *, exists=True):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts
            and path.resolve(strict=exists) == path, 'Tool paths must be absolute and have no links')
    return path


def private_json(path):
    path = canonical(path)
    value = path.stat()
    require(path.is_file() and value.st_uid == os.getuid() and stat.S_IMODE(value.st_mode) == 0o600
            and 0 < value.st_size <= 1024 * 1024, 'Owned private bounded tool manifest required')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path, value):
    temporary = path.with_name(path.name + '.' + secrets.token_hex(6) + '.tmp')
    with temporary.open('x', encoding='utf8') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
    temporary.replace(path)


def docker(program, *arguments, timeout=45):
    result = subprocess.run([str(program), *arguments], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, check=False)
    require(result.returncode == 0, 'ECS tool Docker operation failed; retain this build evidence')
    return result.stdout


def identity_guard(expected):
    require(sys.platform == 'linux' and Path('/etc/machine-id').read_text().strip() == expected['machineId'],
            'ECS tool machine identity differs')
    opener = build_opener(ProxyHandler({}))
    base = 'http://100.100.100.200/latest/'
    with opener.open(Request(base + 'api/token', data=b'', method='PUT', headers={
            'X-aliyun-ecs-metadata-token-ttl-seconds': '60'}), timeout=3) as response:
        token = response.read(4096).decode()
    with opener.open(Request(base + 'meta-data/instance-id', headers={
            'X-aliyun-ecs-metadata-token': token}), timeout=3) as response:
        require(response.read(256).decode().strip() == expected['instanceId'],
                'ECS tool instance identity differs')


def validate_manifest(value, *, root, tag, commit, source_sha, identity):
    require(isinstance(value, dict), 'Tool manifest must be an object')
    expected = {'schema': 1, 'kind': 'doorhandle-ecs-tool-runtime', 'release': tag,
                'commit': commit, 'sourceSha256': source_sha, 'identity': identity}
    require(all(value.get(key) == entry for key, entry in expected.items())
            and TAG.fullmatch(tag) and re.fullmatch(r'[a-f0-9]{40}', commit)
            and tag.endswith('-' + commit[:12]) and SHA.fullmatch(source_sha),
            'Tool runtime belongs to another commit, source, build or ECS')
    base = canonical(root)
    folder = base / 'inbox' / tag / 'tool-runtime'
    require(value.get('directory') == str(folder)
            and value.get('checkout') == str(base / 'verification' / tag / 'checkout')
            and re.fullmatch(r'[a-f0-9]{24}', value.get('token', ''))
            and value.get('uid') == os.getuid() and value.get('gid') == os.getgid(),
            'Tool runtime directory or execution owner changed')
    images = value.get('images', {})
    require(isinstance(images, dict) and set(images) == {'maven', 'node', 'python'}
            and all(isinstance(v, str) and IMAGE.fullmatch(v) for v in images.values()),
            'Tool images must use complete immutable image IDs')
    files = value.get('files', {})
    require(isinstance(files, dict) and set(files) == {'executor.py', *BINARIES}
            and all(isinstance(v, str) and SHA.fullmatch(v) for v in files.values()), 'Tool launcher source catalog is incomplete')
    return folder


def admit(path, *, root, tag, commit, source_sha, identity, source):
    path = canonical(path)
    value = private_json(path)
    folder = validate_manifest(value, root=root, tag=tag, commit=commit, source_sha=source_sha, identity=identity)
    require(path == folder / 'manifest.json' and canonical(folder) == folder,
            'The private tool registration escaped this build inbox')
    for name, sha in value['files'].items():
        file = canonical(folder / name)
        require(file.is_file() and file.stat().st_uid == os.getuid() and not file.stat().st_mode & 0o022
                and digest(file) == sha, 'A pinned tool launcher changed')
    source_file = Path(__file__).resolve() if Path(source) == folder else Path(source) / 'script/jenkins/ecs-tool-runtime.py'
    require(value['files']['executor.py'] == digest(source_file),
            'The admitted executor differs from the fixed source checkout')
    return value, digest(path)


def release_identity(value, candidate_file):
    """Bind Java migration to the same release, source archive and Jenkins jar."""
    folder = canonical(value['directory'])
    root = folder.parents[2]
    source = canonical(root / 'releases' / value['release'])
    candidate_file = canonical(candidate_file)
    require(candidate_file == source / 'candidate-build.json', 'Java release is outside this immutable build')
    archive = canonical(root / 'inbox' / value['release'] / 'source.tar.gz')
    require(digest(archive) == value['sourceSha256'], 'Java release archive changed')
    # Check original archive bytes, not a Git blob or a CRLF-normalized worktree.
    seen, total = set(), 0
    with tarfile.open(archive, 'r:gz') as package:
        for entry in package:
            name = Path(entry.name)
            require(not name.is_absolute() and '..' not in name.parts and '\\' not in entry.name
                    and (entry.isdir() or entry.isfile()), 'Unsafe Java release source archive')
            if entry.isdir():
                continue
            total += entry.size
            require(entry.name not in seen and name.parts[0] not in ('work', '.git')
                    and 0 <= entry.size <= 128 * 1024 ** 2 and total <= 512 * 1024 ** 2
                    and len(seen) < 50000, 'Java release source archive exceeds its bounds')
            seen.add(entry.name)
            path = canonical(source / name)
            require(path.is_relative_to(source) and path.is_file() and path.stat().st_size == entry.size
                    and digest(path) == hashlib.sha256(package.extractfile(entry).read()).hexdigest(),
                    'Java release differs from the fixed source archive')
        require(package.pax_headers.get('comment') == value['commit']
                and 'script/jenkins/ecs-tool-runtime.py' in seen,
                'Java release is missing its pinned executor/commit')
    require(digest(source / 'script/jenkins/ecs-tool-runtime.py') == value['files']['executor.py'],
            'Java release executor differs from its manifest')
    build = private_json(candidate_file)
    require(all(build.get(key) == expected for key, expected in {
        'schemaVersion': 1, 'kind': 'doorhandle-compact-candidate-build', 'status': 'BUILT',
        'release': value['release'], 'commit': value['commit'], 'sourceSha256': value['sourceSha256'],
        'ecs': value['identity']}.items()), 'Java candidate belongs to another source or ECS')
    artifact_file = canonical(root / 'inbox' / value['release'] / 'build-artifacts.json')
    artifact = private_json(artifact_file)
    jar = canonical(source / 'work/candidate-app.jar')
    input_jar = canonical(root / 'inbox' / value['release'] / 'application.jar')
    require(all(artifact.get(key) == expected for key, expected in {
        'schema': 1, 'kind': 'doorhandle-compact-fixture-artifacts', 'release': value['release'],
        'commit': value['commit'], 'sourceSha256': value['sourceSha256']}.items())
        and build.get('buildArtifactPlanSha256') == digest(artifact_file)
        and type(artifact.get('applicationJarBytes')) is int
        and 0 < artifact['applicationJarBytes'] <= 512 * 1024 ** 2
        and jar.stat().st_size == input_jar.stat().st_size == build.get('applicationJarBytes') == artifact['applicationJarBytes']
        and digest(jar) == digest(input_jar) == build.get('applicationJarSha256') == artifact.get('applicationJarSha256'),
        'Java migration must use the exact Jenkins application jar')
    return {'schema': 1, 'kind': 'doorhandle-ecs-java-release', 'release': value['release'],
            'commit': value['commit'], 'sourceSha256': value['sourceSha256'], 'identity': value['identity'],
            'manifestSha256': digest(folder / 'manifest.json'), 'candidateBuildSha256': digest(candidate_file),
            'source': str(source), 'work': str(canonical(source / 'work')), 'applicationJar': str(jar),
            'applicationJarSha256': digest(jar), 'applicationJarBytes': jar.stat().st_size}


def admit_release(value, candidate_file):
    proof = release_identity(value, candidate_file)
    path = Path(value['directory']) / 'java-release.json'
    require(not path.exists(), 'Java release registration cannot overwrite an existing outcome')
    write_json(path, proof)
    return {'status': 'ADMITTED', 'release': value['release'], 'javaReleaseSha256': digest(path)}


def java_release(value):
    folder = Path(value['directory'])
    file = folder / 'java-release.json'
    require(file.exists(), 'Java release has not been admitted for this build')
    proof = private_json(file)
    expected = release_identity(value, folder.parents[2] / 'releases' / value['release'] / 'candidate-build.json')
    require(proof == expected, 'Pinned Java release, source, jar or manifest changed')
    return proof


def release_arguments(proof, arguments):
    prefix = ['-Dloader.main=com.ruanzhu.doorhandle.module.ai.workbench.CompactWorkbenchMigrationCli',
              '-cp', proof['applicationJar'], 'org.springframework.boot.loader.launch.PropertiesLauncher', '--config']
    require(arguments[:5] == prefix and len(arguments) == 8 and arguments[6] == '--output',
            'Release Java is restricted to the fixed Workbench migration entry point')
    work = canonical(proof['work'])
    config, output = canonical(arguments[5]), canonical(arguments[7], exists=False)
    require(config.is_file() and config.is_relative_to(work) and output.is_relative_to(work)
            and not output.exists(), 'Java migration private inputs/receipt escaped this release work directory')
    return work


def owned_row(program, value, container):
    require(re.fullmatch(r'[a-f0-9]{64}', container), 'Tool container ID is invalid')
    row = json.loads(docker(program, 'inspect', container))[0]
    labels = row.get('Config', {}).get('Labels') or {}
    tool = labels.get('io.doorhandle.tool')
    role = 'maven' if tool in ('java', 'mvn') else 'node' if tool in ('node', 'npm') else 'python'
    host = row['HostConfig']
    require(tool in BINARIES and row['Id'] == container and labels.get(LABEL) == value['token']
            and labels.get('io.doorhandle.release') == value['release']
            and labels.get('io.doorhandle.source') == value['sourceSha256']
            and row['Image'] == value['images'][role]
            and re.fullmatch('/doorhandle-ci-tool-' + value['token'] + '-[a-f0-9]{12}', row.get('Name', ''))
            and host['RestartPolicy']['Name'] == 'no' and host['NetworkMode'] == 'host'
            and host.get('ReadonlyRootfs') is True and host.get('Privileged') is False
            and host.get('Memory') == MEMORY[tool] * 1024 ** 3
            and host.get('MemorySwap') == MEMORY[tool] * 1024 ** 3
            and set(host.get('CapDrop') or ()) == {'ALL'}
            and 'no-new-privileges:true' in (host.get('SecurityOpt') or ())
            and row['Config']['Entrypoint'] == [BINARIES[tool]]
            and row['Config']['User'] == str(value['uid']) + ':' + str(value['gid']),
            'Tool cleanup may only act on this exact build and owner')
    folder = Path(value['directory'])
    allowed = {(str(folder), str(folder)): False,
               (str(folder / 'receipts'), str(folder / 'receipts')): True,
               ('/etc/machine-id', '/etc/machine-id'): False}
    if tool == 'python':
        allowed[(str(docker_socket()), '/var/run/docker.sock')] = True
        allowed[(value['docker'], value['docker'])] = False
    release = None
    if labels.get('io.doorhandle.java-release') is not None:
        require(tool == 'java', 'Only Java may mount an admitted candidate release')
        release = java_release(value)
        require(labels['io.doorhandle.java-release'] == digest(folder / 'java-release.json'),
                'Java container release registration changed')
        allowed[(release['source'], release['source'])] = False
    writable = []
    for mount in row.get('Mounts', []):
        if mount['Type'] == 'tmpfs':
            require(mount['Destination'] == '/tmp', 'Unexpected tool temporary mount')
            continue
        # The selected official tool images declare no persistent data volumes.
        require(mount['Type'] == 'bind', 'Unexpected tool volume cannot be cleaned automatically')
        pair = (mount['Source'], mount['Destination'])
        if pair in allowed:
            require(mount['RW'] is allowed.pop(pair), 'Tool bind permissions changed')
        else:
            permitted = (release['work'],) if release else (value['checkout'], str(folder / 'probe'))
            require(pair[0] == pair[1] and pair[0] in permitted
                    and mount['RW'] is True, 'Tool bind escaped this build checkout')
            writable.append(pair[0])
    require(not allowed and len(writable) == 1, 'Tool mount admission is incomplete')
    return row


def stop_container(program, value, container, *, remove=True):
    row = owned_row(program, value, container)
    if row['State'].get('Paused'):
        docker(program, 'unpause', container)
    if row['State']['Running']:
        docker(program, 'stop', '--time', '10', container, timeout=25)
    final = owned_row(program, value, container)
    require(not final['State']['Running'] and not final['State'].get('Restarting') and final['State']['Pid'] == 0,
            'The owned tool process did not stop')
    if remove:
        # No named volume is accepted; -v only removes image-created anonymous
        # volumes belonging to this disposable container, never bind data.
        docker(program, 'rm', '--volumes', container)
    return {'containerId': container, 'image': final['Image'], 'pid': 0,
            'exitCode': final['State']['ExitCode'], 'removed': remove}


def cleanup(value):
    identity_guard(value['identity'])
    program = canonical(value['docker'])
    containers = docker(program, 'ps', '-aq', '--no-trunc', '--filter', 'label=' + LABEL + '=' + value['token']).decode().split()
    stopped, errors = [], []
    for container in containers:
        try:
            stopped.append(stop_container(program, value, container))
        except BaseException as error:
            # Continue admitting/cleaning the other owned IDs even if one failed.
            errors.append({'containerId': container, 'errorType': type(error).__name__})
    remaining = docker(program, 'ps', '-aq', '--no-trunc', '--filter', 'label=' + LABEL + '=' + value['token']).decode().split()
    if remaining or errors:
        write_json(Path(value['directory']) / 'cleanup-failed.json', {
            'status': 'FAILED_OR_UNKNOWN', 'release': value['release'], 'containers': stopped,
            'remaining': remaining, 'errors': errors})
        raise RuntimeError('Owned tool containers remain or could not be admitted for cleanup')
    return {'status': 'STOPPED', 'release': value['release'], 'containers': stopped,
            'remaining': [], 'manifestSha256': digest(Path(value['directory']) / 'manifest.json')}


def evidence(value, stopped):
    """Export hashes and observed exits only; arguments and private env stay on ECS."""
    require(stopped.get('status') == 'STOPPED' and stopped.get('remaining') == [],
            'Tool evidence requires actual owned-container cleanup')
    folder = Path(value['directory']) / 'receipts'
    files = sorted(folder.iterdir())
    require(len(files) <= 1024, 'Too many tool command receipts')
    commands = []
    for file in files:
        require(re.fullmatch(r'doorhandle-ci-tool-' + value['token'] + r'-[a-f0-9]{12}\.json', file.name),
                'Unexpected tool receipt path')
        item = private_json(file)
        require(item.get('kind') == 'doorhandle-ecs-tool-command'
                and item.get('release') == value['release'] and item.get('commit') == value['commit']
                and item.get('sourceSha256') == value['sourceSha256'] and item.get('tool') in BINARIES
                and (item.get('containerId') is None or SHA.fullmatch(item['containerId']))
                and SHA.fullmatch(item.get('argumentsSha256', '')),
                'Tool command receipt belongs to another execution')
        cleaned = item.get('cleanup')
        if cleaned is not None:
            require(set(cleaned) == {'containerId', 'image', 'pid', 'exitCode', 'removed'}
                    and cleaned['containerId'] == item['containerId'] and cleaned['image'] in value['images'].values()
                    and cleaned['pid'] == 0 and type(cleaned['exitCode']) is int and cleaned['removed'] is True,
                    'Tool command cleanup receipt is invalid')
        require(item.get('status') in ('EXITED', 'FAILED_OR_UNKNOWN')
                and (item.get('exitCode') is None or type(item['exitCode']) is int),
                'Tool command exit status is invalid')
        commands.append({'receiptSha256': digest(file), 'tool': item['tool'], 'containerId': item['containerId'],
                         'argumentsSha256': item['argumentsSha256'], 'status': item['status'],
                         'exitCode': item.get('exitCode'), 'cleanup': cleaned,
                         'resourceLimitTriggered': item.get('resourceLimitTriggered', False),
                         'resourceMonitoring': item.get('resourceMonitoring')})
    return {'schema': 1, 'kind': 'doorhandle-ecs-tool-evidence', 'release': value['release'],
            'commit': value['commit'], 'sourceSha256': value['sourceSha256'],
            'manifestSha256': digest(Path(value['directory']) / 'manifest.json'),
            'images': value['images'], 'commands': commands, 'cleanup': stopped,
            'capacityVerdict': 'CONTROLLED_MEASUREMENT'}


def safe_environment(value, original, directory):
    env = {key: entry for key, entry in original.items() if key in ENVIRONMENT}
    require('DOORHANDLE_MIGRATION_JAVA' not in env
            or env['DOORHANDLE_MIGRATION_JAVA'] == str(Path(value['directory']) / 'java'),
            'Migration Java must be this immutable registration wrapper')
    home = directory / 'work' / 'tool-home' if directory == Path(value['checkout']) else directory / 'home'
    temporary = home / 'tmp'
    temporary.mkdir(mode=0o700, parents=True, exist_ok=True)
    env.update(HOME=str(home), TMPDIR=str(temporary), PYTHONDONTWRITEBYTECODE='1',
               PYTHONNOUSERSITE='1', PYTHON_DOTENV_DISABLED='1', PYTHONPATH='',
               npm_config_cache=str(home / 'npm-cache'),
               DOORHANDLE_ECS_INSTANCE_ID=value['identity']['instanceId'],
               DOORHANDLE_ECS_MACHINE_ID=value['identity']['machineId'])
    return env, home


def docker_socket():
    path = canonical(Path('/var/run/docker.sock').resolve(strict=True))
    require(stat.S_ISSOCK(path.stat().st_mode), 'The existing ECS Docker socket is unavailable')
    return path


def command(value, tool, arguments, cwd, environment):
    require(tool in BINARIES and isinstance(arguments, list) and all(isinstance(v, str) and '\x00' not in v for v in arguments),
            'Only the registered tool command is allowed')
    checkout = Path(value['checkout'])
    folder = canonical(value['directory'])
    actual = canonical(cwd)
    release = None
    if actual == checkout or actual.is_relative_to(checkout):
        canonical(checkout)
        writable = checkout
    elif tool == 'java' and actual == folder.parents[2] / 'releases' / value['release']:
        release = java_release(value)
        writable = release_arguments(release, arguments)
    else:
        require(arguments in (['-version'], ['--version'], ['-v']),
                'Tool execution outside this checkout is restricted to version admission')
        writable = folder / 'probe'
        writable.mkdir(mode=0o700, exist_ok=True)
        actual = writable
    env, home = safe_environment(value, environment, writable)
    role = 'maven' if tool in ('java', 'mvn') else 'node' if tool in ('node', 'npm') else 'python'
    image = value['images'][role]
    name = 'doorhandle-ci-tool-' + value['token'] + '-' + secrets.token_hex(6)
    args = [value['docker'], 'create', '-i', '--name', name, '--network', 'host', '--restart', 'no',
            '--user', str(value['uid']) + ':' + str(value['gid']), '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--pids-limit', '512', '--cpus', '2',
            '--memory', str(MEMORY[tool]) + 'g', '--memory-swap', str(MEMORY[tool]) + 'g',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=536870912',
            '--log-driver', 'json-file', '--log-opt', 'max-size=10m', '--log-opt', 'max-file=1',
            '--label', LABEL + '=' + value['token'], '--label', 'io.doorhandle.release=' + value['release'],
            '--label', 'io.doorhandle.source=' + value['sourceSha256'], '--label', 'io.doorhandle.tool=' + tool,
            '--workdir', str(actual), '--entrypoint', BINARIES[tool]]
    binds = [(str(writable), str(writable), False), (str(folder), str(folder), True),
             (str(folder / 'receipts'), str(folder / 'receipts'), False),
             ('/etc/machine-id', '/etc/machine-id', True)]
    if release:
        binds.append((release['source'], release['source'], True))
        args += ['--label', 'io.doorhandle.java-release=' + digest(folder / 'java-release.json')]
    # The probe lies beneath the read-only registration folder; add the more
    # specific writable bind after its parent so only probe output can change.
    binds.sort(key=lambda item: len(Path(item[1]).parts))
    if tool == 'python':
        socket = docker_socket()
        args += ['--group-add', str(socket.stat().st_gid)]
        binds += [(str(socket), '/var/run/docker.sock', False), (value['docker'], value['docker'], True)]
    for source, target, readonly in binds:
        require(',' not in source and ',' not in target, 'Docker bind paths cannot contain commas')
        args += ['--mount', 'type=bind,src=' + source + ',dst=' + target + (',readonly' if readonly else '')]
    if role == 'maven':
        env.update(JAVA_HOME='/opt/java/openjdk', PATH='/opt/java/openjdk/bin:/usr/local/bin:/usr/bin:/bin',
                   MAVEN_CONFIG=str(home / '.m2'))
        env['JAVA_TOOL_OPTIONS'] = ('-Xmx1536m -XX:MaxMetaspaceSize=512m -Duser.home=' + str(home)
            + ' -Djava.io.tmpdir=' + str(home / 'tmp') + ' -Djansi.tmpdir=' + str(home / 'tmp'))
    else:
        env['PATH'] = '/usr/local/bin:/usr/bin:/bin'
    if role == 'python':
        data = home / 'mem0'
        data.mkdir(mode=0o700, exist_ok=True)
        env.update(MEM0_DATA_DIR=str(data), MEM0_TELEMETRY='false', ANONYMIZED_TELEMETRY='false')
    for key, entry in sorted(env.items()):
        require('\x00' not in entry, 'Invalid tool environment')
        args += ['--env', key + '=' + entry]
    return args + [image, *arguments], name


def launch(path, tool, arguments):
    require(sys.platform == 'linux', 'Tool processes may only execute on ECS')
    value = private_json(path)
    root = Path(value['directory']).parents[2]
    value, _ = admit(path, root=root, tag=value['release'], commit=value['commit'], source_sha=value['sourceSha256'],
                     identity=value['identity'], source=Path(value['directory']))
    identity_guard(value['identity'])
    return launch_admitted(value, tool, arguments)


def resource_probe(value):
    disk = os.statvfs(value['directory'])
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        name, _, entry = line.partition(':')
        if name == 'MemAvailable':
            memory[name] = int(entry.split()[0]) * 1024
    require('MemAvailable' in memory, 'ECS memory availability cannot be measured')
    return {'capturedAtUnix': time.time(), 'diskAvailableBytes': disk.f_bavail * disk.f_frsize,
            'memoryAvailableBytes': memory['MemAvailable']}


def observe_resources(value, record, file):
    probe = resource_probe(value)
    monitoring = record.setdefault('resourceMonitoring', {
        'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'pollIntervalSeconds': 2,
        'diskFloorBytes': DISK_FLOOR, 'memoryFloorBytes': MEMORY_FLOOR, 'samples': 0,
        'minimumDiskAvailableBytes': probe['diskAvailableBytes'],
        'minimumMemoryAvailableBytes': probe['memoryAvailableBytes']})
    monitoring['samples'] += 1
    monitoring['latestProbe'] = probe
    for source, target in (('diskAvailableBytes', 'minimumDiskAvailableBytes'),
                           ('memoryAvailableBytes', 'minimumMemoryAvailableBytes')):
        monitoring[target] = min(monitoring[target], probe[source])
    if probe['diskAvailableBytes'] < DISK_FLOOR or probe['memoryAvailableBytes'] < MEMORY_FLOOR:
        record.update(status='FAILED_OR_UNKNOWN', resourceLimitTriggered=True)
        write_json(file, record)
        raise RuntimeError('Owned tool resource floor reached; this attempt must stop')


def launch_admitted(value, tool, arguments):
    args, name = command(value, tool, arguments, Path.cwd(), dict(os.environ))
    program = canonical(value['docker'])
    record = {'kind': 'doorhandle-ecs-tool-command', 'release': value['release'], 'commit': value['commit'],
              'sourceSha256': value['sourceSha256'], 'tool': tool, 'containerId': None,
              'argumentsSha256': hashlib.sha256(json.dumps(arguments, ensure_ascii=True).encode()).hexdigest(),
              'startedAtUnix': time.time(), 'status': 'FAILED_OR_UNKNOWN'}
    file = Path(value['directory']) / 'receipts' / (name + '.json')
    write_json(file, record)
    process, container = None, None
    try:
        observe_resources(value, record, file)
        container = docker(program, *args[1:]).decode().strip()
        require(re.fullmatch(r'[a-f0-9]{64}', container), 'Docker did not return an owned tool ID')
        record['containerId'] = container; write_json(file, record)
        owned_row(program, value, container)
        process = subprocess.Popen([str(program), 'start', '-a', '-i', container])
        while True:
            observe_resources(value, record, file)
            try:
                result = process.wait(timeout=2)
                break
            except subprocess.TimeoutExpired:
                pass
        observe_resources(value, record, file)
        observed = owned_row(program, value, container)
        require(not observed['State']['Running'] and not observed['State'].get('OOMKilled')
                and result == observed['State']['ExitCode'],
                'Tool attachment result differs from the actual container')
        record.update(status='EXITED', exitCode=result)
        return result
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=3)
        try:
            if container and re.fullmatch(r'[a-f0-9]{64}', container):
                record['cleanup'] = stop_container(program, value, container)
            if record.get('resourceLimitTriggered'):
                record['resourceAbortCleanup'] = cleanup(value)
        finally:
            record['finishedAtUnix'] = time.time()
            write_json(file, record)


def prepare(args):
    require(sys.platform == 'linux', 'Tool preparation may only execute on ECS')
    root = canonical(args.root)
    require(TAG.fullmatch(args.tag) and args.tag.endswith('-' + args.commit[:12])
            and re.fullmatch(r'[a-f0-9]{40}', args.commit) and SHA.fullmatch(args.source_sha256),
            'Exact source and release are required')
    inbox = canonical(root / 'inbox' / args.tag)
    archive = canonical(inbox / 'source.tar.gz')
    require(digest(archive) == args.source_sha256, 'Tool preparation source archive differs')
    original = Path(__file__).resolve()
    with tarfile.open(archive, 'r:gz') as package:
        require(package.pax_headers.get('comment') == args.commit, 'Tool source commit differs')
        info = package.getmember('script/jenkins/ecs-tool-runtime.py')
        require(info.isfile() and info.size <= 1024 * 1024, 'Pinned executor source is missing')
        require(hashlib.sha256(package.extractfile(info).read()).hexdigest() == digest(original),
                'Uploaded executor differs from the pinned archive source')
    expected = {'instanceId': args.instance_id, 'machineId': args.machine_id, 'executionLocation': 'ECS'}
    require(re.fullmatch(r'i-[a-z0-9]+', args.instance_id) and re.fullmatch(r'[a-f0-9]{32}', args.machine_id),
            'Explicit ECS identity is required')
    identity_guard(expected)
    folder = inbox / 'tool-runtime'
    require(not folder.exists(), 'Use a fresh build for tool preparation')
    folder.mkdir(mode=0o700)
    program = canonical(shutil.which('docker'))
    images = {'maven': args.maven_image, 'node': args.node_image, 'python': args.python_image}
    for role, image in images.items():
        require(IMAGE.fullmatch(image), 'Use complete existing tool image IDs')
        row = json.loads(docker(program, 'image', 'inspect', image))[0]
        require(row['Id'] == image and row['Os'] == 'linux', 'Existing immutable tool image is unavailable')
        require(not row['Config'].get('Volumes'), 'Tool images must not declare persistent data volumes')
        for entry in row['Config'].get('Env') or []:
            key, _, content = entry.partition('=')
            require(not content or not re.search(r'PASSWORD|PASSWD|SECRET|API_KEY|ACCESS_KEY|TOKEN|DATABASE_URL|DB_URL', key, re.I),
                    'Tool image must not contain credentials or business database connections')
        if role == 'python':
            require((row['Config'].get('Labels') or {}).get('io.doorhandle.ci-tools') == 'python-v1',
                    'Python tools require the reviewed dependency image label')
    (folder / 'receipts').mkdir(mode=0o700)
    executor = folder / 'executor.py'
    shutil.copyfile(original, executor); os.chmod(executor, 0o500)
    files = {'executor.py': digest(executor)}
    for tool in BINARIES:
        wrapper = folder / tool
        wrapper.write_text('#!/usr/bin/env -S python3 -I -B\nimport runpy,sys\nsys.argv=['
                           + repr(str(executor)) + ',"launch","--manifest",' + repr(str(folder / 'manifest.json'))
                           + ',"--tool",' + repr(tool) + ',"--",*sys.argv[1:]]\nrunpy.run_path('
                           + repr(str(executor)) + ',run_name="__main__")\n', encoding='utf8')
        os.chmod(wrapper, 0o500); files[tool] = digest(wrapper)
    value = {'schema': 1, 'kind': 'doorhandle-ecs-tool-runtime', 'release': args.tag, 'commit': args.commit,
             'sourceSha256': args.source_sha256, 'identity': expected, 'directory': str(folder),
             'checkout': str(root / 'verification' / args.tag / 'checkout'), 'token': secrets.token_hex(12),
             'uid': os.getuid(), 'gid': os.getgid(), 'docker': str(program), 'images': images, 'files': files}
    path = folder / 'manifest.json'; write_json(path, value)
    return {'status': 'PREPARED', 'release': args.tag, 'manifest': str(path), 'manifestSha256': digest(path),
            'java': str(folder / 'java'), 'tools': {key: str(folder / key) for key in BINARIES}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    make = sub.add_parser('prepare')
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id', 'maven-image', 'node-image', 'python-image'):
        make.add_argument('--' + name, required=True)
    call = sub.add_parser('launch'); call.add_argument('--manifest', required=True); call.add_argument('--tool', choices=BINARIES, required=True)
    call.add_argument('arguments', nargs=argparse.REMAINDER)
    clean = sub.add_parser('cleanup'); clean.add_argument('--manifest', required=True)
    release = sub.add_parser('admit-release'); release.add_argument('--manifest', required=True)
    release.add_argument('--candidate-build', required=True)
    args = parser.parse_args()
    for name in (signal.SIGTERM, signal.SIGINT):
        signal.signal(name, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        if args.action == 'prepare':
            print(json.dumps(prepare(args))); return 0
        if args.action == 'launch':
            values = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
            return launch(args.manifest, args.tool, values)
        require(sys.platform == 'linux', 'Tool cleanup is ECS-only')
        value = private_json(args.manifest)
        value, _ = admit(args.manifest, root=Path(value['directory']).parents[2], tag=value['release'],
                         commit=value['commit'], source_sha=value['sourceSha256'], identity=value['identity'],
                         source=Path(value['directory']))
        if args.action == 'admit-release':
            identity_guard(value['identity'])
            print(json.dumps(admit_release(value, args.candidate_build))); return 0
        print(json.dumps(cleanup(value))); return 0
    except BaseException as error:
        print(json.dumps({'status': 'FAILED_OR_UNKNOWN', 'errorType': type(error).__name__}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
