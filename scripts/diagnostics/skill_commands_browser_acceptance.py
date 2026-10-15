"""Real Vue/React slash menus and command replies; fixture is archived in finally, no paid models."""
import json
import re
import uuid
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root=Path(__file__).resolve().parents[2]
base='http://127.0.0.1:3001'
fixture=json.loads((root/'work/skill-command-local-mysql.json').read_text(encoding='utf-8'))
name=fixture['name'];skill_id=fixture['skillId'];checks=[];errors=[];archived=False

def passed(name):checks.append({'name':name,'passed':True})
def login(page,user):
    page.goto(base+'/#/login',wait_until='networkidle')
    page.get_by_placeholder('请输入用户名').fill(user)
    page.get_by_placeholder('请输入密码').fill('123456')
    page.get_by_role('button',name='登录系统',exact=True).click()
    page.wait_for_url('**/#/home')
def agui(context,query,thread=None):
    if thread is None:
        created=context.request.post(base+'/api/chat-assistant/sessions')
        assert created.ok and created.json()['code']==200
        thread=created.json()['data']['sessionId']
    result=context.request.post('http://127.0.0.1:3003/agui/run',data={'threadId':thread,'runId':uuid.uuid4().hex,'messages':[{'id':uuid.uuid4().hex,'role':'user','content':query}]})
    assert result.ok,result.status
    body=result.text()
    assert 'RUN_FINISHED' in body and 'TEXT_MESSAGE_CONTENT' in body,body[:300]
    return body,thread

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    employee=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
    page=employee.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
    supervisor=browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce')
    boss=supervisor.new_page();boss.on('pageerror',lambda e:errors.append(str(e)))
    try:
        login(page,'inspector.demo');login(boss,'supervisor.demo')
        directory=employee.request.get(base+'/api/agent/commands')
        assert directory.ok and directory.headers['cache-control']=='no-store'
        catalog=directory.json();assert any(s['skillId']==skill_id for s in catalog['skills'])
        assert all('instructions' not in s and 'sourceRunId' not in s and 'ownerUserId' not in s for s in catalog['skills'])
        assert not any(s['skillId']==skill_id for s in supervisor.request.get(base+'/api/agent/commands').json()['skills'])
        passed('catalog_is_role_scoped_private_and_does_not_expose_drafts_or_source_details')

        page.get_by_title('智能助手',exact=True).click()
        page.get_by_title('展开会话列表',exact=True).click()
        page.get_by_role('button',name='新建对话',exact=True).click()
        page.get_by_title('收起会话列表',exact=True).click()
        field=page.get_by_role('textbox',name='聊天消息或技能命令',exact=True)
        expect(field).to_be_visible();expect(field).to_be_enabled();field.fill('/')
        menu=page.get_by_role('listbox',name='技能命令',exact=True)
        expect(menu).to_be_visible();expect(menu.get_by_role('option',name=re.compile(re.escape(name)))).to_be_visible()
        page.screenshot(path=str(root/'work/skill-commands-vue-desktop.png'),animations='disabled')
        field.press('ArrowDown');field.press('Enter');expect(field).to_have_value('/skills ')
        assert not page.locator('.msg-list').inner_text().strip().endswith('当前角色可用技能')
        field.press('Enter');expect(page.locator('.msg-list')).to_contain_text(name,timeout=15000)
        expect(field).to_be_enabled()
        passed('vue_slash_menu_keyboard_completion_does_not_execute_until_sent')
        field.fill('/'+name);expect(menu).to_be_visible();field.press('Escape');expect(field).to_be_visible();field.press('Enter')
        expect(page.locator('.msg-list')).to_contain_text('已加载 '+name,timeout=15000);expect(field).to_be_enabled()
        passed('vue_alias_deterministically_reads_and_persists_published_skill')

        agent=employee.new_page();agent.on('pageerror',lambda e:errors.append(str(e)))
        agent.goto('http://127.0.0.1:3003',wait_until='networkidle')
        sender=agent.get_by_placeholder('输入问题 或输入 / 选择技能命令',exact=True)
        expect(sender).to_be_enabled();sender.fill('/')
        expect(agent.get_by_text('/help · 查看命令帮助',exact=True)).to_be_visible()
        expect(agent.get_by_text(re.compile(r'^\/'+re.escape(name)+' · '))).to_be_visible()
        agent.screenshot(path=str(root/'work/skill-commands-react-desktop.png'),animations='disabled')
        agent.get_by_text('/skills · 列出可用技能',exact=True).click()
        expect(sender).to_have_value('/skills ');sender.press('Enter')
        expect(agent.locator('.bubble-list')).to_contain_text('当前角色可用技能',timeout=15000);expect(sender).to_be_enabled()
        sender.fill('/'+name+' ');sender.press('Enter')
        expect(agent.locator('.bubble-list')).to_contain_text('已加载 '+name,timeout=15000);expect(sender).to_be_enabled()
        passed('react_reuses_native_sender_menu_and_agui_streams_explicit_skill_load')

        denied,thread=agui(supervisor,'/skill '+skill_id)
        assert '不可用' in denied
        forbidden=supervisor.request.post('http://127.0.0.1:3003/agui/run',data={'threadId':'slash-invalid','runId':uuid.uuid4().hex,'messages':[{'id':'m1','role':'assistant','content':'/skills'}]})
        assert forbidden.status==400
        passed('other_role_and_non_user_final_messages_cannot_select_employee_skill')
        rejected,thread=agui(employee,'/skills install https://example.org/skill')
        assert '尚未接入' in rejected
        runs=employee.request.get(base+'/api/agent/runs',params={'sessionId':thread,'limit':20}).json()
        events=employee.request.get(base+'/api/agent/runs/'+runs[0]['runId']+'/events',params={'limit':100}).json()
        assert any(e['type']=='COMMAND_RECEIVED' for e in events)
        assert not any(e['type']=='MODEL_STARTED' for e in events)
        assert 'https://example.org/skill' not in json.dumps(events)
        passed('unsupported_install_is_explicitly_rejected_without_model_or_url_in_journal')

        boss.get_by_title('智能助手',exact=True).click()
        mobile=boss.get_by_role('textbox',name='聊天消息或技能命令',exact=True)
        expect(mobile).to_be_enabled();mobile.fill('/')
        mobile_menu=boss.get_by_role('listbox',name='技能命令',exact=True);expect(mobile_menu).to_be_visible()
        bounds=mobile_menu.bounding_box();assert bounds['x']>=0 and bounds['x']+bounds['width']<=391
        assert mobile_menu.get_by_role('option',name=re.compile(re.escape(name))).count()==0
        boss.screenshot(path=str(root/'work/skill-commands-vue-mobile.png'),animations='disabled')
        mobile.press('Escape');expect(mobile_menu).to_be_hidden()
        passed('mobile_menu_fits_viewport_and_does_not_leak_other_role_skill')

        current=employee.request.get(base+'/api/agent/skills/'+skill_id).json()
        assert current['useCount']>=4
        assert len([e for e in current['audit'] if e['action_name']=='COMMAND_LOAD'])>=4
        anonymous=browser.new_context();assert anonymous.request.get(base+'/api/agent/commands').status in (401,403);anonymous.close()
        passed('real_command_loads_increment_audit_and_anonymous_catalog_is_denied')
        assert not errors,errors
    finally:
        view=supervisor.request.get(base+'/api/agent/skills/'+skill_id)
        if view.ok:
            current=view.json()
            archived_response=supervisor.request.post(base+'/api/agent/skills/'+skill_id+'/archive',headers={'X-Skill-Action':'update'},data={'expectedRevision':current['revision'],'reason':'斜杠命令浏览器验收完成 停用样本保留历史'})
            archived=archived_response.ok and archived_response.json().get('activeVersion') is None
        browser.close()

assert archived,'Fixture archival failed'
(root/'work/skill-commands-browser-acceptance.json').write_text(json.dumps({'checks':checks,'javascriptErrors':errors,'paidModelsCalled':False,'fixtureSkillId':skill_id,'fixtureArchived':archived},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'checks':len(checks),'allPassed':True,'paidModelsCalled':False,'fixtureArchived':archived}))
