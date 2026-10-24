<template>
  <section class="proposal-originals" aria-label="检测任务原图资料" :aria-busy="loading">
    <div class="proposal-originals-toolbar"><span>核对已有任务的原图</span><el-button size="small" :loading="loading" @click="refresh"><AppIcon name="Refresh" :size="14" />重新读取资料</el-button></div>
    <p v-if="loading" class="proposal-originals-note" role="status">{{ images.length ? '正在读取，当前保留上次原图资料快照。' : '正在读取原图资料…' }}</p>
    <p v-if="error" class="proposal-originals-error" role="alert">{{ error }}</p>
    <ProposalImageGallery :images="images" :scope-key="JSON.stringify([taskId, proposalVersion])" label="任务原图" />
    <p v-if="images.length" class="proposal-originals-note">本次返回 {{ images.length.toLocaleString('zh-CN') }} 张预览，{{ Number.isSafeInteger(count) && count >= 0 ? `提议共 ${count.toLocaleString('zh-CN')} 张` : '提议图片总数未记录' }}。检测范围仍以原卡片及其版本为准。</p>
    <p v-else-if="hasLoaded && !loading && !error" class="proposal-originals-note">本次没有返回可预览原图。请到检测记录核对，不能据此认为原任务没有图片。</p>
  </section>
</template>
<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import request from '@/api/request'
import { businessImagePreview } from '@/utils/agentActions'
import { useUserStore } from '@/stores/user'
import ProposalImageGallery from './ProposalImageGallery.vue'
const props = defineProps({ taskId: String, count: Number, proposalVersion: Number, refreshKey: [String, Number] })
const userStore = useUserStore()
const actor = computed(() => JSON.stringify([userStore.identity?.userId || userStore.username || '', userStore.role, userStore.isAuthenticated]))
const images = ref([]), error = ref(''), loading = ref(false), hasLoaded = ref(false)
let generation = 0, controller
function stopRead() { generation++; controller?.abort(); controller = null; loading.value = false }
async function refresh() {
  stopRead()
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(props.taskId || '')) { error.value = '任务编号不完整，无法核对原图资料。'; return }
  if (!userStore.isAuthenticated) { images.value = []; error.value = '请确认登录账号后重新读取原图资料。'; return }
  const version = ++generation, taskId = props.taskId, currentRead = new AbortController()
  controller = currentRead; loading.value = true; error.value = ''
  try {
    const { data } = await request.get('/api/agent/business-files/DETECTION/' + encodeURIComponent(taskId) + '/originals', { signal: currentRead.signal })
    if (version !== generation) return
    if (!Array.isArray(data) || !data.every(image => image && image.resourceId === taskId && typeof image.name === 'string' && businessImagePreview(image))) throw new Error()
    images.value = data; hasLoaded.value = true
  } catch (failure) {
    if (version !== generation || currentRead.signal.aborted) return
    if ([401, 403, 404].includes(failure.response?.status)) { images.value = []; hasLoaded.value = false; error.value = '当前账号无法读取该任务原图，请核对任务及文件权限。' }
    else error.value = '原图资料暂不可读取。已显示资料仅为上次快照，请重新读取或到检测记录核对。'
  } finally { if (version === generation) { controller = null; loading.value = false } }
}
watch(() => JSON.stringify([props.taskId, props.proposalVersion, actor.value]), () => { stopRead(); images.value = []; hasLoaded.value = false; error.value = ''; refresh() }, { immediate: true, flush: 'sync' })
watch(() => props.refreshKey, refresh)
onBeforeUnmount(stopRead)
</script>
