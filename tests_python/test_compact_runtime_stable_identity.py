"""ECS CI contracts for the actual admission helper; fixtures are not HTTP/DB runtime proof.

Only the full runner's real transport and target DB can emit acceptance evidence.
These adapter fixtures exercise fail-closed decisions and exact hook semantics.
No application, database, browser, cloud lifecycle or original data is started.
"""
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.error

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stable_identity_admission_contract', ROOT / 'script/docker/compact-runtime-stable-identity.py')
stable = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stable)
real_http = stable._http


class Database:
    def __init__(self, ctx): self.ctx = ctx; self.queries = []
    def one(self, sql):
        self.queries.append(sql)
        if 'tableCount' in sql:
            return {'schema': self.ctx.owner['targetSchema'], 'serverUuid': self.ctx.server, 'tableCount': self.ctx.tables}
        if 'createdIdMissing' in sql:
            return {'tasks': self.ctx.tasks, 'createdIdMissing': 0, 'assigneeIdMissing': 0}
        return {'taskId': 'actual-task', 'createdUserId': self.ctx.accounts['supervisor']['userId'], 'createdIdentityName': self.ctx.accounts['supervisor']['username'],
            'createdBy': self.ctx.accounts['supervisor']['username'], 'assigneeUserId': self.ctx.accounts['inspector']['userId'], 'status': 'COMPLETED', 'version': 1}
    def query(self, sql):
        self.queries.append(sql)
        return [{'namespace': name, 'mode': self.ctx.mode if index == 0 else self.ctx.source,
            'revision': self.ctx.revision, 'payloadVersion': 1, 'controlId': 1,
            'activationRevision': self.ctx.revision if self.ctx.source == 'ACTIVE' else None}
            for index, name in enumerate(('DETECTION_IDENTITY_CONTROL', 'DETECTION_IDENTITY_SOURCE_CONTROL'))]
    def literal(self, value): return "'" + value.replace("'", "''") + "'"


def record(task='historical-task', state='ALREADY_ALIGNED', source='SOURCE_RECORDED', role='created'):
    user = 3 if task == 'actual-task' else 1
    name = 'private-account-supervisor' if task == 'actual-task' else 'private-historical-name'
    return {'taskId': task, 'role': role, 'state': state, 'existingUserId': user,
        'expectedName': name, 'suggestedUserId': 99,
        'source': {'state': source, 'bound_user_id': user, 'bound_identity_name': name,
                   'source_kind': 'NEW_CREATION' if task == 'actual-task' else 'SUPERVISOR_MAPPING'}}


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    value = SimpleNamespace(attempt=tmp_path, directory=tmp_path / 'public', project='owned-project-private-token', token='private-token',
        mode='PREVIEW', source='COLLECTING', revision=0, tasks=1, tables=29, server='owned-mysql-server',
        records=[record()], activations=[], saved=0, actual_flags=dict(stable.REQUIRED_ENV), peer_allowed=False, activation_readback=True)
    value.directory.mkdir()
    value.owner = {'targetSchema': 'doorhandle_compact_candidate_aaaaaaaaaa', 'serverUuid': value.server,
        'migrationReceiptSha256': 'a' * 64, 'initialTargetSnapshotSha256': 'b' * 64}
    value.accounts = {key: {'username': 'private-account-' + key, 'password': 'never-public-password', 'userId': index,
        'role': 'SUPERVISOR' if key in ('supervisor', 'reviewer') else 'INSPECTOR'}
        for index, key in enumerate(('inspector', 'peer', 'supervisor', 'reviewer'), 1)}
    value.context = lambda: {'schemaVersion': 1, 'kind': 'doorhandle-compact-runtime-acceptance', 'release': 'fixed-build',
        'commit': 'c' * 40, 'sourceSha256': 'd' * 64, 'candidateBuildSha256': 'e' * 64}
    value.common = SimpleNamespace(write_json=lambda path, data: Path(path).write_text(json.dumps(data), encoding='utf-8'),
        environment=lambda row: value.actual_flags)
    value.row = lambda service: {'Id': 'owned-container'}
    value.save = lambda: setattr(value, 'saved', value.saved + 1)
    value.db = Database(value)

    def http(ctx, alias, method, path, body=None, denied=()):
        if path == '/api/auth/check': return 200, {**ctx.accounts[alias], 'authenticated': True}
        if '/identity/preview' in path:
            records = [record('actual-task')] if 'taskId=actual-task' in path else ctx.records
            return 200, {'protocol': 'identity-map-v2', 'reviewEnabled': True, 'sourceEvidenceEnabled': True,
                'missingNameReviewEnabled': True, 'mode': ctx.mode, 'sourceMode': ctx.source, 'revision': ctx.revision,
                'records': records, 'hasMore': False, 'nextCursor': records[-1]['taskId'] if records else ''}
        if path.endswith('/activate'):
            ctx.activations.append(body)
            if ctx.activation_readback:
                ctx.revision += int(ctx.mode != 'ACTIVE' or ctx.source != 'ACTIVE');ctx.mode = ctx.source = 'ACTIVE'
            return 200, {'mode': 'ACTIVE'}
        if '/audit/changes?' in path:
            return 200, {'items': [] if alias == 'peer' else [{'resourceId': 'actual-task'}]}
        if alias == 'peer' and not ctx.peer_allowed: return 403, None
        return 200, {'taskId': 'actual-task', 'version': '1'}
    monkeypatch.setattr(stable, '_http', http)
    return value


def admission(ctx): stable.preflight(ctx); return stable.admit(ctx)
def complete(ctx): admission(ctx);ctx.tasks = 2;stable.prove_current_task(ctx, 'actual-task');return stable.require_receipts(ctx)
def report(ctx, stage): return json.loads((ctx.directory / stable.FILES[stage]).read_text(encoding='utf-8'))


def test_candidate_flags_are_forced_without_modifying_production_input():
    original = {'services': {'backend': {'environment': {'DETECTION_STABLE_IDENTITY_ENABLED': 'false', 'OTHER': 'retained'}}}}
    configured = stable.enable_required_environment(original)
    assert original['services']['backend']['environment']['DETECTION_STABLE_IDENTITY_ENABLED'] == 'false'
    assert configured['services']['backend']['environment']['OTHER'] == 'retained'
    assert all(configured['services']['backend']['environment'][key] == 'true' for key in stable.REQUIRED_ENV)


@pytest.mark.parametrize('state', ['CANDIDATE_ONLY', 'UNMATCHED', 'DIFFERENT_CURRENT_ACCOUNT', 'ORIGINAL_ACCOUNT_UNAVAILABLE', 'MISSING_NAME'])
def test_unknown_historical_ownership_never_applies_name_suggestion_or_activates(ctx, state):
    ctx.records = [record(state=state)]
    with pytest.raises(stable.StableIdentityBlocked, match='HISTORICAL_IDENTITY_REVIEW_REQUIRED'): admission(ctx)
    assert ctx.activations == []
    evidence = report(ctx, 'admission');assert evidence['historicalPreview']['gapCount'] == 1
    text = json.dumps(evidence)
    assert 'private-historical-name' not in text and 'private-token' not in text and 'suggestedUserId' not in text


def test_aligned_name_without_verified_source_still_blocks(ctx):
    ctx.records = [record(source='SOURCE_UNVERIFIED')]
    with pytest.raises(stable.StableIdentityBlocked): admission(ctx)
    assert not ctx.activations


def test_true_original_activate_uses_opened_revision_and_source_protection(ctx):
    reference = admission(ctx)
    assert reference['status'] == 'PASS'
    assert len(ctx.activations) == 1 and ctx.activations[0]['revision'] == 0 and ctx.activations[0]['sourceProtection'] is True
    assert report(ctx, 'admission')['databaseAfter']['bindingMode'] == 'ACTIVE'
    assert all(sql.startswith('SELECT ') for sql in ctx.db.queries)


def test_preflight_is_never_accepted_as_full_admission(ctx):
    stable.preflight(ctx)
    assert report(ctx, 'preflight')['status'] == 'PREFLIGHT_ONLY'
    with pytest.raises(stable.StableIdentityBlocked): stable.require_receipts(ctx)


def test_actual_disabled_flag_cannot_pass_by_declared_config(ctx):
    ctx.actual_flags['DETECTION_STABLE_IDENTITY_ENABLED'] = 'false'
    with pytest.raises(stable.StableIdentityBlocked, match='ACTUAL_STABLE_IDENTITY_FLAGS_REQUIRED'): admission(ctx)
    assert not ctx.activations


def test_success_response_without_active_db_readback_is_blocked(ctx):
    ctx.activation_readback = False
    with pytest.raises(stable.StableIdentityBlocked, match='ACTUAL_STABLE_SOURCE_MODE_REQUIRED'): admission(ctx)
    assert 'stableIdentityActivationPending' in ctx.owner


def test_empty_replacement_inventory_cannot_hide_preserved_historical_tasks(ctx):
    stable.preflight(ctx);ctx.tasks = 0
    with pytest.raises(stable.StableIdentityBlocked, match='SOURCE_TASK_INVENTORY_CHANGED'): stable.admit(ctx)
    assert not ctx.activations


def test_owned_server_identity_mismatch_blocks_before_start(ctx):
    ctx.server = 'different-server'
    with pytest.raises(stable.StableIdentityBlocked, match='OWNED_MIGRATED_TARGET_IDENTITY_MISMATCH'): stable.preflight(ctx)


def test_new_task_real_permission_receipts_are_required_in_same_build(ctx):
    assert complete(ctx)['status'] == 'PASS'
    value = report(ctx, 'authorization')
    assert value['taskBinding']['createdUserId'] == '3'
    assert value['taskBinding']['assigneeUserId'] == '1'
    assert value['taskBinding']['sourceKind'] == 'NEW_CREATION'
    assert [item['progressHttpStatus'] for item in value['httpPermissions']] == [200, 200, 200, 403]
    assert 'never-public-password' not in json.dumps(value)


def test_peer_success_is_not_an_authorization_denial(ctx):
    admission(ctx);ctx.tasks = 2;ctx.peer_allowed = True
    # Fixture intentionally violates _http's contract; scope assertion still rejects it.
    with pytest.raises(stable.StableIdentityBlocked, match='PEER_HTTP_SCOPE_MUST_BE_DENIED'): stable.prove_current_task(ctx, 'actual-task')
    assert report(ctx, 'authorization')['status'] == 'BLOCKED'


def test_current_inspector_access_cannot_replace_the_actual_supervisor_creator_or_assignee_binding(ctx):
    complete(ctx)
    authorization = report(ctx, 'authorization')
    authorization['taskBinding']['assigneeUserId'] = str(ctx.accounts['peer']['userId'])
    with pytest.raises(stable.StableIdentityBlocked, match='FINAL_ACTUAL_TASK_BINDING_NOT_PROVEN'):
        stable.validate_final_values(report(ctx, 'preflight'), report(ctx, 'admission'), authorization, ctx.accounts, ctx.server)


def test_new_creation_source_must_match_the_actual_supervisor_creator_not_an_aligned_other_identity(ctx, monkeypatch):
    admission(ctx); ctx.tasks = 2
    original = stable._http
    def mismatched_source(*args, **kwargs):
        status, value = original(*args, **kwargs)
        if 'taskId=actual-task' in args[3]:
            value['records'][0]['existingUserId'] = 1
            value['records'][0]['source']['bound_user_id'] = 1
        return status, value
    monkeypatch.setattr(stable, '_http', mismatched_source)
    with pytest.raises(stable.StableIdentityBlocked, match='ACTUAL_NEW_CREATION_SOURCE_CERTIFICATE_REQUIRED'):
        stable.prove_current_task(ctx, 'actual-task')


def test_mutated_evidence_cannot_pass_just_because_owner_status_is_pass(ctx):
    complete(ctx)
    (ctx.directory / stable.FILES['authorization']).write_text('{}', encoding='utf-8')
    with pytest.raises(stable.StableIdentityBlocked, match='DIGEST_MISMATCH'): stable.require_receipts(ctx)


def test_receipt_from_another_build_is_rejected(ctx):
    complete(ctx)
    ctx.context = lambda: {'schemaVersion': 1, 'kind': 'doorhandle-compact-runtime-acceptance', 'release': 'another-build',
        'commit': 'f' * 40, 'sourceSha256': 'd' * 64, 'candidateBuildSha256': 'e' * 64}
    with pytest.raises(stable.StableIdentityBlocked, match='CONTEXT_MISMATCH'): stable.require_receipts(ctx)


def test_old_unknown_activation_is_not_silently_reissued_with_new_intent(ctx):
    stable.preflight(ctx);ctx.owner['stableIdentityActivationPending'] = {'requestId': 'original', 'revision': '0'}
    with pytest.raises(stable.StableIdentityBlocked, match='OUTCOME_REQUIRES_REVIEW'): stable.admit(ctx)
    assert not ctx.activations


def test_real_http_adapter_never_counts_500_as_an_authorization_denial(ctx):
    rehearsal_spec = importlib.util.spec_from_file_location('stable_identity_real_client', ROOT / 'script/docker/application-rehearsal.py')
    rehearsal = importlib.util.module_from_spec(rehearsal_spec);rehearsal_spec.loader.exec_module(rehearsal)
    client = rehearsal.Client(18081);client.account_context = 'fixture-context'
    prepared = []
    def open_request(request, timeout):
        prepared.append(request)
        raise urllib.error.HTTPError(request.full_url, 500, 'private body is not read', {}, io.BytesIO(b''))
    client.opener = SimpleNamespace(open=open_request);ctx.client = lambda alias: client
    with pytest.raises(stable.StableIdentityBlocked, match='IDENTITY_HTTP_STATUS_UNEXPECTED'):
        real_http(ctx, 'peer', 'GET', '/api/detection/tasks/actual-task', denied=(403, 404))
    assert prepared[0].get_header('X-account-context') == 'fixture-context'
    assert prepared[0].get_header('Origin') == client.base


def test_public_gap_samples_are_bounded_even_when_many_histories_need_review(ctx):
    ctx.records = [record(task='legacy-' + str(index), state='CANDIDATE_ONLY') for index in range(100)]
    ctx.tasks = 100
    with pytest.raises(stable.StableIdentityBlocked): admission(ctx)
    value = report(ctx, 'admission')['historicalPreview']
    assert value['gapCount'] == 100 and len(value['gaps']) == stable.MAX_GAPS


def test_duplicate_authoritative_cursor_does_not_turn_partial_scan_into_success(ctx, monkeypatch):
    def preview(*args, **kwargs):
        return 200, {'protocol': 'identity-map-v2', 'reviewEnabled': True, 'sourceEvidenceEnabled': True,
            'missingNameReviewEnabled': True, 'mode': 'PREVIEW', 'revision': 0, 'sourceMode': 'COLLECTING',
            'records': [], 'hasMore': True, 'nextCursor': 'repeated-cursor'}
    monkeypatch.setattr(stable, '_http', preview)
    with pytest.raises(stable.StableIdentityBlocked, match='CURSOR_DID_NOT_ADVANCE'): stable._scan(ctx)


def test_active_mode_without_a_source_activation_revision_is_not_protection_proof(ctx):
    original = ctx.db.query
    def corrupt_source(sql):
        result = original(sql)
        for item in result:
            if item['namespace'] == 'DETECTION_IDENTITY_SOURCE_CONTROL': item['activationRevision'] = None
        return result
    ctx.db.query = corrupt_source
    with pytest.raises(stable.StableIdentityBlocked, match='ACTUAL_SOURCE_PROTECTION_REVISION_REQUIRED'): admission(ctx)
