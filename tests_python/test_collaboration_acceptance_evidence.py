"""ECS-only original-byte and business-policy receipt regressions; synthetic fixtures."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
from tests_python.browser_evidence_fixture import report_value
from tests_python.collaboration_evidence_fixture import install, write

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('collaboration_acceptance_policy', ROOT / 'script/docker/collaboration-acceptance-evidence.py')
policy = importlib.util.module_from_spec(spec); spec.loader.exec_module(policy)


def fixture(tmp_path):
    context = {'schemaVersion': 1, 'kind': 'doorhandle-compact-runtime-acceptance', 'release': 'ci-1-' + 'a' * 12,
        'commit': 'a' * 40, 'sourceSha256': 'b' * 64, 'identity': {'instanceId': 'i-example', 'machineId': 'c' * 32},
        'acceptanceProfileSha256': 'd' * 64, 'candidateBuildSha256': 'e' * 64}
    proof = {**context, 'status': 'PASS', 'project': 'doorhandle-rehearsal-' + 'f' * 12,
        'migrationReceiptSha256': '1' * 64, 'initialTargetSnapshotSha256': '2' * 64,
        'actualServerUuid': '11111111-1111-1111-1111-111111111111'}
    cleanup = {**context, 'status': 'STOPPED', 'project': proof['project']}
    browser = report_value(context)
    install(tmp_path, context, proof['project'], proof, cleanup, browser['accounts'])
    return proof, cleanup, browser


def change(tmp_path, cleanup, name, mutation):
    path = tmp_path / name; value = json.loads(path.read_bytes()); mutation(value)
    checksum = write(path, value)
    for collection in ('stableIdentityEvidence', 'collaborationHttpEvidence'):
        for reference in cleanup[collection].values():
            if reference['file'].endswith('/' + name): reference['sha256'] = checksum


def test_original_five_receipts_require_actual_cross_account_and_stable_identity_policy(tmp_path):
    proof, cleanup, browser = fixture(tmp_path)
    assert policy.validate_files(tmp_path, cleanup)['status'] == 'PRESERVED'
    assert policy.validate_files(tmp_path, cleanup, proof, browser)['status'] == 'VERIFIED'


@pytest.mark.parametrize('damage', ['missing', 'unlisted', 'bytes', 'escape', 'foreign-source', 'fake-active', 'missing-source',
    'flags-off', 'wrong-supervisor', 'peer-history', 'same-competitor', 'two-audits', 'two-commands', 'wrong-assignee',
    'bad-version', 'loser-500', 'candidate-write-200', 'restored-old-login', 'fresh-login-200', 'binding-not-advanced', 'other-task'])
def test_pass_labels_and_rehashed_receipts_cannot_hide_incomplete_actual_semantics(tmp_path, damage):
    proof, cleanup, browser = fixture(tmp_path)
    if damage == 'missing': (tmp_path / 'stable-identity-authorization.json').unlink()
    elif damage == 'unlisted': (tmp_path / 'private-input.json').write_text('{}')
    elif damage == 'bytes':
        with (tmp_path / 'collaboration-http-claim.json').open('ab') as stream: stream.write(b' ')
    elif damage == 'escape': cleanup['stableIdentityEvidence']['admission']['file'] = '../private.json'
    elif damage == 'foreign-source': change(tmp_path, cleanup, 'stable-identity-admission.json', lambda value: value.update(commit='0' * 40))
    elif damage in ('fake-active', 'missing-source', 'flags-off', 'wrong-supervisor'):
        def mutate(value):
            if damage == 'fake-active': value['databaseAfter']['bindingRevision'] = '1'
            elif damage == 'missing-source': value['databaseAfter']['sourceActivationRevision'] = None
            elif damage == 'flags-off': value['actualFlags']['DETECTION_STABLE_IDENTITY_ENABLED'] = False
            else: value['activation']['actualSupervisorUserId'] = browser['accounts']['peer']['userId']
        change(tmp_path, cleanup, 'stable-identity-admission.json', mutate)
    elif damage == 'peer-history':
        change(tmp_path, cleanup, 'stable-identity-authorization.json', lambda value: value['httpPermissions'][1].update(historyVisibleItems=1))
    elif damage in ('restored-old-login', 'fresh-login-200', 'binding-not-advanced'):
        def mutate(value):
            row = value['observations']['positions'][0]
            if damage == 'restored-old-login': row['oldSessionHttpStatuses'][1] = 200
            elif damage == 'fresh-login-200': row['loginRejected'] = 200
            else: row['restoredBindingVersion'] = '1'
        change(tmp_path, cleanup, 'collaboration-http-personnel.json', mutate)
    else:
        def mutate(value):
            row = value['observations']
            if damage == 'same-competitor': row['competingUserIds'][1] = row['competingUserIds'][0]
            elif damage == 'two-audits': row['committedAuditCount'] = 2
            elif damage == 'two-commands': row['committedCommandCount'] = 2
            elif damage == 'wrong-assignee': row['stableAssigneeUserId'] = browser['accounts']['inspector']['userId']
            elif damage == 'bad-version': row['receiptResourceVersion'] = '2'
            elif damage == 'loser-500': row['loserStatus'] = 500
            elif damage == 'candidate-write-200': row['candidateWriteHttpStatuses'][0] = 200
            else: row['taskId'] = 'a-different-task'
        change(tmp_path, cleanup, 'collaboration-http-claim.json', mutate)
    stable_rejections = {
        'fake-active': 'FINAL_ACTIVATION_CONTROL_REVISION_NOT_PROVEN',
        'missing-source': 'FINAL_ACTIVATION_CONTROL_REVISION_NOT_PROVEN',
        'flags-off': 'FINAL_STABLE_FLAGS_NOT_PROVEN',
        'wrong-supervisor': 'FINAL_ACTIVATION_CONTROL_REVISION_NOT_PROVEN',
        'peer-history': 'FINAL_PEER_SCOPE_NOT_DENIED',
    }
    if damage in stable_rejections:
        with pytest.raises(policy.stable.StableIdentityBlocked) as rejected:
            policy.validate_files(tmp_path, cleanup, proof, browser)
        assert str(rejected.value) == stable_rejections[damage]
    else:
        with pytest.raises((ValueError, OSError, KeyError)): policy.validate_files(tmp_path, cleanup, proof, browser)
