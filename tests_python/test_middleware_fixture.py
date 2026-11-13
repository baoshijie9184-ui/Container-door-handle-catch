"""Owned middleware contracts; Jenkins runs these only on admitted ECS."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

FILE = Path(__file__).resolve().parents[1] / 'script/jenkins/middleware-fixture.py'
SPEC = importlib.util.spec_from_file_location('owned_middleware_fixture', FILE)
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)
MIB = 1024 ** 2
CONTEXT = {'release': 'ci-1-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64,
           'identity': {'executionLocation': 'ECS', 'instanceId': 'fixture-instance', 'machineId': 'fixture-machine'}}


class MiddlewareFixtureTests(unittest.TestCase):
    def build(self, root):
        (root / 'work').mkdir()
        with mock.patch.object(fixture.os, 'getuid', return_value=1000):
            value = fixture.Fixture(root, deepcopy(CONTEXT))
        value.image = 'sha256:' + 'c' * 64
        value.container = 'd' * 64
        row = {'Id': value.container, 'Name': '/' + value.name, 'Image': value.image,
            'Config': {'User': '1000:1000', 'Entrypoint': None,
                'Cmd': ['./entrypoint.sh', '--config-path', '/run/doorhandle-vector/server.json'],
                'Labels': {fixture.LABEL: value.token, 'io.doorhandle.release': CONTEXT['release'],
                           'io.doorhandle.source': CONTEXT['sourceSha256']}},
            'HostConfig': {'RestartPolicy': {'Name': 'no'}, 'Privileged': False,
                'ReadonlyRootfs': True, 'Memory': 512*MIB, 'MemorySwap': 512*MIB,
                'NanoCpus': 10**9, 'PidsLimit': 128, 'CapDrop': ['ALL'], 'CapAdd': None,
                'SecurityOpt': ['no-new-privileges:true'], 'NetworkMode': 'bridge',
                'PortBindings': {'6333/tcp': [{'HostIp': '127.0.0.1', 'HostPort': ''}],
                                 '6334/tcp': [{'HostIp': '127.0.0.1', 'HostPort': ''}]}},
            'NetworkSettings': {'Ports': {'6333/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '35001'}],
                                         '6334/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '35002'}]}},
            'Mounts': [{'Type': 'bind', 'Source': str(value.folder/name), 'Destination': target, 'RW': writable}
                for name,target,writable in [('storage','/qdrant/storage',True),
                    ('snapshots','/qdrant/snapshots',True),('private','/run/doorhandle-vector',False)]],
            'State': {'Running': False, 'Pid': 0, 'OOMKilled': False, 'Status': 'exited', 'ExitCode': 0}}
        return value,row

    def image_summary(self, value, *, terminal=True):
        directory=value.folder/'image-preparation';directory.mkdir()
        fixture.private_write(directory/'resource-summary.json',json.dumps({**CONTEXT,'status':'PASS' if terminal else 'FAILED',
            'cleanup':{'creatorStopped':True,'builderStopped':True,'daemonImportTerminated':terminal}}))

    def fake_docker(self, value, row, calls):
        present=[True]
        def run(*args):
            calls.append(args)
            if args[0]=='inspect': return json.dumps([row]).encode()
            if args[0]=='ps': return (value.name+'\n').encode() if present[0] else b''
            if args[0]=='stop': row['State'].update(Running=False,Pid=0);return b''
            if args[0]=='rm': present[0]=False;return b''
            if args[0] in ('create','start'): return value.container.encode()
            raise AssertionError('Unreviewed Docker operation '+repr(args))
        return run

    def test_loopback_port_requires_one_high_port_and_never_public_or_ambiguous_binding(self):
        valid={'NetworkSettings':{'Ports':{'6333/tcp':[{'HostIp':'127.0.0.1','HostPort':'35001'}]}}}
        self.assertEqual('35001',fixture.binding_port(valid,6333))
        for binding in ([{'HostIp':'0.0.0.0','HostPort':'35001'}],
                [{'HostIp':'::','HostPort':'35001'}],[{'HostIp':'127.0.0.1','HostPort':'633'}],
                [{'HostIp':'127.0.0.1','HostPort':'65536'}],valid['NetworkSettings']['Ports']['6333/tcp']*2,None):
            with self.subTest(binding=binding),self.assertRaises(ValueError):
                fixture.binding_port({'NetworkSettings':{'Ports':{'6333/tcp':binding}}},6333)

    def test_owned_accepts_only_the_exact_limited_recipe_and_engine_id(self):
        mutations=[('MemorySwap',-1),('NanoCpus',0),('PidsLimit',0),('CapDrop',[]),('CapAdd',['SYS_ADMIN']),
                   ('SecurityOpt',[]),('ReadonlyRootfs',False),('NetworkMode','host'),('Memory',1024*MIB)]
        with tempfile.TemporaryDirectory() as directory:
            value,row=self.build(Path(directory).resolve())
            value.docker=mock.Mock(return_value=json.dumps([row]).encode());self.assertEqual(row,value.owned())
            for key,replacement in mutations:
                changed=deepcopy(row);changed['HostConfig'][key]=replacement
                value.docker.return_value=json.dumps([changed]).encode()
                with self.subTest(field=key),self.assertRaises(ValueError): value.owned()
            for mutate in (lambda r:r.update(Image='sha256:'+'e'*64),
                    lambda r:r['Config'].update(Cmd=['./qdrant']),lambda r:r['Config'].update(Entrypoint=['sh']),
                    lambda r:r['Config']['Labels'].update({fixture.LABEL:'another-owner'}),
                    lambda r:r['HostConfig']['PortBindings']['6333/tcp'][0].update(HostIp='0.0.0.0'),
                    lambda r:r['HostConfig']['PortBindings']['6334/tcp'][0].update(HostPort='6334'),
                    lambda r:r['Mounts'][0].update(Source='/production/data')):
                changed=deepcopy(row);mutate(changed);value.docker.return_value=json.dumps([changed]).encode()
                with self.assertRaises(ValueError): value.owned()

    def test_prepare_uses_immutable_engine_id_nonroot_readonly_random_loopback_and_private_config(self):
        with tempfile.TemporaryDirectory() as directory:
            value,row=self.build(Path(directory).resolve());row['State'].update(Running=True,Pid=1234)
            calls=[];value.docker=self.fake_docker(value,row,calls)
            resources=SimpleNamespace(prepare_qdrant_image=mock.Mock(return_value={'engineIdentity':{'engineImageId':value.image}}),
                component_input=mock.Mock(return_value={'file':'/owned/public-input.tar','sha256':'a'*64,'bytes':10240}),
                probe=mock.Mock(return_value={'memoryAvailableBytes':8*fixture.GIB,'diskAvailableBytes':4*fixture.GIB}))
            spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module:None))
            response=mock.MagicMock();response.__enter__.return_value.status=200
            opener=SimpleNamespace(open=mock.Mock(return_value=response))
            with mock.patch.object(fixture.importlib.util,'spec_from_file_location',return_value=spec), \
                    mock.patch.object(fixture.importlib.util,'module_from_spec',return_value=resources), \
                    mock.patch.object(fixture,'build_opener',return_value=opener),mock.patch.object(value,'check'):
                environment=value.prepare()
            resources.component_input.assert_called_once_with(value.checkout,value.context,'qdrant')
            self.assertEqual(resources.component_input.return_value,resources.prepare_qdrant_image.call_args.kwargs['archive'])
            create=next(call for call in calls if call[0]=='create')
            self.assertEqual('never',create[create.index('--pull')+1])
            self.assertEqual('1000:1000',create[create.index('--user')+1]);self.assertIn('--read-only',create)
            self.assertEqual('512m',create[create.index('--memory')+1]);self.assertEqual('512m',create[create.index('--memory-swap')+1])
            self.assertEqual(['127.0.0.1::6333','127.0.0.1::6334'],[create[index+1] for index,arg in enumerate(create) if arg=='--publish'])
            self.assertEqual(value.image,create[-4]);self.assertEqual(['./entrypoint.sh','--config-path','/run/doorhandle-vector/server.json'],list(create[-3:]))
            self.assertIn('QDRANT_INIT_FILE_PATH=/qdrant/storage/.qdrant-initialized',create)
            key=(value.folder/'private/api-key').read_text();config=json.loads((value.folder/'private/server.json').read_text())
            self.assertNotIn(key,' '.join(create));self.assertEqual(key,config['service']['api_key'])
            self.assertTrue(config['telemetry_disabled']);self.assertEqual('/qdrant/storage',config['storage']['storage_path'])
            self.assertEqual(fixture.ENVIRONMENT,set(environment));self.assertEqual('127.0.0.1',environment['DOORHANDLE_TEST_QDRANT_HOST'])
            self.assertEqual(('35001','35002'),(environment['DOORHANDLE_TEST_QDRANT_PORT'],environment['DOORHANDLE_TEST_QDRANT_GRPC_PORT']))

    def test_prepare_resource_rejection_happens_before_docker_create(self):
        for capacity in ({'memoryAvailableBytes':6*fixture.GIB,'diskAvailableBytes':4*fixture.GIB},
                         {'memoryAvailableBytes':8*fixture.GIB,'diskAvailableBytes':2*fixture.GIB}):
            with self.subTest(capacity=capacity),tempfile.TemporaryDirectory() as directory:
                value,_=self.build(Path(directory).resolve());value.docker=mock.Mock()
                resources=SimpleNamespace(prepare_qdrant_image=mock.Mock(return_value={'engineIdentity':{'engineImageId':value.image}}),
                    component_input=mock.Mock(return_value={'file':'/owned/public-input.tar','sha256':'a'*64,'bytes':10240}),
                    probe=mock.Mock(return_value=capacity))
                spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module:None))
                with mock.patch.object(fixture.importlib.util,'spec_from_file_location',return_value=spec), \
                        mock.patch.object(fixture.importlib.util,'module_from_spec',return_value=resources):
                    with self.assertRaisesRegex(ValueError,'runtime resource reserve'): value.prepare()
                value.docker.assert_not_called();self.assertFalse(value.started)

    def test_unknown_image_import_never_reports_cleanup_confirmed_or_deletes_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            value,_=self.build(Path(directory).resolve());self.image_summary(value,terminal=False)
            value.docker=mock.Mock(side_effect=AssertionError('unknown import must not be changed'))
            with self.assertRaisesRegex(ValueError,'not confirmed terminal'): value.stop()
            self.assertFalse(value.cleaned);self.assertTrue((value.folder/'owner.json').is_file())
            self.assertTrue((value.folder/'image-preparation/resource-summary.json').is_file())
            value.docker.assert_not_called()

    def test_missing_image_terminal_summary_preserves_the_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            value,_=self.build(Path(directory).resolve());(value.folder/'image-preparation').mkdir()
            value.docker=mock.Mock()
            with self.assertRaisesRegex(ValueError,'no terminal'): value.stop()
            self.assertFalse(value.cleaned);value.docker.assert_not_called()

    def test_stop_preserves_inspect_and_both_log_streams_before_removing_owned_container(self):
        with tempfile.TemporaryDirectory() as directory:
            value,row=self.build(Path(directory).resolve());self.image_summary(value)
            value.started=True;value.ready=False;calls=[];value.docker=self.fake_docker(value,row,calls)
            for name in ('storage','snapshots','private'): (value.folder/name).mkdir(mode=0o700)
            logs=SimpleNamespace(returncode=0,stdout=b'synthetic startup stdout\n',stderr=b'synthetic startup stderr\n')
            def preserve(*args,**kwargs):
                self.assertTrue((value.folder/'stopped-container.json').is_file())
                self.assertFalse(any(call[0]=='rm' for call in calls));return logs
            with mock.patch.object(fixture.subprocess,'run',side_effect=preserve): result=value.stop()
            self.assertEqual('STOPPED',result['status']);self.assertTrue(result['cleanupConfirmed'])
            self.assertEqual(logs.stdout,(value.folder/'container.stdout.log').read_bytes())
            self.assertEqual(logs.stderr,(value.folder/'container.stderr.log').read_bytes())
            self.assertEqual(value.container,json.loads((value.folder/'stopped-container.json').read_text())['Id'])
            self.assertTrue((value.folder/'owner.json').is_file());self.assertFalse((value.folder/'private').exists())
            self.assertEqual([value.container],[call[1] for call in calls if call[0]=='rm'])

    def test_log_capture_failure_keeps_container_and_same_attempt_can_safely_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            value,row=self.build(Path(directory).resolve());self.image_summary(value)
            value.started=True;calls=[];value.docker=self.fake_docker(value,row,calls)
            bad=SimpleNamespace(returncode=1,stdout=b'',stderr=b'temporary failure')
            good=SimpleNamespace(returncode=0,stdout=b'preserved after retry\n',stderr=b'')
            with mock.patch.object(fixture.subprocess,'run',return_value=bad):
                with self.assertRaises(ValueError): value.stop()
            self.assertFalse(any(call[0]=='rm' for call in calls));self.assertFalse(value.cleaned)
            with mock.patch.object(fixture.subprocess,'run',return_value=good): result=value.stop()
            self.assertTrue(result['cleanupConfirmed']);self.assertEqual(good.stdout,(value.folder/'container.stdout.log').read_bytes())

    def test_wrong_container_owner_is_never_stopped_removed_or_used_to_delete_data(self):
        with tempfile.TemporaryDirectory() as directory:
            value,row=self.build(Path(directory).resolve());value.started=True
            storage=value.folder/'storage';storage.mkdir();(storage/'keep.txt').write_text('keep')
            row['Config']['Labels'][fixture.LABEL]='unrelated';calls=[];value.docker=self.fake_docker(value,row,calls)
            with self.assertRaises(ValueError): value.stop()
            self.assertFalse(any(call[0] in ('stop','rm') for call in calls));self.assertTrue((storage/'keep.txt').is_file())

    def test_check_rejects_stopped_oom_and_disk_floor_without_contacting_other_services(self):
        with tempfile.TemporaryDirectory() as directory:
            value,row=self.build(Path(directory).resolve());value.ready=True;value.docker=mock.Mock(return_value=json.dumps([row]).encode())
            with self.assertRaisesRegex(ValueError,'not healthy'): value.check()
            row['State'].update(Running=True,Pid=1234,OOMKilled=True);value.docker.return_value=json.dumps([row]).encode()
            with self.assertRaisesRegex(ValueError,'not healthy'): value.check()
            row['State']['OOMKilled']=False;value.docker.return_value=json.dumps([row]).encode()
            with mock.patch.object(fixture.os,'statvfs',return_value=SimpleNamespace(f_bavail=1,f_frsize=4096)):
                with self.assertRaisesRegex(ValueError,'reserve'): value.check()


if __name__ == '__main__':
    unittest.main()
