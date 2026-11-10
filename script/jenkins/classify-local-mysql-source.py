"""Read-only JSON classification of one build's recovered 45/source 131 tables.

Expected input digests are trust anchors supplied by an authenticated CI caller;
this module does not authenticate offline claims, connect to a database, read
SQL data, or confer merge, coverage, retirement or deployment authority.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys


_DDL_HELPER_PATH = Path(__file__).resolve().parents[1] / 'schema/compact_ddl_policy.py'
_DDL_SPEC = importlib.util.spec_from_file_location('fixed_source_snapshot_ddl_policy', _DDL_HELPER_PATH)
_DDL_POLICY = importlib.util.module_from_spec(_DDL_SPEC)
_DDL_SPEC.loader.exec_module(_DDL_POLICY)


MAX_JSON = 16 * 1024 ** 2
SHA = re.compile(r'[a-f0-9]{64}')
UUID = re.compile(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}')
IDENT = re.compile(r'[a-z][a-z0-9_]{0,63}')
TAG = re.compile(r'ci-[1-9][0-9]*-[a-f0-9]{12}')
INSTANCE = 'i-2zeieuov2aum486jm1ek'
MACHINE = '1ebe8f77e3104ab6a49a9386e38abd20'
RAW_SQL_SHA = '6b8bce0cc4da19384d9fc4ce894946c34b9b285dd2e9a150f1211967999e2464'
GZIP_SHA = '8f0a2e9014233dc20f4e26321eb855846bda0ddb689c39d85db33133e447b627'
ROLES = ('verification', 'localOwner', 'localPublic', 'localA', 'localB', 'fixtureOwner', 'sourceManifest', 'contract')
ANCHORS = ('verification', 'localOwner', 'fixtureOwner', 'contract')
TABLE_FIELDS = {'rows', 'rowsSha256', 'autoIncrement', 'columns', 'indexes', 'collation', 'ddlSha256'}
COLUMN_FIELDS = {'name', 'ordinal', 'type', 'nullable', 'default', 'extra', 'generation', 'charset', 'collation', 'datetimePrecision'}
INDEX_FIELDS = {'name', 'ordinal', 'column', 'expression', 'nonUnique', 'subPart', 'collation', 'type', 'visible'}
METADATA_FIELDS = {'catalog', 'columns', 'indexes', 'checks', 'foreignKeys', 'triggers'}
CONTEXT_FIELDS = {'release', 'commit', 'sourceSha256', 'identity'}
KEYED_ROLES = ('localA', 'localB', 'source')
KEYED_FIELDS = {'status', 'rows', 'rowsSha256', 'columnsSha256', 'primary', 'file', 'fileSha256', 'bytes', 'entries'}
KEYED_LINE = re.compile(rb'\{"keySha256":"([a-f0-9]{64})","rowSha256":"([a-f0-9]{64})"\}\n')
MAX_KEYED_ROWS = 50_000
MAX_KEYED_TOTAL_ROWS = 250_000
MAX_KEYED_BUNDLE_BYTES = 64 * 1024 ** 2
# Audited old45/#107 and source131/#188 complete ordered vectors. These pins
# include every COLUMN_FIELDS attribute (including defaults), not a name-only
# intersection. The source change is exactly 14 + 5 appended columns.
LEGACY_EVOLUTION_EVIDENCE_SHA256 = '5fedf7fd1e1d95a0533d5ee201aad2e2a7489f5950d56519137e4494ffb94e0f'
LEGACY_EVOLUTION = {
    'detection_task': {'oldCount': 63, 'sourceCount': 77,
        'oldSha256': '736e20cae98ab7265393a078b4e1ed6cd4466c1a2077b2827a4797dd9e3968fa',
        'sourceSha256': '47a0409adb23f08b02ac051e197b36ee14578037e9781e5f5e27f86c5f352ec1'},
    'model_management': {'oldCount': 27, 'sourceCount': 32,
        'oldSha256': '13eb82f86a3439e627d7fe0c6fe9bf6c6b8ee28ab25401c980a92c2cefef49da',
        'sourceSha256': 'e0de60e1e803d8d990f75dcdf176ad7f1540166a8b3776d3edd4e3083332e02a'}}
PROJECTION_PROOFS = ('cloneComparison', 'runtimeInput', 'wholeReceipt', 'wholeReadback', 'wholeSummary', 'verifier')


class ClassificationError(ValueError):
    pass


def need(value, code):
    if not value:
        raise ClassificationError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def sha_json(value):
    return digest(canonical(value))


def hash_field(value):
    return isinstance(value, str) and SHA.fullmatch(value)


def decode(raw):
    need(type(raw) is bytes and 0 < len(raw) <= MAX_JSON, 'BOUNDED_JSON_BYTES_REQUIRED')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'DUPLICATE_JSON_KEY'); result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique,
            parse_constant=lambda _: need(False, 'NONFINITE_JSON_VALUE'))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ClassificationError('INVALID_JSON_INPUT') from None
    need(type(value) is dict, 'JSON_OBJECT_REQUIRED')
    return value


def normalize_ddl(sql, schema):
    # Same schema_snapshot v1 normalization, preserving SQL string literals.
    strings = []
    def save(match):
        strings.append(match.group(0)); return '\x01' + str(len(strings) - 1) + '\x02'
    masked = re.sub(r"'(?:''|\\.|[^'\\])*'|\"(?:\"\"|\\.|[^\"\\])*\"", save, sql)
    masked = re.sub(r'`' + re.escape(schema) + r'`\s*\.', '`$SELF`.', masked)
    return re.sub(r'\x01(\d+)\x02', lambda match: strings[int(match.group(1))], masked)


def validate_context(context):
    need(type(context) is dict and set(context) == CONTEXT_FIELDS, 'EXACT_EXPECTED_CONTEXT_REQUIRED')
    identity = context['identity']
    need(type(identity) is dict and identity == {'instanceId': INSTANCE, 'machineId': MACHINE, 'executionLocation': 'ECS'},
         'FIXED_ECS_IDENTITY_REQUIRED')
    need(isinstance(context['release'], str) and TAG.fullmatch(context['release'])
         and isinstance(context['commit'], str) and re.fullmatch(r'[a-f0-9]{40}', context['commit'])
         and context['release'].endswith('-' + context['commit'][:12]) and hash_field(context['sourceSha256']),
         'FIXED_BUILD_CONTEXT_REQUIRED')


def same_context(value, context):
    need(all(value.get(key) == expected for key, expected in context.items()), 'CROSS_BUILD_OR_MACHINE_EVIDENCE')


def snapshot_policy(value):
    if 'ddlHashPolicy' not in value:
        return None
    policy = value['ddlHashPolicy']
    need(policy in (_DDL_POLICY.RAW_POLICY, _DDL_POLICY.CANONICAL_POLICY), 'UNKNOWN_SNAPSHOT_DDL_HASH_POLICY')
    return policy


def validate_tables(tables, create_tables, schema, expected_count, *, ddl_hash_policy=None):
    need(ddl_hash_policy is None or ddl_hash_policy in (_DDL_POLICY.RAW_POLICY, _DDL_POLICY.CANONICAL_POLICY),
         'UNKNOWN_SNAPSHOT_DDL_HASH_POLICY')
    need(type(tables) is dict and len(tables) == expected_count and type(create_tables) is dict
         and set(create_tables) == set(tables) and isinstance(schema, str) and IDENT.fullmatch(schema),
         'COMPLETE_TABLE_SNAPSHOT_REQUIRED')
    for name, row in tables.items():
        need(isinstance(name, str) and IDENT.fullmatch(name) and type(row) is dict and set(row) == TABLE_FIELDS,
             'TABLE_SNAPSHOT_V1_FIELDS_REQUIRED')
        need(type(row['rows']) is int and 0 <= row['rows'] < 2 ** 64 and hash_field(row['rowsSha256'])
             and hash_field(row['ddlSha256']) and isinstance(row['collation'], str) and row['collation'],
             'TABLE_ROW_OR_METADATA_DIGEST_REQUIRED')
        need(row['autoIncrement'] is None or isinstance(row['autoIncrement'], str)
             and re.fullmatch(r'[0-9]{1,20}', row['autoIncrement']), 'EXACT_HIGH_WATER_MARK_REQUIRED')
        columns, indexes = row['columns'], row['indexes']
        need(type(columns) is list and 0 < len(columns) <= 1024 and type(indexes) is list and len(indexes) <= 4096,
             'COMPLETE_COLUMNS_AND_INDEXES_REQUIRED')
        names = []
        for ordinal, column in enumerate(columns, 1):
            need(type(column) is dict and set(column) == COLUMN_FIELDS and type(column['ordinal']) is int
                 and column['ordinal'] == ordinal and isinstance(column['name'], str)
                 and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]{0,63}', column['name'])
                 and isinstance(column['type'], str) and column['type'] and column['nullable'] in ('YES', 'NO'),
                 'COMPLETE_TYPED_COLUMN_VECTOR_REQUIRED')
            names.append(column['name'])
        need(len(names) == len(set(names)), 'DUPLICATE_COLUMN_NAME')
        for index in indexes:
            need(type(index) is dict and set(index) == INDEX_FIELDS and isinstance(index['name'], str)
                 and type(index['ordinal']) is int and index['ordinal'] > 0
                 and (index['column'] is None or index['column'] in names), 'COMPLETE_INDEX_VECTOR_REQUIRED')
        primary = [item for item in indexes if item['name'] == 'PRIMARY']
        need(all(item['column'] is not None for item in primary)
             and [item['ordinal'] for item in primary] == list(range(1, len(primary) + 1)),
             'EXPLICIT_PRIMARY_ORDER_REQUIRED')
        ddl = create_tables[name]
        need(isinstance(ddl, str) and 0 < len(ddl.encode('utf8')) <= MAX_JSON, 'COMPLETE_CREATE_TABLE_REQUIRED')
        try:
            normalized_ddl = _DDL_POLICY.normalize_ddl(ddl, schema, columns,
                policy=ddl_hash_policy or _DDL_POLICY.RAW_POLICY)
        except ValueError:
            raise ClassificationError('DDL_CANONICALIZATION_NOT_PROVEN_BY_COLUMNS') from None
        need(digest(normalized_ddl.encode('utf8')) == row['ddlSha256'], 'CREATE_TABLE_DIGEST_DRIFT')
    payload = {'schemaVersion': 1, 'tables': tables}
    if ddl_hash_policy is not None:
        payload['ddlHashPolicy'] = ddl_hash_policy
    return sha_json(payload)


def validate_snapshot(value, expected_count):
    base_fields = {'schema', 'schemaVersion', 'snapshotSha256', 'tables', 'createTables'}
    need(type(value) is dict and set(value) in (base_fields, base_fields | {'ddlHashPolicy'})
         and type(value['schemaVersion']) is int and value['schemaVersion'] == 1, 'SUPPORTED_COMPLETE_SNAPSHOT_REQUIRED')
    checksum = validate_tables(value['tables'], value['createTables'], value['schema'], expected_count,
                               ddl_hash_policy=snapshot_policy(value))
    need(value['snapshotSha256'] == checksum, 'SNAPSHOT_PAYLOAD_DIGEST_DRIFT')
    return checksum


def classify_documents(raw_documents, *, expected_context, anchors):
    """Pure bytes/JSON validation and classification; no I/O or external helpers."""
    validate_context(expected_context)
    need(type(raw_documents) is dict and set(raw_documents) == set(ROLES), 'COMPLETE_EVIDENCE_BUNDLE_REQUIRED')
    need(type(anchors) is dict and set(anchors) == set(ANCHORS)
         and all(hash_field(value) for value in anchors.values()), 'EXTERNAL_TRUSTED_DIGEST_ANCHORS_REQUIRED')
    hashes = {key: digest(raw) for key, raw in raw_documents.items() if type(raw) is bytes}
    need(len(hashes) == len(ROLES) and all(hashes[key] == value for key, value in anchors.items()), 'TRUST_ANCHOR_DIGEST_DRIFT')
    docs = {key: decode(raw) for key, raw in raw_documents.items()}
    verification, owner, public, fixture, manifest, contract = (docs[key] for key in
        ('verification', 'localOwner', 'localPublic', 'fixtureOwner', 'sourceManifest', 'contract'))
    for value in (verification, owner, public, fixture): same_context(value, expected_context)
    need(type(verification.get('schema')) is int and verification['schema'] == 1
         and verification.get('kind') == 'doorhandle-ecs-ci' and verification.get('status') == 'PASS'
         and type(verification.get('verificationExitCode')) is int and verification['verificationExitCode'] == 0
         and verification.get('scope') == 'mysql' and verification.get('finishedAt')
         and verification.get('fixtureManifestProvided') is True and verification.get('fixtureReadinessValidated') is True
         and not verification.get('evidenceOmissions'), 'ACTUAL_SAME_BUILD_MYSQL_PASS_REQUIRED')
    for value in (owner, public):
        need(type(value.get('version')) is int and value['version'] == 1 and value.get('kind') == 'doorhandle-local-mysql-custody'
             and value.get('profile') == 'local-mysql-export45-v1' and value.get('status') == 'SQL_DOUBLE_RESTORED_VERIFIED'
             and value.get('verificationReceiptSha256') == hashes['verification'], 'ACTUAL_LOCAL_DOUBLE_RECOVERY_REQUIRED')
    catalogue = owner.get('cleanupEvidence')
    need(type(catalogue) is dict and all(isinstance(key, str) and hash_field(value) for key, value in catalogue.items())
         and public.get('logicalEvidenceCatalogueSha256') == sha_json(catalogue)
         and owner.get('publicRecoverySha256') == hashes['localPublic'], 'LOCAL_LOGICAL_EVIDENCE_CHAIN_DRIFT')
    for key, member in (('localA', 'local-mysql-recovery/a/full-recovery-private.json'),
                        ('localB', 'local-mysql-recovery/b/full-recovery-private.json')):
        need(catalogue.get(member) == hashes[key], 'LOCAL_FULL_SNAPSHOT_RAW_DIGEST_DRIFT')
    need(public.get('rawSqlSha256') == RAW_SQL_SHA and public.get('gzipSha256') == GZIP_SHA
         and public.get('allOriginalRowsPreserved') is True and public.get('liveSourceRowHashesVerified') is False
         and public.get('productionMerged') is False and public.get('retirementAllowed') is False
         and public.get('eventsExecuted') is False and type(public.get('paidModelCalls')) is int and public['paidModelCalls'] == 0
         and public.get('cleanup') == 'STOPPED' and hash_field(public.get('byteReceiptSha256'))
         and public['byteReceiptSha256'] == owner.get('byteReceiptSha256'), 'FIXED_LOCAL_EXPORT_PROVENANCE_REQUIRED')
    first, second = docs['localA'], docs['localB']
    for row in (first, second):
        validate_snapshot(row.get('snapshot'), 45)
        need(row.get('observedCountsMatch') is True and row.get('liveSourceRowHashesVerified') is False
             and row.get('eventsExecuted') is False and type(row.get('metadata')) is dict
             and set(row['metadata']) == METADATA_FIELDS
             and all(type(value) is list for value in row['metadata'].values())
             and row.get('metadataSha256') == sha_json(row['metadata']) and type(row.get('extraObjects')) is dict
             and set(row['extraObjects']) == {'routines', 'parameters', 'events'} and type(row.get('findings')) is list,
             'COMPLETE_LOCAL_LOGICAL_RECOVERY_REQUIRED')
    need(all(first.get(key) == second.get(key) for key in ('snapshot', 'metadata', 'metadataSha256', 'extraObjects', 'findings')),
         'INDEPENDENT_LOCAL_RECOVERIES_DIFFER')
    servers = owner.get('servers')
    need(type(servers) is list and len(servers) == 2 and {node.get('ordinal') for node in servers} == {'a', 'b'},
         'TWO_INDEPENDENT_RECOVERY_SERVERS_REQUIRED')
    for ordinal, row in zip(('a', 'b'), (first, second)):
        node = next(node for node in servers if node['ordinal'] == ordinal)
        need(all(row.get(key) == node.get(key) for key in ('containerId', 'serverUuid', 'volume'))
             and isinstance(row.get('containerId'), str) and SHA.fullmatch(row['containerId'])
             and isinstance(row.get('serverUuid'), str) and UUID.fullmatch(row['serverUuid'])
             and isinstance(row.get('volume'), str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,254}', row['volume']),
             'RECOVERY_SERVER_OWNER_BINDING_DRIFT')
    need(all(first[key] != second[key] for key in ('containerId', 'serverUuid', 'volume')), 'RECOVERY_SERVERS_NOT_INDEPENDENT')
    local_snapshot = first['snapshot']
    need(public.get('snapshotSha256') == local_snapshot['snapshotSha256'] and public.get('metadataSha256') == first['metadataSha256']
         and type(public.get('tableCount')) is int and public['tableCount'] == 45
         and type(public.get('restoredRows')) is int
         and public['restoredRows'] == sum(row['rows'] for row in local_snapshot['tables'].values()), 'LOCAL_PUBLIC_SUMMARY_DRIFT')
    need(type(fixture.get('schemaVersion')) is int and fixture['schemaVersion'] == 1
         and fixture.get('kind') == 'doorhandle-compact-fixture-owner'
         and fixture.get('phase') in ('PREPARED', 'OWNED_SERVER_STOPPED') and fixture.get('sourceTableCount') == 131
         and type(fixture['sourceTableCount']) is int and fixture.get('sourceBackupSha256') == hashes['sourceManifest'],
         'ACTUAL_SAME_BUILD_FIXTURE_SOURCE_REQUIRED')
    original = fixture.get('sourceContainerId')
    need(isinstance(original, str) and SHA.fullmatch(original) and owner.get('originalContainerId') == original
         and all(row['containerId'] != original for row in (first, second)), 'ORIGINAL_CONTAINER_PROVENANCE_DRIFT')
    need(type(manifest.get('schemaVersion')) is int and manifest['schemaVersion'] == 1
         and manifest.get('kind') == 'doorhandle-mysql-private-backup' and manifest.get('purpose') == 'source'
         and manifest.get('serverUuid') == fixture.get('sourceServerUuid')
         and isinstance(manifest.get('serverUuid'), str) and UUID.fullmatch(manifest['serverUuid'])
         and manifest.get('migrationContext') == {'kind': 'fixture-origin-copy', 'sourceCommit': expected_context['commit'],
                                                 'sourceSha256': expected_context['sourceSha256']},
         'FIXTURE_ORIGIN_COPY_PROVENANCE_DRIFT')
    source_sha = validate_tables(manifest.get('tables'), manifest.get('createTables'), manifest.get('schema'), 131,
                                 ddl_hash_policy=snapshot_policy(manifest))
    need(manifest.get('snapshotSha256') == fixture.get('sourceSnapshotSha256') == source_sha
         and type(fixture.get('sourceRows')) is int and fixture['sourceRows'] == sum(row['rows'] for row in manifest['tables'].values())
         and hash_field(manifest.get('metadataSha256')) and type(manifest.get('triggers')) is list,
         'FIXTURE_SOURCE_SNAPSHOT_DIGEST_DRIFT')
    data = manifest.get('data')
    need(type(data) is dict and set(data) == {'file', 'sha256', 'bytes'} and data['file'] == 'data.sql'
         and hash_field(data['sha256']) and type(data['bytes']) is int and 0 < data['bytes'] <= 4 * 1024 ** 3,
         'DECLARED_SOURCE_BACKUP_DATA_BINDING_REQUIRED')
    need(manifest['schema'] == local_snapshot['schema'] == 'doorhandledb', 'SAME_LOGICAL_SOURCE_SCHEMA_REQUIRED')
    source_names, targets, mapping = contract.get('sourceTables'), contract.get('expectedTargetTables'), contract.get('mapping')
    need(type(source_names) is list and len(source_names) == len(set(source_names)) == 131
         and set(source_names) == set(manifest['tables']) and type(targets) is list and len(targets) == len(set(targets)) == 29
         and contract.get('maximumBusinessTables') == 30 and type(mapping) is list and len(mapping) == 29,
         'FIXED_131_TO_29_CONTRACT_REQUIRED')
    target_by_source = {name: [] for name in source_names}; mapped_targets = set()
    for row in mapping:
        need(type(row) is dict and row.get('target') in targets and row['target'] not in mapped_targets
             and type(row.get('sources')) is list and row['sources'] and len(row['sources']) == len(set(row['sources']))
             and set(row['sources']) <= set(source_names), 'COMPLETE_CONTRACT_MAPPING_REQUIRED')
        mapped_targets.add(row['target'])
        for name in row['sources']: target_by_source[name].append(row['target'])
    need(all(target_by_source.values()), 'UNMAPPED_CONTRACT_SOURCE')
    classifications = []
    for name in sorted(set(local_snapshot['tables']) | set(manifest['tables'])):
        local, source = local_snapshot['tables'].get(name), manifest['tables'].get(name)
        changed = []; missing = None; equal_data = equal_metadata = None
        if local is None or source is None:
            state = 'MISSING'; missing = 'local45' if local is None else 'source131'
            reasons = ['TABLE_ABSENT_FROM_' + missing.upper()]
        else:
            changed = sorted(key for key in TABLE_FIELDS if local[key] != source[key])
            equal_metadata = not any(key in changed for key in TABLE_FIELDS - {'rows', 'rowsSha256'})
            primary = lambda row: [item['column'] for item in row['indexes'] if item['name'] == 'PRIMARY']
            if local['columns'] != source['columns'] or primary(local) != primary(source):
                state = 'NOT_COMPARABLE'; reasons = []
                if local['columns'] != source['columns']: reasons.append('COMPLETE_TYPED_COLUMN_VECTOR_DIFFERS')
                if primary(local) != primary(source): reasons.append('ROW_CHAIN_PRIMARY_ORDER_DIFFERS')
            else:
                equal_data = (local['rows'], local['rowsSha256']) == (source['rows'], source['rowsSha256'])
                state = 'DIFFERENT' if changed else 'MATCH'
                reasons = ['COMPLETE_TABLE_SNAPSHOT_EQUAL'] if not changed else ['TABLE_FIELD_DIFFERS:' + key for key in changed]
        classifications.append({'table': name, 'status': state, 'missingSide': missing, 'reasonCodes': reasons,
            'localRows': local['rows'] if local else None, 'sourceRows': source['rows'] if source else None,
            'dataDigestEqual': equal_data, 'tableMetadataEqual': equal_metadata,
            'changedFields': changed, 'contractSource': name in target_by_source,
            'targetTables': sorted(target_by_source.get(name, []))})
    return {'schemaVersion': 1, 'kind': 'doorhandle-local-mysql-source-classification', 'status': 'CLASSIFIED',
        'context': expected_context, 'inputRawSha256': hashes,
        'localSnapshotSha256': local_snapshot['snapshotSha256'], 'sourceSnapshotSha256': source_sha,
        'comparisonScope': 'COMPLETE_TABLE_SNAPSHOT_V1',
        'excludedComparisons': ['SCHEMA_WIDE_METADATA', 'TRIGGERS', 'ROUTINES', 'EVENTS', 'PER_KEY_ROWS', 'TARGET29_DATA'],
        'counts': {state: sum(row['status'] == state for row in classifications)
                   for state in ('MATCH', 'DIFFERENT', 'NOT_COMPARABLE', 'MISSING')},
        'localTableCount': 45, 'sourceTableCount': 131, 'tableClassifications': classifications,
        'declaredSourceDataSha256': data['sha256'], 'sourceDataBytesRehashed': False,
        'trustAnchorAuthentication': 'REQUIRED_FROM_CALLER', 'contractProjectionOnly': True,
        'coverageVerified': False, 'targetDataCompared': False, 'productionMerged': False, 'retirementAllowed': False,
        'perKeyReconciliation': {'status': 'NOT_COLLECTED', 'scope': 'EXACT_TYPED_PRIMARY_KEYS_V1',
            'gateScope': 'PER_KEY_SOURCE_INCLUSION_ONLY', 'wholeMigrationAndRuntimeAcceptanceStillRequired': True,
            'requiredBeforeCutover': True, 'cutoverBlocked': True, 'legacyRowsPresentInSource': False,
            'reasonCodes': ['TRUSTED_PER_KEY_EVIDENCE_NOT_COLLECTED'], 'targetDataCompared': False}}


def primary_columns(table):
    primary = sorted((item for item in table['indexes'] if item['name'] == 'PRIMARY'), key=lambda item: item['ordinal'])
    need([item['ordinal'] for item in primary] == list(range(1, len(primary) + 1))
         and all(isinstance(item['column'], str) for item in primary)
         and len({item['column'] for item in primary}) == len(primary), 'COMPLETE_UNIQUE_PRIMARY_ORDER_REQUIRED')
    return [item['column'] for item in primary]


def keyed_references(docs):
    return {'localA': docs['localA'].get('keyedRowsIndex'), 'localB': docs['localB'].get('keyedRowsIndex'),
            'source': docs['fixtureOwner'].get('sourceKeyedRowsIndex')}


def validate_keyed_index(raw, reference, snapshot, *, role):
    need(type(raw) is bytes and type(reference) is dict and set(reference) == {'file', 'sha256', 'bytes'}
         and reference['file'] == ('source-keyed-rows/index.json' if role == 'source' else 'keyed-rows/index.json')
         and type(reference['bytes']) is int and reference['bytes'] == len(raw)
         and hash_field(reference['sha256']) and digest(raw) == reference['sha256'], 'TRUSTED_KEYED_INDEX_BINDING_DRIFT')
    index = decode(raw)
    need(set(index) == {'schemaVersion', 'kind', 'schema', 'snapshotSha256', 'tables'}
         and type(index['schemaVersion']) is int and index['schemaVersion'] == 1
         and index['kind'] == 'doorhandle-mysql-keyed-row-index' and index['schema'] == snapshot['schema']
         and index['snapshotSha256'] == snapshot['snapshotSha256'] and type(index['tables']) is dict
         and set(index['tables']) == set(snapshot['tables']), 'COMPLETE_KEYED_INDEX_SNAPSHOT_REQUIRED')
    total_rows = total_bytes = 0
    for name, item in index['tables'].items():
        expected = snapshot['tables'][name]; primary = primary_columns(expected)
        need(type(item) is dict and set(item) == KEYED_FIELDS and type(item['rows']) is int
             and item['rows'] == expected['rows'] and item['rowsSha256'] == expected['rowsSha256']
             and item['columnsSha256'] == sha_json(expected['columns']) and item['primary'] == primary,
             'KEYED_TABLE_TYPED_SNAPSHOT_DRIFT')
        if primary:
            need(item['status'] == 'KEYED' and item['file'] == name + '.jsonl' and hash_field(item['fileSha256'])
                 and type(item['entries']) is int and item['entries'] == item['rows'] <= MAX_KEYED_ROWS
                 and type(item['bytes']) is int and 0 <= item['bytes'] <= MAX_JSON,
                 'BOUNDED_COMPLETE_KEYED_TABLE_REQUIRED')
            total_rows += item['entries']; total_bytes += item['bytes']
        else:
            need(item['status'] == 'NO_PRIMARY_KEY' and item['file'] is None and item['fileSha256'] is None
                 and type(item['entries']) is int and item['entries'] == 0
                 and type(item['bytes']) is int and item['bytes'] == 0, 'UNKEYED_TABLE_CANNOT_CLAIM_KEY_COVERAGE')
    need(total_rows <= MAX_KEYED_TOTAL_ROWS and total_bytes <= MAX_KEYED_BUNDLE_BYTES, 'KEYED_SCHEMA_BUDGET_EXCEEDED')
    return index


def validate_keyed_rows(raw, descriptor):
    need(type(raw) is bytes and len(raw) == descriptor['bytes'] and digest(raw) == descriptor['fileSha256'],
         'KEYED_ROWS_FILE_DIGEST_DRIFT')
    rows = {}; chain = hashlib.sha256(b'compact-row-hash-chain-v1\n')
    for line in raw.splitlines(keepends=True):
        match = KEYED_LINE.fullmatch(line)
        need(match is not None, 'CANONICAL_KEYED_HASH_ROW_REQUIRED')
        key, row = (part.decode('ascii') for part in match.groups())
        need(key not in rows, 'DUPLICATE_PRIMARY_KEY_DIGEST')
        rows[key] = row; chain.update(bytes.fromhex(row))
        need(len(rows) <= MAX_KEYED_ROWS, 'KEYED_TABLE_ROW_LIMIT_EXCEEDED')
    need(len(rows) == descriptor['entries'] == descriptor['rows'] and chain.hexdigest() == descriptor['rowsSha256'],
         'KEYED_FULL_ROW_CHAIN_DRIFT')
    return rows


def approved_legacy_projection(name, local, source):
    rule = LEGACY_EVOLUTION.get(name)
    return bool(rule and len(local['columns']) == rule['oldCount']
        and len(source['columns']) == rule['sourceCount']
        and sha_json(local['columns']) == rule['oldSha256']
        and sha_json(source['columns']) == rule['sourceSha256']
        and source['columns'][:rule['oldCount']] == local['columns']
        and primary_columns(local) == primary_columns(source) == ['id'])


def validate_projection_proofs(proofs, docs, context, contract_sha256):
    """Pure checks of real same-build clone/migration/readback provenance."""
    need(type(proofs) is dict and set(proofs) == set(PROJECTION_PROOFS), 'COMPLETE_PROJECTION_PROOF_CHAIN_REQUIRED')
    values = {name: decode(value) for name, value in proofs.items()}
    owner, source = docs['fixtureOwner'], docs['sourceManifest']
    clone, supplied, receipt, readback, summary, verifier = (values[name] for name in PROJECTION_PROOFS)
    same_context(clone, context)
    need(clone.get('kind') == 'doorhandle-source-clone-comparison' and clone.get('schemaVersion') == 1
         and clone.get('sourceSnapshotSha256') == clone.get('cloneSnapshotSha256') == source['snapshotSha256']
         and owner.get('sourceCloneSnapshotSha256') == source['snapshotSha256']
         and clone.get('sourceMetadataSha256') == clone.get('cloneMetadataSha256') == source['metadataSha256']
         and clone.get('ddlHashPolicy') == source.get('ddlHashPolicy')
         and clone.get('snapshotFieldsDifferent') == {} and clone.get('businessRowValuesIncluded') is False,
         'FULL_SOURCE_CLONE_PROVENANCE_DRIFT')
    catalog = docs['verification'].get('reportFiles')
    need(type(catalog) is list, 'AUTHENTICATED_WHOLE_REPORT_CATALOG_REQUIRED')
    for role, path in (('verifier', 'reports/receipt.json'), ('wholeSummary', 'reports/migration.json')):
        entries = [item for item in catalog if item.get('path') == path]
        need(len(entries) == 1 and entries[0].get('sha256') == digest(proofs[role])
             and entries[0].get('bytes') == len(proofs[role]), 'WHOLE_REPORT_RAW_DIGEST_DRIFT')
    need(verifier.get('status') == 'PASS' and verifier.get('identity') == context['identity']
         and verifier.get('scopeKind') == 'mysql' and verifier.get('wholeMigrationRequested') is True
         and verifier.get('wholeMigrationSummarySha256') == digest(proofs['wholeSummary'])
         and type(verifier.get('wholeMigrationTests')) is dict
         and type(verifier['wholeMigrationTests'].get('passed')) is int and verifier['wholeMigrationTests']['passed'] > 0
         and verifier['wholeMigrationTests'].get('failed') == verifier['wholeMigrationTests'].get('skipped') == 0,
         'ACTUAL_WHOLE_MIGRATION_PASS_REQUIRED')
    need(summary.get('kind') == 'doorhandle-compact-migration-acceptance' and summary.get('status') == 'VERIFIED'
         and summary.get('sourceTableCount') == 131 and summary.get('targetTableCount') == 29
         and summary.get('migrationReceiptSha256') == digest(proofs['wholeReceipt'])
         and summary.get('sourceSnapshotSha256') == source['snapshotSha256'], 'WHOLE_SOURCE_ANCHOR_DRIFT')
    need(supplied.get('kind') == 'doorhandle-runtime-migration-input' and supplied.get('version') == 1
         and supplied.get('ecs') == context['identity'] and supplied.get('serverUuid') == owner.get('serverUuid')
         and supplied.get('migrationReceiptSha256') == digest(proofs['wholeReceipt']), 'RUNTIME_MIGRATION_INPUT_DRIFT')
    need(receipt.get('kind') == 'doorhandle-compact-migration' and receipt.get('schemaVersion') == 1
         and receipt.get('status') == 'VERIFIED' and receipt.get('scope') == 'ecs-disposable-migration'
         and receipt.get('ecs') == context['identity'] and receipt.get('serverUuid') == owner.get('serverUuid')
         and receipt.get('sourceSchema') == owner.get('sourceClone')
         and receipt.get('sourceTableCount') == 131 and receipt.get('targetTableCount') == 29
         and receipt.get('sourceSnapshotSha256') == source['snapshotSha256']
         and receipt.get('sourceMetadataSha256') == source['metadataSha256']
         and receipt.get('sourceSnapshot', {}).get('tables') == source['tables']
         and receipt.get('contractSha256') == contract_sha256
         and receipt.get('foreignKeysValidated') is True, 'WHOLE_MIGRATION_SOURCE_PROVENANCE_DRIFT')
    need(readback.get('kind') == 'doorhandle-compact-cutover-readback' and readback.get('status') == 'VERIFIED'
         and readback.get('migrationReceiptSha256') == digest(proofs['wholeReceipt'])
         and all(readback.get(key) == receipt.get(key) for key in ('ecs', 'serverUuid', 'sourceSchema', 'targetSchema',
             'attempt', 'sourceSnapshotSha256', 'targetSnapshotSha256', 'targetMetadataSha256', 'freezeEvidenceSha256')),
         'WHOLE_MIGRATION_FINAL_READBACK_DRIFT')
    return values


def validate_projection_packet(packet, *, documents, docs, context, source_index, anchor):
    need(type(packet) is dict and set(packet) == {'receipt', 'tables', 'proofs'} and hash_field(anchor)
         and digest(packet['receipt']) == anchor, 'EXTERNAL_PROJECTION_RECEIPT_ANCHOR_REQUIRED')
    receipt = decode(packet['receipt']); same_context(receipt, context)
    validate_projection_proofs(packet['proofs'], docs, context, digest(documents['contract']))
    source, local, owner = docs['sourceManifest'], docs['localA']['snapshot'], docs['fixtureOwner']
    need(receipt.get('kind') == 'doorhandle-source-legacy-projection' and receipt.get('schemaVersion') == 1
         and receipt.get('status') == 'VERIFIED' and receipt.get('ruleEvidenceSha256') == LEGACY_EVOLUTION_EVIDENCE_SHA256
         and receipt.get('inputRawSha256') == {name: digest(value) for name, value in documents.items()}
         and receipt.get('proofRawSha256') == {name: digest(value) for name, value in packet['proofs'].items()}
         and receipt.get('fullSourceIndexSha256') == docs['fixtureOwner']['sourceKeyedRowsIndex']['sha256']
         and receipt.get('sourceServerUuid') == source['serverUuid']
         and receipt.get('cloneServerUuid') == owner.get('serverUuid')
         and receipt.get('cloneContainerId') == owner.get('containerId')
         and receipt.get('sourceContainerId') == owner.get('sourceContainerId')
         and receipt.get('sourceClone') == owner.get('sourceClone')
         and receipt.get('sourceScope') == 'SAME_BUILD_FULL_131_FROZEN_SOURCE_CLONE'
         and receipt.get('productionMerged') is False and receipt.get('retirementAllowed') is False
         and receipt.get('sourceReadLock', {}).get('kind') == 'MYSQL_LOCK_TABLES_READ'
         and receipt['sourceReadLock'].get('sourceTableCount') == 131,
         'PROJECTION_SOURCE_BINDING_DRIFT')
    need(receipt.get('beforeSnapshotSha256') == receipt.get('afterSnapshotSha256') == source['snapshotSha256']
         and receipt.get('beforeMetadataSha256') == receipt.get('afterMetadataSha256') == source['metadataSha256'],
         'PROJECTION_COMPLETE_SOURCE_CHANGED')
    names = {name for name in LEGACY_EVOLUTION if name in local['tables'] and name in source['tables']
             and local['tables'][name]['columns'] != source['tables'][name]['columns']}
    need(names and set(receipt.get('tables', {})) == set(packet['tables']) == names, 'CLOSED_LEGACY_PROJECTION_TABLES_REQUIRED')
    maps = {}
    for name in sorted(names):
        old, full, descriptor = local['tables'][name], source['tables'][name], receipt['tables'][name]
        need(approved_legacy_projection(name, old, full), 'UNAPPROVED_LEGACY_COLUMN_EVOLUTION')
        need(type(descriptor) is dict and set(descriptor) == KEYED_FIELDS | {'sourceColumnsSha256', 'fullSourceDescriptorSha256'}
             and descriptor['status'] == 'KEYED' and descriptor['rows'] == descriptor['entries'] == full['rows']
             and type(descriptor['rows']) is int and type(descriptor['entries']) is int and descriptor['rows'] <= MAX_KEYED_ROWS
             and descriptor['columnsSha256'] == sha_json(old['columns']) and descriptor['primary'] == primary_columns(old)
             and descriptor['sourceColumnsSha256'] == sha_json(full['columns'])
             and descriptor['fullSourceDescriptorSha256'] == sha_json(source_index['tables'][name])
             and descriptor['file'] == name + '.jsonl' and hash_field(descriptor['fileSha256'])
             and type(descriptor['bytes']) is int and 0 <= descriptor['bytes'] <= MAX_JSON,
             'PROJECTION_COMPLETE_TYPED_DESCRIPTOR_DRIFT')
        maps[name] = validate_keyed_rows(packet['tables'][name], descriptor)
    return maps


def reconcile_keyed_documents(raw_documents, *, expected_context, anchors, keyed_documents,
                              projection_documents=None, projection_anchor=None):
    """Audit captured full typed rows; hashes only, no DB access or merge authority.

    The existing complete evidence chain authenticates both recovered local
    indexes and the source index. Key digests come from that fixed collector;
    a matching full row chain alone is never accepted as a trusted key source.
    Returned differences are private ECS evidence, not the public CI report.
    """
    base = classify_documents(raw_documents, expected_context=expected_context, anchors=anchors)
    docs = {key: decode(raw) for key, raw in raw_documents.items()}; refs = keyed_references(docs)
    need(all(type(refs[role]) is dict for role in KEYED_ROLES), 'ALL_THREE_TRUSTED_KEYED_INDEXES_REQUIRED')
    need(type(keyed_documents) is dict and set(keyed_documents) == set(KEYED_ROLES), 'COMPLETE_KEYED_DOCUMENT_BUNDLE_REQUIRED')
    source = docs['sourceManifest']
    snapshots = {'localA': docs['localA']['snapshot'], 'localB': docs['localB']['snapshot'],
                'source': {'schema': source['schema'], 'snapshotSha256': source['snapshotSha256'], 'tables': source['tables']}}
    indexes = {}; total_bytes = 0
    for role in KEYED_ROLES:
        packet = keyed_documents[role]
        need(type(packet) is dict and set(packet) == {'index', 'tables'} and type(packet['tables']) is dict,
             'EXACT_KEYED_DOCUMENT_PACKET_REQUIRED')
        indexes[role] = validate_keyed_index(packet['index'], refs[role], snapshots[role], role=role)
        names = {name for name, entry in indexes[role]['tables'].items() if entry['status'] == 'KEYED'}
        need(set(packet['tables']) == names and all(type(raw) is bytes for raw in packet['tables'].values()),
             'COMPLETE_KEYED_ROW_MEMBERS_REQUIRED')
        total_bytes += len(packet['index']) + sum(len(raw) for raw in packet['tables'].values())
        need(total_bytes <= MAX_KEYED_BUNDLE_BYTES, 'KEYED_BUNDLE_BYTE_LIMIT_EXCEEDED')
    need(indexes['localA'] == indexes['localB'], 'INDEPENDENT_KEYED_RECOVERY_INDEXES_DIFFER')
    projected = (validate_projection_packet(projection_documents, documents=raw_documents, docs=docs,
        context=expected_context, source_index=indexes['source'], anchor=projection_anchor)
        if projection_documents is not None else {})
    need(projection_documents is not None or projection_anchor is None, 'PROJECTION_ANCHOR_WITHOUT_PACKET')
    if projection_documents is not None:
        need(total_bytes + len(projection_documents['receipt'])
             + sum(len(raw) for raw in projection_documents['tables'].values()) <= MAX_KEYED_BUNDLE_BYTES,
             'KEYED_BUNDLE_BYTE_LIMIT_EXCEEDED')
    counts = {'MATCH': 0, 'LOCAL_ONLY': 0, 'SOURCE_ONLY': 0, 'ROW_CONFLICT': 0}
    comparisons, differences, blockers = [], [], []
    local_tables, source_tables = snapshots['localA']['tables'], snapshots['source']['tables']
    for name in sorted(set(local_tables) | set(source_tables)):
        maps = {}
        for role in KEYED_ROLES:
            descriptor = indexes[role]['tables'].get(name)
            if descriptor is not None and descriptor['status'] == 'KEYED':
                maps[role] = validate_keyed_rows(keyed_documents[role]['tables'][name], descriptor)
        if name in local_tables and 'localA' in maps:
            need(maps['localA'] == maps['localB'], 'INDEPENDENT_KEYED_RECOVERY_ROWS_DIFFER')
        local, cloud = local_tables.get(name), source_tables.get(name)
        if local is None:
            # New cloud-only tables have no legacy rows requiring inclusion.
            comparisons.append({'table': name, 'status': 'SOURCE_TABLE_ONLY', 'sourceRows': cloud['rows']})
            continue
        approved = cloud is not None and approved_legacy_projection(name, local, cloud)
        reason = ('LOCAL_TABLE_MISSING_FROM_SOURCE' if cloud is None else
                  'TRUSTED_LEGACY_PROJECTION_NOT_COLLECTED' if approved and name not in projected else
                  'FULL_TYPED_COLUMNS_OR_PRIMARY_ORDER_DIFFER' if (local['columns'] != cloud['columns']
                  and not approved) or primary_columns(local) != primary_columns(cloud) else
                  'NO_PRIMARY_KEY' if not primary_columns(local) else None)
        if reason is not None:
            comparisons.append({'table': name, 'status': 'NOT_COMPARABLE', 'reasonCode': reason,
                                'localRows': local['rows'], 'sourceRows': cloud['rows'] if cloud else None})
            blockers.append({'table': name, 'reasonCode': reason}); continue
        local_rows, cloud_rows = maps['localA'], projected.get(name, maps['source'])
        if name in projected:
            need(set(cloud_rows) == set(maps['source']), 'PROJECTION_FULL_SOURCE_PRIMARY_KEYS_DIFFER')
        table_counts = {key: 0 for key in counts}
        for key in sorted(set(local_rows) | set(cloud_rows)):
            before, after = local_rows.get(key), cloud_rows.get(key)
            state = 'SOURCE_ONLY' if before is None else 'LOCAL_ONLY' if after is None else 'MATCH' if before == after else 'ROW_CONFLICT'
            table_counts[state] += 1; counts[state] += 1
            if state != 'MATCH': differences.append({'table': name, 'status': state, 'keySha256': key,
                                                     'localRowSha256': before, 'sourceRowSha256': after})
        if table_counts['LOCAL_ONLY'] or table_counts['ROW_CONFLICT']:
            blockers.append({'table': name, 'reasonCode': 'LEGACY_ROWS_MISSING_OR_CONFLICTING'})
        comparisons.append({'table': name, 'status': 'COMPARED', 'counts': table_counts,
                            'localRows': local['rows'], 'sourceRows': cloud['rows'],
                            **({'comparisonColumns': 'APPROVED_COMPLETE_LEGACY_VECTOR'} if name in projected else {})})
    summary = {'status': 'RECONCILED' if not blockers else 'NEEDS_REVIEW', 'scope': 'EXACT_TYPED_PRIMARY_KEYS_V1',
        'gateScope': 'PER_KEY_SOURCE_INCLUSION_ONLY', 'wholeMigrationAndRuntimeAcceptanceStillRequired': True,
        'requiredBeforeCutover': True, 'cutoverBlocked': bool(blockers), 'legacyRowsPresentInSource': not blockers,
        'counts': counts, 'rowCountScope': 'COMPARABLE_COMMON_TABLES_ONLY',
        'sourceOnlyTableCount': len(set(source_tables) - set(local_tables)),
        'sourceOnlyTableRows': sum(source_tables[name]['rows'] for name in set(source_tables) - set(local_tables)),
        'tableComparisons': comparisons, 'blockingTables': blockers,
        'indexSha256': {role: digest(keyed_documents[role]['index']) for role in KEYED_ROLES},
        'localSnapshotSha256': base['localSnapshotSha256'], 'sourceSnapshotSha256': base['sourceSnapshotSha256'],
        'coverageVerified': False, 'targetDataCompared': False, 'productionMerged': False, 'retirementAllowed': False,
        'excludedComparisons': ['TARGET29_DATA', 'SCHEMA_WIDE_METADATA', 'TRIGGERS', 'ROUTINES', 'EVENTS'],
        'clockPolicy': 'EXACT_ORIGINAL_BYTES_NO_TIMEZONE_INFERENCE'}
    if projected:
        summary['legacyColumnProjection'] = {'status': 'VERIFIED', 'tables': sorted(projected),
            'receiptSha256': projection_anchor, 'ruleEvidenceSha256': LEGACY_EVOLUTION_EVIDENCE_SHA256,
            'fullSourceColumnsAndRowsRetained': True, 'scope': 'AUDITED_19_APPENDED_COLUMNS_ONLY',
            'sourceScope': 'SAME_BUILD_FULL_131_FROZEN_SOURCE_CLONE'}
    return {'summary': summary, 'differences': differences}


def read_control(path):
    need(path.is_absolute() and '..' not in path.parts and path.resolve(strict=True) == path, 'CANONICAL_CONTROL_PATH_REQUIRED')
    for parent in (path, *path.parents): need(not parent.is_symlink(), 'CONTROL_LINK_REFUSED')
    before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == os.getuid()
         and not before.st_mode & 0o077 and 0 < before.st_size <= MAX_JSON, 'PRIVATE_UNLINKED_CONTROL_REQUIRED')
    raw = path.read_bytes(); after = path.lstat()
    signature = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
    need(signature(before) == signature(after) and len(raw) == before.st_size, 'CONTROL_CHANGED_DURING_READ')
    return raw


def read_keyed_member(path):
    """Stable private read; an empty table legitimately has a zero-byte file."""
    need(path.is_absolute() and '..' not in path.parts and path.resolve(strict=True) == path, 'CANONICAL_KEYED_MEMBER_REQUIRED')
    for parent in (path, *path.parents): need(not parent.is_symlink(), 'KEYED_MEMBER_LINK_REFUSED')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == os.getuid()
             and not before.st_mode & 0o077 and 0 <= before.st_size <= MAX_JSON, 'PRIVATE_BOUNDED_KEYED_MEMBER_REQUIRED')
        raw = stream.read(MAX_JSON + 1); after = os.fstat(stream.fileno()); linked = path.lstat()
    signature = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_nlink, value.st_mode)
    need(signature(before) == signature(after) == signature(linked) and len(raw) == before.st_size, 'KEYED_MEMBER_CHANGED_DURING_READ')
    return raw


def load_keyed_documents(work, docs):
    references = keyed_references(docs); result = {}; total = 0
    for role in KEYED_ROLES:
        directory = (work / 'compact-fixtures/source-keyed-rows' if role == 'source'
                     else work / 'local-mysql-recovery' / ('a' if role == 'localA' else 'b') / 'keyed-rows')
        need(directory.resolve(strict=True) == directory and not directory.is_symlink(), 'CANONICAL_KEYED_DIRECTORY_REQUIRED')
        info = directory.stat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
             'PRIVATE_KEYED_DIRECTORY_REQUIRED')
        raw_index = read_control(directory / 'index.json')
        snapshot = (docs[role]['snapshot'] if role != 'source' else
                    {key: docs['sourceManifest'][key] for key in ('schema', 'snapshotSha256', 'tables')})
        index = validate_keyed_index(raw_index, references[role], snapshot, role=role)
        names = {name for name, item in index['tables'].items() if item['status'] == 'KEYED'}
        need({entry.name for entry in directory.iterdir()} == {'index.json'} | {name + '.jsonl' for name in names},
             'CLOSED_KEYED_DIRECTORY_MEMBERSHIP_REQUIRED')
        total += len(raw_index); members = {}
        for name in sorted(names):
            need(total + index['tables'][name]['bytes'] <= MAX_KEYED_BUNDLE_BYTES, 'KEYED_BUNDLE_BYTE_LIMIT_EXCEEDED')
            members[name] = read_keyed_member(directory / (name + '.jsonl')); total += len(members[name])
        result[role] = {'index': raw_index, 'tables': members}
    return result


def load_projection_proofs(work):
    directory = work / 'compact-fixtures'
    runtime_raw = read_control(directory / 'runtime-migration.json'); supplied = decode(runtime_raw)
    path = Path(supplied.get('migrationReceiptFile', ''))
    need(path.is_absolute() and path.is_relative_to(directory)
         and len(path.relative_to(directory).parts) == 3
         and re.fullmatch(r'whole-migration-acceptance-[a-f0-9]{10}', path.parent.parent.name)
         and path.parent.name == 'migrate' and path.name == 'migration-receipt.json',
         'EXACT_WHOLE_MIGRATION_RECEIPT_PATH_REQUIRED')
    return {'runtimeInput': runtime_raw,
        'cloneComparison': read_control(directory / 'source-clone-comparison-private.json'),
        'wholeReceipt': read_control(path),
        'wholeReadback': read_control(path.parent.parent / 'readback/cutover-readback.json'),
        'wholeSummary': read_control(work / 'ci-evidence/migration.json'),
        'verifier': read_control(work / 'ci-evidence/receipt.json')}


def load_projection_documents(work):
    directory = work / 'compact-fixtures/source-legacy-projection'
    need(directory.resolve(strict=True) == directory and not directory.is_symlink(), 'CANONICAL_PROJECTION_DIRECTORY_REQUIRED')
    info = directory.stat()
    need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
         'PRIVATE_PROJECTION_DIRECTORY_REQUIRED')
    private = directory / 'private'; private_info = private.lstat()
    need(not private.is_symlink() and stat.S_ISDIR(private_info.st_mode) and private_info.st_uid == os.getuid()
         and stat.S_IMODE(private_info.st_mode) == 0o700, 'PRIVATE_PROJECTION_SCRATCH_REQUIRED')
    receipt = read_control(directory / 'receipt.json'); value = decode(receipt)
    names = set(value.get('tables', {}))
    need(names and names <= set(LEGACY_EVOLUTION)
         and {entry.name for entry in directory.iterdir()} == {'receipt.json', 'private'} | {name + '.jsonl' for name in names},
         'CLOSED_PROJECTION_DIRECTORY_MEMBERSHIP_REQUIRED')
    return {'receipt': receipt, 'tables': {name: read_keyed_member(directory / (name + '.jsonl')) for name in sorted(names)},
            'proofs': load_projection_proofs(work)}


def classification_paths(checkout):
    work = checkout / 'work'
    return {'verification': checkout.parent / 'verification-receipt.json',
        'localOwner': work / 'local-mysql-recovery-owner.json', 'localPublic': work / 'local-mysql-recovery/public-recovery.json',
        'localA': work / 'local-mysql-recovery/a/full-recovery-private.json',
        'localB': work / 'local-mysql-recovery/b/full-recovery-private.json',
        'fixtureOwner': work / 'compact-fixtures-owner.json',
        'sourceManifest': work / 'compact-fixtures/source-backup/manifest.json',
        'contract': checkout / 'docs/database/compact-schema-contract.json'}


def write_private_differences(path, context, differences):
    need(not path.exists() and not path.is_symlink() and path.parent.resolve(strict=True) == path.parent,
         'NEW_PRIVATE_DIFFERENCE_REPORT_REQUIRED')
    checksum = hashlib.sha256(); written = 0
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as target:
        header = {'schemaVersion': 1, 'kind': 'doorhandle-keyed-differences-private', 'context': context,
                  'comparisonScope': 'EXACT_TYPED_PRIMARY_KEYS_V1', 'entries': len(differences)}
        for item in (header, *differences):
            record = canonical(item) + b'\n'; written += len(record)
            need(written <= MAX_KEYED_BUNDLE_BYTES, 'PRIVATE_KEY_DIFFERENCE_REPORT_LIMIT_EXCEEDED')
            target.write(record); checksum.update(record)
        target.flush(); os.fsync(target.fileno())
    return {'file': path.name, 'sha256': checksum.hexdigest(), 'bytes': written, 'entries': len(differences)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id', 'output'):
        parser.add_argument('--' + flag, required=True)
    for flag in ('verification-receipt', 'local-owner', 'fixture-owner', 'contract'):
        parser.add_argument('--' + flag + '-sha256', required=True)
    parser.add_argument('--legacy-projection-sha256')
    args = parser.parse_args(argv)
    try:
        need(sys.platform == 'linux', 'ECS_LINUX_CONTROL_ONLY')
        root = Path(args.root); checkout = root / 'verification' / args.tag / 'checkout'; work = checkout / 'work'
        need(root.is_absolute() and '..' not in root.parts and root.resolve(strict=True) == root
             and Path(__file__).absolute().parents[2] == checkout, 'FIXED_BUILD_CHECKOUT_REQUIRED')
        context = {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
            'identity': {'instanceId': args.instance_id, 'machineId': args.machine_id, 'executionLocation': 'ECS'}}
        validate_context(context)
        paths = classification_paths(checkout)
        # Tracked contract permissions follow the fixed checkout, not private
        # runtime-file permissions. All other input files must be owner-only.
        contract_path = paths.pop('contract')
        need(contract_path.resolve(strict=True) == contract_path and not contract_path.is_symlink(), 'CANONICAL_CONTRACT_REQUIRED')
        contract_info = contract_path.stat()
        need(stat.S_ISREG(contract_info.st_mode) and contract_info.st_nlink == 1 and 0 < contract_info.st_size <= MAX_JSON,
             'BOUNDED_CONTRACT_REQUIRED')
        raw = {key: read_control(path) for key, path in paths.items()}; raw['contract'] = contract_path.read_bytes()
        anchors = {'verification': args.verification_receipt_sha256, 'localOwner': args.local_owner_sha256,
                   'fixtureOwner': args.fixture_owner_sha256, 'contract': args.contract_sha256}
        report = classify_documents(raw, expected_context=context, anchors=anchors)
        docs = {key: decode(value) for key, value in raw.items()}; references = keyed_references(docs)
        need(all(value is None or type(value) is dict for value in references.values()), 'MALFORMED_KEYED_INDEX_REFERENCE')
        if all(value is not None for value in references.values()):
            compared = reconcile_keyed_documents(raw, expected_context=context, anchors=anchors,
                keyed_documents=load_keyed_documents(work, docs),
                projection_documents=load_projection_documents(work) if args.legacy_projection_sha256 else None,
                projection_anchor=args.legacy_projection_sha256)
            detail = write_private_differences(work / 'local-mysql-keyed-reconciliation-private.jsonl', context, compared['differences'])
            report['perKeyReconciliation'] = {**compared['summary'], 'privateDifferences': detail}
        else:
            report['perKeyReconciliation']['missingIndexes'] = [role for role in KEYED_ROLES if references[role] is None]
        output = Path(args.output)
        need(output.is_absolute() and output.is_relative_to(work) and '..' not in output.parts
             and output.parent.resolve(strict=True) == output.parent and not output.exists() and not output.is_symlink(),
             'NEW_PRIVATE_REPORT_BELOW_BUILD_WORK_REQUIRED')
        # Creating the new control report is the only mutation in this CLI.
        with os.fdopen(os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as target:
            target.write(canonical(report) + b'\n'); target.flush(); os.fsync(target.fileno())
        print(json.dumps({'status': 'CLASSIFIED', 'reportSha256': digest(output.read_bytes()), 'counts': report['counts'],
                          'coverageVerified': False, 'productionMerged': False, 'retirementAllowed': False,
                          'perKeyStatus': report['perKeyReconciliation']['status'],
                          'cutoverBlocked': report['perKeyReconciliation']['cutoverBlocked']}))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'REJECTED', 'errorType': type(error).__name__,
            'code': str(error) if isinstance(error, ClassificationError) else 'JSON_CLASSIFICATION_REJECTED',
            'coverageVerified': False, 'productionMerged': False, 'retirementAllowed': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
