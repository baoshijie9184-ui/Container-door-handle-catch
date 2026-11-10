export const historicalRole = role => ({ SUPERVISOR: '主管', INSPECTOR: '检测人员' })[role] || '操作时角色未记录'
export const actorName = actor => actor?.displayName || actor?.username || (actor?.userId ? '账号 ' + actor.userId : '操作人未记录')
export const historyActorName = item => item?.source?.type === 'SYSTEM' ? '系统执行' : actorName(item?.actor)
export const historyActorRole = item => item?.source?.type === 'SYSTEM'
  ? ({DETECTION_WORKER:'检测执行器',IMAGE_DETECTION_ASYNC:'图片批量检测',IMAGE_DETECTION:'单图检测'})[item.source.component] || '系统执行来源'
  : historicalRole(item?.actor?.role)
export function historyInitiator(item) {
  if(item?.source?.type !== 'SYSTEM')return ''
  const origin=item.source.initiator
  return origin?.username || (origin?.userId ? '账号 '+origin.userId : '未记录')
}
// A notice for an open editor needs evidence newer than that editor's snapshot.
// An event about another row must not blame this row's previous operator.
export function newerResourceChange(item, openedVersion) {
  const revision = value => typeof value === 'number' ? Number.isSafeInteger(value) && value >= 0 ? String(value) : null
    : typeof value === 'string' && /^(0|[1-9]\d{0,18})$/.test(value) ? value : null
  const before = revision(openedVersion), after = revision(item?.afterVersion)
  if (before === null || after === null || BigInt(before) > 9223372036854775807n || BigInt(after) > 9223372036854775807n) return null
  return BigInt(after) > BigInt(before) ? item : null
}
export function changeValue(change, side) {
  if (change.redacted) return '内容已受保护'
  if (side === 'before' && change.operation === 'ADD' || side === 'after' && change.operation === 'REMOVE') return '字段不存在'
  if (!Object.prototype.hasOwnProperty.call(change, side)) return '历史未记录'
  const value = change[side]
  if (value === null) return '空值（NULL）'
  if (value === '') return '空字符串'
  if (value === false) return '否'
  if (value === true) return '是'
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)
}
export function resourceHistoryLink(resourceType, resourceId, domain) {
  return { path: '/operations/audit', query: { ...(resourceType && resourceId ? { resourceType, resourceId: String(resourceId) } : {}), ...(domain ? { domain } : {}) } }
}
export function readChangePage(response) {
  const raw = response?.data?.code === 200 ? response.data.data : response?.data
  if (!raw || !Array.isArray(raw.items) || raw.items.some(row => typeof row.id !== 'string' || !row.eventId)
      || raw.nextCursor != null && typeof raw.nextCursor !== 'string') throw new Error('修改记录未完整读取，请重新核对')
  return raw
}
