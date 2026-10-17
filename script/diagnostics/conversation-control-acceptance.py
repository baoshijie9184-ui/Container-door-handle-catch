"""Both conversation control UIs, shared isolated APIs, Vite 3011 and 5175."""
import json,uuid
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright,expect
OUT=Path(__file__).resolve().parents[2]/'work/conversation-control'
OUT.mkdir(parents=True,exist_ok=True)
checks,errors,requests=[],[],[]
session={'sessionId':'control-session','title':'集装箱门把手检测调研','messages':[{'id':1,'role':'user','messageType':'TEXT','content':'核对本次检测任务'},{'id':2,'role':'assistant','messageType':'TEXT','content':'已完成上一轮查询。'}]}
run={'sessionId':session['sessionId'],'runId':str(uuid.uuid4()),'phase':'RUNNING','revision':0,'local':True,'text':'正在核对当前任务的检测结果，等待下一执行步骤。'}
inputs=[{'id':str(uuid.uuid4()),'mode':'NEXT_TURN','status':'QUEUED','revision':0,'content':'<img src=x onerror="window.controlInjected=true"> 当前任务结束后整理报告'}]
fail_next=False
pause_reads=0
def reply(route,data,raw=True,status=200):route.fulfill(status=status,content_type='application/json',body=json.dumps(data if raw else {'code':200,'data':data},ensure_ascii=False))
def api(route):
 global fail_next,pause_reads
 req=route.request;path=urlparse(req.url).path
 if not path.startswith(('/api/','/agui/')):return route.continue_()
 requests.append({'method':req.method,'path':path,'body':req.post_data_json if req.method=='POST' else None})
 (OUT/'requests-debug.json').write_text(json.dumps(requests,ensure_ascii=False,indent=2),encoding='utf8')
 if path=='/api/auth/check':return reply(route,{'username':'supervisor.demo','role':'SUPERVISOR'},False)
 if path=='/api/chat-assistant/sessions':return reply(route,[session],False)
 if path.startswith('/api/chat-assistant/sessions/') or path=='/api/chat-assistant/session':return reply(route,session,False)
 if path.endswith('/agent-health'):return reply(route,{'framework':'AgentScope','mode':'CONFIRMABLE','runJournalEnabled':True},False)
 if path=='/api/agent/actions':return reply(route,[])
 if path=='/api/agent/commands':return reply(route,{'enabled':True,'skills':[]})
 if path=='/agui/catalog':return reply(route,{'role':'SUPERVISOR','mainAgent':'supervisor-main','agents':[]})
 if path=='/agui/models':return reply(route,{'models':[]})
 if path=='/api/agent/conversations/capabilities':return reply(route,{'enabled':True,'pauseMode':'LIVE_SAFE_BOUNDARY','maxRunSeconds':1800})
 if path.endswith('/control') and path.startswith('/api/agent/conversations/'):
  if req.method=='POST':
   body=req.post_data_json
   assert req.headers.get('x-agent-action')=='conversation-control'
   if body['revision']!=run['revision']:return reply(route,{'message':'状态已变化'},status=409)
   if body['action']=='pause':run.update(phase='PAUSE_REQUESTED',revision=run['revision']+1);pause_reads=0
   elif body['action']=='resume':run.update(phase='RUNNING',revision=run['revision']+1)
   elif body['action']=='cancel':assert body['confirmed'];run.update(phase='IDLE',runId=None,text='',local=False,revision=run['revision']+1)
   return reply(route,run)
  if run['phase']=='PAUSE_REQUESTED':
   pause_reads+=1
   if pause_reads>=2:run.update(phase='PAUSED',revision=run['revision']+1)
  return reply(route,{'run':run,'inputs':list(reversed(inputs))})
 if '/api/agent/conversations/' in path and '/inputs' in path:
  body=req.post_data_json;assert req.method=='POST' and req.headers.get('x-agent-action')=='conversation-control'
  if path.endswith('/inputs'):
   existing=next((item for item in inputs if item['id']==body['id']),None)
   if existing:return reply(route,existing)
   item={'id':body['id'],'mode':body['mode'],'content':body['content'],'status':'QUEUED','revision':0};inputs.append(item)
   if fail_next:fail_next=False;return reply(route,{'message':'PRIVATE_SERVER_DETAILS'},status=503)
   return reply(route,item)
  promoting=path.endswith('/steer')
  item=next(item for item in inputs if item['id']==path.split('/')[-2 if promoting else -1])
  if body['revision']!=item['revision']:return reply(route,{'message':'conflict'},status=409)
  if promoting:
   if body['runId']!=run['runId']:return reply(route,{'message':'conflict'},status=409)
   item.update(mode='NEXT_STEP',revision=item['revision']+1);return reply(route,item)
  item.update(revision=item['revision']+1,content=body.get('content') or '',status='CANCELLED' if body.get('content') is None else 'QUEUED');return reply(route,item)
 return reply(route,[],False)
def check(name,action):
 try:action();checks.append({'name':name,'passed':True})
 except Exception as error:checks.append({'name':name,'passed':False,'error':str(error)})
def ensure(value,message):assert value,message
def capture(page,name):page.wait_for_timeout(300);page.screenshot(path=str(OUT/(name+'.png')),full_page=True)
def input_posts():return [row for row in requests if row['method']=='POST' and row['path'].endswith('/inputs')]
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1600,'height':1050});context.route('**/api/**',api);context.route('**/agui/**',api)
 page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)));page.goto('http://127.0.0.1:3011/#/agent/chat');page.wait_for_load_state('networkidle')
 panel=page.get_by_role('region',name='Agent 执行控制');expect(panel).to_be_visible();panel.get_by_text('任务操作',exact=True).click()
 check('Vue control reflects the actual live phase',lambda:expect(panel.get_by_role('status')).to_have_text('执行中'))
 check('Vue partial reply is shown in the transcript',lambda:expect(page.get_by_text(run['text'],exact=True)).to_be_visible())
 check('pending input renders markup as plain text',lambda:ensure(panel.locator('img').count()==0 and not page.evaluate('window.controlInjected===true'),'HTML executed'))
 page.get_by_role('button',name='暂停任务',exact=True).click()
 check('pause request is not mislabelled as already paused',lambda:expect(panel.get_by_role('status')).to_have_text('等待安全切点暂停'))
 expect(panel.get_by_role('status')).to_have_text('已暂停',timeout=6000)
 check('pause completion comes from the returned server phase',lambda:expect(panel.get_by_role('button',name='继续任务')).to_be_visible())
 capture(page,'vue-paused-desktop')
 draft=page.get_by_role('textbox',name='聊天消息或技能命令');draft.fill('排队的第二个问题');draft.press('Enter')
 check('Vue can submit while the current task is paused',lambda:expect(panel.locator('li').filter(has_text='排队的第二个问题')).to_be_visible())
 check('ordinary input uses next-turn delivery',lambda:ensure(input_posts()[-1]['body']['mode']=='NEXT_TURN','wrong delivery'))
 row=panel.locator('li').filter(has_text='当前任务结束后整理报告');row.get_by_role('button',name='更多消息操作',exact=True).click()
 page.get_by_role('menuitem',name='编辑消息',exact=True).click()
 dialog=page.get_by_role('dialog',name='编辑待处理消息');dialog.get_by_role('textbox',name='待处理消息内容').fill('修改后的待发消息');dialog.get_by_role('button',name='保存修改').click()
 check('editing updates the versioned pending message',lambda:expect(panel.locator('li').filter(has_text='修改后的待发消息')).to_be_visible())
 panel.locator('li').filter(has_text='修改后的待发消息').get_by_role('button',name='撤回消息').click()
 check('withdrawal removes pending content and shows the receipt',lambda:expect(panel).to_contain_text('已撤回'))
 row=panel.locator('li').filter(has_text='排队的第二个问题');old_id=next(item['id'] for item in inputs if item['content']=='排队的第二个问题');before=len(input_posts());row.get_by_role('button',name='引导',exact=True).click()
 check('Vue row steering changes delivery on the original message',lambda:expect(row).to_contain_text('等待引导'))
 check('row steering does not create another input',lambda:ensure(len(input_posts())==before and any(req['path'].endswith('/'+old_id+'/steer') and req['body']['runId']==run['runId'] for req in requests if req['method']=='POST'),'duplicate or wrong promotion'))
 row.get_by_role('button',name='更多消息操作').click();page.get_by_role('menuitem',name='关闭排队',exact=True).click()
 check('Vue more menu closes queue without deleting pending messages',lambda:expect(panel).to_contain_text('消息排队已关闭'))
 draft.fill('关闭排队时的后续问题');draft.press('Enter');check('closed queue restores an unsent draft',lambda:expect(draft).to_have_value('关闭排队时的后续问题'))
 check('closed queue does not post another message',lambda:ensure(len(input_posts())==before,'closed queue still posted'))
 panel.get_by_role('button',name='开启排队').click();draft.fill('')
 panel.get_by_label('发送方式',exact=True).select_option('NEXT_STEP');draft.fill('只关注缺陷来源，不执行新的业务修改');draft.press('Enter')
 check('Vue steering is an explicit next-step input',lambda:expect(panel.locator('li').filter(has_text='只关注缺陷来源')).to_be_visible())
 check('steering targets the same active conversation',lambda:ensure(input_posts()[-1]['body']['mode']=='NEXT_STEP' and '/control-session/' in input_posts()[-1]['path'],'wrong steering'))
 fail_next=True;draft.fill('网络结果不确定的问题');draft.press('Enter')
 check('unknown submission restores the composer draft',lambda:expect(draft).to_have_value('网络结果不确定的问题'))
 check('unknown submission shows a safe error',lambda:expect(panel.get_by_role('alert')).to_contain_text('不会自动重试'))
 before=len(input_posts());page.wait_for_timeout(400)
 check('unknown submission is not retried automatically',lambda:ensure(len(input_posts())==before,'automatic write retry'))
 draft.press('Enter');expect(draft).to_have_value('')
 check('manual retry retains the request ID',lambda:ensure(input_posts()[-1]['body']['id']==input_posts()[-2]['body']['id'],'request ID changed'))
 page.set_viewport_size({'width':390,'height':844});capture(page,'vue-paused-mobile')
 check('Vue mobile controls fit the viewport',lambda:ensure(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'overflow'))
 nav=page.get_by_role('button',name='查看历史提问');check('Vue mobile history navigation is in the control toolbar',lambda:expect(panel.get_by_role('button',name='查看历史提问')).to_be_visible())
 nav.click();history=page.get_by_role('region',name='当前会话历史提问');expect(history).to_be_visible()
 check('inline history popover stays within the mobile viewport',lambda:ensure(history.bounding_box()['x']>=0 and history.bounding_box()['x']+history.bounding_box()['width']<=391,'history overflow'))
 page.keyboard.press('Escape');check('inline history Escape returns keyboard focus',lambda:expect(nav).to_be_focused())
 agent=context.new_page();agent.on('pageerror',lambda error:errors.append(str(error)));agent.goto('http://127.0.0.1:5175/');agent.wait_for_load_state('networkidle')
 react=agent.get_by_role('region',name='Agent 执行控制');expect(react).to_be_visible();react.get_by_text('任务操作',exact=True).click()
 check('React expanded session sidebar keeps its intended desktop width',lambda:ensure(agent.locator('.session-sidebar').bounding_box()['width']>=240,'sidebar compressed'))
 check('React control panel follows the conversation content width',lambda:ensure(react.bounding_box()['width']<=830,'controls stretched across workspace'))
 check('React sees the same paused run and pending messages',lambda:expect(react.get_by_role('status')).to_have_text('已暂停'))
 agent.get_by_role('button',name='继续任务',exact=True).click()
 check('React resumes the same server-side execution',lambda:expect(react.get_by_role('status')).to_have_text('执行中'))
 check('Vue observes the resume from the other entry',lambda:expect(panel.get_by_role('status')).to_have_text('执行中',timeout=5000))
 react.get_by_label('发送方式',exact=True).select_option('NEXT_TURN');sender=agent.locator('[data-sender-input]');sender.fill('独立入口待发消息');sender.press('Enter')
 row=react.locator('li').filter(has_text='独立入口待发消息');expect(row).to_be_visible();before=len(input_posts());row.get_by_role('button',name='引导',exact=True).click()
 check('React row steering promotes without a second submission',lambda:(expect(row).to_contain_text('等待引导'),ensure(len(input_posts())==before,'duplicate')))
 row.get_by_role('button',name='更多消息操作').click();agent.get_by_role('menuitem',name='关闭排队',exact=True).click()
 check('React more menu exposes close queue and retains rows',lambda:(expect(react).to_contain_text('消息排队已关闭'),expect(row).to_be_visible()))
 react.get_by_role('button',name='开启排队').click()
 react.get_by_label('发送方式',exact=True).select_option('NEXT_STEP');sender=agent.locator('[data-sender-input]');sender.fill('来自独立入口的补充要求');sender.press('Enter')
 check('React steering uses the shared controlled input endpoint',lambda:expect(react.locator('li').filter(has_text='来自独立入口')).to_be_visible())
 capture(agent,'react-running-desktop')
 agent.set_viewport_size({'width':390,'height':844});capture(agent,'react-running-mobile')
 check('React mobile controls fit the viewport',lambda:ensure(agent.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'overflow'))
 agent.get_by_role('button',name='取消任务',exact=True).click();confirm=agent.get_by_role('dialog');check('cancel confirmation explains queued-message retention',lambda:expect(confirm).to_contain_text('排队消息保留'))
 confirm.get_by_role('button',name='确认取消',exact=True).click();expect(react.get_by_role('status')).to_have_text('空闲')
 check('task cancellation does not silently delete pending messages',lambda:ensure(any(item['status']=='QUEUED' for item in inputs),'queue lost'))
 check('controlled mode never invokes a second direct streaming execution',lambda:ensure(not any(row['method']=='POST' and row['path'] in ('/agui/run','/api/chat-assistant/messages/stream') for row in requests),'direct execution also invoked'))
 check('no JavaScript errors or raw private server details',lambda:ensure(not errors and 'PRIVATE_SERVER_DETAILS' not in page.locator('body').inner_text(),'UI error or data leak'))
 browser.close()
failed=[item for item in checks if not item['passed']]
(OUT/'results.json').write_text(json.dumps({'checks':checks,'javascriptErrors':errors,'requests':requests},ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'passed':len(checks)-len(failed),'failed':failed,'javascriptErrors':errors},ensure_ascii=False))
if failed:raise SystemExit(1)
