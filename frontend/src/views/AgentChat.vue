<template><div class="agent-chat-page"><ChatAssistantDrawer full-screen /></div></template>
<script setup>
import { onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import ChatAssistantDrawer from '@/components/chat/ChatAssistantDrawer.vue'
import { useChatAssistantStore } from '@/stores/chatAssistant'
const store = useChatAssistantStore()
const route = useRoute()
let active = true
onMounted(async () => {
  try {
    await store.open()
    if (active && typeof route.query.sessionId === 'string' && route.query.sessionId !== store.sessionId) await store.switchSession(route.query.sessionId)
  } catch { if (active) ElMessage.error('会话加载失败，请重新选择会话') }
})
onBeforeUnmount(() => { active = false; store.close() })
watch(()=>route.query.sessionId,async id=>{if(active&&typeof id==='string'&&id!==store.sessionId)try{await store.switchSession(id)}catch{ElMessage.error('分支会话加载失败')}})
</script>
<style scoped>
.agent-chat-page { height: 100%; min-height: 0; }
</style>
