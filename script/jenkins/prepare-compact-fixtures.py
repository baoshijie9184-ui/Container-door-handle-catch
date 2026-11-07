#!/usr/bin/env python3
"""Provision or stop this Jenkins build's disposable compact MySQL fixtures on ECS.

This does not execute project tests, deploy applications, start ECS, write the
original database, or remove source dumps/data/evidence. Preparation is fail-stop;
an interrupted attempt is retained and cannot be reused by another build.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
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
import sys
import tarfile
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


GIB = 1024 ** 3
PROJECT = 'doorhandlecatch-monolith'
INSTANCE = 'i-2zeieuov2aum486jm1ek'
TAG = re.compile(r'ci-[1-9][0-9]*-[a-f0-9]{12}')
SHA = re.compile(r'[a-f0-9]{64}')
CID = re.compile(r'[a-f0-9]{64}')
IDENT = re.compile(r'[a-z][a-z0-9_]{0,63}')
LABEL = 'io.doorhandle.compact-fixtures'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(part)
    return value.hexdigest()


def canonical(value):
    path = Path(value)
    require(path.is_absolute() and path.resolve(strict=True) == path
            and not any(item.is_symlink() for item in (path, *path.parents)), 'Canonical existing path required')
    return path


def private_json(path):
    path = canonical(path)
    metadata = path.stat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid()
            and metadata.st_nlink == 1 and not metadata.st_mode & 0o077
            and metadata.st_size <= 16 * 1024 * 1024, 'Private bounded owned JSON required')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Repeated private JSON field')
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=pairs)


def write_json(path, value, *, replace=False):
    require(not path.is_symlink() and (replace or not path.exists()), 'Refusing to replace unknown evidence')
    temporary = path.with_name(path.name + '.' + secrets.token_hex(6) + '.tmp')
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_DIRECTORY | os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def ecs_identity(args):
    require(sys.platform == 'linux' and args.instance_id == INSTANCE
            and re.fullmatch(r'[a-f0-9]{32}', args.machine_id), 'Only the original admitted monolith ECS is allowed')
    require(Path('/etc/machine-id').read_text().strip() == args.machine_id, 'Actual ECS machine differs')
    opener = build_opener(ProxyHandler({})); base = 'http://100.100.100.200/latest/'
    with opener.open(Request(base + 'api/token', data=b'', method='PUT', headers={
            'X-aliyun-ecs-metadata-token-ttl-seconds': '60'}), timeout=3) as response:
        token = response.read(4096).decode()
    with opener.open(Request(base + 'meta-data/instance-id', headers={
            'X-aliyun-ecs-metadata-token': token}), timeout=3) as response:
        require(response.read(256).decode().strip() == args.instance_id, 'Actual ECS instance differs')
    return {'instanceId': args.instance_id, 'machineId': args.machine_id, 'executionLocation': 'ECS'}


def run(arguments, *, data=None, timeout=60, diagnostics=None):
    result = subprocess.run(arguments, input=data, capture_output=True, timeout=timeout,
                            env={name: value for name, value in os.environ.items() if name in ('PATH', 'LANG', 'LC_ALL')})
    if result.returncode and diagnostics is not None:
        with diagnostics.open('xb') as stream:
            os.chmod(diagnostics, 0o600)
            stream.write(result.stderr[-256 * 1024:])
    require(result.returncode == 0, 'Owned fixture operation failed; private evidence is retained')
    require(len(result.stdout) <= 64 * 1024 * 1024, 'Fixture metadata exceeded its limit')
    return result.stdout


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def archive_source(archive, destination, commit, source_sha):
    require(digest(archive) == source_sha, 'Git archive digest differs from Jenkins')
    seen, total, this_script = set(), 0, None
    with tarfile.open(archive, 'r:gz') as source:
        for entry in source:
            path = Path(entry.name)
            require(not path.is_absolute() and '..' not in path.parts and '\\' not in entry.name
                    and path.parts and path.parts[0] not in ('work', '.git', 'artifacts')
                    and (entry.isfile() or entry.isdir()) and entry.name not in seen,
                    'Unsafe fixed-source archive member')
            seen.add(entry.name); total += entry.size
            require(len(seen) <= 50000 and entry.size <= 32 * 1024 * 1024 and total <= 512 * 1024 * 1024,
                    'Fixed-source archive exceeds its budget')
            target = destination.joinpath(*path.parts)
            if entry.isdir():
                target.mkdir(parents=True, mode=0o700, exist_ok=True); continue
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            with source.extractfile(entry) as original, target.open('xb') as output:
                os.chmod(target, 0o700 if entry.mode & 0o100 else 0o600)
                shutil.copyfileobj(original, output, 1024 * 1024)
            if path.as_posix() == 'script/jenkins/prepare-compact-fixtures.py':
                this_script = digest(target)
        require(source.pax_headers.get('comment') == commit, 'Archive commit metadata differs')
    require(this_script == digest(Path(__file__).resolve()), 'Provisioner itself is not this fixed SCM source')


def registry(source):
    tree = ast.parse((source / 'script/jenkins/verify-ecs.py').read_text('utf8'))
    values = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id in ('FIXTURE_SCHEMAS', 'MIGRATION_PAIRS'):
                    values[target.id] = ast.literal_eval(statement.value)
    require(set(values) == {'FIXTURE_SCHEMAS', 'MIGRATION_PAIRS'}, 'Audited fixture registry is absent')
    return values


def fixture_java_executable(configured, *, root, inbox, archive, tag, commit, source_sha, identity):
    if configured != 'ecs-tool-runtime':
        return canonical(configured)
    # This check precedes importing the uploaded executor and does not rely on a
    # previous prepare command's return flag or on an uncommitted host checkout.
    require(digest(archive) == source_sha and archive.stat().st_size <= 128 * 1024 ** 2,
            'Tool Java requires this fixed uploaded source archive')
    executor_sha, seen, total, count = None, set(), 0, 0
    with tarfile.open(archive, 'r:gz') as package:
        for entry in package:
            count += 1; total += entry.size
            require(count <= 50000 and 0 <= entry.size <= 32 * 1024 ** 2 and total <= 512 * 1024 ** 2
                    and entry.name not in seen, 'Tool source archive is duplicate or exceeds its bounds')
            seen.add(entry.name)
            if entry.name == 'script/jenkins/ecs-tool-runtime.py':
                require(entry.isfile() and 0 < entry.size <= 1024 ** 2, 'Pinned tool executor source is invalid')
                executor_sha = hashlib.sha256(package.extractfile(entry).read(1024 ** 2 + 1)).hexdigest()
        require(package.pax_headers.get('comment') == commit and executor_sha is not None,
                'Pinned executor is missing or belongs to another source commit')
    uploaded = canonical(inbox / 'ecs-tool-runtime.py')
    folder = canonical(inbox / 'tool-runtime')
    require(uploaded.stat().st_uid == os.getuid() and not uploaded.stat().st_mode & 0o022
            and digest(uploaded) == executor_sha and digest(canonical(folder / 'executor.py')) == executor_sha,
            'Uploaded tool executor bytes differ from this source archive')
    runtime = module('fixed_fixture_tool_runtime', uploaded)
    value, _ = runtime.admit(folder / 'manifest.json', root=root, tag=tag, commit=commit,
        source_sha=source_sha, identity=identity, source=folder)
    require(value['directory'] == str(folder), 'Fixture Java registration escaped its fixed build inbox')
    return canonical(folder / 'java')


class Preparation:
    def __init__(self, args):
        self.args = args; self.identity = ecs_identity(args)
        require(TAG.fullmatch(args.tag) and re.fullmatch(r'[a-f0-9]{40}', args.commit)
                and args.tag.endswith('-' + args.commit[:12]) and SHA.fullmatch(args.source_sha256),
                'Fixed Jenkins commit, release and source digest required')
        self.root = canonical(args.root)
        require(re.fullmatch(r'/(?:home|srv|opt)/[A-Za-z0-9_./-]+', str(self.root)), 'Existing admitted release root required')
        self.inbox = canonical(self.root / 'inbox' / args.tag)
        self.archive = canonical(self.inbox / 'source.tar.gz')
        require(digest(self.archive) == args.source_sha256, 'Source archive checksum differs')
        self.attempt = self.root / 'verification' / args.tag
        self.checkout = self.attempt / 'checkout'
        self.journal_file = self.checkout / 'work' / 'compact-fixtures-owner.json'
        self.docker = canonical(shutil.which('docker'))
        self.journal = None

    def docker_call(self, *arguments, **kwargs):
        if self.journal is not None:
            kwargs['diagnostics'] = self.work / 'private' / ('docker-' + secrets.token_hex(6) + '.stderr')
        return run([str(self.docker), *arguments], **kwargs)

    def save(self, phase):
        self.journal['phase'] = phase
        self.journal['updatedAtUtc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        write_json(self.journal_file, self.journal, replace=True)

    def resource_gate(self, source, schema, suite_count):
        info = source.single("SELECT JSON_OBJECT('bytes',COALESCE(SUM(DATA_LENGTH+INDEX_LENGTH),0)) FROM information_schema.TABLES WHERE TABLE_SCHEMA=" + source.runtime.literal(schema) + ';')
        memory = {line.split(':', 1)[0]: int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()}
        disk = shutil.disk_usage(self.work)
        # One clean reactor build is retained; suites reuse it sequentially with
        # clean test rather than manufacturing 56 packaged application jars.
        # Reserve source extraction/Jar, Maven output/cache growth and both Node
        # dependency trees in addition to source+target+two restores/backups.
        required = max(10 * GIB, int(info['bytes']) * 8 + suite_count * 32 * 1024 ** 2 + 8 * GIB)
        reserve = max(2 * GIB, disk.total // 10)
        evidence = {'sourceAllocatedBytes': int(info['bytes']), 'availableDiskBytes': disk.free,
                    'requiredDiskBytes': required, 'diskReserveBytes': reserve,
                    'availableMemoryBytes': memory['MemAvailable'], 'mysqlMemoryLimitBytes': 1536 * 1024 ** 2,
                    'requiredMemoryBytes': 6 * GIB}
        write_json(self.work / 'resource-admission.json', evidence)
        require(disk.free >= required + reserve and memory['MemAvailable'] >= 6 * GIB,
                'ECS disk or memory is insufficient; no automatic resize or application stop is allowed')
        return evidence

    def prepare(self):
        require(not self.attempt.exists() and not self.attempt.is_symlink(), 'Use a new Jenkins build; fixture attempts cannot be reused')
        settings = private_json(self.args.settings)
        required = {'version', 'sourceMysqlContainerId', 'sourceSchema', 'sourceOffsets', 'java'}
        require(required <= set(settings) <= required | {'applicationJar', 'applicationJarSha256'}
                and settings['version'] == 1 and CID.fullmatch(settings['sourceMysqlContainerId'])
                and IDENT.fullmatch(settings['sourceSchema']), 'Unsupported explicit fixture settings')
        require(isinstance(settings['sourceOffsets'], dict) and settings['sourceOffsets'] and all(
            re.fullmatch(r'[+-](?:0[0-9]|1[0-4]):[0-5][0-9]', value) and (value[1:3] != '14' or value[4:] == '00')
            for value in settings['sourceOffsets'].values()), 'Explicit reviewed domain source offsets required')
        java = fixture_java_executable(settings['java'], root=self.root, inbox=self.inbox,
            archive=self.archive, tag=self.args.tag, commit=self.args.commit,
            source_sha=self.args.source_sha256, identity=self.identity)
        jar = canonical(self.inbox / 'application.jar')
        plan = private_json(self.inbox / 'build-artifacts.json')
        require(isinstance(plan.get('applicationJarSha256'), str) and SHA.fullmatch(plan['applicationJarSha256'])
                and type(plan.get('applicationJarBytes')) is int and 0 < plan['applicationJarBytes'] <= 512 * 1024 * 1024
                and digest(jar) == plan['applicationJarSha256'] and jar.stat().st_size == plan['applicationJarBytes']
                and settings.get('applicationJar', str(jar)) == str(jar)
                and settings.get('applicationJarSha256', plan['applicationJarSha256']) == plan['applicationJarSha256'],
                'Fixed uploaded application jar differs from its Jenkins artifact plan')
        settings['applicationJarSha256'] = plan['applicationJarSha256']
        expected = {'schema': 1, 'kind': 'doorhandle-compact-fixture-artifacts', 'release': self.args.tag,
                    'commit': self.args.commit, 'sourceSha256': self.args.source_sha256,
                    'applicationJarSha256': settings['applicationJarSha256'], 'applicationJarBytes': jar.stat().st_size}
        require(all(plan.get(key) == value for key, value in expected.items()), 'Jenkins source/jar artifact plan differs')
        version = subprocess.run([str(java), '-version'], capture_output=True,
                                 timeout=90 if settings['java'] == 'ecs-tool-runtime' else 15)
        require(version.returncode == 0 and re.search(rb'version "17(?:[.\"]|$)', version.stderr + version.stdout),
                'An existing Java 17 executable is required; no JRE is installed')
        parent = self.root / 'verification'; parent.mkdir(mode=0o700, exist_ok=True); canonical(parent)
        require(parent.stat().st_uid == os.getuid() and not parent.stat().st_mode & 0o022, 'Verification parent is not owned/private')
        self.attempt.mkdir(mode=0o700); self.checkout.mkdir(mode=0o700)
        (self.checkout / 'work').mkdir(mode=0o700)
        token = secrets.token_hex(5); self.work = self.checkout / 'work' / 'compact-fixtures'
        self.work.mkdir(mode=0o700); (self.work / 'private').mkdir(mode=0o700)
        self.journal = {'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-owner', 'release': self.args.tag,
            'commit': self.args.commit, 'sourceSha256': self.args.source_sha256, 'identity': self.identity,
            'token': token, 'work': str(self.work), 'phase': 'PREPARING', 'containerId': None,
            'sourceContainerId': settings['sourceMysqlContainerId'], 'schemas': []}
        self.save('PREPARING')
        source_root = self.work / 'fixed-source'; source_root.mkdir(mode=0o700)
        preliminary = shutil.disk_usage(self.work)
        available = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:'))
        require(preliminary.free >= 10 * GIB + max(2 * GIB, preliminary.total // 10) and available >= 6 * GIB,
                'Insufficient ECS resources even before source extraction; no resize or application stop is allowed')
        archive_source(self.archive, source_root, self.args.commit, self.args.source_sha256)
        profile_file = source_root / 'script/jenkins/compact-acceptance.json'
        profile = json.loads(profile_file.read_text('utf8')); suites = profile.get('javaSuites')
        require(profile.get('schemaVersion') == 1 and profile.get('kind') == 'doorhandle-compact-acceptance-profile'
                and profile.get('sourceTableCount') == 131 and profile.get('targetTableCount') == 29
                and profile.get('externalModelPolicy', {}).get('paidCallsAllowed') is False
                and isinstance(suites, list) and suites, 'Versioned complete acceptance profile is required')
        self.registry = registry(source_root)
        self.validate_suites(suites)
        offsets = {'workbench'}
        for file in (source_root / 'sql/mysql/compact/copy').glob('*.sql'):
            offsets.update(key.lower() for key in re.findall(r'__SOURCE_([A-Z_]+)_OFFSET__', file.read_text('utf8')))
        require(set(settings['sourceOffsets']) == offsets, 'All and only the fixed copy plan domain offsets must be reviewed explicitly')
        sys.path.insert(0, str(source_root / 'script/schema'))
        self.runtime = module('fixture_migration_runtime', source_root / 'script/schema/compact_migration_runtime.py')
        self.runtime.ROOT = self.checkout
        # The verifier has not unpacked its source yet: checkout may contain only
        # work. Use the fixed archive's read-only metadata implementation while
        # keeping private migration paths admitted below the future checkout.
        schema_guard = module('fixture_metadata_guard', source_root / 'script/docker/compact-schema-guard.py')
        def metadata_snapshot(mysql, schema):
            value = schema_guard.metadata_snapshot(lambda sql: mysql.json_rows(sql, database=schema))
            return value, schema_guard.metadata_sha256(value)
        self.runtime.metadata_snapshot = metadata_snapshot
        original = json.loads(self.docker_call('inspect', settings['sourceMysqlContainerId']))[0]
        require(original['Id'] == settings['sourceMysqlContainerId'] and original['State']['Running']
                and original['Config']['Labels'].get('com.docker.compose.project') == PROJECT
                and original['Config']['Labels'].get('com.docker.compose.service') == 'mysql',
                'Source is not the existing original MySQL container')
        backends = self.docker_call('ps', '-aq', '--no-trunc', '--filter',
            'label=com.docker.compose.project=' + PROJECT, '--filter',
            'label=com.docker.compose.service=backend').decode().split()
        require(len(backends) == 1, 'Original application generation is missing or ambiguous')
        backend = json.loads(self.docker_call('inspect', backends[0]))[0]
        environment = dict(item.split('=', 1) for item in backend['Config'].get('Env', []) if '=' in item)
        jdbc = environment.get('DB_URL', '')
        require(jdbc.startswith('jdbc:mysql://'), 'Original application must declare its actual MySQL schema')
        endpoint = urlsplit(jdbc[5:])
        require(endpoint.hostname == 'mysql' and (endpoint.port or 3306) == 3306
                and not endpoint.username and not endpoint.password and endpoint.path == '/' + settings['sourceSchema'],
                'Fixture source is not the actual original application database')
        self.source = readonly_source(self.runtime, self.docker, original['Id'], self.work)
        actual = self.source.single("SELECT JSON_OBJECT('uuid',@@server_uuid,'version',@@version,'foreignKeys',@@foreign_key_checks);")
        require(actual['version'].startswith('8.4.') and actual['foreignKeys'] == 1, 'Existing MySQL 8.4 with FK enforcement required')
        self.source.config['serverUuid'] = actual['uuid']
        contract = json.loads((source_root / 'docs/database/compact-schema-contract.json').read_text('utf8'))
        sources = contract['sourceTables']
        require(len(sources) == len(set(sources)) == 131, 'Complete actual 131-table source contract required')
        require(not self.source.json_rows('SELECT JSON_OBJECT(\'name\',ROUTINE_NAME) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=' + self.runtime.literal(settings['sourceSchema']) + ';')
                and not self.source.json_rows('SELECT JSON_OBJECT(\'name\',EVENT_NAME) FROM information_schema.EVENTS WHERE EVENT_SCHEMA=' + self.runtime.literal(settings['sourceSchema']) + ';'),
                'Source routines/events need a separate reviewed restore plan; no facts will be silently omitted')
        self.journal['resources'] = self.resource_gate(self.source, settings['sourceSchema'], len(suites))
        _, original_metadata = self.runtime.metadata_snapshot(self.source, settings['sourceSchema'])
        snapshot = self.runtime.schema_snapshot(self.source, settings['sourceSchema'], sources)
        require(sum(table['rows'] for table in snapshot['tables'].values()) > 0, 'An empty source cannot prove existing-data preservation')
        backup = self.runtime.backup_schema(self.source, snapshot, self.work / 'source-backup', purpose='source',
            migration_context={'kind': 'fixture-origin-copy', 'sourceCommit': self.args.commit, 'sourceSha256': self.args.source_sha256})
        after = self.runtime.schema_snapshot(self.source, settings['sourceSchema'], sources)
        _, final_metadata = self.runtime.metadata_snapshot(self.source, settings['sourceSchema'])
        require(after['snapshotSha256'] == snapshot['snapshotSha256']
                and private_json(backup)['metadataSha256'] == original_metadata == final_metadata,
                'Source changed during read-only export; retain evidence and prepare another build during a stable window')
        self.start_mysql(original['Image'])
        self.clone_source(snapshot, backup)
        uploaded = self.work / 'candidate-app.jar'; shutil.copyfile(jar, uploaded); os.chmod(uploaded, 0o600)
        require(digest(uploaded) == settings['applicationJarSha256'], 'Copied candidate jar differs')
        java_suites = self.provision_suites(suites)
        worker = self.fixture_config('doorhandle_worker_verify_', 'ecsit_', 'python-worker')
        self.create_account(worker)
        whole = self.whole_config(settings, str(java), str(uploaded))
        manifest = {'version': 2, 'javaSuites': java_suites, 'javaOnly': False, 'sourceRegression': True,
                    'workerMysqlConfig': str(self.write_config('python-worker', worker)),
                    'wholeMigrationConfig': str(self.work / 'whole-migration.json')}
        write_json(self.work / 'whole-migration.json', whole)
        write_json(self.work / 'manifest.json', manifest)
        self.journal.update(manifest=str(self.work / 'manifest.json'), manifestSha256=digest(self.work / 'manifest.json'),
            profileSha256=digest(profile_file), sourceServerUuid=actual['uuid'], sourceSnapshotSha256=snapshot['snapshotSha256'],
            sourceTableCount=131, sourceRows=sum(table['rows'] for table in snapshot['tables'].values()),
            sourceBackupSha256=digest(backup), javaSuiteCount=len(java_suites), fixtureConfigCount=len(self.journal['schemas']))
        self.inspect_owned()
        self.save('PREPARED')
        write_json(self.attempt / '.fixtures-ready.json', {'schema': 1, 'kind': 'doorhandle-ci-fixtures',
            'release': self.args.tag, 'commit': self.args.commit,
            'instanceId': self.args.instance_id, 'machineId': self.args.machine_id})
        return {'status': 'PREPARED', 'commit': self.args.commit, 'release': self.args.tag,
                'manifest': self.journal['manifest'], 'ownerReceipt': str(self.journal_file),
                'containerId': self.journal['containerId'], 'port': self.journal['port'], 'javaSuiteCount': len(java_suites)}

    def validate_suites(self, suites):
        seen, ids = set(), set()
        for suite in suites:
            require(isinstance(suite, dict) and isinstance(suite.get('id'), str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,95}', suite['id'])
                    and isinstance(suite.get('className'), str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]*', suite['className'])
                    and suite['className'].rsplit('.', 1)[-1] not in seen
                    and suite['id'] not in ids
                    and isinstance(suite.get('fixtureProperties'), list) and suite['fixtureProperties']
                    and len(suite['fixtureProperties']) == len(set(suite['fixtureProperties']))
                    and set(suite['fixtureProperties']) <= self.registry['FIXTURE_SCHEMAS'].keys(),
                    'Versioned Java suites must have unique exact classes and audited property lists')
            seen.add(suite['className'].rsplit('.', 1)[-1])
            ids.add(suite['id'])

    def start_mysql(self, image):
        require(re.fullmatch(r'sha256:[a-f0-9]{64}', image), 'Reuse an existing immutable MySQL image')
        require(json.loads(self.docker_call('image', 'inspect', image))[0]['Id'] == image, 'Existing MySQL image is unavailable')
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0)); port = available.getsockname()[1]
        require(1024 < port <= 65535 and port != 3306, 'Owned non-default loopback port required')
        data = self.work / 'mysql-data'; data.mkdir(mode=0o700)
        password = secrets.token_hex(32)
        env = self.work / 'mysql.env'; env.write_text('MYSQL_ROOT_PASSWORD=' + password + '\n', encoding='utf8'); os.chmod(env, 0o600)
        name = 'doorhandle-compact-fixture-' + self.journal['token']
        self.journal.update(containerName=name, image=image, port=port, dataDirectory=str(data), rootPassword=password)
        self.save('STARTING_MYSQL')
        container = self.docker_call('run', '-d', '--pull=never', '--restart=no', '--name', name,
            '--label', LABEL + '=' + self.journal['token'], '--label', 'io.doorhandle.release=' + self.args.tag,
            '--label', 'io.doorhandle.source=' + self.args.source_sha256, '--env-file', str(env),
            '--publish', '127.0.0.1:' + str(port) + ':' + str(port), '--memory', str(1536 * 1024 ** 2),
            '--memory-swap', str(1536 * 1024 ** 2), '--cpus', '1', '--pids-limit', '256',
            '--mount', 'type=bind,source=' + str(data) + ',target=' + str(data),
            '--tmpfs', '/var/lib/mysql', image, '--datadir=' + str(data), '--port=' + str(port),
            '--bind-address=0.0.0.0', '--mysqlx=OFF', '--event-scheduler=OFF', '--local-infile=OFF',
            '--innodb-buffer-pool-size=268435456', '--max-connections=120', timeout=120).decode().strip()
        require(CID.fullmatch(container), 'Owned MySQL container identity unavailable')
        self.journal['containerId'] = container; self.save('MYSQL_STARTED')
        deadline = time.monotonic() + 240
        while True:
            try:
                row = self.admin_query("SELECT JSON_OBJECT('uuid',@@server_uuid,'version',@@version,'port',@@port,'data',@@datadir,'fk',@@foreign_key_checks);")
                require(row['version'].startswith('8.4.') and row['port'] == port and row['fk'] == 1
                        and row['data'].rstrip('/') == str(data), 'Owned MySQL actual storage/port/version differs')
                self.journal['serverUuid'] = row['uuid']; break
            except Exception:
                require(time.monotonic() < deadline and json.loads(self.docker_call('inspect', container))[0]['State']['Running'],
                        'Owned MySQL failed readiness; no other server or image will be substituted')
                time.sleep(2)
        self.save('MYSQL_READY'); self.inspect_owned()
        output = self.work / 'mysql-client'; output.mkdir(mode=0o700); (output / 'private').mkdir(mode=0o700)
        self.mysql = self.runtime.Mysql({'scope': 'ecs-disposable-migration', 'serverUuid': self.journal['serverUuid'],
            'dataDirectory': str(data), 'connection': {'host': '127.0.0.1', 'port': port, 'username': 'root', 'password': password},
            'client': {'kind': 'docker', 'executable': str(self.docker), 'containerId': container}}, output)
        self.mysql.admitted_server()

    def admin_query(self, sql):
        output = self.docker_call('exec', '-i', self.journal['containerId'], 'sh', '-ec',
            'MYSQL_PWD="${MYSQL_ROOT_PASSWORD:?}" exec mysql --no-defaults --no-login-paths -uroot --protocol=TCP -h127.0.0.1 --port="$1" --default-character-set=utf8mb4 --batch --raw --skip-column-names',
            '--', str(self.journal['port']), data=sql.encode('utf8'), timeout=15)
        return json.loads(output.decode().strip())

    def clone_source(self, snapshot, backup):
        manifest = private_json(backup)
        require(manifest['snapshotSha256'] == snapshot['snapshotSha256']
                and manifest['data']['file'] == 'data.sql'
                and (backup.parent / 'data.sql').stat().st_size == manifest['data']['bytes']
                and digest(backup.parent / 'data.sql') == manifest['data']['sha256'], 'Original private backup bytes changed')
        clone = 'doorhandle_migration_verify_' + self.journal['token']
        self.runtime.new_schema(self.mysql, clone); foreign = []
        for table, ddl in sorted(manifest['createTables'].items()):
            statement, relations = self.runtime.remove_inline_foreign_keys(self.runtime.normalize_self(ddl, snapshot['schema'], clone), clone)
            self.mysql.script(statement + ';', database=clone, label='clone-create'); foreign += relations
        self.runtime.restore_data(self.mysql, clone, manifest, backup.parent / 'data.sql')
        for table, detail in manifest['tables'].items():
            if detail['autoIncrement'] is not None:
                require(re.fullmatch(r'[0-9]{1,20}', detail['autoIncrement']), 'Invalid actual source high water')
                self.mysql.script('ALTER TABLE ' + self.runtime.quoted(table) + ' AUTO_INCREMENT=' + detail['autoIncrement'] + ';', database=clone, label='clone-hwm')
        self.runtime.install_relations(self.mysql, clone, foreign)
        self.runtime.install_triggers(self.mysql, clone, snapshot['schema'], manifest['triggers'])
        actual = self.runtime.schema_snapshot(self.mysql, clone, manifest['tables'])
        _, metadata_sha = self.runtime.metadata_snapshot(self.mysql, clone)
        require(actual['snapshotSha256'] == snapshot['snapshotSha256'] and metadata_sha == manifest['metadataSha256'],
                'Read-only actual source clone differs in rows/NULL/clocks/keys/triggers/DDL/high water')
        self.journal.update(sourceClone=clone, sourceCloneSnapshotSha256=actual['snapshotSha256'], sourceCollations={name: detail['collation'] for name, detail in actual['tables'].items()})
        self.save('SOURCE_CLONED')

    def fixture_config(self, prefix, account_prefix, description):
        suffix = secrets.token_hex(6 if prefix == 'doorhandle_feature_' else 5)
        schema = prefix + suffix
        require(schema not in {row['database'] for row in self.journal['schemas']}, 'Unexpected disposable identity collision')
        return {'scope': 'ecs-disposable-mysql', **{key: self.identity[key] for key in ('instanceId', 'machineId')},
            'database': schema, 'username': account_prefix + suffix, 'password': secrets.token_hex(32),
            'serverUuid': self.journal['serverUuid'], 'port': self.journal['port'], 'dataDirectory': self.journal['dataDirectory'],
            'url': f"jdbc:mysql://127.0.0.1:{self.journal['port']}/{schema}?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai"}

    def create_account(self, config):
        self.runtime.new_schema(self.mysql, config['database'])
        self.mysql.script("CREATE USER '" + config['username'] + "'@'%' IDENTIFIED BY '" + config['password'] + "'; GRANT ALL PRIVILEGES ON "
            + self.runtime.quoted(config['database']) + ".* TO '" + config['username'] + "'@'%';", label='fixture-account')
        self.journal['schemas'].append({'database': config['database'], 'username': config['username']})
        self.save('CREATING_SCHEMAS')

    def write_config(self, name, config):
        require(re.fullmatch(r'[a-zA-Z0-9_.-]+', name), 'Invalid fixture configuration name')
        path = self.work / (name + '.json'); write_json(path, config); return path

    def provision_suites(self, suites):
        result = []
        for suite in suites:
            configs, properties = {}, {}
            for number, key in enumerate(suite['fixtureProperties']):
                prefix, account = self.registry['FIXTURE_SCHEMAS'][key]
                config = self.fixture_config(prefix, account, suite['id']); self.create_account(config); configs[key] = config
                properties[key] = str(self.write_config(suite['id'] + '-' + str(number), config))
            for source, target, strict in self.registry['MIGRATION_PAIRS']:
                if source in configs or strict and target in configs:
                    require(source in configs and target in configs, 'Versioned migration suite lacks one side')
                    self.mysql.script('GRANT SELECT,TRIGGER ON ' + self.runtime.quoted(configs[source]['database']) + ".* TO '" + configs[target]['username'] + "'@'%';", label='fixture-source-read')
            result.append({'javaTests': [suite['className']], 'fixtureProperties': properties})
        return result

    def whole_config(self, settings, java, jar):
        token = self.journal['token']; user = 'mig_' + token; secret = secrets.token_hex(32)
        target = 'doorhandle_compact_candidate_' + token
        recovery = {'source': 'doorhandle_legacy_restore_' + token, 'target': 'doorhandle_compact_restore_' + token}
        self.mysql.script("CREATE USER '" + user + "'@'%' IDENTIFIED BY '" + secret + "'; GRANT SELECT,TRIGGER,LOCK TABLES,EVENT,EXECUTE ON " + self.runtime.quoted(self.journal['sourceClone']) + ".* TO '" + user + "'@'%'; "
            + ' '.join('GRANT ALL PRIVILEGES ON ' + self.runtime.quoted(schema) + ".* TO '" + user + "'@'%';" for schema in (target, *recovery.values()))
            + " GRANT SET_ANY_DEFINER,SYSTEM_USER ON *.* TO '" + user + "'@'%';", label='whole-migration-account')
        return {'version': 1, 'scope': 'ecs-disposable-migration', **{key: self.identity[key] for key in ('instanceId', 'machineId')},
            'serverUuid': self.journal['serverUuid'], 'sourceSchema': self.journal['sourceClone'], 'targetSchema': target,
            'connection': {'host': '127.0.0.1', 'port': self.journal['port'], 'username': user, 'password': secret},
            'client': {'kind': 'docker', 'executable': str(self.docker), 'containerId': self.journal['containerId']},
            'sourceOffsets': settings['sourceOffsets'], 'sourceCollations': self.journal['sourceCollations'],
            'workbench': {'java': java, 'applicationJar': jar, 'applicationJarSha256': settings['applicationJarSha256']},
            'recoverySchemas': recovery, 'dataDirectory': self.journal['dataDirectory']}

    def inspect_owned(self):
        row = json.loads(self.docker_call('inspect', self.journal['containerId']))[0]
        require(row['Id'] != self.journal['sourceContainerId'] and row['Id'] == self.journal['containerId']
                and row['Image'] == self.journal['image'] and row['Config']['Labels'].get(LABEL) == self.journal['token']
                and row['Config']['Labels'].get('io.doorhandle.release') == self.args.tag
                and row['Config']['Labels'].get('io.doorhandle.source') == self.args.source_sha256,
                'Container does not belong to this fixture attempt')
        data = canonical(self.journal['dataDirectory'])
        require(data.is_relative_to(canonical(self.journal['work'])) and any(
            mount.get('Type') == 'bind' and mount.get('RW') is True and mount.get('Source') == str(data)
            and mount.get('Destination') == str(data) for mount in row['Mounts']), 'Owned same-path MySQL data bind differs')
        port = self.journal['port']; ports = row['HostConfig']['PortBindings']
        require(ports == {str(port) + '/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]}
                and row['HostConfig']['RestartPolicy']['Name'] == 'no', 'Owned loopback-only port or restart policy differs')
        return row

    def load(self):
        self.journal = private_json(self.journal_file)
        require(all(self.journal.get(key) == value for key, value in {'schemaVersion': 1,
            'kind': 'doorhandle-compact-fixture-owner', 'release': self.args.tag, 'commit': self.args.commit,
            'sourceSha256': self.args.source_sha256, 'identity': self.identity}.items()), 'Fixture receipt belongs to another build/host')
        self.work = canonical(self.journal['work'])
        require(self.work.is_relative_to(canonical(self.checkout / 'work')), 'Fixture state escaped this checkout/work')

    def cleanup(self):
        self.load()
        if (self.attempt / '.verification-claimed').exists():
            verification = private_json(self.attempt / 'verification-receipt.json')
            require(verification.get('status') in ('PASS', 'FAILED') and all(verification.get(key) == value
                for key, value in {'release': self.args.tag, 'commit': self.args.commit,
                    'sourceSha256': self.args.source_sha256, 'identity': self.identity}.items()),
                    'Verification has not returned with matching private evidence; do not stop a running fixture')
        if not self.journal.get('containerId') and self.journal.get('containerName'):
            # Docker may create a container and then time out before returning its
            # ID. Recover only the exact pre-recorded name and all ownership labels.
            candidates = self.docker_call('ps', '-aq', '--no-trunc', '--filter',
                'label=' + LABEL + '=' + self.journal['token']).decode().split()
            require(len(candidates) <= 1 and all(CID.fullmatch(value) for value in candidates),
                    'Unknown Docker create result requires manual review')
            if candidates:
                self.journal['containerId'] = candidates[0]
                owned = self.inspect_owned()
                require(owned['Name'] == '/' + self.journal['containerName'], 'The recorded owned container name changed')
                self.save('CLEANUP_IDENTITY_RECOVERED')
        if self.journal.get('containerId'):
            self.inspect_owned()
            self.docker_call('stop', '--time', '60', self.journal['containerId'], timeout=90)
            row = self.inspect_owned()
            require(not row['State']['Running'] and not row['State']['Restarting'] and row['State']['Pid'] == 0,
                    'Owned MySQL stop was not confirmed')
        receipt = {'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-cleanup', 'status': 'STOPPED',
            'release': self.args.tag, 'commit': self.args.commit, 'sourceSha256': self.args.source_sha256, 'identity': self.identity,
            'containerId': self.journal.get('containerId'), 'sourceContainerUntouched': self.journal['sourceContainerId'],
            'dataDirectoryRetained': self.journal.get('dataDirectory'), 'sourceDumpAndEvidenceRetained': True}
        path = self.work / 'cleanup-receipt.json'; write_json(path, receipt, replace=True)
        self.save('OWNED_SERVER_STOPPED')
        return {'status': receipt['status'], 'commit': self.args.commit, 'release': self.args.tag,
                'cleanupReceipt': str(path), 'cleanupReceiptSha256': digest(path)}


def readonly_source(runtime, docker, container, output):
    """Keep production root credentials inside its existing container; no write method is admitted."""
    class ReadonlySource(runtime.Mysql):
        def __init__(self):
            self.runtime = runtime; self.program = docker; self.container = container
            self.output = output; self.sequence = 0
            self.config = {'scope': 'production-migration', 'serverUuid': None}
        def command(self, database=None, *, dump=False, table_names=()):
            utility = 'mysqldump' if dump else 'mysql'
            arguments = ['--default-character-set=utf8mb4']
            if dump:
                arguments += ['--single-transaction', '--skip-lock-tables', '--skip-add-locks', '--skip-disable-keys',
                    '--skip-add-drop-table', '--no-create-info', '--skip-triggers', '--complete-insert', '--hex-blob',
                    '--skip-extended-insert', '--set-gtid-purged=OFF', '--no-tablespaces', '--skip-comments',
                    runtime.identifier(database), *[runtime.identifier(table) for table in table_names]]
            else:
                arguments += ['--batch', '--raw', '--skip-column-names', '--unbuffered', '--binary-mode', '--local-infile=0']
                if database:
                    arguments.append('--database=' + runtime.identifier(database))
            return [str(docker), 'exec', '-i', container, 'sh', '-ec',
                'MYSQL_PWD="${MYSQL_ROOT_PASSWORD:?}" exec ' + utility + ' --no-defaults --no-login-paths --protocol=SOCKET -uroot "$@"', '--', *arguments], b''
        def script(self, sql, **kwargs):
            require(isinstance(sql, str) and all(re.match(r'(?:SELECT\b|SHOW CREATE TABLE\b|SHOW GRANTS\b|SET SESSION (?:time_zone|sql_mode)\b)', statement, re.I)
                for statement in runtime.split_top_level(runtime.without_comments(sql), ';')), 'Only fixed original-source read statements are admitted')
            return super().script(sql, **kwargs)
        def source_lock(self, *args, **kwargs):
            raise ValueError('Fixture preparation never locks or pauses the original production source')
    return ReadonlySource()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'cleanup', 'status'))
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--settings')
    args = parser.parse_args(); instance = None
    try:
        instance = Preparation(args)
        if args.phase == 'prepare':
            require(args.settings, 'Explicit private preparation settings required'); result = instance.prepare()
        elif args.phase == 'cleanup':
            result = instance.cleanup()
        else:
            instance.load(); result = {'status': instance.journal['phase'], 'release': args.tag,
                                       'containerId': instance.journal.get('containerId')}
        print(json.dumps(result)); return 0
    except BaseException:
        if instance and instance.journal:
            try:
                instance.save('FAILED_OR_UNKNOWN_RETAINED')
            except BaseException:
                pass
        print('Fixture preparation/control failed; do not use a readiness flag. Preserve private owned evidence on ECS.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
