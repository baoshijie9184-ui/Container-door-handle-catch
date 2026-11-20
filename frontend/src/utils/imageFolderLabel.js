// Only the display label drops the storage hierarchy. Navigation keeps the original key.
export function imageFolderLabel(path) {
  const parts = String(path ?? '').split(/[\\/]+/).filter(Boolean)
  if (parts.length > 1 && /^originals?$/i.test(parts.at(-1))) parts.pop()
  const leaf = parts.at(-1) || ''
  if (parts.at(-4) === '图片上传' && ['主管上传', '员工上传'].includes(parts.at(-3))) {
    return leaf.replace(/_det_\d{8}_\d{6}_[a-f0-9]{8}$/i, '')
  }
  return leaf
}

export function recordFolderLabel(row) {
  const storageName = imageFolderLabel(row.prefix)
  if (row.taskType === 'OSS_FOLDER' && storageName) return storageName
  return imageFolderLabel(row.folder) || storageName || '未命名文件夹'
}
