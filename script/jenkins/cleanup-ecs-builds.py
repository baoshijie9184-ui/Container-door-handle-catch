"""Reclaim only proven old source-build outputs after original evidence retention.

Plan discovers terminal source attempts. Apply binds its exact SHA and repeats every
admission. Business data, source archives, reports, releases and the shared Maven
dependency cache have no deletion API. ECS lifecycle is outside this helper.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
from functools import lru_cache
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


TAG = re.compile(r'ci-([0-9]+)-[a-f0-9]{12}')
SHA = re.compile(r'[a-f0-9]{64}')
COMMIT = re.compile(r'[a-f0-9]{40}')
MODULE = re.compile(r'doorhandle-[a-z0-9-]+')
COMPILE_DIRS = {'classes', 'test-classes', 'generated-sources', 'generated-test-sources',
                'maven-status', 'maven-archiver'}
MAX_PLAN = 32 * 1024 ** 2
CONTROL_DISK_RESERVE = 2 * 1024 ** 3
CONTROL_METADATA_BYTES = 1024 ** 2
MAX_TARGET_CANONICAL = 16 * 1024 ** 2
PYTEST_SKIP_DETAIL_LIMIT = 64
MAX_TREE_BYTES = 4 * 1024 ** 3
MAX_TREE_FILES = 100000
MAX_TREE_ENTRIES = 150000
FRONTENDS = ('frontend', 'frontend-agent')
NPM_CACHE_SUFFIX = 'work/tool-home/npm-cache/_cacache'
# These reviewed functions route checkout commands to this one disposable cache.
# Compare syntax only; never execute an old source or infer ownership by name.
NPM_ROUTING_AST = {
    'safe_environment': 'f3d236e9e74747545aa36f74a1cebf7de1675e2dbafb300d9d506068d7f3b3d6',
    'command': 'b44e28ef754376c8a1dcb792f34bf4200a6d4d85da7e52a345fa0aa1eac18bc7',
}
NPM_INSTALL_ARGUMENTS = ['ci', '--include=dev', '--ignore-scripts', '--no-audit', '--no-fund']
PYTEST_TMP_SUFFIX = 'work/ci-evidence/tmp/pytest'
# Reviewed source runners: 392ae841c2ab, 7a024fc1f02f and the source-only
# temporary cleanup revision. The main function
# includes its nested execute callback, source environment and exact basetemp.
PYTEST_RUNNER_MAIN_AST = {
    '6ed391795b01ecca1c45efd86b84b5270fa35f36742c76ac957141a28cb2a4ba',
    '140ee68b43a749ccdfd82ef40754ba7b7a7e7586257c6a119b55e1d1d5b54857',
    'd44f6afbdcb415341c311c486ad0fad1c4f10519e7840560652a68126e3d4a36',
}
# The root metadata mode receives these exact already-loaded source bytes via
# stdin, avoiding a second privileged open of a replaceable user-owned script.
LOADED_SOURCE = None if __file__ == '<stdin>' else Path(__file__).read_bytes()
PROCESS_PROBE_KIND = 'doorhandle-single-process-metadata'


def require(condition, code):
    if not condition:
        raise ValueError(code)


@lru_cache(maxsize=1)
def _failure_source_metadata(source):
    """Cache the fixed byte source's literal guards and own function names."""
    if not source: return frozenset(), frozenset(), 0
    codes, functions = set(), {'<module>'}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.add(node.name)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'require'
                and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,99}', node.args[1].value)):
            codes.add(node.args[1].value)
    return frozenset(codes), frozenset(functions), len(source.splitlines())


def failure_guard_code(error):
    """Return only a literal refusal code from this fixed controller's source."""
    if isinstance(error, ValueError) and len(error.args) == 1 and isinstance(error.args[0], str) and LOADED_SOURCE:
        if error.args[0] in _failure_source_metadata(LOADED_SOURCE)[0]: return error.args[0]
    return 'UNCLASSIFIED_VALIDATION_ERROR' if isinstance(error, ValueError) else 'UNCLASSIFIED_OS_ERROR'


def failure_details(error):
    """Expose at most eight fixed-controller locations, never private payload."""
    _, functions, line_count = _failure_source_metadata(LOADED_SOURCE)
    locations = []; trace = error.__traceback__
    while trace is not None:
        code = trace.tb_frame.f_code
        if (code.co_filename == __file__ and code.co_name in functions
                and type(trace.tb_lineno) is int and 0 < trace.tb_lineno <= line_count):
            locations.append({'function': code.co_name, 'line': trace.tb_lineno})
        trace = trace.tb_next
    return {'guardCode': failure_guard_code(error), 'locations': locations[-8:]}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def digest(path):
    result = hashlib.sha256()
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'HASH_INPUT_NOT_A_SINGLE_REGULAR_FILE')
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
        require(metadata(os.fstat(stream.fileno())) == metadata(before), 'HASH_INPUT_CHANGED_WHILE_READING')
    return result.hexdigest()


def owned(path, *, directory=False, maximum=MAX_PLAN):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts and path.resolve(strict=True) == path,
            'PATH_NOT_ABSOLUTE_OR_REDIRECTED')
    for ancestor in (path, *path.parents):
        info = ancestor.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'PATH_SYMLINK_OR_JUNCTION_NOT_ALLOWED')
    info = path.lstat()
    require(os.name == 'nt' or info.st_uid == os.getuid() and not info.st_mode & 0o022,
            'PATH_NOT_OWNED_OR_WRITABLE_BY_OTHERS')
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1 and info.st_size <= maximum, 'PATH_TYPE_LINK_OR_SIZE_INVALID')
    return path


def owned_chain(path, root, *, directory=False, maximum=MAX_PLAN):
    """Every CI-owned ancestor is checked, not just the final leaf."""
    path, root = Path(path), Path(root)
    require(path == root or path.is_relative_to(root), 'PATH_ESCAPES_CI_ROOT')
    owned(root, directory=True)
    for parent in reversed(path.parents):
        if parent != root and parent.is_relative_to(root): owned(parent, directory=True)
    return owned(path, directory=directory, maximum=maximum)


def read_json(path, maximum=MAX_PLAN):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'DUPLICATE_JSON_FIELD')
            result[key] = value
        return result
    return json.loads(owned(path, maximum=maximum).read_text(encoding='utf-8-sig'),
                      object_pairs_hook=unique, parse_constant=lambda _value: require(False, 'NONFINITE_JSON_VALUE'))


def write_json(path, value, *, byte_limit=MAX_PLAN):
    path = Path(path)
    owned(path.parent, directory=True)
    raw = canonical(value) + b'\n'
    require(len(raw) <= min(MAX_PLAN, byte_limit), 'OUTPUT_EXCEEDS_BOUNDED_PLAN')
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600), 'wb') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())


def verifier_module(path):
    spec = importlib.util.spec_from_file_location('fixed_cleanup_evidence_verifier', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def receipt_catalog(record, verifier):
    args = SimpleNamespace(tag=record['release'], attempt=record['attempt'], commit=record['commit'],
        source_sha256=record['sourceSha256'], scope='source',
        instance_id=record['identity']['instanceId'], machine_id=record['identity']['machineId'])
    verifier.validate_request(args)
    return verifier.validate_envelope(record, args)


def local_custody(directory, verifier):
    """Hash previously retained bytes only; no tests or application are run."""
    base = owned(Path(directory).absolute(), directory=True)
    receipt_file = owned(base / 'verification-receipt.json', maximum=verifier.MAX_RECEIPT_BYTES)
    record = read_json(receipt_file, verifier.MAX_RECEIPT_BYTES)
    catalog = receipt_catalog(record, verifier)
    require(catalog and any(name.endswith('.xml') for name in catalog), 'NO_ORIGINAL_REPORT_CATALOG')
    for name, row in catalog.items():
        file = owned(base.joinpath(*verifier.member_path(name).parts), maximum=verifier.MAX_FILE_BYTES)
        require(file.stat().st_size == row['bytes'] and digest(file) == row['sha256'], 'LOCAL_RETAINED_REPORT_CHANGED')
    preservation_file = owned(base / 'preservation.json')
    preservation = read_json(preservation_file)
    require(preservation.get('kind') in ('doorhandle-retained-original-ci-evidence', 'doorhandle-ci-evidence-preservation'),
            'UNKNOWN_LOCAL_PRESERVATION_RECORD')
    if preservation['kind'] == 'doorhandle-retained-original-ci-evidence':
        expected = [{'path': 'verification-receipt.json', 'bytes': receipt_file.stat().st_size, 'sha256': digest(receipt_file)},
                    *record['reportFiles']]
        require(sorted(preservation.get('files', []), key=lambda row: row['path']) == sorted(expected, key=lambda row: row['path'])
                and preservation.get('testsExecutedLocally') is False, 'LOCAL_PRESERVATION_CATALOG_DIFFERS')
    else:
        require(preservation.get('release') == record['release'] and preservation.get('commit') == record['commit']
                and preservation.get('verificationReceiptSha256') == digest(receipt_file)
                and preservation.get('reportFiles') == len(catalog), 'LOCAL_PRESERVATION_BINDING_DIFFERS')
    archive = base / 'verification-evidence.tar.gz'
    archive_proof = None
    if archive.exists() or archive.is_symlink():
        owned(archive, maximum=verifier.MAX_EVIDENCE_ARCHIVE)
        archive_proof = {'bytes': archive.stat().st_size, 'sha256': digest(archive)}
        retained = preservation.get('originalEvidenceArchive')
        if retained is None:
            retained = {'bytes': preservation.get('originalEvidenceArchiveBytes'),
                        'sha256': preservation.get('originalEvidenceArchiveSha256')}
        require(retained == archive_proof, 'LOCAL_EVIDENCE_ARCHIVE_CHANGED')
    return {'schema': 1, 'kind': 'doorhandle-original-evidence-custody', 'status': 'VERIFIED_LOCAL_BYTES',
        **{key: record[key] for key in ('release', 'commit', 'sourceSha256', 'identity')},
        'verificationReceiptSha256': digest(receipt_file), 'reportCatalogSha256': sha(canonical(record['reportFiles'])),
        'reportFiles': len(catalog), 'reportBytes': sum(row['bytes'] for row in catalog.values()),
        'preservationSha256': digest(preservation_file), 'originalEvidenceArchive': archive_proof,
        'testsExecutedLocally': False}


def discover_request(root, current, identity, protected=()):
    """Read direct CI children only; the original ECS tar/reports are mandatory.

    Independent local custody remains optional additional evidence, without a
    per-build manual prerequisite. Incomplete attempts become explicit skips.
    """
    require(TAG.fullmatch(current or ''), 'CURRENT_RELEASE_INVALID')
    parent = root / 'verification'; candidates = []
    if parent.exists() or parent.is_symlink():
        owned(parent, directory=True)
        children = sorted(parent.iterdir(), key=lambda path: path.name)
        require(len(children) <= 256, 'DIRECT_ATTEMPT_DISCOVERY_BOUND_EXCEEDED')
        for child in children:
            if not TAG.fullmatch(child.name): continue
            row = {'release': child.name}
            try:
                owned(child, directory=True)
                record_file = child / 'verification-receipt.json'
                record = read_json(record_file, 256 * 1024)
                require(record.get('release') == child.name and record.get('scope') == 'source'
                        and record.get('status') in ('PASS', 'FAILED') and record.get('finishedAt'), 'ATTEMPT_NOT_TERMINAL_SOURCE')
                row.update(schema=1, kind='doorhandle-retained-ecs-evidence', status='VERIFY_RETAINED_ECS_BYTES',
                    **{key: record[key] for key in ('commit', 'sourceSha256', 'identity')},
                    verificationReceiptSha256=digest(record_file), reportCatalogSha256=sha(canonical(record['reportFiles'])),
                    reportFiles=len(record['reportFiles']), reportBytes=sum(item['bytes'] for item in record['reportFiles']),
                    originalEvidenceArchive=None)
            except (ValueError, OSError, KeyError, TypeError) as error:
                row['discoveryError'] = str(error) if isinstance(error, ValueError) else type(error).__name__
            candidates.append(row)
    return {'schema': 1, 'kind': 'doorhandle-old-build-cleanup-request', 'currentRelease': current,
        'identity': identity, 'protectedReleases': sorted(set([current, *protected])), 'candidates': candidates}


def fixed_build_layout(archive, commit, verifier):
    """Read only pinned POM bytes; derive exact artifact names and isolated layout."""
    poms = {}
    with verifier.bounded_tar(archive, verifier.MAX_SOURCE_BYTES) as package:
        for item in package:
            if item.name == 'pom.xml' or re.fullmatch(r'doorhandle-[a-z0-9-]+/pom.xml', item.name):
                require(item.isfile() and 0 < item.size <= 1024 ** 2, 'PINNED_POM_NOT_BOUNDED')
                require(item.name not in poms, 'DUPLICATE_PINNED_POM')
                poms[item.name] = ET.fromstring(package.extractfile(item).read())
        require(package.pax_headers.get('comment') == commit, 'PINNED_SOURCE_COMMIT_DIFFERS')
    root = poms.get('pom.xml'); require(root is not None, 'PINNED_PARENT_POM_MISSING')
    profiles = root.findall('./{*}profiles/{*}profile')
    require(any(profile.findtext('./{*}activation/{*}property/{*}name') == 'doorhandle.isolated-verification'
        and profile.findtext('./{*}build/{*}directory') == '${doorhandle.verification-root}/${project.artifactId}'
        for profile in profiles), 'PINNED_ISOLATED_BUILD_LAYOUT_NOT_PROVEN')
    parent_version = root.findtext('./{*}version')
    modules = {}
    for entry in root.findall('./{*}modules/{*}module'):
        name = entry.text; require(MODULE.fullmatch(name or ''), 'PINNED_MODULE_PATH_NOT_CLOSED')
        child = poms.get(name + '/pom.xml'); require(child is not None, 'PINNED_MODULE_POM_MISSING')
        artifact = child.findtext('./{*}artifactId'); version = child.findtext('./{*}version') or parent_version
        require(MODULE.fullmatch(artifact or '') and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', version or ''), 'PINNED_ARTIFACT_ID_OR_VERSION_INVALID')
        require(child.find('./{*}build/{*}directory') is None, 'MODULE_OVERRIDES_ISOLATED_LAYOUT')
        final_name = child.findtext('./{*}build/{*}finalName') or artifact + '-' + version
        final_name = final_name.replace('${project.artifactId}', artifact).replace('${project.version}', version)
        require(re.fullmatch(r'[A-Za-z0-9_.-]{1,180}', final_name), 'PINNED_ARTIFACT_FINAL_NAME_NOT_CLOSED')
        modules[artifact] = {final_name + '.jar', final_name + '.jar.original', 'original-' + final_name + '.jar'}
    require(0 < len(modules) <= 64, 'PINNED_MODULE_SET_INVALID')
    return modules


def routing_ast_sha(function):
    # Python 3.12 added an empty type_params field to ordinary functions. Strip
    # only that empty metadata field so host and tool Python versions agree.
    for node in ast.walk(function):
        if 'type_params' in node._fields:
            if getattr(node, 'type_params', None) != []:
                return None
            node._fields = tuple(name for name in node._fields if name != 'type_params')
    return sha(ast.dump(function, include_attributes=False).encode())


def npm_cache_provenance(root, source, commit, manifest, inner, catalog, tools, verifier):
    """Admit only a cache produced by the archived, actually registered executor."""
    def skipped(reason):
        return {'status': 'SKIPPED', 'reason': reason}
    raw = None
    with verifier.bounded_tar(source, verifier.MAX_SOURCE_BYTES) as package:
        for item in package:
            if item.name != 'script/jenkins/ecs-tool-runtime.py':
                continue
            require(raw is None and item.isfile() and 0 < item.size <= 1024 ** 2,
                    'NPM_EXECUTOR_SOURCE_MEMBER_INVALID')
            raw = package.extractfile(item).read()
        require(package.pax_headers.get('comment') == commit, 'PINNED_SOURCE_COMMIT_DIFFERS')
    if raw is None:
        return skipped('NPM_EXECUTOR_SOURCE_MISSING')
    try:
        functions = {}
        for node in ast.parse(raw).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in NPM_ROUTING_AST:
                if node.name in functions:
                    return skipped('NPM_ROUTING_NOT_REVIEWED')
                functions[node.name] = routing_ast_sha(node)
    except (SyntaxError, UnicodeError, ValueError):
        return skipped('NPM_ROUTING_NOT_REVIEWED')
    if functions != NPM_ROUTING_AST:
        return skipped('NPM_ROUTING_NOT_REVIEWED')
    executor_sha = sha(raw)
    if not isinstance(manifest.get('files'), dict) or manifest['files'].get('executor.py') != executor_sha:
        return skipped('NPM_EXECUTOR_BINDING_MISSING_OR_CHANGED')
    try:
        executor = owned_chain(Path(manifest['directory']) / 'executor.py', root, maximum=1024 ** 2)
        if digest(executor) != executor_sha:
            return skipped('NPM_REGISTERED_EXECUTOR_CHANGED')
    except (OSError, ValueError):
        return skipped('NPM_REGISTERED_EXECUTOR_UNAVAILABLE')
    installs = [row for row in inner['commands'] if row.get('label') in
                ('frontend-install', 'frontend-agent-install')]
    if not installs or any('reports/' + row['label'] + '.log' not in catalog for row in installs):
        return skipped('NPM_INSTALL_PROVENANCE_MISSING')
    arguments_sha = sha(json.dumps(NPM_INSTALL_ARGUMENTS, ensure_ascii=True).encode())
    commands = tools.get('commands')
    if not isinstance(commands, list) or not any(
        isinstance(row, dict) and row.get('tool') == 'npm' and row.get('argumentsSha256') == arguments_sha
        and row.get('status') in ('EXITED', 'FAILED_OR_UNKNOWN')
        and isinstance(row.get('containerId'), str) and SHA.fullmatch(row['containerId'])
        and isinstance(row.get('cleanup'), dict) and row['cleanup'].get('containerId') == row['containerId']
        and type(row['cleanup'].get('pid')) is int and row['cleanup']['pid'] == 0
        and row['cleanup'].get('removed') is True
        for row in commands):
        return skipped('NPM_TOOL_COMMAND_PROVENANCE_MISSING')
    return {'status': 'PROVEN', 'executorSha256': executor_sha, 'routingAstSha256': functions,
            'installArgumentsSha256': arguments_sha}


def pytest_temp_provenance(root, source, commit, manifest, inner, catalog, tools, verifier):
    """Prove only synthetic source pytest data, never native migration fixtures."""
    def skipped(reason): return {'status': 'SKIPPED', 'reason': reason}
    commands = inner.get('commands', [])
    python = [row for row in commands if isinstance(row, dict) and row.get('label') == 'python']
    if (inner.get('scopeKind') != 'source' or inner.get('javaOnly') is not False
            or inner.get('wholeMigrationRequested') is not False or inner.get('workerMysqlRequested') is not False
            or inner.get('fixtureProperties') != [] or 'fixtureManifest' not in inner or inner['fixtureManifest'] is not None
            or 'workerMysqlConfigSha256' not in inner or inner['workerMysqlConfigSha256'] is not None or len(python) != 1
            or not python[0].get('finishedAt') or type(python[0].get('exitCode')) is not int
            or python[0]['exitCode'] != 0 or not {'reports/python.xml', 'reports/python.log'} <= set(catalog)):
        return skipped('PYTEST_SOURCE_SCOPE_REQUIRED')
    wanted = {'script/jenkins/verify-ecs.py', 'script/jenkins/ecs-tool-runtime.py'}
    recipes = {}
    with verifier.bounded_tar(source, verifier.MAX_SOURCE_BYTES) as package:
        for item in package:
            if item.name not in wanted: continue
            require(item.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and item.sparse is None
                    and item.name not in recipes and 0 < item.size <= 1024 ** 2, 'PYTEST_SOURCE_RECIPE_INVALID')
            recipes[item.name] = package.extractfile(item).read()
        require(package.pax_headers.get('comment') == commit, 'PINNED_SOURCE_COMMIT_DIFFERS')
    if set(recipes) != wanted: return skipped('PYTEST_SOURCE_RECIPE_MISSING')
    runner = recipes['script/jenkins/verify-ecs.py']; executor = recipes['script/jenkins/ecs-tool-runtime.py']
    try:
        mains = [node for node in ast.parse(runner).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name == 'main']
        main_sha = routing_ast_sha(mains[0]) if len(mains) == 1 and isinstance(mains[0], ast.FunctionDef) else None
        if main_sha not in PYTEST_RUNNER_MAIN_AST: return skipped('PYTEST_RUNNER_NOT_REVIEWED')
        routing = {}
        for node in ast.parse(executor).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in NPM_ROUTING_AST:
                if node.name in routing: return skipped('PYTEST_ROUTING_NOT_REVIEWED')
                routing[node.name] = routing_ast_sha(node)
    except (SyntaxError, UnicodeError, ValueError): return skipped('PYTEST_RUNNER_NOT_REVIEWED')
    if routing != NPM_ROUTING_AST: return skipped('PYTEST_ROUTING_NOT_REVIEWED')
    checkout = Path(manifest['checkout']); runner_sha, executor_sha = sha(runner), sha(executor)
    try:
        actual_runner = owned_chain(checkout / 'script/jenkins/verify-ecs.py', root, maximum=1024 ** 2)
        if digest(actual_runner) != runner_sha: return skipped('PYTEST_RUNNER_BINDING_MISSING_OR_CHANGED')
    except (OSError, ValueError): return skipped('PYTEST_RUNNER_BINDING_MISSING_OR_CHANGED')
    if not isinstance(manifest.get('files'), dict) or manifest['files'].get('executor.py') != executor_sha:
        return skipped('PYTEST_EXECUTOR_BINDING_MISSING_OR_CHANGED')
    try:
        actual_executor = owned_chain(Path(manifest['directory']) / 'executor.py', root, maximum=1024 ** 2)
        if digest(actual_executor) != executor_sha: return skipped('PYTEST_EXECUTOR_BINDING_MISSING_OR_CHANGED')
    except (OSError, ValueError): return skipped('PYTEST_REGISTERED_EXECUTOR_UNAVAILABLE')
    try:
        report = owned_chain(checkout / 'work/ci-evidence/python.xml', root, maximum=verifier.MAX_FILE_BYTES)
        with report.open('rb') as stream: raw = stream.read(verifier.MAX_FILE_BYTES + 1)
        descriptor = catalog['reports/python.xml']
        if len(raw) != descriptor['bytes'] or sha(raw) != descriptor['sha256'] or b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
            return skipped('PYTEST_REPORT_NOT_PASS')
        tally = {'found': 0, 'passed': 0, 'failed': 0, 'skipped': 0}
        for case in ET.fromstring(raw).iter('testcase'):
            result = 'failed' if case.find('failure') is not None or case.find('error') is not None else (
                'skipped' if case.find('skipped') is not None else 'passed')
            tally['found'] += 1; tally[result] += 1
        expected = inner.get('pythonTests')
        if (not isinstance(expected, dict) or set(expected) != set(tally)
                or any(type(value) is not int for value in expected.values())
                or tally != expected or not tally['passed'] or tally['failed']):
            return skipped('PYTEST_REPORT_NOT_PASS')
    except (OSError, ValueError, ET.ParseError): return skipped('PYTEST_REPORT_NOT_PASS')
    arguments = ['-B', '-m', 'pytest', 'tests_python', '-q', '--basetemp=' + str(checkout / PYTEST_TMP_SUFFIX),
                 '--junitxml=' + str(checkout / 'work/ci-evidence/python.xml')]
    arguments_sha = sha(json.dumps(arguments, ensure_ascii=True).encode())
    actual = tools.get('commands')
    matching = [row for row in actual if isinstance(row, dict) and row.get('tool') == 'python'
                and row.get('argumentsSha256') == arguments_sha] if isinstance(actual, list) else []
    if len(matching) != 1: return skipped('PYTEST_TOOL_COMMAND_PROVENANCE_MISSING')
    command = matching[0]; cleaned = command.get('cleanup', {})
    images = manifest.get('images'); image = images.get('python') if isinstance(images, dict) else None
    if (command.get('status') != 'EXITED' or type(command.get('exitCode')) is not int or command['exitCode'] != 0
            or not isinstance(command.get('containerId'), str) or not SHA.fullmatch(command['containerId'])
            or not isinstance(cleaned, dict) or cleaned.get('containerId') != command['containerId']
            or not isinstance(image, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', image)
            or cleaned.get('image') != image or type(cleaned.get('pid')) is not int or cleaned['pid'] != 0
            or type(cleaned.get('exitCode')) is not int or cleaned['exitCode'] != 0 or cleaned.get('removed') is not True):
        return skipped('PYTEST_TOOL_COMMAND_PROVENANCE_MISSING')
    return {'status': 'PROVEN', 'runnerSha256': runner_sha, 'runnerMainAstSha256': main_sha,
            'executorSha256': executor_sha, 'routingAstSha256': routing, 'argumentsSha256': arguments_sha,
            'pythonTests': tally}


def evidence_binding(root, custody, identity, verifier):
    tag = custody['release']; attempt = owned_chain(root / 'verification' / tag, root, directory=True)
    checkout = owned_chain(attempt / 'checkout', root, directory=True)
    inbox = owned_chain(root / 'inbox' / tag, root, directory=True)
    receipt_path = owned_chain(attempt / 'verification-receipt.json', root, maximum=verifier.MAX_RECEIPT_BYTES)
    require(digest(receipt_path) == custody['verificationReceiptSha256'], 'RETAINED_RECEIPT_DIFFERS_FROM_ECS')
    record = read_json(receipt_path, verifier.MAX_RECEIPT_BYTES); catalog = receipt_catalog(record, verifier)
    require(catalog and any(name.endswith('.xml') for name in catalog), 'NO_ORIGINAL_REPORT_CATALOG')
    require(all(record.get(key) == custody.get(key) for key in ('release', 'commit', 'sourceSha256', 'identity'))
            and record['identity'] == identity and record.get('finishedAt') and not record.get('evidenceOmissions'), 'OLD_BUILD_BINDING_INCOMPLETE')
    require(sha(canonical(record['reportFiles'])) == custody['reportCatalogSha256']
            and len(catalog) == custody['reportFiles'] and sum(row['bytes'] for row in catalog.values()) == custody['reportBytes'],
            'RETAINED_REPORT_CATALOG_DIFFERS')
    archive = owned_chain(inbox / 'verification-evidence.tar.gz', root, maximum=verifier.MAX_EVIDENCE_ARCHIVE)
    archive_proof = {'bytes': archive.stat().st_size, 'sha256': digest(archive)}
    require(custody['originalEvidenceArchive'] is None or custody['originalEvidenceArchive'] == archive_proof, 'RETAINED_TAR_DIFFERS_FROM_ECS')
    seen = set()
    with verifier.bounded_tar(archive, verifier.MAX_EVIDENCE_BYTES) as package:
        for item in package:
            name = item.name
            require(item.isfile() and name not in seen and (name == 'verification-receipt.json' or name in catalog), 'UNEXPECTED_EVIDENCE_TAR_MEMBER')
            expected = {'bytes': receipt_path.stat().st_size, 'sha256': custody['verificationReceiptSha256']} if name == 'verification-receipt.json' else catalog[name]
            require(item.size == expected['bytes'], 'EVIDENCE_TAR_MEMBER_SIZE_DIFFERS')
            content = package.extractfile(item); actual = hashlib.sha256()
            for block in iter(lambda: content.read(1024 * 1024), b''): actual.update(block)
            require(actual.hexdigest() == expected['sha256'], 'EVIDENCE_TAR_MEMBER_SHA_DIFFERS'); seen.add(name)
    require(seen == {'verification-receipt.json', *catalog}, 'EVIDENCE_TAR_MISSING_ORIGINAL_REPORTS')
    for name, row in catalog.items():
        file = checkout / ('driver.log' if name == 'driver.log' else 'work/ci-evidence/' + name.removeprefix('reports/'))
        owned_chain(file, root, maximum=verifier.MAX_FILE_BYTES)
        require(file.stat().st_size == row['bytes'] and digest(file) == row['sha256'], 'ECS_ORIGINAL_REPORT_CHANGED')
    inner = read_json(checkout / 'work/ci-evidence/receipt.json', verifier.MAX_RECEIPT_BYTES)
    require(inner.get('scopeKind') == 'source' and inner.get('finishedAt') and inner.get('status') in ('PASS', 'FAILED'), 'SOURCE_BUILD_NOT_FINISHED')
    require(inner.get('identity') == identity and isinstance(inner.get('commands'), list)
            and inner['commands'] and all(command.get('finishedAt') and type(command.get('exitCode')) is int
                                          for command in inner['commands']), 'BUILD_HAS_UNSETTLED_COMMANDS')
    tools = read_json(checkout / 'work/ci-evidence/tool-runtime.json', 1024 ** 2)
    manifest_path = owned_chain(inbox / 'tool-runtime/manifest.json', root, maximum=1024 ** 2)
    manifest = read_json(manifest_path, 1024 ** 2); manifest_sha = digest(manifest_path)
    require(record.get('toolRuntime', {}).get('cleanupStatus') == 'STOPPED'
            and record['toolRuntime'].get('manifestSha256') == manifest_sha
            and record['toolRuntime'].get('evidenceSha256') == digest(checkout / 'work/ci-evidence/tool-runtime.json'), 'TOOL_STOP_EVIDENCE_NOT_BOUND')
    require(tools.get('kind') == 'doorhandle-ecs-tool-evidence'
            and tools.get('manifestSha256') == manifest_sha
            and manifest.get('schema') == 1 and manifest.get('kind') == 'doorhandle-ecs-tool-runtime'
            and manifest.get('directory') == str(manifest_path.parent)
            and all(tools.get(key) == record[key] and manifest.get(key) == record[key] for key in ('release', 'commit', 'sourceSha256'))
            and manifest.get('identity') == identity and manifest.get('uid') == os.getuid()
            and manifest.get('checkout') == str(checkout) and re.fullmatch(r'[a-f0-9]{24}', manifest.get('token', '')),
            'TOOL_MANIFEST_BELONGS_TO_ANOTHER_BUILD')
    stopped = tools.get('cleanup', {})
    require(stopped.get('status') == 'STOPPED' and stopped.get('remaining') == [] and stopped.get('release') == tag
            and stopped.get('manifestSha256') == manifest_sha, 'TOOLS_NOT_CONFIRMED_STOPPED')
    source = owned_chain(inbox / 'source.tar.gz', root, maximum=verifier.MAX_SOURCE_ARCHIVE)
    require(digest(source) == record['sourceSha256'], 'OLD_PINNED_SOURCE_ARCHIVE_CHANGED')
    claim_file = owned_chain(attempt / '.verification-claimed/claim.json', root)
    claim = read_json(claim_file)
    require(claim == {'schema': 1, 'kind': 'doorhandle-ci-claim', 'release': tag, 'attempt': record['attempt'],
            'commit': record['commit'], 'sourceSha256': record['sourceSha256'], 'identity': identity, 'scope': 'source'},
            'ORIGINAL_ATTEMPT_OWNER_CLAIM_DIFFERS')
    result = {'checkout': checkout, 'inner': inner, 'token': manifest['token'], 'catalog': catalog,
            'modules': fixed_build_layout(source, record['commit'], verifier), 'evidenceArchive': archive_proof,
            'claimSha256': digest(claim_file), 'toolManifestSha256': manifest_sha}
    cache = checkout / NPM_CACHE_SUFFIX
    if cache.exists() or cache.is_symlink():
        result['npmCache'] = npm_cache_provenance(root, source, record['commit'], manifest, inner, catalog, tools, verifier)
    temporary = checkout / PYTEST_TMP_SUFFIX
    if temporary.exists() or temporary.is_symlink():
        result['pytestTmp'] = pytest_temp_provenance(root, source, record['commit'], manifest, inner, catalog, tools, verifier)
    return result


def docker_snapshot():
    command = ['/usr/bin/docker', 'ps', '-aq', '--no-trunc']
    result = subprocess.run(command, capture_output=True, timeout=15)
    require(result.returncode == 0, 'DOCKER_STATE_NOT_VERIFIABLE')
    ids = result.stdout.decode().split(); require(len(ids) <= 256, 'DOCKER_CONTAINER_SCAN_BOUND_EXCEEDED')
    if not ids: return []
    template = '[{{json .Id}},{{json .State.Running}},{{json .State.Restarting}},{{json .State.Pid}},{{json (index .Config.Labels "io.doorhandle.release")}},{{json (index .Config.Labels "io.doorhandle.ci-tool-runtime")}},{{json .Mounts}}]'
    result = subprocess.run(['/usr/bin/docker', 'inspect', '--format', template, *ids], capture_output=True, timeout=15)
    require(result.returncode == 0, 'DOCKER_MOUNTS_NOT_VERIFIABLE')
    return [json.loads(line) for line in result.stdout.decode().splitlines()]


def quiescent(binding, tag, containers):
    checkout = binding['checkout']
    for _cid, running, restarting, pid, release, token, mounts in containers:
        require(release != tag and token != binding['token'], 'OLD_BUILD_CONTAINER_STILL_PRESENT')
        for mount in mounts:
            if mount.get('Type') != 'bind' or not mount.get('Source'): continue
            source = Path(mount['Source'])
            require(not (source == checkout or source.is_relative_to(checkout) or checkout.is_relative_to(source)),
                    'CONTAINER_REFERENCES_OLD_CHECKOUT')
    process_references(checkout)


def process_reference(raw, checkout):
    text = os.fsdecode(raw).removesuffix(' (deleted)')
    if '=' in text and not text.startswith('/'): text = text.split('=', 1)[1]
    path = Path(text)
    return path.is_absolute() and (path == checkout or path.is_relative_to(checkout))


def probe_result(status, checkout, pid, uid, nonce):
    return {'schema': 1, 'kind': PROCESS_PROBE_KIND, 'status': status,
            'pid': pid, 'uid': uid, 'checkout': str(checkout), 'nonce': nonce}


def checked_probe_checkout(checkout):
    checkout = Path(checkout)
    require(checkout.is_absolute() and '..' not in checkout.parts
            and checkout.resolve(strict=True) == checkout and checkout.name == 'checkout'
            and TAG.fullmatch(checkout.parent.name)
            and checkout.parent.parent.name == 'verification'
            and len(checkout.parts) > 5 and checkout.parts[1] in ('home', 'srv', 'opt'),
            'PROCESS_PROBE_CHECKOUT_NOT_CANONICAL_CI_PATH')
    root = checkout.parent.parent.parent
    for path in (root, checkout.parent.parent, checkout.parent, checkout):
        info = path.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 1000 and not info.st_mode & 0o022,
                'PROCESS_PROBE_CHECKOUT_OWNER_OR_MODE_CHANGED')
    return checkout


def probe_read(pid_fd, name, maximum):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=pid_fd)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), 'PROCESS_METADATA_NOT_REGULAR')
        chunks = []; total = 0
        while True:
            raw = os.read(fd, min(65536, maximum + 1 - total))
            if not raw: break
            total += len(raw); require(total <= maximum, 'PROCESS_METADATA_BOUND_EXCEEDED'); chunks.append(raw)
        return b''.join(chunks)
    finally:
        os.close(fd)


def process_identity_at(pid_fd, pid, uid):
    raw = probe_read(pid_fd, 'stat', 65536)
    opening, closing = raw.find(b'('), raw.rfind(b')')
    require(opening > 0 and closing > opening and raw[:opening].strip() == str(pid).encode(),
            'PROCESS_STAT_IDENTITY_INVALID')
    fields = raw[closing + 1:].split()
    require(len(fields) >= 20 and fields[19].isdigit(), 'PROCESS_START_TIME_INVALID')
    status = probe_read(pid_fd, 'status', 65536); ids = {}
    for line in status.splitlines():
        if line.startswith((b'Uid:', b'Gid:')):
            key, values = line.split(b':', 1)
            require(key not in ids and len(values.split()) == 4 and all(x.isdigit() for x in values.split()),
                    'PROCESS_UID_OR_GID_METADATA_INVALID')
            ids[key] = tuple(int(x) for x in values.split())
    require(set(ids) == {b'Uid', b'Gid'} and ids[b'Uid'] == (uid,) * 4,
            'PROCESS_PROBE_UID_CHANGED')
    return int(fields[19]), ids[b'Uid'], ids[b'Gid']


def confirm_pid_gone(proc_fd, pid):
    # Absence is required twice. An alive replacement, unreadable task, zombie,
    # or a missing metadata file within a live task is never reported as GONE.
    for unused in range(2):
        try:
            os.stat(str(pid), dir_fd=proc_fd, follow_symlinks=False)
        except (FileNotFoundError, ProcessLookupError):
            continue
        raise ValueError('PROCESS_DISAPPEARANCE_NOT_PROVEN')


def single_process_metadata(checkout, pid, uid, nonce, *, proc=Path('/proc')):
    """Root-only read-only probe. ``proc`` is internal synthetic-test injection."""
    require(sys.platform == 'linux' and os.geteuid() == 0, 'ROOT_PROCESS_METADATA_MODE_REQUIRED')
    require(type(pid) is int and 0 < pid <= 2 ** 31 - 1 and type(uid) is int and uid == 1000
            and isinstance(nonce, str) and re.fullmatch(r'[a-f0-9]{32}', nonce), 'PROCESS_PROBE_REQUEST_INVALID')
    checkout = checked_probe_checkout(checkout)
    proc_fd = os.open(proc, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    pid_fd = None
    try:
        try:
            pid_fd = os.open(str(pid), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=proc_fd)
        except (FileNotFoundError, ProcessLookupError):
            confirm_pid_gone(proc_fd, pid)
            return probe_result('GONE', checkout, pid, uid, nonce)
        before = os.fstat(pid_fd); before_identity = None
        try:
            before_identity = process_identity_at(pid_fd, pid, uid)
            require(not process_reference(os.readlink('cwd', dir_fd=pid_fd), checkout),
                    'ACTIVE_PROCESS_REFERENCES_OLD_CHECKOUT')
            argv = probe_read(pid_fd, 'cmdline', 1024 ** 2)
            require(not any(process_reference(arg, checkout) for arg in argv.split(b'\0') if arg),
                    'ACTIVE_PROCESS_REFERENCES_OLD_CHECKOUT')
            fd_fd = os.open('fd', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=pid_fd)
            try:
                descriptors = os.listdir(fd_fd)
                require(len(descriptors) <= 8192 and all(name.isascii() and name.isdecimal() for name in descriptors),
                        'PROCESS_DESCRIPTOR_SCAN_BOUND_EXCEEDED')
                for descriptor in descriptors:
                    try:
                        target = os.readlink(descriptor, dir_fd=fd_fd)
                    except (FileNotFoundError, ProcessLookupError):
                        try:
                            os.stat(descriptor, dir_fd=fd_fd, follow_symlinks=False)
                        except (FileNotFoundError, ProcessLookupError):
                            continue  # Only this vanished descriptor is skipped.
                        raise ValueError('PROCESS_DESCRIPTOR_CHANGED_DURING_SCAN')
                    require(not process_reference(target, checkout), 'ACTIVE_FILE_DESCRIPTOR_REFERENCES_OLD_CHECKOUT')
            finally:
                os.close(fd_fd)
            maps = probe_read(pid_fd, 'maps', 16 * 1024 ** 2)
            for line in maps.splitlines():
                fields = line.split(None, 5)
                if len(fields) == 6:
                    require(not process_reference(fields[5], checkout), 'ACTIVE_MEMORY_MAP_REFERENCES_OLD_CHECKOUT')
            after_identity = process_identity_at(pid_fd, pid, uid)
            current = os.stat(str(pid), dir_fd=proc_fd, follow_symlinks=False)
            require((current.st_dev, current.st_ino) == (before.st_dev, before.st_ino)
                    and after_identity == before_identity, 'PROCESS_PID_OR_IDENTITY_REUSED')
        except (FileNotFoundError, ProcessLookupError):
            confirm_pid_gone(proc_fd, pid)
            return probe_result('GONE', checkout, pid, uid, nonce)
        return probe_result('QUIESCENT', checkout, pid, uid, nonce)
    finally:
        if pid_fd is not None: os.close(pid_fd)
        os.close(proc_fd)


def privileged_process_probe(checkout, pid, proc):
    require(sys.platform == 'linux' and proc == Path('/proc') and os.getuid() == 1000 and os.geteuid() == 1000,
            'PRIVILEGED_PROCESS_PROBE_SCOPE_REFUSED')
    checkout = checked_probe_checkout(checkout)
    require(LOADED_SOURCE is not None and len(LOADED_SOURCE) <= 1024 ** 2, 'FIXED_PROCESS_PROBE_SOURCE_REQUIRED')
    source = owned(Path(__file__).absolute(), maximum=1024 ** 2)
    admitted = metadata(source.lstat())
    with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        info = os.fstat(stream.fileno()); before = metadata(info)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 1000 and info.st_nlink == 1
                and not info.st_mode & 0o022 and info.st_size <= 1024 ** 2 and before == admitted,
                'OPENED_PROCESS_PROBE_SOURCE_NOT_ADMITTED')
        raw = stream.read(1024 ** 2 + 1)
        require(raw == LOADED_SOURCE and before == metadata(os.fstat(stream.fileno()))
                and before == metadata(source.lstat()), 'LOADED_PROCESS_PROBE_SOURCE_CHANGED')
    nonce = secrets.token_hex(16)
    command = ['/usr/bin/sudo', '-n', '/usr/bin/python3', '-I', '-B', '-', 'inspect-process',
               '--checkout', str(checkout), '--pid', str(pid), '--uid', '1000', '--nonce', nonce]
    result = subprocess.run(command, input=raw, capture_output=True, timeout=20,
                            env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'})
    require(result.returncode == 0 and len(result.stdout) <= 4096 and len(result.stderr) <= 4096,
            'PRIVILEGED_PROCESS_METADATA_UNAVAILABLE')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'DUPLICATE_PROCESS_PROBE_FIELD'); value[key] = item
        return value
    value = json.loads(result.stdout, object_pairs_hook=unique,
                       parse_constant=lambda unused: require(False, 'NONFINITE_PROCESS_PROBE_FIELD'))
    expected = probe_result(value.get('status') if isinstance(value, dict) else None, checkout, pid, 1000, nonce)
    require(isinstance(value, dict) and set(value) == set(expected) and value == expected
            and type(value['schema']) is int and type(value['pid']) is int and type(value['uid']) is int
            and value['status'] in ('QUIESCENT', 'GONE'), 'PROCESS_PROBE_RESPONSE_NOT_BOUND')


def process_references(checkout, proc=Path('/proc')):
    """Read only cwd/argv/fd paths; root fallback is restricted to one denied PID."""
    def references(raw):
        return process_reference(raw, checkout)

    entries = list(proc.iterdir()); require(len(entries) <= 65536, 'PROCESS_SCAN_BOUND_EXCEEDED')
    for entry in entries:
        if not entry.name.isdecimal(): continue
        if int(entry.name) == os.getpid(): continue
        same_uid = False
        try:
            if entry.stat().st_uid != os.getuid(): continue
            same_uid = True
            require(not references(os.readlink(entry / 'cwd')), 'ACTIVE_PROCESS_REFERENCES_OLD_CHECKOUT')
            with (entry / 'cmdline').open('rb') as stream: argv = stream.read(1024 ** 2 + 1)
            require(len(argv) <= 1024 ** 2, 'PROCESS_ARGUMENT_SCAN_BOUND_EXCEEDED')
            require(not any(references(arg) for arg in argv.split(b'\0') if arg), 'ACTIVE_PROCESS_REFERENCES_OLD_CHECKOUT')
            descriptors = list((entry / 'fd').iterdir())
            require(len(descriptors) <= 8192, 'PROCESS_DESCRIPTOR_SCAN_BOUND_EXCEEDED')
            for descriptor in descriptors:
                try:
                    target = os.readlink(descriptor)
                except (FileNotFoundError, ProcessLookupError):
                    try: descriptor.lstat()
                    except (FileNotFoundError, ProcessLookupError): continue
                    raise ValueError('PROCESS_DESCRIPTOR_CHANGED_DURING_SCAN')
                require(not references(target), 'ACTIVE_FILE_DESCRIPTOR_REFERENCES_OLD_CHECKOUT')
            with (entry / 'maps').open('rb') as stream: maps = stream.read(16 * 1024 ** 2 + 1)
            require(len(maps) <= 16 * 1024 ** 2, 'PROCESS_MAP_SCAN_BOUND_EXCEEDED')
            for line in maps.splitlines():
                fields = line.split(None, 5)
                if len(fields) == 6:
                    require(not references(fields[5]), 'ACTIVE_MEMORY_MAP_REFERENCES_OLD_CHECKOUT')
        except (FileNotFoundError, ProcessLookupError):
            try: entry.stat()
            except (FileNotFoundError, ProcessLookupError): continue
            raise ValueError('LIVE_PROCESS_METADATA_DISAPPEARED')
        except PermissionError:
            if not same_uid or sys.platform != 'linux' or proc != Path('/proc') or os.getuid() != 1000 or os.geteuid() != 1000:
                raise
            privileged_process_probe(checkout, int(entry.name), proc)


def metadata(info):
    return [info.st_mode, info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns,
            info.st_ino, info.st_dev, info.st_ctime_ns, info.st_nlink]


def tree_inventory(path):
    path = owned(path, directory=True); device = path.stat().st_dev
    rows = []; files = size = allocated = 0
    def unreadable(error): raise error
    for current, dirs, names in os.walk(path, followlinks=False, onerror=unreadable):
        for name in sorted(dirs + names):
            item = Path(current) / name; info = item.lstat()
            require(info.st_uid == os.getuid() and info.st_dev == device and not info.st_mode & 0o022
                    and (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)), 'TREE_OWNER_TYPE_LINK_OR_DEVICE_CHANGED')
            relative = item.relative_to(path).as_posix()
            row = {'path': relative, 'metadata': metadata(info)}
            if stat.S_ISREG(info.st_mode):
                require(info.st_nlink == 1, 'TREE_FILE_HARDLINK_NOT_ALLOWED')
                row['sha256'] = digest(item); files += 1; size += info.st_size
                require(files <= MAX_TREE_FILES and size <= MAX_TREE_BYTES, 'TREE_RECLAMATION_BOUND_EXCEEDED')
            rows.append(row); allocated += info.st_blocks * 512
            require(len(rows) <= MAX_TREE_ENTRIES, 'TREE_RECLAMATION_BOUND_EXCEEDED')
        dirs.sort()
    keys = {(row['metadata'][6], row['metadata'][5]) for row in rows}
    keys.add((path.stat().st_dev, path.stat().st_ino))
    require(not keys & locked_inodes(), 'OUTPUT_HAS_HELD_FILE_LOCK')
    return {'files': files, 'bytes': size, 'allocatedBytes': allocated, 'rootMetadata': metadata(path.lstat()),
            'inventorySha256': sha(canonical(rows)), 'entries': rows}


def locked_inodes(path=Path('/proc/locks')):
    result = set()
    with path.open('rb') as stream: raw = stream.read(4 * 1024 ** 2 + 1)
    require(len(raw) <= 4 * 1024 ** 2, 'LOCK_SCAN_BOUND_EXCEEDED')
    for line in raw.decode('ascii').splitlines():
        for field in line.split():
            if re.fullmatch(r'[a-fA-F0-9]+:[a-fA-F0-9]+:[0-9]+', field):
                major, minor, inode = field.split(':')
                result.add((os.makedev(int(major, 16), int(minor, 16)), int(inode)))
                break
    return result


def pytest_case_preflight(path, root, *, remaining=None):
    """Reject synthetic negative fixtures before hashing any sparse/special file."""
    require(re.fullmatch(r'[A-Za-z0-9_.-]{1,180}', path.name) and path.name not in ('.', '..'),
            'PYTEST_CASE_NAME_INVALID')
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode), 'PYTEST_CASE_NOT_REGULAR_DIRECTORY')
    require(info.st_dev == Path(root).stat().st_dev, 'PYTEST_CASE_METADATA_UNSAFE')
    owned_chain(path, root, directory=True); device = info.st_dev
    descriptor = {'path': path.relative_to(root).as_posix(), 'kind': 'PYTEST_CASE_DIRECTORY',
                  'files': 0, 'bytes': 0, 'allocatedBytes': 0, 'rootMetadata': metadata(info),
                  'inventorySha256': '0' * 64, 'entries': []}
    files = size = entries = allocated = row_bytes = 0
    def projected():
        descriptor.update(files=files, bytes=size, allocatedBytes=allocated)
        return len(canonical(descriptor)) + (row_bytes - 1 if entries else 0) + 1
    if remaining is not None:
        require(projected() <= remaining, 'PYTEST_TARGET_CANONICAL_BUDGET_EXCEEDED')
    def unreadable(error): raise error
    for current, dirs, names in os.walk(path, followlinks=False, onerror=unreadable):
        for name in sorted(dirs + names):
            item = Path(current) / name; info = item.lstat(); entries += 1
            require(info.st_uid == os.getuid() and info.st_dev == device and not info.st_mode & 0o022
                    and (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)), 'PYTEST_CASE_METADATA_UNSAFE')
            if stat.S_ISREG(info.st_mode):
                require(info.st_nlink == 1 and info.st_size <= info.st_blocks * 512, 'PYTEST_CASE_HARDLINK_OR_SPARSE')
                files += 1; size += info.st_size
            require(files <= MAX_TREE_FILES and size <= MAX_TREE_BYTES and entries <= MAX_TREE_ENTRIES,
                    'PYTEST_CASE_BOUND_EXCEEDED')
            row = {'path': item.relative_to(path).as_posix(), 'metadata': metadata(info)}
            if stat.S_ISREG(info.st_mode): row['sha256'] = '0' * 64
            row_bytes += len(canonical(row)) + 1; allocated += info.st_blocks * 512
            if remaining is not None:
                require(projected() <= remaining, 'PYTEST_TARGET_CANONICAL_BUDGET_EXCEEDED')
        dirs.sort()
    return projected()


def pytest_case_targets(root, binding, *, budget=None):
    proof = binding.get('pytestTmp')
    if not isinstance(proof, dict) or proof.get('status') != 'PROVEN': return []
    if budget is None: budget = {'remaining': MAX_TARGET_CANONICAL}
    parent = binding['checkout'] / PYTEST_TMP_SUFFIX
    proof['skippedCases'] = []; proof['skippedCaseCount'] = 0
    skipped_sha = hashlib.sha256(); proof['skippedCasesSha256'] = skipped_sha.hexdigest()
    try:
        owned_chain(parent, root, directory=True)
        children = sorted(parent.iterdir(), key=lambda path: path.name)
        require(len(children) <= MAX_TREE_ENTRIES, 'PYTEST_CASE_BOUND_EXCEEDED')
    except (OSError, ValueError) as error:
        proof['rootStatus'] = 'SKIPPED'
        proof['rootReason'] = failure_guard_code(error)
        return []
    proof['rootStatus'] = 'INSPECTED'; result = []
    for child in children:
        try:
            pytest_case_preflight(child, root, remaining=budget['remaining'])
            data = tree_inventory(child)
            target = {'path': child.relative_to(root).as_posix(), 'kind': 'PYTEST_CASE_DIRECTORY', **data}
            cost = len(canonical(target)) + 1
            require(cost <= budget['remaining'], 'PYTEST_TARGET_CANONICAL_BUDGET_EXCEEDED')
            budget['remaining'] -= cost; result.append(target)
        except (OSError, ValueError) as error:
            label = {'name': child.name} if re.fullmatch(r'[A-Za-z0-9_.-]{1,180}', child.name) else {
                'nameSha256': sha(os.fsencode(child.name))}
            row = {**label, 'reason': failure_guard_code(error)}
            proof['skippedCaseCount'] += 1; skipped_sha.update(canonical(row) + b'\n')
            if len(proof['skippedCases']) < PYTEST_SKIP_DETAIL_LIMIT: proof['skippedCases'].append(row)
    proof['skippedCasesSha256'] = skipped_sha.hexdigest()
    return result


def target_descriptors(root, binding, *, include_pytest=True, budget=None):
    if budget is None: budget = {'remaining': MAX_TARGET_CANONICAL}
    checkout = binding['checkout']; evidence = checkout / 'work/ci-evidence'
    candidates = []
    suites = [(evidence / 'java-suites' / row['id']) for row in binding['inner'].get('javaSuites', [])
              if re.fullmatch(r'suite-[0-9]{3}', row.get('id', ''))]
    if binding['inner'].get('sourceRegression'):
        suites.append(evidence / 'source-regression/build')
    for suite in suites:
        if not suite.exists() and not suite.is_symlink(): continue
        owned_chain(suite, root, directory=True)
        for module in binding['modules']:
            folder = suite / module
            if not folder.exists() and not folder.is_symlink(): continue
            owned_chain(folder, root, directory=True)
            for name in sorted(COMPILE_DIRS):
                target = folder / name
                if target.exists() or target.is_symlink(): candidates.append((target, 'COMPILED_DIRECTORY'))
    for frontend in FRONTENDS:
        target = checkout / frontend / 'node_modules'
        if not target.exists() and not target.is_symlink(): continue
        label = frontend + '-install'
        commands = [row for row in binding['inner']['commands'] if row.get('label') == label]
        require(len(commands) == 1 and 'reports/' + label + '.log' in binding['catalog'],
                'NODE_DEPENDENCIES_LACK_ARCHIVED_INSTALL_PROVENANCE')
        owned_chain(target, root, directory=True)
        candidates.append((target, 'NODE_MODULES'))
    if binding.get('npmCache', {}).get('status') == 'PROVEN':
        target = checkout / NPM_CACHE_SUFFIX
        owned_chain(target, root, directory=True)
        candidates.append((target, 'NPM_CACHE'))
    result = []
    for target, kind in sorted(candidates):
        relative = target.relative_to(root).as_posix()
        owned_chain(target, root, directory=True)
        data = tree_inventory(target)
        result.append({'path': relative, 'kind': kind, **data})
    cost = sum(len(canonical(target)) + 1 for target in result)
    require(cost <= budget['remaining'], 'TARGET_CANONICAL_BUDGET_EXCEEDED')
    budget['remaining'] -= cost
    if include_pytest: result.extend(pytest_case_targets(root, binding, budget=budget))
    return result


@contextmanager
def attempt_lock(root, tag):
    """flock the existing attempt directory; planning creates no lock file."""
    import fcntl
    folder = owned_chain(root / 'verification' / tag, root, directory=True)
    descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        require(metadata(os.fstat(descriptor)) == metadata(folder.lstat()), 'ATTEMPT_DIRECTORY_CHANGED')
        try: fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('OLD_ATTEMPT_LOCK_HELD') from None
        yield
    finally:
        os.close(descriptor)


def build_plan(root, request, verifier, containers, *, held_releases=()):
    root = owned(root, directory=True)
    require(set(request) == {'schema', 'kind', 'currentRelease', 'identity', 'protectedReleases', 'candidates'}
            and request['schema'] == 1 and request['kind'] == 'doorhandle-old-build-cleanup-request', 'CLEANUP_REQUEST_SCHEMA_INVALID')
    current = request['currentRelease']; require(TAG.fullmatch(current), 'CURRENT_RELEASE_INVALID')
    require(set(request['identity']) == {'instanceId', 'machineId', 'executionLocation'}
            and request['identity']['executionLocation'] == 'ECS'
            and re.fullmatch(r'i-[a-z0-9]+', request['identity']['instanceId'])
            and re.fullmatch(r'[a-f0-9]{32}', request['identity']['machineId']), 'REQUEST_ECS_IDENTITY_INVALID')
    protected = request['protectedReleases']
    require(isinstance(protected, list) and current in protected and all(TAG.fullmatch(tag) for tag in protected), 'CURRENT_OR_ROLLBACK_PROTECTION_MISSING')
    require(isinstance(request['candidates'], list) and len(request['candidates']) <= 256, 'TOO_MANY_CLEANUP_CANDIDATES')
    require(all(isinstance(item, dict) for item in request['candidates']), 'CLEANUP_CANDIDATE_NOT_AN_OBJECT')
    accepted = []; skipped = []; seen = set(); pending_pytest = []
    budget = {'remaining': MAX_TARGET_CANONICAL}
    for custody in request['candidates']:
        tag = custody.get('release', '')
        try:
            require(TAG.fullmatch(tag) and tag not in seen, 'INVALID_OR_REPEATED_CANDIDATE_TAG'); seen.add(tag)
            require(tag not in protected and int(TAG.fullmatch(tag)[1]) < int(TAG.fullmatch(current)[1]), 'CURRENT_OR_PROTECTED_BUILD')
            require('discoveryError' not in custody, custody.get('discoveryError', 'ATTEMPT_NOT_TERMINAL_SOURCE'))
            require(not (root / 'releases' / tag).exists() and not (root / 'releases' / tag).is_symlink(), 'BUILD_HAS_RETAINED_RELEASE_OR_ROLLBACK_ARTIFACTS')
            if custody.get('kind') == 'doorhandle-original-evidence-custody':
                require(custody.get('status') == 'VERIFIED_LOCAL_BYTES' and custody.get('testsExecutedLocally') is False
                        and SHA.fullmatch(custody.get('preservationSha256', '')), 'INDEPENDENT_ORIGINAL_EVIDENCE_CUSTODY_INVALID')
            else:
                require(custody.get('kind') == 'doorhandle-retained-ecs-evidence'
                        and custody.get('status') == 'VERIFY_RETAINED_ECS_BYTES', 'RETAINED_ORIGINAL_EVIDENCE_MISSING')
            with ExitStack() as locks:
                if tag not in held_releases: locks.enter_context(attempt_lock(root, tag))
                binding = evidence_binding(root, custody, request['identity'], verifier)
                quiescent(binding, tag, containers)
                candidate_budget = dict(budget)
                targets = target_descriptors(root, binding, include_pytest=False, budget=candidate_budget)
            candidate = {'release': tag, 'custodySha256': sha(canonical(custody)),
                'evidenceArchive': binding['evidenceArchive'], 'claimSha256': binding['claimSha256'],
                'toolManifestSha256': binding['toolManifestSha256'], 'targets': targets,
                **({'npmCache': binding['npmCache']} if 'npmCache' in binding else {}),
                **({'pytestTmp': binding['pytestTmp']} if 'pytestTmp' in binding else {})}
            accepted.append(candidate); budget = candidate_budget
            pending_pytest.append((tag, binding, candidate))
        except (ValueError, OSError, KeyError, TypeError, ET.ParseError, verifier.VerificationError) as error:
            skipped.append({'release': tag, 'reason': str(error) if isinstance(error, ValueError) else type(error).__name__})
    # Every original category has first claim on the one shared target budget.
    # Retained Python bindings are private process state, never serialized code.
    for tag, binding, candidate in pending_pytest:
        if binding.get('pytestTmp', {}).get('status') != 'PROVEN': continue
        try:
            with ExitStack() as locks:
                if tag not in held_releases: locks.enter_context(attempt_lock(root, tag))
                quiescent(binding, tag, docker_snapshot())
                candidate['targets'].extend(pytest_case_targets(root, binding, budget=budget))
        except (OSError, ValueError) as error:
            candidate['pytestTmp'].update(rootStatus='SKIPPED', rootReason=failure_guard_code(error))
    return {'schema': 1, 'kind': 'doorhandle-old-build-cleanup-plan', 'root': str(root), 'currentRelease': current,
        'identity': request['identity'], 'requestSha256': sha(canonical(request)), 'request': request,
        'executorSha256': digest(Path(__file__).resolve()), 'verifierSha256': digest(Path(verifier.__file__).resolve()),
        'candidates': accepted, 'skipped': skipped,
        'sourceDataDeleted': False, 'sharedMavenCachePreserved': True, 'originalEvidencePreserved': True,
        'publishedArtifactsPreserved': True, 'oldMavenRepositoriesPreserved': True,
        'candidateBytes': sum(t['bytes'] for c in accepted for t in c['targets']),
        'candidateAllocatedBytes': sum(t['allocatedBytes'] for c in accepted for t in c['targets'])}


def remove_target(root_fd, target):
    """Use descriptor-relative no-follow traversal; never a shell or broad prune."""
    base = r'verification/ci-[0-9]+-[a-f0-9]{12}/checkout/work/'
    build = base + r'ci-evidence/(?:java-suites/suite-[0-9]{3}|source-regression/build)/doorhandle-[a-z0-9-]+/'
    patterns = {'COMPILED_DIRECTORY': build + '(?:' + '|'.join(sorted(COMPILE_DIRS)) + ')',
        'NODE_MODULES': r'verification/ci-[0-9]+-[a-f0-9]{12}/checkout/(?:frontend|frontend-agent)/node_modules',
        'NPM_CACHE': base + re.escape(NPM_CACHE_SUFFIX.removeprefix('work/')),
        'PYTEST_CASE_DIRECTORY': base + re.escape(PYTEST_TMP_SUFFIX.removeprefix('work/')) + r'/[A-Za-z0-9_.-]{1,180}'}
    require(target.get('kind') in patterns and re.fullmatch(patterns[target['kind']], target.get('path', '')),
            'DELETION_TARGET_OUTSIDE_COMPILED_ALLOWLIST')
    require(target.get('kind') != 'PYTEST_CASE_DIRECTORY' or target['path'].rsplit('/', 1)[-1] not in ('.', '..'),
            'DELETION_TARGET_OUTSIDE_COMPILED_ALLOWLIST')
    parts = target['path'].split('/'); stack = [os.dup(root_fd)]
    try:
        device = os.fstat(root_fd).st_dev
        for part in parts[:-1]:
            descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=stack[-1])
            stack.append(descriptor); info = os.fstat(descriptor)
            require(info.st_uid == os.getuid() and info.st_dev == device and not info.st_mode & 0o022,
                    'DELETION_ANCESTOR_OWNER_OR_DEVICE_CHANGED')
        parent_fd = stack[-1]; name = parts[-1]
        require(metadata(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)) == target['rootMetadata'], 'TARGET_CHANGED_AFTER_APPROVAL')
        entries = {row['path']: row for row in target['entries']}
        require(len(entries) == len(target['entries']) and sha(canonical(target['entries'])) == target['inventorySha256'],
                'DELETION_INVENTORY_NOT_BOUND')

        def remove(directory_fd, prefix=''):
            for child in sorted(os.listdir(directory_fd)):
                relative = prefix + child; row = entries.get(relative)
                require(row is not None, 'NEW_FILE_AFTER_APPROVAL')
                info = os.stat(child, dir_fd=directory_fd, follow_symlinks=False)
                require(metadata(info) == row['metadata'], 'FILE_CHANGED_AFTER_APPROVAL')
                if stat.S_ISDIR(info.st_mode):
                    fd = os.open(child, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    try:
                        require(metadata(os.fstat(fd)) == row['metadata'], 'DIRECTORY_CHANGED_AFTER_APPROVAL')
                        remove(fd, relative + '/')
                    finally: os.close(fd)
                    os.rmdir(child, dir_fd=directory_fd)
                else:
                    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'FILE_BECAME_A_LINK')
                    file_fd = os.open(child, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    try:
                        require(metadata(os.fstat(file_fd)) == row['metadata'], 'FILE_CHANGED_AFTER_APPROVAL')
                        actual = hashlib.sha256()
                        while True:
                            block = os.read(file_fd, 1024 * 1024)
                            if not block: break
                            actual.update(block)
                        require(actual.hexdigest() == row['sha256']
                                and metadata(os.fstat(file_fd)) == row['metadata']
                                and metadata(os.stat(child, dir_fd=directory_fd, follow_symlinks=False)) == row['metadata'],
                                'FILE_BYTES_CHANGED_AFTER_APPROVAL')
                    finally: os.close(file_fd)
                    os.unlink(child, dir_fd=directory_fd)
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            require(metadata(os.fstat(fd)) == target['rootMetadata'], 'TARGET_CHANGED_AFTER_APPROVAL')
            remove(fd)
        finally: os.close(fd)
        os.rmdir(name, dir_fd=parent_fd)
    finally:
        for fd in reversed(stack): os.close(fd)


@contextmanager
def cleanup_lock(root):
    import fcntl
    file = root / '.old-build-cleanup.lock'
    with os.fdopen(os.open(file, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'r+b') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600, 'CLEANUP_LOCK_NOT_PRIVATE')
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try: yield
        finally: fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def deleted_projection(target):
    return {key: target[key] for key in ('path', 'kind', 'files', 'bytes', 'allocatedBytes', 'inventorySha256')}


def cleanup_receipt(plan, deleted, before_bytes, after_bytes, journal_sha, failure, finished):
    require(type(before_bytes) is int and type(after_bytes) is int and 0 <= before_bytes < 2 ** 128
            and 0 <= after_bytes < 2 ** 128, 'CLEANUP_DISK_COUNTER_EXCEEDS_CONTROL_BOUND')
    require(failure in (None, 'OSError', 'ValueError') and type(finished) is str and len(finished) <= 32
            and re.fullmatch(r'[0-9T:.+\-Z]+', finished) and type(journal_sha) is str and SHA.fullmatch(journal_sha),
            'CLEANUP_RECEIPT_FIXED_FIELD_BOUND_EXCEEDED')
    return {'schema': 1, 'kind': 'doorhandle-old-build-cleanup-receipt', 'status': 'PARTIAL_FAILURE' if failure else 'REMOVED' if deleted else 'NO_ACTION',
        'currentRelease': plan['currentRelease'], 'identity': plan['identity'], 'planSha256': sha(canonical(plan)),
        'deleted': deleted, 'skipped': plan['skipped'], 'availableBytesBefore': before_bytes,
        'availableBytesAfter': after_bytes, 'originalEvidencePreserved': True,
        'journalSha256': journal_sha, 'errorType': failure, 'sharedMavenCachePreserved': True,
        'publishedArtifactsPreserved': True, 'oldMavenRepositoriesPreserved': True,
        'businessDataDeleted': False, 'finishedAtUtc': finished}


def control_growth_budget(plan, *, include_plan, allocation_unit=4096):
    """Bound only the remaining immutable controls; never credit future deletions.

    Every successful journal event is known from the approved plan. Any partial
    execution is a prefix of those events plus the existing 4096-byte failure
    reserve. A receipt contains a prefix of the exact six-field projections and
    the unchanged skipped list; all variable fixed fields are bounded below.
    """
    require(type(allocation_unit) is int and 4096 <= allocation_unit <= 1024 ** 2
            and not allocation_unit & (allocation_unit - 1), 'CONTROL_ALLOCATION_UNIT_INVALID')
    plan_bytes = len(canonical(plan)) + 1
    projected = [deleted_projection(target) for candidate in plan['candidates'] for target in candidate['targets']]
    normal = len(canonical({'phase': 'STARTED', 'planSha256': sha(canonical(plan)), 'identity': plan['identity']})) + 1
    for target in projected:
        normal += len(canonical({'phase': 'DELETE_STARTED', 'path': target['path'], 'inventorySha256': target['inventorySha256']})) + 1
        normal += len(canonical({'phase': 'DELETE_FINISHED', **target})) + 1
    normal += len(canonical({'phase': 'FINISHED', 'deletedTargets': len(projected)})) + 1
    journal_bytes = normal + 4096
    receipt = cleanup_receipt(plan, projected, 2 ** 128 - 1, 2 ** 128 - 1, 'f' * 64,
                              'ValueError', '9999-12-31T23:59:59.999999+00:00')
    receipt_bytes = len(canonical(receipt)) + 1
    require(max(plan_bytes, journal_bytes, receipt_bytes) <= MAX_PLAN, 'CONTROL_PLAN_JOURNAL_OR_RECEIPT_EXCEEDS_LIMIT')
    allocated = lambda size: ((size + allocation_unit - 1) // allocation_unit) * allocation_unit
    growth = (allocated(plan_bytes) if include_plan else 0) + allocated(journal_bytes) + allocated(receipt_bytes) + CONTROL_METADATA_BYTES
    return {'planBytes': plan_bytes, 'journalBytes': journal_bytes, 'receiptBytes': receipt_bytes,
            'allocationUnitBytes': allocation_unit, 'remainingGrowthBytes': growth,
            'reserveBytes': CONTROL_DISK_RESERVE, 'requiredBytes': CONTROL_DISK_RESERVE + growth}


def admit_control_growth(root, plan, *, include_plan):
    current = os.statvfs(root)
    budget = control_growth_budget(plan, include_plan=include_plan, allocation_unit=max(4096, current.f_frsize))
    available = current.f_bavail * current.f_frsize
    require(available >= budget['requiredBytes'], 'CONTROL_GROWTH_WOULD_EXHAUST_DISK_RESERVE')
    return {**budget, 'availableBytes': available}


def apply_plan(root, request, plan, verifier):
    root = owned(root, directory=True)
    require(sys.platform == 'linux', 'APPLY_REQUIRES_ADMITTED_LINUX_ECS')
    control_budget = admit_control_growth(root, plan, include_plan=False)
    with cleanup_lock(root), ExitStack() as locks:
        tags = [candidate['release'] for candidate in plan['candidates']]
        require(len(tags) == len(set(tags)) and all(TAG.fullmatch(tag) for tag in tags), 'PLAN_CANDIDATES_INVALID')
        for tag in sorted(tags): locks.enter_context(attempt_lock(root, tag))
        fresh = build_plan(root, request, verifier, docker_snapshot(), held_releases=tags)
        require(fresh == plan, 'PLAN_OR_ORIGINAL_EVIDENCE_CHANGED_NO_DELETION')
        control_budget = admit_control_growth(root, plan, include_plan=False)
        before = os.statvfs(root); deleted = []; failure = None
        journal_file = root / 'inbox' / plan['currentRelease'] / 'build-cleanup-journal.jsonl'
        owned(journal_file.parent, directory=True)
        journal_fd = os.open(journal_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        journal_bytes = 0

        def journal(event):
            nonlocal journal_bytes
            data = canonical(event) + b'\n'
            failed = event.get('phase') == 'FAILED'
            limit = control_budget['journalBytes'] if failed else control_budget['journalBytes'] - 4096
            require(not failed or len(data) <= 4096, 'CLEANUP_FAILURE_RECORD_EXCEEDS_RESERVE')
            require(journal_bytes + len(data) <= limit, 'CLEANUP_JOURNAL_BOUND_EXCEEDED')
            view = memoryview(data)
            while view:
                require(journal_bytes + len(view) <= limit, 'CLEANUP_JOURNAL_BOUND_EXCEEDED')
                count = os.write(journal_fd, view); require(count > 0, 'CLEANUP_JOURNAL_WRITE_FAILED')
                journal_bytes += count; view = view[count:]
            os.fsync(journal_fd)

        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stage, active_release = 'START_JOURNAL', None
        try:
            journal({'phase': 'STARTED', 'planSha256': sha(canonical(plan)), 'identity': plan['identity']})
            for candidate in plan['candidates']:
                active_release = candidate['release']; stage = 'EVIDENCE_BINDING'
                custody = next(item for item in request['candidates'] if item['release'] == candidate['release'])
                binding = evidence_binding(root, custody, request['identity'], verifier)
                stage = 'QUIESCENCE'
                quiescent(binding, candidate['release'], docker_snapshot())
                for target in candidate['targets']:
                    stage = 'TARGET_INVENTORY'
                    require(tree_inventory(root / target['path']) == {key: target[key] for key in
                        ('files', 'bytes', 'allocatedBytes', 'rootMetadata', 'inventorySha256', 'entries')},
                        'TARGET_INVENTORY_CHANGED_NO_DELETION')
                    stage = 'DELETE_START_JOURNAL'
                    journal({'phase': 'DELETE_STARTED', 'path': target['path'], 'inventorySha256': target['inventorySha256']})
                    stage = 'DELETE_TARGET'
                    remove_target(root_fd, target)
                    deleted.append(deleted_projection(target))
                    stage = 'DELETE_FINISH_JOURNAL'
                    journal({'phase': 'DELETE_FINISHED', **deleted[-1]})
            stage = 'FINISH_JOURNAL'
            journal({'phase': 'FINISHED', 'deletedTargets': len(deleted)})
        except (OSError, ValueError) as error:
            failure = 'ValueError' if isinstance(error, ValueError) else 'OSError'
            journal({'phase': 'FAILED', 'errorType': failure, 'deletedTargets': len(deleted),
                     'stage': stage, 'release': active_release, 'guardCode': failure_guard_code(error)})
        finally:
            os.close(root_fd); os.close(journal_fd)
        after = os.statvfs(root)
        result = cleanup_receipt(plan, deleted, before.f_bavail * before.f_frsize, after.f_bavail * after.f_frsize,
                                 digest(journal_file), failure, datetime.now(timezone.utc).isoformat())
        require(len(canonical(result)) + 1 <= control_budget['receiptBytes'], 'CLEANUP_RECEIPT_EXCEEDS_ADMITTED_BOUND')
        return result


def fixed_helper(args, verifier=None, *, executor=None, verifier_path=None):
    """Authenticate both recipes before importing any deployed helper module."""
    root = Path(args.root); inbox = root / 'inbox' / args.current_tag
    archive = owned_chain(Path(args.source_archive), root, maximum=128 * 1024 ** 2)
    require(archive.parent == inbox and archive.name in ('source.tar.gz', 'cleanup-source.tar.gz')
            and digest(archive) == args.source_sha256, 'CLEANUP_FIXED_SOURCE_NOT_BOUND')
    executor = Path(executor) if executor else Path(__file__).absolute()
    verifier_path = Path(verifier_path) if verifier_path else executor.with_name('verify-remote.py')
    wanted = {'script/jenkins/cleanup-ecs-builds.py': executor,
              'script/jenkins/verify-remote.py': verifier_path}
    for name, path in wanted.items():
        require(path == inbox / Path(name).name, 'CLEANUP_HELPER_OUTSIDE_CURRENT_INBOX')
        owned_chain(path, root, maximum=1024 ** 2)
    seen = set()

    class BoundedReader:
        def __init__(self, original): self.original, self.total = original, 0
        def read(self, size=-1):
            remaining = 512 * 1024 ** 2 - self.total
            raw = self.original.read(remaining + 1 if size < 0 else min(size, remaining + 1))
            self.total += len(raw)
            require(self.total <= 512 * 1024 ** 2, 'CLEANUP_FIXED_SOURCE_EXPANSION_EXCEEDED')
            return raw

    with gzip.open(archive, 'rb') as expanded, tarfile.open(fileobj=BoundedReader(expanded), mode='r|') as source:
        for entry in source:
            if entry.name in wanted:
                require(entry.isfile() and 0 < entry.size <= 1024 ** 2 and entry.name not in seen, 'CLEANUP_HELPER_ARCHIVE_ENTRY_INVALID')
                require(sha(source.extractfile(entry).read()) == digest(wanted[entry.name]), 'CLEANUP_HELPER_DIFFERS_FROM_PINNED_SOURCE')
                seen.add(entry.name)
        require(source.pax_headers.get('comment') == args.commit and seen == set(wanted), 'CLEANUP_HELPERS_NOT_IN_FIXED_COMMIT')


def admitted_plan(path, expected_path, expected_sha, tag, identity):
    require(SHA.fullmatch(expected_sha or ''), 'PLAN_SHA_REQUIRED')
    file = owned(Path(path))
    require(file == expected_path and digest(file) == expected_sha, 'PLAN_SHA_REQUIRED')
    plan = read_json(file); request = plan['request']
    require(plan['currentRelease'] == tag and plan['identity'] == identity
            and plan['requestSha256'] == sha(canonical(request)), 'PLAN_BELONGS_TO_ANOTHER_BUILD_OR_ECS')
    return plan, request


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['inspect-process']:
        parser = argparse.ArgumentParser(description='Read only one denied Linux process metadata namespace.')
        parser.add_argument('--checkout', required=True)
        parser.add_argument('--pid', required=True, type=int)
        parser.add_argument('--uid', required=True, type=int)
        parser.add_argument('--nonce', required=True)
        args = parser.parse_args(argv[1:])
        result = single_process_metadata(Path(args.checkout), args.pid, args.uid, args.nonce)
        print(json.dumps(result, sort_keys=True)); return
    require(not (sys.platform == 'linux' and os.geteuid() == 0), 'ROOT_PERMITS_ONLY_PROCESS_METADATA_MODE')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('custody', 'plan', 'apply'))
    parser.add_argument('--retained-directory'); parser.add_argument('--output', required=True)
    parser.add_argument('--root'); parser.add_argument('--current-tag'); parser.add_argument('--commit')
    parser.add_argument('--instance-id'); parser.add_argument('--machine-id')
    parser.add_argument('--protected-release', action='append', default=[])
    parser.add_argument('--source-archive'); parser.add_argument('--source-sha256'); parser.add_argument('--request')
    parser.add_argument('--request-sha256'); parser.add_argument('--plan'); parser.add_argument('--plan-sha256')
    args = parser.parse_args(argv)
    if args.phase == 'custody':
        verifier = verifier_module(Path(__file__).with_name('verify-remote.py'))
        result = local_custody(args.retained_directory, verifier)
    else:
        require(TAG.fullmatch(args.current_tag or '') and COMMIT.fullmatch(args.commit or '')
                and args.current_tag.endswith('-' + args.commit[:12]) and SHA.fullmatch(args.source_sha256 or ''), 'CURRENT_FIXED_SOURCE_INVALID')
        root = owned(Path(args.root), directory=True)
        require(len(root.parts) > 2 and root.parts[1] in ('home', 'srv', 'opt'), 'RELEASE_ROOT_OUTSIDE_ADMITTED_ECS_BASE')
        require(re.fullmatch(r'i-[a-z0-9]+', args.instance_id or '') and re.fullmatch(r'[a-f0-9]{32}', args.machine_id or ''), 'ADMITTED_ECS_IDENTITY_REQUIRED')
        fixed_helper(args)
        verifier = verifier_module(Path(__file__).with_name('verify-remote.py'))
        identity = verifier.ecs_identity(args.instance_id, args.machine_id)
        expected_output = root / 'inbox' / args.current_tag / ('build-cleanup-plan.json' if args.phase == 'plan' else 'build-cleanup-receipt.json')
        require(Path(args.output) == expected_output, 'CLEANUP_OUTPUT_OUTSIDE_CURRENT_INBOX')
        if args.phase == 'plan':
            if args.request:
                request_file = owned(Path(args.request)); require(digest(request_file) == args.request_sha256, 'CLEANUP_REQUEST_SHA_DIFFERS')
                require(request_file == root / 'inbox' / args.current_tag / 'build-cleanup-request.json', 'CLEANUP_REQUEST_OUTSIDE_CURRENT_INBOX')
                request = read_json(request_file)
            else:
                request = discover_request(root, args.current_tag, identity, args.protected_release)
            require(request['currentRelease'] == args.current_tag and request['identity'] == identity, 'REQUEST_BELONGS_TO_ANOTHER_BUILD_OR_ECS')
            result = build_plan(root, request, verifier, docker_snapshot())
            control_budget = admit_control_growth(root, result, include_plan=True)
        else:
            plan, request = admitted_plan(args.plan, expected_output.with_name('build-cleanup-plan.json'),
                                         args.plan_sha256, args.current_tag, identity)
            result = apply_plan(root, request, plan, verifier)
            control_budget = control_growth_budget(plan, include_plan=False)
    byte_limit = (control_budget['planBytes'] if args.phase == 'plan' else control_budget['receiptBytes']) if args.phase != 'custody' else MAX_PLAN
    write_json(Path(args.output).absolute(), result, byte_limit=byte_limit)
    summary = {key: result[key] for key in ('kind', 'status', 'currentRelease', 'candidateBytes', 'candidateAllocatedBytes') if key in result}
    if args.phase != 'custody': summary['controlBudget'] = control_budget
    print(json.dumps(summary))
    if result.get('status') == 'PARTIAL_FAILURE': raise SystemExit(2)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, RuntimeError, TypeError) as error:
        print(json.dumps({'status': 'REFUSED', 'errorType': type(error).__name__, **failure_details(error)}), file=sys.stderr)
        raise SystemExit(2)
