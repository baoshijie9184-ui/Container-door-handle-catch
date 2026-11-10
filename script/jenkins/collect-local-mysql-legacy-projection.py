"""Capture the two audited old45 column vectors from this build's frozen clone.

No original/production connection, grants, schema writes, merge or retirement.
The existing admitted migration client is used only for reads and a source
read lock. A final receipt is written only after the complete 131-table source
and metadata are independently rechecked on both sides of the projection.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('legacy_projection_classifier',
    ROOT / 'script/jenkins/classify-local-mysql-source.py')
audit = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(audit)


def admitted_clone(runtime, work, docs, proofs, context):
    """Reuse the exact existing connection; historical pins never admit a client."""
    values = audit.validate_projection_proofs(proofs, docs, context,
        audit.digest((ROOT / 'docs/database/compact-schema-contract.json').read_bytes()))
    owner, supplied = docs['fixtureOwner'], values['runtimeInput']
    config_path = work / 'compact-fixtures/whole-migration.json'
    raw_config = audit.read_control(config_path)
    config, identity, config_sha = runtime.load_config(config_path)
    audit.need(config_sha == audit.digest(raw_config) and identity == context['identity']
        and owner.get('phase') == 'PREPARED' and config['scope'] == 'ecs-disposable-migration'
        and config['client']['kind'] == 'docker' and config['client']['containerId'] == owner.get('containerId')
        and config['client']['containerId'] != owner.get('sourceContainerId')
        and config['serverUuid'] == owner.get('serverUuid') != owner.get('sourceServerUuid')
        and config['sourceSchema'] == owner.get('sourceClone')
        and config['targetSchema'] == supplied.get('targetSchema')
        and config['dataDirectory'] == owner.get('dataDirectory')
        and config['connection']['host'] == '127.0.0.1' and config['connection']['port'] == owner.get('port')
        and config['connection']['username'].startswith('mig_'), 'EXISTING_ADMITTED_SOURCE_CLONE_CLIENT_REQUIRED')
    # The whole acceptance test changes only these two reviewed-observation
    # fields in the already admitted config, never the account or source.
    receipt_path = Path(supplied['migrationReceiptFile'])
    suffix = receipt_path.parent.parent.name.removeprefix('whole-migration-acceptance-')
    reviewed_path = work / 'compact-fixtures' / ('reviewed-whole-migration-' + suffix + '.json')
    audit.need(supplied.get('reviewedConfigFile') == str(reviewed_path), 'EXACT_REVIEWED_SOURCE_CONFIG_REQUIRED')
    reviewed_raw = audit.read_control(reviewed_path); reviewed = audit.decode(reviewed_raw)
    audit.need(audit.digest(reviewed_raw) == supplied.get('reviewedConfigSha256')
        == values['wholeReceipt'].get('configSha256'), 'REVIEWED_SOURCE_CONFIG_DIGEST_DRIFT')
    original = audit.decode(raw_config)
    audit.need(set(reviewed) == set(original) | {'reviewedSourceSnapshot', 'reviewedSourceSnapshotSha256'}
        and all(reviewed.get(key) == value for key, value in original.items())
        and reviewed.get('reviewedSourceSnapshot') == str(receipt_path.parent.parent / 'observe/source-observation.json')
        and reviewed.get('reviewedSourceSnapshotSha256') == values['wholeReceipt']['reviewedSourceObservationSha256'],
        'WHOLE_ACCEPTANCE_CHANGED_SOURCE_CONNECTION')
    observed_raw = audit.read_control(Path(reviewed['reviewedSourceSnapshot']))
    audit.need(audit.digest(observed_raw) == reviewed['reviewedSourceSnapshotSha256'], 'REVIEWED_SOURCE_OBSERVATION_DRIFT')
    observed = audit.decode(observed_raw); source = docs['sourceManifest']
    audit.need(observed.get('kind') == 'doorhandle-compact-source-observation'
        and observed.get('status') == 'FROZEN_SOURCE_OBSERVED' and observed.get('ecs') == identity
        and observed.get('serverUuid') == config['serverUuid'] and observed.get('sourceSchema') == config['sourceSchema']
        and observed.get('sourceTableCount') == 131 and observed.get('sourceSnapshotSha256') == source['snapshotSha256']
        and observed.get('sourceMetadataSha256') == source['metadataSha256']
        and observed.get('contractSha256') == audit.digest((ROOT / 'docs/database/compact-schema-contract.json').read_bytes()),
        'WHOLE_REVIEWED_SOURCE_OBSERVATION_BINDING_DRIFT')
    receipt = runtime.validate_migration_receipt(receipt_path, {'ecs': identity, 'scope': config['scope'],
        'serverUuid': config['serverUuid'], 'sourceSchema': config['sourceSchema'], 'targetSchema': config['targetSchema']})
    audit.need(receipt == values['wholeReceipt'], 'WHOLE_RECEIPT_CHANGED_DURING_ADMISSION')
    return config, {config_path: config_sha, reviewed_path: audit.digest(reviewed_raw),
                    Path(reviewed['reviewedSourceSnapshot']): audit.digest(observed_raw)}


def capture(runtime, mysql, config, output, docs, context, documents, proofs, source_index):
    source, local, owner = docs['sourceManifest'], docs['localA']['snapshot'], docs['fixtureOwner']
    names = sorted(name for name in audit.LEGACY_EVOLUTION if name in local['tables'] and name in source['tables']
        and local['tables'][name]['columns'] != source['tables'][name]['columns'])
    audit.need(names and all(audit.approved_legacy_projection(name, local['tables'][name], source['tables'][name])
        for name in names), 'ONLY_AUDITED_COMPLETE_LEGACY_VECTORS_MAY_BE_CAPTURED')
    server = mysql.admitted_server()
    tables = sorted(source['tables'])
    descriptors = {}
    with mysql.source_lock(config['sourceSchema'], tables) as lock:
        def full_source():
            mysql.assert_source_lock()
            value = runtime.schema_snapshot(mysql, config['sourceSchema'], tables,
                ddl_hash_policy=audit.snapshot_policy(source) or audit._DDL_POLICY.RAW_POLICY)
            _metadata, meta_sha = runtime.metadata_snapshot(mysql, config['sourceSchema'])
            audit.need(value['snapshotSha256'] == source['snapshotSha256']
                and value['tables'] == source['tables'] and meta_sha == source['metadataSha256'],
                'FULL_131_SOURCE_CHANGED_BEFORE_OR_DURING_PROJECTION')
            return value['snapshotSha256'], meta_sha
        before, before_meta = full_source()
        for name in names:
            mysql.assert_source_lock()
            old, full = local['tables'][name], source['tables'][name]
            target = output / (name + '.jsonl')
            count, row_sha = mysql.row_hashes(config['sourceSchema'], name,
                [column['name'] for column in old['columns']], audit.primary_columns(old), keyed_rows_path=target)
            raw = audit.read_keyed_member(target)
            descriptor = {'status': 'KEYED', 'rows': count, 'rowsSha256': row_sha,
                'columnsSha256': audit.sha_json(old['columns']), 'primary': audit.primary_columns(old),
                'file': target.name, 'fileSha256': audit.digest(raw), 'bytes': len(raw), 'entries': count,
                'sourceColumnsSha256': audit.sha_json(full['columns']),
                'fullSourceDescriptorSha256': audit.sha_json(source_index['tables'][name])}
            audit.need(count == full['rows'], 'COMPLETE_SOURCE_PROJECTION_ROW_COUNT_REQUIRED')
            audit.validate_keyed_rows(raw, descriptor)
            descriptors[name] = descriptor
        after, after_meta = full_source()
        audit.need(mysql.admitted_server() == server, 'CLONE_IDENTITY_CHANGED_DURING_PROJECTION')
        mysql.assert_source_lock()
    return {'schemaVersion': 1, 'kind': 'doorhandle-source-legacy-projection', 'status': 'VERIFIED', **context,
        'ruleEvidenceSha256': audit.LEGACY_EVOLUTION_EVIDENCE_SHA256,
        'inputRawSha256': {key: audit.digest(value) for key, value in documents.items()},
        'proofRawSha256': {key: audit.digest(value) for key, value in proofs.items()},
        'sourceServerUuid': source['serverUuid'], 'cloneServerUuid': owner['serverUuid'],
        'cloneContainerId': owner['containerId'], 'sourceContainerId': owner['sourceContainerId'],
        'sourceClone': config['sourceSchema'], 'fullSourceIndexSha256': owner['sourceKeyedRowsIndex']['sha256'],
        'beforeSnapshotSha256': before, 'afterSnapshotSha256': after,
        'beforeMetadataSha256': before_meta, 'afterMetadataSha256': after_meta,
        'sourceReadLock': lock, 'tables': descriptors,
        'sourceScope': 'SAME_BUILD_FULL_131_FROZEN_SOURCE_CLONE', 'productionMerged': False, 'retirementAllowed': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id'):
        parser.add_argument('--' + flag, required=True)
    for flag in ('verification-receipt', 'local-owner', 'fixture-owner', 'contract'):
        parser.add_argument('--' + flag + '-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        audit.need(sys.platform == 'linux', 'ECS_LINUX_COLLECTION_ONLY')
        root = Path(args.root); checkout = root / 'verification' / args.tag / 'checkout'; work = checkout / 'work'
        audit.need(root.is_absolute() and '..' not in root.parts and root.resolve(strict=True) == root
            and checkout == ROOT, 'FIXED_BUILD_CHECKOUT_REQUIRED')
        context = {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
            'identity': {'instanceId': args.instance_id, 'machineId': args.machine_id, 'executionLocation': 'ECS'}}
        audit.validate_context(context)
        paths = audit.classification_paths(checkout)
        # This tracked document is fixed by the source archive, not a secret.
        contract_path = paths.pop('contract')
        audit.need(contract_path.resolve(strict=True) == contract_path and contract_path.is_file(), 'FIXED_CONTRACT_REQUIRED')
        documents = {name: audit.read_control(path) for name, path in paths.items()}
        documents['contract'] = contract_path.read_bytes()
        anchors = {'verification': args.verification_receipt_sha256, 'localOwner': args.local_owner_sha256,
            'fixtureOwner': args.fixture_owner_sha256, 'contract': args.contract_sha256}
        docs = {name: audit.decode(value) for name, value in documents.items()}
        keyed = audit.load_keyed_documents(work, docs)
        audit.reconcile_keyed_documents(documents, expected_context=context, anchors=anchors, keyed_documents=keyed)
        proofs = audit.load_projection_proofs(work)
        sys.path.insert(0, str(ROOT / 'script/schema')); sys.path.insert(0, str(ROOT / 'scripts'))
        import compact_migration_runtime as runtime
        config, config_bindings = admitted_clone(runtime, work, docs, proofs, context)
        output = runtime.fresh_output(work / 'compact-fixtures/source-legacy-projection')
        mysql = runtime.Mysql(config, output)
        receipt = capture(runtime, mysql, config, output, docs, context, documents, proofs, audit.decode(keyed['source']['index']))
        audit.need(all(audit.read_control(path) == documents[name] for name, path in paths.items())
            and contract_path.read_bytes() == documents['contract'] and audit.load_projection_proofs(work) == proofs
            and all(audit.digest(audit.read_control(path)) == expected for path, expected in config_bindings.items()),
            'PROJECTION_INPUT_EVIDENCE_CHANGED_DURING_COLLECTION')
        raw = audit.canonical(receipt) + b'\n'
        packet = {'receipt': raw, 'proofs': proofs,
            'tables': {name: audit.read_keyed_member(output / (name + '.jsonl')) for name in receipt['tables']}}
        audit.reconcile_keyed_documents(documents, expected_context=context, anchors=anchors,
            keyed_documents=keyed, projection_documents=packet, projection_anchor=audit.digest(raw))
        # Publish only after read-lock exit, full recheck and independent packet validation.
        with os.fdopen(os.open(output / 'receipt.json', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        print(json.dumps({'status': 'LEGACY_PROJECTION_VERIFIED', 'receiptSha256': audit.digest(raw),
            'tables': sorted(receipt['tables']), 'productionMerged': False, 'retirementAllowed': False}))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'REJECTED', 'errorType': type(error).__name__,
            'code': str(error) if isinstance(error, audit.ClassificationError) else 'LEGACY_PROJECTION_COLLECTION_REJECTED',
            'productionMerged': False, 'retirementAllowed': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
