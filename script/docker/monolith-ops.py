#!/usr/bin/env python3
"""Private, single-host maintenance for the existing Docker monolith (Python standard library)."""
import argparse
import contextlib
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import uuid

PROJECT = 'doorhandlecatch-monolith'
ZONE = dt.timezone(dt.timedelta(hours=8))
APP = re.compile(r'^doorhandlecatch/(backend|web|mem0):ci-([0-9]+)-[a-f0-9]{12}$')
VOLUME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,150}$')
DIGEST = re.compile(r'^sha256:[a-f0-9]{64}$')


class OpsError(RuntimeError):
    pass


class MaintenanceBusy(OpsError):
    pass


def run(args, *, data=None, input_stream=None, output=None, timeout=120, env=None, file_limit=None):
    def limit_output():
        import resource
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
    try:
        result = subprocess.run(args, input=data, stdin=input_stream, stdout=output or subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout, env=env, check=False,
                                **({'preexec_fn': limit_output} if file_limit is not None else {}))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise OpsError('Operation unavailable or timed out: '+args[0]) from error
    if result.returncode:
        # Provider/DB diagnostics can contain connection details. Keep them out of CI logs.
        raise OpsError('Operation failed: '+args[0]+' (exit '+str(result.returncode)+')')
    return result.stdout if output is None else b''


def docker(*args, **kwargs):
    return run(['docker', *args], **kwargs)


def digest(path):
    with path.open('rb') as stream:
        return stream_digest(stream)


def stream_digest(stream):
    value = hashlib.sha256()
    for block in iter(lambda: stream.read(1024*1024), b''):
        value.update(block)
    return value.hexdigest()


def private_config_ok(path):
    return path.is_file() and not path.is_symlink() and path.stat().st_mode & 0o077 == 0


def credential_status(path):
    if not private_config_ok(path):
        return {'healthy': False, 'reason': 'Private configuration permissions are invalid'}
    values = {}
    for line in path.read_text(encoding='utf8').splitlines():
        match = re.fullmatch(r'\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=(.*)', line)
        if match:
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            values[match.group(1)] = value
    def present(name, minimum=1):
        value = values.get(name, '')
        return len(value) >= minimum and not value.startswith(('replace-', 'change-me', 'example-'))
    required = {name: present(name) for name in ('MYSQL_ROOT_PASSWORD', 'MYSQL_PASSWORD', 'DB_PASSWORD')}
    required['JWT_SECRET'] = present('JWT_SECRET', 32)
    required['MEM0_BRIDGE_TOKEN'] = present('MEM0_BRIDGE_TOKEN', 32)
    if values.get('APP_REDIS_ENABLED', 'true').lower() == 'true':
        required['REDIS_PASSWORD'] = present('REDIS_PASSWORD', 16)
    matching = bool(values.get('DB_PASSWORD')) and values.get('DB_PASSWORD') == values.get('MYSQL_PASSWORD')
    return {'healthy': all(required.values()) and matching, 'requiredConfigured': required,
            'applicationDatabasePasswordMatches': matching,
            'modelCredentialsConfigured': {name: present(name) for name in ('OPENAI_API_KEY', 'DEEPSEEK_API_KEY', 'DASHSCOPE_API_KEY', 'AGENT_RESPONSES_API_KEY')},
            'providerConnectivityVerified': False}


def write_json(path, value):
    temporary = path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    with temporary.open('x', encoding='utf8') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def checked_root(value):
    path = Path(value).resolve(strict=True)
    if path == Path(path.anchor) or not (path/'state').is_dir() or not (path/'releases').is_dir():
        raise OpsError('Expected an existing release root with state and releases')
    if any((path/name).is_symlink() for name in ('state', 'releases', 'backups')):
        raise OpsError('Maintenance directories must not be symbolic links')
    return path


@contextlib.contextmanager
def maintenance_lock(root, inherited_fd=None):
    import fcntl  # Host operations run on the Linux ECS, never install a Windows service.
    if inherited_fd is not None:
        if inherited_fd < 3:
            raise OpsError('Inherited deployment lock does not match')
        opened = os.fstat(inherited_fd);expected = (root/'state/deploy.lock').stat()
        if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            raise OpsError('Inherited deployment lock does not match')
        with os.fdopen(os.dup(inherited_fd), 'a') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise MaintenanceBusy('Deployment or maintenance already active') from error
            yield
        return  # Closing a duplicate does not release the parent's open-file-description lock.
    with (root/'state/deploy.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise MaintenanceBusy('Deployment or maintenance already active') from error
        yield


def inventory():
    ids = docker('ps', '-aq', '--filter', 'label=com.docker.compose.project='+PROJECT).decode().split()
    if not ids:
        raise OpsError('Existing monolith containers are required')
    result = []
    for row in json.loads(docker('inspect', *ids)):
        labels = row.get('Config', {}).get('Labels', {})
        service = labels.get('com.docker.compose.service', '')
        if not re.fullmatch(r'[a-z0-9-]+', service):
            raise OpsError('Invalid service identity')
        if row['State']['Running'] and labels.get('com.docker.compose.oneoff', '').lower() == 'true':
            raise OpsError('Wait for one-off work before maintenance; it must not be restarted')
        mounts = [{'type': m['Type'], 'source': m.get('Name', m.get('Source', '')),
                   'target': m['Destination']} for m in row.get('Mounts', [])]
        result.append({'id': row['Id'], 'service': service, 'image': row['Image'],
                       'running': row['State']['Running'], 'mounts': mounts})
    if len([row for row in result if row['service'] == 'mysql' and row['running']]) != 1:
        raise OpsError('Exactly one running MySQL is required')
    live_services = [row['service'] for row in result if row['running']]
    if len(set(live_services)) != len(live_services):
        raise OpsError('Single-host maintenance requires one running container per service')
    return result


def db(container, sql):
    return docker('exec', '-i', container, 'sh', '-c',
                  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --default-character-set=utf8mb4 '
                  '--batch --skip-column-names "$MYSQL_DATABASE"', data=sql.encode(), timeout=120).decode()


def table_counts(container):
    tables = db(container, 'SELECT TABLE_NAME FROM information_schema.tables '
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME;").splitlines()
    if not tables or len(tables) > 500 or any(not re.fullmatch(r'[A-Za-z0-9_]+', name) for name in tables):
        raise OpsError('Unexpected database table catalog')
    sql = ' UNION ALL '.join("SELECT '"+name+"',COUNT(*) FROM `"+name+'`' for name in tables)+';'
    return {name: int(count) for name, count in (line.split('\t') for line in db(container, sql).splitlines())}


def table_checksums(container, names):
    if not names or any(not re.fullmatch(r'[A-Za-z0-9_]+', name) for name in names):
        raise OpsError('Invalid checksum table catalog')
    result = {}
    for line in db(container, 'CHECKSUM TABLE '+','.join('`'+name+'`' for name in sorted(names))+' EXTENDED;').splitlines():
        table, value = line.split('\t');name = table.rsplit('.', 1)[-1]
        if name not in names or not value.isdigit():
            raise OpsError('Database checksum is unavailable')
        result[name] = int(value)
    if set(result) != set(names):
        raise OpsError('Database checksum inventory is incomplete')
    return result


def healthy(container):
    state = json.loads(docker('inspect', '--format', '{{json .State}}', container))
    return state.get('Running') and state.get('Health', {}).get('Status', 'healthy') == 'healthy'


def resume(rows):
    # Resume only containers that were running before the backup. No service is recreated.
    groups = [['redis', 'kafka', 'chroma', 'mcp-egress', 'higress', 'mcp-runner'],
              ['mem0', 'detection-worker'], ['backend'], ['nginx']]
    known = {service for group in groups for service in group}
    extra = [row['service'] for row in rows if row['service'] not in known]
    if extra:
        groups.insert(0, extra)
    for group in groups:
        selected = [row for row in rows if row['service'] in group]
        if not selected:
            continue
        docker('start', *[row['id'] for row in selected], timeout=120)
        deadline = time.monotonic()+240
        while not all(healthy(row['id']) for row in selected):
            if time.monotonic() > deadline:
                raise OpsError('Service health did not recover: '+','.join(group))
            time.sleep(2)


def check(root, runtime, minimum_gib=2, maximum_percent=85, maximum_backup_hours=48):
    usage = shutil.disk_usage(root)
    private = runtime/'deploy/cloud.env'
    private_ok = private_config_ok(private)
    credentials = credential_status(private)
    snapshots = []
    for path in (root/'backups').glob('ops-*'):
        if not path.is_symlink() and (path/'COMPLETE').is_file() and not (path/'COMPLETE').is_symlink():
            snapshots.append(path)
    latest = max(snapshots, key=lambda path: (path/'COMPLETE').stat().st_mtime) if snapshots else None
    age = round((time.time()-(latest/'COMPLETE').stat().st_mtime)/3600, 2) if latest else None
    receipt_valid = False
    if latest and not (latest/'manifest.json').is_symlink():
        try:
            receipt = json.loads((latest/'COMPLETE').read_text(encoding='utf8'))
            receipt_valid = receipt.get('manifestSha256') == digest(latest/'manifest.json')
        except (OSError, ValueError, AttributeError):
            pass
    disk_ok = usage.free >= minimum_gib*1024**3 and usage.used/usage.total*100 < maximum_percent
    result = {'checkedAt': dt.datetime.now(ZONE).isoformat(), 'healthy': bool(disk_ok and private_ok and credentials['healthy'] and receipt_valid and age is not None and age <= maximum_backup_hours),
              'disk': {'freeBytes': usage.free, 'usedPercent': round(usage.used/usage.total*100, 2), 'healthy': disk_ok},
              'privateConfigurationPermissions': private_ok, 'credentialConfiguration': credentials,
              'backupAgeHours': age, 'backupReceiptValid': receipt_valid, 'backupContentChecked': False}
    write_json(root/'state/operations-health.json', result)
    return result


def validate_members(path):
    # Validate names before any restore. Restoration is additionally confined to a fresh container volume.
    with tarfile.open(path, 'r:gz') as archive:
        for index, member in enumerate(archive):
            name = PurePosixPath(member.name)
            if index >= 1000000 or name.is_absolute() or '..' in name.parts or not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise OpsError('Unsafe archive entry')
            if member.islnk():
                target = PurePosixPath(member.linkname)
                if target.is_absolute() or '..' in target.parts:
                    raise OpsError('Unsafe archive hardlink')


SIZE_VOLUME = '''import os,stat
from pathlib import Path
total=0;entries=0
for folder,dirs,files in os.walk('/source',followlinks=False):
 for name in dirs+files:
  value=(Path(folder)/name).lstat();entries+=1
  if not (stat.S_ISREG(value.st_mode) or stat.S_ISDIR(value.st_mode) or stat.S_ISLNK(value.st_mode)):raise RuntimeError('Unsupported source file')
  total+=value.st_size+1536
  if entries>1000000:raise RuntimeError('Too many source files')
print(total)
'''


def estimate_backup(mysql, helper, volumes):
    size = db(mysql, 'SELECT COALESCE(SUM(DATA_LENGTH+INDEX_LENGTH),0) FROM information_schema.tables WHERE TABLE_SCHEMA=DATABASE();').strip()
    if not size.isdigit():
        raise OpsError('Source database size is unavailable')
    # Allow SQL escaping/hex expansion and the temporary uncompressed+gzip copies.
    required = max(64*1024**2, int(size)*6)
    for volume in volumes:
        if not VOLUME.fullmatch(volume):
            raise OpsError('Invalid volume identity')
        raw = docker('run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE',
                     '--security-opt', 'no-new-privileges', '--user', '0',
                     '--mount', 'type=volume,src='+volume+',dst=/source,readonly',
                     '--entrypoint', 'python3', helper, '-c', SIZE_VOLUME, timeout=180).decode().strip()
        if not raw.isdigit():
            raise OpsError('Source volume size is unavailable')
        required += int(raw)*102//100+1024*1024
    return required


def output_budget(root, reserve):
    remaining = shutil.disk_usage(root).free-reserve
    if remaining < 1024*1024:
        raise OpsError('Backup stopped to preserve free disk space')
    return remaining


def verify(snapshot, require_complete=True):
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise OpsError('Snapshot directory is invalid')
    manifest = json.loads((snapshot/'manifest.json').read_text(encoding='utf8'))
    if not isinstance(manifest, dict):
        raise OpsError('Snapshot manifest is invalid')
    if require_complete:
        if not (snapshot/'COMPLETE').is_file() or (snapshot/'COMPLETE').is_symlink():
            raise OpsError('Snapshot did not complete')
        receipt = json.loads((snapshot/'COMPLETE').read_text(encoding='utf8'))
        if not isinstance(receipt, dict) or receipt.get('manifestSha256') != digest(snapshot/'manifest.json'):
            raise OpsError('Snapshot manifest checksum mismatch')
    if manifest.get('version') != 1 or manifest.get('project') != PROJECT:
        raise OpsError('Snapshot manifest is invalid')
    if not isinstance(manifest.get('databaseName'), str) or not re.fullmatch(r'[A-Za-z0-9_]{1,64}', manifest['databaseName']):
        raise OpsError('Snapshot database identity is invalid')
    files = manifest.get('files', {})
    if not isinstance(files, dict) or not files or 'database.sql.gz' not in files:
        raise OpsError('Snapshot inventory is incomplete')
    volumes = manifest.get('volumes', {})
    if not isinstance(volumes, dict) or len(volumes) > 30 or any(not isinstance(key, str) or not isinstance(value, str) for key, value in volumes.items()) or len(set(volumes.values())) != len(volumes):
        raise OpsError('Snapshot volume map is invalid')
    for volume, name in volumes.items():
        if not VOLUME.fullmatch(volume) or not isinstance(name, str) or name not in files or not name.endswith('.tar.gz'):
            raise OpsError('Snapshot volume map is invalid')
    counts = manifest.get('tableCounts', {})
    if not isinstance(counts, dict) or not counts or len(counts) > 500 or any(not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_]+', key) or type(value) is not int or value < 0 for key, value in counts.items()):
        raise OpsError('Snapshot database counts are invalid')
    checksums = manifest.get('tableChecksums', {})
    if not isinstance(checksums, dict) or set(checksums) != set(counts) or any(type(value) is not int or value < 0 for value in checksums.values()):
        raise OpsError('Snapshot database checksums are invalid')
    for name, expected in files.items():
        if not isinstance(name, str) or not isinstance(expected, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..') or not re.fullmatch(r'[a-f0-9]{64}', expected):
            raise OpsError('Invalid snapshot filename')
        target = snapshot/name
        if target.is_symlink() or not target.is_file() or digest(target) != expected:
            raise OpsError('Snapshot checksum mismatch: '+name)
        if name.endswith('.tar.gz'):
            validate_members(target)
        if name.endswith('.gz'):
            with gzip.open(target, 'rb') as stream:
                while stream.read(1024*1024):
                    pass  # Checks gzip CRC/end marker; no content is printed.
    return manifest


def backup(root, runtime, minimum_gib=2):
    reserve = minimum_gib*1024**3
    if shutil.disk_usage(root).free < reserve:
        raise OpsError('Insufficient free disk space for backup')
    private = runtime/'deploy/cloud.env'
    if not private_config_ok(private):
        raise OpsError('Private runtime configuration must have mode 0600')
    rows = inventory()
    live = [row for row in rows if row['running']]
    for row in live:
        if not healthy(row['id']):
            raise OpsError('Cannot snapshot unhealthy service: '+row['service'])
    backend = next((row for row in live if row['service'] == 'backend'), None)
    mysql = next(row for row in live if row['service'] == 'mysql')
    events = db(mysql['id'], "SELECT COUNT(*) FROM information_schema.events WHERE EVENT_SCHEMA=DATABASE() AND STATUS='ENABLED';").strip()
    if events != '0':
        raise OpsError('Enabled database events require a separate coordinated backup window')
    if backend is None or not DIGEST.fullmatch(backend['image']):
        raise OpsError('A running backend image is required for volume export')
    volumes = sorted({mount['source'] for row in live if row['service'] != 'mysql'
                      for mount in row['mounts'] if mount['type'] == 'volume'})
    if any(not VOLUME.fullmatch(volume) for volume in volumes):
        raise OpsError('Invalid existing volume name')
    estimated = estimate_backup(mysql['id'], backend['image'], volumes)
    if shutil.disk_usage(root).free < estimated+reserve:
        raise OpsError('Insufficient space for the estimated backup and free-space reserve')
    target = root/'backups'/('ops-'+dt.datetime.now(ZONE).strftime('%Y%m%dT%H%M%S%z')+'-'+uuid.uuid4().hex[:8])
    target.mkdir(parents=True, mode=0o700)
    stopped = [row for row in live if row['service'] != 'mysql']
    manifest = {'version': 1, 'project': PROJECT, 'createdAt': dt.datetime.now(ZONE).isoformat(),
                'images': {row['service']: row['image'] for row in live}, 'volumes': {}, 'files': {}, 'estimatedBytes': estimated,
                'externalBinds': [mount for row in live for mount in row['mounts'] if mount['type'] == 'bind'],
                'externalObjectStorage': 'OSS objects remain external; preserve bucket data separately'}
    # A dump alone is not a cross-store snapshot. Briefly quiesce all application writers.
    record = {'version': 1, 'project': PROJECT, 'snapshot': target.name, 'phase': 'QUIESCING', 'containers': stopped}
    try:
        write_json(root/'state/maintenance.json', record)
        if stopped:
            # Stop ingress first. Even partial stop failure goes through the resume path below.
            ingress = [row for row in stopped if row['service'] == 'nginx']
            others = [row for row in stopped if row['service'] != 'nginx']
            for group in (ingress, others):
                if group:
                    docker('stop', '--time', '60', *[row['id'] for row in group], timeout=180)
        manifest['tableCounts'] = table_counts(mysql['id'])
        manifest['tableChecksums'] = table_checksums(mysql['id'], manifest['tableCounts'])
        manifest['databaseName'] = db(mysql['id'], 'SELECT DATABASE();').strip()
        if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', manifest['databaseName']):
            raise OpsError('Source database identity is invalid')
        raw = target/'database.sql'
        with raw.open('xb') as stream:
            os.chmod(raw, 0o600)
            docker('exec', mysql['id'], 'sh', '-c',
                   'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction '
                   '--routines --events --triggers --hex-blob --no-tablespaces --set-gtid-purged=OFF '
                   '--column-statistics=0 --default-character-set=utf8mb4 "$MYSQL_DATABASE"', output=stream, timeout=600,
                   file_limit=output_budget(root, reserve))
        with raw.open('rb') as source, gzip.open(target/'database.sql.gz', 'xb') as output:
            while True:
                block = source.read(1024*1024)
                if not block:
                    break
                output_budget(root, reserve);output.write(block)
        raw.unlink()
        shutil.copyfile(private, target/'cloud.env');os.chmod(target/'cloud.env', 0o600)
        for number, volume in enumerate(volumes):
            name = 'volume-'+str(number)+'.tar.gz'
            with (target/name).open('xb') as stream:
                docker('run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE',
                       '--security-opt', 'no-new-privileges', '--user', '0',
                       '--mount', 'type=volume,src='+volume+',dst=/source,readonly',
                       '--entrypoint', 'tar', backend['image'], '-czf', '-', '-C', '/source', '.', output=stream, timeout=600,
                       file_limit=output_budget(root, reserve))
            manifest['volumes'][volume] = name
        for file in target.iterdir():
            if file.is_file():
                os.chmod(file, 0o600);manifest['files'][file.name] = digest(file)
        write_json(target/'manifest.json', manifest)
        verify(target, require_complete=False)
    finally:
        try:
            resume(stopped)
            record['phase'] = 'RESUMED'
        except BaseException:
            record['phase'] = 'RECOVERY_REQUIRED'
            raise
        finally:
            write_json(root/'state/maintenance.json', record)
    # Only advertise completion after source services are healthy again.
    write_json(target/'COMPLETE', {'createdAt': dt.datetime.now(ZONE).isoformat(), 'manifestSha256': digest(target/'manifest.json')})
    return target


def recover_maintenance(root):
    path = root/'state/maintenance.json'
    if not path.is_file():
        return {'recovered': False, 'reason': 'No interrupted maintenance'}
    record = json.loads(path.read_text(encoding='utf8'))
    if record.get('version') != 1 or record.get('project') != PROJECT:
        raise OpsError('Maintenance recovery record is invalid')
    if record.get('phase') == 'RESUMED':
        return {'recovered': False, 'reason': 'Source services already resumed'}
    if record.get('phase') not in ('QUIESCING', 'RECOVERY_REQUIRED'):
        raise OpsError('Unknown maintenance phase')
    current = {row['id']: row for row in inventory()}
    rows = record.get('containers')
    if not isinstance(rows, list) or len(rows) > 20:
        raise OpsError('Invalid recovery service list')
    selected = []
    for row in rows:
        actual = current.get(row.get('id'))
        if not actual or actual['service'] != row.get('service') or actual['image'] != row.get('image') or not row.get('running') or row['service'] == 'mysql':
            raise OpsError('Service identity changed; review maintenance before recovery')
        selected.append(actual)
    resume(selected)
    record['phase'] = 'RESUMED';record['recoveredAt'] = dt.datetime.now(ZONE).isoformat()
    write_json(path, record)
    return {'recovered': True, 'services': [row['service'] for row in selected]}


def systemd_units(root, runtime, script, username):
    for path in (root, runtime, script):
        if not re.fullmatch(r'/(home|srv|opt)/[A-Za-z0-9_./-]+', str(path)) or '..' in PurePosixPath(str(path)).parts:
            raise OpsError('Systemd paths must be absolute deployment paths without shell syntax')
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', username):
        raise OpsError('Invalid service account')
    command = '/usr/bin/python3 '+str(script)
    common = ' --root '+str(root)+' --runtime '+str(runtime)
    marker = '# DoorHandleCatch managed operations\n'
    def service(description, action, recovery=False):
        return marker+('[Unit]\nDescription='+description+'\nRequires=docker.service\nAfter=docker.service\n'
                       '[Service]\nType=oneshot\nUser='+username+'\nSupplementaryGroups=docker\nUMask=0077\n'
                       'Environment=TZ=Asia/Shanghai\nExecStart='+command+' '+action+common+'\n'
                       + ('ExecStopPost='+command+' recover'+common+'\n' if recovery else '')
                       + 'TimeoutStartSec=1800\nTimeoutStopSec=300\nSuccessExitStatus=75\nNoNewPrivileges=true\nPrivateTmp=true\n'
                       'ProtectSystem=strict\nProtectHome=read-only\nReadWritePaths='+str(root)+'\n')
    return {
        'doorhandle-backup.service': service('DoorHandle private data backup', 'backup', True),
        'doorhandle-backup.timer': marker+'[Unit]\nDescription=DoorHandle evening backup\n[Timer]\nOnCalendar=*-*-* 23:00:00 Asia/Shanghai\nPersistent=false\nAccuracySec=1min\n[Install]\nWantedBy=timers.target\n',
        'doorhandle-disk-check.service': service('DoorHandle disk, backup and credential permission checks', 'check'),
        'doorhandle-disk-check.timer': marker+'[Unit]\nDescription=DoorHandle operation health checks\n[Timer]\nOnBootSec=2min\nOnUnitInactiveSec=15min\n[Install]\nWantedBy=timers.target\n',
        'doorhandle-maintenance-recover.service': service('Resume interrupted DoorHandle maintenance', 'recover')+'[Install]\nWantedBy=multi-user.target\n',
    }


def install_timers(root, runtime, apply=False):
    import pwd
    username = pwd.getpwuid(runtime.stat().st_uid).pw_name
    # Pin the selected checked-out helper; timer upgrades are explicit rather than following mutable HEAD.
    units = systemd_units(root, runtime, Path(__file__).resolve(), username)
    staging = root/'state/ops-units';staging.mkdir(mode=0o700, exist_ok=True)
    for name, value in units.items():
        path = staging/name
        if path.is_symlink():
            raise OpsError('Unit staging path must not be a symbolic link')
        path.write_text(value, encoding='utf8');os.chmod(path, 0o600)
    run(['systemd-analyze', 'verify', *[str(staging/name) for name in units]], timeout=30)
    if apply:
        if os.geteuid() != 0:
            raise OpsError('Install timers as root; units run under the runtime owner account')
        destination = Path('/etc/systemd/system')
        for name in units:
            path = destination/name
            if path.is_symlink() or path.exists() and not path.read_text(encoding='utf8').startswith('# DoorHandleCatch managed operations\n'):
                raise OpsError('Refusing to replace a unit not managed by this project')
        for name, value in units.items():
            target = destination/name
            temporary = destination/(name+'.doorhandle-tmp')
            with temporary.open('x', encoding='utf8') as stream:
                stream.write(value)
            os.chmod(temporary, 0o644);os.replace(temporary, target)
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'enable', 'doorhandle-maintenance-recover.service', 'doorhandle-disk-check.timer', 'doorhandle-backup.timer'])
    return {'units': sorted(units), 'installed': apply, 'backupTime': '23:00 Asia/Shanghai', 'missedBackupRunsOnBoot': False}


def prune_plan(root, keep=3):
    containers = docker('ps', '-aq').decode().split()
    protected = {row['Image'] for row in json.loads(docker('inspect', *containers))} if containers else set()
    for path in [root/'state/previous-images.yml', root/'state/memory-activation-images.yml', *root.glob('releases/*/runtime-images.yml')]:
        if path.is_file():
            protected.update(re.findall(r'sha256:[a-f0-9]{64}', path.read_text(encoding='utf8')))
    records = [json.loads(line) for line in docker('image', 'ls', '--no-trunc', '--format', '{{json .}}').decode().splitlines()]
    candidates = []
    for repository in ('doorhandlecatch/backend', 'doorhandlecatch/web', 'doorhandlecatch/mem0'):
        images = [row for row in records if APP.fullmatch(row['Repository']+':'+row['Tag']) and row['Repository'] == repository]
        images.sort(key=lambda row: int(APP.fullmatch(row['Repository']+':'+row['Tag']).group(2)), reverse=True)
        for row in images[keep:]:
            tag = row['Repository']+':'+row['Tag']
            canonical = docker('image', 'inspect', '--format', '{{.Id}}', tag).decode().strip()
            if not DIGEST.fullmatch(canonical):
                raise OpsError('Image identity could not be verified')
            if row['ID'] not in protected and canonical not in protected:
                candidates.append(tag)
    return {'keepLatestPerRepository': keep, 'candidates': candidates, 'protectedDigests': sorted(protected)}


def archive_files(path):
    result = {}
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            name = str(PurePosixPath(member.name))
            if name == '.':
                continue
            if name in result:
                raise OpsError('Duplicate archive entry')
            if member.issym():
                result[name] = {'type': 'symlink', 'target': member.linkname}
            elif member.isdir():
                result[name] = {'type': 'directory'}
            elif member.isfile() or member.islnk():
                with archive.extractfile(member) as stream:
                    result[name] = {'type': 'file', 'sha256': stream_digest(stream)}
            else:
                raise OpsError('Unsupported archive entry')
    return result


SCAN_VOLUME = '''import os,json,hashlib
from pathlib import Path
root=Path('/target');result={}
for folder,dirs,files in os.walk(root,followlinks=False):
 for name in dirs+files:
  path=Path(folder)/name;key=path.relative_to(root).as_posix()
  if path.is_symlink():result[key]={'type':'symlink','target':os.readlink(path)}
  elif path.is_dir():result[key]={'type':'directory'}
  elif path.is_file():
   value=hashlib.sha256()
   with path.open('rb') as stream:
    for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
   result[key]={'type':'file','sha256':value.hexdigest()}
  else:raise RuntimeError('Unexpected restored file type')
print(json.dumps(result,sort_keys=True))
'''


def restore_drill(root, snapshot, helper_image=None):
    manifest = verify(snapshot)
    if not (snapshot/'COMPLETE').is_file():
        raise OpsError('Only completed snapshots can be drilled')
    images = manifest.get('images', {})
    if not all(DIGEST.fullmatch(images.get(service, '')) for service in ('mysql', 'backend')):
        raise OpsError('Snapshot images are invalid')
    if helper_image is not None and not DIGEST.fullmatch(helper_image):
        raise OpsError('Helper image must be a local digest')
    helper = helper_image or images['backend']
    suffix = uuid.uuid4().hex[:12]
    container = 'doorhandle-restore-drill-'+suffix
    created_volumes = []
    password = uuid.uuid4().hex+uuid.uuid4().hex
    report = {'checkedAt': dt.datetime.now(ZONE).isoformat(), 'snapshot': snapshot.name, 'passed': False, 'helperImage': helper}
    try:
        docker('run', '-d', '--name', container, '--label', 'doorhandle.ops=restore-drill', '--label', 'doorhandle.ops.run='+suffix,
               '--network', 'none', '--memory', '1536m', '--tmpfs', '/var/lib/mysql:rw,nosuid,nodev,size=1073741824',
               '--env', 'MYSQL_ROOT_PASSWORD', '--env', 'MYSQL_DATABASE='+manifest['databaseName'], images['mysql'], '--event-scheduler=OFF',
               env={**os.environ, 'MYSQL_ROOT_PASSWORD': password})
        deadline = time.monotonic()+180
        while True:
            try:
                db(container, 'SELECT 1;');break
            except OpsError:
                if time.monotonic() > deadline:
                    raise OpsError('Isolated restore database did not become ready')
                time.sleep(2)
        with (snapshot/'database.sql.gz').open('rb') as source:
            docker('exec', '-i', container, 'bash', '-o', 'pipefail', '-c',
                   'gzip -dc | MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot '
                   '--default-character-set=utf8mb4 "$MYSQL_DATABASE"', input_stream=source, timeout=600)
        counts = table_counts(container)
        if counts != manifest['tableCounts']:
            raise OpsError('Restored database row counts differ')
        if table_checksums(container, counts) != manifest['tableChecksums']:
            raise OpsError('Restored database checksums differ; inspect data and row format')
        report['databaseTables'] = len(counts)
        report['volumes'] = []
        for number, (original, name) in enumerate(manifest.get('volumes', {}).items()):
            volume = container+'-'+str(number)
            docker('volume', 'create', '--label', 'doorhandle.ops=restore-drill', '--label', 'doorhandle.ops.run='+suffix, volume)
            created_volumes.append(volume)
            common = ['run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                      '--security-opt', 'no-new-privileges', '--user', '0',
                      '--mount', 'type=volume,src='+volume+',dst=/target']
            # No host bind mounts; tar can only write this new volume, never production data.
            with (snapshot/name).open('rb') as source:
                docker(*common, '-i', '--entrypoint', 'tar', helper,
                       '-xzf', '-', '--no-same-owner', '--no-same-permissions', '-C', '/target', input_stream=source, timeout=600)
            restored = json.loads(docker(*common, '--entrypoint', 'python3', helper, '-c', SCAN_VOLUME, timeout=600))
            if restored != archive_files(snapshot/name):
                raise OpsError('Restored file inventory or content differs')
            report['volumes'].append({'source': original, 'entries': len(restored), 'verified': True})
        report['passed'] = True
    finally:
        # Names are freshly generated here; no production project/volume deletion command exists.
        try:
            label = docker('inspect', '--format', '{{index .Config.Labels "doorhandle.ops.run"}}', container).decode().strip()
            if label != suffix:
                raise OpsError('Isolated resource ownership differs')
            docker('rm', '-fv', container)
        except OpsError:
            report['cleanupWarning'] = 'Isolated database container requires cleanup'
        for volume in created_volumes:
            try:
                label = docker('volume', 'inspect', '--format', '{{index .Labels "doorhandle.ops.run"}}', volume).decode().strip()
                if label != suffix:
                    raise OpsError('Isolated resource ownership differs')
                docker('volume', 'rm', volume)
            except OpsError:
                report['cleanupWarning'] = 'An isolated restore volume requires cleanup'
        write_json(root/'state'/('restore-drill-'+suffix+'.json'), report)
    if report.get('cleanupWarning'):
        raise OpsError(report['cleanupWarning'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'backup', 'verify', 'restore-drill', 'recover', 'prune', 'install-timers'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--runtime')
    parser.add_argument('--snapshot')
    parser.add_argument('--helper-image')
    parser.add_argument('--lock-fd', type=int)
    parser.add_argument('--keep', type=int, default=3)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--min-free-gib', type=int, default=2)
    args = parser.parse_args()
    os.umask(0o077)
    root = checked_root(args.root)
    if args.keep < 2 or args.min_free_gib < 1:
        raise OpsError('Keep at least two application releases and one GiB free')
    if args.action in ('verify', 'restore-drill'):
        if not args.snapshot:
            raise OpsError('Snapshot path is required')
        snapshot = Path(args.snapshot).resolve(strict=True)
        if not snapshot.is_relative_to(root/'backups'):
            raise OpsError('Snapshot must be inside the release backup directory')
        if args.action == 'verify':
            verify(snapshot);print(json.dumps({'verified': True}));return
        with maintenance_lock(root, args.lock_fd):
            print(json.dumps(restore_drill(root, snapshot, args.helper_image)));return
    if args.action == 'recover':
        with maintenance_lock(root, args.lock_fd):
            print(json.dumps(recover_maintenance(root)));return
    if not args.runtime:
        raise OpsError('Existing runtime path is required')
    runtime = Path(args.runtime).resolve(strict=True)
    if args.action == 'install-timers':
        if args.lock_fd is not None:
            raise OpsError('Install timers independently of an active deployment')
        with maintenance_lock(root, args.lock_fd):
            result = install_timers(root, runtime, args.apply)
        if args.apply:
            # Start only after releasing the lock: the recovery service needs that same lock.
            run(['systemctl', 'start', 'doorhandle-maintenance-recover.service', 'doorhandle-disk-check.timer', 'doorhandle-backup.timer'])
        print(json.dumps(result));return
    with maintenance_lock(root, args.lock_fd):
        if args.action == 'check':
            result = check(root, runtime, args.min_free_gib);print(json.dumps(result));return 0 if result['healthy'] else 2
        if args.action == 'backup':
            print(json.dumps({'snapshot': str(backup(root, runtime, args.min_free_gib))}));return
        plan = prune_plan(root, args.keep)
        if args.apply:
            for tag in plan['candidates']:
                # Re-evaluate immediately before each mutation under the deployment lock.
                if tag in prune_plan(root, args.keep)['candidates']:
                    docker('image', 'rm', tag)
        print(json.dumps(plan))


if __name__ == '__main__':
    try:
        def interrupted(signum, frame):
            raise OpsError('Maintenance interrupted; source services need verification')
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        sys.exit(main())
    except MaintenanceBusy as error:
        print(json.dumps({'skipped': str(error)}), file=sys.stderr)
        sys.exit(75)
    except (OpsError, ValueError, OSError, tarfile.TarError, json.JSONDecodeError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        sys.exit(1)
