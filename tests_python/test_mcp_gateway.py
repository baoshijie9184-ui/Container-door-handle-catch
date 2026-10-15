"""Exercise signed identities through real MCP HTTP dispatch, without Docker or paid models."""
import base64
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import socket
import time
import uuid

import anyio
import httpx
import pytest
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mcp_gateway_runner', ROOT / 'deploy/mcp/runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
SECRET = 'test-secret-with-at-least-32-bytes-000'
IMAGE = 'sha256:' + 'a' * 64


def credential(owner=11, scope='execute', **overrides):
    now = int(time.time())
    identity = dict(aud='doorhandle-mcp-runner', owner=owner, scope=scope, iat=now, exp=now+60,
                    nonce=str(uuid.uuid4()), installation=str(uuid.uuid4()))
    identity.update(overrides)
    body = base64.urlsafe_b64encode(json.dumps(identity).encode()).decode().rstrip('=')
    signature = base64.urlsafe_b64encode(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest()).decode().rstrip('=')
    return body + '.' + signature


def test_credentials_require_signature_scope_expiry_and_canonical_owner():
    assert runner.decode_credential(credential(), SECRET)['owner'] == 11
    for token in [credential()+'x', credential(owner=True), credential(owner=0), credential(scope='shell'),
                  credential(exp=int(time.time())-1), credential(exp=int(time.time())+120), credential(nonce='bad')]:
        with pytest.raises((ValueError, TypeError)):
            runner.decode_credential(token, SECRET)


@pytest.mark.parametrize('url', ['http://localhost/', 'http://169.254.169.254/', 'http://example.com:8080/',
    'https://user:pass@example.com/', 'https://example.com/?api_key=secret', 'file:///etc/passwd',
    'http://127.0.0.1/', 'http://[::1]/', 'http://192.168.1.1/', 'http://100.100.100.200/'])
def test_private_destinations_and_secret_urls_denied(url):
    def resolver(host, port, **kwargs):
        try:
            import ipaddress
            ipaddress.ip_address(host)
            address = host
        except ValueError:
            address = '127.0.0.1' if host == 'localhost' else '93.184.216.34'
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, port))]
    with pytest.raises(ValueError):
        runner.validate_arguments({'url': url}, resolver)


def test_fixed_container_command_has_no_user_files_secrets_or_socket():
    executor = runner.DockerExecutor(IMAGE, 'doorhandlecatch-mcp-exec', 'http://mcp-egress:3128')
    identity = runner.decode_credential(credential(), SECRET)
    args = executor.arguments(identity, 'dh-mcp-'+'a'*32+'-'+'b'*32)
    assert '--read-only' in args and '--cap-drop=ALL' in args and '--memory=256m' in args
    assert args[-5:] == [IMAGE, '/opt/fetch/.venv/bin/python', '-I', '-m', 'mcp_server_fetch']
    assert not any(value in args for value in ['--volume', '-v', '--privileged', '/var/run/docker.sock'])
    assert all('API_KEY' not in value and 'PASSWORD' not in value for value in args)
    with pytest.raises(ValueError):
        runner.DockerExecutor('fetch:latest', 'anything', 'http://mcp-egress:3128')


def test_standalone_routes_preserve_protocols_and_do_not_store_provider_keys(tmp_path):
    import yaml
    spec = importlib.util.spec_from_file_location('gateway_configuration', ROOT / 'deploy/mcp/configure.py')
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    (tmp_path/'configmaps').mkdir()
    (tmp_path/'configmaps/higress-config.yaml').write_text(yaml.safe_dump({'data': {'mesh': 'rootNamespace: higress-system\n'}}))
    env = {'AGENT_MCP_GATEWAY_KEY': 'service-key-'+'a'*32, 'OPENAI_BASE_URL': 'https://custom.example/v1',
           'MCP_SERVER_PUBLIC_IPS': '101.201.227.35', 'MCP_EGRESS_CONFIG': str(tmp_path/'egress/server-deny.conf'),
           'OPENAI_API_KEY': 'never-write-provider-secret'}
    config.configure(tmp_path, env)
    registry = yaml.safe_load((tmp_path/'mcpbridges/default.yaml').read_text())
    assert any(value['name']=='openai' and value['domain']=='custom.example' for value in registry['spec']['registries'])
    route = yaml.safe_load((tmp_path/'ingresses/llm-openai.yaml').read_text())
    assert route['metadata']['annotations']['higress.io/rewrite-target'] == '/$2'
    content = '\n'.join(path.read_text() for path in tmp_path.rglob('*.yaml'))
    assert 'never-write-provider-secret' not in content and '%REQ(:PATH)%' not in content
    assert '101.201.227.35' in (tmp_path/'egress/server-deny.conf').read_text()


class FakeExecutor:
    def __init__(self):
        self.revoked = {}
        self.calls = []
    async def execute(self, identity, args):
        self.calls.append(identity)
        return runner.types.CallToolResult(content=[runner.types.TextContent(type='text', text=str(identity['owner']))])
    async def cancel(self, identity):
        self.revoked[identity['nonce']] = identity['exp']
    async def reap(self):
        await anyio.sleep_forever()


def test_http_mcp_dispatch_binds_each_request_owner_and_revokes_cancelled_credential(tmp_path, monkeypatch):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(dict(version=runner.VERSION, packageSha256=runner.PACKAGE_SHA, artifacts=[], licenses=[])))
    executor = FakeExecutor()
    monkeypatch.setattr(runner, 'validate_arguments', lambda args: args)
    app = runner.create_app(SECRET, IMAGE, 'doorhandlecatch-mcp-exec', 'http://mcp-egress:3128', str(manifest), executor)
    def headers(token):
        return {'Authorization': 'Bearer '+token, 'Accept': 'application/json, text/event-stream'}
    with TestClient(app, base_url='http://localhost:8080') as client:
        assert client.get('/health').status_code == 200
        assert client.get('/mcp/fetch/artifact').status_code == 401
        assert client.get('/mcp/fetch/artifact', headers=headers(credential())).status_code == 401
        assert client.get('/mcp/fetch/artifact', headers=headers(credential(scope='install'))).json()['image'] == IMAGE
        tokens = [credential(owner=11), credential(owner=22)]
        for index, token in enumerate(tokens):
            result = client.post('/mcp/fetch/mcp', headers=headers(token), json={
                'jsonrpc': '2.0', 'id': index+1, 'method': 'tools/call',
                'params': {'name': 'fetch', 'arguments': {'url': 'https://example.com'}}})
            assert result.status_code == 200, result.text
            assert result.json()['result']['content'][0]['text'] == str([11,22][index]), result.text
        assert [value['owner'] for value in executor.calls] == [11,22]
        assert client.post('/mcp/fetch/cancel', headers=headers(tokens[0])).status_code == 200
        assert client.post('/mcp/fetch/mcp', headers=headers(tokens[0]), json={}).status_code == 401
        assert client.get('/mcp/fetch/artifact', headers=headers(credential(scope='install')+'x')).status_code == 401
