const assert = require('node:assert/strict')
const test = require('node:test')
const { readFrontendFile, readProjectFile } = require('./helpers/project-source.cjs')

test('tests\\auth-response-guard-contract.test.cjs', () => {
  const source = readFrontendFile('src', 'stores', 'user.js')

  assert.match(source, /error\.response\?\.status === 401/)
  assert.doesNotMatch(source, /\[401,\s*403\]\.includes/)

  const interceptor = source.match(/request\.interceptors\.response\.use\([\s\S]*?return Promise\.reject\(error\)[\s\S]*?\n\s*\)/)?.[0] || ''
  assert.match(interceptor, /clearSession\(\)/)
  assert.doesNotMatch(interceptor, /logout\(\)/)

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
