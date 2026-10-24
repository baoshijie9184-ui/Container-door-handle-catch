<template>
 <section class="task-result-snapshot" aria-label="本次已读取的检测结果">
  <p v-if="!matches" class="task-result-mismatch" role="alert">结果编号未能与当前任务一致核对，请打开追溯详情重新读取。</p>
  <template v-else>
   <header><h4><AppIcon name="DocumentChecked" :size="17" />已读检测结果</h4><StatusBadge domain="detection" :code="result.status" /></header>
   <p class="task-result-note">以下为本次已返回的结果快照。检测、人工复核、任务放行与报告审批分别记录，最新资料请重新读取追溯。</p>
   <dl class="task-result-counts"><div><dt>图片总数</dt><dd>{{ count(result.totalImages) }}</dd></div><div><dt>检测成功图片</dt><dd>{{ count(result.successfulImages) }}</dd></div><div><dt>检测失败图片</dt><dd>{{ count(result.failedImages) }}</dd></div></dl>
   <dl class="task-result-responsibility"><div><dt>责任人</dt><dd>{{ result.assignee || '未记录' }}</dd></div><div><dt>质检截止 · UTC+8</dt><dd>{{ time(result.dueAt) }}</dd></div><div><dt>人工复核</dt><dd><StatusBadge domain="review" :code="result.reviewStatus" /></dd></div><div><dt>复核结论</dt><dd><StatusBadge domain="reviewConclusion" :code="result.reviewConclusion" /></dd></div></dl>
   <p v-if="result.errorMessage" class="task-result-mismatch">结果记录的异常：{{ result.errorMessage }}</p>
   <EvidenceComparison :task-id="taskId" :originals="originals" :annotations="previews" />
   <details class="task-result-disclosure"><summary>任务资料、复核与处置记录</summary><p class="task-result-note">仅展示当前结果已有字段，未返回的模型设置和资料保持未记录。</p><TaskTraceDetails :detail="detail" /></details>
   <details v-if="statisticsRows.length" class="task-result-disclosure"><summary>已返回的分类与统计</summary><p class="task-result-note">分类计数以原统计字段为准，不推算人工确认缺陷。缺失值为未知，不补零。</p><dl class="task-result-statistics"><div v-for="row in statisticsRows" :key="row.key"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div></dl><p v-if="hasHistoricalRate" class="task-result-note">历史未检出统计的比例单位尚未统一，此处保留原值供核对，不作为模型漏检率或准确率。</p></details>
   <div class="task-result-actions"><el-button size="small" type="primary" plain @click="$emit('trace',taskId)"><AppIcon name="Search" :size="14" />重新读取任务追溯</el-button><a v-if="resultHref" :href="resultHref" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">查看结果 JSON<AppIcon name="TopRight" :size="13" /></a></div>
  </template>
 </section>
</template>
<script setup>
import {computed} from 'vue'
import EvidenceComparison from './EvidenceComparison.vue'
import TaskTraceDetails from './TaskTraceDetails.vue'
import {knownCount} from '@/utils/countPresentation'
import {beijingDateTime} from '@/utils/beijingTime'
import {evidencePreviewUrl} from '@/utils/evidencePresentation'
import {CATEGORY_LABELS} from '@/stores/taskStore'
const props=defineProps({taskId:{type:String,required:true},result:{type:Object,required:true}})
defineEmits(['trace'])
const matches=computed(()=>typeof props.result.taskId==='string' && props.result.taskId===props.taskId)
const count=value=>knownCount(value)?.toLocaleString('zh-CN') ?? '未知'
const time=value=>value ? beijingDateTime(value)||'时间格式未知' : '未记录'
const previews=computed(()=>(Array.isArray(props.result.previewImages)?props.result.previewImages:[]).filter(image=>image && typeof image==='object' && !Array.isArray(image)))
const originals=computed(()=>previews.value.filter(image=>evidencePreviewUrl({previewUrl:image.originalUrl})).map(image=>({imageName:image.imageName,previewUrl:image.originalUrl})))
const resultHref=computed(()=>evidencePreviewUrl({previewUrl:props.result.resultJsonUrl}))
const detail=computed(()=>({...props.result,captureDate:props.result.captureInfo?.captureDate,region:props.result.captureInfo?.region,collector:props.result.captureInfo?.collector,deviceName:props.result.captureInfo?.deviceName,imageFolderName:props.result.captureInfo?.imageFolderName}))
const hasHistoricalRate=computed(()=>Object.hasOwn(props.result.statistics||{},'missDetectionRate'))
const statisticsRows=computed(()=>{
 const stats=props.result.statistics
 if(!stats || typeof stats!=='object' || Array.isArray(stats))return []
 const classes=stats.classCounts,rows=[]
 if(classes && typeof classes==='object' && !Array.isArray(classes))for(const [key,value] of Object.entries(classes))rows.push({key:'class-'+key,label:Object.hasOwn(CATEGORY_LABELS,key)?CATEGORY_LABELS[key]:key,value:count(value)})
 for(const [key,label] of [['noDetectionImages','未检出图片数'],['totalImages','统计图片总数'],['successfulImages','统计成功图片数'],['failedImages','统计失败图片数']])if(Object.hasOwn(stats,key))rows.push({key,label,value:count(stats[key])})
 if(Object.hasOwn(stats,'missDetectionRate'))rows.push({key:'missDetectionRate',label:'历史未检出统计（原值）',value:typeof stats.missDetectionRate==='number' && Number.isFinite(stats.missDetectionRate)?stats.missDetectionRate.toLocaleString('zh-CN',{maximumFractionDigits:8}):'未知'})
 return rows
})
</script>
<style scoped>
.task-result-snapshot { min-width:0; padding-top:16px; border-top:1px solid var(--app-border); }
.task-result-snapshot > header { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:9px; }
.task-result-snapshot h4 { display:flex; align-items:center; gap:7px; margin:0; color:var(--app-text); font-size:14px; line-height:1.8; font-weight:600; }
.task-result-snapshot h4 .el-icon { color:var(--app-primary); }
.task-result-note { margin:10px 0 14px; color:var(--app-text-secondary); font-size:12px; line-height:1.9; overflow-wrap:anywhere; }
.task-result-counts { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin:14px 0; padding:14px 0; border-block:1px solid var(--app-border); }
.task-result-counts dt,.task-result-responsibility dt,.task-result-statistics dt { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.task-result-counts dd { margin:7px 0 0; font-size:22px; font-weight:600; line-height:1.5; color:var(--app-text); }
.task-result-responsibility { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin:0 0 18px; }
.task-result-responsibility > div,.task-result-counts > div,.task-result-statistics > div { min-width:0; }
.task-result-responsibility dd,.task-result-statistics dd { margin:5px 0 0; color:var(--app-text); font-size:13px; line-height:1.8; overflow-wrap:anywhere; }
.task-result-mismatch { margin:12px 0; padding:12px; color:var(--app-warning); background:var(--app-warning-soft); font-size:12px; line-height:1.9; overflow-wrap:anywhere; border-radius:7px; }
.task-result-disclosure { margin:14px 0; padding:12px 0; border-bottom:1px solid var(--app-border); }
.task-result-disclosure > summary { width:fit-content; cursor:pointer; color:var(--app-primary); font-size:12px; line-height:1.8; }
.task-result-statistics { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; margin:12px 0; }
.task-result-actions { display:flex; flex-wrap:wrap; align-items:center; gap:10px 16px; margin-top:14px; }
.task-result-actions a { display:inline-flex; align-items:center; gap:5px; color:var(--app-primary); font-size:12px; line-height:1.8; }
.task-result-snapshot :is(a,button,summary):focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
@media(max-width:480px) { .task-result-responsibility,.task-result-statistics { grid-template-columns:minmax(0,1fr); }.task-result-counts dd { font-size:19px; } }
</style>
