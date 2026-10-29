"""Owned rehearsal transport shared by explicit, isolated HTTP acceptance tools."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import socket
import subprocess
import time

import requests

ROOT=Path(__file__).resolve().parents[2]
CST=timezone(timedelta(hours=8))
BAILIAN_TEST_MODELS=('dashscope:qwen3.8-flash','dashscope:qwen3.8-max-0902',
                     'dashscope:deepseek-v4.1-flash','dashscope:glm-5.3')


def timestamp():
    return datetime.now(CST).isoformat()


def conversation_not_started(control,runs,history):
    """A browser wait failure does not prove that a chat was never accepted."""
    return (control.get('run',{}).get('phase')=='IDLE' and control.get('inputs')==[] and runs==[]
            and isinstance(history.get('messages'),list)
            and all(message.get('role')=='assistant' and message.get('intent')=='GREETING'
                    for message in history['messages']))


def owned_child_denial(items,root):
    if root.get('kind')!='EXECUTION' or root.get('status')!='WAITING_CHILD' or not root.get('id'):return None
    children=[i for i in items if i.get('kind')=='CHILD' and i.get('status')=='WAITING_INPUT'
              and i.get('data',{}).get('parentId')==root['id'] and i.get('id')]
    matches=[(child,q) for child in children for q in items if q.get('kind')=='QUESTION'
             and q.get('status')=='PENDING' and q.get('data',{}).get('parentId')==child['id']
             and re.search(r'无访问权限|无权|资源不存在|无权限|access denied|not found',q.get('data',{}).get('text',''),re.I)]
    if len(matches)!=1:return None
    child,question=matches[0]
    return {'questionId':question['id'],'childId':child['id'],'rootId':root['id'],'text':question['data']['text']}


def candidate_identity(value):
    if value.get('passed') is not True or value.get('kept') is not True or value.get('productionChanged') is not False:
        raise ValueError('A successful, retained, isolated candidate is required')
    project=value.get('project','')
    if not isinstance(project,str) or not re.fullmatch(r'doorhandle-rehearsal-[a-f0-9]{12}',project) or value.get('port')!=18089:
        raise ValueError('Candidate project/listener is invalid')
    if not re.fullmatch(r'ci-[0-9]+-[a-f0-9]{12}',value.get('release','')):
        raise ValueError('Candidate release is invalid')
    images=value.get('candidateImages',{})
    if set(images)!={'backend','nginx','mem0'} or any(not re.fullmatch(r'sha256:[a-f0-9]{64}',v) for v in images.values()):
        raise ValueError('Exact candidate image identities are required')
    if not re.fullmatch(r'[a-f0-9]{64}',value.get('sourceSha256','')):
        raise ValueError('Candidate source archive identity is required')
    return project


def probe_source(candidate):
    project=candidate_identity(candidate)
    return '''import json,subprocess
project='''+repr(project)+'''
expected='''+repr(candidate['candidateImages'])+'''
for service,image in expected.items():
    ids=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+project,'--filter','label=com.docker.compose.service='+service]).decode().split()
    assert len(ids)==1
    row=json.loads(subprocess.check_output(['docker','inspect',ids[0]]))[0]
    assert row['Config']['Labels']['io.doorhandle.rehearsal']==project
    assert row['Image']==image and row['State']['Running']
    assert row['State'].get('Health',{}).get('Status')=='healthy'
    if service=='nginx':
        assert row['NetworkSettings']['Ports']['80/tcp']==[{'HostIp':'127.0.0.1','HostPort':'18089'}]
print('owned-candidate-ready')
'''


class CandidateEnvironment:
    """Does not start cloud instances, modify Compose or read server credentials."""
    def __init__(self,report,directory,*,local_port=18089):
        self.candidate=json.loads(Path(report).read_text(encoding='utf-8-sig'))
        self.project=candidate_identity(self.candidate)
        if type(local_port) is not int or local_port not in (18089,18090):
            raise ValueError('Only the two reserved loopback candidate ports are allowed')
        self.local_port=local_port
        self.out=Path(directory).resolve()
        if self.out.exists() or not self.out.is_relative_to((ROOT/'work').resolve()) or self.out==(ROOT/'work').resolve():
            raise ValueError('Use a new project work directory')
        self.out.mkdir(parents=True,mode=0o700)
        self.ssh=['ssh','-F',str(ROOT/'work/cloud/ssh-config'),'-o','BatchMode=yes','-o','ConnectTimeout=10']
        self.tunnel=None
        self.clients=[]
        self.base='http://127.0.0.1:'+str(local_port)

    def __enter__(self):
        try:
            probe=subprocess.run(self.ssh+['doorhandle-bj','python3 -'],input=probe_source(self.candidate),capture_output=True,text=True,timeout=25)
            if probe.returncode or probe.stdout.strip()!='owned-candidate-ready':
                raise RuntimeError('Candidate ownership, image, health or listener check failed')
            with socket.socket() as listener:listener.bind(('127.0.0.1',self.local_port))
            with (self.out/'ssh.log').open('wb') as log:
                self.tunnel=subprocess.Popen(self.ssh+['-o','ExitOnForwardFailure=yes','-N','-L',f'127.0.0.1:{self.local_port}:127.0.0.1:18089','doorhandle-bj'],stdout=log,stderr=log)
            self.write('transport.json',{'project':self.project,'release':self.candidate['release'],'startedAt':timestamp(),'ownedTunnelPid':self.tunnel.pid,'localPort':self.local_port,'remotePort':18089})
            client=self.client()
            for _ in range(40):
                if self.tunnel.poll() is not None:raise RuntimeError('Owned SSH tunnel ended')
                try:
                    if client.get(self.base+'/nginx-health',timeout=1).ok:return self
                except requests.RequestException:pass
                time.sleep(.25)
            raise RuntimeError('Candidate tunnel did not become ready')
        except BaseException:
            self.__exit__(None,None,None)
            raise

    def __exit__(self,*ignored):
        for client in self.clients:client.close()
        if self.tunnel is not None and self.tunnel.poll() is None:
            self.tunnel.terminate()
            self.tunnel.wait(timeout=15)

    def client(self):
        client=requests.Session();client.trust_env=False
        self.clients.append(client)
        return client

    def api(self,client,method,path,*,expected=200,**kwargs):
        if not path.startswith(('/api/','/agui/')) or '://' in path or '?' in path or '..' in path:
            raise ValueError('Only fixed relative application paths are accepted')
        response=client.request(method,self.base+path,timeout=kwargs.pop('timeout',30),**kwargs)
        if response.status_code!=expected:
            raise RuntimeError('Candidate API returned HTTP '+str(response.status_code))
        if expected!=200:return None
        value=response.json()
        if isinstance(value,dict) and 'code' in value:
            if value['code']!=200:raise RuntimeError('Candidate API rejected the operation')
            return value.get('data')
        return value

    def write(self,name,value):
        if not re.fullmatch(r'[a-z0-9-]+\.json',name):raise ValueError('Invalid evidence filename')
        target=self.out/name;temp=target.with_suffix('.tmp')
        temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(target)
