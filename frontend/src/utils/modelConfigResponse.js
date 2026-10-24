const unavailable = () => new Error('模型管理暂不可用，请核对主管权限、服务开关及前后端版本')
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)

export function readModelConfiguration(value) {
  // Some legacy deployments return an HTTP 200 envelope for an absent route.
  // Validate the entire view before replacing any previously verified state.
  if (!record(value) || !Number.isSafeInteger(value.activeRevision) || value.activeRevision < 1
      || !Array.isArray(value.versions) || !value.versions.length) throw unavailable()
  const revisions = new Set()
  for (const version of value.versions) {
    const document = version?.document
    if (!record(version) || !Number.isSafeInteger(version.revision) || version.revision < 1
        || revisions.has(version.revision) || !record(document) || !record(version.credentials)
        || !Array.isArray(document.models) || !document.models.length
        || !document.models.every(model => record(model) && typeof model.id === 'string' && typeof model.enabled === 'boolean')
        || !Array.isArray(document.fallbackModels) || !document.fallbackModels.every(id => typeof id === 'string')
        || typeof document.defaultModel !== 'string' || typeof document.memoryModel !== 'string'
        || typeof document.fallbackEnabled !== 'boolean'
        || !['timeoutMs', 'firstTokenTimeoutMs', 'maxOutputTokens'].every(field => Number.isSafeInteger(document[field]) && document[field] > 0)
        || !['DRAFT', 'VALIDATED', 'PUBLISHED', 'RETIRED'].includes(version.status)
        || !['dashscope', 'deepseek', 'openai'].every(provider => typeof version.credentials[provider] === 'boolean')
        || version.jsonProbes != null && !Array.isArray(version.jsonProbes)) throw unavailable()
    revisions.add(version.revision)
  }
  if (!revisions.has(value.activeRevision)) throw unavailable()
  return value
}
