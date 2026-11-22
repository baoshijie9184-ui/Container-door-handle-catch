const test=require('node:test'),assert=require('node:assert/strict');
const {readFrontendFile, importFrontendModule}=require('./helpers/project-source.cjs');
const mod=importFrontendModule('src','utils','composerResources.js')
const response=(value,status=200)=>({ok:status===200,status,json:async()=>value});
const fid='00000000-0000-0000-0000-000000000001';
const fixture=(path)=>path.endsWith('capabilities')?response({enabled:true,files:true}):path==='/agui/models'?response({models:[{id:'deepseek:demo',model:'demo',configured:true},{id:'missing',model:'missing',configured:false}]}):response({modelId:'',revision:0});
test('model choice is persisted through a versioned server command with stable retry identity',async()=>{
 const {ComposerResources}=await mod;let fail=true;const posts=[];const client=new ComposerResources({fetcher:async(path,opts)=>{if(opts.method){posts.push(JSON.parse(opts.body));if(fail){fail=false;throw Error('network')}return response({modelId:'deepseek:demo',revision:1})}return fixture(path)}});
 await client.open('mine');assert.equal(client.state.models.length,1);await assert.rejects(client.select('deepseek:demo'));assert.equal(client.state.modelId,'');await client.select('deepseek:demo');assert.equal(posts[0].requestId,posts[1].requestId);assert.equal(posts[1].revision,0);assert.equal(client.state.modelId,'deepseek:demo');
});

test('model labels distinguish provider routes and show the actual default without changing selection',async()=>{
 const {ComposerResources,modelLabel,defaultModelLabel,selectedModelMissing}=await mod;
 const client=new ComposerResources({fetcher:async(path)=>path==='/agui/models'?response({selectedModel:'dashscope:flash',fallbackEnabled:true,models:[{id:'dashscope:flash',provider:'dashscope',model:'flash',configured:true},{id:'deepseek:flash',provider:'deepseek',model:'flash',configured:true}]}):fixture(path)});
 await client.open('mine');assert.equal(client.state.modelId,'');assert.equal(defaultModelLabel(client.state),'系统默认 · flash · 百炼');assert.equal(client.state.fallbackEnabled,true);assert.equal(modelLabel(client.state.models[1]),'flash · DeepSeek 直连');assert.equal(selectedModelMissing({...client.state,modelId:'removed'}),true);
});

test('stale selection can be reconciled read-only without losing the draft or replaying a write',async()=>{
 const {ComposerResources}=await mod;let selection={modelId:'',revision:0};let writes=0;
 const client=new ComposerResources({fetcher:async(path,options)=>{if(options.method){writes++;selection={modelId:'deepseek:demo',revision:2};return response({},409)}return path.endsWith('/model-selection')?response(selection):fixture(path)}});
 await client.open('mine');client.draft('保留未发送的问题');client.publish({files:[{id:fid,name:'private.md',bytes:4}]});await assert.rejects(client.select('deepseek:demo'));
 assert.equal(client.state.modelError,false);assert.match(client.state.modelNotice,/状态已变化/);assert.equal(writes,1);assert.equal(client.state.modelId,'deepseek:demo');assert.equal(client.state.revision,2);assert.equal(client.state.modelError,false);assert.equal(client.text,'保留未发送的问题');assert.equal(client.state.files[0].id,fid);assert.equal(client.pending.size,0);
});

test('an uncertain switch is read back, and returning to system default persists with the current revision',async()=>{
 const {ComposerResources}=await mod;let selection={modelId:'',revision:0},lost=true;const writes=[];
 const client=new ComposerResources({fetcher:async(path,options)=>{if(options.method){const body=JSON.parse(options.body);writes.push(body);assert.equal(body.revision,selection.revision);selection={modelId:body.modelId,revision:selection.revision+1};if(lost){lost=false;throw Error('connection closed after commit')}return response(selection)}return path.endsWith('/model-selection')?response(selection):fixture(path)}});
 await client.open('mine');await assert.rejects(client.select('deepseek:demo'));assert.equal(writes.length,1);await client.refreshModels();assert.equal(writes.length,1);assert.equal(client.state.modelId,'deepseek:demo');await client.select('');assert.equal(writes[1].revision,1);assert.equal(client.state.modelId,'');assert.match(client.state.modelNotice,/当前会话/);await client.open('mine');assert.equal(client.state.revision,2);assert.equal(client.state.modelNotice,'');
});

test('a late selection readback cannot overwrite another conversation',async()=>{
 const {ComposerResources}=await mod;let release,hold=false;
 const client=new ComposerResources({fetcher:async(path)=>hold&&path.includes('/old/model-selection')?new Promise(resolve=>{release=()=>resolve(response({modelId:'deepseek:demo',revision:3}))}):fixture(path)});
 await client.open('old');hold=true;const readback=client.refreshModels();while(!release)await new Promise(resolve=>setImmediate(resolve));await client.open('new');release();await readback;assert.equal(client.state.modelId,'');assert.equal(client.state.revision,0);assert.equal(client.state.busy,false);assert.equal(client.state.modelNotice,'');
});

test('catalog failure is visible and read-only recovery leaves typed text intact',async()=>{
 const {ComposerResources}=await mod;let down=true;
 const client=new ComposerResources({fetcher:async(path)=>path==='/agui/models'&&down?response({},503):fixture(path)});
 await client.open('mine');client.draft('继续编辑');assert.equal(client.state.ready,false);assert.equal(client.state.modelError,true);down=false;await client.refreshModels();assert.equal(client.state.ready,true);assert.equal(client.text,'继续编辑');
});

test('malformed selection receipts do not replace the last confirmed model or revision',async()=>{
 const {ComposerResources}=await mod;const client=new ComposerResources({fetcher:async(path,options)=>options.method?response({modelId:123,revision:-1}):fixture(path)});
 await client.open('mine');await assert.rejects(client.select('deepseek:demo'),/响应无效/);assert.equal(client.state.modelId,'');assert.equal(client.state.revision,0);assert.equal(client.state.modelError,true);assert.equal(client.pending.size,1);
});
test('attachment is a private server ID and uncertain upload keeps its request ID',async()=>{
 const {ComposerResources}=await mod;let fail=true;const ids=[];const client=new ComposerResources({fetcher:async(path,opts)=>{if(opts.method){ids.push(opts.body.get('requestId'));assert.equal(opts.headers['X-Agent-Action'],'workbench');if(fail){fail=false;throw Error('network')}return response({id:fid,name:'private.md',bytes:4})}return fixture(path)}});
 await client.open('mine');const file=new File(['test'],'private.md',{type:'text/markdown'});await assert.rejects(client.upload([file]));assert.equal(client.state.files.length,0);await client.upload([file]);assert.equal(ids[0],ids[1]);assert.equal(client.content('读取附件'),'读取附件\n@file:'+fid);assert.equal(client.content('@file:'+fid),'@file:'+fid);client.remove(fid);assert.equal(client.content(''),'');
});
test('a late upload cannot attach a private file to another session',async()=>{
 const {ComposerResources}=await mod;let release;const client=new ComposerResources({fetcher:async(path,opts)=>opts.method?new Promise(resolve=>{release=()=>resolve(response({id:fid,name:'old.txt',bytes:1}))}):fixture(path)});await client.open('old');const upload=client.upload([new File(['x'],'old.txt')]);while(!release)await new Promise(resolve=>setImmediate(resolve));await client.open('new');release();await upload;assert.deepEqual(client.state.files,[]);assert.equal(client.session,'new');
});
test('definitively rejected uploads do not exhaust pending slots but unknown results keep their ID',async()=>{
 const {ComposerResources}=await mod;let status=415;const client=new ComposerResources({fetcher:async(path,options)=>options.method?{ok:false,status}:fixture(path)});await client.open('mine');
 for(let i=0;i<20;i++)await assert.rejects(client.upload([new File(['broken'],'bad'+i+'.pdf')]),/格式、编码或内容无效/);
 assert.equal(client.pending.size,0);status=503;await assert.rejects(client.upload([new File(['unknown'],'uncertain.pdf')]));assert.equal(client.pending.size,1);
});
test('assigned pending review remains actionable; completed reviews do not become actionable',async()=>{
 const workflow=await import('data:text/javascript;base64,'+Buffer.from(readFrontendFile('src','utils','qualityWorkflow.js')).toString('base64'));
 assert.equal(workflow.canReviewTask({status:'COMPLETED',reviewStatus:'PENDING',flowStatus:'REVIEWING'}),true);assert.equal(workflow.canReviewTask({status:'COMPLETED',reviewStatus:'REVIEWED',flowStatus:'CONFIRMED'}),false);
});
test('draft text and server file references survive refresh, are reauthorized and remain account/session scoped',async()=>{
 const {ComposerResources}=await mod;const saved=new Map(),storage={setItem:(k,v)=>saved.set(k,v),getItem:k=>saved.get(k),removeItem:k=>saved.delete(k)};let account='alice',revoked=false;const file=new File(['test'],'mine.md');
 const fetcher=async(path,options)=>path==='/api/auth/check'?response({code:200,data:{username:account,userId:account==='alice'?1:2}}):path.endsWith('/workbench')?response({files:revoked?[]:[{id:fid,name:'mine.md',bytes:4}]}):options.method?response({id:fid,name:'mine.md',bytes:4}):fixture(path);
 const first=new ComposerResources({fetcher,storage});await first.open('same');first.draft('保留草稿');await first.upload([file]);first.close();
 let text;const restored=new ComposerResources({fetcher,storage,onDraft:value=>{text=value}});await restored.open('same');assert.equal(text,'保留草稿');assert.equal(restored.state.files[0].id,fid);
 await restored.open('different');assert.equal(text,'');assert.equal(restored.state.files.length,0);account='bob';await restored.open('same');assert.equal(text,'');assert.equal(restored.state.files.length,0);
 account='alice';revoked=true;await restored.open('same');assert.equal(text,'保留草稿');assert.deepEqual(restored.state.files,[]);assert.match(restored.state.error,/权限已变化/);
 restored.clear();assert.equal(saved.size,0);
 restored.draft('x'.repeat(20001));assert.equal(restored.text.length,20001);assert.match(restored.state.draftWarning,/仅当前页面/);assert.equal(saved.size,0);restored.draft('short');assert.equal(restored.state.draftWarning,'');assert.equal(saved.size,1);
});
test('unknown upload keeps request identity across reload and is only retried when user reselects the file',async()=>{
 const {ComposerResources}=await mod;const saved=new Map(),storage={setItem:(k,v)=>saved.set(k,v),getItem:k=>saved.get(k),removeItem:k=>saved.delete(k)};const posts=[];let fail=true;
 const fetcher=async(path,options)=>{if(path==='/api/auth/check')return response({code:200,data:{username:'alice',userId:1}});if(options.method){posts.push(options.body.get('requestId'));if(fail)throw Error('network');return response({id:fid,name:'private.md',bytes:4})}return fixture(path)};
 const first=new ComposerResources({fetcher,storage});await first.open('same');const file=new File(['test'],'private.md');await assert.rejects(first.upload([file]));first.close();
 const next=new ComposerResources({fetcher,storage});await next.open('same');assert.equal(posts.length,1);fail=false;await next.upload([file]);assert.equal(posts[0],posts[1]);assert.equal(next.state.files[0].id,fid);
});

test('workbench and model selection have independent capability states',async()=>{
 const {ComposerResources}=await mod;
 for(const enabled of [true,false]){
  const client=new ComposerResources({fetcher:async path=>path.endsWith('capabilities')?response({code:404}):!enabled&&path.endsWith('model-selection')?response({enabled:false}):fixture(path)});
  await client.open('mine');
  assert.equal(client.state.ready,enabled);assert.equal(client.state.modelDisabled,!enabled);assert.equal(client.state.filesEnabled,false);assert.equal(client.state.modelError,false);
 }
});
test('a pending attachment capability cannot block the model picker',async()=>{
 const {ComposerResources}=await mod;let finish;
 const client=new ComposerResources({fetcher:async path=>path.endsWith('capabilities')?new Promise(resolve=>{finish=resolve}):fixture(path)});
 const opened=client.open('mine');await new Promise(resolve=>setImmediate(resolve));
 assert.equal(client.state.ready,true);finish(response({files:false,enabled:false}));await opened;
});

test('approval mode is a versioned server preference for the current conversation',async()=>{
 const {ComposerResources,APPROVAL_MODES}=await mod;
 assert.deepEqual(APPROVAL_MODES.map(option=>[option.value,option.label]),[
  ['MANUAL','请求人工审查'],['DEFAULT','默认'],['AUTO','自动'],['FAST','极速模式']
 ]);
 const confirmed=new Map();
 let posted;
 const client=new ComposerResources({fetcher:async(path,options)=>{
  if(!path.endsWith('/approval-mode'))return fixture(path);
  if(options.method){
   posted={path,headers:options.headers,body:JSON.parse(options.body)};
   confirmed.set(path,{mode:posted.body.mode,revision:posted.body.revision+1});
  }
  return response(confirmed.get(path)||{mode:'DEFAULT',revision:0});
 }});
 await client.open('mine');
 assert.equal(client.state.approvalMode.ready,true);
 assert.equal(client.state.approvalMode.mode,'DEFAULT');
 await client.selectApprovalMode('MANUAL');
 assert.equal(posted.path,'/api/agent/conversations/mine/approval-mode');
 assert.equal(posted.headers['X-Agent-Action'],'workbench');
 assert.equal(posted.body.mode,'MANUAL');
 assert.equal(posted.body.revision,0);
 assert.match(posted.body.requestId,/^[a-f0-9-]{36}$/);
 await client.open('another');
 assert.equal(client.state.approvalMode.mode,'DEFAULT');
 await client.open('mine');
 assert.equal(client.state.approvalMode.mode,'MANUAL');
 assert.equal(client.state.approvalMode.revision,1);
});

test('approval conflicts re-read the server choice and preserve the draft without reposting',async()=>{
 const {ComposerResources}=await mod;
 let reads=0,writes=0;
 const client=new ComposerResources({fetcher:async(path,options)=>{
  if(!path.endsWith('/approval-mode'))return fixture(path);
  if(options.method){writes++;return response({message:'当前有活动任务，暂不能更改审批模式'},409)}
  return response(++reads===1?{mode:'DEFAULT',revision:0}:{mode:'AUTO',revision:1});
 }});
 await client.open('mine');
 client.draft('准备查询的内容');
 await assert.rejects(client.selectApprovalMode('FAST'),/当前有活动任务/);
 assert.equal(reads,2);
 assert.equal(writes,1);
 assert.equal(client.state.approvalMode.mode,'AUTO');
 assert.equal(client.state.approvalMode.unverified,false);
 assert.match(client.state.approvalMode.notice,/当前有活动任务/);
 assert.equal(client.text,'准备查询的内容');
});

test('an uncertain approval update requires readback and late results stay in the old conversation',async()=>{
 const {ComposerResources}=await mod;
 let release,writes=0;
 const client=new ComposerResources({fetcher:async(path,options)=>{
  if(!path.endsWith('/approval-mode'))return fixture(path);
  if(options.method){
   if(++writes===1)throw Error('request receipt lost');
   return new Promise(resolve=>{release=resolve});
  }
  return response({mode:'DEFAULT',revision:0});
 }});
 await client.open('old');
 await assert.rejects(client.selectApprovalMode('FAST'));
 assert.equal(client.state.approvalMode.unverified,true);
 await assert.rejects(client.selectApprovalMode('MANUAL'),/先核对/);
 assert.equal(writes,1);
 await client.refreshApprovalMode();
 assert.equal(client.state.approvalMode.unverified,false);
 const pending=client.selectApprovalMode('MANUAL');
 assert.equal(client.state.busy,true);
 assert.equal(client.state.approvalMode.mode,'DEFAULT');
 await client.open('new');
 release(response({mode:'MANUAL',revision:1}));
 await pending;
 assert.equal(client.state.approvalMode.mode,'DEFAULT');
 assert.equal(client.state.approvalMode.revision,0);
 assert.equal(client.state.busy,false);
});
