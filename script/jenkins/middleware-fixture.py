"""Owned Qdrant for the existing ECS source verifier, not a production service.

All points are synthetic. Provider calls are never configured. The normal
verifier supervisor owns start, health observation and terminal cleanup.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import time
from urllib.request import ProxyHandler, build_opener

GIB = 1024 ** 3
LABEL = 'io.doorhandle.middleware-fixture'
ENVIRONMENT = frozenset({'DOORHANDLE_TEST_QDRANT_HOST', 'DOORHANDLE_TEST_QDRANT_PORT',
    'DOORHANDLE_TEST_QDRANT_GRPC_PORT', 'DOORHANDLE_TEST_QDRANT_KEY_FILE',
    'DOORHANDLE_TEST_QDRANT_TLS', 'DOORHANDLE_REQUIRE_QDRANT_TESTS'})


def require(value, message):
    if not value:
        raise ValueError(message)


def private_write(path, value):
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w', encoding='utf8') as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def preserve_private_bytes(path, raw):
    """Resume an interrupted custody step without replacing its originals."""
    if path.exists() or path.is_symlink():
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and not path.is_symlink() and info.st_uid == os.getuid()
                and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600
                and path.read_bytes() == raw, 'Retained middleware original changed')
        return
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def binding_port(row, port):
    values = row['NetworkSettings']['Ports'].get(str(port) + '/tcp')
    require(isinstance(values, list) and len(values) == 1
            and values[0]['HostIp'] == '127.0.0.1'
            and values[0]['HostPort'].isdigit() and 1024 <= int(values[0]['HostPort']) <= 65535,
            'Qdrant fixture port is not a unique loopback endpoint')
    return values[0]['HostPort']


class Fixture:
    def __init__(self, checkout, context):
        self.checkout = Path(checkout)
        require(self.checkout.resolve(strict=True) == self.checkout
                and os.getuid() == 1000 and context['identity']['executionLocation'] == 'ECS',
                'Middleware fixture requires the admitted ECS checkout owner')
        self.context = context
        self.folder = self.checkout / 'work/middleware-fixture'
        self.folder.mkdir(mode=0o700)
        self.token = secrets.token_hex(16)
        self.name = 'doorhandle-qdrant-test-' + self.token
        self.container = None
        self.image = None
        self.ready = False
        self.started = False
        self.cleaned = False
        self.environment = {}
        private_write(self.folder / 'owner.json', json.dumps({**context, 'token': self.token,
            'name': self.name, 'sourceData': 'SYNTHETIC_ONLY'}))

    def docker(self, *args):
        result = subprocess.run(['docker', *args], capture_output=True, timeout=30,
            env={key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
        require(result.returncode == 0 and len(result.stdout) <= 2 * 1024 ** 2,
                'Owned middleware Docker operation failed')
        return result.stdout

    def owned(self):
        row = json.loads(self.docker('inspect', self.container or self.name))[0]
        labels = row['Config'].get('Labels') or {}
        host = row['HostConfig']
        require(row['Name'] == '/' + self.name and row['Image'] == self.image
                and (self.container is None or row['Id'] == self.container)
                and labels.get(LABEL) == self.token
                and labels.get('io.doorhandle.release') == self.context['release']
                and labels.get('io.doorhandle.source') == self.context['sourceSha256']
                and row['Config']['User'] == '1000:1000'
                and host['RestartPolicy']['Name'] == 'no' and not host['Privileged']
                and host['ReadonlyRootfs'] is True and host['Memory'] == 512 * 1024 ** 2
                and host['MemorySwap'] == 512 * 1024 ** 2 and host['NanoCpus'] == 10 ** 9
                and host['PidsLimit'] == 128 and set(host.get('CapDrop') or []) == {'ALL'}
                and not host.get('CapAdd')
                and 'no-new-privileges:true' in (host.get('SecurityOpt') or [])
                and row['Config'].get('Entrypoint') in (None, [])
                and row['Config']['Cmd'] == ['./entrypoint.sh', '--config-path', '/run/doorhandle-vector/server.json']
                and host['NetworkMode'] == 'bridge', 'Middleware fixture ownership changed')
        bindings = host.get('PortBindings') or {}
        require(set(bindings) == {'6333/tcp', '6334/tcp'} and all(
            isinstance(value, list) and len(value) == 1 and value[0]['HostIp'] == '127.0.0.1'
            and value[0]['HostPort'] in ('', '0') for value in bindings.values()),
            'Middleware fixture requested ports changed')
        expected = {(str(self.folder / 'storage'), '/qdrant/storage'): True,
                    (str(self.folder / 'snapshots'), '/qdrant/snapshots'): True,
                    (str(self.folder / 'private'), '/run/doorhandle-vector'): False}
        for mount in row['Mounts']:
            if mount['Type'] == 'tmpfs':
                require(mount['Destination'] == '/tmp', 'Unknown fixture temporary mount')
                continue
            pair = (mount['Source'], mount['Destination'])
            require(mount['Type'] == 'bind' and pair in expected and mount['RW'] is expected.pop(pair),
                    'Middleware fixture bind changed')
        require(not expected, 'Middleware fixture bind is missing')
        return row

    def prepare(self):
        helper = self.checkout / 'script/docker/compact-build-resources.py'
        spec = importlib.util.spec_from_file_location('middleware_image_resources', helper)
        resources = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(resources)
        value = resources.prepare_qdrant_image(self.folder / 'image-preparation',
            self.context, helper.parent)
        self.image = value['engineIdentity']['engineImageId']
        capacity = resources.probe(self.folder)
        # Existing tools can nest a 2 GiB Java process inside the 4 GiB
        # Python command. Add Qdrant's 512 MiB limit and the 1 GiB host floor.
        require(capacity['memoryAvailableBytes'] >= 15 * GIB // 2
                and capacity['diskAvailableBytes'] >= 2 * GIB + 768 * 1024 ** 2,
                'Qdrant plus the existing serial ECS tools lacks its runtime resource reserve')
        for name in ('storage', 'snapshots', 'private'):
            (self.folder / name).mkdir(mode=0o700)
        key = secrets.token_hex(32)
        private_write(self.folder / 'private/api-key', key)
        private_write(self.folder / 'private/server.json', json.dumps({
            'log_level': 'WARN', 'telemetry_disabled': True,
            'storage': {'storage_path': '/qdrant/storage', 'snapshots_path': '/qdrant/snapshots'},
            'service': {'api_key': key, 'host': '0.0.0.0', 'http_port': 6333, 'grpc_port': 6334}}))
        args = ['create', '--pull', 'never', '--name', self.name, '--restart', 'no', '--user', '1000:1000',
            '--network', 'bridge', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--memory', '512m', '--memory-swap', '512m',
            '--cpus', '1', '--pids-limit', '128', '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m',
            '--log-driver', 'json-file', '--log-opt', 'max-size=5m', '--log-opt', 'max-file=1',
            '--label', LABEL + '=' + self.token, '--label', 'io.doorhandle.release=' + self.context['release'],
            '--label', 'io.doorhandle.source=' + self.context['sourceSha256'],
            '--publish', '127.0.0.1::6333', '--publish', '127.0.0.1::6334',
            '--env', 'QDRANT_INIT_FILE_PATH=/qdrant/storage/.qdrant-initialized']
        for source, destination, readonly in ((self.folder / 'storage', '/qdrant/storage', False),
                (self.folder / 'snapshots', '/qdrant/snapshots', False),
                (self.folder / 'private', '/run/doorhandle-vector', True)):
            args += ['--mount', 'type=bind,src=' + str(source) + ',dst=' + destination + (',readonly' if readonly else '')]
        args += [self.image, './entrypoint.sh', '--config-path', '/run/doorhandle-vector/server.json']
        # Owner is durable before create. If transport returns unknown, cleanup
        # resolves only this unpredictable name and validates every binding.
        self.started = True
        self.docker(*args)
        row = self.owned()
        self.container = row['Id']
        self.docker('start', self.container)
        deadline = time.monotonic() + 60
        opener = build_opener(ProxyHandler({}))
        while time.monotonic() < deadline:
            row = self.owned()
            require(row['State']['Running'] and not row['State'].get('OOMKilled'),
                    'Qdrant fixture stopped during startup')
            port = binding_port(row, 6333)
            try:
                with opener.open('http://127.0.0.1:' + port + '/readyz', timeout=2) as response:
                    if response.status == 200:
                        self.ready = True
                        break
            except OSError:
                time.sleep(.2)
        require(self.ready, 'Qdrant fixture did not become ready')
        self.environment = {'DOORHANDLE_TEST_QDRANT_HOST': '127.0.0.1',
            'DOORHANDLE_TEST_QDRANT_PORT': binding_port(row, 6333),
            'DOORHANDLE_TEST_QDRANT_GRPC_PORT': binding_port(row, 6334),
            'DOORHANDLE_TEST_QDRANT_KEY_FILE': str(self.folder / 'private/api-key'),
            'DOORHANDLE_TEST_QDRANT_TLS': 'false', 'DOORHANDLE_REQUIRE_QDRANT_TESTS': 'true'}
        self.check()
        return self.environment

    def check(self):
        row = self.owned()
        require(self.ready and row['State']['Running'] and not row['State'].get('OOMKilled'),
                'Qdrant fixture is not healthy')
        fs = os.statvfs(self.folder)
        require(fs.f_bavail * fs.f_frsize >= 2 * GIB + 256 * 1024 ** 2,
                'Middleware fixture disk reserve exhausted')

    def stop(self):
        image_folder = self.folder / 'image-preparation'
        if image_folder.exists():
            # Killing a Docker CLI does not prove its daemon import ended.
            # Preserve an unknown import, including all its input evidence.
            summary = image_folder / 'resource-summary.json'
            require(summary.is_file() and not summary.is_symlink(),
                    'Qdrant image preparation has no terminal resource evidence')
            value = json.loads(summary.read_text(encoding='utf8'))
            require(all(value.get(key) == self.context[key] for key in ('release', 'commit', 'sourceSha256', 'identity'))
                    and all(value.get('cleanup', {}).get(key) is True for key in
                            ('creatorStopped', 'builderStopped', 'daemonImportTerminated')),
                    'Qdrant image import is not confirmed terminal; retain resources')
        if self.started:
            # A failed Docker create may have created nothing. Only absence of
            # this owned name in the complete listing authorizes NO_RESOURCES.
            names = self.docker('ps', '-a', '--format', '{{.Names}}').decode().splitlines()
            if self.name in names:
                row = self.owned()
                if row['State']['Running']:
                    self.docker('stop', '--time', '15', row['Id'])
                row = self.owned()
                require(not row['State']['Running'] and row['State']['Pid'] == 0,
                        'Qdrant fixture has not stopped')
                preserve_private_bytes(self.folder / 'stopped-container.json', json.dumps(row, sort_keys=True).encode())
                logs = subprocess.run(['docker', 'logs', '--timestamps', '--tail', '500', row['Id']],
                    capture_output=True, timeout=30,
                    env={key: val for key, val in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
                require(logs.returncode == 0 and len(logs.stdout) + len(logs.stderr) <= 6 * 1024 ** 2,
                        'Qdrant startup logs could not be preserved; retain the container')
                for name, raw in (('container.stdout.log', logs.stdout), ('container.stderr.log', logs.stderr)):
                    preserve_private_bytes(self.folder / name, raw)
                self.docker('rm', row['Id'])
                require(self.name not in self.docker('ps', '-a', '--format', '{{.Names}}').decode().splitlines(),
                        'Qdrant fixture object remains')
        # No real inputs are ever mounted here. Only this attempt's two fresh
        # synthetic directories are disposable; image proof and owner remain.
        for name in ('storage', 'snapshots', 'private'):
            path = self.folder / name
            if path.exists():
                require(path.resolve(strict=True) == path and not path.is_symlink()
                        and stat.S_ISDIR(path.stat().st_mode) and path.stat().st_uid == os.getuid(),
                        'Synthetic cleanup path changed')
                shutil.rmtree(path)
        self.cleaned = True
        return {'version': 1, 'kind': 'doorhandle-middleware-fixture', **self.context,
                'status': 'STOPPED', 'containerId': self.container, 'imageId': self.image,
                'ready': self.ready, 'cleanupConfirmed': True, 'sourceData': 'SYNTHETIC_ONLY',
                'providerCalls': 0, 'productionPromotionAllowed': False}
