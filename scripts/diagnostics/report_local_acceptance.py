"""Actual local MySQL/HTTP report lifecycle acceptance; only report-fixture-* tasks are mutated."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
import pymysql
import requests
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[2]
env = dotenv_values(root / '.env')
url = urlparse(env['DB_URL'].removeprefix('jdbc:'))
assert url.hostname in ('localhost','127.0.0.1') and url.path == '/doorhandledb' and url.port in (None,3306)
base='http://127.0.0.1:8080'; prefix='report-fixture-'+uuid4().hex[:8]
headers={'X-Report-Action':'update'}; checks=[]
def check(name,value=True):
    assert value,name
    checks.append({'name':name,'passed':True})
def key(): return str(uuid4())
def client(name):
    c=requests.Session();c.trust_env=False
    r=c.post(base+'/api/auth/login',json={'username':name,'password':'123456'},timeout=20)
    assert r.status_code==200 and r.json()['code']==200
    return c
def data(c,method,path,**kwargs):
    r=c.request(method,base+path,timeout=20,**kwargs)
    assert r.status_code==200 and r.json()['code']==200,(path,r.status_code,r.json().get('message'))
    return r.json()['data']
def post(c,path,body): return data(c,'POST',path,json=body,headers=headers)
staff=client('inspector.demo'); other=client('inspector.demo2'); boss=client('supervisor.demo'); boss2=client('supervisor.demo2')
connection=pymysql.connect(host=url.hostname,port=url.port or 3306,user=env['DB_USERNAME'],password=env['DB_PASSWORD'],database='doorhandledb',charset='utf8mb4',autocommit=True)
task_ids=[prefix+'-'+str(i) for i in range(5)]
with connection.cursor() as cursor:
    for task in task_ids:
        cursor.execute("INSERT INTO detection_task(task_id,status,flow_status,created_by,assignee,total_images,processed_images,successful_images,failed_images,defect_count,review_status,review_conclusion,reviewer,reviewed_at,recheck_required,finished_at,created_at,updated_at) VALUES(%s,'COMPLETED','REVIEWED','inspector.demo','inspector.demo',3,3,3,0,1,'REVIEWED','DEFECT','inspector.demo',NOW(),false,NOW(),NOW(),NOW())",(task,))
        cursor.execute('UPDATE detection_task SET confirmed_defect_count=1 WHERE task_id=%s',(task,))
    cursor.execute("UPDATE detection_task SET created_by='supervisor.demo' WHERE task_id=%s",(task_ids[4],))

def create(task):
    body={'taskId':task,'title':prefix+' 报告','narrative':'人工意见 <script>alert(1)</script>','requestId':key()}
    return post(staff,'/api/detection/reports',body),body
def submit(row): return post(staff,f"/api/detection/reports/{row['reportId']}/submit",{'expectedVersion':row['version'],'requestId':key()})
def preview(c,row,decision='APPROVE',reason='已核对任务及复核依据'):
    return post(c,f"/api/detection/reports/{row['reportId']}/decision-preview",{'expectedVersion':row['version'],'decision':decision,'reason':reason})
def decide(c,p):
    body={'expectedVersion':p['report']['version'],'decision':p['decision'],'reason':p['reason'],'confirmationToken':p['confirmationToken'],'requestId':key()}
    return post(c,f"/api/detection/reports/{p['report']['reportId']}/decision",body),body

draft,create_body=create(task_ids[0]); rid=draft['reportId']
check('private_draft_other_employee_404',other.get(base+f'/api/detection/reports/{rid}',timeout=20).status_code==404)
check('private_draft_other_supervisor_404',boss.get(base+f'/api/detection/reports/{rid}',timeout=20).status_code==404)
check('create_idempotent',post(staff,'/api/detection/reports',create_body)['reportId']==rid)
check('missing_marker_400',staff.post(base+f'/api/detection/reports/{rid}/submit',json={'expectedVersion':1,'requestId':key()},timeout=20).status_code==400)
pending=submit(draft)
check('employee_cannot_approve',staff.post(base+f'/api/detection/reports/{rid}/decision-preview',json={'expectedVersion':2,'decision':'APPROVE','reason':'越权'},headers=headers,timeout=20).status_code==403)
check('submitted_cannot_edit',staff.put(base+f'/api/detection/reports/{rid}',json={'expectedVersion':2,'title':'改动','narrative':'改动','requestId':key()},headers=headers,timeout=20).status_code==409)
check('supervisor_cannot_withdraw_owner_submission',boss.post(base+f'/api/detection/reports/{rid}/withdraw',json={'expectedVersion':2,'requestId':key()},headers=headers,timeout=20).status_code==403)
p=preview(boss,pending)
check('preview_has_fixed_source',p['report']['source']['totalImages']==3 and not any(k in p['report']['source'] for k in ('resultJsonOssKey','sourceOssPrefix','originalImageKeysJson')))
wrong={'expectedVersion':2,'decision':'APPROVE','reason':'不同意见','confirmationToken':p['confirmationToken'],'requestId':key()}
check('changed_reason_confirmation_denied',boss.post(base+f'/api/detection/reports/{rid}/decision',json=wrong,headers=headers,timeout=20).status_code==409)
correct={**wrong,'reason':p['reason'],'requestId':key()}
check('other_supervisor_token_denied',boss2.post(base+f'/api/detection/reports/{rid}/decision',json=correct,headers=headers,timeout=20).status_code==409)
approved,decision_body=decide(boss,p)
check('approval_state_and_version',approved['status']=='APPROVED' and approved['version']==3)
check('decision_replay_same_result',post(boss,f'/api/detection/reports/{rid}/decision',decision_body)==approved)
audits=data(staff,'GET',f'/api/detection/reports/{rid}/audit')
check('one_decision_audit',sum(a['action']=='APPROVE' for a in audits)==1)
export=staff.post(base+f'/api/detection/reports/{rid}/export',headers=headers,timeout=20)
check('approved_export_safe_and_audited',export.status_code==200 and export.headers['Content-Type'].startswith('text/markdown') and '<script>' not in export.text and '&lt;script&gt;' in export.text)
(root/'work/report-approved-sample.md').write_text(export.text,encoding='utf-8')
check('export_no_store','no-store' in export.headers.get('Cache-Control',''))
check('other_employee_export_denied',other.post(base+f'/api/detection/reports/{rid}/export',headers=headers,timeout=20).status_code==404)
with connection.cursor() as cursor:
    cursor.execute('SELECT flow_status FROM detection_task WHERE task_id=%s',(task_ids[0],));check('approval_does_not_release_task',cursor.fetchone()[0]=='REVIEWED')
    cursor.execute("SELECT COUNT(*) FROM detection_report_outbox WHERE report_id=%s AND delivery_status='PENDING'",(rid,));check('outbox_persisted',cursor.fetchone()[0]==2)

rejected_draft,_=create(task_ids[1]);rejected_pending=submit(rejected_draft)
rejected,_=decide(boss,preview(boss,rejected_pending,'REJECT','请补充材料'))
check('rejection_preserves_snapshot',rejected['status']=='REJECTED' and rejected['narrative']==rejected_pending['narrative'])
revised=post(staff,f"/api/detection/reports/{rejected['reportId']}/revise",{'expectedVersion':rejected['version'],'requestId':key()})
check('revision_links_immutable_previous',revised['status']=='DRAFT' and revised['previousReportId']==rejected['reportId'])
withdrawn_pending=submit(revised)
withdrawn=post(staff,f"/api/detection/reports/{revised['reportId']}/withdraw",{'expectedVersion':withdrawn_pending['version'],'requestId':key()})
check('owner_withdraw',withdrawn['status']=='WITHDRAWN')

concurrent_draft,_=create(task_ids[2]); concurrent=submit(concurrent_draft)
pa=preview(boss,concurrent);pb=preview(boss2,concurrent)
def compete(item):
    c,p=item
    r=c.post(base+f"/api/detection/reports/{concurrent['reportId']}/decision",json={'expectedVersion':2,'decision':'APPROVE','reason':p['reason'],'confirmationToken':p['confirmationToken'],'requestId':key()},headers=headers,timeout=20)
    return r.status_code
with ThreadPoolExecutor(max_workers=2) as workers: statuses=list(workers.map(compete,[(boss,pa),(boss2,pb)]))
check('mysql_two_supervisors_one_winner',sorted(statuses)==[200,409])

changed_draft,_=create(task_ids[3]);changed=submit(changed_draft);cp=preview(boss,changed)
with connection.cursor() as cursor:cursor.execute('UPDATE detection_task SET defect_count=8 WHERE task_id=%s',(task_ids[3],))
stale={'expectedVersion':2,'decision':'APPROVE','reason':cp['reason'],'confirmationToken':cp['confirmationToken'],'requestId':key()}
check('source_change_blocks_decision',boss.post(base+f"/api/detection/reports/{changed['reportId']}/decision",json=stale,headers=headers,timeout=20).status_code==409)
ep=preview(boss,changed,'REJECT','任务依据变化，请修订')
with connection.cursor() as cursor:cursor.execute('UPDATE detection_report_confirmation SET expires_at=DATE_SUB(NOW(),INTERVAL 1 MINUTE) WHERE token=%s',(ep['confirmationToken'],))
check('expired_confirmation_denied',boss.post(base+f"/api/detection/reports/{changed['reportId']}/decision",json={'expectedVersion':2,'decision':'REJECT','reason':ep['reason'],'confirmationToken':ep['confirmationToken'],'requestId':key()},headers=headers,timeout=20).status_code==409)

assigned_draft,_=create(task_ids[4])
data(boss,'POST',f'/api/detection/tasks/{task_ids[4]}/assignment',json={'qualityStation':'fixture-station','assignee':'inspector.demo2'})
check('reassignment_revokes_report_owner_access',staff.get(base+f"/api/detection/reports/{assigned_draft['reportId']}",timeout=20).status_code==404)
check('new_assignee_cannot_read_others_private_draft',other.get(base+f"/api/detection/reports/{assigned_draft['reportId']}",timeout=20).status_code==404)
for c in (staff,other):
    rows=data(c,'GET','/api/detection/reports',params={'keyword':task_ids[4]})
    check('filtered_list_and_count_private_'+('owner' if c is staff else 'assignee'),rows['total']==0 and rows['records']==[])

# 为浏览器另保留一个已完整复核任务及待审批报告。
ui_draft,_=create(task_ids[0]);ui_pending=submit(ui_draft)
artifact={'prefix':prefix,'taskIds':task_ids,'approvedReportId':rid,'browserPendingReportId':ui_pending['reportId'],'checks':checks,'fixtureDataRetained':True}
(root/'work/report-local-acceptance.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2),encoding='utf-8')
connection.close()
print(json.dumps({'checks':len(checks),'allPassed':True,'artifact':'work/report-local-acceptance.json'}))
