<template>
  <section class="no-detection-summary" aria-label="整图未检出统计">
    <div class="no-detection-heading"><span><AppIcon name="Picture" :size="16" />整图未检出率</span><strong>{{ summary.value }}</strong></div>
    <p>{{ summary.description }}</p>
    <details><summary>统计口径</summary><p>一张图片中没有任何达到本次检测阈值的目标，计为整图未检出；检出 Normal 类也算检出。分母为成功检测的图片数，失败图片不计入。此项描述模型输出，不能据此判定真实目标漏检；AP 仍单独展示。</p></details>
  </section>
</template>
<script setup>
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import { noDetectionSummary } from '@/utils/noDetectionPresentation'
const props = defineProps({ result: { type: Object, required: true } })
const summary = computed(() => noDetectionSummary(props.result))
</script>
<style scoped>
.no-detection-summary { margin:14px 0; padding:12px 14px; border-left:3px solid var(--app-primary,#2563eb); background:var(--app-primary-soft,#eff6ff); color:var(--app-text,#0f172a); border-radius:0 8px 8px 0; }
.no-detection-heading { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:8px 14px; }
.no-detection-heading > span { display:inline-flex; align-items:center; gap:7px; font-size:13px; line-height:1.8; }
.no-detection-heading .el-icon { color:var(--app-primary,#2563eb); }
.no-detection-heading strong { font-size:21px; line-height:1.4; font-weight:600; font-variant-numeric:tabular-nums; }
.no-detection-summary p { margin:7px 0 0; font-size:12px; line-height:1.85; color:var(--app-text-secondary,#475569); overflow-wrap:anywhere; }
.no-detection-summary details { margin-top:7px; font-size:12px; line-height:1.85; color:var(--app-text-secondary,#475569); }
.no-detection-summary summary { width:fit-content; cursor:pointer; }
.no-detection-summary summary:focus-visible { outline:2px solid var(--app-primary,#2563eb); outline-offset:3px; border-radius:3px; }
</style>
