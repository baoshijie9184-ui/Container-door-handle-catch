"""Read-only live resource catalog acceptance; never calls or installs external resources."""
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
checks, errors = [], []

def passed(name):
    checks.append({"name": name, "passed": True})

def login(page, username):
    page.goto('http://127.0.0.1:3001/#/login', wait_until='networkidle')
    page.get_by_placeholder('请输入用户名').fill(username)
    page.get_by_placeholder('请输入密码').fill('123456')
    page.get_by_role('button', name='登录系统', exact=True).click()
    page.wait_for_url('**/#/home')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    anonymous = browser.new_context()
    assert anonymous.request.get('http://127.0.0.1:3001/api/agent/markets').status in (401, 403)
    page = anonymous.new_page()
    page.goto('http://127.0.0.1:3001/#/agent/markets', wait_until='networkidle')
    expect(page.get_by_placeholder('请输入用户名')).to_be_visible()
    passed('anonymous_api_and_route_require_login')
    anonymous.close()

    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
    page = context.new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))
    login(page, 'inspector.demo')
    page.goto('http://127.0.0.1:3001/#/agent/markets', wait_until='networkidle')
    cards = page.locator('.market-item')
    expect(cards).to_have_count(11)
    response = context.request.get('http://127.0.0.1:3001/api/agent/markets')
    assert response.ok and response.headers['cache-control'] == 'no-store'
    catalog = response.json()
    assert catalog['integrationStatus'] == 'DIRECTORY_ONLY'
    assert len({m['id'] for m in catalog['markets']}) == 11
    passed('employee_live_catalog_has_11_sources_and_no_runtime_authorization')

    for link in page.locator('.market-item a').all():
        assert urlparse(link.get_attribute('href')).scheme == 'https'
        assert link.get_attribute('target') == '_blank'
        assert {'noopener', 'noreferrer'} <= set(link.get_attribute('rel').split())
        assert link.get_attribute('referrerpolicy') == 'no-referrer'
    passed('external_links_use_https_and_isolate_login_context')

    page.get_by_role('button', name='Agent 智能体', exact=False).click()
    expect(cards).to_have_count(3)
    expect(cards.filter(has_text='魔搭智能工坊')).to_have_count(1)
    expect(cards.filter(has_text='MCP.so')).to_have_count(1)
    passed('agent_category_does_not_treat_unverified_sources_as_available')
    page.get_by_role('button', name='MCP 工具', exact=False).click()
    expect(cards).to_have_count(5)
    expect(cards.filter(has_text='SkillsMP')).to_have_count(0)
    page.get_by_role('checkbox', name='包含仅提供 MCP 接口的平台').check()
    expect(cards).to_have_count(6)
    expect(cards.filter(has_text='SkillsMP')).to_have_count(1)
    passed('mcp_market_and_skill_search_interface_are_distinct')
    page.get_by_role('button', name='Skill 技能', exact=False).click()
    expect(cards).to_have_count(9)
    page.get_by_role('textbox', name='搜索平台或能力').fill('阿里云')
    expect(cards).to_have_count(3)
    page.get_by_role('combobox', name='市场地区').press('ArrowDown')
    page.get_by_role('option', name='国内', exact=True).click()
    expect(cards).to_have_count(3)
    page.get_by_role('textbox', name='搜索平台或能力').fill('no-match-resource-fixture')
    expect(cards).to_have_count(0)
    expect(page.get_by_text('没有匹配的平台 试试其他关键词或分类')).to_be_visible()
    passed('skill_search_region_intersection_and_empty_state')
    page.get_by_role('textbox', name='搜索平台或能力').fill('百炼')
    cards.get_by_role('button', name='能力与接入说明').click()
    dialog = page.get_by_role('dialog', name='平台能力与接入说明')
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text('不等同于可下载的 AgentScope 模板')
    expect(dialog.get_by_role('link', name='查看核实来源')).to_have_attribute('href', 'https://docs.agent.bailian.aliyun.com/en/flow-agent/applications/agent-app')
    dialog.get_by_role('button', name='关闭', exact=True).click()
    passed('managed_agent_details_and_primary_source_are_visible')
    page.get_by_role('textbox', name='搜索平台或能力').fill('')
    page.get_by_role('button', name='全部平台', exact=False).click()
    page.get_by_role('combobox', name='市场地区').press('ArrowDown')
    page.get_by_role('option', name='全部地区', exact=True).click()
    expect(cards).to_have_count(11)
    page.screenshot(path=str(ROOT / 'work/agent-market-desktop.png'), full_page=True, animations='disabled')
    page.route('**/api/agent/markets', lambda route: route.fulfill(status=503, content_type='application/json', body='{"message":"目录验收临时不可用"}'))
    page.get_by_role('button', name='刷新目录').click()
    expect(page.locator('.market-page [role="alert"]')).to_contain_text('目录验收临时不可用')
    expect(cards).to_have_count(0)
    passed('refresh_failure_hides_previous_catalog')
    context.close()

    context = browser.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
    page = context.new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))
    login(page, 'supervisor.demo')
    page.goto('http://127.0.0.1:3001/#/agent/markets', wait_until='networkidle')
    expect(page.locator('.market-item')).to_have_count(11)
    assert context.request.get('http://127.0.0.1:3001/api/agent/markets').json()['markets'] == catalog['markets']
    assert page.locator('.market-page').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
    page.locator('.market-item').filter(has_text='魔搭智能工坊').get_by_role('button', name='能力与接入说明').click()
    dialog = page.get_by_role('dialog', name='平台能力与接入说明')
    expect(dialog).to_be_visible()
    bounds = dialog.bounding_box()
    assert bounds['x'] >= 0 and bounds['y'] >= 0 and bounds['x'] + bounds['width'] <= 391 and bounds['y'] + bounds['height'] <= 845
    assert dialog.locator('.el-dialog__body').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
    page.screenshot(path=str(ROOT / 'work/agent-market-mobile.png'), full_page=True, animations='disabled')
    passed('supervisor_catalog_and_mobile_dialog_fit_viewport')
    context.close()
    browser.close()

assert not errors
(ROOT / 'work/agent-market-browser-acceptance.json').write_text(json.dumps({'checks': checks, 'javascriptErrors': errors, 'readOnly': True, 'externalServicesCalled': False}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'checks': len(checks), 'allPassed': True}))
