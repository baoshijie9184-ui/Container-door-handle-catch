"""ECS-executed failure contracts for the first compact cutover controller."""
import importlib.util
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import pytest
from tests_python.browser_evidence_fixture import install as install_browser, CID as BROWSER_CID, IMAGE as BROWSER_IMAGE
from tests_python.collaboration_evidence_fixture import install as install_collaboration


ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'script/docker' / file)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


cutover = load('compact_cutover_contract', 'compact-cutover.py')
schema = load('compact_cutover_schema_contract', 'compact-schema-guard.py')
runtime = load('compact_cutover_runtime_resource_fixture', 'compact-runtime-acceptance.py')
build_resources = load('compact_cutover_build_resource_fixture', 'compact-build-resources.py')
coverage_spec = importlib.util.spec_from_file_location('compact_coverage_contract', ROOT / 'script/jenkins/compact-acceptance.py')
coverage = importlib.util.module_from_spec(coverage_spec); coverage_spec.loader.exec_module(coverage)


def fixture_build_resources(directory, context, name):
    """Retain the real resource protocol's byte files, not a PASS-only stub."""
    resource = directory / 'checkout/work/runtime-acceptance' / ('controlled-build-' + name)
    resource.mkdir(parents=True)
    baseline = {'monotonic': 100.0, 'diskAvailableBytes': 8 * runtime.GIB,
                'memoryAvailableBytes': 12 * runtime.GIB, 'filesystemBlockBytes': 4096}
    token = hashlib.sha256(('owner:' + name).encode()).hexdigest()[:24]
    cid = hashlib.sha256(('builder:' + name).encode()).hexdigest()
    builder_engine = {'engineImageId': build_resources.IMAGE_ID, 'configDigest': build_resources.IMAGE_ID,
        'loadDescriptor': None, 'diffIds': ['sha256:' + hashlib.sha256(b'fixture-builder-layer').hexdigest()],
        'os': 'linux', 'architecture': 'amd64'}
    rootless_profile = build_resources.rootless_profile_proof()
    builder = {'id': cid, 'pid': 1200 if name == 'model' else 1201, 'image': build_resources.IMAGE_ID,
               'memoryLimitBytes': build_resources.BUILDER_MEMORY, 'currentBytes': 8 * runtime.MIB,
               'peakBytes': 16 * runtime.MIB, 'oomKills': 0, 'writeRateLimitBytesPerSecond': 64 * runtime.MIB}
    build_context = {key: context[key] for key in ('release', 'commit', 'sourceSha256', 'identity')}
    plans, samples = [], []
    for index, phase in enumerate(('builder-bootstrap', 'build-' + name, 'load-' + name), 1):
        phase += '-%03d' % index
        value = build_resources.phase_plan({**build_context, 'ownerToken': token}, phase, baseline,
            64 * runtime.MIB, build_resources.BUILDER_MEMORY,
            {'retainedFixtureInputBytes': 1024, **({'engineIdentity': builder_engine, 'rootlessProfile': rootless_profile}
                                                 if phase.startswith('builder-bootstrap-') else {})})
        file = resource / ('phase-%02d.json' % index); write(file, value)
        plans.append({'file': file.name, 'sha256': cutover.sha_file(file)})
        samples.append({**baseline, 'monotonic': 100.0 + index * .5, 'phase': phase, 'builder': builder})
    raw = b''.join(build_resources.encoded(sample) + b'\n' for sample in samples)
    probes = resource / 'resource-probes.jsonl'; probes.write_bytes(raw); probes.chmod(0o600)
    image_id = 'sha256:' + hashlib.sha256(('fixture-image:' + name).encode()).hexdigest()
    image = {'imageId': image_id, 'ociArchiveSha256': hashlib.sha256(('archive:' + name).encode()).hexdigest(),
             'ociArchiveBytes': 20480, 'controlledDockerfileSha256': hashlib.sha256(('dockerfile:' + name).encode()).hexdigest(),
             'inputContext': {'sha256': hashlib.sha256(('input:' + name).encode()).hexdigest()},
             'layers': [{'diffId': 'sha256:' + hashlib.sha256(('layer:' + name).encode()).hexdigest(),
                         'blobDigest': 'sha256:' + hashlib.sha256(('blob:' + name).encode()).hexdigest(),
                         'allocationUpperBoundBytes': 8192}]}
    image.update(configDigest=image_id,
        manifestDigest='sha256:' + hashlib.sha256(('manifest:' + name).encode()).hexdigest(), loadDescriptor=None,
        engineIdentity={'engineImageId': image_id, 'configDigest': image_id, 'loadDescriptor': None,
                        'diffIds': [row['diffId'] for row in image['layers']], 'os': 'linux', 'architecture': 'amd64'})
    summary = {'version': 1, 'kind': 'doorhandle-candidate-build-resources', **build_context, 'ownerToken': token,
        'status': 'PASS', 'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'productionCapacityVerified': False,
        'engineIdentity': builder_engine, 'rootlessProfile': rootless_profile,
        'baselineProbe': baseline, 'finalProbe': {**baseline, 'monotonic': 102.0}, 'phases': plans,
        'probeFile': 'resource-probes.jsonl', 'probeSha256': hashlib.sha256(raw).hexdigest(), 'monitorFailure': None,
        'originalDataChanged': False, 'cleanup': {'creatorStopped': True, 'builderStopped': True,
            'daemonImportTerminated': True, 'builderContainerId': cid}, 'build': {'images': {name: image}}}
    file = resource / 'resource-summary.json'; write(file, summary)
    return {'file': file.relative_to(directory).as_posix(), 'sha256': cutover.sha_file(file)}, image_id


def attach_runtime_resources(directory, context, project, proof, images, fixture_images):
    resource = directory / 'checkout/work/runtime-acceptance'
    # Existing persisted runtime receipts predate the opt-in monitoring contract.
    daemons = sorted(runtime.CORE_DAEMON_SERVICES - {'prometheus'})
    metrics = []
    for index, service in enumerate(daemons, 1):
        image = images.get(service, 'sha256:' + hashlib.sha256(('infra:' + service).encode()).hexdigest())
        if service == 'model-fixture': image = fixture_images['model']
        if service == 'mcp-runner': image = fixture_images['mcp']
        metrics.append({'containerId': format(index, '064x'), 'service': service, 'image': image,
            'memoryLimitBytes': (256 if service == 'redis' else runtime.SERVICE_MEMORY_MIB[service]) * runtime.MIB,
            'currentBytes': runtime.MIB, 'peakBytes': 2 * runtime.MIB, 'oom': 0, 'oomKills': 0,
            'running': True, 'exitCode': 0})
    metrics.append({'containerId': 'e' * 64, 'service': 'bge-qdrant',
        'image': 'sha256:' + hashlib.sha256(b'infra:bge-qdrant').hexdigest(),
        'memoryLimitBytes': runtime.TRANSIENT_SERVICE_MEMORY_MIB['bge-qdrant'] * runtime.MIB,
        'currentBytes': 0, 'peakBytes': 2 * runtime.MIB,
        'oom': 0, 'oomKills': 0, 'running': False, 'exitCode': 0})
    metrics.append({'containerId': 'f' * 64, 'service': 'bge-verifier', 'image': images['mem0'],
        'memoryLimitBytes': runtime.BGE_VERIFIER_MEMORY, 'currentBytes': 0, 'peakBytes': 4 * runtime.MIB,
        'oom': 0, 'oomKills': 0, 'running': False, 'exitCode': 0})
    metrics.append({'containerId': BROWSER_CID, 'service': 'collaboration-browser', 'image': BROWSER_IMAGE,
        'memoryLimitBytes': runtime.BROWSER_MEMORY, 'currentBytes': 0, 'peakBytes': 2 * runtime.MIB,
        'oom': 0, 'oomKills': 0, 'running': False, 'exitCode': 0})
    phases, plans, samples = [], {}, []
    declared_memory = (sum(runtime.SERVICE_MEMORY_MIB.values()) + 128) * runtime.MIB + 512 * runtime.MIB + runtime.BGE_VERIFIER_MEMORY
    for index, phase in enumerate(('runtime-start', 'runtime-backup', 'runtime-restore', 'runtime-browser'), 1):
        baseline = {'capturedAtUnix': 100 + index, 'diskTotalBytes': 40 * runtime.GIB,
            'diskAvailableBytes': 8 * runtime.GIB, 'memoryAvailableBytes': 12 * runtime.GIB}
        plans[phase] = runtime.phase_admission(phase, baseline, runtime.GIB, runtime.BROWSER_MEMORY if phase == 'runtime-browser' else declared_memory,
            {'retainedFixtureBytes': 1024, 'actualDeclaredMemoryLimitBytes': declared_memory})
        file = resource / ('resource-phase-' + str(index) + '-' + phase + '.json'); write(file, plans[phase])
        phases.append({'phase': phase, 'file': file.relative_to(directory).as_posix(), 'sha256': cutover.sha_file(file)})
        samples.append({'probe': {**baseline, 'phase': phase, 'hostDiskLossUpperBoundBytes': 0,
                                 'diskLossOwnershipProof': False}, 'containers': [row for row in metrics if phase=='runtime-browser' or row['service']!='collaboration-browser'], 'stopReasons': []})
    raw = b''.join((json.dumps(sample) + '\n').encode() for sample in samples)
    probes = resource / 'resource-probes.jsonl'; probes.write_bytes(raw); probes.chmod(0o600)
    summary = {**context, 'kind': 'doorhandle-bounded-runtime-resources', 'project': project,
        'profile': runtime.RUNTIME_PROFILE, 'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'productionCapacityVerified': False,
        'status': 'MEASURED_FOR_BOUNDED_SCENARIOS', 'pollIntervalSeconds': 2, 'diskFloorBytes': runtime.DISK_FLOOR,
        'memoryFloorBytes': runtime.MEMORY_FLOOR, 'rawProbeFile': 'checkout/work/runtime-acceptance/resource-probes.jsonl',
        'rawProbeSha256': hashlib.sha256(raw).hexdigest(), 'samples': 4,
        'containers': {row['containerId']: row for row in metrics}, 'requiredDaemonServices': daemons,
        'requiredTransientServices': ['bge-qdrant', 'bge-verifier', 'collaboration-browser'], 'minimumDiskAvailableBytes': 8 * runtime.GIB,
        'minimumMemoryAvailableBytes': 12 * runtime.GIB, 'latestProbeAtUnix': 104, 'phases': phases, 'phasePlans': plans}
    file = resource / 'resource-summary.json'; write(file, summary)
    reference = {'file': file.relative_to(directory).as_posix(), 'sha256': cutover.sha_file(file)}
    proof['resourceEvidence'] = reference
    proof['loadScope'] = {'profile': runtime.RUNTIME_PROFILE, 'productionPerformanceVerified': False,
                          'productionCapacityVerified': False, 'allMandatoryScenariosRequired': True}
    cleanup_file = directory / proof['cleanup']['file']
    cleanup = json.loads(cleanup_file.read_text()); cleanup['resourceEvidence'] = reference
    cleanup['fixtureBuildResources'] = proof['fixtureBuildResources']
    install_browser(resource, context, project, proof, cleanup)
    write(cleanup_file, cleanup)
    proof['cleanup']['sha256'] = cutover.sha_file(cleanup_file)


def runtime_verification(tmp_path):
    tag = 'ci-11-' + 'a' * 12
    identity = {'instanceId': 'i-example', 'machineId': 'b' * 32, 'executionLocation': 'ECS'}
    directory = tmp_path / 'verification' / tag
    profile, profile_sha = coverage.profile(ROOT)
    images = {key: 'sha256:' + str(index) * 64 for index, key in enumerate(('backend', 'nginx', 'mem0', 'detection-worker'), 1)}
    context = {'schemaVersion': 1, 'kind': 'doorhandle-compact-runtime-acceptance', 'release': tag,
        'commit': 'a' * 40, 'sourceSha256': 'c' * 64, 'identity': identity,
        'acceptanceProfileSha256': profile_sha, 'candidateBuildSha256': 'd' * 64}
    project = 'doorhandle-rehearsal-' + 'e' * 12
    proof = {**context, 'status': 'PASS', 'project': project, 'images': images,
        'migrationReceiptSha256': 'f' * 64, 'initialTargetSnapshotSha256': '1' * 64,
        'actualServerUuid': '11111111-1111-1111-1111-111111111111', 'actualMysqlPort': 15444, 'paidModelCalls': 0,
        'scenarios': {}, 'modelIsolation': {
            'fixtureSourceSha256': cutover.sha_file(ROOT / 'script/docker/compact-model-fixture.py'),
            'ossAdapterSourceSha256': cutover.sha_file(ROOT / 'script/docker/compact-oss-fixture.py'),
            'internalNetworksVerified': True, 'providerCredentialsRemoved': True,
            'fixtureState': {'kind': 'doorhandle-owned-scripted-model', 'modelRequests': 12, 'embeddingRequests': 2},
            'observedInternalNetworks': [{'service': key, 'networkId': '7' * 64, 'internal': True}
                for key in ('backend', 'mem0', 'model-fixture')]}}
    proof['fixtureBuildResources'] = {}; fixture_images = {}
    for name in ('model', 'mcp', 'browser'):
        proof['fixtureBuildResources'][name], fixture_images[name] = fixture_build_resources(directory, context, name)
    def evidence(name, value):
        path = directory / 'checkout/work/runtime-acceptance' / (name + '.json')
        write(path, {**context, 'project': project, **value})
        return {'file': path.relative_to(directory).as_posix(), 'sha256': cutover.sha_file(path)}
    recovery_file = directory / 'checkout/work/runtime-acceptance/post-business-recovery/recovery-receipt.json'
    write(recovery_file, {**context, 'kind': 'doorhandle-runtime-post-business-recovery', 'status': 'VERIFIED',
        'originalMigrationReceiptSha256': 'f' * 64, 'sourceSnapshotSha256': '2' * 64, 'restoredSnapshotSha256': '2' * 64})
    critical = {
        'detection-pth-worker-kafka-receipts': {'actualUnknownResultFence': {'status': 'NEEDS_REVIEW',
            'actualSuccessfulImages': 1, 'actualFailedImages': 0,
            'actualCompletionSignal': {'error': 1644, 'sqlState': '45000', 'statementSha256': '3' * 64},
            'unknownRowSha256': '4' * 64, 'actualSummarySha256': '5' * 64, 'actualUncommittedPartition': {'lag': 2}}},
        'private-mcp-install-fetch-cancel-reconcile': {'actualUnknownControlFault': {'unknownState': 'NEEDS_REVIEW',
            'newInstallationBlockedHttpStatus': 409, 'newInstallationBlockedReason': 'PENDING_EXECUTION_EXIT',
            'denialResponseSha256': '6' * 64, 'reconciledState': 'REMOVED', 'writerExitAndCleanupVerified': True,
            'observedWriterId': '7' * 64, 'pausedControllerId': '8' * 64, 'poolId': '9' * 32}},
        'sdk-session-workbench-recovery': {'interruptedRunId': 'interrupted', 'resumedRunId': 'continued',
            'beforeRestoreRevision': 1, 'afterRestoreRevision': 2, 'afterRestoreSha256': 'a' * 64, 'cancelledExecutionFence': 3},
        'compact-application-upgrade-recovery': {'restoredTableCount': 29, 'originalSchema': 'original', 'restoredSchema': 'restore',
            'postBusinessSnapshotSha256': '2' * 64, 'restoredSnapshotSha256': '2' * 64,
            'wrongKeyRejectedServices': ['backend', 'mem0'], 'actualProcessesUseRestoredSchema': True,
            'postBusinessRecoveryReceiptSha256': cutover.sha_file(recovery_file)}}
    for item in profile['runtimeAcceptance']['scenarios']:
        proof['scenarios'][item['id']] = evidence('scenario-' + item['id'], {
            'scenario': item['id'], 'status': 'PASS', 'observations': critical.get(item['id'], {'actualReceiptSha256': '8' * 64})})
    proof['cleanup'] = {**evidence('cleanup', {'status': 'STOPPED', 'unresolved': [],
        'stoppedContainers': ['9' * 64], 'sourceResourcesChanged': False,
        'sourceBeforeSha256': 'a' * 64, 'sourceAfterSha256': 'a' * 64}), 'status': 'STOPPED'}
    write(directory / 'checkout/work/ci-evidence/migration.json', {'migrationReceiptSha256': 'f' * 64, 'targetSnapshotSha256': '1' * 64})
    attach_runtime_resources(directory, context, project, proof, images, fixture_images)
    cleanup_file = directory / 'checkout/work/runtime-acceptance/cleanup.json'
    cleanup = json.loads(cleanup_file.read_bytes())
    install_collaboration(directory / 'checkout/work/runtime-acceptance', context, project, proof, cleanup)
    write(cleanup_file, cleanup); proof['cleanup']['sha256'] = cutover.sha_file(cleanup_file)
    path = directory / 'runtime-acceptance.json'; write(path, proof)
    def admit():
        return cutover.admitted_runtime(tmp_path, tag, 'a' * 40, 'c' * 64, identity, schema, {'images': images}, 'd' * 64)
    return SimpleNamespace(path=path, directory=directory, proof=proof, admit=admit)


def test_runtime_gate_requires_all_nine_scenario_artifacts_from_the_exact_candidate(tmp_path):
    actual = runtime_verification(tmp_path)
    assert actual.admit() == cutover.sha_file(actual.path)
    actual.proof['scenarios'].pop('report-draft-review-export-delivery')
    write(actual.path, actual.proof)
    with pytest.raises(ValueError, match='Every mandatory runtime'):
        actual.admit()


@pytest.mark.parametrize('damage',['absent-proof','absent-report','different-measured-image'])
def test_runtime_cutover_requires_original_browser_execution_and_the_same_measured_image(tmp_path,damage):
    actual=runtime_verification(tmp_path)
    resource=actual.directory/'checkout/work/runtime-acceptance'
    if damage=='absent-proof':actual.proof.pop('browserAcceptance')
    if damage=='absent-report':(resource/'browser-evidence/browser-evidence.json').unlink()
    if damage=='different-measured-image':
        report_file=resource/'browser-evidence/browser-evidence.json';report=json.loads(report_file.read_bytes())
        report['runtime']['browserImageId']='sha256:'+'0'*64;write(report_file,report)
        manifest_file=resource/'browser-manifest.json';manifest=json.loads(manifest_file.read_bytes())
        manifest['browserImageId']=report['runtime']['browserImageId']
        for when in ('before','after'):manifest['externalContainerObservation'][when]['imageId']=manifest['browserImageId']
        row=next(row for row in manifest['files'] if row['path'].endswith('/browser-evidence.json'))
        row.update(bytes=report_file.stat().st_size,sha256=cutover.sha_file(report_file))
        manifest['externalContainerObservation']['files']=manifest['files'];write(manifest_file,manifest)
        actual.proof['browserAcceptance'].update(sha256=cutover.sha_file(report_file),externalContainerObservation=manifest['externalContainerObservation'])
        cleanup_file=resource/'cleanup.json';cleanup=json.loads(cleanup_file.read_bytes())
        cleanup['browserEvidence']['sha256']=cutover.sha_file(manifest_file);write(cleanup_file,cleanup)
        actual.proof['cleanup']['sha256']=cutover.sha_file(cleanup_file)
    write(actual.path,actual.proof)
    with pytest.raises((ValueError,OSError)):actual.admit()


def test_runtime_gate_rejects_modified_child_or_foreign_migration_even_when_summary_says_pass(tmp_path):
    actual = runtime_verification(tmp_path)
    item = next(iter(actual.proof['scenarios'].values()))
    child = actual.directory / item['file']
    child.write_text(child.read_text(encoding='utf8') + ' ', encoding='utf8')
    with pytest.raises(ValueError, match='missing, changed or foreign'):
        actual.admit()
    item['sha256'] = cutover.sha_file(child)
    actual.proof['migrationReceiptSha256'] = '0' * 64; write(actual.path, actual.proof)
    with pytest.raises(ValueError, match='exact whole-migration target'):
        actual.admit()


def test_runtime_gate_rejects_unconfirmed_cleanup_and_external_model_networks(tmp_path):
    actual = runtime_verification(tmp_path)
    reference = actual.proof['cleanup']; path = actual.directory / reference['file']
    value = json.loads(path.read_text(encoding='utf8')); value['unresolved'] = ['container-unknown']
    write(path, value); reference['sha256'] = cutover.sha_file(path); write(actual.path, actual.proof)
    with pytest.raises(ValueError, match='cleanup has not been confirmed'):
        actual.admit()
    value['unresolved'] = []; write(path, value); reference['sha256'] = cutover.sha_file(path)
    actual.proof['modelIsolation']['observedInternalNetworks'][0]['internal'] = False
    write(actual.path, actual.proof)
    with pytest.raises(ValueError, match='internal-network observations'):
        actual.admit()


def test_runtime_scenario_name_and_409_do_not_replace_an_actual_unknown_writer_fence(tmp_path):
    actual = runtime_verification(tmp_path)
    reference = actual.proof['scenarios']['private-mcp-install-fetch-cancel-reconcile']
    path = actual.directory / reference['file']; value = json.loads(path.read_text(encoding='utf8'))
    value['observations']['actualUnknownControlFault']['newInstallationBlockedReason'] = 'ALREADY_INSTALLED'
    write(path, value); reference['sha256'] = cutover.sha_file(path); write(actual.path, actual.proof)
    with pytest.raises(ValueError, match='Actual unknown MCP writer/control fault'):
        actual.admit()


def oss_transport(monkeypatch):
    monkeypatch.setenv('FIXTURE_OSS_BUCKET', 'owned-fixture-bucket')
    monkeypatch.setenv('FIXTURE_OSS_ENDPOINT', 'https://oss-cn-beijing.aliyuncs.com')
    monkeypatch.setenv('FIXTURE_OSS_PREFIX', 'runtime-acceptance/' + 'a' * 12 + '/')
    value = load('compact_owned_oss_fixture', 'compact-oss-fixture.py')
    handler = object.__new__(value.Handler)
    handler.command = 'HEAD'; handler.request_version = 'HTTP/1.1'
    handler.requestline = 'HEAD / HTTP/1.1'; handler.wfile = io.BytesIO()
    return value, handler


def test_owned_oss_head_retains_actual_object_length_without_sending_a_body(monkeypatch):
    _, handler = oss_transport(monkeypatch)
    handler.response(200, b'', {'Content-Length': '4096', 'ETag': 'fixture-etag'})
    result = handler.wfile.getvalue()
    assert b'Content-Length: 4096\r\n' in result and b'ETag: fixture-etag\r\n' in result
    assert result.endswith(b'\r\n\r\n')


def test_owned_oss_preserves_v1_signature_path_and_refuses_foreign_prefix(monkeypatch):
    value, handler = oss_transport(monkeypatch)
    requests = []
    class Upstream:
        status = 200
        def read(self, bound):
            return b'owned-object'
        def getheader(self, name, default=None):
            return 'fixture-request' if name == 'x-oss-request-id' else default
        def getheaders(self):
            return [('Content-Length', '12')]
    class Connection:
        def __init__(self, host, port, timeout):
            assert host == 'owned-fixture-bucket.oss-cn-beijing.aliyuncs.com' and port == 443
        def request(self, method, path, body, headers):
            requests.append((method, path, body, headers))
        def getresponse(self):
            return Upstream()
        def close(self):
            pass
    monkeypatch.setattr(value.http.client, 'HTTPSConnection', Connection)
    handler.command = 'GET'
    handler.path = '/runtime-acceptance/' + 'a' * 12 + '/%E4%B8%AD.png?OSSAccessKeyId=fixture&Expires=1&Signature=a%2Bb%3D'
    handler.headers = {'Host': 'oss-proxy:9000', 'Content-Type': 'image/png', 'Content-Length': '0'}
    handler.rfile = io.BytesIO(b'')
    handler.forward()
    assert len(requests) == 1 and requests[0][:3] == ('GET', handler.path, b'')
    assert requests[0][3]['Host'] == 'owned-fixture-bucket.oss-cn-beijing.aliyuncs.com'
    handler.wfile = io.BytesIO(); handler.path = '/another-prefix/private.png?OSSAccessKeyId=fixture&Signature=fixture'
    handler.forward()
    assert len(requests) == 1 and b'502 ' in handler.wfile.getvalue().split(b'\r\n')[0]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf8'); path.chmod(0o600)


def verification(tmp_path):
    tag = 'ci-11-' + 'a' * 12
    identity = {'instanceId': 'i-example', 'machineId': 'b' * 32, 'executionLocation': 'ECS'}
    folder = tmp_path / 'verification' / tag
    profile, profile_sha = coverage.profile(ROOT)
    evidence = folder / 'checkout/work/ci-evidence'
    artifacts = []
    def report(relative, classes):
        root = ET.Element('testsuite')
        for name, count in classes:
            for index in range(count):
                ET.SubElement(root, 'testcase', classname=name, name='test_' + str(index))
        path = evidence / relative; path.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(root).write(path, encoding='utf8')
        artifacts.append(('reports/' + relative, path))
        return {'path': relative, 'bytes': path.stat().st_size, 'sha256': cutover.sha_file(path)}
    def count(number):
        return {'found': number, 'passed': number, 'failed': 0, 'skipped': 0}
    java_suites = []
    for index, requirement in enumerate(profile['javaSuites'], 1):
        name, number = requirement['className'], requirement['minimumTests']
        descriptor = report('java/suite-' + str(index) + '/surefire-reports/TEST-' + name + '.xml', [(name, number)])
        java_suites.append({'id': 'suite-' + str(index), 'javaSelection': [name],
            'fixtureProperties': requirement['fixtureProperties'], 'status': 'PASS', 'javaTests': count(number),
            'selectedJavaClasses': {name: count(number)}, 'reportFiles': [descriptor]})
    source_classes = [(item['className'], item['minimumTests']) for item in profile['sourceRegression']['requiredClasses']]
    source_report = report('source-regression/java/source/surefire-reports/TEST-source.xml', source_classes)
    python_classes = [(item['module'], item['minimumTests']) for item in profile['python']['requiredSuites']]
    report('python.xml', python_classes)
    result = {'status': 'PASS', 'identity': identity, 'fixtureProperties': ['private-fixture'], 'javaOnly': False,
              'javaSelection': ','.join(item['className'] for item in profile['javaSuites']),
              'acceptanceProfileSha256': profile_sha, 'javaTests': count(sum(item['javaTests']['passed'] for item in java_suites)),
              'javaSuites': java_suites, 'javaReportFiles': [item['reportFiles'][0] for item in java_suites],
              'selectedJavaClasses': {name: tally for item in java_suites for name, tally in item['selectedJavaClasses'].items()},
              'sourceRegression': {'status': 'PASS', 'javaTests': count(sum(number for _, number in source_classes)),
                 'selectedJavaClasses': {name: count(number) for name, number in source_classes}, 'reportFiles': [source_report]},
              'pythonTests': count(sum(number for _, number in python_classes)),
              'selectedPythonSuites': {name: count(number) for name, number in python_classes},
              'workerMysqlRequested': True, 'workerMysqlConfigSha256': 'd' * 64,
              'wholeMigrationRequested': True, 'wholeMigrationTests': {'passed': next(number for name, number in python_classes
                   if name == profile['wholeMigration']['pythonSuite']), 'failed': 0, 'skipped': 0},
              'commands': [], 'frontendResults': {}}
    for frontend in profile['frontends']:
        name = frontend['directory']; number = frontend['minimumTests']
        result['frontendResults'][name] = {'selectedTestFiles': frontend['testFiles'], 'installExitCode': 0,
            'testExitCode': 0, 'buildExitCode': 0, 'tests': count(number)}
        result['commands'].extend({'label': label, 'exitCode': 0} for label in frontend['requiredCommands'])
        log = evidence / (name + '-test.log')
        log.write_text('TAP version 13\n# tests ' + str(number) + '\n# pass ' + str(number)
            + '\n# fail 0\n# skipped 0\n# cancelled 0\n# todo 0\n', encoding='utf8')
        artifacts.append(('reports/' + log.name, log))
    summary = folder / 'checkout/work/ci-evidence/migration.json'
    write(summary, {'status': 'VERIFIED', 'sourceTableCount': 131, 'targetTableCount': 29})
    result['wholeMigrationSummarySha256'] = cutover.sha_file(summary)
    result_file = summary.with_name('receipt.json'); write(result_file, result)
    xml = artifacts[0][1]
    files = [('reports/receipt.json', result_file), ('reports/migration.json', summary), *artifacts]
    receipt = {'schema': 1, 'kind': 'doorhandle-ecs-ci', 'release': tag, 'commit': 'a' * 40,
               'sourceSha256': 'c' * 64, 'identity': identity, 'scope': 'mysql', 'status': 'PASS',
               'verificationExitCode': 0, 'fixtureReadinessValidated': True,
               'reportFiles': [{'path': name, 'bytes': file.stat().st_size, 'sha256': cutover.sha_file(file)}
                               for name, file in files]}
    file = folder / 'verification-receipt.json'; write(file, receipt)
    return SimpleNamespace(tag=tag, identity=identity, file=file, receipt=receipt, result=result,
                           result_file=result_file, xml=xml)


def admit(tmp_path, fixture):
    return cutover.admitted_verification(tmp_path, fixture.tag, 'a' * 40, 'c' * 64, fixture.identity, schema)


def test_executed_mysql_and_whole_migration_reports_are_bound_to_this_build(tmp_path):
    fixture = verification(tmp_path)
    assert admit(tmp_path, fixture) == cutover.sha_file(fixture.file)


def test_changed_java_report_blocks_cutover_even_when_pass_envelope_is_unchanged(tmp_path):
    fixture = verification(tmp_path); fixture.xml.write_text('<testsuite tests="9" failures="1"/>')
    with pytest.raises(ValueError, match='artifact is missing or changed'):
        admit(tmp_path, fixture)


def test_source_scope_pass_cannot_stand_in_for_executed_database_acceptance(tmp_path):
    fixture = verification(tmp_path); fixture.receipt['scope'] = 'source'; write(fixture.file, fixture.receipt)
    with pytest.raises(ValueError, match='MySQL ECS verification'):
        admit(tmp_path, fixture)


@pytest.mark.parametrize('counts', [{'passed': 0, 'failed': 0, 'skipped': 0},
                                   {'passed': 3, 'failed': 0, 'skipped': 1}])
def test_omitted_whole_migration_cases_cannot_enable_first_cutover(tmp_path, counts):
    fixture = verification(tmp_path); fixture.result['wholeMigrationTests'] = counts
    write(fixture.result_file, fixture.result)
    for item in fixture.receipt['reportFiles']:
        if item['path'] == 'reports/receipt.json':
            item.update(bytes=fixture.result_file.stat().st_size, sha256=cutover.sha_file(fixture.result_file))
    write(fixture.file, fixture.receipt)
    with pytest.raises(ValueError, match='copy and source/target recovery'):
        admit(tmp_path, fixture)


def update_result(fixture):
    write(fixture.result_file, fixture.result)
    for item in fixture.receipt['reportFiles']:
        if item['path'] == 'reports/receipt.json':
            item.update(bytes=fixture.result_file.stat().st_size, sha256=cutover.sha_file(fixture.result_file))
    write(fixture.file, fixture.receipt)


def test_one_passing_mysql_class_cannot_replace_the_required_suite_matrix(tmp_path):
    fixture = verification(tmp_path); fixture.result['javaSuites'] = fixture.result['javaSuites'][:1]
    update_result(fixture)
    with pytest.raises(ValueError, match='complete required MySQL suite matrix'):
        admit(tmp_path, fixture)


def test_passing_mysql_matrix_cannot_replace_an_ordinary_source_regression(tmp_path):
    fixture = verification(tmp_path); fixture.result.pop('sourceRegression')
    update_result(fixture)
    with pytest.raises(ValueError, match='ordinary source regression'):
        admit(tmp_path, fixture)


def test_self_reported_successful_frontend_build_cannot_replace_missing_tests(tmp_path):
    fixture = verification(tmp_path); fixture.result['frontendResults']['frontend']['selectedTestFiles'] = []
    update_result(fixture)
    with pytest.raises(ValueError, match='fixed test files and build'):
        admit(tmp_path, fixture)


def test_candidate_start_prevents_source_recovery_even_when_no_http_traffic_was_opened():
    instance = object.__new__(cutover.Cutover)
    instance.journal = {'phase': 'FAILED_ACTIVATION_FROZEN', 'activationStarted': True}
    instance.assert_maintenance = lambda: pytest.fail('Source readback or restart must not be attempted')
    with pytest.raises(ValueError, match='compact runtime may have written'):
        instance.recover()
    assert not cutover.may_restore_source(instance.journal)


def test_source_recovery_is_available_before_candidate_start_and_never_implicitly_enabled():
    assert cutover.may_restore_source({'phase': 'MIGRATED', 'activationStarted': False})
    assert not cutover.may_restore_source({'phase': 'ACTIVE', 'activationStarted': False})
    assert not cutover.may_restore_source({'phase': 'MIGRATED'})
    assert not cutover.may_restore_source({'phase': 'SOURCE_RESTORED', 'activationStarted': False})


@pytest.mark.parametrize('action', ['prepare', 'recover'])
@pytest.mark.parametrize('failed_stop', [None, '1' * 64])
def test_partial_source_stop_or_restore_failure_freezes_all_writers_and_reports_unverified_stop(tmp_path, action, failed_stop):
    instance = object.__new__(cutover.Cutover)
    rows = [{'Id': char * 64, 'Config': {'Labels': {'com.docker.compose.service': service}},
             'State': {'Running': True, 'Restarting': False, 'Pid': 12},
             'HostConfig': {'RestartPolicy': {'Name': 'unless-stopped'}}}
            for char, service in (('1', 'backend'), ('2', 'nginx'), ('3', 'mysql'))]
    instance.journal = {'phase': 'PREPARING', 'activationStarted': False, 'sourceSchema': 'old_source',
        'sourceAccountsApproved': True, 'sourceAccounts': [{'user': 'doorhandle', 'host': '%', 'locked': 'N'}],
        'originals': [{'id': row['Id'], 'service': row['Config']['Labels']['com.docker.compose.service']}
                      for row in rows if row['Config']['Labels']['com.docker.compose.service'] != 'mysql']}
    instance.state = tmp_path
    calls = []
    def docker(*args, **kwargs):
        calls.append(args)
        row = next(row for row in rows if row['Id'] == args[-1])
        if args[0] == 'update':
            row['HostConfig']['RestartPolicy']['Name'] = 'no'
        elif args[0] == 'stop':
            if row['Id'] == failed_stop:
                raise RuntimeError('stop unavailable')
            row['State'].update(Running=False, Pid=0)
        return json.dumps([row]).encode()
    instance.ops = SimpleNamespace(docker=docker)
    instance.current = lambda: rows
    instance.sql = lambda *args, **kwargs: '0'
    instance.source_account_rows = lambda: [{'user': 'doorhandle', 'host': '%', 'locked': 'Y'}]
    instance.unexpected_source_writers = lambda: []
    instance.external_source_clients = lambda: []
    instance.event_catalog = lambda: []
    instance.routine_catalog = lambda: []
    instance.persist = lambda phase: instance.journal.update(phase=phase)
    instance.fail_closed(action)
    assert {item[-1] for item in calls if item[0] == 'stop'} == {'1' * 64, '2' * 64}
    assert rows[2]['State']['Running'] is True
    assert instance.journal['failureFreeze']['confirmed'] is (failed_stop is None)
    assert instance.journal['phase'].endswith('_FROZEN' if failed_stop is None else '_NEEDS_REVIEW')


def test_source_root_credential_is_never_locked_or_unlocked():
    instance = object.__new__(cutover.Cutover)
    instance.journal = {'sourceAccounts': [{'user': 'root', 'host': '%', 'locked': 'N'}]}
    instance.sql = lambda *args, **kwargs: pytest.fail('Maintenance root must remain available')
    with pytest.raises(ValueError, match='cannot be safely fenced'):
        instance.fence_accounts()


@pytest.mark.parametrize('catalog', ['TABLE_PRIVILEGES', 'COLUMN_PRIVILEGES'])
@pytest.mark.parametrize('predicate', ['TABLE_SCHEMA<>DATABASE()', "IS_GRANTABLE='YES'"])
def test_source_account_with_other_schema_or_delegating_object_grants_cannot_be_fenced(catalog, predicate):
    instance = object.__new__(cutover.Cutover)
    instance.journal = {'sourceAccounts': [{'user': 'old_app', 'host': '%', 'locked': 'N'}]}
    calls = []

    def query(sql):
        calls.append(sql)
        if 'information_schema.' + catalog + ' WHERE' in sql:
            assert predicate in sql
            assert "CONCAT(CHAR(39),'old_app',CHAR(39))" in sql
            return '1'
        return '0'

    instance.sql = query
    with pytest.raises(ValueError, match='cross-schema or delegating table/column grants'):
        instance.check_fenceable_accounts()
    assert all(sql.startswith('SELECT ') for sql in calls)


def test_source_account_confined_to_its_database_remains_fenceable():
    instance = object.__new__(cutover.Cutover)
    instance.journal = {'sourceAccounts': [{'user': 'old_app', 'host': '%', 'locked': 'N'}]}
    calls = []
    instance.sql = lambda sql: calls.append(sql) or '0'
    instance.check_fenceable_accounts()
    for catalog in ('SCHEMA_PRIVILEGES', 'TABLE_PRIVILEGES', 'COLUMN_PRIVILEGES'):
        assert any('information_schema.' + catalog + ' WHERE' in sql
                   and "(TABLE_SCHEMA<>DATABASE() OR IS_GRANTABLE='YES')" in sql for sql in calls)


@pytest.fixture
def release_permission():
    context = {'release': 'ci-420-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64,
               'identity': {'instanceId': 'i-owned', 'machineId': 'c' * 32, 'executionLocation': 'ECS'}}
    inputs = dict.fromkeys(cutover.RELEASE_INPUTS, '')
    inputs.update(REMOTE_ROOT='/home/ecs-user/doorhandle-ci', REMOTE_RUNTIME='/home/ecs-user/runtime',
                  COMPACT_CUTOVER_SETTINGS='/home/ecs-user/settings.json')
    request = {**context, 'inputs': inputs, 'settingsSha256': 'd' * 64}
    authorization = {**{key: context[key] for key in ('commit','sourceSha256','identity')},
        'schemaVersion': 1, 'kind': 'doorhandle-compact-release-authorization', 'scope': 'first-production-131-to-29',
        'job': 'doorhandle-java', 'branch': 'java-cloud', 'approved': True, 'revoked': False,
        'approvalReference': 'current-user-explicit-release-approval', 'allowPreActivationSourceRestore': True,
        'afterActivationFailure': 'FAIL_CLOSED_COMPACT_ONLY', 'inputs': dict(inputs), 'settingsSha256': 'd' * 64}
    manual = {'enabled': True, 'status': 'ACCEPTED', 'executionId': 'e' * 32, 'submittedBy': 'actual-user',
              'readyAtUnix': 1000, 'submittedAtUnix': 1100, 'expiresAtUnix': 1900}
    proof = {**context, 'status': 'PASS', 'candidateBuildSha256': 'f' * 64, 'manualAcceptance': manual}
    gate = {**context, 'kind': 'doorhandle-runtime-gate-passed', 'status': 'VERIFIED', 'candidateBuildSha256': 'f' * 64}
    decision = {**{key: proof[key] for key in ('release','commit','sourceSha256','candidateBuildSha256')},
                'executionId': 'e' * 32, 'submittedBy': 'actual-user', 'decision': 'ACCEPTED', 'submittedAtUnix': 1100}
    return authorization, request, gate, proof, decision


def test_release_requires_one_fixed_authorized_candidate_and_original_human_decision(release_permission):
    approved = cutover.approve_release(*release_permission)
    assert approved['kind'] == 'doorhandle-compact-release-approval'
    assert approved['commit'] == 'a' * 40 and approved['sourceSha256'] == 'b' * 64
    assert approved['root'] == '/home/ecs-user/doorhandle-ci'
    assert approved['allowPreActivationSourceRestore'] is True
    assert 'inputs' not in approved and 'submittedBy' not in approved


@pytest.mark.parametrize('index,key,value', [
    (0,'approved',False),(0,'revoked',True),(0,'scope','generic-production'),
    (0,'commit','1'*40),(0,'sourceSha256','1'*64),(0,'settingsSha256','1'*64),
    (0,'afterActivationFailure','RESTORE_LEGACY'),(0,'allowPreActivationSourceRestore',False),
    (0,'inputs',{}),(0,'identity',{}),(2,'release','ci-419-'+'a'*12),
    (2,'status','RUNNING'),(2,'candidateBuildSha256','1'*64),(3,'status','FAILED'),
    (3,'identity',{}),(4,'decision','REJECTED'),(4,'commit','1'*40),
    (4,'executionId','1'*32),(4,'submittedAtUnix',999),(4,'submittedBy','another-user'),
])
def test_release_permission_refuses_changed_scope_inputs_or_partial_evidence(release_permission,index,key,value):
    release_permission[index][key] = value
    with pytest.raises(ValueError): cutover.approve_release(*release_permission)


@pytest.mark.parametrize('damage', ['not-requested','expired','wrong-source','unknown-classification'])
def test_manual_acceptance_cannot_be_inferred_from_boolean_job_parameters(release_permission,damage):
    manual=release_permission[3]['manualAcceptance']
    if damage == 'not-requested': manual['enabled']=False
    elif damage == 'expired': manual['submittedAtUnix']=manual['expiresAtUnix']
    elif damage == 'wrong-source': release_permission[3]['sourceSha256']='1'*64
    else: manual['status']='READY_FOR_MANUAL_ACCEPTANCE'
    with pytest.raises(ValueError): cutover.approve_release(*release_permission)


def test_controller_authorization_binds_original_runtime_bytes_without_archiving_private_authorization(tmp_path,release_permission,capsys):
    authorization,request,gate,proof,decision=release_permission
    authorization['privateAnnotation']='must-not-be-exported'
    files={}
    for name,value in [('authorization',authorization),('request',request),('runtime_proof',proof),('manual_decision',decision)]:
        file=tmp_path/(name+'.json');file.write_text(json.dumps(value));files[name]=str(file)
    gate['runtimeReceiptSha256']=cutover.sha_file(files['runtime_proof'])
    file=tmp_path/'gate.json';file.write_text(json.dumps(gate));files['runtime_gate']=str(file)
    assert cutover.authorize_files(SimpleNamespace(**files)) == 0
    output=capsys.readouterr().out
    approved=json.loads(output)
    assert approved['runtimeReceiptSha256'] == gate['runtimeReceiptSha256']
    assert approved['manualDecisionSha256'] == cutover.sha_file(files['manual_decision'])
    assert 'must-not-be-exported' not in output
    Path(files['runtime_proof']).write_text(json.dumps({**proof,'altered':True}))
    with pytest.raises(ValueError,match='bytes differ'): cutover.authorize_files(SimpleNamespace(**files))


@pytest.fixture
def settlement(tmp_path):
    instance=object.__new__(cutover.Cutover)
    instance.work=tmp_path;instance.args=SimpleNamespace(tag='ci-420-'+'a'*12,source_sha256='b'*64)
    instance.input={'gitCommit':'a'*40};instance.identity={'machineId':'c'*32}
    instance.common=SimpleNamespace(write_json=lambda path,value:path.write_text(json.dumps(value)))
    instance.journal={'phase':'FAILED_PREPARE_FROZEN','activationStarted':False,'targetSchema':'compact_exact'}
    calls=[]
    def freeze(action):
        calls.append(('freeze',action));instance.journal['failureFreeze']={'confirmed':True}
    def restore():
        calls.append(('restore',));instance.journal['phase']='SOURCE_RESTORED'
    instance.fail_closed=freeze;instance.recover=restore
    instance.restored_health=lambda:calls.append(('health',))
    instance.persist=lambda *args:None
    return instance,calls


def test_failure_settlement_restores_pre_activation_source_and_requires_health(settlement):
    instance,calls=settlement
    assert instance.settle()['status'] == 'SOURCE_RESTORED'
    assert calls == [('freeze','settle'),('restore',),('health',)]
    assert instance.journal['recovery']['healthVerified'] is True
    calls.clear();assert instance.settle()['status'] == 'SOURCE_RESTORED'
    assert calls == [('health',)]


def test_failed_source_health_refreezes_and_never_reports_recovered(settlement):
    instance,calls=settlement
    def fail(): raise ValueError('actual health unavailable')
    instance.restored_health=fail
    with pytest.raises(ValueError,match='actual health'): instance.settle()
    assert calls == [('freeze','settle'),('restore',),('freeze','recover')]
    assert 'recovery' not in instance.journal


def test_post_activation_settlement_preserves_new_writes_and_never_replays_migration(settlement):
    instance,calls=settlement;instance.journal.update(activationStarted=True,phase='FAILED_ACTIVATE_FROZEN')
    instance.migrate=lambda:pytest.fail('Do not replay copy or restore a target snapshot')
    outcome=instance.settle()
    assert calls == [('freeze','settle')]
    assert outcome == {'status':'COMPACT_FORWARD_REQUIRED','sourceRestored':False,'freezeConfirmed':True,
        'targetWritesPreserved':True,'targetSchema':'compact_exact','migrationReplayed':False,
        'nextAction':'REPAIR_FAILED_COMPONENT_PRESERVING_COMPACT_DATA'}
    assert json.loads((instance.work/'recovery-receipt.json').read_text())['activationStarted'] is True


@pytest.mark.parametrize('state',[None,'ACTIVE'])
def test_settlement_does_not_stop_unstarted_or_successfully_published_business(settlement,state):
    instance,calls=settlement
    instance.journal=None if state is None else {'phase':'ACTIVE','activationStarted':True}
    assert instance.settle()['status'] == (state or 'NOT_STARTED')
    assert calls == []


def test_unconfirmed_writer_freeze_never_restarts_either_schema(settlement):
    instance,calls=settlement
    instance.fail_closed=lambda action:instance.journal.update(failureFreeze={'confirmed':False})
    with pytest.raises(ValueError,match='freeze is unresolved'): instance.settle()
    assert calls == []


def test_same_build_release_does_not_rerun_runtime_and_retains_post_recovery_entry():
    pipeline=(ROOT/'Jenkinsfile.ecs-monolith').read_text(encoding='utf8')
    powershell=(ROOT/'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    stage=pipeline.split("stage('Accept candidate application on ECS')",1)[1].split("stage('Deploy or rollback')",1)[0]
    assert "params.ACTION in ['verify-runtime','compact-cutover']" in stage
    assert "input(id: 'manual-candidate-acceptance'" in stage and 'releaseNotice' in stage
    release=powershell.split("if ($Action -in @('CompactCutover','RecoverCutover'))",1)[1].split("if ($Action -eq 'Rehearse')",1)[0]
    assert "runtimeHelper' run" not in release and 'candidate-build.py' not in release
    assert "{'settle'} else {'run'}" in release and 'compact-release-approval.json' in release
    assert '-Action RecoverCutover' in pipeline and "CI_CUTOVER_VERIFIED != 'true'" in pipeline
    assert "CI_RUNTIME_VERIFIED -ne 'true'" in powershell


def test_machine_release_gate_remains_default_closed_and_authority_is_not_a_job_parameter():
    controller=(ROOT/'script/jenkins/configure-local.groovy').read_text(encoding='utf8')
    assert "'DOORHANDLE_COMPACT_RELEASE_READY': 'false'" in controller
    assert "settings.compactReleaseAuthorization ?: ''" in controller
    assert "'DOORHANDLE_COMPACT_RELEASE_AUTHORIZATION': releaseAuthorizationPath" in controller
    assert "StringParameterDefinition('DOORHANDLE_COMPACT_RELEASE_AUTHORIZATION'" not in controller
    assert 'first-production-131-to-29' in controller and 'FAIL_CLOSED_COMPACT_ONLY' in controller


@pytest.mark.parametrize('failure_phase',['prepare','migrate','activate'])
def test_release_failure_settles_even_after_active_intent_without_repeating_any_phase(monkeypatch,failure_phase):
    instance=object.__new__(cutover.Cutover);calls=[];instance.journal=None
    instance.admit_release=lambda:calls.append('admit')
    stub_execution(instance)
    def phase(name):
        def call():
            calls.append(name)
            if name == 'prepare': instance.journal={'phase':'PREPARING','activationStarted':False}
            if name == 'activate': instance.journal.update(phase='ACTIVE',activationStarted=True)
            if name == failure_phase: raise ValueError('original phase failed')
        return call
    for name in ('prepare','migrate','activate'):setattr(instance,name,phase(name))
    instance.fail_closed=lambda action:calls.append('freeze:'+action)
    instance.settle=lambda:calls.append('settle')
    monkeypatch.setattr(cutover.signal,'signal',lambda *args:None)
    with pytest.raises(ValueError,match='original phase'):instance.run_release()
    expected=['admit','prepare','migrate','activate'];expected=expected[:expected.index(failure_phase)+1]
    assert calls == expected+['freeze:'+failure_phase,'settle']


def test_successful_release_runs_each_durable_phase_once_without_restarting_acceptance():
    instance=object.__new__(cutover.Cutover);instance.journal=None;calls=[]
    instance.admit_release=lambda:calls.append('admit')
    stub_execution(instance)
    for name in ('prepare','migrate','activate'):setattr(instance,name,lambda name=name:calls.append(name))
    instance.run_release()
    assert calls == ['admit','prepare','migrate','activate']
    instance.journal={'phase':'SOURCE_RESTORED'}
    with pytest.raises(ValueError,match='single-use'):instance.run_release()


def stub_execution(instance):
    instance.begin_execution=lambda:setattr(instance,'execution',{})
    instance.check_cancellation=lambda:None
    instance.execution_path=lambda:Path('unused-execution.json')
    instance.common=SimpleNamespace(write_json=lambda *args:None)


@pytest.mark.parametrize('damage',['candidate-settings','settings-bytes'])
def test_release_binds_settings_to_the_accepted_build_before_runtime_readback(tmp_path,release_permission,damage):
    instance=object.__new__(cutover.Cutover)
    instance.source=tmp_path; (tmp_path/'work').mkdir()
    instance.root=tmp_path; instance.runtime=tmp_path/'runtime'
    instance.args=SimpleNamespace(tag=release_permission[1]['release'],source_sha256='b'*64,
                                 approval=str(tmp_path/'work/production-release-approval.json'))
    instance.input={'gitCommit':'a'*40};instance.identity=release_permission[1]['identity'];instance.build_sha='f'*64
    settings=tmp_path/'settings.json';settings.write_text('{}')
    digest=cutover.sha_file(settings)
    instance.build={'settingsSha256':digest if damage=='settings-bytes' else '1'*64}
    approval={**cutover.approve_release(*release_permission),'root':str(tmp_path),'runtime':str(instance.runtime),
              'settings':str(settings),'settingsSha256':digest,
              **dict.fromkeys(['authorizationSha256','runtimeGateSha256','runtimeReceiptSha256','manualDecisionSha256'],'2'*64)}
    Path(instance.args.approval).write_text(json.dumps(approval))
    if damage=='settings-bytes':settings.write_text('{"changed":true}')
    instance.guard=SimpleNamespace(read_private=lambda path:(json.loads(path.read_text()),cutover.sha_file(path)))
    with pytest.raises(ValueError,match='accepted candidate'):instance.admit_release()


@pytest.mark.parametrize('damage',['missing-observation','changed-observation','wrong-path','missing-settings'])
def test_registered_source_observation_cannot_be_skipped_during_recovery(tmp_path,damage):
    instance=object.__new__(cutover.Cutover);instance.work=tmp_path
    instance.journal={'phase':'FAILED_MIGRATE_FROZEN','activationStarted':False,'migrationStarted':True}
    instance.assert_maintenance=lambda:None;instance.migration_sessions_drained=lambda:True
    instance.guard=SimpleNamespace(read_private=lambda path:(json.loads(path.read_text()),cutover.sha_file(path)))
    instance.fence_accounts=lambda **kwargs:pytest.fail('Missing evidence must not unlock source credentials')
    observed=tmp_path/'observation/source-observation.json';observed.parent.mkdir();observed.write_text('{}')
    settings={'reviewedSourceSnapshot':str(observed),'reviewedSourceSnapshotSha256':cutover.sha_file(observed)}
    if damage=='wrong-path':settings['reviewedSourceSnapshot']=str(tmp_path/'foreign.json')
    if damage!='missing-settings':(tmp_path/'migration.json').write_text(json.dumps(settings))
    if damage=='missing-observation':observed.unlink()
    if damage=='changed-observation':observed.write_text('{"changed":true}')
    with pytest.raises(ValueError,match='Registered source observation'):instance.recover()


@pytest.fixture
def cutover_execution(tmp_path,monkeypatch):
    import contextlib
    instance=object.__new__(cutover.Cutover);instance.source=tmp_path;(tmp_path/'work').mkdir()
    instance.root=tmp_path;instance.runtime=tmp_path/'runtime';instance.journal=None
    instance.args=SimpleNamespace(tag='ci-420-'+'a'*12,source_sha256='b'*64)
    instance.input={'gitCommit':'a'*40};instance.input_sha='c'*64;instance.identity={'machineId':'d'*32}
    instance.common=SimpleNamespace(write_json=lambda path,value:path.write_text(json.dumps(value)))
    instance.guard=SimpleNamespace(read_private=lambda path:(json.loads(path.read_text()),cutover.sha_file(path)))
    instance.execution_transport=lambda:SimpleNamespace(supervisor_start=lambda pid:'12345')
    instance.ops=SimpleNamespace(maintenance_lock=lambda root:contextlib.nullcontext(),MaintenanceBusy=BlockingIOError)
    monkeypatch.setattr(cutover.os,'pidfd_open',lambda *args:99)
    monkeypatch.setattr(cutover.os,'close',lambda fd:None)
    signals=[];monkeypatch.setattr(cutover.signal,'pidfd_send_signal',lambda *args:signals.append(args))
    return instance,signals


def test_prestart_cancel_is_persistent_and_prevents_late_start(cutover_execution):
    instance,signals=cutover_execution
    assert instance.cancel()['status']=='CANCELLED_BEFORE_START'
    assert instance.observe_execution()['phase']=='NOT_STARTED'
    with pytest.raises(ValueError,match='cancelled before start'):instance.begin_execution()
    assert signals==[]


def test_owned_cutover_cancel_signals_once_and_waits_for_original_terminal(cutover_execution):
    instance,signals=cutover_execution;instance.begin_execution()
    assert instance.cancel()['status']=='SIGNAL_SENT'
    assert instance.cancel()['status']=='ALREADY_REQUESTED'
    assert signals==[(99,cutover.signal.SIGTERM)]
    with pytest.raises(KeyboardInterrupt):instance.check_cancellation()
    instance.execution.update(terminal=True,phase='SOURCE_RESTORED')
    instance.common.write_json(instance.execution_path(),instance.execution)
    assert instance.cancel()['status']=='ALREADY_TERMINAL'
    assert instance.observe_execution()['phase']=='SOURCE_RESTORED'


@pytest.mark.parametrize('damage',['commit','pid-reuse','foreign-request','missing-execution'])
def test_cutover_cancellation_refuses_unknown_owner_without_sending_signal(cutover_execution,damage):
    instance,signals=cutover_execution;instance.begin_execution()
    if damage=='commit':
        instance.execution['commit']='1'*40;instance.common.write_json(instance.execution_path(),instance.execution)
    elif damage=='pid-reuse':instance.execution_transport=lambda:SimpleNamespace(supervisor_start=lambda pid:'999')
    elif damage=='foreign-request':
        instance.common.write_json(instance.source/'work/cutover-cancel-request.json',{'foreign':True})
    else:
        instance.execution_path().unlink();instance.journal={'phase':'PREPARING'}
    with pytest.raises(ValueError):instance.cancel()
    assert signals==[]


def test_terminal_observation_requires_the_original_maintenance_lock_to_be_released(cutover_execution,monkeypatch):
    instance,_=cutover_execution;instance.begin_execution();instance.execution['terminal']=True
    instance.common.write_json(instance.execution_path(),instance.execution)
    def busy(root):raise BlockingIOError('still held')
    instance.ops.maintenance_lock=busy
    values=iter([0,181]);monkeypatch.setattr(cutover.time,'monotonic',lambda:next(values))
    with pytest.raises(ValueError,match='not released maintenance'):instance.observe_execution()


@pytest.mark.parametrize('child_drained,sql_drained',[(False,True),(True,False)])
def test_source_restore_requires_both_migration_child_and_sql_drain(child_drained,sql_drained):
    instance=object.__new__(cutover.Cutover)
    instance.journal={'phase':'FAILED_MIGRATE_FROZEN','activationStarted':False,'migrationChild':{'drained':child_drained}}
    instance.assert_maintenance=lambda:None;instance.migration_sessions_drained=lambda:sql_drained
    instance.fence_accounts=lambda **kwargs:pytest.fail('Do not unlock a live migration')
    with pytest.raises(ValueError,match='not drained'):instance.recover()


@pytest.mark.parametrize('mode',['success','cancel','undrained','failure'])
def test_migration_child_is_owned_and_drained_before_any_restore(tmp_path,monkeypatch,mode):
    instance=object.__new__(cutover.Cutover);instance.source=tmp_path;instance.work=tmp_path
    instance.identity={'instanceId':'i-owned','machineId':'d'*32};instance.journal={};instance.persist=lambda:None
    instance.execution_transport=lambda:SimpleNamespace(supervisor_start=lambda pid:'77')
    instance.migration_group_members=lambda pid:[pid] if mode=='undrained' else []
    instance.migration_sessions_drained=lambda:True
    calls=[]
    class Child:
        pid=123
        returncode=None
        def poll(self):return self.returncode
        def wait(self,timeout):self.returncode=-2;return -2
    child=Child()
    def spawn(command,**kwargs):
        calls.append((command,kwargs));return child
    def check():
        if mode=='cancel':raise KeyboardInterrupt('requested')
        child.returncode=1 if mode=='failure' else 0
    instance.check_cancellation=check
    monkeypatch.setattr(cutover.subprocess,'Popen',spawn)
    monkeypatch.setattr(cutover.os,'pidfd_open',lambda *args:99)
    monkeypatch.setattr(cutover.os,'close',lambda fd:None)
    monkeypatch.setattr(cutover.os,'getpgid',lambda pid:pid)
    monkeypatch.setattr(cutover.os,'killpg',lambda *args:calls.append(args))
    monkeypatch.setattr(cutover.signal,'signal',lambda *args:None)
    monkeypatch.setattr(cutover.time,'sleep',lambda *args:None)
    if mode=='success':assert instance.invoke_migration('copy','copy-result')==tmp_path/'copy-result'
    else:
        with pytest.raises(KeyboardInterrupt if mode=='cancel' else ValueError):instance.invoke_migration('copy','copy-result')
    assert calls[0][1]['start_new_session'] is True
    assert instance.journal['migrationChild']['drained'] is (mode!='undrained')
    assert ((123,cutover.signal.SIGINT) in calls) is (mode=='cancel')


@pytest.mark.parametrize('window',['spawn','after-exit'])
def test_fast_migration_child_cannot_skip_cancellation_before_activation(tmp_path,monkeypatch,window):
    instance=object.__new__(cutover.Cutover);instance.source=tmp_path;instance.work=tmp_path
    instance.identity={'instanceId':'i-owned','machineId':'d'*32};instance.journal={};instance.persist=lambda:None
    instance.execution_transport=lambda:SimpleNamespace(supervisor_start=lambda pid:'77')
    instance.migration_group_members=lambda pid:[];instance.migration_sessions_drained=lambda:True
    checks=[]
    class Child:
        pid=123;returncode=0
        def poll(self):
            if window=='after-exit':instance._cancelled_during_spawn=True
            return 0
        def wait(self,timeout):return 0
    def spawn(*args,**kwargs):
        if window=='spawn':instance._cancelled_during_spawn=True
        return Child()
    real_check=instance.check_cancellation
    def check():checks.append(True);real_check()
    instance.check_cancellation=check
    monkeypatch.setattr(cutover.subprocess,'Popen',spawn)
    monkeypatch.setattr(cutover.os,'pidfd_open',lambda *args:99)
    monkeypatch.setattr(cutover.os,'close',lambda fd:None)
    monkeypatch.setattr(cutover.signal,'signal',lambda *args:None)
    monkeypatch.setattr(cutover.os,'killpg',lambda *args:pytest.fail('Completed child must not be signalled'))
    with pytest.raises(KeyboardInterrupt):instance.invoke_migration('readback','activation-readback')
    assert instance.journal['migrationChild']['drained'] is True
    assert len(checks)==(1 if window=='spawn' else 2)


def test_cutover_post_cancels_then_observes_then_settles_without_replaying_migration():
    source=(ROOT/'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    section=source.split("if ($Action -in @('CompactCutover','RecoverCutover'))",1)[1].split("if ($Action -eq 'Rehearse')",1)[0]
    assert section.index("'$helper' cancel") < section.index("'$helper' observe") < section.index("{'settle'} else {'run'}")
    assert 'compact-cutover-recovery-receipt.json' in section
    assert 'runtime-acceptance.py' not in section


@pytest.mark.parametrize('damage',['none','other-image','command','process','entrypoint','mount','changed-code','changed-parent'])
def test_only_reviewed_kafka_oss_worker_may_lack_an_independent_sql_identity(damage):
    instance=object.__new__(cutover.Cutover)
    command=['python','/app/kafka_detection_worker.py']
    config={'Cmd':command,'Entrypoint':None,'WorkingDir':'/app'}
    row={'Id':'1'*64,'Image':cutover.LEGACY_KAFKA_ONLY_IMAGE,'Config':dict(config),'Path':'python',
         'Args':['/app/kafka_detection_worker.py'],'Mounts':[{'Destination':'/app/models'}]}
    image={'Id':row['Image'],'Config':config};diff=b''
    if damage=='other-image':row['Image']='sha256:'+'2'*64
    elif damage=='command':row['Config']['Cmd']=['python','foreign.py']
    elif damage=='process':row['Args']=['foreign.py']
    elif damage=='entrypoint':row['Config']['Entrypoint']=['bash']
    elif damage=='mount':row['Mounts'].append({'Destination':'/app/kafka_settings.py'})
    elif damage=='changed-code':diff=b'C /app/kafka_detection_worker.py\n'
    elif damage=='changed-parent':diff=b'C /app\n'
    instance.ops=SimpleNamespace(docker=lambda *args:json.dumps([image]).encode() if args[0]=='image' else diff)
    if damage=='other-image':assert instance.legacy_kafka_only_worker(row) is False
    elif damage=='none':assert instance.legacy_kafka_only_worker(row) is True
    else:
        with pytest.raises(ValueError):instance.legacy_kafka_only_worker(row)


def test_kafka_only_worker_still_enters_the_frozen_inventory_and_complete_source_grants_gate():
    source=(ROOT/'script/docker/compact-cutover.py').read_text(encoding='utf8')
    prepare=source.split('    def prepare(self):',1)[1].split('    def ',1)[0]
    assert "'sqlWriter': False, 'mustStop': True" in prepare
    assert "self.journal['originals'].append" in prepare
    assert "self.ops.docker('update', '--restart=no', row['id'])" in prepare
    assert 'self.check_fenceable_accounts()' in prepare and 'not self.unexpected_source_writers()' in prepare
    assert 'self.fence_accounts()' in prepare and 'self.assert_maintenance()' in prepare


@pytest.mark.parametrize('mutation',['none','foreign-user','active-session','missing-lock'])
def test_post_activation_fence_only_locks_exact_new_target_accounts(tmp_path,mutation):
    instance=object.__new__(cutover.Cutover);instance.work=tmp_path/('compact-cutover-'+'a'*10)
    instance.journal={'targetSchema':'compact_exact'}
    accounts={'app':{'user':'app_'+'a'*10},'worker':{'user':'worker_'+'a'*10}}
    if mutation == 'foreign-user':accounts['app']['user']='root'
    instance.guard=SimpleNamespace(read_private=lambda path:(accounts,'b'*64))
    calls=[]
    def sql(query):
        calls.append(query)
        if 'mysql.user' in query:return '1' if mutation == 'missing-lock' else '2'
        if 'PROCESSLIST' in query:return '1' if mutation == 'active-session' else '0'
        return ''
    instance.sql=sql
    if mutation == 'foreign-user':
        with pytest.raises(ValueError,match='not owned'):instance.fence_target_accounts()
        assert calls == []
    else:
        assert instance.fence_target_accounts() is (mutation == 'none')
        assert calls[:2] == ["ALTER USER 'app_aaaaaaaaaa'@'%' ACCOUNT LOCK;","ALTER USER 'worker_aaaaaaaaaa'@'%' ACCOUNT LOCK;"]
        assert all('DROP ' not in query and 'DELETE ' not in query and 'UNLOCK' not in query for query in calls)


@pytest.mark.parametrize('mutation',['none','image','stopped','unhealthy'])
def test_source_restored_health_reads_real_original_container_state(tmp_path,mutation):
    instance=object.__new__(cutover.Cutover);instance.state=tmp_path
    instance.journal={'phase':'SOURCE_RESTORED','activationStarted':False,
        'originals':[{'id':'1'*64,'image':'sha256:'+'a'*64,'running':True}]}
    actual={'Image':'sha256:'+('b' if mutation == 'image' else 'a')*64,
            'State':{'Running':mutation != 'stopped','Restarting':False}}
    instance.ops=SimpleNamespace(docker=lambda *args:json.dumps([actual]).encode(),healthy=lambda cid:mutation != 'unhealthy')
    if mutation == 'none':instance.restored_health()
    else:
        with pytest.raises(ValueError,match='actual health'):instance.restored_health()
