<template>
  <details v-if="rows.length || runId || active" class="tool-execution" @toggle="toggle">
    <summary class="tool-execution-heading"><span class="tool-execution-toggle"><AppIcon name="ArrowRight" :size="13" /></span><strong>{{ summary }}</strong></summary>
    <div class="tool-execution-body">
      <details v-for="tool in displayRows" :key="tool.id" class="tool-call">
        <summary><span class="tool-call-state" :data-status="tool.status" :class="{ 'is-spinning': ['calling','awaiting-result'].includes(tool.status) }"><AppIcon :name="tool.status==='returned'?'CircleCheck':tool.status==='failed'?'CircleClose':tool.status==='cancelled'?'Close':'Refresh'" :size="15" /></span><span class="tool-call-label">{{ toolTitle(tool.name) }}</span><span class="tool-call-status">{{ toolStatus(tool.status) }}</span><span class="tool-call-description" :title="tool.name">{{ tool.name }}</span><span v-if="toolTime(tool.durationMs)" class="tool-call-duration">{{ toolTime(tool.durationMs) }}</span></summary>
        <div class="tool-call-detail"><header><span>工具调用记录</span><button type="button" class="tool-call-copy" aria-label="复制工具调用记录" @click="copy(tool)"><AppIcon name="DocumentCopy" :size="13" /></button></header><dl><dt>工具</dt><dd>{{ tool.name }}</dd><dt>调用编号</dt><dd>{{ tool.id }}</dd><dt>状态</dt><dd>{{ toolStatus(tool.status) }}</dd><template v-if="tool.agent"><dt>执行助手</dt><dd>{{ tool.agent }}</dd></template><template v-if="toolTime(tool.durationMs)"><dt>记录耗时</dt><dd>{{ toolTime(tool.durationMs) }}</dd></template></dl><p>{{ tool.status==='returned'?'已收到工具返回，业务结论以回复和业务记录为准。':tool.status==='failed'?'本次调用返回失败，详细原因请核对执行追溯。':'仅展示服务端已经记录的执行状态。' }}</p><p v-if="copyState" role="status">{{ copyState }}</p></div>
      </details>
      <p v-if="!rows.length" class="tool-execution-notice">{{ active ? '等待服务端工具回执' : '本轮尚未读到工具调用记录' }}</p>
      <p v-if="saved.error" class="tool-execution-notice" role="status">{{ saved.error }}<button v-if="!saved.denied" type="button" class="tool-execution-reload" @click="reader?.read()">重新读取</button></p>
    </div>
  </details>
</template>
<script setup>
import {computed,onBeforeUnmount,ref,watch} from 'vue'
import {ToolExecutionReader,toolRows,toolSummary,toolTitle,toolStatus,toolTime} from '@/utils/toolExecution'
import '@/assets/tool-execution.css'
const props=defineProps({sessionId:String,runId:String,events:{type:Array,default:()=>[]},active:Boolean})
const saved=ref({events:[],known:false,complete:true}),copyState=ref('')
let reader
watch(()=>[props.sessionId,props.runId],()=>{reader?.close();reader=new ToolExecutionReader({onChange:value=>{saved.value=value}});saved.value=reader.open(props.sessionId,props.runId,props.active);copyState.value=''}, {immediate:true})
watch(()=>props.active,value=>{if(reader){reader.active=value;if(value)reader.read()}})
onBeforeUnmount(()=>reader?.close())
const rows=computed(()=>saved.value.denied?[]:toolRows([...saved.value.events,...props.events]))
const displayRows=computed(()=>rows.value.map(tool=>!props.active&&['calling','awaiting-result'].includes(tool.status)?{...tool,status:'unconfirmed'}:tool))
const summary=computed(()=>toolSummary(rows.value,props.active?'RUNNING':saved.value.phase||'finished',{known:props.events.length>0||saved.value.known,complete:props.events.length>0&&!props.active||!props.runId||saved.value.complete,truncated:saved.value.truncated}))
function toggle(event){if(event.currentTarget.open&&props.runId&&!saved.value.known)reader?.read()}
async function copy(tool){try{await navigator.clipboard.writeText([toolTitle(tool.name),tool.name,toolStatus(tool.status),'调用编号 '+tool.id,tool.agent,toolTime(tool.durationMs)].filter(Boolean).join('\n'));copyState.value='已复制调用记录'}catch{copyState.value='复制未完成，请手动选择调用记录'}}
</script>
