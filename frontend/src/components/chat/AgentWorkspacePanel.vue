<template>
  <aside class="workspace-context" aria-label="Agent 工作面板" @keydown.esc.stop="$emit('close')">
    <header class="context-heading"><div><h3>会话工作区</h3></div><button type="button" aria-label="关闭工作面板" @click="$emit('close')"><el-icon><Close /></el-icon></button></header>
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
      <AgentRecentExecution :session-id="sessionId" :trace="trace" :loaded="traceLoaded" :error="traceError" :loading="loading" @refresh="$emit('refresh')" />
    </section>
    <footer><span>DoorHandle Agent</span><span>当前账号工作区</span></footer>
  </aside>
</template>
<script setup>
import { computed, ref, nextTick } from 'vue'
import AgentWorkbenchPanel from './AgentWorkbenchPanel.vue'
import AgentRecentExecution from './AgentRecentExecution.vue'
import { Close, ChatDotRound, Collection, Connection, Notebook, DataLine, Lock, TopRight as ArrowUpRight, Compass } from '@element-plus/icons-vue'
const props=defineProps({title:String,sessionId:String,trace:Object,traceLoaded:Boolean,traceError:String,loading:Boolean,messages:{type:Array,default:()=>[]}})
defineEmits(['close','refresh','reference'])
const tabs=['工作区','最近执行'],tab=ref(0)
const resources=computed(()=>[
  {name:'技能 Skills',description:'查看技能与安装记录',path:'/agent/skills',icon:Collection},
  {name:'固定 Fetch MCP',description:'查看本人安装、启用与执行状态',path:'/agent/mcp',icon:Connection},
  {name:'资源市场',description:'查看外部资源目录与接入条件',path:'/agent/markets',icon:Compass},
  {name:'个人记忆',description:'查看和管理本人记忆',path:'/agent/memory',icon:Notebook},
  {name:'执行与调研',description:'工具轨迹、模型路由与来源',path:'/agent/trace?sessionId='+encodeURIComponent(props.sessionId||''),icon:DataLine},
])
async function changeTab(event){
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return
  const container=event.currentTarget
  event.preventDefault();tab.value=event.key==='Home'?0:event.key==='End'?1:1-tab.value
  await nextTick();container.querySelector('[aria-selected="true"]')?.focus()
}
</script>
<style scoped>
.workspace-context { height:100%; min-height:0; display:flex; flex-direction:column; background:var(--app-bg); border-left:1px solid var(--app-border); color:var(--app-text); }
.context-heading { display:flex; justify-content:space-between; align-items:center; gap:12px; padding:20px 18px 16px; }
.context-heading h3 { font-size:14px; margin:0; font-weight:600; }
.context-heading button { display:grid; place-items:center; border:0; background:transparent; cursor:pointer; color:var(--app-text-secondary); width:32px; height:32px; flex:0 0 32px; border-radius:7px; }
.context-heading button:hover { background:var(--app-primary-soft); color:var(--app-primary); }
.context-tabs { display:flex; gap:4px; margin:0 16px 6px; padding:4px; background:#eaf0f7; border-radius:8px; }
.context-tabs button { flex:1; min-width:0; padding:8px; border:0; border-radius:6px; background:transparent; color:var(--app-text-secondary); font:inherit; font-size:12px; cursor:pointer; transition:color 160ms ease, background-color 160ms ease; }
.context-tabs button[aria-selected=true] { background:white; color:var(--app-primary); box-shadow:0 1px 3px #0f172a0a; }
.context-content { flex:1; overflow:auto; padding:18px; min-height:0; overscroll-behavior:contain; }
.context-session { display:flex; align-items:flex-start; gap:10px; padding-bottom:18px; border-bottom:1px solid var(--app-border); margin-bottom:20px; }
.context-session > .el-icon { margin-top:3px; color:var(--app-primary); flex-shrink:0; }
.context-session > div { display:grid; gap:7px; min-width:0; }
.context-session small,.context-section-title { font-size:11px; line-height:1.8; color:var(--app-text-secondary); }
.context-session strong { font-size:13px; line-height:1.8; font-weight:550; overflow-wrap:anywhere; }
.context-section-title { margin:24px 0 10px; }
.context-resource { display:flex; gap:10px; align-items:center; padding:12px 0; color:var(--app-text); text-decoration:none; border-radius:8px; transition:background-color 160ms ease; }
.context-resource > span:nth-child(2) { display:grid; gap:5px; flex:1; min-width:0; }
.context-resource strong { font-size:12px; font-weight:550; line-height:1.7; overflow-wrap:anywhere; }
.context-resource small { font-size:11px; line-height:1.8; color:var(--app-text-secondary); overflow-wrap:anywhere; }
.context-resource > .el-icon { font-size:13px; color:var(--app-text-secondary); flex-shrink:0; }
.resource-icon { height:32px; width:32px; flex:0 0 32px; display:grid; place-items:center; background:white; border:1px solid var(--app-border); border-radius:8px; color:var(--app-primary); }
.context-resource:hover { background:var(--app-primary-soft); }
.context-notice { display:flex; align-items:flex-start; gap:8px; padding:14px 0 0; margin-top:22px; border-top:1px solid var(--app-border); color:var(--app-text-secondary); }
.context-notice p { margin:0; font-size:11px; line-height:1.85; }
.context-notice > .el-icon { margin-top:3px; color:var(--app-primary); flex-shrink:0; }
footer { display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; padding:14px 18px; border-top:1px solid var(--app-border); font-size:10px; line-height:1.8; color:var(--app-text-secondary); }
button:focus-visible,a:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
button:active:not(:disabled) { transform:scale(.98); }
@media(prefers-reduced-motion:reduce) { .context-resource,.context-tabs button { transition:none; } button:active:not(:disabled) { transform:none; } }
</style>
