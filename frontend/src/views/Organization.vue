<template>
  <div class="page-shell organization-page">
    <section class="page-hero">
      <div>
        <span class="page-hero-label">Organization</span>
        <h1 class="page-hero-title">账号与组织</h1>
        <p class="page-hero-text">核对个人员工身份，主管可维护账号关联和部门。</p>
      </div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </section>

    <section class="toolbar-panel" aria-label="我的身份" v-loading="loading">
      <h2>我的身份</h2>
      <div v-if="mine" class="identity-grid">
        <div><span>登录账号</span><strong>{{ mine.username }}</strong></div>
        <div><span>系统角色</span><strong>{{ roleLabel(mine.role) }}</strong></div>
        <div><span>员工</span><strong>{{ mine.employeeName ? `${mine.employeeName} / ${mine.employeeNumber}` : '尚未关联，请联系主管' }}</strong></div>
        <div><span>部门 / 班组</span><strong>{{ mine.departmentName || '尚未关联' }}</strong></div>
        <div><span>员工状态</span><strong>{{ statusLabel(mine.employeeStatus) }}</strong></div>
        <div><span>业务数据范围</span><strong>{{ mine.dataScope === 'SINGLE_ENTERPRISE' ? '全企业' : '本人及分派任务' }}</strong></div>
      </div>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    </section>

    <template v-if="isSupervisor">
      <section class="toolbar-panel">
        <div class="section-heading"><h2>部门 / 班组</h2><el-button type="primary" @click="departmentDialog = true">新增部门</el-button></div>
        <div class="department-tags"><el-tag v-for="d in departments" :key="d.id" effect="plain">{{ d.name }}</el-tag></div>
      </section>
      <section class="table-panel">
        <div class="account-toolbar">
          <h2>账号员工关联</h2>
          <el-input v-model="keyword" placeholder="查找登录账号" clearable @keyup.enter="search" />
          <el-button @click="search">查询</el-button>
        </div>
        <el-table :data="accounts" v-loading="loading" row-key="userId">
          <el-table-column prop="username" label="登录账号" min-width="160" />
          <el-table-column label="角色" min-width="100"><template #default="{ row }">{{ roleLabel(row.role) }}</template></el-table-column>
          <el-table-column label="员工" min-width="170"><template #default="{ row }">{{ row.employeeName || '未关联' }}<div class="muted">{{ row.employeeNumber }}</div></template></el-table-column>
          <el-table-column label="部门" min-width="140"><template #default="{ row }">{{ row.departmentName || '未关联' }}</template></el-table-column>
          <el-table-column label="员工状态" min-width="100"><template #default="{ row }">{{ statusLabel(row.employeeStatus) }}</template></el-table-column>
          <el-table-column label="操作" min-width="220"><template #default="{ row }">
            <el-button size="small" type="primary" @click="openBinding(row)">关联员工</el-button>
            <el-button size="small" @click="openAudit(row)">变更记录</el-button>
          </template></el-table-column>
        </el-table>
        <div class="page-footer"><el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load" /></div>
      </section>
    </template>

    <el-dialog v-model="bindingDialog" title="关联员工" width="min(540px, 94vw)" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
      <el-form v-if="selectedAccount" label-position="top">
        <el-form-item label="登录账号"><strong>{{ selectedAccount.username }} · {{ roleLabel(selectedAccount.role) }}</strong></el-form-item>
        <el-form-item label="关联员工">
          <el-select v-model="selectedEmployee" filterable remote :remote-method="findEmployees" :loading="employeeLoading" clearable placeholder="输入姓名或从在岗员工中选择" style="width:100%" :disabled="saving">
            <el-option v-for="e in employeeOptions" :key="e.id" :value="e.id" :label="`${e.name} / ${e.employeeNumber} / ${e.department}`" />
          </el-select>
        </el-form-item>
        <p class="muted">清空员工后保存可解除关联。一个员工只能关联一个账号，账号角色和任务归属按原规则生效。</p>
        <el-alert v-if="bindingError" :title="bindingError" type="error" :closable="false" show-icon />
      </el-form>
      <template #footer><el-button :disabled="saving" @click="bindingDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveBinding">保存关联</el-button></template>
    </el-dialog>
    <el-dialog v-model="departmentDialog" title="新增部门 / 班组" width="min(480px, 94vw)" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
      <el-input v-model="departmentName" placeholder="部门 / 班组名称" maxlength="100" :disabled="saving" />
      <p class="muted">创建后可在人员资料中选择该部门。</p>
      <template #footer><el-button :disabled="saving" @click="departmentDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="createDepartment">创建部门</el-button></template>
    </el-dialog>
    <el-dialog v-model="auditDialog" title="账号关联变更记录" width="min(720px, 94vw)">
      <p class="muted">{{ auditUsername }} · 最近 50 次变更</p>
      <el-table :data="auditRows" v-loading="auditLoading">
        <el-table-column label="操作" min-width="80"><template #default="{ row }">{{ ({ BIND: '关联', UNBIND: '解除', REBIND: '更换' })[row.action] || row.action }}</template></el-table-column>
        <el-table-column prop="actorUsername" label="操作账号" min-width="130" />
        <el-table-column label="员工 ID 变更" min-width="130"><template #default="{ row }">{{ row.beforeEmployeeId || '无' }} → {{ row.afterEmployeeId || '无' }}</template></el-table-column>
        <el-table-column prop="bindingVersion" label="版本" width="65" />
        <el-table-column prop="createdAt" label="时间" min-width="180" />
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../api/request'
import { useUserStore } from '../stores/user'

const userStore = useUserStore()
const mine = ref(null), accounts = ref([]), departments = ref([]), total = ref(0), page = ref(1), keyword = ref('')
const loading = ref(false), error = ref(''), saving = ref(false)
const isSupervisor = computed(() => mine.value?.role === 'SUPERVISOR')
const bindingDialog = ref(false), selectedAccount = ref(null), selectedEmployee = ref(null), bindingError = ref('')
const employeeOptions = ref([]), employeeLoading = ref(false)
const departmentDialog = ref(false), departmentName = ref('')
const auditDialog = ref(false), auditRows = ref([]), auditLoading = ref(false), auditUsername = ref('')
const headers = { 'X-Organization-Action': 'update' }
let generation = 0, employeeGeneration = 0, auditGeneration = 0
const roleLabel = role => role === 'SUPERVISOR' ? '主管' : '员工'
const statusLabel = status => ({ ACTIVE: '在岗', VACATION: '休假', RESIGNED: '离职' })[status] || '未关联'
function unwrap(response) {
  if (response.data?.code !== 200) throw new Error(response.data?.message || '请求失败')
  return response.data.data
}
const message = err => err.response?.data?.message || err.message || '请求失败，请重试'
async function load() {
  const current = ++generation
  loading.value = true; error.value = ''; accounts.value = []
  try {
    const identity = unwrap(await request.get('/api/organization/me'))
    if (current !== generation) return
    mine.value = identity; userStore.identity = identity
    if (identity.role === 'SUPERVISOR') {
      const [staff, depts] = await Promise.all([
        request.get('/api/organization/accounts', { params: { page: page.value, size: 20, keyword: keyword.value || undefined } }),
        request.get('/api/organization/departments')
      ])
      if (current !== generation) return
      const data = unwrap(staff); accounts.value = data.records || []; total.value = data.total || 0
      departments.value = unwrap(depts) || []
    }
  } catch (err) { if (current === generation) error.value = message(err) }
  finally { if (current === generation) loading.value = false }
}
function search() { page.value = 1; load() }
async function findEmployees(name = '') {
  const current = ++employeeGeneration
  employeeLoading.value = true
  try {
    const data = unwrap(await request.get('/api/employees', { params: { page: 1, size: 100, status: 'ACTIVE', name: name || undefined } }))
    if (current === employeeGeneration) {
      const selected = employeeOptions.value.find(e => e.id === selectedEmployee.value)
      const options = data.records || []
      employeeOptions.value = selected && !options.some(e => e.id === selected.id) ? [selected, ...options] : options
    }
  } catch (err) { if (current === employeeGeneration) ElMessage.error(message(err)) }
  finally { if (current === employeeGeneration) employeeLoading.value = false }
}
function openBinding(row) {
  selectedAccount.value = { ...row }; selectedEmployee.value = row.employeeId || null
  employeeOptions.value = row.employeeId ? [{ id: row.employeeId, name: row.employeeName, employeeNumber: row.employeeNumber, department: row.departmentName }] : []
  bindingError.value = ''; bindingDialog.value = true; findEmployees()
}
async function saveBinding() {
  if (saving.value || !selectedAccount.value) return
  saving.value = true; bindingError.value = ''
  try {
    unwrap(await request.put(`/api/organization/accounts/${selectedAccount.value.userId}/employee`, {
      employeeId: selectedEmployee.value || null, version: selectedAccount.value.bindingVersion
    }, { headers }))
    bindingDialog.value = false; ElMessage.success('账号关联已保存'); await load()
  } catch (err) { bindingError.value = message(err) }
  finally { saving.value = false }
}
async function createDepartment() {
  if (saving.value) return
  if (!departmentName.value.trim()) return ElMessage.warning('请输入部门名称')
  saving.value = true
  try {
    unwrap(await request.post('/api/organization/departments', { name: departmentName.value.trim() }, { headers }))
    departmentDialog.value = false; departmentName.value = ''; ElMessage.success('部门已创建'); await load()
  } catch (err) { ElMessage.error(message(err)) }
  finally { saving.value = false }
}
async function openAudit(row) {
  const current = ++auditGeneration
  auditUsername.value = row.username; auditRows.value = []; auditDialog.value = true; auditLoading.value = true
  try {
    const data = unwrap(await request.get(`/api/organization/accounts/${row.userId}/audit`))
    if (current === auditGeneration) auditRows.value = data || []
  } catch (err) { if (current === auditGeneration) ElMessage.error(message(err)) }
  finally { if (current === auditGeneration) auditLoading.value = false }
}
onMounted(load)
</script>

<style scoped>
.organization-page { gap: 18px; }
h2 { margin: 0 0 16px; font-size: 18px; color: #0f172a; }
.identity-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; }
.identity-grid div { display: flex; flex-direction: column; gap: 8px; }
.identity-grid span, .muted { color: #64748b; font-size: 13px; }
.identity-grid strong { color: #0f172a; overflow-wrap: anywhere; }
.section-heading, .account-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.section-heading h2, .account-toolbar h2 { margin: 0; margin-right: auto; }
.account-toolbar .el-input { width: 220px; }
.department-tags { display: flex; gap: 8px; flex-wrap: wrap; }
.el-button { transition: transform 160ms ease; }
.el-button:active { transform: scale(.98); }
@media (prefers-reduced-motion: reduce) { .el-button { transition: none; } .el-button:active { transform: none; } }
</style>
