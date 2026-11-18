"""Real login/API guards + isolated edit/page UI fixtures; no existing memories modified."""
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, expect

root=Path(__file__).resolve().parents[2]
base='http://127.0.0.1:3001'
checks=[];errors=[];requests=[];mode='success';list_down=False;more_down=False
rows=[{'id':f'fixture-{i}','memory':f'本人记忆 {i}','digest':'a'*64,'sourceSessionId':'fixture-session','updatedAt':'2026-10-14 16:00:00'} for i in range(125)]
rows[0]['memory']='<script>window.__memoryInjected=true</script> 本人报告按周统计'

def passed(name):checks.append({'name':name,'passed':True})
def login(page,user):
    page.goto(base+'/#/login',wait_until='networkidle')
    page.get_by_placeholder('请输入用户名').fill(user)
    page.get_by_placeholder('请输入密码').fill('123456')
    page.get_by_role('button',name='登录系统',exact=True).click()
    page.wait_for_url('**/#/home')

def route_memory(route):
    global mode
    parsed=urlparse(route.request.url);path=parsed.path
    if path=='/api/agent/memories':
        query=parse_qs(parsed.query);offset=int(query.get('offset',['0'])[0]);limit=int(query.get('limit',['50'])[0])
        if list_down or (more_down and offset):route.fulfill(status=503,json={'message':'记忆服务暂不可用'});return
        next_offset=offset+limit
        route.fulfill(json={'items':rows[offset:next_offset],'hasMore':next_offset<len(rows),'nextOffset':next_offset if next_offset<len(rows) else None});return
    if path.endswith('/audit'):
        route.fulfill(json=[{'id':1,'action':'UPDATE','outcome':'SUCCEEDED','createdAt':'2026-10-14 16:00:00'}]);return
    if path.endswith('/fixture-0'):
        route.fulfill(json=rows[0]);return
    if path.endswith('/fixture-0/update'):
        body=route.request.post_data_json;requests.append(body)
        assert body['confirmed'] and body['expectedDigest']==rows[0]['digest']
        if mode=='conflict':
            rows[0]={**rows[0],'memory':'另一个页面已更新的原文','digest':'b'*64}
            route.fulfill(status=409,json={'message':'记忆已变化 请刷新核对后再操作'});return
        rows[0]={**rows[0],'memory':body['memory'],'digest':'c'*64}
        if mode=='unknown':route.fulfill(status=503,json={'message':'修改结果待核对 请刷新记忆列表'});return
        route.fulfill(json={'updated':True,'replayed':False});return
    route.continue_()

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
    page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        login(page,'inspector.demo')
        # These real requests do not modify memory or settings.
        health=context.request.get('http://127.0.0.1:8081/health').json()
        assert health.get('owned_edit') and health.get('owned_pagination')
        result=context.request.get(base+'/api/agent/memories?limit=50&offset=100')
        assert result.ok and result.headers['cache-control']=='no-store'
        assert context.request.get(base+'/api/agent/memories?offset=-1').status==400
        assert context.request.get(base+'/api/agent/memories/not-a-real-memory').status==404
        invalid={'requestId':'browser-unconfirmed','expectedDigest':'a'*64,'memory':'不应保存','confirmed':False}
        assert context.request.post(base+'/api/agent/memories/not-a-real-memory/update',data=invalid).status==400
        passed('real_backend_paging_validation_private_read_and_unconfirmed_update_guard')

        page.route('**/api/agent/memories**',route_memory)
        page.goto(base+'/#/agent/memory',wait_until='networkidle')
        expect(page.locator('.memory-item')).to_have_count(50)
        assert page.evaluate('window.__memoryInjected') is None
        page.get_by_role('button',name='读取更多',exact=True).click();expect(page.locator('.memory-item')).to_have_count(100)
        page.get_by_role('button',name='读取更多',exact=True).click();expect(page.locator('.memory-item')).to_have_count(125)
        expect(page.get_by_role('button',name='读取更多',exact=True)).to_have_count(0)
        passed('three_pages_exceed_100_records_and_render_memory_as_plain_text')

        page.get_by_role('button',name='编辑记忆',exact=True).first.click()
        dialog=page.get_by_role('dialog',name='编辑长期记忆',exact=True)
        editor=dialog.get_by_role('textbox',name='修改记忆正文')
        editor.fill('   ');expect(dialog.get_by_role('button',name='预览修改',exact=True)).to_be_disabled()
        editor.fill('本人报告改成按月统计');dialog.get_by_role('button',name='预览修改',exact=True).click()
        expect(dialog.locator('.memory-preview')).to_have_text('本人报告改成按月统计')
        expect(dialog.locator('.memory-original')).to_contain_text('本人报告按周统计')
        dialog.get_by_role('button',name='取消',exact=True).click();assert not requests
        passed('blank_edits_are_blocked_and_preview_cancel_does_not_dispatch')

        mode='conflict'
        page.get_by_role('button',name='编辑记忆',exact=True).first.click()
        editor.fill('冲突后仍保留的私人草稿');dialog.get_by_role('button',name='预览修改',exact=True).click()
        dialog.get_by_role('button',name='确认保存',exact=True).click()
        expect(dialog.get_by_role('alert')).to_contain_text('记忆已变化')
        expect(editor).to_have_value('冲突后仍保留的私人草稿')
        expect(dialog.get_by_role('button',name='确认保存',exact=True)).to_have_count(0);assert len(requests)==1
        dialog.get_by_role('button',name='重新读取当前版本',exact=True).click()
        expect(dialog.locator('.memory-original')).to_have_text('另一个页面已更新的原文')
        expect(editor).to_have_value('冲突后仍保留的私人草稿')
        mode='success';dialog.get_by_role('button',name='预览修改',exact=True).click();dialog.get_by_role('button',name='确认保存',exact=True).click()
        expect(dialog).not_to_be_visible();expect(page.locator('.memory-item')).to_have_count(50)
        expect(page.locator('.memory-content').first).to_have_text('冲突后仍保留的私人草稿')
        assert len(requests)==2 and requests[1]['expectedDigest']=='b'*64 and requests[1]['requestId']!=requests[0]['requestId']
        passed('stale_version_retains_draft_and_requires_reload_preview_and_new_confirmation')

        mode='unknown'
        page.get_by_role('button',name='编辑记忆',exact=True).first.click();editor.fill('网络异常但可能已保存的草稿')
        dialog.get_by_role('button',name='预览修改',exact=True).click();dialog.get_by_role('button',name='确认保存',exact=True).click()
        expect(dialog.get_by_role('alert')).to_contain_text('结果待核对');expect(editor).to_have_value('网络异常但可能已保存的草稿')
        assert len(requests)==3
        dialog.get_by_role('button',name='重新读取当前版本',exact=True).click()
        expect(dialog.locator('.memory-original')).to_have_text('网络异常但可能已保存的草稿')
        expect(dialog.get_by_role('button',name='预览修改',exact=True)).to_be_disabled()
        dialog.get_by_role('button',name='取消',exact=True).click();assert len(requests)==3
        passed('unknown_outcome_is_not_automatically_retried_and_current_text_can_be_checked')

        more_down=True;page.get_by_role('button',name='读取更多',exact=True).click()
        expect(page.locator('.memory-list [role=alert]')).to_contain_text('记忆服务暂不可用');expect(page.locator('.memory-item')).to_have_count(50)
        more_down=False;page.get_by_role('button',name='读取更多',exact=True).click();expect(page.locator('.memory-item')).to_have_count(100)
        list_down=True;page.get_by_role('button',name='刷新',exact=True).click();expect(page.locator('.memory-item')).to_have_count(0)
        list_down=False;page.get_by_role('button',name='刷新',exact=True).click();expect(page.locator('.memory-item')).to_have_count(50)
        page.locator('.memory-audit summary').click();expect(page.locator('.memory-audit')).to_contain_text('编辑记忆')
        passed('pagination_failure_preserves_loaded_rows_refresh_failure_clears_rows_and_edit_audit_is_labeled')

        page.get_by_role('button',name='编辑记忆',exact=True).first.click();editor.fill('桌面和手机编辑布局检查')
        page.screenshot(path=str(root/'work/memory-edit-desktop.png'),animations='disabled')
        page.set_viewport_size({'width':390,'height':844});expect(dialog).to_be_visible()
        dialog.scroll_into_view_if_needed()
        bounds=dialog.bounding_box();assert bounds['x']>=0 and bounds['x']+bounds['width']<=391 and bounds['y']>=0 and bounds['y']+bounds['height']<=845
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(root/'work/memory-edit-mobile.png'),animations='disabled')
        passed('desktop_and_mobile_dialog_stay_within_viewport_without_javascript_errors')
        assert not errors
    finally:
        (root/'work/memory-edit-browser-acceptance.json').write_text(json.dumps({'checks':checks,'passed':len(checks)==7 and not errors,'javascriptErrors':errors,'paidModelsCalled':False,'existingMemoryModified':False,'uiMemoryMutationsWereFixtures':True},ensure_ascii=False,indent=2),encoding='utf-8')
        context.close();browser.close()
