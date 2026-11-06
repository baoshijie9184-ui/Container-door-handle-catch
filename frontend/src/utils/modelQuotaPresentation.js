// A missing amount is unknown. Available tokens may legitimately be negative after settlement.
export function quotaNumber(value) {
  if (typeof value !== 'number' && typeof value !== 'string') return null
  if (typeof value === 'string' && !value.trim()) return null
  const number = Number(value)
  return Number.isSafeInteger(number) ? number : null
}

export function quotaCount(value) {
  return quotaNumber(value)?.toLocaleString('zh-CN') ?? '未知'
}

export function enterpriseAvailableValue(row) {
  if (row.total_tokens === null) return '未设企业上限'
  if (quotaNumber(row.total_tokens) === null) return '未知'
  const unresolved = quotaNumber(row.unreconciled_legacy_attempts)
  if (unresolved === null) return '未知'
  if (unresolved > 0) return '历史用量待核实'
  return quotaCount(row.available_tokens)
}

export function personalQuotaValue(row, key) {
  if (key === 'totalTokens' || key === 'availableTokens') {
    if (row.hasPersonalQuota === false) return key === 'totalTokens' ? '未设置' : '沿用原权限'
    if (row.hasPersonalQuota !== true) return '未知'
    if (row.totalTokens === null && (key === 'totalTokens' || row.availableTokens === null)) return '未设个人上限'
  }
  return quotaCount(row[key])
}

export function quotaStatus(row) {
  if (row.configured !== true) return { label: row.configured === false ? '未配置连接' : '连接配置未知', tone: 'info' }
  if (row.hasPersonalQuota === false) return { label: '沿用原使用权限', tone: 'info' }
  if (row.hasPersonalQuota !== true) return { label: '个人额度未完整读取', tone: 'warning' }
  if (row.expiresAt && Number.isFinite(Date.parse(row.expiresAt)) && Date.parse(row.expiresAt) <= Date.now()) return { label: '个人额度已到期', tone: 'warning' }
  if (row.totalTokens === null) return { label: '未设个人上限', tone: 'info' }
  const available = quotaNumber(row.availableTokens)
  if (available === null) return { label: '可用额度未知', tone: 'warning' }
  return available <= 0 ? { label: '个人可用额度不足', tone: 'warning' } : { label: '个人额度可用', tone: 'success' }
}

export function canApplyForQuota(row) {
  return row?.configured === true && (row.hasPersonalQuota === false || row.hasPersonalQuota === true && quotaNumber(row.totalTokens) !== null && Number(row.totalTokens) >= 0)
}

const enterpriseReasons = {
  HISTORY_UNRECONCILED: '企业历史用量尚未核实，当前暂停新增调用',
  EXPIRED: '企业额度已到期',
  LIMIT_REACHED: '企业可用额度不足',
  OBSERVED_EXHAUSTED: '最近一次供应商核对记录显示额度已耗尽'
}
export function enterpriseQuotaBlock(row) {
  if (row.enterpriseBlockedReason === null) return ''
  return Object.hasOwn(enterpriseReasons, row.enterpriseBlockedReason) ? enterpriseReasons[row.enterpriseBlockedReason] : row.enterpriseBlockedReason ? '企业额度暂不可用，请联系主管核对' : '企业额度限制状态未完整读取'
}

export const quotaApplicationLabels = { PENDING: '待审批', APPROVED: '已批准', REJECTED: '已拒绝', CANCELLED: '已取消' }
export const quotaApplicationTones = { PENDING: 'warning', APPROVED: 'success', REJECTED: 'danger', CANCELLED: 'info' }

export function readQuotaModels(value) {
  if (!Array.isArray(value) || value.some(row => !row || typeof row.modelId !== 'string' || !row.modelId.trim()) || new Set(value.map(row => row.modelId)).size !== value.length) throw new Error('模型额度目录未完整读取，请重新读取')
  return value
}

export function readQuotaApplications(value) {
  if (!value || !Array.isArray(value.items) || !Object.hasOwn(value, 'nextCursor') || value.nextCursor !== null && (quotaNumber(value.nextCursor) === null || Number(value.nextCursor) <= 0)) throw new Error('额度申请列表未完整读取，请重新读取')
  if (value.items.some(row => !row || typeof row.id !== 'string' || !row.id || typeof row.modelId !== 'string' || !row.modelId || quotaNumber(row.version) === null || Number(row.version) < 0 || quotaNumber(row.requestedTokens) === null || Number(row.requestedTokens) <= 0 || Number(row.requestedTokens) > 1000000000000 || !Object.hasOwn(quotaApplicationLabels, row.status)) || new Set(value.items.map(row => row.id)).size !== value.items.length) throw new Error('额度申请记录未完整读取，请重新读取')
  return value
}
