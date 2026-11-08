"""ECS-only filesystem contracts for reclaiming terminal build outputs.

All targets are synthetic children of pytest's own namespace. No Docker daemon,
cloud API, database, application, or production directory is used by these cases.
"""
import ast
import copy
import fcntl
import gzip
import importlib.util
import io
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'script/jenkins' / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


cleanup = load('ecs_old_build_cleanup_contract', 'cleanup-ecs-builds.py')
remote = load('ecs_old_build_original_evidence_contract', 'verify-remote.py')
IDENTITY = {'instanceId': 'i-fixture123', 'machineId': 'd' * 32, 'executionLocation': 'ECS'}
OLD = 'ci-70-' + 'a' * 12
CURRENT = 'ci-72-' + 'c' * 12
MODULE = 'doorhandle-module-fixture'


def put(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(raw)
    path.chmod(0o600)
    return path


def put_json(path, value):
    return put(path, cleanup.canonical(value))


def package(path, files, commit):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tarfile.open(path, 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': commit}) as archive:
        for name, raw in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(raw)
            archive.addfile(entry, io.BytesIO(raw))
    path.chmod(0o600)


def preserved_bytes(state):
    return {str(path.relative_to(state.root)): path.read_bytes() for path in state.keep}


def seal(state):
    """Create a detached original-evidence tar from every exact report byte."""
    catalog = []
    for name in sorted(state.reports):
        path = state.checkout / ('driver.log' if name == 'driver.log' else 'work/ci-evidence/' + name[8:])
        catalog.append({'path': name, 'bytes': path.stat().st_size, 'sha256': cleanup.digest(path)})
    state.record['reportFiles'] = catalog
    state.record['toolRuntime'] = {'manifestSha256': cleanup.digest(state.manifest),
        'cleanupStatus': 'STOPPED', 'evidenceSha256': cleanup.digest(state.evidence / 'tool-runtime.json')}
    receipt = put_json(state.attempt / 'verification-receipt.json', state.record)
    members = {'verification-receipt.json': receipt.read_bytes()}
    members.update({name: (state.checkout / ('driver.log' if name == 'driver.log' else
        'work/ci-evidence/' + name[8:])).read_bytes() for name in state.reports})
    package(state.archive, members, 'a' * 40)
    custody = {'schema': 1, 'kind': 'doorhandle-retained-ecs-evidence', 'status': 'VERIFY_RETAINED_ECS_BYTES',
        'release': OLD, 'commit': 'a' * 40, 'sourceSha256': state.record['sourceSha256'], 'identity': IDENTITY,
        'verificationReceiptSha256': cleanup.digest(receipt),
        'reportCatalogSha256': cleanup.sha(cleanup.canonical(catalog)), 'reportFiles': len(catalog),
        'reportBytes': sum(row['bytes'] for row in catalog), 'originalEvidenceArchive': None}
    state.request = {'schema': 1, 'kind': 'doorhandle-old-build-cleanup-request', 'currentRelease': CURRENT,
        'identity': copy.deepcopy(IDENTITY), 'protectedReleases': [CURRENT], 'candidates': [custody]}


@pytest.fixture
def state(tmp_path, monkeypatch):
    root = tmp_path / 'owned-ci-fixture'
    root.mkdir(mode=0o700)
    attempt = root / 'verification' / OLD
    checkout = attempt / 'checkout'
    evidence = checkout / 'work/ci-evidence'
    inbox = root / 'inbox' / OLD
    (root / 'inbox' / CURRENT).mkdir(parents=True, mode=0o700)
    evidence.mkdir(parents=True, mode=0o700)
    inbox.mkdir(parents=True, mode=0o700)
    pom = (b'<project><version>1.0.0</version><modules><module>' + MODULE.encode() +
        b'</module></modules><profiles><profile><activation><property><name>doorhandle.isolated-verification'
        b'</name></property></activation><build><directory>${doorhandle.verification-root}/${project.artifactId}'
        b'</directory></build></profile></profiles></project>')
    source = inbox / 'source.tar.gz'
    package(source, {'pom.xml': pom, MODULE + '/pom.xml':
        b'<project><artifactId>' + MODULE.encode() + b'</artifactId></project>'}, 'a' * 40)
    manifest = put_json(inbox / 'tool-runtime/manifest.json', {'schema': 1, 'kind': 'doorhandle-ecs-tool-runtime',
        'directory': str(inbox / 'tool-runtime'), 'release': OLD, 'commit': 'a' * 40,
        'sourceSha256': cleanup.digest(source), 'identity': IDENTITY, 'uid': os.getuid(),
        'checkout': str(checkout), 'token': 'b' * 24})
    put_json(attempt / '.verification-claimed/claim.json', {'schema': 1, 'kind': 'doorhandle-ci-claim',
        'release': OLD, 'attempt': 'e' * 32, 'commit': 'a' * 40, 'sourceSha256': cleanup.digest(source),
        'identity': IDENTITY, 'scope': 'source'})
    inner = {'scopeKind': 'source', 'status': 'FAILED', 'finishedAt': '2026-11-07T00:00:00+00:00',
        'identity': IDENTITY, 'javaSuites': [{'id': 'suite-001'}],
        'commands': [{'label': 'java-suite-001', 'exitCode': 1, 'finishedAt': '2026-11-07T00:00:00+00:00'}]}
    put_json(evidence / 'receipt.json', inner)
    put_json(evidence / 'tool-runtime.json', {'kind': 'doorhandle-ecs-tool-evidence', 'release': OLD,
        'commit': 'a' * 40, 'sourceSha256': cleanup.digest(source), 'manifestSha256': cleanup.digest(manifest),
        'cleanup': {'status': 'STOPPED',
        'remaining': [], 'release': OLD, 'manifestSha256': cleanup.digest(manifest)}})
    report_name = 'reports/java/' + MODULE + '/surefire-reports/TEST-example.ExampleTest.xml'
    put(evidence / report_name[8:], b'<?xml version="1.0"?>\r\n<testsuite><testcase name="original"/></testsuite>\r\n')
    put(checkout / 'driver.log', b'original private driver log\r\n')
    build = evidence / 'java-suites/suite-001' / MODULE
    classes = put(build / 'classes' / 'Example.class', b'compiled-bytecode').parent
    put(build / 'test-classes' / 'ExampleTest.class', b'compiled-test-bytecode')
    keep = [source, manifest, evidence / report_name[8:], evidence / 'receipt.json',
        evidence / 'tool-runtime.json', checkout / 'driver.log',
        put(build / (MODULE + '-1.0.0.jar'), b'published-jar-bytes'),
        put(build / 'surefire-reports/TEST-example.ExampleTest.xml', b'original raw XML beside compiled output'),
        put(checkout / 'work/ecs-maven-repository/dependency.jar', b'old private dependency cache'),
        put(root / 'caches/maven-dependencies/shared.jar', b'shared dependency cache'),
        put(checkout / 'work/source.sql', b'original SQL snapshot'),
        put(checkout / 'work/legacy-source-snapshot/originals.tar', b'legacy data archive'),
        put(checkout / 'README.md', b'fixed checkout source')]
    record = {'schema': 1, 'kind': 'doorhandle-ecs-ci', 'release': OLD, 'attempt': 'e' * 32,
        'commit': 'a' * 40, 'sourceSha256': cleanup.digest(source), 'scope': 'source',
        'identity': IDENTITY, 'status': 'FAILED', 'lifecycle': 'managed-outside-jenkins',
        'finishedAt': '2026-11-07T00:00:00+00:00'}
    value = SimpleNamespace(root=root, attempt=attempt, checkout=checkout, evidence=evidence, inbox=inbox,
        manifest=manifest, record=record, archive=inbox / 'verification-evidence.tar.gz', classes=classes,
        reports=['driver.log', 'reports/receipt.json', 'reports/tool-runtime.json', report_name], keep=keep)
    seal(value)
    value.keep.extend([value.archive, value.attempt / 'verification-receipt.json'])
    monkeypatch.setattr(cleanup, 'docker_snapshot', lambda: [])
    return value


def plan(state):
    return cleanup.build_plan(state.root, state.request, remote, [])


def skipped(state, reason):
    value = plan(state)
    assert value['candidates'] == []
    assert reason in value['skipped'][0]['reason']
    assert (state.classes / 'Example.class').read_bytes() == b'compiled-bytecode'


def add_dependencies(state, *, proven=True):
    target = put(state.checkout / 'frontend/node_modules/pkg/index.js', b'reproducible package').parent.parent
    if proven:
        inner = cleanup.read_json(state.evidence / 'receipt.json')
        inner['commands'].append({'label': 'frontend-install', 'exitCode': 0,
                                  'finishedAt': '2026-11-07T00:00:00+00:00'})
        put_json(state.evidence / 'receipt.json', inner)
        put(state.evidence / 'frontend-install.log', b'original npm install log')
        state.reports.append('reports/frontend-install.log')
        seal(state)
    return target


def add_npm_cache(state, damage=None):
    raw = (ROOT / 'script/jenkins/ecs-tool-runtime.py').read_bytes()
    archived = raw
    if damage == 'changed-routing':
        archived = raw.replace(b"npm_config_cache=str(home / 'npm-cache')", b"npm_config_cache=str(home / 'unreviewed-cache')")
        assert archived != raw
    elif damage == 'duplicate-routing':
        archived += b'\ndef command(value, tool, arguments, cwd, environment):\n    pass\n'
    with tarfile.open(state.inbox / 'source.tar.gz', 'r:gz') as source:
        files = {entry.name: source.extractfile(entry).read() for entry in source}
    if damage != 'missing-source':
        files['script/jenkins/ecs-tool-runtime.py'] = archived
    package(state.inbox / 'source.tar.gz', files, 'a' * 40)
    source_sha = cleanup.digest(state.inbox / 'source.tar.gz')
    manifest = cleanup.read_json(state.manifest)
    manifest.update(sourceSha256=source_sha, files={'executor.py': cleanup.sha(archived)})
    if damage == 'manifest-binding': manifest['files']['executor.py'] = '0' * 64
    put_json(state.manifest, manifest)
    executor = put(state.inbox / 'tool-runtime/executor.py', archived)
    if damage == 'registered-bytes': put(executor, archived + b'\n# changed registered bytes\n')
    if damage == 'registered-missing': executor.unlink()
    claim_path = state.attempt / '.verification-claimed/claim.json'
    claim = cleanup.read_json(claim_path); claim['sourceSha256'] = source_sha; put_json(claim_path, claim)
    inner = cleanup.read_json(state.evidence / 'receipt.json')
    if damage != 'install-provenance':
        inner['commands'].append({'label': 'frontend-install', 'exitCode': 1, 'finishedAt': '2026-11-07T00:00:00+00:00'})
        put(state.evidence / 'frontend-install.log', b'original terminal install log')
        state.reports.append('reports/frontend-install.log')
    put_json(state.evidence / 'receipt.json', inner)
    tools = cleanup.read_json(state.evidence / 'tool-runtime.json')
    tools.update(sourceSha256=source_sha, manifestSha256=cleanup.digest(state.manifest))
    tools['cleanup']['manifestSha256'] = cleanup.digest(state.manifest)
    tools['commands'] = [{'tool': 'npm', 'containerId': 'f' * 64, 'status': 'FAILED_OR_UNKNOWN',
        'argumentsSha256': cleanup.sha(json.dumps(cleanup.NPM_INSTALL_ARGUMENTS, ensure_ascii=True).encode()),
        'cleanup': {'containerId': 'f' * 64, 'pid': 0, 'removed': True}}]
    if damage == 'tool-arguments': tools['commands'][0]['argumentsSha256'] = '0' * 64
    put_json(state.evidence / 'tool-runtime.json', tools)
    state.record['sourceSha256'] = source_sha
    seal(state)
    cache = put(state.checkout / cleanup.NPM_CACHE_SUFFIX / 'content-v2/object', b'regenerable package content').parents[1]
    state.keep.extend([
        put(state.checkout / 'work/tool-home/npm-cache/_logs/original-debug.log', b'keep original cache diagnostics'),
        put(state.checkout / 'work/tool-home/mem0/history.db', b'protected memory bytes'),
        put(state.checkout / 'work/tool-home/tmp/retained.bin', b'outside the closed cache suffix'),
        put(state.checkout / 'frontend/home/npm-cache/_cacache/object', b'unproven alternate home cache'),
    ])
    return cache


def test_reviewed_npm_routing_fingerprints_still_match_the_fixed_executor_source():
    tree = ast.parse((ROOT / 'script/jenkins/ecs-tool-runtime.py').read_bytes())
    actual = {node.name: cleanup.routing_ast_sha(node) for node in tree.body
              if isinstance(node, ast.FunctionDef) and node.name in cleanup.NPM_ROUTING_AST}
    assert actual == cleanup.NPM_ROUTING_AST


@pytest.mark.parametrize('generic', [False, True])
def test_routing_fingerprint_only_normalizes_an_empty_cross_version_type_parameters_field(generic):
    node = ast.parse('def sample(value):\n    return value\n').body[0]
    expected = cleanup.routing_ast_sha(copy.deepcopy(node))
    if 'type_params' not in node._fields:
        node._fields += ('type_params',)
    node.type_params = [ast.Name(id='T', ctx=ast.Load())] if generic else []
    assert cleanup.routing_ast_sha(node) == (None if generic else expected)


def test_exact_proven_npm_content_cache_is_removed_from_a_terminal_failed_build(state):
    cache = add_npm_cache(state)
    before = preserved_bytes(state)
    value = plan(state)
    candidate = value['candidates'][0]
    assert candidate['npmCache']['status'] == 'PROVEN'
    targets = [row for row in candidate['targets'] if row['kind'] == 'NPM_CACHE']
    assert len(targets) == 1 and targets[0]['path'] == str(cache.relative_to(state.root))
    result = cleanup.apply_plan(state.root, state.request, value, remote)
    assert result['status'] == 'REMOVED' and not cache.exists()
    assert any(row['kind'] == 'NPM_CACHE' for row in result['deleted'])
    assert preserved_bytes(state) == before


@pytest.mark.parametrize('damage,reason', [
    ('missing-source', 'NPM_EXECUTOR_SOURCE_MISSING'),
    ('changed-routing', 'NPM_ROUTING_NOT_REVIEWED'),
    ('duplicate-routing', 'NPM_ROUTING_NOT_REVIEWED'),
    ('manifest-binding', 'NPM_EXECUTOR_BINDING_MISSING_OR_CHANGED'),
    ('registered-bytes', 'NPM_REGISTERED_EXECUTOR_CHANGED'),
    ('registered-missing', 'NPM_REGISTERED_EXECUTOR_UNAVAILABLE'),
    ('install-provenance', 'NPM_INSTALL_PROVENANCE_MISSING'),
    ('tool-arguments', 'NPM_TOOL_COMMAND_PROVENANCE_MISSING'),
])
def test_unproven_or_changed_npm_cache_is_explicitly_skipped_without_broadening_old_targets(state, damage, reason):
    cache = add_npm_cache(state, damage)
    before = preserved_bytes(state)
    value = plan(state)
    assert value['candidates'][0]['npmCache'] == {'status': 'SKIPPED', 'reason': reason}
    assert all(row['kind'] != 'NPM_CACHE' for row in value['candidates'][0]['targets'])
    result = cleanup.apply_plan(state.root, state.request, value, remote)
    assert result['status'] == 'REMOVED' and cache.is_dir()
    assert (cache / 'content-v2/object').read_bytes() == b'regenerable package content'
    assert preserved_bytes(state) == before


@pytest.mark.parametrize('suffix', ['work/tool-home', 'work/tool-home/npm-cache',
    'work/tool-home/npm-cache/_logs', 'work/tool-home/mem0', 'work/ecs-maven-repository',
    'frontend/home/npm-cache/_cacache', 'work/tool-home/npm-cache/_cacache/../_logs'])
def test_npm_cache_delete_api_rejects_any_parent_alternate_home_or_noncontent_cache(state, suffix):
    fd = os.open(state.root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(ValueError, match='OUTSIDE_COMPILED_ALLOWLIST'):
            cleanup.remove_target(fd, {'kind': 'NPM_CACHE', 'path': 'verification/' + OLD + '/checkout/' + suffix})
    finally:
        os.close(fd)
    assert state.classes.exists()


@pytest.mark.parametrize('damage', ['symlink', 'hardlink'])
def test_even_proven_npm_cache_keeps_original_tree_link_and_inode_guards(state, damage):
    cache = add_npm_cache(state)
    if damage == 'symlink':
        (cache / 'redirect').symlink_to(state.keep[2])
        reason = 'TREE_OWNER_TYPE_LINK_OR_DEVICE_CHANGED'
    else:
        os.link(cache / 'content-v2/object', state.root / 'outside-cache-alias')
        reason = 'TREE_FILE_HARDLINK_NOT_ALLOWED'
    skipped(state, reason)
    assert cache.is_dir()


def test_plan_is_read_only_and_only_names_compile_and_proven_node_dependencies(state):
    dependencies = add_dependencies(state)
    before = preserved_bytes(state)
    result = plan(state)
    assert result['skipped'] == []
    assert {item['kind'] for item in result['candidates'][0]['targets']} == {'COMPILED_DIRECTORY', 'NODE_MODULES'}
    assert result['candidateBytes'] == len(b'compiled-bytecodecompiled-test-bytecodereproducible package')
    assert not (state.attempt / '.build-cleanup.lock').exists()
    assert dependencies.is_dir() and state.classes.is_dir()
    assert preserved_bytes(state) == before


def test_apply_reclaims_exact_targets_and_keeps_original_reports_data_jars_and_caches(state):
    dependencies = add_dependencies(state)
    before = preserved_bytes(state)
    value = plan(state)
    result = cleanup.apply_plan(state.root, state.request, value, remote)
    assert result['status'] == 'REMOVED'
    assert len(result['deleted']) == 3
    assert not state.classes.exists() and not dependencies.exists()
    assert preserved_bytes(state) == before
    assert result['businessDataDeleted'] is False and result['publishedArtifactsPreserved'] is True
    journal = state.root / 'inbox' / CURRENT / 'build-cleanup-journal.jsonl'
    assert cleanup.digest(journal) == result['journalSha256']
    assert json.loads(journal.read_text().splitlines()[-1])['phase'] == 'FINISHED'


@pytest.mark.parametrize('which', ['archive', 'original-report', 'claim', 'source'])
def test_drift_in_independently_retained_evidence_or_owner_source_refuses_cleanup(state, which):
    path = {'archive': state.archive, 'original-report': state.keep[2],
            'claim': state.attempt / '.verification-claimed/claim.json', 'source': state.inbox / 'source.tar.gz'}[which]
    path.write_bytes(path.read_bytes() + b'changed')
    assert not plan(state)['candidates']
    assert state.classes.exists()


@pytest.mark.parametrize('damage', ['suffix', 'crc', 'footer-truncated', 'buffered-tail', 'gzip-tail', 'padding-budget'])
def test_bounded_original_archive_rejects_transport_tampering_and_hidden_tail(state, damage):
    raw = state.archive.read_bytes()
    expanded = gzip.decompress(raw)
    limit = remote.MAX_EVIDENCE_BYTES
    if damage == 'suffix':
        raw += b'changed'
    elif damage == 'crc':
        raw = raw[:-8] + bytes([raw[-8] ^ 1]) + raw[-7:]
    elif damage == 'footer-truncated':
        raw = raw[:-4]
    elif damage == 'buffered-tail':
        # This fits in tarfile's first read-ahead buffer, after the tar EOF.
        raw = gzip.compress(expanded[:-8] + b'changed!')
    elif damage == 'gzip-tail':
        raw += gzip.compress(b'changed')
    else:
        limit = len(expanded)
        raw = gzip.compress(expanded + b'\0' * 512)
    state.archive.write_bytes(raw)
    with pytest.raises((remote.VerificationError, gzip.BadGzipFile, EOFError)):
        with remote.bounded_tar(state.archive, limit) as source:
            list(source)
    assert state.classes.exists()


def test_bounded_original_archive_accepts_zero_padding_at_exact_expansion_bound(state):
    limit = len(gzip.decompress(state.archive.read_bytes()))
    with remote.bounded_tar(state.archive, limit) as source:
        names = [entry.name for entry in source]
    assert set(names) == {'verification-receipt.json', *state.reports}


def test_bounded_original_archive_does_not_mask_the_consumers_validation_error(state):
    failure = ValueError('original validation failure')
    with pytest.raises(ValueError) as caught:
        with remote.bounded_tar(state.archive, remote.MAX_EVIDENCE_BYTES):
            raise failure
    assert caught.value is failure


@pytest.mark.parametrize('mode', ['current', 'future', 'protected', 'release-artifact'])
def test_current_future_protected_and_published_attempts_are_never_reclaimed(state, mode):
    if mode == 'current': state.request['currentRelease'] = OLD; state.request['protectedReleases'] = [OLD]
    elif mode == 'future':
        state.request['currentRelease'] = 'ci-69-' + 'f' * 12
        state.request['protectedReleases'] = [state.request['currentRelease']]
    elif mode == 'protected': state.request['protectedReleases'].append(OLD)
    else: (state.root / 'releases' / OLD).mkdir(parents=True, mode=0o700)
    assert not plan(state)['candidates']
    assert state.classes.exists()


@pytest.mark.parametrize('kind', ['symlink-file', 'symlink-parent', 'hardlink', 'foreign-owner', 'foreign-writable'])
def test_links_and_foreign_ownership_do_not_enter_a_deletion_plan(state, monkeypatch, kind):
    if kind == 'symlink-file': (state.classes / 'external').symlink_to(state.keep[2])
    elif kind == 'symlink-parent':
        folder = state.classes.parent
        moved = folder.with_name('moved')
        folder.rename(moved); folder.symlink_to(moved, target_is_directory=True)
    elif kind == 'hardlink': os.link(state.keep[2], state.classes / 'linked-original.xml')
    elif kind == 'foreign-writable': (state.classes / 'Example.class').chmod(0o666)
    else:
        original = Path.lstat
        def changed(path):
            info = original(path)
            if path == state.classes / 'Example.class':
                return SimpleNamespace(st_uid=os.getuid() + 1, st_dev=info.st_dev, st_mode=info.st_mode)
            return info
        monkeypatch.setattr(Path, 'lstat', changed)
    assert not plan(state)['candidates']
    assert state.keep[2].read_bytes().startswith(b'<?xml')


def test_node_dependencies_without_an_original_install_log_and_command_are_refused(state):
    add_dependencies(state, proven=False)
    skipped(state, 'NODE_DEPENDENCIES_LACK_ARCHIVED_INSTALL_PROVENANCE')


def test_npm_bin_symlinks_are_refused_without_following_their_target(state):
    dependencies = add_dependencies(state)
    (dependencies / '.bin').mkdir(mode=0o700)
    (dependencies / '.bin/tool').symlink_to(state.keep[2])
    skipped(state, 'TREE_OWNER_TYPE_LINK_OR_DEVICE_CHANGED')
    assert state.keep[2].read_bytes().startswith(b'<?xml')


@pytest.mark.parametrize('condition', ['running-command', 'tools-unknown', 'wrong-host'])
def test_unfinished_commands_unstopped_tools_and_other_hosts_are_not_terminal_evidence(state, condition):
    if condition == 'running-command':
        inner = cleanup.read_json(state.evidence / 'receipt.json')
        inner['commands'][0].pop('finishedAt'); put_json(state.evidence / 'receipt.json', inner)
    elif condition == 'tools-unknown':
        tools = cleanup.read_json(state.evidence / 'tool-runtime.json')
        tools['cleanup']['status'] = 'FAILED_OR_UNKNOWN'; put_json(state.evidence / 'tool-runtime.json', tools)
    else: state.record['identity'] = {**IDENTITY, 'machineId': 'f' * 32}
    seal(state)
    assert not plan(state)['candidates']


@pytest.mark.parametrize('container', ['owner-label', 'foreign-active-mount', 'foreign-stopped-mount'])
def test_owned_or_foreign_containers_referencing_an_old_checkout_block_cleanup(state, container):
    row = ['1' * 64, False, False, 0, None, None, []]
    if container == 'owner-label': row[4] = OLD
    else:
        row[1] = container == 'foreign-active-mount'
        row[6] = [{'Type': 'bind', 'Source': str(state.checkout)}]
    result = cleanup.build_plan(state.root, state.request, remote, [row])
    assert result['candidates'] == []
    assert state.classes.exists()


@pytest.mark.parametrize('reference', ['cwd', 'argv', 'fd', 'mmap'])
def test_live_process_cwd_argv_open_files_and_memory_maps_block_cleanup(state, tmp_path, reference):
    proc = tmp_path / 'fake-proc'
    pid = proc / str(os.getpid() + 100000)
    (pid / 'fd').mkdir(parents=True)
    (pid / 'cwd').symlink_to(state.checkout if reference == 'cwd' else tmp_path, target_is_directory=True)
    (pid / 'cmdline').write_bytes(b'python\0' + (os.fsencode(state.checkout / 'script.py') if reference == 'argv' else b'-I') + b'\0')
    if reference == 'fd': (pid / 'fd/9').symlink_to(state.classes / 'Example.class')
    (pid / 'maps').write_bytes(b'00000000-00001000 r--p 00000000 00:00 1 ' +
        os.fsencode(state.classes / 'Example.class') + b'\n' if reference == 'mmap' else b'')
    with pytest.raises(ValueError, match='REFERENCES_OLD_CHECKOUT'):
        cleanup.process_references(state.checkout, proc)


def test_an_existing_attempt_directory_lock_refuses_the_plan_without_creating_old_lock_files(state):
    fd = os.open(state.attempt, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        skipped(state, 'OLD_ATTEMPT_LOCK_HELD')
    finally: os.close(fd)
    assert not (state.attempt / '.build-cleanup.lock').exists()


def test_a_real_advisory_lock_on_a_compiled_file_refuses_reclamation(state):
    with (state.classes / 'Example.class').open('rb') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        skipped(state, 'OUTPUT_HAS_HELD_FILE_LOCK')


def test_apply_refuses_an_existing_global_cleanup_lock_before_deleting(state):
    value = plan(state)
    with cleanup.cleanup_lock(state.root):
        with pytest.raises(BlockingIOError): cleanup.apply_plan(state.root, state.request, value, remote)
    assert state.classes.exists()


@pytest.mark.parametrize('change', ['same-size-file', 'new-file', 'evidence', 'request'])
def test_apply_refuses_approval_drift_before_any_target_is_removed(state, change):
    value = plan(state)
    if change == 'same-size-file':
        file = state.classes / 'Example.class'; info = file.stat()
        file.write_bytes(b'x' * info.st_size); os.utime(file, ns=(info.st_atime_ns, info.st_mtime_ns))
    elif change == 'new-file': put(state.classes / 'new.class', b'new')
    elif change == 'evidence': state.keep[2].write_bytes(b'changed original report')
    else: state.request['protectedReleases'].append(OLD)
    with pytest.raises(ValueError, match='PLAN_OR_ORIGINAL_EVIDENCE_CHANGED'):
        cleanup.apply_plan(state.root, state.request, value, remote)
    assert state.classes.exists()


def test_apply_stops_on_late_file_drift_and_retains_failure_journal_and_all_original_evidence(state, monkeypatch):
    value = plan(state); before = preserved_bytes(state)
    original = cleanup.remove_target
    def drift(fd, target):
        put(state.root / target['path'] / 'unexpected.class', b'late writer')
        return original(fd, target)
    monkeypatch.setattr(cleanup, 'remove_target', drift)
    result = cleanup.apply_plan(state.root, state.request, value, remote)
    assert result['status'] == 'PARTIAL_FAILURE'
    assert preserved_bytes(state) == before
    journal = state.root / 'inbox' / CURRENT / 'build-cleanup-journal.jsonl'
    failure = json.loads(journal.read_text().splitlines()[-1])
    assert failure['phase'] == 'FAILED'
    assert failure['stage'] == 'DELETE_TARGET' and failure['release'] == OLD
    assert failure['guardCode'] == 'TARGET_CHANGED_AFTER_APPROVAL'


def test_late_quiescence_failure_records_only_controlled_stage_release_and_guard(state, monkeypatch):
    value = plan(state); before = preserved_bytes(state)
    original = cleanup.quiescent
    calls = []
    secret = 'MYSQL_PWD=synthetic-private-exception-payload'
    def refuse_after_fresh_plan(binding, tag, containers):
        calls.append(tag)
        if len(calls) == 2:
            raise ValueError(secret)
        return original(binding, tag, containers)
    monkeypatch.setattr(cleanup, 'quiescent', refuse_after_fresh_plan)
    result = cleanup.apply_plan(state.root, state.request, value, remote)
    assert result['status'] == 'PARTIAL_FAILURE' and result['deleted'] == []
    raw = (state.root / 'inbox' / CURRENT / 'build-cleanup-journal.jsonl').read_text()
    failure = json.loads(raw.splitlines()[-1])
    assert failure == {'phase': 'FAILED', 'errorType': 'ValueError', 'deletedTargets': 0,
        'stage': 'QUIESCENCE', 'release': OLD, 'guardCode': 'UNCLASSIFIED_VALIDATION_ERROR'}
    assert secret not in raw and secret not in json.dumps(result)
    assert preserved_bytes(state) == before and state.classes.is_dir()


def test_journal_capacity_refuses_the_next_delete_record_and_preserves_space_for_failure(state, monkeypatch):
    value = plan(state); before = preserved_bytes(state)
    started = {'phase': 'STARTED', 'planSha256': cleanup.sha(cleanup.canonical(value)), 'identity': IDENTITY}
    target = value['candidates'][0]['targets'][0]
    deleting = {'phase': 'DELETE_STARTED', 'path': target['path'], 'inventorySha256': target['inventorySha256']}
    normal_limit = len(cleanup.canonical(started)) + 1 + len(cleanup.canonical(deleting))
    monkeypatch.setattr(cleanup, 'MAX_PLAN', normal_limit + 4096)
    result = cleanup.apply_plan(state.root, state.request, value, remote)
    assert result['status'] == 'PARTIAL_FAILURE' and result['deleted'] == []
    raw = (state.root / 'inbox' / CURRENT / 'build-cleanup-journal.jsonl').read_bytes()
    entries = [json.loads(line) for line in raw.splitlines()]
    assert entries[0] == started and [row['phase'] for row in entries] == ['STARTED', 'FAILED']
    assert entries[-1]['guardCode'] == 'CLEANUP_JOURNAL_BOUND_EXCEEDED'
    assert entries[-1]['stage'] == 'DELETE_START_JOURNAL' and entries[-1]['release'] == OLD
    assert len(raw) <= cleanup.MAX_PLAN and len(cleanup.canonical(entries[-1])) + 1 <= 4096
    assert preserved_bytes(state) == before and state.classes.is_dir()


@pytest.mark.parametrize('kind,path', [
    ('OLD_MAVEN_REPOSITORY', 'verification/' + OLD + '/checkout/work/ecs-maven-repository'),
    ('PINNED_POM_JAR', 'verification/' + OLD + '/checkout/work/ci-evidence/java-suites/suite-001/' + MODULE + '/artifact.jar'),
    ('COMPILED_DIRECTORY', 'verification/' + OLD + '/checkout/work/ci-evidence/java'),
    ('NODE_MODULES', 'verification/' + OLD + '/checkout/work/database'),
])
def test_the_final_delete_api_has_no_data_report_jar_or_maven_repository_operation(state, kind, path):
    fd = os.open(state.root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(ValueError, match='OUTSIDE_COMPILED_ALLOWLIST'):
            cleanup.remove_target(fd, {'kind': kind, 'path': path})
    finally: os.close(fd)
    assert state.classes.exists()


def test_exact_plan_file_hash_and_same_build_identity_are_required(state):
    value = plan(state)
    file = put_json(state.root / 'inbox' / CURRENT / 'build-cleanup-plan.json', value)
    accepted, request = cleanup.admitted_plan(file, file, cleanup.digest(file), CURRENT, IDENTITY)
    assert accepted == value and request == state.request
    with pytest.raises(ValueError, match='PLAN_SHA_REQUIRED'):
        cleanup.admitted_plan(file, file, '0' * 64, CURRENT, IDENTITY)
    with pytest.raises(ValueError, match='ANOTHER_BUILD_OR_ECS'):
        cleanup.admitted_plan(file, file, cleanup.digest(file), CURRENT, {**IDENTITY, 'machineId': 'f' * 32})


def test_fixed_bootstrap_checks_deployed_recipes_before_importing_any_helper(state):
    inbox = state.root / 'inbox' / CURRENT
    executor = put(inbox / 'cleanup-ecs-builds.py', b'# fixed cleanup recipe\n')
    verifier = put(inbox / 'verify-remote.py', b'# fixed evidence verifier\n')
    archive = inbox / 'cleanup-source.tar.gz'
    package(archive, {'script/jenkins/cleanup-ecs-builds.py': executor.read_bytes(),
        'script/jenkins/verify-remote.py': verifier.read_bytes()}, 'c' * 40)
    args = SimpleNamespace(root=str(state.root), current_tag=CURRENT, source_archive=str(archive),
                           source_sha256=cleanup.digest(archive), commit='c' * 40)
    cleanup.fixed_helper(args, executor=executor, verifier_path=verifier)
    verifier.write_bytes(b'raise RuntimeError("untrusted code must never be imported")\n')
    with pytest.raises(ValueError, match='DIFFERS_FROM_PINNED_SOURCE'):
        cleanup.fixed_helper(args, executor=executor, verifier_path=verifier)


def test_duplicate_json_keys_cannot_redefine_a_reviewed_cleanup_plan(state):
    file = put(state.root / 'duplicate.json', b'{"identity":1,"identity":2}')
    with pytest.raises(ValueError, match='DUPLICATE_JSON_FIELD'): cleanup.read_json(file)


@pytest.fixture
def process_namespace(state, tmp_path, monkeypatch):
    """Only synthetic proc metadata; the root role is simulated, never acquired."""
    proc = tmp_path / 'synthetic-process-metadata'; pid = os.getpid() + 100000
    directory = proc / str(pid); (directory / 'fd').mkdir(parents=True)
    fields = ['S'] + ['0'] * 49; fields[19] = '123456'
    (directory / 'stat').write_bytes((str(pid) + ' (synthetic task) ' + ' '.join(fields)).encode())
    (directory / 'status').write_bytes(b'Name:\tsynthetic\nUid:\t1000\t1000\t1000\t1000\nGid:\t1000\t1000\t1000\t1000\n')
    (directory / 'cwd').symlink_to(tmp_path, target_is_directory=True)
    (directory / 'cmdline').write_bytes(b'synthetic\0--safe\0')
    (directory / 'maps').write_bytes(b'')
    (directory / 'fd/9').symlink_to('/dev/null')
    monkeypatch.setattr(cleanup.os, 'geteuid', lambda: 0)
    return SimpleNamespace(proc=proc, pid=pid, directory=directory, checkout=state.checkout, nonce='a' * 32)


def inspect_process(value):
    return cleanup.single_process_metadata(value.checkout, value.pid, 1000, value.nonce, proc=value.proc)


def test_root_probe_reads_only_metadata_and_returns_no_argv_maps_or_path_targets(process_namespace, monkeypatch):
    value = process_namespace; original = cleanup.os.open; opens = []
    def readonly(path, flags, *args, **kwargs):
        assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        opens.append((path, flags)); return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(cleanup.os, 'open', readonly)
    monkeypatch.setattr(cleanup, 'write_json', lambda *args: pytest.fail('root metadata wrote a file'))
    monkeypatch.setattr(cleanup, 'remove_target', lambda *args: pytest.fail('root metadata used deletion API'))
    result = inspect_process(value)
    assert result == cleanup.probe_result('QUIESCENT', value.checkout, value.pid, 1000, value.nonce)
    assert opens and set(result) == {'schema', 'kind', 'status', 'pid', 'uid', 'checkout', 'nonce'}
    assert not any(key in result for key in ('argv', 'maps', 'cwd', 'descriptors', 'environment'))


@pytest.mark.parametrize('reference', ['cwd', 'argv', 'fd', 'mmap'])
def test_root_probe_still_refuses_every_real_reference(process_namespace, reference):
    value = process_namespace
    if reference == 'cwd':
        (value.directory / 'cwd').unlink(); (value.directory / 'cwd').symlink_to(value.checkout, target_is_directory=True)
    elif reference == 'argv': (value.directory / 'cmdline').write_bytes(b'process\0--script=' + os.fsencode(value.checkout / 'app.py') + b'\0')
    elif reference == 'fd':
        (value.directory / 'fd/9').unlink(); (value.directory / 'fd/9').symlink_to(value.checkout / 'opened.data')
    else: (value.directory / 'maps').write_bytes(b'0-1 r--p 0 00:00 1 ' + os.fsencode(value.checkout / 'mapped.data') + b'\n')
    with pytest.raises(ValueError, match='REFERENCES_OLD_CHECKOUT'): inspect_process(value)


@pytest.mark.parametrize('change', ['uid', 'gid', 'starttime', 'pid-directory'])
def test_root_probe_refuses_changed_identity_or_reused_pid_without_following_new_process(process_namespace, monkeypatch, change):
    value = process_namespace; original = cleanup.probe_read; original_inode = value.directory.stat().st_ino
    observed = []; mutated = False
    def read(pid_fd, name, maximum):
        nonlocal mutated
        observed.append(os.fstat(pid_fd).st_ino); raw = original(pid_fd, name, maximum)
        if name == 'maps' and not mutated:
            mutated = True
            if change == 'pid-directory':
                value.directory.rename(value.proc / 'retired-process'); value.directory.mkdir()
                (value.directory / 'status').write_bytes(b'untrusted replacement must not be read')
            elif change == 'starttime':
                path = value.directory / 'stat'; path.write_bytes(path.read_bytes().replace(b'123456', b'987654'))
            else:
                path = value.directory / 'status'; old = b'Uid:' if change == 'uid' else b'Gid:'
                path.write_bytes(path.read_bytes().replace(old + b'\t1000\t1000\t1000\t1000', old + b'\t1001\t1001\t1001\t1001'))
        return raw
    monkeypatch.setattr(cleanup, 'probe_read', read)
    with pytest.raises(ValueError, match='UID_CHANGED|PID_OR_IDENTITY_REUSED'): inspect_process(value)
    assert mutated and set(observed) == {original_inode}


def test_root_probe_refuses_foreign_uid_before_reading_other_metadata(process_namespace, monkeypatch):
    value = process_namespace; (value.directory / 'status').write_bytes(b'Uid:\t1001\t1001\t1001\t1001\nGid:\t1000\t1000\t1000\t1000\n')
    monkeypatch.setattr(cleanup.os, 'readlink', lambda *a, **k: pytest.fail('foreign UID reached reference scan'))
    with pytest.raises(ValueError, match='UID_CHANGED'): inspect_process(value)


@pytest.mark.parametrize('phase', ['before-open', 'after-open'])
def test_root_probe_reports_gone_only_when_pid_namespace_is_actually_absent(process_namespace, monkeypatch, phase):
    value = process_namespace
    if phase == 'before-open': value.directory.rename(value.proc / 'exited-process')
    else:
        original = cleanup.probe_read
        def read(fd, name, maximum):
            raw = original(fd, name, maximum)
            if name == 'maps': value.directory.rename(value.proc / 'exited-process')
            return raw
        monkeypatch.setattr(cleanup, 'probe_read', read)
    assert inspect_process(value)['status'] == 'GONE'


@pytest.mark.parametrize('condition', ['missing-maps-alive', 'permission-denied', 'open-race-alive'])
def test_root_probe_never_calls_an_unknown_or_unreadable_live_pid_gone(process_namespace, monkeypatch, condition):
    value = process_namespace
    if condition == 'missing-maps-alive': (value.directory / 'maps').unlink()
    elif condition == 'permission-denied':
        original = cleanup.probe_read
        def denied(fd, name, maximum):
            if name == 'maps': raise PermissionError('synthetic root metadata unavailable')
            return original(fd, name, maximum)
        monkeypatch.setattr(cleanup, 'probe_read', denied)
    else:
        original = cleanup.os.open
        def missing(path, flags, *a, **kw):
            if path == str(value.pid) and kw.get('dir_fd') is not None: raise FileNotFoundError('PID open raced')
            return original(path, flags, *a, **kw)
        monkeypatch.setattr(cleanup.os, 'open', missing)
    with pytest.raises((ValueError, PermissionError)): inspect_process(value)
    assert value.directory.exists()


@pytest.mark.parametrize('scanner', ['privileged', 'unprivileged'])
def test_closing_one_descriptor_does_not_skip_a_live_process_memory_mapping(process_namespace, monkeypatch, scanner):
    value = process_namespace; original = cleanup.os.readlink
    (value.directory / 'maps').write_bytes(b'0-1 r--p 0 00:00 1 ' + os.fsencode(value.checkout / 'mapped.data') + b'\n')
    fd_inode = (value.directory / 'fd').stat().st_ino
    def closed(path, *a, **kw):
        matches = (kw.get('dir_fd') is not None and os.fstat(kw['dir_fd']).st_ino == fd_inode and path == '9')
        matches = matches or Path(path) == value.directory / 'fd/9'
        if matches:
            (value.directory / 'fd/9').unlink(); raise FileNotFoundError('descriptor closed')
        return original(path, *a, **kw)
    monkeypatch.setattr(cleanup.os, 'readlink', closed)
    with pytest.raises(ValueError, match='MEMORY_MAP_REFERENCES_OLD_CHECKOUT'):
        inspect_process(value) if scanner == 'privileged' else cleanup.process_references(value.checkout, value.proc)


def test_a_descriptor_replaced_during_missing_read_is_not_treated_as_closed(process_namespace, monkeypatch):
    value = process_namespace; original = cleanup.os.readlink; fd_inode = (value.directory / 'fd').stat().st_ino
    def changed(path, *a, **kw):
        if path == '9' and kw.get('dir_fd') is not None and os.fstat(kw['dir_fd']).st_ino == fd_inode:
            raise FileNotFoundError('descriptor number already reused')
        return original(path, *a, **kw)
    monkeypatch.setattr(cleanup.os, 'readlink', changed)
    with pytest.raises(ValueError, match='DESCRIPTOR_CHANGED'): inspect_process(value)


@pytest.fixture
def denied_real_process(state, monkeypatch):
    pid = os.getpid(); entry = Path('/proc') / str(pid); original_iter = Path.iterdir; original_link = os.readlink
    monkeypatch.setattr(cleanup.os, 'getpid', lambda: pid + 100000)
    monkeypatch.setattr(Path, 'iterdir', lambda path: iter([entry]) if path == Path('/proc') else original_iter(path))
    def denied(path, *a, **kw):
        if Path(path) == entry / 'cwd': raise PermissionError(13, 'synthetic non-dumpable process', str(path))
        return original_link(path, *a, **kw)
    monkeypatch.setattr(cleanup.os, 'readlink', denied)
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        result = cleanup.probe_result('QUIESCENT', state.checkout, pid, 1000, command[command.index('--nonce') + 1])
        return SimpleNamespace(returncode=0, stdout=cleanup.canonical(result), stderr=b'')
    monkeypatch.setattr(cleanup.subprocess, 'run', run)
    return SimpleNamespace(pid=pid, calls=calls, run=run, checkout=state.checkout, entry=entry)


def test_only_denied_real_proc_uses_single_pid_fixed_source_stdin_and_sanitized_sudo(denied_real_process):
    value = denied_real_process; cleanup.process_references(value.checkout)
    assert len(value.calls) == 1; command, options = value.calls[0]
    assert command[:7] == ['/usr/bin/sudo', '-n', '/usr/bin/python3', '-I', '-B', '-', 'inspect-process']
    assert command[command.index('--pid') + 1] == str(value.pid)
    assert command[command.index('--checkout') + 1] == str(value.checkout)
    assert command[command.index('--uid') + 1] == '1000'
    assert options['input'] == cleanup.LOADED_SOURCE and options['timeout'] == 20
    assert options['env'] == {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}


@pytest.mark.parametrize('field', ['uid', 'pid', 'checkout', 'nonce', 'kind', 'schema-type', 'status', 'extra', 'duplicate', 'not-json'])
def test_privileged_metadata_response_must_be_closed_typed_and_bound(denied_real_process, monkeypatch, field):
    value = denied_real_process
    def changed(command, **kwargs):
        reply = value.run(command, **kwargs); row = json.loads(reply.stdout)
        if field == 'uid': row[field] = 1001
        elif field == 'pid': row[field] += 1
        elif field == 'checkout': row[field] += '/other'
        elif field == 'nonce': row[field] = '0' * 32
        elif field == 'kind': row[field] = 'untrusted'
        elif field == 'schema-type': row['schema'] = True
        elif field == 'status': row[field] = 'REFERENCED'
        elif field == 'extra': row['argv'] = ['must not be returned']
        if field == 'duplicate': reply.stdout = b'{"schema":1,' + cleanup.canonical(row)[1:]
        elif field == 'not-json': reply.stdout = b'not-json'
        else: reply.stdout = cleanup.canonical(row)
        return reply
    monkeypatch.setattr(cleanup.subprocess, 'run', changed)
    with pytest.raises(ValueError): cleanup.process_references(value.checkout)


@pytest.mark.parametrize('failure', ['sudo-denied', 'timeout', 'stdout-bound', 'stderr-bound'])
def test_failed_or_unavailable_privileged_metadata_never_becomes_quiescent(denied_real_process, monkeypatch, failure):
    value = denied_real_process
    def changed(command, **kwargs):
        if failure == 'timeout': raise subprocess.TimeoutExpired(command, 20)
        reply = value.run(command, **kwargs)
        if failure == 'sudo-denied': reply.returncode = 1
        elif failure == 'stdout-bound': reply.stdout = b'x' * 4097
        else: reply.stderr = b'x' * 4097
        return reply
    monkeypatch.setattr(cleanup.subprocess, 'run', changed)
    with pytest.raises((ValueError, subprocess.TimeoutExpired)): cleanup.process_references(value.checkout)


@pytest.mark.parametrize('error', [OSError(5, 'unrelated IO failure'), FileNotFoundError('live task metadata disappeared'), ValueError('other validation')])
def test_non_permission_error_does_not_invoke_privileged_fallback(denied_real_process, monkeypatch, error):
    value = denied_real_process
    monkeypatch.setattr(cleanup.os, 'readlink', lambda *a, **kw: (_ for _ in ()).throw(error))
    monkeypatch.setattr(cleanup, 'privileged_process_probe', lambda *a: pytest.fail('non-permission error elevated'))
    with pytest.raises((OSError, ValueError)): cleanup.process_references(value.checkout)


def test_unproven_process_uid_does_not_request_privileged_metadata(denied_real_process, monkeypatch):
    value = denied_real_process; original = Path.stat
    def denied(path, *args, **kwargs):
        if path == value.entry: raise PermissionError('PID owner could not be established')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', denied)
    monkeypatch.setattr(cleanup, 'privileged_process_probe', lambda *a: pytest.fail('unproven UID elevated'))
    with pytest.raises(PermissionError): cleanup.process_references(value.checkout)


def test_synthetic_or_non_proc_namespace_never_invokes_sudo(process_namespace, monkeypatch):
    value = process_namespace
    monkeypatch.setattr(cleanup.os, 'readlink', lambda *a, **kw: (_ for _ in ()).throw(PermissionError('denied')))
    monkeypatch.setattr(cleanup, 'privileged_process_probe', lambda *a: pytest.fail('non-proc namespace elevated'))
    with pytest.raises(PermissionError): cleanup.process_references(value.checkout, value.proc)


@pytest.mark.parametrize('scope', ['wrong-uid', 'wrong-euid', 'non-linux'])
def test_wrong_actor_or_platform_cannot_request_sudo_probe(denied_real_process, monkeypatch, scope):
    value = denied_real_process
    if scope == 'wrong-uid': monkeypatch.setattr(cleanup.os, 'getuid', lambda: 1001)
    elif scope == 'wrong-euid': monkeypatch.setattr(cleanup.os, 'geteuid', lambda: 0)
    else: monkeypatch.setattr(cleanup.sys, 'platform', 'win32')
    with pytest.raises(ValueError, match='SCOPE_REFUSED'):
        cleanup.privileged_process_probe(value.checkout, value.pid, Path('/proc'))
    assert value.calls == []


@pytest.mark.parametrize('race', ['writable', 'hardlink', 'replacement', 'fifo'])
def test_fixed_source_fd_rechecks_admitted_shape_before_root_interpretation(denied_real_process, tmp_path, monkeypatch, race):
    value = denied_real_process; source = put(tmp_path / 'cleanup-fixed.py', cleanup.LOADED_SOURCE)
    monkeypatch.setattr(cleanup, '__file__', str(source)); original = cleanup.os.open; changed = False
    def racing(path, flags, *a, **kw):
        nonlocal changed
        if Path(path) == source and not changed:
            changed = True; assert flags & os.O_NONBLOCK
            if race == 'writable': source.chmod(0o666)
            elif race == 'hardlink': os.link(source, source.with_name('unreviewed-link'))
            elif race == 'replacement': put(source.with_name('replacement'), cleanup.LOADED_SOURCE).replace(source)
            else: source.unlink(); os.mkfifo(source, 0o600)
        return original(path, flags, *a, **kw)
    monkeypatch.setattr(cleanup.os, 'open', racing)
    with pytest.raises(ValueError, match='SOURCE_NOT_ADMITTED'):
        cleanup.privileged_process_probe(value.checkout, value.pid, Path('/proc'))
    assert changed and value.calls == []


def test_stdin_root_module_does_not_try_to_open_a_source_path(monkeypatch):
    source = cleanup.LOADED_SOURCE
    monkeypatch.setattr(Path, 'read_bytes', lambda *a: pytest.fail('stdin code tried source pathname read'))
    namespace = {'__file__': '<stdin>', '__name__': 'fixed_root_metadata_stdin_contract'}
    exec(compile(source, '<stdin>', 'exec'), namespace)
    assert namespace['LOADED_SOURCE'] is None


@pytest.mark.parametrize('phase', ['custody', 'plan', 'apply'])
def test_root_has_no_data_cleanup_or_custody_cli_mode(monkeypatch, phase):
    monkeypatch.setattr(cleanup.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(cleanup, 'write_json', lambda *a: pytest.fail('root cleanup wrote an artifact'))
    monkeypatch.setattr(cleanup, 'remove_target', lambda *a: pytest.fail('root cleanup deleted data'))
    with pytest.raises(ValueError, match='ROOT_PERMITS_ONLY_PROCESS_METADATA'): cleanup.main([phase])


def test_unprivileged_process_cannot_claim_root_probe_result(process_namespace, monkeypatch):
    value = process_namespace; monkeypatch.setattr(cleanup.os, 'geteuid', lambda: 1000)
    with pytest.raises(ValueError, match='ROOT_PROCESS_METADATA_MODE_REQUIRED'): inspect_process(value)


def test_root_cli_is_only_bound_single_pid_metadata_and_never_writes_outputs(state, monkeypatch, capsys):
    monkeypatch.setattr(cleanup.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(cleanup, 'write_json', lambda *a: pytest.fail('root metadata wrote an artifact'))
    pid = 2 ** 31 - 1; assert not (Path('/proc') / str(pid)).exists()
    cleanup.main(['inspect-process', '--checkout', str(state.checkout), '--pid', str(pid), '--uid', '1000', '--nonce', 'a' * 32])
    assert json.loads(capsys.readouterr().out) == cleanup.probe_result('GONE', state.checkout, pid, 1000, 'a' * 32)


def test_windows_local_custody_dispatch_does_not_require_linux_privilege_api(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cleanup.sys, 'platform', 'win32')
    monkeypatch.setattr(cleanup.os, 'geteuid', lambda: pytest.fail('Windows custody accessed Linux privilege API'))
    expected = {'kind': 'local-custody-contract', 'status': 'VERIFIED_LOCAL_BYTES'}; writes = []
    monkeypatch.setattr(cleanup, 'verifier_module', lambda path: object())
    monkeypatch.setattr(cleanup, 'local_custody', lambda directory, verifier: expected)
    monkeypatch.setattr(cleanup, 'write_json', lambda path, value: writes.append((path, value)))
    output = tmp_path / 'custody.json'
    cleanup.main(['custody', '--retained-directory', str(tmp_path), '--output', str(output)])
    assert writes == [(output, expected)] and json.loads(capsys.readouterr().out) == expected
