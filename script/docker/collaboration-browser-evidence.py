"""Verify original public browser bytes only; no browser, network or container execution."""
import ast
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import stat

MIB = 1024 ** 2
PREFIX = 'checkout/work/runtime-acceptance/'
MANIFEST = PREFIX + 'browser-manifest.json'
REPORT = PREFIX + 'browser-evidence/browser-evidence.json'
SOURCE_NAMES = ('collaboration-browser-runner.py', 'collaboration-browser-proxy.py', 'collaboration-browser-sources.json')
ACCOUNTS = {'inspector', 'peer', 'supervisor', 'reviewer'} | {f'load_{index:02}' for index in range(1, 17)}
MEMORY = 2 * 1024 ** 3
SHA = re.compile(r'[a-f0-9]{64}')


def require(value, message):
    if not value: raise ValueError(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate browser evidence field')
        result[key] = value
    return result


def decode(raw):
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid browser JSON number')))
    require(type(value) is dict, 'Browser evidence must be an object')
    return value


def raw_file(path, maximum):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path
            and all(not item.is_symlink() for item in (path, *path.parents)), 'Browser evidence path is linked or noncanonical')
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= maximum,
            'Browser evidence is missing, linked or oversized')
    raw = path.read_bytes()
    require(len(raw) == info.st_size, 'Browser evidence changed while reading')
    return raw, hashlib.sha256(raw).hexdigest()


def source_contract(source_root):
    directory = Path(source_root) / 'script/docker'
    hashes = {name: raw_file(directory / name, MIB)[1] for name in SOURCE_NAMES}
    tree = ast.parse((directory / SOURCE_NAMES[0]).read_text(encoding='utf8'))
    required = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'REQUIRED' for target in node.targets)]
    require(len(required) == 1 and type(required[0]) is tuple and len(required[0]) == 18
            and len(set(required[0])) == 18, 'Fixed browser source must declare all 18 required checks')
    return hashes, set(required[0])


def public_path(value):
    return value == REPORT or (isinstance(value, str) and re.fullmatch(
        re.escape(PREFIX) + r'browser-evidence/screenshots/[A-Za-z0-9][A-Za-z0-9_-]{0,95}\.png', value) is not None)


def validate_manifest(value, context, project):
    require(all(value.get(key) == expected for key, expected in context.items())
            and value.get('project') == project and value.get('status') == 'EVIDENCE_PRESERVED',
            'Browser manifest is foreign or was not preserved')
    files = value.get('files')
    require(type(files) is list and len(files) <= 128 and type(value.get('rejectedArtifactCount', 0)) is int
            and value.get('rejectedArtifactCount', 0) >= 0, 'Browser file count or rejection evidence exceeds its bound')
    seen, total = set(), 0
    for row in files:
        require(type(row) is dict and set(row) == {'path', 'bytes', 'sha256'} and public_path(row['path'])
                and row['path'] not in seen and type(row['bytes']) is int and 0 < row['bytes'] <= 32 * MIB
                and isinstance(row['sha256'], str) and SHA.fullmatch(row['sha256']),
                'Browser catalog contains an unsafe, duplicate, oversized or unbound file')
        seen.add(row['path']); total += row['bytes']
    require(total <= 128 * MIB, 'Browser evidence total exceeds its bound')
    return files


def revision(value, positive=False):
    return isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,18}' if positive else r'0|[1-9][0-9]{0,18}', value) is not None and int(value) <= 9223372036854775807


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_public_report(value):
    require(value.get('schemaVersion') == 1 and value.get('status') in ('PASS', 'FAIL')
            and value.get('fullA01A28AcceptanceClaimed') is False and type(value.get('checks')) is dict and 0 < len(value['checks']) <= 64
            and all(type(row) is dict and row.get('status') in ('PASS', 'FAIL', 'NOT_EXECUTED') for row in value['checks'].values()),
            'Only controlled public browser reports may be preserved')
    accounts = value.get('accounts', {})
    require(type(accounts) is dict and set(accounts) <= ACCOUNTS
            and all(type(row) is dict and set(row) == {'userId', 'role'} and revision(row['userId'], True)
                    and row['role'] in ('SUPERVISOR', 'INSPECTOR') for row in accounts.values()),
            'Private users or descriptor inputs cannot be preserved as a public report')


def validate_report(report, context, manifest, acceptance, source_root):
    hashes, required = source_contract(source_root)
    require(report.get('schemaVersion') == 1 and report.get('commit') == context['commit']
            and report.get('sourceSha256') == context['sourceSha256'] and report.get('status') == 'PASS'
            and report.get('fullA01A28AcceptanceClaimed') is False and report.get('runnerSourceSha256') == hashes,
            'Browser report has no passing fixed-source execution binding')
    require(type(acceptance) is dict and acceptance.get('file') == REPORT
            and isinstance(acceptance.get('sha256'), str) and SHA.fullmatch(acceptance['sha256'])
            and acceptance.get('allA01A28Verified') is False and acceptance.get('requiredBrowserChecksPassed') == 18,
            'Browser acceptance cannot claim full A01-A28 or omit the actual report')
    checks = report.get('checks')
    require(type(checks) is dict and set(checks) == required
            and all(type(row) is dict and row.get('status') == 'PASS' for row in checks.values())
            and report.get('failures') == [] and report.get('pageErrors') == [], 'All 18 actual browser checks must pass')
    pins = decode(raw_file(Path(source_root) / 'script/docker/collaboration-browser-sources.json', MIB)[0])
    tool = report.get('tool', {})
    require(tool.get('playwright') == pins['playwright']['version']
            and tool.get('actualChromium') == tool.get('expectedChromium') == pins['chromiumHeadlessShell']['version']
            and tool.get('chromiumSandbox') is False, 'Browser tool versions differ from the source pins')
    actual = report.get('runtime', {})
    require(actual == {'browserImageId': manifest.get('browserImageId'), 'browserContainerId': manifest.get('browserContainerId'),
            'cpuLimit': 2, 'memoryLimitBytes': MEMORY, 'pidsLimit': 512}
            and re.fullmatch(r'sha256:[a-f0-9]{64}', str(actual.get('browserImageId', '')))
            and SHA.fullmatch(str(actual.get('browserContainerId', ''))), 'Actual immutable browser image/container differs')
    observed = manifest.get('externalContainerObservation')
    require(type(observed) is dict and observed == acceptance.get('externalContainerObservation')
            and observed.get('files') == manifest['files'], 'External browser observation and preserved files differ')
    for when in ('before', 'after'):
        row = observed.get(when, {})
        require(row.get('containerId') == actual['browserContainerId'] and row.get('imageId') == actual['browserImageId']
                and SHA.fullmatch(str(row.get('networkId', ''))) and row.get('executionUid') == 1000
                and row.get('memoryLimitBytes') == MEMORY and row.get('cpuLimit') == 2 and row.get('pidsLimit') == 512
                and row.get('shmBytes') == 256 * MIB and row.get('readOnlyRoot') is True
                and row.get('ownedMountsVerified') is True and row.get('internalNetworkVerified') is True
                and row.get('privileged') is False and row.get('hostNamespaces') is False
                and row.get('running') is False and row.get('exitCode') == 0 and row.get('oomKilled') is False,
                'External browser namespace, owner, cgroup or process result differs')
    require(observed['before']['networkId'] == observed['after']['networkId'], 'Browser changed its owned network')
    accounts = report.get('accounts')
    require(type(accounts) is dict and set(accounts) == ACCOUNTS
            and all(type(row) is dict and set(row) == {'userId', 'role'} and revision(row['userId'], True)
                    and row['role'] == ('SUPERVISOR' if alias in ('supervisor', 'reviewer') else 'INSPECTOR')
                    for alias, row in accounts.items())
            and len({row['userId'] for row in accounts.values()}) == 20, 'Twenty distinct actual qualified browser accounts are required')
    load = checks['twenty-accounts-forty-tabs']
    require(load.get('accounts') == 20 and load.get('actualTabs') == 40 and load.get('allAccountsSampled') is True
            and load.get('backgroundFocusRecovery') is True and load.get('visibleWatcherAccountsPerRound') == 19
            and type(load.get('actualMutationRounds')) is int and load['actualMutationRounds'] >= 2,
            'Actual forty-tab controlled UI load evidence is missing')
    samples = report.get('latencySamples')
    require(type(samples) is list and 20 <= len(samples) <= 2000, 'Actual latency sample count is insufficient or oversized')
    covered, values, seen = set(), [], set()
    for sample in samples:
        require(type(sample) is dict and sample.get('account') in accounts and sample.get('tab') == 1
                and sample.get('visibility') == 'visible' and sample.get('filterPageScrollFocusPreserved') is True
                and revision(sample.get('resourceVersion')) and isinstance(sample.get('requestId'), str)
                and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', sample['requestId'])
                and isinstance(sample.get('eventId'), str) and re.fullmatch(r'[A-Za-z0-9_-]{1,160}', sample['eventId'])
                and number(sample.get('domAtEpochMs')) and number(sample.get('eventOccurredToDomMs'))
                and number(sample.get('responseToDomMs')), 'Latency sample has no matched visible DOM/event identity')
        key = (sample['account'], sample['requestId'], sample['eventId'])
        require(key not in seen, 'Duplicate latency observation cannot replace independent accounts')
        seen.add(key)
        occurred = datetime.fromisoformat(sample.get('eventOccurredAt', '').replace('Z', '+00:00'))
        require(occurred.tzinfo is not None, 'Actual server event timestamp needs an offset')
        elapsed = sample['domAtEpochMs'] - occurred.timestamp() * 1000
        require(0 <= elapsed < 60000 and abs(round(elapsed, 3) - sample['eventOccurredToDomMs']) <= .0011,
                'Reported latency differs from actual server-event and DOM timestamps')
        values.append(sample['eventOccurredToDomMs']); covered.add(sample['account'])
    p95 = sorted(values)[math.ceil(.95 * len(values)) - 1]
    latency = report.get('latency', {})
    require(covered == ACCOUNTS and latency.get('samples') == len(samples) and latency.get('accountsWithSamples') == 20
            and latency.get('quantile') == 'nearest-rank' and latency.get('limitMs') == 2000
            and latency.get('p95Ms') == p95 and 0 <= p95 <= 2000
            and latency.get('serverTimestampIsPreCommitAuditTime') is True
            and latency.get('backgroundTabsIncludedInP95') is False and latency.get('backgroundFocusRecoveryAsserted') is True
            and checks['latency-p95'].get('samples') == len(samples) and checks['latency-p95'].get('accounts') == 20
            and checks['latency-p95'].get('p95Ms') == p95 and checks['latency-p95'].get('limitMs') == 2000,
            'Actual twenty-account nearest-rank P95 does not meet its two-second bound')
    connections = checks['http1-shared-connections']
    require(connections.get('actualSsePerAccount') == {alias: 1 for alias in ACCOUNTS}
            and connections.get('sameAccountTabs') == 2 and type(connections.get('loadPeakSse')) is int
            and connections['loadPeakSse'] <= 20 and connections.get('browserProtocols') == ['http/1.1']
            and connections.get('nginxProtocols') == ['HTTP/1.1'] and connections.get('publicHttp2Claimed') is False
            and report.get('sse', {}).get('allFramesLocatorOnly') is True
            and report.get('sse', {}).get('stableAccountContextMismatchFrames') == 0,
            'Actual shared SSE transport or account isolation evidence differs')
    resources = report.get('resourceSamples')
    require(type(resources) is list and 1 <= len(resources) <= 1801
            and checks['resource-samples'].get('samples') == len(resources)
            and checks['resource-samples'].get('memoryOomDelta') == 0
            and checks['resource-samples'].get('pidsMaxEventsDelta') == 0,
            'Actual browser cgroup samples are absent')
    admission = report.get('cgroupAdmission', {})
    require(admission.get('memory.max') == str(MEMORY) and admission.get('pids.max') == '512', 'Original browser cgroup admission is missing')
    def counters(value):
        return {key: int(count) for key, count in (line.split() for line in value.splitlines())}
    initial_memory = counters(admission.get('memory.events', ''))
    initial_pids = counters(admission.get('pids.events', ''))
    for sample in resources:
        require(sample.get('memory.max') == str(MEMORY) and sample.get('pids.max') == '512'
                and isinstance(sample.get('cpu.max'), str), 'Browser resource samples changed their actual limits')
        quota, period = map(int, sample['cpu.max'].split())
        require(quota > 0 and period > 0 and quota == 2 * period
                and 0 < int(sample['memory.current']) <= int(sample['memory.peak']) <= MEMORY
                and 0 < int(sample['pids.current']) <= 512, 'Browser resource samples exceeded the admitted cgroup')
        memory_events, pids_events = counters(sample.get('memory.events', '')), counters(sample.get('pids.events', ''))
        require(all(key in initial_memory and memory_events.get(key) == initial_memory[key] for key in ('oom', 'oom_kill'))
                and 'max' in initial_pids and pids_events.get('max') == initial_pids['max'], 'Actual browser cgroup OOM/PID pressure was hidden')
    boundary = checks['artifact-secret-boundary']
    require(boundary.get('passwordFieldsMasked') is True and boundary.get('exactSecretScan') is True
            and boundary.get('cookiesTokensStorageStateHarTraceVideoWritten') is False
            and boundary.get('actualSseLocatorsOnly') is True, 'Browser secret artifact boundary did not pass')
    return {'status': 'VERIFIED', 'checks': 18, 'accounts': 20, 'tabs': 40, 'latencySamples': len(samples),
            'p95Ms': p95, 'productionCapacityVerified': False, 'allA01A28Verified': False,
            'browserContainerId': actual['browserContainerId'], 'browserImageId': actual['browserImageId']}


def validate_files(directory, cleanup, proof=None, source_root=None):
    directory = Path(directory)
    context = {key: cleanup[key] for key in ('schemaVersion', 'kind', 'release', 'commit', 'sourceSha256', 'identity',
                                           'acceptanceProfileSha256', 'candidateBuildSha256')}
    reference = cleanup.get('browserEvidence')
    require(type(reference) is dict and set(reference) == {'file', 'sha256'} and reference.get('file') == MANIFEST
            and isinstance(reference.get('sha256'), str) and SHA.fullmatch(reference['sha256']), 'Cleanup lacks its fixed browser manifest')
    raw, digest = raw_file(directory / 'browser-manifest.json', 256 * 1024)
    require(digest == reference['sha256'], 'Original browser manifest bytes changed')
    manifest = decode(raw); files = validate_manifest(manifest, context, cleanup['project'])
    evidence = directory / 'browser-evidence'
    require(evidence.is_dir() and not evidence.is_symlink(), 'Original browser evidence directory is absent or linked')
    observed = set()
    for path in evidence.rglob('*'):
        require(not path.is_symlink(), 'Unexpected linked browser artifact')
        if path.is_dir():
            require(path == evidence / 'screenshots', 'Unexpected browser evidence subdirectory')
            continue
        observed.add(PREFIX + path.relative_to(directory).as_posix())
        require(len(observed) <= 128, 'Uncataloged browser artifacts exceed the collection bound')
    require(observed == {row['path'] for row in files}, 'Uncataloged browser artifacts cannot enter the archive')
    report, report_sha = None, None
    for row in files:
        file = directory / row['path'][len(PREFIX):]
        raw, digest = raw_file(file, 32 * MIB)
        require(len(raw) == row['bytes'] and digest == row['sha256'], 'Original browser artifact bytes changed')
        if row['path'] == REPORT:
            report, report_sha = decode(raw), digest
            validate_public_report(report)
        else: require(len(raw) >= 33 and raw.startswith(b'\x89PNG\r\n\x1a\n'), 'Browser screenshot is not an original PNG')
    if proof is None:
        return {'status': 'PRESERVED', 'files': len(files), 'browserManifestSha256': reference['sha256']}
    require(all(proof.get(key) == value for key, value in context.items()) and proof.get('project') == cleanup['project']
            and proof.get('status') == 'PASS' and cleanup.get('status') == 'STOPPED'
            and manifest.get('rejectedArtifactCount', 0) == 0
            and report is not None and any(row['path'] != REPORT for row in files), 'Successful runtime lacks the original browser report/screenshots')
    acceptance = proof.get('browserAcceptance')
    require(type(acceptance) is dict and acceptance.get('sha256') == report_sha, 'Runtime browser proof differs from the original report bytes')
    result = validate_report(report, context, manifest, acceptance, source_root or Path(__file__).resolve().parents[2])
    return {**result, 'browserManifestSha256': reference['sha256'], 'browserReportSha256': report_sha}
