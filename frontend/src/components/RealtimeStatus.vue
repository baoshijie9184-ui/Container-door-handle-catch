<template><div class="collaboration-status" role="status" aria-live="polite"><AppIcon :name="connection==='connected'?'Connection':'Refresh'" :size="15" /><span>{{ label }}</span><button v-if="connection!=='connected'" type="button" @click="verify">重新连接</button></div></template>
<script setup>
import { computed } from 'vue'
import { useResourceChanges, realtimeHub } from '../composables/useResourceChanges'
import { useUserStore } from '../stores/user'
const { connection } = useResourceChanges()
const label = computed(() => ({ connected:'实时同步', connecting:'正在连接', reconnecting:'连接中断，正在重连', unavailable:'实时通知不可用，每 30 秒刷新', polling:'每 30 秒刷新', closed:'实时通知未连接' })[connection.value])
const verify = () => useUserStore().checkAuth().then(() => { realtimeHub().retry(); window.dispatchEvent(new Event('focus')) })
</script>
<style scoped>.collaboration-status{display:flex;align-items:center;flex-wrap:wrap;gap:7px;color:var(--app-text-secondary);font-size:12px;line-height:1.7}.collaboration-status button{border:0;background:transparent;color:var(--app-primary);font:inherit;cursor:pointer}.collaboration-status button:focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}</style>
