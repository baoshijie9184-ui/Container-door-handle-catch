<template>
  <component
    :is="fullScreen ? 'section' : ElDrawer"
    v-bind="containerProps"
    :class="{ 'chat-workspace': fullScreen }"
    @close="chatStore.close()"
    @update:model-value="handleDrawerChange"
  >
    <div class="chat-panel" :class="{ 'drawer-panel': !fullScreen }">
      <!-- 拖拽手柄 -->
      <div
        v-if="!isMobile && !fullScreen"
        class="resize-handle"
        role="separator"
        tabindex="0"
        aria-label="调整助手面板宽度"
        aria-orientation="vertical"
        :aria-valuemin="MIN_WIDTH"
        :aria-valuemax="maxPanelWidth"
        :aria-valuenow="clampPanelWidth(panelWidth)"
        :aria-valuetext="`${clampPanelWidth(panelWidth)} 像素，左右方向键调整，Home 最窄，End 最宽`"
        @keydown="resizeWithKeyboard"
        @mousedown.prevent="startResize"
        @touchstart.prevent="startResizeTouch"
      >
        <div class="resize-knob" :title="resizeTooltip">
          <svg width="10" height="20" viewBox="0 0 10 20" fill="none" aria-hidden="true">
            <path d="M3 5v10M7 5v10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
          </svg>
        </div>
      </div>
      <!-- 侧边栏 + 主区域 -->
      <div class="chat-layout" :class="{ 'compact-history': compactSidebar }" ref="workspaceRef">
        <ChatSidebar :compact="compactSidebar">
          <template v-if="!fullScreen" #footer="{ collapsed }">
            <div class="drawer-sidebar-actions" :class="{ compact: collapsed }">
              <ChatConversationMenu :tasks-enabled="controlState.enabled" workspace-enabled :show-label="!collapsed" placement="top-start" @command="handleMenuCommand" />
              <button type="button" class="drawer-sidebar-close" title="关闭助手" aria-label="关闭助手" @click="chatStore.close()">
                <AppIcon name="Close" :size="16" /><span v-if="!collapsed">关闭助手</span>
              </button>
            </div>
          </template>
        </ChatSidebar>
        <div class="chat-main" @click="closeSidebarMenu">
          <!-- 头部 -->
          <header v-if="fullScreen" class="chat-header">
            <div class="chat-header-main">
              <div class="chat-avatar ai">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 2a4 4 0 0 1 4 4v2a4 4 0 0 1-8 0V6a4 4 0 0 1 4-4z"/>
                  <path d="M8 12h8a4 4 0 0 1 4 4v2a4 4 0 0 1-8 0"/>
                  <path d="M12 12v4"/>
                  <circle cx="8" cy="8" r="1" fill="currentColor"/>
                  <circle cx="16" cy="8" r="1" fill="currentColor"/>
                  <rect x="8" y="16" width="8" height="4" rx="2"/>
                </svg>
              </div>
              <div class="chat-heading">
                <h3 class="chat-header-title">{{ chatStore.sessionTitle }}</h3>
              </div>
            </div>
            <div class="chat-header-actions">
              <button ref="contextToggleRef" type="button" class="chat-header-btn context-toggle" :aria-expanded="contextOpen" :aria-controls="contextOpen ? 'chat-workspace-context' : undefined" @click="contextOpen ? closeContext() : contextOpen = true"><el-icon aria-hidden="true"><Operation /></el-icon><span>任务与资料</span></button>
              <ChatConversationMenu :tasks-enabled="controlState.enabled" @command="handleMenuCommand" />
            </div>
          </header>

          <!-- 消息区 -->
          <div class="chat-body transcript-reading-region" ref="chatBodyRef" tabindex="0" role="region" aria-label="对话消息，可在此区域滚动阅读" @scroll.passive="handleTranscriptScroll">
            <ChatMessageList
              ref="messageListRef"
              :messages="controlledMessages"
              :session-id="chatStore.sessionId"
              :loading="chatStore.loading"
              :confirming-action-ids="chatStore.confirmingActionIds"
              @confirm="handleConfirm"
              @send="handleSend"
            />
            <AgentActionList v-if="chatStore.sessionId" compact :session-id="chatStore.sessionId" :refresh-key="chatStore.loading ? 'running' : chatStore.messages.at(-1)?.id || ''" />
          </div>

          <div v-if="!followTranscript && controlledMessages.length" class="transcript-return">
            <button type="button" @click="handleReturnToLatest"><AppIcon name="ArrowDown" :size="16" />回到最新消息</button>
          </div>

          <ChatQuestionNavigator
            v-if="!controlState.enabled"
            :questions="questionItems"
            :active-key="activeQuestionKey"
            :reset-key="`${chatStore.sessionId}-${chatStore.visible}`"
            @locate="handleLocateQuestion"
          />

          <!-- 输入区 -->
           <ChatComposer ref="composerRef" :active="fullScreen || chatStore.visible" :show-presets="chatStore.messages.length > 0" :loading="chatStore.loading || chatStore.openingFirstSession" :session-id="chatStore.sessionId" :run="controlState.run" :model-locked="!!controlState.run&&controlState.run.phase!=='IDLE'" @send="handleSend" @stop="conversationControlsRef?.cancel()"><template #queue><ConversationControls v-if="chatStore.sessionId" ref="conversationControlsRef" :session-id="chatStore.sessionId" @snapshot="controlState=$event" @refresh="chatStore.refreshControlHistory"><template #navigation><ChatQuestionNavigator inline :questions="questionItems" :active-key="activeQuestionKey" :reset-key="`${chatStore.sessionId}-${chatStore.visible}`" @locate="handleLocateQuestion" /></template></ConversationControls></template></ChatComposer>
        </div>
        <button v-if="contextOpen&&!contextDocked" class="context-scrim" type="button" tabindex="-1" aria-label="收起工作面板遮罩" @click="closeContext"></button>
        <Transition name="workspace-context">
          <AgentWorkspacePanel v-if="contextOpen" id="chat-workspace-context" :class="{ 'context-floating': !contextDocked }" :session-id="chatStore.sessionId" :messages="chatStore.messages" :task-attention="taskAttention" @reference="composerRef?.appendReference($event)" :trace="chatStore.executionTrace" :loading="chatStore.diagnosticsLoading" :trace-loaded="chatStore.diagnosticsLoaded.trace" :trace-error="chatStore.diagnosticsErrors.trace" @close="closeContext" @refresh="chatStore.loadDiagnostics" />
        </Transition>
      </div>

      <AgentDiagnostics v-model="diagnosticsVisible" :session-id="chatStore.sessionId" :health="chatStore.agentHealth" :health-loaded="chatStore.diagnosticsLoaded.health" :health-error="chatStore.diagnosticsErrors.health" :trace="chatStore.executionTrace" :trace-loaded="chatStore.diagnosticsLoaded.trace" :trace-error="chatStore.diagnosticsErrors.trace" :loading="chatStore.diagnosticsLoading" @refresh="chatStore.loadDiagnostics" @navigate="chatStore.close()" />
    </div>
  </component>
</template>

<script setup>
import { accountSession } from '../../utils/accountContext'
import { computed, ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { ElDrawer } from 'element-plus'
import { useRouter } from 'vue-router'
import { useChatAssistantStore } from '@/stores/chatAssistant'
import ChatComposer from './ChatComposer.vue'
import ConversationControls from './ConversationControls.vue'
import ChatMessageList from './ChatMessageList.vue'
import AgentActionList from './AgentActionList.vue'
import ChatQuestionNavigator from './ChatQuestionNavigator.vue'
import ChatSidebar from './ChatSidebar.vue'
import ChatConversationMenu from './ChatConversationMenu.vue'
import AgentWorkspacePanel from './AgentWorkspacePanel.vue'
import AgentDiagnostics from './AgentDiagnostics.vue'
import { Operation } from '@element-plus/icons-vue'
import { buildQuestionItems } from '@/utils/chatMessageNavigation'
import { observeTranscriptLayout } from '@/utils/transcriptLayout'
import { hasForegroundDialog, keepTabInWorkspace } from '@/utils/workspaceFocus'

const props = defineProps({
  fullScreen: { type: Boolean, default: false }
})

const chatStore = useChatAssistantStore()
const router = useRouter()
const conversationControlsRef=ref(null),composerRef=ref(null),controlState=ref({enabled:false,run:null})
const controlledMessages=computed(()=>controlState.value.run?.runId&&controlState.value.run.phase!=='IDLE'?[...chatStore.messages,{role:'assistant',content:controlState.value.run.text,messageType:'TEXT',streaming:true,runId:controlState.value.run.runId}]:chatStore.messages)
const chatBodyRef = ref(null)
const followTranscript = ref(true)
const messageListRef = ref(null)
const activeQuestionKey = ref('')
const resizeTooltip = '拖拽或使用左右方向键调整面板宽度'
const diagnosticsVisible = ref(false)
const workspaceRef=ref(null),contextToggleRef=ref(null),contextOpen=ref(false),workspaceWidth=ref(0)
const contextDocked=computed(()=>props.fullScreen&&workspaceWidth.value>=1000)
const taskAttention=computed(()=>{
  const run=controlState.value.run
  return run&&['WAITING_PLAN','WAITING_INPUT','AWAITING_RECOVERY'].includes(run.phase) ? `${run.runId}:${run.phase}` : ''
})
watch(taskAttention,value=>{if(value&&(props.fullScreen||chatStore.visible))contextOpen.value=true})
let workspaceObserver
const closeContext=()=>{
  if(!contextOpen.value)return
  contextOpen.value=false
  nextTick(()=>(contextToggleRef.value||workspaceRef.value?.querySelector('.drawer-sidebar-actions .chat-menu-button'))?.focus({preventScroll:true}))
}
const contextElement = () => workspaceRef.value?.querySelector('#chat-workspace-context')
const contextKey=event=>{
  if (!contextOpen.value || !['Escape', 'Tab'].includes(event.key)) return
  const panel = contextElement()
  if (!panel || diagnosticsVisible.value || hasForegroundDialog(panel, event.target)) return
  if (event.target?.closest?.('[role="menu"], [role="listbox"], [aria-haspopup="menu"][aria-expanded="true"]')) return
  if (event.key === 'Tab' && !contextDocked.value) keepTabInWorkspace(event, panel)
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    closeContext()
  }
}
watch(contextOpen, async open => {
  if (!open) return
  await nextTick()
  const panel = contextElement()
  if (panel && !hasForegroundDialog(panel)) panel.querySelector('button')?.focus({ preventScroll: true })
})
const questionItems = computed(() => buildQuestionItems(chatStore.messages))

const handleLocateQuestion = (key) => {
  const wasFollowing = followTranscript.value
  followTranscript.value = false
  if (messageListRef.value?.locateMessage(key)) activeQuestionKey.value = key
  else followTranscript.value = wasFollowing
}

watch(() => chatStore.sessionId, () => {
  activeQuestionKey.value = ''
  followTranscript.value = true
  scrollToBottom()
})
watch(() => chatStore.visible, (visible) => {
  if (!visible) {
    activeQuestionKey.value = ''
    if (!props.fullScreen) contextOpen.value = false
  }
})

// 关闭侧边栏菜单
const closeSidebarMenu = () => {
  chatStore.closeMenu()
  chatStore.closeProjectMenu()
}

// ─── 面板宽度拖拽调整 ───
const STORAGE_KEY = 'chat_panel_width'
const MIN_WIDTH = 360
const DEFAULT_WIDTH = 440
const MOBILE_BREAKPOINT = 768

const viewportWidth = ref(window.innerWidth)
const panelWidth = ref(DEFAULT_WIDTH)
let resizing = false

const isMobile = computed(() => viewportWidth.value <= MOBILE_BREAKPOINT)
const maxPanelWidth = computed(() => Math.min(1200, Math.floor(viewportWidth.value * 0.75)))
const clampPanelWidth = (width) => Math.min(
  maxPanelWidth.value,
  Math.max(MIN_WIDTH, width)
)
const drawerSize = computed(() => {
  if (props.fullScreen) return '100%'
  const width = isMobile.value ? viewportWidth.value : clampPanelWidth(panelWidth.value)
  return `${width}px`
})
const compactSidebar=computed(()=>isMobile.value||(!props.fullScreen&&clampPanelWidth(panelWidth.value)<700))
const containerProps = computed(() => props.fullScreen
  ? { 'aria-label': '智能对话工作区' }
  : { modelValue: chatStore.visible, title: '智能助手', size: drawerSize.value, appendToBody: true, withHeader: false, direction: 'rtl', class: 'assistant-drawer' })

const loadPanelWidth = () => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      const val = parseInt(saved, 10)
      if (Number.isFinite(val)) panelWidth.value = clampPanelWidth(val)
    }
  } catch { /* ignore */ }
}

const savePanelWidth = () => {
  try {
    localStorage.setItem(STORAGE_KEY, String(panelWidth.value))
  } catch { /* ignore */ }
}

const resizeWithKeyboard = event => {
  if (props.fullScreen || isMobile.value || event.altKey || event.ctrlKey || event.metaKey) return
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const step = event.shiftKey ? 64 : 16
  const current = clampPanelWidth(panelWidth.value)
  panelWidth.value = event.key === 'Home' ? MIN_WIDTH : event.key === 'End' ? maxPanelWidth.value : clampPanelWidth(current + (event.key === 'ArrowLeft' ? step : -step))
  savePanelWidth()
}

const startResize = (e) => {
  e.currentTarget?.focus({ preventScroll:true })
  resizing = true
  document.body.style.cursor = 'ew-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
}

const startResizeTouch = (e) => {
  resizing = true
  document.addEventListener('touchmove', onTouchMove, { passive: false })
  document.addEventListener('touchend', onTouchEnd)
  document.addEventListener('touchcancel', onTouchEnd)
}

const onMouseMove = (e) => {
  if (!resizing) return
  const newWidth = window.innerWidth - e.clientX
  panelWidth.value = clampPanelWidth(newWidth)
}

const onMouseUp = () => {
  resizing = false
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
  savePanelWidth()
}

const onTouchMove = (e) => {
  if (!resizing) return
  e.preventDefault()
  const touch = e.touches[0]
  const newWidth = window.innerWidth - touch.clientX
  panelWidth.value = clampPanelWidth(newWidth)
}

const onTouchEnd = () => {
  resizing = false
  document.removeEventListener('touchmove', onTouchMove)
  document.removeEventListener('touchend', onTouchEnd)
  document.removeEventListener('touchcancel', onTouchEnd)
  savePanelWidth()
}

const handleViewportResize = () => {
  viewportWidth.value = window.innerWidth
  if (!isMobile.value) {
    panelWidth.value = clampPanelWidth(panelWidth.value)
    savePanelWidth()
  }
}

onMounted(() => {
  loadPanelWidth()
  scrollToBottom()
  window.addEventListener('resize', handleViewportResize)
  window.addEventListener('keydown',contextKey,true)
  if(props.fullScreen&&workspaceRef.value){workspaceObserver=new ResizeObserver(entries=>{workspaceWidth.value=entries[0].contentRect.width});workspaceObserver.observe(workspaceRef.value)}
})
onUnmounted(() => {
  workspaceObserver?.disconnect();window.removeEventListener('keydown',contextKey,true)
  window.removeEventListener('resize', handleViewportResize)
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
  document.removeEventListener('touchmove', onTouchMove)
  document.removeEventListener('touchend', onTouchEnd)
  document.removeEventListener('touchcancel', onTouchEnd)
  if (resizing) { document.body.style.cursor = ''; document.body.style.userSelect = ''; resizing = false }
})

// Follow new output only while the reader is already near the bottom.
const handleTranscriptScroll = () => {
  const body = chatBodyRef.value
  if (body) followTranscript.value = body.scrollHeight - body.scrollTop - body.clientHeight < 72
}

const scrollToBottom = () => {
  const sessionId = chatStore.sessionId
  nextTick(() => {
    if (followTranscript.value && sessionId === chatStore.sessionId && chatBodyRef.value) {
      chatBodyRef.value.scrollTop = controlledMessages.value.length ? chatBodyRef.value.scrollHeight : 0
    }
  })
}

watch([chatBodyRef, () => chatStore.sessionId], ([viewport], _previous, onCleanup) => {
  onCleanup(observeTranscriptLayout(viewport, {
    isFollowing: () => followTranscript.value,
    follow: scrollToBottom
  }))
}, { flush: 'post' })

const returnToLatest = () => {
  followTranscript.value = true
  scrollToBottom()
}

// This focus move belongs only to the explicit reading control, never new output.
const handleReturnToLatest = () => {
  returnToLatest()
  nextTick(()=>chatBodyRef.value?.focus({preventScroll:true}))
}

watch([
  () => chatStore.messages.length,
  () => chatStore.messages.at(-1)?.content?.length,
  () => controlState.value.run?.text?.length,
  () => chatStore.loading
], scrollToBottom, { flush: 'post' })
watch(() => chatStore.visible, (val) => {
  if (val) scrollToBottom()
})

const handleSend = async (content, guideRunId) => {
  const account=accountSession.stamp()
  const currentSession=chatStore.sessionId
  await conversationControlsRef.value?.ready()
  accountSession.assert(account)
  if(chatStore.sessionId!==currentSession)return
  returnToLatest()
  if(controlState.value.enabled || guideRunId){const session=chatStore.sessionId;try{if(guideRunId)await conversationControlsRef.value.guide(content,guideRunId);else await conversationControlsRef.value.submit(content)}catch{if(chatStore.sessionId===session)composerRef.value?.restoreDraft(content)}return}
  await chatStore.sendMessage(content)
  scrollToBottom()
}

const handleConfirm = async (actionId, confirmed) => {
  await chatStore.confirmAction(actionId, confirmed)
  scrollToBottom()
}

const handleRetry = async () => {
  returnToLatest()
  await chatStore.retryLastMessage()
  scrollToBottom()
}

const handleClear = async () => {
  await chatStore.clearConversation()
  scrollToBottom()
}

const openDiagnostics = async () => {
  diagnosticsVisible.value = true
  await chatStore.loadDiagnostics()
}

const handleMenuCommand = command => {
  if (command === 'workspace') { contextOpen.value = true; return }
  if (command === 'tasks') return conversationControlsRef.value?.openOptions()
  if (command === 'trace' || command === 'memory') {
    chatStore.close()
    return router.push(command === 'trace' ? {path:'/agent/trace',query:{sessionId:chatStore.sessionId || ''}} : '/agent/memory')
  }
  if (command === 'diagnostics' && !chatStore.diagnosticsLoading && chatStore.sessionId) return openDiagnostics()
  if (command === 'retry' && !chatStore.loading) return handleRetry()
  if (command === 'clear' && !chatStore.loading) return handleClear()
}

const handleDrawerChange = (value) => {
  if (value) {
    chatStore.open()
  } else {
    chatStore.close()
  }
}
</script>

<style scoped>
.chat-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  position: relative;
}

.chat-layout {
  display: flex;
  height: 100%;
  min-height: 0;
  position: relative;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  position: relative;
}

/* ── 拖拽手柄 ── */
.resize-handle {
  position: absolute;
  left: -16px;
  top: 0;
  bottom: 0;
  width: 32px;
  cursor: col-resize;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
}

.resize-knob {
  width: 22px;
  height: 48px;
  border-radius: 6px;
  background: #e2e8f0;
  color: #94a3b8;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: col-resize;
  transition: background-color 180ms ease, color 180ms ease, box-shadow 180ms ease;
}

.resize-knob:hover {
  background: var(--app-primary);
  color: #fff;
  box-shadow: 0 0 8px rgba(79, 110, 247, 0.3);
}

.resize-handle:focus-visible { outline:2px solid var(--app-primary); outline-offset:-3px; border-radius:6px; }
.resize-handle:focus-visible .resize-knob { background:var(--app-primary-soft); color:var(--app-primary); }

.resize-knob:active {
  background: var(--app-primary);
}

/* ── 头部 ── */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 22px;
  background: #fff;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
  flex-shrink: 0;
}

.chat-header-main {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.chat-avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.chat-avatar.ai {
  background: #eff5ff;
  color: #2563eb;
}

.chat-heading { min-width: 0; }
.chat-heading p { margin: 3px 0 0; font-size: 11px; color: #64748b; }
.chat-workspace { height: 100%; min-height: 0; overflow: hidden; border: 1px solid var(--app-border); border-radius: 18px; background: white; }
.chat-workspace .chat-body { padding: 24px clamp(16px, 3vw, 48px) 12px; }
.chat-workspace :deep(.msg-list), .chat-workspace :deep(.agent-actions) { max-width: 820px; margin-inline: auto; width: 100%; }
.chat-workspace :deep(.composer) { padding: 12px clamp(16px, 3vw, 48px) 16px; }
.chat-workspace :deep(.composer > *) { max-width: 820px; margin-inline: auto; }
.chat-workspace :deep(.slash-menu) { max-width: min(820px, calc(100% - 32px)); }
.chat-workspace :deep(.chat-sidebar) { width: 236px; }
.chat-workspace :deep(.chat-sidebar.collapsed) { width: 42px; }
.chat-layout :deep(.workspace-context){flex:0 0 340px;width:340px;min-width:0}
.chat-layout :deep(.workspace-context.context-floating){position:absolute;inset:0 0 0 auto;width:min(380px,100%);z-index:26;box-shadow:-12px 0 40px #21355418}
.context-scrim{position:absolute;inset:0;border:0;background:#17294036;z-index:25}
.workspace-context-enter-active,.workspace-context-leave-active{transition:opacity .18s ease,transform .18s ease}
.workspace-context-enter-from,.workspace-context-leave-to{opacity:0;transform:translateX(14px)}
@media(prefers-reduced-motion:reduce){.workspace-context-enter-active,.workspace-context-leave-active{transition:none}}
@media (max-width: 768px) {
  .chat-workspace { border-radius: 12px; }
  .chat-header { padding: 12px 14px; gap: 8px; }
  .chat-header-main { gap: 8px; overflow: hidden; }
  .chat-header-title { font-size: 13px; }
}

.chat-header-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.chat-header-btn {
  min-height: 36px;
  padding: 0 10px;
  gap: 6px;
  border: none;
  border-radius: 8px;
  background: var(--app-surface-muted);
  color: var(--app-text);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font: inherit;
  font-size: 13px;
  white-space: nowrap;
  flex-shrink: 0;
}

.chat-header-btn:hover,
.chat-header-btn[aria-expanded=true] {
  background: var(--app-primary-soft);
  color: var(--app-primary);
}

/* The reading column changes width independently of the browser and the history pane. */
.drawer-panel .chat-main { container: drawer-conversation / inline-size; }
.drawer-panel :deep(.chat-sidebar.collapsed) { width: 52px; }
.drawer-panel :deep(.chat-sidebar.collapsed .sidebar-toggle) {
  top: 10px; right: 4px; width: 32px; height: 32px;
  border: 0; border-radius: 8px; background: transparent; box-shadow: none;
}
.drawer-panel :deep(.chat-sidebar.collapsed .sidebar-toggle:hover) { background: var(--app-primary-soft); }
.drawer-sidebar-actions {
  margin-top: auto; padding: 7px 10px; display: flex; flex: none; align-items: center;
  justify-content: space-between; gap: 4px; border-top: 1px solid var(--app-border);
}
.drawer-sidebar-actions.compact { flex-direction: column; align-items: flex-end; padding: 8px 4px; }
.drawer-sidebar-close, .drawer-sidebar-actions :deep(.chat-menu-button) {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  min-width: 32px; min-height: 32px; padding: 0 6px; border: 0; border-radius: 8px;
  background: transparent; color: var(--app-text-secondary); font: inherit; font-size: 12px; cursor: pointer;
}
.drawer-sidebar-close:hover, .drawer-sidebar-actions :deep(.chat-menu-button:hover) {
  background: var(--app-primary-soft); color: var(--app-primary);
}
.drawer-sidebar-close:focus-visible, .drawer-panel :deep(.sidebar-toggle:focus-visible) {
  outline: 2px solid var(--app-primary); outline-offset: -2px;
}
@media (max-width: 768px) {
  .drawer-panel :deep(.chat-sidebar.collapsed) { width: 42px; }
}
.drawer-panel .resize-handle { left: 0; width: 12px; }
.drawer-panel .resize-knob { width: 10px; height: 36px; border-radius: 5px; }

@container drawer-conversation (max-width: 560px) {
  .drawer-panel .chat-body { padding: 16px 14px 8px; }
  .drawer-panel :deep(.composer) { padding: 8px 12px 12px; }
  .drawer-panel :deep(.gpt-composer-input) {
    min-height: 88px; padding: 10px; gap: 4px; border-radius: 15px;
  }
  .drawer-panel :deep(.composer-textarea) { min-height: 34px; }
  .drawer-panel :deep(.composer-toolbar) { gap: 4px; }
  .drawer-panel :deep(.composer-context), .drawer-panel :deep(.composer-permission) { display: none; }
  .drawer-panel :deep(.composer-toolbar select) {
    flex: 1; min-width: 0; max-width: 235px; padding-inline: 6px;
    background: var(--app-surface-muted); color: var(--app-text);
  }
}

/* ── 消息区 ── */
.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 20px 8px;
  scroll-behavior: auto;
}

.transcript-return { display: flex; justify-content: center; height: 0; position: relative; z-index: 2; }
.transcript-return button { display: inline-flex; align-items: center; gap: 6px; position: absolute; bottom: 12px; padding: 8px 14px; color: var(--app-primary, #2563eb); background: white; border: 1px solid var(--app-border, #e2e8f0); border-radius: 20px; box-shadow: 0 3px 12px #0f172a0d; font: inherit; font-size: 12px; cursor: pointer; transition: background-color 150ms ease, border-color 150ms ease; }
.transcript-return button:hover { background: var(--app-primary-soft, #eff6ff); border-color: #b6cdfa; }
.transcript-return button:focus-visible { outline: 2px solid var(--app-primary, #2563eb); outline-offset: 3px; }

.chat-body::-webkit-scrollbar {
  width: 5px;
}

.chat-body::-webkit-scrollbar-track {
  background: transparent;
}

.chat-body::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 999px;
}

.chat-body::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}
</style>
