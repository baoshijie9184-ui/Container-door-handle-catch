<template>
  <section class="agent-result" aria-label="助手业务结果">
    <p class="result-answer">{{ envelope?.text || '此卡片消息无法解析 请重新查询' }}</p>
    <template v-if="envelope">
      <header class="result-heading">
        <span>业务数据按当前权限刷新</span>
        <el-button size="small" :loading="loading" @click="refresh">刷新卡片</el-button>
      </header>
      <p v-if="error" class="result-error" role="alert">{{ error }}</p>
      <p v-if="loading && !views.length" role="status">正在读取业务数据</p>
      <TransitionGroup name="result-card" tag="div" class="result-cards">
        <article v-for="(card, index) in views" :key="index + ':' + card.tool" class="result-card" :aria-busy="loading">
          <header><strong>{{ cardTitle(card) }}</strong><span class="scope-label">{{ cardScope(card.scope) }}</span></header>
          <template v-if="card.type === 'METRICS'">
            <p class="card-period">{{ formatDate(card.from) }} 至 {{ formatDate(card.to) }}</p>
            <div class="card-metrics"><div v-for="(label, key) in metricLabels" :key="key"><strong>{{ card.metrics?.[key] ?? '—' }}</strong><span>{{ label }}</span></div></div>
          </template>
          <template v-else-if="card.type === 'TASKS'">
            <div v-for="task in card.items || []" :key="task.taskId" class="card-record">
              <a :href="cardRoute('TASKS', task.taskId)">{{ task.taskId }}</a>
              <p>状态 {{ task.status || '未知' }} · 图片 {{ task.processedImages ?? 0 }}/{{ task.totalImages ?? 0 }} · 缺陷 {{ task.defectCount ?? 0 }}</p>
              <p>设备 {{ task.deviceName || '未记录' }} · 复核 {{ task.reviewStatus || '未复核' }}</p>
            </div>
          </template>
          <template v-else-if="card.type === 'REPORTS'">
            <div v-for="report in card.items || []" :key="report.reportId" class="card-record">
              <a :href="cardRoute('REPORTS', report.reportId)">{{ report.title }}</a>
              <p>{{ reportStatus(report.status) }} · 版本 {{ report.version }} · 任务 {{ report.taskId }}</p>
              <p v-if="report.status === 'DRAFT'" class="draft-note">私人草稿尚未提交或审批 请到报告页面核对</p>
              <a class="record-action" :href="cardRoute('REPORTS', report.reportId)">查看报告</a>
            </div>
          </template>
          <p class="card-note" :class="{ 'result-error': card.status !== 'OK' }">{{ card.message }}</p>
          <footer>更新 {{ formatDate(card.updatedAt) }}</footer>
        </article>
      </TransitionGroup>
    </template>
  </section>
</template>
<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { resolveAgentCards } from '@/api/chatAssistant'
import { parseAgentCardEnvelope, cardRoute, cardTitle, cardScope, reportStatus, metricLabels } from '@/utils/agentCards'
const props = defineProps({ message: { type: Object, required: true } })
const envelope = computed(() => parseAgentCardEnvelope(props.message.content))
const views = ref([]), loading = ref(false), error = ref('')
let generation = 0
const formatDate = value => value ? String(value).replace('T', ' ').slice(0, 19) : '—'
async function refresh() {
  const current = envelope.value
  if (!current) return
  const version = ++generation
  views.value = []; loading.value = true; error.value = ''
  try {
    const response = await resolveAgentCards(current.cards)
    if (version === generation) views.value = response.data.cards
  } catch {
    if (version === generation) error.value = '卡片数据暂不可用 请检查登录状态后刷新'
  } finally { if (version === generation) loading.value = false }
}
watch(() => props.message.content, () => { generation++; views.value = []; error.value = ''; loading.value = false; refresh() }, { immediate: true })
onBeforeUnmount(() => generation++)
</script>
<style scoped>
.agent-result{padding:16px;border:1px solid #dce7f6;border-radius:16px;background:#fff;min-width:0;max-width:100%}.result-answer{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7;margin:0 0 14px}.result-heading,.result-card>header{display:flex;align-items:center;justify-content:space-between;gap:12px}.result-heading,.scope-label,.card-period,.card-note,footer{font-size:12px;color:#66758b}.result-cards{display:grid;gap:12px;margin-top:12px}.result-card{padding:14px;background:#f7faff;border:1px solid #e1e9f4;border-radius:12px;min-width:0;overflow-wrap:anywhere}.card-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:12px 0}.card-metrics>div{display:grid;gap:4px}.card-metrics strong{font-size:23px;color:#1764cc}.card-metrics span,.card-record p{font-size:12px;color:#53647d}.card-record{padding:12px 0;border-bottom:1px solid #e3eaf4}.card-record:last-of-type{border-bottom:0}.card-record>a{color:#1764cc;text-decoration:none;transition:color .15s ease}.card-record>a:hover{color:#09479b}.card-record p{line-height:1.6;margin:6px 0}.card-record .draft-note{color:#8a560b}.record-action{font-size:12px}.result-error{color:#a52d2d}.card-note{line-height:1.6}footer{margin-top:12px}.result-card-enter-active,.result-card-leave-active{transition:opacity .18s ease,transform .18s ease}.result-card-enter-from,.result-card-leave-to{opacity:0;transform:translateY(4px)}.result-heading :deep(button){transition:transform .15s ease}.result-heading :deep(button:hover:not(:disabled)){transform:scale(1.02)}.result-heading :deep(button:active:not(:disabled)){transform:scale(.98)}@media(prefers-reduced-motion:reduce){.result-card-enter-active,.result-card-leave-active,.result-heading :deep(button),.card-record>a{transition:none}.result-card-enter-from,.result-card-leave-to{transform:none}}@media(max-width:480px){.agent-result{padding:12px}.result-heading{align-items:flex-start}.result-card{padding:12px}}
</style>
