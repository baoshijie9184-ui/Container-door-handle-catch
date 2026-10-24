"""Two-entry confirmation contract checks with isolated API fixtures; no business writes or model calls."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'work/detection-retry-browser'
OUT.mkdir(parents=True, exist_ok=True)
fixture = {'__file__': str(ROOT / 'script/diagnostics/conversation-control-acceptance.py')}
exec((ROOT / 'script/diagnostics/conversation-control-acceptance.py').read_text('utf-8').split('with sync_playwright() as p:')[0], fixture)
checks, errors = [], []
pending = dict(actionId='retry-1', runId='run-1', sessionId='control-session', operation='RETRY_DETECTION', status='PENDING', version=1,
               command=None, before=None, result=None, execution=None, reasonCode=None, createdAt='2026-10-21T16:00:00', expiresAt='2026-10-21T16:10:00',
               retry=dict(taskId='task-1', resourceVersion='a'*64, status='FAILED', flowStatus='FAILED', previousDispatchId='dispatch-old',
                          modelId=12, threshold=0.5, imageCount=2, impact='将清空当前检测结果与复核、处置状态；不会自动放行或审批报告'))
assignment = dict(actionId='assignment-1', runId='run-1', operation='ASSIGN_QUALITY_TASK', status='PENDING', version=1,
                  command=dict(taskId='task-2', qualityStation='站点 A', assignee='inspector.demo', dueAt=None), before=dict(qualityStation=None, assignee=None))

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for kind, url in [('vue', 'http://127.0.0.1:3011/#/agent/actions'), ('react', 'http://127.0.0.1:5175/')]:
        for size, width, height in [('desktop', 1500, 1050), ('mobile', 390, 844)]:
            print(f'Checking {kind} {size}', flush=True)
            state = {'actions': [copy.deepcopy(pending), copy.deepcopy(assignment)], 'failure': None, 'malformed': False}
            writes = []
            fixture['run'].update(phase='IDLE', runId=None, local=False, text='')
            fixture['inputs'].clear()
            context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce', timezone_id='America/Los_Angeles')
            def api(route):
                req = route.request
                path = urlparse(req.url).path
                reply = fixture['reply']
                if path == '/api/agent/actions':
                    return reply(route, {'code': 404, 'message': 'missing route'} if state['malformed'] else state['actions'])
                if path.startswith('/api/agent/actions/'):
                    if path.endswith('/audit'):
                        return reply(route, [dict(id=1, occurredAt='2026-10-21T16:01:00', eventType='CONFIRMATION_CREATED', result='PENDING')])
                    assert req.method == 'POST'
                    assert req.headers.get('x-agent-action') == 'confirm'
                    body = req.post_data_json
                    assert set(body) == {'decision', 'version'} and body['decision'] == 'APPROVE'
                    assert path == '/api/agent/actions/retry-1/confirm'
                    writes.append(body)
                    if state['failure'] == 'stale':
                        state['failure'] = None
                        state['actions'][0]['version'] = 2
                        return reply(route, {'message': '操作版本已变化，请刷新卡片'}, status=409)
                    assert body['version'] == state['actions'][0]['version']
                    state['actions'][0].update(status='SUCCEEDED', version=3, execution=dict(commandId='command-1', operation='RETRY', taskId='task-1', dispatchId='dispatch-new', status='QUEUED'))
                    if state['failure'] == 'lost-response':
                        state['failure'] = None
                        return route.abort('connectionfailed')
                    return reply(route, state['actions'][0])
                if path == '/agui/models':
                    return reply(route, {'selectedModel': 'deepseek:fixture', 'models': [{'id': 'deepseek:fixture', 'configured': True, 'model': 'fixture'}]})
                if path == '/api/agent/workbench/capabilities':
                    return reply(route, {'enabled': False, 'files': False})
                if path.endswith('/model-selection'):
                    return reply(route, {'modelId': '', 'revision': 0})
                return fixture['api'](route)
            context.route('**/api/**', api)
            context.route('**/agui/**', api)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            def open_panel():
                page.goto(url)
                page.wait_for_load_state('networkidle')
                if kind == 'react':
                    page.locator('.info-toggle').click()
                return page.get_by_role('region', name='助手操作确认', exact=True)
            panel = open_panel()
            card = panel.locator('article').filter(has_text='重新检测任务')
            expect(card).to_contain_text('2 张')
            expect(card).to_contain_text('0.5')
            expect(card).to_contain_text('不会自动放行')
            expect(card).to_contain_text('2026-10-21 16:10:00')
            expect(panel.get_by_role('button', name='确认分配', exact=True)).to_be_visible()
            assert not writes
            checks.append(f'{kind} {size}: immutable retry impact, UTC+8 despite foreign browser timezone, original assignment preserved')
            state['failure'] = 'stale'
            card.get_by_role('button', name='确认重新检测').click()
            expect(panel.get_by_role('alert')).to_contain_text('刷新')
            expect(card.get_by_role('button', name='确认重新检测')).to_be_disabled()
            assert len(writes) == 1
            page.screenshot(path=str(OUT / f'{kind}-{size}-stale.png'), full_page=True)
            panel.get_by_role('button', name='刷新', exact=True).click()
            expect(card.get_by_role('button', name='确认重新检测')).to_be_enabled()
            assert len(writes) == 1
            checks.append(f'{kind} {size}: stale version blocks writes, explicit refresh only reads')
            state['failure'] = 'lost-response'
            card.get_by_role('button', name='确认重新检测').click()
            expect(panel.get_by_role('alert')).to_be_visible()
            expect(card.get_by_role('button', name='确认重新检测')).to_be_disabled()
            assert len(writes) == 2 and writes[1]['version'] == 2
            panel.get_by_role('button', name='刷新', exact=True).click()
            expect(card).to_contain_text('已提交检测')
            expect(card).to_contain_text('不表示检测已完成')
            expect(card).to_contain_text('dispatch-new')
            assert len(writes) == 2
            page.reload()
            page.wait_for_load_state('networkidle')
            if kind == 'react':
                page.locator('.info-toggle').click()
            expect(card).to_contain_text('已提交检测')
            assert len(writes) == 2
            checks.append(f'{kind} {size}: lost acknowledgement reconciled and refresh never resubmits')
            card.get_by_role('button', name='查看审计').click()
            expect(card.locator('ol')).to_contain_text('2026-10-21 16:01:00')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            page.keyboard.press('Tab')
            assert page.evaluate('document.activeElement.tagName') != 'BODY'
            page.screenshot(path=str(OUT / f'{kind}-{size}.png'), full_page=True)
            checks.append(f'{kind} {size}: audit, keyboard, reduced motion and no horizontal overflow')
            state['malformed'] = True
            panel.get_by_role('button', name='刷新', exact=True).click()
            expect(panel.get_by_role('alert')).to_be_visible()
            expect(panel.get_by_role('button', name='确认分配', exact=True)).to_be_disabled()
            assert len(writes) == 2
            state['malformed'] = False
            state['actions'][0].update(status='INVALIDATED', reasonCode='EXECUTION_NEEDS_REVIEW')
            panel.get_by_role('button', name='刷新', exact=True).click()
            expect(card).to_contain_text('不会自动重试')
            expect(card.get_by_role('button', name='确认重新检测')).to_have_count(0)
            assert len(writes) == 2
            checks.append(f'{kind} {size}: malformed read fails closed; unknown execution cannot be approved')
            context.close()
    browser.close()
assert not errors, errors
(OUT / 'results.json').write_text(json.dumps({'scope': 'isolated browser/API contracts, not real detection or Kafka acceptance', 'checks': checks, 'pageErrors': errors}, ensure_ascii=False, indent=2), 'utf-8')
print(json.dumps({'passed': len(checks), 'pageErrors': errors}, ensure_ascii=False))
