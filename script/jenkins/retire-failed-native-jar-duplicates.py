"""Retire one exact, proven failed-native JAR copy while retaining its keeper.

The CLI authenticates fixed current source and ECS identity before importing
the existing strict cleanup admission library. The local Jenkins controller
authenticates the request SHA and the original C/D control-file byte provenance.
No source archive, inbox artifact, database, report, image or directory has a
deletion API here. Historical metadata never substitutes for keeper bytes.
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
import stat
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


def remove_duplicate(root, descriptor):
    """Unlink only candidate-app.jar; the exact inbox keeper stays open throughout."""
    need(type(descriptor) is dict and set(descriptor) == {'kind', 'release', 'path', 'metadata', 'sha256', 'bytes', 'allocatedBytes', 'keeper'}
         and descriptor['kind'] == 'FAILED_NATIVE_CANDIDATE_JAR_COPY', 'EXACT_SINGLE_FILE_DESCRIPTOR_REQUIRED')
    root = Path(root); target, keeper = duplicate_paths(root, descriptor['release'])
    need(descriptor['path'] == target.relative_to(root).as_posix() and type(descriptor['keeper']) is dict
         and set(descriptor['keeper']) == {'path', 'metadata', 'sha256', 'bytes'}
         and descriptor['keeper']['path'] == keeper.relative_to(root).as_posix(), 'INBOX_KEEPER_HAS_NO_DELETION_API')
    need(describe_duplicate(root, descriptor['release'], descriptor['sha256'], descriptor['bytes']) == descriptor,
         'DUPLICATE_CHANGED_AFTER_PLAN')
    with held_file(root, keeper, MAX_JAR) as (kept, keeper_info), os.fdopen(os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as copy:
        copy_info = metadata(os.fstat(copy.fileno()))
        need(keeper_info == descriptor['keeper']['metadata'] and copy_info == descriptor['metadata']
             and hash_stream(kept) == hash_stream(copy) == descriptor['sha256'], 'DUPLICATE_CHANGED_BEFORE_UNLINK')
        stack = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
        try:
            device = os.fstat(stack[0]).st_dev
            for part in target.relative_to(root).parts[:-1]:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=stack[-1]); stack.append(fd)
                info = os.fstat(fd)
                need(info.st_uid == os.getuid() and info.st_dev == device and not info.st_mode & 0o022,
                     'DELETION_ANCESTOR_CHANGED')
            need(metadata(os.stat(target.name, dir_fd=stack[-1], follow_symlinks=False)) == copy_info
                 and metadata(os.fstat(copy.fileno())) == copy_info and metadata(keeper.lstat()) == keeper_info,
                 'TARGET_OR_KEEPER_MOVED_BEFORE_UNLINK')
            os.unlink(target.name, dir_fd=stack[-1]); os.fsync(stack[-1])
            need(not target.exists() and not target.is_symlink(), 'EXACT_DUPLICATE_REMOVAL_NOT_CONFIRMED')
            need(metadata(os.fstat(kept.fileno())) == keeper_info == metadata(keeper.lstat())
                 and hash_stream(kept) == descriptor['sha256'], 'KEEPER_CHANGED_AFTER_UNLINK_REVIEW_REQUIRED')
        finally:
            for fd in reversed(stack): os.close(fd)
        return {'path': descriptor['path'], 'bytes': descriptor['bytes'], 'allocatedBytes': descriptor['allocatedBytes'],
                'sha256': descriptor['sha256'], 'keeperPath': descriptor['keeper']['path'], 'keeperVerifiedAfter': True}


def source_proof(root, tag, commit, source_sha):
    """Read and authenticate the retained archive; never extract or run it."""
    path = Path(root) / 'inbox' / tag / 'source.tar.gz'
    need(path.exists() or path.is_symlink(), 'OLD_SOURCE_ARCHIVE_MISSING')
    with held_file(root, path, MAX_SOURCE_ARCHIVE) as (stream, signature):
        need(hash_stream(stream, MAX_SOURCE_ARCHIVE) == source_sha, 'OLD_SOURCE_ARCHIVE_SHA_DRIFT')
        stream.seek(0); recipe = None
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
        return {'path': path.relative_to(root).as_posix(), 'metadata': signature, 'bytes': signature[6],
                'sha256': source_sha, 'transportRecipeSha256': digest_bytes(recipe)}


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


def admit_candidate(root, request, row, quiescence):
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
    original_source = source_proof(root, tag, context['commit'], context['sourceSha256'])
    # The adapter must call the existing fixed cleanup.quiescent with a fresh
    # docker_snapshot. No weaker path-only or stopped-container exception is
    # implemented by this new library.
    need(callable(quiescence), 'ACTUAL_STRICT_QUIESCENCE_ADAPTER_REQUIRED')
    need(quiescence(Path(root) / 'verification' / tag / 'checkout', tag, evidence['ownerToken']) is None,
         'STRICT_QUIESCENCE_MUST_RETURN_ONLY_AFTER_SUCCESS')
    target = describe_duplicate(root, tag, evidence['jarSha256'], evidence['jarBytes'])
    return {'context': context, 'jenkinsResult': evidence['jenkinsResult'], 'controls': bindings,
            'sourceArchive': original_source, 'ownerToken': evidence['ownerToken'], 'target': target}


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
                row = next(row for row in request['candidates'] if row['release'] == active)
                with attempt_lock(root, active):
                    need(admit_candidate(root, request, row, quiescence) == candidate, 'CANDIDATE_CHANGED_AFTER_PLAN')
                    need(quiescence(Path(root) / 'verification' / active / 'checkout', active, candidate['ownerToken']) is None,
                         'STRICT_QUIESCENCE_MUST_RETURN_ONLY_AFTER_SUCCESS')
                    record({'phase': 'DELETE_STARTED', 'release': active, 'path': candidate['target']['path'],
                            'keeperPath': candidate['target']['keeper']['path'], 'sha256': candidate['target']['sha256']})
                    mutation_attempted = True
                    result = remove_duplicate(root, candidate['target']); deleted.append(result)
                    record({'phase': 'DELETE_FINISHED', **result})
            record({'phase': 'FINISHED', 'deletedFiles': len(deleted)})
        except (RetirementError, OSError, ValueError, KeyError, TypeError, tarfile.TarError, EOFError) as error:
            failure = str(error) if isinstance(error, RetirementError) else type(error).__name__
            record({'phase': 'FAILED_OR_UNKNOWN', 'release': active, 'reason': failure,
                    'completedDeletions': len(deleted), 'mutationAttempted': mutation_attempted})
        after = os.statvfs(root)
    return {'schemaVersion': 1, 'kind': KIND + '-receipt', 'current': expected_current, 'identity': identity,
            'status': 'FAILED_OR_UNKNOWN' if failure else 'REMOVED' if deleted else 'NO_ACTION',
            'requestSha256': request_sha256, 'planSha256': plan_sha256, 'deleted': deleted, 'failure': failure,
            'mutationAttempted': mutation_attempted, 'lastAttemptedRelease': active,
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
             'script/jenkins/verify-remote.py': inbox / 'verify-remote.py'}
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
    for name, filename in (('cleanup', 'cleanup-ecs-builds.py'), ('verifier', 'verify-remote.py')):
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
    return root, current, identity, quiescence


def approved_request(raw, checksum, current, identity):
    request = validate_request(raw, checksum, current, identity)
    need(all(APPROVED_OLD.get(row['release']) == row['commit'] for row in request['candidates']), 'ONLY_THREE_REVIEWED_OLD_ATTEMPTS_ALLOWED')
    return request


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
    parser.add_argument('--phase', choices=('capture-request', 'plan', 'apply', 'inspect'), required=True)
    parser.add_argument('--mode', choices=('Verified', 'Maintenance'), required=True)
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id', 'current-receipt-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--local-spec-sha256'); parser.add_argument('--request-sha256'); parser.add_argument('--plan-sha256')
    args = parser.parse_args(argv)
    try:
        root, current, identity, quiescence = admitted_current(args); inbox = root / 'inbox' / args.tag
        request_file = inbox / 'native-jar-duplicate-request.json'; plan_file = inbox / 'native-jar-duplicate-plan.json'
        receipt_file = inbox / 'native-jar-duplicate-receipt.json'; capture_file = inbox / 'native-jar-duplicate-capture.json'
        if args.phase == 'capture-request':
            raw = private_bytes(root, inbox / 'native-jar-duplicate-local-spec.json')
            request, skipped = capture_request(root, raw, local_spec_sha256=args.local_spec_sha256, expected_current=current, identity=identity)
            result = {'status': 'CAPTURED', 'current': current, 'identity': identity,
                      'request': write_new(request_file, request), 'skipped': skipped}
            result['capture'] = write_new(capture_file, result)
        elif args.phase == 'inspect':
            files = {}
            for name, path in (('request', request_file), ('plan', plan_file), ('receipt', receipt_file), ('capture', capture_file),
                               ('journal', inbox / 'native-jar-duplicate-journal.jsonl')):
                if path.exists():
                    raw = private_bytes(root, path); files[name] = {'file': path.name, 'bytes': len(raw), 'sha256': digest_bytes(raw)}
            result = {'status': 'INSPECTED', 'current': current, 'identity': identity, 'files': files}
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
        print(json.dumps({'status': 'REJECTED', 'errorType': type(error).__name__,
                          'reason': str(error) if isinstance(error, RetirementError) else 'NATIVE_DUPLICATE_ADMISSION_FAILED'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
