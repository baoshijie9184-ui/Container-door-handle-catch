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
import signal
import stat
import subprocess
import sys
import tarfile
import time
import uuid

PROJECT = 'doorhandlecatch-monolith'
DIGEST = re.compile(r'sha256:[a-f0-9]{64}')
TAG = re.compile(r'ci-([1-9][0-9]*)-([a-f0-9]{12})')
SHA = re.compile(r'[a-f0-9]{64}')
# Reviewed running pre-receipt worker: Kafka/OSS only, with no SQL client or
# receipt module. This is an immutable historical image, not an absent-env bypass.
LEGACY_KAFKA_ONLY_IMAGE = 'sha256:4bbc067a144707e7764de7a4e1e7e5450ea2618c7ed74ee8d5c84d0f3defa8c3'
RELEASE_INPUTS = ('REMOTE_ROOT', 'REMOTE_RUNTIME', 'COMPACT_CUTOVER_SETTINGS', 'LOCAL_MYSQL_FIXTURE_SETTINGS',
    'LEGACY_SOURCE_SNAPSHOT', 'LEGACY_SOURCE_ECS_SNAPSHOT', 'LOCAL_ARTIFACTS_SNAPSHOT',
    'LOCAL_ARTIFACTS_ECS_SNAPSHOT', 'LOCAL_ARTIFACTS_PROFILE', 'LOCAL_MYSQL_SNAPSHOT',
    'LOCAL_MYSQL_ECS_SNAPSHOT', 'COLD_STORES_SNAPSHOT', 'COLD_STORES_ECS_SNAPSHOT',
    'COLD_STORES_PROFILE', 'COLD_HISTORY_SNAPSHOT', 'COLD_HISTORY_ECS_SNAPSHOT',
    'PROJECT_MYSQL_SNAPSHOT', 'PROJECT_MYSQL_MANIFEST_SHA256', 'PROJECT_MYSQL_ARCHIVE_SHA256',
    'REMAINING_SYSTEM_DATA_SNAPSHOT', 'REMAINING_SYSTEM_DATA_ECS_SNAPSHOT',
    'CANDIDATE_BUILD_TOOLS_ARCHIVE')


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


def approve_release(authorization, request, gate, proof, decision):
    """Controller-only permission check; actual ECS evidence is checked again before freeze."""
    context = {key: request.get(key) for key in ('release', 'commit', 'sourceSha256', 'identity')}
    match = TAG.fullmatch(context['release'] or '')
    require(match and re.fullmatch(r'[a-f0-9]{40}', context['commit'] or '')
            and context['commit'].startswith(match[2]) and SHA.fullmatch(context['sourceSha256'] or ''),
            'Release authorization requires one fixed build')
    require(authorization.get('schemaVersion') == 1
            and authorization.get('kind') == 'doorhandle-compact-release-authorization'
            and authorization.get('scope') == 'first-production-131-to-29'
            and authorization.get('job') == 'doorhandle-java' and authorization.get('branch') == 'java-cloud'
            and authorization.get('approved') is True and authorization.get('revoked') is False
            and authorization.get('allowPreActivationSourceRestore') is True
            and authorization.get('afterActivationFailure') == 'FAIL_CLOSED_COMPACT_ONLY'
            and isinstance(authorization.get('approvalReference'), str)
            and 1 <= len(authorization['approvalReference']) <= 256,
            'Explicit current-task release and recovery authorization is required')
    require(all(authorization.get(key) == context[key] for key in ('commit', 'sourceSha256', 'identity'))
            and set(request.get('inputs', {})) == set(RELEASE_INPUTS)
            and all(isinstance(value, str) for value in request['inputs'].values())
            and authorization.get('inputs') == request['inputs']
            and SHA.fullmatch(request.get('settingsSha256', ''))
            and authorization.get('settingsSha256') == request['settingsSha256'],
            'Approved fixed source or inputs differ')
    require(gate.get('kind') == 'doorhandle-runtime-gate-passed' and gate.get('status') == 'VERIFIED'
            and all(gate.get(key) == context[key] for key in ('release', 'commit', 'sourceSha256'))
            and proof.get('status') == 'PASS' and all(proof.get(key) == value for key, value in context.items())
            and gate.get('candidateBuildSha256') == proof.get('candidateBuildSha256')
            and SHA.fullmatch(gate.get('candidateBuildSha256', '')),
            'This same build has not completed runtime and owned cleanup')
    manual = proof.get('manualAcceptance', {})
    require(manual.get('enabled') is True and manual.get('status') == 'ACCEPTED'
            and decision.get('decision') == 'ACCEPTED'
            and all(decision.get(key) == proof.get(key) for key in ('release', 'commit', 'sourceSha256', 'candidateBuildSha256'))
            and decision.get('executionId') == manual.get('executionId')
            and decision.get('submittedBy') == manual.get('submittedBy')
            and isinstance(manual.get('submittedBy'), str) and manual['submittedBy']
            and all(type(manual.get(key)) in (int, float) for key in ('readyAtUnix', 'submittedAtUnix', 'expiresAtUnix'))
            and manual['readyAtUnix'] <= manual['submittedAtUnix'] < manual['expiresAtUnix']
            and decision.get('submittedAtUnix') == manual['submittedAtUnix'],
            'The original human acceptance decision is missing, rejected or foreign')
    return {'schemaVersion': 1, 'kind': 'doorhandle-compact-release-approval', **context,
            'candidateBuildSha256': gate['candidateBuildSha256'],
            'root': request['inputs']['REMOTE_ROOT'], 'runtime': request['inputs']['REMOTE_RUNTIME'],
            'settings': request['inputs']['COMPACT_CUTOVER_SETTINGS'],
            'settingsSha256': request['settingsSha256'],
            'approvalReference': authorization['approvalReference'],
            'allowPreActivationSourceRestore': True, 'afterActivationFailure': 'FAIL_CLOSED_COMPACT_ONLY'}


def authorize_files(args):
    # No environment, credentials or original authorization text is archived.
    def read(path):
        path = canonical(Path(path).absolute()); metadata = path.stat()
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1 and 0 < metadata.st_size <= 1024 * 1024,
                'Bounded unlinked controller receipt required')
        raw = path.read_bytes()
        return json.loads(raw.decode('utf-8-sig')), hashlib.sha256(raw).hexdigest()
    authorization, authorization_sha = read(args.authorization)
    request, _ = read(args.request)
    gate, gate_sha = read(args.runtime_gate)
    proof, proof_sha = read(args.runtime_proof)
    decision, decision_sha = read(args.manual_decision)
    require(gate.get('runtimeReceiptSha256') == proof_sha, 'Original runtime receipt bytes differ')
    result = approve_release(authorization, request, gate, proof, decision)
    result.update(authorizationSha256=authorization_sha, runtimeGateSha256=gate_sha,
                  runtimeReceiptSha256=proof_sha, manualDecisionSha256=decision_sha)
    print(json.dumps(result))
    return 0


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
    fixture_builds = proof.get('fixtureBuildResources')
    require(isinstance(fixture_builds, dict) and set(fixture_builds) == {'model', 'mcp', 'browser'}, 'Owned runtime fixture build proofs are missing')
    build_resources = module('cutover_fixture_build_resources', Path(__file__).with_name('compact-build-resources.py'))
    build_context = {'release': tag, 'commit': commit, 'sourceSha256': source_sha, 'identity': identity}
    for name, reference in fixture_builds.items():
        expected = 'checkout/work/runtime-acceptance/controlled-build-' + name + '/resource-summary.json'
        require(isinstance(reference, dict) and set(reference) == {'file', 'sha256'} and reference.get('file') == expected,
                'Runtime fixture build reference escaped its owned directory')
        resource_directory = canonical(directory / Path(expected).parent)
        build_resources.validate_files(resource_directory, build_context, require_services=False)
        require(sha_file(resource_directory / 'resource-summary.json') == reference['sha256'], 'Runtime fixture build bytes changed')
        if name == 'browser':
            browser_build = guard.read_private(resource_directory / 'resource-summary.json')[0]
            require(set(browser_build['build']['images']) == {'browser'}, 'Browser build image set differs')
            browser_image = browser_build['build']['images']['browser']['imageId']
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
    browser = module('cutover_browser_evidence_bytes', Path(__file__).with_name('collaboration-browser-evidence.py'))
    browser_result = browser.validate_files(canonical(directory / 'checkout/work/runtime-acceptance'), cleanup, proof,
                                            Path(__file__).resolve().parents[2])
    require(browser_result['browserImageId'] == browser_image, 'Executed browser differs from its measured immutable build')
    collaboration = module('cutover_collaboration_evidence_bytes', Path(__file__).with_name('collaboration-acceptance-evidence.py'))
    browser_report = browser.decode(browser.raw_file(canonical(directory / 'checkout/work/runtime-acceptance/browser-evidence/browser-evidence.json'), 32 * 1024 ** 2)[0])
    collaboration.validate_files(canonical(directory / 'checkout/work/runtime-acceptance'), cleanup, proof,
                                 browser_report, owned_runtime_directory=True)
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
                    and value.get('localMem0SemanticStatus') == 'PHASE_SEMANTIC_VERIFIED'
                    and value.get('candidateSemanticVerified') is True and value.get('productionDataMaterialized') is False
                    and value.get('productionPromotionAllowed') is legacy['productionPromotionAllowed'],
                    'Native startup/restart/recovery readback belongs to another candidate or result')
            semantic_ref = value.get('bgeSemanticVerification', {})
            semantic_path = Path('checkout/work/runtime-acceptance') / ('bge-semantic-' + phase + '.json')
            require(set(semantic_ref) == {'file', 'sha256'} and semantic_ref['file'] == semantic_path.as_posix(),
                    'BGE phase evidence escaped its fixed source outcome')
            semantic, checksum = guard.read_private(canonical(directory / semantic_path))
            helper = module('cutover_actual_semantic_receipt', Path(__file__).resolve().parents[1] / 'jenkins/prepare-legacy-candidate.py')
            helper.validate_semantic_receipt(semantic, guard.read_private(private / 'mem0-semantic-plan.json')[0])
            require(checksum == semantic_ref['sha256'] and semantic.get('phase') == phase
                    and semantic.get('candidateSha256') == legacy['candidateSha256']
                    and semantic.get('sourceSha256', context['sourceSha256']) == context['sourceSha256']
                    and semantic.get('helperCleanup', {}).get('pid') == 0
                    and semantic.get('helperCleanup', {}).get('exitCode') == 0, 'BGE original phase/cleanup evidence changed')
        activation = legacy.get('semanticActivation', {})
        expected = 'checkout/work/runtime-acceptance/native-semantic-activation.json'
        require(set(activation) == {'file', 'sha256'} and activation['file'] == expected, 'Semantic activation location is invalid')
        activated, checksum = guard.read_private(canonical(directory / expected))
        require(checksum == activation['sha256'] and activated.get('status') == 'VERIFIED_AND_ACTIVATED'
                and activated.get('candidateSemanticVerified') is True and activated.get('productionDataMaterialized') is False
                and activated.get('candidateSha256') == legacy['candidateSha256']
                and set(activated.get('verifications', {})) == set(legacy['verifications'])
                and all(activated['verifications'][phase].get('readback') == ref for phase, ref in legacy['verifications'].items()),
                'Three-phase activation receipt changed')
    return digest


def require_native_release(runtime_proof):
    """A preserved archive/test namespace is never a semantic production import."""
    legacy = runtime_proof.get('legacyData', {})
    require(legacy.get('localMem0SemanticStatus') == 'VERIFIED_AND_ACTIVATED'
            and legacy.get('verificationSubject') == 'INDEPENDENT_REAL_BGE_CANDIDATE'
            and legacy.get('appRuntimeValidationMode') == 'ISOLATED_MOCK_QDRANT_RUNTIME'
            and legacy.get('vectorBackend') == 'qdrant' and legacy.get('storageGeneration') == 'qdrant-bge-m3-v1'
            and legacy.get('candidateSemanticVerified') is True and legacy.get('productionDataMaterialized') is False
            and legacy.get('activatedLocalMem0Records') == 30 and legacy.get('productionPromotionAllowed') is False
            and isinstance(legacy.get('semanticActivation'), dict),
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
        resources = module('cutover_candidate_build_resources', self.source / 'script/docker/compact-build-resources.py')
        resources.validate_candidate(build, self.source,
            {'release': args.tag, 'commit': self.input['gitCommit'], 'sourceSha256': args.source_sha256, 'identity': self.identity})
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

    def admit_release(self):
        path = canonical(self.args.approval)
        require(path == self.source / 'work/production-release-approval.json', 'Release approval escaped its fixed candidate')
        approval, digest = self.guard.read_private(path)
        require(approval.get('schemaVersion') == 1 and approval.get('kind') == 'doorhandle-compact-release-approval'
                and all(approval.get(key) == value for key, value in {
                    'release': self.args.tag, 'commit': self.input['gitCommit'],
                    'sourceSha256': self.args.source_sha256, 'identity': self.identity,
                    'root': str(self.root), 'runtime': str(self.runtime),
                    'candidateBuildSha256': self.build_sha}.items())
                and all(SHA.fullmatch(approval.get(key, '')) for key in
                        ('authorizationSha256', 'runtimeGateSha256', 'runtimeReceiptSha256', 'manualDecisionSha256'))
                and approval.get('allowPreActivationSourceRestore') is True
                and approval.get('afterActivationFailure') == 'FAIL_CLOSED_COMPACT_ONLY',
                'Controller approval belongs to another candidate or policy')
        require(approval['settingsSha256'] == self.build.get('settingsSha256')
                and sha_file(canonical(approval['settings'])) == approval['settingsSha256'],
                'Approved source settings changed from the accepted candidate')
        directory = self.root / 'verification' / self.args.tag
        proof, proof_sha = self.guard.read_private(directory / 'runtime-acceptance.json')
        decision, decision_sha = self.guard.read_private(directory / 'checkout/work/runtime-acceptance/manual-decision.json')
        require(proof_sha == approval['runtimeReceiptSha256'] and decision_sha == approval['manualDecisionSha256']
                and proof.get('manualAcceptance', {}).get('status') == 'ACCEPTED'
                and proof['manualAcceptance'].get('enabled') is True and decision.get('decision') == 'ACCEPTED'
                and all(decision.get(key) == proof.get(key) for key in ('release', 'commit', 'sourceSha256', 'candidateBuildSha256'))
                and decision.get('executionId') == proof['manualAcceptance'].get('executionId')
                and decision.get('submittedAtUnix') == proof['manualAcceptance'].get('submittedAtUnix'),
                'Original manual and runtime acceptance changed before production freeze')
        require(admitted_runtime(self.root, self.args.tag, self.input['gitCommit'], self.args.source_sha256,
                                 self.identity, self.guard, self.build, self.build_sha) == proof_sha,
                'The exact accepted runtime is required before production freeze')
        if self.journal:
            require(self.journal.get('releaseApprovalSha256') == digest, 'Original cutover approval changed')
        self.release_approval_sha = digest

    def restored_health(self):
        require(self.journal['phase'] == 'SOURCE_RESTORED' and self.journal['activationStarted'] is False,
                'Source restoration was not completed')
        for original in self.journal['originals']:
            current = json.loads(self.ops.docker('inspect', original['id']))[0]
            require(current['Image'] == original['image'] and current['State']['Running'] == original['running']
                    and not current['State']['Restarting']
                    and (not original['running'] or self.ops.healthy(original['id'])),
                    'Restored source runtime failed its actual health readback')
        require(not (self.state / 'compact-connection.override.yml').exists(), 'Target connection remains active after source restoration')

    def settle(self):
        """Idempotent same-build failure disposition; never replay migration or target writes."""
        if not self.journal:
            return {'status': 'NOT_STARTED', 'sourceRestored': False, 'targetWritesPreserved': True}
        if self.journal['phase'] == 'ACTIVE':
            return {'status': 'ACTIVE', 'sourceRestored': False, 'targetWritesPreserved': True}
        if self.journal['phase'] == 'SOURCE_RESTORED':
            self.restored_health()
            outcome = {'status': 'SOURCE_RESTORED', 'sourceRestored': True, 'healthVerified': True}
        else:
            self.fail_closed('settle')
            require(self.journal.get('failureFreeze', {}).get('confirmed') is True,
                    'Writer freeze is unresolved; retain all evidence and require exact component repair')
            if may_restore_source(self.journal):
                try:
                    self.recover()
                    self.restored_health()
                except BaseException:
                    self.fail_closed('recover')
                    raise
                outcome = {'status': 'SOURCE_RESTORED', 'sourceRestored': True, 'healthVerified': True}
            else:
                require(self.journal.get('activationStarted') is True, 'Unknown activation state cannot authorize recovery')
                outcome = {'status': 'COMPACT_FORWARD_REQUIRED', 'sourceRestored': False,
                           'freezeConfirmed': True, 'targetWritesPreserved': True,
                           'targetSchema': self.journal['targetSchema'], 'migrationReplayed': False,
                           'nextAction': 'REPAIR_FAILED_COMPONENT_PRESERVING_COMPACT_DATA'}
        self.common.write_json(self.work / 'recovery-receipt.json', {
            'kind': 'doorhandle-compact-cutover-recovery', 'release': self.args.tag,
            'commit': self.input['gitCommit'], 'sourceSha256': self.args.source_sha256,
            'identity': self.identity, 'activationStarted': self.journal['activationStarted'], **outcome})
        self.journal['recovery'] = {'file': str(self.work / 'recovery-receipt.json'),
                                    'sha256': sha_file(self.work / 'recovery-receipt.json'), **outcome}
        self.persist()
        return outcome

    def run_release(self):
        self.admit_release()
        require(self.journal is None, 'First cutover is single-use; use its controlled settlement, never replay it')
        self.begin_execution()
        try:
            for phase in ('prepare', 'migrate', 'activate'):
                self.check_cancellation()
                getattr(self, phase)()
            self.check_cancellation()
        except BaseException:
            # A second Jenkins interruption must not interrupt owned fail-closed
            # work. The outer controller keeps the original failure result.
            for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                signal.signal(signum, signal.SIG_IGN)
            # Even the final ACTIVE readback can fail after publication. Do not
            # mistake that durable intent for a successful outer execution.
            self.fail_closed(phase)
            self.settle()
            raise
        finally:
            self.execution['terminal'] = True
            self.execution['phase'] = (self.journal or {}).get('phase', 'NOT_STARTED')
            self.common.write_json(self.execution_path(), self.execution)

    def execution_path(self):
        return self.source / 'work/cutover-execution.json'

    def execution_context(self):
        return {'schemaVersion': 1, 'kind': 'doorhandle-compact-cutover-execution',
                'release': self.args.tag, 'commit': self.input['gitCommit'],
                'sourceSha256': self.args.source_sha256, 'inputSha256': self.input_sha,
                'runtime': str(self.runtime), 'identity': self.identity}

    def execution_transport(self):
        return module('cutover_execution_transport', self.source / 'script/jenkins/verify-remote.py')

    def begin_execution(self):
        import fcntl
        with (self.source / 'work/cutover-cancel.lock').open('a') as stream:
            os.chmod(stream.name, 0o600); fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            require(not self.execution_path().exists(), 'Do not restart an already requested cutover')
            require(not (self.source / 'work/cutover-cancel-request.json').exists(), 'Cutover was cancelled before start')
            self.execution = {**self.execution_context(), 'terminal': False,
                'supervisor': {'pid': os.getpid(), 'startTicks': self.execution_transport().supervisor_start(os.getpid()),
                               'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}}
            self.common.write_json(self.execution_path(), self.execution)

    def read_execution(self):
        value, _ = self.guard.read_private(self.execution_path())
        require(all(value.get(key) == expected for key, expected in self.execution_context().items())
                and type(value.get('terminal')) is bool, 'Original cutover execution identity differs')
        supervisor = value.get('supervisor', {})
        require(set(supervisor) == {'pid', 'startTicks', 'bootId'}
                and type(supervisor['pid']) is int and supervisor['pid'] > 1
                and isinstance(supervisor['startTicks'], str) and supervisor['startTicks'].isdigit()
                and supervisor['bootId'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'Original cutover supervisor identity differs')
        return value

    def check_cancellation(self):
        if getattr(self, '_cancelled_during_spawn', False):
            raise KeyboardInterrupt('Owned cutover cancellation received during migration spawn')
        path = self.source / 'work/cutover-cancel-request.json'
        if hasattr(self, 'execution') and path.exists():
            value, _ = self.guard.read_private(path)
            require(value == {**self.execution_context(), 'supervisor': self.execution['supervisor'], 'requestedSignal': 'SIGTERM'},
                    'Cutover cancellation belongs to another execution')
            raise KeyboardInterrupt('Owned cutover cancellation requested')

    def cancel(self):
        """One normal signal to the exact owner; never a signal to MySQL or business containers."""
        import fcntl
        ack = {**self.execution_context(), 'operation': 'cutover-cancellation', 'terminal': False,
               'requestedSignal': 'SIGTERM'}
        lock = self.source / 'work/cutover-cancel.lock'
        with lock.open('a') as stream:
            os.chmod(lock, 0o600); fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if not self.execution_path().exists():
                require(self.journal is None, 'Missing execution ownership for an existing cutover')
                request = {**self.execution_context(), 'supervisor': None, 'requestedSignal': 'SIGTERM'}
                path = self.source / 'work/cutover-cancel-request.json'
                if path.exists():
                    require(self.guard.read_private(path)[0] == request, 'Conflicting pre-start cancellation')
                else:
                    self.common.write_json(path, request)
                return {**ack, 'status': 'CANCELLED_BEFORE_START', 'terminal': True}
            value = self.read_execution()
            if value['terminal']:
                return {**ack, 'terminal': True, 'status': 'ALREADY_TERMINAL'}
            supervisor = value['supervisor']; path = self.source / 'work/cutover-cancel-request.json'
            request = {**self.execution_context(), 'supervisor': supervisor, 'requestedSignal': 'SIGTERM'}
            if path.exists():
                prior, _ = self.guard.read_private(path)
                require(prior == request, 'Conflicting cutover cancellation request')
                return {**ack, 'status': 'ALREADY_REQUESTED'}
            descriptor = os.pidfd_open(supervisor['pid'], 0)
            try:
                require(self.execution_transport().supervisor_start(supervisor['pid']) == supervisor['startTicks'],
                        'Cutover supervisor PID was reused')
                self.common.write_json(path, request)
                signal.pidfd_send_signal(descriptor, signal.SIGTERM)
            finally:
                os.close(descriptor)
        return {**ack, 'status': 'SIGNAL_SENT'}

    def observe_execution(self):
        """Wait for the original finally, never resume an unknown migration."""
        if not self.execution_path().exists():
            expected = {**self.execution_context(), 'supervisor': None, 'requestedSignal': 'SIGTERM'}
            require(self.journal is None and self.guard.read_private(self.source / 'work/cutover-cancel-request.json')[0] == expected,
                    'Missing original cutover execution and cancellation')
            return {**self.execution_context(), 'terminal': True, 'phase': 'NOT_STARTED'}
        deadline = time.monotonic() + 180
        while True:
            value = self.read_execution()
            if value['terminal']:
                try:
                    with self.ops.maintenance_lock(self.root):
                        return value
                except self.ops.MaintenanceBusy:
                    require(time.monotonic() < deadline, 'Terminal cutover has not released maintenance ownership')
                    time.sleep(0.5)
                    continue
            require(self.execution_transport().supervisor_start(value['supervisor']['pid']) == value['supervisor']['startTicks'],
                    'Cutover owner disappeared without terminal evidence')
            require(time.monotonic() < deadline, 'Cutover still owns maintenance; retain resources and do not settle concurrently')
            time.sleep(0.5)

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
            if service in ('mysql', 'redis', 'kafka', 'kafka-init', 'kafka-storage-init'):
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
        for catalog in ('TABLE_PRIVILEGES', 'COLUMN_PRIVILEGES'):
            require(self.sql('SELECT COUNT(*) FROM information_schema.' + catalog + ' WHERE ' + identity
                             + " AND (TABLE_SCHEMA<>DATABASE() OR IS_GRANTABLE='YES');") == '0',
                    'Source runtime cannot use cross-schema or delegating table/column grants')
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
        for name in ('compose.monolith.yml', 'deploy/compose/compose.cloud.yml', 'deploy/compose/compose.detection.yml'):
            command += ['-f', str(self.source / name)]
        if (self.runtime / 'deploy/ai-gateway.enabled').is_file():
            command += ['-f', str(self.source / 'deploy/compose/compose.ai-gateway.yml')]
        secret = module('cutover_model_secrets', self.source / 'script/docker/model-secrets.py')
        setting = secret.load_settings(self.root, self.runtime)
        environment = dict(os.environ, DOORHANDLE_ENV_FILE=str(self.envfile),
                           DETECTION_BUILD_CONTEXT=str(self.runtime / 'work/cloud/pth-worker-build'),
                           QDRANT_IMAGE=self.images['qdrant'])
        if setting:
            environment['MODEL_CONFIG_MASTER_KEY_SOURCE'] = setting['masterKeyFile']
            command += ['-f', str(self.source / 'deploy/compose/compose.model-config.yml')]
        command += ['-f', str(self.work / 'candidate-images.json')]
        for path in overlays:
            command += ['-f', str(path)]
        native = self.state / 'native-data.override.json'
        if native.exists():
            memory = module('cutover_native_binding', self.source / 'script/docker/memory-compat.py')
            memory.validate_native_state(self.state, allow_pending=True)
            command += ['-f', str(native)]
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
            # Persist unknown-before-spawn, so an interrupt between child
            # creation and registration cannot authorize restoration.
            self.journal['migrationChild'] = {'operation': mode, 'drained': False}
            self.persist()
            process = descriptor = None
            owner = self.journal['migrationChild']
            try:
                self._migration_spawn_in_progress = True
                try:
                    process = subprocess.Popen(command, cwd=self.source, env=env, stdout=stream,
                                               stderr=subprocess.STDOUT, start_new_session=True)
                    descriptor = os.pidfd_open(process.pid, 0)
                    owner.update(pid=process.pid, startTicks=self.execution_transport().supervisor_start(process.pid))
                    self.persist()
                finally:
                    self._migration_spawn_in_progress = False
                self.check_cancellation()
                deadline = time.monotonic() + 14400
                while process.poll() is None:
                    self.check_cancellation()
                    require(time.monotonic() < deadline, 'Owned migration command timed out')
                    time.sleep(0.25)
                self.check_cancellation()
            except BaseException:
                # SIGINT lets the Python migration contexts close transactions,
                # source-lock helpers and the Java bridge. Never signal MySQL.
                for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                    signal.signal(signum, signal.SIG_IGN)
                if process is None:
                    raise
                if process.poll() is None:
                    require(descriptor is not None and self.execution_transport().supervisor_start(process.pid) == owner.get('startTicks')
                            and os.getpgid(process.pid) == process.pid, 'Migration command ownership changed')
                    os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    raise ValueError('Migration child has not drained; preserve maintenance and inspect its original log')
                raise
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                # A dead wrapper is insufficient: a Java/client process in the
                # original session, or a SQL session, still blocks recovery.
                owner['drained'] = (process is not None and process.poll() is not None
                                    and not self.migration_group_members(process.pid))
                self.persist()
        require(owner['drained'] and self.migration_sessions_drained(), 'Migration children or SQL sessions remain; preserve maintenance')
        require(process.returncode == 0, 'Migration/readback failed or has an unknown result; keep every source writer stopped')
        return output

    @staticmethod
    def migration_group_members(group):
        members = []
        for path in Path('/proc').iterdir():
            if not path.name.isdigit():
                continue
            try:
                fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
            except FileNotFoundError:
                continue
            if fields[0] != 'Z' and int(fields[2]) == group:
                members.append(int(path.name))
        return members

    def migration_sessions_drained(self):
        user = self.journal.get('migrationUser')
        if not user:
            return not self.journal.get('migrationStarted')
        require(re.fullmatch(r'mig_[a-f0-9]{10}', user), 'Migration SQL identity differs')
        return self.sql("SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE USER='" + user
                        + "' AND ID<>CONNECTION_ID();") == '0'

    def legacy_kafka_only_worker(self, row):
        if row['Image'] != LEGACY_KAFKA_ONLY_IMAGE:
            return False
        images = json.loads(self.ops.docker('image', 'inspect', row['Image']))
        require(len(images) == 1 and images[0]['Id'] == row['Image'], 'Historical worker image identity differs')
        config, original = row['Config'], images[0]['Config']
        command = original.get('Cmd') or []
        require(not original.get('Entrypoint') and not config.get('Entrypoint')
                and config.get('Cmd') == command and config.get('WorkingDir') == original.get('WorkingDir') == '/app'
                and command in (['python', '/app/kafka_detection_worker.py'], ['python3', '/app/kafka_detection_worker.py'],
                                ['/usr/local/bin/python', '/app/kafka_detection_worker.py'])
                and [row.get('Path'), *row.get('Args', [])] == command,
                'Historical worker no longer runs its reviewed Kafka-only entry point')
        code = {'/app/' + name for name in ('kafka_detection_worker.py', 'kafka_settings.py', 'kafka_event_models.py',
                'oss_result_uploader.py', 'pth_detection_engine.py', 'detection_image.py', 'worker_health.py')}
        require(not any(mount.get('Destination') in ('/', '/app') or mount.get('Destination') in code
                        for mount in row.get('Mounts', [])),
                'Historical worker code can be overridden by a mount')
        changes = self.ops.docker('diff', row['Id']).decode().splitlines()
        require(all(len(line) >= 3 and line[1] == ' ' and line[2:] not in ('/', '/app')
                    and line[2:] not in code for line in changes),
                'Historical worker image code has changed in its writable layer')
        return True

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
            'releaseApprovalSha256': getattr(self, 'release_approval_sha', None),
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
                if service == 'detection-worker' and not username and self.legacy_kafka_only_worker(row):
                    self.journal['legacyKafkaOnlyWorker'] = {'containerId': row['Id'], 'imageId': row['Image'],
                                                           'sqlWriter': False, 'mustStop': True}
                else:
                    require(isinstance(username, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', username)
                            and username.lower() != 'root', 'Source runtime must use explicitly fenceable non-root accounts')
                    users.add(username)
            if service in ('mysql', 'redis', 'kafka', 'kafka-init', 'kafka-storage-init'):
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
        native = module('cutover_native_installer', self.source / 'script/jenkins/prepare-legacy-candidate.py')
        native.prepare_production_native(self)
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
        native_receipt = canonical(self.journal['nativeProductionInstall']['file'])
        require(sha_file(native_receipt) == self.journal['nativeProductionInstall']['sha256'], 'Native production install receipt changed')
        action = memory.prepare(self.state, effective, native_transition=native_receipt)
        overlays.append(self.state / 'memory-activation-images.yml')
        # The new remote vector store must be healthy before the bridge starts.
        self.compose('up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '120',
                     'qdrant', overlays=overlays)
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
        native = module('cutover_native_readback', self.source / 'script/jenkins/prepare-legacy-candidate.py')
        native.verify_production_native(self)
        memory.validate_native_state(self.state, self.config(overlays))
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
        require(self.journal.get('migrationChild', {}).get('drained', True)
                and self.migration_sessions_drained(), 'Migration execution is not drained; source recovery is not approved')
        observed = self.work / 'observation/source-observation.json'
        settings_path = self.work / 'migration.json'
        settings = self.guard.read_private(settings_path)[0] if settings_path.exists() else {}
        registered = settings.get('reviewedSourceSnapshot')
        if self.journal.get('migrationStarted') or registered:
            require(registered == str(observed) and observed.is_file()
                    and sha_file(observed) == settings.get('reviewedSourceSnapshotSha256'),
                    'Registered source observation is missing or changed; source recovery is not approved')
        if observed.exists():
            # Recovering the original source requires an actual fresh full row /
            # metadata/HWM comparison, not the absence of external HTTP traffic.
            sys.path.insert(0, str(self.source / 'script/schema'))
            runtime = module('cutover_recovery_runtime', self.source / 'script/schema/compact_migration_runtime.py')
            require(settings, 'Source recovery requires its original private migration configuration')
            folder = self.work / ('recovery-readback-' + uuid.uuid4().hex[:10])
            folder.mkdir(mode=0o700); (folder / 'private').mkdir(mode=0o700)
            mysql = runtime.Mysql(settings, folder)
            model = json.loads((self.source / 'docs/database/compact-schema-contract.json').read_text())
            expected, _ = self.guard.read_private(observed)
            with mysql.source_lock(settings['sourceSchema'], model['sourceTables']):
                actual = runtime.schema_snapshot(mysql, settings['sourceSchema'], model['sourceTables'])
                require(actual['snapshotSha256'] == expected['sourceSnapshotSha256'], 'The old source changed; source recovery is not approved')
        for file in ('compact-connection.override.yml', 'compact-connection.json', 'native-data.override.json', 'native-data.json'):
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

    def fence_target_accounts(self):
        """Close only this migration's new DML identities after target activation."""
        accounts, _ = self.guard.read_private(self.work / 'runtime-accounts.json')
        suffix = self.work.name.rsplit('-', 1)[1]
        require(re.fullmatch(r'[a-f0-9]{10}', suffix) and set(accounts) == {'app', 'worker'},
                'Target writer identities differ from the original migration')
        users = []
        for role in ('app', 'worker'):
            expected = role + '_' + suffix
            require(accounts[role].get('user') == expected, 'Target writer is not owned by this migration')
            users.append(expected)
        for user in users:
            self.sql("ALTER USER '" + user + "'@'%' ACCOUNT LOCK;")
        names = ','.join("'" + user + "'" for user in users)
        return (self.sql("SELECT COUNT(*) FROM mysql.user WHERE User IN (" + names + ") AND Host='%' AND account_locked='Y';") == '2'
                and self.sql("SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE (DB='"
                    + self.journal['targetSchema'] + "' OR USER IN (" + names + ")) AND ID<>CONNECTION_ID();") == '0')

    def fail_closed(self, action):
        if not self.journal:
            return
        # prepare may fail halfway through stopping the source; recover may fail
        # after restarting only some originals. Both need the same real freeze
        # as a partially started target. One failed stop cannot skip the rest.
        exempt = {'mysql', 'redis', 'kafka', 'kafka-init', 'kafka-storage-init'}
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
        target_fence_ok = self.journal.get('activationStarted') is False
        if self.journal.get('activationStarted') is True:
            try:
                target_fence_ok = self.fence_target_accounts()
            except BaseException:
                target_fence_ok = False
        try:
            migration_drained = (self.journal.get('migrationChild', {}).get('drained', True)
                                 and self.migration_sessions_drained())
        except BaseException:
            migration_drained = False
        confirmed = inventory_ok and not unresolved and account_fence_ok and target_fence_ok and migration_drained
        self.journal['failureFreeze'] = {'action': action, 'confirmed': confirmed,
                                         'sourceAccountsFenced': account_fence_ok,
                                         'targetAccountsFenced': target_fence_ok,
                                         'migrationExecutionDrained': migration_drained,
                                         'unverifiedContainers': sorted(unresolved)}
        phase = 'FAILED_' + action.upper() + ('_FROZEN' if confirmed else '_NEEDS_REVIEW')
        self.persist(phase)
        if (self.state / 'compact-connection.override.yml').exists():
            self.connection(phase)

    def summary(self):
        journal = self.journal or {}
        native_ref = journal.get('nativeProductionReadback')
        if native_ref:
            require(sha_file(canonical(native_ref['file'])) == native_ref['sha256'], 'Native production readback changed')
        return {'kind': 'doorhandle-first-compact-cutover', 'phase': journal.get('phase', 'NOT_STARTED'),
                'status': 'ACTIVE' if journal.get('phase') == 'ACTIVE' else 'STOPPED_OR_PRIVATE',
                'sourceTableCount': 131, 'targetTableCount': 29,
                'release': self.args.tag, 'commit': self.input['gitCommit'],
                'sourceSha256': self.args.source_sha256, 'ecs': self.identity,
                'migrationReceiptSha256': journal.get('migrationReceiptSha256'),
                'candidateSemanticVerified': bool(journal.get('nativeProductionInstall')),
                'productionDataMaterialized': bool(native_ref), 'nativeProductionReadback': native_ref,
                'sourceRestorationAllowed': may_restore_source(journal),
                'activationStarted': journal.get('activationStarted'),
                'failureFreeze': journal.get('failureFreeze'), 'recovery': journal.get('recovery')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    if len(sys.argv) > 1 and sys.argv[1] == 'authorize':
        parser.add_argument('phase', choices=('authorize',))
        for name in ('authorization', 'request', 'runtime-gate', 'runtime-proof', 'manual-decision'):
            parser.add_argument('--' + name, required=True)
        return authorize_files(parser.parse_args())
    parser.add_argument('phase', choices=('prepare', 'migrate', 'activate', 'recover', 'status', 'run', 'settle', 'cancel', 'observe'))
    for name in ('root', 'runtime', 'tag', 'source-sha256', 'config'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--lock-fd', type=int)
    parser.add_argument('--approval')
    args = parser.parse_args()
    instance = None
    try:
        instance = Cutover(args)
        if args.phase in ('cancel', 'observe'):
            # Cancellation must not wait for the lock held by the process it
            # needs to interrupt. Only original execution metadata is mutated.
            require(args.approval, 'Controlled cancellation requires its original approval')
            instance.admit_release()
            value = instance.cancel() if args.phase == 'cancel' else instance.observe_execution()
            print(json.dumps(value)); return 0
        with instance.ops.maintenance_lock(instance.root, args.lock_fd):
            instance.refresh_journal()
            try:
                if args.phase in ('run', 'settle'):
                    require(args.approval, 'Controlled release requires its original approval')
                    def interrupted(_signal, _frame):
                        if getattr(instance, '_migration_spawn_in_progress', False):
                            instance._cancelled_during_spawn = True
                            return
                        raise KeyboardInterrupt('Controlled cutover interrupted')
                    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                        signal.signal(signum, interrupted)
                    if args.phase == 'run':
                        instance.run_release()
                    else:
                        instance.admit_release()
                        outcome = instance.settle()
                        print(json.dumps(instance.summary()))
                        return 2 if outcome['status'] == 'COMPACT_FORWARD_REQUIRED' else 0
                elif args.phase != 'status':
                    getattr(instance, args.phase)()
            except BaseException:
                if args.phase not in ('status', 'run', 'settle'):
                    instance.fail_closed(args.phase)
                raise
            print(json.dumps(instance.summary()))
        return 0
    except BaseException:
        print('Compact cutover did not complete. Preserve private evidence and inspect the freeze/NEEDS_REVIEW phase before recovery.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
