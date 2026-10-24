<template>
  <section class="report-basis" aria-label="本版报告检测依据">
    <div class="report-basis-groups">
      <section v-for="group in groups" :key="group.title" class="report-basis-group">
        <h4><AppIcon :name="group.icon" :size="17" />{{ group.title }}</h4>
        <dl><div v-for="field in group.fields" :key="field.key"><dt>{{ field.label }}</dt><dd>
          <StatusBadge v-if="field.key==='reviewStatus'" domain="review" :code="sourceValue(field.key)" />
          <StatusBadge v-else-if="field.key==='reviewConclusion'" domain="reviewConclusion" :code="sourceValue(field.key)" />
          <template v-else>{{ display(field) }}</template>
        </dd></div></dl>
      </section>
    </div>
    <p class="report-basis-note">复核结论、任务处置与报告审批分别记录；以上为本版报告依据，不代表任务已放行。</p>
  </section>
</template>

<script setup>
import AppIcon from './AppIcon.vue'
import StatusBadge from './StatusBadge.vue'
import { knownCount } from '@/utils/countPresentation'
import { beijingDateTime } from '@/utils/beijingTime'
const props = defineProps({ source:{type:Object,default:()=>({})} })
const groups = [
  { title:'检测与图片', icon:'Picture', fields:[{key:'totalImages',label:'图片总数',count:true},{key:'successfulImages',label:'成功图片',count:true},{key:'failedImages',label:'失败图片',count:true},{key:'defectCount',label:'检测缺陷数',count:true},{key:'finishedAt',label:'检测完成 · UTC+8'}] },
  { title:'模型版本', icon:'Tickets', fields:[{key:'modelId',label:'检测模型编号'},{key:'modelVersion',label:'模型版本'}] },
  { title:'人工复核', icon:'DocumentChecked', fields:[{key:'reviewStatus',label:'复核状态'},{key:'reviewConclusion',label:'复核结论'},{key:'confirmedDefectCount',label:'人工确认缺陷数',count:true},{key:'falsePositiveCount',label:'误报数',count:true},{key:'reviewer',label:'复核账号'}] }
]
const sourceValue = key => props.source?.[key]
function display(field) {
  const value = sourceValue(field.key)
  if (field.count) return knownCount(value)?.toLocaleString('zh-CN') ?? '—'
  if (field.key === 'finishedAt') return value ? beijingDateTime(value) || '时间未记录' : '未记录'
  return value == null || (typeof value === 'string' && !value.trim()) ? '未记录' : value
}
</script>

<style scoped>
.report-basis-groups { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px 24px; }
.report-basis-group { min-width:0; padding:14px 0; border-top:1px solid var(--app-border); }
.report-basis-group:first-child { grid-column:1/-1; }
.report-basis-group h4 { display:flex; align-items:center; gap:8px; margin:0 0 16px; color:var(--app-text); font-size:13px; font-weight:650; }
.report-basis-group h4 .el-icon { color:var(--app-primary); }
.report-basis-group dl { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; margin:0; }
.report-basis-group:first-child dl { grid-template-columns:repeat(3,minmax(0,1fr)); }
.report-basis-group dl > div { min-width:0; }
.report-basis-group dt { font-size:11px; line-height:1.8; color:var(--app-text-muted); }
.report-basis-group dd { margin:5px 0 0; color:var(--app-text); font-size:13px; line-height:1.8; overflow-wrap:anywhere; font-variant-numeric:tabular-nums; }
.report-basis-note { margin:12px 0 0; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
@media(max-width:620px) { .report-basis-groups { grid-template-columns:minmax(0,1fr); gap:8px; } .report-basis-group:first-child dl { grid-template-columns:repeat(2,minmax(0,1fr)); } }
</style>
