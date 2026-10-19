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


def timestamp():
    return datetime.now(CST).isoformat()


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
    def __init__(self,report,directory):
        self.candidate=json.loads(Path(report).read_text(encoding='utf-8-sig'))
        self.project=candidate_identity(self.candidate)
        self.out=Path(directory).resolve()
        if self.out.exists() or not self.out.is_relative_to((ROOT/'work').resolve()) or self.out==(ROOT/'work').resolve():
            raise ValueError('Use a new project work directory')
        self.out.mkdir(parents=True,mode=0o700)
        self.ssh=['ssh','-F',str(ROOT/'work/cloud/ssh-config'),'-o','BatchMode=yes','-o','ConnectTimeout=10']
        self.tunnel=None
        self.clients=[]
        self.base='http://127.0.0.1:18089'

    def __enter__(self):
        try:
            probe=subprocess.run(self.ssh+['doorhandle-bj','python3 -'],input=probe_source(self.candidate),capture_output=True,text=True,timeout=25)
            if probe.returncode or probe.stdout.strip()!='owned-candidate-ready':
                raise RuntimeError('Candidate ownership, image, health or listener check failed')
            with socket.socket() as listener:listener.bind(('127.0.0.1',18089))
            with (self.out/'ssh.log').open('wb') as log:
                self.tunnel=subprocess.Popen(self.ssh+['-o','ExitOnForwardFailure=yes','-N','-L','127.0.0.1:18089:127.0.0.1:18089','doorhandle-bj'],stdout=log,stderr=log)
            self.write('transport.json',{'project':self.project,'release':self.candidate['release'],'startedAt':timestamp(),'ownedTunnelPid':self.tunnel.pid})
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
