"""Fixed cold bytes only: pack, ECS custody/reuse, and a non-executable retirement plan.

No database reader, source deletion, model loader or business runtime is provided.
The 36-file custody profile remains separate and unchanged.
"""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import gzip
from functools import lru_cache
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import threading
import time
import uuid


ROOT = Path(__file__).absolute().parents[2]
SELF = Path(__file__).absolute()
PROFILE = 'cold-store-originals-v1'
KIND = 'doorhandle-cold-store-byte-custody'
INVENTORY_SHA256 = 'd31a1359676053b4182a0e4a9d15d8647cf17f93b2bc26bd7e84ce01116e2f6d'
FILES = 15750
ORIGINAL_BYTES = 12547814103
TREE_ROOTS = 70
SOURCE_DIRECTORIES = 624
LARGEST_GROUP_BYTES = 258012096
LARGEST_GROUP_FILES = 1180
LARGEST_GROUP_DIRECTORIES = 113
MAX_JSON = 64 * 1024 ** 2
ROOT_EVIDENCE_MAX = MAX_JSON // 2
PROBE_EVIDENCE_MAX = MAX_JSON // 4
FINAL_EVIDENCE_MAX = MAX_JSON // 8
MAX_ARCHIVE = 14 * 1024 ** 3
FLOOR = (2048 + 256) * 1024 ** 2
SNAPSHOT = 'cold-stores-snapshot'
RESTORE = 'cold-stores-restore'
PUBLIC = 'cold-stores-public-receipt.json'
OWNER = 'cold-stores-owner.json'
HAS_REPORTS = True
ROOT_ID_PATTERN = r'(?:mysql|store)-[0-9]{2}'
SOURCE_INVENTORY_SHA256 = None
HISTORY_KINDS = ('HISTORICAL_TEST_SCENARIO_COMPLETE_TREE', 'TOOL_RECEIPT_STORE_COMPLETE_TREE_OWNERSHIP_UNPROVED')
HISTORY_EXCLUDED_KINDS = ('BROWSER_TOOL_PROFILE_COMPLETE_TREE', 'PRIMARY_LEGACY_CHROMA_ALREADY_IN_NAMED_SOURCE_PROFILE',
                          'TRANSPORT_TOOL_CACHE_COMPLETE_TREE')
PROFILES = {
    'cold-store-originals-v1': dict(PROFILE=PROFILE, INVENTORY_SHA256=INVENTORY_SHA256, FILES=FILES,
        ORIGINAL_BYTES=ORIGINAL_BYTES, TREE_ROOTS=TREE_ROOTS, SOURCE_DIRECTORIES=SOURCE_DIRECTORIES,
        LARGEST_GROUP_BYTES=LARGEST_GROUP_BYTES, LARGEST_GROUP_FILES=LARGEST_GROUP_FILES,
        LARGEST_GROUP_DIRECTORIES=LARGEST_GROUP_DIRECTORIES, MAX_ARCHIVE=MAX_ARCHIVE,
        SNAPSHOT=SNAPSHOT, RESTORE=RESTORE, PUBLIC=PUBLIC, OWNER=OWNER, HAS_REPORTS=True,
        ROOT_ID_PATTERN=ROOT_ID_PATTERN, SOURCE_INVENTORY_SHA256=None),
    'cold-store-history-v2': dict(PROFILE='cold-store-history-v2',
        INVENTORY_SHA256='61a9dddc73bbcd15be4dd6ad0cb11aed3ad805862eb99c4940ecf321df25f33a',
        FILES=16417, ORIGINAL_BYTES=486493287, TREE_ROOTS=4041, SOURCE_DIRECTORIES=11379,
        LARGEST_GROUP_BYTES=356070, LARGEST_GROUP_FILES=10, LARGEST_GROUP_DIRECTORIES=5,
        MAX_ARCHIVE=576 * 1024 ** 2, SNAPSHOT='cold-history-snapshot', RESTORE='cold-history-restore',
        PUBLIC='cold-history-public-receipt.json', OWNER='cold-history-owner.json', HAS_REPORTS=False,
        ROOT_ID_PATTERN=r'(?:test|tool)-[0-9]{4}',
        SOURCE_INVENTORY_SHA256='dc5ba47b8f2f0f8c0fc1b818fdb313d0f2dc5ff265b0e84329529574e4e57d0b'),
}
SHA = re.compile(r'[a-f0-9]{64}')
TAG = re.compile(r'ci-([1-9][0-9]*)-([a-f0-9]{12})')
FORBIDDEN = 'work/ecs-only-20261105/micro-followup/checkout'
UTIL_NAME = 'preserve-local-artifacts.py'
PUBLIC_FIELDS = ('version kind profile release commit sourceSha256 identity verificationReceiptSha256 '
                 'inventorySha256 files bytes roots status manifestSha256 archiveSha256 archiveBytes '
                 'sourceCustodyReceiptSha256 restoredRoots restoreReceiptSha256 originalFilesDeleted '
                 'databasesOpened temporaryRestoresRemoved').split()


class ColdError(Exception):
    pass


def need(value, code):
    if not value:
        raise ColdError(code)


def select_profile(name):
    """Explicit CLI selection only; untrusted inventory never selects a recipe."""
    need(isinstance(name, str) and name in PROFILES, 'UNKNOWN_FIXED_COLD_PROFILE')
    globals().update(PROFILES[name])


def group_count():
    return TREE_ROOTS + int(HAS_REPORTS)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@lru_cache(maxsize=None)
def load(name):
    spec = importlib.util.spec_from_file_location('cold_fixed_' + name.replace('.', '_'), SELF.with_name(name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def utility():
    return load(UTIL_NAME)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 ** 2), b''):
            value.update(block)
    return value.hexdigest()


def bootstrap_path(path):
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts and path.resolve(strict=True) == path, 'CANONICAL_COLD_PATH_REQUIRED')
    for parent in (path, *path.parents):
        need(not parent.is_symlink() and not getattr(parent.lstat(), 'st_file_attributes', 0) & 0x400,
             'COLD_LINK_OR_REPARSE_POINT_REFUSED')
    return path


class LimitedReader:
    def __init__(self, source, maximum, check=lambda: None):
        self.source, self.maximum, self.total, self.check = source, maximum, 0, check

    def read(self, size=-1):
        self.check()
        left = self.maximum - self.total
        raw = self.source.read(left + 1 if size < 0 else min(size, left + 1))
        self.total += len(raw)
        need(self.total <= self.maximum, 'COLD_EXPANSION_BOUND_REACHED')
        return raw


def read(path, maximum=MAX_JSON, private=False):
    return utility().read_json(path, maximum, private=private)


def private_json(path, value):
    utility().write_json(path, value)


def safe_source(name):
    utility().member_name(name)
    need(name != FORBIDDEN and not name.startswith(FORBIDDEN + '/'), 'FORBIDDEN_SOURCE_SCOPE')
    return utility().safe(ROOT / name)


def fingerprint(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_nlink, info.st_mode, getattr(info, 'st_file_attributes', 0)]


def inventory(path):
    path = utility().safe(path)
    info = path.lstat()
    need(path.is_file() and info.st_nlink == 1 and info.st_size <= MAX_JSON, 'COLD_INVENTORY_REGULAR_FILE_REQUIRED')
    raw = path.read_bytes()
    need(0 < len(raw) <= MAX_JSON and sha(raw) == INVENTORY_SHA256, 'UNREVIEWED_RAW_INVENTORY')
    value = json.loads(raw)
    need(value.get('kind') == 'doorhandle-local-cold-store-scoped-inventory'
         and value.get('status') == 'MEMBERS_HASHED' and len(value['roots']) == TREE_ROOTS
         and len(value['members']) == FILES and len(value['directories']) == SOURCE_DIRECTORIES
         and value['summary']['issues'] == 0 and value['summary']['approvedForDeletion'] == 0
         and not value['physicalFileAliases'] and not value['overlappingTreeDeclarations'], 'INVENTORY_NOT_CLOSED')
    roots = {row['id']: row for row in value['roots']}
    need(len(roots) == TREE_ROOTS and all(re.fullmatch(ROOT_ID_PATTERN, key) for key in roots), 'ROOT_CATALOG_CHANGED')
    if SOURCE_INVENTORY_SHA256 is not None:
        need(value.get('sourceInventorySha256') == SOURCE_INVENTORY_SHA256
             and value.get('selection') == {'includedKinds': list(HISTORY_KINDS), 'excludedKinds': list(HISTORY_EXCLUDED_KINDS)}
             and all(row.get('kind') in HISTORY_KINDS for row in roots.values()), 'HISTORY_SELECTION_NOT_CLOSED')
    seen = set(); ids = set(); total = 0
    for row in value['members']:
        name = utility().member_name(row['path']); info = row['fingerprint']
        need(name not in seen and not name.startswith(FORBIDDEN + '/') and name != FORBIDDEN
             and len(info) == 8 and info[5] == 1 and info[1] != 0 and tuple(info[:2]) not in ids
             and row['stableDuringHash'] is True and row['bytes'] == info[2] and SHA.fullmatch(row['sha256']), 'MEMBER_IDENTITY_NOT_CLOSED')
        seen.add(name); ids.add(tuple(info[:2])); total += row['bytes']
    need(total == ORIGINAL_BYTES, 'COMPLETE_ORIGINAL_BYTES_REQUIRED')
    return value


def layout(value):
    """Every fixed-profile tree and its declared evidence, including empty dirs."""
    roots = {row['id']: row for row in value['roots']}; root_ids = set(roots)
    groups = {key: {'files': [], 'directories': []} for key in roots}
    if HAS_REPORTS:
        groups['reports'] = {'files': [], 'directories': []}
    for row in value['members']:
        scopes = set(row['scopes']) & root_ids
        need(len(scopes) <= 1, 'OVERLAPPING_SOURCE_MEMBER')
        key = next(iter(scopes)) if scopes else 'reports'
        need(scopes or HAS_REPORTS and row['scopes'] == ['EXACT_EVIDENCE'], 'MEMBER_WITHOUT_EXACT_SCOPE')
        prefix = roots[key]['path'] + '/' if key != 'reports' else ''
        need(row['path'].startswith(prefix), 'SOURCE_ESCAPES_ITS_ROOT')
        relative = row['path'][len(prefix):]
        groups[key]['files'].append({'member': key + '/' + relative, 'source': row['path'],
                                     'bytes': row['bytes'], 'sha256': row['sha256']})
    for row in value['directories']:
        matches = ([key for key in row.get('scopes', []) if key in root_ids] if not HAS_REPORTS else
                   [key for key, root in roots.items() if row['path'] == root['path'] or row['path'].startswith(root['path'] + '/')])
        need(len(matches) == 1, 'DIRECTORY_SCOPE_NOT_EXACT')
        need(row['path'] == roots[matches[0]]['path'] or row['path'].startswith(roots[matches[0]]['path'] + '/'),
             'DIRECTORY_ESCAPES_ITS_ROOT')
        key = matches[0]; suffix = row['path'][len(roots[key]['path']):]
        groups[key]['directories'].append({'member': key + suffix, 'source': row['path']})
    report_dirs = set()
    for row in groups.get('reports', {}).get('files', []):
        parent = Path(row['member']).parent
        while str(parent) != '.':
            report_dirs.add(parent.as_posix()); parent = parent.parent
    if HAS_REPORTS:
        groups['reports']['directories'] = [{'member': name, 'source': name[len('reports/'):] if name != 'reports' else None}
                                            for name in sorted(report_dirs)]
    seen = set()
    for key, group in groups.items():
        need(group['files'], 'EMPTY_SOURCE_GROUP')
        group['directories'].sort(key=lambda row: (row['member'].count('/'), row['member']))
        group['files'].sort(key=lambda row: row['member'])
        for row in group['directories'] + group['files']:
            utility().member_name(row['member'])
            need(row['member'] not in seen, 'DUPLICATE_ARCHIVE_MEMBER'); seen.add(row['member'])
        group['bytes'] = sum(row['bytes'] for row in group['files'])
    return groups


def check_directories(value):
    for row in value['directories']:
        path = safe_source(row['path'])
        need(fingerprint(path.lstat()) == row['fingerprint'], 'SOURCE_DIRECTORY_CHANGED')
        with os.scandir(path) as scan:
            need(sorted(entry.name for entry in scan) == row['children'], 'SOURCE_MEMBERSHIP_CHANGED')


class NativeReader:
    def __init__(self, owner, handle):
        self.owner, self.handle, self.checksum, self.bytes = owner, handle, hashlib.sha256(), 0

    def read(self, size):
        if self.owner.windows:
            buffer = ctypes.create_string_buffer(size); copied = ctypes.c_ulong()
            need(self.owner.api.ReadFile(self.handle, buffer, size, ctypes.byref(copied), None), 'SOURCE_NATIVE_READ_FAILED')
            raw = buffer.raw[:copied.value]
        else:
            raw = os.read(self.handle, size)
        self.checksum.update(raw); self.bytes += len(raw)
        return raw


class HeldSources:
    """Win32 handles avoid the CRT fd ceiling and hold ShareMode=0 for every file."""
    def __init__(self, value):
        self.value, self.handles, self.windows = value, {}, os.name == 'nt'

    def __enter__(self):
        if self.windows:
            from ctypes import wintypes as w
            self.api = ctypes.WinDLL('kernel32', use_last_error=True)
            self.api.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
            self.api.CreateFileW.restype = w.HANDLE
            self.api.ReadFile.argtypes = [w.HANDLE, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID]
            self.api.CloseHandle.argtypes = [w.HANDLE]
            class Info(ctypes.Structure):
                _fields_ = [('attributes', w.DWORD), ('created', w.FILETIME), ('accessed', w.FILETIME), ('written', w.FILETIME),
                            ('volume', w.DWORD), ('sizeHigh', w.DWORD), ('sizeLow', w.DWORD), ('links', w.DWORD),
                            ('indexHigh', w.DWORD), ('indexLow', w.DWORD)]
            self.info_type = Info
            self.api.GetFileInformationByHandle.argtypes = [w.HANDLE, ctypes.POINTER(Info)]
        try:
            for row in self.value['members']:
                path = safe_source(row['path'])
                need(fingerprint(path.lstat()) == row['fingerprint'], 'SOURCE_NTFS_ID_OR_METADATA_CHANGED')
                if self.windows:
                    handle = self.api.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x00200000, None)
                    need(handle not in (None, ctypes.c_void_p(-1).value), 'ACTIVE_SOURCE_OWNER_OR_ACCESS_BLOCKED')
                else:
                    import fcntl
                    handle = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BaseException:
                        os.close(handle); raise ColdError('ACTIVE_SOURCE_OWNER_OR_ACCESS_BLOCKED')
                self.handles[row['path']] = handle
                self.verify_one(row)
            return self
        except BaseException:
            self.__exit__(None, None, None); raise

    def verify_one(self, row):
        handle = self.handles[row['path']]; expected = row['fingerprint']
        if self.windows:
            info = self.info_type()
            need(self.api.GetFileInformationByHandle(handle, ctypes.byref(info)), 'SOURCE_HANDLE_ID_UNAVAILABLE')
            def stamp(value):
                return (((value.dwHighDateTime << 32) | value.dwLowDateTime) - 116444736000000000) * 100
            actual = [info.volume, (info.indexHigh << 32) | info.indexLow, (info.sizeHigh << 32) | info.sizeLow,
                      stamp(info.written), stamp(info.created), info.links, info.attributes]
            need(actual == [expected[i] for i in (0, 1, 2, 3, 4, 5, 7)] and not info.attributes & 0x400,
                 'SOURCE_NATIVE_HANDLE_CHANGED')
        else:
            need(fingerprint(os.fstat(handle))[:7] == expected[:7], 'SOURCE_NATIVE_HANDLE_CHANGED')

    def verify(self):
        for row in self.value['members']:
            self.verify_one(row)

    def reader(self, name):
        return NativeReader(self, self.handles[name])

    def __exit__(self, *unused):
        failed = False
        for handle in self.handles.values():
            if self.windows:
                failed = not bool(self.api.CloseHandle(handle)) or failed
            else:
                os.close(handle)
        self.handles.clear()
        need(not failed, 'SOURCE_HANDLE_RELEASE_FAILED')


def pack(inventory_file, output):
    base = utility(); value = inventory(inventory_file); groups = layout(value)
    output = base.safe(output, exists=False)
    need(output.is_relative_to(ROOT / 'work') and len(output.relative_to(ROOT / 'work').parts) >= 2
         and re.fullmatch(r'data-migration-[A-Za-z0-9_.-]+', output.relative_to(ROOT / 'work').parts[0])
         and not output.exists(), 'FRESH_PRIVATE_PACK_DESTINATION_REQUIRED')
    need(shutil.disk_usage(output.parent).free >= FLOOR + ORIGINAL_BYTES + ORIGINAL_BYTES // 1000 + MAX_JSON * 2,
         'LOCAL_PACK_WORST_CASE_SPACE_REQUIRED')
    check_directories(value)
    # Read original ACLs before taking exclusive handles; no second fopen/hash of
    # a held file occurs. The reviewed mode/file ID and all byte hashes stay fixed.
    permissions = {row['path']: base.permissions(safe_source(row['path'])) for row in value['members']}
    base.private_directory(output)
    archive = output / 'originals.tar.gz'
    try:
        with HeldSources(value) as held:
            check_directories(value)
            with archive.open('xb') as raw:
                os.chmod(archive, 0o600)
                with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as compressed:
                    with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as tar:
                        tar.copybufsize = 1024 * 1024
                        for group in groups.values():
                            for row in group['directories']:
                                entry = tarfile.TarInfo(row['member']); entry.type = tarfile.DIRTYPE; entry.mode = 0o700
                                tar.addfile(entry)
                            for row in group['files']:
                                entry = tarfile.TarInfo(row['member']); entry.size = row['bytes']; entry.mode = 0o600
                                stream = held.reader(row['source']); tar.addfile(entry, stream)
                                need(stream.bytes == row['bytes'] and stream.checksum.hexdigest() == row['sha256'], 'SOURCE_BYTES_CHANGED')
                                need(shutil.disk_usage(output).free >= FLOOR, 'LOCAL_PACK_RESERVE_REACHED')
                raw.flush(); os.fsync(raw.fileno())
            held.verify(); check_directories(value)
        need(0 < archive.stat().st_size <= MAX_ARCHIVE, 'COLD_ARCHIVE_BOUND_EXCEEDED')
        (output / 'inventory.json').write_bytes(Path(inventory_file).read_bytes()); os.chmod(output / 'inventory.json', 0o600)
        need(digest(output / 'inventory.json') == INVENTORY_SHA256, 'SOURCE_INVENTORY_DRIFT')
        manifest = {'version': 1, 'kind': KIND, 'profile': PROFILE, 'status': 'COMPLETE',
                    'inventorySha256': INVENTORY_SHA256, 'files': FILES, 'bytes': ORIGINAL_BYTES,
                    'roots': TREE_ROOTS, 'groups': len(groups), 'archiveEncoding': 'TAR_GZIP',
                    'archiveBytes': archive.stat().st_size, 'archiveSha256': digest(archive),
                    'heldAllSourcesExclusive': True, 'sourceDirectoriesVerified': SOURCE_DIRECTORIES,
                    'packedAtUtc': dt.datetime.now(dt.timezone.utc).isoformat(), 'permissions': permissions}
        need(len(encoded(manifest)) <= MAX_JSON, 'COLD_PRIVATE_MANIFEST_BOUND')
        private_json(output / 'custody.json', manifest)
        return {'status': 'PACKED', 'inventorySha256': INVENTORY_SHA256, 'files': FILES, 'bytes': ORIGINAL_BYTES,
                'archiveBytes': manifest['archiveBytes'], 'archiveSha256': manifest['archiveSha256'],
                'manifestBytes': (output / 'custody.json').stat().st_size, 'manifestSha256': digest(output / 'custody.json')}
    except BaseException as error:
        private_json(output / 'pack-failed.json', {'status': 'FAILED', 'errorType': type(error).__name__, 'sourceFilesDeleted': 0})
        raise


def validate_manifest(manifest, value):
    expected = {'version', 'kind', 'profile', 'status', 'inventorySha256', 'files', 'bytes', 'roots', 'groups',
                'archiveEncoding', 'archiveBytes', 'archiveSha256', 'heldAllSourcesExclusive',
                'sourceDirectoriesVerified', 'packedAtUtc', 'permissions'}
    need(set(manifest) == expected and type(manifest['version']) is int and manifest['version'] == 1 and manifest['kind'] == KIND
         and manifest['profile'] == PROFILE and manifest['status'] == 'COMPLETE'
         and manifest['inventorySha256'] == INVENTORY_SHA256 and manifest['files'] == FILES
         and manifest['bytes'] == ORIGINAL_BYTES and manifest['roots'] == TREE_ROOTS
         and manifest['groups'] == group_count() and manifest['archiveEncoding'] == 'TAR_GZIP'
         and manifest['heldAllSourcesExclusive'] is True and manifest['sourceDirectoriesVerified'] == SOURCE_DIRECTORIES
         and type(manifest['archiveBytes']) is int and 0 < manifest['archiveBytes'] <= MAX_ARCHIVE
         and SHA.fullmatch(manifest['archiveSha256']) and set(manifest['permissions']) == {row['path'] for row in value['members']},
         'COLD_MANIFEST_NOT_COMPLETE')
    permission_fields = {'mode', 'uid', 'gid', 'atimeNs', 'mtimeNs'}
    for metadata in manifest['permissions'].values():
        need(isinstance(metadata, dict) and permission_fields <= set(metadata) <= permission_fields | {'windowsSddl'}
             and all(type(metadata[key]) is int and metadata[key] >= 0 for key in permission_fields)
             and metadata['mode'] <= 0o7777
             and ('windowsSddl' not in metadata or isinstance(metadata['windowsSddl'], str)
                  and 0 < len(metadata['windowsSddl']) <= 16384), 'COLD_ORIGINAL_PERMISSION_METADATA_INVALID')
    return layout(value)


def available(path):
    info = os.statvfs(path)
    return info.f_bavail * info.f_frsize


def budget(groups, inputs, block):
    need(type(block) is int and 512 <= block <= 1024 ** 2, 'MEASURED_FILESYSTEM_BLOCK_REQUIRED')
    rounded = lambda n: ((n + block - 1) // block) * block
    amounts = {key: sum(rounded(row['bytes']) for row in group['files']) + len(group['directories']) * block
               for key, group in groups.items()}
    copied = sum(rounded(row['bytes']) for row in inputs.values())
    return {'inputAllocationBoundBytes': copied, 'largestRestoreAllocationBytes': max(amounts.values()),
            'restoreAllocationByGroup': amounts, 'filesystemBlockBytes': block, 'reserveBytes': FLOOR,
            'evidenceBoundBytes': MAX_JSON, 'requiredAvailableBytes': copied + max(amounts.values()) + FLOOR + MAX_JSON}


def resource(path, additional=0):
    free = available(path)
    memory = next((int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()
                   if line.startswith('MemAvailable:')), 0)
    need(free >= FLOOR + additional, 'COLD_SPACE_REQUIRED_%s_FREE_%s' % (FLOOR + additional, free))
    need(memory >= 1024 ** 3, 'COLD_MEMORY_RESERVE_REACHED')


def fixed_modules(args):
    root = bootstrap_path(args.root)
    checkout = bootstrap_path(root / 'verification' / args.tag / 'checkout')
    need(ROOT == checkout and TAG.fullmatch(args.tag) and re.fullmatch(r'[a-f0-9]{40}', args.commit)
         and args.tag.endswith('-' + args.commit[:12]) and SHA.fullmatch(args.source_sha256), 'FIXED_COLD_SOURCE_REQUIRED')
    source = bootstrap_path(root / 'inbox' / args.tag / 'source.tar.gz')
    need(source.stat().st_size <= 128 * 1024 ** 2 and digest(source) == args.source_sha256, 'FIXED_SOURCE_ARCHIVE_CHANGED')
    wanted = {'script/jenkins/' + name: SELF.with_name(name) for name in (SELF.name, UTIL_NAME, 'verify-remote.py', 'cleanup-ecs-builds.py')}
    seen = set()
    with gzip.open(source, 'rb') as expanded:
        with tarfile.open(fileobj=LimitedReader(expanded, 512 * 1024 ** 2), mode='r|') as archive:
            for entry in archive:
                if entry.name not in wanted: continue
                need(entry.isfile() and entry.name not in seen and 0 < entry.size <= 1024 ** 2
                     and sha(archive.extractfile(entry).read(1024 ** 2 + 1)) == digest(bootstrap_path(wanted[entry.name])), 'FIXED_COLD_RECIPE_CHANGED')
                seen.add(entry.name)
            need(archive.pax_headers.get('comment') == args.commit and seen == set(wanted), 'FIXED_COLD_CLOSURE_INCOMPLETE')
    need(digest(source) == args.source_sha256, 'FIXED_SOURCE_CHANGED_DURING_COLD_ADMISSION')
    return utility(), load('verify-remote.py'), load('cleanup-ecs-builds.py'), checkout


def stopped_receipt(root, tag, observed, verifier, cleanup, *, current=False):
    path = root / 'verification' / tag / 'verification-receipt.json'
    record = read(utility().owner_path(path), private=True)
    request = argparse.Namespace(tag=tag, attempt=record.get('attempt'), commit=record.get('commit'),
        source_sha256=record.get('sourceSha256'), scope=record.get('scope'),
        instance_id=observed['instanceId'], machine_id=observed['machineId'])
    verifier.validate_request(request); catalog = verifier.validate_envelope(record, request)
    need(record.get('status') == 'PASS' and record.get('verificationExitCode') == 0 and record.get('finishedAt')
         and record.get('identity') == observed and not record.get('evidenceOmissions'), 'COLD_REQUIRES_ACTUAL_TERMINAL_PASS')
    checkout = path.parent / 'checkout'
    for name, row in catalog.items():
        file = checkout / ('driver.log' if name == 'driver.log' else 'work/ci-evidence/' + name[len('reports/'):])
        cleanup.owned_chain(file, root, maximum=verifier.MAX_FILE_BYTES)
        need(file.stat().st_size == row['bytes'] and digest(file) == row['sha256'], 'ORIGINAL_PASS_REPORT_DRIFT')
    need('reports/tool-runtime.json' in catalog and 'reports/receipt.json' in catalog
         and any(name.endswith('.xml') for name in catalog), 'COLD_RAW_REPORTS_REQUIRED')
    inner = read(checkout / 'work/ci-evidence/receipt.json')
    need(inner.get('status') == 'PASS' and inner.get('scopeKind') == record.get('scope')
         and inner.get('identity') == observed and inner.get('finishedAt')
         and isinstance(inner.get('commands'), list) and inner['commands']
         and all(row.get('finishedAt') and row.get('exitCode') == 0 for row in inner['commands']),
         'COLD_EXECUTED_COMMANDS_NOT_FINISHED')
    manifest_file = root / 'inbox' / tag / 'tool-runtime/manifest.json'
    manifest = read(manifest_file, private=True); tools = read(checkout / 'work/ci-evidence/tool-runtime.json', private=True)
    ms = digest(manifest_file)
    need(record['toolRuntime']['manifestSha256'] == ms and record['toolRuntime']['cleanupStatus'] == 'STOPPED'
         and tools.get('manifestSha256') == ms and tools.get('cleanup', {}).get('status') == 'STOPPED'
         and tools['cleanup'].get('remaining') == [] and tools['cleanup'].get('manifestSha256') == ms
         and manifest.get('identity') == observed and manifest.get('checkout') == str(checkout)
         and re.fullmatch(r'[a-f0-9]{24}', manifest.get('token', ''))
         and all(manifest.get(k) == tools.get(k) == record[k] for k in ('release', 'commit', 'sourceSha256')),
         'COLD_ACTUAL_TOOLS_STOPPED_REQUIRED')
    containers = cleanup.docker_snapshot()
    need(not any(row[4] == tag or row[5] == manifest['token'] for row in containers), 'COLD_OLD_TOOL_OWNER_PRESENT')
    if not current:
        cleanup.process_references(checkout)
    return record, digest(path)


def admit(args):
    base, verifier, cleanup, checkout = fixed_modules(args)
    observed = base.identity(args.expected_instance_id, args.expected_machine_id)
    root = base.safe(args.root)
    for path in (root, root / 'verification', checkout.parent, checkout, checkout / 'work'):
        base.owned_ancestor(path)
    record, record_sha = stopped_receipt(root, args.tag, observed, verifier, cleanup, current=True)
    need(record['commit'] == args.commit and record['sourceSha256'] == args.source_sha256, 'COLD_CURRENT_PASS_SOURCE_CHANGED')
    context = dict(version=1, kind=KIND, profile=PROFILE, release=args.tag, commit=args.commit,
                   sourceSha256=args.source_sha256, identity=observed, verificationReceiptSha256=record_sha,
                   inventorySha256=INVENTORY_SHA256, files=FILES, bytes=ORIGINAL_BYTES, roots=TREE_ROOTS)
    return checkout / 'work', context


def expected_inputs(args):
    result = {}
    for prefix, name, maximum in (('inventory', 'inventory.json', MAX_JSON), ('manifest', 'custody.json', MAX_JSON),
                                  ('archive', 'originals.tar.gz', MAX_ARCHIVE)):
        size, checksum = getattr(args, prefix + '_bytes'), getattr(args, prefix + '_sha256')
        need(type(size) is int and 0 < size <= maximum and isinstance(checksum, str) and SHA.fullmatch(checksum),
             'COLD_INPUT_BINDING_REQUIRED')
        result[name] = {'bytes': size, 'sha256': checksum}
    need(result['inventory.json']['sha256'] == INVENTORY_SHA256, 'COLD_FIXED_INVENTORY_REQUIRED')
    return result


def prepare(args):
    work, context = admit(args); base = utility(); inputs = expected_inputs(args)
    need(not any((work / name).exists() or (work / name).is_symlink() for name in (SNAPSHOT, RESTORE, OWNER, PUBLIC)),
         'FRESH_COLD_ATTEMPT_REQUIRED')
    block = os.statvfs(work).f_frsize
    need(512 <= block <= 1024 ** 2, 'COLD_FILESYSTEM_BLOCK_REQUIRED')
    copied = sum(((row['bytes'] + block - 1) // block) * block for row in inputs.values())
    restore_bound = LARGEST_GROUP_BYTES + LARGEST_GROUP_FILES * (block - 1) + LARGEST_GROUP_DIRECTORIES * block
    required = copied + restore_bound + MAX_JSON
    resource(work, required)
    token = uuid.uuid4().hex
    private_json(work / OWNER, {**context, 'inputs': inputs, 'token': token,
        'sourceCustodyReceiptSha256': getattr(args, 'source_receipt_sha256', None),
        'prepareBudget': {'inputAllocationBoundBytes': copied, 'maximumSingleRestoreBoundBytes': restore_bound,
                         'evidenceBoundBytes': MAX_JSON, 'reserveBytes': FLOOR,
                         'requiredAvailableBytes': required + FLOOR, 'availableBytes': available(work)}})
    base.private_directory(work / SNAPSHOT)
    for name in inputs:
        os.close(os.open(work / SNAPSHOT / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    return {**context, 'status': 'PREPARED', 'requiredAvailableBytes': required + FLOOR}


class RestoreGuard:
    """Independent Linux watchdog; only its own byte-restoration process is signalled."""
    def __init__(self, work, evidence):
        self.work, self.evidence, self.event, self.thread = work, evidence, threading.Event(), None

    def __enter__(self):
        import signal
        self.previous = signal.getsignal(signal.SIGUSR1)
        self.failure = None
        def abort(*unused):
            raise ColdError('OWNED_COLD_RESTORE_RESOURCE_ABORT')
        signal.signal(signal.SIGUSR1, abort)
        def watch():
            previous = time.monotonic()
            probe_bytes = 0
            while not self.event.is_set():
                now = time.monotonic()
                try:
                    need(now - previous <= 3, 'COLD_MONITOR_SAMPLE_LATE')
                    resource(self.work)
                    sample = {'monotonic': now, 'availableBytes': available(self.work)}
                    raw = encoded(sample) + b'\n'
                    probe_bytes += len(raw)
                    need(HAS_REPORTS or probe_bytes <= PROBE_EVIDENCE_MAX, 'HISTORY_PROBE_EVIDENCE_BOUND')
                    with (self.evidence / 'resource-probes.jsonl').open('ab') as output:
                        output.write(raw)
                    os.chmod(self.evidence / 'resource-probes.jsonl', 0o600)
                except BaseException as error:
                    self.failure = type(error).__name__
                    try:
                        private_json(self.evidence / 'resource-abort.json', {'status': 'ABORTED_OWNED_PROCESS_ONLY', 'errorType': self.failure})
                    finally:
                        os.kill(os.getpid(), signal.SIGUSR1)
                    return
                previous = now
                self.event.wait(1)
        self.thread = threading.Thread(target=watch, name='cold-restore-reserve', daemon=True); self.thread.start()
        return self

    def __exit__(self, *unused):
        import signal
        self.event.set(); self.thread.join(timeout=3)
        signal.signal(signal.SIGUSR1, self.previous)
        need(not self.thread.is_alive() and self.failure is None, 'COLD_MONITOR_NOT_CLOSED')


def restored_tree(path):
    base = utility(); base.owner_path(path, directory=True)
    files = {}; directories = {''}
    for current, dirs, names in os.walk(path, followlinks=False):
        for name in dirs:
            entry = base.owner_path(Path(current) / name, directory=True)
            directories.add(entry.relative_to(path).as_posix())
        for name in names:
            entry = base.owner_path(Path(current) / name)
            files[entry.relative_to(path).as_posix()] = {'bytes': entry.stat().st_size, 'sha256': digest(entry)}
    return files, directories


def remove_verified_temporary(path, parent, token, expected):
    """Only this attempt's restored, already receipted copy has a deletion API."""
    base = utility(); parent = base.owner_path(parent, directory=True); path = base.owner_path(path, directory=True)
    need(path.parent == parent and path.name == 'temporary-' + token, 'TEMPORARY_RESTORE_OWNER_REQUIRED')
    files, directories = restored_tree(path)
    need(files == expected['files'] and directories == expected['directories'], 'TEMPORARY_RESTORE_CHANGED_BEFORE_CLEANUP')
    shutil.rmtree(path)
    need(not path.exists(), 'TEMPORARY_RESTORE_CLEANUP_UNKNOWN')


def restore_all(snapshot, output, value, manifest, owner, context):
    groups = validate_manifest(manifest, value); base = utility()
    for prefix, group in groups.items():
        need(group['bytes'] <= LARGEST_GROUP_BYTES and len(group['files']) <= LARGEST_GROUP_FILES
             and len(group['directories']) <= LARGEST_GROUP_DIRECTORIES, 'PINNED_GROUP_RESOURCE_BOUND_CHANGED')
    block = os.statvfs(output).f_frsize
    plan = budget(groups, owner['inputs'], block)
    resource(output, plan['largestRestoreAllocationBytes'] + MAX_JSON)
    evidence_bytes = 0
    def save_evidence(path, record):
        nonlocal evidence_bytes
        evidence_bytes += len(encoded(record))
        need(HAS_REPORTS or evidence_bytes <= ROOT_EVIDENCE_MAX, 'HISTORY_ROOT_EVIDENCE_BOUND')
        private_json(path, record)
    save_evidence(output / 'resource-plan.json', plan)
    order = list(groups); completed = []; seen = set(); current = None; temporary = None
    expected_entries = {row['member']: ('FILE', row) for group in groups.values() for row in group['files']}
    expected_entries.update({row['member']: ('DIRECTORY', row) for group in groups.values() for row in group['directories']})
    total = 0
    def finish(key):
        group = groups[key]
        files, directories = restored_tree(temporary)
        expected_files = {row['member'][len(key) + 1:]: {'bytes': row['bytes'], 'sha256': row['sha256']} for row in group['files']}
        expected_dirs = {row['member'][len(key):].lstrip('/') for row in group['directories']}
        need(files == expected_files and directories == expected_dirs, 'FULL_INDEPENDENT_ROOT_READBACK_DIFFERS')
        proof = {**context, 'status': 'ROOT_RESTORED_VERIFIED', 'group': key,
                 'files': len(files), 'bytes': group['bytes'], 'directories': len(directories),
                 'memberCatalogueSha256': sha(encoded(files)), 'directoryCatalogueSha256': sha(encoded(sorted(directories))),
                 'archiveSha256': manifest['archiveSha256'], 'ownerToken': owner['token']}
        receipt_file = output / (key + '-restore.json'); save_evidence(receipt_file, proof)
        # The proof is fsynced before removing the new, never-published restore copy.
        remove_verified_temporary(temporary, output, owner['token'], {'files': files, 'directories': directories})
        cleanup_file = output / (key + '-temporary-cleanup.json')
        save_evidence(cleanup_file, {'status': 'REMOVED_OWNED_VERIFIED_RESTORE', 'group': key,
                     'ownerToken': owner['token'], 'restoreReceiptSha256': digest(receipt_file)})
        completed.append({'group': key, 'files': len(files), 'bytes': group['bytes'],
                          'restoreReceiptSha256': digest(receipt_file), 'temporaryCleanupSha256': digest(cleanup_file)})
    class BoundedInfo(tarfile.TarInfo):
        @staticmethod
        def checked_header(entry):
            need(entry.type in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE, tarfile.XHDTYPE)
                 and 0 <= entry.size <= (ORIGINAL_BYTES if entry.isfile() else 65536), 'COLD_FOREIGN_TAR_HEADER')
            return entry
        @classmethod
        def frombuf(cls, raw, encoding, errors):
            return cls.checked_header(super().frombuf(raw, encoding, errors))
        def _proc_member(self, archive):
            # Streaming tarfile also bypasses public frombuf on newer Python.
            self.checked_header(self)
            return super()._proc_member(archive)
        def _proc_gnusparse_00(self, *unused):
            raise ColdError('COLD_SPARSE_TAR_HEADER')
        _proc_gnusparse_01 = _proc_gnusparse_00
        _proc_gnusparse_10 = _proc_gnusparse_00
    expansion_limit = ORIGINAL_BYTES + len(expected_entries) * 4096 + 2 * 1024 ** 2
    with RestoreGuard(snapshot.parent, output):
        with gzip.open(snapshot / 'originals.tar.gz', 'rb') as compressed:
            expanded = LimitedReader(compressed, expansion_limit, lambda: resource(output))
            with tarfile.open(fileobj=expanded, mode='r|', tarinfo=BoundedInfo, ignore_zeros=True) as archive:
                for entry in archive:
                    name = base.member_name(entry.name)
                    need(name in expected_entries and name not in seen and not entry.sparse
                         and set(entry.pax_headers) <= {'path'}, 'COLD_EXTRA_OR_REPEATED_TAR_MEMBER')
                    key = name.split('/')[0]
                    if key != current:
                        if current is not None: finish(current)
                        need(len(completed) < len(order) and key == order[len(completed)], 'COLD_GROUP_ORDER_OR_REPLAY')
                        current = key; temporary = output / ('temporary-' + owner['token'])
                        need(not temporary.exists(), 'FRESH_TEMPORARY_RESTORE_REQUIRED'); base.private_directory(temporary)
                    kind, row = expected_entries[name]
                    relative = name[len(key):].lstrip('/')
                    target = temporary / relative
                    if kind == 'DIRECTORY':
                        need(entry.isdir() and entry.size == 0, 'COLD_DIRECTORY_TYPE_CHANGED')
                        if relative:
                            base.safe(target, exists=False).mkdir(mode=0o700)
                    else:
                        need(entry.isfile() and entry.size == row['bytes'], 'COLD_FILE_TYPE_OR_SIZE_CHANGED')
                        base.owner_path(target.parent, directory=True); checksum = hashlib.sha256(); copied = 0
                        with archive.extractfile(entry) as source, os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as destination:
                            for block in iter(lambda: source.read(1024 ** 2), b''):
                                copied += len(block); total += len(block)
                                need(copied <= row['bytes'] and total <= ORIGINAL_BYTES, 'COLD_ORIGINAL_BYTE_BOUND')
                                checksum.update(block); destination.write(block); resource(output)
                            destination.flush(); os.fsync(destination.fileno())
                        need(copied == row['bytes'] and checksum.hexdigest() == row['sha256'], 'COLD_RESTORED_MEMBER_SHA_DIFFERS')
                    seen.add(name)
            # Finish reading through the actual gzip footer/CRC after all tar padding.
            while expanded.read(1024 ** 2): pass
        need(current is not None, 'EMPTY_COLD_ARCHIVE'); finish(current)
    need(seen == set(expected_entries) and total == ORIGINAL_BYTES and len(completed) == len(groups), 'COLD_ARCHIVE_OMITTED_ORIGINALS')
    return completed, plan


def verify_restore(args):
    work, context = admit(args); base = utility(); inputs = expected_inputs(args)
    owner = read(base.owner_path(work / OWNER), private=True)
    need(all(owner.get(key) == val for key, val in context.items()) and owner.get('inputs') == inputs
         and re.fullmatch(r'[a-f0-9]{32}', owner.get('token', '')), 'COLD_OWNER_BINDING_DRIFT')
    snapshot = base.owner_path(work / SNAPSHOT, directory=True)
    need({p.name for p in snapshot.iterdir()} == set(inputs), 'COLD_SNAPSHOT_MEMBER_SET_CHANGED')
    for name, row in inputs.items():
        file = base.owner_path(snapshot / name)
        need(file.stat().st_size == row['bytes'] and digest(file) == row['sha256'], 'COLD_UPLOADED_BYTES_CHANGED')
    value = inventory(snapshot / 'inventory.json'); manifest = read(snapshot / 'custody.json', private=True)
    validate_manifest(manifest, value)
    need(manifest['archiveSha256'] == args.archive_sha256 and manifest['archiveBytes'] == args.archive_bytes, 'COLD_MANIFEST_ARCHIVE_DRIFT')
    output = base.safe(work / RESTORE, exists=False)
    need(not output.exists() and not (work / PUBLIC).exists(), 'FRESH_COLD_RESTORE_EVIDENCE_REQUIRED')
    base.private_directory(output)
    try:
        completed, plan = restore_all(snapshot, output, value, manifest, owner, context)
        need(all(digest(snapshot / name) == row['sha256'] for name, row in inputs.items()), 'RETAINED_COLD_ORIGINALS_CHANGED')
        resource(work)
        restored = {**context, 'status': 'RESTORED_VERIFIED', 'manifestSha256': args.manifest_sha256,
            'archiveSha256': args.archive_sha256, 'archiveBytes': args.archive_bytes,
            'sourceCustodyReceiptSha256': owner.get('sourceCustodyReceiptSha256'), 'restoredRoots': len(completed),
            'originalFilesDeleted': 0, 'databasesOpened': 0, 'temporaryRestoresRemoved': len(completed)}
        receipt = {**restored, 'groups': completed,
                   'resourcePlanSha256': digest(output / 'resource-plan.json'), 'ownerToken': owner['token']}
        need(HAS_REPORTS or len(encoded(receipt)) <= FINAL_EVIDENCE_MAX, 'HISTORY_FINAL_EVIDENCE_BOUND')
        private_json(output / 'restore-receipt.json', receipt)
        public = {**restored, 'restoreReceiptSha256': digest(output / 'restore-receipt.json')}
        need(set(public) == set(PUBLIC_FIELDS), 'COLD_PUBLIC_FIELDS_CHANGED')
        need(HAS_REPORTS or len(encoded(public)) <= 16384, 'HISTORY_PUBLIC_EVIDENCE_BOUND')
        private_json(work / PUBLIC, public)
        return {**public, 'publicReceiptSha256': digest(work / PUBLIC)}
    except BaseException as error:
        private_json(output / 'restore-failed.json', {'status': 'FAILED', 'errorType': type(error).__name__, 'originalFilesDeleted': 0})
        raise


def original_snapshot(args):
    work, context = admit(args); base, verifier, cleanup, _ = fixed_modules(args)
    root = base.safe(args.root); old = base.safe(args.source_snapshot_directory)
    relative = old.relative_to(root / 'verification')
    need(len(relative.parts) == 4 and TAG.fullmatch(relative.parts[0]) and relative.parts[1:] == ('checkout', 'work', SNAPSHOT)
         and int(TAG.fullmatch(relative.parts[0])[1]) < int(TAG.fullmatch(args.tag)[1]), 'COLD_REUSE_EXACT_OLDER_SNAPSHOT_REQUIRED')
    for path in (old.parent, old.parent.parent, old.parent.parent.parent): base.owned_ancestor(path)
    base.owner_path(old, directory=True)
    public_file = base.owner_path(old.parent / PUBLIC); public = read(public_file, private=True)
    record, record_sha = stopped_receipt(root, relative.parts[0], context['identity'], verifier, cleanup)
    need(set(public) == set(PUBLIC_FIELDS) and public.get('status') == 'RESTORED_VERIFIED'
         and public.get('kind') == KIND and public.get('profile') == PROFILE and public.get('inventorySha256') == INVENTORY_SHA256
         and public.get('files') == FILES and public.get('bytes') == ORIGINAL_BYTES and public.get('roots') == TREE_ROOTS
         and public.get('restoredRoots') == group_count() and public.get('temporaryRestoresRemoved') == group_count()
         and public.get('originalFilesDeleted') == public.get('databasesOpened') == 0
         and public.get('verificationReceiptSha256') == record_sha
         and all(public.get(key) == record[key] for key in ('release', 'commit', 'sourceSha256', 'identity')), 'COLD_OLD_CUSTODY_NOT_PROVED')
    need({p.name for p in old.iterdir()} == {'inventory.json', 'custody.json', 'originals.tar.gz'}, 'COLD_OLD_SNAPSHOT_SET_DRIFT')
    for name in ('inventory.json', 'custody.json', 'originals.tar.gz'): base.owner_path(old / name)
    value = inventory(old / 'inventory.json'); manifest = read(old / 'custody.json', private=True); validate_manifest(manifest, value)
    need(digest(old / 'custody.json') == public['manifestSha256'] and digest(old / 'originals.tar.gz') == public['archiveSha256']
         and manifest['archiveSha256'] == public['archiveSha256'] and manifest['archiveBytes'] == public['archiveBytes']
         and (old / 'originals.tar.gz').stat().st_size == public['archiveBytes'], 'COLD_OLD_INPUT_BYTES_CHANGED')
    restore = base.owner_path(old.parent / RESTORE, directory=True)
    proof = read(base.owner_path(restore / 'restore-receipt.json'), private=True)
    need(digest(restore / 'restore-receipt.json') == public['restoreReceiptSha256']
         and all(proof.get(key) == val for key, val in public.items() if key != 'restoreReceiptSha256')
         and len(proof['groups']) == group_count(), 'COLD_OLD_ROOT_RESTORE_PROOFS_MISSING')
    need(digest(base.owner_path(restore / 'resource-plan.json')) == proof.get('resourcePlanSha256'), 'COLD_OLD_RESOURCE_PROOF_DRIFT')
    old_owner = read(base.owner_path(old.parent / OWNER), private=True)
    expected_groups = layout(value)
    need(old_owner.get('token') == proof.get('ownerToken')
         and all(old_owner.get(key) == public[key] for key in ('release', 'commit', 'sourceSha256', 'identity'))
         and {row.get('group') for row in proof['groups']} == set(expected_groups), 'COLD_OLD_OWNER_OR_GROUP_SET_DRIFT')
    for group in proof['groups']:
        key = group['group']; expected = expected_groups[key]
        proof_file = base.owner_path(restore / (key + '-restore.json'))
        cleanup_file = base.owner_path(restore / (key + '-temporary-cleanup.json'))
        root_proof = read(proof_file, private=True); removed = read(cleanup_file, private=True)
        expected_files = {row['member'][len(key) + 1:]: {'bytes': row['bytes'], 'sha256': row['sha256']} for row in expected['files']}
        expected_dirs = {row['member'][len(key):].lstrip('/') for row in expected['directories']}
        need(digest(proof_file) == group['restoreReceiptSha256'] and digest(cleanup_file) == group['temporaryCleanupSha256']
             and root_proof.get('status') == 'ROOT_RESTORED_VERIFIED' and root_proof.get('group') == key
             and root_proof.get('files') == len(expected_files) and root_proof.get('bytes') == expected['bytes']
             and root_proof.get('memberCatalogueSha256') == sha(encoded(expected_files))
             and root_proof.get('directoryCatalogueSha256') == sha(encoded(sorted(expected_dirs)))
             and root_proof.get('archiveSha256') == public['archiveSha256'] and root_proof.get('ownerToken') == old_owner['token']
             and removed == {'status': 'REMOVED_OWNED_VERIFIED_RESTORE', 'group': key,
                             'ownerToken': old_owner['token'], 'restoreReceiptSha256': group['restoreReceiptSha256']},
             'COLD_OLD_INDEPENDENT_ROOT_PROOF_DRIFT')
    return work, context, old, public, digest(public_file)


def describe(args):
    _, context, old, public, checksum = original_snapshot(args)
    return {**context, 'status': 'DESCRIBED', 'manifestBytes': (old / 'custody.json').stat().st_size,
            'manifestSha256': public['manifestSha256'], 'archiveBytes': public['archiveBytes'],
            'archiveSha256': public['archiveSha256'], 'inventoryBytes': (old / 'inventory.json').stat().st_size,
            'sourceCustodyReceiptSha256': checksum}


def reuse(args):
    work, _, old, _, checksum = original_snapshot(args)
    need(getattr(args, 'source_receipt_sha256', None) == checksum, 'COLD_OLD_DESCRIPTION_CHANGED')
    inputs = expected_inputs(args)
    for name, row in inputs.items():
        need((old / name).stat().st_size == row['bytes'] and digest(old / name) == row['sha256'], 'COLD_REUSE_INPUT_BINDING_DRIFT')
    prepare(args)
    for name, row in inputs.items():
        before = utility().fingerprint((old / name).stat()); checksum = hashlib.sha256(); total = 0
        with (old / name).open('rb') as source, (work / SNAPSHOT / name).open('wb') as target:
            for block in iter(lambda: source.read(1024 ** 2), b''):
                total += len(block); need(total <= row['bytes'], 'COLD_REUSE_SOURCE_GREW')
                target.write(block); checksum.update(block); resource(work)
            target.flush(); os.fsync(target.fileno())
        need(total == row['bytes'] and checksum.hexdigest() == row['sha256']
             and utility().fingerprint((old / name).stat()) == before, 'COLD_REUSE_SOURCE_CHANGED')
    return verify_restore(args)


def retirement_plan(inventory_file, public_file, output):
    value = inventory(inventory_file); public = read(public_file)
    need(set(public) == set(PUBLIC_FIELDS) and public['status'] == 'RESTORED_VERIFIED' and public['kind'] == KIND
         and public['profile'] == PROFILE and public['inventorySha256'] == INVENTORY_SHA256
         and public['files'] == FILES and public['bytes'] == ORIGINAL_BYTES and public['restoredRoots'] == group_count(),
         'EXACT_SERVER_CUSTODY_RECEIPT_REQUIRED')
    output = utility().safe(output, exists=False)
    need(output.is_relative_to(ROOT / 'work') and len(output.relative_to(ROOT / 'work').parts) >= 3
         and re.fullmatch(r'data-migration-[A-Za-z0-9_.-]+', output.relative_to(ROOT / 'work').parts[0])
         and not output.exists() and not output.parent.exists(), 'FRESH_PRIVATE_RETIREMENT_PLAN_REQUIRED')
    utility().private_directory(output.parent)
    private_json(output, {'kind': 'doorhandle-cold-store-local-retirement-plan', 'status': 'PLAN_ONLY_NO_DELETION_AUTHORITY',
                 'inventorySha256': INVENTORY_SHA256, 'publicReceiptSha256': digest(public_file),
                 'serverReceipt': public, 'roots': value['roots'], 'members': value['members'],
                 'originalFilesDeleted': 0, 'requiresFreshNoActiveHandleProof': True,
                 'requiresFreshSourceHashesAndFileIds': True, 'requiresIndependentServerReceiptValidation': True})
    return {'status': 'PLAN_ONLY_NO_DELETION_AUTHORITY', 'files': FILES, 'bytes': ORIGINAL_BYTES,
            'planSha256': digest(output), 'originalFilesDeleted': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='action', required=True)
    p = commands.add_parser('pack'); p.add_argument('--inventory', required=True); p.add_argument('--output', required=True)
    p = commands.add_parser('retirement-plan')
    for flag in ('inventory', 'public-receipt', 'output'): p.add_argument('--' + flag, required=True)
    for action in ('prepare', 'verify-restore', 'describe', 'reuse'):
        p = commands.add_parser(action)
        for flag in ('root', 'tag', 'commit', 'source-sha256', 'expected-instance-id', 'expected-machine-id'):
            p.add_argument('--' + flag, required=True)
        if action != 'describe':
            for prefix in ('inventory', 'manifest', 'archive'):
                p.add_argument('--' + prefix + '-bytes', required=True, type=int)
                p.add_argument('--' + prefix + '-sha256', required=True)
        if action in ('describe', 'reuse'): p.add_argument('--source-snapshot-directory', required=True)
        if action == 'reuse': p.add_argument('--source-receipt-sha256', required=True)
    for command in commands.choices.values():
        command.add_argument('--profile', choices=tuple(PROFILES), default='cold-store-originals-v1')
    args = parser.parse_args()
    try:
        select_profile(args.profile)
        if args.action == 'pack': result = pack(args.inventory, args.output)
        elif args.action == 'retirement-plan': result = retirement_plan(args.inventory, args.public_receipt, args.output)
        else: result = globals()[args.action.replace('-', '_')](args)
        print(json.dumps(result)); return 0
    except Exception as error:
        print(json.dumps({'status': 'FAILED', 'errorType': type(error).__name__,
                          'code': str(error) if isinstance(error, ColdError) else 'COLD_CUSTODY_REJECTED',
                          'originalFilesDeleted': 0}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
