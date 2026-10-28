import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readAnswer,initialRunState,reduceRunEvent,A2UI_EVENT } from './aguiClient.js';

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

test('tool argument completion never marks execution successful; only actual results do',()=>{
  let state=reduceRunEvent(initialRunState(),{type:'TOOL_CALL_START',toolCallId:'call1',toolCallName:'get_task_detail'});
  state=reduceRunEvent(state,{type:'TOOL_CALL_END',toolCallId:'call1'});assert.equal(state.tools.call1.status,'awaiting-result');
  state=reduceRunEvent(state,{type:'RUN_FINISHED'});assert.equal(state.tools.call1.status,'awaiting-result');
  state=reduceRunEvent(state,{type:'TOOL_CALL_RESULT',toolCallId:'call1',content:'已收到记录'});assert.equal(state.tools.call1.status,'returned');
  state=reduceRunEvent(state,{type:'CUSTOM',name:'doorhandle.tool-status.v1',value:{toolCallId:'call1',status:'failed'}});assert.equal(state.tools.call1.status,'failed');
});
test('supports mixed text and A2UI, UI-only runs, unknown events and terminal cancellation',async()=>{
  let ui;const message={version:'v0.9.1',createSurface:{surfaceId:'s1'}};
  const frames=[{type:'RUN_STARTED',runId:'r1'},{type:'CUSTOM',name:A2UI_EVENT,value:message},{type:'FUTURE_EVENT'},{type:'TEXT_MESSAGE_CONTENT',messageId:'m1',delta:'统计结果'},{type:'RUN_FINISHED'}];
  assert.equal(await readAnswer(response(frames.map(value=>'data: '+JSON.stringify(value)+'\n\n').join('')),()=>{},()=>{},{onA2ui:value=>{ui=value;}}),'统计结果');assert.deepEqual(ui,message);
  assert.equal(await readAnswer(response(`data: ${JSON.stringify(frames[1])}\n\ndata: {"type":"RUN_FINISHED"}\n\n`)),'');
});
test('preserves callback text on malformed data and bounds frames',async()=>{
  let text='';await assert.rejects(readAnswer(response('data: {"type":"TEXT_MESSAGE_CONTENT","delta":"保留"}\n\ndata: broken\n\n'),value=>{text=value;}),/解析/);assert.equal(text,'保留');
  await assert.rejects(readAnswer(new Response('data: '+ 'x'.repeat(524289))),/上限/);
});
test('abort cancels a blocked reader and never auto retries',async()=>{
  let cancelled=false;const abort=new AbortController();const stream=new Response(new ReadableStream({cancel(){cancelled=true;}}));
  const reading=readAnswer(stream,()=>{},()=>{},{signal:abort.signal});abort.abort();await assert.rejects(reading,{name:'AbortError'});assert.equal(cancelled,true);
});

test('supports comment heartbeats, CR-only framing and multiple assistant messages',async()=>{
  const data=': heartbeat\r\rdata: {"type":"TEXT_MESSAGE_START","messageId":"a"}\r\rdata: {"type":"TEXT_MESSAGE_CONTENT","messageId":"a","delta":"第一段"}\r\rdata: {"type":"TEXT_MESSAGE_END","messageId":"a"}\r\rdata: {"type":"TEXT_MESSAGE_CONTENT","messageId":"b","delta":"第二段"}\r\rdata: {"type":"RUN_FINISHED"}\r\r';
  assert.equal(await readAnswer(response(data)),'第一段\n第二段');
});
