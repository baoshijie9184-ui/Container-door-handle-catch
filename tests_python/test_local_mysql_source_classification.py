"""ECS-only synthetic JSON contracts; no database, SQL execution or live service."""
import copy
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import tarfile
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('fixed_local_source_json_classification',
    ROOT / 'script/jenkins/classify-local-mysql-source.py')
classifier = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(classifier)
COLLECTOR_SPEC = importlib.util.spec_from_file_location('fixed_legacy_column_projection_collector',
    ROOT / 'script/jenkins/collect-local-mysql-legacy-projection.py')
collector = importlib.util.module_from_spec(COLLECTOR_SPEC); COLLECTOR_SPEC.loader.exec_module(collector)


def test_projection_source_archive_reader_and_remote_guards_bind_real_dependency_paths(tmp_path, monkeypatch, capsys):
    """Exercise the actual PS reader: a nonexistent builder path must not pass mocks."""
    controller = ROOT / 'script/jenkins/preserve-local-mysql.ps1'
    program = controller.read_text(encoding='utf-8')
    readers = re.findall(r"(?ms)^\$archiveReader = @'\r?\n(.*?)\r?\n'@$", program)
    assert len(readers) == 1
    members = {name: 'script/jenkins/' + name for name in ('preserve-local-mysql.py',
        'restore-local-mysql.py', 'classify-local-mysql-source.py', 'collect-local-mysql-legacy-projection.py')}
    members.update({'compact-schema-contract.json': 'docs/database/compact-schema-contract.json',
        'compact_ddl_policy.py': 'script/schema/compact_ddl_policy.py',
        'compact_migration_runtime.py': 'script/schema/compact_migration_runtime.py',
        'compact_clock_policy.py': 'script/schema/compact_clock_policy.py',
        'build_compact_schema.py': 'script/schema/build_compact_schema.py',
        'ecs_execution.py': 'scripts/ecs_execution.py'})
    commit = 'a' * 40
    archive_path = tmp_path / 'fixed-source.tar.gz'
    hashes = {}
    with tarfile.open(archive_path, 'x:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': commit}) as archive:
        for name, path in members.items():
            body = (ROOT / path).read_bytes()
            member = tarfile.TarInfo(path); member.size = len(body)
            archive.addfile(member, io.BytesIO(body))
            hashes[name] = hashlib.sha256(body).hexdigest()
    with monkeypatch.context() as patch:
        patch.setattr(sys, 'argv', ['archive-reader', str(archive_path), commit])
        exec(compile(readers[0], str(controller) + ':archiveReader', 'exec'), {})
    assert json.loads(capsys.readouterr().out) == hashes
    guards = program.split('foreach ($entry in ', 1)[1].split('$projectionLines = ', 1)[0]
    dependencies = re.findall(r"@\('([^']+)','([^']+)'\)", guards)
    assert len(dependencies) == 4 and {name for name, _directory in dependencies} == {
        'compact_migration_runtime.py', 'compact_clock_policy.py', 'build_compact_schema.py', 'ecs_execution.py'}
    assert all(members[name] == directory + '/' + name for name, directory in dependencies)
    assert '$RemoteRoot/verification/$Tag/checkout/$($entry[1])/$($entry[0])' in guards
    assert '$boundSha = $sourceHashes.($entry[0])' in guards


def raw(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def column(name, ordinal, kind, nullable):
    return {'name': name, 'ordinal': ordinal, 'type': kind, 'nullable': nullable, 'default': None, 'extra': '',
            'generation': '', 'charset': None, 'collation': None, 'datetimePrecision': None}


def detail(name):
    ddl = 'CREATE TABLE `' + name + '` (`id` bigint NOT NULL, `body` varbinary(20), PRIMARY KEY (`id`))'
    table = {'rows': 1, 'rowsSha256': sha(raw([name, 'opaque row values'])), 'autoIncrement': '2',
        'columns': [column('id', 1, 'bigint', 'NO'), column('body', 2, 'varbinary(20)', 'YES')],
        'indexes': [{'name': 'PRIMARY', 'ordinal': 1, 'column': 'id', 'expression': None, 'nonUnique': 0,
                     'subPart': None, 'collation': 'A', 'type': 'BTREE', 'visible': 'YES'}],
        'collation': 'utf8mb4_0900_ai_ci', 'ddlSha256': sha(ddl.encode())}
    return table, ddl


def snapshot(names):
    pairs = {name: detail(name) for name in names}
    tables = {name: pair[0] for name, pair in pairs.items()}
    return {'schemaVersion': 1, 'schema': 'doorhandledb', 'snapshotSha256': sha(raw({'schemaVersion': 1, 'tables': tables})),
            'tables': tables, 'createTables': {name: pair[1] for name, pair in pairs.items()}}


def update_source(fixture):
    source = fixture.values['sourceManifest']; owner = fixture.values['fixtureOwner']
    source['snapshotSha256'] = sha(raw({'schemaVersion': 1, 'tables': source['tables']}))
    owner['sourceSnapshotSha256'] = source['snapshotSha256']
    owner['sourceRows'] = sum(row['rows'] for row in source['tables'].values())


def bind(fixture):
    values = fixture.values; owner = values['localOwner']; public = values['localPublic']
    owner['cleanupEvidence'].update({
        'local-mysql-recovery/a/full-recovery-private.json': sha(raw(values['localA'])),
        'local-mysql-recovery/b/full-recovery-private.json': sha(raw(values['localB']))})
    public['logicalEvidenceCatalogueSha256'] = sha(raw(owner['cleanupEvidence']))
    owner['publicRecoverySha256'] = sha(raw(public))
    values['fixtureOwner']['sourceBackupSha256'] = sha(raw(values['sourceManifest']))
    documents = {key: raw(value) for key, value in values.items()}
    anchors = {key: sha(documents[key]) for key in classifier.ANCHORS}
    return documents, anchors


def classify(fixture):
    documents, anchors = bind(fixture)
    return classifier.classify_documents(documents, expected_context=fixture.context, anchors=anchors)


def row_chain(rows):
    chain = hashlib.sha256(b'compact-row-hash-chain-v1\n')
    for _key, value in rows: chain.update(bytes.fromhex(value))
    return chain.hexdigest()


def refresh_keyed(fixture):
    """Synthetic authenticated collector output; no DB, process or file I/O."""
    captures = {}; values = fixture.values
    for role in classifier.KEYED_ROLES:
        snap = values['sourceManifest'] if role == 'source' else values[role]['snapshot']
        for name, table in snap['tables'].items():
            rows = fixture.keyed_rows[role][name]
            table.update(rows=len(rows), rowsSha256=row_chain(rows))
        snap['snapshotSha256'] = sha(raw({'schemaVersion': 1, 'tables': snap['tables']}))
        index = {'schemaVersion': 1, 'kind': 'doorhandle-mysql-keyed-row-index', 'schema': snap['schema'],
                 'snapshotSha256': snap['snapshotSha256'], 'tables': {}}
        members = {}
        for name, table in snap['tables'].items():
            primary = classifier.primary_columns(table); rows = fixture.keyed_rows[role][name]
            body = b''.join(raw({'keySha256': key, 'rowSha256': value}) + b'\n' for key, value in rows)
            index['tables'][name] = {'status': 'KEYED' if primary else 'NO_PRIMARY_KEY', 'rows': len(rows),
                'rowsSha256': table['rowsSha256'], 'columnsSha256': sha(raw(table['columns'])), 'primary': primary,
                'file': name + '.jsonl' if primary else None, 'fileSha256': sha(body) if primary else None,
                'bytes': len(body) if primary else 0, 'entries': len(rows) if primary else 0}
            if primary: members[name] = body
        index_raw = raw(index) + b'\n'
        ref = {'file': 'source-keyed-rows/index.json' if role == 'source' else 'keyed-rows/index.json',
               'sha256': sha(index_raw), 'bytes': len(index_raw)}
        if role == 'source': values['fixtureOwner']['sourceKeyedRowsIndex'] = ref
        else: values[role]['keyedRowsIndex'] = ref
        captures[role] = {'index': index_raw, 'tables': members}
    values['localPublic']['snapshotSha256'] = values['localA']['snapshot']['snapshotSha256']
    values['localPublic']['restoredRows'] = sum(row['rows'] for row in values['localA']['snapshot']['tables'].values())
    update_source(fixture); fixture.keyed_documents = captures
    return fixture


def reconcile(fixture):
    documents, anchors = bind(fixture)
    return classifier.reconcile_keyed_documents(documents, expected_context=fixture.context, anchors=anchors,
                                                keyed_documents=fixture.keyed_documents)


@pytest.fixture
def keyed_bundle(bundle):
    bundle.keyed_rows = {}
    for role in classifier.KEYED_ROLES:
        snap = bundle.values['sourceManifest'] if role == 'source' else bundle.values[role]['snapshot']
        bundle.keyed_rows[role] = {name: [(sha((name + '/key').encode()), sha((name + '/row').encode()))]
                                  for name in snap['tables']}
    return refresh_keyed(bundle)


def test_old_snapshot_classification_explicitly_blocks_uncollected_key_subgate(bundle):
    result = classify(bundle)['perKeyReconciliation']
    assert result['status'] == 'NOT_COLLECTED' and result['cutoverBlocked'] is True
    assert result['legacyRowsPresentInSource'] is False and result['requiredBeforeCutover'] is True
    assert result['wholeMigrationAndRuntimeAcceptanceStillRequired'] is True


def test_keyed_full_row_inclusion_has_no_merge_or_target29_authority(keyed_bundle, monkeypatch):
    monkeypatch.setattr(Path, 'open', lambda *_a, **_k: pytest.fail('Pure reconciliation performed file I/O'))
    result = reconcile(keyed_bundle); summary = result['summary']
    assert summary['status'] == 'RECONCILED' and summary['legacyRowsPresentInSource'] is True
    assert summary['counts'] == {'MATCH': 45, 'LOCAL_ONLY': 0, 'SOURCE_ONLY': 0, 'ROW_CONFLICT': 0}
    assert summary['gateScope'] == 'PER_KEY_SOURCE_INCLUSION_ONLY' and summary['cutoverBlocked'] is False
    assert summary['wholeMigrationAndRuntimeAcceptanceStillRequired'] is True and result['differences'] == []
    assert all(summary[field] is False for field in ('coverageVerified', 'targetDataCompared', 'productionMerged', 'retirementAllowed'))
    assert summary['clockPolicy'] == 'EXACT_ORIGINAL_BYTES_NO_TIMEZONE_INFERENCE'


def test_source_superset_keeps_every_local_row_and_lists_only_opaque_differences(keyed_bundle):
    keyed_bundle.keyed_rows['source']['table_000'].append(('e' * 64, 'f' * 64)); refresh_keyed(keyed_bundle)
    result = reconcile(keyed_bundle)
    assert result['summary']['status'] == 'RECONCILED' and result['summary']['counts']['SOURCE_ONLY'] == 1
    assert result['differences'] == [{'table': 'table_000', 'status': 'SOURCE_ONLY', 'keySha256': 'e' * 64,
                                     'localRowSha256': None, 'sourceRowSha256': 'f' * 64}]


def test_missing_legacy_key_is_a_cutover_blocker_even_with_valid_source_snapshot(keyed_bundle):
    keyed_bundle.keyed_rows['source']['table_000'] = []; refresh_keyed(keyed_bundle)
    result = reconcile(keyed_bundle)
    assert result['summary']['status'] == 'NEEDS_REVIEW' and result['summary']['cutoverBlocked'] is True
    assert result['summary']['counts']['LOCAL_ONLY'] == 1
    assert result['differences'][0]['sourceRowSha256'] is None


def test_same_primary_key_with_changed_complete_row_is_not_merged(keyed_bundle):
    key, _row = keyed_bundle.keyed_rows['source']['table_000'][0]
    keyed_bundle.keyed_rows['source']['table_000'] = [(key, 'd' * 64)]; refresh_keyed(keyed_bundle)
    result = reconcile(keyed_bundle)
    assert result['summary']['counts']['ROW_CONFLICT'] == 1 and result['summary']['cutoverBlocked'] is True
    assert result['differences'][0]['status'] == 'ROW_CONFLICT'


@pytest.mark.parametrize('field,value', [('type', 'bigint unsigned'), ('nullable', 'YES'), ('default', '0'),
                                        ('collation', 'utf8mb4_bin'), ('datetimePrecision', 6)])
def test_no_common_column_projection_or_clock_guess_for_incompatible_schema(keyed_bundle, field, value):
    keyed_bundle.values['sourceManifest']['tables']['table_000']['columns'][0][field] = value
    refresh_keyed(keyed_bundle); result = reconcile(keyed_bundle)['summary']
    row = next(row for row in result['tableComparisons'] if row['table'] == 'table_000')
    assert row['status'] == 'NOT_COMPARABLE' and row['reasonCode'] == 'FULL_TYPED_COLUMNS_OR_PRIMARY_ORDER_DIFFER'
    assert result['cutoverBlocked'] is True and result['legacyRowsPresentInSource'] is False


def test_without_complete_primary_key_no_key_comparability_is_claimed(keyed_bundle):
    for role in classifier.KEYED_ROLES:
        snapshot = keyed_bundle.values['sourceManifest'] if role == 'source' else keyed_bundle.values[role]['snapshot']
        snapshot['tables']['table_000']['indexes'] = []
    refresh_keyed(keyed_bundle); result = reconcile(keyed_bundle)['summary']
    assert result['cutoverBlocked'] is True
    assert {'table': 'table_000', 'reasonCode': 'NO_PRIMARY_KEY'} in result['blockingTables']


def test_duplicate_key_is_rejected_instead_of_overwriting_prior_row(keyed_bundle):
    for role in ('localA', 'localB'):
        keyed_bundle.keyed_rows[role]['table_000'].append(keyed_bundle.keyed_rows[role]['table_000'][0])
    refresh_keyed(keyed_bundle)
    with pytest.raises(classifier.ClassificationError, match='DUPLICATE_PRIMARY_KEY_DIGEST'):
        reconcile(keyed_bundle)


@pytest.mark.parametrize('role', ['localA', 'localB', 'source'])
def test_sidecar_file_tampering_is_rejected_by_trusted_index(keyed_bundle, role):
    keyed_bundle.keyed_documents[role]['tables']['table_000'] = b''
    with pytest.raises(classifier.ClassificationError, match='KEYED_ROWS_FILE_DIGEST_DRIFT'):
        reconcile(keyed_bundle)


def test_standalone_self_consistent_index_cannot_replace_owner_authentication(keyed_bundle):
    index = json.loads(keyed_bundle.keyed_documents['source']['index'])
    index['tables']['table_000']['fileSha256'] = 'f' * 64
    keyed_bundle.keyed_documents['source']['index'] = raw(index) + b'\n'
    with pytest.raises(classifier.ClassificationError, match='TRUSTED_KEYED_INDEX_BINDING_DRIFT'):
        reconcile(keyed_bundle)


def test_different_local_key_streams_fail_independent_recovery_check(keyed_bundle):
    _key, row = keyed_bundle.keyed_rows['localB']['table_000'][0]
    keyed_bundle.keyed_rows['localB']['table_000'] = [('f' * 64, row)]; refresh_keyed(keyed_bundle)
    with pytest.raises(classifier.ClassificationError, match='INDEPENDENT_KEYED_RECOVERY_INDEXES_DIFFER'):
        reconcile(keyed_bundle)


def test_source_only_table_digest_is_checked_even_without_legacy_rows(keyed_bundle):
    keyed_bundle.keyed_documents['source']['tables']['table_130'] = b''
    with pytest.raises(classifier.ClassificationError, match='KEYED_ROWS_FILE_DIGEST_DRIFT'):
        reconcile(keyed_bundle)


@pytest.mark.parametrize('damage', ['missing-table', 'extra-table', 'missing-role'])
def test_keyed_evidence_membership_is_closed(keyed_bundle, damage):
    if damage == 'missing-table': keyed_bundle.keyed_documents['source']['tables'].pop('table_000')
    elif damage == 'extra-table': keyed_bundle.keyed_documents['source']['tables']['unknown'] = b''
    else: keyed_bundle.keyed_documents.pop('localB')
    with pytest.raises(classifier.ClassificationError, match='COMPLETE_KEYED_'):
        reconcile(keyed_bundle)


def test_keyed_bundle_limits_are_enforced_without_partial_success(keyed_bundle, monkeypatch):
    monkeypatch.setattr(classifier, 'MAX_KEYED_BUNDLE_BYTES', 1)
    with pytest.raises(classifier.ClassificationError, match='KEYED_.*BUDGET_EXCEEDED|KEYED_BUNDLE_BYTE_LIMIT_EXCEEDED'):
        reconcile(keyed_bundle)


@pytest.fixture
def evolution_bundle(keyed_bundle, monkeypatch):
    value = keyed_bundle; rules = copy.deepcopy(classifier.LEGACY_EVOLUTION)
    for previous, name in (('table_000', 'detection_task'), ('table_001', 'model_management')):
        for role in classifier.KEYED_ROLES:
            snap = value.values['sourceManifest'] if role == 'source' else value.values[role]['snapshot']
            table = snap['tables'].pop(previous); snap['tables'][name] = table
            snap['createTables'][name] = snap['createTables'].pop(previous).replace(previous, name)
            table['ddlSha256'] = sha(snap['createTables'][name].encode())
            table['columns'] += [column('legacy_' + str(i), i, 'int', 'YES')
                                 for i in range(3, rules[name]['oldCount'] + 1)]
            if role == 'source':
                table['columns'] += [column('appended_' + str(i), i, 'int', 'YES')
                                    for i in range(rules[name]['oldCount'] + 1, rules[name]['sourceCount'] + 1)]
            value.keyed_rows[role][name] = value.keyed_rows[role].pop(previous)
            if role == 'source':
                key, _ = value.keyed_rows[role][name][0]
                value.keyed_rows[role][name] = [(key, sha((name + '/full-new-vector').encode()))]
        model = value.values['contract']
        model['sourceTables'] = [name if item == previous else item for item in model['sourceTables']]
        for mapping in model['mapping']:
            mapping['sources'] = [name if item == previous else item for item in mapping['sources']]
        rules[name]['oldSha256'] = sha(raw(value.values['localA']['snapshot']['tables'][name]['columns']))
        rules[name]['sourceSha256'] = sha(raw(value.values['sourceManifest']['tables'][name]['columns']))
    # Synthetic vectors replace only the cryptographic pins. Production's real
    # #107/#188 vectors are never accepted by a general name/column intersection.
    monkeypatch.setattr(classifier, 'LEGACY_EVOLUTION', rules)
    monkeypatch.setattr(collector, 'audit', classifier)
    refresh_keyed(value)
    owner = value.values['fixtureOwner']; source = value.values['sourceManifest']
    owner.update(serverUuid='44444444-4444-4444-4444-444444444444', containerId='4' * 64,
        sourceClone='doorhandle_legacy_verify_0123456789', sourceCloneSnapshotSha256=source['snapshotSha256'])
    clone = {'schemaVersion': 1, 'kind': 'doorhandle-source-clone-comparison', **value.context,
        'sourceSnapshotSha256': source['snapshotSha256'], 'cloneSnapshotSha256': source['snapshotSha256'],
        'sourceMetadataSha256': source['metadataSha256'], 'cloneMetadataSha256': source['metadataSha256'],
        'snapshotFieldsDifferent': {}, 'businessRowValuesIncluded': False}
    whole = {'schemaVersion': 1, 'kind': 'doorhandle-compact-migration', 'status': 'VERIFIED',
        'scope': 'ecs-disposable-migration', 'ecs': value.context['identity'], 'serverUuid': owner['serverUuid'],
        'sourceSchema': owner['sourceClone'], 'targetSchema': 'doorhandle_compact_candidate_0123456789',
        'sourceTableCount': 131, 'targetTableCount': 29, 'sourceSnapshotSha256': source['snapshotSha256'],
        'sourceMetadataSha256': source['metadataSha256'], 'sourceSnapshot': {'tables': source['tables']},
        'contractSha256': sha(raw(value.values['contract'])), 'foreignKeysValidated': True,
        'attempt': 'a' * 32, 'targetSnapshotSha256': 'c' * 64, 'targetMetadataSha256': 'd' * 64,
        'freezeEvidenceSha256': None}
    readback = {'kind': 'doorhandle-compact-cutover-readback', 'status': 'VERIFIED',
        **{key: whole[key] for key in ('ecs', 'serverUuid', 'sourceSchema', 'targetSchema', 'attempt',
            'sourceSnapshotSha256', 'targetSnapshotSha256', 'targetMetadataSha256', 'freezeEvidenceSha256')},
        'migrationReceiptSha256': sha(raw(whole))}
    supplied = {'version': 1, 'kind': 'doorhandle-runtime-migration-input', 'ecs': value.context['identity'],
        'serverUuid': owner['serverUuid'], 'migrationReceiptSha256': sha(raw(whole))}
    summary = {'kind': 'doorhandle-compact-migration-acceptance', 'status': 'VERIFIED', 'sourceTableCount': 131,
        'targetTableCount': 29, 'migrationReceiptSha256': sha(raw(whole)), 'sourceSnapshotSha256': source['snapshotSha256']}
    verifier = {'status': 'PASS', 'identity': value.context['identity'], 'scopeKind': 'mysql',
        'wholeMigrationRequested': True, 'wholeMigrationSummarySha256': sha(raw(summary)),
        'wholeMigrationTests': {'passed': 1, 'failed': 0, 'skipped': 0}}
    proofs = dict(zip(classifier.PROJECTION_PROOFS, map(raw, (clone, supplied, whole, readback, summary, verifier))))
    value.values['verification']['reportFiles'] = [
        {'path': path, 'bytes': len(proofs[role]), 'sha256': sha(proofs[role])}
        for role, path in (('verifier', 'reports/receipt.json'), ('wholeSummary', 'reports/migration.json'))]
    for role in ('localOwner', 'localPublic'):
        value.values[role]['verificationReceiptSha256'] = sha(raw(value.values['verification']))
    documents, anchors = bind(value)
    source_index = json.loads(value.keyed_documents['source']['index']); members = {}; descriptors = {}
    for name in rules:
        rows = value.keyed_rows['localA'][name]
        body = b''.join(raw({'keySha256': key, 'rowSha256': digest}) + b'\n' for key, digest in rows)
        members[name] = body
        descriptors[name] = {'status': 'KEYED', 'rows': len(rows), 'rowsSha256': row_chain(rows),
            'columnsSha256': rules[name]['oldSha256'], 'primary': ['id'], 'file': name + '.jsonl',
            'fileSha256': sha(body), 'bytes': len(body), 'entries': len(rows),
            'sourceColumnsSha256': rules[name]['sourceSha256'],
            'fullSourceDescriptorSha256': sha(raw(source_index['tables'][name]))}
    receipt = {'schemaVersion': 1, 'kind': 'doorhandle-source-legacy-projection', 'status': 'VERIFIED', **value.context,
        'ruleEvidenceSha256': classifier.LEGACY_EVOLUTION_EVIDENCE_SHA256,
        'inputRawSha256': {key: sha(body) for key, body in documents.items()},
        'proofRawSha256': {key: sha(body) for key, body in proofs.items()},
        'fullSourceIndexSha256': owner['sourceKeyedRowsIndex']['sha256'], 'sourceServerUuid': source['serverUuid'],
        'cloneServerUuid': owner['serverUuid'], 'cloneContainerId': owner['containerId'],
        'sourceContainerId': owner['sourceContainerId'], 'sourceClone': owner['sourceClone'],
        'beforeSnapshotSha256': source['snapshotSha256'], 'afterSnapshotSha256': source['snapshotSha256'],
        'beforeMetadataSha256': source['metadataSha256'], 'afterMetadataSha256': source['metadataSha256'], 'tables': descriptors,
        'sourceScope': 'SAME_BUILD_FULL_131_FROZEN_SOURCE_CLONE', 'productionMerged': False, 'retirementAllowed': False,
        'sourceReadLock': {'kind': 'MYSQL_LOCK_TABLES_READ', 'sourceTableCount': 131}}
    value.projection_packet = {'receipt': raw(receipt), 'proofs': proofs, 'tables': members}
    value.projection_receipt = receipt; value.documents = documents; value.anchors = anchors
    return value


def projected_reconcile(value):
    return classifier.reconcile_keyed_documents(value.documents, expected_context=value.context, anchors=value.anchors,
        keyed_documents=value.keyed_documents, projection_documents=value.projection_packet,
        projection_anchor=sha(value.projection_packet['receipt']))


def test_approved_old_vectors_compare_without_discarding_the_full_source_index(evolution_bundle):
    result = projected_reconcile(evolution_bundle)['summary']
    assert result['status'] == 'RECONCILED' and result['counts']['MATCH'] == 45
    assert result['legacyColumnProjection']['tables'] == ['detection_task', 'model_management']
    assert result['legacyColumnProjection']['fullSourceColumnsAndRowsRetained'] is True
    assert result['indexSha256']['source'] == sha(evolution_bundle.keyed_documents['source']['index'])
    assert all(result[key] is False for key in ('coverageVerified', 'targetDataCompared', 'productionMerged', 'retirementAllowed'))


def test_audited_evolution_without_projection_still_blocks_cutover(evolution_bundle):
    value = evolution_bundle
    summary = classifier.reconcile_keyed_documents(value.documents, expected_context=value.context,
        anchors=value.anchors, keyed_documents=value.keyed_documents)['summary']
    assert summary['status'] == 'NEEDS_REVIEW' and summary['cutoverBlocked'] is True
    assert summary['legacyRowsPresentInSource'] is False
    assert {row['table'] for row in summary['blockingTables']} == set(classifier.LEGACY_EVOLUTION)


@pytest.mark.parametrize('damage', ['old-type', 'appended-default', 'primary-order'])
def test_closed_evolution_rule_rejects_any_further_column_or_primary_change(evolution_bundle, damage):
    local = copy.deepcopy(evolution_bundle.values['localA']['snapshot']['tables']['detection_task'])
    source = copy.deepcopy(evolution_bundle.values['sourceManifest']['tables']['detection_task'])
    if damage == 'old-type': source['columns'][0]['type'] = 'bigint unsigned'
    elif damage == 'appended-default': source['columns'][-1]['default'] = '42'
    else: source['indexes'][0]['column'] = 'body'
    assert classifier.approved_legacy_projection('detection_task', local, source) is False


@pytest.mark.parametrize('damage', ['missing-table', 'wrong-columns', 'wrong-original-index', 'source-changed', 'wrong-machine'])
def test_projection_evidence_cannot_expand_or_rebind_its_scope(evolution_bundle, damage):
    value = evolution_bundle; receipt = value.projection_receipt
    if damage == 'missing-table': receipt['tables'].pop('detection_task')
    elif damage == 'wrong-columns': receipt['tables']['detection_task']['columnsSha256'] = 'f' * 64
    elif damage == 'wrong-original-index': receipt['tables']['detection_task']['fullSourceDescriptorSha256'] = 'f' * 64
    elif damage == 'source-changed': receipt['afterSnapshotSha256'] = 'f' * 64
    else: receipt['identity'] = {**receipt['identity'], 'machineId': '0' * 32}
    value.projection_packet['receipt'] = raw(receipt)
    with pytest.raises(classifier.ClassificationError): projected_reconcile(value)


def test_projection_rows_are_rehashed_and_not_accepted_from_a_header(evolution_bundle):
    evolution_bundle.projection_packet['tables']['detection_task'] = b''
    with pytest.raises(classifier.ClassificationError, match='KEYED_ROWS_FILE_DIGEST_DRIFT'):
        projected_reconcile(evolution_bundle)


def test_projection_with_a_different_source_key_set_is_rejected(evolution_bundle):
    value = evolution_bundle; name = 'detection_task'; rows = [('e' * 64, 'f' * 64)]
    body = raw({'keySha256': rows[0][0], 'rowSha256': rows[0][1]}) + b'\n'
    value.projection_packet['tables'][name] = body
    value.projection_receipt['tables'][name].update(fileSha256=sha(body), bytes=len(body), rowsSha256=row_chain(rows))
    value.projection_packet['receipt'] = raw(value.projection_receipt)
    with pytest.raises(classifier.ClassificationError, match='PROJECTION_FULL_SOURCE_PRIMARY_KEYS_DIFFER'):
        projected_reconcile(value)


def test_real_projected_value_conflict_remains_reviewable_and_blocks_cutover(evolution_bundle):
    value = evolution_bundle; name = 'detection_task'
    key, _ = value.keyed_rows['localA'][name][0]; rows = [(key, 'f' * 64)]
    body = raw({'keySha256': key, 'rowSha256': 'f' * 64}) + b'\n'
    value.projection_packet['tables'][name] = body
    value.projection_receipt['tables'][name].update(fileSha256=sha(body), bytes=len(body), rowsSha256=row_chain(rows))
    value.projection_packet['receipt'] = raw(value.projection_receipt)
    summary = projected_reconcile(value)['summary']
    assert summary['status'] == 'NEEDS_REVIEW' and summary['counts']['ROW_CONFLICT'] == 1
    assert summary['cutoverBlocked'] is True and summary['legacyRowsPresentInSource'] is False


def test_projection_cannot_replace_authenticated_whole_migration_proofs(evolution_bundle):
    value = evolution_bundle
    changed = json.loads(value.projection_packet['proofs']['wholeSummary']); changed['sourceSnapshotSha256'] = 'f' * 64
    value.projection_packet['proofs']['wholeSummary'] = raw(changed)
    value.projection_receipt['proofRawSha256']['wholeSummary'] = sha(raw(changed))
    value.projection_packet['receipt'] = raw(value.projection_receipt)
    with pytest.raises(classifier.ClassificationError, match='WHOLE_REPORT_RAW_DIGEST_DRIFT'):
        projected_reconcile(value)


@pytest.mark.parametrize('change_source', [False, True])
def test_real_collector_uses_locked_complete_old_vectors_and_checks_full_source_twice(evolution_bundle, tmp_path, change_source):
    value = evolution_bundle; source = value.values['sourceManifest']; calls = []; source_calls = []
    output = tmp_path / 'projection'; output.mkdir(mode=0o700)
    class Mysql:
        locked = False
        def admitted_server(self): return {'uuid': value.values['fixtureOwner']['serverUuid']}
        def assert_source_lock(self): assert self.locked
        @contextmanager
        def source_lock(self, schema, tables):
            assert len(tables) == 131; self.locked = True
            try: yield {'kind': 'MYSQL_LOCK_TABLES_READ', 'sourceTableCount': 131}
            finally: self.locked = False
        def row_hashes(self, schema, table, columns, primary, *, keyed_rows_path):
            self.assert_source_lock(); calls.append((table, columns, primary))
            keyed_rows_path.write_bytes(value.projection_packet['tables'][table]); keyed_rows_path.chmod(0o600)
            descriptor = value.projection_receipt['tables'][table]
            return descriptor['rows'], descriptor['rowsSha256']
    mysql = Mysql()
    def snapshot(actual, schema, tables, *, ddl_hash_policy):
        actual.assert_source_lock(); source_calls.append(schema)
        result = {'snapshotSha256': source['snapshotSha256'], 'tables': copy.deepcopy(source['tables'])}
        if change_source and len(source_calls) == 2: result['tables']['table_002']['rows'] += 1
        return result
    runtime = SimpleNamespace(schema_snapshot=snapshot,
        metadata_snapshot=lambda *_: ({}, source['metadataSha256']))
    invoke = lambda: collector.capture(runtime, mysql, {'sourceSchema': value.values['fixtureOwner']['sourceClone']},
        output, value.values, value.context, value.documents, value.projection_packet['proofs'],
        json.loads(value.keyed_documents['source']['index']))
    if change_source:
        with pytest.raises(classifier.ClassificationError, match='FULL_131_SOURCE_CHANGED'): invoke()
    else:
        result = invoke(); assert result['beforeSnapshotSha256'] == result['afterSnapshotSha256']
    assert len(source_calls) == 2 and len(calls) == 2 and not mysql.locked
    for name, columns, primary in calls:
        assert columns == [row['name'] for row in value.values['localA']['snapshot']['tables'][name]['columns']]
        assert len(columns) == classifier.LEGACY_EVOLUTION[name]['oldCount'] and primary == ['id']


def test_collector_reuses_the_exact_existing_whole_migration_connection(evolution_bundle, tmp_path, monkeypatch):
    value = evolution_bundle; work = tmp_path / 'work'; directory = work / 'compact-fixtures'
    directory.mkdir(parents=True, mode=0o700)
    contract_path = tmp_path / 'docs/database/compact-schema-contract.json'
    contract_path.parent.mkdir(parents=True); contract_path.write_bytes(raw(value.values['contract']))
    monkeypatch.setattr(collector, 'ROOT', tmp_path)
    owner = value.values['fixtureOwner']; owner.update(dataDirectory=str(directory / 'mysql-data'), port=33307)
    config = {'version': 1, 'scope': 'ecs-disposable-migration', 'serverUuid': owner['serverUuid'],
        'sourceSchema': owner['sourceClone'], 'targetSchema': 'doorhandle_compact_candidate_0123456789',
        'dataDirectory': owner['dataDirectory'],
        'client': {'kind': 'docker', 'containerId': owner['containerId'], 'executable': '/usr/bin/docker'},
        'connection': {'host': '127.0.0.1', 'port': owner['port'], 'username': 'mig_synthetic', 'password': 'synthetic-only'}}
    def save(path, body):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body); path.chmod(0o600)
    config_path = directory / 'whole-migration.json'; save(config_path, raw(config))
    parent = directory / 'whole-migration-acceptance-0123456789'
    observed = parent / 'observe/source-observation.json'
    save(observed, raw({'kind': 'doorhandle-compact-source-observation', 'status': 'FROZEN_SOURCE_OBSERVED',
        'ecs': value.context['identity'], 'serverUuid': owner['serverUuid'], 'sourceSchema': owner['sourceClone'],
        'sourceTableCount': 131, 'sourceSnapshotSha256': value.values['sourceManifest']['snapshotSha256'],
        'sourceMetadataSha256': value.values['sourceManifest']['metadataSha256'],
        'contractSha256': sha(raw(value.values['contract']))}))
    reviewed = {**config, 'reviewedSourceSnapshot': str(observed), 'reviewedSourceSnapshotSha256': sha(observed.read_bytes())}
    reviewed_path = directory / 'reviewed-whole-migration-0123456789.json'; save(reviewed_path, raw(reviewed))
    proofs = dict(value.projection_packet['proofs']); whole = json.loads(proofs['wholeReceipt'])
    whole.update(configSha256=sha(raw(reviewed)), reviewedSourceObservationSha256=sha(observed.read_bytes()))
    receipt_path = parent / 'migrate/migration-receipt.json'; save(receipt_path, raw(whole)); proofs['wholeReceipt'] = raw(whole)
    supplied = json.loads(proofs['runtimeInput']); supplied.update(migrationReceiptFile=str(receipt_path),
        migrationReceiptSha256=sha(raw(whole)), reviewedConfigFile=str(reviewed_path),
        reviewedConfigSha256=sha(raw(reviewed)), targetSchema=config['targetSchema'])
    proofs['runtimeInput'] = raw(supplied)
    readback = json.loads(proofs['wholeReadback']); readback['migrationReceiptSha256'] = sha(raw(whole)); proofs['wholeReadback'] = raw(readback)
    summary = json.loads(proofs['wholeSummary']); summary['migrationReceiptSha256'] = sha(raw(whole)); proofs['wholeSummary'] = raw(summary)
    verifier = json.loads(proofs['verifier']); verifier['wholeMigrationSummarySha256'] = sha(raw(summary)); proofs['verifier'] = raw(verifier)
    value.values['verification']['reportFiles'] = [
        {'path': path, 'bytes': len(proofs[role]), 'sha256': sha(proofs[role])}
        for role, path in (('verifier', 'reports/receipt.json'), ('wholeSummary', 'reports/migration.json'))]
    runtime = SimpleNamespace(load_config=lambda path: (json.loads(path.read_bytes()), value.context['identity'], sha(path.read_bytes())),
        validate_migration_receipt=lambda path, expected: json.loads(path.read_bytes()))
    admitted, bindings = collector.admitted_clone(runtime, work, value.values, proofs, value.context)
    assert admitted == config and set(bindings) == {config_path, reviewed_path, observed}
    config['connection']['username'] = 'mig_different'; save(config_path, raw(config))
    with pytest.raises(classifier.ClassificationError, match='WHOLE_ACCEPTANCE_CHANGED_SOURCE_CONNECTION'):
        collector.admitted_clone(runtime, work, value.values, proofs, value.context)


@pytest.fixture
def bundle():
    context = {'release': 'ci-96-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64,
        'identity': {'instanceId': classifier.INSTANCE, 'machineId': classifier.MACHINE, 'executionLocation': 'ECS'}}
    verification = {**copy.deepcopy(context), 'schema': 1, 'kind': 'doorhandle-ecs-ci', 'status': 'PASS',
        'scope': 'mysql', 'verificationExitCode': 0, 'finishedAt': '2026-11-08T08:30:00Z',
        'fixtureManifestProvided': True, 'fixtureReadinessValidated': True, 'evidenceOmissions': []}
    local = snapshot(['table_' + str(i).zfill(3) for i in range(45)])
    source = snapshot(['table_' + str(i).zfill(3) for i in range(131)])
    metadata = {name: [] for name in classifier.METADATA_FIELDS}
    metadata['catalog'] = [{'name': name, 'type': 'BASE TABLE', 'engine': 'InnoDB', 'collation': row['collation']}
                           for name, row in local['tables'].items()]
    recovered = []
    for ordinal, cid, uuid in (('a', '1' * 64, '11111111-1111-1111-1111-111111111111'),
                                ('b', '2' * 64, '22222222-2222-2222-2222-222222222222')):
        recovered.append({'snapshot': copy.deepcopy(local), 'containerId': cid, 'serverUuid': uuid,
            'volume': 'fixture-' + ordinal, 'metadata': copy.deepcopy(metadata), 'metadataSha256': sha(raw(metadata)),
            'extraObjects': {'routines': [], 'parameters': [], 'events': []}, 'findings': [],
            'observedCountsMatch': True, 'liveSourceRowHashesVerified': False, 'eventsExecuted': False})
    common = {**copy.deepcopy(context), 'version': 1, 'kind': 'doorhandle-local-mysql-custody',
        'profile': 'local-mysql-export45-v1', 'status': 'SQL_DOUBLE_RESTORED_VERIFIED',
        'verificationReceiptSha256': sha(raw(verification)), 'byteReceiptSha256': 'd' * 64}
    owner = {**copy.deepcopy(common), 'originalContainerId': '3' * 64,
        'servers': [{'ordinal': ordinal, **{key: row[key] for key in ('containerId', 'serverUuid', 'volume')}}
                    for ordinal, row in zip(('a', 'b'), recovered)], 'cleanupEvidence': {'retained-original-controls.json': 'e' * 64}}
    public = {**copy.deepcopy(common), 'tableCount': 45, 'restoredRows': 45,
        'rawSqlSha256': classifier.RAW_SQL_SHA, 'gzipSha256': classifier.GZIP_SHA,
        'snapshotSha256': local['snapshotSha256'], 'metadataSha256': sha(raw(metadata)),
        'allOriginalRowsPreserved': True, 'liveSourceRowHashesVerified': False, 'productionMerged': False,
        'retirementAllowed': False, 'eventsExecuted': False, 'paidModelCalls': 0, 'cleanup': 'STOPPED'}
    fixture_owner = {**copy.deepcopy(context), 'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-owner',
        'phase': 'PREPARED', 'sourceTableCount': 131, 'sourceContainerId': '3' * 64,
        'sourceServerUuid': '33333333-3333-3333-3333-333333333333'}
    manifest = {'schemaVersion': 1, 'kind': 'doorhandle-mysql-private-backup', 'purpose': 'source',
        'schema': source['schema'], 'serverUuid': fixture_owner['sourceServerUuid'], 'tables': source['tables'],
        'createTables': source['createTables'], 'metadataSha256': 'f' * 64, 'triggers': [],
        'data': {'file': 'data.sql', 'bytes': 12000, 'sha256': '0' * 64},
        'migrationContext': {'kind': 'fixture-origin-copy', 'sourceCommit': context['commit'], 'sourceSha256': context['sourceSha256']}}
    targets = ['target_' + str(i).zfill(2) for i in range(29)]
    names = list(source['tables'])
    contract = {'sourceTables': names, 'expectedTargetTables': targets, 'maximumBusinessTables': 30,
        'mapping': [{'target': target, 'sources': [name for j, name in enumerate(names) if j % 29 == i]}
                    for i, target in enumerate(targets)]}
    fixture = SimpleNamespace(context=context, values={'verification': verification, 'localOwner': owner,
        'localPublic': public, 'localA': recovered[0], 'localB': recovered[1], 'fixtureOwner': fixture_owner,
        'sourceManifest': manifest, 'contract': contract})
    update_source(fixture); bind(fixture)
    return fixture


def table_result(report, name='table_000'):
    return next(row for row in report['tableClassifications'] if row['table'] == name)


def test_full_table_snapshot_match_is_classification_without_coverage_or_target_claim(bundle, monkeypatch):
    before = copy.deepcopy(bundle.values)
    def refuse(*_args, **_kw): pytest.fail('Pure JSON classification must not perform file or process I/O')
    monkeypatch.setattr(Path, 'open', refuse)
    report = classify(bundle)
    assert report['counts'] == {'MATCH': 45, 'DIFFERENT': 0, 'NOT_COMPARABLE': 0, 'MISSING': 86}
    assert table_result(report)['reasonCodes'] == ['COMPLETE_TABLE_SNAPSHOT_EQUAL']
    assert table_result(report)['dataDigestEqual'] is True and table_result(report)['contractSource'] is True
    assert report['comparisonScope'] == 'COMPLETE_TABLE_SNAPSHOT_V1' and report['sourceDataBytesRehashed'] is False
    assert report['excludedComparisons'] == ['SCHEMA_WIDE_METADATA', 'TRIGGERS', 'ROUTINES', 'EVENTS', 'PER_KEY_ROWS', 'TARGET29_DATA']
    assert all(report[key] is False for key in ('coverageVerified', 'targetDataCompared', 'productionMerged', 'retirementAllowed'))
    assert bundle.values == before


@pytest.mark.parametrize('field', ['rows', 'rowsSha256', 'autoIncrement', 'collation', 'indexes', 'ddlSha256'])
def test_comparable_full_tables_report_exact_differing_field_without_inclusion_claim(bundle, field):
    source = bundle.values['sourceManifest']; row = source['tables']['table_000']
    if field == 'rows': row[field] += 1
    elif field == 'rowsSha256': row[field] = '9' * 64
    elif field == 'autoIncrement': row[field] = '99'
    elif field == 'collation': row[field] = 'utf8mb4_bin'
    elif field == 'indexes': row[field].append({**row[field][0], 'name': 'secondary'})
    else:
        source['createTables']['table_000'] += ' COMMENT=\'history\''
        row[field] = sha(source['createTables']['table_000'].encode())
    update_source(bundle)
    result = table_result(classify(bundle))
    assert result['status'] == 'DIFFERENT' and result['changedFields'] == [field]
    assert result['dataDigestEqual'] is (field not in ('rows', 'rowsSha256'))


@pytest.mark.parametrize('field', ['type', 'name', 'nullable', 'default', 'charset', 'generation', 'datetimePrecision'])
def test_common_column_values_never_make_incompatible_typed_vectors_comparable(bundle, field):
    row = bundle.values['sourceManifest']['tables']['table_000']
    if field == 'name': row['columns'][1][field] = 'replacement'
    elif field == 'nullable': row['columns'][1][field] = 'NO'
    elif field == 'datetimePrecision': row['columns'][1][field] = 6
    else: row['columns'][1][field] = 'changed'
    update_source(bundle)
    result = table_result(classify(bundle))
    assert result['status'] == 'NOT_COMPARABLE' and result['dataDigestEqual'] is None
    assert result['reasonCodes'] == ['COMPLETE_TYPED_COLUMN_VECTOR_DIFFERS']


def test_primary_key_order_difference_is_not_a_row_digest_difference(bundle):
    bundle.values['sourceManifest']['tables']['table_000']['indexes'][0]['column'] = 'body'
    update_source(bundle)
    result = table_result(classify(bundle))
    assert result['status'] == 'NOT_COMPARABLE' and result['reasonCodes'] == ['ROW_CHAIN_PRIMARY_ORDER_DIFFERS']


def test_missing_table_is_reported_on_each_side_without_guessing_renames(bundle):
    for role in ('localA', 'localB'):
        value = bundle.values[role]['snapshot']
        value['tables']['local_only'] = value['tables'].pop('table_044')
        value['createTables']['local_only'] = value['createTables'].pop('table_044')
        value['snapshotSha256'] = sha(raw({'schemaVersion': 1, 'tables': value['tables']}))
    bundle.values['localPublic']['snapshotSha256'] = bundle.values['localA']['snapshot']['snapshotSha256']
    report = classify(bundle)
    assert table_result(report, 'local_only')['status'] == 'MISSING'
    assert table_result(report, 'local_only')['missingSide'] == 'source131'
    assert not table_result(report, 'local_only')['contractSource']
    assert table_result(report, 'table_044')['missingSide'] == 'local45'
    assert report['counts']['MATCH'] == 44 and report['counts']['MISSING'] == 88


@pytest.mark.parametrize('role', ['verification', 'localOwner', 'fixtureOwner', 'contract'])
def test_changed_external_trust_anchor_is_always_rejected(bundle, role):
    documents, anchors = bind(bundle); documents[role] += b' '
    with pytest.raises(classifier.ClassificationError, match='TRUST_ANCHOR_DIGEST_DRIFT'):
        classifier.classify_documents(documents, expected_context=bundle.context, anchors=anchors)


@pytest.mark.parametrize('role', ['verification', 'localOwner', 'localPublic', 'fixtureOwner'])
@pytest.mark.parametrize('field', ['release', 'commit', 'sourceSha256', 'identity'])
def test_resealed_cross_machine_or_cross_build_claims_still_fail(bundle, role, field):
    value = bundle.values[role]
    value[field] = {**value[field], 'machineId': '9' * 32} if field == 'identity' else 'wrong-build'
    with pytest.raises(classifier.ClassificationError, match='CROSS_BUILD_OR_MACHINE'):
        classify(bundle)


@pytest.mark.parametrize('damage', ['not-pass', 'source-scope', 'unfinished', 'omission', 'not-ready', 'wrong-kind', 'boolean-exit'])
def test_actual_mysql_pass_is_mandatory_even_with_valid_control_hashes(bundle, damage):
    value = bundle.values['verification']
    if damage == 'not-pass': value['status'] = 'FAILED'
    elif damage == 'source-scope': value['scope'] = 'source'
    elif damage == 'unfinished': value['finishedAt'] = None
    elif damage == 'omission': value['evidenceOmissions'] = ['uncollected']
    elif damage == 'not-ready': value['fixtureReadinessValidated'] = False
    elif damage == 'wrong-kind': value['kind'] = 'other'
    else: value['verificationExitCode'] = False
    with pytest.raises(classifier.ClassificationError, match='ACTUAL_SAME_BUILD_MYSQL_PASS'):
        classify(bundle)


@pytest.mark.parametrize('damage', ['same-container', 'same-uuid', 'same-volume', 'unobserved-counts',
                                  'different-rows', 'different-metadata', 'different-extra-objects', 'live-claim'])
def test_fabricated_or_nonindependent_local_recovery_never_becomes_classifiable(bundle, damage):
    first, second = bundle.values['localA'], bundle.values['localB']
    names = {'same-container': 'containerId', 'same-uuid': 'serverUuid', 'same-volume': 'volume'}
    if damage in names:
        key = names[damage]; second[key] = first[key]; bundle.values['localOwner']['servers'][1][key] = first[key]
    elif damage == 'unobserved-counts': first['observedCountsMatch'] = False
    elif damage == 'different-rows':
        second['snapshot']['tables']['table_000']['rowsSha256'] = '9' * 64
        second['snapshot']['snapshotSha256'] = sha(raw({'schemaVersion': 1, 'tables': second['snapshot']['tables']}))
    elif damage == 'different-metadata':
        second['metadata']['checks'] = [{'opaque': 'different'}]; second['metadataSha256'] = sha(raw(second['metadata']))
    elif damage == 'different-extra-objects': second['extraObjects']['events'] = [{'name': 'other'}]
    else: first['liveSourceRowHashesVerified'] = True
    with pytest.raises(classifier.ClassificationError): classify(bundle)


@pytest.mark.parametrize('damage', ['wrong-source-container', 'wrong-server', 'migration-backup', 'wrong-origin-kind',
                                  'wrong-origin-commit', 'wrong-origin-sha', 'wrong-phase', 'target-purpose',
                                  'table-count', 'snapshot-sha', 'metadata-sha', 'data-path', 'boolean-rows'])
def test_source_must_be_the_complete_same_build_fixture_origin_copy(bundle, damage):
    owner, manifest = bundle.values['fixtureOwner'], bundle.values['sourceManifest']
    if damage == 'wrong-source-container': owner['sourceContainerId'] = '8' * 64
    elif damage == 'wrong-server': manifest['serverUuid'] = '88888888-8888-8888-8888-888888888888'
    elif damage == 'migration-backup': manifest['migrationContext'] = {'attempt': 'e' * 32}
    elif damage == 'wrong-origin-kind': manifest['migrationContext']['kind'] = 'migration'
    elif damage == 'wrong-origin-commit': manifest['migrationContext']['sourceCommit'] = '8' * 40
    elif damage == 'wrong-origin-sha': manifest['migrationContext']['sourceSha256'] = '8' * 64
    elif damage == 'wrong-phase': owner['phase'] = 'PREPARING'
    elif damage == 'target-purpose': manifest['purpose'] = 'target'
    elif damage == 'table-count': owner['sourceTableCount'] = 130
    elif damage == 'snapshot-sha': manifest['snapshotSha256'] = '8' * 64
    elif damage == 'metadata-sha': manifest['metadataSha256'] = 'not-a-sha'
    elif damage == 'data-path': manifest['data']['file'] = '../other.sql'
    else: manifest['tables']['table_000']['rows'] = True
    with pytest.raises(classifier.ClassificationError): classify(bundle)


@pytest.mark.parametrize('damage', ['source-count', 'source-name', 'target-count', 'duplicate-target', 'unmapped-source', 'new-source'])
def test_contract_projection_is_exact_and_cannot_redefine_the_131_to_29_relationship(bundle, damage):
    value = bundle.values['contract']
    if damage == 'source-count': value['sourceTables'].pop()
    elif damage == 'source-name': value['sourceTables'][0] = 'other_table'
    elif damage == 'target-count': value['expectedTargetTables'].pop()
    elif damage == 'duplicate-target': value['mapping'][1]['target'] = value['mapping'][0]['target']
    elif damage == 'unmapped-source': value['mapping'][0]['sources'].pop()
    else: value['mapping'][0]['sources'].append('not_in_source')
    with pytest.raises(classifier.ClassificationError): classify(bundle)


@pytest.mark.parametrize('role', ['localA', 'localB', 'sourceManifest'])
def test_raw_full_snapshot_changes_cannot_hide_behind_unchanged_parent_digests(bundle, role):
    documents, anchors = bind(bundle); documents[role] += b' '
    with pytest.raises(classifier.ClassificationError):
        classifier.classify_documents(documents, expected_context=bundle.context, anchors=anchors)


@pytest.mark.parametrize('damage', ['bad-row-sha', 'ddl-sha', 'missing-field', 'extra-field', 'boolean-version',
                                  'missing-table', 'duplicate-ordinal', 'expression-primary', 'schema-version'])
def test_incomplete_or_unknown_table_encoding_is_rejected_instead_of_soft_classified(bundle, damage):
    value = bundle.values['sourceManifest']; table = value['tables']['table_000']
    if damage == 'bad-row-sha': table['rowsSha256'] = 'not-typed-row-sha'
    elif damage == 'ddl-sha': table['ddlSha256'] = '9' * 64
    elif damage == 'missing-field': table.pop('columns')
    elif damage == 'extra-field': table['commonColumnsOnly'] = True
    elif damage == 'boolean-version': value['schemaVersion'] = True
    elif damage == 'missing-table': value['tables'].pop('table_130')
    elif damage == 'duplicate-ordinal': table['columns'][1]['ordinal'] = 1
    elif damage == 'expression-primary': table['indexes'][0]['column'] = None
    else: value['schemaVersion'] = 2
    with pytest.raises(classifier.ClassificationError): classify(bundle)


@pytest.mark.parametrize('payload', [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'[]', b'\xff', b'{'])
def test_control_json_is_strictly_bounded_unique_finite_and_an_object(payload):
    with pytest.raises(classifier.ClassificationError): classifier.decode(payload)


def test_missing_required_proof_is_refused_and_never_reported_as_a_missing_business_table(bundle):
    documents, anchors = bind(bundle); documents.pop('localA')
    with pytest.raises(classifier.ClassificationError, match='COMPLETE_EVIDENCE_BUNDLE'):
        classifier.classify_documents(documents, expected_context=bundle.context, anchors=anchors)


def test_schema_name_normalization_keeps_sql_literal_bytes_distinct():
    sql = "CREATE TABLE `doorhandledb`.`x` (`v` varchar(80) DEFAULT 'doorhandledb.x')"
    assert classifier.normalize_ddl(sql, 'doorhandledb') == "CREATE TABLE `$SELF`.`x` (`v` varchar(80) DEFAULT 'doorhandledb.x')"
