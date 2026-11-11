"""ECS-only serial A/B restore of the closed, separately approved v2 three-schema packet.

Reuse existing owned-container creation, resource observation, stop and derived
cleanup. Fixtures stay archival and no original server connection is opened.
This entry is intentionally not enabled in Jenkins until real packet pins exist.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


packet = load('fixed_project_mysql_packet', ROOT / 'script/jenkins/project-mysql-custody.py')
existing = load('existing_owned_mysql_recovery', ROOT / 'script/jenkins/restore-local-mysql.py')
need, quote = existing.need, existing.quote


def constraint_findings(mysql, schema, metadata):
    """Check three-schema FKs after all three have restored; never filter/repair."""
    groups, result = {}, []
    for row in metadata['foreignKeys']:
        parent_schema = schema if row['parentSchema'] == '$SELF' else row['parentSchema']
        if parent_schema not in packet.SCHEMAS:
            result.append({'kind': 'EXTERNAL_FOREIGN_KEY', 'table': row['table'], 'constraint': row['name'],
                'violations': 0, 'unverified': True, 'reason': 'PARENT_SCHEMA_OUTSIDE_THREE_SCHEMA_EXPORT'})
        else: groups.setdefault((row['table'], row['name'], parent_schema), []).append(row)
    for (table, name, parent_schema), rows in sorted(groups.items()):
        rows.sort(key=lambda row: row['ordinal']); parent = rows[0]['parent']
        condition = ' AND '.join('c.' + quote(row['column']) + ' IS NOT NULL' for row in rows)
        join = ' AND '.join('p.' + quote(row['parentColumn']) + '=c.' + quote(row['column']) for row in rows)
        count = mysql.single("SELECT JSON_OBJECT('n',COUNT(*)) FROM " + quote(schema) + '.' + quote(table)
            + ' c WHERE ' + condition + ' AND NOT EXISTS (SELECT 1 FROM ' + quote(parent_schema) + '.' + quote(parent)
            + ' p WHERE ' + join + ');')['n']
        need(type(count) is int and count >= 0, 'Recovered FK count differs')
        if count: result.append({'kind': 'FOREIGN_KEY', 'table': table, 'constraint': name, 'violations': count})
    for row in metadata['checks']:
        if row['enforced'] != 'YES': continue
        clause = row['clause']; need(type(clause) is str and 0 < len(clause) <= 65536, 'Recovered CHECK expression exceeds its bound')
        count = mysql.single("SELECT JSON_OBJECT('n',COUNT(*)) FROM " + quote(schema) + '.' + quote(row['table'])
            + ' WHERE (' + clause + ') IS FALSE;')['n']
        need(type(count) is int and count >= 0, 'Recovered CHECK count differs')
        if count: result.append({'kind': 'CHECK', 'table': row['table'], 'constraint': row['name'], 'violations': count})
    return result


def compare_recoveries(first, second):
    need(set(first['schemas']) == set(second['schemas']) == set(packet.SCHEMAS), 'All three complete recoveries are required')
    need(first['serverUuid'] != second['serverUuid'] and first['containerId'] != second['containerId']
        and first['volume'] != second['volume'], 'Independent server/volume identities are required')
    for schema in packet.SCHEMAS:
        left, right = first['schemas'][schema], second['schemas'][schema]
        need(left == right and left['observedCountsMatch'] is True,
             'Independent complete schema/rows/keys/metadata/routines/events evidence differs')


def compare_source_ddl(baseline, recovered):
    need(set(baseline['schemas']) == set(recovered['schemas']) == set(packet.SCHEMAS), 'Complete source DDL baseline required')
    for schema, detail in recovered['schemas'].items():
        before = baseline['schemas'][schema]
        need(before['observedCountsMatch'] is True and before['metadata'] == detail['metadata']
            and before['extraObjects'] == detail['extraObjects'],
            'Restored constraints/routines/events differ from original source DDL')
        need(set(before['snapshot']['tables']) == set(detail['snapshot']['tables']), 'Original complete table catalogue differs')
        for name, table in detail['snapshot']['tables'].items():
            need(all(table[key] == before['snapshot']['tables'][name][key]
                for key in ('columns', 'indexes', 'collation', 'ddlSha256', 'autoIncrement')),
                'Restored DDL/types/indexes/high-water marks differ from original source DDL')


class Recovery(existing.Recovery):
    cancel_name = 'project-mysql-recovery-cancel.json'
    lock_name = 'project-mysql-recovery-create.lock'
    not_created_name = 'project-mysql-recovery-not-created.json'

    def __init__(self, args):
        self.args, self.bytes = args, packet
        self.work, self.context = packet.admit(args)
        self.utility = packet.common(); self.directory = self.work / 'project-mysql-recovery'
        self.owner_file = self.work / 'project-mysql-recovery-owner.json'
        self.docker = self.utility.safe(shutil.which('docker'))
        self.original = None; self.state = None; self.cancel = threading.Event(); self.pressure = None
        if getattr(args, 'action', 'run') in ('cleanup', 'observe') and not self.owner_file.exists():
            # Transfer/byte recovery may fail before SQL is ever created. The
            # same fixed build and ECS identity can still prove no SQL owner or
            # recovery directory exists; partial original bytes stay retained.
            self.utility.safe(self.owner_file, exists=False); self.utility.safe(self.directory, exists=False)
            if args.action == 'cleanup':
                need(not self.directory.exists(), 'An unowned partial recovery directory requires investigation')
            self.manifest, self.specifications = None, {}
        else:
            self.manifest = packet.verified_inputs(args, self.work)
            self.specifications = self.manifest['schemas']
        self.runtime = existing.load_runtime()

    def cleanup_source_fields(self):
        return {'projectSqlSha256': {name: row['rawSqlSha256'] for name, row in self.specifications.items()},
            'packetManifestSha256': self.args.manifest_sha256, 'batchReceiptSha256': self.args.batch_receipt_sha256}

    def create_registered(self, ordinal):
        need(all(not self.inspect(node['containerId'])['State']['Running'] for node in self.state['servers']),
             'At most one owned recovery server may run')
        return super().create_registered(ordinal)

    def sql_client(self, cid, output):
        runtime, parent = self.runtime, self
        class OwnedMysql(runtime.Mysql):
            def __init__(self):
                self.program, self.container, self.output, self.sequence = parent.docker, cid, output, 0
                self.config = {'scope': 'project-sql-custody-recovery', 'serverUuid': None}
            def command(self, database=None, *, dump=False, table_names=()):
                parent.guard(); parent.inspect(cid)
                need(not dump and not table_names and (database is None or database in packet.SCHEMAS),
                     'Only original SQL and the three owned schemas are admitted')
                args = ['--no-defaults', '--no-login-paths', '--protocol=SOCKET', '-uroot', '--default-character-set=utf8mb4',
                    '--batch', '--raw', '--skip-column-names', '--unbuffered', '--binary-mode', '--local-infile=0']
                if database: args += ['--database=' + database]
                return [str(parent.docker), 'exec', '-i', cid, 'sh', '-ec',
                    'MYSQL_PWD="${MYSQL_ROOT_PASSWORD:?}" exec mysql "$@"', '--', *args], b''
        return OwnedMysql()

    def recreate_owned_schemas(self, client):
        # This client is admitted against the fresh owned container and its
        # sole derived volume. No command or connection can target the source.
        self.guard(); self.inspect(client.container)
        sql = 'SET FOREIGN_KEY_CHECKS=0;\n'
        sql += '\n'.join('DROP DATABASE IF EXISTS ' + quote(name) + ';' for name in packet.SCHEMAS)
        sql += '\n' + '\n'.join('CREATE DATABASE ' + quote(name)
            + ' CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;' for name in packet.SCHEMAS)
        client.script(sql + '\nSET FOREIGN_KEY_CHECKS=1;', label='recreate-owned-three-schemas')

    def import_original(self, client, schema, name):
        path = self.work / packet.RESTORE / 'schemas' / schema / name
        public = packet.read(path.parent / 'public-manifest.json'); binding = public['files'][name]
        need(path.stat().st_size == binding['bytes'] and packet.digest(path) == binding['sha256'], 'Original SQL changed before import')
        command, prefix = client.command(schema); need(not prefix, 'Unexpected credential prefix in original SQL')
        label = schema + '-' + name
        output, errors = client.output / 'private' / (label + '.stdout'), client.output / 'private' / (label + '.stderr')
        with path.open('rb') as incoming, output.open('xb') as stdout, errors.open('xb') as stderr:
            os.chmod(output, 0o600); os.chmod(errors, 0o600)
            process = subprocess.Popen(command, stdin=incoming, stdout=stdout, stderr=stderr,
                start_new_session=True, env=client.environment())
            try:
                deadline = time.monotonic() + 600
                while process.poll() is None:
                    self.guard(); need(time.monotonic() < deadline, 'Original SQL recovery exceeded its bound'); time.sleep(0.1)
                need(process.returncode == 0, 'Original SQL import failed; retain private diagnostics and originals')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=10)
        need(packet.digest(path) == binding['sha256'], 'Original SQL changed during import')

    def capture_schema(self, client, schema, *, baseline=False):
        specification = self.specifications[schema]
        snapshot = self.runtime.schema_snapshot(client, schema, specification['tables'],
            keyed_rows_directory=None if baseline else client.output / 'keyed-rows')
        metadata, metadata_sha = self.runtime.metadata_snapshot(client, schema)
        definitions = {
            'routines': ('ROUTINES', 'ROUTINE_SCHEMA', "'name',ROUTINE_NAME,'type',ROUTINE_TYPE,'returns',DTD_IDENTIFIER,'body',ROUTINE_DEFINITION,'mode',SQL_MODE,'definer',DEFINER,'deterministic',IS_DETERMINISTIC,'access',SQL_DATA_ACCESS,'security',SECURITY_TYPE,'comment',ROUTINE_COMMENT,'clientCharset',CHARACTER_SET_CLIENT,'connectionCollation',COLLATION_CONNECTION,'databaseCollation',DATABASE_COLLATION"),
            'parameters': ('PARAMETERS', 'SPECIFIC_SCHEMA', "'routine',SPECIFIC_NAME,'ordinal',ORDINAL_POSITION,'name',PARAMETER_NAME,'mode',PARAMETER_MODE,'type',DTD_IDENTIFIER,'charset',CHARACTER_SET_NAME,'collation',COLLATION_NAME"),
            'events': ('EVENTS', 'EVENT_SCHEMA', "'name',EVENT_NAME,'body',EVENT_DEFINITION,'type',EVENT_TYPE,'executeAt',EXECUTE_AT,'intervalValue',INTERVAL_VALUE,'intervalField',INTERVAL_FIELD,'starts',STARTS,'ends',ENDS,'zone',TIME_ZONE,'completion',ON_COMPLETION,'comment',EVENT_COMMENT,'status',STATUS,'mode',SQL_MODE,'definer',DEFINER,'clientCharset',CHARACTER_SET_CLIENT,'connectionCollation',COLLATION_CONNECTION,'databaseCollation',DATABASE_COLLATION")}
        extra = {name: client.json_rows('SELECT JSON_OBJECT(' + columns + ') FROM information_schema.' + table
            + ' WHERE ' + schema_column + "='" + schema + "' ORDER BY 1;")
            for name, (table, schema_column, columns) in definitions.items()}
        expected = {name: 0 for name in specification['tables']} if baseline else specification['counts']
        result = {'snapshot': snapshot, 'metadata': metadata, 'metadataSha256': metadata_sha, 'extraObjects': extra,
            'findings': constraint_findings(client, schema, metadata),
            'observedCountsMatch': {name: row['rows'] for name, row in snapshot['tables'].items()} == expected,
            'liveSourceRowHashesVerified': False, 'eventsExecuted': False, 'purpose': specification['purpose']}
        if not baseline:
            index = self.utility.owner_path(client.output / 'keyed-rows/index.json')
            result['keyedRowsIndex'] = {'file': 'full/' + schema + '/keyed-rows/index.json',
                'bytes': index.stat().st_size, 'sha256': packet.digest(index)}
        return result

    def capture_all(self, node, client, *, baseline=False):
        actual = client.json_rows("SELECT JSON_OBJECT('name',SCHEMA_NAME) FROM information_schema.SCHEMATA ORDER BY SCHEMA_NAME;")
        need({row['name'] for row in actual} == set(packet.SCHEMAS) | {'mysql', 'information_schema', 'performance_schema', 'sys'},
             'The original dump created schemas outside the closed recovery set')
        values = {}
        for schema in packet.SCHEMAS:
            output = client.output / ('baseline' if baseline else 'full') / schema
            output.mkdir(mode=0o700, parents=True); (output / 'private').mkdir(mode=0o700)
            values[schema] = self.capture_schema(self.sql_client(node['containerId'], output), schema, baseline=baseline)
        return {'containerId': node['containerId'], 'volume': node['volume'], 'serverUuid': node['serverUuid'], 'schemas': values}

    def evidence_bindings(self):
        manifest = packet.verified_inputs(self.args, self.work)
        original = self.work / packet.RESTORE
        paths = {name: self.utility.owner_path(original / name) for name in packet.MEMBERS}
        need(packet.verify_originals(paths, self.args.batch_receipt_sha256) == manifest['schemas'], 'Original packet changed before derived cleanup')
        receipt_file = self.utility.owner_path(original / 'restore-receipt.json'); byte_receipt = packet.read(receipt_file)
        need(all(byte_receipt.get(key) == value for key, value in self.context.items())
            and byte_receipt.get('status') == 'BYTES_RESTORED_VERIFIED'
            and byte_receipt.get('manifestSha256') == self.args.manifest_sha256
            and byte_receipt.get('archiveSha256') == self.args.archive_sha256,
            'Original same-build byte proof changed')
        files = [*paths.values(), receipt_file, self.work / packet.SNAPSHOT / 'custody.json',
                 self.work / packet.SNAPSHOT / 'originals.tar.gz', self.directory / 'resource-probes.jsonl']
        baseline_path = self.utility.owner_path(self.directory / 'a/source-ddl-baseline-private.json')
        baseline = packet.read(baseline_path); files.append(baseline_path)
        values = []
        for ordinal in ('a', 'b'):
            path = self.utility.owner_path(self.directory / ordinal / 'full-recovery-private.json'); value = packet.read(path)
            node = next(item for item in self.state['servers'] if item['ordinal'] == ordinal)
            need(all(value[key] == node[key] for key in ('containerId', 'volume', 'serverUuid')), 'Logical proof belongs to another owned server')
            for schema, detail in value['schemas'].items():
                index_file = self.utility.owner_path(path.parent / 'full' / schema / 'keyed-rows/index.json')
                reference = detail['keyedRowsIndex']; index = packet.read(index_file)
                need(reference['file'] == 'full/' + schema + '/keyed-rows/index.json'
                    and index_file.stat().st_size == reference['bytes'] and packet.digest(index_file) == reference['sha256']
                    and index.get('kind') == 'doorhandle-mysql-keyed-row-index'
                    and index.get('schema') == schema and index.get('snapshotSha256') == detail['snapshot']['snapshotSha256']
                    and set(index['tables']) == set(detail['snapshot']['tables']), 'Complete keyed-row index changed')
                names = {'index.json'}; files.append(index_file)
                for name, descriptor in index['tables'].items():
                    if descriptor['status'] == 'NO_PRIMARY_KEY':
                        need(descriptor['file'] is None and descriptor['entries'] == descriptor['bytes'] == 0,
                             'Unkeyed table cannot claim a keyed capture'); continue
                    need(descriptor['status'] == 'KEYED' and descriptor['file'] == name + '.jsonl', 'Unexpected keyed-row member')
                    member = self.utility.owner_path(index_file.parent / descriptor['file'])
                    actual = self.runtime.keyed_row_inventory(member, descriptor['rows'], descriptor['rowsSha256'])
                    need(all(descriptor[key] == item for key, item in actual.items()), 'Complete original row-key chain changed')
                    names.add(member.name); files.append(member)
                need({entry.name for entry in index_file.parent.iterdir()} == names, 'Keyed-row membership differs')
            compare_source_ddl(baseline, value); values.append(value); files.append(path)
        compare_recoveries(*values)
        return {path.relative_to(self.work).as_posix(): packet.digest(self.utility.owner_path(path)) for path in files}

    def run(self):
        need(not self.owner_file.exists() and not self.directory.exists(), 'Fresh three-schema recovery required')
        original = self.work / packet.RESTORE
        need(packet.verify_originals({name: self.utility.owner_path(original / name) for name in packet.MEMBERS},
            self.args.batch_receipt_sha256) == self.specifications, 'Actual byte recovery is required before SQL')
        byte_file = self.utility.owner_path(original / 'restore-receipt.json'); byte_receipt = packet.read(byte_file)
        need(byte_receipt.get('status') == 'BYTES_RESTORED_VERIFIED'
            and all(byte_receipt.get(key) == value for key, value in self.context.items())
            and byte_receipt.get('manifestSha256') == self.args.manifest_sha256
            and byte_receipt.get('archiveSha256') == self.args.archive_sha256, 'Same-build byte proof required')
        settings = packet.read(self.utility.owner_path(self.args.fixture_settings)); cid = settings.get('sourceMysqlContainerId', '')
        need(existing.CID.fullmatch(cid), 'Existing immutable image source required')
        image = self.docker_call('inspect', '--format', '{{.Image}}', cid).decode().strip()
        need(existing.IMAGE.fullmatch(image) and self.docker_call('image', 'inspect', '--format', '{{.Id}}', image).decode().strip() == image,
             'Existing immutable MySQL image identity differs')
        raw = sum(row['rawSqlBytes'] for row in self.specifications.values())
        self.utility.resource_guard(self.work, 1536 * packet.MIB + 6 * raw)
        with self.creation_lock():
            self.guard(); need(not self.owner_file.exists() and not self.directory.exists(), 'Another recovery owner appeared')
            self.utility.private_directory(self.directory); self.original = cid
            self.state = {**self.context, 'directory': str(self.directory), 'owner': secrets.token_hex(12),
                'originalContainerId': cid, 'mysqlImage': image, 'byteReceiptSha256': packet.digest(byte_file),
                'fixtureSettingsSha256': packet.digest(self.args.fixture_settings), 'servers': [], 'status': 'PREPARING'}
            self.persist()
        watcher = threading.Thread(target=self.watch, daemon=True); watcher.start(); recovered = []; baseline = None
        try:
            for ordinal in ('a', 'b'):
                node, client = self.start(ordinal)
                if ordinal == 'a':
                    self.recreate_owned_schemas(client)
                    for schema in packet.SCHEMAS: self.import_original(client, schema, 'schema-before.sql')
                    baseline = self.capture_all(node, client, baseline=True)
                    packet.write(client.output / 'source-ddl-baseline-private.json', baseline)
                self.recreate_owned_schemas(client)
                for schema in packet.SCHEMAS: self.import_original(client, schema, 'database.sql')
                value = self.capture_all(node, client)
                compare_source_ddl(baseline, value)
                packet.write(client.output / 'full-recovery-private.json', value)
                recovered.append(value); self.stop(node)
            self.guard(); compare_recoveries(*recovered)
            need(all(node.get('peakBytes', 0) > 0 for node in self.state['servers']), 'Actual cgroup peak evidence required')
        finally:
            self.cancel.set(); watcher.join(timeout=10); need(not watcher.is_alive(), 'Resource observer did not stop')
            for node in self.state['servers']: self.stop(node)
        self.guard()
        need(all(node['exitCode'] == 0 and node['oomKilled'] is False for node in self.state['servers']), 'Failed or OOM recovery cannot pass')
        bindings = self.evidence_bindings()
        public = {**self.context, 'status': 'PROJECT_SQL_DOUBLE_RESTORED_VERIFIED',
            'schemas': {name: {'tableCount': len(value['snapshot']['tables']),
                'restoredRows': sum(row['rows'] for row in value['snapshot']['tables'].values()),
                'snapshotSha256': value['snapshot']['snapshotSha256'], 'metadataSha256': value['metadataSha256'],
                'constraintDefectCount': sum(row['violations'] for row in value['findings']),
                'constraintsSatisfied': not value['findings'], 'purpose': value['purpose']}
                for name, value in recovered[0]['schemas'].items()},
            'logicalEvidenceCatalogueSha256': packet.sha(bindings), 'liveSourceRowHashesVerified': False,
            'allAcceptedDumpRowsPreserved': True, 'productionMerged': False, 'retirementAllowed': False,
            'eventsExecuted': False, 'paidModelCalls': 0, 'cleanup': 'STOPPED'}
        packet.write(self.directory / 'public-recovery.json', public)
        # Existing cleanup only removes derived resources after independently
        # re-reading this full pair and every original custody binding.
        self.state.update(status='SQL_DOUBLE_RESTORED_VERIFIED', cleanupEvidence=bindings,
            publicRecoverySha256=packet.digest(self.directory / 'public-recovery.json')); self.persist()
        return {**public, 'recoveryReceiptSha256': packet.digest(self.directory / 'public-recovery.json')}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('action', choices=('run', 'cleanup', 'observe'))
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id', 'batch-receipt-sha256',
                 'manifest-sha256', 'archive-sha256', 'fixture-settings'): parser.add_argument('--' + name, required=True)
    for name in ('manifest-bytes', 'archive-bytes'): parser.add_argument('--' + name, type=int, required=True)
    parser.add_argument('--run-requested', action='store_true')
    args = parser.parse_args(); controller = None
    for event in (signal.SIGINT, signal.SIGTERM):
        signal.signal(event, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    signal.signal(signal.SIGHUP, signal.SIG_IGN if args.action == 'run' else
                  lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        controller = Recovery(args)
        result = controller.run_supervised() if args.action == 'run' else controller.observe() if args.action == 'observe' else controller.cleanup()
        existing.emit(result); return 0
    except BaseException as error:
        if args.action == 'cleanup' and controller and controller.state:
            with contextlib.suppress(Exception): controller.cleanup()
        existing.emit({'kind': 'doorhandle-project-mysql-recovery', 'status': 'FAILED_OR_UNKNOWN',
            'errorType': type(error).__name__, 'productionMerged': False, 'retirementAllowed': False}); return 2


if __name__ == '__main__': raise SystemExit(main())
