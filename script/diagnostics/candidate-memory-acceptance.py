"""Owned-candidate ten-session memory exercise and two actual backend restarts."""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'script/diagnostics'))
from candidate_environment import CandidateEnvironment, probe_source, timestamp

def checkpoint(value,candidate):
    if any(value.get(key)!=candidate.get(key) for key in ('project','release','sourceSha256')):
        raise ValueError('Memory checkpoint belongs to another candidate')
    turns=value.get('turns',[]);restarts=value.get('restarts',[]);checks=value.get('checks',[])
    if (value.get('passed') is not False or value.get('errorType')!='AssertionError'
            or len(turns)!=9 or len(restarts)!=2 or not all(r.get('healthy') for r in restarts)
            or not re.fullmatch(r'DEMO-MEM-[a-f0-9]{10}',value.get('marker',''))
            or len({t.get('sessionId') for t in turns})!=9
            or any(t.get('number')!=i+1 or t.get('status')!='SUCCEEDED'
                   or t.get('receipt',{}).get('status')!='SUCCEEDED' for i,t in enumerate(turns))
            or not turns[0].get('createdMemoryId') or not checks
            or checks[-1]!={'name':'Session 9 reads corrected format across sessions','passed':False}
            or any(c.get('passed') is not True for c in checks[:-1])):
        raise ValueError('Only the verified ninth structured-question checkpoint may resume')
    result=deepcopy(value)
    result['priorFailure']={key:result.pop(key) for key in ('errorType','finishedAt') if key in result}
    result['priorFailure']['check']=result['checks'].pop()
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-report',required=True)
    parser.add_argument('--directory',required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--resume-from',help='Continue only a verified ninth-session structured-question checkpoint')
    args=parser.parse_args(argv)
    if not args.execute:parser.error('Explicit candidate mutations must be requested')
    env=CandidateEnvironment(args.candidate_report,args.directory)
    report={'startedAt':timestamp(),'release':env.candidate['release'],'sourceSha256':env.candidate['sourceSha256'],
            'project':env.project,'passed':False,'checks':[],'turns':[],'restarts':[],
            'scope':'ten short real HTTP sessions, not weeks of memory stability'}
    if args.resume_from:
        previous=Path(args.resume_from).resolve(strict=True)
        if not previous.is_relative_to(ROOT/'work') or previous.name!='result.json':
            raise ValueError('Resume requires a project-owned memory receipt')
        report=checkpoint(json.loads(previous.read_text(encoding='utf8')),env.candidate)
        report.update(resumedFrom=str(previous),resumedAt=timestamp())

    def save():env.write('result.json',report)
    def check(name,value):
        report['checks'].append({'name':name,'passed':bool(value)});save()
        if not value:raise AssertionError(name)
        print(name,flush=True)
    def remote(code,timeout=160):
        r=subprocess.run(env.ssh+['doorhandle-bj','python3 -'],input=code,text=True,capture_output=True,timeout=timeout)
        if r.returncode:raise RuntimeError('Owned diagnostic failed; private logs are not echoed')
        return json.loads(r.stdout.strip())

    save()
    try:
        with env:
            client=env.client();foreign=env.client()
            def api(method,path,**kw):return env.api(client,method,path,**kw)
            api('POST','/api/auth/login',json={'username':'inspector.demo','password':os.environ.get('DOORHANDLE_DEMO_PASSWORD','123456')})
            env.api(foreign,'POST','/api/auth/login',json={'username':'inspector.demo2','password':os.environ.get('DOORHANDLE_DEMO_PASSWORD','123456')})
            uid=api('GET','/api/auth/check')['userId'];assert isinstance(uid,int) and uid>0
            preference=api('GET','/api/agent/memories/preferences')
            check('Demo account reading and saving are enabled',preference['readEnabled'] and preference['saveEnabled'])
            initial=api('GET','/api/agent/memories')['items']
            baseline={i['id'] for i in initial}
            marker=report['marker'] if args.resume_from else 'DEMO-MEM-'+uuid.uuid4().hex[:10]
            if args.resume_from:
                owned_sessions={t['sessionId'] for t in report['turns']}
                baseline-={i['id'] for i in initial if marker in i['memory'] and i['sourceSessionId'] in owned_sessions}
            report['marker']=marker;save()
            def own_memory(predicate,source_session):
                found=[i for i in api('GET','/api/agent/memories')['items'] if i['id'] not in baseline and marker in i['memory'] and i['sourceSessionId']==source_session and predicate(i)]
                if len(found)!=1:raise AssertionError('One unambiguous new synthetic memory is required')
                return found[0]
            def native_ids(query):
                payload={'user_id':'doorhandlecatch:user:'+str(uid),'app_id':'doorhandlecatch','run_id':'synthetic-retrieval-check','scope':'ACCOUNT','query':query,'top_k':20}
                child="""import json,os,requests
r=requests.post('http://127.0.0.1:8081/memories/search',headers={'X-Doorhandle-Memory-Token':os.environ['MEM0_BRIDGE_TOKEN'],'X-Doorhandle-Memory-Protocol':'2'},json=PAYLOAD,timeout=40)
r.raise_for_status();value=r.json();assert value['code']==200
print(json.dumps({'ids':[i['id'] for i in value['data']]}))
""".replace('PAYLOAD',repr(payload))
                code='import json,subprocess\nproject='+repr(env.project)+'\ncode='+repr(child)+'\n'+"""
ids=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+project,'--filter','label=com.docker.compose.service=mem0']).decode().split();assert len(ids)==1
row=json.loads(subprocess.check_output(['docker','inspect',ids[0]]))[0];assert row['Config']['Labels'].get('io.doorhandle.rehearsal')==project
r=subprocess.run(['docker','exec','-i',ids[0],'python','-'],input=code,text=True,capture_output=True,timeout=50);assert r.returncode==0
print(r.stdout.strip())
"""
                return remote(code)['ids']
            def restart():
                code=probe_source(env.candidate).replace("print('owned-candidate-ready')",'')+"""
ids=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+project,'--filter','label=com.docker.compose.service=backend']).decode().split();assert len(ids)==1
before=json.loads(subprocess.check_output(['docker','inspect',ids[0]]))[0]
subprocess.run(['docker','restart','--time','15',ids[0]],check=True,stdout=subprocess.DEVNULL)
import time
for _ in range(100):
    after=json.loads(subprocess.check_output(['docker','inspect',ids[0]]))[0]
    if after['State'].get('Health',{}).get('Status')=='healthy':break
    time.sleep(1)
else:raise RuntimeError('Candidate backend restart failed')
assert after['Id']==before['Id'] and after['Image']==before['Image'] and after['State']['StartedAt']!=before['State']['StartedAt']
print(json.dumps({'containerId':after['Id'],'image':after['Image'],'before':before['State']['StartedAt'],'after':after['State']['StartedAt'],'healthy':True}))
"""
                value=remote(code);report['restarts'].append(value);save()
                check('Owned application restart '+str(len(report['restarts']))+' is healthy',True)
            selected=next(m for m in api('GET','/agui/models')['models'] if m['id']=='dashscope:qwen3.8-flash' and m['configured'])['id']
            statements=[
                '你好，请记住我的明确长期偏好：'+marker+' 验收资料的默认文件格式是 PDF。',
                '你好，请记住我的明确长期偏好：'+marker+' 验收资料的页边距统一使用两厘米。',
                '你好，请记住我的明确长期偏好：'+marker+' 验收资料的标题统一使用蓝色。',
                '你好，请记住我的明确长期偏好：'+marker+' 验收资料的时间统一使用 UTC+8。',
                '查询我对 '+marker+' 验收资料文件格式的长期偏好。',
                '你好，请记住我的明确长期偏好：'+marker+' 验收资料的金额统一使用人民币。',
                '你好，请记住我的明确长期偏好：'+marker+' 验收资料的长度单位统一使用毫米。',
                '查询我对 '+marker+' 验收资料标题颜色的长期偏好。',
                '查询我对 '+marker+' 验收资料文件格式的长期偏好。',
                '查询我对 '+marker+' 验收资料时区的长期偏好。']
            format_memory=None
            mutation_ids=[]
            if args.resume_from:
                for turn in report['turns']:
                    receipt=api('POST','/api/agent/memories/operations/'+turn['extractionId']+'/verify',headers={'X-Agent-Action':'memory-verify'})
                    if receipt['status']!='SUCCEEDED':raise ValueError('A prior extraction is no longer verified')
                format_memory=own_memory(lambda i:i['id']==report['turns'][0]['createdMemoryId'] and 'CSV' in i['memory'],report['turns'][0]['sessionId'])
                updates=[a for a in api('GET','/api/agent/memories/audit') if a['action']=='UPDATE'
                         and a.get('memoryId')==format_memory['id'] and a['outcome']=='SUCCEEDED']
                if len(updates)!=1:raise ValueError('A unique successful human correction is required')
                mutation_ids.append(updates[0]['requestId'])
                sid=report['turns'][-1]['sessionId'];prefix='/api/agent/conversations/'+sid
                items=api('GET',prefix+'/workbench')['items']
                questions=[i for i in items if i['kind']=='QUESTION' and i['status']=='PENDING'
                           and marker in i['data'].get('text','') and 'CSV' in i['data'].get('text','')]
                executions=[i for i in items if i['kind']=='EXECUTION' and i['status']=='WAITING_INPUT']
                inputs=api('GET',prefix+'/control')['inputs']
                if (len(questions)!=1 or len(executions)!=1 or len(inputs)!=1
                        or inputs[0]['id']!=report['turns'][-1]['inputId'] or inputs[0]['status']!='COMPLETED'
                        or questions[0]['data'].get('parentId')!=executions[0]['id']):
                    raise ValueError('The owned ninth clarification and idle queue must match exactly')
                report['turns'][-1]['structuredClarification']={'id':questions[0]['id'],'text':questions[0]['data']['text']}
                check('Ninth structured clarification reads the corrected CSV preference',True)
                execution=executions[0]
                api('POST',prefix+'/workbench/'+execution['id'],headers={'X-Agent-Action':'workbench'},
                    json={'requestId':str(uuid.uuid4()),'revision':execution['revision'],'action':'cancel','input':{}})
                check('Owned ninth clarification is cancelled without answering or replaying',True)
            for index,text in enumerate(statements):
                if args.resume_from and index<9:continue
                if index in (4,7):
                    restart()
                    if index==4:
                        format_memory=own_memory(lambda i:'PDF' in i['memory'].upper(),report['turns'][0]['sessionId'])
                        request=uuid.uuid4().hex;mutation_ids.append(request)
                        updated='用户明确纠正：'+marker+' 验收资料的默认导出格式为 CSV，不再使用 PDF。'
                        api('POST','/api/agent/memories/'+format_memory['id']+'/update',json={'requestId':request,'expectedDigest':format_memory['digest'],'memory':updated,'confirmed':True})
                        current=api('GET','/api/agent/memories/'+format_memory['id'])
                        check('Human correction preserves memory identity and source',current['memory']==updated and current['sourceSessionId']==format_memory['sourceSessionId'])
                sid=api('POST','/api/chat-assistant/sessions')['sessionId'];prefix='/api/agent/conversations/'+sid
                choice=api('GET',prefix+'/model-selection')
                api('POST',prefix+'/model-selection',headers={'X-Agent-Action':'workbench'},json={'requestId':uuid.uuid4().hex,'revision':choice['revision'],'modelId':selected})
                input_id=str(uuid.uuid4())
                turn={'number':index+1,'sessionId':sid,'inputId':input_id,'messageSha256':hashlib.sha256(text.encode()).hexdigest(),'status':'SUBMITTING'}
                report['turns'].append(turn);save()
                # Lost chat/unknown extraction results are never resubmitted.
                api('POST',prefix+'/inputs',headers={'X-Agent-Action':'conversation-control'},json={'id':input_id,'mode':'NEXT_TURN','content':text,'entryPoint':'CHAT'})
                deadline=time.monotonic()+180
                while time.monotonic()<deadline:
                    control=api('GET',prefix+'/control');value=next(i for i in control['inputs'] if i['id']==input_id)
                    if value['status']=='COMPLETED':break
                    if value['status'] in {'FAILED','CANCELLED','INTERRUPTED','NEEDS_REVIEW'}:raise AssertionError('Chat input did not complete; not resubmitted')
                    time.sleep(.5)
                else:raise AssertionError('Chat input outcome is unknown; not resubmitted')
                history=api('GET','/api/chat-assistant/sessions/'+sid)
                replies=[m for m in history['messages'] if m['role']=='assistant' and m.get('intent')!='GREETING']
                assert len(replies)==1
                reply=replies[0]
                if reply.get('messageType')=='AGENT_CARDS':reply=dict(reply,content=json.loads(reply['content'])['text'])
                turn['reply']=reply['content'];turn['messageId']=reply['id'];save()
                extraction_id=hashlib.sha256(('doorhandlecatch:user:'+str(uid)+'\0doorhandlecatch\0'+sid+'\0'+str(reply['id'])).encode()).hexdigest()
                turn['extractionId']=extraction_id;save()
                deadline=time.monotonic()+100;receipt=None
                while time.monotonic()<deadline:
                    audits=[a for a in api('GET','/api/agent/memories/audit') if a['action']=='AUTOSAVE' and a['requestId']==extraction_id]
                    if len(audits)>1:raise AssertionError('Duplicate extraction audit identity')
                    if audits:
                        receipt=api('POST','/api/agent/memories/operations/'+audits[0]['requestId']+'/verify',headers={'X-Agent-Action':'memory-verify'})
                        if receipt['status']=='SUCCEEDED':break
                        if receipt['status']!='RUNNING':raise AssertionError('Extraction needs review; not replayed')
                    time.sleep(1)
                else:raise AssertionError('Extraction did not finish; not replayed')
                turn['receipt']=receipt;turn['status']='SUCCEEDED';save()
                check('Session '+str(index+1)+' has a verified extraction receipt',True)
                def preference_text(matches):
                    if matches(reply['content']):return reply['content']
                    items=api('GET',prefix+'/workbench')['items']
                    questions=[i for i in items if i['kind']=='QUESTION' and i['status']=='PENDING'
                               and marker in i['data'].get('text','') and matches(i['data'].get('text',''))]
                    executions=[i for i in items if i['kind']=='EXECUTION' and i['status']=='WAITING_INPUT']
                    if len(questions)!=1 or len(executions)!=1 or questions[0]['data'].get('parentId')!=executions[0]['id']:
                        return reply['content']
                    controls=api('GET',prefix+'/control')['inputs']
                    if len(controls)!=1 or controls[0]['id']!=input_id or controls[0]['status']!='COMPLETED':
                        raise ValueError('Clarification cleanup requires the one completed owned input')
                    turn['structuredClarification']={'id':questions[0]['id'],'text':questions[0]['data']['text']};save()
                    execution=executions[0]
                    api('POST',prefix+'/workbench/'+execution['id'],headers={'X-Agent-Action':'workbench'},
                        json={'requestId':str(uuid.uuid4()),'revision':execution['revision'],'action':'cancel','input':{}})
                    return questions[0]['data']['text']
                if index==0:
                    format_memory=own_memory(lambda i:'PDF' in i['memory'].upper(),sid)
                    turn['createdMemoryId']=format_memory['id'];save()
                    check('The explicit format preference was actually extracted',True)
                if index==2:
                    own_memory(lambda i:'蓝' in i['memory'] or 'blue' in i['memory'].lower(),sid)
                    check('The explicit title preference was actually extracted',True)
                if index in (4,8):
                    text=preference_text(lambda value:'CSV' in value.upper())
                    check('Session '+str(index+1)+' reads corrected format across sessions','CSV' in text.upper())
                if index==7:
                    text=preference_text(lambda value:'蓝' in value or 'BLUE' in value.upper())
                    check('Title preference survives the second restart','蓝' in text or 'BLUE' in text.upper())
                if index==9:
                    text=preference_text(lambda value:'UTC+8' in value or '北京时间' in value or '东八区' in value)
                    check('Timezone preference survives the second restart','UTC+8' in text or '北京时间' in text or '东八区' in text)
            current=api('GET','/api/agent/memories/'+format_memory['id'])
            check('Corrected memory is in native account retrieval',current['id'] in native_ids(marker+' 默认导出格式'))
            env.api(foreign,'GET','/api/agent/memories/'+current['id'],expected=404)
            check('Other account cannot read the private memory',True)
            request=uuid.uuid4().hex;mutation_ids.append(request)
            body={'requestId':request,'expectedDigest':current['digest'],'expectedRevision':current['lifecycle']['revision'],'state':'EXCLUDED','expiresAt':None,'autoDelete':False,'confirmed':True}
            api('POST','/api/agent/memories/'+current['id']+'/lifecycle',json=body)
            check('Excluded memory is absent from native retrieval',current['id'] not in native_ids(marker+' 默认导出格式'))
            title=own_memory(lambda i:'蓝' in i['memory'] or 'blue' in i['memory'].lower(),report['turns'][2]['sessionId'])
            expiry=datetime.now(timezone(timedelta(hours=8)))+timedelta(seconds=20)
            request=uuid.uuid4().hex;mutation_ids.append(request)
            body={'requestId':request,'expectedDigest':title['digest'],'expectedRevision':title['lifecycle']['revision'],'state':'ACTIVE','expiresAt':expiry.isoformat(),'autoDelete':False,'confirmed':True}
            api('POST','/api/agent/memories/'+title['id']+'/lifecycle',json=body)
            while datetime.now(timezone(timedelta(hours=8)))<expiry+timedelta(seconds=2):time.sleep(1)
            check('Expired memory stays stored but leaves retrieval',api('GET','/api/agent/memories/'+title['id'])['id']==title['id'] and title['id'] not in native_ids(marker+' 标题颜色'))
            audits=api('GET','/api/agent/memories/audit')
            check('All human changes have successful MySQL audits',all(any(a['requestId']==request and a['outcome']=='SUCCEEDED' for a in audits) for request in mutation_ids))
            check('Ten sessions and two actual backend restarts completed',len(report['turns'])==10 and len(report['restarts'])==2)
            report['passed']=True
    except Exception as error:
        report['errorType']=type(error).__name__;save();raise
    finally:
        report['finishedAt']=timestamp();save()


if __name__=='__main__':main()
