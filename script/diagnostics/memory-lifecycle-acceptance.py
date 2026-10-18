"""Lifecycle UI checks with isolated HTTP fixtures; never alter existing memories or call models."""
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'work/memory-lifecycle-browser';OUT.mkdir(parents=True,exist_ok=True)
scope={'__file__':str(ROOT/'script/diagnostics/conversation-control-acceptance.py')}
exec((ROOT/'script/diagnostics/conversation-control-acceptance.py').read_text(encoding='utf-8').split('with sync_playwright() as p:')[0],scope)
controls={'memoryId':'mine','revision':0,'state':'ACTIVE','expiresAt':None,'autoDelete':False,'cleanupState':'NONE','updatedAt':None}
writes=[];errors=[];checks=[];fault=None;pending=True


def api(route):
    global pending
    request=route.request;path=urlparse(request.url).path
    if not path.startswith('/api/agent/memories'):return scope['api'](route)
    if request.method not in ['GET','HEAD']:
        writes.append({'path':path,'body':request.post_data_json})
        if path.endswith('/cleanup/verify'):
            assert request.headers['x-agent-action']=='memory-verify'
            pending=False;return route.fulfill(json={**controls,'memoryId':'removed','cleanupState':'SUCCEEDED'})
        assert path.endswith('/mine/lifecycle')
        body=request.post_data_json
        assert body['confirmed'] and body['expectedDigest']=='a'*64 and body['expectedRevision']==controls['revision']
        if fault:return route.fulfill(status=fault,json={'message':'结果需要刷新核对'})
        controls.update({'revision':controls['revision']+1,'state':body['state'],'expiresAt':body['expiresAt'],'autoDelete':body['autoDelete'],'cleanupState':'READY' if body['autoDelete'] else 'NONE'})
        return route.fulfill(json=controls)
    if path.endswith('/reviews'):return route.fulfill(json=[])
    if path.endswith('/preferences'):return route.fulfill(json={'readEnabled':True,'saveEnabled':True,'revision':0})
    if path.endswith('/audit'):return route.fulfill(json=[])
    if path.endswith('/lifecycle'):return route.fulfill(json=[{**controls,'memoryId':'removed','cleanupState':'NEEDS_REVIEW' if pending else 'SUCCEEDED'}])
    item={'id':'mine','memory':'<script>window.memoryInjected=true</script> 只管理本人长期记忆','updatedAt':'2026-10-18T04:00:00Z','digest':'a'*64,'lifecycle':controls}
    return route.fulfill(json=item if path.endswith('/mine') else {'items':[item],'hasMore':False})


with sync_playwright() as p:
    browser=p.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1500,'height':1050},timezone_id='America/Los_Angeles',reduced_motion='reduce')
    context.route('**/api/**',api);context.route('**/agui/**',api)
    page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.goto('http://127.0.0.1:3011/#/agent/memory');page.wait_for_load_state('networkidle')
    expect(page.locator('.memory-item')).to_have_count(1);assert not writes and not page.evaluate('window.memoryInjected===true');checks.append('reading private memory does not mutate controls or execute its text')
    page.get_by_role('button',name='有效期与停用',exact=True).click();dialog=page.get_by_role('dialog',name='记忆有效期与停用');expect(dialog).to_be_visible()
    dialog.get_by_role('button',name='取消',exact=True).click();expect(dialog).not_to_be_visible();assert not writes;checks.append('opening and canceling controls never saves')
    page.get_by_role('button',name='有效期与停用',exact=True).click();dialog.locator('.el-select__wrapper').click();page.get_by_role('option',name='停用错误或重复记忆',exact=True).click()
    dialog.get_by_text('到期后自动删除这条记忆',exact=True).click();expect(dialog.get_by_role('checkbox',name='到期后自动删除这条记忆')).to_be_checked();expect(dialog.get_by_role('button',name='预览设置')).to_be_disabled();checks.append('automatic cleanup cannot be confirmed without an expiry')
    expiry=dialog.get_by_role('textbox',name='记忆有效期 北京时间') if dialog.get_by_role('textbox',name='记忆有效期 北京时间').count() else dialog.locator('input[type="datetime-local"]')
    expiry.fill('2026-11-18T12:30');dialog.get_by_role('button',name='预览设置').click();expect(dialog).to_contain_text('无法在此恢复');assert not writes
    dialog.get_by_role('button',name='确认设置').focus();page.keyboard.press('Enter');expect(dialog).not_to_be_visible();expect(page.locator('.memory-lifecycle-status')).to_contain_text('已停用')
    assert len(writes)==1 and writes[0]['body']['expiresAt']=='2026-11-18T12:30:00+08:00';checks.append('preview then explicit keyboard confirmation saves the UTC+8 expiry and original version')
    page.get_by_role('button',name='有效期与停用',exact=True).click();expect(dialog.locator('input[type="datetime-local"]')).to_have_value('2026-11-18T12:30');checks.append('a Los Angeles browser edits the saved Beijing time without shifting it')
    fault=503;dialog.get_by_role('button',name='预览设置').click();dialog.get_by_role('button',name='确认设置').click();expect(dialog.get_by_role('alert')).to_contain_text('需要刷新核对');assert len(writes)==2;expect(dialog.get_by_role('button',name='预览设置')).not_to_be_visible()
    dialog.get_by_role('button',name='重新读取当前版本').click();expect(dialog.get_by_role('button',name='预览设置')).to_be_visible();expect(dialog.locator('input[type="datetime-local"]')).to_have_value('2026-11-18T12:30');assert len(writes)==2;checks.append('an unknown result preserves the draft and requires a fresh read and confirmation without replay')
    page.screenshot(path=str(OUT/'desktop-policy.png'),full_page=True);page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');page.screenshot(path=str(OUT/'mobile-policy.png'),full_page=True)
    dialog.get_by_role('button',name='取消',exact=True).click();page.locator('.memory-lifecycle-history summary').click();verify=page.get_by_role('button',name='核对清理结果',exact=True);verify.click();expect(page.locator('.memory-lifecycle-history')).to_contain_text('已核对记忆不存在');expect(verify).not_to_be_visible();assert len(writes)==3;checks.append('unknown cleanup is reconciled by a read and never submits another delete')
    page.locator('.memory-lifecycle-history').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'mobile-history.png'),full_page=True);checks.append('mobile controls and history fit the viewport with reduced motion')
    page.get_by_role('button',name='编辑记忆',exact=True).click();editor=page.get_by_role('dialog',name='编辑长期记忆');expect(editor).to_contain_text('修改正文不会自动恢复')
    editor.get_by_role('textbox',name='修改记忆正文').fill('纠正后的记忆正文');editor.get_by_role('button',name='预览修改').click();expect(editor).to_contain_text('纠正后的记忆正文');editor.get_by_role('button',name='取消',exact=True).click();assert len(writes)==3;checks.append('editing an excluded memory keeps its governance state and canceling the preview does not save')
    context.close();browser.close()
assert not errors,errors
(OUT/'results.json').write_text(json.dumps({'checks':checks,'javascriptErrors':errors,'requests':writes,'apiMode':'isolated fixtures'},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':len(checks),'javascriptErrors':errors}))
