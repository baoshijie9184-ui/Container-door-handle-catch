<template>
  <section class="trace-report-overview" :aria-label="`${kindLabel}追溯摘要`">
    <dl class="trace-overview-identity"><div><dt>{{ kindLabel }}编号</dt><dd>{{ referenceNo || '未记录' }}</dd></div><div><dt>{{ workOrder ? '覆盖批次' : '采集区域（摘要首条）' }}</dt><dd>{{ workOrder ? listCount(report.summary?.batchNos) : report.summary?.region || '未记录' }}</dd></div><div><dt>{{ workOrder ? '覆盖区域' : '采集人员（摘要首条）' }}</dt><dd>{{ workOrder ? listText(report.summary?.regions) : report.summary?.collector || '未记录' }}</dd></div><div><dt>摘要生成 · UTC+8</dt><dd>{{ time(report.generatedAt) }}</dd></div></dl>
    <TraceReportMetrics :report="report" />
    <div class="trace-overview-columns">
      <section class="trace-overview-section"><h3><AppIcon name="DocumentChecked" :size="18" />质量处理情况</h3><dl class="trace-quality-counts"><div v-for="metric in qualityMetrics" :key="metric.key" :data-attention="metric.attention && countValue(report.quality?.[metric.key]) > 0"><dt>{{ metric.label }}</dt><dd>{{ count(report.quality?.[metric.key]) }}<small v-if="countValue(report.quality?.[metric.key])!==null">个任务</small></dd></div></dl><p class="trace-overview-note">各项按关联任务统计，同一任务可能计入多项，不能相加作为任务总数。未复核任务不能据此认定为零缺陷；任务闭环与报告审批分别核对。</p></section>
      <section class="trace-overview-section"><h3><AppIcon name="Collection" :size="18" />关联来源</h3><dl class="trace-source-list"><div v-for="group in sourceGroups" :key="group.key"><dt>{{ group.label }}</dt><dd><template v-if="Array.isArray(group.values)"><ul v-if="group.values.length" class="trace-source-values"><li v-for="(value,index) in group.values.slice(0,6)" :key="`${index}:${value}`"><router-link v-if="group.route" :to="{path:group.route,query:{[group.query]:value}}">{{ value }}</router-link><span v-else>{{ value }}</span></li></ul><span v-else>未返回可展示的来源</span><details v-if="group.values.length>6"><summary>展开其余 {{ group.values.length - 6 }} 项</summary><ul class="trace-source-values"><li v-for="(value,index) in group.values.slice(6)" :key="`${index}:${value}`"><router-link v-if="group.route" :to="{path:group.route,query:{[group.query]:value}}">{{ value }}</router-link><span v-else>{{ value }}</span></li></ul></details></template><span v-else>本摘要未提供此集合，具体来源请核对任务明细</span></dd></div></dl><p v-if="!workOrder" class="trace-overview-note">采集区域和人员取服务端摘要的首条任务，不表示整个批次的采集信息完全一致。</p></section>
    </div>
    <dl class="trace-overview-times"><div><dt>任务创建范围 · UTC+8</dt><dd>{{ time(report.timeRange?.createdFrom) }} 至 {{ time(report.timeRange?.createdTo) }}</dd></div><div><dt>最晚检测完成 · UTC+8</dt><dd>{{ time(report.timeRange?.finishedTo) }}</dd></div><div><dt>最近任务更新 · UTC+8</dt><dd>{{ time(report.timeRange?.lastUpdatedAt) }}</dd></div></dl>
    <div class="trace-overview-columns trace-distributions">
      <section class="trace-overview-section"><h3><AppIcon name="Search" :size="18" />主要缺陷任务分布</h3><p class="trace-overview-note">按任务记录的主要缺陷归类，不是全部缺陷目标的分类数量。</p><el-table :scrollbar-tabindex="0" role="region" aria-label="已读缺陷类型分布" :data="distributionRows(report.distribution?.defectType)" size="small" empty-text="本摘要未提供可展示的分类统计"><el-table-column prop="name" label="主要缺陷" min-width="150" /><el-table-column label="任务数" width="95"><template #default="{row}">{{ count(row.count) }}</template></el-table-column></el-table></section>
      <section class="trace-overview-section"><h3><AppIcon :name="workOrder ? 'Connection' : 'Warning'" :size="18" />{{ workOrder ? '检测任务状态分布' : '任务最高严重等级分布' }}</h3><p class="trace-overview-note">{{ workOrder ? '检测状态与人工复核、处置和放行分别记录。' : '按每个任务记录的最高等级归类，缺失等级不推断为正常。' }}</p><el-table :scrollbar-tabindex="0" role="region" aria-label="已读状态或严重等级分布" :data="distributionRows(workOrder ? report.distribution?.status : report.distribution?.severity)" size="small" empty-text="本摘要未提供可展示的分布统计"><el-table-column :label="workOrder ? '检测状态' : '最高等级'" min-width="150"><template #default="{row}"><StatusBadge :domain="workOrder ? 'detection' : 'severity'" :code="row.name" :label="workOrder ? undefined : severityText(row.name)" /></template></el-table-column><el-table-column label="任务数" width="95"><template #default="{row}">{{ count(row.count) }}</template></el-table-column></el-table></section>
    </div>
    <section class="trace-overview-section trace-overview-records">
      <div class="trace-records-heading"><h3><AppIcon name="Tickets" :size="18" />{{ kindLabel }}任务明细</h3><span>本次返回 {{ records.length }} 条<span v-if="totalTasks!==null"> / 汇总 {{ count(totalTasks) }} 个任务</span></span></div>
      <p class="trace-overview-note">当前接口按创建时间升序最多返回 50 条明细，统计汇总覆盖当前账号可访问的关联任务。{{ totalTasks!==null && totalTasks>records.length ? '下方明细没有覆盖全部关联任务。' : '明细与汇总范围仍需分别核对。' }}</p>
      <div class="trace-record-query"><el-input v-model="recordQuery" clearable placeholder="搜索已返回的任务、设备或责任人" aria-label="搜索当前已返回的追溯任务明细"><template #prefix><AppIcon name="Search" :size="15" /></template></el-input><span>显示 {{ visibleRecords.length.toLocaleString('zh-CN') }} / {{ records.length.toLocaleString('zh-CN') }} 条</span></div>
      <p v-if="recordQuery.trim()" class="trace-overview-note">此筛选仅影响下方已返回明细，上方统计仍属于原{{ kindLabel }}摘要范围。</p>
      <el-table :scrollbar-tabindex="0" role="region" aria-label="本次追溯关联任务" :data="visibleRecords" row-key="taskId" size="small" max-height="460">
        <template #empty><CollectionEmptyState :filtered="!!recordQuery.trim()" empty-title="本次摘要未返回任务明细" empty-description="不能据此判断没有关联任务，可在下方检测记录入口继续核对。" @reset="recordQuery = ''" /></template>
        <el-table-column label="任务与采集来源" min-width="235"><template #default="{row}"><div class="trace-record-source"><button type="button" @click="$emit('open-trace',row.taskId)">{{ row.taskId }}</button><router-link v-if="workOrder && row.batchNo" :to="{path:'/quality/batch-trace',query:{batchNo:row.batchNo}}">批次 {{ row.batchNo }}</router-link><router-link v-else-if="!workOrder && row.workOrderNo" :to="{path:'/quality/work-order-trace',query:{workOrderNo:row.workOrderNo}}">工单 {{ row.workOrderNo }}</router-link><span v-else>{{ workOrder ? '批次未记录' : '工单未记录' }}</span><span>设备 {{ row.deviceName || '未记录' }}</span></div></template></el-table-column>
        <el-table-column label="检测与流转" min-width="165"><template #default="{row}"><div class="trace-record-states"><span>检测 <StatusBadge domain="detection" :code="row.status" /></span><span>流转 <StatusBadge domain="flow" :code="row.flowStatus" /></span></div></template></el-table-column>
        <el-table-column label="人工复核" min-width="125"><template #default="{row}"><StatusBadge domain="review" :code="row.reviewStatus" /></template></el-table-column>
        <el-table-column label="检测缺陷数" width="110"><template #default="{row}">{{ count(row.defectCount) }}</template></el-table-column>
        <el-table-column label="最高等级" min-width="125"><template #default="{row}"><StatusBadge domain="severity" :code="row.maxDefectSeverity" :label="row.maxDefectSeverity ? severityText(row.maxDefectSeverity) : '未记录等级'" /></template></el-table-column>
        <el-table-column label="责任与截止" min-width="180"><template #default="{row}"><div class="trace-record-responsibility"><strong>{{ row.assignee || '未记录责任人' }}</strong><span>{{ row.dueAt ? time(row.dueAt) + ' · UTC+8' : '未设置截止时间' }}</span></div></template></el-table-column>
        <el-table-column label="操作" width="155"><template #default="{row}"><div class="trace-record-actions"><el-button size="small" @click="$emit('open-trace',row.taskId)"><AppIcon name="Search" :size="14" />详情</el-button><el-button size="small" :disabled="reportDownloading" @click="$emit('download-task',row.taskId)"><AppIcon name="Download" :size="14" />摘要</el-button></div></template></el-table-column>
      </el-table>
      <router-link class="trace-history-link" :to="{path:'/inspection/history',query:{keyword:referenceNo}}">按此编号继续查询检测记录<AppIcon name="ArrowRight" :size="15" /></router-link><p class="trace-overview-note">检测记录使用关键词匹配，请继续核对工单、批次与账号范围。摘要下载不代替已独立审批的正式报告。</p>
    </section>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import TraceReportMetrics from './TraceReportMetrics.vue'
import CollectionEmptyState from './CollectionEmptyState.vue'
import { knownCount } from '@/utils/countPresentation'
import { beijingDateTime } from '@/utils/beijingTime'
import { severityText } from '@/utils/qualityWorkflow'
const props = defineProps({ report:{ type:Object, required:true }, kind:{ type:String, required:true }, reportDownloading:Boolean })
defineEmits(['open-trace','download-task'])
const workOrder = computed(() => props.kind === 'work-order')
const kindLabel = computed(() => workOrder.value ? '工单' : '批次')
const referenceNo = computed(() => workOrder.value ? props.report.workOrderNo : props.report.batchNo)
const records = computed(() => Array.isArray(props.report.records) ? props.report.records : [])
const recordQuery = ref('')
const visibleRecords = computed(() => {
  const needle = recordQuery.value.trim().toLowerCase()
  return records.value.filter(row => !needle || [row.taskId, row.batchNo, row.workOrderNo, row.deviceName, row.assignee].filter(value => typeof value === 'string').join(' ').toLowerCase().includes(needle))
})
watch(referenceNo, () => { recordQuery.value = '' })
const totalTasks = computed(() => knownCount(props.report.summary?.taskCount))
const countValue = knownCount
const count = value => knownCount(value)?.toLocaleString('zh-CN') ?? '—'
const time = value => value ? beijingDateTime(value) || '时间格式未知' : '未记录'
const listCount = value => Array.isArray(value) ? count(value.length) : '—'
const listText = value => Array.isArray(value) ? value.join('、') || '未记录' : '未记录'
const qualityMetrics = [ {key:'pendingReview',label:'待复核',attention:true}, {key:'reviewed',label:'已复核'}, {key:'disposed',label:'已处置'}, {key:'reworkRequired',label:'需返工',attention:true}, {key:'recheckRequired',label:'需复检',attention:true}, {key:'closed',label:'闭环任务'} ]
const sourceGroups = computed(() => {
  const summary = props.report.summary || {}
  return [
    ...(workOrder.value ? [{key:'batchNos',label:'覆盖批次',values:summary.batchNos,route:'/quality/batch-trace',query:'batchNo'}, {key:'collectors',label:'采集人员',values:summary.collectors}] : [{key:'workOrders',label:'关联工单',values:summary.workOrders,route:'/quality/work-order-trace',query:'workOrderNo'}]),
    {key:'devices',label:'设备名称',values:summary.devices}, {key:'models',label:'任务记录模型',values:summary.models}
  ]
})
function distributionRows(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? Object.entries(value).map(([name,count])=>({name,count})).sort((a,b)=>(knownCount(b.count)??-1)-(knownCount(a.count)??-1)) : []
}
</script>

<style scoped>
.trace-report-overview { color:var(--app-text); min-width:0; }
.trace-overview-identity { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:20px; margin:0; padding:18px 0; border-bottom:1px solid var(--app-border); }
.trace-overview-identity > div { min-width:0; }
.trace-overview-identity dt { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.trace-overview-identity dd { margin:7px 0 0; color:var(--app-text); font-size:14px; line-height:1.85; font-weight:550; overflow-wrap:anywhere; }
.trace-overview-columns { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:26px; }
.trace-overview-section { min-width:0; border-top:1px solid var(--app-border); padding:20px 0; }
.trace-overview-section h3 { display:flex; align-items:center; gap:8px; color:var(--app-text); font-size:14px; font-weight:600; line-height:1.8; margin:0 0 16px; }
.trace-overview-section h3 > .el-icon { flex-shrink:0; color:var(--app-primary); }
.trace-quality-counts { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:18px 14px; margin:0; }
.trace-quality-counts dt { font-size:12px; color:var(--app-text-secondary); line-height:1.8; }
.trace-quality-counts dd { font-size:22px; line-height:1.5; font-weight:600; margin:7px 0 0; font-variant-numeric:tabular-nums; }
.trace-quality-counts dd small { display:block; color:var(--app-text-secondary); font-size:11px; font-weight:400; }
.trace-quality-counts > [data-attention=true] dd { color:var(--app-warning); }
.trace-overview-note { color:var(--app-text-secondary); font-size:12px; line-height:1.85; margin:14px 0; max-width:85ch; overflow-wrap:anywhere; }
.trace-source-list { display:grid; gap:15px; margin:0; }
.trace-source-list dt { font-size:12px; line-height:1.8; color:var(--app-text-secondary); }
.trace-source-list dd { margin:6px 0 0; color:var(--app-text); font-size:12px; line-height:1.85; overflow-wrap:anywhere; }
.trace-source-values { display:flex; flex-wrap:wrap; gap:6px 12px; margin:0; padding:0; list-style:none; }
.trace-source-values li { max-width:100%; overflow-wrap:anywhere; }
.trace-source-values a { color:var(--app-primary); text-decoration:underline; text-underline-offset:3px; }
.trace-source-list summary { width:fit-content; cursor:pointer; color:var(--app-primary); margin-top:9px; }
.trace-source-list details[open] .trace-source-values { margin-top:9px; }
.trace-overview-times { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:18px; margin:0 0 18px; padding:16px 0; border-top:1px solid var(--app-border); }
.trace-overview-times dt { color:var(--app-text-secondary); font-size:11px; line-height:1.8; }
.trace-overview-times dd { margin:7px 0 0; color:var(--app-text); font-size:12px; line-height:1.85; overflow-wrap:anywhere; font-variant-numeric:tabular-nums; }
.trace-records-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }
.trace-records-heading h3 { margin:0; }
.trace-record-query { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; margin:16px 0 12px; }
.trace-record-query .el-input { flex:1 1 240px; max-width:520px; }
.trace-record-query > span { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.trace-records-heading > span { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.trace-record-source { display:grid; justify-items:start; gap:5px; min-width:0; padding:7px 0; }
.trace-record-source > button { max-width:100%; border:0; padding:0; background:none; color:var(--app-primary); text-align:left; font:inherit; font-size:12px; font-weight:550; line-height:1.85; overflow-wrap:anywhere; cursor:pointer; }
.trace-record-source :is(span,a) { font-size:12px; line-height:1.8; color:var(--app-text-secondary); overflow-wrap:anywhere; }
.trace-record-source a { text-decoration:underline; text-underline-offset:3px; }
.trace-record-states { display:grid; gap:8px; padding:6px 0; }
.trace-record-states > span { display:flex; align-items:center; flex-wrap:wrap; gap:6px; color:var(--app-text-secondary); font-size:11px; line-height:1.8; }
.trace-record-responsibility { display:grid; gap:6px; font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.trace-record-responsibility strong { color:var(--app-text); font-weight:550; }
.trace-record-responsibility span { color:var(--app-text-secondary); }
.trace-record-actions { display:flex; flex-wrap:wrap; gap:7px; }
.trace-record-actions .el-button + .el-button { margin-left:0; }
.trace-history-link { display:inline-flex; align-items:center; gap:8px; margin-top:18px; color:var(--app-primary); font-size:12px; line-height:1.8; text-decoration:none; }
.trace-report-overview :is(a,summary,button):focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; border-radius:3px; }
@media(max-width:1080px) { .trace-overview-columns { grid-template-columns:minmax(0,1fr); gap:0; } .trace-overview-identity { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media(max-width:640px) { .trace-overview-identity,.trace-overview-times { grid-template-columns:minmax(0,1fr); gap:13px; } .trace-quality-counts { grid-template-columns:repeat(2,minmax(0,1fr)); } .trace-overview-section { padding:17px 0; } }
</style>
