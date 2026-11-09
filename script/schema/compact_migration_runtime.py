"""Shared, explicit ECS-only compact migration/restore primitives.

No environment fallback, cloud lifecycle operation, source mutation, constraint
disabling, compatibility table, application startup, or automatic retry lives here.
Runtime credentials and data dumps remain in the admitted checkout/work directory.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from ecs_execution import require_ecs_execution
from build_compact_schema import GUARD_RESOURCES, compile_schema, split_top_level, without_comments
import compact_clock_policy as clocks

IDENT = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')
UUID = re.compile(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z')
SHA = re.compile(r'[a-f0-9]{64}\Z')
WORKBENCH_SOURCES = {'agent_workbench_item', 'agent_workbench_request', 'agent_workbench_audit'}
MAX_PRIVATE_JSON = 16 * 1024 * 1024
MAX_DUMP_BYTES = 4 * 1024 * 1024 * 1024
MAX_QUERY_BYTES = 64 * 1024 * 1024
MAX_KEYED_ROWS_PER_TABLE = 50_000
MAX_KEYED_ROW_BYTES_PER_TABLE = 16 * 1024 * 1024
MAX_KEYED_ROWS_TOTAL = 250_000
MAX_KEYED_ROW_BYTES_TOTAL = 64 * 1024 * 1024
KEYED_ROW_LINE = re.compile(rb'\{"keySha256":"([a-f0-9]{64})","rowSha256":"([a-f0-9]{64})"\}\n')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf8')


def sha_json(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def row_hash_expression(columns):
    """Keep SQL NULL, empty values and complete original binary bytes distinct."""
    require(isinstance(columns, (list, tuple)) and columns and len(columns) == len(set(columns)),
            'A complete ordered, unique column vector is required for row hashing')
    chunks = ["IF(" + quoted(column) + " IS NULL,'N;',CONCAT('V',OCTET_LENGTH(CAST(" + quoted(column)
              + " AS BINARY)),':',HEX(CAST(" + quoted(column) + " AS BINARY)),';'))" for column in columns]
    return 'SHA2(CONCAT(' + ','.join(chunks) + '),256)'


def keyed_row_output(path):
    """Open one new, owner-only sidecar in an already admitted private folder."""
    path = Path(path)
    require(path.is_absolute() and path.is_relative_to(ROOT / 'work')
            and path.parent.resolve(strict=True) == path.parent and not path.exists()
            and not path.is_symlink(), 'Use a new canonical keyed-row file below checkout/work')
    parent = path.parent.stat()
    require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.getuid()
            and stat.S_IMODE(parent.st_mode) == 0o700, 'Keyed-row parent must be private and owned')
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags, 0o600)
    return os.fdopen(descriptor, 'wb')


def keyed_row_inventory(path, expected_rows, expected_chain):
    """Independently reread a fresh sidecar before it can enter an index."""
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path
            and path.is_relative_to(ROOT / 'work') and not path.is_symlink(),
            'A canonical keyed-row sidecar below checkout/work is required')
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
            and stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1
            and before.st_size <= MAX_KEYED_ROW_BYTES_PER_TABLE,
            'Keyed-row evidence must be bounded, private, regular and unlinked')
    signature = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
                               value.st_ctime_ns, value.st_nlink, value.st_uid, value.st_mode)
    raw_digest, chain = hashlib.sha256(), hashlib.sha256(b'compact-row-hash-chain-v1\n')
    keys, count, size = set(), 0, 0
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as source:
        require(signature(os.fstat(source.fileno())) == signature(before), 'Keyed-row file changed before reread')
        while True:
            line = source.readline(192)
            if not line:
                break
            match = KEYED_ROW_LINE.fullmatch(line)
            require(match is not None, 'Keyed-row file must contain complete canonical digest records')
            key, row = match.groups()
            require(key not in keys, 'Duplicate complete primary-key digest in keyed-row evidence')
            keys.add(key); count += 1; size += len(line)
            require(count <= MAX_KEYED_ROWS_PER_TABLE and size <= MAX_KEYED_ROW_BYTES_PER_TABLE,
                    'Keyed-row evidence exceeds the per-table limit')
            raw_digest.update(line); chain.update(bytes.fromhex(row.decode('ascii')))
        require(signature(os.fstat(source.fileno())) == signature(before)
                and signature(path.lstat()) == signature(before), 'Keyed-row file changed during reread')
    require(count == expected_rows and chain.hexdigest() == expected_chain and size == before.st_size,
            'Keyed-row index differs from the complete actual table row chain')
    return {'file': path.name, 'fileSha256': raw_digest.hexdigest(), 'bytes': size, 'entries': count}


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate private JSON key')
        result[key] = value
    return result


def private_json(path, *, below_work=True):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path and path.is_file(),
            'Private JSON must be an existing canonical absolute regular file')
    if below_work:
        require(path.is_relative_to(ROOT / 'work'), 'Private JSON must remain in this checkout/work')
    require(path.stat().st_uid == os.getuid() and not stat.S_IMODE(path.stat().st_mode) & 0o077,
            'Private JSON must belong to the current Unix account and have owner-only permissions')
    require(path.stat().st_size <= MAX_PRIVATE_JSON, 'Private JSON exceeds the size limit')
    raw = path.read_bytes()
    return path, json.loads(raw, object_pairs_hook=no_duplicate_keys), hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path = Path(path)
    with path.open('x', encoding='utf8') as output:
        os.chmod(path, 0o600)
        json.dump(value, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write('\n')


def fresh_output(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and path.is_relative_to(ROOT / 'work'),
            'Use a fresh canonical absolute output below this checkout/work')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir(mode=0o700)
    (path / 'private').mkdir(mode=0o700)
    return path


def identifier(value):
    require(isinstance(value, str) and IDENT.fullmatch(value), 'Invalid explicit MySQL identifier')
    return value


def quoted(value):
    return '`' + identifier(value) + '`'


def literal(value):
    require(isinstance(value, str) and '\x00' not in value, 'Invalid SQL literal')
    # SQL_MODE is explicitly set without NO_BACKSLASH_ESCAPES for every connection.
    return "'" + value.replace('\\', '\\\\').replace("'", "''") + "'"


def executable(path):
    path = Path(path)
    require(path.is_absolute() and path.is_file() and path.resolve() == path,
            'Select an existing canonical absolute executable')
    return path


def load_config(path):
    identity = require_ecs_execution()
    require(identity['instanceId'] == 'i-2zeieuov2aum486jm1ek', 'Compact migration is admitted only on the monolith ECS')
    admitted_path, config, digest = private_json(path)
    allowed = {'version', 'scope', 'instanceId', 'machineId', 'serverUuid', 'sourceSchema', 'targetSchema',
               'connection', 'client', 'sourceOffsets', 'sourceCollations', 'workbench', 'recoverySchemas',
               'reviewedSourceSnapshot', 'reviewedSourceSnapshotSha256', 'freezeEvidenceFile',
               'freezeEvidenceSha256', 'dataDirectory', 'legacyClockPolicy'}
    require(isinstance(config, dict) and not set(config) - allowed and type(config.get('version')) is int
            and config['version'] == 1, 'Unsupported migration configuration shape')
    require(all(config.get(key) == identity[key] for key in ('instanceId', 'machineId')),
            'Configuration and actual admitted ECS identity differ')
    require(config.get('scope') in ('ecs-disposable-migration', 'production-migration'), 'Explicit migration scope required')
    require(isinstance(config.get('serverUuid'), str) and UUID.fullmatch(config['serverUuid']),
            'Previously reviewed MySQL UUID required')
    source = identifier(config.get('sourceSchema'))
    target = identifier(config.get('targetSchema'))
    require(source != target and re.fullmatch(r'doorhandle_compact_candidate_[a-f0-9]{10}', target),
            'A distinct new compact candidate schema is required')
    connection = config.get('connection')
    require(isinstance(connection, dict) and set(connection) == {'host', 'port', 'username', 'password'},
            'Only explicit local MySQL connection fields are accepted')
    require(isinstance(connection['host'], str) and type(connection['port']) is int
            and 1 <= connection['port'] <= 65535,
            'Use an explicit admitted MySQL address and port')
    require(isinstance(connection['username'], str) and re.fullmatch(r'[a-z_][a-z0-9_]{0,31}', connection['username'])
            and isinstance(connection['password'], str) and connection['password']
            and '\x00' not in connection['password'], 'Explicit dedicated migration credentials required')
    if config['scope'] == 'ecs-disposable-migration':
        require(connection['host'] == '127.0.0.1' and 1024 < connection['port'] <= 65535 and connection['port'] != 3306,
                'Disposable migration must use its owned non-default loopback MySQL port')
        require(re.fullmatch(r'doorhandle_(?:migration|legacy|agent)_verify_[a-f0-9]{10}', source),
                'Disposable migration source needs an admitted verification schema name')
        require(connection['username'].startswith(('ecsit_', 'mig_')), 'Disposable migration needs a dedicated account')
        data = Path(config.get('dataDirectory', ''))
        require(data.is_absolute() and data.is_dir() and data.resolve(strict=True) == data
                and data.is_relative_to(admitted_path.parent), 'Disposable MySQL data directory must be inside its private attempt')
    recovery = config.get('recoverySchemas')
    require(isinstance(recovery, dict) and set(recovery) == {'source', 'target'}
            and re.fullmatch(r'doorhandle_legacy_restore_[a-f0-9]{10}', recovery['source'])
            and re.fullmatch(r'doorhandle_compact_restore_[a-f0-9]{10}', recovery['target'])
            and len({source, target, *recovery.values()}) == 4,
            'Two distinct new source/target recovery-proof schemas are required')
    require(isinstance(config.get('sourceOffsets'), dict) and isinstance(config.get('sourceCollations'), dict),
            'Explicit reviewed domain offsets and all source table collations required')
    clocks.validate(config['sourceOffsets'], config.get('legacyClockPolicy'))
    config['_admittedConfigDirectory'] = str(admitted_path.parent)
    return config, identity, digest


class Mysql:
    """Existing native or container mysql client; passwords only enter a private stdin option file."""

    def __init__(self, config, output):
        self.config = config
        self.output = Path(output)
        self.sequence = 0
        client = config.get('client')
        require(isinstance(client, dict) and client.get('kind') in ('native', 'docker'), 'Explicit existing mysql client required')
        self.program = executable(client.get('executable', ''))
        self.kind = client['kind']
        connection = config['connection']
        def ini(value):
            return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') + '"'
        port = connection['port'] if self.kind == 'native' or config['scope'] == 'ecs-disposable-migration' else 3306
        self.options = ('[client]\nprotocol=tcp\nhost=127.0.0.1\nport=' + str(port)
                        + '\nuser=' + ini(connection['username']) + '\npassword=' + ini(connection['password'])
                        + '\nconnect-timeout=10\n').encode('utf8')
        if self.kind == 'native':
            require(set(client) == {'kind', 'executable', 'mysqldump'}, 'Native client also needs an existing mysqldump')
            self.dump_program = executable(client['mysqldump'])
            self.option_file = self.output / 'private' / 'mysql-client.cnf'
            with self.option_file.open('xb') as target:
                os.chmod(self.option_file, 0o600)
                target.write(self.options)
        else:
            require(set(client) == {'kind', 'executable', 'containerId'}
                    and re.fullmatch(r'[a-f0-9]{64}', client['containerId']), 'Exact owned MySQL container ID required')
            self.container = client['containerId']
            result = subprocess.run([str(self.program), 'inspect', self.container], capture_output=True,
                                    timeout=15, check=True, env=self.environment())
            node = json.loads(result.stdout)[0]
            require(node.get('Id') == self.container and node.get('State', {}).get('Running') is True,
                    'The admitted owned MySQL container is not running')
            if config['scope'] == 'ecs-disposable-migration':
                bindings = node.get('NetworkSettings', {}).get('Ports', {}).get(str(connection['port']) + '/tcp') or []
                require(len(bindings) == 1 and bindings[0].get('HostIp') == '127.0.0.1'
                        and bindings[0].get('HostPort') == str(connection['port']),
                        'Disposable MySQL port is not exclusively bound to the admitted loopback port')
                mounts = [item for item in node.get('Mounts', []) if item.get('Source') == config['dataDirectory']
                          and item.get('Destination', '').rstrip('/') == config['dataDirectory'].rstrip('/')
                          and item.get('Type') == 'bind' and item.get('RW') is True]
                require(len(mounts) == 1, 'Disposable MySQL requires an exact same-absolute-path owned data bind mount')
                self.container_data_directory = mounts[0]['Destination'].rstrip('/') + '/'
            if connection['host'] != '127.0.0.1':
                addresses = {network.get('IPAddress') for network in node.get('NetworkSettings', {}).get('Networks', {}).values()}
                require(config['scope'] == 'production-migration' and connection['port'] == 3306
                        and connection['host'] in addresses and re.fullmatch(r'[0-9.]+', connection['host']),
                        'Production JDBC endpoint is not the admitted MySQL container bridge address')
        if self.kind == 'native':
            require(connection['host'] == '127.0.0.1', 'Native client migration is restricted to the same ECS loopback')

    @staticmethod
    def environment():
        return {key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')}

    def command(self, database=None, *, dump=False, table_names=()):
        arguments = ['--no-login-paths', '--default-character-set=utf8mb4']
        if dump:
            arguments += ['--single-transaction', '--skip-lock-tables', '--skip-add-locks', '--skip-disable-keys',
                          '--skip-add-drop-table', '--no-create-info', '--skip-triggers', '--complete-insert',
                          '--hex-blob', '--skip-extended-insert', '--set-gtid-purged=OFF', '--no-tablespaces', '--skip-comments']
            arguments += [identifier(database), *[identifier(name) for name in table_names]]
        else:
            arguments += ['--batch', '--raw', '--skip-column-names', '--unbuffered', '--binary-mode', '--local-infile=0']
            if database:
                arguments += ['--database=' + identifier(database)]
        if self.kind == 'native':
            return [str(self.dump_program if dump else self.program), '--defaults-file=' + str(self.option_file), *arguments], b''
        # Only our fixed command is interpreted by the container shell. Passwords
        # are the first N stdin bytes, never argv, environment, command logs or receipts.
        utility = 'mysqldump' if dump else 'mysql'
        import shlex
        shell = ("set -eu; umask 077; f=$(mktemp /tmp/doorhandle-migration-client.XXXXXXXX); "
                 "trap 'rm -f -- \"$f\"' EXIT; head -c " + str(len(self.options)) + " > \"$f\"; "
                 + utility + ' --defaults-file="$f" ' + ' '.join(shlex.quote(item) for item in arguments))
        return [str(self.program), 'exec', '-i', self.container, 'sh', '-c', shell], self.options

    def script(self, sql, *, database=None, label='statement', timeout=3600):
        self.sequence += 1
        key = f'{self.sequence:04d}-{label}'
        require(re.fullmatch(r'[a-z0-9_.-]+', key), 'Invalid private operation label')
        command, prefix = self.command(database)
        input_file = self.output / 'private' / (key + '.input')
        out_file = self.output / 'private' / (key + '.stdout')
        err_file = self.output / 'private' / (key + '.stderr')
        body = sql.encode('utf8') if isinstance(sql, str) else sql
        with input_file.open('xb') as target:
            os.chmod(input_file, 0o600)
            target.write(prefix)
            target.write(b"SET SESSION time_zone='+00:00'; SET SESSION sql_mode='STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION,NO_AUTO_VALUE_ON_ZERO';\n")
            target.write(body)
        with input_file.open('rb') as source, out_file.open('xb') as stdout, err_file.open('xb') as stderr:
            os.chmod(out_file, 0o600); os.chmod(err_file, 0o600)
            process = subprocess.run(command, stdin=source, stdout=stdout, stderr=stderr, env=self.environment(), timeout=timeout)
        require(process.returncode == 0, 'MySQL operation failed; private operation evidence retained: ' + key)
        require(out_file.stat().st_size <= MAX_QUERY_BYTES, 'MySQL response exceeds the bounded query size')
        return out_file.read_bytes()

    def json_rows(self, sql, *, database=None):
        return [json.loads(line) for line in self.script(sql, database=database, label='catalog').splitlines() if line]

    def single(self, sql, *, database=None):
        rows = self.json_rows(sql, database=database)
        require(len(rows) == 1, 'Expected exactly one catalog result')
        return rows[0]

    def admitted_server(self):
        value = self.single("SELECT JSON_OBJECT('serverUuid',@@server_uuid,'version',@@version,'serverPort',@@port,'foreignKeyChecks',@@foreign_key_checks,'currentUser',CURRENT_USER(),'dataDirectory',@@datadir);")
        require(value['serverUuid'] == self.config['serverUuid'] and value['version'].startswith('8.4.')
                and value['foreignKeyChecks'] == 1, 'MySQL server, version or foreign-key enforcement differs')
        if self.config['scope'] == 'ecs-disposable-migration':
            expected = self.container_data_directory if self.kind == 'docker' else self.config['dataDirectory'].rstrip('/') + '/'
            require(value['dataDirectory'].rstrip('/') + '/' == expected and value['serverPort'] == self.config['connection']['port'],
                    'Actual disposable MySQL storage or server port differs from the admitted fixture')
        return value

    @contextmanager
    def source_lock(self, schema, tables):
        command, prefix = self.command(schema)
        marker = 'compact_source_locked_' + uuid.uuid4().hex
        error_path = self.output / 'private' / (marker + '.stderr')
        with error_path.open('xb') as stderr:
            os.chmod(error_path, 0o600)
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                                       env=self.environment(), start_new_session=True)
            selector = selectors.DefaultSelector()
            try:
                selector.register(process.stdout, selectors.EVENT_READ)
                sql = "SET SESSION lock_wait_timeout=30; SET SESSION innodb_lock_wait_timeout=30; LOCK TABLES "
                sql += ','.join(quoted(schema) + '.' + quoted(table) + ' READ' for table in sorted(tables))
                sql += '; SELECT ' + literal(marker) + ';\n'
                process.stdin.write(prefix + sql.encode('utf8')); process.stdin.flush()
                require(bool(selector.select(40)), 'Source read-lock acquisition timed out')
                require(process.stdout.readline().decode('ascii').strip() == marker and process.poll() is None,
                        'The complete source read-lock was not acquired')
                self.source_lock_process = process
                yield {'kind': 'MYSQL_LOCK_TABLES_READ', 'sourceTableCount': len(tables), 'acquiredAtUtc': utc_now()}
                require(process.poll() is None, 'Source lock session ended before verification completed')
            finally:
                self.source_lock_process = None
                selector.close()
                if process.poll() is None:
                    try:
                        process.stdin.write(b'UNLOCK TABLES;\n'); process.stdin.close()
                        process.wait(timeout=10)
                    except (BrokenPipeError, subprocess.TimeoutExpired):
                        os.killpg(process.pid, signal.SIGTERM)
                        process.wait(timeout=10)
                process.stdout.close()

    def assert_source_lock(self):
        process = getattr(self, 'source_lock_process', None)
        require(process is not None and process.poll() is None, 'The independent complete source read-lock session is no longer alive')

    def row_hashes(self, schema, table, columns, primary, *, keyed_rows_path=None):
        expression = row_hash_expression(columns)
        capture = keyed_rows_path is not None
        require(not capture or primary and len(primary) == len(set(primary)) and set(primary) <= set(columns),
                'Keyed-row capture requires the complete nonempty ordered primary key')
        order = ','.join(quoted(column) for column in primary) if primary else 'row_sha'
        selected = (row_hash_expression(primary) + ' AS key_sha,' if capture else '') + expression
        sql = ("SET SESSION time_zone='+00:00'; SELECT " + selected + ' AS row_sha FROM '
               + quoted(schema) + '.' + quoted(table) + ' ORDER BY ' + order + ';\n')
        command, prefix = self.command()
        error_file = self.output / 'private' / ('snapshot-' + schema + '-' + table + '.stderr-' + uuid.uuid4().hex)
        count, digest = 0, hashlib.sha256(b'compact-row-hash-chain-v1\n')
        keyed_output, keyed_bytes, seen_keys = None, 0, set()
        with error_file.open('xb') as stderr:
            os.chmod(error_file, 0o600)
            process, selector = None, None
            try:
                if capture:
                    keyed_output = keyed_row_output(keyed_rows_path)
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, env=self.environment())
                selector = selectors.DefaultSelector()
                pending, deadline = b'', time.monotonic() + 3600
                process.stdin.write(prefix + sql.encode('utf8')); process.stdin.close()
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    require(remaining > 0 and selector.select(min(60, remaining)), 'Full-table row hashing stream timed out')
                    block = os.read(process.stdout.fileno(), 65536)
                    if not block:
                        break
                    pending += block
                    lines = pending.split(b'\n'); pending = lines.pop()
                    require(len(pending) <= (129 if capture else 64), 'Unexpected partial row hash length')
                    for line in lines:
                        parts = line.split(b'\t') if capture else [line]
                        require(len(parts) == (2 if capture else 1)
                                and all(len(part) == 64 and re.fullmatch(rb'[a-f0-9]{64}', part) for part in parts),
                                'Unexpected source row hash response')
                        row_sha = parts[-1]
                        if capture:
                            key_sha = parts[0]
                            require(key_sha not in seen_keys, 'Duplicate complete primary-key digest in source rows')
                            seen_keys.add(key_sha)
                            record = canonical({'keySha256': key_sha.decode('ascii'), 'rowSha256': row_sha.decode('ascii')}) + b'\n'
                            keyed_bytes += len(record)
                            require(count < MAX_KEYED_ROWS_PER_TABLE and keyed_bytes <= MAX_KEYED_ROW_BYTES_PER_TABLE,
                                    'Keyed-row capture exceeds the per-table limit')
                            keyed_output.write(record)
                        digest.update(bytes.fromhex(row_sha.decode('ascii'))); count += 1
                require(not pending and process.wait(timeout=30) == 0, 'Full-table row hashing failed; private error retained')
                if keyed_output is not None:
                    keyed_output.flush(); os.fsync(keyed_output.fileno())
            finally:
                if keyed_output is not None:
                    keyed_output.close()
                if selector is not None:
                    selector.close()
                if process is not None:
                    process.stdout.close()
                if process is not None and process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=10)
        return count, digest.hexdigest()

    def data_dump(self, schema, tables, path):
        command, prefix = self.command(schema, dump=True, table_names=sorted(tables))
        errors = path.with_suffix('.stderr')
        with path.open('xb') as target, errors.open('xb') as stderr:
            os.chmod(path, 0o600); os.chmod(errors, 0o600)
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, env=self.environment())
            selector = selectors.DefaultSelector()
            written, deadline = 0, time.monotonic() + 3600
            try:
                process.stdin.write(prefix); process.stdin.close()
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    require(remaining > 0 and selector.select(min(60, remaining)), 'Private backup stream timed out')
                    block = os.read(process.stdout.fileno(), 1024 * 1024)
                    if not block:
                        break
                    written += len(block)
                    space = os.statvfs(path.parent)
                    require(written <= MAX_DUMP_BYTES and space.f_bavail * space.f_frsize > len(block) + 64 * 1024 * 1024,
                            'Private backup exceeds its size budget or the ECS has insufficient remaining disk')
                    target.write(block)
                require(process.wait(timeout=30) == 0, 'Private data backup failed; private diagnostics retained')
            finally:
                selector.close(); process.stdout.close()
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=10)
        return {'file': str(path), 'sha256': sha_file(path), 'bytes': path.stat().st_size}


def schema_tables(mysql, schema):
    rows = mysql.json_rows("SELECT JSON_OBJECT('name',TABLE_NAME,'kind',TABLE_TYPE,'engine',ENGINE,'collation',TABLE_COLLATION) "
                           "FROM information_schema.tables WHERE table_schema=" + literal(schema) + ' ORDER BY TABLE_NAME;')
    require(all(row['kind'] == 'BASE TABLE' and row['engine'] == 'InnoDB' for row in rows),
            'Migration sources/targets cannot contain views or non-InnoDB tables')
    return rows


def normalize_self(sql, schema, replacement='$SELF'):
    strings = []
    def save(match):
        strings.append(match.group(0))
        return '\x01' + str(len(strings) - 1) + '\x02'
    masked = re.sub(r"'(?:''|\\.|[^'\\])*'|\"(?:\"\"|\\.|[^\"\\])*\"", save, sql)
    masked = re.sub(r'`' + re.escape(schema) + r'`\s*\.', '`' + replacement + '`.', masked)
    return re.sub(r'\x01(\d+)\x02', lambda match: strings[int(match.group(1))], masked)


def show_create(mysql, schema, table):
    raw = mysql.script('SHOW CREATE TABLE ' + quoted(schema) + '.' + quoted(table) + ';', label='show-create').decode('utf8')
    require('\t' in raw, 'SHOW CREATE TABLE did not return its complete DDL')
    return raw.split('\t', 1)[1].rstrip('\r\n')


def schema_snapshot(mysql, schema, expected_tables, *, keyed_rows_directory=None):
    """Every ordinary/generated column, all rows, keys, DDL, clocks and high-water marks."""
    actual = schema_tables(mysql, schema)
    require({row['name'] for row in actual} == set(expected_tables), 'Actual complete table catalog differs from the admitted schema')
    keyed_directory = None
    if keyed_rows_directory is not None:
        keyed_directory = Path(keyed_rows_directory)
        require(keyed_directory.is_absolute() and keyed_directory.is_relative_to(ROOT / 'work')
                and keyed_directory.parent.resolve(strict=True) == keyed_directory.parent
                and not keyed_directory.exists() and not keyed_directory.is_symlink(),
                'Use a new canonical keyed-row directory below checkout/work')
        keyed_directory.mkdir(mode=0o700)
        directory_info = keyed_directory.stat()
        require(directory_info.st_uid == os.getuid() and stat.S_IMODE(directory_info.st_mode) == 0o700,
                'Keyed-row directory must be private and owned')
    result, keyed_tables, keyed_rows, keyed_bytes = {}, {}, 0, 0
    for row in actual:
        name = row['name']
        where = 'table_schema=' + literal(schema) + ' AND table_name=' + literal(name)
        columns = mysql.json_rows("SELECT JSON_OBJECT('name',COLUMN_NAME,'ordinal',ORDINAL_POSITION,'type',COLUMN_TYPE,"
            "'nullable',IS_NULLABLE,'default',COLUMN_DEFAULT,'extra',EXTRA,'generation',GENERATION_EXPRESSION,"
            "'charset',CHARACTER_SET_NAME,'collation',COLLATION_NAME,'datetimePrecision',DATETIME_PRECISION) "
            'FROM information_schema.columns WHERE ' + where + ' ORDER BY ORDINAL_POSITION;')
        indexes = mysql.json_rows("SELECT JSON_OBJECT('name',INDEX_NAME,'ordinal',SEQ_IN_INDEX,'column',COLUMN_NAME,"
            "'expression',EXPRESSION,'nonUnique',NON_UNIQUE,'subPart',SUB_PART,'collation',COLLATION,'type',INDEX_TYPE,'visible',IS_VISIBLE) "
            'FROM information_schema.statistics WHERE ' + where + ' ORDER BY INDEX_NAME,SEQ_IN_INDEX;')
        primary = [item['column'] for item in indexes if item['name'] == 'PRIMARY']
        require(all(primary) or not primary, 'An expression primary key cannot be snapshotted')
        if keyed_directory is not None and primary:
            row_file = keyed_directory / (identifier(name) + '.jsonl')
            count, row_sha = mysql.row_hashes(schema, name, [item['name'] for item in columns], primary,
                                              keyed_rows_path=row_file)
            inventory = keyed_row_inventory(row_file, count, row_sha)
            keyed_rows += count; keyed_bytes += inventory['bytes']
            require(keyed_rows <= MAX_KEYED_ROWS_TOTAL and keyed_bytes <= MAX_KEYED_ROW_BYTES_TOTAL,
                    'Keyed-row index exceeds the complete schema budget')
        else:
            count, row_sha = mysql.row_hashes(schema, name, [item['name'] for item in columns], primary)
            inventory = {'file': None, 'fileSha256': None, 'bytes': 0, 'entries': 0}
        if keyed_directory is not None:
            keyed_tables[name] = {'status': 'KEYED' if primary else 'NO_PRIMARY_KEY', 'rows': count,
                                 'rowsSha256': row_sha, 'columnsSha256': sha_json(columns),
                                 'primary': primary, **inventory}
        sequence = mysql.single("SELECT JSON_OBJECT('autoIncrement',CAST(AUTO_INCREMENT AS CHAR)) FROM information_schema.tables WHERE " + where + ';')
        ddl = show_create(mysql, schema, name)
        result[name] = {'rows': count, 'rowsSha256': row_sha, 'autoIncrement': sequence['autoIncrement'],
                        'columns': columns, 'indexes': indexes, 'collation': row['collation'],
                        'ddl': ddl, 'ddlSha256': hashlib.sha256(normalize_self(ddl, schema).encode('utf8')).hexdigest()}
    payload = {'schemaVersion': 1, 'tables': {name: {key: value for key, value in detail.items() if key != 'ddl'}
                                           for name, detail in result.items()}}
    snapshot = {'schema': schema, 'snapshotSha256': sha_json(payload), **payload,
                'createTables': {name: row['ddl'] for name, row in result.items()}}
    if keyed_directory is not None:
        expected_files = {row['file'] for row in keyed_tables.values() if row['file'] is not None}
        require({entry.name for entry in keyed_directory.iterdir()} == expected_files,
                'The complete keyed-row folder contains unexpected members')
        for row in keyed_tables.values():
            if row['status'] == 'KEYED':
                reread = keyed_row_inventory(keyed_directory / row['file'], row['rows'], row['rowsSha256'])
                require(all(row[key] == value for key, value in reread.items()),
                        'A keyed-row sidecar changed before the complete index was published')
        write_json(keyed_directory / 'index.json', {'schemaVersion': 1, 'kind': 'doorhandle-mysql-keyed-row-index',
                   'schema': schema, 'snapshotSha256': snapshot['snapshotSha256'], 'tables': keyed_tables})
    return snapshot


def metadata_snapshot(mysql, schema):
    # Use the same pure metadata schema as the live deployment guard. Business
    # row hashes intentionally do not enter the upgrade metadata fingerprint.
    import importlib.util
    path = ROOT / 'script/docker/compact-schema-guard.py'
    require(path.is_file(), 'The reviewed compact metadata guard is required')
    spec = importlib.util.spec_from_file_location('doorhandle_compact_schema_guard', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value = module.metadata_snapshot(lambda sql: mysql.json_rows(sql, database=schema))
    return value, module.metadata_sha256(value)


def freeze_evidence(config, identity):
    if config['scope'] == 'ecs-disposable-migration':
        require(not config.get('freezeEvidenceFile') and not config.get('freezeEvidenceSha256'),
                'Disposable proof cannot impersonate a production writer-freeze proof')
        return {'scope': config['scope'], 'kind': 'DISPOSABLE_SOURCE_READ_LOCK', 'sha256': None}
    path, evidence, digest = private_json(config.get('freezeEvidenceFile', ''))
    require(SHA.fullmatch(config.get('freezeEvidenceSha256', '')) and digest == config['freezeEvidenceSha256'],
            'Writer freeze evidence checksum differs')
    require(evidence.get('schemaVersion') == 1 and evidence.get('kind') == 'doorhandle-source-writer-freeze'
            and isinstance(evidence.get('ecs'), dict)
            and all(evidence['ecs'].get(key) == identity[key] for key in ('instanceId', 'machineId'))
            and evidence.get('serverUuid') == config['serverUuid']
            and evidence.get('sourceSchema') == config['sourceSchema'], 'Writer freeze evidence belongs to another source')
    events = evidence.get('eventCatalog')
    require(isinstance(events, list) and sha_json(events) == evidence.get('eventCatalogSha256')
            and all(isinstance(row, dict) and row.get('schema') == config['sourceSchema']
                    and isinstance(row.get('name'), str) and row['name']
                    and row.get('status') in ('DISABLED', 'SLAVESIDE_DISABLED') for row in events)
            and len({row['name'] for row in events}) == len(events),
            'The administrative source event catalog is missing, changed or contains an active writer')
    require(not events, 'Source SQL events need a separately reviewed event restore plan; this table/trigger migration will not silently omit them')
    routines = evidence.get('routineCatalog')
    require(isinstance(routines, list) and not routines and sha_json(routines) == evidence.get('routineCatalogSha256'),
            'The administrative routine catalog must prove this table/trigger-only source has no omitted routines')
    accounts = evidence.get('sourceAccounts')
    require(isinstance(accounts, list) and accounts and all(isinstance(row, dict)
            and isinstance(row.get('user'), str) and row['user'] and row['user'].lower() != 'root'
            and isinstance(row.get('host'), str) and row['host'] and row.get('locked') == 'Y' for row in accounts)
            and len({(row['user'], row['host']) for row in accounts}) == len(accounts),
            'The administrative freeze must bind the complete locked original runtime accounts')
    writers = evidence.get('writerContainers')
    require(isinstance(writers, list) and writers and len(writers) == len(set(writers))
            and all(isinstance(item, str) and re.fullmatch(r'[a-f0-9]{64}', item) for item in writers),
            'Explicit complete stopped source-writer container IDs required')
    client = config['client']
    require(client['kind'] == 'docker', 'Production writer verification requires the existing Docker executable')
    require(client['containerId'] not in writers, 'The MySQL server is not a stopped application writer')
    program = executable(client['executable'])
    response = subprocess.run([str(program), 'inspect', *writers], capture_output=True, timeout=20,
                              check=True, env=Mysql.environment())
    observed = json.loads(response.stdout)
    require({row['Id'] for row in observed} == set(writers) and all(
        row['State']['Running'] is False and row['State']['Restarting'] is False and row['State']['Pid'] == 0
        and row['HostConfig']['RestartPolicy'].get('Name') == 'no'
        for row in observed), 'A source writer is still running; preserve the source and candidate')
    return {'scope': config['scope'], 'kind': evidence['kind'], 'file': str(path), 'sha256': digest,
            'writerContainers': sorted(writers), 'eventCatalogSha256': evidence['eventCatalogSha256'],
            'routineCatalogSha256': evidence['routineCatalogSha256']}


# The workbench bridge is scheduled after its owner/checkpoint and session
# producers; chat evidence must follow the complete session/message producers.
COPY_DEPENDENCIES = {
    '10-core.sql': (), '12-chat-and-fingerprints.sql': ('10-core.sql',),
    '43-workspace.sql': ('10-core.sql', '12-chat-and-fingerprints.sql'),
    '11-duplicate-ticket.sql': ('10-core.sql', '12-chat-and-fingerprints.sql'),
    '25-agent-runs.sql': ('10-core.sql', '43-workspace.sql'),
    '20-knowledge.sql': ('10-core.sql',), '21-research.sql': ('25-agent-runs.sql',),
    '22-skills.sql': ('10-core.sql',), '23-skill-downloads.sql': ('22-skills.sql',),
    '24-chat-evidence.sql': ('12-chat-and-fingerprints.sql', '25-agent-runs.sql', '43-workspace.sql'),
    '26-model-configuration.sql': ('10-core.sql',), '31-conversation-inbox.sql': ('43-workspace.sql',),
    '32-agent-journal.sql': ('25-agent-runs.sql',), '33-sdk-checkpoint.sql': ('43-workspace.sql',),
    'workbench-java': ('25-agent-runs.sql', '26-model-configuration.sql', '33-sdk-checkpoint.sql', '43-workspace.sql'),
    '34-quality-report-workflow.sql': ('10-core.sql', 'workbench-java'),
    '35-research-export.sql': ('21-research.sql', '25-agent-runs.sql'),
    '36-memory-governance.sql': ('10-core.sql', '43-workspace.sql'),
    '37-operations-file-delivery.sql': ('10-core.sql',), '38-model-budget.sql': ('26-model-configuration.sql',),
    '39-organization-binding-audit.sql': ('10-core.sql',), '40-model-operations.sql': ('10-core.sql',),
    '41-infra-operations.sql': ('10-core.sql',), '42-model-file-governance.sql': ('10-core.sql',),
    '44-confirmation-actions.sql': ('25-agent-runs.sql', '43-workspace.sql'),
    '45-context.sql': ('24-chat-evidence.sql', '43-workspace.sql', 'workbench-java'),
    '46-detection-identity.sql': ('10-core.sql',),
    '47-detection-runtime.sql': ('10-core.sql', '46-detection-identity.sql'),
    '48-mcp.sql': ('26-model-configuration.sql', 'workbench-java'),
    '49-digests.sql': ('10-core.sql', '25-agent-runs.sql', '34-quality-report-workflow.sql'),
    '50-owner-locks.sql': ('21-research.sql', '23-skill-downloads.sql'),
}


def copy_plan(contract):
    paths = {path.name: path for path in (ROOT / 'sql/mysql/compact/copy').glob('*.sql')}
    expected = set(COPY_DEPENDENCIES) - {'workbench-java'}
    require(set(paths) == expected, 'The complete reviewed copy plan is missing or has unregistered SQL segments')
    covered, steps, done = set(), [], set()
    while len(done) < len(COPY_DEPENDENCIES):
        ready = sorted(name for name, dependencies in COPY_DEPENDENCIES.items() if name not in done and set(dependencies) <= done)
        require(ready, 'Copy plan has a dependency cycle or missing producer')
        for name in ready:
            if name == 'workbench-java':
                source = ROOT / 'doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/workbench/WorkbenchLegacyMigration.java'
                sources = sorted(WORKBENCH_SOURCES)
                steps.append({'name': name, 'kind': 'java', 'sourceTables': sources, 'sha256': sha_file(source),
                              'requires': list(COPY_DEPENDENCIES[name])})
            else:
                source = paths[name]
                sql = source.read_text(encoding='utf8')
                sources = sorted(set(re.findall(r'`__SOURCE_SCHEMA__`\s*\.\s*`?([a-z][a-z0-9_]*)', sql)))
                require(sources, 'Each SQL segment must declare its actual source relations')
                executable_sql = without_comments(sql)
                require(not re.search(r'\bFOREIGN_KEY_CHECKS\s*=\s*0\b|\b(?:DROP|TRUNCATE)\s+(?:TABLE|DATABASE)\b(?!\s+compact_)', executable_sql, re.I),
                        'A copy segment attempts destructive or constraint-disabling operations')
                steps.append({'name': name, 'kind': 'sql', 'sourceTables': sources, 'sha256': sha_file(source),
                              'requires': list(COPY_DEPENDENCIES[name])})
            covered.update(sources); done.add(name)
    require(covered == set(contract['sourceTables']), 'The actual SQL/Java copy plan does not cover all 131 observed source tables')
    return steps


COLLATION_BINDINGS = {
    '__SOURCE_MODEL_FILE_COLLATION__': ('detection_model_file_journal', 'detection_model_file_retention'),
    '__SOURCE_PENDING_COLLATION__': ('agent_pending_action',), '__SOURCE_AUDIT_COLLATION__': ('agent_action_audit',),
    '__SOURCE_DETECTION_OBJECT_COLLATION__': ('detection_creation_object',),
    '__SOURCE_DETECTION_REVIEW_COLLATION__': ('detection_creation_review',),
}


def render_copy(sql, config, *, source_snapshot_sha256=None):
    clocks.validate(config['sourceOffsets'], config.get('legacyClockPolicy'))
    values = {'__SOURCE_SCHEMA__': identifier(config['sourceSchema'])}
    placeholders = set(re.findall(r'__[A-Za-z0-9_]+__', sql))
    for token in placeholders - values.keys():
        offset = re.fullmatch(r'__SOURCE_([A-Z_]+)_OFFSET__', token)
        mcp_collation = re.fullmatch(r'__SOURCE_(?:MCP|IDENTITY|DIGEST)_COLLATION_([a-z][a-z0-9_]+)__', token)
        if offset:
            key = offset.group(1).lower()
            require(key in config['sourceOffsets'], 'A domain UTC offset has no reviewed source evidence: ' + key)
            values[token] = clocks.offset_literal_value(key, config['sourceOffsets'], config.get('legacyClockPolicy'))
        elif token == '__SOURCE_SNAPSHOT_SHA256__':
            values[token] = clocks.snapshot_binding(source_snapshot_sha256)
        elif token in COLLATION_BINDINGS or mcp_collation:
            names = COLLATION_BINDINGS.get(token, (mcp_collation.group(1),) if mcp_collation else ())
            observed = {config['sourceCollations'].get(name) for name in names}
            require(len(observed) == 1 and None not in observed, 'Copy segment source collations differ or were not reviewed')
            value = observed.pop()
            require(isinstance(value, str) and re.fullmatch(r'utf8mb4_[a-z0-9_]+', value), 'Unsafe source collation')
            values[token] = value
        else:
            raise ValueError('Unregistered copy placeholder: ' + token)
    for token, value in values.items():
        sql = sql.replace(token, value)
    require(not re.search(r'__[A-Za-z0-9_]+__', sql), 'Unresolved copy template value')
    return sql


def remove_inline_foreign_keys(ddl, schema):
    match = re.fullmatch(r'(CREATE\s+TABLE\s+`?[a-z][a-z0-9_]*`?\s*)\((.*)\)(\s*ENGINE\s*=.*)', ddl, re.I | re.S)
    require(match is not None, 'Only actual regular InnoDB CREATE TABLE DDL can be restored')
    prefix, body, suffix = match.groups()
    fields, foreign = [], []
    table = re.search(r'CREATE\s+TABLE\s+`?([a-z][a-z0-9_]*)', prefix, re.I).group(1)
    for field in split_top_level(body, ','):
        if re.match(r'(?:CONSTRAINT\s+`?\w+`?\s+)?FOREIGN\s+KEY\b', field, re.I):
            foreign.append('ALTER TABLE ' + quoted(schema) + '.' + quoted(table) + ' ADD ' + field)
        else:
            fields.append(field)
    return prefix + '(' + ',\n'.join(fields) + ')' + suffix, foreign


def compiled_target_parts():
    sql, catalog = compile_schema()
    base, foreign, guards = [], [], []
    baseline = ROOT / 'sql/mysql/compact/baseline'
    for path in sorted(baseline.glob('*.sql')):
        body = path.read_text(encoding='utf8')
        if path.name == '40-relations.sql':
            foreign += list(split_top_level(without_comments(body), ';'))
        elif re.match(r'3[5-9]-', path.name):
            guards.append('DELIMITER $$\n' + body.rstrip() + '\nDELIMITER ;\n')
        else:
            for statement in split_top_level(without_comments(body), ';'):
                if re.match(r'CREATE\s+TABLE\b', statement, re.I):
                    clean, embedded = remove_inline_foreign_keys(statement, 'compact_target_placeholder')
                    base.append(clean); foreign += embedded
                else:
                    require(re.fullmatch(r'SET\s+NAMES\s+utf8mb4(?:\s+COLLATE\s+utf8mb4_0900_ai_ci)?', statement, re.I),
                            'Unregistered baseline statement')
    expected_guards = {(name, table, 'BEFORE', event) for table, resources in GUARD_RESOURCES.values()
                       for name, event in resources.items()}
    actual_guards = {(item['name'], item['table'], item['timing'], item['event']) for item in catalog['triggers']}
    require(len(base) == catalog['tableCount'] == 29 and actual_guards == expected_guards,
            'Compiled compact target must contain the reviewed 29 tables and complete builder protection guards')
    return sql, catalog, base, foreign, guards


def new_schema(mysql, schema):
    count = mysql.single("SELECT JSON_OBJECT('n',COUNT(*)) FROM information_schema.schemata WHERE schema_name=" + literal(schema) + ';')['n']
    require(count == 0, 'A migration or recovery schema already exists; never retry over an unknown result')
    mysql.script('CREATE DATABASE ' + quoted(schema) + ' CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;', label='create-schema')


def install_relations(mysql, schema, foreign):
    for number, statement in enumerate(foreign):
        rendered = statement.replace('`compact_target_placeholder`', quoted(schema))
        mysql.script(rendered + ';', database=schema, label='foreign-' + str(number))
    require(mysql.admitted_server()['foreignKeyChecks'] == 1, 'Foreign-key enforcement was disabled')


def trigger_catalog(mysql, schema):
    return mysql.json_rows("SELECT JSON_OBJECT('name',TRIGGER_NAME,'table',EVENT_OBJECT_TABLE,'event',EVENT_MANIPULATION,"
        "'timing',ACTION_TIMING,'order',ACTION_ORDER,'body',ACTION_STATEMENT,'definer',DEFINER,'sqlMode',SQL_MODE,"
        "'characterSetClient',CHARACTER_SET_CLIENT,'collationConnection',COLLATION_CONNECTION) "
        'FROM information_schema.triggers WHERE trigger_schema=' + literal(schema)
        + ' ORDER BY EVENT_OBJECT_TABLE,ACTION_TIMING,EVENT_MANIPULATION,ACTION_ORDER;')


def admit_source_trigger_definers(mysql, schema):
    """Check recovery authority before copying; never invent or elevate a definer."""
    triggers = trigger_catalog(mysql, schema)
    current = mysql.single("SELECT JSON_OBJECT('user',CURRENT_USER());")['user']
    others = {item['definer'] for item in triggers if item['definer'] != current}
    if not others:
        return
    # These visible direct global grants are conservative admission evidence.
    # Role-only authority is intentionally not guessed, nor granted by this CLI.
    grants = mysql.script('SHOW GRANTS;', label='recovery-definer-grants').decode('utf8').splitlines()
    names = set()
    for grant in grants:
        match = re.fullmatch(r'GRANT (.+) ON \*\.\* TO .+', grant)
        if match:
            names.update(part.strip() for part in match.group(1).split(','))
    if 'ALL PRIVILEGES' in names:
        names.add('SUPER')
    require('SET_ANY_DEFINER' in names or 'SUPER' in names,
            'Source trigger recovery needs an explicitly reviewed SET_ANY_DEFINER grant; no privileges are auto-granted')
    # Source definers can be SYSTEM_USER accounts. We cannot safely infer their
    # authority from a schema-limited migration identity, so require a direct
    # reviewed SYSTEM_USER grant whenever another definer must be preserved.
    require('SYSTEM_USER' in names,
            'Preserving another source trigger definer requires reviewed SYSTEM_USER authority or an operator-owned recovery path')


def install_triggers(mysql, schema, original_schema, triggers):
    for index, trigger in enumerate(triggers):
        require(trigger['timing'] in ('BEFORE', 'AFTER') and trigger['event'] in ('INSERT', 'UPDATE', 'DELETE'),
                'Unexpected backup trigger event')
        user, separator, host = trigger['definer'].rpartition('@')
        require(separator and user and host, 'A trigger definer cannot be represented unchanged')
        require(re.fullmatch(r'[a-z0-9_]+', trigger['characterSetClient'])
                and re.fullmatch(r'[a-z0-9_]+', trigger['collationConnection']), 'Unsupported trigger character set')
        body = normalize_self(trigger['body'], original_schema, schema)
        ddl = ('SET SESSION sql_mode=' + literal(trigger['sqlMode']) + '; SET NAMES '
               + trigger['characterSetClient'] + ' COLLATE ' + trigger['collationConnection'] + ';\nDELIMITER $$\n'
               + 'CREATE DEFINER=' + literal(user) + '@' + literal(host) + ' TRIGGER ' + quoted(trigger['name'])
               + ' ' + trigger['timing'] + ' ' + trigger['event'] + ' ON ' + quoted(trigger['table'])
               + ' FOR EACH ROW ' + body + '$$\nDELIMITER ;\n')
        mysql.script(ddl, database=schema, label='restore-trigger-' + str(index))


def backup_schema(mysql, snapshot, path, *, purpose, migration_context):
    path.mkdir(mode=0o700)
    data = mysql.data_dump(snapshot['schema'], snapshot['tables'], path / 'data.sql')
    meta, meta_sha = metadata_snapshot(mysql, snapshot['schema'])
    manifest = {'schemaVersion': 1, 'kind': 'doorhandle-mysql-private-backup', 'purpose': purpose,
                'createdAtUtc': utc_now(), 'schema': snapshot['schema'], 'serverUuid': mysql.config['serverUuid'],
                'snapshotSha256': snapshot['snapshotSha256'], 'metadataSha256': meta_sha,
                'tables': snapshot['tables'], 'createTables': snapshot['createTables'],
                'triggers': trigger_catalog(mysql, snapshot['schema']),
                'data': {'file': 'data.sql', 'sha256': data['sha256'], 'bytes': data['bytes']},
                'migrationContext': migration_context}
    write_json(path / 'manifest.json', manifest)
    return path / 'manifest.json'


def restore_data(mysql, schema, manifest, data_file):
    """Restore only verified INSERTs; never execute mysqldump FK/unique-check disabling boilerplate."""
    clean = mysql.output / 'private' / ('restore-data-' + schema + '.sql')
    counts = {name: 0 for name in manifest['tables']}
    with data_file.open('r', encoding='utf8', newline='') as source, clean.open('x', encoding='utf8', newline='\n') as target:
        os.chmod(clean, 0o600)
        for line in source:
            require(len(line.encode('utf8')) <= 64 * 1024 * 1024, 'A backup row exceeds its explicit restore byte budget')
            value = line.strip()
            if not value or value.startswith('--'):
                continue
            directive = re.fullmatch(r'/\*!\d{5,6}\s*(.*?)\*/\s*;?', value, re.S)
            if directive:
                value = directive.group(1).strip()
            if re.match(r'SET\s+', value, re.I):
                require(not re.search(r'\b(?:GLOBAL|GTID_PURGED|SQL_LOG_BIN|PASSWORD)\b', value, re.I),
                        'Privileged or global backup directives are forbidden')
                # Restore uses our own UTC/strict session; every dump SET (including
                # FOREIGN_KEY_CHECKS=0) is discarded and is never sent to MySQL.
                continue
            match = re.match(r'INSERT\s+INTO\s+`([a-z][a-z0-9_]*)`\s*\(', value, re.I)
            require(match is not None and match.group(1) in counts and value.endswith(';'),
                    'Only complete INSERTs into the backed-up table catalog can be restored')
            require(len(list(split_top_level(without_comments(value), ';'))) == 1,
                    'A backup row contains more than its one INSERT statement')
            counts[match.group(1)] += 1
            target.write(value + '\n')
    require(all(counts[name] == detail['rows'] for name, detail in manifest['tables'].items()),
            'The complete-insert backup row counts differ from its frozen source')
    # Feed the large, private SQL file without holding customer data in memory.
    command, prefix = mysql.command(schema)
    input_file = mysql.output / 'private' / ('restore-input-' + schema)
    with input_file.open('xb') as target, clean.open('rb') as source:
        os.chmod(input_file, 0o600)
        target.write(prefix)
        target.write(b"SET SESSION time_zone='+00:00'; SET SESSION sql_mode='STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION,NO_AUTO_VALUE_ON_ZERO';\n")
        for block in iter(lambda: source.read(1024 * 1024), b''):
            target.write(block)
    out = mysql.output / 'private' / ('restore-' + schema + '.stdout')
    err = mysql.output / 'private' / ('restore-' + schema + '.stderr')
    with input_file.open('rb') as source, out.open('xb') as stdout, err.open('xb') as stderr:
        os.chmod(out, 0o600); os.chmod(err, 0o600)
        result = subprocess.run(command, stdin=source, stdout=stdout, stderr=stderr, timeout=3600, env=Mysql.environment())
    require(result.returncode == 0, 'Data restore failed; private original and recovery schema are retained')


def restore_backup(mysql, backup_file, restore_schema, output, evidence_file):
    backup_file, manifest, backup_sha = private_json(backup_file)
    evidence_file, evidence, evidence_sha = private_json(evidence_file)
    require(manifest.get('kind') == 'doorhandle-mysql-private-backup' and manifest.get('schemaVersion') == 1
            and manifest.get('serverUuid') == mysql.config['serverUuid'], 'Backup identity differs')
    require(evidence.get('kind') == 'doorhandle-compact-migration-evidence' and evidence.get('status') == 'COPY_VERIFIED',
            'Recovery must bind a completed, verified copy evidence file')
    require(manifest['migrationContext'] == evidence['migrationContext'], 'Backup belongs to another migration attempt')
    purpose = manifest['purpose']
    require(purpose in ('source', 'target') and restore_schema == mysql.config['recoverySchemas'][purpose],
            'Restore schema is not admitted for this exact recovery purpose')
    expected = evidence['sourceSnapshotSha256' if purpose == 'source' else 'targetSnapshotSha256']
    require(manifest['snapshotSha256'] == expected, 'Backup snapshot differs from the migration evidence')
    data_file = backup_file.parent / manifest['data']['file']
    require(data_file.name == 'data.sql' and data_file.resolve(strict=True) == data_file
            and data_file.is_file() and data_file.stat().st_size == manifest['data']['bytes']
            and sha_file(data_file) == manifest['data']['sha256'], 'Private backup data checksum or path differs')
    new_schema(mysql, restore_schema)
    foreign = []
    for table in sorted(manifest['tables']):
        ddl = manifest['createTables'][table]
        require(hashlib.sha256(normalize_self(ddl, manifest['schema']).encode('utf8')).hexdigest()
                == manifest['tables'][table]['ddlSha256'], 'Backed-up DDL checksum differs')
        ddl = normalize_self(ddl, manifest['schema'], restore_schema)
        create, relations = remove_inline_foreign_keys(ddl, restore_schema)
        mysql.script(create + ';', database=restore_schema, label='restore-create')
        foreign += relations
    restore_data(mysql, restore_schema, manifest, data_file)
    for table, detail in manifest['tables'].items():
        if detail['autoIncrement'] is not None:
            value = detail['autoIncrement']
            require(re.fullmatch(r'[0-9]{1,20}', value) is not None, 'Invalid backed-up AUTO_INCREMENT')
            mysql.script('ALTER TABLE ' + quoted(table) + ' AUTO_INCREMENT=' + value + ';',
                         database=restore_schema, label='restore-sequence')
    install_relations(mysql, restore_schema, foreign)
    install_triggers(mysql, restore_schema, manifest['schema'], manifest['triggers'])
    observed = schema_snapshot(mysql, restore_schema, manifest['tables'])
    _, metadata_sha = metadata_snapshot(mysql, restore_schema)
    require(observed['snapshotSha256'] == expected and metadata_sha == manifest['metadataSha256'],
            'The full restored rows, columns, DDL, indexes, triggers or high-water marks differ')
    result = {'schemaVersion': 1, 'kind': 'doorhandle-compact-recovery', 'status': 'VERIFIED',
              'purpose': purpose, 'attempt': evidence['attempt'], 'ecs': evidence['ecs'],
              'serverUuid': evidence['serverUuid'], 'originalSchema': manifest['schema'], 'restoreSchema': restore_schema,
              'sourceSchema': evidence['sourceSchema'], 'targetSchema': evidence['targetSchema'],
              'migrationEvidenceSha256': evidence_sha, 'backupManifestSha256': backup_sha,
              'contractSha256': evidence['contractSha256'], 'sqlSha256': evidence['sqlSha256'],
              'copyPlanSha256': evidence['copyPlanSha256'], 'targetMetadataSha256': evidence['targetMetadataSha256'],
              'expectedSnapshotSha256': expected, 'restoredSnapshotSha256': observed['snapshotSha256'],
              'restoredMetadataSha256': metadata_sha, 'restoredTableCount': len(observed['tables']),
              'restoredRowCount': sum(table['rows'] for table in observed['tables'].values()), 'finishedAtUtc': utc_now()}
    output.mkdir(mode=0o700)
    write_json(output / 'recovery-receipt.json', result)
    return result


def receipt_member(parent, descriptor):
    require(isinstance(descriptor, dict) and set(descriptor) == {'file', 'sha256'}
            and isinstance(descriptor['file'], str) and SHA.fullmatch(descriptor['sha256']), 'Invalid proof member descriptor')
    path = parent / descriptor['file']
    require(not Path(descriptor['file']).is_absolute() and '..' not in Path(descriptor['file']).parts
            and path.resolve(strict=True) == path and path.is_relative_to(parent), 'Proof member escaped its receipt bundle')
    require(sha_file(path) == descriptor['sha256'], 'Proof member checksum differs')
    return json.loads(path.read_text(encoding='utf8'), object_pairs_hook=no_duplicate_keys)


def validate_migration_receipt(path, expected_context=None):
    """Pure immutable proof-chain validation; NOT a current data/cutover validation."""
    path = Path(path).absolute()
    require(path.resolve(strict=True) == path and path.is_file(), 'Expected a canonical migration receipt')
    value = json.loads(path.read_text(encoding='utf8'), object_pairs_hook=no_duplicate_keys)
    require(value.get('schemaVersion') == 1 and value.get('kind') == 'doorhandle-compact-migration'
            and value.get('status') == 'VERIFIED' and value.get('targetTableCount') == 29
            and value.get('sourceTableCount') == 131 and value.get('foreignKeysValidated') is True,
            'Migration receipt is incomplete or does not prove the complete 131-to-29 migration')
    require(isinstance(value.get('attempt'), str) and re.fullmatch(r'[a-f0-9]{32}', value['attempt'])
            and isinstance(value.get('serverUuid'), str) and UUID.fullmatch(value['serverUuid'])
            and value.get('scope') in ('ecs-disposable-migration', 'production-migration'),
            'Migration attempt, server identity or scope is malformed')
    for key in ('configSha256', 'contractSha256', 'sqlSha256', 'copyPlanSha256', 'reviewedSourceObservationSha256',
                'sourceSnapshotSha256', 'sourceMetadataSha256', 'targetSnapshotSha256', 'targetMetadataSha256'):
        require(isinstance(value.get(key), str) and SHA.fullmatch(value[key]), 'A complete migration digest is missing: ' + key)
    require((value['scope'] == 'production-migration' and isinstance(value.get('freezeEvidenceSha256'), str)
             and SHA.fullmatch(value['freezeEvidenceSha256'])) or
            (value['scope'] == 'ecs-disposable-migration' and value.get('freezeEvidenceSha256') is None),
            'Production and disposable writer-freeze evidence cannot be interchanged')
    if expected_context:
        require(all(value.get(key) == actual for key, actual in expected_context.items()), 'Migration receipt context differs')
    if 'sourceClockPolicy' in value:
        clocks.validate_evidence(value['sourceClockPolicy'])
    evidence = receipt_member(path.parent, value['evidence'])
    require(evidence.get('status') == 'COPY_VERIFIED' and evidence.get('kind') == 'doorhandle-compact-migration-evidence',
            'Copy evidence is not verified')
    binding = ('attempt', 'ecs', 'scope', 'serverUuid', 'sourceSchema', 'targetSchema', 'contractSha256', 'sqlSha256',
               'copyPlanSha256', 'sourceSnapshotSha256', 'sourceMetadataSha256', 'targetSnapshotSha256', 'targetMetadataSha256',
               'freezeEvidenceSha256', 'executedSteps', 'sourceSnapshot', 'targetSnapshot',
               'sourceTableCount', 'targetTableCount', 'foreignKeysValidated', 'sourceClockPolicy')
    require(all(evidence.get(key) == value.get(key) for key in binding), 'Copy evidence and migration receipt bindings differ')
    for purpose in ('source', 'target'):
        snapshot = value.get(purpose + 'Snapshot')
        require(isinstance(snapshot, dict) and snapshot.get('schemaVersion') == 1
                and snapshot.get('schema') == value[purpose + 'Schema'] and isinstance(snapshot.get('tables'), dict)
                and len(snapshot['tables']) == (131 if purpose == 'source' else 29)
                and sha_json({'schemaVersion': 1, 'tables': snapshot['tables']}) == value[purpose + 'SnapshotSha256']
                and snapshot.get('snapshotSha256') == value[purpose + 'SnapshotSha256'],
                'The migration full table/column/row snapshot is incomplete or changed')
        proof = receipt_member(path.parent, value['recovery'][purpose])
        require(proof.get('kind') == 'doorhandle-compact-recovery' and proof.get('schemaVersion') == 1
                and proof.get('status') == 'VERIFIED' and proof.get('purpose') == purpose
                and proof.get('migrationEvidenceSha256') == value['evidence']['sha256']
                and all(proof.get(key) == value.get(key) for key in ('attempt', 'ecs', 'serverUuid', 'sourceSchema', 'targetSchema',
                    'contractSha256', 'sqlSha256', 'copyPlanSha256', 'targetMetadataSha256')),
                'Recovery proof is not bound to this migration')
        require(proof.get('expectedSnapshotSha256') == value['sourceSnapshotSha256' if purpose == 'source' else 'targetSnapshotSha256']
                and proof.get('restoredSnapshotSha256') == proof.get('expectedSnapshotSha256')
                and proof.get('restoredMetadataSha256') == value['sourceMetadataSha256' if purpose == 'source' else 'targetMetadataSha256']
                and proof.get('restoredTableCount') == (131 if purpose == 'source' else 29),
                'Recovery did not reproduce the complete source/target snapshot')
    return value
