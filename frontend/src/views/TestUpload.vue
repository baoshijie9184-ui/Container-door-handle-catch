<template>
  <div class="page-shell form-page compatibility-upload-page">
    <PageHero icon="Operation" title="兼容上传诊断" description="核对兼容上传入口的参数与受理回执。发送会保存图片并创建异步检测任务。"><template #actions><el-button :disabled="busy" @click="$router.push('/inspection/workbench')"><AppIcon name="ArrowRight" :size="16" />正式检测工作台</el-button></template></PageHero>
    <p class="management-scope-note"><AppIcon name="Warning" :size="16" /><span>此页为隐藏的辅助入口。完整采集信息、上传进度及质检流程请使用正式工作台；兼容回执不代表推理、人工复核或报告审批完成。</span></p>
    <section class="test-upload-surface app-panel">
      <el-form id="compatibility-upload-form" :model="form" :rules="rules" ref="formRef" label-position="top" scroll-to-error :disabled="busy || !!proposal || attempted || !userStore.isAuthenticated" @submit.prevent="prepareRequest">
        <div class="test-upload-layout">
          <section aria-labelledby="compatibility-files-heading"><h2 id="compatibility-files-heading"><AppIcon name="Picture" :size="19" />待发送图片</h2><p class="test-upload-note">已选择 {{ fileList.length }} 张 · {{ totalBytesLabel }}</p>
            <el-form-item label="选择图片"><el-upload ref="uploadRef" :auto-upload="false" :disabled="busy || !!proposal || attempted || !userStore.isAuthenticated" v-model:file-list="fileList" multiple accept=".jpg,.jpeg,.png,.bmp" list-type="picture-card"><span class="test-upload-trigger"><AppIcon name="Plus" :size="22" /><span>选择图片</span></span></el-upload><p class="test-upload-note">此兼容入口支持 JPG、PNG、BMP。单张大小与批量数量限制以当前接口校验为准。</p></el-form-item>
          </section>
          <section aria-labelledby="compatibility-parameters-heading"><h2 id="compatibility-parameters-heading"><AppIcon name="Operation" :size="19" />请求参数</h2>
            <el-form-item label="检测模型编号" prop="modelId"><el-input ref="modelInput" v-model="form.modelId" inputmode="numeric" placeholder="填写已登记的兼容模型编号" /><p class="test-upload-note">不预填或推断默认模型，<router-link to="/models">查看模型登记</router-link>后核对实际兼容性。</p></el-form-item>
            <el-form-item label="输出格式" prop="outputFormat"><el-radio-group v-model="form.outputFormat"><el-radio label="YOLO">YOLO</el-radio><el-radio label="COCO">COCO</el-radio></el-radio-group></el-form-item>
            <el-form-item label="置信度阈值" prop="confidenceThreshold"><el-slider v-model="form.confidenceThreshold" :min="0.1" :max="1" :step="0.05" aria-label="置信度阈值" /><p class="test-upload-note">本次拟用阈值 {{ thresholdLabel }}，不修改其他任务或模型登记。</p></el-form-item>
          </section>
        </div>
      </el-form>
      <el-alert v-if="submitError" :type="uncertain ? 'warning' : 'error'" :title="submitError" show-icon :closable="false" />
      <Transition name="compatibility-review"><section v-if="proposal" ref="proposalRef" tabindex="-1" class="test-upload-review" aria-label="确认创建兼容检测任务"><h3><AppIcon name="DocumentChecked" :size="18" />核对本次检测请求</h3><dl class="test-upload-facts"><div><dt>当前登录账号</dt><dd>{{ proposal.account }}</dd></div><div><dt>图片数量</dt><dd>{{ proposal.files.length }} 张</dd></div><div><dt>模型编号</dt><dd>{{ proposal.modelId }}</dd></div><div><dt>输出格式 / 阈值</dt><dd>{{ proposal.outputFormat }} / {{ proposal.confidenceThreshold.toFixed(2) }}</dd></div></dl><details class="test-upload-file-names"><summary>核对所选文件名称</summary><ul><li v-for="(file,index) in proposal.files" :key="index">{{ file.name }}</li></ul></details><p class="test-upload-note">确认后将保存这些图片，创建检测任务并登记模型使用。任务继续异步执行，不自动完成质检或报告审批。</p><div class="test-upload-actions"><el-button :disabled="busy" @click="backToEdit">返回修改</el-button><el-button type="primary" :loading="busy" @click="sendRequest"><AppIcon name="Upload" :size="16" />确认上传并创建任务</el-button></div></section></Transition>
      <div v-if="!proposal" class="test-upload-actions"><el-button type="primary" native-type="submit" form="compatibility-upload-form" :disabled="attempted || !userStore.isAuthenticated" :loading="phase==='VALIDATING'"><AppIcon name="Search" :size="16" />核对请求</el-button><el-button :disabled="busy || uncertain" @click="resetForm"><AppIcon name="Refresh" :size="16" />{{ attempted ? '开始新的选择' : '恢复初始值' }}</el-button></div>
      <p v-if="busy" class="test-upload-progress" role="status"><AppIcon name="Connection" :size="16" />{{ phase==='VALIDATING' ? '正在核对输入，尚未发送请求' : phase==='WAITING' ? '请求体已发送，正在等待受理回执，请保留此页' : '正在发送请求体，尚未确认任务创建结果，请保留此页' }}</p>
      <div v-if="requestId" class="test-upload-request"><span>本次请求编号</span><code>{{ requestId }}</code><span v-if="receivedAt">回执读取时间 {{ receivedAt }}（UTC+8）</span></div>
      <section v-if="response !== null" class="response-container" aria-label="最近一次兼容接口回执">
        <div class="test-response-heading"><h3><AppIcon name="Document" :size="18" />接口回执</h3><StatusBadge domain="apiReceipt" :code="responseCode" :label="responseCode==='SUCCEEDED' ? '已确认受理回执' : undefined" /></div>
        <dl v-if="receipt" class="test-upload-facts"><div><dt>登记序号</dt><dd>{{ receipt.id }}</dd></div><div><dt>回执中的任务状态</dt><dd><StatusBadge domain="detection" :code="receipt.status" /></dd></div><div><dt>回执模型编号</dt><dd>{{ receipt.modelId }}</dd></div><div><dt>回执登记图片数</dt><dd>{{ receipt.images??'未记录' }}</dd></div></dl>
        <p class="test-upload-note">受理回执不是推理完成证据。此入口返回的数值序号不是工单号或业务任务号，请到检测记录核对实际进度。</p><div class="test-upload-links"><router-link to="/inspection/history"><AppIcon name="Tickets" :size="15" />查看检测记录</router-link><router-link to="/operations/audit"><AppIcon name="DocumentChecked" :size="15" />查看操作审计</router-link></div>
        <details v-if="receipt" class="test-upload-raw"><summary>展开已核对的回执字段（纯文本）</summary><pre tabindex="0" aria-label="已核对的受理回执字段">{{ JSON.stringify(receipt,null,2) }}</pre></details>
      </section>
    </section>
  </div>
</template>

<script setup>
import { ref,reactive,computed,nextTick,watch,onBeforeUnmount } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import request from '../api/request'
import { useUserStore } from '../stores/user'
import { validResourceId } from '../utils/agentCards'
import { createUiRequestId } from '../utils/requestIdentity'
import { beijingDateTime } from '../utils/beijingTime'
const userStore=useUserStore(),formRef=ref(null),uploadRef=ref(null),modelInput=ref(null),proposalRef=ref(null)
const actor=computed(()=>JSON.stringify([userStore.identity?.userId || userStore.username || '',userStore.role,userStore.isAuthenticated]))
const fileList=ref([]),response=ref(null),receipt=ref(null),phase=ref('IDLE'),proposal=ref(null),attempted=ref(false),uncertain=ref(false),submitError=ref(''),responseCode=ref('UNKNOWN'),requestId=ref(''),receivedAt=ref('')
const defaults=()=>({modelId:'',outputFormat:'YOLO',confidenceThreshold:0.5}),form=reactive(defaults())
const busy=computed(()=>phase.value!=='IDLE')
const thresholdLabel=computed(()=>typeof form.confidenceThreshold==='number' && Number.isFinite(form.confidenceThreshold)?form.confidenceThreshold.toFixed(2):'尚未核对')
const byteCount=value=>!Number.isSafeInteger(value) || value<0?'大小未完整读取':value>=1048576?(value/1048576).toFixed(1)+' MiB':(value/1024).toFixed(1)+' KiB'
const totalBytesLabel=computed(()=>fileList.value.every(file=>Number.isSafeInteger(file.raw?.size) && file.raw.size>=0)?byteCount(fileList.value.reduce((sum,file)=>sum+file.raw.size,0)):'大小未完整读取')
let generation=0,disposed=false
const current=(version,stamp)=>!disposed && generation===version && actor.value===stamp
const rules={modelId:[{required:true,message:'请填写模型编号',trigger:'blur'},{validator:(_rule,value,callback)=>callback(!value || validResourceId(String(value),'MODELS')?undefined:new Error('请填写有效的正整数模型编号')),trigger:'blur'}],outputFormat:[{required:true,message:'请选择输出格式',trigger:'change'}]}
async function prepareRequest(){
  if(disposed || busy.value || attempted.value || proposal.value || !userStore.isAuthenticated || !formRef.value)return
  const version=++generation,stamp=actor.value
  phase.value='VALIDATING';submitError.value=''
  try{
    const valid=await formRef.value.validate().catch(()=>false)
    if(!current(version,stamp) || !valid)return
    if(!fileList.value.length)throw new Error('请选择至少一张图片')
    const files=fileList.value.map(item=>item.raw)
    if(files.some(file=>!file || !Number.isSafeInteger(file.size) || file.size<=0 || !/\.(jpe?g|png|bmp)$/i.test(file.name)))throw new Error('请选择已完整读取的非空 JPG、PNG 或 BMP 图片')
    if(!['YOLO','COCO'].includes(form.outputFormat) || !Number.isFinite(form.confidenceThreshold) || form.confidenceThreshold<0.1 || form.confidenceThreshold>1)throw new Error('请核对输出格式与本次阈值')
    proposal.value=Object.freeze({files:Object.freeze([...files]),modelId:form.modelId,outputFormat:form.outputFormat,confidenceThreshold:form.confidenceThreshold,account:userStore.username || '账号未记录',version,stamp})
    await nextTick()
    if(current(version,stamp))proposalRef.value?.focus()
  }catch(error){if(current(version,stamp))submitError.value=error.message || '输入未核对完成，尚未发送'}
  finally{if(current(version,stamp))phase.value='IDLE'}
}
function backToEdit(){if(busy.value)return;proposal.value=null;nextTick(()=>{if(!disposed)modelInput.value?.focus()})}
async function sendRequest(){
  const target=proposal.value
  if(!target || busy.value || attempted.value || !userStore.isAuthenticated || !current(target.version,target.stamp))return
  let sent=false
  phase.value='SENDING';submitError.value='';response.value=null;receipt.value=null;responseCode.value='UNKNOWN';receivedAt.value=''
  try{
    const body=new FormData()
    target.files.forEach(file=>body.append('files',file));body.append('modelId',target.modelId);body.append('outputFormat',target.outputFormat);body.append('confidenceThreshold',String(target.confidenceThreshold))
    requestId.value=createUiRequestId();attempted.value=true;sent=true
    const result=await request.post('/api/detection/upload',body,{headers:{'Content-Type':'multipart/form-data','X-Request-ID':requestId.value},onUploadProgress:event=>{if(current(target.version,target.stamp) && phase.value==='SENDING' && Number.isFinite(event.total) && event.total>0 && event.loaded>=event.total)phase.value='WAITING'}})
    if(!current(target.version,target.stamp))return
    response.value=result.data??{message:'接口未提供可核对的响应正文'};receivedAt.value=beijingDateTime()
    if(result.data?.code!==200){const error=new Error(result.data?.message || '接口未确认受理');error.status=result.data?.code;throw error}
    const data=result.data?.data,id=data?.id,key=typeof id==='number' && Number.isSafeInteger(id) && id>0?String(id):typeof id==='string' && /^[1-9]\d*$/.test(id)?id:''
    if(!key || String(data.modelId)!==target.modelId){const error=new Error('未收到可核对的登记序号或模型编号');error.unknown=true;throw error}
    receipt.value=Object.freeze({id:key,status:data.status,modelId:data.modelId,images:Number.isSafeInteger(data.detectedImagesCount) && data.detectedImagesCount>=0?data.detectedImagesCount:null});responseCode.value='SUCCEEDED'
  }catch(error){
    if(!current(target.version,target.stamp))return
    const status=error.response?.status || error.status
    uncertain.value=sent && (!!error.unknown || !status || status>=500 || status===408)
    if(response.value===null && sent){response.value=error.response?.data || {message:error.message || '接口回执未返回'};receivedAt.value=beijingDateTime()}
    responseCode.value=uncertain.value?'UNKNOWN':'REJECTED'
    submitError.value=uncertain.value?'创建结果待核对，请保留请求编号，到检测记录及操作审计核对。当前页面不再次发送本次图片。':(error.response?.data?.message || error.message || '请求未完成')+(sent?'；接口未确认受理。':'；尚未发送请求。')
  }finally{if(current(target.version,target.stamp)){phase.value='IDLE';proposal.value=null}}
}
async function resetForm(){
  if(busy.value || uncertain.value || disposed)return
  const version=generation,stamp=actor.value
  if(fileList.value.length || attempted.value || form.modelId || proposal.value){try{await ElMessageBox.confirm('恢复初始值会清除本页文件选择与回执展示，服务器任务和文件不因此删除。','核对本页选择',{confirmButtonText:'清除本页选择',cancelButtonText:'保留当前内容',type:'warning'})}catch{return}}
  if(!current(version,stamp))return
  generation++;proposal.value=null;uploadRef.value?.clearFiles();fileList.value=[];Object.assign(form,defaults());attempted.value=false;response.value=null;receipt.value=null;submitError.value='';responseCode.value='UNKNOWN';requestId.value='';receivedAt.value='';formRef.value?.clearValidate()
}
onBeforeRouteLeave(async()=>{
  if(!userStore.isAuthenticated)return true
  if(busy.value)return false
  if(!uncertain.value && !fileList.value.length && !proposal.value && !form.modelId)return true
  const version=generation,stamp=actor.value
  try{await ElMessageBox.confirm(uncertain.value?'创建结果仍待核对，离开不会取消已接收的任务；请保留请求编号后核对。':'离开会丢弃本页选择与展示，已提交的服务器任务不会被取消。','核对当前请求',{confirmButtonText:'离开页面',cancelButtonText:'留在此页',type:'warning'});return true}catch{return !current(version,stamp)}
})
watch(actor,()=>{generation++;phase.value='IDLE';proposal.value=null;attempted.value=false;uncertain.value=false;response.value=null;receipt.value=null;requestId.value='';receivedAt.value='';submitError.value='';uploadRef.value?.clearFiles();fileList.value=[];Object.assign(form,defaults())},{flush:'sync'})
onBeforeUnmount(()=>{disposed=true;generation++})
</script>

<style scoped>
.compatibility-upload-page { gap:18px; }
.test-upload-surface { padding:22px; border:1px solid var(--app-border); border-radius:12px; background:#fff; }
.test-upload-layout { display:grid; grid-template-columns:minmax(0,1.3fr) minmax(0,1fr); gap:28px; }
.test-upload-layout > section { min-width:0; }
.test-upload-layout h2,.test-response-heading h3,.test-upload-review h3 { display:flex; align-items:center; gap:8px; margin:0 0 18px; color:var(--app-text); font-size:16px; font-weight:600; line-height:1.7; }
.test-upload-layout h2 .el-icon,.test-response-heading h3 .el-icon,.test-upload-review h3 .el-icon { color:var(--app-primary); flex-shrink:0; }
.test-upload-note { margin:8px 0 16px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; overflow-wrap:anywhere; }
.test-upload-note a { color:var(--app-primary); text-underline-offset:3px; }
.test-upload-trigger { display:grid; place-items:center; gap:8px; font-size:12px; line-height:1.7; }
.test-upload-review { border-top:1px solid var(--app-border); padding-top:20px; outline-offset:4px; }
.test-upload-facts { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px 24px; margin:18px 0; }
.test-upload-facts > div { min-width:0; }
.test-upload-facts dt { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.test-upload-facts dd { margin:6px 0 0; color:var(--app-text); font-size:13px; line-height:1.8; overflow-wrap:anywhere; }
.test-upload-actions { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:8px; padding-top:16px; }
.test-upload-actions .el-button + .el-button { margin-left:0; }
.test-upload-progress { display:flex; align-items:flex-start; gap:8px; margin:16px 0; padding:12px 14px; border-radius:8px; background:var(--app-primary-soft); color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.test-upload-progress .el-icon { color:var(--app-primary); flex-shrink:0; margin-top:3px; }
.test-upload-request { display:flex; align-items:center; flex-wrap:wrap; gap:7px 12px; margin:18px 0; color:var(--app-text-secondary); font-size:12px; line-height:1.85; overflow-wrap:anywhere; }
.test-response-heading { display:flex; align-items:center; flex-wrap:wrap; gap:10px; }
.test-response-heading h3 { margin:0; }
.response-container { border-top:1px solid var(--app-border); padding-top:22px; margin-top:22px; }
.test-upload-links { display:flex; flex-wrap:wrap; gap:10px 18px; }
.test-upload-links a { display:inline-flex; align-items:center; gap:6px; color:var(--app-primary); font-size:12px; line-height:1.85; text-decoration:none; }
.test-upload-raw,.test-upload-file-names { margin-top:18px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.test-upload-file-names ul { max-height:220px; overflow-y:auto; padding-left:20px; overflow-wrap:anywhere; }
.test-upload-raw summary,.test-upload-file-names summary { width:fit-content; cursor:pointer; }
.test-upload-raw pre { max-height:420px; padding:14px; overflow:auto; color:var(--app-text); background:var(--app-bg); font:12px/1.85 var(--app-font-mono,Consolas,monospace); white-space:pre-wrap; overflow-wrap:anywhere; border-radius:8px; }
.test-upload-surface :is(a,summary,[tabindex]):focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
.compatibility-review-enter-active,.compatibility-review-leave-active { transition:opacity 180ms ease,transform 180ms ease; }
.compatibility-review-enter-from,.compatibility-review-leave-to { opacity:0;transform:translateY(3px); }
@media(max-width:780px) { .test-upload-layout { grid-template-columns:minmax(0,1fr); gap:20px; } }
@media(max-width:540px) { .test-upload-surface { padding:18px 16px; } .test-upload-facts { grid-template-columns:minmax(0,1fr); } }
@media(prefers-reduced-motion:reduce) { .compatibility-review-enter-active,.compatibility-review-leave-active { transition:none;transform:none; } }
</style>
