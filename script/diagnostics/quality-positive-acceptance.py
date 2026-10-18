"""Explicit demo-only ECS quality verification: two new tasks, actual PTH, approval/export and rework/recheck."""
import argparse
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
from urllib.parse import urlsplit
import uuid
import requests
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');parser.add_argument('--directory',required=True);args=parser.parse_args()
out=Path(args.directory).resolve()
if not args.execute or out.exists() or not out.is_relative_to((ROOT/'work').resolve()):parser.error('Require --execute and a new project work directory')
password=os.environ['DOORHANDLE_DEMO_PASSWORD'];base='http://127.0.0.1:18088';out.mkdir(parents=True)
report={'at':datetime.now(timezone(timedelta(hours=8))).isoformat(),'scope':'demo workflow only, not physical repair or accuracy assessment','tasks':{},'checks':[],'javascriptErrors':[],'passed':False}
staff=requests.Session();boss=requests.Session()
for session in [staff,boss]:session.trust_env=False
def save():(out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
def check(name):report['checks'].append(name);save();print(name,flush=True)
def api(session,method,path,body=None):
    result=session.request(method,base+path,json=body,timeout=40)
    if not result.ok:raise RuntimeError('Demo API failed: '+method+' '+path+' status='+str(result.status_code))
    value=result.json()
    if value.get('code')!=200:raise RuntimeError('Demo API rejected: '+path+' code='+str(value.get('code')))
    return value.get('data')
for session,name,role in [(staff,'inspector.demo','INSPECTOR'),(boss,'supervisor.demo','SUPERVISOR')]:
    api(session,'POST','/api/auth/login',{'username':name,'password':password});identity=api(session,'GET','/api/auth/check');assert identity['username']==name and identity['role']==role
catalog=json.loads((ROOT/'work/testing/wacga-pth-100-20261015/results.json').read_text(encoding='utf8'))
normal=next(row for row in catalog if row['detections'] and all(d['label']=='Normal' for d in row['detections']))
defect=next(row for row in catalog if any(d['label']!='Normal' for d in row['detections']))
def ensure_demo(task):assert task in {v['taskId'] for v in report['tasks'].values()},'Only new demo tasks may be changed'
def mutate(task,operation,body=None):ensure_demo(task);return api(staff,'POST','/api/detection/tasks/'+task+'/'+operation,body)
def wait(task):
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        state=api(staff,'GET','/api/detection/tasks/'+task)
        if state['status'] in ['COMPLETED','FAILED','PARTIAL_FAILED']:break
        time.sleep(1)
    result=api(staff,'GET','/api/detection/tasks/'+task+'/result')
    assert result['status']=='COMPLETED' and result['successfulImages']==1 and result['failedImages']==0
    return result
def create(kind,sample):
    image=ROOT/'work/testing/cloud100-20261015-111121-8d75ad/report'/sample['original'];data=image.read_bytes()
    assert hashlib.sha256(data).hexdigest()==sample['imageSha256']
    filename='DEMO-'+kind+'-'+uuid.uuid4().hex[:10]+'.jpg'
    task=api(staff,'POST','/api/detection/tasks',{'taskType':'SINGLE','modelId':105,'threshold':.5,'files':[{'fileName':filename,'relativePath':filename,'contentType':'image/jpeg','fileSize':len(data)}],
        'captureInfo':{'captureDate':datetime.now(timezone(timedelta(hours=8))).date().isoformat(),'region':'演示验收-非生产','collector':'inspector.demo','deviceName':'CPU-PTH-105-DEMO','imageFolderName':filename[:-4]}})
    id=task['taskId'];report['tasks'][kind]={'taskId':id,'sourceSha256':sample['imageSha256']};save()
    upload=task['uploadUrls'][0];url=urlsplit(upload['putUrl']);response=staff.put(base+'/oss-upload'+url.path+'?'+url.query,data=data,headers={'Content-Type':'image/jpeg'},timeout=45);assert response.status_code==200
    mutate(id,'uploaded',{'modelId':105,'threshold':.5,'uploadedFiles':[{'fileName':filename,'objectKey':upload['objectKey']}]});result=wait(id)
    api(boss,'POST','/api/detection/tasks/'+id+'/assignment',{'qualityStation':'演示闭环验收站','assignee':'inspector.demo','assignmentRemark':'仅本次系统验收任务 不涉及真实产品或生产放行'})
    report['tasks'][kind]['initialDefectCount']=result.get('defectCount');save();check(kind+' real upload, CPU PTH and supervisor assignment completed')
    return id,result
def login(page,name):
    page.goto(base+'/#/login',wait_until='networkidle');page.get_by_placeholder('请输入用户名').fill(name);page.get_by_placeholder('请输入密码').fill(password);page.get_by_role('button',name='登录系统',exact=True).click();page.wait_for_url('**/#/home');page.wait_for_load_state('networkidle')
def workspace(page,task):
    page.goto(base+'/#/inspection/workbench',wait_until='networkidle');page.get_by_placeholder('搜索任务ID或文件夹名…').fill(task)
def reports(page,task):
    page.goto(base+'/#/quality/reports',wait_until='networkidle');page.get_by_placeholder('查询任务编号或报告标题').fill(task);page.get_by_role('button',name='查询',exact=True).click()
try:
    release,released=create('normal-release',normal);assert released.get('defectCount',0)==0
    rework,reworked=create('rework-recheck',defect)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            context=browser.new_context(viewport={'width':1500,'height':1050},accept_downloads=True,reduced_motion='reduce');page=context.new_page();page.on('pageerror',lambda e:report['javascriptErrors'].append(str(e)))
            login(page,'inspector.demo');workspace(page,release)
            page.get_by_role('button',name='确认复核',exact=True).click();dialog=page.get_by_role('dialog',name='人工复核',exact=True)
            dialog.locator('.el-form-item').filter(has_text='复核结论').locator('.el-select__wrapper').click();page.get_by_role('option',name='正常放行',exact=True).click()
            dialog.get_by_placeholder('记录缺陷位置、人工判断依据或误报原因').fill('系统演示验收：此样本模型未检出缺陷，仅验证流程，不作为实际产品的质量认证。')
            with page.expect_response(lambda r:r.url.endswith('/review') and r.request.method=='POST') as response:dialog.get_by_role('button',name='提交复核',exact=True).click()
            assert response.value.ok;expect(dialog).not_to_be_visible();check('employee completes normal sample review through the actual UI')
            page.get_by_role('button',name='质检处置',exact=True).click();dialog=page.get_by_role('dialog',name='质检处置',exact=True)
            dialog.locator('.el-select__wrapper').click();page.get_by_role('option',name='正常放行',exact=True).click();dialog.get_by_placeholder('记录处置依据、返工要求或隔离说明').fill('仅演示验收任务 正常处置流程 不关联真实生产产品')
            with page.expect_response(lambda r:r.url.endswith('/disposition') and r.request.method=='POST') as response:dialog.get_by_role('button',name='提交处置',exact=True).click()
            assert response.value.ok;expect(dialog).not_to_be_visible();assert api(staff,'GET','/api/detection/tasks/'+release)['flowStatus']=='RELEASED';check('normal demo task release persists through the actual UI')
            reports(page,release);page.get_by_role('button',name='新建报告草稿',exact=True).click();editor=page.get_by_role('dialog',name='新建报告草稿',exact=True)
            editor.get_by_placeholder('输入已完成检测任务编号').fill(release);editor.get_by_placeholder('报告标题',exact=True).fill('演示验收-审批通过与导出 '+release);editor.get_by_placeholder('记录复核说明、风险和建议，检测数量以系统依据为准').fill('本报告仅用于系统闭环演示，记录真实上传、CPU PTH、演示员工复核及处置。不是模型准确率报告或实际产品放行凭证。')
            with page.expect_response(lambda r:r.url.endswith('/api/detection/reports') and r.request.method=='POST') as created:editor.get_by_role('button',name='保存草稿',exact=True).click()
            assert created.value.ok;report['reportId']=created.value.json()['data']['reportId'];save()
            detail=page.get_by_role('dialog',name='报告详情',exact=True);detail.get_by_role('button',name='提交主管审批',exact=True).click();submit=page.get_by_role('dialog',name='提交主管审批',exact=True);submit.get_by_role('button',name='确认提交',exact=True).click();expect(submit).not_to_be_visible();check('employee explicitly submits the frozen demo report version')
            context2=browser.new_context(viewport={'width':1500,'height':1050},accept_downloads=True,reduced_motion='reduce');supervisor=context2.new_page();supervisor.on('pageerror',lambda e:report['javascriptErrors'].append(str(e)))
            login(supervisor,'supervisor.demo');reports(supervisor,release);row=supervisor.locator('.el-table__body tr').filter(has_text=release);expect(row).to_have_count(1);row.get_by_role('button',name='查看',exact=True).click()
            detail=supervisor.get_by_role('dialog',name='报告详情',exact=True);detail.get_by_role('button',name='审批通过',exact=True).click();approval=supervisor.get_by_role('dialog',name='报告审批通过',exact=True);approval.get_by_placeholder('填写本次审批依据与意见').fill('演示验收：核对本次成功处理、已复核和无待复检的任务快照，仅批准演示报告，不是实际产品认证。');approval.get_by_role('button',name='预览审批操作',exact=True).click();expect(approval.get_by_text('确认审批内容',exact=True)).to_be_visible();supervisor.screenshot(path=str(out/'approval-preview.png'),full_page=True)
            with supervisor.expect_response(lambda r:r.url.endswith('/decision') and r.request.method=='POST') as response:approval.get_by_role('button',name='确认审批通过',exact=True).click()
            assert response.value.ok;expect(approval).not_to_be_visible();expect(detail.get_by_role('button',name='导出已审批报告',exact=True)).to_be_visible();check('independent supervisor previews and explicitly approves eligible frozen report')
            with supervisor.expect_download() as download:detail.get_by_role('button',name='导出已审批报告',exact=True).click()
            download.value.save_as(out/'approved-demo-report.md');content=(out/'approved-demo-report.md').read_text(encoding='utf8');assert release in content and '演示' in content
            assert api(staff,'GET','/api/detection/reports/'+report['reportId'])['status']=='APPROVED';audit=api(boss,'GET','/api/detection/reports/'+report['reportId']+'/audit');assert {'CREATE','SUBMIT','APPROVE','EXPORT'}.issubset({a['action'] for a in audit});check('approved Markdown download, persisted status and all four audit actions verified')
            supervisor.screenshot(path=str(out/'approved-desktop.png'),full_page=True);supervisor.set_viewport_size({'width':390,'height':844});assert supervisor.evaluate('document.documentElement.scrollWidth<=innerWidth+1');supervisor.screenshot(path=str(out/'approved-mobile.png'),full_page=True)
        finally:browser.close()
    ensure_demo(rework);counts=max(1,int(reworked.get('defectCount') or 0))
    mutate(rework,'review',{'reviewConclusion':'CONFIRMED_DEFECT','severityLevel':'MAJOR','confirmedDefectCount':counts,'falsePositiveCount':0,'reviewRemark':'演示验收：依据模型缺陷候选登记模拟复核结论，不作为真实产品判断。'})
    state=mutate(rework,'disposition',{'dispositionAction':'REWORK','recheckRequired':False,'dispositionRemark':'演示模拟返工流程 不执行实体维修'});assert state['flowStatus']=='REWORK_REQUIRED';check('defect demo enters rework required through authorized business API')
    state=mutate(rework,'rework-result',{'reworkResult':'演示：模拟返工登记，未发生实际维修；用同一原图验证复检链路','reworkRemark':'仅验收接口、状态和推理通道，不宣称缺陷被修复','recheckRequired':True});assert state['flowStatus']=='RECHECK_REQUIRED';check('explicit demo rework record moves task to recheck required')
    before=api(staff,'GET','/api/detection/tasks/'+rework+'/trace');save()
    (out/'recheck-before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf8')
    state=mutate(rework,'retry');again=wait(rework);after=api(staff,'GET','/api/detection/tasks/'+rework+'/trace')
    (out/'recheck-after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2),encoding='utf8')
    assert again['successfulImages']==1
    originals=lambda trace:[(image['imageName'],image['objectKey']) for image in trace['originalImages']]
    assert originals(before)==originals(after) and after['reworkResult']==before['reworkResult']
    dispatched=lambda trace:next(event['occurredAt'] for event in trace['timeline'] if event['eventType']=='DISPATCHED')
    assert dispatched(before)!=dispatched(after)
    check('recheck reuses authorized original and completes a new actual CPU PTH run')
    mutate(rework,'review',{'reviewConclusion':'CONFIRMED_DEFECT','severityLevel':'MAJOR','confirmedDefectCount':counts,'falsePositiveCount':0,'reviewRemark':'演示复检：同一原图仍有模型缺陷候选，保留缺陷结论，暂挂处理。'})
    final=mutate(rework,'disposition',{'dispositionAction':'HOLD','recheckRequired':False,'dispositionRemark':'演示闭环：复检后保留缺陷并暂挂，不作正常放行'});assert final['flowStatus']=='HOLD';report['tasks']['rework-recheck']['finalFlowStatus']='HOLD';report['tasks']['normal-release']['finalFlowStatus']='RELEASED';check('rechecked defect demo ends on hold without pretending a physical repair succeeded')
    assert not report['javascriptErrors'];report['passed']=True;save();print(json.dumps({'passed':True,'checks':len(report['checks']),'tasks':{k:v['taskId'] for k,v in report['tasks'].items()},'reportId':report['reportId']},ensure_ascii=False))
except Exception:
    report['failure']=traceback.format_exc();save();raise
