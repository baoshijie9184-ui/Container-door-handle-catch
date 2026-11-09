"""Bounded keyed digests from the exact complete-row stream, without row values.

Only fake client processes are used here. Actual execution belongs to the ECS
Jenkins test matrix; editing or compiling this file is not a local test run.
"""
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import re
from types import SimpleNamespace

import pytest


PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    directory = PROJECT / 'script/schema'
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location('keyed_capture_primitives', directory / 'compact_migration_runtime.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    (tmp_path / 'work').mkdir(mode=0o700)
    return module


def chain(rows):
    result = hashlib.sha256(b'compact-row-hash-chain-v1\n')
    for row in rows:
        result.update(bytes.fromhex(row['rowSha256']))
    return result.hexdigest()


def record(key='1', value='a'):
    return {'keySha256': key * 64, 'rowSha256': value * 64}


def private_folder(runtime, name='keyed'):
    folder = runtime.ROOT / 'work' / name
    folder.mkdir(mode=0o700)
    return folder


def sidecar(runtime, rows, *, folder=None):
    folder = folder or private_folder(runtime)
    file = folder / 'item.jsonl'
    with runtime.keyed_row_output(file) as stream:
        for row in rows:
            stream.write(runtime.canonical(row) + b'\n')
    return file


def stream_client(runtime, monkeypatch, body, *, blocks=None, exit_code=0):
    output = private_folder(runtime, 'client')
    (output / 'private').mkdir(mode=0o700)

    class Input(io.BytesIO):
        def close(self):
            self.saved = self.getvalue()
            super().close()

    class Output(io.BytesIO):
        def fileno(self):
            return 734

    class Process:
        def __init__(self):
            self.stdin, self.stdout = Input(), Output()
            self.returncode = None
            self.terminated = False

        def wait(self, timeout=None):
            if self.returncode is None:
                self.returncode = exit_code
            return self.returncode

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def kill(self):
            self.terminated = True
            self.returncode = -9

    class Selector:
        def register(self, *_args):
            pass

        def select(self, _timeout):
            return [object()]

        def close(self):
            pass

    process = Process()
    chunks = iter(blocks if blocks is not None else [body])

    def read(fd, size):
        assert fd == 734 and size == 65536
        return next(chunks, b'')

    monkeypatch.setattr(runtime.subprocess, 'Popen', lambda *_args, **_kwargs: process)
    monkeypatch.setattr(runtime.selectors, 'DefaultSelector', Selector)
    monkeypatch.setattr(runtime.os, 'read', read)
    client = SimpleNamespace(output=output, command=lambda: (['fake-mysql'], b''), environment=lambda: {})
    return client, process


def invoke(runtime, client, *, file=None, primary=None, columns=None):
    return runtime.Mysql.row_hashes(client, 'doorhandledb', 'item', columns or ['id', 'payload'],
                                    ['id'] if primary is None else primary, keyed_rows_path=file)


def test_row_expression_preserves_null_empty_and_binary_bytes(runtime):
    expression = runtime.row_hash_expression(['id', 'payload'])
    assert expression.startswith('SHA2(CONCAT(IF(`id` IS NULL,')
    assert expression.count("'N;'") == 2
    assert expression.count('OCTET_LENGTH(CAST(') == 2
    assert expression.count('HEX(CAST(') == 2
    assert expression.count(' AS BINARY)') == 4
    assert "':',HEX" in expression and "';'))" in expression
    assert expression.endswith('),256)')


@pytest.mark.parametrize('columns', [[], ['id', 'id'], ['unsafe;'], ['id', 'PAYLOAD'], 'id'])
def test_row_expression_refuses_missing_duplicate_or_unquoted_columns(runtime, columns):
    with pytest.raises(ValueError):
        runtime.row_hash_expression(columns)


def test_old_row_stream_preserves_chain_and_does_not_select_or_write_keys(runtime, monkeypatch):
    rows = [record(), record('2', 'b')]
    body = b''.join((row['rowSha256'] + '\n').encode() for row in rows)
    client, process = stream_client(runtime, monkeypatch, body)
    count, checksum = invoke(runtime, client)
    assert (count, checksum) == (2, chain(rows))
    assert b'AS key_sha' not in process.stdin.saved
    assert list(client.output.glob('*.jsonl')) == []


def test_capture_uses_complete_ordered_compound_key_in_the_same_row_stream(runtime, monkeypatch):
    rows = [record(), record('2', 'b')]
    body = b''.join((row['keySha256'] + '\t' + row['rowSha256'] + '\n').encode() for row in rows)
    client, process = stream_client(runtime, monkeypatch, body, blocks=[body[:70], body[70:137], body[137:]])
    file = private_folder(runtime) / 'item.jsonl'
    actual = invoke(runtime, client, file=file, columns=['tenant', 'id', 'payload'], primary=['tenant', 'id'])
    assert actual == (2, chain(rows))
    sql = process.stdin.saved.decode()
    expected_keys = runtime.row_hash_expression(['tenant', 'id'])
    assert expected_keys + ' AS key_sha,' in sql
    assert sql.count(' SELECT ') == 1 and 'ORDER BY `tenant`,`id`;' in sql
    assert sql.startswith("SET SESSION time_zone='+00:00'; SELECT ")
    assert not any(word in sql for word in ('UPDATE ', 'INSERT ', 'DELETE ', 'CREATE ', 'ALTER '))
    assert file.read_bytes() == b''.join(runtime.canonical(row) + b'\n' for row in rows)
    inventory = runtime.keyed_row_inventory(file, 2, chain(rows))
    assert inventory == {'file': 'item.jsonl', 'fileSha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                         'bytes': file.stat().st_size, 'entries': 2}
    assert file.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('body', [
    b'a' * 64 + b'\n',
    b'1' * 64 + b'\t' + b'A' * 64 + b'\n',
    b'1' * 64 + b'\t' + b'a' * 64,
    b'1' * 64 + b'\t' + b'a' * 64 + b'\textra\n',
    b'1' * 130,
])
def test_capture_rejects_malformed_or_partial_records_and_stops_client(runtime, monkeypatch, body):
    client, process = stream_client(runtime, monkeypatch, body)
    file = private_folder(runtime) / 'item.jsonl'
    with pytest.raises(ValueError):
        invoke(runtime, client, file=file)
    assert process.terminated


def test_duplicate_full_key_digest_is_not_silently_overwritten(runtime, monkeypatch):
    rows = [record(), record('1', 'b')]
    body = b''.join((row['keySha256'] + '\t' + row['rowSha256'] + '\n').encode() for row in rows)
    client, process = stream_client(runtime, monkeypatch, body)
    with pytest.raises(ValueError, match='Duplicate complete primary-key'):
        invoke(runtime, client, file=private_folder(runtime) / 'item.jsonl')
    assert process.terminated


@pytest.mark.parametrize('limit', ['MAX_KEYED_ROWS_PER_TABLE', 'MAX_KEYED_ROW_BYTES_PER_TABLE'])
def test_capture_limits_reject_instead_of_truncating_success(runtime, monkeypatch, limit):
    rows = [record(), record('2', 'b')]
    body = b''.join((row['keySha256'] + '\t' + row['rowSha256'] + '\n').encode() for row in rows)
    client, process = stream_client(runtime, monkeypatch, body)
    monkeypatch.setattr(runtime, limit, 1)
    with pytest.raises(ValueError, match='per-table limit'):
        invoke(runtime, client, file=private_folder(runtime) / 'item.jsonl')
    assert process.terminated


@pytest.mark.parametrize('primary', [[], ['missing'], ['id', 'id']])
def test_capture_requires_a_complete_nonempty_primary_vector(runtime, monkeypatch, primary):
    client, process = stream_client(runtime, monkeypatch, b'')
    file = private_folder(runtime) / 'item.jsonl'
    with pytest.raises(ValueError, match='complete nonempty ordered primary key'):
        invoke(runtime, client, file=file, primary=primary)
    assert not file.exists() and not process.stdin.closed


def test_empty_keyed_table_is_a_verified_empty_stream(runtime, monkeypatch):
    client, _ = stream_client(runtime, monkeypatch, b'')
    file = private_folder(runtime) / 'item.jsonl'
    assert invoke(runtime, client, file=file) == (0, chain([]))
    assert runtime.keyed_row_inventory(file, 0, chain([]))['entries'] == 0


def test_inventory_independently_rejects_row_chain_or_count_drift(runtime):
    rows = [record(), record('2', 'b')]
    file = sidecar(runtime, rows)
    for count, checksum in [(1, chain(rows)), (2, '0' * 64)]:
        with pytest.raises(ValueError, match='complete actual table row chain'):
            runtime.keyed_row_inventory(file, count, checksum)


def test_inventory_rejects_duplicate_keys_even_with_matching_aggregate_row_chain(runtime):
    rows = [record(), record('1', 'b')]
    file = sidecar(runtime, rows)
    with pytest.raises(ValueError, match='Duplicate complete primary-key'):
        runtime.keyed_row_inventory(file, 2, chain(rows))


@pytest.mark.parametrize('body', [b'{}\n', b'{"rowSha256":"' + b'a' * 64 + b'","keySha256":"' + b'1' * 64 + b'"}\n',
                                  b'{"keySha256":"' + b'1' * 64 + b'","rowSha256":"' + b'a' * 64 + b'"}'])
def test_inventory_requires_exact_canonical_complete_records(runtime, body):
    file = sidecar(runtime, [])
    file.write_bytes(body)
    with pytest.raises(ValueError, match='complete canonical digest records'):
        runtime.keyed_row_inventory(file, 1, chain([record()]))


def test_inventory_refuses_hardlinked_sidecars(runtime):
    rows = [record()]
    file = sidecar(runtime, rows)
    os.link(file, file.with_name('alias.jsonl'))
    with pytest.raises(ValueError, match='regular and unlinked'):
        runtime.keyed_row_inventory(file, 1, chain(rows))


def test_output_refuses_existing_or_aliased_names(runtime):
    file = sidecar(runtime, [])
    with pytest.raises(ValueError, match='new canonical keyed-row file'):
        runtime.keyed_row_output(file)
    alias = file.with_name('alias.jsonl')
    alias.symlink_to(file)
    with pytest.raises(ValueError, match='new canonical keyed-row file'):
        runtime.keyed_row_output(alias)


def test_output_refuses_nonprivate_parent(runtime):
    folder = private_folder(runtime)
    folder.chmod(0o755)
    with pytest.raises(ValueError, match='parent must be private'):
        runtime.keyed_row_output(folder / 'item.jsonl')


class SnapshotMysql:
    def __init__(self, runtime, *, no_primary=False, second=False, drift=False):
        self.runtime, self.no_primary, self.second, self.drift = runtime, no_primary, second, drift
        self.calls = []
        self.columns = [{'name': 'id', 'ordinal': 1, 'type': 'bigint', 'nullable': 'NO',
                         'default': None, 'extra': '', 'generation': '', 'charset': None,
                         'collation': None, 'datetimePrecision': None},
                        {'name': 'payload', 'ordinal': 2, 'type': 'varbinary(16)', 'nullable': 'YES',
                         'default': None, 'extra': '', 'generation': '', 'charset': None,
                         'collation': None, 'datetimePrecision': None}]
        self.rows = [record()]

    def json_rows(self, sql):
        if 'FROM information_schema.tables' in sql:
            names = ['item', 'other'] if self.second else ['item']
            return [{'name': name, 'kind': 'BASE TABLE', 'engine': 'InnoDB', 'collation': 'utf8mb4_bin'} for name in names]
        if 'FROM information_schema.columns' in sql:
            return self.columns
        if 'FROM information_schema.statistics' in sql:
            return [] if self.no_primary else [{'name': 'PRIMARY', 'column': 'id', 'ordinal': 1,
                'expression': None, 'nonUnique': 0, 'subPart': None, 'collation': 'A', 'type': 'BTREE', 'visible': 'YES'}]
        raise AssertionError('Unexpected fake metadata query')

    def single(self, _sql):
        return {'autoIncrement': '2'}

    def script(self, sql, *, label):
        table = re.search(r'SHOW CREATE TABLE `doorhandledb`\.`([a-z]+)`;', sql).group(1)
        return (table + '\tCREATE TABLE `' + table + '` (`id` bigint NOT NULL,`payload` varbinary(16))').encode()

    def row_hashes(self, schema, table, columns, primary, **kwargs):
        self.calls.append((schema, table, columns, primary, kwargs))
        if kwargs:
            with self.runtime.keyed_row_output(kwargs['keyed_rows_path']) as stream:
                for row in self.rows:
                    stream.write(self.runtime.canonical(row) + b'\n')
        return len(self.rows), '0' * 64 if self.drift else chain(self.rows)


def test_snapshot_opt_in_keeps_original_snapshot_v1_unchanged(runtime):
    old_client = SnapshotMysql(runtime)
    old = runtime.schema_snapshot(old_client, 'doorhandledb', ['item'])
    assert old_client.calls[0][-1] == {}
    directory = runtime.ROOT / 'work' / 'sidecars'
    new = runtime.schema_snapshot(SnapshotMysql(runtime), 'doorhandledb', ['item'], keyed_rows_directory=directory)
    assert old == new
    _, index, _ = runtime.private_json(directory / 'index.json')
    assert set(index) == {'schemaVersion', 'kind', 'schema', 'snapshotSha256', 'tables'}
    assert index['kind'] == 'doorhandle-mysql-keyed-row-index' and index['schema'] == new['schema']
    assert index['snapshotSha256'] == new['snapshotSha256']
    table = index['tables']['item']
    assert table['status'] == 'KEYED' and table['primary'] == ['id'] and table['rows'] == table['entries'] == 1
    assert table['rowsSha256'] == new['tables']['item']['rowsSha256']
    assert table['columnsSha256'] == runtime.sha_json(new['tables']['item']['columns'])
    assert table['file'] == 'item.jsonl' and table['fileSha256'] == runtime.sha_file(directory / 'item.jsonl')


def test_snapshot_marks_no_primary_key_instead_of_claiming_key_comparability(runtime):
    client = SnapshotMysql(runtime, no_primary=True)
    directory = runtime.ROOT / 'work' / 'sidecars'
    snapshot = runtime.schema_snapshot(client, 'doorhandledb', ['item'], keyed_rows_directory=directory)
    _, index, _ = runtime.private_json(directory / 'index.json')
    table = index['tables']['item']
    assert table == {'status': 'NO_PRIMARY_KEY', 'rows': 1, 'rowsSha256': snapshot['tables']['item']['rowsSha256'],
                     'columnsSha256': runtime.sha_json(client.columns), 'primary': [],
                     'file': None, 'fileSha256': None, 'bytes': 0, 'entries': 0}
    assert client.calls[0][-1] == {} and list(directory.glob('*.jsonl')) == []


def test_snapshot_refuses_existing_sidecar_directory(runtime):
    directory = private_folder(runtime)
    with pytest.raises(ValueError, match='new canonical keyed-row directory'):
        runtime.schema_snapshot(SnapshotMysql(runtime), 'doorhandledb', ['item'], keyed_rows_directory=directory)


def test_snapshot_requires_sidecar_chain_to_equal_the_actual_snapshot(runtime):
    directory = runtime.ROOT / 'work' / 'sidecars'
    with pytest.raises(ValueError, match='complete actual table row chain'):
        runtime.schema_snapshot(SnapshotMysql(runtime, drift=True), 'doorhandledb', ['item'], keyed_rows_directory=directory)
    assert not (directory / 'index.json').exists()


def test_snapshot_refuses_extra_members_before_publishing_complete_index(runtime):
    class IntrudingMysql(SnapshotMysql):
        def single(self, sql):
            file = self.calls[0][-1]['keyed_rows_path']
            (file.parent / 'unexpected.txt').write_text('not part of this capture')
            return super().single(sql)

    directory = runtime.ROOT / 'work' / 'sidecars'
    with pytest.raises(ValueError, match='unexpected members'):
        runtime.schema_snapshot(IntrudingMysql(runtime), 'doorhandledb', ['item'], keyed_rows_directory=directory)
    assert not (directory / 'index.json').exists()


def test_snapshot_rereads_earlier_sidecars_before_final_index_publication(runtime):
    class ChangingMysql(SnapshotMysql):
        def single(self, sql):
            file = self.calls[0][-1]['keyed_rows_path']
            file.write_bytes(self.runtime.canonical(record('1', 'b')) + b'\n')
            return super().single(sql)

    directory = runtime.ROOT / 'work' / 'sidecars'
    with pytest.raises(ValueError, match='complete actual table row chain'):
        runtime.schema_snapshot(ChangingMysql(runtime), 'doorhandledb', ['item'], keyed_rows_directory=directory)
    assert not (directory / 'index.json').exists()


@pytest.mark.parametrize('limit', ['MAX_KEYED_ROWS_TOTAL', 'MAX_KEYED_ROW_BYTES_TOTAL'])
def test_snapshot_complete_budget_does_not_publish_a_truncated_index(runtime, monkeypatch, limit):
    directory = runtime.ROOT / 'work' / 'sidecars'
    monkeypatch.setattr(runtime, limit, 1)
    with pytest.raises(ValueError, match='complete schema budget'):
        runtime.schema_snapshot(SnapshotMysql(runtime, second=True), 'doorhandledb', ['item', 'other'],
                                keyed_rows_directory=directory)
    assert not (directory / 'index.json').exists()
