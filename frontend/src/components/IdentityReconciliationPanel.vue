<template>
  <section class="reconciliation-panel" :aria-labelledby="`${panelId}-title`">
    <header class="reconciliation-header">
      <div class="panel-heading">
        <span class="panel-icon"><el-icon aria-hidden="true"><DocumentChecked /></el-icon></span>
        <div><h3 :id="`${panelId}-title`">历史身份核对摘要</h3><p>对照任务关联与来源快照，追溯迁移前后的差异</p></div>
      </div>
      <el-button type="primary" :loading="creating" :disabled="!canCreate" @click="create">生成核对摘要</el-button>
    </header>
    <p class="snapshot-note">摘要记录观察时的状态。生成摘要不修改任务归属；处理差异前，仍需重新预览并核对当前权限。</p>
    <el-alert v-if="!enabled" title="当前环境尚未启用快照核对。已有请求编号可保留，待服务可用后查询。" type="info" :closable="false" show-icon />
    <p v-else-if="!canCreate && !creating" class="generation-note" role="status">{{ original ? '请先核对保留的原生成请求，再生成新的摘要。' : disabled ? '请等待当前预览或确认操作结束。' : !sourceProtection ? '启用身份来源记录后，才能生成核对摘要。' : !Number.isSafeInteger(revision) || revision < 0 ? '请先重新读取任务预览，取得有效控制版本。' : '正在读取核对结果，请稍候。' }}</p>
    <form class="report-lookup" @submit.prevent="lookup">
      <label :for="`${panelId}-request`">按原请求编号查询</label>
      <div class="report-search">
        <el-input :id="`${panelId}-request`" v-model="query" :disabled="statusBusy || creating" maxlength="128" clearable placeholder="输入原核对请求编号" />
        <el-button native-type="submit" :loading="statusBusy" :disabled="creating" :icon="Search">只读核对</el-button>
        <el-button v-if="notRecorded && original" :disabled="creating || statusBusy || disabled" @click="submitOriginal">重试原生成请求</el-button>
      </div>
    </form>
    <p v-if="original" class="pending-request" role="status">已保留原请求 <code>{{ original.requestId }}</code>。查询不到也可能仍在处理中，不会自动生成另一请求。</p>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <section v-if="report" :key="report.requestId" class="report-summary" :aria-labelledby="`${panelId}-snapshot`">
      <div class="section-heading"><h4 :id="`${panelId}-snapshot`">本次观察快照</h4><span class="snapshot-label">历史快照</span></div>
      <dl class="report-totals">
        <div><dt>覆盖任务</dt><dd>{{ countText(report.taskCount) }}</dd></div>
        <div><dt>职责关联位置</dt><dd>{{ countText(report.roleCount) }}</dd></div>
        <div :class="{ 'has-issues': report.issueCount > 0 }"><dt>存在差异的关联</dt><dd>{{ countText(report.issueCount) }}</dd></div>
      </dl>
      <dl class="snapshot-metadata">
        <div><dt>观察时间 UTC+8</dt><dd>{{ formatTime(report.startedAt) }} 至 {{ formatTime(report.finishedAt) }}</dd></div>
        <div><dt>执行账号</dt><dd>{{ report.actorName || '名称未记录' }} · ID {{ report.actorUserId ?? '未记录' }}</dd></div>
        <div><dt>控制版本</dt><dd>{{ report.controlRevision ?? '未记录' }}</dd></div>
        <div class="request-metadata"><dt>请求编号</dt><dd><code>{{ report.requestId }}</code></dd></div>
      </dl>
      <div class="reason-summary" aria-label="差异原因统计"><el-tag v-for="(count, reason) in report.summary.reasonCounts" :key="reason" :type="count > 0 ? 'warning' : 'info'" effect="light">{{ reasons[reason] || reason }} {{ countText(count) }}</el-tag></div>
      <p v-if="report.summary.comparison?.available" class="comparison-note">与上次观察比较：新增 {{ countText(report.summary.comparison.newIssueRows) }}，变化 {{ countText(report.summary.comparison.changedIssueRows) }}，相同 {{ countText(report.summary.comparison.unchangedIssueRows) }}，上次差异本次未再观察到 {{ countText(report.summary.comparison.previousIssuesNotObserved) }}。未再观察到也可能是记录删除或范围变化，不能据此认定已修复。</p>
      <el-collapse class="snapshot-evidence"><el-collapse-item title="查看资料摘要与对照编号" name="evidence"><p>资料摘要 <code>{{ report.datasetDigest }}</code></p><p>上次请求 <code>{{ report.summary.comparison?.previousRequestId || '没有同协议对照' }}</code></p><p>资料变化 {{ changes[report.summary.datasetChanged] || '未知' }}</p></el-collapse-item></el-collapse>
      <div class="section-heading detail-heading"><h4>快照差异明细</h4><span>{{ items.length ? `已读取 ${items.length.toLocaleString('zh-CN')} 条${itemsMore ? '，还有后续明细' : ''}` : itemsBusy ? '正在读取明细' : '本次读取范围' }}</span></div>
      <p>重新预览任务后再确认归属。旧摘要中的目标账号与确认不能直接用于当前写入。</p>
      <div class="report-table"><el-table :data="items" :aria-busy="itemsBusy">
        <template #empty><CollectionEmptyState :loading="itemsBusy" :error="itemsError" empty-title="本快照没有差异明细" empty-description="这里只展示本次观察的差异，当前任务授权仍需单独核对。" @retry="loadItems(true)" /></template>
        <el-table-column label="任务 / 职责" min-width="200"><template #default="{ row }"><strong>{{ roles[row.identity_role] || '职责未记录' }}</strong><code>{{ row.task_id }}</code><el-button link type="primary" :disabled="disabled" :aria-label="`重新预览任务 ${row.task_id} 的${roles[row.identity_role] || '身份'}关联`" @click="$emit('focus-task', row.task_id)">重新预览此任务</el-button></template></el-table-column>
        <el-table-column label="原关联" min-width="170"><template #default="{ row }"><p>{{ row.existing_name || '名称为空' }}</p><p>ID {{ row.existing_user_id ?? '未关联' }}</p><p>身份快照 {{ row.identity_name ?? '未保存' }}</p></template></el-table-column>
        <el-table-column label="当时的账号资料" min-width="190"><template #default="{ row }"><p>{{ row.current_username || '不可用' }}</p><p>{{ row.current_role || '角色未知' }}</p></template></el-table-column>
        <el-table-column label="差异" min-width="230"><template #default="{ row }"><div class="reason-list"><el-tag v-for="reason in row.reasons" :key="reason" type="warning" size="small">{{ reasons[reason] || reason }}</el-tag></div></template></el-table-column>
      </el-table></div>
      <div v-if="items.length && (itemsBusy || itemsError)" class="read-feedback" :role="itemsError ? 'alert' : 'status'"><span>{{ itemsBusy ? '正在读取差异明细，当前保留已读快照。' : itemsError }}</span><el-button v-if="itemsError && !itemsBusy" size="small" :icon="Refresh" @click="loadItems(true)">重新读取明细</el-button></div>
      <el-button v-if="itemsMore" :loading="itemsBusy" @click="loadItems(false)">继续读取明细</el-button>
    </section>
    <div class="report-history-heading"><div><h4>已保存的观察</h4><p>{{ history.length ? `已读取 ${history.length.toLocaleString('zh-CN')} 次观察${historyMore ? '，可继续读取更早记录' : ''}` : '按观察时间倒序读取，不代表实时授权状态' }}</p></div><el-button :loading="historyBusy" :disabled="!enabled" :icon="Refresh" @click="loadHistory(true)">刷新列表</el-button></div>
    <div class="report-table"><el-table :data="history" :aria-busy="historyBusy">
      <template #empty><CollectionEmptyState :loading="historyBusy" :error="historyError" :empty-title="enabled ? '暂无已保存的观察' : '当前未启用核对摘要'" :empty-description="enabled ? '生成一次核对摘要后，可在这里回看当时的差异。' : '已有原请求编号仍可在上方查询，不会自动生成或重试。'" @retry="loadHistory(true)" /></template>
      <el-table-column prop="requestId" label="请求编号" min-width="250" />
      <el-table-column label="时间 UTC+8" min-width="180"><template #default="{ row }">{{ formatTime(row.finishedAt) }}</template></el-table-column>
      <el-table-column label="任务" width="100"><template #default="{ row }">{{ countText(row.taskCount) }}</template></el-table-column>
      <el-table-column label="差异关联" width="110"><template #default="{ row }"><span :class="{ 'issue-count': row.issueCount > 0 }">{{ countText(row.issueCount) }}</span></template></el-table-column>
      <el-table-column label="明细" width="80"><template #default="{ row }"><el-button link type="primary" :disabled="statusBusy || creating" :aria-label="`查看核对摘要 ${row.requestId}`" @click="show(row.requestId)">查看</el-button></template></el-table-column>
    </el-table></div>
    <div v-if="history.length && (historyBusy || historyError)" class="read-feedback" :role="historyError ? 'alert' : 'status'"><span>{{ historyBusy ? '正在读取观察列表，当前保留已读记录。' : historyError }}</span><el-button v-if="historyError && !historyBusy" size="small" :disabled="!enabled" :icon="Refresh" @click="loadHistory(true)">重新读取列表</el-button></div>
    <el-button v-if="historyMore" :loading="historyBusy" :disabled="!enabled" @click="loadHistory(false)">更早的观察</el-button>
  </section>
</template>
<script setup>
import { computed, getCurrentInstance, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DocumentChecked, Refresh, Search } from '@element-plus/icons-vue'
import request from '@/api/request'
import CollectionEmptyState from '@/components/CollectionEmptyState.vue'
import { beijingDateTime } from '@/utils/beijingTime'
const props = defineProps({ enabled: Boolean, disabled: Boolean, revision: Number, sourceProtection: Boolean })
const panelId = `identity-reconciliation-${getCurrentInstance().uid}`
const formatTime = value => value ? beijingDateTime(value) || '时间未记录' : '时间未记录'
const countText = value => Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString('zh-CN') : '未记录'
defineEmits(['focus-task'])
const route = useRoute(), router = useRouter()
const creating = ref(false), statusBusy = ref(false), query = ref(''), error = ref(''), report = ref(null), original = ref(null), notRecorded = ref(false)
const items = ref([]), itemsBusy = ref(false), itemsMore = ref(false), itemsCursor = ref(0), itemsError = ref('')
let itemsGeneration = 0
function resetItems() { itemsGeneration++; items.value = []; itemsBusy.value = false; itemsMore.value = false; itemsCursor.value = 0; itemsError.value = '' }
const history = ref([]), historyBusy = ref(false), historyMore = ref(false), historyCursor = ref(0), historyError = ref('')
const roles = { created: '创建人', assignee: '责任人', reviewer: '复核人', disposition: '处置人', rework: '返工人' }
const reasons = { MISSING_NAME: '缺少名称', UNMAPPED: '尚未映射', INVALID_ID: '账号 ID 无效', SNAPSHOT_MISMATCH: '名称快照不一致', ACCOUNT_UNAVAILABLE: '账号已不可用', STALE_BINDING: '残留身份关联', SOURCE_UNVERIFIED: '来源待核对', SOURCE_INVALID: '来源异常', SOURCE_MISMATCH: '来源与任务不一致' }
const changes = { UNKNOWN: '没有对照', UNCHANGED: '摘要一致', CHANGED: '摘要发生变化' }
const validId = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value)
const canCreate = computed(() => props.enabled && !props.disabled && props.sourceProtection && Number.isSafeInteger(props.revision) && props.revision >= 0 && !creating.value && !statusBusy.value && !original.value)
const validReport = value => value?.found === true && value.state === 'COMPLETED_SNAPSHOT' && value.protocol === 'identity-reconciliation-v1' && validId(value.requestId) && Number.isSafeInteger(value.taskCount) && Number.isSafeInteger(value.roleCount) && Number.isSafeInteger(value.issueCount) && value.taskCount >= 0 && value.roleCount === value.taskCount * 5 && value.issueCount >= 0 && value.issueCount <= value.roleCount && /^[a-f0-9]{64}$/.test(value.datasetDigest) && value.summary?.reasonCounts && typeof value.summary.reasonCounts === 'object'
async function remember(id) { await router.replace({ query: { ...route.query, identityScan: id } }) }
async function create() {
  if (!canCreate.value) return
  original.value = { requestId: crypto.randomUUID(), revision: props.revision, sourceProtection: true }; query.value = original.value.requestId
  try { await remember(query.value); await submitOriginal() } catch { error.value = '原生成请求尚未确认，保留编号后只读核对' }
}
async function submitOriginal() {
  if (!original.value || creating.value || statusBusy.value || props.disabled) return
  creating.value = true; error.value = ''; notRecorded.value = false
  try {
    const { data } = await request.post('/api/detection/identity/reconciliations', original.value, { timeout: 45000, headers: { 'X-Identity-Action': 'update' } })
    if (!validReport(data) || data.requestId !== original.value.requestId) throw Error()
    resetItems(); report.value = data; original.value = null; await Promise.all([loadItems(true), loadHistory(true)])
  } catch (failure) {
    if ([400,403,409,413].includes(failure.response?.status)) { original.value = null; error.value = failure.response?.data?.message || '生成被拒绝，请核对当前权限、版本与配额' }
    else error.value = '生成结果未确认，请查询原编号。不会自动再次扫描或生成另一个请求'
  } finally { creating.value = false }
}
async function lookup() {
  const id = query.value.trim(); if (statusBusy.value || creating.value) return
  if (!validId(id)) { error.value = '请填写有效的原核对请求编号'; return }
  statusBusy.value = true; error.value = ''; resetItems(); report.value = null; notRecorded.value = false
  try {
    const { data } = await request.get(`/api/detection/identity/reconciliations/${encodeURIComponent(id)}`)
    if (data?.found === false) { notRecorded.value = original.value?.requestId === id; error.value = '当前未查到已提交摘要，原请求可能仍在处理中；不会自动重发'; return }
    if (!validReport(data) || data.requestId !== id) throw Error()
    report.value = data; if (original.value?.requestId === id) original.value = null
    await loadItems(true)
  } catch { error.value = '核对摘要暂不可读取，请保留原编号；权限变化和服务错误都不能当成生成失败证明' }
  finally { statusBusy.value = false }
}
async function loadItems(reset) {
  if (!report.value || itemsBusy.value) return
  itemsBusy.value = true; itemsError.value = ''; const id = report.value.requestId, generation = ++itemsGeneration
  try {
    const { data } = await request.get(`/api/detection/identity/reconciliations/${encodeURIComponent(id)}/items`, { params: { after: reset ? 0 : itemsCursor.value, size: 50 } })
    if (generation !== itemsGeneration || report.value?.requestId !== id) return
    if (data?.requestId !== id || !Array.isArray(data.records) || !data.records.every(row => Array.isArray(row.reasons) && row.reasons.every(reason => reasons[reason])) || !Number.isSafeInteger(data.nextCursor)) throw Error()
    items.value = reset ? data.records : [...items.value, ...data.records]; itemsCursor.value = data.nextCursor; itemsMore.value = data.hasMore === true
  } catch { if (generation === itemsGeneration && report.value?.requestId === id) itemsError.value = '差异明细暂不可核对，保留摘要与原编号' }
  finally { if (generation === itemsGeneration) itemsBusy.value = false }
}
async function loadHistory(reset) {
  if (!props.enabled || historyBusy.value) return
  historyBusy.value = true; historyError.value = ''
  try {
    const { data } = await request.get('/api/detection/identity/reconciliations', { params: { before: reset ? 0 : historyCursor.value, size: 10 } })
    if (!Array.isArray(data?.records) || !data.records.every(validReport) || !Number.isSafeInteger(data.nextCursor)) throw Error()
    history.value = reset ? data.records : [...history.value, ...data.records]; historyCursor.value = data.nextCursor; historyMore.value = data.hasMore === true
  } catch { historyError.value = '已保存观察列表暂不可读取' }
  finally { historyBusy.value = false }
}
async function show(id) { if (statusBusy.value || creating.value || !validId(id)) return; query.value = id; try { await remember(id); await lookup() } catch { error.value = '未能打开原摘要，请保留编号' } }
onMounted(async () => { const id = route.query.identityScan; if (validId(id)) { query.value = id; await lookup() } await loadHistory(true) })
</script>
<style scoped>
.reconciliation-panel { min-width: 0; margin-top: 28px; padding: 24px 0 0; border-top: 1px solid var(--app-border, #e2e8f0); color: var(--app-text, #0f172a); }
.reconciliation-header, .report-history-heading, .section-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
.panel-heading { display: flex; align-items: center; gap: 12px; min-width: 0; }
.panel-heading > div { min-width: 0; }
.panel-icon { display: grid; place-items: center; flex: 0 0 40px; width: 40px; height: 40px; border-radius: 10px; color: var(--app-primary, #2563eb); background: var(--app-primary-soft, #eff6ff); font-size: 23px; }
.reconciliation-panel h3, .reconciliation-panel h4 { margin: 0; color: var(--app-text, #0f172a); font-size: 16px; font-weight: 650; overflow-wrap: anywhere; }
.reconciliation-panel p { color: var(--app-text-secondary, #475569); font-size: 13px; line-height: 1.8; margin: 7px 0; overflow-wrap: anywhere; }
.reconciliation-panel .snapshot-note { max-width: 80ch; margin: 14px 0 18px; }
.reconciliation-panel .generation-note { color: #92400e; }
.report-lookup { margin: 18px 0; max-width: 900px; }
.report-lookup label { display: block; margin-bottom: 8px; font-size: 13px; font-weight: 550; color: var(--app-text-secondary, #475569); }
.report-search { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.report-search .el-input { flex: 1; min-width: 200px; }
.report-search .el-button + .el-button { margin-left: 0; }
.reconciliation-panel .pending-request { padding: 12px 14px; border-left: 3px solid #d97706; background: #fffbeb; color: #92400e; }
.report-summary { margin-top: 22px; padding: 20px; background: var(--app-surface, #fff); border: 1px solid var(--app-border, #e2e8f0); border-radius: 12px; animation: snapshot-enter 180ms ease-out; }
.snapshot-label { padding: 3px 8px; border-radius: 5px; background: #f1f5f9; color: var(--app-text-secondary, #475569); font-size: 12px; }
.report-totals { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0; margin: 20px 0; }
.report-totals > div { padding: 2px 20px; border-left: 1px solid var(--app-border, #e2e8f0); }
.report-totals > div:first-child { border-left: 0; padding-left: 0; }
.report-totals dt { font-size: 13px; line-height: 1.8; color: var(--app-text-secondary, #475569); }
.report-totals dd { margin: 6px 0 0; font-size: 28px; font-weight: 650; line-height: 1.3; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.report-totals .has-issues dd, .issue-count { color: #b45309; }
.snapshot-metadata { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 22px; margin: 18px 0; padding-block: 16px; border-block: 1px solid var(--app-border, #e2e8f0); }
.snapshot-metadata > div { min-width: 0; }
.snapshot-metadata dt { font-size: 12px; line-height: 1.7; color: var(--app-text-secondary, #475569); }
.snapshot-metadata dd { margin: 4px 0 0; font-size: 13px; line-height: 1.8; overflow-wrap: anywhere; }
.reason-summary, .reason-list { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 6px; margin: 12px 0; }
.reason-summary :deep(.el-tag), .reason-list :deep(.el-tag) { height: auto; min-height: 24px; white-space: normal; line-height: 1.6; padding-block: 3px; }
.reconciliation-panel .comparison-note { max-width: 80ch; margin: 14px 0; }
.snapshot-evidence { margin-block: 16px; }
.snapshot-evidence :deep(.el-collapse-item__header) { height: auto; min-height: 44px; padding-block: 6px; line-height: 1.7; }
.detail-heading { margin-top: 22px; }
.section-heading > span { font-size: 12px; color: var(--app-text-secondary, #475569); overflow-wrap: anywhere; }
.report-table { max-width: 100%; overflow: auto; margin: 12px 0; background: var(--app-surface, #fff); border-block: 1px solid var(--app-border, #e2e8f0); }
.report-table :deep(.cell) { overflow-wrap: anywhere; line-height: 1.8; }
.report-table :deep(.el-table__header .cell) { font-size: 12px; color: var(--app-text-secondary, #475569); }
.report-table code, .reconciliation-panel code { overflow-wrap: anywhere; white-space: normal; font-size: 12px; }
.report-table code { display: block; margin: 6px 0; }
.report-history-heading { margin-top: 26px; }
.report-history-heading p { margin-bottom: 0; }
.read-feedback { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin: 12px 0; font-size: 13px; line-height: 1.8; color: var(--app-text-secondary, #475569); }
.read-feedback[role="alert"] { color: #92400e; }
.read-feedback > span { min-width: 0; overflow-wrap: anywhere; }
.reconciliation-panel :deep(button:focus-visible) { outline: 2px solid var(--app-primary, #2563eb); outline-offset: 3px; }
.reconciliation-panel :deep(.el-input__wrapper:focus-within) { outline: 2px solid var(--app-primary, #2563eb); outline-offset: 2px; }
@keyframes snapshot-enter { from { opacity: 0; } to { opacity: 1; } }
@media (max-width: 640px) {
  .reconciliation-panel { padding-top: 20px; }
  .report-summary { padding: 14px; }
  .reconciliation-header { align-items: flex-start; }
  .report-totals { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .report-totals > div { padding: 0 0 12px; border-left: 0; border-bottom: 1px solid var(--app-border, #e2e8f0); }
  .report-totals > div:last-child { padding-bottom: 0; border-bottom: 0; }
  .report-totals dd { font-size: 24px; }
  .snapshot-metadata { grid-template-columns: minmax(0, 1fr); }
  .report-search .el-input { flex-basis: 100%; min-width: 0; }
}
@media (prefers-reduced-motion: reduce) { .report-summary { animation: none; } }
</style>
