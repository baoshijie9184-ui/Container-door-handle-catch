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
              <a class="chat-header-btn" href="#/agent/memory" title="个人记忆" @click="chatStore.close()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-2H4zM20 4h-4a3 3 0 0 0-3 3v14a4 4 0 0 1 4-2h3z"/></svg>
              </a>
              <button class="chat-header-btn diagnose-btn" @click="openDiagnostics" :disabled="chatStore.diagnosticsLoading" title="Agent诊断">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <path d="M22 12h-4l-3 7-6-14-3 7H2"/>
                  <path d="M17 4h4v4"/>
                </svg>
              </button>
              <button class="chat-header-btn" @click="handleRetry" :disabled="chatStore.loading" title="重试最后一条消息">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
                </svg>
              </button>
              <button class="chat-header-btn" @click="handleClear" :disabled="chatStore.loading" title="清空对话">
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
          <div class="chat-body" ref="chatBodyRef">
            <ChatMessageList
              ref="messageListRef"
              :messages="controlledMessages"
              :loading="chatStore.loading"
              :confirming-action-ids="chatStore.confirmingActionIds"
              @confirm="handleConfirm"
              @send="handleSend"
            />
            <AgentActionList v-if="chatStore.sessionId" :session-id="chatStore.sessionId" :refresh-key="chatStore.loading ? 'running' : chatStore.messages.at(-1)?.id || ''" />
          </div>

          <ChatQuestionNavigator
            v-if="!controlState.enabled"
            :questions="questionItems"
            :active-key="activeQuestionKey"
            :reset-key="`${chatStore.sessionId}-${chatStore.visible}`"
            @locate="handleLocateQuestion"
          />

          <!-- 输入区 -->
           <ConversationControls v-if="chatStore.sessionId" ref="conversationControlsRef" :session-id="chatStore.sessionId" @snapshot="controlState=$event" @refresh="chatStore.refreshControlHistory"><template #navigation><ChatQuestionNavigator inline :questions="questionItems" :active-key="activeQuestionKey" :reset-key="`${chatStore.sessionId}-${chatStore.visible}`" @locate="handleLocateQuestion" /></template></ConversationControls>
           <ChatComposer ref="composerRef" :loading="chatStore.loading" @send="handleSend" />
        </div>
        <button v-if="fullScreen&&contextOpen&&!contextDocked" class="context-scrim" type="button" aria-label="收起工作面板遮罩" @click="closeContext"></button>
        <Transition name="workspace-context">
          <AgentWorkspacePanel v-if="fullScreen&&contextOpen" id="chat-workspace-context" :class="{ 'context-floating': !contextDocked }" :title="chatStore.sessionTitle" :session-id="chatStore.sessionId" :messages="chatStore.messages" @reference="composerRef?.appendReference($event)" :trace="chatStore.executionTrace" :loading="chatStore.diagnosticsLoading" @close="closeContext" @refresh="chatStore.loadDiagnostics" />
        </Transition>
      </div>

      <div v-if="diagnosticsVisible" class="diagnostics-mask" @click.self="diagnosticsVisible = false">
        <aside class="diagnostics-panel" v-loading="chatStore.diagnosticsLoading">
          <header class="diagnostics-head">
            <div>
              <p>Agent Diagnostics</p>
              <h4>智能体运行诊断</h4>
            </div>
            <button class="chat-header-close" @click="diagnosticsVisible = false" title="关闭诊断">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </header>

          <section class="health-card">
            <div class="health-status" :class="['READ_ONLY', 'CONFIRMABLE', 'DRAFTS'].includes(chatStore.agentHealth?.mode) ? 'status-healthy' : 'status-unknown'">
              <span class="health-dot"></span>
              <strong>{{ chatStore.agentHealth?.framework || 'AgentScope' }}</strong>
              <small>{{ chatStore.agentHealth?.reportDraftsEnabled ? '业务查询 · 本人报告草稿 · 审批需页面确认' : chatStore.agentHealth?.mode === 'CONFIRMABLE' ? '业务查询 · 主管分配需人工确认' : chatStore.agentHealth?.mode === 'READ_ONLY' ? '员工与主管角色助手 · 只读查询' : chatStore.agentHealth?.mode === 'DISABLED' ? '助手尚未启用' : '运行状态暂不可用' }}</small>
            </div>
            <div class="diagnostic-grid">
              <div>
                <span>{{ chatStore.agentHealth?.defaultModel || '暂无' }}</span>
                <small>默认模型</small>
              </div>
              <div>
                <span>{{ chatStore.executionTrace?.status || '暂无' }}</span>
                <small>最近执行状态</small>
              </div>
              <div>
                <span>{{ chatStore.executionTrace?.events?.length || 0 }}</span>
                <small>记录事件</small>
              </div>
              <div>
                <span>{{ chatStore.executionTrace?.events?.at(-1)?.elapsedMs ?? '暂无' }}</span>
                <small>最近事件时间 ms</small>
              </div>
            </div>
          </section>

          <section class="checkpoint-card">
            <div class="checkpoint-title">
              <span>最近一次 AgentScope 执行</span>
              <button @click="chatStore.loadDiagnostics">刷新</button>
            </div>
            <dl>
              <div>
                <dt>运行编号</dt>
                <dd>{{ chatStore.executionTrace?.runId || '暂无' }}</dd>
              </div>
              <div>
                <dt>框架</dt>
                <dd>{{ chatStore.executionTrace?.framework || 'AgentScope' }}</dd>
              </div>
              <div>
                <dt>状态</dt>
                <dd>{{ chatStore.executionTrace?.status || '暂无执行记录' }}</dd>
              </div>
              <div>
                <dt>更新时间</dt>
                <dd>{{ chatStore.executionTrace?.updatedAt || '暂无' }}</dd>
              </div>
            </dl>
            <p class="guard-reason">
              仅展示服务器记录的事件，历史对话不会补造调用节点或耗时
            </p>
            <div v-if="routeTrace.length" class="route-trace">
              <span v-for="route in routeTrace" :key="route">{{ route }}</span>
            </div>
          </section>
        </aside>
      </div>
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
import { Operation } from '@element-plus/icons-vue'
import { buildQuestionItems } from '@/utils/chatMessageNavigation'

const props = defineProps({
  fullScreen: { type: Boolean, default: false }
})

const chatStore = useChatAssistantStore()
const conversationControlsRef=ref(null),composerRef=ref(null),controlState=ref({enabled:false,run:null})
const controlledMessages=computed(()=>controlState.value.run?.text&&controlState.value.run.phase!=='IDLE'?[...chatStore.messages,{role:'assistant',content:controlState.value.run.text,messageType:'TEXT',streaming:true}]:chatStore.messages)
const chatBodyRef = ref(null)
const messageListRef = ref(null)
const activeQuestionKey = ref('')
const resizeTooltip = ref('拖拽调整面板宽度')
const diagnosticsVisible = ref(false)
const workspaceRef=ref(null),contextToggleRef=ref(null),contextOpen=ref(false),workspaceWidth=ref(0)
const contextDocked=computed(()=>workspaceWidth.value>=1000)
watch(()=>controlState.value.run?.phase,phase=>{if(['WAITING_PLAN','WAITING_INPUT','AWAITING_RECOVERY'].includes(phase))contextOpen.value=true})
let workspaceObserver
const closeContext=()=>{contextOpen.value=false;nextTick(()=>contextToggleRef.value?.focus())}
const contextKey=event=>{if(event.target?.closest?.('[role="dialog"]')||document.querySelector('.el-overlay-dialog .el-dialog[aria-modal="true"]'))return;if(event.key==='Escape'&&contextOpen.value&&!diagnosticsVisible.value)closeContext()}
watch(contextOpen,async open=>{if(open){await nextTick();workspaceRef.value?.querySelector('#chat-workspace-context button')?.focus()}})
const routeTrace = computed(() => {
  const trace = chatStore.executionTrace?.events
  return Array.isArray(trace) ? trace.slice(-8).map(event => `${event.type} · ${event.tool || event.agent}`) : []
})
const questionItems = computed(() => buildQuestionItems(chatStore.messages))

const handleLocateQuestion = (key) => {
  if (messageListRef.value?.locateMessage(key)) activeQuestionKey.value = key
}

watch(() => chatStore.sessionId, () => {
  activeQuestionKey.value = ''
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

const startResize = (e) => {
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
  window.addEventListener('resize', handleViewportResize)
  window.addEventListener('keydown',contextKey)
  if(props.fullScreen&&workspaceRef.value){workspaceObserver=new ResizeObserver(entries=>{workspaceWidth.value=entries[0].contentRect.width});workspaceObserver.observe(workspaceRef.value)}
})
onUnmounted(() => {
  workspaceObserver?.disconnect();window.removeEventListener('keydown',contextKey)
  window.removeEventListener('resize', handleViewportResize)
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
  document.removeEventListener('touchmove', onTouchMove)
  document.removeEventListener('touchend', onTouchEnd)
})

// ─── 滚动到底部 ───
const scrollToBottom = () => {
  nextTick(() => {
    if (chatBodyRef.value) {
      chatBodyRef.value.scrollTop = chatBodyRef.value.scrollHeight
    }
  })
}

watch(() => chatStore.messages.length, scrollToBottom)
watch(() => chatStore.visible, (val) => {
  if (val) scrollToBottom()
})

const handleSend = async (content) => {
  const currentSession=chatStore.sessionId
  await conversationControlsRef.value?.ready()
  if(chatStore.sessionId!==currentSession)return
  if(controlState.value.enabled){const session=chatStore.sessionId;try{await conversationControlsRef.value.submit(content)}catch{if(chatStore.sessionId===session)composerRef.value?.restoreDraft(content)}return}
  await chatStore.sendMessage(content)
  scrollToBottom()
}

const handleConfirm = async (actionId, confirmed) => {
  await chatStore.confirmAction(actionId, confirmed)
  scrollToBottom()
}

const handleRetry = async () => {
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
  transition: all 0.25s;
}

.resize-knob:hover {
  background: #4f6ef7;
  color: #fff;
  height: 56px;
  box-shadow: 0 0 8px rgba(79, 110, 247, 0.3);
}

.resize-knob:active {
  background: #3b5de7;
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
  background: #ecfeff;
  color: #0891b2;
}

.diagnose-btn:hover {
  background: #cffafe;
  color: #0e7490;
}

.chat-header-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ── Agent 诊断 ── */
.diagnostics-mask {
  position: absolute;
  inset: 0;
  z-index: 30;
  display: flex;
  justify-content: flex-end;
  background: rgba(15, 23, 42, 0.18);
  backdrop-filter: blur(2px);
}

.diagnostics-panel {
  width: min(360px, 92%);
  height: 100%;
  padding: 16px;
  display: grid;
  align-content: start;
  gap: 14px;
  background:
    linear-gradient(180deg, rgba(248, 250, 252, 0.98), rgba(255, 255, 255, 0.98)),
    radial-gradient(circle at top right, rgba(6, 182, 212, 0.12), transparent 42%);
  border-left: 1px solid rgba(148, 163, 184, 0.24);
  box-shadow: -18px 0 40px rgba(15, 23, 42, 0.12);
}

.diagnostics-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.diagnostics-head p {
  margin: 0 0 4px;
  color: #0891b2;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.diagnostics-head h4 {
  margin: 0;
  color: #0f172a;
  font-size: 17px;
}

.health-card,
.checkpoint-card {
  padding: 13px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(226, 232, 240, 0.92);
  box-shadow: 0 10px 26px rgba(15, 23, 42, 0.05);
}

.health-status {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 8px;
  align-items: center;
  padding: 10px;
  border-radius: 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.health-status strong {
  color: #0f172a;
  font-size: 14px;
}

.health-status small {
  grid-column: 2;
  color: #64748b;
  line-height: 1.5;
}

.health-dot {
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: #94a3b8;
  box-shadow: 0 0 0 5px rgba(148, 163, 184, 0.14);
}

.status-healthy .health-dot { background: #16a34a; box-shadow: 0 0 0 5px rgba(22, 163, 74, 0.14); }
.status-warn .health-dot { background: #d97706; box-shadow: 0 0 0 5px rgba(217, 119, 6, 0.14); }
.status-critical .health-dot { background: #dc2626; box-shadow: 0 0 0 5px rgba(220, 38, 38, 0.14); }

.diagnostic-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.diagnostic-grid div {
  padding: 10px;
  border-radius: 13px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.diagnostic-grid span {
  display: block;
  color: #0f172a;
  font-size: 18px;
  font-weight: 900;
}

.diagnostic-grid small {
  display: block;
  margin-top: 3px;
  color: #64748b;
  font-size: 11px;
}

.checkpoint-title {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  margin-bottom: 10px;
}

.checkpoint-title span {
  color: #0f172a;
  font-size: 13px;
  font-weight: 850;
}

.checkpoint-title button {
  min-height: 30px;
  padding: 5px 10px;
  border: 1px solid #bae6fd;
  border-radius: 999px;
  background: #f0f9ff;
  color: #0369a1;
  font-size: 12px;
  cursor: pointer;
}

.checkpoint-card dl {
  display: grid;
  gap: 8px;
  margin: 0;
}

.checkpoint-card dl div {
  display: grid;
  grid-template-columns: 70px 1fr;
  gap: 8px;
  align-items: start;
}

.checkpoint-card dt {
  color: #94a3b8;
  font-size: 11px;
}

.checkpoint-card dd {
  margin: 0;
  color: #334155;
  font-size: 12px;
  word-break: break-word;
}

.guard-reason {
  margin: 12px 0 0;
  padding: 9px 10px;
  border-radius: 12px;
  background: #fff7ed;
  border: 1px dashed #fed7aa;
  color: #9a3412;
  font-size: 12px;
  line-height: 1.5;
}

.route-trace {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.route-trace span {
  padding: 4px 7px;
  border-radius: 999px;
  background: #eef2ff;
  color: #4338ca;
  font-size: 10.5px;
  font-weight: 750;
}

/* ── 消息区 ── */
.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 20px 8px;
  scroll-behavior: smooth;
}

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
