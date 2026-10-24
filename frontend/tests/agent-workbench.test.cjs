const test=require('node:test'),assert=require('node:assert/strict')
const {readFrontendFile}=require('./helpers/project-source.cjs')
const utility=import(`data:text/javascript;base64,${Buffer.from(readFrontendFile('src','utils','agentWorkbench.js')).toString('base64')}`)
const id='00000000-0000-0000-0000-000000000001'
test('recovery model choice is explicit and bound to a verified configuration version',async()=>{
 const {recoveryInput}=await utility
 assert.deepEqual(recoveryInput('KEEP',{}),{})
 const state={recoveryConfigVersion:9,recoveryDefault:'dashscope:new',recoveryModels:[{id:'dashscope:new'},{id:'deepseek:new'}]}
 assert.deepEqual(recoveryInput('CURRENT_DEFAULT',state),{replacementModelId:'',replacementConfigVersion:9})
 assert.deepEqual(recoveryInput('deepseek:new',state),{replacementModelId:'deepseek:new',replacementConfigVersion:9})
 assert.throws(()=>recoveryInput('removed',state),/已不可用/)
 assert.throws(()=>recoveryInput('CURRENT_DEFAULT',{...state,recoveryModelError:'unavailable'}),/先核对/)
 assert.throws(()=>recoveryInput('CURRENT_DEFAULT',{...state,recoveryModelsLoading:true}),/先核对/)
})
test('catalog failure preserves the workbench and reconciliation never submits a mutation',async()=>{
 const {AgentWorkbenchClient,recoveryInput}=await utility
 let fails=true;const requests=[]
 const client=new AgentWorkbenchClient({fetcher:async(path,options)=>{requests.push([path,options.method]);if(path.endsWith('/capabilities'))return response({enabled:true,modelConfig:true});if(path==='/agui/models'){if(fails)throw Error('offline');return response({configVersion:9,selectedModel:'dashscope:new',models:[{id:'dashscope:new',model:'new',provider:'dashscope',configured:true},{id:'unconfigured',model:'none',configured:false}]})}return response({items:[],files:[]})}})
 try{await client.open('mine');assert.equal(client.value.enabled,true);assert.match(client.value.recoveryModelError,/尚未核对/);assert.deepEqual(recoveryInput('KEEP',client.value),{});fails=false;await client.loadRecoveryModels();assert.equal(client.value.recoveryConfigVersion,9);assert.equal(client.value.recoveryModels.length,1);assert.equal(client.value.recoveryModelError,'');assert.ok(requests.every(([,method])=>!method))}finally{client.close()}
})
test('late recovery catalog cannot overwrite another session or leave its spinner active',async()=>{
 const {AgentWorkbenchClient}=await utility
 let release,reads=0
 const client=new AgentWorkbenchClient({fetcher:async path=>path.endsWith('/capabilities')?response({enabled:true,modelConfig:true}):path==='/agui/models'?(++reads===1?new Promise(resolve=>{release=()=>resolve(response({configVersion:7,selectedModel:'old',models:[]}))}):response({configVersion:8,selectedModel:'new',models:[]})):response({items:[],files:[]})})
 try{const old=client.open('old');while(!release)await new Promise(resolve=>setImmediate(resolve));await client.open('new');release();await old;assert.equal(client.value.recoveryConfigVersion,8);assert.equal(client.value.recoveryDefault,'new');assert.equal(client.value.recoveryModelsLoading,false)}finally{client.close()}
})
const snapshot={items:[{id,kind:'QUESTION',status:'PENDING',revision:0,data:{text:'<script>plain text</script>',questionType:'TEXT'}}],files:[],lineage:{sourceSessionId:'parent'}}
const response=(body,ok=true,status=200)=>({ok,status,json:async()=>body})
test('workbench projection validates private IDs, versions and files while preserving plain text',async()=>{const {normalizeWorkbench}=await utility;assert.equal(normalizeWorkbench(snapshot).items[0].data.text,snapshot.items[0].data.text);assert.throws(()=>normalizeWorkbench({...snapshot,items:[snapshot.items[0],snapshot.items[0]]}));assert.throws(()=>normalizeWorkbench({...snapshot,items:[{...snapshot.items[0],revision:-1}]}));assert.throws(()=>normalizeWorkbench({...snapshot,files:[{id,name:'x',bytes:-1,contentType:'text/plain'}]}))})
test('unknown answers retain request identity and never automatically resubmit',async()=>{const {AgentWorkbenchClient}=await utility;let attempts=0;const posts=[];const client=new AgentWorkbenchClient({fetcher:async(path,options)=>{if(options.method){posts.push(JSON.parse(options.body));if(++attempts===1)throw Error('network')}return response(snapshot)}});client.session='s1';client.value.enabled=true;try{await assert.rejects(()=>client.command(snapshot.items[0],'answer',{answer:'A'}));assert.equal(posts.length,1);await client.command(snapshot.items[0],'answer',{answer:'A'});assert.equal(posts.length,2);assert.equal(posts[0].requestId,posts[1].requestId)}finally{client.close()}})
test('late reads cannot replace the selected conversation',async()=>{const {AgentWorkbenchClient}=await utility;let release;const client=new AgentWorkbenchClient({fetcher:async path=>path.endsWith('/capabilities')?response({enabled:true}):path.includes('/old/')?new Promise(resolve=>release=()=>resolve(response(snapshot))):response({...snapshot,items:[]})});try{const old=client.open('old');await new Promise(resolve=>setImmediate(resolve));await client.open('new');release();await old;assert.equal(client.session,'new');assert.equal(client.value.items.length,0)}finally{client.close()}})
test('missing usage stays unknown, and values are not presented as billing',async()=>{const {tokenDisplay,workbenchRows}=await utility;assert.equal(tokenDisplay(null),'未知');assert.equal(tokenDisplay(-1),'未知');assert.equal(tokenDisplay(0),'0');assert.equal(workbenchRows([{kind:'EXECUTION',status:'NEEDS_REVIEW'}],'RECOVERY').length,1)})

test('background completion notifies once after an observed transition, without replaying history or crossing sessions',async()=>{
 const {AgentWorkbenchClient}=await utility
 let status='COMPLETED',revision=1
 const client=new AgentWorkbenchClient({fetcher:async path=>response(path.endsWith('/capabilities')?{enabled:true}:{items:[{id,kind:'CHILD',status,revision,data:{title:'专业分析'}}],files:[]})})
 try{await client.open('one');assert.deepEqual(client.value.notifications,[])
  status='RUNNING';revision++;await client.poll();assert.deepEqual(client.value.notifications,[])
  status='COMPLETED';revision++;await client.poll();assert.equal(client.value.notifications.length,1);assert.match(client.value.notifications[0].text,/专业分析：已完成/)
  await client.poll();assert.equal(client.value.notifications.length,1)
  await client.open('two');assert.deepEqual(client.value.notifications,[])
 }finally{client.close()}
})
