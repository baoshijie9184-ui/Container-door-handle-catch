import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  archiveSession,
  confirmChatAction,
  createSession,
  deleteSession as deleteSessionApi,
  fetchAgentHealth,
  fetchChatSession,
  fetchSessionCheckpoint,
  fetchSessionById,
  fetchSessionList,
  fetchSessionMessages,
  renameSession,
  sendChatMessage,
  streamChatMessage,
  togglePinSession as togglePinSessionApi
} from '@/api/chatAssistant'
import {
  fetchProjectList,
  createProject as createProjectApi,
  updateProject as updateProjectApi,
  deleteProject as deleteProjectApi,
  moveSessionToProject,
  removeSessionFromProject
} from '@/api/chatProject'

export const useChatAssistantStore = defineStore('chatAssistant', () => {
  const visible = ref(false)
  const sessionId = ref('')
  const sessionTitle = ref('智能助手')
  const sessionStatus = ref('ACTIVE')
  const messages = ref([])
  const loading = ref(false)
  const bootstrapped = ref(false)
  const confirmingActionIds = ref(new Set())

  // 多会话
  const sessions = ref([])
  const sessionsLoading = ref(false)

  // 项目
  const projects = ref([])
  const projectsLoading = ref(false)

  // Agent 诊断
  const agentHealth = ref(null)
  const checkpointSnapshot = ref(null)
  const diagnosticsLoading = ref(false)

  // 菜单状态
  const menuOpenId = ref(null)
  const projectMenuOpenId = ref(null)

  let pollTimer = null
  let pollCount = 0
  let pollActive = false
  const POLL_INTERVAL = 3000
  const MAX_POLL_COUNT = 200

  /** 加载当前会话消息 */
  const loadSession = async (sid, force = false) => {
    if (!force && sessionId.value === sid && bootstrapped.value) return
    loading.value = true
    try {
      const response = await fetchSessionById(sid)
      const data = response.data?.data || {}
      sessionId.value = data.sessionId || sid
      sessionTitle.value = data.title || '智能助手'
      sessionStatus.value = data.status || 'ACTIVE'
      messages.value = data.messages || []
      bootstrapped.value = true
    } finally {
      loading.value = false
    }
  }

  const bootstrap = async (force = false) => {
    if (bootstrapped.value && !force) return
    await Promise.all([loadSessionList(), loadProjectList()])
    if (sessions.value.length > 0) {
      await loadSession(sessions.value[0].sessionId, force)
    } else {
      // 没有活跃会话时回退到旧接口创建默认会话
      try {
        const response = await fetchChatSession()
        const data = response.data?.data || {}
        sessionId.value = data.sessionId || ''
        sessionTitle.value = data.title || '智能助手'
        sessionStatus.value = data.status || 'ACTIVE'
        messages.value = data.messages || []
        bootstrapped.value = true
        await loadSessionList()
      } catch (err) {
        console.error('[chat] 加载默认会话失败:', err)
      }
    }
  }

  /** 加载会话列表 */
  const loadSessionList = async () => {
    sessionsLoading.value = true
    try {
      const response = await fetchSessionList()
      sessions.value = response.data?.data || []
    } catch (err) {
      console.error('[chat] 加载会话列表失败:', err)
    } finally {
      sessionsLoading.value = false
    }
  }

  /** 加载项目列表 */
  const loadProjectList = async () => {
    projectsLoading.value = true
    try {
      const response = await fetchProjectList()
      projects.value = response.data?.data || []
    } catch (err) {
      console.error('[chat] 加载项目列表失败:', err)
    } finally {
      projectsLoading.value = false
    }
  }

  /** 创建项目 */
  const createProject = async (data) => {
    try {
      await createProjectApi(data)
      await loadProjectList()
      ElMessage.success('项目已创建')
    } catch (err) {
      console.error('[chat] 创建项目失败:', err)
      ElMessage.error('创建项目失败')
    }
  }

  /** 更新项目 */
  const updateProject = async (projectId, data) => {
    try {
      await updateProjectApi(projectId, data)
      await loadProjectList()
      ElMessage.success('项目已更新')
    } catch (err) {
      console.error('[chat] 更新项目失败:', err)
      ElMessage.error('更新项目失败')
    }
  }

  /** 删除项目 */
  const deleteProject = async (projectId) => {
    try {
      await deleteProjectApi(projectId)
      await loadProjectList()
      await loadSessionList()
      ElMessage.success('项目已删除')
    } catch (err) {
      console.error('[chat] 删除项目失败:', err)
      ElMessage.error('删除项目失败')
    }
  }

  /** 移动会话到项目 */
  const moveToProject = async (sessionId, projectId) => {
    try {
      await moveSessionToProject(sessionId, projectId)
      await loadSessionList()
      await loadProjectList()
      ElMessage.success('已移动到项目')
    } catch (err) {
      console.error('[chat] 移动会话失败:', err)
      ElMessage.error('移动失败')
    }
  }

  /** 从项目移出会话 */
  const removeFromProject = async (sessionId) => {
    try {
      await removeSessionFromProject(sessionId)
      await loadSessionList()
      await loadProjectList()
      ElMessage.success('已从项目移出')
    } catch (err) {
      console.error('[chat] 移出会话失败:', err)
      ElMessage.error('移出失败')
    }
  }

  /** 切换会话 */
  const switchSession = async (sid) => {
    if (sid === sessionId.value) return
    stopPolling()
    bootstrapped.value = false
    await loadSession(sid, true)
  }

  /** 新建会话 */
  const newSession = async () => {
    stopPolling()
    try {
      const response = await createSession()
      const data = response.data?.data || {}
      sessionId.value = data.sessionId || ''
      sessionTitle.value = data.title || '新对话'
      sessionStatus.value = 'ACTIVE'
      messages.value = data.messages || []
      bootstrapped.value = true
      await loadSessionList()
      ElMessage.success('新对话已创建')
    } catch (err) {
      console.error('[chat] 创建会话失败，完整错误:', err)
      console.error('[chat] 错误响应:', err.response?.status, err.response?.data)
      const errMsg = err.response?.data?.message || err.message || '创建会话失败'
      ElMessage.error(errMsg)
    }
  }

  /** 重命名会话 */
  const renameCurrentSession = async (sid, title) => {
    try {
      await renameSession(sid, title)
      await loadSessionList()
      if (sid === sessionId.value) {
        sessionTitle.value = title
      }
      ElMessage.success('重命名成功')
    } catch (err) {
      console.error('[chat] 重命名会话失败:', err)
      const errMsg = err.response?.data?.message || err.message || '重命名失败'
      ElMessage.error(errMsg)
    }
  }

  /** 归档会话 */
  const archiveCurrentSession = async (sid) => {
    try {
      await archiveSession(sid)
      await loadSessionList()
      if (sid === sessionId.value && sessions.value.length > 0) {
        await loadSession(sessions.value[0].sessionId, true)
      }
      ElMessage.success('会话已归档')
    } catch (err) {
      console.error('[chat] 归档会话失败:', err)
      const errMsg = err.response?.data?.message || err.message || '删除会话失败'
      ElMessage.error(errMsg)
    }
  }

  /** 获取会话消息列表 */
  const fetchSessionMessagesById = async (sid) => {
    try {
      const response = await fetchSessionMessages(sid)
      return response.data?.data || []
    } catch (err) {
      console.error('[chat] 获取会话消息失败:', err)
      return []
    }
  }

  /** 加载 Agent 健康和当前会话 checkpoint */
  const loadDiagnostics = async () => {
    if (!sessionId.value) {
      ElMessage.warning('请先选择一个会话')
      return
    }
    diagnosticsLoading.value = true
    try {
      const [healthResult, checkpointResult] = await Promise.allSettled([
        fetchAgentHealth(),
        fetchSessionCheckpoint(sessionId.value)
      ])
      if (healthResult.status === 'fulfilled') {
        agentHealth.value = healthResult.value.data?.data || null
      }
      if (checkpointResult.status === 'fulfilled') {
        checkpointSnapshot.value = checkpointResult.value.data?.data || null
      }
      if (healthResult.status === 'rejected' && checkpointResult.status === 'rejected') {
        throw healthResult.reason || checkpointResult.reason
      }
      if (healthResult.status === 'rejected' || checkpointResult.status === 'rejected') {
        ElMessage.warning('部分 Agent 诊断信息暂时不可用')
      }
    } catch (err) {
      console.error('[chat] 加载 Agent 诊断失败:', err)
      ElMessage.error(err.response?.data?.message || err.message || '加载 Agent 诊断失败')
    } finally {
      diagnosticsLoading.value = false
    }
  }

  /** 置顶/取消置顶会话 */
  const togglePinSession = async (sid, pinned) => {
    try {
      await togglePinSessionApi(sid, pinned)
      await loadSessionList()
      ElMessage.success(pinned ? '已置顶' : '已取消置顶')
    } catch (err) {
      console.error('[chat] 置顶操作失败:', err)
      const errMsg = err.response?.data?.message || err.message || '操作失败'
      ElMessage.error(errMsg)
    }
  }

  /** 删除会话 */
  const deleteSession = async (sid) => {
    try {
      await deleteSessionApi(sid)
      await loadSessionList()
      if (sid === sessionId.value && sessions.value.length > 0) {
        await loadSession(sessions.value[0].sessionId, true)
      } else if (sessions.value.length === 0) {
        await newSession()
      }
      ElMessage.success('对话已删除')
    } catch (err) {
      console.error('[chat] 删除会话失败:', err)
      const errMsg = err.response?.data?.message || err.message || '删除失败'
      ElMessage.error(errMsg)
    }
  }

  const startPolling = () => {
    stopPolling()
    pollCount = 0
    pollActive = true
    const lastMsgId = messages.value.length > 0
      ? messages.value[messages.value.length - 1]?.id
      : null

    const poll = async () => {
      if (!pollActive) return
      pollCount++
      try {
        const response = await fetchSessionById(sessionId.value)
        const data = response.data?.data || {}
        const newMessages = data.messages || []
        const newLastMsgId = newMessages.length > 0
          ? newMessages[newMessages.length - 1]?.id
          : null
        if (newMessages.length !== messages.value.length || newLastMsgId !== lastMsgId) {
          messages.value = newMessages
          stopPolling()
          return
        }
      } catch (err) {
        console.error('[chat] 轮询消息失败:', err)
      }

      if (pollCount >= MAX_POLL_COUNT) {
        stopPolling()
        return
      }
      pollTimer = setTimeout(poll, POLL_INTERVAL)
    }

    pollTimer = setTimeout(poll, POLL_INTERVAL)
  }

  const stopPolling = () => {
    pollActive = false
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
  }

  const open = async () => {
    visible.value = true
    await bootstrap()
  }

  const close = () => {
    visible.value = false
    stopPolling()
  }

  const buildPageContext = () => ({
    currentRoute: window.location.hash?.replace(/^#/, '') || '/',
    currentPageTitle: document.title || ''
  })

  const sendMessage = async (content) => {
    const text = String(content || '').trim()
    if (!text) {
      ElMessage.warning('请输入聊天内容')
      return
    }

    stopPolling()

    const userMsg = { role: 'user', content: text, messageType: 'TEXT', createdAt: new Date().toISOString() }
    const assistantMsg = {
      role: 'assistant',
      content: '',
      messageType: 'TEXT',
      intent: 'STREAMING',
      createdAt: new Date().toISOString(),
      streaming: true,
      statusText: '正在连接智能助手...',
      statusPlaceholder: true
    }
    messages.value = [...messages.value, userMsg, assistantMsg]

    loading.value = true
    try {
      await streamChatMessage(
        {
          sessionId: sessionId.value,
          content: text,
          ...buildPageContext()
        },
        {
          onStatus: (status) => {
            assistantMsg.statusText = status
            if (!assistantMsg.content) {
              assistantMsg.content = status ? `${status}...` : ''
              assistantMsg.statusPlaceholder = true
            }
            messages.value = [...messages.value]
          },
          onChunk: (chunk) => {
            if (assistantMsg.statusPlaceholder) {
              assistantMsg.content = ''
              assistantMsg.statusPlaceholder = false
            }
            assistantMsg.content += chunk
            assistantMsg.statusText = ''
            messages.value = [...messages.value]
          },
          onDone: (messageResponse) => {
            Object.assign(assistantMsg, {
              ...messageResponse,
              streaming: false,
              statusText: '',
              statusPlaceholder: false
            })
            if (messageResponse?.sessionId) {
              sessionId.value = messageResponse.sessionId
            }
            messages.value = [...messages.value]
          },
          onError: (event) => {
            throw new Error(event?.message || '流式响应失败')
          }
        }
      )
      // 重新加载当前会话消息
      await loadSession(sessionId.value, true)
      // 刷新会话列表（标题可能更新）
      await loadSessionList()
    } catch (error) {
      try {
        const response = await sendChatMessage({
          sessionId: sessionId.value,
          content: text,
          ...buildPageContext()
        })
        Object.assign(assistantMsg, response.data?.data || {}, { streaming: false, statusText: '', statusPlaceholder: false })
        messages.value = [...messages.value]
        await loadSession(sessionId.value, true)
        await loadSessionList()
      } catch (fallbackError) {
        messages.value = messages.value.filter(m => m !== userMsg && m !== assistantMsg)
        ElMessage.error(fallbackError.response?.data?.message || fallbackError.message || error.message || '发送消息失败')
        throw fallbackError
      }
    } finally {
      loading.value = false
    }
  }

  const confirmAction = async (actionId, confirmed) => {
    if (!actionId) return
    if (confirmingActionIds.value.has(actionId)) return
    stopPolling()
    confirmingActionIds.value.add(actionId)
    confirmingActionIds.value = new Set(confirmingActionIds.value)
    loading.value = true
    try {
      await confirmChatAction({
        sessionId: sessionId.value,
        actionId,
        confirmed
      })
      await loadSession(sessionId.value, true)
      startPolling()
    } catch (error) {
      ElMessage.error(error.response?.data?.message || error.message || '执行确认失败')
      throw error
    } finally {
      confirmingActionIds.value.delete(actionId)
      confirmingActionIds.value = new Set(confirmingActionIds.value)
      loading.value = false
    }
  }

  /** 重试最后一条用户消息 */
  const retryLastMessage = async () => {
    const lastUserMsg = [...messages.value].reverse().find(m => m.role === 'user')
    if (!lastUserMsg) {
      ElMessage.warning('没有可重试的消息')
      return
    }
    // 移除最后一条用户消息之后的所有消息（包括失败的AI回复）
    const lastUserIdx = messages.value.lastIndexOf(lastUserMsg)
    messages.value = messages.value.slice(0, lastUserIdx)
    await sendMessage(lastUserMsg.content)
  }

  /** 清空当前会话（创建新会话） */
  const clearConversation = async () => {
    await newSession()
  }

  // 菜单操作
  const toggleMenu = (sessionId) => {
    menuOpenId.value = menuOpenId.value === sessionId ? null : sessionId
  }

  const closeMenu = () => {
    menuOpenId.value = null
  }

  const toggleProjectMenu = (projectId) => {
    projectMenuOpenId.value = projectMenuOpenId.value === projectId ? null : projectId
  }

  const closeProjectMenu = () => {
    projectMenuOpenId.value = null
  }

  return {
    visible,
    sessionId,
    sessionTitle,
    sessionStatus,
    messages,
    loading,
    confirmingActionIds,
    sessions,
    sessionsLoading,
    projects,
    projectsLoading,
    agentHealth,
    checkpointSnapshot,
    diagnosticsLoading,
    menuOpenId,
    projectMenuOpenId,
    bootstrap,
    loadSessionList,
    loadProjectList,
    switchSession,
    newSession,
    archiveCurrentSession,
    renameCurrentSession,
    fetchSessionMessages: fetchSessionMessagesById,
    loadDiagnostics,
    togglePinSession,
    deleteSession,
    createProject,
    updateProject,
    deleteProject,
    moveToProject,
    removeFromProject,
    toggleMenu,
    closeMenu,
    toggleProjectMenu,
    closeProjectMenu,
    open,
    close,
    sendMessage,
    confirmAction,
    retryLastMessage,
    clearConversation
  }
})
