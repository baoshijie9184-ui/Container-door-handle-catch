"""Candidate metrics contracts; run only through the ECS verification matrix."""
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('candidate_observability', ROOT / 'script/docker/compact-runtime-observability.py')
monitoring = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(monitoring)
PROJECT = 'doorhandle-rehearsal-' + 'a' * 12
IMAGES = {name: 'sha256:' + character * 64 for name, character in zip(monitoring.COMPONENTS, 'bc')}


def config():
    services = {name: {'environment': {'LANGFUSE_SECRET_KEY_FILE': '/production/secret', 'OTEL_ENABLED': 'true'},
                      'volumes': [], 'networks': {'doorhandle-network': {}}} for name in monitoring.APPLICATIONS}
    for name in monitoring.COMPONENTS:
        services[name] = {'image': 'mutable:tag', 'profiles': ['observability'], 'ports': ['127.0.0.1:9090:9090'],
            'command': ['--storage.tsdb.retention.time=7d', '--storage.tsdb.retention.size=512MB'],
            'volumes': [{'type': 'bind', 'source': '/production/secret', 'target': '/run/observability-secrets'},
                        {'type': 'volume', 'source': 'doorhandle-' + name, 'target': '/' + name}]}
    services['langfuse-web'] = {'image': 'never-start'}
    value = {'services': services, 'volumes': {'doorhandle-prometheus': {}, 'doorhandle-alertmanager': {}, 'doorhandle-langfuse-postgres': {}}}
    monitoring.select_overlay(value, IMAGES)
    # The existing isolated_config owns naming and strips all host ports.
    for name, volume in value['volumes'].items(): volume['name'] = PROJECT + '_' + name
    for service in value['services'].values(): service.pop('ports', None)
    monitoring.enable(value)
    return value


def targets():
    return {'status': 'success', 'data': {'activeTargets': [
        {'labels': {'job': job}, 'scrapeUrl': 'http://' + address + path, 'health': 'up', 'lastError': '',
         'lastScrape': datetime.fromtimestamp(200, timezone.utc).isoformat()}
        for job, (address, path) in monitoring.JOBS.items()]}}


def vector(number='1'):
    return {'status': 'success', 'data': {'resultType': 'vector', 'result': [{'value': [200, number]}]}}


def test_overlay_reuses_only_the_two_pinned_services_and_owned_volumes():
    value = config()
    assert not any('langfuse' in name for name in (*value['services'], *value['volumes']))
    for name in monitoring.COMPONENTS:
        service = value['services'][name]
        assert service['image'] == IMAGES[name] and service['user'] == '10001:10001'
        assert 'profiles' not in service and 'ports' not in service
        assert all(mount['type'] == 'volume' for mount in service['volumes'])
    assert '--storage.tsdb.retention.size=64MB' in value['services']['prometheus']['command']


def test_all_three_actual_applications_use_private_metrics_without_tracing_credentials():
    value = config()
    for name in monitoring.APPLICATIONS:
        env = value['services'][name]['environment']
        assert env['TELEMETRY_METRICS_ENABLED'] == 'true'
        assert env['OTEL_ENABLED'] == env['DOORHANDLE_OBSERVABILITY_TRACING_ENABLED'] == 'false'
        assert not any(key.startswith('LANGFUSE_') for key in env)
    assert value['services']['backend']['environment']['DOORHANDLE_OBSERVABILITY_METRICS_TOKEN_FILE'] == monitoring.TOKEN_FILE


@pytest.mark.parametrize('damage', ['disabled', 'writable-secret', 'trace-secret', 'host-port', 'langfuse'])
def test_candidate_monitoring_config_rejects_missing_metrics_or_weakened_isolation(damage):
    value = config()
    if damage == 'disabled': value['services']['mem0']['environment']['TELEMETRY_METRICS_ENABLED'] = 'false'
    elif damage == 'writable-secret': value['services']['backend']['volumes'][0]['read_only'] = False
    elif damage == 'trace-secret': value['services']['backend']['environment']['LANGFUSE_SECRET_KEY'] = 'unexpected'
    elif damage == 'host-port': value['services']['prometheus']['ports'] = ['9090:9090']
    else: value['services']['langfuse-web'] = {}
    with pytest.raises(ValueError): monitoring.validate(value)


def test_actual_scrapes_must_follow_the_current_start_or_recovery_phase():
    monitoring.require_targets(targets(), since=199)
    with pytest.raises(ValueError, match='predates'): monitoring.require_targets(targets(), since=201)


@pytest.mark.parametrize('damage', ['absent', 'foreign', 'down', 'duplicate'])
def test_three_up_targets_cannot_be_replaced_by_a_fixture_or_old_healthy_flag(damage):
    value = targets(); rows = value['data']['activeTargets']
    if damage == 'absent': rows.pop()
    elif damage == 'foreign': rows[0]['scrapeUrl'] = 'http://source-backend:8080/actuator/prometheus'
    elif damage == 'down': rows[0]['health'] = 'down'
    else: rows[1] = copy.deepcopy(rows[0])
    with pytest.raises(ValueError): monitoring.require_targets(value)


@pytest.mark.parametrize('number', ['0', 'NaN', '+Inf'])
def test_ready_samples_require_a_real_finite_one(number):
    with pytest.raises(ValueError): monitoring.require_sample(vector(number), exact=1)


def test_metric_presence_is_required_and_jvm_heap_has_actual_positive_bytes():
    monitoring.require_sample(vector('24576000'), positive=True)
    value = vector(); value['data']['result'] = []
    with pytest.raises(ValueError): monitoring.require_sample(value)


def test_private_install_uses_stdin_owned_volumes_and_never_records_token(tmp_path):
    calls = []
    value = config()
    def docker(*args, **kwargs):
        calls.append((args, kwargs))
        if args[:2] == ('volume', 'inspect'):
            return json.dumps([{'Labels': {'io.doorhandle.rehearsal': PROJECT}}]).encode()
        return b''
    ctx = SimpleNamespace(config=value, project=PROJECT, source=ROOT, ops=SimpleNamespace(docker=docker),
        images={'mem0': 'sha256:' + 'd' * 64}, owner={}, save=lambda: None)
    monitoring.install(ctx)
    args, kwargs = next(call for call in calls if call[0][0] == 'run')
    payload = json.loads(kwargs['data'])
    assert len(payload['token']) == 64 and payload['token'] not in json.dumps(ctx.owner)
    assert '--network' in args and args[args.index('--network') + 1] == 'none'
    assert '--pull' in args and args[args.index('--pull') + 1] == 'never'
    assert set(payload['files']) == set(monitoring.FILES)
    assert all(name.startswith(PROJECT + '_') for name in ctx.owner['observabilityVolumes'].values())


def proof_files(tmp_path):
    context = {'release': 'ci-1-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64,
        'identity': {'executionLocation': 'ECS'}, 'project': PROJECT,
        'acceptanceProfileSha256': 'c' * 64, 'candidateBuildSha256': 'd' * 64}
    proofs = {}; readbacks = {}
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value).encode(); path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()
    for name in monitoring.COMPONENTS:
        summary = {**context, 'status': 'PASS', 'cleanup': {key: True for key in
            ('creatorStopped', 'builderStopped', 'daemonImportTerminated')}}
        checksum = write(tmp_path / (name + '-image') / 'resource-summary.json', summary)
        image = {**context, 'kind': 'doorhandle-' + name + '-image', 'status': 'PREPARED',
            'engineIdentity': {'engineImageId': IMAGES[name]}, 'resourceEvidence': {'sha256': checksum}}
        proofs[name] = {'file': 'checkout/work/observability-fixture/' + name + '-image/image.json',
            'sha256': write(tmp_path / (name + '-image') / 'image.json', image), 'image': IMAGES[name],
            'resourceSummarySha256': checksum}
    monitoring_proof = {'status': 'PASS', 'images': proofs, 'readbacks': readbacks,
        'tracingEnabled': False, 'langfuseEnabled': False, 'externalNotificationVerified': False,
        'storageRecovery': 'RETAINED_MONITORING_VOLUMES_ACROSS_BUSINESS_RESTORE'}
    proof = {**context, 'observability': monitoring_proof, 'images': {name: 'sha256:' + 'e' * 64 for name in monitoring.APPLICATIONS}}
    queries = {'up{job="' + job + '"}': vector() for job in monitoring.JOBS}
    queries.update({'sum(jvm_memory_used_bytes{job="monolith",area="heap"})': vector('10000'),
        'doorhandle_runtime_ready{job="detection-worker"}': vector(), 'doorhandle_runtime_ready{job="mem0"}': vector()})
    for phase in monitoring.PHASES:
        value = {**context, 'kind': 'doorhandle-runtime-observability', 'phase': phase, 'status': 'PASS',
            'containers': {name: {'containerId': 'f' * 64, 'image': IMAGES[name] if name in monitoring.COMPONENTS else proof['images'][name]}
                           for name in (*monitoring.COMPONENTS, *monitoring.APPLICATIONS)},
            'volumes': {name: PROJECT + '_' + name for name in (monitoring.CONFIG_VOLUME, monitoring.SECRET_VOLUME, 'doorhandle-prometheus', 'doorhandle-alertmanager')},
            'tracingEnabled': False, 'langfuseEnabled': False, 'storageRecovery': monitoring_proof['storageRecovery'],
            'scrapedAfterUnix': 199, 'evidence': {'targets': targets(), 'queries': queries,
                'rules': {'status': 'success', 'data': {'groups': [{'rules': [{'name': rule, 'health': 'ok'} for rule in monitoring.RULES]}]}},
                'alertmanagers': {'status': 'success', 'data': {'activeAlertmanagers': [{'url': 'http://alertmanager:9093/api/v2/alerts'}]}},
                'alertmanagerStatus': {'config': {'original': (ROOT / 'deploy/observability/alertmanager.yml').read_text(encoding='utf8')}},
                'alertmanagerGroups': []}}
        name = 'observability-' + phase + '.json'
        readbacks[phase] = {'file': 'checkout/work/runtime-acceptance/' + name, 'sha256': write(tmp_path / name, value)}
    def read(path):
        raw = path.read_bytes(); return json.loads(raw), hashlib.sha256(raw).hexdigest()
    return proof, read, write


def test_byte_validator_binds_all_actual_phases_and_reused_image_preparation(tmp_path):
    proof, read, _ = proof_files(tmp_path)
    result = monitoring.validate_files(proof, tmp_path, read)
    assert result['status'] == 'VERIFIED' and result['phases'] == list(monitoring.PHASES)


@pytest.mark.parametrize('damage', ['missing-phase', 'foreign-app', 'changed-volume', 'stale-scrape', 'lost-rule', 'changed-image'])
def test_collected_monitoring_cannot_pass_with_changed_or_incomplete_evidence(tmp_path, damage):
    proof, read, write = proof_files(tmp_path)
    if damage == 'missing-phase': proof['observability']['readbacks'].pop('after-restart')
    elif damage == 'changed-image': proof['observability']['images']['prometheus']['sha256'] = '0' * 64
    else:
        phase = 'after-volume-restore'; path = tmp_path / ('observability-' + phase + '.json'); value, _ = read(path)
        if damage == 'foreign-app': value['containers']['mem0']['image'] = 'sha256:' + '0' * 64
        elif damage == 'changed-volume': value['volumes']['doorhandle-prometheus'] = 'another-project'
        elif damage == 'stale-scrape': value['scrapedAfterUnix'] = 201
        else: value['evidence']['rules']['data']['groups'][0]['rules'].pop()
        proof['observability']['readbacks'][phase]['sha256'] = write(path, value)
    with pytest.raises(ValueError): monitoring.validate_files(proof, tmp_path, read)


def test_jenkins_archives_both_downloaded_image_resource_probe_originals():
    workflow = (ROOT / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf8')
    catalogues = [set(value.split(',')) for value in re.findall(r"archiveArtifacts\s+artifacts:\s*'([^']+)'", workflow)]
    runtime = next(value for value in catalogues if 'artifacts/runtime-resources/resource-probes.jsonl' in value)
    assert {'artifacts/runtime-observability/' + name + '-image/resource-probes.jsonl'
            for name in monitoring.COMPONENTS} <= runtime
    assert 'artifacts/runtime-observability/**/*' not in runtime


def test_new_runtime_collector_rejects_missing_required_flag_before_legacy_byte_validation():
    pipeline = (ROOT / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    collector = pipeline.split('function Receive-RuntimeObservability($Proof) {', 1)[1].split('function Receive-RuntimeCollaboration', 1)[0]
    guard = collector.split('$phases =', 1)[0]
    assert "-not $Proof.loadScope.PSObject.Properties['observabilityRequired']" in guard
    assert '$Proof.loadScope.observabilityRequired -isnot [bool]' in guard
    assert '$Proof.loadScope.observabilityRequired -ne $true' in guard
    assert "throw 'Required candidate monitoring did not pass.'" in guard
    assert not re.search(r'\breturn\b', guard)
    assert pipeline.index('Receive-RuntimeObservability $runtimeProof') < pipeline.index('$validatedResources = Invoke-Checked')
