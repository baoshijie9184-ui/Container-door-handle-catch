<template>
 <section v-if="state.enabled&&state.sessionId===sessionId" class="agent-workbench" aria-label="Agent 持久工作台">
  <header><strong>任务工作台</strong><button type="button" :disabled="busy" @click="client.poll()"><AppIcon name="Refresh" :size="14" />刷新</button></header>
  <div role="status" aria-live="polite" aria-label="后台任务通知"><p v-for="notice in state.notifications||[]" :key="notice.id" class="wb-note">{{ notice.text }}</p></div>
  <nav ref="workbenchTabs" aria-label="工作台视图"><button v-for="[key,label] in tabs" :key="key" type="button" :class="{active:tab===key}" :aria-pressed="tab===key" @click="tab=key"><AppIcon :name="workbenchTabIcon(key)" :size="14" />{{ label }}</button></nav>
  <p v-if="error||state.error" role="alert" class="wb-error">{{ error||state.error }}</p>
  <p v-if="tab==='RECOVERY'" class="wb-note">仅可恢复启用后保存了 SDK 检查点的任务；旧版历史记录不可续跑</p>
  <template v-if="tab==='FILE'">
   <label class="wb-upload"><span class="wb-upload-title"><AppIcon name="Upload" :size="18" />上传本人资料</span><input type="file" accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.md,.csv,.json,.html,.svg" :disabled="busy||!state.loaded" @change="upload" /></label>
   <p class="wb-note">单文件上限 {{ state.loaded?composerAttachment({bytes:state.limits?.maxFileBytes}).size:'尚未核对' }} · HTML/SVG 仅查看源码</p>
   <details class="wb-business-link"><summary><AppIcon name="Connection" :size="15" />关联已有业务资料</summary><p class="wb-note">填写有权访问的任务或报告编号，每次读取重新鉴权。</p><form class="wb-business-form" @submit.prevent="attachBusiness"><select v-model="businessKind" aria-label="业务文件类型" :disabled="busy||!state.loaded"><option value="DETECTION">检测任务</option><option value="REPORT">质检报告</option></select><input v-model="businessId" aria-label="业务对象编号" placeholder="任务或报告编号" maxlength="128" :disabled="busy||!state.loaded"/><button type="submit" :disabled="busy||!state.loaded||!businessId.trim()">关联业务文件</button></form></details>
   <AgentWorkbenchFiles :key="sessionId" :files="state.files" :business-files="state.businessFiles" :known="state.loaded" :loading="state.loading" :error="state.error" :busy="busy" @preview="preview" @download="download" @reference="insertReference" @copy="copyReference" @remove="removeFile" @preview-business="previewBusiness" />
  </template>
  <template v-else-if="tab==='FORK'">
   <AgentForkPanel :key="sessionId" :session-id="sessionId" :messages="messages" :lineage="state.lineage" :known="state.loaded" :loading="state.loading" :read-error="state.error" :busy="busy" @fork="fork" @source="openSourceSession" />
  </template>
  <template v-else>
   <article v-for="item in rows" :key="item.id" :data-kind="item.kind">
    <header><span class="wb-kind-icon"><AppIcon :name="workbenchKind(item.kind).icon" :size="18" /></span><strong>{{ workbenchTitle(item) }}</strong><StatusBadge :domain="item.kind==='CONTEXT'?'contextRecord':'task'" :code="item.kind==='CONTEXT'?contextStatusCode(item):item.status" :label="item.kind==='CONTEXT'?undefined:workbenchInteractionStatus(item) || status[item.status]" /></header>
    <p class="wb-record-meta">{{ workbenchKind(item.kind).label }} · 版本 {{ item.revision }}<span v-if="workbenchTime(item.updatedAt)"> · 更新于 {{ workbenchTime(item.updatedAt) }} UTC+8</span></p>
    <p v-if="item.kind==='QUESTION'" class="wb-purpose"><AppIcon name="ChatDotRound" :size="14" />补充任务信息，回答不等于业务授权</p>
    <p v-if="item.kind==='PLAN'" class="wb-purpose"><AppIcon name="DocumentChecked" :size="14" />审阅执行范围，业务操作仍需单独确认</p>
    <a v-if="item.data.runId&&/^[a-f0-9-]{36}$/.test(item.data.runId)" :href="'/#/agent/trace?runId='+encodeURIComponent(item.data.runId)">查看本次执行轨迹</a>
    <a v-if="['/detection','/agent/mcp','/agent/actions'].includes(item.data.managementPath)" :href="'/#'+item.data.managementPath">打开原任务页面</a>
    <p v-if="item.data.text && ['PLAN','QUESTION'].includes(item.kind)" class="wb-reading-text">{{ item.data.text }}</p>
    <pre v-else-if="item.data.text && item.kind!=='CONTEXT'" tabindex="0" aria-label="工作记录正文">{{ item.data.text }}</pre>
    <p v-if="item.kind==='EXECUTION'&&item.data.result" class="wb-output">{{ item.data.result }}</p>
    <button v-if="item.kind==='EXECUTION'&&['RUNNING','QUEUED','READY','WAITING_PLAN','WAITING_INPUT','WAITING_CHILD'].includes(item.status)" :disabled="busy" @click="cancelTask(item)">取消任务</button>
    <p v-if="taskListSummary(item.data.tasks)" class="wb-task-summary">{{ taskListSummary(item.data.tasks) }}</p>
    <ol v-if="Array.isArray(item.data.tasks)&&item.data.tasks.length" class="wb-task-list"><li v-for="(task,index) in item.data.tasks" :key="index"><StatusBadge domain="task" :code="taskStepStatus(task?.status)" /><div>{{ task?.title || '未记录步骤名称' }}<small v-if="task?.evidenceCallId">执行证据 {{ task.evidenceCallId }}</small></div></li></ol>
    <div v-if="item.kind==='QUESTION'&&item.status==='ANSWERED'" class="wb-answer"><strong>已提交的回答</strong><p>{{ workbenchAnswer(item.data.answer) }}</p></div>
    <div v-if="item.kind==='PLAN'&&item.data.feedback" class="wb-answer"><strong>修订意见</strong><p>{{ item.data.feedback }}</p></div>
    <WorkbenchInteraction v-if="['PLAN','QUESTION'].includes(item.kind) && item.status === 'PENDING'" :item="item" :value="item.data.questionType === 'MULTIPLE' ? (selections[item.id] || []) : (drafts[item.id] || '')" :busy="busy" @update:value="updateInteraction(item, $event)" @command="act(item, $event.action, $event.input)" />
    <AgentChildTask v-if="item.kind==='CHILD'" :item="item" :value="drafts[item.id] || ''" :busy="busy" :available-views="tabs.map(([key])=>key)" @update:value="drafts[item.id]=$event" @command="act(item,'child-message',{content:$event})" @cancel="cancelChild(item)" @view="openWorkbenchView" />
    <AgentUsageSummary v-if="item.kind==='USAGE'" :data="item.data" />
    <AgentContextSummary v-if="item.kind==='CONTEXT'" :item="item" :files="state.files" :files-enabled="state.capabilities.files!==false" @open-files="openContextFiles" />
    <p v-if="item.kind==='TOOL_TIMING'">工具批次耗时 {{ tokens(item.data.durationMs) }} ms</p>
    <div v-if="item.status==='NEEDS_REVIEW'" class="wb-recovery"><p class="wb-note">恢复会重新鉴权，未知写结果不会自动重做</p>
     <template v-if="state.capabilities.modelConfig">
      <p class="wb-note">任务模型 {{ item.data.modelId||item.data.modelDefault||'未固定' }} · {{ item.data.modelConfigVersion?'V'+item.data.modelConfigVersion:'历史配置未知' }}</p>
      <template v-if="item.kind==='EXECUTION'"><label>恢复时使用<select v-model="recoveryChoices[item.id]" :disabled="busy" aria-label="恢复任务使用模型"><option value="KEEP">保留任务原配置</option><option value="CURRENT_DEFAULT" :disabled="!state.recoveryModels?.some(model=>model.id===state.recoveryDefault)">当前默认 · {{ state.recoveryDefault||'尚未核对' }} · V{{ state.recoveryConfigVersion||'未知' }}</option><option v-for="model in state.recoveryModels||[]" :key="model.id" :value="model.id">{{ modelLabel(model) }} · V{{ state.recoveryConfigVersion }}</option></select></label><button :disabled="busy||state.recoveryModelsLoading" @click="client.loadRecoveryModels()">核对恢复模型</button><p v-if="state.recoveryModelError" role="alert" class="wb-error">{{ state.recoveryModelError }}</p><small>更换配置后，未结束的专业任务同步使用新版本；仍在执行的子任务需要先停止</small></template>
      <p v-else class="wb-note">需要更换模型时，先在主任务恢复卡片选择当前配置</p>
     </template>
     <button :disabled="busy||!canResume(item)" @click="resume(item)">确认从检查点恢复</button><button :disabled="busy" @click="act(item,'cancel')">结束任务</button>
    </div>
   </article>
   <div v-if="!rows.length" class="wb-empty"><AppIcon :name="workbenchEmpty(tab,state).icon" :size="24" /><strong>{{ workbenchEmpty(tab,state).title }}</strong><p>{{ workbenchEmpty(tab,state).description }}</p></div>
  </template>
  <el-dialog v-model="previewOpen" :title="previewFile?.name||'文件预览'" append-to-body width="min(900px,90vw)" class="workbench-file-preview-dialog">
   <p class="file-preview-meta"><AppIcon :name="composerAttachment(previewFile).icon" :size="18" /><span>{{ composerAttachment(previewFile).type }}</span><span>{{ composerAttachment(previewFile).size }}</span></p>
   <p v-if="previewError" class="wb-error" role="alert">{{ previewError }}</p><p v-if="busy" role="status">正在读取文件，请稍候</p>
   <nav v-if="previewType==='pdf'" ref="pdfNavigation" tabindex="-1" class="chat-file-pages" aria-label="PDF 页码"><button type="button" :disabled="busy||previewPage===1" @click="preview(previewFile,previewPage-1)">上一页</button><span role="status">第 {{ previewPage }} / {{ previewPages }} 页</span><button type="button" :disabled="busy||previewPage===previewPages" @click="preview(previewFile,previewPage+1)">下一页</button><small>页面预览 · Agent 仅可读取文字层</small></nav>
   <p class="wb-preview-note">预览不执行文件内容。HTML/SVG 按源码展示，PDF 显示页面图片；下载可保留原文件。</p>
   <img v-if="['image','pdf'].includes(previewType)" :src="previewUrl" class="wb-preview-image" :alt="(previewFile?.name||'本人资料')+'页面预览'" @error="previewError='图片预览失败，请下载原文件核对'"/>
   <pre v-else class="chat-file-preview-text" tabindex="0" aria-label="资料文本或源码预览">{{ previewText }}</pre>
   <template #footer><div class="file-preview-actions"><el-button @click="previewOpen=false">关闭预览</el-button><el-button v-if="canDownloadPreview" type="primary" :disabled="busy" @click="download(previewFile)"><AppIcon name="Download" :size="15" />下载原文件</el-button></div></template>
  </el-dialog>
 </section>
</template>
<script setup>
import {nextTick,ref,reactive,computed,watch,onBeforeUnmount} from 'vue'
import {ElMessageBox} from 'element-plus'
import {AgentWorkbenchClient,availableWorkbenchTabs,workbenchStatus,workbenchRows,tokenDisplay,recoveryInput} from '@/utils/agentWorkbench'
import {modelLabel} from '@/utils/composerResources'
import {composerAttachment} from '@/utils/composerPresentation'
import AgentWorkbenchFiles from './AgentWorkbenchFiles.vue'
import AgentUsageSummary from './AgentUsageSummary.vue'
import AgentContextSummary from './AgentContextSummary.vue'
import AgentForkPanel from './AgentForkPanel.vue'
import AgentChildTask from './AgentChildTask.vue'
import { contextStatusCode } from '@/utils/contextPresentation'
import WorkbenchInteraction from './WorkbenchInteraction.vue'
import {workbenchKind,workbenchTabIcon,workbenchInteractionStatus,workbenchTitle,workbenchEmpty,workbenchTime,taskListSummary,taskStepStatus,workbenchAnswer} from '@/utils/workbenchPresentation'
import {readFilePreview,boundedTextPreview} from '@/utils/chatFileReferences'
import '@/assets/agent-workbench.css'
import '@/assets/chat-file-references.css'
const props=defineProps({sessionId:String,messages:{type:Array,default:()=>[]}})
const emit=defineEmits(['reference'])
const state=ref({enabled:false,items:[],files:[],capabilities:{}}),tab=ref('PLAN'),error=ref(''),busy=ref(false),drafts=reactive({}),selections=reactive({})
const workbenchTabs=ref(null)
async function openWorkbenchView(view){if(!tabs.value.some(([key])=>key===view))return;const session=props.sessionId;tab.value=view;await nextTick();if(props.sessionId===session && tab.value===view)workbenchTabs.value?.querySelector('[aria-pressed="true"]')?.focus({preventScroll:true})}
function openContextFiles(){return openWorkbenchView('FILE')}
const recoveryChoices=reactive({})
const previewOpen=ref(false),previewUrl=ref(''),previewText=ref(''),previewType=ref('text')
const previewFile=ref(null),previewPage=ref(1),previewPages=ref(1),previewError=ref('')
const pdfNavigation=ref(null)
let pdfFocusPending=false
const canDownloadPreview=computed(()=>!!previewFile.value?.id&&(state.value.files||[]).some(file=>file.id===previewFile.value.id))
watch([previewOpen,previewPage,busy],async()=>{if(previewOpen.value&&previewType.value==='pdf'&&!busy.value&&pdfFocusPending){await nextTick();if(previewOpen.value&&pdfFocusPending){pdfFocusPending=false;pdfNavigation.value?.focus()}}},{flush:'post'})
let previewVersion=0,operationVersion=0
watch(previewOpen,open=>{if(!open){previewVersion++;pdfFocusPending=false;if(previewUrl.value)URL.revokeObjectURL(previewUrl.value);previewUrl.value=''}},{flush:'sync'})
const businessKind=ref('DETECTION'),businessId=ref('')
const client=new AgentWorkbenchClient({base:(import.meta.env.VITE_API_URL||'').replace(/\/$/,''),onState:value=>{state.value=value;for(const item of value.items){if(item.kind==='QUESTION'&&item.data.questionType==='MULTIPLE'&&!selections[item.id])selections[item.id]=[];if(item.status==='NEEDS_REVIEW'&&!recoveryChoices[item.id])recoveryChoices[item.id]='KEEP'}}})
const tabs=computed(()=>availableWorkbenchTabs(state.value.capabilities)),status=workbenchStatus,tokens=tokenDisplay,rows=computed(()=>workbenchRows(state.value.items,tab.value))
watch(()=>props.sessionId,session=>{operationVersion++;busy.value=false;error.value='';previewOpen.value=false;previewVersion++;businessId.value='';for(const map of [recoveryChoices,drafts,selections])for(const id of Object.keys(map))delete map[id];client.open(session)},{immediate:true})
onBeforeUnmount(()=>{operationVersion++;client.close();if(previewUrl.value)URL.revokeObjectURL(previewUrl.value)})
async function run(action,previewing=false){if(busy.value)return;const generation=client.generation,operation=++operationVersion;busy.value=true;error.value='';try{const result=await action();return generation===client.generation&&operation===operationVersion?result:undefined}catch(cause){if(generation===client.generation&&operation===operationVersion){error.value=cause.message||'操作结果尚未核对，请刷新资料';if(previewing)previewError.value=error.value;if([403,404].includes(cause.status))previewOpen.value=false}}finally{if(operation===operationVersion)busy.value=false}}
async function act(item,action,input){await run(()=>client.command(item,action,input));}
function updateInteraction(item,value){if(busy.value)return;if(item.kind==='QUESTION'&&item.data.questionType==='MULTIPLE')selections[item.id]=value;else drafts[item.id]=value}
function recoveryPayload(item){return recoveryInput(item.kind==='EXECUTION'?(recoveryChoices[item.id]||'KEEP'):'KEEP',state.value)}
function canResume(item){try{recoveryPayload(item);return true}catch{return false}}
async function resume(item){
 const generation=client.generation
 try{const input=recoveryPayload(item);if(Object.hasOwn(input,'replacementModelId'))await ElMessageBox.confirm(`将任务及未结束的专业任务改用 V${input.replacementConfigVersion} 的 ${input.replacementModelId||state.value.recoveryDefault}。已完成工具结果仍保留，未知写结果不会重新执行。`,'确认恢复模型',{confirmButtonText:'确认更换并恢复',cancelButtonText:'保留现状'});if(generation===client.generation)await act(item,'resume',input)}catch(cause){if(cause!=='cancel'&&cause!=='close')error.value=cause.message}
}
async function cancelTask(item){const generation=client.generation;try{await ElMessageBox.confirm('取消本任务及其活动子任务，已完成的操作不会回滚。排队消息仍按原设置处理。','取消任务',{confirmButtonText:'确认取消',cancelButtonText:'继续执行',type:'warning'});if(generation===client.generation)await act(item,'cancel')}catch{/* Dialog dismissal does not change the task. */}}
async function cancelChild(item){
 if(busy.value)return
 const generation=client.generation
 try{
  await ElMessageBox.confirm(`取消所选专业任务 ${item.id}（V${item.revision}）？已完成的业务操作不会回滚，主任务和其他专业任务状态需分别核对。`,'取消此专业任务',{type:'warning',confirmButtonText:'确认取消此任务',cancelButtonText:'保留当前状态'})
  if(generation!==client.generation || busy.value)return
  const current=state.value.items.find(row=>row.id===item.id)
  if(!current || current.kind!=='CHILD' || current.revision!==item.revision){error.value='子任务记录已变化，请重新核对后再确认取消';return}
  await act(item,'cancel')
 }catch(cause){if(generation===client.generation && !['cancel','close'].includes(cause))error.value='取消尚未确认，请重新核对子任务记录'}
}
async function attachBusiness(){if(busy.value||!state.value.loaded||!businessId.value.trim())return;await run(()=>client.attachBusiness(businessKind.value,businessId.value.trim()))}
async function removeFile(file){
 const generation=client.generation
 try{await ElMessageBox.confirm(`从当前会话移出“${file.name}”？此操作解除本会话的文件引用，不代表后端文件已物理删除或账号配额已释放。`,'移出会话资料',{type:'warning',confirmButtonText:'移出当前会话',cancelButtonText:'保留资料'});if(generation!==client.generation)return;const current=state.value.files.find(row=>row.id===file.id);if(!current){error.value='资料列表已变化，请刷新后核对';return}await run(()=>client.remove(current))}catch{/* Dismissing the confirmation keeps the reference. */}
}
function sessionHref(id){return '#/agent/chat?sessionId='+encodeURIComponent(id)}
function openSourceSession(id){if(!busy.value)window.location.assign(sessionHref(id))}
async function fork(id){const result=await run(()=>client.fork(id));if(result)window.location.assign(sessionHref(result.sessionId))}
async function upload(event){const file=event.target.files?.[0];if(file)await run(()=>client.upload(file));event.target.value=''}
async function copyReference(file){await run(()=>navigator.clipboard.writeText('@file:'+file.id));}
function insertReference(file){emit('reference','@file:'+file.id)}
async function preview(file,page=1){if(busy.value)return;const version=++previewVersion;if(previewOpen.value&&previewType.value==='pdf')pdfFocusPending=true;await run(async()=>{const generation=client.generation;const value=await readFilePreview(props.sessionId,file,{base:client.base,fetcher:client.fetcher,limit:state.value.limits?.previewBytes,page});if(generation!==client.generation||version!==previewVersion)return;if(previewUrl.value)URL.revokeObjectURL(previewUrl.value);previewUrl.value='';previewError.value='';previewFile.value=file;previewPage.value=value.page||1;previewPages.value=value.pages||1;previewType.value=value.kind;previewText.value=value.text||'';pdfFocusPending=value.kind==='pdf';if(value.kind!=='text')previewUrl.value=URL.createObjectURL(value.kind==='pdf'?value.blob:new Blob([value.blob],{type:file.contentType}));previewOpen.value=true},true)}
async function download(file){await run(async()=>{const generation=client.generation,blob=await client.content(file);if(generation!==client.generation)return;const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=file.name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)})}
async function previewBusiness(file){if(busy.value)return;pdfFocusPending=false;const version=++previewVersion;await run(async()=>{const generation=client.generation,image=['image/png','image/jpeg','image/webp'].includes(file.contentType);let text='';if(!image)text=await boundedTextPreview(await (await client.read(file.previewPath)).blob(),state.value.limits?.previewBytes);if(generation!==client.generation||version!==previewVersion)return;if(previewUrl.value)URL.revokeObjectURL(previewUrl.value);previewFile.value=file;previewError.value='';previewType.value=image?'image':'text';previewText.value=text;previewUrl.value=image?client.base+file.previewPath:'';previewOpen.value=true},true)}
</script>
