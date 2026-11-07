"""ECS-only contracts for the bounded real runtime, not production capacity."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


runtime = load('bounded_runtime_resource_contract', 'script/docker/compact-runtime-acceptance.py')
candidate = load('bounded_worker_dependency_contract', 'script/docker/compact-candidate-build.py')


def evidence():
    context = {'schemaVersion': 1, 'kind': 'doorhandle-compact-runtime-acceptance', 'release': 'ci-58-' + 'a' * 12,
        'commit': 'a' * 40, 'sourceSha256': 'b' * 64, 'identity': {'instanceId': 'i-test', 'machineId': 'c' * 32},
        'acceptanceProfileSha256': 'd' * 64, 'candidateBuildSha256': 'e' * 64}
    project = 'doorhandle-rehearsal-' + 'f' * 12
    daemons = sorted(set(runtime.SERVICE_MEMORY_MIB) - {'kafka-init', 'kafka-storage-init', 'higress-seed', 'higress-config'})
    metrics = [{'containerId': format(index + 1, '064x'), 'service': name, 'image': 'sha256:' + '1' * 64,
        'memoryLimitBytes': runtime.SERVICE_MEMORY_MIB[name] * runtime.MIB, 'currentBytes': 128,
        'peakBytes': 256, 'oom': 0, 'oomKills': 0, 'running': True, 'exitCode': 0} for index, name in enumerate(daemons)]
    plans, phases, samples = {}, [], []
    for index, phase in enumerate(('runtime-start', 'runtime-backup', 'runtime-restore'), 1):
        baseline = {'capturedAtUnix': 100 + index, 'diskTotalBytes': 40 * runtime.GIB,
            'diskAvailableBytes': 8 * runtime.GIB, 'memoryAvailableBytes': 12 * runtime.GIB}
        plans[phase] = runtime.phase_admission(phase, baseline, runtime.GIB, 0, {'actualBytes': 100})
        phases.append({'phase': phase, 'file': 'checkout/work/runtime-acceptance/resource-phase-' + str(index) + '-' + phase + '.json',
                       'sha256': str(index) * 64})
        samples.append({'probe': {**baseline, 'phase': phase, 'hostDiskLossUpperBoundBytes': 0,
                                  'diskLossOwnershipProof': False}, 'containers': metrics, 'stopReasons': []})
    raw = b''.join((json.dumps(row) + '\n').encode() for row in samples)
    summary = {**context, 'kind': 'doorhandle-bounded-runtime-resources', 'project': project,
        'profile': runtime.RUNTIME_PROFILE, 'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'productionCapacityVerified': False,
        'status': 'MEASURED_FOR_BOUNDED_SCENARIOS', 'pollIntervalSeconds': 2, 'diskFloorBytes': runtime.DISK_FLOOR,
        'memoryFloorBytes': runtime.MEMORY_FLOOR, 'rawProbeFile': 'checkout/work/runtime-acceptance/resource-probes.jsonl',
        'rawProbeSha256': hashlib.sha256(raw).hexdigest(), 'samples': 3, 'containers': {v['containerId']: v for v in metrics},
        'requiredDaemonServices': daemons, 'minimumDiskAvailableBytes': 8 * runtime.GIB,
        'minimumMemoryAvailableBytes': 12 * runtime.GIB, 'latestProbeAtUnix': 103, 'phases': phases, 'phasePlans': plans}
    return summary, samples, context, project


def test_bounded_profile_changes_real_cgroups_jvm_heaps_and_keeps_source_unchanged():
    original = {'services': {name: {'environment': {}, 'mem_limit': 10 * runtime.GIB}
                             for name in runtime.SERVICE_MEMORY_MIB}}
    bounded = runtime.bounded_config(original)
    assert original['services']['backend']['mem_limit'] == 10 * runtime.GIB
    assert sum(v['mem_limit'] for v in bounded['services'].values()) == 8448 * runtime.MIB
    assert all(v['mem_limit'] == v['memswap_limit'] for v in bounded['services'].values())
    assert '-Xmx1024m' in bounded['services']['backend']['environment']['JAVA_OPTS']
    assert '-Xmx512m' in bounded['services']['kafka']['environment']['KAFKA_HEAP_OPTS']
    assert bounded['services']['detection-worker']['mem_limit'] == 2 * runtime.GIB


def test_unbudgeted_service_fails_closed():
    with pytest.raises(ValueError, match='unbudgeted'):
        runtime.bounded_config({'services': {'another-db': {}}})


@pytest.mark.parametrize('field', ['diskAvailableBytes', 'memoryAvailableBytes'])
def test_phase_admission_retains_actual_disk_and_memory_reserves(field):
    probe = {'diskAvailableBytes': runtime.GIB + runtime.DISK_FLOOR,
             'memoryAvailableBytes': runtime.GIB + runtime.MEMORY_FLOOR}
    assert runtime.phase_admission('runtime-start', probe, runtime.GIB, runtime.GIB, {'measured': 1})['status'] == 'MEASUREMENT_ADMITTED'
    probe[field] -= 1
    assert runtime.phase_admission('runtime-start', probe, runtime.GIB, runtime.GIB, {'measured': 1})['status'] == 'FAIL_CLOSED'


def test_resource_evidence_is_recomputed_from_all_raw_samples():
    summary, samples, context, project = evidence()
    raw = b''.join((json.dumps(v) + '\n').encode() for v in samples)
    assert runtime.validate_resource_evidence(summary, raw, context, project)['sampleCount'] == 3


@pytest.mark.parametrize('damage', ['none', 'missing', 'wrong-limit', 'oom'])
def test_free_bge_transient_worker_requires_real_bounded_peak_and_zero_oom(damage):
    summary, samples, context, project = evidence()
    summary['requiredTransientServices'] = ['bge-verifier']
    worker = {'containerId': 'f' * 64, 'service': 'bge-verifier', 'image': 'sha256:' + '2' * 64,
        'memoryLimitBytes': runtime.BGE_VERIFIER_MEMORY, 'currentBytes': 0, 'peakBytes': 1024,
        'oom': 0, 'oomKills': 0, 'running': False, 'exitCode': 0}
    if damage == 'wrong-limit': worker['memoryLimitBytes'] = 256 * runtime.MIB
    if damage == 'oom': worker['oomKills'] = 1
    if damage != 'missing':
        samples[-1]['containers'] = samples[-1]['containers'] + [worker]
        summary['containers'][worker['containerId']] = worker
    raw = b''.join((json.dumps(row) + '\n').encode() for row in samples)
    summary['rawProbeSha256'] = hashlib.sha256(raw).hexdigest()
    if damage == 'none': assert runtime.validate_resource_evidence(summary, raw, context, project)['status'] == 'VERIFIED'
    else:
        with pytest.raises(ValueError): runtime.validate_resource_evidence(summary, raw, context, project)


@pytest.mark.parametrize('mutation', ['summary-minimum', 'summary-peak', 'oom', 'missing-daemon', 'late-probe', 'growth', 'raw-sha', 'phase-reserve'])
def test_resource_evidence_rejects_missing_or_falsified_pressure_measurements(mutation):
    summary, samples, context, project = evidence()
    if mutation == 'summary-minimum': summary['minimumDiskAvailableBytes'] += 1
    if mutation == 'summary-peak': summary['containers'] = copy.deepcopy(summary['containers']); next(iter(summary['containers'].values()))['peakBytes'] += 1
    if mutation == 'oom': samples[-1]['containers'] = copy.deepcopy(samples[-1]['containers']); samples[-1]['containers'][0]['oomKills'] = 1
    if mutation == 'missing-daemon':
        for sample in samples: sample['containers'] = sample['containers'][1:]
        summary['containers'] = {v['containerId']: v for v in samples[-1]['containers']}
    if mutation == 'late-probe': samples[-1]['probe']['capturedAtUnix'] += 3
    if mutation == 'growth': samples[-1]['probe']['hostDiskLossUpperBoundBytes'] = runtime.GIB + 1
    if mutation == 'phase-reserve': summary['phasePlans']['runtime-restore']['baselineProbe']['diskAvailableBytes'] = 0
    raw = b''.join((json.dumps(v) + '\n').encode() for v in samples)
    summary['rawProbeSha256'] = hashlib.sha256(raw).hexdigest()
    if mutation == 'raw-sha':
        first = '0' if summary['rawProbeSha256'][0] != '0' else '1'
        summary['rawProbeSha256'] = first + summary['rawProbeSha256'][1:]
    with pytest.raises(ValueError): runtime.validate_resource_evidence(summary, raw, context, project)


def test_pressure_records_raw_probe_before_any_container_operation(tmp_path, monkeypatch):
    ctx = SimpleNamespace(directory=tmp_path, project='doorhandle-rehearsal-' + 'a' * 12,
                          context=lambda: {}, owner={}, settings={})
    monitor = runtime.RuntimeResources(ctx)
    monkeypatch.setattr(runtime, 'host_probe', lambda _: {'capturedAtUnix': 1, 'diskTotalBytes': 40 * runtime.GIB,
        'diskAvailableBytes': runtime.DISK_FLOOR - 1, 'memoryAvailableBytes': 12 * runtime.GIB})
    monkeypatch.setattr(monitor, 'rows', lambda: (_ for _ in ()).throw(AssertionError('must not query Docker after pressure')))
    with pytest.raises(ValueError, match='DISK_FLOOR'): monitor.sample()
    assert json.loads(monitor.raw.read_text())['stopReasons'] == ['DISK_FLOOR']


def test_worker_reuses_verified_torch_and_adds_only_missing_pymysql(tmp_path):
    source = ROOT; old = tmp_path / 'old'; old.mkdir(); context = tmp_path / 'candidate'; context.mkdir()
    required = candidate.dependency_versions((ROOT / 'deploy/worker/requirements.txt').read_text())
    former = {name: version for name, version in required.items() if name != 'pymysql'}
    requirements = ''.join(name + '==' + version + '\n' for name, version in former.items())
    (old / 'requirements.txt').write_text(requirements)
    (old / 'cpu-wheels').mkdir()
    wheels = {}
    for name in ('torch.whl', 'torchvision.whl'):
        (old / 'cpu-wheels' / name).write_bytes(b'owned upstream wheel')
        wheels[name] = hashlib.sha256(b'owned upstream wheel').hexdigest()
    (old / 'BUILD_PROVENANCE.json').write_text(json.dumps({'sourceZipSha256': 'e' * 64, 'verifiedSourceFiles': 146, 'wheelSha256': wheels}))
    digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    result = {'versions': {name.replace('_', '-'): version for name, version in former.items()},
        'requirements': requirements, 'requirementsSha256': digest(old / 'requirements.txt'),
        'provenanceSha256': digest(old / 'BUILD_PROVENANCE.json')}
    image = 'sha256:' + 'f' * 64
    common = SimpleNamespace(PROJECT='original', container=lambda *_: {'Image': image}, require=runtime.require)
    ops = SimpleNamespace(docker=lambda *args, **_: json.dumps([{'Id': image, 'Config': {}, 'Size': 123}]
        if args[:2] == ('image', 'inspect') else result).encode())
    cutover = SimpleNamespace(canonical=lambda p: Path(p).resolve(strict=True), sha_file=digest)
    receipt = candidate.stage_worker_dependencies(source, context, old, SimpleNamespace(tag='ci-58-' + 'a' * 12), ops, common, cutover)
    dockerfile = (context / 'Dockerfile').read_text()
    assert dockerfile.startswith('FROM ' + image + '\n')
    assert 'pip install --no-cache-dir --no-deps' in dockerfile and 'PyMySQL==1.1.2' in dockerfile
    assert 'pip install --find-links' not in dockerfile and 'COPY kafka_detection_worker.py' in dockerfile
    assert receipt['addedNoDeps'] == ['PyMySQL==1.1.2']


def test_worker_rejects_unpinned_or_duplicate_requirements():
    for value in ('torch>=2', 'torch==2\ntorch==3'):
        with pytest.raises(ValueError): candidate.dependency_versions(value)


@pytest.mark.parametrize('tamper', [False, True])
def test_file_evidence_binds_runtime_cleanup_raw_and_original_phase_plans(tmp_path, tamper):
    validator = load('bounded_runtime_file_contract', 'script/jenkins/validate-runtime-resources.py')
    summary, samples, context, project = evidence()
    def write(name, value):
        path = tmp_path / name
        path.write_bytes((json.dumps(value, indent=2) + '\n').encode())
        return path
    for reference in summary['phases']:
        phase = reference['phase']; name = Path(reference['file']).name
        file = write(name, summary['phasePlans'][phase]); reference['sha256'] = runtime.sha_file(file)
    raw = b''.join((json.dumps(value) + '\n').encode() for value in samples)
    probes = tmp_path / 'resource-probes.jsonl'; probes.write_bytes(raw)
    summary_file = write('resource-summary.json', summary)
    resource_reference = {'file': 'checkout/work/runtime-acceptance/resource-summary.json', 'sha256': runtime.sha_file(summary_file)}
    proof = {**context, 'project': project, 'status': 'PASS', 'resourceEvidence': resource_reference,
             'loadScope': {'profile': runtime.RUNTIME_PROFILE, 'productionPerformanceVerified': False,
                           'productionCapacityVerified': False, 'allMandatoryScenariosRequired': True}}
    cleanup = {**context, 'project': project, 'status': 'STOPPED', 'resourceEvidence': resource_reference}
    proof_file, cleanup_file = write('runtime-acceptance.json', proof), write('cleanup.json', cleanup)
    if tamper:
        file = tmp_path / Path(summary['phases'][1]['file']).name
        value = json.loads(file.read_text()); value['growthEnvelopeBytes'] += 1; write(file.name, value)
        with pytest.raises(ValueError, match='Original runtime phase'):
            validator.validate_files(proof_file, cleanup_file, summary_file, probes, tmp_path)
    else:
        assert validator.validate_files(proof_file, cleanup_file, summary_file, probes, tmp_path)['status'] == 'VERIFIED'


def web_fixture(tmp_path):
    tag = 'ci-58-' + 'a' * 12
    source = tmp_path / 'releases' / tag; (source / 'deploy/nginx').mkdir(parents=True)
    work = source / 'work'; work.mkdir()
    for name in ('Dockerfile', 'nginx.monolith.conf'):
        (source / 'deploy/nginx' / name).write_bytes((ROOT / 'deploy/nginx' / name).read_bytes())
    verification = tmp_path / 'verification' / tag; checkout = verification / 'checkout'
    results = {}
    for frontend in ('frontend', 'frontend-agent'):
        distribution = checkout / frontend / 'dist'; distribution.mkdir(parents=True)
        (distribution / 'index.html').write_text('<html>' + frontend + '</html>')
        results[frontend] = {'installExitCode': 0, 'testExitCode': 0, 'buildExitCode': 0,
            'tests': {'passed': 10, 'failed': 0, 'skipped': 0}, 'artifact': candidate.frontend_inventory(distribution),
            'dependenciesCleanup': {'status': 'REMOVED', 'relativePath': frontend + '/node_modules'}}
    evidence_dir = checkout / 'work/ci-evidence'; evidence_dir.mkdir(parents=True)
    result_file = evidence_dir / 'receipt.json'
    result_file.write_text(json.dumps({'status': 'PASS', 'identity': {'instanceId': 'i-test'}, 'frontendResults': results}))
    envelope = verification / 'verification-receipt.json'
    envelope.write_text(json.dumps({'status': 'PASS', 'verificationExitCode': 0, 'release': tag, 'identity': {'instanceId': 'i-test'},
        'reportFiles': [{'path': 'reports/receipt.json', 'bytes': result_file.stat().st_size, 'sha256': runtime.sha_file(result_file)}]}))
    common = SimpleNamespace(require=runtime.require, write_json=lambda path, value: path.write_text(json.dumps(value)))
    cutover = SimpleNamespace(canonical=lambda path: Path(path).resolve(strict=True), sha_file=runtime.sha_file)
    return source, work, envelope, common, cutover


def test_web_candidate_contains_only_tested_artifacts_and_pinned_nginx_runtime(tmp_path):
    source, work, envelope, common, cutover = web_fixture(tmp_path)
    context = candidate.stage_web(source, work, envelope, runtime.sha_file(envelope), common, cutover)
    body = (context / 'Dockerfile').read_text()
    assert body.startswith('FROM nginx:') and 'node:' not in body and 'npm ' not in body
    assert 'COPY frontend-dist/' in body and 'COPY agent-dist/' in body
    receipt = json.loads((work / 'web-build-source.json').read_text())
    assert candidate.frontend_inventory(context / 'frontend-dist') == receipt['frontendArtifacts']['frontend']
    assert candidate.frontend_inventory(context / 'agent-dist') == receipt['frontendArtifacts']['frontend-agent']
    assert runtime.sha_file(context / 'nginx.conf') == receipt['nginxConfigurationSha256']


def test_web_candidate_refuses_changed_dist_even_with_unchanged_passing_receipt(tmp_path):
    source, work, envelope, common, cutover = web_fixture(tmp_path)
    (envelope.parent / 'checkout/frontend/dist/index.html').write_text('unverified replacement')
    with pytest.raises(ValueError, match='tested frontend artifact changed'):
        candidate.stage_web(source, work, envelope, runtime.sha_file(envelope), common, cutover)
