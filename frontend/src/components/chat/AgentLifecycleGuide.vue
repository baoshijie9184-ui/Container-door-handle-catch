<template>
  <ol class="agent-lifecycle-guide" :aria-label="label">
    <li v-for="(step, index) in steps" :key="step.title"><span class="agent-step-order">{{ index + 1 }}</span><div><strong>{{ step.title }}</strong><p>{{ step.description }}</p></div></li>
  </ol>
</template>
<script setup>
defineProps({ label: { type: String, default: '操作流程说明' }, steps: { type: Array, default: () => [] } })
</script>
<style scoped>
.agent-lifecycle-guide { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); list-style: none; margin: 18px 0 22px; padding: 0; background: #f8fafc; border: 1px solid var(--app-border); border-radius: 10px; overflow: hidden; }
.agent-lifecycle-guide li { display: flex; gap: 10px; padding: 16px 14px; min-width: 0; }
.agent-lifecycle-guide li + li { border-left: 1px solid var(--app-border); }
.agent-step-order { display: grid; place-items: center; flex: 0 0 24px; height: 24px; border-radius: 7px; font-size: 12px; font-weight: 650; color: var(--app-primary); background: #e8f0ff; }
.agent-lifecycle-guide strong { display: block; font-size: 13px; line-height: 1.8; color: var(--app-text); font-weight: 650; }
.agent-lifecycle-guide p { margin: 5px 0 0; font-size: 11px; line-height: 1.8; color: var(--app-text-secondary); overflow-wrap: anywhere; }
@media(max-width: 1100px) { .agent-lifecycle-guide { grid-template-columns: repeat(2, minmax(0, 1fr)); }.agent-lifecycle-guide li:nth-child(3) { border-left: 0; }.agent-lifecycle-guide li:nth-child(n+3) { border-top: 1px solid var(--app-border); } }
@media(max-width: 640px) { .agent-lifecycle-guide { grid-template-columns: minmax(0, 1fr); }.agent-lifecycle-guide li + li { border-left: 0; border-top: 1px solid var(--app-border); } }
</style>
