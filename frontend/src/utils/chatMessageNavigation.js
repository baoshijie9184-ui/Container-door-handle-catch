export const buildChatMessageKey = (message, index) => {
  if (message?.id !== null && message?.id !== undefined) {
    return `message-${message.id}`
  }
  return `message-${message?.role || 'unknown'}-${message?.createdAt || 'pending'}-${index}`
}

export const buildQuestionItems = (messages = []) => messages
  .map((message, index) => ({ message, index }))
  .filter(({ message }) => message?.role === 'user')
  .map(({ message, index }) => ({
    key: buildChatMessageKey(message, index),
    content: String(message.content || '').trim() || '未命名提问',
    createdAt: message.createdAt || ''
  }))
