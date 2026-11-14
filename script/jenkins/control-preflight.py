"""ECS-only control-script tests before native JAR transfer or database setup.

Uses the current source archive and its already registered immutable Python
image. This is never full project verification or production readiness.
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
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET

MODULES = ('test_jenkins_resource_budget', 'test_jenkins_fixture_admission', 'test_jenkins_fixture_cgroup_probe',
           'test_derived_mysql_retirement', 'test_source_pytest_retirement', 'test_source_pytest307308_retirement',
           'test_jenkins_ecs_build_cleanup', 'test_generated_artifact_lifecycle',
           'test_failed_native_jar_duplicates', 'test_historical_builder_retirement',
           'test_historical_mysql_fixture_retirement', 'test_public_buildkit_layer_retirement',
           'test_generated_public_image_archive_retirement', 'test_historical_python_build_cache_retirement',
           'test_local_artifact_custody', 'test_compose_container_selection',
           'test_local_fixed_originals_retirement', 'test_fixed_originals_attestation',
           'test_local_mysql_custody', 'test_local_mysql_source_classification',
           'test_project_mysql_custody',
           'test_jenkins_suite_evidence', 'test_jenkins_evidence_recollection', 'test_jenkins_maven_dependency_cache',
           'test_compact_schema_source', 'test_control_preflight', 'test_middleware_fixture',
           'test_observability_fixture', 'test_semantic_mysql_fixture')
TAG = re.compile(r'ci-[1-9][0-9]*-[a-f0-9]{12}')
SHA = re.compile(r'[a-f0-9]{64}')
MIB = 1024 ** 2
MEMORY = 2 * 1024 ** 3
TIMEOUT = 360
LABEL = 'io.doorhandle.control-preflight'
SCRATCH_301 = {'release': 'ci-301-cfc056762f1f', 'commit': 'cfc056762f1f9fb41fd58196e5bdf63badbc20cf',
    'sourceSha256': 'd99156ca7a1b910e6480637ba9a9488bfef04206c4f9622cedb2b704608785e8',
    'toolManifestSha256': '1830b1ee2d7b2c6a0e007f198d355870041f37b2ca751de8c4bd0127ce22909b'}
SCRATCH_301_RECEIPT = '6ab66872b08040511d6afade650be7654a0d7b0f57f6bb9a7e5cc03527be996f'
SCRATCH_302 = {'release': 'ci-302-28e41fc4eae1', 'commit': '28e41fc4eae11850a9f4a74636e7672b6dbdd7d4',
    'sourceSha256': '5e3aab67f330828a8ff306b90ef071214369edfd64b8d5ad0547758e92b3ee67',
    'toolManifestSha256': '853a1066f01bc8458481ad5350f56a4b61153e53d1990b50849586d384860ea7'}
SCRATCH_REPAIRS = {301: (SCRATCH_301, SCRATCH_301_RECEIPT),
    302: (SCRATCH_302, 'ff3ec19164387e322e22726dddcd8c85307b995bb43130abed6af2364646db71')}
REFUSAL_CODES = frozenset({
    'BOUNDED_CONTROL_XML_REQUIRED', 'CANONICAL_CONTROL_PATH_REQUIRED',
    'CONTROL_CONTAINER_DID_NOT_STOP', 'CONTROL_CONTAINER_ID_REQUIRED',
    'CONTROL_CONTAINER_MOUNTS_DIFFER', 'CONTROL_CONTAINER_OWNER_OR_SANDBOX_DIFFERS',
    'CONTROL_CONTAINER_REMOVAL_UNKNOWN', 'CONTROL_CREATE_OUTCOME_UNKNOWN',
    'CONTROL_DOCKER_OPERATION_FAILED', 'CONTROL_ECS_UID_1000_REQUIRED', 'CONTROL_FIXED_CONTEXT_REQUIRED',
    'CONTROL_HELPER_CLOSURE_DIFFERS', 'CONTROL_HELPER_SHA_DIFFERS', 'CONTROL_IMMUTABLE_PYTHON_IMAGE_REQUIRED',
    'CONTROL_LINK_REJECTED', 'CONTROL_LOG_BOUND_OR_READ_FAILED', 'CONTROL_OWNER_TYPE_OR_BOUND_DIFFERS',
    'CONTROL_PYTEST_FAILED_OR_OOM', 'CONTROL_PYTHON_IMAGE_DIFFERS', 'CONTROL_RECEIPT_BOUND_EXCEEDED',
    'CONTROL_REQUIRED_TEST_PROFILE_INCOMPLETE', 'CONTROL_SCRATCH_CLEANUP_UNKNOWN',
    'CONTROL_SCRATCH_IDENTITY_CHANGED', 'CONTROL_SOURCE_AND_SCRATCH_RESERVE_REQUIRED',
    'CONTROL_SCRATCH_RECOVERY_UNKNOWN',
    'CONTROL_SOURCE_CHANGED_DURING_ADMISSION', 'CONTROL_SOURCE_COMMIT_DIFFERS',
    'CONTROL_SOURCE_EXPANSION_EXCEEDED', 'CONTROL_SOURCE_MEMBER_BOUND_EXCEEDED', 'CONTROL_SOURCE_SHA_DIFFERS',
    'CONTROL_FORMAL_VERIFICATION_PATH_OCCUPIED',
    'CONTROL_TESTS_FAILED_SKIPPED_OR_INCOMPLETE', 'CONTROL_TEST_DISK_RESERVE_EXHAUSTED',
    'CONTROL_TEST_EXIT_UNKNOWN', 'CONTROL_TEST_TIMEOUT', 'CONTROL_TOOL_MANIFEST_SHA_DIFFERS',
    'CONTROL_EXECUTION_CLAIM_DIFFERS', 'CONTROL_EXECUTION_OBSERVATION_TIMEOUT',
    'CONTROL_EXECUTION_STOPPED_WITHOUT_RECEIPT', 'CONTROL_TERMINAL_RECEIPT_DIFFERS',
    'CONTROL_XML_UNEXPECTED_MODULE', 'EXACT_CONTROL_CONTAINER_REQUIRED',
    'FIXED_CONTROL_EXECUTOR_REQUIRED', 'FRESH_CONTROL_ATTEMPT_REQUIRED',
})


def need(value, code):
    if not value: raise ValueError(code)


def safe_failure(error):
    code = error.args[0] if isinstance(error, ValueError) and len(error.args) == 1 else None
    return {'errorType': type(error).__name__,
            'code': code if type(code) is str and code in REFUSAL_CODES else 'CONTROL_EXECUTION_FAILED'}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def digest(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def owned(path, *, directory=False, maximum=128 * MIB):
    path = Path(path)
    need(path.is_absolute() and path.resolve(strict=True) == path, 'CANONICAL_CONTROL_PATH_REQUIRED')
    for parent in (path, *path.parents): need(not parent.is_symlink(), 'CONTROL_LINK_REJECTED')
    info = path.lstat()
    need(info.st_uid == 1000 and not info.st_mode & 0o022
         and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
              and info.st_nlink == 1 and 0 <= info.st_size <= maximum), 'CONTROL_OWNER_TYPE_OR_BOUND_DIFFERS')
    return path


def write(path, value):
    raw = encoded(value); need(len(raw) <= 2 * MIB, 'CONTROL_RECEIPT_BOUND_EXCEEDED')
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def fixed_modules(root, args):
    inbox = root / 'inbox' / args.tag; source = owned(inbox / 'source.tar.gz')
    need(digest(source) == args.source_sha256, 'CONTROL_SOURCE_SHA_DIFFERS')
    paths = {'script/jenkins/control-preflight.py': Path(__file__).absolute(),
             'script/jenkins/verify-remote.py': inbox / 'control-verify-remote.py',
             'script/jenkins/ecs-tool-runtime.py': inbox / 'ecs-tool-runtime.py'}
    need(paths['script/jenkins/control-preflight.py'] == inbox / 'control-preflight.py', 'FIXED_CONTROL_EXECUTOR_REQUIRED')
    expected = {name: digest(owned(path, maximum=MIB)) for name, path in paths.items()}
    class Bounded:
        def __init__(self, stream): self.stream, self.total = stream, 0
        def read(self, size=-1):
            remain = 512 * MIB - self.total
            raw = self.stream.read(remain + 1 if size < 0 else min(size, remain + 1)); self.total += len(raw)
            need(self.total <= 512 * MIB, 'CONTROL_SOURCE_EXPANSION_EXCEEDED'); return raw
    seen = set(); count = 0; allocation = 0
    with gzip.open(source, 'rb') as expanded, tarfile.open(fileobj=Bounded(expanded), mode='r|') as archive:
        for member in archive:
            count += 1; need(count <= 50000 and 0 <= member.size <= 32 * MIB, 'CONTROL_SOURCE_MEMBER_BOUND_EXCEEDED')
            allocation += ((member.size + 4095) // 4096) * 4096 + 4096
            if member.name not in paths: continue
            need(member.name not in seen and member.isfile() and 0 < member.size <= MIB, 'CONTROL_HELPER_CLOSURE_DIFFERS')
            raw = archive.extractfile(member).read(MIB + 1)
            need(len(raw) == member.size and hashlib.sha256(raw).hexdigest() == expected[member.name], 'CONTROL_HELPER_SHA_DIFFERS')
            seen.add(member.name)
        need(archive.pax_headers.get('comment') == args.commit and seen == set(paths), 'CONTROL_SOURCE_COMMIT_DIFFERS')
    need(digest(source) == args.source_sha256, 'CONTROL_SOURCE_CHANGED_DURING_ADMISSION')
    result = {}
    for key, name in (('verifier', 'control-verify-remote.py'), ('tools', 'ecs-tool-runtime.py')):
        spec = importlib.util.spec_from_file_location('fixed_control_' + key, inbox / name)
        module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
        result[key] = module
    return source, allocation, result


def docker(*arguments, timeout=30):
    result = subprocess.run(['/usr/bin/docker', *arguments], capture_output=True, timeout=timeout,
        env={key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
    need(result.returncode == 0 and len(result.stdout) <= 16 * MIB, 'CONTROL_DOCKER_OPERATION_FAILED')
    return result.stdout


def container_row(cid, context, token, image, source, output):
    rows = json.loads(docker('inspect', cid)); need(type(rows) is list and len(rows) == 1, 'EXACT_CONTROL_CONTAINER_REQUIRED')
    row = rows[0]; config, host = row['Config'], row['HostConfig']; labels = config.get('Labels') or {}
    need(row['Id'] == cid and row['Image'] == image and labels.get(LABEL) == token
         and all(labels.get('io.doorhandle.' + key) == value for key, value in
                 (('release', context['release']), ('source', context['sourceSha256']), ('commit', context['commit'])))
         and config.get('User') == '1000:1000' and config.get('Entrypoint') == ['/usr/local/bin/python']
         and host.get('NetworkMode') == 'none' and host.get('ReadonlyRootfs') is True
         and host.get('Privileged') is False and host.get('AutoRemove') is False
         and host.get('Memory') == host.get('MemorySwap') == MEMORY and host.get('NanoCpus') == 2 * 10 ** 9
         and host.get('PidsLimit') == 256 and host['RestartPolicy']['Name'] == 'no'
         and set(host.get('CapDrop') or []) == {'ALL'}
         and 'no-new-privileges:true' in (host.get('SecurityOpt') or []), 'CONTROL_CONTAINER_OWNER_OR_SANDBOX_DIFFERS')
    mounts = row.get('Mounts', [])
    need(len(mounts) == 2 and all(item.get('Type') == 'bind' for item in mounts)
         and {(item['Source'], item['Destination'], item['RW']) for item in mounts}
         == {(str(source), str(source), False), (str(output), str(output), True)}, 'CONTROL_CONTAINER_MOUNTS_DIFFER')
    return row


def tally_report(path, minimum):
    path = owned(path, maximum=2 * MIB); raw = path.read_bytes()
    need(raw and b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'BOUNDED_CONTROL_XML_REQUIRED')
    tallies = {name: {'passed': 0, 'failed': 0, 'skipped': 0} for name in minimum}
    for case in ET.fromstring(raw).iter('testcase'):
        match = re.match(r'(?:tests_python\.)?(test_[A-Za-z0-9_]+)(?:\.|$)', case.get('classname', ''))
        need(match is not None and match[1] in tallies, 'CONTROL_XML_UNEXPECTED_MODULE')
        result = tallies[match[1]]
        failed = len(case.findall('failure')) + len(case.findall('error')); skipped = len(case.findall('skipped'))
        result['failed'] += failed; result['skipped'] += skipped
        if not failed and not skipped: result['passed'] += 1
    need(all(value['passed'] >= minimum[name] and not value['failed'] and not value['skipped']
             for name, value in tallies.items()), 'CONTROL_TESTS_FAILED_SKIPPED_OR_INCOMPLETE')
    return tallies


def required_minimum(profile):
    required = profile['python']['requiredSuites']
    minimum = {entry['module'].removeprefix('tests_python.'): entry['minimumTests'] for entry in required
               if entry['module'].removeprefix('tests_python.') in MODULES}
    need(set(minimum) == set(MODULES) and all(type(value) is int and value > 0 for value in minimum.values()),
         'CONTROL_REQUIRED_TEST_PROFILE_INCOMPLETE')
    return minimum


def require_fresh_verification_paths(inbox):
    for name in ('verify-remote.py', '.verification-upload'):
        path = inbox / name
        need(not path.exists() and not path.is_symlink(), 'CONTROL_FORMAL_VERIFICATION_PATH_OCCUPIED')


def remove_owned_tree(path, expected):
    path = owned(path, directory=True); info = path.lstat()
    need([info.st_dev, info.st_ino, info.st_uid] == expected and shutil.rmtree.avoids_symlink_attacks,
         'CONTROL_SCRATCH_IDENTITY_CHANGED')
    count = [0]
    def allow_directory(descriptor, depth=0):
        current = os.fstat(descriptor); count[0] += 1
        # Nested directories are synthetic test inputs, including deliberate
        # group/world-writable negative cases. The private, identity-bound root
        # remains the authority boundary; never follow a nested link or cross a filesystem device.
        need(depth <= 128 and count[0] <= 100000 and current.st_uid == 1000
             and current.st_dev == expected[0],
             'CONTROL_SCRATCH_IDENTITY_CHANGED')
        with os.scandir(descriptor) as children:
            for child in children:
                before = child.stat(follow_symlinks=False)
                if not stat.S_ISDIR(before.st_mode): continue
                fd = os.open(child.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=descriptor)
                try:
                    after = os.fstat(fd)
                    need((before.st_dev, before.st_ino) == (after.st_dev, after.st_ino),
                         'CONTROL_SCRATCH_IDENTITY_CHANGED')
                    allow_directory(fd, depth + 1)
                finally: os.close(fd)
        if not current.st_mode & stat.S_IWUSR:
            os.fchmod(descriptor, stat.S_IMODE(current.st_mode) | stat.S_IWUSR)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        held = os.fstat(descriptor)
        need([held.st_dev, held.st_ino, held.st_uid] == expected, 'CONTROL_SCRATCH_IDENTITY_CHANGED')
        allow_directory(descriptor)
    finally: os.close(descriptor)
    current = path.lstat()
    need([current.st_dev, current.st_ino, current.st_uid] == expected, 'CONTROL_SCRATCH_IDENTITY_CHANGED')
    shutil.rmtree(path)
    need(not path.exists() and not path.is_symlink(), 'CONTROL_SCRATCH_CLEANUP_UNKNOWN')


def recover_control_scratch(root, args, modules, identity, build):
    """Continue only #301/#302's already-owned cleanup, after new controls pass.

    Preserve its original failure, reports and source archive. This fixed repair
    is separate from the sixteen historical pytest-root retirement authority.
    """
    need(type(build) is int and build in SCRATCH_REPAIRS, 'CONTROL_SCRATCH_RECOVERY_UNKNOWN')
    old, receipt_sha = SCRATCH_REPAIRS[build]
    inbox = root / 'inbox' / old['release']; base = inbox / 'control-preflight'
    if not base.exists() and not base.is_symlink(): return {'status': 'NOT_PRESENT', **old}
    owned(base, directory=True)
    receipt_path = owned(base / 'output/receipt.json', maximum=2 * MIB)
    need(digest(receipt_path) == receipt_sha, 'CONTROL_SCRATCH_RECOVERY_UNKNOWN')
    original = json.loads(receipt_path.read_bytes())
    need(all(original.get(key) == value for key, value in old.items())
         and original.get('identity') == identity and original.get('kind') == 'doorhandle-control-preflight'
         and original.get('status') == 'FAILED_OR_UNKNOWN' and original.get('containerCleanupConfirmed') is True
         and original.get('sourceScratchCleanupConfirmed') is False and original.get('fullProjectVerified') is False
         and original.get('businessRuntimeStarted') is False, 'CONTROL_SCRATCH_RECOVERY_UNKNOWN')
    source = owned(inbox / 'source.tar.gz')
    need(digest(source) == old['sourceSha256'], 'CONTROL_SCRATCH_RECOVERY_UNKNOWN')
    for name, limit in (('python.xml', 2 * MIB), ('pytest.log', 8 * MIB)):
        path = owned(base / 'output' / name, maximum=limit); proof = original['reports'][name]
        need(proof['file'] == name and path.stat().st_size == proof['bytes'] and digest(path) == proof['sha256'],
             'CONTROL_SCRATCH_RECOVERY_UNKNOWN')
    old_args = argparse.Namespace(**{**vars(args), 'tag': old['release'],
        'commit': old['commit'], 'source_sha256': old['sourceSha256'],
        'tool_manifest_sha256': old['toolManifestSha256']})
    claim = json.loads(owned(base / 'execution.json', maximum=64 * 1024).read_bytes())
    expected = execution_context(old_args, identity)
    need(set(claim) == set(expected) | {'supervisor'}
         and all(claim.get(key) == value for key, value in expected.items()), 'CONTROL_SCRATCH_RECOVERY_UNKNOWN')
    supervisor = claim['supervisor']
    need(set(supervisor) == {'pid', 'startTicks', 'bootId'} and type(supervisor['pid']) is int
         and supervisor['pid'] > 1 and type(supervisor['startTicks']) is str and supervisor['startTicks'].isdigit()
         and type(supervisor['bootId']) is str and re.fullmatch(r'[a-f0-9-]{36}', supervisor['bootId']),
         'CONTROL_SCRATCH_RECOVERY_UNKNOWN')
    if supervisor['bootId'] == boot_id():
        try: active = modules['verifier'].supervisor_start(supervisor['pid']) == supervisor['startTicks']
        except (FileNotFoundError, ProcessLookupError): active = False
        need(not active, 'CONTROL_SCRATCH_RECOVERY_UNKNOWN')
    identifiers = docker('ps', '-aq', '--no-trunc').decode().split()
    need(len(identifiers) <= 4096 and all(SHA.fullmatch(value) for value in identifiers),
         'CONTROL_SCRATCH_RECOVERY_UNKNOWN')
    if identifiers:
        rows = json.loads(docker('inspect', *identifiers))
        need(type(rows) is list and {row['Id'] for row in rows} == set(identifiers), 'CONTROL_SCRATCH_RECOVERY_UNKNOWN')
        for row in rows:
            need(row['Id'] != original.get('containerId')
                 and (row['Config'].get('Labels') or {}).get('io.doorhandle.release') != old['release'],
                 'CONTROL_SCRATCH_RECOVERY_UNKNOWN')
            for mount in row.get('Mounts', []):
                if mount.get('Type') != 'bind' or not mount.get('Source'): continue
                path = Path(mount['Source'])
                need(not (path == base or path.is_relative_to(base) or base.is_relative_to(path)),
                     'CONTROL_SCRATCH_RECOVERY_UNKNOWN')
    paths = [base / 'control-checkout', base / 'output/scratch', base / 'output/home']
    marker = base / 'scratch-recovery.json'
    if marker.exists() or marker.is_symlink():
        previous = json.loads(owned(marker, maximum=2 * MIB).read_bytes())
        need(previous.get('status') == 'COMPLETE' and previous.get('original') == old
             and previous.get('originalReceiptSha256') == receipt_sha
             and previous.get('identity') == identity
             and all(not path.exists() and not path.is_symlink() for path in paths), 'CONTROL_SCRATCH_RECOVERY_UNKNOWN')
        return {**previous, 'status': 'ALREADY_COMPLETE'}
    selected = []
    for path in paths:
        if not path.exists() and not path.is_symlink(): selected.append((path, None)); continue
        owned(path, directory=True); info = path.lstat()
        selected.append((path, [info.st_dev, info.st_ino, info.st_uid]))
    write(base / 'scratch-recovery-claim.json', {'original': old,
        'originalReceiptSha256': receipt_sha, 'current': execution_context(args, identity)})
    result = {'schemaVersion': 1, 'kind': 'doorhandle-owned-control-scratch-recovery',
        'status': 'FAILED_OR_UNKNOWN', 'original': old, 'originalReceiptSha256': receipt_sha,
        'identity': identity, 'current': execution_context(args, identity), 'removed': [], 'alreadyAbsent': [],
        'originalFailureAndReportsPreserved': True, 'sourceArchivePreserved': True}
    try:
        for path, expected_id in selected:
            if expected_id is None: result['alreadyAbsent'].append(str(path)); continue
            remove_owned_tree(path, expected_id)
            result['removed'].append({'path': str(path), 'identity': expected_id})
        need(digest(receipt_path) == receipt_sha, 'CONTROL_SCRATCH_RECOVERY_UNKNOWN')
        disk = os.statvfs(root); result['freshAvailableBytes'] = disk.f_bavail * disk.f_frsize
        result['status'] = 'COMPLETE'
    finally: write(marker, result)
    return result


def admit_context(args):
    need(sys.platform == 'linux' and os.getuid() == os.geteuid() == os.getgid() == 1000, 'CONTROL_ECS_UID_1000_REQUIRED')
    need(TAG.fullmatch(args.tag) and re.fullmatch(r'[a-f0-9]{40}', args.commit)
         and args.tag.endswith('-' + args.commit[:12]) and SHA.fullmatch(args.source_sha256)
         and SHA.fullmatch(args.tool_manifest_sha256), 'CONTROL_FIXED_CONTEXT_REQUIRED')
    root = owned(Path(args.root), directory=True)
    source_archive, allocation, modules = fixed_modules(root, args)
    identity = modules['verifier'].ecs_identity(args.instance_id, args.machine_id)
    return root, source_archive, allocation, modules, identity


def execution_context(args, identity):
    return {'schemaVersion': 1, 'kind': 'doorhandle-control-execution', 'release': args.tag,
            'commit': args.commit, 'sourceSha256': args.source_sha256,
            'toolManifestSha256': args.tool_manifest_sha256, 'identity': identity}


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def execution_supervisor(claim, args, identity):
    expected = execution_context(args, identity)
    need(type(claim) is dict and type(claim.get('schemaVersion')) is int
         and set(claim) == set(expected) | {'supervisor'}
         and all(claim.get(key) == value for key, value in expected.items()), 'CONTROL_EXECUTION_CLAIM_DIFFERS')
    supervisor = claim['supervisor']
    need(type(supervisor) is dict and set(supervisor) == {'pid', 'startTicks', 'bootId'}
         and type(supervisor['pid']) is int and supervisor['pid'] > 1
         and type(supervisor['startTicks']) is str and supervisor['startTicks'].isdigit()
         and supervisor['bootId'] == boot_id(), 'CONTROL_EXECUTION_CLAIM_DIFFERS')
    return supervisor


def terminal_result(receipt, path, args, identity):
    expected = execution_context(args, identity)
    need(type(receipt) is dict and type(receipt.get('schemaVersion')) is int and receipt['schemaVersion'] == 1
         and receipt.get('kind') == 'doorhandle-control-preflight'
         and all(receipt.get(key) == expected[key] for key in
                 ('release', 'commit', 'sourceSha256', 'toolManifestSha256', 'identity'))
         and receipt.get('status') in ('CONTROL_PREFLIGHT_PASS', 'FAILED_OR_UNKNOWN')
         and receipt.get('fullProjectVerified') is False
         and receipt.get('businessRuntimeStarted') is False, 'CONTROL_TERMINAL_RECEIPT_DIFFERS')
    return {**expected, 'status': receipt['status'], 'terminal': True,
            'cleanupConfirmed': receipt.get('containerCleanupConfirmed') is True
                and receipt.get('sourceScratchCleanupConfirmed') is True,
            'receipt': str(path), 'receiptSha256': digest(path),
            'reports': receipt['reports'], 'fullProjectVerified': False}


def progress(value):
    # A broken SSH stdout is not cancellation of this original execution.
    try:
        print(json.dumps(value), flush=True)
    except BrokenPipeError:
        sink = os.open(os.devnull, os.O_WRONLY)
        try: os.dup2(sink, 1)
        finally: os.close(sink)


def observe(args):
    """Read only this release's original process and final receipt; never rerun it."""
    root, _source, _allocation, modules, identity = admit_context(args)
    base = root / 'inbox' / args.tag / 'control-preflight'
    claim_path = base / 'execution.json'; path = base / 'output/receipt.json'
    deadline = time.monotonic() + TIMEOUT + 120
    while True:
        need(time.monotonic() < deadline, 'CONTROL_EXECUTION_OBSERVATION_TIMEOUT')
        # Dispatch may precede the claim. Its absence cannot authorize cleanup.
        if base.exists() or base.is_symlink(): owned(base, directory=True)
        if not claim_path.exists() and not claim_path.is_symlink():
            time.sleep(1); continue
        try: claim = json.loads(owned(claim_path, maximum=64 * 1024).read_bytes())
        except json.JSONDecodeError:
            time.sleep(1); continue  # The original exclusive writer may still be publishing it.
        supervisor = execution_supervisor(claim, args, identity)
        try: alive = modules['verifier'].supervisor_start(supervisor['pid']) == supervisor['startTicks']
        except (FileNotFoundError, ProcessLookupError): alive = False
        if not alive:
            need(path.exists() or path.is_symlink(), 'CONTROL_EXECUTION_STOPPED_WITHOUT_RECEIPT')
            receipt = json.loads(owned(path, maximum=2 * MIB).read_bytes())
            return terminal_result(receipt, path, args, identity)
        # Wait until the original process ends, not merely until a filename appears.
        time.sleep(1)


def run(args):
    root, source_archive, allocation, modules, identity = admit_context(args)
    context = {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256}
    inbox = owned(root / 'inbox' / args.tag, directory=True)
    require_fresh_verification_paths(inbox)
    base = inbox / 'control-preflight'; need(not base.exists() and not base.is_symlink(), 'FRESH_CONTROL_ATTEMPT_REQUIRED')
    disk = os.statvfs(root)
    need(disk.f_bavail * disk.f_frsize >= 2 * 1024 ** 3 + allocation + 144 * MIB, 'CONTROL_SOURCE_AND_SCRATCH_RESERVE_REQUIRED')
    base.mkdir(mode=0o700)
    write(base / 'execution.json', {**execution_context(args, identity), 'supervisor': {
        'pid': os.getpid(), 'startTicks': modules['verifier'].supervisor_start(os.getpid()), 'bootId': boot_id()}})
    source = base / 'control-checkout'; source.mkdir(mode=0o700)
    output = base / 'output'; output.mkdir(mode=0o700)
    scratches = [source, output / 'scratch', output / 'home']
    for path in scratches[1:]: path.mkdir(mode=0o700)
    scratch_ids = {str(path): [path.stat().st_dev, path.stat().st_ino, path.stat().st_uid] for path in scratches}
    receipt = {'schemaVersion': 1, 'kind': 'doorhandle-control-preflight', **context, 'identity': identity,
        'status': 'FAILED_OR_UNKNOWN', 'fullProjectVerified': False, 'businessRuntimeStarted': False,
        'selectedModules': list(MODULES), 'toolManifestSha256': args.tool_manifest_sha256,
        'containerCleanupConfirmed': False, 'sourceScratchCleanupConfirmed': False, 'reports': {}}
    token = secrets.token_hex(12); cid = None; image = None; error = None; create_attempted = False
    try:
        modules['verifier'].unpack_source(source_archive, source, args.commit)
        manifest = owned(inbox / 'tool-runtime/manifest.json', maximum=2 * MIB)
        need(digest(manifest) == args.tool_manifest_sha256, 'CONTROL_TOOL_MANIFEST_SHA_DIFFERS')
        tools, manifest_sha = modules['tools'].admit(manifest, root=root, tag=args.tag, commit=args.commit,
            source_sha=args.source_sha256, identity=identity, source=source)
        image = tools['images']['python']; need(re.fullmatch(r'sha256:[a-f0-9]{64}', image), 'CONTROL_IMMUTABLE_PYTHON_IMAGE_REQUIRED')
        inspected = json.loads(docker('image', 'inspect', image))[0]
        need(inspected['Id'] == image and inspected.get('Os') == 'linux', 'CONTROL_PYTHON_IMAGE_DIFFERS')
        receipt['pythonImageId'] = image
        profile = json.loads((source / 'script/jenkins/compact-acceptance.json').read_bytes())
        minimum = required_minimum(profile)
        arguments = ['-I', '-B', '-m', 'pytest', *['tests_python/' + name + '.py' for name in MODULES], '-q',
            '-p', 'no:cacheprovider', '--basetemp=' + str(output / 'scratch/pytest'), '--junitxml=' + str(output / 'python.xml')]
        command = ['create', '--name', 'doorhandle-control-' + token, '--pull', 'never', '--network', 'none',
            '--restart', 'no', '--user', '1000:1000', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--memory', str(MEMORY), '--memory-swap', str(MEMORY),
            '--cpus', '2', '--pids-limit', '256', '--log-opt', 'max-size=8m', '--log-opt', 'max-file=1',
            '--label', LABEL + '=' + token, '--label', 'io.doorhandle.release=' + args.tag,
            '--label', 'io.doorhandle.source=' + args.source_sha256, '--label', 'io.doorhandle.commit=' + args.commit,
            '--mount', 'type=bind,src=' + str(source) + ',dst=' + str(source) + ',readonly',
            '--mount', 'type=bind,src=' + str(output) + ',dst=' + str(output), '--workdir', str(source),
            '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', 'PYTHONNOUSERSITE=1', '--env', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1',
            '--env', 'TMPDIR=' + str(output / 'scratch'), '--env', 'HOME=' + str(output / 'home'),
            '--entrypoint', '/usr/local/bin/python', image, *arguments]
        create_attempted = True
        cid = docker(*command).decode('ascii').strip(); need(SHA.fullmatch(cid), 'CONTROL_CONTAINER_ID_REQUIRED')
        receipt['containerId'] = cid
        container_row(cid, context, token, image, source, output)
        docker('start', cid); deadline = time.monotonic() + TIMEOUT
        while True:
            row = container_row(cid, context, token, image, source, output)
            disk = os.statvfs(root)
            need(disk.f_bavail * disk.f_frsize >= 2 * 1024 ** 3 + 8 * MIB, 'CONTROL_TEST_DISK_RESERVE_EXHAUSTED')
            need(time.monotonic() <= deadline, 'CONTROL_TEST_TIMEOUT')
            if not row['State']['Running']:
                need(row['State']['Status'] == 'exited' and row['State']['Pid'] == 0 and not row['State']['Restarting'], 'CONTROL_TEST_EXIT_UNKNOWN')
                receipt['testExitCode'] = row['State']['ExitCode']; break
            time.sleep(.5)
        need(receipt['testExitCode'] == 0 and not row['State'].get('OOMKilled'), 'CONTROL_PYTEST_FAILED_OR_OOM')
        receipt['modules'] = tally_report(output / 'python.xml', minimum)
    except Exception as caught:
        error = caught
        receipt['failure'] = safe_failure(caught)
    finally:
        for event in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT): signal.signal(event, signal.SIG_IGN)
        cleanup_errors = []
        if create_attempted and (cid is None or not SHA.fullmatch(cid)):
            try:
                candidates = docker('ps', '-aq', '--no-trunc', '--filter', 'label=' + LABEL + '=' + token).decode().split()
                need(len(candidates) <= 1 and all(SHA.fullmatch(item) for item in candidates), 'CONTROL_CREATE_OUTCOME_UNKNOWN')
                cid = candidates[0] if candidates else None
            except Exception as caught: cleanup_errors.append(type(caught).__name__)
        if cid is not None and image is not None:
            try:
                row = container_row(cid, context, token, image, source, output)
                if row['State'].get('Paused'): docker('unpause', cid)
                if row['State']['Running']: docker('stop', '--time', '10', cid, timeout=25)
                row = container_row(cid, context, token, image, source, output)
                need(not row['State']['Running'] and not row['State']['Restarting'] and row['State']['Pid'] == 0,
                     'CONTROL_CONTAINER_DID_NOT_STOP')
                try:
                    logs = subprocess.run(['/usr/bin/docker', 'logs', cid], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        timeout=20, env={key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
                    need(logs.returncode == 0 and len(logs.stdout) <= 8 * MIB, 'CONTROL_LOG_BOUND_OR_READ_FAILED')
                    with os.fdopen(os.open(output / 'pytest.log', os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as stream:
                        stream.write(logs.stdout); stream.flush(); os.fsync(stream.fileno())
                except Exception as caught: cleanup_errors.append(type(caught).__name__)
                docker('rm', cid)
                remaining = docker('ps', '-aq', '--no-trunc', '--filter', 'id=' + cid).decode().split()
                need(cid not in remaining, 'CONTROL_CONTAINER_REMOVAL_UNKNOWN')
                receipt['containerCleanupConfirmed'] = True
            except Exception as caught: cleanup_errors.append(type(caught).__name__)
        elif cid is None and not cleanup_errors:
            receipt['containerCleanupConfirmed'] = True
        if receipt['containerCleanupConfirmed']:
            try:
                for path in scratches: remove_owned_tree(path, scratch_ids[str(path)])
                receipt['sourceScratchCleanupConfirmed'] = True
            except Exception as caught: cleanup_errors.append(type(caught).__name__)
        if cleanup_errors: receipt['cleanupErrors'] = cleanup_errors
        for name, maximum in (('python.xml', 2 * MIB), ('pytest.log', 8 * MIB)):
            path = output / name
            if path.exists():
                try:
                    owned(path, maximum=maximum)
                    receipt['reports'][name] = {'file': name, 'bytes': path.stat().st_size, 'sha256': digest(path)}
                except Exception: receipt.setdefault('cleanupErrors', []).append('CONTROL_REPORT_INVALID')
        if error is None and receipt['containerCleanupConfirmed'] and receipt['sourceScratchCleanupConfirmed'] and not receipt.get('cleanupErrors'):
            try:
                recovered = {'status': 'COMPLETE', 'attempts': [
                    recover_control_scratch(root, args, modules, identity, build) for build in SCRATCH_REPAIRS]}
                recovery_path = output / 'control-scratch-recovery.json'
                write(recovery_path, recovered)
                receipt['reports'][recovery_path.name] = {'file': recovery_path.name,
                    'bytes': recovery_path.stat().st_size, 'sha256': digest(recovery_path)}
                receipt['status'] = 'CONTROL_PREFLIGHT_PASS'
            except Exception as caught:
                receipt['failure'] = safe_failure(caught)
                receipt.setdefault('cleanupErrors', []).append('CONTROL_SCRATCH_RECOVERY_UNKNOWN')
        write(output / 'receipt.json', receipt)
    return receipt, output / 'receipt.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id', 'tool-manifest-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--observe', action='store_true')
    args = parser.parse_args()
    def interrupted(_signal, _frame): raise RuntimeError('CONTROL_PREFLIGHT_INTERRUPTED')
    for event in (signal.SIGTERM, signal.SIGINT): signal.signal(event, interrupted)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        if args.observe: result = observe(args)
        else:
            receipt, path = run(args)
            result = terminal_result(receipt, path, args, receipt['identity'])
        progress(result)
        return 0 if result['status'] == 'CONTROL_PREFLIGHT_PASS' else 2
    except Exception as error:
        progress({'status': 'CONTROL_PREFLIGHT_REJECTED', 'terminal': not args.observe,
            'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
            'toolManifestSha256': args.tool_manifest_sha256,
            'identity': {'instanceId': args.instance_id, 'machineId': args.machine_id, 'executionLocation': 'ECS'},
            'cleanupConfirmed': False, 'receipt': None, 'receiptSha256': None, **safe_failure(error)})
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
