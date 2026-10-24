<template><section class="action-page"><header><div><h2><AgentSectionIcon kind="actions" />助手操作确认</h2><p>核对任务、参数和操作影响后再确认，决策与实际结果可通过审计查看</p></div></header><AgentActionList standalone /></section></template>
<script setup>
import AgentSectionIcon from "@/components/chat/AgentSectionIcon.vue"
import AgentActionList from '@/components/chat/AgentActionList.vue'
</script>
<style scoped>.action-page{max-width:960px;margin:0 auto}.action-page>header{margin-bottom:20px}.action-page p{color:#68758b;font-size:14px}</style>
