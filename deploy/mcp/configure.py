"""Generate our standalone Higress resources; never include provider keys or prompts.

Resource format follows Apache-2.0 Higress standalone 2.2.5 defaults.
https://github.com/higress-group/higress-standalone
"""
import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit
import yaml


def resource(kind, name, spec=None, api='networking.k8s.io/v1'):
    value = {'apiVersion': api, 'kind': kind, 'metadata': {'name': name, 'namespace': 'higress-system',
        'creationTimestamp': '2000-01-01T00:00:00Z', 'resourceVersion': '1'}}
    if spec is not None:
        value['spec'] = spec
    return value


def configure(root, env):
    root = Path(root)
    key = env['AGENT_MCP_GATEWAY_KEY']
    if len(key) < 32:
        raise ValueError('MCP gateway key must contain at least 32 characters')
    def write(folder, name, value):
        target = root / folder / (name + '.yaml')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(value, sort_keys=False), encoding='utf-8')
    # Remove the default catch-all console route; management UI stays disabled.
    (root / 'ingresses/higress-console.yaml').unlink(missing_ok=True)
    registries = [{'name': 'mcp-runner', 'type': 'dns', 'domain': 'mcp-runner', 'port': 8080}]
    def ingress(name, destination, path, annotations=None):
        value = resource('Ingress', name, {'ingressClassName': 'higress', 'rules': [{'http': {'paths': [{
            'path': path, 'pathType': 'ImplementationSpecific' if annotations else 'Prefix',
            'backend': {'resource': {'apiGroup': 'networking.higress.io', 'kind': 'McpBridge', 'name': 'default'}}}]}}]})
        value['metadata']['annotations'] = {'higress.io/destination': destination, 'higress.io/timeout': '65',
            'higress.io/proxy-next-upstream-tries': '0', **(annotations or {})}
        write('ingresses', name, value)
    ingress('mcp-fetch', 'mcp-runner.dns', '/mcp/fetch')
    defaults = {'openai': 'https://api.openai.com/v1', 'deepseek': 'https://api.deepseek.com',
                'dashscope': 'https://dashscope.aliyuncs.com/compatible-mode/v1'}
    for provider, default in defaults.items():
        url = urlsplit(env.get(provider.upper() + '_BASE_URL', default))
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('HTTPS model upstream without embedded credentials is required')
        registries.append({'name': provider, 'type': 'dns', 'domain': url.hostname, 'port': url.port or 443})
        ingress('llm-' + provider, provider + '.dns', '/llm/' + provider + '(/|$)(.*)', {
            'higress.io/use-regex': 'true', 'higress.io/rewrite-target': '/$2',
            'higress.io/upstream-vhost': url.hostname, 'higress.io/backend-protocol': 'HTTPS'})
    write('mcpbridges', 'default', resource('McpBridge', 'default', {'registries': registries}, 'networking.higress.io/v1'))
    # Load the bundled, versioned plugin from the all-in-one image, without registry downloads.
    write('wasmplugins', 'mcp-key-auth', resource('WasmPlugin', 'mcp-key-auth', {
        'url': 'http://127.0.0.1:8002/plugins/key-auth/2.0.0/plugin.wasm',
        'phase': 'AUTHN', 'priority': 310, 'defaultConfigDisable': False,
        'defaultConfig': {'global_auth': False, 'in_header': True, 'in_query': False,
            'keys': ['x-mcp-gateway-key'], 'consumers': [{'name': 'doorhandle-backend', 'credential': key}]},
        'matchRules': [{'ingress': ['higress-system/mcp-fetch'], 'config': {'allow': ['doorhandle-backend']}}]
    }, 'extensions.higress.io/v1alpha1'))
    target = root / 'configmaps/higress-config.yaml'
    config = yaml.safe_load(target.read_text())
    mesh = yaml.safe_load(config['data']['mesh'])
    # Omit path/query, headers, bodies, tokens and AI log filter state.
    mesh['accessLogFormat'] = '{"route":"%ROUTE_NAME%","status":"%RESPONSE_CODE%","duration_ms":"%DURATION%","request_id":"%REQ(X-REQUEST-ID)%"}\n'
    config['data']['mesh'] = yaml.safe_dump(mesh, sort_keys=False)
    write('configmaps', 'higress-config', config)
    deny = Path(env.get('MCP_EGRESS_CONFIG', '/egress/server-deny.conf'))
    deny.parent.mkdir(parents=True, exist_ok=True)
    addresses = [str(ipaddress.ip_address(value.strip())) for value in env['MCP_SERVER_PUBLIC_IPS'].split(',')]
    deny.write_text('acl server_dst dst ' + ' '.join(addresses) + '\n')


if __name__ == '__main__':
    configure('/data', os.environ)
