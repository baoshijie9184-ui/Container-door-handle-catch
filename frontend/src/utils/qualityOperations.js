import { beijingDateTime } from './beijingTime'

export function operationData(response) {
  if (response.data?.code !== 200) { const error = new Error(response.data?.message || '操作未完成，请重新核对'); error.httpStatus = response.data?.code; throw error }
  return response.data.data
}
export function operationError(error, feature = false) {
  if (feature && [404, 501].includes(error.response?.status || error.httpStatus)) return '当前服务尚未启用此功能，请在服务升级后重新读取'
  return error.response?.data?.message || error.message || '操作未完成，请刷新核对后重试'
}
export function utcDisplay(value) {
  if (!value) return '—'
  let text = String(value).replace(' ', 'T')
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)) text += 'Z'
  return beijingDateTime(text) || '—'
}
export async function deliverFile(response, filename, allowedTypes, stillCurrent, expectedHash) {
  const type = response.headers?.['content-type'] || ''
  if (!(response.data instanceof Blob) || !allowedTypes.some(value => type.startsWith(value))) {
    let message = '文件尚未生成或无法读取，请刷新核对'
    if (response.data instanceof Blob && response.data.size < 64000) try { message = JSON.parse(await response.data.text()).message || message } catch { /* Retain safe file error. */ }
    throw new Error(message)
  }
  if (expectedHash) {
    const digest = await crypto.subtle.digest('SHA-256', await response.data.arrayBuffer())
    const actual = [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('')
    if (actual !== expectedHash) throw new Error('文件摘要与资料版本不一致，未开始下载')
  }
  if (!stillCurrent()) return
  const url = URL.createObjectURL(response.data), link = document.createElement('a')
  link.href = url; link.download = filename; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
