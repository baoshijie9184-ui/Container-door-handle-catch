"""Synthetic public BuildKit byte copies; run only by Jenkins on ECS."""
from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
from types import SimpleNamespace

import pytest


MODULE = Path(__file__).resolve().parents[1] / 'script/jenkins/retire-failed-native-jar-duplicates.py'
SPEC = importlib.util.spec_from_file_location('public_buildkit_layer_retirement_tests', MODULE)
retirer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = retirer
SPEC.loader.exec_module(retirer)

KEEPER = 'ci-117-8c898996cc28'
TARGET = 'ci-118-6481f7fa6021'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def private_file(root, relative, raw):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    for parent in (path.parent, *path.parent.parents):
        if parent == root or parent.is_relative_to(root): parent.chmod(0o700)
    path.write_bytes(raw); path.chmod(0o600)
    return path


@pytest.fixture
def copies(tmp_path, monkeypatch):
    root = tmp_path / 'ci'; root.mkdir(mode=0o700)
    payloads = [b'public synthetic layer ' + bytes([index]) for index in range(4)]
    layers = {sha(raw): len(raw) for raw in payloads}
    monkeypatch.setattr(retirer, 'PUBLIC_LAYERS', layers)
    for tag in (KEEPER, TARGET):
        for raw in payloads:
            private_file(root, 'inbox/' + tag + '/candidate-build-tools/official-oci/blobs/sha256/' + sha(raw), raw)
    raw = payloads[0]
    target, keeper = retirer.duplicate_paths(root, TARGET, kind=retirer.PUBLIC_LAYER_KIND, blob_sha=sha(raw))
    return SimpleNamespace(root=root, payload=raw, payloads=payloads, target=target, keeper=keeper,
                           checksum=sha(raw), size=len(raw))


def described(copies):
    return retirer.describe_duplicate(copies.root, TARGET, copies.checksum, copies.size, kind=retirer.PUBLIC_LAYER_KIND)


def test_public_paths_only_select_exact_blob_and_preserved_117(copies):
    descriptor = described(copies)
    assert descriptor['kind'] == retirer.PUBLIC_LAYER_KIND
    assert descriptor['path'] == copies.target.relative_to(copies.root).as_posix()
    assert descriptor['keeper']['path'] == copies.keeper.relative_to(copies.root).as_posix()
    assert descriptor['sha256'] == descriptor['keeper']['sha256'] == copies.checksum
    assert descriptor['metadata'][:2] != descriptor['keeper']['metadata'][:2]
    assert descriptor['metadata'][5] == descriptor['keeper']['metadata'][5] == 1


@pytest.mark.parametrize('tag,kind,checksum', [
    (KEEPER, retirer.PUBLIC_LAYER_KIND, None),
    ('ci-156-' + 'a' * 12, retirer.PUBLIC_LAYER_KIND, None),
    (TARGET, 'UNKNOWN_PUBLIC_KIND', None),
    (TARGET, retirer.PUBLIC_LAYER_KIND, 'f' * 64),
])
def test_keeper_current_unknown_tag_or_unknown_blob_has_no_public_delete_path(copies, tag, kind, checksum):
    with pytest.raises(retirer.RetirementError):
        retirer.duplicate_paths(copies.root, tag, kind=kind, blob_sha=checksum or copies.checksum)


def test_original_default_jar_paths_are_unchanged(copies):
    target, keeper = retirer.duplicate_paths(copies.root, TARGET)
    assert target == copies.root / 'verification' / TARGET / 'checkout/work/compact-fixtures/candidate-app.jar'
    assert keeper == copies.root / 'inbox' / TARGET / 'application.jar'


@pytest.mark.parametrize('mutation', ['length', 'same_length_bytes', 'keeper_bytes', 'target_symlink', 'keeper_hardlink'])
def test_only_independent_full_byte_equal_public_copies_are_admitted(copies, mutation):
    if mutation == 'length': copies.target.write_bytes(copies.payload + b'x')
    elif mutation == 'same_length_bytes': copies.target.write_bytes(b'x' * copies.size)
    elif mutation == 'keeper_bytes': copies.keeper.write_bytes(b'x' * copies.size)
    elif mutation == 'target_symlink':
        copies.target.unlink(); copies.target.symlink_to(copies.keeper)
    else: os.link(copies.keeper, copies.keeper.with_name('another-link'))
    with pytest.raises((retirer.RetirementError, OSError)):
        described(copies)


@pytest.mark.parametrize('mutation', ['path', 'keeper', 'kind', 'bytes'])
def test_public_descriptor_cannot_select_any_other_file(copies, mutation):
    descriptor = described(copies)
    if mutation == 'path': descriptor['path'] = descriptor['keeper']['path']
    elif mutation == 'keeper': descriptor['keeper']['path'] = descriptor['path']
    elif mutation == 'kind': descriptor['kind'] = retirer.JAR_COPY_KIND
    else: descriptor['bytes'] += 1
    with pytest.raises((retirer.RetirementError, OSError)):
        retirer.remove_duplicate(copies.root, descriptor)
    assert copies.target.read_bytes() == copies.keeper.read_bytes() == copies.payload


def test_public_remove_retains_keeper_tar_index_config_and_directories(copies):
    directory = copies.target.parent
    index = private_file(copies.root, 'inbox/' + TARGET + '/candidate-build-tools/official-oci/index.json', b'original index')
    config = private_file(copies.root, str(directory.relative_to(copies.root) / ('a' * 64)), b'distinct config')
    source_tar = private_file(copies.root, 'build-inputs/buildkit-v0.34.2/retained.tar', b'original upstream tar')
    keeper_before = retirer.metadata(copies.keeper.stat())
    result = retirer.remove_duplicate(copies.root, described(copies))
    assert not copies.target.exists() and directory.is_dir()
    assert copies.keeper.read_bytes() == copies.payload
    assert retirer.metadata(copies.keeper.stat()) == keeper_before
    assert index.read_bytes() == b'original index' and config.read_bytes() == b'distinct config'
    assert source_tar.read_bytes() == b'original upstream tar'
    assert result['keeperVerifiedAfter'] and result['capturedInodeVerified']
    assert not list((copies.root / result['quarantinePath']).parent.iterdir())


def test_changed_public_keeper_rejects_before_capture(copies):
    descriptor = described(copies); copies.keeper.write_bytes(b'x' * copies.size)
    with pytest.raises(retirer.RetirementError): retirer.remove_duplicate(copies.root, descriptor)
    assert copies.target.read_bytes() == copies.payload


def test_public_capture_of_replaced_keeper_is_retained_never_unlinked(copies, monkeypatch):
    descriptor = described(copies); reservation = retirer.reserve_quarantine(copies.root)
    keeper_inode = copies.keeper.stat().st_ino; capture = retirer._capture_no_replace
    def swap_before_capture(*args, **kwargs):
        os.replace(copies.keeper, copies.target)
        return capture(*args, **kwargs)
    monkeypatch.setattr(retirer, '_capture_no_replace', swap_before_capture)
    with pytest.raises((retirer.RetirementError, OSError)):
        retirer.remove_duplicate(copies.root, descriptor, quarantine=reservation)
    captured = copies.root / reservation['path']
    assert captured.stat().st_ino == keeper_inode and captured.read_bytes() == copies.payload
    assert not copies.keeper.exists()


def upstream(copies, monkeypatch, *, mutation=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:') as archive:
        for index, raw in enumerate(copies.payloads):
            name = 'blobs/sha256/' + sha(raw)
            info = tarfile.TarInfo(name)
            if mutation == 'unsafe' and index == 0: info.name = '../' + name
            if mutation == 'duplicate' and index == 1: info.name = 'blobs/sha256/' + sha(copies.payloads[0])
            if mutation == 'symlink' and index == 0:
                info.type = tarfile.SYMTYPE; info.linkname = 'somewhere'; archive.addfile(info); continue
            if mutation == 'missing' and index == 0: continue
            data = b'x' * len(raw) if mutation == 'wrong_bytes' and index == 0 else raw
            info.size = len(data); archive.addfile(info, io.BytesIO(data))
    raw = output.getvalue(); checksum = sha(raw)
    monkeypatch.setattr(retirer, 'PUBLIC_ARCHIVE_SHA', checksum)
    monkeypatch.setattr(retirer, 'PUBLIC_ARCHIVE_BYTES', len(raw))
    return private_file(copies.root, 'build-inputs/buildkit-v0.34.2/' + checksum + '.tar', raw)


def test_upstream_tar_requires_real_full_file_and_four_member_hashes(copies, monkeypatch):
    path = upstream(copies, monkeypatch)
    proof = retirer.public_layer_archive(copies.root)
    assert proof['sha256'] == sha(path.read_bytes()) and proof['bytes'] == path.stat().st_size
    assert {row['sha256']: row['bytes'] for row in proof['layers']} == retirer.PUBLIC_LAYERS
    assert proof['metadata'] == retirer.metadata(path.stat())


@pytest.mark.parametrize('mutation', ['unsafe', 'duplicate', 'symlink', 'missing', 'wrong_bytes', 'full_sha'])
def test_invalid_public_upstream_does_not_authorize_layers(copies, monkeypatch, mutation):
    path = upstream(copies, monkeypatch, mutation=None if mutation == 'full_sha' else mutation)
    if mutation == 'full_sha':
        raw = path.read_bytes(); path.write_bytes(b'x' + raw[1:])
    with pytest.raises((retirer.RetirementError, tarfile.TarError, OSError)):
        retirer.public_layer_archive(copies.root)
    assert copies.target.read_bytes() == copies.keeper.read_bytes() == copies.payload


def test_upstream_file_must_stay_identical_while_action_runs(copies, monkeypatch):
    path = upstream(copies, monkeypatch)
    with pytest.raises(retirer.RetirementError):
        with retirer.held_public_layer_archive(copies.root):
            raw = path.read_bytes(); path.write_bytes(raw[:-1] + b'x')


@pytest.fixture
def planning(copies, monkeypatch):
    current = {'release': 'ci-999-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}
    identity = {'executionLocation': 'ECS', 'instanceId': 'synthetic', 'machineId': 'c' * 32}
    rows = [{'release': tag, 'commit': retirer.APPROVED_OLD[tag], 'sourceSha256': 'd' * 64, 'controls': {}}
            for tag in (KEEPER, TARGET)]
    request = {'schemaVersion': 1, 'kind': retirer.KIND + '-request', 'current': current, 'identity': identity,
               'protectedReleases': [current['release']], 'candidates': rows}
    raw = retirer.canonical(request)
    private_file(copies.root, 'inbox/' + current['release'] + '/retained-control', b'synthetic')
    proof = {'path': 'global-original-public.tar', 'sha256': 'e' * 64, 'metadata': [1], 'bytes': 1, 'layers': []}
    @contextmanager
    def archive(_root): yield copy.deepcopy(proof)
    calls = []
    def admit(_root, actual_request, row, quiescence):
        assert actual_request == request
        quiescence(copies.root / 'verification' / row['release'] / 'checkout', row['release'], '0123456789')
        return {'context': {key: row[key] for key in ('release', 'commit', 'sourceSha256')},
                'ownerToken': '0123456789', 'controls': {}, 'sourceArchive': {}, 'tools': {}, 'jenkinsResult': 'FAILURE'}
    monkeypatch.setattr(retirer, 'held_public_layer_archive', archive)
    monkeypatch.setattr(retirer, 'admit_public_layer_attempt', admit)
    return SimpleNamespace(copies=copies, current=current, identity=identity, rows=rows, request=request, raw=raw,
                           checksum=sha(raw), proof=proof, calls=calls,
                           quiescence=lambda _checkout, tag, _token: calls.append(tag))


def planned(planning):
    return retirer.plan_public_layers(planning.copies.root, planning.raw, request_sha256=planning.checksum,
        expected_current=planning.current, identity=planning.identity, quiescence=planning.quiescence)


def applied(planning, plan):
    return retirer.apply_public_layers(planning.copies.root, planning.raw, plan, request_sha256=planning.checksum,
        plan_sha256=sha(retirer.canonical(plan)), expected_current=planning.current,
        identity=planning.identity, quiescence=planning.quiescence)


def test_public_plan_has_four_targets_and_no_keeper_deletion(planning):
    plan = planned(planning)
    assert len(plan['candidates']) == 1 and len(plan['candidates'][0]['targets']) == 4
    assert plan['candidateBytes'] == sum(len(raw) for raw in planning.copies.payloads)
    assert plan['keeper']['context']['release'] == KEEPER
    assert {row['release'] for row in plan['candidates'][0]['targets']} == {TARGET}
    assert not plan['deletionPerformed'] and plan['upstreamTarAndKeeper117Preserved']
    assert set(planning.calls) == {KEEPER, TARGET}


def test_public_apply_uses_same_quarantine_core_and_retains_all_real_keepers(planning):
    plan = planned(planning); receipt = applied(planning, plan)
    assert receipt['status'] == 'REMOVED' and len(receipt['deleted']) == 4
    assert not receipt['retainedQuarantinePaths'] and receipt['upstreamTarAndKeeper117Preserved']
    assert not receipt['testsRunByRetirement'] and receipt['directoriesImagesAndBusinessDataPreserved']
    for raw in planning.copies.payloads:
        target, keeper = retirer.duplicate_paths(planning.copies.root, TARGET, kind=retirer.PUBLIC_LAYER_KIND, blob_sha=sha(raw))
        assert not target.exists() and keeper.read_bytes() == raw
    journal = planning.copies.root / 'inbox' / planning.current['release'] / 'native-public-layer-duplicate-journal.jsonl'
    assert sha(journal.read_bytes()) == receipt['journalSha256']
    phases = [json.loads(row)['phase'] for row in journal.read_bytes().splitlines()]
    assert phases.count('DELETE_STARTED') == phases.count('DELETE_FINISHED') == 4


def test_missing_one_keeper_or_target_skips_whole_attempt_without_deletion(planning):
    planning.copies.keeper.unlink()
    plan = planned(planning)
    assert not plan['candidates'] and plan['skipped'] and plan['archive'] is None
    receipt = applied(planning, plan)
    assert receipt['status'] == 'NO_ACTION' and not receipt['deleted']
    assert planning.copies.target.read_bytes() == planning.copies.payload


def test_changed_archive_after_plan_produces_unknown_receipt_without_mutation(planning):
    plan = planned(planning); planning.proof['bytes'] += 1
    receipt = applied(planning, plan)
    assert receipt['status'] == 'FAILED_OR_UNKNOWN' and not receipt['deleted'] and not receipt['mutationAttempted']
    assert planning.copies.target.read_bytes() == planning.copies.keeper.read_bytes() == planning.copies.payload


def test_changed_public_target_after_plan_is_not_deleted(planning):
    plan = planned(planning); planning.copies.target.write_bytes(b'x' * planning.copies.size)
    receipt = applied(planning, plan)
    assert receipt['status'] == 'FAILED_OR_UNKNOWN' and not receipt['deleted']
    assert planning.copies.target.read_bytes() == b'x' * planning.copies.size
    assert planning.copies.keeper.read_bytes() == planning.copies.payload


@pytest.mark.parametrize('source', ['same', 'ancestor', 'descendant'])
def test_public_quiescence_rejects_any_tag_bind_to_old_inbox_tools(copies, source):
    tools = copies.root / 'inbox' / TARGET / 'candidate-build-tools'
    path = tools if source == 'same' else tools.parent if source == 'ancestor' else tools / 'official-oci'
    cleanup = SimpleNamespace(docker_snapshot=lambda: [('x', False, False, 0, 'other-tag', 'other-token',
                                                        [{'Type': 'bind', 'Source': str(path)}])])
    original_calls = []
    check = retirer.public_layer_quiescence(copies.root, cleanup, lambda *args: original_calls.append(args))
    with pytest.raises(retirer.RetirementError): check(copies.root / 'verification' / TARGET / 'checkout', TARGET, 'token')
    assert len(original_calls) == 1
