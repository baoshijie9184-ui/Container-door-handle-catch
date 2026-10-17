const test=require('node:test'),assert=require('node:assert/strict')
const {readFrontendFile}=require('./helpers/project-source.cjs')
const utility=import(`data:text/javascript;base64,${Buffer.from(readFrontendFile('src','utils','conversationControl.js')).toString('base64')}`)
const id='00000000-0000-0000-0000-000000000001'
const snapshot=(session='s1',extra={})=>({run:{sessionId:session,runId:'run-1',phase:'RUNNING',revision:0,local:true,text:''},inputs:[{id,mode:'NEXT_TURN',status:'QUEUED',revision:0,content:'<img src=x> plain text'}],...extra})
const response=(body,ok=true,status=200)=>({ok,status,json:async()=>body})

test('per-row steering promotes the same input and version without creating a second submission',async()=>{
 const {ConversationControlClient}=await utility;const posts=[]
 const client=new ConversationControlClient({fetcher:async(path,options)=>{if(options.method)posts.push({path,body:JSON.parse(options.body)});return response(snapshot())}});client.enabled=true;client.session='s1';client.state=snapshot()
 try{await client.steer({...snapshot().inputs[0],revision:2});assert.deepEqual(posts,[{path:'/api/agent/conversations/s1/inputs/'+id+'/steer',body:{revision:2,runId:'run-1'}}]);client.state.run.runId=null;assert.throws(()=>client.steer(snapshot().inputs[0]),/没有可引导/)}finally{client.close()}
})

test('closing queue prevents new ordinary queued sends and preserves existing rows and explicit steering',async()=>{
 const {ConversationControlClient}=await utility;const posts=[]
 const client=new ConversationControlClient({fetcher:async(path,options)=>{if(options.method)posts.push(path);return response(snapshot())}});client.enabled=true;client.session='s1';client.state=snapshot()
 try{client.setQueueEnabled(false);await assert.rejects(()=>client.submit('new'),/排队已关闭/);assert.equal(posts.length,0);assert.equal(client.state.inputs.length,1);await client.steer(client.state.inputs[0]);client.setQueueEnabled(true);await client.submit('new');assert.equal(posts.length,2)}finally{client.close()}
})
test('control projection validates scope and known phases without rendering supplied HTML',async()=>{
 const {normalizeControl}=await utility
 assert.equal(normalizeControl(snapshot(),'s1').inputs[0].content,'<img src=x> plain text')
 assert.throws(()=>normalizeControl(snapshot(),'other'))
 for(const phase of ['constructor','__proto__','FUTURE'])assert.throws(()=>normalizeControl(snapshot('s1',{run:{...snapshot().run,phase}}),'s1'))
 assert.throws(()=>normalizeControl(snapshot('s1',{inputs:[snapshot().inputs[0],snapshot().inputs[0]]}),'s1'))
 assert.throws(()=>normalizeControl(snapshot('s1',{run:{...snapshot().run,text:'x'.repeat(64001)}}),'s1'))
})
test('uncertain explicit submissions retain their request ID across other messages and never automatically retry',async()=>{
 const {ConversationControlClient}=await utility;const posts=[]
 const client=new ConversationControlClient({fetcher:async(path,options)=>{if(options.method){posts.push(JSON.parse(options.body));assert.equal(options.headers['X-Agent-Action'],'conversation-control');if(posts.length===1)throw Error('network');return response({})}return response(snapshot())}})
 client.enabled=true;client.session='s1';client.state=snapshot()
 try{
  await assert.rejects(()=>client.submit('first'))
  assert.equal(posts.length,1)
  await client.submit('second');await client.submit('first')
  assert.equal(posts[0].id,posts[2].id);assert.notEqual(posts[0].id,posts[1].id)
 }finally{client.close()}
})
test('late reads from an old conversation cannot replace the selected session',async()=>{
 const {ConversationControlClient}=await utility;let release;const seen=[]
 const client=new ConversationControlClient({fetcher:async path=>path.endsWith('/capabilities')?response({enabled:true}):path.includes('/old/')?new Promise(resolve=>release=()=>resolve(response(snapshot('old')))):response(snapshot('new')),onState:state=>seen.push(state)})
 try{const old=client.open('old');await new Promise(resolve=>setImmediate(resolve));await client.open('new');release();await old;assert.equal(client.state.run.sessionId,'new');assert.equal(seen.at(-1).run.sessionId,'new')}finally{client.close()}
})
test('failed state reads clear stale controls and prevent further mutations',async()=>{
 const {ConversationControlClient}=await utility;let state
 const client=new ConversationControlClient({fetcher:async()=>response({},false,503),onState:value=>state=value});client.enabled=true;client.session='s1';client.state=snapshot()
 try{await client.poll();assert.equal(client.state,null);assert.equal(state.run,null);await assert.rejects(()=>client.submit('question'));assert.throws(()=>client.command('pause'))}finally{client.close()}
})
test('a disabled or older server leaves both conversation actions and mutation requests off',async()=>{
 const {ConversationControlClient}=await utility;const calls=[]
 const client=new ConversationControlClient({fetcher:async(path,options)=>{calls.push(options);return response({},false,404)}})
 try{await client.open('s1');assert.equal(client.enabled,false);await assert.rejects(()=>client.submit('query'));assert.equal(calls.filter(call=>call.method).length,0)}finally{client.close()}
})
test('remote execution is readable but cannot be paused through the wrong instance',async()=>{
 const {ConversationControlClient}=await utility;const client=new ConversationControlClient();client.enabled=true;client.session='s1';client.state={...snapshot(),run:{...snapshot().run,local:false,phase:'REMOTE_RUNNING'}}
 try{assert.throws(()=>client.command('pause'),/当前实例/)}finally{client.close()}
})
test('a slower earlier read cannot overwrite a newer phase in the same conversation',async()=>{
 const {ConversationControlClient}=await utility;let release,calls=0
 const client=new ConversationControlClient({fetcher:async()=>++calls===1?new Promise(resolve=>release=()=>resolve(response(snapshot()))):response(snapshot('s1',{run:{...snapshot().run,phase:'PAUSED',revision:2}}))})
 client.enabled=true;client.session='s1'
 try{const slow=client.poll();await client.poll();release();await slow;assert.equal(client.state.run.phase,'PAUSED');assert.equal(client.state.run.revision,2)}finally{client.close()}
})
