<template>
  <div class="action-audit">
    <el-button class="action-audit-toggle" text :disabled="disabled" :aria-expanded="open" :aria-controls="panelId" @click="toggle"><AppIcon name="DocumentChecked" :size="15" />{{ open ? '收起审计' : '查看审计' }}</el-button>
    <Transition name="action-audit">
      <section v-if="open" :id="panelId" class="action-audit-panel" :aria-busy="loading" :aria-labelledby="`${panelId}-title`">
        <header class="action-audit-heading"><strong :id="`${panelId}-title`">操作审计时间线</strong><el-button size="small" :loading="loading" :disabled="disabled" @click="load"><AppIcon name="Refresh" :size="14" />重新读取</el-button></header>
        <p class="action-audit-hint">提议 <code>{{ actionId }}</code> · V{{ revision }}。仅展示本次已读审计；读取失败不代表业务操作失败。</p>
        <p v-if="loading" class="action-audit-read-state" role="status">{{ records ? '正在读取，当前保留上次审计快照。' : '正在读取原操作的审计记录…' }}</p>
        <p v-if="error" class="action-audit-error" role="alert">{{ error }}</p>
        <template v-if="records">
          <p class="action-audit-count">本次已读取 {{ records.length.toLocaleString('zh-CN') }} 条 · 时间均为 UTC+8</p>
          <ol v-if="records.length" class="action-audit-events" tabindex="0" aria-label="操作审计记录，可滚动阅读">
            <li v-for="event in records" :key="event.id" :data-result="event.result">
              <div class="action-audit-event-heading"><strong>{{ actionAuditEvent(event.eventType) }}</strong><StatusBadge domain="confirmation" :code="event.result" :label="actionAuditResult(event.result, operation)" /></div>
              <p class="action-audit-event-meta"><time>{{ formatTime(event.occurredAt) }}</time><span>{{ actionAuditRole(event.actorRole) }}</span></p>
              <p v-if="event.reasonCode" class="action-audit-reason">{{ actionAuditReason(event.reasonCode) }}</p>
            </li>
          </ol>
          <p v-else-if="!loading && !error" class="action-audit-empty">本次未读到审计事件，可重新读取核对。不据此判断原操作没有执行。</p>
        </template>
      </section>
    </Transition>
  </div>
</template>

<script setup>
import { computed, getCurrentInstance, onBeforeUnmount, ref, watch } from 'vue'
import { fetchAgentActionAudit } from '@/api/chatAssistant'
import { useUserStore } from '@/stores/user'
import { beijingDateTime } from '@/utils/beijingTime'
import { validActionAudit, actionAuditEvent, actionAuditResult, actionAuditRole, actionAuditReason } from '@/utils/agentActionAudit'
import '@/assets/agent-action-audit.css'

const props = defineProps({ actionId: { type: String, required: true }, revision: Number, operation: String, scopeKey: String, disabled: Boolean })
const panelId = `action-audit-${getCurrentInstance().uid}`
const userStore = useUserStore()
const actor = computed(() => JSON.stringify([userStore.identity?.userId || userStore.username || '', userStore.role, userStore.isAuthenticated]))
const open = ref(false), loading = ref(false), records = ref(null), error = ref('')
let generation = 0, activeRead = null
const formatTime = value => value ? beijingDateTime(value) || '时间未记录' : '时间未记录'
function stopRead() { generation++; activeRead?.abort(); activeRead = null; loading.value = false }
function reset() { stopRead(); open.value = false; records.value = null; error.value = '' }
function toggle() {
  if (props.disabled) return
  open.value = !open.value
  if (open.value) load()
  else stopRead()
}
async function load() {
  if (props.disabled || activeRead || !open.value) return
  if (!userStore.isAuthenticated) { records.value = null; error.value = '请重新确认登录账号后读取审计。'; return }
  const version = ++generation, controller = new AbortController()
  activeRead = controller; loading.value = true; error.value = ''
  try {
    const { data } = await fetchAgentActionAudit(props.actionId, { signal: controller.signal })
    if (version !== generation) return
    if (!validActionAudit(data)) throw new Error('审计记录格式暂不可核对，请重新读取。')
    records.value = data
  } catch (failure) {
    if (version !== generation || controller.signal.aborted) return
    if ([401, 403, 404].includes(failure.response?.status)) { records.value = null; error.value = '当前账号无法读取该操作的审计，请核对权限及原记录。' }
    else error.value = '审计暂不可读取；已读内容仅为上次快照，请重新读取核对。不会重发业务操作。'
  } finally { if (version === generation) { activeRead = null; loading.value = false } }
}
watch(() => [props.actionId, props.revision, props.scopeKey, actor.value], reset, { flush: 'sync' })
onBeforeUnmount(stopRead)
</script>
