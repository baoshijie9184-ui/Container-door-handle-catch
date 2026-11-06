#!/usr/bin/env python3
"""Forward only this acceptance run's OSS objects, without general Internet egress.

The backend remains on an internal Docker network. Its ordinary OSS V1 SDK
requests retain the canonical bucket/key and signature while this adapter sends
them to the configured real Alibaba endpoint over TLS. Unsupported signatures,
redirects, buckets and object prefixes fail closed. No credentials are logged.
"""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import threading
from urllib.parse import unquote, urlsplit

BUCKET = os.environ['FIXTURE_OSS_BUCKET']
ENDPOINT = urlsplit(os.environ['FIXTURE_OSS_ENDPOINT'])
PREFIX = os.environ['FIXTURE_OSS_PREFIX']
assert re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', BUCKET)
assert ENDPOINT.scheme == 'https' and re.fullmatch(r'oss-[a-z0-9-]+\.aliyuncs\.com', ENDPOINT.hostname or '')
assert ENDPOINT.port in (None, 443) and ENDPOINT.path in ('', '/') and not ENDPOINT.query and not ENDPOINT.fragment
assert not ENDPOINT.username and not ENDPOINT.password
assert re.fullmatch(r'runtime-acceptance/[a-f0-9]{12}/', PREFIX)
COUNTS = {'requests': 0, 'failed': 0, 'responseRequestIdsSha256': hashlib.sha256(b'').hexdigest()}
LOCK = threading.Lock()
HOP = {'host', 'connection', 'transfer-encoding', 'proxy-authorization', 'proxy-connection', 'upgrade', 'keep-alive', 'te', 'trailer'}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args):
        pass
    def response(self, code, body=b'', headers=None):
        self.send_response(code)
        for key, value in (headers or {}).items():
            if key.lower() not in HOP | {'content-length'}:
                self.send_header(key, value)
        length = len(body)
        if self.command == 'HEAD':
            # HEAD carries object metadata without a response body. Replacing
            # the upstream length with zero would invalidate upload readback.
            declared = next((value for key, value in (headers or {}).items() if key.lower() == 'content-length'), None)
            if declared is not None:
                length = int(declared)
        self.send_header('Content-Length', str(length))
        self.send_header('Connection', 'close'); self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)
        self.close_connection = True
    def do_GET(self):
        if self.path in ('/health', '/__fixture/state') and self.headers.get('Host', '').split(':')[0] in ('127.0.0.1', 'localhost'):
            with LOCK:
                value = dict(COUNTS)
            self.response(200, json.dumps(value).encode(), {'Content-Type': 'application/json'}); return
        self.forward()
    do_HEAD = do_PUT = do_DELETE = lambda self: self.forward()
    def forward(self):
        connection = None
        try:
            route = urlsplit(self.path)
            key = unquote(route.path).lstrip('/')
            assert not route.scheme and not route.netloc and not route.fragment
            # The reviewed Java OSS 3.17.4 client defaults to CNAME addressing
            # for custom endpoints; both forms still sign the same fixed
            # canonical bucket/key. No caller-provided upstream host is used.
            assert self.headers.get('Host', '').split(':')[0] in ('oss-proxy', BUCKET + '.oss-proxy')
            assert key.startswith(PREFIX) and not any(part in ('.', '..') for part in key.split('/'))
            assert len(key) <= 1024 and not any(ord(value) < 32 for value in key)
            assert self.command in ('GET', 'HEAD', 'PUT', 'DELETE')
            authorization = self.headers.get('Authorization', '')
            assert authorization.startswith('OSS ') or ('OSSAccessKeyId=' in route.query and 'Signature=' in route.query)
            assert 'OSS4-' not in authorization and 'x-oss-signature-version=' not in route.query.lower()
            assert not self.headers.get('Transfer-Encoding')
            length = int(self.headers.get('Content-Length', '0'))
            assert 0 <= length <= 26 * 1024 * 1024
            body = self.rfile.read(length)
            assert len(body) == length
            headers = {key: value for key, value in self.headers.items() if key.lower() not in HOP}
            headers['Host'] = BUCKET + '.' + ENDPOINT.hostname
            connection = http.client.HTTPSConnection(headers['Host'], 443, timeout=60)
            connection.request(self.command, self.path, body=body, headers=headers)
            upstream = connection.getresponse(); result = upstream.read(26 * 1024 * 1024 + 1)
            assert len(result) <= 26 * 1024 * 1024 and not 300 <= upstream.status < 400
            with LOCK:
                COUNTS['requests'] += 1
                COUNTS['failed'] += int(upstream.status >= 400)
                COUNTS['responseRequestIdsSha256'] = hashlib.sha256((COUNTS['responseRequestIdsSha256'] + upstream.getheader('x-oss-request-id', '')).encode()).hexdigest()
            self.response(upstream.status, result, dict(upstream.getheaders()))
        except Exception:
            with LOCK:
                COUNTS['failed'] += 1
            self.response(502, b'Owned OSS transport did not complete')
        finally:
            if connection:
                connection.close()


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 9000), Handler).serve_forever()
