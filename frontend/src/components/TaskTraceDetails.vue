<template>
  <div class="task-trace-details">
    <section aria-label="任务与采集资料">
      <h4><AppIcon name="Tickets" :size="17" />任务与采集</h4>
      <dl><div><dt>任务编号</dt><dd>{{ detail.taskId || '未记录' }}</dd></div><div><dt>当前状态</dt><dd class="trace-statuses"><StatusBadge domain="flow" :code="detail.flowStatus" /><StatusBadge domain="detection" :code="detail.status" /></dd></div><div><dt>工单</dt><dd><router-link v-if="typeof detail.workOrderNo === 'string' && detail.workOrderNo.trim()" :to="{ path: '/quality/work-order-trace', query: { workOrderNo: detail.workOrderNo } }" target="_blank" rel="noopener noreferrer" :aria-label="'查看工单追溯：' + detail.workOrderNo">{{ detail.workOrderNo }}<AppIcon name="TopRight" :size="13" /></router-link><span v-else>未记录</span></dd></div><div><dt>批次</dt><dd><router-link v-if="typeof detail.batchNo === 'string' && detail.batchNo.trim()" :to="{ path: '/quality/batch-trace', query: { batchNo: detail.batchNo } }" target="_blank" rel="noopener noreferrer" :aria-label="'查看批次追溯：' + detail.batchNo">{{ detail.batchNo }}<AppIcon name="TopRight" :size="13" /></router-link><span v-else>未记录</span></dd></div><div><dt>采集日期</dt><dd>{{ detail.captureDate || '未记录' }}</dd></div><div><dt>采集区域</dt><dd>{{ detail.region || '未记录' }}</dd></div><div><dt>采集人</dt><dd>{{ detail.collector || '未记录' }}</dd></div><div><dt>采集设备</dt><dd>{{ detail.deviceName || '未记录' }}</dd></div><div><dt>图片批次</dt><dd>{{ detail.imageFolderName || '未记录' }}</dd></div><div><dt>质检站点</dt><dd>{{ detail.qualityStation || '未记录' }}</dd></div></dl>
    </section>
    <section aria-label="检测设置">
      <h4><AppIcon name="Picture" :size="17" />检测设置</h4>
      <dl><div><dt>检测模型编号</dt><dd>{{ detail.modelId ?? '未记录' }}</dd></div><div><dt>模型版本</dt><dd>{{ detail.modelVersion || '未记录' }}</dd></div><div><dt>置信度阈值</dt><dd>{{ formatEvidenceConfidence(detail.threshold) }}</dd></div></dl>
    </section>
    <section aria-label="人工复核记录">
      <h4><AppIcon name="Search" :size="17" />人工复核</h4>
      <dl><div><dt>复核状态</dt><dd><StatusBadge domain="review" :code="detail.reviewStatus" /></dd></div><div><dt>复核结论</dt><dd><StatusBadge domain="reviewConclusion" :code="detail.reviewConclusion" /></dd></div><div><dt>严重等级</dt><dd><StatusBadge domain="severity" :code="detail.severityLevel" /></dd></div><div><dt>已确认缺陷 / 误报数</dt><dd>{{ count(detail.confirmedDefectCount) }} / {{ count(detail.falsePositiveCount) }}</dd></div><div><dt>复核人</dt><dd>{{ detail.reviewer || '未记录' }}</dd></div><div><dt>复核时间 · UTC+8</dt><dd>{{ time(detail.reviewedAt) }}</dd></div><div v-if="detail.reviewRemark" class="trace-detail-wide"><dt>复核备注</dt><dd>{{ detail.reviewRemark }}</dd></div></dl>
    </section>
    <section aria-label="处置与返工记录">
      <h4><AppIcon name="DocumentChecked" :size="17" />处置与返工</h4>
      <dl><div><dt>处置状态</dt><dd><StatusBadge domain="qualityDisposition" :code="detail.dispositionStatus" /></dd></div><div><dt>处置方式</dt><dd><StatusBadge domain="dispositionAction" :code="detail.dispositionAction" /></dd></div><div><dt>处置操作人</dt><dd>{{ detail.dispositionOperator || '未记录' }}</dd></div><div><dt>处置时间 · UTC+8</dt><dd>{{ time(detail.disposedAt) }}</dd></div><div><dt>是否仍需复检</dt><dd>{{ detail.recheckRequired === true ? '需要复检' : detail.recheckRequired === false ? '当前记录未要求复检' : '尚未记录' }}</dd></div><div><dt>返工完成时间 · UTC+8</dt><dd>{{ time(detail.reworkCompletedAt) }}</dd></div><div><dt>返工操作人</dt><dd>{{ detail.reworkOperator || '未记录' }}</dd></div><div><dt>返工结果</dt><dd>{{ detail.reworkResult || '未记录' }}</dd></div><div v-if="detail.dispositionRemark" class="trace-detail-wide"><dt>处置备注</dt><dd>{{ detail.dispositionRemark }}</dd></div><div v-if="detail.reworkRemark" class="trace-detail-wide"><dt>返工备注</dt><dd>{{ detail.reworkRemark }}</dd></div></dl>
      <p>任务放行与报告审批分别记录；返工回填不代替实际复检。</p>
    </section>
  </div>
</template>
<script setup>
import AppIcon from './AppIcon.vue'
import StatusBadge from './StatusBadge.vue'
import { knownCount } from '@/utils/countPresentation'
import { beijingDateTime } from '@/utils/beijingTime'
import { formatEvidenceConfidence } from '@/utils/qualityRecords'
defineProps({ detail: { type: Object, required: true } })
const count = value => knownCount(value)?.toLocaleString('zh-CN') ?? '—'
const time = value => value ? beijingDateTime(value) || '时间格式未知' : '未记录'
</script>
<style scoped>
.task-trace-details { margin-top:20px; }
.task-trace-details > section { padding:18px 0; border-top:1px solid var(--app-border); }
.task-trace-details h4 { display:flex; align-items:center; gap:8px; margin:0 0 16px; color:var(--app-text); font-size:14px; font-weight:600; }
.task-trace-details h4 .el-icon { color:var(--app-primary); }
.task-trace-details dl { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px 28px; margin:0; }
.task-trace-details dl > div { min-width:0; }
.task-trace-details dt { color:var(--app-text-muted); font-size:12px; line-height:1.8; }
.task-trace-details dd { margin:4px 0 0; color:var(--app-text); font-size:13px; line-height:1.8; white-space:pre-wrap; overflow-wrap:anywhere; }
.task-trace-details .trace-statuses { display:flex; flex-wrap:wrap; gap:6px; }
.trace-detail-wide { grid-column:1 / -1; }
.task-trace-details p { margin:16px 0 0; padding:10px 12px; border-radius:8px; background:var(--app-primary-light); color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
@media(max-width:580px) { .task-trace-details dl { grid-template-columns:minmax(0,1fr); gap:12px; }.task-trace-details > section { padding:16px 0; } }
.task-trace-details a { display:inline-flex; align-items:baseline; gap:5px; color:var(--app-primary); overflow-wrap:anywhere; text-underline-offset:3px; }
.task-trace-details a:hover { text-decoration:underline; }
.task-trace-details a:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
</style>
