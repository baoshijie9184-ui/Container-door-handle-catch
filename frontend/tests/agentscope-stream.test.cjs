const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const source = fs.readFileSync(path.join(__dirname, '../src/api/chatAssistant.js'), 'utf8')
  .replace("import request from './request'", 'const request = {}')
  .replaceAll('import.meta.env', '({})')
const modulePromise = import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)

test('SSE decodes split UTF-8 chunks and delivers the persisted final response', async t => {
  const { streamChatMessage } = await modulePromise
  const bytes = new TextEncoder().encode('event: chunk\r\ndata: {"content":"查询完成"}\r\n\r\nevent: done\r\ndata: {"messageResponse":{"id":42,"content":"查询完成"}}\r\n\r\n')
  const body = new ReadableStream({ start(controller) {
    for (let i = 0; i < bytes.length; i++) controller.enqueue(bytes.slice(i, i + 1))
    controller.close()
  } })
  t.mock.method(globalThis, 'fetch', async () => ({ ok: true, body }))
  let text = '', final
  await streamChatMessage({ content: '查询任务' }, { onChunk: chunk => { text += chunk }, onDone: answer => { final = answer } })
  assert.equal(text, '查询完成')
  assert.deepEqual(final, { id: 42, content: '查询完成' })
  assert.equal(body.locked, false)
})

test('premature EOF fails without issuing a second generation request', async t => {
  const { streamChatMessage } = await modulePromise
  const body = new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode('event: chunk\ndata: {"content":"部分回答"}\n\n'))
    controller.close()
  } })
  const fetch = t.mock.method(globalThis, 'fetch', async () => ({ ok: true, body }))
  await assert.rejects(streamChatMessage({ content: '查询任务' }), /提前结束/)
  assert.equal(fetch.mock.callCount(), 1)
  assert.equal(body.locked, false)
})

test('server error cancels the open reader and preserves the safe error', async t => {
  const { streamChatMessage } = await modulePromise
  let cancelled = false
  const body = new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode('event: error\ndata: {"message":"执行失败"}\n\n'))
  }, cancel() { cancelled = true } })
  t.mock.method(globalThis, 'fetch', async () => ({ ok: true, body }))
  await assert.rejects(streamChatMessage({ content: '查询任务' }, { onError: error => { throw new Error(error.message) } }), /执行失败/)
  assert.equal(cancelled, true)
  assert.equal(body.locked, false)
})
