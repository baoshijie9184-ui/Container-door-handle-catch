"""ECS-only synthetic backend contracts: no native Windows deletion or SSH."""
from contextlib import contextmanager
import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('fixed_cold_retirement_contract', ROOT / 'script/jenkins/retire-local-cold-stores.py')
retire = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(retire)
PROFILE = 'cold-store-originals-v1'


class MemoryAudit:
    def __init__(self, events, callback=lambda event: None):
        self.events, self.callback = events, callback

    def record(self, event, **fields):
        self.events.append(('audit', event, fields)); self.callback(event)


class FakeCold:
    PROFILES = {PROFILE: {'SNAPSHOT': 'cold-store-originals-v1'}}

    def __init__(self):
        self.expired = False; self.validations = []
        self.now = dt.datetime(2026, 11, 8, 0, 0, tzinfo=dt.timezone.utc)

    def utc_now(self): return self.now

    @staticmethod
    def attestation_time(value):
        return dt.datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=dt.timezone.utc)

    def validate_retirement_attestation(self, value, **expected):
        self.validations.append(expected)
        retire.need(not self.expired and value == proof_for({'current': expected['expected_current'],
                    'custody': expected['expected_custody']}, expected['nonce'], self.attestation_time(value['issuedAtUtc']))
                    and self.attestation_time(value['issuedAtUtc']) <= self.now < self.attestation_time(value['expiresAtUtc']),
                    'SYNTHETIC_AUTHENTICATED_PROOF_REJECTED')
        return value


def proof_for(plan, nonce, now):
    return {'nonce': nonce, 'current': plan['current'], 'custody': plan['custody'],
            'issuedAtUtc': now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            'expiresAtUtc': (now + dt.timedelta(seconds=300)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')}


class FakeBackend:
    def __init__(self, events):
        self.events, self.held, self.tracked = events, False, set()
        self.fail_hash = self.fail_verify = self.fail_delete = self.fail_directory = None

    def tracked_sources(self): return self.tracked

    def active_references(self, value): self.events.append(('processes',))

    @contextmanager
    def hold(self, value):
        self.held = True; self.events.append(('held-all',))
        try: yield self
        finally: self.held = False; self.events.append(('closed-all',))

    def check_directories(self, value):
        assert self.held; self.events.append(('directory-preflight',))

    def hash_file(self, row):
        assert self.held; self.events.append(('hash', row['path']))
        retire.need(row['path'] != self.fail_hash, 'FRESH_SOURCE_BYTES_DIFFER')

    def verify_file(self, row):
        assert self.held; self.events.append(('verify', row['path']))
        retire.need(row['path'] != self.fail_verify, 'SOURCE_NATIVE_HANDLE_CHANGED')

    def delete_file(self, row):
        assert self.held
        retire.need(row['path'] != self.fail_delete, 'EXACT_HANDLE_DISPOSITION_REFUSED')
        self.events.append(('delete-held', row['path']))

    def rmdir_empty(self, row):
        assert self.held
        retire.need(row['path'] != self.fail_directory, 'DIRECTORY_HAS_UNKNOWN_REMAINING_CONTENT')
        self.events.append(('empty-dir-held', row['path']))


class FakeAttestor:
    def __init__(self, events, clock): self.events, self.clock = events, clock; self.failure = False; self.damage = False

    def fetch(self, plan, nonce):
        self.events.append(('live-ssh-proof', nonce))
        retire.need(not self.failure, 'AUTHENTICATED_LIVE_SERVER_ATTESTATION_REQUIRED')
        return proof_for(plan, 'wrong' if self.damage else nonce, self.clock.utc_now())


@pytest.fixture
def scope():
    prefix = 'work/frozen/memory'
    files = [{'path': prefix + '/' + name, 'fingerprint': [7, i + 20, 1, 40, 50, 1, 0o100600, 32],
              'bytes': 1, 'sha256': 'a' * 64, 'scopes': ['memory-01']} for i, name in enumerate(('a.bin', 'b.bin'))]
    directories = [{'path': prefix, 'fingerprint': [7, 10, 0, 40, 50, 1, 0o40700, 16],
                    'children': ['a.bin', 'b.bin', 'empty']},
                   {'path': prefix + '/empty', 'fingerprint': [7, 11, 0, 40, 50, 1, 0o40700, 16], 'children': []}]
    value = {'roots': [{'id': 'memory-01', 'path': prefix, 'kind': 'SQLITE_STORE_TREE'}],
             'members': files, 'directories': directories}
    counts, _ = retire.inventory_scope(value)
    current = {'release': 'ci-93-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    old = {'release': 'ci-92-' + 'c' * 12}
    plan = {'profile': PROFILE, 'counts': counts, 'selectedCounts': counts,
            'retained': {'rootIds': [], 'files': 0, 'directories': 0, 'bytes': 0},
            'inventorySha256': 'd' * 64, 'current': current, 'custody': old, 'coldHelperSha256': 'e' * 64}
    events = []; cold = FakeCold(); backend = FakeBackend(events); attest = FakeAttestor(events, cold)
    return SimpleNamespace(value=value, plan=plan, events=events, cold=cold, backend=backend,
                           attestor=attest, audit=MemoryAudit(events))


def apply(scope):
    return retire.apply_owned(scope.cold, scope.plan, scope.value, scope.backend, scope.attestor, scope.audit)


@pytest.mark.parametrize('path', ['C:/data/a', '//server/share/a', 'work/../a', 'work//a', 'work/a:stream',
    r'work\a', 'work/.git/../a', 'work/jenkins/a', 'work/middlewares/mysql/a',
    'work/ecs-only-20261105/micro-followup/checkout/a', 'work/NUL', 'work/com1.txt', 'work/a.', 'work/a '])
def test_only_canonical_unprotected_d_project_members_are_admissible(path):
    with pytest.raises(retire.RetirementError): retire.source_path(path)


def test_fixed_member_is_inside_literal_d_project_boundary():
    assert retire.source_path('work/frozen/x.bin') == retire.PROJECT_ROOT + r'\work\frozen\x.bin'


@pytest.mark.parametrize('damage', ['case-alias', 'file-directory-alias', 'unproved'])
def test_scope_never_infers_alias_or_unknown_root_ownership(scope, damage):
    if damage == 'case-alias': scope.value['members'].append({**scope.value['members'][0], 'path': 'work/FROZEN/memory/a.bin'})
    elif damage == 'file-directory-alias': scope.value['directories'].append({'path': scope.value['members'][0]['path']})
    else: scope.value['roots'][0]['kind'] = 'OWNERSHIP_UNPROVED'
    with pytest.raises(retire.RetirementError): apply(scope)
    assert not scope.events


def history_value():
    roots = [{'id': key, 'path': path, 'kind': 'TOOL_RECEIPT_STORE_COMPLETE_TREE_OWNERSHIP_UNPROVED'}
             for key, path in retire.KEPT_HISTORY_ROOTS.items()]
    files = []
    for root in roots:
        for i in range(4):
            files.append({'path': root['path'] + '/' + str(i), 'bytes': 117235 if not files else 0,
                          'scopes': [root['id']], 'fingerprint': [0] * 8, 'sha256': 'b' * 64})
    directories = [{'path': row['path'], 'scopes': [row['id']], 'fingerprint': [0] * 8} for row in roots]
    roots.append({'id': 'test-1', 'path': 'work/frozen/test', 'kind': 'HISTORICAL_TEST_STORE'})
    files.append({'path': 'work/frozen/test/file', 'bytes': 1, 'scopes': ['test-1'], 'fingerprint': [0] * 8, 'sha256': 'b' * 64})
    directories.append({'path': 'work/frozen/test', 'scopes': ['test-1'], 'fingerprint': [0] * 8})
    return {'roots': roots, 'members': files, 'directories': directories}


def test_exact_unproved_history_roots_are_retained_without_blocking_proved_roots():
    value = history_value(); original = copy.deepcopy(value)
    selected, kept = retire.selected_scope('cold-store-history-v2', value)
    assert value == original and kept == {'rootIds': ['tool-1675', 'tool-1676'], 'files': 8, 'directories': 2, 'bytes': 117235}
    assert [row['id'] for row in selected['roots']] == ['test-1']
    assert len(selected['members']) == len(selected['directories']) == 1


def test_history_apply_reports_partial_and_never_opens_or_deletes_protected_roots(scope):
    scope.value = history_value()
    selected, kept = retire.selected_scope('cold-store-history-v2', scope.value)
    scope.plan.update(profile='cold-store-history-v2', counts=retire.inventory_scope(scope.value)[0],
                      selectedCounts=retire.inventory_scope(selected)[0], retained=kept)
    def hold_selected(value):
        assert value == selected
        return FakeBackend.hold(scope.backend, value)
    scope.backend.hold = hold_selected
    result = apply(scope)
    assert result['status'] == 'PARTIAL_FIXED_PROFILE_PROTECTED_ROOTS_RETAINED'
    assert result['rootsSkipped'] == ['tool-1675', 'tool-1676'] and not result['entireProfileRetired']
    assert result['filesDeleted'] == result['directoriesRemoved'] == 1
    assert result['retained']['bytes'] == 117235
    assert not any('llm-management' in str(event) for event in scope.events if event[0] in ('hash', 'delete-held', 'empty-dir-held'))


@pytest.mark.parametrize('damage', ['kind', 'path', 'files', 'bytes', 'scopes', 'unknown-unproved'])
def test_retained_history_exceptions_cannot_expand_or_change_source(damage):
    value = history_value()
    if damage == 'kind': value['roots'][0]['kind'] = 'ANOTHER_UNPROVED'
    elif damage == 'path': value['roots'][0]['path'] += '-other'
    elif damage == 'files': value['members'].pop(0)
    elif damage == 'bytes': value['members'][0]['bytes'] += 1
    elif damage == 'scopes': value['members'][0]['scopes'] = ['test-1']
    else: value['roots'][-1]['kind'] += '_UNPROVED'
    with pytest.raises(retire.RetirementError): retire.selected_scope('cold-store-history-v2', value)


def test_all_hashes_and_live_nonce_precede_first_same_handle_deletion(scope):
    result = apply(scope); events = scope.events
    first = next(i for i, event in enumerate(events) if event[0] == 'delete-held')
    assert len([event for event in events[:first] if event[0] == 'hash']) == 2
    assert len([event for event in events[:first] if event[0] == 'directory-preflight']) == 2
    assert len([event for event in events[:first] if event[0] == 'live-ssh-proof']) == 1
    assert events[first - 2][0:2] == ('audit', 'FILE_DELETE_INTENT') and events[first - 1][0] == 'verify'
    assert len(events[next(i for i, event in enumerate(events) if event[0] == 'live-ssh-proof')][1]) == 64
    dirs = [event[1] for event in events if event[0] == 'empty-dir-held']
    assert dirs == ['work/frozen/memory/empty', 'work/frozen/memory']
    assert result['filesDeleted'] == 2 and result['directoriesRemoved'] == 2 and result['entireProfileRetired']
    assert not scope.backend.held


@pytest.mark.parametrize('failure', ['last-hash', 'directory', 'held-open', 'tracked', 'active', 'missing-current',
                                     'missing-custody', 'selected-count', 'live-ssh', 'forged-proof', 'expired-proof'])
def test_complete_preflight_and_authenticated_custody_are_required_before_any_delete(scope, failure):
    if failure == 'last-hash': scope.backend.fail_hash = scope.value['members'][-1]['path']
    elif failure == 'directory': scope.backend.check_directories = lambda value: retire.need(False, 'SOURCE_MEMBERSHIP_CHANGED')
    elif failure == 'held-open':
        @contextmanager
        def denied(value):
            raise retire.RetirementError('ACTIVE_SOURCE_OWNER_OR_ACCESS_BLOCKED'); yield
        scope.backend.hold = denied
    elif failure == 'tracked': scope.backend.tracked = {scope.value['members'][0]['path']}
    elif failure == 'active': scope.backend.active_references = lambda value: retire.need(False, 'ACTIVE_LOCAL_ROOT_REFERENCE_REFUSED')
    elif failure == 'missing-current': scope.plan['current'] = None
    elif failure == 'missing-custody': scope.plan['custody'] = None
    elif failure == 'selected-count': scope.plan['selectedCounts'] = {**scope.plan['selectedCounts'], 'files': 1}
    elif failure == 'live-ssh': scope.attestor.failure = True
    elif failure == 'forged-proof': scope.attestor.damage = True
    else: scope.cold.expired = True
    with pytest.raises(retire.RetirementError): apply(scope)
    assert not any(event[0] in ('delete-held', 'empty-dir-held') for event in scope.events)


@pytest.mark.parametrize('intent', ['FILE_DELETE_INTENT', 'EMPTY_DIRECTORY_INTENT'])
def test_proof_is_rechecked_after_durable_intent_fsync_before_disposition(scope, intent):
    scope.audit.callback = lambda event: setattr(scope.cold, 'expired', True) if event == intent else None
    with pytest.raises(retire.RetirementError): apply(scope)
    deleted = [event for event in scope.events if event[0] == 'delete-held']
    assert len(deleted) == (0 if intent == 'FILE_DELETE_INTENT' else 2)
    assert not any(event[0] == 'empty-dir-held' for event in scope.events)


@pytest.mark.parametrize('failure', ['second-disposition', 'directory-unknown-content', 'late-file-identity'])
def test_partial_failure_stops_at_exact_member_and_never_recurses_or_auto_resumes(scope, failure):
    if failure == 'second-disposition': scope.backend.fail_delete = scope.value['members'][1]['path']
    elif failure == 'directory-unknown-content': scope.backend.fail_directory = 'work/frozen/memory/empty'
    else:
        scope.audit.callback = lambda event: setattr(scope.backend, 'fail_verify', scope.value['members'][1]['path']) if event == 'FILE_DELETED' else None
    with pytest.raises(retire.RetirementError): apply(scope)
    partial = [event[2] for event in scope.events if event[0:2] == ('audit', 'PARTIAL_OR_REFUSED')][-1]
    assert partial['filesDeleted'] == (2 if failure == 'directory-unknown-content' else 1)
    assert partial['directoriesRemoved'] == 0 and not partial['automaticResumeAllowed']
    assert partial['unconfirmedFileDispositions'] == (1 if failure == 'second-disposition' else 0)
    assert partial['unconfirmedDirectoryDispositions'] == (1 if failure == 'directory-unknown-content' else 0)
    assert partial['requiresOwnIntentReconciliation'] and not scope.backend.held
    assert not any(event[0:2] == ('audit', 'COMPLETED') for event in scope.events)


def test_expired_monotonic_window_refuses_even_if_wall_clock_was_rolled_back(scope, monkeypatch):
    ticks = iter([100.0, 400.0]); monkeypatch.setattr(retire.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(retire.RetirementError, match='MONOTONIC_WINDOW'): apply(scope)
    assert not any(event[0] == 'delete-held' for event in scope.events)


def controlled_clock(scope, monkeypatch, *, monotonic_moves=True):
    origin = scope.cold.now
    monkeypatch.setattr(retire.time, 'monotonic', lambda:
                        (scope.cold.now - origin).total_seconds() if monotonic_moves else 0.0)


def test_periodic_fresh_challenges_keep_all_source_handles_without_repeating_preflight(scope, monkeypatch):
    controlled_clock(scope, monkeypatch)
    scope.audit.callback = lambda event: setattr(scope.cold, 'now', scope.cold.now + dt.timedelta(seconds=130)) if event == 'FILE_DELETED' else None
    result = apply(scope)
    proofs = [event[2]['attestation'] for event in scope.events if event[0:2] == ('audit', 'FRESH_CUSTODY_PROOF')]
    assert len(proofs) == 3 and len({row['nonce'] for row in proofs}) == 3
    for proof in proofs:
        assert proof['current'] == scope.plan['current'] and proof['custody'] == scope.plan['custody']
        assert (scope.cold.attestation_time(proof['expiresAtUtc']) - scope.cold.attestation_time(proof['issuedAtUtc'])).total_seconds() == 300
    assert len([event for event in scope.events if event[0] == 'held-all']) == 1
    assert len([event for event in scope.events if event[0] == 'hash']) == 2
    assert result['filesDeleted'] == 2 and result['directoriesRemoved'] == 2


def test_near_wall_deadline_refreshes_even_before_monotonic_interval(scope, monkeypatch):
    controlled_clock(scope, monkeypatch, monotonic_moves=False)
    shifted = []
    def after_first_delete(event):
        if event == 'FILE_DELETED' and not shifted:
            shifted.append(True); scope.cold.now += dt.timedelta(seconds=241)
    scope.audit.callback = after_first_delete
    apply(scope)
    assert len([event for event in scope.events if event[0] == 'live-ssh-proof']) == 2


@pytest.mark.parametrize('damage', ['ssh', 'current', 'custody', 'replayed-nonce', 'expired', 'archive-sha'])
def test_refresh_cannot_change_binding_reuse_old_nonce_or_fall_back_after_failure(scope, monkeypatch, damage):
    controlled_clock(scope, monkeypatch)
    original_fetch = scope.attestor.fetch; calls = []
    def fetch(plan, nonce):
        value = copy.deepcopy(original_fetch(plan, nonce)); calls.append(nonce)
        if len(calls) == 1: return value
        if damage == 'ssh': raise retire.RetirementError('AUTHENTICATED_LIVE_SERVER_ATTESTATION_REQUIRED')
        if damage == 'current': value['current']['sourceSha256'] = '0' * 64
        elif damage == 'custody': value['custody']['release'] = 'ci-1-' + 'f' * 12
        elif damage == 'replayed-nonce': value['nonce'] = calls[0]
        elif damage == 'expired': value['expiresAtUtc'] = value['issuedAtUtc']
        else: value['custody']['archiveSha256'] = '0' * 64
        return value
    scope.attestor.fetch = fetch
    scope.audit.callback = lambda event: setattr(scope.cold, 'now', scope.cold.now + dt.timedelta(seconds=130)) if event == 'FILE_DELETED' else None
    with pytest.raises(retire.RetirementError): apply(scope)
    assert len(calls) == 2 and calls[0] != calls[1]
    assert len([event for event in scope.events if event[0] == 'delete-held']) == 1
    assert not any(event[0] == 'empty-dir-held' for event in scope.events)
    assert not scope.backend.held


@pytest.mark.parametrize('intent', ['FILE_DELETE_INTENT', 'EMPTY_DIRECTORY_INTENT'])
def test_intent_fsync_stall_requires_new_live_proof_before_next_disposition(scope, monkeypatch, intent):
    controlled_clock(scope, monkeypatch); shifted = []
    def stall_once(event):
        if event == intent and not shifted:
            shifted.append(True); scope.cold.now += dt.timedelta(seconds=301)
    scope.audit.callback = stall_once
    result = apply(scope)
    intent_index = next(i for i, event in enumerate(scope.events) if event[0:2] == ('audit', intent))
    tail = scope.events[intent_index + 1:]
    assert tail[0][0] == 'live-ssh-proof' and tail[1][0:2] == ('audit', 'FRESH_CUSTODY_PROOF')
    assert result['filesDeleted'] == 2 and result['directoriesRemoved'] == 2


def test_renewal_audit_stall_cannot_authorize_a_delete_with_expired_new_proof(scope, monkeypatch):
    controlled_clock(scope, monkeypatch)
    scope.audit.callback = lambda event: setattr(scope.cold, 'now', scope.cold.now + dt.timedelta(seconds=301)) if event == 'FRESH_CUSTODY_PROOF' else None
    with pytest.raises(retire.RetirementError): apply(scope)
    assert not any(event[0] in ('delete-held', 'empty-dir-held') for event in scope.events)


def test_nonce_generator_reuse_refuses_refresh_without_reusing_prior_authority(scope, monkeypatch):
    controlled_clock(scope, monkeypatch)
    monkeypatch.setattr(retire.secrets, 'token_hex', lambda size: '7' * 64)
    scope.audit.callback = lambda event: setattr(scope.cold, 'now', scope.cold.now + dt.timedelta(seconds=130)) if event == 'FILE_DELETED' else None
    with pytest.raises(retire.RetirementError, match='NONCE_REUSE_REFUSED'): apply(scope)
    assert len([event for event in scope.events if event[0] == 'live-ssh-proof']) == 1
    assert len([event for event in scope.events if event[0] == 'delete-held']) == 1


@pytest.mark.parametrize('raw', [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'])
def test_control_json_refuses_duplicate_or_nonfinite_claims(raw):
    with pytest.raises(retire.RetirementError): retire.decode_control(raw)


def test_live_attestor_authenticates_only_pinned_peer_and_fixed_helper_bytes(scope, tmp_path, monkeypatch):
    key = tmp_path / 'dummy-key'; key.write_bytes(b'not a private key')
    known = tmp_path / 'dummy-known-hosts'; known.write_bytes(b'not real host keys')
    args = SimpleNamespace(profile=PROFILE, ssh_host='60.205.59.129', ssh_user='ecs-user', ssh_port=22,
        ssh_key=key, known_hosts=known, remote_root='/home/ecs-user/doorhandle-ci')
    calls = []; nonce = '9' * 64
    def run(command, **kwargs):
        calls.append((command, kwargs))
        value = proof_for(scope.plan, nonce, scope.cold.utc_now())
        return SimpleNamespace(returncode=0, stdout=retire.encoded(value) + b'\n')
    monkeypatch.setattr(retire, 'canonical_control', lambda path: path)
    monkeypatch.setattr(retire.shutil, 'which', lambda _: 'ssh')
    monkeypatch.setattr(retire.subprocess, 'run', run)
    assert retire.LiveAttestor(scope.cold, args).fetch(scope.plan, nonce)['nonce'] == nonce
    command, kwargs = calls[0]
    for option in ('StrictHostKeyChecking=yes', 'HostKeyAlias=doorhandle-bj', 'GlobalKnownHostsFile=NUL',
                   'IdentitiesOnly=yes', 'PermitLocalCommand=no', 'ClearAllForwardings=yes'):
        assert option in command
    assert command[1:3] == ['-F', 'NUL'] and str(known) in next(x for x in command if x.startswith('UserKnownHostsFile='))
    assert 'sha256sum ' in command[-1] and scope.plan['coldHelperSha256'] in command[-1]
    assert 'fresh-retirement-attest' in command[-1] and '--nonce ' + nonce in command[-1]
    assert '--source-snapshot-directory ' in command[-1] and kwargs['timeout'] == 300


@pytest.mark.parametrize('damage', ['exit', 'empty', 'multiline', 'oversize', 'duplicate'])
def test_live_ssh_failure_or_unbounded_ambiguous_response_has_no_authority(scope, tmp_path, monkeypatch, damage):
    path = tmp_path / 'dummy-control'; path.write_bytes(b'dummy')
    args = SimpleNamespace(profile=PROFILE, ssh_host='60.205.59.129', ssh_user='ecs-user', ssh_port=22,
                           ssh_key=path, known_hosts=path, remote_root='/home/ecs-user/doorhandle-ci')
    code = 255 if damage == 'exit' else 0
    raw = {'empty': b'', 'multiline': b'{}\n{}\n', 'oversize': b'x' * 16385,
           'duplicate': b'{"nonce":1,"nonce":2}'}.get(damage, b'{}')
    monkeypatch.setattr(retire, 'canonical_control', lambda path: path)
    monkeypatch.setattr(retire.shutil, 'which', lambda _: 'ssh')
    monkeypatch.setattr(retire.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=code, stdout=raw))
    with pytest.raises(retire.RetirementError): retire.LiveAttestor(scope.cold, args).fetch(scope.plan, '9' * 64)


def test_plan_is_default_and_never_initializes_native_or_network_backend(scope, tmp_path, monkeypatch, capsys):
    utility = SimpleNamespace(write_json=lambda path, value: path.write_bytes(retire.encoded(value)))
    scope.cold.utility = lambda: utility
    scope.plan['unprovedRootIds'] = []
    monkeypatch.setattr(retire, 'cold_module', lambda: scope.cold)
    monkeypatch.setattr(retire, 'make_plan', lambda *args: (scope.plan, scope.value))
    class PlanAudit(MemoryAudit):
        def __init__(self, *args): super().__init__(scope.events); self.directory = tmp_path
        def close(self): pass
    monkeypatch.setattr(retire, 'Audit', PlanAudit)
    def denied(*args): pytest.fail('Default plan must not reach Windows or SSH')
    monkeypatch.setattr(retire, 'WindowsBackend', denied); monkeypatch.setattr(retire, 'LiveAttestor', denied)
    assert retire.main(['--profile', PROFILE, '--inventory', 'ignored', '--output', 'ignored']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['status'] == 'PLAN_ONLY' and output['originalFilesDeleted'] == 0


def test_apply_requires_all_reviewed_plan_and_cloud_control_arguments(scope, monkeypatch, capsys):
    monkeypatch.setattr(retire, 'cold_module', lambda: scope.cold)
    monkeypatch.setattr(retire, 'load_plan', lambda *args: pytest.fail('Incomplete apply cannot load or change originals'))
    assert retire.main(['--profile', PROFILE, '--inventory', 'ignored', '--output', 'ignored', '--apply',
                        '--ssh-host', '192.0.2.10']) == 1
    assert json.loads(capsys.readouterr().err)['code'] == 'EXPLICIT_WINDOWS_APPLY_PLAN_AND_CLOUD_CONTROLS_REQUIRED'


@pytest.mark.parametrize('host', [None, ''])
def test_apply_never_uses_a_previous_ecs_address_when_current_host_is_not_supplied(scope, monkeypatch, capsys, host):
    monkeypatch.setattr(retire, 'cold_module', lambda: scope.cold)
    monkeypatch.setattr(retire, 'load_plan', lambda *args: pytest.fail('No current endpoint cannot reach apply preflight'))
    args = ['--profile', PROFILE, '--inventory', 'ignored', '--output', 'ignored', '--apply']
    if host is not None: args += ['--ssh-host', host]
    assert retire.main(args) == 1
    assert json.loads(capsys.readouterr().err)['code'] == 'EXPLICIT_CURRENT_ECS_SSH_HOST_REQUIRED'


def test_disposition_uses_original_handle_and_one_byte_boolean_without_path_delete():
    seen = []
    backend = retire.WindowsBackend.__new__(retire.WindowsBackend)
    import ctypes
    class Disposition(ctypes.Structure): _fields_ = [('DeleteFile', ctypes.c_ubyte)]
    backend.disposition = Disposition
    backend.api = SimpleNamespace(SetFileInformationByHandle=lambda handle, kind, value, size:
        seen.append(('dispose', handle, kind, size, ctypes.cast(value, ctypes.POINTER(Disposition)).contents.DeleteFile)) or 1,
        CloseHandle=lambda handle: seen.append(('close', handle)) or 1)
    backend.dispose(2468)
    assert seen == [('dispose', 2468, 4, 1, 1), ('close', 2468)]
