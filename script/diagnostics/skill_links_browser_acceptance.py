"""Real public download and UI consent checks; no model calls or third-party script execution."""
from pathlib import Path
import json
import time
import uuid
from playwright.sync_api import sync_playwright,expect

root=Path(__file__).resolve().parents[2];base='http://127.0.0.1:3001';checks=[];errors=[];mutations=[]
url='https://modelscope.cn/skills/@anthropics/skill-creator'
def passed(name):checks.append({'name':name,'passed':True})
def login(page,user):
    page.goto(base+'/#/login',wait_until='networkidle');page.get_by_placeholder('请输入用户名').fill(user);page.get_by_placeholder('请输入密码').fill('123456');page.get_by_role('button',name='登录系统',exact=True).click();page.wait_for_url('**/#/home')

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True);employee=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce');boss=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce');page=employee.new_page();boss_page=boss.new_page()
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda request:mutations.append(request.post_data_json) if request.method=='POST' and request.url.endswith('/api/agent/skills/links') else None)
    artifact={'checks':checks,'paidModelsCalled':False,'scriptsExecuted':False};skill_id=None
    try:
        login(page,'inspector.demo');login(boss_page,'supervisor.demo')
        assert employee.request.get(base+'/api/agent/skills/links').headers['cache-control']=='no-store'
        anonymous=browser.new_context();assert anonymous.request.get(base+'/api/agent/skills/links').status in (401,403);anonymous.close()
        passed('private_download_api_is_authenticated_and_not_cached')
        for payload in [{'url':url,'targetRole':'INSPECTOR','requestId':uuid.uuid4().hex,'confirmed':False},{'url':'https://127.0.0.1/secret','targetRole':'INSPECTOR','requestId':uuid.uuid4().hex,'confirmed':True}]:
            response=employee.request.post(base+'/api/agent/skills/links',data=payload,headers={'X-Skill-Action':'update'});assert response.status==400
        escalation=employee.request.post(base+'/api/agent/skills/links',data={'url':url,'targetRole':'SUPERVISOR','requestId':uuid.uuid4().hex,'confirmed':True},headers={'X-Skill-Action':'update'});assert escalation.status==403
        assert employee.request.get(base+'/api/agent/skills/imports').status==410
        passed('unconfirmed_download_private_sources_role_escalation_and_retired_zip_are_rejected')
        page.goto(base+'/#/agent/skills?installUrl='+url,wait_until='networkidle');expect(page.get_by_role('heading',name='从链接安装 Skill')).to_be_visible();expect(page.get_by_role('textbox',name='Skill 来源链接')).to_have_value(url)
        button=page.get_by_role('button',name='确认下载为私人草稿',exact=True);expect(button).to_be_enabled();button.click();expect(page.get_by_role('dialog',name='确认链接下载')).to_be_visible();page.get_by_role('button',name='取消',exact=True).last.click();assert not mutations
        passed('agent_navigation_prefills_link_and_cancel_does_not_download')
        button.click()
        with page.expect_response(lambda response:response.request.method=='POST' and response.url.endswith('/api/agent/skills/links')) as started:
            page.get_by_role('button',name='确认下载',exact=True).click()
        record=started.value.json();download_id=record['download_id'];assert record['status'] in ('DOWNLOADING','DRAFT_CREATED');assert len(mutations)==1 and mutations[0]['confirmed']
        replay=employee.request.post(base+'/api/agent/skills/links',data=mutations[0],headers={'X-Skill-Action':'update'});assert replay.ok and replay.json()['download_id']==download_id
        deadline=time.monotonic()+200
        while time.monotonic()<deadline:
            row=next(row for row in employee.request.get(base+'/api/agent/skills/links').json() if row['download_id']==download_id)
            if row['status'] not in ('DOWNLOADING','DOWNLOADED'):break
            page.wait_for_timeout(1500)
        assert row['status']=='DRAFT_CREATED',row
        skill_id=row['skill_id'];artifact['downloadId']=download_id;artifact['skillId']=skill_id
        view=employee.request.get(base+'/api/agent/skills/'+skill_id).json();v=view['versions'][0];assert v['status']=='DRAFT' and view.get('activeVersion') is None
        assert v['evidence']['sourceType']=='LINK' and v['evidence']['provenanceVerified'] and not v['evidence']['scriptsExecutable']
        assert v['evidence']['revisionKind']=='CONTENT_SNAPSHOT' and v['evidence'].get('commit') is None and v['evidence']['licenses']
        assert len(v['evidence']['archiveSha256'])==64 and v['evidence']['sourceVersion']=='snapshot-sha256:'+v['evidence']['archiveSha256']
        artifact['archiveSha256']=v['evidence']['archiveSha256'];artifact['fileCount']=len(v['evidence']['files'])
        assert boss.request.get(base+'/api/agent/skills/'+skill_id).status==404
        assert all(item['download_id']!=download_id for item in boss.request.get(base+'/api/agent/skills/links').json())
        passed('real_modelscope_native_archive_is_snapshotted_licensed_private_and_idempotent')
        page.get_by_role('button',name='刷新',exact=True).click();target=page.locator('.link-install-panel .el-table__body-wrapper tr').filter(has_text=url).first;expect(target).to_contain_text('下载完成 已保存');target.get_by_role('button',name='查看私人草稿').click()
        dialog=page.get_by_role('dialog',name='技能详情与审核');expect(dialog).to_contain_text('归档快照');expect(dialog).to_contain_text('只存档');expect(dialog.get_by_role('button',name='运行规则 Eval')).to_be_visible();expect(dialog.get_by_role('button',name='提交独立审核')).to_have_count(0)
        page.screenshot(path=str(root/'work/skill-links-desktop.png'),animations='disabled')
        passed('downloaded_original_skill_and_license_are_previewed_before_evaluation_or_submission')
        dialog.get_by_role('button',name='卸载此链接技能').click();page.get_by_role('button',name='确认卸载',exact=True).click();expect(dialog.get_by_role('button',name='卸载此链接技能')).to_have_count(0)
        after=employee.request.get(base+'/api/agent/skills/'+skill_id).json();assert after['lifecycle']=='ARCHIVED' and after.get('activeVersion') is None and after['versions'][0]['sha256']==v['sha256']
        passed('owner_uninstall_disables_loading_and_preserves_original_version_and_audit')
        dialog.locator('.el-dialog__headerbtn').click();page.set_viewport_size({'width':390,'height':844});page.locator('.link-install-panel').evaluate("el=>el.scrollIntoView({block:'start'})");page.screenshot(path=str(root/'work/skill-links-mobile.png'),animations='disabled');assert page.evaluate('document.documentElement.scrollWidth <= innerWidth');assert not errors
        passed('mobile_layout_has_no_page_overflow_or_javascript_errors')
    finally:
        artifact.update({'passed':len(checks)==7 and not errors,'javascriptErrors':errors});(root/'work/skill-links-browser-acceptance.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2),encoding='utf-8');employee.close();boss.close();browser.close()
