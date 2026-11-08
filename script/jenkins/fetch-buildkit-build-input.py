"""Fetch pinned public OCI build dependencies; never execute a container or test.

The existing local Jenkins Python uses its existing HTTPS proxy settings. The
result is a build cache, with original registry bytes verified again on ECS.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

MIB = 1024 ** 2
MAX_ARCHIVE = 128 * MIB
MAX_METADATA = 4 * MIB
MEDIA = 'application/vnd.oci.image.manifest.v1+json'
SHA = re.compile(r'sha256:[a-f0-9]{64}')


def need(value, code):
    if not value:
        raise ValueError(code)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def checksum(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    need(type(raw) is bytes and 0 < len(raw) <= MAX_METADATA, 'BOUNDED_BUILD_METADATA_REQUIRED')
    def pairs(items):
        value = {}
        for key, item in items:
            need(key not in value, 'DUPLICATE_BUILD_METADATA_FIELD')
            value[key] = item
        return value
    def constant(_value):
        raise ValueError('NONFINITE_BUILD_METADATA_FIELD')
    return json.loads(raw.decode('utf8'), object_pairs_hook=pairs, parse_constant=constant)


class ClosedInfo(tarfile.TarInfo):
    @staticmethod
    def checked_header(entry):
        need(entry.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and 0 < entry.size <= MAX_ARCHIVE
             and (entry.name in ('index.json', 'oci-layout') or re.fullmatch(r'blobs/sha256/[a-f0-9]{64}', entry.name)),
             'CLOSED_OCI_TAR_MEMBERS_REQUIRED')
        return entry
    @classmethod
    def frombuf(cls, raw, encoding, errors):
        return cls.checked_header(super().frombuf(raw, encoding, errors))
    def _proc_member(self, package):
        self.checked_header(self)
        return super()._proc_member(package)


def pins(source):
    values = {}
    for node in ast.parse(Path(source).read_bytes()).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ('VERSION', 'REFERENCE', 'IMAGE_ID'):
                    need(target.id not in values, 'DUPLICATE_BUILD_INPUT_PIN')
                    values[target.id] = ast.literal_eval(node.value)
    need(set(values) == {'VERSION', 'REFERENCE', 'IMAGE_ID'} and
         re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', values['VERSION']) and SHA.fullmatch(values['IMAGE_ID']),
         'LITERAL_BUILD_INPUT_PINS_REQUIRED')
    match = re.fullmatch(r'docker.io/([a-z0-9_./-]+)@(sha256:[a-f0-9]{64})', values['REFERENCE'])
    need(match and '..' not in match[1].split('/'), 'PINNED_DOCKER_HUB_REFERENCE_REQUIRED')
    return {**values, 'repository': match[1], 'manifestDigest': match[2]}


def safe(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if not item.exists() and not item.is_symlink():
            continue
        info = item.lstat()
        need(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
             'BUILD_CACHE_LINK_OR_REPARSE_REFUSED')
    return path


def fingerprint(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink


def file_digest(path, maximum=MAX_ARCHIVE):
    path = safe(path); before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= maximum,
         'BOUNDED_SINGLE_LINK_BUILD_FILE_REQUIRED')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        need(fingerprint(os.fstat(stream.fileno())) == fingerprint(before), 'BUILD_FILE_ID_CHANGED')
        for block in iter(lambda: stream.read(MIB), b''):
            h.update(block)
        need(fingerprint(os.fstat(stream.fileno())) == fingerprint(before) == fingerprint(path.lstat()),
             'BUILD_FILE_CHANGED_DURING_READ')
    return before.st_size, h.hexdigest()


def publish_file(temporary, destination):
    # Publish without replacing a pre-existing cache object. Both names are in
    # this invocation's explicit cache directory; no recursive removal occurs.
    try:
        os.link(temporary, destination)
    except FileExistsError:
        need(file_digest(temporary) == file_digest(destination), 'EXISTING_BUILD_CACHE_BYTES_DIFFER')
    finally:
        temporary.unlink()


def put_bytes(path, raw):
    path = safe(path)
    if path.exists():
        need(file_digest(path) == (len(raw), checksum(raw)), 'EXISTING_BUILD_METADATA_DIFFERS')
        return
    temporary = path.with_name(path.name + '.part-' + secrets.token_hex(8))
    with temporary.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    publish_file(temporary, path)


def manifest(raw, fixed):
    need(0 < len(raw) <= MAX_METADATA and 'sha256:' + checksum(raw) == fixed['manifestDigest'],
         'ORIGINAL_PINNED_MANIFEST_REQUIRED')
    value = strict_json(raw)
    need(type(value) is dict and type(value.get('schemaVersion')) is int and value['schemaVersion'] == 2
         and value.get('mediaType') == MEDIA and 'manifests' not in value and type(value.get('config')) is dict
         and type(value.get('layers')) is list and 0 < len(value['layers']) <= 128,
         'PINNED_SINGLE_PLATFORM_MANIFEST_REQUIRED')
    rows = [value['config'], *value['layers']]
    need(value['config']['digest'] == fixed['IMAGE_ID'] and
         all(type(row) is dict and set(row) == {'mediaType', 'digest', 'size'} and type(row['digest']) is str
             and SHA.fullmatch(row['digest']) and type(row['size']) is int and 0 < row['size'] <= MAX_ARCHIVE
             and row['mediaType'] == ('application/vnd.oci.image.config.v1+json' if number == 0
                                     else 'application/vnd.oci.image.layer.v1.tar+gzip') for number, row in enumerate(rows)),
         'PINNED_BUILD_DESCRIPTOR_INVALID')
    need(len({row['digest'] for row in rows}) == len(rows)
         and sum(row['size'] for row in rows) + len(raw) + MIB < MAX_ARCHIVE,
         'BUILD_INPUT_CATALOGUE_EXCEEDS_BOUND')
    return value


class SecureRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        need(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password,
             'BUILD_DOWNLOAD_REDIRECT_REQUIRES_TLS')
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if result is not None:
            result.remove_header('Authorization')
        return result


class Registry:
    def __init__(self, fixed):
        self.fixed, self.token = fixed, None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler(), SecureRedirect())

    def get(self, suffix):
        if self.token is None:
            url = 'https://auth.docker.io/token?service=registry.docker.io&scope=repository:' + self.fixed['repository'] + ':pull'
            with self.opener.open(url, timeout=30) as response:
                raw = response.read(MAX_METADATA + 1)
            need(len(raw) <= MAX_METADATA, 'REGISTRY_TOKEN_METADATA_TOO_LARGE')
            self.token = strict_json(raw)['token']
            need(isinstance(self.token, str) and 0 < len(self.token) <= 16384, 'REGISTRY_TOKEN_INVALID')
        url = 'https://registry-1.docker.io/v2/' + self.fixed['repository'] + '/' + suffix
        return self.opener.open(urllib.request.Request(url, headers={
            'Authorization': 'Bearer ' + self.token, 'Accept': MEDIA}), timeout=30)


def fetch_blob(registry, directory, descriptor):
    target = safe(directory / descriptor['digest'][7:])
    expected = descriptor['size'], descriptor['digest'][7:]
    if target.exists():
        need(file_digest(target) == expected, 'CACHED_ORIGINAL_BLOB_DIFFERS')
        return True
    temporary = target.with_name(target.name + '.part-' + secrets.token_hex(8))
    h = hashlib.sha256(); count = 0; deadline = time.monotonic() + 900
    try:
        with registry.get('blobs/' + descriptor['digest']) as response, temporary.open('xb') as stream:
            for block in iter(lambda: response.read(MIB), b''):
                count += len(block)
                need(count <= descriptor['size'] and time.monotonic() < deadline, 'BUILD_BLOB_BOUND_OR_DEADLINE_EXCEEDED')
                h.update(block); stream.write(block)
            stream.flush(); os.fsync(stream.fileno())
        need((count, h.hexdigest()) == expected, 'ORIGINAL_BUILD_BLOB_HASH_DIFFERS')
        publish_file(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return False


def verify_bundle(path, fixed):
    size, raw_sha = file_digest(path)
    entries = {}
    with tarfile.open(path, 'r:', tarinfo=ClosedInfo) as package:
        for entry in package:
            need(entry.isfile() and entry.name not in entries and len(entries) < 132
                 and not entry.pax_headers and not entry.issparse() and 0 < entry.size <= MAX_ARCHIVE and
                 (entry.name in ('index.json', 'oci-layout') or re.fullmatch(r'blobs/sha256/[a-f0-9]{64}', entry.name)),
                 'CLOSED_OCI_TAR_MEMBERS_REQUIRED')
            h = hashlib.sha256(); data = bytearray() if entry.size <= MAX_METADATA else None
            with package.extractfile(entry) as source:
                for block in iter(lambda: source.read(MIB), b''):
                    h.update(block)
                    if data is not None: data.extend(block)
            entries[entry.name] = (entry.size, h.hexdigest(), bytes(data) if data is not None else None)
        with path.open('rb') as source:
            source.seek(package.offset); tail = 0
            for block in iter(lambda: source.read(MIB), b''):
                tail += len(block); need(not block.strip(b'\0'), 'NONZERO_OCI_ARCHIVE_TAIL')
            need(tail >= 1024 and size % 512 == 0, 'TRUNCATED_OCI_ARCHIVE_TERMINATOR')
    root_name = 'blobs/sha256/' + fixed['manifestDigest'][7:]
    need(root_name in entries and entries[root_name][2] is not None, 'OCI_ROOT_MANIFEST_MISSING')
    value = manifest(entries[root_name][2], fixed)
    wanted = {'index.json', 'oci-layout', root_name, *('blobs/sha256/' + row['digest'][7:] for row in [value['config'], *value['layers']])}
    need(set(entries) == wanted, 'OCI_BLOB_CATALOGUE_NOT_CLOSED')
    need(strict_json(entries['oci-layout'][2]) == {'imageLayoutVersion': '1.0.0'}, 'OCI_LAYOUT_VERSION_DIFFERS')
    expected_index = {'schemaVersion': 2, 'manifests': [{'mediaType': MEDIA, 'digest': fixed['manifestDigest'], 'size': len(entries[root_name][2])}]}
    index = strict_json(entries['index.json'][2])
    need(type(index) is dict and type(index.get('schemaVersion')) is int and type(index.get('manifests')) is list
         and len(index['manifests']) == 1 and type(index['manifests'][0]) is dict
         and type(index['manifests'][0].get('size')) is int and index == expected_index,
         'OCI_INDEX_MUST_SELECT_PINNED_MANIFEST')
    for row in [value['config'], *value['layers']]:
        need(entries['blobs/sha256/' + row['digest'][7:]][:2] == (row['size'], row['digest'][7:]),
             'OCI_ORIGINAL_BLOB_BYTES_DIFFER')
    config = strict_json(entries['blobs/sha256/' + fixed['IMAGE_ID'][7:]][2])
    need(config.get('os') == 'linux' and config.get('architecture') == 'amd64', 'LINUX_AMD64_BUILD_INPUT_REQUIRED')
    need(file_digest(path) == (size, raw_sha), 'OCI_ARCHIVE_CHANGED_DURING_ADMISSION')
    return {'status': 'PINNED_OCI_BUILD_INPUT_READY', 'file': str(Path(path).absolute()), 'sha256': raw_sha, 'bytes': size,
            'reference': fixed['REFERENCE'], 'imageId': fixed['IMAGE_ID'], 'manifestSha256': fixed['manifestDigest'][7:],
            'originalLayerBytes': sum(row['size'] for row in value['layers']), 'runtimeExecuted': False, 'testsExecutedLocally': False}


def fetch(output, fixed):
    need(Path(output).is_absolute(), 'BUILD_CACHE_REQUIRES_EXPLICIT_D_DRIVE_DIRECTORY')
    output = safe(output)
    need(output.is_absolute() and (os.name != 'nt' or output.drive.upper() == 'D:'), 'BUILD_CACHE_REQUIRES_EXPLICIT_D_DRIVE_DIRECTORY')
    output.mkdir(parents=True, exist_ok=True)
    target = output / 'buildkit-oci.tar'
    if target.exists():
        return verify_bundle(target, fixed)
    registry = Registry(fixed); metadata = output / 'original-manifest.json'
    if metadata.exists():
        need(file_digest(metadata, MAX_METADATA)[1] == fixed['manifestDigest'][7:], 'CACHED_PINNED_MANIFEST_DIFFERS')
        raw = metadata.read_bytes()
    else:
        with registry.get('manifests/' + fixed['manifestDigest']) as response: raw = response.read(MAX_METADATA + 1)
        manifest(raw, fixed); put_bytes(metadata, raw)
    value = manifest(raw, fixed)
    blobs = safe(output / 'blobs' / 'sha256'); blobs.mkdir(parents=True, exist_ok=True)
    put_bytes(blobs / fixed['manifestDigest'][7:], raw)
    for row in [value['config'], *value['layers']]:
        reused = fetch_blob(registry, blobs, row)
        print(json.dumps({'event': 'BUILD_BLOB_READY', 'digest': row['digest'], 'bytes': row['size'], 'reused': reused}), flush=True)
    control = {'oci-layout': encoded({'imageLayoutVersion': '1.0.0'}),
               'index.json': encoded({'schemaVersion': 2, 'manifests': [{'mediaType': MEDIA, 'digest': fixed['manifestDigest'], 'size': len(raw)}]})}
    temporary = target.with_name(target.name + '.part-' + secrets.token_hex(8))
    try:
        with tarfile.open(temporary, 'x', format=tarfile.PAX_FORMAT) as package:
            for name, content in control.items():
                info = tarfile.TarInfo(name); info.size = len(content); info.mode = 0o600; package.addfile(info, io.BytesIO(content))
            for blob in sorted({fixed['manifestDigest'][7:], *(row['digest'][7:] for row in [value['config'], *value['layers']])}):
                source = blobs / blob; length, actual = file_digest(source)
                need(actual == blob, 'BLOB_CHANGED_BEFORE_PACKING')
                info = tarfile.TarInfo('blobs/sha256/' + blob); info.size = length; info.mode = 0o600
                with source.open('rb') as stream: package.addfile(info, stream)
        verify_bundle(temporary, fixed)
        publish_file(temporary, target)
    finally:
        if temporary.exists(): temporary.unlink()
    return verify_bundle(target, fixed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--resources-source', default=str(Path(__file__).resolve().parents[1] / 'docker/compact-build-resources.py'))
    args = parser.parse_args(argv)
    try:
        print(json.dumps(fetch(args.output_dir, pins(args.resources_source))), flush=True)
        return 0
    except BaseException as error:
        code = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', str(error)) else 'PINNED_BUILD_INPUT_FETCH_FAILED'
        print(json.dumps({'status': 'FAILED_OR_UNKNOWN', 'errorType': type(error).__name__, 'code': code,
                          'runtimeExecuted': False, 'testsExecutedLocally': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
