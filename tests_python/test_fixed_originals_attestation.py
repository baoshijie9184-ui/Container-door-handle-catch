"""ECS-only synthetic fixed-source and opaque custody contracts; no live service."""
from contextlib import contextmanager
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


attest = load('fixed_originals_attestation_contract', 'script/jenkins/attest-fixed-originals.py')
legacy = load('fixed_originals_legacy_fixture', 'tests_python/test_jenkins_legacy_source_reuse.py')
additional = load('fixed_originals_additional_fixture', 'tests_python/test_local_artifact_custody.py')
cold = load('fixed_originals_pass_fixture', 'script/jenkins/preserve-cold-stores.py')


def put(path, raw):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(raw); path.chmod(0o600)
    return path


def put_json(path, value):
    return put(path, attest.encoded(value))


@pytest.fixture
def old_state(tmp_path, monkeypatch):
    state = legacy.support.state.__wrapped__(tmp_path, monkeypatch)
    return legacy.archive_state.__wrapped__(state, monkeypatch)


def build_custody_state(profile, old_state, tmp_path, monkeypatch):
    state = old_state
    work = state.root / 'verification' / legacy.support.CURRENT / 'checkout/work'
    work.mkdir(mode=0o700, parents=True); work.chmod(0o755)
    source = put(state.root / 'inbox' / legacy.support.CURRENT / 'source.tar.gz', b'opaque current fixed-source reference')
    current_record = {'release': legacy.support.CURRENT, 'commit': 'c' * 40, 'sourceSha256': attest.sha(source.read_bytes()),
        'identity': copy.deepcopy(legacy.support.IDENTITY), 'status': 'PASS', 'verificationExitCode': 0}
    receipt = put_json(work.parent.parent / 'verification-receipt.json', current_record)
    current = {key: current_record[key] for key in attest.CURRENT_FIELDS if key != 'verificationReceiptSha256'}
    current['verificationReceiptSha256'] = attest.sha(receipt.read_bytes())
    args = SimpleNamespace(root=str(state.root), tag=legacy.support.CURRENT, commit='c' * 40,
        source_sha256=current['sourceSha256'], expected_instance_id=current['identity']['instanceId'],
        expected_machine_id=current['identity']['machineId'], profile=profile, nonce='9' * 64, attestation_seconds=120)
    helpers = SimpleNamespace(root=state.root, checkout=work.parent, source=source, reuse=legacy.reuse,
        artifacts=additional.custody, cold=cold, cleanup=legacy.support.cleanup, verifier=legacy.support.remote,
        migration=state.migration)
    if profile == 'legacy-project-originals-v1':
        old, public = state.snapshot, state.public
    else:
        original_root = tmp_path / 'additional-fixture'; original_root.mkdir(mode=0o700)
        metadata_run = additional.custody.subprocess.run
        if profile == 'legacy-partial-transports-v1':
            originals = additional.originals.__wrapped__(original_root, monkeypatch)
            originals = additional.partial_transport_originals.__wrapped__(originals, monkeypatch)
        elif profile == 'remaining-system-data-v1':
            originals = additional.remaining_originals.__wrapped__(original_root, monkeypatch)
        elif profile == 'residual-project-originals-v1':
            originals = additional.residual_originals.__wrapped__(original_root, monkeypatch)
        else:
            originals = additional.originals.__wrapped__(original_root, monkeypatch)
        package = originals.parent / 'package'
        try:
            additional.custody.pack(originals.catalog, package)
        finally:
            if profile in ('residual-project-originals-v1', 'remaining-system-data-v1', 'legacy-partial-transports-v1'):
                # The synthetic Git dispatcher belongs only to local pack's
                # real metadata guard, never the later CI/old-custody chain.
                monkeypatch.setattr(additional.custody.subprocess, 'run', metadata_run)
        old_work = state.checkout / 'work'
        old_context = {'version': 1, 'kind': additional.custody.KIND, 'profile': additional.custody.PROFILE,
            'release': legacy.support.OLD, 'commit': state.record['commit'], 'sourceSha256': state.record['sourceSha256'],
            'identity': copy.deepcopy(legacy.support.IDENTITY),
            'verificationReceiptSha256': attest.sha((state.attempt / 'verification-receipt.json').read_bytes()),
            'catalogSha256': additional.custody.CATALOG_SHA256, 'files': additional.custody.FILE_COUNT,
            'bytes': additional.custody.ORIGINAL_BYTES}
        first_args = SimpleNamespace(source_receipt_sha256=None)
        for prefix, filename in (('manifest', 'custody.json'), ('archive', 'originals.tar')):
            setattr(first_args, prefix + '_sha256', attest.sha((package / filename).read_bytes()))
            setattr(first_args, prefix + '_bytes', (package / filename).stat().st_size)
        monkeypatch.setattr(additional.custody, 'admit', lambda _: (old_work, old_context))
        monkeypatch.setattr(additional.custody, 'resource_guard', lambda *_: None)
        additional.custody.prepare(first_args); additional.upload(package, old_work); additional.custody.verify_restore(first_args)
        old = old_work / additional.custody.SNAPSHOT
        public = additional.custody.read_json(old_work / additional.custody.PUBLIC)
        current_context = {**old_context, **current}
        monkeypatch.setattr(additional.custody, 'admit', lambda _: (work, current_context))
    args.source_snapshot_directory = str(old)
    fixed = {**attest.PROFILES[profile], 'FILES': public['files'], 'ORIGINAL_BYTES': public['bytes']}
    fixed['MANIFEST_SHA256'] = attest.sha((old / fixed['MANIFEST']).read_bytes())
    if profile in ('remaining-system-data-v1', 'legacy-partial-transports-v1'):
        fixed.update(CATALOG_SHA256=public['catalogSha256'], ARCHIVE_SHA256=public['archiveSha256'], ARCHIVE_BYTES=public['archiveBytes'])
    if profile == 'legacy-partial-transports-v1':
        fixed['MANIFEST_BYTES'] = (old / fixed['MANIFEST']).stat().st_size
    monkeypatch.setitem(attest.PROFILES, profile, fixed); helpers.fixed = fixed
    monkeypatch.setattr(attest, 'fixed_modules', lambda _: helpers)
    monkeypatch.setattr(attest, 'current_pass', lambda *_: copy.deepcopy(current))
    now = attest.dt.datetime(2026, 11, 8, 10, 30, tzinfo=attest.dt.timezone.utc)
    monkeypatch.setattr(attest, 'utc_now', lambda: now)
    public_file = (old if fixed['PUBLIC_IN_SNAPSHOT'] else old.parent) / fixed['PUBLIC']
    custody = attest.custody_projection(profile, public, attest.sha(public_file.read_bytes()))
    return SimpleNamespace(args=args, state=state, helpers=helpers, work=work, old=old, now=now,
        current=current, custody=custody, public_file=public_file)


@pytest.fixture(params=['legacy-project-originals-v1', 'additional-originals-v1', 'residual-project-originals-v1', 'remaining-system-data-v1'])
def custody_state(request, old_state, tmp_path, monkeypatch):
    return build_custody_state(request.param, old_state, tmp_path, monkeypatch)


def validate(value, state, **overrides):
    args = dict(profile=state.args.profile, nonce=state.args.nonce, expected_current=state.current,
                expected_custody=state.custody, now_utc=state.now)
    args.update(overrides)
    return attest.validate_retirement_attestation(value, **args)


@pytest.fixture
def remaining_state(old_state, tmp_path, monkeypatch):
    return build_custody_state('remaining-system-data-v1', old_state, tmp_path, monkeypatch)


def test_remaining_fixed_profile_is_the_actual_86_member_snapshot_not_a_wider_deletion_scope():
    fixed = attest.PROFILES['remaining-system-data-v1']
    assert (fixed['FILES'], fixed['ORIGINAL_BYTES'], fixed['ARCHIVE_BYTES']) == (86, 28695377, 28825600)
    assert fixed['MANIFEST_SHA256'] == '6c8c5c1f9db87f8aed0c5578ff9781f69e93cb85f318a8797c63e2a66a340842'
    assert fixed['CATALOG_SHA256'] == '0f92d397bed2b6f6a56a4dfec37d7c4bd6f41d195182b10604438ed10747baf4'
    assert fixed['MAX_ARCHIVE'] == 64 * 1024 ** 2 and fixed['MAX_MANIFEST'] == 2 * 1024 ** 2


def test_remaining_attestation_rehashes_every_independent_restore_and_keeps_all_bytes(remaining_state, monkeypatch):
    state = remaining_state; fixed = state.helpers.fixed; seen = []; previous = attest.file_digest
    def observed(path, *args, **kwargs):
        seen.append(Path(path)); return previous(path, *args, **kwargs)
    monkeypatch.setattr(attest, 'file_digest', observed)
    before = tree_bytes(state.state.root); value = attest.fresh_retirement_attest(state.args)
    assert validate(value, state) is value and tree_bytes(state.state.root) == before
    manifest = json.loads((state.old / fixed['MANIFEST']).read_bytes())
    assert all(state.old.parent / fixed['RESTORE'] / row['member'] in seen for row in manifest['files'])


@pytest.mark.parametrize('damage', ['changed', 'missing', 'extra', 'hardlink', 'symlink', 'mode', 'directory-mode'])
def test_remaining_restore_receipt_alone_cannot_replace_fresh_complete_member_bytes(remaining_state, damage):
    state = remaining_state; fixed = state.helpers.fixed
    manifest = json.loads((state.old / fixed['MANIFEST']).read_bytes())
    restore = state.old.parent / fixed['RESTORE']; target = restore / manifest['files'][0]['member']
    if damage == 'changed': target.write_bytes(target.read_bytes() + b'drift')
    elif damage == 'missing': target.unlink()
    elif damage == 'extra': put(restore / 'unreviewed.bin', b'extra')
    elif damage == 'hardlink': os.link(target, state.work / 'foreign-link.bin')
    elif damage == 'symlink':
        outside = put(state.work / 'foreign.bin', target.read_bytes()); target.unlink(); target.symlink_to(outside)
    elif damage == 'mode': target.chmod(0o644)
    else: target.parent.chmod(0o755)
    with pytest.raises(attest.AttestationError):
        attest.fresh_retirement_attest(state.args)


@pytest.mark.parametrize('field', ['archiveSha256', 'archiveBytes'])
def test_remaining_projection_keeps_the_exact_original_archive_pin(remaining_state, field):
    state = remaining_state; value = attest.fresh_retirement_attest(state.args)
    value['custody'][field] = 'e' * 64 if field.endswith('Sha256') else value['custody'][field] + 1
    expected = copy.deepcopy(value['custody']); resign(value)
    with pytest.raises(attest.AttestationError, match='REMAINING_FIXED_ARCHIVE_DRIFT'):
        validate(value, state, expected_custody=expected)


def test_remaining_empty_preserved_member_still_has_a_complete_zero_byte_hash_bound(tmp_path):
    old = tmp_path / 'snapshot'; old.mkdir(mode=0o700)
    manifest = put_json(old / 'custody.json', {'opaque': True})
    restore = tmp_path / 'restore'; restore.mkdir(mode=0o700)
    target = put(restore / 'empty.log', b''); put_json(restore / 'restore-receipt.json', {'status': 'RESTORED_VERIFIED'})
    rows = [{'member': 'empty.log', 'bytes': 0, 'sha256': attest.sha(b'')}]
    state = SimpleNamespace(fixed={'PUBLIC_PROFILE': 'remaining-system-data-v1', 'MANIFEST': 'custody.json',
        'MANIFEST_SHA256': attest.sha(manifest.read_bytes()), 'MAX_MANIFEST': 1024, 'RESTORE': 'restore'},
        artifacts=SimpleNamespace(read_json=lambda *_args, **_kwargs: {}, validate_manifest=lambda _: rows))
    assert attest.remaining_restored_bindings(state, old) == ((target, attest.sha(b''), 0),)
    assert attest.file_digest(target, 0, private=True)[:2] == (attest.sha(b''), 0)


@pytest.fixture
def partial_transport_state(old_state, tmp_path, monkeypatch):
    return build_custody_state('legacy-partial-transports-v1', old_state, tmp_path, monkeypatch)


def test_partial_transport_recipe_pins_only_the_actual_four_file_archive():
    fixed = attest.PROFILES['legacy-partial-transports-v1']
    assert (fixed['FILES'], fixed['ORIGINAL_BYTES'], fixed['MANIFEST_BYTES'], fixed['ARCHIVE_BYTES']) == (4, 155793058, 3583, 155801600)
    assert fixed['MANIFEST_SHA256'] == '7b9e2f51eb658b2eff8431b3b2fd5f003f1bfd9418e0947cd14c67ffbb12f6f2'
    assert fixed['CATALOG_SHA256'] == 'a2669cdf5cb129eadb62361e1de1658482dc002f8dc53b193c11dd5fd5a9e477'
    assert fixed['ARCHIVE_SHA256'] == '904d67de3b7a57bc5cf40c8f1e6894a2445fa867bf5c65dfa1e809e8c12f041b'
    assert fixed['MAX_ARCHIVE'] == 256 * 1024 ** 2 and fixed['MAX_MANIFEST'] == 64 * 1024


def test_partial_transport_attestation_rehashes_all_four_private_restores_before_accepting_custody(partial_transport_state, monkeypatch):
    state = partial_transport_state; fixed = state.helpers.fixed; seen = []; original = attest.file_digest
    def observed(path, *args, **kwargs):
        seen.append((Path(path), kwargs.get('private'))); return original(path, *args, **kwargs)
    monkeypatch.setattr(attest, 'file_digest', observed)
    before = tree_bytes(state.state.root); value = attest.fresh_retirement_attest(state.args)
    assert validate(value, state) is value and tree_bytes(state.state.root) == before
    manifest = json.loads((state.old / fixed['MANIFEST']).read_bytes())
    assert len(manifest['files']) == 4
    assert all((state.old.parent / fixed['RESTORE'] / row['member'], True) in seen for row in manifest['files'])
    inner_archives = [row for row in manifest['files'] if Path(row['member']).name == fixed['ARCHIVE']]
    assert len(inner_archives) == 2
    for row in inner_archives:
        target = state.old.parent / fixed['RESTORE'] / row['member']; raw = target.read_bytes()
        assert len(raw) == row['bytes'] and row['bytes'] != state.custody['archiveBytes']
        target.write_bytes(b'X' + raw[1:])
        with pytest.raises(attest.AttestationError, match='ORIGINALS_ATTESTATION_RAW_INPUT_CHANGED'):
            attest.fresh_retirement_attest(state.args)
        target.write_bytes(raw)
    target = state.old.parent / fixed['RESTORE'] / manifest['files'][0]['member']
    target.write_bytes(target.read_bytes() + b'drift')
    with pytest.raises(attest.AttestationError): attest.fresh_retirement_attest(state.args)


def test_partial_transport_projection_cannot_reseal_a_different_archive_or_size(partial_transport_state):
    state = partial_transport_state; original = attest.fresh_retirement_attest(state.args)
    for field in ('archiveSha256', 'archiveBytes'):
        value = copy.deepcopy(original)
        value['custody'][field] = 'e' * 64 if field.endswith('Sha256') else value['custody'][field] + 1
        expected = copy.deepcopy(value['custody']); resign(value)
        with pytest.raises(attest.AttestationError, match='PARTIAL_TRANSPORT_FIXED_ARCHIVE_DRIFT'):
            validate(value, state, expected_custody=expected)


def test_partial_transport_source_admission_uses_the_same_fixed_helper_closure(tmp_path, monkeypatch):
    source = fixed_source.__wrapped__(tmp_path, monkeypatch, SimpleNamespace(param='legacy-partial-transports-v1'))
    state = attest.fixed_modules(source.args)
    assert state.artifacts.PROFILE == 'legacy-partial-transports-v1'
    assert state.artifacts.CATALOG_SHA256 == state.fixed['CATALOG_SHA256']
    helper = source.checkout / 'script/jenkins/preserve-local-artifacts.py'
    helper.write_bytes(helper.read_bytes() + b'\n')
    with pytest.raises(attest.AttestationError, match='FIXED_ORIGINALS_RECIPE_CHANGED'):
        attest.fixed_modules(source.args)


@pytest.mark.parametrize('damage', ['kind', 'scope', 'controlsOnly', 'fullProjectVerified'])
def test_current_custody_attestor_never_accepts_a_control_only_result_as_project_pass(damage):
    identity = copy.deepcopy(legacy.support.IDENTITY)
    record = {'kind': 'doorhandle-ecs-ci', 'scope': 'source', 'release': 'ci-99-' + 'a' * 12,
              'commit': 'a' * 40, 'sourceSha256': 'b' * 64, 'identity': identity}
    record[damage] = {'kind': 'doorhandle-controls-only-source', 'scope': 'controls',
                      'controlsOnly': True, 'fullProjectVerified': False}[damage]
    state = SimpleNamespace(root=None, artifacts=SimpleNamespace(identity=lambda *_: identity),
        cold=SimpleNamespace(stopped_receipt=lambda *_args, **_kwargs: (record, 'c' * 64)), verifier=None, cleanup=None)
    args = SimpleNamespace(tag=record['release'], commit=record['commit'], source_sha256=record['sourceSha256'],
                           expected_instance_id=identity['instanceId'], expected_machine_id=identity['machineId'])
    with pytest.raises(attest.AttestationError, match='ACTUAL_PROJECT_PASS_NOT_CONTROLS_REQUIRED'):
        attest.current_pass(args, state)


def resign(value):
    value['proofDigest'] = attest.sha(attest.encoded({key: row for key, row in value.items() if key != 'proofDigest'}))


def tree_bytes(path):
    return {str(file.relative_to(path)): (attest.metadata(file.stat()), file.read_bytes() if file.is_file() else None)
            for file in path.rglob('*')}


def test_real_old_custody_chains_supply_fresh_readonly_projections(custody_state, monkeypatch):
    state = custody_state; before = tree_bytes(state.state.root)
    opened = Path.open
    def readonly(path, mode='r', *args, **kwargs):
        assert mode in ('r', 'rb'), 'Attestation may not write any evidence or restore data'
        return opened(path, mode, *args, **kwargs)
    def refuse(*_args, **_kwargs): pytest.fail('Attestation cannot restore, copy, or change resources')
    with monkeypatch.context() as guard:
        guard.setattr(Path, 'open', readonly)
        for name in ('mkdir', 'unlink', 'rmdir', 'write_bytes', 'write_text', 'chmod', 'rename', 'replace'):
            guard.setattr(Path, name, refuse)
        guard.setattr(legacy.reuse, 'write', refuse)
        guard.setattr(additional.custody, 'write_json', refuse)
        guard.setattr(state.state.migration, 'private_json', refuse)
        proof = attest.fresh_retirement_attest(state.args)
        assert validate(proof, state) is proof
    assert proof['current'] == state.current and proof['custody'] == state.custody
    assert set(proof['custody']) == set(attest.CUSTODY_FIELDS) and str(state.state.root) not in json.dumps(proof)
    assert tree_bytes(state.state.root) == before


def test_pure_projection_validator_never_reads_disk_or_imports_helpers(custody_state, monkeypatch):
    proof = attest.fresh_retirement_attest(custody_state.args)
    def refuse(*_args, **_kwargs): pytest.fail('Pure verification must not inspect filesystem or ECS')
    for name in ('load', 'owned', 'file_digest', 'fixed_modules', 'current_pass', 'old_snapshot'):
        monkeypatch.setattr(attest, name, refuse)
    monkeypatch.setattr(Path, 'open', refuse)
    assert validate(proof, custody_state) is proof


def test_replaced_open_handle_is_refused_before_the_first_byte_is_read(custody_state, monkeypatch):
    target = put(custody_state.work / 'opaque-original-control.json', b'opaque fixture bytes')
    replacement = put(custody_state.work / 'opaque-replacement-control.json', b'opaque fixture bytes')
    os.link(replacement, custody_state.work / 'synthetic-extra-hardlink.json')
    real_open, real_fdopen = os.open, os.fdopen
    def replaced_open(path, flags, *args, **kwargs):
        return real_open(replacement if Path(path) == target else path, flags, *args, **kwargs)
    @contextmanager
    def unreadable(fd, mode):
        with real_fdopen(fd, mode) as stream:
            def refuse(*_args): pytest.fail('Replaced or linked descriptor must be rejected before reading')
            yield SimpleNamespace(fileno=stream.fileno, read=refuse)
    monkeypatch.setattr(attest.os, 'open', replaced_open)
    monkeypatch.setattr(attest.os, 'fdopen', unreadable)
    with pytest.raises(attest.AttestationError, match='OPENED_FILE_ADMISSION_CHANGED'):
        attest.file_digest(target, 1024, private=True)


@pytest.mark.parametrize('damage', ['archive', 'manifest', 'public', 'restore-proof', 'same-build', 'future-build', 'private-mode'])
def test_original_old_snapshot_gates_refuse_drift_without_new_evidence(custody_state, damage):
    state = custody_state; fixed = attest.PROFILES[state.args.profile]
    if damage in ('archive', 'manifest'):
        file = state.old / fixed['ARCHIVE' if damage == 'archive' else 'MANIFEST']; file.write_bytes(file.read_bytes() + b'drift')
    elif damage == 'public':
        value = json.loads(state.public_file.read_bytes()); value['identity']['machineId'] = 'f' * 32
        state.public_file.write_bytes(attest.encoded(value))
    elif damage == 'restore-proof': (state.old.parent / fixed['RESTORE'] / 'restore-receipt.json').write_bytes(b'{}')
    elif damage == 'private-mode': state.public_file.chmod(0o644)
    else: state.args.tag = ('ci-70-' + 'a' * 12) if damage == 'same-build' else ('ci-69-' + 'a' * 12)
    before = tree_bytes(state.state.root)
    with pytest.raises(Exception): attest.fresh_retirement_attest(state.args)
    assert tree_bytes(state.state.root) == before


@pytest.mark.parametrize('damage', ['manifest', 'archive', 'public', 'restore-proof', 'current-pass', 'source'])
def test_raw_inputs_are_rehashed_after_the_complete_old_chain_was_admitted(custody_state, monkeypatch, damage):
    state = custody_state; previous = attest.old_snapshot; fixed = attest.PROFILES[state.args.profile]
    file = {'manifest': state.old / fixed['MANIFEST'], 'archive': state.old / fixed['ARCHIVE'], 'public': state.public_file,
        'restore-proof': state.old.parent / fixed['RESTORE'] / 'restore-receipt.json',
        'current-pass': state.work.parent.parent / 'verification-receipt.json', 'source': state.helpers.source}[damage]
    def changed(*args):
        result = previous(*args); file.write_bytes(file.read_bytes() + b'late drift'); return result
    monkeypatch.setattr(attest, 'old_snapshot', changed)
    with pytest.raises(attest.AttestationError, match='RAW_INPUT_CHANGED'): attest.fresh_retirement_attest(state.args)
    assert not list(state.work.iterdir())


@pytest.mark.parametrize('nonce', [None, '', 'a' * 63, 'A' * 64, 'g' * 64, True])
def test_bad_nonce_refuses_before_any_remote_observation(monkeypatch, nonce):
    monkeypatch.setattr(attest, 'fixed_modules', lambda _: pytest.fail('Invalid nonce cannot read server state'))
    with pytest.raises(attest.AttestationError, match='NONCE_REQUIRED'):
        attest.fresh_retirement_attest(SimpleNamespace(profile='additional-originals-v1', nonce=nonce))


@pytest.mark.parametrize('ttl', [0, -1, 301, True, 1.5, '120'])
def test_unbounded_or_untyped_ttl_refuses_before_any_remote_observation(monkeypatch, ttl):
    monkeypatch.setattr(attest, 'fixed_modules', lambda _: pytest.fail('Invalid lifetime cannot read server state'))
    with pytest.raises(attest.AttestationError, match='TTL_REQUIRED'):
        attest.fresh_retirement_attest(SimpleNamespace(profile='additional-originals-v1', nonce='9' * 64, attestation_seconds=ttl))


def test_complete_observation_must_finish_before_its_monotonic_deadline(custody_state, monkeypatch):
    ticks = iter([0.0, 120.0]); monkeypatch.setattr(attest.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(attest.AttestationError, match='OBSERVATION_EXPIRED'):
        attest.fresh_retirement_attest(custody_state.args)


@pytest.mark.parametrize('damage', ['digest', 'nonce', 'profile', 'extra', 'current', 'old-binding', 'same-build', 'identity',
    'fixed-manifest', 'boolean-files', 'archive-size', 'future', 'expired', 'ttl', 'fractional-ttl', 'timestamp', 'naive-clock'])
def test_live_output_still_requires_exact_challenge_context_fixed_recipe_and_time(custody_state, damage):
    state = custody_state; proof = attest.fresh_retirement_attest(state.args)
    expected_current, expected_old = copy.deepcopy(state.current), copy.deepcopy(state.custody); now = state.now
    if damage == 'digest': proof['custody']['archiveSha256'] = '0' * 64
    elif damage == 'nonce': proof['nonce'] = '8' * 64
    elif damage == 'profile': proof['profile'] = 'additional-originals-v1' if state.args.profile.startswith('legacy') else 'legacy-project-originals-v1'
    elif damage == 'extra': proof['localPath'] = '/unadmitted'
    elif damage == 'current': proof['current']['sourceSha256'] = '0' * 64
    elif damage == 'old-binding': proof['custody']['restoreReceiptSha256'] = '0' * 64
    elif damage == 'same-build':
        proof['custody']['release'] = proof['current']['release']; proof['custody']['commit'] = proof['current']['commit']
        expected_old = copy.deepcopy(proof['custody'])
    elif damage == 'identity':
        proof['custody']['identity']['instanceId'] = 'i-foreign'; expected_old = copy.deepcopy(proof['custody'])
    elif damage == 'fixed-manifest':
        proof['custody']['manifestSha256'] = '0' * 64; expected_old = copy.deepcopy(proof['custody'])
    elif damage == 'boolean-files':
        proof['custody']['files'] = True; expected_old = copy.deepcopy(proof['custody'])
    elif damage == 'archive-size':
        proof['custody']['archiveBytes'] = True; expected_old = copy.deepcopy(proof['custody'])
    elif damage == 'future': proof['issuedAtUtc'] = (now + attest.dt.timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    elif damage == 'expired': now += attest.dt.timedelta(seconds=120)
    elif damage in ('ttl', 'fractional-ttl'):
        proof['expiresAtUtc'] = (now + attest.dt.timedelta(seconds=301 if damage == 'ttl' else 1.5)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    elif damage == 'timestamp': proof['issuedAtUtc'] = '2026-02-30T10:30:00.000000Z'
    else: now = now.replace(tzinfo=None)
    if damage != 'digest': resign(proof)
    with pytest.raises(attest.AttestationError):
        validate(proof, state, expected_current=expected_current, expected_custody=expected_old, now_utc=now)


@pytest.fixture(params=['legacy-project-originals-v1', 'additional-originals-v1', 'residual-project-originals-v1', 'remaining-system-data-v1'])
def fixed_source(tmp_path, monkeypatch, request):
    if request.param == 'residual-project-originals-v1':
        monkeypatch.setitem(attest.PROFILES, request.param, {**attest.PROFILES[request.param], 'MANIFEST_SHA256': 'e' * 64})
    root = tmp_path / 'source-fixture'; root.mkdir(mode=0o700)
    tag = 'ci-81-' + 'a' * 12; checkout = root / 'verification' / tag / 'checkout'; checkout.mkdir(mode=0o700, parents=True)
    inbox = root / 'inbox' / tag; inbox.mkdir(mode=0o700, parents=True)
    files = {}
    for name in attest.CLOSURE:
        files[name] = (ROOT / name).read_bytes(); put(checkout / name, files[name])
    put(inbox / 'reuse-legacy-source.py', files['script/jenkins/reuse-legacy-source.py'])
    source = inbox / 'source.tar.gz'
    def package():
        with tarfile.open(source, 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': 'a' * 40}) as archive:
            for name, raw in files.items():
                info = tarfile.TarInfo(name); info.size = len(raw); archive.addfile(info, io.BytesIO(raw))
        source.chmod(0o600)
        return attest.sha(source.read_bytes())
    args = SimpleNamespace(root=str(root), tag=tag, commit='a' * 40, source_sha256=package(), profile=request.param)
    monkeypatch.setattr(attest, 'SELF', checkout / 'script/jenkins/attest-fixed-originals.py')
    # The real CI basetemp is below /home. Standalone ECS fixture runs may use
    # /tmp; only this synthetic namespace is admitted by the fixture recipe.
    monkeypatch.setattr(attest, 'ADMITTED_ROOTS', (root.parts[1],))
    return SimpleNamespace(args=args, root=root, checkout=checkout, inbox=inbox, source=source, files=files, package=package)


def test_own_recipe_and_every_reused_helper_are_admitted_before_any_project_import(fixed_source):
    state = attest.fixed_modules(fixed_source.args)
    assert state.checkout == fixed_source.checkout and state.fixed == attest.PROFILES[fixed_source.args.profile]


@pytest.mark.parametrize('damage', ['self', 'reuse', 'artifacts', 'cold', 'cleanup', 'verifier', 'migration', 'source-sha', 'commit'])
def test_changed_source_closure_never_imports_a_project_helper(fixed_source, monkeypatch, damage):
    names = {'self': 'script/jenkins/attest-fixed-originals.py', 'reuse': 'script/jenkins/reuse-legacy-source.py',
        'artifacts': 'script/jenkins/preserve-local-artifacts.py', 'cold': 'script/jenkins/preserve-cold-stores.py',
        'cleanup': 'script/jenkins/cleanup-ecs-builds.py', 'verifier': 'script/jenkins/verify-remote.py',
        'migration': 'script/memory/migrate_legacy_stores.py'}
    if damage in names:
        fixed_source.files[names[damage]] = b'raise RuntimeError("unadmitted code must never execute")'
        fixed_source.args.source_sha256 = fixed_source.package()
    elif damage == 'source-sha': fixed_source.args.source_sha256 = '0' * 64
    else: fixed_source.args.commit = 'b' * 40
    monkeypatch.setattr(attest, 'load', lambda _: pytest.fail('No helper import before byte closure'))
    with pytest.raises(attest.AttestationError): attest.fixed_modules(fixed_source.args)


def test_only_legacy_requires_the_existing_inbox_executor_and_neither_profile_writes_one(fixed_source, monkeypatch):
    (fixed_source.inbox / 'reuse-legacy-source.py').unlink()
    before = tree_bytes(fixed_source.root)
    if fixed_source.args.profile == 'legacy-project-originals-v1':
        monkeypatch.setattr(attest, 'load', lambda _: pytest.fail('Missing inbox closure cannot import helpers'))
        with pytest.raises(Exception): attest.fixed_modules(fixed_source.args)
    else:
        assert attest.fixed_modules(fixed_source.args).checkout == fixed_source.checkout
    assert tree_bytes(fixed_source.root) == before


@pytest.mark.parametrize('manifest_sha', [None, '', 'unfrozen', 'A' * 64])
def test_unfrozen_residual_manifest_is_refused_before_any_server_access(monkeypatch, manifest_sha):
    profile = 'residual-project-originals-v1'
    monkeypatch.setitem(attest.PROFILES, profile, {**attest.PROFILES[profile], 'MANIFEST_SHA256': manifest_sha})
    monkeypatch.setattr(attest, 'fixed_modules', lambda _: pytest.fail('Unfrozen manifest cannot inspect server state'))
    with pytest.raises(attest.AttestationError, match='FROZEN_FIXED_ORIGINALS_MANIFEST_REQUIRED'):
        attest.fresh_retirement_attest(SimpleNamespace(profile=profile, nonce='9' * 64, attestation_seconds=120))


@pytest.mark.parametrize('field', ['CATALOG_SHA256', 'FILE_COUNT', 'ORIGINAL_BYTES', 'SNAPSHOT', 'RESTORE', 'PUBLIC',
                                  'MAX_BYTES', 'MAX_MANIFEST'])
def test_residual_source_admission_selects_and_checks_the_fixed_producer_profile(tmp_path, monkeypatch, field):
    state = fixed_source.__wrapped__(tmp_path, monkeypatch, SimpleNamespace(param='residual-project-originals-v1'))
    real_load = attest.load
    def changed_profile(path):
        module = real_load(path)
        if path.name == 'preserve-local-artifacts.py':
            select = module.select_profile
            def changed(name):
                select(name)
                value = getattr(module, field)
                setattr(module, field, value + 1 if type(value) is int else value + '-changed')
            module.select_profile = changed
        return module
    monkeypatch.setattr(attest, 'load', changed_profile)
    with pytest.raises(attest.AttestationError, match='RESIDUAL_FIXED_PRODUCER_PROFILE_DRIFT'):
        attest.fixed_modules(state.args)


@pytest.mark.parametrize('damage', ['none', 'report', 'tool-owner', 'unfinished'])
def test_current_pass_gate_uses_original_reports_and_actual_stopped_tools(old_state, monkeypatch, damage):
    state = old_state
    args = SimpleNamespace(tag=legacy.support.OLD, commit=state.record['commit'], source_sha256=state.record['sourceSha256'],
        expected_instance_id=legacy.support.IDENTITY['instanceId'], expected_machine_id=legacy.support.IDENTITY['machineId'])
    monkeypatch.setattr(additional.custody, 'identity', lambda *_: copy.deepcopy(legacy.support.IDENTITY))
    helpers = SimpleNamespace(root=state.root, artifacts=additional.custody, cold=cold,
        verifier=legacy.support.remote, cleanup=legacy.support.cleanup)
    if damage == 'report': state.keep[2].write_bytes(state.keep[2].read_bytes() + b'changed XML')
    elif damage == 'tool-owner': monkeypatch.setattr(helpers.cleanup, 'docker_snapshot',
        lambda: [['1' * 64, True, False, 44, args.tag, None, []]])
    elif damage == 'unfinished':
        value = json.loads((state.evidence / 'receipt.json').read_bytes()); value['commands'][0].pop('finishedAt')
        legacy.support.put_json(state.evidence / 'receipt.json', value); legacy.support.seal(state)
    if damage == 'none': assert attest.current_pass(args, helpers)['release'] == args.tag
    else:
        with pytest.raises(Exception): attest.current_pass(args, helpers)


def test_cli_emits_one_projection_and_never_accepts_an_unregistered_profile(custody_state, monkeypatch, capsys):
    state = custody_state; args = state.args
    argv = ['fresh-retirement-attest', '--profile', args.profile, '--root', args.root, '--tag', args.tag,
        '--commit', args.commit, '--source-sha256', args.source_sha256, '--expected-instance-id', args.expected_instance_id,
        '--expected-machine-id', args.expected_machine_id, '--source-snapshot-directory', args.source_snapshot_directory,
        '--nonce', args.nonce]
    assert attest.main(argv) == 0
    captured = capsys.readouterr(); assert not captured.err and len(captured.out.splitlines()) == 1
    validate(json.loads(captured.out), state)
    argv[argv.index('--profile') + 1] = 'unregistered-aliases-v1'
    with pytest.raises(SystemExit) as rejected: attest.main(argv)
    assert rejected.value.code == 2


@pytest.fixture
def physical_state(tmp_path, monkeypatch):
    raw = b'opaque model bytes, never loaded'
    model = put(tmp_path / 'physical-model/best_stg2.pth', raw)
    manifest_value = {'schemaVersion': 1, 'format': 'pth', 'modelFile': 'best_stg2.pth', 'checkpointSha256': attest.sha(raw),
        'classNames': ['Normal', 'Bent', 'Deformed', 'Rusty', 'Missing', 'Compromised']}
    manifest = put_json(model.with_name('manifest.json'), manifest_value)
    monkeypatch.setattr(attest, 'MODEL_SOURCE', model)
    monkeypatch.setattr(attest, 'MODEL_MANIFEST_SOURCE', manifest)
    monkeypatch.setattr(attest, 'MODEL_BYTES', len(raw)); monkeypatch.setattr(attest, 'MODEL_SHA256', attest.sha(raw))
    worker = {'containerId': '7' * 64, 'imageId': 'sha256:' + '8' * 64, 'running': True, 'restarting': False, 'processId': 1234,
        'composeProject': 'doorhandlecatch-monolith', 'composeService': 'detection-worker',
        'modelManifest': 'DETECTION_MODEL_MANIFEST=/models/manifest.json', 'modelId': 'DETECTION_MODEL_ID=1',
        'mounts': [{'Type': 'bind', 'Source': '/srv/doorhandle/models', 'Destination': '/models', 'RW': False}]}
    calls = []
    def docker(arguments, maximum=128 * 1024):
        calls.append(arguments)
        if arguments[0] == 'ps': return (worker['containerId'] + '\n').encode()
        assert arguments[0] == 'inspect'
        return attest.encoded(worker)
    monkeypatch.setattr(attest, 'docker_output', docker)
    return SimpleNamespace(model=model, manifest=manifest, manifest_value=manifest_value, raw=raw, worker=worker, calls=calls)


@pytest.fixture
def alias_state(old_state, physical_state, tmp_path, monkeypatch):
    state = build_custody_state('additional-originals-v1', old_state, tmp_path, monkeypatch)
    alias = dict(attest.PROFILES['additional-originals-v1']); monkeypatch.setitem(attest.PROFILES, 'pth-aliases-v1', alias)
    state.args.profile = 'pth-aliases-v1'; state.helpers.fixed = alias
    # The actual synthetic 36-profile fixture contains this small opaque member.
    manifest = json.loads((state.old / 'custody.json').read_bytes())
    member = next(row for row in manifest['files'] if row['member'] == 'work/cloud/opaque.pth')
    assert member['sha256'] == attest.MODEL_SHA256 and member['bytes'] == attest.MODEL_BYTES
    monkeypatch.setattr(attest, 'MODEL_SEALED_MEMBER', member['member'])
    monkeypatch.setattr(attest, 'MODEL_SEALED_SOURCE', member['sourcePath'].replace('\\', '/'))
    state.physical = physical_state
    return state


def test_alias_profile_requires_complete_36_custody_and_fresh_configuration_plus_physical_bytes(alias_state):
    state = alias_state; proof = attest.fresh_retirement_attest(state.args)
    assert validate(proof, state) is proof and 'physicalModel' in proof
    physical = proof['physicalModel']
    assert physical['configuredModelSelectionVerified'] is True and physical['physicalModelVerified'] is True
    assert physical['workerLoadedInMemory'] is False and physical['modelsExecuted'] == 0
    assert physical['worker']['configuredModelId'] == 1
    assert physical['manifest']['checkpointSha256'] == physical['sha256'] == attest.MODEL_SHA256
    assert len([call for call in state.physical.calls if call[0] == 'inspect']) == 2


def test_alias_model_expected_reference_is_pure_and_preserves_owner_policy_and_origin():
    value = attest.model_expected_reference()
    assert value['sourcePath'] == '/srv/doorhandle/models/best_stg2.pth'
    assert value['manifestSourcePath'] == '/srv/doorhandle/models/manifest.json'
    assert value['containerPath'] == '/models/best_stg2.pth' and value['allowedOwnerUids'] == [0, 1000]
    assert value['bytes'] == 159274200 and value['sha256'] == 'eb10caf9fe5fa41e1ce0cfe2bcfaaa728ff44c4fa56f3c6994d6fadb66da434b'
    assert value['sealedMember'] == 'work/cloud/pth-model/best_stg2.pth'
    assert value['sealedManifestSha256'] == 'b247f6f8bf0f5fc3e4d12b5bca008bb05786221d657262860de1ae6c479eec94'


def test_windows_pure_validator_uses_the_same_posix_server_reference(monkeypatch):
    from pathlib import PureWindowsPath
    monkeypatch.setattr(attest, 'MODEL_SOURCE', PureWindowsPath('/srv/doorhandle/models/best_stg2.pth'))
    monkeypatch.setattr(attest, 'MODEL_MANIFEST_SOURCE', PureWindowsPath('/srv/doorhandle/models/manifest.json'))
    value = attest.model_expected_reference()
    assert value['sourcePath'] == '/srv/doorhandle/models/best_stg2.pth'
    assert value['manifestSourcePath'] == '/srv/doorhandle/models/manifest.json'


@pytest.mark.parametrize('resource', ['model', 'manifest'])
def test_fifo_replacement_between_lstat_and_open_is_nonblocking_and_refused_before_read(physical_state, monkeypatch, resource):
    target = getattr(physical_state, resource); real_open = os.open; replaced = []
    def swapped_open(path, flags, *args, **kwargs):
        if Path(path) == target and not replaced:
            assert flags & os.O_NONBLOCK
            replaced.append(True)
            target.rename(target.with_name('original-' + target.name)); os.mkfifo(target, 0o600)
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(attest.os, 'open', swapped_open)
    with pytest.raises(attest.AttestationError, match='PHYSICAL_MODEL_FD_ADMISSION_REFUSED'):
        attest.observe_model_files()
    assert replaced


@pytest.mark.parametrize('uid', [0, 1000, 42, 10001])
def test_only_the_two_explicit_model_resource_owner_uids_are_admitted(physical_state, monkeypatch, uid):
    real_fstat, real_lstat = os.fstat, Path.lstat
    def projected(info):
        keys = ('st_mode', 'st_uid', 'st_gid', 'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')
        values = {key: getattr(info, key) for key in keys}; values['st_uid'] = uid
        return SimpleNamespace(**values)
    def lstat(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        return projected(info) if path in (physical_state.model, physical_state.manifest) else info
    monkeypatch.setattr(attest.os, 'fstat', lambda fd: projected(real_fstat(fd)))
    monkeypatch.setattr(Path, 'lstat', lstat)
    if uid in (0, 1000):
        result = attest.observe_model_files(); assert result['ownerUid'] == result['manifest']['ownerUid'] == uid
    else:
        with pytest.raises(attest.AttestationError, match='FD_ADMISSION_REFUSED'): attest.observe_model_files()


@pytest.mark.parametrize('damage', ['model-sha', 'model-size', 'model-hardlink', 'model-symlink', 'model-writable',
                                  'manifest-hardlink', 'manifest-symlink', 'manifest-writable'])
def test_alias_resources_cannot_use_changed_shared_linked_or_writable_physical_files(physical_state, damage):
    state = physical_state; path = state.manifest if damage.startswith('manifest') else state.model
    if damage == 'model-sha': path.write_bytes(b'x' * len(state.raw))
    elif damage == 'model-size': path.write_bytes(state.raw + b'x')
    elif damage.endswith('hardlink'): os.link(path, path.with_name('foreign-' + path.name))
    elif damage.endswith('symlink'):
        original = path.with_name('original-' + path.name); path.rename(original); path.symlink_to(original)
    else: path.chmod(0o666)
    with pytest.raises(Exception): attest.observe_model_files()


@pytest.mark.parametrize('damage', ['schema', 'format', 'other-file', 'traversal', 'checkpoint', 'class-names', 'duplicate', 'nonfinite'])
def test_manifest_path_and_checkpoint_follow_the_single_pth_reader_contract(physical_state, damage):
    state = physical_state; value = copy.deepcopy(state.manifest_value)
    if damage == 'schema': value['schemaVersion'] = True
    elif damage == 'format': value['format'] = 'onnx'
    elif damage == 'other-file': value['modelFile'] = 'other.pth'
    elif damage == 'traversal': value['modelFile'] = '../best_stg2.pth'
    elif damage == 'checkpoint': value['checkpointSha256'] = '0' * 64
    elif damage == 'class-names': value['classNames'] = ['other']
    raw = attest.encoded(value)
    if damage == 'duplicate': raw = b'{"schemaVersion":1,"schemaVersion":1}'
    elif damage == 'nonfinite': raw = b'{"schemaVersion":NaN}'
    state.manifest.write_bytes(raw)
    with pytest.raises(Exception): attest.observe_model_files()


@pytest.mark.parametrize('damage', ['stopped', 'restarting', 'wrong-project', 'wrong-service', 'wrong-id', 'wrong-image',
    'zero-pid', 'manifest-env', 'missing-id', 'zero-id', 'foreign-manifest', 'rw-mount', 'volume-mount',
    'foreign-source', 'nested-shadow'])
def test_fresh_worker_projection_requires_actual_role_two_config_keys_and_exact_readonly_mount(physical_state, damage):
    worker = physical_state.worker
    if damage == 'stopped': worker['running'] = False
    elif damage == 'restarting': worker['restarting'] = True
    elif damage == 'wrong-project': worker['composeProject'] = 'other'
    elif damage == 'wrong-service': worker['composeService'] = 'backend'
    elif damage == 'wrong-id': worker['containerId'] = 'bad'
    elif damage == 'wrong-image': worker['imageId'] = 'latest'
    elif damage == 'zero-pid': worker['processId'] = 0
    elif damage == 'manifest-env': worker['modelManifest'] = 'OTHER=/models/manifest.json'
    elif damage == 'missing-id': worker.pop('modelId')
    elif damage == 'zero-id': worker['modelId'] = 'DETECTION_MODEL_ID=0'
    elif damage == 'foreign-manifest': worker['modelManifest'] = 'DETECTION_MODEL_MANIFEST=/other/manifest.json'
    elif damage == 'rw-mount': worker['mounts'][0]['RW'] = True
    elif damage == 'volume-mount': worker['mounts'][0]['Type'] = 'volume'
    elif damage == 'foreign-source': worker['mounts'][0]['Source'] = '/other/models'
    else: worker['mounts'].append({'Type': 'bind', 'Source': '/other', 'Destination': '/models/best_stg2.pth', 'RW': False})
    with pytest.raises(Exception): attest.physical_model_proof()


@pytest.mark.parametrize('damage', ['worker-id', 'image', 'model-id-raw', 'manifest-bytes', 'model-bytes'])
def test_worker_and_open_resource_identities_are_checked_again_at_the_end(physical_state, monkeypatch, damage):
    original = attest.observe_worker; calls = []
    def observed():
        value = original(); calls.append(True)
        if len(calls) == 2:
            if damage == 'worker-id': value['containerId'] = '6' * 64
            elif damage == 'image': value['imageId'] = 'sha256:' + '6' * 64
            elif damage == 'model-id-raw': value['configuredModelIdRaw'] = '+1'
            elif damage == 'manifest-bytes': physical_state.manifest.write_bytes(physical_state.manifest.read_bytes() + b' ')
            else: physical_state.model.write_bytes(b'x' * len(physical_state.raw))
        return value
    monkeypatch.setattr(attest, 'observe_worker', observed)
    with pytest.raises(attest.AttestationError): attest.physical_model_proof()


@pytest.mark.parametrize('damage', ['missing', 'different-member', 'different-source', 'different-sha', 'different-size', 'duplicate'])
def test_alias_origin_is_the_exact_original_member_inside_the_complete_36_package(alias_state, damage):
    state = alias_state
    manifest = json.loads((state.old / 'custody.json').read_bytes())
    row = next(r for r in manifest['files'] if r['member'] == attest.MODEL_SEALED_MEMBER)
    if damage == 'missing': manifest['files'].remove(row)
    elif damage == 'different-member': row['member'] = 'other/model.pth'
    elif damage == 'different-source': row['sourcePath'] = 'D:/other/model.pth'
    elif damage == 'different-sha': row['sha256'] = '0' * 64
    elif damage == 'different-size': row['bytes'] += 1
    else: manifest['files'].append(copy.deepcopy(row))
    with pytest.raises(attest.AttestationError, match='SEALED_PTH'): attest.validate_sealed_model_member(manifest)


@pytest.mark.parametrize('damage', ['missing', 'owner', 'manifest-owner', 'model-sha', 'manifest-file', 'model-id',
    'writable-mount', 'loaded-claim', 'executed-claim', 'different-path', 'extra'])
def test_alias_pure_validator_requires_the_extra_physical_and_configuration_proof(alias_state, damage):
    state = alias_state; value = attest.fresh_retirement_attest(state.args); physical = value['physicalModel']
    if damage == 'missing': value.pop('physicalModel')
    elif damage == 'owner': physical['ownerUid'] = 42
    elif damage == 'manifest-owner': physical['manifest']['ownerUid'] = 42
    elif damage == 'model-sha': physical['sha256'] = '0' * 64
    elif damage == 'manifest-file': physical['manifest']['modelFile'] = 'other.pth'
    elif damage == 'model-id': physical['worker']['configuredModelIdRaw'] = '2'
    elif damage == 'writable-mount': physical['worker']['mountReadOnly'] = False
    elif damage == 'loaded-claim': physical['workerLoadedInMemory'] = True
    elif damage == 'executed-claim': physical['modelsExecuted'] = 1
    elif damage == 'different-path': physical['sourcePath'] = '/other/model.pth'
    else: physical['arbitraryReadAllowed'] = True
    resign(value)
    with pytest.raises(attest.AttestationError): validate(value, state)


def test_old_profiles_do_not_acquire_model_observation_or_a_larger_envelope(custody_state, monkeypatch):
    monkeypatch.setattr(attest, 'physical_model_proof', lambda: pytest.fail('Original profiles must not inspect any model or worker'))
    proof = attest.fresh_retirement_attest(custody_state.args)
    assert 'physicalModel' not in proof and set(proof) == set(attest.ATTESTATION_FIELDS)


def test_docker_reads_are_local_metadata_only_and_discard_process_environment(physical_state, monkeypatch):
    # Use the original function body from the module independently of the
    # fixture's fake producer, without contacting Docker.
    spec = importlib.util.spec_from_file_location('fixed_originals_docker_command_contract', ROOT / 'script/jenkins/attest-fixed-originals.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    calls = []
    monkeypatch.setattr(module.shutil, 'which', lambda _: '/usr/bin/docker')
    monkeypatch.setattr(module.subprocess, 'run', lambda command, **kwargs:
        calls.append((command, kwargs)) or SimpleNamespace(returncode=0, stdout=b'opaque metadata'))
    monkeypatch.setenv('DOCKER_HOST', 'tcp://must-not-be-used')
    assert module.docker_output(['ps']) == b'opaque metadata'
    command, kwargs = calls[0]
    assert command[:3] == ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock']
    assert not set(kwargs['env']) - {'PATH', 'LANG', 'LC_ALL'} and 'DOCKER_HOST' not in kwargs['env']
