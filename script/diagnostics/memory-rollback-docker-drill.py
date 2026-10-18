"""Exercise the real compatibility guard on an isolated Linux Docker project and new volumes."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--execute', action='store_true')
parser.add_argument('--directory', required=True)
parser.add_argument('--base-image', required=True)
args = parser.parse_args()
source = Path(__file__).resolve().parent
directory = Path(args.directory).resolve()
if sys.platform != 'linux' or not args.execute or directory.exists() or not directory.is_relative_to(source):
    parser.error('Use Linux, --execute, and a fresh directory below this isolated source directory')
if not re.fullmatch(r'sha256:[a-f0-9]{64}', args.base_image):
    parser.error('Use an existing pinned image digest')
directory.mkdir(mode=0o700)
state = directory / 'state'
state.mkdir(mode=0o700)
run_id = uuid.uuid4().hex[:12]
project = 'doorhandle-memory-drill-' + run_id
label = 'doorhandle.memory.drill=' + run_id
report = {'at': datetime.now(timezone(timedelta(hours=8))).isoformat(), 'runId': run_id, 'checks': [], 'passed': False,
          'productionDeploymentExecuted': False, 'providerMode': 'offline scripted, actual installed SDK and Docker'}
resources, volumes = [], []
image_name = 'doorhandlecatch/memory-drill:' + run_id
token = secrets.token_hex(32)

def save():
    (directory / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')

def run(*cmd, timeout=60, check=True, stdin=None, pass_fds=(), env=None):
    value = subprocess.run(cmd, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, pass_fds=pass_fds, env=env)
    if check and value.returncode:
        # Keep diagnostics private; never print container environments or tokens.
        with (directory / 'last-failure.txt').open('ab') as stream:
            stream.write(value.stdout + b'\n' + value.stderr + b'\n')
        raise RuntimeError('Isolated command failed; review private last-failure.txt')
    return value

def docker(*cmd, **kwargs):
    return run('docker', *cmd, **kwargs).stdout.decode().strip()

def inspect(container):
    return json.loads(docker('inspect', container))[0]

def check(name, value=True):
    if not value:
        raise AssertionError(name)
    report['checks'].append(name)
    save()
    print(name, flush=True)

def owned(row):
    return (row.get('Config', {}).get('Labels') or row.get('Labels') or {}).get('doorhandle.memory.drill') == run_id

def remove(name):
    row = inspect(name)
    if not owned(row):
        raise RuntimeError('Refuse cleanup of a foreign container')
    docker('rm', '-f', name)
    resources.remove(name)

def start(service, image, command=(), volume=None, liar=False):
    name = project + '-' + service
    command_line = ['run', '-d', '--pull', 'never', '--name', name, '--label', label,
                    '--label', 'com.docker.compose.project=' + project, '--label', 'com.docker.compose.service=' + service,
                    '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                    '--user', '10001:10001', '--memory', '512m', '--cpus', '1', '--pids-limit', '128',
                    '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m', '--env', 'HOME=/tmp', '--env', 'MEM0_DATA_DIR=/data',
                    '--env', 'MEM0_TELEMETRY=false', '--env', 'ANONYMIZED_TELEMETRY=false']
    if volume:
        command_line += ['--mount', 'type=volume,src=' + volume + ',dst=/data']
    if service == 'mem0' and not command:
        command_line += ['--env', 'DOORHANDLE_ROLLBACK_DRILL=offline-isolated', '--env', 'MEM0_BRIDGE_TOKEN=' + token,
                         '--health-interval', '1s', '--health-timeout', '3s', '--health-retries', '20',
                         '--health-cmd', 'python -c "import urllib.request;urllib.request.urlopen(\'http://127.0.0.1:8081/health\',timeout=2)"']
        command = ('python', '-B', '/app/memory-rollback-fixture.py') + (('--lie-about-health',) if liar else ())
    else:
        command_line += ['--no-healthcheck']
    command_line += ['--entrypoint', command[0], image, *command[1:]]
    docker(*command_line)
    resources.append(name)
    return name

def healthy(name):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        row = inspect(name)
        if not row['State']['Running']:
            (directory / 'bridge-failure.log').write_text(docker('logs', name), encoding='utf8')
            raise RuntimeError('Isolated bridge exited; inspect private log')
        if row['State'].get('Health', {}).get('Status') == 'healthy':
            return
        time.sleep(1)
    raise RuntimeError('Isolated health timeout; do not restart this drill blindly')

def api(path, body, protocol='2'):
    # Runs entirely in this network-less container, using real HTTP middleware.
    code = """import json,os,sys,urllib.request
body=json.loads(sys.stdin.read())
r=urllib.request.Request('http://127.0.0.1:8081'+body['path'],data=json.dumps(body['body']).encode(),headers={'Content-Type':'application/json','X-Doorhandle-Memory-Token':os.environ['MEM0_BRIDGE_TOKEN'],'X-Doorhandle-Memory-Protocol':body['protocol']})
print(urllib.request.urlopen(r,timeout=10).read().decode())
"""
    return json.loads(docker('exec', '-i', memory, 'python', '-B', '-c', code,
                            stdin=json.dumps({'path': path, 'body': body, 'protocol': protocol}).encode()))

runner = """import importlib.util,sys
s=importlib.util.spec_from_file_location('guard',sys.argv.pop(1));g=importlib.util.module_from_spec(s);s.loader.exec_module(g)
g.PROJECT=sys.argv.pop(1)
g.main()
"""
def guard(action, target=None, expect=0):
    result = run(sys.executable, '-c', runner, str(source / 'memory-compat.py'), project, action, '--state', str(state), '--lock-fd', str(lock.fileno()),
                 stdin=json.dumps({'services': {'mem0': {'image': target}}}).encode() if target else None,
                 pass_fds=(lock.fileno(),), timeout=120, check=False)
    if result.returncode != expect:
        (directory / 'guard-failure.log').write_bytes(result.stdout + b'\n' + result.stderr)
        transition = state / 'memory-transition.json'
        if transition.exists() and json.loads(transition.read_text()).get('phase') == 'FAILED':
            spec = importlib.util.spec_from_file_location('diagnostic_guard', source / 'memory-compat.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            probe = module.PROBE.replace('except Exception:\n', 'except Exception as error:\n import traceback;traceback.print_exc()\n')
            probe_result = run('docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                               '--security-opt', 'no-new-privileges', '--user', '10001:10001', '--env', 'MEM0_DATA_DIR=/data',
                               '--mount', 'type=volume,src=' + volume + ',dst=/data,readonly', '--entrypoint', 'python', compatible, '-B', '-c', probe,
                               check=False)
            (directory / 'readonly-probe-failure.log').write_bytes(probe_result.stdout + b'\n' + probe_result.stderr)
        raise AssertionError('Unexpected real guard exit: ' + str(result.returncode))
    return result.stdout.decode().strip()

def snapshot_production():
    ids = docker('ps', '-aq', '--filter', 'label=com.docker.compose.project=doorhandlecatch-monolith').split()
    return {row['Id']: {'image': row['Image'], 'running': row['State']['Running'], 'healthy': row['State'].get('Health', {}).get('Status')}
            for row in json.loads(docker('inspect', *ids))}

baseline = snapshot_production()
report['productionBefore'] = baseline
lock = (state / 'deploy.lock').open('a')
fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
try:
    docker('image', 'inspect', args.base_image)
    # Reuse installed dependencies without any download, overlay only project-owned source.
    # The legacy local builder accepts a content ID directly. BuildKit treats
    # sha256:... as a registry reference and attempts Docker Hub resolution.
    # No RUN or package installation is needed; uploaded sources are mode 0644.
    (source / 'Dockerfile.drill').write_text('FROM ' + args.base_image + '\nLABEL io.doorhandle.memory-protocol="2"\nCOPY main.py write_receipts.py lifecycle.py duplicate_review.py memory-rollback-fixture.py /app/\n', encoding='utf8')
    docker('build', '--pull=false', '--network=none', '--label', label, '-f', str(source / 'Dockerfile.drill'), '-t', image_name, str(source), timeout=120,
           env={**os.environ, 'DOCKER_BUILDKIT': '0'})
    compatible = json.loads(docker('image', 'inspect', image_name))[0]['Id']
    report.update(baseImage=args.base_image, compatibleImage=compatible)
    volume = project + '-data'
    docker('volume', 'create', '--label', label, volume)
    volumes.append(volume)
    # Docker initializes the new volume from the existing image's /data ownership.
    sleeper = ('python', '-c', 'import signal,sys,time;signal.signal(signal.SIGTERM,lambda *args:sys.exit(0));time.sleep(1800)')
    backend = start('backend', args.base_image, sleeper)
    memory = start('mem0', args.base_image, sleeper, volume)
    check('Empty new volume permits compatible upgrade', guard('prepare', compatible) == 'replace')
    check('Upgrade quiesces backend and original bridge', not inspect(backend)['State']['Running'] and not inspect(memory)['State']['Running'])
    remove(memory)
    memory = start('mem0', compatible, volume=volume)
    healthy(memory)
    guard('verify')
    check('Actual HTTP protocol and image/volume verify before backend activation', json.loads((state / 'memory-transition.json').read_text())['phase'] == 'VERIFIED')
    docker('start', backend)
    owner = {'user_id': 'doorhandlecatch:user:990001', 'app_id': 'doorhandlecatch'}
    items = api('/memories/owned/list', owner)['data']['items']
    by_name = {item['memory'].rsplit(' ', 1)[-1]: item for item in items}
    for name in ['excluded', 'expired']:
        item = by_name[name]
        expires = (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat() if name == 'expired' else None
        api('/memories/owned/lifecycle', {**owner, 'memory_id': item['id'], 'expected_digest': item['digest'], 'expected_revision': 0,
                                       'state': 'EXCLUDED' if name == 'excluded' else 'ACTIVE', 'expires_at': expires, 'auto_delete': False})
    time.sleep(2.1)
    operation = {**owner, 'run_id': 'drill-request', 'request_id': 'stable-drill-request', 'content': 'Offline persisted receipt fixture'}
    original_receipt = api('/memories/add', operation)['data']['operation']
    check('Native write commits a persistent receipt', original_receipt['status'] == 'SUCCEEDED')
    original_id = inspect(memory)['Id']
    check('Old target preserves compatible container after reading actual governed volume', guard('prepare', args.base_image) == 'preserve')
    healthy(memory)
    guard('verify')
    record = json.loads((state / 'memory-transition.json').read_text())
    check('Rollback retains exact container image and volume with protocol floor two', record['preserved'] and record['requiredProtocol'] == 2 and inspect(memory)['Id'] == original_id)
    check('Backend stays stopped throughout verification', not inspect(backend)['State']['Running'])
    docker('start', backend)
    retrieved = api('/memories/search', {**owner, 'run_id': 'other-session', 'scope': 'ACCOUNT', 'query': 'fixture', 'top_k': 20}, protocol='0')['data']
    ids = {row['id'] for row in retrieved}
    check('Old protocol search still excludes disabled and expired memories', by_name['active']['id'] in ids and all(by_name[name]['id'] not in ids for name in ['excluded', 'expired']))
    old_items = api('/memories/owned/list', owner, protocol='0')['data']['items']
    check('Old DTO omits lifecycle while stored original content is retained', len(old_items) == 4 and all(set(row) == {'id', 'memory', 'sourceSessionId', 'createdAt', 'updatedAt', 'digest'} for row in old_items))
    replay = api('/memories/add', operation)['data']['operation']
    count = docker('exec', memory, 'python', '-c', "from pathlib import Path;print(len(Path('/data/native-add-calls.jsonl').read_text().splitlines()))")
    check('Same receipt after actual stop/start does not replay native write', replay['status'] == 'SUCCEEDED' and count == '1')

    check('Prepare again retains compatible bridge', guard('prepare', args.base_image) == 'preserve')
    docker('start', backend)
    guard('verify', expect=6)
    check('Premature backend activation is detected and stopped', not inspect(backend)['State']['Running'])
    guard('verify')

    check('Compatible target selects controlled replacement', guard('prepare', compatible) == 'replace')
    remove(memory)
    memory = start('mem0', compatible, volume=volume, liar=True)
    healthy(memory)
    guard('verify', expect=6)
    check('Image label cannot override an incompatible real HTTP protocol', not inspect(memory)['State']['Running'] and not inspect(backend)['State']['Running'])
    remove(memory)
    memory = start('mem0', compatible, volume=volume)
    healthy(memory)
    guard('verify')
    check('Compatible recovery succeeds without discarding original data', len(api('/memories/owned/list', owner)['data']['items']) == 4)
    check('Monotone protocol requirement remains two', json.loads((state / 'memory-minimum.json').read_text())['requiredProtocol'] == 2)
    # A new, empty volume must not lower the durable requirement or silently
    # replace the original governed data, even with a valid compatible image.
    other_volume = project + '-wrong-data'
    docker('volume', 'create', '--label', label, other_volume)
    volumes.append(other_volume)
    remove(memory)
    memory = start('mem0', compatible, volume=other_volume)
    healthy(memory)
    guard('prepare', args.base_image, expect=6)
    check('Different empty volume cannot bypass durable original-volume identity',
          not inspect(memory)['State']['Running'] and json.loads((state / 'memory-minimum.json').read_text())['dataMount']['name'] == volume)
    remove(memory)
    memory = start('mem0', compatible, volume=volume)
    healthy(memory)
    guard('prepare', compatible)
    docker('start', memory)
    healthy(memory)
    guard('verify')
    check('Original governed volume remains recoverable after wrong-volume rejection', len(api('/memories/owned/list', owner)['data']['items']) == 4)

    # Keep a genuinely committed, uncheckpointed WAL alive on a separate new
    # volume, then use the same read-only Docker probe as the actual guard.
    wal_volume = project + '-wal'
    docker('volume', 'create', '--label', label, wal_volume)
    volumes.append(wal_volume)
    wal_code = """import sqlite3,signal,sys,time
from pathlib import Path
p=Path('/data/bridge_receipts');p.mkdir()
d=sqlite3.connect(p/'write-receipts.sqlite3');d.execute('PRAGMA journal_mode=WAL');d.execute('PRAGMA wal_autocheckpoint=0')
d.execute('CREATE TABLE memory_write_receipt(id TEXT)');d.execute('CREATE TABLE memory_lifecycle(memory_id TEXT)');d.commit();d.execute('PRAGMA wal_checkpoint(TRUNCATE)')
d.execute("INSERT INTO memory_lifecycle VALUES('offline-fixture')");d.commit();(p/'ready').touch()
signal.signal(signal.SIGTERM,lambda *a:sys.exit(0))
try:time.sleep(120)
finally:d.close()
"""
    wal_helper = start('wal-fixture', compatible, ('python', '-c', wal_code), wal_volume)
    deadline = time.monotonic() + 10
    ready_code = "from pathlib import Path;import sys;sys.exit(0 if Path('/data/bridge_receipts/ready').exists() else 1)"
    while run('docker', 'exec', wal_helper, 'python', '-c', ready_code, check=False).returncode:
        if time.monotonic() > deadline:
            raise AssertionError('Isolated WAL fixture did not become ready')
        time.sleep(.2)
    hashes_code = "import hashlib,json;from pathlib import Path;p=Path('/data/bridge_receipts');print(json.dumps({f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in p.iterdir()}))"
    before_hashes = docker('exec', wal_helper, 'python', '-c', hashes_code)
    spec = importlib.util.spec_from_file_location('actual_guard_probe', source / 'memory-compat.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    wal_result = docker('run', '--rm', '--pull', 'never', '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                        '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=256m', '--memory', '384m', '--cpus', '1', '--pids-limit', '64',
                        '--user', '10001:10001', '--env', 'MEM0_DATA_DIR=/data', '--mount', 'type=volume,src=' + wal_volume + ',dst=/data,readonly',
                        '--entrypoint', 'python', compatible, '-B', '-c', module.PROBE)
    check('Actual read-only Docker probe sees committed uncheckpointed WAL', json.loads(wal_result)['requiredProtocol'] == 2)
    check('Read-only probe leaves database WAL and auxiliary files unchanged', before_hashes == docker('exec', wal_helper, 'python', '-c', hashes_code))
    current = snapshot_production()
    report['productionAfter'] = current
    active = [row for row in current.values() if row['running']]
    check('Production containers and images remain unchanged and healthy', current == baseline and len(active) == 11 and all(row['healthy'] == 'healthy' for row in active))
    report['passed'] = True
except Exception as error:
    report['failure'] = type(error).__name__ + ': ' + str(error)
    raise
finally:
    lock.close()
    for name in list(reversed(resources)):
        try:
            remove(name)
        except Exception:
            report.setdefault('cleanupWarnings', []).append('Container cleanup requires verification: ' + name)
    for name in volumes:
        try:
            row = json.loads(docker('volume', 'inspect', name))[0]
            if not owned(row):
                raise RuntimeError('Foreign volume')
            docker('volume', 'rm', name)
        except Exception:
            report.setdefault('cleanupWarnings', []).append('Volume cleanup requires verification: ' + name)
    try:
        row = json.loads(docker('image', 'inspect', image_name))[0]
        if owned(row):
            docker('image', 'rm', image_name)
    except Exception:
        report.setdefault('cleanupWarnings', []).append('Fixture image cleanup requires verification')
    report['passed'] = report['passed'] and not report.get('cleanupWarnings')
    save()
print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'runId': run_id,
                  'result': str(directory / 'result.json'), 'productionDeploymentExecuted': False}))
