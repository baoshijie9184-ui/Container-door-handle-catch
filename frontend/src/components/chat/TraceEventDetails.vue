<template>
  <div class="record-details trace-event-record">
    <section v-for="group in groups" :key="group.id" class="record-details-group" :aria-label="group.label">
      <h4 class="record-details-heading"><AppIcon :name="group.icon" :size="15" />{{ group.label }}</h4>
      <RecordedFactList :fields="group.fields" />
    </section>
    <details class="record-details-identifiers">
      <summary><AppIcon name="DocumentCopy" :size="15" /><span>核对调用编号与内容摘要</span><AppIcon class="record-details-chevron" name="ArrowDown" :size="13" /></summary>
      <RecordedFactList :fields="identifiers" />
    </details>
    <p class="record-details-note">以上仅为本事件登记的字段，缺失耗时和用量不按零计算；不从当前配置补造历史信息。</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import RecordedFactList from '@/components/RecordedFactList.vue'
import { eventCategory, traceTime, traceDuration, modelFailureLabel } from '@/utils/agentTrace'
import '@/assets/record-details.css'

const props = defineProps({ event: { type: Object, required: true } })
const recorded = value => value != null && value !== ''
const field = (label, value, identifier = false) => ({ label, value: recorded(value) ? value : '未记录', identifier })
const optional = entries => entries.filter(([, value]) => recorded(value)).map(([label, value]) => field(label, value))

const groups = computed(() => {
  // Preserve the existing inspector's explicit metadata allowlist. No prompt,
  // tool argument/body, credential or arbitrary payload enumeration is added.
  const event = props.event, p = event.payload || {}
  const hasModel = eventCategory(event.type) === 'MODEL' || [p.inputTokens, p.outputTokens, p.provider, p.modelId, p.model, p.attempt, p.firstContentMs, p.failureReason, p.httpStatus, p.nextModelId, p.modelRequestId].some(recorded)
  return [
    { id:'execution', label:'执行位置与耗时', icon:'Connection', fields:[
      field('事件类型', event.type), field('Agent', p.agent), field('工具', p.tool),
      field('记录时间 · UTC+8', traceTime(event.occurredAt)), field('运行后时间', traceDuration(p.elapsedMs)),
      field('此事件记录耗时', traceDuration(p.durationMs)), ...optional([['结果', p.result]])
    ] },
    { id:'model', label:'模型与用量记录', icon:'Cpu', fields:hasModel ? [
      field('输入 Token', p.inputTokens), field('输出 Token', p.outputTokens),
      ...optional([
        ['供应商接入标识', p.provider], ['候选模型 ID', p.modelId], ['请求模型名', p.model], ['候选序号', p.attempt],
        ['首段内容耗时', p.firstContentMs == null ? null : traceDuration(p.firstContentMs)],
        ['失败原因', p.failureReason ? modelFailureLabel(p.failureReason) : null], ['HTTP 状态', p.httpStatus], ['下一备用候选', p.nextModelId]
      ])
    ] : [] },
    { id:'authorization', label:'权限与策略记录', icon:'Key', fields:optional([
      ['角色决策', p.decision], ['数据范围', p.scope], ['策略版本', p.policyVersion]
    ]) },
    { id:'skill', label:'技能与命令记录', icon:'Operation', fields:optional([
      ['技能', p.skillId], ['技能版本', p.version], ['命令', p.command]
    ]) },
    { id:'context', label:'上下文压缩记录', icon:'Collection', fields:optional([
      ['请求用途', p.purpose === 'CONTEXT_COMPACTION' ? '上下文摘要' : null],
      ['压缩前消息数', p.beforeMessages], ['压缩后消息数', p.afterMessages], ['压缩前字符数', p.beforeChars], ['压缩后字符数', p.afterChars]
    ]) }
  ].filter(group => group.fields.length)
})

const identifiers = computed(() => {
  const p = props.event.payload || {}
  return [field('调用编号', p.callId, true), field('父调用编号', p.parentCallId, true),
    ...[['模型请求编号', p.modelRequestId], ['内容摘要 SHA256', p.sha256]]
      .filter(([, value]) => recorded(value)).map(([label, value]) => field(label, value, true))]
})
</script>
