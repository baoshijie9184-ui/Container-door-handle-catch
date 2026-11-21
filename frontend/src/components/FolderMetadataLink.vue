<template>
  <button type="button" class="metadata-link" aria-haspopup="dialog" @click="openDetails">元数据</button>
  <el-dialog v-if="opened" :model-value="true" title="文件夹元数据" width="min(560px, 94vw)"
    append-to-body destroy-on-close @update:model-value="value => { if (!value) close() }">
    <div v-if="loading" role="status">正在读取元数据…</div>
    <div v-else-if="error" role="alert">{{ error }} <el-button link type="primary" @click="load">重新读取</el-button></div>
    <template v-else-if="metadata">
      <h3 class="metadata-name"><AppIcon name="FolderOpened" :size="20" />{{ recordFolderLabel(metadata) }}</h3>
      <dl class="metadata-fields">
        <div><dt>图片数量</dt><dd>{{ metadata.totalImages == null ? '未登记' : metadata.totalImages+' 张' }}</dd></div>
        <div><dt>登记时间</dt><dd>{{ metadata.registeredAt || '未登记' }}</dd></div>
        <div><dt>上传人工号</dt><dd>{{ metadata.creator || '未关联' }}</dd></div>
        <div><dt>上传人姓名</dt><dd>{{ metadata.creatorName || '未登记' }}</dd></div>
        <template v-if="Number(metadata.canReadTask)">
          <div><dt>采集城市</dt><dd>{{ metadata.city || '未登记' }}</dd></div>
          <div><dt>采集日期</dt><dd>{{ metadata.captureDate || '未登记' }}</dd></div>
          <div><dt>采集员</dt><dd>{{ metadata.collector || '未登记' }}</dd></div>
          <div><dt>采集设备</dt><dd>{{ metadata.device || '未登记' }}</dd></div>
          <div v-if="metadata.uploadFolder && metadata.uploadFolder!==recordFolderLabel(metadata)" class="full"><dt>上传登记名称</dt><dd>{{ metadata.uploadFolder }}</dd></div>
        </template>
        <div class="full"><dt>任务编号</dt><dd><code>{{ metadata.taskId }}</code></dd></div>
        <div v-if="Number(metadata.canReadTask)" class="full"><dt>{{ metadata.prefix?.startsWith('detection/') ? 'OSS 原图目录' : '原图存储路径' }}</dt><dd><code>{{ metadata.prefix || '未登记' }}</code></dd></div>
      </dl>
    </template>
  </el-dialog>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { captureAccountRequest } from '@/api/request'
import { useUserStore } from '@/stores/user'
import { recordFolderLabel } from '@/utils/imageFolderLabel'

const props = defineProps({ taskId: { type: String, required: true } })
const user = useUserStore()
const opened = ref(false), loading = ref(false), error = ref(''), metadata = ref(null)
let controller
function close() {
  controller?.abort()
  controller = null
  opened.value = false
  metadata.value = null
  error.value = ''
}
function openDetails() {
  opened.value = true
  load()
}
async function load() {
  controller?.abort()
  const pending = new AbortController()
  controller = pending
  loading.value = true
  error.value = ''
  try {
    const { data } = await captureAccountRequest().get('/api/detection/board/'+encodeURIComponent(props.taskId)+'/folder-metadata', { signal: pending.signal })
    if (data?.code !== 200 || data.data?.taskId !== props.taskId) throw Error(data?.message || '文件夹元数据读取失败')
    if (!pending.signal.aborted) metadata.value = data.data
  } catch (e) {
    if (!pending.signal.aborted) error.value = e.response?.data?.message || e.message || '文件夹元数据读取失败'
  } finally {
    if (!pending.signal.aborted) loading.value = false
  }
}
watch(() => [props.taskId, user.accountContext, user.username, user.role], close, { flush:'sync' })
onBeforeUnmount(close)
</script>

<style scoped>
.metadata-link { padding:2px 0;background:none;border:0;color:var(--app-primary);font:inherit;font-size:12px;cursor:pointer }
.metadata-link:hover { text-decoration:underline }.metadata-link:focus-visible { outline:2px solid currentColor;outline-offset:3px }
.metadata-name { display:flex;align-items:center;gap:8px;margin:0 0 14px;font-size:17px;color:var(--app-text);overflow-wrap:anywhere }
.metadata-fields { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 20px;margin:0 }
.metadata-fields dt { color:var(--app-text-secondary);font-size:12px }.metadata-fields dd { margin:4px 0 0;overflow-wrap:anywhere;color:var(--app-text) }
.metadata-fields .full { grid-column:1/-1;border-top:1px solid var(--app-border);padding-top:10px }.metadata-fields code { font-size:12px;white-space:pre-wrap }
</style>
