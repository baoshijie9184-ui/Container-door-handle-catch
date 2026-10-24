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
  for (const [list,keys] of [[task?.previewImages,['annotatedUrl','previewUrl']],[task?.defectEvidence,['previewUrl','annotatedUrl']],[task?.originalImages,['previewUrl']]]) {
    if (!Array.isArray(list)) continue
    for (const item of list) for (const key of keys) if (typeof item?.[key] === 'string' && item[key].trim()) return item[key]
  }
  return ''
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
