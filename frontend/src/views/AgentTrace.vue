<template>
  <section class="agent-trace-page app-panel">
    <header class="trace-header">
      <div><h2>AgentScope 调用轨迹</h2><p>服务器记录的执行事件与运行历史</p></div>
      <div><el-button :loading="store.diagnosticsLoading" @click="refresh">刷新</el-button><el-button type="primary" :disabled="!events.length || hasMoreEvents" @click="exportTrace">导出轨迹</el-button></div>
    </header>
    <div class="trace-content">
      <aside>
        <h3>会话</h3>
        <button v-for="session in store.sessions" :key="session.sessionId" class="session-button" :class="{ active: session.sessionId === store.sessionId }" @click="selectSession(session.sessionId)">
          <strong>{{ session.title || '新对话' }}</strong><small>{{ session.messageCount || 0 }} 条消息</small>
        </button>
      </aside>
      <main>
        <template v-if="store.agentHealth?.runJournalEnabled">
          <div class="history-toolbar">
            <el-switch v-model="allRuns" active-text="全部入口运行" aria-label="全部入口运行" @change="changeHistoryScope" />
            <el-select v-model="selectedRunId" placeholder="选择运行" :loading="historyLoading" @change="loadRun">
              <el-option v-for="run in runs" :key="run.runId" :value="run.runId" :label="`${run.startedAt} · ${run.entryPoint} · ${run.status}`" />
            </el-select>
            <el-button :disabled="!hasMoreRuns" :loading="historyLoading" @click="loadRuns(true)">更早运行</el-button>
            <el-button v-if="selectedRun?.status === 'RUNNING'" type="danger" :loading="cancelling" @click="cancelRun">取消运行</el-button>
          </div>
          <p v-if="historyError" role="alert" class="history-error">{{ historyError }}</p>
          <p class="journal-note">事件按序号补读 不会重新执行模型或工具</p>
        </template>
        <div class="trace-summary"><el-tag>{{ store.agentHealth?.framework || 'AgentScope' }}</el-tag><span>{{ displayStatus }}</span><small>{{ displayUpdatedAt }}</small></div>
        <p v-if="store.agentHealth?.runJournalEnabled ? selectedRunId : store.executionTrace?.runId" class="run-id">运行编号 {{ selectedRunId || store.executionTrace.runId }}</p>
        <el-table v-if="events.length" :data="events" stripe>
          <el-table-column label="序号" width="70"><template #default="{ row, $index }">{{ row.sequence || $index + 1 }}</template></el-table-column>
          <el-table-column prop="type" label="事件" min-width="150" />
          <el-table-column label="技能 / 命令" min-width="180"><template #default="{ row }">{{ row.skillId ? row.skillId + ' · v' + row.version : row.command || '—' }}</template></el-table-column>
          <el-table-column prop="agent" label="Agent" min-width="160" />
          <el-table-column prop="tool" label="工具" min-width="150" />
          <el-table-column prop="callId" label="调用编号" min-width="140" />
          <el-table-column prop="result" label="结果" min-width="110" />
          <el-table-column prop="elapsedMs" label="运行后 ms" width="130" />
        </el-table>
        <el-button v-if="hasMoreEvents" :loading="eventsLoading" @click="loadMoreEvents">补读后续事件</el-button>
        <el-empty v-if="!events.length" description="此会话暂无 AgentScope 轨迹，历史对话不会补造调用节点或耗时" />
        <p v-if="selectedRun" class="journal-note">入口 {{ selectedRun.entryPoint }} · 会话 {{ selectedRun.sessionId }} · 默认模型 {{ selectedRun.defaultModel || '未记录' }}</p>
        <AgentActionList v-if="selectedRunId" :run-id="selectedRunId" />
        <h3>{{ selectedRun && selectedRun.sessionId !== store.sessionId ? '此运行的消息不在当前主站会话中' : '会话消息' }}</h3>
        <div v-for="message in displayedMessages" :key="message.id" class="message-item" :class="message.role"><el-tag size="small">{{ message.role === 'user' ? '用户' : '助手' }}</el-tag><p>{{ message.content }}</p></div>
      </main>
    </div>
  </section>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchAgentRuns, fetchAgentRun, fetchAgentRunEvents, cancelAgentRun } from '@/api/chatAssistant'
import { useChatAssistantStore } from '@/stores/chatAssistant'
import AgentActionList from '@/components/chat/AgentActionList.vue'
const store = useChatAssistantStore()
const route = useRoute()
const runs = ref([]), selectedRunId = ref(''), persistedEvents = ref([]), allRuns = ref(false)
const historyLoading = ref(false), eventsLoading = ref(false), cancelling = ref(false)
const hasMoreRuns = ref(false), hasMoreEvents = ref(false), historyError = ref('')
let generation = 0
const selectedRun = computed(() => runs.value.find(run => run.runId === selectedRunId.value))
const displayedMessages = computed(() => selectedRun.value && selectedRun.value.sessionId !== store.sessionId ? [] : store.messages)
const displayStatus = computed(() => (store.agentHealth?.runJournalEnabled ? selectedRun.value?.status : store.executionTrace?.status) || '暂无执行记录')
const displayUpdatedAt = computed(() => store.agentHealth?.runJournalEnabled ? selectedRun.value?.endedAt || selectedRun.value?.startedAt : store.executionTrace?.updatedAt)
const events = computed(() => store.agentHealth?.runJournalEnabled ? persistedEvents.value.map(event => ({ ...event.payload, type: event.type, sequence: event.sequence })) : store.executionTrace?.events || [])
async function loadRuns(append = false) {
  if (!store.agentHealth?.runJournalEnabled) return
  const version = generation, sid = store.sessionId
  historyLoading.value = true; historyError.value = ''
  try {
    const response = await fetchAgentRuns({ ...(allRuns.value ? {} : { sessionId: sid }), limit: 20, ...(append ? { beforeRunId: runs.value.at(-1)?.runId } : {}) })
    if (version !== generation || sid !== store.sessionId) return
    const rows = Array.isArray(response.data) ? response.data : []
    runs.value = append ? [...runs.value, ...rows] : rows
    hasMoreRuns.value = rows.length === 20
    if (!append) {
      selectedRunId.value = rows.some(run => run.runId === selectedRunId.value) ? selectedRunId.value : rows[0]?.runId || ''
      historyLoading.value = false
      await loadRun()
    }
  } catch (error) {
    if (version === generation) historyError.value = error.response?.data?.message || '运行历史暂不可用 请刷新'
  } finally { if (version === generation) historyLoading.value = false }
}
async function loadRun() {
  generation++
  persistedEvents.value = []; hasMoreEvents.value = false; historyError.value = ''
  if (selectedRunId.value) await loadMoreEvents()
}
async function loadMoreEvents() {
  const version = generation, id = selectedRunId.value
  eventsLoading.value = true
  try {
    const response = await fetchAgentRunEvents(id, persistedEvents.value.at(-1)?.sequence || 0)
    if (version !== generation || id !== selectedRunId.value) return
    const rows = Array.isArray(response.data) ? response.data : []
    const existing = new Set(persistedEvents.value.map(event => event.sequence))
    persistedEvents.value = [...persistedEvents.value, ...rows.filter(event => !existing.has(event.sequence))]
    hasMoreEvents.value = rows.length === 100
  } catch (error) {
    if (version === generation) historyError.value = error.response?.data?.message || '执行事件暂不可用 请刷新'
  } finally { if (version === generation) eventsLoading.value = false }
}
async function refresh() {
  await store.loadDiagnostics()
  await loadRuns()
}
async function changeHistoryScope() {
  generation++; selectedRunId.value = ''; runs.value = []; persistedEvents.value = []
  hasMoreEvents.value = false; hasMoreRuns.value = false
  await loadRuns()
}
async function selectSession(id) {
  allRuns.value = false
  generation++; selectedRunId.value = ''; runs.value = []; persistedEvents.value = []
  hasMoreEvents.value = false; hasMoreRuns.value = false; eventsLoading.value = false; historyLoading.value = false
  await store.switchSession(id); await refresh()
}
async function cancelRun() {
  cancelling.value = true
  try { await cancelAgentRun(selectedRunId.value); ElMessage.success('取消请求已处理'); await refresh() }
  catch (error) { ElMessage.error(error.response?.data?.message || '取消未确认 请刷新状态') }
  finally { cancelling.value = false }
}
function exportTrace() {
  const data = store.agentHealth?.runJournalEnabled ? { framework: 'AgentScope', run: selectedRun.value, events: persistedEvents.value } : store.executionTrace
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = `agentscope-trace-${selectedRunId.value || store.sessionId}.json`; anchor.click()
  URL.revokeObjectURL(url)
}
onMounted(async () => {
  await store.bootstrap()
  const linkedRun=typeof route.query.runId==='string'?route.query.runId:''
  if(linkedRun)allRuns.value=true
  await refresh()
  if(linkedRun && store.agentHealth?.runJournalEnabled){
    // 直接读取指定运行，不以第一页历史中是否包含它为授权依据。
    try {
      const response=await fetchAgentRun(linkedRun)
      if(!runs.value.some(run=>run.runId===linkedRun))runs.value.unshift(response.data)
      selectedRunId.value=linkedRun
      await loadRun()
    } catch(error) { historyError.value=error.response?.data?.message || '该运行不存在或无访问权限' }
  }
})
</script>
<style scoped>
.agent-trace-page { padding: 24px; background: #fff; color: #182332; animation: trace-enter .2s ease-out }
.trace-header { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 24px }
.trace-header h2 { margin: 0 0 8px }.trace-header p, .run-id { color: #697789; font-size: 13px }
.trace-content { display: grid; grid-template-columns: 230px minmax(0, 1fr); gap: 24px }
.history-toolbar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 12px }.history-toolbar .el-select { width: min(100%, 340px) }.journal-note { color: #697789; font-size: 13px }.history-error { color: #bf3131; font-size: 13px }
.trace-content main { min-width: 0 }.run-id { overflow-wrap: anywhere }
.trace-content aside { border-right: 1px solid #e7edf5; padding-right: 16px }.session-button { width: 100%; border: 0; padding: 12px; border-radius: 8px; text-align: left; background: transparent; cursor: pointer; transition: background .15s, transform .15s }.session-button:hover { background: #f4f7fc; transform: scale(1.01) }.session-button.active { background: #eaf2ff; color: #1764cb }.session-button small { display: block; margin-top: 6px; color: #748091 }
.trace-summary { display: flex; align-items: center; gap: 12px }.trace-summary small { color: #748091 }.message-item { padding: 16px; margin: 12px 0; background: #f7f9fc; border-radius: 10px }.message-item.user { background: #edf4ff }.message-item p { white-space: pre-wrap; overflow-wrap: anywhere; margin: 10px 0 0; line-height: 1.6 }
@keyframes trace-enter { from { opacity: 0; transform: translateY(5px) } to { opacity: 1; transform: translateY(0) } }
@media (max-width: 800px) { .trace-content { grid-template-columns: 1fr }.trace-content aside { border-right: 0 }.trace-header { align-items: flex-start; flex-direction: column } }
@media (prefers-reduced-motion: reduce) { .agent-trace-page { animation: none }.session-button { transition: none }.session-button:hover { transform: none } }
</style>
