<template>
  <section class="file-image-reader" aria-label="图像预览阅读区">
    <div class="file-image-toolbar">
      <div role="group" aria-label="图像显示方式"><button type="button" :aria-pressed="mode==='fit'" :disabled="busy || !dimensions || failed" @click="mode='fit'"><AppIcon name="Picture" :size="15" />适应窗口</button><button type="button" :aria-pressed="mode==='actual'" :disabled="busy || !dimensions || failed" @click="mode='actual'"><AppIcon name="Expand" :size="15" />实际像素</button></div>
      <span>{{ previewImageSizeLabel(dimensions, kind) }}</span>
    </div>
    <p v-if="src && !failed && !dimensions" class="file-image-status" role="status"><AppIcon name="Connection" :size="16" />正在显示预览图</p>
    <div v-if="failed || !src" class="file-image-unavailable" role="status"><AppIcon name="Warning" :size="24" /><strong>图像暂不可显示</strong><p>{{ downloadable ? '可手动重新显示已读取的预览图，或使用下方下载入口核对原文件。' : '可手动重新显示预览图，或关闭后重新读取会话资料核对。' }}</p><button v-if="src" type="button" :disabled="busy" @click="retry"><AppIcon name="Refresh" :size="15" />重新显示预览图</button></div>
    <div v-else ref="viewportElement" class="file-image-viewport" :class="{ 'is-actual': mode==='actual' }" tabindex="0" :aria-label="mode==='actual' ? '实际像素预览，可使用方向键滚动图像' : '适应窗口的图像预览'" :aria-busy="!dimensions">
      <img :key="requestKey" ref="imageElement" class="file-image-content" :src="src" :alt="name || '会话资料预览图'" :style="mode==='actual' && dimensions ? {width:dimensions.width+'px'} : undefined" @load="loaded" @error="imageFailed" />
    </div>
    <p v-if="dimensions && !failed" class="file-image-note">{{ mode==='actual' ? '实际像素显示，可在图像区域内横向或纵向滚动。' : '适应窗口会缩小大图，可切换实际像素查看细节。' }}<span v-if="kind==='pdf'">像素尺寸属于当前页面预览图，不是原 PDF 的页面尺寸。</span></p>
  </section>
</template>
<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { previewImageDimensions, previewImageSizeLabel } from '@/utils/fileImagePresentation'
import '@/assets/file-image-reader.css'
const props = defineProps({ src: String, name: String, kind: String, busy: Boolean, downloadable: Boolean })
const mode = ref('fit'), dimensions = ref(null), failed = ref(false), attempt = ref(0), imageElement = ref(null), viewportElement = ref(null)
const requestKey = computed(() => JSON.stringify([props.src,props.name,props.kind,attempt.value]))
watch(() => [props.src,props.name,props.kind], () => { mode.value='fit';dimensions.value=null;failed.value=false;attempt.value++ }, {flush:'sync'})
function current(event) { return event.currentTarget === imageElement.value && event.currentTarget.getAttribute('src') === props.src }
function loaded(event) {
  if (!current(event)) return
  dimensions.value = previewImageDimensions(event.currentTarget.naturalWidth,event.currentTarget.naturalHeight)
  failed.value = !dimensions.value
}
function imageFailed(event) { if (current(event)) { dimensions.value=null;failed.value=true } }
async function retry() { if (props.busy || !props.src) return; mode.value='fit';dimensions.value=null;failed.value=false;attempt.value++;const key=requestKey.value;await nextTick();if(key===requestKey.value)viewportElement.value?.focus({preventScroll:true}) }
</script>
