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
.ui-page-heading { display:flex; flex-flow:row wrap; align-items:flex-start; gap:13px; width:100%; min-width:0; padding:0 0 24px; border:0; border-bottom:1px solid var(--app-border); border-radius:0; background:transparent; box-shadow:none; overflow:visible; }
.ui-page-symbol { display:grid; place-items:center; flex:0 0 34px; width:34px; height:34px; margin-top:1px; border:1px solid var(--app-border); border-radius:8px; color:var(--app-text-secondary); background:white; }
.ui-page-symbol :deep(svg) { width:19px; height:19px; }
.ui-page-heading > :deep(div:first-of-type) { flex:1 1 260px; min-width:0; }
.ui-page-heading :deep(.page-hero-title) { margin:0; font-size:var(--app-font-title); font-weight:650; line-height:1.35; letter-spacing:-.035em; color:var(--app-text); }
.ui-page-heading :deep(.page-hero-label),.ui-page-heading :deep(.industrial-kicker) { display:none; }
.ui-page-heading :deep(.page-hero-text) { max-width:76ch; margin:8px 0 0; font-size:13px; line-height:1.85; color:var(--app-text-secondary); }
.ui-page-heading > :deep(.panel-actions) { flex:0 1 auto; display:flex; flex-wrap:wrap; justify-content:flex-end; align-items:center; gap:8px; padding-top:1px; }
.ui-page-heading :deep(.panel-actions .el-button + .el-button) { margin-left:0; }
.ui-page-heading :deep(.hero-side-note) { display:grid; gap:5px; flex:0 1 260px; max-width:260px; padding:12px 15px; border:1px solid var(--app-border); border-radius:8px; background:var(--app-surface); font-size:12px; line-height:1.8; color:var(--app-text-secondary); }
.ui-page-heading :deep(.hero-side-note strong) { display:flex; align-items:center; gap:6px; color:var(--app-text); font-size:12px; font-weight:550; }
.ui-page-heading :deep(.hero-side-note strong > .el-icon) { flex:none; color:var(--app-primary); }
@media(max-width:700px) {
  .ui-page-heading { gap:11px; padding-bottom:20px; }
  .ui-page-heading :deep(.page-hero-title) { font-size:23px; }
  .ui-page-heading > :deep(div:first-of-type) { flex-basis:calc(100% - 48px); }
  .ui-page-heading > :deep(.panel-actions),.ui-page-heading > :deep(.hero-side-note) { flex-basis:100%; max-width:100%; justify-content:flex-start; margin-left:0; }
}
</style>
