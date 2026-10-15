import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readAnswer } from './aguiClient.js';

function response(text) {
  const bytes = new TextEncoder().encode(text);
  return new Response(new ReadableStream({ start(controller) {
    // 每次一个字节，覆盖 UTF-8 字符及 CRLF 跨块分隔。
    for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
    controller.close();
  } }));
}
test('handles fragmented SSE and excludes tool arguments', async () => {
  const stream = response('data: {"type":"TOOL_CALL_ARGS","delta":"private"}\r\n\r\ndata: {"type":"TEXT_MESSAGE_CONTENT","delta":"任务完成"}\r\n\r\ndata: {"type":"RUN_FINISHED"}\r\n\r\n');
  assert.equal(await readAnswer(stream, () => {}), '任务完成');
});
test('reports run errors and interrupted streams', async () => {
  await assert.rejects(readAnswer(response('data: {"type":"RUN_ERROR","message":"失败"}\n\n'), () => {}), /失败/);
  await assert.rejects(readAnswer(response('data: {"type":"TEXT_MESSAGE_CONTENT","delta":"部分回答"}\n\n'), () => {}), /连接中断/);
});
test('business cards use the versioned custom event and never enter model answer text', async () => {
  let cards;
  const ref = { version: 1, cards: [{ type: 'TASKS', tool: 'get_task_detail', ids: ['task-1'], days: null }] };
  const stream = response('data: {"type":"CUSTOM","name":"unknown","value":"ignore"}\n\ndata: ' + JSON.stringify({ type: 'CUSTOM', name: 'doorhandle.business-cards.v1', value: ref }) + '\n\ndata: {"type":"TEXT_MESSAGE_CONTENT","delta":"查询完成"}\n\ndata: {"type":"RUN_FINISHED"}\n\n');
  assert.equal(await readAnswer(stream, () => {}, value => { cards = value; }), '查询完成');
  assert.deepEqual(cards, ref);
});
