const taskTools = new Set(['get_task_detail', 'get_my_detection_tasks', 'search_detection_tasks', 'get_my_quality_records', 'get_quality_records'])
const metricTools = new Set(['get_my_work_metrics', 'get_department_work_metrics'])
const reportTools = new Set(['list_quality_reports', 'get_quality_report', 'create_report_draft', 'edit_report_draft'])
const taskId = /^[A-Za-z0-9_-]{1,128}$/
const reportId = /^qr-[a-f0-9-]{36}$/

export function validCardReference(card) {
  if (!card || typeof card !== 'object' || Array.isArray(card) || Object.keys(card).some(key => !['type', 'tool', 'ids', 'days'].includes(key))) return false
  if (!Array.isArray(card.ids) || card.ids.length > 5 || new Set(card.ids).size !== card.ids.length || card.ids.some(id => typeof id !== 'string')) return false
  if (card.type === 'METRICS') return metricTools.has(card.tool) && !card.ids.length && Number.isInteger(card.days) && card.days >= 1 && card.days <= 366
  if (card.days != null) return false
  if (card.type === 'TASKS') return taskTools.has(card.tool) && card.ids.every(id => taskId.test(id))
  return card.type === 'REPORTS' && reportTools.has(card.tool) && card.ids.every(id => reportId.test(id))
}

export function parseAgentCardEnvelope(content) {
  try {
    if (typeof content !== 'string' || content.length > 128000) return null
    const value = JSON.parse(content)
    if (value?.version !== 1 || typeof value.text !== 'string' || !Array.isArray(value.cards) || value.cards.length > 8 || !value.cards.every(validCardReference)) return null
    if (value.runId != null && (typeof value.runId !== 'string' || !/^[A-Za-z0-9_:.-]{1,128}$/.test(value.runId))) return null
    return value
  } catch { return null }
}

export function cardRoute(type, id) {
  if (type === 'TASKS' && typeof id === 'string' && taskId.test(id)) return '#/inspection/workbench?taskId=' + encodeURIComponent(id)
  if (type === 'REPORTS' && typeof id === 'string' && reportId.test(id)) return '#/quality/reports?reportId=' + encodeURIComponent(id)
  return ''
}

export const cardTitle = card => card.type === 'METRICS' ? '工作统计' : card.type === 'REPORTS' ? (['create_report_draft', 'edit_report_draft'].includes(card.tool) ? '报告草稿结果' : '报告查询') : ['get_my_quality_records', 'get_quality_records'].includes(card.tool) ? '质检记录' : '检测任务'
export const cardScope = scope => scope === 'SINGLE_ENTERPRISE' ? '全企业' : scope === 'OWNED_OR_ASSIGNED' ? '本人及分派任务' : ''
export const reportStatus = status => ({ DRAFT: '私人草稿', SUBMITTED: '待审批', APPROVED: '已审批', REJECTED: '已驳回', WITHDRAWN: '已撤回' }[status] || '状态未知')
export const metricLabels = { taskCount: '任务数', imageCount: '图片数', processedImageCount: '已处理图片', defectCount: '缺陷数量' }
