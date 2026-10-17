<template>
 <section v-if="state.enabled" class="agent-workbench" aria-label="Agent 持久工作台">
  <header><strong>任务工作台</strong><button type="button" :disabled="busy" @click="client.poll()">刷新</button></header>
  <div role="status" aria-live="polite" aria-label="后台任务通知"><p v-for="notice in state.notifications||[]" :key="notice.id" class="wb-note">{{ notice.text }}</p></div>
  <nav aria-label="工作台视图"><button v-for="[key,label] in tabs" :key="key" type="button" :class="{active:tab===key}" :aria-pressed="tab===key" @click="tab=key">{{ label }}</button></nav>
  <p v-if="error||state.error" role="alert" class="wb-error">{{ error||state.error }}</p>
  <p v-if="tab==='RECOVERY'" class="wb-note">仅可恢复启用后保存了 SDK 检查点的任务；旧版历史记录不可续跑</p>
  <template v-if="tab==='FILE'">
   <label class="wb-upload">上传资料<input type="file" accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.md,.csv,.json,.html,.svg" :disabled="busy" @change="upload" /></label>
   <p class="wb-note">本人文件 · 每文件最多 {{ Math.ceil((state.limits?.maxFileBytes||26214400)/1048576) }} MB · HTML/SVG 仅查看源码</p>
   <div class="wb-business-form"><select v-model="businessKind" aria-label="业务文件类型"><option value="DETECTION">检测任务</option><option value="REPORT">质检报告</option></select><input v-model="businessId" aria-label="业务对象编号" placeholder="任务或报告编号" maxlength="128"/><button :disabled="busy||!businessId.trim()" @click="run(()=>client.attachBusiness(businessKind,businessId.trim()))">关联业务文件</button></div>
   <article v-for="file in state.businessFiles||[]" :key="file.kind+file.resourceId+file.fileId"><strong>业务引用 / {{ file.name }}</strong><small>{{ file.resourceId }} · 每次读取重新鉴权</small><button @click="previewBusiness(file)">预览业务文件</button></article>
   <details v-for="folder in ['uploads','artifacts']" :key="folder" open class="wb-file-tree"><summary>{{ folder==='uploads'?'上传资料':'生成产物' }}（{{ state.files.filter(file=>file.folder===folder).length }}）</summary><article v-for="file in state.files.filter(file=>file.folder===folder)" :key="file.id"><strong>{{ file.name }}</strong><small>{{ Math.ceil(file.bytes/1024) }} KB</small><div class="wb-actions"><button @click="preview(file)">预览</button><button @click="download(file)">下载</button><button @click="insertReference(file)">引用</button><button @click="copyReference(file)">复制引用</button><button :disabled="busy" @click="run(()=>client.remove(file))">移除</button></div></article></details>
  </template>
  <template v-else-if="tab==='FORK'">
   <p class="wb-note">选择已完成回复创建独立分支，审批与排队消息不继承</p>
   <a v-if="state.lineage" :href="sessionHref(state.lineage.sourceSessionId)">返回来源会话</a>
   <article v-for="message in completedMessages" :key="message.id"><p>{{ message.content?.slice(0,120) }}</p><button :disabled="busy" @click="fork(message.id)">从此处创建分支</button></article>
  </template>
  <template v-else>
   <article v-for="item in rows" :key="item.id">
    <header><strong>{{ item.data.title||item.data.specialist||item.kind }}</strong><span>{{ status[item.status]||item.status }}</span></header>
    <a v-if="item.data.runId&&/^[a-f0-9-]{36}$/.test(item.data.runId)" :href="'/#/agent/trace?runId='+encodeURIComponent(item.data.runId)">查看本次执行轨迹</a>
    <a v-if="['/detection','/agent/mcp'].includes(item.data.managementPath)" :href="'/#'+item.data.managementPath">打开原任务页面</a>
    <pre v-if="item.data.text">{{ item.data.text }}</pre>
    <ol v-if="Array.isArray(item.data.tasks)"><li v-for="(task,index) in item.data.tasks" :key="index"><span>{{ task.status }}</span> {{ task.title }}<small v-if="task.evidenceCallId">证据 {{ task.evidenceCallId }}</small></li></ol>
    <template v-if="item.kind==='PLAN'&&item.status==='PENDING'"><textarea v-model="drafts[item.id]" placeholder="修改意见（要求修订时填写）" aria-label="计划修改意见" /><div class="wb-actions"><button :disabled="busy" @click="act(item,'approve-plan')">批准计划</button><button :disabled="busy||!drafts[item.id]?.trim()" @click="act(item,'revise-plan',{feedback:drafts[item.id]})">要求修订</button><button :disabled="busy" @click="act(item,'cancel')">取消计划</button></div><p class="wb-note">计划批准不代替业务审批</p></template>
    <template v-if="item.kind==='QUESTION'&&item.status==='PENDING'">
     <textarea v-if="item.data.questionType==='TEXT'" v-model="drafts[item.id]" aria-label="问题回答" />
     <select v-else-if="item.data.questionType==='SINGLE'" v-model="drafts[item.id]" aria-label="选择回答"><option disabled value="">请选择</option><option v-for="option in item.data.options" :key="option" :value="option">{{ option }}</option></select>
     <label v-for="option in item.data.questionType==='MULTIPLE'?item.data.options:[]" :key="option" class="wb-option"><input v-model="selections[item.id]" type="checkbox" :value="option" />{{ option }}</label>
     <div class="wb-actions"><button :disabled="busy" @click="act(item,'answer',{answer:item.data.questionType==='MULTIPLE'?(selections[item.id]||[]):drafts[item.id]})">提交回答</button><button :disabled="busy" @click="act(item,'cancel')">取消问题</button></div>
    </template>
    <template v-if="item.kind==='CHILD'"><p v-if="item.data.result">{{ item.data.result }}</p><template v-if="['COMPLETED','RUNNING','QUEUED'].includes(item.status)"><textarea v-model="drafts[item.id]" aria-label="子 Agent 补充要求" /><button :disabled="busy||!drafts[item.id]?.trim()" @click="act(item,'child-message',{content:drafts[item.id]})">追加专业要求</button><small v-if="item.status!=='COMPLETED'">追加要求在当前执行结束后继续处理</small></template><button v-if="['QUEUED','RUNNING','WAITING_INPUT','WAITING_PLAN','NEEDS_REVIEW'].includes(item.status)" :disabled="busy" @click="act(item,'cancel')">取消子任务</button></template>
    <dl v-if="item.kind==='USAGE'"><dt>模型 / 用途</dt><dd>{{ item.data.modelId||'未知模型' }} · {{ item.data.purpose==='SESSION_TOTAL'?'全部执行':item.data.purpose==='CONTEXT_COMPACTION'?'上下文摘要':'Agent 推理' }}</dd><dt>输入 / 输出 Token</dt><dd>{{ tokens(item.data.inputTokens) }} / {{ tokens(item.data.outputTokens) }}</dd><dt>数据依据</dt><dd>{{ item.data.basis==='PROVIDER_REPORTED'?'供应商报告':'供应商用量未知' }}</dd><dt>模型 / 首响应耗时</dt><dd>{{ tokens(item.data.durationMs) }} / {{ tokens(item.data.firstContentMs) }} ms</dd><dt>系统 / 工具 / 历史估算（非账单）</dt><dd>{{ tokens(item.data.systemTokens) }} / {{ tokens(item.data.toolsTokens) }} / {{ tokens(item.data.messageTokens) }}</dd></dl>
    <dl v-if="item.kind==='CONTEXT'"><dt>上下文压缩</dt><dd>{{ item.data.phase }}</dd><dt>压缩前 / 后字符数</dt><dd>{{ tokens(item.data.beforeChars) }} / {{ tokens(item.data.afterChars) }}</dd></dl>
    <p v-if="item.kind==='TOOL_TIMING'">工具批次耗时 {{ tokens(item.data.durationMs) }} ms</p>
    <div v-if="item.status==='NEEDS_REVIEW'"><p class="wb-note">恢复会重新鉴权，未知写结果不会自动重做</p><button :disabled="busy" @click="act(item,'resume')">确认从检查点恢复</button><button :disabled="busy" @click="act(item,'cancel')">结束任务</button></div>
   </article>
   <p v-if="!rows.length" class="wb-note">当前视图暂无记录</p>
  </template>
  <el-dialog v-model="previewOpen" title="文件预览" append-to-body width="min(900px,90vw)"><img v-if="previewType==='image'" :src="previewUrl" class="wb-preview-image" alt="本人工作区图片"/><iframe v-else-if="previewType==='pdf'" :src="previewUrl" sandbox="" title="PDF 预览" class="wb-preview-frame"/><pre v-else>{{ previewText }}</pre></el-dialog>
 </section>
</template>
<script setup>
import {ref,reactive,computed,watch,onBeforeUnmount} from 'vue'
import {AgentWorkbenchClient,availableWorkbenchTabs,workbenchStatus,workbenchRows,tokenDisplay} from '@/utils/agentWorkbench'
import '@/assets/agent-workbench.css'
const props=defineProps({sessionId:String,messages:{type:Array,default:()=>[]}})
const emit=defineEmits(['reference'])
const state=ref({enabled:false,items:[],files:[],capabilities:{}}),tab=ref('PLAN'),error=ref(''),busy=ref(false),drafts=reactive({}),selections=reactive({})
const previewOpen=ref(false),previewUrl=ref(''),previewText=ref(''),previewType=ref('text')
const businessKind=ref('DETECTION'),businessId=ref('')
const client=new AgentWorkbenchClient({base:(import.meta.env.VITE_API_URL||'').replace(/\/$/,''),onState:value=>{state.value=value;for(const item of value.items)if(item.kind==='QUESTION'&&item.data.questionType==='MULTIPLE'&&!selections[item.id])selections[item.id]=[]}})
const tabs=computed(()=>availableWorkbenchTabs(state.value.capabilities)),status=workbenchStatus,tokens=tokenDisplay,rows=computed(()=>workbenchRows(state.value.items,tab.value)),completedMessages=computed(()=>props.messages.filter(message=>message.role==='assistant'&&message.id).slice(-20))
watch(()=>props.sessionId,session=>{error.value='';previewOpen.value=false;client.open(session)},{immediate:true})
onBeforeUnmount(()=>{client.close();if(previewUrl.value)URL.revokeObjectURL(previewUrl.value)})
async function run(action){const session=props.sessionId;busy.value=true;error.value='';try{const result=await action();return props.sessionId===session?result:undefined}catch(cause){if(props.sessionId===session)error.value=cause.message}finally{busy.value=false}}
async function act(item,action,input){await run(()=>client.command(item,action,input));}
function sessionHref(id){return '#/agent/chat?sessionId='+encodeURIComponent(id)}
async function fork(id){const result=await run(()=>client.fork(id));if(result)window.location.assign(sessionHref(result.sessionId))}
async function upload(event){const file=event.target.files?.[0];if(file)await run(()=>client.upload(file));event.target.value=''}
async function copyReference(file){await run(()=>navigator.clipboard.writeText('@file:'+file.id));}
function insertReference(file){emit('reference','@file:'+file.id)}
async function preview(file){await run(async()=>{const blob=await client.content(file);if(previewUrl.value)URL.revokeObjectURL(previewUrl.value);previewType.value=file.contentType.startsWith('image/')?'image':file.contentType==='application/pdf'?'pdf':'text';if(previewType.value==='text')previewText.value=await blob.slice(0,state.value.limits?.previewBytes||64000).text();else previewUrl.value=URL.createObjectURL(blob);previewOpen.value=true})}
async function download(file){await run(async()=>{const blob=await client.content(file),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=file.name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)})}
async function previewBusiness(file){await run(async()=>{if(previewUrl.value)URL.revokeObjectURL(previewUrl.value);if(file.contentType.startsWith('image/')){previewType.value='image';previewUrl.value=client.base+file.previewPath}else{previewType.value='text';const response=await client.read(file.previewPath);previewText.value=(await response.text()).slice(0,state.value.limits?.previewBytes||64000)}previewOpen.value=true})}
</script>
