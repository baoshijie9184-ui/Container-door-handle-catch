const test = require('node:test'), assert = require('node:assert/strict')
const { readFrontendFile } = require('./helpers/project-source.cjs')
const moduleUrl = code => 'data:text/javascript;base64,' + Buffer.from(code).toString('base64')
const accountModule = import(moduleUrl(readFrontendFile('src','utils','accountContext.js')))
const realtimeModule = import(moduleUrl(readFrontendFile('src','utils','realtimeChanges.js')))
const versionModule = import(moduleUrl(readFrontendFile('src','utils','mutationVersion.js').replace(
  "'./requestIdentity'", JSON.stringify(moduleUrl(readFrontendFile('src','utils','requestIdentity.js'))))))
const diffModule = import(moduleUrl(readFrontendFile('src','utils','changeHistory.js')))
const cacheModule = import(moduleUrl(readFrontendFile('src','utils','accountTaskCache.js')))
const fetchModule = import(moduleUrl(readFrontendFile('src','utils','accountFetch.js')
  .replace("'./accountContext'",JSON.stringify(moduleUrl(readFrontendFile('src','utils','accountContext.js'))))
  .replace("'./requestIdentity'",JSON.stringify(moduleUrl(readFrontendFile('src','utils','requestIdentity.js'))))))
const user = (accountContext='context-a', overrides={}) => ({authenticated:true,userId:'21',username:'supervisor-a',role:'SUPERVISOR',
  accountContext,capabilities:{sessionTracking:true,realtime:true,changeHistory:true},...overrides})
const flush = async () => { for(let i=0;i<12;i++)await Promise.resolve() }

function browser({shared=true}={}) {
  let time=100000, sequence=0
  const sources=[], channels=new Map(), held=new Set(), timers=new Set()
  class Channel {
    constructor(name){this.name=name;if(!channels.has(name))channels.set(name,new Set());channels.get(name).add(this)}
    postMessage(data){for(const peer of channels.get(this.name)||[])if(peer!==this)peer.onmessage?.({data})}
    close(){channels.get(this.name)?.delete(this)}
  }
  class Source {
    constructor(url,options){this.url=url;this.options=options;this.readyState=0;this.listeners={};sources.push(this)}
    addEventListener(type,fn){this.listeners[type]=fn}
    close(){this.closed=true;this.readyState=2}
    emit(type,data){this.listeners[type]?.({data:JSON.stringify(data)})}
  }
  const locks={request:async(name,_options,callback)=>{
    if(held.has(name))return callback(null)
    held.add(name);try{return await callback({name})}finally{held.delete(name)}
  }}
  const environment={navigator:shared?{locks}:{},BroadcastChannel:shared?Channel:undefined,EventSource:Source,
    document:{visibilityState:'visible',addEventListener(){},removeEventListener(){}},
    addEventListener(){},removeEventListener(){},setInterval(){const id=++sequence;timers.add(id);return id},clearInterval(id){timers.delete(id)}}
  return {environment,sources,timers,now:()=>time,advance:ms=>{time+=ms}}
}
async function fixture(options) {
  const {createAccountContext}=await accountModule,{createRealtimeChanges}=await realtimeModule
  const session=createAccountContext(),fake=browser(options);session.accept(user())
  const hub=createRealtimeChanges({session,environment:fake.environment,now:fake.now,checkAuth:async()=>true})
  hub.start();await flush();return {session,hub,...fake}
}

test('account switch aborts old requests, clears caches and rejects late identity reads',async()=>{
  const {createAccountContext}=await accountModule,session=createAccountContext();let resets=0
  session.onReset(()=>resets++);session.accept(user());const old=session.stamp()
  session.accept(user('context-b',{userId:'22',username:'supervisor-b'}))
  assert.equal(old.signal.aborted,true);assert.equal(session.current(old),false);assert.equal(resets,1)
  assert.throws(()=>session.accept(user(),old.epoch),{code:'ACCOUNT_CONTEXT_CHANGED'})
  assert.equal(session.state.user.username,'supervisor-b')
})
test('legacy identity is read-only and unsupported login roles invalidate old authorization',async()=>{
  const {createAccountContext}=await accountModule,session=createAccountContext()
  session.accept(user(undefined,{accountContext:undefined,capabilities:{}}));assert.equal(session.state.blocked,true)
  assert.throws(()=>session.accept(user('context-a',{role:'MAINTENANCE'})),{code:'ACCOUNT_CONTEXT_CHANGED'})
  assert.equal(session.state.authenticated,false)
})
test('a changed personnel binding invalidates same-account cached scopes',async()=>{
  const {createAccountContext}=await accountModule,session=createAccountContext()
  session.accept(user('same',{identity:{employeeId:'31',bindingVersion:'5'}}));const old=session.stamp()
  session.accept(user('same',{identity:{employeeId:'32',bindingVersion:'6'}}))
  assert.equal(session.current(old),false)
})
test('request abort composes caller cancellation with the account lifetime',async()=>{
  const {accountSignal}=await accountModule,a=new AbortController(),b=new AbortController()
  const signal=accountSignal(a.signal,b.signal);b.abort();assert.equal(signal.aborted,true)
})
test('versions preserve bigint precision and model release names never become row versions',async()=>{
  const {decimalVersion,resourceVersion,mutationHeaders,responseResourceVersion}=await versionModule
  assert.equal(decimalVersion('9223372036854775807'),'9223372036854775807')
  assert.equal(decimalVersion(Number.MAX_SAFE_INTEGER+1),null)
  assert.equal(resourceVersion({version:'v1'},{model:true}),null)
  assert.equal(resourceVersion({version:'v1',rowVersion:'9'},{model:true}),'9')
  assert.equal(mutationHeaders('9','request-a')['If-Match'],'"9"')
  assert.equal(responseResourceVersion({headers:{'x-resource-version':'10'},data:{data:{resource:{version:'8'}}}}),'10')
})
test('draft snapshots retain the version read on opening and repeat the same request identity',async()=>{
  const {captureTaskMutation,taskMutationPayload}=await versionModule
  const row={taskId:'task-a',version:'4',result:{version:'4'}},snapshot=captureTaskMutation(row)
  row.version='5';row.result.version='5'
  const first=taskMutationPayload(snapshot,{reviewConclusion:'NORMAL_RELEASE'})
  const retry=taskMutationPayload(snapshot,{reviewConclusion:'NORMAL_RELEASE'})
  assert.equal(first,retry);assert.equal(first.expectedVersion,'4');assert.ok(first.requestId)
  assert.throws(()=>taskMutationPayload(snapshot,{reviewConclusion:'CONFIRMED_DEFECT'}),/本次请求已发送/)
})
test('SSE receives named events, deduplicates and rejects version regression',async()=>{
  const value=await fixture(),events=[];value.hub.subscribe(event=>events.push(event))
  try{
    const change={accountContext:'context-a',eventId:'a',resourceType:'DETECTION_TASK',resourceId:'task-a',resourceVersion:'8'}
    value.sources[0].emit('resource-changed',change)
    value.sources[0].emit('resource-changed',change)
    value.sources[0].emit('resource-changed',{...change,eventId:'b',resourceVersion:'7'})
    assert.equal(events.filter(event=>event.type==='resource-changed').length,1)
  }finally{value.hub.dispose()}
})
test('version gaps and unknown event schemas trigger reads, never synthesize changes',async()=>{
  const value=await fixture(),events=[];value.hub.subscribe(event=>events.push(event))
  try{
    const change={accountContext:'context-a',eventId:'a',resourceType:'DETECTION_TASK',resourceId:'task-a',resourceVersion:'8'}
    value.sources[0].emit('resource-changed',change)
    value.sources[0].emit('resource-changed',{...change,eventId:'b',resourceVersion:'10'})
    value.sources[0].emit('resource-changed',{...change,eventId:'c',schemaVersion:99})
    assert.ok(events.some(event=>event.reason==='version-gap'));assert.ok(events.some(event=>event.reason==='unknown-event'))
    assert.equal(events.filter(event=>event.type==='resource-changed').length,2)
  }finally{value.hub.dispose()}
})
test('other-account events are ignored and changing account closes the old stream',async()=>{
  const value=await fixture(),events=[];value.hub.subscribe(event=>events.push(event))
  try{
    value.sources[0].emit('resource-changed',{accountContext:'other',eventId:'a',resourceType:'DEVICE',resourceId:'1',resourceVersion:'1'})
    assert.equal(events.length,0);value.session.accept(user('context-b'));await flush()
    assert.equal(value.sources[0].closed,true)
  }finally{value.hub.dispose()}
})
test('same-context tabs share one stream and a released leader can be replaced',async()=>{
  const {createRealtimeChanges}=await realtimeModule,value=await fixture()
  const other=createRealtimeChanges({session:value.session,environment:value.environment,now:value.now,checkAuth:async()=>true})
  try{
    other.start();await flush();assert.equal(value.sources.length,1)
    value.hub.stop();await flush();await other.tick();await flush()
    assert.equal(value.sources.length,2);assert.equal(value.sources.filter(item=>!item.closed).length,1)
  }finally{value.hub.dispose();other.dispose();assert.equal(value.timers.size,0)}
})
test('browsers without cross-tab locking allocate zero SSE streams and poll instead',async()=>{
  const value=await fixture({shared:false}),events=[];value.hub.subscribe(event=>events.push(event))
  try{assert.equal(value.sources.length,0);assert.equal(value.hub.status,'polling');value.advance(30000);await value.hub.tick();assert.ok(events.some(event=>event.type==='resync-required'))}
  finally{value.hub.dispose()}
})
test('feature switches close the stream and disable reconnect attempts',async()=>{
  const value=await fixture()
  try{value.session.accept(user('context-a',{capabilities:{sessionTracking:true,realtime:false}}));await flush();value.advance(70000);await value.hub.tick();assert.equal(value.sources[0].closed,true);assert.equal(value.sources.length,1);assert.equal(value.hub.status,'polling')}
  finally{value.hub.dispose()}
})
test('60 seconds without a server event rebuilds one stream after identity validation',async()=>{
  const value=await fixture()
  try{value.advance(61000);await value.hub.tick();await flush();assert.equal(value.sources[0].closed,true);assert.equal(value.sources.filter(item=>!item.closed).length,1)}
  finally{value.hub.dispose()}
})
test('history values distinguish absence, null, empty, boolean and protected fields',async()=>{
  const {changeValue}=await diffModule
  assert.equal(changeValue({operation:'ADD'},'before'),'字段不存在')
  assert.equal(changeValue({},'before'),'历史未记录')
  assert.equal(changeValue({before:null},'before'),'空值（NULL）')
  assert.equal(changeValue({before:''},'before'),'空字符串')
  assert.equal(changeValue({before:false},'before'),'否')
  assert.equal(changeValue({before:'secret',redacted:true},'before'),'内容已受保护')
})
function localCache(entries=[]) {
  const values=new Map(entries)
  return {get length(){return values.size},key:index=>[...values.keys()][index],getItem:key=>values.get(key)??null,
    setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key),values}
}
test('account reset removes only that account task and file checkpoints',async()=>{
  const {createAccountContext}=await accountModule,{createAccountTaskCache}=await cacheModule,session=createAccountContext()
  const storage=localCache([['another-app','keep'],['doorhandle:context-b:taskList','keep'],['doorhandle:context-a:other-feature','keep']])
  const cache=createAccountTaskCache({session,storage:()=>storage});session.onReset(previous=>cache.clear(previous.accountContext))
  session.accept(user());cache.writeTasks([{taskId:'a'}],session.stamp());cache.writeFile('a',{completed:['a.png']},session.stamp())
  session.accept(user('context-b',{userId:'22',username:'supervisor-b'}))
  assert.equal(storage.values.has('doorhandle:context-a:taskList'),false)
  assert.equal(storage.values.has('doorhandle:context-a:task_files_a'),false)
  assert.equal(storage.getItem('doorhandle:context-b:taskList'),'keep');assert.equal(storage.getItem('another-app'),'keep')
  assert.equal(storage.getItem('doorhandle:context-a:other-feature'),'keep')
})
test('a delayed upload rejection cannot write old checkpoints into the next account',async()=>{
  const {createAccountContext}=await accountModule,{createAccountTaskCache}=await cacheModule,session=createAccountContext(),storage=localCache()
  const cache=createAccountTaskCache({session,storage:()=>storage});session.onReset(previous=>cache.clear(previous.accountContext))
  session.accept(user());const original=session.stamp();let reject
  const upload=new Promise((_resolve,failure)=>{reject=failure}).catch(()=>{
    assert.equal(cache.writeFile('old-task',{failed:['private.png']},original),false)
    assert.equal(cache.writeTasks([{taskId:'old-task'}],original),false)
    assert.equal(cache.removeFile('new-task',original),false)
  })
  session.accept(user('context-b',{userId:'22',username:'supervisor-b'}));cache.writeFile('new-task',{completed:['b.png']},session.stamp())
  reject(Error('cancel arrived late'));await upload
  assert.deepEqual(cache.readFile('new-task'),{completed:['b.png']});assert.equal(cache.readFile('old-task'),null)
  assert.equal([...storage.values.keys()].some(key=>key.includes('context-a')),false)
})
test('an intent bound before an await cannot first send an unsafe AGUI request as another account',async()=>{
  const {accountSession}=await accountModule,{accountFetch}=await fetchModule,originalFetch=globalThis.fetch;const requests=[]
  globalThis.fetch=async(...args)=>{requests.push(args);return new Response('{}',{status:200})}
  try{
    accountSession.accept(user());const original=accountFetch.capture()
    await Promise.resolve();accountSession.accept(user('context-b',{userId:'22',username:'supervisor-b'}))
    await assert.rejects(original('/agui/run',{method:'POST',body:'{}'}),{code:'ACCOUNT_CONTEXT_CHANGED'})
    assert.equal(requests.length,0)
  }finally{globalThis.fetch=originalFetch;accountSession.clear()}
})
