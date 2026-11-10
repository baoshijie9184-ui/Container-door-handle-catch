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
