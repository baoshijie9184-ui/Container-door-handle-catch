"""Download a pinned public GitHub Skill into a private quarantine; never execute its files."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
from urllib.parse import urlparse, unquote, quote
import requests
import yaml

MAX_FILE = 1024 * 1024
MAX_TOTAL = 4 * 1024 * 1024
MAX_FILES = 96
MODEL_SCOPE_CREATOR = 'https://modelscope.cn/skills/@anthropics/skill-creator'


def source(url):
    if url.rstrip('/') == MODEL_SCOPE_CREATOR:
        url = 'https://github.com/anthropics/skills/tree/main/skills/skill-creator'
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.query or parsed.fragment:
        raise ValueError('SUPPORTED_SOURCE_REQUIRED')
    parts = unquote(parsed.path).strip('/').split('/')
    if len(parts) < 5 or parts[2] != 'tree':
        raise ValueError('GITHUB_SKILL_DIRECTORY_REQUIRED')
    owner, repo, _, ref, *directory = parts
    if not all(re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', item) for item in (owner, repo, ref)):
        raise ValueError('INVALID_SOURCE')
    folder = '/'.join(directory)
    safe_path(folder)
    return owner, repo, ref, folder


def safe_path(value):
    if not value or len(value) > 220 or not re.fullmatch(r'[A-Za-z0-9_./-]+', value):
        raise ValueError('UNSAFE_PACKAGE_PATH')
    if any(part in ('', '.', '..') or part.endswith('.') or re.match(r'(?i)^(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)', part)
           for part in value.split('/')):
        raise ValueError('UNSAFE_PACKAGE_PATH')
    return value


class Transport:
    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers['User-Agent'] = 'DoorHandleCatch-SkillInstaller/1'

    def get(self, url, limit):
        host = urlparse(url).hostname
        if host not in ('api.github.com', 'raw.githubusercontent.com'):
            raise ValueError('REMOTE_HOST_NOT_ALLOWED')
        for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(result[4][0]).is_global:
                raise ValueError('REMOTE_ADDRESS_NOT_PUBLIC')
        with self.session.get(url, timeout=(8, 20), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise ValueError('REMOTE_FILE_UNAVAILABLE')
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > limit:
                    raise ValueError('PACKAGE_LIMIT_EXCEEDED')
            return bytes(data)

    def document(self, url):
        return json.loads(self.get(url, 2 * MAX_FILE))


def license_type(text):
    if 'Apache License' in text and 'Version 2.0' in text:
        return 'Apache-2.0'
    if 'Permission is hereby granted, free of charge' in text and 'THE SOFTWARE IS PROVIDED' in text:
        return 'MIT'
    if 'Redistribution and use in source and binary forms' in text and 'THIS SOFTWARE IS PROVIDED' in text:
        return 'BSD'
    raise ValueError('SUPPORTED_LICENSE_REQUIRED')


def download(url, destination, transport=None):
    owner, repo, ref, folder = source(url)
    transport = transport or Transport()
    commit = transport.document(f'https://api.github.com/repos/{owner}/{repo}/commits/{quote(ref, safe="")}')['sha']
    if not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise ValueError('INVALID_PINNED_REVISION')
    tree = transport.document(f'https://api.github.com/repos/{owner}/{repo}/git/trees/{commit}?recursive=1')
    if tree.get('truncated'):
        raise ValueError('PACKAGE_TREE_TOO_LARGE')
    prefix = folder + '/'
    entries = [entry for entry in tree['tree'] if entry['path'].startswith(prefix) and entry['type'] != 'tree']
    if not entries or len(entries) > MAX_FILES or not any(entry['path'] == prefix + 'SKILL.md' for entry in entries):
        raise ValueError('SKILL_PACKAGE_REQUIRED')
    # Inherited copyright/NOTICE are archived with their original repository path.
    ancestors = {str(PurePosixPath(folder).parent)}
    parent = PurePosixPath(folder).parent
    while str(parent) != '.':
        ancestors.add(str(parent)); parent = parent.parent
    ancestors.add('.')
    for entry in tree['tree']:
        path = PurePosixPath(entry['path'])
        if entry['type'] == 'blob' and str(path.parent) in ancestors and re.fullmatch(r'(?i)(LICENSE(?:\.[A-Za-z]+)?|COPYING|NOTICE(?:\.[A-Za-z]+)?)', path.name):
            entries.append(entry)
    if len(entries) > MAX_FILES:
        raise ValueError('PACKAGE_LIMIT_EXCEEDED')
    destination = Path(destination)
    if destination.exists():
        raise ValueError('INSTALL_DIRECTORY_EXISTS')
    destination.mkdir(parents=True)
    manifest_files, licenses, total, used = [], {}, 0, set()
    for entry in entries:
        if entry.get('mode') not in ('100644', '100755') or entry['type'] != 'blob':
            raise ValueError('LINKS_AND_SUBMODULES_FORBIDDEN')
        remote_path = safe_path(entry['path'])
        relative = remote_path[len(prefix):] if remote_path.startswith(prefix) else '_licenses/' + remote_path
        safe_path(relative)
        if relative.casefold() in used:
            raise ValueError('DUPLICATE_PACKAGE_PATH')
        used.add(relative.casefold())
        if entry.get('size', MAX_FILE + 1) > MAX_FILE:
            raise ValueError('PACKAGE_LIMIT_EXCEEDED')
        content = transport.get(f'https://raw.githubusercontent.com/{owner}/{repo}/{commit}/{quote(remote_path, safe="/")}', MAX_FILE)
        blob_digest = hashlib.sha1(b'blob ' + str(len(content)).encode('ascii') + b'\x00' + content).hexdigest()
        if entry.get('sha') != blob_digest:
            raise ValueError('REMOTE_BLOB_DIGEST_MISMATCH')
        total += len(content)
        if total > MAX_TOTAL:
            raise ValueError('PACKAGE_LIMIT_EXCEEDED')
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        manifest_files.append({'path': relative, 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
        if re.fullmatch(r'(?i)(LICENSE(?:\.[A-Za-z]+)?|COPYING)', path.name):
            licenses[relative] = content.decode('utf-8')
    if not licenses:
        raise ValueError('LICENSE_REQUIRED')
    # The nearest package license takes precedence over inherited repository licenses.
    primary = next((text for path, text in licenses.items() if '/' not in path), next(iter(licenses.values())))
    spdx = license_type(primary)
    text = (destination / 'SKILL.md').read_text(encoding='utf-8')
    if len(text) > 64000 or not text.startswith('---\n'):
        raise ValueError('INVALID_SKILL_METADATA')
    pieces = text.split('\n---', 1)
    if len(pieces) != 2:
        raise ValueError('INVALID_SKILL_METADATA')
    metadata = yaml.safe_load(pieces[0][4:])
    if not isinstance(metadata, dict) or not re.fullmatch(r'[a-z][a-z0-9-]{2,63}', str(metadata.get('name', ''))):
        raise ValueError('INVALID_SKILL_METADATA')
    description = metadata.get('description')
    if not isinstance(description, str) or not 4 <= len(description.strip()) <= 2000:
        raise ValueError('INVALID_SKILL_METADATA')
    instructions = pieces[1].lstrip()
    if len(instructions) < 40:
        raise ValueError('INVALID_SKILL_METADATA')
    manifest = {'sourceType': 'LINK', 'sourceUrl': url, 'resolvedUrl': f'https://github.com/{owner}/{repo}/tree/{commit}/{folder}',
                'commit': commit, 'directory': folder, 'name': metadata['name'], 'description': description.strip()[:300],
                'instructions': instructions, 'files': manifest_files, 'licenses': licenses, 'license': spdx,
                'scriptsExecutable': False, 'resourcesReadable': False, 'provenanceVerified': True}
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    return {'downloaded': True, 'commit': commit, 'files': len(manifest_files), 'bytes': total}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True); parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(download(args.url, args.destination)))
    except Exception as error:
        # Never print a response body, proxy environment, local path or arbitrary remote exception.
        code = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{3,80}', str(error)) else 'DOWNLOAD_FAILED'
        print(json.dumps({'downloaded': False, 'errorCode': code})); raise SystemExit(1)
