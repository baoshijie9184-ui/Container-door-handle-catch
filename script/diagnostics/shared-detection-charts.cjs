// Acceptance against a populated review database using two separately authenticated browsers.
const assert = require('node:assert/strict')
const { chromium } = require('playwright')

const base = process.env.REVIEW_BASE_URL || 'http://127.0.0.1:8081'
const counts = values => values.map(value => Number(value.replaceAll(',', '')))

async function table(page, title) {
  const details = page.locator('details.chart-data-details').filter({ has: page.locator('summary', { hasText: title }) })
  const summary = details.locator('summary')
  if (!await details.evaluate(el => el.open)) await summary.click()
  return details.locator('tbody tr').evaluateAll(rows => rows.map(row => [...row.cells].map(cell => cell.innerText)))
}

async function inspect(browser, role) {
  const context = await browser.newContext()
  try {
    const page = await context.newPage()
    await page.goto(base + '/#/login')
    await page.locator('input[name=username]').fill(process.env[role + '_USERNAME'])
    await page.locator('input[name=password]').fill(process.env[role + '_PASSWORD'])
    await page.getByRole('button', { name: '登录系统' }).click()
    await page.waitForURL('**/#/home')
    await page.locator('.model-stat-card').first().waitFor()
    const api = async path => {
      const response = await context.request.get(base + path)
      assert.equal(response.status(), 200, path)
      const { code, data } = await response.json()
      assert.equal(code, 200, path)
      return data
    }
    const shared = {}
    const stats = await api('/api/dashboard/stats')
    const hero = page.getByRole('button', { name: /企业累计完成检测任务/ })
    assert.equal(counts([await hero.locator('.hl-value').innerText()])[0], stats.companyDetectionCount)
    await hero.click()
    assert(await page.getByRole('heading', { name: '检测趋势', exact: true }).evaluate(el => el === document.activeElement))

    for (const [range, label] of [['month', '近 12 个月'], ['week', '近 7 天'], ['year', '全部年份']]) {
      if (range !== 'month') {
        await Promise.all([
          page.waitForResponse(r => r.url().includes('/api/statistics/detection-trend?') && new URL(r.url()).searchParams.get('timeRange') === range),
          page.getByText(label, { exact: true }).click()
        ])
      }
      if (range === 'month') await page.locator('details.chart-data-details').filter({hasText:'查看趋势数据'}).locator('tbody tr').first().waitFor({state:'attached'})
      await page.locator('.chart[aria-busy="false"]').first().waitFor()
      const rows = await table(page, '查看趋势数据')
      const data = await api('/api/statistics/detection-trend?scope=COMPANY&timeRange=' + range)
      assert.deepEqual(rows.map(r => [r[0], ...counts(r.slice(1))]), data.map(r =>
        [r.date, r.total, r.normal, r.bent, r.deformed, r.rusty, r.missing, r.compromised]))
      shared[range] = rows
    }

    const regions = await api('/api/dashboard/region-stats?scope=COMPANY')
    const distribution = await api('/api/statistics/detection-distribution?scope=COMPANY')
    const models = await api('/api/dashboard/model-stats?scope=COMPANY')
    shared.regions = await table(page, '查看城市数据')
    shared.distribution = await table(page, '查看分类目标数')
    assert.deepEqual(shared.regions.map(r => [r[0], ...counts(r.slice(1))]), regions.map(r => [r.region, r.imageCount, r.taskCount]))
    assert.deepEqual(Object.fromEntries(shared.distribution.map(([k,v]) => [k,counts([v])[0]])), Object.fromEntries(distribution.map(r => [r.result,r.count])))
    shared.models = await page.locator('.model-stat-card').allInnerTexts()
    assert.equal(shared.models.length, models.length)
    assert(shared.month.length && shared.year.length && regions.length && models.length)
    const tasks = (await api('/api/detection/tasks?size=1')).total
    const workload = await api('/api/dashboard/quality-workload')
    console.log(role, JSON.stringify({tasks, visibleCompleted:stats.detectionCount, sharedCompleted:stats.companyDetectionCount,
      week:shared.week.length, month:shared.month.length, years:shared.year.length, regions:regions.length, models:models.length,
      targets:distribution.reduce((s,r)=>s+r.count,0), pendingReview:workload.pendingReviewCount}))
    return { shared, tasks, completed:stats.detectionCount }
  } finally { await context.close() }
}

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE || undefined })
  try {
    const supervisor = await inspect(browser, 'SUPERVISOR')
    const inspector = await inspect(browser, 'INSPECTOR')
    assert.deepEqual(inspector.shared, supervisor.shared)
    assert(inspector.tasks < supervisor.tasks && inspector.completed < supervisor.completed)
    console.log('PASS two roles see identical dashboard charts and distinct scoped task counts')
  } finally { await browser.close() }
}
main().catch(error => { console.error(error.message); process.exitCode = 1 })
