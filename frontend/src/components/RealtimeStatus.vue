<template><div class="collaboration-status" role="status" aria-live="polite"><AppIcon :name="connection==='connected'?'Connection':'Refresh'" :size="15" /><span>{{ label }}</span><button v-if="connection!=='connected'" type="button" @click="verify">重新核对</button></div></template>
<script setup>
import { computed } from 'vue'
import { useResourceChanges, realtimeHub } from '../composables/useResourceChanges'
import { useUserStore } from '../stores/user'
const { connection } = useResourceChanges()
const label = computed(() => ({ connected:'修改通知已连接', connecting:'正在连接修改通知', reconnecting:'修改通知中断，正在重连；页面仍会定期核对', unavailable:'修改通知暂不可用，仍每30秒核对页面', polling:'当前使用定期核对 每30秒刷新可见页面', closed:'修改通知未连接' })[connection.value])
const verify = () => useUserStore().checkAuth().then(() => { realtimeHub().retry(); window.dispatchEvent(new Event('focus')) })
</script>
<style scoped>.collaboration-status{display:flex;align-items:center;flex-wrap:wrap;gap:7px;color:var(--app-text-secondary);font-size:12px;line-height:1.7}.collaboration-status button{border:0;background:transparent;color:var(--app-primary);font:inherit;cursor:pointer}.collaboration-status button:focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}</style>
