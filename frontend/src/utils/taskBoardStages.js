import { statusPresentation } from './statusPresentation.js'
import { QUALITY_READY_STATUSES } from './qualityWorkflow.js'

export function modelStep(row) {
  if (QUALITY_READY_STATUSES.includes(row.modelStatus) && Number(row.totalImages) > 0 && Number(row.failedImages) === Number(row.totalImages)) {
    return '全部图片检测失败'
  }
  if (row.modelStatus === 'READY') return '待启动检测'
  return statusPresentation('detection', row.modelStatus || 'UNKNOWN').label
}

const humanStages = {
  WAITING_CHECK: '待人工校验',
  VERIFYING: '校验中',
  CHECKED: '校验完成',
  FOLLOW_UP: '校验待跟进',
  MODEL_DONE: '无校验记录'
}

export function humanStep(row) {
  if (!QUALITY_READY_STATUSES.includes(row.modelStatus)) return '未进入校验'
  if (row.reviewStatus === 'SKIPPED') return '已跳过校验'
  return humanStages[row.listPhase] || '校验状态未记录'
}

export function canReview(row) {
  return QUALITY_READY_STATUSES.includes(row.modelStatus)
    && ['WAITING_CHECK', 'VERIFYING'].includes(row.listPhase)
    && ['PENDING_REVIEW', 'REVIEWING'].includes(row.flow)
    && row.reviewStatus === 'PENDING'
}
