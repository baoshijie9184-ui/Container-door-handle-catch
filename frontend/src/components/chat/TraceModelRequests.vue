<template>
  <section class="model-route-records" aria-label="已加载模型路由记录">
    <div class="model-route-toolbar"><el-input v-model="query" clearable placeholder="搜索已加载的模型、接入或请求编号" aria-label="搜索已加载的模型路由记录"/><span>显示 {{ visible.length.toLocaleString('zh-CN') }} / {{ requests.length.toLocaleString('zh-CN') }} 组请求</span></div>
    <p v-if="loading" class="model-route-read-note" role="status">正在补读事件，当前保留已加载的请求记录。</p>
    <article v-for="request in visible" :key="request.key" class="model-route-request">
      <header class="model-route-request-heading"><span class="model-route-symbol"><AppIcon name="Cpu" :size="19" /></span><div><h5>{{ request.agent || 'Agent 未记录' }}</h5><p>{{ request.purpose === 'CONTEXT_COMPACTION' ? '上下文摘要请求' : '模型逻辑请求' }} · {{ request.attempts.length.toLocaleString('zh-CN') }} 条候选记录</p></div></header>
      <p class="model-route-id">请求编号 <code>{{ request.requestId }}</code></p>
      <section v-for="attempt in request.attempts" :key="attempt.key" class="model-route-attempt" :data-status="attempt.status" aria-label="模型候选记录">
        <header><div><span class="model-route-attempt-number">候选 {{ attempt.attempt }}</span><strong>{{ attempt.modelId || '候选编号未记录' }}</strong></div><StatusBadge domain="traceExecution" :code="attempt.status" :label="traceStatus(attempt.status)" /></header>
        <dl><div><dt>供应商接入</dt><dd>{{ attempt.provider || '未记录' }}</dd></div><div><dt>请求模型名</dt><dd>{{ attempt.model || '未记录' }}</dd></div><template v-if="attempt.status !== 'SKIPPED'"><div><dt>模型耗时</dt><dd>{{ traceDuration(attempt.durationMs) }}</dd></div><div><dt>首段内容耗时</dt><dd>{{ traceDuration(attempt.firstContentMs) }}</dd></div></template></dl>
        <p v-if="attempt.failureReason" class="model-route-failure">{{ modelFailureLabel(attempt.failureReason) }}<span v-if="attempt.httpStatus != null"> · HTTP {{ attempt.httpStatus }}</span></p>
        <p v-if="attempt.status === 'SKIPPED'" class="model-route-note">此候选已跳过，不把跳过记录当作一次已完成的模型请求。</p>
        <button type="button" class="model-route-event-link" :disabled="!attempt.firstEvent" :aria-label="`查看候选 ${attempt.attempt} ${attempt.modelId || ''} 的事件记录`" @click="$emit('inspect', attempt.firstEvent)">查看候选事件<AppIcon name="ArrowRight" :size="14" /></button>
      </section>
      <p v-if="!request.attempts.length" class="model-route-note">此逻辑请求尚无候选记录，可能尚未补读到对应事件。</p>
      <div v-for="event in fallbacks(request)" :key="event.sequence" class="model-route-fallback"><AppIcon name="Refresh" :size="16" /><div><strong>已记录备用选择</strong><p><code>{{ event.payload.modelId || '原候选未记录' }}</code><AppIcon name="ArrowRight" :size="13" /><code>{{ event.payload.nextModelId || '备用候选未记录' }}</code></p><p>{{ modelFailureLabel(event.payload.failureReason) }}</p><button type="button" class="model-route-event-link" @click="$emit('inspect', event)">查看切换事件<AppIcon name="ArrowRight" :size="14" /></button></div></div>
    </article>
    <CollectionEmptyState v-if="!visible.length" :filtered="!!query.trim()" :loading="loading" empty-title="当前没有可展示的模型请求" empty-description="这里只搜索已加载的调用记录，不查询供应商或补造历史模型。" @reset="query = ''" />
  </section>
</template>
<script setup>
import { computed, ref } from 'vue'
import CollectionEmptyState from '@/components/CollectionEmptyState.vue'
import { traceStatus, traceDuration, modelFailureLabel } from '@/utils/agentTrace'
const props = defineProps({ requests: { type: Array, default: () => [] }, loading: Boolean })
defineEmits(['inspect'])
const query = ref('')
const visible = computed(() => {
  const needle = query.value.trim().toLowerCase()
  return props.requests.filter(request => !needle || [request.requestId, request.agent, request.purpose === 'CONTEXT_COMPACTION' ? '上下文摘要' : '', ...request.attempts.flatMap(attempt => [attempt.modelId, attempt.provider, attempt.model, traceStatus(attempt.status), modelFailureLabel(attempt.failureReason)])].join(' ').toLowerCase().includes(needle))
})
const fallbacks = request => request.events.filter(event => event.type === 'MODEL_FALLBACK_SELECTED')
</script>
<style scoped>
.model-route-records { min-width: 0; margin-top: 18px; }
.model-route-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
.model-route-toolbar .el-input { flex: 1 1 260px; }
.model-route-toolbar > span { font-size: 12px; color: var(--app-text-secondary, #475569); }
.model-route-read-note, .model-route-note { color: var(--app-text-secondary, #475569); font-size: 12px; line-height: 1.85; overflow-wrap: anywhere; }
.model-route-read-note { margin: 12px 0; padding: 10px 12px; background: var(--app-primary-soft, #eff6ff); border-radius: 7px; }
.model-route-request { margin: 20px 0 0; padding: 18px 0 0; border: 0; border-top: 1px solid var(--app-border, #e2e8f0); background: #fff; min-width: 0; }
.model-route-request-heading { display: flex; align-items: flex-start; gap: 10px; }
.model-route-symbol { display: grid; place-items: center; flex: 0 0 34px; width: 34px; height: 34px; border-radius: 8px; background: var(--app-primary-soft, #eff6ff); color: var(--app-primary, #2563eb); }
.model-route-request-heading > div { min-width: 0; }
.model-route-request-heading h5 { font-size: 14px; font-weight: 600; line-height: 1.7; margin: 0; color: var(--app-text, #0f172a); overflow-wrap: anywhere; }
.model-route-request-heading p, .model-route-id { margin: 4px 0 0; font-size: 12px; line-height: 1.8; color: var(--app-text-secondary, #475569); overflow-wrap: anywhere; }
.model-route-id { margin: 12px 0; }
.model-route-id code, .model-route-fallback code { font-size: 12px; white-space: normal; overflow-wrap: anywhere; }
.model-route-attempt { padding: 14px 0 14px 14px; margin-top: 12px; border-left: 2px solid var(--app-border, #e2e8f0); min-width: 0; }
.model-route-attempt[data-status="ERROR"] { border-color: #f1a5ab; }
.model-route-attempt[data-status="SUCCESS"] { border-color: #86cda3; }
.model-route-attempt > header { display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 8px 12px; }
.model-route-attempt > header > div { min-width: 0; flex: 1 1 150px; }
.model-route-attempt-number { display: block; margin-bottom: 3px; font-size: 12px; color: var(--app-text-secondary, #475569); }
.model-route-attempt strong { font-size: 13px; font-weight: 600; line-height: 1.8; color: var(--app-text, #0f172a); overflow-wrap: anywhere; }
.model-route-attempt dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 18px; margin: 14px 0; }
.model-route-attempt dl > div { min-width: 0; }
.model-route-attempt dt { font-size: 12px; line-height: 1.8; color: var(--app-text-secondary, #475569); }
.model-route-attempt dd { margin: 3px 0 0; color: var(--app-text, #0f172a); font-size: 13px; line-height: 1.8; overflow-wrap: anywhere; }
.model-route-failure { color: #b91c1c; font-size: 12px; line-height: 1.85; overflow-wrap: anywhere; }
.model-route-attempt[data-status="SKIPPED"] .model-route-failure { color: var(--app-text-secondary, #475569); }
.model-route-event-link { display: inline-flex; align-items: center; gap: 6px; min-height: 30px; padding: 3px 0; border: 0; border-radius: 3px; background: transparent; color: var(--app-primary, #2563eb); font: inherit; font-size: 12px; cursor: pointer; text-align: left; transition: color 180ms ease; }
.model-route-event-link:hover:not(:disabled) { color: #1d4ed8; text-decoration: underline; text-underline-offset: 3px; }
.model-route-event-link:disabled { color: var(--app-text-secondary, #475569); cursor: not-allowed; }
.model-route-fallback { display: flex; align-items: flex-start; gap: 9px; margin: 12px 0; padding: 12px 14px; background: var(--app-primary-soft, #eff6ff); border-radius: 8px; }
.model-route-fallback > .el-icon { color: var(--app-primary, #2563eb); flex-shrink: 0; margin-top: 4px; }
.model-route-fallback > div { min-width: 0; }
.model-route-fallback strong { color: var(--app-text, #0f172a); font-size: 12px; font-weight: 550; }
.model-route-fallback p { display: flex; align-items: center; flex-wrap: wrap; gap: 5px; margin: 5px 0; color: var(--app-text-secondary, #475569); font-size: 12px; line-height: 1.8; overflow-wrap: anywhere; }
.model-route-records :is(button, summary):focus-visible { outline: 2px solid var(--app-primary, #2563eb); outline-offset: 3px; }
@media (max-width: 480px) { .model-route-attempt { padding-left: 10px; } .model-route-attempt dl { grid-template-columns: minmax(0, 1fr); gap: 10px; } .model-route-event-link { min-height: 36px; } }
@media (prefers-reduced-motion: reduce) { .model-route-event-link { transition: none; } }
</style>
