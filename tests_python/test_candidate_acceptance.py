"""Owned candidate admission and cleanup must fail closed without cloud access."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

SCRIPTS=Path(__file__).resolve().parents[1]/'script/diagnostics'
SPEC=importlib.util.spec_from_file_location('candidate_environment',SCRIPTS/'candidate_environment.py')
environment=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(environment)
SPEC=importlib.util.spec_from_file_location('candidate_concurrency',SCRIPTS/'candidate-concurrency-acceptance.py')
concurrency=importlib.util.module_from_spec(SPEC)
with __import__('unittest.mock',fromlist=['patch']).patch.dict(sys.modules,{'candidate_environment':environment}):SPEC.loader.exec_module(concurrency)


def receipt():
    return {'passed':True,'kept':True,'productionChanged':False,'project':'doorhandle-rehearsal-123456abcdef',
            'port':18089,'release':'ci-26-41dcd195e2b2','sourceSha256':'a'*64,
            'candidateImages':{s:'sha256:'+'b'*64 for s in ('backend','nginx','mem0')}}


@pytest.mark.parametrize('key,value',[
    ('passed',False),('kept',False),('productionChanged',True),('port',8088),
    ('project','doorhandlecatch-monolith'),('project','doorhandle-rehearsal-123456abcdef;echo x'),
    ('release','latest'),('sourceSha256','unknown'),('candidateImages',{'backend':'latest'})])
def test_candidate_admission_rejects_production_or_ambiguous_identity(key,value):
    report=receipt();report[key]=value
    with pytest.raises(ValueError):environment.candidate_identity(report)


def test_remote_probe_checks_every_image_and_private_listener():
    source=environment.probe_source(receipt())
    compile(source,'candidate_probe','exec')
    assert "row['Image']==image" in source and "row['State']['Running']" in source
    assert "'HostIp':'127.0.0.1','HostPort':'18089'" in source
    assert 'docker compose' not in source and 'cloud.env' not in source


def test_unknown_image_identity_stops_before_tunnel_or_login(tmp_path,monkeypatch):
    report=tmp_path/'receipt.json';report.write_text(json.dumps(receipt()))
    monkeypatch.setattr(environment,'ROOT',tmp_path)
    monkeypatch.setattr(environment.subprocess,'run',lambda *a,**k:type('Probe',(),{'returncode':1,'stdout':''})())
    def forbidden(*a,**k):raise AssertionError('No tunnel may open after a failed image probe')
    monkeypatch.setattr(environment.subprocess,'Popen',forbidden)
    with pytest.raises(RuntimeError,match='ownership'):
        with environment.CandidateEnvironment(report,tmp_path/'work'/'probe'):pass


class Clock:
    value=0
    def monotonic(self):return self.value
    def sleep(self,seconds):self.value+=seconds


class FakeCandidate:
    """Realistic HTTP states; model waiting and elapsed time are deterministic here."""
    def __init__(self,*,fail_during_load=False):
        self.project=receipt()['project'];self.candidate=receipt();self.snapshots=[];self.states={};self.events=[]
        self.fail_during_load=fail_during_load;self.control_reads=0
    def __enter__(self):return self
    def __exit__(self,*ignored):pass
    def write(self,name,value):self.snapshots.append(deepcopy(value))
    def client(self):return {'name':None}
    def api(self,client,method,path,expected=200,**kw):
        body=kw.get('json',{});status=200;value={};name=client['name']
        if path=='/api/auth/login':client['name']=body['username']
        elif path=='/api/auth/check':value={'username':name,'role':'SUPERVISOR' if name.startswith('supervisor') else 'INSPECTOR'}
        elif path=='/api/chat-assistant/sessions':
            sid='s'+str(len(self.states));self.states[sid]={'owner':name,'inputs':[],'waiting':False,'revision':0};value={'sessionId':sid}
        elif path=='/api/chat-assistant/messages':self.states[body['sessionId']]['waiting']=True
        elif path=='/agui/models':value={'models':[{'id':'deepseek:test','provider':'deepseek','configured':True}]}
        else:
            parts=path.split('/');sid=parts[4];state=self.states[sid]
            if state['owner']!=name:status=404
            elif path.endswith('/model-selection'):value={'modelId':'deepseek:test','revision':0}
            elif path.endswith('/workbench'):
                value={'items':[{'id':'execution','kind':'EXECUTION','status':'WAITING_PLAN','revision':0,'data':{}},
                                {'id':'plan','kind':'PLAN','status':'PENDING','revision':0,'data':{}}] if state['waiting'] else []}
            elif '/workbench/' in path:
                assert not any(i['status'] in {'QUEUED','STARTED'} for i in state['inputs']), 'Cleanup cancelled a plan before draining its queue'
                state['waiting']=False;self.events.append(('cancel-plan',name))
            elif path.endswith('/control'):
                self.control_reads+=1
                if self.fail_during_load and self.control_reads==40:
                    raise RuntimeError('Injected read failure, cleanup can still inspect the next request')
                value={'run':{'phase':'IDLE'},'inputs':deepcopy(state['inputs'])}
            elif path.endswith('/inputs'):
                old=next((i for i in state['inputs'] if i['id']==body['id']),None)
                if old:value=old
                elif len([i for i in state['inputs'] if i['status']=='QUEUED'])>=16:status=429
                else:
                    value={'id':body['id'],'content':body['content'],'status':'QUEUED' if state['waiting'] else 'COMPLETED','revision':0}
                    state['inputs'].append(value)
            elif '/inputs/' in path:
                item=next(i for i in state['inputs'] if i['id']==parts[-1])
                if item['revision']!=body['revision']:status=409
                else:
                    item['revision']+=1;item['content']=body['content']
                    if body['content'] is None:item['status']='CANCELLED';self.events.append(('withdraw',name))
                    value=item
            else:raise AssertionError('Unexpected test route')
        assert status==expected,(method,path,status,expected)
        return deepcopy(value) if expected==200 else None


def run_harness(monkeypatch,candidate):
    clock=Clock()
    monkeypatch.setattr(concurrency,'CandidateEnvironment',lambda *a:candidate)
    monkeypatch.setattr(concurrency.time,'monotonic',clock.monotonic)
    monkeypatch.setattr(concurrency.time,'sleep',clock.sleep)
    monkeypatch.setattr(sys,'argv',['acceptance','--candidate-report','receipt.json','--directory','work/evidence','--execute'])
    return concurrency.main()


def test_full_harness_drains_private_queue_before_unblocking_plans(monkeypatch):
    candidate=FakeCandidate()
    assert run_harness(monkeypatch,candidate)==0
    final=candidate.snapshots[-1]
    assert final['passed'] and final['cleanup']['complete'] and final['load']['elapsedSeconds']>=600
    assert final['load']['samples']>=1200
    assert len([e for e in candidate.events if e[0]=='withdraw'])==32
    assert len([e for e in candidate.events if e[0]=='cancel-plan'])==2


def test_read_failure_does_not_report_pass_and_still_withdraws_owned_inputs(monkeypatch):
    candidate=FakeCandidate(fail_during_load=True)
    with pytest.raises(RuntimeError):run_harness(monkeypatch,candidate)
    final=candidate.snapshots[-1]
    assert not final['passed'] and final['cleanup']['complete']
    assert all(i['status']!='QUEUED' for state in candidate.states.values() for i in state['inputs'])
