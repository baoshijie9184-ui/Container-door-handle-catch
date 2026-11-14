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
            r"(?m)^    elseif \(\$env:GENERATED_ARTIFACTS_ONLY -ceq 'true'\) \{ \$maintenancePaths \+= '([^']+)' \}$",
            package)
        assert selected, 'Generated maintenance must package its dynamic tree helper'
        paths.append(selected[1])
    assert "'--output=artifacts/source.tar.gz', $commit) + $maintenancePaths" in package
    return paths


def inspect_packaged_helpers(tmp_path, monkeypatch, *, generated, damage=None):
    paths = maintenance_package_paths(generated)
    if damage == 'missing-helper': paths.remove('script/jenkins/retire-source-pytest.py')
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
    if generated: expected.add('script/jenkins/retire-source-pytest.py')
    assert set(result) == expected
    for name, descriptor in result.items():
        raw = (legacy.ROOT / name).read_bytes()
        assert descriptor == {'bytes': len(raw), 'sha256': cleanup.sha(raw)}


@pytest.mark.parametrize(('damage', 'error'), [
    ('missing-helper', 'Required cleanup helper missing from fixed source archive'),
    ('wrong-commit', 'Fixed helper commit differs'),
])
def test_generated_package_rejects_missing_helper_and_wrong_commit_separately(tmp_path, monkeypatch, damage, error):
    with pytest.raises(ValueError, match=error):
        inspect_packaged_helpers(tmp_path, monkeypatch, generated=True, damage=damage)
