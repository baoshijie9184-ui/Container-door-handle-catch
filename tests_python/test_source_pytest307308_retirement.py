"""Contracts for the separate, exact #307/#308 synthetic pytest retirement.

The original sixteen-root module has its own import and unchanged authorization.
These cases create only pytest-owned synthetic controls and files on ECS.
"""
import ast
import copy
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'source_pytest307308_retirement_direct_contract', ROOT / 'script/jenkins/retire-source-pytest.py')
retirement = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retirement)

OLD_BATCH = 'source-pytest16-20261114'
NEW_BATCH = 'source-pytest307308-20261114'
RELEASES = ('ci-307-dc8219bd868f', 'ci-308-ba8f5b580c7a')
QUALITY_CLASS = 'com.ruanzhu.doorhandle.module.app.service.knowledge.QualityKnowledgeMySqlTest'


@pytest.fixture(autouse=True)
def exact_new_batch():
    retirement.select_batch(NEW_BATCH)
    try:
        yield
    finally:
        retirement.select_batch(OLD_BATCH)


def authorization_for_selected_batch():
    return {'schemaVersion': 1,
        'kind': 'doorhandle-exact-source-pytest-temporary-retirement-authorization',
        'source': 'USER_EXPLICIT_MESSAGE', 'answer': retirement.USER_ANSWER,
        'branch': 'java-cloud', 'job': 'doorhandle-java', 'root': str(retirement.ROOT),
        'identity': copy.deepcopy(retirement.IDENTITY), 'actorUid': 1000,
        'exactBuilds': list(retirement.EXACT_BUILDS),
        'entries': copy.deepcopy(retirement.APPROVED_ENTRIES), 'excludedBuilds': [225, 229, 266],
        'allowArbitraryPath': False, 'allowFutureBuilds': False, 'allowDiskExpansion': False,
        'allowRootTargetMutations': False, 'allowOwnerWriteForOwnedTargetDirectories': True,
        'authorizationEndsWhenExactTargetsConsumed': True,
        'requiredConditions': copy.deepcopy(retirement.REQUIRED_CONDITIONS),
        'alwaysPreserve': copy.deepcopy(retirement.ALWAYS_PRESERVE),
        'grantedAtUtc': '2026-11-14T09:00:00+00:00'}


@pytest.fixture
def source_scope():
    entry = copy.deepcopy(retirement.APPROVED_ENTRIES[0])
    tally = {'found': 14, 'passed': 14, 'failed': 0, 'skipped': 0}
    inner = {'javaOnly': False, 'wholeMigrationRequested': False, 'workerMysqlRequested': False,
        'fixtureManifest': None, 'workerMysqlConfigSha256': None,
        'fixtureProperties': ['doorhandle.feature.mysql.config'],
        'semanticMysqlComponentRequested': True,
        'javaSuites': [{'id': 'suite-001', 'javaSelection': [QUALITY_CLASS],
            'fixtureProperties': ['doorhandle.feature.mysql.config'], 'status': 'PASS',
            'javaTests': tally.copy(), 'selectedJavaClasses': {QUALITY_CLASS: tally.copy()}}]}
    semantic = {'version': 1, 'kind': 'doorhandle-semantic-mysql-fixture',
        'release': entry['release'], 'commit': entry['sourceProof']['commit'],
        'sourceSha256': entry['sourceProof']['sourceSha256'],
        'identity': copy.deepcopy(retirement.IDENTITY), 'sourceData': 'SYNTHETIC_ONLY',
        'ready': True, 'status': 'STOPPED', 'cleanupConfirmed': True,
        'providerCalls': 0, 'productionPromotionAllowed': False,
        'privateOriginals': ['work/semantic-mysql-fixture/ready-server.json',
                            'work/semantic-mysql-fixture/stopped-container.json']}
    return SimpleNamespace(entry=entry, inner=inner, semantic=semantic)


def test_new_batch_contains_only_the_two_original_exact_roots_and_complete_source_proofs():
    assert retirement.BATCH == NEW_BATCH
    assert retirement.EXACT_BUILDS == [307, 308]
    assert retirement.EXACT_RELEASES == RELEASES
    assert retirement.USER_ANSWER == '允许按原条件回收这两份（推荐）'
    for entry, release in zip(retirement.APPROVED_ENTRIES, RELEASES):
        assert entry['release'] == release
        assert entry['path'] == str(retirement.ROOT / 'verification' / release /
                                   'checkout/work/ci-evidence/tmp/pytest')
        proof = entry['sourceProof']
        assert set(proof) == {'commit', 'sourceSha256', 'verificationReceiptSha256',
                             'reportCatalogSha256', 'claimSha256', 'toolManifestSha256'}
        assert len(proof['commit']) == 40 and release.endswith(proof['commit'][:12])
        assert all(retirement.SHA.fullmatch(value) for key, value in proof.items() if key != 'commit')


def test_batch_switching_does_not_expand_or_mutate_the_original_sixteen_root_contract():
    new_entries = copy.deepcopy(retirement.APPROVED_ENTRIES)
    retirement.select_batch(OLD_BATCH)
    old_entries = copy.deepcopy(retirement.APPROVED_ENTRIES)
    assert len(old_entries) == 16
    assert retirement.EXACT_BUILDS == [100, 102, 103, 104, 105, 107, 109, 110,
                                      114, 120, 122, 150, 178, 180, 215, 217]
    assert not set(RELEASES) & set(retirement.EXACT_RELEASES)
    retirement.select_batch(NEW_BATCH)
    assert retirement.APPROVED_ENTRIES == new_entries
    retirement.select_batch(OLD_BATCH)
    assert retirement.APPROVED_ENTRIES == old_entries


@pytest.mark.parametrize('name', ['SourcePytest307308', 'source-pytest-all', '', None, [NEW_BATCH]])
def test_batch_selection_is_closed_and_rejected_selection_does_not_change_scope(name):
    original = (retirement.BATCH, copy.deepcopy(retirement.APPROVED_ENTRIES))
    with pytest.raises(ValueError, match='UNAPPROVED_PYTEST_BATCH'):
        retirement.select_batch(name)
    assert (retirement.BATCH, retirement.APPROVED_ENTRIES) == original


def test_new_authorization_accepts_only_its_actual_exact_user_scope():
    auth = authorization_for_selected_batch()
    assert retirement.validate_authorization(auth) == auth['entries']


@pytest.mark.parametrize('field,value', [
    ('answer', '允许按条件回收这16份旧Python测试目录'), ('source', 'ASSUMED_CONSENT'),
    ('exactBuilds', [307, 308, 309]), ('exactBuilds', [307]),
    ('allowArbitraryPath', True), ('allowFutureBuilds', True), ('allowDiskExpansion', True),
    ('allowRootTargetMutations', True), ('allowOwnerWriteForOwnedTargetDirectories', False),
    ('authorizationEndsWhenExactTargetsConsumed', False), ('actorUid', True),
    ('excludedBuilds', [225, 229]), ('requiredConditions', []), ('alwaysPreserve', []),
])
def test_new_authorization_rejects_extra_powers_builds_or_weakened_preservation(field, value):
    auth = authorization_for_selected_batch()
    auth[field] = value
    with pytest.raises(ValueError):
        retirement.validate_authorization(auth)


@pytest.mark.parametrize('change', ['missing-entry', 'extra-entry', 'release', 'path', 'proof'])
def test_new_authorization_rejects_changed_original_source_or_target(change):
    auth = authorization_for_selected_batch()
    if change == 'missing-entry': auth['entries'].pop()
    elif change == 'extra-entry': auth['entries'].append(copy.deepcopy(auth['entries'][0]))
    elif change == 'release': auth['entries'][0]['release'] = 'ci-309-' + 'a' * 12
    elif change == 'path': auth['entries'][0]['path'] += '/..'
    else: auth['entries'][0]['sourceProof']['claimSha256'] = 'f' * 64
    with pytest.raises(ValueError):
        retirement.validate_authorization(auth)


def test_authorizations_for_the_old_and_new_batches_cannot_be_consumed_by_each_other():
    new_auth = authorization_for_selected_batch()
    retirement.select_batch(OLD_BATCH)
    old_auth = authorization_for_selected_batch()
    with pytest.raises(ValueError):
        retirement.validate_authorization(new_auth)
    retirement.select_batch(NEW_BATCH)
    with pytest.raises(ValueError):
        retirement.validate_authorization(old_auth)


def test_new_batch_has_distinct_authorization_marker_and_bound_receipt_context():
    args = SimpleNamespace(tag='ci-310-' + 'a' * 12, commit='a' * 40,
        source_sha256='b' * 64, authorization_sha256='c' * 64)
    assert retirement.AUTHORIZATION_NAME == 'source-pytest307308-authorization.json'
    marker = retirement.marker_path(RELEASES[0])
    assert marker.name == 'source-pytest307308-retired.json'
    assert retirement.context(args)['batch'] == NEW_BATCH
    retirement.select_batch(OLD_BATCH)
    assert retirement.AUTHORIZATION_NAME == 'source-pytest16-authorization.json'
    assert retirement.marker_path(RELEASES[0]) != marker
    assert retirement.context(args)['batch'] == OLD_BATCH


def test_exact_semantic_component_is_admitted_only_for_the_new_batch(source_scope):
    retirement.require_source_scope(source_scope.inner, source_scope.entry, source_scope.semantic)
    retirement.select_batch(OLD_BATCH)
    with pytest.raises(ValueError, match='SYNTHETIC_SOURCE_ONLY_REQUIRED'):
        retirement.require_source_scope(source_scope.inner, source_scope.entry, source_scope.semantic)
    source_scope.inner['fixtureProperties'] = []
    retirement.require_source_scope(source_scope.inner, source_scope.entry)


@pytest.mark.parametrize('field,value', [
    ('javaOnly', True), ('wholeMigrationRequested', True), ('workerMysqlRequested', True),
    ('fixtureManifest', {}), ('workerMysqlConfigSha256', 'a' * 64),
    ('fixtureProperties', []), ('fixtureProperties', ['doorhandle.ecs.mysql.config']),
    ('fixtureProperties', ['doorhandle.feature.mysql.config', 'doorhandle.ecs.mysql.config']),
    ('fixtureProperties', ['doorhandle.feature.mysql.config'] * 2),
    ('semanticMysqlComponentRequested', False), ('semanticMysqlComponentRequested', 'true'),
])
def test_new_source_scope_never_accepts_other_fixture_or_migration_modes(source_scope, field, value):
    source_scope.inner[field] = value
    with pytest.raises(ValueError):
        retirement.require_source_scope(source_scope.inner, source_scope.entry, source_scope.semantic)


@pytest.mark.parametrize('field,value', [
    ('kind', 'unrelated-fixture'), ('sourceData', 'DERIVED_REAL_SOURCE'),
    ('status', 'RUNNING'), ('cleanupConfirmed', False), ('identity', {}),
    ('ready', False), ('providerCalls', 1), ('productionPromotionAllowed', True),
    ('release', 'ci-266-' + 'a' * 12), ('commit', 'f' * 40), ('sourceSha256', 'f' * 64),
])
def test_semantic_component_must_have_original_synthetic_source_identity_and_stop_receipt(
        source_scope, field, value):
    source_scope.semantic[field] = value
    with pytest.raises(ValueError, match='SEMANTIC_COMPONENT_CUSTODY_REQUIRED'):
        retirement.require_source_scope(source_scope.inner, source_scope.entry, source_scope.semantic)


@pytest.mark.parametrize('change', ['absent', 'extra-suite', 'different-class', 'different-property',
                                   'not-passed', 'failed-case', 'skipped-case', 'missing-case'])
def test_native_suite_exception_requires_only_the_fourteen_original_quality_cases(source_scope, change):
    suites = source_scope.inner['javaSuites']
    if change == 'absent': source_scope.inner.pop('javaSuites')
    elif change == 'extra-suite': suites.append(copy.deepcopy(suites[0]))
    elif change == 'different-class': suites[0]['javaSelection'] = ['UnrelatedMySqlTest']
    elif change == 'different-property': suites[0]['fixtureProperties'] = ['doorhandle.ecs.mysql.config']
    elif change == 'not-passed': suites[0]['status'] = 'FAILED'
    elif change == 'failed-case': suites[0]['javaTests'].update(passed=13, failed=1)
    elif change == 'skipped-case': suites[0]['javaTests'].update(passed=13, skipped=1)
    else: suites[0]['javaTests'].update(found=13, passed=13)
    with pytest.raises(ValueError, match='EXACT_NATIVE_QUALITY_SUITE_REQUIRED'):
        retirement.require_source_scope(source_scope.inner, source_scope.entry, source_scope.semantic)


@pytest.mark.parametrize('error,passed,failed', [('VerificationCommandFailure', 4841, 13),
                                             ('ParseError', 4854, 0)])
def test_scope_admission_preserves_both_original_failure_outcomes(source_scope, error, passed, failed):
    source_scope.inner.update(status='FAILED', errorType=error,
        pythonTests={'found': 4878, 'passed': passed, 'failed': failed, 'skipped': 24})
    before = copy.deepcopy(source_scope.inner)
    retirement.require_source_scope(source_scope.inner, source_scope.entry, source_scope.semantic)
    assert source_scope.inner == before


@pytest.mark.parametrize('originals', [None, [], ['work/ci-evidence/tmp/pytest/real-database'],
    ['/home/ecs-user/doorhandle-ci/verification/unapproved'],
    ['work/semantic-mysql-fixture/../ci-evidence/tmp/pytest/data']])
def test_semantic_originals_cannot_move_into_pytest_or_escape_the_fixed_component(source_scope, originals):
    source_scope.semantic['privateOriginals'] = originals
    with pytest.raises(ValueError, match='SEMANTIC_COMPONENT_OUTSIDE_PYTEST_REQUIRED'):
        retirement.require_source_scope(source_scope.inner, source_scope.entry, source_scope.semantic)


def test_semantic_component_does_not_authorize_an_unapproved_entry(source_scope):
    source_scope.entry['release'] = 'ci-309-' + 'a' * 12
    with pytest.raises(ValueError, match='EXACT_SEMANTIC_SOURCE_SCOPE_REQUIRED'):
        retirement.require_source_scope(source_scope.inner, source_scope.entry, source_scope.semantic)


@pytest.mark.parametrize('release', RELEASES)
def test_new_batch_reuses_descriptor_removal_only_inside_each_exact_root(tmp_path, release):
    root = tmp_path / 'synthetic-ci'
    target = root / retirement.relative_target(release)
    target.mkdir(parents=True, mode=0o700)
    (target / 'synthetic-file').write_bytes(b'owned synthetic scratch')
    original = tmp_path / 'outside-original'
    original.write_bytes(b'preserved original')
    (target / 'outside-link').symlink_to(original)
    planned = retirement.inventory(target)
    events = []
    retirement.remove_owned_tree(root, target.relative_to(root).as_posix(), planned, events.append)
    assert not target.exists()
    assert original.read_bytes() == b'preserved original'
    assert any(event['phase'] == 'UNLINK' for event in events)


@pytest.mark.parametrize('relative', [
    'verification/ci-100-c44e23d06a69/checkout/work/ci-evidence/tmp/pytest',
    'verification/ci-266-aaaaaaaaaaaa/checkout/work/ci-evidence/tmp/pytest',
    'verification/ci-309-aaaaaaaaaaaa/checkout/work/ci-evidence/tmp/pytest',
    'verification/ci-307-dc8219bd868f/checkout/work/semantic-mysql-fixture',
    'verification/ci-307-dc8219bd868f/checkout/work/ci-evidence',
    'verification/ci-307-dc8219bd868f/checkout/work/ci-evidence/tmp/pytest/child',
])
def test_new_batch_cannot_delete_another_build_component_report_or_descendant(tmp_path, relative):
    root = tmp_path / 'synthetic-ci'
    target = root / relative
    target.mkdir(parents=True, mode=0o700)
    payload = target / 'keep'
    payload.write_bytes(b'not authorized')
    events = []
    with pytest.raises(ValueError, match='DELETION_TARGET_OUTSIDE_EXACT_SCOPE'):
        retirement.remove_owned_tree(root, relative, retirement.inventory(target), events.append)
    assert payload.read_bytes() == b'not authorized'
    assert events == []


def test_all_uid_probe_payload_selects_the_same_new_batch_before_the_root_worker(monkeypatch):
    metadata = [0o40700, 1000, 1000, 4096, 1, 20, 30, 1, 2]
    tree = {'rootMetadata': metadata, 'entries': []}
    cleanup = SimpleNamespace(docker_snapshot=lambda: [], locked_inodes=lambda: set())
    monkeypatch.setattr(retirement, 'LOADED_SOURCE', b'# synthetic source\n')
    monkeypatch.setattr(retirement, 'read_bounded', lambda *_args: retirement.LOADED_SOURCE)
    monkeypatch.setattr(retirement.secrets, 'token_hex', lambda _size: 'a' * 32)
    def response(_command, **kwargs):
        payload = kwargs['input']
        assert b"select_batch('source-pytest307308-20261114')" in payload
        assert payload.index(b'select_batch(') < payload.index(b'probe_processes(')
        result = {'status': 'QUIESCENT', 'scope': 'ALL_UIDS_EXACT_SOURCE_PYTEST_ROOT',
            'release': RELEASES[0], 'nonce': 'a' * 32,
            'keysSha256': retirement.hashlib.sha256(retirement.encoded([[30, 20]])).hexdigest(),
            'socketKeysSha256': retirement.hashlib.sha256(retirement.encoded([])).hexdigest(),
            'socketNamespacesChecked': 0}
        return SimpleNamespace(returncode=0, stdout=retirement.encoded(result), stderr=b'')
    monkeypatch.setattr(retirement.subprocess, 'run', response)
    assert retirement.reference_probe(RELEASES[0], tree, cleanup)['release'] == RELEASES[0]


@pytest.mark.parametrize('release,approved', [(RELEASES[0], True), (RELEASES[1], True),
    ('ci-100-c44e23d06a69', False), ('ci-266-aaaaaaaaaaaa', False), ('ci-309-aaaaaaaaaaaa', False)])
def test_root_worker_uses_the_selected_batch_with_no_real_process_namespace_scan(
        tmp_path, monkeypatch, release, approved):
    proc = tmp_path / 'synthetic-empty-proc'
    proc.mkdir(mode=0o700)
    request = {'release': release, 'keys': [[1, 2]], 'socketKeys': [], 'nonce': 'a' * 32}
    monkeypatch.setattr(retirement.os, 'getuid', lambda: 0)
    monkeypatch.setattr(retirement.os, 'geteuid', lambda: 0)
    def machine_id(path, *_args, **_kwargs):
        assert path == Path('/etc/machine-id')
        return retirement.IDENTITY['machineId']
    monkeypatch.setattr(Path, 'read_text', machine_id)
    original_scandir = os.scandir
    scans = []
    def synthetic_scan(path):
        assert Path(path) == proc, 'Only the fixture process namespace is admitted'
        scans.append(path)
        return original_scandir(path)
    monkeypatch.setattr(retirement.os, 'scandir', synthetic_scan)
    if approved:
        value = retirement.probe_processes(request, proc=proc)
        assert value['status'] == 'QUIESCENT' and value['release'] == release
        assert value['processesChecked'] == 0 and len(scans) == 1
    else:
        with pytest.raises(ValueError, match='UNAPPROVED_OLD_RELEASE'):
            retirement.probe_processes(request, proc=proc)
        assert scans == []


def test_cli_selects_a_closed_batch_before_reading_fixed_modules_and_authorization():
    source = (ROOT / 'script/jenkins/retire-source-pytest.py').read_text(encoding='utf-8')
    main = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    calls = [node for node in ast.walk(main) if isinstance(node, ast.Call)]
    choose = next(node for node in calls if isinstance(node.func, ast.Name) and node.func.id == 'select_batch')
    fixed = next(node for node in calls if isinstance(node.func, ast.Name) and node.func.id == 'fixed_modules')
    assert choose.lineno < fixed.lineno
    argument = next(node for node in calls if isinstance(node.func, ast.Attribute)
        and node.func.attr == 'add_argument' and node.args and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == '--batch')
    keywords = {node.arg: node.value for node in argument.keywords}
    assert ast.literal_eval(keywords['default']) == OLD_BATCH
    assert ast.dump(keywords['choices']) == ast.dump(ast.parse('tuple(BATCHES)', mode='eval').body)


def test_controller_selects_only_the_new_policy_and_does_not_archive_private_authorization():
    controller = (ROOT / 'script/jenkins/retire-source-pytest.ps1').read_text(encoding='utf-8')
    workflow = (ROOT / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf-8')
    assert "$env:NATIVE_RETENTION_POLICY -ceq 'SourcePytest307308'" in controller
    assert '$numbers=@(307,308)' in controller
    assert "$batch='source-pytest307308-20261114'" in controller
    assert "$binding+=\" --batch '$batch'\"" in controller
    assert "$authorizationName='source-pytest307308-authorization.json'" in controller
    assert "$local='artifacts/source-pytest307308'" in controller
    assert 'artifacts/source-pytest307308/*' in workflow
    for line in workflow.splitlines():
        if 'archiveArtifacts' in line:
            assert 'source-pytest307308-authorization.json' not in line
