<template>
  <section class="page-hero ui-page-heading">
    <span class="ui-page-symbol"><AppIcon :name="icon || presentation.icon" :size="24" /></span>
    <slot>
      <div class="ui-page-copy"><h1 class="page-hero-title">{{ title || presentation.title }}</h1><p v-if="description" class="page-hero-text">{{ description }}</p></div>
    </slot>
    <div v-if="$slots.actions" class="panel-actions"><slot name="actions" /></div>
  </section>
</template>
<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from './AppIcon.vue'
import { pagePresentation } from '../utils/pagePresentation'
defineProps({ title: String, description: String, icon: String })
const route = useRoute()
const presentation = computed(() => pagePresentation(route))
</script>
<style scoped>
.ui-page-heading { display:flex; flex-flow:row nowrap; align-items:flex-start; gap:16px; width:100%; max-width:100%; min-width:0; box-sizing:border-box; padding:8px 0 20px; border:0; border-bottom:1px solid var(--app-border); border-radius:0; box-shadow:none; background:transparent; overflow:visible; }
.ui-page-symbol { display: grid; place-items: center; width: 48px; height: 48px; flex: 0 0 48px; border: 1px solid #dce7fb; border-radius: 13px; background: var(--app-primary-soft); color: var(--app-primary); }
.ui-page-heading > :deep(div:first-of-type) { flex: 1; min-width: 0; }
.ui-page-heading :deep(.page-hero-title) { font-size: clamp(22px, 2.1vw, 28px); line-height: 1.3; font-weight: 700; letter-spacing: -.025em; }
.ui-page-heading :deep(.page-hero-label), .ui-page-heading :deep(.industrial-kicker) { display: none; }
.ui-page-heading :deep(.page-hero-text) { max-width: 76ch; font-size: 13px; margin-top: 8px; line-height: 1.8; }
.ui-page-heading > :deep(.panel-actions) { flex: 0 1 auto; }
.ui-page-heading :deep(.hero-side-note) { display:grid; align-content:start; gap:6px; flex:0 1 245px; min-width:0; max-width:245px; box-sizing:border-box; padding:12px 16px; border:0; border-radius:10px; background:var(--app-primary-soft); color:var(--app-text); box-shadow:none; overflow-wrap:anywhere; }
.ui-page-heading :deep(.hero-side-note strong) { display:flex; align-items:flex-start; gap:7px; margin:0; color:var(--app-text); font-size:13px; font-weight:600; line-height:1.8; }
.ui-page-heading :deep(.hero-side-note strong > .el-icon) { flex:none; margin-top:3px; color:var(--app-primary); }
.ui-page-heading :deep(.hero-side-note > span) { color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
@media(max-width: 700px) {
  .ui-page-heading { flex-wrap: wrap; gap: 12px; padding-bottom: 16px; }
  .ui-page-symbol { width: 40px; height: 40px; flex-basis: 40px; }
  .ui-page-heading > :deep(div:first-of-type) { flex-basis: calc(100% - 56px); }
  .ui-page-heading > :deep(.panel-actions), .ui-page-heading > :deep(.hero-side-note) { margin-left: 52px; max-width: calc(100% - 52px); }
}
</style>
