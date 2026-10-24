<template>
  <details class="config-diff">
    <summary><AppIcon name="DocumentCopy" :size="16" /><span>{{ title }}（{{ changes.length }} 项）</span><AppIcon name="ArrowRight" :size="12" class="config-diff-chevron" /></summary>
    <p class="config-diff-scope">仅比较模型策略；凭证值不在此展示。登记启停与超时配置不代表供应商实时可用性。</p>
    <p v-if="!changes.length" class="config-diff-empty">模型策略未变化</p>
    <dl v-else class="config-changes">
      <template v-for="change in changes" :key="change.field">
        <dt>{{ change.label }}</dt>
        <dd>
          <div><h4>当前生效值</h4><ModelConfigValue :field="change.field" :value="change.before" :label="change.label+'当前生效值'" /></div>
          <div><h4>{{ nextLabel }}</h4><ModelConfigValue :field="change.field" :value="change.after" :label="change.label+nextLabel" /></div>
        </dd>
      </template>
    </dl>
    <slot />
  </details>
</template>

<script setup>
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import ModelConfigValue from './ModelConfigValue.vue'
import { modelConfigChanges } from '@/utils/modelConfigPresentation'
const props = defineProps({
  before: { type: Object, default: () => ({}) },
  after: { type: Object, default: () => ({}) },
  title: { type: String, default: '查看相对生效版本的配置变更' },
  nextLabel: { type: String, default: '当前查看版本' }
})
const changes = computed(() => modelConfigChanges(props.before,props.after))
</script>
<style scoped>
.config-diff{padding:16px 0;margin:18px 0;border:0;border-top:1px solid var(--app-border);border-radius:0;font-size:13px;background:transparent}
.config-diff>summary{display:flex;align-items:center;gap:7px;width:fit-content;max-width:100%;cursor:pointer;color:var(--app-text-secondary);font-size:13px;line-height:1.85;list-style:none;border-radius:3px;transition:color 180ms ease}
.config-diff>summary::-webkit-details-marker{display:none}
.config-diff>summary>.el-icon{flex:none;color:var(--app-primary)}
.config-diff>summary>span:not(.el-icon){min-width:0;overflow-wrap:anywhere}
.config-diff-chevron{transition:transform 180ms ease}
.config-diff[open]>summary .config-diff-chevron{transform:rotate(90deg)}
.config-diff>summary:hover{color:var(--app-primary)}
.config-diff :is(.config-diff-scope,.config-diff-empty){font-size:12px;line-height:1.85;color:var(--app-text-secondary);margin:12px 0}
.config-changes{margin:18px 0 0}
.config-changes>dt{font-weight:600;color:var(--app-text);font-size:13px;line-height:1.85}
.config-changes>dd{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 24px;margin:9px 0 20px;padding-bottom:20px;border-bottom:1px solid var(--app-border)}
.config-changes>dd:last-child{border-bottom:0;margin-bottom:0;padding-bottom:0}
.config-changes>dd>div{min-width:0}
.config-changes h4{font-weight:400;color:var(--app-text-secondary);font-size:12px;line-height:1.85;margin:0 0 8px}
.config-diff>summary:focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}
.config-diff :slotted(p){font-size:12px;color:var(--app-text-secondary);line-height:1.85;margin:12px 0}
@media(max-width:700px){.config-changes>dd{grid-template-columns:1fr}}
@media(prefers-reduced-motion:reduce){.config-diff>summary,.config-diff-chevron{transition:none}}
</style>
