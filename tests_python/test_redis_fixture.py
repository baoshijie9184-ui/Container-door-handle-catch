"""Synthetic Redis lifecycle contracts; execution belongs to the ECS verifier."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

FILE = Path(__file__).resolve().parents[1] / 'script/jenkins/redis-fixture.py'
SPEC = importlib.util.spec_from_file_location('owned_redis_fixture', FILE)
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)
CONTEXT = {'release': 'ci-1-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64,
           'identity': {'executionLocation': 'ECS', 'instanceId': 'i-fixture123', 'machineId': 'c' * 32}}
FORMAL_ID = 'f' * 64
OWN_ID = 'd' * 64
IMAGE = 'sha256:' + 'e' * 64
RUN_ID = '1' * 40
REAL_QUERY = fixture.Fixture.query


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(fixture.os, 'getuid', lambda: 1000)
    (tmp_path / 'work').mkdir()
    value = fixture.Fixture(tmp_path.resolve(), deepcopy(CONTEXT))
    value.image, value.container, value.port, value.version = IMAGE, OWN_ID, '35001', '7.4.6'
    identity = {'runId': RUN_ID, 'version': '7.4.6', 'mode': 'standalone', 'port': '6379',
                'settings': dict(fixture.SETTINGS)}
    row = {'Id': OWN_ID, 'Name': '/' + value.name, 'Image': IMAGE,
        'Config': {'User': '1000:1000', 'Entrypoint': [fixture.ENTRYPOINT], 'WorkingDir': '/data',
            'Cmd': value._command(), 'Labels': {fixture.LABEL: value.token,
                'io.doorhandle.release': CONTEXT['release'], 'io.doorhandle.commit': CONTEXT['commit'],
                'io.doorhandle.source': CONTEXT['sourceSha256']}},
        'HostConfig': {'NetworkMode': 'bridge', 'RestartPolicy': {'Name': 'no'}, 'Privileged': False,
            'ReadonlyRootfs': True, 'Memory': fixture.MEMORY, 'MemorySwap': fixture.MEMORY,
            'NanoCpus': 500000000, 'PidsLimit': 64, 'CapDrop': ['ALL'], 'CapAdd': None,
            'Devices': [], 'Binds': None, 'SecurityOpt': ['no-new-privileges:true'], 'Tmpfs': value._tmpfs(),
            'LogConfig': {'Type': 'json-file', 'Config': {'max-size': '1m', 'max-file': '1'}},
            'PortBindings': {'6379/tcp': [{'HostIp': '127.0.0.1', 'HostPort': ''}]}},
        'NetworkSettings': {'Ports': {'6379/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '35001'}]}},
        'Mounts': [], 'State': {'Running': False, 'Restarting': False, 'OOMKilled': False, 'Pid': 0}}
    result = SimpleNamespace(value=value, row=row, identity=identity, calls=[], present=False, formal_ids=[FORMAL_ID],
        image_metadata={'Id': IMAGE, 'RedisVersion': ['REDIS_VERSION=7.4.6']})

    def docker(*args):
        result.calls.append(args)
        if args[0] == 'ps':
            if '--filter' in args:
                return '\n'.join(result.formal_ids).encode()
            assert args == ('ps', '-a', '--format', '{{.Names}}')
            return (value.name + '\n').encode() if result.present else b''
        if args[:3] == ('inspect', '--format', fixture.FORMAL_PROJECTION):
            assert args[-1] == FORMAL_ID
            return json.dumps({'Id': FORMAL_ID, 'Image': IMAGE, 'Project': fixture.PROJECT, 'Service': 'redis'}).encode()
        if args[:4] == ('image', 'inspect', '--format', fixture.IMAGE_PROJECTION):
            assert args[-1] == IMAGE
            return json.dumps(result.image_metadata).encode()
        if args[0] == 'inspect':
            assert args[1] in (OWN_ID, value.name)
            return json.dumps([result.row]).encode()
        if args[0] == 'create':
            result.present = True
            return OWN_ID.encode()
        if args[0] == 'start':
            assert args == ('start', OWN_ID)
            row['State'].update(Running=True, Pid=1234)
            return b''
        if args[0] == 'stop':
            assert args == ('stop', '--time', '15', OWN_ID)
            row['State'].update(Running=False, Pid=0)
            return b''
        if args[0] == 'rm':
            assert args == ('rm', OWN_ID)
            result.present = False
            return b''
        raise AssertionError('Unexpected Docker operation ' + repr(args))

    monkeypatch.setattr(value, 'docker', docker)
    monkeypatch.setattr(value, '_capacity', lambda: {'memoryAvailableBytes': 8 * fixture.GIB,
                                                   'diskAvailableBytes': 8 * fixture.GIB})
    monkeypatch.setattr(value, 'query', lambda full=False: deepcopy(result.identity))
    monkeypatch.setattr(fixture.os, 'statvfs', lambda _: SimpleNamespace(f_bavail=8 * fixture.GIB, f_frsize=1))

    def logs(command, **options):
        assert command == ['docker', 'logs', '--timestamps', OWN_ID]
        assert not result.row['State']['Running']
        assert (value.folder / 'stopped-container.json').is_file()
        return SimpleNamespace(returncode=0, stdout=b'synthetic Redis stdout\n', stderr=b'synthetic Redis stderr\n')

    monkeypatch.setattr(fixture.subprocess, 'run', logs)
    return result


def test_constructor_creates_only_private_owner_metadata(state):
    value = state.value
    assert not value.started and not value.ready and not value.cleaned
    assert value.environment == {} and state.calls == []
    assert value.folder.stat().st_mode & 0o777 == 0o700
    owner = value.folder / 'owner.json'
    assert owner.stat().st_mode & 0o777 == 0o600
    assert json.loads(owner.read_text()) == value.owner
    assert sorted(x.name for x in value.folder.iterdir()) == ['owner.json']


@pytest.mark.parametrize('damage', ['local', 'uid', 'commit', 'release', 'source'])
def test_constructor_rejects_wrong_context_before_creating_resources(tmp_path, monkeypatch, damage):
    (tmp_path / 'work').mkdir(); context = deepcopy(CONTEXT)
    monkeypatch.setattr(fixture.os, 'getuid', lambda: 0 if damage == 'uid' else 1000)
    if damage == 'local': context['identity']['executionLocation'] = 'WORKSTATION'
    if damage == 'commit': context['commit'] = 'not-fixed'
    if damage == 'release': context['release'] = 'ci-1-' + 'c' * 12
    if damage == 'source': context['sourceSha256'] = 'short'
    with mock.patch.object(fixture.subprocess, 'run') as command, pytest.raises(ValueError):
        fixture.Fixture(tmp_path.resolve(), context)
    command.assert_not_called()
    assert not (tmp_path / 'work/redis-fixture').exists()


def test_prepare_uses_only_formal_image_projection_and_fresh_bounded_server(state):
    value = state.value
    assert value.prepare() == {'DOORHANDLE_CACHE_REDIS_TEST_HOST': '127.0.0.1',
        'DOORHANDLE_CACHE_REDIS_TEST_PORT': '35001', 'DOORHANDLE_CACHE_REDIS_TEST_DATABASE': '0',
        'DOORHANDLE_REQUIRE_REDIS_TESTS': 'true'}
    assert set(value.environment) == fixture.ENVIRONMENT and value.run_id == RUN_ID and value.ready
    create = next(args for args in state.calls if args[0] == 'create')
    assert create[create.index('--pull') + 1] == 'never'
    assert create[create.index('--publish') + 1] == '127.0.0.1::6379'
    assert create[create.index('--user') + 1] == '1000:1000'
    assert create[create.index('--memory') + 1] == create[create.index('--memory-swap') + 1] == '256m'
    assert create[create.index('--cpus') + 1] == '0.5' and create[create.index('--pids-limit') + 1] == '64'
    assert create[create.index('--entrypoint') + 1] == fixture.ENTRYPOINT
    assert create[create.index('--save') + 1] == '' and create[create.index('--appendonly') + 1] == 'no'
    assert create[create.index(IMAGE) + 1:] == tuple(value._command())
    assert '--env' not in create and '--mount' not in create and '--volume' not in create
    assert [(args[0], args[-1]) for args in state.calls if FORMAL_ID in args] == [('inspect', FORMAL_ID)]
    assert all(args[:3] == ('inspect', '--format', fixture.FORMAL_PROJECTION)
               for args in state.calls if FORMAL_ID in args)
    assert '.Config.Env' not in fixture.FORMAL_PROJECTION and '.Mounts' not in fixture.FORMAL_PROJECTION
    assert [args for args in state.calls if args[0] == 'image'] == [
        ('image', 'inspect', '--format', fixture.IMAGE_PROJECTION, IMAGE)]
    assert 'REDIS_VERSION' in fixture.IMAGE_PROJECTION and '{{json .Config.Env}}' not in fixture.IMAGE_PROJECTION
    assert not any(args[0] in ('exec', 'pull', 'volume', 'network') for args in state.calls)


@pytest.mark.parametrize('field', ['memoryAvailableBytes', 'diskAvailableBytes'])
def test_capacity_rejects_before_formal_read_or_create(state, monkeypatch, field):
    monkeypatch.setattr(state.value, '_capacity', lambda: {field: 0,
        ('diskAvailableBytes' if field == 'memoryAvailableBytes' else 'memoryAvailableBytes'): 8 * fixture.GIB})
    with pytest.raises(ValueError): state.value.prepare()
    assert state.calls == [] and not state.value.started


@pytest.mark.parametrize('ids', [[], [FORMAL_ID, OWN_ID], ['short']])
def test_formal_image_selection_must_be_unique(state, ids):
    state.formal_ids = ids
    with pytest.raises(ValueError): state.value.prepare()
    assert not state.value.started and not any(x[0] == 'create' for x in state.calls)


@pytest.mark.parametrize('field,value', [('Id', 'short'), ('Image', 'redis:latest'),
    ('Project', 'other-project'), ('Service', 'mysql'), ('Env', ['never-read'])])
def test_formal_projection_rejects_wrong_identity_or_extra_fields(field, value):
    row = {'Id': FORMAL_ID, 'Image': IMAGE, 'Project': fixture.PROJECT, 'Service': 'redis'}
    row[field] = value
    with pytest.raises(ValueError): fixture.formal_projection(row)


@pytest.mark.parametrize('damage', ['cid', 'name', 'image', 'token', 'release', 'commit', 'source',
    'user', 'entrypoint', 'command', 'workdir', 'network', 'restart', 'privileged', 'rootfs',
    'memory', 'swap', 'cpu', 'pids', 'capdrop', 'capadd', 'device', 'bind', 'security', 'tmpfs',
    'log', 'requested-port', 'actual-port', 'persistent-volume'])
def test_ownership_rejects_each_widened_identity_or_resource(state, damage):
    row = state.row; row['State'].update(Running=True, Pid=1234)
    if damage == 'cid': row['Id'] = 'c' * 64
    elif damage == 'name': row['Name'] = '/formal-redis'
    elif damage == 'image': row['Image'] = 'sha256:' + '0' * 64
    elif damage in ('token', 'release', 'commit', 'source'):
        key = fixture.LABEL if damage == 'token' else 'io.doorhandle.' + damage
        row['Config']['Labels'][key] = 'changed'
    elif damage in ('user', 'entrypoint', 'command', 'workdir'):
        key, changed = {'user': ('User', '0:0'), 'entrypoint': ('Entrypoint', ['sh']),
            'command': ('Cmd', ['--appendonly', 'yes']), 'workdir': ('WorkingDir', '/')}[damage]
        row['Config'][key] = changed
    elif damage == 'actual-port': row['NetworkSettings']['Ports']['6379/tcp'][0]['HostIp'] = '0.0.0.0'
    elif damage == 'persistent-volume': row['Mounts'] = [{'Type': 'volume', 'Destination': '/data', 'Name': 'production'}]
    else:
        key, changed = {'network': ('NetworkMode', 'host'), 'restart': ('RestartPolicy', {'Name': 'always'}),
            'privileged': ('Privileged', True), 'rootfs': ('ReadonlyRootfs', False), 'memory': ('Memory', 0),
            'swap': ('MemorySwap', -1), 'cpu': ('NanoCpus', 0), 'pids': ('PidsLimit', 0),
            'capdrop': ('CapDrop', []), 'capadd': ('CapAdd', ['SYS_ADMIN']), 'device': ('Devices', ['/dev/sda']),
            'bind': ('Binds', ['/production:/data']), 'security': ('SecurityOpt', []), 'tmpfs': ('Tmpfs', {}),
            'log': ('LogConfig', {}), 'requested-port': ('PortBindings', {'6379/tcp': [{'HostIp': '0.0.0.0', 'HostPort': ''}]})}[damage]
        row['HostConfig'][key] = changed
    with pytest.raises(ValueError): state.value.owned()


@pytest.mark.parametrize('mounts', [[], [{'Type': 'tmpfs', 'Destination': '/data'}]])
def test_legacy_tmpfs_inspect_forms_remain_accepted_without_a_volume(state, mounts):
    state.row['Mounts'] = mounts
    assert state.value.owned() == state.row


@pytest.mark.parametrize('damage', ['runId', 'version', 'mode', 'port', *fixture.SETTINGS])
def test_effective_identity_and_persistence_cannot_change(state, damage):
    value = state.value; value.run_id = RUN_ID
    identity = deepcopy(state.identity)
    if damage in fixture.SETTINGS: identity['settings'][damage] = 'changed'
    else: identity[damage] = 'changed'
    with pytest.raises(ValueError): value._identity(identity, full=True)


@pytest.mark.parametrize('metadata', [
    {'Id': IMAGE, 'RedisVersion': []},
    {'Id': IMAGE, 'RedisVersion': ['REDIS_VERSION=7.4.6', 'REDIS_VERSION=7.4.6']},
    {'Id': IMAGE, 'RedisVersion': ['REDIS_VERSION=unfixed']},
    {'Id': 'sha256:' + '0' * 64, 'RedisVersion': ['REDIS_VERSION=7.4.6']},
    {'Id': IMAGE, 'RedisVersion': ['REDIS_VERSION=7.4.6'], 'Other': 'never-read'},
])
def test_immutable_image_version_must_be_exact_before_create(state, metadata):
    state.image_metadata = metadata
    with pytest.raises(ValueError): state.value.prepare()
    assert not state.value.started and not any(x[0] == 'create' for x in state.calls)


def test_actual_image_version_is_not_guessed_from_compose(state):
    state.image_metadata['RedisVersion'] = ['REDIS_VERSION=7.2.9']
    state.identity['version'] = '7.2.9'
    state.value.prepare()
    assert state.value.version == '7.2.9'
    state.identity['version'] = '7.4.6'
    with pytest.raises(ValueError): state.value.check()


def cli_responses(state, monkeypatch, server=None, settings=None):
    if server is None:
        server = '# Server\r\nredis_version:7.4.6\r\nredis_mode:standalone\r\ntcp_port:6379\r\nrun_id:' + RUN_ID + '\r\n'
    if settings is None:
        settings = [x for pair in fixture.SETTINGS.items() for x in pair]
    calls = []
    prefix = ('exec', OWN_ID, 'redis-cli', '-h', '127.0.0.1', '-p', '6379', '-n', '0', '-2')
    def docker(*args):
        calls.append(args)
        assert args[:len(prefix)] == prefix
        if args[len(prefix):] == ('--raw', 'INFO', 'server'):
            return server if isinstance(server, bytes) else server.encode()
        assert args[len(prefix):] == ('--json', 'CONFIG', 'GET', *fixture.SETTINGS)
        return json.dumps(settings).encode()
    monkeypatch.setattr(state.value, 'docker', docker)
    return calls


def test_bundled_cli_reads_full_identity_only_from_owned_container(state, monkeypatch):
    calls = cli_responses(state, monkeypatch)
    assert REAL_QUERY(state.value, full=True) == state.identity
    assert len(calls) == 2 and all(FORMAL_ID not in call for call in calls)
    assert not any(word in call for call in calls for word in ('AUTH', 'KEYS', 'SCAN', 'SET', 'FLUSHALL'))


def test_frequent_probe_is_one_info_call_without_config_or_ping(state, monkeypatch):
    calls = cli_responses(state, monkeypatch)
    assert REAL_QUERY(state.value) == {k: v for k, v in state.identity.items() if k != 'settings'}
    assert len(calls) == 1 and calls[0][-2:] == ('INFO', 'server')


@pytest.mark.parametrize('damage', ['invalid-json', 'server-json-quoted', 'server-bound', 'config-map',
    'config-short', 'config-nonstring', 'config-duplicate', 'config-unknown'])
def test_bundled_cli_rejects_invalid_or_ambiguous_json_shape(state, monkeypatch, damage):
    server = None; settings = None
    if damage == 'server-json-quoted': server = json.dumps('# Server\r\nredis_version:7.4.6\r\n')
    if damage == 'server-bound': server = 'x' * 65537
    if damage == 'config-map': settings = dict(fixture.SETTINGS)  # RESP3 is not the selected -2 contract.
    if damage == 'config-short': settings = []
    if damage == 'config-nonstring': settings = [x for pair in fixture.SETTINGS.items() for x in pair]; settings[1] = 42
    if damage == 'config-duplicate': settings = ['save', ''] * len(fixture.SETTINGS)
    if damage == 'config-unknown': settings = [x for pair in fixture.SETTINGS.items() for x in pair]; settings[0] = 'unknown'
    cli_responses(state, monkeypatch, server, settings)
    if damage == 'invalid-json':
        original = state.value.docker
        monkeypatch.setattr(state.value, 'docker', lambda *args: b'NOAUTH not JSON' if '--json' in args else original(*args))
    with pytest.raises(ValueError): REAL_QUERY(state.value, full=True)


def test_cli_cannot_run_without_inspected_owned_cid(state):
    state.value.container = None
    with pytest.raises(ValueError): REAL_QUERY(state.value)
    assert state.calls == []


def test_prepare_retries_only_startup_readback_then_uses_one_check_read(state, monkeypatch):
    calls = []
    def query(full=False):
        calls.append(full)
        if len(calls) == 1: raise ValueError('temporary connection refused')
        return deepcopy(state.identity)
    monkeypatch.setattr(state.value, 'query', query)
    monkeypatch.setattr(fixture.time, 'sleep', lambda _: None)
    state.value.prepare()
    assert calls == [True, True, False]


@pytest.mark.parametrize('damage', ['stopped', 'oom', 'restarting', 'changed-run', 'disk'])
def test_check_refuses_unhealthy_or_replaced_fixture(state, monkeypatch, damage):
    value = state.value; value.ready = True; value.run_id = RUN_ID
    state.row['State'].update(Running=True, Pid=1234)
    if damage == 'stopped': state.row['State'].update(Running=False, Pid=0)
    if damage == 'oom': state.row['State']['OOMKilled'] = True
    if damage == 'restarting': state.row['State']['Restarting'] = True
    if damage == 'changed-run': state.identity['runId'] = '2' * 40
    if damage == 'disk': monkeypatch.setattr(fixture.os, 'statvfs', lambda _: SimpleNamespace(f_bavail=0, f_frsize=1))
    with pytest.raises(ValueError): value.check()


def test_stop_preserves_terminal_originals_removes_only_own_container_and_is_idempotent(state):
    value = state.value; value.prepare()
    result = value.stop()
    assert result['status'] == 'STOPPED' and result['cleanupConfirmed']
    assert result['protocolHealthy'] is True and result['terminalValidationErrorType'] is None
    assert result['identity'] == CONTEXT['identity'] and result['sourceData'] == 'SYNTHETIC_ONLY'
    assert result['persistentVolumes'] is False and result['database'] == 0 and result['providerCalls'] == 0
    assert (value.folder / 'container.stdout.log').read_bytes() == b'synthetic Redis stdout\n'
    assert (value.folder / 'container.stderr.log').read_bytes() == b'synthetic Redis stderr\n'
    assert (value.folder / 'owner.json').is_file() and result['privateOriginals']
    assert json.loads((value.folder / 'before-stop-server.json').read_text()) == state.identity
    assert result['redisVersion'] == '7.4.6'
    calls = list(state.calls)
    assert value.stop() == result and state.calls == calls
    assert [x[-1] for x in state.calls if x[0] in ('stop', 'rm')] == [OWN_ID, OWN_ID]
    assert not any(x[0] in ('exec', 'volume', 'network') for x in state.calls)


def test_unknown_create_is_resolved_by_exact_owned_name(state):
    value = state.value; value.started = True; value.container = None; state.present = True
    state.row['State'].update(Running=True, Pid=1234)
    result = value.stop()
    assert result['containerId'] == OWN_ID and result['cleanupConfirmed']
    assert ('inspect', value.name) in state.calls


def test_failed_create_without_an_object_needs_no_delete(state):
    value = state.value; value.started = True; value.container = None
    result = value.stop()
    assert result['cleanupConfirmed'] and result['containerId'] is None
    assert not any(x[0] in ('stop', 'rm') for x in state.calls)


def test_known_server_cannot_disappear_without_terminal_originals(state):
    state.value.started = True
    with pytest.raises(ValueError, match='without terminal originals'): state.value.stop()
    assert not state.value.cleaned and not any(x[0] in ('stop', 'rm') for x in state.calls)


def test_wrong_owner_is_not_stopped_logged_or_removed(state):
    state.value.started = True; state.present = True
    state.row['Config']['Labels'][fixture.LABEL] = 'foreign'
    with pytest.raises(ValueError): state.value.stop()
    assert not state.value.cleaned and not any(x[0] in ('stop', 'rm') for x in state.calls)


@pytest.mark.parametrize('damage', ['content', 'mode'])
def test_durable_owner_tampering_prevents_all_docker_calls(state, damage):
    path = state.value.folder / 'owner.json'
    if damage == 'content': path.write_text('{}')
    else: path.chmod(0o644)
    with pytest.raises(ValueError): state.value.stop()
    assert state.calls == [] and not state.value.cleaned


def test_logs_failure_keeps_stopped_container_and_retry_does_not_repeat_stop(state, monkeypatch):
    value = state.value; value.prepare()
    with monkeypatch.context() as patch:
        patch.setattr(fixture.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1, stdout=b'', stderr=b'unavailable'))
        with pytest.raises(ValueError, match='logs'): value.stop()
    assert state.present and not value.cleaned and not value.custody_saved
    assert not any(x[0] == 'rm' for x in state.calls)
    assert value.stop()['protocolHealthy'] is True and value.cleaned
    assert sum(x[0] == 'stop' for x in state.calls) == 1


def test_unknown_remove_can_confirm_absence_after_terminal_custody(state, monkeypatch):
    value = state.value; value.prepare(); original = value.docker
    def unknown(*args):
        result = original(*args)
        if args[0] == 'rm': raise ValueError('transport lost after removal')
        return result
    with monkeypatch.context() as patch:
        patch.setattr(value, 'docker', unknown)
        with pytest.raises(ValueError, match='transport lost'): value.stop()
    assert value.custody_saved and not value.cleaned and not state.present
    assert value.stop()['cleanupConfirmed']
    assert sum(x[0] == 'rm' for x in state.calls) == 1


def test_failed_start_can_be_cleaned_without_reading_the_production_service(state, monkeypatch):
    value = state.value; original = value.docker
    def fail(*args):
        if args[0] == 'start': raise ValueError('owned start failed')
        return original(*args)
    monkeypatch.setattr(value, 'docker', fail)
    with pytest.raises(ValueError, match='owned start'): value.prepare()
    assert value.started and not value.ready and value.environment == {}
    assert value.stop()['cleanupConfirmed']
    assert all(args[:3] == ('inspect', '--format', fixture.FORMAL_PROJECTION)
               for args in state.calls if FORMAL_ID in args)


@pytest.mark.parametrize('failure', ['exit', 'timeout', 'oversize'])
def test_docker_failure_is_bounded_and_preserves_original_output(state, monkeypatch, failure):
    def run(*args, **kwargs):
        assert kwargs['timeout'] == 30 and set(kwargs['env']) <= {'PATH', 'LANG', 'LC_ALL'}
        if failure == 'timeout':
            raise fixture.subprocess.TimeoutExpired('docker', 30, output=b'owned stdout', stderr=b'owned stderr')
        return SimpleNamespace(returncode=1 if failure == 'exit' else 0,
            stdout=b'x' * (2 * fixture.MIB + 1) if failure == 'oversize' else b'owned stdout', stderr=b'owned stderr')
    monkeypatch.setattr(fixture.subprocess, 'run', run)
    with pytest.raises(ValueError): fixture.Fixture.docker(state.value, 'start', OWN_ID)
    if failure != 'oversize':
        prefix = 'docker-timeout' if failure == 'timeout' else 'docker-failure'
        assert (state.value.folder / (prefix + '.stdout.log')).read_bytes() == b'owned stdout'
        assert (state.value.folder / (prefix + '.stderr.log')).read_bytes() == b'owned stderr'


def test_unhealthy_final_readback_does_not_leak_owned_synthetic_container(state, monkeypatch):
    value = state.value; value.prepare()
    def fail(full=False):
        assert full
        raise ValueError('already unhealthy')
    monkeypatch.setattr(value, 'query', fail)
    result = value.stop()
    assert result['cleanupConfirmed'] and not state.present
    assert result['protocolHealthy'] is False and result['terminalValidationErrorType'] == 'ValueError'
    assert json.loads((value.folder / 'before-stop-server-error.json').read_text()) == {'errorType': 'ValueError'}


@pytest.mark.parametrize('damage', ['config', 'identity', 'stopped', 'oom', 'restarting', 'post-stop-oom'])
def test_terminal_health_rejection_is_separate_from_successful_owned_cleanup(state, monkeypatch, damage):
    value = state.value; value.prepare()
    if damage == 'config': state.identity['settings']['appendonly'] = 'yes'
    if damage == 'identity': state.identity['runId'] = '2' * 40
    if damage == 'stopped': state.row['State'].update(Running=False, Pid=0)
    if damage == 'oom': state.row['State']['OOMKilled'] = True
    if damage == 'restarting':
        state.row['State']['Restarting'] = True
        original = value.docker
        def stop_restarting(*args):
            result = original(*args)
            if args[0] == 'stop': state.row['State']['Restarting'] = False
            return result
        monkeypatch.setattr(value, 'docker', stop_restarting)
    if damage == 'post-stop-oom':
        original = value.docker
        def stop_with_oom(*args):
            result = original(*args)
            if args[0] == 'stop': state.row['State']['OOMKilled'] = True
            return result
        monkeypatch.setattr(value, 'docker', stop_with_oom)
    result = value.stop()
    assert result['status'] == 'STOPPED' and result['cleanupConfirmed'] and not state.present
    assert result['protocolHealthy'] is False and result['terminalValidationErrorType'] == 'ValueError'
    assert value.stop() == result
