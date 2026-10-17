const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const source = fs.readFileSync(path.join(__dirname, '../src/utils/agentCards.js'), 'utf8')
const modulePromise = import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)

test('persisted card envelope restores text and references without accepting arbitrary components', async () => {
  const { parseAgentCardEnvelope } = await modulePromise
  const value = { version: 1, text: '查询完成', runId: 'run-1', cards: [{ type: 'TASKS', tool: 'get_task_detail', ids: ['task-1'], days: null }] }
  assert.deepEqual(parseAgentCardEnvelope(JSON.stringify(value)), value)
  assert.equal(parseAgentCardEnvelope(JSON.stringify({ ...value, version: 2 })), null)
  assert.equal(parseAgentCardEnvelope(JSON.stringify({ ...value, cards: [{ ...value.cards[0], html: '<script>' }] })), null)
  assert.equal(parseAgentCardEnvelope('非法 JSON'), null)
})
test('card links only permit known business routes and reject malicious IDs', async () => {
  const { cardRoute, validCardReference } = await modulePromise
  assert.equal(cardRoute('TASKS', 'task-1'), '#/inspection/workbench?taskId=task-1')
  for (const id of ['javascript:alert(1)', '../secret', 'task-1&runId=other', '//external']) assert.equal(cardRoute('TASKS', id), '')
  assert.equal(cardRoute('HTML', 'task-1'), '')
  assert.equal(validCardReference({ type: 'METRICS', tool: 'get_my_work_metrics', ids: [], days: 1.5 }), false)
  assert.equal(validCardReference({ type: 'TASKS', tool: 'approve_report', ids: ['task-1'] }), false)
  assert.equal(validCardReference({ type: 'TASKS', tool: 'get_task_detail', ids: ['task-1', 'task-1'] }), false)
})

test('resource cards preserve large device IDs and only link canonical bounded primary keys', async () => {
  const { cardRoute, validCardReference, parseAgentCardEnvelope } = await modulePromise
  assert.equal(cardRoute('DEVICES', '9223372036854775807'), '#/devices/9223372036854775807')
  assert.equal(cardRoute('MODELS', '2147483647'), '#/models?modelId=2147483647')
  for (const type of ['DEVICES', 'MODELS']) {
    const tool = type === 'DEVICES' ? 'list_devices' : 'list_models'
    const card = { type, tool, ids: ['7'], days: null }
    const envelope = { version: 1, text: '查询完成', cards: [card] }
    assert.deepEqual(parseAgentCardEnvelope(JSON.stringify(envelope)), envelope)
    assert.equal(validCardReference({ ...card, tool: type === 'DEVICES' ? 'list_models' : 'list_devices' }), false)
    assert.equal(validCardReference({ ...card, days: 7 }), false)
    for (const id of ['0', '-1', '01', '1.0', '1e2', 'javascript:alert(1)', '../1', '1&mode=publish', '9223372036854775808', 7]) {
      assert.equal(cardRoute(type, id), '')
      assert.equal(validCardReference({ ...card, ids: [id] }), false)
    }
  }
  assert.equal(cardRoute('MODELS', '2147483648'), '')
})

test('resource labels distinguish detection models and unknown states without inventing readiness', async () => {
  const { cardTitle, modelStatus, deviceStatus } = await modulePromise
  assert.equal(cardTitle({ type: 'MODELS' }), '检测模型')
  assert.equal(cardTitle({ type: 'DEVICES' }), '设备运行状态')
  assert.equal(modelStatus('PUBLISHED'), '已发布')
  assert.equal(modelStatus('new-status'), '状态未知')
  assert.equal(deviceStatus(null), '未知')
  assert.equal(deviceStatus('DISCONNECTED'), '未连接')
  for (const value of ['__proto__', 'constructor', 'toString']) {
    assert.equal(modelStatus(value), '状态未知')
    assert.equal(deviceStatus(value), '未知')
  }
})

test('alert cards allow only read tools and bounded primary IDs, without fabricating an alert route', async () => {
  const { validCardReference, parseAgentCardEnvelope, cardRoute } = await modulePromise
  for (const tool of ['list_device_alerts', 'get_device_alert']) {
    const card = { type: 'DEVICE_ALERTS', tool, ids: ['9223372036854775807'], days: null }
    assert.equal(validCardReference(card), true)
    assert.ok(parseAgentCardEnvelope(JSON.stringify({ version: 1, text: '告警查询结果', cards: [card] })))
    for (const id of ['0', '01', 'ALERT-code', '../7', '9223372036854775808', 7]) assert.equal(validCardReference({ ...card, ids: [id] }), false)
    assert.equal(validCardReference({ ...card, tool: 'resolve_alert' }), false)
    assert.equal(validCardReference({ ...card, days: 7 }), false)
    assert.equal(cardRoute('DEVICE_ALERTS', '7'), '')
  }
})

test('alert labels separate record workflow from live device health and handle unknown status safely', async () => {
  const { cardTitle, alertStatus, alertType, alertLevel } = await modulePromise
  assert.equal(cardTitle({ type: 'DEVICE_ALERTS' }), '采集告警')
  assert.equal(alertStatus('ACKNOWLEDGED'), '已确认')
  assert.equal(alertStatus('RESOLVED'), '已解决')
  assert.equal(alertLevel('CRITICAL'), '紧急')
  assert.equal(alertType('HEARTBEAT_OFFLINE'), '心跳离线')
  for (const value of [null, '__proto__', 'constructor', 'UNKNOWN']) {
    assert.equal(alertStatus(value), '状态未知')
    assert.equal(alertLevel(value), '级别未知')
    assert.equal(alertType(value), '类型未知')
  }
})

test('detection model operations references accept only the readonly tool and bounded model IDs', async () => {
  const { validCardReference, parseAgentCardEnvelope, cardRoute, cardTitle } = await modulePromise
  const ref = { type: 'MODEL_OPERATIONS', tool: 'get_model_operations', ids: ['7'], days: null }
  assert.ok(parseAgentCardEnvelope(JSON.stringify({ version: 1, text: '登记信息', cards: [ref] })))
  assert.equal(cardRoute('MODEL_OPERATIONS', '7'), '#/models?modelId=7')
  assert.equal(cardTitle(ref), '模型指标与发布配置')
  for (const id of ['0', '01', '1.0', '2147483648', '../7', 7]) assert.equal(validCardReference({ ...ref, ids: [id] }), false)
  assert.equal(validCardReference({ ...ref, tool: 'publish_model' }), false)
  assert.equal(validCardReference({ ...ref, days: 7 }), false)
})

test('registered metric formatting preserves zero and missing values and rejects invalid numeric evidence', async () => {
  const { modelOperationMetrics } = await modulePromise
  const values = item => Object.fromEntries(modelOperationMetrics(item).map(row => [row.label, row.value]))
  assert.deepEqual(values({ evaluation: { precisionScore: 0, recallScore: 1, mapScore: .925, f1Score: null } }), {
    Precision: '0%', Recall: '100%', mAP: '92.5%', F1: '未记录',
  })
  for (const value of [-.1, 1.1, Infinity, NaN, '0.9']) assert.equal(values({ evaluation: { precisionScore: value } }).Precision, '需核对')
  assert.equal(values({ evaluation: { precisionScore: null }, invalidFields: ['precisionScore'] }).Precision, '需核对')
  assert.equal(values({ evaluation: { precisionScore: .000001 } }).Precision, '0.0001%')
})

test('model configuration display makes no default percentage or live routing assumptions', async () => {
  const { modelOperationDetails } = await modulePromise
  const values = item => Object.fromEntries(modelOperationDetails(item).map(row => [row.label, row.value]))
  const zero = values({ evaluation: { avgInferenceMs: 0 }, rollout: { strategy: 'CANARY', configuredPercent: 0 }, usage: { count: 0 } })
  assert.equal(zero['配置比例'], '0%'); assert.equal(zero['登记平均耗时'], '0 ms'); assert.equal(zero['登记使用次数'], '0')
  assert.equal(zero['发布策略配置'], '灰度'); assert.equal(zero['回滚来源模型'], '未记录')
  assert.equal(values({})['配置比例'], '未记录')
  assert.equal(values({ rollout: { strategy: '__proto__', configuredPercent: 101, rollbackFromModelId: 0 }, usage: { count: -1 } })['配置比例'], '需核对')
  assert.equal(values({ rollout: { strategy: '__proto__' } })['发布策略配置'], '需核对')
  assert.equal(values({ rollout: { strategy: null }, invalidFields: ['strategy'] })['发布策略配置'], '需核对')
})
