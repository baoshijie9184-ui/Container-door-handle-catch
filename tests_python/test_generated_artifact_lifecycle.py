"""Generated-output lifecycle controls. Run only through Jenkins on ECS.

All filesystem operations target pytest-owned synthetic trees; container and
process snapshots are injected. These are not business-data migration tests.
"""
import copy
import json
import os
from pathlib import Path
import stat

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


def test_request_payload_not_embedded_in_windows_ssh_command():
    # Shape matches the real 41-release/52-target admission, without private data.
    rows = [{'release': 'ci-' + str(i) + '-' + 'a'*12, 'targets': [
        {'path': 'inbox/ci-' + str(i) + '-' + 'a'*12 + '/candidate-build-tools/official-oci',
         'kind': 'GENERATED_OCI_CACHE'}], 'proof': 'x'*500} for i in range(1,42)]
    raw = json.dumps({'candidates': rows}).encode()
    descriptor = {'bytes': len(raw), 'sha256': 'a'*64}
    assert len(raw) > 23000 and len(json.dumps(descriptor)) < 120
    assert len(raw) < 1024**2
