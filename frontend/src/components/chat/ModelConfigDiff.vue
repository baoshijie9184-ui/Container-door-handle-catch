<template>
  <details class="config-diff">
    <summary>{{ title }}（{{ changes.length }} 项）</summary>
    <p v-if="!changes.length">模型策略未变化</p>
    <dl v-else>
      <template v-for="change in changes" :key="change.field">
        <dt>{{ change.label }}</dt>
        <dd>
          <div><span>当前生效值</span><pre tabindex="0" :aria-label="change.label+'当前生效值'">{{ change.before }}</pre></div>
          <div><span>{{ nextLabel }}</span><pre tabindex="0" :aria-label="change.label+nextLabel">{{ change.after }}</pre></div>
        </dd>
      </template>
    </dl>
    <slot />
  </details>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({
  before: { type: Object, default: () => ({}) },
  after: { type: Object, default: () => ({}) },
  title: { type: String, default: '查看相对生效版本的配置变更' },
  nextLabel: { type: String, default: '当前查看版本' }
})
// Deliberate display allowlist: never diff credential objects or replacement keys.
const labels = { models:'模型列表', defaultModel:'默认模型', memoryModel:'记忆提炼模型', fallbackModels:'备用模型顺序', timeoutMs:'总超时（毫秒）', firstTokenTimeoutMs:'首响应超时（毫秒）', maxOutputTokens:'最大输出 Token', fallbackEnabled:'备用切换' }
const format = value => value == null ? '未记录' : typeof value === 'boolean' ? value ? '启用' : '停用' : typeof value === 'string' ? value : JSON.stringify(value,null,2)
const changes = computed(() => Object.entries(labels)
  .filter(([field]) => JSON.stringify(props.before?.[field]) !== JSON.stringify(props.after?.[field]))
  .map(([field,label]) => ({field,label,before:format(props.before?.[field]),after:format(props.after?.[field])})))
</script>
