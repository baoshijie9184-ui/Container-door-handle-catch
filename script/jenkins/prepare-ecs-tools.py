"""Prepare this fixed Jenkins source's Python dependency image on the admitted ECS.

Only the source-controlled recipe and pinned requirements are extracted. A
bounded, owned pip container installs dependencies; no project test or business
process is started. Source, reports, stopped containers and images are retained.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import threading
import time
from urllib.request import ProxyHandler, Request, build_opener


GIB = 1024 ** 3
MIB = 1024 ** 2
RESERVE = 2 * GIB
OVERSHOOT = 256 * MIB
MAX_GROWTH = 2 * GIB
INTERVAL = 1.0
LABEL = 'io.doorhandle.ci-tool-preparation'
INSTANCE = 'i-2zeieuov2aum486jm1ek'
MACHINE = '1ebe8f77e3104ab6a49a9386e38abd20'
BASE = 'sha256:d9489c281e69291fec34ee6bd470197c4c41d06fdc29a822d3a5aaad66f1b2fa'
MAVEN = 'sha256:f58d59b6273e785ac0a4477f6e9b5ba1d7731c75b906c0f7b34076f1851318cc'
NODE = 'sha256:44fce696f38ba8c987c4db89954051000bbd05ffd8d8659ba15ed4a8602e937f'
# This dependency image was installed and pip-checked by Jenkins #97. Its
# stdout contained Docker 29's deprecation notice before the immutable ID.
CACHED_PYTHON = 'sha256:4e8c4a575022713b56227dbf8a4df04e37bf6659e7d1828cd29a884368a1c66d'
CACHED_RECIPE = '86cc3a2b9cdf5e809a32f59fd7449aa1807a3c51df5cc5c044c62878f111189d'
CACHED_RELEASE = 'ci-97-abedbf81a73d'
CACHED_COMMIT = 'abedbf81a73d1b7e28f660e3e72aa10cfbdce747'
CACHED_SOURCE = '8683361ca092fb85b6497109f9dd6d54f0cbd5712d96be55d5c9bc957a0a1568'
CACHED_REQUIREMENTS = 'dba9e875042c857fd97eacb52c72a85a239a132c534fe2efee0573d8013da70d'
CACHED_PINS = {'pytest': '8.4.2', 'pymysql': '1.1.2', 'pillow': '11.3.0',
               'onnx': '1.17.0', 'python-multipart': '0.0.20', 'oss2': '2.19.1',
               'confluent-kafka': '2.10.1', 'mcp': '1.29.0', 'scipy': '1.15.3'}
CACHED_PROOFS = {
    'owner.json': 'ef68f3412d4b02aa62e72e8a38c201fd0a412f139fae4cdae354f49f725bee95',
    'reports/pip-install.json': '4b2b83db99827ac39cc34b831689cb92d27d4c097fc4e822d847fa38e2537da0',
    'reports/installed-versions.json': 'c8e26a35f0bf756e18dd7a3c31d0d3843f33281b8486c5ad9145f4d926f10ac4',
    'commit.stdout': '318ab009265cd910acc49886fb42b926bd8db2c9a2e4325376a0cbbd0530b15f',
    'prepare-ecs-tools.py': CACHED_RECIPE,
    'python-test-requirements.txt': CACHED_REQUIREMENTS,
    'pip.log': 'c3d61e1515148f47a74acc84701ceaa891cecf4f9c997d9b27edccdc15f3d0bc',
}
PYTHON = '/usr/local/bin/python'
CONFIG_GROWTH_BOUND = 2 * MIB
RECIPE = 'script/jenkins/prepare-ecs-tools.py'
REQUIREMENTS = 'script/jenkins/python-test-requirements.txt'
MEM0_REQUIREMENTS = 'deploy/mem0/requirements.txt'
MEM0_PACKAGES = frozenset(('mem0ai', 'chromadb', 'fastapi', 'uvicorn', 'python-dotenv', 'openai',
    'pydantic', 'cryptography', 'qdrant-client', 'opentelemetry-api', 'opentelemetry-sdk',
    'opentelemetry-exporter-otlp-proto-http', 'prometheus-client'))
BUILDER_RECIPES = {'script/docker/compact-build-resources.py', 'script/docker/compact-image-inputs.py', 'deploy/buildkit/LICENSE'}
SHA = re.compile(r'[a-f0-9]{64}')
IMAGE = re.compile(r'sha256:[a-f0-9]{64}')
TAG = re.compile(r'ci-[1-9][0-9]*-[a-f0-9]{12}')
SENSITIVE = re.compile(r'PASSWORD|PASSWD|SECRET|API_KEY|ACCESS_KEY|TOKEN|DATABASE_URL|DB_URL', re.I)


class PreparationError(ValueError):
    """An authored diagnostic safe to include in the public CI receipt."""


class PreparationPending(PreparationError):
    """The same owned request has no final completion evidence yet."""


def require(condition, message):
    if not condition:
        raise PreparationError(message)


def validate_builder_input_arguments(args):
    """Admit the optional public archive request before creating any resources."""
    archive, checksum, size = (getattr(args, name, None) for name in
                               ('buildkit_archive', 'buildkit_archive_sha256', 'buildkit_archive_bytes'))
    if archive is None and checksum is None and size is None:
        return None
    require(all(value is not None for value in (archive, checksum, size))
            and getattr(args, 'prepare_candidate_builder', False) is True,
            'BuildKit archive arguments must be complete and request candidate builder preparation')
    require(type(checksum) is str and SHA.fullmatch(checksum)
            and type(size) is int and 0 < size <= 128 * MIB,
            'BuildKit archive requires a full SHA256 and bounded positive byte count')
    root_value = str(args.root); root = PurePosixPath(root_value)
    require(root.is_absolute() and str(root) == root_value and '..' not in root.parts
            and '\\' not in root_value and type(archive) is str
            and archive == str(root / 'build-inputs' / 'buildkit-v0.34.2' / (checksum + '.tar')),
            'BuildKit archive must use the exact owned fixed-version cache path')
    return {'file': archive, 'sha256': checksum, 'bytes': size}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(MIB), b''):
            result.update(chunk)
    return result.hexdigest()


def canonical(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path
            and all(not item.is_symlink() for item in (path, *path.parents)),
            'Existing canonical path without symbolic links required')
    return path


def write_json(path, value):
    require(not path.exists() and not path.is_symlink(), 'Do not replace existing evidence')
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf8') as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=True, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())


def identity(args):
    require(sys.platform == 'linux' and args.instance_id == INSTANCE and args.machine_id == MACHINE,
            'Only the explicitly admitted original monolith ECS may prepare tools')
    require(Path('/etc/machine-id').read_text().strip() == args.machine_id, 'Machine identity differs')
    opener = build_opener(ProxyHandler({})); base = 'http://100.100.100.200/latest/'
    with opener.open(Request(base + 'api/token', data=b'', method='PUT', headers={
            'X-aliyun-ecs-metadata-token-ttl-seconds': '60'}), timeout=3) as response:
        token = response.read(4096).decode()
    with opener.open(Request(base + 'meta-data/instance-id', headers={
            'X-aliyun-ecs-metadata-token': token}), timeout=3) as response:
        require(response.read(256).decode().strip() == args.instance_id, 'Instance identity differs')
    return {'instanceId': args.instance_id, 'machineId': args.machine_id, 'executionLocation': 'ECS'}


def scan_archive_inputs(archive, commit, expected_sha, own_recipe, include_builder=False, include_mem0_runtime=False):
    require(digest(archive) == expected_sha, 'Fixed source archive digest differs')
    found, seen, total = {}, set(), 0
    expected = ({RECIPE, REQUIREMENTS} | (BUILDER_RECIPES if include_builder else set())
                | ({MEM0_REQUIREMENTS} if include_mem0_runtime else set()))
    with tarfile.open(archive, 'r:gz') as package:
        for member in package:
            name = member.name
            path = Path(name)
            require(not path.is_absolute() and '\\' not in name and '..' not in path.parts
                    and path.parts and path.parts[0] not in ('work', '.git', 'artifacts')
                    and (member.isfile() or member.isdir()) and name not in seen,
                    'Unsafe source archive member')
            seen.add(name); total += member.size
            require(len(seen) <= 50000 and member.size <= 32 * MIB and total <= 512 * MIB,
                    'Source archive exceeds bounded inspection')
            if name in expected:
                require(member.isfile() and 0 < member.size <= MIB, 'Bounded regular tool source required')
                with package.extractfile(member) as stream:
                    content = stream.read(MIB + 1)
                require(len(content) == member.size, 'Tool source member size differs')
                found[name] = content
        require(package.pax_headers.get('comment') == commit, 'Git archive PAX commit differs')
    require(set(found) == expected, 'Fixed source recipe or requirements is missing')
    require(hashlib.sha256(found[RECIPE]).hexdigest() == digest(own_recipe),
            'Uploaded tool provisioner is not this fixed source recipe')
    return found


def archive_inputs(archive, destination, commit, expected_sha, own_recipe, include_builder=False, include_mem0_runtime=False):
    found = scan_archive_inputs(archive, commit, expected_sha, own_recipe, include_builder, include_mem0_runtime)
    for source_name, content in found.items():
        target = destination / Path(source_name).name
        with target.open('xb') as output:
            os.chmod(target, 0o600); output.write(content)
    return {name: hashlib.sha256(content).hexdigest() for name, content in found.items()}


def requirements(path):
    result = {}
    for line in Path(path).read_text('utf8').splitlines():
        value = line.strip()
        if not value or value.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][A-Za-z0-9.!+_-]*)', value)
        require(match is not None, 'Only explicit pinned package versions are allowed')
        key = re.sub(r'[-_.]+', '-', match[1]).lower()
        require(key not in result, 'Duplicate pinned package requirement')
        result[key] = match[2]
    require(result and len(result) <= 64, 'Bounded explicit Python tool requirements required')
    return result


def validate_mem0_requirements(pinned, runtime):
    """Current source is explicit: no inherited old-base SDK or cached 9-pin claim."""
    require(set(runtime) == MEM0_PACKAGES,
            'Current native Mem0 runtime requires exactly its 13 admitted pinned packages')
    require(all(pinned.get(name) == version for name, version in runtime.items()),
            'Python tools must include every exact current Mem0 runtime version')
    return runtime


def commit_image_id(output):
    """Docker may prepend an authored CLI warning on stdout; bind one full ID."""
    matches = [line.strip() for line in output.splitlines() if IMAGE.fullmatch(line.strip())]
    require(len(matches) == 1, 'Tool image commit did not return one immutable image ID')
    return matches[0]


def validate_dependency_layers(cached, repaired):
    # Docker 29's Size includes image metadata: replacing a long default Cmd
    # can reduce Size while every filesystem DiffID stays exactly identical.
    require(repaired['RootFS']['Layers'] == cached['RootFS']['Layers']
            and abs(repaired['Size'] - cached['Size']) <= CONFIG_GROWTH_BOUND,
            'Config-only repair changed dependency filesystem layers')


INSTALL = r'''
import importlib.metadata,json,pathlib,subprocess,sys
report=pathlib.Path('/ci-report')
args=[sys.executable,'-I','-m','pip','--isolated','--disable-pip-version-check','--no-input']
# Use the same HTTPS mirror as compose.cloud.yml; isolated pip cannot inherit another index.
code=subprocess.call(args+['install','--index-url','https://mirrors.aliyun.com/pypi/simple','--no-cache-dir','--no-compile','--report',str(report/'pip-install.json'),'-r','/ci-input/requirements.txt'])
if code: raise SystemExit(code)
code=subprocess.call(args+['check'])
if code: raise SystemExit(code)
expected=json.loads(sys.argv[1])
versions={name:importlib.metadata.version(name) for name in expected}
if versions != expected: raise SystemExit('Pinned installed versions differ')
(report/'installed-versions.json').write_text(json.dumps(versions,sort_keys=True),encoding='utf8')
'''


def installer_command(pinned):
    return ['-I', '-B', '-c', INSTALL, json.dumps(pinned, sort_keys=True)]


def tool_changes(sources, *, uid, gid, commit, source_sha):
    # Docker 29 merges empty ENTRYPOINT/CMD changes with the container config.
    # Explicit nonempty inert defaults cannot inherit the pip install command.
    return ['USER ' + str(uid) + ':' + str(gid),
            'ENTRYPOINT ["' + PYTHON + '"]', 'CMD ["--version"]', 'WORKDIR /',
            'LABEL io.doorhandle.ci-tools=python-v1',
            'LABEL io.doorhandle.source=' + source_sha,
            'LABEL io.doorhandle.commit=' + commit,
            'LABEL io.doorhandle.ci-tools-requirements-sha256=' + sources[REQUIREMENTS],
            'LABEL io.doorhandle.ci-tools-recipe-sha256=' + sources[RECIPE]]


def validate_tool_config(cfg, sources, *, uid, gid, commit, source_sha):
    labels = cfg.get('Labels') or {}
    require(cfg.get('User') == str(uid) + ':' + str(gid)
            and cfg.get('Entrypoint') == [PYTHON] and cfg.get('Cmd') == ['--version']
            and cfg.get('Healthcheck', {}).get('Test') == ['NONE'] and cfg.get('WorkingDir') == '/'
            and not cfg.get('Volumes') and labels.get('io.doorhandle.ci-tools') == 'python-v1'
            and labels.get('io.doorhandle.source') == source_sha
            and labels.get('io.doorhandle.commit') == commit
            and labels.get('io.doorhandle.ci-tools-requirements-sha256') == sources[REQUIREMENTS]
            and labels.get('io.doorhandle.ci-tools-recipe-sha256') == sources[RECIPE],
            'Committed tool configuration or source labels differ')


def metadata_arguments(name, token, release, source_sha, *, uid, gid):
    return ['create', '--pull', 'never', '--name', name, '--user', str(uid) + ':' + str(gid),
            '--label', LABEL + '=' + token, '--label', 'io.doorhandle.release=' + release,
            '--label', 'io.doorhandle.source=' + source_sha,
            '--label', 'io.doorhandle.ci-tool-preparation-role=metadata-only',
            '--restart', 'no', '--read-only', '--network', 'none', '--no-healthcheck', '--workdir', '/',
            '--memory', str(512 * MIB), '--memory-swap', str(512 * MIB), '--cpus', '1',
            '--pids-limit', '16', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '--entrypoint', PYTHON, CACHED_PYTHON, '--version']


def create_arguments(name, token, release, source_sha, requirement_path, report_path, expected):
    return ['create', '--pull', 'never', '--name', name, '--user', '0:0',
            '--label', LABEL + '=' + token, '--label', 'io.doorhandle.release=' + release,
            '--label', 'io.doorhandle.source=' + source_sha, '--restart', 'no',
            '--memory', str(2 * GIB), '--memory-swap', str(2 * GIB), '--cpus', '2',
            '--pids-limit', '256', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '--network', 'bridge', '--no-healthcheck', '--workdir', '/',
            '--log-driver', 'json-file', '--log-opt', 'max-size=10m', '--log-opt', 'max-file=1',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=268435456',
            '--mount', 'type=bind,src=' + str(requirement_path) + ',dst=/ci-input/requirements.txt,readonly',
            '--mount', 'type=bind,src=' + str(report_path) + ',dst=/ci-report',
            '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', 'PYTHONNOUSERSITE=1',
            '--env', 'PIP_CONFIG_FILE=/dev/null', '--entrypoint', '/usr/local/bin/python',
            BASE, *installer_command(expected)]


def resource_check(baseline, available, owned_writable, *, required_growth=0):
    host_growth = max(0, baseline - available)
    require(available >= RESERVE + OVERSHOOT + required_growth,
            'Tool preparation would consume the real disk reserve')
    require(max(host_growth, owned_writable) + required_growth <= MAX_GROWTH,
            'Tool preparation exceeded its bounded disk growth')
    return host_growth


def admit_fresh_install(baseline, available):
    """Reserve the unused part of the same cumulative disk-growth envelope."""
    observed_growth = resource_check(baseline, available, 0)
    remaining_growth = MAX_GROWTH - observed_growth
    require(remaining_growth > 0, 'No bounded disk growth remains for dependency installation')
    resource_check(baseline, available, 0, required_growth=remaining_growth)
    return remaining_growth


class Preparation:
    def __init__(self, args):
        validate_builder_input_arguments(args)
        self.args = args; self.identity = identity(args)
        require(TAG.fullmatch(args.tag) and re.fullmatch(r'[a-f0-9]{40}', args.commit)
                and args.tag.endswith('-' + args.commit[:12]) and SHA.fullmatch(args.source_sha256),
                'Fixed commit, source archive hash and release are required')
        self.root = canonical(args.root)
        require(re.fullmatch(r'/(?:home|srv|opt)/[A-Za-z0-9_./-]+', str(self.root))
                and self.root.is_dir() and self.root.stat().st_uid == os.getuid()
                and not self.root.stat().st_mode & 0o022, 'Owned existing release root required')
        self.inbox = canonical(self.root / 'inbox' / args.tag)
        require(self.inbox.is_dir() and self.inbox.stat().st_uid == os.getuid()
                and not self.inbox.stat().st_mode & 0o022, 'Owned build inbox required')
        self.archive = canonical(self.inbox / 'source.tar.gz')
        metadata = self.archive.stat()
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid()
                and metadata.st_nlink == 1 and 0 < metadata.st_size <= 512 * MIB,
                'Owned bounded source archive required')
        self.docker = canonical(shutil.which('docker'))
        self.folder = self.inbox / 'python-tools'
        require(not self.folder.exists() and not self.folder.is_symlink(), 'Use a fresh Jenkins build for Python tool preparation')
        self.token = secrets.token_hex(12)
        self.name = 'doorhandle-ci-python-' + self.token
        self.container = None; self.image = None
        self.metadata_container = None
        self.metadata_name = self.name + '-metadata'
        self.preparation_role = 'pip'
        self.baseline = self.available()
        resource_check(self.baseline, self.baseline, 0, required_growth=2 * MIB)
        self.folder.mkdir(mode=0o700)
        self.reports = self.folder / 'reports'; self.reports.mkdir(mode=0o733)
        os.chmod(self.reports, 0o733)
        # UID 0 has no DAC override/chown capability. Only these new, public pip
        # evidence files are writable inside the private owned parent directory.
        for filename in ('pip-install.json', 'installed-versions.json'):
            with (self.reports / filename).open('xb') as stream:
                os.chmod(stream.name, 0o666)
        self.observed = {'hostDiskGrowthPeakBytes': 0, 'containerWritablePeakBytes': 0,
                         'memoryPeakBytes': 0, 'oomKilled': False, 'samples': 0}
        self.snapshot = self.folder / 'resource-samples.jsonl'
        self.sample_stream = None
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.watch_stop = threading.Event()
        self.watch_failed = threading.Event()
        self.watcher = None

    def available(self):
        info = os.statvfs(self.inbox)
        return info.f_bavail * info.f_frsize

    def call(self, *arguments, timeout=30):
        result = subprocess.run([str(self.docker), *arguments], capture_output=True, timeout=timeout,
                                env={key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
        if result.returncode:
            with (self.folder / ('docker-error-' + secrets.token_hex(5) + '.log')).open('xb') as stream:
                os.chmod(stream.name, 0o600); stream.write(result.stderr[-256 * 1024:])
        require(result.returncode == 0, 'Owned tool operation failed; evidence retained on ECS')
        require(len(result.stdout) <= 32 * MIB, 'Tool metadata exceeds evidence budget')
        return result.stdout

    def image_row(self, image):
        row = json.loads(self.call('image', 'inspect', image))[0]
        require(row['Id'] == image and row['Os'] == 'linux' and not row['Config'].get('Volumes'),
                'The immutable tool image is unavailable or declares unexpected volumes')
        for entry in row['Config'].get('Env') or []:
            key, _, content = entry.partition('=')
            require(not content or not SENSITIVE.search(key), 'Tool image contains a sensitive business environment')
        return row

    def owned(self, *, size=False):
        arguments = ['inspect'] + (['--size'] if size else []) + [self.container or self.name]
        row = json.loads(self.call(*arguments))[0]
        cfg, host = row['Config'], row['HostConfig']; labels = cfg.get('Labels') or {}
        require(row['Image'] == BASE and row['Name'] == '/' + self.name and SHA.fullmatch(row['Id'])
                and (self.container is None or row['Id'] == self.container)
                and labels.get(LABEL) == self.token and labels.get('io.doorhandle.release') == self.args.tag
                and labels.get('io.doorhandle.source') == self.args.source_sha256
                and cfg.get('User') == '0:0' and cfg.get('Entrypoint') == ['/usr/local/bin/python']
                and cfg.get('Healthcheck', {}).get('Test') == ['NONE']
                and host['RestartPolicy']['Name'] == 'no' and not host.get('Privileged')
                and host.get('Memory') == 2 * GIB and host.get('MemorySwap') == 2 * GIB
                and host.get('NanoCpus') == 2 * 10 ** 9 and host.get('PidsLimit') == 256
                and host.get('NetworkMode') == 'bridge' and set(host.get('CapDrop') or []) == {'ALL'}
                and 'no-new-privileges:true' in (host.get('SecurityOpt') or []),
                'Refusing to act on a container outside this owned pip preparation')
        expected = {(str(self.folder / 'python-test-requirements.txt'), '/ci-input/requirements.txt'): False,
                    (str(self.reports), '/ci-report'): True}
        for mount in row.get('Mounts', []):
            if mount['Type'] == 'tmpfs':
                require(mount['Destination'] == '/tmp', 'Unexpected pip temporary mount')
                continue
            pair = (mount['Source'], mount['Destination'])
            require(mount['Type'] == 'bind' and pair in expected and mount['RW'] is expected.pop(pair),
                    'Pip tool mount ownership changed')
        require(not expected, 'Expected pip tool mounts are missing')
        return row

    def sample(self, *, extra=0):
        row = (self.metadata_owned(size=True) if getattr(self, 'preparation_role', 'pip') == 'metadata'
               else self.owned(size=True) if self.container else None)
        writable = int(row.get('SizeRw', 0)) if row else 0
        available = self.available()
        growth = resource_check(self.baseline, available, writable, required_growth=extra)
        memory, oom = 0, bool(row and row['State'].get('OOMKilled'))
        if row and row['State'].get('Pid'):
            try:
                relative = next((line.split(':', 2)[2] for line in Path('/proc/' + str(row['State']['Pid']) + '/cgroup').read_text().splitlines() if line.startswith('0::')), None)
                require(relative is not None and relative.startswith('/') and '..' not in Path(relative).parts,
                        'Owned pip cgroup identity is unavailable')
                cgroup = Path('/sys/fs/cgroup') / relative.lstrip('/')
                memory = int((cgroup / 'memory.peak').read_text())
                events = dict(line.split() for line in (cgroup / 'memory.events').read_text().splitlines())
                oom = oom or int(events.get('oom_kill', 0)) > 0
            except FileNotFoundError:
                # The container can exit between inspect and the cgroup read.
                require(not self.owned()['State']['Running'], 'Running pip memory monitor became unavailable')
        value = {'elapsedSeconds': round(time.monotonic() - self.started, 3), 'availableDiskBytes': available,
                 'hostDiskGrowthBytes': growth, 'ownedWritableBytes': writable, 'ownedMemoryPeakBytes': memory, 'oomKilled': oom}
        with self.lock:
            self.observed['hostDiskGrowthPeakBytes'] = max(growth, self.observed['hostDiskGrowthPeakBytes'])
            self.observed['containerWritablePeakBytes'] = max(writable, self.observed['containerWritablePeakBytes'])
            self.observed['memoryPeakBytes'] = max(memory, self.observed['memoryPeakBytes'])
            self.observed['oomKilled'] |= oom
            self.observed['samples'] += 1
            self.sample_stream.write(json.dumps(value, sort_keys=True) + '\n'); self.sample_stream.flush()
        require(not oom, 'Owned pip preparation recorded an OOM kill')
        self.check_watchdog()
        return row

    def watchdog(self):
        """statvfs stays independent of potentially slow Docker inspect/commit."""
        try:
            previous = time.monotonic()
            while not self.watch_stop.wait(INTERVAL):
                current = time.monotonic()
                require(current - previous <= 2, 'Disk monitor missed its maximum sampling interval')
                previous = current
                available = self.available()
                growth = resource_check(self.baseline, available, 0)
                with self.lock:
                    self.observed['hostDiskGrowthPeakBytes'] = max(growth, self.observed['hostDiskGrowthPeakBytes'])
                    self.observed['samples'] += 1
                    self.sample_stream.write(json.dumps({'kind': 'disk-watchdog',
                        'elapsedSeconds': round(current - self.started, 3), 'availableDiskBytes': available,
                        'hostDiskGrowthBytes': growth}, sort_keys=True) + '\n')
                    self.sample_stream.flush()
        except BaseException as error:
            self.watch_failed.set()
            try:
                write_json(self.folder / 'watchdog-failure.json', {'status': 'FAILED_OR_UNKNOWN',
                    'errorType': type(error).__name__, 'ownerToken': self.token, 'stopScope': 'OWNED_ATTEMPT_ONLY'})
            except BaseException:
                pass
            if getattr(self, 'preparation_role', 'pip') != 'metadata':
                try:
                    self.stop_owned()
                except BaseException:
                    pass

    def check_watchdog(self):
        require(not self.watch_failed.is_set(), 'Resource watchdog failed; only owned tool preparation may be stopped')

    def finish_watchdog(self):
        self.watch_stop.set()
        if self.watcher:
            self.watcher.join(timeout=35)
            require(not self.watcher.is_alive(), 'Owned tool resource monitor did not exit')
        self.check_watchdog()

    def stop_owned(self):
        row = self.owned()
        self.container = row['Id']
        if row['State'].get('Running'):
            self.call('stop', '--time', '10', self.container, timeout=20)
        final = self.owned()
        require(not final['State']['Running'] and not final['State'].get('Restarting') and final['State']['Pid'] == 0,
                'Owned pip container stop was not confirmed')
        return {'containerId': self.container, 'pid': 0, 'exitCode': final['State']['ExitCode'], 'retained': True}

    def metadata_owned(self, *, size=False):
        arguments = ['inspect'] + (['--size'] if size else []) + [self.metadata_container or self.metadata_name]
        row = json.loads(self.call(*arguments))[0]
        cfg, host, state = row['Config'], row['HostConfig'], row['State']
        labels = cfg.get('Labels') or {}
        require(row['Image'] == CACHED_PYTHON and row['Name'] == '/' + self.metadata_name
                and SHA.fullmatch(row['Id']) and (self.metadata_container is None or row['Id'] == self.metadata_container)
                and labels.get(LABEL) == self.token and labels.get('io.doorhandle.release') == self.args.tag
                and labels.get('io.doorhandle.source') == self.args.source_sha256
                and labels.get('io.doorhandle.ci-tool-preparation-role') == 'metadata-only'
                and cfg.get('User') == str(os.getuid()) + ':' + str(os.getgid())
                and cfg.get('Entrypoint') == [PYTHON] and cfg.get('Cmd') == ['--version']
                and cfg.get('Healthcheck', {}).get('Test') == ['NONE'] and cfg.get('WorkingDir') == '/'
                and host.get('ReadonlyRootfs') is True and host['RestartPolicy']['Name'] == 'no'
                and not host.get('Privileged') and not host.get('CapAdd')
                and host.get('Memory') == 512 * MIB and host.get('MemorySwap') == 512 * MIB
                and host.get('NanoCpus') == 10 ** 9 and host.get('PidsLimit') == 16
                and host.get('NetworkMode') == 'none' and set(host.get('CapDrop') or []) == {'ALL'}
                and 'no-new-privileges:true' in (host.get('SecurityOpt') or [])
                and not row.get('Mounts') and not host.get('Binds') and not host.get('Mounts')
                and not host.get('Tmpfs') and not host.get('Devices')
                and state.get('Status') == 'created' and not state.get('Running')
                and not state.get('Restarting') and not state.get('Paused') and not state.get('OOMKilled')
                and state.get('Pid') == 0 and state.get('ExitCode') == 0
                and str(state.get('StartedAt', '')).startswith('0001-'),
                'Refusing to act on a container outside this never-started metadata repair')
        return row

    def cleanup_metadata(self):
        row = self.metadata_owned()
        self.metadata_container = row['Id']
        require(not self.call('diff', self.metadata_container).strip(), 'Metadata repair unexpectedly changed filesystem content')
        self.call('rm', self.metadata_container)
        remaining = self.call('ps', '-aq', '--no-trunc', '--filter', 'id=' + self.metadata_container).decode().split()
        require(not remaining, 'The owned metadata container was not removed')
        return {'status': 'STOPPED', 'containersCreated': [self.metadata_container],
                'containers': [{'containerId': self.metadata_container, 'sourceImageId': CACHED_PYTHON,
                                'started': False, 'pid': 0, 'removed': True}], 'remaining': []}

    def commit_tool_image(self, sources, *, container, stem):
        command = [str(self.docker), 'commit', '--pause=false']
        for change in tool_changes(sources, uid=os.getuid(), gid=os.getgid(),
                                   commit=self.args.commit, source_sha=self.args.source_sha256):
            command += ['--change', change]
        command += [container, 'doorhandlecatch/ci-python:' + self.args.tag + '-' + self.token[:12]]
        with (self.folder / (stem + '.stdout')).open('xb') as stdout, (self.folder / (stem + '.stderr')).open('xb') as stderr:
            os.chmod(stdout.name, 0o600); os.chmod(stderr.name, 0o600)
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr,
                env={key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
            try:
                deadline = time.monotonic() + 120
                while process.poll() is None:
                    self.sample()
                    require(time.monotonic() < deadline, 'Tool image commit exceeded its bounded deadline')
                    time.sleep(INTERVAL)
                require(process.returncode == 0, 'Tool image commit failed')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=3)
        self.image = commit_image_id((self.folder / (stem + '.stdout')).read_text())
        row = self.image_row(self.image)
        validate_tool_config(row['Config'], sources, uid=os.getuid(), gid=os.getgid(),
                             commit=self.args.commit, source_sha=self.args.source_sha256)
        return row

    def repair_cached_image(self, sources, cached):
        """Change only Docker metadata; this container is never started."""
        self.preparation_role = 'metadata'
        resource_check(self.baseline, self.available(), 0, required_growth=CONFIG_GROWTH_BOUND)
        self.sample_stream = self.snapshot.open('x', encoding='utf8'); os.chmod(self.snapshot, 0o600)
        cleanup = None
        try:
            self.metadata_container = self.call(*metadata_arguments(self.metadata_name, self.token,
                self.args.tag, self.args.source_sha256, uid=os.getuid(), gid=os.getgid())).decode().strip()
            require(SHA.fullmatch(self.metadata_container), 'Metadata create did not return a complete owned ID')
            self.metadata_owned()
            require(not self.call('diff', self.metadata_container).strip(), 'Metadata container must have no filesystem changes')
            self.watcher = threading.Thread(target=self.watchdog, name='owned-python-tools-config-disk', daemon=True)
            self.watcher.start()
            self.sample(extra=CONFIG_GROWTH_BOUND)
            row = self.commit_tool_image(sources, container=self.metadata_container, stem='config-commit')
            validate_dependency_layers(cached, row)
            self.sample()
            self.finish_watchdog()
            cleanup = self.cleanup_metadata()
            resource_check(self.baseline, self.available(), 0)
            self.sample_stream.flush(); os.fsync(self.sample_stream.fileno())
            return cleanup
        except BaseException as error:
            if cleanup is None:
                try:
                    cleanup = self.cleanup_metadata()
                except BaseException:
                    pass
            write_json(self.folder / 'metadata-failure.json', {
                'status': 'FAILED_OR_UNKNOWN', 'errorType': type(error).__name__, 'ownerToken': self.token,
                'sourceImageId': CACHED_PYTHON, 'currentImageId': self.image, 'cleanup': cleanup,
                'oldProducerUntouched': True, 'sourceAndEvidenceRetained': True})
            raise
        finally:
            self.watch_stop.set()
            if self.watcher:
                self.watcher.join(timeout=35)
            self.sample_stream.close()

    def inspect_pinned_dependencies(self, pinned):
        """Inspect the historical immutable producer without changing it."""
        if pinned != CACHED_PINS:
            return None
        images = self.call('image', 'ls', '-q', '--no-trunc', '--filter', 'label=io.doorhandle.ci-tools=python-v1').decode().split()
        if CACHED_PYTHON not in images:
            return None
        image = self.image_row(CACHED_PYTHON); cfg = image['Config']; labels = cfg.get('Labels') or {}
        # Producer evidence keeps its original bytes and pinned provenance.
        # Original evidence still matches its exact hashes;
        # compatibility additionally requires precisely the same version pins.
        # The finished image is passive; only its original producer ran pip.
        require(labels.get('io.doorhandle.ci-tools-requirements-sha256') == CACHED_REQUIREMENTS
                and labels.get('io.doorhandle.ci-tools-recipe-sha256') == CACHED_RECIPE
                and cfg.get('User') == str(os.getuid()) + ':' + str(os.getgid())
                and cfg.get('Entrypoint') == [PYTHON] and cfg.get('Cmd') == ['--version']
                and cfg.get('WorkingDir') == '/' and cfg.get('Healthcheck', {}).get('Test') == ['NONE'],
                'Pinned dependency image configuration differs')
        base = self.image_row(BASE)['RootFS']['Layers']
        require(image['RootFS']['Layers'][:len(base)] == base, 'Pinned dependency image has another base')
        release = labels.get('io.doorhandle.release', '')
        require(release == CACHED_RELEASE and labels.get('io.doorhandle.commit') == CACHED_COMMIT
                and labels.get('io.doorhandle.source') == CACHED_SOURCE,
                'Pinned dependency producer source differs')
        origin = canonical(self.root / 'inbox' / release / 'python-tools')
        original = {}
        for name, expected_sha in CACHED_PROOFS.items():
            path = origin / name
            canonical(path); meta = path.stat()
            require(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid() and meta.st_nlink == 1
                    and stat.S_IMODE(meta.st_mode) == (0o444 if name == 'python-test-requirements.txt' else 0o600)
                    and 0 < meta.st_size <= 32 * MIB and digest(path) == expected_sha,
                    'Original private dependency evidence is unavailable')
            original[name] = path
        producer = json.loads(original['owner.json'].read_text())
        require(producer.get('identity') == self.identity
                and producer.get('sourceFiles', {}).get(RECIPE) == CACHED_RECIPE
                and producer.get('sourceFiles', {}).get(REQUIREMENTS) == CACHED_REQUIREMENTS
                and producer.get('release') == CACHED_RELEASE and producer.get('baseImageId') == BASE
                and producer.get('sourceSha256') == CACHED_SOURCE and producer.get('commit') == CACHED_COMMIT
                and producer.get('ownerToken') == labels.get(LABEL)
                and re.fullmatch(r'[a-f0-9]{24}', producer.get('ownerToken', ''))
                and producer.get('containerName') == 'doorhandle-ci-python-' + producer['ownerToken']
                and json.loads(original['reports/installed-versions.json'].read_text()) == pinned
                and b'No broken requirements found.' in original['pip.log'].read_bytes(),
                'Pinned dependency image is not bound to its successful installation evidence')
        commit_output = original['commit.stdout']
        require(commit_image_id(commit_output.read_text()) == CACHED_PYTHON,
                'Original immutable dependency image receipt differs')
        # Inspect the original producer only. Never assign its ID to this
        # attempt's container fields and never call start/stop/rm for that ID.
        old = object.__new__(Preparation)
        old.args = argparse.Namespace(tag=CACHED_RELEASE, source_sha256=CACHED_SOURCE)
        old.token = producer['ownerToken']; old.name = producer['containerName']
        old.container = None; old.folder = origin; old.reports = origin / 'reports'; old.call = self.call
        produced = old.owned()
        require(produced['Config'].get('Cmd') == installer_command(pinned)
                and produced['State'].get('Status') == 'exited' and produced['State'].get('ExitCode') == 0
                and not produced['State'].get('Running') and not produced['State'].get('Restarting')
                and not produced['State'].get('OOMKilled') and produced['State'].get('Pid') == 0
                and not str(produced['State'].get('StartedAt', '')).startswith('0001-'),
                'Original dependency producer did not finish successfully')
        return image, original, produced

    def reuse_pinned_dependencies(self, sources, pinned, owner):
        """Reuse only the reviewed immutable dependency artifact, never a tag."""
        if MEM0_REQUIREMENTS in sources:
            # This source requests the new runtime closure. The old image has
            # only its original 9-pin producer proof and cannot satisfy it.
            return None
        proof = self.inspect_pinned_dependencies(pinned)
        if proof is None:
            return None
        image, original, produced = proof
        commit_output = original['commit.stdout']
        for name in ('installed-versions.json', 'pip-install.json'):
            target = self.reports / name
            source = original['reports/' + name]
            shutil.copyfile(source, target); os.chmod(target, 0o600)
            require(digest(target) == CACHED_PROOFS['reports/' + name], 'Dependency installation evidence changed during reuse')
        cleanup = self.repair_cached_image(sources, image)
        available = self.available(); growth = resource_check(self.baseline, available, 0)
        write_json(self.folder / 'reuse.json', {'kind': 'doorhandle-pinned-dependency-reuse',
            'sourceImageId': CACHED_PYTHON, 'repairedImageId': self.image,
            'producerContainerId': produced['Id'], 'producerContainerInspectedOnly': True,
            'producerOwnerSha256': digest(original['owner.json']), 'producerProofs': CACHED_PROOFS,
            'producerCommitReceiptSha256': digest(commit_output), 'currentSourceFiles': sources,
            'diskAvailableBytes': available, 'observedGrowthBytes': growth})
        receipt = {**owner, 'status': 'PREPARED', 'kind': 'doorhandle-ecs-tool-preparation',
            'dependencyPreparation': 'REUSED_IMMUTABLE_IMAGE_CONFIG_REPAIRED', 'pythonImageId': self.image,
            'dependencyImageId': CACHED_PYTHON, 'pipExecutedThisAttempt': False, 'testsExecuted': False,
            'mavenImageId': MAVEN, 'nodeImageId': NODE,
            'reportSha': digest(self.reports / 'pip-install.json'),
            'pipReportSha256': digest(self.reports / 'pip-install.json'),
            'installedVersionsSha256': digest(self.reports / 'installed-versions.json'),
            'reuseEvidenceSha256': digest(self.folder / 'reuse.json'),
            'resourceSamplesSha256': digest(self.snapshot), 'observed': dict(self.observed), 'cleanup': cleanup}
        write_json(self.folder / 'preparation.json', receipt)
        return {**receipt, 'preparation': str(self.folder / 'preparation.json'),
                'preparationSha256': digest(self.folder / 'preparation.json')}

    def prepare(self):
        sources = archive_inputs(self.archive, self.folder, self.args.commit, self.args.source_sha256, Path(__file__).resolve(),
                                 include_builder=getattr(self.args, 'prepare_candidate_builder', False), include_mem0_runtime=True)
        os.chmod(self.folder / 'python-test-requirements.txt', 0o444)
        pinned = requirements(self.folder / 'python-test-requirements.txt')
        validate_mem0_requirements(pinned, requirements(self.folder / 'requirements.txt'))
        for image in (BASE, MAVEN, NODE):
            self.image_row(image)
        owner = {'release': self.args.tag, 'commit': self.args.commit, 'sourceSha256': self.args.source_sha256,
                 'identity': self.identity, 'ownerToken': self.token, 'containerName': self.name,
                 'baseImageId': BASE, 'diskReserveBytes': RESERVE, 'diskOvershootBytes': OVERSHOOT,
                 'maximumGrowthBytes': MAX_GROWTH, 'sourceFiles': sources,
                 'baselineAvailableBytes': self.baseline}
        write_json(self.folder / 'owner.json', owner)
        reused = self.reuse_pinned_dependencies(sources, pinned, owner)
        if reused is not None:
            return reused
        available = self.available()
        remaining = admit_fresh_install(self.baseline, available)
        write_json(self.folder / 'fresh-install-admission.json', {
            'kind': 'doorhandle-fresh-tool-admission', 'release': self.args.tag,
            'commit': self.args.commit, 'sourceSha256': self.args.source_sha256,
            'baselineAvailableBytes': self.baseline, 'availableBytes': available,
            'observedHostGrowthUpperBoundBytes': MAX_GROWTH - remaining,
            'remainingGrowthBytes': remaining, 'maximumGrowthBytes': MAX_GROWTH,
            'reserveBytes': RESERVE, 'overshootBytes': OVERSHOOT})
        self.sample_stream = self.snapshot.open('x', encoding='utf8'); os.chmod(self.snapshot, 0o600)
        try:
            self.container = self.call(*create_arguments(self.name, self.token, self.args.tag, self.args.source_sha256,
                self.folder / 'python-test-requirements.txt', self.reports, pinned)).decode().strip()
            require(SHA.fullmatch(self.container), 'Owned pip container did not return a complete ID')
            self.watcher = threading.Thread(target=self.watchdog, name='owned-python-tools-disk', daemon=True)
            self.watcher.start()
            self.owned(); self.call('start', self.container)
            while True:
                row = self.sample()
                if not row['State']['Running']:
                    break
                require(time.monotonic() - self.started <= 1800, 'Pip preparation exceeded its deadline')
                time.sleep(INTERVAL)
            with (self.folder / 'pip.log').open('xb') as stream:
                os.chmod(stream.name, 0o600)
                logs = subprocess.run([str(self.docker), 'logs', '--tail', '100000', self.container],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30,
                    env={key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
                require(logs.returncode == 0 and len(logs.stdout) <= 16 * MIB, 'Bounded raw pip log is unavailable')
                stream.write(logs.stdout)
            require(row['State']['ExitCode'] == 0 and not row['State'].get('OOMKilled'),
                    'Pinned dependency installation did not complete successfully')
            report = self.reports / 'pip-install.json'
            versions = self.reports / 'installed-versions.json'
            for path in (report, versions):
                meta = path.stat()
                require(not path.is_symlink() and stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid() and meta.st_nlink == 1
                        and 0 < meta.st_size <= 32 * MIB, 'Owned pip evidence is missing or was replaced')
                os.chmod(path, 0o600)
            require(json.loads(versions.read_text('utf8')) == pinned, 'Installed dependency versions differ')
            # A commit can temporarily retain a tar/compressed layer in addition
            # to its final unique diff. Reserve this before asking the daemon.
            commit_growth = max(OVERSHOOT, 2 * int(row.get('SizeRw', 0)) + 64 * MIB)
            self.sample(extra=commit_growth)
            self.commit_tool_image(sources, container=self.container, stem='commit')
            self.sample()
            stopped = self.stop_owned()
            self.finish_watchdog()
            self.sample_stream.flush(); os.fsync(self.sample_stream.fileno())
            receipt = {**owner, 'status': 'PREPARED', 'kind': 'doorhandle-ecs-tool-preparation',
                       'dependencyPreparation': 'INSTALLED_CURRENT_SOURCE', 'pipExecutedThisAttempt': True,
                       'testsExecuted': False,
                       'pythonImageId': self.image, 'mavenImageId': MAVEN, 'nodeImageId': NODE,
                       'pipReportSha256': digest(report), 'installedVersionsSha256': digest(versions),
                       'resourceSamplesSha256': digest(self.snapshot), 'observed': dict(self.observed),
                       'cleanup': stopped, 'reportSha': digest(report)}
            write_json(self.folder / 'preparation.json', receipt)
            return {**receipt, 'preparation': str(self.folder / 'preparation.json'),
                    'preparationSha256': digest(self.folder / 'preparation.json')}
        except BaseException as error:
            stopped = None
            # Name recovery covers a create response lost after daemon creation.
            try:
                stopped = self.stop_owned()
            except BaseException:
                pass
            failure = {**owner, 'status': 'FAILED_OR_UNKNOWN', 'errorType': type(error).__name__,
                       'observed': dict(self.observed), 'cleanup': stopped,
                       'pythonImageId': self.image, 'sourceAndEvidenceRetained': True}
            write_json(self.folder / 'failure.json', failure)
            raise
        finally:
            self.watch_stop.set()
            if self.watcher:
                self.watcher.join(timeout=35)
            if self.sample_stream:
                self.sample_stream.close()


def control_bytes(path, *, maximum=32 * MIB, empty=False):
    path = canonical(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
                and stat.S_IMODE(before.st_mode) == (0o444 if path.name == 'python-test-requirements.txt' else 0o600)
                and (0 if empty else 1) <= before.st_size <= maximum, 'Owned bounded preparation evidence required')
        raw = stream.read(maximum + 1); after = os.fstat(stream.fileno())
        require(len(raw) == before.st_size and (before.st_ino, before.st_size, before.st_mtime_ns)
                == (after.st_ino, after.st_size, after.st_mtime_ns), 'Preparation evidence changed while reading')
    return raw


def completion_files(receipt):
    names = {'owner.json', 'preparation.json', 'reports/pip-install.json', 'reports/installed-versions.json',
             'resource-samples.jsonl', *[Path(name).name for name in receipt['sourceFiles']]}
    if receipt['dependencyPreparation'] == 'INSTALLED_CURRENT_SOURCE':
        names.update(('pip.log', 'fresh-install-admission.json', 'commit.stdout', 'commit.stderr'))
    else:
        require(receipt['dependencyPreparation'] == 'REUSED_IMMUTABLE_IMAGE_CONFIG_REPAIRED',
                'Unknown completed dependency preparation')
        names.update(('reuse.json', 'config-commit.stdout', 'config-commit.stderr'))
    return sorted(names)


def complete_preparation(preparation, value):
    """Publish success only after every component requested by this invocation."""
    buildkit_archive = validate_builder_input_arguments(preparation.args)
    if buildkit_archive is not None:
        value = {**value, 'buildkitArchive': buildkit_archive}
    receipt = json.loads(control_bytes(preparation.folder / 'preparation.json'))
    proofs = {name: hashlib.sha256(control_bytes(preparation.folder / name, empty=name.endswith('.stderr'))).hexdigest()
              for name in completion_files(receipt)}
    completion = {'schema': 1, 'kind': 'doorhandle-completed-tool-preparation',
                  **{key: value[key] for key in ('release', 'commit', 'sourceSha256', 'identity', 'ownerToken')},
                  'prepareCandidateBuilder': preparation.args.prepare_candidate_builder,
                  'proofs': proofs, 'result': value}
    if buildkit_archive is not None:
        completion['buildkitArchive'] = buildkit_archive
    path = preparation.folder / 'completion.json'
    atomic_completion(path, completion)
    return {**value, 'completion': str(path), 'completionSha256': digest(path)}


def atomic_completion(path, value):
    """Linux no-replace rename publishes only a fully fsynced completion file."""
    temporary = path.with_name(path.name + '.' + secrets.token_hex(12) + '.pending')
    try:
        write_json(temporary, value)
        rename = ctypes.CDLL(None, use_errno=True).renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(temporary), -100, os.fsencode(path), 1):  # RENAME_NOREPLACE
            number = ctypes.get_errno()
            raise OSError(number, os.strerror(number))
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


class PreparedReadback(Preparation):
    """Re-admit an existing result; this path has no create, pip or cleanup API."""

    def __init__(self, args):
        validate_builder_input_arguments(args)
        self.args = args; self.identity = identity(args)
        require(TAG.fullmatch(args.tag) and re.fullmatch(r'[a-f0-9]{40}', args.commit)
                and args.tag.endswith('-' + args.commit[:12]) and SHA.fullmatch(args.source_sha256),
                'Fixed commit, source archive hash and release are required')
        self.root = canonical(args.root); self.inbox = canonical(self.root / 'inbox' / args.tag)
        require(re.fullmatch(r'/(?:home|srv|opt)/[A-Za-z0-9_./-]+', str(self.root)), 'Owned release root path required')
        for path in (self.root, self.inbox):
            info = path.stat()
            require(path.is_dir() and info.st_uid == os.getuid() and not info.st_mode & 0o022,
                    'Owned existing preparation root and inbox required')
        self.archive = canonical(self.inbox / 'source.tar.gz')
        control_bytes(self.archive, maximum=512 * MIB)
        self.found = scan_archive_inputs(self.archive, args.commit, args.source_sha256, Path(__file__).resolve(),
                                         args.prepare_candidate_builder, include_mem0_runtime=True)
        self.docker = canonical(shutil.which('docker')); self.folder = self.inbox / 'python-tools'
        require(not self.folder.is_symlink(), 'Preparation directory cannot be a link')
        if not self.folder.exists():
            raise PreparationPending('Same-request preparation has not created its evidence yet')
        canonical(self.folder); info = self.folder.stat()
        require(self.folder.is_dir() and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                'Private owned preparation directory required')
        self.reports = self.folder / 'reports'

    def call(self, *arguments, timeout=20):
        require((arguments[:2] == ('image', 'inspect') or arguments[:2] == ('image', 'ls')
                 or arguments[:1] == ('inspect',) or arguments[:1] == ('ps',)),
                'Preparation readback permits Docker inspection only')
        result = subprocess.run([str(self.docker), *arguments], capture_output=True, timeout=min(timeout, 20),
                                env={key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
        require(result.returncode == 0 and len(result.stdout) <= 32 * MIB,
                'Read-only preparation inspection failed')
        return result.stdout

    def validate_samples(self, receipt):
        rows = control_bytes(self.snapshot).splitlines()
        require(0 < len(rows) <= 10000, 'Bounded raw preparation samples required')
        peaks = {'hostDiskGrowthPeakBytes': 0, 'containerWritablePeakBytes': 0,
                 'memoryPeakBytes': 0, 'oomKilled': False, 'samples': len(rows)}
        owned_samples = 0
        for raw in rows:
            row = json.loads(raw); elapsed = row['elapsedSeconds']
            common = {'elapsedSeconds', 'availableDiskBytes', 'hostDiskGrowthBytes'}
            if row.get('kind') == 'disk-watchdog':
                require(set(row) == common | {'kind'}, 'Disk watchdog sample schema differs')
            else:
                require(set(row) == common | {'ownedWritableBytes', 'ownedMemoryPeakBytes', 'oomKilled'},
                        'Owned container sample schema differs')
                owned_samples += 1
            require(type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0,
                    'Preparation sample time is invalid')
            for key in ('availableDiskBytes', 'hostDiskGrowthBytes', 'ownedWritableBytes', 'ownedMemoryPeakBytes'):
                require(type(row.get(key, 0)) is int and row.get(key, 0) >= 0, 'Preparation resource sample is invalid')
            growth = resource_check(self.baseline, row['availableDiskBytes'], row.get('ownedWritableBytes', 0))
            require(growth == row['hostDiskGrowthBytes'] and row.get('oomKilled', False) is False
                    and row.get('ownedMemoryPeakBytes', 0) <= 2 * GIB, 'Preparation growth or OOM evidence differs')
            for key, field in (('hostDiskGrowthBytes', 'hostDiskGrowthPeakBytes'),
                               ('ownedWritableBytes', 'containerWritablePeakBytes'), ('ownedMemoryPeakBytes', 'memoryPeakBytes')):
                peaks[field] = max(peaks[field], row.get(key, 0))
        require(owned_samples > 0 and peaks == receipt['observed'], 'Preparation observed peaks differ from original samples')

    def validate_builder(self, reference):
        spec = importlib.util.spec_from_file_location('readback_fixed_builder', self.folder / 'compact-build-resources.py')
        helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
        context = {key: value for key, value in self.owner.items() if key in ('release', 'commit', 'sourceSha256', 'identity')}
        proof = helper.admit_tools(self.root, context, self.folder)
        require(reference == {**proof, 'imageId': helper.IMAGE_ID, 'status': 'PREPARED'},
                'Completed builder reference differs')
        directory = self.inbox / 'candidate-build-tools'
        value = json.loads(control_bytes(directory / 'tools.json'))
        buildkit_archive = helper.buildkit_input(self.args)
        require(buildkit_archive == validate_builder_input_arguments(self.args), 'BuildKit archive request interpretation differs')
        if buildkit_archive is None:
            require('buildkitArchive' not in value, 'Prepared builder archive binding differs from this request')
        else:
            require(value.get('buildkitArchive') == buildkit_archive
                    and type(value['buildkitArchive'].get('bytes')) is int,
                    'Prepared builder archive binding differs from this request')
            helper.validate_buildkit_archive(self.root, buildkit_archive)
        require(value['licenseFile'] == str(directory / 'LICENSE')
                and hashlib.sha256(control_bytes(directory / 'LICENSE')).hexdigest() == helper.LICENSE_SHA
                and set(value['versions']) == {'buildctl', 'buildkitd'}, 'Builder license or version evidence differs')
        for name, evidence in value['versions'].items():
            require(evidence['file'] == name + '-version.log', 'Builder version log escaped its owned path')
            raw = control_bytes(directory / evidence['file'], maximum=4096)
            require(hashlib.sha256(raw).hexdigest() == evidence['sha256'] and helper.VERSION.encode() in raw,
                    'Actual builder version evidence differs')
        require(value.get('rootlessProfile') == helper.admit_rootless_profile()
                and value['rootlessProfile'].get('localOverrideRulesAbsent') is True,
                'Completed rootless AppArmor profile differs from the current admitted profile')
        engine = helper.tool_engine_identity(self.root, context, self.folder)
        image = json.loads(self.call('image', 'inspect', engine['engineImageId']))[0]
        require(helper.validate_engine_identity(image, engine) == engine and image['Os'] == 'linux'
                and image['Config'].get('User') in ('1000', '1000:1000'), 'Prepared builder image is not rootless')
        summary = json.loads(control_bytes(directory / 'resource-summary.json'))
        cid = summary['cleanup']['builderContainerId']; require(SHA.fullmatch(cid), 'Stopped builder ID is invalid')
        row = json.loads(self.call('inspect', cid))[0]; labels = row['Config'].get('Labels') or {}; state = row['State']
        require(row['Id'] == cid and row['Image'] == engine['engineImageId']
                and labels.get(helper.LABEL) == summary['ownerToken'] and labels.get('io.doorhandle.release') == self.args.tag
                and labels.get('io.doorhandle.source') == self.args.source_sha256
                and row['Config'].get('User') in ('1000', '1000:1000') and not row['HostConfig'].get('Privileged')
                and row['HostConfig'].get('Memory') == helper.BUILDER_MEMORY
                and row['HostConfig'].get('MemorySwap') == helper.BUILDER_MEMORY
                and row['HostConfig']['RestartPolicy']['Name'] == 'no'
                and row['HostConfig'].get('NetworkMode') == 'bridge' and row['HostConfig'].get('NanoCpus') == 2 * 10 ** 9
                and row['HostConfig'].get('PidsLimit') == 1024
                and helper.rootless_security_options(row['HostConfig'])
                and row.get('AppArmorProfile') == helper.ROOTLESS_PROFILE
                and state.get('Status') == 'exited' and not state.get('Running') and not state.get('Restarting')
                and not state.get('Paused') and not state.get('OOMKilled')
                and not str(state.get('StartedAt', '')).startswith('0001-')
                and state.get('Pid') == 0 and state.get('ExitCode') == summary['cleanup']['builderExitCode'],
                'Prepared builder owner, cgroup or actual stopped state differs')

    def read_prepared(self):
        buildkit_archive = validate_builder_input_arguments(self.args)
        for name in ('failure.json', 'watchdog-failure.json', 'metadata-failure.json', 'completion-failure.json'):
            require(not (self.folder / name).exists() and not (self.folder / name).is_symlink(),
                    'This preparation has terminal failure evidence')
        builder_summary = self.inbox / 'candidate-build-tools/resource-summary.json'
        if self.args.prepare_candidate_builder and builder_summary.exists():
            require(json.loads(control_bytes(builder_summary)).get('status') == 'PASS', 'Requested builder preparation failed')
        path = self.folder / 'completion.json'
        if not path.exists():
            require(not path.is_symlink(), 'Completion evidence cannot be a link')
            raise PreparationPending('Same-request preparation has no final completion evidence yet')
        complete_raw = control_bytes(path); complete = json.loads(complete_raw)
        completion_keys = {'schema', 'kind', 'release', 'commit', 'sourceSha256', 'identity',
                           'ownerToken', 'prepareCandidateBuilder', 'proofs', 'result'}
        if buildkit_archive is not None:
            completion_keys.add('buildkitArchive')
        require(complete.get('schema') == 1 and complete.get('kind') == 'doorhandle-completed-tool-preparation'
                and complete.get('prepareCandidateBuilder') is self.args.prepare_candidate_builder
                and set(complete) == completion_keys
                and (buildkit_archive is None or (complete.get('buildkitArchive') == buildkit_archive
                    and type(complete['buildkitArchive'].get('bytes')) is int)),
                'Completed preparation request mode differs')
        if buildkit_archive is not None:
            stored = complete['result'].get('buildkitArchive') if type(complete['result']) is dict else None
            require(type(stored) is dict and stored == buildkit_archive and type(stored.get('bytes')) is int,
                    'Completed preparation result archive binding differs')
        found = self.found
        sources = {name: hashlib.sha256(raw).hexdigest() for name, raw in found.items()}
        for name, raw in found.items():
            require(control_bytes(self.folder / Path(name).name) == raw, 'Retained recipe or requirements differ from fixed source')
        self.owner = json.loads(control_bytes(self.folder / 'owner.json')); owner = self.owner
        self.token = owner['ownerToken']; self.name = owner['containerName']; self.container = None
        self.metadata_container = None; self.metadata_name = self.name + '-metadata'
        self.snapshot = self.folder / 'resource-samples.jsonl'; self.baseline = owner['baselineAvailableBytes']
        require(type(self.baseline) is int and self.baseline >= RESERVE + OVERSHOOT
                and re.fullmatch(r'[a-f0-9]{24}', self.token) and self.name == 'doorhandle-ci-python-' + self.token,
                'Preparation owner or baseline is invalid')
        expected = {'release': self.args.tag, 'commit': self.args.commit, 'sourceSha256': self.args.source_sha256,
                    'identity': self.identity, 'baseImageId': BASE, 'diskReserveBytes': RESERVE,
                    'diskOvershootBytes': OVERSHOOT, 'maximumGrowthBytes': MAX_GROWTH, 'sourceFiles': sources}
        require(set(owner) == set(expected) | {'ownerToken', 'containerName', 'baselineAvailableBytes'}
                and all(owner.get(key) == value for key, value in expected.items())
                and all(complete.get(key) == owner[key] for key in ('release', 'commit', 'sourceSha256', 'identity', 'ownerToken')),
                'Completed preparation belongs to another source, ECS or owner')
        receipt = json.loads(control_bytes(self.folder / 'preparation.json'))
        receipt_keys = set(owner) | {'status', 'kind', 'dependencyPreparation', 'pipExecutedThisAttempt', 'testsExecuted',
            'pythonImageId', 'mavenImageId', 'nodeImageId', 'pipReportSha256', 'installedVersionsSha256',
            'resourceSamplesSha256', 'observed', 'cleanup', 'reportSha'}
        if receipt.get('dependencyPreparation') == 'REUSED_IMMUTABLE_IMAGE_CONFIG_REPAIRED':
            receipt_keys |= {'dependencyImageId', 'reuseEvidenceSha256'}
        require(all(receipt.get(key) == value for key, value in owner.items())
                and set(receipt) == receipt_keys
                and receipt.get('status') == 'PREPARED' and receipt.get('kind') == 'doorhandle-ecs-tool-preparation'
                and receipt.get('testsExecuted') is False and receipt.get('mavenImageId') == MAVEN
                and receipt.get('nodeImageId') == NODE, 'Python preparation receipt is incomplete or changed')
        names = completion_files(receipt)
        proofs = {name: hashlib.sha256(control_bytes(self.folder / name, empty=name.endswith('.stderr'))).hexdigest() for name in names}
        require(complete.get('proofs') == proofs, 'Completed preparation original control bytes changed')
        pinned = requirements(self.folder / 'python-test-requirements.txt')
        if MEM0_REQUIREMENTS in found:
            validate_mem0_requirements(pinned, requirements(self.folder / 'requirements.txt'))
            require(receipt['dependencyPreparation'] == 'INSTALLED_CURRENT_SOURCE'
                    and receipt['pipExecutedThisAttempt'] is True,
                    'Current Mem0 runtime closure cannot use the historical 9-pin dependency proof')
        require(json.loads(control_bytes(self.reports / 'installed-versions.json')) == pinned
                and receipt['installedVersionsSha256'] == proofs['reports/installed-versions.json']
                and receipt['pipReportSha256'] == receipt['reportSha'] == proofs['reports/pip-install.json']
                and receipt['resourceSamplesSha256'] == proofs['resource-samples.jsonl'], 'Python reports or pinned versions differ')
        self.validate_samples(receipt)
        require(IMAGE.fullmatch(receipt['pythonImageId']), 'Prepared image is not immutable')
        image = self.image_row(receipt['pythonImageId'])
        validate_tool_config(image['Config'], sources, uid=os.getuid(), gid=os.getgid(),
                             commit=self.args.commit, source_sha=self.args.source_sha256)
        base = self.image_row(BASE)['RootFS']['Layers']
        require(image['RootFS']['Layers'][:len(base)] == base, 'Prepared dependency image has another base')
        if receipt['dependencyPreparation'] == 'INSTALLED_CURRENT_SOURCE':
            admission = json.loads(control_bytes(self.folder / 'fresh-install-admission.json'))
            require(all(admission.get(key) == expected for key, expected in {
                'kind': 'doorhandle-fresh-tool-admission', 'release': self.args.tag, 'commit': self.args.commit,
                'sourceSha256': self.args.source_sha256, 'baselineAvailableBytes': self.baseline,
                'maximumGrowthBytes': MAX_GROWTH, 'reserveBytes': RESERVE, 'overshootBytes': OVERSHOOT}.items())
                and type(admission['availableBytes']) is int
                and admission['remainingGrowthBytes'] == admit_fresh_install(self.baseline, admission['availableBytes'])
                and admission['observedHostGrowthUpperBoundBytes'] == MAX_GROWTH - admission['remainingGrowthBytes'],
                'Fresh installation admission differs from its actual bounded baseline')
            require(receipt['pipExecutedThisAttempt'] is True and b'No broken requirements found.' in control_bytes(self.folder / 'pip.log')
                    and commit_image_id(control_bytes(self.folder / 'commit.stdout').decode()) == receipt['pythonImageId'],
                    'Current dependency installation or commit evidence differs')
            self.container = receipt['cleanup']['containerId']; row = self.owned(); state = row['State']
            require(row['Config'].get('Cmd') == installer_command(pinned) and state.get('Status') == 'exited'
                    and not state.get('Running') and not state.get('Restarting') and not state.get('OOMKilled')
                    and not state.get('Paused') and not str(state.get('StartedAt', '')).startswith('0001-')
                    and state.get('Pid') == 0 and state.get('ExitCode') == 0
                    and receipt['cleanup'] == {'containerId': row['Id'], 'pid': 0, 'exitCode': 0, 'retained': True},
                    'Owned pip producer did not actually finish successfully')
        else:
            proof = self.inspect_pinned_dependencies(pinned)
            require(proof is not None and receipt['pipExecutedThisAttempt'] is False
                    and receipt['dependencyImageId'] == CACHED_PYTHON, 'Historical dependency provenance differs')
            validate_dependency_layers(proof[0], image)
            require(commit_image_id(control_bytes(self.folder / 'config-commit.stdout').decode()) == receipt['pythonImageId']
                    and digest(self.folder / 'reuse.json') == receipt['reuseEvidenceSha256'], 'Config-only commit evidence differs')
            reuse = json.loads(control_bytes(self.folder / 'reuse.json'))
            require(all(reuse.get(key) == expected for key, expected in {
                'kind': 'doorhandle-pinned-dependency-reuse', 'sourceImageId': CACHED_PYTHON,
                'repairedImageId': receipt['pythonImageId'], 'producerContainerId': proof[2]['Id'],
                'producerContainerInspectedOnly': True, 'producerOwnerSha256': CACHED_PROOFS['owner.json'],
                'producerCommitReceiptSha256': CACHED_PROOFS['commit.stdout'], 'currentSourceFiles': sources,
                'producerProofs': CACHED_PROOFS}.items()) and type(reuse['diskAvailableBytes']) is int
                and resource_check(self.baseline, reuse['diskAvailableBytes'], 0) == reuse['observedGrowthBytes']
                and all(proofs['reports/' + name] == CACHED_PROOFS['reports/' + name]
                        for name in ('pip-install.json', 'installed-versions.json')), 'Config-only producer evidence differs')
            cleanup = receipt['cleanup']
            require(cleanup['status'] == 'STOPPED' and cleanup['remaining'] == [] and len(cleanup['containers']) == 1
                    and cleanup['containersCreated'] == [cleanup['containers'][0]['containerId']]
                    and cleanup['containers'][0] == {'containerId': cleanup['containersCreated'][0], 'sourceImageId': CACHED_PYTHON,
                        'started': False, 'pid': 0, 'removed': True}, 'Config-only cleanup evidence differs')
            cid = cleanup['containersCreated'][0]; require(SHA.fullmatch(cid), 'Metadata container ID is invalid')
            require(not self.call('ps', '-aq', '--no-trunc', '--filter', 'id=' + cid).strip(), 'Metadata container still exists')
        for fixed in (MAVEN, NODE): self.image_row(fixed)
        result = {**receipt, 'preparation': str(self.folder / 'preparation.json'),
                  'preparationSha256': digest(self.folder / 'preparation.json')}
        if buildkit_archive is not None:
            result['buildkitArchive'] = buildkit_archive
        if self.args.prepare_candidate_builder:
            reference = complete['result'].get('candidateBuilderTools'); self.validate_builder(reference)
            result['candidateBuilderTools'] = reference
        require(complete['result'] == result, 'Final completion result differs from fully verified components')
        require(digest(self.archive) == self.args.source_sha256 and control_bytes(path) == complete_raw
                and all(hashlib.sha256(control_bytes(self.folder / name, empty=name.endswith('.stderr'))).hexdigest() == checksum
                        for name, checksum in proofs.items()),
                'Preparation evidence changed during final readback')
        return {**result, 'completion': str(path), 'completionSha256': hashlib.sha256(complete_raw).hexdigest(),
                'readbackValidated': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--prepare-candidate-builder', action='store_true')
    parser.add_argument('--buildkit-archive')
    parser.add_argument('--buildkit-archive-sha256')
    parser.add_argument('--buildkit-archive-bytes', type=int)
    parser.add_argument('--read-prepared', action='store_true')
    args = parser.parse_args(argv)
    for event in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(event, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    preparation = None
    try:
        validate_builder_input_arguments(args)
        if args.read_prepared:
            print(json.dumps(PreparedReadback(args).read_prepared(), ensure_ascii=True)); return 0
        preparation = Preparation(args)
        value = preparation.prepare()
        if args.prepare_candidate_builder:
            spec = importlib.util.spec_from_file_location('pinned_candidate_build_resources', preparation.folder / 'compact-build-resources.py')
            helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
            value['candidateBuilderTools'] = helper.prepare_tools(args, preparation.identity, preparation.folder)
        value = complete_preparation(preparation, value)
        print(json.dumps(value, ensure_ascii=True)); return 0
    except BaseException as error:
        failed = {'status': 'PENDING' if isinstance(error, PreparationPending) else 'FAILED_OR_UNKNOWN', 'errorType': type(error).__name__,
                  'sourceAndEvidenceRetained': True}
        if isinstance(error, PreparationError) or getattr(error, 'doorhandle_public_resource_error', False):
            failed['error'] = str(error)
        if preparation is not None and not args.read_prepared:
            marker = preparation.folder / 'completion-failure.json'
            try:
                if not marker.exists():
                    write_json(marker, {**failed, 'release': args.tag, 'commit': args.commit,
                                        'sourceSha256': args.source_sha256, 'prepareCandidateBuilder': args.prepare_candidate_builder})
            except (OSError, PreparationError):
                pass  # Keep the original failure when its evidence filesystem is unavailable.
        print(json.dumps(failed), file=sys.stderr)
        return 75 if isinstance(error, PreparationPending) else 2


if __name__ == '__main__':
    raise SystemExit(main())
