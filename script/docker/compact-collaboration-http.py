"""Actual candidate HTTP/DB collaboration checks, preserving the nine runtime scenarios."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
import threading
import urllib.error
import urllib.parse
import uuid


def require(value, message):
    if not value:
        raise ValueError(message)


def request(ctx, alias, method, path, body=None, *, headers=None, statuses=(200,)):
    client = ctx.client(alias)
    require(re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]*', client.base)
            and path.startswith('/api/'), 'Collaboration HTTP escaped the owned application endpoint')
    message = client.prepare_request(method, path, body, headers=headers or {})
    try:
        response = client.opener.open(message, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code in statuses and error.code != 200, 'Unexpected collaboration HTTP rejection')
        status = error.code; error.close()
        return {'status': status}
    with response:
        raw = response.read(1024 * 1024 + 1)
        require(response.status in statuses and len(raw) <= 1024 * 1024, 'Unbounded or unexpected collaboration HTTP response')
        value = json.loads(raw)
        if isinstance(value, dict) and 'code' in value:
            require(value['code'] == 200 and response.status == 200, 'A legacy business error cannot prove HTTP success')
            value = value.get('data')
        return {'status': response.status, 'body': value,
                'receipt': {name: response.headers.get(name) for name in
                            ('X-Resource-Version', 'X-Audit-ID', 'X-Change-Event-ID')}}


def command(version, request_id=None):
    require(re.fullmatch(r'0|[1-9][0-9]{0,18}', str(version)), 'A real persisted resource revision is required')
    return {'X-Expected-Version': str(version), 'If-Match': '"' + str(version) + '"',
            'X-Request-ID': request_id or uuid.uuid4().hex}


def save(ctx, name, observations):
    require(name in ('claim', 'personnel') and observations, 'Unknown collaboration evidence')
    value = {**ctx.context(), 'project': ctx.project, 'status': 'PASS', 'observations': observations}
    path = ctx.directory / ('collaboration-http-' + name + '.json')
    ctx.common.write_json(path, value)
    reference = {'file': path.relative_to(ctx.attempt).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    ctx.owner.setdefault('collaborationHttpEvidence', {})[name] = reference
    ctx.save()
    return reference


def claim(ctx):
    task = ctx.report_task_id
    base = '/api/detection/tasks/' + urllib.parse.quote(task, safe='')
    require(re.fullmatch(r'[A-Za-z0-9_-]{1,128}', task), 'Claim must use the actual worker-created task')
    original = request(ctx, 'supervisor', 'GET', base)['body']
    require(original['status'] == 'COMPLETED' and original['flowStatus'] == 'PENDING_REVIEW'
            and not original.get('assignee'), 'Real completed task is not available for candidate authorization')
    aliases = ('peer', 'load_01')
    candidates = [str(ctx.accounts[alias]['userId']) for alias in aliases]
    require(len(set(candidates)) == 2 and all(value != str(ctx.accounts['inspector']['userId']) for value in candidates),
            'Claim competitors must be two independent accounts other than the creator')
    grant = {'candidateUserIds': candidates, 'expectedVersion': str(original['version']), 'requestId': uuid.uuid4().hex}
    authorized = request(ctx, 'supervisor', 'POST', base + '/claim-candidates', grant)['body']
    for alias in aliases:
        visible = request(ctx, alias, 'GET', base)['body']
        require(visible.get('claimReadOnly') is True and set(visible['claimCandidateUserIds']) == set(candidates),
                'Explicit candidates did not receive only the intended temporary read scope')
        denied = request(ctx, alias, 'POST', base + '/retry', headers=command(authorized['version']), statuses=(403,))
        require(denied['status'] == 403, 'Unclaimed candidate acquired an ordinary mutation permission')
    gate = threading.Barrier(2)
    commands = {alias: {'expectedVersion': str(authorized['version']), 'requestId': uuid.uuid4().hex} for alias in aliases}
    def send(alias):
        gate.wait(timeout=10)
        return request(ctx, alias, 'POST', base + '/claim', commands[alias], statuses=(200, 403, 409))
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = {alias: workers.submit(send, alias) for alias in aliases}
        outcomes = {alias: future.result(timeout=45) for alias, future in futures.items()}
    winners = [alias for alias in aliases if outcomes[alias]['status'] == 200]
    require(len(winners) == 1, 'Concurrent independent HTTP claims must have exactly one committed winner')
    winner = winners[0]; loser = next(alias for alias in aliases if alias != winner)
    first = outcomes[winner]
    require(all(first['receipt'].values()), 'Successful claim lacks its real resource/audit/event response receipt')
    replay = request(ctx, winner, 'POST', base + '/claim', commands[winner])
    require(replay['body'] == first['body'] and replay['receipt'] == first['receipt'],
            'Exact claim retry did not return its original result and receipt')
    for path in (base, base + '/trace', base + '/result'):
        require(request(ctx, loser, 'GET', path, statuses=(403, 404))['status'] in (403, 404),
                'Losing candidate retained the temporary task scope')
    q = ctx.db.literal
    actual = ctx.db.one("SELECT JSON_OBJECT('assignee',assignee_user_id,'version',version,'vacant',claim_candidate_ids IS NULL) FROM detection_task WHERE task_id=" + q(task) + ';')
    audits = ctx.db.query("SELECT JSON_OBJECT('id',CAST(id AS CHAR),'actor',CAST(actor_user_id AS CHAR),'request',request_id) FROM audit_event WHERE kind='OPERATIONS' AND operation_domain='DETECTION' AND operation_resource_type='DETECTION_TASK' AND resource_id="
                          + q(task) + " AND action='claimTask';")
    receipts = ctx.db.one("SELECT JSON_OBJECT('n',COUNT(*)) FROM workflow_instance WHERE kind='BUSINESS_COMMAND' AND request_id IN ("
                         + ','.join(q(value['requestId']) for value in commands.values()) + ');')
    require(str(actual['assignee']) == str(ctx.accounts[winner]['userId']) and actual['vacant'] == 1
            and int(actual['version']) == int(authorized['version']) + 1 and len(audits) == 1
            and audits[0]['id'] == first['receipt']['X-Audit-ID']
            and audits[0]['actor'] == str(ctx.accounts[winner]['userId']) and receipts['n'] == 1,
            'Claim HTTP result, stable assignee, revision, audit and command receipt do not agree')
    # Continue the existing report/SDK scenarios through a real supervisor assignment,
    # retaining the winning claim and the reassignment as separate historical facts.
    options = request(ctx, 'supervisor', 'GET', '/api/detection/quality-assignees?keyword='
                      + urllib.parse.quote(ctx.accounts['inspector']['username'], safe=''))['body']
    recipient = [row for row in options if str(row['userId']) == str(ctx.accounts['inspector']['userId'])]
    require(len(recipient) == 1, 'Original inspector is not a current qualified assignment target')
    current = request(ctx, 'supervisor', 'GET', base)['body']
    restored = request(ctx, 'supervisor', 'POST', base + '/assignment', {
        'qualityStation': 'owned-collaboration', 'assignee': recipient[0]['username'],
        'assigneeUserId': recipient[0]['userId'], 'assigneeRevision': recipient[0]['revision'],
        'expectedAssignmentRevision': current['assignmentRevision'], 'assignmentRemark': 'Owned scenario continuation'},
        headers=command(current['version']))['body']
    require(restored['assignee'] == ctx.accounts['inspector']['username'] and not restored.get('claimCandidateUserIds'),
            'Real reassignment did not restore the original scenario scope')
    return save(ctx, 'claim', {'taskId': task, 'competingUserIds': candidates, 'winnerUserId': str(ctx.accounts[winner]['userId']),
        'loserStatus': outcomes[loser]['status'], 'committedVersion': str(actual['version']),
        'auditId': audits[0]['id'], 'exactResponseAndReceiptReplay': True, 'temporaryScopeRevoked': True,
        'candidateOtherWritesDenied': True, 'continuedThroughRealSupervisorAssignment': True})


def personnel(ctx):
    observations = []
    for alias, role in (('load_14', 'COLLECTION'), ('load_15', 'MAINTENANCE')):
        account = ctx.accounts[alias]; user = str(account['userId'])
        # Establish a real previous session before changing a live personnel binding.
        old_client = ctx.client(alias)
        name = 'owned-' + role.lower() + '-' + uuid.uuid4().hex[:12]
        staff = request(ctx, 'supervisor', 'POST', '/api/employees', {
            'name': name, 'employeeNumber': name, 'contact': 'fixture-not-contactable',
            'gender': 'UNKNOWN', 'departmentId': ctx.accounts['supervisor']['departmentId'],
            'employeeType': role, 'status': 'ACTIVE', 'hireDate': '2020-01-01'},
            headers={'X-Request-ID': uuid.uuid4().hex})['body']
        require(str(staff['id']).isdigit() and staff['employeeType'] == role,
                'Actual personnel creation did not retain the non-login position')
        route = '/api/organization/accounts/' + user + '/employee'
        own = request(ctx, alias, 'GET', '/api/organization/me')['body']
        require(str(own['employeeId']) == str(account['employeeId']), 'Owned identity changed before personnel acceptance')
        linked = request(ctx, 'supervisor', 'PUT', route, {'employeeId': staff['id'], 'version': own['bindingVersion']},
                         headers={**command(own['bindingVersion']), 'X-Organization-Action': 'update'})['body']
        require(str(linked['employeeId']) == str(staff['id']), 'Actual supervisor association did not persist')
        require(request(ctx, alias, 'GET', '/api/organization/me', statuses=(401, 403))['status'] in (401, 403),
                'An old JWT retained access after its current personnel qualification was withdrawn')
        login = ctx.rehearsal.Client(ctx.owner['port'])
        result = ctx.http.request(login, 'POST', '/api/auth/login',
                                  {'username': account['username'], 'password': account['password']}, denied=(401, 403))
        require(result['deniedStatus'] in (401, 403), 'A collector/maintenance profile acquired login permission')
        reverted = request(ctx, 'supervisor', 'PUT', route, {'employeeId': account['employeeId'], 'version': linked['bindingVersion']},
                           headers={**command(linked['bindingVersion']), 'X-Organization-Action': 'update'})['body']
        require(str(reverted['employeeId']) == str(account['employeeId']), 'Owned qualified binding was not restored for later scenarios')
        require(request(ctx, alias, 'GET', '/api/organization/me', statuses=(401, 403))['status'] in (401, 403),
                'Restoring qualification resurrected the already revoked login session')
        require(ctx.clients[alias] is old_client, 'Old-session rejection was replaced by another login')
        account['bindingVersion'] = int(reverted['bindingVersion'])
        ctx.common.write_json(ctx.directory / 'users.json', ctx.accounts)
        ctx.clients.pop(alias)
        fresh = request(ctx, alias, 'GET', '/api/organization/me')['body']
        require(str(fresh['employeeId']) == str(account['employeeId']), 'New qualified session could not recover its own identity')
        observations.append({'position': role, 'staffId': str(staff['id']), 'userId': user,
            'createdAndAssociatedThroughActualHttp': True, 'loginRejected': result['deniedStatus'],
            'oldSessionRevokedAndNotResurrected': True, 'qualifiedNewSessionVerified': True})
    return save(ctx, 'personnel', {'positions': observations, 'oldBusinessDataModified': False})


def require_receipts(ctx):
    references = ctx.owner.get('collaborationHttpEvidence', {})
    require(set(references) == {'claim', 'personnel'}, 'Actual HTTP claim and personnel evidence are required')
    for name, reference in references.items():
        path = ctx.directory / ('collaboration-http-' + name + '.json')
        require(reference['file'] == path.relative_to(ctx.attempt).as_posix()
                and reference['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest(), 'Collaboration HTTP evidence changed')
        value = json.loads(path.read_bytes())
        require(all(value.get(key) == expected for key, expected in ctx.context().items())
                and value.get('status') == 'PASS' and value.get('project') == ctx.project,
                'Collaboration HTTP evidence belongs to another source/runtime')
    return references
