"""Fresh synthetic Redis for the existing ECS verifier; never a production client.

Reuse only the formal Redis service's immutable image identity. The owned server
has no persistent volume, password, application keys or production network.
verify-remote owns prepare/check/stop and preserves the terminal receipt.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import time

MIB = 1024 ** 2
GIB = 1024 ** 3
MEMORY = 256 * MIB
MAXMEMORY = 64 * MIB
LABEL = 'io.doorhandle.redis-fixture'
PROJECT = 'doorhandlecatch-monolith'
ENTRYPOINT = '/usr/local/bin/redis-server'
ENVIRONMENT = frozenset({'DOORHANDLE_CACHE_REDIS_TEST_HOST', 'DOORHANDLE_CACHE_REDIS_TEST_PORT',
    'DOORHANDLE_CACHE_REDIS_TEST_DATABASE', 'DOORHANDLE_REQUIRE_REDIS_TESTS'})
FORMAL_PROJECTION = ('{"Id":{{json .Id}},"Image":{{json .Image}},'
    '"Project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"Service":{{json (index .Config.Labels "com.docker.compose.service")}}}')
# Only the public version field is selected from immutable image metadata, never
# the formal container environment or command (which can contain credentials).
IMAGE_PROJECTION = ('{"Id":{{json .Id}},"RedisVersion":['
    '{{range .Config.Env}}{{if eq (index (split . "=") 0) "REDIS_VERSION"}}{{json .}}{{end}}{{end}}]}')
SETTINGS = {'save': '', 'appendonly': 'no', 'maxmemory': str(MAXMEMORY),
            'maxmemory-policy': 'noeviction', 'databases': '1', 'maxclients': '64'}


def require(value, message):
    if not value:
        raise ValueError(message)


def private_write(path, raw):
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def formal_projection(row):
    require(isinstance(row, dict) and set(row) == {'Id', 'Image', 'Project', 'Service'}
            and re.fullmatch(r'[a-f0-9]{64}', row.get('Id', ''))
            and re.fullmatch(r'sha256:[a-f0-9]{64}', row.get('Image', ''))
            and row['Project'] == PROJECT and row['Service'] == 'redis',
            'Formal Redis immutable image metadata is not uniquely admitted')
    return row


def binding_port(row):
    ports = row['NetworkSettings']['Ports']
    bindings = ports.get('6379/tcp')
    require(isinstance(bindings, list) and len(bindings) == 1
            and bindings[0]['HostIp'] == '127.0.0.1'
            and re.fullmatch(r'[0-9]{1,5}', bindings[0]['HostPort'])
            and 1024 < int(bindings[0]['HostPort']) <= 65535
            and int(bindings[0]['HostPort']) != 6379
            and all(value is None for key, value in ports.items() if key != '6379/tcp'),
            'Owned Redis must have one non-default loopback endpoint')
    return bindings[0]['HostPort']


class Fixture:
    def __init__(self, checkout, context):
        self.checkout = Path(checkout)
        require(self.checkout.resolve(strict=True) == self.checkout
                and (self.checkout / 'work').resolve(strict=True) == self.checkout / 'work'
                and os.getuid() == 1000 and context['identity']['executionLocation'] == 'ECS'
                and re.fullmatch(r'i-[a-z0-9]+', context['identity']['instanceId'])
                and re.fullmatch(r'[a-f0-9]{32}', context['identity']['machineId'])
                and re.fullmatch(r'[a-f0-9]{40}', context['commit'])
                and re.fullmatch(r'[a-f0-9]{64}', context['sourceSha256'])
                and re.fullmatch(r'ci-[1-9][0-9]*-[a-f0-9]{12}', context['release'])
                and context['release'].endswith(context['commit'][:12]),
                'Redis fixture requires the admitted fixed ECS checkout owner')
        self.context = context
        self.folder = self.checkout / 'work/redis-fixture'
        self.folder.mkdir(mode=0o700)
        self.token = secrets.token_hex(16)
        self.name = 'doorhandle-redis-test-' + self.token
        self.container = self.image = self.port = self.run_id = self.version = None
        self.started = self.ready = self.cleaned = self.custody_saved = False
        self.terminal_checked = self.protocol_healthy = False
        self.terminal_error = None
        self.environment = {}
        self.originals = []
        self.owner = {**context, 'token': self.token, 'name': self.name, 'sourceData': 'SYNTHETIC_ONLY'}
        private_write(self.folder / 'owner.json', json.dumps(self.owner, sort_keys=True).encode())

    def _evidence(self, name, raw):
        require(re.fullmatch(r'[a-z0-9.-]+', name) and len(raw) <= 2 * MIB,
                'Owned Redis evidence bound exceeded')
        path = self.folder / name
        if path.exists() or path.is_symlink():
            info = path.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_uid == 1000 and info.st_nlink == 1
                    and stat.S_IMODE(info.st_mode) == 0o600, 'Retained Redis evidence changed ownership')
            if path.read_bytes() != raw:
                path = self.folder / (name + '.' + secrets.token_hex(4))
        if not path.exists():
            private_write(path, raw)
        relative = path.relative_to(self.checkout).as_posix()
        if relative not in self.originals:
            self.originals.append(relative)

    def docker(self, *args):
        try:
            result = subprocess.run(['docker', *args], capture_output=True, timeout=30,
                env={key: val for key, val in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
        except subprocess.TimeoutExpired as error:
            self._evidence('docker-timeout.stdout.log', error.stdout or b'')
            self._evidence('docker-timeout.stderr.log', error.stderr or b'')
            raise ValueError('Owned Redis Docker operation timed out; originals retained') from None
        require(len(result.stdout) + len(result.stderr) <= 2 * MIB, 'Owned Redis Docker output exceeded its bound')
        if result.returncode:
            self._evidence('docker-failure.stdout.log', result.stdout)
            self._evidence('docker-failure.stderr.log', result.stderr)
            raise ValueError('Owned Redis Docker operation failed; originals retained')
        return result.stdout

    def _capacity(self):
        spec = importlib.util.spec_from_file_location('redis_fixture_resources',
            self.checkout / 'script/docker/compact-build-resources.py')
        resources = importlib.util.module_from_spec(spec); spec.loader.exec_module(resources)
        return resources.probe(self.folder)

    def _command(self):
        return ['--bind', '0.0.0.0', '--port', '6379', '--protected-mode', 'no',
            '--daemonize', 'no', '--logfile', '', '--dir', '/data', '--save', '', '--appendonly', 'no',
            '--maxmemory', str(MAXMEMORY), '--maxmemory-policy', 'noeviction',
            '--databases', '1', '--maxclients', '64']

    def _tmpfs(self):
        return {'/data': 'rw,nosuid,nodev,noexec,uid=1000,gid=1000,mode=0700,size=8m'}

    def owned(self):
        rows = json.loads(self.docker('inspect', self.container or self.name))
        require(isinstance(rows, list) and len(rows) == 1, 'One owned Redis container is required')
        row = rows[0]; config = row['Config']; host = row['HostConfig']; labels = config.get('Labels') or {}
        require(re.fullmatch(r'[a-f0-9]{64}', row['Id']) and row['Name'] == '/' + self.name
                and row['Image'] == self.image and (self.container is None or row['Id'] == self.container)
                and labels.get(LABEL) == self.token
                and labels.get('io.doorhandle.release') == self.context['release']
                and labels.get('io.doorhandle.commit') == self.context['commit']
                and labels.get('io.doorhandle.source') == self.context['sourceSha256']
                and config['User'] == '1000:1000' and config['Entrypoint'] == [ENTRYPOINT]
                and config['Cmd'] == self._command() and config['WorkingDir'] == '/data'
                and host['NetworkMode'] == 'bridge' and host['RestartPolicy']['Name'] == 'no'
                and not host['Privileged'] and host['ReadonlyRootfs'] is True
                and host['Memory'] == MEMORY and host['MemorySwap'] == MEMORY
                and host['NanoCpus'] == 500000000 and host['PidsLimit'] == 64
                and set(host.get('CapDrop') or []) == {'ALL'} and not host.get('CapAdd')
                and not host.get('Devices') and not host.get('Binds')
                and 'no-new-privileges:true' in (host.get('SecurityOpt') or [])
                and host.get('Tmpfs') == self._tmpfs()
                and host.get('LogConfig') == {'Type': 'json-file', 'Config': {'max-size': '1m', 'max-file': '1'}}
                and host.get('PortBindings') in ({'6379/tcp': [{'HostIp': '127.0.0.1', 'HostPort': ''}]},
                                               {'6379/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '0'}]}),
                'Redis fixture ownership or isolation changed')
        destinations = set()
        for mount in row['Mounts']:
            require(mount['Type'] == 'tmpfs' and mount['Destination'] in self._tmpfs()
                    and mount['Destination'] not in destinations, 'Redis acquired a persistent or unknown mount')
            destinations.add(mount['Destination'])
        # Legacy --tmpfs is authoritative in HostConfig; Moby may omit it from Mounts.
        if row['State']['Running']:
            port = binding_port(row)
            require(self.port is None or port == self.port, 'Owned Redis endpoint changed')
        return row

    def query(self, full=False):
        """Read only the already-owned server, using its bundled Redis client.

        INFO has a CLI raw-output override, so request plain text explicitly.
        CONFIG GET uses -2 --json for a stable alternating string array:
        https://redis.io/docs/latest/develop/tools/cli/ .
        Frequent checks need one INFO call, not three Docker executions.
        """
        require(self.container is not None and re.fullmatch(r'[a-f0-9]{64}', self.container),
                'Redis client requires the inspected owned container')
        command = ('exec', self.container, 'redis-cli', '-h', '127.0.0.1', '-p', '6379', '-n', '0', '-2')
        raw = self.docker(*command, '--raw', 'INFO', 'server')
        require(len(raw) <= 65536, 'Owned Redis server response exceeds its bound')
        server = raw.decode('utf8')
        require(server.startswith('# Server\r\n') or server.startswith('# Server\n'),
                'Owned Redis server response differs')
        info = dict(line.split(':', 1) for line in server.splitlines() if line and not line.startswith('#') and ':' in line)
        identity = {'runId': info.get('run_id'), 'version': info.get('redis_version'),
                    'mode': info.get('redis_mode'), 'port': info.get('tcp_port')}
        if full:
            values = json.loads(self.docker(*command, '--json', 'CONFIG', 'GET', *SETTINGS))
            require(isinstance(values, list) and len(values) == len(SETTINGS) * 2
                    and all(isinstance(x, str) for x in values)
                    and set(values[::2]) == set(SETTINGS), 'Owned Redis config response differs')
            identity['settings'] = dict(zip(values[::2], values[1::2]))
        return identity

    def _identity(self, value, full=False):
        require(re.fullmatch(r'[a-f0-9]{40}', value.get('runId') or '')
                and (self.run_id is None or value['runId'] == self.run_id)
                and self.version is not None and value.get('version') == self.version
                and value.get('mode') == 'standalone' and value.get('port') == '6379'
                and (not full or value.get('settings') == SETTINGS),
                'Owned Redis process, persistence or memory settings changed')

    def prepare(self):
        require(not self.started and not self.cleaned, 'Redis fixture cannot be prepared twice')
        capacity = self._capacity()
        require(capacity['memoryAvailableBytes'] >= GIB + MEMORY
                and capacity['diskAvailableBytes'] >= 2 * GIB + 256 * MIB + 2 * MIB,
                'Redis fixture lacks its memory or disk reserve')
        ids = self.docker('ps', '-a', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + PROJECT,
            '--filter', 'label=com.docker.compose.service=redis', '--format', '{{.ID}}').decode().splitlines()
        require(len(ids) == 1 and re.fullmatch(r'[a-f0-9]{64}', ids[0]),
                'Exactly one formal Redis image owner is required')
        formal = formal_projection(json.loads(self.docker('inspect', '--format', FORMAL_PROJECTION, ids[0])))
        require(formal['Id'] == ids[0], 'Formal Redis image source changed')
        self.image = formal['Image']
        image = json.loads(self.docker('image', 'inspect', '--format', IMAGE_PROJECTION, self.image))
        require(isinstance(image, dict) and set(image) == {'Id', 'RedisVersion'}
                and image['Id'] == self.image and isinstance(image['RedisVersion'], list)
                and len(image['RedisVersion']) == 1 and isinstance(image['RedisVersion'][0], str)
                and re.fullmatch(r'REDIS_VERSION=[0-9]+\.[0-9]+\.[0-9]+', image['RedisVersion'][0]),
                'Selected immutable Redis image has no exact public version')
        self.version = image['RedisVersion'][0].split('=', 1)[1]
        self._evidence('image-source.json', json.dumps({'formal': formal, 'image': image}, sort_keys=True).encode())
        args = ['create', '--pull', 'never', '--name', self.name, '--restart', 'no', '--user', '1000:1000',
            '--network', 'bridge', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '--memory', '256m', '--memory-swap', '256m', '--cpus', '0.5', '--pids-limit', '64',
            '--log-driver', 'json-file', '--log-opt', 'max-size=1m', '--log-opt', 'max-file=1',
            '--label', LABEL + '=' + self.token, '--label', 'io.doorhandle.release=' + self.context['release'],
            '--label', 'io.doorhandle.commit=' + self.context['commit'],
            '--label', 'io.doorhandle.source=' + self.context['sourceSha256'],
            '--publish', '127.0.0.1::6379', '--entrypoint', ENTRYPOINT, '--workdir', '/data',
            '--tmpfs', '/data:' + self._tmpfs()['/data'], self.image, *self._command()]
        self.started = True  # Durable owner precedes create, including an unknown transport result.
        self.docker(*args)
        row = self.owned(); self.container = row['Id']
        self.docker('start', self.container)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            row = self.owned()
            require(row['State']['Running'] and not row['State'].get('Restarting') and not row['State'].get('OOMKilled'),
                    'Owned Redis stopped during startup')
            self.port = binding_port(row)
            try:
                identity = self.query(full=True)
            except ValueError:
                time.sleep(.2); continue
            self._identity(identity, full=True); self.run_id = identity['runId']; self.ready = True
            self._evidence('ready-server.json', json.dumps(identity, sort_keys=True).encode())
            break
        require(self.ready, 'Owned Redis did not become ready')
        self.environment = {'DOORHANDLE_CACHE_REDIS_TEST_HOST': '127.0.0.1',
            'DOORHANDLE_CACHE_REDIS_TEST_PORT': self.port, 'DOORHANDLE_CACHE_REDIS_TEST_DATABASE': '0',
            'DOORHANDLE_REQUIRE_REDIS_TESTS': 'true'}
        self.check()
        return self.environment

    def check(self):
        row = self.owned()
        require(self.ready and row['State']['Running'] and not row['State'].get('Restarting')
                and not row['State'].get('OOMKilled'), 'Owned Redis is not healthy')
        self._identity(self.query())
        fs = os.statvfs(self.folder)
        require(fs.f_bavail * fs.f_frsize >= 2 * GIB + 256 * MIB, 'Redis fixture disk reserve exhausted')

    def _logs(self):
        result = subprocess.run(['docker', 'logs', '--timestamps', self.container], capture_output=True, timeout=30,
            env={key: val for key, val in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
        require(result.returncode == 0 and len(result.stdout) + len(result.stderr) <= 2 * MIB,
                'Owned Redis logs could not be preserved; retain its container')
        self._evidence('container.stdout.log', result.stdout)
        self._evidence('container.stderr.log', result.stderr)

    def stop(self):
        if self.cleaned:
            return self._receipt()
        owner = self.folder / 'owner.json'; info = owner.lstat()
        require(self.folder.resolve(strict=True) == self.folder and stat.S_ISREG(info.st_mode)
                and info.st_uid == 1000 and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600
                and json.loads(owner.read_text(encoding='utf8')) == self.owner,
                'Redis durable ownership changed; retain resources')
        if self.started:
            names = self.docker('ps', '-a', '--format', '{{.Names}}').decode().splitlines()
            if self.name in names:
                row = self.owned(); self.container = row['Id']
                self._evidence('before-stop-container.json', json.dumps(row, sort_keys=True).encode())
                if not self.terminal_checked:
                    try:
                        require(self.ready and row['State']['Running'] and not row['State'].get('Restarting')
                                and not row['State'].get('OOMKilled'), 'Owned Redis terminal state is not healthy')
                        final = self.query(full=True)
                        self._evidence('before-stop-server.json', json.dumps(final, sort_keys=True).encode())
                        self._identity(final, full=True)
                        self.protocol_healthy = True
                    except ValueError as error:
                        # Cleanup success is separate from acceptance. The verifier
                        # must reject protocolHealthy=false, even after safe removal.
                        self.protocol_healthy = False
                        self.terminal_error = type(error).__name__
                        self._evidence('before-stop-server-error.json',
                            json.dumps({'errorType': self.terminal_error}).encode())
                    self.terminal_checked = True
                if row['State']['Running']:
                    self.docker('stop', '--time', '15', self.container)
                row = self.owned()
                require(not row['State']['Running'] and not row['State'].get('Restarting') and row['State']['Pid'] == 0,
                        'Owned Redis has not stopped')
                if row['State'].get('OOMKilled'):
                    self.protocol_healthy = False
                    self.terminal_error = 'ValueError'
                self._evidence('stopped-container.json', json.dumps(row, sort_keys=True).encode())
                self._logs()
                self.custody_saved = True
                self.docker('rm', self.container)
                require(self.name not in self.docker('ps', '-a', '--format', '{{.Names}}').decode().splitlines(),
                        'Owned Redis container remains')
            else:
                require(self.custody_saved or self.container is None,
                        'Owned Redis disappeared without terminal originals')
        self.cleaned = True
        return self._receipt()

    def _receipt(self):
        return {'version': 1, 'kind': 'doorhandle-redis-fixture', **self.context,
            'status': 'STOPPED', 'cleanupConfirmed': self.cleaned, 'containerId': self.container,
            'protocolHealthy': self.protocol_healthy, 'terminalValidationErrorType': self.terminal_error,
            'imageId': self.image, 'redisVersion': self.version, 'ready': self.ready, 'runId': self.run_id, 'port': self.port,
            'database': 0, 'sourceData': 'SYNTHETIC_ONLY', 'persistentVolumes': False,
            'memoryLimitBytes': MEMORY, 'redisMaxmemoryBytes': MAXMEMORY,
            'privateOriginals': self.originals, 'providerCalls': 0, 'productionPromotionAllowed': False}
