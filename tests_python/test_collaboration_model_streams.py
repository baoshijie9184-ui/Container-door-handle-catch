"""ECS-only regressions; local development compiles source and never runs these.

Transport tests use owned loopback sockets and synthetic credentials, without
external providers. They verify fixture framing, not replace the actual browser
AGUI/device-save acceptance or the full migration/runtime gates.
"""
from contextlib import contextmanager
import asyncio
import copy
import hashlib
import http.client
from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'script/docker' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = load('a21_model_fixture', 'compact-model-fixture.py')
probes = load('a21_stream_probes', 'compact-collaboration-stream-probes.py')
browser = load('a21_browser', 'collaboration-browser-runner.py')
proxy = load('a21_proxy', 'collaboration-browser-proxy.py')
MARKERS = ['a21-stream-' + value * 24 for value in ('a', 'b')]


@pytest.mark.parametrize('value', [7, 9007199254740991, '9007199254740993', '9223372036854775807'])
def test_browser_preserves_existing_numeric_and_exact_string_execution_reply_ids(value):
    assert browser.model_reply_id(value) == str(value)


@pytest.mark.parametrize('value', [None, True, 7.0, 0, -1, 9007199254740992, '', '0', '01', '1.0', '-1', '9223372036854775808'])
def test_browser_rejects_missing_noncanonical_and_rounded_execution_reply_ids(value):
    code = ('model_reply_identity_outside_signed_range' if value == '9223372036854775808'
            else 'model_reply_identity_must_be_lossless')
    with pytest.raises(browser.CheckError) as rejected:
        browser.model_reply_id(value)
    assert rejected.value.args == (code,)
TOKEN = 'owned-private-runtime-token'


def spec():
    return {'schemaVersion': 1, 'kind': probes.KIND, 'modelId': 'deepseek:runtime-scripted',
        'streamDelayMillis': 15000, 'saveMaxMillis': 2000, 'completionTimeoutMillis': 45000,
        'markers': list(MARKERS)}


def arm(scripts, marker=MARKERS[0], delay=0):
    return scripts.arm({'marker': marker, 'steps': [{'text': 'content ' + marker, 'streamDelayMillis': delay}]})


@pytest.mark.parametrize('delay', [-1, 15001, True, False, 1.0, '1', None])
def test_armed_delay_rejects_non_integer_or_out_of_bound(delay):
    with pytest.raises(ValueError):
        arm(fixture.Scripts(), delay=delay)


@pytest.mark.parametrize('delay', [0, 1, 15000])
def test_armed_delay_accepts_bounded_integers(delay):
    scripts = fixture.Scripts()
    arm(scripts, delay=delay)
    assert scripts.next({'messages': [{'content': MARKERS[0]}]})['streamDelayMillis'] == delay


def test_delayed_tool_step_rejected():
    with pytest.raises(ValueError):
        fixture.Scripts().arm({'marker': MARKERS[0], 'steps': [{'tool': 'read_device', 'streamDelayMillis': 1}]})


def test_arm_checksum_binds_delay_and_rearm_does_not_reset_cursor():
    scripts = fixture.Scripts()
    original = arm(scripts, delay=100)
    scripts.next({'messages': [{'content': MARKERS[0]}]})
    assert arm(scripts, delay=100) == original
    assert scripts.state()['markers'][0]['remainingSteps'] == 0
    with pytest.raises(ValueError):
        arm(scripts, delay=101)


def test_provider_body_cannot_inject_unarmed_delay():
    scripts = fixture.Scripts()
    scripts.arm({'marker': MARKERS[0], 'steps': [{'text': 'owned content'}]})
    value = scripts.next({'messages': [{'content': MARKERS[0]}], 'streamDelayMillis': 15000})
    assert value == {'text': 'owned content'}


class Owner:
    def __init__(self, failure=None):
        self.owner, self.token, self.model_id = {}, TOKEN, 'deepseek:runtime-scripted'
        self.fixture_scripts, self.snapshots, self.calls = fixture.Scripts(), [], []
        self.failure = failure

    def save(self):
        self.snapshots.append(copy.deepcopy(self.owner))

    def fixture(self, method, path, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        assert method == 'POST' and path == '/__fixture/arm'
        if self.failure == 'second' and len(self.calls) == 2:
            raise TimeoutError('unknown remote outcome')
        result = self.fixture_scripts.arm(body)
        if self.failure == 'checksum':
            result['scriptSha256'] = '0' * 64
        return result


def test_controller_arms_exact_two_scripts_and_journals_before_remote_side_effect():
    owner = Owner()
    descriptor = probes.arm_model_stream_probes(owner)
    assert owner.snapshots[0]['modelStreamProbes']['phase'] == 'ARMING'
    assert owner.snapshots[0]['modelStreamProbes']['armed'] == []
    assert owner.owner['modelStreamProbes']['phase'] == 'ARMED'
    assert len(owner.calls) == 2 and len(owner.owner['modelStreamProbes']['armed']) == 2
    assert owner.token not in json.dumps(descriptor)
    assert owner.token not in json.dumps(owner.calls)
    assert all(call[2]['steps'][0]['streamDelayMillis'] == 15000 for call in owner.calls)
    assert browser.stream_probe_spec({'ownership': {'token': TOKEN}, 'fixtures': {'modelStreamProbes': descriptor}}) == descriptor


@pytest.mark.parametrize('phase', ['ARMING', 'ARMED'])
def test_controller_refuses_rearming_known_or_unknown_attempt(phase):
    owner = Owner()
    owner.owner['modelStreamProbes'] = {'phase': phase}
    with pytest.raises(ValueError):
        probes.arm_model_stream_probes(owner)
    assert owner.calls == []


@pytest.mark.parametrize('failure', ['second', 'checksum'])
def test_partial_arm_or_unverified_reply_remains_fail_closed(failure):
    owner = Owner(failure)
    with pytest.raises((TimeoutError, ValueError)):
        probes.arm_model_stream_probes(owner)
    assert owner.owner['modelStreamProbes']['phase'] == 'ARMING'
    with pytest.raises(ValueError):
        probes.arm_model_stream_probes(owner)


def final_state():
    value = spec()
    rows = []
    for marker in MARKERS:
        checksum = hashlib.sha256(fixture.encoded(probes.script(value, marker))).hexdigest()
        rows.append({'marker': marker, 'armedSteps': 1, 'remainingSteps': 0, 'calls': 1, 'toolCalls': 0,
            'scriptSha256': checksum, 'streamResponses': 1, 'streamFirstChunks': 1, 'streamFinishes': 1,
            'activeStreams': 0, 'streamDelayMillisObserved': 15000})
    return {'kind': 'doorhandle-owned-scripted-model', 'markers': rows}


def test_final_state_requires_actual_once_consumed_finished_provider_streams():
    result = probes.verify_model_stream_probes(spec(), final_state())
    assert result['status'] == 'PASS' and len(result['streams']) == 2


@pytest.mark.parametrize('key,value', [('remainingSteps', 1), ('calls', 0), ('calls', 2), ('toolCalls', 1),
    ('streamResponses', 0), ('streamFirstChunks', 0), ('streamFinishes', 0), ('activeStreams', 1),
    ('streamDelayMillisObserved', 14999), ('scriptSha256', '0' * 64)])
def test_final_state_rejects_incomplete_extra_or_different_real_consumption(key, value):
    state = final_state()
    state['markers'][0][key] = value
    with pytest.raises(ValueError):
        probes.verify_model_stream_probes(spec(), state)


@pytest.mark.parametrize('mutation', ['missing', 'duplicate'])
def test_final_state_rejects_missing_or_ambiguous_marker(mutation):
    state = final_state()
    state['markers'] = state['markers'][1:] if mutation == 'missing' else state['markers'] + [state['markers'][0]]
    with pytest.raises(ValueError):
        probes.verify_model_stream_probes(spec(), state)


@pytest.mark.parametrize('key,value', [('streamDelayMillis', 15001), ('streamDelayMillis', True),
    ('saveMaxMillis', 3000), ('completionTimeoutMillis', 0), ('markers', MARKERS[:1]),
    ('markers', [MARKERS[0], MARKERS[0]]), ('modelId', 'https://paid.invalid/model')])
def test_browser_and_controller_reject_invalid_probe_protocol(key, value):
    descriptor = spec()
    descriptor[key] = value
    with pytest.raises(ValueError):
        probes.validate_spec(descriptor, TOKEN)
    with pytest.raises(browser.CheckError):
        browser.stream_probe_spec({'ownership': {'token': TOKEN}, 'fixtures': {'modelStreamProbes': descriptor}})


@contextmanager
def actual_provider():
    class Handler(fixture.Handler):
        scripts = fixture.Scripts()
        token = '1' * 64
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, Handler.scripts
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def open_stream(port, marker):
    client = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    client.request('POST', '/v1/chat/completions', fixture.encoded({'model': 'runtime-scripted', 'stream': True,
        'messages': [{'role': 'user', 'content': marker}], 'stream_options': {'include_usage': True}}),
        {'Content-Type': 'application/json', 'Authorization': 'Bearer runtime-fixture'})
    response = client.getresponse()
    assert response.status == 200 and response.getheader('Content-Type') == 'text/event-stream'
    while True:
        line = response.readline()
        assert line
        if line.startswith(b'data:') and b'"content"' in line:
            assert marker.encode() in line
            return client, response


def test_actual_provider_flushes_two_contents_before_finish_without_holding_queue_lock():
    with actual_provider() as (port, scripts):
        for marker in MARKERS:
            arm(scripts, marker, delay=1500)
        clients = []
        try:
            for marker in MARKERS:
                clients.append(open_stream(port, marker))
            active = scripts.state()['markers']
            assert all(row['activeStreams'] == 1 and row['streamFirstChunks'] == 1
                and row['streamFinishes'] == 0 and row['remainingSteps'] == 0 for row in active)
            for _client, response in clients:
                tail = response.read()
                assert b'"finish_reason":"stop"' in tail and b'"usage"' in tail and tail.endswith(b'data: [DONE]\n\n')
            deadline = time.monotonic() + 2
            while any(row['activeStreams'] for row in scripts.state()['markers']) and time.monotonic() < deadline:
                time.sleep(.01)
            assert all(row['activeStreams'] == 0 and row['streamFinishes'] == 1
                and row['streamDelayMillisObserved'] >= 1500 for row in scripts.state()['markers'])
        finally:
            for client, _response in clients:
                client.close()


def test_proxy_cannot_gate_model_response_to_manufacture_concurrency():
    transport = proxy.LoopbackProxy()
    try:
        with pytest.raises(ValueError):
            transport.pause_next_response('POST', '/agui/run')
        assert transport.snapshot()['modelActive'] == 0
        assert transport.snapshot()['modelCompleted'] == 0
    finally:
        transport.server.server_close()


def persistence_report():
    return {'status': 'PASS', 'accounts': {'supervisor': {'userId': '9007199254740993'}}, 'checks': {
        'model-stream-save-connection-budget': {'status': 'PASS', 'modelId': spec()['modelId'], 'actualAgentStreams': [
            {'marker': marker, 'runId': str(index) * 8 + '-aaaa-bbbb-cccc-' + str(index) * 12,
             'sessionId': 'owned-stream-session-' + str(index), 'messageId': str(9007199254741000 + index),
             'firstContent': True, 'finishedEvent': True, 'done': True, 'error': False}
            for index, marker in enumerate(MARKERS, 1)]}}}


class PersistenceDb:
    def __init__(self):
        owner, streams = persistence_report()['accounts']['supervisor']['userId'], persistence_report()['checks'][
            'model-stream-save-connection-budget']['actualAgentStreams']
        self.calls, self.rows = [], []
        for index, stream in enumerate(streams, 1):
            body = 'Owned stream content ' + stream['marker']
            self.rows.append([{**{key: stream[key] for key in ('runId', 'sessionId', 'messageId')},
                'ownerUserId': owner, 'runStatus': 'COMPLETED', 'entryPoint': 'AGUI', 'modelId': spec()['modelId'],
                'runEnded': 1, 'sessionOwnerUserId': owner, 'messageSessionId': stream['sessionId'],
                'messageRole': 'assistant', 'messageType': 'TEXT', 'executionRunId': stream['runId'],
                'executionOwnerUserId': owner, 'executionEvidenceId': str(800 + index),
                'assistantRowsForRun': 1, 'sessionAssistantRows': 1, 'markerAssistantRows': 1,
                'markerOccurrences': 1, 'otherMarkerOccurrences': 0, 'contentSha256': hashlib.sha256(body.encode()).hexdigest(),
                'contentBytes': len(body.encode()), 'executionEvidenceRows': 1, 'executionEvidenceMatched': 1}])

    @staticmethod
    def literal(value):
        return "'" + value.replace("'", "''") + "'"

    def query(self, sql):
        # The production adapter exposes the same query() shape; this fixture
        # does not execute SQL or claim to be actual database acceptance.
        assert sql.startswith('SELECT JSON_OBJECT(') and sql.count(';') == 1 and sql.endswith(';')
        self.calls.append(sql)
        return copy.deepcopy(self.rows[len(self.calls) - 1])


def persistence_owner():
    return SimpleNamespace(token=TOKEN, accounts={'supervisor': {'userId': 9007199254740993}}, db=PersistenceDb())


def test_persisted_model_streams_match_the_actual_assistant_ids_without_returning_plaintext():
    owner = persistence_owner()
    result = probes.verify_persisted_model_streams(owner, spec(), persistence_report())
    assert result['kind'] == probes.PERSISTENCE_KIND and result['status'] == 'PASS'
    assert result['ownerUserId'] == '9007199254740993' and result['actualAssistantRows'] == 2
    assert len(owner.db.calls) == 2 and len(result['streams']) == 2
    assert all(row['messageId'] == expected['messageId'] and row['markerOccurrences'] == 1
        and row['executionEvidenceMatched'] is True for row, expected in zip(result['streams'],
            persistence_report()['checks']['model-stream-save-connection-budget']['actualAgentStreams']))
    assert 'Owned stream content ' not in json.dumps(result) and TOKEN not in json.dumps(result)
    assert all('JOIN chat_message m ON m.id=' in sql and "e.kind='MESSAGE_EXECUTION'" in sql for sql in owner.db.calls)


@pytest.mark.parametrize('key,value', [
    ('runId', 'a' * 36), ('ownerUserId', '99'), ('runStatus', 'INTERRUPTED'), ('entryPoint', 'CHAT'),
    ('modelId', 'other-model'), ('runEnded', 0), ('sessionOwnerUserId', '99'), ('messageId', '2'),
    ('messageSessionId', 'other-session'), ('messageRole', 'user'), ('messageType', 'AGENT_CARDS'),
    ('executionRunId', 'other-run'), ('executionOwnerUserId', '99'), ('assistantRowsForRun', 0),
    ('assistantRowsForRun', 2), ('sessionAssistantRows', 2), ('markerAssistantRows', 0),
    ('markerOccurrences', 2), ('markerOccurrences', True), ('otherMarkerOccurrences', 1),
    ('executionEvidenceId', None), ('executionEvidenceRows', 0), ('executionEvidenceRows', 2),
    ('executionEvidenceMatched', 0), ('contentSha256', None), ('contentBytes', 0), ('contentBytes', 2097153)])
def test_persisted_model_streams_reject_wrong_identity_links_content_or_ambiguous_evidence(key, value):
    owner = persistence_owner(); owner.db.rows[0][0][key] = value
    with pytest.raises(ValueError):
        probes.verify_persisted_model_streams(owner, spec(), persistence_report())


@pytest.mark.parametrize('shape', ['missing', 'duplicate'])
def test_completed_http_stream_cannot_replace_a_missing_or_ambiguous_actual_database_row(shape):
    owner = persistence_owner(); owner.db.rows[0] = [] if shape == 'missing' else owner.db.rows[0] * 2
    with pytest.raises(ValueError):
        probes.verify_persisted_model_streams(owner, spec(), persistence_report())


@pytest.mark.parametrize('damage', ['failed-check', 'other-owner', 'duplicate-session', 'duplicate-run',
    'duplicate-message', 'unfinished', 'stream-error', 'input-message-uuid', 'lossy-number-id', 'other-marker'])
def test_bad_browser_stream_identifiers_never_become_database_completion_evidence(damage):
    owner, report = persistence_owner(), persistence_report()
    check = report['checks']['model-stream-save-connection-budget']; first, second = check['actualAgentStreams']
    if damage == 'failed-check': check['status'] = 'FAIL'
    elif damage == 'other-owner': report['accounts']['supervisor']['userId'] = '99'
    elif damage == 'duplicate-session': second['sessionId'] = first['sessionId']
    elif damage == 'duplicate-run': second['runId'] = first['runId']
    elif damage == 'duplicate-message': second['messageId'] = first['messageId']
    elif damage == 'unfinished': first['done'] = False
    elif damage == 'stream-error': first['error'] = True
    elif damage == 'input-message-uuid': first['messageId'] = '11111111-aaaa-bbbb-cccc-111111111111'
    elif damage == 'lossy-number-id': first['messageId'] = 9007199254741000
    else: second['marker'] = first['marker']
    with pytest.raises(ValueError):
        probes.verify_persisted_model_streams(owner, spec(), report)


def test_actual_browser_model_selection_adapter_preserves_guard_origin_context_and_body():
    calls = []
    class Response:
        status = 200
        async def json(self):
            return {'code': 200, 'data': {'modelId': spec()['modelId'], 'revision': '3'}}
    class Request:
        async def fetch(self, url, **options):
            calls.append((url, options)); return Response()
    subject = SimpleNamespace(base='http://127.0.0.1:18080', auth={'supervisor': {'accountContext': 'A' * 43}})
    body = {'modelId': spec()['modelId'], 'revision': '2', 'requestId': 'actual-command-id'}
    result = asyncio.run(browser.Runner.api(subject, SimpleNamespace(request=Request()), 'POST',
        '/api/agent/conversations/owned-stream-session/model-selection', body, auth_key='supervisor'))
    assert result['revision'] == '3'
    assert calls == [('http://127.0.0.1:18080/api/agent/conversations/owned-stream-session/model-selection', {
        'method': 'POST', 'data': body, 'headers': {'Origin': subject.base,
            'X-Account-Context': 'A' * 43, 'X-Agent-Action': 'workbench'}, 'timeout': 30000})]
