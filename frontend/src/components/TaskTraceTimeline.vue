<template>
  <section class="task-trace-timeline" :aria-labelledby="headingId">
    <h4 :id="headingId"><AppIcon name="Clock" :size="17" />已记录的流程节点<span>{{ Array.isArray(events) ? `${rows.length.toLocaleString('zh-CN')} 个` : '数量未返回' }}</span></h4>
    <p class="trace-timeline-note">由当前任务资料汇成，按已知时间排列，不等于完整审计历史。未知时间单独注明，所有时间为 UTC+8。</p>
    <ol v-if="rows.length"><li v-for="row in rows" :key="row.index"><span class="trace-timeline-icon"><AppIcon :name="icons[row.event.eventType] || 'Document'" :size="15" /></span><div><header><strong>{{ row.event.eventName || '未命名节点' }}</strong><time>{{ time(row.event.occurredAt) }}</time></header><p class="trace-timeline-operator">记录操作人 {{ row.event.operator || '未记录' }}</p><p v-if="row.event.description" class="trace-timeline-description">{{ row.event.description }}</p></div></li></ol>
    <p v-else class="trace-timeline-empty"><AppIcon name="Document" :size="19" />未读取到可展示节点；这不证明相关业务操作没有发生。</p>
  </section>
</template>
<script setup>
import { computed, getCurrentInstance } from 'vue'
import AppIcon from './AppIcon.vue'
import { businessDate, beijingDateTime } from '@/utils/beijingTime'
const props = defineProps({ events: Array })
const headingId = `task-trace-timeline-${getCurrentInstance().uid}`
const icons = { CREATED:'Tickets', DISPATCHED:'Picture', FINISHED:'DocumentChecked', ASSIGNED:'User', REVIEWED:'Search', DISPOSED:'Document', REWORK_COMPLETED:'Edit' }
const rows = computed(() => (Array.isArray(props.events) ? props.events : []).map((event,index) => ({ event,index })).filter(row => row.event && typeof row.event === 'object' && !Array.isArray(row.event)).sort((a,b) => {
  const left = businessDate(a.event.occurredAt)?.getTime(), right = businessDate(b.event.occurredAt)?.getTime()
  if (left == null && right == null) return a.index - b.index
  if (left == null) return 1
  if (right == null) return -1
  return left - right || a.index - b.index
}))
const time = value => value ? beijingDateTime(value) || '时间格式未知' : '时间未记录'
</script>
<style scoped>
.task-trace-timeline { padding:20px 0 4px; border-top:1px solid var(--app-border); }
.task-trace-timeline h4 { display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin:0; color:var(--app-text); font-size:14px; font-weight:600; }
.task-trace-timeline h4 > .el-icon { color:var(--app-primary); }
.task-trace-timeline h4 > span { margin-left:auto; color:var(--app-text-muted); font-size:12px; font-weight:400; }
.trace-timeline-note { margin:9px 0 20px; color:var(--app-text-muted); font-size:12px; line-height:1.8; }
.task-trace-timeline ol { list-style:none; margin:0; padding:0; }
.task-trace-timeline li { display:grid; grid-template-columns:30px minmax(0,1fr); gap:12px; position:relative; padding-bottom:22px; }
.task-trace-timeline li:not(:last-child)::before { content:''; position:absolute; left:14px; top:32px; bottom:2px; width:1px; background:var(--app-border); }
.trace-timeline-icon { display:grid; place-items:center; width:30px; height:30px; border-radius:8px; color:var(--app-primary); background:var(--app-primary-soft); }
.task-trace-timeline li > div { min-width:0; padding-top:4px; }
.task-trace-timeline li header { display:flex; align-items:baseline; flex-wrap:wrap; gap:6px 16px; }
.task-trace-timeline strong { color:var(--app-text); font-size:13px; font-weight:550; overflow-wrap:anywhere; }
.task-trace-timeline time { margin-left:auto; color:var(--app-text-muted); font-size:12px; font-variant-numeric:tabular-nums; }
.trace-timeline-operator { margin:7px 0 0; color:var(--app-text-secondary); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.trace-timeline-description { margin:5px 0 0; color:var(--app-text-secondary); font-size:12px; line-height:1.85; white-space:pre-wrap; overflow-wrap:anywhere; }
.trace-timeline-empty { display:flex; align-items:flex-start; gap:8px; padding:14px; border-radius:8px; color:var(--app-text-secondary); background:var(--app-bg); font-size:12px; line-height:1.8; }
.trace-timeline-empty > .el-icon { flex:0 0 auto; margin-top:2px; }
@media(max-width:580px) { .task-trace-timeline time { flex-basis:100%; margin-left:0; } }
</style>
