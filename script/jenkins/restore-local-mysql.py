"""ECS-only two independent recoveries of the preserved local 45-table dump.

Only fresh owner-labelled, network-none MySQL containers receive SQL. The
original source container supplies its immutable image ID only. No application,
event scheduler, external provider, original database or production volume is
started, queried, attached or modified by this controller.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
MIB = 1024 ** 2
MEMORY = 1536 * MIB
DISK_FLOOR = 2 * 1024 ** 3 + 256 * MIB
LABEL = 'io.doorhandle.local-mysql-custody'
CID = re.compile(r'[a-f0-9]{64}')
IMAGE = re.compile(r'sha256:[a-f0-9]{64}')
SCHEMA = 'doorhandledb'


class CleanupNotQuiescent(Exception):
    """An owned creator did not leave its bounded critical section in time."""


def need(value, message):
    if not value: raise ValueError(message)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def source(): return module('fresh_local_mysql_bytes', ROOT / 'script/jenkins/preserve-local-mysql.py')


def load_runtime():
    # Isolated -I execution deliberately has no checkout PYTHONPATH. The
    # reviewed runtime imports its two sibling schema modules by name.
    directory = ROOT / 'script/schema'
    need(directory.resolve(strict=True) == directory and not directory.is_symlink(), 'Fixed schema helper path differs')
    sys.path.insert(0, str(directory))
    return module('local_sql_existing_snapshot_primitives', directory / 'compact_migration_runtime.py')


def quote(value):
    need(isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', value), 'Unsupported explicit recovered SQL identifier')
    return '`' + value + '`'


def findings(mysql, metadata):
    """Observe defects without dropping constraints, filtering or repairing rows."""
    groups, result = {}, []
    for row in metadata['foreignKeys']:
        if row['parentSchema'] != '$SELF':
            result.append({'kind': 'EXTERNAL_FOREIGN_KEY', 'table': row['table'], 'constraint': row['name'],
                           'violations': 0, 'unverified': True, 'reason': 'PARENT_SCHEMA_OUTSIDE_PROJECT_EXPORT'})
            continue
        groups.setdefault((row['table'], row['name']), []).append(row)
    for (table, name), rows in sorted(groups.items()):
        rows.sort(key=lambda row: row['ordinal']); parent = rows[0]['parent']
        condition = ' AND '.join('c.' + quote(row['column']) + ' IS NOT NULL' for row in rows)
        join = ' AND '.join('p.' + quote(row['parentColumn']) + '=c.' + quote(row['column']) for row in rows)
        sql = 'SELECT JSON_OBJECT(\'n\',COUNT(*)) FROM ' + quote(SCHEMA) + '.' + quote(table) + ' c WHERE ' + condition
        sql += ' AND NOT EXISTS (SELECT 1 FROM ' + quote(SCHEMA) + '.' + quote(parent) + ' p WHERE ' + join + ');'
        count = mysql.single(sql)['n']
        need(type(count) is int and count >= 0, 'Recovered FK defect count is invalid')
        if count: result.append({'kind': 'FOREIGN_KEY', 'table': table, 'constraint': name, 'violations': count})
    for row in metadata['checks']:
        if row['enforced'] != 'YES': continue
        # MySQL has already parsed this CHECK. It is read only on the owned DB;
        # subqueries/stored functions are not legal MySQL CHECK expressions.
        clause = row['clause']; need(isinstance(clause, str) and 0 < len(clause) <= 65536, 'Recovered CHECK expression exceeds its bound')
        count = mysql.single('SELECT JSON_OBJECT(\'n\',COUNT(*)) FROM ' + quote(SCHEMA) + '.' + quote(row['table'])
            + ' WHERE (' + clause + ') IS FALSE;')['n']
        need(type(count) is int and count >= 0, 'Recovered CHECK defect count is invalid')
        if count: result.append({'kind': 'CHECK', 'table': row['table'], 'constraint': row['name'], 'violations': count})
    return result


def compare_recoveries(first, second):
    need(first['snapshot']['snapshotSha256'] == second['snapshot']['snapshotSha256']
         and first['snapshot']['tables'] == second['snapshot']['tables']
         and first['metadata'] == second['metadata'] and first['extraObjects'] == second['extraObjects']
         and first['findings'] == second['findings'] and first['observedCountsMatch'] is True
         and second['observedCountsMatch'] is True and len(first['snapshot']['tables']) == 45,
         'Independent recoveries differ in original rows/types/NULLs/clocks/DDL/indexes/constraints/high-water marks')
    need(first['serverUuid'] != second['serverUuid'] and first['containerId'] != second['containerId']
         and first['volume'] != second['volume'], 'The second recovery must be an independent server and fresh volume')


class Recovery:
    def __init__(self, args):
        self.args, self.bytes = args, source()
        self.work, self.context = self.bytes.admit(args)
        self.utility = self.bytes.common(); self.directory = self.work / 'local-mysql-recovery'
        self.owner_file = self.work / 'local-mysql-recovery-owner.json'
        self.docker = self.utility.safe(shutil.which('docker'))
        self.original = None; self.state = None; self.cancel = threading.Event(); self.pressure = None

    def docker_call(self, *arguments, data=None, timeout=120):
        result = subprocess.run([str(self.docker), *arguments], input=data, capture_output=True, timeout=timeout,
            env={key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
        need(result.returncode == 0, 'An owned recovery Docker operation failed; private recovery evidence is retained')
        need(len(result.stdout) <= 64 * MIB, 'Owned Docker metadata exceeds its bound')
        return result.stdout

    def persist(self):
        path = self.owner_file; temporary = path.with_name(path.name + '.' + secrets.token_hex(4))
        self.bytes.write(temporary, self.state); os.replace(temporary, path)

    def load(self):
        self.state = self.bytes.read(self.utility.owner_path(self.owner_file))
        need(all(self.state.get(key) == value for key, value in self.context.items())
             and self.state['directory'] == str(self.directory), 'Recovery belongs to another fixed source attempt')
        self.original = self.state['originalContainerId']

    def inspect(self, cid):
        need(CID.fullmatch(cid) and cid != self.original, 'Original/foreign database cannot receive recovery commands')
        row = json.loads(self.docker_call('inspect', cid))[0]; labels = row['Config'].get('Labels') or {}; host = row['HostConfig']
        node = next((item for item in self.state['servers'] if item['containerId'] == cid), None)
        need(node is not None and row['Id'] == cid and row['Image'] == self.state['mysqlImage']
             and labels.get(LABEL) == self.state['owner'] and labels.get('io.doorhandle.release') == self.args.tag
             and labels.get('io.doorhandle.source') == self.args.source_sha256
             and host['NetworkMode'] == 'none' and not host.get('Privileged') and not host.get('PortBindings')
             and host['Memory'] == host['MemorySwap'] == MEMORY and host['RestartPolicy']['Name'] == 'no',
             'Owned MySQL image/network/cgroup/identity changed')
        mounts = [m for m in row['Mounts'] if m.get('Type') == 'volume']
        need(len(row['Mounts']) == 1 and len(mounts) == 1 and mounts[0]['Name'] == node['volume']
             and mounts[0]['Destination'] == '/var/lib/mysql' and mounts[0]['RW'], 'Recovery attempted an unreviewed/original data mount')
        return row

    def guard(self):
        need(self.pressure is None, 'Recovery resource supervision failed')
        need(not (self.work / 'local-mysql-recovery-cancel.json').exists(), 'This exact recovery attempt was cancelled')
        self.utility.resource_guard(self.directory if self.directory.exists() else self.work, 0)

    @contextlib.contextmanager
    def creation_lock(self, timeout=15):
        import fcntl
        path = self.utility.safe(self.work / 'local-mysql-recovery-create.lock', exists=False)
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            self.utility.owner_path(path)
            actual, visible = os.fstat(descriptor), path.stat()
            need((actual.st_dev, actual.st_ino) == (visible.st_dev, visible.st_ino), 'Recovery create-lock identity changed')
            deadline = time.monotonic() + timeout
            while True:
                try: fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB); break
                except BlockingIOError:
                    if time.monotonic() >= deadline: raise CleanupNotQuiescent()
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            yield
        finally: os.close(descriptor)

    def watch(self):
        probes = self.directory / 'resource-probes.jsonl'
        with probes.open('x', encoding='utf8') as stream:
            os.chmod(probes, 0o600)
            while not self.cancel.is_set():
                try:
                    disk = os.statvfs(self.directory); free = disk.f_bavail * disk.f_frsize
                    mem = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
                    rows = []
                    for server in list(self.state['servers']):
                        row = self.inspect(server['containerId']); peak, oom = 0, bool(row['State'].get('OOMKilled'))
                        if row['State']['Running']:
                            try:
                                pid = row['State']['Pid']; records = [line[3:] for line in (Path('/proc') / str(pid) / 'cgroup').read_text().splitlines() if line.startswith('0::/')]
                                need(len(records) == 1 and records[0].endswith(('/docker-' + row['Id'] + '.scope', '/docker/' + row['Id']))
                                     and '..' not in Path(records[0]).parts, 'Recovery process cgroup is not its exact owned container')
                                base = Path('/sys/fs/cgroup') / records[0].lstrip('/')
                                need(int((base / 'memory.max').read_text()) == MEMORY and int((base / 'memory.swap.max').read_text()) == 0,
                                     'Actual recovery cgroup differs from its bounded allocation')
                                peak = int((base / 'memory.peak').read_text()); events = dict(line.split() for line in (base / 'memory.events').read_text().splitlines())
                                oom = oom or int(events.get('oom_kill', 0)) > 0 or int(events.get('oom', 0)) > 0
                                server['peakBytes'] = max(server.get('peakBytes', 0), peak)
                            except FileNotFoundError:
                                current = self.inspect(server['containerId'])
                                need(server.get('stopping') is True and not current['State']['Running']
                                     and current['State']['Pid'] == 0, 'A running recovery process lost cgroup observation')
                        rows.append({'containerId': row['Id'], 'peakBytes': peak, 'oom': oom})
                    stream.write(json.dumps({'atUnix': time.time(), 'diskAvailableBytes': free, 'memoryAvailableBytes': mem, 'containers': rows}) + '\n'); stream.flush()
                    need(free >= DISK_FLOOR and mem >= 1024 ** 3 and not any(row['oom'] for row in rows), 'Recovery resource reserve/OOM boundary reached')
                except Exception as error:
                    self.pressure = type(error).__name__
                    for server in list(self.state['servers']):
                        with contextlib.suppress(Exception):
                            self.inspect(server['containerId']); self.docker_call('stop', '--time', '5', server['containerId'], timeout=15)
                    return
                self.cancel.wait(1)

    def sql_client(self, cid, output):
        runtime = self.runtime; parent = self
        class OwnedMysql(runtime.Mysql):
            # Reuse reviewed streaming I/O and all-column hashes, with explicit
            # network-none owner admission instead of impersonating 131->29.
            def __init__(self):
                self.program, self.container, self.output, self.sequence = parent.docker, cid, output, 0
                self.config = {'scope': 'local-sql-custody-recovery', 'serverUuid': None}
            def command(self, database=None, *, dump=False, table_names=()):
                parent.guard(); parent.inspect(cid); need(not dump and not table_names, 'Recovery never regenerates/substitutes the original SQL dump')
                args = ['--no-defaults', '--no-login-paths', '--protocol=SOCKET', '-uroot', '--default-character-set=utf8mb4',
                        '--batch', '--raw', '--skip-column-names', '--unbuffered', '--binary-mode', '--local-infile=0']
                if database: need(database == SCHEMA, 'Only the recovered project schema is admitted'); args += ['--database=' + SCHEMA]
                return [str(parent.docker), 'exec', '-i', cid, 'sh', '-ec',
                    'MYSQL_PWD="${MYSQL_ROOT_PASSWORD:?}" exec mysql "$@"', '--', *args], b''
        return OwnedMysql()

    def create_registered(self, ordinal):
        self.guard(); name = 'doorhandle-local-mysql-' + self.state['owner'] + '-' + ordinal
        memory_available = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
        need(memory_available >= MEMORY + 1024 ** 3, 'Owned MySQL start would exhaust the host memory reserve')
        volume = name + '-data'; existing = self.docker_call('volume', 'ls', '--format', '{{.Name}}').decode().splitlines()
        need(volume not in existing, 'A fresh recovery volume already exists')
        labels = {LABEL: self.state['owner'], 'io.doorhandle.release': self.args.tag, 'io.doorhandle.source': self.args.source_sha256}
        self.state.setdefault('containerIntents', []).append({'name': name, 'volume': volume, 'ordinal': ordinal})
        self.persist()  # Record capabilities before either create can succeed.
        command = ['volume', 'create']
        for key, value in labels.items(): command += ['--label', key + '=' + value]
        self.docker_call(*command, volume)
        volume_row = json.loads(self.docker_call('volume', 'inspect', volume))[0]
        need(volume_row.get('Name') == volume and volume_row.get('Driver') == 'local' and not volume_row.get('Options')
             and volume_row.get('Labels') == labels, 'New recovery volume ownership/driver differs')
        env_file = self.directory / ('mysql-' + ordinal + '.env')
        with os.fdopen(os.open(env_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as stream:
            stream.write('MYSQL_ROOT_PASSWORD=' + secrets.token_hex(32) + '\n'); stream.flush(); os.fsync(stream.fileno())
        try:
            command = ['create', '--name', name, '--pull', 'never', '--restart', 'no', '--network', 'none',
                '--memory', str(MEMORY), '--memory-swap', str(MEMORY), '--cpus', '1', '--pids-limit', '256', '--env-file', str(env_file)]
            for key, value in labels.items(): command += ['--label', key + '=' + value]
            command += ['--mount', 'type=volume,src=' + volume + ',dst=/var/lib/mysql', self.state['mysqlImage'],
                '--event-scheduler=DISABLED', '--mysqlx=OFF', '--local-infile=OFF', '--skip-log-bin',
                '--innodb-buffer-pool-size=268435456', '--max-connections=20']
            cid = self.docker_call(*command).decode().strip()
        finally:
            if env_file.exists(): env_file.unlink()
        need(CID.fullmatch(cid) and cid != self.original, 'Fresh MySQL recovery identity is invalid')
        node = {'ordinal': ordinal, 'containerId': cid, 'volume': volume, 'name': name, 'peakBytes': 0}
        self.state['servers'].append(node); self.persist(); self.inspect(cid)
        self.docker_call('start', cid)
        return node

    def start(self, ordinal):
        # Cleanup uses this same lock after recording cancellation. Every
        # create/intent/CID is closed before cleanup observes owned resources.
        with self.creation_lock():
            self.guard(); node = self.create_registered(ordinal)
        self.guard(); cid = node['containerId']
        output = self.directory / ordinal; output.mkdir(mode=0o700); (output / 'private').mkdir(mode=0o700)
        client = self.sql_client(cid, output); deadline = time.monotonic() + 240
        while True:
            self.guard()
            try:
                identity = client.single("SELECT JSON_OBJECT('uuid',@@server_uuid,'version',@@version,'port',@@port,'datadir',@@datadir,'events',@@event_scheduler);")
                need(identity['version'].startswith('8.4.') and identity['events'] == 'DISABLED' and identity['port'] == 3306
                     and identity['datadir'] == '/var/lib/mysql/', 'Recovered server version/data-directory/event boundary differs')
                node['serverUuid'] = identity['uuid']; self.persist(); return node, client
            except Exception:
                need(time.monotonic() < deadline and self.inspect(cid)['State']['Running'], 'Owned recovery MySQL readiness failed')
                time.sleep(1)

    def import_original(self, client, file):
        client.script('CREATE DATABASE ' + quote(SCHEMA) + ' CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;', label='fresh-project-schema')
        need(self.bytes.digest(file) == self.bytes.RAW_SHA and file.stat().st_size == self.bytes.RAW_BYTES, 'Original SQL changed before import')
        command, prefix = client.command(SCHEMA); need(not prefix, 'Unexpected credentials in the original SQL input stream')
        output, errors = client.output / 'private/import.stdout', client.output / 'private/import.stderr'
        with file.open('rb') as source_file, output.open('xb') as stdout, errors.open('xb') as stderr:
            os.chmod(output, 0o600); os.chmod(errors, 0o600)
            process = subprocess.Popen(command, stdin=source_file, stdout=stdout, stderr=stderr, start_new_session=True,
                env=client.environment())
            try:
                deadline = time.monotonic() + 600
                while process.poll() is None:
                    self.guard(); need(time.monotonic() < deadline, 'Original SQL recovery exceeded its time budget'); time.sleep(0.1)
                need(process.returncode == 0, 'Original SQL import failed; all original bytes and private diagnostics are retained')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=10)
        need(self.bytes.digest(file) == self.bytes.RAW_SHA, 'Original SQL changed during recovery')

    def capture(self, node, client, expected_catalog, observed_counts):
        self.guard(); actual = self.runtime.schema_snapshot(client, SCHEMA, expected_catalog)
        metadata, metadata_sha = self.runtime.metadata_snapshot(client, SCHEMA)
        extra = {}
        definitions = {
            'routines': ('ROUTINES', 'ROUTINE_SCHEMA', "'name',ROUTINE_NAME,'type',ROUTINE_TYPE,'returns',DTD_IDENTIFIER,'body',ROUTINE_DEFINITION,'mode',SQL_MODE,'definer',DEFINER,'deterministic',IS_DETERMINISTIC,'access',SQL_DATA_ACCESS,'security',SECURITY_TYPE,'comment',ROUTINE_COMMENT,'clientCharset',CHARACTER_SET_CLIENT,'connectionCollation',COLLATION_CONNECTION,'databaseCollation',DATABASE_COLLATION"),
            'parameters': ('PARAMETERS', 'SPECIFIC_SCHEMA', "'routine',SPECIFIC_NAME,'ordinal',ORDINAL_POSITION,'name',PARAMETER_NAME,'mode',PARAMETER_MODE,'type',DTD_IDENTIFIER,'charset',CHARACTER_SET_NAME,'collation',COLLATION_NAME"),
            'events': ('EVENTS', 'EVENT_SCHEMA', "'name',EVENT_NAME,'body',EVENT_DEFINITION,'type',EVENT_TYPE,'executeAt',EXECUTE_AT,'intervalValue',INTERVAL_VALUE,'intervalField',INTERVAL_FIELD,'starts',STARTS,'ends',ENDS,'zone',TIME_ZONE,'completion',ON_COMPLETION,'comment',EVENT_COMMENT,'status',STATUS,'mode',SQL_MODE,'definer',DEFINER,'clientCharset',CHARACTER_SET_CLIENT,'connectionCollation',COLLATION_CONNECTION,'databaseCollation',DATABASE_COLLATION")}
        for name, (table, schema_column, columns) in definitions.items():
            # Definitions/signatures/schedules remain private. Creation/last
            # execution timestamps are server-specific, not definition identity.
            extra[name] = client.json_rows('SELECT JSON_OBJECT(' + columns + ') FROM information_schema.' + table
                + ' WHERE ' + schema_column + "='doorhandledb' ORDER BY 1;")
        defects = findings(client, metadata)
        result = {'containerId': node['containerId'], 'volume': node['volume'], 'serverUuid': node['serverUuid'],
            'snapshot': actual, 'metadata': metadata, 'metadataSha256': metadata_sha, 'extraObjects': extra, 'findings': defects,
            'observedCountsMatch': {name: row['rows'] for name, row in actual['tables'].items()} == observed_counts,
            'liveSourceRowHashesVerified': False, 'eventsExecuted': False}
        self.bytes.write(client.output / 'full-recovery-private.json', result); return result

    def stop(self, node):
        node['stopping'] = True; self.persist()
        self.inspect(node['containerId']); self.docker_call('stop', '--time', '30', node['containerId'], timeout=60)
        row = self.inspect(node['containerId'])
        need(not row['State']['Running'] and not row['State'].get('Restarting') and row['State']['Pid'] == 0, 'Owned recovery did not stop')
        node['stopped'] = True; node['exitCode'] = row['State']['ExitCode']; node['oomKilled'] = bool(row['State'].get('OOMKilled')); self.persist()

    def evidence_bindings(self):
        """Re-read originals and full logical evidence before retiring derived data."""
        snapshot = self.utility.owner_path(self.work / self.bytes.SNAPSHOT, directory=True)
        restored = self.utility.owner_path(self.work / self.bytes.RESTORE, directory=True)
        manifest_file = self.utility.owner_path(snapshot / 'custody.json')
        manifest = self.bytes.read(manifest_file); members = self.bytes.validate_package(manifest)
        receipt_file = self.utility.owner_path(restored / 'restore-receipt.json'); receipt = self.bytes.read(receipt_file)
        need(receipt['status'] == 'BYTES_RESTORED_VERIFIED' and all(receipt.get(key) == value for key, value in self.context.items())
             and receipt['manifestSha256'] == self.bytes.digest(manifest_file)
             and receipt['archiveSha256'] == manifest['archiveSha256'], 'Original byte custody no longer closes before derived cleanup')
        expected = {'custody.json', 'originals.tar.gz'}
        need({entry.name for entry in snapshot.iterdir()} == expected
             and {entry.name for entry in restored.iterdir()} == self.bytes.MEMBERS | {'restore-receipt.json'},
             'Original custody membership changed before derived cleanup')
        files = [manifest_file, receipt_file]
        archive = self.utility.owner_path(snapshot / 'originals.tar.gz')
        need(archive.stat().st_size == manifest['archiveBytes'] and self.bytes.digest(archive) == manifest['archiveSha256'],
             'Original SQL archive changed before derived cleanup')
        files.append(archive)
        for member in members:
            path = self.utility.owner_path(restored / member['member'])
            need(path.stat().st_size == member['bytes'] and self.bytes.digest(path) == member['sha256'],
                 'An original recovered member changed before derived cleanup')
            files.append(path)
        original_public = self.bytes.read(restored / 'public-manifest.json')
        self.bytes.validate_export_metadata(original_public, self.bytes.read(restored / 'export-control-private.json'))
        recovered = []
        for ordinal in ('a', 'b'):
            path = self.utility.owner_path(self.directory / ordinal / 'full-recovery-private.json')
            node = next(item for item in self.state['servers'] if item['ordinal'] == ordinal)
            value = self.bytes.read(path)
            need(value['containerId'] == node['containerId'] and value['volume'] == node['volume']
                 and value['serverUuid'] == node['serverUuid'], 'Full row/schema evidence belongs to another recovered server')
            recovered.append(value); files.append(path)
        compare_recoveries(*recovered)
        files.append(self.utility.owner_path(self.directory / 'resource-probes.jsonl'))
        return {path.relative_to(self.work).as_posix(): self.bytes.digest(path) for path in files}

    def remove_derived(self, node):
        """Only the stopped, independently verified pair has this deletion API."""
        cid, volume = node['containerId'], node['volume']
        labels = {LABEL: self.state['owner'], 'io.doorhandle.release': self.args.tag, 'io.doorhandle.source': self.args.source_sha256}
        if not node.get('containerRemoved'):
            row = self.inspect(cid)
            need(not row['State']['Running'] and row['State']['Pid'] == 0 and row['State']['ExitCode'] == 0
                 and not row['State'].get('OOMKilled'), 'Only a successfully stopped derived recovery can be removed')
            refs = self.docker_call('ps', '-aq', '--no-trunc', '--filter', 'volume=' + volume).decode().split()
            need(refs == [cid], 'Another container references this recovery volume')
            need(self.docker_call('rm', cid).decode().strip() == cid, 'Owned derived container removal did not confirm its exact identity')
            need(not self.docker_call('ps', '-aq', '--no-trunc', '--filter', 'id=' + cid).strip(), 'Derived container is still present')
            node['containerRemoved'] = True; self.persist()
        else:
            need(not self.docker_call('ps', '-aq', '--no-trunc', '--filter', 'id=' + cid).strip(), 'Removed derived container reappeared')
        if not node.get('volumeRemoved'):
            row = json.loads(self.docker_call('volume', 'inspect', volume))[0]
            need(row['Name'] == volume and row['Driver'] == 'local' and not row.get('Options') and row.get('Labels') == labels,
                 'Derived volume identity/owner changed before removal')
            need(not self.docker_call('ps', '-aq', '--no-trunc', '--filter', 'volume=' + volume).strip(), 'A container still references derived data')
            need(self.docker_call('volume', 'rm', volume).decode().strip() == volume, 'Exact derived volume removal was not confirmed')
            need(volume not in self.docker_call('volume', 'ls', '--format', '{{.Name}}').decode().splitlines(), 'Derived volume is still present')
            node['volumeRemoved'] = True; self.persist()
        else:
            need(volume not in self.docker_call('volume', 'ls', '--format', '{{.Name}}').decode().splitlines(), 'Removed derived volume reappeared')

    def run(self):
        need(not self.owner_file.exists() and not self.directory.exists(), 'SQL double recovery requires a fresh attempt')
        restored = self.utility.owner_path(self.work / self.bytes.RESTORE, directory=True)
        receipt = self.bytes.read(self.utility.owner_path(restored / 'restore-receipt.json'))
        need(receipt['status'] == 'BYTES_RESTORED_VERIFIED' and all(receipt.get(k) == v for k, v in self.context.items())
             and self.bytes.digest(restored / 'database.sql') == self.bytes.RAW_SHA, 'Actual same-build byte recovery is required before MySQL')
        settings = self.bytes.read(self.utility.owner_path(self.args.fixture_settings)); cid = settings.get('sourceMysqlContainerId', '')
        need(CID.fullmatch(cid), 'The existing fixture settings must identify the original image source')
        # Deliberately no original DB connection or original mount/env inspection.
        image = self.docker_call('inspect', '--format', '{{.Image}}', cid).decode().strip()
        need(IMAGE.fullmatch(image), 'An existing immutable MySQL image is required')
        need(self.docker_call('image', 'inspect', '--format', '{{.Id}}', image).decode().strip() == image, 'The cached MySQL image identity changed')
        self.utility.resource_guard(self.work, 1536 * MIB + 6 * self.bytes.RAW_BYTES)
        with self.creation_lock():
            self.guard()
            need(not self.owner_file.exists() and not self.directory.exists(), 'A recovery owner appeared during admission')
            self.utility.private_directory(self.directory)
            self.original = cid; self.state = {**self.context, 'directory': str(self.directory), 'owner': secrets.token_hex(12),
                'originalContainerId': cid, 'mysqlImage': image, 'byteReceiptSha256': self.bytes.digest(restored / 'restore-receipt.json'),
                'fixtureSettingsSha256': self.bytes.digest(self.args.fixture_settings), 'servers': [], 'status': 'PREPARING'}
            self.persist()
        self.runtime = load_runtime()
        catalog = [json.loads(line)['table'] for line in (restored / 'before-catalog-private.jsonl').read_text().splitlines()]
        counts = {row['table']: row['rows'] for row in (json.loads(line) for line in (restored / 'before-row-counts-private.jsonl').read_text().splitlines())}
        need(len(set(catalog)) == len(catalog) == len(counts) == 45, 'The complete original project table catalogue is required')
        watcher = threading.Thread(target=self.watch, daemon=True); watcher.start(); results = []
        try:
            for ordinal in ('a', 'b'):
                node, client = self.start(ordinal); self.import_original(client, restored / 'database.sql')
                results.append(self.capture(node, client, catalog, counts)); self.stop(node)
            self.guard(); compare_recoveries(*results)
            need(all(node.get('peakBytes', 0) > 0 for node in self.state['servers']), 'Recovery MySQL has no actual cgroup peak evidence')
        finally:
            self.cancel.set(); watcher.join(timeout=10)
            need(not watcher.is_alive(), 'Recovery resource observer did not stop')
            for node in self.state['servers']: self.stop(node)
        self.guard()
        need(all(node['exitCode'] == 0 and node['oomKilled'] is False for node in self.state['servers']),
             'A failed/OOM recovery server cannot supply a successful double-restore receipt')
        bindings = self.evidence_bindings()
        public = {**self.context, 'status': 'SQL_DOUBLE_RESTORED_VERIFIED', 'tableCount': 45,
            'restoredRows': sum(row['rows'] for row in results[0]['snapshot']['tables'].values()),
            'rawSqlSha256': self.bytes.RAW_SHA, 'gzipSha256': self.bytes.GZIP_SHA,
            'byteReceiptSha256': self.state['byteReceiptSha256'], 'snapshotSha256': results[0]['snapshot']['snapshotSha256'],
            'metadataSha256': results[0]['metadataSha256'], 'constraintDefectCount': sum(row['violations'] for row in results[0]['findings']),
            'allOriginalRowsPreserved': True, 'liveSourceRowHashesVerified': False, 'productionMerged': False, 'retirementAllowed': False,
            'constraintsSatisfied': not results[0]['findings'], 'eventsExecuted': False, 'paidModelCalls': 0,
            'resourceProbeSha256': self.bytes.digest(self.directory / 'resource-probes.jsonl'), 'cleanup': 'STOPPED'}
        public['logicalEvidenceCatalogueSha256'] = self.bytes.sha(bindings)
        self.bytes.write(self.directory / 'public-recovery.json', public)
        self.state.update(status='SQL_DOUBLE_RESTORED_VERIFIED', cleanupEvidence=bindings,
                          publicRecoverySha256=self.bytes.digest(self.directory / 'public-recovery.json')); self.persist()
        return {**public, 'recoveryReceiptSha256': self.bytes.digest(self.directory / 'public-recovery.json')}

    def cleanup(self):
        cancel = self.utility.safe(self.work / 'local-mysql-recovery-cancel.json', exists=False)
        if cancel.exists(): need(self.bytes.read(self.utility.owner_path(cancel)) == self.context, 'Recovery cancellation belongs to another source')
        else: self.bytes.write(cancel, self.context)
        with self.creation_lock(): return self.cleanup_locked()

    def cleanup_locked(self):
        # __init__ already revalidated the immutable source and actual ECS
        # identity. Absence is provable only before any recovery owner/directory
        # exists; never fabricate an owner state for an interrupted attempt.
        if self.state is None and not self.owner_file.exists():
            self.utility.safe(self.owner_file, exists=False)
            self.utility.safe(self.directory, exists=False)
            need(not self.directory.exists(), 'A partial recovery directory has no usable owner receipt; retain it for investigation')
            result = {**self.context, 'status': 'NOT_CREATED', 'containers': [], 'originalsChanged': False,
                'derivedContainersRemoved': 0, 'derivedVolumesRemoved': 0, 'derivedVolumesRetained': 0,
                'recoveryVolumesRetained': False, 'rawSqlSha256': self.bytes.RAW_SHA}
            path = self.work / 'local-mysql-recovery-not-created.json'
            if path.exists(): need(self.bytes.read(self.utility.owner_path(path)) == result, 'Existing not-created cleanup receipt differs')
            else: self.bytes.write(path, result)
            return {**result, 'cleanupReceiptSha256': self.bytes.digest(path)}
        self.load(); stopped = []
        # Recover a create/receipt interruption using only this run's persisted
        # exact name/volume intents and cryptographic owner labels.
        cids = self.docker_call('ps', '-aq', '--no-trunc', '--filter', 'label=' + LABEL + '=' + self.state['owner']).decode().split()
        for cid in cids:
            if any(node['containerId'] == cid for node in self.state['servers']): continue
            row = json.loads(self.docker_call('inspect', cid))[0]
            intent = next((item for item in self.state.get('containerIntents', []) if row['Name'] == '/' + item['name']), None)
            need(intent is not None and row['Image'] == self.state['mysqlImage'] and cid != self.original,
                 'Cleanup cannot adopt an unknown container')
            self.state['servers'].append({**intent, 'containerId': cid, 'peakBytes': 0}); self.inspect(cid); self.persist()
        for node in self.state['servers']:
            if not node.get('containerRemoved'): self.stop(node)
            stopped.append(node['containerId'])
        for ordinal in ('a', 'b'):
            file = self.directory / ('mysql-' + ordinal + '.env')
            if file.exists():
                self.utility.owner_path(file); file.unlink()
        if self.state.get('status') == 'SQL_DOUBLE_RESTORED_VERIFIED':
            need(len(self.state['servers']) == 2 and {node['ordinal'] for node in self.state['servers']} == {'a', 'b'}
                 and self.state.get('cleanupEvidence') == self.evidence_bindings()
                 and self.state.get('publicRecoverySha256') == self.bytes.digest(self.utility.owner_path(self.directory / 'public-recovery.json')),
                 'Complete original archive and double-restore evidence are required for derived data cleanup')
            for node in self.state['servers']: self.remove_derived(node)
        intended = {item['volume'] for item in self.state.get('containerIntents', [])}
        intended.update(node['volume'] for node in self.state['servers'])
        present = set(self.docker_call('volume', 'ls', '--format', '{{.Name}}').decode().splitlines())
        remaining = sorted(intended & present)
        labels = {LABEL: self.state['owner'], 'io.doorhandle.release': self.args.tag, 'io.doorhandle.source': self.args.source_sha256}
        for name in remaining:
            row = json.loads(self.docker_call('volume', 'inspect', name))[0]
            need(row['Name'] == name and row['Driver'] == 'local' and not row.get('Options') and row.get('Labels') == labels,
                 'A retained create-intent volume cannot be attributed to this attempt')
        result = {**self.context, 'status': 'STOPPED', 'containers': stopped, 'originalsChanged': False,
            'derivedContainersRemoved': sum(node.get('containerRemoved') is True for node in self.state['servers']),
            'derivedVolumesRemoved': sum(node.get('volumeRemoved') is True for node in self.state['servers']),
            'derivedVolumesRetained': len(remaining), 'recoveryVolumesRetained': bool(remaining),
            'rawSqlSha256': self.bytes.RAW_SHA}
        path = self.directory / 'public-cleanup.json'
        if path.exists(): need(self.bytes.read(self.utility.owner_path(path)) == result, 'Existing cleanup receipt differs from actual resources')
        else: self.bytes.write(path, result)
        return {**result, 'cleanupReceiptSha256': self.bytes.digest(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('action', choices=('run', 'cleanup'))
    for key in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id'): parser.add_argument('--' + key, required=True)
    parser.add_argument('--fixture-settings'); args = parser.parse_args(); controller = None
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(event, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        controller = Recovery(args)
        result = controller.run() if args.action == 'run' else controller.cleanup()
        print(json.dumps(result)); return 0
    except BaseException as error:
        if controller and controller.state:
            with contextlib.suppress(Exception): controller.cleanup()
        print(json.dumps({'kind': 'doorhandle-local-mysql-recovery', 'status': 'UNKNOWN' if isinstance(error,CleanupNotQuiescent) else 'FAILED', 'errorType': type(error).__name__,
                          'productionMerged': False, 'retirementAllowed': False})); return 2


if __name__ == '__main__': raise SystemExit(main())
