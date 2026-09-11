<template>
  <div class="business-card">
    <div class="business-head">
      <span class="business-icon">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 21h18"/>
          <path d="M5 21V7l8-4v18"/>
          <path d="M19 21V11l-6-4"/>
          <path d="M9 9h.01M9 13h.01M9 17h.01"/>
        </svg>
      </span>
      <div>
        <div class="business-title">{{ payload.title || '业务卡片' }}</div>
        <div class="business-desc">{{ payload.description || '已为你整理相关业务入口。' }}</div>
      </div>
    </div>

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
          <span class="metric-value">{{ metric.value }}</span>
          <span class="metric-label">{{ metric.label }}</span>
        </div>
      </div>

      <div class="quality-actions">
        <a v-if="isRoute(payload.route)" class="route-btn" :href="payload.route">
          {{ traceRouteText }}
        </a>
        <button
          v-for="action in payload.actions || []"
          :key="action"
          class="example-chip"
          @click="$emit('send', action)"
        >
          {{ action }}
        </button>
      </div>

      <div v-if="isAgentHealth" class="agent-health-mini">
        <div class="agent-health-status" :class="`status-${String(payload.status || 'UNKNOWN').toLowerCase()}`">
          <span class="status-dot"></span>
          <strong>{{ payload.status || 'UNKNOWN' }}</strong>
          <span>{{ payload.health?.lastUpdatedAt || '暂无更新时间' }}</span>
        </div>
        <div class="trace-context">
          <span>最近退出 {{ payload.health?.lastExitReason || 'UNKNOWN' }}</span>
          <span>兜底率 {{ payload.health?.fallbackRate || '0.0%' }}</span>
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
              <a class="task-id" :href="`#/inspection/workbench?taskId=${task.taskId}`">{{ task.taskId }}</a>
              <span class="severity-pill">{{ task.maxDefectSeverity || '未知' }}</span>
            </div>
            <div class="task-meta">
              <span>缺陷 {{ task.primaryDefectType || '未知' }}</span>
              <span>设备 {{ task.deviceName || '未知' }}</span>
              <span>批次 {{ task.batchNo || '未知' }}</span>
            </div>
            <div class="task-status">
              <span>数量 {{ task.defectCount || 0 }}</span>
              <span>复核 {{ task.reviewStatus || '未知' }}</span>
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
          <span>待复核 {{ payload.quality?.pendingReview || 0 }}</span>
          <span>已处置 {{ payload.quality?.disposed || 0 }}</span>
          <span>需返工 {{ payload.quality?.reworkRequired || 0 }}</span>
          <span>需复检 {{ payload.quality?.recheckRequired || 0 }}</span>
        </div>
        <div v-if="batchRecords.length" class="task-list">
          <article v-for="task in batchRecords" :key="task.taskId" class="task-card">
            <div class="task-main">
              <a class="task-id" :href="`#/inspection/workbench?taskId=${task.taskId}`">{{ task.taskId }}</a>
              <span class="severity-pill">{{ task.maxDefectSeverity || '未知' }}</span>
            </div>
            <div class="task-meta">
              <span>工单 {{ task.workOrderNo || '未知' }}</span>
              <span>设备 {{ task.deviceName || '未知' }}</span>
              <span>缺陷 {{ task.defectCount || 0 }}</span>
            </div>
            <div class="task-status">
              <span>{{ task.status || '未知' }}</span>
              <span>流转 {{ task.flowStatus || '未知' }}</span>
              <span>复核 {{ task.reviewStatus || '未知' }}</span>
            </div>
          </article>
        </div>
      </div>

      <div class="task-list" v-else-if="tasks.length">
        <article v-for="task in tasks" :key="task.taskId" class="task-card">
          <div class="task-main">
            <a class="task-id" :href="task.route">{{ task.taskId }}</a>
            <span class="severity-pill">{{ task.severity }}</span>
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
            <span>缺陷 {{ task.defectCount }}</span>
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
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4">
            <path d="M7 17L17 7"/>
            <path d="M8 7h9v9"/>
          </svg>
        </a>
        <span v-else class="route-note">{{ card.route }}</span>
        <div class="example-list">
          <button
            v-for="example in card.examples || []"
            :key="example"
            class="example-chip"
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

const props = defineProps({
  message: { type: Object, required: true }
})

defineEmits(['send'])

const payload = computed(() => {
  try {
    return JSON.parse(props.message.content || '{}')
  } catch {
    return {
      title: '业务卡片解析失败',
      description: props.message.content || '',
      cards: []
    }
  }
})

const cards = computed(() => Array.isArray(payload.value.cards) ? payload.value.cards : [])
const isQualityQueue = computed(() => payload.value.type === 'quality-queue')
const isBatchTrace = computed(() => payload.value.type === 'batch-trace')
const isWorkOrderTrace = computed(() => payload.value.type === 'work-order-trace')
const isDefectGallery = computed(() => payload.value.type === 'defect-gallery')
const isAgentHealth = computed(() => payload.value.type === 'agent-health')
const metrics = computed(() => Array.isArray(payload.value.metrics) ? payload.value.metrics : [])
const tasks = computed(() => Array.isArray(payload.value.tasks) ? payload.value.tasks : [])
const sources = computed(() => Array.isArray(payload.value.sources) ? payload.value.sources : [])
const batchRecords = computed(() => Array.isArray(payload.value.records) ? payload.value.records.slice(0, 5) : [])
const defectRecords = computed(() => Array.isArray(payload.value.records) ? payload.value.records.slice(0, 5) : [])
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

const isRoute = (route) => typeof route === 'string' && route.startsWith('#/')
const contextList = (value) => Array.isArray(value) ? value.filter(Boolean).slice(0, 3) : []
const evidenceCount = (value) => Array.isArray(value) ? value.length : 0
</script>

<style scoped>
.business-card {
  width: min(620px, 100%);
  padding: 16px;
  border-radius: 20px;
  background:
    linear-gradient(135deg, rgba(239, 246, 255, 0.95), rgba(255, 255, 255, 0.98)),
    radial-gradient(circle at top left, rgba(59, 130, 246, 0.16), transparent 42%);
  border: 1px solid rgba(147, 197, 253, 0.45);
  box-shadow: 0 16px 40px rgba(30, 64, 175, 0.08);
}

.business-head {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.business-icon {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  color: #1d4ed8;
  background: #dbeafe;
  flex-shrink: 0;
}

.business-title {
  font-size: 15px;
  font-weight: 800;
  color: #0f172a;
}

.business-desc {
  margin-top: 3px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
}

.business-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
  margin-top: 14px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.source-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px;
  margin-top: 12px;
}

.source-label {
  color: #64748b;
  font-size: 11px;
  font-weight: 850;
  letter-spacing: 0.04em;
}

.source-chip {
  padding: 5px 8px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.04);
  border: 1px solid rgba(148, 163, 184, 0.26);
  color: #334155;
  font-size: 11px;
  font-weight: 800;
}

.source-chip small {
  color: #64748b;
  font-weight: 650;
}

.metric-card {
  padding: 10px;
  border-radius: 14px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
}

.metric-value {
  display: block;
  font-size: 20px;
  line-height: 1;
  font-weight: 900;
  color: #1d4ed8;
}

.metric-label {
  display: block;
  margin-top: 5px;
  font-size: 11px;
  color: #475569;
}

.tone-amber { background: #fffbeb; border-color: #fde68a; }
.tone-amber .metric-value { color: #b45309; }
.tone-orange { background: #fff7ed; border-color: #fed7aa; }
.tone-orange .metric-value { color: #c2410c; }
.tone-indigo { background: #eef2ff; border-color: #c7d2fe; }
.tone-indigo .metric-value { color: #4338ca; }
.tone-red { background: #fef2f2; border-color: #fecaca; }
.tone-red .metric-value { color: #dc2626; }
.tone-rose { background: #fff1f2; border-color: #fecdd3; }
.tone-rose .metric-value { color: #e11d48; }

.quality-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.batch-trace-mini,
.defect-gallery-mini,
.agent-health-mini {
  display: grid;
  gap: 9px;
  margin-top: 12px;
}

.agent-health-status {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border-radius: 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #334155;
  font-size: 12px;
}

.agent-health-status strong {
  color: #0f172a;
  font-size: 13px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #94a3b8;
  box-shadow: 0 0 0 4px rgba(148, 163, 184, 0.14);
}

.status-healthy .status-dot { background: #16a34a; box-shadow: 0 0 0 4px rgba(22, 163, 74, 0.14); }
.status-warn .status-dot { background: #d97706; box-shadow: 0 0 0 4px rgba(217, 119, 6, 0.14); }
.status-critical .status-dot { background: #dc2626; box-shadow: 0 0 0 4px rgba(220, 38, 38, 0.14); }

.agent-health-reason {
  margin: 0;
  padding: 9px 10px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px dashed rgba(148, 163, 184, 0.55);
  color: #475569;
  font-size: 12px;
  line-height: 1.55;
}

.trace-context,
.trace-quality {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.trace-context span,
.trace-quality span {
  padding: 5px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(191, 219, 254, 0.72);
  color: #334155;
  font-size: 11px;
  font-weight: 750;
}

.trace-quality span {
  background: #f8fafc;
  border-color: #e2e8f0;
}

.task-list {
  display: grid;
  gap: 9px;
  margin-top: 13px;
}

.task-card {
  padding: 12px;
  border-radius: 15px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(226, 232, 240, 0.95);
}

.task-main,
.task-meta,
.task-status {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  align-items: center;
}

.task-id {
  color: #1d4ed8;
  font-size: 13px;
  font-weight: 850;
  text-decoration: none;
}

.severity-pill {
  padding: 2px 7px;
  border-radius: 999px;
  background: #fef2f2;
  color: #dc2626;
  font-size: 10px;
  font-weight: 800;
}

.task-meta {
  margin-top: 7px;
  color: #64748b;
  font-size: 11px;
}

.task-status {
  margin-top: 8px;
}

.task-status span {
  padding: 3px 7px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  font-size: 10.5px;
  font-weight: 700;
}

.task-defect {
  margin: 8px 0 0;
  color: #334155;
  font-size: 12px;
}

.module-card {
  padding: 13px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(226, 232, 240, 0.9);
}

.module-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.module-top h4 {
  margin: 0;
  font-size: 14px;
  color: #0f172a;
}

.agent-tag {
  padding: 2px 7px;
  border-radius: 999px;
  background: #eef2ff;
  color: #3730a3;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.04em;
}

.module-card p {
  margin: 8px 0 10px;
  color: #475569;
  font-size: 12.5px;
  line-height: 1.55;
}

.route-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 10px;
  border-radius: 999px;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18);
}

.route-note {
  display: inline-block;
  color: #64748b;
  font-size: 12px;
}

.example-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.example-chip {
  border: 1px solid #dbeafe;
  background: #f8fbff;
  color: #1d4ed8;
  border-radius: 999px;
  padding: 5px 8px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.18s;
}

.example-chip:hover {
  background: #dbeafe;
  transform: translateY(-1px);
}

.business-note {
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.04);
  color: #475569;
  font-size: 12px;
  line-height: 1.55;
}

@media (max-width: 560px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
