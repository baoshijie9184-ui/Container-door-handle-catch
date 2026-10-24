<template>
  <section v-if="rows.length" class="proposal-gallery" :aria-label="label">
    <div class="proposal-gallery-heading"><strong><AppIcon name="Picture" :size="15" />{{ label }}</strong><span>{{ rows.length.toLocaleString('zh-CN') }} 张预览资料</span></div>
    <div class="proposal-gallery-grid" tabindex="0" :aria-label="label + '缩略图，可滚动阅读'">
      <figure v-for="(row, index) in rows" :key="row.key">
        <button v-if="row.path && !failed.has(row.key)" type="button" class="proposal-image-button" aria-haspopup="dialog" :aria-label="'放大图片 ' + row.name" @click="select(index)">
          <img :key="attempts[row.key] || 0" :src="row.path" :alt="row.name" loading="lazy" decoding="async" referrerpolicy="no-referrer" @load="mark(row.key, true)" @error="mark(row.key, false)" />
          <span class="proposal-image-overlay"><AppIcon :name="loaded.has(row.key) ? 'Search' : 'Connection'" :size="14" />{{ loaded.has(row.key) ? '放大核对' : '正在读取' }}</span>
        </button>
        <div v-else class="proposal-image-fallback"><AppIcon name="Warning" :size="21" /><span>{{ row.path ? '预览暂不可读取' : '预览地址待核对' }}</span><el-button v-if="row.path" size="small" @click="retry(row)">重新读取</el-button></div>
        <figcaption><strong>{{ row.name }}</strong><span>{{ row.source }}</span></figcaption>
      </figure>
    </div>
    <el-dialog v-model="zoomOpen" class="proposal-image-dialog" title="检测原图核对" width="min(1000px, 94vw)" append-to-body @close="close">
      <template v-if="current">
        <div class="proposal-image-details"><strong>{{ current.name }}</strong><span>{{ current.source }}<template v-if="current.taskId"> · 任务 {{ current.taskId }}</template> · 第 {{ selectedIndex + 1 }} / {{ rows.length }} 张</span></div>
        <p class="proposal-preview-note">此处仅查看原图资料，关闭或翻页不会批准检测。请回到卡片核对图片范围、参数及提议版本后明确确认。</p>
        <div v-if="zoomError" class="proposal-image-fallback proposal-zoom-fallback" role="alert"><AppIcon name="Warning" :size="26" /><strong>图片暂不可读取</strong><span>请核对登录与文件权限，或重新读取原预览。</span><el-button @click="retryZoom">重新读取图片</el-button></div>
        <div v-else class="proposal-zoom-frame"><p v-if="!zoomLoaded" role="status" class="proposal-preview-note">正在读取原图…</p><img :key="current.key + ':' + zoomAttempt" :src="current.path" :alt="current.name" :data-key="current.key" :data-attempt="zoomAttempt" referrerpolicy="no-referrer" @load="zoomEvent($event, true)" @error="zoomEvent($event, false)" /></div>
        <details v-if="current.hash" class="proposal-image-digest"><summary>内容摘要 SHA-256</summary><code>{{ current.hash }}</code></details>
      </template>
      <template #footer><div class="proposal-preview-actions"><div><el-button :disabled="selectedIndex <= 0 || !rows[selectedIndex - 1]?.path" @click="select(selectedIndex - 1)">上一张</el-button><el-button :disabled="selectedIndex < 0 || !rows[selectedIndex + 1]?.path" @click="select(selectedIndex + 1)">下一张</el-button></div><el-button @click="close">关闭图片</el-button></div></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { proposalImageRows } from '@/utils/proposalImages'
import '@/assets/proposal-image-gallery.css'
const props = defineProps({ images: { type: Array, default: () => [] }, scopeKey: { type: String, default: '' }, label: { type: String, default: '提议原图' } })
const rows = computed(() => proposalImageRows(props.images, props.scopeKey))
const failed = ref(new Set()), loaded = ref(new Set()), attempts = ref({})
const selectedIndex = ref(-1), zoomOpen = ref(false), zoomError = ref(false), zoomLoaded = ref(false), zoomAttempt = ref(0)
const current = computed(() => rows.value[selectedIndex.value] || null)
const signature = computed(() => JSON.stringify(rows.value.map(row => row.key)))
function mark(key, success) {
  if (!rows.value.some(row => row.key === key)) return
  if (success) loaded.value = new Set([...loaded.value, key])
  else failed.value = new Set([...failed.value, key])
}
function retry(row) {
  if (!rows.value.some(item => item.key === row.key) || !row.path) return
  attempts.value = { ...attempts.value, [row.key]: (attempts.value[row.key] || 0) + 1 }
  failed.value = new Set([...failed.value].filter(key => key !== row.key)); loaded.value = new Set([...loaded.value].filter(key => key !== row.key))
}
function select(index) { if (!Number.isInteger(index) || !rows.value[index]?.path) return; selectedIndex.value = index; zoomError.value = false; zoomLoaded.value = false; zoomAttempt.value = 0; zoomOpen.value = true }
function close() { zoomOpen.value = false; selectedIndex.value = -1; zoomError.value = false; zoomLoaded.value = false }
function retryZoom() { zoomAttempt.value++; zoomError.value = false; zoomLoaded.value = false }
function zoomEvent(event, success) {
  if (!zoomOpen.value || event.currentTarget.dataset.key !== current.value?.key || Number(event.currentTarget.dataset.attempt) !== zoomAttempt.value) return
  if (success) zoomLoaded.value = true
  else zoomError.value = true
}
watch(signature, () => { close(); failed.value = new Set(); loaded.value = new Set(); attempts.value = {} }, { flush: 'sync' })
</script>
