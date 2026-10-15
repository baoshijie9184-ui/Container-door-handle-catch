<template>
  <div class="page-shell reports-page">
    <section class="page-hero">
      <div><span class="page-hero-label">Quality Reports</span><h1 class="page-hero-title">报告与审批</h1>
        <p class="page-hero-text">编写个人报告，提交固定版本给主管审批，保留检测依据和审批记录。</p></div>
      <el-button type="primary" @click="openCreate">新建报告草稿</el-button>
    </section>
    <section class="toolbar-panel report-toolbar">
      <el-input v-model="keyword" placeholder="查询任务编号或报告标题" clearable @keyup.enter="search" />
      <el-select v-model="status" placeholder="全部状态" clearable><el-option v-for="(label, value) in states" :key="value" :label="label" :value="value" /></el-select>
      <el-button :loading="loading" @click="search">查询</el-button>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
    </section>
    <section class="table-panel">
      <el-table :data="records" v-loading="loading" row-key="reportId">
        <el-table-column prop="title" label="报告标题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="taskId" label="依据任务" min-width="200" show-overflow-tooltip />
        <el-table-column prop="ownerUsername" label="编写账号" min-width="150" />
        <el-table-column label="状态" width="120"><template #default="{ row }"><el-tag :type="row.status === 'APPROVED' ? 'success' : row.status === 'REJECTED' ? 'danger' : 'info'">{{ states[row.status] }}</el-tag></template></el-table-column>
        <el-table-column prop="version" label="版本" width="70" />
        <el-table-column label="操作" width="100"><template #default="{ row }"><el-button size="small" @click="openDetail(row.reportId)">查看</el-button></template></el-table-column>
      </el-table>
      <div class="page-footer"><el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" @current-change="load" /></div>
    </section>

    <el-dialog v-model="editorVisible" :title="editingId ? '编辑个人草稿' : '新建报告草稿'" width="min(650px, 94vw)" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
      <el-form label-position="top">
        <el-form-item label="检测任务编号"><el-input v-model="form.taskId" placeholder="输入已完成检测任务编号" :disabled="!!editingId || busy" maxlength="128" /></el-form-item>
        <el-form-item label="报告标题"><el-input v-model="form.title" placeholder="报告标题" maxlength="120" :disabled="busy" /></el-form-item>
        <el-form-item label="编写意见"><el-input v-model="form.narrative" type="textarea" :rows="7" maxlength="10000" placeholder="记录复核说明、风险和建议，检测数量以系统依据为准" :disabled="busy" /></el-form-item>
        <el-alert v-if="editorError" :title="editorError" type="error" :closable="false" />
      </el-form>
      <template #footer><el-button :disabled="busy" @click="editorVisible = false">取消</el-button><el-button type="primary" :loading="busy" @click="saveDraft">保存草稿</el-button></template>
    </el-dialog>

    <el-dialog v-model="detailVisible" class="report-scroll-dialog" title="报告详情" width="min(920px, 96vw)" append-to-body :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
      <div v-loading="detailLoading">
        <template v-if="detail">
          <div class="detail-heading"><h2>{{ detail.title }}</h2><el-tag>{{ states[detail.status] }} · 版本 {{ detail.version }}</el-tag></div>
          <p class="muted">{{ detail.ownerUsername }} · 任务 {{ detail.taskId }}</p>
          <p v-if="detail.previousReportId" class="muted">修订自报告 {{ detail.previousReportId }}</p>
          <h3>检测依据</h3>
          <div class="source-grid"><div v-for="(label, key) in sourceLabels" :key="key"><span>{{ label }}</span><strong>{{ fact(detail.source?.[key]) }}</strong></div></div>
          <h3>编写意见</h3><p class="narrative">{{ detail.narrative }}</p>
          <el-alert v-if="detail.status === 'DRAFT'" title="保存草稿会更新任务依据，提交后本版本内容冻结" type="info" :closable="false" />
          <el-alert v-if="detail.decisionReason" :title="`审批意见：${detail.decisionReason}`" :type="detail.status === 'APPROVED' ? 'success' : 'warning'" :closable="false" />
          <p v-if="detail.deciderUsername" class="muted">审批账号 {{ detail.deciderUsername }} · {{ detail.decidedAt }}</p>
          <section class="report-delivery" aria-label="报告状态同步">
            <div class="detail-heading"><h3>状态同步</h3><el-button size="small" :disabled="busy" :loading="eventsLoading" @click="loadEvents(detail.reportId)">刷新同步状态</el-button></div>
            <p class="muted">发送失败会自动重试 重新发送不会重复执行审批</p>
            <el-alert v-if="eventsError" :title="eventsError" type="error" :closable="false" />
            <el-table v-else :data="events" empty-text="本报告暂无需要同步的状态更新" max-height="240">
              <el-table-column label="状态更新" min-width="110"><template #default="{ row }">{{ eventLabel(row.eventType) }}</template></el-table-column>
              <el-table-column label="发送状态" min-width="110"><template #default="{ row }">{{ deliveryLabels[row.deliveryStatus] || '待核对' }}</template></el-table-column>
              <el-table-column prop="attempts" label="尝试次数" width="90" />
              <el-table-column label="接收结果" min-width="170"><template #default="{ row }">{{ row.consumedAt ? '已接收 · '+row.consumedAt : '等待接收确认' }}</template></el-table-column>
              <el-table-column v-if="isSupervisor" label="操作" width="110"><template #default="{ row }"><el-button v-if="['FAILED','RETRY'].includes(row.deliveryStatus)" size="small" :disabled="busy||eventsLoading" @click="retryEvent(row)">重新发送</el-button></template></el-table-column>
            </el-table>
          </section>
          <div class="detail-actions">
            <template v-if="own && detail.status === 'DRAFT'"><el-button :disabled="busy" @click="openEdit">编辑草稿</el-button><el-button type="primary" :loading="busy" @click="openTransition('submit')">提交主管审批</el-button></template>
            <el-button v-if="own && detail.status === 'SUBMITTED'" :disabled="busy" @click="openTransition('withdraw')">撤回申请</el-button>
            <el-button v-if="own && ['APPROVED', 'REJECTED', 'WITHDRAWN'].includes(detail.status)" :loading="busy" @click="runCommand('revise')">创建修订草稿</el-button>
            <template v-if="isSupervisor && !own && detail.status === 'SUBMITTED'"><el-button type="primary" :disabled="busy" @click="openDecision('APPROVE')">审批通过</el-button><el-button type="danger" plain :disabled="busy" @click="openDecision('REJECT')">驳回报告</el-button></template>
            <el-button v-if="detail.status === 'APPROVED'" :loading="busy" @click="download">导出已审批报告</el-button>
          </div>
          <h3>操作记录</h3>
          <el-table :data="audits" max-height="260"><el-table-column prop="actorUsername" label="操作账号" min-width="140" /><el-table-column label="操作" min-width="90"><template #default="{ row }">{{ auditLabels[row.action] || row.action }}</template></el-table-column><el-table-column prop="reportVersion" label="版本" width="65" /><el-table-column label="来源" min-width="150"><template #default="{ row }"><router-link v-if="row.runId" :to="{ path: '/agent/trace', query: { runId: row.runId } }">助手运行轨迹</router-link><span v-else>业务页面</span></template></el-table-column><el-table-column prop="reason" label="意见" min-width="160" /><el-table-column prop="createdAt" label="时间" min-width="170" /></el-table>
        </template>
        <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
      </div>
    </el-dialog>

    <el-dialog v-model="transitionVisible" :title="transition === 'submit' ? '提交主管审批' : '撤回报告申请'" width="min(480px, 94vw)" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
      <p>{{ transition === 'submit' ? '提交后本版本的意见和检测依据将冻结，主管审批的是这份内容。' : '撤回后保留本次提交快照和审计，可以创建修订草稿。' }}</p>
      <template #footer><el-button :disabled="busy" @click="transitionVisible = false">取消</el-button><el-button type="primary" :loading="busy" @click="runCommand(transition)">确认{{ transition === 'submit' ? '提交' : '撤回' }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="decisionVisible" class="report-scroll-dialog" :title="decision === 'APPROVE' ? '报告审批通过' : '驳回报告'" width="min(700px, 94vw)" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
      <el-form label-position="top"><el-form-item label="审批意见"><el-input v-model="reason" type="textarea" :rows="3" maxlength="500" placeholder="填写本次审批依据与意见" :disabled="busy || !!preview" /></el-form-item></el-form>
      <div v-if="preview" class="approval-preview">
        <h3>确认审批内容</h3><p>{{ preview.report.title }} · 版本 {{ preview.report.version }}</p>
        <p>依据任务 {{ preview.report.taskId }} · 编写账号 {{ preview.report.ownerUsername }}</p>
        <div class="source-grid"><div><span>成功 / 总图片</span><strong>{{ preview.report.source?.successfulImages }} / {{ preview.report.source?.totalImages }}</strong></div><div><span>确认缺陷数</span><strong>{{ fact(preview.report.source?.confirmedDefectCount) }}</strong></div><div><span>复核结论</span><strong>{{ fact(preview.report.source?.reviewConclusion) }}</strong></div></div>
        <p class="narrative">{{ preview.report.narrative }}</p>
        <p>决定：{{ decision === 'APPROVE' ? '审批通过' : '驳回' }} · {{ preview.reason }}</p>
        <p class="muted">审批记录将引用此快照，确认有效至 {{ preview.expiresAt }}</p>
      </div>
      <el-alert v-if="decisionError" :title="decisionError" type="error" :closable="false" />
      <template #footer><el-button :disabled="busy" @click="decisionVisible = false">取消</el-button><el-button v-if="preview" :disabled="busy" @click="preview = null">修改意见</el-button><el-button v-if="!preview" type="primary" :loading="busy" @click="prepareDecision">预览审批操作</el-button><el-button v-else type="primary" :loading="busy" @click="confirmDecision">确认{{ decision === 'APPROVE' ? '审批通过' : '驳回报告' }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../api/request'
import { useUserStore } from '../stores/user'
const route = useRoute(), userStore = useUserStore()
const states = { DRAFT: '个人草稿', SUBMITTED: '待审批', APPROVED: '审批通过', REJECTED: '已驳回', WITHDRAWN: '已撤回' }
const auditLabels = { CREATE: '创建草稿', EDIT: '保存草稿', SUBMIT: '提交审批', WITHDRAW: '撤回', REVISE: '创建修订', APPROVE: '审批通过', REJECT: '驳回', EXPORT: '导出', EVENT_RETRY: '重新发送状态' }
const sourceLabels = { modelId: '检测模型', modelVersion: '模型版本', totalImages: '图片总数', successfulImages: '成功图片', failedImages: '失败图片', defectCount: '缺陷数量', reviewStatus: '人工复核状态', reviewConclusion: '复核结论', confirmedDefectCount: '确认缺陷数', falsePositiveCount: '误报数', reviewer: '复核账号', finishedAt: '检测完成时间' }
const fact = value => ({ REVIEWED: '已复核', PENDING: '待复核', PASS: '通过', DEFECT: '确认缺陷', RECHECK: '需要复检', REJECT: '拒绝', NORMAL_RELEASE: '正常放行', CONFIRMED_DEFECT: '确认缺陷', NEEDS_RECHECK: '需要复检', FALSE_POSITIVE: '误报' })[value] || (value ?? '未记录')
const records = ref([]), status = ref(''), keyword = ref(''), page = ref(1), total = ref(0), loading = ref(false), error = ref('')
const busy = ref(false), detail = ref(null), detailVisible = ref(false), detailLoading = ref(false), detailError = ref(''), audits = ref([])
const events=ref([]),eventsError=ref(''),eventsLoading=ref(false)
const deliveryLabels={PENDING:'等待发送',PROCESSING:'发送中',RETRY:'等待重试',DELIVERED:'已发送',FAILED:'需检查后重试'}
const eventLabel=value=>({submitted:'提交审批',withdrawn:'撤回申请',approved:'审批通过',rejected:'驳回报告'}[value?.split('.')[2]]||'报告状态更新')
const editorVisible = ref(false), editingId = ref(''), editingVersion = ref(null), editorError = ref('')
const form = reactive({ taskId: '', title: '', narrative: '' })
const transitionVisible = ref(false), transition = ref('submit')
const decisionVisible = ref(false), decision = ref('APPROVE'), reason = ref(''), preview = ref(null), decisionError = ref('')
const own = computed(() => detail.value?.ownerUserId === userStore.identity?.userId)
const isSupervisor = computed(() => userStore.role === 'SUPERVISOR')
const headers = { 'X-Report-Action': 'update' }
const keys = new Map()
let loadGeneration = 0, detailGeneration = 0
const message = e => e.response?.data?.message || e.message || '操作失败，请刷新核对状态'
function unwrap(response) { if (response.data?.code !== 200) throw new Error(response.data?.message || '请求失败'); return response.data.data }
function withId(operation, payload) {
  const key = JSON.stringify([operation, payload])
  if (!keys.has(key)) keys.set(key, crypto.randomUUID())
  return { ...payload, requestId: keys.get(key) }
}
async function load() {
  const generation = ++loadGeneration; loading.value = true; error.value = ''
  try { const data = unwrap(await request.get('/api/detection/reports', { params: { page: page.value, size: 20, status: status.value || undefined, keyword: keyword.value || undefined } })); if (generation === loadGeneration) { records.value = data.records || []; total.value = data.total || 0 } }
  catch (e) { if (generation === loadGeneration) error.value = message(e) }
  finally { if (generation === loadGeneration) loading.value = false }
}
function search() { page.value = 1; load() }
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
  const generation = ++detailGeneration; detailVisible.value = true; detailLoading.value = true; detailError.value = ''; detail.value = null; audits.value = [];events.value=[];eventsError.value=''
  try { const [report, audit] = await Promise.all([request.get(`/api/detection/reports/${id}`), request.get(`/api/detection/reports/${id}/audit`)]); if (generation === detailGeneration) { detail.value = unwrap(report); audits.value = unwrap(audit) || [];loadEvents(id) } }
  catch (e) { if (generation === detailGeneration) detailError.value = message(e) }
  finally { if (generation === detailGeneration) detailLoading.value = false }
}
async function loadEvents(id){
  const generation=detailGeneration;eventsLoading.value=true;eventsError.value=''
  try{const result=unwrap(await request.get(`/api/detection/reports/${id}/events`));if(generation===detailGeneration)events.value=result||[]}
  catch(e){if(generation===detailGeneration){events.value=[];eventsError.value=message(e)}}finally{if(generation===detailGeneration)eventsLoading.value=false}
}
async function retryEvent(event){
  if(busy.value||!detail.value)return
  const generation=detailGeneration,id=detail.value.reportId;busy.value=true
  try{
    try{await ElMessageBox.confirm(`重新发送“${eventLabel(event.eventType)}”状态更新 不会重新执行审批`,'重新发送报告状态',{confirmButtonText:'确认重新发送',cancelButtonText:'取消'})}catch{return}
    if(generation!==detailGeneration)return
    const payload=withId(`retry-event:${event.eventId}`,{expectedAttempts:event.attempts,confirmed:true})
    const result=unwrap(await request.post(`/api/detection/reports/${id}/events/${event.eventId}/retry`,payload,{headers}));if(generation!==detailGeneration)return;events.value=result||[]
    if(generation===detailGeneration){audits.value=unwrap(await request.get(`/api/detection/reports/${id}/audit`))||[];ElMessage.success('已安排重新发送')}
  }catch(e){if(generation===detailGeneration){await loadEvents(id);eventsError.value=message(e)}}finally{busy.value=false}
}
function openTransition(action) { transition.value = action; transitionVisible.value = true }
async function runCommand(action) {
  if (busy.value || !detail.value) return
  busy.value = true; detailError.value = ''
  try { const id = detail.value.reportId; const saved = unwrap(await request.post(`/api/detection/reports/${id}/${action}`, withId(`${action}:${id}`, { expectedVersion: detail.value.version }), { headers })); transitionVisible.value = false; await load(); await openDetail(saved.reportId); ElMessage.success('报告状态已更新') }
  catch (e) { transitionVisible.value = false; detailError.value = message(e) }
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
.source-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }.source-grid div { display: flex; flex-direction: column; gap: 6px; }
.source-grid span, .muted { font-size: 13px; color: #64748b; }.source-grid strong { font-weight: 500; overflow-wrap: anywhere; }
.narrative { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }.detail-actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0; }
.approval-preview { border: 1px solid #bfdbfe; padding: 16px; border-radius: 12px; background: #f8fbff; }
.el-button { transition: transform 160ms ease; }.el-button:active { transform: scale(.98); }
:global(.report-scroll-dialog .el-dialog__body) { max-height: calc(75dvh - 140px); overflow-y: auto; overscroll-behavior: contain; }
@media (prefers-reduced-motion: reduce) { .el-button { transition: none; }.el-button:active { transform: none; } }
</style>
