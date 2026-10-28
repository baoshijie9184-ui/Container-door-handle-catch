<template><span class="agent-section-icon" :class="{small}" :data-tone="kind" aria-hidden="true"><el-icon><component :is="icons[kind] || icons.chat" /></el-icon></span></template>
<script setup>
import {Collection,Connection,Notebook,Setting,CircleCheck,Compass,ChatDotRound} from '@element-plus/icons-vue'
defineProps({kind:String,small:Boolean})
const icons={skills:Collection,mcp:Connection,memory:Notebook,models:Setting,actions:CircleCheck,markets:Compass,chat:ChatDotRound}
</script>
<style scoped>
.agent-section-icon { display:inline-grid; place-items:center; flex-shrink:0; width:34px; height:34px; border:1px solid var(--app-border); border-radius:8px; background:var(--app-surface); color:var(--app-text-secondary); font-size:19px; vertical-align:middle; }
.agent-section-icon.small { width:26px; height:26px; margin-right:8px; border:0; border-radius:6px; background:var(--app-surface-muted); font-size:16px; }
</style>
