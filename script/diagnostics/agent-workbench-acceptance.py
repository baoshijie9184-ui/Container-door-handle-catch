"""Isolated workbench UI acceptance; no cloud connection and no paid model requests."""
import json,uuid
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[2]
namespace={'__file__':str(ROOT/'script/diagnostics/conversation-control-acceptance.py')}
exec((ROOT/'script/diagnostics/conversation-control-acceptance.py').read_text(encoding='utf8').split('with sync_playwright() as p:')[0],namespace)
base_api=namespace['api']
OUT=ROOT/'work/agent-workbench';OUT.mkdir(parents=True,exist_ok=True)
checks,errors,posts=[],[],[]
def row(kind,status,data):return {'id':str(uuid.uuid4()),'kind':kind,'status':status,'revision':0,'data':data,'updatedAt':'2026-10-17 17:00:00'}
items=[row('PLAN','PENDING',{'title':'批次分析计划','text':'查询授权批次，然后生成报告','tasks':[{'title':'查询批次','status':'pending'}]}),row('QUESTION','PENDING',{'text':'选择统计时间','questionType':'SINGLE','options':['今天','本周']}),row('QUESTION','PENDING',{'text':'选择缺陷类型','questionType':'MULTIPLE','options':['变形','缺失']}),row('QUESTION','PENDING',{'text':'填写批次编号','questionType':'TEXT'}),row('CHILD','COMPLETED',{'specialist':'detection-task','title':'专业任务','result':'已查询授权批次'}),row('EXECUTION','NEEDS_REVIEW',{'title':'中断的分析任务'}),row('USAGE','COMPLETED',{'basis':'UNAVAILABLE','inputTokens':None,'outputTokens':None,'durationMs':120,'systemTokens':42,'toolsTokens':80,'messageTokens':100})]
file={'id':str(uuid.uuid4()),'name':'notes.html','contentType':'text/plain; charset=utf-8','bytes':50,'folder':'uploads'}
files=[file]
def api(route):
 req=route.request;path=urlparse(req.url).path
 if path=='/api/agent/workbench/capabilities':return namespace['reply'](route,dict(enabled=True,plans=True,questions=True,files=True,forks=True,children=True,jobs=True,usage=True,recovery=True))
 if path.endswith('/workbench'):
  return namespace['reply'](route,{'items':items,'files':files,'lineage':{'sourceSessionId':'parent-session'}})
 if '/workbench/' in path:
  body=req.post_data_json;assert req.headers.get('x-agent-action')=='workbench';posts.append({'path':path,'body':body});item=next(item for item in items if item['id']==path.split('/')[-1])
  if body['revision']!=item['revision']:return namespace['reply'](route,{'message':'conflict'},status=409)
  action=body['action'];item['revision']+=1;item['status']={'approve-plan':'APPROVED','revise-plan':'CHANGES_REQUESTED','answer':'ANSWERED','child-message':'QUEUED','resume':'READY','cancel':'CANCELLED'}[action]
  return namespace['reply'](route,item)
 if '/files/' in path and path.endswith('/content'):return route.fulfill(status=200,content_type='text/plain',body='<script>window.workbenchInjected=true</script>')
 if '/files/' in path and path.endswith('/remove'):
  posts.append({'path':path,'body':req.post_data_json});files.clear();return namespace['reply'](route,{'removed':True})
 if path.endswith('/fork'):
  posts.append({'path':path,'body':req.post_data_json});return namespace['reply'](route,{'sessionId':'control-session','sourceSessionId':'parent-session'})
 return base_api(route)
def check(name,action):
 try:action();checks.append({'name':name,'passed':True})
 except Exception as error:checks.append({'name':name,'passed':False,'error':str(error)})
def ensure(condition,message):assert condition,message

with sync_playwright() as playwright:
 browser=playwright.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1600,'height':1050});context.route('**/api/**',api);context.route('**/agui/**',api)
 for kind,url in [('Vue','http://127.0.0.1:3011/#/agent/chat'),('React','http://127.0.0.1:5175/')]:
  for item in items:item['revision']=0
  items[0]['status']='PENDING';items[1]['status']='PENDING';items[2]['status']='PENDING';items[3]['status']='PENDING';items[4]['status']='COMPLETED';items[5]['status']='NEEDS_REVIEW';files[:]=[file]
  page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)));page.goto(url);page.wait_for_load_state('networkidle')
  page.get_by_role('button',name='展开工作面板' if kind=='Vue' else '查看助手信息',exact=True).click()
  panel=page.get_by_role('region',name='Agent 持久工作台');expect(panel).to_be_visible()
  check(kind+' workbench has eight capability tabs',lambda:expect(panel.get_by_role('navigation',name='工作台视图').get_by_role('button')).to_have_count(8))
  plan=panel.locator('article').filter(has_text='批次分析计划');plan.get_by_role('button',name='批准计划').click();check(kind+' plan approval preserves the versioned item',lambda:expect(plan).to_contain_text('已批准'))
  panel.get_by_role('button',name='待回答',exact=True).click();question=panel.locator('article').filter(has_text='选择统计时间');question.get_by_label('选择回答').select_option('本周');question.get_by_role('button',name='提交回答').click();check(kind+' single choice submits structured answer',lambda:ensure(posts[-1]['body']['input']['answer']=='本周','wrong answer'))
  question=panel.locator('article').filter(has_text='选择缺陷类型');question.get_by_label('缺失',exact=True).check();question.get_by_role('button',name='提交回答').click();check(kind+' multiple choice submits an array',lambda:ensure(posts[-1]['body']['input']['answer']==['缺失'],'wrong answer'))
  question=panel.locator('article').filter(has_text='填写批次编号');question.get_by_label('问题回答').fill('batch-A');question.get_by_role('button',name='提交回答').click();check(kind+' text question submits without a business approval',lambda:ensure(posts[-1]['body']['action']=='answer' and posts[-1]['body']['input']['answer']=='batch-A','wrong action'))
  panel.get_by_role('button',name='文件产物',exact=True).click();panel.get_by_role('button',name='预览',exact=True).click();dialog=page.get_by_role('dialog');expect(dialog).to_be_visible()
  check(kind+' HTML file is rendered as plain text',lambda:ensure('<script>' in dialog.inner_text() and not page.evaluate('window.workbenchInjected===true'),'HTML executed'))
  if kind=='Vue':page.keyboard.press('Escape')
  else:dialog.get_by_role('button',name='Close',exact=True).focus();page.keyboard.press('Enter')
  expect(dialog).to_be_hidden()
  check(kind+' file tree separates uploads and generated artifacts',lambda:expect(panel.locator('details.wb-file-tree')).to_have_count(2))
  editor=page.get_by_role('textbox',name='聊天消息或技能命令') if kind=='Vue' else page.locator('[data-sender-input]')
  editor.fill('保留原来的草稿');panel.get_by_role('button',name='引用',exact=True).click()
  check(kind+' file reference appends the server ID without losing the draft',lambda:expect(editor).to_have_value('保留原来的草稿 @file:'+file['id']+' '))
  panel.get_by_role('button',name='子 Agent',exact=True).click();child=panel.locator('article').filter(has_text='专业任务');child.get_by_label('子 Agent 补充要求').fill('再核对缺失类型');child.get_by_role('button',name='追加专业要求').click();check(kind+' child follow-up targets its existing item',lambda:ensure(posts[-1]['body']['action']=='child-message','wrong child action'))
  expect(child).to_contain_text('排队中')
  items[4]['status']='COMPLETED';items[4]['revision']+=1;panel.get_by_role('button',name='刷新',exact=True).click()
  check(kind+' background completion is announced',lambda:expect(panel.get_by_role('status',name='后台任务通知')).to_contain_text('专业任务：已完成'))
  panel.get_by_role('button',name='用量',exact=True).click();check(kind+' unavailable token usage stays unknown',lambda:expect(panel).to_contain_text('未知 / 未知'))
  panel.get_by_role('button',name='恢复',exact=True).click();panel.get_by_role('button',name='确认从检查点恢复',exact=True).click();check(kind+' recovery is explicit and versioned',lambda:ensure(posts[-1]['body']['action']=='resume' and isinstance(posts[-1]['body']['revision'],int),'wrong recovery'))
  panel.get_by_role('button',name='分支',exact=True).click();check(kind+' fork view shows source navigation',lambda:expect(panel.get_by_text('返回来源会话',exact=True)).to_be_visible())
  expect(panel.get_by_role('button',name='刷新',exact=True)).to_be_enabled()
  page.wait_for_timeout(250)
  page.screenshot(path=str(OUT/(kind.lower()+'-desktop.png')),full_page=True)
  page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(250)
  if kind=='React':page.get_by_role('button',name='查看助手信息',exact=True).click()
  check(kind+' mobile workspace fits viewport',lambda:ensure(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'horizontal overflow'))
  panel.get_by_role('button',name='文件产物',exact=True).click();page.screenshot(path=str(OUT/(kind.lower()+'-mobile.png')),full_page=True)
  page.close()
 check('no browser JavaScript errors',lambda:ensure(not errors,str(errors)))
 browser.close()
failed=[item for item in checks if not item['passed']]
(OUT/'results.json').write_text(json.dumps({'checks':checks,'javascriptErrors':errors,'posts':posts},ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'passed':len(checks)-len(failed),'failed':failed,'javascriptErrors':errors},ensure_ascii=False))
if failed:raise SystemExit(1)
