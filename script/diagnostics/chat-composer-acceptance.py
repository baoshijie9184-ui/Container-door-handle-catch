"""Isolated browser contract checks for empty queue, native attachment chooser and model selection."""
import json,uuid
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'work/chat-composer';OUT.mkdir(parents=True,exist_ok=True)
namespace={'__file__':str(ROOT/'script/diagnostics/conversation-control-acceptance.py')}
exec((ROOT/'script/diagnostics/conversation-control-acceptance.py').read_text(encoding='utf8').split('with sync_playwright() as p:')[0],namespace)
checks=[];errors=[];selections=[];uploads=[];choice={'modelId':'','revision':0};fid=str(uuid.uuid4());reject_next=False;hide_selected=False
def api(route):
 global reject_next
 req=route.request;path=urlparse(req.url).path;reply=namespace['reply']
 if path=='/api/agent/workbench/capabilities':return reply(route,{'enabled':True,'files':True})
 if path=='/agui/models':return reply(route,{'selectedModel':'dashscope:flash','fallbackEnabled':True,'models':[{'id':'dashscope:flash','provider':'dashscope','model':'flash','configured':True},{'id':'dashscope:max','provider':'dashscope','model':'max','configured':True},{'id':'deepseek:demo','provider':'deepseek','model':'DeepSeek 演示','configured':not hide_selected},{'id':'missing','model':'未配置','configured':False}]})
 if path.endswith('/model-selection'):
  if req.method=='POST':
   body=req.post_data_json;assert body['revision']==choice['revision'] and req.headers['x-agent-action']=='workbench';selections.append(body)
   if reject_next:
    reject_next=False;choice.update(modelId='dashscope:max',revision=choice['revision']+1);return reply(route,{'message':'状态已变化'},status=409)
   choice.update(modelId=body['modelId'],revision=choice['revision']+1)
  return reply(route,choice)
 if path.endswith('/files') and req.method=='POST':
  assert req.headers['x-agent-action']=='workbench' and 'multipart/form-data' in req.headers['content-type'];uploads.append(path);return reply(route,{'id':fid,'name':'演示附件.md','bytes':17})
 if path.endswith('/workbench'):return reply(route,{'files':[{'id':fid,'name':'演示附件.md','bytes':17,'contentType':'text/plain'}]})
 return namespace['api'](route)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 for kind,url in [('vue','http://127.0.0.1:3011/#/agent/chat'),('react','http://127.0.0.1:5175/')]:
  namespace['run'].update(phase='IDLE',runId=None,local=False,text='');namespace['inputs'].clear();choice.update(modelId='',revision=0)
  context=browser.new_context(viewport={'width':1500,'height':1050},reduced_motion='reduce');context.route('**/api/**',api);context.route('**/agui/**',api);page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.goto(url);page.wait_for_load_state('networkidle')
  controls=page.get_by_role('region',name='Agent 执行控制');expect(controls).not_to_be_visible();checks.append(kind+' no empty queue panel')
  namespace['inputs'].append({'id':str(uuid.uuid4()),'mode':'NEXT_TURN','status':'COMPLETED','revision':1,'content':''});page.wait_for_timeout(2300);expect(controls).not_to_be_visible();checks.append(kind+' delivery history does not create an empty queue')
  model=page.get_by_label('使用模型',exact=True);expect(model).to_be_enabled();assert model.locator('option').count()==4;expect(model.locator('option[value=""]')).to_have_text('系统默认 · flash · 百炼');expect(model.locator('option[value="deepseek:demo"]')).to_contain_text('DeepSeek 直连');model.select_option('deepseek:demo');expect(model).to_have_value('deepseek:demo');page.reload();page.wait_for_load_state('networkidle');expect(page.get_by_label('使用模型',exact=True)).to_have_value('deepseek:demo');checks.append(kind+' persisted configured model choice and distinct provider labels')
  editor=page.get_by_role('textbox',name='聊天消息或技能命令') if kind=='vue' else page.get_by_placeholder('输入问题 或输入 / 选择技能命令');editor.fill('保留这个未发送草稿');reject_next=True;model.select_option('dashscope:flash');expect(page.get_by_role('button',name='核对模型选择',exact=True)).to_be_visible();posts=len(selections);page.get_by_role('button',name='核对模型选择',exact=True).click();expect(model).to_have_value('dashscope:max');expect(editor).to_have_value('保留这个未发送草稿');assert len(selections)==posts;checks.append(kind+' stale model revision reconciled without another POST or losing draft')
  model.select_option('');expect(model).to_have_value('');expect(page.get_by_text('已保存，仅对当前会话的新任务生效',exact=True)).to_be_visible();page.reload();page.wait_for_load_state('networkidle');expect(model).to_have_value('');checks.append(kind+' system default can be restored and survives refresh')
  model.select_option('deepseek:demo');expect(model).to_have_value('deepseek:demo');hide_selected=True;page.reload();page.wait_for_load_state('networkidle');expect(model).to_have_value('deepseek:demo');expect(model.locator('option:checked')).to_be_disabled();expect(page.get_by_text('原选模型已不在可用目录，请选择其他模型',exact=True)).to_be_visible();model.select_option('dashscope:flash');expect(model).to_have_value('dashscope:flash');hide_selected=False;checks.append(kind+' removed model is explicit and user can select an available replacement')
  file=OUT/'演示附件.md';file.write_text('private document',encoding='utf8')
  with page.expect_file_chooser() as picker:page.get_by_role('button',name='添加附件',exact=True).click()
  picker.value.set_files(str(file));rail=page.get_by_label('待发送附件',exact=True);expect(rail).to_contain_text('演示附件.md');checks.append(kind+' plus opens native chooser and stores private attachment')
  draft=page.get_by_role('textbox',name='聊天消息或技能命令') if kind=='vue' else page.get_by_placeholder('输入问题 或输入 / 选择技能命令');draft.fill('刷新后继续读取附件');page.reload();page.wait_for_load_state('networkidle');expect(draft).to_have_value('刷新后继续读取附件');expect(rail).to_contain_text('演示附件.md');checks.append(kind+' unsent text and authorized attachment restored after reload')
  namespace['run'].update(phase='RUNNING',runId=str(uuid.uuid4()),local=True,text='正在查询');namespace['inputs'].clear();namespace['inputs'].append({'id':str(uuid.uuid4()),'mode':'NEXT_TURN','status':'QUEUED','revision':0,'content':'后续补充要求'})
  expect(controls).to_be_visible(timeout=6000);expect(page.get_by_label('使用模型',exact=True)).to_be_disabled();expect(controls.get_by_role('button',name='更多消息操作')).to_be_visible();checks.append(kind+' active queue keeps steering and editing, model locked')
  editor=page.get_by_role('textbox',name='聊天消息或技能命令') if kind=='vue' else page.get_by_placeholder('输入问题 或输入 / 选择技能命令');editor.fill('读取附件');editor.press('Enter');expect(rail).not_to_be_visible();assert any('@file:'+fid in row['content'] for row in namespace['inputs']);checks.append(kind+' queued input carries server file reference')
  expect(page.get_by_role('button',name='发送消息',exact=True)).not_to_be_visible()
  if kind=='vue':expect(page.get_by_role('button',name='语音输入',exact=True)).to_be_visible()
  page.get_by_role('button',name='停止任务',exact=True).click();expect(page.get_by_role('button',name='继续执行',exact=True)).to_be_visible();page.get_by_role('button',name='继续执行',exact=True).click();assert namespace['run']['phase']=='RUNNING';checks.append(kind+' composer stop requires explicit confirmation and preserves queue')
  page.screenshot(path=str(OUT/(kind+'-desktop.png')),full_page=True);page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');expect(page.get_by_role('button',name='添加附件',exact=True)).to_be_visible();page.screenshot(path=str(OUT/(kind+'-mobile.png')),full_page=True);checks.append(kind+' mobile controls reachable')
  context.close()
 browser.close()
assert not errors,errors
(OUT/'results.json').write_text(json.dumps({'passed':len(checks),'checks':checks,'javascriptErrors':errors,'uploads':len(uploads),'modelChanges':len(selections)},ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps({'passed':len(checks),'javascriptErrors':errors}))
