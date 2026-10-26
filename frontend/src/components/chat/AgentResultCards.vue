<template>
  <section class="agent-result" aria-label="助手业务结果">
    <AgentMarkdown class="result-answer" :text="envelope?.text || '此卡片消息无法解析 请重新查询'" />
    <template v-if="envelope?.cards.length">
      <p class="result-freshness-note">回答保留生成时的内容，下方卡片按当前权限重新读取。</p>
      <header class="result-heading">
        <span><AppIcon name="Collection" :size="16" />业务卡片<span class="result-read-count">已有 {{ views.length }} / {{ envelope.cards.length }} 张回执</span></span>
        <el-button size="small" :loading="loading" @click="refresh"><AppIcon name="Refresh" :size="14" />重新读取</el-button>
      </header>
      <p v-if="error" class="result-read-feedback" data-tone="warning" role="alert"><AppIcon name="Warning" :size="16" /><span>{{ error }}</span></p>
      <p v-else class="result-read-feedback" :data-tone="loading ? 'loading' : 'info'" role="status"><AppIcon :name="loading ? 'Connection' : 'DocumentChecked'" :size="16" /><span>{{ loading ? views.length ? '正在重新核对，以下仍为上次读取的快照。' : '正在按当前账号权限读取业务数据。' : '下方为最近一次读取的快照，业务操作仍需进入对应页面核对。' }}</span></p>
      <TransitionGroup name="result-card" tag="div" class="result-cards">
        <article v-for="(card, index) in views" :key="index + ':' + card.tool" class="result-card" :aria-busy="loading">
          <header><span class="result-card-symbol"><AppIcon :name="cardIcon(card)" :size="19" /></span><div class="result-card-heading"><strong>{{ cardTitle(card) }}</strong><small>{{ cardScope(card.scope) || '访问范围未返回' }}</small></div><StatusBadge domain="cardRead" :code="card.status" /></header>
          <template v-if="card.type === 'METRICS'">
            <p class="card-period">按任务创建时间 · {{ formatDate(card.from) }} 至 {{ formatDate(card.to) }} · UTC+8</p>
            <div class="card-metrics"><div v-for="(label, key) in metricLabels" :key="key"><strong>{{ cardCount(card.metrics?.[key]) }}</strong><span>{{ label }}</span></div></div>
          </template>
          <template v-else-if="card.type === 'TASKS'">
            <div v-for="task in card.items || []" :key="task.taskId" class="card-record">
              <a :href="cardRoute('TASKS', task.taskId)">{{ task.taskId }}</a>
              <p><StatusBadge domain="detection" :code="task.status" /> · 已处理 / 总图片 {{ cardCount(task.processedImages) }} / {{ cardCount(task.totalImages) }} · 缺陷 {{ cardCount(task.defectCount) }}</p>
              <p>设备 {{ task.deviceName || '未记录' }} · <StatusBadge domain="review" :code="task.reviewStatus" /></p>
            </div>
          </template>
          <template v-else-if="card.type === 'REPORTS'">
            <div v-for="report in card.items || []" :key="report.reportId" class="card-record">
              <a :href="cardRoute('REPORTS', report.reportId)">{{ report.title || '未命名报告' }}</a>
              <p><StatusBadge domain="report" :code="report.status" :label="reportStatus(report.status)" /> · 版本 {{ cardVersion(report.version) }} · 任务 {{ report.taskId || '未记录' }}</p>
              <p v-if="report.status === 'DRAFT'" class="draft-note">私人草稿尚未提交或审批 请到报告页面核对</p>
              <a class="record-action" :href="cardRoute('REPORTS', report.reportId)">查看报告</a>
            </div>
          </template>
          <template v-else-if="card.type === 'DEVICES'">
            <div v-for="device in card.items || []" :key="device.deviceId" class="card-record">
              <a :href="cardRoute('DEVICES', device.deviceId)">{{ device.deviceCode || '设备 ' + device.deviceId }}</a>
              <dl class="card-device-states"><div v-for="field in cardDeviceFields" :key="field.key"><dt>{{ field.label }}</dt><dd><StatusBadge :domain="field.domain" :code="device[field.key]" /></dd></div></dl>
              <a class="record-action" :href="cardRoute('DEVICES', device.deviceId)">查看设备</a>
            </div>
            <p class="card-note">状态来自本次读取的设备记录，不是持续监控或当前健康证明。</p>
          </template>
          <template v-else-if="card.type === 'DEVICE_ALERTS'">
            <div v-for="alert in card.items || []" :key="alert.alertId" class="card-record">
              <div class="card-alert-heading"><strong>{{ alert.alertCode || '告警 ' + alert.alertId }}</strong><StatusBadge domain="deviceAlert" :code="alert.status" :label="alertStatus(alert.status)" /></div>
              <div class="card-alert-classification"><span>{{ alertType(alert.type) }}</span><StatusBadge domain="deviceAlertLevel" :code="alert.level" :label="alertLevel(alert.level)" /></div>
              <p>设备 {{ alert.deviceCode || '未记录' }}</p>
              <dl class="card-record-facts"><dt>发生 · UTC+8</dt><dd>{{ formatDate(alert.createdAt) }}</dd><dt>记录更新 · UTC+8</dt><dd>{{ formatDate(alert.updatedAt) }}</dd></dl>
              <details class="card-alert-identity"><summary>核对告警编号与类型代码<AppIcon class="card-alert-chevron" name="ArrowDown" :size="13" /></summary><dl class="card-record-facts"><dt>告警 ID</dt><dd>{{ alert.alertId }}</dd><dt>设备 ID</dt><dd>{{ alert.deviceId || '未记录' }}</dd><dt>类型代码</dt><dd>{{ alert.type || '未记录' }}</dd></dl></details>
              <a v-if="cardRoute('DEVICES', alert.deviceId)" class="record-action" :href="cardRoute('DEVICES', alert.deviceId)">查看设备</a>
              <p v-else>设备关联已不可用</p>
            </div>
            <p class="card-note">按告警记录展示 不代表设备当前仍故障或已修复</p>
          </template>
          <template v-else-if="card.type === 'MODELS'">
            <div v-for="model in card.items || []" :key="model.modelId" class="card-record">
              <a :href="cardRoute('MODELS', String(model.modelId))">{{ model.name || '模型 ' + model.modelId }}</a>
              <p>版本 {{ model.version || '未记录' }} · {{ modelStatus(model.status) }} · {{ model.defaultModel === true ? '默认模型' : model.defaultModel === false ? '非默认模型' : '默认状态未知' }}</p>
              <a class="record-action" :href="cardRoute('MODELS', String(model.modelId))">查看模型</a>
            </div>
          </template>
          <template v-else-if="card.type === 'MODEL_OPERATIONS'">
            <div v-for="item in card.items || []" :key="item.model.modelId" class="card-record model-operation">
              <a :href="cardRoute('MODEL_OPERATIONS', String(item.model.modelId))">{{ item.model.name || '模型 ' + item.model.modelId }}</a>
              <p>版本 {{ item.model.version || '未记录' }} · {{ modelStatus(item.model.status) }}</p>
              <div class="card-metrics operation-metrics"><div v-for="metric in modelOperationMetrics(item)" :key="metric.label"><strong>{{ metric.value }}</strong><span>{{ metric.label }} 登记值</span></div></div>
              <details v-if="modelOperationLegacyMetrics(item).length" class="operation-disclosure"><summary>其他历史指标</summary><dl class="operation-details"><div v-for="metric in modelOperationLegacyMetrics(item)" :key="metric.label"><dt>{{ metric.label }}</dt><dd>{{ metric.value }}</dd></div></dl></details>
              <details class="operation-disclosure"><summary>查看发布配置与登记信息</summary>
                <dl class="operation-details"><div v-for="row in modelOperationDetails(item)" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div></dl>
              </details>
              <p v-if="item.invalidFields?.length" class="result-error">部分登记字段异常 请到模型页面核对</p>
              <p class="card-note">指标为登记值，未检出率排除执行失败，Normal 检出也算检出。FPS 测试环境见模型详情；发布策略为配置记录，实际分流尚未核验。</p>
              <a class="record-action" :href="cardRoute('MODEL_OPERATIONS', String(item.model.modelId))">查看模型</a>
            </div>
          </template>
          <p v-if="card.type !== 'METRICS' && !card.items.length" class="card-empty"><AppIcon :name="card.status === 'OK' ? 'Files' : 'Warning'" :size="18" />{{ cardEmptyText(card) }}</p>
          <p v-if="card.message" class="card-note" :class="{ 'result-error': card.status !== 'OK' }">{{ card.message }}</p>
          <footer>卡片读取时间 {{ formatDate(card.updatedAt) }} · UTC+8</footer>
        </article>
      </TransitionGroup>
    </template>
  </section>
</template>
<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import AgentMarkdown from './AgentMarkdown.vue'
import { beijingDateTime } from '@/utils/beijingTime'
import { resolveAgentCards } from '@/api/chatAssistant'
import { useUserStore } from '@/stores/user'
import { parseAgentCardEnvelope, readResolvedAgentCards, cardIcon, cardCount, cardVersion, cardEmptyText, cardRoute, cardTitle, cardScope, reportStatus, metricLabels, cardDeviceFields, modelStatus, alertStatus, alertLevel, alertType, modelOperationMetrics, modelOperationLegacyMetrics, modelOperationDetails } from '@/utils/agentCards'
const props = defineProps({ message: { type: Object, required: true } })
const userStore = useUserStore()
const actor = computed(() => JSON.stringify([userStore.identity?.userId || userStore.username || '',userStore.role,userStore.isAuthenticated]))
const envelope = computed(() => parseAgentCardEnvelope(props.message.content))
const views = ref([]), loading = ref(false), error = ref('')
let generation = 0, activeRead = null, disposed = false
const formatDate = value => value ? beijingDateTime(value) || '时间格式未知' : '—'
async function refresh() {
  const current = envelope.value
  if (disposed || !current?.cards.length || loading.value) return
  if (!userStore.isAuthenticated) { views.value = []; error.value = '登录状态未确认，请重新核对账号后读取卡片。'; return }
  const version = ++generation
  const controller = new AbortController()
  activeRead = controller
  loading.value = true; error.value = ''
  try {
    const response = await resolveAgentCards(current.cards, { signal:controller.signal })
    if (version === generation) views.value = readResolvedAgentCards(response.data, current.cards)
  } catch (failure) {
    if (version !== generation) return
    const status = failure.response?.status
    if (status === 401 || status === 403) {
      views.value = []
      error.value = status === 401 ? '登录状态已失效，已清除旧卡片；请核对账号后重新读取。' : '当前账号无法读取这些卡片，已清除旧数据；请核对访问权限。'
    } else error.value = views.value.length ? '本次读取未完成，以下保留上次读取的快照，不代表当前业务状态。可重新读取，不会重新执行业务操作。' : '业务卡片暂未读出，请重新读取。此操作只核对业务资料，不重新调用模型或执行审批。'
  } finally { if (version === generation) { activeRead = null; loading.value = false } }
}
watch(() => [props.message.content,actor.value], () => { generation++; activeRead?.abort(); activeRead = null; views.value = []; error.value = ''; loading.value = false; refresh() }, { immediate: true, flush:'sync' })
onBeforeUnmount(() => { disposed = true; generation++; activeRead?.abort(); activeRead = null })
</script>
<style scoped>
.model-operation .operation-metrics strong{font-size:20px}
.operation-metrics strong{font-size:20px}.operation-disclosure{margin:12px 0}.operation-disclosure summary{color:#1764cc;font-size:12px;cursor:pointer;padding:6px 0}.operation-disclosure summary:focus-visible{outline:2px solid #1764cc;outline-offset:3px}.operation-details{display:grid;gap:8px;margin:12px 0;font-size:12px}.operation-details>div{display:grid;grid-template-columns:100px minmax(0,1fr);gap:8px}.operation-details dt{color:#66758b}.operation-details dd{margin:0;overflow-wrap:anywhere}.operation-disclosure[open] .operation-details{animation:operation-open .18s ease}@keyframes operation-open{from{opacity:0;transform:translateY(3px)}to{opacity:1;transform:none}}@media(prefers-reduced-motion:reduce){.operation-disclosure[open] .operation-details{animation:none}}
.agent-result{padding:16px;border:1px solid #dce7f6;border-radius:16px;background:#fff;min-width:0;max-width:100%}.result-answer{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7;margin:0 0 14px}.result-heading,.result-card>header{display:flex;align-items:center;justify-content:space-between;gap:12px}.result-heading,.scope-label,.card-period,.card-note,footer{font-size:12px;color:#66758b}.result-cards{display:grid;gap:12px;margin-top:12px}.result-card{padding:14px;background:#f7faff;border:1px solid #e1e9f4;border-radius:12px;min-width:0;overflow-wrap:anywhere}.card-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:12px 0}.card-metrics>div{display:grid;gap:4px}.card-metrics strong{font-size:23px;color:#1764cc}.card-metrics span,.card-record p{font-size:12px;color:#53647d}.card-record{padding:12px 0;border-bottom:1px solid #e3eaf4}.card-record:last-of-type{border-bottom:0}.card-record>a{color:#1764cc;text-decoration:none;transition:color .15s ease}.card-record>a:hover{color:#09479b}.card-record p{line-height:1.6;margin:6px 0}.card-record .draft-note{color:#8a560b}.record-action{font-size:12px}.result-error{color:#a52d2d}.card-note{line-height:1.6}footer{margin-top:12px}.result-card-enter-active,.result-card-leave-active{transition:opacity .18s ease,transform .18s ease}.result-card-enter-from,.result-card-leave-to{opacity:0;transform:translateY(4px)}.result-heading :deep(button){transition:transform .15s ease}.result-heading :deep(button:hover:not(:disabled)){transform:scale(1.02)}.result-heading :deep(button:active:not(:disabled)){transform:scale(.98)}@media(prefers-reduced-motion:reduce){.result-card-enter-active,.result-card-leave-active,.result-heading :deep(button),.card-record>a{transition:none}.result-card-enter-from,.result-card-leave-to{transform:none}}@media(max-width:480px){.agent-result{padding:12px}.result-heading{align-items:flex-start}.result-card{padding:12px}}
</style>
