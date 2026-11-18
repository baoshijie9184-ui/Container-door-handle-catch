"""Headless browser acceptance of the report page using report_local_acceptance.py fixtures."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root=Path(__file__).resolve().parents[2]
fixture=json.loads((root/'work/report-local-acceptance.json').read_text(encoding='utf-8'))
checks=[];errors=[];native_dialogs=[]
def check(name,value=True):
    assert value,name
    checks.append({'name':name,'passed':True})
def login(page,username):
    page.goto('http://127.0.0.1:3001/#/login',wait_until='networkidle')
    page.get_by_placeholder('请输入用户名').fill(username);page.get_by_placeholder('请输入密码').fill('123456')
    page.get_by_role('button',name='登录系统',exact=True).click();page.wait_for_url('**/#/home')
def report_page(page,query):
    page.goto('http://127.0.0.1:3001/#/quality/reports',wait_until='networkidle')
    search=page.get_by_placeholder('查询任务编号或报告标题');expect(search).to_be_visible();search.fill(query)
    with page.expect_response(lambda r:'/api/detection/reports?' in r.url and r.request.method=='GET'):
        page.get_by_role('button',name='查询',exact=True).click()
def observe(page):
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('dialog',lambda d:(native_dialogs.append(d.message),d.dismiss()))

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    boss_context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
    boss=boss_context.new_page();observe(boss)
    decisions=[];boss.on('request',lambda r:decisions.append(r.url) if r.method=='POST' and r.url.endswith('/decision') else None)
    login(boss,'supervisor.demo');report_page(boss,fixture['taskIds'][0])
    row=boss.locator('.el-table__body tr').filter(has_text=fixture['taskIds'][0]).filter(has_text='待审批');expect(row).to_have_count(1)
    row.get_by_role('button',name='查看',exact=True).click()
    detail=boss.get_by_role('dialog',name='报告详情',exact=True)
    expect(detail.get_by_role('button',name='审批通过',exact=True)).to_be_visible()
    detail.get_by_role('button',name='审批通过',exact=True).click()
    decision=boss.get_by_role('dialog',name='报告审批通过',exact=True)
    decision.get_by_placeholder('填写本次审批依据与意见').fill('浏览器核对检测依据并批准')
    decision.get_by_role('button',name='预览审批操作',exact=True).click()
    expect(decision.get_by_text('确认审批内容',exact=True)).to_be_visible()
    check('preview_does_not_execute',len(decisions)==0)
    boss.screenshot(path=str(root/'work/report-browser-confirmation.png'),full_page=True)
    with boss.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/decision')) as response:
        decision.get_by_role('button',name='确认审批通过',exact=True).click()
    assert response.value.status==200
    expect(decision).not_to_be_visible();expect(detail.get_by_role('button',name='导出已审批报告',exact=True)).to_be_visible()
    check('confirm_sends_exactly_one_decision',len(decisions)==1)
    with boss.expect_download() as download:
        detail.get_by_role('button',name='导出已审批报告',exact=True).click()
    output=root/'work/report-browser-approved.md';download.value.save_as(output)
    text=output.read_text(encoding='utf-8')
    check('approved_markdown_download', '已审批检测报告' in text and '浏览器核对检测依据并批准' in text and '<script>' not in text)
    expect(detail.locator('.el-table__body tr').filter(has_text='导出')).to_have_count(1)
    check('export_has_visible_audit')
    boss.keyboard.press('Escape');expect(detail).not_to_be_visible()
    boss.reload(wait_until='networkidle');expect(boss.get_by_placeholder('查询任务编号或报告标题')).to_be_visible()
    check('reload_does_not_repeat_decision',len(decisions)==1)

    staff_context=browser.new_context(viewport={'width':1440,'height':1000})
    staff=staff_context.new_page();observe(staff);login(staff,'inspector.demo')
    report_page(staff,fixture['prefix'])
    staff.get_by_role('button',name='新建报告草稿',exact=True).click()
    editor=staff.get_by_role('dialog',name='新建报告草稿',exact=True)
    title=fixture['prefix']+' 浏览器草稿'
    editor.get_by_placeholder('输入已完成检测任务编号').fill(fixture['taskIds'][0])
    editor.get_by_placeholder('报告标题',exact=True).fill(title)
    editor.get_by_placeholder('记录复核说明、风险和建议，检测数量以系统依据为准').fill('浏览器编写意见 <script>alert(99)</script>')
    with staff.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/detection/reports')) as created:
        editor.get_by_role('button',name='保存草稿',exact=True).click()
    report_id=created.value.json()['data']['reportId']
    own=staff.get_by_role('dialog',name='报告详情',exact=True)
    expect(own.get_by_role('button',name='提交主管审批',exact=True)).to_be_visible()
    expect(own.get_by_text('浏览器编写意见 <script>alert(99)</script>',exact=True)).to_be_visible()
    check('employee_creates_plain_text_private_draft')
    own.get_by_role('button',name='提交主管审批',exact=True).click()
    submit=staff.get_by_role('dialog',name='提交主管审批',exact=True)
    submit.get_by_role('button',name='确认提交',exact=True).click()
    expect(submit).not_to_be_visible();expect(own.get_by_role('button',name='撤回申请',exact=True)).to_be_visible()
    expect(own.get_by_role('button',name='编辑草稿',exact=True)).to_have_count(0)
    expect(own.get_by_role('button',name='审批通过',exact=True)).to_have_count(0)
    check('submitted_employee_report_is_read_only')
    staff.screenshot(path=str(root/'work/report-browser-employee.png'),full_page=True)
    staff.set_viewport_size({'width':390,'height':844});staff.emulate_media(reduced_motion='reduce')
    expect(own.get_by_role('button',name='撤回申请',exact=True)).to_be_visible()
    check('mobile_detail_has_no_horizontal_overflow',staff.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
    withdraw=own.get_by_role('button',name='撤回申请',exact=True)
    withdraw.scroll_into_view_if_needed()
    check('mobile_actions_reachable_in_dialog',withdraw.evaluate('(e)=>{const r=e.getBoundingClientRect();return r.top>=0 && r.bottom<=window.innerHeight}'))
    staff.screenshot(path=str(root/'work/report-browser-mobile.png'),full_page=True)

    other_context=browser.new_context(viewport={'width':1440,'height':1000})
    other=other_context.new_page();observe(other);login(other,'inspector.demo2');report_page(other,title)
    expect(other.locator('.el-table__body tr')).to_have_count(0)
    check('other_employee_cannot_find_report')
    check('no_script_execution_or_javascript_errors',not errors and not native_dialogs)
    browser.close()

result={'checks':checks,'javascriptErrors':errors,'scriptDialogs':native_dialogs,'browserCreatedReportId':report_id,'fixturePrefix':fixture['prefix'],'fixtureDataRetained':True}
(root/'work/report-browser-acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'checks':len(checks),'allPassed':True,'artifact':'work/report-browser-acceptance.json'}))
