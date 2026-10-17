"""Resource-card browser checks with isolated API fixtures; no ECS, database or LLM calls."""
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

OUT = Path(__file__).resolve().parents[2] / 'work/resource-cards'
OUT.mkdir(parents=True, exist_ok=True)
checks, errors, writes, pending = [], [], [], []
state = {'mode': 'ok', 'calls': 0, 'hold7': False}
references = [{'type': 'DEVICES', 'tool': 'list_devices', 'ids': ['9'], 'days': None},
              {'type': 'MODELS', 'tool': 'list_models', 'ids': ['7'], 'days': None}]
envelope = {'version': 1, 'text': '已查询设备及检测模型', 'runId': 'run-resources', 'cards': references}
session = {'sessionId': 'resource-session', 'title': '设备与检测模型', 'messages': [
    {'id': 1, 'role': 'user', 'messageType': 'TEXT', 'content': '查询设备和检测模型'},
    {'id': 2, 'role': 'assistant', 'messageType': 'AGENT_CARDS', 'content': json.dumps(envelope, ensure_ascii=False)}]}
alert_references = [{'type': 'DEVICE_ALERTS', 'tool': 'list_device_alerts', 'ids': ['11', '12'], 'days': None}]
alert_session = {'sessionId': 'alert-session', 'title': '采集告警查询', 'messages': [
    {'id': 3, 'role': 'user', 'messageType': 'TEXT', 'content': '查看待处理采集告警'},
    {'id': 4, 'role': 'assistant', 'messageType': 'AGENT_CARDS', 'content': json.dumps({'version': 1, 'text': '已查询采集告警摘要', 'runId': 'run-alerts', 'cards': alert_references}, ensure_ascii=False)}]}
operations_references = [{'type': 'MODEL_OPERATIONS', 'tool': 'get_model_operations', 'ids': ['7'], 'days': None}]
operations_session = {'sessionId': 'operations-session', 'title': '模型指标与发布配置', 'messages': [
    {'id': 5, 'role': 'user', 'messageType': 'TEXT', 'content': '查看模型 7 的登记指标与灰度配置'},
    {'id': 6, 'role': 'assistant', 'messageType': 'AGENT_CARDS', 'content': json.dumps({'version': 1, 'text': '已查询检测模型登记信息', 'runId': 'run-model-operations', 'cards': operations_references}, ensure_ascii=False)}]}


def operations_views():
    item = {'model': {'modelId': 7, 'name': '六类检测登记信息', 'version': 'v2', 'status': 'PUBLISHED', 'defaultModel': True},
            'validationStatus': 'PASSED', 'mlopsStatus': 'ROLLOUT', 'queriedAt': '2026-10-16T14:00:00', 'invalidFields': [],
            'evaluation': {'dataset': '<script>TEST-DATASET</script>', 'precisionScore': 0, 'recallScore': 1, 'mapScore': .925, 'f1Score': None, 'avgInferenceMs': 0},
            'rollout': {'strategy': 'CANARY', 'configuredPercent': 0, 'abGroup': 'B', 'rollbackFromModelId': None},
            'usage': {'count': 0, 'publishedAt': None, 'lastUsedAt': None}}
    card = {**operations_references[0], 'items': [item], 'metrics': {}, 'status': 'OK', 'scope': 'SINGLE_ENTERPRISE',
            'message': '仅展示本次工具结果中的前五条 当前状态以业务页面为准', 'updatedAt': '2026-10-16T14:00:00'}
    if state['mode'] == 'missing':
        item['evaluation'] = {}; item['rollout'] = {}; item['usage'] = {}; item['validationStatus'] = None; item['mlopsStatus'] = None
    if state['mode'] == 'invalid':
        item['evaluation']['precisionScore'] = None
        item['rollout']['configuredPercent'] = None
        item['invalidFields'] = ['precisionScore', 'configuredPercent']
    if state['mode'] == 'revoked': card.update(items=[], status='UNAVAILABLE', scope=None, message='此卡片已不可用 请重新查询')
    if state['mode'] == 'deleted': card.update(items=[], status='PARTIAL', message='部分记录已不存在或当前无权访问')
    return [card]


def alert_views():
    items = [{'alertId': '11', 'alertCode': '<script>ALERT-CODE</script>', 'deviceId': '9', 'deviceCode': 'LINE-A',
              'type': 'CAPTURE_EXCEPTION', 'level': 'CRITICAL', 'status': 'OPEN', 'createdAt': '2026-10-16T13:00:00', 'updatedAt': '2026-10-16T13:01:00'},
             {'alertId': '12', 'alertCode': 'ALERT-ORPHAN', 'deviceId': None, 'deviceCode': 'REMOVED-DEVICE',
              'type': 'HEARTBEAT_OFFLINE', 'level': 'MAJOR', 'status': 'ACKNOWLEDGED', 'createdAt': None, 'updatedAt': None}]
    card = {**alert_references[0], 'items': items, 'metrics': {}, 'status': 'OK', 'scope': 'SINGLE_ENTERPRISE',
            'message': '仅展示本次工具结果中的前五条 当前状态以业务页面为准', 'updatedAt': '2026-10-16T14:00:00'}
    if state['mode'] == 'resolved':
        for item in items: item['status'] = 'RESOLVED'
    if state['mode'] == 'unknown':
        items[0].update(type='__proto__', level='constructor', status='toString')
    if state['mode'] == 'revoked': card.update(items=[], status='UNAVAILABLE', scope=None, message='此卡片已不可用 请重新查询')
    if state['mode'] == 'deleted': card.update(items=[], status='PARTIAL', message='部分记录已不存在或当前无权访问')
    return [card]


def reply(route, data, raw=False, status=200):
    route.fulfill(status=status, content_type='application/json', body=json.dumps(data if raw else {'code': 200, 'data': data}, ensure_ascii=False))


def views():
    base = {'status': 'OK', 'metrics': {}, 'scope': 'SINGLE_ENTERPRISE', 'updatedAt': '2026-10-16T14:00:00', 'message': '仅展示本次工具结果中的前五条 当前状态以业务页面为准'}
    items = [[{'deviceId': '9', 'deviceCode': 'LINE-A-OTHER-CODE', 'status': 'IDLE', 'onlineStatus': 'ONLINE', 'plcStatus': 'CONNECTED', 'cameraStatus': 'DISCONNECTED', 'captureStatus': 'STOPPED'}],
             [{'modelId': 7, 'name': '<img src=x onerror=alert(1)> 六类检测', 'version': 'v2', 'status': 'PUBLISHED', 'defaultModel': True}]]
    result = [{**base, **ref, 'items': item} for ref, item in zip(references, items)]
    if state['mode'] == 'unknown':
        result[0]['items'][0]['plcStatus'] = '__proto__'
        result[1]['items'][0]['status'] = 'constructor'
    if state['mode'] == 'revoked':
        for card in result:
            card.update(status='UNAVAILABLE', items=[], scope=None, message='此卡片已不可用 请重新查询')
    return result


def api(route):
    request = route.request
    path = urlparse(request.url).path
    if not path.startswith(('/api/', '/agui/')): return route.continue_()
    if request.method != 'GET' and path != '/api/agent/cards/resolve':
        writes.append((request.method, path))
        return reply(route, {'message': 'unexpected write'}, raw=True, status=500)
    if path == '/api/agent/cards/resolve':
        requested = request.post_data_json
        assert requested in ({'cards': references}, {'cards': alert_references}, {'cards': operations_references})
        state['calls'] += 1
        if state['mode'] == 'fail': return reply(route, {'message': 'unavailable'}, raw=True, status=503)
        resolved = operations_views() if requested['cards'] == operations_references else alert_views() if requested['cards'] == alert_references else views()
        return reply(route, {'cards': resolved}, raw=True)
    if path == '/api/auth/check': return reply(route, {'username': 'boss.demo', 'role': 'SUPERVISOR', 'identity': {'departmentName': '质检中心'}})
    if path == '/api/chat-assistant/sessions': return reply(route, [session, alert_session, operations_session])
    if path.startswith('/api/chat-assistant/sessions/') or path == '/api/chat-assistant/session': return reply(route, operations_session if path.endswith('/operations-session') else alert_session if path.endswith('/alert-session') else session)
    if path == '/api/chat-projects': return reply(route, [])
    if path == '/api/agent/actions': return reply(route, [], raw=True)
    if path == '/api/agent/commands': return reply(route, {'enabled': True, 'skills': []}, raw=True)
    if path.endswith('/agent-health'): return reply(route, {'framework': 'AgentScope', 'mode': 'READ_ONLY', 'defaultModel': 'fixture'})
    if path == '/agui/catalog': return reply(route, {'role': 'SUPERVISOR', 'mainAgent': 'supervisor-main', 'agents': [], 'mode': 'READ_ONLY'}, raw=True)
    if path == '/agui/models': return reply(route, {'models': [], 'fallbackEnabled': False}, raw=True)
    if path == '/api/model-info': return reply(route, {'records': [], 'total': 0})
    if path.startswith('/api/model-info/'):
        model_id = int(path.rsplit('/', 1)[1])
        if state['hold7'] and model_id == 7:
            pending.append(route)
            return
        if model_id == 99: return reply(route, None, status=404)
        return reply(route, {'modelId': model_id, 'modelName': '六类检测详情-' + str(model_id), 'version': 'v2', 'status': 'PUBLISHED', 'isDefault': True})
    if path.startswith('/api/models/') and path.endswith('/operations'): return reply(route, [])
    if path == '/api/devices/9': return reply(route, {'id': 9, 'deviceCode': 'LINE-A-OTHER-CODE', 'status': 'IDLE'})
    if path == '/api/detection/tasks/by-device': return reply(route, {'records': [], 'total': 0})
    return reply(route, [])


def check(name, assertion):
    try:
        assertion()
        checks.append({'name': name, 'passed': True})
    except Exception as error:
        checks.append({'name': name, 'passed': False, 'error': str(error)})
    print(json.dumps(checks[-1], ensure_ascii=False), flush=True)


def equal(actual, expected):
    assert actual == expected, (actual, expected)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 1080})
    context.set_default_timeout(8000)
    context.route('**/api/**', api)
    context.route('**/agui/**', api)
    context.on('page', lambda page: page.on('pageerror', lambda error: errors.append(str(error))))
    for name, url in [('vue', 'http://127.0.0.1:3011/#/agent/chat?sessionId=resource-session'), ('react', 'http://127.0.0.1:5175/?sessionId=resource-session')]:
        state['mode'] = 'ok'
        page = context.new_page()
        page.goto(url, timeout=120000)
        page.wait_for_load_state('networkidle')
        cards = page.locator('.agent-result')
        check(name + ' restores both cards from persisted references', lambda: expect(cards.locator('.result-card')).to_have_count(2))
        check(name + ' device states reflect actual fields', lambda: expect(cards.get_by_text('PLC 已连接 · 相机 未连接 · 采集 已停止')).to_be_visible())
        check(name + ' model card shows version and default state', lambda: expect(cards.get_by_text('版本 v2 · 已发布 · 默认模型')).to_be_visible())
        check(name + ' untrusted title is rendered as text', lambda: expect(cards.locator('img')).to_have_count(0))
        check(name + ' device link uses primary key rather than code', lambda: equal(urlparse(cards.get_by_role('link', name='查看设备').get_attribute('href')).fragment, '/devices/9'))
        check(name + ' model link selects the detail drawer', lambda: equal(urlparse(cards.get_by_role('link', name='查看模型').get_attribute('href')).fragment, '/models?modelId=7'))
        page.screenshot(path=str(OUT / (name + '-desktop.png')), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.emulate_media(reduced_motion='reduce')
        page.wait_for_timeout(350)
        check(name + ' mobile has no horizontal overflow', lambda: equal(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), True))
        page.screenshot(path=str(OUT / (name + '-mobile.png')), full_page=True)
        state['mode'] = 'unknown'
        cards.get_by_role('button', name='刷新卡片').click()
        check(name + ' unrecognized device state safely shows unknown', lambda: expect(cards.get_by_text('PLC 未知 · 相机 未连接 · 采集 已停止')).to_be_visible())
        check(name + ' unrecognized model state safely shows unknown', lambda: expect(cards.get_by_text('版本 v2 · 状态未知 · 默认模型')).to_be_visible())
        state['mode'] = 'fail'
        cards.get_by_role('button', name='刷新卡片').click()
        check(name + ' refresh failure shows a recoverable error', lambda: expect(cards.get_by_role('alert')).to_be_visible())
        check(name + ' refresh failure removes stale private views', lambda: expect(cards.locator('.result-card')).to_have_count(0))
        state['mode'] = 'ok'
        cards.get_by_role('button', name='刷新卡片').click()
        check(name + ' retry restores fresh views', lambda: expect(cards.locator('.result-card')).to_have_count(2))
        state['mode'] = 'revoked'
        cards.get_by_role('button', name='刷新卡片').click()
        check(name + ' revoked role hides device and model links', lambda: expect(cards.locator('a')).to_have_count(0))
        check(name + ' revoked cards show generic unavailable hints', lambda: expect(cards.get_by_text('此卡片已不可用 请重新查询')).to_have_count(2))
        state['mode'] = 'ok'
        page.reload()
        page.wait_for_load_state('networkidle')
        check(name + ' reload recovers original references', lambda: expect(page.locator('.agent-result .result-card')).to_have_count(2))
        page.close()

    page = context.new_page()
    page.goto('http://127.0.0.1:3011/#/agent/chat?sessionId=resource-session')
    page.wait_for_load_state('networkidle')
    page.get_by_role('link', name='查看模型', exact=True).click()
    drawer = page.get_by_role('dialog', name='模型详情')
    check('model card opens actual model detail drawer', lambda: expect(drawer.get_by_text('六类检测详情-7')).to_be_visible())
    page.evaluate("location.hash='/models?modelId=99'")
    check('missing model shows generic detail error', lambda: expect(drawer.get_by_role('alert')).to_be_visible())
    check('missing model clears previous detail', lambda: expect(drawer.get_by_text('六类检测详情-7')).to_have_count(0))
    state['hold7'] = True
    page.evaluate("location.hash='/models?modelId=7'")
    page.wait_for_timeout(150)
    check('pending model detail clears older data', lambda: expect(drawer.get_by_role('status')).to_be_visible())
    check('race fixture actually holds the older model request', lambda: equal(len(pending), 1))
    page.evaluate("location.hash='/models?modelId=8'")
    check('newer model detail resolves first', lambda: expect(drawer.get_by_text('六类检测详情-8')).to_be_visible())
    for route in pending:
        reply(route, {'modelId': 7, 'modelName': 'STALE-DETAIL-7', 'status': 'DISABLED'})
    page.wait_for_timeout(150)
    check('late response cannot replace current model detail', lambda: expect(drawer.get_by_text('六类检测详情-8')).to_be_visible())
    check('late response leaves no stale model text', lambda: expect(drawer.get_by_text('STALE-DETAIL-7')).to_have_count(0))
    page.evaluate("location.hash='/models?modelId=01'")
    check('invalid model query cannot open details', lambda: expect(drawer).to_be_hidden())
    state['hold7'] = False
    page.goto('http://127.0.0.1:3011/#/agent/chat?sessionId=resource-session')
    page.wait_for_load_state('networkidle')
    page.get_by_role('link', name='查看设备', exact=True).click()
    check('device card opens actual primary-key detail page', lambda: expect(page.get_by_text('LINE-A-OTHER-CODE', exact=True).first).to_be_visible())
    page.close()

    for name, url in [('vue', 'http://127.0.0.1:3011/#/agent/chat?sessionId=alert-session'), ('react', 'http://127.0.0.1:5175/?sessionId=alert-session')]:
        state['mode'] = 'ok'
        page = context.new_page()
        page.goto(url, timeout=120000)
        page.wait_for_load_state('networkidle')
        cards = page.locator('.agent-result')
        check(name + ' alert history restores a card with two records', lambda: expect(cards.locator('.card-record')).to_have_count(2))
        check(name + ' alert card displays workflow and severity', lambda: expect(cards.get_by_text('采集异常 · 紧急 · 待处理')).to_be_visible())
        check(name + ' alert timestamps show occurrence and record update separately', lambda: expect(cards.get_by_text('发生 2026-10-16 13:00:00 · 记录更新 2026-10-16 13:01:00')).to_be_visible())
        check(name + ' alert code is plain text without executable HTML', lambda: expect(cards.locator('script')).to_have_count(0))
        check(name + ' only live device associations create links', lambda: expect(cards.get_by_role('link', name='查看设备')).to_have_count(1))
        check(name + ' removed device remains a historical record', lambda: expect(cards.get_by_text('设备关联已不可用')).to_be_visible())
        check(name + ' alert record is distinguished from live device health', lambda: expect(cards.get_by_text('按告警记录展示 不代表设备当前仍故障或已修复')).to_be_visible())
        check(name + ' alert card has only a readonly refresh button', lambda: expect(cards.get_by_role('button')).to_have_count(1))
        page.screenshot(path=str(OUT / (name + '-alerts-desktop.png')), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.emulate_media(reduced_motion='reduce')
        page.wait_for_timeout(300)
        check(name + ' mobile alert cards do not overflow', lambda: equal(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), True))
        page.screenshot(path=str(OUT / (name + '-alerts-mobile.png')), full_page=True)
        state['mode'] = 'resolved'
        cards.get_by_role('button', name='刷新卡片').click()
        check(name + ' alert refresh reads latest record state', lambda: expect(cards.get_by_text('采集异常 · 紧急 · 已解决')).to_be_visible())
        state['mode'] = 'unknown'
        cards.get_by_role('button', name='刷新卡片').click()
        check(name + ' unknown alert metadata renders safe labels', lambda: expect(cards.get_by_text('类型未知 · 级别未知 · 状态未知')).to_be_visible())
        state['mode'] = 'fail'
        cards.get_by_role('button', name='刷新卡片').click()
        check(name + ' alert refresh failure clears previous records', lambda: expect(cards.locator('.card-record')).to_have_count(0))
        check(name + ' alert refresh failure is recoverable', lambda: expect(cards.get_by_role('alert')).to_be_visible())
        state['mode'] = 'deleted'
        cards.get_by_role('button', name='刷新卡片').click()
        check(name + ' deleted alerts have no stale records', lambda: expect(cards.locator('.card-record')).to_have_count(0))
        check(name + ' deleted or inaccessible alerts use a generic hint', lambda: expect(cards.get_by_text('部分记录已不存在或当前无权访问')).to_be_visible())
        state['mode'] = 'revoked'
        cards.get_by_role('button', name='刷新卡片').click()
        check(name + ' role revocation removes alert device links', lambda: expect(cards.locator('a')).to_have_count(0))
        check(name + ' role revocation shows unavailable alert card', lambda: expect(cards.get_by_text('此卡片已不可用 请重新查询')).to_be_visible())
        state['mode'] = 'ok'
        page.reload()
        page.wait_for_load_state('networkidle')
        check(name + ' alert references recover after reload', lambda: expect(page.locator('.agent-result .card-record')).to_have_count(2))
        page.close()
    for name, url in [('vue', 'http://127.0.0.1:3011/#/agent/chat?sessionId=operations-session'), ('react', 'http://127.0.0.1:5175/?sessionId=operations-session')]:
        state['mode'] = 'ok'
        page = context.new_page()
        page.goto(url, timeout=120000)
        page.wait_for_load_state('networkidle')
        cards = page.locator('.agent-result')
        check(name + ' model operations restore from history', lambda: expect(cards.get_by_text('模型指标与发布配置', exact=True)).to_be_visible())
        check(name + ' metric grid preserves zero and missing score', lambda: expect(cards.locator('.operation-metrics strong')).to_have_text(['0%', '100%', '92.5%', '未记录']))
        check(name + ' model operations have a fixed detail route', lambda: equal(urlparse(cards.get_by_role('link', name='查看模型').get_attribute('href')).fragment, '/models?modelId=7'))
        check(name + ' configuration does not claim live routing', lambda: expect(cards.get_by_text('指标为登记值 发布策略为配置记录 实际分流尚未核验')).to_be_visible())
        cards.locator('summary').click()
        def detail(label): return cards.locator('.operation-details > div').filter(has=page.get_by_text(label, exact=True)).locator('dd')
        check(name + ' configured zero percent remains zero', lambda: expect(detail('配置比例')).to_have_text('0%'))
        check(name + ' registered zero latency remains zero', lambda: expect(detail('登记平均耗时')).to_have_text('0 ms'))
        check(name + ' registered zero usage remains zero', lambda: expect(detail('登记使用次数')).to_have_text('0'))
        check(name + ' rollout strategy is displayed as configuration', lambda: expect(detail('发布策略配置')).to_have_text('灰度'))
        check(name + ' dataset label is escaped plain text', lambda: expect(detail('测试集')).to_have_text('<script>TEST-DATASET</script>'))
        check(name + ' model operations never execute dataset markup', lambda: expect(cards.locator('script')).to_have_count(0))
        check(name + ' model operation card exposes no write action', lambda: expect(cards.get_by_role('button')).to_have_count(1))
        page.wait_for_timeout(250)
        page.screenshot(path=str(OUT / (name + '-model-operations-desktop.png')), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.emulate_media(reduced_motion='reduce')
        page.wait_for_timeout(300)
        check(name + ' model operations fit mobile viewport', lambda: equal(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), True))
        check(name + ' operation detail animation respects reduced motion', lambda: expect(cards.locator('.operation-details')).to_have_css('animation-name', 'none'))
        page.screenshot(path=str(OUT / (name + '-model-operations-mobile.png')), full_page=True)
        state['mode'] = 'missing'
        cards.get_by_role('button', name='刷新卡片').click()
        check(name + ' missing scores never become zeros', lambda: expect(cards.locator('.operation-metrics strong')).to_have_text(['未记录'] * 4))
        cards.locator('summary').click()
        check(name + ' missing configured percentage has no invented full rollout', lambda: expect(detail('配置比例')).to_have_text('未记录'))
        state['mode'] = 'invalid'
        cards.get_by_role('button', name='刷新卡片').click()
        check(name + ' sanitized invalid metric requires verification', lambda: expect(cards.locator('.operation-metrics strong').first).to_have_text('需核对'))
        check(name + ' invalid recorded fields show verification hint', lambda: expect(cards.get_by_text('部分登记字段异常 请到模型页面核对')).to_be_visible())
        state['mode'] = 'fail'
        cards.get_by_role('button', name='刷新卡片').click()
        check(name + ' failed operations refresh removes stale records', lambda: expect(cards.locator('.model-operation')).to_have_count(0))
        state['mode'] = 'revoked'
        cards.get_by_role('button', name='刷新卡片').click()
        check(name + ' revoked operations access shows unavailable state', lambda: expect(cards.get_by_text('此卡片已不可用 请重新查询')).to_be_visible())
        check(name + ' revoked operations access leaves no links', lambda: expect(cards.locator('a')).to_have_count(0))
        state['mode'] = 'ok'
        page.reload()
        page.wait_for_load_state('networkidle')
        check(name + ' model operations recover after reload', lambda: expect(page.locator('.agent-result .model-operation')).to_have_count(1))
        page.close()
    check('all browser interactions avoid model calls and business writes', lambda: equal(writes, []))
    check('no browser JavaScript errors', lambda: equal(errors, []))
    browser.close()

(OUT / 'results.json').write_text(json.dumps({'mode': 'isolated API fixtures', 'checks': checks, 'javascriptErrors': errors, 'unexpectedWrites': writes}, ensure_ascii=False, indent=2), encoding='utf8')
failed = [item for item in checks if not item['passed']]
print(json.dumps({'passed': len(checks)-len(failed), 'failed': failed, 'javascriptErrors': errors}, ensure_ascii=False))
if failed: raise SystemExit(1)
