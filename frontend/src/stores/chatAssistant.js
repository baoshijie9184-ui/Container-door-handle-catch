import { defineStore } from 'pinia'
import { ref, watch, onScopeDispose } from 'vue'
import { ElMessage } from 'element-plus'
import {
  archiveSession,
  confirmChatAction,
  createSession,
  deleteSession as deleteSessionApi,
  fetchAgentHealth,
  fetchChatSession,
  fetchSessionTrace,
  fetchSessionById,
  fetchSessionList,
  fetchSessionMessages,
  renameSession,
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
  const sessionsError = ref('')
  let sessionListRequest = 0

  // 项目
  const projects = ref([])
  const projectsLoading = ref(false)

  // Agent 诊断
  const agentHealth = ref(null)
  const executionTrace = ref(null)
  const diagnosticsLoading = ref(false)
  const diagnosticsErrors = ref({ health:'', trace:'' })
  const diagnosticsLoaded = ref({ health:false, trace:false })
  let diagnosticsRequest = 0
  const resetDiagnostics = () => {
    diagnosticsRequest++
    agentHealth.value = null; executionTrace.value = null
    diagnosticsErrors.value = { health:'', trace:'' }
    diagnosticsLoaded.value = { health:false, trace:false }
    diagnosticsLoading.value = false
  }
  watch(sessionId, resetDiagnostics, { flush:'sync' })
  onScopeDispose(resetDiagnostics)

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
      resetDiagnostics()
      sessionId.value = data.sessionId || sid
      sessionTitle.value = data.title || '智能助手'
      sessionStatus.value = data.status || 'ACTIVE'
      messages.value = data.messages || []
      bootstrapped.value = true
    } finally {
      loading.value = false
    }
  }

  const refreshControlHistory = async sid => {
    try{
      const response=await fetchSessionById(sid)
      if(sessionId.value!==sid)return
      const data=response.data?.data
      if(data&&Array.isArray(data.messages)){messages.value=data.messages;sessionTitle.value=data.title||sessionTitle.value}
    }catch{if(sessionId.value===sid)ElMessage.warning('会话消息暂不可读取，请刷新核对')}
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
    const request = ++sessionListRequest
    sessionsLoading.value = true
    sessionsError.value = ''
    try {
      const response = await fetchSessionList()
      if (request !== sessionListRequest) return
      const rows = response.data?.data
      if (!Array.isArray(rows) || rows.some(row => !row || typeof row.sessionId !== 'string')) throw new Error('会话列表格式异常')
      sessions.value = rows
    } catch (err) {
      if (request !== sessionListRequest) return
      if ([401, 403].includes(err.response?.status)) sessions.value = []
      sessionsError.value = '会话列表暂不可读取，请重新读取。已有列表可能不是最新状态。'
    } finally {
      if (request === sessionListRequest) sessionsLoading.value = false
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
      const response = await createProjectApi(data)
      if(response.data?.code!==200 || typeof response.data?.data?.projectId!=='string' || !response.data.data.projectId.trim())throw new Error('项目保存回执未完整返回')
      await loadProjectList()
      ElMessage.success('项目已创建')
      return {acknowledged:true}
    } catch (err) {
      console.error('[chat] 创建项目失败:', err)
      ElMessage.warning('创建结果待核对，请刷新项目列表')
      return {acknowledged:false}
    }
  }

  /** 更新项目 */
  const updateProject = async (projectId, data) => {
    try {
      const response = await updateProjectApi(projectId, data)
      if(response.data?.code!==200 || String(response.data?.data?.projectId)!==String(projectId))throw new Error('项目保存回执未完整返回')
      await loadProjectList()
      ElMessage.success('项目已更新')
      return {acknowledged:true}
    } catch (err) {
      console.error('[chat] 更新项目失败:', err)
      ElMessage.warning('更新结果待核对，请刷新项目列表')
      return {acknowledged:false}
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
      return { acknowledged: true }
    } catch (err) {
      console.error('[chat] 重命名会话失败:', err)
      const errMsg = err.response?.data?.message || err.message || '重命名失败'
      ElMessage.error(errMsg)
      const status = err.response?.status
      return { acknowledged: false, uncertain: !status || status === 408 || status >= 500 }
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

  /** 加载 AgentScope 状态和当前会话执行轨迹 */
  const loadDiagnostics = async () => {
    if (!sessionId.value) {
      ElMessage.warning('请先选择一个会话')
      return
    }
    if (diagnosticsLoading.value) return
    diagnosticsLoading.value = true
    const sid = sessionId.value
    const requestId = ++diagnosticsRequest
    agentHealth.value = null; executionTrace.value = null
    diagnosticsErrors.value = { health:'', trace:'' }
    diagnosticsLoaded.value = { health:false, trace:false }
    try {
      const [healthResult, traceResult] = await Promise.allSettled([
        fetchAgentHealth(),
        fetchSessionTrace(sid)
      ])
      if (requestId !== diagnosticsRequest || sessionId.value !== sid) return
      if (healthResult.status === 'fulfilled') {
        const body = healthResult.value.data, data = body?.data
        if (body?.code === 200 && data && typeof data.framework === 'string' && typeof data.mode === 'string' && (data.defaultModel == null || typeof data.defaultModel === 'string')) {
          agentHealth.value = data; diagnosticsLoaded.value.health = true
        } else diagnosticsErrors.value.health = '服务配置信息未完整读取，请重新核对'
      } else {
        diagnosticsErrors.value.health = healthResult.reason?.response?.data?.message || '服务配置暂不可读取，请重试'
      }
      if (traceResult.status === 'fulfilled') {
        const body = traceResult.value.data, data = body?.data
        const validTrace = data?.sessionId === sid && ['runId','status','updatedAt','framework'].every(key => data[key] == null || typeof data[key] === 'string') && Array.isArray(data.events) && data.events.every(event => event && typeof event.type === 'string' && event.type.trim())
        if (body?.code === 200 && validTrace) {
          executionTrace.value = data; diagnosticsLoaded.value.trace = true
          if (data.status === 'UNAVAILABLE') diagnosticsErrors.value.trace = '已保存的会话轨迹暂不可解析，请打开执行追溯核对'
        } else diagnosticsErrors.value.trace = '会话轨迹未完整读取，请重新核对'
      } else {
        diagnosticsErrors.value.trace = traceResult.reason?.response?.data?.message || '会话轨迹暂不可读取，请重试'
      }
    } catch {
      if (requestId === diagnosticsRequest && sessionId.value === sid) {
        diagnosticsErrors.value = { health:'服务配置读取未完成，请重试', trace:'会话轨迹读取未完成，请重试' }
      }
    } finally {
      if (requestId === diagnosticsRequest) diagnosticsLoading.value = false
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
    if (!loading.value && bootstrapped.value && sessionId.value) {
      await loadSession(sessionId.value, true)
      await loadSessionList()
    } else await bootstrap()
  }

  const close = () => {
    visible.value = false
    stopPolling()
  }

  const refreshOnFocus = () => {
    if (visible.value && !loading.value && sessionId.value) {
      loadSession(sessionId.value, true).catch(() => ElMessage.error('会话刷新失败 请重新打开助手'))
    }
  }
  window.addEventListener('focus', refreshOnFocus)
  onScopeDispose(() => window.removeEventListener('focus', refreshOnFocus))

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
      assistantMsg.streaming = false
      assistantMsg.statusText = ''
      assistantMsg.statusPlaceholder = false
      messages.value = [...messages.value]
      try {
        await loadSession(sessionId.value, true)
        await loadSessionList()
      } catch (_) { /* 保留当前显示，用户可手动刷新会话 */ }
      ElMessage.error(error.response?.data?.message || error.message || '发送消息失败')
      throw error
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
    sessionsError,
    projects,
    projectsLoading,
    agentHealth,
    executionTrace,
    diagnosticsLoading,
    diagnosticsErrors,
    diagnosticsLoaded,
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
    refreshControlHistory,
    confirmAction,
    retryLastMessage,
    clearConversation
  }
})
