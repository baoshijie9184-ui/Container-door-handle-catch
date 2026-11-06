// Execute with the frontend checks on ECS; this file does not start a local runtime.
const test = require('node:test')
const assert = require('node:assert/strict')
const { readFrontendFile } = require('./helpers/project-source.cjs')
const source = readFrontendFile('src', 'utils', 'modelQuotaPresentation.js')
const modulePromise = import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)

test('enterprise remaining quota distinguishes unlimited, unresolved history, missing data and an overrun', async () => {
  const { enterpriseAvailableValue } = await modulePromise
  assert.equal(enterpriseAvailableValue({}), '未知')
  assert.equal(enterpriseAvailableValue({ total_tokens: 1000, available_tokens: 700 }), '未知')
  assert.equal(enterpriseAvailableValue({ total_tokens: null }), '未设企业上限')
  assert.equal(enterpriseAvailableValue({ total_tokens: 1000, unreconciled_legacy_attempts: 1, available_tokens: null }), '历史用量待核实')
  assert.equal(enterpriseAvailableValue({ total_tokens: 1000, unreconciled_legacy_attempts: 0, available_tokens: -50 }), '-50')
})

test('missing quota values remain unknown while a real zero and an overrun remain visible', async () => {
  const { quotaCount, personalQuotaValue } = await modulePromise
  for (const value of [null, undefined, '', ' ', false, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) assert.equal(quotaCount(value), '未知')
  assert.equal(quotaCount(0), '0')
  assert.equal(personalQuotaValue({ hasPersonalQuota: true, totalTokens: 1000, availableTokens: -125 }, 'availableTokens'), '-125')
  assert.equal(personalQuotaValue({ hasPersonalQuota: true, totalTokens: 1000 }, 'availableTokens'), '未知')
})

test('unconfigured personal quotas preserve rights and stay distinct from unlimited personal quotas', async () => {
  const { personalQuotaValue, canApplyForQuota } = await modulePromise
  const legacy = { configured: true, hasPersonalQuota: false, totalTokens: null, availableTokens: null }
  const unlimited = { ...legacy, hasPersonalQuota: true }
  assert.equal(personalQuotaValue(legacy, 'totalTokens'), '未设置')
  assert.equal(personalQuotaValue(legacy, 'availableTokens'), '沿用原权限')
  assert.equal(canApplyForQuota(legacy), true)
  assert.equal(personalQuotaValue(unlimited, 'totalTokens'), '未设个人上限')
  assert.equal(personalQuotaValue(unlimited, 'availableTokens'), '未设个人上限')
  assert.equal(canApplyForQuota(unlimited), false)
  assert.equal(personalQuotaValue({ hasPersonalQuota: true }, 'totalTokens'), '未知')
  assert.equal(personalQuotaValue({ totalTokens: null }, 'availableTokens'), '未知')
})

test('models with unknown or absent connection/limit configuration cannot accept an application', async () => {
  const { canApplyForQuota } = await modulePromise
  for (const row of [null, {}, { configured: false, hasPersonalQuota: false }, { configured: true }, { configured: true, hasPersonalQuota: true }, { configured: true, hasPersonalQuota: true, totalTokens: -1 }]) assert.equal(canApplyForQuota(row), false)
  assert.equal(canApplyForQuota({ configured: true, hasPersonalQuota: true, totalTokens: 0 }), true)
})

test('personal expiry and enterprise blocking remain separate from the displayed personal balance', async () => {
  const { quotaStatus, enterpriseQuotaBlock, personalQuotaValue } = await modulePromise
  const row = { configured: true, hasPersonalQuota: true, totalTokens: 5000, availableTokens: 2000, expiresAt: '2000-01-01T00:00:00Z', enterpriseBlockedReason: 'HISTORY_UNRECONCILED' }
  assert.equal(quotaStatus(row).label, '个人额度已到期')
  assert.equal(personalQuotaValue(row, 'availableTokens'), '2,000')
  assert.match(enterpriseQuotaBlock(row), /历史用量尚未核实/)
  assert.equal(enterpriseQuotaBlock({ enterpriseBlockedReason: null }), '')
  assert.match(enterpriseQuotaBlock({}), /未完整读取/)
  assert.match(enterpriseQuotaBlock({ enterpriseBlockedReason: 'NEW_GATE' }), /暂不可用/)
})

test('incomplete catalog and missing pagination metadata are not silently treated as an empty result', async () => {
  const { readQuotaModels, readQuotaApplications } = await modulePromise
  for (const value of [undefined, {}, [null], [{ modelId: '' }], [{ modelId: 'one' }, { modelId: 'one' }]]) assert.throws(() => readQuotaModels(value))
  assert.deepEqual(readQuotaModels([]), [])
  for (const value of [null, [], { items: [] }, { items: [], nextCursor: '' }, { items: [], nextCursor: 0 }]) assert.throws(() => readQuotaApplications(value))
  assert.deepEqual(readQuotaApplications({ items: [], nextCursor: null }), { items: [], nextCursor: null })
})

test('approval records require exact safe versions and known positive requested amounts', async () => {
  const { readQuotaApplications } = await modulePromise
  const row = { id: 'application-id', modelId: 'configured-model', status: 'PENDING', version: 0, requestedTokens: 1000 }
  assert.equal(readQuotaApplications({ items: [row], nextCursor: 12 }).items[0], row)
  for (const patch of [{ version: null }, { version: -1 }, { version: Number.MAX_SAFE_INTEGER + 1 }, { requestedTokens: null }, { requestedTokens: 0 }, { requestedTokens: 1000000000001 }, { status: 'UNKNOWN' }]) assert.throws(() => readQuotaApplications({ items: [{ ...row, ...patch }], nextCursor: null }))
  assert.throws(() => readQuotaApplications({ items: [row, row], nextCursor: null }))
})
