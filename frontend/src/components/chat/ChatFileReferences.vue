<template>
 <section class="chat-file-references" aria-label="消息附件">
  <span v-if="loading" role="status">正在读取附件信息</span>
  <article v-for="file in files" :key="file.id" class="chat-file-card">
   <AppIcon :name="file.unavailable ? 'Lock' : composerAttachment(file).icon" :size="18" /><span class="chat-file-label">{{ file.unavailable?'资料已移除或无权访问':file.name }}<small v-if="!file.unavailable">{{ composerAttachment(file).type }} · {{ composerAttachment(file).size }}</small></span>
   <template v-if="!file.unavailable"><button type="button" :disabled="busy" @click="open(file)">预览</button><button type="button" :disabled="busy" @click="download(file)">下载</button></template>
  </article>
  <p v-if="error && !previewOpen" role="alert">{{ error }} <button type="button" :disabled="loading || busy" @click="load">重新读取</button></p>
  <el-dialog v-model="previewOpen" :title="previewFile?.name || '消息附件预览'" class="chat-reference-preview-dialog" append-to-body width="min(900px,90vw)">
   <p class="file-preview-meta"><AppIcon :name="composerAttachment(previewFile).icon" :size="18" /><span>{{ composerAttachment(previewFile).type }}</span><span>{{ composerAttachment(previewFile).size }}</span></p>
   <p v-if="error" class="chat-reference-preview-error" role="alert">{{ error }}</p>
   <p v-if="busy" role="status">正在读取文件，请稍候</p>
   <nav v-if="previewKind==='pdf'" ref="pdfNavigation" tabindex="-1" class="chat-file-pages" aria-label="PDF 页码"><button type="button" :disabled="busy||previewPage===1" @click="open(previewFile,previewPage-1)">上一页</button><span role="status">第 {{ previewPage }} / {{ previewPages }} 页</span><button type="button" :disabled="busy||previewPage===previewPages" @click="open(previewFile,previewPage+1)">下一页</button><small>页面预览 · Agent 仅可读取文字层</small></nav>
   <p class="chat-reference-preview-note">预览不执行文件内容；HTML/SVG 仅展示源码，PDF 显示页面图片。</p>
   <AgentFileImage v-if="previewOpen&&['image','pdf'].includes(previewKind)" :src="previewUrl" :name="previewFile?.name" :kind="previewKind" :busy="busy" downloadable /><pre v-else-if="previewOpen" class="chat-file-preview-text" tabindex="0" aria-label="附件文本或源码预览">{{ previewText }}</pre>
   <template #footer><div class="file-preview-actions"><el-button @click="previewOpen=false">关闭预览</el-button><el-button type="primary" :disabled="busy || !previewFile" @click="download(previewFile)"><AppIcon name="Download" :size="15" />下载原文件</el-button></div></template>
  </el-dialog>
 </section>
</template>
<script setup>
import {ref,computed,watch,onBeforeUnmount,nextTick} from 'vue'
import {useUserStore} from '@/stores/user'
import {composerAttachment} from '@/utils/composerPresentation'
import AgentFileImage from './AgentFileImage.vue'
import {referencedFiles,readReferencedFile,readFilePreview} from '@/utils/chatFileReferences'
import '@/assets/chat-file-references.css'
const props=defineProps({sessionId:String,ids:{type:Array,default:()=>[]}})
const userStore=useUserStore()
const actor=computed(()=>JSON.stringify([userStore.identity?.userId || userStore.username || '',userStore.role,userStore.isAuthenticated]))
const files=ref([]),error=ref(''),loading=ref(false),busy=ref(false),previewOpen=ref(false),previewKind=ref('text'),previewText=ref(''),previewUrl=ref('')
const previewFile=ref(null),previewPage=ref(1),previewPages=ref(1)
const pdfNavigation=ref(null)
let pdfFocusPending=false
watch([previewOpen,previewPage,busy],async()=>{if(previewOpen.value&&previewKind.value==='pdf'&&!busy.value&&pdfFocusPending){await nextTick();if(previewOpen.value&&pdfFocusPending){pdfFocusPending=false;pdfNavigation.value?.focus()}}},{flush:'post'})
const base=(import.meta.env.VITE_API_URL||'').replace(/\/$/,'');let abort,generation=0,previewVersion=0
function revoke(){if(previewUrl.value)URL.revokeObjectURL(previewUrl.value);previewUrl.value=''}
async function load(){abort?.abort();abort=new AbortController();const version=++generation;previewVersion++;pdfFocusPending=false;files.value=[];error.value='';loading.value=true;busy.value=false;previewOpen.value=false;previewFile.value=null;previewText.value='';revoke();if(!userStore.isAuthenticated){error.value='登录状态未确认，请核对账号后重新读取附件。';loading.value=false;return}try{const value=await referencedFiles(props.sessionId,props.ids,{base,signal:abort.signal});if(version===generation)files.value=value}catch(e){if(version===generation&&e.name!=='AbortError')error.value=e.message}finally{if(version===generation)loading.value=false}}
watch(()=>[props.sessionId,props.ids.join(','),actor.value],load,{immediate:true,flush:'sync'})
async function read(file,action,preview=false,page=1,expectedPreview=null){if(busy.value||!file||file.unavailable)return;const version=generation;busy.value=true;error.value='';try{const value=await (preview?readFilePreview:readReferencedFile)(props.sessionId,file,{base,signal:abort.signal,page});if(version===generation)await action(value,version)}catch(e){if(version===generation&&(!preview||expectedPreview===previewVersion)&&e.name!=='AbortError'){error.value=e.message;if([401,403,404].includes(e.status)){files.value=e.status===401?[]:files.value.map(value=>value.id===file.id?{id:file.id,unavailable:true}:value);previewOpen.value=false;revoke()}}}finally{if(version===generation)busy.value=false}}
async function open(file,page=1){if(busy.value||!file||file.unavailable)return;const version=++previewVersion;if(previewOpen.value&&previewKind.value==='pdf')pdfFocusPending=true;await read(file,value=>{if(version!==previewVersion)return;revoke();previewFile.value=file;previewKind.value=value.kind;previewText.value=value.text||'';previewPage.value=value.page||1;previewPages.value=value.pages||1;pdfFocusPending=value.kind==='pdf';if(value.kind!=='text')previewUrl.value=URL.createObjectURL(value.kind==='pdf'?value.blob:new Blob([value.blob],{type:file.contentType}));previewOpen.value=true},true,page,version)}
async function download(file){await read(file,blob=>{const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=file.name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)})}
watch(previewOpen,open=>{if(!open){previewVersion++;pdfFocusPending=false;revoke()}},{flush:'sync'})
onBeforeUnmount(()=>{generation++;abort?.abort();revoke()})
</script>
