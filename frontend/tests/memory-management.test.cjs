const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const source=fs.readFileSync(path.join(__dirname,'../src/api/agentMemory.js'),'utf8')
const apiPromise=import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
test('lifecycle changes require the supplied confirmation and cleanup checks only query their original identity',async(t)=>{
 const original=global.fetch,calls=[];t.after(()=>{global.fetch=original});global.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,status:200,json:async()=>({})}};
 const api=await apiPromise,body={requestId:'unique',expectedDigest:'a'.repeat(64),expectedRevision:0,state:'EXCLUDED',expiresAt:null,autoDelete:false,confirmed:true};
 await api.memoryLifecycle();await api.changeMemoryLifecycle('mine/id',body);await api.verifyMemoryCleanup('mine/id');
 assert.equal(calls[0].url,'/api/agent/memories/lifecycle');assert.equal(calls[1].url,'/api/agent/memories/mine%2Fid/lifecycle');assert.deepEqual(JSON.parse(calls[1].options.body),body);
 assert.equal(calls[2].url,'/api/agent/memories/mine%2Fid/cleanup/verify');assert.equal(calls[2].options.headers['X-Agent-Action'],'memory-verify');assert.equal(calls[2].options.body,undefined);
 for(const call of calls){assert.equal(call.options.credentials,'include');assert.equal(call.options.cache,'no-store')}
});
test('verifying an extraction only queries its existing request identity with private credentials',async(t)=>{
 const original=global.fetch,calls=[];t.after(()=>{global.fetch=original});global.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,status:200,json:async()=>({status:'RUNNING'})}};
 const api=await apiPromise;assert.equal((await api.verifyMemoryExtraction('a'.repeat(64))).status,'RUNNING');
 assert.equal(calls[0].url,'/api/agent/memories/operations/'+'a'.repeat(64)+'/verify');assert.equal(calls[0].options.headers['X-Agent-Action'],'memory-verify');assert.equal(calls[0].options.body,undefined);assert.equal(calls[0].options.credentials,'include');assert.equal(calls[0].options.cache,'no-store');
});

test('memory reads support subsequent pages and carry private session/cache settings',async(t)=>{
  const calls=[],original=global.fetch
  t.after(()=>{global.fetch=original})
  global.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,status:200,json:async()=>({items:[],hasMore:false})}}
  const api=await apiPromise;await api.memoryList(50,100);await api.personalMemory('mine/id')
  assert.equal(calls[0].url,'/api/agent/memories?limit=50&offset=100')
  assert.equal(calls[1].url,'/api/agent/memories/mine%2Fid')
  for(const call of calls){assert.equal(call.options.cache,'no-store');assert.equal(call.options.credentials,'include')}
})

test('confirmed edits send the version and retain HTTP conflict information for the editor',async(t)=>{
  const calls=[],original=global.fetch
  t.after(()=>{global.fetch=original})
  global.fetch=async(url,options)=>{calls.push({url,options});return {ok:false,status:409,json:async()=>({message:'记忆已变化'})}}
  const api=await apiPromise,payload={requestId:'unique-request',expectedDigest:'a'.repeat(64),memory:'修改后正文',confirmed:true}
  await assert.rejects(api.updatePersonalMemory('mine',payload),error=>error.status===409&&error.message==='记忆已变化')
  assert.equal(calls[0].url,'/api/agent/memories/mine/update');assert.equal(calls[0].options.method,'POST')
  assert.deepEqual(JSON.parse(calls[0].options.body),payload)
})

test('semantic review starts explicitly and decisions carry confirmation and revision',async(t)=>{
 const original=global.fetch,calls=[];t.after(()=>{global.fetch=original});global.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,status:202,json:async()=>({status:'RUNNING'})}};
 const api=await apiPromise;await api.memoryReviews();await api.startMemoryReview('mine/id',{requestId:'read',expectedDigest:'a'.repeat(64),expectedRevision:0});await api.memoryReview('read');await api.resolveMemoryReview('read',{requestId:'decision',expectedRevision:1,candidateId:'candidate',choice:'KEEP_SOURCE',confirmed:true});
 assert.equal(calls[0].url,'/api/agent/memories/reviews');assert.equal(calls[1].url,'/api/agent/memories/mine%2Fid/reviews');assert.equal(calls[2].options.body,undefined);assert.equal(JSON.parse(calls[3].options.body).confirmed,true);assert.equal(JSON.parse(calls[3].options.body).expectedRevision,1);
 for(const call of calls){assert.equal(call.options.credentials,'include');assert.equal(call.options.cache,'no-store')}
});
