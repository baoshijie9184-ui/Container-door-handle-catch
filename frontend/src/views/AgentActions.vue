<template>
  <section class="action-page">
    <header><h2><AgentSectionIcon kind="actions" />助手操作确认</h2></header>
    <DetectionCreationReview v-if="reviewSessionId" :session-id="reviewSessionId" @changed="refreshKey++" />
    <AgentActionList standalone :refresh-key="refreshKey" />
  </section>
</template>
<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import AgentSectionIcon from "@/components/chat/AgentSectionIcon.vue"
import AgentActionList from '@/components/chat/AgentActionList.vue'
import DetectionCreationReview from '@/components/chat/DetectionCreationReview.vue'

const route = useRoute()
const reviewSessionId = computed(() => typeof route.query.sessionId === 'string' ? route.query.sessionId : '')
const refreshKey = ref(0)
</script>
<style scoped>.action-page{max-width:960px;margin:0 auto}.action-page>header{margin-bottom:20px}.action-page p{color:#68758b;font-size:14px}</style>
