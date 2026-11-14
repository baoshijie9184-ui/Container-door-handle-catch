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
            if args[0]=='kill':
                self.assertEqual(('kill','--signal','HUP',rows['prometheus']['Id']),args);return b''
            raise AssertionError(args)
        value.docker=docker
        with mock.patch.object(fixture.importlib.util,'spec_from_file_location',return_value=spec), \
                mock.patch.object(fixture.importlib.util,'module_from_spec',return_value=resources), \
                mock.patch.object(fixture,'free_port',side_effect=[35001,35002]),mock.patch.object(value,'check'):
            environment=value.prepare()
        return value,rows,present,calls,environment

    def alert_snapshot(self,value,firing=True,resolved=0):
        labels=[{'attempt':value.token,'source':'source-fixture','probe':probe} for probe in fixture.ALERT_PROBES]
        alerts=[{'labels':{**item,'alertname':fixture.ALERT_NAME},'status':{'state':'active'},
                 'fingerprint':str(index)*16,'receivers':[{'name':'owned-null'}]} for index,item in enumerate(labels,1)]
        rules={'status':'success','data':{'groups':[{'name':'owned-source','rules':[
            {'name':fixture.ALERT_NAME,'type':'alerting','labels':item,'health':'ok',
             'query':'vector(1)' if firing else 'vector(0) > 0','state':'firing' if firing else 'inactive',
             'alerts':[{'labels':{**item,'alertname':fixture.ALERT_NAME},'state':'firing'}] if firing else []}
            for item in labels]}]}}
        groups=[{'labels':{'alertname':fixture.ALERT_NAME,'attempt':value.token},
                 'receiver':{'name':'owned-null'},'alerts':deepcopy(alerts)}]
        return rules,alerts if firing else [],groups if firing else [],resolved

    def alert_http(self,value):
        firing=(value.folder/'rules.yml').read_text()==fixture.alert_rules(value.token)
        rules,alerts,groups,count=self.alert_snapshot(value,firing,0 if firing else 2)
        return {'/api/v1/rules?type=alert':json.dumps(rules,indent=1).encode()+b'\n',
            '/api/v2/alerts':json.dumps(alerts,indent=1).encode()+b'\n',
            '/api/v2/alerts/groups':json.dumps(groups,indent=1).encode()+b'\n',
            '/metrics':b'# actual raw counter\nalertmanager_alerts_received_total{status="resolved",version="v2"} '+str(count).encode()+b'\n'}

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
            rules=(value.folder/'rules.yml').read_text()
            self.assertEqual(2,rules.count('alert: '+fixture.ALERT_NAME))
            for probe in fixture.ALERT_PROBES:self.assertIn('probe: '+probe,rules)
            self.assertIn('group_by: [alertname, attempt]',config)
            self.assertNotIn('--web.enable-lifecycle',' '.join(map(str,calls)))

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
            value,_,present,calls,_=self.configured(Path(directory).resolve())
            inode=(value.folder/'rules.yml').stat().st_ino
            firing_http=self.alert_http(value)
            for runtime in ('java','python'):
                fixture.preserve(value.folder/('evidence/'+runtime+'-scrape.json'),json.dumps({
                    'schemaVersion':1,'runtime':runtime,'status':'PASS','missingTokenStatus':401,
                    'wrongTokenStatus':401,'authenticatedStatus':200,'providerCalls':0}))
            def request(component,route):
                if route=='/api/v1/targets':return {'status':'success','data':{'activeTargets':[]}}
                self.assertEqual('prometheus',component);self.assertTrue(route.startswith('/api/v1/query?'))
                return {'status':'success','data':{'result':[{'metric':{'attempt':value.token},'value':[1,'3']}]}}
            with mock.patch.object(value,'check'),mock.patch.object(value,'request',side_effect=request), \
                    mock.patch.object(value,'request_raw',side_effect=lambda component,route:self.alert_http(value)[route]), \
                    mock.patch.object(fixture.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'original',stderr=b'')):
                result=value.stop()
            self.assertEqual('PASS',result['metricsAcceptance']);self.assertTrue(result['alertmanagerReceivedOwnedAlert'])
            self.assertEqual('PASS',result['alertLifecycle']['status'])
            self.assertEqual(2,result['alertLifecycle']['firing']['ownedAlertCount'])
            self.assertEqual(1,result['alertLifecycle']['firing']['ownedGroupCount'])
            self.assertEqual(0,result['alertLifecycle']['resolved']['ownedAlertCount'])
            self.assertEqual(0,result['alertLifecycle']['resolved']['ownedGroupCount'])
            self.assertEqual(2,result['alertLifecycle']['resolvedReceiptIncrease'])
            self.assertEqual(inode,(value.folder/'rules.yml').stat().st_ino)
            self.assertEqual(1,len([call for call in calls if call[0]=='kill']))
            self.assertEqual(firing_http['/api/v2/alerts/groups'],(value.folder/'evidence/alert-firing-groups.json').read_bytes())
            self.assertEqual(self.alert_http(value)['/metrics'],(value.folder/'evidence/alert-resolved-received.txt').read_bytes())
            self.assertTrue(result['cleanupConfirmed']);self.assertFalse(present)
            evidence=json.loads((value.folder/'evidence/prometheus-readback.json').read_text())
            self.assertEqual({'javaUp','javaCounter','javaHistogram','pythonUp','pythonCounter','pythonHistogram'},set(evidence))
            with mock.patch.object(value,'request',side_effect=AssertionError('Stopped services must not be queried again')):
                retry=value.stop()
            self.assertEqual('PASS',retry['metricsAcceptance']);self.assertEqual(result['evidence'],retry['evidence'])
            self.assertEqual(result['alertLifecycle'],retry['alertLifecycle'])
            self.assertEqual(b'original',(value.folder/'prometheus.stdout.log').read_bytes())

    def test_http_original_is_kept_as_received_not_reserialized(self):
        with tempfile.TemporaryDirectory() as directory:
            value,_,_,_,_=self.configured(Path(directory).resolve())
            response=mock.MagicMock();response.status=200;response.read.return_value=b' [ ] \n'
            response.__enter__.return_value=response
            with mock.patch.object(value.opener,'open',return_value=response) as opened:
                self.assertEqual(b' [ ] \n',value.request_raw('alertmanager','/api/v2/alerts'))
                self.assertEqual([],value.request('alertmanager','/api/v2/alerts'))
            self.assertTrue(all(call.args[0].startswith('http://127.0.0.1:35002/') for call in opened.call_args_list))

    def test_grouping_requires_two_distinct_unsuppressed_owned_members_and_the_real_group(self):
        with tempfile.TemporaryDirectory() as directory:
            value=self.build(Path(directory).resolve())
            for damage in ('foreign-attempt','single-alert','wrong-receiver','suppressed','split-groups',
                           'foreign-group','wrong-fingerprint','unhealthy-rule','absent-rules','pending-rule'):
                rules,alerts,groups,count=self.alert_snapshot(value)
                if damage=='foreign-attempt':alerts[0]['labels']['attempt']='foreign'
                elif damage=='single-alert':alerts.pop()
                elif damage=='wrong-receiver':alerts[0]['receivers']=[{'name':'other'}]
                elif damage=='suppressed':alerts[0]['status']['state']='suppressed'
                elif damage=='split-groups':groups.append(deepcopy(groups[0]))
                elif damage=='foreign-group':groups[0]['labels']['attempt']='foreign'
                elif damage=='wrong-fingerprint':groups[0]['alerts'][0]['fingerprint']='0'*16
                elif damage=='unhealthy-rule':rules['data']['groups'][0]['rules'][0]['health']='err'
                elif damage=='absent-rules':rules['data']['groups']=[]
                elif damage=='pending-rule':rules['data']['groups'][0]['rules'][0]['state']='pending'
                with self.subTest(damage=damage):
                    self.assertFalse(fixture.alert_phase_matches(value.token,'firing',rules,alerts,groups,count,0))

    def test_resolution_needs_inactive_original_rules_empty_views_and_two_new_received_resolutions(self):
        with tempfile.TemporaryDirectory() as directory:
            value=self.build(Path(directory).resolve())
            for damage in ('none','old-counter','one-resolution','still-active','still-grouped','removed-rules','old-expression'):
                rules,alerts,groups,count=self.alert_snapshot(value,False,7)
                if damage=='old-counter':count=5
                elif damage=='one-resolution':count=6
                elif damage=='still-active':alerts=self.alert_snapshot(value)[1]
                elif damage=='still-grouped':groups=self.alert_snapshot(value)[2]
                elif damage=='removed-rules':rules['data']['groups'][0]['rules']=[]
                elif damage=='old-expression':rules['data']['groups'][0]['rules'][0]['query']='vector(1)'
                with self.subTest(damage=damage):
                    self.assertEqual(damage=='none',fixture.alert_phase_matches(value.token,'resolved',rules,alerts,groups,count,5))

    def test_resolved_counter_requires_exact_v2_series_and_finite_nonnegative_integral_value(self):
        self.assertEqual(2,fixture.resolved_received(b'alertmanager_alerts_received_total{version="v2",status="resolved"} 2\n'))
        for raw in (b'',b'alertmanager_alerts_received_total{status="firing",version="v2"} 2\n',
                    *[b'alertmanager_alerts_received_total{status="resolved",version="v2"} '+value+b'\n'
                      for value in (b'NaN',b'Inf',b'-1',b'1.5')]):
            with self.subTest(raw=raw),self.assertRaises(ValueError):fixture.resolved_received(raw)

    def test_grouping_waits_for_actual_readback_and_preserves_only_the_final_http_bodies(self):
        with tempfile.TemporaryDirectory() as directory:
            value,_,_,_,_=self.configured(Path(directory).resolve());evidence=[];calls=[]
            def raw(component,route):
                calls.append(route)
                if len(calls)<=4 and route=='/api/v2/alerts/groups':return b'[]'
                return self.alert_http(value)[route]
            with mock.patch.object(value,'request_raw',side_effect=raw),mock.patch.object(value,'check'),mock.patch.object(fixture.time,'sleep') as sleep:
                result=value.observe_alert_phase('firing',evidence)
            self.assertEqual(2,result['polls']);sleep.assert_called_once_with(.2)
            self.assertEqual(4,len(evidence))
            self.assertEqual(self.alert_http(value)['/api/v2/alerts/groups'],(value.folder/'evidence/alert-firing-groups.json').read_bytes())

    def test_grouping_timeout_preserves_observation_and_still_stops_both_containers(self):
        with tempfile.TemporaryDirectory() as directory:
            value,_,present,_,_=self.configured(Path(directory).resolve())
            def raw(component,route):return b'[]' if route=='/api/v2/alerts/groups' else self.alert_http(value)[route]
            with mock.patch.object(value,'request_raw',side_effect=raw),mock.patch.object(value,'check'), \
                    mock.patch.object(fixture.time,'monotonic',side_effect=[0,61]), \
                    mock.patch.object(fixture.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'original',stderr=b'')):
                result=value.stop()
            self.assertEqual('FAILED',result['metricsAcceptance']);self.assertEqual('FAILED',result['alertLifecycle']['status'])
            self.assertTrue(result['cleanupConfirmed']);self.assertFalse(present)
            self.assertEqual(b'[]',(value.folder/'evidence/alert-firing-groups.json').read_bytes())

    def test_failed_reload_cannot_claim_resolution_or_prevent_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            value,_,present,_,_=self.configured(Path(directory).resolve());docker=value.docker
            def fail_reload(*args):
                if args[0]=='kill':raise ValueError('reload failed')
                return docker(*args)
            with mock.patch.object(value,'request_raw',side_effect=lambda component,route:self.alert_http(value)[route]), \
                    mock.patch.object(value,'check'),mock.patch.object(value,'docker',side_effect=fail_reload), \
                    mock.patch.object(fixture.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'original',stderr=b'')):
                result=value.stop()
            self.assertEqual('FAILED',result['metricsAcceptance']);self.assertEqual('FAILED',result['alertLifecycle']['status'])
            self.assertNotIn('resolved',result['alertLifecycle']);self.assertTrue(result['cleanupConfirmed']);self.assertFalse(present)

    def test_unreceived_resolution_fails_acceptance_but_cleanup_still_completes(self):
        with tempfile.TemporaryDirectory() as directory:
            value,_,present,_,_=self.configured(Path(directory).resolve())
            def raw(component,route):
                if route=='/metrics':return b'alertmanager_alerts_received_total{status="resolved",version="v2"} 0\n'
                return self.alert_http(value)[route]
            with mock.patch.object(value,'request_raw',side_effect=raw),mock.patch.object(value,'check'), \
                    mock.patch.object(fixture.time,'monotonic',side_effect=[0,0,61]), \
                    mock.patch.object(fixture.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'original',stderr=b'')):
                result=value.stop()
            self.assertEqual('FAILED',result['metricsAcceptance']);self.assertEqual('FAILED',result['alertLifecycle']['status'])
            self.assertEqual('PASS',result['alertLifecycle']['firing']['status']);self.assertNotIn('resolved',result['alertLifecycle'])
            self.assertTrue(result['cleanupConfirmed']);self.assertFalse(present)
            self.assertEqual(b'[]\n',(value.folder/'evidence/alert-resolved-alerts.json').read_bytes())

    def test_old_pass_without_alert_lifecycle_is_not_reused_and_does_not_block_container_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            value,_,present,_,_=self.configured(Path(directory).resolve())
            fixture.preserve(value.folder/'metrics-acceptance.json',json.dumps({**CONTEXT,'ownerToken':value.token,
                'images':value.images,'metricsAcceptance':'PASS','evidence':[]}))
            with mock.patch.object(value,'request_raw',side_effect=AssertionError('Do not rerun a retained acceptance')), \
                    mock.patch.object(fixture.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'original',stderr=b'')):
                result=value.stop()
            self.assertEqual('FAILED',result['metricsAcceptance']);self.assertFalse(present)
            self.assertFalse(result['cleanupConfirmed'])
            self.assertEqual('acceptance-original',result['cleanupErrors'][0]['component'])

    def test_changed_or_linked_synthetic_rules_never_signal_the_container(self):
        for damage in ('changed','symlink','hardlink'):
            with self.subTest(damage=damage),tempfile.TemporaryDirectory() as directory:
                value,_,_,calls,_=self.configured(Path(directory).resolve());path=value.folder/'rules.yml'
                if damage=='changed':path.write_text('unreviewed rules')
                elif damage=='symlink':
                    original=value.folder/'retained.yml';path.rename(original);path.symlink_to(original)
                else:(value.folder/'retained.yml').hardlink_to(path)
                with self.assertRaises(ValueError):value.resolve_alert_rules([])
                self.assertFalse([call for call in calls if call[0]=='kill'])

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
            observation=json.loads((value.folder/'capacity-before-images.json').read_text())
            self.assertEqual('FAIL_CLOSED',observation['capacityVerdict'])
            self.assertEqual('MEMORY_RESERVE_BEFORE_IMAGES',observation['failureCode'])
            self.assertEqual(3*fixture.GIB,observation['requiredDiskBytes'])

    def test_post_image_capacity_rejection_preserves_original_bytes_and_stops_without_starting_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            value=self.build(Path(directory).resolve());value.docker=mock.Mock(side_effect=AssertionError('Rejected capacity must not create a container'))
            # This disclosed post-cleanup number is a synthetic boundary fixture,
            # not a substitute for the missing historical failure-time probe.
            available=3054800896
            resources=SimpleNamespace(prepare_observability_image=mock.Mock(return_value={'engineIdentity':{'engineImageId':'sha256:'+'a'*64}}),
                component_input=mock.Mock(return_value={'file':'/owned/public.tar','sha256':'b'*64,'bytes':10240}),
                probe=mock.Mock(side_effect=[{'memoryAvailableBytes':10*fixture.GIB,'diskAvailableBytes':4*fixture.GIB},
                    {'memoryAvailableBytes':10*fixture.GIB,'diskAvailableBytes':available}]))
            spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module:None))
            with mock.patch.object(fixture.importlib.util,'spec_from_file_location',return_value=spec), \
                    mock.patch.object(fixture.importlib.util,'module_from_spec',return_value=resources), \
                    self.assertRaisesRegex(ValueError,'runtime reserve'):
                value.prepare()
            self.assertEqual(2,resources.prepare_observability_image.call_count);self.assertFalse(value.started)
            before=(value.folder/'capacity-before-images.json').read_bytes()
            after=(value.folder/'capacity-after-images.json').read_bytes()
            observation=json.loads(after)
            self.assertEqual('after-images',observation['phase']);self.assertEqual(available,observation['diskAvailableBytes'])
            self.assertEqual(166424576,observation['diskShortfallBytes']);self.assertEqual(0,observation['memoryShortfallBytes'])
            self.assertEqual('DISK_RESERVE_AFTER_IMAGES',observation['failureCode'])
            self.assertEqual(CONTEXT['release'],observation['release']);self.assertEqual(value.token,observation['ownerToken'])
            result=value.stop()
            self.assertEqual('STOPPED',result['status']);self.assertTrue(result['cleanupConfirmed'])
            self.assertEqual('NOT_RUN',result['metricsAcceptance']);self.assertEqual([],result['containers'])
            self.assertEqual('DISK_RESERVE_AFTER_IMAGES',result['preparationFailureCode'])
            self.assertEqual([row['capacityVerdict'] for row in result['capacityAdmissions']],['ADMITTED','FAIL_CLOSED'])
            self.assertEqual(before,(value.folder/'capacity-before-images.json').read_bytes())
            self.assertEqual(after,(value.folder/'capacity-after-images.json').read_bytes())
            value.docker.assert_not_called()

    def test_invalid_capacity_values_are_not_reinterpreted_as_valid_bytes_or_exported(self):
        with tempfile.TemporaryDirectory() as directory:
            value=self.build(Path(directory).resolve())
            resources=SimpleNamespace(probe=lambda _: {'memoryAvailableBytes':True,'diskAvailableBytes':4*fixture.GIB})
            with self.assertRaisesRegex(ValueError,'capacity probe is invalid'):value.admit_runtime(resources,'before-images')
            self.assertEqual('CAPACITY_PROBE_INVALID',value.preparation_failure_code)
            self.assertEqual([],value.capacity_admissions)
            self.assertFalse((value.folder/'capacity-before-images.json').exists())

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
