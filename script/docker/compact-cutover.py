#!/usr/bin/env python3
"""ECS-only first legacy-to-compact cutover, called by the local Jenkins controller.

All credentials, copied data and raw diagnostics remain in private ECS work/state.
prepare, migrate and activate are deliberately separate durable phases. No phase
starts ECS, modifies cloud.env, retries an unknown migration, or falls back to the
old schema after a compact runtime may have written new business data.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import time
import uuid

PROJECT = 'doorhandlecatch-monolith'
DIGEST = re.compile(r'sha256:[a-f0-9]{64}')
TAG = re.compile(r'ci-([1-9][0-9]*)-([a-f0-9]{12})')
SHA = re.compile(r'[a-f0-9]{64}')


def require(value, message):
    if not value:
        raise ValueError(message)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def canonical(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path
            and not any(parent.is_symlink() for parent in (path, *path.parents)), 'Canonical existing path required')
    return path


def fixed_source(archive, source, digest, commit):
    """Match the SCM artifact file-for-file; work/build outputs are excluded by construction."""
    require(SHA.fullmatch(digest) and sha_file(archive) == digest, 'SCM artifact checksum differs')
    entries, total = set(), 0
    with tarfile.open(archive, 'r:gz') as stream:
        for entry in stream:
            name = Path(entry.name)
            require(not name.is_absolute() and '..' not in name.parts and '\\' not in entry.name
                    and (entry.isdir() or entry.isfile()), 'Unsafe SCM artifact member')
            if entry.isdir():
                continue
            require(entry.name not in entries and not name.parts[0] in ('work', '.git')
                    and entry.size <= 128 * 1024 * 1024, 'Invalid SCM artifact file')
            entries.add(entry.name); total += entry.size
            require(total <= 512 * 1024 * 1024, 'SCM artifact exceeds its bounded source budget')
            target = canonical(source / name)
            require(target.is_relative_to(source) and target.is_file() and target.stat().st_size == entry.size,
                    'Candidate release no longer matches the SCM artifact')
            with stream.extractfile(entry) as item:
                expected = hashlib.sha256(item.read()).hexdigest()
            require(sha_file(target) == expected, 'Candidate source differs from the Jenkins SCM artifact')
        require(stream.pax_headers.get('comment') == commit, 'Git archive commit metadata differs from the Jenkins SCM commit')
    require({'script/schema/migrate_compact.py', 'script/docker/compact-cutover.py',
             'script/docker/compact-schema-guard.py', 'docs/database/compact-schema-contract.json'} <= entries,
            'SCM artifact lacks the complete migration and admission implementation')


def may_restore_source(journal):
    # Starting even a health-only backend can run schedulers. No "no user traffic"
    # flag establishes absence of new target writes; recovery remains conservative.
    return journal.get('activationStarted') is False and journal.get('phase') not in ('ACTIVE', 'SOURCE_RESTORED')


def admitted_verification(root, tag, commit, source_sha, identity, guard):
    """A readiness flag cannot substitute for this build's executed ECS evidence."""
    directory = canonical(Path(root) / 'verification' / tag)
    receipt, digest = guard.read_private(directory / 'verification-receipt.json')
    require(all(receipt.get(name) == expected for name, expected in {
        'schema': 1, 'kind': 'doorhandle-ecs-ci', 'release': tag, 'commit': commit,
        'sourceSha256': source_sha, 'identity': identity, 'scope': 'mysql',
        'status': 'PASS', 'verificationExitCode': 0, 'fixtureReadinessValidated': True}.items()),
        'The complete fixed-source MySQL ECS verification did not pass')
    files = receipt.get('reportFiles')
    require(isinstance(files, list) and 0 < len(files) < 10000, 'Verification evidence catalog is missing')
    seen, catalog = set(), {}
    for item in files:
        require(isinstance(item, dict) and set(item) == {'path', 'bytes', 'sha256'}
                and isinstance(item['path'], str) and item['path'] not in seen
                and type(item['bytes']) is int and 0 <= item['bytes'] <= 64 * 1024 * 1024
                and isinstance(item['sha256'], str) and SHA.fullmatch(item['sha256']),
                'Invalid verification artifact binding')
        relative = Path(item['path'])
        require(not relative.is_absolute() and '..' not in relative.parts and '\\' not in item['path'],
                'Verification evidence escaped the owned checkout')
        if item['path'] == 'driver.log':
            file = canonical(directory / 'checkout/driver.log')
        else:
            require(relative.parts[0] == 'reports' and len(relative.parts) >= 2,
                    'Verification artifact has no reviewed evidence location')
            file = canonical(directory / 'checkout/work/ci-evidence' / Path(*relative.parts[1:]))
        require(file.is_relative_to(directory / 'checkout') and file.is_file()
                and file.stat().st_size == item['bytes'] and sha_file(file) == item['sha256'],
                'An executed verification artifact is missing or changed')
        seen.add(item['path'])
        if item['path'].startswith('reports/'):
            catalog[item['path']] = {**item, 'path': item['path'][len('reports/'): ]}
    result_file = directory / 'checkout/work/ci-evidence/receipt.json'
    # The verifier writes public test counts inside its 0700 evidence directory;
    # their bytes have just been checked against the private envelope catalog.
    require(result_file.stat().st_size <= 16 * 1024 * 1024, 'Verification result exceeds its bound')
    result = json.loads(result_file.read_text(encoding='utf8'))
    require(result.get('identity') == identity, 'Test results belong to a different ECS')
    coverage = module('compact_cutover_coverage', Path(__file__).resolve().parents[1] / 'jenkins/compact-acceptance.py')
    profile, profile_sha = coverage.profile(Path(__file__).resolve().parents[2])
    coverage.validate_run(result, profile, profile_sha, result_file.parent, catalog)
    require(sha_file(result_file.with_name('migration.json')) == result.get('wholeMigrationSummarySha256'),
            'The whole-source migration and restoration summary changed')
    require({'reports/receipt.json', 'reports/migration.json'} <= seen,
            'Verification catalog does not bind its complete migration acceptance results')
    return digest


def admitted_runtime(root, tag, commit, source_sha, identity, guard, build, build_sha):
    """Bind every executed runtime scenario and cleanup to this exact candidate."""
    directory = canonical(Path(root) / 'verification' / tag)
    proof, digest = guard.read_private(directory / 'runtime-acceptance.json')
    coverage = module('compact_runtime_coverage', Path(__file__).resolve().parents[1] / 'jenkins/compact-acceptance.py')
    profile, profile_sha = coverage.profile(Path(__file__).resolve().parents[2])
    context = {'schemaVersion': 1, 'kind': 'doorhandle-compact-runtime-acceptance', 'release': tag,
        'commit': commit, 'sourceSha256': source_sha, 'identity': identity,
        'acceptanceProfileSha256': profile_sha, 'candidateBuildSha256': build_sha}
    require(all(proof.get(key) == value for key, value in context.items()) and proof.get('status') == 'PASS'
            and proof.get('images') == {key: build['images'][key] for key in ('backend', 'nginx', 'mem0', 'detection-worker')},
            'The full runtime proof belongs to another build, model protocol or candidate image')
    require(re.fullmatch(r'doorhandle-rehearsal-[a-f0-9]{12}', proof.get('project', ''))
            and SHA.fullmatch(proof.get('migrationReceiptSha256', ''))
            and SHA.fullmatch(proof.get('initialTargetSnapshotSha256', ''))
            and re.fullmatch(r'[a-f0-9-]{36}', proof.get('actualServerUuid', ''))
            and type(proof.get('actualMysqlPort')) is int and 1024 <= proof['actualMysqlPort'] <= 65535
            and proof['actualMysqlPort'] != 3306 and proof.get('paidModelCalls') == 0,
            'Runtime proof lacks its actual owned migration/server binding')
    matrix = json.loads((directory / 'checkout/work/ci-evidence/migration.json').read_text(encoding='utf8'))
    require(matrix.get('migrationReceiptSha256') == proof['migrationReceiptSha256']
            and matrix.get('targetSnapshotSha256') == proof['initialTargetSnapshotSha256'],
            'Runtime did not use the exact whole-migration target accepted by this matrix')
    required = {item['id'] for item in profile['runtimeAcceptance']['scenarios']}
    require(isinstance(proof.get('scenarios'), dict) and set(proof['scenarios']) == required,
            'Every mandatory runtime business scenario must actually have passed')
    def artifact(reference, name):
        require(isinstance(reference, dict) and set(reference) == ({'file', 'sha256', 'status'} if name == 'cleanup' else {'file', 'sha256'})
                and isinstance(reference.get('file'), str) and SHA.fullmatch(reference.get('sha256', '')),
                'A runtime proof reference is malformed')
        relative = Path(reference['file'])
        expected = Path('checkout/work/runtime-acceptance') / (name + '.json')
        require(relative.as_posix() == expected.as_posix(), 'Runtime evidence escaped its fixed owned location')
        value, actual_sha = guard.read_private(canonical(directory / relative))
        require(actual_sha == reference['sha256'] and all(value.get(key) == expected for key, expected in context.items())
                and value.get('project') == proof['project'], 'An actual runtime artifact is missing, changed or foreign')
        return value
    observations = {}
    for name, reference in proof['scenarios'].items():
        value = artifact(reference, 'scenario-' + name)
        require(value.get('scenario') == name and value.get('status') == 'PASS'
                and isinstance(value.get('observations'), dict) and value['observations'],
                'A mandatory runtime scenario was not executed successfully')
        observations[name] = value['observations']
    worker = observations['detection-pth-worker-kafka-receipts'].get('actualUnknownResultFence', {})
    signal = worker.get('actualCompletionSignal', {})
    require(worker.get('status') == 'NEEDS_REVIEW' and worker.get('actualSuccessfulImages') == 1
            and worker.get('actualFailedImages') == 0 and signal.get('error') == 1644 and signal.get('sqlState') == '45000'
            and SHA.fullmatch(signal.get('statementSha256', '')) and SHA.fullmatch(worker.get('unknownRowSha256', ''))
            and SHA.fullmatch(worker.get('actualSummarySha256', ''))
            and worker.get('actualUncommittedPartition', {}).get('lag', 0) > 0,
            'Actual worker completion failure and retained unknown-result fence are missing')
    mcp = observations['private-mcp-install-fetch-cancel-reconcile'].get('actualUnknownControlFault', {})
    require(mcp.get('unknownState') == 'NEEDS_REVIEW' and mcp.get('newInstallationBlockedHttpStatus') == 409
            and mcp.get('newInstallationBlockedReason') == 'PENDING_EXECUTION_EXIT'
            and SHA.fullmatch(mcp.get('denialResponseSha256', ''))
            and mcp.get('reconciledState') == 'REMOVED' and mcp.get('writerExitAndCleanupVerified') is True
            and re.fullmatch(r'[a-f0-9]{64}', mcp.get('observedWriterId', ''))
            and re.fullmatch(r'[a-f0-9]{64}', mcp.get('pausedControllerId', ''))
            and re.fullmatch(r'[a-f0-9]{32}', mcp.get('poolId', '')),
            'Actual unknown MCP writer/control fault and causal reconciliation are missing')
    sdk = observations['sdk-session-workbench-recovery']
    require(sdk.get('interruptedRunId') and sdk.get('resumedRunId') and sdk['interruptedRunId'] != sdk['resumedRunId']
            and type(sdk.get('beforeRestoreRevision')) is int and type(sdk.get('afterRestoreRevision')) is int
            and sdk['afterRestoreRevision'] > sdk['beforeRestoreRevision']
            and SHA.fullmatch(sdk.get('afterRestoreSha256', '')) and sdk.get('cancelledExecutionFence', 0) > 0,
            'Actual SDK checkpoint continuation after restart and cancellation fence are missing')
    recovered = observations['compact-application-upgrade-recovery']
    require(recovered.get('restoredTableCount') == 29 and recovered.get('originalSchema') != recovered.get('restoredSchema')
            and SHA.fullmatch(recovered.get('postBusinessSnapshotSha256', ''))
            and recovered.get('postBusinessSnapshotSha256') == recovered.get('restoredSnapshotSha256')
            and recovered.get('wrongKeyRejectedServices') == ['backend', 'mem0']
            and recovered.get('actualProcessesUseRestoredSchema') is True,
            'Actual post-business 29-table recovery and wrong-key startup rejection are missing')
    recovery, recovery_sha = guard.read_private(directory / 'checkout/work/runtime-acceptance/post-business-recovery/recovery-receipt.json')
    require(recovery_sha == recovered.get('postBusinessRecoveryReceiptSha256')
            and recovery.get('kind') == 'doorhandle-runtime-post-business-recovery' and recovery.get('status') == 'VERIFIED'
            and all(recovery.get(key) == value for key, value in context.items() if key != 'kind')
            and recovery.get('originalMigrationReceiptSha256') == proof['migrationReceiptSha256']
            and recovery.get('sourceSnapshotSha256') == recovered['postBusinessSnapshotSha256']
            and recovery.get('restoredSnapshotSha256') == recovered['restoredSnapshotSha256'],
            'The actual post-business backup/restore proof changed or belongs to another migration')
    cleanup = artifact(proof.get('cleanup'), 'cleanup')
    require(cleanup.get('status') == 'STOPPED' and proof['cleanup'].get('status') == 'STOPPED'
            and cleanup.get('unresolved') == [] and isinstance(cleanup.get('stoppedContainers'), list)
            and cleanup['stoppedContainers'] and all(re.fullmatch(r'[a-f0-9]{64}', cid) for cid in cleanup['stoppedContainers'])
            and cleanup.get('sourceResourcesChanged') is False
            and SHA.fullmatch(cleanup.get('sourceBeforeSha256', ''))
            and cleanup.get('sourceBeforeSha256') == cleanup.get('sourceAfterSha256'), 'Actual owned cleanup has not been confirmed')
    resources = module('compact_runtime_resource_bytes', Path(__file__).resolve().parents[1]
                       / 'jenkins/validate-runtime-resources.py')
    resource_directory = canonical(directory / 'checkout/work/runtime-acceptance')
    resources.validate_files(directory / 'runtime-acceptance.json', resource_directory / 'cleanup.json',
                             resource_directory / 'resource-summary.json',
                             resource_directory / 'resource-probes.jsonl', resource_directory)
    isolation = proof.get('modelIsolation', {})
    fixture = isolation.get('fixtureState', {})
    require(isolation.get('fixtureSourceSha256') == sha_file(Path(__file__).with_name('compact-model-fixture.py'))
            and isolation.get('ossAdapterSourceSha256') == sha_file(Path(__file__).with_name('compact-oss-fixture.py'))
            and isolation.get('internalNetworksVerified') is True and isolation.get('providerCredentialsRemoved') is True
            and fixture.get('kind') == 'doorhandle-owned-scripted-model'
            and type(fixture.get('modelRequests')) is int and fixture['modelRequests'] > 0
            and type(fixture.get('embeddingRequests')) is int and fixture['embeddingRequests'] > 0,
            'The actual isolated model and embedding transport has not been evidenced')
    observed = isolation.get('observedInternalNetworks')
    require(isinstance(observed, list) and {row.get('service') for row in observed} == {'backend', 'mem0', 'model-fixture'}
            and all(row.get('internal') is True and re.fullmatch(r'[a-f0-9]{64}', row.get('networkId', '')) for row in observed),
            'Model-capable services lack actual internal-network observations')
    legacy = proof.get('legacyData')
    if legacy is not None:
        require(isinstance(legacy, dict) and SHA.fullmatch(legacy.get('candidateSha256', ''))
                and SHA.fullmatch(legacy.get('ragManifestSha256', ''))
                and set(legacy.get('verifications', {})) == {'after-start', 'after-restart', 'after-volume-restore'},
                'Native RAG startup/restart/new-volume recovery evidence is incomplete')
        private = directory / 'checkout/work/legacy-candidate'
        require(sha_file(canonical(private / 'legacy-candidate.json')) == legacy['candidateSha256']
                and sha_file(canonical(private / 'rag-preservation-manifest.json')) == legacy['ragManifestSha256'],
                'The actual complete native candidate/manifest changed')
        for phase, reference in legacy['verifications'].items():
            expected = Path('checkout/work/runtime-acceptance') / ('native-readback-' + phase + '.json')
            require(set(reference) == {'file', 'sha256'} and reference['file'] == expected.as_posix()
                    and SHA.fullmatch(reference['sha256']), 'Native readback escaped its owned evidence location')
            value, checksum = guard.read_private(canonical(directory / expected))
            require(checksum == reference['sha256'] and all(value.get(key) == entry for key, entry in context.items() if key != 'kind')
                    and value.get('kind') == 'doorhandle-legacy-runtime-readback' and value.get('status') == 'VERIFIED'
                    and value.get('phase') == phase and value.get('project') == proof['project']
                    and value.get('descriptorSha256') == legacy['candidateSha256']
                    and value.get('ragManifestSha256') == legacy['ragManifestSha256']
                    and value.get('localMem0SemanticStatus') == legacy['localMem0SemanticStatus']
                    and value.get('productionPromotionAllowed') is legacy['productionPromotionAllowed'],
                    'Native startup/restart/recovery readback belongs to another candidate or result')
    return digest


def require_native_release(runtime_proof):
    """A preserved archive/test namespace is never a semantic production import."""
    legacy = runtime_proof.get('legacyData', {})
    require(legacy.get('localMem0SemanticStatus') == 'VERIFIED_AND_ACTIVATED'
            and legacy.get('productionPromotionAllowed') is True,
            'Native legacy semantics/current-cloud final merge are not release-admitted; do not promote an earlier test volume')


class Cutover:
    def __init__(self, args):
        require(sys.platform == 'linux', 'Cutover runs only on the admitted ECS Linux host')
        self.args = args
        self.root, self.runtime = canonical(args.root), canonical(args.runtime)
        require((self.root / 'state').is_dir() and (self.root / 'releases').is_dir(), 'Existing release root required')
        self.state = canonical(self.root / 'state')
        match = TAG.fullmatch(args.tag)
        require(match is not None, 'Fixed Jenkins release tag required')
        self.source = canonical(self.root / 'releases' / args.tag)
        self.archive = canonical(self.root / 'inbox' / args.tag / 'source.tar.gz')
        self.guard = module('cutover_schema_guard', self.source / 'script/docker/compact-schema-guard.py')
        self.common = module('cutover_assignment', self.source / 'script/docker/assignment-compat.py')
        self.ops = module('cutover_ops', self.source / 'script/docker/monolith-ops.py')
        self.input_path = canonical(args.config)
        require(self.input_path.is_relative_to(self.source / 'work'), 'Private cutover input must remain in candidate/work')
        self.input, self.input_sha = self.guard.read_private(self.input_path)
        input_fields = {'version', 'ecs', 'gitCommit', 'buildNumber', 'sourceOffsets', 'candidateImages', 'workbench'}
        require(input_fields <= set(self.input) <= input_fields | {'legacyClockPolicy'}
                and self.input.get('version') == 1, 'Unsupported private cutover input shape')
        clocks = module('cutover_clock_policy', self.source / 'script/schema/compact_clock_policy.py')
        clocks.validate(self.input['sourceOffsets'], self.input.get('legacyClockPolicy'))
        require(re.fullmatch(r'[a-f0-9]{40}', self.input.get('gitCommit', ''))
                and self.input['gitCommit'].startswith(match[2]) and type(self.input['buildNumber']) is int
                and self.input['buildNumber'] == int(match[1]), 'SCM commit, build and release tag differ')
        self.identity = self.guard.ecs_identity(self.input['ecs'])
        build, self.build_sha = self.guard.read_private(self.source / 'candidate-build.json')
        self.build = build
        require(build.get('kind') == 'doorhandle-compact-candidate-build' and build.get('status') == 'BUILT'
                and build.get('release') == args.tag and build.get('commit') == self.input['gitCommit']
                and build.get('sourceSha256') == args.source_sha256 and build.get('inputSha256') == self.input_sha
                and build.get('images') == self.input['candidateImages'] and build.get('ecs') == self.identity
                and build.get('applicationJarSha256') == self.input['workbench'].get('applicationJarSha256'),
                'Candidate input is not bound to the completed Jenkins source/image/artifact build')
        verification_sha = admitted_verification(self.root, args.tag, self.input['gitCommit'],
                                                 args.source_sha256, self.identity, self.guard)
        require(build.get('verificationReceiptSha256') == verification_sha, 'Candidate build uses another verification attempt')
        self.runtime_overlay, runtime_sha = self.guard.read_private(self.source / 'work/candidate-runtime.json')
        require(runtime_sha == build.get('runtimeOverlaySha256'), 'Pinned runtime readers and write-pause settings changed')
        fixed_source(self.archive, self.source, args.source_sha256, self.input['gitCommit'])
        self.envfile = canonical(self.runtime / 'deploy/cloud.env')
        require(self.envfile.stat().st_mode & 0o077 == 0, 'Original runtime environment must remain private')
        self.env_sha = sha_file(self.envfile)
        self.journal_path = self.state / 'compact-cutover.json'
        self.journal = None
        self.mysql = self.common.container(PROJECT, 'mysql')
        require(self.mysql['State']['Running'], 'The existing admitted MySQL must already be running')
        self.images = self.input['candidateImages']
        require(isinstance(self.images, dict) and {'backend', 'nginx', 'mem0', 'detection-worker'} <= set(self.images)
                and all(re.fullmatch(r'[a-z][a-z0-9-]*', key) and DIGEST.fullmatch(value)
                        for key, value in self.images.items()), 'All candidate service images must be immutable local IDs')
        for value in self.images.values():
            rows = json.loads(self.ops.docker('image', 'inspect', value))
            require(len(rows) == 1 and rows[0]['Id'] == value, 'Candidate image is not available locally')
        for service in ('backend', 'detection-worker'):
            self.guard.compact_image(self.images[service], self.common)
        jar = self.input['workbench']
        require(isinstance(jar, dict) and set(jar) == {'java', 'applicationJar', 'applicationJarSha256'},
                'A candidate BootJar and existing Java 17 executable are required')
        require(canonical(jar['applicationJar']).is_relative_to(self.source)
                and sha_file(jar['applicationJar']) == jar['applicationJarSha256'], 'Candidate Java migration artifact differs')
        canonical(jar['java'])
        self.refresh_journal()

    def refresh_journal(self):
        if self.journal_path.exists():
            self.journal, _ = self.guard.read_private(self.journal_path)
            require(all(self.journal.get(name) == value for name, value in {
                'schemaVersion': 1, 'kind': 'doorhandle-first-compact-cutover', 'inputSha256': self.input_sha,
                'tag': self.args.tag, 'sourceArchiveSha256': self.args.source_sha256, 'runtime': str(self.runtime),
                'sourceRoot': str(self.source), 'originalEnvSha256': self.env_sha, 'ecs': self.identity}.items()),
                'An existing cutover belongs to another fixed artifact, configuration or ECS')
            self.work = canonical(self.journal['work'])
        else:
            self.work = self.source / 'work' / ('compact-cutover-' + uuid.uuid4().hex[:10])

    def persist(self, phase=None):
        if phase:
            self.journal['phase'] = phase
        self.journal['updatedAtUtc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        self.common.write_json(self.journal_path, self.journal)

    def current(self):
        ids = self.ops.docker('ps', '-aq', '--no-trunc', '--filter',
                              'label=com.docker.compose.project=' + PROJECT).decode().split()
        require(ids, 'Existing application project is missing')
        return json.loads(self.ops.docker('inspect', *ids))

    def assert_maintenance(self):
        require(sha_file(self.envfile) == self.journal['originalEnvSha256'], 'Original cloud.env changed during cutover')
        frozen = {item['id']: item for item in self.journal['originals']}
        rows = self.current()
        for row in rows:
            service = row['Config']['Labels']['com.docker.compose.service']
            if service in ('mysql', 'redis', 'kafka', 'chroma', 'kafka-init', 'kafka-storage-init'):
                continue
            require(row['Id'] in frozen and not row['State']['Running'] and not row['State']['Restarting']
                    and row['State']['Pid'] == 0 and row['HostConfig']['RestartPolicy'].get('Name') == 'no',
                    'A source writer or ingress escaped the maintenance freeze')
        require(set(frozen) <= {row['Id'] for row in rows}, 'An original writer disappeared before migration verification')
        names = ','.join("'" + row['user'] + "'" for row in self.journal.get('sourceAccounts', []))
        accounts = self.source_account_rows()
        require(accounts and all(row['locked'] == 'Y' for row in accounts), 'Original source runtime credentials are not fenced')
        require(self.journal.get('sourceAccountsApproved') is True and not self.unexpected_source_writers(),
                'The complete source write-identity inventory changed')
        require(self.sql("SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE (DB='"
                         + self.journal['sourceSchema'] + "' OR USER IN (" + names + ")) AND ID<>CONNECTION_ID();") == '0',
                'Another source database session remains active')
        events = self.event_catalog()
        require(not events and not self.routine_catalog()
                and (not self.journal.get('eventCatalogSha256')
                     or self.guard.metadata_sha256(events) == self.journal['eventCatalogSha256']),
                'A source database event changed or remains enabled during migration')
        require(not self.external_source_clients(), 'An unowned container still has a running connection to the source database')

    def external_source_clients(self):
        running = self.ops.docker('ps', '-q', '--no-trunc').decode().split()
        networks = set(self.mysql['NetworkSettings']['Networks'])
        result = []
        for row in json.loads(self.ops.docker('inspect', *running)) if running else []:
            if row['Id'] == self.mysql['Id'] or not networks.intersection(row['NetworkSettings']['Networks']):
                continue
            environment = self.common.environment(row)
            database = environment.get('DETECTION_RECEIPT_DB_DATABASE')
            url = environment.get('DB_URL', '')
            source_client = database == self.journal['sourceSchema'] or bool(re.search(
                r'/' + re.escape(self.journal['sourceSchema']) + r'(?:\?|$)', url))
            if source_client:
                result.append(row['Id'])
        return result

    def event_catalog(self):
        return [json.loads(line) for line in self.sql("SELECT JSON_OBJECT('schema',EVENT_SCHEMA,'name',EVENT_NAME,"
            "'status',STATUS,'definition',EVENT_DEFINITION,'definer',DEFINER,'timeZone',TIME_ZONE,"
            "'type',EVENT_TYPE,'executeAt',EXECUTE_AT,'intervalValue',INTERVAL_VALUE,'intervalField',INTERVAL_FIELD,"
            "'starts',STARTS,'ends',ENDS,'sqlMode',SQL_MODE) FROM information_schema.EVENTS "
            "WHERE EVENT_SCHEMA=DATABASE() ORDER BY EVENT_NAME;").splitlines()]

    def routine_catalog(self):
        return [json.loads(line) for line in self.sql("SELECT JSON_OBJECT('schema',ROUTINE_SCHEMA,'name',ROUTINE_NAME,"
            "'type',ROUTINE_TYPE,'definition',ROUTINE_DEFINITION,'definer',DEFINER) FROM information_schema.ROUTINES "
            "WHERE ROUTINE_SCHEMA=DATABASE() ORDER BY ROUTINE_NAME,ROUTINE_TYPE;").splitlines()]

    def source_account_rows(self):
        expected = self.journal.get('sourceAccounts', [])
        if not expected:
            return []
        predicate = ' OR '.join("(User='" + row['user'] + "' AND Host='" + row['host'] + "')" for row in expected)
        rows = [json.loads(line) for line in self.sql("SELECT JSON_OBJECT('user',User,'host',Host,'locked',account_locked) "
            'FROM mysql.user WHERE ' + predicate + ' ORDER BY User,Host;').splitlines()]
        require({(row['user'], row['host']) for row in rows} == {(row['user'], row['host']) for row in expected},
                'An original source runtime account was removed or replaced')
        return rows

    def fence_accounts(self, restore=False):
        for row in self.journal.get('sourceAccounts', []):
            require(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', row['user']) and row['user'].lower() != 'root'
                    and re.fullmatch(r'[A-Za-z0-9_.:%-]{1,255}', row['host']), 'Original runtime account cannot be safely fenced')
            mode = 'UNLOCK' if restore and row['locked'] == 'N' else 'LOCK'
            self.sql("ALTER USER '" + row['user'] + "'@'" + row['host'] + "' ACCOUNT " + mode + ';')
        actual = self.source_account_rows()
        require(actual and (all(row['locked'] == 'Y' for row in actual) if not restore else
                actual == self.journal['sourceAccounts']), 'Source account lock state was not verified')

    def check_fenceable_accounts(self):
        users = {row['user'] for row in self.journal['sourceAccounts']}
        names = ','.join("'" + user + "'" for user in sorted(users))
        identity = 'SUBSTRING_INDEX(GRANTEE,\'@\',1) IN (' + ','.join("CONCAT(CHAR(39),'" + user + "',CHAR(39))" for user in sorted(users)) + ')'
        require(self.sql('SELECT COUNT(*) FROM information_schema.USER_PRIVILEGES WHERE ' + identity
                         + " AND PRIVILEGE_TYPE<>'USAGE';") == '0',
                'Source runtime cannot use an administrative account with global privileges')
        require(self.sql('SELECT COUNT(*) FROM information_schema.SCHEMA_PRIVILEGES WHERE ' + identity
                         + " AND (TABLE_SCHEMA<>DATABASE() OR IS_GRANTABLE='YES');") == '0',
                'Source runtime cannot use a cross-schema maintenance or delegating account')
        require(self.sql('SELECT COUNT(*) FROM mysql.role_edges WHERE TO_USER IN (' + names + ');') == '0'
                and self.sql('SELECT COUNT(*) FROM mysql.proxies_priv WHERE User IN (' + names + ');') == '0',
                'Source runtime role/proxy grants require separate reviewed fencing')

    def unexpected_source_writers(self):
        privileges = "('INSERT','UPDATE','DELETE','CREATE','ALTER','DROP','TRIGGER','EVENT')"
        sql = ('SELECT DISTINCT GRANTEE FROM (SELECT GRANTEE FROM information_schema.SCHEMA_PRIVILEGES '
               'WHERE TABLE_SCHEMA=DATABASE() AND PRIVILEGE_TYPE IN ' + privileges
               + ' UNION SELECT GRANTEE FROM information_schema.TABLE_PRIVILEGES WHERE TABLE_SCHEMA=DATABASE() AND PRIVILEGE_TYPE IN '
               + privileges + ' UNION SELECT GRANTEE FROM information_schema.USER_PRIVILEGES WHERE PRIVILEGE_TYPE IN '
               + privileges + ' UNION SELECT GRANTEE FROM information_schema.COLUMN_PRIVILEGES WHERE TABLE_SCHEMA=DATABASE() AND PRIVILEGE_TYPE IN '
               + privileges + ') p ORDER BY GRANTEE;')
        require(self.sql('SELECT @@GLOBAL.mandatory_roles;') in ('', 'NONE')
                and self.sql("SELECT COUNT(*) FROM mysql.role_edges WHERE FROM_USER='root' AND TO_USER<>'root';") == '0'
                and self.sql("SELECT COUNT(*) FROM mysql.proxies_priv WHERE User<>'root';") == '0',
                'Unreviewed mandatory roles or maintenance-account delegation prevent a complete source write fence')
        allowed = {(row['user'], row['host']) for row in self.journal.get('sourceAccounts', [])}
        result = []
        for grantee in self.sql(sql).splitlines():
            match = re.fullmatch(r"'([^']+)'@'([^']+)'", grantee)
            require(match is not None, 'Source writer grants cannot be enumerated safely')
            user, host = match.groups()
            # Root is the existing private administrative transport, never a
            # runtime identity to lock. A migration user has source read/trigger
            # metadata grants only; all other old writers require explicit proof.
            if user == 'root' or user == self.journal.get('migrationUser') or (user, host) in allowed:
                continue
            result.append(grantee)
        return result

    def sql(self, sql, schema=None):
        mysql = dict(self.mysql)
        mysql['_doorhandle_database'] = schema or self.journal['sourceSchema']
        return self.common.db(mysql, sql)

    def compose(self, *args, overlays=(), data=None, timeout=240):
        command = ['compose', '--project-name', PROJECT, '--env-file', str(self.envfile)]
        for name in ('compose.monolith.yml', 'compose.cloud.yml', 'compose.detection.yml'):
            command += ['-f', str(self.source / name)]
        if (self.runtime / 'deploy/ai-gateway.enabled').is_file():
            command += ['-f', str(self.source / 'compose.ai-gateway.yml')]
        secret = module('cutover_model_secrets', self.source / 'script/docker/model-secrets.py')
        setting = secret.load_settings(self.root, self.runtime)
        environment = dict(os.environ, DOORHANDLE_ENV_FILE=str(self.envfile),
                           DETECTION_BUILD_CONTEXT=str(self.runtime / 'work/cloud/pth-worker-build'))
        if setting:
            environment['MODEL_CONFIG_MASTER_KEY_SOURCE'] = setting['masterKeyFile']
            command += ['-f', str(self.source / 'compose.model-config.yml')]
        command += ['-f', str(self.work / 'candidate-images.json')]
        for path in overlays:
            command += ['-f', str(path)]
        connection = self.state / 'compact-connection.override.yml'
        if connection.exists():
            command += ['-f', str(connection)]
        return self.ops.docker(*command, *args, data=data, timeout=timeout, env=environment)

    def config(self, overlays=()):
        return json.loads(self.compose('config', '--format', 'json', overlays=overlays))

    def invoke_migration(self, mode, folder, receipt=None):
        output = self.work / folder
        command = [sys.executable, '-B', str(self.source / 'script/schema/migrate_compact.py'), mode,
                   '--config', str(self.work / 'migration.json'), '--output', str(output)]
        if receipt:
            command += ['--receipt', str(receipt)]
        env = {key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')}
        env.update(DOORHANDLE_ECS_INSTANCE_ID=self.identity['instanceId'], DOORHANDLE_ECS_MACHINE_ID=self.identity['machineId'])
        log = self.work / (folder + '.log')
        with log.open('xb') as stream:
            os.chmod(log, 0o600)
            result = subprocess.run(command, cwd=self.source, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=14400)
        require(result.returncode == 0, 'Migration/readback failed or has an unknown result; keep every source writer stopped')
        return output

    def prepare(self):
        require(os.environ.get('DOORHANDLE_COMPACT_RELEASE_READY') == 'true', 'ECS acceptance release gate is closed')
        require(self.journal is None and not (self.state / 'compact-connection.json').exists()
                and not (self.state / 'compact-connection.override.yml').exists(), 'First cutover cannot overwrite existing admission state')
        runtime_sha = admitted_runtime(self.root, self.args.tag, self.input['gitCommit'], self.args.source_sha256,
            self.identity, self.guard, self.build, self.build_sha)
        require_native_release(self.guard.read_private(self.root / 'verification' / self.args.tag / 'runtime-acceptance.json')[0])
        self.work.mkdir(mode=0o700, parents=True)
        backend = self.common.container(PROJECT, 'backend')
        source_schema = self.common.database_name(self.common.environment(backend))
        self.journal = {'schemaVersion': 1, 'kind': 'doorhandle-first-compact-cutover', 'phase': 'PREPARING',
            'ecs': self.identity, 'tag': self.args.tag, 'inputSha256': self.input_sha,
            'sourceArchiveSha256': self.args.source_sha256, 'gitCommit': self.input['gitCommit'],
            'buildNumber': self.input['buildNumber'], 'sourceRoot': str(self.source), 'runtime': str(self.runtime),
            'work': str(self.work), 'originalEnvSha256': self.env_sha, 'sourceSchema': source_schema,
            'runtimeAcceptanceSha256': runtime_sha,
            'activationStarted': False, 'migrationStarted': False, 'originals': []}
        self.persist()
        identity = json.loads(self.sql("SELECT JSON_OBJECT('uuid',@@server_uuid,'version',@@version);"))
        require(identity['version'].startswith('8.4.'), 'Compact migration requires the reviewed MySQL 8.4 runtime')
        self.journal['serverUuid'] = identity['uuid']
        rows = self.current()
        users = set()
        for row in rows:
            service = row['Config']['Labels']['com.docker.compose.service']
            if service in ('backend', 'detection-worker'):
                environment = self.common.environment(row)
                username = environment.get('DB_USERNAME') if service == 'backend' else environment.get('DETECTION_RECEIPT_DB_USER')
                require(isinstance(username, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', username)
                        and username.lower() != 'root', 'Source runtime must use explicitly fenceable non-root accounts')
                users.add(username)
            if service in ('mysql', 'redis', 'kafka', 'chroma', 'kafka-init', 'kafka-storage-init'):
                continue
            require((row['Config'].get('Labels') or {}).get('com.docker.compose.oneoff', '').lower() != 'true',
                    'One-off application work prevents cutover')
            self.journal['originals'].append({'id': row['Id'], 'service': service, 'image': row['Image'],
                'running': bool(row['State']['Running']), 'restartPolicy': row['HostConfig']['RestartPolicy']})
        require({'backend', 'nginx', 'detection-worker', 'mem0'} <= {row['service'] for row in self.journal['originals']},
                'Complete existing writer and ingress inventory required')
        accounts = [json.loads(line) for line in self.sql("SELECT JSON_OBJECT('user',User,'host',Host,'locked',account_locked) "
            'FROM mysql.user WHERE User IN (' + ','.join("'" + user + "'" for user in sorted(users)) + ') ORDER BY User,Host;').splitlines()]
        require({row['user'] for row in accounts} == users, 'Source runtime accounts are not directly identifiable')
        require(all(re.fullmatch(r'[A-Za-z0-9_.:%-]{1,255}', row['host']) and row['locked'] in ('Y', 'N') for row in accounts),
                'Source runtime account host/lock identity cannot be safely represented')
        self.journal['sourceAccounts'] = accounts
        self.persist()
        self.check_fenceable_accounts()
        require(not self.unexpected_source_writers(), 'An unreviewed account can still write the old source schema')
        self.journal['sourceAccountsApproved'] = True
        self.persist()
        # Persist original restart policies before changing them. A daemon restart
        # cannot accidentally wake an old source writer during the migration.
        for row in sorted(self.journal['originals'], key=lambda item: item['service'] != 'nginx'):
            self.ops.docker('update', '--restart=no', row['id'])
            self.ops.docker('stop', '--time', '90', row['id'], timeout=120)
        self.fence_accounts()
        self.assert_maintenance()
        suffix = self.work.name.rsplit('-', 1)[1]
        target = 'doorhandle_compact_candidate_' + suffix
        recovery = {'source': 'doorhandle_legacy_restore_' + suffix, 'target': 'doorhandle_compact_restore_' + suffix}
        self.journal.update(targetSchema=target, recoverySchemas=recovery)
        freeze = {'schemaVersion': 1, 'kind': 'doorhandle-source-writer-freeze', 'ecs': self.identity,
                  'serverUuid': identity['uuid'], 'sourceSchema': source_schema,
                  'writerContainers': sorted(row['id'] for row in self.journal['originals']),
                  'sourceAccounts': self.source_account_rows(), 'eventCatalog': self.event_catalog(),
                  'routineCatalog': self.routine_catalog()}
        freeze['eventCatalogSha256'] = self.guard.metadata_sha256(freeze['eventCatalog'])
        freeze['routineCatalogSha256'] = self.guard.metadata_sha256(freeze['routineCatalog'])
        self.journal['eventCatalogSha256'] = freeze['eventCatalogSha256']
        self.common.write_json(self.work / 'source-freeze.json', freeze)
        user, password = 'mig_' + suffix, secrets.token_hex(32)
        self.journal['migrationUser'] = user
        self.persist()
        self.common.write_json(self.work / 'migration-account.json', {'user': user, 'password': password})
        # Credentials are random lowercase hexadecimal; no shell/SQL interpolation
        # of user-supplied passwords or identifiers enters this administrative SQL.
        self.sql("CREATE USER '" + user + "'@'%' IDENTIFIED BY '" + password + "'; GRANT SELECT,TRIGGER,LOCK TABLES ON `"
                 + source_schema + "`.* TO '" + user + "'@'%'; " + ' '.join(
                     "GRANT ALL PRIVILEGES ON `" + schema + "`.* TO '" + user + "'@'%';" for schema in (target, *recovery.values())))
        collations = dict(line.split('\t') for line in self.sql(
            "SELECT TABLE_NAME,TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME;").splitlines())
        require(len(collations) == 131, 'Actual source is not the complete expected 131-table database')
        addresses = sorted({row.get('IPAddress') for row in self.mysql['NetworkSettings']['Networks'].values()
                            if re.fullmatch(r'[0-9.]+', row.get('IPAddress', ''))})
        require(len(addresses) == 1, 'MySQL has no single unambiguous owned bridge endpoint')
        settings = {'version': 1, **{key: self.identity[key] for key in ('instanceId', 'machineId')},
            'scope': 'production-migration', 'serverUuid': identity['uuid'], 'sourceSchema': source_schema,
            'targetSchema': target, 'sourceOffsets': self.input['sourceOffsets'], 'sourceCollations': collations,
            'connection': {'host': addresses[0], 'port': 3306, 'username': user, 'password': password},
            'client': {'kind': 'docker', 'executable': str(canonical(shutil.which('docker'))), 'containerId': self.mysql['Id']},
            'workbench': self.input['workbench'], 'recoverySchemas': recovery,
            'freezeEvidenceFile': str(self.work / 'source-freeze.json'), 'freezeEvidenceSha256': sha_file(self.work / 'source-freeze.json')}
        if self.input.get('legacyClockPolicy') is not None:
            settings['legacyClockPolicy'] = self.input['legacyClockPolicy']
        self.common.write_json(self.work / 'migration.json', settings)
        self.common.write_json(self.work / 'candidate-images.json', self.runtime_overlay)
        observed = self.invoke_migration('observe', 'observation') / 'source-observation.json'
        settings.update(reviewedSourceSnapshot=str(observed), reviewedSourceSnapshotSha256=sha_file(observed))
        self.common.write_json(self.work / 'migration.json', settings)
        self.persist('PREPARED')

    def migrate(self):
        require(os.environ.get('DOORHANDLE_COMPACT_RELEASE_READY') == 'true', 'ECS acceptance release gate is closed')
        require(self.journal and self.journal['phase'] == 'PREPARED' and not self.journal['migrationStarted'],
                'Migration requires one prepared fresh target; unknown/failed work is never replayed')
        self.assert_maintenance()
        self.journal['migrationStarted'] = True
        self.persist('MIGRATING')
        output = self.invoke_migration('migrate', 'migration')
        receipt = output / 'migration-receipt.json'
        value, digest = self.guard.read_private(receipt)
        self.journal.update(migrationReceiptFile=str(receipt), migrationReceiptSha256=digest)
        require(value.get('status') == 'VERIFIED', 'Complete migration and both restores were not verified')
        # DML-only runtime accounts are distinct from the migration account and
        # the old application account; their secrets never modify cloud.env.
        suffix = self.work.name.rsplit('-', 1)[1]
        app, worker = 'app_' + suffix, 'worker_' + suffix
        app_secret, worker_secret = secrets.token_hex(32), secrets.token_hex(32)
        self.common.write_json(self.work / 'runtime-accounts.json', {
            'app': {'user': app, 'password': app_secret}, 'worker': {'user': worker, 'password': worker_secret}})
        for user, secret in ((app, app_secret), (worker, worker_secret)):
            self.sql("CREATE USER '" + user + "'@'%' IDENTIFIED BY '" + secret + "'; GRANT SELECT,INSERT,UPDATE,DELETE ON `"
                     + self.journal['targetSchema'] + "`.* TO '" + user + "'@'%';")
        original_url = self.common.environment(self.common.container(PROJECT, 'backend'))['DB_URL']
        from urllib.parse import urlsplit, urlunsplit
        parsed = urlsplit(original_url[5:])
        url = 'jdbc:' + urlunsplit(parsed._replace(path='/' + self.journal['targetSchema']))
        overlay = {'services': {'backend': {'environment': {'DB_URL': url, 'DB_USERNAME': app,
            'DB_PASSWORD': app_secret, 'APP_BUSINESS_SEED_ENABLED': 'false'}},
            'detection-worker': {'environment': {'DETECTION_RECEIPT_DB_DATABASE': self.journal['targetSchema'],
            'DETECTION_RECEIPT_DB_USER': worker, 'DETECTION_RECEIPT_DB_PASSWORD': worker_secret}}}}
        self.common.write_json(self.state / 'compact-connection.override.yml', overlay)
        self.persist('MIGRATED')
        self.connection('MIGRATED')
        self.guard.guard(self.state, self.config(), self.source, receipt, allow_cutover=True)

    def connection(self, phase):
        self.common.write_json(self.state / 'compact-connection.json', {
            **self.journal, 'phase': phase, 'overlaySha256': sha_file(self.state / 'compact-connection.override.yml')})

    def activate(self):
        require(os.environ.get('DOORHANDLE_COMPACT_RELEASE_READY') == 'true', 'ECS acceptance release gate is closed')
        require(self.journal and self.journal['phase'] == 'MIGRATED' and not self.journal['activationStarted'],
                'Activation requires the exact complete migration; failed activation cannot be retried automatically')
        require(admitted_runtime(self.root, self.args.tag, self.input['gitCommit'], self.args.source_sha256,
            self.identity, self.guard, self.build, self.build_sha) == self.journal.get('runtimeAcceptanceSha256'),
            'Runtime acceptance changed after the source was frozen')
        self.assert_maintenance()
        receipt = canonical(self.journal['migrationReceiptFile'])
        require(sha_file(receipt) == self.journal['migrationReceiptSha256'], 'Final migration receipt changed')
        self.invoke_migration('verify', 'activation-readback', receipt)
        config = self.config()
        # The backend is reachable only through ingress, which remains stopped
        # until internal health checks, protocols and runtime identity all pass.
        require(not config['services']['backend'].get('ports'), 'Backend must not expose a maintenance-bypassing host port')
        self.guard.guard(self.state, config, self.source, receipt, allow_cutover=True)
        mysql = self.common.selected_mysql(self.mysql, config['services']['backend']['environment'])
        self.guard.inspect_database(mysql, self.source, require_quiescent=True)
        self.common.guard(self.state, config, pin=True)
        secret = module('cutover_model_guard', self.source / 'script/docker/model-secrets.py')
        self.common.write_json(self.state / 'model-secret-transition.json',
                               secret.deployment_guard(self.root, self.runtime, config, pin=True))
        self.journal['activationStarted'] = True
        self.persist('ACTIVATING'); self.connection('ACTIVATING')
        memory = module('cutover_memory', self.source / 'script/docker/memory-compat.py')
        runner = module('cutover_mcp_runtime', self.source / 'script/docker/mcp-runtime.py')
        mcp = module('cutover_mcp_guard', self.source / 'script/docker/mcp-compat.py')
        overlays = []
        transition = runner.prepare(self.state, config)
        overlays.append(self.state / 'mcp-runtime-activation.json')
        if transition['action'] != 'disabled':
            runner.applying(self.state)
            self.compose('up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '120',
                         'mcp-runner', overlays=overlays)
            runner.verify(self.state)
        effective = self.config(overlays)
        mcp.guard(self.state, effective, pin=True)
        action = memory.prepare(self.state, effective)
        overlays.append(self.state / 'memory-activation-images.yml')
        if action == 'replace':
            self.compose('up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '240',
                         'mem0', overlays=overlays)
        memory.verify(self.state)
        if 'higress' in effective['services']:
            self.compose('up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '120',
                         'higress', overlays=overlays)
        for service in ('detection-worker', 'backend'):
            self.compose('up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '240',
                         service, overlays=overlays)
        self.compose('exec', '-T', 'backend', 'curl', '-fsS', 'http://127.0.0.1:8080/actuator/health', overlays=overlays)
        live = self.common.container(PROJECT, 'backend')
        require(live['Image'] == self.images['backend'] and self.common.database_name(self.common.environment(live))
                == self.journal['targetSchema'], 'Activated backend identity or actual database differs')
        worker = self.common.container(PROJECT, 'detection-worker')
        desired_worker = self.config(overlays)['services']['detection-worker']['environment']
        actual_worker = self.common.environment(worker)
        require(worker['Image'] == self.images['detection-worker'] and worker['State']['Running']
                and worker['State'].get('Health', {}).get('Status') == 'healthy'
                and all(str(actual_worker.get(name)) == str(desired_worker.get(name)) for name in (
                    'DETECTION_WORKER_RECEIPTS_ENABLED', 'DETECTION_RECEIPT_DB_HOST', 'DETECTION_RECEIPT_DB_PORT',
                    'DETECTION_RECEIPT_DB_DATABASE', 'DETECTION_RECEIPT_DB_USER', 'DETECTION_RECEIPT_DB_PASSWORD')),
                'Activated worker image or actual compact receipt endpoint/credentials differs')
        self.guard.guard(self.state, self.config(overlays), self.source, receipt, allow_cutover=True)
        # The compact candidate itself is the first compatible recovery reader.
        # Source images remain separate private evidence, never previous-images.
        previous = self.source / 'previous-images.yml'
        # Persist the selected protocol/reader overrides as well as image IDs.
        selected = self.config(overlays)
        previous_services = {}
        for key in self.images:
            spec = selected['services'][key]
            previous_services[key] = {'image': spec['image']}
            keys = {'backend': ('DETECTION_ASSIGNMENT_WRITES_ENABLED', 'AGENT_MCP_WRITES_ENABLED',
                                 'AGENT_MCP_GATEWAY_IMAGE', 'MCP_FETCH_APPROVED_IMAGES'),
                    'mcp-runner': ('MCP_FETCH_IMAGE', 'MCP_FETCH_APPROVED_IMAGES')}.get(key, ())
            values = {name: spec['environment'][name] for name in keys if name in spec.get('environment', {})}
            if values:
                previous_services[key]['environment'] = values
        self.common.write_json(previous, {'services': previous_services})
        runner.publish(self.state, str(self.source), str(self.source), str(previous))
        runner.finalize(self.state)
        self.compose('up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--force-recreate', '--wait',
                     '--wait-timeout', '90', 'nginx', overlays=overlays)
        self.compose('exec', '-T', 'nginx', 'wget', '-q', '-O', '/dev/null', 'http://127.0.0.1/nginx-health', overlays=overlays)
        self.persist('ACTIVE'); self.connection('ACTIVE')
        self.guard.guard(self.state, self.config(overlays), self.source, receipt)

    def recover(self):
        require(self.journal and may_restore_source(self.journal),
                'A compact runtime may have written data; preserve maintenance and recover the compact target or apply a forward repair')
        self.assert_maintenance()
        observed = self.work / 'observation/source-observation.json'
        if observed.exists():
            # Recovering the original source requires an actual fresh full row /
            # metadata/HWM comparison, not the absence of external HTTP traffic.
            sys.path.insert(0, str(self.source / 'script/schema'))
            runtime = module('cutover_recovery_runtime', self.source / 'script/schema/compact_migration_runtime.py')
            settings, _ = self.guard.read_private(self.work / 'migration.json')
            folder = self.work / ('recovery-readback-' + uuid.uuid4().hex[:10])
            folder.mkdir(mode=0o700); (folder / 'private').mkdir(mode=0o700)
            mysql = runtime.Mysql(settings, folder)
            model = json.loads((self.source / 'docs/database/compact-schema-contract.json').read_text())
            expected, _ = self.guard.read_private(observed)
            with mysql.source_lock(settings['sourceSchema'], model['sourceTables']):
                actual = runtime.schema_snapshot(mysql, settings['sourceSchema'], model['sourceTables'])
                require(actual['snapshotSha256'] == expected['sourceSnapshotSha256'], 'The old source changed; source recovery is not approved')
        for file in ('compact-connection.override.yml', 'compact-connection.json'):
            path = self.state / file
            if path.exists():
                require(not path.is_symlink(), 'Connection state cannot be a link')
                # Preserve secrets and cutover evidence privately rather than deleting.
                os.replace(path, self.work / ('aborted-' + file))
        self.fence_accounts(restore=True)
        for row in sorted(self.journal['originals'], key=lambda item: item['service'] == 'nginx'):
            current = json.loads(self.ops.docker('inspect', row['id']))[0]
            require(current['Image'] == row['image'], 'Original source image changed before recovery')
            policy = row['restartPolicy']; name = policy.get('Name') or 'no'
            if name == 'on-failure' and policy.get('MaximumRetryCount'):
                name += ':' + str(policy['MaximumRetryCount'])
            self.ops.docker('update', '--restart=' + name, row['id'])
            if row['running']:
                self.ops.docker('start', row['id'])
                deadline = time.monotonic() + 240
                while not self.ops.healthy(row['id']):
                    require(time.monotonic() < deadline, 'Original source runtime recovery health timed out')
                    time.sleep(1)
        self.persist('SOURCE_RESTORED')

    def fail_closed(self, action):
        if not self.journal:
            return
        # prepare may fail halfway through stopping the source; recover may fail
        # after restarting only some originals. Both need the same real freeze
        # as a partially started target. One failed stop cannot skip the rest.
        exempt = {'mysql', 'redis', 'kafka', 'chroma', 'kafka-init', 'kafka-storage-init'}
        stopped, unresolved, inventory_ok = set(), set(), True
        try:
            rows = self.current()
        except BaseException:
            rows, inventory_ok = [], False
        desired = {row['id']: row['service'] for row in self.journal.get('originals', [])}
        desired.update({row['Id']: row['Config']['Labels']['com.docker.compose.service'] for row in rows})
        live_ids = {row['Id'] for row in rows}
        for container, service in desired.items():
            if service in exempt:
                continue
            # Old IDs may legitimately have been removed by Compose after a
            # candidate was created. A successful full inventory proves absence.
            if inventory_ok and container not in live_ids:
                stopped.add(container)
                continue
            for arguments in (('update', '--restart=no', container), ('stop', '--time', '90', container)):
                try:
                    self.ops.docker(*arguments, timeout=120)
                except BaseException:
                    unresolved.add(container)
            try:
                row = json.loads(self.ops.docker('inspect', container))[0]
                if row['State']['Running'] is False and row['State']['Restarting'] is False and row['State']['Pid'] == 0 \
                        and row['HostConfig']['RestartPolicy'].get('Name') == 'no':
                    stopped.add(container); unresolved.discard(container)
                else:
                    unresolved.add(container)
            except BaseException:
                unresolved.add(container)
        try:
            final = self.current()
            for row in final:
                service = row['Config']['Labels']['com.docker.compose.service']
                if service not in exempt and (row['Id'] not in stopped or row['State']['Running']
                                              or row['State']['Restarting'] or row['State']['Pid'] != 0):
                    unresolved.add(row['Id'])
        except BaseException:
            inventory_ok = False
        account_fence_ok = self.journal.get('sourceAccountsApproved') is True
        if account_fence_ok:
            for account in self.journal.get('sourceAccounts', []):
                try:
                    self.sql("ALTER USER '" + account['user'] + "'@'" + account['host'] + "' ACCOUNT LOCK;")
                except BaseException:
                    account_fence_ok = False
            try:
                account_fence_ok = account_fence_ok and all(row['locked'] == 'Y' for row in self.source_account_rows())
                account_fence_ok = account_fence_ok and not self.unexpected_source_writers()
                account_fence_ok = account_fence_ok and not self.external_source_clients()
                events = self.event_catalog()
                account_fence_ok = account_fence_ok and not events and not self.routine_catalog()
                if self.journal.get('eventCatalogSha256'):
                    account_fence_ok = account_fence_ok and self.guard.metadata_sha256(events) == self.journal['eventCatalogSha256']
                names = ','.join("'" + row['user'] + "'" for row in self.journal.get('sourceAccounts', []))
                account_fence_ok = account_fence_ok and self.sql("SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE "
                    "(DB='" + self.journal['sourceSchema'] + "' OR USER IN (" + names + ")) AND ID<>CONNECTION_ID();") == '0'
            except BaseException:
                account_fence_ok = False
        confirmed = inventory_ok and not unresolved and account_fence_ok
        self.journal['failureFreeze'] = {'action': action, 'confirmed': confirmed,
                                         'sourceAccountsFenced': account_fence_ok,
                                         'unverifiedContainers': sorted(unresolved)}
        phase = 'FAILED_' + action.upper() + ('_FROZEN' if confirmed else '_NEEDS_REVIEW')
        self.persist(phase)
        if (self.state / 'compact-connection.override.yml').exists():
            self.connection(phase)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'migrate', 'activate', 'recover', 'status'))
    for name in ('root', 'runtime', 'tag', 'source-sha256', 'config'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--lock-fd', type=int)
    args = parser.parse_args()
    instance = None
    try:
        instance = Cutover(args)
        with instance.ops.maintenance_lock(instance.root, args.lock_fd):
            instance.refresh_journal()
            try:
                if args.phase != 'status':
                    getattr(instance, args.phase)()
            except BaseException:
                if args.phase != 'status':
                    instance.fail_closed(args.phase)
                raise
            require(instance.journal is not None, 'No cutover has been prepared')
            print(json.dumps({'kind': 'doorhandle-first-compact-cutover', 'phase': instance.journal['phase'],
                              'status': 'ACTIVE' if instance.journal['phase'] == 'ACTIVE' else 'STOPPED_OR_PRIVATE',
                              'sourceTableCount': 131, 'targetTableCount': 29,
                              'release': instance.args.tag, 'commit': instance.input['gitCommit'],
                              'sourceSha256': instance.args.source_sha256, 'ecs': instance.identity,
                              'migrationReceiptSha256': instance.journal.get('migrationReceiptSha256'),
                              'sourceRestorationAllowed': may_restore_source(instance.journal)}))
        return 0
    except BaseException:
        print('Compact cutover did not complete. Preserve private evidence and inspect the freeze/NEEDS_REVIEW phase before recovery.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
