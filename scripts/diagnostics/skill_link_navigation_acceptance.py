"""Both chat entries return actionable confirmation links without downloading or calling models."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright,expect

root=Path(__file__).resolve().parents[2];base='http://127.0.0.1:3001';url='https://modelscope.cn/skills/@anthropics/skill-creator';errors=[];checks=[]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce');page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(base+'/#/login',wait_until='networkidle');page.get_by_placeholder('请输入用户名').fill('inspector.demo');page.get_by_placeholder('请输入密码').fill('123456');page.get_by_role('button',name='登录系统',exact=True).click();page.wait_for_url('**/#/home')
        before=context.request.get(base+'/api/agent/skills/links').json()
        page.get_by_title('智能助手',exact=True).click();page.get_by_title('展开会话列表',exact=True).click();page.get_by_role('button',name='新建对话',exact=True).click();page.get_by_title('收起会话列表',exact=True).click()
        field=page.get_by_role('textbox',name='聊天消息或技能命令',exact=True);field.fill('/skills install '+url);field.press('Enter');link=page.locator('.msg-list').get_by_role('link',name='打开本人技能页面确认下载',exact=True);expect(link).to_be_visible(timeout=20000);link.click();expect(page.get_by_role('textbox',name='Skill 来源链接')).to_have_value(url)
        checks.append({'name':'vue_command_renders_link_and_prefills_confirmation_page','passed':True})
        agent=context.new_page();agent.on('pageerror',lambda error:errors.append(str(error)));agent.goto('http://127.0.0.1:3003',wait_until='networkidle');sender=agent.get_by_placeholder('输入问题 或输入 / 选择技能命令',exact=True);expect(sender).to_be_enabled();agent.get_by_role('button',name='新建对话',exact=True).click();expect(sender).to_be_enabled();sender.fill('/skills install '+url);sender.press('Enter');react_link=agent.locator('.bubble-list').get_by_role('link',name='打开本人技能页面确认下载',exact=True).last;expect(react_link).to_be_visible(timeout=20000);href=react_link.get_attribute('href');assert href.startswith(base+'/#/agent/skills?installUrl=');react_link.click();agent.wait_for_url('http://127.0.0.1:3001/**');expect(agent.get_by_role('textbox',name='Skill 来源链接')).to_have_value(url)
        assert context.request.get(base+'/api/agent/skills/links').json()==before;assert not errors
        checks.append({'name':'react_command_targets_business_site_and_neither_chat_downloads_without_ui_confirmation','passed':True})
    finally:
        (root/'work/skill-links-navigation-acceptance.json').write_text(json.dumps({'passed':len(checks)==2 and not errors,'checks':checks,'javascriptErrors':errors,'paidModelsCalled':False,'downloadsStarted':False},ensure_ascii=False,indent=2),encoding='utf-8');context.close();browser.close()
