"""Generated public import-cache guards; Jenkins/ECS execution only."""
from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace

import pytest


SPEC = importlib.util.spec_from_file_location('generated_public_archive_retirement_tests',
    Path(__file__).resolve().parents[1] / 'script/jenkins/retire-failed-native-jar-duplicates.py')
retirer = importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name] = retirer; SPEC.loader.exec_module(retirer)
TAG = 'ci-118-6481f7fa6021'


def sha(raw): return hashlib.sha256(raw).hexdigest()


def private_file(root, relative, raw):
    path = root / relative; path.parent.mkdir(parents=True, exist_ok=True)
    for parent in (path.parent, *path.parent.parents):
        if parent == root or parent.is_relative_to(root): parent.chmod(0o700)
    path.write_bytes(raw); path.chmod(0o600); return path


def public_tar(payloads, mtime):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:') as package:
        for raw in payloads:
            info = tarfile.TarInfo('blobs/sha256/' + sha(raw)); info.size = len(raw); info.mtime = mtime
            package.addfile(info, io.BytesIO(raw))
    return output.getvalue()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    root = tmp_path / 'ci'; root.mkdir(mode=0o700)
    payloads = [b'public synthetic upstream layer ' + bytes([index]) for index in range(4)]
    seed_raw, generated_raw = public_tar(payloads, 0), public_tar(payloads, 123456)
    monkeypatch.setattr(retirer, 'PUBLIC_LAYERS', {sha(raw): len(raw) for raw in payloads})
    monkeypatch.setattr(retirer, 'PUBLIC_ARCHIVE_SHA', sha(seed_raw))
    monkeypatch.setattr(retirer, 'PUBLIC_ARCHIVE_BYTES', len(seed_raw))
    seed = private_file(root, 'build-inputs/buildkit-v0.34.2/' + sha(seed_raw) + '.tar', seed_raw)
    target = private_file(root, 'inbox/' + TAG + '/candidate-build-tools/official-image.tar', generated_raw)
    retained = private_file(root, 'inbox/ci-117-8c898996cc28/candidate-build-tools/official-oci/retained-original', b'public original OCI')
    return SimpleNamespace(root=root, seed=seed, target=target, retained=retained, seed_raw=seed_raw,
                           generated_raw=generated_raw, proof=retirer.public_layer_archive(root))


def described(cache): return retirer.describe_generated_image_archive_cache(cache.root, TAG)


def test_generated_cache_with_different_tar_headers_is_removed_and_public_originals_preserved(cache):
    descriptor = described(cache)
    assert descriptor['kind'] == retirer.GENERATED_CACHE_KIND
    assert descriptor['sha256'] != cache.proof['sha256'] and cache.generated_raw != cache.seed_raw
    value = retirer.remove_generated_image_archive_cache(cache.root, descriptor, cache.proof)
    assert not cache.target.exists() and cache.target.parent.is_dir()
    assert cache.seed.read_bytes() == cache.seed_raw and cache.retained.read_bytes() == b'public original OCI'
    assert value['sha256'] == sha(cache.generated_raw) and value['publicSeedVerifiedAfter']
    assert not value['sameBytesAsSeedClaimed'] and value['capturedInodeVerified']


@pytest.mark.parametrize('mutation', ['path', 'kind', 'release', 'bytes'])
def test_generated_descriptor_cannot_select_seed_or_any_other_path(cache, mutation):
    descriptor = described(cache)
    if mutation == 'path': descriptor['path'] = cache.seed.relative_to(cache.root).as_posix()
    elif mutation == 'kind': descriptor['kind'] = retirer.JAR_COPY_KIND
    elif mutation == 'release': descriptor['release'] = 'ci-999-' + 'a' * 12
    else: descriptor['bytes'] += 1
    with pytest.raises((ValueError, OSError)):
        retirer.remove_generated_image_archive_cache(cache.root, descriptor, cache.proof)
    assert cache.target.read_bytes() == cache.generated_raw and cache.seed.read_bytes() == cache.seed_raw


@pytest.mark.parametrize('mutation', ['target_bytes', 'target_link', 'seed_bytes', 'seed_hardlink'])
def test_changed_generated_target_or_public_seed_fails_before_removal(cache, mutation):
    descriptor = described(cache)
    if mutation == 'target_bytes': cache.target.write_bytes(b'x' * len(cache.generated_raw))
    elif mutation == 'target_link': cache.target.unlink(); cache.target.symlink_to(cache.seed)
    elif mutation == 'seed_bytes': cache.seed.write_bytes(b'x' * len(cache.seed_raw))
    else: os.link(cache.seed, cache.seed.with_name('additional-link'))
    with pytest.raises((ValueError, OSError, tarfile.TarError)):
        retirer.remove_generated_image_archive_cache(cache.root, descriptor, cache.proof)
    assert cache.target.exists()


def test_replaced_target_at_atomic_capture_is_retained_in_quarantine(cache, monkeypatch):
    descriptor = described(cache); reservation = retirer.reserve_quarantine(cache.root)
    replacement = private_file(cache.root, 'other-retained-original', b'unrecognized original')
    inode = replacement.stat().st_ino; capture = retirer._capture_no_replace
    def replace_before_capture(*args):
        os.replace(replacement, cache.target); return capture(*args)
    monkeypatch.setattr(retirer, '_capture_no_replace', replace_before_capture)
    with pytest.raises(ValueError):
        retirer.remove_generated_image_archive_cache(cache.root, descriptor, cache.proof, quarantine=reservation)
    captured = cache.root / reservation['path']
    assert captured.stat().st_ino == inode and captured.read_bytes() == b'unrecognized original'
    assert cache.seed.read_bytes() == cache.seed_raw


def test_changed_seed_during_capture_retains_generated_archive(cache, monkeypatch):
    descriptor = described(cache); reservation = retirer.reserve_quarantine(cache.root); capture = retirer._capture_no_replace
    def corrupt_seed_at_capture(*args):
        result = capture(*args); cache.seed.write_bytes(b'x' * len(cache.seed_raw)); return result
    monkeypatch.setattr(retirer, '_capture_no_replace', corrupt_seed_at_capture)
    with pytest.raises(ValueError):
        retirer.remove_generated_image_archive_cache(cache.root, descriptor, cache.proof, quarantine=reservation)
    assert (cache.root / reservation['path']).read_bytes() == cache.generated_raw


@pytest.mark.parametrize('mutation', ['none', 'context', 'identity', 'producer', 'original_sha'])
def test_generated_admission_binds_original_tools_to_old_source_and_actual_owner(cache, monkeypatch, mutation):
    context = {'release': TAG, 'commit': retirer.APPROVED_OLD[TAG], 'sourceSha256': 'a' * 64}
    identity = {'executionLocation': 'ECS', 'instanceId': 'synthetic', 'machineId': 'b' * 32}
    helpers = {'compact-build-resources.py': 'c' * 64, 'compact-image-inputs.py': 'd' * 64}
    historical = {'context': context, 'evidence': {'ownerToken': '0123456789', 'jenkinsResult': 'FAILURE'},
                  'controls': {}, 'sourceArchive': {'builderHelperSha256': helpers}}
    monkeypatch.setattr(retirer, 'admit_historical_controls', lambda *_args, **_kwargs: historical)
    tools = {**context, 'status': 'PREPARED', 'identity': identity,
             'helperSha256': helpers['compact-build-resources.py'], 'imageInputsHelperSha256': helpers['compact-image-inputs.py']}
    if mutation == 'context': tools['sourceSha256'] = 'e' * 64
    elif mutation == 'identity': tools['identity'] = {**identity, 'machineId': 'e' * 32}
    elif mutation == 'producer': tools['helperSha256'] = 'e' * 64
    raw = retirer.canonical(tools)
    private_file(cache.root, 'inbox/' + TAG + '/candidate-build-tools/tools.json', raw)
    monkeypatch.setattr(retirer, 'APPROVED_BUILDER_TOOLS', {TAG: 'f' * 64 if mutation == 'original_sha' else sha(raw)})
    operation = lambda: retirer.admit_generated_image_archive_attempt(cache.root, {'identity': identity},
        context, lambda *_args: None)
    if mutation == 'none':
        value = operation()
        assert value['rebuildBasis']['producerSha256'] == helpers['compact-build-resources.py']
        assert value['rebuildBasis']['publicInputSha256'] == cache.proof['sha256']
        assert not value['rebuildBasis']['sameBytesAsSeedClaimed'] and value['target']['sha256'] == sha(cache.generated_raw)
    else:
        with pytest.raises(ValueError): operation()
    assert cache.target.read_bytes() == cache.generated_raw


@pytest.fixture
def planning(cache, monkeypatch):
    current = {'release': 'ci-999-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    identity = {'executionLocation': 'ECS', 'instanceId': 'synthetic', 'machineId': 'c' * 32}
    row = {'release': TAG, 'commit': retirer.APPROVED_OLD[TAG], 'sourceSha256': 'd' * 64, 'controls': {}}
    request = {'schemaVersion': 1, 'kind': retirer.KIND + '-request', 'current': current, 'identity': identity,
               'protectedReleases': [current['release']], 'candidates': [row]}
    raw = retirer.canonical(request)
    private_file(cache.root, 'verification/' + TAG + '/checkout/retained-source.py', b'synthetic fixed source')
    private_file(cache.root, 'inbox/' + current['release'] + '/retained-control', b'synthetic current control')
    calls = []
    def admit(root, actual_request, actual_row, quiescence):
        assert actual_request == request and actual_row == row
        assert quiescence(root / 'verification' / TAG / 'checkout', TAG, '0123456789') is None
        return {'context': {key: row[key] for key in ('release', 'commit', 'sourceSha256')},
                'ownerToken': '0123456789', 'target': retirer.describe_generated_image_archive_cache(root, TAG),
                'rebuildBasis': {'sameBytesAsSeedClaimed': False, 'producerSha256': 'e' * 64}}
    monkeypatch.setattr(retirer, 'admit_generated_image_archive_attempt', admit)
    return SimpleNamespace(cache=cache, current=current, identity=identity, raw=raw, checksum=sha(raw),
                           calls=calls, quiescence=lambda _checkout, tag, _token: calls.append(tag))


def planned(planning):
    return retirer.plan_generated_image_archives(planning.cache.root, planning.raw, request_sha256=planning.checksum,
        expected_current=planning.current, identity=planning.identity, quiescence=planning.quiescence)


def applied(planning, plan):
    return retirer.apply_generated_image_archives(planning.cache.root, planning.raw, plan, request_sha256=planning.checksum,
        plan_sha256=sha(retirer.canonical(plan)), expected_current=planning.current,
        identity=planning.identity, quiescence=planning.quiescence)


def test_generated_plan_and_apply_keep_source_binding_and_actual_removed_bytes(planning):
    plan = planned(planning); assert not plan['skipped'], plan['skipped']
    assert len(plan['candidates']) == 1 and plan['candidateBytes'] == len(planning.cache.generated_raw)
    receipt = applied(planning, plan)
    assert receipt['status'] == 'REMOVED' and len(receipt['deleted']) == 1
    assert receipt['deleted'][0]['sha256'] == sha(planning.cache.generated_raw)
    assert receipt['publicInputsDirectoriesImagesAndBusinessDataPreserved'] and not receipt['sameBytesAsSeedClaimed']
    assert not receipt['retainedQuarantinePaths'] and not receipt['testsRunByRetirement']
    path = planning.cache.root / 'inbox' / planning.current['release'] / 'native-generated-public-image-archive-journal.jsonl'
    assert receipt['journalSha256'] == sha(path.read_bytes())


@pytest.mark.parametrize('mutation', ['target', 'seed'])
def test_changed_planned_generated_cache_or_seed_produces_failure_without_deleting(planning, mutation):
    plan = planned(planning); assert plan['candidates'], plan['skipped']
    path = planning.cache.target if mutation == 'target' else planning.cache.seed
    raw = path.read_bytes(); path.write_bytes(b'x' + raw[1:])
    receipt = applied(planning, plan)
    assert receipt['status'] == 'FAILED_OR_UNKNOWN' and not receipt['deleted']
    assert planning.cache.target.exists()


def test_missing_generated_cache_is_explicit_skip_and_no_action(planning):
    planning.cache.target.unlink(); plan = planned(planning)
    assert not plan['candidates'] and plan['skipped']
    receipt = applied(planning, plan)
    assert receipt['status'] == 'NO_ACTION' and not receipt['mutationAttempted']


def test_generated_apply_cannot_select_current_or_unauthenticated_tag(planning):
    plan = planned(planning); plan['candidates'][0]['context']['release'] = planning.current['release']
    with pytest.raises(ValueError): applied(planning, plan)
    assert planning.cache.target.exists()


def test_quarantine_failure_receipt_retains_actual_captured_file(planning, monkeypatch):
    plan = planned(planning); capture = retirer._capture_no_replace
    def fail_after_capture(*args):
        capture(*args); raise OSError('synthetic loss of confirmation')
    monkeypatch.setattr(retirer, '_capture_no_replace', fail_after_capture)
    receipt = applied(planning, plan)
    assert receipt['status'] == 'FAILED_OR_UNKNOWN' and not receipt['deleted'] and receipt['mutationAttempted']
    assert receipt['retainedQuarantinePaths'] == [receipt['lastQuarantinePath']]
    assert (planning.cache.root / receipt['lastQuarantinePath']).read_bytes() == planning.cache.generated_raw


# Share one synthetic six-source fixture, not private developer/production data.
RECENT_SPEC = importlib.util.spec_from_file_location('generated_recent_public_fixture',
    Path(__file__).with_name('test_public_buildkit_layer_retirement.py'))
RECENT_FIXTURES = importlib.util.module_from_spec(RECENT_SPEC)
RECENT_SPEC.loader.exec_module(RECENT_FIXTURES)
recent_public_case = RECENT_FIXTURES.recent_public_case


def recent_plan(s):
    return s.retirer.plan_generated_image_archives(s.root, s.raw, **s.options)


def recent_apply(s, value):
    return s.retirer.apply_generated_image_archives(s.root, s.raw, value,
        plan_sha256=sha(s.retirer.canonical(value)), **s.options)


def test_recent_generated_cache_binds_real_tar_sha_not_unlinked_measurement_archive(recent_public_case):
    s = recent_public_case; value = recent_plan(s)
    assert value['skipped'] == [] and len(value['candidates']) == 5
    for candidate in value['candidates']:
        target = candidate['target']; tag = candidate['context']['release']
        measurement = json.loads((s.root / 'inbox' / tag / 'candidate-build-tools/official-layer-measurements.json').read_bytes())
        assert target['sha256'] == sha((s.root / target['path']).read_bytes()) != measurement['archiveSha256']
        assert candidate['rebuildBasis']['sameBytesAsSeedClaimed'] is False
    result = recent_apply(s, value)
    assert result['status'] == 'REMOVED' and len(result['deleted']) == 5
    assert result['sameBytesAsSeedClaimed'] is False and all(path.exists() for path in s.layers)
    assert all(path.read_bytes() == body for path, body in s.originals.items())


@pytest.mark.parametrize('damage', ['tar', 'source', 'prepared-control', 'seed', 'keeper'])
def test_recent_generated_plan_cannot_apply_a_partial_or_unproven_five_file_set(recent_public_case, damage):
    s = recent_public_case; r = s.retirer; tag = next(iter(r.PUBLIC_CACHE_TARGETS))
    path = {'tar': s.tars[0], 'source': s.root / 'inbox' / tag / 'source.tar.gz',
        'prepared-control': s.root / 'inbox' / tag / 'candidate-build-tools/tools.json', 'seed': s.seed,
        'keeper': next(path for path in s.originals if 'official-oci' in str(path))}[damage]
    path.write_bytes(b'changed original before planning')
    value = recent_plan(s)
    assert value['skipped'] and len(value['candidates']) < 5
    with pytest.raises(r.RetirementError, match='COMPLETE_FIVE_GENERATED_PUBLIC_ARCHIVES_REQUIRED'):
        recent_apply(s, value)
    assert all(path.exists() for path in s.tars)


@pytest.mark.parametrize('changed', ['tar', 'source', 'prepared-control', 'keeper', 'container', 'publication'])
def test_recent_generated_apply_rechecks_targets_sources_and_references_before_any_delete(recent_public_case, changed):
    s = recent_public_case; r = s.retirer; value = recent_plan(s); tag = next(iter(r.PUBLIC_CACHE_TARGETS))
    if changed == 'tar': s.tars[0].write_bytes(b'changed generated tar after approval')
    elif changed == 'source': (s.root / 'inbox' / tag / 'source.tar.gz').write_bytes(b'changed source after approval')
    elif changed == 'prepared-control': (s.root / 'inbox' / tag / 'candidate-build-tools/tools.json').write_bytes(b'changed prepared control')
    elif changed == 'keeper': next(path for path in s.originals if 'official-oci' in str(path)).write_bytes(b'changed keeper')
    elif changed == 'publication': (s.root / 'releases' / tag).mkdir(parents=True, mode=0o700)
    else: s.containers.append(['a' * 64, False, False, 0, tag, None, []])
    result = recent_apply(s, value)
    assert result['status'] == 'FAILED_OR_UNKNOWN' and result['deleted'] == []
    assert all(path.exists() for path in s.tars)


@pytest.mark.parametrize('changed', ['source', 'prepared-control', 'keeper', 'seed', 'container', 'publication'])
def test_recent_generated_after_capture_requires_same_sources_keeper_and_dual_root_quiescence(recent_public_case, monkeypatch, changed):
    s = recent_public_case; r = s.retirer; value = recent_plan(s); tag = next(iter(r.PUBLIC_CACHE_TARGETS)); capture = r._capture_no_replace
    def mutate(*args):
        capture(*args)
        if changed == 'source': (s.root / 'inbox' / tag / 'source.tar.gz').write_bytes(b'changed source after capture')
        elif changed == 'prepared-control': (s.root / 'inbox' / tag / 'candidate-build-tools/tools.json').write_bytes(b'changed prepared control')
        elif changed == 'keeper': next(path for path in s.originals if 'official-oci' in str(path)).write_bytes(b'changed keeper')
        elif changed == 'seed': s.seed.write_bytes(b'changed master archive')
        elif changed == 'publication': (s.root / 'releases' / tag).mkdir(parents=True, mode=0o700)
        else: s.containers.append(['a' * 64, False, False, 0, tag, None, []])
    monkeypatch.setattr(r, '_capture_no_replace', mutate)
    result = recent_apply(s, value)
    assert result['status'] == 'FAILED_OR_UNKNOWN' and result['deleted'] == [] and len(result['retainedQuarantinePaths']) == 1
    assert (s.root / result['retainedQuarantinePaths'][0]).exists()


@pytest.mark.parametrize('reference', ['cwd', 'argv', 'fd', 'mmap'])
def test_recent_generated_real_process_scanner_rejects_old_inbox_references(recent_public_case, reference):
    s = recent_public_case; r = s.retirer; tag = next(iter(r.PUBLIC_CACHE_TARGETS)); inbox = s.root / 'inbox' / tag
    pid = s.proc / str(os.getpid() + 100000); (pid / 'fd').mkdir(parents=True)
    (pid / 'cwd').symlink_to(inbox if reference == 'cwd' else s.root, target_is_directory=True)
    (pid / 'cmdline').write_bytes(b'process\0' + (os.fsencode(inbox / 'candidate-build-tools/official-image.tar') if reference == 'argv' else b'-I') + b'\0')
    if reference == 'fd': (pid / 'fd/9').symlink_to(inbox / 'candidate-build-tools/official-image.tar')
    (pid / 'maps').write_bytes(b'0-1 r--p 0 00:00 1 ' + os.fsencode(inbox / 'candidate-build-tools/official-image.tar') + b'\n' if reference == 'mmap' else b'')
    value = recent_plan(s)
    assert value['skipped'] and len(value['candidates']) < 5
    with pytest.raises(r.RetirementError, match='COMPLETE_FIVE_GENERATED_PUBLIC_ARCHIVES_REQUIRED'): recent_apply(s, value)
    assert all(path.exists() for path in s.tars)


@pytest.mark.parametrize(('mode', 'phase', 'jar_batch'), [
    ('Verified', 'capture-public-cache-request', None), ('Maintenance', 'capture-canonical-request', None),
    ('Maintenance', 'plan-canonical', None), ('Maintenance', 'apply', None),
    ('Maintenance', 'apply-recent-fixtures', None), ('Maintenance', 'inspect', retirer.FAILED_NATIVE_BATCH)])
def test_public_batch_cli_does_not_authorize_verified_or_other_resource_phases(monkeypatch, capsys, mode, phase, jar_batch):
    def forbidden(args): raise AssertionError('Invalid public policy reached actual ECS context')
    monkeypatch.setattr(retirer, 'admitted_current', forbidden)
    args = ['--phase', phase, '--mode', mode, '--public-cache-batch', retirer.PUBLIC_CACHE_BATCH,
        '--root', '/home/ecs-user/doorhandle-ci', '--tag', 'ci-999-' + 'a' * 12, '--commit', 'a' * 40,
        '--source-sha256', 'b' * 64, '--instance-id', 'i-fixture123', '--machine-id', 'c' * 32,
        '--current-receipt-sha256', 'd' * 64]
    if jar_batch is not None: args += ['--jar-batch', jar_batch]
    assert retirer.cli(args) == 2
    assert json.loads(capsys.readouterr().out)['reason'] == 'PUBLIC_CACHE_BATCH_MAINTENANCE_PHASE_REQUIRED'


