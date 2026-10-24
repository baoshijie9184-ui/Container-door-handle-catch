// Display allowlist only. Credentials and extra model metadata are never projected.
export const modelConfigFields = {
  models:'模型列表', defaultModel:'默认模型', memoryModel:'记忆提炼模型',
  fallbackModels:'备用模型顺序', timeoutMs:'总超时（毫秒）',
  firstTokenTimeoutMs:'首响应超时（毫秒）', maxOutputTokens:'最大输出 Token', fallbackEnabled:'备用切换'
}
export function modelConfigValue(field, value) {
  if (field === 'models') return Array.isArray(value) ? value.map(row => ({
    id: typeof row?.id === 'string' ? row.id : null,
    enabled: typeof row?.enabled === 'boolean' ? row.enabled : null
  })) : null
  if (field === 'fallbackModels') return Array.isArray(value) ? value.map(id => typeof id === 'string' ? id : null) : null
  if (field === 'fallbackEnabled') return typeof value === 'boolean' ? value : null
  if (['timeoutMs','firstTokenTimeoutMs','maxOutputTokens'].includes(field)) return Number.isSafeInteger(value) && value > 0 ? value : null
  return ['defaultModel','memoryModel'].includes(field) && typeof value === 'string' ? value : null
}
export function modelConfigChanges(before, after) {
  return Object.entries(modelConfigFields).map(([field,label]) => ({
    field, label, before:modelConfigValue(field,before?.[field]), after:modelConfigValue(field,after?.[field])
  })).filter(change => JSON.stringify(change.before) !== JSON.stringify(change.after))
}
export function modelConfigScalar(field, value) {
  const known = modelConfigValue(field,value)
  if (known == null || known === '') return '未填写或未记录'
  if (typeof known === 'boolean') return known ? '启用' : '停用'
  if (typeof known === 'number') return known.toLocaleString('zh-CN') + (field === 'maxOutputTokens' ? ' Token' : ' ms')
  return typeof known === 'string' ? known : '未记录'
}
