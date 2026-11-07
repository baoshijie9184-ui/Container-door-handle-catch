"""Tighten only registered, fully authenticated, quiescent old CI evidence.

Default is a read-only plan. No report bytes, archives or business data are
rewritten; Linux descriptor-relative fchmod is the only old-tree mutation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile


SELF = Path(__file__).absolute()
REGISTRY = 'ci-evidence-permission-repairs.json'
SHA = re.compile(r'[a-f0-9]{64}')
TAG = re.compile(r'ci-[1-9][0-9]*-[a-f0-9]{12}')
MAX_JSON = 1024 * 1024
CLOSURE = (SELF.name, REGISTRY, 'preserve-cold-stores.py',
           'preserve-local-artifacts.py', 'verify-remote.py', 'cleanup-ecs-builds.py')
OLD_CLOSURE = CLOSURE[2:]


def need(value, code):
    if not value:
        raise ValueError(code)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'DUPLICATE_JSON_FIELD')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda unused: need(False, 'NONFINITE_JSON_VALUE'))


def relative(name):
    need(isinstance(name, str) and 0 < len(name) < 2048 and '\\' not in name and ':' not in name
         and '\x00' not in name and not name.startswith('/')
         and all(p not in ('', '.', '..') for p in name.split('/')), 'EXACT_RELATIVE_PATH_REQUIRED')
    return PurePosixPath(name)


def metadata(info):
    return {'device': info.st_dev, 'inode': info.st_ino, 'uid': info.st_uid,
            'gid': info.st_gid, 'mode': stat.S_IMODE(info.st_mode), 'bytes': info.st_size,
            'mtimeNs': info.st_mtime_ns, 'ctimeNs': info.st_ctime_ns, 'nlink': info.st_nlink}


class HeldTree:
    """Hold the CI root and every traversed ancestor; never follow path links."""
    def __init__(self, root, changes=()):
        self.root = Path(root)
        self.allowed = {row['path']: row for row in changes}
        self.nodes = {}

    def __enter__(self):
        need(self.root.is_absolute() and '..' not in self.root.parts
             and self.root.resolve(strict=True) == self.root, 'CANONICAL_CI_ROOT_REQUIRED')
        for path in (self.root, *self.root.parents):
            need(not path.is_symlink(), 'CI_ROOT_LINK_REFUSED')
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            need(info.st_uid == os.getuid() and not info.st_mode & 0o022, 'CI_ROOT_OWNER_OR_MODE_CHANGED')
            self.nodes[''] = {'fd': fd, 'before': metadata(info), 'directory': True}
        except BaseException:
            os.close(fd)
            raise
        return self

    def __exit__(self, *unused):
        for node in reversed(list(self.nodes.values())):
            os.close(node['fd'])
        self.nodes.clear()

    def add(self, name, *, directory=False, maximum=MAX_JSON):
        parts = relative(name).parts
        parent = ''
        for i, component in enumerate(parts):
            key = '/'.join(parts[:i + 1]); is_dir = directory or i < len(parts) - 1
            if key not in self.nodes:
                flags = os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if is_dir else os.O_NONBLOCK)
                fd = os.open(component, flags, dir_fd=self.nodes[parent]['fd'])
                try:
                    info = os.fstat(fd); change = self.allowed.get(key)
                    need(info.st_uid == os.getuid(), 'PATH_UID_CHANGED')
                    need(stat.S_ISDIR(info.st_mode) if is_dir else stat.S_ISREG(info.st_mode)
                         and info.st_nlink == 1 and info.st_size <= maximum, 'PATH_TYPE_LINK_OR_SIZE_CHANGED')
                    mode = stat.S_IMODE(info.st_mode)
                    if change:
                        need(change['directory'] is is_dir and mode in (change['beforeMode'], change['afterMode'])
                             and (not is_dir or info.st_nlink == change['nlink']), 'REGISTERED_PATH_METADATA_CHANGED')
                    else:
                        need(not info.st_mode & 0o022, 'UNREGISTERED_WRITABLE_PATH_REFUSED')
                    self.nodes[key] = {'fd': fd, 'before': metadata(info), 'directory': is_dir}
                except BaseException:
                    os.close(fd)
                    raise
            else:
                need(self.nodes[key]['directory'] is is_dir, 'PATH_TYPE_CHANGED')
            parent = key
        self.verify_one(name)
        return self.nodes[name]

    def verify_one(self, name, *, changed=False):
        node = self.nodes[name]; info = os.fstat(node['fd'])
        if name:
            parent, _, leaf = name.rpartition('/')
            actual = os.stat(leaf, dir_fd=self.nodes[parent]['fd'], follow_symlinks=False)
        else:
            actual = self.root.lstat()
        need(metadata(actual) == metadata(info), 'HELD_PATH_REPLACED')
        before, after = node['before'], metadata(info)
        stable = ('device', 'inode', 'uid', 'gid', 'bytes', 'mtimeNs', 'nlink')
        need(all(before[k] == after[k] for k in stable), 'HELD_METADATA_CHANGED')
        if changed:
            need(after['mode'] == self.allowed[name]['afterMode'], 'PRIVATE_MODE_NOT_APPLIED')
        else:
            need(before == after, 'HELD_METADATA_CHANGED')

    def verify_all(self, changed=()):
        for name in self.nodes:
            self.verify_one(name, changed=name in changed)

    def digest(self, name):
        node = self.nodes[name]; need(not node['directory'], 'HASH_DIRECTORY_REFUSED')
        value, offset = hashlib.sha256(), 0
        while True:
            raw = os.pread(node['fd'], 1024 ** 2, offset)
            if not raw: break
            value.update(raw); offset += len(raw)
            need(offset <= node['before']['bytes'], 'FILE_GREW_DURING_HASH')
        need(offset == node['before']['bytes'] == os.fstat(node['fd']).st_size, 'FILE_LENGTH_CHANGED_DURING_HASH')
        return value.hexdigest()

    def read(self, name, maximum=MAX_JSON):
        node = self.add(name, maximum=maximum)
        raw = os.pread(node['fd'], maximum + 1, 0)
        need(len(raw) <= maximum and len(raw) == os.fstat(node['fd']).st_size, 'BOUNDED_READ_CHANGED')
        return raw


class Bound:
    def __init__(self, source, limit):
        self.source, self.limit, self.total = source, limit, 0

    def read(self, size=-1):
        left = self.limit - self.total
        raw = self.source.read(left + 1 if size < 0 else min(size, left + 1))
        self.total += len(raw)
        need(self.total <= self.limit, 'ARCHIVE_EXPANSION_BOUND_REACHED')
        return raw


@contextmanager
def held_tar(tree, name, maximum):
    with os.fdopen(os.dup(tree.nodes[name]['fd']), 'rb') as raw:
        raw.seek(0)
        with gzip.GzipFile(fileobj=raw, mode='rb') as expanded:
            with tarfile.open(fileobj=Bound(expanded, maximum), mode='r|') as source:
                yield source
                for block in iter(lambda: source.fileobj.read(1024 ** 2), b''):
                    need(not block.strip(b'\0'), 'ARCHIVE_TRAILING_NONPADDING_BYTES')


def source_closure(tree, tag, commit, source_sha, names):
    archive = 'inbox/' + tag + '/source.tar.gz'
    tree.add(archive, maximum=128 * 1024 ** 2)
    need(tree.digest(archive) == source_sha, 'FIXED_SOURCE_ARCHIVE_CHANGED')
    checkout = 'verification/' + tag + '/checkout/'
    wanted = {'script/jenkins/' + name: checkout + 'script/jenkins/' + name for name in names}
    for path in wanted.values(): tree.add(path)
    seen = set()
    with held_tar(tree, archive, 512 * 1024 ** 2) as source:
        for entry in source:
            if entry.name not in wanted: continue
            need(entry.isfile() and 0 < entry.size <= MAX_JSON and entry.name not in seen,
                 'PINNED_CLOSURE_ENTRY_INVALID')
            need(sha(source.extractfile(entry).read(MAX_JSON + 1)) == tree.digest(wanted[entry.name]),
                 'PINNED_CLOSURE_BYTES_CHANGED')
            seen.add(entry.name)
        need(source.pax_headers.get('comment') == commit and seen == set(wanted), 'PINNED_CLOSURE_INCOMPLETE')
    need(tree.digest(archive) == source_sha, 'FIXED_SOURCE_CHANGED_DURING_READ')


def load(name):
    spec = importlib.util.spec_from_file_location('fixed_permission_repair_' + name.replace('.', '_'), SELF.with_name(name))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def validate_registry(value):
    need(value.get('schema') == 1 and value.get('kind') == 'doorhandle-registered-ci-permission-repairs'
         and isinstance(value.get('releases'), list) and len(value['releases']) == 1, 'FIXED_REGISTRY_SCHEMA_REQUIRED')
    entry = value['releases'][0]
    need(TAG.fullmatch(entry.get('release', '')) and re.fullmatch(r'[a-f0-9]{40}', entry.get('commit', ''))
         and entry['release'].endswith('-' + entry['commit'][:12]) and SHA.fullmatch(entry.get('sourceSha256', ''))
         and SHA.fullmatch(entry.get('verificationReceiptSha256', ''))
         and SHA.fullmatch(entry.get('toolManifestSha256', ''))
         and SHA.fullmatch(entry.get('evidenceArchiveSha256', ''))
         and type(entry.get('evidenceArchiveBytes')) is int and 0 < entry['evidenceArchiveBytes'] <= 64 * 1024 ** 2
         and re.fullmatch(r'[a-f0-9]{32}', entry.get('attempt', '')), 'REGISTERED_SOURCE_BINDING_INVALID')
    catalog = entry['reportFiles']; changes = entry['changes']; prefix = 'verification/' + entry['release'] + '/checkout/work/ci-evidence/'
    need(len(catalog) == 223 and len({row['path'] for row in catalog}) == 223 and len(changes) == 21
         and len({row['path'] for row in changes}) == 21, 'EXACT_REVIEWED_REPORT_SCOPE_REQUIRED')
    for row in catalog:
        relative(row['path'])
        need(type(row['bytes']) is int and 0 <= row['bytes'] <= 32 * 1024 ** 2 and SHA.fullmatch(row['sha256']), 'REGISTERED_REPORT_INVALID')
    for row in changes:
        relative(row['path'])
        need(row['path'].startswith(prefix) and type(row['directory']) is bool
             and type(row['nlink']) is int and row['nlink'] >= (2 if row['directory'] else 1)
             and (row['directory'] or row['nlink'] == 1)
             and (row['beforeMode'], row['afterMode']) == ((0o775, 0o700) if row['directory'] else (0o664, 0o600)),
             'REGISTERED_CHANGE_ESCAPES_REVIEWED_SCOPE')
    need(sum(row['directory'] for row in changes) == 12, 'EXACT_REVIEWED_DIRECTORY_SCOPE_REQUIRED')
    return entry


def report_path(tag, name):
    relative(name)
    need(name == 'driver.log' or name.startswith('reports/'), 'REPORT_OUTSIDE_EVIDENCE_SCOPE')
    return 'verification/' + tag + '/checkout/' + ('driver.log' if name == 'driver.log' else 'work/ci-evidence/' + name[8:])


def old_preflight(tree, entry, observed, verifier, cleanup):
    """Validate bytes before allowing the registered mode exception to be used."""
    tag = entry['release']; base = 'verification/' + tag
    need(entry['identity'] == observed, 'REGISTERED_INSTANCE_CHANGED')
    receipt_name = base + '/verification-receipt.json'
    raw = tree.read(receipt_name, verifier.MAX_RECEIPT_BYTES)
    need(tree.nodes[receipt_name]['before']['mode'] == 0o600, 'OLD_PRIVATE_RAW_RECEIPT_REQUIRED')
    need(sha(raw) == entry['verificationReceiptSha256'], 'OLD_RAW_RECEIPT_CHANGED')
    record = parse(raw); catalog = cleanup.receipt_catalog(record, verifier)
    need(all(record.get(k) == entry[k] for k in ('release', 'commit', 'sourceSha256', 'attempt', 'identity'))
         and record.get('status') == 'PASS' and record.get('verificationExitCode') == 0 and record.get('finishedAt')
         and record.get('scope') == 'source' and not record.get('evidenceOmissions')
         and record['reportFiles'] == entry['reportFiles'], 'OLD_ACTUAL_PASS_OR_CATALOG_CHANGED')
    source_closure(tree, tag, entry['commit'], entry['sourceSha256'], OLD_CLOSURE)
    for name, row in catalog.items():
        path = report_path(tag, name); node = tree.add(path, maximum=verifier.MAX_FILE_BYTES)
        need(node['before']['bytes'] == row['bytes'] and tree.digest(path) == row['sha256'], 'ORIGINAL_REPORT_BYTES_CHANGED')
    for change in entry['changes']:
        tree.add(change['path'], directory=change['directory'])
    archive = 'inbox/' + tag + '/verification-evidence.tar.gz'
    tree.add(archive, maximum=verifier.MAX_EVIDENCE_ARCHIVE); seen = set()
    need(tree.nodes[archive]['before']['bytes'] == entry['evidenceArchiveBytes']
         and tree.digest(archive) == entry['evidenceArchiveSha256'], 'ORIGINAL_ARCHIVE_BYTES_CHANGED')
    with held_tar(tree, archive, verifier.MAX_EVIDENCE_BYTES) as package:
        for item in package:
            need(item.isfile() and item.name not in seen and (item.name == 'verification-receipt.json' or item.name in catalog),
                 'ORIGINAL_ARCHIVE_MEMBER_CHANGED')
            expected = {'bytes': len(raw), 'sha256': sha(raw)} if item.name == 'verification-receipt.json' else catalog[item.name]
            need(item.size == expected['bytes'], 'ORIGINAL_ARCHIVE_MEMBER_SIZE_CHANGED')
            value = hashlib.sha256(); source = package.extractfile(item)
            for block in iter(lambda: source.read(1024 ** 2), b''): value.update(block)
            need(value.hexdigest() == expected['sha256'], 'ORIGINAL_ARCHIVE_MEMBER_SHA_CHANGED'); seen.add(item.name)
    need(seen == {'verification-receipt.json', *catalog}, 'ORIGINAL_ARCHIVE_INCOMPLETE')
    evidence = base + '/checkout/work/ci-evidence/'
    inner = parse(tree.read(evidence + 'receipt.json'))
    need(inner.get('status') == 'PASS' and inner.get('scopeKind') == 'source' and inner.get('identity') == observed
         and inner.get('finishedAt') and isinstance(inner.get('commands'), list) and inner['commands']
         and all(row.get('finishedAt') and row.get('exitCode') == 0 for row in inner['commands']), 'OLD_PRODUCER_NOT_FINISHED_PASS')
    manifest_name = 'inbox/' + tag + '/tool-runtime/manifest.json'
    manifest = parse(tree.read(manifest_name)); tools = parse(tree.read(evidence + 'tool-runtime.json'))
    need(tree.nodes[manifest_name]['before']['mode'] == 0o600
         and tree.nodes[evidence + 'tool-runtime.json']['before']['mode'] == 0o600, 'OLD_PRIVATE_TOOL_PROOFS_REQUIRED')
    manifest_sha = tree.digest(manifest_name)
    need(manifest_sha == entry['toolManifestSha256'] == record['toolRuntime']['manifestSha256']
         and manifest.get('schema') == 1 and manifest.get('kind') == 'doorhandle-ecs-tool-runtime'
         and manifest.get('directory') == str(tree.root / Path(manifest_name).parent)
         and manifest.get('identity') == observed and manifest.get('uid') == os.getuid()
         and manifest.get('checkout') == str(tree.root / base / 'checkout')
         and re.fullmatch(r'[a-f0-9]{24}', manifest.get('token', ''))
         and all(manifest.get(k) == tools.get(k) == record[k] for k in ('release', 'commit', 'sourceSha256'))
         and tools.get('kind') == 'doorhandle-ecs-tool-evidence' and tools.get('manifestSha256') == manifest_sha
         and record['toolRuntime'].get('evidenceSha256') == tree.digest(evidence + 'tool-runtime.json')
         and record['toolRuntime'].get('cleanupStatus') == 'STOPPED'
         and tools.get('cleanup', {}).get('status') == 'STOPPED' and tools['cleanup'].get('remaining') == []
         and tools['cleanup'].get('release') == tag and tools['cleanup'].get('manifestSha256') == manifest_sha,
         'OLD_TOOL_OWNER_OR_STOP_PROOF_CHANGED')
    claim_name = base + '/.verification-claimed/claim.json'
    claim = parse(tree.read(claim_name))
    need(tree.nodes[claim_name]['before']['mode'] == 0o600, 'OLD_PRIVATE_OWNER_CLAIM_REQUIRED')
    need(claim == dict(schema=1, kind='doorhandle-ci-claim', release=tag, attempt=record['attempt'], commit=record['commit'],
         sourceSha256=record['sourceSha256'], identity=observed, scope='source'), 'OLD_OWNER_CLAIM_CHANGED')
    binding = {'checkout': tree.root / base / 'checkout', 'token': manifest['token']}
    cleanup.quiescent(binding, tag, cleanup.docker_snapshot())
    tree.verify_all()
    return binding


def repair_entry(root, entry, observed, verifier, cleanup, *, apply=False, audit=None, journal=lambda event: None):
    audit = audit if audit is not None else {}
    with HeldTree(root, entry['changes']) as tree:
        binding = old_preflight(tree, entry, observed, verifier, cleanup)
        rows = []
        for change in entry['changes']:
            name = change['path']; node = tree.nodes[name]
            rows.append({'path': name, 'before': node['before'], 'after': None,
                         'sha256Before': None if change['directory'] else tree.digest(name), 'sha256After': None})
        audit.update(priorRelease=entry['release'], originalReportFiles=len(entry['reportFiles']),
                     originalReportBytesChanged=False, targets=rows, preflight='PASS', changedPaths=[])
        journal({'phase': 'PREFLIGHT', **audit})
        pending = [row['path'] for row in entry['changes'] if tree.nodes[row['path']]['before']['mode'] != row['afterMode']]
        if not apply:
            return {'status': 'PLANNED' if pending else 'NO_ACTION', 'changedPaths': pending}
        # Recheck all original bytes and quiescence immediately before the first
        # mutation. No repair is attempted when any earlier predicate failed.
        for report in entry['reportFiles']:
            need(tree.digest(report_path(entry['release'], report['path'])) == report['sha256'], 'ORIGINAL_REPORT_BYTES_CHANGED')
        cleanup.quiescent(binding, entry['release'], cleanup.docker_snapshot())
        tree.verify_all(); changed = set()
        for change, row in zip(entry['changes'], rows):
            name = change['path']; tree.verify_all(changed)
            if name in pending:
                audit['pendingIntent'] = name
                journal({'phase': 'INTENT', 'path': name, 'before': row['before'],
                         'expectedMode': change['afterMode'], 'sha256Before': row['sha256Before']})
                tree.verify_all(changed)
                os.fchmod(tree.nodes[name]['fd'], change['afterMode']); changed.add(name)
                audit['changedPaths'].append(name)
                os.fsync(tree.nodes[name]['fd'])
            row['after'] = metadata(os.fstat(tree.nodes[name]['fd']))
            tree.verify_one(name, changed=name in changed)
            if not change['directory']:
                row['sha256After'] = tree.digest(name)
                need(row['sha256Before'] == row['sha256After'], 'REPAIRED_REPORT_BYTES_CHANGED')
            journal({'phase': 'AFTER', **row, 'changed': name in changed})
            audit.pop('pendingIntent', None)
        for report in entry['reportFiles']:
            need(tree.digest(report_path(entry['release'], report['path'])) == report['sha256'], 'ORIGINAL_REPORT_BYTES_CHANGED')
        tree.verify_all(changed)
        cleanup.quiescent(binding, entry['release'], cleanup.docker_snapshot())
        return {'status': 'REPAIRED' if pending else 'NO_ACTION', 'changedPaths': pending}


def current_context(args):
    need(sys.platform == 'linux' and os.getuid() == 1000, 'ECS_EXECUTION_UID_1000_REQUIRED')
    need(TAG.fullmatch(args.tag) and re.fullmatch(r'[a-f0-9]{40}', args.commit)
         and args.tag.endswith('-' + args.commit[:12]) and SHA.fullmatch(args.source_sha256)
         and SHA.fullmatch(args.verification_receipt_sha256), 'FIXED_CURRENT_CONTEXT_REQUIRED')
    root = Path(args.root); checkout = root / 'verification' / args.tag / 'checkout'
    need(SELF == checkout / 'script/jenkins' / SELF.name and Path(args.plan) == SELF.with_name(REGISTRY),
         'FIXED_CHECKOUT_HELPER_AND_REGISTRY_REQUIRED')
    with HeldTree(root) as tree:
        source_closure(tree, args.tag, args.commit, args.source_sha256, CLOSURE)
        registry = parse(tree.read('verification/' + args.tag + '/checkout/script/jenkins/' + REGISTRY))
        entry = validate_registry(registry); tree.verify_all()
    cold = load('preserve-cold-stores.py'); base, verifier, cleanup, unused = cold.fixed_modules(args)
    observed = base.identity(args.instance_id, args.machine_id)
    record, raw_sha = cold.stopped_receipt(root, args.tag, observed, verifier, cleanup, current=True)
    need(record.get('scope') in ('source', 'mysql') and record.get('commit') == args.commit
         and record.get('sourceSha256') == args.source_sha256 and raw_sha == args.verification_receipt_sha256,
         'CURRENT_SOURCE_PASS_OR_RAW_SHA_CHANGED')
    receipt = root / 'verification' / args.tag / 'verification-receipt.json'
    need(stat.S_IMODE(receipt.lstat().st_mode) == 0o600, 'CURRENT_PRIVATE_RAW_RECEIPT_REQUIRED')
    return root, checkout, observed, verifier, cleanup, entry


def write_private(path, value):
    raw = encoded(value)
    need(len(raw) <= 2 * MAX_JSON, 'AUDIT_OUTPUT_BOUND_REACHED')
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return sha(raw)


def run(args):
    root, checkout, observed, verifier, cleanup, entry = current_context(args)
    output = Path(args.output)
    need(output.is_absolute() and output.parent == checkout / 'work' and re.fullmatch(r'[a-z0-9-]{1,80}', output.name)
         and not output.exists() and not output.is_symlink(), 'FRESH_CURRENT_PRIVATE_AUDIT_DIRECTORY_REQUIRED')
    cleanup.owned_chain(output.parent, root, directory=True)
    need(stat.S_IMODE(output.parent.stat().st_mode) == 0o700, 'CURRENT_PRIVATE_WORK_REQUIRED')
    output.mkdir(mode=0o700)
    parent_fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(parent_fd)
    finally: os.close(parent_fd)
    context = dict(release=args.tag, commit=args.commit, sourceSha256=args.source_sha256, identity=observed)
    audit = dict(schema=1, kind='doorhandle-ci-evidence-permission-repair-audit', **context,
                 currentVerificationReceiptSha256=args.verification_receipt_sha256, applyRequested=args.apply,
                 requestedPriorTags=args.prior_tag, changedPaths=[], originalReportBytesChanged=False)
    journal_path = output / 'audit.jsonl'
    with os.fdopen(os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        directory_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(directory_fd)
        finally: os.close(directory_fd)
        def journal(event):
            raw = encoded(event)
            need(stream.tell() + len(raw) <= 2 * MAX_JSON, 'JOURNAL_OUTPUT_BOUND_REACHED')
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        try:
            need(args.prior_tag and len(args.prior_tag) <= 8 and len(set(args.prior_tag)) == len(args.prior_tag)
                 and all(TAG.fullmatch(tag) and int(tag.split('-')[1]) < int(args.tag.split('-')[1])
                         for tag in args.prior_tag), 'EXPLICIT_DISTINCT_EARLIER_PRIOR_TAGS_REQUIRED')
            if entry['release'] not in args.prior_tag:
                result = dict(status='NO_ACTION', reason='UNREGISTERED_PRIOR_TAG', changedPaths=[])
            else:
                result = repair_entry(root, entry, observed, verifier, cleanup, apply=args.apply, audit=audit, journal=journal)
            audit.update(result)
            journal({'phase': 'FINISHED', 'status': result['status'], 'changedPaths': result['changedPaths']})
        except BaseException as error:
            audit.update(status='FAILED', errorType=type(error).__name__, errorCode=str(error) if isinstance(error, ValueError) else 'REPAIR_REJECTED')
            journal({'phase': 'FAILED', 'errorType': type(error).__name__, 'pendingIntent': audit.get('pendingIntent')})
            audit['journalSha256'] = sha(journal_path.read_bytes())
            write_private(output / 'audit.json', audit)
            raise
    audit['journalSha256'] = sha(journal_path.read_bytes())
    audit_sha = write_private(output / 'audit.json', audit)
    public = dict(schema=1, kind='doorhandle-ci-evidence-permission-repair', **context, **result,
                  auditSha256=audit_sha, originalReportBytesChanged=False)
    report_sha = write_private(output / 'public.json', public)
    return {**public, 'reportSha256': report_sha}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id', 'verification-receipt-sha256', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--prior-tag', action='append', required=True)
    parser.add_argument('--plan', default=str(SELF.with_name(REGISTRY)))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        result = run(args)
    except Exception as error:
        print(json.dumps({'status': 'FAILED', 'errorType': type(error).__name__,
                          'code': str(error) if isinstance(error, ValueError) else 'PERMISSION_REPAIR_REJECTED'}))
        return 2
    print(encoded(result).decode().strip())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
