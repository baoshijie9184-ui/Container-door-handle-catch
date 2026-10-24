<template>
  <article class="detection-history-card" :aria-label="`检测任务 ${task.taskId}`">
    <header class="history-card-heading"><span class="history-card-symbol"><AppIcon name="Picture" :size="20" /></span><div><h3>{{ task.folderName || task.captureInfo?.imageFolderName || '检测任务' }}</h3><button type="button" class="history-task-link" @click="$emit('trace',task.taskId)">{{ task.taskId }}</button></div><StatusBadge domain="detection" :code="statusCode" /></header>
    <div class="history-quality-states"><span>流转 <StatusBadge domain="flow" :code="task.flowStatus" /></span><span>复核 <StatusBadge domain="review" :code="task.reviewStatus" /></span><StatusBadge v-if="task.reviewConclusion" domain="reviewConclusion" :code="task.reviewConclusion" /></div>
    <dl class="history-image-counts"><div><dt>图片总数</dt><dd>{{ count(task.totalImages ?? task.imageCount) }}<small>张</small></dd></div><div><dt>检测成功图片</dt><dd>{{ count(task.successfulImages) }}<small>张</small></dd></div><div :data-attention="knownCount(task.failedImages)>0"><dt>检测失败图片</dt><dd>{{ count(task.failedImages) }}<small>张</small></dd></div></dl>
    <p class="history-card-time"><AppIcon name="Clock" :size="14" />{{ task.finishedAt ? '检测结束' : '任务创建' }} {{ time(task.finishedAt || task.createdAt) }} · UTC+8</p>
    <dl class="history-capture-fields"><div><dt>工单 / 批次</dt><dd><router-link v-if="task.workOrderNo" :to="{path:'/quality/work-order-trace',query:{workOrderNo:task.workOrderNo}}">{{ task.workOrderNo }}</router-link><span v-else>工单未记录</span><router-link v-if="task.batchNo" :to="{path:'/quality/batch-trace',query:{batchNo:task.batchNo}}">{{ task.batchNo }}</router-link><span v-else>批次未记录</span></dd></div><div><dt>采集人员 / 区域</dt><dd>{{ task.captureInfo?.collector || '人员未记录' }}<span>{{ task.captureInfo?.region || '区域未记录' }}</span></dd></div><div><dt>采集设备</dt><dd>{{ task.captureInfo?.deviceName || '未记录' }}</dd></div><div><dt>采集日期</dt><dd>{{ task.captureInfo?.captureDate || '未记录' }}</dd></div></dl>
    <p v-if="task.errorMessage" class="history-task-error" :data-failed="statusCode==='FAILED'"><AppIcon name="Warning" :size="15" /><span>任务记录的异常说明：{{ task.errorMessage }}</span></p>
    <div v-if="task.resultReadError" class="history-result-read-error" role="status"><AppIcon name="Warning" :size="16" /><div><strong>结果详情读取未完成</strong><p>{{ task.resultReadError }}；上方保留本次列表已返回的统计与检测状态。</p><el-button size="small" :disabled="refreshing" @click="$emit('refresh')"><AppIcon name="Refresh" :size="14" />重新读取列表与结果</el-button></div></div>
    <div v-if="classCounts.length" class="history-class-counts"><span v-for="item in classCounts" :key="item.key">{{ item.label }}<strong>{{ item.count.toLocaleString('zh-CN') }}</strong></span></div>
    <p v-else-if="task.result && !task.resultReadError" class="history-card-note">分类计数未提供或没有非零记录，仍需人工复核。</p>
    <div v-if="previews.length" class="history-image-previews"><button v-for="(image,index) in previews.slice(0,6)" :key="index" type="button" :aria-label="`打开任务图片对照：${image.imageName || '预览 '+(index+1)}`" @click="$emit('trace',task.taskId)"><el-image :src="previewUrl(image)" :alt="image.imageName || '检测结果预览'" loading="lazy" fit="contain"><template #error><span class="history-preview-failure"><AppIcon name="Warning" :size="18" />预览未读取</span></template></el-image><span>{{ image.imageName || `预览 ${index+1}` }}</span></button></div>
    <p v-if="previews.length>6" class="history-card-note">展示本次读取预览中的前 6 张，更多图片请打开追溯详情。</p>
    <p v-if="!previews.length" class="history-preview-state" :role="task.resultLoading ? 'status' : undefined"><AppIcon :name="task.resultLoading ? 'Connection' : 'Picture'" :size="18" />{{ task.resultLoading ? '正在读取结果详情与预览…' : '本次未读取到可展示预览，可打开追溯详情核对。' }}</p>
    <footer class="history-card-actions"><el-button type="primary" plain size="small" @click="$emit('trace',task.taskId)"><AppIcon name="Search" :size="15" />追溯详情</el-button><router-link class="history-report-link" :to="{path:'/quality/reports',query:{taskId:task.taskId}}"><AppIcon name="Document" :size="15" />编写报告草稿</router-link><a v-if="resultHref" :href="resultHref" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer" aria-label="查看本任务结果 JSON，新窗口打开">结果 JSON<AppIcon name="TopRight" :size="14" /></a></footer>
    <details v-if="task.sourceOssPrefix || cached" class="history-local-details"><summary>存储资料与本机缓存</summary><p v-if="task.sourceOssPrefix">来源存储标识 <code>{{ task.sourceOssPrefix }}</code></p><template v-if="cached"><p>这里只清除本机任务缓存，后端记录继续保留，服务器检测不会被取消；重新查询可能再次缓存。</p><el-button type="danger" plain size="small" :disabled="cacheBusy" @click="$emit('remove-cache',task.taskId)"><AppIcon name="Delete" :size="14" />清除本机任务缓存</el-button></template></details>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { knownCount } from '@/utils/countPresentation'
import { beijingDateTime } from '@/utils/beijingTime'
import { CATEGORY_LABELS } from '@/stores/taskStore'
const props = defineProps({ task:{type:Object,required:true}, cached:Boolean, refreshing:Boolean, cacheBusy:Boolean })
defineEmits(['trace','refresh','remove-cache'])
const statusCode = computed(() => props.task.status ? String(props.task.status).toUpperCase() : ({uploading:'UPLOADING',uploaded:'UPLOADED',queued:'QUEUED',detecting:'DETECTING',failed:'FAILED',completed:'COMPLETED'}[props.task.stage] || 'UNKNOWN'))
const count = value => knownCount(value)?.toLocaleString('zh-CN') ?? '—'
const time = value => value ? beijingDateTime(value) || '时间格式未知' : '未记录'
function safeHref(value) {
  if(typeof value!=='string'||!value.trim())return ''
  try{const url=new URL(value,window.location.href);return ['https:','http:'].includes(url.protocol)&&!url.username&&!url.password?url.href:''}catch{return ''}
}
const previewUrl = image => safeHref(image?.annotatedUrl) || safeHref(image?.previewUrl)
const previews = computed(() => (Array.isArray(props.task.result?.previewImages) ? props.task.result.previewImages : []).filter(image=>image&&previewUrl(image)))
const resultHref = computed(() => safeHref(props.task.result?.resultJsonUrl))
const classCounts = computed(() => {
  const counts=props.task.result?.statistics?.classCounts
  return counts&&typeof counts==='object'&&!Array.isArray(counts)?Object.entries(counts).flatMap(([key,value])=>{const count=knownCount(value);return count!==null&&count>0?[{key,label:CATEGORY_LABELS[key] || key,count}]:[]}):[]
})
</script>

<style scoped>
.detection-history-card { min-width:0; padding:20px; border:1px solid var(--app-border); border-radius:12px; background:white; color:var(--app-text); }
.history-card-heading { display:flex; align-items:flex-start; gap:11px; }
.history-card-symbol { display:grid; place-items:center; width:36px; height:36px; flex:0 0 36px; border-radius:9px; background:var(--app-primary-soft); color:var(--app-primary); }
.history-card-heading > div { flex:1; min-width:0; }
.history-card-heading h3 { margin:0 0 6px; font-size:15px; font-weight:600; line-height:1.7; overflow-wrap:anywhere; }
.history-card-heading > .business-status { flex-shrink:0; }
.history-task-link { max-width:100%; padding:0; border:0; background:none; text-align:left; color:var(--app-primary); font:inherit; font-size:11px; line-height:1.8; overflow-wrap:anywhere; cursor:pointer; }
.history-quality-states { display:flex; align-items:center; flex-wrap:wrap; gap:8px 14px; margin:15px 0; }
.history-quality-states > span { display:inline-flex; align-items:center; gap:6px; color:var(--app-text-secondary); font-size:11px; line-height:1.8; }
.history-image-counts { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin:0; padding:15px 0; border-block:1px solid var(--app-border); }
.history-image-counts dt { font-size:11px; color:var(--app-text-secondary); line-height:1.8; }
.history-image-counts dd { margin:7px 0 0; color:var(--app-text); font-size:23px; font-weight:600; line-height:1.4; font-variant-numeric:tabular-nums; }
.history-image-counts dd small { margin-left:5px; color:var(--app-text-secondary); font-size:11px; font-weight:400; }
.history-image-counts [data-attention=true] dd { color:var(--app-danger); }
.history-card-time { display:flex; align-items:flex-start; gap:6px; margin:12px 0 18px; font-size:11px; line-height:1.8; color:var(--app-text-secondary); font-variant-numeric:tabular-nums; }
.history-card-time .el-icon { flex-shrink:0; margin-top:3px; }
.history-capture-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px 18px; margin:0 0 18px; }
.history-capture-fields > div { min-width:0; }
.history-capture-fields dt { color:var(--app-text-secondary); font-size:11px; line-height:1.8; }
.history-capture-fields dd { display:grid; justify-items:start; gap:3px; margin:5px 0 0; font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.history-capture-fields a { color:var(--app-primary); text-decoration:underline; text-underline-offset:3px; overflow-wrap:anywhere; max-width:100%; }
.history-card-note,.history-preview-state { margin:12px 0; color:var(--app-text-secondary); font-size:11px; line-height:1.85; }
.history-preview-state { display:flex; align-items:center; gap:8px; padding:16px 0; }
.history-preview-state .el-icon { color:var(--app-primary); flex-shrink:0; }
.history-class-counts { display:flex; flex-wrap:wrap; gap:7px; margin:12px 0; }
.history-class-counts > span { display:inline-flex; align-items:center; gap:8px; padding:4px 8px; border-radius:5px; background:var(--app-primary-soft); color:var(--app-text-secondary); font-size:11px; line-height:1.8; }
.history-class-counts strong { color:var(--app-text); font-weight:550; }
.history-image-previews { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin-top:16px; }
.history-image-previews > button { display:grid; gap:5px; min-width:0; padding:5px; border:1px solid var(--app-border); border-radius:7px; background:var(--app-bg); cursor:pointer; text-align:left; }
.history-image-previews :deep(.el-image) { width:100%; height:70px; }
.history-image-previews > button > span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--app-text-secondary); font-size:10px; line-height:1.7; }
.history-preview-failure { display:flex; flex-direction:column; justify-content:center; align-items:center; gap:5px; height:100%; color:var(--app-text-secondary); font-size:10px; }
.history-card-actions { display:flex; flex-wrap:wrap; align-items:center; gap:12px 15px; margin-top:18px; padding-top:14px; border-top:1px solid var(--app-border); }
.history-card-actions a { display:inline-flex; align-items:center; gap:6px; color:var(--app-primary); font-size:12px; line-height:1.8; text-decoration:none; }
.history-task-error,.history-result-read-error { display:flex; align-items:flex-start; gap:8px; margin:14px 0; padding:11px 12px; border-radius:7px; background:var(--app-warning-soft); color:var(--app-warning); font-size:12px; line-height:1.85; overflow-wrap:anywhere; }
.history-task-error[data-failed=true] { color:var(--app-danger); background:var(--app-danger-soft); }
.history-task-error > .el-icon,.history-result-read-error > .el-icon { flex-shrink:0; margin-top:3px; }
.history-result-read-error strong { font-weight:550; }
.history-result-read-error p { margin:5px 0 10px; }
.history-local-details { margin-top:16px; color:var(--app-text-secondary); font-size:11px; line-height:1.85; }
.history-local-details summary { width:fit-content; cursor:pointer; }
.history-local-details p { margin:10px 0; overflow-wrap:anywhere; }
.history-local-details code { display:block; margin-top:6px; font-size:11px; overflow-wrap:anywhere; }
.detection-history-card :is(button,a,summary):focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; border-radius:3px; }
@media(max-width:640px) { .detection-history-card { padding:16px; } .history-card-heading { flex-wrap:wrap; } .history-card-heading > .business-status { margin-left:47px; } .history-capture-fields { grid-template-columns:minmax(0,1fr); gap:12px; } }
</style>
