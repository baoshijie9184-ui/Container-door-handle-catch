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
  const env = { subscriptions: [], calls: [], denied: false,
    user: { isAuthenticated:true, capabilities:{changeHistory:true}, accountContext:'owned-context', accountEpoch:1 },
    vue: { ref:value=>({value}), unref:value=>value&&Object.hasOwn(value,'value')?value.value:value, watch:()=>{} } }
  env.request = { async post(path, resources) {
    env.calls.push({path,resources}); if(env.denied)throw Error('current access denied')
    return { data: resources.map(resource=>({resource,latest:{id:'99',resourceType:resource.resourceType,
      resourceId:resource.resourceId,afterVersion:'8',actor:{displayName:'当前获准显示的操作人'}}})) }
  } }
  env.scope = { channel:()=>({ begin:()=>({signal:new AbortController().signal}),current:()=>true }) }
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
