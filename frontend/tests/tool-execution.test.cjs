const {test}=require('node:test')
const assert=require('node:assert/strict')
const modulePath=require('node:url').pathToFileURL(require('node:path').resolve(__dirname,'../src/utils/toolExecution.js')).href
test('pairs actual receipts by call ID and counts four failures without counting starts twice',async()=>{
 const {toolRows,toolSummary}=await import(modulePath);const events=[]
 for(let i=1;i<=11;i++){const payload={callId:'call-'+i,tool:'read_workspace_file',agent:'reader'};events.push({type:'TOOL_STARTED',payload},{type:[2,4,7,10].includes(i)?'TOOL_ERROR':'TOOL_COMPLETED',payload:{...payload,durationMs:35}})}
 const rows=toolRows(events);assert.equal(rows.length,11);assert.equal(toolSummary(rows,'COMPLETED'),'执行工具 11 次，其中 4 次失败');assert.equal(toolRows(events.concat(events)).length,11)
})
test('keeps cancelled and unconfirmed results distinct from failure or success',async()=>{
 const {toolRows,toolSummary}=await import(modulePath)
 const rows=toolRows([{type:'TOOL_STARTED',callId:'one',tool:'get_task_detail'},{type:'TOOL_CANCELLED',callId:'two',tool:'get_task_detail'},{type:'REASONING',text:'已成功运行十次'}]);assert.equal(rows.length,2);assert.equal(rows[0].status,'calling');assert.equal(rows[1].status,'cancelled');assert.equal(toolSummary(rows,'COMPLETED'),'执行工具 2 次');assert.equal(toolSummary(rows,'RUNNING'),'正在执行工具 2 次')
 assert.equal(toolSummary([], 'finished'), '查看工具执行记录');assert.equal(toolSummary(rows,'COMPLETED',{complete:false}), '已记录工具 2 次')
})
test('does not forward raw parameters, private errors, invalid metadata or invented file changes',async()=>{
 const {toolRows,messageRunId}=await import(modulePath);const rows=toolRows([{type:'TOOL_ERROR',payload:{callId:'call1',tool:'read_workspace_file',arguments:'SECRET',error:'PRIVATE',fileDiff:'FAKE',durationMs:4}}]);assert.equal(rows.length,1);assert.doesNotMatch(JSON.stringify(rows),/SECRET|PRIVATE|FAKE/)
 assert.equal(toolRows([{type:'TOOL_STARTED',callId:'../x',tool:'read_file'}]).length,0);assert.equal(messageRunId({messageType:'AGENT_CARDS',content:JSON.stringify({version:1,runId:'owned-run'})}),'owned-run');assert.equal(messageRunId({content:'运行编号 owned-run'}),'')
})
test('a late live snapshot cannot downgrade a completed durable tool receipt',async()=>{
 const {toolRows}=await import(modulePath);assert.equal(toolRows([{type:'TOOL_COMPLETED',callId:'one',tool:'read_file'}],{one:{id:'one',name:'read_file',status:'calling'}})[0].status,'returned')
})
test('reader pages actual owned records and clears events on permission loss',async()=>{
 const {ToolExecutionReader}=await import(modulePath);let denied=false;const calls=[]
 const reader=new ToolExecutionReader({fetcher:async url=>{calls.push(url);if(denied)return new Response('',{status:403});return Response.json(url.includes('/events?')?[{sequence:1,type:'TOOL_STARTED',payload:{callId:'c1',tool:'read_file'}},{sequence:2,type:'TOOL_COMPLETED',payload:{callId:'c1',tool:'read_file'}}]:{runId:'r1',sessionId:'s1',lastSequence:2,status:'COMPLETED'})}})
 reader.open('s1','r1');await reader.read();assert.equal(reader.state.complete,true);assert.equal(reader.state.events.length,2);assert.equal(calls.length,2);denied=true;await reader.read();assert.equal(reader.state.denied,true);assert.deepEqual(reader.state.events,[]);reader.close()
})
test('reader rejects cross-session metadata and ignores responses after switching session',async()=>{
 const {ToolExecutionReader}=await import(modulePath);let finish;const reader=new ToolExecutionReader({fetcher:()=>new Promise(resolve=>{finish=resolve})});reader.open('s1','r1');const first=reader.read();reader.open('s2','r2');finish(Response.json({runId:'r1',sessionId:'s1',lastSequence:0,status:'COMPLETED'}));await first;assert.equal(reader.state.known,false);reader.close()
 const mismatch=new ToolExecutionReader({fetcher:async()=>Response.json({runId:'r1',sessionId:'other',lastSequence:0,status:'COMPLETED'})});mismatch.open('s1','r1');await mismatch.read();assert.equal(mismatch.state.known,false);assert.deepEqual(mismatch.state.events,[]);mismatch.close()
})
