import request from './request'

export const fetchChatSession = () => request.get('/api/chat-assistant/session')

export const fetchSessionList = () => request.get('/api/chat-assistant/sessions')

export const createSession = () => request.post('/api/chat-assistant/sessions')

export const fetchSessionById = (sessionId) => request.get(`/api/chat-assistant/sessions/${sessionId}`)

export const fetchSessionMessages = (sessionId) => request.get(`/api/chat-assistant/sessions/${sessionId}/messages`)

export const fetchSessionCheckpoint = (sessionId) => request.get(`/api/chat-assistant/sessions/${sessionId}/checkpoint`)

export const fetchAgentHealth = () => request.get('/api/chat-assistant/agent-health')

export const archiveSession = (sessionId) => request.put(`/api/chat-assistant/sessions/${sessionId}/archive`)

export const renameSession = (sessionId, title) => request.put(`/api/chat-assistant/sessions/${sessionId}/title`, { title })

export const togglePinSession = (sessionId, pinned) => request.put(`/api/chat-assistant/sessions/${sessionId}/pin`, { pinned })

export const deleteSession = (sessionId) => request.delete(`/api/chat-assistant/sessions/${sessionId}`)

export const sendChatMessage = (payload) => request.post('/api/chat-assistant/messages', payload)

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
    if (event === 'done') handlers.onDone?.(data.messageResponse || data)
    if (event === 'error') handlers.onError?.(data)
  }

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() || ''
    blocks.forEach(dispatchBlock)
  }
  if (buffer.trim()) {
    dispatchBlock(buffer)
  }
}

export const confirmChatAction = (payload) => request.post('/api/chat-assistant/confirm', payload)
