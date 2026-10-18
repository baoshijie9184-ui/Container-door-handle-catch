#!/usr/bin/env python3
"""Build and rehearse real application upgrades against private backup copies, never production volumes."""
import argparse
import copy
import datetime as dt
import hashlib
from html.parser import HTMLParser
import http.cookiejar
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import tarfile
import time
import traceback
import urllib.error
import urllib.request
import uuid

PROJECT = re.compile(r'^doorhandle-rehearsal-[a-f0-9]{12}$')
TAG = re.compile(r'^ci-[0-9]+-[a-f0-9]{12}$')
PRODUCTION = 'doorhandlecatch-monolith'
ZONE = dt.timezone(dt.timedelta(hours=8))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def private_json(path, value):
    require(not path.is_symlink(), 'Private evidence cannot be a link')
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def extract_source(archive, destination):
    with tarfile.open(archive, 'r:gz') as source:
        for entry in source:
            name = Path(entry.name)
            require(not name.is_absolute() and '..' not in name.parts and
                    not entry.name.startswith(('\\', '/')) and '\\' not in entry.name and
                    (entry.isfile() or entry.isdir()), 'Unsafe source archive entry')
        source.extractall(destination, filter='data')


def isolated_config(config, project, port, images, database):
    """Flattened Compose config is private; rewrite every storage/network/credential identity."""
    require(bool(PROJECT.fullmatch(project)) and project != PRODUCTION, 'Invalid rehearsal identity')
    require(type(port) is int and 1024 <= port <= 65535, 'Invalid private rehearsal port')
    require(re.fullmatch(r'[A-Za-z0-9_]{1,64}', database), 'Invalid database name')
    value = copy.deepcopy(config)
    value['name'] = project
    passwords = {key: secrets.token_hex(32) for key in ('mysql', 'root', 'redis', 'jwt', 'mem0', 'mcp', 'gateway')}
    replacements = {
        'MYSQL_ROOT_PASSWORD': passwords['root'], 'MYSQL_PASSWORD': passwords['mysql'],
        'DB_PASSWORD': passwords['mysql'], 'MYSQL_DATABASE': database, 'MYSQL_USER': 'doorhandle',
        'DB_USERNAME': 'doorhandle',
        'DB_URL': f'jdbc:mysql://mysql:3306/{database}?useSSL=false&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true&useUnicode=true&characterEncoding=UTF-8',
        'REDIS_HOST': 'redis', 'REDIS_PASSWORD': passwords['redis'], 'JWT_SECRET': passwords['jwt'],
        'MEM0_BRIDGE_TOKEN': passwords['mem0'], 'MEM0_SERVICE_URL': 'http://mem0:8081',
        'MEM0_BASE_URL': 'http://mem0:8081', 'CHAT_ASSISTANT_CHROMA_BASE_URL': 'http://chroma:8000',
        'APP_KAFKA_BOOTSTRAP_SERVERS': 'kafka:9092', 'KAFKA_BOOTSTRAP_SERVERS': 'kafka:9092',
        'AGENT_MCP_GATEWAY_SECRET': passwords['mcp'], 'MCP_RUNNER_SECRET': passwords['mcp'],
        'AGENT_MCP_GATEWAY_KEY': passwords['gateway'],
        'AGENT_MCP_GATEWAY_URL': 'http://higress:8080/mcp/fetch',
        'AGENT_MODEL_GATEWAY_BASE_URL': 'http://higress:8080',
        'MCP_EXEC_NETWORK': project+'-mcp-exec',
        'APP_COOKIE_SECURE': 'false', 'APP_CORS_ALLOWED_ORIGINS': f'http://127.0.0.1:{port},http://localhost:{port}',
    }
    for name, definition in value.get('volumes', {}).items():
        value['volumes'][name] = {'name': project+'_'+name, 'labels': {'io.doorhandle.rehearsal': project}}
    for name, definition in value.get('networks', {}).items():
        value['networks'][name] = {'name': project+'-'+name, 'driver': 'bridge',
                                 'internal': bool(definition.get('internal', False)),
                                 'labels': {'io.doorhandle.rehearsal': project}}
    for name, service in value['services'].items():
        service.pop('container_name', None)
        service.pop('env_file', None)
        service.pop('extra_hosts', None)
        service.pop('ports', None)
        service['restart'] = 'no'
        service.setdefault('labels', {})['io.doorhandle.rehearsal'] = project
        environment = service.setdefault('environment', {})
        for key in list(environment):
            if key in replacements:
                environment[key] = replacements[key]
        if name == 'backend':
            environment.update({key: replacements[key] for key in (
                'DB_URL', 'DB_USERNAME', 'DB_PASSWORD', 'REDIS_HOST', 'REDIS_PASSWORD', 'JWT_SECRET',
                'MEM0_SERVICE_URL', 'MEM0_BASE_URL', 'MEM0_BRIDGE_TOKEN', 'CHAT_ASSISTANT_CHROMA_BASE_URL',
                'APP_KAFKA_BOOTSTRAP_SERVERS', 'APP_COOKIE_SECURE', 'APP_CORS_ALLOWED_ORIGINS')})
        if name == 'mysql':
            environment.update({key: replacements[key] for key in ('MYSQL_ROOT_PASSWORD', 'MYSQL_PASSWORD', 'MYSQL_DATABASE', 'MYSQL_USER')})
            # Never run copied database EVENT definitions in an isolated rehearsal.
            service['command'] = list(service.get('command', []))+['--event-scheduler=OFF']
        if name == 'nginx':
            service['ports'] = [{'target': 80, 'published': str(port), 'host_ip': '127.0.0.1', 'protocol': 'tcp'}]
        if name in images:
            service['image'] = images[name]
    validate_isolation(value, project)
    return value


def validate_isolation(config, project):
    require(bool(PROJECT.fullmatch(project)) and config.get('name') == project, 'Rehearsal project differs')
    require(not config.get('secrets') and not config.get('configs'), 'External Compose resources are unsupported')
    for kind in ('volumes', 'networks'):
        for resource in config.get(kind, {}).values():
            require(not resource.get('external') and resource.get('name', '').startswith(project+('_' if kind == 'volumes' else '-')),
                    'Shared storage or network rejected')
    for name, service in config['services'].items():
        require(not service.get('network_mode') and not service.get('privileged') and not service.get('pid') and
                not service.get('ipc') and not service.get('volumes_from') and not service.get('devices'), 'Host namespace rejected')
        for network in service.get('networks', {}):
            require(network in config.get('networks', {}), 'Unknown network')
        for mount in service.get('volumes', []):
            if mount['type'] == 'volume':
                require(mount['source'] in config.get('volumes', {}), 'Unowned volume rejected')
            else:
                allowed = (name == 'detection-worker' and mount['target'] == '/models' and mount.get('read_only') or
                           name == 'mcp-runner' and (mount['source'], mount['target']) in (
                               ('/var/run/docker.sock', '/var/run/docker.sock'), ('/usr/bin/docker', '/usr/local/bin/docker')))
                require(mount['type'] == 'bind' and allowed, 'Unexpected host mount rejected')
        for port in service.get('ports', []):
            require(name == 'nginx' and port.get('host_ip') == '127.0.0.1' and port.get('target') == 80,
                    'Public rehearsal port rejected')


def require_no_detection_backlog(output, group):
    rows = [line.split() for line in output.splitlines() if line.split() and line.split()[0] == group]
    require(bool(rows), 'Detection consumer offset is unknown; do not start a copied worker')
    for row in rows:
        require(len(row) >= 6 and all(part.isdigit() for part in row[2:6]) and row[3] == row[4] and int(row[5]) == 0,
                'Detection backlog or unknown offset; do not replay copied work')


class Rehearsal:
    def __init__(self, directory, config, ops, guard, baseline):
        self.directory, self.config, self.ops, self.guard = directory, config, ops, guard
        self.project = config['name']
        self.guard.PROJECT = self.project  # Dedicated imported module, never the production guard process.
        self.baseline = baseline
        self.state = directory/'state'
        self.state.mkdir(mode=0o700)
        self.file = directory/'compose.json'
        private_json(self.file, config)
        self.report = {'project': self.project, 'startedAt': dt.datetime.now(ZONE).isoformat(),
                       'passed': False, 'checks': [], 'productionChanged': False}
        private_json(directory/'production-baseline.json', baseline)
        self.persist()

    def persist(self):
        private_json(self.directory/'result.json', self.report)

    def check(self, name, condition):
        require(condition, name)
        self.report['checks'].append(name)
        self.persist()

    def dc(self, *args, config=None, **kwargs):
        file = self.file
        if config is not None:
            validate_isolation(config, self.project)
            file = self.directory/'activation.json'
            private_json(file, config)
        try:
            return self.ops.docker('compose', '--project-name', self.project, '-f', str(file), *args, **kwargs)
        except self.ops.OpsError:
            # Detailed diagnostics stay on the server, never in Jenkins console/artifacts.
            with (self.directory/'compose-diagnostics.log').open('ab') as log:
                os.chmod(log.name, 0o600)
                subprocess.run(['docker', 'compose', '--project-name', self.project, '-f', str(file),
                                'logs', '--no-color', '--tail', '100'], stdout=log, stderr=log, timeout=35, check=False)
            raise

    def bridge(self, path, body):
        require(path in ('/memories/add', '/memories/operations/get', '/memories/search'), 'Unsupported bridge diagnostic')
        script = '''import json,os,sys,urllib.request
value=json.load(sys.stdin)
request=urllib.request.Request('http://127.0.0.1:8081'+value['path'],data=json.dumps(value['body']).encode(),headers={'Content-Type':'application/json','x-doorhandle-memory-token':os.environ['MEM0_BRIDGE_TOKEN']})
with urllib.request.urlopen(request,timeout=40) as response:print(response.read().decode())
'''
        return json.loads(self.ops.docker('exec', '-i', self.row('mem0')['Id'], 'python', '-B', '-c', script,
                                         data=json.dumps({'path': path, 'body': body}).encode(), timeout=50))

    def row(self, service):
        ids = self.dc('ps', '-aq', service).decode().split()
        require(len(ids) == 1, 'Expected one rehearsal '+service)
        row = json.loads(self.ops.docker('inspect', ids[0]))[0]
        require(row['Config']['Labels'].get('com.docker.compose.project') == self.project, 'Container ownership differs')
        return row

    def require_fresh_resources(self):
        require(not self.ops.docker('ps', '-aq', '--filter', 'label=com.docker.compose.project='+self.project).strip(),
                'Rehearsal containers already exist')
        for kind in ('volume', 'network'):
            existing = set(self.ops.docker(kind, 'ls', '--format', '{{.Name}}').decode().splitlines())
            require(not existing.intersection(definition['name'] for definition in self.config.get(kind+'s', {}).values()),
                    'Rehearsal resource already exists; refusing to restore into it')

    def production_unchanged(self):
        current = self.ops.inventory()
        stable = lambda rows: sorted((r['id'], r['image'], r['running'], json.dumps(r['mounts'], sort_keys=True)) for r in rows)
        unchanged = stable(current) == stable(self.baseline)
        if not unchanged:
            self.report['productionChanged'] = True
            self.persist()
        self.check('Production containers, images, mounts and running states unchanged', unchanged)

    def activate(self, images, label):
        config = copy.deepcopy(self.config)
        for service in ('backend', 'nginx', 'mem0'):
            config['services'][service]['image'] = images[service]
        mode = self.guard.prepare(self.state, config)
        record = self.guard.read_json(self.state/'memory-transition.json')
        config['services']['mem0']['image'] = record['selectedImage']
        if mode == 'replace':
            self.dc('up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '240', 'mem0', config=config, timeout=270)
        self.guard.verify(self.state)
        self.dc('up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '240', 'backend', config=config, timeout=270)
        self.dc('up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--force-recreate', '--wait', '--wait-timeout', '90', 'nginx', config=config, timeout=120)
        self.check(label+' uses the requested real backend', self.row('backend')['Image'] == images['backend'])
        self.report.setdefault('transitions', []).append({'label': label, 'memoryPreserved': mode == 'preserve',
                                                        'requiredProtocol': record['requiredProtocol'], 'backend': images['backend']})
        self.persist()
        return config

    def verify_dispatch_index(self):
        sql = "SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='agent_conversation_input' AND INDEX_NAME='idx_conversation_input_dispatch_owner';"
        return self.ops.db(self.row('mysql')['Id'], sql).strip() == 'status,user_id,id'

    def migrate_candidate(self, source):
        # Fixed additive migration on the owned copy only; production publishing never invokes it.
        file = source/'sql/mysql/migration-V39-conversation-owner-dispatch.sql'
        mirror = source/'doorhandle-module-app/src/main/resources/db/migration-V39-conversation-owner-dispatch.sql'
        require(file.read_bytes() == mirror.read_bytes(), 'Candidate V39 migration copies differ')
        existing = self.ops.db(self.row('mysql')['Id'], "SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='agent_conversation_input' AND INDEX_NAME='idx_conversation_input_dispatch_owner';").strip()
        if existing == '0':
            self.ops.db(self.row('mysql')['Id'], file.read_text(encoding='utf8'))
        self.check('Candidate V39 adds only the expected dispatch index', self.verify_dispatch_index())

    def cleanup(self):
        # Re-read labels, and revalidate the exact private config before deleting owned copies.
        validate_isolation(self.config, self.project)
        ids = self.ops.docker('ps', '-aq', '--filter', 'label=com.docker.compose.project='+self.project).decode().split()
        if ids:
            containers = json.loads(self.ops.docker('inspect', *ids))
            require(all((row['Config'].get('Labels') or {}).get('io.doorhandle.rehearsal') == self.project for row in containers),
                    'Cleanup container ownership differs')
        for kind in ('volume', 'network'):
            for definition in self.config.get(kind+'s', {}).values():
                name = definition['name']
                try:
                    data = json.loads(self.ops.docker(kind, 'inspect', name))[0]
                except self.ops.OpsError:
                    continue
                require((data.get('Labels') or {}).get('io.doorhandle.rehearsal') == self.project, 'Cleanup ownership differs')
        self.dc('down', '--volumes', '--remove-orphans', timeout=240)
        self.report['cleaned'] = True
        self.report['kept'] = False
        self.persist()


class Client:
    def __init__(self, port):
        self.base = 'http://127.0.0.1:'+str(port)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, method, path, value=None, data=None, content_type='application/json'):
        body = json.dumps(value).encode() if value is not None else data
        request = urllib.request.Request(self.base+path, data=body, method=method,
                                         headers={'Content-Type': content_type, 'X-Agent-Action': 'workbench'})
        with self.opener.open(request, timeout=25) as response:
            raw = response.read()
            if 'application/json' not in response.headers.get('Content-Type', ''):
                return raw
            result = json.loads(raw)
            if isinstance(result, dict) and 'code' in result:
                require(result['code'] == 200, 'Application API returned an error')
                return result.get('data')
            return result

    def login(self, account):
        return self.request('POST', '/api/auth/login', {'username': account, 'password': os.environ.get('DOORHANDLE_DEMO_PASSWORD', '123456')})


def verify_ui_entries(client):
    class Entry(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids, self.scripts = set(), []
        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if attributes.get('id'):
                self.ids.add(attributes['id'])
            if tag == 'script' and attributes.get('type') == 'module' and attributes.get('src'):
                self.scripts.append(attributes['src'])
    for path, node, prefix in (('/', 'app', '/assets/'), ('/agent-ui/', 'root', '/agent-ui/assets/')):
        body = client.request('GET', path)
        require(isinstance(body, bytes), 'UI entry is not an HTML resource')
        entry = Entry()
        entry.feed(body.decode('utf8'))
        require(node in entry.ids and bool(entry.scripts), 'UI mount point or compiled module is missing')
        for script in entry.scripts:
            require(script.startswith(prefix) and not any(part in ('..', '.') for part in script.split('/')) and
                    not any(char in script for char in ('\\', '?', '#', ':')), 'UI module is not a private same-origin asset')
            module = client.request('GET', script)
            require(isinstance(module, bytes) and len(module) >= 32 and not module.lstrip().lower().startswith((b'<!doctype', b'<html')),
                    'Compiled UI module is unavailable or fell back to HTML')


def smoke(run, port, marker=None):
    client = Client(port)
    for account in ('inspector.demo', 'inspector.demo2', 'supervisor.demo', 'supervisor.demo2'):
        client.login(account)
        require(client.request('GET', '/api/chat-assistant/sessions') is not None, 'Sessions unavailable')
    run.check('Four demo accounts can log in and read their own sessions', True)
    verify_ui_entries(client)
    run.check('Vue and React production entry points served', True)
    client.login('inspector.demo')
    capabilities = client.request('GET', '/api/agent/workbench/capabilities')
    run.check('All eight workbench capabilities enabled', all(capabilities.get(key) is True for key in ('plans', 'questions', 'files', 'forks', 'children', 'jobs', 'usage', 'recovery')))
    if marker:
        content = client.request('GET', marker['path'])
        run.check('Uploaded private file survives the application transition', hashlib.sha256(content).hexdigest() == marker['sha256'])
        client.login('inspector.demo2')
        try:
            client.request('GET', marker['path'])
        except urllib.error.HTTPError as error:
            run.check('Other account cannot read the retained file', error.code in (403, 404))
        else:
            raise RuntimeError('Private file isolation failed')
    return client


def upload_marker(port):
    client = Client(port)
    client.login('inspector.demo')
    session = client.request('POST', '/api/chat-assistant/sessions')
    session_id = session['sessionId']
    boundary = 'rehearsal-'+uuid.uuid4().hex
    payload = ('隔离升级与回滚验收 '+uuid.uuid4().hex).encode()
    data = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="rehearsal.txt"\r\nContent-Type: text/plain\r\n\r\n'.encode()+payload+f'\r\n--{boundary}--\r\n'.encode())
    uploaded = client.request('POST', f'/api/agent/conversations/{session_id}/files?requestId='+uuid.uuid4().hex,
                              data=data, content_type='multipart/form-data; boundary='+boundary)
    return {'path': f'/api/agent/conversations/{session_id}/files/{uploaded["id"]}/content',
            'sha256': hashlib.sha256(payload).hexdigest()}


def memory_marker(run, port):
    client = Client(port)
    identity = client.login('inspector.demo')
    owner = 'doorhandlecatch:user:'+str(identity['userId'])
    request_id, session = uuid.uuid4().hex, 'rehearsal-'+uuid.uuid4().hex
    response = run.bridge('/memories/add', {'user_id': owner, 'app_id': 'doorhandlecatch', 'run_id': session,
                         'request_id': request_id, 'content': '请长期记住：我的质检报告偏好先列出缺陷分类，再列出整改建议。'})
    deadline = time.monotonic()+100
    operation = response['data'].get('operation', response['data'])
    while operation['status'] == 'RUNNING' and time.monotonic() < deadline:
        time.sleep(2)
        operation = run.bridge('/memories/operations/get', {'user_id': owner, 'app_id': 'doorhandlecatch', 'request_id': request_id})['data']
    require(operation['status'] == 'SUCCEEDED', 'Memory extraction outcome needs review; no replay attempted')
    rows = client.request('GET', '/api/agent/memories')['items']
    row = next((item for item in rows if item['sourceSessionId'] == session), None)
    require(row is not None and row.get('lifecycle') is not None, 'New memory was not independently read')
    change_id = uuid.uuid4().hex
    policy = client.request('POST', '/api/agent/memories/'+row['id']+'/lifecycle', {
        'requestId': change_id, 'expectedDigest': row['digest'], 'expectedRevision': row['lifecycle']['revision'],
        'state': 'EXCLUDED', 'expiresAt': None, 'autoDelete': False, 'confirmed': True})
    run.check('Real Java API confirms memory exclusion', policy['state'] == 'EXCLUDED')
    audit = client.request('GET', '/api/agent/memories/audit')
    run.check('Memory exclusion has a successful MySQL audit', any(item.get('requestId') == change_id and item['outcome'] == 'SUCCEEDED' for item in audit))
    result = {'owner': owner, 'session': session, 'memoryId': row['id'], 'requestId': change_id, 'revision': policy['revision']}
    private_json(run.directory/'memory-marker.json', result)
    return result


def verify_memory_marker(run, port, marker, *, legacy=False):
    client = Client(port)
    client.login('inspector.demo')
    if not legacy:
        row = client.request('GET', '/api/agent/memories/'+marker['memoryId'])
        run.check('Excluded policy and revision survive reactivation/restart', row['lifecycle']['state'] == 'EXCLUDED' and row['lifecycle']['revision'] == marker['revision'])
    response = run.bridge('/memories/search', {'user_id': marker['owner'], 'app_id': 'doorhandlecatch',
                          'run_id': marker['session'], 'query': '我的质检报告偏好是什么', 'scope': 'ACCOUNT', 'top_k': 20})
    rows = response['data']
    if isinstance(rows, dict):
        rows = rows.get('results', [])
    run.check('Excluded memory stays absent from native retrieval'+(' after legacy rollback' if legacy else ''),
              all(item['id'] != marker['memoryId'] for item in rows))


def run(args):
    root, runtime = Path(args.root), Path(args.runtime)
    require(TAG.fullmatch(args.tag) and re.fullmatch(r'[a-f0-9]{64}', args.source_sha256), 'Invalid source identity')
    for path in (root, runtime):
        require(path.is_absolute() and path.parts[1] in ('home', 'opt', 'srv') and
                path.is_dir() and not any(p.is_symlink() for p in (path, *path.parents)) and '..' not in path.parts, 'Unsafe deployment path')
    archive = root/'inbox'/args.tag/'source.tar.gz'
    ops = module('rehearsal_ops', Path(__file__).with_name('monolith-ops.py'))
    guard = module('rehearsal_guard', Path(__file__).with_name('memory-compat.py'))
    require(archive.is_file() and not archive.is_symlink() and ops.digest(archive) == args.source_sha256, 'Source checksum differs')
    with ops.maintenance_lock(root):
        snapshots = sorted((root/'backups').glob('ops-*'), key=lambda p: p.stat().st_mtime, reverse=True)
        snapshot = root/'backups'/args.snapshot if args.snapshot else next((p for p in snapshots if (p/'COMPLETE').is_file()), None)
        require(snapshot is not None and snapshot.parent == root/'backups' and snapshot.name.startswith('ops-'), 'Completed backup required')
        manifest = ops.verify(snapshot)
        require(shutil.disk_usage(root).free > max(5*1024**3, manifest.get('estimatedBytes', 0)+3*1024**3), 'Insufficient rehearsal disk reserve')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', args.port))
        project = 'doorhandle-rehearsal-'+uuid.uuid4().hex[:12]
        parent = root/'rehearsals'
        require(not parent.is_symlink(), 'Rehearsal root cannot be a link')
        parent.mkdir(mode=0o700, exist_ok=True)
        directory = parent/project
        directory.mkdir(mode=0o700)
        source = directory/'source'
        source.mkdir(mode=0o700)
        extract_source(archive, source)
        baseline = ops.inventory()
        require(all(ops.healthy(row['id']) for row in baseline if row['running']), 'Production is unhealthy; defer resource-intensive rehearsal')
        env = {**os.environ, 'DOORHANDLE_ENV_FILE': str(runtime/'deploy/cloud.env'),
               'DETECTION_BUILD_CONTEXT': str(runtime/'work/cloud/pth-worker-build'), 'APP_IMAGE_TAG': args.tag}
        command = ['compose', '--project-name', project, '--env-file', str(runtime/'deploy/cloud.env')]
        for file in ('compose.monolith.yml', 'compose.cloud.yml', 'compose.detection.yml', 'compose.ai-gateway.yml'):
            command += ['-f', str(source/file)]
        config = json.loads(ops.docker(*command, 'config', '--format', 'json', env=env))
        config = isolated_config(config, project, args.port, manifest['images'], manifest['databaseName'])
        instance = Rehearsal(directory, config, ops, guard, baseline)
        instance.report.update(snapshot=snapshot.name, release=args.tag, sourceSha256=args.source_sha256, port=args.port)
        instance.persist()
        instance.require_fresh_resources()
        print(json.dumps({'project': project, 'phase': 'BUILDING', 'port': args.port}), flush=True)
        succeeded = False
        try:
            # Full production Dockerfiles; do not substitute a JAR into the previous runtime image.
            build_config = copy.deepcopy(config)
            for service, repository in (('backend', 'backend'), ('nginx', 'web'), ('mem0', 'mem0')):
                build_config['services'][service]['image'] = 'doorhandlecatch/'+repository+':'+project
            private_json(directory/'build.json', build_config)
            with (directory/'image-build.log').open('xb') as log:
                os.chmod(log.name, 0o600)
                result = subprocess.run(['docker', 'compose', '--project-name', project, '-f', str(directory/'build.json'),
                                         'build', 'backend', 'nginx', 'mem0'], stdout=log, stderr=log, timeout=1800, check=False)
            require(result.returncode == 0, 'Image build failed; inspect private image-build.log')
            candidate = {service: guard.image(build_config['services'][service]['image'])[0] for service in ('backend', 'nginx', 'mem0')}
            instance.report['candidateImages'] = candidate
            instance.check('Three candidate images built from production Dockerfiles', True)
            print(json.dumps({'project': project, 'phase': 'RESTORING'}), flush=True)
            for logical, definition in config['volumes'].items():
                original = PRODUCTION+'_'+logical
                if original not in manifest['volumes']:
                    continue
                name = definition['name']
                ops.docker('volume', 'create', '--label', 'io.doorhandle.rehearsal='+project, name)
                common = ['run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                          '--cap-add', 'CHOWN', '--cap-add', 'FOWNER', '--cap-add', 'DAC_OVERRIDE',
                          '--security-opt', 'no-new-privileges', '--user', '0', '--mount', 'type=volume,src='+name+',dst=/target']
                file = snapshot/manifest['volumes'][original]
                with file.open('rb') as stream:
                    ops.docker(*common, '-i', '--entrypoint', 'tar', manifest['images']['backend'], '-xzf', '-', '-C', '/target', input_stream=stream, timeout=600)
                actual = json.loads(ops.docker(*common, '--entrypoint', 'python3', manifest['images']['backend'], '-c', ops.SCAN_VOLUME, timeout=600))
                instance.check('Restored volume matches backup: '+logical, actual == ops.archive_files(file))
            instance.dc('up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '180', 'mysql', timeout=210)
            mysql = instance.row('mysql')['Id']
            with (snapshot/'database.sql.gz').open('rb') as stream:
                ops.docker('exec', '-i', mysql, 'bash', '-o', 'pipefail', '-c',
                           'gzip -dc | MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot --default-character-set=utf8mb4 "$MYSQL_DATABASE"', input_stream=stream, timeout=600)
            instance.check('Restored MySQL row counts and checksums match', ops.table_counts(mysql) == manifest['tableCounts'] and ops.table_checksums(mysql, manifest['tableCounts']) == manifest['tableChecksums'])
            # Never start copied pending input/install work. Require a quiescent source snapshot.
            checks = ["SELECT COUNT(*) FROM agent_conversation_input WHERE status IN ('QUEUED','STARTED')",
                      "SELECT COUNT(*) FROM agent_workbench_item WHERE (kind='EXECUTION' AND status IN ('RUNNING','READY')) OR (kind='CHILD' AND status IN ('QUEUED','RUNNING'))",
                      "SELECT COUNT(*) FROM agent_mcp_install_job WHERE status IN ('QUEUED','RUNNING')"]
            instance.check('Backup has no automatically executable Agent or installation work', all(ops.db(mysql, sql).strip() == '0' for sql in checks))
            instance.dc('up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '180', 'kafka', timeout=210)
            group = config['services']['detection-worker']['environment']['KAFKA_CONSUMER_GROUP']
            require(isinstance(group, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', group), 'Unexpected detection consumer group')
            offsets = ops.docker('exec', instance.row('kafka')['Id'], '/opt/kafka/bin/kafka-consumer-groups.sh',
                                 '--bootstrap-server', 'kafka:9092', '--describe', '--group', group, timeout=45).decode()
            require_no_detection_backlog(offsets, group)
            instance.check('Restored Kafka has committed zero-lag worker offsets; copied detection is not replayed', True)
            instance.dc('up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '240', timeout=420)
            smoke(instance, args.port)
            marker = upload_marker(args.port)
            private_json(directory/'marker.json', marker)
            instance.migrate_candidate(source)
            print(json.dumps({'project': project, 'phase': 'UPGRADING'}), flush=True)
            instance.activate(candidate, 'Upgrade')
            smoke(instance, args.port, marker)
            memory = memory_marker(instance, args.port)
            upgraded_memory = instance.row('mem0')['Id']
            print(json.dumps({'project': project, 'phase': 'ROLLING_BACK'}), flush=True)
            instance.activate(manifest['images'], 'Rollback')
            instance.check('Application rollback preserves the additive V39 index', instance.verify_dispatch_index())
            smoke(instance, args.port, marker)
            instance.check('Legacy rollback retains the exact compatible memory bridge', instance.row('mem0')['Id'] == upgraded_memory)
            verify_memory_marker(instance, args.port, memory, legacy=True)
            current_config = instance.activate(candidate, 'Candidate reactivation')
            instance.dc('restart', 'backend', timeout=120)
            instance.dc('up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '240', 'backend', config=current_config, timeout=270)
            smoke(instance, args.port, marker)
            verify_memory_marker(instance, args.port, memory)
            instance.production_unchanged()
            private_json(instance.file, current_config)
            succeeded = True
        except BaseException:
            instance.report['failure'] = 'Rehearsal did not complete; inspect private evidence before retrying'
            with (directory/'failure.log').open('x', encoding='utf8') as stream:
                os.chmod(stream.name, 0o600)
                stream.write(traceback.format_exc())
            instance.persist()
            raise
        finally:
            if not args.keep or not succeeded:
                instance.cleanup()
            instance.production_unchanged()
        instance.report.update(passed=True, finishedAt=dt.datetime.now(ZONE).isoformat(), kept=args.keep)
        instance.persist()
        print(json.dumps({'project': project, 'passed': True, 'checks': len(instance.report['checks']), 'kept': args.keep}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('run', 'cleanup'), default='run')
    parser.add_argument('--root', required=True)
    parser.add_argument('--runtime')
    parser.add_argument('--tag')
    parser.add_argument('--source-sha256')
    parser.add_argument('--project', help='Exact owned identity, required for cleanup')
    parser.add_argument('--snapshot')
    parser.add_argument('--port', type=int, default=18089)
    parser.add_argument('--keep', action='store_true', help='Keep an explicitly successful private candidate for immediate browser acceptance')
    args = parser.parse_args()
    try:
        if args.action == 'cleanup':
            root = Path(args.root)
            require(PROJECT.fullmatch(args.project or ''), 'Invalid cleanup project')
            directory = root/'rehearsals'/args.project
            require(directory.is_dir() and not any(p.is_symlink() for p in (directory, *directory.parents)), 'Invalid private rehearsal directory')
            instance = Rehearsal.__new__(Rehearsal)
            instance.directory, instance.project = directory, args.project
            instance.file = directory/'compose.json'
            require(not instance.file.is_symlink(), 'Invalid rehearsal config')
            instance.config = json.loads(instance.file.read_text())
            instance.report = json.loads((directory/'result.json').read_text())
            instance.baseline = json.loads((directory/'production-baseline.json').read_text())
            instance.ops = module('cleanup_ops', Path(__file__).with_name('monolith-ops.py'))
            with instance.ops.maintenance_lock(root):
                instance.cleanup()
                instance.production_unchanged()
            print(json.dumps({'project': args.project, 'cleaned': True}))
        else:
            require(args.tag and args.runtime and args.source_sha256, 'Run requires runtime, tag and source checksum')
            run(args)
    except Exception:
        print('Isolated application rehearsal failed; no production deployment was requested. Inspect private result.json.', file=__import__('sys').stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
