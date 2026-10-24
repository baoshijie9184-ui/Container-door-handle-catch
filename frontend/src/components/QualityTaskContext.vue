<template>
  <section v-if="task" class="quality-task-context" aria-label="当前质检任务">
    <header><span class="quality-context-icon"><AppIcon :name="operationIcon" :size="20" /></span><div><small>当前任务</small><strong>{{ task.taskId || '任务编号未记录' }}</strong></div><StatusBadge domain="flow" :code="value('flowStatus')" /></header>
    <dl><div><dt>责任人</dt><dd>{{ value('assignee') || '未记录责任人' }}</dd></div><div><dt>截止时间 · UTC+8</dt><dd>{{ deadline }}</dd></div><div><dt>人工复核</dt><dd><StatusBadge domain="review" :code="value('reviewStatus')" /></dd></div><div><dt>已记录的确认缺陷数</dt><dd>{{ confirmedDefects }}</dd></div></dl>
    <p>{{ operationNote }}</p>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import StatusBadge from './StatusBadge.vue'
import { knownCount } from '@/utils/countPresentation'
import { beijingDateTime } from '@/utils/beijingTime'
const props=defineProps({task:Object,operation:{type:String,default:'review'}})
const value = key => props.task?.[key] ?? props.task?.result?.[key]
const deadline=computed(()=>{const due=value('dueAt');return due?beijingDateTime(due)||'时间未记录':'未记录截止时间'})
const confirmedDefects=computed(()=>knownCount(value('confirmedDefectCount'))?.toLocaleString('zh-CN')??'—')
const operationIcon=computed(()=>({review:'Search',assignment:'User',disposition:'DocumentChecked',rework:'Edit'})[props.operation]||'Tickets')
const operationNote=computed(()=>({
  review:'对照原图、模型输出及人工判断后提交复核。复核结论与任务放行、报告审批分别记录。',
  assignment:'从员工账号中选择责任人，文字姓名不代替账号选择；核对站点、截止时间与本次分派对象。',
  disposition:'按人工复核结论选择后续处置；不满足条件时不能直接放行，报告仍需独立审批。',
  rework:'回填返工事实与证据。原处置要求复检时，返工记录不能代替实际复检。'
})[props.operation]||'提交前请核对当前任务与操作内容。')
</script>

<style scoped>
.quality-task-context { margin-bottom:20px; padding:16px; border:1px solid var(--app-border); border-radius:10px; background:var(--app-primary-light); }
.quality-task-context header { display:flex; align-items:flex-start; flex-wrap:wrap; gap:10px; }
.quality-context-icon { display:grid; place-items:center; flex:0 0 36px; height:36px; width:36px; border-radius:9px; color:var(--app-primary); background:var(--app-primary-soft); }
.quality-task-context header > div { flex:1 1 180px; min-width:0; display:grid; gap:4px; }
.quality-task-context header small { color:var(--app-text-muted); font-size:11px; }
.quality-task-context header strong { font-size:13px; font-weight:650; color:var(--app-text); overflow-wrap:anywhere; line-height:1.7; }
.quality-task-context dl { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; margin:18px 0 0; }
.quality-task-context dl > div { min-width:0; }
.quality-task-context dt { font-size:11px; line-height:1.8; color:var(--app-text-muted); }
.quality-task-context dd { margin:4px 0 0; font-size:12px; line-height:1.8; color:var(--app-text); overflow-wrap:anywhere; }
.quality-task-context p { margin:14px 0 0; padding-top:12px; border-top:1px solid var(--app-border); font-size:12px; color:var(--app-text-secondary); line-height:1.85; }
@media(max-width:480px) { .quality-task-context { padding:12px; } .quality-task-context dl { grid-template-columns:minmax(0,1fr); gap:10px; } }
</style>
