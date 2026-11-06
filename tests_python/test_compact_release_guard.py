"""ECS-run unit contracts for release provenance; not migration/DDL acceptance evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

SOURCE = Path(__file__).resolve().parents[1]/'script/docker/compact-schema-guard.py'
spec = importlib.util.spec_from_file_location('compact_release_guard', SOURCE)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data=(json.dumps(value,sort_keys=True)+'\n').encode()
    path.write_bytes(data);path.chmod(0o600)
    return {'file':path.name,'sha256':hashlib.sha256(data).hexdigest()}


def migration_fixture(tmp_path):
    context={'contractSha256':'1'*64,'sqlSha256':'2'*64,'serverUuid':'server-fixture',
             'sourceSchema':'old_source','targetSchema':'compact_target','targetMetadataSha256':'3'*64,
             'sourceSnapshotSha256':'4'*64,'targetSnapshotSha256':'5'*64,
             'sourceMetadataSha256':'7'*64,'freezeEvidenceSha256':'8'*64,
             'attempt':'a'*32,'ecs':{'instanceId':'i-fixture','machineId':'b'*32},'copyPlanSha256':'6'*64}
    evidence={**context,'kind':'doorhandle-compact-migration-evidence','scope':'production-migration','status':'COPY_VERIFIED'}
    reference=private_json(tmp_path/'migration-evidence.json',evidence)
    proofs={}
    for purpose in ('source','target'):
        proof={**context,'schemaVersion':1,'kind':'doorhandle-compact-recovery','status':'VERIFIED',
               'purpose':purpose,'originalSchema':context[purpose+'Schema'],'restoreSchema':'restored_'+purpose,
               'migrationEvidenceSha256':reference['sha256'],
               'expectedSnapshotSha256':context[purpose+'SnapshotSha256'],
               'restoredSnapshotSha256':context[purpose+'SnapshotSha256'],
               'restoredTableCount':131 if purpose=='source' else 29,
               'restoredMetadataSha256':context['sourceMetadataSha256' if purpose=='source' else 'targetMetadataSha256']}
        proofs[purpose]=private_json(tmp_path/(purpose+'-proof.json'),proof)
    receipt={**context,'schemaVersion':1,'kind':'doorhandle-compact-migration','status':'VERIFIED',
             'scope':'production-migration','sourceTableCount':131,'targetTableCount':29,
             'foreignKeysValidated':True,'evidence':reference,'recovery':proofs}
    file=tmp_path/'migration-receipt.json';private_json(file,receipt)
    return file,receipt


def validate(file):
    return guard.validate_migration_receipts(file,contract_sha='1'*64,sql_sha='2'*64,
        server_uuid='server-fixture',target_schema='compact_target',live_metadata_sha='3'*64)


def test_complete_evidence_chain_is_bound_to_exact_schema_and_restoration_attempt(tmp_path):
    file,_=migration_fixture(tmp_path)
    result=validate(file)
    assert result['targetSchema']=='compact_target'
    assert result['attempt']=='a'*32


def test_self_consistent_foreign_restore_hash_cannot_replace_this_migration_snapshot(tmp_path):
    file,receipt=migration_fixture(tmp_path)
    proof_file=tmp_path/'target-proof.json';proof=json.loads(proof_file.read_text())
    proof['expectedSnapshotSha256']=proof['restoredSnapshotSha256']='f'*64
    receipt['recovery']['target']=private_json(proof_file,proof)
    private_json(file,receipt)
    with pytest.raises(ValueError,match='Restoration verification'):
        validate(file)


@pytest.mark.parametrize('field,value',[('sourceTableCount',130),('targetTableCount',30),
    ('foreignKeysValidated',False),('scope','disposable-migration')])
def test_incomplete_or_disposable_migration_cannot_admit_production(tmp_path,field,value):
    file,receipt=migration_fixture(tmp_path);receipt[field]=value;private_json(file,receipt)
    with pytest.raises(ValueError,match='complete source and target scope'):
        validate(file)


def test_restored_target_metadata_must_equal_the_current_admitted_schema(tmp_path):
    file,receipt=migration_fixture(tmp_path)
    proof_file=tmp_path/'target-proof.json';proof=json.loads(proof_file.read_text())
    proof['restoredMetadataSha256']='f'*64
    receipt['recovery']['target']=private_json(proof_file,proof);private_json(file,receipt)
    with pytest.raises(ValueError,match='Restored target structure'):
        validate(file)


def test_disposable_admission_requires_the_exact_ecs_disposable_migration_scope(tmp_path):
    file, receipt = migration_fixture(tmp_path)
    receipt['scope'] = 'ecs-disposable-migration'
    evidence = json.loads((tmp_path / 'migration-evidence.json').read_text()); evidence['scope'] = receipt['scope']
    receipt['evidence'] = private_json(tmp_path / 'migration-evidence.json', evidence)
    for purpose in ('source', 'target'):
        path = tmp_path / (purpose + '-proof.json'); proof = json.loads(path.read_text())
        proof['migrationEvidenceSha256'] = receipt['evidence']['sha256']
        receipt['recovery'][purpose] = private_json(path, proof)
    private_json(file, receipt)
    accepted = guard.validate_migration_receipts(file, contract_sha='1'*64, sql_sha='2'*64,
        server_uuid='server-fixture', target_schema='compact_target', live_metadata_sha='3'*64,
        scope='ecs-disposable-migration')
    assert accepted['targetSchema'] == 'compact_target'
    with pytest.raises(ValueError, match='complete source and target scope'):
        guard.validate_migration_receipts(file, contract_sha='1'*64, sql_sha='2'*64,
            server_uuid='server-fixture', target_schema='compact_target', live_metadata_sha='3'*64,
            scope='disposable-migration')


def test_schema_reference_normalization_preserves_literal_and_comment_facts():
    sql="UPDATE `old_source`.records SET note='old_source.records', other=old_source.records /* old_source.records */"
    normalized=guard.normalize_self_references(sql,'old_source')
    assert normalized=="UPDATE `$SELF`.records SET note='old_source.records', other=`$SELF`.records /* old_source.records */"


def test_metadata_fingerprint_detects_changed_generated_expression():
    original={'columns':[{'name':'derived','expression':'json_unquote(`payload`)'}]}
    changed={'columns':[{'name':'derived','expression':'json_extract(`payload`,\'$.different\')'}]}
    assert guard.metadata_sha256(original)!=guard.metadata_sha256(changed)
