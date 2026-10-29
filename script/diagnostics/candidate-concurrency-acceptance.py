"""Opt-in four-account HTTP fairness/load acceptance on an owned rehearsal only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
import time
import uuid

from candidate_environment import BAILIAN_TEST_MODELS, CandidateEnvironment, timestamp

ACCOUNTS=('inspector.demo','supervisor.demo','inspector.demo2','supervisor.demo2')
TERMINAL={'COMPLETED','APPLIED','CANCELLED','FAILED','EXPIRED'}


def identifier():return str(uuid.uuid4())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-report',required=True)
    parser.add_argument('--directory',required=True)
    parser.add_argument('--model',choices=BAILIAN_TEST_MODELS,default='dashscope:qwen3.8-flash')
    parser.add_argument('--execute',action='store_true',help='Creates four private sessions and at most two real-model plans')
    args=parser.parse_args()
    if not args.execute:parser.error('Explicit --execute is required')
    environment=CandidateEnvironment(args.candidate_report,args.directory)
    report={'startedAt':timestamp(),'project':environment.project,'release':environment.candidate['release'],
            'sourceSha256':environment.candidate['sourceSha256'],'passed':False,'checks':[],
            'accounts':[],'modelId':args.model,'load':{'minimumSeconds':600,'samples':0,'failures':0},'cleanup':{'complete':False},
            'scope':'four demo accounts on an isolated monolith; not a larger capacity or distributed fairness claim'}
    accounts=[]
    def save():environment.write('result.json',report)
    def check(name,condition):
        report['checks'].append({'name':name,'passed':bool(condition),'at':timestamp()});save()
        if not condition:raise AssertionError(name)
        print(name,flush=True)
    save()
    try:
        with environment as env:
            def api(account,method,path,**kwargs):return env.api(account['client'],method,path,**kwargs)
            def workbench(account):return api(account,'GET',account['prefix']+'/workbench')['items']
            def control(account):return api(account,'GET',account['prefix']+'/control')
            def enqueue(account,content='/help',entry='CHAT'):
                id=identifier();account['submitted'].append(id);save()
                body={'id':id,'mode':'NEXT_TURN','content':content,'entryPoint':entry}
                value=api(account,'POST',account['prefix']+'/inputs',headers={'X-Agent-Action':'conversation-control'},json=body)
                return value,body
            def command(account,item,action):
                return api(account,'POST',account['prefix']+'/workbench/'+item['id'],headers={'X-Agent-Action':'workbench'},
                           json={'requestId':identifier(),'revision':item['revision'],'action':action,'input':{}})
            try:
                for index,name in enumerate(ACCOUNTS):
                    client=env.client();account={'client':client,'submitted':[],'name':name,'blocking':index<2}
                    env.api(client,'POST','/api/auth/login',json={'username':name,'password':os.environ.get('DOORHANDLE_DEMO_PASSWORD','123456')})
                    identity=env.api(client,'GET','/api/auth/check')
                    check(name+' authenticated with the expected role',identity['username']==name and identity['role']==('SUPERVISOR' if name.startswith('supervisor') else 'INSPECTOR'))
                    sid=env.api(client,'POST','/api/chat-assistant/sessions')['sessionId']
                    account.update(id=sid,prefix='/api/agent/conversations/'+sid)
                    accounts.append(account);report['accounts'].append({'name':name,'sessionId':sid,'blocking':index<2,'submitted':account['submitted']});save()
                for account in accounts[:2]:
                    models=api(account,'GET','/agui/models')['models']
                    selected=next((m for m in models if m['id']==args.model and m['provider']=='dashscope' and m['configured']),None)
                    if selected is None:raise RuntimeError('Configured Bailian test model unavailable; do not switch to a direct paid provider')
                    selection=api(account,'GET',account['prefix']+'/model-selection')
                    api(account,'POST',account['prefix']+'/model-selection',headers={'X-Agent-Action':'workbench'},
                        json={'modelId':selected['id'],'revision':selection['revision'],'requestId':identifier()})
                    # One submission only. A lost response is inspected through workbench,
                    # never retried or replaced with an unconfirmed second model request.
                    try:
                        api(account,'POST','/api/chat-assistant/messages',json={'sessionId':account['id'],
                            'content':'/plan 仅制定查看本人授权检测任务的计划，调用 submit_plan 后等待我批准，不执行计划。'},timeout=120)
                    except Exception:
                        if not any(item['kind']=='EXECUTION' and item['status']=='WAITING_PLAN' for item in workbench(account)):raise
                    deadline=time.monotonic()+30
                    while time.monotonic()<deadline:
                        items=workbench(account)
                        # Only inspect the public DTO. SDK/checkpoint fields such as
                        # yieldReady are intentionally never exposed to the browser.
                        if any(i['kind']=='EXECUTION' and i['status']=='WAITING_PLAN' for i in items):break
                        time.sleep(.5)
                    else:raise AssertionError('Plan did not persist its safe waiting boundary')
                    check(account['name']+' waits for an unapproved plan',any(i['kind']=='PLAN' and i['status']=='PENDING' for i in items))
                    for _ in range(16):enqueue(account)
                    check(account['name']+' retains exactly sixteen blocked inputs',len([i for i in control(account)['inputs'] if i['status']=='QUEUED'])==16)
                    extra=identifier()
                    api(account,'POST',account['prefix']+'/inputs',expected=429,headers={'X-Agent-Action':'conversation-control'},
                        json={'id':extra,'mode':'NEXT_TURN','content':'/help','entryPoint':'CHAT'})
                    check(account['name']+' rejects the seventeenth pending input',True)
                first=accounts[0];pending=control(first)['inputs'][0]
                api(first,'POST',first['prefix']+'/inputs/'+pending['id'],headers={'X-Agent-Action':'conversation-control'},
                    json={'revision':pending['revision'],'content':'/help edited'})
                api(first,'POST',first['prefix']+'/inputs/'+pending['id'],expected=409,headers={'X-Agent-Action':'conversation-control'},
                    json={'revision':pending['revision'],'content':'/help stale'})
                check('Stale input editing is refused without applying a second change',True)
                api(accounts[2],'GET',first['prefix']+'/control',expected=404)
                check('Another employee cannot read the private control state',True)
                targets=[];started=time.monotonic()
                for index,account in enumerate(accounts[2:]):
                    value,body=enqueue(account,entry='CHAT' if index==0 else 'AGUI')
                    repeated=api(account,'POST',account['prefix']+'/inputs',headers={'X-Agent-Action':'conversation-control'},json=body)
                    check(account['name']+' duplicate submission preserves its identity',repeated['id']==value['id'])
                    targets.append((account,value['id']))
                while time.monotonic()-started<60:
                    states=[next(i for i in control(a)['inputs'] if i['id']==id)['status'] for a,id in targets]
                    if all(s=='COMPLETED' for s in states):break
                    if any(s in TERMINAL-{'COMPLETED'} for s in states):raise AssertionError('An executable input failed')
                    time.sleep(.5)
                else:raise AssertionError('Unblocked accounts exceeded the sixty-second fairness gate')
                report['fairnessSeconds']=round(time.monotonic()-started,3)
                check('Both available accounts finish within sixty seconds behind thirty-two blocked inputs',True)

                def sample(account):
                    started=time.monotonic()
                    state=control(account);api(account,'GET',account['prefix']+'/workbench')
                    return {'millis':round((time.monotonic()-started)*1000),'queued':sum(i['status']=='QUEUED' for i in state['inputs'])}
                started=time.monotonic();next_commands=started+60;durations=[]
                with ThreadPoolExecutor(max_workers=4) as executor:
                    while time.monotonic()-started<600:
                        cycle=time.monotonic()
                        for index,measurement in enumerate(executor.map(sample,accounts)):
                            report['load']['samples']+=1;durations.append(measurement['millis'])
                            if index<2 and measurement['queued']!=16:raise AssertionError('An unapproved plan dispatched a queued input')
                        if time.monotonic()>=next_commands:
                            for index,account in enumerate(accounts[2:]):enqueue(account,entry='CHAT' if index==0 else 'AGUI')
                            next_commands+=60
                            print('Four-account load elapsed '+str(int(time.monotonic()-started))+' seconds',flush=True)
                        report['load']['elapsedSeconds']=round(time.monotonic()-started,3);save()
                        time.sleep(max(0,2-(time.monotonic()-cycle)))
                report['load']['elapsedSeconds']=round(time.monotonic()-started,3)
                report['load']['combinedReadP95Millis']=sorted(durations)[max(0,int(len(durations)*.95)-1)]
                check('Four accounts remain isolated and responsive for at least ten minutes',report['load']['elapsedSeconds']>=600)
                deadline=time.monotonic()+60
                while time.monotonic()<deadline:
                    if all(all(i['status']=='COMPLETED' for i in control(a)['inputs'] if i['id'] in a['submitted']) for a in accounts[2:]):break
                    time.sleep(.5)
                else:raise AssertionError('Queued deterministic commands did not finish')
                check('Every repeated deterministic command has one completed input receipt',True)
                report['passed']=True
            finally:
                # Withdraw the known private queue before cancelling plans. Otherwise
                # cleanup itself could unblock and execute thirty-two pending inputs.
                errors=[]
                for account in accounts:
                    try:
                        for item in control(account)['inputs']:
                            if item['id'] in account['submitted'] and item['status']=='QUEUED':
                                api(account,'POST',account['prefix']+'/inputs/'+item['id'],headers={'X-Agent-Action':'conversation-control'},
                                    json={'revision':item['revision'],'content':None})
                        state=control(account)
                        if any(i['id'] in account['submitted'] and i['status'] in {'QUEUED','STARTED'} for i in state['inputs']):
                            raise RuntimeError('Private input remains active; plan kept blocked')
                        for item in workbench(account):
                            if item['kind']=='EXECUTION' and item['status'] in {'WAITING_PLAN','WAITING_INPUT','WAITING_CHILD','NEEDS_REVIEW'}:
                                command(account,item,'cancel')
                    except Exception as error:errors.append({'account':account['name'],'errorType':type(error).__name__})
                report['cleanup']={'complete':not errors,'errors':errors}
                if errors:report['passed']=False
                save()
    except Exception as error:
        report['passed']=False;report['errorType']=type(error).__name__;save()
        raise
    finally:
        report['finishedAt']=timestamp();save()
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
