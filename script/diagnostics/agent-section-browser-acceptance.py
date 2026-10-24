"""Read-only visual checks against the existing ECS through the local frontend proxy."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'work/agent-section'
OUT.mkdir(parents=True, exist_ok=True)
checks, errors = [], []
BASE = 'http://127.0.0.1:3012'

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for label, width, height in [('desktop', 1500, 1000), ('mobile', 390, 844)]:
        context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce')
        response = context.request.post(BASE + '/api/auth/login', data={'username': 'supervisor.demo', 'password': '123456'})
        assert response.status == 200 and response.json().get('code') == 200
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        for route, kind in [('markets','markets'), ('skills','skills'), ('memory','memory'), ('mcp','mcp'), ('actions','actions'), ('model-config','models'), ('trace',None), ('chat',None)]:
            page.goto(BASE + '/#/agent/' + route)
            page.wait_for_load_state('networkidle')
            expect(page.get_by_role('navigation', name='Agent 导航', exact=True)).to_be_visible()
            assert page.locator('.agent-app-rail').bounding_box()['width'] <= 72
            assert page.get_by_role('complementary', name='系统导航', exact=True).count() == 0
            if kind:
                icon = page.locator(f'.agent-section-icon[data-tone="{kind}"]:not(.small)')
                expect(icon).to_be_visible()
                assert icon.locator('svg').count() == 1
            if route == 'chat':
                expect(page.locator('.agent-chat-page')).to_be_visible()
                expect(page.locator('.layout-header')).to_have_count(0)
                expect(page.get_by_label('使用模型', exact=True)).to_be_visible()
            if route == 'trace':
                expect(page.locator('.trace-workspace')).to_be_visible()
            if route == 'model-config':
                expect(page.locator('.model-config-page .el-alert')).to_be_visible()
            page.wait_for_load_state('networkidle')
            expect(page.locator('.el-loading-mask:visible')).to_have_count(0, timeout=25000)
            assert page.locator('.global-error-bar').count() == 0
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            page.keyboard.press('Tab')
            assert page.evaluate('document.activeElement.tagName') != 'BODY'
            page.evaluate('document.activeElement.blur()')
            page.screenshot(path=str(OUT / f'{route}-{label}.png'), full_page=True)
            checks.append(f'{label} {route}: real API, navigation, icon, focus and no overflow or render exception')
        page.get_by_role('button', name='账号菜单 supervisor.demo', exact=True).click()
        expect(page.get_by_role('menuitem', name='退出登录', exact=True)).to_be_visible()
        page.keyboard.press('Escape')
        checks.append(label + ' account and logout remain reachable')
        page.get_by_role('link', name='返回业务系统', exact=True).click()
        expect(page.get_by_role('complementary', name='系统导航', exact=True)).to_be_visible()
        expect(page.get_by_role('navigation', name='Agent 导航', exact=True)).to_have_count(0)
        checks.append(label + ' returning to business restores its original navigation')
        context.close()
    browser.close()
assert not errors, errors
(OUT / 'results.json').write_text(json.dumps({'scope': 'real ECS read-only pages, no supplier calls or configuration writes', 'checks': checks, 'javascriptErrors': errors}, ensure_ascii=False, indent=2), 'utf-8')
print(json.dumps({'passed': len(checks), 'javascriptErrors': errors}))
