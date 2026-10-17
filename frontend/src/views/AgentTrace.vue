<template>
  <section class="trace-workspace" :class="{ 'has-inspector': selectedEvent, 'history-open': historyOpen }" aria-label="Agent 执行追溯">
    <header class="trace-page-header">
      <div class="trace-page-title"><span class="trace-brand"><el-icon><Connection /></el-icon></span><div><h2>Agent 执行追溯</h2><p>从一次提问，追踪实际发生的调用</p></div></div>
      <div class="trace-page-actions">
        <el-button :loading="refreshing" @click="refresh"><el-icon><Refresh /></el-icon><span>刷新记录</span></el-button>
        <el-button :disabled="!canExport" @click="exportTrace"><el-icon><Download /></el-icon><span>导出轨迹</span></el-button>
      </div>
    </header>

    <button v-if="historyOpen" class="trace-history-mask" type="button" aria-label="关闭运行列表" @click="historyOpen=false"></button>
    <aside class="trace-history" aria-label="运行历史">
      <header><h3>运行历史</h3><span>仅当前账号</span></header>
      <el-select v-model="sessionId" aria-label="筛选会话" placeholder="选择会话" :disabled="allRuns || initializing" @change="changeScope">
        <el-option v-for="session in store.sessions" :key="session.sessionId" :label="session.title || '新对话'" :value="session.sessionId" />
      </el-select>
      <el-switch v-model="allRuns" active-text="全部入口运行" aria-label="全部入口运行" :disabled="initializing" @change="changeScope" />
      <el-input v-model="runQuery" placeholder="搜索已加载的运行" aria-label="搜索已加载的运行" clearable :prefix-icon="Search" />
      <p v-if="state.historyError" class="trace-error" role="alert">{{ state.historyError }}</p>
      <div class="trace-run-list" :aria-busy="state.historyLoading">
        <button v-for="run in visibleRuns" :key="run.runId" type="button" class="trace-run" :class="{ active: run.runId === state.selectedRun?.runId }" :aria-current="run.runId === state.selectedRun?.runId ? 'true' : undefined" @click="selectRun(run.runId)">
          <span class="trace-run-heading"><strong>{{ traceEntry(run.entryPoint) }}</strong><span class="trace-status" :class="run.status.toLowerCase()">{{ traceStatus(run.status) }}</span></span>
          <span class="trace-run-date">{{ traceTime(run.startedAt) }}</span>
          <span class="trace-run-id">{{ run.runId }}</span>
        </button>
        <p v-if="!visibleRuns.length && !state.historyLoading" class="trace-empty-note">{{ runQuery ? '已加载运行中没有匹配项' : journalEnabled ? '当前范围暂无运行记录' : '持久运行日志尚未启用' }}</p>
        <p v-if="state.historyLoading" class="trace-empty-note" role="status">正在读取运行历史…</p>
      </div>
      <el-button v-if="state.hasMoreRuns" :loading="state.historyLoading" @click="loadHistory(true)">加载更早运行</el-button>
      <p class="trace-history-note"><el-icon><Lock /></el-icon>主站与独立 Agent 共用本人运行日志</p>
    </aside>

    <main class="trace-main">
      <header class="trace-run-toolbar">
        <button ref="historyToggle" class="trace-icon-button history-toggle" type="button" aria-label="展开运行列表" :aria-expanded="historyOpen" @click="historyOpen=!historyOpen"><el-icon><Fold /></el-icon></button>
        <div class="trace-run-heading"><span class="trace-status" :class="displayStatus.toLowerCase()">{{ traceStatus(displayStatus) }}</span><span>{{ journalEnabled ? traceEntry(state.selectedRun?.entryPoint) : '最新会话摘要' }}</span></div>
        <el-button v-if="state.selectedRun?.status==='RUNNING'" type="danger" plain size="small" :loading="cancelling" @click="cancelRun">取消运行</el-button>
        <a v-if="state.selectedRun?.sessionId" :href="chatLink" class="trace-chat-link">返回会话 <el-icon><TopRight /></el-icon></a>
      </header>
      <p v-if="pageError || state.detailError" class="trace-error trace-inline-alert" role="alert">{{ pageError || state.detailError }}</p>
      <p v-if="!journalEnabled && !initializing" class="trace-note trace-inline-alert">持久运行日志未启用，仅展示当前会话已有摘要；历史对话不会补造调用节点或耗时。</p>
      <template v-if="state.selectedRun || (!journalEnabled && events.length)">
        <div class="trace-run-overview">
          <span class="trace-eyebrow">EXECUTION RECORD</span>
          <div class="trace-overview-heading"><h3>{{ state.selectedRun?.mainAgent || store.agentHealth?.framework || 'AgentScope' }}</h3><button v-if="state.selectedRun" class="trace-copy-id" type="button" @click="copyRunId" title="复制运行编号"><el-icon><CopyDocument /></el-icon>{{ state.selectedRun.runId }}</button></div>
          <div class="trace-metrics">
            <div><span>已加载事件</span><strong>{{ summary.events }}<small v-if="state.selectedRun"> / {{ state.selectedRun.lastSequence }}</small></strong></div>
            <div><span>工具调用</span><strong>{{ summary.tools }}<small> 次已记录开始</small></strong></div>
            <div><span>模型逻辑请求</span><strong>{{ summary.modelRequests }}<small> 次已记录开始</small></strong><small>{{ summary.modelAttempts }} 次候选调用 · {{ summary.fallbackSelections }} 次备用选择</small></div>
            <div><span>已记录 Token 用量</span><strong>{{ tokenTotal ?? '—' }}</strong><small>{{ summary.usageRecords }} 条用量记录</small></div>
          </div>
          <p class="trace-note">{{ traceTime(state.selectedRun?.startedAt || store.executionTrace?.updatedAt) }}<template v-if="state.selectedRun?.endedAt"> → {{ traceTime(state.selectedRun.endedAt) }}</template><span v-if="summary.denied"> · {{ summary.denied }} 次角色核验拒绝</span></p>
        </div>
        <div class="trace-view-tabs" role="group" aria-label="追溯视图">
          <button v-for="tab in tabs" :key="tab.value" type="button" :aria-pressed="activeTab===tab.value" :class="{ active: activeTab===tab.value }" @click="activeTab=tab.value"><el-icon><component :is="tab.icon" /></el-icon>{{ tab.label }}</button>
        </div>
        <div class="trace-scroll-area">
          <section v-if="activeTab === 'timeline'" aria-label="执行过程">
            <div class="trace-filter-row"><el-input v-model="eventQuery" clearable :prefix-icon="Search" placeholder="搜索 Agent、工具或调用编号" aria-label="搜索事件" /><span>{{ filteredEvents.length }} / {{ events.length }} 条</span></div>
            <div class="trace-filter-chips" role="group" aria-label="事件类型"><button v-for="category in traceCategories" :key="category.value" type="button" :class="{ active: eventFilter===category.value }" :aria-pressed="eventFilter===category.value" @click="eventFilter=category.value">{{ category.label }}</button></div>
            <ol class="trace-timeline">
              <li v-for="event in pagedEvents" :key="event.sequence">
                <button type="button" class="trace-event" :class="{ selected: selectedSequence===event.sequence }" :aria-label="'查看事件 '+event.sequence+' '+eventTitle(event)" @click="inspect(event)">
                  <span class="trace-event-marker" :class="eventTone(event.type)"><el-icon><component :is="categoryIcon(event.type)" /></el-icon></span>
                  <span class="trace-event-content"><span class="trace-event-top"><strong>{{ eventTitle(event) }}</strong><small>#{{ event.sequence }}</small></span><span class="trace-event-subtitle">{{ event.payload.tool || event.payload.modelId || event.payload.skillId || event.payload.agent || '运行生命周期' }}</span><span v-if="event.payload.parentCallId" class="trace-parent-label">子调用 · {{ event.payload.parentCallId }}</span></span>
                  <span class="trace-event-timing"><strong>{{ event.payload.elapsedMs != null ? '+'+traceDuration(event.payload.elapsedMs) : '时间未记录' }}</strong><small v-if="event.payload.durationMs != null">耗时 {{ traceDuration(event.payload.durationMs) }}</small></span>
                  <el-icon class="trace-event-arrow"><ArrowRight /></el-icon>
                </button>
              </li>
            </ol>
            <p v-if="!filteredEvents.length" class="trace-empty-note">{{ events.length ? '没有匹配的事件，可调整筛选条件' : '暂未读取到执行事件' }}</p>
            <el-pagination v-if="filteredEvents.length>PAGE_SIZE" v-model:current-page="eventPage" :page-size="PAGE_SIZE" :total="filteredEvents.length" layout="prev, pager, next" small />
          </section>

          <section v-else-if="activeTab === 'results'" class="trace-results" aria-label="关联结果">
            <h4>本次运行关联的业务结果</h4><p class="trace-note">仅展示消息中明确记录相同 runId 的卡片；刷新卡片会按当前账号重新核对业务权限。</p>
            <AgentResultCards v-for="message in linkedCards" :key="message.id" :message="message" />
            <el-empty v-if="!linkedCards.length" :description="state.messagesError ? '会话暂不可用，无法核对结果关联' : '未找到明确关联本次运行的结果卡片'" :image-size="76" />
            <div class="trace-evidence-note"><el-icon><Document /></el-icon><div><strong>关于调研来源</strong><p>当前日志不保存网页 URL、引用正文、工具参数或返回内容。Fetch 调用记录只能证明发生了调用，不能作为具体网页或结论的证据。</p></div></div>
          </section>

          <section v-else-if="activeTab === 'sources'" aria-label="调研来源">
            <h4>本次运行的调研来源</h4>
            <p v-if="state.evidenceLoading" class="trace-note" role="status">正在读取本人来源记录…</p>
            <p v-if="state.evidenceError" class="trace-error" role="alert">{{ state.evidenceError }} <el-button size="small" @click="reader.loadEvidence()">重试读取来源</el-button></p>
            <AgentResearchSources v-if="state.selectedRun" :key="state.selectedRun.runId" :run-id="state.selectedRun.runId" :evidence="state.evidence" :answers="sourceAnswers" :recorded-calls="sourceToolEvents.map(event=>event.payload.callId)" @inspect-call="inspectSourceCall" />
          </section>

          <section v-else-if="activeTab === 'models'" aria-label="模型路由">
            <h4>实际模型调用</h4><p class="trace-note">按模型请求编号展示已记录的候选调用、备用选择和熔断跳过。候选序号不等于供应商 HTTP 重试次数；SDK 内部重试尚未单独采集。</p><p class="trace-note">供应商标识对应系统接入配置，openai 也可指灵算等自定义 Responses 上游。模型名为适配器请求的名称，供应商内部转发未采集。</p>
            <el-empty v-if="!modelRequests.length" description="此记录未采集调用级模型信息，不从默认配置推断" :image-size="76" />
            <article v-for="request in modelRequests" :key="request.key" class="trace-model-request">
              <h4>{{ request.agent || 'Agent 未记录' }}<template v-if="request.purpose==='CONTEXT_COMPACTION'"> · 上下文摘要</template></h4><p class="trace-note">请求编号 {{ request.requestId }}</p>
              <div v-for="attempt in request.attempts" :key="attempt.key" class="trace-model-attempt">
                <div><strong>候选 {{ attempt.attempt }} · {{ attempt.modelId }}</strong><p>{{ attempt.provider || '供应商未记录' }} · {{ attempt.model || '模型名未记录' }} · {{ attempt.status === 'SKIPPED' ? '已跳过，未请求' : traceStatus(attempt.status) }}</p>
                  <p v-if="attempt.failureReason">{{ modelFailureLabel(attempt.failureReason) }}<template v-if="attempt.httpStatus != null"> · HTTP {{ attempt.httpStatus }}</template></p>
                  <p v-if="attempt.status !== 'SKIPPED'" class="trace-note">耗时 {{ traceDuration(attempt.durationMs) }} · 首段内容 {{ traceDuration(attempt.firstContentMs) }}</p></div>
                <button class="trace-icon-button" type="button" :aria-label="'查看候选 '+attempt.attempt+' '+attempt.modelId" @click="inspect(attempt.firstEvent)"><el-icon><ArrowRight /></el-icon></button>
              </div>
              <p v-if="!request.attempts.length" class="trace-note">此请求尚无候选调用记录</p>
              <p v-for="event in request.events.filter(row=>row.type==='MODEL_FALLBACK_SELECTED')" :key="event.sequence" class="trace-note">备用选择：{{ event.payload.modelId }} → {{ event.payload.nextModelId }} · {{ modelFailureLabel(event.payload.failureReason) }}</p>
            </article>
          </section>

          <section v-else-if="activeTab === 'messages'" aria-label="会话上下文">
            <p class="trace-note">展示所属会话的消息上下文，可能包含多次运行；消息时间不用于推断本次运行的输入与回答。</p>
            <p v-if="state.messagesLoading" role="status">正在读取会话…</p><p v-if="state.messagesError" class="trace-error" role="alert">{{ state.messagesError }}</p>
            <ChatMessageList v-if="displayedMessages.length" :messages="displayedMessages" />
            <el-empty v-else-if="!state.messagesLoading" description="没有可展示的会话上下文" :image-size="76" />
          </section>

          <section v-else aria-label="原始事件">
            <p class="trace-note">当前已加载的白名单元数据。缺失字段保持缺失，不展示提示词、思考正文或凭证。</p>
            <pre class="trace-json">{{ JSON.stringify(events, null, 2) }}</pre>
          </section>

          <div class="trace-load-footer">
            <p v-if="state.eventsError" class="trace-error" role="alert">{{ state.eventsError }}</p>
            <el-button v-if="journalEnabled && (state.hasMoreEvents || state.eventsError)" :loading="state.eventsLoading" @click="reader.loadMore()">补读后续事件</el-button>
            <span v-if="journalEnabled" class="trace-note">{{ complete ? '当前记录已读全' : '事件未读全，导出暂不可用' }} · 补读不会重新执行模型或工具</span>
          </div>
          <AgentActionList v-if="state.selectedRun" :key="state.selectedRun.runId" :run-id="state.selectedRun.runId" />
        </div>
      </template>
      <div v-else class="trace-idle"><el-icon><Connection /></el-icon><h3>{{ initializing || state.detailLoading ? '正在读取执行记录' : '选择一次运行，查看它的执行过程' }}</h3><p>模型请求、工具调用与权限事件，都以服务器记录为依据</p></div>
    </main>

    <Transition name="trace-inspector">
      <aside v-if="selectedEvent" class="trace-inspector" aria-label="事件详情" @keydown.esc="closeInspector">
        <header><div><span class="trace-eyebrow">EVENT INSPECTOR</span><h3>事件详情 <small>#{{ selectedEvent.sequence }}</small></h3></div><button class="trace-icon-button" type="button" aria-label="关闭事件详情" @click="closeInspector"><el-icon><Close /></el-icon></button></header>
        <span class="trace-event-kind" :class="eventTone(selectedEvent.type)">{{ eventTitle(selectedEvent) }}</span>
        <dl class="trace-detail-list"><template v-for="field in detailFields" :key="field.label"><dt>{{ field.label }}</dt><dd>{{ field.value }}</dd></template></dl>
        <template v-if="selectedCall"><h4>同次工具调用</h4><p class="trace-note">{{ traceStatus(selectedCall.status) }} · 耗时 {{ traceDuration(selectedCall.durationMs) }}</p><button v-for="event in selectedCall.events" :key="event.sequence" class="trace-related-event" type="button" @click="inspect(event)"><span>#{{ event.sequence }} {{ eventTitle(event) }}</span><el-icon><ArrowRight /></el-icon></button></template>
        <template v-if="selectedModelRequest"><h4>同次模型逻辑请求</h4><button v-for="event in selectedModelRequest.events" :key="event.sequence" class="trace-related-event" type="button" @click="inspect(event)"><span>#{{ event.sequence }} {{ eventTitle(event) }}</span><el-icon><ArrowRight /></el-icon></button></template>
        <template v-if="parentCandidates.length"><h4>上级委派调用</h4><button v-for="call in parentCandidates" :key="call.key" class="trace-related-event" type="button" @click="inspect(call.events[0])">{{ call.tool }}<el-icon><TopRight /></el-icon></button></template>
        <p v-else-if="selectedEvent.payload.parentCallId" class="trace-note">已记录父调用编号，对应节点尚未加载或未记录；不会按工具名称推测关联。</p>
        <div v-if="eventCategory(selectedEvent.type)==='AUTHORIZATION'" class="trace-evidence-note"><p>角色核验通过仅表示允许调用工具，具体业务资源权限仍由服务端再次校验。</p></div>
        <h4>运行配置</h4><dl class="trace-detail-list"><dt>默认模型</dt><dd>{{ state.selectedRun?.defaultModel || store.agentHealth?.defaultModel || '未记录' }}</dd><dt>策略版本</dt><dd>{{ state.selectedRun?.policyVersion || '未记录' }}</dd></dl><p class="trace-note">默认模型是配置值，不表示该事件实际使用的供应商或备用模型。</p>
      </aside>
    </Transition>
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Refresh, Download, Search, Lock, Fold, TopRight, CopyDocument, ArrowRight, Close, Document, Operation, Cpu, Key, Collection, ChatDotRound } from '@element-plus/icons-vue'
import { fetchAgentRuns, fetchAgentRun, fetchAgentRunEvents, fetchAgentRunSources, fetchSessionById, cancelAgentRun } from '@/api/chatAssistant'
import { useChatAssistantStore } from '@/stores/chatAssistant'
import { initialTraceState, createTraceReader } from '@/utils/agentTraceReader'
import { normalizeTraceEvents, traceStatus, traceDuration, traceTime, traceEntry, eventTitle, eventCategory, eventTone, traceCategories, filterTraceEvents, traceCalls, traceSummary, traceCompleteness, traceModelRequests, modelFailureLabel } from '@/utils/agentTrace'
import { parseAgentCardEnvelope } from '@/utils/agentCards'
import AgentResultCards from '@/components/chat/AgentResultCards.vue'
import AgentActionList from '@/components/chat/AgentActionList.vue'
import ChatMessageList from '@/components/chat/ChatMessageList.vue'
import AgentResearchSources from '@/components/chat/AgentResearchSources.vue'

const store = useChatAssistantStore(), route = useRoute(), router = useRouter()
const state = reactive(initialTraceState())
const reader = createTraceReader({ list: fetchAgentRuns, run: fetchAgentRun, events: fetchAgentRunEvents, sources: fetchAgentRunSources, session: fetchSessionById }, state, normalizeTraceEvents, traceCompleteness)
const sessionId = ref(''), allRuns = ref(false), runQuery = ref(''), eventQuery = ref(''), eventFilter = ref('ALL')
const activeTab = ref('timeline'), eventPage = ref(1), selectedSequence = ref(null), historyOpen = ref(false), historyToggle = ref(null)
const initializing = ref(true), refreshing = ref(false), cancelling = ref(false), pageError = ref('')
const requestedRunId = ref('')
const PAGE_SIZE = 50
let mounted = false, scopeVersion = 0, pollTimer, opener = null
const journalEnabled = computed(() => store.agentHealth?.runJournalEnabled === true)
const events = computed(() => pageError.value ? [] : journalEnabled.value ? state.events : route.query.runId ? [] : normalizeTraceEvents(store.executionTrace?.events, true))
const displayStatus = computed(() => (journalEnabled.value ? state.selectedRun?.status : store.executionTrace?.status) || 'RECORDED')
const visibleRuns = computed(() => {
  const current=state.selectedRun
  const rows=current && !state.runs.some(run=>run.runId===current.runId) ? [current,...state.runs] : state.runs
  return rows.filter(run => !runQuery.value || [run.runId, run.mainAgent, run.status, traceStatus(run.status), traceEntry(run.entryPoint)].join(' ').toLowerCase().includes(runQuery.value.toLowerCase()))
})
const summary = computed(() => traceSummary(events.value, displayStatus.value))
const tokenTotal = computed(() => summary.value.inputTokens == null && summary.value.outputTokens == null ? null : (summary.value.inputTokens || 0) + (summary.value.outputTokens || 0))
const filteredEvents = computed(() => filterTraceEvents(events.value, eventFilter.value, eventQuery.value))
const pagedEvents = computed(() => filteredEvents.value.slice((eventPage.value-1)*PAGE_SIZE, eventPage.value*PAGE_SIZE))
const selectedEvent = computed(() => events.value.find(event => event.sequence === selectedSequence.value))
const calls = computed(() => traceCalls(events.value, displayStatus.value))
const selectedCall = computed(() => calls.value.find(call => call.events.some(event => event.sequence === selectedSequence.value)))
const modelRequests = computed(() => traceModelRequests(events.value, displayStatus.value))
const selectedModelRequest = computed(() => modelRequests.value.find(request => request.events.some(event => event.sequence === selectedSequence.value)))
const parentCandidates = computed(() => selectedEvent.value?.payload.parentCallId ? calls.value.filter(call => call.callId === selectedEvent.value.payload.parentCallId) : [])
const complete = computed(() => !!state.selectedRun && traceCompleteness(events.value, state.selectedRun.lastSequence).complete)
const canExport = computed(() => events.value.length > 0 && !initializing.value && !state.detailLoading && !state.eventsLoading && !state.detailError && !state.eventsError && (!journalEnabled.value || complete.value))
const displayedMessages = computed(() => journalEnabled.value ? state.messages : store.messages)
const linkedCards = computed(() => state.selectedRun ? state.messages.filter(message => message.messageType === 'AGENT_CARDS' && parseAgentCardEnvelope(message.content)?.runId === state.selectedRun.runId) : [])
const chatLink = computed(() => '#/agent/chat?sessionId='+encodeURIComponent(state.selectedRun?.sessionId || sessionId.value))
const sourceAnswers = computed(()=>state.messages.filter(message=>message.role==='assistant').flatMap(message=>message.messageType==='AGENT_CARDS'?[parseAgentCardEnvelope(message.content)?.text].filter(Boolean):typeof message.content==='string'?[message.content]:[]))
const sourceToolEvents = computed(()=>events.value.filter(event=>event.type==='TOOL_STARTED'&&event.payload.tool==='mcp__fetch__fetch'&&event.payload.agent===state.selectedRun?.mainAgent))
function inspectSourceCall(callId){const matches=sourceToolEvents.value.filter(event=>event.payload.callId===callId);if(matches.length===1)inspect(matches[0])}
const tabs = [{ value: 'timeline', label: '执行过程', icon: Connection }, { value: 'models', label: '模型路由', icon: Cpu }, { value: 'sources', label: '调研来源', icon: Document }, { value: 'results', label: '关联结果', icon: Document }, { value: 'messages', label: '会话上下文', icon: ChatDotRound }, { value: 'raw', label: '原始事件', icon: Collection }]
const categoryIcon = type => ({ MODEL: Cpu, TOOL: Operation, AUTHORIZATION: Key, SKILL: Collection, AGENT: Connection, RUN: Connection, CONTEXT: Collection })[eventCategory(type)]
const detailFields = computed(() => {
  if (!selectedEvent.value) return []
  const event = selectedEvent.value, p = event.payload
  return [
    ['事件类型', event.type], ['Agent', p.agent], ['工具', p.tool], ['调用编号', p.callId], ['父调用编号', p.parentCallId],
    ['记录时间', traceTime(event.occurredAt)], ['运行后时间', traceDuration(p.elapsedMs)], ['此事件记录耗时', traceDuration(p.durationMs)],
    ['输入 Token', p.inputTokens], ['输出 Token', p.outputTokens], ['结果', p.result], ['角色决策', p.decision], ['数据范围', p.scope],
    ['策略版本', p.policyVersion], ['技能', p.skillId], ['技能版本', p.version], ['命令', p.command], ['内容摘要 SHA256', p.sha256],
    ['模型请求编号', p.modelRequestId], ['供应商接入标识', p.provider], ['候选模型 ID', p.modelId], ['请求模型名', p.model], ['候选序号', p.attempt],
    ['首段内容耗时', p.firstContentMs == null ? null : traceDuration(p.firstContentMs)], ['失败原因', p.failureReason ? modelFailureLabel(p.failureReason) : null], ['HTTP 状态', p.httpStatus], ['下一备用候选', p.nextModelId],
    ['请求用途', p.purpose==='CONTEXT_COMPACTION'?'上下文摘要':null], ['压缩前消息数', p.beforeMessages], ['压缩后消息数', p.afterMessages], ['压缩前字符数', p.beforeChars], ['压缩后字符数', p.afterChars],
  ].filter(([,value],index) => index < 10 || value != null).map(([label,value]) => ({label,value: value ?? '未记录'}))
})
watch([eventFilter,eventQuery], () => { eventPage.value=1 })
watch(() => state.selectedRun?.runId, () => { selectedSequence.value=null; eventPage.value=1 })
function inspect(event) { if (!document.activeElement?.closest('.trace-inspector')) opener=document.activeElement; selectedSequence.value=event.sequence }
function closeInspector() { selectedSequence.value=null; nextTick(() => { if (opener?.isConnected) opener.focus() }) }
function escapePanels(event) { if (event.key !== 'Escape') return; if (selectedEvent.value) closeInspector(); else if (historyOpen.value) { historyOpen.value=false; historyToggle.value?.focus() } }
async function selectRun(id) {
  scopeVersion++; requestedRunId.value=id
  historyOpen.value=false; await reader.select(id)
  if (state.selectedRun?.runId === id) await router.replace({ query: { runId: id } })
}
async function loadHistory(append=false) { if (journalEnabled.value) await reader.history({ sessionId: sessionId.value, all: allRuns.value, append }) }
async function changeScope() {
  const version=++scopeVersion
  requestedRunId.value=''
  reader.reset(); selectedSequence.value=null; runQuery.value=''
  await router.replace({ query: allRuns.value ? {} : { sessionId: sessionId.value } })
  await loadHistory()
  if (version===scopeVersion && state.runs[0]) await selectRun(state.runs[0].runId)
}
watch(() => [route.query.runId,route.query.sessionId], async ([id,sid]) => {
  if (!mounted || initializing.value || !journalEnabled.value) return
  if (typeof id==='string' && id!==requestedRunId.value) {
    const version=++scopeVersion
    requestedRunId.value=id; allRuns.value=true; reader.reset()
    await loadHistory()
    if (version===scopeVersion) await selectRun(id)
  } else if (typeof id!=='string' && typeof sid==='string' && (sid!==sessionId.value || allRuns.value)) {
    sessionId.value=sid; allRuns.value=false; await changeScope()
  } else if (id==null && sid==null && requestedRunId.value) {
    allRuns.value=true; await changeScope()
  }
})
async function refresh() {
  if (refreshing.value) return
  refreshing.value=true
  try {
    if (!journalEnabled.value) { await store.loadDiagnostics(); return }
    if (state.selectedRun) await Promise.all([reader.refresh(),loadHistory()])
    else if (typeof route.query.runId==='string' && journalEnabled.value) await reader.select(route.query.runId)
    else { await loadHistory(); if (state.runs[0]) await selectRun(state.runs[0].runId) }
  } finally { refreshing.value=false }
}
async function copyRunId() { try { await navigator.clipboard.writeText(state.selectedRun.runId); ElMessage.success('运行编号已复制') } catch { ElMessage.info('复制不可用，请手动选择运行编号') } }
async function cancelRun() {
  const id=state.selectedRun?.runId
  if (!id || cancelling.value) return
  try { await ElMessageBox.confirm('取消后不会自动恢复本次运行，已完成的业务操作不会回滚。确认取消？','取消运行',{confirmButtonText:'确认取消运行',cancelButtonText:'继续运行',type:'warning'}) } catch { return }
  if (!mounted || state.selectedRun?.runId!==id) return
  cancelling.value=true
  try { await cancelAgentRun(id); ElMessage.success('取消请求已处理'); if (mounted && state.selectedRun?.runId===id) await reader.refresh() }
  catch (error) { ElMessage.error(error.response?.data?.message || '取消未确认，请刷新运行状态') }
  finally { cancelling.value=false }
}
function exportTrace() {
  if (!canExport.value) return
  const data={ framework: 'AgentScope', run: journalEnabled.value ? state.selectedRun : null, source: journalEnabled.value ? 'persisted-journal' : 'legacy-summary', complete: journalEnabled.value ? complete.value : false, events: events.value }
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}))
  const anchor=document.createElement('a'); anchor.href=url; anchor.download=`agentscope-trace-${state.selectedRun?.runId || store.sessionId}.json`; anchor.click(); setTimeout(()=>URL.revokeObjectURL(url),1000)
}
onMounted(async () => {
  mounted=true; document.addEventListener('keydown',escapePanels)
  try {
    await store.bootstrap(); if (!mounted) return
    if (typeof route.query.sessionId==='string' && route.query.sessionId !== store.sessionId) await store.switchSession(route.query.sessionId)
    await store.loadDiagnostics(); if (!mounted) return
    sessionId.value=typeof route.query.sessionId==='string' ? route.query.sessionId : store.sessionId
    allRuns.value=typeof route.query.runId==='string'
    if (journalEnabled.value) {
      await loadHistory(); if (!mounted) return
      const id=typeof route.query.runId==='string' ? route.query.runId : state.runs[0]?.runId
      if (id) await selectRun(id)
    }
    else if (typeof route.query.runId==='string') pageError.value='持久运行日志未启用，无法读取指定运行'
  } catch { if (mounted) pageError.value='追溯页面初始化失败，请重新进入页面' }
  finally { if (mounted) initializing.value=false }
  if (!mounted) return
  pollTimer=setInterval(() => { if (!document.hidden && journalEnabled.value && state.selectedRun?.status==='RUNNING') reader.refresh() },5000)
})
onBeforeUnmount(() => { mounted=false; scopeVersion++; clearInterval(pollTimer); reader.dispose(); document.removeEventListener('keydown',escapePanels) })
</script>

<style scoped>
.trace-workspace { display: grid; grid-template-columns: 236px minmax(0,1fr); grid-template-rows: auto minmax(0,1fr); height: 100%; min-height: 0; overflow: hidden; border: 1px solid #e7ebf1; border-radius: 18px; background: #fff; color: #18263c; }
.trace-page-header { grid-column: 1/-1; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 20px 24px; border-bottom: 1px solid #edf0f5; }
.trace-page-title { display: flex; align-items: center; gap: 12px; }.trace-brand { width: 40px; height: 40px; display: grid; place-items: center; color: #2563eb; background: #eff5ff; border-radius: 12px; font-size: 21px; }
.trace-page-title h2 { margin: 0; font-size: 18px; font-weight: 650; }.trace-page-title p { margin: 5px 0 0; font-size: 12px; color: #68768a; }.trace-page-actions { display: flex; align-items: center; gap: 8px; }.trace-page-actions :deep(.el-button) { margin: 0; gap: 6px; }
.trace-history { display: flex; flex-direction: column; gap: 14px; min-height: 0; padding: 20px 14px 14px; background: #f8f9fc; border-right: 1px solid #e7ebf1; }.trace-history header { display: flex; align-items: center; justify-content: space-between; padding: 0 4px; }.trace-history h3 { font-size: 13px; margin: 0; }.trace-history header span { font-size: 10px; color: #68768a; }.trace-history :deep(.el-select) { width: 100%; }
.trace-run-list { flex: 1; min-height: 0; overflow-y: auto; }.trace-run { width: 100%; display: grid; gap: 8px; text-align: left; padding: 14px 12px; margin-bottom: 6px; background: transparent; border: 1px solid transparent; border-radius: 12px; cursor: pointer; transition: background .18s,border-color .18s,transform .18s; color: #526078; }.trace-run:hover { background: #eef2f8; }.trace-run:active { transform: scale(.985); }.trace-run.active { border-color: #d5e3ff; background: #eaf1ff; }.trace-run-heading { display: flex; align-items: center; gap: 10px; min-width: 0; }.trace-run-heading strong { flex: 1; font-size: 12px; color: #24354e; }.trace-run-date { font-size: 11px; color: #68768a; }.trace-run-id { font-family: Consolas,monospace; font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.trace-history-note { display: flex; gap: 6px; font-size: 10px; color: #68768a; line-height: 1.7; border-top: 1px solid #e7ebf1; padding-top: 14px; }
.trace-status { display: inline-flex; align-items: center; width: fit-content; font-size: 10px; line-height: 1.5; padding: 3px 7px; border-radius: 6px; color: #68768a; background: #eff2f6; white-space: nowrap; }.trace-status.running { color: #2563eb; background: #eaf1ff; }.trace-status.completed { color: #167653; background: #ecf8f1; }.trace-status.failed,.trace-status.interrupted { color: #b54542; background: #fff0ef; }
.trace-main { min-width: 0; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }.trace-run-toolbar { display: flex; align-items: center; min-height: 56px; padding: 12px 24px; gap: 12px; border-bottom: 1px solid #edf0f5; font-size: 12px; flex-shrink: 0; }.trace-chat-link { display: flex; align-items: center; gap: 5px; margin-left: auto; font-size: 11px; color: #2563eb; white-space: nowrap; }.trace-run-overview { padding: 22px 24px 10px; }.trace-eyebrow { font-size: 9px; font-weight: 700; color: #68768a; letter-spacing: .12em; }.trace-overview-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 8px; }.trace-overview-heading h3 { font-size: 18px; font-weight: 650; margin: 0; }.trace-copy-id { display: flex; align-items: center; gap: 5px; max-width: 100%; padding: 4px 6px; border: 0; border-radius: 6px; background: #f5f7fb; color: #68768a; font-size: 10px; word-break: break-all; text-align: left; cursor: pointer; }
.trace-metrics { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 12px; padding: 20px 0 12px; }.trace-metrics > div { display: grid; align-content: start; gap: 4px; }.trace-metrics span { font-size: 11px; color: #68768a; }.trace-metrics strong { font-size: 23px; font-weight: 650; line-height: 1.5; }.trace-metrics small { font-size: 10px; font-weight: 400; color: #68768a; }.trace-note { color: #68768a; font-size: 11px; line-height: 1.8; }.trace-inline-alert { margin: 12px 24px; }.trace-error { color: #b54542; font-size: 12px; line-height: 1.7; }
.trace-view-tabs { display: flex; gap: 20px; padding: 0 24px; border-bottom: 1px solid #edf0f5; flex-shrink: 0; overflow-x: auto; }.trace-view-tabs button { display: inline-flex; align-items: center; gap: 6px; min-height: 42px; padding: 0 0 8px; white-space: nowrap; border: 0; border-bottom: 2px solid transparent; color: #68768a; background: transparent; cursor: pointer; font-size: 12px; transition: color .18s,border-color .18s; }.trace-view-tabs button.active { color: #2563eb; border-bottom-color: #2563eb; font-weight: 600; }
.trace-scroll-area { flex: 1; min-height: 0; overflow-y: auto; padding: 20px 24px; }.trace-filter-row { display: flex; align-items: center; gap: 12px; }.trace-filter-row :deep(.el-input) { flex: 1; }.trace-filter-row > span { color: #68768a; font-size: 10px; white-space: nowrap; }.trace-filter-chips { display: flex; gap: 6px; margin: 14px 0 22px; overflow-x: auto; }.trace-filter-chips button { font-size: 10px; padding: 6px 9px; border-radius: 8px; border: 1px solid #e7ebf1; background: #fff; color: #68768a; cursor: pointer; white-space: nowrap; transition: background .18s,border-color .18s; }.trace-filter-chips button.active { background: #eff5ff; border-color: #cddfff; color: #2563eb; }
.trace-timeline { padding: 0; margin: 0; list-style: none; }.trace-timeline li { position: relative; }.trace-timeline li:not(:last-child)::before { position: absolute; content: ''; top: 35px; bottom: -8px; left: 24px; width: 1px; background: #e7edf5; }.trace-event { display: flex; align-items: flex-start; width: 100%; gap: 12px; padding: 12px 8px; border: 1px solid transparent; border-radius: 12px; background: transparent; color: inherit; text-align: left; cursor: pointer; transition: background .18s,border-color .18s; }.trace-event:hover { background: #f8faff; }.trace-event.selected { background: #f3f7ff; border-color: #d5e3ff; }.trace-event-marker { position: relative; z-index: 1; display: grid; place-items: center; width: 32px; height: 32px; border-radius: 10px; font-size: 15px; flex-shrink: 0; background: #eff5ff; color: #2563eb; }.trace-event-marker.success { color: #167653; background: #ecf8f1; }.trace-event-marker.danger { color: #b54542; background: #fff0ef; }.trace-event-marker.muted { color: #68768a; background: #eff2f6; }.trace-event-content { flex: 1; min-width: 0; display: grid; gap: 6px; }.trace-event-top { display: flex; align-items: center; gap: 8px; }.trace-event-top strong { font-size: 12px; font-weight: 600; }.trace-event-top small { font-size: 9px; color: #8190a5; }.trace-event-subtitle { font-size: 11px; color: #68768a; overflow-wrap: anywhere; }.trace-parent-label { font-size: 9px; color: #8190a5; overflow-wrap: anywhere; }.trace-event-timing { display: grid; gap: 5px; text-align: right; flex-shrink: 0; }.trace-event-timing strong { font-size: 10px; color: #526078; font-weight: 500; }.trace-event-timing small { font-size: 9px; color: #8190a5; }.trace-event-arrow { color: #8190a5; margin-top: 5px; font-size: 12px; }.trace-load-footer { display: grid; gap: 10px; justify-items: start; padding-top: 20px; }.trace-empty-note { font-size: 12px; color: #68768a; line-height: 1.8; padding: 20px 6px; }.trace-idle { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 30px; text-align: center; color: #68768a; }.trace-idle > .el-icon { color: #a7bfe9; font-size: 40px; }.trace-idle h3 { font-size: 16px; color: #334155; margin: 18px 0 10px; }.trace-idle p { font-size: 12px; line-height: 1.8; }
.trace-results h4,.trace-inspector h4 { font-size: 12px; margin: 16px 0 12px; }.trace-results :deep(.agent-result) { margin: 16px 0; }.trace-evidence-note { display: flex; align-items: flex-start; gap: 10px; padding: 14px; margin-top: 20px; border: 1px solid #e7edf7; background: #f7faff; border-radius: 12px; font-size: 11px; line-height: 1.8; color: #68768a; }.trace-evidence-note > .el-icon { font-size: 16px; margin-top: 2px; flex-shrink: 0; }.trace-evidence-note strong { color: #526078; }.trace-evidence-note p { margin: 4px 0 0; }.trace-json { white-space: pre-wrap; overflow-wrap: anywhere; padding: 16px; margin-top: 14px; background: #f7f9fc; border: 1px solid #e7ebf1; border-radius: 12px; font: 11px/1.8 Consolas,monospace; }
.trace-workspace.has-inspector { grid-template-columns: 216px minmax(0,1fr) 286px; }.trace-inspector { min-width: 0; min-height: 0; overflow-y: auto; border-left: 1px solid #e7ebf1; padding: 22px 18px; background: #fff; }.trace-inspector > header { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 22px; }.trace-inspector h3 { font-size: 15px; margin: 6px 0 0; }.trace-inspector h3 small { color: #8190a5; font-size: 10px; }.trace-event-kind { display: inline-flex; padding: 6px 9px; color: #2563eb; background: #eff5ff; border-radius: 8px; font-size: 11px; }.trace-event-kind.danger { color: #b54542; background: #fff0ef; }.trace-detail-list { display: grid; grid-template-columns: 86px minmax(0,1fr); gap: 12px 8px; padding: 20px 0; margin: 0; font-size: 11px; line-height: 1.7; }.trace-detail-list dt { color: #68768a; }.trace-detail-list dd { margin: 0; overflow-wrap: anywhere; }.trace-related-event { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; border: 1px solid #e7ebf1; background: #f8faff; border-radius: 8px; padding: 10px; margin-bottom: 6px; text-align: left; font-size: 11px; color: #526078; cursor: pointer; overflow-wrap: anywhere; }.trace-related-event .el-icon { flex-shrink: 0; }.trace-icon-button { display: grid; place-items: center; min-width: 32px; min-height: 32px; border: 0; background: #f5f7fb; border-radius: 8px; color: #68768a; cursor: pointer; }.history-toggle,.trace-history-mask { display: none; }.trace-inspector-enter-active,.trace-inspector-leave-active { transition: opacity .18s,transform .18s; }.trace-inspector-enter-from,.trace-inspector-leave-to { opacity: 0; transform: translateX(12px); }
@media (max-width: 1450px) { .trace-workspace.has-inspector { grid-template-columns: 216px minmax(0,1fr); }.trace-inspector { position: fixed; z-index: 90; top: 0; bottom: 0; right: 0; width: min(340px,100vw); box-shadow: -12px 0 40px #19315520; } }
@media (max-width: 1100px) { .trace-workspace,.trace-workspace.has-inspector { grid-template-columns: minmax(0,1fr); position: relative; }.trace-history { display: none; }.history-toggle { display: grid; }.history-open .trace-history { display: flex; position: absolute; top: 0; bottom: 0; left: 0; width: min(270px,calc(100% - 40px)); z-index: 42; box-shadow: 12px 0 30px #19315520; }.history-open .trace-history-mask { display: block; position: absolute; inset: 0; z-index: 41; background: #19315533; border: 0; }.trace-page-header { grid-column: 1; } }
@media (max-width: 640px) { .trace-workspace { border-radius: 12px; }.trace-page-header { padding: 14px; gap: 8px; }.trace-page-title { gap: 8px; }.trace-page-title h2 { font-size: 14px; }.trace-page-title p { display: none; }.trace-brand { width: 30px; height: 30px; font-size: 16px; }.trace-page-actions { gap: 4px; }.trace-page-actions :deep(.el-button) { padding: 8px; }.trace-page-actions :deep(.el-button span span) { display: none; }.trace-run-toolbar { padding: 10px 12px; gap: 8px; }.trace-run-overview { padding: 18px 14px 8px; }.trace-metrics { grid-template-columns: repeat(2,minmax(0,1fr)); gap: 14px; }.trace-view-tabs { padding: 0 14px; gap: 18px; }.trace-scroll-area { padding: 14px; }.trace-filter-row > span { display: none; }.trace-event { gap: 8px; padding-inline: 0; }.trace-event-arrow { display: none; }.trace-event-timing { max-width: 68px; }.trace-event-top { align-items: flex-start; }.trace-event-top strong { font-size: 11px; }.trace-run-heading { gap: 6px; }.trace-run-toolbar > .trace-run-heading > span:last-child { font-size: 10px; }.trace-overview-heading h3 { font-size: 16px; } }
@media (prefers-reduced-motion: reduce) { .trace-run,.trace-event,.trace-filter-chips button,.trace-view-tabs button,.trace-inspector-enter-active,.trace-inspector-leave-active { transition: none; transform: none; } }
.trace-model-request { border: 1px solid #e7ebf1; border-radius: 12px; padding: 16px; margin: 14px 0; overflow-wrap: anywhere; }
.trace-model-request h4 { margin: 0; font-size: 13px; }.trace-model-attempt { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; padding: 12px 0; border-top: 1px solid #edf0f5; font-size: 12px; }.trace-model-attempt p { margin: 6px 0 0; }.trace-model-attempt .trace-icon-button { flex-shrink: 0; }
.trace-status.error { color: #b54542; background: #fff0ef; }
</style>
