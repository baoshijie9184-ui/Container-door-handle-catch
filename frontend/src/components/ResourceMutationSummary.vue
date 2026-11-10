<template>
  <div class="resource-mutation-summary">
    <strong>{{ latest ? historyActorName(latest) : '修改人未核实' }}</strong>
    <small v-if="latest?.source?.type==='SYSTEM'">{{ historyActorRole(latest) }} · 原发起人 {{ historyInitiator(latest) }}</small>
    <time>{{ latest?.occurredAt ? auditTime(latest.occurredAt) : '修改时间未记录' }}</time>
    <small>资料版本 {{ revision ?? '未知' }}<span v-if="latest?.afterVersion != null && revision != null && latest.afterVersion !== String(revision)"> · 最近变更 {{ latest.afterVersion }}</span></small>
    <router-link :to="resourceHistoryLink(resourceType, resourceId, domain)">查看修改记录</router-link>
  </div>
</template>
<script setup>
import { historyActorName, historyActorRole, historyInitiator, resourceHistoryLink } from '../utils/changeHistory'
import { auditTime } from '../utils/auditPresentation'
defineProps({ latest: Object, revision: [String, Number], resourceType: String, resourceId: [String, Number], domain: String })
</script>
<style scoped>
.resource-mutation-summary{display:flex;flex-direction:column;gap:4px;font-size:12px;line-height:1.6}.resource-mutation-summary strong{font-weight:500}.resource-mutation-summary time,.resource-mutation-summary small{font-size:12px;color:var(--app-text-secondary)}.resource-mutation-summary a{width:fit-content;color:var(--app-primary);text-decoration:none;transition:color .15s ease}.resource-mutation-summary a:hover{text-decoration:underline}.resource-mutation-summary a:focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}@media(prefers-reduced-motion:reduce){.resource-mutation-summary a{transition:none}}
</style>
