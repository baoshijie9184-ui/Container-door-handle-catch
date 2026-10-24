<template>
  <div class="page-shell reports-page">
    <PageHero title="报告与审批" description="编写个人报告，提交固定版本给主管独立审批，编写人不能审批本人报告。"><template #actions><el-button :loading="loading" :disabled="busy" @click="load()"><AppIcon name="Refresh" :size="16" />刷新已查范围</el-button><el-button type="primary" :disabled="busy" @click="openCreate"><AppIcon name="Plus" :size="16" />新建报告草稿</el-button></template></PageHero>
    <p class="report-scope-note"><AppIcon name="Lock" :size="15" />{{ reportScope }}</p>
    <form class="toolbar-panel report-toolbar" @submit.prevent="search">
      <div class="report-filter-field"><label for="report-keyword">报告标题或任务编号</label><el-input id="report-keyword" v-model="keyword" aria-label="查询任务编号或报告标题" placeholder="输入标题或任务编号" maxlength="128" clearable /></div>
      <div class="report-filter-field"><label for="report-status">审批状态</label><el-select id="report-status" v-model="status" aria-label="审批状态" placeholder="全部状态" clearable><el-option v-for="(label, value) in states" :key="value" :label="label" :value="value" /></el-select></div>
      <el-button type="primary" native-type="submit" :loading="loading"><AppIcon name="Search" :size="16" />查询</el-button>
      <el-button v-if="keyword.trim() || status" @click="resetSearch"><AppIcon name="Refresh" :size="16" />重置</el-button>
    </form>
    <section class="table-panel">
      <p v-if="filtersDirty&&records.length" class="report-query-note" role="status">查询条件已修改，下方保留上次读取的结果；点击查询更新。</p>
      <div class="collection-heading"><h2><AppIcon name="DocumentChecked" :size="18" />报告记录</h2><span>{{ loading ? '正在读取…' : error ? '本次读取失败' : total===null ? '总数尚未读取' : `共 ${total} 条` }}</span></div>
      <p v-if="listLoaded" class="report-applied-query">已读取范围：{{ appliedQuery.keyword ? `关键词“${appliedQuery.keyword}”` : '全部关键词' }} · {{ appliedQuery.status ? states[appliedQuery.status] || '指定状态' : '全部状态' }} · 第 {{ appliedPage }} 页</p>
      <el-alert v-if="error && records.length" :title="error + '；下方保留先前读取的记录，请重新查询核对。'" type="error" show-icon :closable="false" />
      <TableReadHint v-if="records.length" />
      <el-table :scrollbar-tabindex="0" role="region" aria-label="质检报告记录" :data="records" v-loading="loading" row-key="reportId">
        <template #empty><CollectionEmptyState :loading="loading" :error="error" :filtered="!!(requestedQuery.keyword || requestedQuery.status)" empty-title="暂无质检报告" empty-description="可在新建报告草稿中填写有权访问的检测任务编号，提交后由主管独立审批。" @retry="retryList" @reset="resetSearch" /></template>
        <el-table-column label="报告与编写账号" min-width="265"><template #default="{ row }"><div class="report-list-identity"><button type="button" :disabled="busy" @click="openDetail(row.reportId)">{{ row.title || '未命名报告' }}</button><span>编写账号 {{ row.ownerUsername || '未记录' }}</span><details><summary>报告编号</summary><code>{{ row.reportId }}</code></details></div></template></el-table-column>
        <el-table-column label="依据任务" min-width="205"><template #default="{ row }"><router-link v-if="row.taskId" class="report-task-link" :to="{ path:'/inspection/history', query:{ keyword:row.taskId } }">{{ row.taskId }}</router-link><span v-else>未记录</span></template></el-table-column>
        <el-table-column label="状态与版本" min-width="145"><template #default="{ row }"><div class="report-list-status"><StatusBadge domain="report" :code="row.status" :label="states[row.status]" /><small>版本 {{ knownCount(row.version) ?? '未记录' }}</small></div></template></el-table-column>
        <el-table-column label="最近更新 · UTC+8" min-width="175"><template #default="{ row }"><span class="report-list-time">{{ reportTime(row.updatedAt) }}</span></template></el-table-column>
        <el-table-column label="操作" width="100"><template #default="{ row }"><el-button size="small" :disabled="busy" @click="openDetail(row.reportId)"><AppIcon name="Search" :size="16" />查看</el-button></template></el-table-column>
      </el-table>
      <div v-if="error && records.length" class="report-list-retry"><el-button size="small" :loading="loading" @click="retryList"><AppIcon name="Refresh" :size="15" />重试上次读取</el-button></div>
      <div v-if="total!==null" class="page-footer"><el-pagination :current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" :disabled="loading || !!error" @current-change="loadAppliedPage" /></div>
    </section>

    <el-dialog v-model="editorVisible" class="report-scroll-dialog report-editor-dialog" :title="editingId ? '编辑个人草稿' : '新建报告草稿'" width="min(650px, 94vw)" append-to-body :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
      <p class="report-dialog-note"><AppIcon name="Document" :size="16" />保存草稿时更新任务依据，提交审批后本版本冻结；报告审批与任务放行分别处理。</p>
      <p v-if="editingId" class="report-editor-version">正在编辑草稿版本 {{ knownCount(editingVersion) ?? '未记录' }} · 保存后请重新核对本版依据。</p>
      <el-form id="quality-report-editor-form" label-position="top" @submit.prevent="saveDraft">
        <section class="report-editor-section" aria-labelledby="report-editor-source-heading"><h3 id="report-editor-source-heading"><AppIcon name="Tickets" :size="18" />报告依据</h3>
        <el-form-item label="检测任务编号" required><el-input id="quality-report-task" v-model="form.taskId" aria-label="输入已完成检测任务编号" aria-describedby="report-editor-source-note" placeholder="输入已完成检测任务编号" :disabled="!!editingId || busy" maxlength="128" /></el-form-item>
        <p id="report-editor-source-note" class="report-editor-help">填写当前账号有权访问的已完成任务。编辑现有草稿时不能更换依据任务，可到<router-link :to="{path:'/inspection/history',query:typeof form.taskId==='string'&&form.taskId.trim()?{keyword:form.taskId.trim()}:{}}">检测记录</router-link>核对原始结果。</p></section>
        <section class="report-editor-section" aria-labelledby="report-editor-content-heading"><h3 id="report-editor-content-heading"><AppIcon name="Edit" :size="18" />标题与意见</h3>
        <el-form-item label="报告标题" required><el-input id="quality-report-title" v-model="form.title" aria-label="报告标题" placeholder="为本版报告填写清晰标题" maxlength="120" show-word-limit :disabled="busy" /></el-form-item>
        <el-form-item label="编写意见" required><el-input id="quality-report-narrative" v-model="form.narrative" type="textarea" :rows="7" maxlength="10000" show-word-limit aria-label="记录复核说明、风险和建议，检测数量以系统依据为准" placeholder="记录复核说明、风险和建议，检测数量以系统依据为准" :disabled="busy" /></el-form-item></section>
        <el-alert v-if="editorError" :title="editorError" type="error" :closable="false" />
      </el-form>
      <template #footer><div class="report-dialog-actions"><el-button :disabled="busy" @click="editorVisible = false"><AppIcon name="Close" :size="16" />取消</el-button><el-button type="primary" native-type="submit" form="quality-report-editor-form" :loading="busy"><AppIcon name="DocumentChecked" :size="16" />保存草稿</el-button></div></template>
    </el-dialog>

    <el-dialog v-model="detailVisible" class="report-scroll-dialog" title="报告详情" width="min(920px, 96vw)" append-to-body :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
      <div v-loading="detailLoading">
        <CollectionEmptyState v-if="!detail" :loading="detailLoading" :error="detailError" empty-title="报告资料尚未读取" empty-description="请重新读取当前报告，核对本版内容及操作记录。" @retry="openDetail(detailRequestedId)" />
        <template v-if="detail">
          <div class="detail-heading"><h2>{{ detail.title }}</h2><StatusBadge domain="report" :code="detail.status" :label="states[detail.status]" /><span class="report-version">版本 {{ detail.version }}</span></div>
          <dl class="report-identity-strip"><div><dt>编写账号</dt><dd>{{ detail.ownerUsername || '未记录' }}</dd></div><div><dt>依据任务</dt><dd>{{ detail.taskId || '未记录' }}</dd></div><div><dt>报告编号</dt><dd>{{ detail.reportId }}</dd></div></dl>
          <div class="report-next-step"><AppIcon name="DocumentChecked" :size="17" /><p>{{ reportNextStep }}</p></div>
          <p v-if="detail.previousReportId" class="muted">修订自报告 {{ detail.previousReportId }}</p>
          <h3><AppIcon name="Picture" :size="18" />本版检测依据</h3>
          <ReportBasis :source="detail.source" />
          <ReportSnapshotIdentity :key="detail.reportId+':'+detail.version" :report="detail" />
          <h3><AppIcon name="Edit" :size="18" />编写意见</h3><p class="narrative">{{ detail.narrative || '未记录编写意见' }}</p>
          <el-alert v-if="detail.status === 'DRAFT'" title="保存草稿会更新任务依据，提交后本版本内容冻结" type="info" :closable="false" />
          <el-alert v-if="detail.decisionReason" :title="`审批意见：${detail.decisionReason}`" :type="detail.status === 'APPROVED' ? 'success' : 'warning'" :closable="false" />
          <p v-if="detail.deciderUsername" class="muted">审批账号 {{ detail.deciderUsername }} · {{ reportTime(detail.decidedAt) }}（UTC+8）</p>
          <details class="report-delivery" aria-label="报告状态同步">
            <summary><AppIcon name="Connection" :size="16" />审批状态同步<span v-if="eventsError"> · 读取未完成</span><span v-else-if="events.some(item=>['FAILED','RETRY'].includes(item.deliveryStatus))"> · 有待核对的发送记录</span></summary>
            <div class="detail-heading"><p class="muted">发送状态与已记录的审批决定分别显示；失败会按原机制重试，重新发送不会再次审批。</p><el-button size="small" :disabled="busy" :loading="eventsLoading" @click="loadEvents(detail.reportId)"><AppIcon name="Refresh" :size="15" />刷新同步状态</el-button></div>
            <el-alert v-if="eventsError" :title="eventsError" type="error" :closable="false" />
            <el-table :scrollbar-tabindex="0" role="region" aria-label="报告同步状态更新" v-else :data="events" v-loading="eventsLoading" empty-text="本报告暂无已读取的同步状态更新" max-height="240">
              <el-table-column label="状态更新" min-width="110"><template #default="{ row }">{{ eventLabel(row.eventType) }}</template></el-table-column>
              <el-table-column label="发送状态" min-width="140"><template #default="{ row }"><StatusBadge domain="reportDelivery" :code="row.deliveryStatus" /></template></el-table-column>
              <el-table-column label="尝试次数" width="90"><template #default="{row}">{{ knownCount(row.attempts) ?? '—' }}</template></el-table-column>
              <el-table-column label="接收结果（UTC+8）" min-width="210"><template #default="{ row }">{{ row.consumedAt ? '已接收 · '+reportTime(row.consumedAt) : '等待接收确认' }}</template></el-table-column>
              <el-table-column v-if="isSupervisor" label="操作" width="110"><template #default="{ row }"><el-button v-if="['FAILED','RETRY'].includes(row.deliveryStatus)" size="small" :disabled="busy||eventsLoading" @click="retryEvent(row)">重新发送</el-button></template></el-table-column>
            </el-table>
          </details>
          <div class="detail-actions">
            <template v-if="own && detail.status === 'DRAFT'"><el-button :disabled="busy" @click="openEdit"><AppIcon name="Edit" :size="15" />编辑草稿</el-button><el-button type="primary" :loading="busy" @click="openTransition('submit')"><AppIcon name="DocumentChecked" :size="15" />提交主管审批</el-button></template>
            <el-button v-if="own && detail.status === 'SUBMITTED'" :disabled="busy" @click="openTransition('withdraw')">撤回申请</el-button>
            <el-button v-if="own && ['APPROVED', 'REJECTED', 'WITHDRAWN'].includes(detail.status)" :loading="busy" @click="runCommand('revise')">创建修订草稿</el-button>
            <template v-if="isSupervisor && !own && detail.status === 'SUBMITTED'"><el-button type="primary" :disabled="busy" @click="openDecision('APPROVE')">审批通过</el-button><el-button type="danger" plain :disabled="busy" @click="openDecision('REJECT')">驳回报告</el-button></template>
            <el-button v-if="detail.status === 'APPROVED'" :loading="busy" @click="download"><AppIcon name="Download" :size="15" />导出已审批报告</el-button>
          </div>
          <h3><AppIcon name="DocumentCopy" :size="18" />操作记录<span class="report-section-count">本次读取 {{ audits.length }} 条</span></h3>
          <el-table :scrollbar-tabindex="0" role="region" aria-label="报告操作记录" :data="audits" max-height="260"><el-table-column prop="actorUsername" label="操作账号" min-width="140" /><el-table-column label="操作" min-width="90"><template #default="{ row }">{{ auditLabels[row.action] || row.action }}</template></el-table-column><el-table-column prop="reportVersion" label="版本" width="65" /><el-table-column label="来源" min-width="150"><template #default="{ row }"><router-link v-if="row.runId" :to="{ path: '/agent/trace', query: { runId: row.runId } }">助手运行轨迹</router-link><span v-else>业务页面</span></template></el-table-column><el-table-column prop="reason" label="意见" min-width="160" /><el-table-column label="时间（UTC+8）" min-width="190"><template #default="{ row }">{{ reportTime(row.createdAt) }}</template></el-table-column></el-table>
        </template>
        <el-alert v-if="detailError&&detail" :title="detailError" type="error" :closable="false" />
      </div>
      <template #footer><div class="report-dialog-actions"><span v-if="detail" class="report-dialog-footnote">当前展示版本 {{ knownCount(detail.version) ?? '未记录' }} · 操作前以本版资料核对</span><el-button :disabled="busy" @click="detailVisible=false">关闭详情</el-button></div></template>
    </el-dialog>

    <el-dialog v-model="transitionVisible" class="report-scroll-dialog" :title="transition === 'submit' ? '提交主管审批' : '撤回报告申请'" width="min(480px, 94vw)" append-to-body :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
      <p>{{ transition === 'submit' ? '提交后本版本的意见和检测依据将冻结，主管审批的是这份内容。' : '撤回后保留本次提交快照和审计，可以创建修订草稿。' }}</p>
      <div v-if="detail" class="report-operation-context"><strong>{{ detail.title }}</strong><p>版本 {{ detail.version }} · 编写账号 {{ detail.ownerUsername }}</p><small>依据任务 {{ detail.taskId }}</small></div>
      <el-alert v-if="transitionError" :title="transitionError" type="warning" show-icon :closable="false" />
      <template #footer><el-button :disabled="busy" @click="transitionVisible = false"><AppIcon name="Close" :size="16" />取消</el-button><el-button type="primary" :loading="busy" @click="runCommand(transition)">确认{{ transition === 'submit' ? '提交' : '撤回' }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="decisionVisible" class="report-scroll-dialog" :title="decision === 'APPROVE' ? '报告审批通过' : '驳回报告'" width="min(700px, 94vw)" append-to-body :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
      <p class="report-dialog-note"><AppIcon name="Lock" :size="16" />先预览本次决定与报告版本，再明确确认。此操作不代替检测任务放行。</p>
      <el-form label-position="top"><el-form-item label="审批意见" required><el-input v-model="reason" type="textarea" :rows="3" maxlength="500" show-word-limit aria-label="填写本次审批依据与意见" placeholder="填写本次审批依据与意见" :disabled="busy || !!preview" /></el-form-item></el-form>
      <div v-if="preview" class="approval-preview">
        <h3>确认审批内容</h3><p>{{ preview.report.title }} · 版本 {{ preview.report.version }}</p>
        <p>依据任务 {{ preview.report.taskId }} · 编写账号 {{ preview.report.ownerUsername }}</p>
        <ReportBasis :source="preview.report.source" />
        <ReportSnapshotIdentity :key="preview.report.reportId+':'+preview.report.version" :report="preview.report" />
        <p class="narrative">{{ preview.report.narrative }}</p>
        <p>决定：{{ decision === 'APPROVE' ? '审批通过' : '驳回' }} · {{ preview.reason }}</p>
        <p class="muted">审批记录将引用此快照，确认有效至 {{ reportTime(preview.expiresAt) }} · UTC+8</p>
      </div>
      <el-alert v-if="decisionError" :title="decisionError" type="error" :closable="false" />
      <template #footer><el-button :disabled="busy" @click="decisionVisible = false"><AppIcon name="Close" :size="16" />取消</el-button><el-button v-if="preview" :disabled="busy" @click="preview = null">修改意见</el-button><el-button v-if="!preview" :type="decision === 'APPROVE' ? 'primary' : 'danger'" :loading="busy" @click="prepareDecision">预览审批操作</el-button><el-button v-else :type="decision === 'APPROVE' ? 'primary' : 'danger'" :loading="busy" @click="confirmDecision">确认{{ decision === 'APPROVE' ? '审批通过' : '驳回报告' }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../api/request'
import { useUserStore } from '../stores/user'
import { beijingDateTime } from '../utils/beijingTime'
import CollectionEmptyState from '../components/CollectionEmptyState.vue'
import ReportBasis from '../components/ReportBasis.vue'
import ReportSnapshotIdentity from '../components/ReportSnapshotIdentity.vue'
import { knownCount } from '../utils/countPresentation'

const reportTime = value => value ? beijingDateTime(value) || '时间格式未知' : '未记录'
const route = useRoute(), userStore = useUserStore()
const states = { DRAFT: '个人草稿', SUBMITTED: '待审批', APPROVED: '审批通过', REJECTED: '已驳回', WITHDRAWN: '已撤回' }
const auditLabels = { CREATE: '创建草稿', EDIT: '保存草稿', SUBMIT: '提交审批', WITHDRAW: '撤回', REVISE: '创建修订', APPROVE: '审批通过', REJECT: '驳回', EXPORT: '导出', EVENT_RETRY: '重新发送状态' }
const records = ref([]), status = ref(''), keyword = ref(''), page = ref(1), total = ref(null), loading = ref(false), error = ref('')
const appliedQuery = reactive({ keyword:'', status:'' })
const requestedQuery = reactive({ keyword:'', status:'', page:1 })
const listLoaded = ref(false), appliedPage = ref(1)
const filtersDirty = computed(() => keyword.value.trim()!==appliedQuery.keyword || (status.value||'')!==appliedQuery.status)
const busy = ref(false), detail = ref(null), detailVisible = ref(false), detailLoading = ref(false), detailError = ref(''), audits = ref([])
const events=ref([]),eventsError=ref(''),eventsLoading=ref(false)
const detailRequestedId=ref(''),transitionError=ref('')
const eventLabel=value=>({submitted:'提交审批',withdrawn:'撤回申请',approved:'审批通过',rejected:'驳回报告'}[value?.split('.')[2]]||'报告状态更新')
const editorVisible = ref(false), editingId = ref(''), editingVersion = ref(null), editorError = ref('')
const form = reactive({ taskId: '', title: '', narrative: '' })
const transitionVisible = ref(false), transition = ref('submit')
const decisionVisible = ref(false), decision = ref('APPROVE'), reason = ref(''), preview = ref(null), decisionError = ref('')
const own = computed(() => detail.value?.ownerUserId === userStore.identity?.userId)
const isSupervisor = computed(() => userStore.role === 'SUPERVISOR')
const reportScope = computed(() => isSupervisor.value ? '主管查看本人草稿及有权访问的非草稿报告；其他账号的私人草稿不共享。' : userStore.role === 'INSPECTOR' ? '员工查看本人报告，依据任务仍需在当前账号可访问范围；报告审批不代替任务放行。' : '仅显示当前账号有权访问的报告，私人草稿按编写账号隔离。')
const reportNextStep = computed(() => {
  const state = detail.value?.status
  if (state === 'DRAFT') return own.value ? '当前为个人草稿。核对编写意见与依据后，提交固定版本给其他主管审批。' : '报告尚为草稿，需编写人提交后才能进入审批。'
  if (state === 'SUBMITTED') return own.value ? '本版本已提交，等待其他主管独立审批。需要修改时先撤回，再创建修订草稿。' : isSupervisor.value ? '请核对提交快照，填写审批意见并预览，再确认本次决定。' : '本版本已提交，等待主管审批；当前不能作为已审批报告导出。'
  if (state === 'APPROVED') return own.value ? '本版本已审批，可导出。修改内容需要另建修订草稿，原版本保持完整。' : '本版本已审批，可通过导出按钮获取报告；任务处置状态仍需分别核对。'
  if (state === 'REJECTED') return '本版本已驳回，请核对审批意见。编写人可创建修订草稿，原记录继续保留。'
  if (state === 'WITHDRAWN') return '本版本已撤回，原快照和操作记录继续保留。编写人可创建修订草稿。'
  return '报告状态尚未确认，请重新读取后核对可用操作。'
})
const headers = { 'X-Report-Action': 'update' }
const keys = new Map()
let loadGeneration = 0, detailGeneration = 0
const message = e => e.response?.data?.message || e.message || '操作失败，请刷新核对状态'
function unwrap(response) { if (response.data?.code !== 200) throw new Error(response.data?.message || '请求失败'); return response.data.data }
function reportRows(value, label) {
  if (!Array.isArray(value) || value.some(row => !row || typeof row !== 'object' || Array.isArray(row))) throw new Error(`${label}尚未完整读取`)
  return value
}
function withId(operation, payload) {
  const key = JSON.stringify([operation, payload])
  if (!keys.has(key)) keys.set(key, crypto.randomUUID())
  return { ...payload, requestId: keys.get(key) }
}
async function load(queryOverride) {
  const generation = ++loadGeneration; loading.value = true; error.value = ''
  const source = queryOverride && typeof queryOverride === 'object' ? queryOverride : listLoaded.value ? { ...appliedQuery, page:appliedPage.value } : requestedQuery
  const query={keyword:source.keyword || '',status:source.status || ''}, requestedPage=source.page ?? page.value
  Object.assign(requestedQuery,query,{page:requestedPage})
  try { const data = unwrap(await request.get('/api/detection/reports', { params: { page: requestedPage, size: 20, status: query.status || undefined, keyword: query.keyword || undefined } })); if (generation === loadGeneration) { if(!Array.isArray(data?.records)||data.records.some(row=>!row||typeof row.reportId!=='string')||knownCount(data.total)===null)throw Error('报告列表或数量尚未完整读取');records.value = data.records; total.value = knownCount(data.total);Object.assign(appliedQuery,query);appliedPage.value=requestedPage;page.value=requestedPage;listLoaded.value=true } }
  catch (e) { if (generation === loadGeneration) { if([401,403].includes(e.response?.status)){records.value=[];total.value=null;listLoaded.value=false}error.value = message(e) } }
  finally { if (generation === loadGeneration) loading.value = false }
}
function search() { load({ keyword:keyword.value.trim(), status:status.value || '', page:1 }) }
function loadAppliedPage(nextPage) { load({ ...appliedQuery, page:nextPage }) }
function retryList() { load({ ...requestedQuery }) }
function resetSearch() { keyword.value = ''; status.value = ''; search() }
function openCreate() { keys.clear(); editingId.value = ''; editingVersion.value = null; form.taskId = String(route.query.taskId || ''); form.title = ''; form.narrative = ''; editorError.value = ''; editorVisible.value = true }
function openEdit() { keys.clear(); editingId.value = detail.value.reportId; editingVersion.value = detail.value.version; Object.assign(form, { taskId: detail.value.taskId, title: detail.value.title, narrative: detail.value.narrative }); editorError.value = ''; editorVisible.value = true }
async function saveDraft() {
  if (busy.value) return
  if (!form.taskId.trim() || !form.title.trim() || !form.narrative.trim()) return ElMessage.warning('请填写任务、标题和意见')
  busy.value = true; editorError.value = ''
  try {
    const payload = editingId.value ? withId(`edit:${editingId.value}`, { expectedVersion: editingVersion.value, title: form.title.trim(), narrative: form.narrative }) : withId('create', { taskId: form.taskId.trim(), title: form.title.trim(), narrative: form.narrative })
    const saved = unwrap(editingId.value ? await request.put(`/api/detection/reports/${editingId.value}`, payload, { headers }) : await request.post('/api/detection/reports', payload, { headers }))
    editorVisible.value = false; ElMessage.success('报告草稿已保存'); await load(); await openDetail(saved.reportId)
  } catch (e) { editorError.value = message(e) }
  finally { busy.value = false }
}
async function openDetail(id) {
  detailRequestedId.value=id
  const generation = ++detailGeneration; detailVisible.value = true; detailLoading.value = true; detailError.value = ''; detail.value = null; audits.value = [];events.value=[];eventsError.value=''
  try {
    const [report, audit] = await Promise.all([request.get(`/api/detection/reports/${id}`), request.get(`/api/detection/reports/${id}/audit`)])
    if (generation !== detailGeneration) return
    const reportData = unwrap(report), auditData = unwrap(audit)
    if (reportData?.reportId !== id) throw new Error('报告编号与当前选择不一致，请重新核对')
    const rows = reportRows(auditData, '报告操作记录')
    detail.value = reportData; audits.value = rows; loadEvents(id)
  }
  catch (e) { if (generation === detailGeneration) detailError.value = message(e) }
  finally { if (generation === detailGeneration) detailLoading.value = false }
}
async function loadEvents(id){
  const generation=detailGeneration;eventsLoading.value=true;eventsError.value=''
  try{const result=unwrap(await request.get(`/api/detection/reports/${id}/events`));if(generation===detailGeneration)events.value=reportRows(result,'报告同步记录')}
  catch(e){if(generation===detailGeneration){events.value=[];eventsError.value=message(e)}}finally{if(generation===detailGeneration)eventsLoading.value=false}
}
async function retryEvent(event){
  if(busy.value||!detail.value)return
  const generation=detailGeneration,id=detail.value.reportId;busy.value=true
  try{
    try{await ElMessageBox.confirm(`重新发送“${eventLabel(event.eventType)}”状态更新 不会重新执行审批`,'重新发送报告状态',{confirmButtonText:'确认重新发送',cancelButtonText:'取消'})}catch{return}
    if(generation!==detailGeneration)return
    const payload=withId(`retry-event:${event.eventId}`,{expectedAttempts:event.attempts,confirmed:true})
    const result=unwrap(await request.post(`/api/detection/reports/${id}/events/${event.eventId}/retry`,payload,{headers}));if(generation!==detailGeneration)return;events.value=reportRows(result,'报告同步记录')
    const auditResult=unwrap(await request.get(`/api/detection/reports/${id}/audit`))
    if(generation===detailGeneration){audits.value=reportRows(auditResult,'报告操作记录');ElMessage.success('已安排重新发送')}
  }catch(e){if(generation===detailGeneration){await loadEvents(id);eventsError.value=message(e)}}finally{busy.value=false}
}
function openTransition(action) { transition.value = action; transitionError.value=''; transitionVisible.value = true }
async function runCommand(action) {
  if (busy.value || !detail.value) return
  busy.value = true; detailError.value = '';transitionError.value=''
  try { const id = detail.value.reportId; const saved = unwrap(await request.post(`/api/detection/reports/${id}/${action}`, withId(`${action}:${id}`, { expectedVersion: detail.value.version }), { headers })); transitionVisible.value = false; await load(); await openDetail(saved.reportId); ElMessage.success('报告状态已更新') }
  catch (e) { if(transitionVisible.value)transitionError.value=message(e)+'；请核对当前报告状态，不会自动重发';else detailError.value = message(e) }
  finally { busy.value = false }
}
function openDecision(action) { decision.value = action; reason.value = ''; preview.value = null; decisionError.value = ''; decisionVisible.value = true }
async function prepareDecision() {
  if (busy.value || !detail.value) return
  if (!reason.value.trim()) return ElMessage.warning('请填写审批意见')
  busy.value = true; decisionError.value = ''
  try { preview.value = unwrap(await request.post(`/api/detection/reports/${detail.value.reportId}/decision-preview`, { expectedVersion: detail.value.version, decision: decision.value, reason: reason.value.trim() }, { headers })) }
  catch (e) { decisionError.value = message(e) }
  finally { busy.value = false }
}
async function confirmDecision() {
  if (busy.value || !preview.value) return
  busy.value = true; decisionError.value = ''
  try {
    const p = preview.value; const saved = unwrap(await request.post(`/api/detection/reports/${p.report.reportId}/decision`, withId(`decide:${p.report.reportId}`, { expectedVersion: p.report.version, decision: p.decision, reason: p.reason, confirmationToken: p.confirmationToken }), { headers }))
    decisionVisible.value = false; preview.value = null; await load(); await openDetail(saved.reportId); ElMessage.success('审批决定已记录')
  } catch (e) { decisionError.value = message(e) }
  finally { busy.value = false }
}
async function download() {
  if (busy.value || !detail.value) return
  busy.value = true; detailError.value = ''
  try {
    const response = await request.post(`/api/detection/reports/${detail.value.reportId}/export`, null, { headers, responseType: 'blob' })
    if (!(response.headers['content-type'] || '').startsWith('text/markdown')) throw new Error('报告导出失败，请刷新核对状态')
    const url = URL.createObjectURL(response.data), link = document.createElement('a'); link.href = url; link.download = `${detail.value.reportId}.md`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
    await openDetail(detail.value.reportId)
  } catch (e) { detailError.value = message(e) }
  finally { busy.value = false }
}
onMounted(async () => { if (!userStore.identity) await userStore.checkAuth(); await load(); if (route.query.reportId) await openDetail(String(route.query.reportId)); else if (route.query.taskId) openCreate() })
onBeforeUnmount(()=>{detailGeneration++;loadGeneration++;events.value=[];eventsError.value='';keys.clear()})
</script>

<style scoped>
.reports-page { gap: 18px; }
.report-delivery { margin-top:20px;padding:16px;border:1px solid #dce6f4;border-radius:12px;background:#f7faff; }.report-delivery h3{margin:0}
.report-toolbar { display: flex; gap: 12px; flex-wrap: wrap; }
.report-toolbar .el-input { width: 280px; }.report-toolbar .el-select { width: 180px; }
.detail-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
h2 { font-size: 20px; overflow-wrap: anywhere; }h3 { margin-top: 22px; font-size: 16px; }
h3 { display:flex; align-items:center; gap:8px; color:var(--app-text); }
h3 .el-icon { color:var(--app-primary); }
.report-toolbar { align-items:flex-end; }
.report-filter-field { display:grid; gap:8px; min-width:0; }
.report-filter-field label { font-size:12px; color:var(--app-text-secondary); font-weight:550; }
.report-scope-note { display:flex; align-items:flex-start; gap:8px; margin:0; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.report-scope-note > .el-icon { margin-top:3px; flex-shrink:0; color:var(--app-primary); }
.report-applied-query { margin:0 0 16px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.report-list-identity { display:grid; justify-items:start; gap:6px; padding:6px 0; min-width:0; }
.report-list-identity > button { max-width:100%; padding:0; border:0; background:none; color:var(--app-text); font:inherit; font-size:14px; font-weight:600; text-align:left; line-height:1.65; overflow-wrap:anywhere; cursor:pointer; transition:color 160ms ease; }
.report-list-identity > button:hover { color:var(--app-primary); }
.report-list-identity > button:disabled { color:var(--app-text-secondary); cursor:wait; }
.report-list-identity > span,.report-list-identity details { max-width:100%; color:var(--app-text-secondary); font-size:12px; line-height:1.7; }
.report-list-identity summary { width:fit-content; cursor:pointer; }
.report-list-identity code { display:block; padding-top:5px; font-size:11px; overflow-wrap:anywhere; }
.report-list-status { display:grid; justify-items:start; gap:7px; }
.report-list-status small { color:var(--app-text-secondary); font-size:12px; }
.report-list-time { color:var(--app-text-secondary); font-size:12px; font-variant-numeric:tabular-nums; }
.report-task-link { color:var(--app-primary); text-decoration:underline; text-underline-offset:3px; font-size:12px; overflow-wrap:anywhere; }
.report-list-retry { margin-top:14px; }
:is(.report-list-identity button,.report-list-identity summary,.report-task-link,.report-delivery summary):focus-visible { outline:2px solid var(--app-primary); outline-offset:4px; border-radius:3px; }
.report-query-note { margin:0 0 12px; font-size:12px; line-height:1.8; color:var(--app-text-secondary); }
.report-dialog-note { display:flex; align-items:flex-start; gap:8px; margin:0 0 20px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.report-dialog-note .el-icon { flex:0 0 auto; margin-top:3px; color:var(--app-primary); }
.report-editor-version { margin:0 0 18px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.report-editor-section { padding:16px 0 4px; border-top:1px solid var(--app-border); }
.report-editor-section h3 { margin:0 0 18px; color:var(--app-text); font-size:14px; font-weight:600; line-height:1.8; }
.report-editor-help { margin:-4px 0 18px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; overflow-wrap:anywhere; }
.report-editor-help a { color:var(--app-primary); text-underline-offset:3px; }
.report-dialog-actions { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:8px; width:100%; }
.report-dialog-actions .el-button + .el-button { margin-left:0; }
.report-dialog-footnote { flex:1 1 200px; text-align:left; color:var(--app-text-secondary); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.report-section-count { margin-left:auto; color:var(--app-text-secondary); font-size:11px; font-weight:400; }
.report-identity-strip { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.5fr) minmax(0,1.5fr); gap:16px; margin:18px 0; }
.report-identity-strip dt { font-size:11px; line-height:1.8; color:var(--app-text-muted); }
.report-identity-strip dd { margin:5px 0 0; color:var(--app-text); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.report-next-step { display:flex; gap:9px; align-items:flex-start; padding:12px 14px; border-radius:8px; background:var(--app-primary-soft); color:var(--app-text-secondary); }
.report-next-step > .el-icon { color:var(--app-primary); margin-top:3px; flex:0 0 auto; }
.report-next-step p { margin:0; font-size:12px; line-height:1.85; }
.report-delivery { background:white; border:1px solid var(--app-border); border-radius:9px; }
.report-delivery summary { width:fit-content; max-width:100%; cursor:pointer; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.report-delivery summary .el-icon { margin-right:6px; vertical-align:middle; color:var(--app-primary); }
.report-delivery summary span { color:var(--app-warning); }
.report-operation-context { padding:14px 16px; margin:16px 0; border:1px solid var(--app-border); border-radius:8px; background:var(--app-primary-light); overflow-wrap:anywhere; }
.report-operation-context strong { color:var(--app-text); font-size:14px; line-height:1.8; }
.report-operation-context :is(p,small) { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
@media(max-width:640px) { .report-identity-strip { grid-template-columns:minmax(0,1fr); gap:10px; } .report-filter-field { width:100%; } .report-toolbar .el-input,.report-toolbar .el-select { width:100%; } }
.source-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }.source-grid div { display: flex; flex-direction: column; gap: 6px; }
.source-grid span, .muted { font-size: 13px; color: #64748b; }.source-grid strong { font-weight: 500; overflow-wrap: anywhere; }
.narrative { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }.detail-actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0; }
.approval-preview { border:0; border-top:2px solid var(--app-border-focus); padding:16px 0; border-radius:0; background:white; }
.approval-preview > h3 { margin:0 0 12px; font-size:16px; }
.approval-preview > p { color:var(--app-text-secondary); font-size:13px; line-height:1.85; overflow-wrap:anywhere; }
.el-button { transition: transform 160ms ease; }.el-button:active { transform: scale(.98); }
@media (prefers-reduced-motion: reduce) { .el-button,.report-list-identity > button { transition: none; }.el-button:active { transform: none; } }
</style>

<style>
.report-scroll-dialog.el-dialog { display:flex; flex-direction:column; margin-top:5vh; margin-bottom:5vh; max-height:90vh; max-height:90dvh; }
.report-scroll-dialog :is(.el-dialog__header,.el-dialog__footer) { flex-shrink:0; }
.report-scroll-dialog .el-dialog__title { display:block; padding-right:28px; font-size:17px; line-height:1.75; overflow-wrap:anywhere; }
.report-scroll-dialog .el-dialog__body { min-height:0; max-height:65vh; max-height:65dvh; overflow:auto; overscroll-behavior:contain; }
.report-scroll-dialog .el-dialog__footer { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:8px; }
.report-scroll-dialog .el-dialog__footer .el-button + .el-button { margin-left:0; }
.report-scroll-dialog :is(a,summary):focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; border-radius:3px; }
.report-scroll-dialog .detail-actions .el-button + .el-button { margin-left:0; }
</style>
