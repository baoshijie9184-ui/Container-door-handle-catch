<template>
  <section class="action-page">
    <header><h2><AgentSectionIcon kind="actions" />助手操作确认</h2></header>
    <div v-if="reviewSessionId" id="creation-review" ref="reviewPanel" tabindex="-1" class="creation-review-panel" aria-label="原会话检测核对">
      <DetectionCreationReview :session-id="reviewSessionId" @changed="refreshKey++" />
    </div>
    <AgentActionList standalone :refresh-key="refreshKey" />
  </section>
</template>
<script setup>
import { computed, ref, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import AgentSectionIcon from "@/components/chat/AgentSectionIcon.vue"
import AgentActionList from '@/components/chat/AgentActionList.vue'
import DetectionCreationReview from '@/components/chat/DetectionCreationReview.vue'

const route = useRoute()
const reviewSessionId = computed(() => typeof route.query.sessionId === 'string' && /^[A-Za-z0-9_.-]{1,128}$/.test(route.query.sessionId) ? route.query.sessionId : '')
const reviewPanel = ref(null)
const refreshKey = ref(0)
watch([reviewSessionId,()=>route.hash], async () => {
  if(!reviewSessionId.value || route.hash!=='#creation-review')return
  await nextTick()
  reviewPanel.value?.focus({preventScroll:true})
  reviewPanel.value?.scrollIntoView({block:'nearest'})
}, {immediate:true,flush:'post'})
</script>
<style scoped>.action-page{max-width:960px;margin:0 auto}.action-page>header{margin-bottom:20px}.action-page p{color:#68758b;font-size:14px}.creation-review-panel:focus{outline:none}.creation-review-panel:focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}</style>
