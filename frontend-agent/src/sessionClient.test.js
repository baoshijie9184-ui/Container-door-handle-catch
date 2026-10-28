import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readSession,sessionItems} from './sessionClient.js';
test('rejects HTTP and business failures and accepts owned session envelope',async()=>{
  await assert.rejects(readSession(new Response('',{status:403})),/登录/);
  await assert.rejects(readSession(Response.json({code:404,message:'private detail'})),/会话不可用/);
  assert.deepEqual(await readSession(Response.json({code:200,data:{sessionId:'s1'}})),{sessionId:'s1'});
});

test('restores only explicit per-message execution links and does not guess from text',()=>{
  const items=sessionItems([{id:1,role:'assistant',messageType:'TEXT',content:'durable-one',runId:'durable-one'},
    {id:2,role:'assistant',messageType:'AGENT_CARDS',content:JSON.stringify({version:1,text:'回答',runId:'durable-two',cards:[]})},
    {id:3,role:'assistant',messageType:'TEXT',content:'运行编号 durable-three'}],()=>[]);
  assert.deepEqual(items.map(item=>item.runId),['durable-one','durable-two','']);
});
test('restores text and trusted references without rendering old action payloads',()=>{
  const refs=[{type:'TASKS',tool:'get_task_detail',ids:['task-1'],days:null}];
  const result=sessionItems([{id:1,role:'user',messageType:'TEXT',content:'问题'},{id:2,role:'assistant',messageType:'AGENT_CARDS',content:JSON.stringify({version:1,text:'回答',cards:refs})},{id:3,role:'assistant',messageType:'PENDING_ACTION',content:'private payload'},{id:4,role:'assistant',messageType:'AGENT_CARDS',content:'invalid'}],(text,cards)=>[{text,cards}]);
  assert.equal(result.length,2);assert.equal(result[0].content,'问题');assert.equal(result[1].text,'回答');assert.deepEqual(result[1].cards,[{text:'回答',cards:refs}]);
});
