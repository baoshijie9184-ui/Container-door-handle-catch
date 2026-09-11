<template>
  <section class="duplicate-comparison" aria-label="重复图片对比复核">
    <div class="comparison-toolbar">
      <div>
        <strong>重复图片对比</strong>
        <span class="comparison-index">{{ currentIndex + 1 }} / {{ maxCount }}</span>
      </div>
      <div class="comparison-actions">
        <el-button size="small" :disabled="currentIndex === 0" @click="move(-1)">上一张</el-button>
        <el-button size="small" :disabled="currentIndex >= maxCount - 1" @click="move(1)">下一张</el-button>
        <el-button size="small" type="primary" @click="$emit('select', currentIndex)">采用当前对比结果</el-button>
      </div>
    </div>

    <div class="comparison-panes">
      <article class="comparison-pane">
        <header><span>{{ left.title || '来源 A' }}</span><small>{{ left.employeeName || '--' }}</small></header>
        <div class="image-stage"><img v-if="leftImage" :src="leftImage.url" :alt="leftImage.fileName" /><el-empty v-else description="暂无图片" /></div>
        <footer>{{ leftImage?.fileName || '--' }}<span>{{ leftImage?.detectionTime || '' }}</span></footer>
      </article>
      <article class="comparison-pane">
        <header><span>{{ right.title || '来源 B' }}</span><small>{{ right.employeeName || '--' }}</small></header>
        <div class="image-stage"><img v-if="rightImage" :src="rightImage.url" :alt="rightImage.fileName" /><el-empty v-else description="暂无图片" /></div>
        <footer>{{ rightImage?.fileName || '--' }}<span>{{ rightImage?.detectionTime || '' }}</span></footer>
      </article>
    </div>
    <div class="comparison-meta"><span>SHA-256：{{ leftImage?.sha256 || rightImage?.sha256 || '--' }}</span><span>切换图片时左右面板同步</span></div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  left: { type: Object, default: () => ({ images: [] }) },
  right: { type: Object, default: () => ({ images: [] }) },
  initialIndex: { type: Number, default: 0 },
})
const emit = defineEmits(['select', 'change'])
const currentIndex = ref(props.initialIndex)
const leftImages = computed(() => props.left.images || [])
const rightImages = computed(() => props.right.images || [])
const maxCount = computed(() => Math.max(leftImages.value.length, rightImages.value.length, 1))
const leftImage = computed(() => leftImages.value[currentIndex.value])
const rightImage = computed(() => rightImages.value[currentIndex.value])
watch(() => props.initialIndex, value => { currentIndex.value = Math.max(0, Math.min(value, maxCount.value - 1)) })
watch(maxCount, value => { if (currentIndex.value >= value) currentIndex.value = Math.max(0, value - 1) })
function move(step) {
  const next = Math.max(0, Math.min(currentIndex.value + step, maxCount.value - 1))
  if (next !== currentIndex.value) { currentIndex.value = next; emitChange() }
}
function emitChange() { emit('change', currentIndex.value) }
</script>

<style scoped>
.duplicate-comparison { background: #fff; border: 1px solid var(--el-border-color-lighter); border-radius: 10px; padding: 14px; }
.comparison-toolbar, .comparison-toolbar > div, .comparison-actions { display: flex; align-items: center; gap: 8px; }
.comparison-toolbar { justify-content: space-between; margin-bottom: 12px; }
.comparison-index { color: var(--el-text-color-secondary); font-size: 12px; }
.comparison-panes { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.comparison-pane { min-width: 0; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; overflow: hidden; }
.comparison-pane header, .comparison-pane footer { display: flex; justify-content: space-between; padding: 8px 10px; background: #f8fafc; font-size: 13px; }
.comparison-pane header small, .comparison-pane footer span { color: var(--el-text-color-secondary); }
.image-stage { height: 360px; display: flex; align-items: center; justify-content: center; background: #111827; }
.image-stage img { max-width: 100%; max-height: 100%; object-fit: contain; }
.comparison-meta { display: flex; justify-content: space-between; margin-top: 10px; color: var(--el-text-color-secondary); font-size: 12px; }
@media (max-width: 800px) { .comparison-panes { grid-template-columns: 1fr; } .image-stage { height: 260px; } .comparison-toolbar { align-items: flex-start; flex-direction: column; } }
</style>
