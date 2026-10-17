<template>
  <aside class="workspace-context" aria-label="Agent 工作面板" @keydown.esc.stop="$emit('close')">
    <header class="context-heading"><div><span>WORKSPACE</span><h3>会话工作区</h3></div><button type="button" aria-label="关闭工作面板" @click="$emit('close')"><el-icon><Close /></el-icon></button></header>
    <div class="context-tabs" role="tablist" aria-label="工作面板视图" @keydown="changeTab">
      <button v-for="(item,index) in tabs" :id="'workspace-tab-'+index" :key="item" type="button" role="tab" :aria-selected="tab===index" :tabindex="tab===index?0:-1" :aria-controls="'workspace-content-'+index" @click="tab=index">{{ item }}</button>
    </div>
    <section v-show="tab===0" id="workspace-content-0" role="tabpanel" aria-labelledby="workspace-tab-0" class="context-content">
      <div class="context-session"><el-icon><ChatDotRound /></el-icon><div><small>当前会话</small><strong>{{ title || '新对话' }}</strong></div></div>
      <AgentWorkbenchPanel :session-id="sessionId" :messages="messages" @reference="$emit('reference',$event)" />
      <p class="context-section-title">资源与能力</p>
      <a v-for="item in resources" :key="item.path" class="context-resource" :href="'#'+item.path"><span class="resource-icon"><el-icon><component :is="item.icon" /></el-icon></span><span><strong>{{ item.name }}</strong><small>{{ item.description }}</small></span><el-icon><ArrowUpRight /></el-icon></a>
      <div class="context-notice"><el-icon><Lock /></el-icon><p>会话与记忆按账号隔离<br>需要确认的操作，请在确认页面核对后执行</p></div>
    </section>
    <section v-show="tab===1" id="workspace-content-1" role="tabpanel" aria-labelledby="workspace-tab-1" class="context-content">
      <div class="context-run-heading"><span>本会话最近执行</span><button type="button" :disabled="loading" @click="$emit('refresh')"><el-icon><Refresh /></el-icon>{{ loading?'读取中':'刷新' }}</button></div>
      <template v-if="trace?.runId"><p class="context-run-status"><span class="record-dot"></span>{{ traceStatus(trace.status) }}</p><p class="context-run-id">{{ trace.runId }}</p></template>
      <ol v-if="events.length" class="context-events"><li v-for="event in events" :key="event.sequence"><span class="event-marker"></span><div><strong>{{ eventTitle(event) }}</strong><small>{{ event.payload.tool || event.payload.agent || '运行事件' }}</small></div></li></ol>
      <div v-else class="context-empty"><el-icon><DataLine /></el-icon><strong>{{ loading?'正在读取执行记录':'暂无已读取的执行事件' }}</strong><p>点击刷新读取当前会话的最近执行</p></div>
      <p class="context-note">仅展示服务器记录的最近 8 个事件，完整过程和调研来源请打开执行追溯</p>
      <a class="context-trace-link" :href="traceHref">打开执行追溯 <el-icon><ArrowRight /></el-icon></a>
    </section>
    <footer><span>DoorHandle Agent</span><span>当前账号工作区</span></footer>
  </aside>
</template>
<script setup>
import { computed, ref, nextTick } from 'vue'
import AgentWorkbenchPanel from './AgentWorkbenchPanel.vue'
import { Close, ChatDotRound, Collection, Connection, Notebook, DataLine, Lock, TopRight as ArrowUpRight, ArrowRight, Refresh } from '@element-plus/icons-vue'
import { normalizeTraceEvents, eventTitle, traceStatus } from '@/utils/agentTrace'
const props=defineProps({title:String,sessionId:String,trace:Object,loading:Boolean,messages:{type:Array,default:()=>[]}})
defineEmits(['close','refresh','reference'])
const tabs=['工作区','最近执行'],tab=ref(0)
const resources=computed(()=>[
  {name:'技能 Skills',description:'查看技能与安装记录',path:'/agent/skills',icon:Collection},
  {name:'MCP 工具',description:'管理工具连接与启用',path:'/agent/mcp',icon:Connection},
  {name:'个人记忆',description:'查看和管理本人记忆',path:'/agent/memory',icon:Notebook},
  {name:'执行与调研',description:'工具轨迹、模型路由与来源',path:'/agent/trace?sessionId='+encodeURIComponent(props.sessionId||''),icon:DataLine},
])
const events=computed(()=>normalizeTraceEvents(props.trace?.events,true).slice(-8))
const traceHref=computed(()=>props.trace?.runId?'#/agent/trace?runId='+encodeURIComponent(props.trace.runId):'#/agent/trace?sessionId='+encodeURIComponent(props.sessionId||''))
async function changeTab(event){
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return
  const container=event.currentTarget
  event.preventDefault();tab.value=event.key==='Home'?0:event.key==='End'?1:1-tab.value
  await nextTick();container.querySelector('[aria-selected="true"]')?.focus()
}
</script>
<style scoped>
.workspace-context{height:100%;min-height:0;display:flex;flex-direction:column;background:#f8f9fc;border-left:1px solid #e8ebf0;color:#263347}.context-heading{display:flex;justify-content:space-between;align-items:center;padding:22px 20px 18px}.context-heading span{font-size:9px;letter-spacing:.16em;color:#8993a2}.context-heading h3{font-size:14px;margin:6px 0 0;font-weight:600}.context-heading button,.context-run-heading button{border:0;background:transparent;cursor:pointer;color:#738097;display:flex;align-items:center;gap:5px;min-width:30px;min-height:30px;justify-content:center;border-radius:7px}.context-heading button:hover,.context-run-heading button:hover{background:#eaf0f8;color:#2563eb}.context-tabs{display:flex;gap:4px;margin:0 16px 6px;padding:4px;background:#edf0f5;border-radius:9px}.context-tabs button{flex:1;padding:8px;border:0;border-radius:6px;background:transparent;color:#718096;font-size:12px;cursor:pointer}.context-tabs button[aria-selected=true]{background:#fff;color:#23334c;box-shadow:0 1px 4px #253a5810}.context-content{flex:1;overflow:auto;padding:18px 20px;min-height:0}.context-session{display:flex;align-items:center;gap:10px;padding-bottom:22px;border-bottom:1px solid #e8ebf0}.context-session>.el-icon{font-size:20px;color:#8491a4}.context-session div{min-width:0;display:grid;gap:5px}.context-session small,.context-resource small{font-size:11px;color:#8290a2}.context-session strong{font-size:13px;font-weight:500;overflow-wrap:anywhere}.context-section-title{font-size:11px;color:#8290a2;margin:22px 0 10px}.context-resource{display:flex;gap:10px;align-items:center;padding:12px 0;color:#35445a;text-decoration:none;border-radius:8px;transition:background .16s,transform .16s}.context-resource>span:nth-child(2){display:grid;gap:5px;flex:1;min-width:0}.context-resource strong{font-size:12px;font-weight:500}.context-resource>.el-icon{font-size:12px;color:#a0aaba}.resource-icon{height:32px;width:32px;display:grid;place-items:center;background:white;border:1px solid #e7ebf1;border-radius:9px;color:#647a9e}.context-resource:hover{background:#edf2fa;transform:translateX(2px)}.context-notice{display:flex;gap:8px;padding:14px 0;margin-top:24px;border-top:1px solid #e7ebf1;color:#8491a4}.context-notice p,.context-note{font-size:11px;line-height:1.8;margin:0;color:#8491a4}.context-notice>.el-icon{margin-top:3px;flex-shrink:0}.context-run-heading{display:flex;justify-content:space-between;align-items:center;font-size:11px;color:#738097}.context-run-heading button{font-size:11px}.context-run-heading button:disabled{opacity:.5;cursor:wait}.context-run-status{display:flex;align-items:center;gap:6px;font-size:12px}.record-dot{width:6px;height:6px;border-radius:50%;background:#507bc5}.context-run-id{font:10px/1.7 Consolas,monospace;overflow-wrap:anywhere;color:#8d98a8}.context-events{list-style:none;padding:10px 0;margin:0 0 18px}.context-events li{position:relative;display:flex;gap:12px;padding:0 0 22px 4px}.context-events li:not(:last-child):before{content:'';position:absolute;left:7px;top:10px;bottom:0;width:1px;background:#dfe5ed}.event-marker{width:7px;height:7px;border-radius:50%;border:1.5px solid #7d98c3;background:#f8f9fc;flex-shrink:0;margin-top:4px}.context-events li div{display:grid;gap:7px;min-width:0}.context-events strong{font-size:12px;font-weight:500}.context-events small{font:10px/1.6 Consolas,monospace;color:#8a96a8;overflow-wrap:anywhere}.context-empty{display:grid;justify-items:center;text-align:center;gap:12px;padding:44px 0;color:#8b97a8}.context-empty>.el-icon{font-size:28px}.context-empty strong{font-size:12px;font-weight:400}.context-empty p{font-size:11px;line-height:1.7}.context-trace-link{font-size:12px;color:#2563eb;display:flex;justify-content:space-between;align-items:center;margin-top:20px;text-decoration:none}footer{display:flex;justify-content:space-between;padding:15px 20px;border-top:1px solid #e7ebf1;font-size:10px;color:#909baa}button:focus-visible,a:focus-visible{outline:2px solid #2563eb;outline-offset:3px}button:active:not(:disabled){transform:scale(.97)}@media(prefers-reduced-motion:reduce){.context-resource{transition:none;transform:none}button:active:not(:disabled){transform:none}}
</style>
