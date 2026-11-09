"""Retire one exact, proven failed-native JAR copy while retaining its keeper.

The CLI authenticates fixed current source and ECS identity before importing
the existing strict cleanup admission library. The local Jenkins controller
authenticates the request SHA and the original C/D control-file byte provenance.
No retained source archive, inbox original, database, report, image or directory
has a deletion API here. Historical metadata never substitutes for keeper bytes.
"""
from __future__ import annotations

from contextlib import contextmanager
import argparse
import ast
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tarfile
from types import SimpleNamespace
import xml.etree.ElementTree as ET


TAG = re.compile(r'ci-([1-9][0-9]*)-([a-f0-9]{12})')
SHA = re.compile(r'[a-f0-9]{64}')
COMMIT = re.compile(r'[a-f0-9]{40}')
MAX_CONTROL = 2 * 1024 ** 2
MAX_JAR = 512 * 1024 ** 2
MAX_SOURCE_ARCHIVE = 128 * 1024 ** 2
MAX_EXPANDED_SOURCE = 512 * 1024 ** 2
REQUIRED_CONTROLS = {'buildXml', 'release', 'artifactPlan', 'fixtureOwner', 'fixtureCleanup'}
OPTIONAL_CONTROLS = {'localBuild', 'fixtureCleanupPublic'}
UPLOADED_NAMES = {'buildXml': 'build.xml', 'release': 'release.json', 'localBuild': 'local-build.json',
                  'fixtureCleanupPublic': 'fixture-cleanup.json'}
KIND = 'doorhandle-failed-native-jar-duplicate'
APPROVED_OLD = {
    'ci-117-8c898996cc28': '8c898996cc28ce30fd6531710511f833cccb4864',
    'ci-118-6481f7fa6021': '6481f7fa6021eb36592a081d04f385886c03412a',
    'ci-130-9a588271dadb': '9a588271dadb135ec4284392ef7b9c9c55ea511d',
    'ci-132-69f2ef0fb309': '69f2ef0fb3091cc204b75194aa6da96c696136f0',
    'ci-134-df30e17036de': 'df30e17036de96863957b13e57f12b129bbfa951',
    'ci-137-facc2ed94047': 'facc2ed94047d7cc01da8072195e6d769c6f1385',
    'ci-139-384439388a8c': '384439388a8c6de52ca90be62722c382ff8973bb',
    'ci-141-56da3c4f7800': '56da3c4f780055e4f1f1ae835888189e85807bec',
    'ci-143-f4b5c8d9e39b': 'f4b5c8d9e39bfe621c97fb1d9e82aea667bab08f',
    'ci-145-dd85b09748a9': 'dd85b09748a996f68e909fa54bc9412110e78134',
    'ci-154-38293aa306b3': '38293aa306b368964bbc2a7f66bb6a6b5c414016',
}
# Original tool bytes recorded by the retained Jenkins preparation receipts.
# These values authenticate the owner chain; matching self-described fields
# alone never authorize retiring an old container.
APPROVED_BUILDER_TOOLS = {
    'ci-117-8c898996cc28': 'da96602b35fc023d3b07ea853026dcc311739c1c3903e086f81af3d7e912a9e4',
    'ci-118-6481f7fa6021': 'ff6df0c9f30b38d66f6bc6bbfd42c2fae86d6fe75a7906fafbe19ce10fcb326a',
    'ci-130-9a588271dadb': '805a2a101db89e26ef54224cd4f1456f4f4b545675485a114374cacbc2bc3fb1',
    'ci-132-69f2ef0fb309': '3123890d98586741cb14d2c2af0d269337b04243d985665b7e46a2c7b2a490d5',
    'ci-134-df30e17036de': 'f8cf1deacead2aad74b133409813bd4448218a68231fda43e3cf1c0088b29252',
    'ci-137-facc2ed94047': 'c8499b18b72497ec1d46d239ebbfcdbf5b2c1a24b6989a194f79eff9685e6313',
    'ci-139-384439388a8c': '0d01a488d105dca27e5926b2ff0fb0070c8a50ce615b79ab4ac1032ca4d6bf9a',
    'ci-141-56da3c4f7800': '332eaa16ca7c39154ff4f81dc9956ad6cf51f1ee3fda8075787c2067a255b87b',
    'ci-143-f4b5c8d9e39b': '74d9b97fbaaa8d5af0cea2d3cfa32df7b5f831e392bcca39340eac02d46cac04',
    'ci-145-dd85b09748a9': '7e55b094d7b558fd66d299a6c872749d6cb87071b50bb031ce2a5d71d03283d4',
    'ci-154-38293aa306b3': 'eb0d82fc9983279390d467849029786648a1dbceda53371924e3894232e25c27',
}


class RetirementError(ValueError):
    pass


def need(value, code):
    if not value: raise RetirementError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def digest_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def metadata(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_blocks * 512]


def decode(raw):
    need(type(raw) is bytes and 0 < len(raw) <= MAX_CONTROL, 'BOUNDED_RAW_CONTROL_REQUIRED')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'DUPLICATE_CONTROL_FIELD'); result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _v: need(False, 'NONFINITE_CONTROL'))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise RetirementError('INVALID_CONTROL_JSON') from None
    need(type(value) is dict, 'CONTROL_OBJECT_REQUIRED')
    return value


def validate_context(context):
    need(type(context) is dict and set(context) == {'release', 'commit', 'sourceSha256'}
         and type(context['release']) is str and TAG.fullmatch(context['release'])
         and type(context['commit']) is str and COMMIT.fullmatch(context['commit'])
         and context['release'].endswith('-' + context['commit'][:12])
         and type(context['sourceSha256']) is str and SHA.fullmatch(context['sourceSha256']), 'FIXED_BUILD_CONTEXT_REQUIRED')


def same_context(value, context):
    need(all(value.get(key) == expected for key, expected in context.items()), 'CROSS_BUILD_CONTROL')


def terminal_xml(raw, context):
    need(type(raw) is bytes and 0 < len(raw) <= MAX_CONTROL
         and b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'BOUNDED_ENTITY_FREE_TERMINAL_XML_REQUIRED')
    try: root = ET.fromstring(raw)
    except ET.ParseError: raise RetirementError('INVALID_TERMINAL_XML') from None
    need(root.tag == 'flow-build' and len(root.findall('result')) == len(root.findall('completed')) == 1
         and root.findtext('result') in ('FAILURE', 'ABORTED') and root.findtext('completed') == 'true'
         and len(root.findall('execution/done')) == 1 and root.findtext('execution/done') == 'true',
         'ACTUAL_FAILED_NATIVE_TERMINAL_REQUIRED')
    parameters = {}
    for item in root.findall('.//hudson.model.ParametersAction/parameters/*'):
        name, value = item.findtext('name'), item.findtext('value')
        need(name and name not in parameters, 'DUPLICATE_TERMINAL_PARAMETER')
        parameters[name] = value
    need(all(parameters.get(key) == value for key, value in {'ACTION': 'verify-runtime', 'DOORHANDLE_CI_SCOPE': 'mysql',
        'TRUSTED_COMMIT': context['commit'], 'PRODUCTION_RELEASE_ENABLED': 'false'}.items()), 'FAILED_NATIVE_PARAMETERS_REQUIRED')
    return root.findtext('result')


def validate_control_documents(raw_docs, context, identity):
    """Pure validation of actual raw controls already authenticated by Jenkins."""
    validate_context(context)
    need(type(identity) is dict and set(identity) == {'instanceId', 'machineId', 'executionLocation'}
         and identity['executionLocation'] == 'ECS' and type(identity['instanceId']) is str
         and re.fullmatch(r'i-[a-z0-9]+', identity['instanceId']) and type(identity['machineId']) is str
         and re.fullmatch(r'[a-f0-9]{32}', identity['machineId']), 'EXACT_ECS_IDENTITY_REQUIRED')
    need(type(raw_docs) is dict and REQUIRED_CONTROLS <= set(raw_docs) <= REQUIRED_CONTROLS | OPTIONAL_CONTROLS,
         'COMPLETE_ACTUAL_CONTROL_BUNDLE_REQUIRED')
    result = terminal_xml(raw_docs['buildXml'], context)
    docs = {name: decode(raw) for name, raw in raw_docs.items() if name != 'buildXml'}
    release, plan, owner, cleanup = (docs[name] for name in ('release', 'artifactPlan', 'fixtureOwner', 'fixtureCleanup'))
    for value in (release, plan, owner, cleanup): same_context(value, context)
    jar_sha, jar_bytes = release.get('applicationJarSha256'), plan.get('applicationJarBytes')
    need(type(jar_sha) is str and SHA.fullmatch(jar_sha) and type(jar_bytes) is int and 0 < jar_bytes <= MAX_JAR
         and plan.get('schema') == 1 and type(plan['schema']) is int
         and plan.get('kind') == 'doorhandle-compact-fixture-artifacts' and plan.get('applicationJarSha256') == jar_sha,
         'RELEASE_AND_NATIVE_ARTIFACT_PLAN_REQUIRED')
    suffix = '/verification/' + context['release'] + '/checkout/work/compact-fixtures'
    need(type(owner.get('schemaVersion')) is int and owner['schemaVersion'] == 1
         and owner.get('kind') == 'doorhandle-compact-fixture-owner' and owner.get('identity') == identity
         and owner.get('phase') == 'OWNED_SERVER_STOPPED' and type(owner.get('token')) is str
         and re.fullmatch(r'[a-f0-9]{10}', owner['token']) and type(owner.get('work')) is str
         and owner['work'].startswith(('/home/', '/srv/', '/opt/')) and owner['work'].endswith(suffix)
         and '..' not in Path(owner['work']).parts and '//' not in owner['work']
         and type(owner.get('sourceContainerId')) is str and SHA.fullmatch(owner['sourceContainerId'])
         and (owner.get('containerId') is None or type(owner['containerId']) is str and SHA.fullmatch(owner['containerId'])),
         'ORIGINAL_STOPPED_FIXTURE_OWNER_REQUIRED')
    need(type(cleanup.get('schemaVersion')) is int and cleanup['schemaVersion'] == 1
         and cleanup.get('kind') == 'doorhandle-compact-fixture-cleanup' and cleanup.get('identity') == identity
         and cleanup.get('status') == 'STOPPED' and cleanup.get('errors') == []
         and cleanup.get('containerId') == owner.get('containerId')
         and cleanup.get('sourceContainerUntouched') == owner['sourceContainerId']
         and cleanup.get('sourceDumpAndEvidenceRetained') is True, 'ORIGINAL_NATIVE_CLEANUP_NOT_CONFIRMED')
    if 'localBuild' in docs:
        local = docs['localBuild']
        need(local.get('release') == context['release'] and local.get('commit') == context['commit']
             and ('sourceSha256' not in local or local['sourceSha256'] == context['sourceSha256']), 'OPTIONAL_LOCAL_BUILD_CONTEXT_DRIFT')
        need(type(local.get('schemaVersion')) is int and local['schemaVersion'] == 1
             and local.get('status') == 'PASS' and type(local.get('exitCode')) is int and local['exitCode'] == 0
             and local.get('testsExecuted') is False and local.get('skipTests') is True
             and local.get('applicationJarSha256') == jar_sha and type(local.get('applicationJarBytes')) is int
             and local['applicationJarBytes'] == jar_bytes
             and release.get('localBuildReceiptSha256') == digest_bytes(raw_docs['localBuild']), 'OPTIONAL_LOCAL_BUILD_BINDING_DRIFT')
    if 'fixtureCleanupPublic' in docs:
        public = docs['fixtureCleanupPublic']
        need(public.get('release') == context['release'] and public.get('commit') == context['commit']
             and public.get('status') == 'STOPPED' and public.get('cleanupReceipt') == owner['work'] + '/cleanup-receipt.json'
             and public.get('cleanupReceiptSha256') == digest_bytes(raw_docs['fixtureCleanup']), 'OPTIONAL_CLEANUP_WRAPPER_DRIFT')
    return {'context': dict(context), 'identity': dict(identity), 'jenkinsResult': result,
            'jarSha256': jar_sha, 'jarBytes': jar_bytes, 'ownerToken': owner['token'], 'work': owner['work'],
            'controlSha256': {name: digest_bytes(raw) for name, raw in raw_docs.items()}}


def owned_path(root, path, *, directory=False):
    root, path = Path(root), Path(path)
    need(root.is_absolute() and root.resolve(strict=True) == root and path.is_absolute()
         and path.is_relative_to(root) and '..' not in path.parts and path.resolve(strict=True) == path,
         'CANONICAL_SAME_CI_ROOT_REQUIRED')
    for parent in (path, *path.parents):
        info = parent.lstat(); need(not stat.S_ISLNK(info.st_mode), 'LINK_NOT_ALLOWED')
        if parent == root or parent.is_relative_to(root):
            need(info.st_uid == os.getuid() and not info.st_mode & 0o022, 'OWNER_OR_MODE_CHANGED')
    info = path.lstat()
    need(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
         'REGULAR_SINGLE_LINK_REQUIRED')
    return path


@contextmanager
def held_file(root, path, maximum):
    path = owned_path(root, path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = metadata(os.fstat(stream.fileno()))
        need(before == metadata(path.lstat()) and 0 <= before[6] <= maximum, 'STABLE_BOUNDED_FILE_REQUIRED')
        yield stream, before
        need(before == metadata(os.fstat(stream.fileno())) == metadata(path.lstat()), 'FILE_CHANGED_DURING_READ')


def hash_stream(stream, maximum=MAX_JAR):
    stream.seek(0); checksum = hashlib.sha256(); total = 0
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        total += len(block); need(total <= maximum, 'STREAM_BYTE_LIMIT_EXCEEDED'); checksum.update(block)
    return checksum.hexdigest()


def duplicate_paths(root, tag):
    need(type(tag) is str and TAG.fullmatch(tag), 'EXACT_OLD_TAG_REQUIRED')
    root = Path(root)
    return (root / 'verification' / tag / 'checkout/work/compact-fixtures/candidate-app.jar',
            root / 'inbox' / tag / 'application.jar')


def describe_duplicate(root, tag, jar_sha, jar_bytes):
    need(type(jar_sha) is str and SHA.fullmatch(jar_sha) and type(jar_bytes) is int and 0 < jar_bytes <= MAX_JAR,
         'EXACT_DECLARED_JAR_REQUIRED')
    root = Path(root); target, keeper = duplicate_paths(root, tag)
    need(target.exists() or target.is_symlink(), 'EXACT_CANDIDATE_COPY_MISSING')
    need(keeper.exists() or keeper.is_symlink(), 'EXACT_ECS_KEEPER_MISSING')
    with held_file(root, target, MAX_JAR) as (target_stream, target_info), held_file(root, keeper, MAX_JAR) as (keeper_stream, keeper_info):
        need(target_info[:2] != keeper_info[:2] and target_info[0] == keeper_info[0]
             and target_info[6] == keeper_info[6] == jar_bytes, 'INDEPENDENT_SAME_SIZE_DUPLICATE_REQUIRED')
        need(hash_stream(target_stream) == hash_stream(keeper_stream) == jar_sha, 'ACTUAL_KEEPER_BYTES_MUST_EQUAL_TARGET')
        return {'kind': 'FAILED_NATIVE_CANDIDATE_JAR_COPY', 'release': tag,
            'path': target.relative_to(root).as_posix(), 'metadata': target_info, 'sha256': jar_sha, 'bytes': jar_bytes,
            'allocatedBytes': target_info[9], 'keeper': {'path': keeper.relative_to(root).as_posix(),
                'metadata': keeper_info, 'sha256': jar_sha, 'bytes': jar_bytes}}


def reserve_quarantine(root, current_tag=None):
    """Reserve a new, private, helper-owned directory; never reuse a path."""
    root=Path(root)
    need(current_tag is None or type(current_tag) is str and TAG.fullmatch(current_tag), 'EXACT_CURRENT_QUARANTINE_TAG_REQUIRED')
    parent=root if current_tag is None else root/'inbox'/current_tag
    owned_path(root,parent,directory=True)
    name='native-jar-quarantine-'+secrets.token_hex(12)
    parent_fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        need(metadata(os.fstat(parent_fd))==metadata(parent.lstat()), 'QUARANTINE_PARENT_MOVED')
        os.mkdir(name,0o700,dir_fd=parent_fd);os.fsync(parent_fd)
        directory=parent/name;info=directory.lstat()
        need(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode)==0o700 and info.st_uid==os.getuid(),
             'PRIVATE_NEW_QUARANTINE_REQUIRED')
        return {'directory':directory.relative_to(root).as_posix(),
                'path':(directory/'candidate-app.jar').relative_to(root).as_posix(),
                'directoryIdentity':[info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_gid]}
    finally:os.close(parent_fd)


def _capture_no_replace(source_fd, source_name, destination_fd, destination_name):
    """Linux atomic rename with NOREPLACE, never an overwriting rename fallback."""
    import ctypes
    import errno
    library=ctypes.CDLL(None,use_errno=True)
    operation=getattr(library,'renameat2',None)
    need(operation is not None, 'ATOMIC_NOREPLACE_RENAME_REQUIRED')
    operation.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    operation.restype=ctypes.c_int
    result=operation(source_fd,os.fsencode(source_name),destination_fd,os.fsencode(destination_name),1)
    if result!=0:
        number=ctypes.get_errno()
        need(number!=errno.EEXIST,'PRIVATE_QUARANTINE_ALREADY_OCCUPIED')
        raise OSError(number,os.strerror(number))


def _renamed_copy_matches(before, after):
    # rename may change ctime only. Ownership, mode, links, full length, mtime,
    # allocation and the exact device/inode must remain those of the held copy.
    return (after[:8]==before[:8] and after[9:]==before[9:]
            and type(after[8]) is int and after[8]>=before[8])


def remove_duplicate(root, descriptor, quarantine=None):
    """Capture the old path privately, prove its inode, then unlink only that copy.

    A race replacing the old path can only move an unexpected file into this
    fresh directory. An unexpected capture is retained, never unlinked or
    automatically moved back over a possibly new original path.
    """
    need(type(descriptor) is dict and set(descriptor) == {'kind', 'release', 'path', 'metadata', 'sha256', 'bytes', 'allocatedBytes', 'keeper'}
         and descriptor['kind'] == 'FAILED_NATIVE_CANDIDATE_JAR_COPY', 'EXACT_SINGLE_FILE_DESCRIPTOR_REQUIRED')
    root = Path(root); target, keeper = duplicate_paths(root, descriptor['release'])
    need(descriptor['path'] == target.relative_to(root).as_posix() and type(descriptor['keeper']) is dict
         and set(descriptor['keeper']) == {'path', 'metadata', 'sha256', 'bytes'}
         and descriptor['keeper']['path'] == keeper.relative_to(root).as_posix(), 'INBOX_KEEPER_HAS_NO_DELETION_API')
    need(describe_duplicate(root, descriptor['release'], descriptor['sha256'], descriptor['bytes']) == descriptor,
         'DUPLICATE_CHANGED_AFTER_PLAN')
    quarantine=reserve_quarantine(root) if quarantine is None else quarantine
    need(type(quarantine) is dict and set(quarantine)=={'directory','path','directoryIdentity'}, 'EXACT_PRIVATE_QUARANTINE_REQUIRED')
    relative=Path(quarantine['directory']);parts=relative.parts
    need((len(parts)==1 or len(parts)==3 and parts[0]=='inbox' and TAG.fullmatch(parts[1]))
         and re.fullmatch(r'native-jar-quarantine-[a-f0-9]{24}',parts[-1])
         and quarantine['path']==(relative/'candidate-app.jar').as_posix(), 'QUARANTINE_OUTSIDE_PRIVATE_ALLOWLIST')
    private=owned_path(root,root/relative,directory=True)
    info=private.lstat()
    need([info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_gid]==quarantine['directoryIdentity']
         and stat.S_IMODE(info.st_mode)==0o700,'PRIVATE_QUARANTINE_IDENTITY_CHANGED')
    with held_file(root, keeper, MAX_JAR) as (kept, keeper_info), os.fdopen(os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as copy:
        copy_info = metadata(os.fstat(copy.fileno()))
        need(keeper_info == descriptor['keeper']['metadata'] and copy_info == descriptor['metadata']
             and hash_stream(kept) == hash_stream(copy) == descriptor['sha256'], 'DUPLICATE_CHANGED_BEFORE_UNLINK')
        stack = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
        quarantine_fd=None
        try:
            quarantine_fd=os.open(private,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            def private_identity():
                value=os.fstat(quarantine_fd);linked=private.lstat()
                need([value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_gid]
                     ==[linked.st_dev,linked.st_ino,linked.st_mode,linked.st_uid,linked.st_gid]
                     ==quarantine['directoryIdentity'],'PRIVATE_QUARANTINE_MOVED')
            private_identity()
            need(not os.listdir(quarantine_fd),'PRIVATE_QUARANTINE_ALREADY_OCCUPIED')
            device = os.fstat(stack[0]).st_dev
            for part in target.relative_to(root).parts[:-1]:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=stack[-1]); stack.append(fd)
                info = os.fstat(fd)
                need(info.st_uid == os.getuid() and info.st_dev == device and not info.st_mode & 0o022,
                     'DELETION_ANCESTOR_CHANGED')
            need(metadata(os.stat(target.name, dir_fd=stack[-1], follow_symlinks=False)) == copy_info
                 and metadata(os.fstat(copy.fileno())) == copy_info and metadata(keeper.lstat()) == keeper_info,
                 'TARGET_OR_KEEPER_MOVED_BEFORE_UNLINK')
            _capture_no_replace(stack[-1],target.name,quarantine_fd,'candidate-app.jar')
            os.fsync(stack[-1]);os.fsync(quarantine_fd)
            captured=metadata(os.stat('candidate-app.jar',dir_fd=quarantine_fd,follow_symlinks=False))
            held_copy=metadata(os.fstat(copy.fileno()))
            need(captured[:2]==copy_info[:2] and captured[:2]!=keeper_info[:2]
                 and captured==held_copy and _renamed_copy_matches(copy_info,captured),
                 'UNEXPECTED_CAPTURED_INODE_RETAINED')
            need(metadata(os.fstat(kept.fileno()))==keeper_info==metadata(keeper.lstat())
                 and hash_stream(kept)==hash_stream(copy)==descriptor['sha256'],
                 'KEEPER_OR_CAPTURE_CHANGED_RETAIN_QUARANTINE')
            need(not target.exists() and not target.is_symlink(),'ORIGINAL_TARGET_REAPPEARED_RETAIN_QUARANTINE')
            private_identity()
            need(os.listdir(quarantine_fd)==['candidate-app.jar']
                 and metadata(os.stat('candidate-app.jar',dir_fd=quarantine_fd,follow_symlinks=False))==captured
                 and metadata(os.fstat(copy.fileno()))==captured
                 and metadata(keeper.lstat())==keeper_info,'CAPTURE_OR_KEEPER_MOVED_RETAIN_QUARANTINE')
            os.unlink('candidate-app.jar',dir_fd=quarantine_fd);os.fsync(quarantine_fd)
            need(not os.listdir(quarantine_fd),'QUARANTINE_REMOVAL_NOT_CONFIRMED')
            need(not target.exists() and not target.is_symlink(), 'EXACT_DUPLICATE_REMOVAL_NOT_CONFIRMED')
            need(metadata(os.fstat(kept.fileno())) == keeper_info == metadata(keeper.lstat())
                 and hash_stream(kept) == descriptor['sha256'], 'KEEPER_CHANGED_AFTER_UNLINK_REVIEW_REQUIRED')
        finally:
            if quarantine_fd is not None:os.close(quarantine_fd)
            for fd in reversed(stack): os.close(fd)
        return {'path': descriptor['path'], 'bytes': descriptor['bytes'], 'allocatedBytes': descriptor['allocatedBytes'],
                'sha256': descriptor['sha256'], 'keeperPath': descriptor['keeper']['path'], 'keeperVerifiedAfter': True,
                'quarantinePath':quarantine['path'],'capturedInodeVerified':True}


def source_proof(root, tag, commit, source_sha, *, builder_helpers=False):
    """Read and authenticate the retained archive; never extract or run it."""
    path = Path(root) / 'inbox' / tag / 'source.tar.gz'
    need(path.exists() or path.is_symlink(), 'OLD_SOURCE_ARCHIVE_MISSING')
    with held_file(root, path, MAX_SOURCE_ARCHIVE) as (stream, signature):
        need(hash_stream(stream, MAX_SOURCE_ARCHIVE) == source_sha, 'OLD_SOURCE_ARCHIVE_SHA_DRIFT')
        stream.seek(0); recipe = None; builder_shas = {}
        builder_names = {'script/docker/compact-build-resources.py', 'script/docker/compact-image-inputs.py'}
        class Bounded:
            def __init__(self, source): self.source, self.total = source, 0
            def read(self, size=-1):
                remaining = MAX_EXPANDED_SOURCE - self.total
                block = self.source.read(remaining + 1 if size < 0 else min(size, remaining + 1))
                self.total += len(block); need(self.total <= MAX_EXPANDED_SOURCE, 'SOURCE_EXPANSION_BOUND_EXCEEDED')
                return block
        with gzip.GzipFile(fileobj=stream, mode='rb') as expanded, tarfile.open(fileobj=Bounded(expanded), mode='r|') as archive:
            count = 0
            for member in archive:
                count += 1; need(count <= 50_000 and 0 <= member.size <= 32 * 1024 ** 2, 'SOURCE_MEMBER_BOUND_EXCEEDED')
                if builder_helpers and member.name in builder_names:
                    key = Path(member.name).name
                    need(key not in builder_shas and member.isfile() and 0 < member.size <= 1024 ** 2,
                         'UNIQUE_OLD_BUILDER_HELPER_REQUIRED')
                    raw = archive.extractfile(member).read(1024 ** 2 + 1)
                    need(len(raw) == member.size, 'OLD_BUILDER_HELPER_TRUNCATED'); builder_shas[key] = digest_bytes(raw)
                if member.name != 'script/jenkins/prepare-compact-fixtures.py': continue
                need(recipe is None and member.isfile() and 0 < member.size <= 1024 ** 2, 'UNIQUE_TRANSPORT_RECIPE_REQUIRED')
                recipe = archive.extractfile(member).read(1024 ** 2 + 1)
                need(len(recipe) == member.size, 'TRANSPORT_RECIPE_TRUNCATED')
            need(archive.pax_headers.get('comment') == commit and recipe is not None, 'FIXED_OLD_SOURCE_COMMIT_REQUIRED')
        try: syntax = ast.parse(recipe)
        except (SyntaxError, RecursionError): raise RetirementError('INVALID_OLD_TRANSPORT_RECIPE') from None
        # This proves the precise reviewed copy location without executing an
        # old script, inferring an arbitrary JAR path or deleting build trees.
        expected_target = ast.dump(ast.parse("uploaded = self.work / 'candidate-app.jar'").body[0], include_attributes=False)
        expected_keeper = ast.dump(ast.parse("jar = canonical(self.inbox / 'application.jar')").body[0], include_attributes=False)
        expected_copy = ast.dump(ast.parse('shutil.copyfile(jar, uploaded)').body[0].value, include_attributes=False)
        proven = False
        for node in ast.walk(syntax):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
            statements = {ast.dump(item, include_attributes=False) for item in ast.walk(node) if isinstance(item, ast.Assign)}
            calls = {ast.dump(item, include_attributes=False) for item in ast.walk(node) if isinstance(item, ast.Call)}
            if expected_target in statements and expected_keeper in statements and expected_copy in calls: proven = True
        need(proven, 'EXACT_REVIEWED_JAR_COPY_RECIPE_REQUIRED')
        proof = {'path': path.relative_to(root).as_posix(), 'metadata': signature, 'bytes': signature[6],
                 'sha256': source_sha, 'transportRecipeSha256': digest_bytes(recipe)}
        if builder_helpers:
            need(set(builder_shas) == {Path(name).name for name in builder_names}, 'ORIGINAL_BUILDER_HELPER_CLOSURE_MISSING')
            proof['builderHelperSha256'] = builder_shas
        return proof


def validate_request(raw_request, request_sha256, expected_current, identity):
    need(type(raw_request) is bytes and type(request_sha256) is str and SHA.fullmatch(request_sha256)
         and digest_bytes(raw_request) == request_sha256, 'AUTHENTICATED_REQUEST_SHA_REQUIRED')
    validate_context(expected_current); request = decode(raw_request)
    need(set(request) == {'schemaVersion', 'kind', 'current', 'identity', 'protectedReleases', 'candidates'}
         and type(request['schemaVersion']) is int and request['schemaVersion'] == 1
         and request['kind'] == KIND + '-request' and request['current'] == expected_current
         and request['identity'] == identity and identity.get('executionLocation') == 'ECS', 'EXACT_CURRENT_REQUEST_REQUIRED')
    protected = request['protectedReleases']; candidates = request['candidates']
    need(type(protected) is list and all(type(tag) is str and TAG.fullmatch(tag) for tag in protected)
         and len(protected) == len(set(protected)) and expected_current['release'] in protected,
         'CURRENT_AND_ROLLBACK_PROTECTION_REQUIRED')
    need(type(candidates) is list and len(candidates) <= 16 and all(type(row) is dict for row in candidates), 'BOUNDED_EXACT_CANDIDATES_REQUIRED')
    tags = []
    for row in candidates:
        need(set(row) == {'release', 'commit', 'sourceSha256', 'controls'}, 'EXACT_NATIVE_CANDIDATE_REQUIRED')
        validate_context({key: row[key] for key in ('release', 'commit', 'sourceSha256')})
        need(row['release'] not in protected and int(TAG.fullmatch(row['release'])[1]) < int(TAG.fullmatch(expected_current['release'])[1]),
             'CURRENT_OR_PROTECTED_NATIVE_BUILD')
        tags.append(row['release'])
    need(len(tags) == len(set(tags)), 'DUPLICATE_CANDIDATE_TAG')
    return request


def expected_control_paths(current_tag, old_tag):
    paths = {role: 'inbox/' + current_tag + '/native-jar-duplicate-controls/' + old_tag + '/' + name
             for role, name in UPLOADED_NAMES.items()}
    base = 'verification/' + old_tag + '/checkout/work/'
    paths.update(artifactPlan='inbox/' + old_tag + '/build-artifacts.json',
                 fixtureOwner=base + 'compact-fixtures-owner.json', fixtureCleanup=base + 'compact-fixtures/cleanup-receipt.json')
    return paths


def admit_historical_controls(root, request, row, *, builder_helpers=False):
    context = {key: row[key] for key in ('release', 'commit', 'sourceSha256')}; tag = row['release']
    controls = row['controls']; names = expected_control_paths(request['current']['release'], tag)
    need(type(controls) is dict and REQUIRED_CONTROLS <= set(controls) <= REQUIRED_CONTROLS | OPTIONAL_CONTROLS,
         'COMPLETE_AUTHENTICATED_CONTROL_REFERENCES_REQUIRED')
    raw_docs, bindings = {}, {}
    for role, reference in controls.items():
        need(type(reference) is dict and set(reference) == {'path', 'bytes', 'sha256'} and reference['path'] == names[role]
             and type(reference['bytes']) is int and 0 < reference['bytes'] <= MAX_CONTROL
             and type(reference['sha256']) is str and SHA.fullmatch(reference['sha256']), 'EXACT_CONTROL_PATH_AND_SHA_REQUIRED')
        need((Path(root) / reference['path']).exists() or (Path(root) / reference['path']).is_symlink(),
             'REQUIRED_CONTROL_MISSING_' + role.upper())
        with held_file(root, Path(root) / reference['path'], MAX_CONTROL) as (stream, signature):
            raw = stream.read(MAX_CONTROL + 1)
            need(len(raw) == reference['bytes'] and digest_bytes(raw) == reference['sha256'], 'RAW_CONTROL_BYTES_DRIFT')
            raw_docs[role] = raw; bindings[role] = {**reference, 'metadata': signature}
    evidence = validate_control_documents(raw_docs, context, request['identity'])
    need(evidence['work'] == str(Path(root) / 'verification' / tag / 'checkout/work/compact-fixtures'), 'FIXTURE_OWNER_OUTSIDE_EXACT_OLD_ATTEMPT')
    original_source = (source_proof(root, tag, context['commit'], context['sourceSha256'], builder_helpers=True)
                       if builder_helpers else source_proof(root, tag, context['commit'], context['sourceSha256']))
    result = {'context': context, 'evidence': evidence, 'controls': bindings, 'sourceArchive': original_source}
    if builder_helpers:
        # Original owner contains a root password. Only these nonsecret control
        # fields may enter a plan or receipt; original bytes remain private.
        owner, cleanup = decode(raw_docs['fixtureOwner']), decode(raw_docs['fixtureCleanup'])
        result['fixtureOwner'] = {key: owner.get(key) for key in ('schemaVersion', 'kind', 'release', 'commit',
            'sourceSha256', 'identity', 'phase', 'token', 'work', 'containerId', 'sourceContainerId',
            'dataDirectory', 'containerName', 'image', 'port')}
        result['fixtureCleanup'] = {key: cleanup.get(key) for key in ('schemaVersion', 'kind', 'release', 'commit',
            'sourceSha256', 'identity', 'status', 'errors', 'containerId', 'sourceContainerUntouched',
            'dataDirectoryRetained', 'sourceDumpAndEvidenceRetained')}
    return result


def admit_candidate(root, request, row, quiescence):
    admitted = admit_historical_controls(root, request, row)
    context, evidence = admitted['context'], admitted['evidence']; tag = row['release']
    # The adapter must call the existing fixed cleanup.quiescent with a fresh
    # docker_snapshot. No weaker path-only or stopped-container exception is
    # implemented by this new library.
    need(callable(quiescence), 'ACTUAL_STRICT_QUIESCENCE_ADAPTER_REQUIRED')
    need(quiescence(Path(root) / 'verification' / tag / 'checkout', tag, evidence['ownerToken']) is None,
         'STRICT_QUIESCENCE_MUST_RETURN_ONLY_AFTER_SUCCESS')
    target = describe_duplicate(root, tag, evidence['jarSha256'], evidence['jarBytes'])
    return {'context': context, 'jenkinsResult': evidence['jenkinsResult'], 'controls': admitted['controls'],
            'sourceArchive': admitted['sourceArchive'], 'ownerToken': evidence['ownerToken'], 'target': target}


@contextmanager
def attempt_lock(root, tag):
    import fcntl
    directory = owned_path(root, Path(root) / 'verification' / tag, directory=True)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        need(metadata(os.fstat(fd)) == metadata(directory.lstat()), 'OLD_ATTEMPT_MOVED_BEFORE_LOCK')
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RetirementError('OLD_ATTEMPT_LOCK_HELD') from None
        yield
    finally: os.close(fd)


@contextmanager
def controller_lock(root):
    import fcntl
    root = owned_path(root, Path(root), directory=True)
    path = root / '.native-jar-duplicate-retirement.lock'
    with os.fdopen(os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600), 'r+b') as stream:
        info = os.fstat(stream.fileno())
        need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
             and stat.S_IMODE(info.st_mode) == 0o600 and metadata(info) == metadata(path.lstat()), 'PRIVATE_RETIREMENT_LOCK_REQUIRED')
        try: fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RetirementError('RETIREMENT_CONTROLLER_LOCK_HELD') from None
        yield


def plan(root, raw_request, *, request_sha256, expected_current, identity, quiescence):
    """Discover only admitted duplicates; rejection is explicit, never approval."""
    request = validate_request(raw_request, request_sha256, expected_current, identity)
    accepted, skipped = [], []
    with controller_lock(root):
        for row in request['candidates']:
            try:
                with attempt_lock(root, row['release']): accepted.append(admit_candidate(root, request, row, quiescence))
            except (RetirementError, OSError, ValueError, KeyError, TypeError, tarfile.TarError, EOFError) as error:
                skipped.append({'release': row['release'], 'reason': str(error) if isinstance(error, RetirementError) else type(error).__name__})
    result = {'schemaVersion': 1, 'kind': KIND + '-plan', 'requestSha256': request_sha256,
              'current': expected_current, 'identity': identity, 'candidates': accepted, 'skipped': skipped,
              'candidateBytes': sum(row['target']['bytes'] for row in accepted),
              'candidateAllocatedBytes': sum(row['target']['allocatedBytes'] for row in accepted),
              'inboxKeepersPreserved': True, 'deletionPerformed': False}
    need(len(canonical(result)) <= MAX_CONTROL, 'BOUNDED_RETIREMENT_PLAN_REQUIRED')
    return result


def apply(root, raw_request, prepared_plan, *, request_sha256, plan_sha256, expected_current, identity, quiescence):
    """Re-admit every selected input before exact single-file mutation.

    An interrupted/partial result must be reviewed; retry requires a newly
    prepared plan. A prior success is never synthesized for a missing file.
    """
    request = validate_request(raw_request, request_sha256, expected_current, identity)
    need(type(prepared_plan) is dict and type(plan_sha256) is str and SHA.fullmatch(plan_sha256)
         and digest_bytes(canonical(prepared_plan)) == plan_sha256
         and prepared_plan.get('kind') == KIND + '-plan' and prepared_plan.get('requestSha256') == request_sha256
         and prepared_plan.get('current') == expected_current and prepared_plan.get('identity') == identity
         and prepared_plan.get('inboxKeepersPreserved') is True and prepared_plan.get('deletionPerformed') is False,
         'EXACT_APPROVED_PLAN_SHA_REQUIRED')
    selected = prepared_plan.get('candidates')
    need(type(selected) is list and len(selected) <= len(request['candidates'])
         and all(type(row) is dict and type(row.get('context')) is dict for row in selected), 'BOUNDED_SELECTED_PLAN_REQUIRED')
    tags = [row['context']['release'] for row in selected]
    need(len(tags) == len(set(tags)) and set(tags) <= {row['release'] for row in request['candidates']}, 'SELECTED_PLAN_TAG_DRIFT')
    journal_path = Path(root) / 'inbox' / expected_current['release'] / 'native-jar-duplicate-journal.jsonl'
    owned_path(root, journal_path.parent, directory=True)
    deleted, failure, active, mutation_attempted = [], None, None, False
    active_quarantine=None;quarantines=[]
    with controller_lock(root), os.fdopen(os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as journal:
        total = 0
        def record(value):
            nonlocal total
            data = canonical(value) + b'\n'; total += len(data)
            need(total <= MAX_CONTROL, 'RETIREMENT_JOURNAL_LIMIT_EXCEEDED')
            journal.write(data); journal.flush(); os.fsync(journal.fileno())
        before = os.statvfs(root)
        record({'phase': 'STARTED', 'planSha256': plan_sha256, 'requestSha256': request_sha256, 'identity': identity})
        try:
            for candidate in selected:
                active = candidate['context']['release']
                active_quarantine=None
                row = next(row for row in request['candidates'] if row['release'] == active)
                with attempt_lock(root, active):
                    need(admit_candidate(root, request, row, quiescence) == candidate, 'CANDIDATE_CHANGED_AFTER_PLAN')
                    need(quiescence(Path(root) / 'verification' / active / 'checkout', active, candidate['ownerToken']) is None,
                         'STRICT_QUIESCENCE_MUST_RETURN_ONLY_AFTER_SUCCESS')
                    active_quarantine=reserve_quarantine(root,expected_current['release']);quarantines.append(active_quarantine)
                    record({'phase': 'DELETE_STARTED', 'release': active, 'path': candidate['target']['path'],
                            'keeperPath': candidate['target']['keeper']['path'], 'sha256': candidate['target']['sha256'],
                            'quarantinePath':active_quarantine['path']})
                    mutation_attempted = True
                    result = remove_duplicate(root, candidate['target'],quarantine=active_quarantine); deleted.append(result)
                    record({'phase': 'DELETE_FINISHED', **result})
            record({'phase': 'FINISHED', 'deletedFiles': len(deleted)})
        except (RetirementError, OSError, ValueError, KeyError, TypeError, tarfile.TarError, EOFError) as error:
            failure = str(error) if isinstance(error, RetirementError) else type(error).__name__
            record({'phase': 'FAILED_OR_UNKNOWN', 'release': active, 'reason': failure,
                    'completedDeletions': len(deleted), 'mutationAttempted': mutation_attempted,
                    'quarantinePath':active_quarantine['path'] if active_quarantine else None})
        after = os.statvfs(root)
    return {'schemaVersion': 1, 'kind': KIND + '-receipt', 'current': expected_current, 'identity': identity,
            'status': 'FAILED_OR_UNKNOWN' if failure else 'REMOVED' if deleted else 'NO_ACTION',
            'requestSha256': request_sha256, 'planSha256': plan_sha256, 'deleted': deleted, 'failure': failure,
            'mutationAttempted': mutation_attempted, 'lastAttemptedRelease': active,
            'lastQuarantinePath':active_quarantine['path'] if active_quarantine else None,
            'retainedQuarantinePaths':[row['path'] for row in quarantines
                                       if (Path(root)/row['path']).exists() or (Path(root)/row['path']).is_symlink()],
            'journalSha256': digest_bytes(journal_path.read_bytes()),
            'availableBytesBefore': before.f_bavail * before.f_frsize, 'availableBytesAfter': after.f_bavail * after.f_frsize,
            'inboxKeepersPreserved': failure is None, 'sourceArchivesDataAndReportsHaveNoDeletionApi': True}


def private_bytes(root, path, maximum=MAX_CONTROL):
    with held_file(root, path, maximum) as (stream, info):
        need(stat.S_IMODE(info[2]) == 0o600, 'PRIVATE_CONTROL_MODE_REQUIRED')
        raw = stream.read(maximum + 1)
        need(len(raw) == info[6], 'CONTROL_READ_SIZE_DRIFT')
        return raw


def write_new(path, value):
    need(not path.exists() and not path.is_symlink() and path.parent.resolve(strict=True) == path.parent,
         'FRESH_CONTROL_OUTPUT_REQUIRED')
    raw = canonical(value); need(0 < len(raw) <= MAX_CONTROL, 'CONTROL_OUTPUT_BOUND_EXCEEDED')
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return {'file': path.name, 'bytes': len(raw), 'sha256': digest_bytes(raw)}


def fixed_current_source(root, args):
    """Authenticate every import against the current committed source archive."""
    root = Path(root); inbox = root / 'inbox' / args.tag
    source = inbox / ('source.tar.gz' if args.mode == 'Verified' else 'cleanup-source.tar.gz')
    own = Path(__file__).absolute()
    need(own == inbox / 'retire-failed-native-jar-duplicates.py', 'FIXED_CURRENT_INBOX_EXECUTOR_REQUIRED')
    paths = {'script/jenkins/retire-failed-native-jar-duplicates.py': own,
             'script/jenkins/cleanup-ecs-builds.py': inbox / 'cleanup-ecs-builds.py',
             'script/jenkins/verify-remote.py': inbox / 'verify-remote.py',
             'script/docker/compact-build-resources.py': inbox / 'compact-build-resources.py'}
    expected = {}
    for name, path in paths.items():
        raw = private_bytes(root, path, 1024 ** 2); expected[name] = digest_bytes(raw)
    with held_file(root, source, MAX_SOURCE_ARCHIVE) as (stream, _info):
        need(hash_stream(stream, MAX_SOURCE_ARCHIVE) == args.source_sha256, 'FIXED_CURRENT_SOURCE_SHA_DRIFT')
        stream.seek(0)
        class Bounded:
            def __init__(self, source): self.source, self.total = source, 0
            def read(self, size=-1):
                remain = MAX_EXPANDED_SOURCE - self.total
                raw = self.source.read(remain + 1 if size < 0 else min(size, remain + 1)); self.total += len(raw)
                need(self.total <= MAX_EXPANDED_SOURCE, 'CURRENT_SOURCE_EXPANSION_EXCEEDED'); return raw
        seen = set(); count = 0
        with gzip.GzipFile(fileobj=stream, mode='rb') as expanded, tarfile.open(fileobj=Bounded(expanded), mode='r|') as archive:
            for member in archive:
                count += 1; need(count <= 50_000 and 0 <= member.size <= 32 * 1024 ** 2, 'CURRENT_SOURCE_MEMBER_BOUND_EXCEEDED')
                if member.name not in paths: continue
                need(member.name not in seen and member.isfile() and 0 < member.size <= 1024 ** 2,
                     'UNIQUE_CURRENT_SOURCE_HELPER_REQUIRED')
                raw = archive.extractfile(member).read(1024 ** 2 + 1)
                need(len(raw) == member.size and digest_bytes(raw) == expected[member.name], 'CURRENT_HELPER_DIFFERS_FROM_FIXED_SOURCE')
                seen.add(member.name)
            need(archive.pax_headers.get('comment') == args.commit and seen == set(paths), 'CURRENT_SOURCE_COMMIT_AND_CLOSURE_REQUIRED')
    modules = {}
    for name, filename in (('cleanup', 'cleanup-ecs-builds.py'), ('verifier', 'verify-remote.py'),
                           ('builder', 'compact-build-resources.py')):
        spec = importlib.util.spec_from_file_location('native_jar_fixed_' + name, inbox / filename)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); modules[name] = module
    return modules


def admitted_current(args):
    need(sys.platform == 'linux' and os.getuid() == os.geteuid() == 1000, 'ACTUAL_ECS_UID_1000_REQUIRED')
    current = {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256}; validate_context(current)
    root = Path(args.root)
    need(root.is_absolute() and len(root.parts) > 2 and root.parts[1] in ('home', 'srv', 'opt'), 'FIXED_ECS_CI_ROOT_REQUIRED')
    modules = fixed_current_source(root, args); cleanup, verifier = modules['cleanup'], modules['verifier']
    identity = verifier.ecs_identity(args.instance_id, args.machine_id)
    need(type(args.current_receipt_sha256) is str and SHA.fullmatch(args.current_receipt_sha256), 'CURRENT_RECEIPT_SHA_REQUIRED')
    if args.mode == 'Verified':
        path = root / 'verification' / args.tag / 'verification-receipt.json'
        raw = private_bytes(root, path); need(digest_bytes(raw) == args.current_receipt_sha256, 'CURRENT_PASS_RAW_SHA_DRIFT')
        record = decode(raw)
        need(all(record.get(key) == value for key, value in {**current, 'identity': identity, 'scope': 'source',
             'status': 'PASS', 'verificationExitCode': 0}.items()) and record.get('finishedAt'), 'CURRENT_SOURCE_PASS_REQUIRED')
        custody = {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256, 'identity': identity,
                   'verificationReceiptSha256': digest_bytes(raw), 'reportCatalogSha256': cleanup.sha(cleanup.canonical(record['reportFiles'])),
                   'reportFiles': len(record['reportFiles']), 'reportBytes': sum(row['bytes'] for row in record['reportFiles']),
                   'originalEvidenceArchive': None}
        cleanup.evidence_binding(root, custody, identity, verifier)
    else:
        path = root / 'inbox' / args.tag / 'native-jar-duplicate-maintenance-package.json'
        raw = private_bytes(root, path); need(digest_bytes(raw) == args.current_receipt_sha256, 'MAINTENANCE_PACKAGE_RAW_SHA_DRIFT')
        package = decode(raw)
        expected = {'schema': 1, 'kind': 'doorhandle-maintenance-source', 'action': 'reclaim-build-outputs',
                    'maintenanceOnly': True, 'testsExecuted': False, 'applicationBuilt': False, **current}
        need(set(package) == set(expected) | {'sourceBytes'} and all(package.get(key) == value for key, value in expected.items())
             and type(package['schema']) is int and all(type(package[key]) is bool for key in ('maintenanceOnly', 'testsExecuted', 'applicationBuilt'))
             and type(package['sourceBytes']) is int and package['sourceBytes'] == (root / 'inbox' / args.tag / 'cleanup-source.tar.gz').stat().st_size
             and not (root / 'verification' / args.tag / 'verification-receipt.json').exists(), 'EXACT_SOURCE_ONLY_MAINTENANCE_REQUIRED')
    def quiescence(checkout, tag, token):
        cleanup.quiescent({'checkout': checkout, 'token': token}, tag, cleanup.docker_snapshot())
    return root, current, identity, quiescence, modules


def approved_request(raw, checksum, current, identity):
    request = validate_request(raw, checksum, current, identity)
    need(all(APPROVED_OLD.get(row['release']) == row['commit'] for row in request['candidates']), 'ONLY_REVIEWED_OLD_ATTEMPTS_ALLOWED')
    return request


def builder_docker(*arguments):
    result = subprocess.run(['/usr/bin/docker', *arguments], capture_output=True, timeout=20,
                            env={key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
    need(result.returncode == 0 and len(result.stdout) <= MAX_CONTROL, 'HISTORICAL_BUILDER_DOCKER_OPERATION_FAILED')
    return result.stdout


def builder_container_ids():
    ids = builder_docker('ps', '-aq', '--no-trunc').decode('ascii').split()
    need(len(ids) <= 256 and len(ids) == len(set(ids)) and all(SHA.fullmatch(cid) for cid in ids),
         'BOUNDED_ACTUAL_CONTAINER_IDS_REQUIRED')
    return ids


def builder_references(root, historical, descriptor, cleanup, builder, fixture=None):
    """Exclude only the fully admitted objects about to retire, never JAR guards."""
    cid = descriptor['containerId']; tag = historical['context']['release']
    retiring = {cid: 'doorhandle-builder-' + descriptor['ownerToken']}
    if fixture is not None:
        need(fixture['containerId'] != cid, 'MYSQL_FIXTURE_AND_BUILDER_ID_COLLISION')
        retiring[fixture['containerId']] = 'doorhandle-compact-fixture-' + fixture['ownerToken']
    containers = cleanup.docker_snapshot()
    need(all(sum(row[0] == selected for row in containers) == 1 for selected in retiring), 'EXACT_HISTORICAL_RETIRING_OBJECT_MISSING')
    try:
        cleanup.quiescent({'checkout': Path(root) / 'verification' / tag / 'checkout',
                           'token': historical['evidence']['ownerToken']}, tag,
                          [row for row in containers if row[0] not in retiring])
    except ValueError as error:
        raise RetirementError('HISTORICAL_OBJECTS_NOT_QUIESCENT_' + cleanup.failure_guard_code(error)) from None
    for other in builder_container_ids():
        row = builder.historical_builder_inspect(builder_docker('inspect', other)); host = row.get('HostConfig') or {}
        values = [host.get(key, '') for key in ('NetworkMode', 'PidMode', 'IpcMode')]
        values += list(host.get('VolumesFrom') or []) + list(host.get('Links') or [])
        for value in values:
            need(type(value) is str, 'CONTAINER_REFERENCE_METADATA_INVALID')
            parts = value.replace('/', ':').split(':')
            need(not any(item == name or re.fullmatch(r'[a-f0-9]+', item) and selected.startswith(item)
                         for item in parts for selected, name in retiring.items()),
                 'ANOTHER_CONTAINER_REFERENCES_HISTORICAL_BUILDER')
    # No fallback kills or cgroup writes. A still-populated retained group stops
    # maintenance even if Docker reports an exited root process.
    for selected in retiring:
        for group in (Path('/sys/fs/cgroup/system.slice') / ('docker-' + selected + '.scope'), Path('/sys/fs/cgroup/docker') / selected):
            if group.exists():
                need(group.resolve(strict=True) == group and not group.is_symlink(), 'BUILDER_CGROUP_LINK_REJECTED')
                value = (group / 'cgroup.events').read_bytes()
                need(len(value) <= 4096 and dict(line.split() for line in value.decode('ascii').splitlines()).get('populated') == '0',
                     'HISTORICAL_BUILDER_CGROUP_REMAINS_POPULATED')


def fixture_data_metadata(root, path):
    """Stat the UID999 directory entry only; never open its private contents."""
    path = Path(path); parent = owned_path(root, path.parent, directory=True)
    need(path.name == 'mysql-data' and path.resolve(strict=True) == path, 'EXACT_RETAINED_MYSQL_DIRECTORY_REQUIRED')
    fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        need(metadata(os.fstat(fd)) == metadata(parent.lstat()), 'MYSQL_DIRECTORY_PARENT_MOVED')
        value = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
        need(stat.S_ISDIR(value.st_mode) and not stat.S_ISLNK(value.st_mode), 'RETAINED_MYSQL_DATA_DIRECTORY_LINK_REJECTED')
        return [value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid]
    finally: os.close(fd)


def capture_fixture(root, request, historical, builder):
    owner, cleanup = historical['fixtureOwner'], historical['fixtureCleanup']; cid = owner.get('containerId')
    if cid is None: return None
    need(type(cid) is str and SHA.fullmatch(cid), 'ORIGINAL_MYSQL_FIXTURE_ID_REQUIRED')
    if cid not in builder_container_ids(): return None
    raw = builder_docker('inspect', cid)
    descriptor = builder.historical_mysql_fixture_descriptor(root, historical['context'], request['identity'], owner, cleanup,
        builder.historical_builder_inspect(raw), fixture_data_metadata(root, owner['dataDirectory']))
    descriptor['rawInspectSha256'] = digest_bytes(raw)
    return descriptor


def capture_builder(root, request, row, builder):
    historical = admit_historical_controls(root, request, row, builder_helpers=True)
    directory = Path(root) / 'inbox' / row['release'] / 'candidate-build-tools'
    controls, raw = {}, {}
    for role, filename in (('tools', 'tools.json'), ('summary', 'resource-summary.json'),
                            ('measurement', 'official-layer-measurements.json')):
        path = directory / filename
        with held_file(root, path, MAX_CONTROL) as (stream, signature):
            content = stream.read(MAX_CONTROL + 1)
            need(0 < len(content) <= MAX_CONTROL, 'BOUNDED_ORIGINAL_BUILDER_CONTROL_REQUIRED')
            raw[role] = content
            controls[role] = {'path': path.relative_to(root).as_posix(), 'bytes': len(content),
                              'sha256': digest_bytes(content), 'metadata': signature}
    need(digest_bytes(raw['tools']) == APPROVED_BUILDER_TOOLS.get(row['release']),
         'HISTORICAL_BUILDER_TOOLS_DIFFERS_FROM_ORIGINAL_JENKINS_REFERENCE')
    summary = decode(raw['summary']); cid = summary.get('cleanup', {}).get('builderContainerId')
    need(type(cid) is str and SHA.fullmatch(cid), 'ORIGINAL_BUILDER_CONTAINER_ID_REQUIRED')
    inspected = builder_docker('inspect', cid); actual = builder.historical_builder_inspect(inspected)
    descriptor = builder.historical_builder_descriptor(root, historical['context'], request['identity'],
        raw['tools'], raw['summary'], raw['measurement'], historical['sourceArchive']['builderHelperSha256'], actual)
    fixture = capture_fixture(root, request, historical, builder)
    return {'historical': historical, 'builderControls': controls, 'descriptor': descriptor, 'fixture': fixture}, inspected


def plan_builders(root, raw_request, *, request_sha256, expected_current, identity, modules):
    request = approved_request(raw_request, request_sha256, expected_current, identity)
    accepted, skipped = [], []; builder, cleanup = modules['builder'], modules['cleanup']
    directory = Path(root) / 'inbox' / expected_current['release'] / 'native-builder-retirement-inspect'
    with controller_lock(root):
        for row in request['candidates']:
            try:
                with attempt_lock(root, row['release']):
                    value, inspected = capture_builder(root, request, row, builder)
                    builder_references(root, value['historical'], value['descriptor'], cleanup, builder, value['fixture'])
                    if not directory.exists(): directory.mkdir(mode=0o700)
                    owned_path(root, directory, directory=True)
                    path = directory / (row['release'] + '.json')
                    need(not path.exists() and not path.is_symlink(), 'FRESH_ORIGINAL_BUILDER_INSPECTION_REQUIRED')
                    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as stream:
                        stream.write(inspected); stream.flush(); os.fsync(stream.fileno())
                    value['inspection'] = {'path': path.relative_to(root).as_posix(), 'bytes': len(inspected),
                                           'sha256': digest_bytes(inspected), 'metadata': metadata(path.lstat())}
                    accepted.append(value)
            except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, EOFError) as error:
                skipped.append({'release': row['release'], 'reason': str(error) if isinstance(error, RetirementError)
                                or getattr(error, 'doorhandle_public_resource_error', False) else type(error).__name__})
    return {'schemaVersion': 1, 'kind': 'doorhandle-historical-builder-retirement-plan', 'current': expected_current,
            'identity': identity, 'requestSha256': request_sha256, 'candidates': accepted, 'skipped': skipped,
            'deletionPerformed': False, 'imagesPreserved': True, 'volumesPreserved': True, 'directoriesPreserved': True}


def apply_builders(root, raw_request, prepared, *, request_sha256, plan_sha256, expected_current, identity, modules):
    request = approved_request(raw_request, request_sha256, expected_current, identity)
    need(digest_bytes(canonical(prepared)) == plan_sha256 and prepared.get('kind') == 'doorhandle-historical-builder-retirement-plan'
         and prepared.get('current') == expected_current and prepared.get('identity') == identity
         and prepared.get('requestSha256') == request_sha256 and prepared.get('deletionPerformed') is False,
         'EXACT_HISTORICAL_BUILDER_PLAN_REQUIRED')
    selected = prepared.get('candidates'); rows = {row['release']: row for row in request['candidates']}
    need(type(selected) is list and len(selected) <= len(rows)
         and len({row['descriptor']['release'] for row in selected}) == len(selected)
         and all(row['descriptor']['release'] in rows for row in selected), 'BOUNDED_HISTORICAL_BUILDER_SELECTION_REQUIRED')
    builder, cleanup = modules['builder'], modules['cleanup']; removed, retired_fixtures, failure = [], [], None
    journal_path = Path(root) / 'inbox' / expected_current['release'] / 'native-builder-retirement-journal.jsonl'
    with controller_lock(root), os.fdopen(os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as journal:
        def record(value):
            journal.write(canonical(value) + b'\n'); journal.flush(); os.fsync(journal.fileno())
        record({'phase': 'STARTED', 'planSha256': plan_sha256, 'requestSha256': request_sha256})
        active = None
        try:
            for candidate in selected:
                active = candidate['descriptor']['release']
                with attempt_lock(root, active):
                    current, _inspected = capture_builder(root, request, rows[active], builder)
                    need(current == {key: value for key, value in candidate.items() if key != 'inspection'},
                         'HISTORICAL_BUILDER_OR_CONTROLS_CHANGED_AFTER_PLAN')
                    reference = candidate['inspection']; path = Path(root) / reference['path']
                    with held_file(root, path, MAX_CONTROL) as (stream, signature):
                        raw = stream.read(MAX_CONTROL + 1)
                        need(signature == reference['metadata'] and len(raw) == reference['bytes']
                             and digest_bytes(raw) == reference['sha256']
                             and digest_bytes(builder.encoded(builder.historical_builder_inspect(raw))) == candidate['descriptor']['inspectSha256'],
                             'FROZEN_HISTORICAL_BUILDER_INSPECTION_DRIFT')
                    fixture = current['fixture']
                    if fixture is not None:
                        record({'phase': 'MYSQL_OBJECT_REMOVE_STARTED', 'release': active, 'containerId': fixture['containerId'],
                                'inspectSha256': fixture['inspectSha256'], 'rawInspectSha256': fixture['rawInspectSha256'],
                                'dataDirectory': fixture['dataDirectory'], 'dataMetadata': fixture['dataMetadata']})
                        retired = builder.historical_mysql_fixture_remove(fixture, lambda cid: builder_docker('inspect', cid),
                            lambda cid: builder_docker('rm', cid), builder_container_ids,
                            lambda _cid: builder_references(root, current['historical'], current['descriptor'], cleanup, builder, fixture),
                            lambda: fixture_data_metadata(root, fixture['dataDirectory']))
                        retired_fixtures.append(retired); record({'phase': 'MYSQL_OBJECT_REMOVED', **retired})
                    record({'phase': 'REMOVE_STARTED', 'release': active, 'containerId': candidate['descriptor']['containerId'],
                            'inspection': reference})
                    value = builder.historical_builder_remove(candidate['descriptor'],
                        lambda cid: builder.historical_builder_inspect(builder_docker('inspect', cid)),
                        lambda cid: builder_docker('rm', cid), builder_container_ids,
                        lambda _cid: builder_references(root, current['historical'], current['descriptor'], cleanup, builder))
                    removed.append(value); record({'phase': 'REMOVED', **value})
        except Exception as error:
            failure = {'release': active, 'reason': str(error) if isinstance(error, RetirementError)
                       or getattr(error, 'doorhandle_public_resource_error', False) else type(error).__name__}
            record({'phase': 'FAILED_OR_UNKNOWN', **failure})
        record({'phase': 'FINISHED', 'removedContainers': len(removed)})
    return {'schemaVersion': 1, 'kind': 'doorhandle-historical-builder-retirement-receipt',
            'status': 'FAILED_OR_UNKNOWN' if failure else 'REMOVED' if removed else 'NO_ACTION',
            'current': expected_current, 'identity': identity, 'requestSha256': request_sha256, 'planSha256': plan_sha256,
            'removed': removed, 'retiredMysqlObjects': retired_fixtures, 'mysqlDataDirectoriesPreserved': True,
            'failure': failure, 'skipped': prepared['skipped'], 'imagesPreserved': True,
            'volumesPreserved': True, 'directoriesPreserved': True, 'jarDeletionPerformed': False}


def capture_request(root, raw_local_spec, *, local_spec_sha256, expected_current, identity):
    spec = approved_request(raw_local_spec, local_spec_sha256, expected_current, identity)
    accepted, skipped = [], []
    for row in spec['candidates']:
        try:
            names = expected_control_paths(expected_current['release'], row['release']); refs = row['controls']
            need(type(refs) is dict and {'buildXml', 'release'} <= set(refs) <= set(UPLOADED_NAMES), 'ACTUAL_LOCAL_TERMINAL_AND_RELEASE_REQUIRED')
            merged = dict(refs)
            for role, ref in refs.items():
                need(type(ref) is dict and set(ref) == {'path', 'bytes', 'sha256'} and ref['path'] == names[role], 'FIXED_LOCAL_CONTROL_LOCATION_REQUIRED')
                raw = private_bytes(root, Path(root) / ref['path'])
                need(len(raw) == ref['bytes'] and digest_bytes(raw) == ref['sha256'], 'UPLOADED_ORIGINAL_LOCAL_CONTROL_DRIFT')
            for role in ('artifactPlan', 'fixtureOwner', 'fixtureCleanup'):
                path = Path(root) / names[role]
                need(path.exists() or path.is_symlink(), 'REQUIRED_ECS_CONTROL_MISSING_' + role.upper())
                raw = private_bytes(root, path)
                merged[role] = {'path': names[role], 'bytes': len(raw), 'sha256': digest_bytes(raw)}
            accepted.append({**row, 'controls': merged})
        except (RetirementError, OSError, ValueError, KeyError, TypeError) as error:
            skipped.append({'release': row['release'], 'reason': str(error) if isinstance(error, RetirementError) else type(error).__name__})
    request = {**spec, 'candidates': accepted}
    return request, skipped


def cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('capture-request', 'plan-builders', 'apply-builders', 'plan', 'apply', 'inspect'), required=True)
    parser.add_argument('--mode', choices=('Verified', 'Maintenance'), required=True)
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id', 'current-receipt-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--local-spec-sha256'); parser.add_argument('--request-sha256'); parser.add_argument('--plan-sha256')
    args = parser.parse_args(argv)
    try:
        root, current, identity, quiescence, modules = admitted_current(args); inbox = root / 'inbox' / args.tag
        request_file = inbox / 'native-jar-duplicate-request.json'; plan_file = inbox / 'native-jar-duplicate-plan.json'
        receipt_file = inbox / 'native-jar-duplicate-receipt.json'; capture_file = inbox / 'native-jar-duplicate-capture.json'
        builder_plan_file = inbox / 'native-builder-retirement-plan.json'; builder_receipt_file = inbox / 'native-builder-retirement-receipt.json'
        if args.phase == 'capture-request':
            raw = private_bytes(root, inbox / 'native-jar-duplicate-local-spec.json')
            request, skipped = capture_request(root, raw, local_spec_sha256=args.local_spec_sha256, expected_current=current, identity=identity)
            result = {'status': 'CAPTURED', 'current': current, 'identity': identity,
                      'request': write_new(request_file, request), 'skipped': skipped}
            result['capture'] = write_new(capture_file, result)
        elif args.phase == 'inspect':
            files = {}
            for name, path in (('request', request_file), ('plan', plan_file), ('receipt', receipt_file), ('capture', capture_file),
                               ('journal', inbox / 'native-jar-duplicate-journal.jsonl'), ('builderPlan', builder_plan_file),
                               ('builderReceipt', builder_receipt_file), ('builderJournal', inbox / 'native-builder-retirement-journal.jsonl')):
                if path.exists():
                    raw = private_bytes(root, path); files[name] = {'file': path.name, 'bytes': len(raw), 'sha256': digest_bytes(raw)}
            result = {'status': 'INSPECTED', 'current': current, 'identity': identity, 'files': files}
        elif args.phase in ('plan-builders', 'apply-builders'):
            raw = private_bytes(root, request_file); approved_request(raw, args.request_sha256, current, identity)
            options = {'request_sha256': args.request_sha256, 'expected_current': current, 'identity': identity, 'modules': modules}
            if args.phase == 'plan-builders':
                value = plan_builders(root, raw, **options)
                result = {'status': 'PLANNED', 'current': current, 'identity': identity,
                          'plan': write_new(builder_plan_file, value), 'skipped': value['skipped']}
            else:
                plan_raw = private_bytes(root, builder_plan_file)
                need(digest_bytes(plan_raw) == args.plan_sha256, 'ORIGINAL_BUILDER_PLAN_RAW_SHA_DRIFT')
                value = apply_builders(root, raw, decode(plan_raw), plan_sha256=args.plan_sha256, **options)
                result = {'status': value['status'], 'current': current, 'identity': identity,
                          'receipt': write_new(builder_receipt_file, value)}
        else:
            raw = private_bytes(root, request_file); approved_request(raw, args.request_sha256, current, identity)
            options = {'request_sha256': args.request_sha256, 'expected_current': current, 'identity': identity, 'quiescence': quiescence}
            if args.phase == 'plan':
                value = plan(root, raw, **options)
                result = {'status': 'PLANNED', 'current': current, 'identity': identity, 'plan': write_new(plan_file, value),
                          'candidateBytes': value['candidateBytes'], 'candidateAllocatedBytes': value['candidateAllocatedBytes'], 'skipped': value['skipped']}
            else:
                plan_raw = private_bytes(root, plan_file)
                need(digest_bytes(plan_raw) == args.plan_sha256, 'ORIGINAL_PLAN_RAW_SHA_DRIFT')
                value = apply(root, raw, decode(plan_raw), plan_sha256=args.plan_sha256, **options)
                result = {'status': value['status'], 'current': current, 'identity': identity, 'receipt': write_new(receipt_file, value)}
        print(json.dumps(result, sort_keys=True))
        return 0 if result['status'] != 'FAILED_OR_UNKNOWN' else 2
    except Exception as error:
        location = error.__traceback__
        while location is not None and location.tb_next is not None: location = location.tb_next
        point = None if location is None else {'file': Path(location.tb_frame.f_code.co_filename).name[:96],
            'function': location.tb_frame.f_code.co_name[:96], 'line': location.tb_lineno}
        print(json.dumps({'status': 'REJECTED', 'phase': args.phase, 'errorType': type(error).__name__, 'location': point,
                          'reason': str(error) if isinstance(error, RetirementError)
                          or getattr(error, 'doorhandle_public_resource_error', False) else 'NATIVE_DUPLICATE_ADMISSION_FAILED'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
