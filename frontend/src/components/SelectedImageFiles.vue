<template>
  <details ref="detailsElement" class="selected-image-review" @toggle="toggle">
    <summary><AppIcon name="Picture" :size="16" /><span>核对所选图片</span><span class="selected-image-count">{{ entries.length }} 张</span><AppIcon class="selected-image-chevron" name="ArrowDown" :size="14" /></summary>
    <div v-if="opened" class="selected-image-content">
      <p class="selected-image-note">仅在本机读取当前选择，不会发起上传。缩略图能显示不代表图片已上传、可检测或检测完成。</p>
      <dl class="selected-image-total"><dt>所选文件总大小</dt><dd :title="totalBytes===null ? undefined : totalBytes+' 字节'">{{ byteLabel(totalBytes) }}<span v-if="totalBytes!==null">（{{ totalBytes.toLocaleString('zh-CN') }} 字节）</span></dd></dl>
      <p class="selected-image-note">缩略图显示所选顺序的前 {{ previews.length }} 张，不代表全部图片。</p>
      <div class="selected-image-previews">
        <figure v-for="preview in previews" :key="preview.key">
          <div class="selected-image-frame">
            <img v-if="preview.url && !preview.failed" :src="preview.url" :alt="preview.name" decoding="async" @load="imageLoaded($event,preview)" @error="imageFailed($event,preview)" />
            <span v-if="!preview.url || preview.failed" class="selected-image-fallback"><AppIcon name="Picture" :size="22" />本机缩略图不可用</span>
            <span v-else-if="!preview.loaded" class="selected-image-loading">正在显示</span>
          </div>
          <figcaption :title="preview.name">{{ preview.name }}</figcaption>
        </figure>
      </div>
      <label class="selected-image-search"><span><AppIcon name="Search" :size="14" />查找本次所选文件</span><el-input ref="searchElement" v-model="query" maxlength="200" clearable aria-label="按文件名或相对路径查找本次所选图片" placeholder="文件名或相对路径" @keydown.enter.prevent @keydown.esc.stop.prevent="query=''" /></label>
      <p class="selected-image-note" role="status">{{ query.trim() ? '匹配 '+matches.length+' / 所选 '+entries.length+' 张，仅查找当前清单。' : '当前清单 '+entries.length+' 张，保持所选顺序。' }}</p>
      <div v-if="matches.length" class="selected-image-manifest" tabindex="0" role="region" :aria-label="(query.trim() ? '本次所选图片匹配文件清单' : '本次所选图片完整文件清单')+'，可使用方向键滚动'">
        <ol><li v-for="entry in matches" :key="entry.key"><div><strong>{{ entry.name }}</strong><span v-if="entry.path && entry.path!==entry.name">{{ entry.path }}</span></div><small :title="entry.bytes===null ? undefined : entry.bytes+' 字节'">{{ byteLabel(entry.bytes) }}</small></li></ol>
      </div>
      <div v-else class="selected-image-empty"><AppIcon name="Search" :size="20" /><p>本次所选文件中没有匹配项</p><button type="button" @click="clearQuery">清空查找</button></div>
      <p class="selected-image-note">文件清单仅供核对，不会因查找而改变上传范围。若选择有误，请使用原“选择图片文件夹”重新选择；开始上传后不会通过本区取消服务器任务。</p>
    </div>
  </details>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, ref, toRaw, watch } from 'vue'
const props = defineProps({ files: { type: Array, default: () => [] }, scopeKey: String })
const detailsElement = ref(null), searchElement = ref(null), opened = ref(false), query = ref(''), previews = ref([])
const entries = computed(() => props.files.map((entry,index) => {
  const file=toRaw(entry?.file),bytes=file?.size ?? entry?.fileSize
  return { key:index, name:typeof entry?.fileName==='string' ? entry.fileName : '文件名未记录', path:typeof entry?.relativePath==='string' ? entry.relativePath : '', bytes:Number.isSafeInteger(bytes) && bytes>=0 ? bytes : null, file }
}))
const totalBytes = computed(() => {
  let total=0
  for(const entry of entries.value){if(entry.bytes===null || !Number.isSafeInteger(total+entry.bytes))return null;total+=entry.bytes}
  return total
})
const matches = computed(() => {
  const needle=query.value.trim().toLowerCase()
  return needle ? entries.value.filter(entry=>(entry.name+'\n'+entry.path).toLowerCase().includes(needle)) : entries.value
})
function byteLabel(bytes){
  if(bytes===null)return '大小未核对'
  if(bytes<1024)return bytes+' B'
  if(bytes<1024**2)return (bytes/1024).toFixed(1)+' KiB'
  if(bytes<1024**3)return (bytes/1024**2).toFixed(2)+' MiB'
  return (bytes/1024**3).toFixed(2)+' GiB'
}
function releasePreviews(){
  const previous=previews.value
  previews.value=[]
  for(const preview of previous)if(preview.url)URL.revokeObjectURL(preview.url)
}
function toggle(event){
  if(event.currentTarget!==detailsElement.value)return
  opened.value=event.currentTarget.open
}
async function clearQuery(){
  query.value=''
  const files=props.files,scope=props.scopeKey
  await nextTick()
  if(opened.value && props.files===files && props.scopeKey===scope)searchElement.value?.input?.focus({preventScroll:true})
}
function currentImage(event,preview){
  return opened.value && previews.value.some(item=>item.key===preview.key && item.url===preview.url) && event.currentTarget.getAttribute('src')===preview.url
}
function imageLoaded(event,preview){if(currentImage(event,preview)){preview.loaded=true;preview.failed=!(event.currentTarget.naturalWidth>0 && event.currentTarget.naturalHeight>0)}}
function imageFailed(event,preview){if(currentImage(event,preview))preview.failed=true}
watch(opened,open=>{
  releasePreviews()
  if(!open)return
  previews.value=entries.value.slice(0,6).map(entry=>{
    let url=''
    try{if(typeof Blob!=='undefined' && entry.file instanceof Blob)url=URL.createObjectURL(entry.file)}catch{/* Local preview failure must not change the selection. */}
    return {key:entry.key,name:entry.name,url,loaded:false,failed:!url}
  })
},{flush:'sync'})
watch(()=>[props.files,props.scopeKey],()=>{
  opened.value=false;query.value='';releasePreviews()
  if(detailsElement.value)detailsElement.value.open=false
},{flush:'sync'})
onBeforeUnmount(releasePreviews)
</script>
<style scoped>
.selected-image-review{margin:14px 0 4px;padding-top:12px;border-top:1px solid var(--app-border);min-width:0}
.selected-image-review>summary{display:flex;align-items:center;gap:7px;cursor:pointer;color:var(--app-primary);font-size:13px;line-height:1.8;list-style:none;transition:color 180ms ease}
.selected-image-review>summary::-webkit-details-marker{display:none}
.selected-image-review>summary>.el-icon{flex:0 0 auto}.selected-image-count{margin-left:auto;font-size:12px;color:var(--app-text-secondary)}
.selected-image-chevron{transition:transform 180ms ease}.selected-image-review[open]>summary .selected-image-chevron{transform:rotate(180deg)}
.selected-image-content{padding-top:8px;min-width:0}.selected-image-note{margin:7px 0 12px;font-size:12px;line-height:1.85;color:var(--app-text-secondary);overflow-wrap:anywhere}
.selected-image-total{margin:12px 0;display:grid;gap:4px;font-size:12px;line-height:1.85}.selected-image-total dt{color:var(--app-text-secondary)}.selected-image-total dd{margin:0;color:var(--app-text);overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.selected-image-total dd span{color:var(--app-text-secondary)}
.selected-image-previews{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px 9px}.selected-image-previews figure{margin:0;min-width:0}
.selected-image-frame{position:relative;aspect-ratio:4/3;display:grid;place-items:center;overflow:hidden;border-radius:6px;background:var(--app-surface-muted);border:1px solid var(--app-border)}
.selected-image-frame img{display:block;max-width:100%;max-height:100%;width:100%;height:100%;object-fit:contain}.selected-image-fallback{display:flex;align-items:center;flex-direction:column;gap:6px;text-align:center;color:var(--app-text-secondary);font-size:12px;line-height:1.7;padding:6px}
.selected-image-loading{position:absolute;bottom:4px;padding:1px 5px;background:#fffffff0;color:var(--app-text-secondary);font-size:12px;line-height:1.8;border-radius:3px}
.selected-image-previews figcaption{margin-top:5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;color:var(--app-text-secondary);line-height:1.85}
.selected-image-search{display:grid;gap:6px;margin-top:16px;font-size:12px;color:var(--app-text-secondary);line-height:1.8}.selected-image-search>span{display:flex;align-items:center;gap:6px}
.selected-image-manifest{max-height:280px;overflow:auto;overscroll-behavior:contain;border-top:1px solid var(--app-border);border-bottom:1px solid var(--app-border)}
.selected-image-manifest ol{margin:0;padding:0;list-style:none}.selected-image-manifest li{display:flex;align-items:flex-start;gap:10px;justify-content:space-between;padding:9px 1px;border-bottom:1px solid var(--app-border)}.selected-image-manifest li:last-child{border-bottom:0}
.selected-image-manifest li>div{display:grid;gap:3px;min-width:0}.selected-image-manifest strong{font-size:12px;font-weight:550;color:var(--app-text);line-height:1.8;overflow-wrap:anywhere}.selected-image-manifest li span{font-size:12px;color:var(--app-text-secondary);line-height:1.8;overflow-wrap:anywhere}
.selected-image-manifest small{font-size:12px;line-height:1.8;white-space:nowrap;font-variant-numeric:tabular-nums;color:var(--app-text-secondary)}
.selected-image-empty{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:12px 0;color:var(--app-text-secondary);font-size:12px;line-height:1.8}.selected-image-empty p{margin:0}.selected-image-empty button{border:0;padding:3px 0;background:transparent;color:var(--app-primary);font:inherit;cursor:pointer}
.selected-image-review :is(summary,button):focus-visible{outline:2px solid var(--app-primary);outline-offset:3px;border-radius:3px}.selected-image-manifest:focus-visible{outline:2px solid var(--app-primary);outline-offset:-2px}
@media(max-width:420px){.selected-image-previews{grid-template-columns:repeat(2,minmax(0,1fr))}.selected-image-count{white-space:nowrap}.selected-image-manifest li{flex-wrap:wrap;gap:3px}}
@media(prefers-reduced-motion:reduce){.selected-image-review>summary,.selected-image-chevron{transition:none}}
</style>
