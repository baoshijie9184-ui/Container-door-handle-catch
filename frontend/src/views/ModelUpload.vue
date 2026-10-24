<template>
  <div class="page-shell model-upload-container">
    <PageHero icon="Upload" title="上传检测模型" description="上传支持的模型文件，填写版本说明并查看登记结果。"><template #actions><ModelFileJournal ref="fileJournal" /><el-button :disabled="loading" @click="$router.push('/models')"><AppIcon name="ArrowLeft" />返回模型列表</el-button></template></PageHero>
    <el-alert v-if="userStore.hasCheckedAuth && !isSupervisor" title="仅已登录的主管可上传检测模型，请返回列表核对当前账号。" type="warning" show-icon :closable="false" /><el-card class="upload-card">
      <div class="model-upload-guidance"><span class="model-upload-symbol"><AppIcon name="Upload" :size="24" /></span><div><h2>登记新的检测模型</h2><p>选择文件并填写版本信息，上传后核对基础校验结果。模型发布与默认设置在模型列表操作。</p></div></div>
      <el-form :model="form" :rules="rules" ref="uploadFormRef" scroll-to-error label-position="top" :disabled="loading || uploadUncertain || !isSupervisor" @submit.prevent="submitUpload">
        <h3 class="model-upload-section">模型文件</h3>
        <el-form-item label="模型文件" prop="file">
          <el-upload
            class="upload-demo"
            ref="uploadRef"
            drag
            :auto-upload="false"
            :show-file-list="false"
            :disabled="loading || uploadUncertain || !isSupervisor"
            :limit="1"
            :on-change="handleFileChange"
            :on-exceed="handleExceed"
            :on-remove="handleRemove"
            accept=".onnx"
          >
            <el-icon class="el-icon--upload"><upload-filled /></el-icon>
            <div class="el-upload__text">
              拖拽 ONNX 文件到此处或 <em>选择文件</em>
            </div>
            <template #tip>
              <div class="el-upload__tip">
                单个 .onnx 文件，最多 500 MiB；基础校验通过不代表已发布或完成模型评估。
              </div>
            </template>
          </el-upload>
        </el-form-item>
        <p v-if="form.file" class="model-selected-file"><AppIcon name="Document" :size="16" /><strong>{{ form.file.name }}</strong><span>{{ fileSize(form.file.size) }}</span><el-button text type="danger" :disabled="loading || uploadUncertain || !isSupervisor" @click="removeSelectedFile"><AppIcon name="Close" :size="14" />移除选择</el-button></p>
        <h3 class="model-upload-section">名称与版本</h3>
        <div class="model-metadata-grid">
        <el-form-item label="模型名称" prop="modelName">
          <el-input v-model="form.modelName" placeholder="请输入模型名称"></el-input>
        </el-form-item>

        <el-form-item label="版本号" prop="version">
          <el-input v-model="form.version" placeholder="请输入版本号"></el-input>
        </el-form-item>
        </div>
        <el-form-item label="更新说明">
          <el-input type="textarea" :rows="4" v-model="form.updateDescription" placeholder="说明本版本的用途、变更和适用范围"></el-input>
        </el-form-item>

        <el-form-item class="model-upload-actions">
          <el-button type="primary" native-type="submit" :loading="loading" :disabled="uploadUncertain || !isSupervisor"><AppIcon name="Upload" :size="16" />上传并登记</el-button>
          <span>登记完成后仍需核对校验与发布状态</span>
        </el-form-item>

        <!-- 上传进度 -->
        <Transition name="model-progress"><div v-if="loading" class="model-upload-progress" role="status" aria-live="polite"><el-progress v-if="uploadProgress!==null" :percentage="uploadProgress" :stroke-width="8" /><p><AppIcon name="Connection" :size="15" />{{ phase==='VALIDATING' ? '正在检查填写内容，尚未发送文件' : phase==='WAITING' ? '浏览器已发送请求体，正在等待模型登记回执' : uploadProgress===null ? `正在发送或等待回执，总量尚未核对${uploadBytes===null ? '' : '；已发送 '+fileSize(uploadBytes)}` : '正在发送模型文件，请保留当前页面' }}</p></div></Transition>
      </el-form>
      <el-alert v-if="uploadError" :title="uploadError" :type="uploadUncertain ? 'warning' : 'error'" show-icon :closable="false" class="model-upload-error" />
      <p v-if="uploadRequestId" class="model-upload-receipt">本次请求编号 <code>{{ uploadRequestId }}</code><el-button text type="primary" :disabled="!isSupervisor" @click="fileJournal?.openForRequest(uploadRequestId)"><AppIcon name="Search" :size="14" />按此编号查询文件记录</el-button></p>
      <div v-if="lastUploadResult" class="result-panel" aria-label="最近一次已确认的上传结果">
        <div class="result-header">
          <div>
            <div class="result-label">最近一次已确认结果</div>
            <h3>{{ lastUploadResult.modelName || '名称未记录' }} <span>版本 {{ lastUploadResult.version || '未记录' }}</span></h3>
          </div>
          <StatusBadge domain="modelValidation" :code="lastUploadResult.validationStatus" />
        </div>

        <p class="model-result-context">已确认模型 ID {{ lastUploadResult.modelId }}，此处保留最近一次已确认的登记资料。</p><div class="result-grid">
          <div class="result-item">
            <span class="result-item-label">模型状态</span>
            <span class="result-item-value"><StatusBadge domain="model" :code="lastUploadResult.status" /></span>
          </div>
          <div class="result-item">
            <span class="result-item-label">上传人</span>
            <span class="result-item-value">{{ lastUploadResult.creator || '--' }}</span>
          </div>
          <div class="result-item">
            <span class="result-item-label">上传时间 · UTC+8</span>
            <span class="result-item-value">{{ formatDateTime(lastUploadResult.uploadTime) || '--' }}</span>
          </div>
          <div class="result-item">
            <span class="result-item-label">下一步建议</span>
            <span class="result-item-value">{{ nextStepText(lastUploadResult) }}</span>
          </div>
        </div>

        <div class="result-block">
          <div class="result-item-label">校验说明</div>
          <div class="result-message">{{ lastUploadResult.validationMessage || '暂无校验说明' }}</div>
        </div>

        <details class="result-block model-storage-disclosure">
          <summary class="result-item-label">存储资料</summary>
          <div class="result-message">{{ lastUploadResult.modelPath || '--' }}</div>
        </details>
        <div class="model-result-actions"><el-button :disabled="loading" type="primary" plain @click="$router.push('/models')"><AppIcon name="ArrowRight" :size="16" />查看模型列表</el-button></div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive,ref,computed,watch,onBeforeUnmount } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage,ElMessageBox,ElNotification } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import request from '../api/request'
import { beijingDateTime } from '@/utils/beijingTime'
import { useUserStore } from '@/stores/user'
import { validResourceId } from '@/utils/agentCards'
import { createUiRequestId } from '@/utils/requestIdentity'
import ModelFileJournal from '@/components/ModelFileJournal.vue'
const userStore=useUserStore()
const actor=computed(()=>JSON.stringify([userStore.identity?.userId || userStore.username || '',userStore.role,userStore.isAuthenticated]))
const isSupervisor=computed(()=>userStore.isAuthenticated && userStore.role==='SUPERVISOR')
const uploadFormRef=ref(null),uploadRef=ref(null),fileJournal=ref(null),phase=ref('IDLE')
const loading=computed(()=>phase.value!=='IDLE')
const uploadProgress=ref(null),uploadBytes=ref(null),lastUploadResult=ref(null),uploadError=ref(''),uploadUncertain=ref(false),uploadRequestId=ref('')
const form=reactive({file:null,modelName:'',version:'',updateDescription:''})
let generation=0,disposed=false
const current=(version,stamp)=>!disposed && generation===version && actor.value===stamp
const fileSize=value=>!Number.isFinite(value) || value<0 ? '大小未知' : value<1048576?`${(value/1024).toFixed(1)} KiB`:`${(value/1048576).toFixed(1)} MiB`
const formatDateTime=value=>value?beijingDateTime(value) || '时间格式未知':'未记录'
const rules={file:[{required:true,message:'请选择 ONNX 模型文件',trigger:'change'}],modelName:[{required:true,message:'请输入模型名称',trigger:'blur'}],version:[{required:true,message:'请输入版本号',trigger:'blur'}]}
function fileError(file){
  if(!file || typeof file.name!=='string' || !file.name.toLowerCase().endsWith('.onnx'))return '当前上传入口仅支持单个 .onnx 模型文件'
  if(!Number.isFinite(file.size) || file.size<=0 || file.size>500*1024*1024)return '请选择非空模型文件，大小不能超过 500 MiB'
  return ''
}
function handleFileChange(file){
  if(loading.value || uploadUncertain.value || !isSupervisor.value)return false
  const message=fileError(file.raw)
  if(message){uploadError.value=message;uploadRef.value?.clearFiles();form.file=null;return false}
  form.file=file.raw;uploadError.value=''
}
const handleExceed=()=>{if(!loading.value && !uploadUncertain.value)uploadError.value='一次只能选择一个模型文件，请先移除现有文件。'}
const handleRemove=()=>{if(!loading.value && !uploadUncertain.value)form.file=null}
function removeSelectedFile(){if(loading.value || uploadUncertain.value || !isSupervisor.value)return;uploadRef.value?.clearFiles();form.file=null;uploadFormRef.value?.clearValidate('file')}
const nextStepText=model=>model.validationStatus==='FAILED'?'文件已登记但基础校验未通过，请先核对校验说明':model.status==='PUBLISHED'?'已发布，具体任务使用版本以任务记录为准':'前往模型列表核对基础校验、评估资料、发布和默认设置'
async function submitUpload(){
  if(disposed || loading.value || uploadUncertain.value || !isSupervisor.value || !uploadFormRef.value)return
  const version=++generation,stamp=actor.value
  phase.value='VALIDATING';uploadError.value='';uploadProgress.value=null;uploadBytes.value=null;uploadRequestId.value=''
  let sent=false
  try{
    const valid=await uploadFormRef.value.validate().catch(()=>false)
    if(!current(version,stamp) || !isSupervisor.value)return
    if(!valid){uploadError.value='请核对已标记的字段，尚未发送文件。';return}
    const message=fileError(form.file)
    if(message)throw new Error(message)
    const payload=Object.freeze({file:form.file,modelName:form.modelName,version:form.version,updateDescription:form.updateDescription})
    const body=new FormData()
    body.append('file',payload.file);body.append('modelName',payload.modelName);body.append('version',payload.version);body.append('updateDescription',payload.updateDescription)
    uploadRequestId.value=createUiRequestId()
    phase.value='SENDING';sent=true
    const response=await request.post('/api/models/upload',body,{
      headers:{'Content-Type':'multipart/form-data','X-Request-ID':uploadRequestId.value},
      onUploadProgress:event=>{
        if(!current(version,stamp) || !['SENDING','WAITING'].includes(phase.value))return
        if(Number.isFinite(event.loaded) && event.loaded>=0)uploadBytes.value=event.loaded
        if(Number.isFinite(event.total) && event.total>0 && Number.isFinite(event.loaded) && event.loaded>=0){
          uploadProgress.value=Math.max(0,Math.min(100,Math.floor(event.loaded*100/event.total)))
          if(event.loaded>=event.total)phase.value='WAITING'
        }
      }
    })
    if(!current(version,stamp))return
    const data=response.data?.data
    if(response.data?.code!==200){const error=new Error(response.data?.message || '模型登记回执未确认');error.status=response.data?.code;throw error}
    if(!data || typeof data!=='object' || Array.isArray(data) || !validResourceId(String(data.modelId),'MODELS')){const error=new Error('未收到可核对的模型编号');error.unknown=true;throw error}
    lastUploadResult.value=Object.freeze({...data})
    ElNotification({type:data.validationStatus==='FAILED'?'warning':'success',title:data.validationStatus==='FAILED'?'模型已登记，基础校验失败':'已收到模型登记回执',message:data.validationMessage || '请核对模型状态、校验说明和后续发布操作',duration:3000})
    uploadRef.value?.clearFiles();Object.assign(form,{file:null,modelName:'',version:'',updateDescription:''});uploadFormRef.value?.clearValidate()
  }catch(error){
    if(!current(version,stamp))return
    const status=error.response?.status || error.status
    uploadUncertain.value=sent && (!!error.unknown || !status || status>=500 || status===408)
    uploadError.value=uploadUncertain.value?'上传登记结果待核对，当前页面不再次提交。请按本次请求编号查询文件记录及模型列表，不要直接重新上传。':`${error.response?.data?.message || error.message || '文件未完成登记'}${sent?'；接口未确认登记成功。':'；尚未发送文件。'}`
  }finally{if(current(version,stamp))phase.value='IDLE'}
}
onBeforeRouteLeave(async()=>{
  if(!isSupervisor.value)return true
  if(loading.value){ElMessage.warning('模型正在校验、上传或等待回执，请保留当前页面');return false}
  if(!uploadUncertain.value && !form.file && !form.modelName && !form.version && !form.updateDescription)return true
  const version=generation,stamp=actor.value
  try{await ElMessageBox.confirm(uploadUncertain.value?'上传结果仍待核对，离开不会取消服务器操作；请保留请求编号，之后在文件记录核对。':'当前文件选择与填写内容尚未登记，离开会丢弃本页草稿。','核对上传状态',{confirmButtonText:'离开页面',cancelButtonText:'留在此页',type:'warning'});return true}catch{return !current(version,stamp)}
})
watch(actor,()=>{generation++;phase.value='IDLE';uploadProgress.value=null;uploadBytes.value=null;lastUploadResult.value=null;uploadError.value='';uploadUncertain.value=false;uploadRequestId.value='';Object.assign(form,{file:null,modelName:'',version:'',updateDescription:''});uploadRef.value?.clearFiles()},{flush:'sync'})
onBeforeUnmount(()=>{disposed=true;generation++})
</script>

<style scoped>
.model-upload-container { gap:18px; }
.upload-card { border:1px solid var(--app-border); border-radius:12px; box-shadow:none; }
.model-upload-guidance { display:flex; align-items:flex-start; gap:12px; margin-bottom:24px; padding-bottom:20px; border-bottom:1px solid var(--app-border); }
.model-upload-symbol { display:grid; place-items:center; flex:0 0 42px; height:42px; color:var(--app-primary); background:var(--app-primary-soft); border-radius:10px; }
.model-upload-guidance > div { min-width:0; }
.model-upload-guidance h2 { margin:0; color:var(--app-text); font-size:17px; font-weight:600; line-height:1.6; }
.model-upload-guidance p { margin:6px 0 0; color:var(--app-text-secondary); font-size:12px; line-height:1.9; overflow-wrap:anywhere; }
.model-upload-section { color:var(--app-text); font-size:15px; font-weight:600; margin:22px 0 16px; }
.upload-demo { width:100%; }
.upload-demo :deep(.el-upload-dragger) { padding:30px 20px; border-color:#c3d5f6; background:var(--app-bg); transition:border-color 180ms ease,background-color 180ms ease; }
.upload-demo :deep(.el-upload-dragger:hover),.upload-demo :deep(.el-upload-dragger:focus-within) { border-color:var(--app-primary); background:var(--app-primary-soft); }
.upload-demo :deep(.el-icon--upload) { color:var(--app-primary); margin-bottom:12px; font-size:44px; }
.upload-demo :deep(.el-upload__text) { color:var(--app-text-secondary); font-size:13px; line-height:1.85; }
.upload-demo :deep(.el-upload__tip) { color:var(--app-text-secondary); font-size:12px; line-height:1.9; }
.model-selected-file { display:flex; align-items:flex-start; flex-wrap:wrap; gap:8px 12px; padding:12px 14px; border-radius:8px; background:var(--app-primary-soft); font-size:12px; line-height:1.8; color:var(--app-text-secondary); }
.model-selected-file > .el-icon { color:var(--app-primary); flex-shrink:0; margin-top:3px; }
.model-selected-file strong { flex:1 1 180px; min-width:0; color:var(--app-text); font-weight:550; overflow-wrap:anywhere; }
.model-metadata-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 24px; }
.model-upload-actions :deep(.el-form-item__content) { gap:10px; }
.model-upload-actions :deep(.el-form-item__content > span) { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.model-upload-progress { padding:14px 16px; border-radius:9px; margin-bottom:20px; background:var(--app-primary-soft); }
.model-upload-progress p { display:flex; align-items:flex-start; gap:8px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; margin:8px 0 0; }
.model-upload-progress .el-icon { color:var(--app-primary); flex-shrink:0; margin-top:3px; }
.model-upload-error { margin:18px 0; overflow-wrap:anywhere; }
.model-upload-receipt { display:flex; align-items:center; flex-wrap:wrap; gap:8px 12px; margin:16px 0; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.model-upload-receipt code { overflow-wrap:anywhere; }
.result-panel { border-top:1px solid var(--app-border); margin-top:24px; padding-top:22px; }
.result-header { display:flex; align-items:flex-start; justify-content:space-between; flex-wrap:wrap; gap:14px; }
.result-header > div { min-width:0; }
.result-label { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.result-header h3 { color:var(--app-text); font-size:20px; font-weight:600; margin:6px 0 0; line-height:1.6; overflow-wrap:anywhere; }
.result-header h3 span { display:inline-block; margin-left:6px; color:var(--app-text-secondary); font-size:13px; font-weight:400; }
.model-result-context { margin:14px 0 18px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.result-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px 24px; }
.result-item { display:grid; gap:7px; min-width:0; }
.result-item-label { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.result-item-value,.result-message { color:var(--app-text); font-size:13px; line-height:1.85; overflow-wrap:anywhere; }
.result-block { margin-top:20px; }
.result-message { margin-top:6px; white-space:pre-wrap; }
.model-storage-disclosure summary { cursor:pointer; width:fit-content; }
.model-storage-disclosure summary:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
.model-result-actions { margin-top:20px; }
.model-progress-enter-active,.model-progress-leave-active { transition:opacity 200ms ease,transform 200ms ease; }
.model-progress-enter-from,.model-progress-leave-to { opacity:0;transform:translateY(3px); }
@media(max-width:640px) { .model-metadata-grid,.result-grid { grid-template-columns:minmax(0,1fr); } }
@media(prefers-reduced-motion:reduce) { .model-progress-enter-active,.model-progress-leave-active,.upload-demo :deep(.el-upload-dragger) { transition:none; } .model-progress-enter-from,.model-progress-leave-to { transform:none; } }
</style>
