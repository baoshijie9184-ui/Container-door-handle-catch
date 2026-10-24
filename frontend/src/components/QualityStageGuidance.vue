<template>
  <div class="quality-guidance" :data-attention="needsAttention" :data-tone="flow === 'FAILED' ? 'danger' : needsAttention ? 'warning' : 'info'">
    <span class="quality-guidance-icon"><AppIcon :name="icon" :size="15" /></span>
    <div><strong>{{ heading }}</strong><p>{{ explanation }}</p></div>
  </div>
</template>
<script setup>
import { computed } from 'vue'
const props = defineProps({ task: { type: Object, required: true } })
const stages = {
  UPLOADING: ['继续上传', '核对采集信息，等待原图上传完成。', 'Upload'],
  PENDING_DETECTION: ['等待检测', '任务已提交，等待检测服务处理。', 'Clock'],
  DETECTING: ['正在检测', '完成后核对原图和标注，再进行人工复核。', 'Picture'],
  PENDING_REVIEW: ['核对图片与结论', '检测完成不等于放行，请由有权限的人员提交人工复核。', 'Search'],
  REVIEWING: ['完成人工复核', '核对缺陷位置和误报，确认后再选择处置方式。', 'Search'],
  CONFIRMED: ['选择处置方式', '复核结论已保存，按业务条件选择放行、返工、复检、暂挂或报废。', 'CircleCheck'],
  REWORK_REQUIRED: ['回填返工结果', '先完成返工并记录结果；原处置要求复检时不能跳过。', 'Edit'],
  RECHECK_REQUIRED: ['完成实际复检', '当前仍需重新检测，不能直接跳到放行或归档。', 'Refresh'],
  HOLD: ['核对后续处置', '任务仍处于暂挂阶段，可在业务条件满足后选择后续处置。', 'Clock'],
  RELEASED: ['任务已放行', '可以查看依据和处理记录，报告仍需独立审批。', 'CircleCheck'],
  SCRAPPED: ['任务已报废', '保留原图和处置依据供追溯。', 'Document'],
  ARCHIVED: ['任务已归档', '保留已有记录供查询，不再修改当前质量结论。', 'Document'],
  FAILED: ['核对检测失败原因', '先查看任务错误；结果未知时先核对回执，再决定后续操作。', 'Warning']
}
const flow = computed(() => props.task.flowStatus || props.task.result?.flowStatus || '')
const guidance = computed(() => stages[flow.value] || ['刷新任务状态', '当前阶段尚不明确，请刷新并核对可用操作。', 'Search'])
const heading = computed(() => guidance.value[0])
const explanation = computed(() => guidance.value[1])
const icon = computed(() => guidance.value[2])
const needsAttention = computed(() => ['REWORK_REQUIRED', 'RECHECK_REQUIRED', 'HOLD', 'FAILED'].includes(flow.value))
</script>
<style scoped>
.quality-guidance { display: flex; align-items: flex-start; gap: 9px; padding: 11px 12px; border-radius: 8px; background: #f8fafc; color: var(--app-text-secondary); font-size: 12px; line-height: 1.7; }
.quality-guidance-icon { color: var(--app-primary); padding-top: 3px; flex: 0 0 auto; }
.quality-guidance strong { font-weight: 600; color: var(--app-text); }
.quality-guidance p { margin: 2px 0 0; overflow-wrap: anywhere; font-size: 12px; line-height:1.8; }
.quality-guidance[data-attention=true] { background: var(--app-warning-soft); }
.quality-guidance[data-attention=true] .quality-guidance-icon { color: var(--app-warning); }
.quality-guidance[data-tone=danger] { background:var(--app-danger-soft); }
.quality-guidance[data-tone=danger] .quality-guidance-icon { color:var(--app-danger); }
</style>
