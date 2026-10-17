const taskTools = new Set(['get_task_detail', 'get_my_detection_tasks', 'search_detection_tasks', 'get_my_quality_records', 'get_quality_records'])
const metricTools = new Set(['get_my_work_metrics', 'get_department_work_metrics'])
const reportTools = new Set(['list_quality_reports', 'get_quality_report', 'create_report_draft', 'edit_report_draft'])
const taskId = /^[A-Za-z0-9_-]{1,128}$/
const reportId = /^qr-[a-f0-9-]{36}$/

export function validResourceId(id, type) {
  const maximum = ['DEVICES', 'DEVICE_ALERTS'].includes(type) ? '9223372036854775807' : ['MODELS', 'MODEL_OPERATIONS'].includes(type) ? '2147483647' : ''
  return !!maximum && typeof id === 'string' && /^[1-9][0-9]{0,18}$/.test(id) && (id.length < maximum.length || id.length === maximum.length && id <= maximum)
}

export function validCardReference(card) {
  if (!card || typeof card !== 'object' || Array.isArray(card) || Object.keys(card).some(key => !['type', 'tool', 'ids', 'days'].includes(key))) return false
  if (!Array.isArray(card.ids) || card.ids.length > 5 || new Set(card.ids).size !== card.ids.length || card.ids.some(id => typeof id !== 'string')) return false
  if (card.type === 'METRICS') return metricTools.has(card.tool) && !card.ids.length && Number.isInteger(card.days) && card.days >= 1 && card.days <= 366
  if (card.days != null) return false
  if (card.type === 'TASKS') return taskTools.has(card.tool) && card.ids.every(id => taskId.test(id))
  if (card.type === 'DEVICES') return card.tool === 'list_devices' && card.ids.every(id => validResourceId(id, 'DEVICES'))
  if (card.type === 'DEVICE_ALERTS') return ['list_device_alerts', 'get_device_alert'].includes(card.tool) && card.ids.every(id => validResourceId(id, 'DEVICE_ALERTS'))
  if (card.type === 'MODELS') return card.tool === 'list_models' && card.ids.every(id => validResourceId(id, 'MODELS'))
  if (card.type === 'MODEL_OPERATIONS') return card.tool === 'get_model_operations' && card.ids.every(id => validResourceId(id, 'MODEL_OPERATIONS'))
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
  if (type === 'DEVICES' && validResourceId(id, type)) return '#/devices/' + id
  if (['MODELS', 'MODEL_OPERATIONS'].includes(type) && validResourceId(id, type)) return '#/models?modelId=' + id
  return ''
}

export const cardTitle = card => card.type === 'MODEL_OPERATIONS' ? '模型指标与发布配置' : card.type === 'DEVICE_ALERTS' ? '采集告警' : card.type === 'DEVICES' ? '设备运行状态' : card.type === 'MODELS' ? '检测模型' : card.type === 'METRICS' ? '工作统计' : card.type === 'REPORTS' ? (['create_report_draft', 'edit_report_draft'].includes(card.tool) ? '报告草稿结果' : '报告查询') : ['get_my_quality_records', 'get_quality_records'].includes(card.tool) ? '质检记录' : '检测任务'

const rolloutLabels = { FULL: '全量', CANARY: '灰度', AB_TEST: 'A/B 测试', ROLLBACK: '回滚' }
const validationLabels = { PASSED: '校验通过', FAILED: '校验失败', PENDING: '待校验' }
const mlopsLabels = { UNASSESSED: '未评估', EVALUATED: '已登记评估', ROLLOUT: '已登记发布策略', ROLLED_BACK: '已登记回滚' }
const invalidOperationField = (item, field) => Array.isArray(item?.invalidFields) && item.invalidFields.includes(field)
function operationNumber(item, field, value, maximum, format, integer = false, minimum = 0) {
  if (invalidOperationField(item, field)) return '需核对'
  if (value == null) return '未记录'
  if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum || value > maximum || integer && !Number.isInteger(value)) return '需核对'
  return format(value)
}
function operationCode(item, field, value, labels) {
  if (invalidOperationField(item, field)) return '需核对'
  if (value == null) return '未记录'
  return typeof value === 'string' && Object.hasOwn(labels, value) ? labels[value] : '需核对'
}
const operationText = value => typeof value === 'string' && value.trim() ? value : '未记录'
const operationDate = value => typeof value === 'string' && value ? value.replace('T', ' ').slice(0, 19) : '未记录'
export function modelOperationMetrics(item) {
  return [['precisionScore', 'Precision'], ['recallScore', 'Recall'], ['mapScore', 'mAP'], ['f1Score', 'F1']].map(([field, label]) => ({
    label, value: operationNumber(item, field, item?.evaluation?.[field], 1, value => (value * 100).toLocaleString('zh-CN', { maximumFractionDigits: 4 }) + '%'),
  }))
}
export function modelOperationDetails(item) {
  const evaluation = item?.evaluation || {}, rollout = item?.rollout || {}, usage = item?.usage || {}
  return [
    { label: '测试集', value: operationText(evaluation.dataset) },
    { label: '登记平均耗时', value: operationNumber(item, 'avgInferenceMs', evaluation.avgInferenceMs, 2147483647, value => value + ' ms', true) },
    { label: '校验状态', value: operationCode(item, 'validationStatus', item?.validationStatus, validationLabels) },
    { label: 'MLOps 状态', value: operationCode(item, 'mlopsStatus', item?.mlopsStatus, mlopsLabels) },
    { label: '发布策略配置', value: operationCode(item, 'strategy', rollout.strategy, rolloutLabels) },
    { label: '配置比例', value: operationNumber(item, 'configuredPercent', rollout.configuredPercent, 100, value => value + '%', true) },
    { label: 'A/B 分组', value: operationText(rollout.abGroup) },
    { label: '回滚来源模型', value: operationNumber(item, 'rollbackFromModelId', rollout.rollbackFromModelId, 2147483647, value => '#' + value, true, 1) },
    { label: '登记使用次数', value: operationNumber(item, 'usageCount', usage.count, 2147483647, String, true) },
    { label: '最近登记使用', value: operationDate(usage.lastUsedAt) },
    { label: '登记发布时间', value: operationDate(usage.publishedAt) },
  ]
}
const alertStatusLabels = { OPEN: '待处理', ACKNOWLEDGED: '已确认', RESOLVED: '已解决' }
const alertLevelLabels = { MINOR: '轻微', MAJOR: '严重', CRITICAL: '紧急' }
const alertTypeLabels = { CAPTURE_EXCEPTION: '采集异常', HEARTBEAT_OFFLINE: '心跳离线' }
export const alertStatus = status => Object.hasOwn(alertStatusLabels, status) ? alertStatusLabels[status] : '状态未知'
export const alertLevel = level => Object.hasOwn(alertLevelLabels, level) ? alertLevelLabels[level] : '级别未知'
export const alertType = type => Object.hasOwn(alertTypeLabels, type) ? alertTypeLabels[type] : '类型未知'
const modelStatusLabels = { READY: '待发布', PUBLISHED: '已发布', DISABLED: '已停用', ARCHIVED: '已归档', DRAFT: '草稿' }
const deviceStatusLabels = { IN_USE: '使用中', MAINTENANCE: '维护中', IDLE: '空闲', OFFLINE: '离线', ONLINE: '在线', NORMAL: '正常', CONNECTED: '已连接', DISCONNECTED: '未连接', ERROR: '异常', RUNNING: '运行中', STOPPED: '已停止', CAPTURING: '采集中', UNKNOWN: '未知' }
export const modelStatus = status => Object.hasOwn(modelStatusLabels, status) ? modelStatusLabels[status] : '状态未知'
export const deviceStatus = status => Object.hasOwn(deviceStatusLabels, status) ? deviceStatusLabels[status] : '未知'
export const cardScope = scope => scope === 'SINGLE_ENTERPRISE' ? '全企业' : scope === 'OWNED_OR_ASSIGNED' ? '本人及分派任务' : ''
export const reportStatus = status => ({ DRAFT: '私人草稿', SUBMITTED: '待审批', APPROVED: '已审批', REJECTED: '已驳回', WITHDRAWN: '已撤回' }[status] || '状态未知')
export const metricLabels = { taskCount: '任务数', imageCount: '图片数', processedImageCount: '已处理图片', defectCount: '缺陷数量' }
