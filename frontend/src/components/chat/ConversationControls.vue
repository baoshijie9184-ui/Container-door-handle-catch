<template>
 <section v-if="state.enabled&&(editing||pending.length||error||state.error||(state.run&&state.run.phase!=='IDLE'))" class="conversation-controls" aria-label="Agent 执行控制">
  <details class="conversation-options"><summary>任务操作</summary>
  <div class="conversation-control-bar"><span role="status"><StatusBadge domain="executionPhase" :code="state.run?.phase" :label="state.run?controlPhaseLabels[state.run.phase]:'状态待核对'" /></span><div><slot name="navigation" />
   <el-button v-if="state.run?.local&&state.run.phase==='RUNNING'" size="small" :icon="VideoPause" :disabled="busy" @click="command('pause')">暂停任务</el-button>
   <el-button v-if="state.run?.local&&['PAUSED','PAUSE_REQUESTED'].includes(state.run.phase)" size="small" :icon="VideoPlay" :disabled="busy" @click="command('resume')">继续任务</el-button>
   <el-button v-if="state.run?.local&&state.run.runId" size="small" type="danger" plain :disabled="busy" @click="command('cancel')">取消任务</el-button>
   <el-button size="small" :icon="Refresh" :disabled="busy" @click="client.poll()">刷新</el-button>
  </div></div>
  <details class="control-help"><summary>执行说明</summary><p class="control-note">暂停在安全切点生效，当前调用可能继续完成；仅在服务进程存活期间继续。排队输入 15 分钟有效，失败不自动重试。</p></details>
  <div class="conversation-delivery"><label for="conversation-delivery-mode">发送方式</label><select id="conversation-delivery-mode" v-model="mode"><option value="NEXT_TURN">排到下一轮</option><option value="NEXT_STEP">引导当前任务</option></select><span>{{ mode==='NEXT_STEP'?'下一推理切点交付；本轮已结束时转入下一轮':'当前任务结束后按顺序处理' }}</span></div>
  <details v-if="receipts.length" class="control-help"><summary>最近交付记录</summary><p v-for="item in receipts" :key="item.id" class="control-receipt"><span>{{ item.mode==='NEXT_STEP'?'补充要求':'消息' }}</span><StatusBadge domain="queuedInput" :code="item.status" :label="inputStatusLabels[item.status]" /><small>{{ item.id.slice(0,8) }}</small></p></details>
  </details>
  <p v-if="!editing&&(error||state.error)" class="control-error" role="alert">{{ error||state.error }}</p>
  <p v-if="state.queueEnabled===false" class="queue-preference">消息排队已关闭，已有消息继续处理<button type="button" @click="client.setQueueEnabled(true)">开启排队</button></p>
  <p v-if="pending.length" class="queue-count" role="status">{{ pending.length }} 条消息待处理</p>
  <TransitionGroup v-if="pending.length" name="queue-row" tag="ol" class="conversation-queue" aria-label="待处理消息">
   <li v-for="(item,index) in pending" :key="item.id">
    <svg class="queue-entry-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3 3v6a3 3 0 0 0 3 3h14m-5-5 5 5-5 5" /></svg>
    <p class="queue-content" :title="item.content">{{ item.content }}</p>
    <span v-if="item.mode==='NEXT_STEP'" class="queue-steering-status">等待引导</span>
    <button v-else type="button" class="queue-steer" :disabled="busy||!state.run?.runId" title="在当前任务的下一推理切点补充要求" @click="steer(item)"><el-icon aria-hidden="true"><Right /></el-icon>引导</button>
    <button type="button" class="queue-icon-button" :aria-label="'撤回第 '+(index+1)+' 条待处理消息'" title="撤回消息" :disabled="busy" @click="withdraw(item)"><el-icon aria-hidden="true"><Delete /></el-icon></button>
    <el-dropdown trigger="click" :disabled="busy" @command="action=>action==='edit'?edit(item):client.setQueueEnabled(false)"><button type="button" class="queue-icon-button" aria-label="更多消息操作" title="更多消息操作" :disabled="busy"><el-icon aria-hidden="true"><MoreFilled /></el-icon></button><template #dropdown><el-dropdown-menu><el-dropdown-item command="edit" :icon="Edit">编辑消息</el-dropdown-item><el-dropdown-item command="close-queue" :icon="Close" :disabled="state.queueEnabled===false">关闭排队</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
   </li>
  </TransitionGroup>

  <el-dialog v-model="editing" class="queue-edit-dialog" title="编辑待处理消息" width="min(520px,calc(100vw - 32px))" append-to-body :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy">
   <p class="control-edit-note">{{ editItem?.mode==='NEXT_STEP'?'此消息将在当前任务的安全切点交付':'此消息排到后续轮次处理' }}。保存失败时保留草稿，不会自动重试。</p>
   <el-input v-model="editText" type="textarea" :rows="4" :disabled="busy" show-word-limit :maxlength="editItem?.mode==='NEXT_STEP'?4000:8000" aria-label="待处理消息内容"/>
   <p v-if="editStale&&!busy" role="status" class="control-error">原消息已变化、交付或尚未读取，请先复制编辑内容，再关闭并核对当前队列。</p>
   <p v-if="error||state.error" class="control-error" role="alert">{{ error||state.error }}</p>
   <template #footer><el-button :disabled="busy" @click="editing=false">取消</el-button><el-button type="primary" :loading="busy" :disabled="editStale||!editText.trim()" @click="saveEdit">保存修改</el-button></template>
  </el-dialog>
 </section>
</template>
<script setup>
import {ref,computed,watch,onBeforeUnmount} from 'vue'
import {ElMessageBox} from 'element-plus'
import {VideoPause,VideoPlay,Refresh,Right,Delete,MoreFilled,Edit,Close} from '@element-plus/icons-vue'
import {ConversationControlClient,controlPhaseLabels,inputStatusLabels} from '@/utils/conversationControl'
import '@/assets/conversation-control.css'
const props=defineProps({sessionId:String}),emit=defineEmits(['snapshot','refresh'])
const state=ref({enabled:false,run:null,inputs:[]}),mode=ref('NEXT_TURN'),busy=ref(false),error=ref(''),editing=ref(false),editText=ref(''),editItem=ref(null)
const client=new ConversationControlClient({base:(import.meta.env.VITE_API_URL||'').replace(/\/$/,'')+'/api/agent/conversations',onState:value=>{state.value=value;emit('snapshot',value)},onRefresh:session=>emit('refresh',session)})
let ready=Promise.resolve()
watch(()=>props.sessionId,session=>{error.value='';editing.value=false;busy.value=false;ready=client.open(session)},{immediate:true})
onBeforeUnmount(()=>client.close())
const pending=computed(()=>state.value.inputs.filter(item=>item.status==='QUEUED').reverse())
const receipts=computed(()=>state.value.inputs.filter(item=>item.status!=='QUEUED').slice(0,3))
const editStale=computed(()=>{const current=state.value.inputs.find(item=>item.id===editItem.value?.id);return !current||current.status!=='QUEUED'||current.revision!==editItem.value?.revision})
async function mutate(action){const generation=client.generation;busy.value=true;error.value='';try{return await action()}catch(cause){if(generation===client.generation)error.value=cause.message;throw cause}finally{if(generation===client.generation)busy.value=false}}
async function command(action){const generation=client.generation,runId=state.value.run?.runId;if(action==='cancel'){try{await ElMessageBox.confirm('取消本轮执行，排队消息保留并在本轮结束后处理。如需停止后续消息，请先逐条撤回。已完成的工具操作不会回滚。','取消任务',{confirmButtonText:'确认取消',cancelButtonText:'继续执行'})}catch{return}if(generation!==client.generation)return;if(runId!==state.value.run?.runId){error.value='当前任务已变化，请重新核对后操作';return}}try{await mutate(()=>client.command(action))}catch{/* 状态已显示，用户手动核对 */}}
function edit(item){error.value='';editItem.value=item;editText.value=item.content;editing.value=true}
async function saveEdit(){if(busy.value||editStale.value||!editText.value.trim())return;const generation=client.generation,item=editItem.value;try{await mutate(()=>client.change(item,editText.value));if(generation===client.generation&&editItem.value?.id===item.id)editing.value=false}catch{/* 保留草稿 */}}
async function withdraw(item){try{await mutate(()=>client.change(item,null))}catch{/* 结果已显示，不重试 */}}
async function steer(item){try{await mutate(()=>client.steer(item))}catch{/* 保留同一条消息，不重发 */}}
defineExpose({ready:async()=>{await ready;return client.enabled},submit:content=>mutate(()=>client.submit(content,mode.value)),cancel:()=>command('cancel')})
</script>
