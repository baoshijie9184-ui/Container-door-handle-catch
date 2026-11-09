"""Explicit snapshot hashing policies and old-byte/new-recovery compatibility."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT = Path(__file__).resolve().parents[1]
MISSING = object()


@pytest.fixture
def modules(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(PROJECT / 'script/schema'))
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    runtime = load('snapshot_policy_runtime_tests', PROJECT / 'script/schema/compact_migration_runtime.py')
    classifier = load('snapshot_policy_classification_tests', PROJECT / 'script/jenkins/classify-local-mysql-source.py')
    monkeypatch.setattr(runtime, 'ROOT', tmp_path)
    (tmp_path / 'work').mkdir(mode=0o700)
    return SimpleNamespace(runtime=runtime, classifier=classifier, root=tmp_path)


def snapshot(runtime, *, policy=MISSING, explicit_charset=False):
    columns = [{'name': 'id', 'ordinal': 1, 'type': 'varchar(36)', 'nullable': 'NO', 'default': None,
                'extra': '', 'generation': '', 'charset': 'utf8mb4', 'collation': 'utf8mb4_bin', 'datetimePrecision': None}]
    declaration = '`id` varchar(36)' + (' CHARACTER SET utf8mb4' if explicit_charset else '') + ' COLLATE utf8mb4_bin NOT NULL'
    ddl = 'CREATE TABLE `item` (\n  ' + declaration + '\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin'
    normalized = runtime.ddl_policy.normalize_ddl(ddl, 'doorhandledb', columns,
        policy=runtime.ddl_policy.RAW_POLICY if policy is MISSING else policy)
    table = {'rows': 1, 'rowsSha256': 'a' * 64, 'autoIncrement': None, 'columns': columns, 'indexes': [],
             'collation': 'utf8mb4_bin', 'ddlSha256': runtime.hashlib.sha256(normalized.encode()).hexdigest()}
    value = {'schemaVersion': 1, 'schema': 'doorhandledb', 'tables': {'item': table}, 'createTables': {'item': ddl}}
    if policy is not MISSING:
        value['ddlHashPolicy'] = policy
    value['snapshotSha256'] = runtime.sha_json(runtime.snapshot_hash_payload(value))
    return value


def test_unmarked_snapshot_keeps_the_original_exact_v1_digest(modules):
    runtime = modules.runtime
    old = snapshot(runtime, explicit_charset=True)
    assert runtime.snapshot_ddl_policy(old) is None
    assert runtime.snapshot_hash_payload(old) == {'schemaVersion': 1, 'tables': old['tables']}
    assert old['snapshotSha256'] == runtime.sha_json({'schemaVersion': 1, 'tables': old['tables']})
    assert modules.classifier.validate_snapshot(old, 1) == old['snapshotSha256']


@pytest.mark.parametrize('policy', ['RAW_SHOW_CREATE_V1', 'CATALOG_VERIFIED_UTF8MB4_BIN_CHARSET_V1'])
def test_explicit_policy_is_part_of_the_snapshot_digest(modules, policy):
    runtime = modules.runtime
    current = snapshot(runtime, policy=policy)
    assert runtime.snapshot_hash_payload(current)['ddlHashPolicy'] == policy
    assert current['snapshotSha256'] != runtime.sha_json({'schemaVersion': 1, 'tables': current['tables']})
    assert modules.classifier.validate_snapshot(current, 1) == current['snapshotSha256']


def test_only_current_proven_charset_policy_equates_redundant_spellings(modules):
    runtime = modules.runtime
    canonical = runtime.ddl_policy.CANONICAL_POLICY
    current = snapshot(runtime, policy=canonical)
    with_charset = snapshot(runtime, policy=canonical, explicit_charset=True)
    assert current['snapshotSha256'] == with_charset['snapshotSha256']
    assert current['createTables'] != with_charset['createTables']
    assert modules.classifier.validate_snapshot(with_charset, 1) == current['snapshotSha256']
    assert snapshot(runtime)['snapshotSha256'] != snapshot(runtime, explicit_charset=True)['snapshotSha256']


def test_declaring_a_new_policy_cannot_reinterpret_an_old_digest(modules):
    old = snapshot(modules.runtime, explicit_charset=True)
    changed = copy.deepcopy(old)
    changed['ddlHashPolicy'] = modules.runtime.ddl_policy.CANONICAL_POLICY
    with pytest.raises(ValueError):
        modules.classifier.validate_snapshot(changed, 1)
    assert 'ddlHashPolicy' not in old


@pytest.mark.parametrize('policy', [None, 'UNKNOWN_POLICY', False, 2, {}, []])
def test_present_unknown_or_null_policy_is_not_legacy_mode(modules, policy):
    value = snapshot(modules.runtime)
    value['ddlHashPolicy'] = policy
    with pytest.raises(ValueError):
        modules.runtime.snapshot_hash_payload(value)
    with pytest.raises(ValueError):
        modules.classifier.validate_snapshot(value, 1)


@pytest.mark.parametrize('policy', [MISSING, 'RAW_SHOW_CREATE_V1', 'CATALOG_VERIFIED_UTF8MB4_BIN_CHARSET_V1'])
def test_backup_carries_exact_policy_without_rewriting_the_source_snapshot(modules, monkeypatch, policy):
    runtime = modules.runtime
    original = snapshot(runtime, policy=policy)
    before = copy.deepcopy(original)
    class Mysql:
        config = {'serverUuid': '11111111-1111-1111-1111-111111111111'}
        def data_dump(self, schema, tables, path):
            path.write_bytes(b'-- synthetic retained dump\n')
            path.chmod(0o600)
            return {'sha256': runtime.sha_file(path), 'bytes': path.stat().st_size}
    monkeypatch.setattr(runtime, 'metadata_snapshot', lambda *_args: ({}, 'b' * 64))
    monkeypatch.setattr(runtime, 'trigger_catalog', lambda *_args: [])
    path = runtime.backup_schema(Mysql(), original, modules.root / 'work/backup', purpose='source',
                                  migration_context={'kind': 'synthetic-owned-recovery'})
    _, manifest, _ = runtime.private_json(path)
    assert manifest['snapshotSha256'] == original['snapshotSha256']
    assert manifest['tables'] == original['tables'] and manifest['createTables'] == original['createTables']
    assert ('ddlHashPolicy' in manifest) is (policy is not MISSING)
    if policy is not MISSING:
        assert manifest['ddlHashPolicy'] == policy
    assert original == before


def test_restore_refuses_unknown_policy_before_creating_or_querying_a_schema(modules, monkeypatch):
    runtime = modules.runtime
    manifest = {'schemaVersion': 1, 'kind': 'doorhandle-mysql-private-backup',
                'serverUuid': '11111111-1111-1111-1111-111111111111', 'ddlHashPolicy': 'UNSUPPORTED'}
    calls = iter([(modules.root / 'backup.json', manifest, 'a' * 64),
                  (modules.root / 'evidence.json', {}, 'b' * 64)])
    monkeypatch.setattr(runtime, 'private_json', lambda *_args, **_kwargs: next(calls))
    def refuse(*_args, **_kwargs):
        pytest.fail('An unsupported old-backup policy must stop before any schema operation')
    monkeypatch.setattr(runtime, 'new_schema', refuse)
    mysql = SimpleNamespace(config={'serverUuid': manifest['serverUuid']}, script=refuse)
    with pytest.raises(ValueError, match='Unknown snapshot DDL hash policy'):
        runtime.restore_backup(mysql, modules.root / 'backup.json', 'restore', modules.root / 'output', modules.root / 'evidence.json')


@pytest.mark.parametrize('policy', [MISSING, 'RAW_SHOW_CREATE_V1', 'CATALOG_VERIFIED_UTF8MB4_BIN_CHARSET_V1'])
def test_restore_explicitly_uses_the_backup_policy_including_unmarked_legacy(modules, monkeypatch, policy):
    runtime = modules.runtime
    original = snapshot(runtime, policy=policy, explicit_charset=True)
    before = copy.deepcopy(original)
    folder = modules.root / 'work/backup'
    folder.mkdir(mode=0o700)
    data = folder / 'data.sql'
    data.write_bytes(b'-- synthetic retained original bytes\n')
    data.chmod(0o600)
    server_uuid = '11111111-1111-1111-1111-111111111111'
    migration_context = {'kind': 'synthetic-owned-recovery'}
    manifest = {**original, 'kind': 'doorhandle-mysql-private-backup', 'purpose': 'source',
        'serverUuid': server_uuid, 'metadataSha256': 'b' * 64, 'triggers': [], 'migrationContext': migration_context,
        'data': {'file': 'data.sql', 'sha256': runtime.sha_file(data), 'bytes': data.stat().st_size}}
    manifest_path = folder / 'manifest.json'
    runtime.write_json(manifest_path, manifest)
    evidence = {'schemaVersion': 1, 'kind': 'doorhandle-compact-migration-evidence', 'status': 'COPY_VERIFIED',
        'migrationContext': migration_context, 'sourceSnapshotSha256': original['snapshotSha256'],
        'scope': 'ecs-disposable-migration', 'serverUuid': server_uuid, 'attempt': 'a' * 32,
        'ecs': {'instanceId': 'i-test', 'machineId': 'b' * 32}, 'sourceSchema': 'doorhandledb',
        'targetSchema': 'doorhandle_compact_candidate_0123456789', 'contractSha256': 'c' * 64,
        'sqlSha256': 'd' * 64, 'copyPlanSha256': 'e' * 64, 'targetMetadataSha256': 'f' * 64}
    evidence_path = folder / 'copy-evidence.json'
    runtime.write_json(evidence_path, evidence)
    restore_schema = 'doorhandle_legacy_restore_0123456789'
    selected = []
    class Mysql:
        config = {'serverUuid': server_uuid, 'recoverySchemas': {'source': restore_schema}}
        def script(self, *_args, **_kwargs):
            return b''
    def capture(_mysql, schema, tables, *, ddl_hash_policy):
        selected.append(ddl_hash_policy)
        value = copy.deepcopy(original)
        value['schema'] = schema
        return value
    monkeypatch.setattr(runtime, 'new_schema', lambda *_args: None)
    monkeypatch.setattr(runtime, 'remove_inline_foreign_keys', lambda sql, _schema: (sql, []))
    monkeypatch.setattr(runtime, 'restore_data', lambda *_args: None)
    monkeypatch.setattr(runtime, 'install_relations', lambda *_args: None)
    monkeypatch.setattr(runtime, 'install_triggers', lambda *_args: None)
    monkeypatch.setattr(runtime, 'schema_snapshot', capture)
    monkeypatch.setattr(runtime, 'metadata_snapshot', lambda *_args: ({}, 'b' * 64))
    result = runtime.restore_backup(Mysql(), manifest_path, restore_schema, modules.root / 'work/recovery', evidence_path)
    assert selected == [None if policy is MISSING else policy]
    assert result['status'] == 'VERIFIED' and result['expectedSnapshotSha256'] == original['snapshotSha256']
    assert result['restoredSnapshotSha256'] == original['snapshotSha256'] and original == before
