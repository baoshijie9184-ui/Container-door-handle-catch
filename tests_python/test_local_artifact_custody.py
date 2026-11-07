"""Run only on ECS: closed opaque bytes, independently restored, never activated."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tarfile
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('opaque_local_artifact_custody', ROOT / 'script/jenkins/preserve-local-artifacts.py')
custody = importlib.util.module_from_spec(spec); spec.loader.exec_module(custody)


@pytest.fixture
def originals(tmp_path, monkeypatch):
    source = tmp_path / 'originals'; source.mkdir(mode=0o700)
    names = [('logs/private.log', 'logs', b'opaque log\x00not displayed'),
             ('uploads/private.bin', 'uploads', b'head' + bytes(2048)),
             ('work/cloud/opaque.pth', 'historical-archives', b'opaque model bytes, never loaded')]
    for name, _, body in names:
        path = source / name; path.parent.mkdir(mode=0o700, parents=True, exist_ok=True); path.write_bytes(body)
    monkeypatch.setattr(custody, 'SOURCE_ROOT', str(source))
    monkeypatch.setattr(custody, 'FILE_COUNT', len(names))
    monkeypatch.setattr(custody.shutil, 'disk_usage', lambda _: SimpleNamespace(free=10 * 1024 ** 3))
    parent = source / 'work/data-migration-fixture'; parent.mkdir(mode=0o700)
    catalog = tmp_path / 'catalog.json'
    def pin():
        rows = [{'path': name, 'group': group, 'bytes': (source / name).stat().st_size,
                 'sha256': custody.digest(source / name)} for name, group, _ in names]
        total = sum(row['bytes'] for row in rows)
        inventory = [[row['group'], row['path'], row['bytes'], row['sha256']] for row in rows]
        monkeypatch.setattr(custody, 'ORIGINAL_BYTES', total)
        monkeypatch.setattr(custody, 'CATALOG_SHA256', hashlib.sha256(custody.encoded(sorted(inventory))).hexdigest())
        value = {'kind': 'doorhandle-additional-local-data-inventory', 'observedAtUtc': '2026-11-07T00:00:00Z',
            'readOnlySources': True, 'notUploaded': True, 'files': len(rows), 'bytes': total, 'members': rows}
        catalog.write_bytes(custody.encoded(value))
        return value
    pin()
    return SimpleNamespace(source=source, names=names, parent=parent, catalog=catalog, pin=pin)


def create_attempt(tmp_path, monkeypatch, package, number=71):
    root = tmp_path / 'ecs'; root.mkdir(mode=0o700, exist_ok=True)
    commit = 'a' * 40; tag = 'ci-' + str(number) + '-' + commit[:12]
    for path in (root / 'verification', root / 'verification' / tag,
                 root / 'verification' / tag / 'checkout', root / 'verification' / tag / 'checkout/work',
                 root / 'inbox', root / 'inbox' / tag):
        path.mkdir(mode=0o700, exist_ok=True)
    checkout = root / 'verification' / tag / 'checkout'
    # The ordinary verifier creates this shared CI ancestor with the host umask.
    # Only the new custody snapshot/restore themselves must be 0700.
    (checkout / 'work').chmod(0o755)
    source = root / 'inbox' / tag / 'source.tar.gz'
    raw = Path(custody.__file__).read_bytes()
    with tarfile.open(source, 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': commit}) as archive:
        entry = tarfile.TarInfo('script/jenkins/preserve-local-artifacts.py'); entry.size = len(raw)
        archive.addfile(entry, io.BytesIO(raw))
    identity = {'instanceId': 'i-test123', 'machineId': 'b' * 32, 'executionLocation': 'ECS'}
    monkeypatch.setattr(custody, 'ROOT', checkout)
    monkeypatch.setattr(custody, 'identity', lambda instance, machine: identity)
    monkeypatch.setattr(custody, 'resource_guard', lambda *unused: None)
    receipt = {'status': 'PASS', 'verificationExitCode': 0, 'release': tag, 'commit': commit,
               'sourceSha256': custody.digest(source), 'identity': identity}
    custody.write_json(checkout.parent / 'verification-receipt.json', receipt)
    return SimpleNamespace(root=str(root), tag=tag, commit=commit, source_sha256=receipt['sourceSha256'],
        expected_instance_id=identity['instanceId'], expected_machine_id=identity['machineId'],
        manifest_sha256=custody.digest(package / 'custody.json'), archive_sha256=custody.digest(package / 'originals.tar'),
        manifest_bytes=(package / 'custody.json').stat().st_size, archive_bytes=(package / 'originals.tar').stat().st_size,
        source_receipt_sha256=None), checkout / 'work'


def upload(package, work):
    for name in ('custody.json', 'originals.tar'):
        target = work / custody.SNAPSHOT / name
        target.write_bytes((package / name).read_bytes())
        target.chmod(0o600)


@pytest.fixture
def residual_originals(tmp_path, monkeypatch):
    for field in custody.PROFILE_FIELDS:
        monkeypatch.setattr(custody, field, getattr(custody, field))
    custody.select_profile('residual-project-originals-v1')
    source = tmp_path / 'opaque-residuals'; source.mkdir(mode=0o700)
    parent = source / 'work/data-migration-residual'; parent.mkdir(parents=True, mode=0o700)
    rows = [('work/case/plain.sql', 'residual-sql', b'opaque sql bytes\x00never executed'),
            ('work/case/archive.sql.gz', 'residual-sql', b'\x1f\x8bopaque-not-decompressed'),
            ('work/case/model.onnx', 'residual-model', b'opaque-model-never-deserialized')]
    for name, _, raw in rows:
        path = source / name; path.parent.mkdir(mode=0o700, parents=True, exist_ok=True); path.write_bytes(raw)
    monkeypatch.setattr(custody, 'SOURCE_ROOT', str(source))
    monkeypatch.setattr(custody, 'FILE_COUNT', len(rows))
    monkeypatch.setattr(custody, 'ORIGINAL_BYTES', sum(len(raw) for _, _, raw in rows))
    monkeypatch.setattr(custody.shutil, 'disk_usage', lambda _: SimpleNamespace(free=10 * 1024 ** 3))
    members = [{'group': group, 'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
               for name, group, raw in rows]
    monkeypatch.setattr(custody, 'CATALOG_SHA256', hashlib.sha256(custody.encoded(sorted(
        [[r['group'], r['path'], r['bytes'], r['sha256']] for r in members]))).hexdigest())
    catalog = tmp_path / 'residual-catalog.json'
    catalog.write_bytes(custody.encoded({'kind': 'doorhandle-additional-local-data-inventory',
        'observedAtUtc': '2026-11-07T00:00:00Z', 'readOnlySources': True, 'notUploaded': True,
        'files': len(rows), 'bytes': custody.ORIGINAL_BYTES, 'members': members}))
    calls = []
    def metadata_only(args, **kwargs):
        calls.append(args)
        assert args[:3] == ['git', '-C', str(source)]
        if args[3:] == ['worktree', 'list', '--porcelain', '-z']:
            return SimpleNamespace(returncode=0, stdout=('worktree ' + str(source) + '\0\0').encode())
        assert args[3:] == ['ls-files', '-z']
        return SimpleNamespace(returncode=0, stdout=b'')
    monkeypatch.setattr(custody.subprocess, 'run', metadata_only)
    return SimpleNamespace(source=source, parent=parent, catalog=catalog, members=members,
                           rows=rows, calls=calls, metadata_only=metadata_only)


def test_original_default_profile_facts_and_limits_are_not_replaced_by_residual_profile(monkeypatch):
    for field in custody.PROFILE_FIELDS:
        monkeypatch.setattr(custody, field, getattr(custody, field))
    original = dict(custody.PROFILES[custody.DEFAULT_PROFILE])
    custody.select_profile('residual-project-originals-v1')
    assert custody.FILE_COUNT == 1968 and custody.ORIGINAL_BYTES == 8779830
    assert custody.MAX_BYTES == 32 * 1024 ** 2 and custody.MAX_MANIFEST == 2 * 1024 ** 2
    custody.select_profile(custody.DEFAULT_PROFILE)
    assert {field: getattr(custody, field) for field in custody.PROFILE_FIELDS} == original
    assert custody.FILE_COUNT == 36 and custody.ORIGINAL_BYTES == 465240718
    assert custody.CATALOG_SHA256 == 'e1258807aae1df63412e2190268351b1d63e770219ce9aba2d760f2f1bae1383'


def test_residual_opaque_pack_restore_and_later_reuse_bind_the_same_private_bytes(residual_originals, tmp_path, monkeypatch):
    fixture = residual_originals; package = fixture.parent / 'package'
    before = {name: custody.digest(fixture.source / name) for name, _, _ in fixture.rows}
    custody.pack(fixture.catalog, package)
    args, work = create_attempt(tmp_path, monkeypatch, package)
    custody.prepare(args); upload(package, work); first = custody.verify_restore(args)
    assert first['profile'] == 'residual-project-originals-v1'
    assert first['databasesOpened'] == first['modelsExecuted'] == first['originalFilesDeleted'] == 0
    old = work / custody.SNAPSHOT
    args, newer = create_attempt(tmp_path, monkeypatch, package, number=72)
    args.source_snapshot_directory = str(old)
    description = custody.describe(args)
    args.source_receipt_sha256 = description['sourceCustodyReceiptSha256']
    second = custody.reuse(args)
    assert second['status'] == 'RESTORED_VERIFIED' and second['files'] == len(fixture.rows)
    assert second['sourceCustodyReceiptSha256'] == description['sourceCustodyReceiptSha256']
    assert custody.SNAPSHOT == 'residual-project-originals-snapshot'
    assert before == {name: custody.digest(fixture.source / name) for name, _, _ in fixture.rows}
    assert not (newer / 'additional-local-artifacts-snapshot').exists()
    assert all(custody.digest(newer / custody.RESTORE / name) == digest for name, digest in before.items())


@pytest.mark.parametrize('where', ['registered-worktree', 'tracked-source', 'nested-git', 'protected-jenkins'])
def test_residual_scope_refuses_source_roots_before_any_original_permission_or_content_read(residual_originals, monkeypatch, where):
    fixture = residual_originals
    def metadata(args, **kwargs):
        if where == 'registered-worktree' and args[3:] == ['worktree', 'list', '--porcelain', '-z']:
            return SimpleNamespace(returncode=0, stdout=('worktree ' + str(fixture.source) + '\0\0worktree '
                + str(fixture.source / 'work/case') + '\0\0').encode())
        if where == 'tracked-source' and args[3:] == ['ls-files', '-z']:
            return SimpleNamespace(returncode=0, stdout=b'work/case/plain.sql\0')
        return fixture.metadata_only(args, **kwargs)
    monkeypatch.setattr(custody.subprocess, 'run', metadata)
    if where == 'nested-git': (fixture.source / 'work/case/.git').mkdir()
    monkeypatch.setattr(custody, 'permissions', lambda *_: pytest.fail('source bytes/permissions read before root admission'))
    if where == 'protected-jenkins':
        with pytest.raises(custody.CustodyError): custody.residual_repository_guard([fixture.source / 'work/jenkins/private.sql'])
    else:
        with pytest.raises(custody.CustodyError): custody.pack(fixture.catalog, fixture.parent / 'rejected')


@pytest.mark.parametrize('damage', ['profile', 'catalogue', 'extra-member', 'old-group'])
def test_residual_manifest_cannot_be_accepted_as_original_36_or_widen_its_closed_set(residual_originals, damage):
    package = residual_originals.parent / 'package'; custody.pack(residual_originals.catalog, package)
    manifest = custody.read_json(package / 'custody.json')
    if damage == 'profile': manifest['profile'] = custody.DEFAULT_PROFILE
    elif damage == 'catalogue': manifest['catalogSha256'] = custody.PROFILES[custody.DEFAULT_PROFILE]['CATALOG_SHA256']
    elif damage == 'extra-member': manifest['files'].append(dict(manifest['files'][0]))
    else: manifest['files'][0]['group'] = 'logs'
    with pytest.raises(custody.CustodyError): custody.validate_manifest(manifest)


def test_pack_copies_only_pinned_opaque_bytes_and_retains_private_original_permissions(originals, monkeypatch):
    monkeypatch.setattr(custody, 'identity', lambda *args: pytest.fail('pack must not contact ECS'))
    package = originals.parent / 'package'
    before = {name: custody.digest(originals.source / name) for name, _, _ in originals.names}
    result = custody.pack(originals.catalog, package)
    assert result['status'] == 'PACKED' and result['files'] == 3
    manifest = custody.read_json(package / 'custody.json'); custody.validate_manifest(manifest)
    assert set(p.name for p in package.iterdir()) == {'custody.json', 'originals.tar'}
    assert stat.S_IMODE(package.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in package.iterdir())
    assert all({'mode', 'uid', 'gid', 'atimeNs', 'mtimeNs'} <= set(row['permissions']) for row in manifest['files'])
    with tarfile.open(package / 'originals.tar', 'r:') as archive:
        assert len(archive.getmembers()) == 3
        for member in archive:
            assert member.isfile() and not member.islnk()
            assert hashlib.sha256(archive.extractfile(member).read()).hexdigest() == before[member.name]
    assert before == {name: custody.digest(originals.source / name) for name, _, _ in originals.names}


@pytest.mark.parametrize('mutation', ['extra-secret', 'changed-hash', 'changed-group'])
def test_unreviewed_catalog_is_rejected_before_any_original_is_opened(originals, monkeypatch, mutation):
    value = json.loads(originals.catalog.read_bytes())
    if mutation == 'extra-secret':
        value['members'].append({'path': str(originals.source / 'work/cloud/private.env'), 'group': 'logs', 'bytes': 1, 'sha256': '0' * 64})
    elif mutation == 'changed-hash': value['members'][0]['sha256'] = '0' * 64
    else: value['members'][0]['group'] = 'uploads'
    originals.catalog.write_bytes(custody.encoded(value))
    original_digest = custody.digest
    monkeypatch.setattr(custody, 'digest', lambda path: original_digest(path) if Path(path) == originals.catalog
                        else pytest.fail('unreviewed original must not be read'))
    with pytest.raises(custody.CustodyError): custody.pack(originals.catalog, originals.parent / 'rejected')


def test_linked_source_is_refused_and_hardlinks_are_copied_as_full_regular_members(originals):
    first = originals.source / originals.names[0][0]; second = originals.source / originals.names[1][0]
    second.unlink(); os.link(first, second); originals.pin()
    package = originals.parent / 'hardlinks'; custody.pack(originals.catalog, package)
    with tarfile.open(package / 'originals.tar', 'r:') as archive:
        entries = archive.getmembers(); assert all(p.isfile() and not p.islnk() for p in entries)
        assert archive.extractfile(entries[0]).read() == archive.extractfile(entries[1]).read()
    second.unlink(); second.symlink_to(first)
    with pytest.raises(custody.CustodyError, match='Linked'): custody.pack(originals.catalog, originals.parent / 'symlink-rejected')


def test_concurrent_source_change_retains_partial_package_and_never_marks_it_complete(originals, monkeypatch):
    add = tarfile.TarFile.addfile; changed = False
    def changing(archive, info, stream=None):
        nonlocal changed
        result = add(archive, info, stream)
        if not changed:
            changed = True
            path = originals.source / info.name; path.write_bytes(path.read_bytes() + b'changed')
        return result
    monkeypatch.setattr(tarfile.TarFile, 'addfile', changing)
    package = originals.parent / 'changed'
    with pytest.raises(custody.CustodyError, match='changed'): custody.pack(originals.catalog, package)
    assert not (package / 'custody.json').exists()


@pytest.mark.parametrize('mutation', ['extra-key', 'changed-sha', 'foreign-root', 'traversal', 'omitted-member', 'encoding', 'oversize', 'group'])
def test_manifest_remains_a_closed_catalog_not_an_arbitrary_archive_plan(originals, mutation):
    package = originals.parent / 'package'; custody.pack(originals.catalog, package)
    value = custody.read_json(package / 'custody.json')
    if mutation == 'extra-key': value['secret'] = 'not admitted'
    elif mutation == 'changed-sha': value['files'][0]['sha256'] = '0' * 64
    elif mutation == 'foreign-root': value['files'][0]['sourcePath'] = '/somewhere/else/private'
    elif mutation == 'traversal': value['files'][0]['member'] = '../private'
    elif mutation == 'omitted-member': value['files'].pop()
    elif mutation == 'encoding': value['archiveEncoding'] = 'TAR_GZIP'
    elif mutation == 'oversize': value['archiveBytes'] = custody.MAX_BYTES + 1
    else: value['files'][0]['group'] = 'uploads'
    with pytest.raises(custody.CustodyError): custody.validate_manifest(value)


@pytest.mark.parametrize('mutation', ['failed-verification', 'wrong-identity', 'source-tamper', 'helper-tamper'])
def test_remote_admission_binds_actual_pass_identity_and_exact_committed_helper(originals, tmp_path, monkeypatch, mutation):
    package = originals.parent / 'package'; custody.pack(originals.catalog, package)
    args, work = create_attempt(tmp_path, monkeypatch, package)
    receipt_file = work.parent.parent / 'verification-receipt.json'
    if mutation in ('failed-verification', 'wrong-identity'):
        value = custody.read_json(receipt_file)
        if mutation == 'failed-verification': value['status'] = 'FAILED'
        else: value['identity']['machineId'] = 'c' * 32
        receipt_file.write_bytes(custody.encoded(value))
    elif mutation == 'source-tamper':
        source = Path(args.root) / 'inbox' / args.tag / 'source.tar.gz'; source.write_bytes(b'changed')
    else:
        source = Path(args.root) / 'inbox' / args.tag / 'source.tar.gz'
        with tarfile.open(source, 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': args.commit}) as archive:
            entry = tarfile.TarInfo('script/jenkins/preserve-local-artifacts.py'); entry.size = 1
            archive.addfile(entry, io.BytesIO(b'x'))
        args.source_sha256 = custody.digest(source)
        value = custody.read_json(receipt_file); value['sourceSha256'] = args.source_sha256; receipt_file.write_bytes(custody.encoded(value))
    with pytest.raises(custody.CustodyError): custody.prepare(args)
    assert not (work / custody.SNAPSHOT).exists()


def test_ecs_independent_restore_preserves_all_bytes_and_returns_only_public_counts_and_hashes(originals, tmp_path, monkeypatch):
    package = originals.parent / 'package'; custody.pack(originals.catalog, package)
    args, work = create_attempt(tmp_path, monkeypatch, package)
    assert custody.prepare(args)['status'] == 'PREPARED'; upload(package, work)
    receipt = custody.verify_restore(args)
    assert receipt['status'] == 'RESTORED_VERIFIED' and receipt['files'] == 3
    assert receipt['modelsExecuted'] == receipt['databasesOpened'] == receipt['originalFilesDeleted'] == 0
    assert str(originals.source) not in json.dumps(receipt) and 'sourcePath' not in json.dumps(receipt)
    assert receipt['publicReceiptSha256'] == custody.digest(work / custody.PUBLIC)
    for name, _, _ in originals.names:
        restored = work / custody.RESTORE / name
        assert restored.read_bytes() == (originals.source / name).read_bytes()
        assert stat.S_IMODE(restored.stat().st_mode) == 0o600
    with pytest.raises(custody.CustodyError): custody.verify_restore(args)


@pytest.mark.parametrize('mutation', ['transport', 'member-bytes', 'extra-member', 'link-member', 'pax-budget', 'global-pax-budget', 'sparse-map'])
def test_restore_rejects_transport_or_member_tampering_and_keeps_failed_inputs(originals, tmp_path, monkeypatch, mutation):
    package = originals.parent / 'package'; custody.pack(originals.catalog, package)
    if mutation != 'transport':
        manifest = custody.read_json(package / 'custody.json')
        with tarfile.open(package / 'originals.tar', 'w', format=tarfile.PAX_FORMAT,
                          pax_headers={'comment': 'x' * 65537} if mutation == 'global-pax-budget' else None) as archive:
            for row in manifest['files']:
                data = (originals.source / row['member']).read_bytes(); entry = tarfile.TarInfo(row['member']); entry.size = len(data)
                if mutation == 'pax-budget' and row == manifest['files'][0]: entry.pax_headers = {'comment': 'x' * 65537}
                if mutation == 'member-bytes' and row == manifest['files'][0]: data = b'X' + data[1:]
                if mutation == 'link-member' and row == manifest['files'][0]: entry.type = tarfile.SYMTYPE; entry.linkname = '/not-admitted'
                if mutation == 'sparse-map' and row == manifest['files'][0]: entry.pax_headers = {'GNU.sparse.map': '0,' + str(len(data))}
                archive.addfile(entry, io.BytesIO(data) if entry.isfile() else None)
            if mutation == 'extra-member':
                entry = tarfile.TarInfo('private.env'); entry.size = 1; archive.addfile(entry, io.BytesIO(b'x'))
        manifest['archiveBytes'] = (package / 'originals.tar').stat().st_size; manifest['archiveSha256'] = custody.digest(package / 'originals.tar')
        (package / 'custody.json').write_bytes(custody.encoded(manifest))
        if 'pax-budget' in mutation:
            with (package / 'originals.tar').open('rb') as raw:
                header = tarfile.TarInfo.frombuf(raw.read(512), 'utf-8', 'strict')
            assert header.type == (tarfile.XGLTYPE if mutation == 'global-pax-budget' else tarfile.XHDTYPE)
            assert header.size > 65536
    args, work = create_attempt(tmp_path, monkeypatch, package)
    custody.prepare(args); upload(package, work)
    if mutation == 'transport':
        path = work / custody.SNAPSHOT / 'originals.tar'; path.write_bytes(path.read_bytes() + b'x')
    if 'pax-budget' in mutation:
        original_pax = tarfile.TarInfo._proc_pax
        def guarded_pax(info, archive):
            assert info.size <= 65536, 'Oversize PAX reached the allocating decoder'
            return original_pax(info, archive)
        monkeypatch.setattr(tarfile.TarInfo, '_proc_pax', guarded_pax)
    with pytest.raises(custody.CustodyError, match='metadata' if 'pax-budget' in mutation else None):
        custody.verify_restore(args)
    assert (work / custody.SNAPSHOT).exists() and not (work / custody.PUBLIC).exists()


def test_prepare_budgets_archive_and_independent_restore_and_never_starts_a_partial_attempt(originals, tmp_path, monkeypatch):
    package = originals.parent / 'package'; custody.pack(originals.catalog, package)
    args, work = create_attempt(tmp_path, monkeypatch, package)
    def refused(path, additional=0):
        assert additional >= custody.ORIGINAL_BYTES + args.archive_bytes + args.manifest_bytes
        raise custody.CustodyError('resource reserve reached')
    monkeypatch.setattr(custody, 'resource_guard', refused)
    with pytest.raises(custody.CustodyError, match='resource'): custody.prepare(args)
    assert not (work / custody.SNAPSHOT).exists() and not (work / custody.OWNER).exists()


def test_server_reuse_copies_then_independently_restores_without_the_local_package(originals, tmp_path, monkeypatch):
    package = originals.parent / 'package'; custody.pack(originals.catalog, package)
    first, old_work = create_attempt(tmp_path, monkeypatch, package)
    custody.prepare(first); upload(package, old_work); custody.verify_restore(first)
    second, work = create_attempt(tmp_path, monkeypatch, package, number=72)
    second.source_snapshot_directory = str(old_work / custody.SNAPSHOT)
    description = custody.describe(second)
    second.source_receipt_sha256 = description['sourceCustodyReceiptSha256']
    # Opaque data stays on ECS even after the original workstation package is unavailable.
    for file in package.iterdir(): file.unlink()
    package.rmdir()
    receipt = custody.reuse(second)
    assert receipt['status'] == 'RESTORED_VERIFIED' and receipt['sourceCustodyReceiptSha256'] == second.source_receipt_sha256
    assert 'sourceSnapshotDirectory' not in description and 'sourcePath' not in description
    for name, _, _ in originals.names:
        assert (work / custody.RESTORE / name).read_bytes() == (old_work / custody.RESTORE / name).read_bytes()
    assert (old_work / custody.SNAPSHOT / 'originals.tar').is_file()


@pytest.mark.parametrize('mutation', ['archive', 'receipt', 'permissions', 'outside-root', 'future-build'])
def test_reuse_refuses_changed_or_foreign_old_custody_without_fallback(originals, tmp_path, monkeypatch, mutation):
    package = originals.parent / 'package'; custody.pack(originals.catalog, package)
    first, old_work = create_attempt(tmp_path, monkeypatch, package, number=73 if mutation == 'future-build' else 71)
    custody.prepare(first); upload(package, old_work); custody.verify_restore(first)
    second, work = create_attempt(tmp_path, monkeypatch, package, number=72)
    second.source_snapshot_directory = str(old_work / custody.SNAPSHOT)
    if mutation == 'archive':
        path = old_work / custody.SNAPSHOT / 'originals.tar'; path.write_bytes(path.read_bytes() + b'x')
    elif mutation == 'receipt':
        path = old_work / custody.PUBLIC; value = custody.read_json(path); value['identity']['machineId'] = 'c' * 32
        path.write_bytes(custody.encoded(value))
    elif mutation == 'permissions': (old_work / custody.SNAPSHOT).chmod(0o755)
    elif mutation == 'outside-root': second.source_snapshot_directory = str(originals.source)
    with pytest.raises((custody.CustodyError, ValueError)): custody.describe(second)
    assert not (work / custody.SNAPSHOT).exists()
