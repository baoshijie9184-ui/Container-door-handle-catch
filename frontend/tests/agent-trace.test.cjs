const test = require('node:test')
const assert = require('node:assert/strict')
const { readFrontendFile } = require('./helpers/project-source.cjs')
const load = file => import(`data:text/javascript;base64,${Buffer.from(readFrontendFile('src','utils',file)).toString('base64')}`)
const projection = load('agentTrace.js'), readerModule = load('agentTraceReader.js')
const event = (sequence,type,payload={}) => ({sequence,type,payload,occurredAt:'2026-10-16T12:00:00'})
const run = (runId,extra={}) => ({runId,sessionId:'session-'+runId,status:'COMPLETED',lastSequence:1,...extra})
const deferred = () => { let resolve,reject; const promise = new Promise((yes,no)=>{resolve=yes;reject=no}); return {promise,resolve,reject} }
test('context events expose counts and purpose without copying summary or raw history',async()=>{
  const {normalizeTraceEvents,eventCategory,eventTitle,filterTraceEvents,traceModelRequests}=await projection
  const rows=normalizeTraceEvents([event(1,'CONTEXT_COMPLETED',{purpose:'CONTEXT_COMPACTION',beforeMessages:32,afterMessages:7,beforeChars:24000,afterChars:3000,summary:'PRIVATE_SUMMARY',history:'PRIVATE_HISTORY'})])
  assert.equal(eventCategory(rows[0].type),'CONTEXT');assert.equal(eventTitle(rows[0]),'上下文压缩已应用')
  assert.equal(filterTraceEvents(rows,'CONTEXT').length,1);assert.equal(filterTraceEvents(rows,'MODEL').length,0)
  assert.deepEqual(rows[0].payload,{purpose:'CONTEXT_COMPACTION',beforeMessages:32,afterMessages:7,beforeChars:24000,afterChars:3000})
  const models=traceModelRequests(normalizeTraceEvents([event(2,'MODEL_STARTED',{modelRequestId:'summary',purpose:'CONTEXT_COMPACTION'}),event(3,'MODEL_STARTED',{modelRequestId:'reasoning'})]),'COMPLETED')
  assert.equal(models[0].purpose,'CONTEXT_COMPACTION');assert.equal(models[1].purpose,null)
})
async function fixture(overrides={}) {
  const {createTraceReader,initialTraceState} = await readerModule
  const {normalizeTraceEvents,traceCompleteness} = await projection
  const state=initialTraceState()
  const api={run: async id=>({data:run(id)}),list:async()=>({data:[]}),events:async()=>({data:[event(1,'RUN_COMPLETED')]}),session:async id=>({data:{data:{sessionId:id,messages:[{id:1,content:id}]}}}),...overrides}
  return {state,reader:createTraceReader(api,state,normalizeTraceEvents,traceCompleteness)}
}

test('trace projection keeps explicit zeroes and removes unrecorded or sensitive payload fields', async()=>{
  const {normalizeTraceEvents,traceDuration}=await projection
  const rows=normalizeTraceEvents([event(1,'MODEL_COMPLETED',{durationMs:0,inputTokens:0,outputTokens:-1,agent:'main',apiKey:'secret',arguments:{url:'https://private'},reasoning:'private'})])
  assert.deepEqual(rows[0].payload,{agent:'main',durationMs:0,inputTokens:0})
  assert.equal(traceDuration(0),'0 ms');assert.equal(traceDuration(undefined),'未记录');assert.equal(traceDuration(-1),'未记录')
})
test('event cursor requires contiguous server sequence numbers, not just the greatest loaded sequence',async()=>{
  const {normalizeTraceEvents,traceCompleteness}=await projection
  const rows=normalizeTraceEvents([event(3,'RUN_COMPLETED'),event(1,'RUN_STARTED'),event(3,'RUN_ERROR'),event(-1,'MODEL_STARTED')])
  assert.deepEqual(rows.map(e=>e.sequence),[1,3])
  assert.deepEqual(traceCompleteness(rows,3),{complete:false,cursor:1})
  assert.deepEqual(traceCompleteness([],0),{complete:true,cursor:0})
  assert.equal(traceCompleteness([],undefined).complete,false)
})
test('tool calls correlate by agent parent and call ID, without pairing by tool name',async()=>{
  const {traceCalls,traceSummary}=await projection
  const p={agent:'main',tool:'fetch',callId:'same'}
  const rows=[event(1,'AUTHORIZATION_ALLOWED',p),event(2,'TOOL_STARTED',p),event(3,'TOOL_STARTED',{...p,callId:'other'}),event(4,'TOOL_COMPLETED',{...p,durationMs:0}),event(5,'AUTHORIZATION_DENIED',{...p,agent:'child',parentCallId:'same'})]
  const calls=traceCalls(rows,'COMPLETED')
  assert.equal(calls.length,3);assert.equal(calls[0].status,'SUCCESS');assert.equal(calls[0].durationMs,0)
  assert.equal(calls[1].status,'INCOMPLETE');assert.equal(calls[1].durationMs,null);assert.equal(calls[2].status,'DENIED')
  assert.equal(traceSummary(rows,'COMPLETED').tools,2)
  assert.equal(traceCalls([event(1,'TOOL_STARTED',{tool:'fetch'}),event(2,'TOOL_COMPLETED',{tool:'fetch'})],'COMPLETED').length,2)
})
test('missing tool completion is pending only while the run is actually running',async()=>{
  const {traceCalls}=await projection
  const rows=[event(1,'TOOL_STARTED',{tool:'fetch',callId:'x'})]
  assert.equal(traceCalls(rows,'RUNNING')[0].status,'PENDING')
  assert.equal(traceCalls(rows,'INTERRUPTED')[0].status,'INCOMPLETE')
})
test('token totals distinguish absent usage from an explicit zero and exclude unrelated event fields',async()=>{
  const {traceSummary}=await projection
  assert.equal(traceSummary([event(1,'MODEL_STARTED')]).inputTokens,null)
  const summary=traceSummary([event(1,'MODEL_COMPLETED',{inputTokens:0,outputTokens:2}),event(2,'TOOL_COMPLETED',{inputTokens:999}),event(3,'MODEL_COMPLETED',{})])
  assert.equal(summary.inputTokens,0);assert.equal(summary.outputTokens,2);assert.equal(summary.usageRecords,1)
})

test('model routes correlate by explicit request ID and keep fallback attempts separate from logical token usage',async()=>{
  const {normalizeTraceEvents,traceModelRequests,traceSummary,modelFailureLabel}=await projection
  const p={agent:'main',modelRequestId:'request-1',modelId:'custom:primary',provider:'custom',model:'primary',attempt:1}
  const rows=normalizeTraceEvents([event(1,'MODEL_STARTED',{agent:'main',modelRequestId:'request-1'}),event(2,'MODEL_ATTEMPT_STARTED',p),
    event(3,'MODEL_ATTEMPT_ERROR',{...p,failureReason:'QUOTA',httpStatus:402,durationMs:0}),
    event(4,'MODEL_FALLBACK_SELECTED',{...p,nextModelId:'deepseek:backup',failureReason:'QUOTA'}),
    event(5,'MODEL_ATTEMPT_STARTED',{...p,modelId:'deepseek:backup',provider:'deepseek',model:'backup',attempt:2}),
    event(6,'MODEL_ATTEMPT_COMPLETED',{...p,modelId:'deepseek:backup',provider:'deepseek',model:'backup',attempt:2,firstContentMs:0,durationMs:0,inputTokens:999}),
    event(7,'MODEL_COMPLETED',{agent:'main',modelRequestId:'request-1',inputTokens:10,outputTokens:2})])
  const routes=traceModelRequests(rows,'COMPLETED')
  assert.equal(routes.length,1);assert.equal(routes[0].attempts.length,2)
  assert.equal(routes[0].attempts[0].failureReason,'QUOTA');assert.equal(routes[0].attempts[1].status,'SUCCESS')
  assert.equal(routes[0].attempts[1].firstContentMs,0)
  const summary=traceSummary(rows,'COMPLETED')
  assert.equal(summary.modelRequests,1);assert.equal(summary.modelAttempts,2);assert.equal(summary.fallbackSelections,1);assert.equal(summary.inputTokens,10)
  assert.equal(modelFailureLabel('QUOTA'),'额度或余额不足')
})

test('model skips never become requests and old records never infer an actual provider',async()=>{
  const {traceModelRequests,traceSummary}=await projection
  assert.deepEqual(traceModelRequests([event(1,'MODEL_STARTED',{agent:'main'})],'COMPLETED'),[])
  const p={agent:'main',modelRequestId:'r',modelId:'custom:primary',provider:'custom',attempt:1}
  const rows=[event(1,'MODEL_CANDIDATE_SKIPPED',{...p,failureReason:'CIRCUIT_OPEN'})]
  assert.equal(traceModelRequests(rows,'COMPLETED')[0].attempts[0].status,'SKIPPED')
  assert.equal(traceSummary(rows,'COMPLETED').modelAttempts,0)
})

test('same model request IDs in other agents or delegation contexts cannot merge and missing terminals stay missing',async()=>{
  const {traceModelRequests}=await projection
  const p={agent:'main',modelRequestId:'r',modelId:'primary',attempt:1}
  const rows=[event(1,'MODEL_ATTEMPT_STARTED',p),event(2,'MODEL_ATTEMPT_STARTED',{...p,parentCallId:'delegate'}),
    event(3,'MODEL_ATTEMPT_COMPLETED',{...p,agent:'child',durationMs:2})]
  const routes=traceModelRequests(rows,'INTERRUPTED')
  assert.equal(routes.length,3);assert.equal(routes[0].attempts[0].status,'INCOMPLETE');assert.equal(routes[1].attempts[0].status,'INCOMPLETE')
  assert.equal(routes[2].attempts[0].status,'SUCCESS')
  assert.equal(traceModelRequests(rows,'RUNNING')[0].attempts[0].status,'PENDING')
})
test('event filters search readable titles and recorded IDs without fabricating model or source metadata',async()=>{
  const {filterTraceEvents,eventTitle,eventTone}=await projection
  const rows=[event(1,'MODEL_STARTED',{agent:'main'}),event(2,'TOOL_STARTED',{tool:'fetch',parentCallId:'parent-42'}),event(3,'COMMAND_REJECTED')]
  assert.equal(filterTraceEvents(rows,'TOOL','PARENT-42').length,1)
  assert.equal(filterTraceEvents(rows,'MODEL','模型请求').length,1)
  assert.equal(eventTitle(rows[2]),'技能命令被拒绝');assert.equal(eventTone(rows[2].type),'danger')
})
test('a delayed run detail cannot replace a more recently selected run',async()=>{
  const slow=deferred()
  const {reader,state}=await fixture({run:id=>id==='a'?slow.promise:Promise.resolve({data:run(id)})})
  const old=reader.select('a');await reader.select('b');slow.resolve({data:run('a')});await old
  assert.equal(state.selectedRun.runId,'b');assert.equal(state.messages[0].content,'session-b');assert.equal(state.detailLoading,false)
})
test('a delayed event response and session response are discarded after switching run',async()=>{
  const slowEvents=deferred(),slowMessages=deferred()
  const {reader,state}=await fixture({events:id=>id==='a'?slowEvents.promise:Promise.resolve({data:[event(1,'RUN_COMPLETED',{agent:'b'})]}),session:id=>id==='session-a'?slowMessages.promise:Promise.resolve({data:{data:{sessionId:id,messages:[{content:'b context'}]}}})})
  const old=reader.select('a');await new Promise(resolve=>setImmediate(resolve));await reader.select('b')
  slowEvents.resolve({data:[event(1,'RUN_COMPLETED',{agent:'a'})]});slowMessages.resolve({data:{data:{sessionId:'session-a',messages:[{content:'a secret'}]}}});await old
  assert.equal(state.events[0].payload.agent,'b');assert.equal(state.messages[0].content,'b context');assert.equal(state.eventsLoading,false)
})
test('an explicit inaccessible deep link clears the prior selection and does not fall back to another run',async()=>{
  const {reader,state}=await fixture({run:async id=>{if(id==='blocked')throw{response:{status:404}};return{data:run(id)}}})
  await reader.select('a');await reader.select('blocked')
  assert.equal(state.selectedRun,null);assert.deepEqual(state.events,[]);assert.deepEqual(state.messages,[]);assert.match(state.detailError,/无访问权限/)
})
test('event gap backfill resumes after the contiguous cursor and removes duplicate sequence numbers',async()=>{
  const cursors=[]
  const {reader,state}=await fixture({run:async id=>({data:run(id,{lastSequence:3})}),events:async(id,after)=>{cursors.push(after);return{data:after===0?[event(1,'RUN_STARTED'),event(3,'RUN_COMPLETED')]:[event(2,'MODEL_COMPLETED'),event(3,'RUN_COMPLETED')]}}})
  await reader.select('a');assert.equal(state.hasMoreEvents,true);await reader.loadMore()
  assert.deepEqual(cursors,[0,1]);assert.deepEqual(state.events.map(e=>e.sequence),[1,2,3]);assert.equal(state.hasMoreEvents,false)
})
test('metadata refresh transitions a running record to its persisted terminal state without invoking a write',async()=>{
  let reads=0
  const {reader,state}=await fixture({run:async id=>({data:run(id,{status:++reads===1?'RUNNING':'COMPLETED',lastSequence:reads===1?1:2})}),events:async(id,after)=>({data:after?[event(2,'RUN_COMPLETED')]:[event(1,'RUN_STARTED')]})})
  await reader.select('a');await reader.refresh()
  assert.equal(state.selectedRun.status,'COMPLETED');assert.equal(state.events.length,2);assert.equal(state.hasMoreEvents,false)
})
test('ownership revocation during refresh removes previously displayed events and messages',async()=>{
  let reads=0
  const {reader,state}=await fixture({run:async id=>{if(++reads>1)throw{response:{status:404}};return{data:run(id)}}})
  await reader.select('a');await reader.refresh()
  assert.equal(state.selectedRun,null);assert.deepEqual(state.events,[]);assert.deepEqual(state.messages,[])
})
test('disposed readers ignore delayed list responses and release loading flags',async()=>{
  const slow=deferred();const {reader,state}=await fixture({list:()=>slow.promise})
  const pending=reader.history({sessionId:'a'});reader.dispose();slow.resolve({data:[run('a')]});await pending
  assert.deepEqual(state.runs,[]);assert.equal(state.historyLoading,false)
})
test('session payload must belong to the selected run before its messages can be displayed',async()=>{
  const {reader,state}=await fixture({session:async()=>({data:{data:{sessionId:'different',messages:[{content:'other session'}]}}})})
  await reader.select('a');assert.deepEqual(state.messages,[]);assert.match(state.messagesError,/暂不可用/)
})
test('an event endpoint ownership denial also clears the previously loaded run',async()=>{
  let reads=0
  const {reader,state}=await fixture({events:async()=>{if(++reads>1)throw{response:{status:404}};return{data:[event(1,'RUN_STARTED')]}}})
  await reader.select('a');await reader.loadMore()
  assert.equal(state.selectedRun,null);assert.deepEqual(state.events,[]);assert.deepEqual(state.messages,[])
})
test('a slow history response cannot overwrite a newer account-scope selection',async()=>{
  const slow=deferred()
  const {reader,state}=await fixture({list:params=>params.sessionId==='a'?slow.promise:Promise.resolve({data:[run('b')]})})
  const old=reader.history({sessionId:'a'});await reader.history({sessionId:'b'});slow.resolve({data:[run('a')]});await old
  assert.deepEqual(state.runs.map(item=>item.runId),['b']);assert.equal(state.historyLoading,false)
})

test('delayed research sources cannot replace evidence for a newer run',async()=>{
  const slow=deferred(), view=id=>({data:{runId:id,enabled:true,sources:[],citations:[]}})
  const {reader,state}=await fixture({sources:id=>id==='a'?slow.promise:Promise.resolve(view(id))})
  const old=reader.select('a');await new Promise(resolve=>setImmediate(resolve));await reader.select('b');slow.resolve(view('a'));await old
  assert.equal(state.evidence.runId,'b');assert.equal(state.evidenceLoading,false)
})

test('sources from another run are rejected and evidence endpoint denial clears all run data',async()=>{
  let reads=0
  const {reader,state}=await fixture({sources:async id=>{if(++reads>1)throw{response:{status:404}};return{data:{runId:id,sources:[{runId:'other'}]}}}})
  await reader.select('a');assert.equal(state.evidence,null);assert.match(state.evidenceError,/读取失败/)
  await reader.loadEvidence();assert.equal(state.selectedRun,null);assert.deepEqual(state.events,[]);assert.deepEqual(state.messages,[]);assert.equal(state.evidence,null)
})
