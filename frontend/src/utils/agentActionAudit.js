// Presentation of the existing read-only AgentActionService.Audit DTO in both UIs.
export const actionAuditEvents = {
  CONFIRMATION_CREATED: '保存操作提议',
  CONFIRMATION_DECIDED: '记录本人决策',
  CONFIRMATION_INVALIDATED: '提议失效',
  AUTHORIZATION_ALLOWED: '权限核对通过',
  AUTHORIZATION_DENIED: '权限核对拒绝',
  TOOL_EXECUTION_STARTED: '开始执行',
  BUSINESS_CHANGED: '业务已更新',
  TOOL_EXECUTION_COMPLETED: '执行结束',
  TOOL_EXECUTION_UNCONFIRMED: '执行结果待核对',
  TOOL_EXECUTION_CANCELLED: '创建已终止'
}

const results = {
  PENDING: '待确认', APPROVED: '已批准', EXECUTING: '执行中', NEEDS_REVIEW: '待核对',
  SUCCEEDED: '已完成', REJECTED: '已拒绝', CANCELLED: '已取消', EXPIRED: '已过期', INVALIDATED: '已失效'
}
const roles = { ADMIN: '管理员', SUPERVISOR: '主管', INSPECTOR: '检测员', OPERATOR: '操作员' }
const reasons = {
  RESOURCE_CHANGED: '任务已变化，请重新核对提议',
  ROLE_REVOKED: '当前账号已无操作权限',
  PARAMETERS_SUPERSEDED: '已有新参数，原提议失效',
  POLICY_CHANGED: '操作规则已更新',
  CONFIRMATION_EXPIRED: '确认已过期，未执行操作',
  ORIGIN_RUN_TERMINATED: '原运行已取消或中断',
  BUSINESS_PRECONDITION_CHANGED: '任务或责任人条件已变化',
  EXECUTION_NEEDS_REVIEW: '执行结果需要核对，不自动重做',
  USER_REJECT: '本人已拒绝', USER_CANCEL: '本人已取消',
  USER_ABANDONED: '本人已终止创建，原文件和不确定传输证据保留'
}
const text = value => typeof value === 'string' && value.length > 0 && value.length <= 128
export function validActionAudit(records) {
  if (!Array.isArray(records)) return false
  const ids = new Set()
  return records.every(row => {
    if (!row || !Number.isSafeInteger(row.id) || row.id <= 0 || ids.has(row.id) || !text(row.eventType) || !text(row.result)
      || (row.actorRole != null && !text(row.actorRole)) || (row.reasonCode != null && !text(row.reasonCode))
      || (row.occurredAt != null && typeof row.occurredAt !== 'string')) return false
    ids.add(row.id)
    return true
  })
}
const label = (catalog, code) => Object.hasOwn(catalog, code) ? catalog[code] : code
export const actionAuditEvent = code => label(actionAuditEvents, code)
export const actionAuditRole = code => label(roles, code) || '角色未记录'
export const actionAuditReason = code => label(reasons, code)
export function actionAuditResult(code, operation) {
  if (code === 'SUCCEEDED') return ['CREATE_DETECTION', 'RETRY_DETECTION'].includes(operation) ? '已提交检测' : operation === 'ASSIGN_QUALITY_TASK' ? '已分配' : '已完成'
  return label(results, code)
}
