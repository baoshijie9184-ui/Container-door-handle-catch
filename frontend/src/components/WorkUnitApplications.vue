<template>
  <section class="applications app-panel" aria-labelledby="my-applications" :aria-busy="loading">
    <header>
      <h2 id="my-applications">我的领任务申请</h2>
      <div class="application-actions">
        <el-button :loading="loading" @click="load()">刷新申请</el-button>
        <el-button type="primary" @click="open">申请领任务</el-button>
      </div>
    </header>
    <p v-if="notice" role="status">{{ notice }}</p>
    <el-alert v-if="loadError" :title="loadError" type="warning" :closable="false" role="alert" />
    <template v-else>
      <ul v-if="visibleRows.length">
        <li v-for="row in visibleRows" :key="row.workUnitId">
          <span><strong>{{ statusLabel(row) }}</strong><small>{{ row.workUnitId }} · 最多 {{ row.imageCount }} 张</small></span>
          <router-link v-if="linkedTask(row)" :to="{path:'/inspection/tasks',query:{inbox:'0',keyword:row.batchId}}">查看已派任务</router-link>
        </li>
      </ul>
      <p v-else-if="loaded">{{ keyword ? '没有匹配的领任务申请' : '暂无领任务申请' }}</p>
    </template>
    <el-dialog v-model="dialog" title="申请领任务" width="min(460px, 94vw)" destroy-on-close
      :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving">
      <el-form label-position="top" @submit.prevent="apply">
        <el-form-item label="最多处理图片数" for="application-image-count">
          <el-input-number id="application-image-count" v-model="imageCount" :min="1" :max="5000" :precision="0" :disabled="!!submitted" />
        </el-form-item>
        <el-form-item label="备注（选填）" for="application-remark">
          <el-input id="application-remark" v-model="remark" type="textarea" :maxlength="1000" :disabled="!!submitted" />
        </el-form-item>
        <el-alert v-if="saveError" :title="saveError" type="error" :closable="false" role="alert" />
        <div class="application-actions dialog-actions">
          <el-button :disabled="saving" @click="dialog=false">取消</el-button>
          <el-button type="primary" native-type="submit" :loading="saving" :disabled="!imageCount">
            {{ submitted && saveError ? '重试提交' : '提交申请' }}
          </el-button>
        </div>
      </el-form>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { captureAccountRequest } from '@/api/request'
import { useUserStore } from '@/stores/user'

const props = defineProps({ keyword: {type:String, default:''} })
const endpoint = '/api/detection/tasks/work-units'
const api = captureAccountRequest()
const user = useUserStore()
const rows = ref([]), loaded = ref(false), loading = ref(false), loadError = ref('')
const dialog = ref(false), saving = ref(false), saveError = ref(''), notice = ref('')
const imageCount = ref(1), remark = ref(''), submitted = ref(null)
let timer, disposed = false, reading = false

const visibleRows = computed(() => {
  const matching = props.keyword ? rows.value.filter(row => row.workUnitId === props.keyword) : rows.value
  return matching.slice(0, 5)
})
const linkedTask = row => /^det_folder_[a-f0-9]{32}$/.test(row.batchId || '')
function statusLabel(row) {
  if (linkedTask(row)) return '已派单'
  return {WAITING:'待主管审批',ASSIGNED:'待主管指定原图',PROCESSING:'处理中',SUBMITTED:'已提交'}[row.status] || row.status
}
function open() {
  imageCount.value = 1
  remark.value = ''
  submitted.value = null
  saveError.value = ''
  dialog.value = true
}
async function load(quiet = false) {
  if (reading || disposed) return
  reading = true
  loading.value = !quiet || !loaded.value
  try {
    const {data} = await api.get(endpoint + '/mine')
    if (data?.code !== 200 || !Array.isArray(data.data)) throw new Error('申请记录读取失败')
    if (disposed) return
    rows.value = data.data.filter(row => row.applicantUserId === user.username)
    loaded.value = true
    loadError.value = ''
  } catch {
    if (!disposed && (!quiet || !loaded.value)) loadError.value = '申请记录暂不可读取，请刷新。'
  } finally {
    reading = false
    if (!disposed) loading.value = false
  }
}
async function apply() {
  if (saving.value || !imageCount.value) return
  submitted.value ??= {requestId:crypto.randomUUID(),imageCount:imageCount.value,remark:remark.value.trim() || null}
  saving.value = true
  saveError.value = ''
  try {
    const {data} = await api.post(endpoint + '/apply', submitted.value)
    if (data?.code !== 200 || !data.data?.workUnitId) throw new Error(data?.message || '申请结果暂未确认')
    if (disposed) return
    rows.value = [data.data, ...rows.value.filter(row => row.workUnitId !== data.data.workUnitId)]
    notice.value = (linkedTask(data.data) ? '申请已派单 · ' : '申请已提交 · ') + data.data.workUnitId
    dialog.value = false
    await load()
  } catch (error) {
    if (!disposed) saveError.value = error.response?.data?.message || error.message || '申请结果暂未确认，请重试提交。'
  } finally {
    if (!disposed) saving.value = false
  }
}
onMounted(() => {
  load()
  timer = window.setInterval(() => { if (!dialog.value && !document.hidden) load(true) }, 6000)
})
onBeforeUnmount(() => { disposed = true; window.clearInterval(timer) })
</script>

<style scoped>
.applications { padding: 14px 16px; min-width: 0; }
.applications header, .applications li, .application-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.applications header, .applications li { justify-content: space-between; }
.applications h2 { margin: 0; font-size: 16px; }
.applications p, .applications small { color: var(--app-text-secondary); font-size: 13px; }
.applications p { margin: 8px 0 0; }
.applications ul { margin: 8px 0 0; padding: 0; list-style: none; }
.applications li { padding-top: 8px; margin-top: 8px; border-top: 1px solid var(--app-border); overflow-wrap: anywhere; }
.applications small { display: block; margin-top: 3px; }
.applications li a { color: var(--app-primary); }
.application-actions :deep(.el-button) { margin: 0; min-height: 44px; }
.dialog-actions { justify-content: flex-end; margin-top: 14px; }
</style>
