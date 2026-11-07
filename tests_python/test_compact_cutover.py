"""ECS-executed failure contracts for the first compact cutover controller."""
import importlib.util
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import pytest


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
    builder = {'id': cid, 'pid': 1200 if name == 'model' else 1201, 'image': build_resources.IMAGE_ID,
               'memoryLimitBytes': build_resources.BUILDER_MEMORY, 'currentBytes': 8 * runtime.MIB,
               'peakBytes': 16 * runtime.MIB, 'oomKills': 0, 'writeRateLimitBytesPerSecond': 64 * runtime.MIB}
    build_context = {key: context[key] for key in ('release', 'commit', 'sourceSha256', 'identity')}
    plans, samples = [], []
    for index, phase in enumerate(('builder-bootstrap', 'build-' + name, 'load-' + name), 1):
        phase += '-%03d' % index
        value = build_resources.phase_plan({**build_context, 'ownerToken': token}, phase, baseline,
            64 * runtime.MIB, build_resources.BUILDER_MEMORY, {'retainedFixtureInputBytes': 1024})
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
    summary = {'version': 1, 'kind': 'doorhandle-candidate-build-resources', **build_context, 'ownerToken': token,
        'status': 'PASS', 'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'productionCapacityVerified': False,
        'baselineProbe': baseline, 'finalProbe': {**baseline, 'monotonic': 102.0}, 'phases': plans,
        'probeFile': 'resource-probes.jsonl', 'probeSha256': hashlib.sha256(raw).hexdigest(), 'monitorFailure': None,
        'originalDataChanged': False, 'cleanup': {'creatorStopped': True, 'builderStopped': True,
            'daemonImportTerminated': True, 'builderContainerId': cid}, 'build': {'images': {name: image}}}
    file = resource / 'resource-summary.json'; write(file, summary)
    return {'file': file.relative_to(directory).as_posix(), 'sha256': cutover.sha_file(file)}, image_id


def attach_runtime_resources(directory, context, project, proof, images, fixture_images):
    resource = directory / 'checkout/work/runtime-acceptance'
    daemons = sorted(set(runtime.SERVICE_MEMORY_MIB) - {'kafka-init', 'kafka-storage-init', 'higress-seed', 'higress-config'})
    metrics = []
    for index, service in enumerate(daemons, 1):
        image = images.get(service, 'sha256:' + hashlib.sha256(('infra:' + service).encode()).hexdigest())
        if service == 'model-fixture': image = fixture_images['model']
        if service == 'mcp-runner': image = fixture_images['mcp']
        metrics.append({'containerId': format(index, '064x'), 'service': service, 'image': image,
            'memoryLimitBytes': runtime.SERVICE_MEMORY_MIB[service] * runtime.MIB,
            'currentBytes': runtime.MIB, 'peakBytes': 2 * runtime.MIB, 'oom': 0, 'oomKills': 0,
            'running': True, 'exitCode': 0})
    metrics.append({'containerId': 'f' * 64, 'service': 'bge-verifier', 'image': images['mem0'],
        'memoryLimitBytes': runtime.BGE_VERIFIER_MEMORY, 'currentBytes': 0, 'peakBytes': 4 * runtime.MIB,
        'oom': 0, 'oomKills': 0, 'running': False, 'exitCode': 0})
    phases, plans, samples = [], {}, []
    declared_memory = sum(runtime.SERVICE_MEMORY_MIB.values()) * runtime.MIB + 512 * runtime.MIB + runtime.BGE_VERIFIER_MEMORY
    for index, phase in enumerate(('runtime-start', 'runtime-backup', 'runtime-restore'), 1):
        baseline = {'capturedAtUnix': 100 + index, 'diskTotalBytes': 40 * runtime.GIB,
            'diskAvailableBytes': 8 * runtime.GIB, 'memoryAvailableBytes': 12 * runtime.GIB}
        plans[phase] = runtime.phase_admission(phase, baseline, runtime.GIB, declared_memory,
            {'retainedFixtureBytes': 1024, 'actualDeclaredMemoryLimitBytes': declared_memory})
        file = resource / ('resource-phase-' + str(index) + '-' + phase + '.json'); write(file, plans[phase])
        phases.append({'phase': phase, 'file': file.relative_to(directory).as_posix(), 'sha256': cutover.sha_file(file)})
        samples.append({'probe': {**baseline, 'phase': phase, 'hostDiskLossUpperBoundBytes': 0,
                                 'diskLossOwnershipProof': False}, 'containers': metrics, 'stopReasons': []})
    raw = b''.join((json.dumps(sample) + '\n').encode() for sample in samples)
    probes = resource / 'resource-probes.jsonl'; probes.write_bytes(raw); probes.chmod(0o600)
    summary = {**context, 'kind': 'doorhandle-bounded-runtime-resources', 'project': project,
        'profile': runtime.RUNTIME_PROFILE, 'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'productionCapacityVerified': False,
        'status': 'MEASURED_FOR_BOUNDED_SCENARIOS', 'pollIntervalSeconds': 2, 'diskFloorBytes': runtime.DISK_FLOOR,
        'memoryFloorBytes': runtime.MEMORY_FLOOR, 'rawProbeFile': 'checkout/work/runtime-acceptance/resource-probes.jsonl',
        'rawProbeSha256': hashlib.sha256(raw).hexdigest(), 'samples': 3,
        'containers': {row['containerId']: row for row in metrics}, 'requiredDaemonServices': daemons,
        'requiredTransientServices': ['bge-verifier'], 'minimumDiskAvailableBytes': 8 * runtime.GIB,
        'minimumMemoryAvailableBytes': 12 * runtime.GIB, 'latestProbeAtUnix': 103, 'phases': phases, 'phasePlans': plans}
    file = resource / 'resource-summary.json'; write(file, summary)
    reference = {'file': file.relative_to(directory).as_posix(), 'sha256': cutover.sha_file(file)}
    proof['resourceEvidence'] = reference
    proof['loadScope'] = {'profile': runtime.RUNTIME_PROFILE, 'productionPerformanceVerified': False,
                          'productionCapacityVerified': False, 'allMandatoryScenariosRequired': True}
    cleanup_file = directory / proof['cleanup']['file']
    cleanup = json.loads(cleanup_file.read_text()); cleanup['resourceEvidence'] = reference
    cleanup['fixtureBuildResources'] = proof['fixtureBuildResources']; write(cleanup_file, cleanup)
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
    for name in ('model', 'mcp'):
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
