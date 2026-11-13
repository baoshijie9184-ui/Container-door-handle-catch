"""Fresh, UID-owned MySQL for the semantic source-fence suite on ECS.

Reuse the formal service's immutable engine image, never its environment,
credentials, network or data. The Java fixture installs the actual 29-table
schema into this empty synthetic database. Lifecycle belongs to verify-remote.
Official entrypoint (_FILE credentials and non-root initialization):
https://github.com/docker-library/mysql/blob/master/8.4/docker-entrypoint.sh
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import subprocess
import time

MIB = 1024 ** 2
GIB = 1024 ** 3
LABEL = 'io.doorhandle.semantic-mysql-fixture'
PROJECT = 'doorhandlecatch-monolith'
PRIVATE = '/run/doorhandle-semantic-private'
SOCKET = '/var/lib/mysql/mysql.sock'
ENVIRONMENT = frozenset({'DOORHANDLE_TEST_SEMANTIC_MYSQL_CONFIG',
                         'DOORHANDLE_REQUIRE_SEMANTIC_MYSQL_TESTS'})
FORMAL_PROJECTION = ('{"Id":{{json .Id}},"Image":{{json .Image}},'
    '"Project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"Service":{{json (index .Config.Labels "com.docker.compose.service")}}}')
IDENTITY_SQL = ("SELECT JSON_OBJECT('version',@@version,'versionComment',@@version_comment,"
    "'serverUuid',@@server_uuid,'port',@@port,'dataDirectory',@@datadir,"
    "'database',DATABASE(),'account',CURRENT_USER(),'skipNetworking',@@skip_networking,"
    "'logBin',@@GLOBAL.log_bin,'foreignKeys',@@foreign_key_checks,"
    "'bufferPoolBytes',@@GLOBAL.innodb_buffer_pool_size,'maxConnections',@@GLOBAL.max_connections,"
    "'tableCount',(SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()),"
    "'schemas',(SELECT JSON_ARRAYAGG(schema_name) FROM information_schema.schemata WHERE schema_name "
    "NOT IN ('mysql','sys','information_schema','performance_schema')));")


def require(value, message):
    if not value:
        raise ValueError(message)


def private_write(path, value):
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600),
                   'w', encoding='utf8') as stream:
        stream.write(value); stream.flush(); os.fsync(stream.fileno())


def formal_projection(row):
    require(isinstance(row, dict) and set(row) == {'Id', 'Image', 'Project', 'Service'}
            and re.fullmatch(r'[a-f0-9]{64}', row.get('Id', ''))
            and re.fullmatch(r'sha256:[a-f0-9]{64}', row.get('Image', ''))
            and row['Project'] == PROJECT and row['Service'] == 'mysql',
            'Formal MySQL immutable image metadata is not uniquely admitted')
    return row


class Fixture:
    def __init__(self, checkout, context):
        self.checkout = Path(checkout)
        require(self.checkout.resolve(strict=True) == self.checkout
                and (self.checkout / 'work').resolve(strict=True) == self.checkout / 'work'
                and os.getuid() == 1000
                and context['identity']['executionLocation'] == 'ECS'
                and re.fullmatch(r'i-[a-z0-9]+', context['identity']['instanceId'])
                and re.fullmatch(r'[a-f0-9]{32}', context['identity']['machineId'])
                and re.fullmatch(r'[a-f0-9]{40}', context['commit'])
                and re.fullmatch(r'[a-f0-9]{64}', context['sourceSha256'])
                and re.fullmatch(r'ci-[0-9]+-[a-f0-9]{12}', context['release']),
                'Semantic MySQL requires the admitted ECS checkout owner')
        self.context = context
        self.folder = self.checkout / 'work/semantic-mysql-fixture'
        self.folder.mkdir(mode=0o700)
        self.data = self.folder / 'data'
        self.private = self.folder / 'private'
        self.config = self.folder / 'feature-mysql.json'
        self.token = secrets.token_hex(16)
        self.name = 'doorhandle-semantic-mysql-' + self.token
        self.database = 'doorhandle_feature_' + self.token[:12]
        self.username = 'ecsit_' + self.token[:12]
        self.image = self.container = self.server_uuid = self.port = None
        self.entrypoint = None
        self.ready = self.started = self.cleaned = False
        self.custody_saved = False
        self.environment = {}
        self.originals = []
        self.deleted_files = self.deleted_bytes = 0
        self.owner = {**context, 'token': self.token, 'name': self.name,
                      'database': self.database, 'sourceData': 'SYNTHETIC_ONLY'}
        private_write(self.folder / 'owner.json', json.dumps(self.owner))

    def _evidence(self, name, raw):
        """Keep original startup/failure bytes; retries never overwrite originals."""
        require(re.fullmatch(r'[a-z0-9.-]+', name) and len(raw) <= 6 * MIB,
                'Owned MySQL evidence bound exceeded')
        target = self.folder / name
        if target.exists():
            info = target.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600,
                    'Retained MySQL evidence changed ownership')
            if target.read_bytes() != raw:
                target = self.folder / (name + '.' + secrets.token_hex(4))
        if not target.exists():
            with os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        relative = str(target.relative_to(self.checkout))
        if relative not in self.originals:
            self.originals.append(relative)

    def docker(self, *args):
        try:
            result = subprocess.run(['docker', *args], capture_output=True, timeout=30,
                env={key: val for key, val in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
        except subprocess.TimeoutExpired as error:
            for name, raw in (('docker-timeout.stdout.log', error.stdout or b''),
                              ('docker-timeout.stderr.log', error.stderr or b'')):
                self._evidence(name, raw)
            raise ValueError('Owned MySQL Docker operation timed out; private originals retained') from None
        require(len(result.stdout) + len(result.stderr) <= 6 * MIB,
                'Owned MySQL Docker output exceeded its bound')
        if result.returncode:
            self._evidence('docker-failure.stdout.log', result.stdout)
            self._evidence('docker-failure.stderr.log', result.stderr)
            raise ValueError('Owned MySQL Docker operation failed; private originals retained')
        return result.stdout

    def _capacity(self):
        spec = importlib.util.spec_from_file_location('semantic_mysql_resources',
            self.checkout / 'script/docker/compact-build-resources.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module.probe(self.folder)

    def _command(self):
        # Ignore image option files: they may name root-owned log/PID paths.
        # All required non-root storage and memory options are explicit here.
        return ['mysqld', '--no-defaults', '--datadir=' + str(self.data), '--port=' + str(self.port),
            '--bind-address=0.0.0.0', '--socket=' + SOCKET,
            '--pid-file=/var/lib/mysql/mysql.pid', '--secure-file-priv=/var/lib/mysql-files',
            '--mysqlx=OFF', '--event-scheduler=OFF', '--local-infile=OFF', '--skip-log-bin',
            '--skip-name-resolve', '--innodb-buffer-pool-size=134217728',
            '--innodb-redo-log-capacity=67108864', '--max-connections=40',
            '--table-open-cache-instances=1', '--default-time-zone=+08:00']

    def _tmpfs(self):
        return {'/var/lib/mysql': 'rw,nosuid,nodev,noexec,uid=1000,gid=1000,mode=0700,size=16m',
            '/var/lib/mysql-files': 'rw,nosuid,nodev,noexec,uid=1000,gid=1000,mode=0700,size=16m',
            '/tmp': 'rw,nosuid,nodev,uid=1000,gid=1000,mode=1777,size=64m'}

    def _env(self):
        return {'MYSQL_ROOT_PASSWORD_FILE': PRIVATE + '/root-password',
            'MYSQL_PASSWORD_FILE': PRIVATE + '/test-password', 'MYSQL_USER': self.username,
            'MYSQL_DATABASE': self.database, 'MYSQL_ROOT_HOST': 'localhost',
            'MYSQL_INITDB_SKIP_TZINFO': '1', 'TZ': 'Asia/Shanghai'}

    def owned(self):
        row = json.loads(self.docker('inspect', self.container or self.name))[0]
        config, host = row['Config'], row['HostConfig']
        labels = config.get('Labels') or {}
        require(re.fullmatch(r'[a-f0-9]{64}', row['Id']) and row['Name'] == '/' + self.name
                and row['Image'] == self.image and (self.container is None or row['Id'] == self.container)
                and labels.get(LABEL) == self.token
                and labels.get('io.doorhandle.release') == self.context['release']
                and labels.get('io.doorhandle.source') == self.context['sourceSha256']
                and config['User'] == '1000:1000' and config['Entrypoint'] == self.entrypoint
                and config['Cmd'] == self._command() and host['NetworkMode'] == 'bridge'
                and host['RestartPolicy']['Name'] == 'no' and not host['Privileged']
                and host['ReadonlyRootfs'] is True and host['Memory'] == GIB
                and host['MemorySwap'] == GIB and host['NanoCpus'] == 10 ** 9
                and host['PidsLimit'] == 128 and set(host.get('CapDrop') or []) == {'ALL'}
                and not host.get('CapAdd') and not host.get('Devices')
                and 'no-new-privileges:true' in (host.get('SecurityOpt') or [])
                and host.get('Tmpfs') == self._tmpfs()
                and host.get('LogConfig') == {'Type': 'json-file', 'Config': {'max-size': '5m', 'max-file': '1'}},
                'Semantic MySQL container ownership or isolation changed')
        env = dict(item.split('=', 1) for item in config.get('Env', []) if '=' in item)
        require(all(env.get(key) == value for key, value in self._env().items())
                and not any(key in env for key in ('MYSQL_ROOT_PASSWORD', 'MYSQL_PASSWORD',
                    'MYSQL_RANDOM_ROOT_PASSWORD', 'MYSQL_ALLOW_EMPTY_PASSWORD')),
                'Owned MySQL credentials must remain file-only')
        expected_port = {str(self.port) + '/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(self.port)}]}
        require(host.get('PortBindings') == expected_port,
                'Owned MySQL must use the same non-default loopback host and server port')
        if row['State']['Running']:
            ports = row['NetworkSettings']['Ports']
            require(ports.get(str(self.port) + '/tcp') == expected_port[str(self.port) + '/tcp']
                    and all(value is None for key, value in ports.items() if key != str(self.port) + '/tcp'),
                    'Owned MySQL acquired an unexpected public endpoint')
        expected = {(str(self.data), str(self.data)): True, (str(self.private), PRIVATE): False}
        tmpfs = set(self._tmpfs())
        for mount in row['Mounts']:
            if mount['Type'] == 'tmpfs':
                require(mount['Destination'] in tmpfs, 'Unknown MySQL temporary mount')
                tmpfs.remove(mount['Destination']); continue
            pair = (mount.get('Source'), mount['Destination'])
            require(mount['Type'] == 'bind' and pair in expected and mount['RW'] is expected.pop(pair),
                    'Owned MySQL bind or anonymous volume changed')
        # Legacy --tmpfs is represented by HostConfig.Tmpfs (verified exactly
        # above), not necessarily inspect.Mounts. --mount type=tmpfs engines
        # additionally report entries there; validate any such entry without
        # inventing a requirement that Docker itself does not guarantee.
        require(not expected, 'Owned MySQL bind is missing')
        return row

    def query(self, test_user=False):
        client = PRIVATE + ('/test-client.cnf' if test_user else '/root-client.cnf')
        raw = self.docker('exec', self.container, 'mysql', '--defaults-extra-file=' + client,
            '--connect-timeout=3', '--batch', '--raw', '--skip-column-names', '--execute', IDENTITY_SQL)
        return json.loads(raw.decode('utf8').strip())

    def _identity(self, row, test_user=False, empty=False):
        require(isinstance(row, dict) and re.fullmatch(r'8\.4\.[0-9]+(?:[-.][A-Za-z0-9.-]+)?', row.get('version', ''))
                and 'MySQL' in row.get('versionComment', '')
                and re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', row.get('serverUuid', ''))
                and (self.server_uuid is None or row['serverUuid'] == self.server_uuid)
                and row['port'] == self.port and row['dataDirectory'].rstrip('/') == str(self.data)
                and row['database'] == self.database
                and row['account'].split('@')[0] == (self.username if test_user else 'root')
                and row['skipNetworking'] == 0 and row['logBin'] == 0 and row['foreignKeys'] == 1
                and row['bufferPoolBytes'] == 128 * MIB and row['maxConnections'] == 40
                and isinstance(row['tableCount'], int) and row['tableCount'] >= 0
                and (not empty or row['tableCount'] == 0)
                and row['schemas'] == [self.database],
                'Owned MySQL effective version, identity, storage or bounds changed')

    def prepare(self):
        capacity = self._capacity()
        require(capacity['memoryAvailableBytes'] >= 4 * GIB
                and capacity['diskAvailableBytes'] >= 2 * GIB + 768 * MIB,
                'Semantic MySQL and the serial Java suite lack their resource reserve')
        ids = self.docker('ps', '-a', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + PROJECT,
            '--filter', 'label=com.docker.compose.service=mysql', '--format', '{{.ID}}').decode().splitlines()
        require(len(ids) == 1 and re.fullmatch(r'[a-f0-9]{64}', ids[0]),
                'Exactly one existing formal MySQL image owner is required')
        formal = formal_projection(json.loads(self.docker('inspect', '--format', FORMAL_PROJECTION, ids[0])))
        require(formal['Id'] == ids[0], 'Formal MySQL image source changed')
        self.image = formal['Image']
        image = json.loads(self.docker('image', 'inspect', '--format',
            '{"Id":{{json .Id}},"Entrypoint":{{json .Config.Entrypoint}}}', self.image))
        require(image['Id'] == self.image and image['Entrypoint'] in
                (['docker-entrypoint.sh'], ['/usr/local/bin/docker-entrypoint.sh']),
                'Existing MySQL image has no admitted official entrypoint')
        self.entrypoint = image['Entrypoint']
        self._evidence('image-source.json', json.dumps({'formal': formal, 'image': image}, sort_keys=True).encode())
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0)); self.port = available.getsockname()[1]
        require(1024 < self.port <= 65535 and self.port != 3306, 'Non-default loopback port required')
        self.data.mkdir(mode=0o700); self.private.mkdir(mode=0o700)
        root_password, password = secrets.token_hex(32), secrets.token_hex(32)
        private_write(self.private / 'root-password', root_password)
        private_write(self.private / 'test-password', password)
        private_write(self.private / 'root-client.cnf', '[client]\nuser=root\npassword=' + root_password
            + '\nprotocol=SOCKET\nsocket=' + SOCKET + '\ndatabase=' + self.database + '\n')
        private_write(self.private / 'test-client.cnf', '[client]\nuser=' + self.username + '\npassword=' + password
            + '\nprotocol=TCP\nhost=127.0.0.1\nport=' + str(self.port) + '\ndatabase=' + self.database + '\n')
        args = ['create', '--pull', 'never', '--name', self.name, '--restart', 'no', '--user', '1000:1000',
            '--network', 'bridge', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '--memory', '1g', '--memory-swap', '1g', '--cpus', '1', '--pids-limit', '128',
            '--log-driver', 'json-file', '--log-opt', 'max-size=5m', '--log-opt', 'max-file=1',
            '--label', LABEL + '=' + self.token, '--label', 'io.doorhandle.release=' + self.context['release'],
            '--label', 'io.doorhandle.source=' + self.context['sourceSha256'],
            '--publish', '127.0.0.1:' + str(self.port) + ':' + str(self.port),
            '--mount', 'type=bind,src=' + str(self.data) + ',dst=' + str(self.data),
            '--mount', 'type=bind,src=' + str(self.private) + ',dst=' + PRIVATE + ',readonly']
        for target, options in self._tmpfs().items(): args += ['--tmpfs', target + ':' + options]
        for key, value in self._env().items(): args += ['--env', key + '=' + value]
        args += [self.image, *self._command()]
        self.started = True
        self.docker(*args)
        row = self.owned(); self.container = row['Id']
        self.docker('start', self.container)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            row = self.owned()
            require(row['State']['Running'] and not row['State'].get('OOMKilled'),
                    'Owned MySQL stopped during initialization')
            try:
                identity = self.query()
            except (ValueError, OSError):
                time.sleep(1); continue
            # The entrypoint's temporary socket server must not count as ready.
            if identity.get('skipNetworking') == 1:
                time.sleep(1); continue
            self._identity(identity, empty=True)
            self.server_uuid = identity['serverUuid']
            self._identity(self.query(test_user=True), test_user=True, empty=True)
            self.ready = True
            self._evidence('ready-server.json', json.dumps(identity, sort_keys=True).encode())
            break
        require(self.ready, 'Owned MySQL did not become ready; preserve its startup originals')
        private_write(self.config, json.dumps({'scope': 'ecs-disposable-mysql',
            'machineId': self.context['identity']['machineId'], 'instanceId': self.context['identity']['instanceId'],
            'database': self.database, 'username': self.username, 'password': password, 'port': self.port,
            'serverUuid': self.server_uuid, 'dataDirectory': str(self.data),
            'url': 'jdbc:mysql://127.0.0.1:' + str(self.port) + '/' + self.database
                   + '?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai'}))
        self.environment = {'DOORHANDLE_TEST_SEMANTIC_MYSQL_CONFIG': str(self.config),
                           'DOORHANDLE_REQUIRE_SEMANTIC_MYSQL_TESTS': 'true'}
        self.check()
        return self.config

    def check(self):
        row = self.owned()
        require(self.ready and row['State']['Running'] and not row['State'].get('OOMKilled'),
                'Semantic MySQL is not healthy')
        self._identity(self.query())
        fs = os.statvfs(self.folder)
        require(fs.f_bavail * fs.f_frsize >= 2 * GIB + 256 * MIB,
                'Semantic MySQL disk reserve exhausted')

    def _unreferenced(self):
        ids = self.docker('ps', '-a', '--no-trunc', '--format', '{{.ID}}').decode().splitlines()
        for cid in ids:
            require(re.fullmatch(r'[a-f0-9]{64}', cid), 'Container inventory identity changed')
            # Never read other containers' environment or credentials.
            mounts = json.loads(self.docker('inspect', '--format', '{{json .Mounts}}', cid))
            for mount in mounts:
                if mount.get('Type') != 'bind': continue
                path = Path(mount['Source'])
                require(path != self.folder and self.folder not in path.parents
                        and path not in self.folder.parents,
                        'Synthetic MySQL files remain referenced by another container')

    def _safe_disposable(self, path, directory):
        require(path.parent == self.folder and self.folder.resolve(strict=True) == self.folder
                and path.resolve(strict=True) == path, 'Synthetic MySQL cleanup target changed')
        root = path.lstat(); device = root.st_dev
        require(root.st_uid == 1000 and (stat.S_ISDIR(root.st_mode) if directory else stat.S_ISREG(root.st_mode))
                and device == self.folder.stat().st_dev
                and (directory or root.st_nlink == 1), 'Synthetic MySQL cleanup owner changed')
        paths = [path]
        if directory:
            for current, folders, files in os.walk(path, followlinks=False):
                paths += [Path(current) / name for name in folders + files]
        for item in paths:
            info = item.lstat()
            require(info.st_uid == 1000 and info.st_dev == device and not item.is_symlink()
                    and (stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)),
                    'Synthetic MySQL tree contains an unknown owner, link or special file')
        return [(item, item.lstat()) for item in paths]

    def _logs(self, cid, prefix):
        logs = subprocess.run(['docker', 'logs', '--timestamps', cid], capture_output=True, timeout=30,
            env={key: val for key, val in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
        require(logs.returncode == 0 and len(logs.stdout) + len(logs.stderr) <= 6 * MIB,
                'Owned MySQL logs could not be preserved; retain its container')
        self._evidence(prefix + '.stdout.log', logs.stdout)
        self._evidence(prefix + '.stderr.log', logs.stderr)

    def stop(self):
        if self.cleaned:
            return self._receipt()
        owner = self.folder / 'owner.json'
        info = owner.lstat()
        require(self.folder.resolve(strict=True) == self.folder and stat.S_ISREG(info.st_mode)
                and info.st_uid == 1000 and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600
                and json.loads(owner.read_text(encoding='utf8')) == self.owner,
                'Semantic MySQL durable ownership changed; retain resources')
        if self.started:
            names = self.docker('ps', '-a', '--format', '{{.Names}}').decode().splitlines()
            if self.name in names:
                row = self.owned()
                self._evidence('before-stop-container.json', json.dumps(row, sort_keys=True).encode())
                self._logs(row['Id'], 'before-stop-container')
                if row['State']['Running']: self.docker('stop', '--time', '20', row['Id'])
                row = self.owned()
                require(not row['State']['Running'] and row['State']['Pid'] == 0,
                        'Owned MySQL has not stopped')
                self._evidence('stopped-container.json', json.dumps(row, sort_keys=True).encode())
                self._logs(row['Id'], 'container')
                self.custody_saved = True
                self.docker('rm', row['Id'])
                require(self.name not in self.docker('ps', '-a', '--format', '{{.Names}}').decode().splitlines(),
                        'Owned MySQL container remains')
            else:
                # A failed create can legitimately leave no object or data.
                # A previously known server disappearing without its original
                # logs/inspect is not evidence that its data is disposable.
                require(self.custody_saved or (self.container is None
                        and (not self.data.exists() or not any(self.data.iterdir()))),
                        'Owned MySQL disappeared without terminal originals; retain data')
        self._unreferenced()
        targets = [(self.data, True), (self.private, True), (self.config, False)]
        admitted = [(path, directory, self._safe_disposable(path, directory))
                    for path, directory in targets if path.exists() or path.is_symlink()]
        # Validate every target first; an unknown path retains all synthetic inputs.
        for path, directory, entries in admitted:
            self.deleted_files += sum(stat.S_ISREG(info.st_mode) for _, info in entries)
            self.deleted_bytes += sum(info.st_size for _, info in entries if stat.S_ISREG(info.st_mode))
            if directory: shutil.rmtree(path)
            else: path.unlink()
        self.cleaned = True
        return self._receipt()

    def _receipt(self):
        return {'version': 1, 'kind': 'doorhandle-semantic-mysql-fixture', **self.context,
            'status': 'STOPPED', 'cleanupConfirmed': self.cleaned, 'containerId': self.container,
            'imageId': self.image, 'ready': self.ready, 'sourceData': 'SYNTHETIC_ONLY',
            'serverUuid': self.server_uuid, 'port': self.port, 'database': self.database,
            'deletedFiles': self.deleted_files, 'deletedBytes': self.deleted_bytes,
            'privateOriginals': self.originals, 'providerCalls': 0, 'productionPromotionAllowed': False}
