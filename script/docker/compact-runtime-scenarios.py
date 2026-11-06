#!/usr/bin/env python3
"""HTTP assertions for an owned migrated compact target, invoked by its ECS runner.

No scenario creates successful inference, SDK origin, token usage or delivery
receipts with SQL. Those facts must be produced by the candidate application,
actual SDK, scripted local model, worker and Kafka before evidence is recorded.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


PASSWORD = '123456'
# Existing V18 fixture hash; never applied to an existing or production account.
PASSWORD_HASH = '$2b$12$PdCGX2zMfKOqh9Ja35FndO9Q2GWLdOOj6sDUNb9yXYF8qOtFVD0qm'
OWNED_SCHEMA = re.compile(r'doorhandle_compact_candidate_[a-f0-9]{10}')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def seed_owned_users(db, schema, token):
    require(isinstance(token, str) and re.fullmatch(r'[a-f0-9]{10,32}', token)
            and OWNED_SCHEMA.fullmatch(schema) and db.schema == schema,
            'Accounts may only be seeded in the runner-verified owned compact target')
    actual = db.one("SELECT JSON_OBJECT('schema',DATABASE(),'fk',@@foreign_key_checks,'tables',"
        "(SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE'));")
    require(actual['schema'] == schema and actual['fk'] == 1 and actual['tables'] == 29,
            'Account fixture requires the complete enforced compact target')
    accounts = {}
    for key, role in (('inspector', 'INSPECTOR'), ('peer', 'INSPECTOR'),
                      ('supervisor', 'SUPERVISOR'), ('reviewer', 'SUPERVISOR')):
        username = 'cf_' + token[:16] + '_' + key
        require(db.one('SELECT JSON_OBJECT(\'n\',COUNT(*)) FROM users WHERE username=' + db.literal(username) + ';')['n'] == 0,
                'Owned acceptance identity already exists; do not change its password or role')
        db.execute('INSERT INTO users(username,password,email,role,created_at,updated_at) VALUES('
            + ','.join(db.literal(value) for value in (username, PASSWORD_HASH, username + '@fixture.invalid', role))
            + ',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6));')
        identity = db.one("SELECT JSON_OBJECT('id',id,'role',role) FROM users WHERE BINARY username=BINARY " + db.literal(username) + ';')
        require(identity['id'] > 0 and identity['role'] == role, 'New owned account was not persisted')
        accounts[key] = {'username': username, 'password': PASSWORD, 'userId': identity['id'], 'role': role}
    return accounts


def request(client, method, path, value=None, *, denied=(), headers=None):
    """Reuse the rehearsal client's cookie session and enforce actual API outcomes."""
    require(re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]*', client.base) and path.startswith(('/api/', '/agui/')),
            'Runtime HTTP must remain on the runner-owned loopback endpoint')
    body = None if value is None else json.dumps(value, ensure_ascii=False).encode('utf8')
    message = urllib.request.Request(client.base + path, data=body, method=method, headers={
        'Content-Type': 'application/json', 'X-Agent-Action': 'workbench',
        'X-Budget-Action': 'update', 'X-Report-Action': 'update', 'X-Skill-Action': 'update',
        'Sec-Fetch-Site': 'same-origin', **(headers or {})})
    try:
        response = client.opener.open(message, timeout=30)
    except urllib.error.HTTPError as error:
        # An internal failure, malformed route or unconfigured fixture is not an
        # authorization proof. Only the explicitly expected denial is accepted.
        require(error.code in denied, 'Runtime API failed with an unexpected HTTP status')
        error.close()
        return {'deniedStatus': error.code}
    with response:
        raw = response.read(16 * 1024 * 1024 + 1)
        require(len(raw) <= 16 * 1024 * 1024, 'Runtime response exceeded its evidence budget')
        if 'application/json' not in response.headers.get('Content-Type', ''):
            require(not denied, 'A successful download cannot prove access denial')
            return raw
        result = json.loads(raw)
        if isinstance(result, dict) and 'code' in result:
            if result['code'] != 200:
                require(result['code'] in denied, 'Runtime API failed with an unexpected business status')
                return {'deniedStatus': result['code']}
            result = result.get('data')
        require(not denied, 'A forbidden operation unexpectedly succeeded')
        return result


def clients(ctx):
    result = {}
    for key in ('inspector', 'peer', 'supervisor', 'reviewer'):
        account = ctx.accounts[key]; client = ctx.client(key)
        request(client, 'POST', '/api/auth/login', {'username': account['username'], 'password': account['password']})
        identity = request(client, 'GET', '/api/auth/check')
        require(identity.get('authenticated') is True and identity.get('userId') == account['userId']
                and identity.get('username') == account['username'] and identity.get('role') == account['role'],
                'HTTP login/check did not establish the exact new role/account')
        result[key] = client
    return result


def mine(client, model):
    records = request(client, 'GET', '/api/agent/model-quotas/mine')
    matches = [row for row in records if row.get('modelId') == model]
    require(len(matches) == 1, 'Configured model quota is absent or ambiguous')
    return matches[0]


def journal_events(ctx, account, run_id):
    result = []; cursor = 0
    for _ in range(100):
        page = ctx.request(account, 'GET', '/api/agent/runs/' + run_id + '/events?after=' + str(cursor) + '&limit=100')
        if not page:
            return result
        require(all(item['sequence'] > cursor for item in page), 'Durable journal cursor did not advance')
        result.extend(page); cursor = page[-1]['sequence']
    raise RuntimeError('Runtime journal exceeded the bounded scenario evidence budget')


def workbench(ctx, account, session):
    return ctx.request(account, 'GET', '/api/agent/conversations/' + session + '/workbench')


def board_command(ctx, account, session, item, action, value=None, request_id=None):
    return ctx.request(account, 'POST', '/api/agent/conversations/' + session + '/workbench/' + item['id'], {
        'requestId': request_id or uuid.uuid4().hex, 'revision': item['revision'],
        'action': action, 'input': value or {}})


def sdk_scenario(ctx):
    """Exercise real plans, child dispatch, files, snapshots, restart and cancel."""
    require(callable(getattr(ctx, 'run_sdk', None)) and callable(getattr(ctx, 'restart_backend', None)),
            'The runtime runner must support actual SDK execution and backend restart')
    marker = 'runtime-sdk-' + ctx.token
    body = '# Owned SDK artifact\n' + marker + '\n'
    task_id = ctx.report_task_id
    result = ctx.run_sdk('inspector', [
        {'tool': 'update_task_list', 'arguments': {'tasks': [{'title': '查询本人任务', 'status': 'in_progress'}]}},
        {'tool': 'create_artifact', 'arguments': {'filename': 'owned-runtime.md', 'content': body}},
        {'tool': 'delegate_detection_task', 'arguments': {'question': '查看 ' + marker + ' 任务 ' + task_id + ' 的状态'}},
        {'tool': 'get_task_detail', 'arguments': {'taskId': task_id}},
        {'text': '本人任务查询已返回 ' + marker}, {'text': '本轮隔离查询结束 ' + marker}],
        '生成一份本人任务查询记录 ' + marker, model=ctx.model_id, marker=marker)
    require(result['phase'] == 'COMPLETED' and result['approvedPlans'],
            'Complex SDK work bypassed the actual persisted plan approval')
    session = result['sessionId']; owner = ctx.accounts['inspector']['userId']; q = ctx.db.literal
    board = workbench(ctx, 'inspector', session)
    main = [item for item in board['items'] if item['kind'] == 'EXECUTION']
    children = [item for item in board['items'] if item['kind'] == 'CHILD']
    require(len(main) == 1 and main[0]['status'] == 'COMPLETED' and len(children) == 1
            and children[0]['status'] == 'COMPLETED' and children[0]['data']['parentId'] == main[0]['id'],
            'Actual specialist child did not preserve its completed parent relation')
    child = children[0]
    require(main[0]['data']['modelConfigVersion'] == child['data']['modelConfigVersion']
            and main[0]['data']['modelId'] == child['data']['modelId'] == ctx.model_id,
            'Actual parent and child did not retain the same governed model snapshot')
    child_run = child['data']['runId']
    child_events = journal_events(ctx, 'inspector', child_run)
    require(any(item['type'] == 'TOOL_COMPLETED' and item['payload'].get('tool') == 'get_task_detail'
                for item in child_events), 'The specialist did not produce a real successful business tool trace')
    tools = ctx.db.query("SELECT JSON_OBJECT('item',workbench_item_id,'run',run_id,'tool',"
        "JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.data.tool')),'call',JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.data.callId')),"
        "'parent',workbench_parent_item_id,'task',workbench_logical_task_id,'status',status,'fence',fence)"
        " FROM workflow_instance WHERE kind='WORKBENCH_TOOL' AND owner_user_id=" + str(owner)
        + ' AND session_id=' + q(session) + ' ORDER BY id;')
    business = [item for item in tools if item['tool'] == 'get_task_detail']
    require(len(business) == 1 and business[0]['run'] == child_run and business[0]['parent'] == child['id']
            and business[0]['status'] == 'COMPLETED' and business[0]['call'],
            'Durable business tool result lost its actual run/call/child provenance')
    files = [item for item in board['files'] if item['name'] == 'owned-runtime.md']
    require(len(files) == 1 and files[0]['bytes'] == len(body.encode('utf8'))
            and files[0]['sha256'] == hashlib.sha256(body.encode('utf8')).hexdigest(),
            'SDK-created file metadata does not match its real bytes')
    file_path = '/api/agent/conversations/' + session + '/files/' + files[0]['id'] + '/content'
    require(ctx.request('inspector', 'GET', file_path) == body.encode('utf8'), 'Actual workspace file download differs')
    snapshot = ctx.db.one("SELECT JSON_OBJECT('n',COUNT(*),'message',MAX(id),'owner',MAX(execution_owner_user_id),"
        "'valid',MIN(workspace_snapshot_sha256=SHA2(workspace_snapshot_json,256))) FROM chat_message"
        + ' WHERE session_id=' + q(session) + ' AND execution_run_id=' + q(result['runId']) + ';')
    require(snapshot['n'] == 1 and snapshot['owner'] == owner and snapshot['valid'] == 1,
            'Actual assistant turn lacks its owned verified workspace snapshot')
    checkpoints = ctx.db.query("SELECT JSON_OBJECT('session',session_id,'key',state_key,'revision',revision,"
        "'sha256',SHA2(payload_json,256)) FROM runtime_state WHERE namespace='SDK_CHECKPOINT' AND owner_id="
        + str(owner) + ' AND session_id IN (' + q('wb:' + result['logicalTaskId'] + ':main') + ','
        + q('wb:' + child['data']['logicalTaskId'] + ':' + child['id']) + ') ORDER BY session_id,state_key;')
    require(len(checkpoints) >= 2 and all(item['revision'] > 0 for item in checkpoints),
            'Real parent/child SDK checkpoints were not durably written')
    for other in ('peer', 'supervisor'):
        client = ctx.client(other)
        for path in ('/api/agent/conversations/' + session + '/workbench', file_path,
                     '/api/agent/runs/' + result['runId'], '/api/agent/runs/' + child_run + '/events'):
            request(client, 'GET', path, denied=(403, 404))
    fork_request = {'requestId': uuid.uuid4().hex, 'throughMessageId': snapshot['message']}
    fork = ctx.request('inspector', 'POST', '/api/agent/conversations/' + session + '/fork', fork_request)
    require(ctx.request('inspector', 'POST', '/api/agent/conversations/' + session + '/fork', fork_request) == fork,
            'The actual fork request did not replay its original session')
    fork_board = workbench(ctx, 'inspector', fork['sessionId'])
    require(fork_board['lineage']['sourceSessionId'] == session
            and fork_board['lineage']['throughMessageId'] == snapshot['message']
            and any(item['kind'] == 'FORK_SNAPSHOT' for item in fork_board['items']),
            'Actual conversation fork lost its completed cut point and workbench reference')
    separate = ctx.request('inspector', 'POST', '/api/chat-assistant/sessions')['sessionId']
    require(ctx.request('inspector', 'GET', '/api/chat-assistant/sessions/' + separate + '/messages') == [],
            'A separate conversation inherited private history')
    before_messages = ctx.request('inspector', 'GET', '/api/chat-assistant/sessions/' + session + '/messages')
    ctx.restart_backend()
    require(ctx.request('inspector', 'GET', '/api/chat-assistant/sessions/' + session + '/messages') == before_messages,
            'A real backend restart lost or rewrote persisted conversation history')
    after_checkpoints = ctx.db.query("SELECT JSON_OBJECT('session',session_id,'key',state_key,'revision',revision,"
        "'sha256',SHA2(payload_json,256)) FROM runtime_state WHERE namespace='SDK_CHECKPOINT' AND owner_id="
        + str(owner) + ' AND session_id IN (' + ','.join(q(item['session']) for item in checkpoints)
        + ') ORDER BY session_id,state_key;')
    require(after_checkpoints == checkpoints, 'A real restart changed completed SDK checkpoint bytes or clocks')
    restore_marker = 'runtime-restore-' + ctx.token
    resumed_text = '已根据实际回答完成原任务 ' + restore_marker
    suspended = ctx.run_sdk('inspector', [
        {'tool': 'ask_user_question', 'arguments': {'text': '请选择本轮只读查询范围',
            'questionType': 'SINGLE', 'options': ['当前任务', '最近任务']}},
        {'text': resumed_text}], '查看需要补充的查询条件', model=ctx.model_id,
        marker=restore_marker, expected_phase='WAITING_INPUT')
    restore_session = suspended['sessionId']
    restore_board = workbench(ctx, 'inspector', restore_session)
    restore_question = next(item for item in restore_board['items']
                            if item['kind'] == 'QUESTION' and item['status'] == 'PENDING')
    original_execution = next(item for item in restore_board['items'] if item['kind'] == 'EXECUTION')
    require(original_execution['data']['logicalTaskId'] == suspended['logicalTaskId']
            and original_execution['status'] == 'WAITING_INPUT', 'Actual suspended SDK task identity is missing')
    question_trace = journal_events(ctx, 'inspector', suspended['runId'])
    question_calls = [item['payload']['callId'] for item in question_trace
                      if item['type'] == 'TOOL_COMPLETED' and item['payload'].get('tool') == 'ask_user_question']
    require(len(question_calls) == 1, 'Actual suspended SDK run lacks its original successful question tool call')
    sdk_session = 'wb:' + suspended['logicalTaskId'] + ':main'
    checkpoint_sql = ("SELECT JSON_OBJECT('revision',revision,'sha256',SHA2(payload_json,256),"
        "'stateJson',JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.stateJson'))) FROM runtime_state"
        " WHERE namespace='SDK_CHECKPOINT' AND owner_id=" + str(owner)
        + ' AND session_id=' + q(sdk_session) + " AND state_key='agent_state';")
    before_restore = ctx.db.one(checkpoint_sql)
    require(before_restore['revision'] > 0 and isinstance(before_restore['stateJson'], str)
            and restore_marker in before_restore['stateJson'] and question_calls[0] in before_restore['stateJson'],
            'Actual suspended SDK checkpoint lost its initial context or tool provenance')
    ctx.restart_backend()
    require(ctx.db.one(checkpoint_sql) == before_restore,
            'The suspended checkpoint changed before any approved continuation')
    restored_board = workbench(ctx, 'inspector', restore_session)
    restored_question = next(item for item in restored_board['items'] if item['id'] == restore_question['id'])
    require(restored_question == restore_question, 'The original pending question did not survive backend replacement')
    answer_id = uuid.uuid4().hex
    answered = board_command(ctx, 'inspector', restore_session, restore_question, 'answer',
                             {'answer': '当前任务'}, request_id=answer_id)
    require(answered['status'] == 'ANSWERED'
            and board_command(ctx, 'inspector', restore_session, restore_question, 'answer',
                              {'answer': '当前任务'}, request_id=answer_id) == answered,
            'The actual answer did not persist and replay its original command')
    restore_end = time.monotonic() + 180
    while time.monotonic() < restore_end:
        observed = workbench(ctx, 'inspector', restore_session)
        resumed = next(item for item in observed['items'] if item['kind'] == 'EXECUTION')
        require(resumed['id'] == original_execution['id']
                and resumed['data']['logicalTaskId'] == suspended['logicalTaskId']
                and resumed['status'] not in {'NEEDS_REVIEW', 'UNKNOWN', 'CANCELLED'},
                'A checkpoint continuation was replaced by a new task or lost its valid execution claim')
        if resumed['status'] == 'COMPLETED':
            resumed_run_id = resumed['data']['runId']
            resumed_run = ctx.request('inspector', 'GET', '/api/agent/runs/' + resumed_run_id)
            saved_reply = ctx.db.one("SELECT JSON_OBJECT('n',COUNT(*)) FROM chat_message WHERE execution_run_id="
                + q(resumed_run_id) + ' AND execution_owner_user_id=' + str(owner) + ';')
            if resumed_run['status'] == 'COMPLETED' and saved_reply['n'] == 1:
                break
        time.sleep(0.25)
    else:
        raise RuntimeError('The actual restored SDK task did not complete after the approved answer')
    require(resumed_run_id != suspended['runId'] and resumed_run['sessionId'] == restore_session
            and ctx.request('inspector', 'GET', '/api/agent/runs/' + suspended['runId'])['status'] == 'INTERRUPTED',
            'Checkpoint recovery rewrote the interrupted attempt instead of creating a real continuation')
    after_restore = ctx.db.one(checkpoint_sql)
    require(after_restore['revision'] > before_restore['revision']
            and after_restore['sha256'] != before_restore['sha256']
            and restore_marker in after_restore['stateJson'] and question_calls[0] in after_restore['stateJson']
            and resumed_text in after_restore['stateJson'],
            'Actual checkpoint execution did not advance while retaining its prior context and question tool call')
    resumed_messages = ctx.request('inspector', 'GET', '/api/chat-assistant/sessions/' + restore_session + '/messages')
    require(any(item['role'] == 'assistant' and resumed_text in item['content'] for item in resumed_messages),
            'The actual resumed SDK answer was not saved to the original conversation')
    resumed_trace = journal_events(ctx, 'inspector', resumed_run_id)
    require(any(item['type'] == 'MODEL_COMPLETED' for item in resumed_trace)
            and not any(item['type'] in {'RUN_ERROR', 'MODEL_ERROR', 'TOOL_ERROR'} for item in resumed_trace)
            and not any(item['type'] == 'TOOL_STARTED' and item['payload'].get('tool') == 'ask_user_question'
                        for item in resumed_trace),
            'Restoration did not execute the actual model, or repeated the already answered question tool')
    # A genuine user question yields a durable checkpoint. Cancellation must
    # settle that same logical task and reject late interaction submissions.
    waiting = ctx.run_sdk('inspector', [{'tool': 'ask_user_question', 'arguments': {
        'text': '请选择本轮只读查询范围', 'questionType': 'SINGLE', 'options': ['当前任务', '最近任务']}}],
        '查看待补充的查询条件', model=ctx.model_id, marker='runtime-cancel-' + ctx.token,
        expected_phase='WAITING_INPUT')
    wait_board = workbench(ctx, 'inspector', waiting['sessionId'])
    question = next(item for item in wait_board['items'] if item['kind'] == 'QUESTION' and item['status'] == 'PENDING')
    ctx.restart_backend()
    restored = workbench(ctx, 'inspector', waiting['sessionId'])
    restored_question = next(item for item in restored['items'] if item['id'] == question['id'])
    require(restored_question == question, 'Pending SDK interaction did not survive the real backend restart')
    cancel_id = uuid.uuid4().hex
    cancelled = board_command(ctx, 'inspector', waiting['sessionId'], question, 'cancel', request_id=cancel_id)
    require(cancelled['status'] == 'CANCELLED'
            and board_command(ctx, 'inspector', waiting['sessionId'], question, 'cancel', request_id=cancel_id) == cancelled,
            'Cancellation did not persist and replay the same owned command receipt')
    request(ctx.client('inspector'), 'POST', '/api/agent/conversations/' + waiting['sessionId'] + '/workbench/' + question['id'],
            {'requestId': uuid.uuid4().hex, 'revision': question['revision'], 'action': 'answer', 'input': {'answer': '当前任务'}},
            denied=(409,))
    settled = workbench(ctx, 'inspector', waiting['sessionId'])
    require(all(item['status'] == 'CANCELLED' for item in settled['items'] if item['kind'] == 'EXECUTION'),
            'Late input resurrected the cancelled logical task')
    fence = ctx.db.one("SELECT JSON_OBJECT('status',status,'claim',claim_token,'lease',lease_expires_at,'fence',fence)"
        " FROM workflow_instance WHERE kind='WORKBENCH_EXECUTION' AND owner_user_id=" + str(owner)
        + ' AND session_id=' + q(waiting['sessionId']) + ';')
    require(fence['status'] == 'CANCELLED' and fence['claim'] is None and fence['lease'] is None and fence['fence'] > 0,
            'Cancelled execution retained an active writer claim')
    ctx.sdk_source_run_id = child_run
    return ctx.record('sdk-session-workbench-recovery', {'sessionId': session, 'runId': result['runId'],
        'initialRunId': result['initialRunId'], 'requestKey': result['requestKey'], 'planIds': result['approvedPlans'],
        'childRunId': child_run, 'toolCallId': business[0]['call'], 'fileSha256': files[0]['sha256'],
        'checkpointDigests': checkpoints, 'forkSessionId': fork['sessionId'],
        'restoredSessionId': restore_session, 'restoredLogicalTaskId': suspended['logicalTaskId'],
        'interruptedRunId': suspended['runId'], 'resumedRunId': resumed_run_id,
        'restoredQuestionCallId': question_calls[0], 'beforeRestoreRevision': before_restore['revision'],
        'afterRestoreRevision': after_restore['revision'], 'afterRestoreSha256': after_restore['sha256'],
        'cancelledSessionId': waiting['sessionId'], 'cancelledExecutionFence': fence['fence']})


def skill_scenario(ctx):
    """Derive a skill only from actual successful owned SDK business evidence."""
    source = getattr(ctx, 'sdk_source_run_id', None)
    require(source, 'Skill acceptance requires the actual prior owned specialist run')
    source_run = ctx.request('inspector', 'GET', '/api/agent/runs/' + source)
    require(source_run['entryPoint'] == 'CHILD' and source_run['status'] == 'COMPLETED',
            'Skill source is not a real completed specialist execution')
    trace = journal_events(ctx, 'inspector', source)
    require(any(item['type'] == 'TOOL_COMPLETED' and item['payload'].get('tool') == 'get_task_detail'
                for item in trace), 'Skill source lacks an actual successful eligible business tool')
    name = 'owned-task-guide-' + ctx.token
    instructions = ('先核对当前账号允许读取的任务范围，再使用 get_task_detail 查询单个任务。'
        '区分检测处理状态和复核状态，只报告工具实际返回的字段，缺少证据时明确说明未知。'
        '不得扩大当前角色权限，涉及后续业务变更时应由原业务页面核对确认。')
    draft = {'name': name, 'targetRole': 'INSPECTOR', 'description': '按真实任务回执核对状态的只读经验',
             'instructions': instructions, 'tools': ['get_task_detail'], 'sourceRunId': source,
             'requestId': 'runtime-skill-' + ctx.token}
    base = '/api/agent/skills'
    # A real persisted run is still private until its own owner grants consent.
    request(ctx.client('inspector'), 'POST', base, draft, denied=(403,))
    for other in ('peer', 'supervisor'):
        request(ctx.client(other), 'POST', base + '/sources/' + source + '/consent', denied=(403, 404))
    granted = ctx.request('inspector', 'POST', base + '/sources/' + source + '/consent')
    require('get_task_detail' in granted['tools'] and granted['framework'] == 'AgentScope'
            and set(granted) == {'tools', 'completedAt', 'framework', 'entryPoint'},
            'Source consent copied private conversation or lacks actual tool evidence')
    safe_evidence = json.dumps(granted, ensure_ascii=False)
    require(source not in safe_evidence and ctx.report_task_id not in safe_evidence
            and all(account['username'] not in safe_evidence for account in ctx.accounts.values()),
            'Source consent retained private account/run/task identity inside reusable evidence')
    proposal_args = {key: value for key, value in draft.items() if key != 'requestId'}
    proposed = ctx.run_sdk('inspector', [
        {'tool': 'propose_learned_skill', 'arguments': proposal_args},
        {'text': '本人技能经验已保存为私人草稿，等待规则评测和独立审核'}],
        '请根据本人已授权来源提议私人任务查询经验', model=ctx.model_id,
        marker='runtime-skill-proposal-' + ctx.token)
    visible = ctx.request('inspector', 'GET', base)
    matches = [item for item in visible if item['name'] == name]
    require(len(matches) == 1, 'Actual SDK skill proposal did not create exactly one owned draft')
    view = matches[0]; skill = view['skillId']; path = base + '/' + skill
    require(view['activeVersion'] is None and view['latestVersion'] == 1
            and view['versions'][0]['status'] == 'DRAFT' and view['versions'][0]['sourceRunId'] == source,
            'A new private draft was published or lost its source relation')
    for other in ('peer', 'supervisor'):
        request(ctx.client(other), 'GET', path, denied=(403, 404))
        require(all(item['skillId'] != skill for item in ctx.request(other, 'GET', base)),
                'Private skill draft leaked through another account list')
    q = ctx.db.literal; owner = ctx.accounts['inspector']['userId']
    origin = ctx.db.one("SELECT JSON_OBJECT('n',COUNT(*),'run',MAX(run_id),'call',"
        "MAX(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.callId')))) FROM audit_event WHERE kind='SKILL_AUDIT'"
        + " AND action='CREATE_DRAFT' AND resource_id=" + q(skill) + ' AND owner_user_id=' + str(owner) + ';')
    require(origin['n'] == 1 and origin['run'] in proposed['runIds'] and origin['call'],
            'Skill draft did not preserve its actual SDK run/call provenance')
    immutable = ctx.db.query("SELECT JSON_OBJECT('version',version,'content',content_sha256,'stored',stored_content_sha256,"
        "'source',source_run_id,'bodySha256',SHA2(content_text,256)) FROM content_revision WHERE asset_kind='SKILL'"
        + ' AND asset_id=' + q(skill) + ' ORDER BY version;')
    require(len(immutable) == 1 and immutable[0]['source'] == source
            and immutable[0]['stored'] == immutable[0]['bodySha256'], 'Skill revision byte digest does not match its real body')

    def publish(candidate):
        evaluated = ctx.request('inspector', 'POST', path + '/eval', {'expectedRevision': candidate['revision']})
        latest = next(item for item in evaluated['versions'] if item['version'] == evaluated['latestVersion'])
        require(latest['status'] == 'EVALUATED' and evaluated['evaluations']
                and evaluated['evaluations'][0]['result']['passed'] is True
                and evaluated['evaluations'][0]['result']['paidModelsCalled'] is False,
                'Actual server structural-policy evaluation did not pass without paid models')
        submitted = ctx.request('inspector', 'POST', path + '/submit', {'expectedRevision': evaluated['revision']})
        command = {'expectedRevision': submitted['revision'], 'decision': 'APPROVE',
            'reason': '核对本人授权的只读业务来源和脱敏经验适用范围', 'businessReviewed': True, 'privacyReviewed': True}
        request(ctx.client('inspector'), 'POST', path + '/decision', command, denied=(403,))
        reviewed = ctx.request('supervisor', 'GET', path)
        require(all(item['sourceRunId'] is None for item in reviewed['versions']),
                'Reviewing a submitted skill exposed its private source run identity')
        approved = ctx.request('supervisor', 'POST', path + '/decision', command)
        require(approved['activeVersion'] == submitted['latestVersion']
                and any(item['version'] == approved['activeVersion'] and item['status'] == 'APPROVED'
                        for item in approved['versions']), 'Independent supervisor review did not publish the actual approved version')
        return ctx.request('inspector', 'GET', path)

    view = publish(view)
    command_catalog = ctx.request('peer', 'GET', '/api/agent/commands')
    require(any(item['skillId'] == skill and item['version'] == 1 for item in command_catalog['skills']),
            'Published role skill did not enter the actual command catalog')
    require(all(item['skillId'] != skill for item in ctx.request('supervisor', 'GET', '/api/agent/commands')['skills']),
            'Inspector role skill leaked into the supervisor execution catalog')
    # AgentScope 2.0.4 AgentSkill.getSkillId is name + '_' + source.
    native_name = 'learned-' + skill[6:] + '-v1_approved-project'
    used = ctx.run_sdk('inspector', [
        {'tool': 'load_skill_through_path', 'arguments': {'skillId': native_name, 'path': 'SKILL.md'}},
        {'text': '已读取经审核的只读任务经验，仍遵守原有业务权限'}],
        '读取已发布的任务查询经验', model=ctx.model_id, marker='runtime-skill-load-' + ctx.token)
    use_trace = journal_events(ctx, 'inspector', used['runId'])
    require(any(item['type'] == 'TOOL_COMPLETED' and item['payload'].get('tool') == 'load_skill_through_path'
                for item in use_trace), 'Actual native SDK skill read did not finish')
    use = ctx.db.one("SELECT JSON_OBJECT('count',use_count,'lastUsed',last_used_at) FROM content_asset WHERE asset_kind='SKILL'"
        + ' AND asset_id=' + q(skill) + ';')
    audited_use = ctx.db.one("SELECT JSON_OBJECT('n',COUNT(*),'call',MAX(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.callId'))))"
        " FROM audit_event WHERE kind='SKILL_AUDIT' AND action='LOAD' AND resource_id=" + q(skill)
        + ' AND owner_user_id=' + str(owner) + ' AND run_id=' + q(used['runId']) + ';')
    require(use['count'] > 0 and use['lastUsed'] is not None and audited_use['n'] > 0 and audited_use['call'],
            'Actual SDK skill usage did not persist its time/count and run/call audit')
    view = ctx.request('inspector', 'GET', path)
    second = {**draft, 'requestId': 'runtime-skill-v2-' + ctx.token,
              'instructions': instructions + ' 查询结束后复核返回信息的适用时间。'}
    view = ctx.request('inspector', 'POST', path + '/versions?expectedRevision=' + str(view['revision']), second)
    require(view['latestVersion'] == 2 and view['activeVersion'] == 1, 'Draft revision replaced the published pointer prematurely')
    view = publish(view)
    before_rollback = ctx.db.query("SELECT JSON_OBJECT('version',version,'content',content_sha256,'stored',stored_content_sha256,"
        "'source',source_run_id,'bodySha256',SHA2(content_text,256)) FROM content_revision WHERE asset_kind='SKILL'"
        + ' AND asset_id=' + q(skill) + ' ORDER BY version;')
    require(len(before_rollback) == 2 and before_rollback[:1] == immutable, 'Appending a skill version rewrote immutable original content')
    rolled = ctx.request('supervisor', 'POST', path + '/rollback', {'expectedRevision': view['revision'],
                         'targetVersion': 1, 'reason': '核对新旧版本后回退到首个已审核版本'})
    require(rolled['activeVersion'] == 1 and rolled['latestVersion'] == 2, 'Rollback did not retain both immutable versions')
    archived = ctx.request('supervisor', 'POST', path + '/archive', {'expectedRevision': rolled['revision'],
                          'reason': '本轮验收结束，停用测试经验并保留历史'})
    require(archived['activeVersion'] is None and archived['lifecycle'] == 'ARCHIVED', 'Archive retained an executable publication pointer')
    for account in ('inspector', 'peer', 'supervisor'):
        require(all(item['skillId'] != skill for item in ctx.request(account, 'GET', '/api/agent/commands')['skills']),
                'Archived skill remained executable through a role command catalog')
    after = ctx.db.query("SELECT JSON_OBJECT('version',version,'content',content_sha256,'stored',stored_content_sha256,"
        "'source',source_run_id,'bodySha256',SHA2(content_text,256)) FROM content_revision WHERE asset_kind='SKILL'"
        + ' AND asset_id=' + q(skill) + ' ORDER BY version;')
    require(after == before_rollback, 'Rollback or archive changed immutable source/body digest history')
    audit = ctx.db.query("SELECT JSON_OBJECT('action',action,'actor',actor_user_id,'run',run_id,'revision',revision)"
        " FROM audit_event WHERE kind='SKILL_AUDIT' AND resource_id=" + q(skill) + ' ORDER BY id;')
    require({'CREATE_DRAFT', 'EVAL', 'SUBMIT', 'PUBLISH', 'LOAD', 'REVISE', 'ROLLBACK', 'ARCHIVE'}
            <= {item['action'] for item in audit}, 'Actual skill lifecycle audit is incomplete')
    return ctx.record('skills-capture-publish-use-rollback', {'skillId': skill, 'sourceRunId': source,
        'proposalRunId': origin['run'], 'proposalCallId': origin['call'], 'nativeLoadRunId': used['runId'],
        'nativeLoadCallId': audited_use['call'], 'revisionDigests': after,
        'lifecycleActions': [item['action'] for item in audit], 'finalLifecycle': archived['lifecycle']})


def run_http_scenarios(ctx):
    session = clients(ctx)
    private_session = request(session['inspector'], 'POST', '/api/chat-assistant/sessions')
    session_id = private_session['sessionId']
    require(isinstance(session_id, str) and session_id, 'Actual owned chat session was not created')
    private_path = '/api/chat-assistant/sessions/' + urllib.parse.quote(session_id, safe='')
    for key in ('peer', 'supervisor'):
        request(session[key], 'GET', private_path, denied=(403, 404))
        request(session[key], 'PUT', private_path + '/title', {'title': '不能越权改名'}, denied=(403, 404))
        visible = request(session[key], 'GET', '/api/chat-assistant/sessions')
        require(all(row['sessionId'] != session_id for row in visible), 'Private session leaked through another user\'s list')
    require(request(session['inspector'], 'GET', private_path)['title'] == private_session['title'],
            'A denied cross-user request changed the actual owner session')
    persisted = ctx.db.one("SELECT JSON_OBJECT('n',COUNT(*)) FROM chat_session WHERE session_id="
        + ctx.db.literal(session_id) + ' AND user_id=' + str(ctx.accounts['inspector']['userId']) + ';')
    require(persisted['n'] == 1, 'HTTP session did not retain the real business owner ID')
    for key in ('inspector', 'peer'):
        request(session[key], 'GET', '/api/agent/model-quotas/applications?scope=team', denied=(403,))
        request(session[key], 'GET', '/api/agent/model-budgets', denied=(403,))
    request(session['supervisor'], 'GET', '/api/agent/model-quotas/applications?scope=team')
    evidence = [ctx.record('auth-role-isolation', {'distinctUsers': len(ctx.accounts),
        'inspectorDeniedTeamQuota': True, 'inspectorDeniedEnterpriseBudget': True,
        'rolesVerified': ['INSPECTOR', 'SUPERVISOR'], 'privateSessionId': session_id,
        'crossUserReadsAndWritesDenied': True})]
    catalog = request(session['inspector'], 'GET', '/agui/models')
    entries = catalog.get('models') if 'models' in catalog else catalog.get('entries')
    require(isinstance(entries, list), 'Actual model catalog has no model entries')
    configured = [row for row in entries if row.get('configured') is True]
    require(configured, 'Owned scripted model must be published through the real model configuration API')
    model = configured[0]['id']
    before = mine(session['inspector'], model); peer = mine(session['peer'], model)
    require(before['configured'] is True and before['hasPersonalQuota'] is False and before['availableTokens'] is None
            and peer['configured'] is True and peer['hasPersonalQuota'] is False,
            'Fresh users lost their preexisting model access without a personal quota')
    amount = 100000
    application_request = {'modelId': model, 'requestedTokens': amount,
        'reason': '本轮隔离验收的模型额度申请', 'requestId': 'quota-apply-' + ctx.token}
    application = request(session['inspector'], 'POST', '/api/agent/model-quotas/applications', application_request)
    require(application['status'] == 'PENDING' and application['requestedTokens'] == amount
            and application['applicantUserId'] == ctx.accounts['inspector']['userId'], 'Quota request was not durably pending')
    repeated = request(session['inspector'], 'POST', '/api/agent/model-quotas/applications', application_request)
    require(repeated['id'] == application['id'] and repeated['version'] == application['version'], 'Quota request replay created or changed an application')
    request(session['inspector'], 'POST', '/api/agent/model-quotas/applications',
            dict(application_request, requestedTokens=1.5, requestId='quota-fraction-' + ctx.token), denied=(400,))
    mine_applications = request(session['peer'], 'GET', '/api/agent/model-quotas/applications?scope=mine')['items']
    require(all(item['id'] != application['id'] for item in mine_applications), 'Peer application list disclosed another user\'s request')
    application_path = '/api/agent/model-quotas/applications/' + application['id']
    decision = {'decision': 'APPROVE', 'reason': '隔离场景主管确认使用额度', 'expectedVersion': application['version'],
                'requestId': 'quota-approve-' + ctx.token}
    request(session['peer'], 'POST', application_path + '/decision', decision, denied=(403,))
    request(session['peer'], 'POST', application_path + '/cancel',
            {'expectedVersion': application['version'], 'requestId': 'quota-peer-cancel-' + ctx.token}, denied=(403,))
    approved = request(session['supervisor'], 'POST', application_path + '/decision', decision)
    require(approved['status'] == 'APPROVED' and approved['deciderUserId'] == ctx.accounts['supervisor']['userId'],
            'Independent supervisor did not approve the actual application')
    replayed = request(session['supervisor'], 'POST', application_path + '/decision', decision)
    require(replayed['version'] == approved['version'], 'Approval replay granted quota twice')
    granted = mine(session['inspector'], model)
    require(granted['hasPersonalQuota'] is True and granted['totalTokens'] == amount
            and granted['availableTokens'] == amount and granted['reservedTokens'] == granted['spentTokens'] == 0,
            'Visible personal quota does not equal its one approved grant')
    require(mine(session['peer'], model)['hasPersonalQuota'] is False, 'An unrelated peer received the applicant\'s quota')
    ctx.quota_scenario = {'model': model, 'amount': amount, 'applicationId': application['id'],
                          'version': approved['version'], 'beforeSpent': granted['spentTokens']}
    if callable(getattr(ctx, 'invoke_model', None)):
        evidence.append(run_quota_consumption_scenario(ctx))
    return evidence


def run_quota_consumption_scenario(ctx):
    scenario = ctx.quota_scenario
    require(callable(getattr(ctx, 'invoke_model', None)), 'Actual SDK/local-provider invocation is required to prove quota deduction')
    session = clients(ctx)
    invocation = ctx.invoke_model('inspector', scenario['model'])
    require(isinstance(invocation, dict) and invocation.get('runId'), 'Actual model run linkage is absent')
    current = mine(session['inspector'], scenario['model'])
    require(current['spentTokens'] > scenario['beforeSpent'] and current['reservedTokens'] == 0
            and current['totalTokens'] == scenario['amount']
            and current['availableTokens'] == scenario['amount'] - current['spentTokens'],
            'Actual completed model usage did not deduct and release the personal quota')
    owner = ctx.accounts['inspector']['userId']
    ledger = ctx.db.one("SELECT JSON_OBJECT('n',COUNT(u.id),'spent',COALESCE(SUM(u.spent_delta),0),"
        "'reserved',COALESCE(SUM(u.reserved_delta),0)) FROM llm_quota q JOIN llm_usage u ON u.account_id=q.id "
        "WHERE q.scope_type='USER' AND q.owner_user_id=" + str(owner) + ' AND q.model_id=' + ctx.db.literal(scenario['model']) + ";")
    require(ledger['n'] > 1 and ledger['spent'] == current['spentTokens'] and ledger['reserved'] == 0,
            'Visible deducted quota differs from its durable original ledger entries')
    run = ctx.db.one("SELECT JSON_OBJECT('n',COUNT(*)) FROM agent_run WHERE run_id=" + ctx.db.literal(invocation['runId'])
        + ' AND user_id=' + str(owner) + " AND status='COMPLETED';")
    require(run['n'] == 1, 'Quota consumption is not linked to the actual completed owner run')
    fallback = ctx.invoke_model('peer', scenario['model'])
    peer = mine(session['peer'], scenario['model'])
    require(isinstance(fallback, dict) and fallback.get('runId') and peer['configured'] is True
            and peer['hasPersonalQuota'] is False and peer['availableTokens'] is None,
            'An existing model user without a personal quota lost the ability to execute')
    fallback_run = ctx.db.one("SELECT JSON_OBJECT('n',COUNT(*)) FROM agent_run WHERE run_id="
        + ctx.db.literal(fallback['runId']) + ' AND user_id=' + str(ctx.accounts['peer']['userId']) + " AND status='COMPLETED';")
    require(fallback_run['n'] == 1, 'No-quota fallback lacks its actual completed SDK run')
    return ctx.record('model-quota-workflow', {'applicationId': scenario['applicationId'], 'approvedTokens': scenario['amount'],
        'spentTokens': current['spentTokens'], 'availableTokens': current['availableTokens'],
        'ledgerEntries': ledger['n'], 'runId': invocation['runId'], 'peerChangesDenied': True,
        'existingAccessWithoutPersonalQuotaRetained': True, 'fallbackRunId': fallback['runId']})


def run_report_scenario(ctx):
    require(isinstance(getattr(ctx, 'report_task_id', None), str)
            and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', ctx.report_task_id)
            and callable(getattr(ctx, 'create_report_draft', None)),
            'Actual worker-completed task and actual SDK-origin draft callback are required')
    session = clients(ctx); task_id = ctx.report_task_id
    task = request(session['inspector'], 'GET', '/api/detection/tasks/' + task_id)
    require(task['status'] == 'COMPLETED' and task['totalImages'] > 0 and task['failedImages'] == 0
            and task['successfulImages'] == task['processedImages'] == task['totalImages'],
            'Report approval cannot use fabricated or unfinished inference facts')
    request(session['peer'], 'GET', '/api/detection/tasks/' + task_id, denied=(403, 404))
    if task.get('reviewStatus') != 'REVIEWED':
        count = task.get('defectCount') or 0
        task = request(session['supervisor'], 'POST', '/api/detection/tasks/' + task_id + '/review', {
            'reviewConclusion': 'CONFIRMED_DEFECT' if count else 'PASS', 'severityLevel': 'MEDIUM',
            'confirmedDefectCount': count, 'falsePositiveCount': 0, 'reviewRemark': '本轮真实检测结果人工复核验收'})
    require(task.get('reviewStatus') == 'REVIEWED', 'Actual review mutation did not complete')
    draft = ctx.create_report_draft('inspector', task_id, '隔离运行报告 ' + ctx.token, '候选SDK保存真实检测任务的私人草稿')
    report_id = draft['reportId'] if isinstance(draft, dict) else draft
    require(isinstance(report_id, str) and re.fullmatch(r'qr-[a-f0-9-]{36}', report_id), 'Actual SDK draft report identifier is absent')
    base = '/api/detection/reports/' + report_id
    report = request(session['inspector'], 'GET', base)
    require(report['status'] == 'DRAFT' and report['taskId'] == task_id
            and report['ownerUserId'] == ctx.accounts['inspector']['userId'], 'SDK draft has another owner or source')
    origins = ctx.db.query("SELECT JSON_OBJECT('run_id',run_id,'payload_json',payload_json) FROM workflow_instance WHERE kind='REPORT_AGENT_ORIGIN' "
        "AND resource_type='QUALITY_REPORT' AND resource_id=" + ctx.db.literal(report_id) + ' AND actor_user_id='
        + str(ctx.accounts['inspector']['userId']) + ';')
    require(origins and all(row['run_id'] for row in origins), 'SDK draft lacks durable run/call/tool provenance')
    origin_runs = {origin['run_id'] for origin in origins}
    actual_runs = ctx.db.one("SELECT JSON_OBJECT('n',COUNT(*)) FROM agent_run WHERE run_id IN ("
        + ','.join(ctx.db.literal(run_id) for run_id in sorted(origin_runs)) + ') AND user_id='
        + str(ctx.accounts['inspector']['userId']) + " AND status='COMPLETED';")
    require(actual_runs['n'] == len(origin_runs), 'Draft origin is not linked to completed actual owner SDK runs')
    audit = request(session['inspector'], 'GET', base + '/audit')
    require(any(row.get('runId') in {origin['run_id'] for origin in origins}
                and row.get('callId') and row.get('toolName') == 'create_report_draft' for row in audit),
            'Report audit does not preserve the actual SDK origin')
    for key in ('peer', 'supervisor'):
        request(session[key], 'GET', base, denied=(404,))
    edit = {'expectedVersion': report['version'], 'title': '人工补充报告 ' + ctx.token,
            'narrative': '本人检查并补充候选SDK报告草稿，交由其他主管独立审批', 'requestId': 'report-edit-' + ctx.token}
    report = request(session['inspector'], 'PUT', base, edit)
    require(report['status'] == 'DRAFT' and report['version'] == edit['expectedVersion'] + 1, 'Owner edit did not advance the exact draft version')
    request(session['peer'], 'PUT', base, edit, denied=(403, 404))
    request(session['inspector'], 'POST', base + '/export?format=md', denied=(409,))
    submit = {'expectedVersion': report['version'], 'requestId': 'report-submit-' + ctx.token}
    report = request(session['inspector'], 'POST', base + '/submit', submit)
    require(report['status'] == 'SUBMITTED' and re.fullmatch(r'[a-f0-9]{64}', report['snapshotSha256']), 'Submit did not freeze the original report snapshot')
    preview_body = {'expectedVersion': report['version'], 'decision': 'APPROVE', 'reason': '独立主管核实真实检测和复核依据'}
    request(session['inspector'], 'POST', base + '/decision-preview', preview_body, denied=(403,))
    preview = request(session['supervisor'], 'POST', base + '/decision-preview', preview_body)
    decision = dict(preview_body, confirmationToken=preview['confirmationToken'], requestId='report-approve-' + ctx.token)
    approved = request(session['supervisor'], 'POST', base + '/decision', decision)
    require(approved['status'] == 'APPROVED' and approved['deciderUsername'] == ctx.accounts['supervisor']['username']
            and approved['snapshotSha256'] == report['snapshotSha256'], 'Independent approval changed or bypassed the frozen source')
    require(request(session['supervisor'], 'POST', base + '/decision', decision)['version'] == approved['version'],
            'Repeated approval changed the report version')
    request(session['peer'], 'GET', base, denied=(404,))
    exported = request(session['inspector'], 'POST', base + '/export?format=md')
    require(isinstance(exported, bytes) and report_id.encode() in exported
            and approved['snapshotSha256'].encode() in exported, 'Approved export lacks its exact report and snapshot')
    deadline = time.monotonic() + 90
    while True:
        events = request(session['supervisor'], 'GET', base + '/events')
        if len(events) >= 2 and all(event['deliveryStatus'] == 'DELIVERED' and event.get('consumedAt') for event in events):
            break
        require(time.monotonic() < deadline, 'Actual report outbox/Kafka/inbox delivery did not finish')
        time.sleep(1)
    request(session['peer'], 'POST', base + '/events/' + events[0]['eventId'] + '/retry', {
        'expectedAttempts': events[0]['attempts'], 'confirmed': True, 'requestId': 'report-peer-retry-' + ctx.token}, denied=(403, 404))
    require(request(session['inspector'], 'GET', base)['version'] == approved['version'],
            'An unauthorized retry changed the approved report version')
    final_audit = request(session['inspector'], 'GET', base + '/audit')
    require({'CREATE', 'EDIT', 'SUBMIT', 'APPROVE', 'EXPORT'} <= {entry['action'] for entry in final_audit}
            and any(entry.get('runId') in origin_runs and entry.get('callId')
                    and entry.get('toolName') == 'create_report_draft' for entry in final_audit),
            'Completed workflow lost its original SDK audit linkage or lifecycle actions')
    receipts = ctx.db.one("SELECT JSON_OBJECT('n',COUNT(*)) FROM workflow_instance WHERE kind='FILE_DELIVERY' "
        "AND actor_user_id=" + str(ctx.accounts['inspector']['userId']) + " AND file_delivery_domain='QUALITY_REPORT' "
        "AND resource_type='FILE_DELIVERY' AND resource_id=" + ctx.db.literal(report_id) + " AND status='SERVER_COMPLETED';")
    require(receipts['n'] >= 1, 'Actual report download lacks its completed file delivery receipt')
    return ctx.record('report-draft-review-export-delivery', {'taskId': task_id, 'reportId': report_id,
        'sdkOriginRuns': sorted({origin['run_id'] for origin in origins}), 'approvedVersion': approved['version'],
        'snapshotSha256': approved['snapshotSha256'], 'exportSha256': hashlib.sha256(exported).hexdigest(),
        'eventsDeliveredAndConsumed': len(events), 'fileDeliveryReceipts': receipts['n'], 'peerAccessAndRetryDenied': True})
