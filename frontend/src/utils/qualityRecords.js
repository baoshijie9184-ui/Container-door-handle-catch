export const normalizeQualityQueueRecord = (record = {}) => ({
  ...record,
  stage: record.stage ? record.stage.toLowerCase() : (record.status === 'FAILED' ? 'failed' : 'completed'),
  imageCount: record.totalImages || record.imageCount || 0,
  result: record.result || null,
  captureInfo: {
    captureDate: record.captureDate || '',
    region: record.region || '',
    collector: record.collector || '',
    deviceName: record.deviceName || '',
    imageFolderName: record.imageFolderName || ''
  }
})

export const buildTraceEvidenceRows = (detail) => {
  if (!detail) return []
  const originals = (detail.originalImages || []).map(item => ({ ...item, type: '原图' }))
  const previews = (detail.previewImages || []).map(item => ({ ...item, type: '标注图' }))
  return [...originals, ...previews]
}

export const resolveDefectPreview = (task = {}) => {
  const preview = task.previewImages?.find(item => item.annotatedUrl || item.previewUrl)
  if (preview) return preview.annotatedUrl || preview.previewUrl
  const evidencePreview = task.defectEvidence?.find(item => item.previewUrl || item.annotatedUrl)
  if (evidencePreview) return evidencePreview.previewUrl || evidencePreview.annotatedUrl
  const original = task.originalImages?.find(item => item.previewUrl)
  return original?.previewUrl || ''
}

export const formatEvidenceConfidence = (value) => {
  const number = Number(value)
  if (Number.isNaN(number)) return '--'
  return `${Math.round(number * 1000) / 10}%`
}

export const formatPercentValue = (value) => {
  const number = Number(value || 0)
  return Math.round(number * 1000) / 10
}
