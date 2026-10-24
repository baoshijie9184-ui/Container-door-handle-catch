<template>
  <component
    :is="fullScreen ? 'section' : ElDrawer"
    v-bind="containerProps"
    :class="{ 'chat-workspace': fullScreen }"
    @close="chatStore.close()"
    @update:model-value="handleDrawerChange"
  >
    <div class="chat-panel">
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
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <!-- 左箭头 -->
            <polyline points="7,4 3,10 7,16" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            <!-- 右箭头 -->
            <polyline points="13,4 17,10 13,16" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
      </div>
      <!-- 侧边栏 + 主区域 -->
      <div class="chat-layout" ref="workspaceRef">
        <ChatSidebar :compact="compactSidebar" />
        <div class="chat-main" @click="closeSidebarMenu">
          <!-- 头部 -->
          <header class="chat-header">
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
                <p>检测与质检工作助手</p>
              </div>
            </div>
            <div class="chat-header-actions">
              <button v-if="fullScreen" ref="contextToggleRef" type="button" class="chat-header-btn context-toggle" :aria-label="contextOpen?'收起工作面板':'展开工作面板'" :aria-expanded="contextOpen" aria-controls="chat-workspace-context" @click="contextOpen=!contextOpen"><el-icon><Operation /></el-icon></button>
              <a class="chat-header-btn" :href="'#/agent/trace?sessionId='+encodeURIComponent(chatStore.sessionId || '')" title="查看执行追溯" aria-label="查看执行追溯" @click="chatStore.close()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><path d="M7 6h10M5 8v2a3 3 0 0 0 3 3h4m7-5v2a3 3 0 0 1-3 3h-4v3"/></svg>
              </a>
              <a class="chat-header-btn" href="#/agent/memory" title="个人记忆" aria-label="个人记忆" @click="chatStore.close()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-2H4zM20 4h-4a3 3 0 0 0-3 3v14a4 4 0 0 1 4-2h3z"/></svg>
              </a>
              <button type="button" class="chat-header-btn diagnose-btn" @click="openDiagnostics" :disabled="chatStore.diagnosticsLoading || !chatStore.sessionId" title="助手诊断" aria-label="查看助手诊断">
                <AppIcon name="DataAnalysis" :size="15" />
              </button>
              <button type="button" class="chat-header-btn" @click="handleRetry" :disabled="chatStore.loading" title="重试最后一条消息" aria-label="重试最后一条消息">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
                </svg>
              </button>
              <button type="button" class="chat-header-btn" @click="handleClear" :disabled="chatStore.loading" title="清空对话" aria-label="清空对话">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                </svg>
              </button>
              <button v-if="!fullScreen" class="chat-header-close" @click="chatStore.close()" title="关闭" aria-label="关闭助手">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
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
            <AgentActionList v-if="chatStore.sessionId" :session-id="chatStore.sessionId" :refresh-key="chatStore.loading ? 'running' : chatStore.messages.at(-1)?.id || ''" />
          </div>

          <div v-if="!followTranscript && controlledMessages.length" class="transcript-return">
            <button type="button" @click="returnToLatest"><AppIcon name="ArrowDown" :size="16" />回到最新消息</button>
          </div>

          <ChatQuestionNavigator
            v-if="!controlState.enabled"
            :questions="questionItems"
            :active-key="activeQuestionKey"
            :reset-key="`${chatStore.sessionId}-${chatStore.visible}`"
            @locate="handleLocateQuestion"
          />

          <!-- 输入区 -->
           <ChatComposer ref="composerRef" :active="fullScreen || chatStore.visible" :show-presets="chatStore.messages.length > 0" :loading="chatStore.loading" :session-id="chatStore.sessionId" :run="controlState.run" :model-locked="!!controlState.run&&controlState.run.phase!=='IDLE'" @send="handleSend" @stop="conversationControlsRef?.cancel()"><template #queue><ConversationControls v-if="chatStore.sessionId" ref="conversationControlsRef" :session-id="chatStore.sessionId" @snapshot="controlState=$event" @refresh="chatStore.refreshControlHistory"><template #navigation><ChatQuestionNavigator inline :questions="questionItems" :active-key="activeQuestionKey" :reset-key="`${chatStore.sessionId}-${chatStore.visible}`" @locate="handleLocateQuestion" /></template></ConversationControls></template></ChatComposer>
        </div>
        <button v-if="fullScreen&&contextOpen&&!contextDocked" class="context-scrim" type="button" aria-label="收起工作面板遮罩" @click="closeContext"></button>
        <Transition name="workspace-context">
          <AgentWorkspacePanel v-if="fullScreen&&contextOpen" id="chat-workspace-context" :class="{ 'context-floating': !contextDocked }" :title="chatStore.sessionTitle" :session-id="chatStore.sessionId" :messages="chatStore.messages" @reference="composerRef?.appendReference($event)" :trace="chatStore.executionTrace" :loading="chatStore.diagnosticsLoading" :trace-loaded="chatStore.diagnosticsLoaded.trace" :trace-error="chatStore.diagnosticsErrors.trace" @close="closeContext" @refresh="chatStore.loadDiagnostics" />
        </Transition>
      </div>

      <AgentDiagnostics v-model="diagnosticsVisible" :session-id="chatStore.sessionId" :health="chatStore.agentHealth" :health-loaded="chatStore.diagnosticsLoaded.health" :health-error="chatStore.diagnosticsErrors.health" :trace="chatStore.executionTrace" :trace-loaded="chatStore.diagnosticsLoaded.trace" :trace-error="chatStore.diagnosticsErrors.trace" :loading="chatStore.diagnosticsLoading" @refresh="chatStore.loadDiagnostics" @navigate="chatStore.close()" />
    </div>
  </component>
</template>

<script setup>
import { computed, ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { ElDrawer } from 'element-plus'
import { useChatAssistantStore } from '@/stores/chatAssistant'
import ChatComposer from './ChatComposer.vue'
import ConversationControls from './ConversationControls.vue'
import ChatMessageList from './ChatMessageList.vue'
import AgentActionList from './AgentActionList.vue'
import ChatQuestionNavigator from './ChatQuestionNavigator.vue'
import ChatSidebar from './ChatSidebar.vue'
import AgentWorkspacePanel from './AgentWorkspacePanel.vue'
import AgentDiagnostics from './AgentDiagnostics.vue'
import { Operation } from '@element-plus/icons-vue'
import { buildQuestionItems } from '@/utils/chatMessageNavigation'
import { observeTranscriptLayout } from '@/utils/transcriptLayout'

const props = defineProps({
  fullScreen: { type: Boolean, default: false }
})

const chatStore = useChatAssistantStore()
const conversationControlsRef=ref(null),composerRef=ref(null),controlState=ref({enabled:false,run:null})
const controlledMessages=computed(()=>controlState.value.run?.text&&controlState.value.run.phase!=='IDLE'?[...chatStore.messages,{role:'assistant',content:controlState.value.run.text,messageType:'TEXT',streaming:true}]:chatStore.messages)
const chatBodyRef = ref(null)
const followTranscript = ref(true)
const messageListRef = ref(null)
const activeQuestionKey = ref('')
const resizeTooltip = '拖拽或使用左右方向键调整面板宽度'
const diagnosticsVisible = ref(false)
const workspaceRef=ref(null),contextToggleRef=ref(null),contextOpen=ref(false),workspaceWidth=ref(0)
const contextDocked=computed(()=>workspaceWidth.value>=1000)
watch(()=>controlState.value.run?.phase,phase=>{if(['WAITING_PLAN','WAITING_INPUT','AWAITING_RECOVERY'].includes(phase))contextOpen.value=true})
let workspaceObserver
const closeContext=()=>{contextOpen.value=false;nextTick(()=>contextToggleRef.value?.focus())}
const contextKey=event=>{
  if(event.key!=='Escape')return
  // Capture before the dialog library closes its overlay, including when a
  // disabled PDF paging button has moved focus back to the document body.
  if(event.target?.closest?.('[role="dialog"]')||Array.from(document.querySelectorAll('[role="dialog"][aria-modal="true"]')).some(dialog=>dialog.getClientRects().length>0))return
  if(contextOpen.value&&!diagnosticsVisible.value)closeContext()
}
watch(contextOpen,async open=>{if(open){await nextTick();workspaceRef.value?.querySelector('#chat-workspace-context button')?.focus()}})
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
  if (!visible) activeQuestionKey.value = ''
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
  : { modelValue: chatStore.visible, size: drawerSize.value, appendToBody: true, withHeader: false, direction: 'rtl', class: 'assistant-drawer' })

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

watch([
  () => chatStore.messages.length,
  () => chatStore.messages.at(-1)?.content?.length,
  () => controlState.value.run?.text?.length,
  () => chatStore.loading
], scrollToBottom, { flush: 'post' })
watch(() => chatStore.visible, (val) => {
  if (val) scrollToBottom()
})

const handleSend = async (content) => {
  const currentSession=chatStore.sessionId
  await conversationControlsRef.value?.ready()
  if(chatStore.sessionId!==currentSession)return
  returnToLatest()
  if(controlState.value.enabled){const session=chatStore.sessionId;try{await conversationControlsRef.value.submit(content)}catch{if(chatStore.sessionId===session)composerRef.value?.restoreDraft(content)}return}
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
.chat-workspace :deep(.workspace-context){flex:0 0 288px;width:288px;min-width:0}.chat-workspace :deep(.workspace-context.context-floating){position:absolute;inset:0 0 0 auto;width:min(310px,100%);z-index:26;box-shadow:-12px 0 40px #21355418}.context-scrim{position:absolute;inset:0;border:0;background:#17294036;z-index:25}.workspace-context-enter-active,.workspace-context-leave-active{transition:opacity .18s ease,transform .18s ease}.workspace-context-enter-from,.workspace-context-leave-to{opacity:0;transform:translateX(14px)}
@media(prefers-reduced-motion:reduce){.workspace-context-enter-active,.workspace-context-leave-active{transition:none}}
@media (max-width: 768px) {
  .chat-workspace { border-radius: 12px; }
  .chat-header { padding: 12px 14px; gap: 8px; }
  .chat-header-btn, .chat-header-close { min-width: 32px; min-height: 32px; }
  .chat-heading p { display: none; }
  .chat-header-main { gap: 8px; overflow: hidden; }
  .chat-header-title { font-size: 13px; }
  .chat-header-actions a[title="个人记忆"], .chat-header-actions button[title="清空对话"] { display: none; }
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

.chat-header-btn,
.chat-header-close {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 8px;
  background: #f1f5f9;
  color: #64748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
  flex-shrink: 0;
}

.chat-header-btn:hover,
.chat-header-close:hover {
  background: #e2e8f0;
  color: #334155;
}

.diagnose-btn {
  background: var(--app-primary-soft);
  color: var(--app-primary);
}

.diagnose-btn:hover {
  background: #e8f0ff;
  color: var(--app-primary);
}

.chat-header-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
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
