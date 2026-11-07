"""ECS-only byte/ownership contracts; opaque fixtures never use a DB or model reader."""
from contextlib import nullcontext
import copy
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
    with tarfile.open(package / 'originals.tar.gz', 'w:gz', format=tarfile.PAX_FORMAT) as archive:
        for entry, body in items: archive.addfile(entry, io.BytesIO(body) if body is not None else None)
    if mutation == 'gzip-crc':
        raw = bytearray((package / 'originals.tar.gz').read_bytes()); raw[-8] ^= 0x80
        (package / 'originals.tar.gz').write_bytes(raw)
    manifest = cold.read(package / 'custody.json')
    manifest['archiveSha256'] = cold.digest(package / 'originals.tar.gz'); manifest['archiveBytes'] = (package / 'originals.tar.gz').stat().st_size
    (package / 'custody.json').write_bytes(cold.encoded(manifest))
    args.archive_bytes = manifest['archiveBytes']; args.archive_sha256 = manifest['archiveSha256']
    args.manifest_bytes = (package / 'custody.json').stat().st_size; args.manifest_sha256 = cold.digest(package / 'custody.json')


@pytest.mark.parametrize('mutation', ['extra', 'duplicate', 'omitted-file', 'omitted-empty-dir', 'linked-file', 'wrong-body', 'gzip-crc'])
def test_full_restore_rejects_inner_tar_drift_even_with_updated_transport_hashes(originals, tmp_path, monkeypatch, mutation):
    package = packed(originals); args, work, _ = attempt(tmp_path, monkeypatch, package)
    repack_changed(package, args, mutation); cold.prepare(args); upload(package, work)
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
