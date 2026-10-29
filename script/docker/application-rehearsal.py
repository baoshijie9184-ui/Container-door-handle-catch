#!/usr/bin/env python3
"""Build and rehearse real application upgrades against private backup copies, never production volumes."""
import argparse
import copy
import datetime as dt
import gzip
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

# A migration fixture uses the installed real Mem0 SDK and real embeddings,
# without making a paid LLM extraction part of an upgrade/rollback prerequisite.
# Live chat extraction is a separate acceptance gate.
MEMORY_SEED = '''import json,sys,hashlib
from mem0 import Memory
import main
value=json.load(sys.stdin)
config=main.get_memory_config()
config['llm']['config']['api_key']='fixture-no-llm-credential'
memory=Memory.from_config(config)
main.configure_provider_timeouts(memory)
calls=[]
def reject_llm(*args,**kwargs):
    calls.append(True)
    raise RuntimeError('The upgrade fixture must not call an LLM')
memory.llm.generate_response=reject_llm
result=memory.add(value['content'],user_id=value['owner'],agent_id='doorhandlecatch',run_id=value['session'],
                  metadata={'source':'upgrade-rehearsal','fixture_request':value['requestId']},infer=False)
assert isinstance(result,dict) and len(result.get('results',[]))==1
item=result['results'][0]
assert item.get('event')=='ADD'
stored=memory.get(item['id'])
assert stored.get('user_id')==value['owner'] and stored.get('agent_id')=='doorhandlecatch' and stored.get('run_id')==value['session']
assert stored.get('memory')==value['content'] and not calls
print(json.dumps({'memoryId':item['id'],'contentSha256':hashlib.sha256(stored['memory'].encode()).hexdigest(),'llmCalls':len(calls)}))
'''


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


def additive_replay_sql(body, column):
    """Make archived simple ADD COLUMN steps repeatable without rewriting SQL.

    Existing declarations must match type, nullability, explicit collation and
    default. This is deliberately not a general SQL parser: unknown ADD syntax
    fails closed. Stored routines and other statements remain byte-identical.
    `column` is a read-only information_schema lookup on the owned MySQL copy.
    """
    pattern = re.compile(r'^ALTER TABLE\s+([a-z][a-z0-9_]*)\s+(ADD COLUMN\s+.*?);', re.M | re.S | re.I)
    definition = re.compile(r"([a-z][a-z0-9_]*)\s+(varchar\([0-9]+\)|char\([0-9]+\)|datetime(?:\([0-9]+\))?|bigint|int)"
        r"(?:\s+COLLATE\s+([a-z0-9_]+))?\s+(NOT NULL|NULL)(?:\s+DEFAULT\s+('[A-Za-z0-9_]+'|[0-9]+))?", re.I)
    def replace(match):
        table, declarations = match.groups(); missing = []
        for declaration in re.split(r',\s*ADD COLUMN\s+', declarations.removeprefix('ADD COLUMN '), flags=re.I):
            parsed = definition.fullmatch(declaration.strip())
            require(parsed is not None, 'Unsupported archived ADD COLUMN declaration')
            name, kind, collation, nullable, default = parsed.groups()
            expected = {'type': kind.lower(), 'nullable': 'NO' if nullable.upper() == 'NOT NULL' else 'YES',
                        'default': None if default is None else default.strip("'")}
            actual = column(table, name)
            if actual is None:
                missing.append('ADD COLUMN '+declaration.strip())
            else:
                require(all(actual.get(key) == value for key, value in expected.items())
                        and (collation is None or actual.get('collation') == collation.lower()),
                        'Existing migration column differs: '+table+'.'+name)
        return 'ALTER TABLE '+table+'\n '+',\n '.join(missing)+';' if missing else ''
    return pattern.sub(replace, body)


def extract_source(archive, destination):
    with tarfile.open(archive, 'r:gz') as source:
        for entry in source:
            name = Path(entry.name)
            require(not name.is_absolute() and '..' not in name.parts and
                    not entry.name.startswith(('\\', '/')) and '\\' not in entry.name and
                    (entry.isfile() or entry.isdir()), 'Unsafe source archive entry')
        source.extractall(destination, filter='data')


def isolated_config(config, project, port, images, database, model_secret_source=None):
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
    if model_secret_source:
        secret=value.get('secrets',{}).get('model_config_master_key',{})
        require(secret.get('file')==model_secret_source,'Rehearsal key source differs from the external policy')
        secret['name']=project+'_model_config_master_key'
    validate_isolation(value, project, model_secret_source)
    return value


def validate_isolation(config, project, model_secret_source=None):
    require(bool(PROJECT.fullmatch(project)) and config.get('name') == project, 'Rehearsal project differs')
    require(not config.get('configs'), 'External Compose resources are unsupported')
    secrets=config.get('secrets',{})
    if model_secret_source:
        require(set(secrets)=={'model_config_master_key'},'Only the explicitly approved model key can be referenced')
        secret=secrets['model_config_master_key']
        require(secret.get('file')==model_secret_source and not secret.get('external') and secret.get('name')==project+'_model_config_master_key','Shared or changed rehearsal Secret rejected')
    else:
        require(not secrets,'External Compose secrets require a verified model policy')
    for kind in ('volumes', 'networks'):
        for resource in config.get(kind, {}).values():
            require(not resource.get('external') and resource.get('name', '').startswith(project+('_' if kind == 'volumes' else '-')),
                    'Shared storage or network rejected')
    for name, service in config['services'].items():
        for secret in service.get('secrets',[]):
            require(model_secret_source and name in ('backend','mem0') and isinstance(secret,dict) and secret.get('source')=='model_config_master_key' and secret.get('target','model_config_master_key') in ('model_config_master_key','/run/secrets/model_config_master_key'),'Unexpected Secret recipient rejected')
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


def compatible_runner_config(config, image, runtime):
    require(isinstance(image, str) and re.fullmatch(r'sha256:[a-f0-9]{64}', image),
            'Compatible runner must be an existing immutable image')
    require(runtime.image(image) == 2, 'Compatible runner requires the reviewed fixed release and deployment-aware journal')
    require(all(name in config['services'] for name in ('backend', 'mcp-runner', 'higress-config')),
            'Compatible runner requires the existing gateway overlay')
    value = copy.deepcopy(config)
    value['services']['mcp-runner']['image'] = image
    value['services']['mcp-runner']['environment']['MCP_FETCH_IMAGE'] = image
    value['services']['backend']['environment']['AGENT_MCP_GATEWAY_IMAGE'] = image
    value['services']['higress-config']['image'] = image
    return value


def memory_extraction_config(config, model):
    require(isinstance(model, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,127}', model),
            'Memory extraction requires a bounded model identifier')
    require('mem0' in config.get('services', {}) and isinstance(config['services']['mem0'].get('environment'), dict),
            'Existing memory service configuration required')
    value=copy.deepcopy(config)
    value['services']['mem0']['environment']['MEM0_LLM_MODEL']=model
    return value


def require_no_detection_backlog(output, group):
    rows = [line.split() for line in output.splitlines() if line.split() and line.split()[0] == group]
    require(bool(rows), 'Detection consumer offset is unknown; do not start a copied worker')
    for row in rows:
        require(len(row) >= 6 and all(part.isdigit() for part in row[2:6]) and row[3] == row[4] and int(row[5]) == 0,
                'Detection backlog or unknown offset; do not replay copied work')


def restore_candidate_volumes(instance, snapshot, manifest):
    """Label every fresh volume before probes or Compose can implicitly create it."""
    ops, project = instance.ops, instance.project
    for logical, definition in instance.config['volumes'].items():
        name = definition['name']
        ops.docker('volume', 'create', '--label', 'io.doorhandle.rehearsal='+project, name)
        original = PRODUCTION+'_'+logical
        if original not in manifest['volumes']:
            instance.check('New owned volume initialized: '+logical, True)
            continue
        common = ['run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                  '--cap-add', 'CHOWN', '--cap-add', 'FOWNER', '--cap-add', 'DAC_OVERRIDE',
                  '--security-opt', 'no-new-privileges', '--user', '0', '--mount', 'type=volume,src='+name+',dst=/target']
        file = snapshot/manifest['volumes'][original]
        with file.open('rb') as stream:
            ops.docker(*common, '-i', '--entrypoint', 'tar', manifest['images']['backend'], '-xzf', '-', '-C', '/target', input_stream=stream, timeout=600)
        actual = json.loads(ops.docker(*common, '--entrypoint', 'python3', manifest['images']['backend'], '-c', ops.SCAN_VOLUME, timeout=600))
        instance.check('Restored volume matches backup: '+logical, actual == ops.archive_files(file))


class Rehearsal:
    def __init__(self, directory, config, ops, guard, baseline, model_secret_source=None):
        self.directory, self.config, self.ops, self.guard = directory, config, ops, guard
        self.project = config['name']
        self.guard.PROJECT = self.project  # Dedicated imported module, never the production guard process.
        self.assignment_guard=module('rehearsal_assignment_guard',Path(__file__).with_name('assignment-compat.py'))
        self.mcp_guard=module('rehearsal_mcp_guard',Path(__file__).with_name('mcp-compat.py'))
        self.mcp_runtime=module('rehearsal_mcp_runtime',Path(__file__).with_name('mcp-runtime.py'))
        self.baseline = baseline
        self.model_secret_source=model_secret_source
        if model_secret_source:private_json(directory/'model-secret-reference.json',{'source':model_secret_source})
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
            validate_isolation(config, self.project, self.model_secret_source)
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
        evidence=self.directory/('bridge-'+uuid.uuid4().hex+'.json')
        receipt={'path':path,'requestId':body.get('request_id'),'session':body.get('run_id'),'status':'STARTING',
                 'startedAt':dt.datetime.now(ZONE).isoformat()}
        private_json(evidence,receipt)
        script = '''import json,os,sys,urllib.request,urllib.error
value=json.load(sys.stdin)
request=urllib.request.Request('http://127.0.0.1:8081'+value['path'],data=json.dumps(value['body']).encode(),headers={'Content-Type':'application/json','x-doorhandle-memory-token':os.environ['MEM0_BRIDGE_TOKEN']})
try:
    with urllib.request.urlopen(request,timeout=40) as response:print(response.read().decode())
except urllib.error.HTTPError as error:
    print(json.dumps({'bridgeFailure':{'type':'HTTPError','status':error.code}}))
except Exception as error:
    print(json.dumps({'bridgeFailure':{'type':type(error).__name__}}))
'''
        try:
            result=json.loads(self.ops.docker('exec','-i',self.row('mem0')['Id'],'python','-B','-c',script,
                                             data=json.dumps({'path':path,'body':body}).encode(),timeout=50))
            if 'bridgeFailure' in result:
                receipt.update(status='FAILED',failure=result['bridgeFailure']);private_json(evidence,receipt)
                raise RuntimeError('Memory bridge failed; inspect private request evidence, do not replay')
            receipt['status']='RETURNED';private_json(evidence,receipt)
            return result
        except BaseException:
            if receipt['status']=='STARTING':
                receipt['status']='UNKNOWN';private_json(evidence,receipt)
            raise

    def seed_memory(self, owner, session):
        row=self.row('mem0')
        require(row['Config']['Labels'].get('io.doorhandle.rehearsal')==self.project,'Seed ownership differs')
        value={'owner':owner,'session':session,'requestId':uuid.uuid4().hex,
               'content':'隔离升级回滚样本：质检报告先列出缺陷分类，再列出整改建议。'}
        receipt={'owner':owner,'session':session,'requestId':value['requestId'],'mode':'SDK_INFER_FALSE',
                 'contentSha256':hashlib.sha256(value['content'].encode()).hexdigest(),'status':'STARTING',
                 'startedAt':dt.datetime.now(ZONE).isoformat()}
        evidence=self.directory/'memory-seed.json';private_json(evidence,receipt)
        seed_config=copy.deepcopy(self.config);seed_config['services']['mem0']['image']=row['Image']
        helper=self.project+'-seed-'+uuid.uuid4().hex[:12]
        self.ops.docker('stop','--time','15',row['Id'],timeout=60)
        try:
            raw=self.dc('run','--rm','--no-deps','-T','--name',helper,'--entrypoint','python','mem0','-B','-c',MEMORY_SEED,
                        config=seed_config,data=json.dumps(value).encode(),timeout=90)
            result=json.loads(raw.decode().strip().splitlines()[-1])
            require(result.get('llmCalls')==0 and result.get('contentSha256')==receipt['contentSha256']
                    and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',result.get('memoryId','')),'Native memory seed was not verified')
            receipt.update(status='SUCCEEDED',**result);private_json(evidence,receipt)
            return receipt
        except BaseException:
            receipt['status']='UNKNOWN';private_json(evidence,receipt);raise
        finally:
            # The client may time out before its one-off container exits. Stop
            # that exact owned helper before allowing the main writer to return.
            ids=self.ops.docker('ps','-aq','--filter','name=^'+helper+'$').decode().split()
            if ids:
                rows=json.loads(self.ops.docker('inspect',*ids))
                require(len(rows)==1 and rows[0]['Config']['Labels'].get('io.doorhandle.rehearsal')==self.project,
                        'Native seed helper ownership differs')
                self.ops.docker('rm','-f',ids[0],timeout=40)
            self.ops.docker('start',row['Id'],timeout=45)
            deadline=time.monotonic()+180
            while not self.ops.healthy(row['Id']):
                require(time.monotonic()<deadline,'Owned memory service did not restart')
                time.sleep(1)

    def capture_memory_failure(self):
        """Private evidence only; never put memory text or provider keys in CI artifacts."""
        ids=self.ops.docker('ps','-aq','--filter','label=com.docker.compose.project='+self.project,
                            '--filter','label=com.docker.compose.service=mem0').decode().split()
        if not ids:return {'captured':True,'memoryContainerCreated':False}
        require(len(ids)==1,'Failure memory ownership is ambiguous')
        row=json.loads(self.ops.docker('inspect',ids[0]))[0]
        require(row['Config']['Labels'].get('io.doorhandle.rehearsal')==self.project,'Failure memory ownership differs')
        logs=subprocess.run(['docker','logs','--tail','150',row['Id']],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=20).stdout.decode(errors='replace')
        for item in row['Config'].get('Env',[]):
            key,_,value=item.partition('=')
            if re.search('KEY|TOKEN|SECRET|PASSWORD',key) and len(value)>=8:logs=logs.replace(value,'[REDACTED]')
        with os.fdopen(os.open(self.directory/'memory-failure.log',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w',encoding='utf8') as stream:stream.write(logs)
        self.ops.docker('stop','--time','15',row['Id'],timeout=60)
        volumes=[v for v in row.get('Mounts',[]) if v['Type']=='volume']
        require(len(volumes)==1 and volumes[0]['Name'].startswith(self.project+'_'),'Failure memory volume differs')
        volume=volumes[0]['Name'];owned=json.loads(self.ops.docker('volume','inspect',volume))[0]
        require(owned.get('Labels',{}).get('io.doorhandle.rehearsal')==self.project,'Failure volume ownership differs')
        target=self.directory/'memory-failure.tar.gz'
        limit=min(512*1024**2,shutil.disk_usage(self.directory).free-2*1024**3)
        require(limit>1024**2,'Insufficient space to preserve failure evidence')
        with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as stream:
            self.ops.docker('run','--rm','--network','none','--read-only','--cap-drop','ALL','--cap-add','DAC_OVERRIDE',
                '--security-opt','no-new-privileges','--user','0','--mount','type=volume,src='+volume+',dst=/source,readonly',
                '--entrypoint','tar',self.baseline_image(),'-czf','-','-C','/source','.',output=stream,timeout=120,file_limit=limit)
        with gzip.open(target,'rb') as stream:
            while stream.read(1024*1024):pass
        return {'captured':True,'memoryContainerCreated':True,'snapshotSha256':self.ops.digest(target)}

    def baseline_image(self):
        image=next(row['image'] for row in self.baseline if row['service']=='backend')
        require(re.fullmatch(r'sha256:[a-f0-9]{64}',image),'Failure helper image is invalid')
        return image

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

    def activate(self, images, label, assignment_writes=None, mcp_writes=None):
        config = copy.deepcopy(self.config)
        for service in ('backend', 'nginx', 'mem0'):
            config['services'][service]['image'] = images[service]
        if assignment_writes is not None:
            config['services']['backend']['environment']['DETECTION_ASSIGNMENT_WRITES_ENABLED']=str(assignment_writes).lower()
        if mcp_writes is not None:
            config['services']['backend']['environment']['AGENT_MCP_WRITES_ENABLED']=str(mcp_writes).lower()
        # The rehearsal already holds the deployment maintenance lock. Check metadata before
        # the memory helper quiesces any writer; a copied database is not exempt from its floor.
        assignment=self.assignment_guard.guard(self.state,config,project=self.project,pin=True)
        if self.model_secret_source:
            for service in ('backend','mem0'):
                image=json.loads(self.ops.docker('image','inspect',images[service]))[0]
                require(image.get('Config',{}).get('Labels',{}).get('io.doorhandle.model-config-format')=='1','Rehearsal rollback image does not support governed credentials')
        try:
            runtime=self.mcp_runtime.prepare(self.state,config,project=self.project)
            if runtime['action']!='disabled':
                override=self.mcp_runtime.private_read(self.state,self.mcp_runtime.OVERRIDE)['services']
                config['services']['mcp-runner']=override['mcp-runner']
                config['services']['backend']['environment'].update(override['backend']['environment'])
                self.mcp_runtime.applying(self.state,project=self.project)
                self.dc('up','-d','--no-deps','--no-build','--pull','never','--wait','--wait-timeout','120','mcp-runner',config=config,timeout=150)
                runtime=self.mcp_runtime.verify(self.state,project=self.project)
            mcp=self.mcp_guard.guard(self.state,config,project=self.project,pin=True)
        except Exception:
            if (self.state/self.mcp_runtime.PRIVATE).exists():
                pending=self.mcp_runtime.private_read(self.state,self.mcp_runtime.PRIVATE)
                if pending.get('phase') in ('PREPARING','PREPARED','APPLYING','NEEDS_REVIEW'):
                    self.mcp_runtime.recover(self.state,project=self.project)
            raise
        mode = self.guard.prepare(self.state, config)
        record = self.guard.read_json(self.state/'memory-transition.json')
        config['services']['mem0']['image'] = record['selectedImage']
        if mode == 'replace':
            self.dc('up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '240', 'mem0', config=config, timeout=270)
        self.guard.verify(self.state)
        self.dc('up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '240', 'backend', config=config, timeout=270)
        self.dc('up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--force-recreate', '--wait', '--wait-timeout', '90', 'nginx', config=config, timeout=120)
        self.check(label+' uses the requested real backend', self.row('backend')['Image'] == images['backend'])
        runtime=self.mcp_runtime.finalize(self.state,project=self.project)
        self.report.setdefault('transitions', []).append({'label': label, 'memoryPreserved': mode == 'preserve',
                                                        'requiredProtocol': record['requiredProtocol'], 'backend': images['backend'],
                                                        'assignmentRequired':assignment['required'],'assignmentWrites':assignment['assignmentWrites'],
                                                        'nativeMcpRequired':mcp['required'],'mcpWrites':mcp['writesEnabled'],'mcpCompatibilityDeclaredOnly':True,
                                                        'runnerAction':runtime['action'],'runnerProtocol':runtime['requiredProtocol'],'runnerPoolVerified':runtime['poolVerified']})
        self.persist()
        return config

    def verify_dispatch_index(self):
        sql = "SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='agent_conversation_input' AND INDEX_NAME='idx_conversation_input_dispatch_owner';"
        return self.ops.db(self.row('mysql')['Id'], sql).strip() == 'status,user_id,id'

    def migrate_candidate(self, source):
        # Fixed additive migrations on the owned copy only; production publishing never invokes this.
        # Verify the entire source plan before the first database operation.
        file = source/'sql/mysql/migration-V39-conversation-owner-dispatch.sql'
        mirror = source/'doorhandle-module-app/src/main/resources/db/migration-V39-conversation-owner-dispatch.sql'
        require(file.read_bytes() == mirror.read_bytes(), 'Candidate V39 migration copies differ')
        plan = []
        for version in range(40, 67):
            files = list((source/'sql/mysql').glob('migration-V'+str(version)+'-*.sql'))
            require(len(files) == 1 and not files[0].is_symlink(), 'Candidate migration source missing or ambiguous: V'+str(version))
            mirrors = list(source.glob('doorhandle-*/src/main/resources/db/'+files[0].name))
            require(len(mirrors) == 1 and not mirrors[0].is_symlink() and files[0].read_bytes() == mirrors[0].read_bytes(),
                    'Candidate V'+str(version)+' migration copies differ')
            plan.append(files[0])
        def column(table, name):
            # Identifiers are accepted only by the trusted declaration parser.
            raw = self.ops.db(self.row('mysql')['Id'],
                "SELECT JSON_OBJECT('type',COLUMN_TYPE,'nullable',IS_NULLABLE,'default',COLUMN_DEFAULT,'collation',COLLATION_NAME) "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='"+table+"' AND COLUMN_NAME='"+name+"';").strip()
            return json.loads(raw) if raw else None
        self.verify_model_fact_columns(complete=False)
        # Validate every pre-existing ADD declaration before executing any DDL.
        prepared = [(migration, additive_replay_sql(migration.read_text(encoding='utf8'), column)) for migration in plan]
        existing = self.ops.db(self.row('mysql')['Id'], "SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='agent_conversation_input' AND INDEX_NAME='idx_conversation_input_dispatch_owner';").strip()
        if existing == '0':
            self.ops.db(self.row('mysql')['Id'], file.read_text(encoding='utf8'))
        self.check('Candidate V39 adds only the expected dispatch index', self.verify_dispatch_index())
        for migration, body in prepared:
            self.report['migrationAttempt'] = migration.name
            self.persist()
            self.ops.db(self.row('mysql')['Id'], body)
            self.report.setdefault('completedMigrations', []).append(migration.name)
            self.persist()
        self.verify_model_fact_columns(complete=True)
        self.report['candidateMigrations'] = [migration.name for migration in (file, *plan)]
        self.check('Owned candidate copy applied V40-V66 and retains the expected nullable model facts', True)

    def verify_model_fact_columns(self, *, complete):
        expected = {'training_image_count': 'int', 'training_completed_at': 'datetime',
                    'evaluation_image_count': 'int', 'no_detection_image_count': 'int', 'inference_fps': 'decimal(12,4)'}
        names = ','.join("'"+name+"'" for name in expected)
        sql = "SELECT COLUMN_NAME,LOWER(COLUMN_TYPE),IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='model_management' AND COLUMN_NAME IN ("+names+");"
        found = {}
        for line in self.ops.db(self.row('mysql')['Id'], sql).splitlines():
            parts = line.split('\t')
            require(len(parts) == 3 and parts[0] in expected and parts[0] not in found, 'Candidate model fact metadata unavailable')
            name, kind, nullable = parts
            kind = 'int' if kind == 'int(11)' else kind
            require(kind == expected[name] and nullable == 'YES', 'Candidate V62 existing column type differs: '+name)
            found[name] = kind
        require(not complete or found.keys() == expected.keys(), 'Candidate V62 model fact columns incomplete')

    def cleanup(self):
        # Re-read labels, and revalidate the exact private config before deleting owned copies.
        validate_isolation(self.config, self.project, self.model_secret_source)
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
    session='rehearsal-'+uuid.uuid4().hex
    seeded=run.seed_memory(owner,session)
    run.report.update(memoryFixtureMode='SDK_INFER_FALSE',memoryExtractionVerified=False)
    run.check('Real Mem0 SDK fixture persists without an LLM extraction',seeded['status']=='SUCCEEDED' and seeded['llmCalls']==0)
    rows = client.request('GET', '/api/agent/memories')['items']
    row = next((item for item in rows if item['id']==seeded['memoryId'] and item['sourceSessionId'] == session), None)
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


def verify_rollback_bridge(run, original_container, requested_image):
    """Verify the guard's real decision for both old and compatible baselines."""
    record = run.guard.read_json(run.state/'memory-transition.json')
    current = run.row('mem0')
    require(record.get('phase') == 'VERIFIED' and
            record['selectedProtocol'] >= record['requiredProtocol'] and
            current['Image'] == record['selectedImage'] and
            current['State'].get('Health', {}).get('Status') == 'healthy',
            'Rollback memory bridge is not the verified compatible selection')
    if record['preserved']:
        run.check('Legacy rollback retains the exact compatible memory bridge',
                  current['Id'] == original_container == record['originalContainer'])
    else:
        expected, protocol = run.guard.image(requested_image)
        run.check('Compatible rollback uses its requested healthy memory image',
                  current['Image'] == expected and protocol >= record['requiredProtocol'])


def initial_reader_config(config, observed, capabilities, mcp_reader):
    """Start a new copy as a reader before enabling any new protocol writers.

    An empty candidate state cannot inherit production pins: those are bound to
    the production MySQL volume. Keep every reader required by restored data,
    pause compatible write gates, and defer unused format features until an
    actual compatible baseline container exists. The normal guards still run.
    """
    require(set(observed) == set(capabilities) and
            set(observed) == {'json', 'identity', 'scope', 'review', 'evidence', 'context'},
            'Incomplete initial reader format evidence')
    require(all(type(level) is int and 0 <= level <= capabilities[key]
                for key, level in observed.items()), 'Baseline cannot read restored format')
    value = copy.deepcopy(config)
    environment = value['services']['backend']['environment']
    if capabilities['json'] == 2:
        environment['DETECTION_ASSIGNMENT_WRITES_ENABLED'] = 'false'
    if mcp_reader >= 2:
        environment['AGENT_MCP_WRITES_ENABLED'] = 'false'
    if not observed['scope']:
        environment['DETECTION_STABLE_IDENTITY_ENABLED'] = 'false'
    if not observed['review']:
        environment['DETECTION_IDENTITY_REVIEW_ENABLED'] = 'false'
    if not observed['evidence']:
        environment['DETECTION_IDENTITY_EVIDENCE_ENABLED'] = 'false'
        environment['DETECTION_IDENTITY_RECONCILIATION_ENABLED'] = 'false'
    if observed['evidence'] < 2:
        environment['DETECTION_IDENTITY_MISSING_NAME_REVIEW_ENABLED'] = 'false'
    if not observed['context']:
        environment['AGENT_DURABLE_CONTEXT_ENABLED'] = 'false'
        environment['AGENT_CONTEXT_OFFLOAD_ENABLED'] = 'false'
    return value


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
        key_helper=ops.model_secret_helper()
        key_setting=key_helper.load_settings(root,runtime)
        if key_setting:key_helper.verify_reference(root,runtime,manifest.get('modelKeyEscrow',{}))
        require(not manifest.get('modelKeyEscrow',{}).get('enabled') or key_setting is not None,'Encrypted candidate data requires its external key policy')
        model_secret_source=key_setting['masterKeyFile'] if key_setting else None
        assignment_preflight=module('rehearsal_assignment_preflight',Path(__file__).with_name('assignment-compat.py'))
        assignment_preflight.private_state(root/'state')
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
        if model_secret_source:
            env['MODEL_CONFIG_MASTER_KEY_SOURCE']=model_secret_source
            command+=['-f',str(source/'compose.model-config.yml')]
        config = json.loads(ops.docker(*command, 'config', '--format', 'json', env=env))
        config = isolated_config(config, project, args.port, manifest['images'], manifest['databaseName'], model_secret_source)
        memory_environment=config['services']['mem0'].get('environment',{})
        original_memory_model=memory_environment.get('MEM0_LLM_MODEL') or memory_environment.get('DASHSCOPE_MODEL')
        memory_model=getattr(args,'memory_extraction_model',None)
        if memory_model:
            config=memory_extraction_config(config,memory_model)
        assignment_guard=module('rehearsal_assignment_input',Path(__file__).with_name('assignment-compat.py'))
        desired_assignment_writes=assignment_guard.boolean(config['services']['backend']['environment'],'DETECTION_ASSIGNMENT_WRITES_ENABLED',True)
        mcp_guard=module('rehearsal_mcp_input',Path(__file__).with_name('mcp-compat.py'))
        desired_mcp_writes=mcp_guard.flag(config['services']['backend']['environment'],'AGENT_MCP_WRITES_ENABLED',True)
        original_backend=mcp_guard.common.container(PRODUCTION,'backend')
        require(original_backend['Image']==manifest['images']['backend'],'Backend changed after the selected backup; refresh the rehearsal baseline')
        _,original_mcp_capability=mcp_guard.capability(original_backend['Image'])
        baseline_mcp_writes=mcp_guard.flag(mcp_guard.common.environment(original_backend),'AGENT_MCP_WRITES_ENABLED',True) if original_mcp_capability>=2 else True
        config['services']['backend']['environment']['AGENT_MCP_WRITES_ENABLED']=str(baseline_mcp_writes).lower()
        if args.compatible_backend_image:
            require(re.fullmatch(r'sha256:[a-f0-9]{64}',args.compatible_backend_image),'Compatible baseline must be an existing immutable backend image')
            baseline_id,baseline_capabilities=assignment_guard.image(args.compatible_backend_image)
            require(baseline_id==args.compatible_backend_image and baseline_capabilities['json']==2 and baseline_capabilities['identity']==1,'Baseline does not declare current assignment readers')
            config['services']['backend']['image']=baseline_id
            config['services']['backend']['environment']['DETECTION_ASSIGNMENT_WRITES_ENABLED']='false'
            _,mcp_capability=mcp_guard.capability(baseline_id)
            require(mcp_capability>=2,'A paused compatible baseline must declare the native MCP protocol and write gate')
            config['services']['backend']['environment']['AGENT_MCP_WRITES_ENABLED']='false'
            baseline_mcp_writes=False
        compatible_runner = getattr(args, 'compatible_runner_image', None)
        if compatible_runner:
            runner_guard=module('rehearsal_compatible_runner',Path(__file__).with_name('mcp-runtime.py'))
            config=compatible_runner_config(config,compatible_runner,runner_guard)
        if model_secret_source:
            for service in ('backend','mem0'):
                old_image=json.loads(ops.docker('image','inspect',config['services'][service]['image']))[0]
                require(old_image.get('Config',{}).get('Labels',{}).get('io.doorhandle.model-config-format')=='1','Governed data requires a compatible baseline before any copied application is started')
        instance = Rehearsal(directory, config, ops, guard, baseline, model_secret_source)
        instance.report.update(snapshot=snapshot.name, release=args.tag, sourceSha256=args.source_sha256, port=args.port)
        instance.report.update(originalBackendImage=manifest['images']['backend'],compatibleBaselineBackend=config['services']['backend']['image'],assignmentBaselinePaused=bool(args.compatible_backend_image),mcpBaselinePaused=not baseline_mcp_writes)
        instance.report.update(originalRunnerImage=manifest['images'].get('mcp-runner'),
                               compatibleBaselineRunner=compatible_runner)
        instance.report.update(originalMemoryExtractionModel=original_memory_model,
                               selectedMemoryExtractionModel=memory_model or original_memory_model)
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
            _,candidate_capabilities=assignment_guard.image(candidate['backend'])
            _,baseline_capabilities=assignment_guard.image(config['services']['backend']['image'])
            intended_environment={**config['services']['backend']['environment'],'DETECTION_ASSIGNMENT_WRITES_ENABLED':str(desired_assignment_writes).lower()}
            intended=assignment_guard.potential(intended_environment,candidate_capabilities)
            require(all(baseline_capabilities[key]>=intended[key] for key in intended),'Prepare a compatible baseline before a rehearsal that activates new assignment formats')
            _,candidate_mcp=mcp_guard.capability(candidate['backend'])
            _,baseline_mcp=mcp_guard.capability(config['services']['backend']['image'])
            intended_mcp={**config['services']['backend']['environment'],'AGENT_MCP_WRITES_ENABLED':str(desired_mcp_writes).lower()}
            require(candidate_mcp>=mcp_guard.potential(intended_mcp) and baseline_mcp>=mcp_guard.potential(intended_mcp),'Prepare a compatible MCP baseline before activating native writers in rehearsal')
            if args.compatible_backend_image:
                require(candidate['backend']!=args.compatible_backend_image,'A candidate image cannot count as its own previous-version rollback evidence')
            instance.check('Three candidate images built from production Dockerfiles', True)
            print(json.dumps({'project': project, 'phase': 'RESTORING'}), flush=True)
            restore_candidate_volumes(instance, snapshot, manifest)
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
            if ops.db(mysql,"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='agent_mcp_execution';").strip()=='1':
                checks.append("SELECT COUNT(*) FROM agent_mcp_execution WHERE state<>'REMOVED'")
            instance.check('Backup has no automatically executable Agent or installation work', all(ops.db(mysql, sql).strip() == '0' for sql in checks))
            if 'mcp-runner' in config['services']:
                logical=next(value['source'] for value in config['services']['mcp-runner']['volumes'] if value['target']=='/var/lib/doorhandle-mcp')
                journal=instance.mcp_runtime.probe({'State':{'Running':False}},config['volumes'][logical]['name'],config['services']['mcp-runner']['image'])
                storage = 'Restored' if PRODUCTION+'_'+logical in manifest['volumes'] else 'New'
                instance.check(storage+' runner journal has no executable resources that could target production containers',journal['pending']==0)
            instance.dc('up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '180', 'kafka', timeout=210)
            group = config['services']['detection-worker']['environment']['KAFKA_CONSUMER_GROUP']
            require(isinstance(group, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', group), 'Unexpected detection consumer group')
            offsets = ops.docker('exec', instance.row('kafka')['Id'], '/opt/kafka/bin/kafka-consumer-groups.sh',
                                 '--bootstrap-server', 'kafka:9092', '--describe', '--group', group, timeout=45).decode()
            require_no_detection_backlog(offsets, group)
            instance.check('Restored Kafka has committed zero-lag worker offsets; copied detection is not replayed', True)
            if args.compatible_backend_image:
                # The independent reader baseline is newer than the production backup
                # and can require additive tables even while its write gates are paused.
                instance.migrate_candidate(source)
                instance.report['migrationStage'] = 'BEFORE_COMPATIBLE_BASELINE'
                instance.persist()
            observed = assignment_guard.data_floor(assignment_guard.container(project, 'mysql'))
            reader_config = initial_reader_config(config, observed, baseline_capabilities, baseline_mcp)
            instance.report['initialReader'] = {'observedAssignmentFloor': observed,
                'assignmentWrites': assignment_guard.boolean(reader_config['services']['backend']['environment'], 'DETECTION_ASSIGNMENT_WRITES_ENABLED', True),
                'mcpWrites': mcp_guard.flag(reader_config['services']['backend']['environment'], 'AGENT_MCP_WRITES_ENABLED', True)}
            instance.persist()
            assignment_guard.guard(instance.state,reader_config,project=project,pin=True,allow_initial=True)
            mcp_guard.guard(instance.state,reader_config,project=project,pin=True,allow_initial=True)
            instance.dc('up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '240', config=reader_config, timeout=420)
            smoke(instance, args.port)
            marker = upload_marker(args.port)
            private_json(directory/'marker.json', marker)
            if not args.compatible_backend_image:
                instance.migrate_candidate(source)
                instance.report['migrationStage'] = 'AFTER_ORIGINAL_BASELINE'
                instance.persist()
            print(json.dumps({'project': project, 'phase': 'UPGRADING'}), flush=True)
            instance.activate(candidate, 'Upgrade',assignment_writes=desired_assignment_writes,mcp_writes=desired_mcp_writes)
            smoke(instance, args.port, marker)
            memory = memory_marker(instance, args.port)
            upgraded_memory = instance.row('mem0')['Id']
            print(json.dumps({'project': project, 'phase': 'ROLLING_BACK'}), flush=True)
            rollback_images = dict(manifest['images'])
            rollback_images['backend'] = config['services']['backend']['image']
            instance.activate(rollback_images, 'Rollback', assignment_writes=False if args.compatible_backend_image else desired_assignment_writes,mcp_writes=baseline_mcp_writes)
            instance.check('Application rollback preserves the additive V39 index', instance.verify_dispatch_index())
            smoke(instance, args.port, marker)
            verify_rollback_bridge(instance, upgraded_memory, rollback_images['mem0'])
            verify_memory_marker(instance, args.port, memory, legacy=True)
            current_config = instance.activate(candidate, 'Candidate reactivation', assignment_writes=desired_assignment_writes,mcp_writes=desired_mcp_writes)
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
            try:
                instance.report['failureEvidence']=instance.capture_memory_failure()
            except BaseException:
                # An unknown result must remain inspectable even if its private
                # archive cannot be exported. The failed copy is never promoted.
                instance.report['failureEvidence']={'captured':False}
            instance.persist()
            raise
        finally:
            preserve_failure=not succeeded and instance.report.get('failureEvidence',{}).get('captured') is False
            if preserve_failure:
                instance.report.update(kept=True,retainedForEvidence=True);instance.persist()
            elif not args.keep or not succeeded:
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
    parser.add_argument('--compatible-backend-image')
    parser.add_argument('--compatible-runner-image')
    parser.add_argument('--memory-extraction-model')
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
            secret_reference=directory/'model-secret-reference.json'
            require(not secret_reference.is_symlink(),'Invalid private model Secret reference')
            instance.model_secret_source=json.loads(secret_reference.read_text())['source'] if secret_reference.exists() else None
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
