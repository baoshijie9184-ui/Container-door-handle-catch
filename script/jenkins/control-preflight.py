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

MODULES = ('test_jenkins_resource_budget', 'test_jenkins_fixture_admission',
           'test_failed_native_jar_duplicates', 'test_historical_builder_retirement',
           'test_historical_mysql_fixture_retirement', 'test_public_buildkit_layer_retirement',
           'test_control_preflight')
TAG = re.compile(r'ci-[1-9][0-9]*-[a-f0-9]{12}')
SHA = re.compile(r'[a-f0-9]{64}')
MIB = 1024 ** 2
MEMORY = 2 * 1024 ** 3
TIMEOUT = 360
LABEL = 'io.doorhandle.control-preflight'
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
    'CONTROL_SOURCE_CHANGED_DURING_ADMISSION', 'CONTROL_SOURCE_COMMIT_DIFFERS',
    'CONTROL_SOURCE_EXPANSION_EXCEEDED', 'CONTROL_SOURCE_MEMBER_BOUND_EXCEEDED', 'CONTROL_SOURCE_SHA_DIFFERS',
    'CONTROL_TESTS_FAILED_SKIPPED_OR_INCOMPLETE', 'CONTROL_TEST_DISK_RESERVE_EXHAUSTED',
    'CONTROL_TEST_EXIT_UNKNOWN', 'CONTROL_TEST_TIMEOUT', 'CONTROL_TOOL_MANIFEST_SHA_DIFFERS',
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
             'script/jenkins/verify-remote.py': inbox / 'verify-remote.py',
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
    for key, name in (('verifier', 'verify-remote.py'), ('tools', 'ecs-tool-runtime.py')):
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


def remove_owned_tree(path, expected):
    path = owned(path, directory=True); info = path.lstat()
    need([info.st_dev, info.st_ino, info.st_uid] == expected and shutil.rmtree.avoids_symlink_attacks,
         'CONTROL_SCRATCH_IDENTITY_CHANGED')
    shutil.rmtree(path)
    need(not path.exists() and not path.is_symlink(), 'CONTROL_SCRATCH_CLEANUP_UNKNOWN')


def run(args):
    need(sys.platform == 'linux' and os.getuid() == os.geteuid() == os.getgid() == 1000, 'CONTROL_ECS_UID_1000_REQUIRED')
    need(TAG.fullmatch(args.tag) and re.fullmatch(r'[a-f0-9]{40}', args.commit)
         and args.tag.endswith('-' + args.commit[:12]) and SHA.fullmatch(args.source_sha256)
         and SHA.fullmatch(args.tool_manifest_sha256), 'CONTROL_FIXED_CONTEXT_REQUIRED')
    root = owned(Path(args.root), directory=True)
    source_archive, allocation, modules = fixed_modules(root, args)
    identity = modules['verifier'].ecs_identity(args.instance_id, args.machine_id)
    context = {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256}
    inbox = owned(root / 'inbox' / args.tag, directory=True)
    base = inbox / 'control-preflight'; need(not base.exists() and not base.is_symlink(), 'FRESH_CONTROL_ATTEMPT_REQUIRED')
    disk = os.statvfs(root)
    need(disk.f_bavail * disk.f_frsize >= 2 * 1024 ** 3 + allocation + 144 * MIB, 'CONTROL_SOURCE_AND_SCRATCH_RESERVE_REQUIRED')
    base.mkdir(mode=0o700); source = base / 'control-checkout'; source.mkdir(mode=0o700)
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
            receipt['status'] = 'CONTROL_PREFLIGHT_PASS'
        write(output / 'receipt.json', receipt)
    return receipt, output / 'receipt.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id', 'tool-manifest-sha256'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    def interrupted(_signal, _frame): raise RuntimeError('CONTROL_PREFLIGHT_INTERRUPTED')
    for event in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT): signal.signal(event, interrupted)
    try:
        receipt, path = run(args)
        print(json.dumps({'status': receipt['status'], 'release': args.tag, 'commit': args.commit,
            'sourceSha256': args.source_sha256, 'receipt': str(path), 'receiptSha256': digest(path),
            'reports': receipt['reports'], 'fullProjectVerified': False}))
        return 0 if receipt['status'] == 'CONTROL_PREFLIGHT_PASS' else 2
    except Exception as error:
        print(json.dumps({'status': 'CONTROL_PREFLIGHT_REJECTED', **safe_failure(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
