const test=require('node:test'),assert=require('node:assert/strict')
const {importFrontendModule}=require('./helpers/project-source.cjs')
test('trace references use actual response values, preserve order and exclude missing identifiers',async()=>{
  const {readTraceReferences}=await importFrontendModule('src','utils','traceReferences.js')
  const result=readTraceReferences({code:200,data:{records:[{taskId:'a',workOrderNo:' WO-actual ',batchNo:'B-actual'},{taskId:'b',workOrderNo:'WO-actual',batchNo:null},{taskId:'c',workOrderNo:'',batchNo:'B-next'}]}})
  assert.deepEqual(result,{workOrders:['WO-actual'],batches:['B-actual','B-next']})
  assert.deepEqual(readTraceReferences({code:200,data:{records:[]}}),{workOrders:[],batches:[]})
})
test('malformed, duplicate and failed responses cannot turn into sample trace references',async()=>{
  const {readTraceReferences}=await importFrontendModule('src','utils','traceReferences.js')
  for(const body of [null,{code:403,data:{records:[]}},{code:200,data:{records:[{}]}},{code:200,data:{records:[{taskId:'x'},{taskId:'x'}]}}])assert.throws(()=>readTraceReferences(body))
})
