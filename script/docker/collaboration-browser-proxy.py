#!/usr/bin/env python3
"""Container-local streaming transport to the owned, actual Nginx service.

This is not an application server. No application response is synthesized. The
SSE transport may be closed; real response headers may be held by bounded gates.
Cookies, request bodies, credentials, and response bodies are never logged.
"""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
import time
from urllib.parse import urlsplit


HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade', 'proxy-connection'}


class ResponseGate:
    def __init__(self, method, path):
        self.method, self.path = method, path
        self.arrived, self.release = threading.Event(), threading.Event()
        self.status = None
        self.claimed = False


class LoopbackProxy:
    def __init__(self):
        self.lock = threading.Lock()
        self.streams = set()
        self.gates = []
        self.block_until = 0.0
        self.stats = {'requests': 0, 'sseOpened': 0, 'sseActive': 0,
                      'ssePeak': 0, 'sseChunks': 0, 'sseBytes': 0,
                      'faultDisconnects': 0, 'faultRejectedConnections': 0,
                      'delayedRealResponsesBeforeHeaders': 0,
                      'transportErrors': 0, 'connectionAdmissionRejections': 0,
                      'maximumProxyConnections': 192,
                      'nginxProtocols': [], 'sseHeaders': []}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def setup(self):
                super().setup()
                self.connection.settimeout(45)

            def log_message(self, *_args):
                pass

            def do_GET(self): self.forward()
            def do_HEAD(self): self.forward()
            def do_POST(self): self.forward()
            def do_PUT(self): self.forward()
            def do_PATCH(self): self.forward()
            def do_DELETE(self): self.forward()
            def do_OPTIONS(self): self.forward()

            def forward(self):
                parsed = urlsplit(self.path)
                if parsed.scheme or parsed.netloc or not self.path.startswith('/') or self.headers.get('Host') != owner.authority:
                    self.send_error(400)
                    return
                is_sse = parsed.path == '/api/realtime/changes'
                with owner.lock:
                    owner.stats['requests'] += 1
                    if is_sse and time.monotonic() < owner.block_until:
                        owner.stats['faultRejectedConnections'] += 1
                        self.send_response(503)
                        self.send_header('Content-Length', '0')
                        self.send_header('Cache-Control', 'no-store')
                        self.end_headers()
                        return
                # Browser requests have a known content length. Reject arbitrary
                # chunked uploads rather than silently corrupt a business body.
                if self.headers.get('Transfer-Encoding'):
                    self.send_error(411)
                    return
                length = int(self.headers.get('Content-Length', '0'))
                if length < 0 or length > 16 * 1024 * 1024:
                    self.send_error(413)
                    return
                body = self.rfile.read(length) if length else None
                connection_tokens = {x.strip().lower() for x in self.headers.get('Connection', '').split(',')}
                headers = {key: value for key, value in self.headers.items()
                           if key.lower() not in HOP | connection_tokens}
                # Preserve loopback Host, Origin, Referer, and Set-Cookie exactly.
                # The backend sees the same origin as a user's SSH loopback visit.
                upstream = http.client.HTTPConnection('ui', 80, timeout=40)
                registered = False
                try:
                    upstream.request(self.command, self.path, body=body, headers=headers)
                    response = upstream.getresponse()
                    with owner.lock:
                        gate = next((value for value in owner.gates if not value.claimed
                                     and value.method == self.command and value.path == parsed.path), None)
                        if gate:
                            gate.claimed = True
                            gate.status = response.status
                            owner.stats['delayedRealResponsesBeforeHeaders'] += 1
                    if gate:
                        # The real upstream has executed, but no response headers
                        # (in particular Set-Cookie) have reached the browser jar.
                        gate.arrived.set()
                        if not gate.release.wait(60):
                            self.close_connection = True
                            return
                    self.send_response(response.status)
                    response_headers = response.getheaders()
                    removed = HOP | {x.strip().lower() for key, value in response_headers
                                     if key.lower() == 'connection' for x in value.split(',')}
                    for key, value in response_headers:
                        if key.lower() not in removed | {'content-length'}:
                            self.send_header(key, value)
                    if self.command == 'HEAD' or response.status in (204, 304):
                        self.send_header('Content-Length', '0')
                        self.end_headers()
                        return
                    self.send_header('Transfer-Encoding', 'chunked')
                    self.end_headers()
                    if is_sse and response.status == 200:
                        with owner.lock:
                            registered = True
                            owner.streams.add(self.connection)
                            owner.stats['sseOpened'] += 1
                            owner.stats['sseActive'] += 1
                            owner.stats['ssePeak'] = max(owner.stats['ssePeak'], owner.stats['sseActive'])
                            protocol = 'HTTP/1.1' if response.version == 11 else 'HTTP/1.0'
                            if protocol not in owner.stats['nginxProtocols']:
                                owner.stats['nginxProtocols'].append(protocol)
                            evidence = {key.lower(): value for key, value in response_headers
                                        if key.lower() in {'content-type', 'cache-control', 'content-encoding', 'x-accel-buffering'}}
                            if evidence not in owner.stats['sseHeaders']:
                                owner.stats['sseHeaders'].append(evidence)
                    while True:
                        # read1 returns available bytes, not a 64KiB accumulation.
                        # Every Nginx SSE chunk is flushed immediately downstream.
                        chunk = response.read1(65536)
                        if not chunk:
                            break
                        self.wfile.write(('%x\r\n' % len(chunk)).encode('ascii'))
                        self.wfile.write(chunk)
                        self.wfile.write(b'\r\n')
                        self.wfile.flush()
                        if registered:
                            with owner.lock:
                                owner.stats['sseChunks'] += 1
                                owner.stats['sseBytes'] += len(chunk)
                    self.wfile.write(b'0\r\n\r\n')
                    self.wfile.flush()
                except (OSError, ValueError, http.client.HTTPException):
                    self.close_connection = True
                finally:
                    upstream.close()
                    if registered:
                        with owner.lock:
                            owner.streams.discard(self.connection)
                            owner.stats['sseActive'] -= 1

        class BoundedServer(ThreadingHTTPServer):
            request_queue_size = 128

            def __init__(self, *args):
                self.slots = threading.BoundedSemaphore(192)
                super().__init__(*args)

            def process_request(self, request, address):
                if not self.slots.acquire(timeout=5):
                    with owner.lock:
                        owner.stats['connectionAdmissionRejections'] += 1
                    self.shutdown_request(request)
                    return
                try:
                    super().process_request(request, address)
                except BaseException:
                    self.slots.release()
                    raise

            def process_request_thread(self, request, address):
                try:
                    super().process_request_thread(request, address)
                finally:
                    self.slots.release()

            def handle_error(self, _request, _address):
                # Never emit a raw HTTP handler traceback/URL to archived logs.
                with owner.lock:
                    owner.stats['transportErrors'] += 1

        self.server = BoundedServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.authority = '127.0.0.1:' + str(self.server.server_port)
        self.origin = 'http://' + self.authority
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self.origin

    def disconnect_sse(self, block_seconds=0):
        with self.lock:
            self.block_until = time.monotonic() + block_seconds
            streams = tuple(self.streams)
            self.stats['faultDisconnects'] += len(streams)
        for connection in streams:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def pause_next_response(self, method, path):
        gate = ResponseGate(method, path)
        with self.lock:
            self.gates.append(gate)
        return gate

    def snapshot(self):
        with self.lock:
            return {**self.stats, 'sseHeaders': list(self.stats['sseHeaders']),
                    'nginxProtocols': list(self.stats['nginxProtocols'])}

    def close(self):
        with self.lock:
            for gate in self.gates:
                gate.release.set()
        self.disconnect_sse()
        self.server.shutdown()
        self.server.server_close()
