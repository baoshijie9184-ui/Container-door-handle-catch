<template>
  <dl class="recorded-facts">
    <div v-for="field in fields" :key="field.label">
      <dt>{{ field.label }}</dt>
      <dd><code v-if="field.identifier">{{ field.value }}</code><template v-else>{{ field.value }}</template></dd>
    </div>
  </dl>
</template>

<script setup>
// Read-only fields selected by the owning view; never inspect arbitrary DTO keys.
defineProps({ fields: { type: Array, default: () => [] } })
</script>

<style scoped>
.recorded-facts { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,210px),1fr)); gap:14px 24px; margin:0; min-width:0; }
.recorded-facts > div { min-width:0; }
.recorded-facts dt { margin:0 0 4px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.recorded-facts dd { margin:0; min-width:0; color:var(--app-text); font-size:13px; line-height:1.85; white-space:pre-wrap; overflow-wrap:anywhere; user-select:text; }
.recorded-facts code { font:12px/1.85 Consolas,"SFMono-Regular",monospace; color:inherit; white-space:pre-wrap; overflow-wrap:anywhere; }
</style>
