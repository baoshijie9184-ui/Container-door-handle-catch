#!/usr/bin/env python3
"""Required stable-identity admission for the existing owned full ECS runtime.

Only the original HTTP activation endpoint may change identity mode. Suggested
accounts are never mappings, and unknown historical ownership blocks admission.
Transport/DB responses stay private; public evidence contains fixed states,
counts, hashes, and owned actor IDs/roles only. No service/cloud lifecycle here.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import uuid


REQUIRED_ENV = {name: 'true' for name in (
    'DETECTION_STABLE_IDENTITY_ENABLED', 'DETECTION_ASSIGNMENT_BINDING_ENABLED',
    'DETECTION_IDENTITY_REVIEW_ENABLED', 'DETECTION_IDENTITY_EVIDENCE_ENABLED',
    'DETECTION_IDENTITY_MISSING_NAME_REVIEW_ENABLED')}
ROLES = frozenset(('created', 'assignee', 'reviewer', 'disposition', 'rework'))
CRITICAL = frozenset(('created', 'assignee'))
STATES = frozenset(('ALREADY_ALIGNED', 'MISSING_NAME_CONFIRMED', 'ORIGINAL_ACCOUNT_UNAVAILABLE',
    'MISSING_NAME', 'SOURCE_UNVERIFIED', 'UNMATCHED', 'DIFFERENT_CURRENT_ACCOUNT', 'CANDIDATE_ONLY'))
SOURCE_STATES = frozenset(('SOURCE_RECORDED', 'SOURCE_UNVERIFIED', 'SOURCE_MISMATCH', 'SOURCE_INVALID'))
MAX_TASKS, PAGE_SIZE, MAX_GAPS, MAX_RESPONSE_BYTES = 20000, 100, 32, 2 * 1024 * 1024
FILES = {'preflight': 'stable-identity-preflight.json', 'admission': 'stable-identity-admission.json',
         'authorization': 'stable-identity-authorization.json'}


class StableIdentityBlocked(RuntimeError):
    """Controlled reason only; never a raw HTTP body, credential or legacy name."""


def need(condition, reason):
    if not condition:
        raise StableIdentityBlocked(reason)


def integer(value, minimum=0):
    need(type(value) is int or isinstance(value, str) and re.fullmatch(r'0|[1-9][0-9]{0,18}', value), 'IDENTITY_INTEGER_INVALID')
    value = int(value)
    need(minimum <= value <= 9223372036854775807, 'IDENTITY_INTEGER_RANGE_INVALID')
    return value


def digest(value):
    return hashlib.sha256(str(value).encode('utf-8')).hexdigest()


def enable_required_environment(config):
    """Return an isolated candidate config; never rewrite a production env file."""
    value = copy.deepcopy(config)
    need(isinstance(value.get('services', {}).get('backend', {}).get('environment'), dict), 'CANDIDATE_BACKEND_ENV_REQUIRED')
    value['services']['backend']['environment'].update(REQUIRED_ENV)
    return value


def _base(ctx, stage):
    context = ctx.context()
    need(re.fullmatch(r'[a-f0-9]{40}', context.get('commit', '')) is not None
         and re.fullmatch(r'[a-f0-9]{64}', context.get('sourceSha256', '')) is not None,
         'FIXED_RUNTIME_SOURCE_REQUIRED')
    need(all(re.fullmatch(r'[a-f0-9]{64}', ctx.owner.get(key, '')) for key in
             ('migrationReceiptSha256', 'initialTargetSnapshotSha256')), 'COMPLETE_MIGRATION_RECEIPTS_REQUIRED')
    return {**context, 'kind': 'doorhandle-runtime-stable-identity', 'stage': stage, 'status': 'BLOCKED',
        'runtimeKind': context.get('kind'),
        'projectSha256': digest(ctx.project), 'targetSchemaSha256': digest(ctx.owner['targetSchema']),
        'migrationReceiptSha256': ctx.owner['migrationReceiptSha256'],
        'initialTargetSnapshotSha256': ctx.owner['initialTargetSnapshotSha256'],
        'mappingAppliedByRunner': False, 'directSqlModeChanges': False,
        'legacyModeAccepted': False, 'historicalNamesInPublicEvidence': False}


def _save(ctx, stage, value):
    directory = Path(ctx.directory).resolve()
    need(directory.is_relative_to(Path(ctx.attempt).resolve()), 'OWNED_EVIDENCE_DIRECTORY_REQUIRED')
    path = directory / FILES[stage]
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    need(len(encoded) <= 256 * 1024, 'IDENTITY_EVIDENCE_BOUND_EXCEEDED')
    # Values are selected above, rather than redacting an arbitrary server body.
    # Account names and the ownership token are deliberately absent even on error.
    private = {str(item.get('username', '')) for item in ctx.accounts.values()}
    private.add(str(getattr(ctx, 'token', '')))
    text = encoded.decode('utf-8')
    need(not any(len(secret) >= 8 and secret in text for secret in private), 'PRIVATE_IDENTITY_EVIDENCE_REJECTED')
    ctx.common.write_json(path, value)
    receipt = {'status': value['status'], 'file': path.relative_to(Path(ctx.attempt).resolve()).as_posix(),
               'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    ctx.owner['stableIdentity' + stage.title()] = receipt
    ctx.save()
    return receipt


def _blocked(ctx, stage, value, error):
    value['status'] = 'BLOCKED'
    value['reason'] = str(error) if isinstance(error, StableIdentityBlocked) else 'IDENTITY_PREREQUISITE_UNAVAILABLE'
    value['errorType'] = type(error).__name__
    _save(ctx, stage, value)
    raise StableIdentityBlocked(value['reason']) from None


def _database(ctx):
    observed = ctx.db.one("SELECT JSON_OBJECT('schema',DATABASE(),'serverUuid',@@server_uuid,'tableCount',"
        "(SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE'));" )
    need(observed['schema'] == ctx.owner['targetSchema'] and observed['serverUuid'] == ctx.owner['serverUuid']
         and integer(observed['tableCount']) == 29, 'OWNED_MIGRATED_TARGET_IDENTITY_MISMATCH')
    controls = ctx.db.query("SELECT JSON_OBJECT('namespace',namespace,'mode',state_code,'revision',revision,"
        "'payloadVersion',payload_version,'controlId',JSON_EXTRACT(payload_json,'$.controlId'),"
        "'activationRevision',JSON_EXTRACT(payload_json,'$.activationRevision')) FROM runtime_state "
        "WHERE owner_id=0 AND scope_key='1' AND namespace IN ('DETECTION_IDENTITY_CONTROL','DETECTION_IDENTITY_SOURCE_CONTROL');")
    need(len(controls) == 2 and len({item['namespace'] for item in controls}) == 2, 'IDENTITY_CONTROL_ABSENT_OR_AMBIGUOUS')
    indexed = {item['namespace']: item for item in controls}
    need(set(indexed) == {'DETECTION_IDENTITY_CONTROL', 'DETECTION_IDENTITY_SOURCE_CONTROL'}, 'IDENTITY_CONTROL_NAMESPACE_INVALID')
    for item in controls:
        need(integer(item['payloadVersion']) == 1 and integer(item['controlId']) == 1, 'IDENTITY_CONTROL_PAYLOAD_INVALID')
        integer(item['revision'])
    binding, source = indexed['DETECTION_IDENTITY_CONTROL'], indexed['DETECTION_IDENTITY_SOURCE_CONTROL']
    need(binding['mode'] in ('PREVIEW', 'ACTIVE') and source['mode'] in ('COLLECTING', 'ACTIVE'), 'IDENTITY_CONTROL_MODE_INVALID')
    need(not (source['mode'] == 'ACTIVE' and binding['mode'] != 'ACTIVE'), 'IDENTITY_CONTROL_MODES_INCONSISTENT')
    counts = ctx.db.one("SELECT JSON_OBJECT('tasks',COUNT(*),'createdIdMissing',COALESCE(SUM(created_user_id IS NULL),0),"
        "'assigneeIdMissing',COALESCE(SUM((COALESCE(assignee,'')<>'' OR assignee_identity_name IS NOT NULL) AND assignee_user_id IS NULL),0)) FROM detection_task;")
    count = integer(counts['tasks'])
    return {'serverUuid': observed['serverUuid'], 'tasks': count,
            'createdIdMissing': integer(counts['createdIdMissing']), 'assigneeIdMissing': integer(counts['assigneeIdMissing']),
            'bindingMode': binding['mode'], 'bindingRevision': str(integer(binding['revision'])),
            'sourceMode': source['mode'], 'sourceRevision': str(integer(source['revision'])),
            'sourceActivationRevision': None if source['activationRevision'] is None else str(integer(source['activationRevision']))}


def preflight(ctx):
    """Before dc up: preserve missing-control evidence, without treating it as admission."""
    value = _base(ctx, 'preflight')
    try:
        value['database'] = _database(ctx)
        need(value['database']['tasks'] <= MAX_TASKS, 'HISTORICAL_IDENTITY_SCAN_BOUND_EXCEEDED')
        value['status'] = 'PREFLIGHT_ONLY'
        return _save(ctx, 'preflight', value)
    except Exception as error:
        return _blocked(ctx, 'preflight', value, error)


def _actual_flags(ctx):
    env = ctx.common.environment(ctx.row('backend'))
    result = {key: str(env.get(key, '')).strip().lower() == 'true' for key in REQUIRED_ENV}
    need(all(result.values()), 'ACTUAL_STABLE_IDENTITY_FLAGS_REQUIRED')
    return result


def _http(ctx, account, method, path, body=None, denied=()):
    client = ctx.client(account)
    need(re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]*', client.base) is not None, 'OWNED_HTTP_LOOPBACK_REQUIRED')
    headers = {'Cache-Control': 'no-cache'}
    if path.startswith('/api/detection/identity/'):
        headers['X-Identity-Action'] = 'update'
    if path != '/api/auth/check' and client.account_context:
        headers['X-Account-Context'] = client.account_context
    request = client.prepare_request(method, path, body, headers=headers)
    try:
        response = client.opener.open(request, timeout=30)
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        need(status in denied, 'IDENTITY_HTTP_STATUS_UNEXPECTED')
        return status, None
    with response:
        need(not denied and response.status == 200, 'IDENTITY_HTTP_PERMISSION_PROOF_INVALID')
        need('application/json' in response.headers.get('Content-Type', ''), 'IDENTITY_HTTP_JSON_REQUIRED')
        if path.startswith('/api/detection/identity/'):
            need('no-store' in response.headers.get('Cache-Control', ''), 'IDENTITY_PREVIEW_MUST_BE_PRIVATE')
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        need(len(raw) <= MAX_RESPONSE_BYTES, 'IDENTITY_HTTP_BODY_BOUND_EXCEEDED')
        value = json.loads(raw)
        if isinstance(value, dict) and 'code' in value:
            need(value['code'] == 200, 'IDENTITY_HTTP_BUSINESS_REJECTED')
            value = value.get('data')
        return response.status, client.observe_auth(path, value)


def _healthy_critical(row):
    source = row.get('source') or {}
    original = row.get('existingUserId')
    return row.get('state') in ('ALREADY_ALIGNED', 'MISSING_NAME_CONFIRMED') and source.get('state') == 'SOURCE_RECORDED' \
        and original is not None and integer(original, 1) == integer(source.get('bound_user_id'), 1) \
        and source.get('bound_identity_name') == row.get('expectedName')


def _scan(ctx):
    after, tasks, keys = '', set(), set()
    summary = {'pages': 0, 'tasks': 0, 'criticalBindings': 0, 'gapCount': 0,
               'nonAuthorizationRoleGapCount': 0, 'gaps': [], 'maximumPublishedGaps': MAX_GAPS}
    signature = None
    for _page in range(MAX_TASKS // PAGE_SIZE + 1):
        _, value = _http(ctx, 'supervisor', 'GET', '/api/detection/identity/preview?' +
                         urllib.parse.urlencode({'after': after, 'size': PAGE_SIZE, 'includeAligned': 'true'}))
        need(isinstance(value, dict) and value.get('protocol') == 'identity-map-v2' and value.get('reviewEnabled') is True
             and value.get('sourceEvidenceEnabled') is True and value.get('missingNameReviewEnabled') is True
             and isinstance(value.get('records'), list) and type(value.get('hasMore')) is bool, 'AUTHORITATIVE_IDENTITY_PREVIEW_REQUIRED')
        observed = (value.get('mode'), str(integer(value.get('revision'))), value.get('sourceMode'))
        need(observed[0] in ('ACTIVE', 'PREVIEW') and observed[2] in ('ACTIVE', 'COLLECTING'), 'IDENTITY_PREVIEW_MODE_INVALID')
        if signature is None:
            signature = observed
        need(signature == observed, 'IDENTITY_PREVIEW_REVISION_CHANGED')
        need(len(value['records']) <= PAGE_SIZE * len(ROLES), 'IDENTITY_PREVIEW_PAGE_BOUND_EXCEEDED')
        for row in value['records']:
            need(isinstance(row, dict) and isinstance(row.get('taskId'), str)
                 and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', row['taskId']) is not None
                 and row.get('role') in ROLES and row.get('state') in STATES, 'IDENTITY_PREVIEW_RECORD_INVALID')
            key = (row['taskId'], row['role'])
            need(key not in keys, 'IDENTITY_PREVIEW_REPEATED_RECORD')
            keys.add(key); tasks.add(row['taskId'])
            if row['role'] in CRITICAL:
                if _healthy_critical(row):
                    summary['criticalBindings'] += 1
                else:
                    summary['gapCount'] += 1
                    if len(summary['gaps']) < MAX_GAPS:
                        state = (row.get('source') or {}).get('state')
                        summary['gaps'].append({'taskIdSha256': digest(row['taskId']), 'role': row['role'],
                            'state': row['state'], 'sourceState': state if state in SOURCE_STATES else 'UNRECOGNIZED'})
            elif row['state'] not in ('ALREADY_ALIGNED', 'MISSING_NAME_CONFIRMED'):
                summary['nonAuthorizationRoleGapCount'] += 1
        summary['pages'] += 1
        cursor = value.get('nextCursor')
        need(isinstance(cursor, str) and len(cursor) <= 128, 'IDENTITY_PREVIEW_CURSOR_INVALID')
        if not value['hasMore']:
            summary.update(tasks=len(tasks), bindingMode=signature[0], bindingRevision=signature[1], sourceMode=signature[2])
            return summary
        need(cursor and cursor != after, 'IDENTITY_PREVIEW_CURSOR_DID_NOT_ADVANCE')
        after = cursor
    raise StableIdentityBlocked('HISTORICAL_IDENTITY_SCAN_BOUND_EXCEEDED')


def _read_receipt(ctx, stage, expected_status):
    reference = ctx.owner.get('stableIdentity' + stage.title(), {})
    path = Path(ctx.attempt).resolve() / reference.get('file', '')
    need(reference.get('status') == expected_status and path.resolve() == Path(ctx.directory).resolve() / FILES[stage]
         and path.is_file() and not path.is_symlink() and path.stat().st_size <= 256 * 1024, 'STABLE_IDENTITY_RECEIPT_REQUIRED')
    raw = path.read_bytes()
    need(hashlib.sha256(raw).hexdigest() == reference.get('sha256'), 'STABLE_IDENTITY_RECEIPT_DIGEST_MISMATCH')
    value = json.loads(raw)
    need(value.get('status') == expected_status and value.get('stage') == stage
         and value.get('runtimeKind') == ctx.context().get('kind')
         and all(value.get(key) == data for key, data in ctx.context().items() if key != 'kind'), 'STABLE_IDENTITY_RECEIPT_CONTEXT_MISMATCH')
    need(value.get('targetSchemaSha256') == digest(ctx.owner['targetSchema'])
         and value.get('mappingAppliedByRunner') is False and value.get('directSqlModeChanges') is False
         and value.get('legacyModeAccepted') is False, 'STABLE_IDENTITY_RECEIPT_SCOPE_INVALID')
    return value


def admit(ctx):
    value = _base(ctx, 'admission')
    try:
        before = _read_receipt(ctx, 'preflight', 'PREFLIGHT_ONLY')['database']
        value['actualFlags'] = _actual_flags(ctx)
        database = _database(ctx); value['databaseBefore'] = database
        need(database['serverUuid'] == before['serverUuid'] and database['tasks'] == before['tasks'], 'SOURCE_TASK_INVENTORY_CHANGED_BEFORE_ADMISSION')
        _, account = _http(ctx, 'supervisor', 'GET', '/api/auth/check')
        need(isinstance(account, dict) and str(integer(account.get('userId'), 1)) == str(integer(ctx.accounts['supervisor']['userId'], 1))
             and account.get('role') == 'SUPERVISOR', 'ACTUAL_SUPERVISOR_REQUIRED_FOR_ACTIVATION')
        scan = _scan(ctx); value['historicalPreview'] = scan
        need(scan['tasks'] == database['tasks'], 'IDENTITY_PREVIEW_DID_NOT_COVER_MIGRATED_TASKS')
        need(scan['bindingMode'] == database['bindingMode'] and scan['bindingRevision'] == database['bindingRevision']
             and scan['sourceMode'] == database['sourceMode'], 'IDENTITY_HTTP_DB_CONTROL_MISMATCH')
        need(scan['gapCount'] == 0, 'HISTORICAL_IDENTITY_REVIEW_REQUIRED')
        # No apply endpoint: existing names, suggestions and guesses are not evidence.
        request_id = 'runtime-identity-' + uuid.uuid4().hex
        need('stableIdentityActivationPending' not in ctx.owner, 'PRIOR_IDENTITY_ACTIVATION_OUTCOME_REQUIRES_REVIEW')
        ctx.owner['stableIdentityActivationPending'] = {'requestId': request_id, 'revision': scan['bindingRevision']}
        ctx.save()
        status, response = _http(ctx, 'supervisor', 'POST', '/api/detection/identity/activate',
            {'revision': integer(scan['bindingRevision']), 'requestId': request_id, 'sourceProtection': True})
        need(isinstance(response, dict) and response.get('mode') == 'ACTIVE', 'ORIGINAL_ACTIVATION_NOT_CONFIRMED')
        after = _database(ctx); value['databaseAfter'] = after
        need(after['bindingMode'] == after['sourceMode'] == 'ACTIVE' and after['tasks'] == database['tasks'], 'ACTUAL_STABLE_SOURCE_MODE_REQUIRED')
        expected = integer(scan['bindingRevision']) + (database['bindingMode'] != 'ACTIVE' or database['sourceMode'] != 'ACTIVE')
        need(integer(after['bindingRevision']) == expected, 'ACTIVATION_REVISION_READBACK_MISMATCH')
        need(after['sourceActivationRevision'] is not None and 1 <= integer(after['sourceActivationRevision']) <= expected,
             'ACTUAL_SOURCE_PROTECTION_REVISION_REQUIRED')
        if database['bindingMode'] != 'ACTIVE' or database['sourceMode'] != 'ACTIVE':
            need(integer(after['sourceActivationRevision']) == expected, 'SOURCE_PROTECTION_ACTIVATION_REVISION_MISMATCH')
        checked = _scan(ctx); value['activatedPreview'] = checked
        need(checked['bindingMode'] == checked['sourceMode'] == 'ACTIVE' and checked['gapCount'] == 0
             and checked['tasks'] == after['tasks'] and checked['bindingRevision'] == after['bindingRevision'], 'ACTIVATED_HTTP_PREVIEW_NOT_STABLE')
        value['activation'] = {'httpStatus': status, 'requestId': request_id, 'openedRevision': scan['bindingRevision'],
            'sourceProtection': True, 'actualSupervisorUserId': str(integer(account['userId'], 1)), 'postReadbackConfirmed': True}
        value['status'] = 'PASS'
        ctx.owner.pop('stableIdentityActivationPending')
        return _save(ctx, 'admission', value)
    except Exception as error:
        return _blocked(ctx, 'admission', value, error)


def prove_current_task(ctx, task_id):
    value = _base(ctx, 'authorization')
    try:
        admitted = _read_receipt(ctx, 'admission', 'PASS')
        value['actualFlags'] = _actual_flags(ctx)
        controls = _database(ctx); value['database'] = controls
        need(controls['bindingMode'] == controls['sourceMode'] == 'ACTIVE'
             and controls['tasks'] >= admitted['databaseAfter']['tasks'] + 1, 'REAL_NEW_TASK_ON_PRESERVED_STABLE_INVENTORY_REQUIRED')
        need(isinstance(task_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', task_id) is not None, 'ACTUAL_WORKER_TASK_REQUIRED')
        row = ctx.db.one("SELECT JSON_OBJECT('taskId',task_id,'createdUserId',created_user_id,'createdIdentityName',created_identity_name,"
            "'createdBy',created_by,'assigneeUserId',assignee_user_id,'assigneeIdentityName',assignee_identity_name,"
            "'assignee',assignee,'status',status,'version',version) FROM detection_task WHERE task_id=" + ctx.db.literal(task_id) + ';')
        need(row.get('taskId') == task_id and row.get('status') in ('COMPLETED', 'PARTIAL_FAILED'), 'ACTUAL_COMPLETED_TASK_ROW_REQUIRED')
        owner = ctx.accounts['supervisor']
        need(integer(row.get('createdUserId'), 1) == integer(owner['userId'], 1)
             and row.get('createdIdentityName') == row.get('createdBy') == owner['username'], 'ACTUAL_TASK_CREATOR_BINDING_MISMATCH')
        need(integer(row.get('assigneeUserId'), 1) == integer(ctx.accounts['inspector']['userId'], 1),
             'ACTUAL_TASK_ASSIGNEE_BINDING_MISMATCH')
        _, preview = _http(ctx, 'supervisor', 'GET', '/api/detection/identity/preview?' + urllib.parse.urlencode({'taskId': task_id, 'includeAligned': 'true', 'size': 1}))
        records = preview.get('records', [])
        created = [item for item in records if item.get('role') == 'created' and item.get('taskId') == task_id]
        need(preview.get('mode') == preview.get('sourceMode') == 'ACTIVE' and len(created) == 1
             and _healthy_critical(created[0]) and integer(created[0].get('existingUserId'), 1) == integer(row['createdUserId'], 1)
             and created[0].get('expectedName') == row['createdIdentityName']
             and (created[0].get('source') or {}).get('source_kind') == 'NEW_CREATION', 'ACTUAL_NEW_CREATION_SOURCE_CERTIFICATE_REQUIRED')
        route = '/api/detection/tasks/' + urllib.parse.quote(task_id, safe='')
        receipts = []
        for alias in ('inspector', 'supervisor', 'reviewer', 'peer'):
            _, checked = _http(ctx, alias, 'GET', '/api/auth/check')
            expected = ctx.accounts[alias]
            need(str(integer(checked.get('userId'), 1)) == str(integer(expected['userId'], 1)) and checked.get('role') == expected['role'], 'ACTUAL_SCOPE_ACCOUNT_IDENTITY_MISMATCH')
            denied = (403, 404) if alias == 'peer' else ()
            status, progress = _http(ctx, alias, 'GET', route, denied=denied)
            trace_status, trace = _http(ctx, alias, 'GET', route + '/trace', denied=denied)
            audit_status, audit = _http(ctx, alias, 'GET', '/api/operations/audit/changes?' + urllib.parse.urlencode({'resourceType': 'DETECTION_TASK', 'resourceId': task_id}), denied=())
            if not denied:
                need(progress.get('taskId') == trace.get('taskId') == task_id
                     and str(integer(progress.get('version'))) == str(integer(trace.get('version'))) == str(integer(row['version'])), 'ACTUAL_STABLE_TASK_VERSION_MISMATCH')
                need(isinstance(audit, dict) and isinstance(audit.get('items'), list) and any(item.get('resourceId') == task_id for item in audit['items']), 'AUTHORIZED_RESOURCE_HISTORY_REQUIRED')
            else:
                # A filtered list may truthfully be empty. It must not reveal any
                # guessed resource metadata, and HTTP detail denials stay 403/404.
                need(status in (403, 404) and trace_status in (403, 404), 'PEER_HTTP_SCOPE_MUST_BE_DENIED')
                need(isinstance(audit, dict) and audit.get('items') == [], 'PEER_RESOURCE_HISTORY_MUST_BE_EMPTY')
            receipts.append({'account': alias, 'userId': str(integer(expected['userId'], 1)), 'role': expected['role'],
                             'progressHttpStatus': status, 'traceHttpStatus': trace_status, 'historyHttpStatus': audit_status,
                             'historyVisibleItems': len(audit['items'])})
        value['taskBinding'] = {'taskIdSha256': digest(task_id), 'createdUserId': str(integer(row['createdUserId'], 1)),
            'assigneeUserId': None if row.get('assigneeUserId') is None else str(integer(row['assigneeUserId'], 1)),
            'version': str(integer(row['version'])), 'sourceKind': 'NEW_CREATION', 'sourceRecorded': True,
            'dbAndHttpCreatorMatched': True}
        value['httpPermissions'] = receipts
        value['status'] = 'PASS'
        return _save(ctx, 'authorization', value)
    except Exception as error:
        return _blocked(ctx, 'authorization', value, error)


def validate_final_values(preflight, admitted, authorization, accounts, server_uuid):
    """Pure final policy, shared with CI/cutover original-byte verification."""
    before, after = admitted['databaseBefore'], admitted['databaseAfter']
    historical, activated = admitted['historicalPreview'], admitted['activatedPreview']
    need(preflight.get('status') == 'PREFLIGHT_ONLY' and admitted.get('status') == authorization.get('status') == 'PASS', 'FINAL_REQUIRED_STAGE_STATUS_INVALID')
    need(preflight['database']['serverUuid'] == before['serverUuid'] == after['serverUuid'] == server_uuid
         and integer(preflight['database']['tasks']) == integer(before['tasks']) == integer(after['tasks'])
         == integer(historical['tasks']) == integer(activated['tasks'])
         and integer(authorization['database']['tasks']) >= integer(after['tasks']) + 1, 'FINAL_PRESERVED_SOURCE_INVENTORY_NOT_PROVEN')
    changed = before['bindingMode'] != 'ACTIVE' or before['sourceMode'] != 'ACTIVE'
    expected = integer(before['bindingRevision']) + changed
    need(before['bindingMode'] in ('PREVIEW', 'ACTIVE') and before['sourceMode'] in ('COLLECTING', 'ACTIVE')
         and historical['bindingMode'] == before['bindingMode'] and historical['sourceMode'] == before['sourceMode']
         and integer(historical['bindingRevision']) == integer(before['bindingRevision'])
         and integer(admitted['activation']['openedRevision']) == integer(before['bindingRevision'])
         and integer(after['bindingRevision']) == integer(activated['bindingRevision']) == expected
         and activated['bindingMode'] == activated['sourceMode'] == 'ACTIVE'
         and after['sourceActivationRevision'] is not None and 1 <= integer(after['sourceActivationRevision']) <= expected
         and (not changed or integer(after['sourceActivationRevision']) == expected)
         and str(integer(admitted['activation']['actualSupervisorUserId'], 1)) == str(integer(accounts['supervisor']['userId'], 1)),
         'FINAL_ACTIVATION_CONTROL_REVISION_NOT_PROVEN')
    need(all(admitted.get('actualFlags', {}).get(key) is True and authorization.get('actualFlags', {}).get(key) is True for key in REQUIRED_ENV), 'FINAL_STABLE_FLAGS_NOT_PROVEN')
    need(admitted['databaseAfter']['bindingMode'] == admitted['databaseAfter']['sourceMode'] == 'ACTIVE'
         and authorization['database']['bindingMode'] == authorization['database']['sourceMode'] == 'ACTIVE'
         and len(authorization.get('httpPermissions', [])) == 4, 'FINAL_STABLE_AUTHORIZATION_NOT_PROVEN')
    need(admitted['databaseAfter']['serverUuid'] == authorization['database']['serverUuid'] == server_uuid
         and admitted.get('historicalPreview', {}).get('gapCount') == admitted.get('activatedPreview', {}).get('gapCount') == 0
         and admitted.get('activation', {}).get('httpStatus') == 200
         and admitted['activation'].get('sourceProtection') is True and admitted['activation'].get('postReadbackConfirmed') is True,
         'FINAL_ORIGINAL_ACTIVATION_NOT_PROVEN')
    permissions = {item.get('account'): item for item in authorization['httpPermissions']}
    need(set(permissions) == {'inspector', 'peer', 'supervisor', 'reviewer'}, 'FINAL_SCOPE_ACCOUNT_SET_INVALID')
    for alias, item in permissions.items():
        need(str(integer(item.get('userId'), 1)) == str(integer(accounts[alias]['userId'], 1))
             and item.get('role') == accounts[alias]['role'] and item.get('historyHttpStatus') == 200,
             'FINAL_SCOPE_RECEIPT_IDENTITY_INVALID')
        if alias == 'peer':
            need(item.get('progressHttpStatus') in (403, 404) and item.get('traceHttpStatus') in (403, 404)
                 and item.get('historyVisibleItems') == 0, 'FINAL_PEER_SCOPE_NOT_DENIED')
        else:
            need(item.get('progressHttpStatus') == item.get('traceHttpStatus') == 200
                 and integer(item.get('historyVisibleItems'), 1) >= 1, 'FINAL_AUTHORIZED_SCOPE_NOT_READ')
    binding = authorization.get('taskBinding', {})
    need(binding.get('sourceKind') == 'NEW_CREATION' and binding.get('sourceRecorded') is True
         and binding.get('dbAndHttpCreatorMatched') is True
         and str(integer(binding.get('createdUserId'), 1)) == str(integer(accounts['supervisor']['userId'], 1))
         and str(integer(binding.get('assigneeUserId'), 1)) == str(integer(accounts['inspector']['userId'], 1))
         and integer(binding.get('version'), 1) >= 1, 'FINAL_ACTUAL_TASK_BINDING_NOT_PROVEN')
    return True


def require_receipts(ctx):
    preflight = _read_receipt(ctx, 'preflight', 'PREFLIGHT_ONLY')
    admitted = _read_receipt(ctx, 'admission', 'PASS')
    authorization = _read_receipt(ctx, 'authorization', 'PASS')
    validate_final_values(preflight, admitted, authorization, ctx.accounts, ctx.owner['serverUuid'])
    return {'status': 'PASS', 'admission': ctx.owner['stableIdentityAdmission'],
            'authorization': ctx.owner['stableIdentityAuthorization'], 'legacyModeAccepted': False}


if __name__ == '__main__':
    raise SystemExit('Load through the fixed-source owned Runtime hooks; standalone invocation is not acceptance.')
