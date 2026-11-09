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
import shutil
import subprocess
import sys
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
PROCESS_REFERENCES = cleanup.process_references
remote = load('ecs_old_build_original_evidence_contract', 'verify-remote.py')
IDENTITY = {'instanceId': 'i-fixture123', 'machineId': 'd' * 32, 'executionLocation': 'ECS'}
OLD = 'ci-70-' + 'a' * 12
CURRENT = 'ci-72-' + 'c' * 12
MODULE = 'doorhandle-module-fixture'


@pytest.mark.parametrize('include_plan', [False, True])
def test_actual_control_budget_accounts_for_block_rounding_and_preserves_two_gib(state, include_plan):
    value = plan(state)
    budget = cleanup.control_growth_budget(value, include_plan=include_plan)
    assert budget['planBytes'] == len(cleanup.canonical(value)) + 1
    rounded = lambda size: ((size + 4095) // 4096) * 4096
    expected = rounded(budget['journalBytes']) + rounded(budget['receiptBytes']) + 1024 ** 2
    if include_plan: expected += rounded(budget['planBytes'])
    assert budget['remainingGrowthBytes'] == expected
    assert budget['requiredBytes'] == 2 * 1024 ** 3 + expected
    assert max(budget['planBytes'], budget['journalBytes'], budget['receiptBytes']) <= cleanup.MAX_PLAN


def test_control_budget_bounds_all_receipt_prefixes_and_the_failure_journal_tail(state):
    value = plan(state); budget = cleanup.control_growth_budget(value, include_plan=False)
    targets = [cleanup.deleted_projection(t) for c in value['candidates'] for t in c['targets']]
    events = [{'phase': 'STARTED', 'planSha256': cleanup.sha(cleanup.canonical(value)), 'identity': value['identity']}]
    for target in targets:
        events += [{'phase': 'DELETE_STARTED', 'path': target['path'], 'inventorySha256': target['inventorySha256']},
                   {'phase': 'DELETE_FINISHED', **target}]
    events += [{'phase': 'FINISHED', 'deletedTargets': len(targets)}]
    assert sum(len(cleanup.canonical(event)) + 1 for event in events) + 4096 == budget['journalBytes']
    for count in range(len(targets) + 1):
        for error in (None, 'OSError', 'ValueError'):
            result = cleanup.cleanup_receipt(value, targets[:count], 2 ** 128 - 1, 2 ** 128 - 1,
                'f' * 64, error, '9999-12-31T23:59:59.999999+00:00')
            assert len(cleanup.canonical(result)) + 1 <= budget['receiptBytes']


@pytest.mark.parametrize('phase', ['plan', 'apply'])
def test_one_byte_below_actual_remaining_control_budget_refuses_before_mutation(state, monkeypatch, phase):
    value = plan(state); before = preserved_bytes(state)
    budget = cleanup.control_growth_budget(value, include_plan=phase == 'plan')
    monkeypatch.setattr(cleanup.os, 'statvfs', lambda _p: SimpleNamespace(f_bavail=budget['requiredBytes'] - 1, f_frsize=1))
    with pytest.raises(ValueError, match='CONTROL_GROWTH_WOULD_EXHAUST_DISK_RESERVE'):
        if phase == 'plan': cleanup.admit_control_growth(state.root, value, include_plan=True)
        else: cleanup.apply_plan(state.root, state.request, value, remote)
    assert not (state.root / 'inbox' / CURRENT / 'build-cleanup-journal.jsonl').exists()
    assert preserved_bytes(state) == before and state.classes.is_dir()


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
        'release': state.record['release'], 'commit': 'a' * 40, 'sourceSha256': state.record['sourceSha256'], 'identity': IDENTITY,
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
    # General custody fixtures scan only their own synthetic process namespace.
    # Explicit process namespaces still reach the real scanner unchanged.
    proc = tmp_path / 'synthetic-proc'; proc.mkdir(mode=0o700)
    def synthetic_process_references(checkout, proc=proc):
        assert Path(checkout).is_relative_to(root), 'Synthetic custody may inspect only its own checkout'
        return PROCESS_REFERENCES(checkout, proc=proc)
    monkeypatch.setattr(cleanup, 'process_references', synthetic_process_references)
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


def add_pytest_cases(state, monkeypatch, damage=None):
    """Bind real archived routing code to synthetic, completed Python evidence."""
    runner = (ROOT / 'script/jenkins/verify-ecs.py').read_bytes()
    executor = (ROOT / 'script/jenkins/ecs-tool-runtime.py').read_bytes()
    main = next(node for node in ast.parse(runner).body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    assert cleanup.routing_ast_sha(main) in cleanup.PYTEST_RUNNER_MAIN_AST
    if damage == 'changed-runner':
        changed = runner.replace(b'def main():', b'def main():\n    unreviewed_fixture_routing = True', 1)
        assert changed != runner; runner = changed
    elif damage == 'duplicate-runner':
        runner += b'\ndef main():\n    pass\n'
    elif damage == 'async-duplicate-runner':
        runner += b'\nasync def main():\n    pass\n'
    if damage == 'changed-routing':
        changed = executor.replace(b"npm_config_cache=str(home / 'npm-cache')",
                                   b"npm_config_cache=str(home / 'unreviewed-cache')", 1)
        assert changed != executor; executor = changed
    source = state.inbox / 'source.tar.gz'
    with tarfile.open(source, 'r:gz') as archive:
        files = {entry.name: archive.extractfile(entry).read() for entry in archive}
    files['script/jenkins/ecs-tool-runtime.py'] = executor
    if damage != 'missing-source': files['script/jenkins/verify-ecs.py'] = runner
    package(source, files, 'a' * 40)
    source_sha = cleanup.digest(source)
    registered = put(state.inbox / 'tool-runtime/executor.py', executor)
    runner_file = put(state.checkout / 'script/jenkins/verify-ecs.py', runner)
    if damage == 'runner-binding': put(runner_file, runner + b'\n# different retained runner bytes\n')
    manifest = cleanup.read_json(state.manifest)
    manifest.update(sourceSha256=source_sha, images={'python': 'sha256:' + '9' * 64},
                    files={'executor.py': cleanup.sha(executor)})
    if damage == 'executor-binding': manifest['files']['executor.py'] = '0' * 64
    put_json(state.manifest, manifest)
    if damage == 'registered-missing': registered.unlink()
    claim_path = state.attempt / '.verification-claimed/claim.json'
    claim = cleanup.read_json(claim_path); claim['sourceSha256'] = source_sha; put_json(claim_path, claim)
    counts = {'found': 3, 'passed': 2, 'failed': 0, 'skipped': 1}
    inner = cleanup.read_json(state.evidence / 'receipt.json')
    inner.update(status='PASS', javaOnly=False, fixtureProperties=[], fixtureManifest=None,
        wholeMigrationRequested=False, workerMysqlRequested=False, workerMysqlConfigSha256=None,
        pythonTests=counts.copy(), selectedPythonSuites={'tests_python.test_synthetic_pytest': counts.copy()})
    inner['commands'][0]['exitCode'] = 0
    python_command = {'label': 'python', 'exitCode': 0, 'finishedAt': '2026-11-07T00:00:00+00:00'}
    inner['commands'].append(python_command)
    source_flags = {'java-only': ('javaOnly', True), 'whole-migration': ('wholeMigrationRequested', True),
        'worker-mysql': ('workerMysqlRequested', True), 'fixtures': ('fixtureProperties', ['fixture']),
        'fixture-manifest': ('fixtureManifest', {}), 'untyped-source-flag': ('wholeMigrationRequested', 0)}
    if damage in source_flags:
        key, value = source_flags[damage]; inner[key] = value
    if damage == 'duplicate-inner-command': inner['commands'].append(python_command.copy())
    if damage == 'xml-count': inner['pythonTests'] = {**counts, 'passed': 3}
    put_json(state.evidence / 'receipt.json', inner)
    xml = (b'<testsuites><testsuite><testcase classname="tests_python.test_synthetic_pytest" name="first"/>'
           b'<testcase classname="tests_python.test_synthetic_pytest" name="second"/>'
           b'<testcase classname="tests_python.test_synthetic_pytest" name="opt_in"><skipped/></testcase>'
           b'</testsuite></testsuites>')
    if damage == 'xml-failure': xml = xml.replace(b'name="first"/>', b'name="first"><failure/></testcase>')
    python_xml = put(state.evidence / 'python.xml', xml)
    python_log = put(state.evidence / 'python.log', b'original completed synthetic Python log\n')
    state.reports.extend(['reports/python.xml', 'reports/python.log'])
    if damage == 'missing-report': state.reports.remove('reports/python.xml')
    arguments = ['-B', '-m', 'pytest', 'tests_python', '-q',
                 '--basetemp=' + str(state.evidence / 'tmp/pytest'),
                 '--junitxml=' + str(state.evidence / 'python.xml')]
    arguments_sha = cleanup.sha(json.dumps(arguments, ensure_ascii=True).encode())
    tools = cleanup.read_json(state.evidence / 'tool-runtime.json')
    command = {'tool': 'python', 'containerId': 'f' * 64, 'status': 'EXITED', 'exitCode': 0,
        'argumentsSha256': arguments_sha, 'cleanup': {'containerId': 'f' * 64,
        'image': manifest['images']['python'], 'pid': 0, 'exitCode': 0, 'removed': True}}
    if damage == 'tool-arguments': command['argumentsSha256'] = '0' * 64
    if damage == 'cleanup-pid': command['cleanup']['pid'] = 1
    if damage == 'cleanup-image': command['cleanup']['image'] = 'sha256:' + '8' * 64
    if damage == 'cleanup-removed': command['cleanup']['removed'] = False
    tools.update(sourceSha256=source_sha, manifestSha256=cleanup.digest(state.manifest), commands=[command])
    if damage == 'duplicate-tool-command': tools['commands'].append(copy.deepcopy(command))
    tools['cleanup']['manifestSha256'] = cleanup.digest(state.manifest)
    put_json(state.evidence / 'tool-runtime.json', tools)
    state.record.update(sourceSha256=source_sha, status='PASS', verificationExitCode=0)
    seal(state)
    state.keep.extend([runner_file, python_xml, python_log,
        put(state.evidence / 'tmp/retained-outside-pytest.bin', b'outside the approved pytest root'),
        put(state.checkout / 'work/tool-home/tmp/retained.bin', b'outside explicit basetemp')])
    if registered.exists(): state.keep.append(registered)
    first = put(state.evidence / 'tmp/pytest/test_synthetic_first0/payload.bin', b'regenerable test payload').parent
    second = put(state.evidence / 'tmp/pytest/test_synthetic_second0/nested/payload.bin', b'another synthetic payload').parents[1]
    return SimpleNamespace(base=first.parent, first=first, second=second, arguments_sha=arguments_sha,
                           runner_sha=cleanup.sha(runner), executor_sha=cleanup.sha(executor))


def test_proven_pytest_case_directories_are_removed_while_reports_and_other_temporary_roots_remain(state, monkeypatch):
    cases = add_pytest_cases(state, monkeypatch); before = preserved_bytes(state)
    value = plan(state); candidate = value['candidates'][0]
    proof = candidate['pytestTmp']
    assert proof['status'] == 'PROVEN' and proof['runnerSha256'] == cases.runner_sha
    assert proof['executorSha256'] == cases.executor_sha and proof['argumentsSha256'] == cases.arguments_sha
    assert proof['pythonTests'] == {'found': 3, 'passed': 2, 'failed': 0, 'skipped': 1}
    assert proof['rootStatus'] == 'INSPECTED' and proof['skippedCases'] == []
    targets = [row for row in candidate['targets'] if row['kind'] == 'PYTEST_CASE_DIRECTORY']
    assert {row['path'] for row in targets} == {str(path.relative_to(state.root)) for path in (cases.first, cases.second)}
    result = cleanup.apply_plan(state.root, state.request, value, remote)
    assert result['status'] == 'REMOVED' and cases.base.is_dir()
    assert not cases.first.exists() and not cases.second.exists()
    assert sum(row['kind'] == 'PYTEST_CASE_DIRECTORY' for row in result['deleted']) == 2
    assert preserved_bytes(state) == before


@pytest.mark.parametrize('damage,reason', [
    *[(name, 'PYTEST_SOURCE_SCOPE_REQUIRED') for name in ('java-only', 'whole-migration', 'worker-mysql',
        'fixtures', 'fixture-manifest', 'untyped-source-flag', 'duplicate-inner-command', 'missing-report')],
    ('missing-source', 'PYTEST_SOURCE_RECIPE_MISSING'),
    ('changed-runner', 'PYTEST_RUNNER_NOT_REVIEWED'), ('duplicate-runner', 'PYTEST_RUNNER_NOT_REVIEWED'),
    ('async-duplicate-runner', 'PYTEST_RUNNER_NOT_REVIEWED'),
    ('changed-routing', 'PYTEST_ROUTING_NOT_REVIEWED'),
    ('runner-binding', 'PYTEST_RUNNER_BINDING_MISSING_OR_CHANGED'),
    ('executor-binding', 'PYTEST_EXECUTOR_BINDING_MISSING_OR_CHANGED'),
    ('registered-missing', 'PYTEST_REGISTERED_EXECUTOR_UNAVAILABLE'),
    ('xml-count', 'PYTEST_REPORT_NOT_PASS'), ('xml-failure', 'PYTEST_REPORT_NOT_PASS'),
    *[(name, 'PYTEST_TOOL_COMMAND_PROVENANCE_MISSING') for name in
      ('tool-arguments', 'duplicate-tool-command', 'cleanup-pid', 'cleanup-image', 'cleanup-removed')],
])
def test_unproven_pytest_namespace_is_skipped_without_losing_existing_compiled_targets(state, monkeypatch, damage, reason):
    cases = add_pytest_cases(state, monkeypatch, damage); before = preserved_bytes(state)
    value = plan(state); candidate = value['candidates'][0]
    assert candidate['pytestTmp'] == {'status': 'SKIPPED', 'reason': reason}
    assert all(row['kind'] != 'PYTEST_CASE_DIRECTORY' for row in candidate['targets'])
    result = cleanup.apply_plan(state.root, state.request, value, remote)
    assert result['status'] == 'REMOVED' and cases.first.is_dir() and cases.second.is_dir()
    assert not state.classes.exists() and preserved_bytes(state) == before


@pytest.mark.parametrize('damage,reason', [
    ('symlink', 'PYTEST_CASE_METADATA_UNSAFE'), ('hardlink', 'PYTEST_CASE_HARDLINK_OR_SPARSE'),
    ('fifo', 'PYTEST_CASE_METADATA_UNSAFE'), ('sparse', 'PYTEST_CASE_HARDLINK_OR_SPARSE'),
    ('foreign-owner', 'PYTEST_CASE_METADATA_UNSAFE'), ('foreign-writable', 'PYTEST_CASE_METADATA_UNSAFE'),
    ('foreign-device', 'PYTEST_CASE_METADATA_UNSAFE'), ('size-bound', 'PYTEST_CASE_BOUND_EXCEEDED'),
    ('case-name', 'PYTEST_CASE_NAME_INVALID'),
])
def test_unsafe_pytest_case_is_skipped_before_hashing_and_does_not_block_safe_cases(state, monkeypatch, damage, reason):
    cases = add_pytest_cases(state, monkeypatch)
    bad = cases.base / ('unreviewed case name' if damage == 'case-name' else 'test_unsafe0')
    leaf = put(bad / 'payload.bin', b'unsafe synthetic test payload')
    if damage == 'symlink': leaf.unlink(); leaf.symlink_to(state.keep[2])
    elif damage == 'hardlink': os.link(leaf, state.root / 'outside-pytest-hardlink')
    elif damage == 'fifo': leaf.unlink(); os.mkfifo(leaf, 0o600)
    elif damage == 'sparse':
        with leaf.open('wb') as stream: stream.truncate(1024 * 1024)
    elif damage == 'foreign-writable': leaf.chmod(0o666)
    elif damage == 'size-bound':
        put(leaf, b'x' * 2048); monkeypatch.setattr(cleanup, 'MAX_TREE_BYTES', 1024)
    elif damage in ('foreign-owner', 'foreign-device'):
        original = Path.lstat
        def changed(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path != leaf: return info
            values = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
            values['st_uid' if damage == 'foreign-owner' else 'st_dev'] += 1
            return SimpleNamespace(**values)
        monkeypatch.setattr(Path, 'lstat', changed)
    inventory = cleanup.tree_inventory
    def no_unsafe_hash(path):
        assert path != bad, 'Unsafe test fixture must be skipped before content hashing'
        return inventory(path)
    monkeypatch.setattr(cleanup, 'tree_inventory', no_unsafe_hash)
    before = preserved_bytes(state); value = plan(state); candidate = value['candidates'][0]
    label = {'nameSha256': cleanup.sha(os.fsencode(bad.name))} if damage == 'case-name' else {'name': bad.name}
    assert {**label, 'reason': reason} in candidate['pytestTmp']['skippedCases']
    targets = [row for row in candidate['targets'] if row['kind'] == 'PYTEST_CASE_DIRECTORY']
    assert {row['path'] for row in targets} == {str(path.relative_to(state.root)) for path in (cases.first, cases.second)}
    result = cleanup.apply_plan(state.root, state.request, value, remote)
    assert result['status'] == 'REMOVED' and bad.is_dir()
    assert not cases.first.exists() and not cases.second.exists() and not state.classes.exists()
    assert preserved_bytes(state) == before


@pytest.mark.parametrize('suffix', ['work/ci-evidence/tmp', 'work/ci-evidence/tmp/pytest',
    'work/ci-evidence/tmp/pytest/test_synthetic0/nested', 'work/ci-evidence/tmp/pytest/../outside',
    'work/ci-evidence/tmp/pytest/.', 'work/ci-evidence/tmp/pytest/..', 'work/tool-home/tmp/test_synthetic0'])
def test_pytest_delete_api_rejects_parent_descendant_traversal_and_other_temporary_roots(state, suffix):
    fd = os.open(state.root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(ValueError, match='OUTSIDE_COMPILED_ALLOWLIST'):
            cleanup.remove_target(fd, {'kind': 'PYTEST_CASE_DIRECTORY',
                'path': 'verification/' + OLD + '/checkout/' + suffix})
    finally: os.close(fd)
    assert state.classes.exists()


def test_pytest_case_changed_after_planning_prevents_all_deletions(state, monkeypatch):
    cases = add_pytest_cases(state, monkeypatch); value = plan(state); before = preserved_bytes(state)
    put(cases.first / 'payload.bin', b'changed after inventory approval')
    with pytest.raises(ValueError, match='PLAN_OR_ORIGINAL_EVIDENCE_CHANGED_NO_DELETION'):
        cleanup.apply_plan(state.root, state.request, value, remote)
    assert cases.first.is_dir() and cases.second.is_dir() and state.classes.is_dir()
    assert not (state.root / 'inbox' / CURRENT / 'build-cleanup-journal.jsonl').exists()
    assert preserved_bytes(state) == before


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


def test_full_control_capacity_refuses_before_any_journal_or_deletion(state, monkeypatch):
    value = plan(state); before = preserved_bytes(state)
    started = {'phase': 'STARTED', 'planSha256': cleanup.sha(cleanup.canonical(value)), 'identity': IDENTITY}
    target = value['candidates'][0]['targets'][0]
    deleting = {'phase': 'DELETE_STARTED', 'path': target['path'], 'inventorySha256': target['inventorySha256']}
    normal_limit = len(cleanup.canonical(started)) + 1 + len(cleanup.canonical(deleting))
    monkeypatch.setattr(cleanup, 'MAX_PLAN', normal_limit + 4096)
    with pytest.raises(ValueError, match='CONTROL_PLAN_JOURNAL_OR_RECEIPT_EXCEEDS_LIMIT'):
        cleanup.apply_plan(state.root, state.request, value, remote)
    assert not (state.root / 'inbox' / CURRENT / 'build-cleanup-journal.jsonl').exists()
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
    monkeypatch.setattr(cleanup, 'process_references', PROCESS_REFERENCES)
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


def test_failure_metadata_parses_the_same_fixed_source_once_for_one_hundred_diagnostics(monkeypatch):
    source = b'def fixed_guard():\n    require(False, "CACHED_AUTHORED_GUARD")\n'
    cleanup._failure_source_metadata.cache_clear()
    monkeypatch.setattr(cleanup, 'LOADED_SOURCE', source)
    original = ast.parse; calls = []
    def tracked(raw, *args, **kwargs):
        calls.append(raw)
        return original(raw, *args, **kwargs)
    monkeypatch.setattr(cleanup.ast, 'parse', tracked)
    for _ in range(100):
        error = ValueError('CACHED_AUTHORED_GUARD')
        assert cleanup.failure_guard_code(error) == 'CACHED_AUTHORED_GUARD'
        assert cleanup.failure_details(error) == {'guardCode': 'CACHED_AUTHORED_GUARD', 'locations': []}
    assert calls == [source]


def test_failure_metadata_reparses_changed_source_and_replaces_its_guard_and_function_sets(monkeypatch):
    first = (b'def first_guard():\n    require(False, "FIRST_AUTHORED_GUARD")\n'
             b'async def first_async_guard():\n    pass\n')
    second = b'def second_guard():\n    require(False, "SECOND_AUTHORED_GUARD")\n'
    cleanup._failure_source_metadata.cache_clear()
    original = ast.parse; calls = []
    def tracked(raw, *args, **kwargs):
        calls.append(raw)
        return original(raw, *args, **kwargs)
    monkeypatch.setattr(cleanup.ast, 'parse', tracked)
    monkeypatch.setattr(cleanup, 'LOADED_SOURCE', first)
    assert cleanup.failure_guard_code(ValueError('FIRST_AUTHORED_GUARD')) == 'FIRST_AUTHORED_GUARD'
    assert cleanup._failure_source_metadata(first) == (
        frozenset({'FIRST_AUTHORED_GUARD'}), frozenset({'<module>', 'first_guard', 'first_async_guard'}), 4)
    monkeypatch.setattr(cleanup, 'LOADED_SOURCE', second)
    assert cleanup.failure_guard_code(ValueError('FIRST_AUTHORED_GUARD')) == 'UNCLASSIFIED_VALIDATION_ERROR'
    assert cleanup.failure_guard_code(ValueError('SECOND_AUTHORED_GUARD')) == 'SECOND_AUTHORED_GUARD'
    assert cleanup._failure_source_metadata(second) == (
        frozenset({'SECOND_AUTHORED_GUARD'}), frozenset({'<module>', 'second_guard'}), 2)
    assert calls == [first, second]


@pytest.mark.parametrize('source', [None, b''])
def test_absent_failure_source_has_no_authored_metadata_and_never_enters_the_parser(monkeypatch, source):
    cleanup._failure_source_metadata.cache_clear()
    monkeypatch.setattr(cleanup, 'LOADED_SOURCE', source)
    def forbidden(*args, **kwargs):
        raise AssertionError('Absent fixed source must not enter ast.parse')
    monkeypatch.setattr(cleanup.ast, 'parse', forbidden)
    assert cleanup._failure_source_metadata(source) == (frozenset(), frozenset(), 0)
    assert cleanup.failure_details(ValueError('PRIVATE_UNREVIEWED_PAYLOAD')) == {
        'guardCode': 'UNCLASSIFIED_VALIDATION_ERROR', 'locations': []}


def test_failure_details_redact_arbitrary_valueerror_arguments_and_keep_exact_guard_matching():
    private = 'CURRENT_FIXED_SOURCE_INVALID private=/home/private/originals.sql password=PRIVATE_SENTINEL'
    details = cleanup.failure_details(ValueError(private))
    assert details == {'guardCode': 'UNCLASSIFIED_VALIDATION_ERROR', 'locations': []}
    raw = json.dumps(details)
    assert 'PRIVATE_SENTINEL' not in raw and '/home/private' not in raw and 'password' not in raw
    assert cleanup.failure_guard_code(ValueError('CURRENT_FIXED_SOURCE_INVALID', private)) == 'UNCLASSIFIED_VALIDATION_ERROR'
    assert cleanup.failure_guard_code(RuntimeError(private)) == 'UNCLASSIFIED_OS_ERROR'


def test_failure_details_keep_only_the_nearest_eight_known_frames_from_the_exact_controller_filename():
    private = 'PRIVATE_TRACE_PAYLOAD /home/private/originals.sql'
    foreign = {'payload': private}
    exec(compile('def require():\n    raise ValueError(payload)\n', '<foreign-diagnostic-fixture>', 'exec'), foreign)
    own = {'foreign_guard': foreign['require']}
    program = ('def require(depth):\n'
               '    if depth: return require(depth - 1)\n'
               '    return unreviewed_diagnostic_frame()\n'
               'def unreviewed_diagnostic_frame():\n'
               '    return foreign_guard()\n')
    assert 'unreviewed_diagnostic_frame' not in cleanup._failure_source_metadata(cleanup.LOADED_SOURCE)[1]
    exec(compile(program, cleanup.__file__, 'exec'), own)
    with pytest.raises(ValueError) as caught:
        own['require'](16)
    details = cleanup.failure_details(caught.value)
    assert details == {'guardCode': 'UNCLASSIFIED_VALIDATION_ERROR', 'locations':
        [{'function': 'require', 'line': 2}] * 7 + [{'function': 'require', 'line': 3}]}
    raw = json.dumps(details)
    assert 'PRIVATE_TRACE_PAYLOAD' not in raw and '/home/private' not in raw
    assert cleanup.__file__ not in raw and 'foreign-diagnostic-fixture' not in raw


def test_real_cleanup_cli_reports_a_known_guard_and_bounded_locations_before_any_output_write(tmp_path):
    output = tmp_path / 'must-not-be-created.json'
    result = subprocess.run([sys.executable, '-I', '-B', cleanup.__file__, 'plan',
        '--output', str(output), '--current-tag', 'not-an-admitted-tag'],
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 2 and result.stdout == '' and not output.exists()
    details = json.loads(result.stderr)
    assert set(details) == {'status', 'errorType', 'guardCode', 'locations'}
    assert details['status'] == 'REFUSED' and details['errorType'] == 'ValueError'
    assert details['guardCode'] == 'CURRENT_FIXED_SOURCE_INVALID'
    assert 1 <= len(details['locations']) <= 8
    assert all(set(row) == {'function', 'line'} and type(row['line']) is int and row['line'] > 0
               for row in details['locations'])
    assert {'main', 'require'} <= {row['function'] for row in details['locations']}
    assert cleanup.__file__ not in result.stderr and str(output) not in result.stderr


def clone_cleanup_candidate(state, tag):
    """Create another independently sealed synthetic attempt in the same CI root."""
    attempt = state.root / 'verification' / tag; inbox = state.root / 'inbox' / tag
    shutil.copytree(state.attempt, attempt); shutil.copytree(state.inbox, inbox)
    def relocated(path):
        for old, new in ((state.attempt, attempt), (state.inbox, inbox)):
            if path == old or path.is_relative_to(old): return new / path.relative_to(old)
        return path
    value = SimpleNamespace(root=state.root, attempt=attempt, checkout=relocated(state.checkout),
        evidence=relocated(state.evidence), inbox=inbox, manifest=relocated(state.manifest),
        record=copy.deepcopy(state.record), archive=relocated(state.archive), classes=relocated(state.classes),
        reports=list(state.reports), keep=[relocated(path) for path in state.keep])
    value.record['release'] = tag
    manifest = cleanup.read_json(value.manifest)
    manifest.update(release=tag, directory=str(value.manifest.parent), checkout=str(value.checkout), token='7' * 24)
    put_json(value.manifest, manifest)
    claim = cleanup.read_json(attempt / '.verification-claimed/claim.json'); claim['release'] = tag
    put_json(attempt / '.verification-claimed/claim.json', claim)
    tools = cleanup.read_json(value.evidence / 'tool-runtime.json')
    tools.update(release=tag, manifestSha256=cleanup.digest(value.manifest))
    tools['cleanup'].update(release=tag, manifestSha256=cleanup.digest(value.manifest))
    for ordinal, command in enumerate(tools.get('commands', [])):
        if command.get('containerId') is not None:
            command['containerId'] = format(ordinal + 7, '064x')
            if isinstance(command.get('cleanup'), dict): command['cleanup']['containerId'] = command['containerId']
        if command.get('tool') == 'python':
            arguments = ['-B', '-m', 'pytest', 'tests_python', '-q',
                '--basetemp=' + str(value.evidence / 'tmp/pytest'),
                '--junitxml=' + str(value.evidence / 'python.xml')]
            command['argumentsSha256'] = cleanup.sha(json.dumps(arguments, ensure_ascii=True).encode())
    put_json(value.evidence / 'tool-runtime.json', tools)
    seal(value)
    return value


def target_canonical_cost(targets):
    return sum(len(cleanup.canonical(target)) + 1 for target in targets)


def test_tiny_batch_skips_an_early_large_case_then_reclaims_it_next_time_with_the_same_budget(state, monkeypatch):
    cases = add_pytest_cases(state, monkeypatch)
    large = put(cases.base / 'test_a_large0/payload-a.bin', b'first synthetic payload').parent
    put(large / 'payload-b.bin', b'second synthetic payload')
    complete = plan(state); targets = complete['candidates'][0]['targets']
    base_cost = target_canonical_cost([row for row in targets if row['kind'] != 'PYTEST_CASE_DIRECTORY'])
    small = next(row for row in targets if row['path'] == cases.first.relative_to(state.root).as_posix())
    large_target = next(row for row in targets if row['path'] == large.relative_to(state.root).as_posix())
    limit = base_cost + target_canonical_cost([small])
    assert target_canonical_cost([small]) < target_canonical_cost([large_target]) <= limit
    monkeypatch.setattr(cleanup, 'MAX_TARGET_CANONICAL', limit)
    inventory = cleanup.tree_inventory
    def no_large_hash(path):
        assert path != large, 'An over-budget case must stop before content hashing'
        return inventory(path)
    monkeypatch.setattr(cleanup, 'tree_inventory', no_large_hash)
    before = preserved_bytes(state); value = plan(state)
    assert value == plan(state)
    candidate = value['candidates'][0]
    assert [row['path'] for row in candidate['targets'] if row['kind'] == 'PYTEST_CASE_DIRECTORY'] == [small['path']]
    assert {'name': large.name, 'reason': 'PYTEST_TARGET_CANONICAL_BUDGET_EXCEEDED'} in candidate['pytestTmp']['skippedCases']
    result = cleanup.apply_plan(state.root, state.request, value, remote)
    assert result['status'] == 'REMOVED' and not cases.first.exists() and large.is_dir() and cases.second.is_dir()
    assert not state.classes.exists() and preserved_bytes(state) == before
    monkeypatch.setattr(cleanup, 'tree_inventory', inventory)
    following = 'ci-73-' + 'd' * 12
    (state.root / 'inbox' / following).mkdir(mode=0o700)
    state.request.update(currentRelease=following, protectedReleases=[following, CURRENT])
    assert cleanup.MAX_TARGET_CANONICAL == limit
    next_plan = plan(state)
    assert any(row['path'] == large_target['path'] for row in next_plan['candidates'][0]['targets'])
    next_result = cleanup.apply_plan(state.root, state.request, next_plan, remote)
    assert next_result['status'] == 'REMOVED' and not large.exists()
    assert preserved_bytes(state) == before


def test_all_candidates_compiled_and_npm_targets_get_the_shared_budget_before_pytest_cases(state, monkeypatch):
    cases = add_pytest_cases(state, monkeypatch)
    later = clone_cleanup_candidate(state, 'ci-71-' + 'a' * 12)
    cache = add_npm_cache(later)
    inner = cleanup.read_json(later.evidence / 'receipt.json'); inner['status'] = 'FAILED'
    put_json(later.evidence / 'receipt.json', inner)
    later.record.update(status='FAILED', verificationExitCode=1)
    tools = cleanup.read_json(later.evidence / 'tool-runtime.json')
    tools['commands'][0]['containerId'] = '8' * 64; tools['commands'][0]['cleanup']['containerId'] = '8' * 64
    put_json(later.evidence / 'tool-runtime.json', tools); seal(later)
    state.keep.extend(later.keep); state.request['candidates'].extend(later.request['candidates'])
    complete = plan(state)
    base = [row for candidate in complete['candidates'] for row in candidate['targets']
            if row['kind'] != 'PYTEST_CASE_DIRECTORY']
    assert any(row['kind'] == 'NPM_CACHE' for row in base)
    monkeypatch.setattr(cleanup, 'MAX_TARGET_CANONICAL', target_canonical_cost(base))
    before = preserved_bytes(state); value = plan(state)
    assert [row['release'] for row in value['candidates']] == [OLD, later.record['release']]
    selected = [row for candidate in value['candidates'] for row in candidate['targets']]
    assert selected == base and all(row['kind'] != 'PYTEST_CASE_DIRECTORY' for row in selected)
    result = cleanup.apply_plan(state.root, state.request, value, remote)
    assert result['status'] == 'REMOVED' and not cache.exists() and not later.classes.exists()
    assert not state.classes.exists() and cases.first.is_dir() and cases.second.is_dir()
    assert preserved_bytes(state) == before


def test_rejected_base_candidate_returns_its_whole_budget_to_the_next_candidate(state, monkeypatch):
    later = clone_cleanup_candidate(state, 'ci-71-' + 'a' * 12)
    for ordinal in range(12): put(state.classes / ('extra-' + str(ordinal) + '.class'), b'synthetic compiled output')
    state.keep.extend(later.keep); state.request['candidates'].extend(later.request['candidates'])
    complete = plan(state); first, second = complete['candidates']
    later_cost = target_canonical_cost(second['targets'])
    assert target_canonical_cost(first['targets']) > later_cost
    monkeypatch.setattr(cleanup, 'MAX_TARGET_CANONICAL', later_cost)
    before = preserved_bytes(state); value = plan(state)
    assert [row['release'] for row in value['candidates']] == [later.record['release']]
    assert {'release': OLD, 'reason': 'TARGET_CANONICAL_BUDGET_EXCEEDED'} in value['skipped']
    assert target_canonical_cost(value['candidates'][0]['targets']) == later_cost
    result = cleanup.apply_plan(state.root, state.request, value, remote)
    assert result['status'] == 'REMOVED' and state.classes.is_dir() and not later.classes.exists()
    assert preserved_bytes(state) == before


def test_skip_details_are_capped_but_the_full_ordered_digest_detects_changes_after_the_cap(state, monkeypatch):
    cases = add_pytest_cases(state, monkeypatch)
    names = ['case_alias_' + format(ordinal, '03d') for ordinal in range(70)]
    for name in names: (cases.base / name).symlink_to(cases.first, target_is_directory=True)
    expected = [{'name': name, 'reason': 'PYTEST_CASE_NOT_REGULAR_DIRECTORY'} for name in names]
    before = preserved_bytes(state); value = plan(state); proof = value['candidates'][0]['pytestTmp']
    assert cleanup.PYTEST_SKIP_DETAIL_LIMIT == 64
    assert proof['skippedCases'] == expected[:64] and proof['skippedCaseCount'] == 70
    assert proof['skippedCasesSha256'] == cleanup.sha(b''.join(cleanup.canonical(row) + b'\n' for row in expected))
    (cases.base / names[-1]).rename(cases.base / 'case_alias_zzzz')
    changed = plan(state)['candidates'][0]['pytestTmp']
    assert changed['skippedCases'] == proof['skippedCases'] and changed['skippedCaseCount'] == 70
    assert changed['skippedCasesSha256'] != proof['skippedCasesSha256']
    with pytest.raises(ValueError, match='PLAN_OR_ORIGINAL_EVIDENCE_CHANGED_NO_DELETION'):
        cleanup.apply_plan(state.root, state.request, value, remote)
    assert state.classes.is_dir() and cases.first.is_dir() and cases.second.is_dir()
    assert not (state.root / 'inbox' / CURRENT / 'build-cleanup-journal.jsonl').exists()
    assert preserved_bytes(state) == before


def test_metadata_estimate_matches_the_descriptor_and_rejects_one_byte_short_without_hashing(state, monkeypatch):
    cases = add_pytest_cases(state, monkeypatch)
    target = {'path': cases.first.relative_to(state.root).as_posix(), 'kind': 'PYTEST_CASE_DIRECTORY',
              **cleanup.tree_inventory(cases.first)}
    exact = target_canonical_cost([target])
    assert cleanup.pytest_case_preflight(cases.first, state.root, remaining=exact) == exact
    def forbidden(path): raise AssertionError('Metadata admission must not hash content')
    monkeypatch.setattr(cleanup, 'digest', forbidden)
    with pytest.raises(ValueError, match='PYTEST_TARGET_CANONICAL_BUDGET_EXCEEDED'):
        cleanup.pytest_case_preflight(cases.first, state.root, remaining=exact - 1)


def test_case_growth_after_metadata_admission_is_skipped_without_consuming_the_exact_budget(state, monkeypatch):
    cases = add_pytest_cases(state, monkeypatch)
    target = {'path': cases.first.relative_to(state.root).as_posix(), 'kind': 'PYTEST_CASE_DIRECTORY',
              **cleanup.tree_inventory(cases.first)}
    available = target_canonical_cost([target]); budget = {'remaining': available}
    binding = cleanup.evidence_binding(state.root, state.request['candidates'][0], IDENTITY, remote)
    original = cleanup.pytest_case_preflight
    def grow_after_preflight(path, root, *, remaining=None):
        estimate = original(path, root, remaining=remaining)
        if path == cases.first: put(path / 'new-after-preflight.bin', b'a new synthetic row after metadata admission')
        return estimate
    monkeypatch.setattr(cleanup, 'pytest_case_preflight', grow_after_preflight)
    selected = cleanup.pytest_case_targets(state.root, binding, budget=budget)
    assert selected == [] and budget == {'remaining': available}
    assert {'name': cases.first.name, 'reason': 'PYTEST_TARGET_CANONICAL_BUDGET_EXCEEDED'} in binding['pytestTmp']['skippedCases']
    assert (cases.first / 'new-after-preflight.bin').is_file() and cases.second.is_dir()
