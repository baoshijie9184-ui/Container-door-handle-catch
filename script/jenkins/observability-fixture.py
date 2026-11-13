"""Owned real Prometheus/Alertmanager for the existing ECS source verifier.

Only synthetic metrics and a null notification receiver are configured. This
does not start Langfuse, a business app, or a model/provider client.
"""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import subprocess
import time
from urllib.request import ProxyHandler, build_opener
from urllib.parse import urlencode

MIB = 1024 ** 2
GIB = 1024 ** 3
LABEL = 'io.doorhandle.observability-fixture'
ENVIRONMENT = frozenset({'DOORHANDLE_TEST_PROMETHEUS_URL','DOORHANDLE_TEST_ALERTMANAGER_URL',
    'DOORHANDLE_TEST_OBSERVABILITY_TARGETS','DOORHANDLE_TEST_OBSERVABILITY_TOKEN_FILE',
    'DOORHANDLE_REQUIRE_OBSERVABILITY_TESTS'})
# Serial nested tools6GiB + Qdrant512MiB + MySQL1GiB + Prom512MiB
# + Alert128MiB + host1GiB. MySQL is the existing single source fixture.
RUNTIME_RESERVE = 9 * GIB + 128 * MIB
STARTUP_DISK_RESERVE = 3 * GIB

def require(value, message):
    if not value: raise ValueError(message)

def preserve(path, raw):
    """Create once, or validate identical prior evidence when cleanup is retried."""
    path=Path(path); raw=raw.encode() if isinstance(raw,str) else raw
    if path.exists() or path.is_symlink():
        info=path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid()
                and stat.S_IMODE(info.st_mode)==0o600 and path.read_bytes()==raw,
                'Owned observability original changed')
        return
    with os.fdopen(os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())

def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0)); return listener.getsockname()[1]

class Fixture:
    def __init__(self,checkout,context):
        self.checkout=Path(checkout)
        require(os.getuid()==1000 and self.checkout.resolve(strict=True)==self.checkout
                and context['identity']['executionLocation']=='ECS','Owned ECS source checkout required')
        self.context=dict(context);self.folder=self.checkout/'work/observability-fixture';self.folder.mkdir(mode=0o700)
        self.token=secrets.token_hex(16);self.rows={};self.images={};self.image_attempts=set();self.ports={};self.started=set();self.cleaned=False
        self.capacity_admissions=[];self.preparation_failure_code=None
        self.opener=build_opener(ProxyHandler({}));self.environment={}
        preserve(self.folder/'owner.json',json.dumps({**context,'ownerToken':self.token,'kind':'doorhandle-observability-fixture','sourceData':'SYNTHETIC_ONLY'},sort_keys=True))

    def docker(self,*args):
        result=subprocess.run(['docker',*args],capture_output=True,timeout=30,
            env={key:value for key,value in os.environ.items() if key in ('PATH','LANG','LC_ALL')})
        require(result.returncode==0 and len(result.stdout)<=2*MIB,'Owned observability Docker operation failed')
        return result.stdout

    def request(self,component,route):
        require(component in ('prometheus','alertmanager') and route.startswith('/') and '\n' not in route,'Invalid observability readback')
        with self.opener.open('http://127.0.0.1:'+str(self.ports[component])+route,timeout=3) as response:
            raw=response.read(2*MIB+1)
            require(response.status==200 and len(raw)<=2*MIB,'Observability endpoint readback failed')
        return json.loads(raw) if raw else {}

    def owned(self,component):
        item=self.rows[component];row=json.loads(self.docker('inspect',item.get('id') or item['name']))[0]
        cfg,host=row['Config'],row['HostConfig'];labels=cfg.get('Labels') or {}
        require(row['Name']=='/'+item['name'] and row['Image']==self.images[component]
                and (not item.get('id') or row['Id']==item['id']) and re.fullmatch('[a-f0-9]{64}',row['Id'])
                and labels.get(LABEL)==self.token and labels.get('io.doorhandle.release')==self.context['release']
                and labels.get('io.doorhandle.source')==self.context['sourceSha256']
                and cfg['User']=='1000:1000' and cfg['Entrypoint']==['/bin/'+component] and cfg['Cmd']==item['command']
                and host['NetworkMode']=='host' and not host.get('PortBindings')
                and host['ReadonlyRootfs'] is True and not host['Privileged'] and not host.get('CapAdd')
                and set(host.get('CapDrop') or [])=={'ALL'} and 'no-new-privileges:true' in (host.get('SecurityOpt') or [])
                and host['Memory']==item['memory'] and host['MemorySwap']==item['memory']
                and host['NanoCpus']==10**9 and host['PidsLimit']==128 and host['RestartPolicy']['Name']=='no',
                'Observability container ownership or limits changed')
        expected={(str(source),destination):writable for source,destination,writable in item['mounts']}
        for mount in row['Mounts']:
            if mount['Type']=='tmpfs':
                require(mount['Destination']=='/tmp','Unexpected observability temporary mount');continue
            key=(mount['Source'],mount['Destination'])
            require(mount['Type']=='bind' and key in expected and mount['RW'] is expected.pop(key),'Observability bind changed')
        require(not expected,'Observability bind is missing');return row

    def admit_runtime(self,resources,phase):
        """Retain the actual gate observation before it can reject preparation."""
        require(phase in ('before-images','after-images'),'Invalid observability admission phase')
        capacity=resources.probe(self.folder)
        if not all(type(capacity.get(key)) is int and capacity[key]>=0 for key in ('memoryAvailableBytes','diskAvailableBytes')):
            self.preparation_failure_code='CAPACITY_PROBE_INVALID'
            raise ValueError('Observability capacity probe is invalid')
        memory_shortfall=max(0,RUNTIME_RESERVE-capacity['memoryAvailableBytes'])
        disk_shortfall=max(0,STARTUP_DISK_RESERVE-capacity['diskAvailableBytes'])
        reason=('MEMORY_AND_DISK_RESERVE' if memory_shortfall and disk_shortfall else
                'MEMORY_RESERVE' if memory_shortfall else 'DISK_RESERVE' if disk_shortfall else None)
        code=reason+'_'+phase.upper().replace('-','_') if reason else None
        value={'schemaVersion':1,'kind':'doorhandle-observability-capacity',**self.context,'ownerToken':self.token,
            'phase':phase,'memoryAvailableBytes':capacity['memoryAvailableBytes'],
            'diskAvailableBytes':capacity['diskAvailableBytes'],'requiredMemoryBytes':RUNTIME_RESERVE,
            'requiredDiskBytes':STARTUP_DISK_RESERVE,'memoryShortfallBytes':memory_shortfall,
            'diskShortfallBytes':disk_shortfall,'capacityVerdict':'FAIL_CLOSED' if reason else 'ADMITTED',
            'failureCode':code}
        path=self.folder/('capacity-'+phase+'.json')
        preserve(path,json.dumps(value,sort_keys=True))
        self.capacity_admissions.append({**value,'file':str(path)})
        if reason:
            self.preparation_failure_code=code
            raise ValueError('Observability plus serial source tools lacks its runtime reserve')

    def prepare(self):
        helper=self.checkout/'script/docker/compact-build-resources.py'
        spec=importlib.util.spec_from_file_location('owned_observability_images',helper)
        resources=importlib.util.module_from_spec(spec);spec.loader.exec_module(resources)
        self.admit_runtime(resources,'before-images')
        for component in ('alertmanager','prometheus'):
            self.image_attempts.add(component)
            proof=resources.prepare_observability_image(self.folder/(component+'-image'),self.context,helper.parent,component,
                archive=resources.component_input(self.checkout,self.context,component))
            self.images[component]=proof['engineIdentity']['engineImageId']
        self.admit_runtime(resources,'after-images')
        for name in ('targets','secrets','evidence','prometheus-data','alertmanager-data'):(self.folder/name).mkdir(mode=0o700)
        preserve(self.folder/'secrets/metrics-token',secrets.token_hex(32))
        self.ports={component:free_port() for component in ('prometheus','alertmanager')}
        require(len(set(self.ports.values()))==2,'Observability ports collided; use a fresh owned attempt')
        prometheus=f'''global:
  scrape_interval: 1s
  scrape_timeout: 500ms
  evaluation_interval: 1s
  external_labels:
    attempt: {self.token}
rule_files: [/etc/prometheus/rules.yml]
alerting:
  alertmanagers:
    - static_configs:
        - targets: ["127.0.0.1:{self.ports['alertmanager']}"]
scrape_configs:
  - job_name: owned-runtime
    authorization:
      type: Bearer
      credentials_file: /run/owned/secrets/metrics-token
    file_sd_configs:
      - files: [/run/owned/targets/*.json]
        refresh_interval: 1s
    relabel_configs:
      - target_label: attempt
        replacement: {self.token}
    sample_limit: 10000
    label_limit: 20
    label_value_length_limit: 128
'''
        rules=f'''groups:
  - name: owned-source
    rules:
      - alert: DoorhandleOwnedFixtureAlert
        expr: vector(1)
        for: 2s
        labels:
          attempt: {self.token}
          source: source-fixture
'''
        alertmanager='''route:
  receiver: owned-null
  group_by: [alertname, attempt]
  group_wait: 1s
  group_interval: 1s
  repeat_interval: 1h
receivers:
  - name: owned-null
'''
        for name,content in (('prometheus.yml',prometheus),('rules.yml',rules),('alertmanager.yml',alertmanager)):
            preserve(self.folder/name,content)
        for component in ('alertmanager','prometheus'):
            config=self.folder/(component+'.yml');data=self.folder/(component+'-data')
            if component=='prometheus':
                command=['--config.file=/etc/prometheus/prometheus.yml','--storage.tsdb.path=/prometheus',
                    '--storage.tsdb.retention.time=1h','--storage.tsdb.retention.size=64MB',
                    '--storage.tsdb.wal-segment-size=10MB','--web.listen-address=127.0.0.1:'+str(self.ports[component])]
                mounts=[(config,'/etc/prometheus/prometheus.yml',False),(self.folder/'rules.yml','/etc/prometheus/rules.yml',False),
                    (self.folder/'targets','/run/owned/targets',False),(self.folder/'secrets','/run/owned/secrets',False),(data,'/prometheus',True)]
                memory=512*MIB
            else:
                command=['--config.file=/etc/alertmanager/alertmanager.yml','--storage.path=/alertmanager','--data.retention=1h',
                    '--web.listen-address=127.0.0.1:'+str(self.ports[component]),'--cluster.listen-address=']
                mounts=[(config,'/etc/alertmanager/alertmanager.yml',False),(data,'/alertmanager',True)];memory=128*MIB
            self.rows[component]={'name':'doorhandle-'+component+'-test-'+self.token,'command':command,'mounts':mounts,'memory':memory}
            args=['create','--pull','never','--name',self.rows[component]['name'],'--restart','no','--user','1000:1000',
                '--network','host','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true',
                '--memory',str(memory),'--memory-swap',str(memory),'--cpus','1','--pids-limit','128',
                '--tmpfs','/tmp:rw,nosuid,nodev,size=64m','--no-healthcheck','--workdir','/',
                '--log-driver','json-file','--log-opt','max-size=5m','--log-opt','max-file=1',
                '--label',LABEL+'='+self.token,'--label','io.doorhandle.release='+self.context['release'],
                '--label','io.doorhandle.source='+self.context['sourceSha256'],'--entrypoint','/bin/'+component]
            for source,destination,writable in mounts:
                args+=['--mount','type=bind,src='+str(source)+',dst='+destination+('' if writable else ',readonly')]
            self.started.add(component);self.docker(*args,self.images[component],*command)
            row=self.owned(component);self.rows[component]['id']=row['Id'];self.docker('start',row['Id'])
        deadline=time.monotonic()+60
        while True:
            try:self.check();break
            except (ValueError,OSError):
                require(time.monotonic()<deadline,'Owned observability services did not become ready');time.sleep(.2)
        self.environment={'DOORHANDLE_TEST_PROMETHEUS_URL':'http://127.0.0.1:'+str(self.ports['prometheus']),
            'DOORHANDLE_TEST_ALERTMANAGER_URL':'http://127.0.0.1:'+str(self.ports['alertmanager']),
            'DOORHANDLE_TEST_OBSERVABILITY_TARGETS':str(self.folder/'targets'),
            'DOORHANDLE_TEST_OBSERVABILITY_TOKEN_FILE':str(self.folder/'secrets/metrics-token'),
            'DOORHANDLE_REQUIRE_OBSERVABILITY_TESTS':'true'}
        return self.environment

    def check(self):
        for component in self.started:
            row=self.owned(component)
            require(row['State']['Running'] and not row['State'].get('OOMKilled'),'Owned observability service stopped')
        config=self.request('prometheus','/api/v1/status/config')
        require(config.get('status')=='success' and re.search(r'(?m)^\s+attempt:\s*[\"\']?'+self.token+r'[\"\']?\s*$',config.get('data',{}).get('yaml','')),
                'Prometheus endpoint belongs to another attempt')
        status=self.request('alertmanager','/api/v2/status')
        require('owned-null' in status.get('config',{}).get('original',''),'Alertmanager null receiver differs')
        fs=os.statvfs(self.folder);require(fs.f_bavail*fs.f_frsize>=2*GIB+256*MIB,'Observability disk reserve exhausted')

    def stop(self):
        for component in self.image_attempts:
            path=self.folder/(component+'-image/resource-summary.json')
            if not path.parent.exists():continue  # No helper directory means no daemon operation was admitted.
            require(path.is_file() and not path.is_symlink(),'Observability image lacks terminal preparation evidence')
            result=json.loads(path.read_text())
            require(all(result.get(key)==self.context[key] for key in ('release','commit','sourceSha256','identity'))
                and all(result.get('cleanup',{}).get(key) is True for key in ('creatorStopped','builderStopped','daemonImportTerminated')),
                'Observability image import remains unknown; retain resources')
        public={'schemaVersion':1,'kind':'doorhandle-observability-fixture','ownerToken':self.token,**self.context,
            'sourceData':'SYNTHETIC_ONLY','providerCalls':0,'langfuseStarted':False,'externalNotifications':False,
            'capacityAdmissions':self.capacity_admissions,'preparationFailureCode':self.preparation_failure_code,
            'metricsAcceptance':'NOT_RUN','evidence':[]}
        acceptance_file=self.folder/'metrics-acceptance.json'
        prior=None;preservation_errors=[]
        if acceptance_file.exists() or acceptance_file.is_symlink():
            try:
                info=acceptance_file.lstat();require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)==0o600,'Observability acceptance original changed')
                prior=json.loads(acceptance_file.read_text())
                require(prior.get('ownerToken')==self.token and prior.get('images')==self.images
                    and all(prior.get(key)==self.context[key] for key in ('release','commit','sourceSha256','identity')),
                    'Observability acceptance belongs to another attempt')
                public.update({key:prior[key] for key in ('metricsAcceptance','evidence','alertmanagerReceivedOwnedAlert','acceptanceErrorType') if key in prior})
            except Exception as error:
                # A damaged readback cannot bypass stopping the in-memory owned objects.
                # Do not replace this original or reuse its acceptance claim.
                prior={};public.update(metricsAcceptance='FAILED',acceptanceErrorType=type(error).__name__)
                preservation_errors.append({'component':'acceptance-original','errorType':type(error).__name__})
        if prior is None and len(self.started)==2:
            try:
                public['metricsAcceptance']='FAILED'
                self.check();alerts=self.request('alertmanager','/api/v2/alerts')
                targets=self.request('prometheus','/api/v1/targets')
                preserve(self.folder/'evidence/prometheus-targets.json',json.dumps(targets,sort_keys=True))
                public['evidence'].append({'file':str(self.folder/'evidence/prometheus-targets.json'),'kind':'actual-target-discovery'})
                firing=[row for row in alerts if row.get('labels',{}).get('alertname')=='DoorhandleOwnedFixtureAlert'
                    and row.get('labels',{}).get('attempt')==self.token and row.get('status',{}).get('state')=='active'
                    and {item['name'] for item in row.get('receivers',[])}=={'owned-null'}]
                public['alertmanagerReceivedOwnedAlert']=bool(firing)
                preserve(self.folder/'evidence/alertmanager-alerts.json',json.dumps(alerts,sort_keys=True))
                public['evidence'].append({'file':str(self.folder/'evidence/alertmanager-alerts.json'),'kind':'actual-alertmanager-readback','ownedAlertCount':len(firing)})
                require(firing,'Alertmanager has not received the owned synthetic firing alert')
                observations={}
                expressions={
                    'javaUp':'max_over_time(up{fixture="java"}[1h])',
                    'javaCounter':'max_over_time(doorhandle_fixture_operations_total{fixture="java"}[1h])',
                    'javaHistogram':'max_over_time(doorhandle_fixture_operation_seconds_bucket{fixture="java",le="+Inf"}[1h])',
                    'pythonUp':'max_over_time(up{fixture="python"}[1h])',
                    'pythonCounter':'max_over_time(doorhandle_runtime_operations_total{fixture="python",operation="mem0.search",outcome="success"}[1h])',
                    'pythonHistogram':'max_over_time(doorhandle_runtime_operation_seconds_bucket{fixture="python",operation="mem0.search",le="+Inf"}[1h])'}
                for name,expression in expressions.items():
                    result=self.request('prometheus','/api/v1/query?'+urlencode({'query':expression}))
                    samples=result.get('data',{}).get('result',[]);minimum=3 if name.endswith('Counter') or name=='pythonHistogram' else 1
                    require(result.get('status')=='success' and len(samples)==1 and samples[0].get('metric',{}).get('attempt')==self.token
                            and float(samples[0]['value'][1])>=minimum,'Prometheus lacks a required real runtime sample')
                    observations[name]=result
                preserve(self.folder/'evidence/prometheus-readback.json',json.dumps(observations,sort_keys=True))
                public['evidence'].append({'file':str(self.folder/'evidence/prometheus-readback.json'),'kind':'actual-prometheus-readback','assertedSeries':len(observations)})
                for runtime in ('java','python'):
                    path=self.folder/('evidence/'+runtime+'-scrape.json');receipt=json.loads(path.read_text())
                    require(receipt.get('schemaVersion')==1 and receipt.get('runtime')==runtime and receipt.get('status')=='PASS'
                        and receipt.get('missingTokenStatus')==401 and receipt.get('wrongTokenStatus')==401
                        and receipt.get('authenticatedStatus')==200 and receipt.get('providerCalls')==0,'Runtime machine-auth scrape receipt is missing')
                    public['evidence'].append({'file':str(path),'kind':'runtime-authenticated-scrape','runtime':runtime})
                public['metricsAcceptance']='PASS'
            except Exception as error:
                public['metricsAcceptance']='FAILED';public['acceptanceErrorType']=type(error).__name__
        if prior is None:
            try:preserve(acceptance_file,json.dumps({**public,'images':self.images},sort_keys=True))
            except Exception as error:
                public.update(metricsAcceptance='FAILED',acceptanceErrorType=type(error).__name__)
                preservation_errors.append({'component':'acceptance-original','errorType':type(error).__name__})
        stopped=[];cleanup_errors=preservation_errors
        for component in ('prometheus','alertmanager'):
            if component not in self.started:continue
            try:
                item=self.rows[component]
                names=self.docker('ps','-a','--format','{{.Names}}').decode().splitlines()
                if item['name'] not in names:continue
                row=self.owned(component)
                if row['State']['Running']:self.docker('stop','--time','15',row['Id'])
                row=self.owned(component);require(not row['State']['Running'] and row['State']['Pid']==0,'Observability service did not stop')
                preserve(self.folder/(component+'-stopped.json'),json.dumps(row,sort_keys=True))
                logs=subprocess.run(['docker','logs','--timestamps','--tail','500',row['Id']],capture_output=True,timeout=30,
                    env={key:value for key,value in os.environ.items() if key in ('PATH','LANG','LC_ALL')})
                require(logs.returncode==0 and len(logs.stdout)+len(logs.stderr)<=6*MIB,'Observability logs unavailable; retain container')
                preserve(self.folder/(component+'.stdout.log'),logs.stdout);preserve(self.folder/(component+'.stderr.log'),logs.stderr)
                self.docker('rm',row['Id']);require(item['name'] not in self.docker('ps','-a','--format','{{.Names}}').decode().splitlines(),'Owned observability object remains')
                stopped.append({'component':component,'containerId':row['Id'],'imageId':self.images[component]})
            except Exception as error:cleanup_errors.append({'component':component,'errorType':type(error).__name__})
        if not cleanup_errors:
            try:
                # These directories contain only this attempt's credentials and synthetic
                # TSDB/silence data. Keep actual HTTP, image, owner and stopped-log originals.
                for name in ('secrets','prometheus-data','alertmanager-data'):
                    directory=self.folder/name
                    if directory.exists() or directory.is_symlink():
                        require(directory.resolve(strict=True)==directory and directory.stat().st_uid==os.getuid(),
                                'Owned synthetic observability directory changed')
                        shutil.rmtree(directory)
            except Exception as error:cleanup_errors.append({'component':'owned-synthetic-directories','errorType':type(error).__name__})
        self.cleaned=not cleanup_errors;public.update(status='STOPPED' if self.cleaned else 'UNKNOWN',cleanupConfirmed=self.cleaned,containers=stopped,cleanupErrors=cleanup_errors,
            syntheticDataRemoved=self.cleaned,
            runtimeEvidenceFiles=sorted(path.name for path in (self.folder/'evidence').glob('*.json')) if (self.folder/'evidence').is_dir() else [])
        return public
