<template>
  <nav class="inspection-flow" aria-label="检测业务流程">
    <h2 v-if="overview">{{ user.role==='SUPERVISOR' ? '检测业务流程' : '我的工作入口' }}</h2>
    <div class="flow-steps">
      <router-link v-for="item in steps" :key="item.key" :to="actionLocation(item)" custom v-slot="{href,navigate}">
        <a :href="href" :aria-current="current===item.key ? 'step' : undefined" @click="navigate">
          <span class="step-icon"><AppIcon :name="item.icon" :size="19" /></span>
          <strong>{{ item.label }}</strong>
          <span v-if="overview && user.role!=='SUPERVISOR' && ['detection','verification'].includes(item.key)" class="step-count" :class="{pending:counts[item.key]>0}">{{ counts[item.key] ?? '—' }}</span>
          <AppIcon v-if="user.role==='SUPERVISOR' && item.key!=='verification'" name="ArrowRight" :size="14" class="step-arrow" />
        </a>
      </router-link>
    </div>
  </nav>
</template>
<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { actionLocation, inspectionActions } from '@/utils/workspaceActions'
defineProps({overview:Boolean,counts:{type:Object,default:()=>({})}})
const route=useRoute(), user=useUserStore()
const steps=computed(()=>inspectionActions(user.role==='SUPERVISOR'))
const current=computed(()=>{
  if (route.meta.uploadScope) return route.meta.awaitingDispatch || user.role!=='SUPERVISOR' ? 'records' : null
  if (route.path==='/upload') return 'upload'
  if (route.meta.taskList) return route.meta.taskList
  if (route.path==='/inspection/tasks' && route.query.inbox==='1') return route.query.kind
  return null
})
</script>
<style scoped>
.inspection-flow { min-width:0;padding:14px 16px;background:var(--app-surface,#fff);border:1px solid var(--app-border);border-radius:var(--app-radius-lg,10px) }
.inspection-flow h2 { margin:0 0 12px;font-size:15px;font-weight:650;color:var(--app-text) }
.flow-steps { display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px }
.flow-steps a { min-width:0;display:flex;align-items:center;gap:9px;padding:8px 10px;color:var(--app-text);border-radius:7px;text-decoration:none }
.flow-steps strong { font-size:14px;line-height:1.45;font-weight:600 }.step-icon { flex:none;display:grid;place-items:center;width:32px;height:32px;background:var(--app-primary-soft);color:var(--app-primary);border-radius:8px }
.step-arrow { margin-left:auto;flex:none;color:var(--app-text-muted) }.flow-steps a:hover { background:var(--app-surface-muted);color:var(--app-primary) }.flow-steps a[aria-current=step] { background:var(--app-primary-soft);color:var(--app-primary) }.flow-steps a[aria-current=step] .step-icon { background:var(--app-primary);color:white }
.step-count { font-size:12px;color:var(--app-text-secondary);font-variant-numeric:tabular-nums }.step-count.pending { color:var(--app-primary);font-weight:700 }.flow-steps a:focus-visible { outline:2px solid var(--app-primary);outline-offset:1px }
@media(max-width:1100px){.flow-steps { grid-template-columns:repeat(2,minmax(0,1fr)) }}
@media(max-width:580px){.inspection-flow{padding:9px}.flow-steps{gap:3px}.flow-steps a{gap:6px;padding:5px}.step-arrow{display:none}}
</style>
