"""ECS-only protocol regressions; no browser, application or SSH is started here."""
import importlib.util
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('owned_manual_acceptance', ROOT / 'script/docker/compact-runtime-manual.py')
manual = importlib.util.module_from_spec(spec); spec.loader.exec_module(manual)


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    clock = SimpleNamespace(now=10000.0, action=None)
    def sleep(seconds):
        clock.now += seconds
        if clock.action: clock.action()
    monkeypatch.setattr(manual, 'time', SimpleNamespace(time=lambda: clock.now, sleep=sleep))
    context = {'schemaVersion': 1, 'kind': 'doorhandle-compact-runtime-acceptance', 'release': 'ci-400-' + 'a' * 12,
        'commit': 'a' * 40, 'sourceSha256': 'b' * 64, 'candidateBuildSha256': 'c' * 64,
        'acceptanceProfileSha256': 'd' * 64, 'identity': {'instanceId': 'i-owned', 'machineId': 'e' * 32}}
    def write(path, value): path.write_text(json.dumps(value)); path.chmod(0o600)
    owner = {'phase': 'ASSERTIONS_PASSED', 'targetSchema': 'doorhandle_compact_candidate_' + 'a' * 10, 'port': 18089}
    phases = []
    def save(phase=None):
        if phase: owner['phase'] = phase; phases.append(phase)
    ctx = SimpleNamespace(directory=tmp_path, owner=owner, project='doorhandle-rehearsal-' + 'a' * 12,
        context=lambda: context, common=SimpleNamespace(write_json=write), save=save,
        guard=SimpleNamespace(read_private=lambda path: (json.loads(path.read_text()), 'f' * 64)),
        resources=SimpleNamespace(error=None), transport=SimpleNamespace(supervisor_start=lambda pid: '777'),
        accounts={alias: {'username': 'cf_' + 'a' * 12 + '_' + alias, 'password': 'private-password',
                         'role': 'SUPERVISOR' if alias in ('supervisor', 'reviewer') else 'INSPECTOR'}
                  for alias in ('supervisor', 'reviewer', 'inspector', 'peer')})
    execution = {**context, 'status': 'RUNNING', 'executionId': '1' * 32, 'manualAcceptanceSeconds': 900,
                 'supervisor': {'pid': 4321, 'startTicks': '777'}}
    def decision(outcome='ACCEPTED'):
        return {**{key: execution[key] for key in ('release', 'commit', 'sourceSha256', 'candidateBuildSha256', 'executionId')},
                'decision': outcome, 'submittedBy': 'reviewing-user'}
    return SimpleNamespace(ctx=ctx, execution=execution, clock=clock, phases=phases, decision=decision, write=write)


def test_default_has_no_window_credentials_or_owner_state_changes(candidate):
    candidate.execution.pop('manualAcceptanceSeconds')
    assert manual.wait(candidate.ctx, candidate.execution) == {'enabled': False, 'status': 'NOT_REQUESTED'}
    assert list(candidate.ctx.directory.iterdir()) == [] and candidate.phases == []


@pytest.mark.parametrize('value', [True, -1, 30, 3601, '900', None])
def test_only_explicit_bounded_window_durations_are_admitted(value):
    with pytest.raises(ValueError): manual.duration(value)


def test_acceptance_uses_same_live_candidate_without_publishing_pass_or_cleaning_early(candidate):
    original = dict(candidate.execution)
    def approve():
        ready = manual.status(candidate.ctx, candidate.execution)
        assert ready['targetTableCount'] == 29 and ready['status'] == 'READY_FOR_MANUAL_ACCEPTANCE'
        assert ready['terminal'] is False and ready['remainingSeconds'] == 899
        assert ready['productionPromotionAllowed'] is False and ready['finalCleanupRequired'] is True
        assert 'accounts' not in ready and 'private-password' not in json.dumps(ready)
        access = candidate.ctx.directory / 'manual-access.json'
        assert access.stat().st_mode & 0o777 == 0o600
        assert len(json.loads(access.read_text())['accounts']) == 4
        manual.decide(candidate.ctx, candidate.execution, candidate.decision())
    candidate.clock.action = approve
    result = manual.wait(candidate.ctx, candidate.execution)
    assert result['status'] == 'ACCEPTED' and result['expiresAtUnix'] == 10900
    assert candidate.execution == original and candidate.phases == ['WAITING_FOR_MANUAL_ACCEPTANCE']
    assert candidate.ctx.owner['manualAcceptance'] == result
    assert not (candidate.ctx.directory / 'manual-access.json').exists()
    assert not (candidate.ctx.directory / 'runtime-acceptance.json').exists()


@pytest.mark.parametrize('outcome', ['REJECTED', 'EXPIRED', 'CANCELLED', 'RESOURCE_FAILURE'])
def test_nonacceptance_is_recorded_for_original_failure_cleanup_and_never_returns_pass(candidate, outcome):
    def action():
        if outcome == 'REJECTED': manual.decide(candidate.ctx, candidate.execution, candidate.decision('REJECTED'))
        elif outcome == 'EXPIRED': candidate.clock.now = 10900
        elif outcome == 'CANCELLED': raise KeyboardInterrupt()
        else: candidate.ctx.resources.error = 'ResourcePressure'
    candidate.clock.action = action
    with pytest.raises((ValueError, KeyboardInterrupt)): manual.wait(candidate.ctx, candidate.execution)
    assert candidate.ctx.owner['manualAcceptance']['status'] == ('CANCELLED' if outcome == 'RESOURCE_FAILURE' else outcome)
    assert not (candidate.ctx.directory / 'manual-access.json').exists()
    assert candidate.execution['status'] == 'RUNNING'


@pytest.mark.parametrize('phase', ['PREPARED', 'RUNNING', 'FAILED_OR_UNKNOWN'])
def test_manual_window_cannot_precede_complete_automatic_assertions(candidate, phase):
    candidate.ctx.owner['phase'] = phase
    with pytest.raises(ValueError, match='all automatic assertions'): manual.wait(candidate.ctx, candidate.execution)
    assert list(candidate.ctx.directory.iterdir()) == []


@pytest.mark.parametrize('field', ['release', 'commit', 'sourceSha256', 'candidateBuildSha256', 'executionId', 'decision', 'submittedBy'])
def test_foreign_or_invalid_decisions_cannot_release_the_waiting_owner(candidate, field):
    def action():
        payload = candidate.decision(); payload[field] = '' if field == 'submittedBy' else 'foreign'
        with pytest.raises(ValueError): manual.decide(candidate.ctx, candidate.execution, payload)
        assert not (candidate.ctx.directory / 'manual-decision.json').exists()
        manual.decide(candidate.ctx, candidate.execution, candidate.decision())
    candidate.clock.action = action
    assert manual.wait(candidate.ctx, candidate.execution)['status'] == 'ACCEPTED'


def test_decision_is_idempotent_but_cannot_be_replaced_or_renew_the_deadline(candidate):
    def action():
        payload = candidate.decision()
        first = manual.decide(candidate.ctx, candidate.execution, payload)
        assert manual.decide(candidate.ctx, candidate.execution, payload) == first
        with pytest.raises(ValueError, match='already fixed'):
            manual.decide(candidate.ctx, candidate.execution, candidate.decision('REJECTED'))
        assert manual.read_ready(candidate.ctx, candidate.execution)['expiresAtUnix'] == 10900
    candidate.clock.action = action
    assert manual.wait(candidate.ctx, candidate.execution)['status'] == 'ACCEPTED'


def test_late_confirmation_is_rejected_and_cannot_turn_timeout_into_success(candidate):
    def action():
        candidate.clock.now = 10900
        with pytest.raises(ValueError, match='deadline has expired'):
            manual.decide(candidate.ctx, candidate.execution, candidate.decision())
    candidate.clock.action = action
    with pytest.raises(ValueError, match='deadline expired'): manual.wait(candidate.ctx, candidate.execution)
    assert candidate.ctx.owner['manualAcceptance']['status'] == 'EXPIRED'


def test_status_and_decision_do_not_admit_a_reused_supervisor_pid(candidate):
    def action():
        candidate.ctx.transport.supervisor_start = lambda _: 'reused'
        with pytest.raises(ValueError, match='not alive'): manual.status(candidate.ctx, candidate.execution)
        with pytest.raises(ValueError, match='original live runtime'):
            manual.decide(candidate.ctx, candidate.execution, candidate.decision())
        raise KeyboardInterrupt()
    candidate.clock.action = action
    with pytest.raises(KeyboardInterrupt): manual.wait(candidate.ctx, candidate.execution)


@pytest.mark.parametrize('status', ['PASS', 'FAILED'])
def test_terminal_status_never_reopens_a_manual_window(candidate, status):
    candidate.execution['status'] = status
    assert manual.status(candidate.ctx, candidate.execution)['terminal'] is True
    assert list(candidate.ctx.directory.iterdir()) == []


def test_existing_runtime_keeps_auto_gates_before_handoff_and_stopped_cleanup_before_pass():
    source = (ROOT / 'script/docker/compact-runtime-acceptance.py').read_text(encoding='utf8')
    run = source.split('    def run(self):', 1)[1].split('    def publish_scripted_model', 1)[0]
    handoff = run.index('self.manual.wait(')
    for gate in ('self.browser.run(self)', 'self.observability.finish(self)', 'self.native.finalize_semantic_activation(self)',
                 'fixture_build_evidence(self, require_pass=True)', 'Every actual service peak must be observed before manual acceptance',
                 'Complete native recovery must pass before manual acceptance', "self.save('ASSERTIONS_PASSED')"):
        assert run.index(gate) < handoff
    assert handoff < run.index('self.cleanup()') < run.index("'status': 'PASS'")
    assert "'ownedCleanup': 'STOPPED'" in run
    assert "original.get('manualAcceptanceSeconds', 0)" in source
    assert "if args.phase in ('observe', 'manual-status', 'manual-decision'):" in source


def test_jenkins_input_and_private_delivery_reuse_original_execution_without_waiting_for_own_build():
    pipeline = (ROOT / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf8')
    stage = pipeline.split("stage('Accept candidate application on ECS')", 1)[1].split("stage('Deploy or rollback')", 1)[0]
    helper = (ROOT / 'script/jenkins/runtime-manual-acceptance.ps1').read_text(encoding='utf8')
    assert "parallel failFast: false" in stage and "input(id: 'manual-candidate-acceptance'" in stage
    assert "def decision = 'REJECTED'" in stage and 'timeout(time: remaining' in stage
    assert 'CompleteManualRuntime' in stage and "runtime-owner-finished.json" in stage
    assert 'Wait-ExistingRuntime' not in helper and '/api/json' not in helper
    assert '127.0.0.1:${localPort}:127.0.0.1:' in helper and 'sleep $remaining' in helper
    assert 'CreateNoWindow=$true' in helper and 'process.StartTime.ToUniversalTime().Ticks' in helper
    assert "'accounts.json'" in helper and 'SetAccessRuleProtection($true,$false)' in helper
    assert 'artifacts/accounts' not in helper and 'Write-Host $access' not in helper
    assert 'DOORHANDLE_MANUAL_ACCEPTANCE_PRIVATE_ROOT' in helper
    assert "else {'REJECTED'}" in helper and "'handoff.json'" in helper


def test_manual_feature_is_default_off_and_never_reuses_production_or_old_rehearsal_gate():
    pipeline = (ROOT / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf8')
    controller = (ROOT / 'script/jenkins/configure-local.groovy').read_text(encoding='utf8')
    powershell = (ROOT / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    assert "name: 'MANUAL_ACCEPTANCE_ENABLED', defaultValue: false" in pipeline
    assert "BooleanParameterDefinition('MANUAL_ACCEPTANCE_ENABLED', false" in controller
    assert "settings.finishedOutputsManifest ?: ''" in controller
    assert "def finishedOutputsDirectory = new File(project, 'work/table-switch-20261115')" in controller
    assert "if (finishedOutputsManifest) {" in controller
    assert "'CI_FINISHED_OUTPUTS_MANIFEST': finishedOutputsManifest" in controller
    assert "params.ACTION != 'verify-runtime'" in pipeline and "params.PRODUCTION_RELEASE_ENABLED" in pipeline
    assert "'15','30','60'" in pipeline and 'bounded non-production verify-runtime candidate' in powershell
    assert "runtimeProof.manualAcceptance.status -cne 'ACCEPTED'" in powershell
    assert "runtimeResult.ownedCleanup -ne 'STOPPED'" in powershell


@pytest.mark.parametrize('path,allowed', [
    ('', True),
    ('D:/AI/lunwen1/DoorHandleCatch/work/table-switch-20261115/finished-ci-outputs-manifest.json', True),
    ('D:/AI/lunwen1/DoorHandleCatch/work/table-switch-20261115/finished-ci-364-outputs-manifest.json', True),
    ('D:\\AI\\lunwen1\\DoorHandleCatch\\work\\table-switch-20261115\\finished-ci-1-outputs-manifest.json', True),
    ('D:/AI/lunwen1/DoorHandleCatch/work/table-switch-20261115/finished-ci-0-outputs-manifest.json', False),
    ('D:/AI/lunwen1/DoorHandleCatch/work/table-switch-20261115/finished-ci-0364-outputs-manifest.json', False),
    ('D:/AI/lunwen1/DoorHandleCatch/work/table-switch-20261115/finished-ci--1-outputs-manifest.json', False),
    ('D:/AI/lunwen1/DoorHandleCatch/work/table-switch-20261115/other.json', False),
    ('D:/AI/lunwen1/DoorHandleCatch/work/table-switch-20261115/../finished-ci-364-outputs-manifest.json', False),
    ('D:/AI/lunwen1/DoorHandleCatch/work/table-switch-20261115/./finished-ci-364-outputs-manifest.json', False),
    ('D:/AI/lunwen1/DoorHandleCatch/work/table-switch-20261115/child/finished-ci-364-outputs-manifest.json', False),
    ('D:/AI/lunwen1/DoorHandleCatch/work/table-switch-20261115-other/finished-ci-364-outputs-manifest.json', False),
    ('D:/other/finished-ci-364-outputs-manifest.json', False),
    ('work/table-switch-20261115/finished-ci-364-outputs-manifest.json', False),
    ('D:/AI/lunwen1/DoorHandleCatch/work/table-switch-20261115/finished-ci-364-outputs-manifest.json/extra', False),
])
def test_finished_manifest_names_stay_in_the_private_task_directory(path, allowed):
    controller = (ROOT / 'script/jenkins/configure-local.groovy').read_text(encoding='utf8')
    block = controller.split("def finishedOutputsManifest =", 1)[1].split('assert settings.version', 1)[0]
    assert "finishedOutputsManifest.replace('\\\\', '/')" in block
    assert "finishedOutputsManifest.startsWith(finishedOutputsDirectory + '/')" in block
    assert 'finishedOutputsManifest.substring(finishedOutputsDirectory.length() + 1)' in block
    directory = re.search(r"new File\(project, '([^']+)'\)", block).group(1)
    pattern = re.search(r'assert finishedOutputsName ==~ /([^\n]+)/', block).group(1)
    prefix = 'D:/AI/lunwen1/DoorHandleCatch/' + directory + '/'
    normalized = path.replace('\\', '/')
    admitted = not normalized or (normalized.startswith(prefix) and re.fullmatch(pattern, normalized[len(prefix):]) is not None)
    assert admitted is allowed
    assert "'CI_FINISHED_OUTPUTS_MANIFEST': finishedOutputsManifest" in controller
    assert "StringParameterDefinition('CI_FINISHED_OUTPUTS_MANIFEST'" not in controller
