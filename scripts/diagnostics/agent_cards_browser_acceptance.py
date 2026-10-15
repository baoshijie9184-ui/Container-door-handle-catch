"""Actual persisted CHAT cards and business reads; React model stream alone uses a fixture."""
import json
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright, expect

root = Path(__file__).resolve().parents[2]
fixture = json.loads((root / 'work/agent-cards-local-mysql.json').read_text(encoding='utf-8'))
checks, errors, model_requests = [], [], []

def check(name, value=True):
    assert value, name
    checks.append({'name': name, 'passed': True})

def client(username):
    session = requests.Session(); session.trust_env = False
    response = session.post('http://127.0.0.1:8080/api/auth/login', json={'username': username, 'password': '123456'}, timeout=15)
    assert response.status_code == 200 and response.json()['code'] == 200
    return session

owner = client('inspector.demo'); other = client('inspector.demo2'); boss = client('supervisor.demo')
body = {'cards': fixture['envelope']['cards']}
response = owner.post('http://127.0.0.1:8080/api/agent/cards/resolve', json=body, timeout=15)
assert response.status_code == 200
views = response.json()['cards']
check('actual_cards_current_scope_and_no_cache', views[0]['items'][0]['taskId'] == fixture['taskId'] and response.headers['Cache-Control'] == 'no-store')
check('reassigned_task_removed_from_original_owner_card', views[1]['items'] == [] and views[1]['status'] == 'PARTIAL')
check('report_current_draft_summary_only', views[3]['items'][0]['status'] == 'DRAFT' and 'narrative' not in views[3]['items'][0])
foreign = other.post('http://127.0.0.1:8080/api/agent/cards/resolve', json=body, timeout=15).json()['cards']
check('other_account_cannot_read_original_task_or_private_report', not foreign[0]['items'] and not foreign[3]['items'])
supervisor = boss.post('http://127.0.0.1:8080/api/agent/cards/resolve', json={'cards': [body['cards'][3]]}, timeout=15).json()['cards']
check('supervisor_cannot_read_private_employee_draft', not supervisor[0]['items'])
response = owner.post('http://127.0.0.1:8080/api/agent/cards/resolve', json={'cards': [], 'userId': 2}, timeout=15)
check('identity_spoof_rejected', response.status_code == 400)
response = other.get(f"http://127.0.0.1:8080/api/chat-assistant/sessions/{fixture['sessionId']}/messages", timeout=15)
check('foreign_chat_history_rejected', response.status_code in (403, 404) or response.json().get('code') in (403, 404))
audit_url = 'http://127.0.0.1:8080/api/detection/reports/' + fixture['reportId'] + '/audit'
audit_before = owner.get(audit_url, timeout=15).json()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    def login(page):
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: model_requests.append(request.url) if request.method == 'POST' and '/api/chat-assistant/messages' in request.url else None)
        page.goto('http://127.0.0.1:3001/#/login', wait_until='networkidle')
        page.get_by_placeholder('请输入用户名').fill('inspector.demo'); page.get_by_placeholder('请输入密码').fill('123456')
        page.get_by_role('button', name='登录系统', exact=True).click(); page.wait_for_url('**/#/home')

    def select_fixture_session(page):
        sidebar = page.locator('.chat-sidebar')
        if 'collapsed' in (sidebar.get_attribute('class') or ''):
            page.get_by_title('展开会话列表', exact=True).click()
        page.locator('[data-session-id="' + fixture['sessionId'] + '"]').click()
        if page.viewport_size['width'] < 600 and page.get_by_title('收起会话列表', exact=True).count():
            page.get_by_title('收起会话列表', exact=True).click()

    context = browser.new_context(viewport={'width': 1440, 'height': 1100}); page = context.new_page(); login(page)
    page.goto('http://127.0.0.1:3001/#/agent/chat', wait_until='networkidle')
    select_fixture_session(page)
    cards = page.locator('.agent-result')
    expect(cards).to_have_count(1); expect(cards.locator('.result-card')).to_have_count(4)
    expect(cards.get_by_text(fixture['taskId'], exact=True)).to_be_visible()
    expect(cards.get_by_text('部分记录已不存在或当前无权访问', exact=True)).to_be_visible()
    expect(cards.get_by_text('私人草稿尚未提交或审批 请到报告页面核对', exact=True)).to_be_visible()
    check('vue_restores_actual_mysql_card_history')
    preview = page.locator('[data-session-id="' + fixture['sessionId'] + '"] .session-preview')
    expect(preview).to_contain_text('已查询授权任务和工作统计')
    check('session_preview_shows_answer_without_card_json', '"version"' not in preview.inner_text())
    expect(cards.locator('script')).to_have_count(0)
    expect(cards.get_by_role('link', name='卡片验收报告 <script>文本</script>', exact=True)).to_be_visible()
    check('report_title_rendered_as_text')
    page.screenshot(path=str(root / 'work/agent-cards-browser-vue.png'), full_page=True, animations='disabled')
    with page.expect_response(lambda response: '/api/agent/cards/resolve' in response.url):
        cards.get_by_role('button', name='刷新卡片', exact=True).click()
    expect(cards.locator('.result-card')).to_have_count(4)
    check('manual_refresh_reads_business_without_model_replay', not model_requests)
    page.reload(wait_until='networkidle'); select_fixture_session(page); expect(page.locator('.agent-result .result-card')).to_have_count(4)
    check('page_reload_restores_cards_without_model_replay', not model_requests)
    page.locator('.agent-result').get_by_role('link', name='查看报告', exact=True).click()
    page.wait_for_url('**/#/quality/reports?reportId=' + fixture['reportId'])
    expect(page.get_by_role('dialog', name='报告详情', exact=True)).to_contain_text('卡片验收报告 <script>文本</script>')
    check('card_link_opens_authorized_report')

    mobile = browser.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce'); mp = mobile.new_page(); login(mp)
    mp.goto('http://127.0.0.1:3001/#/agent/chat', wait_until='networkidle')
    select_fixture_session(mp)
    expect(mp.locator('.agent-result .result-card')).to_have_count(4)
    check('mobile_cards_no_horizontal_overflow', mp.locator('.agent-result').evaluate('(node) => node.scrollWidth <= node.clientWidth + 1'))
    mp.screenshot(path=str(root / 'work/agent-cards-browser-mobile.png'), full_page=True, animations='disabled')

    react = context.new_page()
    react.on('pageerror', lambda error: errors.append(str(error)))
    # Only model stream is intercepted; card resolve/login/report are actual HTTP and MySQL.
    frames = [ {'type': 'TEXT_MESSAGE_CONTENT', 'delta': fixture['envelope']['text']},
               {'type': 'CUSTOM', 'name': 'doorhandle.business-cards.v1', 'value': {'version': 1, 'cards': body['cards']}},
               {'type': 'RUN_FINISHED'} ]
    react.route('**/agui/run', lambda route: route.fulfill(status=200, content_type='text/event-stream', body=''.join('data: ' + json.dumps(event, ensure_ascii=False) + '\n\n' for event in frames)))
    react.goto('http://127.0.0.1:3003', wait_until='networkidle')
    sender = react.locator('textarea').first; sender.fill('卡片界面验收'); sender.press('Enter')
    try:
        expect(react.locator('.agent-result .result-card')).to_have_count(4)
    except Exception:
        react.screenshot(path=str(root / 'work/agent-cards-browser-react-debug.png'), full_page=True)
        (root / 'work/agent-cards-browser-react-debug.txt').write_text(react.locator('body').inner_text() + '\n' + json.dumps(errors), encoding='utf-8')
        raise
    expect(react.locator('.agent-result').get_by_text('私人草稿尚未提交或审批 请到报告页面核对', exact=True)).to_be_visible()
    check('react_custom_event_cards_read_actual_business_data')
    react.screenshot(path=str(root / 'work/agent-cards-browser-react.png'), full_page=True, animations='disabled')
    check('no_javascript_errors', not errors)
    browser.close()

check('card_reads_do_not_append_business_audit', owner.get(audit_url, timeout=15).json() == audit_before)
(root / 'work/agent-cards-browser-acceptance.json').write_text(json.dumps({'checks': checks, 'javascriptErrors': errors, 'primaryModelRequests': model_requests, 'reactModelStreamFixture': True, 'actualCardApiAndMysql': True}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'checks': len(checks), 'allPassed': True, 'artifact': 'work/agent-cards-browser-acceptance.json'}))
