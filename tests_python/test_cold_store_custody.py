"""ECS-only byte/ownership contracts; opaque fixtures never use a DB or model reader."""
from contextlib import nullcontext
import copy
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('fixed_cold_custody_contract', ROOT / 'script/jenkins/preserve-cold-stores.py')
cold = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(cold)


def put(path, raw):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(raw); path.chmod(0o600)
    return path


@pytest.fixture
def originals(tmp_path, monkeypatch):
    source = tmp_path / 'project'; source.mkdir(mode=0o700)
    mysql = source / 'work/old/mysql/data'; store = source / 'work/old/memory'
    bodies = {'work/old/mysql/data/schema/table.ibd': b'opaque Win32 InnoDB\x00not SQL',
              'work/old/memory/chroma.sqlite3': b'opaque SQLite\x00not opened',
              'work/old/memory/chroma.sqlite3-wal': b'opaque WAL original',
              'work/old/memory/index/vector.bin': bytes(range(256)),
              'work/old/original.xml': b'<testsuite errors="1"><testcase name="original failure"/></testsuite>'}
    for name, body in bodies.items(): put(source / name, body)
    (mysql / 'empty-directory').mkdir(mode=0o700)
    parent = source / 'work/data-migration-fixture'; parent.mkdir(mode=0o700)
    roots = [{'id': 'mysql-01', 'path': mysql.relative_to(source).as_posix(), 'kind': 'MYSQL_DATADIR'},
             {'id': 'store-01', 'path': store.relative_to(source).as_posix(), 'kind': 'SQLITE_STORE_TREE'}]
    members = []
    for name in bodies:
        scopes = [r['id'] for r in roots if name.startswith(r['path'] + '/')] or ['EXACT_EVIDENCE']
        path = source / name
        members.append({'path': name, 'bytes': len(bodies[name]), 'sha256': cold.digest(path),
            'scopes': scopes, 'stableDuringHash': True, 'fingerprint': cold.fingerprint(path.stat())})
    directories = []
    for root in roots:
        for current, _, _ in os.walk(source / root['path']):
            path = Path(current)
            directories.append({'path': path.relative_to(source).as_posix(), 'fingerprint': cold.fingerprint(path.stat()),
                                'children': sorted(p.name for p in path.iterdir())})
    value = {'kind': 'doorhandle-local-cold-store-scoped-inventory', 'status': 'MEMBERS_HASHED',
        'roots': roots, 'members': members, 'directories': directories,
        'summary': {'issues': 0, 'approvedForDeletion': 0}, 'physicalFileAliases': [], 'overlappingTreeDeclarations': []}
    inventory = put(tmp_path / 'inventory.json', cold.encoded(value) + b'\n')
    monkeypatch.setattr(cold, 'ROOT', source)
    monkeypatch.setattr(cold, 'INVENTORY_SHA256', cold.digest(inventory))
    monkeypatch.setattr(cold, 'FILES', len(members)); monkeypatch.setattr(cold, 'ORIGINAL_BYTES', sum(len(b) for b in bodies.values()))
    monkeypatch.setattr(cold, 'TREE_ROOTS', len(roots)); monkeypatch.setattr(cold, 'SOURCE_DIRECTORIES', len(directories))
    monkeypatch.setattr(cold, 'resource', lambda *unused: None)
    monkeypatch.setattr(cold, 'available', lambda *unused: 16 * 1024 ** 3)
    monkeypatch.setattr(cold, 'RestoreGuard', lambda *unused: nullcontext())
    monkeypatch.setattr(cold.shutil, 'disk_usage', lambda *unused: SimpleNamespace(free=16 * 1024 ** 3))
    return SimpleNamespace(source=source, parent=parent, inventory=inventory, value=value, bodies=bodies)


def packed(originals):
    output = originals.parent / 'package'
    cold.pack(originals.inventory, output)
    return output


def attempt(tmp_path, monkeypatch, package, number=80):
    root = tmp_path / ('ecs-' + str(number)); root.mkdir(mode=0o700)
    tag = 'ci-' + str(number) + '-' + 'a' * 12
    work = root / 'verification' / tag / 'checkout/work'; work.mkdir(mode=0o700, parents=True)
    work.chmod(0o755)
    context = {'version': 1, 'kind': cold.KIND, 'profile': cold.PROFILE, 'release': tag, 'commit': 'a' * 40,
        'sourceSha256': 'b' * 64, 'identity': {'instanceId': 'i-fixture123', 'machineId': 'c' * 32, 'executionLocation': 'ECS'},
        'verificationReceiptSha256': 'd' * 64, 'inventorySha256': cold.INVENTORY_SHA256,
        'files': cold.FILES, 'bytes': cold.ORIGINAL_BYTES, 'roots': cold.TREE_ROOTS}
    args = SimpleNamespace(root=str(root), tag=tag, commit='a' * 40, source_sha256='b' * 64,
                           source_receipt_sha256=None)
    for prefix, name in [('inventory', 'inventory.json'), ('manifest', 'custody.json'), ('archive', 'originals.tar.gz')]:
        setattr(args, prefix + '_bytes', (package / name).stat().st_size)
        setattr(args, prefix + '_sha256', cold.digest(package / name))
    monkeypatch.setattr(cold, 'admit', lambda _args: (work, context))
    return args, work, context


def upload(package, work):
    for name in ('inventory.json', 'custody.json', 'originals.tar.gz'):
        target = work / cold.SNAPSHOT / name
        target.write_bytes((package / name).read_bytes()); target.chmod(0o600)


def test_complete_pack_covers_every_root_report_wal_index_and_empty_directory(originals):
    before = {name: cold.digest(originals.source / name) for name in originals.bodies}
    package = packed(originals)
    assert {p.name for p in package.iterdir()} == {'inventory.json', 'custody.json', 'originals.tar.gz'}
    manifest = cold.read(package / 'custody.json'); groups = cold.validate_manifest(manifest, cold.inventory(package / 'inventory.json'))
    assert set(groups) == {'mysql-01', 'store-01', 'reports'}
    assert manifest['heldAllSourcesExclusive'] is True
    with tarfile.open(package / 'originals.tar.gz', 'r:gz') as archive:
        names = {entry.name for entry in archive}
    assert 'mysql-01/empty-directory' in names and 'store-01/chroma.sqlite3-wal' in names
    assert 'store-01/index/vector.bin' in names and 'reports/work/old/original.xml' in names
    assert before == {name: cold.digest(originals.source / name) for name in originals.bodies}


@pytest.mark.parametrize('damage', ['inventory', 'bytes', 'inode', 'hardlink', 'symlink', 'new-member'])
def test_unreviewed_or_changed_originals_never_receive_a_complete_package(originals, damage):
    target = originals.source / 'work/old/memory/chroma.sqlite3'
    if damage == 'inventory': originals.inventory.write_bytes(originals.inventory.read_bytes() + b' ')
    elif damage == 'bytes': target.write_bytes(target.read_bytes() + b'changed')
    elif damage == 'inode':
        original = target.read_bytes(); target.unlink(); target.write_bytes(original)
    elif damage == 'hardlink': os.link(target, originals.source / 'external-link')
    elif damage == 'symlink': target.unlink(); target.symlink_to(originals.source / 'work/old/original.xml')
    else: put(target.parent / 'unreviewed.bin', b'must not be silently omitted')
    with pytest.raises(Exception): cold.pack(originals.inventory, originals.parent / 'rejected')
    assert not (originals.parent / 'rejected/custody.json').exists()


def test_an_existing_owner_lock_blocks_the_whole_pack_without_changing_any_source(originals):
    import fcntl
    file = originals.source / next(iter(originals.bodies))
    with file.open('rb') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(cold.ColdError, match='ACTIVE_SOURCE_OWNER'): packed(originals)
    assert all((originals.source / name).read_bytes() == body for name, body in originals.bodies.items())


def test_mid_pack_source_drift_keeps_partial_archive_and_never_marks_complete(originals, monkeypatch):
    original = tarfile.TarFile.addfile; changed = False
    def mutate(tar, info, stream=None):
        nonlocal changed
        result = original(tar, info, stream)
        if info.isfile() and not changed:
            changed = True
            # A noncooperating Linux writer is caught by the final held-handle
            # metadata check; Windows ShareMode=0 prevents this write outright.
            target = originals.source / 'work/old/memory/chroma.sqlite3'
            target.write_bytes(target.read_bytes() + b'drift')
        return result
    monkeypatch.setattr(tarfile.TarFile, 'addfile', mutate)
    with pytest.raises(cold.ColdError): packed(originals)
    assert not (originals.parent / 'package/custody.json').exists()
    assert (originals.parent / 'package/pack-failed.json').is_file()


def test_full_independent_ecs_restore_reads_all_bytes_and_removes_only_temporary_copies(originals, tmp_path, monkeypatch):
    package = packed(originals); args, work, _ = attempt(tmp_path, monkeypatch, package)
    before = {name: (package / name).read_bytes() for name in ('inventory.json', 'custody.json', 'originals.tar.gz')}
    assert cold.prepare(args)['status'] == 'PREPARED'; upload(package, work)
    public = cold.verify_restore(args)
    assert public['status'] == 'RESTORED_VERIFIED' and public['restoredRoots'] == public['temporaryRestoresRemoved'] == 3
    assert public['files'] == 5 and public['originalFilesDeleted'] == public['databasesOpened'] == 0
    assert set(public) == set(cold.PUBLIC_FIELDS) | {'publicReceiptSha256'}
    assert all((work / cold.SNAPSHOT / name).read_bytes() == body for name, body in before.items())
    proof = cold.read(work / cold.RESTORE / 'restore-receipt.json')
    assert sum(group['files'] for group in proof['groups']) == 5
    assert not list((work / cold.RESTORE).glob('temporary-*'))
    assert all(cold.read(work / cold.RESTORE / (group['group'] + '-temporary-cleanup.json'))['status'] == 'REMOVED_OWNED_VERIFIED_RESTORE'
               for group in proof['groups'])
    assert str(originals.source) not in json.dumps(public) and 'private' not in json.dumps(public)


def repack_changed(package, args, mutation):
    with tarfile.open(package / 'originals.tar.gz', 'r:gz') as archive:
        items = [(entry, archive.extractfile(entry).read() if entry.isfile() else None) for entry in archive]
    if mutation == 'extra':
        entry = tarfile.TarInfo('store-01/private.env'); entry.size = 6; items.append((entry, b'secret'))
    elif mutation == 'duplicate': items.append(next(item for item in items if item[0].isfile()))
    elif mutation == 'omitted-file': items.pop(next(i for i, item in enumerate(items) if item[0].isfile()))
    elif mutation == 'omitted-empty-dir': items = [item for item in items if not item[0].name.endswith('/empty-directory')]
    elif mutation == 'linked-file':
        i = next(i for i, item in enumerate(items) if item[0].isfile()); entry = copy.copy(items[i][0])
        entry.type = tarfile.SYMTYPE; entry.size = 0; entry.linkname = '/foreign/secret'; items[i] = (entry, None)
    elif mutation == 'wrong-body':
        i = next(i for i, item in enumerate(items) if item[0].isfile()); entry, body = items[i]; items[i] = (entry, b'x' * len(body))
    with tarfile.open(package / 'originals.tar.gz', 'w:gz', format=tarfile.PAX_FORMAT,
                      pax_headers={'comment': 'opaque'} if mutation == 'global-pax-header' else None) as archive:
        for index, (entry, body) in enumerate(items):
            if mutation == 'pax-budget' and index == 0: entry.pax_headers = {'comment': 'x' * 65537}
            archive.addfile(entry, io.BytesIO(body) if body is not None else None)
    if mutation in ('pax-budget', 'global-pax-header'):
        with gzip.open(package / 'originals.tar.gz', 'rb') as raw:
            header = tarfile.TarInfo.frombuf(raw.read(512), 'utf-8', 'strict')
        assert header.type == (tarfile.XGLTYPE if mutation == 'global-pax-header' else tarfile.XHDTYPE)
        assert (header.size > 65536) if mutation == 'pax-budget' else (0 < header.size < 65536)
    if mutation == 'gzip-crc':
        raw = bytearray((package / 'originals.tar.gz').read_bytes()); raw[-8] ^= 0x80
        (package / 'originals.tar.gz').write_bytes(raw)
    manifest = cold.read(package / 'custody.json')
    manifest['archiveSha256'] = cold.digest(package / 'originals.tar.gz'); manifest['archiveBytes'] = (package / 'originals.tar.gz').stat().st_size
    (package / 'custody.json').write_bytes(cold.encoded(manifest))
    args.archive_bytes = manifest['archiveBytes']; args.archive_sha256 = manifest['archiveSha256']
    args.manifest_bytes = (package / 'custody.json').stat().st_size; args.manifest_sha256 = cold.digest(package / 'custody.json')


@pytest.mark.parametrize('mutation', ['extra', 'duplicate', 'omitted-file', 'omitted-empty-dir', 'linked-file', 'wrong-body', 'gzip-crc', 'pax-budget', 'global-pax-header'])
def test_full_restore_rejects_inner_tar_drift_even_with_updated_transport_hashes(originals, tmp_path, monkeypatch, mutation):
    package = packed(originals); args, work, _ = attempt(tmp_path, monkeypatch, package)
    repack_changed(package, args, mutation); cold.prepare(args); upload(package, work)
    if mutation in ('pax-budget', 'global-pax-header'):
        monkeypatch.setattr(tarfile.TarInfo, '_proc_pax',
            lambda *unused: pytest.fail('Unadmitted cold-store PAX must be rejected before decoding'))
        with pytest.raises(cold.ColdError, match='COLD_FOREIGN_TAR_HEADER'): cold.verify_restore(args)
    else:
        with pytest.raises(Exception): cold.verify_restore(args)
    assert not (work / cold.PUBLIC).exists() and (work / cold.SNAPSHOT / 'originals.tar.gz').is_file()
    assert (work / cold.RESTORE / 'restore-failed.json').is_file()


def test_serial_budget_uses_largest_coexisting_restore_not_sum_of_all_roots(originals):
    groups = cold.layout(cold.inventory(originals.inventory)); inputs = {'archive': {'bytes': 1201}, 'manifest': {'bytes': 2201}}
    plan = cold.budget(groups, inputs, 4096)
    assert plan['inputAllocationBoundBytes'] == 8192
    assert plan['largestRestoreAllocationBytes'] == max(plan['restoreAllocationByGroup'].values())
    assert plan['largestRestoreAllocationBytes'] < sum(plan['restoreAllocationByGroup'].values())
    assert plan['requiredAvailableBytes'] == 8192 + plan['largestRestoreAllocationBytes'] + cold.FLOOR + cold.MAX_JSON
    assert cold.budget(groups, inputs, 65536)['requiredAvailableBytes'] > plan['requiredAvailableBytes']


def test_low_space_error_exposes_required_and_free_without_a_source_path(originals, monkeypatch):
    # Call the real gate with only its host observations substituted.
    spec = importlib.util.spec_from_file_location('cold_real_space_gate', ROOT / 'script/jenkins/preserve-cold-stores.py')
    real = importlib.util.module_from_spec(spec); spec.loader.exec_module(real)
    monkeypatch.setattr(real, 'available', lambda _: real.FLOOR - 1)
    with pytest.raises(real.ColdError, match='COLD_SPACE_REQUIRED_[0-9]+_FREE_[0-9]+') as error:
        real.resource(originals.source, 123)
    assert str(originals.source) not in str(error.value)


def test_cleanup_refuses_foreign_location_or_a_changed_restored_member(originals, tmp_path):
    parent = tmp_path / 'restore'; parent.mkdir(mode=0o700)
    token = 'a' * 32; child = parent / ('temporary-' + token); child.mkdir(mode=0o700)
    file = put(child / 'row.bin', b'preserve')
    expected = {'files': {'row.bin': {'bytes': 8, 'sha256': cold.digest(file)}}, 'directories': {''}}
    with pytest.raises(cold.ColdError, match='OWNER_REQUIRED'):
        cold.remove_verified_temporary(child, parent, 'b' * 32, expected)
    file.write_bytes(b'changed')
    with pytest.raises(cold.ColdError, match='CHANGED_BEFORE_CLEANUP'):
        cold.remove_verified_temporary(child, parent, token, expected)
    assert file.read_bytes() == b'changed'


def test_retirement_is_only_a_plan_and_never_changes_original_files(originals, tmp_path, monkeypatch):
    package = packed(originals); args, work, _ = attempt(tmp_path, monkeypatch, package)
    cold.prepare(args); upload(package, work); cold.verify_restore(args)
    out = originals.parent / 'retirement-plan/plan.json'; result = cold.retirement_plan(originals.inventory, work / cold.PUBLIC, out)
    assert result['status'] == 'PLAN_ONLY_NO_DELETION_AUTHORITY' and result['originalFilesDeleted'] == 0
    assert cold.read(out)['requiresFreshNoActiveHandleProof'] is True
    assert all((originals.source / name).read_bytes() == body for name, body in originals.bodies.items())
    assert not hasattr(cold, 'retire') and not hasattr(cold, 'apply')
    with pytest.raises(cold.ColdError, match='PRIVATE_RETIREMENT_PLAN'):
        cold.retirement_plan(originals.inventory, work / cold.PUBLIC, tmp_path / 'outside-plan.json')


@pytest.mark.parametrize('drift', ['archive', 'inventory', 'owner'])
def test_failed_restore_retains_originals_and_refuses_drifted_snapshot_or_owner(originals, tmp_path, monkeypatch, drift):
    package = packed(originals); args, work, _ = attempt(tmp_path, monkeypatch, package)
    cold.prepare(args); upload(package, work)
    if drift == 'owner':
        owner = cold.read(work / cold.OWNER); owner['release'] = 'ci-1-' + 'f' * 12
        (work / cold.OWNER).write_bytes(cold.encoded(owner))
    else:
        name = 'inventory.json' if drift == 'inventory' else 'originals.tar.gz'
        file = work / cold.SNAPSHOT / name; file.write_bytes(file.read_bytes() + b'drift')
    with pytest.raises(cold.ColdError): cold.verify_restore(args)
    assert not (work / cold.PUBLIC).exists() and (work / cold.SNAPSHOT).exists()


def install_fixed_source(tmp_path, monkeypatch):
    root = tmp_path / 'source-admission'; root.mkdir(mode=0o700)
    tag = 'ci-90-' + 'a' * 12
    checkout = root / 'verification' / tag / 'checkout'; checkout.mkdir(mode=0o700, parents=True)
    inbox = root / 'inbox' / tag; inbox.mkdir(mode=0o700, parents=True)
    archive = inbox / 'source.tar.gz'
    with tarfile.open(archive, 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': 'a' * 40}) as tar:
        for name in (cold.SELF.name, cold.UTIL_NAME, 'verify-remote.py', 'cleanup-ecs-builds.py'):
            raw = cold.SELF.with_name(name).read_bytes(); info = tarfile.TarInfo('script/jenkins/' + name)
            info.size = len(raw); tar.addfile(info, io.BytesIO(raw))
    args = SimpleNamespace(root=str(root), tag=tag, commit='a' * 40, source_sha256=cold.digest(archive))
    monkeypatch.setattr(cold, 'ROOT', checkout)
    return args, archive


@pytest.mark.parametrize('damage', ['source-sha', 'helper', 'utility', 'verifier', 'commit'])
def test_fixed_source_closure_is_checked_before_project_helpers_are_imported(tmp_path, monkeypatch, damage):
    args, archive = install_fixed_source(tmp_path, monkeypatch)
    if damage == 'source-sha': args.source_sha256 = '0' * 64
    else:
        with tarfile.open(archive, 'r:gz') as tar:
            rows = {entry.name: tar.extractfile(entry).read() for entry in tar}
        key = {'helper': cold.SELF.name, 'utility': cold.UTIL_NAME, 'verifier': 'verify-remote.py'}.get(damage)
        if key: rows['script/jenkins/' + key] = b'raise RuntimeError("must never execute")'
        with tarfile.open(archive, 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': 'b' * 40 if damage == 'commit' else args.commit}) as tar:
            for name, raw in rows.items():
                info = tarfile.TarInfo(name); info.size = len(raw); tar.addfile(info, io.BytesIO(raw))
        args.source_sha256 = cold.digest(archive)
    monkeypatch.setattr(cold, 'load', lambda name: pytest.fail('No project helper may be imported before byte closure'))
    with pytest.raises(cold.ColdError): cold.fixed_modules(args)


def test_stopped_gate_checks_original_reports_not_only_the_pass_boolean(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('cold_stopped_fixture_support', ROOT / 'tests_python/test_jenkins_ecs_build_cleanup.py')
    support = importlib.util.module_from_spec(spec); spec.loader.exec_module(support)
    # Use the existing complete synthetic CI claim/report fixture generator.
    generated = support.state.__wrapped__(tmp_path, monkeypatch)
    identity = copy.deepcopy(support.IDENTITY)
    inner = support.cleanup.read_json(generated.evidence / 'receipt.json')
    inner['status'] = 'PASS'; inner['commands'][0]['exitCode'] = 0
    support.put_json(generated.evidence / 'receipt.json', inner)
    generated.record.update(status='PASS', verificationExitCode=0); support.seal(generated)
    monkeypatch.setattr(support.cleanup, 'docker_snapshot', lambda: [])
    assert cold.stopped_receipt(generated.root, support.OLD, identity, support.remote, support.cleanup, current=True)[0]['status'] == 'PASS'
    report = generated.keep[2]; report.write_bytes(report.read_bytes() + b'original changed')
    with pytest.raises(cold.ColdError, match='REPORT_DRIFT'):
        cold.stopped_receipt(generated.root, support.OLD, identity, support.remote, support.cleanup, current=True)


@pytest.mark.parametrize('damage', ['tools-not-stopped', 'active-owner', 'incomplete-command'])
def test_raw_tool_stop_and_active_owner_are_mandatory_for_custody(tmp_path, monkeypatch, damage):
    spec = importlib.util.spec_from_file_location('cold_owner_fixture_support_' + damage, ROOT / 'tests_python/test_jenkins_ecs_build_cleanup.py')
    support = importlib.util.module_from_spec(spec); spec.loader.exec_module(support)
    state = support.state.__wrapped__(tmp_path, monkeypatch)
    inner = support.cleanup.read_json(state.evidence / 'receipt.json'); inner['status'] = 'PASS'; inner['commands'][0]['exitCode'] = 0
    if damage == 'incomplete-command': inner['commands'][0].pop('finishedAt')
    support.put_json(state.evidence / 'receipt.json', inner)
    if damage == 'tools-not-stopped':
        value = support.cleanup.read_json(state.evidence / 'tool-runtime.json'); value['cleanup']['status'] = 'FAILED_OR_UNKNOWN'
        support.put_json(state.evidence / 'tool-runtime.json', value)
    state.record.update(status='PASS', verificationExitCode=0); support.seal(state)
    if damage == 'active-owner': monkeypatch.setattr(support.cleanup, 'docker_snapshot', lambda: [['1' * 64, True, False, 44, support.OLD, None, []]])
    with pytest.raises(Exception): cold.stopped_receipt(state.root, support.OLD, support.IDENTITY, support.remote, support.cleanup, current=True)


def old_custody(originals, tmp_path, monkeypatch):
    package = packed(originals); old_args, old_work, old_context = attempt(tmp_path, monkeypatch, package)
    cold.prepare(old_args); upload(package, old_work); cold.verify_restore(old_args)
    root = Path(old_args.root); tag = 'ci-81-' + 'a' * 12
    work = root / 'verification' / tag / 'checkout/work'; work.mkdir(mode=0o700, parents=True); work.chmod(0o755)
    context = {**old_context, 'release': tag, 'sourceSha256': 'e' * 64}
    args = copy.copy(old_args); args.tag = tag; args.source_sha256 = 'e' * 64
    args.source_snapshot_directory = str(old_work / cold.SNAPSHOT)
    args.source_receipt_sha256 = cold.digest(old_work / cold.PUBLIC)
    monkeypatch.setattr(cold, 'admit', lambda _args: (work, context))
    monkeypatch.setattr(cold, 'fixed_modules', lambda _args: (cold.utility(), None, None, work.parent))
    monkeypatch.setattr(cold, 'stopped_receipt', lambda *_args, **_kw: (old_context, old_context['verificationReceiptSha256']))
    return args, work, old_work


def test_same_ecs_reuse_rechecks_all_old_root_proofs_and_independently_restores_again(originals, tmp_path, monkeypatch):
    args, work, old_work = old_custody(originals, tmp_path, monkeypatch)
    before = {p.name: p.read_bytes() for p in (old_work / cold.SNAPSHOT).iterdir()}
    described = cold.describe(args)
    assert described['sourceCustodyReceiptSha256'] == args.source_receipt_sha256
    public = cold.reuse(args)
    assert public['release'] == args.tag and public['sourceCustodyReceiptSha256'] == args.source_receipt_sha256
    assert public['restoredRoots'] == 3 and (work / cold.RESTORE / 'restore-receipt.json').is_file()
    assert before == {p.name: p.read_bytes() for p in (old_work / cold.SNAPSHOT).iterdir()}


@pytest.mark.parametrize('damage', ['future', 'foreign-root', 'root-proof', 'cleanup-proof', 'archive', 'private-mode'])
def test_cloud_reuse_refuses_old_custody_or_independent_restore_proof_drift(originals, tmp_path, monkeypatch, damage):
    args, _, old_work = old_custody(originals, tmp_path, monkeypatch)
    if damage == 'future': args.tag = 'ci-79-' + 'a' * 12
    elif damage == 'foreign-root': args.source_snapshot_directory = str(tmp_path / 'foreign/cold-stores-snapshot')
    elif damage == 'root-proof': (old_work / cold.RESTORE / 'mysql-01-restore.json').write_bytes(b'{}')
    elif damage == 'cleanup-proof': (old_work / cold.RESTORE / 'mysql-01-temporary-cleanup.json').unlink()
    elif damage == 'archive':
        archive = old_work / cold.SNAPSHOT / 'originals.tar.gz'; archive.write_bytes(archive.read_bytes() + b'changed')
    else: (old_work / cold.SNAPSHOT / 'custody.json').chmod(0o644)
    with pytest.raises(Exception): cold.describe(args)
    assert (old_work / cold.SNAPSHOT).is_dir()


def test_resource_watchdog_aborts_only_its_own_restoration_process_and_retains_evidence(tmp_path):
    folder = tmp_path / 'watchdog'; folder.mkdir(mode=0o700)
    original = put(folder / 'original.bin', b'original bytes never removed')
    code = '''import importlib.util,json,sys,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('owned_cold_watchdog',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def pressure(*args):raise m.ColdError('synthetic resource threshold')
m.resource=pressure
try:
 with m.RestoreGuard(Path(sys.argv[2]),Path(sys.argv[2])):time.sleep(5)
except m.ColdError:print(json.dumps({'status':'ABORTED_OWNED_PROCESS_ONLY'}))
'''
    child = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(cold.SELF), str(folder)], capture_output=True, text=True, timeout=10)
    assert child.returncode == 0 and json.loads(child.stdout)['status'] == 'ABORTED_OWNED_PROCESS_ONLY'
    assert original.read_bytes() == b'original bytes never removed'
    assert cold.read(folder / 'resource-abort.json')['status'] == 'ABORTED_OWNED_PROCESS_ONLY'


def choose_profile(monkeypatch, name):
    # Register every mutation with pytest so a selected profile cannot leak
    # into another test or override the original fixture's count restoration.
    for key in cold.PROFILES['cold-store-originals-v1']:
        monkeypatch.setattr(cold, key, getattr(cold, key))
    cold.select_profile(name)


@pytest.fixture
def history_originals(originals, tmp_path, monkeypatch):
    choose_profile(monkeypatch, 'cold-store-history-v2')
    value = copy.deepcopy(originals.value)
    names = {'mysql-01': 'test-0001', 'store-01': 'tool-0002'}
    for root, kind in zip(value['roots'], cold.HISTORY_KINDS):
        root['id'] = names[root['id']]; root['kind'] = kind
    value['members'] = [row for row in value['members'] if row['scopes'] != ['EXACT_EVIDENCE']]
    for row in value['members']:
        row['scopes'] = [names[key] for key in row['scopes']]
    for row in value['directories']:
        row['scopes'] = [root['id'] for root in value['roots']
                         if row['path'] == root['path'] or row['path'].startswith(root['path'] + '/')]
    value['sourceInventorySha256'] = cold.SOURCE_INVENTORY_SHA256
    value['selection'] = {'includedKinds': list(cold.HISTORY_KINDS), 'excludedKinds': list(cold.HISTORY_EXCLUDED_KINDS)}
    inventory = put(tmp_path / 'history-inventory.json', cold.encoded(value) + b'\n')
    monkeypatch.setattr(cold, 'INVENTORY_SHA256', cold.digest(inventory))
    monkeypatch.setattr(cold, 'FILES', len(value['members']))
    monkeypatch.setattr(cold, 'ORIGINAL_BYTES', sum(row['bytes'] for row in value['members']))
    monkeypatch.setattr(cold, 'TREE_ROOTS', len(value['roots']))
    monkeypatch.setattr(cold, 'SOURCE_DIRECTORIES', len(value['directories']))
    return SimpleNamespace(source=originals.source, parent=originals.parent, inventory=inventory, value=value,
                           bodies={row['path']: originals.bodies[row['path']] for row in value['members']})


def test_fixed_profile_selection_is_explicit_and_original_packet_defaults_remain_compatible():
    spec = importlib.util.spec_from_file_location('cold_profile_selection', cold.SELF)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.PROFILE == 'cold-store-originals-v1' and module.FILES == 15750 and module.group_count() == 71
    assert module.INVENTORY_SHA256 == 'd31a1359676053b4182a0e4a9d15d8647cf17f93b2bc26bd7e84ce01116e2f6d'
    legacy = (module.SNAPSHOT, module.RESTORE, module.OWNER, module.PUBLIC)
    with pytest.raises(module.ColdError, match='UNKNOWN_FIXED_COLD_PROFILE'):
        module.select_profile('auto')
    assert module.PROFILE == 'cold-store-originals-v1'
    module.select_profile('cold-store-history-v2')
    assert module.FILES == 16417 and module.ORIGINAL_BYTES == 486493287 and module.group_count() == 4041
    assert not module.HAS_REPORTS and set(legacy).isdisjoint((module.SNAPSHOT, module.RESTORE, module.OWNER, module.PUBLIC))
    assert module.MAX_ARCHIVE == 576 * 1024 ** 2
    module.select_profile('cold-store-originals-v1')
    assert (module.SNAPSHOT, module.RESTORE, module.OWNER, module.PUBLIC) == legacy and module.group_count() == 71


@pytest.mark.parametrize('damage', ['source-sha', 'browser-kind', 'extra-evidence', 'directory-outside'])
def test_history_inventory_refuses_scope_expansion_even_when_transport_hash_is_updated(history_originals, monkeypatch, damage):
    value = copy.deepcopy(history_originals.value)
    if damage == 'source-sha': value['sourceInventorySha256'] = '0' * 64
    elif damage == 'browser-kind': value['roots'][0]['kind'] = 'BROWSER_TOOL_PROFILE_COMPLETE_TREE'
    elif damage == 'extra-evidence': value['members'][0]['scopes'] = ['EXACT_EVIDENCE']
    else: value['directories'][0]['path'] = 'work/foreign-store'
    history_originals.inventory.write_bytes(cold.encoded(value))
    monkeypatch.setattr(cold, 'INVENTORY_SHA256', cold.digest(history_originals.inventory))
    with pytest.raises(cold.ColdError):
        cold.layout(cold.inventory(history_originals.inventory))
    assert all((history_originals.source / name).read_bytes() == body for name, body in history_originals.bodies.items())


def test_history_recovers_every_group_without_empty_reports_or_touching_legacy_destinations(history_originals, tmp_path, monkeypatch):
    package = packed(history_originals); args, work, _ = attempt(tmp_path, monkeypatch, package)
    legacy_file = put(work / 'cold-stores-snapshot/originals.tar.gz', b'old independent cold packet')
    legacy_public = put(work / 'cold-stores-public-receipt.json', b'old immutable receipt')
    originals = {name: (package / name).read_bytes() for name in ('inventory.json', 'custody.json', 'originals.tar.gz')}
    groups = cold.layout(cold.inventory(history_originals.inventory))
    assert set(groups) == {'test-0001', 'tool-0002'} and 'reports' not in groups
    assert cold.prepare(args)['status'] == 'PREPARED'; upload(package, work)
    public = cold.verify_restore(args)
    assert public['profile'] == 'cold-store-history-v2' and public['restoredRoots'] == public['temporaryRestoresRemoved'] == 2
    assert public['files'] == 4 and public['originalFilesDeleted'] == public['databasesOpened'] == 0
    assert cold.read(work / cold.RESTORE / 'test-0001-restore.json')['directories'] == 3
    assert sum(group['files'] for group in cold.read(work / cold.RESTORE / 'restore-receipt.json')['groups']) == 4
    assert not list((work / cold.RESTORE).glob('temporary-*'))
    assert legacy_file.read_bytes() == b'old independent cold packet' and legacy_public.read_bytes() == b'old immutable receipt'
    assert originals == {name: (work / cold.SNAPSHOT / name).read_bytes() for name in originals}


@pytest.mark.parametrize('damage', ['manifest', 'public', 'snapshot-path'])
def test_history_never_accepts_original_profile_manifest_or_cloud_receipt(history_originals, tmp_path, monkeypatch, damage):
    if damage == 'manifest':
        package = packed(history_originals); manifest = cold.read(package / 'custody.json')
        manifest['profile'] = 'cold-store-originals-v1'
        with pytest.raises(cold.ColdError, match='MANIFEST_NOT_COMPLETE'):
            cold.validate_manifest(manifest, history_originals.value)
    else:
        args, _, old_work = old_custody(history_originals, tmp_path, monkeypatch)
        if damage == 'public':
            public = cold.read(old_work / cold.PUBLIC); public['profile'] = 'cold-store-originals-v1'
            (old_work / cold.PUBLIC).write_bytes(cold.encoded(public))
        else:
            foreign = old_work / 'cold-stores-snapshot'; foreign.mkdir(mode=0o700)
            args.source_snapshot_directory = str(foreign)
        with pytest.raises(cold.ColdError): cold.describe(args)
        assert (old_work / cold.SNAPSHOT / 'originals.tar.gz').is_file()


def test_history_cloud_reuse_rechecks_every_group_without_original_local_stores(history_originals, tmp_path, monkeypatch):
    args, work, old_work = old_custody(history_originals, tmp_path, monkeypatch)
    before = {file.name: file.read_bytes() for file in (old_work / cold.SNAPSHOT).iterdir()}
    monkeypatch.setattr(cold, 'safe_source', lambda *_: pytest.fail('Cloud reuse cannot read an original local store'))
    public = cold.reuse(args)
    assert public['profile'] == 'cold-store-history-v2' and public['restoredRoots'] == public['temporaryRestoresRemoved'] == 2
    assert public['sourceCustodyReceiptSha256'] == args.source_receipt_sha256
    assert len(cold.read(work / cold.RESTORE / 'restore-receipt.json')['groups']) == 2
    assert before == {file.name: file.read_bytes() for file in (old_work / cold.SNAPSHOT).iterdir()}


def test_history_evidence_limit_keeps_unproven_restore_and_original_archive(history_originals, tmp_path, monkeypatch):
    package = packed(history_originals); args, work, _ = attempt(tmp_path, monkeypatch, package)
    cold.prepare(args); upload(package, work)
    owner = cold.read(work / cold.OWNER)
    plan = cold.budget(cold.layout(history_originals.value), owner['inputs'], os.statvfs(work).f_frsize)
    monkeypatch.setattr(cold, 'ROOT_EVIDENCE_MAX', len(cold.encoded(plan)) + 1)
    monkeypatch.setattr(cold, 'remove_verified_temporary', lambda *_: pytest.fail('No deletion before a persisted full root proof'))
    with pytest.raises(cold.ColdError, match='HISTORY_ROOT_EVIDENCE_BOUND'):
        cold.verify_restore(args)
    assert (work / cold.SNAPSHOT / 'originals.tar.gz').read_bytes() == (package / 'originals.tar.gz').read_bytes()
    assert (work / cold.RESTORE / ('temporary-' + owner['token'])).is_dir()
    assert not (work / cold.RESTORE / 'test-0001-restore.json').exists() and not (work / cold.PUBLIC).exists()
    assert cold.read(work / cold.RESTORE / 'restore-failed.json')['originalFilesDeleted'] == 0


@pytest.fixture(params=['originals', 'history_originals'])
def fresh_custody(request, tmp_path, monkeypatch):
    original = request.getfixturevalue(request.param)
    args, work, old_work = old_custody(original, tmp_path, monkeypatch)
    # Only synthetic fixtures change fixed recipe constants. Production accepts
    # precisely the two reviewed profiles and their original byte/count limits.
    monkeypatch.setitem(cold.PROFILES, cold.PROFILE,
                        {key: getattr(cold, key) for key in cold.PROFILES[cold.PROFILE]})
    args.nonce = '9' * 64; args.attestation_seconds = 120
    now = cold.dt.datetime(2026, 11, 8, 8, 30, tzinfo=cold.dt.timezone.utc)
    monkeypatch.setattr(cold, 'utc_now', lambda: now)
    public = cold.read(old_work / cold.PUBLIC)
    current = {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
        'identity': copy.deepcopy(public['identity']), 'verificationReceiptSha256': 'd' * 64}
    custody = {key: public[key] for key in cold.ATTESTATION_CUSTODY_FIELDS if key != 'publicReceiptSha256'}
    custody['publicReceiptSha256'] = cold.digest(old_work / cold.PUBLIC)
    return SimpleNamespace(args=args, work=work, old_work=old_work, now=now, current=current, custody=custody)


def validate_fresh(value, fixture, **overrides):
    args = dict(profile=cold.PROFILE, nonce=fixture.args.nonce, expected_current=fixture.current,
                expected_custody=fixture.custody, now_utc=fixture.now)
    args.update(overrides)
    return cold.validate_retirement_attestation(value, **args)


def resign_fresh(value):
    value['proofDigest'] = cold.sha(cold.encoded({key: val for key, val in value.items() if key != 'proofDigest'}))


def custody_tree_bytes(root):
    return {p.relative_to(root).as_posix(): (cold.fingerprint(p.stat()), p.read_bytes() if p.is_file() else None)
            for p in root.rglob('*')}


def forbid_custody_writes(monkeypatch):
    def refuse(*_args, **_kw):
        pytest.fail('A fresh custody attestation may only observe existing evidence')
    open_file = Path.open
    def readonly(path, mode='r', *args, **kw):
        assert mode in ('r', 'rb'), 'Attestation tried to open a writable file'
        return open_file(path, mode, *args, **kw)
    monkeypatch.setattr(Path, 'open', readonly)
    for name in ('mkdir', 'unlink', 'rmdir', 'chmod', 'write_bytes', 'write_text', 'rename', 'replace'):
        monkeypatch.setattr(Path, name, refuse)
    for name in ('private_json', 'prepare', 'verify_restore', 'restore_all', 'remove_verified_temporary', 'safe_source'):
        monkeypatch.setattr(cold, name, refuse)
    for name in ('write_json', 'private_directory'):
        monkeypatch.setattr(cold.utility(), name, refuse)


def test_fresh_retirement_attests_actual_older_roots_and_raw_inputs_without_writing(fresh_custody, monkeypatch):
    fixture = fresh_custody; root = Path(fixture.args.root)
    before = custody_tree_bytes(root)
    with monkeypatch.context() as readonly:
        forbid_custody_writes(readonly)
        value = cold.fresh_retirement_attest(fixture.args)
        assert validate_fresh(value, fixture) == value
    assert value['current'] == fixture.current and value['custody'] == fixture.custody
    assert value['custody']['restoredRoots'] == cold.group_count()
    assert value['custody']['temporaryRestoresRemoved'] == cold.group_count()
    assert set(value) == set(cold.ATTESTATION_FIELDS) and str(root) not in json.dumps(value)
    assert (cold.attestation_time(value['expiresAtUtc']) - cold.attestation_time(value['issuedAtUtc'])).total_seconds() == 120
    assert custody_tree_bytes(root) == before


def test_fresh_validator_uses_only_authenticated_projection_and_explicit_references(fresh_custody, monkeypatch):
    value = cold.fresh_retirement_attest(fresh_custody.args)
    def refuse(*_args, **_kw):
        pytest.fail('Projection validation must not import helpers or observe the machine')
    for name in ('utility', 'load', 'digest', 'original_snapshot', 'admit', 'fixed_modules'):
        monkeypatch.setattr(cold, name, refuse)
    monkeypatch.setattr(Path, 'open', refuse)
    assert validate_fresh(value, fresh_custody) is value
    assert validate_fresh(value, fresh_custody, now_utc=fresh_custody.now + cold.dt.timedelta(seconds=119)) is value


@pytest.mark.parametrize('damage', ['future-build', 'root-proof', 'cleanup-proof', 'archive', 'public-profile'])
def test_fresh_attestation_retains_original_snapshot_gate_and_never_writes_failures(fresh_custody, monkeypatch, damage):
    fixture = fresh_custody
    if damage == 'future-build': fixture.args.tag = 'ci-79-' + fixture.args.commit[:12]
    elif damage in ('root-proof', 'cleanup-proof'):
        key = next(iter(cold.layout(cold.inventory(fixture.old_work / cold.SNAPSHOT / 'inventory.json'))))
        suffix = '-restore.json' if damage == 'root-proof' else '-temporary-cleanup.json'
        (fixture.old_work / cold.RESTORE / (key + suffix)).write_bytes(b'{}')
    elif damage == 'archive':
        path = fixture.old_work / cold.SNAPSHOT / 'originals.tar.gz'; path.write_bytes(path.read_bytes() + b'changed')
    else:
        path = fixture.old_work / cold.PUBLIC; value = cold.read(path)
        value['profile'] = 'unreviewed-profile'; path.write_bytes(cold.encoded(value))
    before = custody_tree_bytes(Path(fixture.args.root))
    with monkeypatch.context() as readonly:
        forbid_custody_writes(readonly)
        with pytest.raises(Exception): cold.fresh_retirement_attest(fixture.args)
    assert custody_tree_bytes(Path(fixture.args.root)) == before


@pytest.mark.parametrize('damage', ['inventory.json', 'custody.json', 'originals.tar.gz', 'public-receipt'])
def test_fresh_attestation_rehashes_raw_inputs_after_all_old_proofs_were_admitted(fresh_custody, monkeypatch, damage):
    original_snapshot = cold.original_snapshot
    def changed_after_gate(args):
        result = original_snapshot(args)
        target = fresh_custody.old_work / (cold.PUBLIC if damage == 'public-receipt' else cold.SNAPSHOT + '/' + damage)
        target.write_bytes(target.read_bytes() + b'drift after original proof admission')
        return result
    monkeypatch.setattr(cold, 'original_snapshot', changed_after_gate)
    with pytest.raises(cold.ColdError, match='COLD_ATTESTATION_(RAW_INPUT|INPUT_OR_RECEIPT)_CHANGED'):
        cold.fresh_retirement_attest(fresh_custody.args)
    assert not list(fresh_custody.work.iterdir())


@pytest.mark.parametrize('nonce', [None, '', 'a' * 63, 'A' * 64, 'g' * 64, True])
def test_invalid_attestation_nonce_is_rejected_before_reading_any_source(monkeypatch, nonce):
    monkeypatch.setattr(cold, 'original_snapshot', lambda *_: pytest.fail('Invalid nonce must not read custody'))
    with pytest.raises(cold.ColdError, match='COLD_ATTESTATION_NONCE_REQUIRED'):
        cold.fresh_retirement_attest(SimpleNamespace(nonce=nonce, attestation_seconds=120))


@pytest.mark.parametrize('seconds', [0, -1, 301, True, 1.5, '120'])
def test_unbounded_or_untyped_attestation_lifetime_is_rejected_before_source_reads(monkeypatch, seconds):
    monkeypatch.setattr(cold, 'original_snapshot', lambda *_: pytest.fail('Invalid lifetime must not read custody'))
    with pytest.raises(cold.ColdError, match='COLD_ATTESTATION_TTL_REQUIRED'):
        cold.fresh_retirement_attest(SimpleNamespace(nonce='9' * 64, attestation_seconds=seconds))


def test_fresh_attestation_refuses_observations_that_outlive_the_challenge(fresh_custody, monkeypatch):
    ticks = iter([0.0, 120.0])
    monkeypatch.setattr(cold.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(cold.ColdError, match='COLD_ATTESTATION_OBSERVATION_EXPIRED'):
        cold.fresh_retirement_attest(fresh_custody.args)
    assert not list(fresh_custody.work.iterdir())


@pytest.mark.parametrize('damage', ['digest', 'nonce', 'profile', 'extra', 'current', 'custody', 'same-build',
                                  'foreign-ecs', 'fixed-inventory', 'boolean-count', 'excess-ttl',
                                  'fractional-ttl', 'future', 'timestamp'])
def test_authenticated_projection_still_rejects_tampering_and_wrong_challenge_or_bindings(fresh_custody, damage):
    fixture = fresh_custody; value = cold.fresh_retirement_attest(fixture.args)
    expected_current = copy.deepcopy(fixture.current); expected_custody = copy.deepcopy(fixture.custody)
    if damage == 'digest': value['custody']['archiveSha256'] = '0' * 64
    elif damage == 'nonce': value['nonce'] = '8' * 64
    elif damage == 'profile': value['profile'] = 'cold-store-history-v2' if cold.HAS_REPORTS else 'cold-store-originals-v1'
    elif damage == 'extra': value['originalPath'] = '/must/not/be/projected'
    elif damage == 'current': value['current']['sourceSha256'] = '0' * 64
    elif damage == 'custody': value['custody']['restoreReceiptSha256'] = '0' * 64
    elif damage == 'same-build':
        value['custody']['release'] = value['current']['release']; expected_custody = copy.deepcopy(value['custody'])
    elif damage == 'foreign-ecs':
        value['custody']['identity'] = {**value['custody']['identity'], 'instanceId': 'i-foreign'}
        expected_custody = copy.deepcopy(value['custody'])
    elif damage == 'fixed-inventory':
        value['custody']['inventorySha256'] = '0' * 64; expected_custody = copy.deepcopy(value['custody'])
    elif damage == 'boolean-count':
        value['custody']['roots'] = True; expected_custody = copy.deepcopy(value['custody'])
    elif damage in ('excess-ttl', 'fractional-ttl'):
        seconds = 301 if damage == 'excess-ttl' else 1.5
        value['expiresAtUtc'] = (fixture.now + cold.dt.timedelta(seconds=seconds)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    elif damage == 'future':
        value['issuedAtUtc'] = (fixture.now + cold.dt.timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    else: value['issuedAtUtc'] = '2026-02-30T08:30:00.000000Z'
    if damage != 'digest': resign_fresh(value)
    with pytest.raises(cold.ColdError):
        validate_fresh(value, fixture, expected_current=expected_current, expected_custody=expected_custody)


def test_projection_expires_at_the_exact_deadline_and_requires_utc(fresh_custody):
    value = cold.fresh_retirement_attest(fresh_custody.args)
    for now in (fresh_custody.now + cold.dt.timedelta(seconds=120),
                fresh_custody.now - cold.dt.timedelta(microseconds=1), fresh_custody.now.replace(tzinfo=None)):
        with pytest.raises(cold.ColdError): validate_fresh(value, fresh_custody, now_utc=now)


def test_fresh_cli_accepts_only_two_fixed_profiles_and_emits_one_json_projection(fresh_custody, monkeypatch, capsys):
    args = fresh_custody.args
    argv = [str(cold.SELF), 'fresh-retirement-attest', '--profile', cold.PROFILE,
        '--root', args.root, '--tag', args.tag, '--commit', args.commit, '--source-sha256', args.source_sha256,
        '--expected-instance-id', fresh_custody.current['identity']['instanceId'],
        '--expected-machine-id', fresh_custody.current['identity']['machineId'],
        '--source-snapshot-directory', args.source_snapshot_directory, '--nonce', args.nonce]
    monkeypatch.setattr(sys, 'argv', argv)
    assert cold.main() == 0
    captured = capsys.readouterr()
    assert not captured.err and len(captured.out.splitlines()) == 1
    validate_fresh(json.loads(captured.out), fresh_custody)
    argv[argv.index('--profile') + 1] = 'invented-retirement-profile'
    with pytest.raises(SystemExit) as rejected: cold.main()
    assert rejected.value.code == 2


@pytest.mark.parametrize('value', [None, 0, 1, 'true'])
def test_held_sources_never_coerces_delete_access_or_changes_default_pack_access(value):
    assert cold.HeldSources({'members': []}).delete_access is False
    with pytest.raises(cold.ColdError, match='DELETE_ACCESS_REQUIRES_WINDOWS'):
        cold.HeldSources({'members': []}, delete_access=value)


def test_delete_access_has_no_posix_fallback_or_implicit_deletion():
    assert os.name != 'nt', 'This contract belongs to the ECS Linux test suite'
    with pytest.raises(cold.ColdError, match='DELETE_ACCESS_REQUIRES_WINDOWS'):
        cold.HeldSources({'members': []}, delete_access=True)


def synthetic_windows_holder(tmp_path, monkeypatch, *, delete_access, readonly, denied=False, native_attributes=None):
    """Exercise the Win32 argument path through a fake DLL, never native APIs."""
    target = put(tmp_path / 'opaque.bin', b'abc')
    attributes = 0x21 if readonly else 0x20
    fingerprint = [7, 11, 3, 0, 0, 1, 0o100444 if readonly else 0o100600, attributes]
    row = {'path': 'work/frozen/opaque.bin', 'fingerprint': fingerprint}
    holder = cold.HeldSources.__new__(cold.HeldSources)
    holder.value = {'members': [row]}; holder.handles = {}; holder.windows = True
    holder.delete_access = delete_access; holder.source_resolver = lambda _name: target
    calls = []
    def create(*args):
        calls.append(('create', args))
        return cold.ctypes.c_void_p(-1).value if denied else 1234
    def info(_handle, pointer):
        value = pointer._obj; value.volume = 7; value.indexLow = 11; value.sizeLow = 3; value.links = 1
        value.attributes = attributes if native_attributes is None else native_attributes
        epoch = 116444736000000000
        for stamp in (value.written, value.created):
            stamp.dwHighDateTime = epoch >> 32; stamp.dwLowDateTime = epoch & 0xffffffff
        return 1
    api = SimpleNamespace(CreateFileW=create, GetFileInformationByHandle=info, ReadFile=lambda *unused: 1,
                          CloseHandle=lambda handle: calls.append(('close', handle)) or 1)
    monkeypatch.setattr(cold.ctypes, 'WinDLL', lambda *args, **kwargs: api, raising=False)
    monkeypatch.setattr(cold, 'fingerprint', lambda _info: fingerprint)
    return holder, calls


@pytest.mark.parametrize('delete_access,readonly,expected', [
    (False, False, 0x80000000), (False, True, 0x80000000),
    (True, False, 0x80010000), (True, True, 0x80010100)])
def test_readonly_write_attributes_permission_is_exclusive_to_reviewed_delete_handles(tmp_path, monkeypatch, delete_access, readonly, expected):
    holder, calls = synthetic_windows_holder(tmp_path, monkeypatch, delete_access=delete_access, readonly=readonly)
    with holder:
        assert holder.handles == {'work/frozen/opaque.bin': 1234}
        assert not any(call[0] == 'close' for call in calls)
    arguments = calls[0][1]
    assert arguments[1] == expected and arguments[2] == 0
    assert arguments[4:6] == (3, 0x00200000)
    assert calls[-1] == ('close', 1234)


def test_readonly_delete_permission_denial_never_falls_back_to_a_weaker_handle(tmp_path, monkeypatch):
    holder, calls = synthetic_windows_holder(tmp_path, monkeypatch, delete_access=True, readonly=True, denied=True)
    with pytest.raises(cold.ColdError, match='ACTIVE_SOURCE_OWNER_OR_ACCESS_BLOCKED'):
        holder.__enter__()
    assert len(calls) == 1 and calls[0][0] == 'create' and calls[0][1][1] == 0x80010100
    assert holder.handles == {}


def test_readonly_attribute_drift_is_refused_on_the_opened_identity_before_use(tmp_path, monkeypatch):
    holder, calls = synthetic_windows_holder(tmp_path, monkeypatch, delete_access=True, readonly=True, native_attributes=0x20)
    with pytest.raises(cold.ColdError, match='SOURCE_NATIVE_HANDLE_CHANGED'):
        holder.__enter__()
    assert len([call for call in calls if call[0] == 'create']) == 1
    assert calls[-1] == ('close', 1234) and holder.handles == {}
