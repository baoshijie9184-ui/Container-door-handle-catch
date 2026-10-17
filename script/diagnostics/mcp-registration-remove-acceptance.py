"""Isolated browser fixtures; never removes a real MCP registration or file."""
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

OUT=Path(__file__).resolve().parents[2]/'work/mcp-registration-remove'
OUT.mkdir(parents=True,exist_ok=True)
checks,errors,requests=[],[],[]
operation='00000000-0000-0000-0000-000000000001'
state={}
mode='success'

def reply(route,data,status=200,wrapped=False):
    route.fulfill(status=status,content_type='application/json',body=json.dumps({'code':200,'data':data} if wrapped else data,ensure_ascii=False))

def api(route):
    req=route.request;path=urlparse(req.url).path
    if not path.startswith('/api/'):return route.continue_()
    requests.append({'path':path,'method':req.method,'body':req.post_data_json if req.method=='POST' and req.post_data else None})
    if path=='/api/auth/check':return reply(route,{'username':'employee.demo','role':'INSPECTOR'},wrapped=True)
    if path=='/api/agent/mcp/fetch':return reply(route,state)
    if path=='/api/agent/mcp/fetch/enabled':
        assert req.post_data_json=={'expectedRevision':state['revision'],'enabled':False}
        assert req.headers.get('x-mcp-action')=='update'
        state.update(enabled=False,revision=state['revision']+1)
        return reply(route,state)
    if path=='/api/agent/mcp/fetch/registration/remove':
        assert req.method=='POST' and req.headers.get('x-mcp-action')=='update'
        assert req.post_data_json=={'operationId':operation,'expectedRevision':state['revision'],'confirmed':True}
        assert not state['enabled']
        if mode=='conflict':
            state.update(enabled=True,revision=state['revision']+1)
            return reply(route,{'message':'MCP 状态已变化 请刷新'},status=409)
        if mode=='error':return reply(route,{'message':'移除结果尚未核实 请刷新后核对'},status=503)
        state.update(status='UNINSTALLED',revision=state['revision']+1,manifest=None,requiresMigration=False,
                     audit=[{'action_name':'REMOVE_REGISTRATION','outcome':'SUCCEEDED','created_at':'2026-10-16T20:30:00'}])
        if mode=='lost-response':return reply(route,{'message':'移除结果尚未核实 请刷新后核对'},status=503)
        return reply(route,state)
    if path=='/api/chat-assistant/agent-health':return reply(route,{'framework':'AgentScope'},wrapped=True)
    if path=='/api/chat-assistant/session':return reply(route,{'sessionId':'fixture','messages':[]},wrapped=True)
    return reply(route,[],wrapped=True)

def check(name,action):
    try:action();checks.append({'name':name,'passed':True})
    except Exception as error:checks.append({'name':name,'passed':False,'error':str(error)})

def ensure(condition,message):assert condition,message
def removals():return [row for row in requests if row['path'].endswith('/registration/remove')]
def reset(page,**overrides):
    state.clear()
    state.update(serverKey='fetch',name='Fetch 网页内容抓取',status='INSTALLED',enabled=False,revision=2,operationId=operation,
                 registrationRemovalSupported=True,version='2026.10.10',license='MIT',transport='STDIO',directory='users/1/mcp/fetch',
                 manifest={'packageSha256':'a'*64,'artifacts':[],'licenses':[]},requiresMigration=False,errorCode=None,
                 sourceUrl='https://modelscope.cn/mcp/servers/@modelcontextprotocol/fetch',audit=[])
    state.update(overrides)
    target='http://127.0.0.1:3011/#/agent/mcp'
    if page.url==target:page.reload()
    else:page.goto(target)
    page.wait_for_load_state('networkidle')

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000})
    context.route('**/api/**',api)
    page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
    remove=page.get_by_role('button',name='移除安装登记',exact=True)
    dialog=page.get_by_role('dialog',name='确认移除安装登记')
    reset(page)
    check('disabled installation allows registration removal',lambda:expect(remove).to_be_enabled())
    count=len(removals());remove.click()
    check('confirmation explains retained files licenses and audit',lambda:expect(dialog).to_contain_text('已有文件、许可证与审计保留'))
    check('confirmation does not promise disk space recovery',lambda:expect(dialog).to_contain_text('不释放磁盘空间'))
    check('opening confirmation sends no mutation',lambda:ensure(len(removals())==count,'early removal'))
    page.wait_for_timeout(350);page.screenshot(path=str(OUT/'confirm-desktop.png'),full_page=True)
    dialog.get_by_role('button',name='保留登记',exact=True).click();expect(dialog).not_to_be_visible()
    check('keeping registration sends no mutation',lambda:ensure(len(removals())==count,'decline sent removal'))
    remove.click();dialog.get_by_role('button',name='确认移除登记',exact=True).click()
    check('confirmed removal shows unusable retained-file state',lambda:expect(page.get_by_role('status').filter(has_text='本人安装登记已移除')).to_be_visible())
    check('confirmed removal makes exactly one request',lambda:ensure(len(removals())==count+1,'duplicate removal'))
    check('removed installation has no enable action',lambda:expect(page.get_by_role('button',name='启用本人 MCP',exact=True)).to_have_count(0))
    check('removed installation has no probe action',lambda:expect(page.get_by_role('button',name='测试 MCP 连接',exact=True)).to_have_count(0))
    check('removed installation has no repeated removal entry',lambda:expect(remove).to_have_count(0))
    check('removed manifest is no longer an active file listing',lambda:expect(page.locator('.files-panel')).to_have_count(0))
    check('removal receipt stays in own audit',lambda:expect(page.locator('.audit-panel')).to_contain_text('REMOVE_REGISTRATION'))
    page.get_by_role('button',name='安装到我的 Agent 目录',exact=True).click()
    install=page.get_by_role('dialog',name='确认安装 Fetch MCP')
    check('reinstallation requires fresh license confirmation',lambda:expect(install.get_by_role('checkbox')).not_to_be_checked())
    check('reinstallation cannot submit without consent',lambda:expect(install.get_by_role('button',name='确认安装',exact=True)).to_be_disabled())
    install.get_by_role('button',name='取消',exact=True).click()

    reset(page,enabled=True,requiresMigration=True)
    check('enabled installation blocks removal',lambda:expect(remove).to_be_disabled())
    check('enabled installation explains the disable prerequisite',lambda:expect(page.get_by_text('移除安装登记前，请先停用本人 MCP',exact=True)).to_be_visible())
    check('outdated enabled runtime still offers explicit disable',lambda:expect(page.get_by_role('button',name='停用本人 MCP',exact=True)).to_be_enabled())
    page.get_by_role('button',name='停用本人 MCP',exact=True).click()
    page.get_by_role('dialog',name='确认 MCP 状态变更').get_by_role('button',name='确认停用',exact=True).click()
    check('explicit disable makes removal available for outdated runtime',lambda:expect(remove).to_be_enabled())
    count=len(removals());remove.click();dialog.get_by_role('button',name='确认移除登记',exact=True).click()
    check('outdated runtime removal succeeds only after disable',lambda:expect(page.get_by_role('status').filter(has_text='本人安装登记已移除')).to_be_visible())
    check('outdated removal posts only once',lambda:ensure(len(removals())==count+1,'duplicate outdated removal'))

    mode='conflict';reset(page);remove.click();dialog.get_by_role('button',name='确认移除登记',exact=True).click()
    check('concurrent change is reported honestly',lambda:expect(page.get_by_role('alert').filter(has_text='已变化')).to_be_visible())
    page.get_by_role('button',name='刷新状态',exact=True).click()
    check('conflict refresh shows actual enabled state',lambda:expect(page.get_by_role('button',name='停用本人 MCP',exact=True)).to_be_visible())
    check('conflict does not leave removal enabled',lambda:expect(remove).to_be_disabled())

    mode='error';reset(page);remove.click();dialog.get_by_role('button',name='确认移除登记',exact=True).click()
    check('uncertain removal asks user to verify state',lambda:expect(page.get_by_role('alert').filter(has_text='尚未核实')).to_be_visible())
    count=len(removals());page.wait_for_timeout(4300)
    check('uncertain removal never retries automatically',lambda:ensure(len(removals())==count,'automatic retry'))
    mode='lost-response';reset(page);remove.click();dialog.get_by_role('button',name='确认移除登记',exact=True).click()
    expect(page.get_by_role('alert').filter(has_text='尚未核实')).to_be_visible();count=len(removals())
    page.get_by_role('button',name='刷新状态',exact=True).click()
    check('lost response is reconciled by read-only refresh',lambda:expect(page.get_by_role('status').filter(has_text='本人安装登记已移除')).to_be_visible())
    check('reconciliation sends no second removal',lambda:ensure(len(removals())==count,'refresh replayed mutation'))

    reset(page,registrationRemovalSupported=False)
    check('older server without capability has no unsupported removal',lambda:expect(remove).to_have_count(0))
    reset(page,status='INSTALLING')
    check('installing task offers cancellation instead of registration removal',lambda:ensure(remove.count()==0 and page.get_by_role('button',name='取消本次安装',exact=True).is_visible(),'wrong lifecycle action'))
    mode='success';reset(page);page.set_viewport_size({'width':390,'height':844});page.emulate_media(reduced_motion='reduce');remove.click()
    check('mobile confirmation has no horizontal overflow',lambda:ensure(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'mobile overflow'))
    check('mobile confirmation submit is accessible',lambda:expect(dialog.get_by_role('button',name='确认移除登记',exact=True)).to_be_visible())
    page.wait_for_timeout(350);page.screenshot(path=str(OUT/'confirm-mobile.png'),full_page=True)
    count=len(removals());page.evaluate("location.hash='#/agent/markets'")
    check('leaving dismisses unsubmitted removal confirmation',lambda:expect(dialog).not_to_be_visible())
    page.wait_for_timeout(300)
    check('leaving sends no removal',lambda:ensure(len(removals())==count,'removal after unmount'))
    check('browser has no JavaScript errors',lambda:ensure(not errors,str(errors)))
    check('management sends no model or tool invocation',lambda:ensure(not any(row['path'] in ('/agui/run','/api/chat-assistant/messages','/api/chat-assistant/messages/stream') for row in requests),'unexpected generation'))
    browser.close()

failed=[row for row in checks if not row['passed']]
(OUT/'results.json').write_text(json.dumps({'mode':'isolated API fixtures','checks':checks,'requests':requests,'javascriptErrors':errors},ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'passed':len(checks)-len(failed),'failed':failed,'javascriptErrors':errors},ensure_ascii=False))
if failed:raise SystemExit(1)
