<template>
  <section class="applications app-panel" aria-labelledby="my-applications" :aria-busy="loading">
    <header>
      <div class="application-overview">
        <h2 id="my-applications">我的检测申请</h2>
        <p v-if="loaded && !loadError && !keyword && (waitingCount || rejectedCount)" class="application-summary">
          <span v-if="waitingCount">待主管审批 {{ waitingCount }} 条</span>
          <span v-if="rejectedCount">已驳回 {{ rejectedCount }} 条</span>
        </p>
        <p v-else-if="keyword" class="application-summary">按申请编号筛选</p>
      </div>
      <router-link v-if="keyword" :to="allApplications" @click="historyOpen = true">查看全部申请</router-link>
      <el-button v-else link type="primary" aria-controls="my-application-history" :aria-expanded="historyExpanded" @click="historyOpen = !historyOpen">
        {{ historyExpanded ? '收起申请记录' : loaded && !loadError ? '查看申请记录（'+rows.length+'）' : '查看申请记录' }}
      </el-button>
    </header>
    <el-alert v-if="loadError" :title="loadError" type="warning" :closable="false" role="alert">
      <el-button link type="primary" :loading="loading" @click="load()">重新读取</el-button>
    </el-alert>
    <div v-show="historyExpanded" id="my-application-history" class="application-history">
      <ul v-if="historyExpanded && !loadError && visibleRows.length">
        <li v-for="{ row, createdAt, imageCount } in visibleRows" :key="row.workUnitId" :data-status="row.status">
          <div class="application-record">
            <div class="application-record-heading">
              <strong>{{ statusLabel(row) }}</strong>
              <small v-if="imageCount != null">最多 {{ imageCount }} 张</small>
              <small v-if="createdAt">申请于 {{ createdAt }}</small>
            </div>
            <p v-if="row.remark" class="application-note">{{ row.remark }}</p>
            <p v-if="row.status==='REJECTED' && row.decisionReason" class="application-reason">
              <strong>驳回原因</strong> {{ row.decisionReason }}
            </p>
          </div>
          <div class="application-row-actions">
            <router-link v-if="linkedTask(row)" :to="{path:'/inspection/tasks',query:{inbox:'0',keyword:row.batchId}}">查看已派任务</router-link>
            <el-button v-else-if="row.status==='WAITING' && needsDetectionBatch(row)" link type="danger"
              @click="withdrawal=row">撤回申请</el-button>
            <details class="application-identifiers">
              <summary>编号</summary>
              <dl>
                <dt>申请编号</dt><dd><code>{{ row.workUnitId }}</code></dd>
                <template v-if="row.sourceBatchId"><dt>原图批次编号</dt><dd><code>{{ row.sourceBatchId }}</code></dd></template>
                <template v-if="linkedTask(row)"><dt>已派任务编号</dt><dd><code>{{ row.batchId }}</code></dd></template>
              </dl>
            </details>
          </div>
        </li>
      </ul>
      <p v-else-if="loaded && !loadError">{{ keyword ? '没有匹配的检测申请' : '暂无检测申请' }}</p>
      <el-button v-if="!loadError" link type="primary" :loading="loading" @click="load()">刷新申请</el-button>
    </div>
    <WorkUnitApplicationDecision v-if="withdrawal" :application="withdrawal" action="withdraw"
      @close="withdrawal=null" @completed="recordWithdrawal" @refresh="load()" />
    <el-dialog v-model="dialog" title="申请检测任务" width="min(460px, 94vw)" destroy-on-close
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
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { captureAccountRequest } from '@/api/request'
import { useUserStore } from '@/stores/user'
import { beijingDateTime } from '@/utils/beijingTime'
import { knownCount } from '@/utils/countPresentation'
import { needsDetectionBatch } from '@/utils/workUnitApplications'
import WorkUnitApplicationDecision from './WorkUnitApplicationDecision.vue'

const props = defineProps({ keyword: {type:String, default:''} })
const endpoint = '/api/detection/tasks/work-units'
const api = captureAccountRequest()
const user = useUserStore()
const route = useRoute()
const rows = ref([]), loaded = ref(false), loading = ref(false), loadError = ref('')
const dialog = ref(false), saving = ref(false), saveError = ref('')
const imageCount = ref(1), remark = ref(''), submitted = ref(null)
const withdrawal = ref(null), historyOpen = ref(false)
let timer, disposed = false, reading = false, read = 0

const historyExpanded = computed(() => Boolean(props.keyword) || historyOpen.value)
const allApplications = computed(() => ({path:route.path, query:{...route.query, keyword:undefined, page:undefined}}))
const waitingCount = computed(() => rows.value.filter(row => row.status === 'WAITING').length)
const rejectedCount = computed(() => rows.value.filter(row => row.status === 'REJECTED').length)
const visibleRows = computed(() => {
  const matching = props.keyword ? rows.value.filter(row => row.workUnitId === props.keyword) : rows.value
  return matching.map(row => ({
    row,
    createdAt: row.createdAt ? beijingDateTime(row.createdAt).slice(0, 16) : '',
    imageCount: knownCount(row.imageCount)
  }))
})
const linkedTask = row => /^det_folder_[a-f0-9]{32}$/.test(row.batchId || '')
function statusLabel(row) {
  if (linkedTask(row)) return '已派单'
  return {WAITING:'待主管审批',ASSIGNED:'待主管指定原图',PROCESSING:'处理中',SUBMITTED:'已提交',REJECTED:'已驳回',WITHDRAWN:'已撤回'}[row.status] || row.status
}
function open() {
  imageCount.value = 1
  remark.value = ''
  submitted.value = null
  saveError.value = ''
  dialog.value = true
}
defineExpose({ open })
async function load(quiet = false) {
  if (disposed || (quiet && reading)) return
  const generation = ++read
  reading = true
  loading.value = !quiet || !loaded.value
  try {
    const {data} = await api.get(endpoint + '/mine')
    if (data?.code !== 200 || !Array.isArray(data.data)) throw new Error('申请记录读取失败')
    if (disposed || generation !== read) return
    rows.value = data.data.filter(row => row.applicantUserId === user.username)
    loaded.value = true
    loadError.value = ''
  } catch {
    if (!disposed && generation === read && (!quiet || !loaded.value)) loadError.value = '申请记录暂不可读取，请刷新。'
  } finally {
    if (generation === read) reading = false
    if (!disposed && generation === read) loading.value = false
  }
}
function recordWithdrawal(saved) {
  rows.value = rows.value.map(row => row.workUnitId === saved.workUnitId ? saved : row)
  ElMessage.success('申请已撤回')
  withdrawal.value = null
  void load()
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
    dialog.value = false
    ElMessage.success(linkedTask(data.data) ? '申请已派单' : '申请已提交')
    await load()
  } catch (error) {
    if (!disposed) saveError.value = error.response?.data?.message || error.message || '申请结果暂未确认，请重试提交。'
  } finally {
    if (!disposed) saving.value = false
  }
}
onMounted(() => {
  load()
  timer = window.setInterval(() => { if (!dialog.value && !withdrawal.value && !document.hidden) load(true) }, 6000)
})
onBeforeUnmount(() => { disposed = true; window.clearInterval(timer) })
</script>

<style scoped>
.applications { padding: 10px 16px; min-width: 0; }
.applications header, .applications li, .application-overview, .application-summary, .application-record-heading,
.application-row-actions, .application-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; }
.applications header, .applications li { justify-content: space-between; }
.applications header { min-height: 34px; }
.applications h2 { margin: 0; font-size: 15px; }
.applications p, .applications small { color: var(--app-text-secondary); font-size: 13px; }
.applications p { margin: 0; }
.applications header a, .applications li a { color: var(--app-primary); font-size: 13px; }
.application-history { padding-top: 4px; }
.application-history ul { margin: 0; padding: 0; list-style: none; }
.applications li { align-items: baseline; padding: 10px 0; border-top: 1px solid var(--app-border); overflow-wrap: anywhere; }
.application-record { flex: 1 1 300px; min-width: 0; }
.application-record-heading strong { font-size: 14px; }
.applications li[data-status=REJECTED] .application-record-heading strong { color: var(--app-danger); }
.applications li[data-status=WAITING] .application-record-heading strong { color: var(--app-primary); }
.application-record .application-note, .application-record .application-reason { margin-top: 4px; }
.application-identifiers { max-width: 100%; min-width: 0; }
.application-identifiers summary { color: var(--app-text-secondary); cursor: pointer; font-size: 13px; }
.application-identifiers dl { margin: 7px 0 0; }
.application-identifiers dt { margin-top: 4px; color: var(--app-text-secondary); font-size: 12px; }
.application-identifiers dd { margin: 0; overflow-wrap: anywhere; font-size: 12px; }
.applications > .el-alert { margin-top: 6px; }
.application-actions :deep(.el-button) { margin: 0; min-height: 44px; }
.dialog-actions { justify-content: flex-end; margin-top: 14px; }
</style>
