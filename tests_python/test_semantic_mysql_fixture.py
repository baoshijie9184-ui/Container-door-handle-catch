"""Owned semantic MySQL contracts; executed only by the admitted ECS verifier."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

FILE = Path(__file__).resolve().parents[1] / 'script/jenkins/semantic-mysql-fixture.py'
SPEC = importlib.util.spec_from_file_location('owned_semantic_mysql_fixture', FILE)
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)
MIB = 1024 ** 2
CONTEXT = {'release': 'ci-1-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64,
           'identity': {'executionLocation': 'ECS', 'instanceId': 'i-fixture123', 'machineId': 'c' * 32}}
FORMAL_ID = 'f' * 64
OWN_ID = 'd' * 64
IMAGE = 'sha256:' + 'e' * 64
SERVER_UUID = '11111111-2222-3333-4444-555555555555'


class SemanticMysqlFixtureTests(unittest.TestCase):
    def construct(self, root, context=None):
        (root / 'work').mkdir(exist_ok=True)
        with mock.patch.object(fixture.os, 'getuid', return_value=1000):
            return fixture.Fixture(root, deepcopy(CONTEXT if context is None else context))

    def build(self, root, *, running=False):
        value = self.construct(root)
        value.image, value.container, value.port = IMAGE, OWN_ID, 35001
        value.entrypoint = ['docker-entrypoint.sh']
        row = {'Id': OWN_ID, 'Name': '/' + value.name, 'Image': IMAGE,
            'Config': {'User': '1000:1000', 'Entrypoint': value.entrypoint,
                'Cmd': value._command(), 'Env': [key + '=' + val for key, val in value._env().items()],
                'Labels': {fixture.LABEL: value.token, 'io.doorhandle.release': CONTEXT['release'],
                           'io.doorhandle.source': CONTEXT['sourceSha256']}},
            'HostConfig': {'RestartPolicy': {'Name': 'no'}, 'Privileged': False,
                'ReadonlyRootfs': True, 'Memory': fixture.GIB, 'MemorySwap': fixture.GIB,
                'NanoCpus': 10**9, 'PidsLimit': 128, 'CapDrop': ['ALL'], 'CapAdd': None,
                'Devices': [], 'SecurityOpt': ['no-new-privileges:true'], 'NetworkMode': 'bridge',
                'Tmpfs': value._tmpfs(), 'LogConfig': {'Type': 'json-file', 'Config': {'max-size': '5m', 'max-file': '1'}},
                'PortBindings': {'35001/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '35001'}]}},
            'NetworkSettings': {'Ports': {'35001/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '35001'}],
                                         '3306/tcp': None, '33060/tcp': None}},
            'Mounts': [{'Type': 'bind', 'Source': str(value.data), 'Destination': str(value.data), 'RW': True},
                {'Type': 'bind', 'Source': str(value.private), 'Destination': fixture.PRIVATE, 'RW': False},
                *[{'Type': 'tmpfs', 'Destination': name} for name in value._tmpfs()]],
            'State': {'Running': running, 'Pid': 1234 if running else 0, 'OOMKilled': False,
                      'Status': 'running' if running else 'exited', 'ExitCode': 0}}
        return value, row

    def identity(self, value, *, test_user=False):
        return {'version': '8.4.7', 'versionComment': 'MySQL Community Server - GPL', 'serverUuid': SERVER_UUID,
            'port': value.port, 'dataDirectory': str(value.data) + '/', 'database': value.database,
            'account': (value.username if test_user else 'root') + '@localhost', 'skipNetworking': 0,
            'logBin': 0, 'foreignKeys': 1, 'bufferPoolBytes': 128 * MIB, 'maxConnections': 40,
            'tableCount': 0, 'schemas': [value.database]}

    def fake_docker(self, value, row, calls, *, present=True, references=None):
        state = [present]
        def run(*args):
            calls.append(args)
            if args[0] == 'ps':
                if '--filter' in args: return (FORMAL_ID + '\n').encode()
                if args[-1] == '{{.Names}}': return (value.name + '\n').encode() if state[0] else b''
                self.assertEqual('{{.ID}}', args[-1])
                return (FORMAL_ID + '\n').encode()
            if args[:3] == ('inspect', '--format', fixture.FORMAL_PROJECTION):
                self.assertEqual(FORMAL_ID, args[-1])
                return json.dumps({'Id': FORMAL_ID, 'Image': IMAGE, 'Project': fixture.PROJECT, 'Service': 'mysql'}).encode()
            if args[:3] == ('image', 'inspect', '--format'):
                self.assertEqual(IMAGE, args[-1])
                return json.dumps({'Id': IMAGE, 'Entrypoint': ['docker-entrypoint.sh']}).encode()
            if args[:3] == ('inspect', '--format', '{{json .Mounts}}'):
                self.assertEqual(FORMAL_ID, args[-1])
                return json.dumps(references or [{'Type': 'volume', 'Name': 'formal-data', 'Destination': '/var/lib/mysql'}]).encode()
            if args[0] == 'inspect':
                self.assertIn(args[1], (OWN_ID, value.name))
                return json.dumps([row]).encode()
            if args[0] == 'create': state[0] = True; return OWN_ID.encode()
            if args[0] == 'start': row['State'].update(Running=True, Pid=1234); return b''
            if args[0] == 'stop':
                self.assertEqual(OWN_ID, args[-1]); row['State'].update(Running=False, Pid=0); return b''
            if args[0] == 'rm':
                self.assertEqual(('rm', OWN_ID), args); state[0] = False; return b''
            raise AssertionError('Unexpected Docker operation ' + repr(args))
        return run

    def prepare_mocks(self, value, row, calls):
        value.docker = self.fake_docker(value, row, calls, present=False)
        available = mock.MagicMock()
        available.__enter__.return_value.getsockname.return_value = ('127.0.0.1', value.port)
        return (mock.patch.object(value, '_capacity', return_value={'memoryAvailableBytes': 8 * fixture.GIB,
                    'diskAvailableBytes': 8 * fixture.GIB}),
                mock.patch.object(fixture.socket, 'socket', return_value=available),
                mock.patch.object(value, 'query', side_effect=[self.identity(value), self.identity(value, test_user=True)]),
                mock.patch.object(value, 'check'))

    def materialize_synthetic_files(self, value):
        value.data.mkdir(mode=0o700); value.private.mkdir(mode=0o700)
        (value.data / 'ibdata1').write_bytes(b'synthetic owned data')
        fixture.private_write(value.private / 'test-password', 'synthetic-not-a-real-credential')
        fixture.private_write(value.config, '{}')

    def test_constructor_only_creates_private_owned_metadata_and_never_contacts_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with mock.patch.object(fixture.subprocess, 'run', side_effect=AssertionError('constructor must be pure')):
                value = self.construct(root)
            self.assertEqual(root / 'work/semantic-mysql-fixture', value.folder)
            self.assertEqual(0o700, value.folder.stat().st_mode & 0o777)
            self.assertEqual(CONTEXT, value.context)
            self.assertFalse(value.started)
            self.assertFalse(value.cleaned)
            self.assertTrue((value.folder / 'owner.json').is_file())
            self.assertEqual(0o600, (value.folder / 'owner.json').stat().st_mode & 0o777)

    def test_constructor_rejects_non_ecs_execution_before_creating_a_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); (root / 'work').mkdir()
            context = deepcopy(CONTEXT); context['identity']['executionLocation'] = 'WORKSTATION'
            with mock.patch.object(fixture.os, 'getuid', return_value=1000), \
                    mock.patch.object(fixture.subprocess, 'run') as command:
                with self.assertRaises(ValueError): fixture.Fixture(root, context)
            command.assert_not_called()
            self.assertFalse((root / 'work/semantic-mysql-fixture').exists())

    def test_constructor_refuses_root_or_another_checkout_owner(self):
        for uid in (0, 999, 1001):
            with self.subTest(uid=uid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve(); (root / 'work').mkdir()
                with mock.patch.object(fixture.os, 'getuid', return_value=uid), \
                        mock.patch.object(fixture.subprocess, 'run') as command:
                    with self.assertRaises(ValueError): fixture.Fixture(root, deepcopy(CONTEXT))
                command.assert_not_called()
                self.assertFalse((root / 'work/semantic-mysql-fixture').exists())

    def test_private_write_is_exclusive_and_preserves_existing_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'private.json'
            fixture.private_write(file, 'original private fixture')
            self.assertEqual(0o600, file.stat().st_mode & 0o777)
            with self.assertRaises((OSError, ValueError)):
                fixture.private_write(file, 'must not replace')
            self.assertEqual('original private fixture', file.read_text())

    def test_formal_projection_refuses_credentials_ambiguous_owners_and_mutable_tags(self):
        valid = {'Id': FORMAL_ID, 'Image': IMAGE, 'Project': fixture.PROJECT, 'Service': 'mysql'}
        self.assertEqual(valid, fixture.formal_projection(valid))
        damaged = [{**valid, 'Env': ['MYSQL_ROOT_PASSWORD=must-not-read']}, {**valid, 'Project': 'another-project'},
            {**valid, 'Service': 'backend'}, {**valid, 'Id': 'short-id'}, {**valid, 'Image': 'mysql:8.4'},
            {key: val for key, val in valid.items() if key != 'Image'}]
        for row in damaged:
            with self.subTest(row=row), self.assertRaises(ValueError): fixture.formal_projection(row)
        self.assertNotIn('.Config.Env', fixture.FORMAL_PROJECTION)
        self.assertNotIn('Password', fixture.FORMAL_PROJECTION)

    def test_prepare_uses_fixed_image_same_port_real_datadir_and_file_only_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            value, row = self.build(Path(directory).resolve()); calls = []
            capacity, available, query, check = self.prepare_mocks(value, row, calls)
            with capacity, available, query, check: result = value.prepare()
            self.assertEqual(value.folder / 'feature-mysql.json', result)
            config = json.loads(result.read_text())
            self.assertEqual({'scope', 'machineId', 'instanceId', 'database', 'username', 'password',
                'port', 'serverUuid', 'dataDirectory', 'url'}, set(config))
            self.assertEqual('ecs-disposable-mysql', config['scope'])
            self.assertEqual(SERVER_UUID, config['serverUuid']); self.assertEqual(str(value.data), config['dataDirectory'])
            self.assertEqual(value.database, 'doorhandle_feature_' + value.token[:12])
            self.assertEqual(value.username, 'ecsit_' + value.token[:12])
            self.assertEqual('jdbc:mysql://127.0.0.1:35001/' + value.database
                + '?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai', config['url'])
            self.assertEqual(fixture.ENVIRONMENT, set(value.environment))
            self.assertEqual(str(result), value.environment['DOORHANDLE_TEST_SEMANTIC_MYSQL_CONFIG'])
            self.assertEqual('true', value.environment['DOORHANDLE_REQUIRE_SEMANTIC_MYSQL_TESTS'])
            create = next(call for call in calls if call[0] == 'create')
            self.assertEqual('never', create[create.index('--pull') + 1])
            self.assertEqual('1000:1000', create[create.index('--user') + 1])
            self.assertEqual('1g', create[create.index('--memory') + 1])
            self.assertEqual('1g', create[create.index('--memory-swap') + 1])
            self.assertEqual('1', create[create.index('--cpus') + 1]); self.assertIn('--read-only', create)
            self.assertEqual('127.0.0.1:35001:35001', create[create.index('--publish') + 1])
            self.assertIn('--port=35001', create); self.assertIn('--datadir=' + str(value.data), create)
            self.assertEqual(['mysqld', '--no-defaults'], list(create[create.index(IMAGE) + 1:create.index(IMAGE) + 3]))
            for flag in ('--mysqlx=OFF', '--event-scheduler=OFF', '--local-infile=OFF', '--skip-log-bin'):
                self.assertIn(flag, create)
            mounts = [create[index + 1] for index, arg in enumerate(create) if arg == '--mount']
            self.assertEqual(['type=bind,src=' + str(value.data) + ',dst=' + str(value.data),
                'type=bind,src=' + str(value.private) + ',dst=' + fixture.PRIVATE + ',readonly'], mounts)
            self.assertEqual({'/var/lib/mysql', '/var/lib/mysql-files', '/tmp'}, set(value._tmpfs()))
            secret = (value.private / 'test-password').read_text(); root_secret = (value.private / 'root-password').read_text()
            self.assertEqual(secret, config['password'])
            for password in (secret, root_secret): self.assertNotIn(password, repr(calls))
            for file in [value.config, *value.private.iterdir()]: self.assertEqual(0o600, file.stat().st_mode & 0o777)
            self.assertTrue(value.ready)
            self.assertFalse(any(call[0] == 'exec' for call in calls))
            formal_reads = [call for call in calls if call[0] == 'inspect' and call[-1] == FORMAL_ID]
            self.assertEqual([('inspect', '--format', fixture.FORMAL_PROJECTION, FORMAL_ID)], formal_reads)

    def test_resource_failure_precedes_source_inspection_creation_and_secret_generation(self):
        for capacity in ({'memoryAvailableBytes': 3 * fixture.GIB, 'diskAvailableBytes': 8 * fixture.GIB},
                         {'memoryAvailableBytes': 8 * fixture.GIB, 'diskAvailableBytes': 2 * fixture.GIB}):
            with self.subTest(capacity=capacity), tempfile.TemporaryDirectory() as directory:
                value = self.construct(Path(directory).resolve()); value.docker = mock.Mock()
                with mock.patch.object(value, '_capacity', return_value=capacity):
                    with self.assertRaises(ValueError): value.prepare()
                value.docker.assert_not_called(); self.assertFalse(value.started)
                self.assertFalse(value.data.exists()); self.assertFalse(value.private.exists())

    def test_prepare_rejects_default_or_out_of_range_server_port_before_creating_data(self):
        for port in (3306, 1024, 65536):
            with self.subTest(port=port), tempfile.TemporaryDirectory() as directory:
                value, row = self.build(Path(directory).resolve()); calls = []
                capacity, available, query, check = self.prepare_mocks(value, row, calls)
                socket = mock.MagicMock(); socket.__enter__.return_value.getsockname.return_value = ('127.0.0.1', port)
                with capacity, available, query, check, mock.patch.object(fixture.socket, 'socket', return_value=socket):
                    with self.assertRaises(ValueError): value.prepare()
                self.assertFalse(value.started); self.assertFalse(value.data.exists()); self.assertFalse(value.private.exists())
                self.assertFalse(any(call[0] == 'create' for call in calls))

    def test_docker_failure_preserves_exact_private_bytes_and_does_not_forward_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            value = self.construct(Path(directory).resolve())
            failed = SimpleNamespace(returncode=17, stdout=b'controlled private stdout', stderr=b'controlled private stderr')
            with mock.patch.dict(fixture.os.environ, {'PATH': '/controlled/bin', 'MYSQL_ROOT_PASSWORD': 'not-a-real-secret'}, clear=True), \
                    mock.patch.object(fixture.subprocess, 'run', return_value=failed) as command:
                with self.assertRaises(ValueError) as raised: value.docker('ps', '-a', '--format', '{{.ID}}')
            self.assertNotIn('controlled private', str(raised.exception))
            self.assertEqual({'PATH': '/controlled/bin'}, command.call_args.kwargs['env'])
            self.assertEqual(failed.stdout, (value.folder / 'docker-failure.stdout.log').read_bytes())
            self.assertEqual(failed.stderr, (value.folder / 'docker-failure.stderr.log').read_bytes())
            self.assertFalse(value.cleaned)

    def test_docker_timeout_preserves_available_original_bytes_without_claiming_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            value = self.construct(Path(directory).resolve())
            error = fixture.subprocess.TimeoutExpired('docker', 30, output=b'partial original stdout', stderr=b'partial original stderr')
            with mock.patch.object(fixture.subprocess, 'run', side_effect=error):
                with self.assertRaises(ValueError): value.docker('create', '--name', value.name)
            self.assertEqual(error.stdout, (value.folder / 'docker-timeout.stdout.log').read_bytes())
            self.assertEqual(error.stderr, (value.folder / 'docker-timeout.stderr.log').read_bytes())
            self.assertFalse(value.cleaned); self.assertTrue((value.folder / 'owner.json').is_file())

    def test_failed_owned_startup_can_be_cleaned_without_touching_the_formal_server(self):
        with tempfile.TemporaryDirectory() as directory:
            value, row = self.build(Path(directory).resolve()); calls = []
            capacity, available, query, check = self.prepare_mocks(value, row, calls)
            original = value.docker
            def failed_start(*args):
                result = original(*args)
                if args[0] == 'start': row['State'].update(Running=False, Pid=0, OOMKilled=True, ExitCode=137)
                return result
            value.docker = failed_start
            with capacity, available, query as probe, check:
                with self.assertRaises(ValueError): value.prepare()
            probe.assert_not_called(); self.assertFalse(value.ready); self.assertTrue(value.started)
            self.assertTrue(value.private.is_dir()); self.assertFalse(value.config.exists())
            with mock.patch.object(fixture.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'owned init failure', stderr=b'exit137')):
                result = value.stop()
            self.assertTrue(result['cleanupConfirmed']); self.assertFalse(result['ready'])
            self.assertTrue((value.folder / 'before-stop-container.json').is_file())
            self.assertTrue((value.folder / 'container.stderr.log').is_file())
            self.assertFalse(any(call[0] in ('stop', 'rm', 'exec') and call[-1] == FORMAL_ID for call in calls))

    def test_owned_rejects_changed_image_owner_limits_ports_credentials_and_mounts(self):
        mutations = [lambda r: r.update(Image='sha256:' + 'a' * 64),
            lambda r: r.update(Id='b' * 64), lambda r: r.update(Name='/unrelated-mysql'),
            lambda r: r['Config'].update(User='999:999'), lambda r: r['Config'].update(Entrypoint=['sh']),
            lambda r: r['Config']['Cmd'].append('--skip-grant-tables'),
            lambda r: r['Config']['Labels'].update({fixture.LABEL: 'different-owner'}),
            lambda r: r['Config']['Labels'].update({'io.doorhandle.source': '0' * 64}),
            lambda r: r['Config']['Env'].append('MYSQL_ROOT_PASSWORD=must-not-use'),
            lambda r: r['Config']['Env'].append('MYSQL_ALLOW_EMPTY_PASSWORD=yes'),
            lambda r: r['HostConfig'].update(Memory=2 * fixture.GIB),
            lambda r: r['HostConfig'].update(MemorySwap=-1), lambda r: r['HostConfig'].update(NanoCpus=0),
            lambda r: r['HostConfig'].update(ReadonlyRootfs=False), lambda r: r['HostConfig'].update(Privileged=True),
            lambda r: r['HostConfig'].update(NetworkMode='host'), lambda r: r['HostConfig'].update(CapDrop=[]),
            lambda r: r['HostConfig'].update(CapAdd=['SYS_ADMIN']), lambda r: r['HostConfig'].update(Devices=['/dev/sda']),
            lambda r: r['HostConfig'].update(PidsLimit=0), lambda r: r['HostConfig'].update(SecurityOpt=[]),
            lambda r: r['HostConfig'].update(Tmpfs={}), lambda r: r['HostConfig'].update(LogConfig={}),
            lambda r: r['HostConfig']['PortBindings']['35001/tcp'][0].update(HostIp='0.0.0.0'),
            lambda r: r['HostConfig']['PortBindings']['35001/tcp'][0].update(HostPort='3306'),
            lambda r: r['NetworkSettings']['Ports'].update({'3306/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '3306'}]}),
            lambda r: r['Mounts'][0].update(Source='/production/mysql'),
            lambda r: r['Mounts'][1].update(RW=True),
            lambda r: r['Mounts'].append({'Type': 'volume', 'Name': 'formal-data', 'Destination': '/var/lib/mysql'}),
            lambda r: r['Mounts'].append({'Type': 'tmpfs', 'Destination': '/etc'}),
            lambda r: r['Mounts'].append({'Type': 'tmpfs', 'Destination': '/tmp'}),
            lambda r: r['Mounts'].pop(0)]
        with tempfile.TemporaryDirectory() as directory:
            value, row = self.build(Path(directory).resolve(), running=True)
            value.docker = mock.Mock(return_value=json.dumps([row]).encode()); self.assertEqual(row, value.owned())
            for index, mutate in enumerate(mutations):
                damaged = deepcopy(row); mutate(damaged); value.docker.return_value = json.dumps([damaged]).encode()
                with self.subTest(mutation=index), self.assertRaises(ValueError): value.owned()

    def test_legacy_docker_tmpfs_map_is_authoritative_even_when_mounts_lists_only_binds(self):
        with tempfile.TemporaryDirectory() as directory:
            value, row = self.build(Path(directory).resolve(), running=True)
            # Moby represents legacy --tmpfs in HostConfig.Tmpfs, without
            # necessarily duplicating those entries in the Mounts projection.
            row['Mounts'] = [mount for mount in row['Mounts'] if mount['Type'] == 'bind']
            value.docker = mock.Mock(return_value=json.dumps([row]).encode())
            self.assertEqual(row, value.owned())
            for change in ('missing', 'options'):
                damaged = deepcopy(row)
                if change == 'missing': damaged['HostConfig']['Tmpfs'].pop('/tmp')
                else: damaged['HostConfig']['Tmpfs']['/tmp'] = 'rw,uid=999,gid=999,size=64m'
                value.docker.return_value = json.dumps([damaged]).encode()
                with self.subTest(change=change), self.assertRaises(ValueError): value.owned()

    def test_effective_server_identity_rejects_wrong_engine_uuid_port_datadir_schema_or_user(self):
        with tempfile.TemporaryDirectory() as directory:
            value, _ = self.build(Path(directory).resolve()); value.server_uuid = SERVER_UUID
            original = self.identity(value); value._identity(original, empty=True)
            mutations = {'version': '8.0.40', 'versionComment': 'MariaDB Server',
                'serverUuid': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', 'port': 3306,
                'dataDirectory': '/var/lib/mysql/', 'database': 'doorhandledb', 'account': 'unrelated@localhost',
                'skipNetworking': 1, 'logBin': 1, 'foreignKeys': 0, 'bufferPoolBytes': 256 * MIB,
                'maxConnections': 120, 'tableCount': 29, 'schemas': [value.database, 'doorhandledb']}
            for field, replacement in mutations.items():
                with self.subTest(field=field), self.assertRaises(ValueError):
                    value._identity({**original, field: replacement}, empty=True)
            value._identity({**original, 'tableCount': 29}, empty=False)
            value._identity(self.identity(value, test_user=True), test_user=True)
            with self.assertRaises(ValueError): value._identity(original, test_user=True)

    def test_query_uses_only_owned_mysql_and_private_option_files_never_password_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            value, _ = self.build(Path(directory).resolve())
            value.docker = mock.Mock(return_value=json.dumps(self.identity(value)).encode())
            value.query(); value.query(test_user=True)
            for call, filename in zip(value.docker.call_args_list, ('root-client.cnf', 'test-client.cnf')):
                args = call.args
                self.assertEqual(('exec', OWN_ID, 'mysql'), args[:3])
                self.assertEqual('--defaults-extra-file=' + fixture.PRIVATE + '/' + filename, args[3])
                self.assertIn('--connect-timeout=3', args)
                self.assertIn(fixture.IDENTITY_SQL, args)
                self.assertFalse(any(arg.startswith('--password') for arg in args))
                self.assertNotIn(FORMAL_ID, args)

    def test_check_does_not_query_stopped_or_oom_fixture_and_rechecks_runtime_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            value, row = self.build(Path(directory).resolve()); value.ready = True
            value.docker = mock.Mock(return_value=json.dumps([row]).encode()); value.query = mock.Mock()
            with self.assertRaises(ValueError): value.check()
            value.query.assert_not_called()
            row['State'].update(Running=True, Pid=1234, OOMKilled=True); value.docker.return_value = json.dumps([row]).encode()
            with self.assertRaises(ValueError): value.check()
            value.query.assert_not_called()
            row['State']['OOMKilled'] = False; value.docker.return_value = json.dumps([row]).encode()
            value.query.return_value = {**self.identity(value), 'port': 3306}
            with self.assertRaises(ValueError): value.check()
            value.query.return_value = self.identity(value)
            with mock.patch.object(fixture.os, 'statvfs', return_value=SimpleNamespace(f_bavail=1, f_frsize=4096)):
                with self.assertRaises(ValueError): value.check()

    def test_stop_archives_original_inspect_and_both_logs_before_stop_remove_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            value, row = self.build(Path(directory).resolve(), running=True)
            self.materialize_synthetic_files(value); value.started = True; calls = []
            value.docker = self.fake_docker(value, row, calls)
            def logs(command, **options):
                self.assertEqual(['docker', 'logs', '--timestamps', OWN_ID], command)
                self.assertTrue((value.folder / 'before-stop-container.json').is_file())
                self.assertFalse(any(call[0] == 'rm' for call in calls))
                return SimpleNamespace(returncode=0, stdout=b'synthetic original stdout\n', stderr=b'synthetic original stderr\n')
            with mock.patch.object(fixture.subprocess, 'run', side_effect=logs): result = value.stop()
            self.assertEqual('STOPPED', result['status']); self.assertTrue(result['cleanupConfirmed'])
            self.assertEqual('SYNTHETIC_ONLY', result['sourceData']); self.assertEqual(0, result['providerCalls'])
            self.assertFalse(result['productionPromotionAllowed']); self.assertEqual(CONTEXT['identity'], result['identity'])
            self.assertFalse(value.data.exists()); self.assertFalse(value.private.exists()); self.assertFalse(value.config.exists())
            self.assertTrue((value.folder / 'owner.json').is_file())
            self.assertEqual(OWN_ID, json.loads((value.folder / 'stopped-container.json').read_text())['Id'])
            for prefix in ('before-stop-container', 'container'):
                self.assertEqual(b'synthetic original stdout\n', (value.folder / (prefix + '.stdout.log')).read_bytes())
                self.assertEqual(b'synthetic original stderr\n', (value.folder / (prefix + '.stderr.log')).read_bytes())
            self.assertTrue(result['privateOriginals']); self.assertEqual(result, value.stop())
            self.assertEqual([OWN_ID], [call[-1] for call in calls if call[0] == 'stop'])
            self.assertEqual([OWN_ID], [call[-1] for call in calls if call[0] == 'rm'])

    def test_failed_log_custody_retains_live_owned_container_and_all_data(self):
        with tempfile.TemporaryDirectory() as directory:
            value, row = self.build(Path(directory).resolve(), running=True)
            self.materialize_synthetic_files(value); value.started = True; calls = []
            value.docker = self.fake_docker(value, row, calls)
            with mock.patch.object(fixture.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout=b'', stderr=b'failure')):
                with self.assertRaises(ValueError): value.stop()
            self.assertFalse(value.cleaned); self.assertTrue(value.data.exists()); self.assertTrue(value.config.exists())
            self.assertFalse(any(call[0] in ('stop', 'rm') for call in calls))

    def test_unknown_create_resolves_only_owned_name_and_never_stops_the_formal_server(self):
        with tempfile.TemporaryDirectory() as directory:
            value, row = self.build(Path(directory).resolve(), running=True)
            self.materialize_synthetic_files(value); value.started = True; value.container = None; calls = []
            value.docker = self.fake_docker(value, row, calls)
            with mock.patch.object(fixture.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'owned startup', stderr=b'')):
                result = value.stop()
            self.assertTrue(result['cleanupConfirmed'])
            self.assertTrue(any(call == ('inspect', value.name) for call in calls))
            self.assertFalse(any(call[0] in ('stop', 'rm') and call[-1] == FORMAL_ID for call in calls))

    def test_wrong_owner_is_not_stopped_logged_removed_or_used_to_delete_files(self):
        with tempfile.TemporaryDirectory() as directory:
            value, row = self.build(Path(directory).resolve(), running=True)
            self.materialize_synthetic_files(value); value.started = True
            row['Config']['Labels'][fixture.LABEL] = 'foreign'; calls = []
            value.docker = self.fake_docker(value, row, calls)
            with mock.patch.object(fixture.subprocess, 'run') as logs:
                with self.assertRaises(ValueError): value.stop()
            logs.assert_not_called(); self.assertTrue(value.data.exists()); self.assertFalse(value.cleaned)
            self.assertFalse(any(call[0] in ('stop', 'rm') for call in calls))

    def test_foreign_ancestor_or_descendant_bind_blocks_all_synthetic_deletion(self):
        for scope in ('ancestor', 'descendant', 'exact'):
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as directory:
                value, row = self.build(Path(directory).resolve()); self.materialize_synthetic_files(value)
                source = value.checkout if scope == 'ancestor' else value.data if scope == 'exact' else value.data / 'ibdata1'
                calls = []; value.docker = self.fake_docker(value, row, calls, present=False,
                    references=[{'Type': 'bind', 'Source': str(source), 'Destination': '/borrowed'}])
                with self.assertRaises(ValueError): value.stop()
                self.assertFalse(value.cleaned); self.assertTrue(value.data.exists()); self.assertTrue(value.private.exists())
                self.assertTrue(value.config.exists())
                self.assertFalse(any(call[0] in ('stop', 'rm') for call in calls))

    def test_uid999_or_link_in_one_target_prevents_deletion_of_every_target(self):
        for damage in ('uid999', 'symlink', 'hardlink'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve(); value, row = self.build(root); self.materialize_synthetic_files(value)
                calls = []; value.docker = self.fake_docker(value, row, calls, present=False)
                bad = value.private / 'test-password'
                original = Path.lstat
                if damage == 'symlink':
                    bad.unlink(); bad.symlink_to(value.data / 'ibdata1')
                elif damage == 'hardlink':
                    bad.unlink(); os.link(value.data / 'ibdata1', bad)
                def lstat(path, *args, **kwargs):
                    info = original(path, *args, **kwargs)
                    if damage == 'uid999' and path == bad:
                        fields = list(info); fields[4] = 999; return os.stat_result(fields)
                    return info
                with mock.patch.object(Path, 'lstat', lstat):
                    with self.assertRaises(ValueError): value.stop()
                self.assertFalse(value.cleaned); self.assertTrue(value.data.exists())
                self.assertTrue(value.private.exists()); self.assertTrue(value.config.exists())

    def test_known_container_disappearing_without_terminal_originals_never_authorizes_data_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            value, row = self.build(Path(directory).resolve()); self.materialize_synthetic_files(value)
            value.started = True; calls = []; value.docker = self.fake_docker(value, row, calls, present=False)
            with mock.patch.object(fixture.subprocess, 'run') as logs:
                with self.assertRaisesRegex(ValueError, 'without terminal originals'): value.stop()
            logs.assert_not_called(); self.assertFalse(value.cleaned)
            self.assertTrue(value.data.exists()); self.assertTrue(value.private.exists()); self.assertTrue(value.config.exists())
            self.assertFalse(any(call[0] in ('stop', 'rm') for call in calls))

    def test_failed_create_without_container_or_database_bytes_can_clean_its_own_private_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            value, row = self.build(Path(directory).resolve()); self.materialize_synthetic_files(value)
            (value.data / 'ibdata1').unlink(); value.container = None; value.started = True
            calls = []; value.docker = self.fake_docker(value, row, calls, present=False)
            with mock.patch.object(fixture.subprocess, 'run') as logs: result = value.stop()
            logs.assert_not_called(); self.assertTrue(result['cleanupConfirmed'])
            self.assertFalse(value.data.exists()); self.assertFalse(value.private.exists())
            self.assertTrue((value.folder / 'owner.json').is_file())
            self.assertFalse(any(call[0] in ('stop', 'rm') for call in calls))

    def test_retry_after_foreign_reference_failure_reuses_preserved_custody_without_replaying_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            value, row = self.build(Path(directory).resolve(), running=True); self.materialize_synthetic_files(value)
            value.started = True; references = [{'Type': 'bind', 'Source': str(value.checkout), 'Destination': '/borrowed'}]
            calls = []; value.docker = self.fake_docker(value, row, calls, references=references)
            logs = SimpleNamespace(returncode=0, stdout=b'owned retained startup', stderr=b'')
            with mock.patch.object(fixture.subprocess, 'run', return_value=logs):
                with self.assertRaises(ValueError): value.stop()
            self.assertTrue(value.custody_saved); self.assertFalse(value.cleaned); self.assertTrue(value.data.exists())
            references.clear()
            with mock.patch.object(fixture.subprocess, 'run') as second_logs: result = value.stop()
            second_logs.assert_not_called(); self.assertTrue(result['cleanupConfirmed'])
            self.assertEqual(1, sum(call[0] == 'stop' for call in calls))
            self.assertEqual(1, sum(call[0] == 'rm' for call in calls))
            self.assertTrue((value.folder / 'stopped-container.json').is_file())

    def test_durable_owner_tampering_prevents_any_container_or_file_cleanup(self):
        for damage in ('changed-content', 'public-mode'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                value, row = self.build(Path(directory).resolve(), running=True); self.materialize_synthetic_files(value)
                value.started = True; file = value.folder / 'owner.json'
                if damage == 'changed-content': file.write_text(json.dumps({**value.owner, 'token': 'different'}))
                else: file.chmod(0o644)
                value.docker = mock.Mock()
                with self.assertRaises(ValueError): value.stop()
                value.docker.assert_not_called(); self.assertTrue(value.data.exists()); self.assertFalse(value.cleaned)

    def test_a_different_filesystem_at_the_data_root_is_not_an_owned_cleanup_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            value, row = self.build(Path(directory).resolve()); self.materialize_synthetic_files(value)
            value.docker = self.fake_docker(value, row, [], present=False)
            original = Path.lstat
            def lstat(path, *args, **kwargs):
                info = original(path, *args, **kwargs)
                if path == value.data:
                    fields = list(info); fields[2] += 1; return os.stat_result(fields)
                return info
            with mock.patch.object(Path, 'lstat', lstat):
                with self.assertRaises(ValueError): value.stop()
            self.assertFalse(value.cleaned); self.assertTrue(value.data.exists()); self.assertTrue(value.private.exists())
