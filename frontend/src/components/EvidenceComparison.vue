<template>
  <section class="evidence-comparison" :aria-labelledby="headingId">
    <header><div><h3 :id="headingId"><AppIcon name="Picture" :size="19" />图片对照</h3><p>按唯一文件名对照原图与标注，选择图片后可放大核对</p></div><el-select v-if="pairs.length" :model-value="current?.key" filterable aria-label="选择对照图片" @change="selection = $event"><el-option v-for="pair in pairs" :key="pair.key" :value="pair.key" :label="pair.label" /></el-select></header>
    <p v-if="current" class="comparison-selection" role="status">当前选择 {{ current.label || '名称未记录' }}<span>本次资料共 {{ pairs.length }} 组<template v-if="unpairedCount"> · {{ unpairedCount }} 组为单份资料</template></span></p>
    <p v-if="current?.ambiguous" class="comparison-note"><AppIcon name="Warning" :size="15" />同名文件不唯一，当前仅显示单份资料，请结合任务中的存储记录核对。</p>
    <p v-if="!pairs.length" class="comparison-note"><AppIcon name="Files" :size="16" />当前任务没有可对照的图片资料</p>
    <div v-else class="comparison-images">
      <figure v-for="side in sideViews" :key="side.key">
        <figcaption><strong>{{ side.label }}</strong><a v-if="side.url" :href="side.url" :aria-label="'在新标签页打开'+side.label+'：'+(current.name || '名称未记录')" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">新标签页打开<AppIcon name="TopRight" :size="13" /></a></figcaption>
        <button v-if="side.url && !side.failed" type="button" class="comparison-image-button" :aria-label="'放大'+side.label+'：'+(current.name || '名称未记录')" @click="openZoom(side)"><img :key="side.url" :src="side.url" :alt="side.label+' '+(current.name || '名称未记录')" loading="lazy" decoding="async" @load="markLoaded(side.key,$event.currentTarget.getAttribute('src'))" @error="markFailed(side.key, $event.currentTarget.getAttribute('src'))"/><span :role="side.loaded ? undefined : 'status'"><AppIcon :name="side.loaded ? 'Search' : 'Connection'" :size="14" />{{ side.loaded ? '放大核对' : '正在读取图片' }}</span></button>
        <div v-else class="comparison-image-empty" :data-state="side.file ? 'unavailable' : 'missing'"><AppIcon :name="side.file ? 'Warning' : 'Picture'" :size="25" /><strong>{{ side.emptyTitle }}</strong><p>{{ side.emptyDescription }}</p><el-button v-if="side.url" size="small" :aria-label="'重新读取'+side.label" @click="retryImage(side)"><AppIcon name="Refresh" :size="14" />重新读取图片</el-button></div>
        <p class="comparison-filename">{{ side.file?.imageName || '名称未记录' }}</p>
      </figure>
    </div>
    <el-dialog v-model="zoomOpen" :title="zoomTitle" width="min(1100px, 96vw)" append-to-body class="evidence-zoom-dialog">
      <p class="comparison-zoom-note"><AppIcon name="Picture" :size="16" />图片仅供核对，人工复核结论及放行状态请查看对应业务记录。</p>
      <div v-if="zoomError" class="comparison-image-empty" data-state="unavailable" role="alert"><AppIcon name="Warning" :size="26" /><strong>图片暂不可读取</strong><p>可通过下方原预览地址核对，或关闭后重新读取任务详情。</p></div><img v-else :src="zoomUrl" :alt="zoomTitle" class="comparison-zoom-image" @error="zoomError = true"/>
      <template #footer><div class="comparison-zoom-actions"><a v-if="zoomUrl" :href="zoomUrl" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">在新标签页打开原预览<AppIcon name="TopRight" :size="14" /></a><el-button @click="zoomOpen = false">关闭图片</el-button></div></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, getCurrentInstance, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { evidenceComparisonPairs, evidencePreviewUrl } from '../utils/evidencePresentation'
const props = defineProps({ taskId: String, originals: { type: Array, default: () => [] }, annotations: { type: Array, default: () => [] } })
const headingId = 'evidence-comparison-' + getCurrentInstance().uid
const selection = ref(''), failed = ref(new Set()), loaded = ref(new Set()), zoomOpen = ref(false), zoomUrl = ref(''), zoomTitle = ref(''), zoomError = ref(false)
const sides = [{ key: 'original', label: '原图' }, { key: 'annotation', label: '标注图' }]
const pairs = computed(() => evidenceComparisonPairs(props.originals, props.annotations))
const unpairedCount = computed(() => pairs.value.filter(pair => !pair.original || !pair.annotation).length)
const current = computed(() => pairs.value.find(pair => pair.key === selection.value) || pairs.value[0] || null)
const imageUrl = side => evidencePreviewUrl(current.value?.[side])
const sideViews = computed(() => sides.map(side => {
  const file=current.value?.[side.key],url=evidencePreviewUrl(file)
  const unavailable=!!file && (!url || failed.value.has(side.key+':'+url))
  return {...side,file,url,loaded:loaded.value.has(side.key+':'+url),failed:unavailable,emptyTitle:unavailable?'图片暂不可读取':current.value?.ambiguous?'未自动匹配':'暂无'+side.label,emptyDescription:unavailable?url?'可重新读取图片、在新标签页打开，或重新读取任务详情。':'已返回图片资料，但没有可使用的预览地址，请重新读取任务详情。':current.value?.ambiguous?'同名资料存在多份，请分别核对。':'当前任务没有返回对应图片资料。'}
}))
const markFailed = (side, source) => { failed.value = new Set([...failed.value, side + ':' + source]) }
const markLoaded = (side, source) => { loaded.value = new Set([...loaded.value, side + ':' + source]) }
function retryImage(side) {
  if(!side.url || imageUrl(side.key)!==side.url)return
  const key=side.key+':'+side.url,nextFailed=new Set(failed.value),nextLoaded=new Set(loaded.value)
  nextFailed.delete(key);nextLoaded.delete(key);loaded.value=nextLoaded;failed.value=nextFailed
}
function openZoom(side) { if(!side.url || side.failed)return; zoomUrl.value = side.url; zoomTitle.value = side.label + ' · ' + (current.value?.label || '名称未记录'); zoomError.value = false; zoomOpen.value = true }
watch(() => props.taskId, () => { selection.value = ''; failed.value = new Set(); loaded.value = new Set() })
watch(() => [props.taskId, current.value?.key, current.value?.name, imageUrl('original'), imageUrl('annotation')], () => { zoomOpen.value = false; zoomUrl.value = ''; zoomError.value = false })
</script>

<style scoped>
.evidence-comparison { min-width: 0; padding: 0 0 20px; margin-bottom: 20px; border: 0; border-bottom: 1px solid var(--app-border); border-radius: 0; background: white; }
.evidence-comparison > header { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 14px; }
.evidence-comparison h3 { display: flex; align-items: center; gap: 8px; font-size: 16px; color: var(--app-text); margin: 0; }
.evidence-comparison h3 .el-icon { color: var(--app-primary); }
.evidence-comparison header p { margin: 7px 0 0; color: var(--app-text-secondary); font-size: 12px; line-height: 1.8; }
.evidence-comparison header .el-select { width: min(320px, 100%); }
.comparison-selection { display:grid; gap:5px; margin:0 0 15px; color:var(--app-text); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.comparison-selection > span { color:var(--app-text-secondary); }
.comparison-images { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.comparison-images figure { min-width: 0; margin: 0; overflow: hidden; border: 1px solid var(--app-border); border-radius: 9px; }
.comparison-images figcaption { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; padding: 10px 12px; background: #f8fafc; border-bottom: 1px solid var(--app-border); font-size: 12px; }
.comparison-images figcaption a { display: inline-flex; align-items: center; gap: 4px; color: var(--app-primary); font-size: 12px; text-underline-offset:3px; }
.comparison-image-button { display: block; position: relative; width: 100%; height: 260px; padding: 0; border: 0; background: #f4f6fa; cursor: zoom-in; overflow: hidden; }
.comparison-image-button img { display: block; width: 100%; height: 100%; object-fit: contain; }
.comparison-image-button > span { position: absolute; display: inline-flex; align-items: center; gap: 5px; bottom: 10px; right: 10px; padding: 5px 9px; border: 1px solid var(--app-border); border-radius: 6px; background: #ffffffef; color: var(--app-text-secondary); font-size: 11px; }
.comparison-image-button:hover > span { color: var(--app-primary); background: white; }
.comparison-image-empty { display: flex; min-height: 260px; flex-direction: column; align-items: center; justify-content: center; gap: 9px; padding: 20px; background: #f8fafc; color: var(--app-text-muted); font-size: 12px; text-align: center; }
.comparison-image-empty p { max-width: 32ch; margin: 0; line-height: 1.8; }
.comparison-image-empty > .el-icon { color:var(--app-primary); }
.comparison-image-empty[data-state=unavailable] > .el-icon { color:var(--app-warning); }
.comparison-filename { margin: 0; padding: 9px 12px; border-top: 1px solid var(--app-border); color: var(--app-text-secondary); font-size: 12px; line-height: 1.8; overflow-wrap: anywhere; }
.comparison-note { display: flex; align-items: flex-start; gap: 7px; padding: 10px 12px; color: var(--app-warning); background: var(--app-warning-soft); border-radius: 8px; line-height: 1.8; font-size: 12px; }
.comparison-note .el-icon { flex-shrink: 0; margin-top: 3px; }
.comparison-zoom-note { display:flex; align-items:flex-start; gap:8px; margin:0 0 16px; font-size:12px; line-height:1.85; color:var(--app-text-secondary); }
.comparison-zoom-note > .el-icon { flex-shrink:0; margin-top:3px; color:var(--app-primary); }
.comparison-zoom-image { display:block; width:100%; max-height:60vh; max-height:60dvh; object-fit:contain; background:var(--app-bg); border-radius:8px; }
.comparison-zoom-actions { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:10px 18px; }
.comparison-zoom-actions a { display:inline-flex; align-items:center; gap:6px; color:var(--app-primary); font-size:12px; line-height:1.8; text-underline-offset:3px; }
.evidence-comparison :is(button,a):focus-visible,.comparison-zoom-actions :is(button,a):focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
.comparison-image-button > span { transition:background-color 180ms ease,color 180ms ease; }
@media(max-width:640px) { .evidence-comparison { padding-bottom:18px; }.comparison-images { grid-template-columns:minmax(0,1fr); }.comparison-image-button { height:230px; }.comparison-image-empty { min-height:230px; } }
@media(prefers-reduced-motion:reduce) { .comparison-image-button > span { transition:none; } }
</style>

<style>
.evidence-zoom-dialog.el-dialog { display:flex; flex-direction:column; margin-top:5vh; margin-bottom:5vh; max-height:90vh; max-height:90dvh; }
.evidence-zoom-dialog :is(.el-dialog__header,.el-dialog__footer) { flex-shrink:0; }
.evidence-zoom-dialog .el-dialog__title { display:block; padding-right:28px; font-size:16px; line-height:1.75; overflow-wrap:anywhere; }
.evidence-zoom-dialog .el-dialog__body { min-height:0; max-height:70vh; max-height:70dvh; overflow:auto; overscroll-behavior:contain; }
</style>
