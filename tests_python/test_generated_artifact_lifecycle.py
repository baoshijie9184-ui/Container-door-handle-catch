"""Generated-output lifecycle controls. Run only through Jenkins on ECS.

All filesystem operations target pytest-owned synthetic trees; container and
process snapshots are injected. These are not business-data migration tests.
"""
import copy
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import tarfile
import zipfile

import pytest

from tests_python import test_jenkins_ecs_build_cleanup as legacy

cleanup = legacy.cleanup
remote = legacy.remote
state = legacy.state
OLD, CURRENT, IDENTITY = legacy.OLD, legacy.CURRENT, legacy.IDENTITY


@pytest.fixture
def generated(state, monkeypatch):
    def no_external_process_scan(path, **kwargs):
        assert Path(path).is_relative_to(state.root)
    monkeypatch.setattr(cleanup, 'process_references', no_external_process_scan)
    return state


def request(state, *, current=False, result='FAILURE', targets='AUTO'):
    row = {'release': OLD, 'commit': 'a' * 40, 'sourceSha256': state.record['sourceSha256'],
           'targets': targets,
           'terminal': {'kind': 'CURRENT_POST' if current else 'ENROLLED_POST',
                        'result': result, 'evidenceArchived': True,
                        'remoteStagesClosed': True, 'completed': True}}
    return {'schema': 1, 'kind': cleanup.GENERATED_REQUEST_KIND,
            'currentRelease': OLD if current else CURRENT, 'identity': copy.deepcopy(IDENTITY),
            'protectedReleases': [], 'currentPost': current, 'candidates': [row]}


def make_plan(state, value=None, containers=()):
    return cleanup.build_plan(state.root, value or request(state), remote, list(containers))


@pytest.mark.parametrize('result', ['SUCCESS', 'UNSTABLE', 'FAILURE', 'ABORTED', 'NOT_BUILT'])
@pytest.mark.parametrize('current', [False, True])
def test_terminal_results_retire_without_business_pass_and_keep_originals(generated, result, current):
    before = {str(path): path.read_bytes() for path in generated.keep}
    value = request(generated, current=current, result=result)
    plan = make_plan(generated, value)
    assert not plan['skipped'] and plan['candidates'][0]['targets']
    receipt = cleanup.apply_plan(generated.root, value, plan, remote)
    assert receipt['retention']['status'] == 'SATISFIED'
    assert receipt['referenceScope'] == {'processScanUid': os.getuid(), 'containers': 'ALL_DOCKER_CONTAINERS'}
    assert not generated.classes.exists()
    assert before == {str(path): path.read_bytes() for path in generated.keep}


@pytest.fixture
def large_inner_report(generated):
    report = generated.evidence / 'receipt.json'
    inner = cleanup.read_json(report)
    inner['sourceRegression'] = {'status': 'FAILED'}
    # Valid JSON whitespace crosses the envelope cap without inventing commands
    # or requiring a 32 MiB allocation to exercise the report-file boundary.
    legacy.put(report, cleanup.canonical(inner) + b' ' * (remote.MAX_RECEIPT_BYTES + 1))
    regression = generated.evidence / 'source-regression/build' / legacy.MODULE
    generated.regression_classes = legacy.put(regression / 'classes/Regression.class', b'compiled-regression').parent
    generated.keep.append(legacy.put(regression / 'surefire-reports/TEST-Regression.xml',
                                    b'<testsuite><testcase name="original-regression"/></testsuite>'))
    legacy.seal(generated)
    assert remote.MAX_RECEIPT_BYTES < report.stat().st_size < remote.MAX_FILE_BYTES
    assert (generated.attempt / 'verification-receipt.json').stat().st_size < remote.MAX_RECEIPT_BYTES
    return generated


def test_generated_large_catalogued_inner_report_retires_both_compile_phases_and_keeps_originals(large_inner_report):
    state = large_inner_report
    before = legacy.preserved_bytes(state)
    value = request(state)
    plan = make_plan(state, value)
    assert not plan['skipped']
    paths = {target['path'] for candidate in plan['candidates'] for target in candidate['targets']}
    assert {path.relative_to(state.root).as_posix() for path in (state.classes, state.regression_classes)} <= paths
    receipt = cleanup.apply_plan(state.root, value, plan, remote)
    assert receipt['status'] == 'REMOVED' and receipt['retention']['status'] == 'SATISFIED'
    assert not state.classes.exists() and not state.regression_classes.exists()
    assert legacy.preserved_bytes(state) == before


def test_legacy_verified_keeps_its_inner_receipt_bound_for_the_same_large_report(large_inner_report):
    state = large_inner_report
    before = legacy.preserved_bytes(state)
    plan = cleanup.build_plan(state.root, state.request, remote, [])
    assert plan['candidates'] == []
    assert plan['skipped'][0]['reason'] == 'PATH_TYPE_LINK_OR_SIZE_INVALID'
    assert state.classes.exists() and state.regression_classes.exists()
    assert legacy.preserved_bytes(state) == before


def test_large_report_change_after_catalog_sealing_blocks_plan_and_deletion(large_inner_report):
    state = large_inner_report
    value = request(state)
    plan = make_plan(state, value)
    assert plan['candidates'] and not plan['skipped']
    report = state.evidence / 'receipt.json'
    before = legacy.preserved_bytes(state)
    changed = report.read_bytes()[:-1] + b'\n'  # Same size and JSON value, different authenticated bytes.
    legacy.put(report, changed)
    rejected = make_plan(state, value)
    assert not rejected['candidates'] and rejected['skipped'][0]['reason'] == 'ECS_ORIGINAL_REPORT_CHANGED'
    with pytest.raises(ValueError, match='PLAN_OR_ORIGINAL_EVIDENCE_CHANGED_NO_DELETION'):
        cleanup.apply_plan(state.root, value, plan, remote)
    assert state.classes.exists() and state.regression_classes.exists()
    before[report.relative_to(state.root).as_posix()] = changed
    assert legacy.preserved_bytes(state) == before
    assert not (state.root / 'inbox' / CURRENT / 'generated-cleanup-journal.jsonl').exists()


def test_generated_outer_envelope_still_rejects_over_its_original_bound(large_inner_report):
    state = large_inner_report
    state.record['diagnostics'] = 'x' * remote.MAX_RECEIPT_BYTES
    legacy.seal(state)  # The archive and custody agree; only the outer size is inadmissible.
    assert (state.attempt / 'verification-receipt.json').stat().st_size > remote.MAX_RECEIPT_BYTES
    before = legacy.preserved_bytes(state)
    plan = make_plan(state)
    assert not plan['candidates'] and plan['skipped'][0]['reason'] == 'PATH_TYPE_LINK_OR_SIZE_INVALID'
    assert state.classes.exists() and state.regression_classes.exists()
    assert legacy.preserved_bytes(state) == before


@pytest.mark.parametrize('field', ['evidenceArchived', 'remoteStagesClosed'])
def test_current_post_requires_archival_and_remote_closure_not_jenkins_completed(generated, field):
    value = request(generated, current=True)
    value['candidates'][0]['terminal'].pop('completed')
    assert make_plan(generated, value)['candidates']
    value['candidates'][0]['terminal'][field] = False
    assert not make_plan(generated, value)['candidates']
    assert generated.classes.exists()


@pytest.mark.parametrize('tag', ['ci-266-f6e062edc7b6', 'ci-117-8c898996cc28'])
def test_protected_recovery_and_public_keeper_never_reach_delete(generated, tag):
    target = {'kind': 'GENERATED_OCI_CACHE', 'path': cleanup.generated_paths(tag)['GENERATED_OCI_CACHE']}
    fd = os.open(generated.root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(ValueError, match='PROTECTED'):
            cleanup.remove_target(fd, target)
    finally:
        os.close(fd)


@pytest.mark.parametrize('reference', ['running', 'restarting', 'pid', 'stopped-mount'])
def test_active_tools_and_even_stopped_target_mounts_block(generated, reference):
    mount = [{'Type': 'bind', 'Source': str(generated.classes)}] if reference == 'stopped-mount' else []
    container = ['f' * 64, reference == 'running', reference == 'restarting',
                 99 if reference == 'pid' else 0, OLD, 'b' * 24, mount]
    plan = make_plan(generated, containers=[container])
    assert not plan['candidates'] and plan['skipped']


def test_stopped_builder_without_selected_file_mount_is_not_active_reference(generated):
    container = ['f' * 64, False, False, 0, OLD, 'b' * 24, []]
    assert make_plan(generated, containers=[container])['candidates']


def test_publication_pointer_protects_unpublished_pending_candidate(generated):
    legacy.put(generated.root / 'state/current-directory', str(generated.checkout).encode())
    assert not make_plan(generated)['candidates']


def test_inbox_only_preparation_failure_uses_existing_inbox_lock(generated, monkeypatch):
    # Do not create a pretend checkout for a preparation that never reached it.
    tag = 'ci-71-' + 'a' * 12
    inbox = generated.root / 'inbox' / tag
    source = inbox / 'source.tar.gz'
    legacy.package(source, {'README.md': b'fixed preparation source'}, 'a' * 40)
    checksum = cleanup.digest(source)
    legacy.put_json(inbox / 'candidate-build-tools/resource-summary.json', {
        'release': tag, 'commit': 'a' * 40, 'sourceSha256': checksum,
        'identity': IDENTITY, 'status': 'FAILED',
        'cleanup': {'builderStopped': False, 'creatorStopped': False}})
    legacy.put(inbox / 'candidate-build-tools/official-image.tar', b'synthetic public input')
    value = request(generated, targets=[{'kind': 'GENERATED_IMAGE_ARCHIVE',
                                         'path': cleanup.generated_paths(tag)['GENERATED_IMAGE_ARCHIVE']}])
    value['candidates'][0].update(release=tag, sourceSha256=checksum)
    value['candidates'][0]['terminal']['kind'] = 'JENKINS_HISTORY'
    monkeypatch.setattr(cleanup, 'generated_public_basis', lambda *args: {'fixture': True})
    monkeypatch.setattr(cleanup, 'generated_public_target', lambda *args: None)
    plan = make_plan(generated, value)
    assert not plan['skipped'] and plan['candidates']
    receipt = cleanup.apply_plan(generated.root, value, plan, remote)
    assert receipt['retention']['status'] == 'SATISFIED'
    assert not (generated.root / 'verification' / tag).exists()
    assert cleanup.read_json(inbox / 'candidate-build-tools/resource-summary.json')['cleanup']['builderStopped'] is False


def test_node_modules_symlinks_unlinked_without_following_external_source(generated):
    target = legacy.add_dependencies(generated)
    external = legacy.put(generated.root / 'preserved-source.js', b'original')
    (target / '.bin').mkdir()
    (target / '.bin/tool').symlink_to(external)
    value = request(generated)
    plan = make_plan(generated, value)
    assert any(t['kind'] == 'GENERATED_NODE_MODULES' for c in plan['candidates'] for t in c['targets'])
    receipt = cleanup.apply_plan(generated.root, value, plan, remote)
    assert receipt['retention']['status'] == 'SATISFIED' and not target.exists()
    assert external.read_bytes() == b'original'


def test_synthetic_root_handles_readonly_and_hardlink_without_modifying_original(generated):
    root = generated.checkout / cleanup.PYTEST_TMP_SUFFIX
    original = legacy.put(generated.root / 'preserved-payload', b'original')
    temporary = legacy.put(root / 'readonly/file', b'regenerated')
    os.link(original, root / 'linked-negative-case')
    (root / 'readonly').chmod(0o500)
    target = {'path': root.relative_to(generated.root).as_posix(), 'kind': 'GENERATED_PYTEST_ROOT'}
    target.update(cleanup.generated_inventory(generated.root, target))
    cleanup.generated_tree_helper().remove_owned_tree(generated.root, target['path'], target, lambda event: None, generated=True)
    assert not root.exists() and original.read_bytes() == b'original'
    assert stat.S_IMODE(original.stat().st_mode) == 0o600


def test_legacy_synthetic_api_does_not_gain_new_targets(generated):
    root = generated.checkout / cleanup.PYTEST_TMP_SUFFIX
    legacy.put(root / 'file', b'generated')
    with pytest.raises(ValueError, match='EXACT_SCOPE'):
        cleanup.generated_tree_helper().remove_owned_tree(generated.root, root.relative_to(generated.root).as_posix(), {}, lambda event: None)


def test_failed_python_with_complete_original_report_is_reclaimed_only_by_new_mode(generated, monkeypatch):
    cases = legacy.add_pytest_cases(generated, monkeypatch, damage='xml-failure', recipe='legacy')
    inner = cleanup.read_json(generated.evidence / 'receipt.json')
    inner.update(status='FAILED', pythonTests={'found': 3, 'passed': 1, 'failed': 1, 'skipped': 1})
    inner['commands'][-1]['exitCode'] = 1
    legacy.put_json(generated.evidence / 'receipt.json', inner)
    tools = cleanup.read_json(generated.evidence / 'tool-runtime.json')
    tools['commands'][0]['exitCode'] = tools['commands'][0]['cleanup']['exitCode'] = 1
    legacy.put_json(generated.evidence / 'tool-runtime.json', tools)
    generated.record.update(status='FAILED', verificationExitCode=1)
    legacy.seal(generated)
    old = cleanup.evidence_binding(generated.root, generated.request['candidates'][0], IDENTITY, remote)
    assert old['pytestTmp']['status'] == 'SKIPPED'
    value = request(generated)
    plan = make_plan(generated, value)
    assert any(t['kind'] == 'GENERATED_PYTEST_ROOT' for c in plan['candidates'] for t in c['targets'])
    receipt = cleanup.apply_plan(generated.root, value, plan, remote)
    assert receipt['retention']['status'] == 'SATISFIED' and not cases.base.exists()
    assert generated.archive.exists() and (generated.evidence / 'python.xml').exists()


def failed_pytest_without_summary(state, monkeypatch, *, recipe='legacy'):
    """The archived #225/#229 runner raises before its count assignment."""
    cases = legacy.add_pytest_cases(state, monkeypatch, damage='xml-failure', recipe=recipe)
    inner = cleanup.read_json(state.evidence / 'receipt.json')
    inner.pop('pythonTests'); inner.pop('selectedPythonSuites')
    inner.update(status='FAILED', pythonTemporaryCleanup={'status': 'RETAINED_PYTHON_NOT_PASSED'})
    inner['commands'][-1]['exitCode'] = 1
    legacy.put_json(state.evidence / 'receipt.json', inner)
    tools = cleanup.read_json(state.evidence / 'tool-runtime.json')
    tools['commands'][0]['exitCode'] = tools['commands'][0]['cleanup']['exitCode'] = 1
    legacy.put_json(state.evidence / 'tool-runtime.json', tools)
    state.record.update(status='FAILED', verificationExitCode=1)
    legacy.seal(state)
    return cases


@pytest.mark.parametrize('xml_result', ['failure', 'error'])
def test_historical_failed_runner_uses_archived_xml_without_inventing_original_count_summary(generated, monkeypatch, xml_result):
    state = generated; cases = failed_pytest_without_summary(state, monkeypatch)
    xml = state.evidence / 'python.xml'
    if xml_result == 'error':
        legacy.put(xml, xml.read_bytes().replace(b'<failure/>', b'<error/>'))
        legacy.seal(state)
    before = legacy.preserved_bytes(state)
    value = authorize_historical_outputs(request(state, targets=[{
        'kind': 'GENERATED_PYTEST_ROOT', 'path': cases.base.relative_to(state.root).as_posix()}]))
    binding = cleanup.generated_binding(state.root, value['candidates'][0], IDENTITY, remote)
    assert binding['pytestTmp']['status'] == 'PROVEN'
    assert binding['pytestTmp']['pythonTests'] == {'found': 3, 'passed': 1, 'failed': 1, 'skipped': 1}
    assert binding['pytestTmp']['pythonCountsSource'] == 'ARCHIVED_FAILED_XML'
    old = cleanup.evidence_binding(state.root, state.request['candidates'][0], IDENTITY, remote)
    assert old['pytestTmp']['status'] == 'SKIPPED'
    plan = make_plan(state, value)
    assert not plan['skipped'] and len(plan['candidates']) == 1
    result = cleanup.apply_plan(state.root, value, plan, remote)
    assert result['status'] == 'REMOVED' and not cases.base.exists()
    assert result['retention']['status'] == 'SATISFIED' and legacy.preserved_bytes(state) == before
    original = cleanup.read_json(state.evidence / 'receipt.json')
    assert original['status'] == 'FAILED' and 'pythonTests' not in original and 'selectedPythonSuites' not in original
    assert cleanup.read_json(state.attempt / 'verification-receipt.json')['status'] == 'FAILED'


@pytest.mark.parametrize('damage', ['counts-null', 'counts-mismatch', 'selected-summary', 'status-pass',
    'missing-disposition', 'native-disposition', 'inner-exit-zero', 'inner-exit-interrupted', 'tools-exit-zero',
    'no-failed-test', 'different-reviewed-runner', 'missing-original-report', 'wrong-basetemp', 'changed-archived-xml'])
def test_missing_failed_summary_does_not_replace_required_original_failure_proofs(generated, monkeypatch, damage):
    state = generated
    cases = failed_pytest_without_summary(state, monkeypatch,
        recipe='middleware' if damage == 'different-reviewed-runner' else 'legacy')
    inner = cleanup.read_json(state.evidence / 'receipt.json')
    tools = cleanup.read_json(state.evidence / 'tool-runtime.json')
    if damage == 'counts-null': inner['pythonTests'] = None
    elif damage == 'counts-mismatch': inner['pythonTests'] = {'found': 3, 'passed': 2, 'failed': 0, 'skipped': 1}
    elif damage == 'selected-summary': inner['selectedPythonSuites'] = {}
    elif damage == 'status-pass': inner['status'] = 'PASS'
    elif damage == 'missing-disposition': inner.pop('pythonTemporaryCleanup')
    elif damage == 'native-disposition': inner['pythonTemporaryCleanup'] = {'status': 'RETAINED_NATIVE_EVIDENCE'}
    elif damage == 'inner-exit-zero': inner['commands'][-1]['exitCode'] = 0
    elif damage == 'inner-exit-interrupted': inner['commands'][-1]['exitCode'] = 2
    elif damage == 'tools-exit-zero':
        tools['commands'][0]['exitCode'] = tools['commands'][0]['cleanup']['exitCode'] = 0
    elif damage == 'no-failed-test':
        xml = state.evidence / 'python.xml'; legacy.put(xml, xml.read_bytes().replace(b'<failure/>', b''))
    elif damage == 'missing-original-report': state.reports.remove('reports/python.xml')
    elif damage == 'wrong-basetemp': tools['commands'][0]['argumentsSha256'] = '0' * 64
    legacy.put_json(state.evidence / 'receipt.json', inner)
    legacy.put_json(state.evidence / 'tool-runtime.json', tools)
    legacy.seal(state)
    if damage == 'changed-archived-xml':
        xml = state.evidence / 'python.xml'; legacy.put(xml, xml.read_bytes() + b'\n')
    before = legacy.preserved_bytes(state)
    value = authorize_historical_outputs(request(state, targets=[{
        'kind': 'GENERATED_PYTEST_ROOT', 'path': cases.base.relative_to(state.root).as_posix()}]))
    plan = make_plan(state, value)
    assert not plan['candidates'] and plan['skipped'] and cases.base.exists()
    if damage == 'changed-archived-xml':
        assert plan['skipped'][0]['reason'] == 'ECS_ORIGINAL_REPORT_CHANGED'
    else:
        binding = cleanup.generated_binding(state.root, value['candidates'][0], IDENTITY, remote)
        reason = ('PYTEST_SOURCE_SCOPE_REQUIRED' if damage == 'missing-original-report' else
                  'PYTEST_TOOL_COMMAND_PROVENANCE_MISSING' if damage in ('tools-exit-zero', 'wrong-basetemp') else
                  'PYTEST_REPORT_NOT_PASS')
        assert binding['pytestTmp'] == {'status': 'SKIPPED', 'reason': reason}
    assert legacy.preserved_bytes(state) == before


@pytest.fixture
def native_pytest(generated, monkeypatch):
    cases = legacy.add_pytest_cases(generated, monkeypatch, recipe='legacy')
    inner = cleanup.read_json(generated.evidence / 'receipt.json')
    inner.update(scopeKind='mysql', fixtureProperties=['doorhandle.test.jdbc-url'],
                 fixtureManifest={'version': 2, 'sha256': 'f' * 64}, wholeMigrationRequested=True,
                 pythonTemporaryCleanup={'status': 'RETAINED_NATIVE_EVIDENCE'})
    legacy.put_json(generated.evidence / 'receipt.json', inner)
    claim_path = generated.attempt / '.verification-claimed/claim.json'
    claim = cleanup.read_json(claim_path)
    claim['scope'] = 'mysql'
    legacy.put_json(claim_path, claim)
    generated.record.update(scope='mysql', fixtureReadinessValidated=True)
    generated.native_pytest = cases.base
    legacy.seal(generated)
    return generated


@pytest.mark.parametrize(('status', 'result'), [('PASS', 'SUCCESS'), ('FAILED', 'FAILURE')])
@pytest.mark.parametrize('current', [False, True])
def test_mysql_native_evidence_is_preserved_outside_generated_scope(native_pytest, status, result, current):
    state = native_pytest
    inner = cleanup.read_json(state.evidence / 'receipt.json')
    inner['status'] = status
    legacy.put_json(state.evidence / 'receipt.json', inner)
    state.record.update(status=status, verificationExitCode=0 if status == 'PASS' else 1)
    legacy.seal(state)
    originals = legacy.preserved_bytes(state)
    contents = {path: path.read_bytes() for path in state.native_pytest.rglob('*') if path.is_file()}
    value = request(state, current=current, result=result)
    plan = make_plan(state, value)
    expected = [{'release': OLD, 'path': state.native_pytest.relative_to(state.root).as_posix(),
                 'kind': 'NATIVE_PYTEST_EVIDENCE', 'reason': 'RETAINED_NATIVE_EVIDENCE',
                 'allocatedBytes': None, 'measurement': 'NOT_MEASURED'}]
    assert not plan['skipped'] and not plan['unresolved']
    assert plan['retentionScope'] == 'DISPOSABLE_GENERATED_OUTPUTS' and plan['preservedEvidence'] == expected
    assert all(target['kind'] != 'GENERATED_PYTEST_ROOT' for row in plan['candidates'] for target in row['targets'])
    receipt = cleanup.apply_plan(state.root, value, plan, remote)
    assert receipt['status'] == 'REMOVED' and receipt['retention']['status'] == 'SATISFIED'
    assert receipt['retention']['scope'] == 'DISPOSABLE_GENERATED_OUTPUTS'
    assert receipt['retention']['preservedEvidence'] == expected
    assert receipt['retention']['knownRemainingAllocatedBytes'] == 0
    assert all(not target['path'].startswith(expected[0]['path']) for target in receipt['deleted'])
    assert not state.classes.exists() and state.native_pytest.is_dir()
    assert all(path.read_bytes() == raw for path, raw in contents.items())
    assert legacy.preserved_bytes(state) == originals
    assert cleanup.read_json(state.evidence / 'receipt.json')['status'] == status
    assert cleanup.read_json(state.attempt / 'verification-receipt.json')['status'] == status
    assert plan['request']['candidates'][0]['terminal']['result'] == result


@pytest.mark.parametrize('damage', ['missing-report', 'duplicate-python', 'java-only', 'untyped-migration',
    'untyped-worker', 'missing-disposition', 'source-envelope', 'fixture-manifest', 'fixture-properties',
    'duplicate-tool-command', 'tool-arguments', 'cleanup-pid', 'cleanup-removed'])
def test_mysql_retention_requires_complete_typed_native_evidence(native_pytest, damage):
    state = native_pytest
    inner = cleanup.read_json(state.evidence / 'receipt.json')
    if damage == 'missing-report': state.reports.remove('reports/python.xml')
    elif damage == 'duplicate-python': inner['commands'].append(copy.deepcopy(inner['commands'][-1]))
    elif damage == 'java-only': inner['javaOnly'] = 0
    elif damage == 'untyped-migration': inner['wholeMigrationRequested'] = 1
    elif damage == 'untyped-worker': inner['workerMysqlRequested'] = 0
    elif damage == 'missing-disposition': inner.pop('pythonTemporaryCleanup')
    elif damage == 'fixture-manifest': inner['fixtureManifest'] = None
    elif damage == 'fixture-properties': inner['fixtureProperties'] = 'not-a-list'
    elif damage in ('duplicate-tool-command', 'tool-arguments', 'cleanup-pid', 'cleanup-removed'):
        tools = cleanup.read_json(state.evidence / 'tool-runtime.json')
        command = tools['commands'][0]
        if damage == 'duplicate-tool-command': tools['commands'].append(copy.deepcopy(command))
        elif damage == 'tool-arguments': command['argumentsSha256'] = '0' * 64
        elif damage == 'cleanup-pid': command['cleanup']['pid'] = 1
        else: command['cleanup']['removed'] = False
        legacy.put_json(state.evidence / 'tool-runtime.json', tools)
    elif damage == 'source-envelope':
        state.record['scope'] = 'source'
        claim_path = state.attempt / '.verification-claimed/claim.json'
        claim = cleanup.read_json(claim_path)
        claim['scope'] = 'source'
        legacy.put_json(claim_path, claim)
    legacy.put_json(state.evidence / 'receipt.json', inner)
    legacy.seal(state)
    originals = legacy.preserved_bytes(state)
    value = request(state)
    plan = make_plan(state, value)
    assert not plan['preservedEvidence']
    assert plan['unresolved'][0]['reason'] == 'PYTEST_SOURCE_SCOPE_REQUIRED'
    receipt = cleanup.apply_plan(state.root, value, plan, remote)
    assert receipt['retention']['status'] == 'BLOCKED' and receipt['retention']['budgetVerdict'] == 'UNKNOWN'
    assert state.native_pytest.is_dir() and legacy.preserved_bytes(state) == originals


def test_native_pytest_root_link_does_not_receive_preserved_classification(native_pytest):
    state = native_pytest
    retained = state.native_pytest.with_name('retained-native-data')
    state.native_pytest.rename(retained)
    state.native_pytest.symlink_to(retained, target_is_directory=True)
    originals = legacy.preserved_bytes(state)
    value = request(state)
    plan = make_plan(state, value)
    assert plan['skipped'] and not plan['preservedEvidence']
    receipt = cleanup.apply_plan(state.root, value, plan, remote)
    assert receipt['retention']['status'] == 'BLOCKED'
    assert state.native_pytest.is_symlink() and retained.is_dir() and state.classes.exists()
    assert legacy.preserved_bytes(state) == originals


def test_preserved_native_evidence_does_not_hide_other_unresolved_outputs(native_pytest):
    state = native_pytest
    cache = legacy.put(state.checkout / cleanup.NPM_CACHE_SUFFIX / 'unproven.bin', b'retained cache')
    value = request(state)
    plan = make_plan(state, value)
    assert plan['preservedEvidence'] and plan['unresolved']
    receipt = cleanup.apply_plan(state.root, value, plan, remote)
    assert receipt['retention']['status'] == 'BLOCKED' and receipt['retention']['budgetVerdict'] == 'UNKNOWN'
    assert state.native_pytest.is_dir() and cache.read_bytes() == b'retained cache'


def test_preserved_native_evidence_does_not_hide_deletion_failure(native_pytest, monkeypatch):
    state = native_pytest
    value = request(state)
    plan = make_plan(state, value)
    def fail_delete(*args): raise OSError('Synthetic generated-output failure')
    monkeypatch.setattr(cleanup, 'remove_target', fail_delete)
    receipt = cleanup.apply_plan(state.root, value, plan, remote)
    assert receipt['status'] == 'PARTIAL_FAILURE' and receipt['retention']['status'] == 'BLOCKED'
    assert receipt['retention']['preservedEvidence'] == plan['preservedEvidence']
    assert state.native_pytest.is_dir() and state.classes.exists()


def test_public_oci_mixed_business_file_is_not_admitted(generated):
    directory = generated.inbox / 'candidate-build-tools'
    legacy.put_json(directory / 'official-layer-measurements.json', {
        'configDigest': 'sha256:e164dcf5aa147a29659dea4e2e6b909db541c2dfe0b512dac38a2ffaf063fc18',
        'imageId': 'sha256:e164dcf5aa147a29659dea4e2e6b909db541c2dfe0b512dac38a2ffaf063fc18',
        'manifestDigest': 'sha256:' + 'a'*64, 'layers': [{'blobDigest': 'sha256:'+'b'*64}]})
    path = legacy.put(directory / 'official-oci/original.sql', b'business data')
    target = {'path': path.parent.relative_to(generated.root).as_posix(), 'kind': 'GENERATED_OCI_CACHE'}
    target.update(cleanup.generated_inventory(generated.root, target))
    with pytest.raises(ValueError, match='UNRECOGNIZED_FILE'):
        cleanup.generated_public_target(generated.root, {'release': OLD}, target, {})
    assert path.read_bytes() == b'business data'


@pytest.mark.parametrize('reason', ['PYTEST_SOURCE_RECIPE_MISSING', 'GENERATED_SOCKET_REFERENCE_UNRESOLVED'])
def test_unresolved_generated_objects_are_never_reported_as_empty(generated, monkeypatch, reason):
    root = generated.checkout / cleanup.PYTEST_TMP_SUFFIX
    legacy.put(root / 'negative/file', b'synthetic')
    original = cleanup.generated_binding
    def binding(*args):
        result = original(*args)
        result['pytestTmp'] = {'status': 'SKIPPED', 'reason': reason}
        return result
    monkeypatch.setattr(cleanup, 'generated_binding', binding)
    value = request(generated)
    plan = make_plan(generated, value)
    receipt = cleanup.apply_plan(generated.root, value, plan, remote)
    assert receipt['retention']['status'] == 'BLOCKED'
    assert receipt['retention']['budgetVerdict'] == 'UNKNOWN'
    assert receipt['retention']['unresolvedTargets'][0]['reason'] == reason
    assert root.exists() and not generated.classes.exists()


def test_stale_inventory_is_refused_before_deletion(generated):
    value = request(generated)
    plan = make_plan(generated, value)
    legacy.put(generated.classes / 'new.class', b'new compilation')
    with pytest.raises(ValueError, match='PLAN_OR_ORIGINAL_EVIDENCE_CHANGED'):
        cleanup.apply_plan(generated.root, value, plan, remote)
    assert generated.classes.exists()


def test_failed_historical_candidate_does_not_block_other_eligible_rows(generated):
    value = request(generated)
    bad = copy.deepcopy(value['candidates'][0])
    bad['release'] = 'ci-69-' + 'a' * 12
    # This attempt really has generated bytes, unlike an already absent build.
    # Its declared original checksum is wrong, so it must be refused and kept.
    bad['sourceSha256'] = '0' * 64
    inbox = generated.root / 'inbox' / bad['release']
    source = inbox / 'source.tar.gz'
    legacy.package(source, {'README.md': b'preserved historical source'}, bad['commit'])
    retained = legacy.put(inbox / 'candidate-build-tools/official-oci/unproven-layer', b'retained input')
    original_bytes = source.read_bytes()
    value['candidates'].append(bad)
    plan = make_plan(generated, value)
    assert [item['release'] for item in plan['candidates']] == [OLD]
    assert plan['skipped'] == [{'release': bad['release'], 'reason': 'GENERATED_ORIGINAL_SOURCE_CHANGED', 'targets': 'AUTO'}]
    assert all(item['release'] != bad['release'] for item in plan['absent'])
    receipt = cleanup.apply_plan(generated.root, value, plan, remote)
    assert receipt['status'] == 'REMOVED' and receipt['retention']['status'] == 'BLOCKED'
    assert receipt['skipped'] == plan['skipped'] and receipt['retention']['unmeasuredCandidates'] == 1
    assert receipt['retention']['budgetVerdict'] == 'UNKNOWN'
    assert not generated.classes.exists()
    assert source.read_bytes() == original_bytes and retained.read_bytes() == b'retained input'


def add_source_package_outputs(state, *, damage=None):
    """Bind real SOURCE failure evidence to small, regenerable Maven outputs."""
    source = state.inbox / 'source.tar.gz'
    with tarfile.open(source, 'r:gz') as archive:
        files = {entry.name: archive.extractfile(entry).read() for entry in archive}
    files['pom.xml'] = files['pom.xml'].replace(b'<version>1.0.0</version>', b'<version>0.0.1-SNAPSHOT</version>')
    files['pom.xml'] = files['pom.xml'].replace(b'</modules>',
        b'<module>doorhandle-module-app</module><module>doorhandle-server</module></modules>')
    files['doorhandle-module-app/pom.xml'] = (
        b'<project><artifactId>doorhandle-module-app</artifactId><build><plugins><plugin>'
        b'<artifactId>maven-dependency-plugin</artifactId><executions><execution>'
        b'<phase>prepare-package</phase><goals><goal>copy-dependencies</goal></goals>'
        b'<configuration><outputDirectory>${project.build.directory}/dependency</outputDirectory>'
        b'</configuration></execution></executions></plugin></plugins></build></project>')
    if damage == 'pom-routing':
        files['doorhandle-module-app/pom.xml'] = files['doorhandle-module-app/pom.xml'].replace(
            b'${project.build.directory}/dependency', b'${project.basedir}/business-files')
    files['doorhandle-server/pom.xml'] = b'<project><artifactId>doorhandle-server</artifactId></project>'
    legacy.package(source, files, 'a' * 40)
    source_sha = cleanup.digest(source)
    manifest = cleanup.read_json(state.manifest)
    manifest['sourceSha256'] = source_sha
    legacy.put_json(state.manifest, manifest)
    claim_path = state.attempt / '.verification-claimed/claim.json'
    claim = cleanup.read_json(claim_path)
    claim['sourceSha256'] = source_sha
    legacy.put_json(claim_path, claim)
    tools = cleanup.read_json(state.evidence / 'tool-runtime.json')
    tools.update(sourceSha256=source_sha, manifestSha256=cleanup.digest(state.manifest))
    tools['cleanup']['manifestSha256'] = cleanup.digest(state.manifest)
    legacy.put_json(state.evidence / 'tool-runtime.json', tools)
    inner = cleanup.read_json(state.evidence / 'receipt.json')
    inner.update(status='FAILED', javaOnly=False, wholeMigrationRequested=False,
                 workerMysqlRequested=False, fixtureProperties=[], fixtureManifest=None)
    if damage == 'unfinished-command': inner['commands'][0].pop('finishedAt')
    legacy.put_json(state.evidence / 'receipt.json', inner)
    # Both archives are genuine ZIP/JAR shapes, not executable application code.
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, 'w') as archive:
        archive.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\n')
    kinds = ('GENERATED_SOURCE_DEPENDENCIES', 'GENERATED_SOURCE_JAR')
    paths = {kind: state.root / cleanup.generated_paths(OLD)[kind] for kind in kinds}
    dependency = legacy.put(paths[kinds[0]] / 'synthetic-library-1.0.jar', blob.getvalue())
    legacy.put(paths[kinds[1]], blob.getvalue())
    if damage == 'jar-signature': legacy.put(paths[kinds[1]], b'not a generated JAR')
    log = '[INFO] Copying ' + dependency.name + ' to ' + str(dependency) + '\n'
    log += '[INFO] Building jar: ' + str(paths[kinds[1]]) + '\n'
    if damage == 'missing-output-log': log = '[INFO] unrelated build diagnostics\n'
    legacy.put(state.evidence / 'java-suite-001.log', log.encode())
    state.reports.append('reports/java-suite-001.log')
    state.record.update(sourceSha256=source_sha, status='FAILED', verificationExitCode=1)
    legacy.seal(state)
    state.keep.append(state.evidence / 'java-suite-001.log')
    return paths


def source_package_request(state, paths):
    value = request(state, targets=[{'kind': kind, 'path': path.relative_to(state.root).as_posix()}
                                    for kind, path in paths.items()])
    value['candidates'][0]['terminal']['kind'] = 'REMOTE_VERIFICATION'
    return value


def test_failed_source_package_retires_exact_outputs_and_preserves_old_contract(generated, monkeypatch):
    paths = add_source_package_outputs(generated)
    # Real packaged JARs exceed the 32 MiB control-file cap. A sparse tail
    # exercises the output inventory boundary without allocating a large buffer.
    with paths['GENERATED_SOURCE_JAR'].open('r+b') as stream:
        stream.truncate(cleanup.MAX_PLAN + 1)
    monkeypatch.setattr(cleanup, 'GENERATED_SOURCE_PACKAGE_HISTORY', frozenset({OLD}))
    before = legacy.preserved_bytes(generated)
    old = cleanup.build_plan(generated.root, generated.request, remote, [])
    assert old['candidates'] and not old['skipped']
    assert all(target['path'] not in {path.relative_to(generated.root).as_posix() for path in paths.values()}
               for candidate in old['candidates'] for target in candidate['targets'])
    value = source_package_request(generated, paths)
    plan = make_plan(generated, value)
    assert not plan['skipped']
    assert {target['kind'] for candidate in plan['candidates'] for target in candidate['targets']} == set(paths)
    jar_target = next(target for candidate in plan['candidates'] for target in candidate['targets']
                      if target['kind'] == 'GENERATED_SOURCE_JAR')
    assert jar_target['bytes'] == cleanup.MAX_PLAN + 1
    receipt = cleanup.apply_plan(generated.root, value, plan, remote)
    assert receipt['status'] == 'REMOVED' and receipt['retention']['status'] == 'SATISFIED'
    assert all(not path.exists() for path in paths.values())
    assert legacy.preserved_bytes(generated) == before
    assert cleanup.read_json(generated.evidence / 'receipt.json')['status'] == 'FAILED'
    assert cleanup.read_json(generated.attempt / 'verification-receipt.json')['status'] == 'FAILED'


def test_future_current_post_auto_discovers_source_packages_without_historical_enrollment(generated):
    paths = add_source_package_outputs(generated)
    assert OLD not in cleanup.GENERATED_SOURCE_PACKAGE_HISTORY
    value = request(generated, current=True)
    plan = make_plan(generated, value)
    assert not plan['skipped']
    assert set(paths) <= {target['kind'] for candidate in plan['candidates'] for target in candidate['targets']}
    receipt = cleanup.apply_plan(generated.root, value, plan, remote)
    assert receipt['retention']['status'] == 'SATISFIED'
    assert all(not path.exists() for path in paths.values())


def test_unapproved_historical_source_packages_are_kept(generated):
    paths = add_source_package_outputs(generated)
    value = source_package_request(generated, paths)
    plan = make_plan(generated, value)
    assert not plan['candidates']
    assert plan['skipped'][0]['reason'] == 'SOURCE_PACKAGE_HISTORY_NOT_APPROVED'
    assert all(path.exists() for path in paths.values())


@pytest.mark.parametrize(('damage', 'reason'), [
    ('pom-routing', 'SOURCE_DEPENDENCY_OUTPUT_ROUTING_NOT_PROVEN'),
    ('missing-output-log', 'SOURCE_DEPENDENCY_COPY_NOT_RECORDED'),
    ('unfinished-command', 'BUILD_HAS_UNSETTLED_COMMANDS'),
    ('jar-signature', 'SOURCE_PACKAGE_JAR_SIGNATURE_INVALID'),
])
def test_source_package_requires_archived_routing_and_completed_output_proof(generated, monkeypatch, damage, reason):
    paths = add_source_package_outputs(generated, damage=damage)
    monkeypatch.setattr(cleanup, 'GENERATED_SOURCE_PACKAGE_HISTORY', frozenset({OLD}))
    plan = make_plan(generated, source_package_request(generated, paths))
    assert not plan['candidates'] and plan['skipped']
    assert plan['skipped'][0]['reason'] == reason
    assert all(path.exists() for path in paths.values())


def test_source_dependency_directory_mixed_with_sql_is_not_retired(generated, monkeypatch):
    paths = add_source_package_outputs(generated)
    original = legacy.put(paths['GENERATED_SOURCE_DEPENDENCIES'] / 'original.sql', b'original SQL')
    monkeypatch.setattr(cleanup, 'GENERATED_SOURCE_PACKAGE_HISTORY', frozenset({OLD}))
    plan = make_plan(generated, source_package_request(generated, paths))
    assert not plan['candidates']
    assert plan['skipped'][0]['reason'] == 'SOURCE_DEPENDENCY_OUTPUT_NOT_CLOSED'
    assert original.read_bytes() == b'original SQL' and all(path.exists() for path in paths.values())


def test_stopped_container_mount_still_protects_source_package(generated, monkeypatch):
    paths = add_source_package_outputs(generated)
    monkeypatch.setattr(cleanup, 'GENERATED_SOURCE_PACKAGE_HISTORY', frozenset({OLD}))
    container = ['f' * 64, False, False, 0, OLD, 'b' * 24,
                 [{'Type': 'bind', 'Source': str(paths['GENERATED_SOURCE_JAR'])}]]
    plan = make_plan(generated, source_package_request(generated, paths), [container])
    assert not plan['candidates'] and plan['skipped'][0]['reason'] == 'CONTAINER_REFERENCES_GENERATED_TARGET'
    assert all(path.exists() for path in paths.values())


def test_source_package_change_after_plan_refuses_before_any_deletion(generated, monkeypatch):
    paths = add_source_package_outputs(generated)
    monkeypatch.setattr(cleanup, 'GENERATED_SOURCE_PACKAGE_HISTORY', frozenset({OLD}))
    value = source_package_request(generated, paths)
    plan = make_plan(generated, value)
    jar = paths['GENERATED_SOURCE_JAR']
    legacy.put(jar, jar.read_bytes() + b'new-build-output')
    with pytest.raises(ValueError, match='PLAN_OR_ORIGINAL_EVIDENCE_CHANGED'):
        cleanup.apply_plan(generated.root, value, plan, remote)
    assert all(path.exists() for path in paths.values())


def test_generated_source_jar_cannot_address_recovery_point(generated):
    target = {'kind': 'GENERATED_SOURCE_JAR',
              'path': cleanup.generated_paths('ci-266-f6e062edc7b6')['GENERATED_SOURCE_JAR']}
    fd = os.open(generated.root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(ValueError, match='PROTECTED'):
            cleanup.remove_target(fd, target)
    finally:
        os.close(fd)


def test_enrollment_discovers_closed_attempt_without_requiring_same_job_final_state(generated):
    value = cleanup.discover_generated_request(generated.root, OLD, 'a' * 40,
        generated.record['sourceSha256'], IDENTITY, 'ABORTED')
    assert value['candidates'][0]['terminal']['kind'] == 'CURRENT_POST'
    marker = cleanup.read_json(generated.inbox / 'generated-terminal.json')
    assert marker['candidate']['terminal']['kind'] == 'ENROLLED_POST'
    assert marker['candidate']['terminal']['completed'] is True


def test_pipeline_parameters_and_archival_precede_terminal_cleanup():
    root = legacy.ROOT
    pipeline = (root / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf8')
    configure = (root / 'script/jenkins/configure-local.groovy').read_text(encoding='utf8')
    controller = (root / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    reclaim = (root / 'script/jenkins/reclaim-build-outputs.ps1').read_text(encoding='utf8')
    for name in ('GENERATED_ARTIFACTS_ONLY', 'GENERATED_RETENTION_MANIFEST'):
        assert name in pipeline and name in configure and name in controller
    assert pipeline.index("env.CI_EVIDENCE_ARCHIVED = 'true'") < pipeline.index('-Action CleanupGeneratedArtifacts')
    assert '-Mode Terminal -GeneratedArtifacts' in controller
    assert controller.index("if ($env:GENERATED_ARTIFACTS_ONLY -ceq 'true')") < controller.index("-CanonicalBatch FailedNative -SshOptions")
    assert "'SUCCESS','UNSTABLE','FAILURE','ABORTED','NOT_BUILT'" in reclaim
    assert '$context.generatedRequest = @{bytes=' in reclaim
    assert '$context.generatedRequest = @{schema=' not in reclaim
    assert 'generated-cleanup-request.json\"))' in reclaim
    assert "if data['mode']!='Terminal'" in reclaim
    assert "$result.retention.scope -cne 'DISPOSABLE_GENERATED_OUTPUTS'" in reclaim
    assert "'FAILED_OR_UNKNOWN','RETAINED_OUTPUTS_REQUIRE_ACTION'" in reclaim
    assert "catchError(buildResult: 'FAILURE', stageResult: 'FAILURE')" in pipeline


def test_request_payload_not_embedded_in_windows_ssh_command():
    # Shape matches the real 41-release/52-target admission, without private data.
    rows = [{'release': 'ci-' + str(i) + '-' + 'a'*12, 'targets': [
        {'path': 'inbox/ci-' + str(i) + '-' + 'a'*12 + '/candidate-build-tools/official-oci',
         'kind': 'GENERATED_OCI_CACHE'}], 'proof': 'x'*500} for i in range(1,42)]
    raw = json.dumps({'candidates': rows}).encode()
    descriptor = {'bytes': len(raw), 'sha256': 'a'*64}
    assert len(raw) > 23000 and len(json.dumps(descriptor)) < 120
    assert len(raw) < 1024**2


def maintenance_package_paths(generated):
    """Read the versioned source-only package selection, not a test copy of it."""
    pipeline = (legacy.ROOT / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    block = re.search(r"(?ms)^if \(\$Action -ceq 'PackageSourceOnly'\) \{\n(.*?)^\}\n", pipeline)
    assert block, 'The source-only package must have its own guarded action block'
    package = block[1]
    base = re.search(r"(?m)^    \$maintenancePaths = @\(([^\n]+)\)$", package)
    assert base, 'Maintenance must explicitly select its small fixed helper closure'
    paths = re.findall(r"'([^']+)'", base[1])
    if generated:
        selected = re.search(
            r"(?m)^    elseif \(\$env:GENERATED_ARTIFACTS_ONLY -ceq 'true'\) \{ \$maintenancePaths \+= @\(([^\n]+)\) \}$",
            package)
        assert selected, 'Generated maintenance must package its dynamic tree helper'
        paths.extend(re.findall(r"'([^']+)'", selected[1]))
    assert "'--output=artifacts/source.tar.gz', $commit) + $maintenancePaths" in package
    return paths


def inspect_packaged_helpers(tmp_path, monkeypatch, *, generated, damage=None):
    paths = maintenance_package_paths(generated)
    if damage == 'missing-helper': paths.remove('script/jenkins/retire-source-pytest.py')
    if damage == 'missing-permission-helper': paths.remove('script/jenkins/repair-ci-evidence-permissions.py')
    source = tmp_path / 'source.tar.gz'
    legacy.package(source, {name: (legacy.ROOT / name).read_bytes() for name in paths}, 'a' * 40)
    controller = (legacy.ROOT / 'script/jenkins/reclaim-build-outputs.ps1').read_text(encoding='utf8')
    reader = controller.split("$archiveReader = @'\n", 1)[1].split("\n'@", 1)[0]
    monkeypatch.setattr(sys, 'argv', ['fixed-helper-reader', str(source),
        'b' * 40 if damage == 'wrong-commit' else 'a' * 40, str(generated)])
    # Execute only the fixed byte-inspection controller. Packaged helpers stay
    # opaque bytes: no application import, remote access or cleanup takes place.
    exec(compile(reader, '<fixed-helper-reader>', 'exec'), {'__name__': '__main__'})


@pytest.mark.parametrize('generated', [False, True])
def test_actual_maintenance_package_contains_its_required_helper_closure(tmp_path, monkeypatch, capsys, generated):
    inspect_packaged_helpers(tmp_path, monkeypatch, generated=generated)
    result = json.loads(capsys.readouterr().out)
    expected = {'script/jenkins/cleanup-ecs-builds.py', 'script/jenkins/verify-remote.py'}
    if generated: expected.update(('script/jenkins/retire-source-pytest.py', 'script/jenkins/repair-ci-evidence-permissions.py'))
    assert set(result) == expected
    for name, descriptor in result.items():
        raw = (legacy.ROOT / name).read_bytes()
        assert descriptor == {'bytes': len(raw), 'sha256': cleanup.sha(raw)}


@pytest.mark.parametrize(('damage', 'error'), [
    ('missing-helper', 'Required cleanup helper missing from fixed source archive'),
    ('missing-permission-helper', 'Required cleanup helper missing from fixed source archive'),
    ('wrong-commit', 'Fixed helper commit differs'),
])
def test_generated_package_rejects_missing_helper_and_wrong_commit_separately(tmp_path, monkeypatch, damage, error):
    with pytest.raises(ValueError, match=error):
        inspect_packaged_helpers(tmp_path, monkeypatch, generated=True, damage=damage)


@pytest.fixture
def permission_request(generated, monkeypatch):
    state = generated
    state.cache = legacy.add_npm_cache(state)
    value = request(state, targets=[{'kind': 'NPM_CACHE', 'path': cleanup.generated_paths(OLD)['NPM_CACHE']}])
    value['candidates'][0]['terminal']['kind'] = 'REMOTE_VERIFICATION'
    changes = []
    for path in (state.checkout / 'work', state.checkout / 'work/tool-home', state.evidence / 'receipt.json',
                 state.evidence / 'frontend-install.log'):
        directory = path.is_dir(); before, after = (0o775, 0o700) if directory else (0o664, 0o600)
        path.chmod(before); info = path.stat()
        changes.append(dict(path=path.relative_to(state.root).as_posix(), directory=directory,
            beforeMode=before, afterMode=after, nlink=info.st_nlink, device=info.st_dev,
            inode=info.st_ino, uid=info.st_uid, gid=info.st_gid))
    value['candidates'][0]['permissionRepairs'] = changes
    (state.root / 'inbox' / CURRENT).mkdir(mode=0o700, parents=True, exist_ok=True)
    monkeypatch.setattr(cleanup, 'docker_snapshot', lambda: [])
    return state, value


@pytest.mark.parametrize('apply', [False, True])
def test_exact_owner_permission_repair_preserves_report_bytes_and_only_then_admits_cache(permission_request, apply):
    state, value = permission_request
    before = legacy.preserved_bytes(state); original_owned = cleanup.owned
    denied = make_plan(state, value)
    assert not denied['candidates'] and denied['skipped'][0]['reason'] == 'PATH_NOT_OWNED_OR_WRITABLE_BY_OTHERS'
    result = cleanup.repair_generated_permissions(state.root, value, remote, apply=apply)
    assert result['status'] == ('REPAIRED' if apply else 'PLANNED') and result['deletedTargets'] == 0
    assert cleanup.owned is original_owned and legacy.preserved_bytes(state) == before and state.cache.exists()
    for change in value['candidates'][0]['permissionRepairs']:
        assert stat.S_IMODE((state.root / change['path']).stat().st_mode) == change['afterMode' if apply else 'beforeMode']
    if apply:
        plan = make_plan(state, value)
        assert not plan['skipped'] and len(plan['candidates'][0]['targets']) == 1
        receipt = cleanup.apply_plan(state.root, value, plan, remote)
        assert receipt['status'] == 'REMOVED' and not state.cache.exists()
        assert legacy.preserved_bytes(state) == before


@pytest.mark.parametrize('damage', ['inode', 'uid', 'gid', 'nlink', 'unsafe-mode', 'duplicate', 'outside',
    'target-itself', 'symlink', 'source', 'report', 'invalid-envelope', 'unregistered-ancestor', 'protected', 'active-reference', 'missing-cache-proof'])
def test_permission_repair_refuses_incomplete_evidence_or_widened_paths_before_chmod(permission_request, monkeypatch, damage):
    state, value = permission_request; row = value['candidates'][0]; changes = row['permissionRepairs']
    original_owned = cleanup.owned; calls = []
    if damage in ('inode', 'uid', 'gid', 'nlink'): changes[0][damage] += 1
    elif damage == 'unsafe-mode': changes[0]['afterMode'] = 0o777
    elif damage == 'duplicate': changes.append(copy.deepcopy(changes[0]))
    elif damage == 'outside': changes[0]['path'] = 'state/production-pointer'
    elif damage == 'target-itself': changes[0]['path'] = row['targets'][0]['path']
    elif damage == 'symlink':
        leaf = state.evidence / 'frontend-install.log'; leaf.rename(leaf.with_suffix('.original')); leaf.symlink_to(leaf.with_suffix('.original'))
    elif damage == 'source': row['sourceSha256'] = '0' * 64
    elif damage == 'report': (state.evidence / 'frontend-install.log').write_bytes(b'changed retained report')
    elif damage == 'invalid-envelope':
        state.record['status'] = 'UNRECOGNIZED'; legacy.seal(state)
    elif damage == 'unregistered-ancestor': (state.checkout / 'work/tool-home/npm-cache').chmod(0o775)
    elif damage == 'protected': value['protectedReleases'].append(OLD)
    elif damage == 'active-reference':
        monkeypatch.setattr(cleanup, 'docker_snapshot', lambda: [
            ('f' * 64, False, False, 0, 'another-build', '', [{'Type': 'bind', 'Source': str(state.cache)}])])
    else:
        monkeypatch.setattr(cleanup, 'npm_cache_provenance', lambda *args, **kwargs: {'status': 'SKIPPED', 'reason': 'MISSING_ORIGINAL_PRODUCER'})
    monkeypatch.setattr(os, 'fchmod', lambda *args: calls.append(args))
    result = cleanup.repair_generated_permissions(state.root, value, remote)
    assert result['status'] == 'PARTIAL_FAILURE' and result['deletedTargets'] == 0 and not calls
    assert cleanup.owned is original_owned and state.cache.exists()


def test_permission_repair_supports_catalogued_logs_larger_than_control_json_limit(permission_request):
    state, value = permission_request
    log = state.evidence / 'frontend-install.log'; log.write_bytes(b'original log\n' * 100000)
    legacy.seal(state)
    # Sealing keeps the same inode, but restores private modes for written controls.
    for change in value['candidates'][0]['permissionRepairs']:
        (state.root / change['path']).chmod(change['beforeMode'])
    before = log.read_bytes()
    result = cleanup.repair_generated_permissions(state.root, value, remote)
    assert result['status'] == 'REPAIRED' and log.read_bytes() == before


def test_permission_repair_requires_explicit_historical_request(permission_request):
    state, value = permission_request
    for damage in ('terminal', 'missing-selection'):
        changed = copy.deepcopy(value)
        if damage == 'terminal': changed['currentPost'] = True
        else: changed['candidates'][0].pop('permissionRepairs')
        with pytest.raises(ValueError, match='EXPLICIT_MAINTENANCE'):
            cleanup.repair_generated_permissions(state.root, changed, remote)
    assert not (state.root / 'inbox' / CURRENT / 'generated-cleanup-permissions-journal.jsonl').exists()


def test_controller_repairs_explicit_modes_before_readonly_plan_and_collects_both_originals():
    source = (legacy.ROOT / 'script/jenkins/reclaim-build-outputs.ps1').read_text(encoding='utf8')
    assert '$repairGeneratedPermissions = $false' in source
    assert "$row.ContainsKey('permissionRepairs')" in source
    assert 'Permission repair cannot be mixed with unrelated generated targets' in source
    assert source.index("'$helper' repair-permissions") < source.index("'$helper' plan") < source.index("'$helper' apply")
    for name in ('generated-cleanup-permissions.json', 'generated-cleanup-permissions-journal.jsonl'):
        assert "Copy-ReclaimEvidence '" + name + "'" in source
    assert 'permissionRepairAttempted = $permissionRepairAttempted' in source


def authorize_historical_outputs(value):
    value['historicalOutputsAuthorization'] = {'taskThreadId': '01a1de46-3b28-7a21-84e7-4f403268fa01',
        'scope': 'historical-finished-ci-outputs', 'sourceSha256': 'd' * 64}
    value['candidates'][0]['terminal']['kind'] = 'REMOTE_VERIFICATION'
    return value


@pytest.mark.parametrize('kind', ['COMPILED_DIRECTORY', 'GENERATED_NODE_MODULES', 'GENERATED_SOURCE_DEPENDENCIES'])
def test_current_exact_authority_reuses_old_compile_and_dependency_primitives_without_old_number_lists(generated, kind):
    state = generated
    if kind == 'COMPILED_DIRECTORY': target = state.classes
    elif kind == 'GENERATED_NODE_MODULES': target = legacy.add_dependencies(state)
    else: target = add_source_package_outputs(state)[kind]
    value = request(state, targets=[{'kind': kind, 'path': target.relative_to(state.root).as_posix()}])
    value['candidates'][0]['terminal']['kind'] = 'REMOTE_VERIFICATION'
    assert not make_plan(state, value)['candidates']
    authorize_historical_outputs(value)
    before = legacy.preserved_bytes(state)
    plan = make_plan(state, value)
    assert len(plan['candidates']) == 1 and not plan['skipped'] and len(plan['candidates'][0]['targets']) == 1
    receipt = cleanup.apply_plan(state.root, value, plan, remote)
    assert receipt['status'] == 'REMOVED' and not target.exists()
    assert legacy.preserved_bytes(state) == before


@pytest.mark.parametrize('damage', ['wrong-task', 'wrong-scope', 'missing-source', 'extra-authority', 'current-post', 'automatic'])
def test_historical_authority_cannot_be_borrowed_or_widened_to_auto(generated, damage):
    value = authorize_historical_outputs(request(generated, targets=[{'kind': 'COMPILED_DIRECTORY',
        'path': generated.classes.relative_to(generated.root).as_posix()}]))
    proof = value['historicalOutputsAuthorization']
    if damage == 'wrong-task': proof['taskThreadId'] = 'another-task'
    elif damage == 'wrong-scope': proof['scope'] = 'all-finished-builds'
    elif damage == 'missing-source': proof['sourceSha256'] = ''
    elif damage == 'extra-authority': proof['allowArbitraryPath'] = True
    elif damage == 'current-post': value['currentPost'] = True
    else: value['candidates'][0]['targets'] = 'AUTO'
    with pytest.raises(ValueError, match='HISTORICAL_OUTPUTS_EXACT_TASK_AUTHORITY_REQUIRED'):
        make_plan(generated, value)
    assert generated.classes.exists()


@pytest.mark.parametrize('damage', ['suite', 'module', 'reports', 'checkout-root', 'absolute', 'dot-alias', 'source', 'protected', 'install-proof'])
def test_historical_exact_leaves_still_require_the_original_producer_and_preserve_reports(generated, damage):
    state = generated; target = state.classes; kind = 'COMPILED_DIRECTORY'
    if damage == 'suite': target = legacy.put(state.evidence / 'java-suites/suite-999' / legacy.MODULE / 'classes/A.class', b'unknown suite').parent
    elif damage == 'module': target = legacy.put(state.classes.parent.parent / 'doorhandle-unknown/classes/A.class', b'unknown module').parent
    elif damage == 'reports': target = state.classes.parent / 'surefire-reports'
    elif damage == 'checkout-root': target = state.checkout
    elif damage == 'install-proof':
        target = legacy.put(state.checkout / 'frontend/node_modules/object', b'no archived install').parent
        kind = 'GENERATED_NODE_MODULES'
    value = authorize_historical_outputs(request(state, targets=[{'kind': kind, 'path': target.relative_to(state.root).as_posix()}]))
    if damage == 'absolute': value['candidates'][0]['targets'][0]['path'] = str(target)
    elif damage == 'dot-alias': value['candidates'][0]['targets'][0]['path'] = './' + value['candidates'][0]['targets'][0]['path']
    if damage == 'source': value['candidates'][0]['sourceSha256'] = '0' * 64
    elif damage == 'protected': value['protectedReleases'].append(OLD)
    before = legacy.preserved_bytes(state); plan = make_plan(state, value)
    assert not plan['candidates'] and plan['skipped'] and legacy.preserved_bytes(state) == before


def test_controller_binds_new_historical_scope_to_original_user_approval_not_old_projection():
    source = (legacy.ROOT / 'script/jenkins/reclaim-build-outputs.ps1').read_text(encoding='utf8')
    block = source.split("if ($inputManifest.ContainsKey('historicalOutputsAuthorizationFile')) {", 1)[1].split('$kindMap =', 1)[0]
    for predicate in ("$approval.approved -eq $true", "$approval.requiresExactManifest -eq $true",
                      "$approval.requiresFinishedBuild -eq $true", "$approval.requiresPreservedOriginals -eq $true",
                      "$approval.requiresNoActiveReferences -eq $true", "$approval.allowsArbitraryPath -eq $false"):
        assert predicate in block
    assert 'cleanup-authorization-20261115.json' in block and "Get-FileHash -LiteralPath $authPath" in block
    assert '$requestValue.historicalOutputsAuthorization=$historicalOutputsAuthorization' in source


def test_explicit_historical_permission_repair_can_cover_the_same_builds_cache_and_compiled_leaf(permission_request):
    state, value = permission_request
    value['candidates'][0]['targets'].append({'kind': 'COMPILED_DIRECTORY', 'path': state.classes.relative_to(state.root).as_posix()})
    authorize_historical_outputs(value)
    before = legacy.preserved_bytes(state)
    result = cleanup.repair_generated_permissions(state.root, value, remote)
    assert result['status'] == 'REPAIRED' and result['deletedTargets'] == 0
    plan = make_plan(state, value)
    assert not plan['skipped'] and len(plan['candidates'][0]['targets']) == 2
    assert state.cache.exists() and state.classes.exists() and legacy.preserved_bytes(state) == before


@pytest.mark.parametrize('damage', [None, 'missing-proof', 'wrong-root'])
def test_historical_source_pytest_uses_existing_exact_basetemp_provenance_and_keeps_original_reports(generated, monkeypatch, damage):
    state = generated; cases = legacy.add_pytest_cases(state, monkeypatch, recipe='legacy')
    target = cases.base if damage != 'wrong-root' else state.evidence / 'tmp'
    value = authorize_historical_outputs(request(state, targets=[{'kind': 'GENERATED_PYTEST_ROOT', 'path': target.relative_to(state.root).as_posix()}]))
    if damage == 'missing-proof':
        monkeypatch.setattr(cleanup, 'pytest_temp_provenance', lambda *args, **kwargs: {'status': 'SKIPPED', 'reason': 'ORIGINAL_PRODUCER_MISSING'})
    before = legacy.preserved_bytes(state); plan = make_plan(state, value)
    if damage:
        assert not plan['candidates'] and plan['skipped'] and cases.base.exists()
    else:
        assert not plan['skipped'] and len(plan['candidates'][0]['targets']) == 1
        result = cleanup.apply_plan(state.root, value, plan, remote)
        assert result['status'] == 'REMOVED' and not cases.base.exists()
    assert legacy.preserved_bytes(state) == before


def test_historical_source_authority_does_not_reclassify_native_mysql_temporary_evidence(native_pytest):
    state = native_pytest
    value = authorize_historical_outputs(request(state, targets=[{'kind': 'GENERATED_PYTEST_ROOT', 'path': state.native_pytest.relative_to(state.root).as_posix()}]))
    before = legacy.preserved_bytes(state); plan = make_plan(state, value)
    assert not plan['candidates'] and plan['skipped'][0]['reason'] == 'HISTORICAL_PYTEST_REQUIRES_PROVEN_SOURCE_PRODUCER'
    assert state.native_pytest.exists() and legacy.preserved_bytes(state) == before


@pytest.fixture
def synthetic_native_case(native_pytest, monkeypatch):
    state = native_pytest
    source = state.inbox / 'source.tar.gz'
    with tarfile.open(source, 'r:gz') as archive:
        members = {entry.name: archive.extractfile(entry).read() for entry in archive}
    name = 'tests_python/test_owned_synthetic.py'
    members[name] = b'def test_owned_copy(tmp_path):\n    (tmp_path / "copy").write_bytes(b"synthetic")\n'
    support = 'tests_python/owned_fixture.py'
    members[support] = b'# synthetic fixture source\n'
    members['tests_python/conftest.py'] = b'# isolated fixture source\n'
    for member in (name, support, 'tests_python/conftest.py', 'script/jenkins/ecs-tool-runtime.py'):
        legacy.put(state.checkout / member, members[member])
    legacy.package(source, members, 'a' * 40)
    checksum = cleanup.digest(source)
    manifest = cleanup.read_json(state.manifest); manifest['sourceSha256'] = checksum
    legacy.put_json(state.manifest, manifest)
    claim_file = state.attempt / '.verification-claimed/claim.json'
    claim = cleanup.read_json(claim_file); claim['sourceSha256'] = checksum; legacy.put_json(claim_file, claim)
    tools = cleanup.read_json(state.evidence / 'tool-runtime.json')
    tools.update(sourceSha256=checksum, manifestSha256=cleanup.digest(state.manifest))
    tools['cleanup']['manifestSha256'] = cleanup.digest(state.manifest)
    legacy.put_json(state.evidence / 'tool-runtime.json', tools)
    legacy.put(state.evidence / 'python.xml', b'<testsuite>'
        b'<testcase classname="tests_python.test_owned_synthetic" name="test_owned_copy"/>'
        b'<testcase classname="tests_python.test_real_native" name="test_real_native"><failure/></testcase></testsuite>')
    state.record['sourceSha256'] = checksum
    legacy.seal(state)
    monkeypatch.setattr(cleanup, 'SYNTHETIC_PYTEST_SOURCES', {OLD: ('a' * 40, checksum)})
    monkeypatch.setattr(cleanup, 'SYNTHETIC_PYTEST_MODULES', frozenset({name}))
    monkeypatch.setattr(cleanup, 'SYNTHETIC_PYTEST_SUPPORT', frozenset({support}))
    state.synthetic_case = legacy.put(state.native_pytest / 'test_owned_copy0/copy', b'synthetic').parent
    state.retained_native = legacy.put(state.native_pytest / 'test_real_native0/diagnostic', b'unique native diagnostic')
    state.synthetic_request = authorize_historical_outputs(request(state, targets=[{
        'kind': 'GENERATED_SYNTHETIC_PYTEST_CASE', 'path': state.synthetic_case.relative_to(state.root).as_posix()}]))
    return state


def test_exact_native_synthetic_pass_case_reuses_ordinary_tree_and_keeps_parent_and_originals(synthetic_native_case):
    state = synthetic_native_case; before = legacy.preserved_bytes(state)
    plan = make_plan(state, state.synthetic_request)
    assert not plan['skipped'] and len(plan['candidates'][0]['targets']) == 1
    basis = plan['candidates'][0]['bases'][state.synthetic_case.relative_to(state.root).as_posix()]
    assert basis['producerModule'] == 'tests_python/test_owned_synthetic.py' and basis['matchingPassedCases'] == 1
    receipt = cleanup.apply_plan(state.root, state.synthetic_request, plan, remote)
    journal = state.root / 'inbox' / CURRENT / 'generated-cleanup-journal.jsonl'
    assert receipt['status'] == 'REMOVED', [json.loads(line) for line in journal.read_text().splitlines()]
    assert not state.synthetic_case.exists()
    assert state.native_pytest.is_dir() and state.retained_native.read_bytes() == b'unique native diagnostic'
    assert legacy.preserved_bytes(state) == before


@pytest.mark.parametrize('damage', ['no-authority', 'unreviewed-source', 'root', 'nested', 'other-case',
    'absolute', 'dot-alias', 'runner', 'executor', 'producer', 'support', 'failed', 'skipped', 'unreviewed-module',
    'ambiguous-module', 'missing-function', 'wrong-basetemp', 'running-tool'])
def test_native_synthetic_case_requires_exact_fixed_producer_and_original_pass_before_inventory(synthetic_native_case, monkeypatch, damage):
    state = synthetic_native_case; value = copy.deepcopy(state.synthetic_request); target = value['candidates'][0]['targets'][0]
    if damage == 'no-authority': value.pop('historicalOutputsAuthorization')
    elif damage == 'unreviewed-source': monkeypatch.setattr(cleanup, 'SYNTHETIC_PYTEST_SOURCES', {})
    elif damage in ('root', 'nested', 'other-case', 'absolute', 'dot-alias'):
        target['path'] = {'root': state.native_pytest.relative_to(state.root).as_posix(),
            'nested': (state.synthetic_case / 'copy').relative_to(state.root).as_posix(),
            'other-case': state.retained_native.parent.relative_to(state.root).as_posix(),
            'absolute': str(state.synthetic_case), 'dot-alias': './' + target['path']}[damage]
    elif damage in ('runner', 'executor', 'producer', 'support'):
        path = {'runner': state.checkout / 'script/jenkins/verify-ecs.py',
                'executor': state.inbox / 'tool-runtime/executor.py',
                'producer': state.checkout / 'tests_python/test_owned_synthetic.py',
                'support': state.checkout / 'tests_python/owned_fixture.py'}[damage]
        legacy.put(path, path.read_bytes() + b'\n# changed\n')
    elif damage in ('failed', 'skipped', 'unreviewed-module', 'ambiguous-module', 'missing-function'):
        path = state.evidence / 'python.xml'; raw = path.read_bytes()
        if damage in ('failed', 'skipped'):
            tag = b'failure' if damage == 'failed' else b'skipped'
            raw = raw.replace(b'name="test_owned_copy"/>', b'name="test_owned_copy"><' + tag + b'/></testcase>')
        elif damage == 'unreviewed-module': raw = raw.replace(b'tests_python.test_owned_synthetic', b'tests_python.test_unreviewed')
        elif damage == 'ambiguous-module': raw = raw.replace(b'</testsuite>', b'<testcase classname="tests_python.test_unreviewed" name="test_owned_copy"/></testsuite>')
        else:
            raw = raw.replace(b'test_owned_copy', b'test_not_in_source')
            renamed = state.synthetic_case.with_name('test_not_in_source0'); state.synthetic_case.rename(renamed)
            state.synthetic_case = renamed; target['path'] = renamed.relative_to(state.root).as_posix()
        legacy.put(path, raw); legacy.seal(state)
    else:
        path = state.evidence / 'tool-runtime.json'; tools = cleanup.read_json(path)
        if damage == 'wrong-basetemp': tools['commands'][0]['argumentsSha256'] = '0' * 64
        else: tools['commands'][0]['cleanup']['pid'] = 1
        legacy.put_json(path, tools); legacy.seal(state)
    monkeypatch.setattr(cleanup, 'tree_inventory', lambda *_: pytest.fail('Invalid producer reached target inventory'))
    result = make_plan(state, value)
    assert not result['candidates'] and result['skipped'] and state.synthetic_case.exists()
    assert state.retained_native.read_bytes() == b'unique native diagnostic'


@pytest.mark.parametrize('damage', ['symlink', 'hardlink', 'fifo', 'writable-file', 'writable-parent', 'writable-root'])
def test_native_synthetic_case_keeps_all_nonordinary_or_unowned_bytes(synthetic_native_case, damage):
    state = synthetic_native_case; child = state.synthetic_case / 'unsafe'
    if damage == 'symlink': child.symlink_to(state.retained_native)
    elif damage == 'hardlink': os.link(state.retained_native, child)
    elif damage == 'fifo': os.mkfifo(child, 0o600)
    elif damage == 'writable-file': (state.synthetic_case / 'copy').chmod(0o664)
    elif damage == 'writable-parent': state.native_pytest.chmod(0o775)
    else: state.synthetic_case.chmod(0o775)
    result = make_plan(state, state.synthetic_request)
    assert not result['candidates'] and result['skipped'] and state.synthetic_case.is_dir()
    assert state.retained_native.read_bytes() == b'unique native diagnostic'


@pytest.mark.parametrize('reference', ['container', 'process'])
def test_native_synthetic_case_does_not_bypass_existing_active_reference_checks(synthetic_native_case, monkeypatch, reference):
    state = synthetic_native_case; containers = []
    if reference == 'container':
        containers = [('f' * 64, False, False, 0, 'unrelated', '',
                       [{'Type': 'bind', 'Source': str(state.synthetic_case)}])]
    else:
        def refuse(path, **kwargs):
            assert path == state.checkout and kwargs == {'include_inbox': True}
            raise ValueError('ACTIVE_FILE_DESCRIPTOR_REFERENCES_OLD_CHECKOUT')
        monkeypatch.setattr(cleanup, 'process_references', refuse)
    result = make_plan(state, state.synthetic_request, containers)
    assert not result['candidates'] and result['skipped'] and state.synthetic_case.exists()


@pytest.mark.parametrize('damage', ['source', 'report', 'target'])
def test_native_synthetic_case_apply_rebinds_all_originals_and_inventory(synthetic_native_case, damage):
    state = synthetic_native_case; value = state.synthetic_request; plan = make_plan(state, value)
    assert plan['candidates'] and not plan['skipped']
    path = {'source': state.inbox / 'source.tar.gz', 'report': state.evidence / 'python.xml',
            'target': state.synthetic_case / 'copy'}[damage]
    path.write_bytes(path.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='PLAN_OR_ORIGINAL_EVIDENCE_CHANGED_NO_DELETION'):
        cleanup.apply_plan(state.root, value, plan, remote)
    assert state.synthetic_case.exists() and state.retained_native.exists()


def test_native_synthetic_case_cannot_contain_a_catalogued_original_report(synthetic_native_case):
    state = synthetic_native_case
    row = state.synthetic_request['candidates'][0]
    binding = cleanup.generated_binding(state.root, row, IDENTITY, remote)
    report = legacy.put(state.synthetic_case / 'original.xml', b'<testsuite><testcase name="original"/></testsuite>')
    name = 'reports/' + report.relative_to(state.evidence).as_posix()
    descriptor = {'path': name, 'bytes': report.stat().st_size, 'sha256': cleanup.digest(report)}
    # The real envelope forbids tmp reports before target admission. Keep that
    # boundary and exercise the independent overlap guard with a bound caller.
    record = copy.deepcopy(state.record); record['reportFiles'].append(descriptor)
    with pytest.raises(remote.VerificationError, match='Unexpected or duplicate report file'):
        cleanup.receipt_catalog(record, remote, generated=True)
    binding['catalog'][name] = descriptor
    with pytest.raises(ValueError, match='GENERATED_TARGET_CONTAINS_ORIGINAL_REPORT'):
        cleanup.historical_generated_target(state.root, binding, row, row['targets'][0], remote)
    assert report.is_file() and state.retained_native.exists()


@pytest.mark.parametrize('path', ['parent', 'nested', 'sibling', 'unreviewed-release', 'absolute', 'dot-alias'])
def test_native_synthetic_delete_primitive_rejects_noncase_and_unreviewed_paths(synthetic_native_case, path):
    state = synthetic_native_case
    selected = state.synthetic_request['candidates'][0]['targets'][0]
    invalid = {'parent': state.native_pytest.relative_to(state.root).as_posix(),
        'nested': selected['path'] + '/nested', 'sibling': selected['path'].replace('/tmp/pytest/', '/tmp/other/'),
        'unreviewed-release': selected['path'].replace(OLD, 'ci-71-' + 'a' * 12),
        'absolute': str(state.synthetic_case), 'dot-alias': './' + selected['path']}[path]
    fd = os.open(state.root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(ValueError, match='DELETION_TARGET_OUTSIDE_COMPILED_ALLOWLIST'):
            cleanup.remove_target(fd, {'kind': 'GENERATED_SYNTHETIC_PYTEST_CASE', 'path': invalid})
    finally: os.close(fd)
    assert state.synthetic_case.is_dir() and state.retained_native.is_file()


@pytest.mark.parametrize(('count', 'kind', 'historical', 'allowed'), [
    (128, 'COMPILED_DIRECTORY', True, True), (129, 'COMPILED_DIRECTORY', True, False),
    (1536, 'GENERATED_SYNTHETIC_PYTEST_CASE', True, True), (1537, 'GENERATED_SYNTHETIC_PYTEST_CASE', True, False),
    (129, 'GENERATED_SYNTHETIC_PYTEST_CASE', False, False), (129, 'MIXED', True, False)])
def test_only_exact_synthetic_case_batches_get_the_independent_count_bound(count, kind, historical, allowed):
    targets = [{'kind': 'GENERATED_SYNTHETIC_PYTEST_CASE' if kind == 'MIXED' else kind, 'path': str(i)} for i in range(count)]
    if kind == 'MIXED': targets[-1]['kind'] = 'COMPILED_DIRECTORY'
    if allowed: cleanup.generated_target_selection(targets, historical)
    else:
        with pytest.raises(ValueError, match='GENERATED_TARGET_SELECTION_INVALID'):
            cleanup.generated_target_selection(targets, historical)
    assert cleanup.MAX_TARGET_CANONICAL == 16 * 1024 ** 2 and cleanup.MAX_PLAN == 32 * 1024 ** 2


def test_synthetic_case_controller_mapping_is_only_inside_current_historical_authority():
    source = (legacy.ROOT / 'script/jenkins/reclaim-build-outputs.ps1').read_text(encoding='utf8')
    line = next(line for line in source.splitlines() if "$kindMap.SYNTHETIC_PYTEST_CASE=" in line)
    assert "if ($null -ne $historicalOutputsAuthorization)" in line
    assert "='GENERATED_SYNTHETIC_PYTEST_CASE'" in line
    assert cleanup.SYNTHETIC_PYTEST_SOURCES == {
        'ci-337-1918c12cd441': ('1918c12cd4419670896cf07e88378c81ea03123a', 'fe062e06868fd588319e7975d38de5b4c569383bde3a131d458ae11908206b2c'),
        'ci-341-46c1dd6b1079': ('46c1dd6b107914d2d000cefbb6372fba8f7fdd97', '4d8cb28ce15c380db020d7694119cd3d116406410101bc13260f60fd73d2e498'),
        'ci-366-2fb71393e3a3': ('2fb71393e3a3c0f1412040633c04db180b2fd2da', 'c628f6efc5e2c23764e9f2886b6dd9796e2fc5a46c697925da6bd226382fadd6'),
        'ci-375-b15e66d4e7e3': ('b15e66d4e7e39b9022c8fcfde8928d1d30231358', '84d4696ec2cfcc8acee67389441c5126af2482d37a2bc9101d19d618fad7fd62'),
        'ci-381-4a2dd6159b77': ('4a2dd6159b770ad9f9d3423d22cbf0dafdb3559b', '7acbfec491ff5016bb35347f1902b6fdfa882d425f3fbe47192df1337e29a364'),
        'ci-383-5400127dd813': ('5400127dd8134c871130f0ea0295384572c103da', '8dc22715f23782fabc357707757509db60dffbc607b8f1344260708b7aa4fc04'),
        'ci-396-55028c090f80': ('55028c090f80d872d59bd02b3321860c8fdca7d9', '412680344bed649bc7d21708b0c834bb7c49edf00420a4724d868e12d11db649'),
        'ci-401-d516ee078dbb': ('d516ee078dbbaa7c3f8cb9015f0734541307b370', '979427716b670355bb0200af40270b0ce0302d2e216f40cf53016f34d9919971'),
        'ci-404-f6d14c20c474': ('f6d14c20c474b96f0c930729fb4e937cf9c8e247', '7222acd6587a5fb95e389673cb4f964e5d87ca6766d4c1ec18c5393c3265bb9c'),
        'ci-411-07cdfca58a85': ('07cdfca58a851c513cff697db337ce48e4c5a2ec', '8a144ff04266c43359c63b13dd64523f4e672fff521643c90b6138824aef8c11'),
        'ci-413-6bc217a3d954': ('6bc217a3d954476ddb30ab95c7078dd8a9088201', 'e4794fc8b72de7db9d93e741b045009679c382cd27e30f45a88452dc7c7ab475'),
    }
    executor = 'tests_python/fixtures/ci-producer-7f8b992d/ecs-tool-runtime.py.txt'
    watcher = 'tests_python/fixtures/ci-389-watch-start-failure.json'
    assert cleanup.SYNTHETIC_PYTEST_SOURCE_SUPPORT == {
        'ci-396-55028c090f80': frozenset({executor}),
        'ci-401-d516ee078dbb': frozenset({executor, watcher}),
        'ci-404-f6d14c20c474': frozenset({executor, watcher}),
        'ci-411-07cdfca58a85': frozenset({executor, watcher}),
        'ci-413-6bc217a3d954': frozenset({executor, watcher}),
    }
    assert 'tests_python/test_compact_migration_orchestration_ecs.py' not in cleanup.SYNTHETIC_PYTEST_MODULES


@pytest.mark.parametrize('phase', ['plan', 'apply'])
@pytest.mark.parametrize('damage', ['none', 'changed', 'missing-checkout', 'missing-archive'])
def test_later_synthetic_source_support_is_bound_before_inventory_and_again_before_apply(
        synthetic_native_case, monkeypatch, phase, damage):
    state = synthetic_native_case
    support = 'tests_python/owned_fixture.py'
    monkeypatch.setattr(cleanup, 'SYNTHETIC_PYTEST_SUPPORT', frozenset())
    monkeypatch.setattr(cleanup, 'SYNTHETIC_PYTEST_SOURCE_SUPPORT', {OLD: frozenset({support})})
    before = legacy.preserved_bytes(state)
    plan = make_plan(state, state.synthetic_request)
    assert not plan['skipped'] and len(plan['candidates'][0]['targets']) == 1
    if damage == 'changed': legacy.put(state.checkout / support, b'changed fixture')
    elif damage == 'missing-checkout': (state.checkout / support).unlink()
    elif damage == 'missing-archive':
        # A checkout file alone cannot substitute for the exact archived member.
        missing = 'tests_python/absent_archived_fixture.py'
        legacy.put(state.checkout / missing, b'synthetic but not archived')
        monkeypatch.setattr(cleanup, 'SYNTHETIC_PYTEST_SOURCE_SUPPORT', {OLD: frozenset({missing})})
    if phase == 'plan':
        result = make_plan(state, state.synthetic_request)
        assert bool(result['candidates']) is (damage == 'none')
        assert bool(result['skipped']) is (damage != 'none')
    elif damage == 'none':
        result = cleanup.apply_plan(state.root, state.synthetic_request, plan, remote)
        assert result['status'] == 'REMOVED' and not state.synthetic_case.exists()
    else:
        with pytest.raises(ValueError, match='PLAN_OR_ORIGINAL_EVIDENCE_CHANGED_NO_DELETION'):
            cleanup.apply_plan(state.root, state.synthetic_request, plan, remote)
    if phase == 'plan' or damage != 'none': assert state.synthetic_case.is_dir()
    assert state.native_pytest.is_dir() and state.retained_native.read_bytes() == b'unique native diagnostic'
    assert legacy.preserved_bytes(state) == before


@pytest.mark.parametrize('kind', ['COMPILED_DIRECTORY', 'NPM_CACHE', 'RETIRED_PRIVATE_MAVEN',
    'GENERATED_SOURCE_DEPENDENCIES', 'GENERATED_SOURCE_JAR', 'GENERATED_OCI_CACHE',
    'GENERATED_IMAGE_ARCHIVE', 'GENERATED_NODE_MODULES', 'GENERATED_PYTEST_ROOT', 'GENERATED_SYNTHETIC_PYTEST_CASE'])
def test_every_generated_inventory_refuses_a_writable_parent_before_reading_target(generated, monkeypatch, kind):
    parent = generated.root / 'unregistered-inventory-parent'
    file_kind = kind in ('GENERATED_SOURCE_JAR', 'GENERATED_IMAGE_ARCHIVE')
    leaf = legacy.put(parent / ('output.jar' if file_kind else 'output/entry'), b'regenerable')
    target = leaf if file_kind else leaf.parent
    parent.chmod(0o775)
    monkeypatch.setattr(cleanup, 'digest', lambda *args: pytest.fail('Target contents read before ancestor admission'))
    with pytest.raises(ValueError, match='PATH_NOT_OWNED_OR_WRITABLE_BY_OTHERS'):
        cleanup.generated_inventory(generated.root, {'kind': kind, 'path': target.relative_to(generated.root).as_posix()})
    assert leaf.read_bytes() == b'regenerable'


@pytest.mark.parametrize('kind', ['GENERATED_NODE_MODULES', 'GENERATED_PYTEST_ROOT'])
def test_generated_dynamic_root_keeps_its_existing_mode_contract_with_private_ancestors(generated, kind):
    target = legacy.put(generated.root / 'private-parent/dynamic-root/entry', b'regenerable').parent
    target.chmod(0o775)
    value = cleanup.generated_inventory(generated.root, {'kind': kind, 'path': target.relative_to(generated.root).as_posix()})
    assert value['files'] == 1 and stat.S_IMODE(value['rootMetadata'][0]) == 0o775


def test_generated_apply_rechecks_parent_modes_before_deletion_or_journal(generated, monkeypatch):
    state = generated; cache = legacy.add_npm_cache(state)
    value = request(state, targets=[{'kind': 'NPM_CACHE', 'path': cache.relative_to(state.root).as_posix()}])
    plan = make_plan(state, value)
    assert len(plan['candidates']) == 1 and not plan['skipped']
    cache.parent.chmod(0o775); calls = []
    monkeypatch.setattr(cleanup, 'remove_target', lambda *args: calls.append(args))
    with pytest.raises(ValueError, match='PLAN_OR_ORIGINAL_EVIDENCE_CHANGED_NO_DELETION'):
        cleanup.apply_plan(state.root, value, plan, remote)
    assert not calls and cache.exists()
    assert not (state.root / 'inbox' / CURRENT / 'generated-cleanup-journal.jsonl').exists()


def test_permission_preflight_holds_unlisted_private_target_ancestors_until_first_chmod(permission_request, monkeypatch):
    state, value = permission_request; original = cleanup.generated_quiescent; calls = []
    def drift_after_inventory(*args, **kwargs):
        original(*args, **kwargs)
        state.cache.parent.chmod(0o775)
    monkeypatch.setattr(cleanup, 'generated_quiescent', drift_after_inventory)
    monkeypatch.setattr(os, 'fchmod', lambda *args: calls.append(args))
    result = cleanup.repair_generated_permissions(state.root, value, remote)
    assert result['status'] == 'PARTIAL_FAILURE' and result['deletedTargets'] == 0
    assert not calls and state.cache.exists()

@pytest.fixture
def transport_copy(generated, monkeypatch, tmp_path):
    """An exact authorized transport copy, with a separate original keeper."""
    import base64
    source = generated.inbox / 'source.tar.gz'
    keeper = legacy.put(tmp_path / 'preserved-original/source.tar.gz', source.read_bytes())
    approved = {'release': OLD, 'remotePath': str(source), 'localKeeper': str(keeper),
                'expectedBytes': source.stat().st_size, 'expectedSourceSha256': cleanup.digest(source)}
    # The production digest pins exactly 125 user-selected entries. Unselected
    # synthetic entries do not create files or enlarge this test's delete scope.
    selected = [approved] + [{**approved, 'release': 'ci-' + str(1000 + n) + '-' + 'a' * 12}
                             for n in range(124)]
    approval = {'approved': True, 'candidateCount': 125, 'selected': selected}
    raw = cleanup.canonical(approval)
    monkeypatch.setattr(cleanup, 'SCM_TRANSPORT_AUTHORIZATION_SHA256', cleanup.sha(raw))
    monkeypatch.setattr(cleanup, 'SCM_TRANSPORT_ROOT', str(generated.root))
    monkeypatch.setattr(cleanup, 'SCM_TRANSPORT_IDENTITY', IDENTITY)
    value = request(generated, targets=[{'kind': cleanup.SCM_TRANSPORT_KIND,
                                        'path': source.relative_to(generated.root).as_posix()}])
    value['scmTransportAuthorization'] = base64.b64encode(raw).decode('ascii')
    row = value['candidates'][0]
    row['terminal'] = {'kind': 'JENKINS_HISTORY', 'result': 'FAILURE', 'completed': True,
        'evidenceArchived': True, 'buildXmlSha256': '1' * 64, 'originalReleaseSha256': '2' * 64,
        'action': 'verify-runtime', 'productionReleaseEnabled': False}
    row['scmTransportKeeper'] = {'path': str(keeper), 'bytes': source.stat().st_size,
        'sha256': cleanup.digest(source), 'buildXmlSha256': '1' * 64,
        'releaseSha256': '2' * 64, 'catalogSha256': '3' * 64}
    row['scmTransportMetadata'] = cleanup.metadata(source.lstat())
    generated.transport = value
    generated.source_copy, generated.original_keeper, generated.approval = source, keeper, approval
    return generated


def test_transport_file_retirement_keeps_originals_and_does_not_reopen_deleted_source(transport_copy, monkeypatch):
    state = transport_copy; before = {str(p): p.read_bytes() for p in state.keep if p != state.source_copy}
    original = state.original_keeper.read_bytes()
    plan = make_plan(state, state.transport)
    assert not plan['skipped'] and len(plan['candidates']) == 1
    binding = cleanup.scm_transport_binding
    calls = []
    def checked(*args, **kwargs):
        assert state.source_copy.exists(), 'No post-delete source revalidation is allowed'
        calls.append(args[1]['release'])
        return binding(*args, **kwargs)
    monkeypatch.setattr(cleanup, 'scm_transport_binding', checked)
    result = cleanup.apply_plan(state.root, state.transport, plan, remote)
    assert calls == [OLD, OLD]  # Whole-plan freshness, then this target's boundary.
    assert result['status'] == 'REMOVED' and result['retention']['status'] == 'SATISFIED'
    assert result['scmTransportCopies']['deletedCount'] == 1
    assert result['scmTransportCopies']['localOriginalArchivesPreserved'] is True
    assert result['referenceScope'] == {'processScanUid': os.getuid(), 'containers': 'ALL_DOCKER_CONTAINERS'}
    assert not state.source_copy.exists() and state.original_keeper.read_bytes() == original
    assert before == {str(p): p.read_bytes() for p in state.keep if p != state.source_copy}
    assert state.classes.exists()  # No directories, compiled output or other categories selected.
    with pytest.raises(ValueError, match='PLAN_OR_ORIGINAL_EVIDENCE_CHANGED_NO_DELETION'):
        cleanup.apply_plan(state.root, state.transport, plan, remote)


@pytest.mark.parametrize('damage', ['missing-approval', 'wrong-approval', 'current-post', 'mixed-category',
    'wrong-host', 'unselected', 'keeper-path', 'keeper-size', 'keeper-source', 'keeper-build', 'keeper-catalog',
    'terminal-source', 'terminal-action', 'terminal-production', 'terminal-unfinished',
    'inode', 'group-writable', 'hardlink', 'changed-bytes', 'pending-runtime', 'pending-link',
    'published', 'publication-pointer', 'live-container', 'stopped-mount', 'process-reference'])
def test_transport_original_identity_and_reference_failures_refuse_without_deletion(transport_copy, monkeypatch, damage):
    state = transport_copy; value = copy.deepcopy(state.transport); row = value['candidates'][0]
    containers = []
    if damage == 'missing-approval': value.pop('scmTransportAuthorization')
    elif damage == 'wrong-approval': value['scmTransportAuthorization'] = 'e30='
    elif damage == 'current-post': value['currentPost'] = True
    elif damage == 'mixed-category': row['targets'].append({'kind': 'NPM_CACHE', 'path': 'other'})
    elif damage == 'wrong-host': value['identity']['machineId'] = '0' * 32
    elif damage == 'unselected': row['release'] = 'ci-69-' + 'f' * 12
    elif damage == 'keeper-path': row['scmTransportKeeper']['path'] += '.partial'
    elif damage == 'keeper-size': row['scmTransportKeeper']['bytes'] -= 1
    elif damage == 'keeper-source': row['scmTransportKeeper']['sha256'] = '0' * 64
    elif damage == 'keeper-build': row['scmTransportKeeper']['buildXmlSha256'] = '0' * 64
    elif damage == 'keeper-catalog': row['scmTransportKeeper']['catalogSha256'] = 'not-a-sha'
    elif damage == 'terminal-source': row['terminal']['originalReleaseSha256'] = '0' * 64
    elif damage == 'terminal-action': row['terminal']['action'] = 'deploy'
    elif damage == 'terminal-production': row['terminal']['productionReleaseEnabled'] = True
    elif damage == 'terminal-unfinished': row['terminal']['completed'] = False
    elif damage == 'inode': row['scmTransportMetadata'][5] += 1
    elif damage == 'group-writable': state.source_copy.chmod(0o660)
    elif damage == 'hardlink': os.link(state.source_copy, state.source_copy.with_name('other-copy'))
    elif damage == 'changed-bytes': state.source_copy.write_bytes(state.source_copy.read_bytes() + b'changed')
    elif damage == 'pending-runtime': legacy.put(state.attempt / 'runtime-execution.json', b'{}')
    elif damage == 'pending-link': (state.attempt / 'runtime-acceptance.json').symlink_to(state.root / 'missing')
    elif damage == 'published': (state.root / 'releases' / OLD).mkdir(parents=True, mode=0o700)
    elif damage == 'publication-pointer': legacy.put(state.root / 'state/current-directory', str(state.checkout).encode())
    elif damage == 'live-container': containers = [['a' * 64, True, False, 123, OLD, None, []]]
    elif damage == 'stopped-mount': containers = [['a' * 64, False, False, 0, None, None,
        [{'Type': 'bind', 'Source': str(state.source_copy)}]]]
    elif damage == 'process-reference':
        def active(*args, **kwargs): raise ValueError('ACTIVE_FILE_DESCRIPTOR_REFERENCES_OLD_CHECKOUT')
        monkeypatch.setattr(cleanup, 'process_references', active)
    try:
        result = make_plan(state, value, containers)
    except ValueError:
        pass  # Fixed authorization failures stop before candidate planning.
    else:
        assert not result['candidates'] and result['skipped']
    assert state.source_copy.exists() and state.original_keeper.exists()
    assert not (state.root / 'inbox' / CURRENT / 'generated-cleanup-journal.jsonl').exists()


@pytest.mark.parametrize('change', ['metadata', 'source', 'reference', 'pending'])
def test_transport_apply_rechecks_before_first_delete(transport_copy, monkeypatch, change):
    state = transport_copy; value = state.transport; plan = make_plan(state, value)
    assert plan['candidates'] and not plan['skipped']
    if change == 'metadata': os.utime(state.source_copy, ns=(1, 1))
    elif change == 'source': state.source_copy.write_bytes(b'replaced original transport bytes')
    elif change == 'reference':
        monkeypatch.setattr(cleanup, 'docker_snapshot', lambda: [['a' * 64, True, False, 123, OLD, None, []]])
    else: legacy.put(state.attempt / 'runtime-execution.json', b'{}')
    with pytest.raises(ValueError, match='PLAN_OR_ORIGINAL_EVIDENCE_CHANGED_NO_DELETION'):
        cleanup.apply_plan(state.root, value, plan, remote)
    assert state.source_copy.exists() and state.original_keeper.exists()


def test_transport_delete_primitive_requires_authorization_even_with_valid_inventory(transport_copy):
    state = transport_copy
    plan = make_plan(state, state.transport); target = plan['candidates'][0]['targets'][0]
    fd = os.open(state.root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(ValueError, match='SCM_TRANSPORT_DELETE_REQUIRES_EXACT_AUTHORIZATION'):
            cleanup.remove_target(fd, target)
    finally: os.close(fd)
    assert state.source_copy.exists()


def test_transport_is_not_discovered_by_old_generated_auto_or_old_permission_repair(transport_copy):
    state = transport_copy
    assert cleanup.SCM_TRANSPORT_KIND not in cleanup.generated_paths(OLD)
    old_plan = make_plan(state, request(state))
    assert all(t['path'] != state.source_copy.relative_to(state.root).as_posix()
               for c in old_plan['candidates'] for t in c['targets'])
    invalid = copy.deepcopy(state.transport)
    invalid['candidates'][0]['permissionRepairs'] = [{'path': 'inbox/' + OLD}]
    with pytest.raises(ValueError, match='SCM_TRANSPORT_TARGET_NOT_AUTHORIZED'):
        make_plan(state, invalid)


def test_transport_mid_batch_failure_reports_only_actual_prefix_and_new_plan_selects_only_remaining(transport_copy, monkeypatch):
    import base64
    state = transport_copy; value = copy.deepcopy(state.transport)
    second_tag = 'ci-69-' + 'a' * 12
    second_source = legacy.put(state.root / 'inbox' / second_tag / 'source.tar.gz', state.source_copy.read_bytes())
    second_row = copy.deepcopy(value['candidates'][0]); second_row['release'] = second_tag
    second_row['targets'][0]['path'] = second_source.relative_to(state.root).as_posix()
    second_row['scmTransportMetadata'] = cleanup.metadata(second_source.lstat())
    value['candidates'].append(second_row)
    approval = copy.deepcopy(state.approval)
    approval['selected'][1] = {**approval['selected'][0], 'release': second_tag, 'remotePath': str(second_source)}
    raw = cleanup.canonical(approval); value['scmTransportAuthorization'] = base64.b64encode(raw).decode()
    monkeypatch.setattr(cleanup, 'SCM_TRANSPORT_AUTHORIZATION_SHA256', cleanup.sha(raw))
    plan = make_plan(state, value)
    assert len(plan['candidates']) == 2 and not plan['skipped']
    original_remove = cleanup.remove_target
    def fail_second(fd, target, **kwargs):
        if second_tag in target['path']: raise ValueError('SYNTHETIC_SECOND_TARGET_CHANGED')
        return original_remove(fd, target, **kwargs)
    monkeypatch.setattr(cleanup, 'remove_target', fail_second)
    result = cleanup.apply_plan(state.root, value, plan, remote)
    assert result['status'] == 'PARTIAL_FAILURE' and len(result['deleted']) == 1
    assert result['scmTransportCopies']['deletedCount'] == 1
    assert not state.source_copy.exists() and second_source.exists() and state.original_keeper.exists()
    assert [x['path'] for x in result['retention']['remainingTargets']] == [second_row['targets'][0]['path']]
    with pytest.raises(ValueError, match='PLAN_OR_ORIGINAL_EVIDENCE_CHANGED_NO_DELETION'):
        cleanup.apply_plan(state.root, value, plan, remote)
    remaining_request = copy.deepcopy(value); remaining_request['candidates'] = [second_row]
    remaining_plan = make_plan(state, remaining_request)
    assert len(remaining_plan['candidates']) == 1 and not remaining_plan['skipped']
    assert remaining_plan['candidates'][0]['release'] == second_tag

@pytest.mark.parametrize('damage', ['different-commit', 'invalid-gzip'])
def test_transport_archive_structure_and_commit_are_checked_even_when_keeper_bytes_agree(transport_copy, monkeypatch, damage):
    import base64
    state = transport_copy; value = copy.deepcopy(state.transport)
    if damage == 'different-commit': legacy.package(state.source_copy, {'fixed-source.txt': b'synthetic'}, 'b' * 40)
    else: legacy.put(state.source_copy, b'not a gzip archive')
    raw_source = state.source_copy.read_bytes()
    legacy.put(state.original_keeper, raw_source)
    checksum = cleanup.sha(raw_source)
    row = value['candidates'][0]; row['sourceSha256'] = checksum
    row['scmTransportKeeper'].update(bytes=len(raw_source), sha256=checksum)
    row['scmTransportMetadata'] = cleanup.metadata(state.source_copy.lstat())
    approval = copy.deepcopy(state.approval)
    approval['selected'][0].update(expectedBytes=len(raw_source), expectedSourceSha256=checksum)
    raw = cleanup.canonical(approval); value['scmTransportAuthorization'] = base64.b64encode(raw).decode()
    monkeypatch.setattr(cleanup, 'SCM_TRANSPORT_AUTHORIZATION_SHA256', cleanup.sha(raw))
    plan = make_plan(state, value)
    assert not plan['candidates'] and plan['skipped']
    assert state.source_copy.exists() and state.original_keeper.exists()

def test_transport_keeps_source_needed_by_existing_enrollment_and_allows_empty_enrollment(transport_copy):
    state = transport_copy
    legacy.put_json(state.inbox / 'generated-terminal.json', {'schema': 1,
        'kind': cleanup.GENERATED_TERMINAL_KIND, 'identity': IDENTITY,
        'candidate': {**state.transport['candidates'][0], 'targets': 'AUTO'}})
    assert cleanup.has_generated_outputs(state.root, OLD)
    refused = make_plan(state, state.transport)
    assert not refused['candidates']
    assert refused['skipped'][0]['reason'] == 'SCM_TRANSPORT_REQUIRED_BY_ENROLLED_OUTPUTS'
    assert state.source_copy.exists()
    # Once the separately authorized old outputs have actually been retired,
    # an enrollment with no outputs is already skipped before source binding.
    old = request(state)
    plan = make_plan(state, old)
    assert not plan['skipped']
    assert cleanup.apply_plan(state.root, old, plan, remote)['status'] == 'REMOVED'
    assert not cleanup.has_generated_outputs(state.root, OLD)
    fresh = copy.deepcopy(state.transport)
    fresh['currentRelease'] = 'ci-73-' + 'c' * 12
    (state.root / 'inbox' / fresh['currentRelease']).mkdir(mode=0o700)
    accepted = make_plan(state, fresh)
    assert accepted['candidates'] and not accepted['skipped']
    assert cleanup.apply_plan(state.root, fresh, accepted, remote)['status'] == 'REMOVED'
    assert not state.source_copy.exists()
    auto = make_plan(state, old)
    assert not auto['candidates'] and not auto['skipped'] and auto['absent']
