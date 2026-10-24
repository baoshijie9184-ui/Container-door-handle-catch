// Read-only presentation of the existing workbench DTO. Never infer authorization or token usage.
const phases = new Set(['PERSISTED','OFFLOADED','CONTEXT_STARTED','CONTEXT_COMPLETED','CONTEXT_FAILED','CONTEXT_CANCELLED'])
const count = value => Number.isSafeInteger(value) && value >= 0 ? value : null
const label = value => value === null ? '未知' : value.toLocaleString('zh-CN')
export function contextStatusCode(item) {
  const data = item?.data || {}
  if (data.phase === 'PERSISTED') return item.status === 'ACTIVE' ? 'ACTIVE' : item.status === 'INVALIDATED' ? 'INVALIDATED' : 'UNKNOWN'
  return phases.has(data.phase) ? data.phase : 'UNKNOWN'
}
export function contextPresentation(item) {
  const data = item?.data || {}, phase = typeof data.phase === 'string' ? data.phase : ''
  const before = count(data.beforeChars), after = count(data.afterChars), through = count(data.coveredThrough)
  const invalidated = phase === 'PERSISTED' && item?.status === 'INVALIDATED'
  let change = '压缩前后数据不完整，无法比较字符变化'
  if (before !== null && after !== null) {
    const difference = before - after
    change = difference === 0 ? '本次记录的字符数未变化' : `${difference > 0 ? '减少' : '增加'} ${Math.abs(difference).toLocaleString('zh-CN')} 字符`
    if (before > 0 && difference !== 0) change += `（${(Math.abs(difference) / before * 100).toLocaleString('zh-CN',{maximumFractionDigits:1})}%）`
  }
  const explanations = {
    PERSISTED:'摘要已保存为历史参考；后续使用仍会核对来源与权限，不代表本次模型已读取。',
    OFFLOADED:'工具结果保存为私有上下文资料。模型只接收摘录，完整内容需通过受控读取重新鉴权。',
    CONTEXT_STARTED:'正在生成摘要，尚不能根据开始记录判断压缩已经应用。',
    CONTEXT_COMPLETED:'此事件记录已应用压缩。字符数只描述当时文本，不代表当前模型上下文容量。',
    CONTEXT_FAILED:'此次摘要未应用，保留原上下文；不能将失败当成历史消息已经丢失。',
    CONTEXT_CANCELLED:'此次摘要已取消，不据此判断主任务或其他专业任务已经结束。'
  }
  const explanation = invalidated ? '此摘要已失效，不能据此认为后续任务仍在使用。原始聊天和工具回执继续保留。' : phases.has(phase) ? explanations[phase] : '此记录的上下文阶段尚未识别，请结合执行轨迹核对，不推断摘要已经生效。'
  return {
    offloaded:phase === 'OFFLOADED',invalidated,explanation,change,
    before:label(before),after:label(after),bytes:label(count(data.byteLength)),
    scope:data.agentScope === 'main' ? '主 Agent' : typeof data.agentScope === 'string' && data.agentScope.startsWith('child:') ? '专业子 Agent' : '范围未记录',
    cutoffLabel:data.agentScope === 'main' ? '覆盖历史至消息切点' : '覆盖至消息位置',cutoff:label(through),
    fileId:typeof data.fileId === 'string' && /^[a-f0-9-]{36}$/.test(data.fileId) ? data.fileId : '',
    sha256:typeof data.sha256 === 'string' && /^[a-f0-9]{64}$/.test(data.sha256) ? data.sha256 : ''
  }
}
