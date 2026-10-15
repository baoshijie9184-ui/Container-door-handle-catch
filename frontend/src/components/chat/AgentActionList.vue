<template>
  <section v-if="standalone || (!disabled && (actions.length || error))" class="agent-actions" aria-label="助手操作确认">
    <header class="actions-heading"><strong>助手操作确认</strong><el-button size="small" :loading="loading" @click="refresh">刷新</el-button></header>
    <p v-if="error" role="alert" class="action-error">{{ error }}</p>
    <p v-if="disabled" class="empty-note">此环境尚未启用人工确认</p>
    <p v-else-if="!loading && !actions.length" class="empty-note">暂无操作提议 提议保存后仍需明确确认</p>
    <article v-for="action in actions" :key="action.actionId" class="action-card" :aria-busy="busy.has(action.actionId)">
      <header><strong>分配质检任务</strong><el-tag :type="action.status === 'SUCCEEDED' ? 'success' : action.status === 'PENDING' ? 'primary' : 'info'">{{ labels[action.status] || action.status }}</el-tag></header>
      <dl>
        <dt>检测任务</dt><dd>{{ action.command.taskId }}</dd>
        <dt>质检站点</dt><dd>{{ action.before.qualityStation || '未分配' }} → {{ action.command.qualityStation }}</dd>
        <dt>责任人</dt><dd>{{ action.before.assignee || '未分配' }} → {{ action.command.assignee }}</dd>
        <dt>截止时间</dt><dd>{{ action.command.dueAt || '未设置' }}</dd>
        <dt v-if="action.command.assignmentRemark">备注</dt><dd v-if="action.command.assignmentRemark">{{ action.command.assignmentRemark }}</dd>
      </dl>
      <p v-if="action.status === 'PENDING'" class="action-note">确认后会修改任务的质检分配信息 尚未执行业务操作 有效期至 {{ action.expiresAt }}</p>
      <p v-if="action.reasonCode" class="action-note">{{ reasons[action.reasonCode] || '操作未执行 请重新核对任务并生成提议' }}</p>
      <div class="action-buttons">
        <template v-if="action.status === 'PENDING'">
          <el-button type="primary" :disabled="busy.has(action.actionId)" @click="decide(action, 'APPROVE')">确认分配</el-button>
          <el-button :disabled="busy.has(action.actionId)" @click="decide(action, 'REJECT')">拒绝</el-button>
          <el-button :disabled="busy.has(action.actionId)" @click="decide(action, 'CANCEL')">取消</el-button>
        </template>
        <el-button text :disabled="busy.has(action.actionId)" @click="showAudit(action)">查看审计</el-button>
      </div>
      <ol v-if="audits[action.actionId]" class="audit-events"><li v-for="event in audits[action.actionId]" :key="event.id">{{ event.occurredAt }} · {{ auditLabels[event.eventType] || event.eventType }} · {{ labels[event.result] || event.result }}</li></ol>
    </article>
  </section>
</template>
<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { fetchAgentActions, confirmAgentAction, cancelAgentAction, fetchAgentActionAudit } from '@/api/chatAssistant'
const props = defineProps({ sessionId: String, runId: String, refreshKey: [String, Number], standalone: Boolean })
const actions = ref([]), audits = ref({}), busy = ref(new Set()), loading = ref(false), error = ref(''), disabled = ref(false)
let generation = 0
const labels = { PENDING: '待确认', APPROVED: '已批准', EXECUTING: '执行中', SUCCEEDED: '已分配', REJECTED: '已拒绝', CANCELLED: '已取消', EXPIRED: '已过期', INVALIDATED: '已失效' }
const reasons = { RESOURCE_CHANGED: '任务已变化 原提议失效 请重新生成', ROLE_REVOKED: '当前账号已无分配权限', PARAMETERS_SUPERSEDED: '已有新的分配参数 原提议失效', POLICY_CHANGED: '操作规则已更新 请重新生成', CONFIRMATION_EXPIRED: '确认已过期 未执行分配', ORIGIN_RUN_TERMINATED: '原运行已取消或中断 未执行分配', BUSINESS_PRECONDITION_CHANGED: '任务或责任人条件已变化 未执行分配', USER_REJECT: '用户已拒绝 未执行分配', USER_CANCEL: '用户已取消 未执行分配' }
const auditLabels = { CONFIRMATION_CREATED: '保存提议', CONFIRMATION_DECIDED: '用户决策', CONFIRMATION_INVALIDATED: '提议失效', AUTHORIZATION_ALLOWED: '权限通过', AUTHORIZATION_DENIED: '权限拒绝', TOOL_EXECUTION_STARTED: '开始分配', BUSINESS_CHANGED: '业务更新', TOOL_EXECUTION_COMPLETED: '分配完成' }
async function refresh() {
  const version = ++generation
  loading.value = true; error.value = ''
  try {
    const response = await fetchAgentActions({ ...(props.sessionId ? { sessionId: props.sessionId } : {}), ...(props.runId ? { runId: props.runId } : {}) })
    if (version !== generation) return
    actions.value = response.data; disabled.value = false
  } catch (e) {
    if (version !== generation) return
    if (e.response?.status === 503 && e.response?.data?.message === '人工确认功能尚未启用') disabled.value = true
    else error.value = e.response?.data?.message || '操作状态暂不可用 请刷新'
  } finally { if (version === generation) loading.value = false }
}
async function decide(action, decision) {
  if (busy.value.has(action.actionId)) return
  const version = generation
  busy.value = new Set([...busy.value, action.actionId]); error.value = ''
  try {
    const response = decision === 'CANCEL' ? await cancelAgentAction(action.actionId, action.version) : await confirmAgentAction(action.actionId, decision, action.version)
    if (version !== generation) return
    actions.value = actions.value.map(item => item.actionId === action.actionId ? response.data : item)
    delete audits.value[action.actionId]
  } catch (e) {
    if (version === generation) error.value = e.response?.data?.message || '确认结果尚未核实 请刷新状态后再操作'
  } finally { busy.value = new Set([...busy.value].filter(id => id !== action.actionId)) }
}
async function showAudit(action) {
  const version = generation
  try { const response = await fetchAgentActionAudit(action.actionId); if (version === generation) audits.value = { ...audits.value, [action.actionId]: response.data } }
  catch { if (version === generation) error.value = '审计记录暂不可用 请稍后刷新' }
}
watch(() => [props.sessionId, props.runId, props.refreshKey], () => { actions.value = []; audits.value = {}; refresh() }, { immediate: true })
onBeforeUnmount(() => generation++)
</script>
<style scoped>
.agent-actions{padding:16px;background:#f7faff;border:1px solid #dbe7fa;border-radius:14px}.actions-heading,.action-card>header{display:flex;align-items:center;justify-content:space-between;gap:12px}.action-card{margin-top:14px;padding:16px;background:white;border:1px solid #e1e8f3;border-radius:12px;animation:action-in .2s ease}.action-card dl{display:grid;grid-template-columns:84px minmax(0,1fr);gap:10px;font-size:13px}.action-card dt{color:#68758b}.action-card dd{margin:0;overflow-wrap:anywhere}.action-note,.empty-note,.audit-events{font-size:12px;color:#637087;line-height:1.7}.action-buttons{display:flex;flex-wrap:wrap;gap:8px}.action-buttons :deep(button){margin-left:0;transition:transform .15s ease}.action-buttons :deep(button:not(:disabled):hover){transform:scale(1.02)}.action-error{font-size:13px;color:#b42318}.audit-events{padding-left:18px}@keyframes action-in{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}@media(prefers-reduced-motion:reduce){.action-card{animation:none}.action-buttons :deep(button){transition:none;transform:none!important}}
</style>
