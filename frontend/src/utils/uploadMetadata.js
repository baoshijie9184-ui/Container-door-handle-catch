const captureFields = ['captureDate', 'region', 'collector', 'deviceName', 'imageFolderName']

export const MAX_METADATA_BYTES = 256 * 1024

const object = value => value !== null && typeof value === 'object' && !Array.isArray(value)
function knownFields(value, keys, label) {
  const field = Object.keys(value).find(name => !keys.includes(name))
  if (field) throw new Error(`${label}包含未识别的字段：${field}`)
}

function text(value, max, label) {
  if (value == null) return ''
  if (typeof value !== 'string' || value.length > max) throw new Error(`${label}须为 ${max} 字以内的文本`)
  return value.trim()
}

export function folderRoot(files) {
  const path = files[0]?.relativePath || ''
  const separator = path.indexOf('/')
  const prefix = path.slice(0, separator + 1)
  return prefix && files.every(file => file.relativePath.startsWith(prefix)) ? prefix.slice(0, -1) : ''
}

export function parseUploadMetadata(contents, files, root) {
  let data
  try { data = JSON.parse(contents.replace(/^\uFEFF/, '')) }
  catch { throw new Error('无法读取 JSON，请检查文件格式') }
  if (!object(data) || (data.schemaVersion !== undefined && data.schemaVersion !== 1)) throw new Error('元数据须使用 schemaVersion 1 的 JSON 对象')
  knownFields(data, ['schemaVersion', 'captureInfo', 'notes', 'images'], '元数据')
  if (data.captureInfo != null && !object(data.captureInfo)) throw new Error('captureInfo 须为对象')
  if (data.captureInfo) knownFields(data.captureInfo, captureFields, '采集信息')
  const captureInfo = Object.fromEntries(captureFields.map(key => [key, text(data.captureInfo?.[key], 128, key)]).filter(([, value]) => value))
  const date = captureInfo.captureDate
  if (date && (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(Date.parse(date)) || new Date(date).toISOString().slice(0, 10) !== date)) {
    throw new Error('采集日期须为有效的 YYYY-MM-DD 日期')
  }

  const paths = new Set(files.map(file => root ? file.relativePath.slice(root.length + 1) : file.relativePath))
  if (data.images != null && (!Array.isArray(data.images) || data.images.length > paths.size)) throw new Error('images 须为图片清单，条数不能超过所选图片数')
  const seen = new Set()
  const images = (data.images || []).map(item => {
    if (!object(item) || typeof item.path !== 'string' || !paths.has(item.path)) throw new Error('图片清单须填写所选图片在文件夹中的相对路径')
    knownFields(item, ['path', 'notes', 'attributes'], '图片资料')
    if (seen.has(item.path)) throw new Error(`图片元数据重复：${item.path}`)
    seen.add(item.path)
    const notes = text(item.notes, 1000, '图片备注')
    const values = item.attributes == null ? {} : item.attributes
    if (!object(values) || Object.keys(values).length > 16) throw new Error('每张图的 attributes 须为最多 16 项的对象')
    const attributes = Object.fromEntries(Object.entries(values).map(([key, value]) => {
      const name = text(key, 80, '属性名称')
      const detail = text(value, 300, '属性内容')
      if (!name || !detail || name !== key) throw new Error('属性名称与内容须填写，名称首尾不能有空格')
      return [name, detail]
    }))
    return { path: item.path, ...(notes ? { notes } : {}), ...(Object.keys(attributes).length ? { attributes } : {}) }
  })
  return { captureInfo, notes: text(data.notes, 1000, '批次备注'), images }
}

export function downloadMetadata(documentData) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(documentData, null, 2) + '\n'], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'metadata.json'
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
