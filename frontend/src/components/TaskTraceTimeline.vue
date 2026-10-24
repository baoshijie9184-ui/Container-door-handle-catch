<template>
  <section class="task-trace-timeline" :aria-labelledby="headingId">
    <h4 :id="headingId"><AppIcon name="Clock" :size="17" />已记录的流程节点<span>{{ groups ? '本次返回 '+count.toLocaleString('zh-CN')+' 个' : '数量未返回' }}</span></h4>
    <p class="trace-timeline-note">由当前任务资料汇成，不等于完整审计历史。时间按 UTC+8 展示，任务处理与报告审批分别核对。</p>
    <section v-for="group in groups || []" :key="group.key" class="trace-timeline-group" :aria-label="group.label" :data-unknown="group.key==='undated'">
      <h5>{{ group.label }}<span>{{ group.rows.length }} 个</span></h5>
      <p v-if="group.key==='undated'" class="trace-timeline-note">以下节点无法确定在流程中的时间位置，保持本次返回顺序。</p>
      <ol><li v-for="row in group.rows" :key="row.key"><span class="trace-timeline-icon"><AppIcon :name="row.icon" :size="15" /></span><div>
        <header><strong>{{ row.name }}</strong><span class="trace-timeline-category">{{ row.category }}</span><time>{{ row.timeLabel }}</time></header>
        <p v-if="!row.complete" class="trace-timeline-incomplete">此条记录未完整返回，未推断操作或结果。</p>
        <p class="trace-timeline-operator">记录操作人 {{ row.operator }}</p>
        <details v-if="row.longDescription" class="trace-timeline-description-details"><summary>查看完整节点说明</summary><pre tabindex="0" :aria-label="row.name+'的完整节点说明'">{{ row.description }}</pre></details>
        <p v-else-if="row.description" class="trace-timeline-description">{{ row.description }}</p>
        <details class="trace-timeline-source"><summary>节点类型与时间字段</summary><dl><dt>类型代码</dt><dd>{{ row.type || '未记录' }}</dd><dt>原时间字段</dt><dd>{{ row.rawTime || '未记录' }}</dd></dl></details>
      </div></li></ol>
    </section>
    <p v-if="!count" class="trace-timeline-empty"><AppIcon name="Document" :size="19" />{{ groups ? '本次未返回流程节点；这不证明相关业务操作没有发生。' : '流程节点未完整返回，请重新读取当前任务核对。' }}</p>
  </section>
</template>
<script setup>
import { computed, getCurrentInstance } from 'vue'
import AppIcon from './AppIcon.vue'
import { taskTimelineGroups } from '@/utils/taskTimelinePresentation'
const props=defineProps({events:Array})
const headingId='task-trace-timeline-'+getCurrentInstance().uid
const groups=computed(()=>taskTimelineGroups(props.events))
const count=computed(()=>groups.value?.reduce((sum,group)=>sum+group.rows.length,0)||0)
</script>
<style scoped>
.task-trace-timeline{padding:20px 0 4px;border-top:1px solid var(--app-border);min-width:0}
.task-trace-timeline h4{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:0;color:var(--app-text);font-size:14px;font-weight:600}
.task-trace-timeline h4>.el-icon{color:var(--app-primary);flex:none}
.task-trace-timeline h4>span{margin-left:auto;color:var(--app-text-secondary);font-size:12px;font-weight:400}
.trace-timeline-note{margin:9px 0 18px;color:var(--app-text-secondary);font-size:12px;line-height:1.85}
.trace-timeline-group h5{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--app-text-secondary);font-weight:600;margin:18px 0 14px}
.trace-timeline-group h5>span{font-weight:400}
.trace-timeline-group[data-unknown=true]{padding-top:4px;border-top:1px solid var(--app-border)}
.trace-timeline-group[data-unknown=true] h5{color:var(--app-warning)}
.task-trace-timeline ol{list-style:none;margin:0;padding:0}
.task-trace-timeline li{display:grid;grid-template-columns:30px minmax(0,1fr);gap:12px;position:relative;padding-bottom:22px}
.task-trace-timeline li:not(:last-child)::before{content:'';position:absolute;left:14px;top:32px;bottom:2px;width:1px;background:var(--app-border)}
.trace-timeline-group[data-unknown=true] li::before{display:none}
.trace-timeline-icon{display:grid;place-items:center;width:30px;height:30px;border-radius:8px;color:var(--app-primary);background:var(--app-primary-soft)}
.trace-timeline-group[data-unknown=true] .trace-timeline-icon{color:var(--app-warning);background:var(--app-warning-soft)}
.task-trace-timeline li>div{min-width:0;padding-top:4px}
.task-trace-timeline li header{display:flex;align-items:baseline;flex-wrap:wrap;gap:6px 12px}
.task-trace-timeline strong{color:var(--app-text);font-size:13px;font-weight:600;overflow-wrap:anywhere}
.trace-timeline-category{font-size:12px;color:var(--app-text-secondary)}
.task-trace-timeline time{margin-left:auto;color:var(--app-text-secondary);font-size:12px;font-variant-numeric:tabular-nums}
.trace-timeline-operator,.trace-timeline-incomplete{margin:7px 0 0;color:var(--app-text-secondary);font-size:12px;line-height:1.85;overflow-wrap:anywhere}
.trace-timeline-incomplete{color:var(--app-warning)}
.trace-timeline-description{margin:5px 0 0;color:var(--app-text-secondary);font-size:12px;line-height:1.85;white-space:pre-wrap;overflow-wrap:anywhere}
.trace-timeline-description-details,.trace-timeline-source{margin-top:8px;font-size:12px;line-height:1.85;color:var(--app-text-secondary)}
.task-trace-timeline summary{cursor:pointer;width:fit-content;max-width:100%;border-radius:3px;transition:color 180ms ease}
.task-trace-timeline summary:hover{color:var(--app-primary)}
.trace-timeline-description-details pre{max-height:240px;overflow:auto;overscroll-behavior:contain;white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;color:var(--app-text);padding:10px 12px;border-left:2px solid var(--app-border);margin:10px 0 0}
.trace-timeline-source dl{display:grid;grid-template-columns:90px minmax(0,1fr);gap:6px 12px;margin:10px 0}
.trace-timeline-source dd{margin:0;min-width:0;overflow-wrap:anywhere;color:var(--app-text)}
.trace-timeline-empty{display:flex;align-items:flex-start;gap:8px;padding:14px;border-radius:8px;color:var(--app-text-secondary);background:var(--app-bg);font-size:12px;line-height:1.85}
.trace-timeline-empty>.el-icon{flex:none;margin-top:2px}
.task-trace-timeline :is(summary,pre):focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}
@media(max-width:580px){.task-trace-timeline time{flex-basis:100%;margin-left:0}.trace-timeline-source dl{grid-template-columns:1fr;gap:3px}.trace-timeline-source dd{margin-bottom:7px}}
@media(prefers-reduced-motion:reduce){.task-trace-timeline summary{transition:none}}
</style>
