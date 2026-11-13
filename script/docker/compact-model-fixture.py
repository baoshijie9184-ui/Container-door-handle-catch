#!/usr/bin/env python3
"""Owned local OpenAI-compatible scripted fixture; performs no outbound requests.

The ECS runtime controller alone arms marker queues. Real application/SDK HTTP
clients consume them. Prompts, arguments, authorization values and response text
are never logged or included in the public state endpoint.
"""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
import re
import secrets
import threading
import time


MAX_BODY = 2 * 1024 * 1024
MAX_STREAM_DELAY_MILLIS = 15000
MARKER = re.compile(r'[A-Za-z0-9_.:-]{8,128}')
TOOL = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]{0,127}')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8')


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)


class Scripts:
    def __init__(self):
        self.lock = threading.Lock()
        self.queues = {}
        self.calls = 0
        self.embedding_calls = 0
        self.unmarked_calls = 0

    def arm(self, body):
        require(isinstance(body, dict) and set(body) <= {'marker', 'steps', 'secret'}
                and isinstance(body.get('marker'), str) and MARKER.fullmatch(body['marker'])
                and isinstance(body.get('steps'), list) and 0 < len(body['steps']) <= 128,
                'Invalid marker script')
        steps = []
        for item in body['steps']:
            require(isinstance(item, dict) and set(item) <= {'tool', 'name', 'arguments', 'text', 'streamDelayMillis'}, 'Invalid scripted step')
            delay = item.get('streamDelayMillis', 0)
            require(type(delay) is int and 0 <= delay <= MAX_STREAM_DELAY_MILLIS, 'Invalid scripted stream delay')
            selector = item.get('tool')
            name = selector if isinstance(selector, str) else item.get('name') if selector is True else None
            if name:
                require(delay == 0, 'Delayed tool steps are unsupported')
                require(isinstance(name, str) and TOOL.fullmatch(name), 'Invalid scripted tool name')
                arguments = item.get('arguments', {})
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                require(isinstance(arguments, dict), 'Scripted tool arguments must be an object')
                steps.append({'tool': name, 'arguments': arguments})
            else:
                require(isinstance(item.get('text'), str) and len(item['text']) <= 65536, 'Scripted text is missing')
                steps.append({'text': item['text']})
            if 'streamDelayMillis' in item:
                steps[-1]['streamDelayMillis'] = delay
        checksum = hashlib.sha256(encoded(steps)).hexdigest()
        with self.lock:
            marker = body['marker']
            if marker in self.queues:
                require(self.queues[marker]['scriptSha256'] == checksum, 'Marker already belongs to another script')
            else:
                require(len(self.queues) < 256, 'Fixture marker budget exceeded')
                self.queues[marker] = {'steps': steps, 'cursor': 0, 'calls': 0, 'toolCalls': 0,
                    'scriptSha256': checksum, 'promptTokens': 0, 'completionTokens': 0, 'totalTokens': 0,
                    'streamResponses': 0, 'streamFirstChunks': 0, 'streamFinishes': 0, 'activeStreams': 0,
                    'streamDelayMillisObserved': 0}
        return {'armed': True, 'marker': marker, 'stepCount': len(steps), 'scriptSha256': checksum}

    def next(self, body):
        return self.next_with_context(body)[0]

    def next_with_context(self, body):
        message = '\n'.join(strings(body.get('messages', [])))
        require(len(message) <= MAX_BODY, 'Fixture messages exceed their bound')
        with self.lock:
            # A recovered SDK conversation can contain previous scenario marks.
            # Select the last occurrence in message order; prefer the longer mark
            # when one complete mark is a suffix of another at that position.
            matches = [marker for marker in self.queues if marker in message]
            self.calls += 1
            marker = max(matches, key=lambda item: (message.rfind(item) + len(item), len(item))) if matches else None
            item = None
            if marker:
                queue = self.queues[marker]
                if queue['cursor'] < len(queue['steps']):
                    item = queue['steps'][queue['cursor']]
                    queue['cursor'] += 1
                queue['calls'] += 1; queue['promptTokens'] += 12; queue['completionTokens'] += 8; queue['totalTokens'] += 20
                if item and 'tool' in item:
                    queue['toolCalls'] += 1
            else:
                self.unmarked_calls += 1
        structured = body.get('response_format') is not None or body.get('structured_response') is not None
        if re.search(r'"compatible"\s*:\s*true', message) and (structured or 'json' in message.lower()):
            # The real compatibility probe accepts precisely this single key.
            # Keep its provider protocol check separate from scenario responses.
            item = {'text': '{"compatible":true}'}
        elif item is None:
            # Configuration JSON probes have no armed marker and need actual
            # parseable JSON rather than a canned Markdown/string pseudo-result.
            item = {'text': encoded({'ok': True, **({'marker': marker} if marker else {})}).decode('utf8')
                    if structured or marker is None or 'json' in message.lower()
                    else 'Owned fixture completed ' + marker}
        elif structured and 'text' in item:
            try:
                json.loads(item['text'])
            except ValueError:
                item = {**item, 'text': encoded({'ok': True, 'marker': marker}).decode('utf8')}
        return item, marker

    def stream_event(self, marker, event, delay=0):
        if marker is None:
            return
        with self.lock:
            queue = self.queues[marker]
            if event == 'opened':
                queue['streamResponses'] += 1
                queue['activeStreams'] += 1
            elif event == 'content':
                queue['streamFirstChunks'] += 1
            elif event == 'finished':
                queue['streamFinishes'] += 1
                queue['streamDelayMillisObserved'] += delay
            elif event == 'closed':
                queue['activeStreams'] -= 1

    def embeddings(self, body):
        value = body.get('input')
        values = [value] if isinstance(value, list) and value and all(type(item) is int for item in value) else value if isinstance(value, list) else [value]
        require(values and len(values) <= 256 and all(isinstance(item, str)
                or isinstance(item, list) and item and all(type(token) is int for token in item) for item in values),
                'Embedding input must contain text or token arrays')
        result = []
        for index, item in enumerate(values):
            data = hashlib.shake_256(hashlib.sha256(encoded(item)).digest()).digest(4096)
            vector = [int.from_bytes(data[offset:offset + 4], 'big') / 2147483647.5 - 1
                      for offset in range(0, 4096, 4)]
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            result.append({'object': 'embedding', 'index': index, 'embedding': [value / norm for value in vector]})
        with self.lock:
            self.embedding_calls += 1
        return {'object': 'list', 'data': result, 'model': body.get('model', 'runtime-embedding'),
                'usage': {'prompt_tokens': 12, 'total_tokens': 12}}

    def state(self):
        with self.lock:
            return {'kind': 'doorhandle-owned-scripted-model', 'modelRequests': self.calls,
                    'embeddingRequests': self.embedding_calls, 'embeddingTokens': self.embedding_calls * 12,
                    'unmarkedModelRequests': self.unmarked_calls,
                    'markers': [{'marker': marker, 'armedSteps': len(value['steps']),
                        'remainingSteps': len(value['steps']) - value['cursor'],
                        **{key: value[key] for key in ('calls', 'toolCalls', 'promptTokens', 'completionTokens', 'totalTokens', 'scriptSha256',
                            'streamResponses', 'streamFirstChunks', 'streamFinishes', 'activeStreams', 'streamDelayMillisObserved')}}
                        for marker, value in sorted(self.queues.items())]}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    scripts = Scripts()
    token = None

    def log_message(self, *args):
        pass

    def json(self, status, value):
        data = encoded(value)
        self.send_response(status); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control', 'no-store')
        if status >= 400:
            self.close_connection = True
            self.send_header('Connection', 'close')
        self.end_headers(); self.wfile.write(data)

    def read_body(self):
        transfer = self.headers.get('Transfer-Encoding')
        if transfer is not None:
            require(transfer.lower() == 'chunked' and self.headers.get('Content-Length') is None,
                    'Ambiguous fixture input framing')
            chunks, total = [], 0
            while True:
                line = self.rfile.readline(128)
                require(re.fullmatch(rb'[0-9A-Fa-f]{1,8}\r\n', line), 'Invalid fixture chunk size')
                length = int(line.strip(), 16)
                if length == 0:
                    # SDK JSON publishers do not require trailers. Rejecting
                    # them avoids smuggling a second credential/framing header.
                    require(self.rfile.readline(128) == b'\r\n', 'Fixture trailers are unsupported')
                    break
                total += length
                require(total <= MAX_BODY and len(chunks) < 65536, 'Fixture chunk body exceeds its budget')
                chunk = self.rfile.read(length)
                require(len(chunk) == length and self.rfile.read(2) == b'\r\n', 'Truncated fixture chunk')
                chunks.append(chunk)
            raw = b''.join(chunks)
        else:
            length = self.headers.get('Content-Length', '')
            require(re.fullmatch(r'[0-9]{1,8}', length) and 0 < int(length) <= MAX_BODY, 'Bounded JSON body required')
            raw = self.rfile.read(int(length)); require(len(raw) == int(length), 'Truncated fixture request')
        body = json.loads(raw)
        require(isinstance(body, dict), 'Fixture JSON must be an object')
        return body

    def admin(self):
        supplied = self.headers.get('X-Runtime-Token', '')
        return (isinstance(self.token, str) and isinstance(supplied, str)
                and re.fullmatch(r'[a-f0-9]{32,128}', supplied) is not None
                and secrets.compare_digest(supplied, self.token))

    def model_auth(self):
        # Synthetic-only credential binding. Provider keys are never accepted or
        # persisted, and this module has no client capable of forwarding them.
        return self.headers.get('Authorization', '') == 'Bearer runtime-fixture'

    def do_GET(self):
        if self.path == '/health':
            self.json(200, {'status': 'ok', 'mode': 'local-scripted', 'outboundRequests': 0})
        elif self.path == '/__fixture/state':
            self.json(200, self.scripts.state()) if self.admin() else self.json(403, {'error': 'fixture token required'})
        else:
            self.json(404, {'error': 'fixture route unavailable'})

    def do_POST(self):
        try:
            if self.path == '/__fixture/arm':
                if not self.admin():
                    self.json(403, {'error': 'fixture token required'}); return
                body = self.read_body()
                if 'secret' in body:
                    require(secrets.compare_digest(str(body['secret']), self.token), 'Fixture token differs')
                self.json(200, self.scripts.arm(body)); return
            if not self.model_auth():
                self.json(401, {'error': {'message': 'synthetic fixture credential required', 'type': 'authentication_error'}}); return
            body = self.read_body()
            require(isinstance(body.get('model', 'runtime-model'), str) and len(body.get('model', 'runtime-model')) <= 160,
                    'Invalid fixture model identifier')
            if re.fullmatch(r'/(?:v1/|llm/[A-Za-z0-9_-]+/(?:v1/)?)?embeddings', self.path):
                self.json(200, self.scripts.embeddings(body)); return
            if not re.fullmatch(r'/(?:v1/|llm/[A-Za-z0-9_-]+/(?:v1/)?)?chat/completions', self.path):
                self.json(404, {'error': {'message': 'fixture model route unavailable'}}); return
            item, marker = self.scripts.next_with_context(body)
            model = body.get('model', 'runtime-model'); identity = 'chatcmpl-fixture-' + secrets.token_hex(8)
            message = {'role': 'assistant'}
            if 'tool' in item:
                message['content'] = None
                message['tool_calls'] = [{'id': 'call_fixture_' + secrets.token_hex(8), 'type': 'function',
                    'function': {'name': item['tool'], 'arguments': encoded(item['arguments']).decode('utf8')}}]
                reason = 'tool_calls'
            else:
                message['content'] = item['text']; reason = 'stop'
            usage = {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20}
            if not body.get('stream', False):
                self.json(200, {'id': identity, 'object': 'chat.completion', 'created': int(time.time()), 'model': model,
                    'choices': [{'index': 0, 'message': message, 'finish_reason': reason}], 'usage': usage}); return
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-store'); self.send_header('Connection', 'close'); self.end_headers()
            self.close_connection = True
            def event(delta, finish=None, *, include_usage=False, choices=True):
                value = {'id': identity, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': model,
                         'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}] if choices else []}
                if include_usage:
                    value['usage'] = usage
                self.wfile.write(b'data: ' + encoded(value) + b'\n\n'); self.wfile.flush()
            self.scripts.stream_event(marker, 'opened')
            try:
                event({'role': 'assistant'})
                if 'tool_calls' in message:
                    event({'tool_calls': [dict(message['tool_calls'][0], index=0)]})
                else:
                    event({'content': message['content']})
                    self.scripts.stream_event(marker, 'content')
                # Only the privately armed queue can delay a real provider
                # response. Its content has already been flushed to the SDK;
                # no browser/proxy gate can manufacture a live model stream.
                delay = item.get('streamDelayMillis', 0)
                started = time.monotonic()
                if delay:
                    time.sleep(delay / 1000)
                observed = int((time.monotonic() - started) * 1000)
                separate = isinstance(body.get('stream_options'), dict) and body['stream_options'].get('include_usage') is True
                event({}, reason, include_usage=not separate)
                if separate:
                    event({}, include_usage=True, choices=False)
                self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
                self.scripts.stream_event(marker, 'finished', observed)
            finally:
                self.scripts.stream_event(marker, 'closed')
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            self.json(400, {'error': {'message': 'invalid owned fixture request', 'type': 'invalid_request_error'}})
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    token = os.environ.get('RUNTIME_FIXTURE_TOKEN', '')
    require(re.fullmatch(r'[a-f0-9]{32,128}', token), 'Explicit private runtime fixture token required')
    Handler.token = token
    server = ThreadingHTTPServer(('0.0.0.0', 8099), Handler)
    server.daemon_threads = True
    server.serve_forever(poll_interval=0.25)


if __name__ == '__main__':
    main()
