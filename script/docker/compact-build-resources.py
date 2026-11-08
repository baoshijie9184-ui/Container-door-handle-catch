"""ECS-only owned BuildKit preparation and candidate image measurement.

The standard runtime's three phases remain separate. These receipts cover the
earlier context/export/build/load phases; no shared-daemon build solve is used.
Upstream: https://github.com/moby/buildkit (Apache-2.0), pinned release v0.34.2.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
try:
    import resource
except ImportError:  # Windows CI uses only the pure byte-evidence validator.
    resource = None
import secrets
import signal
import stat
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request


MIB = 1024 ** 2
GIB = 1024 ** 3
DISK_FLOOR = 2 * GIB + 256 * MIB
MEMORY_FLOOR = GIB
BUILDER_MEMORY = 3 * GIB
LABEL = 'io.doorhandle.candidate-builder'
VERSION = 'v0.34.2'
REFERENCE = 'docker.io/moby/buildkit@sha256:b2eef63fa76615a59fdab47309743d3018219574b8fcece77d38296704154f44'
IMAGE_ID = 'sha256:e164dcf5aa147a29659dea4e2e6b909db541c2dfe0b512dac38a2ffaf063fc18'
BUILDKIT_ARCHIVE_MAX = 128 * MIB
BUILDKIT_LAYER_BYTES = 119868658
LICENSE_URL = 'https://raw.githubusercontent.com/moby/buildkit/v0.34.2/LICENSE'
LICENSE_SHA = 'c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4'
RECIPES = ('script/docker/compact-build-resources.py', 'script/docker/compact-image-inputs.py')
SERVICES = ('backend', 'nginx', 'mem0', 'detection-worker')
SENSITIVE = re.compile(r'PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|ACCESS_KEY|PRIVATE_KEY', re.I)
SHA = re.compile(r'[a-f0-9]{64}')
IMAGE = re.compile(r'sha256:[a-f0-9]{64}')


class BuildResourceError(ValueError):
    doorhandle_public_resource_error = True


def require(condition, message):
    if not condition:
        raise BuildResourceError(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(MIB), b''): h.update(block)
    return h.hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def safe(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path
            and all(not part.is_symlink() for part in (path, *path.parents)), 'Canonical unlinked build path required')
    return path


def write(path, value):
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
        stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())


def monitored_tar_file(package, path, name, check):
    with path.open('rb') as source:
        class Reader:
            def read(self, size):
                require(0 <= size <= MIB, 'Unbounded archive copy request')
                check(); return source.read(size)
        package.addfile(package.gettarinfo(str(path), arcname=name), Reader())


def read(path):
    path = safe(path); info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
            and not info.st_mode & 0o077 and 0 < info.st_size <= 16 * MIB, 'Owned private build receipt required')
    return json.loads(path.read_bytes())


def probe(path):
    fs = os.statvfs(path)
    require(max(fs.f_bsize, fs.f_frsize) <= 4096, 'Image allocation accounting requires filesystem blocks no larger than 4096 bytes')
    memory = next(int(row.split()[1]) * 1024 for row in Path('/proc/meminfo').read_text().splitlines()
                  if row.startswith('MemAvailable:'))
    return {'monotonic': time.monotonic(), 'diskAvailableBytes': fs.f_bavail * fs.f_frsize,
            'memoryAvailableBytes': memory, 'filesystemBlockBytes': max(fs.f_bsize, fs.f_frsize)}


def phase_plan(context, phase, baseline, growth, memory, measured):
    require(type(growth) is int and growth > 0 and type(memory) is int and memory >= 0 and measured,
            'Measured inputs and explicit enforced candidate bounds required')
    required = growth + DISK_FLOOR
    return {'version': 1, 'kind': 'doorhandle-candidate-build-phase', **context, 'phase': phase,
            'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'productionCapacityVerified': False,
            'baselineProbe': baseline, 'measuredInputs': measured, 'growthEnvelopeBytes': growth,
            'memoryAdmissionBytes': memory, 'diskFloorBytes': DISK_FLOOR, 'memoryFloorBytes': MEMORY_FLOOR,
            'requiredAvailableBytes': required, 'status': 'MEASUREMENT_ADMITTED'
            if baseline['diskAvailableBytes'] >= required and baseline['memoryAvailableBytes'] >= memory + MEMORY_FLOOR
            else 'FAIL_CLOSED'}


def unique_image_inputs(rows):
    """Image IDs deduplicate tags; layer identities do not invent layer sizes."""
    images = {}
    for row in rows:
        require(IMAGE.fullmatch(row['Id']) and row['Os'] == 'linux' and row['Architecture'] == 'amd64',
                'An existing immutable linux/amd64 dependency image is required')
        for entry in row.get('Config', {}).get('Env') or []:
            key, _, value = entry.partition('=')
            require(not value or not SENSITIVE.search(key), 'Dependency image contains a sensitive environment')
        images[row['Id']] = {'imageId': row['Id'], 'reportedImageBytes': row['Size'],
                             'diffIds': row['RootFS']['Layers']}
    return images


def engine_descriptor(value, *, metadata=False):
    """Identity is three typed fields; optional OCI metadata cannot change it."""
    keys = {'mediaType', 'digest', 'size'}
    require(type(value) is dict and keys <= set(value)
            and set(value) <= keys | ({'annotations', 'platform'} if metadata else set())
            and value['mediaType'] in ('application/vnd.oci.image.manifest.v1+json',
                'application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.v2+json',
                'application/vnd.docker.distribution.manifest.list.v2+json')
            and type(value['digest']) is str and IMAGE.fullmatch(value['digest'])
            and type(value['size']) is int and 0 < value['size'] <= 4 * MIB,
            'Loaded image descriptor identity differs')
    if 'annotations' in value:
        require(type(value['annotations']) is dict and all(type(k) is str and type(v) is str
                for k, v in value['annotations'].items()), 'Loaded image annotations differ')
    if 'platform' in value:
        platform = value['platform']
        require(type(platform) is dict and {'os', 'architecture'} <= set(platform)
                and set(platform) <= {'os', 'architecture', 'variant', 'os.version', 'os.features'}
                and platform['os'] == 'linux' and platform['architecture'] == 'amd64'
                and all(type(platform[key]) is str for key in ('os', 'architecture', 'variant', 'os.version') if key in platform)
                and ('os.features' not in platform or (type(platform['os.features']) is list
                    and all(type(item) is str for item in platform['os.features']))), 'Loaded image platform metadata differs')
    return {key: value[key] for key in ('mediaType', 'digest', 'size')}


def engine_identity(row, measurement, load_descriptor):
    """Bind an engine handle to verified OCI content without changing config pins."""
    config = measurement.get('configDigest')
    require(type(config) is str and IMAGE.fullmatch(config) and measurement.get('imageId', config) == config,
            'Measured image config identity differs')
    layers = measurement.get('layers')
    require(type(layers) is list and 0 < len(layers) <= 256
            and all(type(item) is dict and type(item.get('diffId')) is str and IMAGE.fullmatch(item['diffId']) for item in layers),
            'Measured ordered image DiffIDs differ')
    diff_ids = [item['diffId'] for item in layers]
    descriptor = None if load_descriptor is None else engine_descriptor(load_descriptor)
    require(type(row) is dict and type(row.get('Id')) is str and IMAGE.fullmatch(row['Id'])
            and row['Id'] in ({config} if descriptor is None else {config, descriptor['digest']})
            and row.get('Os') == 'linux' and row.get('Architecture') == 'amd64'
            and type(row.get('RootFS')) is dict and row['RootFS'].get('Type', 'layers') == 'layers'
            and row['RootFS'].get('Layers') == diff_ids, 'Loaded engine image is not the verified config/manifest/platform')
    if row['Id'] != config or row.get('Descriptor') is not None:
        require(descriptor is not None and engine_descriptor(row.get('Descriptor'), metadata=True) == descriptor,
                'Loaded engine target descriptor differs')
    return {'engineImageId': row['Id'], 'configDigest': config, 'loadDescriptor': descriptor,
            'diffIds': diff_ids, 'os': 'linux', 'architecture': 'amd64'}


def validate_engine_identity(row, binding):
    require(type(binding) is dict and set(binding) == {'engineImageId', 'configDigest', 'loadDescriptor', 'diffIds', 'os', 'architecture'}
            and type(binding['diffIds']) is list, 'Closed engine identity binding required')
    measured = {'configDigest': binding['configDigest'], 'layers': [{'diffId': value} for value in binding['diffIds']]}
    actual = engine_identity(row, measured, binding['loadDescriptor'])
    require(actual == binding, 'Loaded engine identity binding changed')
    return actual


def stored_builder_identity(binding):
    require(type(binding) is dict and set(binding) == {'engineImageId', 'configDigest', 'loadDescriptor', 'diffIds', 'os', 'architecture'},
            'Stored builder engine identity is missing')
    row = {'Id': binding['engineImageId'], 'Descriptor': binding['loadDescriptor'], 'Os': binding['os'],
           'Architecture': binding['architecture'], 'RootFS': {'Layers': binding['diffIds']}}
    require(binding['configDigest'] == IMAGE_ID, 'Stored builder config pin differs')
    return validate_engine_identity(row, binding)


def engine_lookup_id(actor, measurement, load_descriptor):
    rows = json.loads(actor.docker('info', '--format', '{{json .DriverStatus}}'))
    require(type(rows) is list and all(type(item) is list and len(item) == 2
            and all(type(value) is str for value in item) for item in rows), 'Docker image-store evidence differs')
    stores = [value for key, value in rows if key == 'driver-type']
    require(not stores or stores == ['io.containerd.snapshotter.v1'], 'Unsupported Docker image-store identity')
    if stores:
        require(load_descriptor is not None, 'Containerd load requires its verified source descriptor')
        return engine_descriptor(load_descriptor)['digest']
    return measurement['configDigest']


def effective_dockerfile(body, original_from, alias):
    lines = body.splitlines(); count = 0; output = []
    for line in lines:
        if line.strip().startswith('# syntax='): continue  # pinned built-in dockerfile.v0, no mutable frontend pull
        if re.match(r'(?i)^FROM\s+', line):
            require(line.split()[1] == original_from, 'Unexpected candidate dependency stage')
            count += 1; parts = line.split(); parts[1] = alias; line = ' '.join(parts)
        output.append(line)
    require(count == 1 and re.fullmatch(r'dh_base_[a-z_]+', alias), 'Only one fixed runtime stage is supported')
    return '\n'.join(output) + '\n'


class Supervisor:
    """One independent pressure watcher; creator groups and builder CID only."""
    def __init__(self, directory, context):
        self.directory = Path(directory); require(not self.directory.exists(), 'Fresh candidate resource attempt required')
        self.directory.mkdir(mode=0o700); self.context = dict(context); self.token = secrets.token_hex(12)
        self.context['ownerToken'] = self.token; self.phases = []; self.current = None; self.builder = None
        self.initial = probe(self.directory); self.last = self.initial; self.process = None; self.failed = None
        self.process_deadline = None
        self.builder_stopping = False
        self.engine_identity = None
        self.daemon_import_unknown = False
        self.builder_last = None
        self.lock = threading.RLock(); self.stop = threading.Event(); self.started = time.monotonic()
        self.stop_lock = threading.RLock()
        self.stream = (self.directory / 'resource-probes.jsonl').open('x', encoding='utf8'); os.chmod(self.stream.name, 0o600)
        self.thread = threading.Thread(target=self.watch, daemon=True); self.thread.start()

    def docker(self, *args, timeout=30):
        result = subprocess.run(['docker', *args], capture_output=True, timeout=timeout,
                                env={k: v for k, v in os.environ.items() if k in ('PATH', 'LANG', 'LC_ALL')})
        require(result.returncode == 0 and len(result.stdout) <= 16 * MIB, 'Owned candidate Docker operation failed')
        return result.stdout

    def begin(self, name, growth, measured, memory=0):
        name += '-%03d' % (len(self.phases) + 1)
        self.check(); baseline = probe(self.directory)
        value = phase_plan(self.context, name, baseline, growth, memory, measured)
        path = self.directory / ('phase-%02d.json' % (len(self.phases) + 1)); write(path, value)
        self.phases.append({'file': path.name, 'sha256': digest(path)})
        require(value['status'] == 'MEASUREMENT_ADMITTED', 'Candidate phase lacks free/reserve: requiredBytes=%d freeBytes=%d requiredMemoryBytes=%d availableMemoryBytes=%d'
                % (value['requiredAvailableBytes'], baseline['diskAvailableBytes'], memory + MEMORY_FLOOR, baseline['memoryAvailableBytes']))
        with self.lock: self.current = value
        self.record_probe()

    def check(self):
        require(self.failed is None, 'Candidate resource monitor failed; retained evidence requires review')
        require(self.process is None or self.process.poll() is not None or self.process_deadline is None
                or time.monotonic() <= self.process_deadline, 'Owned candidate creator exceeded its deadline')
        item = probe(self.directory)
        require(item['diskAvailableBytes'] >= DISK_FLOOR and item['memoryAvailableBytes'] >= MEMORY_FLOOR,
                'Candidate reached the real disk or memory reserve')
        if self.current:
            require(max(0, self.current['baselineProbe']['diskAvailableBytes'] - item['diskAvailableBytes'])
                    <= self.current['growthEnvelopeBytes'], 'Candidate exceeded its enforced phase growth')
        return item

    def owned_builder(self):
        row = json.loads(self.docker('inspect', self.builder['id']))[0]
        require(row['Id'] == self.builder['id'] and row['Image'] == self.builder['engineIdentity']['engineImageId']
                and row['Config']['Labels'].get(LABEL) == self.token
                and row['Config']['Labels'].get('io.doorhandle.release') == self.context['release']
                and not row['HostConfig']['Privileged'] and row['HostConfig']['Memory'] == BUILDER_MEMORY
                and row['HostConfig']['MemorySwap'] == BUILDER_MEMORY and row['Config']['User'] in ('1000', '1000:1000'),
                'Owned rootless builder identity/cgroup changed')
        require(row['Config']['Labels'].get('io.doorhandle.source') == self.context['sourceSha256']
                and row['HostConfig'].get('BlkioDeviceWriteBps') == [{'Path': self.builder['ioDevice'], 'Rate': 64 * MIB}]
                and set(row['HostConfig'].get('SecurityOpt') or []) == {'seccomp=unconfined', 'apparmor=unconfined', 'systempaths=unconfined'},
                'Builder source, I/O ceiling or rootless sandbox configuration changed')
        expected = self.builder['mounts']
        actual = sorted((m['Type'], m.get('Name') if m['Type'] == 'volume' else m.get('Source', ''), m['Destination'], m['RW'])
                        for m in row['Mounts'] if m['Type'] != 'tmpfs')
        require(actual == [m for m in expected if m[0] != 'tmpfs']
                and set(row['HostConfig'].get('Tmpfs') or {}) == {'/run/user/1000', '/tmp'}
                and all(m['Destination'] in ('/tmp', '/run/user/1000') for m in row['Mounts'] if m['Type'] == 'tmpfs'),
                'Builder acquired an unadmitted host or data mount')
        return row

    def sample_builder(self):
        # The pressure watcher never waits for a Docker RPC. The PID/start-tick
        # and cgroup claim was independently inspected after this no-restart
        # container started; final stopping still re-inspects Docker ownership.
        if self.builder is None or not self.builder.get('claim'): return None
        if self.builder_stopping: return self.builder_last
        claim = self.builder['claim']; pid = claim['pid']
        info = Path('/proc/' + str(pid) + '/stat')
        if not info.exists() and self.builder_stopping:
            return {'id': self.builder['id'], 'image': self.builder['engineIdentity']['engineImageId'], 'running': False, 'pid': 0}
        require(info.exists() and info.read_text().rsplit(')', 1)[1].split()[19] == claim['startTicks'],
                'Owned builder PID identity changed')
        result = {'id': self.builder['id'], 'image': self.builder['engineIdentity']['engineImageId'], 'running': True, 'pid': pid,
                  'memoryLimitBytes': BUILDER_MEMORY}
        if pid:
            relative = next(x.split(':', 2)[2] for x in Path('/proc/' + str(pid) + '/cgroup').read_text().splitlines() if x.startswith('0::'))
            require(relative == claim['cgroup'] and relative.startswith('/') and '..' not in Path(relative).parts,
                    'Builder cgroup escaped its namespace')
            group = Path('/sys/fs/cgroup') / relative.lstrip('/')
            events = dict(x.split() for x in (group / 'memory.events').read_text().splitlines())
            result.update(currentBytes=int((group / 'memory.current').read_text()), peakBytes=int((group / 'memory.peak').read_text()),
                          oomKills=int(events.get('oom_kill', 0)))
            require((group / 'memory.max').read_text().strip() == str(BUILDER_MEMORY)
                    and (group / 'memory.swap.max').read_text().strip() == '0', 'Builder hard memory/swap cgroup differs')
            require(result['oomKills'] == 0, 'Owned builder recorded an OOM')
            limits = dict(line.split(' ', 1) for line in (group / 'io.max').read_text().splitlines())
            require('wbps=' + str(64 * MIB) in limits.get(self.builder['ioMajorMinor'], '').split(), 'Builder write-rate cgroup is absent')
            result['writeRateLimitBytesPerSecond'] = 64 * MIB
        self.builder_last = result
        return result

    def watch(self):
        try:
            while not self.stop.wait(0.5):
                self.record_probe()
        except BaseException as error:
            self.failed = type(error).__name__
            if self.builder and self.builder.get('pidfd') is not None:
                with contextlib.suppress(BaseException): signal.pidfd_send_signal(self.builder['pidfd'], signal.SIGKILL)
            with contextlib.suppress(BaseException):
                with self.lock:
                    self.stream.write(json.dumps({**probe(self.directory), 'phase': self.current['phase'] if self.current else 'admission',
                        'monitorError': self.failed, 'builder': self.builder_last}, sort_keys=True) + '\n'); self.stream.flush()
            with contextlib.suppress(BaseException): self.stop_owned(emergency=True)

    def record_probe(self):
        with self.lock:
            current = self.check()
            require(current['monotonic'] - self.last['monotonic'] <= 2, 'Candidate pressure sampling became late')
            self.stream.write(json.dumps({**current, 'phase': self.current['phase'] if self.current else 'admission',
                'hostDiskLossUpperBoundBytes': max(0, self.initial['diskAvailableBytes'] - current['diskAvailableBytes']),
                'builder': self.sample_builder()}, sort_keys=True) + '\n'); self.stream.flush(); self.last = current
            require(self.stream.tell() <= 64 * MIB, 'Candidate resource observation byte bound exceeded')
        return current

    def run(self, args, name, *, output=None, maximum=32 * MIB, timeout=900):
        self.check(); path = output or self.directory / (name + '.log')
        with path.open('xb') as stream:
            os.chmod(path, 0o600)
            def limit(): resource.setrlimit(resource.RLIMIT_FSIZE, (maximum, maximum))
            process = subprocess.Popen(args, stdout=stream, stderr=subprocess.STDOUT if output is None else subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, start_new_session=True, preexec_fn=limit,
                env={k: v for k, v in os.environ.items() if k in ('PATH', 'LANG', 'LC_ALL')})
            self.process = process; deadline = time.monotonic() + timeout
            self.process_deadline = deadline
            try:
                while process.poll() is None:
                    self.check(); require(time.monotonic() <= deadline, 'Owned candidate creator timed out'); time.sleep(0.25)
                require(process.returncode == 0, 'Owned candidate creator failed; private raw log retained')
            finally:
                if process.poll() is None:
                    require(os.getpgid(process.pid) == process.pid, 'Owned creator process group changed')
                    os.killpg(process.pid, signal.SIGTERM)
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=5)
                self.process = None
                self.process_deadline = None
        self.check(); return path

    def stop_owned(self, emergency=False):
        with self.stop_lock: return self._stop_owned(emergency)

    def _stop_owned(self, emergency=False):
        stopped = {'creatorStopped': self.process is None or self.process.poll() is not None, 'builderStopped': self.builder is None,
                   'daemonImportTerminated': not self.daemon_import_unknown}
        if self.builder:
            direct = False
            if emergency and self.builder.get('pidfd') is not None and not self.builder_stopping:
                # Kernel handle is bound while the inspected immutable/no-restart
                # container is alive. No daemon RPC or reusable numeric PID is
                # needed to stop writes at the pressure boundary.
                self.builder_stopping = True
                try: signal.pidfd_send_signal(self.builder['pidfd'], signal.SIGKILL)
                except ProcessLookupError: pass
                direct = True
            row = self.owned_builder()
            if direct:
                deadline = time.monotonic() + 5
                while row['State']['Running'] and time.monotonic() < deadline:
                    time.sleep(.1); row = self.owned_builder()
            if row['State']['Running'] and self.builder.get('claim') and not emergency:
                claim = self.builder['claim']
                require(row['State']['Pid'] == claim['pid'] and Path('/proc/' + str(claim['pid']) + '/stat').read_text().rsplit(')', 1)[1].split()[19] == claim['startTicks'],
                        'Owned builder process identity changed')
            self.builder_stopping = True
            if row['State']['Running']:
                self.docker(*(['kill', '--signal', 'KILL', row['Id']] if emergency else ['stop', '--time', '5', row['Id']]), timeout=15)
            row = self.owned_builder()
            require(not row['State']['Running'] and row['State']['Pid'] == 0 and not row['State'].get('Restarting'),
                    'Owned BuildKit daemon still has a creator')
            if self.builder.get('claim'):
                group = Path('/sys/fs/cgroup') / self.builder['claim']['cgroup'].lstrip('/')
                require(not group.exists() or dict(line.split() for line in (group / 'cgroup.events').read_text().splitlines()).get('populated') == '0',
                        'Owned builder cgroup still contains descendants')
            stopped.update(builderStopped=True, builderContainerId=row['Id'], builderExitCode=row['State']['ExitCode'])
        if self.process is not None and self.process.poll() is None:
            require(os.getpgid(self.process.pid) == self.process.pid, 'Owned creator group changed')
            os.killpg(self.process.pid, signal.SIGKILL if emergency else signal.SIGTERM)
            self.process.wait(timeout=10); stopped['creatorStopped'] = True
        return stopped

    def finish(self, status, **extra):
        requested = status
        try:
            if self.failed is None: self.record_probe()
        except BaseException as error:
            self.failed = type(error).__name__; status = 'FAILED'
        try: cleanup = self.stop_owned(emergency=status != 'PASS')
        except BaseException as error:
            cleanup = {'creatorStopped': False, 'builderStopped': False, 'errorType': type(error).__name__}; status = 'FAILED'
        self.stop.set(); self.thread.join(timeout=35)
        require(not self.thread.is_alive(), 'Candidate watcher did not stop')
        self.stream.flush(); os.fsync(self.stream.fileno()); self.stream.close()
        if self.builder and self.builder.get('pidfd') is not None:
            os.close(self.builder['pidfd']); self.builder['pidfd'] = None
        if self.failed is not None or not all(cleanup.get(key) is True for key in ('creatorStopped', 'builderStopped', 'daemonImportTerminated')):
            status = 'FAILED'
        result = {'version': 1, 'kind': 'doorhandle-candidate-build-resources', **self.context,
                  'status': status, 'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'productionCapacityVerified': False,
                  'baselineProbe': self.initial, 'finalProbe': probe(self.directory), 'phases': self.phases,
                  'probeFile': 'resource-probes.jsonl', 'probeSha256': digest(self.directory / 'resource-probes.jsonl'),
                  'monitorFailure': self.failed, 'cleanup': cleanup, 'originalDataChanged': False, **extra}
        if self.engine_identity is not None: result['engineIdentity'] = self.engine_identity
        write(self.directory / 'resource-summary.json', result)
        require(requested != 'PASS' or status == 'PASS', 'Candidate resource finalization failed; raw evidence retained')
        return {'file': str(self.directory / 'resource-summary.json'), 'sha256': digest(self.directory / 'resource-summary.json')}


def bootstrap_builder(actor, mounts=(), *, image_identity):
    """Official rootless daemon, no host socket, no privilege/host setting change."""
    image_identity = stored_builder_identity(image_identity)
    actor.engine_identity = image_identity
    actor.begin('builder-bootstrap', 64 * MIB, {'imageId': IMAGE_ID, 'engineIdentity': image_identity, 'version': VERSION}, BUILDER_MEMORY)
    name = 'doorhandle-builder-' + actor.token; volume = name + '-state'
    labels = {LABEL: actor.token, 'io.doorhandle.release': actor.context['release'],
              'io.doorhandle.source': actor.context['sourceSha256']}
    command = ['volume', 'create']
    for key, value in labels.items(): command += ['--label', key + '=' + value]
    actor.docker(*command, volume)
    row = json.loads(actor.docker('volume', 'inspect', volume))[0]
    require(row['Name'] == volume and row['Driver'] == 'local' and not row.get('Options') and row.get('Labels') == labels,
            'Owned builder state volume differs')
    fuse = Path('/dev/fuse')
    has_fuse = fuse.exists() and stat.S_ISCHR(fuse.stat().st_mode) and os.major(fuse.stat().st_rdev) == 10 and os.minor(fuse.stat().st_rdev) == 229
    kernel = tuple(int(x) for x in re.match(r'([0-9]+)\.([0-9]+)', os.uname().release).groups())
    snapshotter = 'fuse-overlayfs' if has_fuse else 'overlayfs' if kernel >= (5, 11) else 'native'
    docker_root = Path(actor.docker('info', '--format', '{{.DockerRootDir}}').decode().strip())
    require(docker_root.is_absolute() and docker_root.stat().st_dev == actor.directory.stat().st_dev, 'Builder cache and probes must share the admitted filesystem')
    dev = actor.directory.stat().st_dev
    device_sys = (Path('/sys/dev/block') / (str(os.major(dev)) + ':' + str(os.minor(dev)))).resolve(strict=True)
    if (device_sys / 'partition').exists(): device_sys = device_sys.parent
    device_meta = dict(line.split('=', 1) for line in (device_sys / 'uevent').read_text().splitlines() if '=' in line)
    require(re.fullmatch(r'[a-zA-Z0-9_-]+', device_meta.get('DEVNAME', '')), 'Bounded builder backing block device is unavailable')
    io_device = '/dev/' + device_meta['DEVNAME']; io_stat = os.stat(io_device)
    require(stat.S_ISBLK(io_stat.st_mode), 'Builder I/O ceiling requires the actual block device')
    io_major_minor = str(os.major(io_stat.st_rdev)) + ':' + str(os.minor(io_stat.st_rdev))
    command = ['create', '--name', name, '--pull', 'never', '--user', '1000:1000', '--network', 'bridge',
        '--restart', 'no', '--memory', str(BUILDER_MEMORY), '--memory-swap', str(BUILDER_MEMORY), '--cpus', '2', '--pids-limit', '1024',
        '--device-write-bps', io_device + ':' + str(64 * MIB),
        '--security-opt', 'seccomp=unconfined', '--security-opt', 'apparmor=unconfined', '--security-opt', 'systempaths=unconfined',
        '--log-opt', 'max-size=5m', '--log-opt', 'max-file=1',
        '--tmpfs', '/run/user/1000:rw,nosuid,nodev,size=67108864,uid=1000,gid=1000,mode=0700',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=268435456,uid=1000,gid=1000',
        '--mount', 'type=volume,src=' + volume + ',dst=/home/user/.local/share/buildkit']
    if has_fuse: command += ['--device', '/dev/fuse:/dev/fuse:rwm']
    expected = [('volume', volume, '/home/user/.local/share/buildkit', True),
                ('tmpfs', '', '/run/user/1000', True), ('tmpfs', '', '/tmp', True)]
    for key, value in labels.items(): command += ['--label', key + '=' + value]
    for source, target, writable in mounts:
        source = safe(source)
        command += ['--mount', 'type=bind,src=' + str(source) + ',dst=' + target + ('' if writable else ',readonly')]
        expected.append(('bind', str(source), target, writable))
    command += ['--entrypoint', 'rootlesskit', image_identity['engineImageId'], 'buildkitd', '--addr', 'unix:///run/user/1000/buildkit/buildkitd.sock',
                '--root', '/home/user/.local/share/buildkit', '--oci-worker-snapshotter=' + snapshotter]
    cid = actor.docker(*command).decode().strip(); require(re.fullmatch(r'[a-f0-9]{64}', cid), 'Builder container ID unavailable')
    actor.builder = {'id': cid, 'mounts': sorted(expected), 'volume': volume, 'labels': labels, 'snapshotter': snapshotter,
                     'ioDevice': io_device, 'ioMajorMinor': io_major_minor, 'engineIdentity': image_identity}
    actor.owned_builder(); actor.run(['docker', 'start', cid], 'builder-start', timeout=90)
    row = actor.owned_builder(); pid = row['State']['Pid']; require(row['State']['Running'] and pid > 1, 'Rootless builder did not start')
    actor.builder['claim'] = {'pid': pid, 'startTicks': Path('/proc/' + str(pid) + '/stat').read_text().rsplit(')', 1)[1].split()[19],
        'cgroup': next(x.split(':', 2)[2] for x in Path('/proc/' + str(pid) + '/cgroup').read_text().splitlines() if x.startswith('0::'))}
    require(hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal')
            and next(line for line in Path('/proc/' + str(pid) + '/status').read_text().splitlines() if line.startswith('Uid:')).split()[1:3]
            == [str(os.getuid()), str(os.getuid())], 'Owned builder requires an unambiguous same-UID kernel process handle')
    actor.builder['pidfd'] = os.pidfd_open(pid, 0)
    require(Path('/proc/' + str(pid) + '/stat').read_text().rsplit(')', 1)[1].split()[19] == actor.builder['claim']['startTicks'], 'Builder changed during kernel-handle admission')
    actor.sample_builder()
    deadline = time.monotonic() + 60
    while True:
        actor.check()
        result = subprocess.run(['docker', 'exec', cid, 'buildctl', '--addr', 'unix:///run/user/1000/buildkit/buildkitd.sock',
                                 'debug', 'workers'], capture_output=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip(): break
        require(time.monotonic() < deadline, 'Rootless BuildKit prerequisites unavailable; no host settings are changed')
        time.sleep(0.5)
    return actor.builder


class RegistryRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require(newurl.startswith('https://'), 'Official image redirect must retain TLS')
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if result is not None: result.remove_header('Authorization')
        return result


def buildkit_input(args):
    values = [getattr(args, name, None) for name in ('buildkit_archive', 'buildkit_archive_sha256', 'buildkit_archive_bytes')]
    if all(value is None for value in values): return None
    path, checksum, size = values
    require(all(value is not None for value in values) and getattr(args, 'prepare_candidate_builder', False) is True
            and type(path) is str and type(checksum) is str and SHA.fullmatch(checksum)
            and type(size) is int and 0 < size <= BUILDKIT_ARCHIVE_MAX, 'Complete bounded BuildKit archive input is required')
    root_value = str(args.root); root = PurePosixPath(root_value)
    require(root.is_absolute() and str(root) == root_value and '\\' not in root_value and '..' not in root.parts
            and path == str(root / 'build-inputs' / ('buildkit-' + VERSION) / (checksum + '.tar')),
            'BuildKit archive must use its exact immutable cache path')
    return {'file': path, 'sha256': checksum, 'bytes': size}


def archive_metadata(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextlib.contextmanager
def buildkit_archive_source(root, binding, check):
    require(type(binding) is dict and set(binding) == {'file', 'sha256', 'bytes'}, 'Closed BuildKit archive binding is required')
    expected = buildkit_input(argparse.Namespace(root=str(root), prepare_candidate_builder=True,
        buildkit_archive=binding['file'], buildkit_archive_sha256=binding['sha256'], buildkit_archive_bytes=binding['bytes']))
    require(expected == binding, 'BuildKit archive binding differs')
    root = safe(root); path = safe(Path(binding['file']))
    directories = {}
    for parent in path.parents:
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o022 and info.st_uid in (0, 1000)
                and (not parent.is_relative_to(root) or info.st_uid == 1000), 'BuildKit archive ancestor is not owned and immutable')
        directories[parent] = (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode)
    def signature():
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 1000 and info.st_nlink == 1
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size == binding['bytes'], 'Private bounded BuildKit archive is required')
        return archive_metadata(info)
    admitted = signature()
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        require(archive_metadata(os.fstat(stream.fileno())) == admitted, 'BuildKit archive changed at open')
        def verify():
            stream.seek(0); checksum = hashlib.sha256(); size = 0
            for block in iter(lambda: stream.read(MIB), b''):
                size += len(block); require(size <= binding['bytes'], 'BuildKit archive grew during verification')
                checksum.update(block); check()
            require(size == binding['bytes'] and checksum.hexdigest() == binding['sha256']
                    and archive_metadata(os.fstat(stream.fileno())) == admitted == signature(), 'BuildKit archive original bytes changed')
            for parent, metadata in directories.items():
                info = parent.lstat()
                require(stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode) == metadata,
                        'BuildKit archive ancestor changed')
            stream.seek(0)
        verify()
        try: yield stream
        finally: verify()


def validate_buildkit_archive(root, binding, check=lambda: None):
    with buildkit_archive_source(root, binding, check): pass
    return dict(binding)


def archive_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate OCI metadata field')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(BuildResourceError('Nonfinite OCI metadata field')))


class ClosedBuildkitInfo(tarfile.TarInfo):
    @staticmethod
    def checked_header(entry):
        regular = entry.type in (tarfile.REGTYPE, tarfile.AREGTYPE)
        require((regular and 0 < entry.size <= BUILDKIT_ARCHIVE_MAX
                 and (entry.name in ('index.json', 'oci-layout') or re.fullmatch(r'blobs/sha256/[a-f0-9]{64}', entry.name)))
                or (entry.type == tarfile.DIRTYPE and entry.size == 0
                    and entry.name in ('blobs', 'blobs/', 'blobs/sha256', 'blobs/sha256/')), 'Foreign BuildKit OCI archive header')
        return entry
    @classmethod
    def frombuf(cls, raw, encoding, errors):
        return cls.checked_header(super().frombuf(raw, encoding, errors))
    def _proc_member(self, package):
        self.checked_header(self)
        return super()._proc_member(package)


def archive_layout(actor, root, binding, destination, inputs):
    """Read the pinned upstream OCI graph from one held, content-addressed input."""
    actor.begin('official-archive-validation', 4 * MIB, {'buildkitArchive': binding}, 128 * MIB)
    with buildkit_archive_source(root, binding, actor.check) as source:
        with tarfile.open(fileobj=source, mode='r:', tarinfo=ClosedBuildkitInfo) as package:
            members = {}
            for entry in package:
                name = entry.name.rstrip('/') if entry.isdir() else entry.name
                require(name not in members and len(members) < 128 and not entry.pax_headers and not entry.issparse(),
                        'Duplicate or extended BuildKit OCI archive member')
                members[name] = entry; actor.check()
            source.seek(package.offset); tail = 0
            for block in iter(lambda: source.read(MIB), b''):
                tail += len(block); require(not block.strip(b'\0'), 'Nonzero BuildKit OCI archive tail'); actor.check()
            require(tail >= 1024 and binding['bytes'] % 512 == 0, 'Truncated BuildKit OCI archive terminator')
            def small(name):
                require(name in members and members[name].isfile() and members[name].size <= 4 * MIB, 'Bounded OCI metadata is missing')
                raw = package.extractfile(members[name]).read(4 * MIB + 1)
                require(len(raw) == members[name].size, 'Truncated BuildKit OCI metadata')
                return raw
            require(archive_json(small('oci-layout')) == {'imageLayoutVersion': '1.0.0'}, 'BuildKit OCI layout differs')
            index = archive_json(small('index.json'))
            require(type(index) is dict and set(index) == {'schemaVersion', 'manifests'}
                    and type(index['schemaVersion']) is int and index['schemaVersion'] == 2
                    and type(index['manifests']) is list and len(index['manifests']) == 1, 'Single pinned BuildKit OCI index is required')
            descriptor = index['manifests'][0]; upstream = REFERENCE.split('@', 1)[1]
            require(type(descriptor) is dict and set(descriptor) == {'mediaType', 'digest', 'size'}
                    and descriptor['mediaType'] == 'application/vnd.oci.image.manifest.v1+json'
                    and descriptor['digest'] == upstream and type(descriptor['size']) is int and 0 < descriptor['size'] <= 4 * MIB,
                    'BuildKit OCI index is not the pinned upstream manifest')
            manifest_name = 'blobs/sha256/' + upstream[7:]; raw = small(manifest_name)
            require(len(raw) == descriptor['size'] and 'sha256:' + hashlib.sha256(raw).hexdigest() == upstream, 'Upstream BuildKit manifest bytes differ')
            manifest = archive_json(raw)
            require(type(manifest) is dict and type(manifest.get('schemaVersion')) is int and manifest['schemaVersion'] == 2
                    and manifest.get('mediaType') == 'application/vnd.oci.image.manifest.v1+json'
                    and type(manifest.get('config')) is dict and type(manifest.get('layers')) is list
                    and 0 < len(manifest['layers']) <= 128, 'Pinned BuildKit manifest metadata differs')
            descriptors = [manifest['config'], *manifest['layers']]
            for number, row in enumerate(descriptors):
                require(type(row) is dict and set(row) == {'mediaType', 'digest', 'size'}
                        and type(row['digest']) is str and IMAGE.fullmatch(row['digest'])
                        and type(row['size']) is int and 0 < row['size'] <= BUILDKIT_ARCHIVE_MAX
                        and row['mediaType'] == ('application/vnd.oci.image.config.v1+json' if number == 0
                                                else 'application/vnd.oci.image.layer.v1.tar+gzip'), 'BuildKit OCI descriptor is invalid')
            require(manifest['config']['digest'] == IMAGE_ID and len({row['digest'] for row in descriptors}) == len(descriptors)
                    and sum(row['size'] for row in manifest['layers']) == BUILDKIT_LAYER_BYTES, 'Pinned BuildKit config or original layer bytes differ')
            wanted = {'oci-layout', 'index.json', manifest_name, *['blobs/sha256/' + row['digest'][7:] for row in descriptors]}
            require({name for name, entry in members.items() if entry.isfile()} == wanted
                    and all(members['blobs/sha256/' + row['digest'][7:]].size == row['size'] for row in descriptors), 'BuildKit OCI member closure differs')
            total = sum(row['size'] for row in descriptors)
            actor.begin('copy-official-oci', total + 8 * MIB, {'buildkitArchive': binding, 'compressedInputBytes': total}, 128 * MIB)
            require(not destination.exists() and not destination.is_symlink(), 'BuildKit OCI output must be fresh')
            destination.mkdir(mode=0o700); (destination / 'blobs').mkdir(mode=0o700); (destination / 'blobs/sha256').mkdir(mode=0o700)
            expected = {'blobs/sha256/' + row['digest'][7:]: row['digest'][7:] for row in descriptors}
            expected[manifest_name] = upstream[7:]
            for name in sorted(wanted):
                checksum = hashlib.sha256(); count = 0
                with package.extractfile(members[name]) as origin, os.fdopen(os.open(destination / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as output:
                    for block in iter(lambda: origin.read(MIB), b''):
                        count += len(block); require(count <= members[name].size, 'BuildKit OCI member grew')
                        checksum.update(block); output.write(block); actor.check()
                    output.flush(); os.fsync(output.fileno())
                require(count == members[name].size and (name not in expected or checksum.hexdigest() == expected[name]), 'BuildKit OCI member bytes differ')
    return measure_registry_layout(actor, destination, inputs, raw, manifest, total)


def prepare_tools(args, identity, recipe_directory):
    """Called only by the existing pinned PrepareTools entry, entirely on ECS."""
    require(sys.platform == 'linux' and os.getuid() == 1000, 'The admitted ECS tool owner is required')
    supplied = buildkit_input(args)
    root = safe(args.root); inbox = safe(root / 'inbox' / args.tag); recipe_directory = safe(recipe_directory)
    require(digest(recipe_directory / 'LICENSE') == LICENSE_SHA, 'Pinned upstream license differs')
    context = {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256, 'identity': identity}
    actor = Supervisor(inbox / 'candidate-build-tools', context)
    inputs = load_module('prepared_image_inputs', recipe_directory / 'compact-image-inputs.py')
    try:
        actor.begin('tool-metadata', 4 * MIB, {'imageReference': REFERENCE, 'imageId': IMAGE_ID}, 128 * MIB)
        (actor.directory / 'LICENSE').write_bytes((recipe_directory / 'LICENSE').read_bytes()); os.chmod(actor.directory / 'LICENSE', 0o600)
        # An already installed config ID alone does not establish that this
        # Docker engine accepts the OCI output format used below. Re-admit the
        # exact official bytes and perform the same bounded OCI load each time.
        proof = (archive_layout(actor, root, supplied, actor.directory / 'official-oci', inputs) if supplied is not None
                 else registry_layout(actor, REFERENCE, actor.directory / 'official-oci', inputs))
        require(proof['imageId'] == IMAGE_ID and proof['compressedBytes'] == BUILDKIT_LAYER_BYTES, 'Pinned official BuildKit bytes differ')
        write(actor.directory / 'official-layer-measurements.json', proof)
        engine_id = engine_lookup_id(actor, proof, proof['loadDescriptor'])
        result = subprocess.run(['docker', 'image', 'inspect', engine_id], capture_output=True, timeout=15)
        installed = result.returncode == 0
        actor.begin('tool-image-archive', proof['compressedBytes'] + 8 * MIB,
                    {'officialLayerMeasurementsSha256': digest(actor.directory / 'official-layer-measurements.json')}, 128 * MIB)
        archive = actor.directory / 'official-image.tar'; layout = actor.directory / 'official-oci'
        with tarfile.open(archive, 'x', format=tarfile.PAX_FORMAT) as package:
            os.chmod(archive, 0o600)
            for path in sorted(layout.rglob('*')):
                if path.is_file(): monitored_tar_file(package, path, path.relative_to(layout).as_posix(), actor.check)
        present = host_diff_ids(actor)
        required = sum(row['allocationUpperBoundBytes'] for row in proof['layers'] if row['diffId'] not in present) + 2 * proof['compressedBytes'] + 64 * MIB
        actor.begin('tool-image-load', required, {'officialLayerMeasurementsSha256': digest(actor.directory / 'official-layer-measurements.json'),
                    'measuredLoadGrowthUpperBoundBytes': required, 'compressedIngestCopiesUpperBound': 2}, 256 * MIB)
        actor.daemon_import_unknown = True
        actor.run(['docker', 'load', '--input', str(archive)], 'official-image-load', timeout=300)
        actor.daemon_import_unknown = False
        row = json.loads(actor.docker('image', 'inspect', engine_id))[0]
        engine = engine_identity(row, proof, proof['loadDescriptor'])
        unique_image_inputs([row]); require(row['Config'].get('User') in ('1000', '1000:1000'), 'Official builder is not rootless UID1000')
        bootstrap_builder(actor, image_identity=engine)
        versions = {}
        for name in ('buildctl', 'buildkitd'):
            log = actor.run(['docker', 'exec', actor.builder['id'], name, '--version'], name + '-version', maximum=MIB, timeout=30)
            text = log.read_text(encoding='utf8'); require(VERSION in text and len(text) <= 4096, 'Actual BuildKit version differs')
            versions[name] = {'file': log.name, 'sha256': digest(log)}
        if supplied is not None: validate_buildkit_archive(root, supplied, actor.check)
        resources = actor.finish('PASS')
        value = {'version': 1, 'kind': 'doorhandle-candidate-build-tools', 'status': 'PREPARED', **context,
                 'imageId': IMAGE_ID, 'imageReference': REFERENCE, 'upstreamVersion': VERSION,
                 'sourceUrl': 'https://github.com/moby/buildkit/releases/tag/' + VERSION, 'license': 'Apache-2.0',
                 'licenseSha256': LICENSE_SHA, 'licenseFile': str(actor.directory / 'LICENSE'), 'hostPluginInstalled': False,
                 'buildctlBundled': True, 'versions': versions, 'ociImageLoadVerified': True,
                 'reusedImage': installed, 'resourceEvidence': resources,
                 'helperSha256': digest(recipe_directory / 'compact-build-resources.py'),
                 'imageInputsHelperSha256': digest(recipe_directory / 'compact-image-inputs.py'),
                 'engineIdentity': engine, 'imageMeasurementSha256': digest(actor.directory / 'official-layer-measurements.json')}
        if supplied is not None: value['buildkitArchive'] = supplied
        write(actor.directory / 'tools.json', value)
        return {'file': str(actor.directory / 'tools.json'), 'sha256': digest(actor.directory / 'tools.json'),
                'imageId': IMAGE_ID, 'status': 'PREPARED'}
    except BaseException:
        with contextlib.suppress(BaseException): actor.finish('FAILED')
        raise


def host_diff_ids(actor):
    """Layer identity only; Docker tag Size is never an incremental budget."""
    ids = sorted(set(actor.docker('image', 'ls', '--quiet', '--no-trunc').decode().split()))
    require(len(ids) <= 512, 'Host image inventory exceeds its reviewed bound')
    layers = set()
    for start in range(0, len(ids), 32):
        for row in actor.docker('image', 'inspect', '--format', '{{json .RootFS.Layers}}', *ids[start:start + 32]).decode().splitlines():
            layers.update(json.loads(row) or [])
    require(all(IMAGE.fullmatch(value) for value in layers), 'Host DiffID inventory is malformed')
    return layers


def context_inventory(path):
    path = safe(path); rows = []; allocated = 0
    for current, directories, files in os.walk(path, followlinks=False):
        directories.sort()
        for name in sorted(directories + files):
            item = Path(current) / name; info = item.lstat()
            require(not item.is_symlink() and (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)),
                    'Image context contains a link/device')
            if item.is_file():
                require(len(rows) < 10000 and info.st_size <= 512 * MIB, 'Image context exceeds its bounded source scope')
                rows.append([item.relative_to(path).as_posix(), info.st_size, digest(item)])
                allocated += ((info.st_size + 4095) // 4096) * 4096 + 4096
    return {'files': len(rows), 'bytes': sum(row[1] for row in rows), 'allocationUpperBoundBytes': allocated,
            'sha256': hashlib.sha256(encoded(rows)).hexdigest()}


def registry_layout(actor, reference, destination, inputs):
    """Fetch only an immutable Docker Hub platform manifest; no daemon pull."""
    match = re.fullmatch(r'(?:docker.io/)?([a-z0-9_./-]+)(?::[A-Za-z0-9_.-]+)?@(sha256:[a-f0-9]{64})', reference)
    require(match, 'Only source-pinned Docker Hub dependency manifests are supported')
    repository = match[1] if '/' in match[1] else 'library/' + match[1]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), RegistryRedirect())
    def small(url, headers=None):
        actor.check()
        with opener.open(urllib.request.Request(url, headers=headers or {}), timeout=30) as response: raw = response.read(4 * MIB + 1)
        require(len(raw) <= 4 * MIB, 'Dependency registry metadata is oversized'); actor.check(); return raw
    token = json.loads(small('https://auth.docker.io/token?service=registry.docker.io&scope=repository:' + repository + ':pull'))['token']
    headers = {'Authorization': 'Bearer ' + token, 'Accept': ','.join(['application/vnd.oci.image.manifest.v1+json',
        'application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.v2+json',
        'application/vnd.docker.distribution.manifest.list.v2+json'])}
    base = 'https://registry-1.docker.io/v2/' + repository + '/'
    def manifest(identifier):
        raw = small(base + 'manifests/' + identifier, headers)
        require('sha256:' + hashlib.sha256(raw).hexdigest() == identifier, 'Pinned dependency manifest bytes differ')
        return raw, json.loads(raw)
    raw, value = manifest(match[2])
    if 'manifests' in value:
        matches = [row for row in value['manifests'] if row.get('platform', {}).get('os') == 'linux'
                   and row.get('platform', {}).get('architecture') == 'amd64' and not row.get('platform', {}).get('variant')]
        require(len(matches) == 1, 'One immutable linux/amd64 platform is required')
        raw, value = manifest(matches[0]['digest'])
    require(value.get('schemaVersion') == 2 and 0 < len(value.get('layers', [])) <= 128, 'Dependency layer catalogue is unsupported')
    descriptors = [value['config'], *value['layers']]
    require(all(IMAGE.fullmatch(row['digest']) and type(row['size']) is int and 0 < row['size'] <= 2 * GIB for row in descriptors),
            'Dependency descriptor is outside its bound')
    total = sum(row['size'] for row in descriptors)
    actor.begin('download-' + destination.name, total + 8 * MIB,
                {'pinnedReference': reference, 'platformManifestSha256': hashlib.sha256(raw).hexdigest(), 'compressedInputBytes': total}, 128 * MIB)
    (destination / 'blobs/sha256').mkdir(mode=0o700, parents=True)
    for row in descriptors:
        target = destination / 'blobs/sha256' / row['digest'][7:]
        if target.exists(): continue
        h = hashlib.sha256(); count = 0
        with opener.open(urllib.request.Request(base + 'blobs/' + row['digest'], headers=headers), timeout=30) as response, target.open('xb') as output:
            os.chmod(target, 0o600)
            for block in iter(lambda: response.read(MIB), b''):
                count += len(block); require(count <= row['size'], 'Dependency blob exceeded the signed descriptor')
                h.update(block); output.write(block); actor.check()
        require(count == row['size'] and 'sha256:' + h.hexdigest() == row['digest'], 'Dependency blob hash differs')
    manifest_sha = hashlib.sha256(raw).hexdigest()
    (destination / 'blobs/sha256' / manifest_sha).write_bytes(raw)
    write(destination / 'oci-layout', {'imageLayoutVersion': '1.0.0'})
    write(destination / 'index.json', {'schemaVersion': 2, 'manifests': [{'mediaType': value.get('mediaType', 'application/vnd.oci.image.manifest.v1+json'),
        'digest': 'sha256:' + manifest_sha, 'size': len(raw)}]})
    return measure_registry_layout(actor, destination, inputs, raw, value, total)


def measure_registry_layout(actor, destination, inputs, raw, value, total):
    manifest_sha = hashlib.sha256(raw).hexdigest()
    # A bounded temporary tar permits the same layer/DiffID/expansion verifier
    # as custom host images. Only this new, reproducible archive is removed.
    actor.begin('measure-' + destination.name, total + 8 * MIB, {'compressedInputBytes': total}, 128 * MIB)
    archive = destination.parent / (destination.name + '-measure.tar')
    with tarfile.open(archive, 'x') as package:
        os.chmod(archive, 0o600)
        for path in sorted(destination.rglob('*')):
            if path.is_file(): monitored_tar_file(package, path, path.relative_to(destination).as_posix(), actor.check)
    try: result = inputs.inspect_docker_archive(archive, maximum_uncompressed_bytes=8 * GIB, check=actor.check)
    finally: archive.unlink()
    normalized = encoded({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
        'config': {'mediaType': 'application/vnd.oci.image.config.v1+json', 'digest': result['configDigest'], 'size': value['config']['size']},
        'layers': [{'mediaType': row['mediaType'], 'digest': row['blobDigest'], 'size': row['bytes']} for row in result['layers']]})
    require('sha256:' + hashlib.sha256(normalized).hexdigest() == result['manifestDigest'], 'Normalized OCI dependency proof differs')
    target = destination / 'blobs/sha256' / result['manifestDigest'][7:]
    if not target.exists(): target.write_bytes(normalized); os.chmod(target, 0o600)
    if manifest_sha != result['manifestDigest'][7:]: (destination / 'blobs/sha256' / manifest_sha).unlink()
    (destination / 'index.json').write_bytes(encoded({'schemaVersion': 2, 'manifests': [{'mediaType': 'application/vnd.oci.image.manifest.v1+json',
        'digest': result['manifestDigest'], 'size': len(normalized)}]}))
    result['loadDescriptor'] = {'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                                'digest': result['manifestDigest'], 'size': len(normalized)}
    config = result.pop('config'); unique_image_inputs([{'Id': result['imageId'], 'Os': config['os'],
        'Architecture': config['architecture'], 'Config': config.get('config') or {}, 'RootFS': {'Layers': [row['diffId'] for row in result['layers']]}, 'Size': 0}])
    return result


def local_layout(actor, image, destination, inputs):
    row = json.loads(actor.docker('image', 'inspect', image))[0]
    item = unique_image_inputs([row])[image]; require(item['diffIds'], 'Immutable dependency has no layers')
    descriptor = engine_descriptor(row['Descriptor'], metadata=True) if row.get('Descriptor') is not None else None
    native = descriptor is not None and row['Id'] == descriptor['digest']
    # Stream Docker's byte export directly into OCI blobs. Declared tar member
    # sizes are admitted before writing; no second full Torch archive is made.
    actor.begin('export-' + destination.name, 16 * MIB, {'imageId': image, 'diffIds': item['diffIds'], 'measurement': 'STREAM_HEADERS'}, 256 * MIB)
    process = subprocess.Popen(['docker', 'image', 'save', image], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, start_new_session=True, env={k: v for k, v in os.environ.items() if k in ('PATH', 'LANG', 'LC_ALL')})
    actor.process = process; deadline = time.monotonic() + 900
    actor.process_deadline = deadline
    def check():
        actor.check(); require(time.monotonic() <= deadline, 'Dependency byte export timed out')
    def before(name, size):
        check()
        if size > MIB:
            actor.begin('export-member-' + destination.name, size + 8 * MIB,
                {'imageId': image, 'memberBytes': size, 'memberNameSha256': hashlib.sha256(name.encode()).hexdigest()}, 256 * MIB)
    try:
        result = inputs.export_stream_to_oci(process.stdout, destination, None if native else image, item['diffIds'], 8 * GIB,
                                             before, check, expected_engine_descriptor=descriptor if native else None)
        require(process.wait(timeout=10) == 0, 'Dependency byte export failed')
        engine_identity(row, result, result['loadDescriptor'])
        return result
    finally:
        process.stdout.close()
        if process.poll() is None:
            require(os.getpgid(process.pid) == process.pid, 'Dependency export process identity changed')
            os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=10)
        actor.process = None
        actor.process_deadline = None


def admit_tools(root, context, module_directory):
    directory = safe(Path(root) / 'inbox' / context['release'] / 'candidate-build-tools')
    value = read(directory / 'tools.json')
    require(all(value.get(key) == expected for key, expected in {**context, 'kind': 'doorhandle-candidate-build-tools',
        'status': 'PREPARED', 'imageId': IMAGE_ID, 'imageReference': REFERENCE, 'licenseSha256': LICENSE_SHA,
        'buildctlBundled': True, 'ociImageLoadVerified': True, 'hostPluginInstalled': False}.items()), 'Pinned same-attempt candidate tools are not prepared')
    require(value['helperSha256'] == digest(module_directory / 'compact-build-resources.py')
            and value['imageInputsHelperSha256'] == digest(module_directory / 'compact-image-inputs.py'), 'Prepared builder helper differs from fixed source')
    reference = value['resourceEvidence']; summary = read(directory / 'resource-summary.json')
    require(reference == {'file': str(directory / 'resource-summary.json'), 'sha256': digest(directory / 'resource-summary.json')}, 'Builder preparation receipt changed')
    validate_files(directory, context, require_services=False)
    engine = measured_tool_identity(directory, value)
    require(summary.get('engineIdentity') == engine, 'Builder resource and tool engine identities differ')
    require(summary['status'] == 'PASS', 'Builder preparation did not pass')
    return {'file': str(directory / 'tools.json'), 'sha256': digest(directory / 'tools.json')}


def measured_tool_identity(directory, value):
    measurement_file = Path(directory) / 'official-layer-measurements.json'; measurement = read(measurement_file)
    require(value.get('imageMeasurementSha256') == digest(measurement_file)
            and measurement.get('configDigest') == IMAGE_ID and measurement.get('imageId') == IMAGE_ID
            and measurement.get('compressedBytes') == BUILDKIT_LAYER_BYTES
            and measurement.get('loadDescriptor', {}).get('digest') == measurement.get('manifestDigest'),
            'Official builder measurement identity differs')
    engine = stored_builder_identity(value.get('engineIdentity'))
    row = {'Id': engine['engineImageId'], 'Descriptor': engine['loadDescriptor'], 'Os': engine['os'],
           'Architecture': engine['architecture'], 'RootFS': {'Layers': engine['diffIds']}}
    require(engine_identity(row, measurement, measurement['loadDescriptor']) == engine,
            'Official builder engine/config/measurement binding differs')
    return engine


def tool_engine_identity(root, context, module_directory):
    """Read-only complete same-attempt tool proof; Docker is inspected by callers."""
    admit_tools(root, context, module_directory)
    directory = Path(root) / 'inbox' / context['release'] / 'candidate-build-tools'
    return measured_tool_identity(directory, read(directory / 'tools.json'))


def build_images(actor, root, source, specifications):
    """One fresh builder, serial images, exact OCI input and output bytes."""
    module_directory = source / 'script/docker'; tool_proof = admit_tools(root, {key: value for key, value in actor.context.items() if key != 'ownerToken'}, module_directory)
    engine = tool_engine_identity(root, {key: value for key, value in actor.context.items() if key != 'ownerToken'}, module_directory)
    inputs = load_module('candidate_image_inputs', module_directory / 'compact-image-inputs.py')
    require(0 < len(specifications) <= 4 and len({item['service'] for item in specifications}) == len(specifications), 'Candidate image set is invalid')
    oci = actor.directory / 'oci-inputs'; oci.mkdir(mode=0o700)
    output = actor.directory / 'outputs'; output.mkdir(mode=0o700)
    mounts = []; prepared = []; catalogue = {}
    for item in specifications:
        service = item['service']; require(re.fullmatch(r'[a-z][a-z0-9-]{0,31}', service), 'Invalid fixed image service')
        context = safe(item['context']); inventory = context_inventory(context)
        require(context.is_relative_to(source / 'work') or context.is_relative_to(Path(root) / 'verification' / actor.context['release'] / 'checkout/work/runtime-acceptance'),
                'Image context escaped this owned attempt')
        body = (context / 'Dockerfile').read_text(encoding='utf8'); matches = re.findall(r'^FROM\s+(\S+)', body, re.M)
        require(len(matches) == 1 and not re.search(r'^\s*(?:ADD|ONBUILD)\b', body, re.M | re.I), 'Only the reviewed single-stage COPY closure is allowed')
        base = matches[0]
        if base not in catalogue:
            name = 'base' + str(len(catalogue)); directory = oci / name
            proof = local_layout(actor, base, directory, inputs) if IMAGE.fullmatch(base) else registry_layout(actor, base, directory, inputs)
            catalogue[base] = {'name': name, 'proof': proof}
            write(actor.directory / (name + '-input.json'), proof)
            mounts.append((directory, '/inputs/' + name, False))
        alias = 'dh_base_' + service.replace('-', '_')
        effective = context / 'Dockerfile.controlled'
        effective_body = effective_dockerfile(body, base, alias)
        for key, value in sorted(item.get('labels', {}).items()):
            require(key == 'io.doorhandle.rehearsal' and re.fullmatch(r'doorhandle-rehearsal-[a-f0-9]{12}', value), 'Unreviewed runtime image label')
            effective_body += 'LABEL ' + key + '=' + json.dumps(value) + '\n'
        with effective.open('x', encoding='utf8') as stream: stream.write(effective_body)
        os.chmod(effective, 0o600)
        prepared.append({**item, 'inventory': inventory, 'base': catalogue[base], 'alias': alias, 'dockerfileSha256': digest(effective)})
        mounts.append((context, '/contexts/' + service, False))
    mounts.append((output, '/outputs', True)); bootstrap_builder(actor, mounts, image_identity=engine)
    results = {}
    for item in prepared:
        service = item['service']; base = item['base']; layers = base['proof']['layers']; context = item['inventory']
        base_alloc = sum(row['allocationUpperBoundBytes'] for row in layers)
        base_raw = sum(row['uncompressedBytes'] for row in layers)
        # RUN dependency writes are an explicitly enforced experimental limit,
        # not measured application capacity. Native snapshots additionally copy
        # the full measured base at every mutating instruction.
        run_bound = item.get('runWriteEnvelopeBytes', 0)
        require(type(run_bound) is int and 0 <= run_bound <= 2 * GIB, 'Invalid controlled RUN write envelope')
        mutations = len(re.findall(r'^\s*(?:RUN|COPY)\b', (item['context'] / 'Dockerfile').read_text(), re.M | re.I))
        native = base_alloc * mutations if actor.builder['snapshotter'] == 'native' else 0
        # Existing gzip blobs are carried through byte-for-byte. Only new or
        # originally uncompressed layers need a raw-byte compression envelope.
        base_archive = sum(row['bytes'] if row['mediaType'].endswith('+gzip') else row['uncompressedBytes'] + MIB for row in layers)
        archive_bound = base_archive + context['allocationUpperBoundBytes'] + run_bound + 16 * MIB
        growth = base_alloc + sum(row['bytes'] for row in layers) + context['allocationUpperBoundBytes'] + 2 * run_bound + archive_bound + native + 64 * MIB
        actor.begin('build-' + service, growth, {'baseInputSha256': digest(actor.directory / (base['name'] + '-input.json')),
            'baseAllocationUpperBoundBytes': base_alloc, 'context': context, 'runWriteEnvelopeBytes': run_bound,
            'runEnvelopeMeaning': 'ENFORCED_EXPERIMENT_BOUND_NOT_CAPACITY_PREDICTION', 'archiveUpperBoundBytes': archive_bound,
            'existingGzipBlobBytes': sum(row['bytes'] for row in layers if row['mediaType'].endswith('+gzip')),
            'nativeSnapshotCopiesUpperBoundBytes': native, 'snapshotter': actor.builder['snapshotter']}, BUILDER_MEMORY)
        command = ['docker', 'exec', actor.builder['id'], 'buildctl', '--addr', 'unix:///run/user/1000/buildkit/buildkitd.sock', 'build',
            '--frontend', 'dockerfile.v0', '--local', 'context=/contexts/' + service, '--local', 'dockerfile=/contexts/' + service,
            '--opt', 'filename=Dockerfile.controlled', '--opt', 'context:' + item['alias'] + '=oci-layout://' + base['name'] + '@' + base['proof']['manifestDigest'],
            '--oci-layout', base['name'] + '=/inputs/' + base['name'], '--output', 'type=oci,compression=gzip,force-compression=false,name=' + item['tag'] + ',dest=/outputs/' + service + '.tar',
            '--metadata-file', '/outputs/' + service + '-metadata.json']
        for key, value in sorted(item.get('buildArgs', {}).items()):
            require(key == 'PIP_INDEX_URL' and value == 'https://mirrors.aliyun.com/pypi/simple', 'Unreviewed image build argument')
            command += ['--opt', 'build-arg:' + key + '=' + value]
        actor.run(command, 'build-' + service, timeout=1800)
        archive = output / (service + '.tar'); require(archive.stat().st_size <= archive_bound, 'OCI output exceeded its admitted bound')
        result = inputs.inspect_docker_archive(archive, maximum_uncompressed_bytes=base_raw + context['allocationUpperBoundBytes'] + run_bound + 16 * MIB, check=actor.check)
        config = result.pop('config'); unique_image_inputs([{'Id': result['imageId'], 'Os': config['os'], 'Architecture': config['architecture'],
            'Config': config.get('config') or {}, 'RootFS': {'Layers': [row['diffId'] for row in result['layers']]}, 'Size': 0}])
        require(len(result['layers']) >= len(layers) and all(
            actual['diffId'] == original['diffId'] and (not original['mediaType'].endswith('+gzip') or actual['blobDigest'] == original['blobDigest'])
            for original, actual in zip(layers, result['layers'])), 'Candidate export did not preserve the measured dependency layers')
        current = host_diff_ids(actor)
        unique = [row for row in result['layers'] if row['diffId'] not in current]
        new_allocation = sum(row['allocationUpperBoundBytes'] for row in unique)
        compressed = sum(row['bytes'] for row in result['layers'])
        # DiffID establishes shared unpacked content, not whether this exact
        # compressed blob is already in containerd's content store. Reserve
        # both ingest/temporary compressed copies without claiming dedup.
        required = new_allocation + 2 * compressed + 64 * MIB
        actor.begin('load-' + service, required, {'ociArchiveBytes': archive.stat().st_size, 'ociArchiveSha256': digest(archive),
            'uniqueNewDiffIds': [row['diffId'] for row in unique], 'measuredUniqueLayerAllocationUpperBoundBytes': new_allocation,
            'allCompressedBlobBytes': compressed, 'compressedIngestCopiesUpperBound': 2, 'loadGrowthUpperBoundBytes': required}, 256 * MIB)
        actor.daemon_import_unknown = True
        actor.run(['docker', 'load', '--input', str(archive)], 'load-' + service, timeout=600)
        actor.daemon_import_unknown = False
        engine_id = engine_lookup_id(actor, result, result['loadDescriptor'])
        loaded = json.loads(actor.docker('image', 'inspect', engine_id))[0]
        loaded_identity = engine_identity(loaded, result, result['loadDescriptor'])
        unique_image_inputs([loaded])
        actor.run(['docker', 'tag', loaded_identity['engineImageId'], item['tag']], 'tag-' + service, timeout=30)
        actual = json.loads(actor.docker('image', 'inspect', item['tag']))[0]
        validate_engine_identity(actual, loaded_identity)
        results[service] = {'imageId': loaded_identity['engineImageId'], 'configDigest': result['configDigest'],
            'manifestDigest': result['manifestDigest'], 'loadDescriptor': result['loadDescriptor'], 'engineIdentity': loaded_identity,
            'ociArchiveSha256': result['archiveSha256'], 'ociArchiveBytes': result['archiveBytes'],
            'inputContext': context, 'controlledDockerfileSha256': item['dockerfileSha256'], 'layers': result['layers']}
        write(actor.directory / ('image-' + service + '.json'), results[service])
        # These are newly produced, reproducible build outputs only. Retain
        # their measured digest/catalogue; original inputs and data stay put.
        archive.unlink()
    return {'tools': tool_proof, 'images': results}


def runtime_image(root, source, args, identity, context, tag, name, project):
    require(name in ('model', 'mcp') and context == Path(root) / 'verification' / args.tag / 'checkout/work/runtime-acceptance' / (name + '-image')
            and re.fullmatch(r'doorhandle-rehearsal-[a-f0-9]{12}', project)
            and tag == 'doorhandlecatch/runtime-' + name + ':' + args.tag + '-' + project.removeprefix('doorhandle-rehearsal-'),
            'Runtime fixture build escaped its owned fixed context')
    actor = Supervisor(context.parent / ('controlled-build-' + name), {'release': args.tag, 'commit': args.commit,
        'sourceSha256': args.source_sha256, 'identity': identity})
    try:
        build = build_images(actor, root, source, [{'service': name, 'context': context, 'tag': tag,
            'labels': {'io.doorhandle.rehearsal': project}}])
        reference = actor.finish('PASS', build=build)
        result = validate_files(actor.directory, {'release': args.tag, 'commit': args.commit,
            'sourceSha256': args.source_sha256, 'identity': identity}, require_services=False)
        require(result['sha256'] == reference['sha256'], 'Runtime build proof changed')
        return {'file': 'checkout/work/runtime-acceptance/controlled-build-' + name + '/resource-summary.json', 'sha256': result['sha256']}
    except BaseException:
        if not (actor.directory / 'resource-summary.json').exists():
            with contextlib.suppress(BaseException): actor.finish('FAILED')
        raise


def fixture_build_evidence(runtime, require_pass=False):
    result = {}
    context = {'release': runtime.args.tag, 'commit': runtime.args.commit, 'sourceSha256': runtime.args.source_sha256, 'identity': runtime.identity}
    for name in ('model', 'mcp'):
        directory = runtime.directory / ('controlled-build-' + name)
        if not directory.exists():
            require(not require_pass, 'Required runtime fixture image was not built'); continue
        summary = read(directory / 'resource-summary.json')
        require(all(summary.get(key) == value for key, value in context.items())
                and all(summary.get('cleanup', {}).get(key) is True for key in ('creatorStopped', 'builderStopped', 'daemonImportTerminated')),
                'Runtime fixture image creator cleanup is unknown')
        cid = summary['cleanup'].get('builderContainerId')
        if cid:
            require(re.fullmatch(r'[a-f0-9]{64}', cid), 'Fixture builder ID is invalid')
            row = json.loads(runtime.ops.docker('inspect', cid))[0]
            labels = row['Config'].get('Labels') or {}
            engine = stored_builder_identity(summary.get('engineIdentity'))
            require(row['Id'] == cid and row['Image'] == engine['engineImageId'] and labels.get(LABEL) == summary['ownerToken']
                    and labels.get('io.doorhandle.release') == runtime.args.tag and labels.get('io.doorhandle.source') == runtime.args.source_sha256
                    and not row['State']['Running'] and row['State']['Pid'] == 0, 'Fixture image builder remains active or lost ownership')
        if require_pass:
            validate_files(directory, context, require_services=False)
            expected = runtime.owner['modelFixtureImage' if name == 'model' else 'runtimeMcpImage']
            require(set(summary['build']['images']) == {name} and summary['build']['images'][name]['imageId'] == expected,
                    'Runtime fixture image differs from the measured build output')
        result[name] = {'file': 'checkout/work/runtime-acceptance/controlled-build-' + name + '/resource-summary.json',
                        'sha256': digest(directory / 'resource-summary.json')}
    return result


def validate_files(directory, context, require_services=True):
    """Read-only shared validator used on ECS and on downloaded CI evidence."""
    directory = Path(directory); raw = (directory / 'resource-summary.json').read_bytes()
    require(0 < len(raw) <= 2 * MIB, 'Candidate resource summary is oversized')
    summary = json.loads(raw)
    require(summary.get('version') == 1 and summary.get('kind') == 'doorhandle-candidate-build-resources'
            and re.fullmatch(r'[a-f0-9]{24}', summary.get('ownerToken', ''))
            and all(summary.get(key) == value for key, value in context.items()) and summary.get('status') == 'PASS'
            and summary.get('capacityVerdict') == 'CONTROLLED_MEASUREMENT' and summary.get('productionCapacityVerified') is False
            and summary.get('monitorFailure') is None and summary.get('originalDataChanged') is False
            and all(summary.get('cleanup', {}).get(key) is True for key in ('creatorStopped', 'builderStopped', 'daemonImportTerminated')),
            'Candidate resource identity, monitor or owned cleanup did not pass')
    engine = stored_builder_identity(summary.get('engineIdentity'))
    probes = (directory / 'resource-probes.jsonl').read_bytes()
    require(summary.get('probeFile') == 'resource-probes.jsonl' and 0 < len(probes) <= 64 * MIB
            and hashlib.sha256(probes).hexdigest() == summary.get('probeSha256'), 'Candidate raw resource observations changed')
    phases = {}; require(0 < len(summary.get('phases', [])) <= 512, 'Candidate phase catalogue is missing')
    for reference in summary['phases']:
        require(set(reference) == {'file', 'sha256'} and re.fullmatch(r'phase-[0-9]{2,3}\.json', reference['file']), 'Candidate phase escaped its fixed directory')
        path = directory / reference['file']; require(digest(path) == reference['sha256'], 'Candidate phase bytes changed')
        value = json.loads(path.read_bytes()); expected = phase_plan({**context, 'ownerToken': summary['ownerToken']}, value['phase'],
            value['baselineProbe'], value['growthEnvelopeBytes'], value['memoryAdmissionBytes'], value['measuredInputs'])
        require(value == expected and value['status'] == 'MEASUREMENT_ADMITTED', 'Candidate phase admission was forged or failed')
        require(value['phase'] not in phases, 'Candidate phase name was reused'); phases[value['phase']] = value
    previous = summary['baselineProbe']['monotonic']; observed = set(); builder_seen = False
    builder_identity = None; builder_peak = 0; phase_order = {name: index for index, name in enumerate(phases)}; current_order = -1
    for line in probes.splitlines():
        require(len(line) <= MIB, 'Candidate raw observation exceeds its bound'); row = json.loads(line)
        require(row['diskAvailableBytes'] >= DISK_FLOOR and row['memoryAvailableBytes'] >= MEMORY_FLOOR
                and (previous is None or 0 <= row['monotonic'] - previous <= 2), 'Candidate pressure/sampling boundary failed')
        previous = row['monotonic']; phase = row['phase']
        if phase != 'admission':
            require(phase in phases and max(0, phases[phase]['baselineProbe']['diskAvailableBytes'] - row['diskAvailableBytes']) <= phases[phase]['growthEnvelopeBytes'], 'Candidate phase growth exceeded its bound')
            require(phase_order[phase] >= current_order and row['monotonic'] >= phases[phase]['baselineProbe']['monotonic'], 'Candidate phase order or observation time was rewritten')
            current_order = phase_order[phase]
            observed.add(phase)
        if row.get('builder'):
            builder = row['builder']; require(builder.get('oomKills') == 0 and builder.get('memoryLimitBytes') == BUILDER_MEMORY
                and 0 <= builder['currentBytes'] <= builder['peakBytes'] <= BUILDER_MEMORY and builder.get('image') == engine['engineImageId'],
                'Candidate builder cgroup/OOM evidence is invalid'); builder_seen = True
            require(builder.get('writeRateLimitBytesPerSecond') == 64 * MIB, 'Builder resource observations lost their write ceiling')
            identity = (builder.get('id'), builder.get('pid'))
            require(re.fullmatch(r'[a-f0-9]{64}', identity[0]) and type(identity[1]) is int and identity[1] > 1
                    and (builder_identity is None or builder_identity == identity) and builder['peakBytes'] >= builder_peak,
                    'Builder cgroup identity or peak was rewritten')
            builder_identity = identity; builder_peak = builder['peakBytes']
    require(observed == set(phases) and builder_seen, 'Candidate phases or owned builder observations are incomplete')
    require(any(name.startswith('builder-bootstrap-') and value['measuredInputs'].get('engineIdentity') == engine
                for name, value in phases.items()), 'Builder bootstrap and actual engine identity differ')
    final = summary['finalProbe']
    require(final['diskAvailableBytes'] >= DISK_FLOOR and final['memoryAvailableBytes'] >= MEMORY_FLOOR
            and 0 <= final['monotonic'] - previous <= 2 and summary['cleanup'].get('builderContainerId') == builder_identity[0],
            'Candidate final reserve or actual stopped builder differs')
    if require_services:
        require(set(summary.get('build', {}).get('images', {})) == set(SERVICES), 'Candidate image build set is incomplete')
        require(all(any(name.startswith(prefix + '-') for name in phases) for prefix in (
            'source-extraction', 'stage-contexts', 'candidate-jar-readback', *['build-' + service for service in SERVICES], *['load-' + service for service in SERVICES])),
            'Candidate source, every image build/import and exact jar readback must be measured')
    for service, image in summary.get('build', {}).get('images', {}).items():
        require(re.fullmatch(r'[a-z][a-z0-9-]{0,31}', service) and IMAGE.fullmatch(image.get('imageId', ''))
                and SHA.fullmatch(image.get('ociArchiveSha256', '')) and type(image.get('ociArchiveBytes')) is int
                and image['ociArchiveBytes'] > 0 and SHA.fullmatch(image.get('controlledDockerfileSha256', ''))
                and SHA.fullmatch(image.get('inputContext', {}).get('sha256', '')) and 0 < len(image.get('layers', [])) <= 256,
                'Candidate image byte evidence is incomplete')
        binding = image.get('engineIdentity')
        require(type(binding) is dict and image['imageId'] == binding.get('engineImageId')
                and image.get('configDigest') == binding.get('configDigest')
                and image.get('loadDescriptor') == binding.get('loadDescriptor')
                and type(image.get('manifestDigest')) is str and IMAGE.fullmatch(image['manifestDigest']),
                'Candidate engine/config/load descriptor evidence differs')
        synthetic = {'Id': image['imageId'], 'Descriptor': image['loadDescriptor'], 'Os': 'linux', 'Architecture': 'amd64',
                     'RootFS': {'Layers': [item['diffId'] for item in image['layers']]}}
        validate_engine_identity(synthetic, binding)
        require(all(IMAGE.fullmatch(layer.get('diffId', '')) and IMAGE.fullmatch(layer.get('blobDigest', ''))
                    and type(layer.get('allocationUpperBoundBytes')) is int and layer['allocationUpperBoundBytes'] > 0
                    for layer in image['layers']), 'Candidate image layer evidence is incomplete')
    return {'file': 'work/candidate-build-resources/resource-summary.json', 'sha256': hashlib.sha256(raw).hexdigest()}


def validate_candidate(build, source, context):
    directory = Path(source) / 'work/candidate-build-resources'
    require(build.get('buildResourceEvidence') == validate_files(directory, context), 'Candidate build resource binding changed')
    summary = json.loads((directory / 'resource-summary.json').read_bytes())
    require(all(build.get('images', {}).get(service) == image['imageId'] for service, image in summary['build']['images'].items())
            and summary.get('applicationJar') == {'sha256': build.get('applicationJarSha256'), 'bytes': build.get('applicationJarBytes')},
            'Candidate controlled images or exact Jenkins jar differ')
    return build['buildResourceEvidence']


def build_candidate(args):
    """The source archive, contexts and all build creators share one watcher."""
    require(sys.platform == 'linux' and os.getuid() == 1000 and re.fullmatch(r'ci-[1-9][0-9]*-[a-f0-9]{12}', args.tag)
            and re.fullmatch(r'[a-f0-9]{40}', args.commit) and args.commit.startswith(args.tag.rsplit('-', 1)[1])
            and SHA.fullmatch(args.source_sha256), 'Admitted ECS owner and fixed candidate identity required')
    root = safe(args.root); inbox = safe(root / 'inbox' / args.tag); archive = safe(inbox / 'source.tar.gz')
    require(digest(archive) == args.source_sha256, 'Candidate source archive changed')
    rows, raw_recipes, total = [], {}, 0
    recipe_names = {'script/jenkins/prepare-ecs-tools.py', 'script/docker/compact-build-resources.py',
                    'script/docker/compact-image-inputs.py', 'deploy/buildkit/LICENSE'}
    with tarfile.open(archive, 'r:gz') as package:
        seen = set()
        for entry in package:
            path = Path(entry.name)
            require(entry.name not in seen and path.parts and not path.is_absolute() and '..' not in path.parts
                    and '\\' not in entry.name and path.parts[0] not in ('work', '.git', 'artifacts')
                    and (entry.isfile() or entry.isdir()) and entry.size <= 32 * MIB,
                    'Unsafe candidate source member')
            seen.add(entry.name); total += entry.size; rows.append(entry)
            require(len(rows) <= 50000 and total <= 512 * MIB, 'Candidate source archive exceeds its reviewed bound')
            if entry.name in recipe_names:
                require(entry.isfile() and entry.size <= MIB, 'Candidate preparation recipe is not a bounded file')
                raw_recipes[entry.name] = package.extractfile(entry).read()
        require(package.pax_headers.get('comment') == args.commit and set(raw_recipes) == recipe_names, 'Candidate source commit/recipe closure differs')
    directory = safe(Path(__file__).resolve().parent)
    for name, content in raw_recipes.items():
        require((directory / Path(name).name).read_bytes() == content, 'Prepared candidate recipe is not the fixed archive bytes')
    preparation = load_module('candidate_preparation_identity', directory / 'prepare-ecs-tools.py')
    identity = preparation.identity(args)
    context = {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256, 'identity': identity}
    admit_tools(root, context, directory)
    verified = read(inbox.parents[1] / 'verification' / args.tag / 'verification-receipt.json')
    require(all(verified.get(key) == value for key, value in {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
        'identity': identity, 'scope': 'mysql', 'status': 'PASS', 'verificationExitCode': 0, 'fixtureReadinessValidated': True}.items()),
        'Candidate extraction requires this exact passing MySQL verification')
    release = root / 'releases' / args.tag
    require(not release.exists() and not release.is_symlink() and safe(release.parent).stat().st_uid == os.getuid(), 'Fresh owned candidate release required')
    require(probe(root)['diskAvailableBytes'] >= DISK_FLOOR + 64 * 1024, 'Candidate cannot create its resource journal below the disk reserve')
    release.mkdir(mode=0o700); (release / 'work').mkdir(mode=0o700)
    actor = Supervisor(release / 'work/candidate-build-resources', context)
    try:
        growth = sum(((entry.size + 4095) // 4096) * 4096 + 4096 for entry in rows) + 16 * MIB
        actor.begin('source-extraction', growth, {'sourceArchiveSha256': args.source_sha256, 'sourceUnpackedBytes': total,
            'sourceMembers': len(rows), 'sourceBlockAllocationUpperBoundBytes': growth}, 256 * MIB)
        with tarfile.open(archive, 'r:gz') as package:
            for entry in package:
                actor.check(); target = release / entry.name
                if entry.isdir(): target.mkdir(mode=0o755, parents=True, exist_ok=True); continue
                target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                with package.extractfile(entry) as source, target.open('xb') as output:
                    os.chmod(target, 0o755 if entry.mode & 0o111 else 0o644)
                    for block in iter(lambda: source.read(MIB), b''): actor.check(); output.write(block)
        # Reuse the exact image snapshot protocol under the inherited lock.
        import fcntl
        lock = root / 'state/deploy.lock'; held, expected = os.fstat(9), lock.stat()
        require(stat.S_ISREG(held.st_mode) and held.st_nlink == 1 and (held.st_dev, held.st_ino) == (expected.st_dev, expected.st_ino),
                'Owned candidate requires the existing inherited deploy lock')
        fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
        actor.begin('current-image-baseline', 16 * MIB, {'snapshotProtocol': 'EXISTING_MCP_RUNTIME_IMAGE_SNAPSHOT'}, 256 * MIB)
        snapshots = load_module('candidate_existing_image_snapshot', release / 'script/docker/mcp-runtime.py')
        snapshots.snapshot(root / 'state', release / 'previous-images.yml', 'all', False)
        snapshots.snapshot(root / 'state', release / 'runtime-images.yml', 'runtime', False)
        candidate = load_module('owned_candidate_orchestration', release / 'script/docker/compact-candidate-build.py')
        values = ['build', *[value for name in ('root', 'runtime', 'tag', 'source_sha256', 'settings', 'instance_id', 'machine_id', 'commit')
            for value in ('--' + name.replace('_', '-'), str(getattr(args, name)))]]
        require(candidate.main(values, actor=actor) == 0, 'Owned candidate build did not complete')
        return 0
    except BaseException:
        if not (actor.directory / 'resource-summary.json').exists():
            with contextlib.suppress(BaseException): actor.finish('FAILED')
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only candidate resource evidence validation')
    parser.add_argument('action', choices=('validate', 'build-candidate'))
    for name in ('tag', 'commit', 'source-sha256', 'instance-id', 'machine-id'): parser.add_argument('--' + name, required=True)
    for name in ('directory', 'root', 'runtime', 'settings'): parser.add_argument('--' + name)
    parser.add_argument('--fixture', choices=('model', 'mcp'))
    args = parser.parse_args(argv)
    if args.action == 'build-candidate':
        for event in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(event, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        if args.action == 'build-candidate':
            require(all(getattr(args, name) for name in ('root', 'runtime', 'settings')) and not args.directory, 'Missing owned candidate paths')
            return build_candidate(args)
        require(args.directory and not any(getattr(args, name) for name in ('root', 'runtime', 'settings')), 'Read-only validation accepts only its evidence directory')
        value = validate_files(Path(args.directory), {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
            'identity': {'instanceId': args.instance_id, 'machineId': args.machine_id, 'executionLocation': 'ECS'}}, require_services=args.fixture is None)
        if args.fixture:
            summary = json.loads((Path(args.directory) / 'resource-summary.json').read_bytes())
            require(set(summary.get('build', {}).get('images', {})) == {args.fixture}, 'Required owned fixture image proof is incomplete')
        print(json.dumps({'status': 'PASS', **value})); return 0
    except BaseException as error:
        value = {'status': 'FAILED', 'errorType': type(error).__name__}
        if isinstance(error, BuildResourceError): value['error'] = str(error)
        print(json.dumps(value)); return 2


if __name__ == '__main__':
    raise SystemExit(main())
