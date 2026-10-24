<template>
  <DetectionCreationReview :session-id="sessionId" :refresh-key="refreshKey" @changed="refresh" />
  <section v-if="standalone || (!disabled && (actions.length || error))" class="agent-actions agent-action-list" aria-label="助手操作确认">
    <header class="actions-heading"><strong><AppIcon name="DocumentChecked" :size="16" />助手操作确认</strong><el-button size="small" :loading="loading" @click="refresh">刷新</el-button></header>
    <p v-if="error" role="alert" class="action-error">{{ error }}</p>
    <p v-if="loading" class="action-read-feedback" role="status">{{ actions.length ? '正在核对操作状态，当前保留上次卡片；读取完成前不能确认。' : '正在读取操作提议…' }}</p>
    <p v-else-if="actions.length && !verified" class="action-read-feedback" role="status">当前卡片尚未重新核实，请刷新后再确认。刷新不会重发业务操作。</p>
    <p v-if="disabled" class="empty-note">此环境尚未启用人工确认</p>
    <p v-else-if="!loading && !error && !actions.length" class="empty-note">暂无操作提议 提议保存后仍需明确确认</p>
    <article v-for="action in actions" :key="action.actionId" class="action-card" :data-operation="action.operation" :data-status="action.status" :aria-busy="busy.has(action.actionId)">
      <header><strong><AppIcon name="Lock" :size="16" />{{ action.operation === 'CREATE_DETECTION' ? '创建检测任务' : action.operation === 'RETRY_DETECTION' ? '重新检测任务' : '分配质检任务' }}</strong><StatusBadge domain="confirmation" :code="action.status" :label="['RETRY_DETECTION', 'CREATE_DETECTION'].includes(action.operation) && action.status === 'SUCCEEDED' ? '已提交检测' : labels[action.status]" /></header>
      <p class="action-review-meta">业务操作确认 · 提议 V{{ action.version }}<span v-if="action.status === 'PENDING'"> · 有效至 {{ beijingDateTime(action.expiresAt ?? null) || '时间未记录' }} UTC+8</span></p>
      <p v-if="action.status === 'PENDING'" class="action-impact"><AppIcon name="Warning" :size="16" /><span>{{ action.creation ? '确认将复制本卡片的已授权图片并创建检测任务。' : action.operation === 'RETRY_DETECTION' ? '确认将提交新的检测，并重置当前检测结果与复核处置。' : '确认将修改下方任务的质检分配信息。' }}请核对本卡片参数，计划批准或普通回答不代替此处确认。</span></p>
      <DetectionProposalImages v-if="action.retry" :task-id="action.retry.taskId" :count="action.retry.imageCount" :proposal-version="action.version" :refresh-key="generation" />
      <template v-if="action.creation">
        <ProposalImageGallery :images="action.creation.images" :scope-key="action.actionId + ':' + action.version" label="拟检测原图" />
        <dl><dt>图片数量</dt><dd>{{ action.creation.images.length }} 张</dd>
          <dt>采集日期</dt><dd>{{ action.creation.capture.captureDate }}</dd><dt>采集区域</dt><dd>{{ action.creation.capture.region }}</dd>
          <dt>采集人</dt><dd>{{ action.creation.capture.collector }}</dd><dt>采集设备</dt><dd>{{ action.creation.capture.deviceName }}</dd>
          <dt>批次文件夹</dt><dd>{{ action.creation.capture.imageFolderName }}</dd>
          <dt>检测模型</dt><dd>{{ action.creation.model.name }} · {{ action.creation.model.version }}</dd><dt>阈值</dt><dd>{{ action.creation.threshold }}</dd>
          <dt>提议版本</dt><dd>{{ action.creation.resourceVersion }}</dd>
          <template v-if="action.creationResult"><dt>检测任务</dt><dd>{{ action.creationResult.taskId }}</dd></template>
        </dl>
        <p class="action-note">仅检测本卡片列出的会话上传或已关联业务原图 不自动复核、放行或审批报告</p>
      </template>
      <dl v-else-if="action.operation === 'RETRY_DETECTION' && action.retry">
        <dt>检测任务</dt><dd>{{ action.retry.taskId }}</dd>
        <dt>提议时状态</dt><dd class="action-status-pair"><StatusBadge domain="detection" :code="action.retry.status" /><StatusBadge v-if="action.retry.flowStatus" domain="flow" :code="action.retry.flowStatus" /></dd>
        <dt>沿用原图</dt><dd>{{ action.retry.imageCount }} 张</dd>
        <dt>检测模型</dt><dd>{{ action.retry.modelId ?? '未知' }} · 阈值 {{ action.retry.threshold ?? '未知' }}</dd>
        <dt>任务版本</dt><dd>{{ action.retry.resourceVersion }}</dd>
        <dt>重试影响</dt><dd>{{ action.retry.impact }}</dd>
        <template v-if="action.execution"><dt>新派发编号</dt><dd>{{ action.execution.dispatchId }}</dd></template>
      </dl>
      <dl v-else-if="action.command && action.before">
        <dt>检测任务</dt><dd>{{ action.command.taskId }}</dd>
        <dt>质检站点</dt><dd>{{ action.before.qualityStation || '未分配' }} → {{ action.command.qualityStation }}</dd>
        <dt>责任人</dt><dd>{{ action.before.assignee || '未分配' }} → {{ action.command.assignee }}</dd>
        <dt>责任人 ID</dt><dd>{{ action.before.assigneeUserId ?? '未知' }} → {{ action.command.assigneeUserId ?? '未知' }}</dd>
        <dt>账号快照</dt><dd>{{ action.command.assigneeRevision || '历史提议未记录' }}</dd>
        <template v-if="action.result?.after"><dt>分派操作人</dt><dd>{{ action.result.after.assignedByName || '未知' }} · ID {{ action.result.after.assignedByUserId ?? '未知' }}</dd><dt>分派身份版本</dt><dd>{{ action.result.after.assignmentRevision ?? '未知' }}</dd></template>
        <dt>截止时间</dt><dd>{{ beijingDateTime(action.command.dueAt ?? null) || '未设置' }}</dd>
        <dt v-if="action.command.assignmentRemark">备注</dt><dd v-if="action.command.assignmentRemark">{{ action.command.assignmentRemark }}</dd>
      </dl>
      <p v-if="action.creation && action.status === 'EXECUTING'" class="action-note">已保存批准 正在准备检测文件 可刷新核对状态 不要重复提交</p>
      <p v-if="['RETRY_DETECTION', 'CREATE_DETECTION'].includes(action.operation) && action.status === 'SUCCEEDED'" class="action-note">已受理新的检测派发 不表示检测已完成 请到检测记录查看实际进度</p>
      <p v-if="action.reasonCode" class="action-note">{{ action.creation && action.reasonCode === 'EXECUTION_NEEDS_REVIEW' ? '图片传输或检测创建结果待核对 不会自动重传或重复提交' : reasons[action.reasonCode] || '操作未执行 请重新核对任务并生成提议' }}</p>
      <div v-if="action.status === 'PENDING'" class="action-buttons">
        <template v-if="action.status === 'PENDING'">
          <el-button :type="action.operation === 'RETRY_DETECTION' ? 'danger' : 'primary'" :loading="busy.has(action.actionId)" :disabled="busy.has(action.actionId) || !verified" @click="decide(action, 'APPROVE')">{{ action.creation ? '确认创建检测' : action.operation === 'RETRY_DETECTION' ? '确认重新检测' : '确认分配' }}</el-button>
          <el-button :disabled="busy.has(action.actionId) || !verified" @click="decide(action, 'REJECT')">拒绝</el-button>
          <el-button :disabled="busy.has(action.actionId) || !verified" @click="decide(action, 'CANCEL')">取消</el-button>
        </template>
      </div>
      <AgentActionAudit :action-id="action.actionId" :revision="action.version" :operation="action.operation" :scope-key="`${sessionId || ''}:${runId || ''}`" :disabled="busy.has(action.actionId)" />
    </article>
  </section>
</template>
<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { fetchAgentActions, confirmAgentAction, cancelAgentAction } from '@/api/chatAssistant'
import { validAgentAction } from '@/utils/agentActions'
import { beijingDateTime } from '@/utils/beijingTime'
import DetectionProposalImages from './DetectionProposalImages.vue'
import DetectionCreationReview from './DetectionCreationReview.vue'
import AgentActionAudit from './AgentActionAudit.vue'
import ProposalImageGallery from './ProposalImageGallery.vue'
import { useUserStore } from '@/stores/user'
const props = defineProps({ sessionId: String, runId: String, refreshKey: [String, Number], standalone: Boolean })
const actions = ref([]), busy = ref(new Set()), loading = ref(false), error = ref(''), disabled = ref(false)
const userStore = useUserStore()
const actor = computed(() => JSON.stringify([userStore.identity?.userId || userStore.username || '', userStore.role, userStore.isAuthenticated]))
const verified = ref(false)
let generation = 0
const labels = { PENDING: '待确认', APPROVED: '已批准', EXECUTING: '执行中', NEEDS_REVIEW: '待核对', SUCCEEDED: '已分配', REJECTED: '已拒绝', CANCELLED: '已取消', EXPIRED: '已过期', INVALIDATED: '已失效' }
const reasons = { RESOURCE_CHANGED: '任务已变化 原提议失效 请重新生成', ROLE_REVOKED: '当前账号已无操作权限', PARAMETERS_SUPERSEDED: '已有新的操作参数 原提议失效', POLICY_CHANGED: '操作规则已更新 请重新生成', CONFIRMATION_EXPIRED: '确认已过期 未执行操作', ORIGIN_RUN_TERMINATED: '原运行已取消或中断 未执行操作', BUSINESS_PRECONDITION_CHANGED: '任务或责任人条件已变化 未执行操作', EXECUTION_NEEDS_REVIEW: '上次检测结果待核对 未提交新的检测 不会自动重试', USER_REJECT: '用户已拒绝 未执行操作', USER_CANCEL: '用户已取消 未执行操作' }
reasons.USER_ABANDONED = '本人已终止创建 原文件及不确定传输证据保留'
async function refresh() {
  const version = ++generation
  loading.value = true; error.value = ''; verified.value = false
  try {
    const response = await fetchAgentActions({ ...(props.sessionId ? { sessionId: props.sessionId } : {}), ...(props.runId ? { runId: props.runId } : {}) })
    if (version !== generation) return
    if (!Array.isArray(response.data) || !response.data.every(validAgentAction)) throw new Error('操作记录格式异常 请刷新核对')
    actions.value = response.data; disabled.value = false; verified.value = true
  } catch (e) {
    if (version !== generation) return
    if ([401, 403].includes(e.response?.status)) actions.value = []
    if (e.response?.status === 503 && e.response?.data?.message === '人工确认功能尚未启用') { disabled.value = true; actions.value = [] }
    else error.value = e.response?.data?.message || e.message || '操作状态暂不可用 请刷新'
  } finally { if (version === generation) loading.value = false }
}
async function decide(action, decision) {
  if (busy.value.has(action.actionId) || !verified.value) return
  const version = generation
  busy.value = new Set([...busy.value, action.actionId]); error.value = ''
  try {
    const response = decision === 'CANCEL' ? await cancelAgentAction(action.actionId, action.version) : await confirmAgentAction(action.actionId, decision, action.version)
    if (version !== generation) return
    if (!validAgentAction(response.data) || response.data.actionId !== action.actionId) throw new Error('操作结果未核实 请刷新')
    actions.value = actions.value.map(item => item.actionId === action.actionId ? response.data : item)
  } catch (e) {
    if (version === generation) { verified.value = false; error.value = e.response?.data?.message || '确认结果尚未核实 请刷新状态后再操作' }
  } finally { busy.value = new Set([...busy.value].filter(id => id !== action.actionId)) }
}
watch(() => [props.sessionId, props.runId, actor.value], () => {
  generation++; actions.value = []; error.value = ''; disabled.value = false; verified.value = false; loading.value = false
  if (userStore.isAuthenticated) refresh()
}, { immediate: true, flush: 'sync' })
watch(() => props.refreshKey, () => { if (userStore.isAuthenticated) refresh() })
onBeforeUnmount(() => generation++)
</script>
<style scoped>
.agent-actions{padding:0;background:transparent;border:0;min-width:0}.actions-heading,.action-card>header{display:flex;align-items:center;justify-content:space-between;gap:12px}.action-card{margin-top:14px;padding:16px;background:white;border:1px solid #e1e8f3;border-radius:12px;animation:action-in .2s ease}.action-card dl{display:grid;grid-template-columns:84px minmax(0,1fr);gap:10px;font-size:13px}.action-card dt{color:#68758b}.action-card dd{margin:0;overflow-wrap:anywhere}.action-note,.empty-note,.audit-events{font-size:12px;color:#637087;line-height:1.7}.action-buttons{display:flex;flex-wrap:wrap;gap:8px}.action-buttons :deep(button){margin-left:0;transition:transform .15s ease}.action-buttons :deep(button:not(:disabled):hover){transform:scale(1.02)}.action-error{font-size:13px;color:#b42318}.audit-events{padding-left:18px}@keyframes action-in{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}@media(prefers-reduced-motion:reduce){.action-card{animation:none}.action-buttons :deep(button){transition:none;transform:none!important}}
</style>
