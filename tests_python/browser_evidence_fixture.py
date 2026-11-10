"""Synthetic byte fixture for ECS-only validator tests; never runtime acceptance evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('browser_evidence_fixture_contract', ROOT / 'script/docker/collaboration-browser-evidence.py')
browser = importlib.util.module_from_spec(spec); spec.loader.exec_module(browser)
CID, IMAGE = '9' * 64, 'sha256:' + hashlib.sha256(b'fixture-image:browser').hexdigest()
PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000b49444154789c636000020000050001a5f645400000000049454e44ae426082')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=2) + '\n').encode()); path.chmod(0o600)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report_value(context):
    hashes, required = browser.source_contract(ROOT)
    accounts = {alias: {'userId': str(index), 'role': 'SUPERVISOR' if alias in ('supervisor', 'reviewer') else 'INSPECTOR'}
                for index, alias in enumerate(sorted(browser.ACCOUNTS), 1)}
    checks = {name: {'status': 'PASS'} for name in required}
    checks['twenty-accounts-forty-tabs'].update(accounts=20, actualTabs=40, allAccountsSampled=True,
        backgroundFocusRecovery=True, visibleWatcherAccountsPerRound=19, actualMutationRounds=2)
    checks['latency-p95'].update(samples=20, accounts=20, p95Ms=100, limitMs=2000)
    checks['http1-shared-connections'].update(actualSsePerAccount={alias: 1 for alias in accounts}, sameAccountTabs=2,
        loadPeakSse=20, browserProtocols=['http/1.1'], nginxProtocols=['HTTP/1.1'], publicHttp2Claimed=False)
    checks['resource-samples'].update(samples=1, memoryOomDelta=0, pidsMaxEventsDelta=0)
    checks['artifact-secret-boundary'].update(passwordFieldsMasked=True, exactSecretScan=True,
        cookiesTokensStorageStateHarTraceVideoWritten=False, actualSseLocatorsOnly=True)
    sample = {'memory.max': str(browser.MEMORY), 'pids.max': '512', 'cpu.max': '200000 100000',
        'memory.current': '1048576', 'memory.peak': '2097152', 'pids.current': '10',
        'memory.events': 'oom 0\noom_kill 0\n', 'pids.events': 'max 0\n'}
    return {'schemaVersion': 1, 'commit': context['commit'], 'sourceSha256': context['sourceSha256'], 'status': 'PASS',
        'fullA01A28AcceptanceClaimed': False, 'runnerSourceSha256': hashes, 'checks': checks,
        'runtime': {'browserImageId': IMAGE, 'browserContainerId': CID, 'cpuLimit': 2, 'memoryLimitBytes': browser.MEMORY, 'pidsLimit': 512},
        'tool': {'playwright': '1.65.0', 'actualChromium': '158.0.8127.18', 'expectedChromium': '158.0.8127.18', 'chromiumSandbox': False},
        'accounts': accounts, 'failures': [], 'pageErrors': [],
        'latencySamples': [{'account': alias, 'tab': 1, 'requestId': 'request-'+alias, 'resourceVersion': '1',
            'eventId': 'event-'+alias, 'eventOccurredAt': '2026-11-10T00:00:00Z', 'domAtEpochMs': 1794268800100,
            'eventOccurredToDomMs': 100, 'responseToDomMs': 80, 'visibility': 'visible',
            'filterPageScrollFocusPreserved': True} for alias in accounts],
        'latency': {'samples': 20, 'accountsWithSamples': 20, 'quantile': 'nearest-rank', 'limitMs': 2000,
            'p95Ms': 100, 'serverTimestampIsPreCommitAuditTime': True, 'backgroundTabsIncludedInP95': False, 'backgroundFocusRecoveryAsserted': True},
        'sse': {'allFramesLocatorOnly': True, 'stableAccountContextMismatchFrames': 0},
        'cgroupAdmission': dict(sample), 'resourceSamples': [sample]}


def observation():
    return {'containerId': CID, 'imageId': IMAGE, 'networkId': '7' * 64, 'executionUid': 1000,
        'memoryLimitBytes': browser.MEMORY, 'cpuLimit': 2, 'pidsLimit': 512, 'shmBytes': 256 * browser.MIB,
        'readOnlyRoot': True, 'ownedMountsVerified': True, 'internalNetworkVerified': True,
        'privileged': False, 'hostNamespaces': False, 'running': False, 'exitCode': 0, 'oomKilled': False}


def install(directory, context, project, proof, cleanup):
    directory.mkdir(parents=True, exist_ok=True)
    report = report_value(context)
    file = directory / 'browser-evidence/browser-evidence.json'; report_sha = write(file, report)
    png = directory / 'browser-evidence/screenshots/actual-ui.png'; png.parent.mkdir(exist_ok=True); png.write_bytes(PNG); png.chmod(0o600)
    files = [{'path': browser.PREFIX + path.relative_to(directory).as_posix(), 'bytes': path.stat().st_size,
              'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in (file, png)]
    external = {'before': observation(), 'after': observation(), 'files': files}
    manifest = {**context, 'project': project, 'status': 'EVIDENCE_PRESERVED', 'files': files,
        'browserContainerId': CID, 'browserImageId': IMAGE, 'externalContainerObservation': external}
    digest = write(directory / 'browser-manifest.json', manifest)
    cleanup['browserEvidence'] = {'file': browser.MANIFEST, 'sha256': digest}
    proof['browserAcceptance'] = {'file': browser.REPORT, 'sha256': report_sha, 'externalContainerObservation': external,
        'allA01A28Verified': False, 'requiredBrowserChecksPassed': 18}
    return manifest, report
