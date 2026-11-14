"""ECS-only contracts for the bounded real runtime, not production capacity."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests_python.browser_evidence_fixture import install as install_browser, CID as BROWSER_CID, IMAGE as BROWSER_IMAGE


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


runtime = load('bounded_runtime_resource_contract', 'script/docker/compact-runtime-acceptance.py')
candidate = load('bounded_worker_dependency_contract', 'script/docker/compact-candidate-build.py')
schema_guard = load('native_usage_receipt_contract', 'script/docker/compact-schema-guard.py')


def native_usage_fixture(tmp_path):
    directory = tmp_path / 'checkout/work/runtime-acceptance'; directory.mkdir(parents=True)
    context = {'schemaVersion': 1, 'kind': 'doorhandle-compact-runtime-acceptance', 'release': 'ci-58-' + 'a' * 12,
        'commit': 'a' * 40, 'sourceSha256': 'b' * 64, 'identity': {'instanceId': 'i-test', 'machineId': 'c' * 32},
        'acceptanceProfileSha256': 'd' * 64, 'candidateBuildSha256': 'e' * 64}
    phases = ('after-start', 'after-restart', 'after-volume-restore')
    references = {phase: {'file': 'checkout/work/runtime-acceptance/native-readback-' + phase + '.json',
                         'sha256': str(index) * 64} for index, phase in enumerate(phases, 1)}
    value = {**context, 'kind': 'doorhandle-native-semantic-activation', 'project': 'doorhandle-rehearsal-' + 'f' * 12,
        'candidateSha256': '1' * 64, 'status': 'VERIFIED_AND_ACTIVATED', 'candidateSemanticVerified': True,
        'productionDataMaterialized': False, 'productionPromotionAllowed': False, 'llmCalls': 0, 'paidModelCalls': 0,
        'verificationSubject': 'INDEPENDENT_REAL_BGE_CANDIDATE', 'appRuntimeValidationMode': 'ISOLATED_MOCK_QDRANT_RUNTIME',
        'vectorBackend': 'qdrant', 'storageGeneration': 'qdrant-bge-m3-v1',
        'verifications': {phase: {'readback': reference, 'semantic': {'file': 'unused-by-projection'}}
                          for phase, reference in references.items()}}
    file = directory / 'native-semantic-activation.json'
    def write():
        file.write_text(json.dumps(value), encoding='utf8'); file.chmod(0o600)
        return {'file': file.relative_to(tmp_path).as_posix(), 'sha256': runtime.sha_file(file)}
    ctx = SimpleNamespace(directory=directory, attempt=tmp_path, project=value['project'],
        legacy_candidate_sha=value['candidateSha256'], context=lambda: context,
        guard=schema_guard, cutover=SimpleNamespace(canonical=lambda path: Path(path).resolve(strict=True)),
        owner={'nativeVerifications': references})
    return ctx, value, write, write()


def test_native_usage_is_read_from_the_original_verified_activation(tmp_path):
    ctx, value, _write, reference = native_usage_fixture(tmp_path)
    actual = runtime.native_activation_usage(ctx, reference)
    assert actual == {'llmCalls': value['llmCalls'], 'paidModelCalls': value['paidModelCalls']}
    assert reference['sha256'] == runtime.sha_file(ctx.directory / 'native-semantic-activation.json')


@pytest.mark.parametrize('damage', ['missing-count', 'bool-llm', 'nonzero-llm', 'nonzero-paid', 'foreign-build',
    'different-candidate', 'changed-bytes', 'different-readback', 'wrong-path', 'unactivated'])
def test_native_usage_rejects_unverified_counts_or_foreign_activation(tmp_path, damage):
    ctx, value, write, reference = native_usage_fixture(tmp_path)
    if damage == 'missing-count': value.pop('llmCalls')
    elif damage == 'bool-llm': value['llmCalls'] = False
    elif damage == 'nonzero-llm': value['llmCalls'] = 1
    elif damage == 'nonzero-paid': value['paidModelCalls'] = 1
    elif damage == 'foreign-build': value['commit'] = '2' * 40
    elif damage == 'different-candidate': value['candidateSha256'] = '2' * 64
    elif damage == 'changed-bytes': value['project'] = 'changed-after-receipt'
    elif damage == 'different-readback': value['verifications']['after-start']['readback'] = {'file': 'another.json', 'sha256': '3' * 64}
    elif damage == 'wrong-path': reference['file'] = '../native-semantic-activation.json'
    else: value['status'] = 'PREPARED'
    if damage != 'wrong-path':
        rewritten = write()
        if damage != 'changed-bytes': reference = rewritten
    with pytest.raises(ValueError): runtime.native_activation_usage(ctx, reference)


def evidence(include_browser=False, observability=True):
    context = {'schemaVersion': 1, 'kind': 'doorhandle-compact-runtime-acceptance', 'release': 'ci-58-' + 'a' * 12,
        'commit': 'a' * 40, 'sourceSha256': 'b' * 64, 'identity': {'instanceId': 'i-test', 'machineId': 'c' * 32},
        'acceptanceProfileSha256': 'd' * 64, 'candidateBuildSha256': 'e' * 64}
    project = 'doorhandle-rehearsal-' + 'f' * 12
    daemons = sorted(runtime.CORE_DAEMON_SERVICES if observability else runtime.CORE_DAEMON_SERVICES - {'prometheus', 'alertmanager'})
    metrics = [{'containerId': format(index + 1, '064x'), 'service': name, 'image': 'sha256:' + '1' * 64,
        'memoryLimitBytes': runtime.SERVICE_MEMORY_MIB[name] * runtime.MIB, 'currentBytes': 128,
        'peakBytes': 256, 'oom': 0, 'oomKills': 0, 'running': True, 'exitCode': 0} for index, name in enumerate(daemons)]
    if include_browser:
        metrics.extend([{'containerId': 'e' * 64, 'service': 'bge-qdrant', 'image': 'sha256:' + '3' * 64,
            'memoryLimitBytes': 512 * runtime.MIB, 'currentBytes': 0, 'peakBytes': 1024,
            'oom': 0, 'oomKills': 0, 'running': False, 'exitCode': 0},
            {'containerId': 'f' * 64, 'service': 'bge-verifier', 'image': 'sha256:' + '2' * 64,
            'memoryLimitBytes': runtime.BGE_VERIFIER_MEMORY, 'currentBytes': 0, 'peakBytes': 1024,
            'oom': 0, 'oomKills': 0, 'running': False, 'exitCode': 0},
            {'containerId': BROWSER_CID, 'service': 'collaboration-browser', 'image': BROWSER_IMAGE,
             'memoryLimitBytes': runtime.BROWSER_MEMORY, 'currentBytes': 0, 'peakBytes': 1024,
             'oom': 0, 'oomKills': 0, 'running': False, 'exitCode': 0}])
    plans, phases, samples = {}, [], []
    phase_names = ('runtime-start', 'runtime-backup', 'runtime-restore', 'runtime-browser') if include_browser else ('runtime-start', 'runtime-backup', 'runtime-restore')
    for index, phase in enumerate(phase_names, 1):
        baseline = {'capturedAtUnix': 100 + index, 'diskTotalBytes': 40 * runtime.GIB,
            'diskAvailableBytes': 8 * runtime.GIB, 'memoryAvailableBytes': 12 * runtime.GIB}
        measured = {'actualBytes': 100}
        if observability: measured['observabilityWritableGrowthEnvelopeBytes'] = runtime.OBSERVABILITY_GROWTH_BYTES
        plans[phase] = runtime.phase_admission(phase, baseline, runtime.GIB, 0, measured)
        phases.append({'phase': phase, 'file': 'checkout/work/runtime-acceptance/resource-phase-' + str(index) + '-' + phase + '.json',
                       'sha256': str(index) * 64})
        samples.append({'probe': {**baseline, 'phase': phase, 'hostDiskLossUpperBoundBytes': 0,
                                  'diskLossOwnershipProof': False}, 'containers': [row for row in metrics if phase=='runtime-browser' or row['service']!='collaboration-browser'], 'stopReasons': []})
    raw = b''.join((json.dumps(row) + '\n').encode() for row in samples)
    summary = {**context, 'kind': 'doorhandle-bounded-runtime-resources', 'project': project,
        'profile': runtime.RUNTIME_PROFILE, 'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'productionCapacityVerified': False,
        'status': 'MEASURED_FOR_BOUNDED_SCENARIOS', 'pollIntervalSeconds': 2, 'diskFloorBytes': runtime.DISK_FLOOR,
        'memoryFloorBytes': runtime.MEMORY_FLOOR, 'rawProbeFile': 'checkout/work/runtime-acceptance/resource-probes.jsonl',
        'rawProbeSha256': hashlib.sha256(raw).hexdigest(), 'samples': len(phase_names), 'containers': {v['containerId']: v for v in metrics},
        'requiredDaemonServices': daemons, 'minimumDiskAvailableBytes': 8 * runtime.GIB,
        'minimumMemoryAvailableBytes': 12 * runtime.GIB, 'latestProbeAtUnix': 100+len(phase_names), 'phases': phases, 'phasePlans': plans}
    if include_browser: summary['requiredTransientServices'] = ['bge-qdrant', 'bge-verifier', 'collaboration-browser']
    if observability: summary['observabilityRequired'] = True
    return summary, samples, context, project


def test_bounded_profile_changes_real_cgroups_jvm_heaps_and_keeps_source_unchanged():
    original = {'services': {name: {'environment': {}, 'mem_limit': 10 * runtime.GIB}
                             for name in set(runtime.SERVICE_MEMORY_MIB) - set(runtime.TRANSIENT_SERVICE_MEMORY_MIB)}}
    bounded = runtime.bounded_config(original)
    assert original['services']['backend']['mem_limit'] == 10 * runtime.GIB
    assert sum(v['mem_limit'] for v in bounded['services'].values()) == (8448 + runtime.SERVICE_MEMORY_MIB['qdrant-storage-init'] + 640) * runtime.MIB
    assert 'chroma' not in bounded['services'] and 'bge-qdrant' not in bounded['services']
    assert bounded['services']['qdrant']['mem_limit'] == 512 * runtime.MIB
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


@pytest.mark.parametrize('damage', ['missing-phase', 'omitted-browser', 'wrong-limit', 'zero-peak', 'phase-reserve', 'missing-samples', 'backwards', 'premature-browser'])
def test_browser_requires_its_fourth_admitted_phase_and_actual_external_peak(damage):
    summary,samples,context,project=evidence(include_browser=True)
    if damage=='missing-phase':summary['phasePlans'].pop('runtime-browser')
    if damage=='omitted-browser':
        for sample in samples:sample['containers']=[row for row in sample['containers'] if row['service']!='collaboration-browser']
        summary['containers'].pop(BROWSER_CID)
    if damage=='wrong-limit':summary['containers'][BROWSER_CID]['memoryLimitBytes']=3*runtime.GIB
    if damage=='zero-peak':summary['containers'][BROWSER_CID]['peakBytes']=0
    if damage=='phase-reserve':summary['phasePlans']['runtime-browser']['baselineProbe']['diskAvailableBytes']=runtime.DISK_FLOOR
    if damage=='missing-samples':samples[-1]['probe']['phase']='runtime-restore';samples[-1]['containers']=[row for row in samples[-1]['containers'] if row['service']!='collaboration-browser']
    if damage=='backwards':samples[2]['probe']['phase']='runtime-start'
    if damage=='premature-browser':samples[0]['containers'].append(summary['containers'][BROWSER_CID])
    raw=b''.join((json.dumps(row)+'\n').encode() for row in samples);summary['rawProbeSha256']=hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):runtime.validate_resource_evidence(summary,raw,context,project)


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


def worker_dependency_fixture(tmp_path, *, installed_pymysql=False, current_requirements=False):
    source = tmp_path / 'source'; old = tmp_path / 'old'; old.mkdir(); context = tmp_path / 'candidate'; context.mkdir()
    for original in candidate.worker_source_files(ROOT).values():
        destination = source / original.relative_to(ROOT); destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(original.read_bytes())
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
    if installed_pymysql: result['versions']['pymysql'] = '1.1.2'
    if current_requirements:
        result.update(requirements=(source / 'deploy/worker/requirements.txt').read_text(encoding='utf8'),
            requirementsSha256=digest(source / 'deploy/worker/requirements.txt'),
            versions={name.replace('_', '-'): version for name, version in required.items()})
    model = old / 'model-source'; model.mkdir(); (model / 'engine').mkdir()
    for directory in (model, model / 'engine'): directory.chmod(0o755)
    for name, body, mode in (('engine/code.py', b'verified original source', 0o755), ('config.yml', b'original config', 0o644),
        ('MANIFEST_SHA256.json', b'original manifest', 0o644), ('CHECKPOINT_METADATA.json', b'original metadata', 0o644),
        ('DINOv3-LICENSE.md', b'original retained license keeper', 0o444),
        ('BUILD_PROVENANCE.json', b'original retained provenance keeper', 0o444)):
        path = model / name; path.write_bytes(body); path.chmod(mode)
    image = 'sha256:' + 'f' * 64
    common = SimpleNamespace(PROJECT='original', container=lambda *_: {'Image': image}, require=runtime.require)
    ops = SimpleNamespace(docker=lambda *args, **_: json.dumps([{'Id': image, 'Config': {}, 'Size': 123}]
        if args[:2] == ('image', 'inspect') else result).encode())
    cutover = SimpleNamespace(canonical=lambda p: Path(p).resolve(strict=True), sha_file=digest)
    return source, context, old, SimpleNamespace(tag='ci-58-' + 'a' * 12, mem0_dependency_image=image), ops, common, cutover, result


@pytest.mark.parametrize('installed_pymysql', [False, True])
def test_worker_reuses_verified_torch_and_adds_only_missing_pymysql(tmp_path, installed_pymysql):
    source, context, old, args, ops, common, cutover, _result = worker_dependency_fixture(tmp_path, installed_pymysql=installed_pymysql)
    model = old / 'model-source'
    keepers = {name: ((model / name).read_bytes(), (model / name).stat().st_ino, (model / name).stat().st_mode & 0o777)
               for name in ('DINOv3-LICENSE.md', 'BUILD_PROVENANCE.json')}
    receipt = candidate.stage_worker_dependencies(source, context, old, args, ops, common, cutover)
    dockerfile = (context / 'Dockerfile').read_text()
    assert 'FROM ' + receipt['baseImage'] + '\n' in dockerfile
    assert ('pip install --no-cache-dir --no-deps' in dockerfile) == (not installed_pymysql)
    assert 'pip install --find-links' not in dockerfile and dockerfile.count('COPY rootfs/ /\n') == 1
    assert receipt['addedNoDeps'] == ([] if installed_pymysql else ['PyMySQL==1.1.2'])
    assert receipt['requirementsClosure'] == {'mode': 'LEGACY_UPSTREAM_WITH_OPTIONAL_PYMYSQL',
        'baseRequirementsSha256': cutover.sha_file(old / 'requirements.txt'),
        'legacyRequirementsSha256': cutover.sha_file(old / 'requirements.txt'),
        'fixedSourceRequirementsSha256': cutover.sha_file(source / 'deploy/worker/requirements.txt')}
    # The shared native resource algorithm counts actual RUN/COPY instructions.
    import re
    assert len(re.findall(r'^\s*(?:RUN|COPY)\b', dockerfile, re.M | re.I)) == (1 if installed_pymysql else 2)
    assert receipt['sourceCopyInstructions'] == 1
    original = (source / 'deploy/worker/Dockerfile').read_text()
    assert original[original.index('ENV '):original.index('COPY ')] in dockerfile
    assert original[original.index('USER app'): ] in dockerfile
    rootfs = context / 'rootfs'
    assert set(path.name for path in context.iterdir()) == {'Dockerfile', 'rootfs'}
    for directory in (rootfs, rootfs / 'app', rootfs / 'app/licenses', rootfs / 'opt'):
        assert directory.stat().st_mode & 0o777 == 0o755
    inputs = candidate.worker_source_files(source); inputs.pop('Dockerfile')
    inputs['BUILD_PROVENANCE.json'] = old / 'BUILD_PROVENANCE.json'
    assert set(receipt['runtimeSourceLayout']) == set(inputs)
    for name, original_file in inputs.items():
        target = rootfs / receipt['runtimeSourceLayout'][name]
        assert target.read_bytes() == original_file.read_bytes()
        assert target.stat().st_mode & 0o777 == 0o644
    assert {path.name for path in (rootfs / 'app').glob('*.py')} == set(candidate.WORKER_PYTHON_FILES)
    for path in model.rglob('*'):
        relative = path.relative_to(model); target = rootfs / 'opt/model-source' / relative
        if relative.as_posix() in keepers: continue
        assert target.stat().st_mode & 0o777 == path.stat().st_mode & 0o777
        if path.is_file():
            assert target.read_bytes() == path.read_bytes() and target.stat().st_ino == path.stat().st_ino
    for name, (body, inode, mode) in keepers.items():
        keeper = model / name; replacement = rootfs / 'opt/model-source' / name
        assert (keeper.read_bytes(), keeper.stat().st_ino, keeper.stat().st_mode & 0o777) == (body, inode, mode)
        assert replacement.stat().st_ino != inode
    assert receipt['modelSourceModePreservation'] == 'COMPLETE_HARDLINKED_TREE'


def test_worker_can_reuse_exact_current_requirements_after_compact_cutover_without_installing(tmp_path):
    source, context, old, args, ops, common, cutover, actual = worker_dependency_fixture(tmp_path, current_requirements=True)
    receipt = candidate.stage_worker_dependencies(source, context, old, args, ops, common, cutover)
    body = (context / 'Dockerfile').read_text()
    assert receipt['requirementsClosure'] == {'mode': 'EXACT_FIXED_SOURCE_REQUIREMENTS',
        'baseRequirementsSha256': cutover.sha_file(source / 'deploy/worker/requirements.txt'),
        'legacyRequirementsSha256': cutover.sha_file(old / 'requirements.txt'),
        'fixedSourceRequirementsSha256': cutover.sha_file(source / 'deploy/worker/requirements.txt')}
    assert receipt['originalProvenanceSha256'] == cutover.sha_file(old / 'BUILD_PROVENANCE.json')
    assert receipt['addedNoDeps'] == [] and 'RUN ' not in body and 'pip install' not in body
    assert body.count('COPY rootfs/ /\n') == 1
    assert receipt['verifiedExistingVersions'] == actual['versions'] == receipt['requiredVersions']
    assert (context / 'rootfs/app/requirements.txt').read_bytes() == (source / 'deploy/worker/requirements.txt').read_bytes()


def test_worker_adds_fixed_telemetry_without_reinstalling_or_unpinning_torch(tmp_path):
    source, context, old, args, ops, common, cutover, actual = worker_dependency_fixture(tmp_path)
    telemetry = {'opentelemetry-api', 'opentelemetry-sdk', 'opentelemetry-exporter-otlp-proto-http', 'prometheus-client'}
    legacy = {name: version for name, version in candidate.dependency_versions(actual['requirements']).items() if name not in telemetry}
    original = ''.join(name + '==' + version + '\n' for name, version in legacy.items())
    (old / 'requirements.txt').write_text(original)
    actual.update(requirements=original, requirementsSha256=cutover.sha_file(old / 'requirements.txt'))
    for name in telemetry: actual['versions'].pop(name, None)
    receipt = candidate.stage_worker_dependencies(source, context, old, args, ops, common, cutover)
    body = (context / 'Dockerfile').read_text()
    assert len(receipt['telemetrySupplementPins']) == 4
    assert 'pip install --find-links' not in body and 'pip install -r' not in body
    assert '--constraint /app/runtime-base-constraints.txt' in body and '--report /app/worker-telemetry-install.json' in body
    assert 'pip check && python -c' in body and '--retries 0' in body
    assert 'torch==2.5.1+cpu' in (context / 'rootfs/app/runtime-base-constraints.txt').read_text()
    assert body.index('COPY rootfs/ /') < body.index('RUN pip install')
    assert receipt['runtimeDependencyVerification'] == 'CONTROLLED_BUILD_PIP_CHECK_AND_ALL_DIRECT_PIN_READBACK'


@pytest.mark.parametrize('damage', ['legacy-digest', 'unknown-digest', 'missing-pymysql', 'wrong-pymysql',
    'extra-requirement', 'different-requirement', 'wrong-upstream-provenance', 'changed-fixed-bytes'])
def test_worker_current_requirements_closure_refuses_approximate_or_incomplete_matches(tmp_path, damage):
    source, context, old, args, ops, common, cutover, actual = worker_dependency_fixture(tmp_path, current_requirements=True)
    if damage == 'legacy-digest': actual['requirementsSha256'] = cutover.sha_file(old / 'requirements.txt')
    elif damage == 'unknown-digest': actual['requirementsSha256'] = '0' * 64
    elif damage == 'missing-pymysql': actual['versions'].pop('pymysql')
    elif damage == 'wrong-pymysql': actual['versions']['pymysql'] = '1.1.1'
    elif damage == 'extra-requirement': actual['requirements'] += '\nother==1.0\n'
    elif damage == 'different-requirement': actual['requirements'] = actual['requirements'].replace('torch==2.5.1+cpu', 'torch==2.5.0+cpu')
    elif damage == 'wrong-upstream-provenance': actual['provenanceSha256'] = '0' * 64
    elif damage == 'changed-fixed-bytes':
        with (source / 'deploy/worker/requirements.txt').open('a', encoding='utf8') as stream:
            stream.write('\n# source bytes changed after the dependency image\n')
    with pytest.raises(ValueError): candidate.stage_worker_dependencies(source, context, old, args, ops, common, cutover)
    assert not (context / 'rootfs').exists() and not (context / 'Dockerfile').exists()


@pytest.mark.parametrize('damage', ['extra-copy', 'extra-run', 'lowercase-run', 'changed-install', 'root-user', 'wrong-schema'])
def test_worker_single_overlay_refuses_unreviewed_source_or_runtime_changes(damage):
    body = (ROOT / 'deploy/worker/Dockerfile').read_text()
    if damage == 'extra-copy': body += '\nCOPY unknown /app/\n'
    elif damage == 'extra-run': body += '\nRUN pip install another\n'
    elif damage == 'lowercase-run': body += '\n  run pip install another\n'
    elif damage == 'changed-install': body = body.replace('pip check', 'pip check && touch /tmp/unknown')
    elif damage == 'root-user': body = body.replace('USER app', 'USER root')
    elif damage == 'wrong-schema': body = body.replace('compact29-v1', 'other-schema')
    with pytest.raises(ValueError): candidate.worker_runtime_dockerfile(body, 'sha256:' + 'f' * 64, add_pymysql=False)


@pytest.mark.parametrize('damage', ['link', 'private-file', 'private-directory'])
def test_worker_overlay_rejects_unclosed_or_unreadable_model_sources_without_changing_keepers(tmp_path, damage):
    source, context, old, args, ops, common, cutover, _result = worker_dependency_fixture(tmp_path)
    keeper = old / 'model-source/engine/code.py'; before = keeper.read_bytes()
    if damage == 'link': (old / 'model-source/link.py').symlink_to(keeper)
    elif damage == 'private-file': keeper.chmod(0o600)
    elif damage == 'private-directory': (old / 'model-source/engine').chmod(0o700)
    with pytest.raises(ValueError): candidate.stage_worker_dependencies(source, context, old, args, ops, common, cutover)
    assert keeper.read_bytes() == before and not (context / 'Dockerfile').exists()


@pytest.mark.parametrize('damage', ['package', 'requirements', 'provenance'])
def test_worker_overlay_retains_original_dependency_and_provenance_rejection(tmp_path, damage):
    source, context, old, args, ops, common, cutover, actual = worker_dependency_fixture(tmp_path)
    if damage == 'package': actual['versions']['torch'] = 'other'
    elif damage == 'requirements': actual['requirementsSha256'] = '0' * 64
    elif damage == 'provenance': actual['provenanceSha256'] = '0' * 64
    with pytest.raises(ValueError): candidate.stage_worker_dependencies(source, context, old, args, ops, common, cutover)
    assert not (context / 'rootfs').exists() and not (context / 'Dockerfile').exists()


def test_worker_run_write_envelope_is_only_reserved_for_the_verified_missing_dependency():
    import ast
    tree = ast.parse(Path(candidate.__file__).read_text())
    specifications = [node for node in ast.walk(tree) if isinstance(node, ast.Dict)
        and any(isinstance(key, ast.Constant) and key.value == 'service'
            and isinstance(value, ast.Constant) and value.value == 'detection-worker' for key, value in zip(node.keys, node.values))]
    assert len(specifications) == 1
    envelope = next(value for key, value in zip(specifications[0].keys, specifications[0].values)
                    if isinstance(key, ast.Constant) and key.value == 'runWriteEnvelopeBytes')
    expected = ast.parse("512 * resources.MIB if dependencies['telemetrySupplementPins'] "
                         "else 64 * resources.MIB if dependencies['addedNoDeps'] else 0", mode='eval').body
    assert ast.dump(envelope) == ast.dump(expected)


def test_worker_rejects_unpinned_or_duplicate_requirements():
    for value in ('torch>=2', 'torch==2\ntorch==3'):
        with pytest.raises(ValueError): candidate.dependency_versions(value)


def mem0_dependency_fixture(tmp_path):
    source = tmp_path / 'source'; work = source / 'work'; work.mkdir(parents=True)
    for name in (*candidate.MEM0_SOURCE_FILES, 'deploy/mem0/Dockerfile'):
        destination = source / name; destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    # The dependency image may contain old application code; all runtime source
    # must come from the current fixed checkout instead.
    with (source / 'memory_service/main.py').open('a', encoding='utf8') as stream:
        stream.write('\n# current fixed-source fixture\n')
    requirements = (source / candidate.MEM0_SOURCE_FILES[0]).read_text(encoding='utf8')
    versions = candidate.dependency_versions(requirements)
    actual = {'requirements': requirements, 'requirementsSha256': hashlib.sha256(requirements.encode()).hexdigest(),
        'versions': versions.copy(), 'pipCheckReturnCode': 0, 'pythonVersion': [3, 12],
        'sourceFiles': [Path(name).name for name in candidate.MEM0_SOURCE_FILES[1:-1] if Path(name).name != 'embedding_config.py'],
        'sourceLinks': False, 'sourceDirectories': [],
        'appFiles': [Path(name).name for name in candidate.MEM0_SOURCE_FILES if Path(name).name != 'embedding_config.py'],
        **{name: 10001 for name in ('uid', 'gid', 'dataUid', 'dataGid', 'appUid', 'appGid')}}
    image = 'sha256:' + 'f' * 64; row = {'Id': image, 'Config': {}, 'Size': 123}
    calls = []
    def docker(*args, **kwargs):
        calls.append((args, kwargs))
        if args[:2] == ('image', 'inspect'):
            assert args == ('image', 'inspect', image)
            return json.dumps([row]).encode()
        assert args[0] == 'run'
        return json.dumps(actual).encode()
    common = SimpleNamespace(PROJECT='original', container=lambda project, service:
        {'Image': image} if (project, service) == ('original', 'mem0') else None,
        require=runtime.require, write_json=lambda path, value: path.write_text(json.dumps(value)))
    cutover = SimpleNamespace(canonical=lambda path: Path(path).resolve(strict=True), sha_file=runtime.sha_file)
    return source, work, SimpleNamespace(tag='ci-58-' + 'a' * 12, mem0_dependency_image=image), SimpleNamespace(docker=docker), common, cutover, actual, row, calls


def test_mem0_reuses_exact_dependencies_and_replaces_all_current_source_with_one_copy(tmp_path):
    source, work, args, ops, common, cutover, actual, row, calls = mem0_dependency_fixture(tmp_path)
    context = candidate.stage_mem0(source, work, args, ops, common, cutover)
    body = (context / 'Dockerfile').read_text()
    assert 'FROM ' + row['Id'] + '\n' in body
    assert sum(line.startswith('COPY ') for line in body.splitlines()) == 1
    assert not any(line.startswith(('RUN ', 'ARG ', 'ADD ', 'ONBUILD ')) for line in body.splitlines())
    original = (source / 'deploy/mem0/Dockerfile').read_text()
    for declaration in ('LABEL io.doorhandle.memory-protocol="2"',
        'LABEL io.doorhandle.memory-embedding-profile="siliconflow-bge-m3-v1"',
        'LABEL io.doorhandle.model-config-format="1"', 'WORKDIR /app', 'USER app', 'EXPOSE 8081'):
        assert declaration in original and declaration in body
    assert original[original.index('ENV '):original.index('COPY ')] in body
    assert original[original.index('HEALTHCHECK '):] in body
    receipt = json.loads((work / 'mem0-build-source.json').read_text())
    assert receipt['sourceDockerfileSha256'] == runtime.sha_file(source / 'deploy/mem0/Dockerfile')
    assert receipt['runtimeDockerfileSha256'] == runtime.sha_file(context / 'Dockerfile')
    assert set(receipt['files']) == set(candidate.MEM0_SOURCE_FILES)
    assert set(path.name for path in context.iterdir()) == {'Dockerfile', *(Path(name).name for name in candidate.MEM0_SOURCE_FILES)}
    for name in candidate.MEM0_SOURCE_FILES:
        assert (context / Path(name).name).read_bytes() == (source / name).read_bytes()
        assert receipt['files'][name] == runtime.sha_file(source / name)
    dependency = receipt['dependencyReuse']
    assert dependency['mode'] == 'IMMUTABLE_DEPENDENCY_BASE_WITH_FIXED_SOURCE'
    assert dependency['baseImage'] == row['Id']
    assert dependency['requiredVersions'] == dependency['verifiedExistingVersions'] == actual['versions']
    assert dependency['addedDependencies'] == [] and dependency['pipCheckReturnCode'] == 0
    assert dependency['sourceCopyInstructions'] == 1
    assert dependency['replacedBaseSourceFiles'] == actual['sourceFiles'] and 'embedding_config.py' not in actual['sourceFiles']
    assert (context / 'embedding_config.py').is_file()
    probe, options = calls[1]
    for token in ('--rm', '--read-only', 'none', '--pull', 'never', '--cap-drop', 'ALL', 'no-new-privileges:true', '-I', '-B'):
        assert token in probe
    assert probe[probe.index('--memory') + 1] == probe[probe.index('--memory-swap') + 1] == '256m'
    assert probe[probe.index('--pids-limit') + 1] == '32' and options['timeout'] == 45
    assert 'pip' in probe[-1] and "'check'" in probe[-1] and 'pip install' not in probe[-1]
    assert 'os.environ' not in probe[-1]


def test_mem0_adapts_only_the_admitted_tool_dependency_base_without_pip(tmp_path, monkeypatch):
    source, work, args, ops, common, cutover, actual, row, calls = mem0_dependency_fixture(tmp_path)
    args.mem0_dependency_image = None
    args.root = str(tmp_path); args.commit = 'a' * 40; args.source_sha256 = 'b' * 64
    args.instance_id = 'i-test'; args.machine_id = 'c' * 32
    actual.update(requirements='', requirementsSha256=hashlib.sha256(b'').hexdigest(),
                  sourceFiles=[], appFiles=[], uid=1000, gid=1000, dataUid=None, dataGid=None, appUid=None, appGid=None)
    row['Config']['Entrypoint'] = ['/usr/local/bin/python']
    monkeypatch.setattr(candidate, 'module', lambda name, path: SimpleNamespace(admit=lambda *args, **kwargs:
        ({'images': {'python': row['Id']}}, 'e' * 64)))
    context = candidate.stage_mem0(source, work, args, ops, common, cutover)
    body = (context / 'Dockerfile').read_text()
    assert 'ENTRYPOINT []' in body and 'USER root' in body and 'USER app' in body
    assert body.count('RUN ') == 1 and 'pip install' not in body
    assert 'groupadd --gid 10001 app' in body and 'mkdir -p /data' in body
    receipt = json.loads((work / 'mem0-build-source.json').read_text())['dependencyReuse']
    assert receipt['appIdentityRunInstructions'] == 1 and receipt['toolManifestSha256'] == 'e' * 64
    assert receipt['mode'] == 'IMMUTABLE_TOOL_DEPENDENCY_BASE_WITH_APP_IDENTITY_AND_FIXED_SOURCE'
    assert receipt['addedDependencies'] == []


@pytest.mark.parametrize('damage', ['missing-package', 'wrong-version', 'different-requirements', 'extra-requirement',
    'bad-requirements-digest', 'failed-pip-check', 'bool-pip-check', 'wrong-python', 'root-user', 'wrong-data-owner',
    'missing-app-user', 'extra-old-module', 'linked-old-module', 'old-module-directory', 'extra-old-file'])
def test_mem0_reuse_refuses_unproven_dependencies_or_runtime_identity(tmp_path, damage):
    source, work, args, ops, common, cutover, actual, _row, _calls = mem0_dependency_fixture(tmp_path)
    if damage == 'missing-package': actual['versions'].pop('mem0ai')
    elif damage == 'wrong-version': actual['versions']['mem0ai'] = '0.0.0'
    elif damage == 'different-requirements': actual['requirements'] = actual['requirements'].replace('mem0ai==2.0.19', 'mem0ai==0.0.0')
    elif damage == 'extra-requirement': actual['requirements'] += '\nother==1.0\n'
    elif damage == 'bad-requirements-digest': actual['requirementsSha256'] = '0' * 64
    elif damage == 'failed-pip-check': actual['pipCheckReturnCode'] = 1
    elif damage == 'bool-pip-check': actual['pipCheckReturnCode'] = False
    elif damage == 'wrong-python': actual['pythonVersion'] = [3, 11]
    elif damage == 'root-user': actual['uid'] = 0
    elif damage == 'wrong-data-owner': actual['dataUid'] = 0
    elif damage == 'missing-app-user': actual['appUid'] = 0
    elif damage == 'extra-old-module': actual['sourceFiles'].append('openai.py')
    elif damage == 'linked-old-module': actual['sourceLinks'] = True
    elif damage == 'old-module-directory': actual['sourceDirectories'].append('openai')
    elif damage == 'extra-old-file': actual['appFiles'].append('old-config.json')
    with pytest.raises(ValueError): candidate.stage_mem0(source, work, args, ops, common, cutover)
    assert not (work / 'compact-mem0-build').exists() and not (work / 'mem0-build-source.json').exists()


@pytest.mark.parametrize('damage', ['image-id', 'volume', 'entrypoint', 'onbuild'])
def test_mem0_reuse_refuses_changed_image_identity_or_inherited_hooks(tmp_path, damage):
    source, work, args, ops, common, cutover, _actual, row, calls = mem0_dependency_fixture(tmp_path)
    if damage == 'image-id': row['Id'] = 'sha256:' + '0' * 64
    elif damage == 'volume': row['Config']['Volumes'] = {'/data': {}}
    elif damage == 'entrypoint': row['Config']['Entrypoint'] = ['old-entrypoint']
    elif damage == 'onbuild': row['Config']['OnBuild'] = ['RUN another-install']
    with pytest.raises(ValueError): candidate.stage_mem0(source, work, args, ops, common, cutover)
    assert len(calls) == 1


@pytest.mark.parametrize('damage', ['extra-source', 'extra-run', 'lowercase-run', 'extra-add', 'onbuild', 'changed-install', 'root-user', 'other-workdir'])
def test_mem0_reuse_requires_the_reviewed_complete_source_only_dockerfile(damage):
    body = (ROOT / 'deploy/mem0/Dockerfile').read_text()
    if damage == 'extra-source': body = body.replace('memory_service/main.py ', 'memory_service/extra.py memory_service/main.py ')
    elif damage == 'extra-run': body += '\nRUN pip install extra\n'
    elif damage == 'lowercase-run': body += '\n  run pip install extra\n'
    elif damage == 'extra-add': body += '\nADD unknown /app/\n'
    elif damage == 'onbuild': body += '\nONBUILD COPY unknown /app/\n'
    elif damage == 'changed-install': body = body.replace('--retries 5', '--retries 6')
    elif damage == 'root-user': body = body.replace('USER app', 'USER root')
    elif damage == 'other-workdir': body = body.replace('WORKDIR /app', 'WORKDIR /other')
    with pytest.raises(ValueError): candidate.mem0_runtime_dockerfile(body, 'sha256:' + 'f' * 64)


def test_mem0_write_envelope_only_covers_tool_base_identity_without_pip_build_arguments():
    import ast
    tree = ast.parse(Path(candidate.__file__).read_text())
    specifications = [node for node in ast.walk(tree) if isinstance(node, ast.Dict)
        and any(isinstance(key, ast.Constant) and key.value == 'service'
            and isinstance(value, ast.Constant) and value.value == 'mem0' for key, value in zip(node.keys, node.values))]
    assert len(specifications) == 1
    assert {key.value for key in specifications[0].keys} == {'service', 'context', 'tag', 'runWriteEnvelopeBytes'}
    envelope = next(value for key, value in zip(specifications[0].keys, specifications[0].values)
                    if isinstance(key, ast.Constant) and key.value == 'runWriteEnvelopeBytes')
    expected = ast.parse('0 if args.mem0_dependency_image else 8 * resources.MIB', mode='eval').body
    assert ast.dump(envelope) == ast.dump(expected)


@pytest.mark.parametrize('tamper', [False, True])
def test_file_evidence_binds_runtime_cleanup_raw_and_original_phase_plans(tmp_path, tamper):
    validator = load('bounded_runtime_file_contract', 'script/jenkins/validate-runtime-resources.py')
    summary, samples, context, project = evidence(include_browser=True, observability=False)
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
    install_browser(tmp_path, context, project, proof, cleanup)
    from tests_python.test_compact_cutover import fixture_build_resources
    proof['fixtureBuildResources'] = {'browser': fixture_build_resources(tmp_path, context, 'browser')[0]}
    build_directory = tmp_path / 'checkout/work/runtime-acceptance/controlled-build-browser'
    proof_file, cleanup_file = write('runtime-acceptance.json', proof), write('cleanup.json', cleanup)
    if tamper:
        file = tmp_path / Path(summary['phases'][1]['file']).name
        value = json.loads(file.read_text()); value['growthEnvelopeBytes'] += 1; write(file.name, value)
        with pytest.raises(ValueError, match='Original runtime phase'):
            validator.validate_files(proof_file, cleanup_file, summary_file, probes, tmp_path, fixture_directory=build_directory)
    else:
        assert validator.validate_files(proof_file, cleanup_file, summary_file, probes, tmp_path, fixture_directory=build_directory)['status'] == 'VERIFIED'


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
