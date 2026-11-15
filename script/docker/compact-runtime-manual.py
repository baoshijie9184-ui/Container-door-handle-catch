"""Bounded human handoff inside the existing owned runtime; never a release."""
import fcntl
import os
import re
import time


def require(value, message):
    if not value:
        raise ValueError(message)


def duration(value):
    require(type(value) is int and value in (0, 900, 1800, 3600), 'Invalid manual acceptance duration')
    return value


def read_ready(ctx, execution):
    value, _ = ctx.guard.read_private(ctx.directory / 'manual-ready.json')
    require(all(value.get(key) == expected for key, expected in ctx.context().items())
            and value.get('executionId') == execution['executionId'] and value.get('project') == ctx.project
            and value.get('status') == 'READY_FOR_MANUAL_ACCEPTANCE'
            and value.get('targetSchema') == ctx.owner['targetSchema']
            and value.get('targetTableCount') == 29 and value.get('port') == ctx.owner['port']
            and value.get('credentialsFile') == str(ctx.directory / 'manual-access.json')
            and type(value.get('readyAtUnix')) in (int, float) and type(value.get('expiresAtUnix')) in (int, float)
            and value['expiresAtUnix'] - value['readyAtUnix'] == duration(execution.get('manualAcceptanceSeconds', 0)) > 0,
            'Manual handoff differs from the original candidate')
    return value


def status(ctx, execution):
    if execution['status'] != 'RUNNING':
        return {**ctx.context(), 'executionId': execution['executionId'], 'status': execution['status'], 'terminal': True}
    require(ctx.transport.supervisor_start(execution['supervisor']['pid']) == execution['supervisor']['startTicks'],
            'Original runtime supervisor is not alive')
    if not (ctx.directory / 'manual-ready.json').exists():
        return {**ctx.context(), 'executionId': execution['executionId'], 'status': 'RUNNING', 'terminal': False}
    ready = read_ready(ctx, execution)
    return {**ready, 'terminal': False, 'remainingSeconds': max(0, int(ready['expiresAtUnix'] - time.time()))}


def decide(ctx, execution, payload):
    ready = read_ready(ctx, execution)
    require(execution['status'] == 'RUNNING'
            and ctx.transport.supervisor_start(execution['supervisor']['pid']) == execution['supervisor']['startTicks'],
            'Manual decision requires the original live runtime')
    fields = ('release', 'commit', 'sourceSha256', 'candidateBuildSha256', 'executionId')
    require(type(payload) is dict and set(payload) == {*fields, 'decision', 'submittedBy'}
            and all(payload.get(key) == ready[key] for key in fields)
            and payload.get('decision') in ('ACCEPTED', 'REJECTED')
            and isinstance(payload.get('submittedBy'), str) and 1 <= len(payload['submittedBy']) <= 160
            and not re.search(r'[\x00-\x1f\x7f]', payload['submittedBy']), 'Manual decision has a foreign or invalid identity')
    path = ctx.directory / 'manual-decision.json'
    # The one small atomic decision file is consumed by the still-running owner.
    # An SSH retry can read the same decision but cannot replace another decision.
    lock = ctx.directory / 'manual-decision.lock'
    with lock.open('a') as stream:
        os.chmod(lock, 0o600); fcntl.flock(stream, fcntl.LOCK_EX)
        if path.exists():
            existing, _ = ctx.guard.read_private(path)
            require(all(existing.get(key) == value for key, value in payload.items()), 'Manual decision is already fixed')
        else:
            require(time.time() < ready['expiresAtUnix'], 'Manual acceptance deadline has expired')
            ctx.common.write_json(path, {**payload, 'submittedAtUnix': time.time()})
    return {'status': 'DECISION_RECORDED', 'release': ready['release'], 'executionId': ready['executionId'],
            'decision': payload['decision']}


def wait(ctx, execution):
    seconds = duration(execution.get('manualAcceptanceSeconds', 0))
    if not seconds:
        return {'enabled': False, 'status': 'NOT_REQUESTED'}
    require(ctx.owner.get('phase') == 'ASSERTIONS_PASSED', 'Manual entry requires all automatic assertions')
    require(not (ctx.directory / 'manual-ready.json').exists(), 'Do not restart a manual acceptance window')
    started = time.time()
    ready = {**ctx.context(), 'executionId': execution['executionId'], 'project': ctx.project,
        'status': 'READY_FOR_MANUAL_ACCEPTANCE', 'targetSchema': ctx.owner['targetSchema'], 'targetTableCount': 29,
        'port': ctx.owner['port'], 'readyAtUnix': started, 'expiresAtUnix': started + seconds,
        'credentialsFile': str(ctx.directory / 'manual-access.json'),
        'productionPromotionAllowed': False, 'modelMode': 'ISOLATED_SCRIPTED_LOCAL',
        'automaticBrowserChecks': 21, 'finalCleanupRequired': True}
    private = {'release': ready['release'], 'commit': ready['commit'], 'executionId': ready['executionId'],
        'expiresAtUnix': ready['expiresAtUnix'], 'accounts': {
            alias: {key: account[key] for key in ('username', 'password', 'role')}
            for alias, account in ctx.accounts.items()}}
    ctx.common.write_json(ctx.directory / 'manual-access.json', private)
    ctx.common.write_json(ctx.directory / 'manual-ready.json', ready)
    ctx.save('WAITING_FOR_MANUAL_ACCEPTANCE')
    result = {'enabled': True, 'executionId': ready['executionId'], 'readyAtUnix': started,
              'expiresAtUnix': ready['expiresAtUnix'], 'status': 'CANCELLED'}
    try:
        while True:
            require(ctx.resources.error is None, 'Resource observation failed during manual acceptance')
            path = ctx.directory / 'manual-decision.json'
            if path.exists():
                decision, _ = ctx.guard.read_private(path)
                require(all(decision.get(key) == ready[key] for key in ('release', 'commit', 'sourceSha256', 'candidateBuildSha256', 'executionId'))
                        and decision.get('decision') in ('ACCEPTED', 'REJECTED')
                        and isinstance(decision.get('submittedBy'), str) and 1 <= len(decision['submittedBy']) <= 160
                        and not re.search(r'[\x00-\x1f\x7f]', decision['submittedBy'])
                        and type(decision.get('submittedAtUnix')) in (int, float)
                        and started <= decision['submittedAtUnix'] < ready['expiresAtUnix'], 'Manual decision is not bound to this live window')
                result.update(status=decision['decision'], submittedBy=decision['submittedBy'], submittedAtUnix=decision['submittedAtUnix'])
                require(decision['decision'] == 'ACCEPTED', 'User rejected candidate acceptance')
                return result
            if time.time() >= ready['expiresAtUnix']:
                result['status'] = 'EXPIRED'
                raise ValueError('Manual acceptance deadline expired')
            time.sleep(1)
    finally:
        result['finishedAtUnix'] = time.time()
        ctx.owner['manualAcceptance'] = result
        ctx.save()
        # Credentials are delivered privately only for this bounded window.
        (ctx.directory / 'manual-access.json').unlink(missing_ok=True)
