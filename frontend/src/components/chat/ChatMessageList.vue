<template>
  <div class="msg-list" ref="listRef">
    <!-- 空状态 / 欢迎 -->
    <div v-if="messages.length === 0" class="msg-empty">
      <div class="empty-glow"></div>
      <div class="empty-avatar">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 2a4 4 0 0 1 4 4v2a4 4 0 0 1-8 0V6a4 4 0 0 1 4-4z"/>
          <path d="M8 12h8a4 4 0 0 1 4 4v2a4 4 0 0 1-8 0"/>
          <path d="M12 12v4"/>
          <circle cx="8" cy="8" r="1" fill="currentColor"/>
          <circle cx="16" cy="8" r="1" fill="currentColor"/>
          <rect x="8" y="16" width="8" height="4" rx="2"/>
        </svg>
      </div>
      <p class="empty-title">工业检测助手在线</p>
      <p class="empty-desc">我可以串联采集检测、缺陷证据、质检闭环、模型 MLOps、追溯报表和系统运维</p>

      <div class="empty-section">
        <p class="empty-section-label">常用操作</p>
        <div class="empty-chips">
          <button class="empty-chip action" @click="$emit('send', '上传本地图片文件夹进行检测')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
            上传检测
          </button>
          <button class="empty-chip action" @click="$emit('send', '开始检测')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            开始检测
          </button>
          <button class="empty-chip action" @click="$emit('send', '查看待复核质检队列和返工复检任务')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
            质检队列
          </button>
          <button class="empty-chip action danger" @click="$emit('send', '查看严重缺陷证据')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M10.3 3.5 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.5a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
            严重缺陷
          </button>
        </div>
      </div>

      <div class="empty-section">
        <p class="empty-section-label">一站式闭环</p>
        <div class="empty-chips">
          <button class="empty-chip trace" @click="$emit('send', '缺陷证据库在哪个页面')">缺陷证据库</button>
          <button class="empty-chip trace" @click="$emit('send', '查询批次 BATCH-001 的追溯报告')">批次追溯</button>
          <button class="empty-chip trace" @click="$emit('send', '查询工单 WO-001 的检测闭环')">工单追溯</button>
          <button class="empty-chip trace" @click="$emit('send', '查看 Agent checkpoint 和健康状态')">Agent健康</button>
        </div>
      </div>

      <div class="empty-section">
        <p class="empty-section-label">快速查询</p>
        <div class="empty-chips">
          <button class="empty-chip" @click="$emit('send', '显示系统业务地图和功能入口')">业务地图</button>
          <button class="empty-chip" @click="$emit('send', '查看当前设备在线状态和采集告警')">设备采集</button>
          <button class="empty-chip" @click="$emit('send', '查看模型评估指标、灰度发布和回滚状态')">模型MLOps</button>
          <button class="empty-chip" @click="$emit('send', '生成本周质量处置统计和质检工作量报表')">质量报表</button>
          <button class="empty-chip" @click="$emit('send', '检查OSS、Kafka和远程Worker运行状态')">运维链路</button>
        </div>
      </div>
    </div>

    <!-- 消息列表 -->
    <template v-for="(item, idx) in messages" :key="item.id || `${item.role}-${item.createdAt}-${idx}`">
      <div
        class="msg-row"
        :data-message-key="buildChatMessageKey(item, idx)"
        :class="item.role === 'user' ? 'is-user' : 'is-assistant'"
        :style="{ animationDelay: `${Math.min(idx * 40, 300)}ms` }"
      >
        <!-- 助手头像 -->
        <div v-if="item.role !== 'user'" class="msg-avatar assistant-avatar">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 2a4 4 0 0 1 4 4v2a4 4 0 0 1-8 0V6a4 4 0 0 1 4-4z"/>
            <path d="M8 12h8a4 4 0 0 1 4 4v2a4 4 0 0 1-8 0"/>
            <path d="M12 12v4"/>
            <circle cx="8" cy="8" r="1" fill="currentColor"/>
            <circle cx="16" cy="8" r="1" fill="currentColor"/>
            <rect x="8" y="16" width="8" height="4" rx="2"/>
          </svg>
        </div>

        <div class="msg-body">
          <!-- PendingAction 卡片 -->
          <ChatPendingActionCard
            v-if="item.messageType === 'PENDING_ACTION'"
            :message="item"
            :busy="confirmingActionIds.has(item.actionId)"
            @confirm="handleConfirm"
          />

          <ChatBusinessCard
            v-else-if="item.messageType === 'BUSINESS_CARD'"
            :message="item"
            @send="emit('send', $event)"
          />

          <!-- 普通消息气泡 -->
          <div v-else class="msg-bubble" :class="item.role">
            <div class="msg-content" v-html="formatMessage(messageBodyContent(item.content))"></div>
            <div v-if="messageSourceText(item.content)" class="msg-source-strip">
              <span class="msg-source-label">来源</span>
              <span class="msg-source-chip">{{ messageSourceText(item.content) }}</span>
            </div>
          </div>

          <!-- 时间 -->
          <div class="msg-time" v-if="item.createdAt">
            {{ formatTime(item.createdAt) }}
          </div>
        </div>

        <!-- 用户头像 -->
        <div v-if="item.role === 'user'" class="msg-avatar user-avatar">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
            <circle cx="12" cy="7" r="4"/>
          </svg>
        </div>
      </div>
    </template>

    <!-- 打字指示器 -->
    <div v-if="loading && messages.length > 0 && !messages.some(m => m.streaming)" class="msg-row is-assistant">
      <div class="msg-avatar assistant-avatar">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 2a4 4 0 0 1 4 4v2a4 4 0 0 1-8 0V6a4 4 0 0 1 4-4z"/>
          <path d="M8 12h8a4 4 0 0 1 4 4v2a4 4 0 0 1-8 0"/>
          <path d="M12 12v4"/>
          <circle cx="8" cy="8" r="1" fill="currentColor"/>
          <circle cx="16" cy="8" r="1" fill="currentColor"/>
          <rect x="8" y="16" width="8" height="4" rx="2"/>
        </svg>
      </div>
      <div class="msg-body">
        <div class="typing-indicator">
          <span class="typing-dot"></span>
          <span class="typing-dot"></span>
          <span class="typing-dot"></span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onUnmounted, ref } from 'vue'
import ChatBusinessCard from './ChatBusinessCard.vue'
import ChatPendingActionCard from './ChatPendingActionCard.vue'
import { buildChatMessageKey } from '@/utils/chatMessageNavigation'

defineProps({
  messages: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  confirmingActionIds: { type: Object, default: () => new Set() }
})

const emit = defineEmits(['confirm', 'send'])
const listRef = ref(null)
let highlightTimer = null

const locateMessage = (key) => {
  const target = Array.from(listRef.value?.querySelectorAll('[data-message-key]') || [])
    .find(element => element.dataset.messageKey === key)
  if (!target) return false
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  target.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'center' })
  if (highlightTimer) window.clearTimeout(highlightTimer)
  listRef.value?.querySelector('.question-locate-highlight')?.classList.remove('question-locate-highlight')
  target.classList.add('question-locate-highlight')
  highlightTimer = window.setTimeout(() => {
    target.classList.remove('question-locate-highlight')
    highlightTimer = null
  }, 1500)
  return true
}

defineExpose({ locateMessage })
onUnmounted(() => {
  if (highlightTimer) window.clearTimeout(highlightTimer)
})

const handleConfirm = (actionId, confirmed) => {
  emit('confirm', actionId, confirmed)
}

const SOURCE_PATTERN = /(?:^|\n)\s*来源[:：]\s*(.+?)\s*$/

const messageSourceText = (content) => {
  const match = String(content || '').match(SOURCE_PATTERN)
  return match ? match[1].trim() : ''
}

const messageBodyContent = (content) => {
  return String(content || '').replace(SOURCE_PATTERN, '').trimEnd()
}

const formatTime = (val) => {
  if (!val) return ''
  try {
    const d = new Date(val)
    if (isNaN(d.getTime())) return val
    const h = d.getHours().toString().padStart(2, '0')
    const m = d.getMinutes().toString().padStart(2, '0')
    return `${h}:${m}`
  } catch {
    return val
  }
}

/** 轻量 markdown → HTML */
const formatMessage = (text) => {
  if (!text) return ''
  let html = escapeHtml(text)

  // 代码块 ```...```
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    return `<pre class="msg-code-block"><code>${code.trim()}</code></pre>`
  })

  // 行内代码 `...`
  html = html.replace(/`([^`]+)`/g, '<code class="msg-inline-code">$1</code>')

  // 粗体 **...**
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')

  // 站内路由链接 [页面](#/path)
  html = html.replace(/\[([^\]]+)]\((#\/[A-Za-z0-9/_?=&.-]+)\)/g, '<a class="msg-route-link" href="$2">$1</a>')

  // 无序列表 - item
  html = html.replace(/(^|\n)- (.+?)(?=\n(?!- )|\n*$)/g, (match, prefix, items) => {
    const lines = match.trim().split('\n').filter(l => l.startsWith('- '))
    const lis = lines.map(l => `<li>${l.substring(2)}</li>`).join('')
    return `<ul class="msg-list">${lis}</ul>`
  })

  // 有序列表 1. item
  html = html.replace(/(^|\n)\d+\. (.+?)(?=\n(?!\d+\. )|\n*$)/g, (match) => {
    const lines = match.trim().split('\n').filter(l => /^\d+\./.test(l))
    const lis = lines.map(l => `<li>${l.replace(/^\d+\.\s*/, '')}</li>`).join('')
    return `<ol class="msg-list">${lis}</ol>`
  })

  // 换行
  html = html.replace(/\n/g, '<br>')

  return html
}

const escapeHtml = (str) => {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}
</script>

<style scoped>
.msg-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* ── 空状态 ── */
.msg-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px 12px;
  text-align: center;
  position: relative;
}

.empty-glow {
  position: absolute;
  top: 0;
  width: 120px;
  height: 120px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(79, 110, 247, 0.08) 0%, transparent 70%);
  pointer-events: none;
}

.empty-avatar {
  width: 52px;
  height: 52px;
  border-radius: 16px;
  background: linear-gradient(135deg, #eef2ff, #e0e7ff);
  color: #4f6ef7;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
  position: relative;
  z-index: 1;
}

.empty-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
}

.empty-desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: #94a3b8;
}

.empty-section {
  width: 100%;
  margin-top: 16px;
}

.empty-section-label {
  margin: 0 0 8px;
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.empty-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: center;
}

.empty-chip {
  min-height: 34px;
  padding: 7px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  color: #475569;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  display: flex;
  align-items: center;
  gap: 5px;
}

.empty-chip:hover {
  border-color: #4f6ef7;
  color: #4f6ef7;
  background: #f8faff;
}

.empty-chip.action {
  background: linear-gradient(135deg, #eef2ff, #e0e7ff);
  border-color: #c7d2fe;
  color: #4338ca;
  font-weight: 500;
}

.empty-chip.action:hover {
  background: linear-gradient(135deg, #e0e7ff, #c7d2fe);
  border-color: #a5b4fc;
}

.empty-chip.action.danger {
  background: linear-gradient(135deg, #fff1f2, #ffe4e6);
  border-color: #fecdd3;
  color: #be123c;
}

.empty-chip.action.danger:hover {
  background: linear-gradient(135deg, #ffe4e6, #fecdd3);
  border-color: #fda4af;
}

.empty-chip.trace {
  background: #f8fafc;
  border-color: #dbeafe;
  color: #1d4ed8;
  font-weight: 600;
}

.empty-chip.trace:hover {
  background: #eff6ff;
  border-color: #93c5fd;
}

/* ── 消息行 ── */
.msg-row {
  display: flex;
  gap: 8px;
  padding: 2px 0;
  animation: msg-in 0.3s cubic-bezier(0.4, 0, 0.2, 1) both;
}

.msg-row.question-locate-highlight {
  border-radius: 18px;
  outline: 2px solid rgba(79, 110, 247, 0.42);
  outline-offset: 4px;
  background: rgba(79, 110, 247, 0.08);
  transition: background-color 0.25s ease, outline-color 0.25s ease;
}

@keyframes msg-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .msg-row { animation: none; }
  .msg-row.question-locate-highlight { transition: none; }
}

.is-user { flex-direction: row-reverse; }
.is-assistant { flex-direction: row; }

.msg-avatar {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  align-self: flex-start;
  margin-top: 2px;
}

.assistant-avatar {
  background: linear-gradient(135deg, #eef2ff, #e0e7ff);
  color: #4f6ef7;
}

.user-avatar {
  background: linear-gradient(135deg, #dbeafe, #bfdbfe);
  color: #2563eb;
}

.msg-body {
  max-width: 85%;
  display: flex;
  flex-direction: column;
}

.is-user .msg-body { align-items: flex-end; }
.is-assistant .msg-body { align-items: flex-start; }

.msg-time {
  font-size: 10px;
  color: #b0b8c4;
  margin-top: 3px;
  padding: 0 4px;
}

.msg-bubble {
  border-radius: 16px;
  padding: 10px 14px;
  line-height: 1.6;
  font-size: 13.5px;
}

.msg-bubble.assistant {
  background: #ffffff;
  color: #1e293b;
  border-bottom-left-radius: 4px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.msg-bubble.user {
  background: linear-gradient(135deg, #4f6ef7 0%, #3b5de7 100%);
  color: #fff;
  border-bottom-right-radius: 4px;
  box-shadow: 0 2px 6px rgba(47, 107, 255, 0.18);
}

.msg-content {
  word-break: break-word;
}

.msg-source-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 9px;
  padding-top: 8px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
}

.msg-source-label {
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
}

.msg-source-chip {
  padding: 2px 8px;
  border: 1px solid rgba(20, 184, 166, 0.26);
  border-radius: 999px;
  background: rgba(20, 184, 166, 0.08);
  color: #0f766e;
  font-size: 11px;
  font-weight: 700;
}

/* ── Markdown 样式 ── */
.msg-content :deep(strong) {
  font-weight: 700;
  color: #0f172a;
}

.msg-bubble.user .msg-content :deep(strong) {
  color: #fff;
}

.msg-content :deep(.msg-code-block) {
  background: #f1f5f9;
  border-radius: 8px;
  padding: 10px 12px;
  margin: 6px 0;
  overflow-x: auto;
  font-size: 12px;
  line-height: 1.5;
}

.msg-content :deep(.msg-code-block code) {
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
  color: #334155;
}

.msg-content :deep(.msg-inline-code) {
  background: #f1f5f9;
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 12px;
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
  color: #e11d48;
}

.msg-content :deep(.msg-route-link) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin: 0 2px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #eff6ff;
  color: #2563eb;
  font-weight: 700;
  text-decoration: none;
  border: 1px solid #bfdbfe;
  transition: all 0.18s;
}

.msg-content :deep(.msg-route-link:hover) {
  background: #dbeafe;
  border-color: #60a5fa;
  transform: translateY(-1px);
}

.msg-content :deep(ul.msg-list),
.msg-content :deep(ol.msg-list) {
  margin: 4px 0;
  padding-left: 18px;
}

.msg-content :deep(.msg-list li) {
  margin: 2px 0;
  line-height: 1.5;
}

/* ── 打字指示器 ── */
.typing-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 12px 16px;
  background: #ffffff;
  border-radius: 16px;
  border-bottom-left-radius: 4px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.typing-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #94a3b8;
  animation: typing-bounce 1.4s ease-in-out infinite;
}

.typing-dot:nth-child(2) { animation-delay: 0.2s; }
.typing-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-5px); opacity: 1; }
}
</style>
