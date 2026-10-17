"""Isolated browser acceptance for Agent trace UI. Start Vite on 3011 and 5175 first."""
import json
import hashlib
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, expect

OUT = Path(__file__).resolve().parents[2] / 'work/agent-trace'
OUT.mkdir(parents=True, exist_ok=True)
checks, errors, requests = [], [], []

def event(seq, kind, **payload):
    return {'sequence': seq, 'type': kind, 'occurredAt': '2026-10-16T12:00:00', 'payload': payload}

base = {'agent': 'supervisor-agent', 'tool': 'delegate_detection_agent', 'callId': 'call-parent', 'scope': 'SINGLE_ENTERPRISE', 'policyVersion': 'role-readonly-v1'}
child = {'agent': 'detection-agent', 'tool': 'search_detection_tasks', 'callId': 'call-child', 'parentCallId': 'call-parent'}
trace = [event(1,'RUN_STARTED',agent='supervisor-agent'), event(2,'MODEL_STARTED',agent='supervisor-agent',elapsedMs=0),
         event(3,'MODEL_COMPLETED',agent='supervisor-agent',elapsedMs=500,durationMs=500,inputTokens=120,outputTokens=35),
         event(4,'AUTHORIZATION_ALLOWED',**base,elapsedMs=510,decision='ALLOW'), event(5,'TOOL_STARTED',**base,elapsedMs=515),
         event(6,'AGENT_STARTED',agent='detection-agent',parentCallId='call-parent',elapsedMs=520),
         event(7,'AUTHORIZATION_ALLOWED',**child,elapsedMs=600,decision='ALLOW'),event(8,'TOOL_STARTED',**child,elapsedMs=605),
         event(9,'TOOL_COMPLETED',**child,elapsedMs=850,durationMs=245,result='SUCCESS'),
         event(10,'TOOL_COMPLETED',**base,elapsedMs=900,durationMs=385,result='SUCCESS'),
         event(11,'AUTHORIZATION_DENIED',agent='supervisor-agent',tool='unregistered',callId='denied',decision='DENY',elapsedMs=910),
         event(12,'COMMAND_RECEIVED',command='/skills',elapsedMs=920), event(13,'RUN_COMPLETED')]
runs = {
    'run-evidence': {'runId':'run-evidence','sessionId':'trace-session','entryPoint':'AGUI','mainAgent':'supervisor-agent','status':'COMPLETED','defaultModel':'configured-default-only','policyVersion':'role-readonly-v1','startedAt':'2026-10-16T12:00:00','endedAt':'2026-10-16T12:00:02','lastSequence':len(trace)},
    'run-long': {'runId':'run-long','sessionId':'trace-session','entryPoint':'CHAT','mainAgent':'history-agent','status':'COMPLETED','lastSequence':130,'startedAt':'2026-10-15T12:00:00'},
    'run-live': {'runId':'run-live','sessionId':'trace-session','entryPoint':'CHAT','mainAgent':'live-agent','status':'RUNNING','lastSequence':1,'startedAt':'2026-10-16T13:00:00'},
}
events = {'run-evidence':trace,'run-long':[event(i,'MODEL_STARTED',agent='history-agent') for i in range(1,131)],'run-live':[event(1,'RUN_STARTED',agent='live-agent')]}
model_primary={'agent':'supervisor-agent','modelRequestId':'model-request-demo','modelId':'custom:primary','provider':'custom','model':'primary','attempt':1}
model_backup={**model_primary,'modelId':'deepseek:backup','provider':'deepseek','model':'backup','attempt':3}
model_events=[event(1,'MODEL_STARTED',agent='supervisor-agent',modelRequestId='model-request-demo'),
              event(2,'MODEL_ATTEMPT_STARTED',**model_primary),event(3,'MODEL_ATTEMPT_ERROR',**model_primary,failureReason='QUOTA',httpStatus=402,durationMs=75),
              event(4,'MODEL_FALLBACK_SELECTED',**model_primary,failureReason='QUOTA',nextModelId='dashscope:cooling'),
              event(5,'MODEL_CANDIDATE_SKIPPED',**{**model_primary,'modelId':'dashscope:cooling','provider':'dashscope','model':'cooling','attempt':2},failureReason='CIRCUIT_OPEN'),
              event(6,'MODEL_ATTEMPT_STARTED',**model_backup),event(7,'MODEL_ATTEMPT_COMPLETED',**model_backup,durationMs=120,firstContentMs=0),
              event(8,'MODEL_COMPLETED',agent='supervisor-agent',modelRequestId='model-request-demo',inputTokens=10,outputTokens=2),event(9,'RUN_COMPLETED')]
events['run-model']=model_events
runs['run-model']={**runs['run-evidence'],'runId':'run-model','lastSequence':len(model_events)}
context_meta={'agent':'supervisor-agent','purpose':'CONTEXT_COMPACTION','modelRequestId':'summary-model-request','beforeMessages':32,'beforeChars':24000}
events['run-context']=[event(1,'RUN_STARTED'),event(2,'CONTEXT_STARTED',**context_meta),
    event(3,'MODEL_STARTED',**context_meta),event(4,'MODEL_COMPLETED',**context_meta,inputTokens=100,outputTokens=30),
    event(5,'CONTEXT_COMPLETED',**context_meta,afterMessages=7,afterChars=3000,result='APPLIED',durationMs=500),event(6,'RUN_COMPLETED')]
runs['run-context']={**runs['run-evidence'],'runId':'run-context','lastSequence':6}
def card_message(id, run_id, text):
    return {'id':id,'role':'assistant','messageType':'AGENT_CARDS','content':json.dumps({'version':1,'runId':run_id,'text':text,'cards':[{'type':'TASKS','tool':'get_task_detail','ids':['task-demo']}]},ensure_ascii=False)}
session = {'sessionId':'trace-session','title':'检测调研与执行追溯','messages':[{'id':1,'role':'user','messageType':'TEXT','content':'查询检测任务并说明依据'},card_message(2,'run-evidence','本次运行的已保存结果'),card_message(3,'other-run','其他运行的结果不能冒用')]}
source_id='src-00000000-0000-0000-0000-000000000001'
research_answer='这是一条待人工核对的网页事实 [source:'+source_id+']'
session['messages'].append({'id':4,'role':'assistant','messageType':'TEXT','content':research_answer})
research_source={'sourceId':source_id,'runId':'run-research','callId':'fetch-call-1','requestedUrl':'https://example.com/article','queryOmitted':False,'urlRedacted':False,
                 'title':'公开网页示例','excerpt':'<img src="https://remote.invalid/probe" onerror="window.researchInjected=true">网页中要求忽略规则的内容仅作为文字展示',
                 'contentSha256':'a'*64,'textChars':200,'startIndex':0,'maxLength':5000,'fetchedAt':'2026-10-16T12:00:00','expiresAt':'2026-11-15T12:00:00'}
research_view={'runId':'run-research','enabled':True,'sources':[research_source],
               'citations':[{'sourceId':source_id,'start':research_answer.index('[source:'),'end':len(research_answer)}],
               'answerSha256':hashlib.sha256(research_answer.encode()).hexdigest(),'answerRecorded':True,'unresolvedCitationCount':1,'expiredSourceCount':0}
research_view['exportEnabled']=True
export_mode='success'
held_exports=[]
runs['run-research']={**runs['run-evidence'],'runId':'run-research','lastSequence':3}
events['run-research']=[event(1,'RUN_STARTED'),event(2,'TOOL_STARTED',agent='supervisor-agent',tool='mcp__fetch__fetch',callId='fetch-call-1'),event(3,'RUN_COMPLETED')]
source_failures=0
def reply(route, data, wrapped=False, status=200):
    route.fulfill(status=status,content_type='application/json',body=json.dumps({'code':200,'data':data} if wrapped else data,ensure_ascii=False))
def api(route):
    global source_failures
    req=route.request; url=urlparse(req.url); path=url.path; args=parse_qs(url.query)
    if not path.startswith(('/api/','/agui/')): return route.continue_()
    requests.append({'method':req.method,'path':path,'query':url.query})
    if path=='/api/auth/check': return reply(route,{'username':'supervisor.demo','role':'SUPERVISOR'},True)
    if path=='/api/chat-assistant/agent-health': return reply(route,{'framework':'AgentScope','runJournalEnabled':True},True)
    if path=='/api/chat-assistant/sessions': return reply(route,[session],True)
    if path=='/api/chat-assistant/session': return reply(route,session,True)
    if path.startswith('/api/chat-assistant/sessions/'):
        return reply(route,{'events':[],'status':'COMPLETED'} if path.endswith('/trace') else session,True)
    if path=='/api/chat-projects': return reply(route,[],True)
    if path=='/api/agent/actions': return reply(route,[])
    if path=='/api/agent/cards/resolve': return reply(route,{'cards':[]})
    if path=='/api/agent/runs': return reply(route,[runs['run-long'],runs['run-live']])
    if path.startswith('/api/agent/runs/'):
        parts=path.split('/'); rid=parts[4]
        if rid not in runs:return reply(route,{'message':'该运行不存在或无访问权限'},status=404)
        if path.endswith('/sources/export'):
            assert req.method=='POST' and req.post_data_json=={'confirmed':True} and req.headers.get('x-agent-action')=='export'
            if export_mode=='hold':
                held_exports.append(route)
                return
            if export_mode=='failed':return reply(route,{'message':'导出审计暂不可用'},status=503)
            if export_mode=='limited':return route.fulfill(status=429,content_type='application/json',headers={'Retry-After':'37','Cache-Control':'no-store'},body=json.dumps({'message':'PRIVATE_SERVER_TEXT'}))
            return export_reply(route,bad_hash=export_mode=='bad-hash')
        if path.endswith('/sources'):
            if rid=='run-research':
                if source_failures:
                    source_failures-=1
                    return reply(route,{'message':'来源暂不可用'},status=503)
                return reply(route,research_view)
            return reply(route,{'runId':rid,'enabled':False,'sources':[],'citations':[],'answerSha256':None,'answerRecorded':False,'unresolvedCitationCount':0,'expiredSourceCount':0})
        if path.endswith('/events'):
            after=int(args.get('after',['0'])[0]);return reply(route,[row for row in events[rid] if row['sequence']>after][:100])
        if path.endswith('/cancel'):
            assert req.headers.get('x-agent-action')=='cancel'
            runs[rid].update(status='CANCELLED',lastSequence=2)
            events[rid].append(event(2,'RUN_CANCELLED'))
        return reply(route,runs[rid])
    if path=='/agui/catalog':return reply(route,{'role':'SUPERVISOR','mainAgent':'supervisor-agent','agents':[]})
    if path=='/agui/models':return reply(route,{'models':[]})
    if path=='/api/agent/commands':return reply(route,{'skills':[]})
    return reply(route,[])

def export_reply(route,bad_hash=False):
    eid='00000000-0000-0000-0000-000000000007'
    body=json.dumps({'version':1,'exportId':eid,'exportedAt':'2026-10-16T12:00:00Z','evidence':research_view,'limitations':['未受信任片段']},ensure_ascii=False)
    route.fulfill(status=200,content_type='application/json',body=body,headers={
        'X-Export-Id':eid,'X-Content-SHA256':'0'*64 if bad_hash else hashlib.sha256(body.encode()).hexdigest(),'Cache-Control':'no-store'})
def check(name, action):
    try: action(); checks.append({'name':name,'passed':True})
    except Exception as error: checks.append({'name':name,'passed':False,'error':str(error)})
def capture(page,name):
    page.wait_for_timeout(300);page.screenshot(path=str(OUT/(name+'.png')),full_page=True)
def no_overflow(page):
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
def ensure(condition, message):
    assert condition, message
def no_generations(items):
    assert not any(item['path'] in ('/agui/run','/api/chat-assistant/messages','/api/chat-assistant/messages/stream') for item in items)
def no_errors(items):
    assert not items, items
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1680,'height':1050},accept_downloads=True)
    context.route('**/api/**',api);context.route('**/agui/**',api)
    context.on('page',lambda page:page.on('pageerror',lambda error:errors.append(str(error))))
    page=context.new_page()
    page.goto('http://127.0.0.1:3011/#/agent/trace?runId=run-evidence');page.wait_for_load_state('networkidle')
    check('direct link loads an owned run outside the first history page',lambda:expect(page.locator('.trace-copy-id')).to_have_text('run-evidence'))
    check('timeline shows every recorded event',lambda:expect(page.locator('.trace-event')).to_have_count(13))
    check('export is enabled for complete persisted events',lambda:expect(page.get_by_role('button',name='导出轨迹')).to_be_enabled())
    capture(page,'trace-desktop')
    page.get_by_role('button',name='查看事件 8 开始调用工具').click()
    check('event inspector shows correlated parent call',lambda:expect(page.get_by_role('complementary',name='事件详情')).to_contain_text('call-parent'))
    check('tool completion uses recorded duration',lambda:expect(page.locator('.trace-inspector')).to_contain_text('245 ms'))
    check('default model is explicitly a configuration value',lambda:expect(page.locator('.trace-inspector')).to_contain_text('不表示该事件实际使用'))
    capture(page,'trace-inspector-desktop')
    page.get_by_role('button',name='delegate_detection_agent',exact=True).click()
    check('parent call navigation selects recorded authorization event',lambda:expect(page.locator('.trace-inspector h3')).to_contain_text('#4'))
    page.keyboard.press('Escape')
    check('inspector Escape returns focus to the event row',lambda:expect(page.get_by_role('button',name='查看事件 8 开始调用工具')).to_be_focused())
    page.get_by_role('button',name='权限核验',exact=True).click()
    check('permission filter matches only recorded authorization events',lambda:expect(page.locator('.trace-event')).to_have_count(3))
    page.get_by_role('textbox',name='搜索事件').fill('denied')
    check('search matches a call ID within the current filter',lambda:expect(page.locator('.trace-event')).to_have_count(1))
    page.get_by_role('textbox',name='搜索事件').fill('')
    page.get_by_role('button',name='全部事件',exact=True).click()
    page.get_by_role('button',name='关联结果',exact=True).click()
    check('results show only cards with the selected run ID',lambda:expect(page.locator('.trace-results .agent-result')).to_have_count(1))
    check('results do not borrow another run answer',lambda:expect(page.locator('.trace-results')).not_to_contain_text('其他运行的结果不能冒用'))
    check('web evidence limitations are visible',lambda:expect(page.locator('.trace-results')).to_contain_text('不能作为具体网页或结论的证据'))
    capture(page,'trace-results-desktop')
    page.get_by_role('button',name='会话上下文',exact=True).click()
    check('session context is labeled as possibly containing multiple runs',lambda:expect(page.get_by_role('region',name='会话上下文')).to_contain_text('可能包含多次运行'))
    page.get_by_role('button',name='原始事件',exact=True).click()
    check('raw metadata stays readable',lambda:expect(page.locator('.trace-json')).to_contain_text('parentCallId'))
    with page.expect_download() as download:
        page.get_by_role('button',name='导出轨迹').click()
    artifact=download.value;artifact.save_as(str(OUT/'trace-export.json'))
    payload=json.loads((OUT/'trace-export.json').read_text('utf8'))
    check('export contains a complete run and ordered events',lambda:ensure(payload['run']['runId']=='run-evidence' and payload['complete'] is True and len(payload['events'])==13 and 'messages' not in payload,'incorrect export content'))
    page.locator('.trace-run').filter(has_text='run-long').click()
    check('incomplete event pages disable export',lambda:expect(page.get_by_role('button',name='导出轨迹')).to_be_disabled())
    page.get_by_role('button',name='补读后续事件').click()
    check('backfill makes full trace exportable',lambda:expect(page.get_by_role('button',name='导出轨迹')).to_be_enabled())
    page.get_by_role('button',name='执行过程',exact=True).click()
    check('long timelines paginate rendered rows',lambda:expect(page.locator('.trace-event')).to_have_count(50))
    page.locator('.el-pagination .el-pager').get_by_text('2',exact=True).click()
    check('timeline second page starts from event 51',lambda:expect(page.locator('.trace-event').first).to_have_attribute('aria-label','查看事件 51 发起模型请求'))
    page.locator('.trace-run').filter(has_text='run-live').click()
    page.get_by_role('button',name='取消运行',exact=True).click()
    check('cancellation requires confirmation before POST',lambda:expect(page.get_by_role('button',name='确认取消运行')).to_be_visible())
    assert not any(r['path'].endswith('/cancel') for r in requests)
    page.get_by_role('button',name='确认取消运行',exact=True).click()
    check('confirmed cancellation refreshes persisted status',lambda:expect(page.locator('.trace-run-toolbar')).to_contain_text('已取消'))
    page.goto('http://127.0.0.1:3011/#/agent/trace?runId=not-owned');page.wait_for_load_state('networkidle')
    check('forbidden direct link does not fall back to latest run',lambda:expect(page.locator('.trace-copy-id')).to_have_count(0))
    check('forbidden direct link clears event rows',lambda:expect(page.locator('.trace-event')).to_have_count(0))
    page.goto('http://127.0.0.1:3011/#/agent/trace?runId=run-evidence');page.wait_for_load_state('networkidle')
    page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300)
    check('mobile trace no horizontal document overflow',lambda:no_overflow(page))
    check('mobile trace process remains visible',lambda:expect(page.locator('.trace-main')).to_be_visible())
    capture(page,'trace-mobile')
    page.get_by_role('button',name='展开运行列表').click()
    check('mobile history can be opened',lambda:expect(page.get_by_role('complementary',name='运行历史')).to_be_visible())
    page.keyboard.press('Escape')
    check('mobile history Escape restores toggle focus',lambda:expect(page.get_by_role('button',name='展开运行列表')).to_be_focused())
    page.get_by_role('button',name='查看事件 8 开始调用工具').click()
    check('mobile inspector stays accessible',lambda:expect(page.get_by_role('complementary',name='事件详情')).to_be_visible())
    capture(page,'trace-inspector-mobile');page.keyboard.press('Escape')
    page.emulate_media(reduced_motion='reduce')
    check('reduced motion disables event transitions',lambda:ensure(page.locator('.trace-event').first.evaluate('el=>parseFloat(getComputedStyle(el).transitionDuration)')<=.001,'motion duration too long'))
    page.get_by_role('link',name='返回会话').click();page.wait_for_load_state('networkidle')
    check('return to conversation opens the recorded session',lambda:expect(page.locator('.chat-header-title')).to_have_text(session['title']))
    check('chat offers trace navigation',lambda:expect(page.get_by_role('link',name='查看执行追溯')).to_have_attribute('href','#/agent/trace?sessionId=trace-session'))
    agent=context.new_page();agent.goto('http://127.0.0.1:5175/',timeout=120000);agent.wait_for_load_state('networkidle')
    check('independent Agent offers same-session trace navigation',lambda:expect(agent.get_by_role('link',name='执行追溯',exact=True)).to_have_attribute('href','http://127.0.0.1:5175/#/agent/trace?sessionId=trace-session'))
    page.set_viewport_size({'width':1680,'height':1050})
    page.goto('http://127.0.0.1:3011/#/agent/trace?runId=run-model');page.wait_for_load_state('networkidle')
    page.get_by_role('button',name='模型路由',exact=True).click()
    check('model route groups three candidates into one explicit request',lambda:ensure(page.locator('.trace-model-request').count()==1 and page.locator('.trace-model-attempt').count()==3,'incorrect candidate grouping'))
    check('model route shows quota failure and HTTP code',lambda:expect(page.get_by_role('region',name='模型路由')).to_contain_text('额度或余额不足 · HTTP 402'))
    check('cooling model is marked skipped without a request',lambda:expect(page.locator('.trace-model-attempt').nth(1)).to_contain_text('已跳过，未请求'))
    check('backup displays actual provider and explicit zero first content time',lambda:expect(page.locator('.trace-model-attempt').nth(2)).to_contain_text('首段内容 0 ms'))
    check('summary distinguishes logical requests and candidates',lambda:expect(page.locator('.trace-metrics')).to_contain_text('2 次候选调用 · 1 次备用选择'))
    capture(page,'model-route-desktop')
    page.get_by_role('button',name='查看候选 3 deepseek:backup',exact=True).click()
    check('model inspector exposes provider and request correlation',lambda:expect(page.locator('.trace-inspector')).to_contain_text('model-request-demo'))
    check('model inspector links only same-request events',lambda:expect(page.locator('.trace-inspector .trace-related-event')).to_have_count(8))
    page.keyboard.press('Escape')
    page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300)
    check('mobile model route has no horizontal overflow',lambda:no_overflow(page))
    check('mobile model route remains operable',lambda:expect(page.get_by_role('button',name='查看候选 3 deepseek:backup',exact=True)).to_be_visible())
    capture(page,'model-route-mobile')
    page.goto('http://127.0.0.1:3011/#/agent/trace?runId=run-evidence');page.wait_for_load_state('networkidle')
    page.get_by_role('button',name='模型路由',exact=True).click()
    check('legacy model records show missing metadata instead of configured default',lambda:expect(page.get_by_role('region',name='模型路由')).to_contain_text('不从默认配置推断'))
    page.set_viewport_size({'width':1680,'height':1050})
    page.goto('http://127.0.0.1:3011/#/agent/trace?runId=run-research');page.wait_for_load_state('networkidle')
    page.get_by_role('button',name='调研来源',exact=True).click()
    check('research sources belong to selected run',lambda:expect(page.locator('.research-source')).to_have_count(1))
    check('research source includes hash and capture time',lambda:expect(page.locator('.research-source')).to_contain_text('2026-10-16 12:00:00'))
    check('citation matches exact persisted answer',lambda:expect(page.locator('.research-reference')).to_have_text('[来源 1]'))
    check('unknown citation is flagged without fabricating evidence',lambda:expect(page.get_by_role('region',name='调研来源')).to_contain_text('1 个回答标记未匹配'))
    check('source excerpts render HTML as plain text',lambda:ensure(page.locator('.research-excerpt img').count()==0 and not page.evaluate('window.researchInjected===true'),'untrusted excerpt executed'))
    check('external source links send no referrer or opener',lambda:ensure(page.get_by_role('link',name='打开记录地址').get_attribute('rel')=='noopener noreferrer' and page.get_by_role('link',name='打开记录地址').get_attribute('referrerpolicy')=='no-referrer','unsafe source link'))
    page.locator('.research-reference').click()
    check('citation navigation focuses the actual source card',lambda:expect(page.locator('.research-source')).to_be_focused())
    page.get_by_role('button',name='查看抓取调用',exact=True).click()
    check('research source navigates to its recorded Fetch call',lambda:expect(page.locator('.trace-inspector')).to_contain_text('fetch-call-1'))
    page.keyboard.press('Escape')
    capture(page,'research-sources-desktop')
    downloads=[]
    page.on('download',lambda download:downloads.append(download))
    def export_requests():return [row for row in requests if row['path'].endswith('/sources/export')]
    export_count=len(export_requests())
    page.get_by_role('button',name='导出来源',exact=True).click()
    dialog=page.get_by_role('dialog',name='导出本次调研来源')
    check('export confirmation explains private content and downloaded-copy retention',lambda:expect(dialog).to_contain_text('服务端到期清理不会删除已下载副本'))
    check('opening confirmation does not request an export',lambda:ensure(len(export_requests())==export_count,'export before confirmation'))
    capture(page,'research-export-confirm-desktop')
    dialog.get_by_role('button',name='取消',exact=True).click()
    expect(dialog).not_to_be_visible()
    check('cancelled source export has no request',lambda:ensure(len(export_requests())==export_count,'cancel triggered export'))
    page.get_by_role('button',name='导出来源',exact=True).click()
    with page.expect_download() as download_info:
        dialog.get_by_role('button',name='确认并保存 JSON',exact=True).click()
    download=download_info.value
    download.save_as(OUT/'research-export.json')
    exported=json.loads((OUT/'research-export.json').read_text(encoding='utf8'))
    check('confirmed export uses safe generated filename and current run',lambda:ensure(download.suggested_filename=='research-00000000-0000-0000-0000-000000000007.json' and exported['evidence']['runId']=='run-research','wrong export'))
    check('download preserves untrusted text as JSON without HTML execution',lambda:ensure(exported['evidence']['sources'][0]['excerpt']==research_source['excerpt'] and not page.evaluate('window.researchInjected===true'),'unsafe export'))
    check('download receipt shows the exact exported byte hash',lambda:expect(page.get_by_role('status').filter(has_text='已发起文件保存')).to_contain_text(hashlib.sha256((OUT/'research-export.json').read_bytes()).hexdigest()))
    export_mode='failed'
    page.get_by_role('button',name='导出来源',exact=True).click();dialog.get_by_role('button',name='确认并保存 JSON',exact=True).click()
    check('failed export states uncertain outcome and does not automatically retry',lambda:expect(page.get_by_role('alert').filter(has_text='不会自动重试')).to_be_visible())
    request_count=len(export_requests());page.wait_for_timeout(450)
    check('failed audit response does not save a file or retry',lambda:ensure(len(downloads)==1 and len(export_requests())==request_count,'failure retried or downloaded'))
    export_mode='limited'
    page.get_by_role('button',name='导出来源',exact=True).click();dialog.get_by_role('button',name='确认并保存 JSON',exact=True).click()
    check('rate-limited export explains bounded retry time without exposing server text',lambda:expect(page.get_by_role('alert').filter(has_text='请等待约 37 秒')).to_be_visible())
    request_count=len(export_requests());page.wait_for_timeout(450)
    check('rate-limited response never downloads or retries automatically',lambda:ensure(len(downloads)==1 and len(export_requests())==request_count and 'PRIVATE_SERVER_TEXT' not in page.locator('body').inner_text(),'limit bypass or server text leak'))
    capture(page,'research-export-rate-limit-desktop')
    export_mode='bad-hash'
    page.get_by_role('button',name='导出来源',exact=True).click();dialog.get_by_role('button',name='确认并保存 JSON',exact=True).click()
    check('hash mismatch blocks download',lambda:expect(page.get_by_role('alert').filter(has_text='不会自动重试')).to_be_visible())
    check('corrupt file was not saved',lambda:ensure(len(downloads)==1,'corrupt file downloaded'))
    export_mode='hold'
    page.get_by_role('button',name='导出来源',exact=True).click();dialog.get_by_role('button',name='确认并保存 JSON',exact=True).click()
    page.wait_for_timeout(100)
    check('pending export disables repeat confirmation',lambda:expect(dialog.get_by_role('button',name='确认并保存 JSON',exact=True)).to_be_disabled())
    page.evaluate("window.location.hash='/agent/trace?runId=run-evidence'")
    expect(page.locator('.trace-copy-id')).to_have_text('run-evidence')
    for held in held_exports:export_reply(held)
    page.wait_for_timeout(400)
    check('switching runs discards a late export without saving',lambda:ensure(len(downloads)==1,'stale run downloaded'))
    export_mode='success'
    page.goto('http://127.0.0.1:3011/#/agent/trace?runId=run-research');page.wait_for_load_state('networkidle')
    page.get_by_role('button',name='调研来源',exact=True).click()
    research_view['answerSha256']='b'*64
    page.get_by_role('button',name='刷新记录',exact=True).click()
    check('mismatching saved answer does not display a guessed citation location',lambda:expect(page.get_by_role('region',name='调研来源')).to_contain_text('尚未找到摘要完全匹配'))
    research_view['answerSha256']=hashlib.sha256(research_answer.encode()).hexdigest()
    research_source.update(queryOmitted=True,urlRedacted=True)
    page.get_by_role('button',name='刷新记录',exact=True).click()
    check('redacted target cannot be opened as an exact fetched page',lambda:expect(page.get_by_role('link',name='打开记录地址')).to_have_count(0))
    source_failures=1
    page.get_by_role('button',name='刷新记录',exact=True).click()
    check('source read failure clears stale excerpt and offers retry',lambda:expect(page.locator('.research-source')).to_have_count(0))
    page.get_by_role('button',name='重试读取来源',exact=True).click()
    check('source read retry does not rerun Fetch',lambda:expect(page.locator('.research-source')).to_have_count(1))
    page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300)
    check('mobile research sources have no horizontal document overflow',lambda:no_overflow(page))
    check('mobile research source remains readable',lambda:expect(page.locator('.research-source')).to_be_visible())
    capture(page,'research-sources-mobile')
    page.get_by_role('button',name='导出来源',exact=True).click()
    check('mobile export confirmation stays within document width',lambda:no_overflow(page))
    check('mobile export confirmation action remains visible',lambda:expect(page.get_by_role('dialog',name='导出本次调研来源').get_by_role('button',name='确认并保存 JSON',exact=True)).to_be_visible())
    capture(page,'research-export-confirm-mobile')
    page.get_by_role('dialog',name='导出本次调研来源').get_by_role('button',name='取消',exact=True).click()
    page.goto('http://127.0.0.1:3011/#/agent/trace?runId=run-evidence');page.wait_for_load_state('networkidle')
    page.get_by_role('button',name='调研来源',exact=True).click()
    check('uncollected history explicitly shows disabled collection',lambda:expect(page.get_by_role('region',name='调研来源')).to_contain_text('旧记录不会补造来源'))
    check('disabled source collection offers no export',lambda:expect(page.get_by_role('button',name='导出来源',exact=True)).to_have_count(0))
    page.set_viewport_size({'width':1680,'height':1050})
    page.goto('http://127.0.0.1:3011/#/agent/trace?runId=run-context');page.wait_for_load_state('networkidle')
    page.get_by_role('button',name='执行过程',exact=True).click()
    page.get_by_role('button',name='查看事件 5 上下文压缩已应用',exact=True).click()
    check('context inspector identifies summary request purpose',lambda:expect(page.locator('.trace-inspector')).to_contain_text('上下文摘要'))
    check('context inspector displays recorded before and after sizes',lambda:ensure('压缩前消息数' in page.locator('.trace-inspector').inner_text() and '压缩后字符数' in page.locator('.trace-inspector').inner_text(),'missing context counts'))
    check('context trace has no summary or conversation payload',lambda:ensure('PRIVATE_SUMMARY' not in page.locator('.trace-inspector').inner_text(),'summary leaked'))
    capture(page,'context-compaction-desktop')
    page.keyboard.press('Escape')
    page.get_by_role('button',name='模型路由',exact=True).click()
    check('model route distinguishes compaction request purpose',lambda:expect(page.locator('.trace-model-request h4')).to_contain_text('上下文摘要'))
    page.get_by_role('button',name='执行过程',exact=True).click();page.set_viewport_size({'width':390,'height':844})
    page.get_by_role('button',name='查看事件 5 上下文压缩已应用',exact=True).click()
    check('mobile context inspector fits viewport',lambda:no_overflow(page))
    check('mobile context inspector remains readable',lambda:expect(page.locator('.trace-inspector')).to_contain_text('压缩前消息数'))
    capture(page,'context-compaction-mobile')
    check('no model requests are triggered by trace reads',lambda: no_generations(requests))
    check('no JavaScript page errors',lambda: no_errors(errors))
    browser.close()

failed=[c for c in checks if not c['passed']]
(OUT/'results.json').write_text(json.dumps({'mode':'isolated API fixtures','checks':checks,'requests':requests,'javascriptErrors':errors},ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'passed':len(checks)-len(failed),'failed':failed,'javascriptErrors':errors},ensure_ascii=False))
if failed:raise SystemExit(1)
