const test=require('node:test'),assert=require('node:assert/strict');
const {readFrontendFile}=require('./helpers/project-source.cjs');
const mod=import('data:text/javascript;base64,'+Buffer.from(readFrontendFile('src','utils','composerResources.js')).toString('base64'));
const response=(value,status=200)=>({ok:status===200,status,json:async()=>value});
const fid='00000000-0000-0000-0000-000000000001';
const fixture=(path)=>path.endsWith('capabilities')?response({enabled:true,files:true}):path==='/agui/models'?response({models:[{id:'deepseek:demo',model:'demo',configured:true},{id:'missing',model:'missing',configured:false}]}):response({modelId:'',revision:0});
test('model choice is persisted through a versioned server command with stable retry identity',async()=>{
 const {ComposerResources}=await mod;let fail=true;const posts=[];const client=new ComposerResources({fetcher:async(path,opts)=>{if(opts.method){posts.push(JSON.parse(opts.body));if(fail){fail=false;throw Error('network')}return response({modelId:'deepseek:demo',revision:1})}return fixture(path)}});
 await client.open('mine');assert.equal(client.state.models.length,1);await assert.rejects(client.select('deepseek:demo'));assert.equal(client.state.modelId,'');await client.select('deepseek:demo');assert.equal(posts[0].requestId,posts[1].requestId);assert.equal(posts[1].revision,0);assert.equal(client.state.modelId,'deepseek:demo');
});
test('attachment is a private server ID and uncertain upload keeps its request ID',async()=>{
 const {ComposerResources}=await mod;let fail=true;const ids=[];const client=new ComposerResources({fetcher:async(path,opts)=>{if(opts.method){ids.push(opts.body.get('requestId'));assert.equal(opts.headers['X-Agent-Action'],'workbench');if(fail){fail=false;throw Error('network')}return response({id:fid,name:'private.md',bytes:4})}return fixture(path)}});
 await client.open('mine');const file=new File(['test'],'private.md',{type:'text/markdown'});await assert.rejects(client.upload([file]));assert.equal(client.state.files.length,0);await client.upload([file]);assert.equal(ids[0],ids[1]);assert.equal(client.content('读取附件'),'读取附件\n@file:'+fid);assert.equal(client.content('@file:'+fid),'@file:'+fid);client.remove(fid);assert.equal(client.content(''),'');
});
test('a late upload cannot attach a private file to another session',async()=>{
 const {ComposerResources}=await mod;let release;const client=new ComposerResources({fetcher:async(path,opts)=>opts.method?new Promise(resolve=>{release=()=>resolve(response({id:fid,name:'old.txt',bytes:1}))}):fixture(path)});await client.open('old');const upload=client.upload([new File(['x'],'old.txt')]);while(!release)await new Promise(resolve=>setImmediate(resolve));await client.open('new');release();await upload;assert.deepEqual(client.state.files,[]);assert.equal(client.session,'new');
});
test('assigned pending review remains actionable; completed reviews do not become actionable',async()=>{
 const workflow=await import('data:text/javascript;base64,'+Buffer.from(readFrontendFile('src','utils','qualityWorkflow.js')).toString('base64'));
 assert.equal(workflow.canReviewTask({status:'COMPLETED',reviewStatus:'PENDING',flowStatus:'REVIEWING'}),true);assert.equal(workflow.canReviewTask({status:'COMPLETED',reviewStatus:'REVIEWED',flowStatus:'CONFIRMED'}),false);
});
