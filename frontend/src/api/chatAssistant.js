import request from './request'

export const fetchChatSession = () => request.get('/api/chat-assistant/session')

export const fetchSessionList = () => request.get('/api/chat-assistant/sessions')

export const createSession = () => request.post('/api/chat-assistant/sessions')

export const fetchSessionById = (sessionId) => request.get(`/api/chat-assistant/sessions/${sessionId}`)

export const fetchSessionMessages = (sessionId) => request.get(`/api/chat-assistant/sessions/${sessionId}/messages`)

export const fetchSessionTrace = (sessionId) => request.get(`/api/chat-assistant/sessions/${sessionId}/trace`)

export const fetchAgentHealth = () => request.get('/api/chat-assistant/agent-health')

export const archiveSession = (sessionId) => request.put(`/api/chat-assistant/sessions/${sessionId}/archive`)

export const renameSession = (sessionId, title) => request.put(`/api/chat-assistant/sessions/${sessionId}/title`, { title })

export const togglePinSession = (sessionId, pinned) => request.put(`/api/chat-assistant/sessions/${sessionId}/pin`, { pinned })

export const deleteSession = (sessionId) => request.delete(`/api/chat-assistant/sessions/${sessionId}`)

export const sendChatMessage = (payload) => request.post('/api/chat-assistant/messages', payload, { timeout: 300000 })

export const transcribeChatVoice = (audioBlob, filename = 'voice.webm') => {
  const form = new FormData()
  form.append('file', audioBlob, filename)
  return request.post('/api/chat-assistant/voice/transcribe', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 30000
  })
}

export const streamChatMessage = async (payload, handlers = {}) => {
  const baseURL = import.meta.env.VITE_API_URL || ''
  const response = await fetch(`${baseURL}/api/chat-assistant/messages/stream`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  })

  if (!response.ok || !response.body) {
    throw new Error(`流式聊天请求失败: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let completed = false

  const dispatchBlock = (block) => {
    const lines = block.split(/\r?\n/)
    let event = 'message'
    const dataLines = []
    for (const line of lines) {
      if (line.startsWith('event:')) {
        event = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trimStart())
      }
    }
    if (!dataLines.length) return
    let data = dataLines.join('\n')
    try {
      data = JSON.parse(data)
    } catch (_) {
      // 保留原始文本，兼容后端临时文本事件
    }
    handlers.onEvent?.(event, data)
    if (event === 'chunk') handlers.onChunk?.(data.content || '')
    if (event === 'status') handlers.onStatus?.(data.message || '')
    if (event === 'done') {
      completed = true
      handlers.onDone?.(data.messageResponse || data)
    }
    if (event === 'error') handlers.onError?.(data)
  }

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop() || ''
      blocks.forEach(dispatchBlock)
    }
    buffer += decoder.decode()
    if (buffer.trim()) dispatchBlock(buffer)
    if (!completed) throw new Error('聊天连接提前结束，请刷新会话后再试')
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

export const confirmChatAction = (payload) => request.post('/api/chat-assistant/confirm', payload)

// 持久事件补读只执行 GET，不发起模型或工具请求。
export const fetchAgentRuns = (params = {}) => request.get('/api/agent/runs', { params })
export const fetchAgentRun = (runId) => request.get(`/api/agent/runs/${encodeURIComponent(runId)}`)
export const fetchAgentRunEvents = (runId, after = 0) => request.get(`/api/agent/runs/${encodeURIComponent(runId)}/events`, { params: { after, limit: 100 } })
export const fetchAgentRunSources = (runId) => request.get(`/api/agent/runs/${encodeURIComponent(runId)}/sources`)
export const exportAgentRunSources = (runId) => request.post(`/api/agent/runs/${encodeURIComponent(runId)}/sources/export`, { confirmed: true }, { responseType: 'arraybuffer', timeout: 35000, headers: { 'X-Agent-Action': 'export' } })
export const cancelAgentRun = (runId) => request.post(`/api/agent/runs/${encodeURIComponent(runId)}/cancel`, null, { headers: { 'X-Agent-Action': 'cancel' } })

export const fetchAgentActions = (params = {}) => request.get('/api/agent/actions', { params })
export const fetchAgentActionAudit = (id) => request.get(`/api/agent/actions/${encodeURIComponent(id)}/audit`)
export const confirmAgentAction = (id, decision, version) => request.post(`/api/agent/actions/${encodeURIComponent(id)}/confirm`, { decision, version }, { headers: { 'X-Agent-Action': 'confirm' } })
export const cancelAgentAction = (id, version) => request.post(`/api/agent/actions/${encodeURIComponent(id)}/cancel`, { version }, { headers: { 'X-Agent-Action': 'cancel' } })

// 只读解析业务引用；刷新不会发起模型、草稿保存或审批。
export const resolveAgentCards = (cards) => request.post('/api/agent/cards/resolve', { cards })
