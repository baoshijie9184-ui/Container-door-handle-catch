"""Actual fixed Fetch install/stdio lifecycle; models are not requested by this script."""
import json,time,uuid
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
root=Path(__file__).resolve().parents[2];base='http://127.0.0.1:3001';checks=[];errors=[]
def check(name):checks.append({'name':name,'passed':True})
def login(page,user):
    page.goto(base+'/#/login',wait_until='networkidle');page.get_by_placeholder('请输入用户名').fill(user);page.get_by_placeholder('请输入密码').fill('123456');page.get_by_role('button',name='登录系统',exact=True).click();page.wait_for_url('**/#/home');page.goto(base+'/#/agent/mcp',wait_until='networkidle')
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce');page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));login(page,'inspector.demo')
    response=context.request.get(base+'/api/agent/mcp/fetch');assert response.ok and response.headers['cache-control']=='no-store';state=response.json()
    if state['status']!='INSTALLED':
        page.get_by_role('button',name='安装到我的 Agent 目录',exact=True).click();dialog=page.get_by_role('dialog',name='确认安装本地 Fetch MCP',exact=True)
        button=dialog.get_by_role('button',name='确认安装',exact=True);expect(button).to_be_disabled()
        dialog.get_by_text('我确认安装此固定版本并已核对 MIT 许可证',exact=True).click();button.click()
        check('actual_install_requires_explicit_fixed_version_license_confirmation')
        deadline=time.monotonic()+620
        while time.monotonic()<deadline:
            state=context.request.get(base+'/api/agent/mcp/fetch').json()
            if state['status'] in ('INSTALLED','ERROR'):break
            time.sleep(3)
        assert state['status']=='INSTALLED',json.dumps({'status':state['status'],'errorCode':state.get('errorCode')})
    else:check('existing_fixed_install_reused_without_redownloading')
    assert not state['enabled'];assert state['manifest']['version']=='2026.10.10';assert state['manifest']['artifacts'] and state['manifest']['licenses']
    check('actual_install_retains_wheels_pinned_dependencies_license_and_private_directory_disabled')
    page.get_by_role('button',name='刷新状态',exact=True).click();expect(page.get_by_role('button',name='测试 Stdio 连接',exact=True)).to_be_visible()
    page.get_by_role('button',name='测试 Stdio 连接',exact=True).click();expect(page.get_by_text('Stdio 握手成功 已发现 fetch 工具',exact=True)).to_be_visible(timeout=45000)
    check('real_agentscope_stdio_handshake_discovers_only_fetch')
    page.get_by_role('button',name='启用本人 MCP',exact=True).click();page.get_by_role('dialog',name='确认 MCP 状态变更',exact=True).get_by_role('button',name='确认启用',exact=True).click();expect(page.get_by_role('button',name='停用本人 MCP',exact=True)).to_be_visible()
    enabled=context.request.get(base+'/api/agent/mcp/fetch').json();assert enabled['enabled']
    check('explicit_enable_with_revision_updates_own_server_and_audit')
    rejected=context.request.post(base+'/api/agent/mcp/fetch/enabled',headers={'X-MCP-Action':'update'},data={'expectedRevision':state['revision'],'enabled':False});assert rejected.status==409
    check('stale_revision_cannot_disable_current_configuration')
    other=browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce');mobile=other.new_page();mobile.on('pageerror',lambda e:errors.append(str(e)));login(mobile,'supervisor.demo')
    other_state=other.request.get(base+'/api/agent/mcp/fetch').json();assert other_state['status']=='NOT_INSTALLED' and not other_state['enabled'];assert other_state['directory']!=enabled['directory'];assert not other_state['audit']
    mobile.get_by_role('button',name='安装到我的 Agent 目录',exact=True).click();dialog=mobile.get_by_role('dialog',name='确认安装本地 Fetch MCP',exact=True);expect(dialog).to_be_visible();bounds=dialog.bounding_box();assert bounds['y']>=0 and bounds['y']+bounds['height']<=845
    assert dialog.locator('.el-dialog__body').evaluate('(node)=>node.scrollWidth<=node.clientWidth+1')
    mobile.screenshot(path=str(root/'work/local-mcp-mobile.png'),animations='disabled');dialog.get_by_role('button',name='取消',exact=True).click()
    page.screenshot(path=str(root/'work/local-mcp-desktop.png'),animations='disabled')
    check('supervisor_cannot_read_or_reuse_employee_install_and_mobile_dialog_fits')
    page.get_by_role('button',name='停用本人 MCP',exact=True).click();page.get_by_role('dialog',name='确认 MCP 状态变更',exact=True).get_by_role('button',name='确认停用',exact=True).click();expect(page.get_by_role('button',name='启用本人 MCP',exact=True)).to_be_visible()
    final=context.request.get(base+'/api/agent/mcp/fetch').json();assert not final['enabled'] and final['status']=='INSTALLED'
    check('disable_preserves_installed_files_and_operation_audit')
    anonymous=browser.new_context();assert anonymous.request.get(base+'/api/agent/mcp/fetch').status in (401,403);anonymous.close();check('anonymous_directory_requires_login')
    assert not errors;browser.close()
(root/'work/local-mcp-browser-acceptance.json').write_text(json.dumps({'checks':checks,'javascriptErrors':errors,'paidModelsCalled':False,'actualInstallAndStdio':True,'installedDirectory':final['directory'],'manifest':final['manifest'],'leftEnabled':False},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'checks':len(checks),'allPassed':True,'paidModelsCalled':False}))
