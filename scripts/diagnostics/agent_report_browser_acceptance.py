"""Read-only UI/API acceptance using AgentReportLocalMysqlTest's retained report and run."""
import json
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright,expect

root=Path(__file__).resolve().parents[2]
fixture=json.loads((root/'work/agent-report-local-mysql.json').read_text(encoding='utf-8'))
checks=[];errors=[]
def check(name,value=True):
    assert value,name
    checks.append({'name':name,'passed':True})
def login_api(username):
    client=requests.Session();client.trust_env=False
    response=client.post('http://127.0.0.1:8080/api/auth/login',json={'username':username,'password':'123456'},timeout=15)
    assert response.status_code==200 and response.json()['code']==200
    return client
for name in ('inspector.demo','supervisor.demo'):
    client=login_api(name)
    catalog=client.get('http://127.0.0.1:8080/agui/catalog',timeout=15).json()
    tools=next(a['tools'] for a in catalog['agents'] if a['id']=='report-assistant')
    check(name+'_catalog_five_specialists',len(catalog['agents'])==5)
    check(name+'_only_report_queries_and_drafts',set(tools)=={'list_quality_reports','get_quality_report','create_report_draft','edit_report_draft'} and catalog['reportDraftsEnabled'])
    health=client.get('http://127.0.0.1:8080/api/chat-assistant/agent-health',timeout=15).json()['data']
    check(name+'_health_report_capability',health['reportsEnabled'] and health['reportDraftsEnabled'])

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    def login(page,username):
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:3001/#/login',wait_until='networkidle')
        page.get_by_placeholder('请输入用户名').fill(username);page.get_by_placeholder('请输入密码').fill('123456')
        page.get_by_role('button',name='登录系统',exact=True).click();page.wait_for_url('**/#/home')
    context=browser.new_context(viewport={'width':1440,'height':1000});page=context.new_page();login(page,'inspector.demo')
    page.goto('http://127.0.0.1:3001/#/quality/reports?reportId='+fixture['reportId'],wait_until='networkidle')
    dialog=page.get_by_role('dialog',name='报告详情',exact=True)
    expect(dialog.get_by_text('修改后草稿',exact=True)).to_be_visible()
    expect(dialog.locator('.el-table__body tr')).to_have_count(2)
    links=dialog.get_by_role('link',name='助手运行轨迹',exact=True);expect(links).to_have_count(2)
    check('report_deep_link_and_origin_visible')
    page.screenshot(path=str(root/'work/agent-report-browser-origin.png'),full_page=True)
    links.first.click();page.wait_for_url('**/#/agent/trace?runId='+fixture['runId'])
    expect(page.locator('.run-id')).to_contain_text(fixture['runId'])
    expect(page.locator('.el-table__body tr').filter(has_text='create_report_draft')).not_to_have_count(0)
    check('origin_link_opens_exact_authorized_run')
    page.screenshot(path=str(root/'work/agent-report-browser-trace.png'),full_page=True)
    page.goto('http://127.0.0.1:3003',wait_until='networkidle')
    expect(page.get_by_text('查询与本人报告草稿',exact=True)).to_be_visible()
    expect(page.get_by_role('link',name='报告与审批',exact=True)).to_be_visible()
    check('react_report_entry_and_capability_visible')
    page.screenshot(path=str(root/'work/agent-report-browser-react.png'),full_page=True)
    other_context=browser.new_context(viewport={'width':1440,'height':1000});other=other_context.new_page();login(other,'inspector.demo2')
    other.goto('http://127.0.0.1:3001/#/quality/reports?reportId='+fixture['reportId'],wait_until='networkidle')
    denied=other.get_by_role('dialog',name='报告详情',exact=True);expect(denied).to_contain_text('报告不存在或无访问权限')
    expect(denied.get_by_text('修改后草稿',exact=True)).to_have_count(0)
    check('other_account_report_deep_link_denied')
    other.goto('http://127.0.0.1:3001/#/agent/trace?runId='+fixture['runId'],wait_until='networkidle')
    expect(other.locator('.history-error')).to_be_visible()
    check('other_account_original_run_denied')
    check('no_javascript_errors',not errors)
    browser.close()
(root/'work/agent-report-browser-acceptance.json').write_text(json.dumps({'checks':checks,'javascriptErrors':errors,'reportId':fixture['reportId'],'runId':fixture['runId']},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'checks':len(checks),'allPassed':True,'artifact':'work/agent-report-browser-acceptance.json'}))
