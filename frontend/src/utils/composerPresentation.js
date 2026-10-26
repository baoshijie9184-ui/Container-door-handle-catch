import { knownCount } from './countPresentation'
import { defaultModelLabel, modelLabel } from './composerResources'

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
  if (!state.ready) return '附件工作区尚未就绪，请先核对服务状态'
  if (!state.filesEnabled) return '当前服务未启用会话文件上传'
  if (state.busy) return '正在处理附件或模型选择，请稍候'
  if (disabled) return '当前消息输入暂不可用，请先核对会话与运行状态'
  return '上传本人会话文件，发送时以文件编号引用'
}

export function composerModelTitle(state = {}, locked = false, disabled = false) {
  const model=(Array.isArray(state.models) ? state.models : []).find(item=>item?.id===state.modelId)
  const label=state.modelId ? model ? modelLabel(model) : '原选模型尚未核对' : composerDefaultModel(state)
  const reason=!state.ready ? '模型目录与会话选择尚未就绪' : locked ? '当前任务模型已固定，结束后可切换' : state.busy ? '正在等待附件或模型选择回执' : disabled ? '当前消息输入暂不可用' : '选择仅对当前会话的新任务生效，实际调用以执行轨迹为准'
  return label+'\n'+reason+(state.fallbackEnabled ? '\n请求失败时可使用备用模型，实际调用见执行轨迹' : '')
}
