"""Real read/authorization guards and isolated report delivery UI; no business decisions changed."""
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright,expect

root=Path(__file__).resolve().parents[2];base='http://127.0.0.1:3001'
checks=[];errors=[];writes=[];unavailable=False;conflict=False
report_id='qr-11111111-1111-1111-1111-111111111111';event_id='22222222-2222-2222-2222-222222222222'
report={'reportId':report_id,'ownerUserId':99999,'ownerUsername':'fixture.author','taskId':'fixture-task','title':'状态同步页面验收报告','narrative':'仅为页面隔离样本 不改变真实审批','version':3,'status':'APPROVED','source':{'totalImages':3,'successfulImages':3,'failedImages':0}}
event={'eventId':event_id,'eventType':'detection.report.approved.v1','deliveryStatus':'RETRY','attempts':2,'nextAttemptAt':'2026-10-14 16:00:00','deliveredAt':None,'lastErrorCode':'BROKER_UNAVAILABLE','consumedAt':None}

def passed(name):checks.append({'name':name,'passed':True})
def login(page,user):
    page.goto(base+'/#/login',wait_until='networkidle');page.get_by_placeholder('请输入用户名').fill(user);page.get_by_placeholder('请输入密码').fill('123456');page.get_by_role('button',name='登录系统',exact=True).click();page.wait_for_url('**/#/home')
def fixture_route(route):
    path=urlparse(route.request.url).path
    if path=='/api/detection/reports':data={'records':[report],'total':1}
    elif path.endswith('/events/'+event_id+'/retry'):
        body=route.request.post_data_json;writes.append(body)
        assert body['confirmed'] and body['expectedAttempts']==event['attempts'] and route.request.headers['x-report-action']=='update'
        if conflict:route.fulfill(status=409,json={'code':409,'message':'事件已变化或正在发送 请刷新后重试'});return
        event['deliveryStatus']='RETRY';data=[event]
    elif path.endswith('/events'):
        if unavailable:route.fulfill(status=503,json={'code':503,'message':'同步记录暂不可用'});return
        data=[event]
    elif path.endswith('/audit'):data=[]
    elif path.endswith('/'+report_id):data=report
    else:route.continue_();return
    route.fulfill(json={'code':200,'data':data})

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True);boss=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce');employee=browser.new_context()
    page=boss.new_page();staff=employee.new_page()
    for current in (page,staff):current.on('pageerror',lambda error:errors.append(str(error)))
    try:
        login(page,'supervisor.demo');login(staff,'inspector.demo')
        real=employee.request.get(base+'/api/detection/reports?page=1&size=20').json()['data']['records'];assert real
        owned=next(row for row in real if row['ownerUsername']=='inspector.demo');target=owned['reportId']
        history=employee.request.get(base+f'/api/detection/reports/{target}/events');assert history.ok and history.headers['cache-control']=='no-store'
        denied=employee.request.post(base+f'/api/detection/reports/{target}/events/{event_id}/retry',headers={'X-Report-Action':'update'},data={'expectedAttempts':1,'confirmed':True,'requestId':'browser-denied-request'});assert denied.status==403
        invalid=boss.request.post(base+f'/api/detection/reports/{target}/events/{event_id}/retry',headers={'X-Report-Action':'update'},data={'expectedAttempts':1,'confirmed':False,'requestId':'browser-unconfirmed-request'});assert invalid.status==400
        passed('real_events_are_uncacheable_and_employee_retry_and_unconfirmed_request_are_rejected')
        for current in (page,staff):current.route('**/api/detection/reports**',fixture_route)
        page.goto(base+'/#/quality/reports?reportId='+report_id,wait_until='networkidle')
        dialog=page.get_by_role('dialog',name='报告详情',exact=True);panel=dialog.get_by_role('region',name='报告状态同步')
        expect(dialog).to_be_visible();expect(panel).to_contain_text('等待重试');expect(panel).to_contain_text('等待接收确认')
        panel.get_by_role('button',name='重新发送',exact=True).click();confirmation=page.get_by_role('dialog',name='重新发送报告状态',exact=True)
        expect(confirmation).to_contain_text('不会重新执行审批');confirmation.get_by_role('button',name='取消',exact=True).click();assert not writes
        passed('supervisor_can_preview_delivery_retry_and_cancel_without_dispatch')
        panel.get_by_role('button',name='重新发送',exact=True).click();confirmation.get_by_role('button',name='确认重新发送',exact=True).click()
        expect(page.get_by_text('已安排重新发送',exact=True)).to_be_visible();assert len(writes)==1
        passed('confirmed_retry_sends_attempt_version_unique_request_and_operation_marker')
        conflict=True;panel.get_by_role('button',name='重新发送',exact=True).click();confirmation.get_by_role('button',name='确认重新发送',exact=True).click()
        expect(panel.get_by_role('alert')).to_contain_text('事件已变化');assert len(writes)==2 and writes[0]['requestId']==writes[1]['requestId']
        conflict=False;unavailable=True;panel.get_by_role('button',name='刷新同步状态',exact=True).click();expect(panel.get_by_role('alert')).to_contain_text('同步记录暂不可用')
        unavailable=False;event.update(deliveryStatus='DELIVERED',consumedAt='2026-10-14 16:20:00');panel.get_by_role('button',name='刷新同步状态',exact=True).click()
        expect(panel).to_contain_text('已发送');expect(panel).to_contain_text('已接收');expect(panel.get_by_role('button',name='重新发送',exact=True)).to_have_count(0)
        passed('conflict_and_unavailable_state_are_visible_then_sent_and_received_are_distinguished')
        staff.goto(base+'/#/quality/reports?reportId='+report_id,wait_until='networkidle');staff_panel=staff.get_by_role('region',name='报告状态同步');expect(staff_panel).to_contain_text('已接收');expect(staff_panel.get_by_role('button',name='重新发送',exact=True)).to_have_count(0)
        panel.scroll_into_view_if_needed();page.screenshot(path=str(root/'work/report-events-desktop.png'),animations='disabled')
        page.set_viewport_size({'width':390,'height':844});panel.scroll_into_view_if_needed();bounds=dialog.bounding_box();assert bounds['x']>=0 and bounds['x']+bounds['width']<=391
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(root/'work/report-events-mobile.png'),animations='disabled');assert not errors
        passed('employee_has_read_only_delivery_view_and_mobile_dialog_remains_within_viewport')
    finally:
        (root/'work/report-events-browser-acceptance.json').write_text(json.dumps({'checks':checks,'passed':len(checks)==5 and not errors,'javascriptErrors':errors,'realBusinessDecisionsChanged':False,'uiWritesWereFixtures':True,'paidModelsCalled':False},ensure_ascii=False,indent=2),encoding='utf-8')
        boss.close();employee.close();browser.close()
