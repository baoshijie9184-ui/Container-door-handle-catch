"""Recovery interaction contract checks in both actual UIs; no paid provider or cloud writes."""
import json,uuid
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'work/recovery-model-browser';OUT.mkdir(parents=True,exist_ok=True)
namespace={'__file__':str(ROOT/'script/diagnostics/conversation-control-acceptance.py')}
exec((ROOT/'script/diagnostics/conversation-control-acceptance.py').read_text(encoding='utf8').split('with sync_playwright() as p:')[0],namespace)
checks=[];errors=[]

with sync_playwright() as playwright:
 browser=playwright.chromium.launch(headless=True)
 for kind,url in [('Vue','http://127.0.0.1:3011/#/agent/chat'),('React','http://127.0.0.1:5175/')]:
  for size,viewport in [('desktop',{'width':1500,'height':1100}),('mobile',{'width':390,'height':844})]:
   namespace['run'].update(phase='IDLE',runId=None,local=False,text='');namespace['inputs'].clear()
   state={'version':9,'posts':[],'catalogReads':0}
   item={'id':str(uuid.uuid4()),'kind':'EXECUTION','status':'NEEDS_REVIEW','revision':0,'data':{'title':'模型恢复验收任务','modelConfigVersion':7,'modelDefault':'dashscope:old','modelId':''}}
   def api(route):
    path=urlparse(route.request.url).path;reply=namespace['reply']
    if not path.startswith(('/api/','/agui/')):return route.continue_()
    if path=='/api/agent/workbench/capabilities':return reply(route,{'enabled':True,'modelConfig':True})
    if path.endswith('/model-selection'):return reply(route,{'modelId':'','revision':0})
    if path=='/agui/models':
     state['catalogReads']+=1
     return reply(route,{'configVersion':state['version'],'selectedModel':'dashscope:new','models':[{'id':'dashscope:new','model':'new','provider':'dashscope','configured':True},{'id':'deepseek:new','model':'new','provider':'deepseek','configured':True}]})
    if path.endswith('/workbench'):return reply(route,{'items':[item],'files':[]})
    if '/workbench/' in path:
     body=route.request.post_data_json;assert route.request.headers.get('x-agent-action')=='workbench'
     assert body['action']=='resume' and body['revision']==item['revision'];state['posts'].append(body)
     if 'replacementConfigVersion' in body['input'] and body['input']['replacementConfigVersion']!=state['version']:
      return reply(route,{'message':'模型配置已变化'},status=409)
     item['status']='READY';item['revision']+=1
     return reply(route,item)
    return namespace['api'](route)
   context=browser.new_context(viewport=viewport,reduced_motion='reduce')
   context.route('**/api/**',api);context.route('**/agui/**',api)
   page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
   page.goto(url);page.wait_for_load_state('networkidle')
   page.get_by_role('button',name='展开工作面板' if kind=='Vue' else '查看助手信息',exact=True).click()
   panel=page.get_by_role('region',name='Agent 持久工作台');expect(panel).to_be_visible()
   panel.get_by_role('button',name='恢复',exact=True).click()
   select=panel.get_by_label('恢复任务使用模型',exact=True)
   expect(select).to_have_value('KEEP');expect(panel).to_contain_text('dashscope:old · V7')
   panel.get_by_role('button',name='确认从检查点恢复',exact=True).click()
   expect(panel.locator('article')).to_have_count(0)
   assert len(state['posts'])==1 and state['posts'][-1]['input']=={}
   checks.append(f'{kind} {size} retains original configuration without an implicit switch')
   item['status']='NEEDS_REVIEW';item['revision']+=1
   panel.get_by_role('button',name='刷新',exact=True).click();expect(select).to_be_visible()
   select.select_option('deepseek:new')
   panel.get_by_role('button',name='确认从检查点恢复',exact=True).click()
   dialog=page.get_by_role('dialog').filter(has_text='确认恢复模型');expect(dialog).to_contain_text('V9')
   assert len(state['posts'])==1
   dialog.get_by_role('button',name='保留现状',exact=True).click();expect(dialog).to_be_hidden();assert len(state['posts'])==1
   checks.append(f'{kind} {size} changing the model requires explicit confirmation')
   # Config changes while this page still displays V9. The backend refuses the stale confirmation.
   state['version']=10
   panel.get_by_role('button',name='确认从检查点恢复',exact=True).click()
   dialog=page.get_by_role('dialog').filter(has_text='确认恢复模型');dialog.get_by_role('button',name='确认更换并恢复',exact=True).click()
   expect(panel.get_by_role('alert').first).to_contain_text('状态已变化')
   assert len(state['posts'])==2 and state['posts'][-1]['input']=={'replacementModelId':'deepseek:new','replacementConfigVersion':9}
   assert item['status']=='NEEDS_REVIEW'
   before=len(state['posts']);panel.get_by_role('button',name='核对恢复模型',exact=True).click()
   expect(select.locator('option[value="deepseek:new"]')).to_contain_text('V10')
   assert len(state['posts'])==before
   panel.get_by_role('button',name='确认从检查点恢复',exact=True).click()
   dialog=page.get_by_role('dialog').filter(has_text='确认恢复模型');expect(dialog).to_contain_text('V10')
   dialog.get_by_role('button',name='确认更换并恢复',exact=True).click()
   expect(panel.locator('article')).to_have_count(0)
   assert len(state['posts'])==3 and state['posts'][-1]['input']=={'replacementModelId':'deepseek:new','replacementConfigVersion':10}
   assert state['posts'][-1]['requestId']!=state['posts'][-2]['requestId']
   checks.append(f'{kind} {size} stale configuration rejected, read-only refresh and confirmed new version')
   item['status']='NEEDS_REVIEW';item['revision']+=1;page.reload();page.wait_for_load_state('networkidle')
   page.get_by_role('button',name='展开工作面板' if kind=='Vue' else '查看助手信息',exact=True).click()
   panel=page.get_by_role('region',name='Agent 持久工作台');panel.get_by_role('button',name='恢复',exact=True).click()
   expect(panel.get_by_label('恢复任务使用模型',exact=True)).to_have_value('KEEP')
   assert len(state['posts'])==3
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
   select=panel.get_by_label('恢复任务使用模型',exact=True);select.focus();page.keyboard.press('Tab')
   expect(panel.get_by_role('button',name='核对恢复模型',exact=True)).to_be_focused()
   page.screenshot(path=str(OUT/f'{kind}-{size}.png'),full_page=True)
   checks.append(f'{kind} {size} refresh never replays recovery, keyboard focus and no horizontal overflow')
   context.close()
 browser.close()
assert not errors,errors
(OUT/'results.json').write_text(json.dumps({'scope':'isolated HTTP contract checks; not candidate or supplier acceptance','checks':checks,'pageErrors':errors},ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'passed':len(checks),'pageErrors':len(errors)}))
