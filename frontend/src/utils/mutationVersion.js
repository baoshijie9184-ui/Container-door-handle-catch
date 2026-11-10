import { createUiRequestId } from './requestIdentity'

// Keep database versions as decimal strings. A model's `version` is its release label.
export function decimalVersion(value) {
  if (typeof value === 'number') return Number.isSafeInteger(value) && value >= 0 ? String(value) : null
  return typeof value === 'string' && /^(0|[1-9]\d*)$/.test(value) ? value : null
}
export function resourceVersion(resource, { model = false } = {}) {
  return decimalVersion(resource?.rowVersion ?? resource?.mutationVersion ?? (model ? undefined : resource?.version)
    ?? resource?.result?.rowVersion ?? resource?.result?.mutationVersion ?? (model ? undefined : resource?.result?.version))
}
export function responseResourceVersion(response, resource = response?.data?.data) {
  const headers=response?.headers
  return decimalVersion(headers?.get?.('X-Resource-Version') ?? headers?.['x-resource-version'] ?? headers?.['X-Resource-Version'])
    ?? resourceVersion(resource)
}
export function mutationHeaders(version, requestId = createUiRequestId()) {
  const expected = decimalVersion(version)
  if (expected === null) throw Object.assign(new Error('尚未读取有效的资料版本 请重新读取后操作'),{notSent:true})
  return { 'X-Expected-Version': expected, 'If-Match': '"' + expected + '"', 'X-Request-ID': requestId }
}
export function captureTaskMutation(task) {
  return { ...task, result: task.result ? { ...task.result } : task.result,
    mutationVersion: resourceVersion(task), mutationRequestId: createUiRequestId() }
}
const taskIntents = new WeakMap()
export function taskMutationPayload(snapshot, payload) {
  if (!snapshot || typeof snapshot !== 'object') throw new Error('请重新选择任务')
  if (snapshot.mutationConflicted) throw Object.assign(new Error('资料版本已变化 原草稿已保留 请重新读取任务后再提交'),{notSent:true})
  if (!taskIntents.has(snapshot)) taskIntents.set(snapshot, createMutationIntent())
  return taskIntents.get(snapshot).prepare(payload, snapshot.mutationVersion, snapshot.mutationRequestId)
}

// Retry exactly the first submitted draft. Changing a rejected/uncertain draft needs a new intent.
export function createMutationIntent() {
  let command
  return {
    prepare(payload, version, requestId = createUiRequestId()) {
      const expectedVersion = decimalVersion(version)
      mutationHeaders(expectedVersion, requestId)
      const value = { ...payload, expectedVersion }, signature = JSON.stringify(value)
      if (command && command.signature !== signature) throw new Error('本次请求已发送 修改内容前请关闭并重新打开表单 原草稿已保留')
      if (!command) command = { signature, payload: Object.freeze({ ...value, requestId }) }
      return command.payload
    },
    reset() { command = undefined },
  }
}
