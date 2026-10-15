"""Live settings/ownership/bridge health plus controlled memory UI fixtures; no paid model calls."""
import json
import re
import uuid
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

root=Path(__file__).resolve().parents[2];base='http://127.0.0.1:3001';checks=[];errors=[]
fixture={'id':'browser-memory-sample','memory':'<script>window.__memoryInjected=true</script> 验收报告按周统计','digest':'a'*64,'sourceSessionId':'fixture-session','createdAt':'2026-10-13 12:00:00','updatedAt':'2026-10-13 12:00:00'}
deleted=False;unavailable=False;stale=False;requests=[];restored=False
def passed(name):checks.append({'name':name,'passed':True})
def login(page,username):
    page.goto(base+'/#/login',wait_until='networkidle');page.get_by_placeholder('请输入用户名').fill(username);page.get_by_placeholder('请输入密码').fill('123456');page.get_by_role('button',name='登录系统',exact=True).click();page.wait_for_url('**/#/home')
def list_route(route):
    if unavailable:route.fulfill(status=503,json={'message':'记忆服务暂不可用'});return
    route.fulfill(status=200,json={'items':[] if deleted else [fixture],'hasMore':False})
def delete_route(route):
    global deleted
    body=route.request.post_data_json;requests.append(body)
    assert body['confirmed'] is True and body['expectedDigest']==fixture['digest']
    assert re.fullmatch(r'[A-Za-z0-9_-]{1,64}',body['requestId'])
    if stale:route.fulfill(status=409,json={'message':'记忆已变化 请刷新后再删除'});return
    deleted=True;route.fulfill(status=200,json={'deleted':True,'replayed':False})
def restore(context,original):
    current=context.request.get(base+'/api/agent/memories/preferences').json()
    if current['readEnabled']==original['readEnabled'] and current['saveEnabled']==original['saveEnabled']:return
    response=context.request.put(base+'/api/agent/memories/preferences',data={'expectedRevision':current['revision'],'readEnabled':original['readEnabled'],'saveEnabled':original['saveEnabled']})
    assert response.ok,response.status

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True);employee=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce');boss_context=browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce')
    page=employee.new_page();page.on('pageerror',lambda e:errors.append(str(e)));boss=boss_context.new_page();boss.on('pageerror',lambda e:errors.append(str(e)));original=None;boss_original=None
    try:
        login(page,'inspector.demo');login(boss,'supervisor.demo')
        original=employee.request.get(base+'/api/agent/memories/preferences').json();boss_original=boss_context.request.get(base+'/api/agent/memories/preferences').json()
        actual=employee.request.get(base+'/api/agent/memories');assert actual.ok and actual.headers['cache-control']=='no-store'
        health=employee.request.get('http://127.0.0.1:8081/health').json();assert health['governance'] and health['bridge_auth_configured']
        raw=employee.request.post('http://127.0.0.1:8081/memories/owned/list',data={'user_id':'doorhandlecatch:user:18','app_id':'doorhandlecatch'});assert raw.status==401
        passed('real_memory_bridge_is_authenticated_and_private_java_read_is_uncacheable')
        page.route(re.compile(r'.*/api/agent/memories\?limit=(50|100)$'),list_route);page.route('**/api/agent/memories/browser-memory-sample/delete',delete_route)
        page.goto(base+'/#/agent/memory',wait_until='networkidle');expect(page.get_by_role('heading',name='个人记忆',exact=True)).to_be_visible();expect(page.locator('.memory-content')).to_have_text(fixture['memory']);assert page.evaluate('window.__memoryInjected') is None
        passed('owned_memory_fixture_is_rendered_as_text_without_script_execution')
        read_switch=page.get_by_role('switch',name='允许读取长期记忆',exact=True);save_switch=page.get_by_role('switch',name='自动保存长期记忆',exact=True)
        if original['readEnabled']:read_switch.locator("xpath=..").click()
        if original['saveEnabled']:save_switch.locator("xpath=..").click()
        if original['readEnabled'] or original['saveEnabled']:
            page.get_by_role('button',name='保存设置',exact=True).click()
            expect(page.get_by_text('记忆设置已保存',exact=True)).to_be_visible()
        expect(read_switch).not_to_be_checked();expect(save_switch).not_to_be_checked()
        current=employee.request.get(base+'/api/agent/memories/preferences').json();assert not current['readEnabled'] and not current['saveEnabled']
        page.reload(wait_until='networkidle');expect(read_switch).not_to_be_checked();expect(save_switch).not_to_be_checked()
        assert boss_context.request.get(base+'/api/agent/memories/preferences').json()['revision']==boss_original['revision']
        passed('settings_persist_across_reload_without_changing_another_account')
        conflict=employee.request.put(base+'/api/agent/memories/preferences',data={'expectedRevision':current['revision']-1,'readEnabled':True,'saveEnabled':True});assert conflict.status==409
        denied=employee.request.post(base+'/api/agent/memories/browser-memory-sample/delete',data={'requestId':uuid.uuid4().hex,'expectedDigest':'a'*64,'confirmed':False});assert denied.status==400
        passed('outdated_settings_and_unconfirmed_deletion_are_rejected_by_real_backend')
        page.get_by_role('button',name='删除记忆',exact=True).click();expect(page.get_by_role('dialog',name='删除长期记忆')).to_contain_text('验收报告按周统计');page.get_by_role('button',name='取消',exact=True).click();assert not requests
        passed('delete_confirmation_previews_the_selected_memory_and_cancel_does_not_mutate')
        stale=True;page.get_by_role('button',name='删除记忆',exact=True).click();page.get_by_role('button',name='确认删除',exact=True).click();expect(page.locator('.memory-page [role=alert]')).to_contain_text('记忆已变化');expect(page.locator('.memory-content')).to_be_visible();stale=False
        page.get_by_role('button',name='删除记忆',exact=True).click();page.get_by_role('button',name='确认删除',exact=True).click();expect(page.get_by_text('暂无已保存记忆',exact=True)).to_be_visible();assert len(requests)==2 and requests[0]['requestId']!=requests[1]['requestId']
        passed('stale_memory_is_retained_and_confirmed_fixture_deletion_removes_only_that_item')
        deleted=False;unavailable=True;page.get_by_role('button',name='刷新',exact=True).click();expect(page.get_by_text('记忆服务暂不可用',exact=True).first).to_be_visible();expect(page.locator('.memory-content')).to_have_count(0);unavailable=False;page.get_by_role('button',name='刷新',exact=True).click();expect(page.locator('.memory-content')).to_be_visible()
        passed('memory_service_failure_clears_old_data_and_is_not_reported_as_an_empty_success')
        page.screenshot(path=str(root/'work/memory-governance-desktop.png'),animations='disabled');page.set_viewport_size({'width':390,'height':844});page.locator('.memory-page').scroll_into_view_if_needed();bounds=page.locator('.memory-page').bounding_box();assert bounds['x']>=0 and bounds['x']+bounds['width']<=391;page.screenshot(path=str(root/'work/memory-governance-mobile.png'),animations='disabled');assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        boss.goto(base+'/#/agent/memory',wait_until='networkidle');expect(boss.get_by_role('heading',name='个人记忆',exact=True)).to_be_visible();expect(boss.locator('.memory-page')).not_to_contain_text(fixture['memory'])
        anonymous=browser.new_context();assert anonymous.request.get(base+'/api/agent/memories').status in (401,403);anonymous.close();assert not errors
        passed('mobile_layout_and_supervisor_personal_scope_and_anonymous_protection')
    finally:
        if original is not None:restore(employee,original)
        if boss_original is not None:restore(boss_context,boss_original)
        restored=original is not None and boss_original is not None
        (root/'work/memory-governance-browser-acceptance.json').write_text(json.dumps({'checks':checks,'passed':len(checks)==8 and not errors,'javascriptErrors':errors,'paidModelsCalled':False,'memoryMutationsWereUiFixtures':True,'settingsRestored':restored},ensure_ascii=False,indent=2),encoding='utf-8')
        employee.close();boss_context.close();browser.close()
