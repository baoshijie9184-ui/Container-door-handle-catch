<template>
  <section class="recent-execution" aria-label="本会话最近保存的执行" :aria-busy="loading">
    <header class="recent-execution-heading"><h3><AppIcon name="Operation" :size="17" />最近执行</h3><el-button size="small" :loading="loading" :disabled="!sessionId" @click="$emit('refresh')"><AppIcon name="Refresh" :size="14" />重新读取</el-button></header>
    <p class="recent-execution-scope">只读取当前会话保存的执行快照，刷新不会重新执行任务。</p>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <template v-else-if="loaded && trace && hasRecord">
      <div class="recent-execution-summary"><StatusBadge domain="task" :code="trace.status || 'UNKNOWN'" :label="traceStatus(trace.status)" /><span>{{ events.length }} 个已保存事件</span></div>
      <p class="recent-execution-time">快照更新 {{ traceTime(trace.updatedAt) }} · UTC+8</p>
      <ol v-if="visibleEvents.length" class="recent-execution-events"><li v-for="event in visibleEvents" :key="event.sequence" :data-tone="eventTone(event.type)"><span class="recent-event-symbol"><AppIcon :name="eventIcon(event.type)" :size="15" /></span><div><strong>{{ eventTitle(event) }}</strong><span>{{ event.payload.tool || event.payload.agent || '运行事件' }}</span><small>距运行开始 {{ traceDuration(event.payload.elapsedMs) }}</small></div></li></ol>
      <p v-else class="recent-execution-note">本快照未保存事件明细，不能据此判断工具是否执行。</p>
      <details class="recent-execution-identifiers"><summary>运行标识与框架</summary><dl><div><dt>运行编号</dt><dd>{{ trace.runId || '未记录' }}</dd></div><div><dt>记录框架</dt><dd>{{ trace.framework || '未记录' }}</dd></div></dl></details>
    </template>
    <div v-else class="recent-execution-empty"><AppIcon :name="loading ? 'Connection' : 'Operation'" :size="25" /><strong>{{ loading ? '正在读取会话记录' : loaded ? '本次未读到已保存的执行' : '执行记录尚未读取' }}</strong><p>{{ loading ? '读取完成后显示状态与事件' : '可重新读取或打开执行追溯；没有快照不代表业务从未发生。' }}</p></div>
    <p class="recent-execution-note">{{ visibleEvents.length ? '展示最近 8 个有效事件，' : '' }}事件记录与业务操作回执分别核对，完整日志和来源请打开执行追溯。</p>
    <router-link class="recent-execution-link" :to="traceRoute" @click="$emit('navigate')">打开执行追溯<AppIcon name="ArrowRight" :size="15" /></router-link>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { eventCategory, eventTitle, eventTone, normalizeTraceEvents, traceDuration, traceStatus, traceTime } from '@/utils/agentTrace'
const props = defineProps({ sessionId:String, trace:Object, loading:Boolean, loaded:Boolean, error:String })
defineEmits(['refresh','navigate'])
const events = computed(() => props.loaded && !props.error ? normalizeTraceEvents(props.trace?.events, true) : [])
const visibleEvents = computed(() => events.value.slice(-8))
const hasRecord = computed(() => !!(props.trace?.runId || props.trace?.status || events.value.length))
const traceRoute = computed(() => ({ path:'/agent/trace', query:props.loaded && !props.error && props.trace?.runId ? { runId:props.trace.runId } : props.sessionId ? { sessionId:props.sessionId } : {} }))
const eventIcon = type => eventTone(type) === 'danger' ? 'Warning' : /CANCELLED$/.test(type) ? 'Close' : ({ TOOL:'Connection', MODEL:'Tickets', AUTHORIZATION:'Lock', AGENT:'ChatDotRound', CONTEXT:'Document', SKILL:'Collection' }[eventCategory(type)] || 'Operation')
</script>

<style scoped>
.recent-execution { min-width:0; color:var(--app-text); }
.recent-execution-heading { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }
.recent-execution-heading h3 { display:flex; align-items:center; gap:8px; margin:0; font-size:14px; font-weight:600; }
.recent-execution-heading h3 .el-icon { color:var(--app-primary); }
.recent-execution-scope,.recent-execution-note,.recent-execution-time { margin:10px 0 16px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; overflow-wrap:anywhere; }
.recent-execution-summary { display:flex; align-items:center; flex-wrap:wrap; gap:10px; padding-top:4px; }
.recent-execution-summary > span:last-child { font-size:12px; color:var(--app-text-secondary); }
.recent-execution-time { font-size:11px; font-variant-numeric:tabular-nums; }
.recent-execution-events { list-style:none; padding:0; margin:18px 0; }
.recent-execution-events li { position:relative; display:flex; gap:11px; padding:0 0 19px; }
.recent-execution-events li:not(:last-child)::after { content:''; position:absolute; left:12px; top:29px; bottom:4px; width:1px; background:var(--app-border); }
.recent-event-symbol { display:grid; place-items:center; width:26px; height:26px; flex:0 0 26px; border-radius:7px; color:var(--app-primary); background:var(--app-primary-soft); }
.recent-execution-events li[data-tone=danger] .recent-event-symbol { color:var(--app-danger); background:var(--app-danger-soft); }
.recent-execution-events li[data-tone=success] .recent-event-symbol { color:var(--app-success); background:var(--app-success-soft); }
.recent-execution-events li[data-tone=muted] .recent-event-symbol { color:var(--app-text-secondary); background:var(--app-bg); }
.recent-execution-events li > div { display:grid; gap:4px; min-width:0; padding-top:1px; }
.recent-execution-events strong { font-size:12px; font-weight:550; line-height:1.7; overflow-wrap:anywhere; }
.recent-execution-events :is(span,small):not(.recent-event-symbol) { font-size:11px; line-height:1.75; overflow-wrap:anywhere; }
.recent-execution-events li > div > :is(span,small) { color:var(--app-text-secondary); }
.recent-execution-identifiers { border-block:1px solid var(--app-border); padding:11px 0; margin-bottom:16px; font-size:12px; line-height:1.8; color:var(--app-text-secondary); }
.recent-execution-identifiers summary { cursor:pointer; width:fit-content; }
.recent-execution-identifiers dl { display:grid; gap:10px; margin:12px 0 0; }
.recent-execution-identifiers dl > div { display:grid; grid-template-columns:70px minmax(0,1fr); gap:10px; }
.recent-execution-identifiers dd { margin:0; overflow-wrap:anywhere; color:var(--app-text); }
.recent-execution-empty { display:grid; justify-items:center; gap:10px; text-align:center; padding:28px 12px; color:var(--app-text-secondary); }
.recent-execution-empty > .el-icon { color:var(--app-primary); }
.recent-execution-empty strong { font-size:13px; font-weight:550; }
.recent-execution-empty p { max-width:44ch; margin:0; font-size:12px; line-height:1.85; }
.recent-execution-link { display:flex; justify-content:space-between; align-items:center; gap:10px; color:var(--app-primary); text-decoration:none; font-size:12px; line-height:1.8; }
.recent-execution :is(summary,a):focus-visible { outline:2px solid var(--app-primary); outline-offset:4px; border-radius:3px; }
</style>
