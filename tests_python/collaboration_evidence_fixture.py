"""Synthetic public receipt fixture; never a real ECS acceptance result."""
import hashlib
import json
from pathlib import Path
from tests_python.browser_evidence_fixture import report_value


def write(path, value):
    path.write_bytes((json.dumps(value, sort_keys=True, indent=2) + '\n').encode()); path.chmod(0o600)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(directory, context, project, proof, cleanup, accounts=None):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    accounts = accounts or report_value(context)['accounts']
    def sha(value): return hashlib.sha256(value.encode()).hexdigest()
    common = {**context, 'kind': 'doorhandle-runtime-stable-identity', 'runtimeKind': context['kind'],
        'projectSha256': sha(project), 'targetSchemaSha256': sha('synthetic-owned-target'),
        'migrationReceiptSha256': proof['migrationReceiptSha256'], 'initialTargetSnapshotSha256': proof['initialTargetSnapshotSha256'],
        'mappingAppliedByRunner': False, 'directSqlModeChanges': False, 'legacyModeAccepted': False, 'historicalNamesInPublicEvidence': False}
    before = {'serverUuid': proof['actualServerUuid'], 'tasks': 3, 'bindingMode': 'PREVIEW', 'sourceMode': 'COLLECTING',
        'bindingRevision': '1', 'sourceActivationRevision': None}
    after = {**before, 'bindingMode': 'ACTIVE', 'sourceMode': 'ACTIVE', 'bindingRevision': '2', 'sourceActivationRevision': '2'}
    preview = {'tasks': 3, 'gapCount': 0, 'bindingMode': 'PREVIEW', 'sourceMode': 'COLLECTING', 'bindingRevision': '1'}
    flags = {key: True for key in ('DETECTION_STABLE_IDENTITY_ENABLED', 'DETECTION_ASSIGNMENT_BINDING_ENABLED',
        'DETECTION_IDENTITY_REVIEW_ENABLED', 'DETECTION_IDENTITY_EVIDENCE_ENABLED', 'DETECTION_IDENTITY_MISSING_NAME_REVIEW_ENABLED')}
    preflight = {**common, 'stage': 'preflight', 'status': 'PREFLIGHT_ONLY', 'database': before}
    admission = {**common, 'stage': 'admission', 'status': 'PASS', 'databaseBefore': before, 'databaseAfter': after,
        'actualFlags': flags, 'historicalPreview': preview,
        'activatedPreview': {**preview, 'bindingMode': 'ACTIVE', 'sourceMode': 'ACTIVE', 'bindingRevision': '2'},
        'activation': {'openedRevision': '1', 'httpStatus': 200, 'actualSupervisorUserId': accounts['supervisor']['userId'],
            'sourceProtection': True, 'postReadbackConfirmed': True}}
    task = 'owned-worker-task'
    authorization = {**common, 'stage': 'authorization', 'status': 'PASS', 'database': {**after, 'tasks': 4}, 'actualFlags': flags,
        'taskBinding': {'taskIdSha256': sha(task), 'sourceKind': 'NEW_CREATION', 'sourceRecorded': True,
            'dbAndHttpCreatorMatched': True, 'createdUserId': accounts['supervisor']['userId'], 'assigneeUserId': accounts['inspector']['userId'], 'version': '4'},
        'httpPermissions': [{'account': alias, 'userId': accounts[alias]['userId'], 'role': accounts[alias]['role'],
            'progressHttpStatus': 403 if alias == 'peer' else 200, 'traceHttpStatus': 404 if alias == 'peer' else 200,
            'historyHttpStatus': 200, 'historyVisibleItems': 0 if alias == 'peer' else 2}
            for alias in ('inspector', 'peer', 'supervisor', 'reviewer')]}
    claim = {'taskId': task, 'createdUserId': accounts['supervisor']['userId'],
        'competingUserIds': [accounts[alias]['userId'] for alias in ('inspector', 'peer')],
        'winnerUserId': accounts['peer']['userId'], 'loserStatus': 409, 'committedVersion': '3', 'auditId': '81',
        'candidateReadHttpStatuses': [200, 200], 'candidateWriteHttpStatuses': [403, 403], 'loserReadHttpStatuses': [403, 404, 403],
        'committedAuditCount': 1, 'committedCommandCount': 1, 'auditActorUserId': accounts['peer']['userId'],
        'stableAssigneeUserId': accounts['peer']['userId'], 'receiptResourceVersion': '3', 'receiptAuditId': '81',
        'receiptEventId': 'actual-event-81', 'requestId': 'actual-command-81', 'restoredAssignmentVersion': '4'}
    claim.update({key: True for key in ('exactResponseAndReceiptReplay', 'temporaryScopeRevoked', 'candidateOtherWritesDenied',
        'continuedThroughRealSupervisorAssignment', 'auditRequestIdMatched', 'candidateIdsCleared')})
    personnel = {'oldBusinessDataModified': False, 'positions': []}
    for index, (position, alias) in enumerate((('COLLECTION', 'inspector'), ('MAINTENANCE', 'peer')), 1):
        personnel['positions'].append({'position': position, 'userId': accounts[alias]['userId'], 'staffId': str(500 + index),
            'createdAndAssociatedThroughActualHttp': True, 'oldSessionRevokedAndNotResurrected': True,
            'exactOldCookieReplay': True, 'qualifiedNewSessionVerified': True,
            'loginRejected': 403, 'freshQualifiedHttpStatus': 200, 'oldSessionHttpStatuses': [401, 401],
            'beforeBindingVersion': '0', 'withdrawnBindingVersion': '1', 'restoredBindingVersion': '2',
            'freshQualifiedEmployeeId': str(600 + index), 'originalEmployeeId': str(600 + index)})
    cleanup['stableIdentityEvidence'] = {}; cleanup['collaborationHttpEvidence'] = {}
    for stage, value in zip(('preflight', 'admission', 'authorization'), (preflight, admission, authorization)):
        name = 'stable-identity-' + stage + '.json'
        cleanup['stableIdentityEvidence'][stage] = {'file': 'checkout/work/runtime-acceptance/' + name,
            'sha256': write(directory / name, value), 'status': value['status']}
    for stage, observations in (('claim', claim), ('personnel', personnel)):
        name = 'collaboration-http-' + stage + '.json'
        cleanup['collaborationHttpEvidence'][stage] = {'file': 'checkout/work/runtime-acceptance/' + name,
            'sha256': write(directory / name, {**context, 'project': project, 'status': 'PASS', 'observations': observations})}
    proof['stableIdentity'] = {'status': 'PASS', 'admission': cleanup['stableIdentityEvidence']['admission'],
        'authorization': cleanup['stableIdentityEvidence']['authorization'], 'legacyModeAccepted': False}
    proof['collaborationHttpAcceptance'] = cleanup['collaborationHttpEvidence']
    return cleanup
