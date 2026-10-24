<template>
  <div class="page-shell device-page">
    <PageHero title="设备管理" icon="Monitor" description="按编号、型号与业务状态查找设备，核对登记使用人及维护记录。"><template #actions><el-button v-if="isSupervisor" type="primary" :disabled="writeBusy" @click="createDevice"><AppIcon name="Plus" :size="16" />新增设备</el-button></template></PageHero>

    <!-- 独立登记统计，不随下方列表筛选变化 -->
    <section class="stats-bar" :aria-busy="statsLoading">
      <div class="stats-bar-item">
        <div class="stats-bar-icon primary">
          <AppIcon name="Monitor" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ statsTotal ?? '—' }}</div>
          <div class="stats-bar-label">设备总数</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon success">
          <AppIcon name="CircleCheck" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ statsInUse ?? '—' }}</div>
          <div class="stats-bar-label">使用中</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon warning">
          <AppIcon name="Warning" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ statsMaintenance ?? '—' }}</div>
          <div class="stats-bar-label">维护中</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon slate">
          <AppIcon name="Monitor" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ statsUnused ?? '—' }}</div>
          <div class="stats-bar-label">未使用</div>
        </div>
      </div>
    </section>

    <div v-if="statsError" class="statistics-notice" role="alert"><AppIcon name="Warning" :size="17" /><span>{{ statsError }}</span><el-button size="small" :loading="statsLoading" @click="fetchDeviceStats">重新读取统计</el-button></div>

    <p class="management-scope-note"><AppIcon name="Monitor" :size="15" />上方为独立登记统计，不随列表筛选变化；“使用中”是业务状态，不代表实时在线心跳。</p>
    <form class="toolbar-panel management-filter-form" @submit.prevent="searchDevices">
      <label for="device-code-query">设备编号<el-input id="device-code-query" v-model="filters.deviceCode" placeholder="输入设备编号" clearable /></label>
      <label for="device-type-query">设备类型<el-select id="device-type-query" v-model="filters.deviceType" placeholder="全部类型" clearable><el-option v-for="item in deviceTypeOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
      <label for="device-model-query">设备型号<el-input id="device-model-query" v-model="filters.modelName" placeholder="输入设备型号" clearable /></label>
      <label for="device-serial-query">序列号<el-input id="device-serial-query" v-model="filters.serialNumber" placeholder="输入序列号" clearable /></label>
      <label for="device-status-query">设备业务状态<el-select id="device-status-query" v-model="filters.status" placeholder="全部状态" clearable><el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
      <div class="management-filter-actions"><el-button type="primary" native-type="submit" :loading="loading"><AppIcon name="Search" :size="15" />查询</el-button><el-button @click="resetFilters"><AppIcon name="Refresh" :size="15" />重置</el-button></div>
    </form>
    <p v-if="writeBusy" class="management-write-progress" role="status"><AppIcon name="Connection" :size="16" />正在等待删除操作回执，请稍候</p>
    <el-alert v-if="mutationNotice" :title="mutationNotice" :type="mutationUncertain ? 'warning' : mutationFailed ? 'error' : 'info'" show-icon :closable="false" />
    <section class="table-panel management-list-panel">
      <div class="collection-heading"><h2><AppIcon name="Monitor" :size="18" />设备记录</h2><span>{{ loading ? '正在读取…' : listError ? '本次读取失败' : total===null ? '总数尚未核对' : `共 ${total} 条` }}</span><el-button size="small" :loading="loading" @click="fetchDevices"><AppIcon name="Refresh" :size="14" />刷新已读范围</el-button></div>
      <p v-if="listLoaded" class="management-applied-query">已读取：{{ appliedDescription }} · 第 {{ pagination.current }} 页</p>
      <p v-if="filtersDirty && devices.length" class="management-query-note" role="status">条件已修改，当前保留已查询范围；点击查询更新。刷新与翻页不会采用未提交条件。</p>
      <el-alert v-if="listError && devices.length" :title="listError+'；下方保留已读取记录，请重新核对。'" type="error" show-icon :closable="false" />
      <div v-if="listError && devices.length" class="management-retry"><el-button size="small" :loading="loading" @click="retryDevices">重读上次查询</el-button></div>
      <TableReadHint v-if="devices.length" />
      <el-table :scrollbar-tabindex="0" role="region" aria-label="设备记录" :data="devices" row-key="id" v-loading="loading">
        <template #empty><CollectionEmptyState :loading="loading" :error="listError" :filtered="listLoaded ? Object.keys(appliedFilters).length>0 : hasFilters" empty-title="暂无设备记录" :empty-description="isSupervisor ? '可从新增设备登记设备，或调整筛选条件。' : '可调整筛选条件，或联系主管核对设备登记。'" @retry="retryDevices" @reset="resetFilters" /></template>
        <el-table-column label="设备与型号" min-width="235"><template #default="{row}"><div class="management-row-identity"><button type="button" @click="viewDevice(row.id)">{{ row.deviceCode || '设备编号未记录' }}</button><span>{{ row.modelName || '型号未记录' }}</span><small>{{ getDeviceTypeName(row.deviceType) }}</small><details><summary>序列号</summary><code>{{ row.serialNumber || '未记录' }}</code></details></div></template></el-table-column>
        <el-table-column label="业务状态与登记使用人" min-width="205"><template #default="{row}"><div class="management-row-status"><StatusBadge domain="device" :code="row.status" :label="getStatusName(row.status)" /><router-link v-if="row.employee?.id" :to="{name:'employeeDetail',params:{id:row.employee.id}}">{{ row.employee.name || row.employee.employeeNumber || '查看登记使用人' }}</router-link><span v-else-if="row.employee">{{ row.employee.name || row.employee.employeeNumber || '使用人资料不完整' }}</span><span v-else>使用人未提供</span><small v-if="row.employee?.employeeNumber">员工编号 {{ row.employee.employeeNumber }}</small></div></template></el-table-column>
        <el-table-column label="最近维护 · UTC+8" min-width="180"><template #default="{row}"><span class="management-row-time">{{ formatDate(row.lastMaintenanceDate) }}</span></template></el-table-column>
        <el-table-column label="操作" min-width="235"><template #default="{row}"><div class="management-row-actions"><el-button size="small" @click="viewDevice(row.id)"><AppIcon name="Search" :size="14" />详情</el-button><el-button size="small" @click="viewDeviceUsageRecords(row)"><AppIcon name="Clock" :size="14" />使用记录</el-button><details v-if="isSupervisor" class="management-more"><summary>更多<AppIcon name="ArrowDown" :size="13" /></summary><div><el-button size="small" :disabled="writeBusy" @click="editDevice(row.id)"><AppIcon name="Edit" :size="14" />编辑设备</el-button><el-popconfirm :title="`确认删除设备 ${row.deviceCode || row.id}？`" @confirm="deleteDevice(row.id)"><template #reference><el-button size="small" type="danger" plain :disabled="writeBusy || unconfirmedDeletes.has(String(row.id))"><AppIcon name="Delete" :size="14" />删除设备</el-button></template></el-popconfirm></div></details><StatusBadge v-if="unconfirmedDeletes.has(String(row.id))" domain="apiReceipt" code="UNKNOWN" label="删除待核对" /></div></template></el-table-column>
      </el-table>
      <div v-if="total!==null" class="page-footer"><el-pagination :current-page="pagination.current" :page-size="pagination.size" :page-sizes="[10,20,30,50]" :pager-count="7" layout="total, sizes, prev, pager, next, jumper" :total="total" :disabled="loading || !!listError" @size-change="handleSizeChange" @current-change="handleCurrentChange" /></div>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import {beijingDateTime} from '@/utils/beijingTime'

import request from '../../api/request'
import { useUserStore } from '../../stores/user'
import CollectionEmptyState from '../../components/CollectionEmptyState.vue'
import { knownCount } from '../../utils/countPresentation'
import { useManagedList } from '../../composables/useManagedList'

const router = useRouter()
const userStore = useUserStore()
const isSupervisor = computed(() => userStore.role === 'SUPERVISOR')
const { records:devices, total, loading, error:listError, loaded:listLoaded, filters, pagination, hasFilters, filtersDirty, appliedFilters, search:searchDevices, reset:resetFilters, refresh:fetchDevices, retry:retryDevices, changePage:handleCurrentChange, changeSize:handleSizeChange } = useManagedList('/api/devices',['deviceCode','deviceType','modelName','serialNumber','status'])
const filterLabels = {deviceCode:'设备编号',deviceType:'设备类型',modelName:'设备型号',serialNumber:'序列号',status:'设备状态'}
const appliedDescription = computed(() => Object.entries(appliedFilters.value).map(([key,value]) => `${filterLabels[key]}：${key==='status'?getStatusName(value):key==='deviceType'?getDeviceTypeName(value):value}`).join(' · ') || '全部条件')
const writeBusy = ref(false), mutationNotice = ref(''), mutationUncertain = ref(false), mutationFailed = ref(false), unconfirmedDeletes = ref(new Set())
let pageActive = true, statsVersion = 0
onBeforeUnmount(() => { pageActive=false;statsVersion++ })

// 统计数据 — 单独请求全量数据
const statsLoading = ref(true)
const statsError = ref('')
const statsTotal = ref(null)
const statsInUse = ref(null)
const statsMaintenance = ref(null)
const statsUnused = ref(null)

async function fetchDeviceStats() {
  if (!pageActive) return
  const version = ++statsVersion
  statsLoading.value = true
  try {
    const response = await request.get('/api/devices/stats')
    if (!pageActive || version !== statsVersion) return
    if (response.data.code === 200) {
      const stats = response.data.data || {}
      statsTotal.value = knownCount(stats.total)
      statsInUse.value = knownCount(stats.inUse)
      statsMaintenance.value = knownCount(stats.maintenance)
      statsUnused.value = knownCount(stats.idle)
      statsError.value = [statsTotal,statsInUse,statsMaintenance,statsUnused].some(item => item.value === null) ? '设备统计返回不完整，缺失值显示 —，请重新读取核对。' : ''
    } else {const failure=new Error('设备统计请求未成功');failure.httpStatus=response.data?.code;throw failure}
  } catch (e) {
    if (!pageActive || version !== statsVersion) return
    if ([401,403].includes(e.response?.status || e.httpStatus)) { statsTotal.value=null;statsInUse.value=null;statsMaintenance.value=null;statsUnused.value=null }
    statsError.value = '设备统计暂不可核对，保留上次已知数值，缺失值显示 —。'
  } finally {
    if (pageActive && version === statsVersion) statsLoading.value = false
  }
}

const deviceTypeOptions = [
  { value: 'IMAGE_CAPTURE', label: '图片采集设备' },
  { value: 'DETECTION', label: '图像检测设备' }
]

const statusOptions = [
  { value: 'IN_USE', label: '使用中' },
  { value: 'IDLE', label: '未使用' },
  { value: 'MAINTENANCE', label: '维护中' },
  { value: 'OFFLINE', label: '离线' }
]

const getDeviceTypeName = (type) => {
  const option = deviceTypeOptions.find((opt) => opt.value === type)
  return option ? option.label : type || '类型未记录'
}

const getStatusName = (status) => {
  const statusMap = {
    IN_USE: '使用中',
    '使用中': '使用中',
    IDLE: '未使用',
    '未使用': '未使用',
    '空闲': '未使用',
    MAINTENANCE: '维护中',
    '维护中': '维护中',
    '维修中': '维护中',
    OFFLINE: '离线',
    '离线': '离线'
  }
  return statusMap[status] || status
}

const formatDate = value => value ? beijingDateTime(value) || '时间格式未知' : '未记录'

const createDevice = () => {
  router.push({ name: 'deviceAdd' })
}

const viewDeviceUsageRecords = (device) => {
  router.push({
    name: 'deviceRecords',
    query: {
      deviceCode: device.deviceCode,
      deviceId: device.id
    }
  })
}

const editDevice = (id) => {
  router.push({ name: 'deviceEdit', params: { id } })
}

const viewDevice = (id) => {
  router.push({ name: 'deviceDetail', params: { id } })
}

const deleteDevice = async (id) => {
  if (!isSupervisor.value || writeBusy.value || unconfirmedDeletes.value.has(String(id))) return
  writeBusy.value=true;mutationNotice.value='';mutationUncertain.value=false;mutationFailed.value=false
  try {
    const response=await request.delete(`/api/devices/${id}`)
    if (!pageActive) return
    if(response.data?.code===200 && response.data.data===true){
      mutationNotice.value='已收到设备删除成功回执，请核对刷新后的列表与登记统计。'
      await Promise.allSettled([fetchDevices(),fetchDeviceStats()])
    }else{
      mutationUncertain.value=response.data?.code==null || response.data.code>=500 || response.data.code===200 && response.data.data!==false
      mutationFailed.value=!mutationUncertain.value
      if(mutationUncertain.value)unconfirmedDeletes.value=new Set([...unconfirmedDeletes.value,String(id)])
      mutationNotice.value=mutationUncertain.value?'设备删除结果待核对，请重新读取列表或详情；当前页面不会重复发送该设备的删除请求。':response.data?.message || '接口未确认设备删除成功，请核对当前状态。'
    }
  } catch (error) {
    if (!pageActive) return
    mutationUncertain.value=!error.response?.status || error.response.status>=500
    mutationFailed.value=!mutationUncertain.value
    if(mutationUncertain.value)unconfirmedDeletes.value=new Set([...unconfirmedDeletes.value,String(id)])
    mutationNotice.value=mutationUncertain.value?'设备删除结果待核对，请重新读取列表或详情；不会自动重发。':error.response?.data?.message || '设备删除请求未成功，请核对权限与设备状态。'
  } finally { if(pageActive)writeBusy.value=false }
}

onMounted(() => {
  fetchDevices()
  fetchDeviceStats()
})
</script>

<style scoped>
.device-page {
  gap: 18px;
}

</style>
