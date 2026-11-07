"""Prepare this fixed Jenkins source's Python dependency image on the admitted ECS.

Only the source-controlled recipe and pinned requirements are extracted. A
bounded, owned pip container installs dependencies; no project test or business
process is started. Source, reports, stopped containers and images are retained.
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
RECIPE = 'script/jenkins/prepare-ecs-tools.py'
REQUIREMENTS = 'script/jenkins/python-test-requirements.txt'
SHA = re.compile(r'[a-f0-9]{64}')
IMAGE = re.compile(r'sha256:[a-f0-9]{64}')
TAG = re.compile(r'ci-[1-9][0-9]*-[a-f0-9]{12}')
SENSITIVE = re.compile(r'PASSWORD|PASSWD|SECRET|API_KEY|ACCESS_KEY|TOKEN|DATABASE_URL|DB_URL', re.I)


def require(condition, message):
    if not condition:
        raise ValueError(message)


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


def archive_inputs(archive, destination, commit, expected_sha, own_recipe):
    require(digest(archive) == expected_sha, 'Fixed source archive digest differs')
    found, seen, total = {}, set(), 0
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
            if name in (RECIPE, REQUIREMENTS):
                require(member.isfile() and 0 < member.size <= MIB, 'Bounded regular tool source required')
                with package.extractfile(member) as stream:
                    content = stream.read(MIB + 1)
                require(len(content) == member.size, 'Tool source member size differs')
                found[name] = content
        require(package.pax_headers.get('comment') == commit, 'Git archive PAX commit differs')
    require(set(found) == {RECIPE, REQUIREMENTS}, 'Fixed source recipe or requirements is missing')
    require(hashlib.sha256(found[RECIPE]).hexdigest() == digest(own_recipe),
            'Uploaded tool provisioner is not this fixed source recipe')
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


INSTALL = r'''
import importlib.metadata,json,pathlib,subprocess,sys
report=pathlib.Path('/ci-report')
args=[sys.executable,'-I','-m','pip','--isolated','--disable-pip-version-check','--no-input']
code=subprocess.call(args+['install','--index-url','https://pypi.org/simple','--no-cache-dir','--no-compile','--report',str(report/'pip-install.json'),'-r','/ci-input/requirements.txt'])
if code: raise SystemExit(code)
code=subprocess.call(args+['check'])
if code: raise SystemExit(code)
expected=json.loads(sys.argv[1])
versions={name:importlib.metadata.version(name) for name in expected}
if versions != expected: raise SystemExit('Pinned installed versions differ')
(report/'installed-versions.json').write_text(json.dumps(versions,sort_keys=True),encoding='utf8')
'''


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
            BASE, '-I', '-B', '-c', INSTALL, json.dumps(expected, sort_keys=True)]


def resource_check(baseline, available, owned_writable, *, required_growth=0):
    host_growth = max(0, baseline - available)
    require(available >= RESERVE + OVERSHOOT + required_growth,
            'Tool preparation would consume the real disk reserve')
    require(max(host_growth, owned_writable) + required_growth <= MAX_GROWTH,
            'Tool preparation exceeded its bounded disk growth')
    return host_growth


class Preparation:
    def __init__(self, args):
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
        self.baseline = self.available()
        resource_check(self.baseline, self.baseline, 0, required_growth=MAX_GROWTH)
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
        row = self.owned(size=True) if self.container else None
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

    def prepare(self):
        sources = archive_inputs(self.archive, self.folder, self.args.commit, self.args.source_sha256, Path(__file__).resolve())
        os.chmod(self.folder / 'python-test-requirements.txt', 0o444)
        pinned = requirements(self.folder / 'python-test-requirements.txt')
        for image in (BASE, MAVEN, NODE):
            self.image_row(image)
        owner = {'release': self.args.tag, 'commit': self.args.commit, 'sourceSha256': self.args.source_sha256,
                 'identity': self.identity, 'ownerToken': self.token, 'containerName': self.name,
                 'baseImageId': BASE, 'diskReserveBytes': RESERVE, 'diskOvershootBytes': OVERSHOOT,
                 'maximumGrowthBytes': MAX_GROWTH, 'sourceFiles': sources}
        write_json(self.folder / 'owner.json', owner)
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
            changes = ['USER ' + str(os.getuid()) + ':' + str(os.getgid()), 'ENTRYPOINT []', 'CMD []', 'WORKDIR /',
                       'LABEL io.doorhandle.ci-tools=python-v1',
                       'LABEL io.doorhandle.source=' + self.args.source_sha256,
                       'LABEL io.doorhandle.commit=' + self.args.commit,
                       'LABEL io.doorhandle.ci-tools-requirements-sha256=' + sources[REQUIREMENTS],
                       'LABEL io.doorhandle.ci-tools-recipe-sha256=' + sources[RECIPE]]
            command = [str(self.docker), 'commit', '--pause=false']
            for change in changes:
                command += ['--change', change]
            command += [self.container, 'doorhandlecatch/ci-python:' + self.args.tag + '-' + self.token[:12]]
            with (self.folder / 'commit.stdout').open('xb') as stdout, (self.folder / 'commit.stderr').open('xb') as stderr:
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
            self.image = (self.folder / 'commit.stdout').read_text().strip()
            require(IMAGE.fullmatch(self.image), 'Tool image commit did not return an immutable image ID')
            cfg = self.image_row(self.image)['Config']; labels = cfg.get('Labels') or {}
            require(cfg.get('User') == str(os.getuid()) + ':' + str(os.getgid())
                    and cfg.get('Entrypoint') in (None, []) and cfg.get('Cmd') in (None, [])
                    and cfg.get('Healthcheck', {}).get('Test') == ['NONE'] and cfg.get('WorkingDir') == '/'
                    and labels.get('io.doorhandle.ci-tools') == 'python-v1'
                    and labels.get('io.doorhandle.source') == self.args.source_sha256
                    and labels.get('io.doorhandle.commit') == self.args.commit
                    and labels.get('io.doorhandle.ci-tools-requirements-sha256') == sources[REQUIREMENTS]
                    and labels.get('io.doorhandle.ci-tools-recipe-sha256') == sources[RECIPE],
                    'Committed tool configuration or source labels differ')
            self.sample()
            stopped = self.stop_owned()
            self.finish_watchdog()
            self.sample_stream.flush(); os.fsync(self.sample_stream.fileno())
            receipt = {**owner, 'status': 'PREPARED', 'kind': 'doorhandle-ecs-tool-preparation',
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    for event in (signal.SIGTERM, signal.SIGINT):
        signal.signal(event, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        print(json.dumps(Preparation(args).prepare(), ensure_ascii=True)); return 0
    except BaseException as error:
        print(json.dumps({'status': 'FAILED_OR_UNKNOWN', 'errorType': type(error).__name__,
                          'sourceAndEvidenceRetained': True}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
