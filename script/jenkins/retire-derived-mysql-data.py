"""Retire one explicitly approved, stopped test-replica batch; retain its SQL.

This closed batch is separate from container retirement's data-retention contract.
The privileged worker accepts no arbitrary directory and opens no MySQL contents.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
import importlib.util
import io
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

LOADED_SOURCE = None if __name__ == '_approved_worker' else Path(__file__).read_bytes()
BATCH = 'derived-mysql-221-222-235-238-247-v1'
RECENT_BATCH = 'derived-mysql-250-253-256-259-264-268-v1'
FOLLOWUP_BATCH = 'derived-mysql-281-283-v1'
ROOT = Path('/home/ecs-user/doorhandle-ci')
INSTANCE = 'i-2zeieuov2aum486jm1ek'
MACHINE = '1ebe8f77e3104ab6a49a9386e38abd20'
TARGETS = {
    'ci-221-8c30776fcd95': (3940427, '8c30776fcd95ed6347494ce5904e5ad7de1867ab'),
    'ci-222-936bdb3e91e2': (3958297, '936bdb3e91e23cbc7daf717333f326b61d43170f'),
    'ci-235-7067d66585cd': (2177178, '7067d66585cd181f4ef8d5cf2345eb4e7851ff17'),
    'ci-238-73ce5aeff862': (2177592, '73ce5aeff86201d9b2776159903acd5907c8420a'),
    'ci-247-abb4a9f35efc': (2697383, 'abb4a9f35efc510d2ef8aa3dec8a42c109395b06'),
}
BACKUP_MANIFESTS = {
    'ci-221-8c30776fcd95': 'fead750efa908141dfad088aebdcf1c9b084b29306f24f5bc0bf45332f077677',
    'ci-222-936bdb3e91e2': '2b596eefe4174de416b29d1b48013b0763f9a627553fb9504a0f458cfdb9ed50',
    'ci-235-7067d66585cd': '5708d62019777e0e9a69e603a17c8803dc5a7d0e89ed97abda36b7839a4d3fc8',
    'ci-238-73ce5aeff862': 'fafd2fb2fa55b4ec2c6d80500d372ccdee6be721da7322c9a70f398e8c2840ac',
    'ci-247-abb4a9f35efc': '8ed4185781611e1905547a178aa0d70484274e2288133a89ab0b31b10279c129',
}
SOURCE_SNAPSHOT = '147dd664c907f079970a0317af60d78eba893010725093d96190e0dd37fd8d82'
APPROVED_METADATA = {
    'ci-221-8c30776fcd95': (311, 265048064),
    'ci-222-936bdb3e91e2': (300, 262062080),
    'ci-235-7067d66585cd': (311, 266653696),
    'ci-238-73ce5aeff862': (328, 289935360),
    'ci-247-abb4a9f35efc': (311, 266706944),
}
RECENT_TARGETS = {
    'ci-250-6444cbc36a65': (1525007, '6444cbc36a653a5e068d95c3138d67ab0b9ca01c'),
    'ci-253-e441933dc75b': (2310434, 'e441933dc75bde0f1fb09cf8e6de4c15130eddfb'),
    'ci-256-9f90b9283367': (1918346, '9f90b92833678240188a0ea68a2ec8ca3d137605'),
    'ci-259-516614e07542': (2965403, '516614e0754249d062103ed64f3d5337fdbee29e'),
    'ci-264-2ff9edc00291': (2050112, '2ff9edc00291f558d6a267f617757911d128ad3e'),
    'ci-268-b3f23013513b': (3610894, 'b3f23013513b11af5041c67569a8f029651aa8db'),
}
RECENT_BACKUP_MANIFESTS = {
    'ci-250-6444cbc36a65': '091403eed082fd4b37c897090417124402979f823814777c61bb06e27d7e5078',
    'ci-253-e441933dc75b': '4b8150d34f16df5cccdb024047cf11537fea3f656baf725e2042cf514479471b',
    'ci-256-9f90b9283367': 'b6f2e2ef20156fef963057fbf504a7940c3ca03e30d564f59dcb3de34034a5a4',
    'ci-259-516614e07542': 'b60c394e2ef33ab948dd95fa4d90ff2983ec14ad1a1e0fcb358e9ac0ee1704e5',
    'ci-264-2ff9edc00291': '9bc30ad8b14a3ceabc74b2e681698c9cb3e714b6e3ca498a3fd114ce671d3c68',
    'ci-268-b3f23013513b': '70eeb86a4e386d8bfba4b93141bbf4d2c57d9cf06db04ed2fa8c82f61248820b',
}
RECENT_APPROVED_METADATA = {
    'ci-250-6444cbc36a65': (311, 266702848),
    'ci-253-e441933dc75b': (311, 265072640),
    'ci-256-9f90b9283367': (300, 262090752),
    'ci-259-516614e07542': (300, 262103040),
    'ci-264-2ff9edc00291': (330, 288403456),
    'ci-268-b3f23013513b': (369, 308985856),
}
FOLLOWUP_TARGETS = {
    'ci-281-81244ba1761d': (4474349, '81244ba1761dcd96a1bdfb7e00154c950e778f3e'),
    'ci-283-30f03c1b1535': (1775872, '30f03c1b15354b9585aee1e4594d53f9f57e802c'),
}
FOLLOWUP_BACKUP_MANIFESTS = {
    'ci-281-81244ba1761d': '51f742817aad0d36020af05fad0791147d0ae622167c780c5ba937d02b7f24dc',
    'ci-283-30f03c1b1535': 'e1524fcf84dd2c6981564ee83eccf09ddfaef5d19101e0c7917ae14485a67fbe',
}
FOLLOWUP_APPROVED_METADATA = {
    'ci-281-81244ba1761d': (369, 308858880),
    'ci-283-30f03c1b1535': (374, 311005184),
}
SHA = re.compile(r'[a-f0-9]{64}')
MIB = 1024 ** 2
TASK_BATCH = 'current-task-failed-verify-mysql-v1'
TASK_ID = '01a1a46b-d37a-7fb2-8638-afe345c73531'


class TaskBatch:
    """Internal, authenticated target set; never a caller-supplied filesystem path."""
    def __init__(self, targets, manifests):
        self.targets, self.manifests = targets, manifests
        self.metadata = {release: None for release in targets}


def need(value, code):
    if not value:
        raise ValueError(code)


def batch_configuration(batch=BATCH):
    # Preserve the original default and select exactly one closed set, never a union.
    if isinstance(batch, TaskBatch):
        return batch.targets, batch.manifests, batch.metadata
    if batch == BATCH:
        return TARGETS, BACKUP_MANIFESTS, APPROVED_METADATA
    if batch == RECENT_BATCH:
        need(set(RECENT_TARGETS) == set(RECENT_BACKUP_MANIFESTS) == set(RECENT_APPROVED_METADATA),
             'COMPLETE_APPROVED_BATCH_REQUIRED')
        return RECENT_TARGETS, RECENT_BACKUP_MANIFESTS, RECENT_APPROVED_METADATA
    need(batch == FOLLOWUP_BATCH, 'CLOSED_BATCH_REQUIRED')
    need(len(FOLLOWUP_TARGETS) == 2
         and set(FOLLOWUP_TARGETS) == set(FOLLOWUP_BACKUP_MANIFESTS) == set(FOLLOWUP_APPROVED_METADATA),
         'COMPLETE_APPROVED_BATCH_REQUIRED')
    return FOLLOWUP_TARGETS, FOLLOWUP_BACKUP_MANIFESTS, FOLLOWUP_APPROVED_METADATA


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def signature(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_blocks]


def safe(path):
    path = Path(path)
    need(path.is_absolute() and path.resolve(strict=True) == path, 'CANONICAL_PATH_REQUIRED')
    need(all(not p.is_symlink() for p in (path, *path.parents)), 'LINKED_PATH_REFUSED')
    return path


def read(path, maximum=2 * MIB):
    path = safe(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
             and not before.st_mode & 0o022 and 0 <= before.st_size <= maximum, 'PRIVATE_REGULAR_INPUT_REQUIRED')
        raw = stream.read(maximum + 1)
        need(len(raw) == before.st_size and signature(os.fstat(stream.fileno())) == signature(before)
             == signature(path.stat()), 'INPUT_CHANGED')
    return raw


def write(path, value):
    raw = encoded(value); need(len(raw) <= 8 * MIB, 'OUTPUT_BOUND_EXCEEDED')
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())


def data_path(release, batch=BATCH):
    targets, _, _ = batch_configuration(batch)
    need(release in targets, 'CLOSED_BATCH_TARGET_REQUIRED')
    return ROOT / 'verification' / release / 'checkout/work/compact-fixtures/mysql-data'


def tree(release, batch=BATCH):
    targets, _, metadata = batch_configuration(batch)
    path = safe(data_path(release, batch)); before = path.stat(); expected = targets[release][0]
    need(stat.S_ISDIR(before.st_mode) and before.st_dev == 64771 and before.st_ino == expected
         and before.st_uid == 999 and before.st_gid == 1000 and stat.S_IMODE(before.st_mode) == 0o700,
         'ORIGINAL_DERIVED_DIRECTORY_REQUIRED')
    rows = []; deadline = time.monotonic() + 20
    def visit(fd, prefix='', depth=0):
        need(depth <= 32 and time.monotonic() < deadline, 'INVENTORY_BOUND_EXCEEDED')
        for name in sorted(os.listdir(fd)):
            need(len(rows) < 10000 and time.monotonic() < deadline, 'INVENTORY_BOUND_EXCEEDED')
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            need(info.st_dev == before.st_dev and info.st_uid == 999
                 and (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) and info.st_nlink == 1),
                 'DERIVED_ENTRY_LINK_OWNER_OR_DEVICE_DIFFERS')
            relative = prefix + name; rows.append({'path': relative, 'metadata': signature(info)})
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    need(signature(os.fstat(child)) == signature(info), 'DIRECTORY_CHANGED')
                    visit(child, relative + '/', depth + 1)
                finally:
                    os.close(child)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        need(signature(os.fstat(fd)) == signature(before), 'ROOT_CHANGED')
        visit(fd)
    finally:
        os.close(fd)
    need(signature(path.stat()) == signature(before), 'ROOT_CHANGED')
    files = sum(stat.S_ISREG(row['metadata'][2]) for row in rows)
    allocated = before.st_blocks * 512 + sum(row['metadata'][9] * 512 for row in rows)
    if metadata[release] is not None:
        need((files, allocated) == metadata[release], 'APPROVED_METADATA_INVENTORY_CHANGED')
    return {'release': release, 'path': str(path), 'rootMetadata': signature(before), 'entries': rows,
            'allocatedBytes': allocated, 'files': files,
            'inventorySha256': digest(encoded(rows))}


def remove_tree(item, batch=BATCH):
    release = item['release']; path = data_path(release, batch)
    need(tree(release, batch) == item, 'DERIVED_TREE_CHANGED_AFTER_PLAN')
    entries = {row['path']: row['metadata'] for row in item['entries']}
    def remove(fd, prefix=''):
        for name in sorted(os.listdir(fd)):
            relative = prefix + name
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            need(relative in entries and signature(info) == entries[relative], 'ENTRY_CHANGED_AFTER_PLAN')
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    need(signature(os.fstat(child)) == entries[relative], 'DIRECTORY_CHANGED_AFTER_PLAN')
                    remove(child, relative + '/')
                finally:
                    os.close(child)
                os.rmdir(name, dir_fd=fd)
            else:
                need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'LINKED_DELETION_REFUSED')
                os.unlink(name, dir_fd=fd)
    parent = os.open(safe(path.parent), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open('mysql-data', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            need(signature(os.fstat(fd)) == item['rootMetadata'], 'ROOT_CHANGED_AFTER_PLAN')
            remove(fd)
        finally:
            os.close(fd)
        # Child removal changes directory times/size; its original inode/owner must remain.
        info = os.stat('mysql-data', dir_fd=parent, follow_symlinks=False)
        need([info.st_dev, info.st_ino, info.st_uid, info.st_gid]
             == [item['rootMetadata'][i] for i in (0, 1, 3, 4)], 'ROOT_REPLACED_DURING_RETIREMENT')
        os.rmdir('mysql-data', dir_fd=parent)
    finally:
        os.close(parent)


def process_references(inventories, proc=Path('/proc')):
    """Administrator metadata check for every user, including root and MySQL.

    Paths and inode identities cover chroot/mount aliases. Never return argv,
    map contents, descriptor names, or unrelated process paths to the controller.
    ``proc`` is an internal synthetic-test injection, not a CLI/root request.
    """
    need(os.getuid() == 0, 'ROOT_REFERENCE_PROBE_REQUIRED')
    roots = [Path(item['path']) for item in inventories]
    inode_keys = set()
    for item in inventories:
        for meta in (item['rootMetadata'], *(row['metadata'] for row in item['entries'])):
            inode_keys.add((meta[0], meta[1]))
    map_keys = {(os.major(dev), os.minor(dev), inode) for dev, inode in inode_keys}
    def refers(value):
        text = os.fsdecode(value).removesuffix(' (deleted)')
        if '=' in text and not text.startswith('/'): text = text.split('=', 1)[1]
        path = Path(text)
        return path.is_absolute() and any(path == root or path.is_relative_to(root) for root in roots)
    def inode_ref(path):
        info = os.stat(path)
        return (info.st_dev, info.st_ino) in inode_keys
    def bounded(path, maximum):
        with path.open('rb') as stream: raw = stream.read(maximum + 1)
        need(len(raw) <= maximum, 'PROCESS_METADATA_BOUND_EXCEEDED')
        return raw
    def process_state(entry):
        raw = bounded(entry / 'stat', 4096)
        fields = raw.rsplit(b')', 1)[1].split()
        need(raw.split(b' ', 1)[0] == entry.name.encode('ascii') and len(fields) >= 20, 'PROCESS_STAT_INVALID')
        return fields[0].decode('ascii'), int(fields[6]), fields[19].decode('ascii')
    entries = list(proc.iterdir()); need(len(entries) <= 65536, 'PROCESS_COUNT_BOUND_EXCEEDED')
    checked = 0; users = set()
    for entry in entries:
        if not entry.name.isdecimal() or int(entry.name) == os.getpid(): continue
        try:
            before = entry.stat(); state, flags, ticks = process_state(entry)
            if state in ('Z', 'X') or flags & 0x00200000: continue  # No userspace references.
            for name in ('cwd', 'root'):
                pointer = entry / name
                need(not refers(os.readlink(pointer)) and not inode_ref(pointer), 'ACTIVE_PROCESS_DIRECTORY_REFERENCE')
            argv = bounded(entry / 'cmdline', MIB)
            need(not any(refers(arg) for arg in argv.split(b'\0') if arg), 'ACTIVE_PROCESS_ARGUMENT_REFERENCE')
            descriptors = list((entry / 'fd').iterdir())
            need(len(descriptors) <= 8192, 'PROCESS_DESCRIPTOR_BOUND_EXCEEDED')
            for descriptor in descriptors:
                try:
                    need(not refers(os.readlink(descriptor)) and not inode_ref(descriptor), 'ACTIVE_PROCESS_FILE_REFERENCE')
                except (FileNotFoundError, ProcessLookupError):
                    try: descriptor.lstat()
                    except (FileNotFoundError, ProcessLookupError): continue
                    raise ValueError('PROCESS_DESCRIPTOR_CHANGED_DURING_PROBE')
            maps = bounded(entry / 'maps', 16 * MIB)
            for line in maps.splitlines():
                fields = line.split(None, 5)
                need(len(fields) >= 5, 'PROCESS_MAP_METADATA_INVALID')
                major, minor = (int(value, 16) for value in fields[3].split(b':'))
                need((major, minor, int(fields[4])) not in map_keys
                     and not (len(fields) == 6 and refers(fields[5])), 'ACTIVE_PROCESS_MAP_REFERENCE')
            after = entry.stat(); _, _, after_ticks = process_state(entry)
            need((before.st_dev, before.st_ino, before.st_uid) == (after.st_dev, after.st_ino, after.st_uid)
                 and ticks == after_ticks, 'PROCESS_IDENTITY_CHANGED_DURING_PROBE')
            checked += 1; users.add(before.st_uid)
        except (FileNotFoundError, ProcessLookupError):
            if not entry.exists(): continue
            state, flags, _ = process_state(entry)
            need(state in ('Z', 'X') or flags & 0x00200000, 'LIVE_PROCESS_METADATA_UNAVAILABLE')
    return {'status': 'QUIESCENT', 'scope': 'ALL_UIDS_CLOSED_DATA_DIRECTORIES',
            'processesChecked': checked, 'uidsChecked': sorted(users)}


def root_worker(request):
    if request.get('phase') in ('task-inventory', 'task-remove'):
        return task_root_worker(request)
    need(os.getuid() == 0 and request.get('batch') in (BATCH, RECENT_BATCH, FOLLOWUP_BATCH)
         and Path('/etc/machine-id').read_text().strip() == MACHINE, 'APPROVED_ROOT_BATCH_REQUIRED')
    batch = request['batch']; selected, _, _ = batch_configuration(batch)
    phase = request.get('phase'); need(phase in ('inventory', 'remove'), 'ROOT_OPERATION_REFUSED')
    if phase == 'inventory':
        need(set(request) == {'phase', 'batch'}, 'ARBITRARY_ROOT_ARGUMENT_REFUSED')
        targets = [tree(release, batch) for release in selected]
        return {'targets': targets, 'processProbe': process_references(targets)}
    need(set(request) == {'phase', 'batch', 'target'}, 'ARBITRARY_ROOT_ARGUMENT_REFUSED')
    item = request['target']; need(item.get('release') in selected, 'CLOSED_BATCH_TARGET_REQUIRED')
    need(tree(item['release'], batch) == item, 'DERIVED_TREE_CHANGED_AFTER_PLAN')
    probe = process_references([item])
    remove_tree(item, batch)
    return {'release': item['release'], 'status': 'REMOVED', 'allocatedBytesBefore': item['allocatedBytes'],
            'processProbe': probe}


def privileged(request):
    need(os.getuid() == 1000 and type(LOADED_SOURCE) is bytes
         and read(Path(__file__).absolute(), MIB) == LOADED_SOURCE, 'ADMITTED_PRIVILEGED_SOURCE_CHANGED')
    payload = LOADED_SOURCE + b'\nprint(json.dumps(root_worker(json.loads(' + repr(encoded(request).decode()).encode() + b'))))\n'
    # The timeout itself has administrator identity, so it can stop its own
    # privileged child before the unprivileged transport deadline expires.
    command = ['sudo', '-n', 'timeout', '--signal=TERM', '--kill-after=2s', '90s', sys.executable, '-I', '-B', '-c',
               "import sys; s=sys.stdin.buffer.read(2097153); assert len(s)<=2097152; exec(compile(s,'<closed-derived-mysql>','exec'),{'__name__':'_approved_worker','__file__':sys.argv[1]})",
               str(Path(__file__).absolute())]
    process = subprocess.run(command, input=payload, capture_output=True, timeout=100)
    need(process.returncode == 0 and len(process.stdout) <= 4 * MIB, 'PRIVILEGED_OPERATION_NOT_CONFIRMED')
    return json.loads(process.stdout)


@contextmanager
def lock(path):
    path = safe(path)
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        need(stat.S_ISREG(info.st_mode) and info.st_uid == 1000 and info.st_nlink == 1
             and not info.st_mode & 0o022, 'EXISTING_PRIVATE_LOCK_REQUIRED')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


@contextmanager
def attempt_lock(release):
    path = safe(ROOT / 'verification' / release)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        need(info.st_uid == 1000 and not info.st_mode & 0o022 and stat.S_ISDIR(info.st_mode),
             'OLD_ATTEMPT_DIRECTORY_OWNER_DIFFERS')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def keeper_binding(release, batch=BATCH):
    targets, manifests, _ = batch_configuration(batch)
    work = data_path(release, batch).parent
    owner_raw = read(work.parent / 'compact-fixtures-owner.json')
    owner = json.loads(owner_raw); cleanup_raw = read(work / 'cleanup-receipt.json'); cleanup = json.loads(cleanup_raw)
    need(owner.get('release') == release and owner.get('commit') == targets[release][1]
         and owner.get('phase') == 'OWNED_SERVER_STOPPED' and owner.get('dataDirectory') == str(data_path(release, batch))
         and owner.get('sourceTableCount') == 131 and SHA.fullmatch(owner.get('sourceSha256', ''))
         and owner.get('sourceClone') == 'doorhandle_migration_verify_' + owner.get('token', '')
         and re.fullmatch(r'[a-f0-9]{10,64}', owner.get('token', ''))
         and owner.get('containerId') != owner.get('sourceContainerId'),
         'OLD_TEST_OWNERSHIP_NOT_PROVEN')
    need(cleanup.get('status') == 'STOPPED' and cleanup.get('errors') == []
         and cleanup.get('containerId') == owner.get('containerId')
         and cleanup.get('dataDirectoryRetained') == str(data_path(release, batch))
         and cleanup.get('sourceDumpAndEvidenceRetained') is True, 'OLD_TEST_STOP_NOT_PROVEN')
    manifest_raw = read(work / 'source-backup/manifest.json'); manifest = json.loads(manifest_raw)
    need(digest(manifest_raw) == owner.get('sourceBackupSha256') == manifests[release]
         and manifest.get('snapshotSha256') == owner.get('sourceSnapshotSha256')
         == owner.get('sourceCloneSnapshotSha256') == SOURCE_SNAPSHOT and len(manifest.get('tables', {})) == 131
         and manifest.get('data', {}).get('file') == 'data.sql', 'COMPLETE_SOURCE_BACKUP_REQUIRED')
    sql = read(work / 'source-backup/data.sql', 128 * MIB)
    need(len(sql) == manifest['data']['bytes'] and digest(sql) == manifest['data']['sha256'], 'SOURCE_SQL_INTEGRITY_FAILED')
    return {'release': release, 'commit': owner['commit'], 'sourceSha256': owner['sourceSha256'],
            'ownerSha256': digest(owner_raw), 'cleanupSha256': digest(cleanup_raw),
            'backupManifestSha256': digest(manifest_raw), 'sourceSqlSha256': digest(sql),
            'sourceSqlBytes': len(sql), 'sourceSnapshotSha256': owner['sourceSnapshotSha256'],
            'token': owner['token']}


def fixed_helpers(args):
    import tarfile
    # Maintenance deliberately uses a separate source transport from runtime CI.
    source = read(ROOT / 'inbox' / args.tag / 'cleanup-source.tar.gz', 128 * MIB)
    need(digest(source) == args.source_sha256, 'FIXED_SOURCE_CHANGED')
    import io
    names = ('retire-derived-mysql-data.py', 'cleanup-ecs-builds.py', 'verify-remote.py')
    bodies = {}
    with tarfile.open(fileobj=io.BytesIO(source), mode='r:gz') as archive:
        need(archive.pax_headers.get('comment') == args.commit, 'FIXED_SOURCE_COMMIT_DIFFERS')
        for member in archive:
            if member.name not in ('script/jenkins/' + name for name in names):
                continue
            name = member.name.rsplit('/', 1)[-1]
            need(name not in bodies and member.isfile() and 0 < member.size <= MIB, 'FIXED_HELPER_CLOSURE_DIFFERS')
            bodies[name] = archive.extractfile(member).read(MIB + 1)
    need(set(bodies) == set(names), 'FIXED_HELPER_CLOSURE_MISSING')
    modules = {}
    for name in names:
        path = ROOT / 'inbox' / args.tag / name
        need(read(path, MIB) == bodies[name], 'FIXED_HELPER_BYTES_DIFFER')
        if name == names[0]:
            need(Path(__file__).absolute() == path and bodies[name] == LOADED_SOURCE, 'FIXED_EXECUTOR_REQUIRED')
            continue
        spec = importlib.util.spec_from_file_location('derived_' + name.replace('-', '_'), path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); modules[name] = module
    return modules


def run(args):
    if getattr(args, 'failed_builds', None) is not None:
        return task_run(args)
    need(os.getuid() == 1000 and args.batch in (BATCH, RECENT_BATCH, FOLLOWUP_BATCH) and re.fullmatch(r'ci-[0-9]+-[a-f0-9]{12}', args.tag)
         and re.fullmatch(r'[a-f0-9]{40}', args.commit) and args.tag.endswith(args.commit[:12])
         and int(args.tag.split('-')[1]) > (271 if args.batch == BATCH else 278 if args.batch == RECENT_BATCH else 283)
         and SHA.fullmatch(args.source_sha256), 'EXPLICIT_FIXED_MAINTENANCE_REQUIRED')
    batch = args.batch; targets, _, _ = batch_configuration(batch)
    modules = fixed_helpers(args); verifier = modules['verify-remote.py']; cleanup = modules['cleanup-ecs-builds.py']
    identity = verifier.ecs_identity(INSTANCE, MACHINE)
    output = ROOT / 'inbox' / args.tag / 'derived-mysql-retirement'
    plan_file = output / 'plan-private.json'; public_file = output / 'plan.json'; receipt_file = output / 'receipt.json'
    execution_file = output / 'execution.json'
    if args.phase == 'status':
        binding = {'batch': batch, 'release': args.tag, 'commit': args.commit,
                   'sourceSha256': args.source_sha256, 'identity': identity}
        if receipt_file.exists():
            value = json.loads(read(receipt_file))
            need(all(value.get(key) == expected for key, expected in binding.items()), 'TERMINAL_BINDING_DIFFERS')
            return {'status': value['status'], 'terminal': True, **binding}
        if execution_file.exists():
            execution = json.loads(read(execution_file))
            need(all(execution.get(key) == expected for key, expected in binding.items())
                 and execution.get('bootId') == Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                 'EXECUTION_IDENTITY_DIFFERS')
            try:
                raw_stat = Path('/proc') / str(execution['pid']) / 'stat'
                fields = raw_stat.read_text().rsplit(')', 1)[1].split()
                alive = fields[19] == execution['startTicks'] and fields[0] not in ('Z', 'X')
            except FileNotFoundError:
                alive = False
            need(alive, 'EXECUTION_STOPPED_WITHOUT_TERMINAL_RECEIPT')
            return {'status': 'RUNNING', 'terminal': False, **binding}
        return {'status': 'UNKNOWN', 'terminal': False, **binding}
    def admitted():
        containers = cleanup.docker_snapshot(); result = []
        for release in targets:
            need(not (ROOT / 'releases' / release).exists(), 'RETAINED_PUBLISHED_RELEASE_REFUSED')
            value = keeper_binding(release, batch)
            cleanup.quiescent({'checkout': data_path(release, batch).parents[2], 'token': value['token']},
                              release, containers, include_inbox=True)
            result.append(value)
        return result
    with lock(ROOT / 'state/deploy.lock'), ExitStack() as attempts:
        for release in targets:
            attempts.enter_context(attempt_lock(release))
        if args.phase == 'plan':
            need(not output.exists(), 'FRESH_DERIVED_RETIREMENT_REQUIRED'); output.mkdir(mode=0o700)
            keepers = admitted(); measurement = privileged({'phase': 'inventory', 'batch': batch})
            inventory = measurement['targets']
            need(measurement['processProbe']['status'] == 'QUIESCENT', 'ALL_UID_REFERENCE_PROOF_REQUIRED')
            need([item['release'] for item in inventory] == list(targets), 'COMPLETE_CLOSED_INVENTORY_REQUIRED')
            plan = {'batch': batch, 'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
                    'identity': identity, 'keepers': keepers, 'targets': inventory,
                    'processProbe': measurement['processProbe']}
            write(plan_file, plan)
            public = {key: plan[key] for key in ('batch', 'release', 'commit', 'sourceSha256', 'identity')}
            public.update(planSha256=digest(encoded(plan)), targets=[{key: item[key] for key in
                ('release', 'path', 'allocatedBytes', 'files', 'inventorySha256')} for item in inventory],
                sourceSqlAndReportsRetained=True, processProbe=measurement['processProbe'])
            write(public_file, public)
            return {'status': 'PLANNED', 'file': str(public_file), 'privatePlanSha256': digest(encoded(plan))}
        raw = read(plan_file, 8 * MIB); plan = json.loads(raw)
        need(SHA.fullmatch(args.plan_sha256 or '') and digest(raw) == args.plan_sha256
             and all(plan.get(key) == expected for key, expected in {'batch': batch, 'release': args.tag,
                 'commit': args.commit, 'sourceSha256': args.source_sha256, 'identity': identity}.items())
             and plan['keepers'] == admitted(), 'PLAN_OR_KEEPERS_CHANGED')
        need(not receipt_file.exists(), 'RETIREMENT_ALREADY_ATTEMPTED')
        write(execution_file, {'batch': batch, 'release': args.tag, 'commit': args.commit,
              'sourceSha256': args.source_sha256, 'identity': identity, 'pid': os.getpid(),
              'startTicks': Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19],
              'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip()})
        receipt = {'status': 'FAILED_OR_UNKNOWN', 'batch': batch, 'release': args.tag,
                   'commit': args.commit, 'sourceSha256': args.source_sha256, 'identity': identity,
                   'planSha256': args.plan_sha256, 'removed': [], 'sourceSqlAndReportsRetained': True,
                   'availableBytesBefore': os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize}
        try:
            measurement = privileged({'phase': 'inventory', 'batch': batch})
            need(measurement['processProbe']['status'] == 'QUIESCENT'
                 and measurement['targets'] == plan['targets'], 'TARGETS_CHANGED_AFTER_PLAN')
            receipt['processProbe'] = measurement['processProbe']
            for item in plan['targets']:
                admitted()
                receipt['removed'].append(privileged({'phase': 'remove', 'batch': batch, 'target': item}))
            need(plan['keepers'] == admitted(), 'KEEPERS_CHANGED_AFTER_RETIREMENT')
            receipt['status'] = 'COMPLETE'
        except BaseException as error:
            receipt['errorType'] = type(error).__name__
            raise
        finally:
            receipt['availableBytesAfter'] = os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize
            write(receipt_file, receipt)
        return {'status': receipt['status'], 'file': str(receipt_file), 'removedDirectories': len(receipt['removed'])}


def task_numbers(text, current):
    need(type(text) is str and re.fullmatch(r'[1-9][0-9]{0,8}(,[1-9][0-9]{0,8}){0,15}', text or ''),
         'EXPLICIT_BOUNDED_TASK_BUILDS_REQUIRED')
    numbers = text.split(',')
    need(len(numbers) == len(set(numbers)) and all(287 <= int(value) < current for value in numbers),
         'ONLY_EARLIER_TASK_FAILED_BUILDS_ALLOWED')
    return numbers


def task_helpers(binding):
    """Load only the current committed maintenance source, including pure validators."""
    need(set(binding) == {'tag', 'commit', 'sourceSha256', 'requestSha256', 'failedBuilds'},
         'EXACT_TASK_SOURCE_BINDING_REQUIRED')
    tag, commit = binding['tag'], binding['commit']
    need(re.fullmatch(r'ci-[1-9][0-9]*-[a-f0-9]{12}', tag or '') and
         re.fullmatch(r'[a-f0-9]{40}', commit or '') and tag.endswith('-' + commit[:12]) and
         SHA.fullmatch(binding.get('sourceSha256', '')) and SHA.fullmatch(binding.get('requestSha256', '')),
         'FIXED_TASK_SOURCE_REQUIRED')
    task_numbers(binding['failedBuilds'], int(tag.split('-')[1]))
    raw = read(ROOT / 'inbox' / tag / 'cleanup-source.tar.gz', 128 * MIB)
    need(digest(raw) == binding['sourceSha256'], 'FIXED_TASK_SOURCE_CHANGED')
    wanted = {'retire-derived-mysql-data.py', 'retire-failed-native-jar-duplicates.py',
              'cleanup-ecs-builds.py', 'verify-remote.py'}
    bodies = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        need(archive.pax_headers.get('comment') == commit, 'TASK_SOURCE_COMMIT_DIFFERS')
        for member in archive:
            name = member.name.removeprefix('script/jenkins/')
            if member.name != 'script/jenkins/' + name or name not in wanted:
                continue
            need(name not in bodies and member.isfile() and 0 < member.size <= MIB,
                 'TASK_HELPER_CLOSURE_DIFFERS')
            bodies[name] = archive.extractfile(member).read(MIB + 1)
    need(set(bodies) == wanted, 'TASK_HELPER_CLOSURE_MISSING')
    own = read(ROOT / 'inbox' / tag / 'retire-derived-mysql-data.py', MIB)
    need(own == bodies['retire-derived-mysql-data.py'] and
         (os.getuid() == 0 or own == LOADED_SOURCE), 'FIXED_TASK_EXECUTOR_DIFFERS')
    result = {}
    for name in wanted - {'retire-derived-mysql-data.py'}:
        # Compile the already authenticated bytes; never reopen a module after checking it.
        module = SimpleNamespace(__name__='_task_' + name.replace('-', '_'),
                                 __file__=str(ROOT / 'inbox' / tag / name))
        exec(compile(bodies[name], module.__file__, 'exec'), module.__dict__)
        # Some real helpers snapshot their on-disk file during module import.
        # Root fallbacks must use authenticated archive bytes, not that later read.
        module.LOADED_SOURCE = bodies[name]
        result[name] = module
    return result


def task_request(binding):
    raw = read(ROOT / 'inbox' / binding['tag'] / 'derived-failed-mysql-retirement/request.json')
    need(digest(raw) == binding['requestSha256'], 'AUTHENTICATED_TASK_REQUEST_CHANGED')
    def unique(pairs):
        result = {}
        for key, item in pairs:
            need(key not in result, 'DUPLICATE_TASK_REQUEST_FIELD')
            result[key] = item
        return result
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _value: need(False, 'NONFINITE_TASK_REQUEST'))
    identity = {'instanceId': INSTANCE, 'machineId': MACHINE, 'executionLocation': 'ECS'}
    expected = {'release': binding['tag'], 'commit': binding['commit'], 'sourceSha256': binding['sourceSha256']}
    need(set(value) == {'schemaVersion', 'kind', 'current', 'identity', 'authorization', 'builds', 'candidates'}
         and type(value['schemaVersion']) is int and value['schemaVersion'] == 1 and value['kind'] == 'doorhandle-authorized-failed-mysql-data-request'
         and value['current'] == expected and value['identity'] == identity,
         'TASK_REQUEST_CONTEXT_DIFFERS')
    authorization = value['authorization']
    need(set(authorization) == {'taskThreadId', 'sourceSha256', 'endsWithTask', 'allowArbitraryPath'}
         and authorization['taskThreadId'] == TASK_ID and SHA.fullmatch(authorization.get('sourceSha256', ''))
         and authorization['endsWithTask'] is True and authorization['allowArbitraryPath'] is False,
         'CURRENT_TASK_AUTHORIZATION_REQUIRED')
    numbers = task_numbers(binding['failedBuilds'], int(binding['tag'].split('-')[1]))
    need(value['builds'] == numbers and type(value['candidates']) is list and
         len(value['candidates']) == len(numbers), 'COMPLETE_EXPLICIT_TASK_TARGETS_REQUIRED')
    for number, row in zip(numbers, value['candidates']):
        need(set(row) == {'release', 'commit', 'sourceSha256', 'controls'} and
             re.fullmatch(r'[a-f0-9]{40}', row.get('commit', '')) and
             row['release'] == 'ci-' + number + '-' + row['commit'][:12] and
             SHA.fullmatch(row.get('sourceSha256', '')), 'CANONICAL_FAILED_TASK_TAG_REQUIRED')
        need(set(row['controls']) == {'buildXml', 'release', 'localBuild', 'fixtureCleanupPublic',
                                      'preparation', 'transport'}, 'COMPLETE_ORIGINAL_TASK_CONTROLS_REQUIRED')
        for reference in row['controls'].values():
            need(set(reference) == {'bytes', 'sha256'} and type(reference['bytes']) is int and
                 0 < reference['bytes'] <= 2 * MIB and SHA.fullmatch(reference.get('sha256', '')),
                 'EXACT_ORIGINAL_TASK_CONTROL_REQUIRED')
    return value


def task_source_recipe(native, row):
    raw = read(ROOT / 'inbox' / row['release'] / 'source.tar.gz', 128 * MIB)
    need(digest(raw) == row['sourceSha256'], 'RETAINED_TASK_SOURCE_CHANGED')
    names = ('Jenkinsfile.ecs-monolith', 'script/jenkins/pipeline.ps1', 'script/jenkins/prepare-ecs-tools.py')
    bodies = {}
    class Bounded:
        def __init__(self, source): self.source, self.total = source, 0
        def read(self, size=-1):
            remaining = 512 * MIB - self.total
            block = self.source.read(remaining + 1 if size < 0 else min(size, remaining + 1))
            self.total += len(block)
            need(self.total <= 512 * MIB, 'RETAINED_TASK_SOURCE_EXPANSION_BOUND')
            return block
    import gzip
    with gzip.GzipFile(fileobj=io.BytesIO(raw), mode='rb') as expanded, tarfile.open(fileobj=Bounded(expanded), mode='r|') as archive:
        need(archive.pax_headers.get('comment') == row['commit'], 'RETAINED_TASK_COMMIT_DIFFERS')
        for index, member in enumerate(archive, 1):
            need(index <= 50000 and 0 <= member.size <= 32 * MIB, 'RETAINED_TASK_SOURCE_MEMBER_BOUND')
            if member.name in names:
                need(member.name not in bodies and member.isfile() and 0 < member.size <= MIB,
                     'ORIGINAL_TASK_RECIPE_INVALID')
                bodies[member.name] = archive.extractfile(member).read(MIB + 1)
    need(set(bodies) == set(names) and tuple(digest(bodies[name]) for name in names[:2])
         in native.DATABASE_VERIFY_PUBLICATION_RECIPES and
         digest(bodies[names[2]]) == native.DATABASE_VERIFY_TOOL_PREPARATION_SOURCE,
         'REVIEWED_VERIFY_ONLY_TASK_SOURCE_REQUIRED')
    return {'sourceSha256': digest(raw), 'publicationRecipe': [digest(bodies[name]) for name in names[:2]]}


def task_reports(row, verifier, *, metadata_only=False):
    receipt_path = ROOT / 'verification' / row['release'] / 'verification-receipt.json'
    if not receipt_path.exists() and not receipt_path.is_symlink():
        # A preparation failure can have a complete source backup without ever
        # starting verification. Unknown/partially uploaded attempts are retained.
        need(not (receipt_path.parent / '.verification-claimed').exists() and
             not (ROOT / 'inbox' / row['release'] / 'verify-remote.py').exists() and
             not (ROOT / 'inbox' / row['release'] / 'verification-evidence.tar.gz').exists(),
             'UNKNOWN_OR_PARTIAL_VERIFICATION_REPORT_STATE')
        return {'status': 'NOT_STARTED', 'originalJenkinsControlsRetained': True}
    raw = read(receipt_path)
    need(len(raw) <= verifier.MAX_RECEIPT_BYTES, 'ORIGINAL_REPORT_RECEIPT_BOUND')
    receipt = json.loads(raw)
    args = SimpleNamespace(tag=row['release'], commit=row['commit'], source_sha256=row['sourceSha256'],
                           attempt=receipt.get('attempt'), scope='mysql', instance_id=INSTANCE, machine_id=MACHINE)
    need(re.fullmatch(r'[a-f0-9]{32}', args.attempt or '') and receipt.get('status') in ('PASS', 'FAILED')
         and type(receipt.get('verificationExitCode')) is int
         and ((receipt['status'] == 'PASS' and receipt['verificationExitCode'] == 0)
              or (receipt['status'] == 'FAILED' and receipt['verificationExitCode'] != 0))
         and not receipt.get('evidenceOmissions'),
         'ORIGINAL_FAILED_VERIFICATION_REPORTS_REQUIRED')
    claim = json.loads(read(receipt_path.parent / '.verification-claimed/claim.json'))
    need(claim == {'schema': 1, 'kind': 'doorhandle-ci-claim', 'release': row['release'],
        'attempt': args.attempt, 'commit': row['commit'], 'sourceSha256': row['sourceSha256'],
        'identity': {'instanceId': INSTANCE, 'machineId': MACHINE, 'executionLocation': 'ECS'}, 'scope': 'mysql'},
        'ORIGINAL_VERIFICATION_CLAIM_DIFFERS')
    catalog = verifier.validate_envelope(receipt, args)
    need(bool(catalog), 'ORIGINAL_VERIFICATION_REPORTS_REQUIRED')
    archive_path = safe(ROOT / 'inbox' / row['release'] / 'verification-evidence.tar.gz')
    before = archive_path.stat()
    need(stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
         and not before.st_mode & 0o022 and 0 < before.st_size <= verifier.MAX_EVIDENCE_ARCHIVE,
         'ORIGINAL_REPORT_ARCHIVE_REQUIRED')
    if not metadata_only:
        seen = set()
        with verifier.bounded_tar(archive_path, verifier.MAX_EVIDENCE_BYTES + 16 * MIB) as archive:
            for index, member in enumerate(archive, 1):
                name = verifier.member_path(member.name).as_posix()
                need(index <= verifier.MAX_EVIDENCE_FILES and member.isfile() and name not in seen,
                     'ORIGINAL_REPORT_ARCHIVE_INVALID')
                seen.add(name)
                if index == 1:
                    need(name == 'verification-receipt.json' and member.size == len(raw) and
                         archive.extractfile(member).read(len(raw) + 1) == raw, 'ORIGINAL_REPORT_RECEIPT_CHANGED')
                    continue
                need(name in catalog and member.size == catalog[name]['bytes'], 'ORIGINAL_REPORT_CATALOG_DIFFERS')
                check = hashlib.sha256()
                with archive.extractfile(member) as stream:
                    for block in iter(lambda: stream.read(MIB), b''):
                        check.update(block)
                need(check.hexdigest() == catalog[name]['sha256'], 'ORIGINAL_REPORT_BYTES_CHANGED')
        need(seen == {'verification-receipt.json', *catalog}, 'ORIGINAL_REPORT_ARCHIVE_INCOMPLETE')
    need(signature(before) == signature(archive_path.stat()), 'ORIGINAL_REPORT_ARCHIVE_CHANGED')
    return {'verificationStatus': receipt['status'], 'receiptSha256': digest(raw),
            'archiveMetadata': signature(before), 'reportFiles': len(catalog)}


def task_admitted(binding, value, helpers, *, metadata_only=False):
    native, verifier = helpers['retire-failed-native-jar-duplicates.py'], helpers['verify-remote.py']
    local_names = {**native.UPLOADED_NAMES, 'preparation': 'ecs-tool-preparation.json',
                   'transport': 'ecs-tool-preparation-transport.json'}
    keepers = []
    for row in value['candidates']:
        tag = row['release']; work = ROOT / 'verification' / tag / 'checkout/work/compact-fixtures'
        context = {key: row[key] for key in ('release', 'commit', 'sourceSha256')}
        raw_docs, local = {}, {}
        for role, name in local_names.items():
            raw = read(ROOT / 'inbox' / binding['tag'] / 'failed-mysql-data-controls' / tag / name)
            need(len(raw) == row['controls'][role]['bytes'] and digest(raw) == row['controls'][role]['sha256'],
                 'AUTHENTICATED_JENKINS_TASK_CONTROL_CHANGED')
            if role in native.UPLOADED_NAMES:
                raw_docs[role] = raw
            else:
                local[role] = json.loads(raw)
        for role, path in (('artifactPlan', ROOT / 'inbox' / tag / 'build-artifacts.json'),
                           ('fixtureOwner', work.parent / 'compact-fixtures-owner.json'),
                           ('fixtureCleanup', work / 'cleanup-receipt.json')):
            raw_docs[role] = read(path)
        evidence = native.validate_control_documents(raw_docs, context, value['identity'],
                                                     canonical_jar=True, database_verification=True)
        owner, cleanup = json.loads(raw_docs['fixtureOwner']), json.loads(raw_docs['fixtureCleanup'])
        need(owner.get('dataDirectory') == str(work / 'mysql-data') and owner.get('sourceTableCount') == 131
             and owner.get('sourceClone') == 'doorhandle_migration_verify_' + evidence['ownerToken']
             and owner.get('containerId') != owner.get('sourceContainerId')
             and cleanup.get('dataDirectoryRetained') == str(work / 'mysql-data'), 'EXACT_DERIVED_TASK_OWNER_REQUIRED')
        preparation, transport = local['preparation'], local['transport']
        need(all(document.get(key) == expected for document in (preparation, transport)
                 for key, expected in context.items()) and preparation.get('status') == 'PREPARED'
             and preparation.get('kind') == 'doorhandle-ecs-tool-preparation'
             and preparation.get('identity') == value['identity'] and 'candidateBuilderTools' not in preparation
             and preparation.get('sourceFiles', {}).get('script/jenkins/prepare-ecs-tools.py') == native.DATABASE_VERIFY_TOOL_PREPARATION_SOURCE
             and transport.get('prepareCandidateBuilder') is False and transport.get('status') == 'PREPARED'
             and transport.get('kind') == 'doorhandle-ecs-tool-preparation-transport'
             and type(transport.get('schema')) is int and transport['schema'] == 1
             and transport.get('instanceId') == INSTANCE and transport.get('machineId') == MACHINE
             and type(transport.get('finalExitCode')) is int and transport['finalExitCode'] == 0 and 'buildkitArchive' not in transport,
             'VERIFY_ONLY_TASK_WITHOUT_CANDIDATE_BUILDER_REQUIRED')
        need(not (ROOT / 'inbox' / tag / 'candidate-build-tools').exists()
             and not (work / 'derived-mysql-retired-task.json').exists()
             and not (ROOT / 'releases' / tag).exists(), 'PUBLISHED_CANDIDATE_OR_RETIRED_TASK_REFUSED')
        recipe = task_source_recipe(native, row)
        publication = None if metadata_only else native.canonical_publication_refs(ROOT, tag)
        manifest_raw = read(work / 'source-backup/manifest.json'); manifest = json.loads(manifest_raw)
        need(digest(manifest_raw) == owner.get('sourceBackupSha256') and
             manifest.get('snapshotSha256') == owner.get('sourceSnapshotSha256') == owner.get('sourceCloneSnapshotSha256')
             and SHA.fullmatch(owner.get('sourceSnapshotSha256', '')) and len(manifest.get('tables', {})) == 131
             and manifest.get('data', {}).get('file') == 'data.sql', 'COMPLETE_TASK_SOURCE_BACKUP_REQUIRED')
        sql_sha, sql_bytes = manifest['data'].get('sha256'), manifest['data'].get('bytes')
        need(SHA.fullmatch(sql_sha or '') and type(sql_bytes) is int and 0 < sql_bytes <= 128 * MIB,
             'COMPLETE_TASK_SQL_METADATA_REQUIRED')
        if not metadata_only:
            sql = read(work / 'source-backup/data.sql', 128 * MIB)
            need(len(sql) == sql_bytes and digest(sql) == sql_sha, 'TASK_SOURCE_SQL_INTEGRITY_FAILED')
        keepers.append({**context, 'jenkinsResult': evidence['jenkinsResult'], 'token': evidence['ownerToken'],
            'ownerSha256': digest(raw_docs['fixtureOwner']),
            'cleanupSha256': digest(raw_docs['fixtureCleanup']), 'backupManifestSha256': digest(manifest_raw),
            'sourceSqlSha256': sql_sha, 'sourceSqlBytes': sql_bytes, 'sourceSnapshotSha256': owner['sourceSnapshotSha256'],
            'sourceRecipe': recipe, 'publicationReferences': publication,
            'reports': task_reports(row, verifier, metadata_only=metadata_only)})
    return keepers


def task_configuration(value, keepers, roots):
    tags = [row['release'] for row in value['candidates']]
    need(set(roots) == set(tags) and [row['release'] for row in keepers] == tags,
         'EXACT_TASK_ROOT_IDENTITIES_REQUIRED')
    targets = {}
    for row in value['candidates']:
        meta = roots[row['release']]
        need(type(meta) is list and len(meta) == 5 and all(type(part) is int for part in meta)
             and meta[0] == 64771 and stat.S_ISDIR(meta[2]) and meta[3:] == [999, 1000]
             and stat.S_IMODE(meta[2]) == 0o700, 'TASK_METADATA_DIRECTORY_IDENTITY_REQUIRED')
        targets[row['release']] = (meta[1], row['commit'])
    return TaskBatch(targets, {row['release']: row['backupManifestSha256'] for row in keepers})


def task_root_worker(request):
    need(os.getuid() == 0 and Path('/etc/machine-id').read_text().strip() == MACHINE,
         'APPROVED_TASK_ROOT_IDENTITY_REQUIRED')
    phase = request.get('phase')
    expected = {'phase', 'binding', 'roots'} | ({'target'} if phase == 'task-remove' else set())
    need(set(request) == expected and phase in ('task-inventory', 'task-remove'), 'ARBITRARY_TASK_ROOT_ARGUMENT_REFUSED')
    helpers = task_helpers(request['binding']); value = task_request(request['binding'])
    keepers = task_admitted(request['binding'], value, helpers, metadata_only=True)
    configuration = task_configuration(value, keepers, request['roots'])
    if phase == 'task-inventory':
        targets = [tree(tag, configuration) for tag in configuration.targets]
        return {'targets': targets, 'processProbe': process_references(targets)}
    item = request['target']
    need(item.get('release') in configuration.targets and tree(item['release'], configuration) == item,
         'TASK_TREE_CHANGED_AFTER_PLAN')
    probe = process_references([item]); remove_tree(item, configuration)
    return {'release': item['release'], 'status': 'REMOVED', 'allocatedBytesBefore': item['allocatedBytes'],
            'processProbe': probe}


def task_run(args):
    need(os.getuid() == 1000 and args.batch == TASK_BATCH, 'EXPLICIT_TASK_MAINTENANCE_REQUIRED')
    binding = {'tag': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
               'requestSha256': args.request_sha256, 'failedBuilds': args.failed_builds}
    helpers = task_helpers(binding); value = task_request(binding)
    identity = helpers['verify-remote.py'].ecs_identity(INSTANCE, MACHINE)
    output = ROOT / 'inbox' / args.tag / 'derived-failed-mysql-retirement'
    plan_file, receipt_file, execution_file = (output / name for name in ('plan-private.json', 'receipt.json', 'execution.json'))
    public_binding = {'batch': TASK_BATCH, 'release': args.tag, 'commit': args.commit,
        'sourceSha256': args.source_sha256, 'identity': identity, 'requestSha256': args.request_sha256,
        'taskThreadId': TASK_ID}
    if args.phase == 'status':
        if receipt_file.exists():
            receipt = json.loads(read(receipt_file))
            need(all(receipt.get(key) == expected for key, expected in public_binding.items()), 'TASK_TERMINAL_BINDING_DIFFERS')
            return {**public_binding, 'terminal': True, 'status': receipt['status']}
        if execution_file.exists():
            execution = json.loads(read(execution_file))
            need(execution.get('binding') == public_binding and execution.get('bootId') == Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                 'TASK_EXECUTION_BINDING_DIFFERS')
            try:
                fields = (Path('/proc') / str(execution['pid']) / 'stat').read_text().rsplit(')', 1)[1].split()
                alive = fields[19] == execution['startTicks'] and fields[0] not in ('Z', 'X')
            except FileNotFoundError:
                alive = False
            need(alive, 'TASK_EXECUTION_STOPPED_WITHOUT_TERMINAL')
            return {**public_binding, 'terminal': False, 'status': 'RUNNING'}
        return {**public_binding, 'terminal': False, 'status': 'UNKNOWN'}
    cleanup = helpers['cleanup-ecs-builds.py']
    def admitted():
        keepers = task_admitted(binding, value, helpers)
        containers = cleanup.docker_snapshot()
        for keeper in keepers:
            cleanup.quiescent({'checkout': ROOT / 'verification' / keeper['release'] / 'checkout', 'token': keeper['token']},
                              keeper['release'], containers, include_inbox=True)
        return keepers
    with lock(ROOT / 'state/deploy.lock'), ExitStack() as attempts:
        for row in value['candidates']:
            attempts.enter_context(attempt_lock(row['release']))
        if args.phase == 'plan':
            need(not plan_file.exists() and not receipt_file.exists() and not execution_file.exists(), 'FRESH_TASK_PLAN_REQUIRED')
            keepers = admitted()
            roots = {row['release']: signature(safe(ROOT / 'verification' / row['release'] /
                     'checkout/work/compact-fixtures/mysql-data').stat())[:5] for row in value['candidates']}
            measured = privileged({'phase': 'task-inventory', 'binding': binding, 'roots': roots})
            need(measured['processProbe']['status'] == 'QUIESCENT', 'ALL_UID_TASK_QUIESCENCE_REQUIRED')
            plan = {**public_binding, 'keepers': keepers, 'roots': roots, 'targets': measured['targets'],
                    'processProbe': measured['processProbe']}
            write(plan_file, plan)
            public = {**public_binding, 'planSha256': digest(encoded(plan)), 'sourceSqlAndReportsRetained': True,
                'targets': [{key: target[key] for key in ('release', 'path', 'allocatedBytes', 'files', 'inventorySha256')}
                            for target in measured['targets']], 'processProbe': measured['processProbe']}
            write(output / 'plan.json', public)
            return {'status': 'PLANNED', **public_binding, 'planSha256': public['planSha256']}
        raw = read(plan_file, 8 * MIB); plan = json.loads(raw)
        need(SHA.fullmatch(args.plan_sha256 or '') and digest(raw) == args.plan_sha256 and
             all(plan.get(key) == expected for key, expected in public_binding.items()) and plan['keepers'] == admitted()
             and not receipt_file.exists() and not execution_file.exists(), 'TASK_PLAN_OR_KEEPERS_CHANGED')
        write(execution_file, {'binding': public_binding, 'pid': os.getpid(),
            'startTicks': Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19],
            'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip()})
        receipt = {**public_binding, 'status': 'FAILED_OR_UNKNOWN', 'planSha256': args.plan_sha256,
                   'removed': [], 'sourceSqlAndReportsRetained': True,
                   'availableBytesBefore': os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize}
        try:
            measurement = privileged({'phase': 'task-inventory', 'binding': binding, 'roots': plan['roots']})
            need(measurement['targets'] == plan['targets'] and measurement['processProbe']['status'] == 'QUIESCENT',
                 'TASK_TARGETS_CHANGED_AFTER_PLAN')
            for target in plan['targets']:
                need(plan['keepers'] == admitted(), 'TASK_KEEPERS_CHANGED_BEFORE_REMOVE')
                receipt['removed'].append(privileged({'phase': 'task-remove', 'binding': binding,
                    'roots': plan['roots'], 'target': target}))
            need(plan['keepers'] == admitted(), 'TASK_SQL_SOURCE_OR_REPORTS_CHANGED_AFTER_REMOVE')
            for target in plan['targets']:
                write(ROOT / 'verification' / target['release'] / 'checkout/work/compact-fixtures/derived-mysql-retired-task.json',
                      {**public_binding, 'targetRelease': target['release'], 'status': 'REMOVED', 'planSha256': args.plan_sha256})
            receipt['status'] = 'COMPLETE'
        except BaseException as error:
            receipt['errorType'] = type(error).__name__
            raise
        finally:
            receipt['availableBytesAfter'] = os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize
            write(receipt_file, receipt)
        return {'status': receipt['status'], **public_binding, 'removedDirectories': len(receipt['removed'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('plan', 'apply', 'status'))
    for name in ('batch', 'tag', 'commit', 'source-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--plan-sha256')
    parser.add_argument('--failed-builds')
    parser.add_argument('--request-sha256')
    args = parser.parse_args()
    # Transport loss observes this same operation; it must never replay deletion.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        print(json.dumps(run(args))); return 0
    except BaseException as error:
        print(json.dumps({'status': 'FAILED_OR_UNKNOWN', 'errorType': type(error).__name__}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
