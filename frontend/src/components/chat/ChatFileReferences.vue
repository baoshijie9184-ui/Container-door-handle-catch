<template>
 <section class="chat-file-references" aria-label="消息附件">
  <span v-if="loading" role="status">正在读取附件信息</span>
  <article v-for="file in files" :key="file.id" class="chat-file-card">
   <el-icon aria-hidden="true"><Document /></el-icon><span class="chat-file-label">{{ file.unavailable?'资料已移除或无权访问':file.name }}<small v-if="!file.unavailable">{{ Math.ceil(file.bytes/1024) }} KB</small></span>
   <template v-if="!file.unavailable"><button :disabled="busy" @click="open(file)">预览</button><button :disabled="busy" @click="download(file)">下载</button></template>
  </article>
  <p v-if="error" role="alert">{{ error }} <button @click="load">重新读取</button></p>
  <el-dialog v-model="previewOpen" title="消息附件预览" append-to-body width="min(900px,90vw)"><img v-if="previewKind==='image'" :src="previewUrl" alt="会话附件" class="chat-file-image"/><iframe v-else-if="previewKind==='pdf'" :src="previewUrl" sandbox="" title="PDF 附件" class="chat-file-frame"/><pre v-else>{{ previewText }}</pre></el-dialog>
 </section>
</template>
<script setup>
import {ref,watch,onBeforeUnmount} from 'vue'
import {Document} from '@element-plus/icons-vue'
import {referencedFiles,readReferencedFile,filePreviewKind} from '@/utils/chatFileReferences'
import '@/assets/chat-file-references.css'
const props=defineProps({sessionId:String,ids:{type:Array,default:()=>[]}})
const files=ref([]),error=ref(''),loading=ref(false),busy=ref(false),previewOpen=ref(false),previewKind=ref('text'),previewText=ref(''),previewUrl=ref('')
const base=(import.meta.env.VITE_API_URL||'').replace(/\/$/,'');let abort,generation=0
function revoke(){if(previewUrl.value)URL.revokeObjectURL(previewUrl.value);previewUrl.value=''}
async function load(){abort?.abort();abort=new AbortController();const version=++generation;files.value=[];error.value='';loading.value=true;busy.value=false;previewOpen.value=false;revoke();try{const value=await referencedFiles(props.sessionId,props.ids,{base,signal:abort.signal});if(version===generation)files.value=value}catch(e){if(version===generation&&e.name!=='AbortError')error.value=e.message}finally{if(version===generation)loading.value=false}}
watch(()=>[props.sessionId,props.ids.join(',')],load,{immediate:true})
async function read(file,action){const version=generation;busy.value=true;error.value='';try{const blob=await readReferencedFile(props.sessionId,file,{base,signal:abort.signal});if(version===generation)await action(blob,version)}catch(e){if(version===generation&&e.name!=='AbortError'){error.value=e.message;if([403,404].includes(e.status)){files.value=files.value.map(value=>value.id===file.id?{id:file.id,unavailable:true}:value);previewOpen.value=false;revoke()}}}finally{if(version===generation)busy.value=false}}
async function open(file){await read(file,async(blob,version)=>{const kind=filePreviewKind(file);const text=kind==='text'?await blob.slice(0,64000).text():'';if(version!==generation)return;revoke();previewKind.value=kind;previewText.value=text;if(kind!=='text')previewUrl.value=URL.createObjectURL(new Blob([blob],{type:file.contentType}));previewOpen.value=true})}
async function download(file){await read(file,blob=>{const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=file.name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)})}
watch(previewOpen,open=>{if(!open)revoke()})
onBeforeUnmount(()=>{generation++;abort?.abort();revoke()})
</script>
