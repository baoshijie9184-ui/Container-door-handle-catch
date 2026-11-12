"""Short-lived, fixed-image ECS tool executors; never a Jenkins agent or production exec.

System Python controls Docker. Maven/JDK, Node/npm and Python test dependencies
remain in explicit immutable images. This build's checkout and its registered
third-party-only Maven repository are writable;
its original host identity and Docker client are mounted read-only. The socket
is required by the trusted migration tests, not an untrusted-code sandbox.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
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
from urllib.request import ProxyHandler, Request, build_opener


LABEL = 'io.doorhandle.ci-tool-runtime'
SHA = re.compile(r'[a-f0-9]{64}')
IMAGE = re.compile(r'sha256:[a-f0-9]{64}')
TAG = re.compile(r'ci-[0-9]+-[a-f0-9]{12}')
BINARIES = {'java': '/opt/java/openjdk/bin/java', 'mvn': '/usr/share/maven/bin/mvn',
            'node': '/usr/local/bin/node', 'npm': '/usr/local/bin/npm', 'python': '/usr/local/bin/python'}
ENVIRONMENT = {'LANG', 'LC_ALL', 'PYTHONDONTWRITEBYTECODE',
               'PYTHONNOUSERSITE', 'PYTHON_DOTENV_DISABLED', 'DOORHANDLE_ECS_INSTANCE_ID',
               'DOORHANDLE_ECS_MACHINE_ID', 'DOORHANDLE_COMPACT_MIGRATION_TESTS',
               'DOORHANDLE_COMPACT_MIGRATION_CONFIG', 'DOORHANDLE_CI_EVIDENCE_DIR',
               'DOORHANDLE_WORKER_MYSQL_TESTS', 'DOORHANDLE_WORKER_MYSQL_CONFIG',
               'DOORHANDLE_MIGRATION_JAVA'}
MEMORY = {'java': 2, 'mvn': 4, 'node': 2, 'npm': 3, 'python': 4}
NPM_NODE_OPTIONS = '--max-old-space-size=2048'
DISK_FLOOR = (2 * 1024 + 256) * 1024 ** 2
MEMORY_FLOOR = 1024 ** 3
CACHE_PROTOCOL = 'doorhandle-maven-release-cache-v1'
# Only source-reviewed original receipt digests may authorize recovery of an
# interrupted cache. Ownership of a locally discovered JSON file is insufficient.
# Authenticated against build #173's preserved successful tool-runtime command
# report (SHA256 9288a489835b301119764b1f0bddb89c119f24e82ea1722c9b57dea4aeefd79b).
MAVEN_CACHE_RECOVERY_PINS = {
    '7c42577d50d6697a5ad00e8ba980adae839cb8c3540184b7d0c5c9221d435484': {
        '30babb7b2a92c095720ed9e0562a01a9790cb9c6d14de85ee1589c8f43fce80c':
            '0f72406c98e3b050ab82229a03d71daeae9a196430da04e6d62c89f423a90306'},
    # Build #224's first Maven command completed with no cache growth before
    # SSH loss caused post-cleanup to cancel its second command. The original
    # READY receipt is preserved in ci-224-failure-diagnosis on D, not rewritten.
    'f13cd293e255d7189142b63cd6f195ef14217810cb755aa017c924ddfd16ada5': {
        '1d00eac2f5129848a756860b373190a1d928960822e01a884dc169e70acf63d5':
            'd3d549812de43946e8e5a48357c15cd4a6f121c1c16f4f14a179572f39f32d6a'}}


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def canonical(path, *, exists=True):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts
            and path.resolve(strict=exists) == path, 'Tool paths must be absolute and have no links')
    return path


def private_json(path):
    path = canonical(path)
    value = path.stat()
    require(path.is_file() and value.st_uid == os.getuid() and stat.S_IMODE(value.st_mode) == 0o600
            and 0 < value.st_size <= 1024 * 1024, 'Owned private bounded tool manifest required')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path, value):
    temporary = path.with_name(path.name + '.' + secrets.token_hex(6) + '.tmp')
    with temporary.open('x', encoding='utf8') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
    temporary.replace(path)


def maven_input(name):
    parts = Path(name).parts
    return bool(parts) and (parts[-1] == 'pom.xml' or '.mvn' in parts)


def maven_cache_definition(root, image, catalog):
    require(IMAGE.fullmatch(image) and isinstance(catalog, list) and 0 < len(catalog) <= 2048,
            'Maven cache requires fixed source inputs and an immutable tool image')
    names, total = [], 0
    for row in catalog:
        require(set(row) == {'path', 'bytes', 'sha256'} and isinstance(row['path'], str)
                and not Path(row['path']).is_absolute() and '\\' not in row['path']
                and all(part not in ('', '.', '..') for part in row['path'].split('/'))
                and maven_input(row['path']) and row['path'].split('/')[0] not in ('work', '.git')
                and type(row['bytes']) is int and 0 <= row['bytes'] <= 1024 ** 2
                and SHA.fullmatch(row['sha256']), 'Unexpected fixed Maven cache input')
        names.append(row['path']); total += row['bytes']
    require(names == sorted(set(names)) and 'pom.xml' in names and total <= 16 * 1024 ** 2,
            'Maven input catalog is incomplete, repeated or oversized')
    inputs_sha = hashlib.sha256(json.dumps(catalog, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    key = hashlib.sha256(json.dumps({'protocol': CACHE_PROTOCOL, 'inputsSha256': inputs_sha,
        'mavenImage': image}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    directory = Path(root) / 'dependency-cache' / 'maven' / key
    return {'protocol': CACHE_PROTOCOL, 'key': key, 'inputsSha256': inputs_sha, 'mavenImage': image,
            'directory': str(directory), 'repository': str(directory / 'repository'), 'inputs': catalog}


def maven_archive_inputs(archive):
    catalog = []
    with tarfile.open(archive, 'r:gz') as package:
        for entry in package:
            if not maven_input(entry.name) or entry.isdir():
                continue
            require(entry.isfile() and 0 <= entry.size <= 1024 ** 2, 'Maven source input is not a bounded regular file')
            raw = package.extractfile(entry).read(1024 ** 2 + 1)
            require(len(raw) == entry.size, 'Maven source input changed')
            if entry.name.endswith(('/maven.config', '/jvm.config', '/settings.xml')):
                require(b'maven.repo.local' not in raw and b'<localRepository>' not in raw,
                        'Fixed Maven configuration cannot override the registered dependency repository')
            catalog.append({'path': entry.name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    return sorted(catalog, key=lambda row: row['path'])


def registered_maven_cache(value):
    root = Path(value['directory']).parents[2]
    actual = value.get('mavenCache', {})
    require(actual == maven_cache_definition(root, value['images']['maven'], actual.get('inputs')),
            'Maven cache escaped its exact source/image registration')
    return actual


def cache_directory(path, *, create=False):
    path = canonical(path, exists=not create)
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    info = path.stat()
    require(path.is_dir() and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
            'Maven dependency cache must be a private owned directory without links')
    return path


def initialize_maven_cache(value):
    binding = registered_maven_cache(value)
    root = Path(value['directory']).parents[2]
    disk = os.statvfs(root)
    require(disk.f_bavail * disk.f_frsize >= DISK_FLOOR, 'Maven cache preparation requires the actual filesystem reserve')
    for path in (root / 'dependency-cache', root / 'dependency-cache/maven', Path(binding['directory']),
                 Path(binding['repository']), Path(binding['directory']) / 'receipts'):
        cache_directory(path, create=True)
    with maven_cache_lock(value):
        before = maven_cache_inventory(value)
        try:
            verify_maven_cache_state(value, before)
        except ValueError:
            recover_maven_cache(value, before)
        else:
            persist_maven_cache(value, before, before)


@contextmanager
def maven_cache_lock(value):
    import fcntl
    binding = registered_maven_cache(value)
    directory = cache_directory(Path(binding['directory']))
    file = directory / 'cache.lock'
    require(not file.is_symlink(), 'Maven cache lock cannot be redirected')
    with os.fdopen(os.open(file, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'r+b') as lock:
        info = os.fstat(lock.fileno())
        require(info.st_uid == os.getuid() and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600,
                'Maven cache lock is not private and owned')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('This Maven dependency cache is already in use') from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def maven_cache_usage(value):
    repository = cache_directory(Path(registered_maven_cache(value)['repository']))
    files, logical, allocated = 0, 0, 0
    for current, dirs, names in os.walk(repository, followlinks=False):
        allocated += Path(current).lstat().st_blocks * 512
        for name in dirs + names:
            path = Path(current) / name; info = path.lstat()
            require(not path.is_symlink() and info.st_uid == os.getuid(), 'Maven cache contains a foreign path or link')
            if path.is_file():
                require(info.st_nlink == 1 and not info.st_mode & 0o022, 'Maven cache file is linked or writable by others')
                files += 1; logical += info.st_size; allocated += info.st_blocks * 512
                require(files <= 50000 and logical <= 2 * 1024 ** 3, 'Maven dependency cache exceeds its reviewed budget')
    return {'files': files, 'bytes': logical, 'allocatedBytes': allocated}


def maven_cache_inventory(value):
    """No reactor outputs, snapshots, unchecked jars or error/temporary metadata are reusable."""
    repository = Path(registered_maven_cache(value)['repository'])
    maven_cache_usage(value)
    records, artifacts = [], []
    for path in sorted(repository.rglob('*')):
        if not path.is_file():
            continue
        name = path.relative_to(repository).as_posix(); parts = name.split('/')
        require(parts[:2] != ['com', 'ruanzhu'] and not any('SNAPSHOT' in part.upper() for part in parts),
                'Reactor or snapshot bytes cannot enter a reusable dependency cache')
        require(all(re.fullmatch(r'[A-Za-z0-9_.+\-]+', part) for part in parts), 'Unexpected Maven dependency path')
        require(path.name == '_remote.repositories' or path.name.endswith(('.jar', '.pom', '.sha1', '.sha256', '.md5', '.sha512')),
                'Partial downloads and resolver metadata cannot be marked ready')
        checksum = digest(path)
        if path.suffix in ('.jar', '.pom'):
            require(len(parts) >= 4 and re.fullmatch(re.escape(parts[-3] + '-' + parts[-2])
                    + r'(?:-[A-Za-z0-9_.+\-]+)?\.(?:jar|pom)', path.name), 'Unexpected release artifact layout')
            verified = False
            for suffix, algorithm in (('.sha256', 'sha256'), ('.sha1', 'sha1')):
                sidecar = Path(str(path) + suffix)
                if sidecar.is_file():
                    require(sidecar.stat().st_size <= 1024, 'Oversized dependency checksum sidecar')
                    supplied = sidecar.read_text(encoding='ascii').strip().split()[0]
                    expected_length = 64 if algorithm == 'sha256' else 40
                    require(re.fullmatch('[a-fA-F0-9]{' + str(expected_length) + '}', supplied), 'Invalid dependency checksum')
                    result = hashlib.new(algorithm)
                    with path.open('rb') as stream:
                        for chunk in iter(lambda: stream.read(1024 ** 2), b''): result.update(chunk)
                    require(result.hexdigest() == supplied.lower(), 'Downloaded dependency checksum mismatch')
                    verified = True
            require(verified, 'Release dependency has no verified repository checksum')
            artifacts.append([name, path.stat().st_size, checksum])
        records.append([name, path.stat().st_size, checksum])
    catalog_sha = hashlib.sha256(json.dumps(records, separators=(',', ':')).encode()).hexdigest()
    return {**maven_cache_usage(value), 'catalogSha256': catalog_sha, 'artifacts': artifacts, 'records': records}


def discard_maven_transients(value):
    """Only known generated resolver markers in this exact registered repository may be removed."""
    repository = Path(registered_maven_cache(value)['repository'])
    maven_cache_usage(value)  # Reject links/foreign files before any unlink.
    for path in repository.rglob('*'):
        if path.is_file() and (path.name.endswith(('.lastUpdated', '.part', '.part.lock', '.tmp'))
                or path.name == 'resolver-status.properties' or path.name.startswith('maven-metadata-')):
            path.unlink()


def persist_maven_cache(value, before, after, *, recovery=None):
    binding = registered_maven_cache(value)
    previous = {tuple(row) for row in before['artifacts']}
    summary = {'key': binding['key'], 'inputsSha256': binding['inputsSha256'], 'mavenImage': binding['mavenImage'],
        'scope': 'SHARED_THIRD_PARTY_RELEASE_DEPENDENCIES', 'status': 'READY',
        'beforeCatalogSha256': before['catalogSha256'], 'afterCatalogSha256': after['catalogSha256'],
        'artifactCount': len(after['artifacts']), 'reusedArtifacts': sum(tuple(row) in previous for row in after['artifacts']),
        'files': after['files'], 'bytes': after['bytes'], 'allocatedBytes': after['allocatedBytes'],
        'allocatedGrowthBytes': max(0, after['allocatedBytes'] - before['allocatedBytes'])}
    directory = Path(binding['directory'])
    state = directory / 'state.json'
    previous_receipt = (recovery['sourceReceiptSha256'] if recovery is not None
                        else private_json(state).get('receiptSha256') if state.exists() else None)
    receipt = directory / 'receipts' / (value['release'] + '-' + secrets.token_hex(6) + '.json')
    write_json(receipt, {**summary, 'release': value['release'], 'commit': value['commit'],
        'sourceSha256': value['sourceSha256'], 'identity': value['identity'], 'catalog': after['records'],
        'previousReceiptSha256': previous_receipt,
        **({'recoveryReceiptSha256': recovery['recoveryReceiptSha256']} if recovery is not None else {})})
    write_json(directory / 'state.json', {**summary, 'receipt': receipt.name, 'receiptSha256': digest(receipt)})
    return {**summary, 'receiptSha256': digest(receipt)}


def read_maven_recovery_json(path, limit):
    """Read one bounded private original without accepting replacement or linked metadata."""
    path = canonical(path)
    def metadata(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    original = path.lstat()
    require(stat.S_ISREG(original.st_mode) and original.st_uid == os.getuid() and original.st_nlink == 1
            and stat.S_IMODE(original.st_mode) == 0o600 and 0 < original.st_size <= limit,
            'Maven recovery requires a bounded private owned single-link original')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        require(metadata(opened) == metadata(original), 'Maven recovery original changed before reading')
        raw = stream.read(limit + 1)
        require(len(raw) == original.st_size and metadata(os.fstat(stream.fileno())) == metadata(original)
                and metadata(path.lstat()) == metadata(original) and canonical(path) == path,
                'Maven recovery original changed while reading')
    value = json.loads(raw.decode('utf-8-sig'))
    require(isinstance(value, dict), 'Maven recovery original must be an object')
    return value, raw, hashlib.sha256(raw).hexdigest()


def recover_maven_cache(value, before):
    """Under the caller's cache lock, recover only bytes proven by an original READY receipt."""
    binding = registered_maven_cache(value); directory = Path(binding['directory'])
    failed, failed_raw, failed_sha = read_maven_recovery_json(directory / 'state.json', 1024 ** 2)
    require(set(failed) == {'status', 'key', 'errorType'} and failed.get('status') == 'FAILED_OR_UNKNOWN'
            and failed.get('key') == binding['key'] and isinstance(failed.get('errorType'), str)
            and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,99}', failed['errorType']),
            'Only an exact matching failed or unknown Maven cache can be recovered')
    pins = MAVEN_CACHE_RECOVERY_PINS.get(binding['key'], {})
    require(isinstance(pins, dict) and pins and all(isinstance(key, str) and SHA.fullmatch(key)
            and isinstance(catalog, str) and SHA.fullmatch(catalog) for key, catalog in pins.items()),
            'Maven cache has no source-approved original recovery receipt')
    folder = cache_directory(directory / 'receipts')
    candidates = []
    for path in folder.iterdir():
        require(len(candidates) < 1024, 'Too many Maven recovery source receipts')
        match = re.fullmatch(r'ci-([0-9]+)-([a-f0-9]{12})-[a-f0-9]{12}\.json', path.name)
        require(match is not None, 'Unexpected Maven recovery source receipt name')
        candidates.append((int(match[1]), path.name, path))
    source = None
    fields = {'key', 'inputsSha256', 'mavenImage', 'scope', 'status', 'beforeCatalogSha256',
        'afterCatalogSha256', 'artifactCount', 'reusedArtifacts', 'files', 'bytes', 'allocatedBytes',
        'allocatedGrowthBytes', 'release', 'commit', 'sourceSha256', 'identity', 'catalog', 'previousReceiptSha256'}
    for _, _, path in sorted(candidates, reverse=True):
        proof, _, proof_sha = read_maven_recovery_json(path, 16 * 1024 ** 2)
        if not (pins.get(proof_sha) == before['catalogSha256']
                and set(proof) in (fields, fields | {'recoveryReceiptSha256'})
                and proof.get('status') == 'READY' and proof.get('scope') == 'SHARED_THIRD_PARTY_RELEASE_DEPENDENCIES'
                and all(proof.get(key) == binding[key] for key in ('key', 'inputsSha256', 'mavenImage'))
                and proof.get('identity') == value['identity']
                and isinstance(proof.get('sourceSha256'), str) and SHA.fullmatch(proof['sourceSha256'])
                and isinstance(proof.get('commit'), str) and re.fullmatch(r'[a-f0-9]{40}', proof['commit'])
                and isinstance(proof.get('release'), str) and TAG.fullmatch(proof['release'])
                and proof['release'].endswith('-' + proof['commit'][:12])
                and path.name.startswith(proof['release'] + '-')
                and (proof['previousReceiptSha256'] is None or isinstance(proof['previousReceiptSha256'], str)
                     and SHA.fullmatch(proof['previousReceiptSha256']))
                and ('recoveryReceiptSha256' not in proof or isinstance(proof['recoveryReceiptSha256'], str)
                     and SHA.fullmatch(proof['recoveryReceiptSha256']))
                and proof.get('catalog') == before['records']
                and proof.get('afterCatalogSha256') == before['catalogSha256']
                and isinstance(proof.get('beforeCatalogSha256'), str) and SHA.fullmatch(proof['beforeCatalogSha256'])
                and all(type(proof.get(key)) is int and proof[key] == expected for key, expected in
                    (('artifactCount', len(before['artifacts'])), ('files', before['files']),
                     ('bytes', before['bytes'])))
                and type(proof.get('allocatedBytes')) is int and proof['allocatedBytes'] >= 0
                and type(proof.get('reusedArtifacts')) is int and 0 <= proof['reusedArtifacts'] <= proof['artifactCount']
                and type(proof.get('allocatedGrowthBytes')) is int and 0 <= proof['allocatedGrowthBytes'] <= proof['allocatedBytes']):
            continue
        source = {'sourceReceipt': path.name, 'sourceReceiptSha256': proof_sha}
        break
    require(source is not None, 'No original READY Maven receipt proves the current dependency bytes')
    after = maven_cache_inventory(value)
    require(after == before, 'Maven dependency bytes changed during recovery')
    _, _, source_sha = read_maven_recovery_json(folder / source['sourceReceipt'], 16 * 1024 ** 2)
    require(source_sha == source['sourceReceiptSha256'], 'Original READY Maven receipt changed during recovery')
    current, current_raw, current_sha = read_maven_recovery_json(directory / 'state.json', 1024 ** 2)
    require(current == failed and current_raw == failed_raw and current_sha == failed_sha,
            'Failed Maven cache state changed during recovery')
    recovery_folder = cache_directory(directory / 'recoveries', create=True)
    recovery_file = recovery_folder / (value['release'] + '-' + secrets.token_hex(6) + '.json')
    write_json(recovery_file, {'schema': 1, 'kind': 'doorhandle-maven-cache-recovery', 'status': 'RECOVERY_VALIDATED',
        'release': value['release'], 'commit': value['commit'], 'sourceSha256': value['sourceSha256'],
        'identity': value['identity'], 'key': binding['key'], 'inputsSha256': binding['inputsSha256'],
        'mavenImage': binding['mavenImage'], 'catalogSha256': after['catalogSha256'],
        'failedStateBytesHex': failed_raw.hex(), 'failedStateSha256': failed_sha, **source})
    persist_maven_cache(value, before, after, recovery={**source, 'recoveryReceiptSha256': digest(recovery_file)})


def verify_maven_cache_state(value, inventory):
    binding = registered_maven_cache(value); directory = Path(binding['directory'])
    state_file = directory / 'state.json'
    if not state_file.exists():
        require(inventory['files'] == 0, 'Unregistered Maven cache bytes cannot be seeded implicitly')
        return
    state = private_json(state_file)
    require(state.get('status') == 'READY' and all(state.get(key) == binding[key]
                for key in ('key', 'inputsSha256', 'mavenImage'))
            and re.fullmatch(r'ci-[0-9]+-[a-f0-9]{12}-[a-f0-9]{12}\.json', state.get('receipt', '')),
            'Maven cache has no completed matching source/image receipt')
    receipt = canonical(directory / 'receipts' / state['receipt']); info = receipt.stat()
    require(info.st_uid == os.getuid() and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600
            and 0 < info.st_size <= 16 * 1024 ** 2 and digest(receipt) == state.get('receiptSha256'),
            'Maven dependency source receipt changed')
    proof = json.loads(receipt.read_text(encoding='utf8'))
    require(proof.get('status') == 'READY' and proof.get('key') == binding['key']
            and proof.get('identity') == value['identity'] and SHA.fullmatch(proof.get('sourceSha256', ''))
            and re.fullmatch(r'[a-f0-9]{40}', proof.get('commit', '')) and TAG.fullmatch(proof.get('release', ''))
            and proof['release'].endswith('-' + proof['commit'][:12])
            and proof.get('catalog') == inventory['records']
            and proof.get('afterCatalogSha256') == state.get('afterCatalogSha256') == inventory['catalogSha256'],
            'Maven dependency bytes changed outside their serial command receipt')


def maven_arguments(value, arguments):
    binding = registered_maven_cache(value)
    expected = '-Dmaven.repo.local=' + binding['repository']
    require(all('maven.repo.local' not in argument or argument == expected for argument in arguments)
            and sum(argument == expected for argument in arguments) <= 1,
            'Maven repository argument differs from its exact registered cache')
    selected_module = None
    verification_arguments = arguments
    if '-pl' in arguments or '-am' in arguments:
        require(len(arguments) >= 4 and arguments[-3] == '-pl' and arguments[-1] == '-am'
                and arguments.count('-pl') == arguments.count('-am') == 1,
                'One explicit Maven module selection is permitted only as the final three arguments')
        selected_module = arguments[-2]
        require(re.fullmatch(r'doorhandle-[a-z0-9]+(?:-[a-z0-9]+)*', selected_module),
                'Maven module selection requires one canonical direct project directory')
        verification_arguments = arguments[:-3]
        require(not any(re.fullmatch(r'-D(?:[A-Za-z0-9_.-]*\.)?(?:ignoreTestFailure|testFailureIgnore)(?:=.*)?', argument)
                        for argument in verification_arguments),
                'Selected-module verification cannot ignore test failures')
    allowed_flags = {'-B', '--batch-mode', '-ntp', '--no-transfer-progress', '-v', '-version', '--version', '-V', '-C', '--strict-checksums'}
    require(all(argument == expected or argument in allowed_flags or argument.startswith('-D')
                or argument in ('clean', 'test', 'verify', 'package') for argument in verification_arguments),
            'Only fixed verification phases and properties may use the shared Maven cache')
    require(not any(argument.startswith(('-Dmaven.', '-Duser.home=', '-Duser.dir=', '-Djava.home=')) and argument != expected for argument in arguments),
            'Maven cannot redirect its fixed source or tool configuration')
    checkout = Path(value['checkout'])
    if arguments not in (['-version'], ['--version'], ['-v']):
        actual_inputs = set()
        for current, dirs, names in os.walk(checkout, followlinks=False):
            dirs[:] = [name for name in dirs if name not in ('work', 'target', '.git', 'node_modules', '.venv')]
            for name in names:
                relative = (Path(current) / name).relative_to(checkout).as_posix()
                if maven_input(relative): actual_inputs.add(relative)
        require(actual_inputs == {row['path'] for row in binding['inputs']}, 'Maven source input set changed')
        for row in binding['inputs']:
            file = canonical(checkout / row['path'])
            require(file.is_file() and file.stat().st_size == row['bytes'] and digest(file) == row['sha256'],
                    'Maven source input differs from the exact cache registration')
    if selected_module is not None:
        from xml.etree import ElementTree as ET
        checkout = canonical(checkout)
        pom = canonical(checkout / 'pom.xml')
        root_input = next(row for row in binding['inputs'] if row['path'] == 'pom.xml')
        with pom.open('rb') as stream:
            content = stream.read(root_input['bytes'] + 1)
        require(len(content) == root_input['bytes'] and hashlib.sha256(content).hexdigest() == root_input['sha256']
                and b'<!DOCTYPE' not in content.upper() and b'<!ENTITY' not in content.upper(),
                'Selected Maven modules require the unchanged entity-free bound root POM')
        try:
            project = ET.fromstring(content)
        except ET.ParseError:
            raise ValueError('Selected Maven modules require a valid bound root POM') from None
        namespace = '{http://maven.apache.org/POM/4.0.0}' if project.tag == '{http://maven.apache.org/POM/4.0.0}project' else ''
        require(project.tag == namespace + 'project', 'Selected Maven modules require the root project POM')
        modules = [(node.text or '').strip() for node in project.findall(namespace + 'modules/' + namespace + 'module')]
        require(modules.count(selected_module) == 1, 'Selected Maven module is not declared exactly once by the bound root POM')
        directory = canonical(checkout / selected_module)
        module_pom = canonical(directory / 'pom.xml')
        require(directory.is_dir() and directory.is_relative_to(checkout) and module_pom.is_file()
                and selected_module + '/pom.xml' in {row['path'] for row in binding['inputs']},
                'Selected Maven module must remain inside the bound checkout with its registered POM')
    return ['-C', *([] if expected in arguments else [expected]), *arguments]


def verify_maven_source(value):
    archive = canonical(Path(value['directory']).parent / 'source.tar.gz')
    require(digest(archive) == value['sourceSha256'], 'Maven cache source archive changed')
    with tarfile.open(archive, 'r:gz') as package:
        require(package.pax_headers.get('comment') == value['commit'], 'Maven cache source commit changed')
    require(maven_archive_inputs(archive) == registered_maven_cache(value)['inputs'],
            'Maven dependency key differs from the fixed source archive bytes')


def public_maven_cache(value, proof):
    if proof is None:
        return None
    require(isinstance(proof, dict) and proof.get('key') == registered_maven_cache(value)['key'],
            'Maven dependency evidence belongs to another source/image key')
    if proof.get('status') == 'FAILED_OR_UNKNOWN':
        require(set(proof) == {'status', 'key', 'errorType'} and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,99}', proof['errorType']),
                'Unexpected private Maven dependency failure metadata')
        return dict(proof)
    hashes = {'key', 'inputsSha256', 'beforeCatalogSha256', 'afterCatalogSha256', 'receiptSha256'}
    numbers = {'artifactCount', 'reusedArtifacts', 'files', 'bytes', 'allocatedBytes', 'allocatedGrowthBytes'}
    fields = hashes | numbers | {'mavenImage', 'scope', 'status'}
    require(set(proof) == fields and all(SHA.fullmatch(proof[key]) for key in hashes)
            and all(type(proof[key]) is int and proof[key] >= 0 for key in numbers)
            and proof['mavenImage'] == value['images']['maven'] and proof['status'] == 'READY'
            and proof['scope'] == 'SHARED_THIRD_PARTY_RELEASE_DEPENDENCIES', 'Unexpected Maven dependency evidence')
    return {key: proof[key] for key in sorted(fields)}


def docker(program, *arguments, timeout=45):
    result = subprocess.run([str(program), *arguments], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, check=False)
    require(result.returncode == 0, 'ECS tool Docker operation failed; retain this build evidence')
    return result.stdout


def identity_guard(expected):
    require(sys.platform == 'linux' and Path('/etc/machine-id').read_text().strip() == expected['machineId'],
            'ECS tool machine identity differs')
    opener = build_opener(ProxyHandler({}))
    base = 'http://100.100.100.200/latest/'
    with opener.open(Request(base + 'api/token', data=b'', method='PUT', headers={
            'X-aliyun-ecs-metadata-token-ttl-seconds': '60'}), timeout=3) as response:
        token = response.read(4096).decode()
    with opener.open(Request(base + 'meta-data/instance-id', headers={
            'X-aliyun-ecs-metadata-token': token}), timeout=3) as response:
        require(response.read(256).decode().strip() == expected['instanceId'],
                'ECS tool instance identity differs')


def validate_manifest(value, *, root, tag, commit, source_sha, identity):
    require(isinstance(value, dict), 'Tool manifest must be an object')
    expected = {'schema': 1, 'kind': 'doorhandle-ecs-tool-runtime', 'release': tag,
                'commit': commit, 'sourceSha256': source_sha, 'identity': identity}
    require(all(value.get(key) == entry for key, entry in expected.items())
            and TAG.fullmatch(tag) and re.fullmatch(r'[a-f0-9]{40}', commit)
            and tag.endswith('-' + commit[:12]) and SHA.fullmatch(source_sha),
            'Tool runtime belongs to another commit, source, build or ECS')
    base = canonical(root)
    folder = base / 'inbox' / tag / 'tool-runtime'
    require(value.get('directory') == str(folder)
            and value.get('checkout') == str(base / 'verification' / tag / 'checkout')
            and re.fullmatch(r'[a-f0-9]{24}', value.get('token', ''))
            and value.get('uid') == os.getuid() and value.get('gid') == os.getgid(),
            'Tool runtime directory or execution owner changed')
    images = value.get('images', {})
    require(isinstance(images, dict) and set(images) == {'maven', 'node', 'python'}
            and all(isinstance(v, str) and IMAGE.fullmatch(v) for v in images.values()),
            'Tool images must use complete immutable image IDs')
    files = value.get('files', {})
    require(isinstance(files, dict) and set(files) == {'executor.py', *BINARIES}
            and all(isinstance(v, str) and SHA.fullmatch(v) for v in files.values()), 'Tool launcher source catalog is incomplete')
    registered_maven_cache(value)
    return folder


def admit(path, *, root, tag, commit, source_sha, identity, source):
    path = canonical(path)
    value = private_json(path)
    folder = validate_manifest(value, root=root, tag=tag, commit=commit, source_sha=source_sha, identity=identity)
    require(path == folder / 'manifest.json' and canonical(folder) == folder,
            'The private tool registration escaped this build inbox')
    for name, sha in value['files'].items():
        file = canonical(folder / name)
        require(file.is_file() and file.stat().st_uid == os.getuid() and not file.stat().st_mode & 0o022
                and digest(file) == sha, 'A pinned tool launcher changed')
    source_file = Path(__file__).resolve() if Path(source) == folder else Path(source) / 'script/jenkins/ecs-tool-runtime.py'
    require(value['files']['executor.py'] == digest(source_file),
            'The admitted executor differs from the fixed source checkout')
    return value, digest(path)


def release_identity(value, candidate_file):
    """Bind Java migration to the same release, source archive and Jenkins jar."""
    folder = canonical(value['directory'])
    root = folder.parents[2]
    source = canonical(root / 'releases' / value['release'])
    candidate_file = canonical(candidate_file)
    require(candidate_file == source / 'candidate-build.json', 'Java release is outside this immutable build')
    archive = canonical(root / 'inbox' / value['release'] / 'source.tar.gz')
    require(digest(archive) == value['sourceSha256'], 'Java release archive changed')
    # Check original archive bytes, not a Git blob or a CRLF-normalized worktree.
    seen, total = set(), 0
    with tarfile.open(archive, 'r:gz') as package:
        for entry in package:
            name = Path(entry.name)
            require(not name.is_absolute() and '..' not in name.parts and '\\' not in entry.name
                    and (entry.isdir() or entry.isfile()), 'Unsafe Java release source archive')
            if entry.isdir():
                continue
            total += entry.size
            require(entry.name not in seen and name.parts[0] not in ('work', '.git')
                    and 0 <= entry.size <= 128 * 1024 ** 2 and total <= 512 * 1024 ** 2
                    and len(seen) < 50000, 'Java release source archive exceeds its bounds')
            seen.add(entry.name)
            path = canonical(source / name)
            require(path.is_relative_to(source) and path.is_file() and path.stat().st_size == entry.size
                    and digest(path) == hashlib.sha256(package.extractfile(entry).read()).hexdigest(),
                    'Java release differs from the fixed source archive')
        require(package.pax_headers.get('comment') == value['commit']
                and 'script/jenkins/ecs-tool-runtime.py' in seen,
                'Java release is missing its pinned executor/commit')
    require(digest(source / 'script/jenkins/ecs-tool-runtime.py') == value['files']['executor.py'],
            'Java release executor differs from its manifest')
    build = private_json(candidate_file)
    require(all(build.get(key) == expected for key, expected in {
        'schemaVersion': 1, 'kind': 'doorhandle-compact-candidate-build', 'status': 'BUILT',
        'release': value['release'], 'commit': value['commit'], 'sourceSha256': value['sourceSha256'],
        'ecs': value['identity']}.items()), 'Java candidate belongs to another source or ECS')
    artifact_file = canonical(root / 'inbox' / value['release'] / 'build-artifacts.json')
    artifact = private_json(artifact_file)
    jar = canonical(source / 'work/candidate-app.jar')
    input_jar = canonical(root / 'inbox' / value['release'] / 'application.jar')
    require(all(artifact.get(key) == expected for key, expected in {
        'schema': 1, 'kind': 'doorhandle-compact-fixture-artifacts', 'release': value['release'],
        'commit': value['commit'], 'sourceSha256': value['sourceSha256']}.items())
        and build.get('buildArtifactPlanSha256') == digest(artifact_file)
        and type(artifact.get('applicationJarBytes')) is int
        and 0 < artifact['applicationJarBytes'] <= 512 * 1024 ** 2
        and jar.stat().st_size == input_jar.stat().st_size == build.get('applicationJarBytes') == artifact['applicationJarBytes']
        and digest(jar) == digest(input_jar) == build.get('applicationJarSha256') == artifact.get('applicationJarSha256'),
        'Java migration must use the exact Jenkins application jar')
    return {'schema': 1, 'kind': 'doorhandle-ecs-java-release', 'release': value['release'],
            'commit': value['commit'], 'sourceSha256': value['sourceSha256'], 'identity': value['identity'],
            'manifestSha256': digest(folder / 'manifest.json'), 'candidateBuildSha256': digest(candidate_file),
            'source': str(source), 'work': str(canonical(source / 'work')), 'applicationJar': str(jar),
            'applicationJarSha256': digest(jar), 'applicationJarBytes': jar.stat().st_size}


def admit_release(value, candidate_file):
    proof = release_identity(value, candidate_file)
    path = Path(value['directory']) / 'java-release.json'
    require(not path.exists(), 'Java release registration cannot overwrite an existing outcome')
    write_json(path, proof)
    return {'status': 'ADMITTED', 'release': value['release'], 'javaReleaseSha256': digest(path)}


def java_release(value):
    folder = Path(value['directory'])
    file = folder / 'java-release.json'
    require(file.exists(), 'Java release has not been admitted for this build')
    proof = private_json(file)
    expected = release_identity(value, folder.parents[2] / 'releases' / value['release'] / 'candidate-build.json')
    require(proof == expected, 'Pinned Java release, source, jar or manifest changed')
    return proof


def release_arguments(proof, arguments):
    prefix = ['-Dloader.main=com.ruanzhu.doorhandle.module.ai.workbench.CompactWorkbenchMigrationCli',
              '-cp', proof['applicationJar'], 'org.springframework.boot.loader.launch.PropertiesLauncher', '--config']
    require(arguments[:5] == prefix and len(arguments) == 8 and arguments[6] == '--output',
            'Release Java is restricted to the fixed Workbench migration entry point')
    work = canonical(proof['work'])
    config, output = canonical(arguments[5]), canonical(arguments[7], exists=False)
    require(config.is_file() and config.is_relative_to(work) and output.is_relative_to(work)
            and not output.exists(), 'Java migration private inputs/receipt escaped this release work directory')
    return work


def runtime_limits(tool):
    return {'containerMemoryBytes': MEMORY[tool] * 1024 ** 3,
            'containerMemorySwapBytes': MEMORY[tool] * 1024 ** 3,
            'nodeOptions': NPM_NODE_OPTIONS if tool == 'npm' else None}


def observed_runtime_limits(tool, row):
    options = [entry.partition('=')[2] for entry in row['Config'].get('Env') or []
               if entry.partition('=')[0] == 'NODE_OPTIONS']
    expected = runtime_limits(tool)
    require(options == ([expected['nodeOptions']] if tool == 'npm' else []),
            'Tool Node options differ from the fixed executor configuration')
    actual = {'containerMemoryBytes': row['HostConfig'].get('Memory'),
              'containerMemorySwapBytes': row['HostConfig'].get('MemorySwap'),
              'nodeOptions': options[0] if options else None}
    require(actual == expected, 'Tool runtime limits differ from the fixed executor configuration')
    return actual


def owned_row(program, value, container):
    require(re.fullmatch(r'[a-f0-9]{64}', container), 'Tool container ID is invalid')
    row = json.loads(docker(program, 'inspect', container))[0]
    labels = row.get('Config', {}).get('Labels') or {}
    tool = labels.get('io.doorhandle.tool')
    role = 'maven' if tool in ('java', 'mvn') else 'node' if tool in ('node', 'npm') else 'python'
    host = row['HostConfig']
    require(tool in BINARIES and row['Id'] == container and labels.get(LABEL) == value['token']
            and labels.get('io.doorhandle.release') == value['release']
            and labels.get('io.doorhandle.source') == value['sourceSha256']
            and row['Image'] == value['images'][role]
            and re.fullmatch('/doorhandle-ci-tool-' + value['token'] + '-[a-f0-9]{12}', row.get('Name', ''))
            and host['RestartPolicy']['Name'] == 'no' and host['NetworkMode'] == 'host'
            and host.get('ReadonlyRootfs') is True and host.get('Privileged') is False
            and host.get('Memory') == MEMORY[tool] * 1024 ** 3
            and host.get('MemorySwap') == MEMORY[tool] * 1024 ** 3
            and set(host.get('CapDrop') or ()) == {'ALL'}
            and 'no-new-privileges:true' in (host.get('SecurityOpt') or ())
            and row['Config']['Entrypoint'] == [BINARIES[tool]]
            and row['Config']['User'] == str(value['uid']) + ':' + str(value['gid']),
            'Tool cleanup may only act on this exact build and owner')
    observed_runtime_limits(tool, row)
    folder = Path(value['directory'])
    allowed = {(str(folder), str(folder)): False,
               (str(folder / 'receipts'), str(folder / 'receipts')): True,
               ('/etc/machine-id', '/etc/machine-id'): False}
    if tool == 'python':
        allowed[(str(docker_socket()), '/var/run/docker.sock')] = True
        allowed[(value['docker'], value['docker'])] = False
    if tool == 'mvn':
        cache = registered_maven_cache(value)
        allowed[(cache['repository'], cache['repository'])] = True
        require(labels.get('io.doorhandle.maven-cache') == cache['key'], 'Maven tool cache identity changed')
    release = None
    if labels.get('io.doorhandle.java-release') is not None:
        require(tool == 'java', 'Only Java may mount an admitted candidate release')
        release = java_release(value)
        require(labels['io.doorhandle.java-release'] == digest(folder / 'java-release.json'),
                'Java container release registration changed')
        allowed[(release['source'], release['source'])] = False
    writable = []
    for mount in row.get('Mounts', []):
        if mount['Type'] == 'tmpfs':
            require(mount['Destination'] == '/tmp', 'Unexpected tool temporary mount')
            continue
        # The selected official tool images declare no persistent data volumes.
        require(mount['Type'] == 'bind', 'Unexpected tool volume cannot be cleaned automatically')
        pair = (mount['Source'], mount['Destination'])
        if pair in allowed:
            require(mount['RW'] is allowed.pop(pair), 'Tool bind permissions changed')
        else:
            permitted = (release['work'],) if release else (value['checkout'], str(folder / 'probe'))
            require(pair[0] == pair[1] and pair[0] in permitted
                    and mount['RW'] is True, 'Tool bind escaped this build checkout')
            writable.append(pair[0])
    require(not allowed and len(writable) == 1, 'Tool mount admission is incomplete')
    return row


def stop_container(program, value, container, *, remove=True):
    row = owned_row(program, value, container)
    if row['State'].get('Paused'):
        docker(program, 'unpause', container)
    if row['State']['Running']:
        docker(program, 'stop', '--time', '10', container, timeout=25)
    final = owned_row(program, value, container)
    require(not final['State']['Running'] and not final['State'].get('Restarting') and final['State']['Pid'] == 0,
            'The owned tool process did not stop')
    if remove:
        # No named volume is accepted; -v only removes image-created anonymous
        # volumes belonging to this disposable container, never bind data.
        docker(program, 'rm', '--volumes', container)
    return {'containerId': container, 'image': final['Image'], 'pid': 0,
            'exitCode': final['State']['ExitCode'], 'removed': remove}


def stop_execution(value):
    """Cancel owned execution without racing the wrapper's receipt/cache cleanup."""
    identity_guard(value['identity'])
    program = canonical(value['docker'])
    containers = docker(program, 'ps', '-aq', '--no-trunc', '--filter', 'label=' + LABEL + '=' + value['token']).decode().split()
    stopped, errors = [], []
    for container in containers:
        try:
            stopped.append(stop_container(program, value, container, remove=False))
        except BaseException as error:
            errors.append({'containerId': container, 'errorType': type(error).__name__})
    require(not errors, 'Owned tool execution cancellation was not confirmed')
    return {'status': 'EXECUTION_STOPPED', 'release': value['release'], 'containers': stopped,
            'containerRemovalDeferredToWrapper': True}


def cleanup(value):
    identity_guard(value['identity'])
    program = canonical(value['docker'])
    containers = docker(program, 'ps', '-aq', '--no-trunc', '--filter', 'label=' + LABEL + '=' + value['token']).decode().split()
    stopped, errors = [], []
    for container in containers:
        try:
            stopped.append(stop_container(program, value, container))
        except BaseException as error:
            # Continue admitting/cleaning the other owned IDs even if one failed.
            errors.append({'containerId': container, 'errorType': type(error).__name__})
    remaining = docker(program, 'ps', '-aq', '--no-trunc', '--filter', 'label=' + LABEL + '=' + value['token']).decode().split()
    if remaining or errors:
        write_json(Path(value['directory']) / 'cleanup-failed.json', {
            'status': 'FAILED_OR_UNKNOWN', 'release': value['release'], 'containers': stopped,
            'remaining': remaining, 'errors': errors})
        raise RuntimeError('Owned tool containers remain or could not be admitted for cleanup')
    return {'status': 'STOPPED', 'release': value['release'], 'containers': stopped,
            'remaining': [], 'manifestSha256': digest(Path(value['directory']) / 'manifest.json')}


def evidence(value, stopped):
    """Export hashes and observed exits only; arguments and private env stay on ECS."""
    require(stopped.get('status') == 'STOPPED' and stopped.get('remaining') == [],
            'Tool evidence requires actual owned-container cleanup')
    folder = Path(value['directory']) / 'receipts'
    files = sorted(folder.iterdir())
    require(len(files) <= 1024, 'Too many tool command receipts')
    commands = []
    for file in files:
        require(re.fullmatch(r'doorhandle-ci-tool-' + value['token'] + r'-[a-f0-9]{12}\.json', file.name),
                'Unexpected tool receipt path')
        item = private_json(file)
        require(item.get('kind') == 'doorhandle-ecs-tool-command'
                and item.get('release') == value['release'] and item.get('commit') == value['commit']
                and item.get('sourceSha256') == value['sourceSha256'] and item.get('tool') in BINARIES
                and (item.get('containerId') is None or SHA.fullmatch(item['containerId']))
                and SHA.fullmatch(item.get('argumentsSha256', '')),
                'Tool command receipt belongs to another execution')
        cleaned = item.get('cleanup')
        if cleaned is not None:
            require(set(cleaned) == {'containerId', 'image', 'pid', 'exitCode', 'removed'}
                    and cleaned['containerId'] == item['containerId'] and cleaned['image'] in value['images'].values()
                    and cleaned['pid'] == 0 and type(cleaned['exitCode']) is int and cleaned['removed'] is True,
                    'Tool command cleanup receipt is invalid')
        require(item.get('status') in ('EXITED', 'FAILED_OR_UNKNOWN')
                and (item.get('exitCode') is None or type(item['exitCode']) is int),
                'Tool command exit status is invalid')
        limits = item.get('runtimeLimits')
        require((limits is None and item['status'] == 'FAILED_OR_UNKNOWN')
                or limits == runtime_limits(item['tool']), 'Tool command runtime limits are missing or changed')
        commands.append({'receiptSha256': digest(file), 'tool': item['tool'], 'containerId': item['containerId'],
                         'argumentsSha256': item['argumentsSha256'], 'status': item['status'],
                         'exitCode': item.get('exitCode'), 'cleanup': cleaned,
                         'resourceLimitTriggered': item.get('resourceLimitTriggered', False),
                         'resourceMonitoring': item.get('resourceMonitoring'),
                         'runtimeLimits': limits,
                         'mavenDependencyCache': public_maven_cache(value, item.get('mavenDependencyCache'))})
    return {'schema': 1, 'kind': 'doorhandle-ecs-tool-evidence', 'release': value['release'],
            'commit': value['commit'], 'sourceSha256': value['sourceSha256'],
            'manifestSha256': digest(Path(value['directory']) / 'manifest.json'),
            'images': value['images'], 'commands': commands, 'cleanup': stopped,
            'capacityVerdict': 'CONTROLLED_MEASUREMENT'}


def safe_environment(value, original, directory):
    env = {key: entry for key, entry in original.items() if key in ENVIRONMENT}
    require('DOORHANDLE_MIGRATION_JAVA' not in env
            or env['DOORHANDLE_MIGRATION_JAVA'] == str(Path(value['directory']) / 'java'),
            'Migration Java must be this immutable registration wrapper')
    home = directory / 'work' / 'tool-home' if directory == Path(value['checkout']) else directory / 'home'
    temporary = home / 'tmp'
    temporary.mkdir(mode=0o700, parents=True, exist_ok=True)
    env.update(HOME=str(home), TMPDIR=str(temporary), PYTHONDONTWRITEBYTECODE='1',
               PYTHONNOUSERSITE='1', PYTHON_DOTENV_DISABLED='1', PYTHONPATH='',
               npm_config_cache=str(home / 'npm-cache'),
               DOORHANDLE_ECS_INSTANCE_ID=value['identity']['instanceId'],
               DOORHANDLE_ECS_MACHINE_ID=value['identity']['machineId'])
    return env, home


def docker_socket():
    path = canonical(Path('/var/run/docker.sock').resolve(strict=True))
    require(stat.S_ISSOCK(path.stat().st_mode), 'The existing ECS Docker socket is unavailable')
    return path


def command(value, tool, arguments, cwd, environment):
    require(tool in BINARIES and isinstance(arguments, list) and all(isinstance(v, str) and '\x00' not in v for v in arguments),
            'Only the registered tool command is allowed')
    checkout = Path(value['checkout'])
    folder = canonical(value['directory'])
    actual = canonical(cwd)
    release = None
    if actual == checkout or actual.is_relative_to(checkout):
        canonical(checkout)
        writable = checkout
    elif tool == 'java' and actual == folder.parents[2] / 'releases' / value['release']:
        release = java_release(value)
        writable = release_arguments(release, arguments)
    else:
        require(arguments in (['-version'], ['--version'], ['-v']),
                'Tool execution outside this checkout is restricted to version admission')
        writable = folder / 'probe'
        writable.mkdir(mode=0o700, exist_ok=True)
        actual = writable
    if tool == 'mvn':
        arguments = maven_arguments(value, arguments)
    env, home = safe_environment(value, environment, writable)
    role = 'maven' if tool in ('java', 'mvn') else 'node' if tool in ('node', 'npm') else 'python'
    image = value['images'][role]
    name = 'doorhandle-ci-tool-' + value['token'] + '-' + secrets.token_hex(6)
    args = [value['docker'], 'create', '-i', '--name', name, '--network', 'host', '--restart', 'no',
            '--user', str(value['uid']) + ':' + str(value['gid']), '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--pids-limit', '512', '--cpus', '2',
            '--memory', str(MEMORY[tool]) + 'g', '--memory-swap', str(MEMORY[tool]) + 'g',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=536870912',
            '--log-driver', 'json-file', '--log-opt', 'max-size=10m', '--log-opt', 'max-file=1',
            '--label', LABEL + '=' + value['token'], '--label', 'io.doorhandle.release=' + value['release'],
            '--label', 'io.doorhandle.source=' + value['sourceSha256'], '--label', 'io.doorhandle.tool=' + tool,
            '--workdir', str(actual), '--entrypoint', BINARIES[tool]]
    binds = [(str(writable), str(writable), False), (str(folder), str(folder), True),
             (str(folder / 'receipts'), str(folder / 'receipts'), False),
             ('/etc/machine-id', '/etc/machine-id', True)]
    if release:
        binds.append((release['source'], release['source'], True))
        args += ['--label', 'io.doorhandle.java-release=' + digest(folder / 'java-release.json')]
    if tool == 'mvn':
        cache = registered_maven_cache(value)
        cache_directory(Path(cache['repository']))
        binds.append((cache['repository'], cache['repository'], False))
        args += ['--label', 'io.doorhandle.maven-cache=' + cache['key']]
    # The probe lies beneath the read-only registration folder; add the more
    # specific writable bind after its parent so only probe output can change.
    binds.sort(key=lambda item: len(Path(item[1]).parts))
    if tool == 'python':
        socket = docker_socket()
        args += ['--group-add', str(socket.stat().st_gid)]
        binds += [(str(socket), '/var/run/docker.sock', False), (value['docker'], value['docker'], True)]
    for source, target, readonly in binds:
        require(',' not in source and ',' not in target, 'Docker bind paths cannot contain commas')
        args += ['--mount', 'type=bind,src=' + source + ',dst=' + target + (',readonly' if readonly else '')]
    if role == 'maven':
        env.update(JAVA_HOME='/opt/java/openjdk', PATH='/opt/java/openjdk/bin:/usr/local/bin:/usr/bin:/bin',
                   MAVEN_CONFIG=str(home / '.m2'))
        env['JAVA_TOOL_OPTIONS'] = ('-Xmx1536m -XX:MaxMetaspaceSize=512m -Duser.home=' + str(home)
            + ' -Djava.io.tmpdir=' + str(home / 'tmp') + ' -Djansi.tmpdir=' + str(home / 'tmp'))
    else:
        env['PATH'] = '/usr/local/bin:/usr/bin:/bin'
    if tool == 'npm':
        # Keep 1 GiB of the existing 3 GiB container for native allocations and
        # npm. Never inherit caller NODE_OPTIONS or apply this heap to 2 GiB node.
        env['NODE_OPTIONS'] = NPM_NODE_OPTIONS
    if role == 'python':
        data = home / 'mem0'
        data.mkdir(mode=0o700, exist_ok=True)
        env.update(MEM0_DATA_DIR=str(data), MEM0_TELEMETRY='false', ANONYMIZED_TELEMETRY='false')
    for key, entry in sorted(env.items()):
        require('\x00' not in entry, 'Invalid tool environment')
        args += ['--env', key + '=' + entry]
    return args + [image, *arguments], name


def launch(path, tool, arguments):
    require(sys.platform == 'linux', 'Tool processes may only execute on ECS')
    value = private_json(path)
    root = Path(value['directory']).parents[2]
    value, _ = admit(path, root=root, tag=value['release'], commit=value['commit'], source_sha=value['sourceSha256'],
                     identity=value['identity'], source=Path(value['directory']))
    identity_guard(value['identity'])
    return launch_admitted(value, tool, arguments)


def resource_probe(value):
    disk = os.statvfs(value['directory'])
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        name, _, entry = line.partition(':')
        if name == 'MemAvailable':
            memory[name] = int(entry.split()[0]) * 1024
    require('MemAvailable' in memory, 'ECS memory availability cannot be measured')
    return {'capturedAtUnix': time.time(), 'diskAvailableBytes': disk.f_bavail * disk.f_frsize,
            'memoryAvailableBytes': memory['MemAvailable']}


def observe_resources(value, record, file):
    probe = resource_probe(value)
    monitoring = record.setdefault('resourceMonitoring', {
        'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'pollIntervalSeconds': 2,
        'diskFloorBytes': DISK_FLOOR, 'memoryFloorBytes': MEMORY_FLOOR, 'samples': 0,
        'minimumDiskAvailableBytes': probe['diskAvailableBytes'],
        'minimumMemoryAvailableBytes': probe['memoryAvailableBytes']})
    monitoring['samples'] += 1
    monitoring['latestProbe'] = probe
    for source, target in (('diskAvailableBytes', 'minimumDiskAvailableBytes'),
                           ('memoryAvailableBytes', 'minimumMemoryAvailableBytes')):
        monitoring[target] = min(monitoring[target], probe[source])
    if record.get('tool') == 'mvn':
        # The shared repository is explicitly separate from this checkout's owned outputs.
        monitoring['sharedMavenDependencyCache'] = {'key': registered_maven_cache(value)['key'],
            'scope': 'SHARED_THIRD_PARTY_RELEASE_DEPENDENCIES', **maven_cache_usage(value)}
    if probe['diskAvailableBytes'] < DISK_FLOOR or probe['memoryAvailableBytes'] < MEMORY_FLOOR:
        record.update(status='FAILED_OR_UNKNOWN', resourceLimitTriggered=True)
        write_json(file, record)
        raise RuntimeError('Owned tool resource floor reached; this attempt must stop')


def launch_admitted(value, tool, arguments):
    if tool == 'mvn':
        verify_maven_source(value)
        with maven_cache_lock(value):
            before = maven_cache_inventory(value)
            verify_maven_cache_state(value, before)
            return launch_command(value, tool, arguments, before)
    return launch_command(value, tool, arguments)


def launch_command(value, tool, arguments, cache_before=None):
    args, name = command(value, tool, arguments, Path.cwd(), dict(os.environ))
    program = canonical(value['docker'])
    record = {'kind': 'doorhandle-ecs-tool-command', 'release': value['release'], 'commit': value['commit'],
              'sourceSha256': value['sourceSha256'], 'tool': tool, 'containerId': None,
              'argumentsSha256': hashlib.sha256(json.dumps(arguments, ensure_ascii=True).encode()).hexdigest(),
              'startedAtUnix': time.time(), 'status': 'FAILED_OR_UNKNOWN'}
    file = Path(value['directory']) / 'receipts' / (name + '.json')
    write_json(file, record)
    process, container = None, None
    try:
        observe_resources(value, record, file)
        container = docker(program, *args[1:]).decode().strip()
        require(re.fullmatch(r'[a-f0-9]{64}', container), 'Docker did not return an owned tool ID')
        record['containerId'] = container; write_json(file, record)
        observed = owned_row(program, value, container)
        record['runtimeLimits'] = observed_runtime_limits(tool, observed)
        write_json(file, record)
        process = subprocess.Popen([str(program), 'start', '-a', '-i', container])
        while True:
            observe_resources(value, record, file)
            try:
                result = process.wait(timeout=2)
                break
            except subprocess.TimeoutExpired:
                pass
        observe_resources(value, record, file)
        observed = owned_row(program, value, container)
        require(not observed['State']['Running'] and not observed['State'].get('OOMKilled')
                and result == observed['State']['ExitCode'],
                'Tool attachment result differs from the actual container')
        record.update(status='EXITED', exitCode=result)
        return result
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=3)
        try:
            if container and re.fullmatch(r'[a-f0-9]{64}', container):
                record['cleanup'] = stop_container(program, value, container)
            if record.get('resourceLimitTriggered'):
                record['resourceAbortCleanup'] = cleanup(value)
        finally:
            if tool == 'mvn':
                try:
                    require(container is None or record.get('cleanup', {}).get('removed') is True,
                            'Maven dependency bytes cannot be prepared while its tool may still run')
                    # Even source-test failure can retain successfully verified third-party downloads.
                    discard_maven_transients(value)
                    after = maven_cache_inventory(value)
                    record['mavenDependencyCache'] = persist_maven_cache(value, cache_before, after)
                except BaseException as error:
                    record.update(status='FAILED_OR_UNKNOWN', mavenDependencyCache={'status': 'FAILED_OR_UNKNOWN',
                        'key': registered_maven_cache(value)['key'], 'errorType': type(error).__name__})
                    write_json(Path(registered_maven_cache(value)['directory']) / 'state.json', record['mavenDependencyCache'])
                    record['finishedAtUnix'] = time.time(); write_json(file, record)
                    raise
            record['finishedAtUnix'] = time.time()
            write_json(file, record)


def prepare(args):
    require(sys.platform == 'linux', 'Tool preparation may only execute on ECS')
    root = canonical(args.root)
    require(TAG.fullmatch(args.tag) and args.tag.endswith('-' + args.commit[:12])
            and re.fullmatch(r'[a-f0-9]{40}', args.commit) and SHA.fullmatch(args.source_sha256),
            'Exact source and release are required')
    inbox = canonical(root / 'inbox' / args.tag)
    archive = canonical(inbox / 'source.tar.gz')
    require(digest(archive) == args.source_sha256, 'Tool preparation source archive differs')
    original = Path(__file__).resolve()
    with tarfile.open(archive, 'r:gz') as package:
        require(package.pax_headers.get('comment') == args.commit, 'Tool source commit differs')
        info = package.getmember('script/jenkins/ecs-tool-runtime.py')
        require(info.isfile() and info.size <= 1024 * 1024, 'Pinned executor source is missing')
        require(hashlib.sha256(package.extractfile(info).read()).hexdigest() == digest(original),
                'Uploaded executor differs from the pinned archive source')
    expected = {'instanceId': args.instance_id, 'machineId': args.machine_id, 'executionLocation': 'ECS'}
    require(re.fullmatch(r'i-[a-z0-9]+', args.instance_id) and re.fullmatch(r'[a-f0-9]{32}', args.machine_id),
            'Explicit ECS identity is required')
    identity_guard(expected)
    folder = inbox / 'tool-runtime'
    require(not folder.exists(), 'Use a fresh build for tool preparation')
    folder.mkdir(mode=0o700)
    program = canonical(shutil.which('docker'))
    images = {'maven': args.maven_image, 'node': args.node_image, 'python': args.python_image}
    for role, image in images.items():
        require(IMAGE.fullmatch(image), 'Use complete existing tool image IDs')
        row = json.loads(docker(program, 'image', 'inspect', image))[0]
        require(row['Id'] == image and row['Os'] == 'linux', 'Existing immutable tool image is unavailable')
        require(not row['Config'].get('Volumes'), 'Tool images must not declare persistent data volumes')
        for entry in row['Config'].get('Env') or []:
            key, _, content = entry.partition('=')
            require(not content or not re.search(r'PASSWORD|PASSWD|SECRET|API_KEY|ACCESS_KEY|TOKEN|DATABASE_URL|DB_URL', key, re.I),
                    'Tool image must not contain credentials or business database connections')
        if role == 'python':
            require((row['Config'].get('Labels') or {}).get('io.doorhandle.ci-tools') == 'python-v1',
                    'Python tools require the reviewed dependency image label')
    (folder / 'receipts').mkdir(mode=0o700)
    executor = folder / 'executor.py'
    shutil.copyfile(original, executor); os.chmod(executor, 0o500)
    files = {'executor.py': digest(executor)}
    for tool in BINARIES:
        wrapper = folder / tool
        wrapper.write_text('#!/usr/bin/env -S python3 -I -B\nimport runpy,sys\nsys.argv=['
                           + repr(str(executor)) + ',"launch","--manifest",' + repr(str(folder / 'manifest.json'))
                           + ',"--tool",' + repr(tool) + ',"--",*sys.argv[1:]]\nrunpy.run_path('
                           + repr(str(executor)) + ',run_name="__main__")\n', encoding='utf8')
        os.chmod(wrapper, 0o500); files[tool] = digest(wrapper)
    value = {'schema': 1, 'kind': 'doorhandle-ecs-tool-runtime', 'release': args.tag, 'commit': args.commit,
             'sourceSha256': args.source_sha256, 'identity': expected, 'directory': str(folder),
             'checkout': str(root / 'verification' / args.tag / 'checkout'), 'token': secrets.token_hex(12),
             'uid': os.getuid(), 'gid': os.getgid(), 'docker': str(program), 'images': images, 'files': files}
    value['mavenCache'] = maven_cache_definition(root, images['maven'], maven_archive_inputs(archive))
    initialize_maven_cache(value)
    path = folder / 'manifest.json'; write_json(path, value)
    return {'status': 'PREPARED', 'release': args.tag, 'manifest': str(path), 'manifestSha256': digest(path),
            'java': str(folder / 'java'), 'tools': {key: str(folder / key) for key in BINARIES}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    make = sub.add_parser('prepare')
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id', 'maven-image', 'node-image', 'python-image'):
        make.add_argument('--' + name, required=True)
    call = sub.add_parser('launch'); call.add_argument('--manifest', required=True); call.add_argument('--tool', choices=BINARIES, required=True)
    call.add_argument('arguments', nargs=argparse.REMAINDER)
    clean = sub.add_parser('cleanup'); clean.add_argument('--manifest', required=True)
    release = sub.add_parser('admit-release'); release.add_argument('--manifest', required=True)
    release.add_argument('--candidate-build', required=True)
    args = parser.parse_args()
    for name in (signal.SIGTERM, signal.SIGINT):
        signal.signal(name, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        if args.action == 'prepare':
            print(json.dumps(prepare(args))); return 0
        if args.action == 'launch':
            values = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
            return launch(args.manifest, args.tool, values)
        require(sys.platform == 'linux', 'Tool cleanup is ECS-only')
        value = private_json(args.manifest)
        value, _ = admit(args.manifest, root=Path(value['directory']).parents[2], tag=value['release'],
                         commit=value['commit'], source_sha=value['sourceSha256'], identity=value['identity'],
                         source=Path(value['directory']))
        if args.action == 'admit-release':
            identity_guard(value['identity'])
            print(json.dumps(admit_release(value, args.candidate_build))); return 0
        print(json.dumps(cleanup(value))); return 0
    except BaseException as error:
        print(json.dumps({'status': 'FAILED_OR_UNKNOWN', 'errorType': type(error).__name__}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
