"""Validate that a rehearsal cannot inherit production identities or unsafe host resources."""
import copy
import importlib.util
import io
from pathlib import Path
import tarfile

import pytest

SOURCE = Path(__file__).resolve().parents[1]/'script/docker/application-rehearsal.py'
spec = importlib.util.spec_from_file_location('application_rehearsal', SOURCE)
rehearsal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rehearsal)
PROJECT = 'doorhandle-rehearsal-0123456789ab'


def sample():
    return {'name': 'doorhandlecatch-monolith',
            'volumes': {'data': {'name': 'doorhandlecatch-monolith_data', 'external': True}},
            'networks': {'main': {'name': 'doorhandlecatch-monolith_main'},
                         'mcp-exec': {'name': 'doorhandlecatch-mcp-exec', 'internal': True}},
            'services': {
                'backend': {'image': 'old', 'environment': {'JWT_SECRET': 'production-jwt', 'DB_PASSWORD': 'production-db',
                    'AGENT_MCP_GATEWAY_SECRET': 'production-mcp', 'AGENT_MCP_GATEWAY_KEY': 'production-gateway',
                    'DEEPSEEK_API_KEY': 'provider-only'}, 'ports': [{'target': 8080, 'published': '8080'}],
                    'networks': {'main': None}, 'volumes': [{'type': 'volume', 'source': 'data', 'target': '/data'}]},
                'mysql': {'image': 'mysql', 'environment': {}, 'command': ['--default-time-zone=+08:00']},
                'mem0': {'image': 'old', 'environment': {'MEM0_BRIDGE_TOKEN': 'production-bridge'}},
                'nginx': {'image': 'old', 'environment': {}},
                'mcp-runner': {'image': 'fixed', 'environment': {'MCP_EXEC_NETWORK': 'doorhandlecatch-mcp-exec', 'MCP_RUNNER_SECRET': 'production-mcp'},
                               'volumes': [{'type': 'bind', 'source': '/var/run/docker.sock', 'target': '/var/run/docker.sock'}]},
                'detection-worker': {'image': 'fixed', 'volumes': [{'type': 'bind', 'source': '/models', 'target': '/models', 'read_only': True}]}}}


def config():
    return rehearsal.isolated_config(sample(), PROJECT, 18089, {'backend': 'sha256:'+'a'*64}, 'doorhandledb')


def test_config_replaces_credentials_networks_storage_and_listener_without_mutating_source():
    source = sample()
    original = copy.deepcopy(source)
    value = rehearsal.isolated_config(source, PROJECT, 18089, {'backend': 'sha256:'+'a'*64}, 'doorhandledb')
    assert source == original
    assert value['volumes']['data']['name'] == PROJECT+'_data' and not value['volumes']['data'].get('external')
    assert all(resource['name'].startswith(PROJECT+'-') for resource in value['networks'].values())
    assert value['networks']['mcp-exec']['internal']
    backend = value['services']['backend']['environment']
    mysql = value['services']['mysql']['environment']
    assert backend['DB_PASSWORD'] == mysql['MYSQL_PASSWORD'] and backend['DB_PASSWORD'] != mysql['MYSQL_ROOT_PASSWORD']
    assert 'mysql:3306/doorhandledb?' in backend['DB_URL'] and backend['DB_USERNAME'] == mysql['MYSQL_USER']
    assert backend['MEM0_BRIDGE_TOKEN'] == value['services']['mem0']['environment']['MEM0_BRIDGE_TOKEN']
    assert backend['AGENT_MCP_GATEWAY_SECRET'] == value['services']['mcp-runner']['environment']['MCP_RUNNER_SECRET']
    assert value['services']['mcp-runner']['environment']['MCP_EXEC_NETWORK'] == PROJECT+'-mcp-exec'
    assert backend['DEEPSEEK_API_KEY'] == 'provider-only'
    assert all(not environment.startswith('production-') for key, environment in backend.items() if key.endswith(('PASSWORD', 'SECRET', 'TOKEN', 'KEY')))
    assert value['services']['mysql']['command'][-1] == '--event-scheduler=OFF'
    assert 'ports' not in value['services']['backend']
    assert value['services']['nginx']['ports'] == [{'target': 80, 'published': '18089', 'host_ip': '127.0.0.1', 'protocol': 'tcp'}]
    assert config()['services']['backend']['environment']['JWT_SECRET'] != backend['JWT_SECRET']


@pytest.mark.parametrize('damage', ['production-project', 'external-volume', 'shared-network', 'unknown-volume', 'host-root',
    'writable-model', 'public-port', 'privileged', 'host-network', 'host-pid', 'inherited-volumes', 'secrets'])
def test_unowned_or_unsafe_resources_rejected_before_docker(damage):
    value = config()
    if damage == 'production-project': value['name'] = 'doorhandlecatch-monolith'
    elif damage == 'external-volume': value['volumes']['data']['external'] = True
    elif damage == 'shared-network': value['networks']['main']['name'] = 'doorhandlecatch-mcp-exec'
    elif damage == 'unknown-volume': value['services']['backend']['volumes'][0]['source'] = 'production'
    elif damage == 'host-root': value['services']['backend']['volumes'] = [{'type': 'bind', 'source': '/', 'target': '/host'}]
    elif damage == 'writable-model': value['services']['detection-worker']['volumes'][0]['read_only'] = False
    elif damage == 'public-port': value['services']['nginx']['ports'][0]['host_ip'] = '0.0.0.0'
    elif damage == 'privileged': value['services']['backend']['privileged'] = True
    elif damage == 'host-network': value['services']['backend']['network_mode'] = 'host'
    elif damage == 'host-pid': value['services']['backend']['pid'] = 'host'
    elif damage == 'inherited-volumes': value['services']['backend']['volumes_from'] = ['production']
    elif damage == 'secrets': value['secrets'] = {'production-secret': {'external': True}}
    with pytest.raises(RuntimeError): rehearsal.validate_isolation(value, PROJECT)


@pytest.mark.parametrize('project', ['doorhandlecatch-monolith', 'other', 'doorhandle-rehearsal-../bad', PROJECT.upper()])
def test_invalid_project_identity_rejected(project):
    with pytest.raises(RuntimeError): rehearsal.isolated_config(sample(), project, 18089, {}, 'doorhandledb')


@pytest.mark.parametrize('name,kind', [('../outside', tarfile.REGTYPE), ('/outside', tarfile.REGTYPE),
    ('a\\outside', tarfile.REGTYPE), ('link', tarfile.SYMTYPE), ('link', tarfile.LNKTYPE), ('device', tarfile.CHRTYPE)])
def test_source_archive_rejects_traversal_links_and_special_files(tmp_path, name, kind):
    file = tmp_path/'source.tar.gz'
    with tarfile.open(file, 'w:gz') as archive:
        entry = tarfile.TarInfo(name)
        entry.type = kind
        if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE): entry.linkname = '/outside'
        archive.addfile(entry)
    target = tmp_path/'source'
    target.mkdir()
    with pytest.raises(RuntimeError): rehearsal.extract_source(file, target)
    assert list(target.iterdir()) == []


def test_source_archive_accepts_actual_git_layout(tmp_path):
    file = tmp_path/'source.tar.gz'
    with tarfile.open(file, 'w:gz') as archive:
        entry = tarfile.TarInfo('README.md')
        entry.size = 4
        archive.addfile(entry, io.BytesIO(b'test'))
    target = tmp_path/'source'
    target.mkdir()
    rehearsal.extract_source(file, target)
    assert (target/'README.md').read_bytes() == b'test'


def test_cleanup_refuses_foreign_volume_even_if_compose_project_name_matches(tmp_path):
    class Ops:
        class OpsError(RuntimeError): pass
        def docker(self, *args):
            if args[0] == 'ps': return b''
            assert args[:2] == ('volume', 'inspect')
            return b'[{"Labels":{"io.doorhandle.rehearsal":"another-project"}}]'
    run = rehearsal.Rehearsal.__new__(rehearsal.Rehearsal)
    run.config, run.project, run.ops = config(), PROJECT, Ops()
    run.dc = lambda *args: pytest.fail('Must not call compose down on an unowned resource')
    with pytest.raises(RuntimeError, match='Cleanup ownership'): run.cleanup()


def test_production_identity_change_blocks_acceptance():
    original = {'id': 'original', 'image': 'immutable', 'running': True, 'mounts': []}
    class Ops:
        def inventory(self): return [{**original, 'id': 'unexpected'}]
    run = rehearsal.Rehearsal.__new__(rehearsal.Rehearsal)
    run.ops, run.baseline = Ops(), [original]
    run.report = {}
    run.persist = lambda: None
    run.check = lambda name, condition: rehearsal.require(condition, name)
    with pytest.raises(RuntimeError, match='Production containers'): run.production_unchanged()
    assert run.report['productionChanged'] is True


def test_foreign_container_rejected_before_compose_down():
    class Ops:
        def docker(self, *args):
            return b'foreign-id' if args[0] == 'ps' else b'[{"Config":{"Labels":{}}}]'
    run = rehearsal.Rehearsal.__new__(rehearsal.Rehearsal)
    run.config, run.project, run.ops = config(), PROJECT, Ops()
    run.dc = lambda *args: pytest.fail('Foreign container must not be removed')
    with pytest.raises(RuntimeError, match='container ownership'): run.cleanup()
