<template>
 <section class="chat-file-references" aria-label="消息附件">
  <span v-if="loading" role="status">正在读取附件信息</span>
  <article v-for="file in files" :key="file.id" class="chat-file-card">
   <el-icon aria-hidden="true"><Document /></el-icon><span class="chat-file-label">{{ file.unavailable?'资料已移除或无权访问':file.name }}<small v-if="!file.unavailable">{{ Math.ceil(file.bytes/1024) }} KB</small></span>
   <template v-if="!file.unavailable"><button :disabled="busy" @click="open(file)">预览</button><button :disabled="busy" @click="download(file)">下载</button></template>
  </article>
  <p v-if="error" role="alert">{{ error }} <button @click="load">重新读取</button></p>
  <el-dialog v-model="previewOpen" title="消息附件预览" append-to-body width="min(900px,90vw)"><p v-if="imageError" role="alert">{{ imageError }}</p><nav v-if="previewKind==='pdf'" class="chat-file-pages" aria-label="PDF 页码"><button :disabled="busy||previewPage===1" @click="open(previewFile,previewPage-1)">上一页</button><span>第 {{ previewPage }} / {{ previewPages }} 页</span><button :disabled="busy||previewPage===previewPages" @click="open(previewFile,previewPage+1)">下一页</button><small>页面预览 · Agent 仅可读取文字层</small></nav><img v-if="['image','pdf'].includes(previewKind)" :src="previewUrl" :alt="previewKind==='pdf'?'PDF 第 '+previewPage+' 页':'会话附件'" class="chat-file-image" @error="imageError='图片预览失败，请下载原文件核对'"/><pre v-else class="chat-file-preview-text">{{ previewText }}</pre></el-dialog>
 </section>
</template>
<script setup>
import {ref,watch,onBeforeUnmount} from 'vue'
import {Document} from '@element-plus/icons-vue'
import {referencedFiles,readReferencedFile,readFilePreview} from '@/utils/chatFileReferences'
import '@/assets/chat-file-references.css'
const props=defineProps({sessionId:String,ids:{type:Array,default:()=>[]}})
const files=ref([]),error=ref(''),loading=ref(false),busy=ref(false),previewOpen=ref(false),previewKind=ref('text'),previewText=ref(''),previewUrl=ref('')
const previewFile=ref(null),previewPage=ref(1),previewPages=ref(1),imageError=ref('')
const base=(import.meta.env.VITE_API_URL||'').replace(/\/$/,'');let abort,generation=0,previewVersion=0
function revoke(){if(previewUrl.value)URL.revokeObjectURL(previewUrl.value);previewUrl.value=''}
async function load(){abort?.abort();abort=new AbortController();const version=++generation;files.value=[];error.value='';loading.value=true;busy.value=false;previewOpen.value=false;revoke();try{const value=await referencedFiles(props.sessionId,props.ids,{base,signal:abort.signal});if(version===generation)files.value=value}catch(e){if(version===generation&&e.name!=='AbortError')error.value=e.message}finally{if(version===generation)loading.value=false}}
watch(()=>[props.sessionId,props.ids.join(',')],load,{immediate:true})
async function read(file,action,preview=false,page=1){const version=generation;busy.value=true;error.value='';try{const value=await (preview?readFilePreview:readReferencedFile)(props.sessionId,file,{base,signal:abort.signal,page});if(version===generation)await action(value,version)}catch(e){if(version===generation&&e.name!=='AbortError'){error.value=e.message;if([403,404].includes(e.status)){files.value=files.value.map(value=>value.id===file.id?{id:file.id,unavailable:true}:value);previewOpen.value=false;revoke()}}}finally{if(version===generation)busy.value=false}}
async function open(file,page=1){const version=++previewVersion;await read(file,value=>{if(version!==previewVersion)return;revoke();imageError.value='';previewFile.value=file;previewKind.value=value.kind;previewText.value=value.text||'';previewPage.value=value.page||1;previewPages.value=value.pages||1;if(value.kind!=='text')previewUrl.value=URL.createObjectURL(value.kind==='pdf'?value.blob:new Blob([value.blob],{type:file.contentType}));previewOpen.value=true},true,page)}
async function download(file){await read(file,blob=>{const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=file.name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)})}
watch(previewOpen,open=>{if(!open){previewVersion++;revoke()}},{flush:'sync'})
onBeforeUnmount(()=>{generation++;abort?.abort();revoke()})
</script>
