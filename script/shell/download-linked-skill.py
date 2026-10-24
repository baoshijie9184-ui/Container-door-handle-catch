"""Snapshot public GitHub, skills.sh and ModelScope Skills in private quarantine; never execute package files."""
import argparse
import hashlib
import ipaddress
import json
import os
import io
import stat
import zipfile
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
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
MAX_STORED = 5 * 1024 * 1024


def source(url):
    parsed = urlparse(url)
    if len(url) > 1000 or parsed.scheme != 'https' or parsed.query or parsed.fragment or '%' in parsed.path:
        raise ValueError('SUPPORTED_SOURCE_REQUIRED')
    parts = parsed.path.strip('/').split('/')
    if parsed.netloc in ('skills.sh', 'www.skills.sh'):
        if len(parts) != 3 or not all(re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}', p) and p not in ('.', '..') for p in parts):
            raise ValueError('SKILLS_DIRECTORY_REQUIRED')
        return {'provider': 'SKILLS_SH', 'owner': parts[0], 'repo': parts[1], 'name': parts[2]}
    if parsed.netloc in ('modelscope.cn', 'www.modelscope.cn'):
        if len(parts) != 3 or parts[0] != 'skills' or not re.fullmatch(r'@[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}', parts[1]) or not re.fullmatch(r'[a-z][a-z0-9-]{2,63}', parts[2]):
            raise ValueError('MODELSCOPE_SKILL_REQUIRED')
        return {'provider': 'MODELSCOPE', 'id': parts[1] + '/' + parts[2]}
    if parsed.netloc != 'github.com':
        raise ValueError('SUPPORTED_SOURCE_REQUIRED')
    if len(parts) < 5 or parts[2] != 'tree':
        raise ValueError('GITHUB_SKILL_DIRECTORY_REQUIRED')
    owner, repo, _, ref, *directory = parts
    if not all(re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}', item) and item not in ('.', '..') for item in (owner, repo, ref)):
        raise ValueError('INVALID_SOURCE')
    folder = '/'.join(directory)
    safe_path(folder)
    return {'provider': 'GITHUB', 'owner': owner, 'repo': repo, 'ref': ref, 'folder': folder}


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
        from urllib.parse import urljoin
        original_host = urlparse(url).hostname
        groups = [('api.github.com',), ('raw.githubusercontent.com',), ('skills.sh', 'www.skills.sh'), ('modelscope.cn', 'www.modelscope.cn')]
        allowed = next((g for g in groups if original_host in g), ())
        for attempt in range(4):
            parsed = urlparse(url); host = parsed.hostname
            if host not in allowed or parsed.scheme != 'https' or parsed.netloc != host or parsed.fragment:
                raise ValueError('REMOTE_HOST_NOT_ALLOWED')
            for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
                if not ipaddress.ip_address(result[4][0]).is_global:
                    raise ValueError('REMOTE_ADDRESS_NOT_PUBLIC')
            try:
                response = self.session.get(url, timeout=(8, 20), allow_redirects=False, stream=True)
            except requests.Timeout as error:
                raise ValueError('SOURCE_TIMEOUT') from error
            except requests.RequestException as error:
                raise ValueError('SOURCE_CONNECTION_FAILED') from error
            with response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get('Location', '')); continue
                if response.status_code in (401, 403):
                    raise ValueError('SOURCE_AUTHENTICATION_REQUIRED')
                if response.status_code != 200:
                    raise ValueError('REMOTE_FILE_UNAVAILABLE')
                data = bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > limit:
                        raise ValueError('PACKAGE_LIMIT_EXCEEDED')
                return bytes(data)
        raise ValueError('REMOTE_REDIRECT_LIMIT')

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


def _download_github(url, destination, transport=None, original_url=None, market=None):
    parsed = source(url)
    owner, repo, ref, folder = (parsed[k] for k in ('owner', 'repo', 'ref', 'folder'))
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
        if relative == 'manifest.json' or relative.startswith('_source/'):
            raise ValueError('RESERVED_PACKAGE_PATH')
        if relative.casefold() in used:
            raise ValueError('DUPLICATE_PACKAGE_PATH')
        used.add(relative.casefold())
        if entry.get('size', MAX_FILE + 1) > MAX_FILE:
            raise ValueError('PACKAGE_LIMIT_EXCEEDED')
        content = transport.get(f'https://raw.githubusercontent.com/{owner}/{repo}/{commit}/{quote(remote_path, safe="/")}', MAX_FILE)
        if len(content) > MAX_FILE:
            raise ValueError('PACKAGE_LIMIT_EXCEEDED')
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
    manifest = {'sourceType': 'LINK', 'sourceUrl': original_url or url, 'resolvedUrl': f'https://github.com/{owner}/{repo}/tree/{commit}/{folder}',
                'commit': commit, 'directory': folder, 'name': metadata['name'], 'description': description.strip()[:300],
                'instructions': instructions, 'files': manifest_files, 'licenses': licenses, 'license': spdx,
                'scriptsExecutable': False, 'resourcesReadable': False, 'provenanceVerified': True}
    manifest.update({'provider': market or 'GITHUB', 'revisionKind': 'GIT_COMMIT', 'sourceIdentity': f'github:{owner.lower()}/{repo.lower()}/{folder}', 'capturedAt': datetime.now(timezone(timedelta(hours=8))).isoformat()})
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    return {'downloaded': True, 'commit': commit, 'files': len(manifest_files), 'bytes': total}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(v for k, v in attrs if k == 'href' and isinstance(v, str))


def _skills_source(url, descriptor, transport):
    owner, repo, name = (descriptor[k] for k in ('owner', 'repo', 'name'))
    page = _Links(); page.feed(transport.get(url, 2 * MAX_FILE).decode('utf-8'))
    repository = f'https://github.com/{owner}/{repo}'
    if not any(link.rstrip('/') == repository or link.startswith(repository + '/tree/') for link in page.links):
        raise ValueError('MARKET_SOURCE_NOT_VERIFIED')
    details = transport.document(f'https://api.github.com/repos/{owner}/{repo}')
    if details.get('private') is not False or not isinstance(details.get('default_branch'), str):
        raise ValueError('PUBLIC_REPOSITORY_REQUIRED')
    revision = transport.document(f'https://api.github.com/repos/{owner}/{repo}/commits/{quote(details["default_branch"], safe="")}')['sha']
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError('INVALID_PINNED_REVISION')
    tree = transport.document(f'https://api.github.com/repos/{owner}/{repo}/git/trees/{revision}?recursive=1')
    if tree.get('truncated'):
        raise ValueError('PACKAGE_TREE_TOO_LARGE')
    matches = []
    candidates = [e for e in tree.get('tree', []) if e.get('path', '').endswith('/SKILL.md') or e.get('path') == 'SKILL.md']
    if len(candidates) > 128:
        raise ValueError('SKILL_DISCOVERY_LIMIT')
    for entry in candidates:
        folder = str(PurePosixPath(entry['path']).parent)
        if folder != '.' and folder.split('/')[-1] == name:
            matches.append(folder)
    if len(matches) != 1:
        raise ValueError('SKILL_DIRECTORY_AMBIGUOUS' if len(matches) > 1 else 'SKILL_DIRECTORY_NOT_FOUND')
    return f'{repository}/tree/{revision}/{matches[0]}'


def _modelscope(url, descriptor, destination, transport):
    skill_id = descriptor['id']
    detail_url = 'https://modelscope.cn/openapi/v1/skills/' + skill_id
    document = transport.document(detail_url); detail = document.get('data')
    if document.get('success') is not True or not isinstance(detail, dict) or detail.get('id') != skill_id or detail.get('private') is not False:
        raise ValueError('PUBLIC_SKILL_METADATA_REQUIRED')
    metadata_bytes = json.dumps(document, sort_keys=True, ensure_ascii=False).encode('utf-8')
    if len(metadata_bytes) > 256 * 1024:
        raise ValueError('PACKAGE_METADATA_LIMIT')
    archive_url = 'https://www.modelscope.cn/skills/' + skill_id + '/archive/zip/master'
    archive = transport.get(archive_url, MAX_TOTAL)
    if len(archive) > MAX_TOTAL:
        raise ValueError('PACKAGE_LIMIT_EXCEEDED')
    payload = {}; total = 0
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        entries = package.infolist()
        if len(entries) > 192:
            raise ValueError('PACKAGE_LIMIT_EXCEEDED')
        paths = []; all_paths = set()
        for entry in entries:
            path = entry.filename.rstrip('/')
            safe_path(path)
            if path.casefold() in all_paths:
                raise ValueError('DUPLICATE_PACKAGE_PATH')
            all_paths.add(path.casefold())
            mode = entry.external_attr >> 16
            if entry.flag_bits & 1 or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFDIR, stat.S_IFREG):
                raise ValueError('LINKS_AND_SPECIAL_FILES_FORBIDDEN')
            if not entry.is_dir(): paths.append((path, entry))
        roots = [p[:-len('SKILL.md')] for p, _ in paths if p == 'SKILL.md' or p.endswith('/SKILL.md')]
        if len(roots) != 1:
            raise ValueError('SKILL_DIRECTORY_AMBIGUOUS')
        prefix = roots[0]
        for remote, entry in paths:
            if not remote.startswith(prefix):
                raise ValueError('ARCHIVE_OUTSIDE_SKILL_ROOT')
            relative = safe_path(remote[len(prefix):])
            if relative.startswith('_source/') or relative == 'manifest.json':
                raise ValueError('RESERVED_PACKAGE_PATH')
            if entry.file_size > MAX_FILE or len(payload) >= MAX_FILES:
                raise ValueError('PACKAGE_LIMIT_EXCEEDED')
            with package.open(entry) as stream: content = stream.read(MAX_FILE + 1)
            if len(content) > MAX_FILE or len(content) != entry.file_size:
                raise ValueError('PACKAGE_LIMIT_EXCEEDED')
            total += len(content)
            if total > MAX_TOTAL:
                raise ValueError('PACKAGE_LIMIT_EXCEEDED')
            payload[relative] = content
    licenses = {p: b.decode('utf-8') for p, b in payload.items() if re.fullmatch(r'(?i)(LICENSE(?:\.[A-Za-z]+)?|COPYING)', PurePosixPath(p).name)}
    if not licenses:
        raise ValueError('LICENSE_REQUIRED')
    root_license = next((v for k, v in licenses.items() if '/' not in k), None)
    if root_license is None:
        raise ValueError('PACKAGE_LICENSE_REQUIRED')
    spdx = license_type(root_license)
    declared = detail.get('license', '')
    if declared and declared not in (spdx, 'MIT License' if spdx == 'MIT' else 'Apache License 2.0' if spdx == 'Apache-2.0' else 'BSD License'):
        raise ValueError('LICENSE_DECLARATION_MISMATCH')
    raw = payload['SKILL.md'].decode('utf-8').replace('\r\n', '\n')
    if len(raw) > 64000 or not raw.startswith('---\n') or '\n---' not in raw[4:]:
        raise ValueError('INVALID_SKILL_METADATA')
    header, instructions = raw.split('\n---', 1); data = yaml.safe_load(header[4:]); instructions = instructions.lstrip()
    if not isinstance(data, dict) or not re.fullmatch(r'[a-z][a-z0-9-]{2,63}', str(data.get('name', ''))) or not isinstance(data.get('description'), str) or not 4 <= len(data['description'].strip()) <= 2000 or len(instructions) < 40:
        raise ValueError('INVALID_SKILL_METADATA')
    digest = hashlib.sha256(archive).hexdigest()
    manifest = {'sourceType': 'LINK', 'provider': 'MODELSCOPE', 'revisionKind': 'CONTENT_SNAPSHOT', 'sourceUrl': url, 'resolvedUrl': archive_url,
                'sourceIdentity': 'modelscope:' + skill_id, 'commit': None, 'sourceVersion': 'snapshot-sha256:' + digest,
                'archiveSha256': digest, 'archiveBytes': len(archive), 'metadataSha256': hashlib.sha256(metadata_bytes).hexdigest(),
                'capturedAt': datetime.now(timezone(timedelta(hours=8))).isoformat(), 'upstreamSourceClaim': detail.get('source_url') or None,
                'name': data['name'], 'description': data['description'].strip()[:300], 'instructions': instructions,
                'files': [{'path': p, 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for p, b in payload.items()],
                'licenses': licenses, 'license': spdx, 'provenanceVerified': True, 'scriptsExecutable': False, 'resourcesReadable': False}
    encoded = json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode('utf-8')
    if len(encoded) > 512000 or len(encoded) + len(metadata_bytes) + len(archive) + total > MAX_STORED:
        raise ValueError('PACKAGE_STORAGE_LIMIT')
    destination = Path(destination)
    if destination.exists(): raise ValueError('INSTALL_DIRECTORY_EXISTS')
    destination.mkdir(parents=True)
    for path, content in {**payload, '_source/archive.zip': archive, '_source/metadata.json': metadata_bytes, 'manifest.json': encoded}.items():
        target = destination / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
    return {'downloaded': True, 'revisionKind': 'CONTENT_SNAPSHOT', 'snapshotSha256': digest, 'files': len(payload), 'bytes': total}


def download(url, destination, transport=None):
    descriptor = source(url); transport = transport or Transport()
    if descriptor['provider'] == 'MODELSCOPE': return _modelscope(url, descriptor, destination, transport)
    if descriptor['provider'] == 'SKILLS_SH':
        resolved = _skills_source(url, descriptor, transport)
        result = _download_github(resolved, destination, transport, url, 'SKILLS_SH')
        manifest = json.loads((Path(destination) / 'manifest.json').read_text('utf-8'))
        if manifest['name'] != descriptor['name']: raise ValueError('MARKET_SKILL_NAME_MISMATCH')
        return result
    return _download_github(url, destination, transport)


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
