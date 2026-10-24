import { agentImagePreview, businessImagePreview } from './agentActions'

// Keep the original authenticated preview paths. Never turn a model-supplied URL into an image request.
export function proposalImageRows(images, scope = '') {
  if (!Array.isArray(images)) return []
  return images.map((image, index) => {
    const file = image && typeof image === 'object' && !Array.isArray(image) ? image : {}
    const path = file.origin != null ? agentImagePreview(file) : agentImagePreview(file) || businessImagePreview(file)
    const name = typeof file.name === 'string' && file.name.trim() ? file.name : '图片名称未记录'
    const hash = typeof file.sha256 === 'string' && /^[a-f0-9]{64}$/.test(file.sha256) ? file.sha256 : ''
    const business = path.startsWith('/api/agent/business-files/DETECTION/')
    const task = business ? file.origin?.taskId || file.resourceId : null
    return { key: JSON.stringify([scope, index, path, hash, name]), path, name, hash,
      source: business ? '业务原图' : path ? '会话上传' : '来源待核对',
      taskId: typeof task === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(task) ? task : '' }
  })
}
