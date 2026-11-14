"""ECS-run contracts for the existing Jenkins evidence-only recovery action."""
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / 'Jenkinsfile.ecs-monolith'
CONFIGURATION = ROOT / 'script/jenkins/configure-local.groovy'


def stages():
    return dict(re.findall(r"(?ms)^        stage\('([^'\n]+)'\) \{\n(.*?)^        \}\n",
                           PIPELINE.read_text(encoding='utf8')))


def test_recollection_is_an_existing_job_action_with_one_build_number_not_a_path_parameter():
    pipeline = PIPELINE.read_text(encoding='utf8')
    configure = CONFIGURATION.read_text(encoding='utf8')
    assert "'reclaim-build-outputs', 'collect-existing-evidence']" in pipeline
    assert "'reclaim-build-outputs', 'collect-existing-evidence'] as String[]" in configure
    assert "string(name: 'EXISTING_EVIDENCE_BUILD', defaultValue: '', trim: true" in pipeline
    assert "new StringParameterDefinition('EXISTING_EVIDENCE_BUILD', ''" in configure
    assert not re.search(r"(?:name: |StringParameterDefinition\()'EXISTING_EVIDENCE_(?:PATH|DIRECTORY|ARCHIVE)'", pipeline + configure)


def test_recollection_requires_an_earlier_canonical_build_and_the_explicit_collector_commit():
    source = PIPELINE.read_text(encoding='utf8')
    gate = source.split("if (params.ACTION == 'collect-existing-evidence') {", 1)[1].split('if (env.FAILED_MYSQL_DATA_BUILDS)', 1)[0]
    assert "env.EXISTING_EVIDENCE_BUILD ==~ /[1-9][0-9]{0,8}/" in gate
    assert "env.EXISTING_EVIDENCE_BUILD.toLong() >= env.BUILD_NUMBER.toLong()" in gate
    assert "!params.TRUSTED_COMMIT?.trim() || params.TRUSTED_COMMIT.trim() != env.GIT_COMMIT" in gate
    assert "else if (env.EXISTING_EVIDENCE_BUILD) error(" in gate
    assert "env.EXISTING_EVIDENCE_BUILD = params.EXISTING_EVIDENCE_BUILD?.trim() ?: ''" in source


def test_recollection_shares_the_no_business_or_release_input_gate_without_requiring_an_ecs_connection():
    source = PIPELINE.read_text(encoding='utf8')
    gate = source.split("if (params.ACTION in ['reclaim-build-outputs', 'verify-controls', 'collect-existing-evidence']) {", 1)[1]
    gate = gate.split('if (env.CANDIDATE_BUILD_TOOLS_ARCHIVE', 1)[0]
    for required in ("params.DOORHANDLE_CI_SCOPE != 'source'", 'businessInputs.any { it }', 'releaseInputs.any { it }',
                     'env.DOORHANDLE_CI_FIXTURE_MANIFEST', 'env.DOORHANDLE_CI_FIXTURE_SETTINGS',
                     'params.DOORHANDLE_CI_AUTO_COMPACT_FIXTURES', 'env.CANDIDATE_BUILD_TOOLS_ARCHIVE',
                     'params.PRODUCTION_RELEASE_ENABLED', 'params.REHEARSAL_KEEP',
                     "env.DOORHANDLE_COMPACT_RELEASE_READY == 'true'", "env.DOORHANDLE_COMPACT_REHEARSAL_READY == 'true'",
                     "env.CI_ECS_VERIFIED = 'false'"):
        assert required in gate
    assert "if (!env.DEPLOY_HOST && params.ACTION != 'collect-existing-evidence')" in source


def test_recollection_stage_calls_only_the_existing_credential_free_controller():
    body = stages()['Collect existing verification evidence']
    assert "when { expression { params.ACTION == 'collect-existing-evidence' } }" in body
    assert re.findall(r"pwsh '([^']+)'", body) == ['& ./script/jenkins/pipeline.ps1 -Action CollectExistingEvidence']
    assert 'withCredentials' not in body and 'sshUserPrivateKey' not in body
    assert 'CI_ECS_VERIFIED' not in body and 'CI_TOOLS_PREPARED' not in body


@pytest.mark.parametrize('stage', ['Build locally without tests', 'Package pinned source',
    'Prepare temporary ECS tools', 'Prepare isolated ECS fixtures', 'Verify on ECS over SSH'])
def test_recollection_is_explicitly_excluded_from_build_package_tools_fixtures_and_tests(stage):
    body = stages()[stage]
    guard = re.search(r'when \{ expression \{ (.+) \} \}', body).group(1)
    excluded = re.search(r"!\(params.ACTION in \[([^]]+)\]\)", guard).group(1)
    assert "'collect-existing-evidence'" in excluded


def test_recollection_post_archives_originals_without_remote_cleanup_or_duplicate_junit_results():
    source = PIPELINE.read_text(encoding='utf8').split('    post {', 1)[1]
    recovery = source.split("if (params.ACTION == 'collect-existing-evidence') {", 1)[1].split("else if (params.ACTION == 'reclaim-build-outputs')", 1)[0]
    for path in ('artifacts/evidence-recollection.json', 'artifacts/ecs/recovered-ci-*/**/*', 'artifacts/ecs/recovered-ci-*.tar.gz'):
        assert path in recovery
    assert 'junit testResults:' not in recovery
    assert 'withCredentials' not in recovery and '-Action Cleanup' not in recovery
    assert "env.CI_ARTIFACTS_READY == 'true'" in recovery
    assert 'fingerprint: true' in recovery


def test_recollection_preserves_fixed_checkout_and_does_not_mark_original_build_success():
    current = stages()
    checkout = current['Trusted checkout']
    assert 'def revision = checkout scm' in checkout and "env.GIT_COMMIT = commit" in checkout
    assert 'requestedCommit != commit' in checkout
    assert "env.CI_ECS_VERIFIED = 'false'" in checkout
    assert "env.CI_TOOLS_PREPARED = 'false'" in checkout
    assert "env.CI_RUNTIME_ATTEMPTED = 'false'" in checkout
    source = PIPELINE.read_text(encoding='utf8')
    assert 'Evidence recollection only: original #${env.EXISTING_EVIDENCE_BUILD}' in source
    assert 'getBuildByNumber' not in source and 'setResult(' not in source
