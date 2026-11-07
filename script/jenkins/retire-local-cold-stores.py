"""Retire only the two fixed cold inventories after authenticated live ECS proof.

The default is a metadata plan. Only --apply reaches Windows deletion APIs.
No database reader, recursive delete, shared-service stop or archive copy exists.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import importlib.util
import json
import ntpath
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import time


PROJECT_ROOT = r'D:\AI\lunwen1\DoorHandleCatch'
INSTANCE = 'i-2zeieuov2aum486jm1ek'
MACHINE = '1ebe8f77e3104ab6a49a9386e38abd20'
SELF = Path(__file__).absolute()
MAX_CONTROL = 32 * 1024 ** 2
PROOF_SECONDS = 300
REFRESH_SECONDS = 120
REFRESH_REMAINING_SECONDS = 60
DENIED = ('.git', 'work/jenkins', 'work/middlewares',
          'work/ecs-only-20261105/micro-followup/checkout')
IDENTITY = {'instanceId': INSTANCE, 'machineId': MACHINE, 'executionLocation': 'ECS'}
KEPT_HISTORY_ROOTS = {
    'tool-1675': 'work/llm-management-20261104/tools-docker-02',
    'tool-1676': 'work/llm-management-20261104/tools-docker-03',
}


class RetirementError(ValueError):
    """Public diagnostics contain authored codes, never original data or secrets."""


def need(value, code):
    if not value:
        raise RetirementError(code)


def cold_module():
    spec = importlib.util.spec_from_file_location('fixed_local_cold_retirement', SELF.with_name('preserve-cold-stores.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def checksum(raw):
    return hashlib.sha256(raw).hexdigest()


def source_path(relative):
    need(isinstance(relative, str) and relative.startswith('work/') and '\\' not in relative
         and ':' not in relative and all(part not in ('', '.', '..') for part in relative.split('/')),
         'EXACT_PROJECT_WORK_MEMBER_REQUIRED')
    need(all(not part.endswith((' ', '.')) and not re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part)
             for part in relative.split('/')), 'WINDOWS_PATH_ALIAS_REFUSED')
    lowered = relative.lower()
    need(not any(lowered == item or lowered.startswith(item + '/') for item in DENIED),
         'PROTECTED_LOCAL_SCOPE')
    path = ntpath.normpath(ntpath.join(PROJECT_ROOT, *relative.split('/')))
    need(ntpath.normcase(path).startswith(ntpath.normcase(PROJECT_ROOT) + '\\'), 'PROJECT_BOUNDARY_REQUIRED')
    return path


def canonical_control(path, *, exists=True):
    path = Path(path).absolute()
    root = Path(PROJECT_ROOT)
    need(path.is_relative_to(root) and path != root and '..' not in path.parts, 'PROJECT_CONTROL_BOUNDARY_REQUIRED')
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            info = item.lstat()
            need(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                 'CONTROL_LINK_OR_REPARSE_REFUSED')
    need(not exists or path.resolve(strict=True) == path, 'CANONICAL_CONTROL_REQUIRED')
    return path


def decode_control(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            need(key not in value, 'DUPLICATE_CONTROL_FIELD'); value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: need(False, 'NONFINITE_CONTROL_VALUE'))


def control(path):
    path = canonical_control(path); info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= MAX_CONTROL,
         'BOUNDED_UNLINKED_CONTROL_REQUIRED')
    raw = path.read_bytes()
    after = path.lstat()
    fields = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns,
                          row.st_nlink, row.st_mode, getattr(row, 'st_file_attributes', 0))
    need(len(raw) == info.st_size and fields(info) == fields(after),
         'CONTROL_CHANGED_DURING_READ')
    value = decode_control(raw)
    return value, checksum(raw)


def expected_evidence(cold, profile, current_file, custody_file):
    current, current_sha = control(current_file); public, public_sha = control(custody_file)
    need(current.get('schema') == 1 and current.get('kind') == 'doorhandle-ecs-ci'
         and current.get('status') == 'PASS' and current.get('verificationExitCode') == 0
         and current.get('finishedAt') and not current.get('evidenceOmissions')
         and current.get('identity') == IDENTITY, 'ACTUAL_CURRENT_SOURCE_PASS_REQUIRED')
    need(set(public) == set(cold.PUBLIC_FIELDS) and public.get('kind') == cold.KIND
         and public.get('profile') == profile and public.get('status') == 'RESTORED_VERIFIED'
         and public.get('identity') == IDENTITY and public.get('originalFilesDeleted') == 0
         and public.get('databasesOpened') == 0, 'EXACT_OLDER_COLD_PUBLIC_RECEIPT_REQUIRED')
    now = {key: current[key] for key in ('release', 'commit', 'sourceSha256', 'identity')}
    now['verificationReceiptSha256'] = current_sha
    old = {key: public[key] for key in cold.ATTESTATION_CUSTODY_FIELDS if key != 'publicReceiptSha256'}
    old['publicReceiptSha256'] = public_sha
    return now, old


def inventory_scope(value):
    files, directories = value['members'], value['directories']
    names = [row['path'] for row in files + directories]
    need(len(names) == len(set(name.lower() for name in names)), 'CASE_OR_FILE_DIRECTORY_ALIAS_REFUSED')
    for name in names:
        source_path(name)
    unresolved = [row['id'] for row in value['roots'] if 'UNPROVED' in row.get('kind', '')]
    return {'files': len(files), 'directories': len(directories), 'bytes': sum(row['bytes'] for row in files)}, unresolved


def selected_scope(profile, value):
    """Keep precisely the two frozen unproved tool roots; never infer ownership."""
    inventory_scope(value)
    roots = {row['id']: row for row in value['roots']}
    unproved = {key for key, row in roots.items() if 'UNPROVED' in row.get('kind', '')}
    if profile == 'cold-store-originals-v1':
        need(not unproved, 'UNEXPECTED_UNPROVED_ROOT')
        return value, {'rootIds': [], 'files': 0, 'directories': 0, 'bytes': 0}
    need(profile == 'cold-store-history-v2' and unproved == set(KEPT_HISTORY_ROOTS),
         'FIXED_HISTORY_RETAINED_ROOTS_REQUIRED')
    for key, path in KEPT_HISTORY_ROOTS.items():
        need(roots[key]['path'] == path and roots[key]['kind'] ==
             'TOOL_RECEIPT_STORE_COMPLETE_TREE_OWNERSHIP_UNPROVED', 'RETAINED_ROOT_SOURCE_DRIFT')
    def retained(row):
        scopes = row.get('scopes')
        need(type(scopes) is list and len(scopes) == 1 and scopes[0] in roots,
             'EXACT_HISTORY_ROW_SCOPE_REQUIRED')
        key = scopes[0]; prefix = roots[key]['path']
        need(row['path'] == prefix or row['path'].startswith(prefix + '/'), 'EXACT_HISTORY_ROW_SCOPE_REQUIRED')
        return key in unproved
    kept_files = [row for row in value['members'] if retained(row)]
    kept_dirs = [row for row in value['directories'] if retained(row)]
    kept = {'rootIds': sorted(unproved), 'files': len(kept_files), 'directories': len(kept_dirs),
            'bytes': sum(row['bytes'] for row in kept_files)}
    need((kept['files'], kept['directories'], kept['bytes']) == (8, 2, 117235), 'FIXED_RETAINED_COUNTS_DRIFT')
    selected = {**value, 'roots': [row for row in value['roots'] if row['id'] not in unproved],
                'members': [row for row in value['members'] if not retained(row)],
                'directories': [row for row in value['directories'] if not retained(row)]}
    return selected, kept


def make_plan(cold, profile, inventory_file, current_file=None, custody_file=None):
    cold.select_profile(profile)
    path = canonical_control(inventory_file); value = cold.inventory(path)
    counts, unresolved = inventory_scope(value)
    selected, retained = selected_scope(profile, value); selected_counts, _ = inventory_scope(selected)
    current = custody = None
    need(bool(current_file) == bool(custody_file), 'BOTH_CONTROL_RECEIPTS_REQUIRED')
    if current_file:
        current, custody = expected_evidence(cold, profile, current_file, custody_file)
    plan = {'version': 1, 'kind': 'doorhandle-fixed-cold-local-retirement', 'status': 'PLAN_ONLY',
        'projectRoot': PROJECT_ROOT, 'profile': profile, 'inventoryFile': str(path),
        'inventorySha256': cold.PROFILES[profile]['INVENTORY_SHA256'], 'counts': counts,
        'selectedCounts': selected_counts, 'retained': retained,
        'executorSha256': checksum(SELF.read_bytes()), 'coldHelperSha256': checksum(Path(cold.__file__).read_bytes()),
        'currentReceiptFile': str(canonical_control(current_file)) if current_file else None,
        'custodyReceiptFile': str(canonical_control(custody_file)) if custody_file else None,
        'current': current, 'custody': custody, 'unprovedRootIds': unresolved,
        'requiresAuthenticatedFreshSsh': True, 'originalFilesDeleted': 0}
    return plan, value


def load_plan(cold, args):
    plan, raw_sha = control(args.plan)
    need(raw_sha == args.plan_sha256, 'EXACT_REVIEWED_PLAN_SHA_REQUIRED')
    rebuilt, value = make_plan(cold, args.profile, args.inventory, args.current_receipt, args.custody_receipt)
    need(plan == rebuilt and plan['current'] is not None and plan['custody'] is not None,
         'PLAN_SOURCE_OR_CLOUD_BINDING_DRIFT')
    return plan, value


class Audit:
    def __init__(self, directory, cold):
        path = canonical_control(directory, exists=False)
        need(path.is_relative_to(Path(PROJECT_ROOT) / 'work/jenkins') and path.parent.is_dir()
             and not path.exists(), 'NEW_PRIVATE_JENKINS_AUDIT_DIRECTORY_REQUIRED')
        cold.utility().private_directory(path); self.directory = path
        self.stream = os.fdopen(os.open(path / 'audit.jsonl', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb')
        self.previous = '0' * 64; self.sequence = 0

    def record(self, event, **fields):
        self.sequence += 1
        value = {'sequence': self.sequence, 'previousSha256': self.previous, 'event': event, **fields}
        raw = encoded(value); self.stream.write(raw + b'\n'); self.stream.flush(); os.fsync(self.stream.fileno())
        self.previous = checksum(raw)

    def close(self):
        self.stream.close()


class LiveAttestor:
    def __init__(self, cold, args, *, helper_name='preserve-cold-stores.py'):
        need(helper_name in ('preserve-cold-stores.py', 'attest-fixed-originals.py'), 'FIXED_ATTESTATION_HELPER_REQUIRED')
        self.cold, self.args = cold, args
        self.helper_name = helper_name

    def fetch(self, plan, nonce):
        args = self.args; now = plan['current']; old = plan['custody']
        need(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', args.ssh_host)
             and re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', args.ssh_user)
             and 1 <= args.ssh_port <= 65535, 'EXPLICIT_SSH_DESTINATION_REQUIRED')
        remote_root = args.remote_root
        need(re.fullmatch(r'/(home|srv|opt)/[A-Za-z0-9_./-]+', remote_root)
             and '..' not in remote_root.split('/') and not remote_root.endswith('/'), 'EXACT_REMOTE_CI_ROOT_REQUIRED')
        key, known = canonical_control(args.ssh_key), canonical_control(args.known_hosts)
        for file in (key, known):
            need(file.is_file() and file.stat().st_nlink == 1, 'UNLINKED_SSH_CONTROL_REQUIRED')
        helper = remote_root + '/verification/' + now['release'] + '/checkout/script/jenkins/' + self.helper_name
        snapshot = remote_root + '/verification/' + old['release'] + '/checkout/work/' + self.cold.PROFILES[args.profile]['SNAPSHOT']
        arguments = ['python3', '-I', '-B', helper, 'fresh-retirement-attest', '--profile', args.profile,
            '--root', remote_root, '--tag', now['release'], '--commit', now['commit'], '--source-sha256', now['sourceSha256'],
            '--expected-instance-id', INSTANCE, '--expected-machine-id', MACHINE,
            '--source-snapshot-directory', snapshot, '--nonce', nonce, '--attestation-seconds', str(PROOF_SECONDS)]
        # Authenticate the fixed recipe before trusting even its identity/proof output.
        helper_sha = plan['coldHelperSha256' if self.helper_name == 'preserve-cold-stores.py' else 'attestationHelperSha256']
        remote = 'test "$(sha256sum ' + shlex.quote(helper) + ' | cut -d " " -f 1)" = ' + shlex.quote(helper_sha)
        remote += ' && ' + shlex.join(arguments)
        ssh = shutil.which('ssh.exe') or shutil.which('ssh'); need(ssh, 'EXISTING_SSH_CLIENT_REQUIRED')
        result = subprocess.run([ssh, '-F', 'NUL', '-i', str(key), '-p', str(args.ssh_port), '-o', 'BatchMode=yes',
            '-o', 'GlobalKnownHostsFile=NUL', '-o', 'IdentitiesOnly=yes', '-o', 'PermitLocalCommand=no',
            '-o', 'ClearAllForwardings=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'HostKeyAlias=doorhandle-bj', '-o', 'UserKnownHostsFile=' + str(known),
            '-o', 'ConnectTimeout=12', args.ssh_user + '@' + args.ssh_host, remote], capture_output=True, timeout=300)
        need(result.returncode == 0 and 0 < len(result.stdout) <= 16384 and len(result.stdout.splitlines()) == 1,
             'AUTHENTICATED_LIVE_SERVER_ATTESTATION_REQUIRED')
        value = decode_control(result.stdout)
        return self.cold.validate_retirement_attestation(value, profile=args.profile, nonce=nonce,
            expected_current=now, expected_custody=old)


class FreshProof:
    """Renew the same fixed custody over SSH; never extend an old proof's TTL."""
    def __init__(self, cold, plan, attestor, audit):
        self.cold, self.plan, self.attestor, self.audit = cold, plan, attestor, audit
        self.proof = self.nonce = self.started = None
        self.sequence = 0; self.used_nonces = set()

    def validate(self):
        need(0 <= time.monotonic() - self.started < PROOF_SECONDS, 'ATTESTATION_MONOTONIC_WINDOW_EXPIRED')
        self.cold.validate_retirement_attestation(self.proof, profile=self.plan['profile'], nonce=self.nonce,
            expected_current=self.plan['current'], expected_custody=self.plan['custody'])

    def ensure(self):
        due = self.proof is None
        if not due:
            remaining = (self.cold.attestation_time(self.proof['expiresAtUtc']) - self.cold.utc_now()).total_seconds()
            due = time.monotonic() - self.started >= REFRESH_SECONDS or remaining <= REFRESH_REMAINING_SECONDS
        if due:
            # Replacement is admitted independently. Any failed refresh aborts;
            # the caller never falls back to the previous response.
            nonce, started = secrets.token_hex(32), time.monotonic()
            need(nonce not in self.used_nonces, 'FRESH_CHALLENGE_NONCE_REUSE_REFUSED')
            self.used_nonces.add(nonce)
            proof = self.attestor.fetch(self.plan, nonce)
            self.cold.validate_retirement_attestation(proof, profile=self.plan['profile'], nonce=nonce,
                expected_current=self.plan['current'], expected_custody=self.plan['custody'])
            self.proof, self.nonce, self.started = proof, nonce, started
            self.sequence += 1
            self.validate()
            self.audit.record('FRESH_CUSTODY_PROOF', renewal=self.sequence, nonce=nonce, attestation=proof)
        # Includes time spent fsyncing the renewed proof. A stall cannot turn
        # an expired challenge into authority for even one deletion.
        self.validate()
        return self.proof


class WindowsBackend:
    """Held handles; read-only files alone request WRITE_ATTRIBUTES for Ex delete."""
    def __init__(self, cold, *, source_resolver=None):
        need(os.name == 'nt', 'APPLY_REQUIRES_WINDOWS')
        self.cold = cold
        need(source_resolver is None or callable(source_resolver), 'EXPLICIT_SOURCE_RESOLVER_REQUIRED')
        self.source_resolver = source_path if source_resolver is None else source_resolver
        self.custom_source_resolver = source_resolver is not None
        from ctypes import wintypes as w
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
        self.api.CreateFileW.restype = w.HANDLE
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.api.GetFinalPathNameByHandleW.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD]
        self.api.SetFileInformationByHandle.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
        class Disposition(ctypes.Structure):
            _fields_ = [('DeleteFile', ctypes.c_ubyte)]  # Win32 BOOLEAN, not BOOL/DWORD.
        class DispositionEx(ctypes.Structure):
            _fields_ = [('Flags', ctypes.c_uint32)]  # DWORD remains 4 bytes in Linux API fixtures too.
        self.disposition = Disposition
        self.disposition_ex = DispositionEx
        self.directories = {}; self.targets = set()

    def final_path(self, handle, expected):
        buffer = ctypes.create_unicode_buffer(32768)
        count = self.api.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        need(0 < count < len(buffer), 'HANDLE_FINAL_PATH_UNAVAILABLE')
        value = buffer.value
        if value.startswith('\\\\?\\'):
            value = value[4:]
        need(ntpath.normcase(ntpath.normpath(value)) == ntpath.normcase(expected), 'HANDLE_PATH_OR_VOLUME_ESCAPE')

    def active_references(self, value):
        # Raw argv stays only in PowerShell memory; report matching IDs, never argv.
        roots = [self.source_resolver(row['path']) for row in value['roots']]
        payload = __import__('base64').b64encode(encoded(roots)).decode()
        script = "$ErrorActionPreference='Stop'; $roots=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + payload + "'))|ConvertFrom-Json; $hits=@(); foreach($p in @(Get-CimInstance Win32_Process)){if($p.CommandLine){foreach($r in $roots){if($p.CommandLine.IndexOf($r,[StringComparison]::OrdinalIgnoreCase)-ge 0){$hits+=@{pid=$p.ProcessId};break}}}}; ConvertTo-Json -InputObject @($hits) -Compress"
        result = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', '-'],
            input=script.encode(), capture_output=True, timeout=90)
        need(result.returncode == 0 and len(result.stdout) <= 65536, 'LOCAL_PROCESS_REFERENCE_SCAN_UNAVAILABLE')
        need(json.loads(result.stdout.decode('utf-8-sig')) == [], 'ACTIVE_LOCAL_ROOT_REFERENCE_REFUSED')

    def tracked_sources(self):
        git = shutil.which('git'); need(git, 'TRACKED_SOURCE_PROTECTION_UNAVAILABLE')
        result = subprocess.run([git, '-C', PROJECT_ROOT, 'ls-files', '-z', '--cached'], capture_output=True, timeout=30)
        need(result.returncode == 0 and len(result.stdout) <= 32 * 1024 ** 2, 'TRACKED_SOURCE_PROTECTION_UNAVAILABLE')
        return {part.decode('utf8').replace('\\', '/').lower() for part in result.stdout.split(b'\0') if part}

    @contextmanager
    def hold(self, value):
        if any(row['fingerprint'][7] & 0x1 for row in value['members']):
            self.check_readonly_platform()
        rows = {self.source_resolver(row['path']): row for row in value['directories']}; paths = set(rows)
        for row in value['members'] + value['directories']:
            path = Path(self.source_resolver(row['path'])).parent
            while path.is_relative_to(Path(PROJECT_ROOT)):
                paths.add(str(path))
                if path == Path(PROJECT_ROOT): break
                path = path.parent
        try:
            for path in sorted(paths, key=lambda item: (item.count('\\'), item)):
                source = Path(path); info = source.lstat()
                need(stat.S_ISDIR(info.st_mode) and not source.is_symlink()
                     and not getattr(info, 'st_file_attributes', 0) & 0x400, 'DIRECTORY_LINK_OR_REPARSE_REFUSED')
                handle = self.api.CreateFileW(path, 0x80 | (0x10000 if path in rows else 0), 3, None, 3, 0x02200000, None)
                need(handle not in (None, ctypes.c_void_p(-1).value), 'DIRECTORY_ACTIVE_OR_ACCESS_REFUSED')
                self.directories[path] = handle; self.final_path(handle, path)
                if path in rows:
                    need(self.cold.fingerprint(source.lstat()) == rows[path]['fingerprint'], 'SOURCE_DIRECTORY_ID_OR_MEMBERSHIP_DRIFT')
            resolver = {'source_resolver': self.source_resolver} if self.custom_source_resolver else {}
            with self.cold.HeldSources(value, delete_access=True, **resolver) as held:
                self.held = held
                for row in value['members']: self.verify_file(row)
                yield self
        finally:
            failed = False
            for handle in self.directories.values(): failed = not bool(self.api.CloseHandle(handle)) or failed
            self.directories.clear()
            need(not failed, 'DIRECTORY_HANDLE_RELEASE_FAILED')

    def check_directories(self, value):
        self.cold.check_directories(value)

    def verify_file(self, row):
        self.held.verify_one(row)
        self.final_path(self.held.handles[row['path']], self.source_resolver(row['path']))

    def hash_file(self, row):
        reader = self.held.reader(row['path'])
        while reader.read(1024 ** 2): pass
        need(reader.bytes == row['bytes'] and reader.checksum.hexdigest() == row['sha256'], 'FRESH_SOURCE_BYTES_DIFFER')
        self.verify_file(row)

    @staticmethod
    def check_readonly_platform():
        try:
            platform = sys.getwindowsversion().platform_version
        except Exception as error:
            raise RetirementError('READONLY_DISPOSITION_PLATFORM_UNAVAILABLE') from error
        need(type(platform) is tuple and len(platform) == 3
             and all(type(part) is int and part >= 0 for part in platform), 'READONLY_DISPOSITION_PLATFORM_UNVERIFIED')
        need(platform >= (10, 0, 17763), 'READONLY_DISPOSITION_PLATFORM_UNSUPPORTED')

    def dispose(self, handle, *, readonly=False):
        need(type(readonly) is bool, 'EXPLICIT_READONLY_DISPOSITION_REQUIRED')
        value = self.disposition_ex(0x1 | 0x10) if readonly else self.disposition(1)
        need(self.api.SetFileInformationByHandle(handle, 21 if readonly else 4, ctypes.byref(value), ctypes.sizeof(value)),
             'EXACT_HANDLE_DISPOSITION_REFUSED')
        need(self.api.CloseHandle(handle), 'DISPOSITION_CLOSE_UNCONFIRMED')

    def delete_file(self, row):
        handle = self.held.handles[row['path']]
        if row['fingerprint'][7] & 0x1:
            self.dispose(handle, readonly=True)
        else:
            self.dispose(handle)
        del self.held.handles[row['path']]
        need(not Path(self.source_resolver(row['path'])).exists(), 'DELETED_PATH_RECREATED_OR_UNCONFIRMED')

    def rmdir_empty(self, row):
        path = self.source_resolver(row['path']); handle = self.directories[path]
        self.final_path(handle, path)
        observed = self.cold.fingerprint(Path(path).lstat()); original = row['fingerprint']
        # Our own file removals change parent mtime. Retain exact directory ID,
        # creation/attributes instead, and require emptiness at the kernel API.
        need([observed[i] for i in (0, 1, 4, 5, 6, 7)] == [original[i] for i in (0, 1, 4, 5, 6, 7)],
             'EMPTY_DIRECTORY_IDENTITY_CHANGED')
        with os.scandir(path) as entries: need(next(entries, None) is None, 'DIRECTORY_HAS_UNKNOWN_REMAINING_CONTENT')
        self.dispose(handle); del self.directories[path]
        need(not Path(path).exists(), 'REMOVED_DIRECTORY_RECREATED_OR_UNCONFIRMED')


def apply_owned(cold, plan, value, backend, attestor, audit):
    counts, _ = inventory_scope(value)
    value, retained = selected_scope(plan['profile'], value)
    selected_counts, unresolved = inventory_scope(value)
    need(counts == plan['counts'] and selected_counts == plan['selectedCounts'] and retained == plan['retained']
         and not unresolved, 'UNPROVED_OR_CHANGED_PROFILE_SCOPE')
    need(plan.get('current') is not None and plan.get('custody') is not None, 'CLOUD_RECEIPTS_REQUIRED')
    tracked = backend.tracked_sources()
    need(not any(row['path'].lower() in tracked for row in value['members']), 'TRACKED_SOURCE_REFUSED')
    backend.active_references(value)
    deleted = directories = file_attempts = directory_attempts = 0
    audit.record('BEGIN', profile=plan['profile'], planSha256=checksum(encoded(plan)), counts=counts)
    try:
        with backend.hold(value):
            backend.check_directories(value)
            for row in value['members']: backend.hash_file(row)
            backend.check_directories(value)
            for row in value['members']: backend.verify_file(row)
            proof = FreshProof(cold, plan, attestor, audit)
            proof.ensure(); audit.record('PREFLIGHT_COMPLETE', proofRenewal=proof.sequence)
            for row in value['members']:
                proof.ensure(); backend.verify_file(row)
                audit.record('FILE_DELETE_INTENT', path=row['path'], fingerprint=row['fingerprint'],
                             bytes=row['bytes'], sha256=row['sha256'])
                proof.ensure()
                backend.verify_file(row)
                file_attempts += 1
                backend.delete_file(row); deleted += 1
                audit.record('FILE_DELETED', path=row['path'])
            for row in sorted(value['directories'], key=lambda item: (item['path'].count('/'), item['path']), reverse=True):
                proof.ensure(); audit.record('EMPTY_DIRECTORY_INTENT', path=row['path'], fingerprint=row['fingerprint'])
                proof.ensure()
                directory_attempts += 1
                backend.rmdir_empty(row); directories += 1
                audit.record('EMPTY_DIRECTORY_REMOVED', path=row['path'])
        result = {'status': 'PARTIAL_FIXED_PROFILE_PROTECTED_ROOTS_RETAINED' if retained['rootIds'] else 'RETIRED_EXACT_FIXED_PROFILE',
                  'filesDeleted': deleted, 'directoriesRemoved': directories, 'rootsSkipped': retained['rootIds'],
                  'retained': retained, 'entireProfileRetired': not retained['rootIds'],
                  'profile': plan['profile'], 'inventorySha256': plan['inventorySha256']}
        audit.record('COMPLETED', **result); return result
    except BaseException:
        audit.record('PARTIAL_OR_REFUSED', filesDeleted=deleted, directoriesRemoved=directories,
                     fileDispositionAttempts=file_attempts, directoryDispositionAttempts=directory_attempts,
                     unconfirmedFileDispositions=file_attempts - deleted,
                     unconfirmedDirectoryDispositions=directory_attempts - directories,
                     automaticResumeAllowed=False, requiresOwnIntentReconciliation=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, choices=('cold-store-originals-v1', 'cold-store-history-v2'))
    parser.add_argument('--inventory', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--current-receipt'); parser.add_argument('--custody-receipt')
    parser.add_argument('--apply', action='store_true'); parser.add_argument('--plan'); parser.add_argument('--plan-sha256')
    parser.add_argument('--remote-root', default='/home/ecs-user/doorhandle-ci')
    parser.add_argument('--ssh-host'); parser.add_argument('--ssh-user', default='ecs-user')
    parser.add_argument('--ssh-port', type=int, default=22)
    parser.add_argument('--ssh-key', default=PROJECT_ROOT + r'\work\cloud\doorhandle-demo-20261014.pem')
    parser.add_argument('--known-hosts', default=PROJECT_ROOT + r'\work\jenkins\known_hosts')
    args = parser.parse_args(argv); audit = None
    try:
        cold = cold_module()
        if not args.apply:
            need(not args.plan and not args.plan_sha256, 'APPLY_ARGUMENTS_REQUIRE_EXPLICIT_APPLY')
            plan, _ = make_plan(cold, args.profile, args.inventory, args.current_receipt, args.custody_receipt)
            audit = Audit(args.output, cold); cold.utility().write_json(audit.directory / 'plan.json', plan)
            audit.record('PLAN_ONLY', originalFilesDeleted=0, unresolvedRootIds=plan['unprovedRootIds'])
            print(json.dumps({'status': 'PLAN_ONLY', 'planSha256': checksum((audit.directory / 'plan.json').read_bytes()),
                              'counts': plan['counts'], 'unprovedRootIds': plan['unprovedRootIds'], 'originalFilesDeleted': 0}))
            return 0
        need(bool(args.ssh_host), 'EXPLICIT_CURRENT_ECS_SSH_HOST_REQUIRED')
        need(os.name == 'nt' and args.plan and args.plan_sha256 and args.current_receipt and args.custody_receipt,
             'EXPLICIT_WINDOWS_APPLY_PLAN_AND_CLOUD_CONTROLS_REQUIRED')
        plan, value = load_plan(cold, args)
        audit = Audit(args.output, cold)
        result = apply_owned(cold, plan, value, WindowsBackend(cold), LiveAttestor(cold, args), audit)
        cold.utility().write_json(audit.directory / 'result.json', result)
        print(json.dumps(result)); return 0
    except BaseException as error:
        print(json.dumps({'status': 'REFUSED_OR_PARTIAL', 'errorType': type(error).__name__,
            'code': str(error) if isinstance(error, RetirementError) else 'FIXED_COLD_RETIREMENT_REFUSED',
            'automaticResumeAllowed': False, 'sourceScopeExpanded': False}), file=sys.stderr)
        return 1
    finally:
        if audit is not None: audit.close()


if __name__ == '__main__':
    raise SystemExit(main())
