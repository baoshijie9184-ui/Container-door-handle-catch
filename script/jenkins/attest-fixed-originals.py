"""Read-only live ECS custody proof for frozen original bytes and explicit PTH aliases.

No restoration, source mutation, database reader, model loader or lifecycle
operation is provided. The proof digest is not a signature: callers must bind
this fixed recipe and the live SSH host key before accepting its projection.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
from types import SimpleNamespace


SELF = Path(__file__).absolute()
MIB = 1024 ** 2
SHA = re.compile(r'[a-f0-9]{64}')
TAG = re.compile(r'ci-([1-9][0-9]*)-([a-f0-9]{12})')
ATTESTATION_KIND = 'doorhandle-fixed-originals-retirement-attestation'
ATTESTATION_SECONDS_MAX = 300
ADMITTED_ROOTS = ('home', 'srv', 'opt')
CURRENT_FIELDS = 'release commit sourceSha256 identity verificationReceiptSha256'.split()
CUSTODY_FIELDS = CURRENT_FIELDS + 'publicReceiptSha256 restoreReceiptSha256 manifestSha256 archiveSha256 archiveBytes files bytes'.split()
ATTESTATION_FIELDS = 'kind schemaVersion status profile nonce issuedAtUtc expiresAtUtc current custody proofDigest'.split()
PROFILES = {
    'legacy-project-originals-v1': {'FILES': 5599, 'ORIGINAL_BYTES': 1321785341,
        'MANIFEST_SHA256': '56c1e60b441183dc9b06be99488b13ecd066a6ab8fbd0ad2f77f5632d6bea4d7',
        'SNAPSHOT': 'legacy-source-snapshot', 'MANIFEST': 'snapshot.json', 'ARCHIVE': 'originals.tar',
        'RESTORE': 'legacy-source-restore', 'PUBLIC': 'preservation-public.json', 'PUBLIC_IN_SNAPSHOT': True,
        'PUBLIC_KIND': 'doorhandle-legacy-source-preservation',
        'PUBLIC_PROFILE': 'legacy-stores-with-windows-mcp-and-kafka-v1',
        'PUBLIC_MANIFEST_FIELD': 'snapshotManifestSha256', 'MAX_ARCHIVE': 512 * MIB},
    'additional-originals-v1': {'FILES': 36, 'ORIGINAL_BYTES': 465240718,
        'MANIFEST_SHA256': 'b247f6f8bf0f5fc3e4d12b5bca008bb05786221d657262860de1ae6c479eec94',
        'SNAPSHOT': 'additional-local-artifacts-snapshot', 'MANIFEST': 'custody.json', 'ARCHIVE': 'originals.tar',
        'RESTORE': 'additional-local-artifacts-restore', 'PUBLIC': 'additional-local-artifacts-public-receipt.json',
        'PUBLIC_IN_SNAPSHOT': False, 'PUBLIC_KIND': 'doorhandle-additional-local-artifact-custody',
        'PUBLIC_PROFILE': 'additional-local-artifacts-v1', 'PUBLIC_MANIFEST_FIELD': 'manifestSha256',
        'MAX_ARCHIVE': 512 * MIB},
    'residual-project-originals-v1': {'FILES': 1968, 'ORIGINAL_BYTES': 8779830,
        'MANIFEST_SHA256': '471dedbba39f7220f760797ba1827040dd1cef7ac51af76daa8d7613117a6025',
        'CATALOG_SHA256': 'a9b6498c0f0e59b8821b0dbd9a8a4c1488bd300a67d92049f673e687fd49a00c',
        'SNAPSHOT': 'residual-project-originals-snapshot', 'MANIFEST': 'custody.json', 'ARCHIVE': 'originals.tar',
        'RESTORE': 'residual-project-originals-restore', 'PUBLIC': 'residual-project-originals-public-receipt.json',
        'PUBLIC_IN_SNAPSHOT': False, 'PUBLIC_KIND': 'doorhandle-additional-local-artifact-custody',
        'PUBLIC_PROFILE': 'residual-project-originals-v1', 'PUBLIC_MANIFEST_FIELD': 'manifestSha256',
        'MAX_ARCHIVE': 32 * MIB, 'MAX_MANIFEST': 2 * MIB},
    'remaining-system-data-v1': {'FILES': 86, 'ORIGINAL_BYTES': 28695377,
        'MANIFEST_SHA256': '6c8c5c1f9db87f8aed0c5578ff9781f69e93cb85f318a8797c63e2a66a340842',
        'CATALOG_SHA256': '0f92d397bed2b6f6a56a4dfec37d7c4bd6f41d195182b10604438ed10747baf4',
        'ARCHIVE_SHA256': '320d2dcee2d016391ae43960fd4777e995e9279e6689caf05d4ffa4973fd56a0', 'ARCHIVE_BYTES': 28825600,
        'SNAPSHOT': 'remaining-system-data-snapshot', 'MANIFEST': 'custody.json', 'ARCHIVE': 'originals.tar',
        'RESTORE': 'remaining-system-data-restore', 'PUBLIC': 'remaining-system-data-public-receipt.json',
        'PUBLIC_IN_SNAPSHOT': False, 'PUBLIC_KIND': 'doorhandle-additional-local-artifact-custody',
        'PUBLIC_PROFILE': 'remaining-system-data-v1', 'PUBLIC_MANIFEST_FIELD': 'manifestSha256',
        'MAX_ARCHIVE': 64 * MIB, 'MAX_MANIFEST': 2 * MIB},
    'legacy-partial-transports-v1': {'FILES': 4, 'ORIGINAL_BYTES': 155793058,
        'MANIFEST_SHA256': '7b9e2f51eb658b2eff8431b3b2fd5f003f1bfd9418e0947cd14c67ffbb12f6f2', 'MANIFEST_BYTES': 3583,
        'CATALOG_SHA256': 'a2669cdf5cb129eadb62361e1de1658482dc002f8dc53b193c11dd5fd5a9e477',
        'ARCHIVE_SHA256': '904d67de3b7a57bc5cf40c8f1e6894a2445fa867bf5c65dfa1e809e8c12f041b', 'ARCHIVE_BYTES': 155801600,
        'SNAPSHOT': 'legacy-partial-transports-snapshot', 'MANIFEST': 'custody.json', 'ARCHIVE': 'originals.tar',
        'RESTORE': 'legacy-partial-transports-restore', 'PUBLIC': 'legacy-partial-transports-public-receipt.json',
        'PUBLIC_IN_SNAPSHOT': False, 'PUBLIC_KIND': 'doorhandle-additional-local-artifact-custody',
        'PUBLIC_PROFILE': 'legacy-partial-transports-v1', 'PUBLIC_MANIFEST_FIELD': 'manifestSha256',
        'MAX_ARCHIVE': 256 * MIB, 'MAX_MANIFEST': 64 * 1024},
}
PROFILES['pth-aliases-v1'] = dict(PROFILES['additional-originals-v1'])
MODEL_SOURCE = Path('/srv/doorhandle/models/best_stg2.pth')
MODEL_MANIFEST_SOURCE = Path('/srv/doorhandle/models/manifest.json')
MODEL_BYTES = 159274200
MODEL_SHA256 = 'eb10caf9fe5fa41e1ce0cfe2bcfaaa728ff44c4fa56f3c6994d6fadb66da434b'
MODEL_SEALED_MEMBER = 'work/cloud/pth-model/best_stg2.pth'
MODEL_SEALED_SOURCE = 'D:/AI/lunwen1/DoorHandleCatch/work/cloud/pth-model/best_stg2.pth'
MODEL_ALLOWED_UIDS = (0, 1000)
MODEL_FIELDS = set(('sourcePath containerPath bytes sha256 ownerUid device inode mode links sealedManifestSha256 '
    'sealedMember manifest worker configuredModelSelectionVerified physicalModelVerified workerLoadedInMemory modelsExecuted').split())
MODEL_MANIFEST_FIELDS = set(('sourcePath containerPath bytes sha256 ownerUid device inode mode links schemaVersion '
    'format modelFile checkpointSha256').split())
MODEL_WORKER_FIELDS = set(('containerId imageId composeProject composeService running mountType mountSource mountDestination '
    'mountReadOnly configuredModelManifest configuredModelId configuredModelIdRaw processId').split())
CLOSURE = ('script/jenkins/attest-fixed-originals.py', 'script/jenkins/reuse-legacy-source.py',
    'script/jenkins/preserve-local-artifacts.py', 'script/jenkins/preserve-cold-stores.py',
    'script/jenkins/cleanup-ecs-builds.py', 'script/jenkins/verify-remote.py',
    'script/memory/migrate_legacy_stores.py')


class AttestationError(ValueError):
    pass


def need(value, code):
    if not value:
        raise AttestationError(code)


def recipe(profile):
    need(isinstance(profile, str) and profile in PROFILES, 'UNKNOWN_FIXED_ORIGINALS_PROFILE')
    fixed = PROFILES[profile]
    need(isinstance(fixed.get('MANIFEST_SHA256'), str) and SHA.fullmatch(fixed['MANIFEST_SHA256']),
         'FROZEN_FIXED_ORIGINALS_MANIFEST_REQUIRED')
    return fixed


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def attestation_time(value):
    need(isinstance(value, str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z', value),
         'ORIGINALS_ATTESTATION_UTC_REQUIRED')
    try:
        return dt.datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=dt.timezone.utc)
    except ValueError:
        raise AttestationError('ORIGINALS_ATTESTATION_UTC_REQUIRED') from None


def custody_projection(profile, public, public_receipt_sha256):
    """Pure projection of an independently authenticated original public receipt."""
    fixed = recipe(profile)
    need(type(public) is dict and public.get('kind') == fixed['PUBLIC_KIND']
         and public.get('profile') == fixed['PUBLIC_PROFILE'] and public.get('status') == 'RESTORED_VERIFIED',
         'EXACT_FIXED_ORIGINAL_PUBLIC_RECEIPT_REQUIRED')
    result = {key: public[key] for key in CURRENT_FIELDS}
    result.update(publicReceiptSha256=public_receipt_sha256, restoreReceiptSha256=public['restoreReceiptSha256'],
        manifestSha256=public[fixed['PUBLIC_MANIFEST_FIELD']], archiveSha256=public['archiveSha256'],
        archiveBytes=public['archiveBytes'], files=public['files'], bytes=public['bytes'])
    return result


def model_expected_reference():
    """Pure fixed policy; owner allowlist is authorized policy, not old observation."""
    return {'sourcePath': MODEL_SOURCE.as_posix(), 'containerPath': '/models/best_stg2.pth',
        'manifestSourcePath': MODEL_MANIFEST_SOURCE.as_posix(), 'manifestContainerPath': '/models/manifest.json',
        'bytes': MODEL_BYTES, 'sha256': MODEL_SHA256, 'allowedOwnerUids': list(MODEL_ALLOWED_UIDS),
        'sealedManifestSha256': PROFILES['pth-aliases-v1']['MANIFEST_SHA256'], 'sealedMember': MODEL_SEALED_MEMBER,
        'sealedMemberSourcePath': MODEL_SEALED_SOURCE, 'composeProject': 'doorhandlecatch-monolith',
        'composeService': 'detection-worker', 'mountType': 'bind', 'mountSource': '/srv/doorhandle/models',
        'mountDestination': '/models', 'mountReadOnly': True}


def validate_physical_model(value):
    fixed = model_expected_reference()
    need(type(value) is dict and set(value) == MODEL_FIELDS, 'COMPLETE_PHYSICAL_MODEL_PROOF_REQUIRED')
    for key in ('sourcePath', 'containerPath', 'bytes', 'sha256', 'sealedManifestSha256', 'sealedMember'):
        need(type(value.get(key)) is type(fixed[key]) and value[key] == fixed[key], 'PHYSICAL_MODEL_FIXED_REFERENCE_DRIFT')
    manifest, worker = value['manifest'], value['worker']
    need(type(manifest) is dict and set(manifest) == MODEL_MANIFEST_FIELDS and type(worker) is dict
         and set(worker) == MODEL_WORKER_FIELDS, 'PHYSICAL_MODEL_MANIFEST_OR_WORKER_REQUIRED')
    for row in (value, manifest):
        need(type(row.get('ownerUid')) is int and row['ownerUid'] in MODEL_ALLOWED_UIDS
             and type(row.get('device')) is int and row['device'] >= 0 and type(row.get('inode')) is int and row['inode'] > 0
             and type(row.get('links')) is int and row['links'] == 1
             and type(row.get('mode')) is int and 0 <= row['mode'] <= 0o7777 and not row['mode'] & 0o022,
             'PHYSICAL_MODEL_OWNER_ID_OR_MODE_DRIFT')
    need(manifest['sourcePath'] == fixed['manifestSourcePath'] and manifest['containerPath'] == fixed['manifestContainerPath']
         and type(manifest['bytes']) is int and 0 < manifest['bytes'] <= 65536
         and isinstance(manifest['sha256'], str) and SHA.fullmatch(manifest['sha256'])
         and type(manifest['schemaVersion']) is int and manifest['schemaVersion'] == 1 and manifest['format'] == 'pth'
         and manifest['modelFile'] == 'best_stg2.pth' and manifest['checkpointSha256'] == MODEL_SHA256,
         'PHYSICAL_MODEL_MANIFEST_SELECTION_DRIFT')
    need(isinstance(worker['containerId'], str) and SHA.fullmatch(worker['containerId'])
         and isinstance(worker['imageId'], str) and re.fullmatch(r'sha256:[a-f0-9]{64}', worker['imageId'])
         and type(worker['processId']) is int and worker['processId'] > 0
         and worker['running'] is True and type(worker['configuredModelId']) is int and 0 < worker['configuredModelId'] < 2 ** 63
         and worker['configuredModelManifest'] == fixed['manifestContainerPath'], 'PHYSICAL_MODEL_WORKER_BINDING_DRIFT')
    need(isinstance(worker['configuredModelIdRaw'], str) and len(worker['configuredModelIdRaw']) <= 64
         and re.fullmatch(r'\+?[0-9]{1,20}', worker['configuredModelIdRaw'].strip())
         and int(worker['configuredModelIdRaw']) == worker['configuredModelId'], 'PHYSICAL_MODEL_ID_GUARD_DRIFT')
    for key in ('composeProject', 'composeService', 'mountType', 'mountSource', 'mountDestination', 'mountReadOnly'):
        need(type(worker[key]) is type(fixed[key]) and worker[key] == fixed[key], 'PHYSICAL_MODEL_READONLY_MOUNT_DRIFT')
    need(value['configuredModelSelectionVerified'] is True and value['physicalModelVerified'] is True
         and value['workerLoadedInMemory'] is False and type(value['modelsExecuted']) is int and value['modelsExecuted'] == 0,
         'PHYSICAL_MODEL_OBSERVATION_SCOPE_DRIFT')
    return value


def validate_retirement_attestation(value, profile, nonce, expected_current, expected_custody, now_utc=None):
    """Pure validation only; an offline digest supplies no authentication."""
    fixed = recipe(profile)
    need(isinstance(nonce, str) and SHA.fullmatch(nonce), 'ORIGINALS_ATTESTATION_NONCE_REQUIRED')
    fields = set(ATTESTATION_FIELDS) | ({'physicalModel'} if profile == 'pth-aliases-v1' else set())
    need(type(value) is dict and set(value) == fields
         and value.get('kind') == ATTESTATION_KIND and type(value.get('schemaVersion')) is int and value['schemaVersion'] == 1
         and value.get('status') == 'CUSTODY_FRESHLY_ATTESTED' and value.get('profile') == profile
         and value.get('nonce') == nonce, 'ORIGINALS_ATTESTATION_ENVELOPE_DRIFT')
    need(isinstance(value.get('proofDigest'), str) and SHA.fullmatch(value['proofDigest'])
         and value['proofDigest'] == sha(encoded({key: item for key, item in value.items() if key != 'proofDigest'})),
         'ORIGINALS_ATTESTATION_DIGEST_DRIFT')
    for row, expected, fields in ((value['current'], expected_current, CURRENT_FIELDS),
                                  (value['custody'], expected_custody, CUSTODY_FIELDS)):
        need(type(row) is dict and type(expected) is dict and set(row) == set(expected) == set(fields) and row == expected,
             'ORIGINALS_ATTESTATION_EXPECTED_BINDING_DRIFT')
        tag, commit, identity = row['release'], row['commit'], row['identity']
        need(isinstance(tag, str) and TAG.fullmatch(tag) and isinstance(commit, str) and re.fullmatch(r'[a-f0-9]{40}', commit)
             and tag.endswith('-' + commit[:12]) and type(identity) is dict
             and set(identity) == {'instanceId', 'machineId', 'executionLocation'}
             and isinstance(identity.get('instanceId'), str) and re.fullmatch(r'i-[a-z0-9]+', identity['instanceId'])
             and isinstance(identity.get('machineId'), str) and re.fullmatch(r'[a-f0-9]{32}', identity['machineId'])
             and identity.get('executionLocation') == 'ECS', 'ORIGINALS_ATTESTATION_SOURCE_OR_IDENTITY_DRIFT')
        for key in fields:
            if key.endswith('Sha256'):
                need(isinstance(row[key], str) and SHA.fullmatch(row[key]), 'ORIGINALS_ATTESTATION_SHA_REQUIRED')
    current, old = value['current'], value['custody']
    need(current['identity'] == old['identity'] and int(TAG.fullmatch(old['release'])[1]) < int(TAG.fullmatch(current['release'])[1]),
         'ORIGINALS_ATTESTATION_OLDER_SAME_ECS_REQUIRED')
    need(old['manifestSha256'] == fixed['MANIFEST_SHA256'] and type(old['files']) is int and old['files'] == fixed['FILES']
         and type(old['bytes']) is int and old['bytes'] == fixed['ORIGINAL_BYTES']
         and type(old['archiveBytes']) is int and 0 < old['archiveBytes'] <= fixed['MAX_ARCHIVE'],
         'ORIGINALS_ATTESTATION_FIXED_PROFILE_DRIFT')
    if profile in ('remaining-system-data-v1', 'legacy-partial-transports-v1'):
        need(old['archiveSha256'] == fixed['ARCHIVE_SHA256'] and old['archiveBytes'] == fixed['ARCHIVE_BYTES'],
             'REMAINING_FIXED_ARCHIVE_DRIFT' if profile == 'remaining-system-data-v1' else 'PARTIAL_TRANSPORT_FIXED_ARCHIVE_DRIFT')
    issued, expires = attestation_time(value['issuedAtUtc']), attestation_time(value['expiresAtUtc'])
    now = utc_now() if now_utc is None else now_utc
    need(isinstance(now, dt.datetime) and now.tzinfo is not None and now.utcoffset() == dt.timedelta(0),
         'ORIGINALS_ATTESTATION_VERIFIER_UTC_REQUIRED')
    lifetime = (expires - issued).total_seconds()
    need(1 <= lifetime <= ATTESTATION_SECONDS_MAX and lifetime.is_integer() and issued <= now < expires,
         'ORIGINALS_ATTESTATION_EXPIRED_OR_FUTURE')
    if profile == 'pth-aliases-v1': validate_physical_model(value['physicalModel'])
    return value


def metadata(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink, info.st_mode)


def owned(path, *, directory=False, private=False):
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts and path.resolve(strict=True) == path, 'CANONICAL_ORIGINALS_PATH_REQUIRED')
    for parent in (path, *path.parents):
        info = parent.lstat()
        need(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
             'ORIGINALS_LINK_OR_REPARSE_REFUSED')
    info = path.lstat()
    need(info.st_uid == os.getuid() and not info.st_mode & 0o022
         and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1),
         'OWNED_ORIGINALS_RESOURCE_REQUIRED')
    if private:
        need(not info.st_mode & 0o077, 'PRIVATE_ORIGINALS_RESOURCE_REQUIRED')
    return path


def file_digest(path, maximum, *, private=False):
    path = owned(path, private=private); checksum = hashlib.sha256(); total = 0
    admitted = path.lstat()
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
             and not before.st_mode & 0o022 and (not private or not before.st_mode & 0o077)
             and metadata(before) == metadata(admitted), 'ORIGINALS_OPENED_FILE_ADMISSION_CHANGED')
        need(0 <= before.st_size <= maximum, 'ORIGINALS_FILE_SIZE_BOUND')
        for block in iter(lambda: stream.read(MIB), b''):
            total += len(block); need(total <= maximum, 'ORIGINALS_FILE_GREW'); checksum.update(block)
        after = os.fstat(stream.fileno())
    need(metadata(before) == metadata(after) == metadata(path.lstat()) and total == before.st_size,
         'ORIGINALS_FILE_CHANGED_DURING_HASH')
    return checksum.hexdigest(), total, metadata(after)


class LimitedReader:
    def __init__(self, stream):
        self.stream, self.total = stream, 0

    def read(self, size=-1):
        left = 512 * MIB - self.total
        raw = self.stream.read(left + 1 if size < 0 else min(size, left + 1)); self.total += len(raw)
        need(self.total <= 512 * MIB, 'FIXED_ORIGINALS_SOURCE_EXPANSION_BOUND')
        return raw


def load(path):
    spec = importlib.util.spec_from_file_location('fixed_originals_' + path.stem.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def fixed_modules(args):
    fixed = recipe(args.profile)
    need(sys.platform == 'linux' and isinstance(args.tag, str) and TAG.fullmatch(args.tag)
         and isinstance(args.commit, str) and re.fullmatch(r'[a-f0-9]{40}', args.commit)
         and args.tag.endswith('-' + args.commit[:12]) and isinstance(args.source_sha256, str)
         and SHA.fullmatch(args.source_sha256), 'FIXED_ORIGINALS_SOURCE_REQUEST_REQUIRED')
    if args.profile == 'pth-aliases-v1':
        need(os.getuid() == 1000, 'PTH_PROOF_REQUIRES_EXISTING_UID_1000')
    root = owned(args.root, directory=True)
    need(len(root.parts) > 1 and root.parts[1] in ADMITTED_ROOTS, 'ADMITTED_ORIGINALS_CI_ROOT_REQUIRED')
    checkout = owned(root / 'verification' / args.tag / 'checkout', directory=True)
    need(SELF == checkout / 'script/jenkins/attest-fixed-originals.py', 'FIXED_ORIGINALS_CHECKOUT_REQUIRED')
    source = root / 'inbox' / args.tag / 'source.tar.gz'
    need(file_digest(source, 128 * MIB, private=True)[0] == args.source_sha256, 'FIXED_ORIGINALS_SOURCE_ARCHIVE_CHANGED')
    wanted = {name: [owned(checkout / name)] for name in CLOSURE}
    if args.profile == 'legacy-project-originals-v1':
        inbox_executor = owned(root / 'inbox' / args.tag / 'reuse-legacy-source.py', private=True)
        wanted['script/jenkins/reuse-legacy-source.py'].append(inbox_executor)
    seen = set()
    with gzip.open(source, 'rb') as expanded, tarfile.open(fileobj=LimitedReader(expanded), mode='r|') as archive:
        for entry in archive:
            if entry.name not in wanted: continue
            need(entry.name not in seen and entry.isfile() and 0 < entry.size <= MIB, 'FIXED_ORIGINALS_RECIPE_MEMBER_INVALID')
            raw = archive.extractfile(entry).read(MIB + 1)
            need(len(raw) == entry.size and all(file_digest(path, MIB)[0] == sha(raw) for path in wanted[entry.name]),
                 'FIXED_ORIGINALS_RECIPE_CHANGED')
            seen.add(entry.name)
        need(seen == set(wanted) and archive.pax_headers.get('comment') == args.commit, 'FIXED_ORIGINALS_CLOSURE_INCOMPLETE')
        for block in iter(lambda: archive.fileobj.read(MIB), b''):
            need(not block.strip(b'\0'), 'FIXED_ORIGINALS_SOURCE_TRAILING_DATA')
    need(file_digest(source, 128 * MIB, private=True)[0] == args.source_sha256, 'FIXED_ORIGINALS_SOURCE_CHANGED_DURING_ADMISSION')
    # Suppress helper .pyc output even when an API caller omitted Python -B.
    sys.dont_write_bytecode = True
    modules = {name: load(checkout / name) for name in CLOSURE if name != 'script/jenkins/attest-fixed-originals.py'}
    state = SimpleNamespace(root=root, checkout=checkout, source=source, fixed=fixed,
        reuse=modules['script/jenkins/reuse-legacy-source.py'], artifacts=modules['script/jenkins/preserve-local-artifacts.py'],
        cold=modules['script/jenkins/preserve-cold-stores.py'], cleanup=modules['script/jenkins/cleanup-ecs-builds.py'],
        verifier=modules['script/jenkins/verify-remote.py'], migration=modules['script/memory/migrate_legacy_stores.py'])
    if args.profile in ('residual-project-originals-v1', 'remaining-system-data-v1', 'legacy-partial-transports-v1'):
        state.artifacts.select_profile(args.profile)
        need(state.artifacts.PROFILE == fixed['PUBLIC_PROFILE'] and state.artifacts.FILE_COUNT == fixed['FILES']
             and state.artifacts.ORIGINAL_BYTES == fixed['ORIGINAL_BYTES']
             and state.artifacts.CATALOG_SHA256 == fixed['CATALOG_SHA256']
             and state.artifacts.SNAPSHOT == fixed['SNAPSHOT'] and state.artifacts.RESTORE == fixed['RESTORE']
             and state.artifacts.PUBLIC == fixed['PUBLIC'] and state.artifacts.MAX_BYTES == fixed['MAX_ARCHIVE']
             and state.artifacts.MAX_MANIFEST == fixed['MAX_MANIFEST'], 'RESIDUAL_FIXED_PRODUCER_PROFILE_DRIFT')
    if args.profile == 'legacy-project-originals-v1':
        need(state.reuse.fixed_source(args, executor=inbox_executor) == checkout, 'LEGACY_FIXED_SOURCE_GATE_DIFFERED')
    return state


def current_pass(args, state):
    identity = state.artifacts.identity(args.expected_instance_id, args.expected_machine_id)
    record, checksum = state.cold.stopped_receipt(state.root, args.tag, identity, state.verifier, state.cleanup, current=True)
    need(record.get('kind') == 'doorhandle-ecs-ci' and record.get('scope') in ('source', 'mysql')
         and record.get('controlsOnly') is not True and record.get('fullProjectVerified') is not False,
         'ACTUAL_PROJECT_PASS_NOT_CONTROLS_REQUIRED')
    need(record['commit'] == args.commit and record['sourceSha256'] == args.source_sha256, 'CURRENT_ORIGINALS_PASS_SOURCE_CHANGED')
    return {key: record[key] for key in CURRENT_FIELDS if key != 'verificationReceiptSha256'} | {'verificationReceiptSha256': checksum}


def old_snapshot(args, state, current):
    fixed = state.fixed; old = Path(args.source_snapshot_directory)
    parts = old.relative_to(state.root / 'verification').parts if old.is_relative_to(state.root / 'verification') else ()
    need(len(parts) == 4 and TAG.fullmatch(parts[0]) and parts[1:] == ('checkout', 'work', fixed['SNAPSHOT'])
         and int(TAG.fullmatch(parts[0])[1]) < int(TAG.fullmatch(args.tag)[1]), 'EXACT_OLDER_ORIGINALS_SNAPSHOT_REQUIRED')
    owned(old, directory=True, private=True)
    manifest_sha, manifest_bytes, _ = file_digest(old / fixed['MANIFEST'], fixed.get('MAX_MANIFEST', 16 * MIB), private=True)
    need(manifest_sha == fixed['MANIFEST_SHA256']
         and ('MANIFEST_BYTES' not in fixed or manifest_bytes == fixed['MANIFEST_BYTES']),
         'FROZEN_ORIGINALS_MANIFEST_REQUIRED')
    if args.profile == 'legacy-project-originals-v1':
        admitted = state.reuse.admit_snapshot(state.root, old, args.tag, current['identity'], state.migration, state.cleanup, state.verifier)
        public, public_sha = admitted['public'], admitted['publicSha256']
    else:
        _, context, observed, public, public_sha = state.artifacts.original_snapshot(args)
        need(observed == old and all(context[key] == current[key] for key in CURRENT_FIELDS), 'ADDITIONAL_CURRENT_GATE_CHANGED')
        record = state.reuse.passing_receipt(old.parents[2] / 'verification-receipt.json', state.root, parts[0], current['identity'])
        state.reuse.terminal_build(state.root, old.parents[2], record, current['identity'], state.cleanup, state.verifier)
        need(file_digest(state.root / 'inbox' / parts[0] / 'source.tar.gz', 128 * MIB, private=True)[0] == public['sourceSha256'],
             'ADDITIONAL_OLD_FIXED_SOURCE_CHANGED')
        need(all(type(public.get(key)) is int and public[key] == 0 for key in ('originalFilesDeleted', 'modelsExecuted', 'databasesOpened')),
             'ADDITIONAL_ORIGINALS_NOT_UNTOUCHED')
        if args.profile == 'pth-aliases-v1':
            validate_sealed_model_member(state.artifacts.read_json(old / fixed['MANIFEST'], private=True))
    return old, custody_projection(args.profile, public, public_sha)


def validate_sealed_model_member(manifest):
    need(type(manifest) is dict and type(manifest.get('files')) is list, 'SEALED_PTH_MEMBER_REQUIRED')
    rows = [row for row in manifest['files'] if type(row) is dict and row.get('member') == MODEL_SEALED_MEMBER]
    need(len(rows) == 1 and type(rows[0].get('bytes')) is int and rows[0]['bytes'] == MODEL_BYTES
         and rows[0].get('sha256') == MODEL_SHA256 and isinstance(rows[0].get('sourcePath'), str)
         and rows[0]['sourcePath'].replace('\\', '/').casefold() == MODEL_SEALED_SOURCE.casefold(),
         'EXACT_SEALED_PTH_ORIGIN_REQUIRED')


def resource_metadata(info):
    return (*metadata(info), info.st_uid, info.st_gid)


@contextmanager
def model_resource(path, maximum):
    # This is the only non-CI ownership policy: two exact public model resources,
    # never arbitrary paths, private CI inputs, directories or credential files.
    need(path in (MODEL_SOURCE, MODEL_MANIFEST_SOURCE) and path.is_absolute() and '..' not in path.parts
         and path.resolve(strict=True) == path, 'EXACT_PHYSICAL_MODEL_PATH_REQUIRED')
    for parent in (path, *path.parents):
        need(not parent.is_symlink() and not getattr(parent.lstat(), 'st_file_attributes', 0) & 0x400,
             'PHYSICAL_MODEL_LINK_REFUSED')
    admitted = path.lstat()
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_uid in MODEL_ALLOWED_UIDS and before.st_nlink == 1
             and not before.st_mode & 0o022 and 0 < before.st_size <= maximum
             and resource_metadata(before) == resource_metadata(admitted), 'PHYSICAL_MODEL_FD_ADMISSION_REFUSED')
        yield stream, before
        need(resource_metadata(before) == resource_metadata(os.fstat(stream.fileno())) == resource_metadata(path.lstat()),
             'PHYSICAL_MODEL_IDENTITY_CHANGED')


def model_manifest(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            need(key not in value, 'DUPLICATE_MODEL_MANIFEST_KEY'); value[key] = item
        return value
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _: need(False, 'NONFINITE_MODEL_MANIFEST_VALUE'))
    need(type(value) is dict and type(value.get('schemaVersion')) is int and value['schemaVersion'] == 1
         and value.get('format') == 'pth' and value.get('modelFile') == 'best_stg2.pth'
         and value.get('checkpointSha256') == MODEL_SHA256
         and value.get('classNames') == ['Normal', 'Bent', 'Deformed', 'Rusty', 'Missing', 'Compromised'],
         'CONFIGURED_MODEL_MANIFEST_SELECTION_REFUSED')
    return value


def observe_model_files(*, expected_worker=None):
    with model_resource(MODEL_MANIFEST_SOURCE, 65536) as (manifest_stream, manifest_info), \
            model_resource(MODEL_SOURCE, MODEL_BYTES) as (model_stream, model_info):
        need(model_info.st_size == MODEL_BYTES, 'PHYSICAL_MODEL_EXACT_SIZE_REQUIRED')
        manifest_raw = manifest_stream.read(65537)
        need(len(manifest_raw) == manifest_info.st_size, 'MODEL_MANIFEST_RAW_SIZE_CHANGED')
        parsed = model_manifest(manifest_raw)
        def full_sha():
            checksum = hashlib.sha256(); total = 0
            for block in iter(lambda: model_stream.read(MIB), b''):
                total += len(block); need(total <= MODEL_BYTES, 'PHYSICAL_MODEL_GREW'); checksum.update(block)
            need(total == MODEL_BYTES and checksum.hexdigest() == MODEL_SHA256, 'PHYSICAL_MODEL_FULL_SHA_DIFFERS')
        full_sha()
        # Repeat both raw reads while the admitted descriptors remain open.
        model_stream.seek(0); full_sha(); manifest_stream.seek(0)
        need(manifest_stream.read(65537) == manifest_raw, 'MODEL_MANIFEST_CHANGED_AT_FINAL_READ')
        if expected_worker is not None:
            need(observe_worker() == expected_worker, 'WORKER_MODEL_CONFIGURATION_CHANGED_DURING_HASH')
        basic = lambda info: {'bytes': info.st_size, 'ownerUid': info.st_uid, 'device': info.st_dev,
                              'inode': info.st_ino, 'mode': stat.S_IMODE(info.st_mode), 'links': info.st_nlink}
        model = {'sourcePath': str(MODEL_SOURCE), 'containerPath': '/models/best_stg2.pth', 'sha256': MODEL_SHA256,
            'sealedManifestSha256': PROFILES['pth-aliases-v1']['MANIFEST_SHA256'], 'sealedMember': MODEL_SEALED_MEMBER,
            **basic(model_info)}
        model['manifest'] = {'sourcePath': str(MODEL_MANIFEST_SOURCE), 'containerPath': '/models/manifest.json',
            'sha256': sha(manifest_raw), **basic(manifest_info),
            **{key: parsed[key] for key in ('schemaVersion', 'format', 'modelFile', 'checkpointSha256')}}
    return model


def docker_output(arguments, maximum=128 * 1024):
    executable = shutil.which('docker'); need(executable, 'EXISTING_LOCAL_DOCKER_CLIENT_REQUIRED')
    environment = {key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')}
    result = subprocess.run([executable, '--host', 'unix:///var/run/docker.sock', *arguments],
                            capture_output=True, timeout=20, env=environment)
    need(result.returncode == 0 and 0 < len(result.stdout) <= maximum, 'LOCAL_WORKER_METADATA_READ_FAILED')
    return result.stdout


def observe_worker():
    ids = docker_output(['ps', '-q', '--no-trunc', '--filter', 'label=com.docker.compose.project=doorhandlecatch-monolith',
        '--filter', 'label=com.docker.compose.service=detection-worker'], 4096).decode('ascii').split()
    need(len(ids) == 1 and SHA.fullmatch(ids[0]), 'ONE_ACTUAL_DETECTION_WORKER_REQUIRED')
    # The CLI projects only these two approved path/ID environment entries.
    # No .env file or other Config.Env values reach this helper's stdout/state.
    environment_entry = lambda key: '{{range .Config.Env}}{{if eq (index (split . "=") 0) "' + key + '"}}{{json .}}{{end}}{{end}}'
    template = ('{"containerId":{{json .Id}},"imageId":{{json .Image}},"running":{{json .State.Running}},'
        '"restarting":{{json .State.Restarting}},"processId":{{json .State.Pid}},'
        '"composeProject":{{json (index .Config.Labels "com.docker.compose.project")}},'
        '"composeService":{{json (index .Config.Labels "com.docker.compose.service")}},'
        '"modelManifest":' + environment_entry('DETECTION_MODEL_MANIFEST') + ',"modelId":'
        + environment_entry('DETECTION_MODEL_ID') + ',"mounts":{{json .Mounts}}}')
    value = json.loads(docker_output(['inspect', '--format', template, ids[0]]))
    need(type(value) is dict and value.get('containerId') == ids[0] and value.get('running') is True
         and value.get('restarting') is False and type(value.get('processId')) is int and value['processId'] > 0
         and value.get('composeProject') == 'doorhandlecatch-monolith' and value.get('composeService') == 'detection-worker'
         and isinstance(value.get('imageId'), str) and re.fullmatch(r'sha256:[a-f0-9]{64}', value['imageId']),
         'ACTUAL_WORKER_STATE_OR_ROLE_DIFFERS')
    manifest_entry, model_entry = value.get('modelManifest'), value.get('modelId')
    need(manifest_entry == 'DETECTION_MODEL_MANIFEST=/models/manifest.json' and isinstance(model_entry, str)
         and model_entry.startswith('DETECTION_MODEL_ID='), 'ACTUAL_MODEL_CONFIGURATION_REQUIRED')
    model_id = model_entry[len('DETECTION_MODEL_ID='):]
    need(len(model_id) <= 64 and re.fullmatch(r'\+?[0-9]{1,20}', model_id.strip())
         and 0 < int(model_id) < 2 ** 63, 'POSITIVE_KAFKA_MODEL_ID_GUARD_REQUIRED')
    mounts = value.get('mounts'); need(type(mounts) is list, 'ACTUAL_MODEL_MOUNT_REQUIRED')
    for path in ('/models/manifest.json', '/models/best_stg2.pth'):
        covering = [mount for mount in mounts if type(mount) is dict and isinstance(mount.get('Destination'), str)
                    and (path == mount['Destination'] or path.startswith(mount['Destination'].rstrip('/') + '/'))]
        need(len(covering) == 1 and covering[0].get('Type') == 'bind' and covering[0].get('Source') == '/srv/doorhandle/models'
             and covering[0].get('Destination') == '/models' and covering[0].get('RW') is False,
             'EXACT_READONLY_WORKER_MODEL_BIND_REQUIRED')
    return {'containerId': value['containerId'], 'imageId': value['imageId'], 'processId': value['processId'],
        'composeProject': value['composeProject'], 'composeService': value['composeService'], 'running': True,
        'mountType': 'bind', 'mountSource': '/srv/doorhandle/models', 'mountDestination': '/models', 'mountReadOnly': True,
        'configuredModelManifest': '/models/manifest.json', 'configuredModelId': int(model_id), 'configuredModelIdRaw': model_id}


def physical_model_proof():
    worker = observe_worker(); model = observe_model_files(expected_worker=worker)
    model.update(worker=worker, configuredModelSelectionVerified=True, physicalModelVerified=True,
                 workerLoadedInMemory=False, modelsExecuted=0)
    return validate_physical_model(model)


def remaining_restored_bindings(state, old):
    """Freshly hash every independent opaque restore; never activate its data."""
    if state.fixed['PUBLIC_PROFILE'] not in ('remaining-system-data-v1', 'legacy-partial-transports-v1'): return ()
    need(file_digest(old / state.fixed['MANIFEST'], state.fixed['MAX_MANIFEST'], private=True)[0]
         == state.fixed['MANIFEST_SHA256'], 'ORIGINALS_ATTESTATION_RAW_INPUT_CHANGED')
    manifest = state.artifacts.read_json(old / state.fixed['MANIFEST'], private=True)
    rows = state.artifacts.validate_manifest(manifest)
    restore = owned(old.parent / state.fixed['RESTORE'], directory=True, private=True)
    expected = {row['member'] for row in rows} | {'restore-receipt.json'}
    directories = {parent.as_posix() for name in expected for parent in Path(name).parents if str(parent) != '.'}
    observed_files, observed_directories = set(), set()
    for base, folders, files in os.walk(restore, followlinks=False):
        for name in folders + files:
            path = Path(base) / name; relative = path.relative_to(restore).as_posix()
            need(relative in (directories if name in folders else expected), 'REMAINING_RESTORE_MEMBERSHIP_DRIFT')
            owned(path, directory=name in folders, private=True)
            (observed_directories if name in folders else observed_files).add(relative)
    need(observed_files == expected and observed_directories == directories, 'REMAINING_RESTORE_INCOMPLETE')
    return tuple((restore / row['member'], row['sha256'], row['bytes']) for row in rows)


def fresh_retirement_attest(args):
    fixed = recipe(args.profile); nonce = getattr(args, 'nonce', None); seconds = getattr(args, 'attestation_seconds', 120)
    need(isinstance(nonce, str) and SHA.fullmatch(nonce), 'ORIGINALS_ATTESTATION_NONCE_REQUIRED')
    need(type(seconds) is int and 1 <= seconds <= ATTESTATION_SECONDS_MAX, 'ORIGINALS_ATTESTATION_TTL_REQUIRED')
    issued, started = utc_now(), time.monotonic()
    state = fixed_modules(args); current = current_pass(args, state); old, custody = old_snapshot(args, state, current)
    public_file = (old if fixed['PUBLIC_IN_SNAPSHOT'] else old.parent) / fixed['PUBLIC']
    restored = remaining_restored_bindings(state, old)
    bindings = ((old / fixed['MANIFEST'], custody['manifestSha256'], fixed.get('MAX_MANIFEST', 16 * MIB)),
        (old / fixed['ARCHIVE'], custody['archiveSha256'], fixed['MAX_ARCHIVE']),
        (public_file, custody['publicReceiptSha256'], MIB),
        (old.parent / fixed['RESTORE'] / 'restore-receipt.json', custody['restoreReceiptSha256'], 16 * MIB),
        (state.checkout.parent / 'verification-receipt.json', current['verificationReceiptSha256'], MIB),
        (state.source, args.source_sha256, 128 * MIB)) + restored
    observations = []
    for path, expected, maximum in bindings:
        observed, size, stamp = file_digest(path, maximum, private=True)
        need(observed == expected and (path != old / fixed['ARCHIVE'] or size == custody['archiveBytes']),
             'ORIGINALS_ATTESTATION_RAW_INPUT_CHANGED')
        observations.append((path, stamp))
    physical = physical_model_proof() if args.profile == 'pth-aliases-v1' else None
    need(all(metadata(owned(path, private=True).lstat()) == stamp for path, stamp in observations),
         'ORIGINALS_ATTESTATION_INPUT_CHANGED_AFTER_HASH')
    need(remaining_restored_bindings(state, old) == restored, 'REMAINING_RESTORE_CHANGED_AFTER_HASH')
    need(0 <= time.monotonic() - started < seconds, 'ORIGINALS_ATTESTATION_OBSERVATION_EXPIRED')
    value = {'kind': ATTESTATION_KIND, 'schemaVersion': 1, 'status': 'CUSTODY_FRESHLY_ATTESTED',
        'profile': args.profile, 'nonce': nonce, 'current': current, 'custody': custody,
        'issuedAtUtc': issued.isoformat(timespec='microseconds').replace('+00:00', 'Z'),
        'expiresAtUtc': (issued + dt.timedelta(seconds=seconds)).isoformat(timespec='microseconds').replace('+00:00', 'Z')}
    if physical is not None: value['physicalModel'] = physical
    value['proofDigest'] = sha(encoded(value))
    return validate_retirement_attestation(value, args.profile, nonce, current, custody)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('fresh-retirement-attest',))
    for flag in ('root', 'tag', 'commit', 'source-sha256', 'expected-instance-id', 'expected-machine-id', 'source-snapshot-directory', 'nonce'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--profile', choices=tuple(PROFILES), required=True)
    parser.add_argument('--attestation-seconds', type=int, default=120)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(fresh_retirement_attest(args))); return 0
    except Exception as error:
        print(json.dumps({'status': 'REFUSED', 'errorType': type(error).__name__,
            'code': str(error) if isinstance(error, AttestationError) else 'FIXED_ORIGINALS_ATTESTATION_REJECTED',
            'originalFilesDeleted': 0}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
