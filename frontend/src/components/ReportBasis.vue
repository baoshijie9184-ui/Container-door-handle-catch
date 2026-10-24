<template>
  <section class="report-basis" aria-label="本版报告检测依据">
    <p class="report-basis-scope"><AppIcon name="DocumentCopy" :size="16" />以下为本版报告保存的任务依据，未重新读取任务当前状态。</p>
    <div class="report-basis-groups">
      <section v-for="group in groups" :key="group.title" class="report-basis-group">
        <h4><AppIcon :name="group.icon" :size="17" />{{ group.title }}</h4>
        <p class="report-basis-group-note">{{ group.note }}</p>
        <dl><div v-for="field in group.fields" :key="field.key"><dt>{{ field.label }}</dt><dd>
          <StatusBadge v-if="field.domain" :domain="field.domain" :code="sourceValue(field.key)" />
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
import { qualityReviewCountText } from '@/utils/qualityRecords'
const props = defineProps({ source:{type:Object,default:()=>({})} })
const groups = [
  { title:'检测与图片', icon:'Picture', note:'图片按张记录，检测缺陷计数与人工确认数量分别核对。', fields:[{key:'detectionStatus',label:'快照检测状态',domain:'detection'},{key:'totalImages',label:'图片总数',count:true,unit:'张'},{key:'processedImages',label:'已处理图片',count:true,unit:'张'},{key:'successfulImages',label:'检测成功图片',count:true,unit:'张'},{key:'failedImages',label:'检测失败图片',count:true,unit:'张'},{key:'defectCount',label:'检测缺陷记录数',count:true},{key:'finishedAt',label:'检测完成 · UTC+8',time:true}] },
  { title:'模型与运行登记', icon:'Tickets', note:'以本版已保存的编号与版本为准，不代表当前默认模型。', fields:[{key:'modelId',label:'检测模型编号'},{key:'modelVersion',label:'模型版本'},{key:'dispatchId',label:'检测运行编号'}] },
  { title:'人工复核', icon:'Search', note:'未复核、已跳过或状态未知时，不把初始计数当作人工无缺陷结论。', fields:[{key:'reviewStatus',label:'复核状态',domain:'review'},{key:'reviewConclusion',label:'记录中的复核结论',domain:'reviewConclusion'},{key:'confirmedDefectCount',label:'人工确认缺陷数',reviewCount:true},{key:'falsePositiveCount',label:'人工误报数',reviewCount:true},{key:'reviewer',label:'复核账号'},{key:'reviewedAt',label:'复核时间 · UTC+8',time:true}] },
  { title:'处置与复检', icon:'DocumentChecked', note:'此处为任务处理记录，报告是否已审批请核对报告状态。', fields:[{key:'flowStatus',label:'快照流转阶段',domain:'flow'},{key:'dispositionStatus',label:'处置登记状态',domain:'qualityDisposition'},{key:'dispositionAction',label:'已记录处置方式',domain:'dispositionAction'},{key:'recheckRequired',label:'复检要求'}] }
]
const sourceValue = key => props.source?.[key]
function display(field) {
  const value = sourceValue(field.key)
  if (field.reviewCount) return qualityReviewCountText(sourceValue('reviewStatus'),value)
  if (field.count) {const number=knownCount(value);return number==null?'数量未记录':number.toLocaleString('zh-CN')+(field.unit?' '+field.unit:'')}
  if (field.time) return value ? beijingDateTime(value) || '时间格式待核对' : '未记录'
  if (field.key==='recheckRequired') return value===true?'仍需复检':value===false?'本版记录未要求复检':'复检要求未记录'
  return value == null || (typeof value === 'string' && !value.trim()) ? '未记录' : value
}
</script>

<style scoped>
.report-basis-groups { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px 24px; }
.report-basis-scope { display:flex; align-items:flex-start; gap:7px; font-size:12px; line-height:1.85; color:var(--app-text-secondary); margin:0 0 16px; }
.report-basis-scope > .el-icon { flex:none; margin-top:3px; color:var(--app-primary); }
.report-basis-group { min-width:0; padding:14px 0; border-top:1px solid var(--app-border); }
.report-basis-group:first-child,.report-basis-group:last-child { grid-column:1/-1; }
.report-basis-group h4 { display:flex; align-items:center; gap:8px; margin:0 0 8px; color:var(--app-text); font-size:13px; font-weight:650; }
.report-basis-group h4 .el-icon { color:var(--app-primary); }
.report-basis-group-note { font-size:12px; line-height:1.85; color:var(--app-text-secondary); margin:0 0 16px; }
.report-basis-group dl { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; margin:0; }
.report-basis-group:first-child dl { grid-template-columns:repeat(3,minmax(0,1fr)); }
.report-basis-group:last-child dl { grid-template-columns:repeat(4,minmax(0,1fr)); }
.report-basis-group dl > div { min-width:0; }
.report-basis-group dt { font-size:12px; line-height:1.85; color:var(--app-text-secondary); }
.report-basis-group dd { margin:5px 0 0; color:var(--app-text); font-size:13px; line-height:1.8; overflow-wrap:anywhere; font-variant-numeric:tabular-nums; }
.report-basis-note { margin:12px 0 0; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
@media(max-width:620px) { .report-basis-groups { grid-template-columns:minmax(0,1fr); gap:8px; } .report-basis-group:first-child dl,.report-basis-group:last-child dl { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media(max-width:420px) { .report-basis-group dl,.report-basis-group:first-child dl,.report-basis-group:last-child dl { grid-template-columns:minmax(0,1fr); } }
</style>
