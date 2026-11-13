"""Owned Prometheus lifecycle contracts; executed only by the ECS verifier."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

FILE=Path(__file__).resolve().parents[1]/'script/jenkins/observability-fixture.py'
SPEC=importlib.util.spec_from_file_location('owned_observability_fixture',FILE)
fixture=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(fixture)
CONTEXT={'release':'ci-1-'+'a'*12,'commit':'a'*40,'sourceSha256':'b'*64,'identity':{'executionLocation':'ECS'}}

class ObservabilityFixtureTests(unittest.TestCase):
    def build(self,root):
        (root/'work').mkdir()
        with mock.patch.object(fixture.os,'getuid',return_value=1000):value=fixture.Fixture(root,deepcopy(CONTEXT))
        return value

    def row(self,value,component):
        item=value.rows[component]
        return {'Id':('c' if component=='prometheus' else 'd')*64,'Name':'/'+item['name'],'Image':value.images[component],
            'Config':{'User':'1000:1000','Entrypoint':['/bin/'+component],'Cmd':item['command'],
                'Labels':{fixture.LABEL:value.token,'io.doorhandle.release':CONTEXT['release'],'io.doorhandle.source':CONTEXT['sourceSha256']}},
            'HostConfig':{'NetworkMode':'host','PortBindings':None,'ReadonlyRootfs':True,'Privileged':False,'CapAdd':None,'CapDrop':['ALL'],
                'SecurityOpt':['no-new-privileges:true'],'Memory':item['memory'],'MemorySwap':item['memory'],'NanoCpus':10**9,
                'PidsLimit':128,'RestartPolicy':{'Name':'no'}},
            'Mounts':[{'Type':'bind','Source':str(source),'Destination':destination,'RW':writable} for source,destination,writable in item['mounts']],
            'State':{'Running':True,'Pid':1234,'OOMKilled':False}}

    def configured(self,root):
        value=self.build(root);calls=[];rows={};present=set()
        images={'prometheus':'sha256:'+'e'*64,'alertmanager':'sha256:'+'f'*64}
        resources=SimpleNamespace(prepare_observability_image=lambda directory,context,module,component,archive=None:{'engineIdentity':{'engineImageId':images[component]}},
            component_input=mock.Mock(return_value={'file':'/owned/public-input.tar','sha256':'a'*64,'bytes':10240}),
            probe=lambda _: {'memoryAvailableBytes':10*fixture.GIB,'diskAvailableBytes':4*fixture.GIB})
        spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module:None))
        def docker(*args):
            calls.append(args)
            if args[0]=='create':
                component=args[args.index('--entrypoint')+1].rsplit('/',1)[1];rows[component]=self.row(value,component);present.add(component);return rows[component]['Id'].encode()
            if args[0]=='ps':return ('\n'.join(value.rows[name]['name'] for name in sorted(present))).encode()
            component=next(name for name,row in rows.items() if args[-1] in (row['Id'],value.rows[name]['name']))
            if args[0]=='inspect':return json.dumps([rows[component]]).encode()
            if args[0]=='stop':rows[component]['State'].update(Running=False,Pid=0);return b''
            if args[0]=='rm':present.remove(component);return b''
            if args[0]=='start':return b''
            raise AssertionError(args)
        value.docker=docker
        with mock.patch.object(fixture.importlib.util,'spec_from_file_location',return_value=spec), \
                mock.patch.object(fixture.importlib.util,'module_from_spec',return_value=resources), \
                mock.patch.object(fixture,'free_port',side_effect=[35001,35002]),mock.patch.object(value,'check'):
            environment=value.prepare()
        return value,rows,present,calls,environment

    def test_real_recipe_uses_bounded_nonroot_hostnetwork_with_only_loopback_listeners_and_null_receiver(self):
        with tempfile.TemporaryDirectory() as directory:
            value,_,_,calls,environment=self.configured(Path(directory).resolve())
            creates=[call for call in calls if call[0]=='create'];self.assertEqual(2,len(creates))
            for args in creates:
                self.assertEqual('never',args[args.index('--pull')+1]);self.assertEqual('host',args[args.index('--network')+1])
                self.assertEqual('1000:1000',args[args.index('--user')+1]);self.assertIn('--read-only',args);self.assertNotIn('--publish',args)
                self.assertIn('--web.listen-address=127.0.0.1:', ' '.join(args))
                self.assertNotIn((value.folder/'secrets/metrics-token').read_text(),' '.join(args))
            self.assertEqual(fixture.ENVIRONMENT,set(environment))
            self.assertIn('attempt: '+value.token,(value.folder/'prometheus.yml').read_text())
            config=(value.folder/'alertmanager.yml').read_text();self.assertIn('owned-null',config)
            self.assertNotIn('webhook_configs',config);self.assertNotIn('email_configs',config)
            self.assertNotIn('langfuse',' '.join(map(str,calls)))

    def test_wrong_owner_or_unbounded_container_is_not_admitted(self):
        with tempfile.TemporaryDirectory() as directory:
            value,rows,_,_,_=self.configured(Path(directory).resolve());self.assertEqual(rows['prometheus'],value.owned('prometheus'))
            original=deepcopy(rows['prometheus'])
            for key,bad in [('NetworkMode','bridge'),('MemorySwap',-1),('NanoCpus',0),('PidsLimit',0),('CapAdd',['SYS_ADMIN'])]:
                rows['prometheus']=deepcopy(original);rows['prometheus']['HostConfig'][key]=bad
                with self.subTest(field=key),self.assertRaises(ValueError):value.owned('prometheus')

    def test_missing_metrics_still_stops_both_owned_containers_and_preserves_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            value,_,present,calls,_=self.configured(Path(directory).resolve())
            with mock.patch.object(value,'check',side_effect=ValueError('synthetic acceptance failure')), \
                    mock.patch.object(fixture.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'owned stdout',stderr=b'owned stderr')):
                result=value.stop()
            self.assertEqual('FAILED',result['metricsAcceptance']);self.assertEqual('STOPPED',result['status']);self.assertTrue(result['cleanupConfirmed'])
            self.assertFalse(present);self.assertEqual(2,len([call for call in calls if call[0]=='rm']))
            for component in ('prometheus','alertmanager'):
                self.assertTrue((value.folder/(component+'-stopped.json')).is_file())
                self.assertEqual(b'owned stdout',(value.folder/(component+'.stdout.log')).read_bytes())
            self.assertFalse((value.folder/'secrets').exists())
            self.assertFalse((value.folder/'prometheus-data').exists())
            self.assertFalse((value.folder/'alertmanager-data').exists())

    def test_independent_prometheus_and_alert_readbacks_are_required_before_acceptance_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            value,_,present,_,_=self.configured(Path(directory).resolve())
            for runtime in ('java','python'):
                fixture.preserve(value.folder/('evidence/'+runtime+'-scrape.json'),json.dumps({
                    'schemaVersion':1,'runtime':runtime,'status':'PASS','missingTokenStatus':401,
                    'wrongTokenStatus':401,'authenticatedStatus':200,'providerCalls':0}))
            def request(component,route):
                if route=='/api/v2/alerts':return [{'labels':{'alertname':'DoorhandleOwnedFixtureAlert','attempt':value.token},
                    'status':{'state':'active'},'receivers':[{'name':'owned-null'}]}]
                if route=='/api/v1/targets':return {'status':'success','data':{'activeTargets':[]}}
                self.assertEqual('prometheus',component);self.assertTrue(route.startswith('/api/v1/query?'))
                return {'status':'success','data':{'result':[{'metric':{'attempt':value.token},'value':[1,'3']}]}}
            with mock.patch.object(value,'check'),mock.patch.object(value,'request',side_effect=request), \
                    mock.patch.object(fixture.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'original',stderr=b'')):
                result=value.stop()
            self.assertEqual('PASS',result['metricsAcceptance']);self.assertTrue(result['alertmanagerReceivedOwnedAlert'])
            self.assertTrue(result['cleanupConfirmed']);self.assertFalse(present)
            evidence=json.loads((value.folder/'evidence/prometheus-readback.json').read_text())
            self.assertEqual({'javaUp','javaCounter','javaHistogram','pythonUp','pythonCounter','pythonHistogram'},set(evidence))
            with mock.patch.object(value,'request',side_effect=AssertionError('Stopped services must not be queried again')):
                retry=value.stop()
            self.assertEqual('PASS',retry['metricsAcceptance']);self.assertEqual(result['evidence'],retry['evidence'])
            self.assertEqual(b'original',(value.folder/'prometheus.stdout.log').read_bytes())

    def test_one_logs_failure_still_stops_other_container_and_can_retry_without_overwriting_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            value,rows,present,_,_=self.configured(Path(directory).resolve())
            with mock.patch.object(value,'check',side_effect=ValueError('no metrics')), \
                    mock.patch.object(fixture.subprocess,'run',side_effect=[SimpleNamespace(returncode=1,stdout=b'',stderr=b''),
                        SimpleNamespace(returncode=0,stdout=b'alert original',stderr=b'')]):
                result=value.stop()
            self.assertFalse(result['cleanupConfirmed']);self.assertEqual({'prometheus'},present)
            self.assertFalse(rows['prometheus']['State']['Running']);self.assertEqual('FAILED',result['metricsAcceptance'])
            self.assertTrue((value.folder/'secrets').is_dir())
            with mock.patch.object(fixture.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'prom original',stderr=b'')):
                retry=value.stop()
            self.assertTrue(retry['cleanupConfirmed']);self.assertFalse(present)
            self.assertEqual('FAILED',retry['metricsAcceptance'])
            self.assertEqual(b'alert original',(value.folder/'alertmanager.stdout.log').read_bytes())

    def test_combined_source_reserve_includes_the_single_mysql_before_image_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            value=self.build(Path(directory).resolve())
            resources=SimpleNamespace(prepare_observability_image=mock.Mock(),
                probe=lambda _: {'memoryAvailableBytes':8*fixture.GIB,'diskAvailableBytes':4*fixture.GIB})
            spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module:None))
            with mock.patch.object(fixture.importlib.util,'spec_from_file_location',return_value=spec), \
                    mock.patch.object(fixture.importlib.util,'module_from_spec',return_value=resources), \
                    self.assertRaisesRegex(ValueError,'runtime reserve'):
                value.prepare()
            resources.prepare_observability_image.assert_not_called()
            self.assertEqual(9*fixture.GIB+128*fixture.MIB,fixture.RUNTIME_RESERVE)

    def test_damaged_acceptance_original_never_prevents_stopping_owned_containers(self):
        with tempfile.TemporaryDirectory() as directory:
            value,_,present,_,_=self.configured(Path(directory).resolve())
            path=value.folder/'metrics-acceptance.json';fixture.preserve(path,b'partial readback')
            with mock.patch.object(fixture.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'original',stderr=b'')):
                result=value.stop()
            self.assertFalse(present);self.assertEqual('FAILED',result['metricsAcceptance'])
            self.assertFalse(result['cleanupConfirmed']);self.assertEqual(b'partial readback',path.read_bytes())
            for component in ('prometheus','alertmanager'):self.assertTrue((value.folder/(component+'-stopped.json')).is_file())

    def test_unknown_import_is_not_misreported_as_cleanup_confirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            value=self.build(Path(directory).resolve());value.image_attempts={'prometheus'}
            folder=value.folder/'prometheus-image';folder.mkdir()
            fixture.preserve(folder/'resource-summary.json',json.dumps({**CONTEXT,'cleanup':{'creatorStopped':True,'builderStopped':True,'daemonImportTerminated':False}}))
            with self.assertRaisesRegex(ValueError,'import remains unknown'):value.stop()
            self.assertFalse(value.cleaned);self.assertTrue((folder/'resource-summary.json').is_file())

    def test_preservation_is_retryable_but_never_overwrites_changed_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'evidence';fixture.preserve(path,b'original');fixture.preserve(path,b'original')
            with self.assertRaisesRegex(ValueError,'original changed'):fixture.preserve(path,b'changed')
            self.assertEqual(b'original',path.read_bytes())

    def test_prometheus_endpoint_config_must_carry_this_exact_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            value,_,_,_,_=self.configured(Path(directory).resolve())
            value.request=mock.Mock(return_value={'status':'success','data':{'yaml':'global:\n  external_labels:\n    attempt: foreign\n'}})
            with self.assertRaisesRegex(ValueError,'another attempt'):value.check()


if __name__=='__main__':unittest.main()
