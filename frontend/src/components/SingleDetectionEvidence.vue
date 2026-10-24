<template>
  <section class="single-evidence" aria-label="本次单图检测图片与模型摘要">
    <dl class="single-evidence-summary"><div><dt>模型返回类别</dt><dd><el-tag :type="categoryTone">{{ categoryLabel }}</el-tag></dd></div><div><dt>模型置信度</dt><dd>{{ confidenceLabel }}</dd></div></dl>
    <p class="single-evidence-note">类别与置信度来自本次返回摘要，不代表人工复核、任务放行或模型准确率。图片可放大核对。</p>
    <div class="single-evidence-images">
      <figure v-for="image in images" :key="image.side">
        <figcaption><strong>{{ image.label }}</strong><span>{{ image.source }}</span></figcaption>
        <button v-if="image.url && !failed.has(image.stamp)" class="single-evidence-image" type="button" :aria-label="'放大'+image.label+'：'+fileName" @click="openImage(image)">
          <img :key="image.stamp" :src="image.url" :alt="image.label+' '+fileName" @load="setImageState(image, false)" @error="setImageState(image, true)" />
          <span v-if="!loaded.has(image.stamp)" class="single-evidence-loading">正在读取图片</span>
          <span v-else class="single-evidence-zoom"><AppIcon name="Expand" :size="14" />放大核对</span>
        </button>
        <div v-else class="single-evidence-unavailable"><AppIcon :name="image.url ? 'Warning' : 'Picture'" :size="23" /><strong>{{ image.url ? '图片暂不可读取' : '没有可用预览地址' }}</strong><p>{{ image.url ? '可重新读取当前图片，或从任务追溯核对原始资料。' : '请从任务追溯核对图片资料，不根据空预览推断没有检测结果。' }}</p><button v-if="image.url" type="button" @click="retryImage(image)"><AppIcon name="Refresh" :size="14" />重新读取图片</button></div>
      </figure>
    </div>
    <p class="single-evidence-file"><AppIcon name="Document" :size="14" /><span>{{ fileName || '提交文件名未记录' }}</span></p>
    <el-dialog v-model="zoomOpen" class="single-evidence-dialog" append-to-body :title="zoomImage?.label || '图片核对'" width="min(1100px, 94vw)" @closed="clearClosedImage">
      <template v-if="zoomImage"><p class="single-evidence-dialog-note">{{ zoomImage.source }} · {{ fileName || '文件名未记录' }}</p><div class="single-evidence-large"><img v-if="!zoomFailed" :key="zoomAttempt" :data-preview-attempt="zoomAttempt" :src="zoomImage.url" :alt="zoomImage.label+' '+fileName" @error="markZoomFailed"/><p v-else role="alert">图片暂不可读取，可重新读取当前图片，或关闭后核对任务追溯。</p></div></template>
      <template #footer><el-button v-if="zoomFailed" @click="zoomFailed=false;zoomAttempt++"><AppIcon name="Refresh" :size="15" />重新读取图片</el-button><el-button @click="zoomOpen=false"><AppIcon name="Close" :size="15" />关闭图片</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { evidencePreviewUrl } from '../utils/evidencePresentation'
const props=defineProps({taskId:String,fileName:String,originalUrl:String,annotationUrl:String,localPreview:String,categoryLabel:String,categoryTone:String,confidenceLabel:String})
const failed=ref(new Set()),loaded=ref(new Set()),attempts=ref({})
const zoomOpen=ref(false),zoomImage=ref(null),zoomFailed=ref(false),zoomAttempt=ref(0)
const originalProvided=computed(()=>typeof props.originalUrl==='string' && !!props.originalUrl.trim())
const localOriginal=computed(()=>{
  try {const url=new URL(props.localPreview);return url.protocol==='blob:' && url.origin===globalThis.location?.origin ? props.localPreview : ''} catch {return ''}
})
const sourceScope=computed(()=>JSON.stringify([props.taskId,props.fileName,props.originalUrl,props.annotationUrl,props.localPreview]))
const images=computed(()=>[
  {side:'original',label:'原图',source:originalProvided.value?'服务端返回资料':'本机已选预览，未核验服务器存储',url:originalProvided.value?evidencePreviewUrl({previewUrl:props.originalUrl}):localOriginal.value},
  {side:'annotation',label:'标注图',source:'本次检测返回预览',url:evidencePreviewUrl({previewUrl:props.annotationUrl})}
].map(image=>({...image,scope:sourceScope.value,stamp:sourceScope.value+'|'+image.side+'|'+(attempts.value[image.side]||0)})))
const isCurrent=image=>images.value.some(current=>current.side===image.side && current.stamp===image.stamp)
function setImageState(image,isFailed){if(!isCurrent(image))return;const values=new Set(isFailed?failed.value:loaded.value);values.add(image.stamp);if(isFailed)failed.value=values;else loaded.value=values}
function retryImage(image){if(isCurrent(image))attempts.value={...attempts.value,[image.side]:(attempts.value[image.side]||0)+1}}
function openImage(image){if(!image.url || failed.value.has(image.stamp) || !isCurrent(image))return;zoomImage.value=image;zoomFailed.value=false;zoomAttempt.value++;zoomOpen.value=true}
function clearClosedImage(){if(!zoomOpen.value)zoomImage.value=null}
function markZoomFailed(event){if(zoomOpen.value && event.currentTarget?.dataset.previewAttempt===String(zoomAttempt.value) && event.currentTarget.getAttribute('src')===zoomImage.value?.url)zoomFailed.value=true}
watch(sourceScope,()=>{zoomOpen.value=false;zoomImage.value=null;failed.value=new Set();loaded.value=new Set();attempts.value={}})
</script>

<style scoped>
.single-evidence { min-width:0; }
.single-evidence-summary { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; padding:14px 0; margin:0; border-bottom:1px solid var(--app-border); }
.single-evidence-summary > div { min-width:0; }
.single-evidence-summary dt { font-size:12px; line-height:1.8; color:var(--app-text-secondary); }
.single-evidence-summary dd { margin:7px 0 0; color:var(--app-text); font-size:19px; font-weight:600; overflow-wrap:anywhere; }
.single-evidence-summary :deep(.el-tag) { max-width:100%; height:auto; white-space:normal; line-height:1.8; text-align:left; }
.single-evidence-note { margin:12px 0 16px; color:var(--app-text-secondary); font-size:12px; line-height:1.9; }
.single-evidence-images { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.single-evidence-images figure { min-width:0; margin:0; border:1px solid var(--app-border); border-radius:8px; overflow:hidden; }
.single-evidence-images figcaption { display:grid; gap:4px; padding:10px; min-height:65px; background:var(--app-bg-alt); }
.single-evidence-images figcaption strong { font-size:13px; color:var(--app-text); font-weight:600; }
.single-evidence-images figcaption span { font-size:12px; color:var(--app-text-secondary); line-height:1.6; overflow-wrap:anywhere; }
.single-evidence-image { position:relative; display:block; width:100%; min-height:210px; padding:0; border:0; background:var(--app-bg); cursor:zoom-in; overflow:hidden; }
.single-evidence-image img { display:block; width:100%; height:210px; object-fit:contain; transition:transform 180ms ease; }
.single-evidence-image:hover img { transform:scale(1.015); }
.single-evidence-image > span { position:absolute; bottom:8px; right:8px; display:inline-flex; align-items:center; gap:5px; padding:5px 7px; max-width:calc(100% - 16px); border-radius:5px; background:#fffffff0; font-size:12px; line-height:1.6; color:var(--app-primary); }
.single-evidence-unavailable { min-height:210px; display:flex; align-items:center; justify-content:center; flex-direction:column; gap:8px; padding:16px 12px; background:var(--app-bg); text-align:center; }
.single-evidence-unavailable > .el-icon { color:var(--app-text-secondary); }
.single-evidence-unavailable strong { font-size:13px; color:var(--app-text); font-weight:500; }
.single-evidence-unavailable p { margin:0; font-size:12px; line-height:1.8; color:var(--app-text-secondary); }
.single-evidence-unavailable button { display:inline-flex; align-items:center; gap:5px; min-height:32px; padding:5px 8px; border:1px solid var(--app-border); border-radius:6px; background:#fff; color:var(--app-primary); font:inherit; font-size:12px; cursor:pointer; transition:background 180ms ease; }
.single-evidence-unavailable button:hover { background:var(--app-primary-soft); }
.single-evidence-file { display:flex; align-items:flex-start; gap:6px; margin:10px 0 0; font-size:12px; line-height:1.8; color:var(--app-text-secondary); overflow-wrap:anywhere; }
.single-evidence-file > .el-icon { flex-shrink:0; margin-top:3px; }
.single-evidence :is(button):focus-visible { outline:2px solid var(--app-primary); outline-offset:-3px; }
@media(max-width:480px) { .single-evidence-images { grid-template-columns:minmax(0,1fr); }.single-evidence-image img { height:240px; } }
@media(prefers-reduced-motion:reduce) { .single-evidence-image img,.single-evidence-image:hover img,.single-evidence-unavailable button { transition:none; transform:none; } }
</style>

<style>
.single-evidence-dialog { display:flex; flex-direction:column; max-height:90vh; max-height:90dvh; }
.single-evidence-dialog .el-dialog__body { min-height:0; overflow:auto; overscroll-behavior:contain; }
.single-evidence-dialog .el-dialog__footer { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:8px; }
.single-evidence-dialog .el-dialog__footer .el-button + .el-button { margin-left:0; }
.single-evidence-dialog-note { margin:0 0 12px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.single-evidence-large { display:grid; place-items:center; min-height:180px; background:var(--app-bg); border-radius:8px; }
.single-evidence-large img { display:block; max-width:100%; max-height:65vh; max-height:65dvh; object-fit:contain; }
.single-evidence-large p { padding:20px; font-size:13px; color:var(--app-text-secondary); line-height:1.9; }
.single-evidence-dialog button:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
</style>
