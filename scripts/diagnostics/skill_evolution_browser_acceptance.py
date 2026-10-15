"""Actual local MySQL skill review workflow; no paid model requests."""
import json
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright,expect

root=Path(__file__).resolve().parents[2]
fixture=json.loads((root/'work/skill-evolution-local-mysql.json').read_text(encoding='utf-8'))
checks=[]; errors=[]; generations=[]
def check(name,value=True):
    assert value,name
    checks.append({'name':name,'passed':True})
def login_api(name):
    client=requests.Session();client.trust_env=False
    response=client.post('http://127.0.0.1:8080/api/auth/login',json={'username':name,'password':'123456'},timeout=15)
    assert response.status_code==200 and response.json()['code']==200
    return client
owner=login_api('inspector.demo'); other=login_api('inspector.demo2'); boss=login_api('supervisor.demo')
url='http://127.0.0.1:8080/api/agent/skills/'+fixture['skillId']
view=owner.get(url,timeout=15).json()
check('actual_skill_source_and_three_immutable_versions',len(view['versions'])==3 and view['versions'][0]['status']=='SUBMITTED')
response=other.get(url,timeout=15)
# Approved versions are shared by role, but private source and unapproved third version remain hidden.
other_view=response.json()
check('other_employee_only_sees_approved_versions',all(v['status']=='APPROVED' and v.get('sourceRunId') is None for v in other_view['versions']))
response=other.post('http://127.0.0.1:8080/api/agent/skills/sources/'+fixture['sourceRunId']+'/consent',headers={'X-Skill-Action':'update'},timeout=15)
check('other_employee_cannot_capture_private_run',response.status_code in (403,404))
response=owner.post(url+'/decision',headers={'X-Skill-Action':'update'},json={'expectedRevision':view['revision'],'decision':'APPROVE','reason':'attempt','businessReviewed':True,'privacyReviewed':True},timeout=15)
check('employee_cannot_publish_own_skill',response.status_code==403)
response=boss.get(url,timeout=15)
check('boss_review_has_no_private_run_links',response.headers.get('Cache-Control')=='no-store' and all(v.get('sourceRunId') is None for v in response.json()['versions']))
check('eval_explicitly_structural_not_semantic',all(not e['result']['semanticQualityEvaluated'] and e['result']['suiteVersion']=='skill-structural-policy-v1' for e in view['evaluations']))
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    def login(page,name):
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('request',lambda r:generations.append(r.url) if r.method=='POST' and ('/agui/run' in r.url or '/api/chat-assistant/messages' in r.url) else None)
        page.goto('http://127.0.0.1:3001/#/login',wait_until='networkidle')
        page.get_by_placeholder('请输入用户名').fill(name);page.get_by_placeholder('请输入密码').fill('123456')
        page.get_by_role('button',name='登录系统',exact=True).click();page.wait_for_url('**/#/home')
    context=browser.new_context(viewport={'width':1440,'height':1000});page=context.new_page();login(page,'supervisor.demo')
    page.goto('http://127.0.0.1:3001/#/agent/skills',wait_until='networkidle')
    row=page.locator('.el-table__body tr').filter(has_text=fixture['name']);expect(row).to_have_count(1)
    row.get_by_role('button',name='查看与管理').click()
    detail=page.get_by_role('dialog',name='技能详情与审核',exact=True)
    expect(detail.get_by_text('v3 待主管审核',exact=True)).to_be_visible()
    expect(detail.get_by_role('link',name='查看本人来源轨迹')).to_have_count(0)
    check('supervisor_ui_shows_frozen_proposal_without_private_trace')
    approve=detail.get_by_role('button',name='审核并发布',exact=True);expect(approve).to_be_disabled()
    detail.get_by_text('已核对经验的业务适用性',exact=True).click();detail.get_by_text('已核对内容脱敏及角色权限',exact=True).click()
    detail.get_by_placeholder('审核意见').fill('浏览器验收 通用流程与隐私已核对')
    approve.click();confirmation=page.get_by_role('dialog',name='确认审核决定',exact=True)
    expect(confirmation).to_be_visible();check('preview_does_not_publish',owner.get(url,timeout=15).json().get('activeVersion') is None)
    confirmation.get_by_role('button',name='确认发布',exact=True).click()
    expect(detail).to_contain_text('当前发布 v3');check('explicit_confirmation_publishes_actual_mysql_version')
    page.screenshot(path=str(root/'work/skill-evolution-browser-published.png'),full_page=True,animations='disabled')
    current=owner.get(url,timeout=15).json()
    response=boss.post(url+'/decision',headers={'X-Skill-Action':'update'},json={'expectedRevision':view['revision'],'decision':'APPROVE','reason':'重复确认','businessReviewed':True,'privacyReviewed':True},timeout=15)
    check('stale_revision_duplicate_publish_rejected',response.status_code==409)
    detail.get_by_placeholder('停用或版本回退原因').fill('浏览器回退验收')
    detail.locator('.review-panel').last.locator('.el-select').click()
    page.get_by_role('option',name='v1',exact=True).click()
    detail.get_by_role('button',name='切换到此审核版本',exact=True).click()
    page.get_by_role('dialog',name='确认版本切换',exact=True).get_by_role('button',name='确认切换',exact=True).click()
    expect(detail).to_contain_text('当前发布 v1');check('rollback_switches_to_previously_reviewed_version')
    detail.get_by_placeholder('停用或版本回退原因').fill('验收完成 停用样本技能')
    detail.get_by_role('button',name='停用技能',exact=True).click()
    page.get_by_role('dialog',name='确认停用',exact=True).get_by_role('button',name='确认停用',exact=True).click()
    expect(detail).to_contain_text('当前发布 无');check('archive_preserves_versions_and_stops_publication')
    final=owner.get(url,timeout=15).json();check('actual_sdk_use_count_and_business_audit_preserved',final['useCount']==1 and len(final['versions'])==3 and any(a['action_name']=='LOAD' for a in final['audit']))
    staff=context.new_page();login(staff,'inspector.demo');staff.goto('http://127.0.0.1:3001/#/agent/skills',wait_until='networkidle')
    staff.locator('.el-table__body tr').filter(has_text=fixture['name']).get_by_role('button',name='查看与管理').click()
    expect(staff.get_by_role('dialog',name='技能详情与审核').get_by_role('link',name='查看本人来源轨迹')).to_have_count(3)
    check('owner_can_follow_only_own_source_trace')
    staff.screenshot(path=str(root/'work/skill-evolution-browser-owner.png'),full_page=True,animations='disabled')
    check('no_model_replay_or_javascript_errors',not generations and not errors)
    browser.close()
(root/'work/skill-evolution-browser-acceptance.json').write_text(json.dumps({'checks':checks,'javascriptErrors':errors,'modelRequests':generations,'paidModelsCalled':False,'actualMysql':True},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'checks':len(checks),'allPassed':True,'artifact':'work/skill-evolution-browser-acceptance.json'}))
