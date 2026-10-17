// A projection of recorded metadata. Missing timing, usage and source text stay missing.
const textFields = ['agent', 'tool', 'callId', 'parentCallId', 'scope', 'decision', 'policyVersion', 'result', 'command', 'status', 'skillId', 'sha256', 'modelRequestId', 'modelId', 'provider', 'model', 'failureReason', 'nextModelId', 'purpose', 'inputId']
const numberFields = ['elapsedMs', 'durationMs', 'inputTokens', 'outputTokens', 'version', 'attempt', 'firstContentMs', 'httpStatus', 'beforeMessages', 'afterMessages', 'beforeChars', 'afterChars']
export const traceCategories = [
  { value: 'ALL', label: '全部事件' }, { value: 'TOOL', label: '工具调用' },
  { value: 'MODEL', label: '模型请求' }, { value: 'AUTHORIZATION', label: '权限核验' },
  { value: 'SKILL', label: '技能与命令' }, { value: 'AGENT', label: 'Agent 协作' },
  { value: 'CONTEXT', label: '上下文压缩' },
]
const names = {
  PAUSE_REQUESTED:'请求暂停',RUN_PAUSED:'已到达暂停切点',RUN_RESUMED:'继续运行',STEERING_APPLIED:'已交付运行中补充要求',
  RUN_STARTED: '开始运行', RUN_COMPLETED: '运行完成', RUN_FAILED: '运行失败', RUN_ERROR: '运行失败', RUN_CANCELLED: '运行取消', RUN_INTERRUPTED: '运行中断',
  AGENT_STARTED: 'Agent 开始处理', AGENT_COMPLETED: 'Agent 处理完成', AGENT_ERROR: 'Agent 处理异常', AGENT_CANCELLED: 'Agent 已取消',
  MODEL_STARTED: '发起模型请求', MODEL_COMPLETED: '模型响应完成', MODEL_ERROR: '模型请求异常', MODEL_CANCELLED: '模型请求取消',
  MODEL_ATTEMPT_STARTED: '请求候选模型', MODEL_ATTEMPT_COMPLETED: '候选模型响应完成', MODEL_ATTEMPT_ERROR: '候选模型请求失败', MODEL_ATTEMPT_CANCELLED: '候选模型请求取消',
  MODEL_CANDIDATE_SKIPPED: '跳过熔断模型', MODEL_FALLBACK_SELECTED: '转向备用候选',
  AUTHORIZATION_ALLOWED: '工具角色核验通过', AUTHORIZATION_DENIED: '工具角色核验拒绝',
  TOOL_STARTED: '开始调用工具', TOOL_COMPLETED: '工具执行完成', TOOL_ERROR: '工具执行异常', TOOL_CANCELLED: '工具调用取消',
  SKILL_LOADED: '加载技能版本', SKILL_COMMAND: '解析技能命令', COMMAND_RESOLVED: '命令解析完成',
  COMMAND_RECEIVED: '收到技能命令', COMMAND_REJECTED: '技能命令被拒绝', SKILL_COMMAND_LOADED: '加载命令指定技能',
  CONTEXT_STARTED: '开始压缩上下文', CONTEXT_COMPLETED: '上下文压缩已应用', CONTEXT_FAILED: '压缩未采用 保留原上下文', CONTEXT_CANCELLED: '上下文压缩已取消',
}
export function traceStatus(value) {
  return ({ RUNNING: '运行中', COMPLETED: '已完成', FAILED: '失败', CANCELLED: '已取消', INTERRUPTED: '已中断',
    SUCCESS: '成功', ERROR: '异常', DENIED: '已拒绝', RECORDED: '仅有记录', INCOMPLETE: '未记录终态', PENDING: '等待结果' })[value] || value || '未记录'
}
export function eventCategory(type = '') {
  if (type.startsWith('SKILL') || type.startsWith('COMMAND')) return 'SKILL'
  return ['TOOL', 'MODEL', 'AUTHORIZATION', 'AGENT', 'CONTEXT'].find(category => type.startsWith(category + '_')) || 'RUN'
}
export function eventTone(type = '') {
  if (/(ERROR|FAILED|DENIED|INTERRUPTED|REJECTED)$/.test(type)) return 'danger'
  if (type.endsWith('CANCELLED')) return 'muted'
  if (/(COMPLETED|ALLOWED|LOADED|RESOLVED)$/.test(type)) return 'success'
  return 'primary'
}
export function normalizeTraceEvents(rows, legacy = false) {
  const seen = new Set()
  return (Array.isArray(rows) ? rows : []).flatMap((row, index) => {
    const sequence = legacy ? index + 1 : row?.sequence
    if (!row || !Number.isSafeInteger(sequence) || sequence < 1 || seen.has(sequence) || typeof row.type !== 'string') return []
    seen.add(sequence)
    const source = legacy ? row : row.payload
    const payload = {}
    for (const key of textFields) if (typeof source?.[key] === 'string') payload[key] = source[key]
    for (const key of numberFields) if (typeof source?.[key] === 'number' && Number.isFinite(source[key]) && source[key] >= 0) payload[key] = source[key]
    return [{ sequence, type: row.type, occurredAt: typeof row.occurredAt === 'string' ? row.occurredAt : null, payload }]
  }).sort((a, b) => a.sequence - b.sequence)
}
export const eventTitle = event => names[event.type] || event.type
export const modelFailureLabel = value => ({ QUOTA: '额度或余额不足', AUTH: '供应商鉴权失败', TIMEOUT: '请求超时', EMPTY_RESPONSE: '未返回有效内容', TRANSIENT: '网络或供应商临时故障', OTHER: '其他错误', CIRCUIT_OPEN: '熔断冷却或探测占用' })[value] || value || '未记录'
export function traceDuration(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '未记录'
  if (value < 1000) return `${Math.round(value)} ms`
  return `${(value / 1000).toFixed(value >= 10000 ? 1 : 2)} s`
}
export const traceTime = value => value ? String(value).replace('T', ' ').slice(0, 19) : '未记录'
export const traceEntry = value => ({ CHAT: '主站对话', AGUI: '独立 Agent', CHILD: '专业子 Agent', 'AG-UI': '独立 Agent', CHAT_ASSISTANT: '主站对话' })[value] || value || '未记录入口'
export function filterTraceEvents(events, category = 'ALL', query = '') {
  const needle = query.trim().toLowerCase()
  return events.filter(event => (category === 'ALL' || eventCategory(event.type) === category)
    && (!needle || [event.type, eventTitle(event), ...Object.values(event.payload)].join(' ').toLowerCase().includes(needle)))
}
export function traceCalls(events, runStatus) {
  const groups = new Map()
  for (const event of events) {
    const p = event.payload
    if (!p.tool || !['TOOL', 'AUTHORIZATION'].includes(eventCategory(event.type))) continue
    // Never infer correlation from a tool name alone: the same tool may run concurrently.
    const key = p.callId ? JSON.stringify([p.agent || '', p.parentCallId || '', p.callId]) : `event:${event.sequence}`
    if (!groups.has(key)) groups.set(key, { key, callId: p.callId, agent: p.agent, parentCallId: p.parentCallId, tool: p.tool, events: [] })
    groups.get(key).events.push(event)
  }
  return [...groups.values()].map(call => {
    const terminal = [...call.events].reverse().find(event => /^(TOOL_(COMPLETED|ERROR|CANCELLED)|AUTHORIZATION_DENIED)$/.test(event.type))
    const started = call.events.find(event => event.type === 'TOOL_STARTED')
    const status = terminal ? ({ TOOL_COMPLETED: 'SUCCESS', TOOL_ERROR: 'ERROR', TOOL_CANCELLED: 'CANCELLED', AUTHORIZATION_DENIED: 'DENIED' })[terminal.type]
      : started ? runStatus === 'RUNNING' ? 'PENDING' : 'INCOMPLETE' : 'RECORDED'
    return { ...call, status, durationMs: terminal?.payload.durationMs ?? null, startedAt: started?.payload.elapsedMs ?? null,
      firstSequence: call.events[0].sequence, lastSequence: call.events.at(-1).sequence }
  })
}
export function traceSummary(events, status) {
  const models = events.filter(event => event.type === 'MODEL_COMPLETED')
  const sum = key => { const values = models.map(event => event.payload[key]).filter(value => typeof value === 'number'); return values.length ? values.reduce((a,b) => a+b, 0) : null }
  return { events: events.length, tools: traceCalls(events, status).filter(call => call.events.some(event => event.type === 'TOOL_STARTED')).length,
    modelRequests: events.filter(event => event.type === 'MODEL_STARTED').length,
    modelAttempts: events.filter(event => event.type === 'MODEL_ATTEMPT_STARTED').length,
    fallbackSelections: events.filter(event => event.type === 'MODEL_FALLBACK_SELECTED').length,
    denied: events.filter(event => event.type === 'AUTHORIZATION_DENIED').length,
    inputTokens: sum('inputTokens'), outputTokens: sum('outputTokens'), usageRecords: models.filter(event => event.payload.inputTokens != null || event.payload.outputTokens != null).length }
}
export function traceModelRequests(events, runStatus) {
  const requests = new Map()
  for (const event of events) {
    const p = event.payload
    if (eventCategory(event.type) !== 'MODEL' || !p.modelRequestId) continue
    const key = JSON.stringify([p.agent || '', p.parentCallId || '', p.modelRequestId])
    if (!requests.has(key)) requests.set(key, { key, requestId: p.modelRequestId, agent: p.agent, events: [] })
    requests.get(key).events.push(event)
  }
  return [...requests.values()].map(request => {
    const candidates = new Map()
    for (const event of request.events) {
      const p = event.payload
      if (!p.modelId || !Number.isSafeInteger(p.attempt) || p.attempt < 1 || event.type === 'MODEL_FALLBACK_SELECTED') continue
      const key = JSON.stringify([p.attempt, p.provider || '', p.modelId])
      if (!candidates.has(key)) candidates.set(key, { key, modelId: p.modelId, provider: p.provider, model: p.model, attempt: p.attempt, events: [] })
      candidates.get(key).events.push(event)
    }
    const attempts = [...candidates.values()].map(candidate => {
      const terminal = [...candidate.events].reverse().find(event => /^(MODEL_ATTEMPT_(COMPLETED|ERROR|CANCELLED)|MODEL_CANDIDATE_SKIPPED)$/.test(event.type))
      const started = candidate.events.some(event => event.type === 'MODEL_ATTEMPT_STARTED')
      return { ...candidate, status: terminal ? ({ MODEL_ATTEMPT_COMPLETED: 'SUCCESS', MODEL_ATTEMPT_ERROR: 'ERROR', MODEL_ATTEMPT_CANCELLED: 'CANCELLED', MODEL_CANDIDATE_SKIPPED: 'SKIPPED' })[terminal.type]
        : started ? runStatus === 'RUNNING' ? 'PENDING' : 'INCOMPLETE' : 'RECORDED',
        durationMs: terminal?.payload.durationMs ?? null, firstContentMs: terminal?.payload.firstContentMs ?? null,
        failureReason: terminal?.payload.failureReason, httpStatus: terminal?.payload.httpStatus,
        firstEvent: candidate.events[0] }
    })
    return { ...request, purpose: request.events.some(event=>event.payload.purpose==='CONTEXT_COMPACTION')?'CONTEXT_COMPACTION':null, attempts }
  })
}
export function traceCompleteness(events, lastSequence) {
  let expected = 1
  for (const event of events) { if (event.sequence !== expected) return { complete: false, cursor: expected - 1 }; expected++ }
  const cursor = expected - 1
  return { complete: Number.isSafeInteger(lastSequence) && cursor === lastSequence, cursor }
}
