<template>
  <section class="trace-metric-summary" aria-label="关联任务统计">
    <p class="trace-scope-note"><AppIcon name="Lock" :size="15" />只统计当前账号可访问的关联任务；追溯摘要不代表质检报告已审批。</p>
    <dl class="trace-metric-grid">
      <div v-for="metric in metrics" :key="metric.label" :data-tone="metric.tone || 'primary'">
        <dt><AppIcon :name="metric.icon" :size="16" />{{ metric.label }}</dt>
        <dd>{{ metric.value }}<small v-if="metric.value!=='—'&&metric.unit">{{ metric.unit }}</small></dd>
      </div>
    </dl>
    <p class="trace-metric-note">缺陷按目标计数，一张图片可含多个缺陷；每百张图的缺陷数不等同缺陷图片占比。任务闭环率按关联任务数计算，分母为空或零时显示 —。</p>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import { knownCount } from '@/utils/countPresentation'
const props = defineProps({ report: { type:Object, required:true } })
const count = value => knownCount(value)?.toLocaleString('zh-CN') ?? '—'
function rate(value, denominator, bounded = false) {
  if (!knownCount(denominator)) return '—'
  if (typeof value !== 'number' && typeof value !== 'string') return '—'
  if (typeof value === 'string' && !value.trim()) return '—'
  const number = Number(value)
  if (!Number.isFinite(number) || !Number.isFinite(number * 100) || number < 0 || (bounded && number > 1)) return '—'
  return (number * 100).toLocaleString('zh-CN', { maximumFractionDigits:1 })
}
const metrics = computed(() => {
  const inspection = props.report.inspection || {}, quality = props.report.quality || {}, summary = props.report.summary || {}
  return [
    { label:'关联任务', value:count(summary.taskCount), unit:'个', icon:'Tickets' },
    { label:'任务图片', value:count(inspection.totalImages), unit:'张', icon:'Picture' },
    { label:'检测缺陷', value:count(inspection.defectCount), unit:'个', icon:'Search', tone:knownCount(inspection.defectCount)>0?'warning':'primary' },
    { label:'人工确认缺陷', value:count(inspection.confirmedDefectCount), unit:'个', icon:'DocumentChecked' },
    { label:'每百张图的缺陷数', value:rate(inspection.defectRate,inspection.totalImages), unit:'个', icon:'DataAnalysis' },
    { label:'任务闭环率', value:rate(quality.closureRate,summary.taskCount,true), unit:'%', icon:'CircleCheck' }
  ]
})
</script>

<style scoped>
.trace-metric-summary { margin: 18px 0 22px; }
.trace-scope-note { display:flex; align-items:flex-start; gap:7px; margin:0 0 12px; font-size:12px; line-height:1.8; color:var(--app-text-secondary); }
.trace-scope-note .el-icon { flex:0 0 auto; margin-top:3px; color:var(--app-primary); }
.trace-metric-grid { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:12px; margin:0; }
.trace-metric-grid > div { min-width:0; padding:14px; border:1px solid var(--app-border); border-radius:10px; background:white; }
.trace-metric-grid dt { display:flex; align-items:flex-start; gap:6px; font-size:12px; line-height:1.75; color:var(--app-text-secondary); }
.trace-metric-grid dt .el-icon { flex:0 0 auto; margin-top:3px; color:var(--app-primary); }
.trace-metric-grid > [data-tone=warning] dt .el-icon { color:var(--app-warning); }
.trace-metric-grid dd { margin:12px 0 0; font-size:24px; font-weight:650; line-height:1.4; color:var(--app-text); font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
.trace-metric-grid dd small { margin-left:5px; font-size:12px; font-weight:400; color:var(--app-text-secondary); }
.trace-metric-note { margin:10px 0 0; max-width:90ch; color:var(--app-text-muted); font-size:12px; line-height:1.8; }
@media(max-width:1200px) { .trace-metric-grid { grid-template-columns:repeat(3,minmax(0,1fr)); } }
@media(max-width:640px) { .trace-metric-grid { grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; } .trace-metric-grid > div { padding:12px; } .trace-metric-grid dd { font-size:22px; } }
</style>
