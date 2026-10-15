const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const source=fs.readFileSync(path.join(__dirname,'../src/api/agentMemory.js'),'utf8')
const apiPromise=import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)

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
