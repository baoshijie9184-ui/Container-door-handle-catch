"""Harness-inspired workspaces, isolated APIs on Vite 3011 and 5175."""
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

OUT=Path(__file__).resolve().parents[2]/'work/harness-workspace'
OUT.mkdir(parents=True,exist_ok=True)
checks,errors,requests=[],[],[]
session={'sessionId':'workspace-session','title':'集装箱门把手检测调研','messages':[
    {'id':1,'role':'user','messageType':'TEXT','content':'核对检测结果的来源'},
    {'id':2,'role':'assistant','messageType':'TEXT','content':'可以查看本次运行记录的工具调用与调研来源。'},
]}
events=[{'type':'TOOL_STARTED' if i%2 else 'TOOL_COMPLETED','agent':'research-agent','tool':'fetch-recorded-'+str(i)} for i in range(1,11)]
trace={'runId':'workspace-run','status':'COMPLETED','events':events}
trace_mode='success'

def reply(route,data,raw=False,status=200):route.fulfill(status=status,content_type='application/json',body=json.dumps(data if raw else {'code':200,'data':data},ensure_ascii=False))
def api(route):
    req=route.request;path=urlparse(req.url).path
    if not path.startswith(('/api/','/agui/')):return route.continue_()
    requests.append({'method':req.method,'path':path})
    if path=='/api/auth/check':return reply(route,{'username':'supervisor.demo','role':'SUPERVISOR'})
    if path=='/api/chat-assistant/sessions':return reply(route,[session])
    if path.endswith('/trace'):
        if trace_mode=='failed':return reply(route,{'message':'记录读取失败'},raw=True,status=503)
        return reply(route,trace)
    if path.startswith('/api/chat-assistant/sessions/') or path=='/api/chat-assistant/session':return reply(route,session)
    if path.endswith('/agent-health'):return reply(route,{'framework':'AgentScope','mode':'CONFIRMABLE','runJournalEnabled':True,'defaultModel':'configured-default'})
    if path=='/api/agent/actions':return reply(route,[],True)
    if path=='/api/agent/commands':return reply(route,{'enabled':True,'skills':[]},True)
    if path=='/agui/catalog':return reply(route,{'role':'SUPERVISOR','mode':'CONFIRMABLE','mainAgent':'supervisor','agents':[]},True)
    if path=='/agui/models':return reply(route,{'models':[{'id':'deepseek:demo','model':'configured-demo','selected':True,'configured':True}], 'fallbackEnabled':False},True)
    return reply(route,[])
def check(name,action):
    try:action();checks.append({'name':name,'passed':True})
    except Exception as error:checks.append({'name':name,'passed':False,'error':str(error)})
def ensure(value,message):assert value,message
def no_overflow(page):ensure(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'horizontal overflow')
def capture(page,name):page.wait_for_timeout(300);page.screenshot(path=str(OUT/(name+'.png')),full_page=True)

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1600,'height':1000})
    context.route('**/api/**',api);context.route('**/agui/**',api)
    page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto('http://127.0.0.1:3011/#/agent/chat');page.wait_for_load_state('networkidle')
    draft=page.get_by_role('textbox',name='聊天消息或技能命令');draft.fill('保留我的未发送草稿')
    page.get_by_role('button',name='展开工作面板',exact=True).click()
    panel=page.get_by_role('complementary',name='Agent 工作面板')
    check('Vue panel identifies current session',lambda:expect(panel).to_contain_text(session['title']))
    check('Vue work panel exposes four resource links',lambda:expect(panel.locator('.context-resource')).to_have_count(4))
    check('Vue resource navigation uses business routes',lambda:ensure(panel.get_by_role('link',name='MCP 工具',exact=False).get_attribute('href')=='#/agent/mcp','wrong route'))
    check('Vue resource trace entry retains current session',lambda:expect(panel.get_by_role('link',name='执行与调研',exact=False)).to_have_attribute('href','#/agent/trace?sessionId=workspace-session'))
    check('Vue desktop panel is docked',lambda:ensure('context-floating' not in panel.get_attribute('class'),'unexpected overlay'))
    check('Vue desktop preserves a usable center',lambda:ensure(page.locator('.chat-main').bounding_box()['width']>=400,'conversation squeezed'))
    check('Vue desktop panel does not overlap transcript',lambda:ensure(panel.bounding_box()['x']>=page.locator('.chat-main').bounding_box()['x']+page.locator('.chat-main').bounding_box()['width']-1,'overlapping columns'))
    check('Vue panel opening retains composer draft',lambda:expect(draft).to_have_value('保留我的未发送草稿'))
    capture(page,'vue-workspace-desktop')
    page.get_by_role('tab',name='最近执行',exact=True).click()
    check('Vue execution pane starts without fabricated events',lambda:expect(panel.locator('.context-events li')).to_have_count(0))
    panel.get_by_role('button',name='刷新',exact=True).click()
    check('Vue execution pane shows only last eight recorded events',lambda:expect(panel.locator('.context-events li')).to_have_count(8))
    check('Vue execution pane uses actual run ID',lambda:expect(panel.get_by_role('link',name='打开执行追溯',exact=False)).to_have_attribute('href','#/agent/trace?runId=workspace-run'))
    check('Vue execution pane keeps actual tool names',lambda:expect(panel).to_contain_text('fetch-recorded-10'))
    check('Vue execution pane omits earlier two events',lambda:expect(panel.locator('.context-events')).not_to_contain_text('fetch-recorded-2'))
    capture(page,'vue-execution-desktop')
    page.get_by_role('tab',name='最近执行',exact=True).focus();page.keyboard.press('Home')
    check('Vue tab Home selects and focuses workspace',lambda:expect(page.get_by_role('tab',name='工作区',exact=True)).to_be_focused())
    page.keyboard.press('ArrowRight')
    check('Vue tab arrow changes selected pane',lambda:expect(page.get_by_role('tab',name='最近执行',exact=True)).to_have_attribute('aria-selected','true'))
    trace_mode='failed';panel.get_by_role('button',name='刷新',exact=True).click()
    check('Vue failed read removes stale execution events',lambda:expect(panel.locator('.context-events li')).to_have_count(0))
    check('Vue failed read cannot link to old run ID',lambda:expect(panel.get_by_role('link',name='打开执行追溯',exact=False)).to_have_attribute('href','#/agent/trace?sessionId=workspace-session'))
    page.keyboard.press('Escape')
    check('Vue Escape closes work panel',lambda:expect(panel).to_have_count(0))
    check('Vue close restores toggle focus',lambda:expect(page.get_by_role('button',name='展开工作面板',exact=True)).to_be_focused())
    page.set_viewport_size({'width':390,'height':844});page.emulate_media(reduced_motion='reduce')
    page.get_by_role('button',name='展开工作面板',exact=True).click()
    check('Vue mobile panel becomes a drawer',lambda:expect(panel).to_have_class('workspace-context context-floating'))
    check('Vue mobile panel has a dismissible backdrop',lambda:expect(page.get_by_role('button',name='收起工作面板遮罩',exact=True)).to_be_visible())
    check('Vue mobile no horizontal overflow',lambda:no_overflow(page))
    check('Vue mobile work panel covers background question navigator',lambda:ensure(page.evaluate("""() => {const r=document.querySelector('.question-nav-trigger').getBoundingClientRect();return !!document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.closest('#chat-workspace-context')}"""),'question navigator overlays panel'))
    capture(page,'vue-workspace-mobile');panel.get_by_role('button',name='关闭工作面板',exact=True).click()
    check('Vue mobile panel closing retains draft',lambda:expect(draft).to_have_value('保留我的未发送草稿'))

    agent=context.new_page();agent.on('pageerror',lambda error:errors.append(str(error)))
    agent.goto('http://127.0.0.1:5175/');agent.wait_for_load_state('networkidle')
    agent.locator('[data-sender-input]').fill('保留独立聊天草稿')
    agent.get_by_role('button',name='查看助手信息',exact=True).click();info=agent.get_by_role('complementary',name='助手信息')
    check('React workspace shows current session',lambda:expect(info).to_contain_text(session['title']))
    check('React workspace exposes four resource links',lambda:expect(info.locator('.workspace-resource')).to_have_count(4))
    check('React work pane navigates to current session trace',lambda:expect(info.get_by_role('link',name='执行与调研',exact=False)).to_have_attribute('href','http://127.0.0.1:5175/#/agent/trace?sessionId=workspace-session'))
    check('React default workspace has no fabricated model availability count',lambda:expect(info.get_by_role('tabpanel',name='工作区',exact=True)).not_to_contain_text('已安装 4'))
    capture(agent,'react-workspace-desktop')
    agent.get_by_role('tab',name='工作区',exact=True).focus();agent.keyboard.press('End')
    check('React tab End focuses model tab',lambda:expect(agent.get_by_role('tab',name='模型与能力',exact=True)).to_be_focused())
    check('React model tab retains actual configuration',lambda:expect(info).to_contain_text('configured-demo'))
    check('React model pane states configured default is not actual route',lambda:expect(info).to_contain_text('实际调用以执行记录为准'))
    agent.keyboard.press('Escape');agent.get_by_role('button',name='收起会话列表',exact=True).click()
    check('React collapsed sidebar retains shortcut rail',lambda:expect(agent.get_by_role('navigation',name='Agent 快捷导航')).to_be_visible())
    check('React collapsed rail has new-conversation action',lambda:expect(agent.get_by_role('navigation',name='Agent 快捷导航').get_by_role('button',name='新建对话',exact=True)).to_be_visible())
    check('React collapse preserves transcript and draft',lambda:expect(agent.locator('[data-sender-input]')).to_have_value('保留独立聊天草稿'))
    capture(agent,'react-collapsed-rail')
    agent.set_viewport_size({'width':390,'height':844});agent.emulate_media(reduced_motion='reduce');agent.get_by_role('button',name='查看助手信息',exact=True).click();agent.get_by_role('tab',name='工作区',exact=True).click()
    check('React mobile workspace remains accessible',lambda:expect(info.get_by_role('link',name='MCP 工具',exact=False)).to_be_visible())
    check('React mobile no horizontal overflow',lambda:no_overflow(agent))
    capture(agent,'react-workspace-mobile');agent.keyboard.press('Escape')
    check('React mobile Escape restores information toggle focus',lambda:expect(agent.get_by_role('button',name='查看助手信息',exact=True)).to_be_focused())
    check('opening and switching work panes triggers no model or mutations',lambda:ensure(not any(row['method']!='GET' for row in requests),'unexpected mutation'))
    check('both workspaces have no JavaScript errors',lambda:ensure(not errors,str(errors)))
    browser.close()

failed=[row for row in checks if not row['passed']]
(OUT/'results.json').write_text(json.dumps({'checks':checks,'requests':requests,'javascriptErrors':errors},ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'passed':len(checks)-len(failed),'failed':failed,'javascriptErrors':errors},ensure_ascii=False))
if failed:raise SystemExit(1)
