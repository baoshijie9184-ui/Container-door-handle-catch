"""Personal memory receipt interactions against isolated HTTP fixtures, Vite 3011."""
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'work/memory-receipts-browser';OUT.mkdir(parents=True,exist_ok=True)
scope={'__file__':str(ROOT/'script/diagnostics/conversation-control-acceptance.py')}
exec((ROOT/'script/diagnostics/conversation-control-acceptance.py').read_text(encoding='utf8').split('with sync_playwright() as p:')[0],scope)
checks=[];errors=[];writes=[];state='RUNNING';unavailable=False;key='a'*64;verified=False

def api(route):
    global verified
    req=route.request;path=urlparse(req.url).path
    if not path.startswith('/api/agent/memories'):return scope['api'](route)
    if req.method not in ['GET','HEAD']:
        writes.append(path)
        assert path.endswith('/operations/'+key+'/verify') and req.headers.get('x-agent-action')=='memory-verify'
        if unavailable:return route.fulfill(status=503,json={'message':'提炼回执暂不可用 请稍后核对 不会重新执行'})
        verified=state=='SUCCEEDED'
        return route.fulfill(json={'requestId':key,'status':state,'affectedMemories':2 if verified else None,'updatedAt':'2026-10-18T12:00:00+08:00'})
    if path.endswith('/preferences'):return route.fulfill(json={'readEnabled':True,'saveEnabled':True,'revision':0})
    if path.endswith('/lifecycle'):return route.fulfill(json=[])
    if path.endswith('/audit'):return route.fulfill(json=[{'id':1,'action':'AUTOSAVE','requestId':key,'outcome':'SUCCEEDED' if verified else 'UNKNOWN','createdAt':'2026-10-18 12:00:00'}])
    return route.fulfill(json={'items':[{'id':'mine','memory':'<script>window.memoryInjected=true</script> 个人报告偏好','updatedAt':'2026-10-18T04:00:00Z','digest':'b'*64}],'hasMore':False})

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1500,'height':1050},timezone_id='America/Los_Angeles',reduced_motion='reduce')
    context.route('**/api/**',api);context.route('**/agui/**',api)
    page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.goto('http://127.0.0.1:3011/#/agent/memory');page.wait_for_load_state('networkidle')
    expect(page.locator('.memory-item')).to_have_count(1);assert not page.evaluate('window.memoryInjected===true');checks.append('memory text remains inert')
    expect(page.locator('.memory-item footer')).to_contain_text('2026-10-18 12:00:00');checks.append('UTC+8 display remains correct in a Los Angeles browser')
    page.locator('.memory-audit summary').click();button=page.get_by_role('button',name='核对提炼结果',exact=True);expect(button).to_be_visible();assert not writes;checks.append('loading history does not replay an extraction')
    button.focus();page.keyboard.press('Enter');expect(page.get_by_role('status')).to_contain_text('尚未获得完成回执');assert writes==['/api/agent/memories/operations/'+key+'/verify'];checks.append('keyboard verification reads the original running receipt without a save request')
    unavailable=True;button.click();expect(page.get_by_role('status')).to_contain_text('暂不可用');expect(button).to_be_visible();checks.append('failed verification does not claim success or remove the pending receipt')
    page.locator('.memory-audit').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'desktop-pending.png'),full_page=True);page.set_viewport_size({'width':390,'height':844});page.locator('.memory-audit').scroll_into_view_if_needed();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');page.screenshot(path=str(OUT/'mobile-pending.png'),full_page=True);checks.append('mobile receipt controls fit within the viewport')
    unavailable=False;state='SUCCEEDED';button.click();expect(page.get_by_role('status')).to_contain_text('已核对 2 条结果');expect(button).not_to_be_visible();assert len(writes)==3;checks.append('a late completion is reflected by a manual query and never reruns extraction')
    page.screenshot(path=str(OUT/'mobile-complete.png'),full_page=True);context.close();browser.close()
assert not errors,errors
(OUT/'results.json').write_text(json.dumps({'checks':checks,'javascriptErrors':errors,'requests':writes,'apiMode':'isolated fixtures'},ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'passed':len(checks),'javascriptErrors':errors}))
