<template>
  <section v-if="rows.length || error || availability" class="detection-transfer-reviews" :class="{'is-unavailable':compact}" aria-label="检测创建结果核对">
    <details v-if="availability" class="transfer-availability"><summary><AppIcon name="DocumentChecked" :size="15" />检测创建核对暂不可用</summary><p role="status">{{ availabilityMessage }}</p><el-button size="small" :loading="loading" :disabled="hasCurrentWrite()" @click="refresh">重新读取能力与状态</el-button></details>
    <header v-if="!compact" class="transfer-heading"><strong><AppIcon name="DocumentChecked" :size="17" />检测创建结果核对</strong><el-button size="small" :loading="loading" :disabled="hasCurrentWrite()" @click="refresh">刷新状态</el-button></header>
    <p v-if="!compact" class="transfer-intro">核对原创建命令的文件与回执，再决定是否完成创建。此处不重新上传图片。</p>
    <p v-if="loading" class="transfer-read-note" role="status">{{ rows.length ? '正在读取，当前保留上次快照；读取完成前不能提交处置。' : '正在读取核对状态；读取完成前不能提交处置。' }}</p>
    <p v-if="error" role="alert" class="transfer-error">{{ error }}</p>
    <p v-if="(error || availability) && lastRequest" class="transfer-read-note">操作请求 {{ operationNames[lastRequest.action] }} · 请求 <code>{{ lastRequest.requestId }}</code>。请保留编号核对，不会自动重发。</p>
    <article v-for="row in rows" :key="row.commandId" class="transfer-record" :data-status="row.status" :aria-busy="busy.has(row.commandId)">
      <header class="transfer-record-heading"><div><small>检测任务</small><strong>{{ row.taskId }}</strong></div><StatusBadge domain="detectionCreation" :code="row.status" /></header>
      <dl class="transfer-metrics">
        <div><dt>目标图片清单</dt><dd>{{ row.manifestAvailable ? transferCount(row.images) + ' 张' : '清单不完整' }}</dd></div>
        <div><dt>存储已记录</dt><dd>{{ transferCount(row.acknowledged) }} 张</dd></div>
        <div><dt>核对内容一致</dt><dd>{{ row.checkStatus ? transferCount(row.verified) + ' 张' : '尚未核对' }}</dd></div>
      </dl>
      <div v-if="row.checkStatus" class="transfer-check-line"><StatusBadge domain="transferCheck" :code="row.checkStatus" /><span>已检查 {{ transferCount(row.checked) }} / {{ transferCount(row.images) }} 张</span></div>
      <p v-if="row.checkStatus">最近核对 {{ formatTime(row.checkedAt) }} UTC+8</p>
      <p class="transfer-next-step">{{ transferNextStep(row, verified) }}</p>
      <p v-if="busy.has(row.commandId)" class="transfer-read-note" role="status">{{ operationNames[busy.get(row.commandId).action] }}已提交，正在等待原回执；不会重复发送。</p>
      <a v-if="row.status === 'QUEUED'" class="transfer-task-link" :href="cardRoute('TASKS', row.taskId)" target="_blank" rel="noopener noreferrer">查看检测任务<AppIcon name="TopRight" :size="14" /></a>
      <details class="transfer-evidence"><summary>编号与核对依据</summary><dl><dt>创建命令</dt><dd><code>{{ row.commandId }}</code></dd><dt>命令版本</dt><dd>V{{ row.revision }}</dd><dt>核对记录</dt><dd><code>{{ row.checkId || '尚未记录' }}</code></dd><template v-if="typeof row.reasonCode === 'string' && row.reasonCode"><dt>原因代码</dt><dd><code>{{ row.reasonCode }}</code></dd></template></dl></details>
      <template v-if="row.status === 'NEEDS_REVIEW'">
        <p class="transfer-cost-note"><AppIcon name="Warning" :size="15" /><span>只读核对会读取目标图片并计算摘要，可能产生存储读取和流量费用。不会重传图片，完成创建仍需本人确认。</span></p>
        <div class="transfer-buttons">
          <el-button :loading="busy.get(row.commandId)?.action === 'CHECK'" :disabled="!verified || busy.has(row.commandId) || !canCheckTransfer(row)" @click="send(row, 'CHECK')"><AppIcon name="Search" :size="14" />只读核对</el-button>
          <el-button type="primary" :disabled="!verified || busy.has(row.commandId) || !row.canFinalize" @click="choose(row, 'FINALIZE')">完成原创建</el-button>
          <el-button type="danger" plain :disabled="!verified || busy.has(row.commandId)" @click="choose(row, 'ABANDON')">终止创建</el-button>
        </div>
      </template>
      <div v-if="decision?.id === row.commandId" class="transfer-decision" :data-action="decision.action" role="group" aria-label="确认原创建命令的处置">
        <strong>{{ decision.action === 'FINALIZE' ? '确认完成原创建' : '确认终止原创建' }} · V{{ decision.revision }}</strong>
        <p>{{ transferDecision(decision.action) }}</p><p v-if="!transferDecisionMatches(decision, row)" role="status">记录已变化，请返回并重新核对，不沿用旧确认。</p>
        <div class="transfer-decision-actions"><el-button :type="decision.action === 'ABANDON' ? 'danger' : 'primary'" :disabled="!verified || busy.has(row.commandId) || !transferDecisionMatches(decision, row)" @click="send(row, decision.action)">确认{{ decision.action === 'FINALIZE' ? '完成创建' : '终止' }}</el-button><el-button @click="decision = null">返回核对</el-button></div>
      </div>
    </article>
    <p v-if="rows.length" class="transfer-intro">本次读取 {{ transferCount(rows.length) }} 条，接口最多返回 20 条；此处不代表全部创建历史。</p>
  </section>
</template>
<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import request from '@/api/request'
import { useUserStore } from '@/stores/user'
import { validTransferReview, canCheckTransfer, transferDecision, transferCount, transferNextStep, transferDecisionSnapshot, transferDecisionMatches, transferPayload, transferCapability, transferReadIssue, transferFailureStatus, transferDisabledMessage } from '@/utils/detectionCreationReview'
import { beijingDateTime } from '@/utils/beijingTime'
import { cardRoute } from '@/utils/agentCards'
import '@/assets/detection-creation-review.css'
const props = defineProps({ sessionId: String, refreshKey: [String, Number] })
const emit = defineEmits(['changed'])
const userStore = useUserStore()
const actor = computed(() => JSON.stringify([userStore.identity?.userId || userStore.username || '', userStore.role, userStore.isAuthenticated]))
const rows = ref([]), error = ref(''), loading = ref(false), verified = ref(false), busy = ref(new Map()), decision = ref(null), lastRequest = ref(null)
const availability = ref(''), availabilityMessage = ref('')
const compact = computed(() => !!availability.value && !rows.value.length && !lastRequest.value)
const operationNames = { CHECK: '只读核对', FINALIZE: '完成原创建', ABANDON: '终止创建' }
const formatTime = value => value ? beijingDateTime(value) || '时间未记录' : '时间未记录'
let scopeGeneration = 0, readGeneration = 0, activeRead
const endpoint = () => '/api/agent/conversations/' + encodeURIComponent(props.sessionId) + '/detection-creations'
function hasCurrentWrite() { return [...busy.value.values()].some(value => value.scope === scopeGeneration) }
function stopRead() { readGeneration++; activeRead?.abort(); activeRead = null; loading.value = false }
async function refresh() {
  if (!props.sessionId || !userStore.isAuthenticated || hasCurrentWrite()) return
  stopRead(); const version = ++readGeneration, scope = scopeGeneration, controller = new AbortController()
  activeRead = controller; loading.value = true; verified.value = false; decision.value = null; error.value = ''
  try {
    let support='UNKNOWN'
    try { const capability=await request.get('/api/agent/workbench/capabilities',{signal:controller.signal}); support=transferCapability(capability.data) }
    catch(failure) { if(transferFailureStatus(failure)!==404)throw failure }
    if (scope !== scopeGeneration || version !== readGeneration || controller.signal.aborted) return
    if(support==='DISABLED'){rows.value=[];availability.value='DISABLED';availabilityMessage.value=transferDisabledMessage;return}
    const response = await request.get(endpoint(), { signal: controller.signal })
    if (scope !== scopeGeneration || version !== readGeneration) return
    const data=transferPayload(response.data)
    if (!Array.isArray(data) || !data.every(validTransferReview)) throw new Error()
    rows.value = data; verified.value = true; availability.value='';availabilityMessage.value=''
  } catch (failure) {
    if (scope !== scopeGeneration || version !== readGeneration || controller.signal.aborted) return
    const issue=transferReadIssue(failure,rows.value.length>0)
    if(issue.clear)rows.value=[]
    availability.value=issue.availability;availabilityMessage.value=issue.availability?issue.message:''
    error.value=issue.availability?'':issue.message
  } finally { if (scope === scopeGeneration && version === readGeneration) { activeRead = null; loading.value = false } }
}
function choose(row, action) {
  if (!verified.value || activeRead || busy.value.has(row.commandId) || row.status !== 'NEEDS_REVIEW' || !['FINALIZE', 'ABANDON'].includes(action) || (action === 'FINALIZE' && !row.canFinalize)) return
  decision.value = transferDecisionSnapshot(row, action)
}
async function send(row, action) {
  if (!verified.value || activeRead || busy.value.has(row.commandId) || row.status !== 'NEEDS_REVIEW' || !Object.hasOwn(operationNames, action)) return
  if (action === 'CHECK' ? !canCheckTransfer(row) : !transferDecisionMatches(decision.value, row) || decision.value.action !== action || (action === 'FINALIZE' && !row.canFinalize)) return
  const scope = scopeGeneration, requestId = crypto.randomUUID()
  busy.value = new Map([...busy.value, [row.commandId, { action, requestId, scope }]])
  lastRequest.value = { requestId, action }; decision.value = null; error.value = ''
  try {
    const response = await request.post(endpoint() + '/' + encodeURIComponent(row.commandId) + '/review', { requestId, revision: row.revision, action, ...(action === 'FINALIZE' ? { checkId: row.checkId } : {}) }, { headers: { 'X-Agent-Action': 'workbench', 'X-Request-ID': requestId } })
    if (scope !== scopeGeneration) return
    const data=transferPayload(response.data)
    if (!validTransferReview(data) || data.commandId !== row.commandId) throw new Error()
    rows.value = rows.value.map(value => value.commandId === row.commandId ? data : value); emit('changed')
  } catch (failure) {
    if (scope !== scopeGeneration) return
    verified.value = false; lastRequest.value = { requestId, action }
    if ([401, 403, 404].includes(transferFailureStatus(failure))) rows.value = []
    error.value = failure.response?.data?.message || '操作结果尚未核实，请刷新原命令状态。保留本次请求编号，不会自动重发。'
  } finally {
    if (busy.value.get(row.commandId)?.requestId === requestId) { const next = new Map(busy.value); next.delete(row.commandId); busy.value = next }
  }
}
watch(() => JSON.stringify([props.sessionId, actor.value]), () => { scopeGeneration++; stopRead(); rows.value = []; decision.value = null; lastRequest.value = null; error.value = ''; availability.value='';availabilityMessage.value='';verified.value = false; refresh() }, { immediate: true, flush: 'sync' })
watch(() => props.refreshKey, refresh)
onBeforeUnmount(() => { scopeGeneration++; stopRead() })
</script>
