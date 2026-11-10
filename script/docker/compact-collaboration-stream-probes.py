#!/usr/bin/env python3
"""Privately arm two bounded, owned provider responses for actual browser runs.

The returned descriptor contains public markers, never the fixture admin key or
the runtime ownership token. Unknown/partial arming is retained for investigation
and cannot silently rearm a different script.
"""
import hashlib
import json
import re
import secrets


KIND = 'doorhandle-owned-model-stream-probes'
PERSISTENCE_KIND = 'doorhandle-owned-model-stream-persistence'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_spec(spec, ownership_token=''):
    require(isinstance(spec, dict) and set(spec) == {'schemaVersion', 'kind', 'modelId',
        'streamDelayMillis', 'saveMaxMillis', 'completionTimeoutMillis', 'markers'}, 'Invalid model stream descriptor')
    require(spec['schemaVersion'] == 1 and spec['kind'] == KIND, 'Invalid model stream descriptor version')
    require(isinstance(spec['modelId'], str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', spec['modelId']), 'Invalid owned model identifier')
    require(type(spec['streamDelayMillis']) is int and spec['streamDelayMillis'] == 15000,
            'Model stream evidence needs the fixed bounded delay')
    require(type(spec['saveMaxMillis']) is int and spec['saveMaxMillis'] == 2000
            and type(spec['completionTimeoutMillis']) is int and spec['completionTimeoutMillis'] == 45000,
            'Invalid model stream evidence timing budget')
    require(isinstance(spec['markers'], list) and len(spec['markers']) == 2
            and all(isinstance(value, str) and re.fullmatch(r'a21-stream-[a-f0-9]{24}', value) for value in spec['markers'])
            and len(set(spec['markers'])) == 2, 'Two distinct model stream markers required')
    require(not ownership_token or all(ownership_token not in marker for marker in spec['markers']), 'Ownership token in model stream marker')
    return spec


def script(spec, marker):
    return [{'text': 'Owned stream content ' + marker, 'streamDelayMillis': spec['streamDelayMillis']}]


def arm_model_stream_probes(ctx):
    require('modelStreamProbes' not in ctx.owner, 'Model stream arming already attempted; inspect retained evidence')
    require(isinstance(ctx.token, str) and len(ctx.token) >= 8, 'Owned runtime token required')
    markers = []
    while len(markers) < 2:
        value = 'a21-stream-' + secrets.token_hex(12)
        if ctx.token not in value and value not in markers:
            markers.append(value)
    spec = validate_spec({'schemaVersion': 1, 'kind': KIND, 'modelId': ctx.model_id,
        'streamDelayMillis': 15000, 'saveMaxMillis': 2000, 'completionTimeoutMillis': 45000, 'markers': markers}, ctx.token)
    ctx.owner['modelStreamProbes'] = {'phase': 'ARMING', 'descriptor': spec, 'armed': []}
    ctx.save()
    for marker in markers:
        steps = script(spec, marker)
        checksum = hashlib.sha256(json.dumps(steps, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8')).hexdigest()
        actual = ctx.fixture('POST', '/__fixture/arm', {'marker': marker, 'steps': steps})
        require(isinstance(actual, dict) and actual.get('armed') is True and actual.get('marker') == marker
                and actual.get('stepCount') == 1 and actual.get('scriptSha256') == checksum,
                'Model fixture did not acknowledge the exact bounded script')
        ctx.owner['modelStreamProbes']['armed'].append({'marker': marker, 'scriptSha256': checksum})
        ctx.save()
    ctx.owner['modelStreamProbes']['phase'] = 'ARMED'
    ctx.save()
    return spec


def verify_model_stream_probes(spec, state):
    validate_spec(spec)
    require(isinstance(state, dict) and state.get('kind') == 'doorhandle-owned-scripted-model'
            and isinstance(state.get('markers'), list), 'Actual final fixture state required')
    proof = []
    for marker in spec['markers']:
        found = [item for item in state['markers'] if item.get('marker') == marker]
        require(len(found) == 1, 'Actual stream marker evidence is missing or ambiguous')
        row = found[0]
        require(all(type(row.get(key)) is int and row[key] == value for key, value in {
            'armedSteps': 1, 'remainingSteps': 0, 'calls': 1, 'toolCalls': 0, 'streamResponses': 1,
            'streamFirstChunks': 1, 'streamFinishes': 1, 'activeStreams': 0}.items()),
            'Both actual model streams must consume and finish exactly once')
        expected = hashlib.sha256(json.dumps(script(spec, marker), ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode('utf8')).hexdigest()
        require(row.get('scriptSha256') == expected and type(row.get('streamDelayMillisObserved')) is int
                and row['streamDelayMillisObserved'] >= spec['streamDelayMillis'], 'Actual provider delay proof differs')
        proof.append({key: row[key] for key in ('marker', 'scriptSha256', 'calls', 'streamFirstChunks',
            'streamFinishes', 'activeStreams', 'streamDelayMillisObserved')})
    return {'kind': KIND, 'status': 'PASS', 'streams': proof}


def _positive_id(value, *, browser=False):
    require(type(value) is int or isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,18}', value),
            'Actual model stream identity must be an exact positive integer')
    require(1 <= int(value) <= 9223372036854775807
            and (not browser or type(value) is not int or value <= 9007199254740991),
            'Actual model stream identity is outside its lossless range')
    return str(value)


def verify_persisted_model_streams(ctx, spec, browser_report):
    """Read actual owned MySQL facts; never manufacture runs, replies or links.

    execution.v1.messageId is AgentScopeChatServiceImpl's saved assistant PK.
    It is different from the browser's input-message UUID and its transient
    TEXT_MESSAGE_START reply UUID. SQL computes content counts/hashes so no
    assistant or question text is returned to the controller or public proof.
    """
    validate_spec(spec, ctx.token)
    owner = _positive_id(ctx.accounts['supervisor']['userId'])
    require(isinstance(browser_report, dict) and browser_report.get('status') == 'PASS',
            'Actual passing browser report is required for persisted model streams')
    require(_positive_id(browser_report.get('accounts', {}).get('supervisor', {}).get('userId')) == owner,
            'Browser model owner differs from the owned supervisor')
    check = browser_report.get('checks', {}).get('model-stream-save-connection-budget', {})
    require(check.get('status') == 'PASS' and check.get('modelId') == spec['modelId'],
            'Actual passing model stream check is required')
    streams = check.get('actualAgentStreams')
    require(isinstance(streams, list) and len(streams) == 2 and all(isinstance(row, dict) for row in streams)
            and {row.get('marker') for row in streams} == set(spec['markers']),
            'Both distinct actual browser model streams must be present')
    seen_runs, seen_sessions, seen_messages, proof = set(), set(), set(), []
    for marker in spec['markers']:
        stream = next(row for row in streams if row['marker'] == marker)
        run, session = stream.get('runId'), stream.get('sessionId')
        message = _positive_id(stream.get('messageId'), browser=True)
        require(isinstance(run, str) and re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', run)
                and isinstance(session, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', session)
                and run not in seen_runs and session not in seen_sessions and message not in seen_messages,
                'Model streams must have distinct actual run, session and assistant identities')
        require(all(stream.get(key) is True for key in ('firstContent', 'finishedEvent', 'done'))
                and stream.get('error') is False, 'Only successfully finished actual streams may be persisted evidence')
        seen_runs.add(run); seen_sessions.add(session); seen_messages.add(message)
        other_marker = next(value for value in spec['markers'] if value != marker)
        q = ctx.db.literal
        marker_sql, other_sql = q(marker), q(other_marker)
        # All dynamic values are validated identities or escaped literal values;
        # column/table names are fixed, and the only database operation is SELECT.
        rows = ctx.db.query("SELECT JSON_OBJECT('runId',r.run_id,'sessionId',r.session_id,'ownerUserId',CAST(r.user_id AS CHAR),"
            "'runStatus',r.status,'entryPoint',r.entry_point,'modelId',r.default_model,'runEnded',r.ended_at IS NOT NULL,"
            "'sessionOwnerUserId',CAST(s.user_id AS CHAR),'messageId',CAST(m.id AS CHAR),'messageSessionId',m.session_id,"
            "'messageRole',m.role,'messageType',m.message_type,'executionRunId',m.execution_run_id,"
            "'executionOwnerUserId',CAST(m.execution_owner_user_id AS CHAR),'executionEvidenceId',CAST(m.execution_evidence_id AS CHAR),"
            "'assistantRowsForRun',(SELECT COUNT(*) FROM chat_message a WHERE BINARY a.execution_run_id=BINARY r.run_id),"
            "'sessionAssistantRows',(SELECT COUNT(*) FROM chat_message a WHERE BINARY a.session_id=BINARY r.session_id AND BINARY a.role=BINARY 'assistant'),"
            "'markerAssistantRows',(SELECT COUNT(*) FROM chat_message a WHERE BINARY a.session_id=BINARY r.session_id AND BINARY a.role=BINARY 'assistant' AND LOCATE(BINARY "
            + marker_sql + ",BINARY a.content)>0),'markerOccurrences',(OCTET_LENGTH(m.content)-OCTET_LENGTH(REPLACE(m.content,"
            + marker_sql + ",''))) DIV OCTET_LENGTH(" + marker_sql + "),'otherMarkerOccurrences',LOCATE(BINARY "
            + other_sql + ",BINARY m.content)>0,'contentSha256',LOWER(SHA2(m.content,256)),'contentBytes',OCTET_LENGTH(m.content),"
            "'executionEvidenceRows',(SELECT COUNT(*) FROM audit_event a WHERE a.kind='MESSAGE_EXECUTION' AND (a.message_id=m.id OR BINARY a.run_id=BINARY r.run_id)),"
            "'executionEvidenceMatched',(e.kind='MESSAGE_EXECUTION' AND e.owner_user_id=r.user_id AND e.message_id=m.id "
            "AND BINARY e.session_id=BINARY r.session_id AND BINARY e.run_id=BINARY r.run_id AND e.resource_type='CHAT_MESSAGE' "
            "AND BINARY e.resource_id=BINARY CAST(m.id AS CHAR) AND e.action='RECORDED' AND e.payload_version=1 "
            "AND e.actor_user_id IS NULL AND e.occurred_at IS NOT NULL AND e.legacy_source IS NULL AND e.legacy_clock_json IS NULL "
            "AND BINARY e.content_sha256=BINARY LOWER(SHA2(e.payload_json,256)) AND m.execution_created_at IS NOT NULL AND m.execution_legacy_id IS NULL)) "
            "FROM agent_run r JOIN chat_session s ON BINARY s.session_id=BINARY r.session_id "
            "JOIN chat_message m ON m.id=" + message + " LEFT JOIN audit_event e ON e.id=m.execution_evidence_id "
            "WHERE BINARY r.run_id=BINARY " + q(run) + " AND BINARY r.session_id=BINARY " + q(session) + " AND r.user_id=" + owner + ';')
        require(isinstance(rows, list) and len(rows) == 1, 'Actual model run and assistant row are missing or ambiguous')
        row = rows[0]
        require(all(row.get(key) == expected for key, expected in {
            'runId': run, 'sessionId': session, 'ownerUserId': owner, 'runStatus': 'COMPLETED',
            'entryPoint': 'AGUI', 'modelId': spec['modelId'], 'sessionOwnerUserId': owner,
            'messageId': message, 'messageSessionId': session, 'messageRole': 'assistant', 'messageType': 'TEXT',
            'executionRunId': run, 'executionOwnerUserId': owner}.items()),
            'Persisted model run, owner, session and assistant execution link do not match the actual browser')
        require(all(type(row.get(key)) is int and row[key] == 1 for key in (
            'runEnded', 'assistantRowsForRun', 'sessionAssistantRows', 'markerAssistantRows',
            'executionEvidenceRows', 'executionEvidenceMatched', 'markerOccurrences'))
            and type(row.get('otherMarkerOccurrences')) is int and row['otherMarkerOccurrences'] == 0,
            'Each finished model stream needs exactly one assistant containing only its own marker and original execution evidence')
        require(isinstance(row.get('contentSha256'), str) and re.fullmatch(r'[a-f0-9]{64}', row['contentSha256'])
                and type(row.get('contentBytes')) is int and 1 <= row['contentBytes'] <= 2097152,
                'Persisted assistant content needs a bounded actual byte count and hash')
        evidence = _positive_id(row.get('executionEvidenceId'))
        public = {key: row[key] for key in ('runId', 'sessionId', 'messageId', 'ownerUserId', 'runStatus', 'entryPoint',
            'modelId', 'assistantRowsForRun', 'sessionAssistantRows', 'markerAssistantRows', 'contentSha256',
            'contentBytes', 'executionEvidenceRows')}
        public.update({'marker': marker, 'markerOccurrences': 1,
                'otherMarkerOccurrences': 0, 'executionEvidenceId': evidence, 'ownerAndSessionMatched': True,
                'executionLinkMatched': True, 'executionEvidenceMatched': True})
        proof.append(public)
    return {'kind': PERSISTENCE_KIND, 'status': 'PASS', 'ownerUserId': owner, 'actualAssistantRows': 2, 'streams': proof}
