import { knownCount } from './countPresentation'
import { defaultModelLabel } from './composerResources'

// Filename-derived type is display metadata, not a claim about validated content.
export function composerAttachment(file) {
  const extension = typeof file?.name === 'string' ? file.name.split('.').pop().toLowerCase() : ''
  const image = ['png', 'jpg', 'jpeg', 'webp'].includes(extension)
  const data = ['csv', 'json'].includes(extension)
  const source = ['html', 'svg'].includes(extension)
  const type = image ? '图片' : extension === 'pdf' ? 'PDF' : data ? extension.toUpperCase() : source ? `${extension.toUpperCase()} 源码` : ['md', 'txt'].includes(extension) ? extension.toUpperCase() : '文件'
  const bytes = knownCount(file?.bytes)
  const size = bytes === null ? '大小未记录' : bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KiB` : `${(bytes / 1048576).toFixed(1)} MiB`
  return { type, size, icon:image ? 'Picture' : data ? 'DataAnalysis' : 'Document' }
}

export function composerDefaultModel(state = {}) {
  if (!state.ready) return state.modelError ? '模型选择待核对' : '模型选择尚未就绪'
  const models = Array.isArray(state.models) ? state.models : []
  if (state.defaultModelId && !models.some(model => model.id === state.defaultModelId)) return '系统默认模型待核对'
  return defaultModelLabel({ ...state, models })
}

export function composerUploadHint(state = {}, disabled = false) {
  if (disabled) return '当前正在处理消息，请稍候'
  if (state.busy) return '正在处理附件或模型选择，请稍候'
  if (!state.ready) return '附件工作区尚未就绪，请先核对服务状态'
  if (!state.filesEnabled) return '当前服务未启用会话文件上传'
  return '上传本人会话文件，发送时以文件编号引用'
}
