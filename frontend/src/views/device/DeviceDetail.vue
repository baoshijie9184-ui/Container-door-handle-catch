<template>
  <div class="page-shell detail-page">
    <PageHero :title="device?.deviceCode || '设备详情'" description="核对设备登记、当前使用员工与采集记录。业务状态不代表实时在线状态。" icon="Monitor">
      <template #actions>
        <el-button :loading="loading" :disabled="deleteBusy" @click="refreshDevice"><AppIcon name="Refresh" :size="16" />刷新资料</el-button>
        <el-button :disabled="loading || !device" @click="viewUsageRecords"><AppIcon name="Clock" :size="16" />使用记录</el-button>
        <el-button v-if="isSupervisor" type="primary" :disabled="loading || !!loadError || deleteBusy || deleteReceipt?.state==='UNKNOWN' || !device" @click="editDevice"><AppIcon name="Edit" :size="16" />编辑设备</el-button>
        <el-popconfirm v-if="isSupervisor && device" :title="`确认删除设备 ${device.deviceCode || deviceId}？`" @confirm="deleteDevice">
          <template #reference><el-button type="danger" plain :loading="deleteBusy" :disabled="loading || !!loadError || deleteReceipt?.state==='UNKNOWN'"><AppIcon name="Delete" :size="16" />删除设备</el-button></template>
        </el-popconfirm>
        <el-button @click="goBack"><AppIcon name="ArrowLeft" :size="16" />返回列表</el-button>
      </template>
    </PageHero>
    <el-alert v-if="deleteReceipt" :title="deleteReceipt.message" :type="deleteReceipt.state==='UNKNOWN' ? 'warning' : 'error'" show-icon :closable="false" />
    <p v-if="deleteBusy" role="status" class="app-panel-subtitle">正在等待设备删除回执，请勿重复提交</p>
    <!-- 状态摘要 -->
    <section v-if="device" class="stats-bar">
      <div class="stats-bar-item">
        <div class="stats-bar-icon" :class="statusIconClass">
          <AppIcon name="Monitor" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ getStatusName(device.status) }}</div>
          <div class="stats-bar-label">当前状态</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon info">
          <AppIcon name="Picture" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ getDeviceTypeName(device.deviceType) }}</div>
          <div class="stats-bar-label">设备类型</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon primary">
          <AppIcon name="User" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ device.employee ? device.employee.name : '未分配' }}</div>
          <div class="stats-bar-label">当前使用人</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon warning">
          <AppIcon name="Clock" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ device.lastMaintenanceDate ? formatDate(device.lastMaintenanceDate) : '暂无记录' }}</div>
          <div class="stats-bar-label">最后维护时间</div>
        </div>
      </div>
    </section>

    <el-card v-loading="loading">
      <template #header>
        <div class="panel-header">
          <div>
            <h3 class="app-panel-title">基本信息</h3>
            <p class="app-panel-subtitle">设备登记信息与 UTC+8 时间，不代表实时在线状态</p>
          </div>
        </div>
      </template>
      <el-alert v-if="loadError && device" :title="loadError+'；以下保留先前读取的资料，请刷新核对。'" type="error" show-icon :closable="false" />
      <CollectionEmptyState v-if="!device" :loading="loading" :error="loadError" empty-title="未找到设备资料" empty-description="请返回列表核对设备编号及当前账号的访问范围。" @retry="refreshDevice" />
      <el-descriptions v-else :column="2" border>
        <el-descriptions-item label="设备编号" :span="2">
          <code class="info-code">{{ device.deviceCode }}</code>
        </el-descriptions-item>
        <el-descriptions-item label="设备类型">
          <el-tag :type="getDeviceTypeTag(device.deviceType)" effect="plain">
            {{ getDeviceTypeName(device.deviceType) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="设备状态">
          <StatusBadge domain="device" :code="device.status" :label="getStatusName(device.status)" />
        </el-descriptions-item>
        <el-descriptions-item label="设备型号">{{ device.modelName }}</el-descriptions-item>
        <el-descriptions-item label="序列号">{{ device.serialNumber }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDate(device.createdTime) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDate(device.updatedTime) }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 使用员工信息 -->
    <el-card v-if="device?.employee">
      <template #header>
        <div class="panel-header">
          <div>
            <h3 class="app-panel-title">当前使用员工</h3>
            <p class="app-panel-subtitle">该设备目前分配给的员工信息</p>
          </div>
          <el-button v-if="isSupervisor" type="danger" plain size="small" :disabled="loading || !!loadError || deleteBusy || deleteReceipt?.state==='UNKNOWN' || !device.employee.id" @click="unassignDevice"><AppIcon name="Close" :size="15" />解除分配</el-button>
        </div>
      </template>
      <div class="employee-card-inner">
        <div class="emp-avatar">
          {{ (device.employee.name || '?').slice(0, 1).toUpperCase() }}
        </div>
        <div class="emp-info-grid">
          <div class="emp-info-item">
            <span class="emp-label">姓名</span>
            <span class="emp-value">{{ device.employee.name }}</span>
          </div>
          <div class="emp-info-item">
            <span class="emp-label">员工编号</span>
            <span class="emp-value">{{ device.employee.employeeNumber }}</span>
          </div>
          <div class="emp-info-item">
            <span class="emp-label">人员类型</span>
            <span class="emp-value">{{ getEmployeeTypeName(device.employee.employeeType) }}</span>
          </div>
          <div class="emp-info-item">
            <span class="emp-label">联系方式</span>
            <span class="emp-value">{{ device.employee.contact }}</span>
          </div>
        </div>
        <el-button size="small" type="primary" @click="viewEmployee(device.employee.id)">
          查看员工详情
        </el-button>
      </div>
    </el-card>

    <!-- 采集记录 -->
    <el-card v-if="device?.deviceCode">
      <template #header>
        <div class="panel-header">
          <div>
            <h3 class="app-panel-title">采集记录</h3>
            <p class="app-panel-subtitle">按登记设备编号查询，仍受当前账号任务权限约束。最多读取 50 条。</p>
          </div>
          <el-button size="small" @click="fetchCollectionRecords" :loading="collectionLoading"><AppIcon name="Refresh" :size="16" />刷新</el-button>
        </div>
      </template>
      <el-alert v-if="collectionError && collectionRecords.length" :title="collectionError+'；下方保留先前读取的记录。'" type="error" show-icon :closable="false" />
      <div v-loading="collectionLoading">
        <div v-if="collectionRecords.length > 0" class="record-list">
          <div v-for="record in collectionRecords" :key="record.taskId" class="record-card">
            <div class="record-card-header">
              <div class="record-card-title">
                <span class="record-folder">{{ record.folderName || record.taskId }}</span>
                <StatusBadge domain="detection" :code="record.status" />
              </div>
              <code class="record-taskid">{{ record.taskId }}</code>
            </div>
            <div class="record-card-body">
              <div class="record-meta-grid">
                <div class="record-meta-item">
                  <span class="meta-label">采集日期</span>
                  <span class="meta-value">{{ record.captureDate || '—' }}</span>
                </div>
                <div class="record-meta-item">
                  <span class="meta-label">地区</span>
                  <span class="meta-value">{{ record.region || '—' }}</span>
                </div>
                <div class="record-meta-item">
                  <span class="meta-label">采集人</span>
                  <span class="meta-value">{{ record.collector || '—' }}</span>
                </div>
                <div class="record-meta-item">
                  <span class="meta-label">图片数量</span>
                  <span class="meta-value meta-highlight">{{ record.totalImages ?? '—' }} 张</span>
                </div>
                <div class="record-meta-item">
                  <span class="meta-label">创建时间</span>
                  <span class="meta-value">{{ formatDate(record.createdAt) }}（UTC+8）</span>
                </div>
              </div>
              <details v-if="record.sourceOssPrefix" class="record-oss">
                <summary class="meta-label">查看存储记录</summary>
                <code class="oss-path">{{ record.sourceOssPrefix }}</code>
              </details>
              <router-link class="detail-record-link" :to="{path:'/inspection/history',query:{keyword:record.taskId}}"><AppIcon name="Search" :size="14" />查看检测记录</router-link>
            </div>
          </div>
        </div>
        <CollectionEmptyState v-else :loading="collectionLoading" :error="collectionError" empty-title="暂无采集记录" empty-description="设备的采集任务登记后，可在这里查看。" @retry="fetchCollectionRecords" />
      </div>
    </el-card>
    <EmployeeDeviceAssignment :context-key="deviceId" ref="assignmentPanel" @changed="refreshDevice" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {beijingDateTime} from '@/utils/beijingTime'
import { ElMessage } from 'element-plus'
import request from '../../api/request'
import { useUserStore } from '../../stores/user'
import CollectionEmptyState from '../../components/CollectionEmptyState.vue'
import EmployeeDeviceAssignment from '../../components/EmployeeDeviceAssignment.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const isSupervisor = computed(() => userStore.role === 'SUPERVISOR')
const resourceId = value => typeof value==='number' && Number.isSafeInteger(value) && value>0 ? String(value) : typeof value==='string' && /^[1-9]\d*$/.test(value) ? value : ''
const deviceId = computed(() => resourceId(route.params.id))
const actor = computed(() => JSON.stringify([userStore.identity?.userId || userStore.username || '', userStore.role, userStore.isAuthenticated]))
let pageActive=true
const readVersion={detail:0,records:0}
const readContext=()=>JSON.stringify([deviceId.value,actor.value])
const currentRead=(channel,version,context)=>pageActive && readVersion[channel]===version && readContext()===context
onBeforeUnmount(()=>{pageActive=false;Object.keys(readVersion).forEach(key=>readVersion[key]++)})
function readData(response){
  if(response.data?.code!==200){const failure=new Error(response.data?.message || '资料读取未成功');failure.httpStatus=response.data?.code;throw failure}
  return response.data.data
}
const accessDenied=error=>[401,403].includes(error.response?.status || error.httpStatus)
const deleteBusy=ref(false), deleteReceipt=ref(null)
const assignmentPanel = ref(null)
const device = ref(null)
const loading = ref(false)
const collectionRecords = ref([])
const collectionLoading = ref(false)
const loadError = ref(''), collectionError = ref('')

const deviceTypeOptions = [
  { value: 'IMAGE_CAPTURE', label: '图片采集设备' },
  { value: 'DETECTION', label: '图像检测设备' }
]

const employeeTypeOptions = [
  { value: 'DETECTION', label: '门把手检测人员' },
  { value: 'COLLECTION', label: '门把手图片采集人员' },
  { value: 'MAINTENANCE', label: '设备维护人员' }
]

const getDeviceTypeName = (type) => {
  const option = deviceTypeOptions.find(opt => opt.value === type)
  return option ? option.label : type
}

const getDeviceTypeTag = (type) => {
  if (type === 'IMAGE_CAPTURE') return 'primary'
  if (type === 'DETECTION') return 'success'
  return 'info'
}

const getStatusName = (status) => {
  const map = {
    IN_USE: '使用中', '使用中': '使用中',
    IDLE: '未使用', '未使用': '未使用', '空闲': '未使用',
    MAINTENANCE: '维护中', '维护中': '维护中',
    OFFLINE: '离线', '离线': '离线'
  }
  return map[status] || status
}

const getStatusType = (status) => {
  if (status === 'IN_USE' || status === '使用中') return 'success'
  if (status === 'MAINTENANCE' || status === '维护中') return 'warning'
  if (status === 'OFFLINE' || status === '离线') return 'danger'
  return 'info'
}

const statusIconClass = computed(() => {
  const t = getStatusType(device.value?.status)
  return { success: t === 'success', warning: t === 'warning', danger: t === 'danger', info: t === 'info' }
})

const getEmployeeTypeName = (type) => {
  const option = employeeTypeOptions.find(opt => opt.value === type)
  return option ? option.label : type
}

const formatDate = (dateStr) => {
  if (!dateStr) return '—'
  return beijingDateTime(dateStr) || '时间格式未知'
}

const fetchDevice = async () => {
  if(!pageActive || !deviceId.value || !userStore.isAuthenticated)return false
  const version=++readVersion.detail, context=readContext()
  loading.value=true;loadError.value=''
  try {
    const response=await request.get(`/api/devices/${deviceId.value}`)
    if(!currentRead('detail',version,context))return false
    const data=readData(response)
    if(resourceId(data?.id)!==deviceId.value)throw new Error('设备编号未完整读取，请重新核对')
    if(device.value?.deviceCode!==data.deviceCode){readVersion.records++;collectionRecords.value=[];collectionError.value='';collectionLoading.value=false}
    device.value=data
    return true
  } catch(error) {
    if(!currentRead('detail',version,context))return false
    if(accessDenied(error)){device.value=null;collectionRecords.value=[];readVersion.records++;collectionLoading.value=false}
    loadError.value=error.response?.data?.message || error.message || '设备详情暂不可读取'
    return false
  } finally {if(currentRead('detail',version,context))loading.value=false}
}
const viewUsageRecords = () => {
  if (device.value) {
    router.push({
      name: 'deviceRecords',
      query: { deviceCode: device.value.deviceCode, deviceId: device.value.id }
    })
  }
}

const editDevice = () => {
  router.push({ name: 'deviceEdit', params: { id: deviceId.value } })
}

const deleteDevice = async () => {
  if(!pageActive || !userStore.isAuthenticated || !isSupervisor.value || loading.value || loadError.value || deleteBusy.value || deleteReceipt.value?.state==='UNKNOWN' || resourceId(device.value?.id)!==deviceId.value)return
  const target=deviceId.value, context=readContext()
  const current=()=>pageActive && readContext()===context
  deleteBusy.value=true;deleteReceipt.value=null
  try {
    const response=await request.delete(`/api/devices/${target}`)
    if(!current())return
    const body=response.data
    if(body?.code===200 && body.data===true){ElMessage.success('已收到设备删除成功回执');goBack();return}
    const unknown=body?.code==null || body.code>=500 || body.code===200 && body.data!==false
    deleteReceipt.value={state:unknown?'UNKNOWN':'REJECTED',message:unknown?'删除结果待核对，请刷新记录；当前页面不会重发。':body?.message || '接口未确认设备删除成功，请核对后操作。'}
  } catch(error) {
    if(!current())return
    const unknown=!error.response?.status || error.response.status>=500
    deleteReceipt.value={state:unknown?'UNKNOWN':'REJECTED',message:unknown?'删除结果待核对，请刷新记录；当前页面不会重发。':error.response?.data?.message || '接口未确认设备删除成功。'}
  } finally {if(current())deleteBusy.value=false}
}
const goBack = () => {
  router.push({ name: 'devices' })
}

const viewEmployee = (employeeId) => {
  router.push({ name: 'employeeDetail', params: { id: employeeId } })
}

const unassignDevice = () => {
  if(loading.value || loadError.value || deleteBusy.value || deleteReceipt.value?.state==='UNKNOWN' || !device.value?.employee?.id || !isSupervisor.value)return
  return assignmentPanel.value?.openFor(device.value.employee.id,{removeDeviceId:device.value.id})
}
const fetchCollectionRecords = async () => {
  if(!pageActive || !device.value?.deviceCode || !userStore.isAuthenticated)return
  const version=++readVersion.records, context=readContext(), code=device.value.deviceCode
  collectionLoading.value=true;collectionError.value=''
  try {
    const response=await request.get('/api/detection/tasks/by-device',{params:{deviceName:code,page:1,size:50}})
    if(!currentRead('records',version,context) || device.value?.deviceCode!==code)return
    const data=readData(response),rows=Array.isArray(data)?data:data?.records
    if(!Array.isArray(rows) || rows.some(row=>!row || typeof row.taskId!=='string' || !row.taskId))throw new Error('采集记录未完整读取')
    collectionRecords.value=rows
  } catch(error) {
    if(!currentRead('records',version,context) || device.value?.deviceCode!==code)return
    if(accessDenied(error))collectionRecords.value=[]
    collectionError.value=error.response?.data?.message || error.message || '采集记录暂不可读取'
  } finally {if(currentRead('records',version,context))collectionLoading.value=false}
}

const refreshDevice = async () => { if(await fetchDevice())fetchCollectionRecords() }
watch([deviceId,actor],async()=>{
  Object.keys(readVersion).forEach(key=>readVersion[key]++)
  device.value=null;collectionRecords.value=[];loadError.value='';collectionError.value='';loading.value=false;collectionLoading.value=false;deleteBusy.value=false;deleteReceipt.value=null
  if(!deviceId.value){loadError.value='设备编号无效，请返回列表核对';return}
  if(!userStore.isAuthenticated)return
  await refreshDevice()
},{immediate:true,flush:'sync'})
</script>

<style scoped>
.detail-page {
  gap: 18px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.info-code {
  font-family: 'SF Mono', 'Consolas', monospace;
  font-size: 13px;
  color: var(--app-primary);
  background: var(--app-primary-soft);
  padding: 2px 10px;
  border-radius: 6px;
}

.employee-card-inner {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}

.emp-avatar {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  display: grid;
  place-items: center;
  color: #fff;
  font-weight: 800;
  font-size: 20px;
  background: linear-gradient(135deg, var(--app-primary), #4f8bff);
  flex-shrink: 0;
}

.emp-info-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 32px;
  flex: 1;
  min-width: 240px;
}

.emp-info-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.emp-label {
  font-size: 12px;
  color: var(--app-text-muted);
}

.emp-value {
  font-weight: 600;
  color: var(--app-text);
  font-size: 14px;
}

@media (max-width: 768px) {
  .emp-info-grid {
    grid-template-columns: 1fr;
  }
  .employee-card-inner {
    flex-direction: column;
    align-items: flex-start;
  }
}

/* 采集记录卡片 */
.record-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.record-card {
  border: 1px solid var(--app-border, #e8ecef);
  border-radius: 12px;
  overflow: hidden;
  background: #fafbfc;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.record-card:hover {
  border-color: rgba(22, 119, 255, 0.2);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
}

.record-card-header {
  padding: 14px 18px 10px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.04);
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.record-card-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.record-folder {
  font-weight: 600;
  font-size: 14px;
  color: #172033;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.record-taskid {
  font-size: 11px;
  color: #8b95a5;
  font-family: 'SF Mono', 'Consolas', monospace;
  background: rgba(15, 23, 42, 0.04);
  padding: 2px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}

.record-card-body {
  padding: 14px 18px;
}

.record-meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px 24px;
}

.record-meta-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.meta-label {
  font-size: 12px;
  color: #8b95a5;
  font-weight: 500;
}

.meta-value {
  font-size: 14px;
  color: #172033;
  font-weight: 500;
}

.meta-highlight {
  color: #1677ff;
  font-weight: 600;
  font-size: 15px;
}

.record-oss {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(15, 23, 42, 0.04);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.oss-path {
  font-size: 12px;
  color: #1677ff;
  background: rgba(22, 119, 255, 0.06);
  padding: 6px 12px;
  border-radius: 8px;
  font-family: 'SF Mono', 'Consolas', monospace;
  word-break: break-all;
}
.emp-value { overflow-wrap:anywhere; }
@media(prefers-reduced-motion:reduce) { .record-card { transition:none; } }
</style>
