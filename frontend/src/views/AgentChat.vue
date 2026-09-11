<template><div class="agent-chat-page"><div class="page-intro"><span class="eyebrow">AGENT INTELLIGENCE</span><h2>智能对话助手</h2><p>在完整工作区中与系统 Agent 对话，查询检测、设备、模型和质量数据。</p></div></div></template>
<script setup>
import { onMounted, onBeforeUnmount } from 'vue'
import { useChatAssistantStore } from '@/stores/chatAssistant'
const store = useChatAssistantStore()
onMounted(() => store.open())
onBeforeUnmount(() => store.close())
</script>
<style scoped>
.agent-chat-page{min-height:calc(100vh - 140px);padding:32px;background:linear-gradient(135deg,#f5f8ff,#fff);border:1px solid #e6ebf5;border-radius:20px}.page-intro{max-width:620px}.eyebrow{font-size:12px;letter-spacing:.16em;color:#4776d0;font-weight:700}.page-intro h2{margin:12px 0 8px;font-size:30px;color:#15233d}.page-intro p{color:#68758b}
</style>
