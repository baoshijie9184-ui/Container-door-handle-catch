"""Agent appearance checks using isolated API fixtures, without model calls."""
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'work/agent-appearance'
OUT.mkdir(parents=True, exist_ok=True)
fixture = {'__file__': str(ROOT / 'script/diagnostics/conversation-control-acceptance.py')}
exec((ROOT / 'script/diagnostics/conversation-control-acceptance.py').read_text('utf-8').split('with sync_playwright() as p:')[0], fixture)
checks, errors = [], []

def api(route):
    path = urlparse(route.request.url).path
    reply = fixture['reply']
    if path == '/agui/models':
        return reply(route, {'selectedModel': 'deepseek:demo', 'models': [
            {'id': 'deepseek:demo', 'provider': 'deepseek', 'model': 'DeepSeek', 'configured': True}]})
    if path.endswith('/model-selection'):
        return reply(route, {'modelId': '', 'revision': 0})
    if path == '/api/agent/workbench/capabilities':
        return reply(route, {'enabled': False, 'files': True})
    return fixture['api'](route)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for kind, url in [('vue', 'http://127.0.0.1:3011/#/agent/chat'), ('react', 'http://127.0.0.1:5175/')]:
        for size, width, height in [('desktop', 1600, 1000), ('mobile', 390, 844)]:
            context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce')
            context.route('**/api/**', api)
            context.route('**/agui/**', api)
            fixture['session']['messages'] = []
            fixture['run'].update(phase='IDLE', runId=None, local=False, text='')
            fixture['inputs'].clear()
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url)
            page.wait_for_load_state('networkidle')
            page.screenshot(path=str(OUT / f'{kind}-{size}-loaded.png'), full_page=True)
            expect(page.get_by_role('heading', name='今天，想先解决什么？')).to_be_visible()
            expect(page.get_by_role('heading', name='今天，想先解决什么？')).to_be_in_viewport()
            expect(page.get_by_role('region', name='Agent 执行控制')).not_to_be_visible()
            expect(page.get_by_label('使用模型', exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='添加附件', exact=True)).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            page.screenshot(path=str(OUT / f'{kind}-{size}-welcome.png'), full_page=True)
            checks.append(f'{kind} {size}: welcome, no empty queue, model and upload, no overflow')
            fixture['session']['messages'] = [
                {'id': 1, 'role': 'user', 'messageType': 'TEXT', 'content': '核对本次检测任务，保留需要复核的项目'},
                {'id': 2, 'role': 'assistant', 'messageType': 'TEXT', 'content': '已核对当前授权范围内的记录。\n\n**需要关注**\n- 检测结果和人工复核结论分别展示\n- 未完成复核的任务仍需在质检页面处理\n\n可以继续补充任务编号，或添加本会话资料。'}]
            page.reload()
            page.wait_for_load_state('networkidle')
            expect(page.get_by_text('核对本次检测任务，保留需要复核的项目', exact=True)).to_be_visible()
            editor = page.get_by_role('textbox', name='聊天消息或技能命令') if kind == 'vue' else page.get_by_placeholder('输入问题 或输入 / 选择技能命令')
            editor.fill('尚未发送的草稿')
            editor.focus()
            assert editor.evaluate('(element) => document.activeElement === element')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            page.screenshot(path=str(OUT / f'{kind}-{size}-conversation.png'), full_page=True)
            toggle = page.get_by_role('button', name='展开工作面板', exact=True)
            if toggle.is_visible():
                toggle.click()
            else:
                # The independent entry labels this control as a workspace toggle.
                candidates = page.locator('.info-toggle')
                if candidates.count():
                    candidates.click()
            panel = page.get_by_role('complementary', name='Agent 工作面板') if kind == 'vue' else page.locator('.agent-info')
            expect(panel).to_be_visible()
            page.screenshot(path=str(OUT / f'{kind}-{size}-workspace.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            checks.append(f'{kind} {size}: transcript, editable draft, focus, workspace and reduced motion')
            context.close()
    browser.close()
assert not errors, errors
(OUT / 'results.json').write_text(json.dumps({'scope': 'isolated API fixtures, no supplier calls', 'checks': checks, 'javascriptErrors': errors}, ensure_ascii=False, indent=2), 'utf-8')
print(json.dumps({'passed': len(checks), 'javascriptErrors': errors}))
