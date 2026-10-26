"""Deterministic, fictional UI data. Never import these records into a business DB.

Standard library only. Local preview and screenshot helpers may call response().
All write commands are rejected; card resolution is a read-only POST.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from uuid import UUID
import json

BASE = datetime(2026, 10, 25, 9, 0, tzinfo=timezone(timedelta(hours=8)))
def at(minutes=0):
    return (BASE + timedelta(minutes=minutes)).isoformat()

def uid(number):
    return str(UUID(int=number + 0xDE001000000040008000000000000000))

def wrapped(data):
    return 200, {'code': 200, 'message': '只读演示数据，非实际业务或模型回执', 'data': data}

DEPARTMENTS = [{'id': 1, 'name': '演示·采集组'}, {'id': 2, 'name': '演示·质量组'}]
EMPLOYEES = [dict(id=i, name='演示·'+name, departmentId=1 if i < 4 else 2,
                  department=DEPARTMENTS[0 if i < 4 else 1], departmentName=DEPARTMENTS[0 if i < 4 else 1]['name'],
                  position=position, status=status, phone='00000000000',
                  email=f'preview-{i}@example.invalid', hireDate='2026-09-01', version=0)
             for i, name, position, status in [
                 (1,'采集员甲','COLLECTION','ACTIVE'),(2,'采集员乙','COLLECTION','ACTIVE'),
                 (3,'巡检员','COLLECTION','VACATION'),(4,'质检员甲','DETECTION','ACTIVE'),
                 (5,'质检员乙','DETECTION','ACTIVE'),(6,'维修员','MAINTENANCE','ACTIVE')]]
DEVICES = [dict(id=i, deviceCode=f'DEMO-{i:03}', deviceType='IMAGE_CAPTURE' if i <= 4 else 'DETECTION',
                modelName='演示·'+name, serialNumber=f'PREVIEW-20261025-{i:03}', status=status,
                onlineStatus='OFFLINE' if status=='OFFLINE' else 'ONLINE', plcStatus='CONNECTED',
                cameraStatus='CONNECTED', captureStatus='IDLE', purchaseDate='2026-09-01',
                employee=EMPLOYEES[(i-1)%6], employeeId=(i-1)%6+1, version=0)
           for i,name,status in [(1,'东区采集相机','IN_USE'),(2,'西区采集相机','IN_USE'),
                                 (3,'返工采集相机','MAINTENANCE'),(4,'备用采集相机','IDLE'),
                                 (5,'CPU 检测工作站甲','IN_USE'),(6,'CPU 检测工作站乙','OFFLINE')]]
MODELS = []
for i,name,status,ap,train,images,empty,fps in [
        (1,'六类检测基线','PUBLISHED',0.625,3200,98,3,12.3456),
        (2,'复杂背景候选','READY',0.6412,3600,120,2,10.125),
        (3,'小样本对照','DISABLED',0.58,1800,80,8,16.5),
        (4,'待登记新版本','DRAFT',None,None,None,None,None)]:
    MODELS.append(dict(modelId=i,modelName='【演示】'+name,version=f'preview-{i}.0',status=status,
                       isDefault=i==1,validationStatus='PENDING' if i==4 else 'PASSED',
                       mlopsStatus='UNASSESSED' if i==4 else 'EVALUATED',mapScore=ap,
                       trainingImageCount=train,trainingCompletedAt=None if i==4 else '2026-10-20T18:30:00',
                       evaluationImageCount=images,noDetectionImageCount=empty,inferenceFps=fps,
                       evaluationDataset=None if i==4 else 'PREVIEW-test（虚构评估资料）',
                       compatibilityNote='演示数值，非实测：CPU / 640x640 / batch=1 / 仅推理计时',
                       uploadTime=at(-1440),publishedAt=at(-720) if i==1 else None,
                       usageCount=0,deploymentStrategy='FULL',canaryPercent=100,
                       creator='demo.preview',updateDescription='只读演示模型记录，不指向真实权重文件'))

SCENARIOS = [
    ('正常放行','COMPLETED','RELEASED','REVIEWED','NORMAL',40,0,0),
    ('缺陷待复核','COMPLETED','PENDING_REVIEW','PENDING',None,36,0,2),
    ('缺陷待返工','COMPLETED','REWORK_REQUIRED','REVIEWED','DEFECT',30,0,1),
    ('返工后待复检','COMPLETED','RECHECK_REQUIRED','REVIEWED','DEFECT',24,0,0),
    ('缺陷暂挂','COMPLETED','HOLD','REVIEWED','DEFECT',20,0,1),
    ('部分图片失败','PARTIAL_FAILED','HOLD','PENDING',None,38,2,3),
    ('图片读取异常','FAILED','FAILED','PENDING',None,0,12,0),
    ('已上传待检测','QUEUED','PENDING_DETECTION','PENDING',None,0,0,0),
    ('正在检测','DETECTING','DETECTING','PENDING',None,0,0,0),
    ('正常归档','COMPLETED','ARCHIVED','REVIEWED','NORMAL',48,0,0),
    ('已确认缺陷','COMPLETED','CONFIRMED','REVIEWED','DEFECT',28,0,2),
    ('人工复核中','COMPLETED','REVIEWING','REVIEWING',None,32,0,0)]
TASKS = []
for n,(title,status,flow,review,conclusion,success,failed,empty) in enumerate(SCENARIOS,1):
    done=status in ('COMPLETED','PARTIAL_FAILED','FAILED')
    defect=0 if conclusion=='NORMAL' or not success else min(success-empty, 3+n%5)
    classes=dict(Normal=max(0,success-empty-defect),Bent=0,Deformed=0,Rusty=0,Missing=0,Compromised=0)
    classes[['Bent','Deformed','Rusty','Missing','Compromised'][(n-1)%5]]=defect
    total=success+failed if done else 25
    task=dict(taskId=f'DEMO-20261025-{n:03}',folderName='【演示】'+title,imageFolderName='【演示】'+title,
              modelId=1,modelVersion='preview-1.0',threshold=0.5,status=status,flowStatus=flow,
              reviewStatus=review,reviewConclusion=conclusion,totalImages=total,successfulImages=success,
              failedImages=failed,createdAt=at(n*3),finishedAt=at(n*3+2) if done else None,
              detectionFinishedAt=at(n*3+2) if done else None,
              batchNo=f'DEMO-BATCH-{(n-1)//4+1:02}',workOrderNo=f'DEMO-WO-{(n-1)//3+1:02}',
              creatorUserId=9001 if n%2 else 9002,assigneeUserId=9001 if n%2 else 9002,
              assignee='demo.preview' if n%2 else 'demo.preview2',assignmentRevision=1,
              reviewer='demo.reviewer' if review=='REVIEWED' else None,
              reviewedAt=at(n*3+3) if review=='REVIEWED' else None,
              confirmedDefectCount=defect if review=='REVIEWED' else None,
              falsePositiveCount=0 if review=='REVIEWED' else None,
              severityLevel='MAJOR' if defect else 'MINOR',dueAt=at(420),
              disposition='RELEASE' if flow in ('RELEASED','ARCHIVED') else 'REWORK' if 'REWORK' in flow else 'HOLD',
              captureDate='2026-10-25',region=['东区','西区','返工区'][(n-1)%3],
              collector=EMPLOYEES[(n-1)%3]['name'],deviceName=DEVICES[(n-1)%2]['modelName'],
              errorMessage='【演示】图片读取失败，未重新执行' if failed else None,
              originalImages=[],previewImages=[],defectEvidence=[],timeline=[],
              statistics={'classCounts':classes,'noDetectionImages':empty,'successfulImages':success,'failedImages':failed,'totalImages':total} if done else {})
    task['captureInfo']={k:task[k] for k in ('captureDate','region','collector','deviceName','imageFolderName')}
    if success:
        for j in range(min(3,success)):
            source=f'/api/demo/images/{n}-{j}-source.svg'
            annotated=f'/api/demo/images/{n}-{j}-annotated.svg'
            image=dict(imageName=f'示意图-{n:03}-{j+1}.svg',originalUrl=source,previewUrl=annotated,annotatedUrl=annotated)
            task['originalImages'].append(dict(imageName=image['imageName'],previewUrl=source))
            task['previewImages'].append(image)
    task['timeline']=[dict(type='TASK_CREATED',title='【演示】任务创建',description='虚构场景，非业务审计回执',timestamp=task['createdAt'])]
    if done: task['timeline'].append(dict(type='DETECTION_FINISHED',title='【演示】检测结果场景',description='未执行真实推理',timestamp=task['finishedAt']))
    if review=='REVIEWED': task['timeline'].append(dict(type='REVIEWED',title='【演示】人工复核场景',description='非真实人员审批',timestamp=task['reviewedAt']))
    task['processedImages']=success+failed
    task['defectCount']=defect
    for event in task['timeline']:
        event.update(eventType=event['type'],eventName=event['title'],occurredAt=event['timestamp'],operator='demo.preview')
    TASKS.append(task)

REPORTS = [dict(reportId='qr-'+uid(400+i),taskId=TASKS[i]['taskId'],title='【演示】'+title,
                status=status,version=1+i,ownerUsername='demo.preview',ownerUserId=9001,
                createdAt=at(50+i),updatedAt=at(60+i),narrative='只读演示意见，不是实际审批或质检结论。',
                taskSnapshot=TASKS[i])
           for i,(title,status) in enumerate([('正常批次放行报告','APPROVED'),('缺陷复核报告','SUBMITTED'),('返工处置草稿','DRAFT'),('复检资料补充','REJECTED')])]
for report in REPORTS:
    report['source']=report['taskSnapshot']

SESSION_TOPICS = ['批次质检总览','缺陷与返工分析','模型训练指标对照','设备异常排查','报告依据整理','文件与专业任务']
SESSIONS = []
for i,topic in enumerate(SESSION_TOPICS):
    sid=uid(100+i)
    messages=[]
    for turn in range(1,5):
        messages.extend([dict(id=i*100+turn*2-1,role='user',messageType='TEXT',createdAt=at(70+i+turn),
                              content=f'【演示】{topic}，请整理第 {turn} 项需要核对的事项。'),
                         dict(id=i*100+turn*2,role='assistant',messageType='TEXT',createdAt=at(70+i+turn),
                              content=f'### {topic}\n\n这是预置的演示对话，**没有调用模型或执行工具**。\n\n- 依据任务：`{TASKS[i]["taskId"]}`\n- 批次：`{TASKS[i]["batchNo"]}`\n- 本轮重点：'+['核对检测与人工复核分别记录','未检出图片数除以成功检测图片数','普通回答不能替代业务授权','报告审批与任务放行分别核对'][turn-1]+'\n\n需要操作时应回到真实环境重新鉴权与确认。')])
    SESSIONS.append(dict(sessionId=sid,title='【演示】'+topic,status='ACTIVE',pinned=i==0,
                         createdAt=at(60+i),updatedAt=at(90-i),messages=messages))

SESSIONS[0]['messages'][-1].update(messageType='AGENT_CARDS',content=json.dumps({
    'version':1,'text':'【演示】以下为预置业务卡片，只读展示，没有运行 Agent 或执行审批。',
    'cards':[{'type':'TASKS','tool':'search_detection_tasks','ids':[t['taskId'] for t in TASKS[:2]]},
             {'type':'REPORTS','tool':'list_quality_reports','ids':[r['reportId'] for r in REPORTS[:2]]}]},ensure_ascii=False))
SESSIONS[2]['messages'][-1].update(messageType='AGENT_CARDS',content=json.dumps({
    'version':1,'text':'【演示】训练数量、日期、mAP、未检出率和 FPS 均为虚构登记资料，非实测成绩。',
    'cards':[{'type':'MODEL_OPERATIONS','tool':'get_model_operations','ids':['1','2','3','4']}]},ensure_ascii=False))

WORKBENCH = [
    dict(id=uid(201),kind='PLAN',status='PENDING',revision=1,updatedAt=at(91),data={'title':'【演示】批次质量核对计划','text':'## 核对范围\n\n1. 查看 DEMO-BATCH-01 四项任务\n2. 对照原图与标注示意\n3. 列出需复核、返工和复检的项目\n\n本计划只是预置样例，未授权任何实际业务操作。'}),
    dict(id=uid(202),kind='TASKS',status='ACTIVE',revision=1,updatedAt=at(91),data={'title':'【演示】待办清单','tasks':[{'id':'scope','title':'核对批次范围','status':'DONE','evidence':'演示任务清单'},{'id':'quality','title':'核对返工与复检','status':'IN_PROGRESS'},{'id':'report','title':'整理报告依据','status':'TODO'}]}),
    dict(id=uid(203),kind='QUESTION',status='PENDING',revision=1,updatedAt=at(91),data={'title':'【演示】补充分析范围','text':'这次需要按哪个批次整理？','questionType':'SINGLE','options':['DEMO-BATCH-01','DEMO-BATCH-02','DEMO-BATCH-03']}),
    dict(id=uid(204),kind='QUESTION',status='ANSWERED',revision=2,updatedAt=at(90),data={'title':'【演示】已回答的分析维度','text':'按任务状态还是缺陷类别？','questionType':'TEXT','answer':'先按任务状态，缺陷类别单独列出'}),
    dict(id=uid(205),kind='CHILD',status='COMPLETED',revision=2,updatedAt=at(90),data={'title':'【演示】质检专业子任务','specialist':'detection-quality','text':'核对返工与复检的差别','result':'预置结果：返工完成后仍需按要求重新检测；没有执行真实专业 Agent。'}),
    dict(id=uid(206),kind='EXECUTION',status='COMPLETED',revision=2,updatedAt=at(90),data={'title':'【演示】整理 CSV 产物','text':'文件场景预置','result':'演示 CSV 已随数据包预置，未运行生成工具。'}),
    dict(id=uid(207),kind='EXECUTION',status='NEEDS_REVIEW',revision=2,updatedAt=at(91),data={'title':'【演示】中断待核对','text':'模拟未知写结果；不得自动重放。本样例不对应真实执行，也没有可恢复 SDK 状态。'}),
    dict(id=uid(208),kind='USAGE',status='COMPLETED',revision=1,updatedAt=at(91),data={'title':'【演示】用量未知','attempts':[],'reportedInputTokens':None,'reportedOutputTokens':None})]
FILE_TEXT = {'batch-summary.md':'# 演示批次摘要\n\n预置演示资料，不是真实模型输出。\n',
             'task-summary.csv':'taskId,batchNo,status\n'+''.join(f'{t["taskId"]},{t["batchNo"]},{t["status"]}\n' for t in TASKS),
             'model-metrics.json':json.dumps(MODELS,ensure_ascii=False,indent=2)}
FILES = [dict(id=uid(300+i),name=name,contentType=ctype,bytes=len(FILE_TEXT[name].encode('utf-8')),folder='artifacts')
         for i,(name,ctype) in enumerate([('batch-summary.md','text/markdown'),('task-summary.csv','text/csv'),('model-metrics.json','application/json')])]

def page(rows, query):
    keyword=query.get('keyword',[''])[0].casefold()
    status=query.get('status',[''])[0]
    rows=[r for r in rows if (not keyword or keyword in json.dumps(r,ensure_ascii=False).casefold()) and (not status or r.get('status')==status)]
    for key in ('modelId','modelName','version','deviceCode','deviceType','name','departmentId','position','collector','deviceName','region'):
        value=query.get(key,[''])[0]
        if value:
            rows=[r for r in rows if str(r.get(key,''))==value] if key in ('modelId','departmentId','deviceType','position') else [r for r in rows if value.casefold() in str(r.get(key,'')).casefold()]
    try: size=max(1,min(200,int(query.get('size',['20'])[0]))); number=max(1,int(query.get('page',['1'])[0]))
    except ValueError: size,number=20,1
    return {'records':rows[(number-1)*size:number*size],'total':len(rows),'current':number,'size':size}

def image_svg(annotated=False):
    box='<rect x="145" y="95" width="355" height="275" rx="8" fill="none" stroke="#2563eb" stroke-width="4"/><text x="148" y="80" fill="#2563eb" font-size="18">DEMO target overlay</text>' if annotated else ''
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480"><rect width="640" height="480" fill="#f1f5f9"/><rect x="65" y="30" width="510" height="420" rx="12" fill="#dbe4ec" stroke="#94a3b8"/><path d="M100 55v370m440-370v370" stroke="#a3b3c3" stroke-width="14"/><rect x="240" y="105" width="30" height="250" rx="10" fill="#64748b"/><path d="M255 220h190v45H255" fill="#94a3b8" stroke="#475569" stroke-width="8"/>{box}<text x="32" y="467" font-family="sans-serif" fill="#475569" font-size="16">FICTIONAL PREVIEW - no detection or approval executed</text></svg>'

def response(path, method='GET', role='SUPERVISOR', url='', body=None):
    query=parse_qs(urlparse(url or path).query)
    if method=='POST' and path=='/api/agent/cards/resolve':
        cards=[]
        for ref in (body or {}).get('cards',[]):
            typ,ids=ref.get('type'),ref.get('ids',[])
            candidates=[]
            if typ=='TASKS': candidates=TASKS
            elif typ=='REPORTS': candidates=REPORTS
            elif typ=='MODELS': candidates=[dict(modelId=m['modelId'],name=m['modelName'],version=m['version'],status=m['status'],defaultModel=m['isDefault']) for m in MODELS]
            elif typ=='MODEL_OPERATIONS':
                candidates=[dict(model={'modelId':m['modelId'],'name':m['modelName'],'version':m['version'],'status':m['status']},evaluation={**{k:m[k] for k in ('mapScore','trainingImageCount','trainingCompletedAt','evaluationImageCount','noDetectionImageCount','inferenceFps')},'dataset':m['evaluationDataset']},rollout={},usage={},invalidFields=[]) for m in MODELS]
            def ident(r):
                if typ=='REPORTS': return r['reportId']
                if typ=='TASKS': return r['taskId']
                return str(r.get('modelId',r.get('model',{}).get('modelId')))
            cards.append(dict(type=typ,tool=ref.get('tool'),status='OK',scope='SINGLE_ENTERPRISE',metrics={},updatedAt=at(91),items=[r for r in candidates if ident(r) in ids]))
        return 200,{'cards':cards}
    if method not in ('GET','HEAD','OPTIONS'):
        return 403,{'code':403,'message':'只读演示数据：不能发送消息、运行工具、保存业务或提交审批'}
    if path.startswith('/api/demo/images/'):
        return 200,image_svg('annotated' in path)
    if path=='/api/auth/check' or path=='/api/organization/me':
        identity=dict(userId=9001,username='demo.preview',role=role,employeeId=4,employeeName='演示·质检员甲',departmentId=2,departmentName='演示·质量组',bindingRevision=1)
        return wrapped({**identity,'identity':identity})
    if path=='/api/organization/departments': return wrapped(DEPARTMENTS)
    if path=='/api/organization/accounts': return wrapped({'records':[],'total':0})
    if path=='/api/chat-projects': return wrapped([])
    if path=='/api/chat-assistant/sessions': return wrapped(SESSIONS)
    if path.startswith('/api/chat-assistant/sessions/'):
        sid=path.split('/')[4]; session=next((s for s in SESSIONS if s['sessionId']==sid),None)
        if not session: return 404,{'code':404,'message':'演示会话不存在'}
        return wrapped(session['messages'] if path.endswith('/messages') else session)
    if path.startswith('/api/agent/conversations/'):
        sid=path.split('/')[4]
        if path.endswith('/control'): return 200,{'run':{'sessionId':sid,'runId':None,'phase':'IDLE','revision':0,'local':False,'text':''},'inputs':[]}
        if path.endswith('/workbench'): return 200,{'items':WORKBENCH,'files':FILES,'businessFiles':[],'limits':{'maxFileBytes':26214400,'quotaBytes':524288000,'previewBytes':64000}}
        if path.endswith('/model-selection'): return 200,{'modelId':'','revision':0}
        if path.endswith('/actions') or path.endswith('/detection-creations'): return 200,[]
        if '/files/' in path and path.endswith('/content'):
            file=next((f for f in FILES if f['id']==path.split('/')[-2]),None)
            if file: return 200,FILE_TEXT[file['name']]
    if path=='/api/agent/conversations/capabilities': return 200,{'enabled':True}
    if path=='/api/agent/workbench/capabilities': return 200,{'enabled':True,**{k:True for k in ('plans','questions','files','children','jobs','usage','recovery','forks','context')}}
    if path=='/api/chat-assistant/agent-health': return wrapped({'enabled':True,'framework':'只读预览（未运行 Agent）','defaultModel':'preview-only','mode':'READ_ONLY'})
    if path=='/agui/models': return 200,{'configVersion':1,'selectedModel':'preview-only','fallbackEnabled':False,'fallbackModels':[],'models':[{'id':'preview-only','model':'只读演示，不连接模型','provider':'preview','configured':False,'healthState':'UNKNOWN'}]}
    if path=='/agui/catalog': return 200,{'role':role,'mainAgent':'只读演示助手','mode':'READ_ONLY','agents':[{'id':'detection-quality','name':'演示·检测质检专业'},{'id':'resource-management','name':'演示·产线资源专业'}],'reportsEnabled':True,'reportDraftsEnabled':False}
    if path in ('/api/agent/actions','/api/agent/runs'): return 200,[]
    if path=='/api/model-info': return wrapped(page(MODELS,query))
    if path=='/api/models': return wrapped(MODELS)
    if path.startswith('/api/model-info/'):
        if path.endswith('/logs'): return wrapped([])
        return wrapped(next((m for m in MODELS if str(m['modelId'])==path.split('/')[3]),None))
    if path=='/api/devices': return wrapped(page(DEVICES,query))
    if path=='/api/employees': return wrapped(page(EMPLOYEES,query))
    if path=='/api/devices/stats': return wrapped(dict(total=6,inUse=3,offline=1,maintenance=1,idle=1,imageCapture=4,imageCaptureInUse=2,detection=2,detectionInUse=1))
    if path=='/api/employees/stats': return wrapped(dict(total=6,active=5,vacation=1,resigned=0,detection=2,collection=3,maintenance=1))
    if path.startswith('/api/devices/') or path.startswith('/api/employees/'):
        rows=DEVICES if '/devices/' in path else EMPLOYEES
        return wrapped(next((r for r in rows if str(r['id'])==path.split('/')[3]),None))
    if path=='/api/detection/tasks': return wrapped(page(TASKS,query))
    if path=='/api/detection/tasks/quality-queue':
        rows=[t for t in TASKS if t['flowStatus'] not in ('RELEASED','ARCHIVED')]
        queue=query.get('queue',[''])[0]
        flows={'PENDING_REVIEW':'PENDING_REVIEW','PENDING_DISPOSITION':'CONFIRMED','REWORK_REQUIRED':'REWORK_REQUIRED','RECHECK_REQUIRED':'RECHECK_REQUIRED','HOLD':'HOLD','FAILED':'FAILED'}
        if queue in flows: rows=[t for t in rows if t['flowStatus']==flows[queue]]
        return wrapped(page(rows,query))
    if path.startswith('/api/detection/tasks/'):
        tid=path.split('/')[4]; task=next((t for t in TASKS if t['taskId']==tid),None)
        if task: return wrapped(task)
    if path=='/api/detection/reports': return wrapped(page(REPORTS,query))
    if path.startswith('/api/detection/reports/'):
        if path.endswith('/audit') or path.endswith('/events'): return wrapped([])
        return wrapped(next((r for r in REPORTS if r['reportId']==path.split('/')[4]),None))
    if path=='/api/device-usage-records': return wrapped({'records':[],'total':0})
    if path=='/api/dashboard/stats': return wrapped({'detectionCount':sum(t['status'] in ('COMPLETED','PARTIAL_FAILED','FAILED') for t in TASKS),'avgMissRate':None})
    if path=='/api/dashboard/model-stats': return wrapped([{'modelId':m['modelId'],'modelName':m['modelName'],'avgMissRate':None} for m in MODELS])
    if path=='/api/dashboard/quality-workload':
        flows=Counter(t['flowStatus'] for t in TASKS)
        return wrapped({key:flows[flow] for key,flow in [('pendingReviewCount','PENDING_REVIEW'),('pendingDispositionCount','CONFIRMED'),('reworkRequiredCount','REWORK_REQUIRED'),('recheckRequiredCount','RECHECK_REQUIRED'),('holdCount','HOLD'),('failedCount','FAILED')]})
    if path=='/api/dashboard/region-stats':
        return wrapped([{'region':region,'imageCount':sum(t['totalImages'] for t in TASKS if t['region']==region),'taskCount':sum(t['region']==region for t in TASKS)} for region in ('东区','西区','返工区')])
    if path in ('/api/dashboard/work-unit-summary','/api/dashboard/duplicate-summary'): return wrapped({'counts':{}})
    if path=='/api/statistics/detection-distribution': return wrapped([{'result':key,'count':sum(t['statistics'].get('classCounts',{}).get(key,0) for t in TASKS)} for key in ('Normal','Bent','Deformed','Rusty','Missing','Compromised')])
    if path=='/api/statistics/detection-trend':
        rows=[]
        for n in range(3):
            group=TASKS[n*4:n*4+4]
            rows.append({'date':f'2026-10-25 演示组 {n+1}','total':sum(t['totalImages'] for t in group),**{k.lower():sum(t['statistics'].get('classCounts',{}).get(k,0) for t in group) for k in ('Normal','Bent','Deformed','Rusty','Missing','Compromised')}})
        return wrapped(rows)
    return None

def export():
    return {'kind':'fictional-read-only-preview','timezone':'UTC+8','createdAt':at(),
            'counts':{'tasks':len(TASKS),'reports':len(REPORTS),'models':len(MODELS),'employees':len(EMPLOYEES),'devices':len(DEVICES),'sessions':len(SESSIONS),'messages':sum(len(s['messages']) for s in SESSIONS),'workbenchItems':len(WORKBENCH),'files':len(FILES)},
            'tasks':TASKS,'reports':REPORTS,'models':MODELS,'employees':EMPLOYEES,'devices':DEVICES,'sessions':SESSIONS,'workbench':WORKBENCH,'files':FILES,'fileContents':FILE_TEXT}
