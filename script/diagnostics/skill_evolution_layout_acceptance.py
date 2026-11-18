"""Read-only desktop/mobile inspection after the mutating skill review acceptance."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

root=Path(__file__).resolve().parents[2]
fixture=json.loads((root/'work/skill-evolution-local-mysql.json').read_text(encoding='utf-8'))
checks=[]; errors=[]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    for role,width,height in [('supervisor.demo',1440,1000),('inspector.demo',390,844)]:
        context=browser.new_context(viewport={'width':width,'height':height},reduced_motion='reduce'); page=context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:3001/#/login',wait_until='networkidle')
        page.get_by_placeholder('请输入用户名').fill(role);page.get_by_placeholder('请输入密码').fill('123456')
        page.get_by_role('button',name='登录系统',exact=True).click();page.wait_for_url('**/#/home')
        page.goto('http://127.0.0.1:3001/#/agent/skills',wait_until='networkidle')
        page.locator('.el-table__body tr').filter(has_text=fixture['name']).get_by_role('button',name='查看与管理').click()
        dialog=page.get_by_role('dialog',name='技能详情与审核',exact=True);expect(dialog).to_be_visible()
        expect(dialog).to_contain_text('当前发布 无')
        bounds=dialog.bounding_box();assert bounds['y']>=0 and bounds['y']+bounds['height']<=height+1
        body=dialog.locator('.el-dialog__body');assert body.evaluate('(node)=>node.scrollHeight>node.clientHeight && node.scrollWidth<=node.clientWidth+1')
        checks.append({'name':role+'_dialog_fits_viewport_and_scrolls_internally','passed':True})
        body.evaluate('(node)=>node.scrollTop=0')
        page.screenshot(path=str(root/('work/skill-evolution-browser-desktop.png' if width>1000 else 'work/skill-evolution-browser-mobile.png')),full_page=True,animations='disabled')
        context.close()
    assert not errors
    browser.close()
(root/'work/skill-evolution-layout-acceptance.json').write_text(json.dumps({'checks':checks,'javascriptErrors':errors,'readOnly':True},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'checks':len(checks),'allPassed':True}))
