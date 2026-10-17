"""Private file cards and UTC+8 display in both current chat entrances (isolated APIs)."""
import json,re
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'work/chat-file-cards';OUT.mkdir(parents=True,exist_ok=True)
namespace={'__file__':str(ROOT/'script/diagnostics/conversation-control-acceptance.py')}
exec((ROOT/'script/diagnostics/conversation-control-acceptance.py').read_text(encoding='utf8').split('with sync_playwright() as p:')[0],namespace)
fid='01234567-0123-4567-89ab-0123456789ab';files=[{'id':fid,'name':'<script>验收.html','contentType':'text/html','bytes':45,'folder':'uploads'}];denied=False;checks=[];errors=[]
namespace['run'].update(phase='IDLE',runId=None,local=False,text='');namespace['inputs'].clear()
namespace['session']['messages']=[{'id':1,'role':'user','messageType':'TEXT','content':'查看附件\n@file:'+fid,'createdAt':'2026-10-18 00:10:00'},{'id':2,'role':'assistant','messageType':'TEXT','content':'这是测试回复','createdAt':'2026-10-18 00:10:01'}]
def api(route):
 path=urlparse(route.request.url).path;reply=namespace['reply']
 if path.endswith('/workbench'):return reply(route,{'files':files,'items':[],'limits':{},'lineage':{}})
 if path.endswith('/content'):
  if denied:return reply(route,{'message':'denied'},status=403)
  return route.fulfill(status=200,content_type='text/html',body='<script>window.attachmentExecuted=true</script>')
 if path=='/api/agent/workbench/capabilities':return reply(route,{'enabled':True,'files':True})
 if path.endswith('/model-selection'):return reply(route,{'modelId':'','revision':0})
 return namespace['api'](route)
with sync_playwright() as p:
 browser=p.chromium.launch()
 for kind,url in [('vue','http://127.0.0.1:3011/#/agent/chat'),('react','http://127.0.0.1:5175/')]:
  context=browser.new_context(viewport={'width':1500,'height':1050},timezone_id='America/Los_Angeles',reduced_motion='reduce',accept_downloads=True);context.route('**/api/**',api);context.route('**/agui/**',api);page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.goto(url);page.wait_for_load_state('networkidle');rail=page.get_by_role('region',name='消息附件');expect(rail).to_contain_text('<script>验收.html');assert '@file:'+fid not in page.locator('body').inner_text();checks.append(kind+' private file card replaces raw reference')
  if kind=='vue':assert page.locator('.msg-time').first.inner_text()=='00:10';checks.append('Vue displays UTC+8 when browser is in Los Angeles')
  rail.get_by_role('button',name='预览',exact=True).click();dialog=page.get_by_role('dialog',name='消息附件预览',exact=True);expect(dialog).to_contain_text('<script>window.attachmentExecuted=true</script>');assert not page.evaluate('window.attachmentExecuted===true');assert dialog.locator('iframe,script').count()==0;checks.append(kind+' HTML and filename remain inert source text')
  if kind=='react':expect(dialog).not_to_have_class(re.compile('ant-zoom-appear'))
  page.keyboard.press('Escape');expect(dialog).not_to_be_visible()
  with page.expect_download() as downloaded:rail.get_by_role('button',name='下载',exact=True).click()
  assert downloaded.value.suggested_filename=='_script_验收.html' or downloaded.value.suggested_filename=='<script>验收.html';checks.append(kind+' authorized download uses filename')
  denied=True;rail.get_by_role('button',name='预览',exact=True).click();expect(rail.get_by_role('alert')).to_contain_text('无权读取');expect(dialog).not_to_be_visible();expect(rail.get_by_role('button',name='预览',exact=True)).not_to_be_visible();expect(rail).not_to_contain_text('<script>验收.html');checks.append(kind+' revoked read removes metadata and actions');denied=False
  page.screenshot(path=str(OUT/(kind+'-desktop.png')),full_page=True);page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');page.screenshot(path=str(OUT/(kind+'-mobile.png')),full_page=True);page.close();context.close()
 browser.close()
assert not errors,errors;(OUT/'results.json').write_text(json.dumps({'checks':checks,'javascriptErrors':errors},ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps({'passed':len(checks),'javascriptErrors':errors}))
