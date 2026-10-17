"""Browser UI regression with isolated API fixtures; never connects to ECS or an LLM.

Run both Vite frontends on ports 3011/5175, then use the project's leetcode Python.
Screenshots and a result manifest are written under work/ui-refresh.
"""
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'work/ui-refresh'
OUT.mkdir(parents=True, exist_ok=True)
results = []
failures = []
sessions = {
    'demo-empty': {'sessionId': 'demo-empty', 'title': '新对话', 'messages': []},
    'demo-history': {'sessionId': 'demo-history', 'title': '检测任务与质检进度', 'messages': [
        {'id': 1, 'role': 'user', 'messageType': 'TEXT', 'content': '查看最近的检测情况', 'createdAt': '2026-10-16T10:00:00'},
        {'id': 2, 'role': 'assistant', 'messageType': 'TEXT', 'content': '已整理你有权限查看的检测结果。\n\n**下一步建议**\n- 查看任务处理进度\n- 核对质检记录\n\n这是一条界面测试数据，不代表真实业务统计。', 'createdAt': '2026-10-16T10:00:02'},
    ]},
}

def reply(route, data, raw=False, status=200):
    route.fulfill(status=status, content_type='application/json', body=json.dumps(data if raw else {'code': 200, 'data': data}, ensure_ascii=False))

def api(route):
    req = route.request
    path = urlparse(req.url).path
    if not path.startswith(('/api/', '/agui/')):
        return route.continue_()
    if path == '/api/auth/check':
        return reply(route, {'username': 'supervisor.demo', 'role': 'SUPERVISOR', 'identity': {'departmentName': '质检中心'}})
    if path == '/api/chat-assistant/sessions':
        if req.method == 'POST':
            sessions['demo-empty']['messages'] = []
            return reply(route, sessions['demo-empty'])
        return reply(route, list(sessions.values()))
    if path.startswith('/api/chat-assistant/sessions/'):
        sid = path.split('/')[4]
        if path.endswith('/trace'): return reply(route, {'events': [], 'status': 'COMPLETED'})
        return reply(route, sessions.get(sid, sessions['demo-empty']))
    if path == '/api/chat-assistant/session': return reply(route, sessions['demo-empty'])
    if path == '/api/chat-projects': return reply(route, [])
    if path == '/api/agent/actions': return reply(route, [], raw=True)
    if path == '/api/agent/commands':
        return reply(route, {'enabled': True, 'skills': []}, raw=True)
    if path.endswith('/agent-health'):
        return reply(route, {'framework': 'AgentScope', 'mode': 'CONFIRMABLE', 'defaultModel': 'deepseek-flash'})
    if path == '/agui/catalog':
        return reply(route, {'role': 'SUPERVISOR', 'mainAgent': 'supervisor', 'mode': 'CONFIRMABLE', 'reportsEnabled': True, 'reportDraftsEnabled': True, 'agents': [{'id': 'detection', 'description': '查询检测任务与处理进度'}, {'id': 'quality', 'description': '查询质检记录与工作统计'}]}, raw=True)
    if path == '/agui/models':
        return reply(route, {'models': [{'id': 'deepseek:deepseek-flash', 'model': 'deepseek-flash', 'selected': True, 'configured': True, 'healthState': 'CLOSED'}, {'id': 'dashscope:kimi-k3', 'model': 'kimi-k3', 'selected': False, 'configured': True, 'healthState': 'CLOSED'}], 'fallbackEnabled': True, 'firstTokenTimeoutMs': 10000, 'fallbackModels': ['dashscope:kimi-k3']}, raw=True)
    if path in ('/api/chat-assistant/messages/stream', '/agui/run'):
        body = req.post_data_json
        sid = body.get('sessionId') or body.get('threadId')
        question = body.get('content') or body['messages'][0]['content']
        answer = '已收到测试问题，会话历史与页面展示正常。'
        messages = sessions[sid]['messages']
        messages.extend([{'id': len(messages)+10, 'role': 'user', 'messageType': 'TEXT', 'content': question}, {'id': len(messages)+11, 'role': 'assistant', 'messageType': 'TEXT', 'content': answer}])
        frames = ([{'type': 'TEXT_MESSAGE_CONTENT', 'delta': answer}, {'type': 'RUN_FINISHED'}] if path == '/agui/run' else None)
        text = ''.join('data: '+json.dumps(frame, ensure_ascii=False)+'\n\n' for frame in frames) if frames else 'event: chunk\ndata: '+json.dumps({'content': answer}, ensure_ascii=False)+'\n\nevent: done\ndata: '+json.dumps({'content': answer, 'sessionId': sid}, ensure_ascii=False)+'\n\n'
        return route.fulfill(content_type='text/event-stream', body=text)
    if path.endswith('work-unit-summary'): return reply(route, {'scope': 'DEPARTMENT', 'counts': {'WAITING': 3, 'ASSIGNED': 8, 'PROCESSING': 4, 'SUBMITTED': 6}})
    if path.endswith('duplicate-summary'): return reply(route, {'scope': 'DEPARTMENT', 'counts': {'OPEN': 1, 'ASSIGNED': 2, 'COMPARING': 1, 'PENDING_APPROVAL': 0}})
    if path == '/api/dashboard/stats': return reply(route, {'detectionCount': 128, 'employeeCount': 12, 'deviceCount': 8, 'avgMissRate': .01})
    if path == '/api/devices/stats': return reply(route, {'total': 8, 'inUse': 6, 'offline': 1, 'maintenance': 1, 'idle': 0})
    if path == '/api/employees/stats': return reply(route, {'total': 12, 'active': 10, 'vacation': 2, 'resigned': 0})
    return reply(route, [])

def check(name, assertion):
    try:
        assertion()
        results.append({'name': name, 'passed': True})
    except Exception as error:
        results.append({'name': name, 'passed': False, 'error': str(error)})
        failures.append(name)

def no_overflow(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'horizontal document overflow'

def screenshot(page, name):
    # Capture the settled appearance after the deliberate 180–250 ms transitions.
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT / (name+'.png')), full_page=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
    context.route('**/api/**', api)
    context.route('**/agui/**', api)
    errors = []
    context.on('page', lambda page: page.on('pageerror', lambda error: errors.append(str(error))))
    page = context.new_page()
    page.goto('http://127.0.0.1:3011/#/login')
    page.wait_for_load_state('networkidle')
    check('login form available', lambda: expect(page.get_by_placeholder('请输入用户名')).to_be_visible())
    screenshot(page, 'vue-login-desktop')
    page.goto('http://127.0.0.1:3011/#/agent/chat')
    page.wait_for_load_state('networkidle')
    check('embedded chat keeps navigation visible', lambda: expect(page.get_by_role('complementary', name='系统导航')).to_be_visible())
    check('chat is embedded without a modal overlay', lambda: expect(page.locator('.el-overlay:visible')).to_have_count(0))
    check('welcome prompts visible', lambda: expect(page.locator('.welcome-prompt')).to_have_count(4))
    check('desktop no horizontal overflow', lambda: no_overflow(page))
    screenshot(page, 'vue-chat-desktop')
    page.locator('.brand-mark').click()
    check('desktop main navigation collapses', lambda: expect(page.locator('.layout-shell')).to_have_class('layout-shell sidebar-collapsed is-agent-workspace'))
    page.locator('.brand-mark').click()
    page.get_by_role('button', name='查看检测进度').click()
    check('Vue chat sends and restores server history', lambda: expect(page.locator('.msg-content').filter(has_text='已收到测试问题')).to_be_visible())
    screenshot(page, 'vue-chat-conversation')
    page.get_by_role('button', name='Agent诊断').click()
    check('Vue diagnostics open', lambda: expect(page.get_by_text('智能体运行诊断')).to_be_visible())
    page.get_by_role('button', name='关闭诊断').click()
    page.set_viewport_size({'width': 390, 'height': 844})
    expect(page.locator('.layout-sidebar')).to_have_css('width', '56px')
    expect(page.locator('.chat-sidebar')).to_have_class('chat-sidebar collapsed compact')
    page.wait_for_timeout(250)
    check('Vue mobile chat keeps usable reading width', lambda: (_ for _ in ()).throw(AssertionError('chat main narrower than 250px')) if page.locator('.chat-main').bounding_box()['width'] < 250 else None)
    check('Vue mobile no horizontal overflow', lambda: no_overflow(page))
    screenshot(page, 'vue-chat-mobile')
    page.get_by_role('button', name='展开会话列表', exact=True).click()
    check('Vue mobile history uses overlay without squeezing chat', lambda: expect(page.locator('.session-backdrop')).to_be_visible())
    backdrop=page.get_by_role('button', name='关闭会话列表', exact=True)
    # The sidebar covers the backdrop's centre; click its visible right-hand strip.
    backdrop.click(position={'x':backdrop.bounding_box()['width']-8,'y':80})
    page.locator('.nav-menu .el-sub-menu__title').last.hover()
    check('mobile business menu remains accessible', lambda: expect(page.locator('.el-menu--popup:visible')).to_have_count(1))
    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.goto('http://127.0.0.1:3011/#/home')
    page.wait_for_load_state('networkidle')
    check('home dashboard loads', lambda: expect(page.locator('.hero-title')).to_be_visible())
    screenshot(page, 'vue-home-desktop')
    page.locator('.launcher-btn').click()
    check('business page assistant still opens as a drawer', lambda: expect(page.locator('.el-drawer:visible')).to_have_count(1))
    screenshot(page, 'vue-assistant-drawer')

    sessions['demo-empty']['messages'] = []
    agent = context.new_page()
    agent.goto('http://127.0.0.1:5175/', timeout=120000)
    agent.wait_for_load_state('networkidle')
    check('React welcome prompts visible', lambda: expect(agent.locator('.welcome-prompts > button')).to_have_count(4))
    agent.wait_for_timeout(300)
    check('React welcome remains within visible transcript', lambda: (_ for _ in ()).throw(AssertionError('welcome scrolled out of viewport')) if agent.locator('.chat-welcome').bounding_box()['y'] < 78 else None)
    check('React desktop no horizontal overflow', lambda: no_overflow(agent))
    screenshot(agent, 'react-chat-desktop')
    agent.get_by_role('button', name='查看助手信息').click()
    agent.get_by_role('tab',name='模型与能力',exact=True).click()
    check('React model panel accessible', lambda: expect(agent.get_by_text('模型与备用')).to_be_visible())
    agent.keyboard.press('Escape')
    check('React Escape restores panel toggle focus', lambda: expect(agent.get_by_role('button', name='查看助手信息')).to_be_focused())
    agent.get_by_role('button', name='查看检测进度').click()
    check('React prompt fills composer without sending', lambda: expect(agent.locator('[data-sender-input]')).to_have_value('查询最近的检测任务和处理进度'))
    agent.locator('[data-sender-input]').press('Enter')
    check('React chat sends and restores server history', lambda: expect(agent.get_by_text('已收到测试问题，会话历史与页面展示正常。')).to_be_visible())
    screenshot(agent, 'react-chat-conversation')
    agent.get_by_role('button', name='新建对话', exact=True).click()
    check('React new session shows welcome', lambda: expect(agent.get_by_role('heading', name='今天有什么需要我协助？')).to_be_visible())
    agent.set_viewport_size({'width': 390, 'height': 844})
    agent.wait_for_timeout(300)
    check('React mobile transcript uses full width', lambda: expect(agent.locator('.agent-main')).to_have_css('width', '390px'))
    check('React mobile no horizontal overflow', lambda: no_overflow(agent))
    screenshot(agent, 'react-chat-mobile')
    agent.get_by_role('button', name='展开会话列表').click()
    check('React mobile history opens', lambda: expect(agent.get_by_role('navigation', name='对话历史')).to_be_visible())
    agent.keyboard.press('Escape')
    check('React mobile Escape closes history', lambda: expect(agent.get_by_role('navigation', name='对话历史')).to_be_hidden())
    agent.get_by_role('button', name='查看助手信息').click()
    check('React mobile assistant information remains reachable', lambda: expect(agent.get_by_text('模型与备用')).to_be_visible())
    screenshot(agent, 'react-info-mobile')
    agent.keyboard.press('Escape')
    agent.set_viewport_size({'width': 1024, 'height': 768})
    check('React tablet no horizontal overflow', lambda: no_overflow(agent))
    screenshot(agent, 'react-chat-tablet')
    agent.emulate_media(reduced_motion='reduce')
    check('reduced motion disables shell transition', lambda: expect(agent.locator('.agent-shell')).to_have_css('transition-duration', '1e-05s'))
    check('no browser JavaScript errors', lambda: (_ for _ in ()).throw(AssertionError(errors)) if errors else None)
    browser.close()

(OUT/'results.json').write_text(json.dumps({'mode': 'isolated API fixtures', 'checks': results, 'javascriptErrors': errors}, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps({'passed': sum(r['passed'] for r in results), 'failed': failures, 'javascriptErrors': errors}, ensure_ascii=False))
if failures: raise SystemExit(1)
