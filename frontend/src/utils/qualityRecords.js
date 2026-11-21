import { knownCount } from './countPresentation'

// Counts describe a recorded human review, not a pending review's initial field values.
export function qualityReviewCountText(status,value) {
  if (status==='REVIEWED') return knownCount(value)?.toLocaleString('zh-CN') ?? '数量未记录'
  if (status==='PENDING') return '待人工复核'
  if (status==='SKIPPED') return '当前记录已跳过复核'
  return '复核状态待核对'
}

export const buildTraceEvidenceRows = (detail) => {
  if (!detail) return []
  const originals = (detail.originalImages || []).map(item => ({ ...item, type: '原图' }))
  const previews = (detail.previewImages || []).map(item => ({ ...item, type: '标注图' }))
  return [...originals, ...previews]
}

export const formatEvidenceConfidence = (value) => {
  if ((typeof value !== 'number' && typeof value !== 'string') || (typeof value === 'string' && !value.trim())) return '—'
  const number = Number(value)
  if (!Number.isFinite(number) || number < 0 || number > 1) return '—'
  return `${Math.round(number * 1000) / 10}%`
}

export const formatPercentValue = (value) => {
  const number = Number(value || 0)
  return Math.round(number * 1000) / 10
}
