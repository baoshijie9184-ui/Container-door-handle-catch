"""Actual 131→29 copy and both restore executions on an explicitly owned ECS fixture.

This module never provisions a server, loads a production dump, or alters the
source. The private manifest must point at a separately prepared, populated
legacy schema and a built Workbench bridge. No mock database can satisfy it.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENABLED = os.environ.get('DOORHANDLE_COMPACT_MIGRATION_TESTS') == '1'
pytestmark = pytest.mark.skipif(not ENABLED, reason='Explicit ECS whole-migration fixture required')


def runtime():
    directory = ROOT / 'script/schema'
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location('compact_acceptance_runtime', directory / 'compact_migration_runtime.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke(mode, config, output, *, receipt=None, success=True):
    command = [sys.executable, '-B', str(ROOT / 'script/schema/migrate_compact.py'), mode,
               '--config', str(config), '--output', str(output)]
    if receipt is not None:
        command += ['--receipt', str(receipt)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=14400)
    # Customer data and SQL diagnostics remain private in the CLI attempt. A
    # failing test must not copy its stdout/stderr into public JUnit artifacts.
    if success:
        assert result.returncode == 0, 'ECS migration CLI stopped; inspect the private attempt on ECS'
    else:
        assert result.returncode != 0, 'An occupied target or unknown prior result must stop migration'
    return result


def test_actual_whole_copy_both_restores_readback_and_unknown_result_stop():
    common = runtime()
    config_file = Path(os.environ['DOORHANDLE_COMPACT_MIGRATION_CONFIG'])
    admitted, identity, _ = common.load_config(config_file)
    assert admitted['scope'] == 'ecs-disposable-migration'
    _, original, _ = common.private_json(config_file)
    # Keep the reviewed config adjacent to the admitted data directory; changing
    # its parent would alter the storage ownership boundary.
    tag = uuid.uuid4().hex[:10]
    parent = config_file.parent / ('whole-migration-acceptance-' + tag)
    parent.mkdir(mode=0o700)
    observe_output = parent / 'observe'
    invoke('observe', config_file, observe_output)
    observed_file = observe_output / 'source-observation.json'
    _, observed, _ = common.private_json(observed_file)
    assert observed['sourceTableCount'] == 131
    assert len(observed['sourceSnapshot']['tables']) == 131
    assert sum(row['rows'] for row in observed['sourceSnapshot']['tables'].values()) > 0
    assert observed['ecs'] == identity

    reviewed = copy.deepcopy(original)
    reviewed['reviewedSourceSnapshot'] = str(observed_file)
    reviewed['reviewedSourceSnapshotSha256'] = common.sha_file(observed_file)
    reviewed_config = config_file.parent / ('reviewed-whole-migration-' + tag + '.json')
    common.write_json(reviewed_config, reviewed)
    migrated = parent / 'migrate'
    invoke('migrate', reviewed_config, migrated)
    receipt_file = migrated / 'migration-receipt.json'
    receipt = common.validate_migration_receipt(receipt_file, {
        'ecs': identity, 'scope': 'ecs-disposable-migration',
        'serverUuid': admitted['serverUuid'], 'sourceSchema': admitted['sourceSchema'],
        'targetSchema': admitted['targetSchema']})
    model = json.loads((ROOT / 'docs/database/compact-schema-contract.json').read_text(encoding='utf8'))
    plan = common.copy_plan(model)
    assert [step['name'] for step in receipt['executedSteps']] == [step['name'] for step in plan]
    assert common.sha_json(plan) == receipt['copyPlanSha256']
    assert set(receipt['sourceSnapshot']['tables']) == set(model['sourceTables'])
    assert set(receipt['targetSnapshot']['tables']) == set(model['expectedTargetTables'])
    assert receipt['sourceSnapshotSha256'] == observed['sourceSnapshotSha256']
    assert receipt['foreignKeysValidated'] is True
    java = [step for step in receipt['executedSteps'] if step['kind'] == 'java']
    assert len(java) == 1 and java[0]['name'] == 'workbench-java'
    for purpose, count in (('source', 131), ('target', 29)):
        proof = common.receipt_member(migrated, receipt['recovery'][purpose])
        assert proof['restoredTableCount'] == count
        assert proof['restoredSnapshotSha256'] == receipt[purpose + 'SnapshotSha256']
        assert proof['restoredMetadataSha256'] == receipt[purpose + 'MetadataSha256']

    # A second real migration must refuse the already-populated target rather
    # than replay committed copy segments or create a success receipt.
    retry = parent / 'refuse-replay'
    invoke('migrate', reviewed_config, retry, success=False)
    assert not (retry / 'migration-receipt.json').exists()
    _, failure, _ = common.private_json(retry / 'migration-failed.json')
    assert failure['status'] == 'FAILED_OR_UNKNOWN_STOPPED'
    assert failure['executedSteps'] == []
    # The rejected replay must leave both original rows and candidate untouched.
    readback = parent / 'readback'
    invoke('verify', reviewed_config, readback, receipt=receipt_file)
    _, verified, _ = common.private_json(readback / 'cutover-readback.json')
    assert verified['status'] == 'VERIFIED'
    assert verified['sourceSnapshotSha256'] == receipt['sourceSnapshotSha256']
    assert verified['targetSnapshotSha256'] == receipt['targetSnapshotSha256']
    assert verified['migrationReceiptSha256'] == common.sha_file(receipt_file)

    evidence_dir = Path(os.environ['DOORHANDLE_CI_EVIDENCE_DIR'])
    assert evidence_dir.is_absolute() and evidence_dir.resolve(strict=True) == evidence_dir
    common.write_json(evidence_dir / 'migration.json', {
        'schemaVersion': 1, 'kind': 'doorhandle-compact-migration-acceptance', 'status': 'VERIFIED',
        'sourceTableCount': 131, 'targetTableCount': 29,
        'migrationReceiptSha256': common.sha_file(receipt_file),
        'sourceSnapshotSha256': receipt['sourceSnapshotSha256'],
        'targetSnapshotSha256': receipt['targetSnapshotSha256'],
        'sourceRecoveryReceiptSha256': receipt['recovery']['source']['sha256'],
        'targetRecoveryReceiptSha256': receipt['recovery']['target']['sha256']})
