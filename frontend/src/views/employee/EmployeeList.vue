<template>
  <div class="page-shell employee-page">
    <PageHero title="人员管理" icon="User" description="按岗位、部门和在岗状态查找人员，核对业务登记资料与设备分配。"><template #actions><el-button v-if="isSupervisor" type="primary" :disabled="writeBusy" @click="createEmployee"><AppIcon name="Plus" :size="16" />新增人员</el-button></template></PageHero>

    <!-- 独立登记统计，不随下方列表筛选变化 -->
    <section class="stats-bar" :aria-busy="statsLoading">
      <div class="stats-bar-item">
        <div class="stats-bar-icon primary">
          <AppIcon name="User" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ statsTotal ?? '—' }}</div>
          <div class="stats-bar-label">人员总数</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon success">
          <AppIcon name="CircleCheck" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ statsActive ?? '—' }}</div>
          <div class="stats-bar-label">在岗</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon warning">
          <AppIcon name="Clock" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ statsVacation ?? '—' }}</div>
          <div class="stats-bar-label">休假</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon slate">
          <AppIcon name="User" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ statsResigned ?? '—' }}</div>
          <div class="stats-bar-label">离职</div>
        </div>
      </div>
    </section>

    <div v-if="statsError" class="statistics-notice" role="alert"><AppIcon name="Warning" :size="17" /><span>{{ statsError }}</span><el-button size="small" :loading="statsLoading" @click="fetchEmployeeStats">重新读取统计</el-button></div>

    <p class="management-scope-note"><AppIcon name="User" :size="15" />上方为独立人员登记统计，不随列表筛选变化；业务岗位、登录账号与操作权限分别维护。</p>
    <form class="toolbar-panel management-filter-form" @submit.prevent="searchEmployees">
      <label for="employee-name-query">姓名<el-input id="employee-name-query" v-model="filters.name" placeholder="输入姓名" clearable /></label>
      <label for="employee-number-query">员工编号<el-input id="employee-number-query" v-model="filters.employeeNumber" placeholder="输入员工编号" clearable /></label>
      <label for="employee-contact-query">联系方式<el-input id="employee-contact-query" v-model="filters.contact" placeholder="输入联系方式" clearable /></label>
      <label for="employee-department-query">部门 / 班组<el-input id="employee-department-query" v-model="filters.department" placeholder="输入部门或班组" clearable /></label>
      <label for="employee-type-query">业务岗位类型<el-select id="employee-type-query" v-model="filters.employeeType" placeholder="全部类型" clearable><el-option v-for="item in employeeTypeOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
      <label for="employee-status-query">在岗状态<el-select id="employee-status-query" v-model="filters.status" placeholder="全部状态" clearable><el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
      <div class="management-filter-actions"><el-button type="primary" native-type="submit" :loading="loading"><AppIcon name="Search" :size="15" />查询</el-button><el-button @click="resetFilters"><AppIcon name="Refresh" :size="15" />重置</el-button></div>
    </form>
    <p v-if="writeBusy" class="management-write-progress" role="status"><AppIcon name="Connection" :size="16" />正在等待删除操作回执，请稍候</p>
    <el-alert v-if="mutationNotice" :title="mutationNotice" :type="mutationUncertain ? 'warning' : mutationFailed ? 'error' : 'info'" show-icon :closable="false" />
    <section class="table-panel management-list-panel">
      <div class="collection-heading"><h2><AppIcon name="User" :size="18" />人员记录</h2><span>{{ loading ? '正在读取…' : listError ? '本次读取失败' : total===null ? '总数尚未核对' : `共 ${total} 条` }}</span><el-button size="small" :loading="loading" @click="fetchEmployees"><AppIcon name="Refresh" :size="14" />刷新已读范围</el-button></div>
      <p v-if="listLoaded" class="management-applied-query">已读取：{{ appliedDescription }} · 第 {{ pagination.current }} 页</p>
      <p v-if="filtersDirty && employees.length" class="management-query-note" role="status">条件已修改，当前保留已查询范围；点击查询更新。刷新与翻页不会采用未提交条件。</p>
      <el-alert v-if="listError && employees.length" :title="listError+'；下方保留已读取记录，请重新核对。'" type="error" show-icon :closable="false" />
      <div v-if="listError && employees.length" class="management-retry"><el-button size="small" :loading="loading" @click="retryEmployees">重读上次查询</el-button></div>
      <TableReadHint v-if="employees.length" />
      <el-table :scrollbar-tabindex="0" role="region" aria-label="人员记录" :data="employees" row-key="id" v-loading="loading">
        <template #empty><CollectionEmptyState :loading="loading" :error="listError" :filtered="listLoaded ? Object.keys(appliedFilters).length>0 : hasFilters" empty-title="暂无人员记录" :empty-description="isSupervisor ? '可从新增人员登记业务人员，或调整筛选条件。' : '可调整筛选条件，或联系主管核对人员登记。'" @retry="retryEmployees" @reset="resetFilters" /></template>
        <el-table-column label="姓名与员工编号" min-width="220"><template #default="{row}"><div class="management-row-identity"><button type="button" @click="viewEmployee(row.id)">{{ row.name || '姓名未记录' }}</button><span>员工编号 {{ row.employeeNumber || '未记录' }}</span><small>性别 {{ row.gender || '未记录' }}</small></div></template></el-table-column>
        <el-table-column label="岗位与部门" min-width="195"><template #default="{row}"><div class="management-row-identity"><strong>{{ getEmployeeTypeName(row.employeeType) }}</strong><span>{{ row.department || '部门 / 班组未记录' }}</span></div></template></el-table-column>
        <el-table-column label="在岗状态与入职日期" min-width="170"><template #default="{row}"><div class="management-row-status"><StatusBadge domain="employee" :code="row.status" :label="getStatusName(row.status)" /><span>入职 {{ row.hireDate || '日期未记录' }}</span></div></template></el-table-column>
        <el-table-column label="联系方式" min-width="155"><template #default="{row}"><span class="management-row-contact">{{ row.contact || '未记录' }}</span></template></el-table-column>
        <el-table-column label="操作" min-width="235"><template #default="{row}"><div class="management-row-actions"><el-button size="small" @click="viewEmployee(row.id)"><AppIcon name="Search" :size="14" />详情</el-button><el-button v-if="isSupervisor" size="small" :disabled="writeBusy" @click="assignDevices(row.id)"><AppIcon name="Monitor" :size="14" />分配设备</el-button><details v-if="isSupervisor" class="management-more"><summary>更多<AppIcon name="ArrowDown" :size="13" /></summary><div><el-button size="small" :disabled="writeBusy" @click="editEmployee(row.id)"><AppIcon name="Edit" :size="14" />编辑人员</el-button><el-popconfirm :title="`确认删除人员 ${row.name || row.employeeNumber || row.id}？`" @confirm="deleteEmployee(row.id)"><template #reference><el-button size="small" type="danger" plain :disabled="writeBusy || unconfirmedDeletes.has(String(row.id))"><AppIcon name="Delete" :size="14" />删除人员</el-button></template></el-popconfirm></div></details><StatusBadge v-if="unconfirmedDeletes.has(String(row.id))" domain="apiReceipt" code="UNKNOWN" label="删除待核对" /></div></template></el-table-column>
      </el-table>
      <div v-if="total!==null" class="page-footer"><el-pagination :current-page="pagination.current" :page-size="pagination.size" :page-sizes="[10,20,30,50]" :pager-count="7" layout="total, sizes, prev, pager, next, jumper" :total="total" :disabled="loading || !!listError" @size-change="handleSizeChange" @current-change="handleCurrentChange" /></div>
    </section>
    <EmployeeDeviceAssignment ref="assignmentPanel" @changed="fetchEmployees" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'


import request from '../../api/request'
import { useUserStore } from '../../stores/user'
import CollectionEmptyState from '../../components/CollectionEmptyState.vue'
import EmployeeDeviceAssignment from '../../components/EmployeeDeviceAssignment.vue'
import { knownCount } from '../../utils/countPresentation'
import { useManagedList } from '../../composables/useManagedList'

const router = useRouter()
const userStore = useUserStore()
const isSupervisor = computed(() => userStore.role === 'SUPERVISOR')
const { records:employees, total, loading, error:listError, loaded:listLoaded, filters, pagination, hasFilters, filtersDirty, appliedFilters, search:searchEmployees, reset:resetFilters, refresh:fetchEmployees, retry:retryEmployees, changePage:handleCurrentChange, changeSize:handleSizeChange } = useManagedList('/api/employees',['name','employeeNumber','contact','department','employeeType','status'])
const filterLabels = {name:'姓名',employeeNumber:'员工编号',contact:'联系方式',department:'部门 / 班组',employeeType:'人员类型',status:'状态'}
const appliedDescription = computed(() => Object.entries(appliedFilters.value).map(([key,value]) => `${filterLabels[key]}：${key==='status'?getStatusName(value):key==='employeeType'?getEmployeeTypeName(value):value}`).join(' · ') || '全部条件')
const writeBusy = ref(false), mutationNotice = ref(''), mutationUncertain = ref(false), mutationFailed = ref(false), unconfirmedDeletes = ref(new Set())
let pageActive = true, statsVersion = 0
onBeforeUnmount(() => { pageActive=false;statsVersion++ })

// 统计数据 — 单独请求全量数据
const statsLoading = ref(true)
const statsError = ref('')
const statsTotal = ref(null)
const statsActive = ref(null)
const statsVacation = ref(null)
const statsResigned = ref(null)

async function fetchEmployeeStats() {
  if (!pageActive) return
  const version = ++statsVersion
  statsLoading.value = true
  try {
    const response = await request.get('/api/employees/stats')
    if (!pageActive || version !== statsVersion) return
    if (response.data.code === 200) {
      const stats = response.data.data || {}
      statsTotal.value = knownCount(stats.total)
      statsActive.value = knownCount(stats.active)
      statsVacation.value = knownCount(stats.vacation)
      statsResigned.value = knownCount(stats.resigned)
      statsError.value = [statsTotal,statsActive,statsVacation,statsResigned].some(item => item.value === null) ? '人员统计返回不完整，缺失值显示 —，请重新读取核对。' : ''
    } else {const failure=new Error('人员统计请求未成功');failure.httpStatus=response.data?.code;throw failure}
  } catch (e) {
    if (!pageActive || version !== statsVersion) return
    if ([401,403].includes(e.response?.status || e.httpStatus)) {statsTotal.value=null;statsActive.value=null;statsVacation.value=null;statsResigned.value=null}
    statsError.value = '人员统计暂不可核对，保留上次已知数值，缺失值显示 —。'
  } finally {
    if (pageActive && version === statsVersion) statsLoading.value = false
  }
}

const assignmentPanel = ref(null)

const employeeTypeOptions = [
  { value: 'DETECTION', label: '门把手检测人员' },
  { value: 'COLLECTION', label: '门把手图片采集人员' },
  { value: 'MAINTENANCE', label: '设备维护人员' }
]

const statusOptions = [
  { value: 'ACTIVE', label: '在岗' },
  { value: 'RESIGNED', label: '离职' },
  { value: 'VACATION', label: '休假' }
]

const getEmployeeTypeName = (type) => {
  const typeMap = {
    DETECTION: '门把手检测人员',
    COLLECTION: '门把手图片采集人员',
    MAINTENANCE: '设备维护人员'
  }
  return typeMap[type] || type || '类型未记录'
}

const getStatusName = (status) => {
  const statusMap = {
    ACTIVE: '在岗',
    RESIGNED: '离职',
    VACATION: '休假'
  }
  return statusMap[status] || status
}

const createEmployee = () => {
  router.push({ name: 'employeeAdd' })
}

const editEmployee = (id) => {
  router.push({ name: 'employeeEdit', params: { id } })
}

const viewEmployee = (id) => {
  router.push({ name: 'employeeDetail', params: { id } })
}

const deleteEmployee = async (id) => {
  if (!isSupervisor.value || writeBusy.value || unconfirmedDeletes.value.has(String(id))) return
  writeBusy.value=true;mutationNotice.value='';mutationUncertain.value=false;mutationFailed.value=false
  try {
    const response = await request.delete(`/api/employees/${id}`)
    if (!pageActive) return
    if (response.data?.code === 200 && response.data.data===true) {
      mutationNotice.value='已收到人员删除成功回执，请核对刷新后的列表与登记统计。'
      await Promise.allSettled([fetchEmployees(),fetchEmployeeStats()])
    } else {
      mutationUncertain.value=response.data?.code==null || response.data.code>=500 || response.data.code===200 && response.data.data!==false
      mutationFailed.value=!mutationUncertain.value
      if(mutationUncertain.value)unconfirmedDeletes.value=new Set([...unconfirmedDeletes.value,String(id)])
      mutationNotice.value=mutationUncertain.value?'人员删除结果待核对，请重新读取列表或详情；当前页面不会重复发送该人员的删除请求。':response.data?.message || '接口未确认人员删除成功，请核对当前状态。'
    }
  } catch (error) {
    if (!pageActive) return
    mutationUncertain.value=!error.response?.status || error.response.status>=500
    mutationFailed.value=!mutationUncertain.value
    if(mutationUncertain.value)unconfirmedDeletes.value=new Set([...unconfirmedDeletes.value,String(id)])
    mutationNotice.value=mutationUncertain.value?'人员删除结果待核对，请重新读取列表或详情；不会自动重发。':error.response?.data?.message || '人员删除请求未成功，请核对权限与设备分配。'
  } finally {if(pageActive)writeBusy.value=false}
}

const assignDevices = employeeId => assignmentPanel.value?.openFor(employeeId)

onMounted(() => {
  fetchEmployees()
  fetchEmployeeStats()
})
</script>

<style scoped>.employee-page { gap:18px; }</style>
