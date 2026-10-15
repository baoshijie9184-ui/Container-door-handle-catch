"""Live MySQL/API upgrade, unchanged-version and owned cache-cleanup acceptance."""
from pathlib import Path
import json,time,uuid
from playwright.sync_api import sync_playwright,expect

root=Path(__file__).resolve().parents[2];base='http://127.0.0.1:3001';checks=[];errors=[];result={'paidModelsCalled':False,'scriptsExecuted':False}
def passed(name):checks.append({'name':name,'passed':True})
def login(page,user):
    page.goto(base+'/#/login',wait_until='networkidle');page.get_by_placeholder('请输入用户名').fill(user);page.get_by_placeholder('请输入密码').fill('123456');page.get_by_role('button',name='登录系统',exact=True).click();page.wait_for_url('**/#/home')
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True);employee=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce');boss=browser.new_context();page=employee.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        login(page,'inspector.demo');boss_page=boss.new_page();login(boss_page,'supervisor.demo')
        rows=employee.request.get(base+'/api/agent/skills/links').json();row=next(row for row in rows if row['status']=='DRAFT_CREATED' and row.get('skill_id'))
        skill_id=row['skill_id'];view=employee.request.get(base+'/api/agent/skills/'+skill_id).json();result['skillId']=skill_id
        latest=view['versions'][0];commit=latest['evidence']['commit'];source=latest['evidence']['resolvedUrl'];headers={'X-Skill-Action':'update'}
        original_versions=len(view['versions']);original_active=view.get('activeVersion');revision=view['revision']
        wrong=employee.request.post(base+'/api/agent/skills/links/'+skill_id+'/upgrade',headers=headers,data={'url':'https://github.com/other/skills/tree/main/skills/skill-creator','expectedRevision':revision,'requestId':uuid.uuid4().hex,'confirmed':True});assert wrong.status==409
        stale=employee.request.post(base+'/api/agent/skills/links/'+skill_id+'/upgrade',headers=headers,data={'url':source,'expectedRevision':max(1,revision-1),'requestId':uuid.uuid4().hex,'confirmed':True});assert revision>1 and stale.status==409
        foreign=boss.request.post(base+'/api/agent/skills/links/'+skill_id+'/upgrade',headers=headers,data={'url':source,'expectedRevision':revision,'requestId':uuid.uuid4().hex,'confirmed':True});assert foreign.status in (403,404)
        passed('wrong_repository_stale_revision_and_foreign_account_cannot_queue_upgrades')
        stats=employee.request.get(base+'/api/agent/skills/links/storage');assert stats.ok and stats.headers['cache-control']=='no-store';assert stats.json()['quotaBytes']>=5242880
        page.goto(base+'/#/agent/skills',wait_until='networkidle');expect(page.locator('.link-install-panel')).to_contain_text('本人存储')
        target=page.locator('.link-install-panel .el-table__body-wrapper tr').filter(has_text=row['source_url']).first;target.get_by_role('button',name='查看私人草稿',exact=True).click();dialog=page.get_by_role('dialog',name='技能详情与审核');dialog.get_by_role('button',name='下载原技能的新版本',exact=True).click()
        upgrade=page.get_by_role('dialog',name='下载原技能的新版本');upgrade.get_by_role('textbox',name='技能升级来源链接').fill(source)
        with page.expect_response(lambda response:response.request.method=='POST' and response.url.endswith('/'+skill_id+'/upgrade')) as started:
            upgrade.get_by_role('button',name='确认下载新版本',exact=True).click()
        response=started.value;assert response.ok;download_id=response.json()['download_id'];body=response.request.post_data_json;result['downloadId']=download_id
        replay=employee.request.post(base+'/api/agent/skills/links/'+skill_id+'/upgrade',headers=headers,data=body);assert replay.ok and replay.json()['download_id']==download_id
        deadline=time.monotonic()+200
        while time.monotonic()<deadline:
            current=next(r for r in employee.request.get(base+'/api/agent/skills/links').json() if r['download_id']==download_id)
            if current['status'] not in ('DOWNLOADING','DOWNLOADED'):break
            page.wait_for_timeout(1500)
        assert current['status']=='NO_CHANGE',current
        after=employee.request.get(base+'/api/agent/skills/'+skill_id).json();assert len(after['versions'])==original_versions and after.get('activeVersion')==original_active and after['revision']==revision
        passed('actual_pinned_download_replay_does_not_duplicate_unchanged_skill_version')
        dialog.locator('.el-dialog__headerbtn').click();page.get_by_role('button',name='刷新',exact=True).click();page.reload(wait_until='networkidle')
        same=page.locator('.link-install-panel .el-table__body-wrapper tr').filter(has_text='已核对 无版本变化').first;same.get_by_role('button',name='清理下载缓存',exact=True).click();confirmation=page.get_by_role('dialog',name='确认清理下载缓存');confirmation.get_by_role('button',name='取消',exact=True).click()
        assert next(r for r in employee.request.get(base+'/api/agent/skills/links').json() if r['download_id']==download_id)['status']=='NO_CHANGE'
        passed('physical_cleanup_requires_explicit_confirmation_and_cancel_retains_package')
        before=employee.request.get(base+'/api/agent/skills/links/storage').json()['usedBytes'];same.get_by_role('button',name='清理下载缓存',exact=True).click()
        with page.expect_response(lambda response:response.request.method=='POST' and response.url.endswith('/'+download_id+'/cleanup')) as cleaned:
            page.get_by_role('button',name='确认清理',exact=True).click()
        cleaned_response=cleaned.value;assert cleaned_response.ok;command=cleaned_response.json();assert command['status']=='COMPLETED' and command['removed_files']>0
        replay=employee.request.post(base+'/api/agent/skills/links/downloads/'+download_id+'/cleanup',headers=headers,data=cleaned_response.request.post_data_json);assert replay.ok and replay.json()==command
        assert employee.request.get(base+'/api/agent/skills/links/storage').json()['usedBytes']<before
        assert any(item['download_id']==download_id and item['status']=='COMPLETED' for item in employee.request.get(base+'/api/agent/skills/links/storage/audit').json())
        assert not any(item['download_id']==download_id for item in boss.request.get(base+'/api/agent/skills/links/storage/audit').json())
        protected=employee.request.post(base+'/api/agent/skills/links/downloads/'+row['download_id']+'/cleanup',headers=headers,data={'requestId':uuid.uuid4().hex,'confirmed':True});assert protected.status==409
        passed('owned_unreferenced_files_are_removed_once_with_private_audit_and_referenced_package_is_protected')
        page.locator('.link-install-panel').evaluate("el=>el.scrollIntoView({block:'start',behavior:'instant'})");page.screenshot(path=str(root/'work/skill-upgrades-storage-desktop.png'),animations='disabled');assert not errors
    finally:
        result.update({'checks':checks,'passed':len(checks)==4 and not errors,'javascriptErrors':errors});(root/'work/skill-upgrades-storage-acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');employee.close();boss.close();browser.close()
