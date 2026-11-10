const assert = require('node:assert/strict')
const test = require('node:test')
const { readFrontendFile, readProjectFile } = require('./helpers/project-source.cjs')
const moduleUrl = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64')

test('tests\\auth-response-guard-contract.test.cjs', async () => {
  const source = readFrontendFile('src', 'stores', 'user.js')

  assert.match(source, /error\.response\?\.status === 401/)
  assert.doesNotMatch(source, /\[401,\s*403\]\.includes/)

  // Capture the callback registered by the whole actual store; its closing `})`
  // and checkout line endings do not define the security contract.
  const callbacks = [], networkCalls = [], key = '__securityShellAuthResponseGuard'
  globalThis[key] = {
    interceptors: { response: { use: (fulfilled, rejected) => callbacks.push({ fulfilled, rejected }) } },
    get: (...args) => { networkCalls.push(['get', ...args]); throw Error('Response guard must not start a request') },
    post: (...args) => { networkCalls.push(['post', ...args]); return Promise.resolve({ data: { code: 200 } }) }
  }
  const contextUrl = moduleUrl(readFrontendFile('src', 'utils', 'accountContext.js'))
  const storeSource = source
    .replace("import { defineStore } from 'pinia'", 'const defineStore=(_id,setup)=>setup')
    .replace("import { ref } from 'vue'", 'const ref=value=>({value})')
    .replace("import request from '../api/request'", 'const request=globalThis[' + JSON.stringify(key) + ']')
    .replace("'../utils/accountContext'", JSON.stringify(contextUrl))
    .replace("'../utils/loginError'", JSON.stringify(moduleUrl(readFrontendFile('src', 'utils', 'loginError.js'))))
    .replace("'../utils/accountPreferences'", JSON.stringify(moduleUrl(readFrontendFile('src', 'utils', 'accountPreferences.js'))))
  let session
  try {
    const context = await import(contextUrl)
    session = context.accountSession
    const { useUserStore } = await import(moduleUrl(storeSource))
    const store = useUserStore()
    assert.equal(callbacks.length, 1)
    const interceptor = callbacks[0]
    const response = { data: { code: 200 } }
    assert.equal(interceptor.fulfilled(response), response)
    const owner = { authenticated: true, userId: '21', username: 'supervisor-a', role: 'SUPERVISOR', accountContext: 'context-a' }
    const failure = (status, config) => Object.assign(Error('response fixture'), { response: { status }, config })
    const rejectOriginal = error => assert.rejects(interceptor.rejected(error), received => received === error)

    session.accept(owner)
    const expired = session.stamp()
    await rejectOriginal(failure(401, { _accountAuth: false, _accountStamp: expired }))
    assert.equal(session.state.authenticated, false)
    assert.equal(session.current(expired), false)
    assert.equal(expired.signal.aborted, true)
    assert.equal(store.username.value, '')
    assert.equal(store.userId.value, null)
    assert.equal(store.hasCheckedAuth.value, true)

    const preserve = async error => {
      const before = session.state, stamp = session.stamp(), checked = store.hasCheckedAuth.value
      await rejectOriginal(error)
      assert.deepEqual(session.state, before)
      assert.equal(session.current(stamp), true)
      assert.equal(store.username.value, before.user.username)
      assert.equal(store.userId.value, before.user.userId)
      assert.equal(store.hasCheckedAuth.value, checked)
    }
    // A late failure cannot clear a new login, even when its public accountContext is reused.
    session.accept(owner)
    await preserve(failure(401, { _accountAuth: false, _accountStamp: expired }))
    const oldAccount = session.stamp()
    session.accept({ ...owner, userId: '22', username: 'supervisor-b', accountContext: 'context-b' })
    let draft = { taskId: 'B', text: 'unsaved B draft', expectedVersion: '0', requestId: 'original-b-command' }
    const originalDraft = JSON.stringify(draft)
    session.onReset(() => { draft = null })
    const current = session.stamp()
    for (const error of [
      failure(401, { _accountAuth: false, _accountStamp: oldAccount }),
      failure(403, { _accountAuth: false, _accountStamp: current }),
      failure(401, { _accountAuth: true, _accountStamp: current }),
      failure(401, {})
    ]) {
      await preserve(error)
      assert.equal(JSON.stringify(draft), originalDraft)
    }
    await rejectOriginal(failure(401, { _accountAuth: false, _accountStamp: current }))
    assert.equal(session.state.authenticated, false)
    assert.equal(session.current(current), false)
    assert.equal(store.username.value, '')
    assert.equal(draft, null)
    assert.deepEqual(networkCalls, [])
  } finally {
    session?.clear()
    delete globalThis[key]
  }

  console.log('auth response guard contract assertions passed')
})

test('tests\\cookie-only-auth-contract.test.cjs', () => {
  const userStore = readFrontendFile('src', 'stores', 'user.js')
  const requestApi = readFrontendFile('src', 'api', 'request.js')
  const chatApi = readFrontendFile('src', 'api', 'chatAssistant.js')
  const router = readFrontendFile('src', 'router', 'index.js')

  assert.doesNotMatch(userStore, /localStorage\.setItem\(['"]token['"]/)
  assert.doesNotMatch(userStore, /localStorage\.getItem\(['"]token['"]/)
  assert.doesNotMatch(userStore, /defaults\.headers\.common\[['"]Authorization['"]\]/)
  assert.match(userStore, /hasCheckedAuth/)

  assert.doesNotMatch(requestApi, /Authorization\s*=/)
  assert.doesNotMatch(requestApi, /localStorage\.getItem\(['"]token['"]/)
  assert.match(requestApi, /withCredentials\s*=\s*true/)

  assert.doesNotMatch(chatApi, /localStorage\.getItem\(['"]token['"]/)
  assert.doesNotMatch(chatApi, /Authorization:\s*`Bearer/)
  assert.match(chatApi, /credentials:\s*['"]include['"]/)

  assert.match(router, /await userStore\.checkAuth\(\)/)
  assert.doesNotMatch(router, /!userStore\.token/)

  console.log('cookie-only auth contract assertions passed')
})

test('tests\\hash-route-anchor-contract.test.cjs', () => {
  const layoutSource = readFrontendFile('src', 'layout', 'index.vue')
  const userManualSource = readFrontendFile('src', 'views', 'UserManual.vue')

  for (const source of [layoutSource, userManualSource]) {
    assert.doesNotMatch(source, /href="#(?!\/)/, 'Hash router pages must not use bare hash anchors')
    assert.doesNotMatch(source, /:href="`#/, 'Hash router pages must not generate bare hash anchors')
  }

  assert.match(userManualSource, /scrollToManualSection/)
  assert.match(layoutSource, /skipToMainContent/)

  console.log('hash route anchor contract assertions passed')
})

{
  test('layout distinguishes supervisor scope from employee-owned and assigned tasks', () => {
    const source = readFrontendFile('src', 'layout', 'index.vue')
    assert.match(source, /userStore\.role==='SUPERVISOR'/)
    assert.match(source, /企业主管/)
    assert.match(source, /本人及分派任务/)
    assert.doesNotMatch(source, /系统管理账号/)
  })

  test('user manual explains current role boundaries and private conversations', () => {
    const source = readFrontendFile('src', 'views', 'UserManual.vue')
    assert.match(source, /员工只能查看本人及分派任务/)
    assert.match(source, /主管/)
    assert.match(source, /不读取其他账号私人会话/)
  })
}
