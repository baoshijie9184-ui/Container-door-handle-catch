// Run against the review site with its two test accounts in the process environment.
const assert = require('node:assert/strict')
const { chromium } = require('playwright')

const base = process.env.REVIEW_BASE_URL || 'http://127.0.0.1:8081'
const headings = { SUPERVISOR: '企业质量工作台', INSPECTOR: '我的检测工作台' }
const homeScript = /\/assets\/Home-[\w-]+\.js$/

async function openLogin(context, role) {
  const page = await context.newPage()
  await page.goto(base + '/#/login')
  await page.locator('input[name=username]').fill(process.env[role + '_USERNAME'])
  await page.locator('input[name=password]').fill(process.env[role + '_PASSWORD'])
  return page
}

async function submit(page) {
  await page.getByRole('button', { name: '登录系统' }).click()
}

async function checkHome(page, role) {
  await page.getByRole('heading', { name: headings[role], exact: true }).waitFor()
  const actual = await page.evaluate(async () => {
    const response = await fetch('/api/auth/check', { cache: 'no-store' })
    const result = await response.json()
    return result.data?.authenticated && result.data.role
  })
  assert.equal(actual, role)
}

function countRequests(page) {
  const counts = { documents: 0, logins: 0 }
  page.on('request', request => {
    if (request.resourceType() === 'document' && request.frame() === page.mainFrame()) counts.documents++
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/auth/login') counts.logins++
  })
  return counts
}

async function verifySharedDirectories(page) {
  for (const [label, heading] of [['人员目录', '人员管理'], ['设备目录', '设备管理'], ['检测模型', '检测模型管理']]) {
    const directories = page.getByRole('navigation', { name: '公共资料' })
    await directories.getByRole('link', { name: label }).click()
    await page.getByRole('heading', { name: heading, exact: true }).first().waitFor()
    await page.locator('main .el-table__body tr').first().waitFor()
    await page.goto(base + '/#/home')
  }
}

async function readDashboard(page) {
  const card = page.locator('section[aria-labelledby="history-overview-title"]')
  await card.getByText('查看年度登记明细').click()
  const annual = await card.locator('tbody tr').allTextContents()
  const counts = await card.locator('.history-metrics dd').allTextContents()
  const snapshot = await page.evaluate(async () => {
    async function read(path) {
      const response = await fetch(path, { cache: 'no-store' })
      const result = await response.json()
      if (!response.ok || result.code !== 200) throw new Error('Dashboard verification request failed')
      return result.data
    }
    const stats = await read('/api/dashboard/stats')
    const tasks = await read('/api/detection/tasks?page=1&size=1')
    return { history: stats.historicalSummary, visibleTasks: tasks.total }
  })
  assert.equal(annual.length, snapshot.history.yearlyTotals.length)
  assert.ok(annual.length > 0)
  assert.equal(counts[0].replace(/[^0-9]/g, ''), String(snapshot.history.imageCount))
  return { annual, counts, ...snapshot }
}

async function exercise(browser) {
  const supervisorContext = await browser.newContext()
  const inspectorContext = await browser.newContext()
  const supervisor = await openLogin(supervisorContext, 'SUPERVISOR')
  const normal = countRequests(supervisor)
  await submit(supervisor)
  await checkHome(supervisor, 'SUPERVISOR')
  assert.deepEqual(normal, { documents: 0, logins: 1 })

  const inspector = await openLogin(inspectorContext, 'INSPECTOR')
  const recovered = countRequests(inspector)
  await inspector.route(homeScript, route => route.fulfill({ status: 404, body: 'Not Found' }), { times: 1 })
  await submit(inspector)
  await checkHome(inspector, 'INSPECTOR')
  assert.deepEqual(recovered, { documents: 1, logins: 1 })
  await checkHome(supervisor, 'SUPERVISOR')
  const { visibleTasks: enterprise, ...supervisorHistory } = await readDashboard(supervisor)
  const { visibleTasks: personal, ...inspectorHistory } = await readDashboard(inspector)
  assert.deepEqual(inspectorHistory, supervisorHistory)
  assert.ok(Number.isInteger(personal) && personal >= 0 && personal <= enterprise)
  console.log('PASS matching shared yearly totals; visible tasks supervisor=%d inspector=%d', enterprise, personal)
  await verifySharedDirectories(inspector)
  console.log('PASS separate role sessions, inspector directories, single-GET login recovery')

  const switched = await openLogin(supervisorContext, 'INSPECTOR')
  await submit(switched)
  await checkHome(switched, 'INSPECTOR')
  await supervisor.bringToFront()
  await checkHome(supervisor, 'INSPECTOR')
  console.log('PASS ordinary tabs follow the selected account')

  const blockedContext = await browser.newContext()
  const blocked = await openLogin(blockedContext, 'INSPECTOR')
  const ongoing = countRequests(blocked)
  await blocked.route(homeScript, route => route.fulfill({ status: 404, body: 'Not Found' }))
  await submit(blocked)
  await blocked.waitForURL('**/#/home')
  const reload = blocked.getByRole('button', { name: '重新加载页面', exact: true })
  await reload.waitFor()
  await blocked.waitForLoadState('domcontentloaded')
  assert.deepEqual(ongoing, { documents: 1, logins: 1 })
  await blocked.unroute(homeScript)
  await reload.click()
  await checkHome(blocked, 'INSPECTOR')
  assert.deepEqual(ongoing, { documents: 2, logins: 1 })
  console.log('PASS persistent failure stops, explicit retry resumes without signing in again')
}

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE || undefined })
  try { await exercise(browser) } finally { await browser.close() }
}
main().catch(error => { console.error(error.name + ': ' + error.message.split('\n')[0]); process.exitCode = 1 })
