<template>
  <div class="task-stage">
    <StatusBadge v-if="verification" domain="boardVerification" :code="row.listPhase" :label="stageLabel" />
    <template v-else>
      <StatusBadge domain="detection" :code="modelCode" :label="stageLabel" />
      <small v-if="row.totalImages != null">
        已处理 {{ row.processedImages ?? '—' }} / {{ row.totalImages }} 张<span v-if="row.failedImages"> · {{ row.failedImages }} 张失败</span>
      </small>
      <progress v-if="row.totalImages && ['QUEUED','DETECTING','RUNNING'].includes(row.modelStatus)"
        :value="row.processedImages" :max="row.totalImages" aria-label="模型图片处理进度" />
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { humanStep, modelStep } from '@/utils/taskBoardStages'

const props = defineProps({
  row: { type: Object, required: true },
  verification: Boolean
})
const modelCode = computed(() => Number(props.row.totalImages) > 0 &&
  Number(props.row.failedImages) === Number(props.row.totalImages) ? 'FAILED' : props.row.modelStatus)
const stageLabel = computed(() => {
  const label = props.verification ? humanStep(props.row) : modelStep(props.row)
  const name = props.verification ? props.row.verifierName : props.row.detectorName
  const number = props.verification ? props.row.verifierEmployeeNumber : props.row.detectorEmployeeNumber
  const employee = [name?.trim(), number?.trim()].filter(Boolean).join(' · ')
  return employee ? `${label}（${employee}）` : label
})
</script>

<style scoped>
.task-stage { display:grid; justify-items:start; align-content:start; min-width:0; gap:4px; }
.task-stage :deep(.business-status) { white-space:normal; }
.task-stage :deep(.business-status span) { overflow-wrap:anywhere; }
.task-stage small { color:var(--app-text-secondary); font-size:12px; line-height:1.5; }
.task-stage progress { width:min(100%, 126px); height:6px; margin-top:2px; accent-color:var(--app-primary); }
</style>
