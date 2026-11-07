"""Closed byte custody of the one approved 45-table local SQL export.

pack never opens a database or interprets SQL. All cloud operations require a
fixed source archive and passing ECS verification. This is not a live merge,
production activation, local deletion admission or a source row-hash proof.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
LOCAL_ROOT = Path('D:/AI/lunwen1/DoorHandleCatch')
PROFILE = 'local-mysql-export45-v1'
KIND = 'doorhandle-local-mysql-custody'
EXPORT_DIRECTORY = 'local-mysql-export-20261107T112707Z-958ab7d6'
CONTROL_DIRECTORY = 'approved-local-db-export-20261107T112702Z'
EXPORT_SHA = '0b58012469e0babb2031b54d34ed906910b75f9385d8950776776153dde3495d'
CONTROL_SHA = '96ba945cd57899daff652b9865cd0bbcee855d58555e43bc93b7bc937bcbdc34'
EXPORT_SCRIPT_SHA = '6f138fe27e14b53532deb8bf3381e80d7d11c042ec0c2ef24e02a182fa69c92c'
RAW_SHA = '6b8bce0cc4da19384d9fc4ce894946c34b9b285dd2e9a150f1211967999e2464'
GZIP_SHA = '8f0a2e9014233dc20f4e26321eb855846bda0ddb689c39d85db33133e447b627'
RAW_BYTES = 11123119
GZIP_BYTES = 1890654
MIB = 1024 ** 2
MAX_BYTES = 32 * MIB
SHA = re.compile(r'[a-f0-9]{64}')
MEMBERS = frozenset(('authorization-private.json', 'before-identity-private.json', 'after-identity-private.json',
    'before-catalog-private.jsonl', 'after-catalog-private.jsonl', 'before-row-counts-private.jsonl',
    'after-row-counts-private.jsonl', 'schema-before.sql', 'schema-after.sql', 'database.sql', 'database.sql.gz',
    'public-manifest.json', 'export-control-private.json'))
SNAPSHOT = 'local-mysql-export-snapshot'
RESTORE = 'local-mysql-export-restore'
OWNER = 'local-mysql-export-owner.json'
PUBLIC = 'local-mysql-export-public.json'


def need(value, message):
    if not value: raise ValueError(message)


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def common():
    return module('local_mysql_byte_primitives', ROOT / 'script/jenkins/preserve-local-artifacts.py')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(value): return hashlib.sha256(encoded(value)).hexdigest()


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(MIB), b''): result.update(block)
    return result.hexdigest()


def read(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            need(key not in value, 'Repeated custody metadata key'); value[key] = item
        return value
    path = common().safe(path)
    need(path.is_file() and 0 < path.stat().st_size <= MIB, 'Bounded regular custody metadata required')
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def write(path, value):
    path = Path(path); need(not path.exists() and not path.is_symlink(), 'Custody evidence is immutable')
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
        stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())


def catalogue(rows): return sha(sorted([[row['member'], row['bytes'], row['sha256']] for row in rows]))


def validate_export_metadata(public, control):
    need(public.get('kind') == 'doorhandle-local-mysql-export' and public.get('status') == 'LOCAL_EXPORT_COMPLETE_RESTORE_PENDING'
         and public.get('schemaVersion') == 1 and public.get('sourceSchema') == 'doorhandledb'
         and public.get('sourceEndpoint') == '127.0.0.1:3306' and public.get('tableCount') == 45
         and public.get('scriptSha256') == EXPORT_SCRIPT_SHA and public.get('rawSqlSha256') == RAW_SHA
         and public.get('rawSqlBytes') == RAW_BYTES and public.get('gzipSha256') == GZIP_SHA
         and public.get('gzipBytes') == GZIP_BYTES and public.get('actualClientIdentityVerified') is True
         and public.get('privateInputFilesRemoved') is True and public.get('credentialsArchived') is False
         and public.get('gzipByteReadbackVerified') is True and public.get('sourceDeleted') is False
         and public.get('servicesChanged') is False and public.get('testsExecuted') is False
         and public.get('cloudUploaded') is False and public.get('backupRestoreVerified') is False
         and public.get('retirementAllowed') is False
         and public.get('rowEvidence') == 'BEFORE_AFTER_OBSERVATIONS_NOT_THE_DUMP_TRANSACTION',
         'Only the complete reviewed one-time local export can be preserved')
    need(set(public.get('files', {})) == MEMBERS - {'public-manifest.json', 'export-control-private.json'},
         'The export member list omits data or contains an unreviewed/credential side file')
    need(control.get('status') == 'SCRIPT_COMPLETED' and control.get('scriptSha256') == EXPORT_SCRIPT_SHA
         and control.get('credentialInputRemoved') is True and control.get('servicesChanged') is False
         and control.get('sourceDeleted') is False, 'Approved administrator export control did not complete')


def validate_package(value):
    need(set(value) == {'version', 'kind', 'profile', 'status', 'catalogSha256', 'files', 'originalBytes',
         'archiveEncoding', 'archiveBytes', 'archiveSha256', 'exportManifestSha256', 'controlReceiptSha256', 'packedAtUtc'}
         and value['version'] == 1 and value['kind'] == KIND and value['profile'] == PROFILE
         and value['status'] == 'PACKED' and value['archiveEncoding'] == 'TAR_GZIP'
         and value['exportManifestSha256'] == EXPORT_SHA and value['controlReceiptSha256'] == CONTROL_SHA
         and type(value['archiveBytes']) is int and 0 < value['archiveBytes'] <= MAX_BYTES
         and SHA.fullmatch(value['archiveSha256']), 'Invalid local MySQL byte custody manifest')
    rows = value['files']; need(isinstance(rows, list) and len(rows) == len(MEMBERS), 'Incomplete closed MySQL custody members')
    seen, total = set(), 0
    for row in rows:
        need(set(row) == {'member', 'bytes', 'sha256', 'permissions'} and row['member'] in MEMBERS
             and row['member'] not in seen and type(row['bytes']) is int and 0 < row['bytes'] <= MAX_BYTES
             and SHA.fullmatch(row['sha256']) and isinstance(row['permissions'], dict), 'Unreviewed MySQL custody member')
        fields = {'mode', 'uid', 'gid', 'atimeNs', 'mtimeNs'}; permissions = row['permissions']
        need(fields <= set(permissions) <= fields | {'windowsSddl'} and all(type(permissions[key]) is int and permissions[key] >= 0 for key in fields)
             and permissions['mode'] <= 0o7777 and ('windowsSddl' not in permissions or isinstance(permissions['windowsSddl'], str)
             and 0 < len(permissions['windowsSddl']) <= 16384), 'Unreviewed original permission/time metadata')
        seen.add(row['member']); total += row['bytes']
    need(total == value['originalBytes'] <= MAX_BYTES and catalogue(rows) == value['catalogSha256'], 'MySQL custody catalogue changed')
    by_name = {row['member']: row for row in rows}
    need(all(by_name[name]['sha256'] == checksum for name, checksum in {'database.sql': RAW_SHA, 'database.sql.gz': GZIP_SHA,
         'public-manifest.json': EXPORT_SHA, 'export-control-private.json': CONTROL_SHA}.items()), 'Reviewed source hashes changed')
    return rows


def verify_gzip(path):
    result, size = hashlib.sha256(), 0
    with gzip.open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(MIB), b''):
            size += len(block); need(size <= RAW_BYTES, 'Expanded export exceeds the reviewed raw byte count'); result.update(block)
    need(size == RAW_BYTES and result.hexdigest() == RAW_SHA, 'Compressed SQL does not reproduce the exact original raw bytes')


def pack(export_directory, control_receipt, output):
    utility = common(); source = utility.safe(export_directory); control = utility.safe(control_receipt)
    output = utility.safe(output, exists=False)
    need(source == LOCAL_ROOT / 'work/data-migration-20261107' / EXPORT_DIRECTORY
         and control == LOCAL_ROOT / 'work/jenkins' / CONTROL_DIRECTORY / 'control-result.json'
         and not output.exists() and output.parent == LOCAL_ROOT / 'work/data-migration-20261107'
         and output.name.startswith('local-mysql-custody-'), 'Use the exact reviewed successful export and a new project-local package')
    need({p.name for p in source.iterdir()} == MEMBERS - {'export-control-private.json'}, 'Unknown side files cannot enter SQL custody')
    need(digest(source / 'public-manifest.json') == EXPORT_SHA and digest(control) == CONTROL_SHA, 'Approved export metadata changed')
    public, proof = read(source / 'public-manifest.json'), read(control); validate_export_metadata(public, proof)
    paths = {name: source / name for name in MEMBERS - {'export-control-private.json'}}
    paths['export-control-private.json'] = control
    rows, states = [], {}
    for name, path in sorted(paths.items()):
        utility.safe(path); before = path.stat()
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'Only original regular unlinked export files can be packed')
        checksum = digest(path)
        if name in public['files']:
            need(checksum == public['files'][name]['sha256'] and before.st_size == public['files'][name]['bytes'], 'An export file changed since its completed manifest')
        rows.append({'member': name, 'bytes': before.st_size, 'sha256': checksum, 'permissions': utility.permissions(path)})
        states[name] = utility.fingerprint(before)
        need(utility.fingerprint(path.stat()) == states[name], 'Export source changed while hashing')
    verify_gzip(source / 'database.sql.gz')
    need(shutil.disk_usage(output.parent).free >= utility.DISK_FLOOR + MAX_BYTES, 'Insufficient reserve for the small SQL custody package')
    utility.private_directory(output); archive = output / 'originals.tar.gz'
    with tarfile.open(archive, 'x:gz', format=tarfile.PAX_FORMAT, dereference=True) as package:
        for row in rows:
            path = paths[row['member']]; need(utility.fingerprint(path.stat()) == states[row['member']], 'Export source metadata drifted')
            info = tarfile.TarInfo(row['member']); info.size = row['bytes']; info.mode = 0o600
            info.mtime = row['permissions']['mtimeNs'] // 1000000000
            with path.open('rb') as stream: package.addfile(info, stream)
            need(digest(path) == row['sha256'] and utility.fingerprint(path.stat()) == states[row['member']], 'Export changed during byte copying')
    if os.name != 'nt': os.chmod(archive, 0o600)
    result = {'version': 1, 'kind': KIND, 'profile': PROFILE, 'status': 'PACKED', 'catalogSha256': catalogue(rows),
        'files': rows, 'originalBytes': sum(row['bytes'] for row in rows), 'archiveEncoding': 'TAR_GZIP',
        'archiveBytes': archive.stat().st_size, 'archiveSha256': digest(archive), 'exportManifestSha256': EXPORT_SHA,
        'controlReceiptSha256': CONTROL_SHA, 'packedAtUtc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    validate_package(result); write(output / 'custody.json', result)
    return {'status': 'PACKED', 'profile': PROFILE, 'files': len(rows), 'bytes': result['originalBytes'],
        'manifestSha256': digest(output / 'custody.json'), 'manifestBytes': (output / 'custody.json').stat().st_size,
        'archiveSha256': result['archiveSha256'], 'archiveBytes': result['archiveBytes'], 'databasesOpened': 0, 'sourceDeleted': False}


def admit(args):
    utility = common(); root = utility.safe(args.root); checkout = utility.safe(root / 'verification' / args.tag / 'checkout')
    need(ROOT == checkout and re.fullmatch(r'ci-[1-9][0-9]*-[a-f0-9]{12}', args.tag)
         and re.fullmatch(r'[a-f0-9]{40}', args.commit) and args.tag.endswith('-' + args.commit[:12])
         and SHA.fullmatch(args.source_sha256), 'Fixed source SQL custody identity required')
    identity = utility.identity(args.instance_id, args.machine_id)
    source = utility.safe(root / 'inbox' / args.tag / 'source.tar.gz')
    need(digest(source) == args.source_sha256, 'Fixed source archive changed')
    with tarfile.open(source, 'r:gz') as package:
        need(package.pax_headers.get('comment') == args.commit, 'Source archive commit differs')
        for name in ('script/jenkins/preserve-local-mysql.py', 'script/jenkins/restore-local-mysql.py',
                     'script/jenkins/preserve-local-artifacts.py', 'script/schema/compact_migration_runtime.py',
                     'script/schema/build_compact_schema.py', 'script/schema/compact_clock_policy.py',
                     'script/docker/compact-schema-guard.py', 'scripts/ecs_execution.py'):
            member = package.getmember(name)
            need(member.isfile() and 0 < member.size <= MIB and hashlib.sha256(package.extractfile(member).read(MIB + 1)).hexdigest()
                 == digest(utility.safe(ROOT / name)), 'Custody/recovery code differs from fixed source')
    receipt_file = utility.owner_path(checkout.parent / 'verification-receipt.json'); receipt = read(receipt_file)
    need(all(receipt.get(k) == v for k, v in {'status': 'PASS', 'verificationExitCode': 0, 'release': args.tag,
         'commit': args.commit, 'sourceSha256': args.source_sha256, 'identity': identity}.items()), 'This fixed build has no actual passing ECS verification')
    context = {'version': 1, 'kind': KIND, 'profile': PROFILE, 'release': args.tag, 'commit': args.commit,
        'sourceSha256': args.source_sha256, 'identity': identity, 'verificationReceiptSha256': digest(receipt_file)}
    for ancestor in (root, root / 'verification', checkout.parent, checkout, checkout / 'work'):
        utility.owned_ancestor(ancestor)
    return checkout / 'work', context


def inputs(args):
    need(SHA.fullmatch(args.manifest_sha256) and SHA.fullmatch(args.archive_sha256)
         and 0 < args.manifest_bytes <= MIB and 0 < args.archive_bytes <= MAX_BYTES, 'Explicit sealed byte bindings required')
    return {'custody.json': {'bytes': args.manifest_bytes, 'sha256': args.manifest_sha256},
            'originals.tar.gz': {'bytes': args.archive_bytes, 'sha256': args.archive_sha256}}


def prepare(args):
    work, context = admit(args); utility = common(); expected = inputs(args)
    need(not any((work / name).exists() for name in (SNAPSHOT, RESTORE, OWNER, PUBLIC)), 'Use a fresh SQL custody attempt')
    utility.resource_guard(work, MAX_BYTES * 2)
    write(work / OWNER, {**context, 'inputs': expected}); utility.private_directory(work / SNAPSHOT)
    for name in expected: os.close(os.open(work / SNAPSHOT / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    return {**context, 'status': 'PREPARED'}


def verify_restore(args):
    work, context = admit(args); utility = common(); owner = read(utility.owner_path(work / OWNER)); expected = inputs(args)
    need(all(owner.get(k) == v for k, v in context.items()) and owner['inputs'] == expected, 'SQL custody owner binding changed')
    snapshot = utility.owner_path(work / SNAPSHOT, directory=True)
    need({p.name for p in snapshot.iterdir()} == set(expected), 'SQL custody snapshot has extra/missing files')
    for name, binding in expected.items():
        file = utility.owner_path(snapshot / name)
        need(file.stat().st_size == binding['bytes'] and digest(file) == binding['sha256'], 'Transferred SQL custody bytes changed')
    manifest = read(snapshot / 'custody.json'); rows = validate_package(manifest)
    need(manifest['archiveBytes'] == args.archive_bytes and manifest['archiveSha256'] == args.archive_sha256, 'Archive/manifest binding differs')
    restore = utility.safe(work / RESTORE, exists=False); need(not restore.exists(), 'SQL recovery directory cannot be replayed')
    utility.resource_guard(work, manifest['originalBytes']); utility.private_directory(restore)
    wanted = {row['member']: row for row in rows}; seen = set(); total = 0
    class ClosedInfo(tarfile.TarInfo):
        @classmethod
        def frombuf(cls, buffer, encoding, errors):
            member = super().frombuf(buffer, encoding, errors)
            # Our closed producer emits only short ASCII names and integer
            # mtime. Reject metadata/long-name headers before gzip/PAX expansion.
            need(member.isfile() and member.name in MEMBERS and 0 < member.size <= MAX_BYTES,
                 'Unreviewed TAR header cannot enter the SQL custody parser')
            return member
    with tarfile.open(snapshot / 'originals.tar.gz', 'r:gz', tarinfo=ClosedInfo) as package:
        for member in package:
            need(member.isfile() and member.name in wanted and member.name not in seen and member.size == wanted[member.name]['bytes']
                 and not member.issparse() and not any(key.startswith('GNU.sparse') for key in member.pax_headers), 'Unexpected SQL custody archive member')
            total += member.size; need(total <= MAX_BYTES, 'SQL custody expanded byte bound exceeded')
            target = restore / member.name
            with package.extractfile(member) as source, os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as output:
                checksum, copied = hashlib.sha256(), 0
                for block in iter(lambda: source.read(MIB), b''):
                    copied += len(block); need(copied <= member.size, 'SQL custody member grew'); checksum.update(block); output.write(block)
                output.flush(); os.fsync(output.fileno())
            need(copied == member.size and checksum.hexdigest() == wanted[member.name]['sha256'] and digest(target) == wanted[member.name]['sha256'], 'SQL custody member byte recovery differs')
            seen.add(member.name)
    need(seen == MEMBERS, 'SQL custody archive omitted an original member')
    public = read(restore / 'public-manifest.json')
    validate_export_metadata(public, read(restore / 'export-control-private.json'))
    for name, binding in public['files'].items():
        need((restore / name).stat().st_size == binding['bytes'] and digest(restore / name) == binding['sha256'],
             'Recovered metadata/SQL differs from the original fixed export manifest')
    verify_gzip(restore / 'database.sql.gz')
    result = {**context, 'status': 'BYTES_RESTORED_VERIFIED', 'files': len(rows), 'bytes': total,
        'manifestSha256': args.manifest_sha256, 'archiveSha256': args.archive_sha256,
        'exportManifestSha256': EXPORT_SHA, 'rawSqlSha256': RAW_SHA, 'gzipSha256': GZIP_SHA,
        'databasesOpened': 0, 'sqlDoubleRestoreVerified': False, 'productionMerged': False, 'retirementAllowed': False}
    write(restore / 'restore-receipt.json', result); result['restoreReceiptSha256'] = digest(restore / 'restore-receipt.json')
    write(work / PUBLIC, result)
    return {**result, 'publicReceiptSha256': digest(work / PUBLIC)}


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    local = sub.add_parser('pack')
    for key in ('export-directory', 'control-receipt', 'output'): local.add_argument('--' + key, required=True)
    for action in ('prepare', 'verify-restore'):
        command = sub.add_parser(action)
        for key in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id', 'manifest-sha256', 'archive-sha256'):
            command.add_argument('--' + key, required=True)
        for key in ('manifest-bytes', 'archive-bytes'): command.add_argument('--' + key, type=int, required=True)
    args = parser.parse_args()
    try:
        result = pack(args.export_directory, args.control_receipt, args.output) if args.action == 'pack' else globals()[args.action.replace('-', '_')](args)
        print(json.dumps(result)); return 0
    except Exception as error:
        print(json.dumps({'kind': KIND, 'status': 'FAILED', 'phase': args.action, 'errorType': type(error).__name__, 'sourceDeleted': False})); return 2


if __name__ == '__main__': raise SystemExit(main())
