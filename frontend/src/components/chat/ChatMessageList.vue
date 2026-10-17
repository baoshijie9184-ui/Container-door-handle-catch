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
      <span class="welcome-eyebrow">DOORHANDLE ASSISTANT</span>
      <h2 class="empty-title">今天有什么需要我协助？</h2>
      <p class="empty-desc">从检测到质检追溯，用对话连接你的工作</p>
      <div class="welcome-prompts">
        <button v-for="prompt in welcomePrompts" :key="prompt.title" class="welcome-prompt" @click="$emit('send', prompt.query)">
          <span class="prompt-icon"><el-icon><component :is="prompt.icon" /></el-icon></span>
          <strong>{{ prompt.title }}</strong><span>{{ prompt.description }}</span>
          <el-icon class="prompt-arrow"><TopRight /></el-icon>
        </button>
      </div>
      <p class="welcome-note">按当前账号权限查询 · 输入 / 调用已启用技能</p>
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

          <AgentResultCards v-else-if="item.messageType === 'AGENT_CARDS'" :message="item" />

          <ChatBusinessCard
            v-else-if="item.messageType === 'BUSINESS_CARD'"
            :message="item"
            @send="emit('send', $event)"
          />

          <!-- 普通消息气泡 -->
          <div v-else class="msg-bubble" :class="item.role">
            <div class="msg-content" v-html="formatMessage(splitFileReferences(messageBodyContent(item.content),item.role).text)"></div>
            <ChatFileReferences v-if="splitFileReferences(item.content,item.role).ids.length" :session-id="sessionId" :ids="splitFileReferences(item.content,item.role).ids" />
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
import { skillInstallNavigation } from '../../utils/skillInstallNavigation'
import { onUnmounted, ref } from 'vue'
import { Search, CircleCheck, DataAnalysis, Guide, TopRight } from '@element-plus/icons-vue'
import ChatBusinessCard from './ChatBusinessCard.vue'
import ChatFileReferences from './ChatFileReferences.vue'
import {splitFileReferences} from '@/utils/chatFileReferences'
import {beijingClock} from '@/utils/beijingTime'
import AgentResultCards from './AgentResultCards.vue'
import ChatPendingActionCard from './ChatPendingActionCard.vue'
import { buildChatMessageKey } from '@/utils/chatMessageNavigation'

defineProps({
  sessionId:String,
  messages: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  confirmingActionIds: { type: Object, default: () => new Set() }
})

const emit = defineEmits(['confirm', 'send'])
const welcomePrompts = [
  { title: '查看检测进度', description: '找到最近任务与处理状态', query: '查询最近的检测任务和处理进度', icon: Search },
  { title: '梳理质检记录', description: '汇总有权限查看的质检结果', query: '查询我有权限查看的质检记录', icon: CircleCheck },
  { title: '了解工作统计', description: '整理本周检测与缺陷情况', query: '查询本周工作统计和缺陷数量', icon: DataAnalysis },
  { title: '找到业务入口', description: '查看批次、工单与报告入口', query: '显示系统业务地图和功能入口', icon: Guide },
]

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

const formatTime = beijingClock

/** 轻量 markdown → HTML */
const formatMessage = (text) => {
  if (!text) return ''
  const install = skillInstallNavigation(text, window.location.href)
  if (install) text = install.before + '[' + install.label + '](' + install.route + ')' + install.after
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
  html = html.replace(/\[([^\]]+)]\((#\/agent\/skills\?installUrl=[A-Za-z0-9%_.+-]+)\)/g, '<a class="msg-route-link" href="$2">$1</a>')
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
  gap: 24px;
}

/* ── 空状态 ── */
.msg-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 320px;
  padding: 32px 8px 24px;
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
  color: #2563eb;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
  position: relative;
  z-index: 1;
}

.empty-title {
  margin: 10px 0 8px;
  font-size: clamp(21px, 2.1vw, 30px);
  font-weight: 650;
  letter-spacing: -.04em;
  color: #14223a;
}

.empty-desc {
  margin: 0;
  font-size: 13px;
  color: #68768a;
}

.welcome-eyebrow { margin-top: 6px; color: #2563eb; letter-spacing: .13em; font-size: 10px; font-weight: 700; }
.welcome-prompts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; width: 100%; max-width: 600px; margin-top: 28px; }
.welcome-prompt { position: relative; display: grid; grid-template-columns: 32px minmax(0, 1fr); gap: 5px 10px; padding: 18px; background: white; border: 1px solid #e7ebf1; border-radius: 14px; text-align: left; cursor: pointer; transition: border-color .18s, background .18s, transform .18s; }
.welcome-prompt:hover { border-color: #a9c6ff; background: #f8faff; transform: translateY(-2px); }
.welcome-prompt:active { transform: scale(.98); }
.welcome-prompt strong { font-size: 13px; font-weight: 600; color: #24354e; padding-right: 10px; }
.welcome-prompt > span:not(.prompt-icon) { grid-column: 2; font-size: 11px; line-height: 1.6; color: #68768a; }
.prompt-icon { grid-row: span 2; display: grid; place-items: center; width: 32px; height: 32px; color: #2563eb; background: #eef4ff; border-radius: 9px; }
.prompt-arrow { position: absolute; top: 18px; right: 14px; color: #8190a5; }
.welcome-note { margin-top: 20px; font-size: 11px; color: #68768a; }
@media (max-width: 540px) { .welcome-prompts { grid-template-columns: 1fr; margin-top: 20px; } .welcome-prompt { padding: 12px 14px; } .msg-empty { padding-top: 12px; } }

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
  color: #2563eb;
}

.user-avatar {
  background: linear-gradient(135deg, #dbeafe, #bfdbfe);
  color: #2563eb;
}

.msg-body {
  max-width: calc(100% - 40px);
  min-width: 0;
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
  font-size: 14px;
  overflow-wrap: anywhere;
}

.msg-bubble.assistant {
  background: #ffffff;
  color: #1e293b;
  border-bottom-left-radius: 4px;
  box-shadow: none;
}

.msg-bubble.user {
  background: #eff4fc;
  color: #1e293b;
  border-bottom-right-radius: 4px;
  box-shadow: none;
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
