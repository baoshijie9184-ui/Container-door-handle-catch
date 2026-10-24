// Dimensions describe the decoded preview image, not the source document or detection accuracy.
export function previewImageDimensions(width, height) {
  return Number.isSafeInteger(width) && width > 0 && Number.isSafeInteger(height) && height > 0 ? { width, height } : null
}
export function previewImageSizeLabel(dimensions, kind) {
  if (!dimensions) return '预览图尺寸未读取'
  return (kind === 'pdf' ? '页面预览图 ' : '预览图 ') + dimensions.width.toLocaleString('zh-CN') + ' × ' + dimensions.height.toLocaleString('zh-CN') + ' 像素'
}
