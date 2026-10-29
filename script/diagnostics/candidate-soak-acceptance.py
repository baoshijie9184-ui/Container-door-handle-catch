"""Opt-in multi-account soak on an owned candidate; never calls a model.

Accounts are synthetic, distinct database identities provisioned only in the
verified rehearsal MySQL. Their sessions and receipts remain in that disposable
copy for inspection until normal candidate cleanup removes the isolated volumes.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
from pathlib import Path
import statistics
import subprocess
import threading
import time
import uuid

from candidate_environment import CandidateEnvironment, probe_source, timestamp


def percentile(values, quantile):
    return sorted(values)[max(0, int(len(values)*quantile)-1)] if values else None


def provision_source(candidate,names):
    if not 1<=len(names)<=32 or len(set(names))!=len(names) or any(not re.fullmatch(r'soak_[a-f0-9]{10}_[0-9]{1,2}',n) for n in names):
        raise ValueError('Only distinct generated soak account names are allowed')
    source=probe_source(candidate).replace("print('owned-candidate-ready')",'')+'''
ids=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+project,'--filter','label=com.docker.compose.service=mysql']).decode().split();assert len(ids)==1
row=json.loads(subprocess.check_output(['docker','inspect',ids[0]]))[0];assert row['Config']['Labels']['io.doorhandle.rehearsal']==project
names=NAMES
sql="START TRANSACTION;"+chr(10)+chr(10).join("INSERT INTO users(username,password,role) SELECT '"+name+"',password,'INSPECTOR' FROM users WHERE username='inspector.demo';" for name in names)+chr(10)+"COMMIT;"+chr(10)+"SELECT id,username FROM users WHERE username IN ("+','.join("'"+n+"'" for n in names)+");"
r=subprocess.run(['docker','exec','-i',ids[0],'sh','-c','MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -u"$MYSQL_USER" "$MYSQL_DATABASE" --batch --skip-column-names'],input=sql,text=True,capture_output=True,timeout=25);assert r.returncode==0
rows=[line.split(chr(9)) for line in r.stdout.splitlines()];assert len(rows)==len(names)
print(json.dumps({'users':[{'id':int(r[0]),'username':r[1]} for r in rows]}))
'''.replace('NAMES',repr(names))
    compile(source,'owned_soak_provision','exec')
    return source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-report',required=True)
    parser.add_argument('--directory',required=True)
    parser.add_argument('--accounts',type=int,default=20)
    parser.add_argument('--seconds',type=int,default=3600)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if not args.execute or not 5<=args.accounts<=32 or not 3600<=args.seconds<=7200:
        parser.error('Use --execute, 5..32 distinct accounts and 3600..7200 seconds')
    env=CandidateEnvironment(args.candidate_report,args.directory,local_port=18090)
    report={'startedAt':timestamp(),'project':env.project,'release':env.candidate['release'],
            'sourceSha256':env.candidate['sourceSha256'],'harnessSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'transportHarnessSha256':hashlib.sha256(Path(__file__).with_name('candidate_environment.py').read_bytes()).hexdigest(),
            'passed':False,'accountCount':args.accounts,'requestedSeconds':args.seconds,
            'modelRequests':None,'samples':0,'commands':0,'commandReceipts':[],'errors':[],'resources':[],
            'scope':'Distinct synthetic inspectors, concurrent authenticated reads and local /help commands; not model throughput or a multi-day uptime claim',
            'cleanup':{'complete':False,'accountsRetainedInDisposableCandidate':True}}
    def save():env.write('result.json',report)
    def remote(code,timeout=40):
        r=subprocess.run(env.ssh+['doorhandle-bj','python3 -'],input=code,text=True,capture_output=True,timeout=timeout)
        if r.returncode:
            env.write('remote-error.json',{'exitCode':r.returncode,'stderr':r.stderr[-3000:]})
            raise RuntimeError('Owned remote diagnostic failed')
        return json.loads(r.stdout)
    accounts=[];durations=[];command_times=[];save()
    try:
        with env:
            prefix='soak_'+uuid.uuid4().hex[:10]+'_'
            names=[prefix+str(n) for n in range(args.accounts)]
            report['provisionedNames']=names;save()
            provision=provision_source(env.candidate,names)
            users=remote(provision)['users'];report['identities']=users;save()
            for user in users:
                client=env.client()
                env.api(client,'POST','/api/auth/login',json={'username':user['username'],'password':os.environ.get('DOORHANDLE_DEMO_PASSWORD','123456')})
                identity=env.api(client,'GET','/api/auth/check')
                assert identity['userId']==user['id'] and identity['role']=='INSPECTOR'
                sid=env.api(client,'POST','/api/chat-assistant/sessions')['sessionId']
                accounts.append({'client':client,'sessionId':sid,'prefix':'/api/agent/conversations/'+sid,'submitted':[]})
            report['sessionIds']=[a['sessionId'] for a in accounts];save()
            # Isolation is checked with real server authorization, not cookies alone.
            env.api(accounts[1]['client'],'GET',accounts[0]['prefix']+'/control',expected=404)
            def sample(account):
                start=time.monotonic()
                control=env.api(account['client'],'GET',account['prefix']+'/control')
                env.api(account['client'],'GET',account['prefix']+'/workbench')
                for command in account['submitted']:
                    if command['done']:continue
                    item=next((i for i in control['inputs'] if i['id']==command['id']),None)
                    if item and item['status']=='COMPLETED':
                        command['done']=True;command_times.append(time.monotonic()-command['start'])
                        command['receipt']['status']='COMPLETED'
                    elif item and item['status'] in {'FAILED','CANCELLED','NEEDS_REVIEW'}:
                        raise AssertionError('Deterministic command has an unsuccessful receipt')
                    elif time.monotonic()-command['start']>60:
                        raise AssertionError('Command exceeds sixty-second fairness gate')
                return (time.monotonic()-start)*1000
            def command(account,index):
                item={'id':str(uuid.uuid4()),'start':time.monotonic(),'done':False}
                receipt={'id':item['id'],'sessionId':account['sessionId'],'submittedAt':timestamp(),'status':'SUBMITTING'}
                report['commandReceipts'].append(receipt);item['receipt']=receipt;save()
                account['submitted'].append(item)
                env.api(account['client'],'POST',account['prefix']+'/inputs',headers={'X-Agent-Action':'conversation-control'},
                        json={'id':item['id'],'mode':'NEXT_TURN','content':'/help','entryPoint':'CHAT' if index%2 else 'AGUI'})
                report['commands']+=1
                receipt['status']='SUBMITTED';save()
            resource_code='''import json,subprocess
project=PROJECT
ids=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+project]).decode().split()
assert len(ids)>=11
rows=json.loads(subprocess.check_output(['docker','inspect',*ids]))
assert all(r['Config']['Labels'].get('io.doorhandle.rehearsal')==project for r in rows)
print(json.dumps({'containers':[{'id':r['Id'],'service':r['Config']['Labels']['com.docker.compose.service'],'startedAt':r['State']['StartedAt'],'restarts':r['RestartCount'],'oom':r['State']['OOMKilled'],'health':r['State'].get('Health',{}).get('Status')} for r in rows],
 'stats':[json.loads(line) for line in subprocess.check_output(['docker','stats','--no-stream','--format','{{json .}}',*ids]).decode().splitlines()]}))
'''.replace('PROJECT',repr(env.project))
            baseline=remote(resource_code);report['resources'].append({'at':timestamp(),**baseline});save()
            active_lock=threading.Lock();active=0;report['maxConcurrentReaders']=0
            sample_inner=sample
            def concurrent_sample(account):
                nonlocal active
                with active_lock:
                    active+=1;report['maxConcurrentReaders']=max(report['maxConcurrentReaders'],active)
                try:return sample_inner(account)
                finally:
                    with active_lock:active-=1
            started=time.monotonic();next_commands=started;next_resources=started+60
            with ThreadPoolExecutor(max_workers=args.accounts) as pool:
                while time.monotonic()-started<args.seconds:
                    cycle=time.monotonic()
                    if cycle>=next_commands:
                        for index,account in enumerate(accounts):command(account,index)
                        next_commands+=60
                    values=list(pool.map(concurrent_sample,accounts));durations.extend(values);report['samples']+=len(values)
                    if cycle>=next_resources:
                        resource=remote(resource_code)
                        assert resource['containers']==baseline['containers'],'Candidate restarted or changed during soak'
                        report['resources'].append({'at':timestamp(),**resource});next_resources+=60
                        print(json.dumps({'elapsedSeconds':round(time.monotonic()-started),'samples':report['samples'],'commands':report['commands'],'readP95Millis':round(percentile(durations,.95))}),flush=True)
                    report['elapsedSeconds']=round(time.monotonic()-started,3);save()
                    time.sleep(max(0,5-(time.monotonic()-cycle)))
                report['elapsedSeconds']=round(time.monotonic()-started,3);save()
                deadline=time.monotonic()+60
                while any(not c['done'] for a in accounts for c in a['submitted']):
                    list(pool.map(concurrent_sample,accounts))
                    if time.monotonic()>deadline:raise AssertionError('Final commands still active')
                    time.sleep(.5)
            report['readP50Millis']=round(statistics.median(durations),3)
            report['readP95Millis']=round(percentile(durations,.95),3)
            report['readP99Millis']=round(percentile(durations,.99),3)
            report['commandP95Seconds']=round(percentile(command_times,.95),3)
            assert report['elapsedSeconds']>=args.seconds and report['readP95Millis']<2000
            assert report['maxConcurrentReaders']>4
            assert len(command_times)==report['commands'] and max(command_times)<60
            assert all(type(u['id']) is int and u['id']>0 for u in users)
            usage_code=probe_source(env.candidate).replace("print('owned-candidate-ready')",'')+'''
ids=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+project,'--filter','label=com.docker.compose.service=mysql']).decode().split();assert len(ids)==1
row=json.loads(subprocess.check_output(['docker','inspect',ids[0]]))[0];assert row['Config']['Labels']['io.doorhandle.rehearsal']==project
sql="SELECT COUNT(*) FROM agent_run_event e JOIN agent_run r ON r.run_id=e.run_id WHERE e.event_type='MODEL_ATTEMPT_STARTED' AND r.user_id IN (USER_IDS);"
r=subprocess.run(['docker','exec','-i',ids[0],'sh','-c','MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -u"$MYSQL_USER" "$MYSQL_DATABASE" --batch --skip-column-names'],input=sql,text=True,capture_output=True,timeout=30);assert r.returncode==0
print(json.dumps({'modelAttempts':int(r.stdout.strip())}))
'''.replace('USER_IDS',','.join(str(u['id']) for u in users))
            report['modelRequests']=remote(usage_code)['modelAttempts']
            report['modelRequestBasis']='Persistent MODEL_ATTEMPT_STARTED events for these distinct synthetic user IDs'
            assert report['modelRequests']==0,'Local command load unexpectedly invoked a model'
            report['cleanup']['complete']=True
            report['passed']=True
    except BaseException as error:
        report['errors'].append({'type':type(error).__name__,'message':str(error)[:300]});save();raise
    finally:
        report['finishedAt']=timestamp();save()
    return 0


if __name__=='__main__':raise SystemExit(main())
