<template>
  <section class="identity-page" aria-labelledby="identity-page-title" :aria-busy="busy || confirming">
    <header class="identity-page-header"><div class="identity-heading"><span class="heading-icon"><el-icon><UserFilled /></el-icon></span><div><h2 id="identity-page-title">任务账号关联</h2><p>保留历史名称，明确每条记录的账号归属</p></div></div><el-button :loading="busy" :disabled="confirming || !!pending" :icon="Refresh" @click="refresh">重新预览</el-button></header>
    <div class="identity-overview">
      <div><el-icon><Key /></el-icon><span>授权模式<strong>{{ !state ? '尚未读取' : state.mode === 'ACTIVE' ? state.sourceMode === 'ACTIVE' ? 'ID 与来源保护' : '按账号 ID' : '等待核对' }}</strong></span></div>
      <div><el-icon><DocumentChecked /></el-icon><span>{{ previewError&&state ? '上次读取的预览' : '当前预览' }}<strong>{{ state ? rows.length : '—' }} 条关联</strong></span></div>
      <div><el-icon><CircleCheck /></el-icon><span>本次选择<strong>{{ selected.length }} 条</strong></span></div>
    </div>
    <el-alert title="同名账号只是候选，不证明历史归属。账号删除、改名或名称重用时，请核对业务资料后明确选择目标。" type="info" :closable="false" show-icon />
    <el-alert v-if="state?.sourceEvidenceEnabled && state.sourceMode !== 'ACTIVE'" title="当前正在收集身份来源，尚未切换为来源保护。旧记录不会自动获得来源，请完成必要回填后明确启用。" type="info" :closable="false" show-icon />
    <el-alert v-if="state?.missingNameReviewEnabled" title="缺失名称可按核实资料单独确认。请填写资料编号并逐条勾选；服务器保留原空名称，不自动补写，也不会读取编号指向的外部资料。" type="warning" :closable="false" show-icon />
    <el-alert v-if="state && !state.reviewEnabled" title="当前仅提供预览，尚未启用身份回填确认。完成部署配置并重新读取后才能提交，不使用缺少目标快照的旧请求。" type="warning" :closable="false" show-icon />
    <el-alert v-if="error" :title="error" :type="pending ? 'warning' : 'error'" :closable="false" show-icon />
    <section v-if="pending" class="receipt-panel" aria-live="polite">
      <strong>原确认结果需要核对</strong><p>请求编号 <code>{{ pending.payload.requestId }}</code></p>
      <p>未查到回执也可能仍在处理中。保留原请求和内容，不能据此再次创建一批映射。</p>
      <el-button :disabled="busy" :icon="Search" @click="checkReceipt">只读核对回执</el-button>
      <el-button v-if="pending.state === 'NOT_RECORDED_YET'" :disabled="busy" @click="retryOriginal">确认重试原请求</el-button>
    </section>
    <section v-if="lastReceipt" class="last-receipt" aria-live="polite"><el-icon><CircleCheck /></el-icon><span>批次已记录 · {{ lastReceipt.applied }} 条 · 版本 {{ lastReceipt.revision }}<code>{{ lastReceipt.requestId }}</code></span></section>
    <div class="preview-toolbar"><el-checkbox v-model="includeAligned" :disabled="busy || !!pending" @change="refresh">同时核对已有 ID 关联</el-checkbox><span v-if="state">预览版本 {{ state.revision }}</span></div>
    <label for="identity-task-query" class="identity-query-label">任务编号</label>
    <form class="receipt-search task-search" @submit.prevent="searchTask"><el-input id="identity-task-query" v-model="taskFilter" maxlength="128" clearable :disabled="busy || confirming || !!pending" placeholder="输入任务编号，留空查看全部" aria-label="身份预览任务编号" @clear="searchTask"/><el-button :disabled="busy || confirming || !!pending" :icon="Search" native-type="submit">定位任务</el-button><el-button v-if="taskFilter" :disabled="busy || confirming || !!pending" @click="focusTask('')">显示全部</el-button></form>
    <div class="preview-toolbar"><h3>账号归属核对</h3><span>{{ state ? `本页 ${rows.length} 条，不代表全部待映射记录` : '预览尚未读取' }}</span></div>
    <p v-if="previewError&&rows.length" class="identity-preview-note" role="status">当前保留上次预览。请重新读取成功后再选择和确认映射。</p>
    <div class="mapping-table"><el-table :scrollbar-tabindex="0" role="region" aria-label="待核对账号关联" :data="rows" v-loading="busy" :row-key="row => row.taskId + ':' + row.role" @selection-change="selectionChanged">
      <template #empty><CollectionEmptyState :loading="busy" :error="previewError" :filtered="!!taskFilter" empty-title="本页暂无待处理关联" empty-description="这里只显示当前预览页；可调整核对范围，或读取后续页面。" @retry="refresh" @reset="focusTask('')" /></template>
      <el-table-column type="selection" width="45" :selectable="row => !pending && !previewError && !busy && state?.reviewEnabled && valid(row)" />
      <el-table-column label="任务 / 职责" min-width="200"><template #default="{ row }"><strong>{{ roles[row.role] || '职责未记录' }}</strong><code class="task-id">{{ row.taskId }}</code><StatusBadge domain="identityMapping" :code="row.state" :label="states[row.state]" /><p v-if="row.flowStatus"><StatusBadge domain="flow" :code="row.flowStatus" :label="flowNames[row.flowStatus]" /></p><p v-if="row.taskUpdatedAt">更新 {{ formatTime(row.taskUpdatedAt) }} UTC+8</p></template></el-table-column>
      <el-table-column label="历史身份" min-width="190"><template #default="{ row }"><strong>{{ row.missingName ? '原名称缺失，保持原样' : row.expectedName }}</strong><p>原 ID {{ row.existingUserId ?? '未关联' }}</p><p v-if="row.existingIdentityName">原快照 {{ row.existingIdentityName }}</p><p v-if="row.existingAccount">当前账号 {{ row.existingAccount.username }} · {{ roleNames[row.existingAccount.role] }}</p></template></el-table-column>
      <el-table-column v-if="state?.sourceEvidenceEnabled" label="身份来源" min-width="210"><template #default="{ row }"><el-tag :type="row.source?.state === 'SOURCE_RECORDED' ? 'info' : 'warning'">{{ row.source?.state === 'SOURCE_RECORDED' ? sourceKinds[row.source.source_kind] || '来源记录' : row.source?.state === 'SOURCE_MISMATCH' ? '旧来源不匹配' : '来源待核对' }}</el-tag><p v-if="row.source?.revision">来源版本 {{ row.source.revision }}</p><p v-if="row.source?.actor_user_id">记录账号 ID {{ row.source.actor_user_id }}</p><el-button v-if="row.source?.source_batch_id" link type="primary" @click="showBatch(row.source.request_id)">查看回填依据</el-button></template></el-table-column>
      <el-table-column label="明确选择目标账号" min-width="290"><template #default="{ row }"><IdentityAccountPicker v-model="row.target" :label="row.taskId + ' ' + (roles[row.role] || '身份') + '目标账号'" :disabled="busy || !!pending || !state?.reviewEnabled || row.mappingAllowed === false" /><div v-if="row.candidateAccount" class="candidate">同名候选 ID {{ row.candidateAccount.userId }}<el-button link type="primary" :disabled="busy || !!pending || !state?.reviewEnabled || row.mappingAllowed === false" @click="row.target = { ...row.candidateAccount }">选择此候选</el-button></div><p v-else>{{ row.mappingBlockedReason || '没有唯一同名候选，请手动检索或保留待映射' }}</p></template></el-table-column>
      <el-table-column label="历史归属核对依据" min-width="260"><template #default="{ row }"><el-select v-model="row.basis" :disabled="busy || !!pending || !state?.reviewEnabled || row.mappingAllowed === false" placeholder="请选择实际核对依据" :aria-label="row.taskId + ' ' + roles[row.role] + '核对依据'"><el-option v-for="(label, key) in bases" :key="key" :value="key" :label="label" :disabled="row.missingName && key === 'ACCOUNT_RENAME_VERIFIED'" /></el-select><div v-if="row.missingName && state?.missingNameReviewEnabled" class="missing-name-review"><el-input v-model="row.evidenceReference" maxlength="128" :disabled="busy || !!pending" placeholder="已核实的资料编号，不填正文或凭据" :aria-label="row.taskId + ' ' + roles[row.role] + '资料编号'"/><el-checkbox v-model="row.missingNameConfirmed" :disabled="busy || !!pending">已核实资料，明确确认此缺失名称的归属</el-checkbox></div></template></el-table-column>
    </el-table></div>
    <el-checkbox v-model="acknowledged" class="acknowledgement" :disabled="busy || !!pending">我已核对选中记录的历史归属，明确将其关联到所选账号；同名候选本身不是证据</el-checkbox>
    <p v-if="!canApply" class="identity-preview-note">{{ previewError ? '请先重新读取身份预览' : pending ? '请先核对上一批请求回执' : !state?.reviewEnabled ? '当前预览尚不允许提交映射' : !selected.length ? '为记录选择目标账号及核对依据后，再勾选需要确认的记录' : !acknowledged ? '请阅读并勾选历史归属确认' : '所选记录尚有未核实内容，请逐条核对' }}</p>
    <div class="actions"><el-button type="primary" :icon="DocumentChecked" :disabled="!canApply" @click="apply">确认选中映射{{ selected.length ? `（${selected.length} 条）` : '' }}</el-button><el-button v-if="state?.hasMore" :disabled="busy || !!pending" @click="next">查看下一页</el-button><el-button v-if="state?.mode !== 'ACTIVE' || (state?.sourceEvidenceEnabled && state.sourceMode !== 'ACTIVE')" :disabled="busy || confirming || !!pending || !state?.reviewEnabled" @click="activate">{{ state?.mode === 'ACTIVE' ? '核对完成，启用来源保护' : '核对完成，启用 ID 授权' }}</el-button></div>
    <p>未选择或无法核实的记录保持原状。启用授权前，服务器检查全部任务的创建人和责任人；历史报告与原显示名称不会被改写。</p>
    <section v-if="state?.reviewEnabled || receiptQuery || pending" class="receipt-history">
      <div class="preview-toolbar"><h3>回填批次与回执</h3><el-button :loading="historyBusy" :icon="Refresh" @click="loadHistory(true)">刷新批次</el-button></div>
      <form class="receipt-search" @submit.prevent="lookupReceipt"><el-input v-model="receiptQuery" maxlength="128" clearable placeholder="输入原请求编号，只读核对结果" aria-label="回填请求编号"/><el-button :loading="receiptBusy" :icon="Search" native-type="submit">核对回执</el-button></form>
      <p>刷新页面只恢复编号并读取回执，不重发映射或恢复旧确认授权。未查到记录不代表原请求已终止。</p>
      <el-alert v-if="historyError" :title="historyError" type="warning" :closable="false"/>
      <el-alert v-if="receiptError" :title="receiptError" type="warning" :closable="false"/>
      <div class="mapping-table"><el-table :scrollbar-tabindex="0" role="region" aria-label="历史关联批次" :data="batches" :aria-busy="historyBusy"><template #empty><CollectionEmptyState :loading="historyBusy" :error="historyError" empty-title="暂无已提交批次" empty-description="完成一次明确确认并取得回执后，可在这里查看映射依据。" @retry="loadHistory(true)" /></template><el-table-column prop="requestId" label="请求编号" min-width="260"/><el-table-column label="确认账号" min-width="160"><template #default="{row}">{{ row.actorName }} · ID {{ row.actorUserId }}</template></el-table-column><el-table-column prop="applied" label="条数" width="75"/><el-table-column prop="revision" label="版本" width="80"/><el-table-column label="北京时间 UTC+8" min-width="185"><template #default="{row}">{{ formatTime(row.createdAt) }}</template></el-table-column><el-table-column label="明细" width="80"><template #default="{row}"><el-button link type="primary" @click="showBatch(row.requestId)"><AppIcon name="Search" :size="16" />查看</el-button></template></el-table-column></el-table></div>
      <p v-if="batches.length" class="identity-preview-note" role="status">已读取 {{ batches.length.toLocaleString('zh-CN') }} 个批次{{ historyBusy ? '，正在更新，当前保留已读记录' : historyError ? '，当前为上次读取快照' : historyMore ? '，还有更早记录' : '' }}</p>
      <el-button v-if="historyMore" :loading="historyBusy" @click="loadHistory(false)">更早的批次</el-button>
      <Transition name="identity-receipt">
        <section v-if="receiptDetail" class="receipt-detail" aria-live="polite">
          <div class="preview-toolbar"><h3>批次明细</h3><el-button @click="receiptDetail = null">关闭明细</el-button></div>
          <p><code>{{ receiptDetail.requestId }}</code> · {{ receiptDetail.applied }} 条 · 版本 {{ receiptDetail.revision }} · {{ formatTime(receiptDetail.createdAt) }}</p>
          <p>摘要 <code>{{ receiptDetail.digest }}</code></p>
          <div class="mapping-table"><el-table :scrollbar-tabindex="0" role="region" aria-label="关联批次明细" :data="receiptDetail.mappings">
            <el-table-column prop="task_id" label="任务" min-width="180"/>
            <el-table-column label="职责" width="90"><template #default="{row}">{{ roles[row.identity_role] }}</template></el-table-column>
            <el-table-column label="历史名称" min-width="160"><template #default="{row}">{{ row.missingNameConfirmation ? '原名称缺失，未改写' : row.source_name }}<p v-if="row.missingNameConfirmation">原值 {{ row.missingNameConfirmation.original_name === null ? 'NULL' : '空白文本' }}</p></template></el-table-column>
            <el-table-column label="原 ID" width="100"><template #default="{row}">{{ row.previous_user_id ?? '未关联' }}</template></el-table-column>
            <el-table-column label="确认目标" min-width="185"><template #default="{row}">{{ row.target_username }} · ID {{ row.target_user_id }}</template></el-table-column>
            <el-table-column label="核对依据" min-width="210"><template #default="{row}">{{ bases[row.confirmation_basis] || '未知' }}<p v-if="row.missingNameConfirmation">资料编号 <code>{{ row.missingNameConfirmation.evidence_reference }}</code></p></template></el-table-column>
          </el-table></div>
        </section>
      </Transition>
    </section>
    <IdentityReconciliationPanel v-if="state?.reconciliationEnabled || route.query.identityScan" :enabled="state?.reconciliationEnabled === true" :disabled="busy || confirming || !!pending" :revision="state?.revision" :source-protection="state?.sourceEvidenceEnabled === true" @focus-task="focusTask"/>
  </section>
</template>
<script setup>
import { ref, computed, h, onMounted } from 'vue'
import { ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { UserFilled, Refresh, Key, DocumentChecked, CircleCheck, Search } from '@element-plus/icons-vue'
import IdentityAccountPicker from '@/components/IdentityAccountPicker.vue'
import IdentityReconciliationPanel from '@/components/IdentityReconciliationPanel.vue'
import CollectionEmptyState from '@/components/CollectionEmptyState.vue'
import request from '@/api/request'
import { beijingDateTime } from '@/utils/beijingTime'
const formatTime = value => value ? beijingDateTime(value) || '时间未记录' : '时间未记录'
const route = useRoute(), router = useRouter()
const taskFilter = ref(typeof route.query.identityTask === 'string' && route.query.identityTask.length <= 128 ? route.query.identityTask : '')
const rows = ref([]), state = ref(null), error = ref(''), busy = ref(false), cursor = ref(''), selected = ref([])
const previewError = ref('')
const includeAligned = ref(false), acknowledged = ref(false), pending = ref(null), lastReceipt = ref(null)
const confirming = ref(false)
const batches = ref([]), historyBusy = ref(false), historyError = ref(''), historyMore = ref(false), historyCursor = ref(0)
const receiptQuery = ref(''), receiptDetail = ref(null), receiptBusy = ref(false), receiptError = ref('')
const roles = { created: '创建人', assignee: '责任人', reviewer: '复核人', disposition: '处置人', rework: '返工人' }
const roleNames = { ADMIN: '管理员', SUPERVISOR: '主管', INSPECTOR: '检测员', OPERATOR: '操作员' }
const flowNames = { PENDING_DETECTION: '等待检测', DETECTING: '检测中', PENDING_REVIEW: '等待复核', RECHECK_REQUIRED: '等待复检', REWORK_REQUIRED: '等待返工', RELEASED: '已放行', REJECTED: '已拒绝', FAILED: '检测失败' }
const states = { ALREADY_ALIGNED: '已有 ID 关联', MISSING_NAME: '历史名称缺失', MISSING_NAME_CONFIRMED: '缺失名称已明确确认', SOURCE_UNVERIFIED: '身份来源待核对', ORIGINAL_ACCOUNT_UNAVAILABLE: '原账号不可用', UNMATCHED: '待手动核对', DIFFERENT_CURRENT_ACCOUNT: '同名候选 ID 不同', CANDIDATE_ONLY: '仅有同名候选' }
const sourceKinds = { NEW_CREATION: '实际创建操作', QUALITY_ASSIGNMENT: '实际分派操作', PERFORMED_OPERATION: '实际人工操作', SUPERVISOR_MAPPING: '主管回填确认', SUPERVISOR_MISSING_NAME: '主管核实缺失名称', OBSERVED_CLEAR: '业务字段已清空' }
const bases = { SOURCE_RECORD_CHECKED: '已核对原始业务记录', ORGANIZATION_RECORD_CHECKED: '已核对组织人员记录', ACCOUNT_RENAME_VERIFIED: '已核实账号更名关联', MANUAL_RECONCILIATION: '主管另行核对确认' }
const headers = { 'X-Identity-Action': 'update' }
let pendingActivation = null
function valid(row) { return row.mappingAllowed !== false && row.target && Number.isSafeInteger(row.target.userId) && row.target.userId > 0 && typeof row.target.username === 'string' && roleNames[row.target.role] && /^[a-f0-9]{64}$/.test(row.target.revision) && !!bases[row.basis] && (!row.missingName || (state.value?.missingNameReviewEnabled === true && row.missingNameConfirmed === true && row.basis !== 'ACCOUNT_RENAME_VERIFIED' && typeof row.evidenceReference === 'string' && row.evidenceReference === row.evidenceReference.trim() && /^[\p{L}\p{N}][\p{L}\p{N}_.:#@ -]{0,127}$/u.test(row.evidenceReference))) }
function validReceiptProtocol(data) { return ['identity-map-v2', 'identity-map-v3'].includes(data?.protocol) }
const canApply = computed(() => !busy.value && !confirming.value && !pending.value && !previewError.value && state.value?.reviewEnabled && acknowledged.value && Number.isSafeInteger(state.value.revision) && selected.value.length > 0 && selected.value.length <= 200 && selected.value.every(valid))
function selectionChanged(value) { selected.value = value }
async function load() {
  if (busy.value || confirming.value || pending.value) return
  busy.value = true; error.value = ''; previewError.value = ''
  try {
    const { data } = await request.get('/api/detection/identity/preview', { params: { after: cursor.value, size: 25, includeAligned: includeAligned.value, taskId: taskFilter.value } })
    if (!Array.isArray(data?.records) || !Number.isSafeInteger(data.revision)) throw Error()
    state.value = data; rows.value = data.records.map(row => ({ ...row, target: null, basis: '', evidenceReference: '', missingNameConfirmed: false })); selected.value = []; acknowledged.value = false
    if (data.reviewEnabled) await loadHistory(true)
  } catch { previewError.value = '无法读取身份预览，或当前账号无权操作；请核对服务是否启用'; error.value = previewError.value }
  finally { busy.value = false }
}
function refresh() { cursor.value = ''; return load() }
function next() { cursor.value = state.value.nextCursor; return load() }
async function searchTask() { if (busy.value || confirming.value || pending.value) return; try { await router.replace({ query: { ...route.query, identityTask: taskFilter.value || undefined } }); await refresh() } catch { error.value = '任务定位未能完成，请保留原编号' } }
async function focusTask(task) { if (busy.value || confirming.value || pending.value || typeof task !== 'string' || task.length > 128) return; taskFilter.value = task; if (task) includeAligned.value = true; await searchTask() }
async function apply() {
  if (!canApply.value) return
  const mappings = selected.value.map(row => ({ taskId: row.taskId, role: row.role, expectedName: row.expectedName, snapshot: row.snapshot, userId: row.target.userId, targetUsername: row.target.username, targetRole: row.target.role, targetRevision: row.target.revision, basis: row.basis }))
  const missingNames = selected.value.filter(row => row.missingName).map(row => ({ taskId: row.taskId, role: row.role, evidenceReference: row.evidenceReference, confirmed: row.missingNameConfirmed === true }))
  const revision = state.value.revision
  confirming.value = true
  try {
    await ElMessageBox.confirm(h('div', { style: { maxHeight: '24rem', overflow: 'auto' } }, [h('p', `将 ${mappings.length} 条历史关联写入所选账号，保留原名称。请逐条核对：`), ...mappings.map(row => { const proof = missingNames.find(item => item.taskId === row.taskId && item.role === row.role); return h('p', { style: { overflowWrap: 'anywhere' } }, `${row.taskId} · ${roles[row.role]} · ${proof ? '原名称缺失' : row.expectedName} → ${row.targetUsername}（ID ${row.userId}，${roleNames[row.targetRole]}）· ${bases[row.basis]}${proof ? ` · 已核实资料编号 ${proof.evidenceReference}` : ''}`) })]), '确认历史账号归属', { confirmButtonText: '确认映射', cancelButtonText: '继续核对', customClass: 'identity-confirmation-dialog' })
    pending.value = { state: 'SENDING', payload: { requestId: crypto.randomUUID(), mappings, revision, acknowledgedHistory: true, missingNames } }
    confirming.value = false
    await router.replace({ query: { ...route.query, identityReceipt: pending.value.payload.requestId } })
    await submitOriginal()
  } catch (failure) { if (failure !== 'cancel' && failure !== 'close') error.value = '确认尚未提交，请保留选择并重新核对' }
  finally { confirming.value = false }
}
async function submitOriginal() {
  if (!pending.value || busy.value) return
  busy.value = true; error.value = ''
  try {
    const { data } = await request.post('/api/detection/identity/apply', pending.value.payload, { headers })
    if (data?.requestId !== pending.value.payload.requestId || data.applied !== pending.value.payload.mappings.length || !Number.isSafeInteger(data.revision) || data.protocol !== (pending.value.payload.missingNames?.length ? 'identity-map-v3' : 'identity-map-v2')) throw Error()
    lastReceipt.value = data; pending.value = null; busy.value = false; await load()
  } catch (failure) {
    if ([400, 403, 409].includes(failure.response?.status)) { pending.value = null; error.value = failure.response?.data?.message || '当前确认被拒绝，请重新预览' }
    else { pending.value.state = 'UNKNOWN'; error.value = '映射结果未确认，已保留原请求。请只读核对回执，不自动重发' }
  } finally { busy.value = false }
}
async function checkReceipt() {
  if (!pending.value || busy.value) return
  busy.value = true
  try {
    const { data } = await request.get(`/api/detection/identity/commands/${encodeURIComponent(pending.value.payload.requestId)}`)
    if (data?.found === true && data.requestId === pending.value.payload.requestId && data.protocol === (pending.value.payload.missingNames?.length ? 'identity-map-v3' : 'identity-map-v2') && data.applied === pending.value.payload.mappings.length && Number.isSafeInteger(data.revision)) { lastReceipt.value = data; pending.value = null; busy.value = false; await load() }
    else if (data?.found === false) { pending.value.state = 'NOT_RECORDED_YET'; error.value = '暂未查到已提交回执，可能仍在处理中；如需重试只能明确确认原编号和原内容' }
    else throw Error()
  } catch { error.value = '回执暂时不可核对，原请求继续保留' }
  finally { busy.value = false }
}
async function retryOriginal() {
  if (!pending.value || busy.value || confirming.value) return
  confirming.value = true
  try { await ElMessageBox.confirm('只重试已保存的同一编号、同一目标和同一版本，服务器会去重；不会生成新映射批次。', '确认重试原请求', { confirmButtonText: '重试原请求', cancelButtonText: '继续核对', customClass: 'identity-confirmation-dialog' }); confirming.value = false; await submitOriginal() }
  catch (failure) { if (failure !== 'cancel' && failure !== 'close') error.value = '原请求尚未确认' }
  finally { confirming.value = false }
}
async function activate() {
  if (busy.value || confirming.value || pending.value || !state.value?.reviewEnabled) return
  confirming.value = true
  try {
    await ElMessageBox.confirm('服务器检查全部任务；未完成必要映射时不会切换。启用来源保护还要求创建人和责任人有明确操作或主管确认来源，已有 ID 不会被自动认作证据。', '启用账号身份保护', { confirmButtonText: '确认启用', cancelButtonText: '继续核对', customClass: 'identity-confirmation-dialog' })
    const sourceProtection = state.value.sourceEvidenceEnabled === true
    if (pendingActivation?.revision !== state.value.revision || pendingActivation?.sourceProtection !== sourceProtection) pendingActivation = { revision: state.value.revision, requestId: crypto.randomUUID(), sourceProtection }
    busy.value = true; await request.post('/api/detection/identity/activate', pendingActivation, { headers }); busy.value = false; confirming.value = false; await load()
  } catch (failure) { if (failure !== 'cancel' && failure !== 'close') error.value = failure.response?.data?.message || '授权模式未确认，请重新预览核对，不自动重发' }
  finally { busy.value = false; confirming.value = false }
}
async function loadHistory(reset = true) {
  if (historyBusy.value) return
  historyBusy.value = true; historyError.value = ''
  try {
    const { data } = await request.get('/api/detection/identity/batches', { params: { before: reset ? 0 : historyCursor.value, size: 10 } })
    if (!Array.isArray(data?.records) || !Number.isSafeInteger(data.nextCursor)) throw Error()
    batches.value = reset ? data.records : [...batches.value, ...data.records]; historyMore.value = data.hasMore === true; historyCursor.value = data.nextCursor
  } catch { historyError.value = '批次列表暂未核对，请保留原请求编号' }
  finally { historyBusy.value = false }
}
async function lookupReceipt() {
  const id = receiptQuery.value.trim()
  if (receiptBusy.value) return
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(id)) { receiptError.value = '请填写有效的原请求编号'; return }
  receiptBusy.value = true; receiptError.value = ''; receiptDetail.value = null
  try {
    const { data } = await request.get(`/api/detection/identity/commands/${encodeURIComponent(id)}`)
    if (data?.found === false) { receiptError.value = '当前未查到已提交回执，不能据此认定原请求失败或重新生成映射'; return }
    if (data?.requestId !== id || data.found !== true || !validReceiptProtocol(data) || !Array.isArray(data.mappings)) throw Error()
    receiptDetail.value = data
  } catch { receiptError.value = '回执暂时不可核对，可能是权限变化、服务异常或明细不完整；不会重发操作' }
  finally { receiptBusy.value = false }
}
async function showBatch(id) { receiptQuery.value = id; await router.replace({ query: { ...route.query, identityReceipt: id } }); await lookupReceipt() }
onMounted(async () => { await refresh(); const id = route.query.identityReceipt; if (typeof id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(id)) { receiptQuery.value = id; await lookupReceipt() } })
</script>
<style scoped>
.identity-page { min-width: 0; color: var(--app-text, #0f172a); border: 0; }
.identity-page-header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px; }
.identity-heading { display: flex; align-items: center; min-width: 0; gap: 12px; }
.identity-heading > div { min-width: 0; }
.identity-page h2 { margin: 0; font-size: 24px; font-weight: 650; line-height: 1.4; }
.identity-page p { color: var(--app-text-secondary, #475569); font-size: 13px; line-height: 1.8; margin: 5px 0; overflow-wrap: anywhere; }
.heading-icon { display: grid; place-items: center; flex: 0 0 44px; width: 44px; height: 44px; color: var(--app-primary, #2563eb); background: var(--app-primary-soft, #eff6ff); border-radius: 11px; font-size: 24px; }
.identity-overview { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 22px 0; }
.identity-overview > div { display: flex; gap: 12px; align-items: flex-start; min-width: 0; padding: 16px; border: 1px solid var(--app-border, #e2e8f0); border-radius: 10px; background: var(--app-surface, #fff); }
.identity-overview .el-icon { flex-shrink: 0; color: var(--app-primary, #2563eb); font-size: 21px; margin-top: 2px; }
.identity-overview span { font-size: 12px; color: var(--app-text-secondary, #475569); line-height: 1.7; }
.identity-overview strong { display: block; font-size: 17px; color: var(--app-text, #0f172a); margin-top: 5px; font-weight: 650; }
.identity-page > .el-alert { margin: 12px 0; }
.preview-toolbar { display: flex; gap: 12px; align-items: center; justify-content: space-between; flex-wrap: wrap; margin: 18px 0 12px; color: var(--app-text-secondary, #475569); font-size: 13px; }
.mapping-table { overflow: auto; max-width: 100%; background: var(--app-surface, #fff); border: 1px solid var(--app-border, #e2e8f0); border-radius: 10px; }
.mapping-table :deep(.cell) { line-height: 1.8; }
.mapping-table .el-select { width: 100%; }
.task-id { display: block; overflow-wrap: anywhere; margin: 7px 0; color: var(--app-text-secondary, #475569); font-size: 12px; }
.candidate { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: 12px; margin-top: 8px; color: var(--app-text-secondary, #475569); }
.acknowledgement { margin-top: 20px; white-space: normal; height: auto; align-items: flex-start; }
.acknowledgement :deep(.el-checkbox__label), .missing-name-review :deep(.el-checkbox__label) { white-space: normal; line-height: 1.8; }
.acknowledgement :deep(.el-checkbox__input), .missing-name-review :deep(.el-checkbox__input) { margin-top: 5px; }
.actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 16px 0; }
.actions .el-button + .el-button, .receipt-panel .el-button + .el-button { margin-left: 0; }
.receipt-panel { padding: 16px 18px; background: #fffbeb; border: 1px solid #f4d49e; border-left: 3px solid #d97706; border-radius: 10px; }
.receipt-panel > strong { color: #92400e; font-size: 15px; }
.receipt-panel .el-button { margin-top: 8px; margin-right: 8px; }
.receipt-panel code, .last-receipt code, .receipt-detail code { overflow-wrap: anywhere; white-space: normal; }
.last-receipt { display: flex; align-items: flex-start; gap: 9px; padding: 14px 16px; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 10px; color: #166534; font-size: 13px; line-height: 1.8; }
.last-receipt > .el-icon { flex-shrink: 0; margin-top: 4px; }
.last-receipt > span { min-width: 0; }
.last-receipt code { display: block; margin-top: 5px; font-size: 12px; }
.receipt-history { border-top: 1px solid var(--app-border, #e2e8f0); margin-top: 28px; padding-top: 8px; min-width: 0; }
.receipt-history h3 { margin: 0; font-size: 16px; font-weight: 650; }
.receipt-search { display: flex; align-items: center; gap: 8px; max-width: 760px; }
.receipt-search .el-input { flex: 1; min-width: 0; }
.receipt-search .el-button + .el-button { margin-left: 0; }
.receipt-history > .el-alert { margin-block: 12px; }
.receipt-detail { margin-top: 20px; padding: 4px 0 0 16px; border-left: 3px solid var(--app-primary, #2563eb); }
.receipt-detail .mapping-table { margin-top: 12px; }
.receipt-history > .el-button { margin-top: 12px; }
.identity-receipt-enter-active, .identity-receipt-leave-active { transition: opacity 180ms ease, transform 180ms ease; }
.identity-receipt-enter-from, .identity-receipt-leave-to { opacity: 0; transform: translateY(4px); }
.task-search { margin: 0 0 20px; }
.missing-name-review { display: grid; gap: 10px; margin-top: 12px; padding: 12px 0 0; border-top: 1px solid #f4d49e; }
.missing-name-review .el-checkbox { height: auto; align-items: flex-start; }
.identity-page :deep(.el-input__wrapper:focus-within), .identity-page :deep(.el-select__wrapper.is-focused) { outline: 2px solid var(--app-primary, #2563eb); outline-offset: 2px; }
.identity-page :deep(button:focus-visible) { outline: 2px solid var(--app-primary, #2563eb); outline-offset: 3px; }
:global(.identity-confirmation-dialog) { width: calc(100vw - 32px); max-width: 680px; max-height: 90vh; max-height: 90dvh; overflow-y: auto; }
:global(.identity-confirmation-dialog .el-message-box__btns) { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
:global(.identity-confirmation-dialog .el-message-box__btns .el-button + .el-button) { margin-left: 0; }
@media (max-width: 640px) {
  .identity-page-header { align-items: flex-start; }
  .identity-page h2 { font-size: 21px; }
  .identity-overview { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .identity-overview > div { padding: 14px; }
  .receipt-search { flex-wrap: wrap; }
  .receipt-search .el-input { flex-basis: 100%; }
  .receipt-detail { padding-left: 10px; }
  .heading-icon { flex-basis: 40px; width: 40px; height: 40px; }
}
@media (prefers-reduced-motion: reduce) {
  .identity-receipt-enter-active, .identity-receipt-leave-active { transition: none; }
  .identity-receipt-enter-from, .identity-receipt-leave-to { transform: none; }
}
</style>
