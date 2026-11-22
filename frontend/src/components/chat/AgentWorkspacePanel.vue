<template>
  <aside class="workspace-context" aria-label="Agent 工作面板">
    <header class="context-heading">
      <h3>任务与资料</h3>
      <button type="button" aria-label="关闭工作面板" @click="$emit('close')"><el-icon><Close /></el-icon></button>
    </header>
    <div class="context-content">
      <AgentWorkbenchPanel :session-id="sessionId" :messages="messages" :task-attention="taskAttention" :active="active" @reference="$emit('reference',$event)" @pending-review="$emit('pending-review',$event)" />
      <details class="context-details" @toggle="toggleDetails">
        <summary>最近执行</summary>
        <AgentRecentExecution v-if="detailsOpen" :session-id="sessionId" :trace="trace" :loaded="traceLoaded" :error="traceError" :loading="loading" @refresh="$emit('refresh')" />
      </details>
    </div>
  </aside>
</template>

<script setup>
import { ref } from 'vue'
import { Close } from '@element-plus/icons-vue'
import AgentWorkbenchPanel from './AgentWorkbenchPanel.vue'
import AgentRecentExecution from './AgentRecentExecution.vue'

const props=defineProps({sessionId:String,taskAttention:String,active:Boolean,trace:Object,traceLoaded:Boolean,traceError:String,loading:Boolean,messages:{type:Array,default:()=>[]}})
const emit=defineEmits(['close','refresh','reference','pending-review'])
const detailsOpen=ref(false)
function toggleDetails(event){
  detailsOpen.value=event.currentTarget.open
  if(detailsOpen.value&&props.sessionId&&!props.traceLoaded&&!props.loading)emit('refresh')
}
</script>

<style scoped>
.workspace-context { height:100%; min-height:0; display:flex; flex-direction:column; background:var(--app-bg); border-left:1px solid var(--app-border); color:var(--app-text); }
.context-heading { display:flex; justify-content:space-between; align-items:center; gap:12px; padding:14px 16px 8px; }
.context-heading h3 { font-size:15px; margin:0; font-weight:650; }
.context-heading button { display:grid; place-items:center; border:0; background:transparent; cursor:pointer; color:var(--app-text-secondary); width:36px; height:36px; flex:0 0 36px; border-radius:7px; }
.context-heading button:hover { background:var(--app-primary-soft); color:var(--app-primary); }
.context-content { flex:1; overflow:auto; padding:0 16px 16px; min-height:0; overscroll-behavior:contain; }
.context-details { margin-top:12px; padding:10px 0; border-top:1px solid var(--app-border); }
.context-details > summary { color:var(--app-text-secondary); cursor:pointer; font-size:13px; line-height:1.8; }
.context-details[open] > summary { margin-bottom:12px; }
button:focus-visible,summary:focus-visible { outline:2px solid var(--app-primary); outline-offset:2px; }
</style>
