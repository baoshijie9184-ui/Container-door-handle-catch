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
