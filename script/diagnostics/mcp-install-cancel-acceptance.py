"""Browser checks with isolated API fixtures; never cancels a real installation."""
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

OUT=Path(__file__).resolve().parents[2]/'work/mcp-install-cancel'
OUT.mkdir(parents=True,exist_ok=True)
checks,errors,requests=[],[],[]
operation='00000000-0000-0000-0000-000000000001'
state={'serverKey':'fetch','name':'Fetch 网页内容抓取','status':'INSTALLING','enabled':False,'revision':1,'operationId':operation,
       'version':'2026.10.10','license':'MIT','transport':'STDIO','directory':'users/1/mcp/fetch','manifest':None,'requiresMigration':False,
       'sourceUrl':'https://modelscope.cn/mcp/servers/@modelcontextprotocol/fetch','errorCode':None,'audit':[]}
mode='success'

def reply(route,data,status=200,wrapped=False):
    route.fulfill(status=status,content_type='application/json',body=json.dumps({'code':200,'data':data} if wrapped else data,ensure_ascii=False))

def api(route):
    req=route.request;path=urlparse(req.url).path
    if not path.startswith('/api/'):return route.continue_()
    requests.append({'path':path,'method':req.method,'body':req.post_data_json if req.method=='POST' and req.post_data else None})
    if path=='/api/auth/check':return reply(route,{'username':'employee.demo','role':'INSPECTOR'},wrapped=True)
    if path=='/api/agent/mcp/fetch':return reply(route,state)
    if path=='/api/agent/mcp/fetch/install/cancel':
        assert req.method=='POST' and req.headers.get('x-mcp-action')=='update'
        assert req.post_data_json=={'operationId':operation,'expectedRevision':1,'confirmed':True}
        if mode=='conflict':
            state.update(status='INSTALLED',revision=2)
            return reply(route,{'message':'当前安装已结束 不能取消 已安装工具请使用停用'},status=409)
        if mode=='error':return reply(route,{'message':'取消结果尚未核实 请刷新状态后核对'},status=503)
        state.update(status='CANCELLED',revision=2,audit=[{'action_name':'CANCEL_INSTALL','outcome':'SUCCEEDED','created_at':'2026-10-16T20:00:00'}])
        return reply(route,state)
    if path=='/api/chat-assistant/agent-health':return reply(route,{'framework':'AgentScope','runJournalEnabled':True},wrapped=True)
    if path=='/api/chat-assistant/session':return reply(route,{'sessionId':'fixture','messages':[]},wrapped=True)
    return reply(route,[],wrapped=True)

def check(name,action):
    try:action();checks.append({'name':name,'passed':True})
    except Exception as error:checks.append({'name':name,'passed':False,'error':str(error)})
def ensure(condition,message):assert condition,message
def cancel_requests():return [row for row in requests if row['path'].endswith('/install/cancel')]
def reset(page):
    state.update(status='INSTALLING',revision=1,operationId=operation,enabled=False,audit=[])
    target='http://127.0.0.1:3011/#/agent/mcp'
    if page.url==target:page.reload()
    else:page.goto(target)
    page.wait_for_load_state('networkidle')
def capture(page,name):page.wait_for_timeout(250);page.screenshot(path=str(OUT/(name+'.png')),full_page=True)

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000})
    context.route('**/api/**',api)
    page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
    reset(page)
    check('installing task exposes cancellation',lambda:expect(page.get_by_role('button',name='取消本次安装',exact=True)).to_be_visible())
    check('installing task has no enable action',lambda:expect(page.get_by_role('button',name='启用本人 MCP',exact=True)).to_have_count(0))
    count=len(cancel_requests())
    page.get_by_role('button',name='取消本次安装',exact=True).click()
    dialog=page.get_by_role('dialog',name='确认取消安装')
    check('confirmation states retained files and best effort interruption',lambda:expect(dialog).to_contain_text('已有文件保留'))
    check('opening confirmation does not cancel',lambda:ensure(len(cancel_requests())==count,'request before confirmation'))
    capture(page,'confirm-desktop')
    dialog.get_by_role('button',name='继续等待',exact=True).click();expect(dialog).not_to_be_visible()
    check('continue waiting does not cancel',lambda:ensure(len(cancel_requests())==count,'declining sent request'))
    page.get_by_role('button',name='取消本次安装',exact=True).click();dialog.get_by_role('button',name='确认取消安装',exact=True).click()
    check('confirmed cancellation shows revoked registration',lambda:expect(page.get_by_text('本次安装登记已撤销',exact=False)).to_be_visible())
    check('confirmed cancellation makes exactly one request',lambda:ensure(len(cancel_requests())==count+1,'duplicate cancellation'))
    check('cancelled state keeps a new-install entry',lambda:expect(page.get_by_role('button',name='安装到我的 Agent 目录',exact=True)).to_be_visible())
    check('cancelled state cannot enable MCP',lambda:expect(page.get_by_role('button',name='启用本人 MCP',exact=True)).to_have_count(0))
    check('cancellation receipt appears in own audit',lambda:expect(page.locator('.audit-panel')).to_contain_text('CANCEL_INSTALL'))
    page.get_by_role('button',name='安装到我的 Agent 目录',exact=True).click()
    install=page.get_by_role('dialog',name='确认安装 Fetch MCP')
    check('reinstallation requires fresh license confirmation',lambda:expect(install.get_by_role('checkbox')).not_to_be_checked())
    check('reinstallation submit is disabled before consent',lambda:expect(install.get_by_role('button',name='确认安装',exact=True)).to_be_disabled())
    install.get_by_role('button',name='取消',exact=True).click();expect(install).not_to_be_visible()
    mode='conflict';reset(page)
    page.get_by_role('button',name='取消本次安装',exact=True).click();dialog.get_by_role('button',name='确认取消安装',exact=True).click()
    check('completed-install race is reported without claiming cancellation',lambda:expect(page.get_by_role('alert').filter(has_text='已结束')).to_be_visible())
    page.get_by_role('button',name='刷新状态',exact=True).click()
    check('refresh after conflict shows the actual installed state',lambda:expect(page.get_by_role('button',name='启用本人 MCP',exact=True)).to_be_visible())
    check('installed state has no cancel-install action',lambda:expect(page.get_by_role('button',name='取消本次安装',exact=True)).to_have_count(0))
    mode='error';reset(page)
    page.get_by_role('button',name='取消本次安装',exact=True).click();dialog.get_by_role('button',name='确认取消安装',exact=True).click()
    check('uncertain cancellation tells user to refresh',lambda:expect(page.get_by_role('alert').filter(has_text='尚未核实')).to_be_visible())
    count=len(cancel_requests());page.wait_for_timeout(4300)
    check('uncertain cancellation never retries the mutation',lambda:ensure(len(cancel_requests())==count,'automatic cancellation retry'))
    state.pop('operationId',None);page.get_by_role('button',name='刷新状态',exact=True).click()
    check('old server without operation ID offers no unsupported cancellation',lambda:expect(page.get_by_role('button',name='取消本次安装',exact=True)).to_have_count(0))
    mode='success';reset(page);page.set_viewport_size({'width':390,'height':844});page.emulate_media(reduced_motion='reduce')
    page.get_by_role('button',name='取消本次安装',exact=True).click()
    check('mobile confirmation fits the viewport',lambda:ensure(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'horizontal overflow'))
    check('mobile confirmation action is accessible',lambda:expect(dialog.get_by_role('button',name='确认取消安装',exact=True)).to_be_visible())
    capture(page,'confirm-mobile');dialog.get_by_role('button',name='继续等待',exact=True).click()
    page.set_viewport_size({'width':1440,'height':1000});reset(page)
    count=len(cancel_requests());page.get_by_role('button',name='取消本次安装',exact=True).click()
    page.evaluate("location.hash='#/agent/markets'")
    check('leaving the page dismisses unsubmitted cancellation',lambda:expect(dialog).not_to_be_visible())
    page.wait_for_timeout(300)
    check('leaving the page sends no cancellation',lambda:ensure(len(cancel_requests())==count,'cancel after unmount'))
    reset(page);state.update(installQueue='DURABLE',installPhase='QUEUED');page.get_by_role('button',name='刷新状态',exact=True).click()
    check('durable waiting state explains restart recovery',lambda:expect(page.get_by_role('status').filter(has_text='已保存安装任务')).to_contain_text('确认有效期内恢复'))
    check('durable waiting state still allows explicit cancellation',lambda:expect(page.get_by_role('button',name='取消本次安装',exact=True)).to_be_enabled())
    check('durable waiting state cannot enable MCP',lambda:expect(page.get_by_role('button',name='启用本人 MCP',exact=True)).to_have_count(0))
    capture(page,'durable-queued-desktop')
    state['installPhase']='RUNNING';page.get_by_role('button',name='刷新状态',exact=True).click()
    check('durable running state never promises automatic replay',lambda:expect(page.get_by_role('status').filter(has_text='已开始执行安装')).to_contain_text('不会自动重复安装'))
    page.set_viewport_size({'width':390,'height':844})
    check('mobile durable state fits viewport',lambda:ensure(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'durable mobile overflow'))
    capture(page,'durable-running-mobile')
    state.pop('installQueue');state.pop('installPhase');page.get_by_role('button',name='刷新状态',exact=True).click()
    check('older server has no fabricated durable recovery claim',lambda:expect(page.get_by_role('status').filter(has_text='已保存安装任务')).to_have_count(0))
    check('browser has no JavaScript errors',lambda:ensure(not errors,str(errors)))
    check('management never calls a model or Fetch tool',lambda:ensure(not any(row['path'] in ('/agui/run','/api/chat-assistant/messages','/api/chat-assistant/messages/stream') for row in requests),'unexpected generation'))
    browser.close()

failed=[row for row in checks if not row['passed']]
(OUT/'results.json').write_text(json.dumps({'mode':'isolated API fixtures','checks':checks,'requests':requests,'javascriptErrors':errors},ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'passed':len(checks)-len(failed),'failed':failed,'javascriptErrors':errors},ensure_ascii=False))
if failed:raise SystemExit(1)
