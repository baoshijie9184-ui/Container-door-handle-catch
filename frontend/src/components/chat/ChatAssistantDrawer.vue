<template>
  <el-drawer
    :model-value="chatStore.visible"
    :size="drawerSize"
    append-to-body
    :with-header="false"
    direction="rtl"
    @close="chatStore.close()"
    @update:model-value="handleDrawerChange"
  >
    <div class="chat-panel">
      <!-- 拖拽手柄 -->
      <div
        v-if="!isMobile"
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
      <div class="chat-layout">
        <ChatSidebar :compact="isMobile" />
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
              <h3 class="chat-header-title">{{ chatStore.sessionTitle }}</h3>
            </div>
            <div class="chat-header-actions">
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
              <button class="chat-header-close" @click="chatStore.close()" title="关闭">
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
              :messages="chatStore.messages"
              :loading="chatStore.loading"
              :confirming-action-ids="chatStore.confirmingActionIds"
              @confirm="handleConfirm"
              @send="handleSend"
            />
          </div>

          <ChatQuestionNavigator
            :questions="questionItems"
            :active-key="activeQuestionKey"
            :reset-key="`${chatStore.sessionId}-${chatStore.visible}`"
            @locate="handleLocateQuestion"
          />

          <!-- 输入区 -->
          <ChatComposer :loading="chatStore.loading" @send="handleSend" />
        </div>
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
            <div class="health-status" :class="`status-${String(chatStore.agentHealth?.healthStatus || 'UNKNOWN').toLowerCase()}`">
              <span class="health-dot"></span>
              <strong>{{ chatStore.agentHealth?.healthStatus || 'UNKNOWN' }}</strong>
              <small>{{ chatStore.agentHealth?.healthMessage || '暂无智能体运行数据' }}</small>
            </div>
            <div class="diagnostic-grid">
              <div>
                <span>{{ chatStore.agentHealth?.totalRuns || 0 }}</span>
                <small>总运行</small>
              </div>
              <div>
                <span>{{ chatStore.agentHealth?.completedRuns || 0 }}</span>
                <small>完成</small>
              </div>
              <div>
                <span>{{ chatStore.agentHealth?.guardBreakRuns || 0 }}</span>
                <small>守卫中断</small>
              </div>
              <div>
                <span>{{ formatRate(chatStore.agentHealth?.fallbackRate) }}</span>
                <small>兜底率</small>
              </div>
            </div>
          </section>

          <section class="checkpoint-card">
            <div class="checkpoint-title">
              <span>当前会话 Checkpoint</span>
              <button @click="chatStore.loadDiagnostics">刷新</button>
            </div>
            <dl>
              <div>
                <dt>版本</dt>
                <dd>{{ chatStore.checkpointSnapshot?.checkpointVersion ?? 0 }}</dd>
              </div>
              <div>
                <dt>节点</dt>
                <dd>{{ chatStore.checkpointSnapshot?.checkpointNode || '暂无' }}</dd>
              </div>
              <div>
                <dt>退出原因</dt>
                <dd>{{ chatStore.checkpointSnapshot?.checkpointExitReason || '暂无' }}</dd>
              </div>
              <div>
                <dt>更新时间</dt>
                <dd>{{ chatStore.checkpointSnapshot?.checkpointUpdatedAt || '暂无' }}</dd>
              </div>
            </dl>
            <p class="guard-reason">
              守卫原因：{{ chatStore.checkpointSnapshot?.guardReason || chatStore.agentHealth?.lastGuardReason || '暂无' }}
            </p>
            <div v-if="routeTrace.length" class="route-trace">
              <span v-for="route in routeTrace" :key="route">{{ route }}</span>
            </div>
          </section>
        </aside>
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useChatAssistantStore } from '@/stores/chatAssistant'
import ChatComposer from './ChatComposer.vue'
import ChatMessageList from './ChatMessageList.vue'
import ChatQuestionNavigator from './ChatQuestionNavigator.vue'
import ChatSidebar from './ChatSidebar.vue'
import { buildQuestionItems } from '@/utils/chatMessageNavigation'

const chatStore = useChatAssistantStore()
const chatBodyRef = ref(null)
const messageListRef = ref(null)
const activeQuestionKey = ref('')
const resizeTooltip = ref('拖拽调整面板宽度')
const diagnosticsVisible = ref(false)
const routeTrace = computed(() => {
  const trace = chatStore.checkpointSnapshot?.routeTrace
  return Array.isArray(trace) ? trace.slice(-8) : []
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
  const width = isMobile.value ? viewportWidth.value : clampPanelWidth(panelWidth.value)
  return `${width}px`
})

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
})
onUnmounted(() => {
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

const formatRate = (value) => {
  const number = Number(value || 0)
  return `${(number * 100).toFixed(1)}%`
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
  background: #fafbfc;
  position: relative;
}

.chat-layout {
  display: flex;
  height: 100%;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
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
  padding: 12px 16px;
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
  background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
  color: #4f6ef7;
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
