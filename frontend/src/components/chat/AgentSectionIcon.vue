<template><span class="agent-section-icon" :class="{small}" :data-tone="kind" aria-hidden="true"><el-icon><component :is="icons[kind] || icons.chat" /></el-icon></span></template>
<script setup>
import {Collection,Connection,Notebook,Setting,CircleCheck,Compass,ChatDotRound} from '@element-plus/icons-vue'
defineProps({kind:String,small:Boolean})
const icons={skills:Collection,mcp:Connection,memory:Notebook,models:Setting,actions:CircleCheck,markets:Compass,chat:ChatDotRound}
</script>
<style scoped>
.agent-section-icon{display:inline-grid;place-items:center;flex-shrink:0;width:46px;height:46px;border-radius:13px;background:var(--app-primary-soft);color:var(--app-primary);font-size:24px;box-shadow:inset 0 0 0 1px #dce7fb;vertical-align:middle}.agent-section-icon[data-tone=actions]{background:var(--app-warning-soft);color:var(--app-warning);box-shadow:inset 0 0 0 1px #f3e1b9}@media(max-width:620px){.agent-section-icon{width:38px;height:38px;border-radius:11px;font-size:21px}}
</style>
<style scoped>.agent-section-icon.small{width:28px;height:28px;font-size:17px;border-radius:8px;margin-right:8px;box-shadow:none}</style>
