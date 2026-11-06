<template>
  <div class="operation-page llm-management">
    <PageHero title="LLM模型管理" icon="Cpu" description="查看当前模型与个人 token 额度，向企业主管申请追加额度，并跟进处理结果。">
      <template #actions>
        <el-button :loading="refreshing" :disabled="busy" @click="refresh"><AppIcon name="Refresh" :size="15" />刷新</el-button>
        <el-button type="primary" :disabled="busy || !applyModels.length" @click="openApply()"><AppIcon name="Plus" :size="15" />申请额度</el-button>
      </template>
    </PageHero>

    <section v-if="supervisor" class="operation-toolbar llm-admin" aria-label="主管管理入口">
      <span><AppIcon name="Operation" :size="16" />主管管理</span>
      <router-link to="/agent/model-budgets">企业额度与供应商核对<AppIcon name="ArrowRight" :size="14" /></router-link>
      <router-link to="/agent/model-config">模型连接与备用配置<AppIcon name="ArrowRight" :size="14" /></router-link>
    </section>

    <el-alert v-if="notice" :title="notice" type="success" :closable="true" @close="notice = ''" />
    <section v-if="command && !dialogVisible" class="operation-toolbar" role="status">
      <span>上次操作尚未确认结果，请使用原请求编号继续核对</span>
      <el-button :disabled="busy" @click="dialogVisible = true">继续处理</el-button>
    </section>

    <section aria-labelledby="llm-models-title" :aria-busy="modelsLoading">
      <div class="llm-section-heading">
        <div><h2 id="llm-models-title">模型与个人额度</h2><p>额度单位为 token · 预留用于进行中的调用，完成后按实际用量结算</p></div>
        <el-switch v-model="showUnconfigured" active-text="显示未配置模型" />
      </div>
      <p class="operation-muted llm-quota-note">个人未设置额度时保留已有使用权限；设置额度后按个人额度扣减。模型连接、企业额度与有效期仍决定实际能否调用。</p>
      <p v-if="modelsLoading && models.length" class="operation-muted" role="status">正在刷新，下方为上次读取的额度</p>
      <el-alert v-if="modelsError && models.length" :title="modelsError + '；下方为上次读取的额度，暂不能发起新申请'" type="warning" :closable="false" />
      <TransitionGroup name="quota-record" tag="div" class="operation-cards llm-model-cards">
        <article v-for="model in visibleModels" :key="model.modelId" class="operation-card llm-model-card">
          <div class="llm-model-heading"><span class="llm-model-icon"><AppIcon name="Cpu" :size="19" /></span><div><h3>{{ model.model || model.modelId }}</h3><p>{{ model.provider || '接入方未记录' }} · {{ model.modelId }}</p></div></div>
          <el-tag :type="quotaStatus(model).tone">{{ quotaStatus(model).label }}</el-tag>
          <el-alert v-if="enterpriseQuotaBlock(model)" class="llm-enterprise-block" :title="enterpriseQuotaBlock(model)" type="warning" :closable="false" />
          <div class="operation-metrics">
            <div><strong>{{ personalQuotaValue(model, 'totalTokens') }}</strong><span>个人总额度</span></div>
            <div><strong>{{ personalQuotaValue(model, 'availableTokens') }}</strong><span>个人可用额度</span></div>
            <div><strong>{{ personalQuotaValue(model, 'reservedTokens') }}</strong><span>个人额度已预留</span></div>
            <div><strong>{{ personalQuotaValue(model, 'spentTokens') }}</strong><span>个人额度已使用</span></div>
          </div>
          <p v-if="model.hasPersonalQuota === false">尚未设置个人额度，继续保留原有模型使用权限；此处个人额度计数不代表历史模型总用量。</p>
          <p v-else-if="model.hasPersonalQuota === true && model.totalTokens === null">未设个人额度上限，无需申请追加个人额度。</p>
          <p v-if="quotaNumber(model.availableTokens) !== null && Number(model.availableTokens) < 0">实际消耗超过可用额度，已完整计入用量；追加额度后仍需满足调用所需的预留量。</p>
          <p v-if="model.hasPersonalQuota === true">个人额度到期时间 {{ model.expiresAt === null ? '未设置' : utcDisplay(model.expiresAt) }} · 北京时间</p>
          <div class="operation-actions"><el-button type="primary" plain :disabled="busy || modelsLoading || !!modelsError || !canApplyForQuota(model)" @click="openApply(model)">申请追加额度</el-button></div>
        </article>
      </TransitionGroup>
      <CollectionEmptyState v-if="!visibleModels.length" :loading="modelsLoading" :error="modelsError" :empty-title="models.length ? '当前没有已配置的模型' : '当前模型目录为空'" empty-description="主管配置模型连接后，可在这里查看个人额度并申请使用。" @retry="loadModels" />
    </section>

    <section class="operation-panel llm-applications" aria-labelledby="llm-applications-title">
      <div class="llm-section-heading"><div><h2 id="llm-applications-title">额度申请</h2><p>批准后追加个人额度，保留已用与预留记录；不变更模型权限或企业总额度</p></div></div>
      <el-tabs v-model="listScope" @tab-change="changeListScope">
        <el-tab-pane label="我的申请" name="mine" />
        <el-tab-pane v-if="supervisor" label="企业审批" name="team" />
      </el-tabs>
      <div class="llm-list-toolbar"><p class="operation-muted">{{ listScope === 'team' ? '企业申请按提交时间倒序展示，待审批记录可批准或拒绝' : '查看本人申请；待审批时可以取消' }}</p><div class="llm-list-filters"><el-select v-model="activeList.status" aria-label="申请状态" :disabled="busy" @change="changeStatus"><el-option label="全部状态" value="" /><el-option v-for="(label, status) in quotaApplicationLabels" :key="status" :label="label" :value="status" /></el-select><el-button :loading="activeList.loading" :disabled="busy" @click="loadApplications(listScope)">刷新申请</el-button></div></div>
      <el-alert v-if="activeList.error" :title="activeList.error" type="error" :closable="false" />
      <TransitionGroup name="quota-record" tag="div" class="llm-application-list" :aria-busy="activeList.loading">
        <article v-for="application in activeList.items" :key="application.id" class="operation-chunk llm-application">
          <div class="llm-application-heading"><h3>{{ application.modelId }}</h3><el-tag :type="quotaApplicationTones[application.status]">{{ quotaApplicationLabels[application.status] }}</el-tag></div>
          <p class="llm-requested"><strong>+{{ quotaCount(application.requestedTokens) }}</strong> token</p>
          <p v-if="listScope === 'team'" class="operation-muted">申请人账号编号 {{ application.applicantUserId ?? '未记录' }}</p>
          <p class="llm-reason">{{ application.reason || '申请说明未记录' }}</p>
          <p v-if="application.decisionReason" class="llm-reason">审批说明：{{ application.decisionReason }}</p>
          <p class="operation-muted">提交 {{ utcDisplay(application.createdAt) }}<template v-if="application.finishedAt"> · 处理 {{ utcDisplay(application.finishedAt) }}</template> · 北京时间</p>
          <div v-if="application.status === 'PENDING'" class="operation-actions">
            <template v-if="listScope === 'team' && supervisor">
              <el-button type="primary" :disabled="busy || activeList.loading || !!activeList.error" @click="openDecision(application, 'APPROVE')">批准</el-button>
              <el-button :disabled="busy || activeList.loading || !!activeList.error" @click="openDecision(application, 'REJECT')">拒绝</el-button>
            </template>
            <el-button v-if="listScope === 'mine'" :disabled="busy || activeList.loading || !!activeList.error" @click="openCancel(application)">取消申请</el-button>
          </div>
        </article>
      </TransitionGroup>
      <CollectionEmptyState v-if="!activeList.items.length" :loading="activeList.loading" :error="activeList.error" :empty-title="listScope === 'mine' ? '还没有额度申请' : '暂无企业额度申请'" :empty-description="listScope === 'mine' ? '从上方模型选择申请，提交后由本企业主管审批。' : '成员提交后会在这里显示申请与处理状态。'" @retry="loadApplications(listScope)" />
      <el-button v-if="activeList.nextCursor !== null" class="llm-load-more" :loading="activeList.loading" :disabled="busy" @click="loadApplications(listScope, true)">加载更早的申请</el-button>
    </section>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="min(560px,94vw)" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :before-close="closeDialog">
      <form class="operation-form" @submit.prevent="submitCommand">
        <template v-if="dialogMode === 'apply'">
          <label>申请模型<el-select v-model="draft.modelId" :disabled="locked" placeholder="选择已配置的模型"><el-option v-for="model in applyModels" :key="model.modelId" :label="(model.model || model.modelId) + ' · ' + model.modelId" :value="model.modelId" /></el-select></label>
          <label>追加额度 · token<el-input-number v-model="draft.requestedTokens" :min="1" :max="1000000000000" :precision="0" :disabled="locked" /></label>
          <p class="operation-muted">申请的是新增个人额度。批准后保留已用与预留记录，模型使用仍需符合连接与企业额度条件。</p>
        </template>
        <template v-else>
          <p class="llm-command-summary">{{ selectedApplication?.modelId }} · 申请追加 {{ quotaCount(selectedApplication?.requestedTokens) }} token</p>
          <p class="llm-reason">{{ selectedApplication?.reason }}</p>
          <p v-if="dialogMode === 'cancel'" class="operation-muted">确认取消这条尚未审批的申请？取消后如需额度，可重新提交新申请。</p>
          <p v-else class="operation-muted">{{ draft.decision === 'APPROVE' ? '批准后追加该成员的个人额度，已有消耗与预留保持不变。' : '拒绝后保留申请与审批记录，成员可重新申请。' }}</p>
        </template>
        <label v-if="dialogMode !== 'cancel'">{{ dialogMode === 'apply' ? '申请说明' : '审批说明' }}<el-input v-model="draft.reason" type="textarea" :rows="4" maxlength="500" show-word-limit :disabled="locked" :placeholder="dialogMode === 'apply' ? '说明使用场景和预计用量' : '填写本次审批依据'" /></label>
        <el-alert v-if="formError" :title="formError" type="error" :closable="false" />
        <p v-if="command" class="operation-muted">本次请求编号 {{ command.requestId }}。结果未确认时重试沿用该编号与原内容，避免重复追加额度。</p>
        <div class="operation-actions"><el-button :disabled="busy" @click="dialogVisible = false">{{ command ? '稍后处理' : '返回' }}</el-button><el-button type="primary" native-type="submit" :loading="busy" :disabled="!canSubmit">{{ command ? '重试原操作' : dialogMode === 'apply' ? '提交申请' : dialogMode === 'cancel' ? '确认取消' : draft.decision === 'APPROVE' ? '确认批准' : '确认拒绝' }}</el-button></div>
      </form>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import request from '../api/request'
import { useUserStore } from '../stores/user'
import { useAccountOperationScope } from '../composables/useAccountOperationScope'
import { operationData, operationError, utcDisplay } from '../utils/qualityOperations'
import { createUiRequestId } from '../utils/requestIdentity'
import { canApplyForQuota, enterpriseQuotaBlock, personalQuotaValue, quotaApplicationLabels, quotaApplicationTones, quotaCount, quotaNumber, quotaStatus, readQuotaApplications, readQuotaModels } from '../utils/modelQuotaPresentation'
import AppIcon from '../components/AppIcon.vue'
import CollectionEmptyState from '../components/CollectionEmptyState.vue'
import '../assets/quality-operations.css'

const user = useUserStore()
const supervisor = computed(() => ['SUPERVISOR', 'ADMIN'].includes(user.role))
const base = '/api/agent/model-quotas', headers = { 'X-Budget-Action': 'update' }
const models = ref([]), modelsLoading = ref(false), modelsError = ref(''), showUnconfigured = ref(false)
const listScope = ref('mine'), busy = ref(false), notice = ref('')
const emptyList = (status = '') => ({ items: [], nextCursor: null, loading: false, error: '', loaded: false, status })
const lists = reactive({ mine: emptyList(), team: emptyList('PENDING') })
const dialogVisible = ref(false), dialogMode = ref('apply'), selectedApplication = ref(null), formError = ref(''), command = ref(null)
const draft = reactive({ modelId: '', requestedTokens: undefined, reason: '', decision: 'APPROVE' })
const scope = useAccountOperationScope(() => {
  models.value = []; modelsLoading.value = false; modelsError.value = ''; listScope.value = 'mine'
  Object.assign(lists, { mine: emptyList(), team: emptyList('PENDING') })
  busy.value = false; notice.value = ''; dialogVisible.value = false; selectedApplication.value = null
  command.value = null; formError.value = ''; Object.assign(draft, { modelId: '', requestedTokens: undefined, reason: '', decision: 'APPROVE' })
})
const modelRead = scope.channel(), listReads = { mine: scope.channel(), team: scope.channel() }
const visibleModels = computed(() => showUnconfigured.value ? models.value : models.value.filter(row => row.configured === true))
const applyModels = computed(() => modelsLoading.value || modelsError.value ? [] : models.value.filter(canApplyForQuota))
const activeList = computed(() => lists[listScope.value])
const refreshing = computed(() => modelsLoading.value || activeList.value.loading)
const locked = computed(() => busy.value || !!command.value)
const dialogTitle = computed(() => dialogMode.value === 'apply' ? '申请个人模型额度' : dialogMode.value === 'cancel' ? '取消额度申请' : draft.decision === 'APPROVE' ? '批准额度申请' : '拒绝额度申请')
const canSubmit = computed(() => {
  if (busy.value) return false
  if (command.value) return true
  if (dialogMode.value === 'cancel') return selectedApplication.value?.status === 'PENDING'
  if (!draft.reason.trim() || draft.reason.length > 500) return false
  return dialogMode.value === 'decision' ? supervisor.value && selectedApplication.value?.status === 'PENDING' : applyModels.value.some(row => row.modelId === draft.modelId) && Number.isSafeInteger(draft.requestedTokens) && draft.requestedTokens > 0 && draft.requestedTokens <= 1000000000000
})

async function loadModels() {
  const token = modelRead.begin(); modelsLoading.value = true; modelsError.value = ''
  try {
    const data = readQuotaModels(operationData(await request.get(base + '/mine', { signal: token.signal })))
    if (modelRead.current(token)) models.value = data
  } catch (error) { if (modelRead.current(token)) modelsError.value = operationError(error, true) }
  finally { if (modelRead.current(token)) modelsLoading.value = false }
}

async function loadApplications(which = 'mine', more = false) {
  if (which !== 'mine' && which !== 'team' || which === 'team' && !supervisor.value) return
  const list = lists[which]
  if (more && (list.loading || list.nextCursor === null)) return
  const token = listReads[which].begin(), before = more ? list.nextCursor : undefined
  list.loading = true; list.error = ''
  try {
    const data = readQuotaApplications(operationData(await request.get(base + '/applications', { params: { scope: which, limit: 20, before, status: list.status || undefined }, signal: token.signal })))
    if (!listReads[which].current(token)) return
    if (more && data.nextCursor !== null && Number(data.nextCursor) >= Number(before)) throw new Error('申请分页游标未推进，请刷新后重新读取')
    list.items = more ? [...list.items, ...data.items.filter(row => !list.items.some(existing => existing.id === row.id))] : data.items
    list.nextCursor = data.nextCursor; list.loaded = true
  } catch (error) { if (listReads[which].current(token)) list.error = operationError(error, true) }
  finally { if (listReads[which].current(token)) list.loading = false }
}

async function refresh() { await Promise.allSettled([loadModels(), loadApplications('mine'), ...(supervisor.value && (listScope.value === 'team' || lists.team.loaded) ? [loadApplications('team')] : [])]) }
function changeListScope(which) { if (!lists[which]?.loaded) loadApplications(which) }
function changeStatus() { activeList.value.items = []; activeList.value.nextCursor = null; loadApplications(listScope.value) }
function reopenPending() { if (!command.value) return false; dialogVisible.value = true; return true }
function openApply(model) {
  if (busy.value || reopenPending()) return
  const selected = model || applyModels.value[0]
  if (!canApplyForQuota(selected)) return
  dialogMode.value = 'apply'; selectedApplication.value = null
  Object.assign(draft, { modelId: selected.modelId, requestedTokens: undefined, reason: '', decision: 'APPROVE' })
  formError.value = ''; dialogVisible.value = true
}
function openDecision(application, decision) {
  if (busy.value || !supervisor.value || reopenPending()) return
  dialogMode.value = 'decision'; selectedApplication.value = { ...application }; draft.reason = ''; draft.decision = decision
  formError.value = ''; dialogVisible.value = true
}
function openCancel(application) {
  if (busy.value || reopenPending()) return
  dialogMode.value = 'cancel'; selectedApplication.value = { ...application }; formError.value = ''; dialogVisible.value = true
}
function closeDialog(done) { if (!busy.value) done() }

async function submitCommand() {
  if (!canSubmit.value) return
  const token = scope.stamp(); busy.value = true; formError.value = ''; notice.value = ''
  try {
    if (!command.value) {
      const requestId = createUiRequestId()
      if (dialogMode.value === 'apply') command.value = { path: '/applications', requestId, body: { modelId: draft.modelId, requestedTokens: draft.requestedTokens, reason: draft.reason.trim(), requestId } }
      else {
        const suffix = dialogMode.value === 'cancel' ? 'cancel' : 'decision'
        const body = { expectedVersion: selectedApplication.value.version, requestId }
        if (suffix === 'decision') Object.assign(body, { decision: draft.decision, reason: draft.reason.trim() })
        command.value = { path: '/applications/' + encodeURIComponent(selectedApplication.value.id) + '/' + suffix, requestId, body }
      }
    }
    const pending = command.value
    const data = operationData(await request.post(base + pending.path, pending.body, { headers }))
    if (!scope.current(token)) return
    // A successful HTTP response without the actual receipt remains unresolved and uses the same key on retry.
    readQuotaApplications({ items: [data], nextCursor: null })
    notice.value = '操作已确认：' + quotaApplicationLabels[data.status] + '。额度与申请状态以下方最新读取结果为准'
    command.value = null; dialogVisible.value = false
    await refresh()
  } catch (error) {
    if (!scope.current(token)) return
    const status = error.response?.status || error.httpStatus
    formError.value = operationError(error)
    if ([400, 403, 404, 409, 422].includes(status)) {
      command.value = null
      if (dialogMode.value !== 'apply' || status === 403) {
        dialogVisible.value = false
        lists[listScope.value].error = formError.value
        await refresh()
        if (scope.current(token)) lists[listScope.value].error = formError.value + '；请核对最新记录后重新操作'
      } else await loadModels()
    } else if (command.value) formError.value += '；结果尚未确认，请使用本次原请求重试'
  } finally { if (scope.current(token)) busy.value = false }
}

onMounted(refresh)
watch(() => JSON.stringify([user.username, user.role, user.identity?.userId, user.isAuthenticated]), () => { if (user.isAuthenticated) refresh() })
</script>

<style scoped>
.llm-section-heading { display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:14px; margin-bottom:18px; }
.llm-section-heading h2 { margin:0; font-size:17px; font-weight:600; color:var(--app-text); }
.llm-section-heading p { margin:7px 0 0; color:var(--app-text-muted); font-size:12px; line-height:1.8; }
.llm-admin { gap:16px 24px; }
.llm-admin > span,.llm-admin a { display:inline-flex; align-items:center; gap:7px; font-size:13px; }
.llm-admin a { color:var(--app-primary); text-decoration:none; }
.llm-admin a:hover { text-decoration:underline; }
.llm-quota-note { margin:0 0 18px; }
.llm-model-cards { position:relative; grid-template-columns:repeat(auto-fill,minmax(min(370px,100%),1fr)); }
.llm-model-heading { display:flex; gap:12px; align-items:flex-start; margin-bottom:16px; }
.llm-model-heading h3 { margin:0; }
.llm-model-heading p { margin:3px 0 0; }
.llm-model-icon { display:grid; place-items:center; flex:none; width:36px; height:36px; border:1px solid var(--app-border); border-radius:9px; color:var(--app-primary); background:var(--app-primary-soft); }
.llm-model-card .operation-metrics strong { font-size:clamp(18px,2.1vw,26px); }
.llm-model-card .operation-actions { margin-top:auto; }
.llm-model-card { display:flex; flex-direction:column; }
.llm-model-card > .el-tag { align-self:flex-start; }
.llm-enterprise-block { margin-top:8px; }
.llm-list-toolbar,.llm-application-heading { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; }
.llm-list-toolbar { margin:0 0 12px; }
.llm-list-toolbar p { margin:0; }
.llm-list-filters { display:flex; gap:10px; flex-wrap:wrap; }
.llm-list-filters .el-select { width:140px; }
.llm-application-list { position:relative; }
.llm-application-heading h3 { margin:0; overflow-wrap:anywhere; }
.llm-requested { margin:12px 0; font-size:12px; color:var(--app-text-muted); }
.llm-requested strong { font-size:21px; color:var(--app-text); font-variant-numeric:tabular-nums; }
.llm-reason { white-space:pre-wrap; overflow-wrap:anywhere; font-size:13px; line-height:1.85; color:var(--app-text-secondary); }
.llm-command-summary { margin:0; font-weight:600; overflow-wrap:anywhere; }
.llm-load-more { margin-top:20px; }
.quota-record-enter-active,.quota-record-leave-active,.quota-record-move { transition:opacity .18s ease,transform .18s ease; }
.quota-record-enter-from,.quota-record-leave-to { opacity:0; transform:translateY(5px); }
.quota-record-leave-active { position:absolute; }
@media(max-width:560px) { .llm-admin { align-items:flex-start; flex-direction:column; } .llm-model-card .operation-metrics strong { font-size:20px; } }
@media(prefers-reduced-motion:reduce) { .quota-record-enter-active,.quota-record-leave-active,.quota-record-move { transition:none; } .quota-record-enter-from,.quota-record-leave-to { transform:none; } }
</style>
