"""ECS filesystem tests for server-only archive reuse, never online store access."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


reuse = load('server_only_legacy_source_reuse', 'script/jenkins/reuse-legacy-source.py')
support = load('server_reuse_finished_build_fixture', 'tests_python/test_jenkins_ecs_build_cleanup.py')
profiles = load('server_reuse_frozen_profile_fixture', 'tests_python/test_legacy_preservation_profiles.py')
# Reuse the complete synthetic CI claim/tool/report fixture, not real CI paths.
state = support.state


@pytest.fixture
def archive_state(state, monkeypatch):
    migration = profiles.migration
    source_archive = state.inbox / 'source.tar.gz'
    with tarfile.open(source_archive, 'r:gz') as source:
        members = {entry.name: source.extractfile(entry).read() for entry in source if entry.isfile()}
    members['script/memory/migrate_legacy_stores.py'] = Path(migration.__file__).read_bytes()
    support.package(source_archive, members, 'a' * 40)
    source_sha = reuse.digest(source_archive)
    manifest = support.cleanup.read_json(state.manifest); manifest['sourceSha256'] = source_sha
    support.put_json(state.manifest, manifest)
    claim_file = state.attempt / '.verification-claimed/claim.json'
    claim = support.cleanup.read_json(claim_file); claim['sourceSha256'] = source_sha; support.put_json(claim_file, claim)
    tools_file = state.evidence / 'tool-runtime.json'; tools = support.cleanup.read_json(tools_file)
    tools['sourceSha256'] = source_sha; tools['manifestSha256'] = reuse.digest(state.manifest)
    tools['cleanup']['manifestSha256'] = reuse.digest(state.manifest); support.put_json(tools_file, tools)
    inner = support.cleanup.read_json(state.evidence / 'receipt.json'); inner['status'] = 'PASS'
    inner['commands'][0]['exitCode'] = 0; support.put_json(state.evidence / 'receipt.json', inner)
    state.record.update(sourceSha256=source_sha, status='PASS', verificationExitCode=0)
    support.seal(state)
    # The cleanup fixture already owns this directory and a placeholder tar.
    # Replace only that synthetic placeholder with the valid closed archive.
    snapshot = state.checkout / 'work/legacy-source-snapshot'
    assert snapshot.is_dir() and {path.name for path in snapshot.iterdir()} == {'originals.tar'}
    frozen = profiles.profile_manifest(monkeypatch, kafka=True)
    with tarfile.open(snapshot / 'originals.tar', 'w:gz', format=tarfile.PAX_FORMAT) as package:
        for row in frozen['files']:
            entry = tarfile.TarInfo(row['path']); entry.size = 6; package.addfile(entry, io.BytesIO(b'opaque'))
    (snapshot / 'originals.tar').chmod(0o600)
    frozen['archiveSha256'] = reuse.digest(snapshot / 'originals.tar')
    migration.private_json(snapshot / 'snapshot.json', frozen)
    restore = state.checkout / 'work/legacy-source-restore'
    result = migration.verify_preservation(snapshot, restore)
    migration.private_json(snapshot / 'verification.stdout.json', result)
    support.put(snapshot / 'verification.stderr', b'')
    plan = migration.validate_preservation_plan(frozen)
    public = {**result, 'kind': 'doorhandle-legacy-source-preservation', 'schemaVersion': 1,
        'release': support.OLD, 'commit': 'a' * 40, 'sourceSha256': source_sha,
        'scriptSha256': reuse.digest(Path(migration.__file__)), 'identity': support.IDENTITY,
        'restoreReceiptSha256': reuse.digest(restore / 'restore-receipt.json'),
        'verificationReceiptSha256': reuse.digest(state.attempt / 'verification-receipt.json'),
        'archiveBytes': (snapshot / 'originals.tar').stat().st_size,
        'manifestBytes': (snapshot / 'snapshot.json').stat().st_size,
        **{key: plan[key] for key in ('profile', 'archiveEncoding', 'kafkaFiles', 'kafkaBytes')},
        'legacyKafkaReplay': 'NOT_PERFORMED'}
    migration.private_json(snapshot / 'preservation-public.json', public)
    state.snapshot, state.public, state.migration = snapshot, public, migration
    monkeypatch.setattr(reuse, 'available', lambda _path: 16 * 1024 ** 3)
    return state


def admitted(state):
    return reuse.admit_snapshot(state.root, state.snapshot, support.CURRENT, support.IDENTITY,
                                state.migration, support.cleanup, support.remote)


def test_verified_archive_is_reused_without_local_data_or_old_original_mutation(archive_state):
    state = archive_state; result = admitted(state)
    before = {file.name: file.read_bytes() for file in state.snapshot.iterdir()}
    target = state.root / 'verification' / support.CURRENT / 'checkout/work/legacy-source-snapshot'
    target.mkdir(parents=True, mode=0o700)
    for name, sha in [('snapshot.json', state.public['snapshotManifestSha256']), ('originals.tar', state.public['archiveSha256'])]:
        reuse.copy_private(state.snapshot / name, target / name, sha, state.root)
    restored = target.with_name('legacy-source-restore')
    proof = state.migration.verify_preservation(target, restored)
    assert proof == result['restore']
    for row in result['manifest']['files']:
        file = restored / row['path']
        assert file.read_bytes() == b'opaque' and file.stat().st_mode & 0o777 == 0o600
    assert {file.name: file.read_bytes() for file in state.snapshot.iterdir()} == before


def test_a_completed_mysql_build_can_supply_the_same_immutable_archive(archive_state):
    state = archive_state
    inner = support.cleanup.read_json(state.evidence / 'receipt.json'); inner['scopeKind'] = 'mysql'
    support.put_json(state.evidence / 'receipt.json', inner)
    state.record.update(scope='mysql', fixtureReadinessValidated=True)
    support.seal(state)
    public = copy.deepcopy(state.public)
    public['verificationReceiptSha256'] = reuse.digest(state.attempt / 'verification-receipt.json')
    support.put_json(state.snapshot / 'preservation-public.json', public)
    assert admitted(state)['public']['profile'] == state.migration.PRESERVATION_KAFKA_PROFILE


def test_a_previously_reused_cloud_snapshot_remains_reusable_without_local_files(archive_state):
    state = archive_state; public = copy.deepcopy(state.public)
    public['memberInventorySha256'] = state.migration.validate_preservation_plan(
        state.migration.read_json(state.snapshot / 'snapshot.json'))['memberInventorySha256']
    public['sourceSnapshotReuse'] = {'kind': 'doorhandle-ecs-legacy-snapshot-reuse-v1',
        'release': 'ci-69-' + 'f' * 12, 'publicSha256': 'f' * 64, 'oldOriginalsPreserved': True}
    support.put_json(state.snapshot / 'reuse-resource-proof.json', {'status': 'COPY_AND_RESTORE_COMPLETED'})
    support.put_json(state.snapshot / 'preservation-public.json', public)
    assert admitted(state)['public']['sourceSnapshotReuse']['oldOriginalsPreserved'] is True


@pytest.mark.parametrize('which', ['outside-root', 'runtime', 'descendant', 'same-build', 'future-build'])
def test_only_an_exact_older_same_root_snapshot_path_is_admitted(archive_state, which):
    state = archive_state
    source = {'outside-root': state.root.parent / 'elsewhere', 'runtime': state.root / 'runtime/legacy-source-snapshot',
        'descendant': state.snapshot / 'child', 'same-build': state.root / 'verification' / support.CURRENT / 'checkout/work/legacy-source-snapshot',
        'future-build': state.root / 'verification' / ('ci-99-' + 'f' * 12) / 'checkout/work/legacy-source-snapshot'}[which]
    with pytest.raises(ValueError):
        reuse.admit_snapshot(state.root, source, support.CURRENT, support.IDENTITY, state.migration, support.cleanup, support.remote)
    assert (state.snapshot / 'originals.tar').exists()


@pytest.mark.parametrize('change', ['archive', 'manifest', 'public-sha', 'restore-proof', 'failed-marker', 'unfinished-build', 'wrong-identity'])
def test_old_public_build_archive_and_restore_proofs_cannot_drift(archive_state, change):
    state = archive_state
    if change in ('archive', 'manifest'):
        path = state.snapshot / ('originals.tar' if change == 'archive' else 'snapshot.json')
        path.write_bytes(path.read_bytes() + b'changed')
    elif change == 'restore-proof': support.put_json(state.checkout / 'work/legacy-source-restore/restore-receipt.json', {})
    elif change == 'failed-marker': support.put_json(state.snapshot / 'preservation-failed.json', {'status': 'FAILED'})
    elif change == 'unfinished-build':
        receipt = copy.deepcopy(state.record); receipt.pop('finishedAt')
        support.put_json(state.attempt / 'verification-receipt.json', receipt)
    else:
        public = copy.deepcopy(state.public)
        if change == 'public-sha': public['archiveSha256'] = '0' * 64
        else: public['identity'] = {**support.IDENTITY, 'machineId': 'f' * 32}
        support.put_json(state.snapshot / 'preservation-public.json', public)
    with pytest.raises((ValueError, state.migration.MigrationError)): admitted(state)


@pytest.mark.parametrize('change', ['symlink', 'hardlink', 'public-permission', 'writable-ancestor'])
def test_links_and_insecure_private_permissions_refuse_cloud_reuse(archive_state, change):
    state = archive_state
    if change == 'symlink':
        file = state.snapshot / 'snapshot.json'; original = file.with_name('moved.json'); file.rename(original); file.symlink_to(original)
    elif change == 'hardlink': os.link(state.snapshot / 'originals.tar', state.root / 'external-hardlink.tar')
    elif change == 'public-permission': (state.snapshot / 'snapshot.json').chmod(0o644)
    else: state.snapshot.parent.chmod(0o777)
    with pytest.raises(ValueError): admitted(state)


def test_a_still_present_old_container_prevents_reuse_of_an_active_build(archive_state, monkeypatch):
    monkeypatch.setattr(support.cleanup, 'docker_snapshot', lambda: [['1' * 64, True, False, 123, support.OLD, None, []]])
    with pytest.raises(ValueError, match='CONTAINER_STILL_PRESENT'): admitted(archive_state)


def test_current_fixed_commit_must_have_its_own_actual_pass_receipt(archive_state):
    state = archive_state; file = state.root / 'verification' / support.CURRENT / 'verification-receipt.json'
    value = {**state.record, 'release': support.CURRENT, 'commit': 'c' * 40}
    support.put_json(file, value)
    assert reuse.passing_receipt(file, state.root, support.CURRENT, support.IDENTITY)['commit'] == 'c' * 40
    value['status'] = 'FAILED'; support.put_json(file, value)
    with pytest.raises(ValueError, match='TERMINAL_PASS'): reuse.passing_receipt(file, state.root, support.CURRENT, support.IDENTITY)


def test_real_file_block_rounding_directories_metadata_and_true_reserve_are_budgeted():
    value = reuse.disk_budget(1001, 2001, 9000, 5, 9, 4096)
    assert value['copyAllocationBoundBytes'] == 3 * 4096
    assert value['restoreAllocationBoundBytes'] == 9000 + 5 * 4095 + 9 * 4096
    assert value['requiredAvailableBytes'] == reuse.RESERVE + value['copyAllocationBoundBytes'] + value['restoreAllocationBoundBytes'] + 4096 + 4 * reuse.MIB
    assert reuse.disk_budget(1001, 2001, 9000, 5, 9, 65536)['requiredAvailableBytes'] > value['requiredAvailableBytes']
    with pytest.raises(ValueError): reuse.disk_budget(1, 1, 1, 0, 1, 4096)


def test_copy_does_not_overwrite_a_target_or_continue_below_the_real_reserve(archive_state, monkeypatch):
    state = archive_state; source = state.snapshot / 'originals.tar'; destination = state.root / 'new-copy.tar'
    support.put(destination, b'keep-existing')
    with pytest.raises(FileExistsError): reuse.copy_private(source, destination, reuse.digest(source), state.root)
    assert destination.read_bytes() == b'keep-existing'
    monkeypatch.setattr(reuse, 'available', lambda _path: reuse.RESERVE)
    with pytest.raises(ValueError, match='TRUE_DISK_RESERVE'):
        reuse.copy_private(source, state.root / 'interrupted-copy.tar', reuse.digest(source), state.root)
    assert source.read_bytes() == (state.snapshot / 'originals.tar').read_bytes()


def test_private_copy_hash_drift_is_rejected_without_modifying_the_source(archive_state):
    state = archive_state; source = state.snapshot / 'originals.tar'; before = source.read_bytes()
    with pytest.raises(ValueError, match='SOURCE_CHANGED'):
        reuse.copy_private(source, state.root / 'rejected-copy.tar', '0' * 64, state.root)
    assert source.read_bytes() == before


def test_restore_pressure_terminates_only_its_new_owned_process_group(archive_state, tmp_path, monkeypatch):
    snapshot = tmp_path / 'new-restore-attempt'; snapshot.mkdir(mode=0o700)
    calls = []; killed = []
    class Child:
        pid = 444444
        returncode = None
        def poll(self): return self.returncode
        def wait(self, timeout=None): self.returncode = -15; return self.returncode
    child = Child()
    def spawn(*args, **kwargs): calls.append((args, kwargs)); return child
    monkeypatch.setattr(reuse.subprocess, 'Popen', spawn)
    monkeypatch.setattr(reuse.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(reuse, 'available', lambda _path: reuse.RESERVE - 1)
    args = SimpleNamespace(instance_id='i-fixture123', machine_id='d' * 32)
    with pytest.raises(ValueError, match='OWNED_RESTORE_RESOURCE'):
        reuse.restore_process(Path(archive_state.migration.__file__), snapshot,
                              snapshot.with_name('new-restore-data'), args)
    assert killed == [(child.pid, reuse.signal.SIGTERM)]
    assert calls[0][1]['start_new_session'] is True
    assert calls[0][1]['env'] == {'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1',
                                 'PYTHONNOUSERSITE': '1', 'PYTHON_DOTENV_DISABLED': '1'}
    assert (archive_state.snapshot / 'originals.tar').is_file()


def test_reuse_recipe_and_entire_import_closure_are_bound_to_the_fixed_source_archive(archive_state):
    state = archive_state; checkout = state.root / 'verification' / support.CURRENT / 'checkout'
    inbox = state.root / 'inbox' / support.CURRENT
    executor = support.put(inbox / 'reuse-legacy-source.py', b'# immutable reuse recipe\n')
    members = {'script/jenkins/reuse-legacy-source.py': executor.read_bytes()}
    for name in ('script/jenkins/cleanup-ecs-builds.py', 'script/jenkins/verify-remote.py', 'script/memory/migrate_legacy_stores.py'):
        raw = ('# immutable ' + name).encode(); support.put(checkout / name, raw); members[name] = raw
    source = inbox / 'source.tar.gz'; support.package(source, members, 'c' * 40)
    args = SimpleNamespace(root=str(state.root), tag=support.CURRENT, commit='c' * 40, source_sha256=reuse.digest(source))
    assert reuse.fixed_source(args, executor=executor) == checkout
    (checkout / 'script/memory/migrate_legacy_stores.py').write_bytes(b'raise RuntimeError("never import changed code")')
    with pytest.raises(ValueError, match='RECIPE_DIFFERS'): reuse.fixed_source(args, executor=executor)


def test_refusal_exposes_only_a_literal_guard_and_own_source_locations():
    try:
        reuse.need(False, 'CURRENT_DISK_CANNOT_RETAIN_COPY_RESTORE_AND_RESERVE')
    except ValueError as error:
        details = reuse.refusal_details(error)
    assert details['errorType'] == 'ValueError'
    assert details['guardCode'] == 'CURRENT_DISK_CANNOT_RETAIN_COPY_RESTORE_AND_RESERVE'
    assert details['locations'] == [{'function': 'need', 'line': reuse.need.__code__.co_firstlineno + 1}]
    assert set(details) == {'errorType', 'guardCode', 'locations'}


@pytest.mark.parametrize('error', [ValueError('PRIVATE_SQL_AND_MODEL_KEY'),
                                  ValueError('UNREVIEWED_UPPERCASE_CODE'),
                                  ValueError('COPY_REACHED_TRUE_DISK_RESERVE'),
                                  ValueError('COPY_REACHED_TRUE_DISK_RESERVE', 'private-extra'),
                                  RuntimeError('COPY_REACHED_TRUE_DISK_RESERVE')])
def test_unreviewed_exception_payloads_never_become_public_refusal_codes(error):
    details = reuse.refusal_details(error)
    assert details == {'errorType': type(error).__name__, 'guardCode': 'UNCLASSIFIED_REFUSAL', 'locations': []}
    assert 'PRIVATE_SQL_AND_MODEL_KEY' not in json.dumps(details)
    assert 'private-extra' not in json.dumps(details)


def test_main_keeps_fixed_refusal_reason_without_printing_args_or_exception_payload(monkeypatch, capsys):
    def denied(_args):
        reuse.need(False, 'CURRENT_DISK_CANNOT_RETAIN_COPY_RESTORE_AND_RESERVE')
    monkeypatch.setattr(reuse, 'run', denied)
    monkeypatch.setattr(reuse.sys, 'argv', ['reuse-legacy-source.py', *[
        item for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id', 'source-snapshot')
        for item in ('--' + name, 'private-value')]])
    assert reuse.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ''
    details = json.loads(captured.err)
    assert details['status'] == 'REFUSED'
    assert details['guardCode'] == 'CURRENT_DISK_CANNOT_RETAIN_COPY_RESTORE_AND_RESERVE'
    assert {row['function'] for row in details['locations']} == {'main', 'need'}
    assert 'private-value' not in captured.err
