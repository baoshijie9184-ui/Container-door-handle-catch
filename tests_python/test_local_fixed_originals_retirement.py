"""ECS-only fixed-manifest/fake-backend contracts; no native deletion or SSH."""
import copy
from contextlib import contextmanager
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests_python.test_local_cold_retirement import FakeBackend, FakeCold, FakeAttestor, MemoryAudit


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('fixed_original_retirement_contract', ROOT / 'script/jenkins/retire-local-fixed-originals.py')
fixed = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(fixed)
core = fixed.load('retire-local-cold-stores.py')
PROFILE = 'legacy-project-originals-v1'


@pytest.fixture
def packet(monkeypatch):
    members = [{'sourcePath': fixed.ROOT + r'\memory_service\chroma_db\chroma.sqlite3', 'path': 'personal_chroma/chroma.sqlite3', 'bytes': 1, 'sha256': 'a' * 64},
        {'sourcePath': fixed.ROOT + r'\work\middlewares\kafka-data\events\0.log', 'path': 'legacy_kafka/events/0.log', 'bytes': 2, 'sha256': 'b' * 64},
        {'sourcePath': fixed.RETAINED_C_HISTORY, 'path': 'legacy_history/history.db', 'bytes': 65536, 'sha256': 'c' * 64}]
    def seal(rows): return json.dumps({'files': rows}, sort_keys=True).encode()
    raw = seal(members)
    recipe = {'manifestSha256': fixed.sha(raw), 'members': 3, 'selected': 2, 'bytes': 65539, 'retained': 1}
    monkeypatch.setattr(fixed, 'RECIPES', {PROFILE: recipe})
    return SimpleNamespace(rows=members, raw=raw, seal=seal, recipe=recipe)


def reseal(packet):
    packet.raw = packet.seal(packet.rows); packet.recipe['manifestSha256'] = fixed.sha(packet.raw)


@pytest.fixture
def scope(packet):
    selected, retained = fixed.select_manifest(PROFILE, packet.raw)
    members = [{**row, 'fingerprint': [7, i + 10, row['bytes'], 40, 50, 1, 0o100600, 32]} for i, row in enumerate(selected)]
    plan = {'profile': PROFILE, 'manifestSha256': packet.recipe['manifestSha256'], 'members': members, 'retained': retained,
            'current': {'release': 'ci-99-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64},
            'custody': {'release': 'ci-97-' + 'c' * 12}}
    events = []; proof = FakeCold(); backend = FakeBackend(events); attestor = FakeAttestor(events, proof)
    return SimpleNamespace(plan=plan, selected=selected, events=events, proof=proof, backend=backend,
                           attestor=attestor, audit=MemoryAudit(events))


def apply(scope): return fixed.apply_plan(scope.plan, core, scope.proof, scope.backend, scope.attestor, scope.audit)


def test_fixed_legacy_selects_only_d_project_and_preserves_c_history_without_access(packet, monkeypatch):
    monkeypatch.setattr(Path, 'lstat', lambda *_: pytest.fail('Manifest selection must not inspect any source'))
    selected, retained = fixed.select_manifest(PROFILE, packet.raw)
    assert len(selected) == 2 and retained == [{'sourcePath': fixed.RETAINED_C_HISTORY,
        'reason': 'C_DRIVE_HISTORY_NEVER_ACCESSED', 'bytes': 65536}]
    assert {r['path'] for r in selected} == {'memory_service/chroma_db/chroma.sqlite3', 'work/middlewares/kafka-data/events/0.log'}


def test_unreviewed_raw_manifest_cannot_select_files_even_if_json_values_match(packet):
    with pytest.raises(ValueError, match='FIXED_RAW_MANIFEST_SHA'): fixed.select_manifest(PROFILE, packet.raw + b' ')


def test_additional_profile_admits_uploads_and_logs_without_admitting_c_history(packet, monkeypatch):
    name = 'additional-originals-v1'
    rows = [{'sourcePath': fixed.ROOT + r'\doorhandle-server\uploads\sample.jpg', 'bytes': 1, 'sha256': 'a' * 64},
            {'sourcePath': fixed.ROOT + r'\logs\backend.out.log', 'bytes': 2, 'sha256': 'b' * 64}]
    raw = packet.seal(rows); recipe = {'manifestSha256': fixed.sha(raw), 'members': 2, 'selected': 2, 'bytes': 3, 'retained': 0}
    monkeypatch.setitem(fixed.RECIPES, name, recipe)
    selected, retained = fixed.select_manifest(name, raw)
    assert len(selected) == 2 and retained == []
    rows[0] = copy.deepcopy(packet.rows[-1]); raw = packet.seal(rows); recipe['manifestSha256'] = fixed.sha(raw)
    with pytest.raises(ValueError, match='ONLY_FIXED_C_HISTORY'): fixed.select_manifest(name, raw)


@pytest.fixture
def residual_packet(packet, monkeypatch):
    name = 'residual-project-originals-v1'
    rows = [{'sourcePath': fixed.ROOT + r'\work\old-output\opaque.sql', 'bytes': 1, 'sha256': 'a' * 64},
            {'sourcePath': fixed.ROOT + r'\work\old-output\opaque.onnx', 'bytes': 2, 'sha256': 'b' * 64}]
    raw = packet.seal(rows)
    recipe = {'manifestSha256': fixed.sha(raw), 'members': 2, 'selected': 2, 'bytes': 3, 'retained': 0}
    monkeypatch.setitem(fixed.RECIPES, name, recipe)
    return SimpleNamespace(profile=name, rows=rows, raw=raw, recipe=recipe)


def residual_plan(scope, residual_packet):
    selected, retained = fixed.select_manifest(residual_packet.profile, residual_packet.raw)
    members = [{**row, 'fingerprint': [7, i + 10, row['bytes'], 40, 50, 1, 0o100600, 32]} for i, row in enumerate(selected)]
    scope.plan.update(profile=residual_packet.profile, manifestSha256=residual_packet.recipe['manifestSha256'],
                      members=members, retained=retained, **fixed.residual_bindings(residual_packet.profile))
    return members


def test_residual_scope_uses_frozen_manifest_and_a_separate_metadata_only_source_guard(residual_packet, monkeypatch):
    selected, retained = fixed.select_manifest(residual_packet.profile, residual_packet.raw)
    assert len(selected) == 2 and retained == []
    seen = []
    helper = SimpleNamespace(residual_repository_guard=lambda paths: seen.extend(paths))
    monkeypatch.setattr(fixed, 'load', lambda name: helper if name == 'preserve-local-artifacts.py' else pytest.fail('unexpected helper'))
    fixed.residual_source_guard(residual_packet.profile, selected)
    assert seen == [fixed.ROOT + '\\' + row['path'].replace('/', '\\') for row in selected]
    fixed.residual_source_guard('additional-originals-v1', selected)
    assert len(seen) == 2


def test_residual_fake_apply_holds_every_original_and_obtains_fresh_custody_before_disposition(scope, residual_packet, monkeypatch):
    members = residual_plan(scope, residual_packet)
    def guard(profile, rows):
        assert profile == residual_packet.profile and rows == members
        scope.events.append(('source-metadata-guard',))
    monkeypatch.setattr(fixed, 'residual_source_guard', guard)
    result = apply(scope)
    assert result['filesDeleted'] == 2 and result['directoriesRemoved'] == 0
    assert scope.events[0] == ('source-metadata-guard',)
    live = next(i for i, row in enumerate(scope.events) if row[0] == 'live-ssh-proof')
    first_delete = next(i for i, row in enumerate(scope.events) if row[0] == 'delete-held')
    assert len([row for row in scope.events[:live] if row[0] == 'hash']) == 2 and live < first_delete


@pytest.mark.parametrize('why', ['guard-code-changed', 'new-foreign-repository', 'new-nested-repository'])
def test_residual_source_guard_failures_refuse_before_any_native_source_handle(scope, residual_packet, monkeypatch, why):
    residual_plan(scope, residual_packet)
    if why == 'guard-code-changed': scope.plan['residualScopeHelperSha256'] = '0' * 64
    else:
        def reject(*unused): raise ValueError('SOURCE_REPOSITORY_SCOPE_CHANGED')
        monkeypatch.setattr(fixed, 'residual_source_guard', reject)
    with pytest.raises(ValueError): apply(scope)
    assert not scope.events


@pytest.fixture
def alias_packet(packet, monkeypatch):
    profile = 'pth-aliases-v1'
    rows = [{'member': fixed.MODEL_ORIGIN_MEMBER, 'sourcePath': fixed.ROOT + r'\work\cloud\pth-model\best_stg2.pth',
             'bytes': fixed.MODEL_BYTES, 'sha256': fixed.MODEL_SHA256},
            {'member': 'uploads/other.jpg', 'sourcePath': fixed.ROOT + r'\uploads\other.jpg', 'bytes': 1, 'sha256': 'b' * 64}]
    raw = packet.seal(rows)
    recipe = {'manifestSha256': fixed.sha(raw), 'members': 2, 'selected': 2, 'bytes': fixed.MODEL_BYTES + 1, 'retained': 0}
    monkeypatch.setitem(fixed.RECIPES, profile, recipe)
    return SimpleNamespace(profile=profile, rows=rows, raw=raw, recipe=recipe, seal=packet.seal)


def test_alias_profile_derives_only_two_explicit_paths_from_exact_sealed_model_origin(alias_packet):
    selected, retained = fixed.select_manifest(alias_packet.profile, alias_packet.raw)
    assert selected == [{'path': name, 'bytes': fixed.MODEL_BYTES, 'sha256': fixed.MODEL_SHA256} for name in fixed.MODEL_ALIASES]
    assert retained == [] and all('other.jpg' not in row['path'] for row in selected)
    resolver = fixed.StrictResolver(selected)
    assert resolver('best_stg2.pth') == fixed.ROOT + r'\best_stg2.pth'
    with pytest.raises(ValueError): resolver('work/cloud/pth-model/best_stg2.pth')


@pytest.mark.parametrize('damage', ['raw-sha', 'missing-origin', 'duplicate-origin', 'wrong-source-path', 'wrong-member', 'size', 'hash'])
def test_alias_source_never_falls_back_to_a_similar_filename_or_old_alias_report(alias_packet, damage):
    if damage == 'raw-sha': alias_packet.raw += b' '
    else:
        row = alias_packet.rows[0]
        if damage == 'missing-origin': alias_packet.rows.pop(0)
        elif damage == 'duplicate-origin': alias_packet.rows.append(copy.deepcopy(row))
        elif damage == 'wrong-source-path': row['sourcePath'] = fixed.ROOT + r'\best_stg2.pth'
        elif damage == 'wrong-member': row['member'] = 'model/best_stg2.pth'
        elif damage == 'size': row['bytes'] += 1
        else: row['sha256'] = 'e' * 64
        alias_packet.raw = alias_packet.seal(alias_packet.rows); alias_packet.recipe['manifestSha256'] = fixed.sha(alias_packet.raw)
    with pytest.raises(ValueError): fixed.select_manifest(alias_packet.profile, alias_packet.raw)


@pytest.mark.parametrize('damage', ['origin', 'model-reference', 'alias-path', 'alias-hash', 'manifest', 'retained'])
def test_alias_apply_requires_closed_plan_and_current_model_reference_before_any_file_handle(scope, alias_packet, damage):
    selected, retained = fixed.select_manifest(alias_packet.profile, alias_packet.raw)
    reference = {'sourcePath': '/srv/doorhandle/models/best_stg2.pth', 'sha256': fixed.MODEL_SHA256}
    scope.proof.model_expected_reference = lambda: reference
    members = [{**row, 'fingerprint': [7, i + 10, row['bytes'], 40, 50, 1, 0o100600, 32]} for i, row in enumerate(selected)]
    scope.plan.update(profile=alias_packet.profile, manifestSha256=alias_packet.recipe['manifestSha256'], members=members,
                      retained=retained, **fixed.alias_bindings(alias_packet.profile, scope.proof))
    if damage == 'origin': scope.plan['aliasOrigin'] = {}
    elif damage == 'model-reference': scope.plan['requiredServerModel'] = {'sourcePath': '/another/model.pth'}
    elif damage == 'alias-path': members[0]['path'] = 'uploads/unknown.pth'
    elif damage == 'alias-hash': members[0]['sha256'] = 'e' * 64
    elif damage == 'manifest': scope.plan['manifestSha256'] = 'e' * 64
    else: scope.plan['retained'] = [{'unknown': True}]
    with pytest.raises(ValueError): apply(scope)
    assert not scope.events


def test_two_aliases_cannot_be_retired_with_only_the_old_36_byte_custody_proof(scope, alias_packet, monkeypatch):
    proof = fixed.load('attest-fixed-originals.py')
    now = dt.datetime(2026, 11, 8, 0, 0, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(proof, 'utc_now', lambda: now)
    selected, retained = fixed.select_manifest(alias_packet.profile, alias_packet.raw)
    current = {'release': 'ci-99-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64,
               'identity': core.IDENTITY, 'verificationReceiptSha256': 'c' * 64}
    recipe = proof.PROFILES[alias_packet.profile]
    custody = {**current, 'release': 'ci-97-' + 'd' * 12, 'commit': 'd' * 40,
        'publicReceiptSha256': 'e' * 64, 'restoreReceiptSha256': 'f' * 64,
        'manifestSha256': recipe['MANIFEST_SHA256'], 'archiveSha256': '1' * 64,
        'archiveBytes': 100, 'files': recipe['FILES'], 'bytes': recipe['ORIGINAL_BYTES']}
    members = [{**row, 'fingerprint': [7, i + 10, row['bytes'], 40, 50, 1, 0o100600, 32]} for i, row in enumerate(selected)]
    scope.plan.update(profile=alias_packet.profile, manifestSha256=alias_packet.recipe['manifestSha256'],
                      current=current, custody=custody, members=members, retained=retained,
                      **fixed.alias_bindings(alias_packet.profile, proof))
    class OldCustodyOnly:
        def fetch(self, plan, nonce):
            value = {'kind': proof.ATTESTATION_KIND, 'schemaVersion': 1, 'status': 'CUSTODY_FRESHLY_ATTESTED',
                'profile': alias_packet.profile, 'nonce': nonce, 'current': current, 'custody': custody,
                'issuedAtUtc': now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                'expiresAtUtc': (now + dt.timedelta(seconds=300)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')}
            value['proofDigest'] = proof.sha(proof.encoded(value)); return value
    with pytest.raises(ValueError): fixed.apply_plan(scope.plan, core, proof, scope.backend, OldCustodyOnly(), scope.audit)
    assert len([e for e in scope.events if e[0] == 'hash']) == 2
    assert not any(e[0] == 'delete-held' for e in scope.events)


@pytest.mark.parametrize('damage', ['other-c-file', 'c-schema', 'outside-d-project', 'protected-checkout', 'jenkins', 'git',
                                  'shared-mysql', 'shared-redis', 'unc', 'traversal', 'ads', 'case-alias'])
def test_resealed_scope_changes_still_cannot_cross_project_or_shared_boundaries(packet, damage):
    replacements = {'other-c-file': r'C:\Users\19771\other.db', 'outside-d-project': r'D:\OtherProject\file.db',
        'protected-checkout': fixed.ROOT + r'\work\ecs-only-20261105\micro-followup\checkout\private.db',
        'jenkins': fixed.ROOT + r'\work\jenkins\control.db', 'git': fixed.ROOT + r'\.git\index',
        'shared-mysql': fixed.ROOT + r'\work\middlewares\mysql\data\ibdata1',
        'shared-redis': fixed.ROOT + r'\work\middlewares\redis\dump.rdb', 'unc': r'\\server\share\x.db',
        'traversal': fixed.ROOT + r'\work\x\..\private.db', 'ads': fixed.ROOT + r'\logs\x:stream'}
    if damage == 'c-schema': packet.rows[-1]['path'] = 'other/history.db'
    elif damage == 'case-alias': packet.rows[1]['sourcePath'] = packet.rows[0]['sourcePath'].upper()
    else: packet.rows[0]['sourcePath'] = replacements[damage]
    reseal(packet)
    with pytest.raises(ValueError): fixed.select_manifest(PROFILE, packet.raw)


@pytest.mark.parametrize('damage', ['omitted', 'extra', 'wrong-bytes', 'boolean-bytes', 'wrong-sha', 'new-profile'])
def test_fixed_counts_original_bytes_and_member_digests_are_closed(packet, damage):
    profile = PROFILE
    if damage == 'omitted': packet.rows.pop(0)
    elif damage == 'extra': packet.rows.append(copy.deepcopy(packet.rows[0]))
    elif damage == 'wrong-bytes': packet.rows[0]['bytes'] += 1
    elif damage == 'boolean-bytes': packet.rows[0]['bytes'] = True
    elif damage == 'wrong-sha': packet.rows[0]['sha256'] = 'not-a-sha'
    else: profile = 'unknown-expanded-profile'
    reseal(packet)
    with pytest.raises(ValueError): fixed.select_manifest(profile, packet.raw)


def test_resolver_admits_exact_members_and_lock_parents_without_cold_work_only_restriction(scope):
    resolver = fixed.StrictResolver(scope.plan['members'])
    assert resolver('memory_service/chroma_db/chroma.sqlite3') == fixed.ROOT + r'\memory_service\chroma_db\chroma.sqlite3'
    assert resolver('memory_service/chroma_db') == fixed.ROOT + r'\memory_service\chroma_db'
    assert resolver('work/middlewares/kafka-data/events') == fixed.ROOT + r'\work\middlewares\kafka-data\events'
    with pytest.raises(ValueError, match='OUTSIDE_FIXED'): resolver('memory_service/chroma_db/unknown.sqlite3')
    with pytest.raises(ValueError, match='OUTSIDE_FIXED'): resolver('best_stg2.pth')


def test_fixed_chroma_or_kafka_root_itself_can_be_held_as_parent_without_admitting_siblings():
    resolver = fixed.StrictResolver([{'path': 'work/middlewares/chroma/chroma.sqlite3'},
                                     {'path': 'work/middlewares/kafka-data/meta.properties'}])
    assert resolver('work/middlewares/chroma') == fixed.ROOT + r'\work\middlewares\chroma'
    assert resolver('work/middlewares/kafka-data') == fixed.ROOT + r'\work\middlewares\kafka-data'
    with pytest.raises(ValueError): resolver('work/middlewares/mysql')


@pytest.mark.parametrize('damage', ['fingerprint-omitted', 'zero-id', 'duplicate-id', 'size', 'hardlink', 'reparse', 'directory',
                                  'metadata-type', 'member-path', 'member-sha', 'row-extra'])
def test_plan_cannot_change_selected_files_or_invent_permissive_identity(scope, damage):
    rows = copy.deepcopy(scope.plan['members'])
    if damage == 'fingerprint-omitted': rows[0].pop('fingerprint')
    elif damage == 'zero-id': rows[0]['fingerprint'][1] = 0
    elif damage == 'duplicate-id': rows[1]['fingerprint'][:2] = rows[0]['fingerprint'][:2]
    elif damage == 'size': rows[0]['fingerprint'][2] += 1
    elif damage == 'hardlink': rows[0]['fingerprint'][5] = 2
    elif damage == 'reparse': rows[0]['fingerprint'][7] |= 0x400
    elif damage == 'directory': rows[0]['fingerprint'][6] = 0o40700
    elif damage == 'metadata-type': rows[0]['fingerprint'][3] = True
    elif damage == 'member-path': rows[0]['path'] = 'uploads/unknown.jpg'
    elif damage == 'member-sha': rows[0]['sha256'] = 'e' * 64
    else: rows[0]['allowMissing'] = True
    with pytest.raises(ValueError): fixed.validate_observations(scope.selected, rows)


def test_all_fresh_hashes_and_live_proof_precede_first_delete_and_no_directory_is_removed(scope):
    def hold(value):
        assert value['directories'] == []
        assert all(not str(r['path']).lower().startswith('c:') for r in value['members'])
        return FakeBackend.hold(scope.backend, value)
    scope.backend.hold = hold
    result = apply(scope)
    first = next(i for i, event in enumerate(scope.events) if event[0] == 'delete-held')
    assert len([e for e in scope.events[:first] if e[0] == 'hash']) == 2
    assert len([e for e in scope.events[:first] if e[0] == 'live-ssh-proof']) == 1
    assert scope.events[first - 2][0:2] == ('audit', 'FILE_DELETE_INTENT') and scope.events[first - 1][0] == 'verify'
    assert result['filesDeleted'] == 2 and result['directoriesRemoved'] == 0 and result['allDirectoriesRetained']
    assert result['retained'] == scope.plan['retained']
    assert not any(e[0] == 'empty-dir-held' for e in scope.events)


@pytest.mark.parametrize('damage', ['hash', 'tracked', 'active', 'open-owner', 'identity', 'missing-current', 'missing-custody', 'ssh', 'proof'])
def test_preflight_failure_never_deletes_any_original(scope, damage):
    if damage == 'hash': scope.backend.fail_hash = scope.plan['members'][-1]['path']
    elif damage == 'tracked': scope.backend.tracked.add(scope.plan['members'][0]['path'].lower())
    elif damage == 'active': scope.backend.active_references = lambda _: fixed.need(False, 'ACTIVE_OWNER')
    elif damage == 'open-owner': scope.backend.hold = lambda _: fixed.need(False, 'ACTIVE_HANDLE')
    elif damage == 'identity': scope.backend.fail_verify = scope.plan['members'][0]['path']
    elif damage == 'missing-current': scope.plan['current'] = None
    elif damage == 'missing-custody': scope.plan['custody'] = None
    elif damage == 'ssh': scope.attestor.failure = True
    else: scope.attestor.damage = True
    with pytest.raises(ValueError): apply(scope)
    assert not any(e[0] in ('delete-held', 'empty-dir-held') for e in scope.events)


def test_owned_partial_disposition_retains_remaining_files_and_prohibits_replay(scope):
    scope.backend.fail_delete = scope.plan['members'][1]['path']
    with pytest.raises(ValueError): apply(scope)
    event = [e[2] for e in scope.events if e[0:2] == ('audit', 'PARTIAL_OR_REFUSED')][-1]
    assert event['confirmedFilesDeleted'] == 1 and event['fileDispositionAttempts'] == 2
    assert event['unconfirmedFileDispositions'] == 1 and not event['automaticResumeAllowed']
    assert not scope.backend.held


def test_plan_observes_all_identities_and_hashes_but_never_deletes_or_fetches_cloud(scope, packet, tmp_path, monkeypatch):
    manifest = tmp_path / 'synthetic-manifest.json'; manifest.write_bytes(packet.raw)
    monkeypatch.setattr(core, 'canonical_control', lambda path: Path(path))
    monkeypatch.setattr(fixed, 'observed_members', lambda *args: scope.plan['members'])
    monkeypatch.setattr(fixed, 'code_bindings', lambda *args: {'executorSha256': 'e' * 64})
    cold = SimpleNamespace(); proof = SimpleNamespace()
    plan = fixed.make_plan(PROFILE, manifest, None, None, core, cold, proof, lambda resolver: scope.backend)
    assert plan['status'] == 'PLAN_ONLY' and plan['originalFilesDeleted'] == 0 and plan['directoriesRemoved'] == 0
    assert len([event for event in scope.events if event[0] == 'hash']) == 2
    assert not any(event[0] in ('delete-held', 'empty-dir-held', 'live-ssh-proof') for event in scope.events)
    assert plan['current'] is None and plan['custody'] is None


@pytest.mark.parametrize('damage', ['plan-bytes', 'source-code', 'cloud-anchor', 'member-id'])
def test_apply_rechecks_reviewed_plan_source_and_cloud_bindings_before_native_backend(scope, packet, tmp_path, monkeypatch, damage):
    manifest = tmp_path / 'synthetic-manifest.json'; manifest.write_bytes(packet.raw)
    monkeypatch.setattr(core, 'canonical_control', lambda path: Path(path))
    monkeypatch.setattr(fixed, 'observed_members', lambda *args: scope.plan['members'])
    monkeypatch.setattr(fixed, 'code_bindings', lambda *args: {'executorSha256': 'e' * 64})
    monkeypatch.setattr(fixed, 'bindings', lambda *args: (scope.plan['current'], scope.plan['custody']))
    plan = fixed.make_plan(PROFILE, manifest, 'current', 'custody', core, SimpleNamespace(), SimpleNamespace(), lambda resolver: scope.backend)
    submitted = copy.deepcopy(plan)
    if damage == 'source-code': submitted['executorSha256'] = 'f' * 64
    elif damage == 'cloud-anchor': submitted['custody']['release'] = 'ci-1-' + 'd' * 12
    elif damage == 'member-id': submitted['members'][0]['fingerprint'][1] = 0
    monkeypatch.setattr(core, 'control', lambda _: (submitted, 'a' * 64))
    args = SimpleNamespace(plan='ignored', plan_sha256='b' * 64 if damage == 'plan-bytes' else 'a' * 64,
                           profile=PROFILE, manifest=manifest, current_receipt='current', custody_receipt='custody')
    with pytest.raises(ValueError): fixed.load_plan(args, core, SimpleNamespace(), SimpleNamespace())
    assert not any(event[0] == 'delete-held' for event in scope.events)


def test_refresh_after_intent_stall_preserves_fixed_bindings_and_remaining_exclusive_handles(scope, monkeypatch):
    origin = scope.proof.now; shifted = []
    monkeypatch.setattr(core.time, 'monotonic', lambda: (scope.proof.now - origin).total_seconds())
    def callback(event):
        if event == 'FILE_DELETE_INTENT' and not shifted:
            shifted.append(True); scope.proof.now += dt.timedelta(seconds=301)
    scope.audit.callback = callback
    assert apply(scope)['filesDeleted'] == 2
    assert len([e for e in scope.events if e[0] == 'live-ssh-proof']) == 2
    assert len([e for e in scope.events if e[0] == 'held-all']) == 1


def test_new_attestor_uses_fixed_original_helper_without_copying_ssh_transport(scope, tmp_path, monkeypatch):
    dummy = tmp_path / 'dummy'; dummy.write_bytes(b'not a key')
    profile = PROFILE; scope.proof.PROFILES = {profile: {'SNAPSHOT': 'legacy-source-snapshot'}}
    args = SimpleNamespace(profile=profile, ssh_host='192.0.2.10', ssh_user='ecs-user', ssh_port=22,
        ssh_key=dummy, known_hosts=dummy, remote_root='/home/ecs-user/doorhandle-ci')
    scope.plan['attestationHelperSha256'] = 'e' * 64; nonce = '9' * 64; calls = []
    from tests_python.test_local_cold_retirement import proof_for
    monkeypatch.setattr(core, 'canonical_control', lambda path: path)
    monkeypatch.setattr(core.shutil, 'which', lambda _: 'ssh')
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=core.encoded(proof_for(scope.plan, nonce, scope.proof.now)) + b'\n')
    monkeypatch.setattr(core.subprocess, 'run', run)
    result = core.LiveAttestor(scope.proof, args, helper_name='attest-fixed-originals.py').fetch(scope.plan, nonce)
    assert result['nonce'] == nonce and 'attest-fixed-originals.py' in calls[0][-1]
    assert scope.plan['attestationHelperSha256'] in calls[0][-1]
    assert 'StrictHostKeyChecking=yes' in calls[0] and 'GlobalKnownHostsFile=NUL' in calls[0]
    with pytest.raises(ValueError, match='FIXED_ATTESTATION_HELPER'): core.LiveAttestor(scope.proof, args, helper_name='../unreviewed.py')


def test_held_source_resolver_default_is_unchanged_and_custom_resolver_is_explicit():
    cold = fixed.load('preserve-cold-stores.py')
    assert cold.HeldSources({'members': []}).source_resolver is cold.safe_source
    resolver = lambda name: Path('/not-opened') / name
    assert cold.HeldSources({'members': []}, source_resolver=resolver).source_resolver is resolver
    with pytest.raises(Exception, match='EXPLICIT_SOURCE_RESOLVER'): cold.HeldSources({'members': []}, source_resolver=True)


def test_explicit_resolver_is_used_by_real_opaque_source_reader_on_ecs(tmp_path, monkeypatch):
    cold = fixed.load('preserve-cold-stores.py')
    source = tmp_path / 'opaque-original.bin'; body = b'opaque original bytes'; source.write_bytes(body)
    row = {'path': 'uploads/opaque-original.bin', 'bytes': len(body), 'sha256': fixed.sha(body),
           'fingerprint': cold.fingerprint(source.stat())}
    monkeypatch.setattr(cold, 'safe_source', lambda _: pytest.fail('A reviewed explicit resolver must be used'))
    resolver = lambda name: source if name == row['path'] else pytest.fail('Unknown source requested')
    with cold.HeldSources({'members': [row]}, source_resolver=resolver) as held:
        reader = held.reader(row['path']); assert reader.read(4096) == body and reader.read(4096) == b''
        held.verify_one(row)
        assert reader.bytes == len(body) and reader.checksum.hexdigest() == row['sha256']
    assert source.read_bytes() == body


def test_windows_backend_forwards_custom_resolver_and_delete_access_to_original_holder(tmp_path, monkeypatch):
    source = tmp_path / 'uploads/opaque.bin'; source.parent.mkdir(); source.write_bytes(b'opaque')
    fingerprint = fixed.load('preserve-cold-stores.py').fingerprint(source.stat())
    fingerprint[7] = 0  # Ordinary-file fixture without the read-only attribute.
    value = {'members': [{'path': 'uploads/opaque.bin', 'bytes': 6, 'sha256': fixed.sha(b'opaque'),
                          'fingerprint': fingerprint}], 'directories': []}
    resolver = lambda name: str(tmp_path / name)
    seen = []; closed = []
    @contextmanager
    def holder(actual, **options):
        seen.append((actual, options)); yield SimpleNamespace()
    backend = core.WindowsBackend.__new__(core.WindowsBackend)
    backend.cold = SimpleNamespace(HeldSources=holder)
    backend.source_resolver = resolver; backend.custom_source_resolver = True; backend.directories = {}
    backend.api = SimpleNamespace(CreateFileW=lambda *args: len(seen) + len(closed) + 123,
                                  CloseHandle=lambda handle: closed.append(handle) or 1)
    backend.final_path = lambda *args: None; backend.verify_file = lambda row: None
    monkeypatch.setattr(core, 'PROJECT_ROOT', str(tmp_path))
    with backend.hold(value): assert len(seen) == 1
    assert seen[0][0] is value and seen[0][1] == {'delete_access': True, 'source_resolver': resolver}
    assert closed and not backend.directories


def test_linux_cannot_enter_real_plan_or_apply_native_backend(capsys):
    assert fixed.os.name != 'nt'
    assert fixed.main(['--profile', PROFILE, '--manifest', 'not-opened', '--output', 'not-created']) == 1
    assert json.loads(capsys.readouterr().err)['status'] == 'REFUSED_OR_PARTIAL'
