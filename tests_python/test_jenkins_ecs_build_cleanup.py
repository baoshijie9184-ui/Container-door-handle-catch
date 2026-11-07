"""ECS-only filesystem contracts for reclaiming terminal build outputs.

All targets are synthetic children of pytest's own namespace. No Docker daemon,
cloud API, database, application, or production directory is used by these cases.
"""
import copy
import fcntl
import gzip
import importlib.util
import io
import json
import os
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
    assert json.loads(journal.read_text().splitlines()[-1])['phase'] == 'FAILED'


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
