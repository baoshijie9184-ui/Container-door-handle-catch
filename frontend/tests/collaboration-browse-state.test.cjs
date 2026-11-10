const test = require('node:test'), assert = require('node:assert/strict')
const { readFrontendFile } = require('./helpers/project-source.cjs')
const source = readFrontendFile('src', 'utils', 'preserveBrowseState.js')
const subject = import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))

function documentFixture() {
  const listeners = new Map()
  const root = { isConnected: true, scrollTop: 310, scrollLeft: 0 }
  const table = { isConnected: true, scrollTop: 180, scrollLeft: 75 }
  const body = { isConnected: true }
  const doc = { body, documentElement: root, scrollingElement: root,
    querySelectorAll: () => [table], addEventListener: (type, listener) => listeners.set(type, listener),
    removeEventListener: (type, listener) => { assert.equal(listeners.get(type), listener); listeners.delete(type) } }
  const input = { isConnected: true, selectionStart: 2, selectionEnd: 6, selectionDirection: 'forward',
    focus: options => { assert.equal(options.preventScroll, true); doc.activeElement = input },
    setSelectionRange: (start, end, direction) => { input.selectionStart = start; input.selectionEnd = end; input.selectionDirection = direction } }
  doc.activeElement = input
  return { doc, input, root, table, listeners }
}

test('automatic read restores window, table position and text selection after the rendered patch', async () => {
  const { preserveBrowseState } = await subject
  const value = documentFixture(); let rendered = false
  const result = await preserveBrowseState(async () => 'read-result', { documentRef: value.doc,
    afterRender: async () => { rendered = true; value.root.scrollTop = 0; value.table.scrollLeft = 0;
      value.table.scrollTop = 0; value.doc.activeElement = value.doc.body; value.input.selectionStart = 0 } })
  assert.equal(result, 'read-result'); assert.equal(rendered, true)
  assert.deepEqual([value.root.scrollTop, value.table.scrollTop, value.table.scrollLeft], [310, 180, 75])
  assert.equal(value.doc.activeElement, value.input)
  assert.deepEqual([value.input.selectionStart, value.input.selectionEnd, value.input.selectionDirection], [2, 6, 'forward'])
  assert.equal(value.listeners.size, 0)
})

test('new pointer, keyboard, touch, wheel or typing intent during the read is never rolled back', async () => {
  const { preserveBrowseState } = await subject
  for (const type of ['pointerdown', 'keydown', 'touchmove', 'wheel', 'input']) {
    const value = documentFixture()
    await preserveBrowseState(async () => { value.listeners.get(type)(); value.root.scrollTop = 900;
      value.table.scrollLeft = 100; value.input.selectionStart = 4 }, { documentRef: value.doc })
    assert.deepEqual([value.root.scrollTop, value.table.scrollLeft, value.input.selectionStart], [900, 100, 4], type)
    assert.equal(value.listeners.size, 0)
  }
})

test('account or component invalidation prevents an old read from moving the new page', async () => {
  const { preserveBrowseState } = await subject
  const value = documentFixture(); let current = true
  await preserveBrowseState(async () => { current = false; value.root.scrollTop = 0; value.doc.activeElement = value.doc.body },
    { documentRef: value.doc, isCurrent: () => current })
  assert.equal(value.root.scrollTop, 0); assert.equal(value.doc.activeElement, value.doc.body)
  assert.equal(value.listeners.size, 0)
})

test('removed rows and scroll containers are not focused or modified after a read', async () => {
  const { preserveBrowseState } = await subject
  const value = documentFixture()
  value.input.focus = () => { throw new Error('removed input must not be focused') }
  await preserveBrowseState(async () => { value.input.isConnected = false; value.table.isConnected = false;
    value.doc.activeElement = value.doc.body; value.table.scrollTop = 0 }, { documentRef: value.doc })
  assert.equal(value.table.scrollTop, 0); assert.equal(value.doc.activeElement, value.doc.body)
  assert.equal(value.listeners.size, 0)
})

test('a different live focused control is retained instead of reopening the former input', async () => {
  const { preserveBrowseState } = await subject
  const value = documentFixture(), other = { isConnected: true }
  await preserveBrowseState(async () => { value.doc.activeElement = other }, { documentRef: value.doc })
  assert.equal(value.doc.activeElement, other)
})

test('a failed read keeps the failure and always releases its temporary interaction listeners', async () => {
  const { preserveBrowseState } = await subject
  const value = documentFixture(), failure = new Error('owned read failed')
  await assert.rejects(preserveBrowseState(async () => { throw failure }, { documentRef: value.doc }), error => error === failure)
  assert.equal(value.listeners.size, 0)
})

test('source or server rendering without a document preserves the original read result', async () => {
  const { preserveBrowseState } = await subject
  let calls = 0
  assert.equal(await preserveBrowseState(async () => { calls++; return false }, { documentRef: null }), false)
  assert.equal(calls, 1)
})

test('the number of observed scroll containers stays bounded for large business lists', async () => {
  const { preserveBrowseState } = await subject
  const value = documentFixture(), nodes = Array.from({ length: 200 }, () => ({ isConnected: true, scrollTop: 4, scrollLeft: 2 }))
  value.doc.querySelectorAll = () => nodes
  await preserveBrowseState(async () => { for (const node of nodes) node.scrollTop = 0 }, { documentRef: value.doc })
  assert.equal(nodes.filter(node => node.scrollTop === 4).length, 64)
  assert.equal(nodes[64].scrollTop, 0)
})

async function latestFixture(key) {
  const env = { subscriptions: [], calls: [], denied: false, current:true,
    user: { isAuthenticated:true, capabilities:{changeHistory:true}, accountContext:'owned-context', accountEpoch:1 },
    vue: { ref:value=>({value}), unref:value=>value&&Object.hasOwn(value,'value')?value.value:value, watch:()=>{} } }
  env.request = { async post(path, resources) {
    env.calls.push({path,resources}); if(env.denied)throw Error('current access denied')
    if(env.reply)return {data:await env.reply(resources)}
    return { data: resources.map(resource=>({resource,latest:{id:'99',resourceType:resource.resourceType,
      resourceId:resource.resourceId,afterVersion:'8',actor:{displayName:'当前获准显示的操作人'}}})) }
  } }
  env.scope = { channel:()=>{let sequence=0;return {begin:()=>({sequence:++sequence,signal:new AbortController().signal}),current:token=>env.current&&token.sequence===sequence}} }
  globalThis[key]=env
  const code=readFrontendFile('src','composables','useLatestChanges.js')
    .replace("import { ref, unref, watch } from 'vue'",`const {ref,unref,watch}=globalThis[${JSON.stringify(key)}].vue`)
    .replace("import { captureAccountRequest } from '../api/request'",`const captureAccountRequest=()=>globalThis[${JSON.stringify(key)}].request`)
    .replace("import { useUserStore } from '../stores/user'",`const useUserStore=()=>globalThis[${JSON.stringify(key)}].user`)
    .replace("import { useAccountOperationScope } from './useAccountOperationScope'",`const useAccountOperationScope=()=>globalThis[${JSON.stringify(key)}].scope`)
    .replace("import { useResourceChanges } from './useResourceChanges'",`const useResourceChanges=options=>globalThis[${JSON.stringify(key)}].subscriptions.push(options)`)
  return {env,module:await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))}
}

test('a metadata update while another record is edited preserves the business row, draft and original command', async () => {
  const key='__collaborationLatestEditingFixture'
  try {
    const {env,module}=await latestFixture(key)
    const records={value:[{taskId:'owned-task',version:'7'}]}, type={value:'DETECTION_TASK'}, domain={value:'DETECTION'}
    const draft={text:'unsubmitted draft',expectedVersion:'7',requestId:'original-command'}
    const before=JSON.stringify({records,draft})
    const result=module.useLatestChanges(records,type,domain,'taskId')
    assert.equal(env.subscriptions.length,1); assert.equal(env.subscriptions[0].resourceType,type)
    await env.subscriptions[0].refresh()
    assert.equal(result.latest.value['owned-task'].actor.displayName,'当前获准显示的操作人')
    assert.equal(result.latest.value['owned-task'].afterVersion,'8')
    assert.deepEqual(env.calls[0],{path:'/api/operations/audit/changes/latest',resources:[{domain:'DETECTION',resourceType:'DETECTION_TASK',resourceId:'owned-task'}]})
    assert.equal(JSON.stringify({records,draft}),before)
  } finally { delete globalThis[key] }
})

test('a denied metadata reread removes the old operation identity instead of keeping it as current', async () => {
  const key='__collaborationLatestDeniedFixture'
  try {
    const {env,module}=await latestFixture(key)
    const result=module.useLatestChanges({value:[{id:'41'}]},'DEVICE','DEVICE')
    await result.refresh(); assert.equal(result.latest.value['41'].actor.displayName,'当前获准显示的操作人')
    env.denied=true; await env.subscriptions[0].refresh()
    assert.deepEqual(result.latest.value,{})
  } finally { delete globalThis[key] }
})

test('defect evidence refresh and paging retain the applied query until an explicit new search', async () => {
  const key='__collaborationGalleryQueryFixture', calls=[]
  const env={ref:value=>({value}),reactive:value=>value,computed:read=>({get value(){return read()}}),onBeforeUnmount:()=>{},
    ElMessage:{error:()=>{}},knownCount:value=>Number.isSafeInteger(value)&&value>=0?value:null,
    async fetchDefectGallery(params){calls.push({...params});return {data:{code:200,data:{records:[],total:0}}}}}
  globalThis[key]=env
  try {
    const code=readFrontendFile('src','composables','useDefectGallery.js')
      .replace("import { computed, reactive, ref, onBeforeUnmount } from 'vue'",`const {computed,reactive,ref,onBeforeUnmount}=globalThis[${JSON.stringify(key)}]`)
      .replace("import { ElMessage } from 'element-plus'",`const {ElMessage}=globalThis[${JSON.stringify(key)}]`)
      .replace("import { fetchDefectGallery } from '../api/detection'",`const {fetchDefectGallery}=globalThis[${JSON.stringify(key)}]`)
      .replace("import { knownCount } from '../utils/countPresentation'",`const {knownCount}=globalThis[${JSON.stringify(key)}]`)
    const {useDefectGallery}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
    const state=useDefectGallery(); state.defectFilters.deviceName='已执行设备'
    await state.searchDefectGallery()
    state.defectFilters.deviceName='尚未查询设备'
    await state.loadDefectGallery(2); await state.loadDefectGallery()
    assert.deepEqual(calls.map(row=>[row.deviceName,row.page]),[['已执行设备',1],['已执行设备',2],['已执行设备',2]])
    await state.searchDefectGallery()
    assert.deepEqual([calls[3].deviceName,calls[3].page],['尚未查询设备',1])
  } finally { delete globalThis[key] }
})

test('an update notice names an operator only when authorized history is newer than the open editor', async () => {
  const code=readFrontendFile('src','utils','changeHistory.js')
  const {newerResourceChange}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
  const item={id:'71',afterVersion:'9007199254740994',actor:{displayName:'已核对操作者'}}
  assert.equal(newerResourceChange(item,'9007199254740993'),item)
  assert.equal(newerResourceChange(item,item.afterVersion),null)
  assert.equal(newerResourceChange(item,'9007199254740995'),null)
  for(const version of [undefined,null,'01',-1,Number.NaN,9007199254740992,'9223372036854775808'])assert.equal(newerResourceChange(item,version),null)
  assert.equal(newerResourceChange({...item,afterVersion:null},'0'),null)
})

test('only missing keys from the successfully checked first hundred resources reduce access', async () => {
  const key='__collaborationMissingScopeFixture'
  try {
    const {env,module}=await latestFixture(key), calls=[]
    env.reply=resources=>resources.filter(row=>row.resourceId!=='task-0').map(resource=>({resource,latest:null}))
    const records={value:Array.from({length:101},(_,index)=>({id:'task-'+index}))}
    const value=module.useLatestChanges(records,'DETECTION_TASK','DETECTION','id',{onInaccessible:scope=>calls.push(scope)})
    await value.refresh()
    assert.equal(calls.length,1);assert.equal(calls[0].requestedIds.length,100)
    assert.deepEqual(calls[0].missingIds,['task-0']);assert.equal(calls[0].isCurrent(),true)
    assert.equal(calls[0].requestedIds.includes('task-100'),false)
    assert.equal(value.latest.value['task-1'],null)
  } finally { delete globalThis[key] }
})

test('failed, malformed or account-stale metadata never becomes a resource revocation', async () => {
  for(const damage of ['request-failed','foreign-key','account-changed']){
    const key='__collaborationMissingFailure'+damage
    try {
      const {env,module}=await latestFixture(key), calls=[]
      if(damage==='request-failed')env.denied=true
      else env.reply=()=>{if(damage==='account-changed'){env.current=false;return []}
        return [{resource:{domain:'DETECTION',resourceType:'DETECTION_TASK',resourceId:'not-requested'},latest:null}]}
      const value=module.useLatestChanges({value:[{id:'owned-task'}]},'DETECTION_TASK','DETECTION','id',{onInaccessible:scope=>calls.push(scope)})
      await value.refresh();assert.deepEqual(calls,[],damage)
    } finally { delete globalThis[key] }
  }
})

test('a late missing-key response cannot override a newer successful metadata read', async () => {
  const key='__collaborationMissingReadEpoch'
  try {
    const {env,module}=await latestFixture(key), calls=[];let release
    env.reply=()=>new Promise(resolve=>{release=resolve})
    const value=module.useLatestChanges({value:[{id:'owned-task'}]},'DETECTION_TASK','DETECTION','id',{onInaccessible:scope=>calls.push(scope)})
    const old=value.refresh();env.reply=rows=>rows.map(resource=>({resource,latest:null}))
    await value.refresh();release([]);await old
    assert.deepEqual(calls,[]);assert.deepEqual(value.latest.value,{'owned-task':null})
  } finally { delete globalThis[key] }
})

test('resource shrink clears exactly A rows and owned cache while B draft, zero revision and unrequested local entries survive', async () => {
  const cacheCode=readFrontendFile('src','utils','accountTaskCache.js')
  const {createAccountTaskCache}=await import('data:text/javascript;base64,'+Buffer.from(cacheCode).toString('base64'))
  const data=new Map(),storage={getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value),removeItem:key=>data.delete(key)}
  const accountSession={state:{authenticated:true,accountContext:'owner-a'},stamp:()=>({accountContext:'owner-a',epoch:1}),current:stamp=>stamp?.accountContext==='owner-a'&&stamp.epoch===1}
  const cache=createAccountTaskCache({session:accountSession,storage:()=>storage}),stamp=accountSession.stamp()
  const rows=[{taskId:'A',version:'0'},{taskId:'B',version:'0',stage:'queued'},{taskId:'local-pending',version:null}]
  cache.writeTasks(rows,stamp);cache.writeFile('A',{name:'A-only'},stamp);cache.writeFile('B',{name:'B-unchanged'},stamp)
  data.set('doorhandle:other-owner:task_files_A','other-account-data')
  const taskList={value:rows.map(row=>({...row,...(row.taskId==='B'?{stage:'detecting'}:{})}))},selectedTaskId={value:'B'},storeCode=readFrontendFile('src','stores','taskStore.js')
  const start=storeCode.indexOf('  const forgetTaskAccess = '),end=storeCode.indexOf('  const normalizeStage = ',start)
  assert.ok(start>0&&end>start)
  let saved=0
  const forgetTaskAccess=new Function('env',`let saveTimer=null,pendingSave=true;const {accountSession,cache,taskList,selectedTaskId,saveTaskList}=env;${storeCode.slice(start,end)};return forgetTaskAccess`)(
    {accountSession,cache,taskList,selectedTaskId,saveTaskList:owner=>{saved++;cache.writeTasks(taskList.value,owner)}})
  const lists=Array.from({length:4},()=>({value:[...rows]})),draft={taskId:'B',text:'未提交内容',expectedVersion:'0',requestId:'original-b-command'},before=JSON.stringify(draft)
  let invalidated=0
  const env={accountSession,refreshingTasks:{value:true},pollingStore:{invalidateTaskReads:()=>invalidated++},taskStore:{forgetTaskAccess}}
  for(const [index,name] of ['forgetHistoryTasks','forgetQualityTasks','forgetDefectTasks','forgetTraceTasks'].entries())env[name]=ids=>{lists[index].value=lists[index].value.filter(row=>!ids.includes(row.taskId))}
  const page=readFrontendFile('src','views','ImageDetection.vue'),pageStart=page.indexOf('function discardInaccessibleTasks('),pageEnd=page.indexOf('\nconst { latest:taskChanges }',pageStart)
  assert.ok(pageStart>0&&pageEnd>pageStart)
  const discard=new Function('env',`const {accountSession,refreshingTasks,pollingStore,taskStore,forgetHistoryTasks,forgetQualityTasks,forgetDefectTasks,forgetTraceTasks}=env;let taskReadVersion=1;${page.slice(pageStart,pageEnd)};return discardInaccessibleTasks`)(env)
  discard({requestedIds:['A','B'],missingIds:['A','not-requested'],isCurrent:()=>true})
  assert.equal(invalidated,1);assert.equal(JSON.stringify(draft),before);assert.equal(selectedTaskId.value,'B')
  for(const list of [...lists,taskList])assert.deepEqual(list.value.map(row=>row.taskId),['B','local-pending'])
  assert.deepEqual(cache.readTasks().map(row=>row.taskId),['B','local-pending']);assert.equal(cache.readFile('A'),null)
  assert.deepEqual(cache.readFile('B'),{name:'B-unchanged'});assert.equal(data.get('doorhandle:other-owner:task_files_A'),'other-account-data')
  assert.equal(saved,1);assert.equal(cache.readTasks().find(row=>row.taskId==='B').stage,'detecting')
  discard({requestedIds:['B'],missingIds:['B'],isCurrent:()=>false});assert.deepEqual(taskList.value.map(row=>row.taskId),['B','local-pending'])
  const identity=readFrontendFile('src','utils','requestIdentity.js'),identityUrl='data:text/javascript;base64,'+Buffer.from(identity).toString('base64')
  const versionCode=readFrontendFile('src','utils','mutationVersion.js').replace("'./requestIdentity'",JSON.stringify(identityUrl))
  const {resourceVersion}=await import('data:text/javascript;base64,'+Buffer.from(versionCode).toString('base64'))
  const predicate=page.match(/\.filter\((task=>resourceVersion\(task\)!==null)\)/)?.[1]
  assert.ok(predicate);const known=new Function('resourceVersion',`return (${predicate})`)(resourceVersion)
  assert.equal(known({version:0}),true);assert.equal(known({version:'0'}),true)
  for(const row of [{},{version:null},{version:undefined},{version:''}])assert.equal(known(row),false)
  const saveLine=storeCode.split(/\r?\n/).find(line=>line.includes('const saveFileState ='))
  const lateSave=new Function('env',`const {accountSession,cache,taskList}=env;${saveLine};return saveFileState`)({accountSession,cache,taskList})
  assert.equal(lateSave('A',{late:true},stamp),false);assert.equal(cache.readFile('A'),null)
  for(const failure of ['bad-list','list-write-failed']){
    const broken=new Map([['doorhandle:owner-a:taskList',failure==='bad-list'?'{bad-json':JSON.stringify(rows)],['doorhandle:owner-a:task_files_A','A-only'],['doorhandle:owner-a:task_files_B','B-only']])
    const target={getItem:key=>broken.get(key)??null,removeItem:key=>broken.delete(key),setItem:()=>{throw Error('write unavailable')}}
    const damaged=createAccountTaskCache({session:accountSession,storage:()=>target})
    assert.equal(damaged.removeTasks(['A'],stamp),false)
    assert.equal(broken.has('doorhandle:owner-a:task_files_A'),false,failure)
    assert.equal(broken.get('doorhandle:owner-a:task_files_B'),'B-only',failure)
  }
})

test('invalidated polling reads cannot repopulate task rows or results from an old request', async () => {
  for(const kind of ['list','results']){
    const key='__collaborationPollingReadEpoch'+kind;let release
    const env={taskStore:{taskList:[],updateTask:()=>{throw Error('stale write')}},request:{get:()=>new Promise(resolve=>{release=resolve})},
      accountSession:{onReset:()=>{}},ElMessage:{error:()=>{},success:()=>{}}}
    globalThis[key]=env
    try {
      const code=readFrontendFile('src','stores','pollingStore.js')
        .replace("import { defineStore } from 'pinia'",'const defineStore=(_name,setup)=>setup')
        .replace("import request, { captureAccountRequest } from '../api/request'",`const request=globalThis[${JSON.stringify(key)}].request,captureAccountRequest=()=>request`)
        .replace("import { accountSession } from '../utils/accountContext'",`const {accountSession}=globalThis[${JSON.stringify(key)}]`)
        .replace("import { resourceVersion, mutationHeaders, responseResourceVersion } from '../utils/mutationVersion'",'const resourceVersion=()=>null,mutationHeaders=()=>({}),responseResourceVersion=()=>null')
        .replace("import { ElMessage } from 'element-plus'",`const {ElMessage}=globalThis[${JSON.stringify(key)}]`)
        .replace("import { useTaskStore } from './taskStore'",`const useTaskStore=()=>globalThis[${JSON.stringify(key)}].taskStore`)
        .replace("import { knownCount } from '../utils/countPresentation'",'const knownCount=value=>value')
      const {usePollingStore}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64')),store=usePollingStore()
      const pending=kind==='list'?store.fetchTaskList():store.fetchTaskResults(['A'])
      store.invalidateTaskReads();release({data:{code:200,data:kind==='list'?{records:[{taskId:'A',status:'COMPLETED'}],total:1}:{taskId:'A',status:'COMPLETED'}}})
      const result=await pending;assert.equal(kind==='list'?result.ok:result[0].ok,false)
      assert.deepEqual(env.taskStore.taskList,[])
    } finally { delete globalThis[key] }
  }
})

test('forgetting an inaccessible history task invalidates a late page read without clearing legitimate B draft', async () => {
  const key='__collaborationHistoryReadEpoch';let release
  const env={ref:value=>({value}),computed:read=>({get value(){return read()}}),onBeforeUnmount:()=>{},knownCount:value=>value}
  globalThis[key]=env
  try {
    const code=readFrontendFile('src','composables','useDetectionHistory.js')
      .replace("import { computed, ref, onBeforeUnmount } from 'vue'",`const {computed,ref,onBeforeUnmount}=globalThis[${JSON.stringify(key)}]`)
      .replace("import { knownCount } from '../utils/countPresentation'",`const {knownCount}=globalThis[${JSON.stringify(key)}]`)
    const {useDetectionHistory}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
    const state=useDetectionHistory({normalizeStage:()=>''},{fetchTaskList:()=>new Promise(resolve=>{release=resolve})})
    state.historyRecords.value=[{taskId:'A'},{taskId:'B'}]
    const draft={taskId:'B',expectedVersion:'0',requestId:'unchanged',text:'保留内容'},before=JSON.stringify(draft)
    const pending=state.fetchHistoryWithFilters(1,10,{});state.historyRecords.value=[{taskId:'A'},{taskId:'B'}]
    state.forgetTasks(['A']);release({ok:true,records:[{taskId:'A',status:'UPLOADING'}],total:1});await pending
    assert.deepEqual(state.historyRecords.value,[{taskId:'B'}]);assert.equal(state.historyTotal.value,null)
    assert.equal(JSON.stringify(draft),before)
  } finally { delete globalThis[key] }
})

test('a changed route URL prevents the old read from restoring the new route scroll', async () => {
  const {preserveBrowseState}=await subject,value=documentFixture(),listeners=new Map()
  value.doc.defaultView={location:{href:'http://owned/#/devices'},addEventListener:(type,listener)=>listeners.set(type,listener),removeEventListener:type=>listeners.delete(type)}
  await preserveBrowseState(async()=>{value.doc.defaultView.location.href='http://owned/#/employees';value.root.scrollTop=0},{documentRef:value.doc})
  assert.equal(value.root.scrollTop,0);assert.equal(listeners.size,0)
})

test('browser back or a changed navigation entry prevents restoration even when the final URL is the same', async () => {
  const {preserveBrowseState}=await subject
  for(const event of ['popstate','hashchange','currententrychange']){
    const value=documentFixture(),listeners=new Map(),entries=new Map()
    value.doc.defaultView={location:{href:'http://owned/#/devices'},addEventListener:(type,listener)=>listeners.set(type,listener),removeEventListener:type=>listeners.delete(type),
      navigation:{addEventListener:(type,listener)=>entries.set(type,listener),removeEventListener:type=>entries.delete(type)}}
    await preserveBrowseState(async()=>{(event==='currententrychange'?entries:listeners).get(event)();value.root.scrollTop=0},{documentRef:value.doc})
    assert.equal(value.root.scrollTop,0,event);assert.equal(listeners.size,0);assert.equal(entries.size,0)
  }
})
