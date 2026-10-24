export const TERMINAL_FLOW_STATUSES = ['RELEASED', 'SCRAPPED', 'ARCHIVED']
export const QUALITY_READY_STATUSES = ['COMPLETED', 'PARTIAL_FAILED']
export const DISPOSABLE_FLOW_STATUSES = ['CONFIRMED', 'HOLD']
export const RELEASE_ALLOWED_CONCLUSIONS = ['NORMAL_RELEASE', 'FALSE_POSITIVE']

const FLOW_STATUS_TEXT = {
  UPLOADING: '上传中',
  PENDING_DETECTION: '待检测',
  DETECTING: '检测中',
  PENDING_REVIEW: '待复核',
  REVIEWING: '复核中',
  CONFIRMED: '已确认',
  REWORK_REQUIRED: '待返工',
  RECHECK_REQUIRED: '待复检',
  RELEASED: '已放行',
  SCRAPPED: '已报废',
  HOLD: '暂挂观察',
  ARCHIVED: '已归档',
  FAILED: '失败'
}

const DISPOSITION_STATUS_TEXT = {
  PENDING: '待处置',
  DISPOSED: '已处置'
}

const DISPOSITION_ACTION_TEXT = {
  RELEASE: '正常放行',
  REWORK: '返工处理',
  RECHECK: '安排复检',
  HOLD: '暂挂观察',
  SCRAP: '报废隔离'
}

const REVIEW_STATUS_TEXT = {
  PENDING: '待复核',
  REVIEWED: '已复核',
  SKIPPED: '已跳过'
}

const REVIEW_STATUS_TAG_TYPE = {
  PENDING: 'warning',
  REVIEWED: 'success',
  SKIPPED: 'info'
}

const REVIEW_CONCLUSION_TEXT = {
  CONFIRMED_DEFECT: '确认缺陷',
  FALSE_POSITIVE: '误报',
  NORMAL_RELEASE: '正常放行',
  NEEDS_RECHECK: '需二次复查'
}

const SEVERITY_TEXT = {
  MINOR: '轻微',
  MAJOR: '一般',
  CRITICAL: '严重'
}

const SEVERITY_TAG_TYPE = {
  MINOR: 'info',
  MAJOR: 'warning',
  CRITICAL: 'danger'
}

const pickTaskValue = (task, field) => task?.[field] ?? task?.result?.[field]

// Hints describe business state only; the server still checks current account permissions.
// A present but malformed action list must not silently fall back to permissive legacy rules.
const stateActionAllowed = (task, action, fallback) => {
  const actions = pickTaskValue(task, 'qualityActions')
  if (actions === undefined || actions === null) return fallback()
  return Array.isArray(actions) && actions.some(item => item?.action === action && item.stateAllowed === true)
}

export const qualityActionReason = (task, action) => {
  const actions = pickTaskValue(task, 'qualityActions')
  if (!Array.isArray(actions)) return '当前阶段不支持此操作，请刷新任务核对'
  return actions.find(item => item?.action === action)?.blockedReason || '任务状态已变化，请刷新后重试'
}

export const flowStatusText = (status) => FLOW_STATUS_TEXT[status] || status || '--'

export const dispositionStatusText = (status) => DISPOSITION_STATUS_TEXT[status] || status || '--'

export const dispositionActionText = (action) => DISPOSITION_ACTION_TEXT[action] || action || '--'

export const reviewStatusText = (status) => REVIEW_STATUS_TEXT[status] || status || '--'

export const reviewStatusTagType = (status) => REVIEW_STATUS_TAG_TYPE[status] || 'info'

export const reviewConclusionText = (conclusion) => REVIEW_CONCLUSION_TEXT[conclusion] || conclusion || '--'

export const severityText = (severity) => SEVERITY_TEXT[severity] || severity || '--'

export const severityTagType = (severity) => SEVERITY_TAG_TYPE[severity] || 'info'

export const isQualityReadyTask = (task) => {
  const status = pickTaskValue(task, 'status')
  return status ? QUALITY_READY_STATUSES.includes(status) : task?.stage === 'completed'
}

export const canReleaseDisposition = (task) => {
  const conclusion = pickTaskValue(task, 'reviewConclusion')
  return RELEASE_ALLOWED_CONCLUSIONS.includes(conclusion) && pickTaskValue(task, 'recheckRequired') !== true
}

export const shouldDefaultRecheck = (task) => pickTaskValue(task, 'recheckRequired') === true || pickTaskValue(task, 'reviewConclusion') === 'NEEDS_RECHECK'

export const canAssignQualityTask = (task) => stateActionAllowed(task, 'ASSIGN', () => {
  const flowStatus = pickTaskValue(task, 'flowStatus')
  return isQualityReadyTask(task) && ['PENDING_REVIEW', 'REVIEWING', 'CONFIRMED', 'REWORK_REQUIRED', 'RECHECK_REQUIRED', 'HOLD'].includes(flowStatus)
})

export const canReviewTask = (task) => stateActionAllowed(task, 'REVIEW', () => {
  const reviewStatus = pickTaskValue(task, 'reviewStatus')
  const flowStatus = pickTaskValue(task, 'flowStatus')
  return isQualityReadyTask(task) && reviewStatus === 'PENDING' && pickTaskValue(task, 'dispositionStatus') !== 'DISPOSED' && ['PENDING_REVIEW','REVIEWING'].includes(flowStatus)
})

export const canDisposeTask = (task) => stateActionAllowed(task, 'DISPOSE', () => {
  const reviewStatus = pickTaskValue(task, 'reviewStatus')
  const dispositionStatus = pickTaskValue(task, 'dispositionStatus')
  const flowStatus = pickTaskValue(task, 'flowStatus')
  const held = flowStatus === 'HOLD' && dispositionStatus === 'DISPOSED' && pickTaskValue(task, 'dispositionAction') === 'HOLD'
  return isQualityReadyTask(task) &&
    reviewStatus === 'REVIEWED' &&
    Boolean(pickTaskValue(task, 'reviewedAt')) && Boolean(pickTaskValue(task, 'reviewConclusion')) &&
    (held || (dispositionStatus !== 'DISPOSED' && flowStatus === 'CONFIRMED'))
})

export const canSubmitReworkResult = (task) => stateActionAllowed(task, 'SUBMIT_REWORK', () =>
  isQualityReadyTask(task) && pickTaskValue(task, 'flowStatus') === 'REWORK_REQUIRED' &&
  pickTaskValue(task, 'reviewStatus') === 'REVIEWED' && pickTaskValue(task, 'dispositionStatus') === 'DISPOSED' &&
  pickTaskValue(task, 'dispositionAction') === 'REWORK')
