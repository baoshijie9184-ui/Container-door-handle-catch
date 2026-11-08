"""Reuse a verified same-ECS legacy archive without a workstation data copy.

Only the fixed old verification/<tag>/checkout/work/legacy-source-snapshot path
is admitted. Originals and their receipts remain immutable; each new CI attempt
gets its own archive copy and independent byte restore, never a live database.
"""
from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tarfile
import time
from types import SimpleNamespace


TAG = re.compile(r'ci-([0-9]+)-[a-f0-9]{12}')
RESERVE = (2 * 1024 + 256) * 1024 ** 2
MIB = 1024 ** 2
MAX_JSON = 16 * MIB
LOADED_SOURCE = Path(__file__).read_bytes()


def need(value, code):
    if not value: raise ValueError(code)


def refusal_details(error):
    """Expose a fixed guard and own-source locations, never exception payloads."""
    codes = {node.args[1].value for node in ast.walk(ast.parse(LOADED_SOURCE))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'need'
             and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
             and isinstance(node.args[1].value, str)
             and re.fullmatch(r'[A-Z][A-Z0-9_]{0,99}', node.args[1].value)}
    code = (error.args[0] if isinstance(error, ValueError) and len(error.args) == 1
            and isinstance(error.args[0], str) and error.args[0] in codes else 'UNCLASSIFIED_REFUSAL')
    locations = []
    own_guard = False
    trace = error.__traceback__
    while trace is not None:
        frame = trace.tb_frame.f_code
        own_guard = own_guard or frame is need.__code__
        if frame.co_filename == __file__:
            locations.append({'function': frame.co_name, 'line': trace.tb_lineno})
        trace = trace.tb_next
    return {'errorType': type(error).__name__, 'guardCode': code if own_guard else 'UNCLASSIFIED_REFUSAL',
            'locations': locations[-8:]}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for raw in iter(lambda: stream.read(MIB), b''): value.update(raw)
    return value.hexdigest()


def owned(path, root, *, directory=False, private=False, maximum=MAX_JSON):
    path, root = Path(path), Path(root)
    need(path.is_absolute() and (path == root or path.is_relative_to(root))
         and '..' not in path.parts and path.resolve(strict=True) == path, 'UNLINKED_SAME_CI_ROOT_REQUIRED')
    for item in (path, *path.parents):
        info = item.lstat()
        need(not stat.S_ISLNK(info.st_mode), 'SOURCE_LINK_NOT_ALLOWED')
        if item == root or item.is_relative_to(root):
            need(info.st_uid == os.getuid() and not info.st_mode & 0o022, 'SOURCE_ANCESTOR_OWNER_OR_MODE_INVALID')
    info = path.lstat()
    need(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
         and info.st_nlink == 1 and info.st_size <= maximum, 'SOURCE_FILE_TYPE_LINK_OR_SIZE_INVALID')
    if private:
        need(stat.S_IMODE(info.st_mode) == 0o700 if directory else stat.S_IMODE(info.st_mode) in (0o400, 0o600),
             'SOURCE_PRIVATE_PERMISSIONS_REQUIRED')
    return path


def read(path, root, *, maximum=MAX_JSON, private=True):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            need(key not in value, 'DUPLICATE_PRIVATE_RECEIPT_FIELD'); value[key] = item
        return value
    file = owned(path, root, private=private, maximum=maximum)
    return json.loads(file.read_text(encoding='utf-8-sig'), object_pairs_hook=unique)


def write(path, value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    need(len(raw) <= MAX_JSON, 'PUBLIC_RECEIPT_BOUND_EXCEEDED')
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def fixed_source(args, *, executor=None):
    root = Path(args.root); checkout = root / 'verification' / args.tag / 'checkout'
    archive = owned(root / 'inbox' / args.tag / 'source.tar.gz', root, maximum=128 * MIB)
    need(digest(archive) == args.source_sha256, 'CURRENT_FIXED_SOURCE_SHA_DIFFERS')
    wanted = {'script/jenkins/reuse-legacy-source.py': executor or Path(__file__).absolute(),
        'script/jenkins/cleanup-ecs-builds.py': checkout / 'script/jenkins/cleanup-ecs-builds.py',
        'script/jenkins/verify-remote.py': checkout / 'script/jenkins/verify-remote.py',
        'script/memory/migrate_legacy_stores.py': checkout / 'script/memory/migrate_legacy_stores.py'}
    need(Path(wanted['script/jenkins/reuse-legacy-source.py']) == root / 'inbox' / args.tag / 'reuse-legacy-source.py',
         'REUSE_EXECUTOR_OUTSIDE_CURRENT_INBOX')
    for file in wanted.values(): owned(file, root, maximum=MIB)

    class Bounded:
        def __init__(self, stream): self.stream, self.total = stream, 0
        def read(self, size=-1):
            remaining = 512 * MIB - self.total
            raw = self.stream.read(remaining + 1 if size < 0 else min(size, remaining + 1))
            self.total += len(raw); need(self.total <= 512 * MIB, 'CURRENT_SOURCE_EXPANSION_BOUND_EXCEEDED')
            return raw

    found = set()
    with gzip.open(archive, 'rb') as expanded, tarfile.open(fileobj=Bounded(expanded), mode='r|') as source:
        for entry in source:
            if entry.name not in wanted: continue
            need(entry.isfile() and entry.name not in found and 0 < entry.size <= MIB, 'FIXED_REUSE_RECIPE_MEMBER_INVALID')
            need(hashlib.sha256(source.extractfile(entry).read(MIB + 1)).hexdigest() == digest(wanted[entry.name]),
                 'FIXED_REUSE_RECIPE_DIFFERS')
            found.add(entry.name)
        need(source.pax_headers.get('comment') == args.commit and found == set(wanted), 'FIXED_REUSE_COMMIT_OR_CLOSURE_DIFFERS')
    return checkout


def passing_receipt(path, root, tag, identity):
    value = read(path, root, maximum=256 * 1024)
    need(value.get('schema') == 1 and value.get('kind') == 'doorhandle-ecs-ci'
         and value.get('release') == tag and value.get('identity') == identity
         and value.get('status') == 'PASS' and value.get('verificationExitCode') == 0
         and value.get('finishedAt') and value.get('lifecycle') == 'managed-outside-jenkins',
         'MATCHING_TERMINAL_PASS_RECEIPT_REQUIRED')
    return value


def terminal_build(root, attempt, record, identity, cleanup, verifier):
    """Both completed source and MySQL builds may have preserved an archive."""
    args = SimpleNamespace(tag=record['release'], attempt=record['attempt'], commit=record['commit'],
        source_sha256=record['sourceSha256'], scope=record['scope'],
        instance_id=identity['instanceId'], machine_id=identity['machineId'])
    verifier.validate_request(args); catalog = verifier.validate_envelope(record, args)
    need('reports/receipt.json' in catalog and 'reports/tool-runtime.json' in catalog
         and any(name.endswith('.xml') for name in catalog), 'OLD_TERMINAL_REPORT_CATALOG_INCOMPLETE')
    checkout = attempt / 'checkout'; inbox = root / 'inbox' / record['release']
    for name, row in catalog.items():
        path = checkout / ('driver.log' if name == 'driver.log' else 'work/ci-evidence/' + name[8:])
        cleanup.owned_chain(path, root, maximum=verifier.MAX_FILE_BYTES)
        need(path.stat().st_size == row['bytes'] and digest(path) == row['sha256'], 'OLD_TERMINAL_REPORT_CHANGED')
    inner = read(checkout / 'work/ci-evidence/receipt.json', root, maximum=256 * 1024, private=False)
    need(inner.get('scopeKind') == record['scope'] and inner.get('status') == 'PASS' and inner.get('finishedAt')
         and inner.get('identity') == identity and isinstance(inner.get('commands'), list) and inner['commands']
         and all(row.get('finishedAt') and type(row.get('exitCode')) is int for row in inner['commands']),
         'OLD_BUILD_HAS_UNFINISHED_COMMANDS')
    manifest_file = inbox / 'tool-runtime/manifest.json'; manifest = read(manifest_file, root)
    tools = read(checkout / 'work/ci-evidence/tool-runtime.json', root)
    manifest_sha = digest(manifest_file); stopped = tools.get('cleanup', {})
    need(manifest.get('kind') == 'doorhandle-ecs-tool-runtime' and manifest.get('identity') == identity
         and manifest.get('uid') == os.getuid() and manifest.get('checkout') == str(checkout)
         and re.fullmatch(r'[a-f0-9]{24}', manifest.get('token', ''))
         and all(manifest.get(key) == tools.get(key) == record[key] for key in ('release', 'commit', 'sourceSha256'))
         and tools.get('kind') == 'doorhandle-ecs-tool-evidence' and tools.get('manifestSha256') == manifest_sha
         and record.get('toolRuntime', {}).get('manifestSha256') == manifest_sha
         and record['toolRuntime'].get('cleanupStatus') == 'STOPPED'
         and stopped.get('status') == 'STOPPED' and stopped.get('remaining') == []
         and stopped.get('release') == record['release'] and stopped.get('manifestSha256') == manifest_sha,
         'OLD_TOOL_OWNER_OR_STOP_PROOF_DIFFERS')
    binding = {'checkout': checkout, 'token': manifest['token']}
    cleanup.quiescent(binding, record['release'], cleanup.docker_snapshot())
    return binding


def admit_snapshot(root, source, current_tag, identity, migration, cleanup, verifier):
    root, source = Path(root), Path(source)
    parts = source.relative_to(root).parts if source.is_relative_to(root) else ()
    need(len(parts) == 5 and parts[0] == 'verification' and TAG.fullmatch(parts[1])
         and parts[2:] == ('checkout', 'work', 'legacy-source-snapshot'), 'EXACT_OLD_CI_SNAPSHOT_PATH_REQUIRED')
    old = parts[1]
    need(TAG.fullmatch(current_tag) and int(TAG.fullmatch(old)[1]) < int(TAG.fullmatch(current_tag)[1]),
         'SOURCE_SNAPSHOT_MUST_BELONG_TO_AN_OLDER_BUILD')
    owned(source, root, directory=True, private=True)
    public_file = source / 'preservation-public.json'; public = read(public_file, root, maximum=256 * 1024)
    expected_files = {'snapshot.json', 'originals.tar', 'verification.stdout.json', 'verification.stderr', 'preservation-public.json'}
    if 'sourceSnapshotReuse' in public:
        need(set(public['sourceSnapshotReuse']) == {'kind', 'release', 'publicSha256', 'oldOriginalsPreserved'}
             and public['sourceSnapshotReuse']['kind'] == 'doorhandle-ecs-legacy-snapshot-reuse-v1'
             and TAG.fullmatch(public['sourceSnapshotReuse']['release'])
             and re.fullmatch(r'[a-f0-9]{64}', public['sourceSnapshotReuse']['publicSha256'])
             and public['sourceSnapshotReuse']['oldOriginalsPreserved'] is True, 'OLD_REUSE_CHAIN_BINDING_INVALID')
        expected_files.add('reuse-resource-proof.json')
        read(source / 'reuse-resource-proof.json', root)
    need({path.name for path in source.iterdir()} == expected_files, 'OLD_SNAPSHOT_NOT_COMPLETE_OR_HAS_FAILURE_EVIDENCE')
    required = {'status', 'archiveSha256', 'snapshotManifestSha256', 'files', 'bytes', 'kind', 'schemaVersion',
        'release', 'commit', 'sourceSha256', 'scriptSha256', 'identity', 'restoreReceiptSha256',
        'verificationReceiptSha256', 'archiveBytes', 'manifestBytes', 'profile', 'archiveEncoding',
        'kafkaFiles', 'kafkaBytes', 'legacyKafkaReplay'}
    need(required <= set(public) <= required | {'sourceSnapshotReuse', 'memberInventorySha256'} and public['schemaVersion'] == 1
         and public['kind'] == 'doorhandle-legacy-source-preservation' and public['status'] == 'RESTORED_VERIFIED'
         and public['release'] == old and public['identity'] == identity and public['legacyKafkaReplay'] == 'NOT_PERFORMED',
         'OLD_PUBLIC_RESTORE_BINDING_INVALID')
    attempt = source.parents[2]; receipt_file = attempt / 'verification-receipt.json'
    record = passing_receipt(receipt_file, root, old, identity)
    need(record['commit'] == public['commit'] and record['sourceSha256'] == public['sourceSha256']
         and digest(receipt_file) == public['verificationReceiptSha256'], 'OLD_BUILD_PUBLIC_RECEIPT_DRIFT')
    binding = terminal_build(root, attempt, record, identity, cleanup, verifier)
    old_archive = owned(root / 'inbox' / old / 'source.tar.gz', root, maximum=128 * MIB)
    need(digest(old_archive) == record['sourceSha256'], 'OLD_FIXED_SOURCE_ARCHIVE_CHANGED')
    found = False
    with verifier.bounded_tar(old_archive, verifier.MAX_SOURCE_BYTES) as archive:
        for entry in archive:
            if entry.name != 'script/memory/migrate_legacy_stores.py': continue
            need(not found and entry.isfile() and 0 < entry.size <= MIB, 'OLD_MIGRATION_RECIPE_INVALID')
            need(hashlib.sha256(archive.extractfile(entry).read(MIB + 1)).hexdigest() == public['scriptSha256'],
                 'OLD_MIGRATION_RECIPE_SHA_DIFFERS'); found = True
        need(archive.pax_headers.get('comment') == record['commit'], 'OLD_SOURCE_COMMIT_DIFFERS')
    need(found, 'OLD_MIGRATION_RECIPE_MISSING')
    for name in ('snapshot.json', 'originals.tar', 'verification.stdout.json', 'verification.stderr'):
        owned(source / name, root, private=True, maximum=512 * MIB if name == 'originals.tar' else MAX_JSON)
    manifest = read(source / 'snapshot.json', root); plan = migration.validate_preservation_plan(manifest)
    need(digest(source / 'snapshot.json') == public['snapshotManifestSha256']
         and digest(source / 'originals.tar') == public['archiveSha256'] == manifest['archiveSha256']
         and (source / 'originals.tar').stat().st_size == public['archiveBytes']
         and (source / 'snapshot.json').stat().st_size == public['manifestBytes']
         and all(public[key] == plan[key] for key in ('profile', 'files', 'bytes', 'archiveEncoding', 'kafkaFiles', 'kafkaBytes')),
         'OLD_SNAPSHOT_BYTES_OR_FROZEN_CATALOG_DIFFERS')
    need('memberInventorySha256' not in public or public['memberInventorySha256'] == plan['memberInventorySha256'],
         'OLD_MEMBER_INVENTORY_DIGEST_DIFFERS')
    verified = migration.verify_preservation(source)
    expected = {**verified, 'status': 'RESTORED_VERIFIED'}
    restore = owned(attempt / 'checkout/work/legacy-source-restore', root, directory=True, private=True)
    owned(restore / 'original-manifest.json', root, private=True)
    need(read(restore / 'restore-receipt.json', root) == expected
         and read(source / 'verification.stdout.json', root) == expected
         and digest(restore / 'restore-receipt.json') == public['restoreReceiptSha256']
         and digest(restore / 'original-manifest.json') == public['snapshotManifestSha256'], 'OLD_INDEPENDENT_RESTORE_PROOF_DIFFERS')
    return {'source': source, 'release': old, 'public': public, 'publicSha256': digest(public_file),
            'plan': plan, 'restore': expected, 'manifest': manifest, 'binding': binding}


def disk_budget(archive_bytes, manifest_bytes, restored_bytes, file_count, directory_count, block_bytes):
    need(all(type(value) is int and value >= 0 for value in
             (archive_bytes, manifest_bytes, restored_bytes, file_count, directory_count, block_bytes))
         and file_count > 0 and directory_count > 0 and 512 <= block_bytes <= MIB,
         'MEASURED_SNAPSHOT_BYTES_REQUIRED')
    rounded = lambda value: ((value + block_bytes - 1) // block_bytes) * block_bytes
    copied = rounded(archive_bytes) + rounded(manifest_bytes) + block_bytes
    restored = restored_bytes + file_count * (block_bytes - 1) + directory_count * block_bytes
    metadata = rounded(manifest_bytes) + 4 * MIB
    return {'archiveBytes': archive_bytes, 'manifestBytes': manifest_bytes, 'restoredLogicalBytes': restored_bytes,
        'restoredFileCount': file_count, 'restoredDirectoryCount': directory_count, 'filesystemBlockBytes': block_bytes,
        'copyAllocationBoundBytes': copied, 'restoreAllocationBoundBytes': restored,
        'restoreMetadataAllowanceBytes': metadata, 'reserveBytes': RESERVE,
        'requiredAvailableBytes': RESERVE + copied + restored + metadata}


def available(path):
    info = os.statvfs(path); return info.f_bavail * info.f_frsize


def copy_private(source, target, expected_sha, root):
    owned(source, root, private=True, maximum=512 * MIB)
    actual = hashlib.sha256(); total = 0
    with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as origin, \
            os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as output:
        before = os.fstat(origin.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == os.getuid()
             and stat.S_IMODE(before.st_mode) in (0o400, 0o600), 'COPY_SOURCE_PRIVATE_FILE_REQUIRED')
        for raw in iter(lambda: origin.read(MIB), b''):
            need(available(target.parent) >= RESERVE + len(raw), 'COPY_REACHED_TRUE_DISK_RESERVE')
            actual.update(raw); total += len(raw); output.write(raw)
        output.flush(); os.fsync(output.fileno())
    after = source.stat()
    need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_nlink)
         == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink)
         and total == before.st_size and actual.hexdigest() == expected_sha == digest(target), 'SOURCE_CHANGED_DURING_PRIVATE_COPY')


def restore_process(migration_file, snapshot, restore, args):
    output = snapshot / 'verification.stdout.json'; error = snapshot / 'verification.stderr'
    with os.fdopen(os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stdout, \
            os.fdopen(os.open(error, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stderr:
        process = subprocess.Popen([sys.executable, '-I', '-B', str(migration_file), 'snapshot-verify', '--snapshot', str(snapshot),
            '--restore', str(restore), '--expected-instance-id', args.instance_id, '--expected-machine-id', args.machine_id],
            stdout=stdout, stderr=stderr, start_new_session=True,
            env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'PYTHON_DOTENV_DISABLED': '1'})
        deadline = time.monotonic() + 600
        try:
            while process.poll() is None:
                need(time.monotonic() < deadline and available(snapshot) >= RESERVE, 'OWNED_RESTORE_RESOURCE_OR_TIME_RESERVE_REACHED')
                time.sleep(0.5)
            need(process.returncode == 0, 'INDEPENDENT_ECS_BYTE_RESTORE_FAILED')
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=5)
            raise


def run(args):
    need(sys.platform == 'linux' and TAG.fullmatch(args.tag or '') and re.fullmatch(r'[a-f0-9]{40}', args.commit or '')
         and args.tag.endswith('-' + args.commit[:12]) and re.fullmatch(r'[a-f0-9]{64}', args.source_sha256 or ''),
         'FIXED_ECS_REUSE_REQUEST_REQUIRED')
    root = Path(args.root); need(root.parts[1] in ('home', 'srv', 'opt'), 'ADMITTED_CI_ROOT_REQUIRED')
    checkout = fixed_source(args)
    verifier = module('fixed_reuse_remote', checkout / 'script/jenkins/verify-remote.py')
    cleanup = module('fixed_reuse_cleanup', checkout / 'script/jenkins/cleanup-ecs-builds.py')
    migration_file = checkout / 'script/memory/migrate_legacy_stores.py'
    migration = module('fixed_reuse_migration', migration_file)
    identity = verifier.ecs_identity(args.instance_id, args.machine_id)
    current_file = checkout.parent / 'verification-receipt.json'
    current = passing_receipt(current_file, root, args.tag, identity)
    current_sha = digest(current_file)
    need(current['commit'] == args.commit and current['sourceSha256'] == args.source_sha256, 'CURRENT_PASS_SOURCE_DIFFERS')
    admitted = admit_snapshot(root, Path(args.source_snapshot), args.tag, identity, migration, cleanup, verifier)
    work = owned(checkout / 'work', root, directory=True)
    snapshot, restore = work / 'legacy-source-snapshot', work / 'legacy-source-restore'
    need(not snapshot.exists() and not snapshot.is_symlink() and not restore.exists() and not restore.is_symlink(),
         'FRESH_CURRENT_SNAPSHOT_AND_RESTORE_REQUIRED')
    public = admitted['public']; directories = {'.'}
    for row in admitted['manifest']['files']:
        for parent in Path(row['path']).parents: directories.add(parent.as_posix())
    filesystem = os.statvfs(work)
    budget = disk_budget(public['archiveBytes'], public['manifestBytes'], public['bytes'], public['files'],
                         len(directories), max(filesystem.f_frsize, filesystem.f_bsize))
    baseline = available(work); need(baseline >= budget['requiredAvailableBytes'], 'CURRENT_DISK_CANNOT_RETAIN_COPY_RESTORE_AND_RESERVE')
    snapshot.mkdir(mode=0o700)
    try:
        copy_private(admitted['source'] / 'snapshot.json', snapshot / 'snapshot.json', public['snapshotManifestSha256'], root)
        copy_private(admitted['source'] / 'originals.tar', snapshot / 'originals.tar', public['archiveSha256'], root)
        restore_process(migration_file, snapshot, restore, args)
        owned(restore / 'original-manifest.json', root, private=True)
        need(read(snapshot / 'verification.stdout.json', root) == admitted['restore']
             and read(restore / 'restore-receipt.json', root) == admitted['restore']
             and digest(restore / 'original-manifest.json') == public['snapshotManifestSha256'], 'NEW_INDEPENDENT_RESTORE_DIFFERS')
        need(digest(admitted['source'] / 'preservation-public.json') == admitted['publicSha256']
             and digest(admitted['source'] / 'snapshot.json') == public['snapshotManifestSha256']
             and digest(admitted['source'] / 'originals.tar') == public['archiveSha256']
             and digest(admitted['source'].parents[2] / 'verification-receipt.json') == public['verificationReceiptSha256']
             and digest(root / 'inbox' / admitted['release'] / 'source.tar.gz') == public['sourceSha256'],
             'OLD_ORIGINALS_CHANGED_DURING_REUSE')
        cleanup.quiescent(admitted['binding'], admitted['release'], cleanup.docker_snapshot())
        fixed_source(args)
        need(digest(current_file) == current_sha, 'CURRENT_PASS_RECEIPT_CHANGED_DURING_REUSE')
        result = {**admitted['restore'], 'kind': 'doorhandle-legacy-source-preservation', 'schemaVersion': 1,
            'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
            'scriptSha256': digest(migration_file), 'identity': identity,
            'restoreReceiptSha256': digest(restore / 'restore-receipt.json'), 'verificationReceiptSha256': current_sha,
            **{key: public[key] for key in ('archiveBytes', 'manifestBytes', 'profile', 'archiveEncoding', 'kafkaFiles', 'kafkaBytes')},
            'memberInventorySha256': admitted['plan']['memberInventorySha256'],
            'legacyKafkaReplay': 'NOT_PERFORMED', 'sourceSnapshotReuse': {'kind': 'doorhandle-ecs-legacy-snapshot-reuse-v1',
                'release': admitted['release'], 'publicSha256': admitted['publicSha256'], 'oldOriginalsPreserved': True}}
        write(snapshot / 'reuse-resource-proof.json', {'status': 'COPY_AND_RESTORE_COMPLETED', **budget,
            'availableBytesBefore': baseline, 'availableBytesAfter': available(work)})
        write(snapshot / 'preservation-public.json', result)
        return result
    except BaseException as error:
        write(snapshot / 'preservation-failed.json', {'status': 'FAILED', **refusal_details(error)})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id', 'source-snapshot'):
        parser.add_argument('--' + name, required=True)
    try:
        print(json.dumps(run(parser.parse_args()), sort_keys=True)); return 0
    except BaseException as error:
        print(json.dumps({'status': 'REFUSED', **refusal_details(error)}), file=sys.stderr); return 2


if __name__ == '__main__': raise SystemExit(main())
