"""Authenticated MCP HTTP endpoint; each Fetch invocation owns a disposable container.

Uses the MIT-licensed official MCP Python SDK. No caller-supplied command, image,
mount, environment or Docker option is accepted by this service.
"""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
import base64
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import time
import uuid
from urllib.parse import parse_qsl, urlsplit

import anyio
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

VERSION = '2026.10.10'
PACKAGE_SHA = 'd722c48bdc1de3e2a81727853bc490cf55c6c935e2038cdcad3c111b1d85db77'
IDENTITY = ContextVar('mcp_identity')


def decode_credential(token, secret, now=None):
    if len(token) > 4096 or len(secret.encode()) < 32:
        raise ValueError('credential')
    body, signature = token.split('.')
    expected = base64.urlsafe_b64encode(hmac.new(secret.encode(), body.encode('ascii'), hashlib.sha256).digest()).decode().rstrip('=')
    if not hmac.compare_digest(expected, signature):
        raise ValueError('signature')
    value = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
    if not isinstance(value, dict):
        raise ValueError('credential')
    now = int(time.time()) if now is None else now
    if value.get('aud') != 'doorhandle-mcp-runner' or type(value.get('owner')) is not int or value['owner'] < 1:
        raise ValueError('owner')
    if value.get('scope') not in ('install', 'execute') or type(value.get('exp')) is not int or type(value.get('iat')) is not int:
        raise ValueError('scope')
    if not value['iat'] - 5 <= now < value['exp'] or not 0 < value['exp'] - value['iat'] <= 60:
        raise ValueError('expiry')
    for name in ('nonce', 'installation'):
        if not isinstance(value.get(name), str) or str(uuid.UUID(value[name])) != value[name]:
            raise ValueError('identity')
    return value


def validate_arguments(args, resolver=socket.getaddrinfo):
    if not isinstance(args, dict) or not set(args) <= {'url', 'max_length', 'start_index'}:
        raise ValueError('arguments')
    url = args.get('url')
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url) or '\\' in url:
        raise ValueError('url')
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('url')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    if port != (443 if parsed.scheme == 'https' else 80):
        raise ValueError('port')
    if any(re.search(r'(?i)(token|secret|password|api.?key|authorization|credential)', key) for key, _ in parse_qsl(parsed.query)):
        raise ValueError('secret')
    addresses = resolver(parsed.hostname, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(record[4][0]).is_global for record in addresses):
        raise ValueError('private destination')
    result = {'url': url}
    for name, minimum, maximum, default in [('max_length', 1, 20000, 5000), ('start_index', 0, 1000000, 0)]:
        value = args.get(name, default)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError('range')
        result[name] = value
    return result


class DockerExecutor:
    def __init__(self, image, network, proxy):
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
            raise ValueError('A locally verified immutable Fetch image ID is required')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{1,80}', network) or proxy != 'http://mcp-egress:3128':
            raise ValueError('Fixed execution network and egress proxy are required')
        self.image, self.network, self.proxy = image, network, proxy
        self.active = {}
        self.revoked = {}
        self.capacity = asyncio.Semaphore(2)

    def arguments(self, identity, name):
        return ['run', '--rm', '-i', '--name', name, '--label', 'doorhandle.mcp.managed=true',
                '--label', f'doorhandle.mcp.owner={identity["owner"]}',
                '--label', f'doorhandle.mcp.expires={int(time.time()) + 45}',
                '--network', self.network, '--user', '10001:10001', '--read-only',
                '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=64',
                '--memory=256m', '--cpus=0.5', '--stop-timeout=2',
                '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=32m,uid=10001,gid=10001',
                '--env', 'HOME=/tmp', '--env', f'HTTP_PROXY={self.proxy}', '--env', f'HTTPS_PROXY={self.proxy}',
                '--env', 'NO_PROXY=', '--env', 'PYTHONNOUSERSITE=1', '--env', 'PYTHONUNBUFFERED=1',
                self.image, '/opt/fetch/.venv/bin/python', '-I', '-m', 'mcp_server_fetch']

    async def remove(self, name):
        if not re.fullmatch(r'dh-mcp-[a-f0-9]{32}-[a-f0-9]{32}', name):
            raise ValueError('container name')
        with anyio.move_on_after(8, shield=True):
            await anyio.run_process(['docker', 'rm', '-f', name], check=False, stdout=-1, stderr=-1)

    async def cancel(self, identity):
        nonce = identity['nonce']
        self.revoked[nonce] = identity['exp']
        for name in tuple(self.active.get(nonce, ())):
            await self.remove(name)

    async def execute(self, identity, args):
        if identity['nonce'] in self.revoked or self.capacity.locked():
            return types.CallToolResult(isError=True, content=[types.TextContent(type='text', text='MCP execution unavailable')])
        name = 'dh-mcp-' + uuid.UUID(identity['nonce']).hex + '-' + uuid.uuid4().hex
        async with self.capacity:
            self.active.setdefault(identity['nonce'], set()).add(name)
            try:
                with anyio.fail_after(25):
                    command = StdioServerParameters(command='docker', args=self.arguments(identity, name), env={'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'), 'HOME': '/tmp'})
                    with open(os.devnull, 'w') as errors:
                        async with stdio_client(command, errlog=errors) as (read, write):
                            async with ClientSession(read, write) as client:
                                await client.initialize()
                                tools = await client.list_tools()
                                if not any(tool.name == 'fetch' for tool in tools.tools):
                                    raise RuntimeError('tool discovery')
                                if identity['nonce'] in self.revoked:
                                    raise RuntimeError('cancelled')
                                result = await client.call_tool('fetch', args)
                                # Only text from the fixed tool crosses back into the Agent.
                                text = '\n'.join(item.text for item in result.content if isinstance(item, types.TextContent))[:24000]
                                return types.CallToolResult(isError=bool(result.isError), content=[types.TextContent(type='text', text=text)])
            except asyncio.CancelledError:
                raise
            except Exception:
                return types.CallToolResult(isError=True, content=[types.TextContent(type='text', text='Isolated Fetch execution failed')])
            finally:
                await self.remove(name)
                self.active.get(identity['nonce'], set()).discard(name)
                if not self.active.get(identity['nonce']):
                    self.active.pop(identity['nonce'], None)

    async def reap(self):
        while True:
            self.revoked = {key: expiry for key, expiry in self.revoked.items() if expiry > time.time()}
            try:
                with anyio.fail_after(10):
                    result = await anyio.run_process(['docker', 'ps', '-aq', '--filter', 'label=doorhandle.mcp.managed=true'], check=True)
                    for container in result.stdout.decode().split():
                        detail = await anyio.run_process(['docker', 'inspect', container], check=True)
                        config = json.loads(detail.stdout)[0]
                        labels = config['Config'].get('Labels') or {}
                        if int(labels.get('doorhandle.mcp.expires', 0)) < time.time():
                            await self.remove(config['Name'].lstrip('/'))
            except Exception:
                pass
            await anyio.sleep(15)


def create_app(secret, image, network, proxy, manifest_path='/opt/fetch/manifest.json', executor=None):
    if len(secret.encode()) < 32:
        raise ValueError('MCP runner signing secret must contain at least 32 bytes')
    executor = executor or DockerExecutor(image, network, proxy)
    artifact = json.loads(Path(manifest_path).read_text())
    if artifact['version'] != VERSION or artifact['packageSha256'] != PACKAGE_SHA:
        raise ValueError('Unreviewed Fetch package')
    artifact = {key: artifact[key] for key in ('version', 'packageSha256', 'artifacts', 'licenses')}
    artifact.update(serverKey='fetch', package='mcp-server-fetch', transport='STREAMABLE_HTTP', image=image)
    server = Server('doorhandle-isolated-fetch')

    @server.list_tools()
    async def list_tools():
        return [types.Tool(name='fetch', description='Fetch an explicitly requested public webpage in an isolated container', inputSchema={
            'type': 'object', 'additionalProperties': False, 'required': ['url'], 'properties': {
                'url': {'type': 'string', 'maxLength': 2048}, 'max_length': {'type': 'integer', 'minimum': 1, 'maximum': 20000},
                'start_index': {'type': 'integer', 'minimum': 0, 'maximum': 1000000}}})]

    @server.call_tool()
    async def call_tool(name, arguments):
        try:
            if name != 'fetch':
                raise ValueError('tool')
            args = await anyio.to_thread.run_sync(validate_arguments, arguments)
            return await executor.execute(IDENTITY.get(), args)
        except (ValueError, LookupError, OSError):
            return types.CallToolResult(isError=True, content=[types.TextContent(type='text', text='MCP request denied')])

    manager = StreamableHTTPSessionManager(server, json_response=True, stateless=True,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=['higress:8080', 'mcp-runner:8080', '127.0.0.1:*', 'localhost:*']))

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run(), anyio.create_task_group() as group:
            group.start_soon(executor.reap)
            yield
            group.cancel_scope.cancel()
    async def health(request):
        return JSONResponse({'status': 'ok'})
    async def artifact_response(request):
        return JSONResponse(artifact)
    async def cancel(request):
        await executor.cancel(IDENTITY.get())
        return JSONResponse({'cancelled': True})
    class McpEndpoint:
        async def __call__(self, scope, receive, send):
            await manager.handle_request(scope, receive, send)
    app = Starlette(routes=[Route('/health', health), Route('/mcp/fetch/artifact', artifact_response),
        Route('/mcp/fetch/cancel', cancel, methods=['POST']), Route('/mcp/fetch/mcp', McpEndpoint(), methods=['GET', 'POST', 'DELETE'])], lifespan=lifespan)

    async def authenticated(scope, receive, send):
        if scope['type'] != 'http' or scope['path'] == '/health':
            return await app(scope, receive, send)
        try:
            values = [v.decode('ascii') for k, v in scope['headers'] if k.lower() == b'authorization']
            if len(values) != 1 or not values[0].startswith('Bearer '):
                raise ValueError('authorization')
            identity = decode_credential(values[0][7:], secret)
            expected_scope = 'install' if scope['path'] == '/mcp/fetch/artifact' else 'execute'
            if identity['scope'] != expected_scope or identity['nonce'] in executor.revoked:
                raise ValueError('scope')
        except (ValueError, KeyError, TypeError, UnicodeError):
            return await JSONResponse({'error': 'unauthorized'}, status_code=401)(scope, receive, send)
        token = IDENTITY.set(identity)
        size = 0
        async def bounded_receive():
            nonlocal size
            message = await receive()
            size += len(message.get('body', b''))
            if size > 32768:
                raise ValueError('MCP request too large')
            return message
        try:
            await app(scope, bounded_receive, send)
        finally:
            IDENTITY.reset(token)
    return authenticated


if __name__ == '__main__':
    import uvicorn
    app = create_app(os.environ['MCP_RUNNER_SECRET'], os.environ['MCP_FETCH_IMAGE'],
                     os.environ['MCP_EXEC_NETWORK'], os.environ.get('MCP_EGRESS_PROXY', 'http://mcp-egress:3128'))
    uvicorn.run(app, host='0.0.0.0', port=8080, access_log=False)
