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
import sys
import sqlite3
import time
import uuid
import importlib.util
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
_store_spec = importlib.util.spec_from_file_location('doorhandle_mcp_execution_store', Path(__file__).with_name('execution_store.py'))
_store_module = importlib.util.module_from_spec(_store_spec)
_store_spec.loader.exec_module(_store_module)
ExecutionStore, CapacityExceeded = _store_module.ExecutionStore, _store_module.CapacityExceeded
_image_spec = importlib.util.spec_from_file_location('doorhandle_mcp_image_lifecycle', Path(__file__).with_name('image_lifecycle.py'))
_image_module = importlib.util.module_from_spec(_image_spec); _image_spec.loader.exec_module(_image_module)


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
    if value.get('scope') not in ('install', 'execute', 'control', 'install-control', 'image-inspect', 'image-prepare', 'image-delete', 'image-receipt') or type(value.get('exp')) is not int or type(value.get('iat')) is not int:
        raise ValueError('scope')
    if not value['iat'] - 5 <= now < value['exp'] or not 0 < value['exp'] - value['iat'] <= 60:
        raise ValueError('expiry')
    for name in ('nonce', 'installation'):
        if not isinstance(value.get(name), str) or str(uuid.UUID(value[name])) != value[name]:
            raise ValueError('identity')
    if value['scope'] == 'control' and (not isinstance(value.get('execution_nonce'), str) or str(uuid.UUID(value['execution_nonce'])) != value['execution_nonce']):
        raise ValueError('execution identity')
    if 'pool_id' in value and (not isinstance(value['pool_id'], str) or not re.fullmatch(r'[a-f0-9]{32}', value['pool_id'])):
        raise ValueError('execution pool')
    if 'image' in value and (not isinstance(value['image'], str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', value['image'])):
        raise ValueError('execution release')
    if value['scope'] in ('image-prepare', 'image-delete', 'image-receipt') and ('image' not in value or 'pool_id' not in value):
        raise ValueError('image lifecycle identity')
    if value['scope'] in ('image-prepare', 'image-delete') and (type(value.get('image_policy')) is not int or value['image_policy'] != 4):
        raise ValueError('deployment-aware image policy required')
    if value['scope'] == 'install-control' and (not isinstance(value.get('controller_id'), str) or not re.fullmatch('[a-f0-9]{12,64}', value['controller_id'])):
        raise ValueError('controller identity')
    if 'controller_started' in value and (not isinstance(value['controller_started'], str) or not 1 <= len(value['controller_started']) <= 64):
        raise ValueError('controller generation')
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
    def __init__(self, image, network, proxy, journal_path=None):
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
            raise ValueError('A locally verified immutable Fetch image ID is required')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{1,80}', network) or proxy != 'http://mcp-egress:3128':
            raise ValueError('Fixed execution network and egress proxy are required')
        self.image, self.network, self.proxy = image, network, proxy
        self.approved_images = {image, *(value.strip() for value in os.environ.get('MCP_FETCH_APPROVED_IMAGES', '').split(',') if value.strip())}
        if len(self.approved_images) > 8 or any(not re.fullmatch(r'sha256:[a-f0-9]{64}', value) for value in self.approved_images):
            raise ValueError('Invalid reviewed Fetch image allowlist')
        self.store = ExecutionStore(journal_path or os.environ.get('MCP_EXECUTION_DB'))
        self.images = _image_module.ImageLifecycle(self, VERSION, PACKAGE_SHA)
        self.worker_id = uuid.uuid4().hex
        self.active = {}
        self.revoked = {}
        self.capacity = asyncio.Semaphore(2)

    def arguments(self, identity, name):
        return ['run', '--pull', 'never', '--rm', '-i', '--name', name, '--label', 'doorhandle.mcp.managed=true',
                '--label', f'doorhandle.mcp.owner={identity["owner"]}',
                '--label', f'doorhandle.mcp.pool={self.store.pool_id}',
                '--label', f'doorhandle.mcp.installation={identity["installation"]}',
                '--label', f'doorhandle.mcp.nonce={identity["nonce"]}',
                '--label', f'doorhandle.mcp.expires={int(time.time()) + 45}',
                '--network', self.network, '--user', '10001:10001', '--read-only',
                '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=64',
                '--memory=256m', '--cpus=0.5', '--stop-timeout=2',
                '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=32m,uid=10001,gid=10001',
                '--env', 'HOME=/tmp', '--env', f'HTTP_PROXY={self.proxy}', '--env', f'HTTPS_PROXY={self.proxy}',
                '--env', 'NO_PROXY=', '--env', 'PYTHONNOUSERSITE=1', '--env', 'PYTHONUNBUFFERED=1',
                identity.get('image', self.image), '/opt/fetch/.venv/bin/python', '-I', '-m', 'mcp_server_fetch']

    async def docker(self, args):
        # Always address the runner's explicitly mounted daemon, never an inherited remote Docker context.
        with anyio.fail_after(5):
            return await anyio.run_process(['docker', *args], check=False, stdout=-1, stderr=-1,
                env={'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'), 'DOCKER_HOST': 'unix:///var/run/docker.sock', 'HOME': '/tmp'})

    async def absent(self, name, field='name'):
        result = await self.docker(['ps', '-aq', '--no-trunc', '--filter', field+'='+('^/'+name+'$' if field == 'name' else name)])
        return result.returncode == 0 and not result.stdout.strip()

    def matches(self, config, row):
        labels = config.get('Config', {}).get('Labels') or {}
        return config.get('Name', '').lstrip('/') == row['name'] and config.get('Image') == row['image'] and all(labels.get(key) == value for key, value in {
            'doorhandle.mcp.managed': 'true', 'doorhandle.mcp.pool': self.store.pool_id, 'doorhandle.mcp.owner': str(row['owner']),
            'doorhandle.mcp.installation': row['installation'], 'doorhandle.mcp.nonce': row['nonce']}.items())

    async def remove(self, name):
        if not re.fullmatch(r'dh-mcp-[a-f0-9]{32}-[a-f0-9]{32}', name):
            raise ValueError('container name')
        row = self.store.get(name)
        if row['status'] == 'REMOVED': return True
        try:
            with anyio.fail_after(15, shield=True):
                before = await self.docker(['inspect', '--type', 'container', name])
                if before.returncode == 0:
                    config = json.loads(before.stdout)
                    if len(config) != 1 or not self.matches(config[0], row):
                        self.store.result(name, 'NEEDS_REVIEW', 'CONTAINER_IDENTITY_MISMATCH'); return False
                    # Use the immutable ID after checking name, owner, installation, nonce, pool and image.
                    container_id = config[0].get('Id', '')
                    if not re.fullmatch(r'[a-f0-9]{64}', container_id): raise ValueError('container identity')
                    await self.docker(['rm', '-f', container_id])
                elif not await self.absent(name):
                    self.store.result(name, 'NEEDS_REVIEW', 'DAEMON_RESULT_UNVERIFIED'); return False
                if await self.absent(name):
                    self.store.result(name, 'REMOVED', 'DAEMON_CONFIRMED_ABSENT')
                    return self.store.get(name)['status'] == 'REMOVED'
                after = await self.docker(['inspect', '--type', 'container', name])
                if after.returncode == 0:
                    config = json.loads(after.stdout)
                    if len(config) == 1 and self.matches(config[0], row) and config[0].get('State', {}).get('Running') is False:
                        self.store.result(name, 'EXITED', 'DAEMON_CONFIRMED_STOPPED'); return False
                self.store.result(name, 'NEEDS_REVIEW', 'EXIT_NOT_CONFIRMED'); return False
        except (Exception, asyncio.CancelledError):
            self.store.result(name, 'NEEDS_REVIEW', 'EXIT_CHECK_INTERRUPTED'); return False

    def is_revoked(self, identity):
        return self.store.revoked(identity)

    async def controller(self):
        hostname = socket.gethostname()
        if not re.fullmatch(r'[a-f0-9]{12,64}', hostname): return None
        result = await self.docker(['inspect', '--type', 'container', hostname])
        if result.returncode != 0: return None
        values = json.loads(result.stdout)
        if len(values) != 1: return None
        value = values[0]
        if not re.fullmatch(r'[a-f0-9]{64}', value.get('Id', '')) or not value['Id'].startswith(hostname) or value.get('Image') != self.image or value.get('State', {}).get('Running') is not True: return None
        started = value['State'].get('StartedAt')
        return {'id': value['Id'], 'started': started} if isinstance(started, str) and started else None

    async def controller_ended(self, row):
        if not row['controller_id'] or not row['controller_started']: return False
        result = await self.docker(['inspect', '--type', 'container', row['controller_id']])
        if result.returncode != 0: return await self.absent(row['controller_id'], 'id')
        values = json.loads(result.stdout)
        if len(values) != 1 or values[0].get('Id') != row['controller_id']: return False
        state = values[0].get('State', {})
        return state.get('Running') is False or isinstance(state.get('StartedAt'), str) and state['StartedAt'] != row['controller_started']

    async def install_controller(self, identity):
        controller, previous = identity['controller_id'], identity.get('controller_started')
        inspected = await self.docker(['inspect', '--type', 'container', controller])
        if inspected.returncode != 0:
            ended = previous is not None and len(controller) == 64 and await self.absent(controller, 'id')
            return {'poolId': self.store.pool_id, 'stopped': ended}
        values = json.loads(inspected.stdout)
        if len(values) != 1:
            raise ValueError('controller unavailable')
        value = values[0]; labels = value.get('Config', {}).get('Labels') or {}; full = value.get('Id', '')
        if not re.fullmatch('[a-f0-9]{64}', full) or not full.startswith(controller) or labels.get('com.docker.compose.project') != 'doorhandlecatch-monolith' or labels.get('com.docker.compose.service') != 'backend':
            raise ValueError('controller is not the fixed backend')
        state = value.get('State', {}); started = state.get('StartedAt')
        if not isinstance(started, str) or not started:
            raise ValueError('controller generation unavailable')
        ended = previous is not None and full == controller and (state.get('Running') is False or started != previous)
        return {'poolId': self.store.pool_id, 'controllerId': full, 'controllerStarted': started, 'stopped': ended}

    async def cancel(self, identity):
        nonce = identity.get('execution_nonce', identity['nonce'])
        self.revoked[nonce] = identity['exp']
        self.store.revoke(identity)
        for row in self.store.rows(identity):
            if row['status'] != 'REMOVED': await self.remove(row['name'])
        return self.store.receipt(identity)

    def receipt(self, identity):
        return self.store.receipt(identity)

    @asynccontextmanager
    async def tracked_stdio(self, name, command, errors):
        # Enter this scope before the SDK enters its task group. Adding a new scope
        # around __aexit__ would violate AnyIO's cancel-scope stack ordering.
        with anyio.CancelScope(shield=True) as lifecycle:
            transport = stdio_client(command, errlog=errors)
            streams = await transport.__aenter__()
            lifecycle.shield = False
            try:
                yield streams
            except BaseException:
                lifecycle.shield = True
                # Preserve the body exception ourselves; normal SDK exit must finish
                # its shutdown before the launcher can be marked settled.
                await transport.__aexit__(None, None, None)
                self.store.launch_done(name)
                raise
            else:
                lifecycle.shield = True
                await transport.__aexit__(None, None, None)
                self.store.launch_done(name)

    async def execute(self, identity, args):
        if self.is_revoked(identity) or self.capacity.locked():
            return types.CallToolResult(isError=True, content=[types.TextContent(type='text', text='MCP execution unavailable')])
        name = 'dh-mcp-' + uuid.UUID(identity['nonce']).hex + '-' + uuid.uuid4().hex
        try:
            image = identity.get('image', self.image)
            if image not in self.approved_images:
                raise ValueError('Release not approved')
            inspected = await self.docker(['image', 'inspect', image])
            values = json.loads(inspected.stdout) if inspected.returncode == 0 else []
            if len(values) != 1 or values[0].get('Id') != image:
                raise ValueError('Release unavailable')
            labels = values[0].get('Config', {}).get('Labels') or {}
            if labels.get('doorhandle.mcp.fetch') != 'true' or labels.get('doorhandle.mcp.version') != VERSION or labels.get('doorhandle.mcp.package-sha256') != PACKAGE_SHA:
                raise ValueError('Release metadata mismatch')
            controller = await self.controller()
            self.store.reserve(identity, name, image, self.worker_id, controller)
        except (CapacityExceeded, OSError, ValueError):
            return types.CallToolResult(isError=True, content=[types.TextContent(type='text', text='MCP execution capacity unavailable or awaiting reconciliation')])
        self.active.setdefault(identity['nonce'], set()).add(name)
        try:
            with anyio.fail_after(25):
                command = StdioServerParameters(command='docker', args=self.arguments(identity, name), env={'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'), 'DOCKER_HOST': 'unix:///var/run/docker.sock', 'HOME': '/tmp'})
                with open(os.devnull, 'w') as errors:
                    async with self.tracked_stdio(name, command, errors) as (read, write):
                        async with ClientSession(read, write) as client:
                            await client.initialize()
                            tools = await client.list_tools()
                            if not any(tool.name == 'fetch' for tool in tools.tools):
                                raise RuntimeError('tool discovery')
                            if self.is_revoked(identity):
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
            if await self.remove(name):
                self.active.get(identity['nonce'], set()).discard(name)
                if not self.active.get(identity['nonce']): self.active.pop(identity['nonce'], None)

    async def reap(self):
        while True:
            try:
                await self.reconcile_once()
            except Exception:
                pass
            await anyio.sleep(15)

    async def reconcile_once(self):
        for row in self.store.rows():
            if not row['launch_settled'] and row['expires_at'] < time.time() and row['worker_id'] != self.worker_id:
                if await self.controller_ended(row): self.store.launch_done(row['name'])
                else: self.store.result(row['name'], 'NEEDS_REVIEW', 'LAUNCHER_EXIT_UNVERIFIED')
            if row['expires_at'] < time.time() or row['status'] in ('NEEDS_REVIEW', 'EXITED'):
                await self.remove(row['name'])


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
    async def execution_pool(request):
        if not hasattr(executor, 'store'):
            return JSONResponse({'error': 'execution journal unavailable'}, status_code=503)
        return JSONResponse({'poolId': executor.store.pool_id})
    async def install_controller(request):
        try:
            if not hasattr(executor, 'install_controller'):
                raise ValueError('controller proof unavailable')
            identity = IDENTITY.get(); result = await executor.install_controller(identity)
            return JSONResponse({**result, 'owner': identity['owner'], 'installation': identity['installation'], 'requestNonce': identity['nonce'], 'requestedController': identity['controller_id'], 'requestedStarted': identity.get('controller_started')}, headers={'Cache-Control': 'no-store'})
        except (ValueError, OSError, sqlite3.Error, TimeoutError):
            return JSONResponse({'error': 'controller proof unavailable', 'stopped': False}, status_code=503)
    async def cancel(request):
        try:
            receipt = await executor.cancel(IDENTITY.get())
            if not isinstance(receipt, dict): receipt = {'exitVerified': False, 'cleanupConfirmed': False, 'executions': []}
            return JSONResponse({**receipt, 'cancelled': receipt.get('exitVerified') is True})
        except (sqlite3.Error, OSError, ValueError):
            return JSONResponse({'error': 'execution state unavailable', 'exitVerified': False}, status_code=503)
    async def receipt(request):
        try:
            if not hasattr(executor, 'receipt'): raise ValueError('Receipt unavailable')
            return JSONResponse(executor.receipt(IDENTITY.get()))
        except (sqlite3.Error, OSError, ValueError):
            return JSONResponse({'error': 'execution state unavailable', 'exitVerified': False}, status_code=503)
    async def image_inventory(request):
        if os.environ.get('MCP_SHARED_IMAGE_CLEANUP_ENABLED', 'false') != 'true' or not hasattr(executor, 'images'):
            return JSONResponse({'error': 'image lifecycle unavailable'}, status_code=503)
        try:
            return JSONResponse(await executor.images.inventory(), headers={'Cache-Control': 'no-store'})
        except Exception:
            return JSONResponse({'error': 'image inventory unverified'}, status_code=503)
    async def image_control(request):
        identity = IDENTITY.get()
        if not hasattr(executor, 'images') or identity['scope'] != 'image-receipt' and os.environ.get('MCP_SHARED_IMAGE_CLEANUP_ENABLED', 'false') != 'true':
            return JSONResponse({'error': 'image lifecycle unavailable'}, status_code=503)
        try:
            method = {'image-prepare': executor.images.prepare, 'image-delete': executor.images.delete, 'image-receipt': executor.images.reconcile}[identity['scope']]
            return JSONResponse(await method(identity), headers={'Cache-Control': 'no-store'})
        except Exception:
            return JSONResponse({'error': 'image result unverified'}, status_code=503)
    class McpEndpoint:
        async def __call__(self, scope, receive, send):
            await manager.handle_request(scope, receive, send)
    app = Starlette(routes=[Route('/health', health), Route('/mcp/fetch/artifact', artifact_response), Route('/mcp/fetch/pool', execution_pool), Route('/mcp/fetch/install-controller', install_controller),
        Route('/mcp/fetch/images', image_inventory), Route('/mcp/fetch/images/prepare', image_control, methods=['POST']), Route('/mcp/fetch/images/delete', image_control, methods=['POST']), Route('/mcp/fetch/images/receipt', image_control, methods=['POST']),
        Route('/mcp/fetch/cancel', cancel, methods=['POST']), Route('/mcp/fetch/receipts', receipt), Route('/mcp/fetch/mcp', McpEndpoint(), methods=['GET', 'POST', 'DELETE'])], lifespan=lifespan)

    async def authenticated(scope, receive, send):
        if scope['type'] != 'http' or scope['path'] == '/health':
            return await app(scope, receive, send)
        try:
            values = [v.decode('ascii') for k, v in scope['headers'] if k.lower() == b'authorization']
            if len(values) != 1 or not values[0].startswith('Bearer '):
                raise ValueError('authorization')
            identity = decode_credential(values[0][7:], secret)
            if 'pool_id' in identity and (not hasattr(executor, 'store') or identity['pool_id'] != executor.store.pool_id):
                raise ValueError('execution pool changed')
            controller_query = scope['path'] == '/mcp/fetch/install-controller'
            image_scope = {'/mcp/fetch/images': 'image-inspect', '/mcp/fetch/images/prepare': 'image-prepare', '/mcp/fetch/images/delete': 'image-delete', '/mcp/fetch/images/receipt': 'image-receipt'}.get(scope['path'])
            control = scope['path'] in ('/mcp/fetch/cancel', '/mcp/fetch/receipts') or controller_query or image_scope is not None
            allowed_scopes = (image_scope,) if image_scope else ('install-control',) if controller_query else ('execute', 'control') if control else ('install',) if scope['path'] == '/mcp/fetch/artifact' else ('execute',)
            revoked = executor.is_revoked(identity) if hasattr(executor, 'is_revoked') else identity['nonce'] in executor.revoked
            if identity['scope'] not in allowed_scopes or not control and revoked:
                raise ValueError('scope')
        except sqlite3.Error:
            return await JSONResponse({'error': 'execution state unavailable'}, status_code=503)(scope, receive, send)
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
