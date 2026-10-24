<template>
  <div class="business-card">
    <div class="business-head">
      <span class="business-icon">
        <AppIcon name="DocumentCopy" :size="19" />
      </span>
      <div>
        <div class="business-title">{{ payload.title || '业务卡片' }}</div>
        <div class="business-desc">{{ payload.description || '已为你整理相关业务入口。' }}</div>
      </div>
    </div>
    <p class="business-snapshot-note"><AppIcon name="Clock" :size="15" /><span>消息中的业务快照 · {{ historicalTime(message.createdAt) }}（UTC+8）<br/>以下内容保留当时回答，当前数据和可用操作请进入业务页面重新核对。</span></p>

    <template v-if="isQualityQueue || isBatchTrace || isWorkOrderTrace || isDefectGallery || isAgentHealth">
      <div v-if="sources.length" class="source-strip">
        <span class="source-label">来源</span>
        <span v-for="source in sources" :key="`${source.type}-${source.detail}`" class="source-chip">
          {{ source.type }}<small v-if="source.detail">：{{ source.detail }}</small>
        </span>
      </div>

      <div class="metric-grid">
        <div
          v-for="metric in metrics"
          :key="metric.label"
          class="metric-card"
          :class="`tone-${metric.tone || 'blue'}`"
        >
          <span class="metric-value">{{ legacyValue(metric.value) }}</span>
          <span class="metric-label">{{ metric.label }}</span>
        </div>
      </div>

      <div class="quality-actions">
        <a v-if="isRoute(payload.route)" class="route-btn" :href="payload.route">
          {{ traceRouteText }}
        </a>
        <button
          v-for="action in textRows(payload.actions)"
          :key="action"
          class="example-chip"
          type="button"
          @click="$emit('send', action)"
        >
          {{ action }}
        </button>
      </div>

      <div v-if="isAgentHealth" class="agent-health-mini">
        <div class="agent-health-status" :class="`status-${String(payload.status || 'UNKNOWN').toLowerCase()}`">
          <span class="status-dot"></span>
          <strong>{{ payload.status || 'UNKNOWN' }}</strong>
          <span>快照记录更新 {{ historicalTime(payload.health?.lastUpdatedAt) }} · UTC+8</span>
        </div>
        <div class="trace-context">
          <span>最近退出 {{ payload.health?.lastExitReason || 'UNKNOWN' }}</span>
          <span>快照中的备用率 {{ legacyValue(payload.health?.fallbackRate) }}</span>
        </div>
        <p class="agent-health-reason">
          最近守卫原因：{{ payload.health?.lastGuardReason || '暂无' }}
        </p>
      </div>

      <div v-else-if="isDefectGallery" class="defect-gallery-mini">
        <div class="trace-context">
          <span>类型 {{ payload.filters?.defectType || '全部' }}</span>
          <span>等级 {{ payload.filters?.severityLevel || '全部' }}</span>
          <span>设备 {{ payload.filters?.deviceName || '全部' }}</span>
          <span>批次 {{ payload.filters?.batchNo || '全部' }}</span>
        </div>
        <div v-if="defectRecords.length" class="task-list">
          <article v-for="task in defectRecords" :key="task.taskId" class="task-card">
            <div class="task-main">
              <a v-if="legacyTaskRoute(task.taskId)" class="task-id" :href="legacyTaskRoute(task.taskId)">{{ task.taskId }}</a><span v-else class="task-id">任务编号未记录或不可用</span>
              <StatusBadge domain="severity" :code="task.maxDefectSeverity" />
            </div>
            <div class="task-meta">
              <span>缺陷 {{ task.primaryDefectType || '未知' }}</span>
              <span>设备 {{ task.deviceName || '未知' }}</span>
              <span>批次 {{ task.batchNo || '未知' }}</span>
            </div>
            <div class="task-status">
              <span>数量 {{ count(task.defectCount) }}</span>
              <StatusBadge domain="review" :code="task.reviewStatus" />
              <span>证据 {{ evidenceCount(task.defectEvidence) }}</span>
            </div>
          </article>
        </div>
      </div>

      <div v-else-if="isBatchTrace || isWorkOrderTrace" class="batch-trace-mini">
        <div class="trace-context">
          <span>{{ tracePrimaryLabel }} {{ tracePrimaryValue }}</span>
          <span>{{ isWorkOrderTrace ? '批次' : '设备' }} {{ secondaryContextText }}</span>
          <span>模型 {{ contextList(payload.summary?.models).join('、') || '未知' }}</span>
        </div>
        <div class="trace-quality">
          <span>待复核 {{ count(payload.quality?.pendingReview) }}</span>
          <span>已处置 {{ count(payload.quality?.disposed) }}</span>
          <span>需返工 {{ count(payload.quality?.reworkRequired) }}</span>
          <span>需复检 {{ count(payload.quality?.recheckRequired) }}</span>
        </div>
        <div v-if="batchRecords.length" class="task-list">
          <article v-for="task in batchRecords" :key="task.taskId" class="task-card">
            <div class="task-main">
              <a v-if="legacyTaskRoute(task.taskId)" class="task-id" :href="legacyTaskRoute(task.taskId)">{{ task.taskId }}</a><span v-else class="task-id">任务编号未记录或不可用</span>
              <StatusBadge domain="severity" :code="task.maxDefectSeverity" />
            </div>
            <div class="task-meta">
              <span>工单 {{ task.workOrderNo || '未知' }}</span>
              <span>设备 {{ task.deviceName || '未知' }}</span>
              <span>缺陷 {{ count(task.defectCount) }}</span>
            </div>
            <div class="task-status">
              <StatusBadge domain="detection" :code="task.status" />
              <StatusBadge domain="flow" :code="task.flowStatus" />
              <StatusBadge domain="review" :code="task.reviewStatus" />
            </div>
          </article>
        </div>
      </div>

      <div class="task-list" v-else-if="tasks.length">
        <article v-for="task in tasks" :key="task.taskId" class="task-card">
          <div class="task-main">
            <a v-if="isRoute(task.route)" class="task-id" :href="task.route">{{ task.taskId || '任务编号未记录' }}</a><span v-else class="task-id">{{ task.taskId || '任务编号未记录' }}</span>
            <StatusBadge domain="severity" :code="task.severity" />
          </div>
          <div class="task-meta">
            <span>工单 {{ task.workOrderNo }}</span>
            <span>批次 {{ task.batchNo }}</span>
            <span>责任人 {{ task.assignee }}</span>
          </div>
          <div class="task-status">
            <span>{{ task.flowStatus }}</span>
            <span>复核 {{ task.reviewStatus }}</span>
            <span>处置 {{ task.dispositionStatus }}</span>
            <span>缺陷 {{ count(task.defectCount) }}</span>
          </div>
          <p v-if="task.primaryDefectType && task.primaryDefectType !== '未知'" class="task-defect">
            主要缺陷：{{ task.primaryDefectType }}
          </p>
        </article>
      </div>
    </template>

    <div v-else class="business-grid">
      <article v-for="card in cards" :key="card.title" class="module-card">
        <div class="module-top">
          <h4>{{ card.title }}</h4>
          <span class="agent-tag">{{ card.agent }}</span>
        </div>
        <p>{{ card.summary }}</p>
        <a v-if="isRoute(card.route)" class="route-btn" :href="card.route">
          进入页面
          <AppIcon name="ArrowRight" :size="14" />
        </a>
        <span v-else class="route-note">此历史入口暂不可用，请从系统导航进入</span>
        <div class="example-list">
          <button
            v-for="example in textRows(card.examples)"
            :key="example"
            class="example-chip"
            type="button"
            @click="$emit('send', example)"
          >
            {{ example }}
          </button>
        </div>
      </article>
    </div>

    <div v-if="payload.note" class="business-note">{{ payload.note }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { knownCount } from '@/utils/countPresentation'
import { beijingDateTime } from '@/utils/beijingTime'

const props = defineProps({
  message: { type: Object, required: true }
})

defineEmits(['send'])
const router=useRouter()
const historicalTime=value=>value?beijingDateTime(value)||'时间格式未知':'时间未记录'
const count=value=>knownCount(value)?.toLocaleString('zh-CN')??'未记录'
const legacyValue=value=>typeof value==='string'&&value.trim()?value:typeof value==='number'&&Number.isFinite(value)?value.toLocaleString('zh-CN'):'未记录'
const objectRows=value=>Array.isArray(value)?value.filter(row=>row&&typeof row==='object'&&!Array.isArray(row)):[]
const textRows=value=>Array.isArray(value)?value.filter(item=>typeof item==='string'&&item.trim()):[]

const payload = computed(() => {
  try {
    // Agent 可能在 JSON 后追加“来源：...”说明，先截取完整 JSON 对象再解析。
    const raw = String(props.message.content || '').trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/i, '')
    const start = raw.indexOf('{')
    const end = raw.lastIndexOf('}')
    const value=JSON.parse(start >= 0 && end > start ? raw.slice(start, end + 1) : raw)
    if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('业务快照格式无效')
    return value
  } catch {
    return {
      title: '业务卡片解析失败',
      description: props.message.content || '',
      cards: []
    }
  }
})

const cards = computed(() => objectRows(payload.value.cards))
const isQualityQueue = computed(() => payload.value.type === 'quality-queue')
const isBatchTrace = computed(() => payload.value.type === 'batch-trace')
const isWorkOrderTrace = computed(() => payload.value.type === 'work-order-trace')
const isDefectGallery = computed(() => payload.value.type === 'defect-gallery')
const isAgentHealth = computed(() => payload.value.type === 'agent-health')
const metrics = computed(() => objectRows(payload.value.metrics))
const tasks = computed(() => objectRows(payload.value.tasks))
const sources = computed(() => objectRows(payload.value.sources))
const batchRecords = computed(() => objectRows(payload.value.records).slice(0,5))
const defectRecords = batchRecords
const traceRouteText = computed(() => {
  if (isAgentHealth.value) return '查看健康详情'
  if (isDefectGallery.value) return '进入缺陷证据库'
  if (isBatchTrace.value) return '进入批次追溯'
  if (isWorkOrderTrace.value) return '查看工单任务'
  return '进入质检队列'
})
const tracePrimaryLabel = computed(() => isWorkOrderTrace.value ? '工单' : '批次')
const tracePrimaryValue = computed(() => isWorkOrderTrace.value
  ? (payload.value.workOrderNo || '未知')
  : (payload.value.batchNo || '未知'))
const secondaryContextText = computed(() => {
  const source = isWorkOrderTrace.value ? payload.value.summary?.batchNos : payload.value.summary?.devices
  return contextList(source).join('、') || '未知'
})

const isRoute = (route) => {
  if(typeof route!=='string'||!/^#\/(?!\/)[^\s\\]*$/.test(route))return false
  try{const target=router.resolve(route.slice(1));return target.matched.length>0&&target.name!=='notFound'}catch{return false}
}
const legacyTaskRoute=id=>typeof id==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(id)?'#/inspection/workbench?taskId='+encodeURIComponent(id):''
const contextList = (value) => Array.isArray(value) ? value.filter(item=>typeof item==='string'&&item.trim()).slice(0,3) : []
const evidenceCount = (value) => Array.isArray(value) ? value.length.toLocaleString('zh-CN') : '未记录'
</script>

<style scoped>
.business-card { width:min(620px,100%); max-width:100%; min-width:0; box-sizing:border-box; padding:18px; border:1px solid var(--app-border); border-radius:12px; background:var(--app-surface); color:var(--app-text); box-shadow:none; overflow-wrap:anywhere; }
.business-head { display:flex; align-items:flex-start; gap:11px; }
.business-head > div { flex:1; min-width:0; }
.business-icon { display:grid; place-items:center; flex:0 0 34px; width:34px; height:34px; border-radius:9px; background:var(--app-primary-soft); color:var(--app-primary); }
.business-title { font-size:15px; line-height:1.7; font-weight:600; }
.business-desc { margin-top:5px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.business-snapshot-note { display:flex; align-items:flex-start; gap:7px; margin:14px 0 18px; padding:10px 12px; border-radius:7px; background:var(--app-info-soft); color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.business-snapshot-note .el-icon { flex-shrink:0; margin-top:3px; }
.source-strip { display:flex; flex-wrap:wrap; align-items:baseline; gap:6px; margin:12px 0; }
.source-label { color:var(--app-text-secondary); font-size:12px; }
.source-chip { padding:3px 7px; border-radius:5px; background:var(--app-bg); color:var(--app-text-secondary); font-size:11px; line-height:1.8; }
.source-chip small { font-size:inherit; }
.metric-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin:14px 0; }
.metric-card { min-width:0; padding:12px 0; border:0; border-top:1px solid var(--app-border); border-radius:0; background:transparent; }
.metric-value { display:block; color:var(--app-primary); font-size:23px; font-weight:600; line-height:1.5; font-variant-numeric:tabular-nums; }
.metric-label { display:block; margin-top:4px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
:is(.tone-amber,.tone-orange) .metric-value { color:var(--app-warning); }
:is(.tone-red,.tone-rose) .metric-value { color:var(--app-danger); }
.quality-actions,.example-list { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:12px; }
.batch-trace-mini,.defect-gallery-mini,.agent-health-mini { display:grid; gap:10px; margin-top:18px; }
.agent-health-status { display:flex; flex-wrap:wrap; align-items:center; gap:8px; padding:11px 12px; border-radius:7px; background:var(--app-bg); color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.agent-health-status strong { color:var(--app-text); font-size:12px; font-weight:550; }
.status-dot { flex:0 0 7px; width:7px; height:7px; border-radius:50%; background:var(--app-text-muted); }
.status-healthy .status-dot { background:var(--app-success); }
.status-degraded .status-dot { background:var(--app-warning); }
.status-unhealthy .status-dot { background:var(--app-danger); }
.agent-health-reason,.task-defect { margin:0; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.trace-context,.trace-quality,.task-meta,.task-status { display:flex; align-items:center; flex-wrap:wrap; gap:7px 14px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.trace-context > span,.task-meta > span,.task-status > span { min-width:0; overflow-wrap:anywhere; }
.task-list { display:grid; gap:0; margin-top:14px; }
.task-card { min-width:0; padding:15px 0; border:0; border-top:1px solid var(--app-border); border-radius:0; background:transparent; }
.task-main { display:flex; align-items:flex-start; flex-wrap:wrap; justify-content:space-between; gap:8px 12px; margin-bottom:10px; }
.task-id { min-width:0; color:var(--app-primary); font-size:12px; line-height:1.8; overflow-wrap:anywhere; text-decoration:underline; text-underline-offset:3px; }
span.task-id { color:var(--app-text-secondary); text-decoration:none; }
.task-status { margin-top:8px; }
.task-defect { margin-top:8px; }
.business-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 18px; margin-top:18px; }
.module-card { min-width:0; padding:16px 0; border:0; border-top:1px solid var(--app-border); border-radius:0; background:transparent; }
.module-top { display:flex; align-items:flex-start; flex-wrap:wrap; gap:7px 10px; }
.module-top h4 { margin:0; color:var(--app-text); font-size:14px; font-weight:600; line-height:1.75; }
.agent-tag { padding:2px 6px; border-radius:5px; background:var(--app-info-soft); color:var(--app-text-secondary); font-size:11px; line-height:1.8; }
.module-card p { margin:8px 0 12px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.route-btn { display:inline-flex; align-items:center; gap:6px; padding:6px 9px; border:1px solid var(--app-border); border-radius:6px; background:white; color:var(--app-primary); font-size:12px; line-height:1.8; text-decoration:none; transition:background-color 160ms ease,border-color 160ms ease,transform 160ms ease; }
.route-btn:hover { background:var(--app-primary-soft); border-color:var(--app-border-focus); }
.route-btn:active { transform:scale(.98); }
.route-note { display:block; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.example-chip { max-width:100%; padding:5px 8px; border:1px solid var(--app-border); border-radius:6px; background:var(--app-primary-light); color:var(--app-primary); font:inherit; font-size:12px; line-height:1.8; text-align:left; cursor:pointer; overflow-wrap:anywhere; transition:background-color 160ms ease,transform 160ms ease; }
.example-chip:hover { background:var(--app-primary-soft); }
.example-chip:active { transform:scale(.98); }
.business-note { margin-top:16px; padding-top:12px; border-top:1px solid var(--app-border); color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.business-card :is(button,a):focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; border-radius:3px; }
@media(max-width:560px) { .business-card { padding:14px; } .business-grid { grid-template-columns:minmax(0,1fr); } .metric-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media(prefers-reduced-motion:reduce) { .route-btn,.route-btn:active,.example-chip,.example-chip:active { transition:none; transform:none; } }
</style>
