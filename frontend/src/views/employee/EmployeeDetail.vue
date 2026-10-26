<template>
  <div class="page-shell detail-page">
    <PageHero :title="employee.name || '人员详情'" description="核对人员登记、设备关系与采集记录；人员业务岗位与登录账号权限分别管理。" icon="User">
      <template #actions>
        <el-button :loading="loading" @click="refreshEmployee"><AppIcon name="Refresh" :size="16" />刷新资料</el-button>
        <el-button v-if="isSupervisor" type="primary" :disabled="loading || !!loadError || !employee.id" @click="editEmployee"><AppIcon name="Edit" :size="16" />编辑人员</el-button>
        <el-button @click="goBack"><AppIcon name="ArrowLeft" :size="16" />返回列表</el-button>
      </template>
    </PageHero>
    <!-- 状态摘要 -->
    <section v-if="employee.id" class="stats-bar">
      <div class="stats-bar-item">
        <div class="stats-bar-icon" :class="statusIconClass">
          <AppIcon :name="statusSummary.icon" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ getStatusName(employee.status) }}</div>
          <div class="stats-bar-label">在岗登记状态</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon info">
          <AppIcon name="User" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ getEmployeeTypeName(employee.employeeType) }}</div>
          <div class="stats-bar-label">人员类型</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon primary">
          <AppIcon name="Monitor" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ devicesKnown ? assignedDevices.length+' 台' : '—' }}</div>
          <div class="stats-bar-label">已分配设备</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon info">
          <AppIcon name="Document" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ employee.employeeNumber || '—' }}</div>
          <div class="stats-bar-label">员工编号</div>
        </div>
      </div>
    </section>

    <el-card v-loading="loading">
      <template #header>
        <div class="panel-header">
          <div>
            <h3 class="app-panel-title">基本信息</h3>
            <p class="app-panel-subtitle">人员登记资料与联系方式</p>
          </div>
        </div>
      </template>
      <el-alert v-if="loadError && employee.id" :title="loadError+'；以下保留先前读取的资料，请刷新核对。'" type="error" show-icon :closable="false" />
      <CollectionEmptyState v-if="!employee.id" :loading="loading" :error="loadError" empty-title="未找到人员资料" empty-description="请返回列表核对员工编号和当前账号的访问范围。" @retry="refreshEmployee" />
      <div v-else class="employee-profile">
        <div class="profile-avatar" aria-hidden="true"><AppIcon name="User" :size="26" /></div>
        <div class="profile-grid">
          <div class="profile-item">
            <span class="profile-label">姓名</span>
            <span class="profile-value">{{ employee.name }}</span>
          </div>
          <div class="profile-item">
            <span class="profile-label">员工编号</span>
            <span class="profile-value">{{ employee.employeeNumber }}</span>
          </div>
          <div class="profile-item">
            <span class="profile-label">联系方式</span>
            <span class="profile-value">{{ employee.contact }}</span>
          </div>
          <div class="profile-item">
            <span class="profile-label">性别</span>
            <span class="profile-value">{{ employee.gender }}</span>
          </div>
          <div class="profile-item">
            <span class="profile-label">部门 / 班组</span>
            <span class="profile-value">{{ employee.department }}</span>
          </div>
          <div class="profile-item">
            <span class="profile-label">人员类型</span>
            <el-tag :type="getEmployeeTypeTag(employee.employeeType)" effect="plain">
              {{ getEmployeeTypeName(employee.employeeType) }}
            </el-tag>
          </div>
          <div class="profile-item">
            <span class="profile-label">入职日期</span>
            <span class="profile-value">{{ employee.hireDate || '暂无记录' }}</span>
          </div>
          <div class="profile-item">
            <span class="profile-label">状态</span>
            <StatusBadge domain="employee" :code="employee.status" :label="getStatusName(employee.status)" />
          </div>
        </div>
        <div v-if="employee.remark" class="profile-remark">
          <span class="profile-label">备注</span>
          <p>{{ employee.remark }}</p>
        </div>
      </div>
    </el-card>

    <!-- 已分配设备 -->
    <el-card>
      <template #header>
        <div class="panel-header">
          <div>
            <h3 class="app-panel-title">已分配设备</h3>
            <p class="app-panel-subtitle">当前登记的设备关系，不代表设备实时在线。</p>
          </div>
          <el-button size="small" :loading="deviceLoading" @click="fetchAssignedDevices"><AppIcon name="Refresh" :size="15" />刷新关系</el-button><el-button v-if="isSupervisor" type="primary" size="small" :disabled="loading || !!loadError || !employee.id" @click="assignDevices"><AppIcon name="Monitor" :size="15" />分配设备</el-button>
        </div>
      </template>
      <div v-loading="deviceLoading">
        <el-alert v-if="deviceError && assignedDevices.length" :title="deviceError+'；下方保留先前读取的记录。'" type="error" show-icon :closable="false" />
        <el-table :scrollbar-tabindex="0" role="region" aria-label="当前人员已分配设备" v-if="assignedDevices.length > 0" :data="assignedDevices" border>
          <template #empty>
            <el-empty description="暂无分配的设备" :image-size="80" />
          </template>
          <el-table-column prop="deviceCode" label="设备编号" width="140" />
          <el-table-column label="设备类型" width="150">
            <template #default="{ row }">
              {{ row.deviceType === 'IMAGE_CAPTURE' ? '图片采集设备' : row.deviceType === 'DETECTION' ? '图像检测设备' : row.deviceType }}
            </template>
          </el-table-column>
          <el-table-column prop="modelName" label="型号" min-width="140" show-overflow-tooltip />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <StatusBadge domain="device" :code="row.status" />
            </template>
          </el-table-column>
          <el-table-column v-if="isSupervisor" label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="danger" plain :disabled="loading || deviceLoading || !!deviceError || !!loadError" @click="unassignDevice(row.id)">解除分配</el-button>
            </template>
          </el-table-column>
        </el-table>
        <CollectionEmptyState v-else :loading="deviceLoading" :error="deviceError" empty-title="暂无分配设备" empty-description="有权限的主管分配设备后，可在这里查看。" @retry="fetchAssignedDevices" />
      </div>
    </el-card>

    <!-- 采集记录 -->
    <el-card v-if="employee.name">
      <template #header>
        <div class="panel-header">
          <div>
            <h3 class="app-panel-title">采集记录</h3>
            <p class="app-panel-subtitle">按登记姓名匹配，仍受当前账号任务权限约束；同名或更名需核对。最多读取 50 条。</p>
          </div>
          <el-button size="small" @click="fetchCollectionRecords" :loading="collectionLoading"><AppIcon name="Refresh" :size="16" />刷新</el-button>
        </div>
      </template>
      <el-alert v-if="collectionError && collectionRecords.length" :title="collectionError+'；下方保留先前读取的记录。'" type="error" show-icon :closable="false" />
      <div v-loading="collectionLoading">
        <CollectionTaskRecords v-if="collectionRecords.length > 0" :records="collectionRecords" counterpart="device" :context-key="employeeId + ':' + actor + ':' + employee.name" />
        <CollectionEmptyState v-else :loading="collectionLoading" :error="collectionError" empty-title="暂无采集记录" empty-description="人员的采集任务登记后，可在这里查看。" @retry="fetchCollectionRecords" />
      </div>
    </el-card>

    <EmployeeDeviceAssignment :context-key="employeeId" ref="assignmentPanel" @changed="fetchAssignedDevices" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import request from '../../api/request'
import { useUserStore } from '../../stores/user'
import { beijingDateTime } from '../../utils/beijingTime'
import CollectionEmptyState from '../../components/CollectionEmptyState.vue'
import CollectionTaskRecords from '../../components/CollectionTaskRecords.vue'
import EmployeeDeviceAssignment from '../../components/EmployeeDeviceAssignment.vue'
import { statusPresentation } from '../../utils/statusPresentation'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const isSupervisor = computed(() => userStore.role === 'SUPERVISOR')
const formatTime = value => value ? beijingDateTime(value) || '时间格式未知' : '未记录'
const resourceId = value => typeof value==='number' && Number.isSafeInteger(value) && value>0 ? String(value) : typeof value==='string' && /^[1-9]\d*$/.test(value) ? value : ''
const employeeId = computed(() => resourceId(route.params.id))
const actor = computed(() => JSON.stringify([userStore.identity?.userId || userStore.username || '', userStore.role, userStore.isAuthenticated]))
let pageActive = true
const readVersion = { detail:0, devices:0, records:0 }
const readContext = () => JSON.stringify([employeeId.value, actor.value])
const currentRead = (channel, version, context) => pageActive && readVersion[channel]===version && readContext()===context
onBeforeUnmount(() => { pageActive=false; Object.keys(readVersion).forEach(key => readVersion[key]++) })
function readData(response) {
  if(response.data?.code!==200) { const failure=new Error(response.data?.message || '资料读取未成功');failure.httpStatus=response.data?.code;throw failure }
  return response.data.data
}
const accessDenied = error => [401,403].includes(error.response?.status || error.httpStatus)

const employee = ref({})
const loading = ref(true)
const assignedDevices = ref([])
const deviceLoading = ref(false)
const collectionRecords = ref([])
const collectionLoading = ref(false)
const loadError = ref(''), deviceError = ref(''), collectionError = ref(''), devicesKnown = ref(false)

const assignmentPanel = ref(null)

const employeeTypeOptions = [
  { value: 'DETECTION', label: '门把手检测人员' },
  { value: 'COLLECTION', label: '门把手图片采集人员' },
  { value: 'MAINTENANCE', label: '设备维护人员' }
]

const getEmployeeTypeName = (type) => {
  const option = employeeTypeOptions.find(opt => opt.value === type)
  return option ? option.label : type
}

const getEmployeeTypeTag = (type) => {
  if (type === 'DETECTION') return 'primary'
  if (type === 'COLLECTION') return 'success'
  if (type === 'MAINTENANCE') return 'warning'
  return 'info'
}

const getStatusName = status => statusPresentation('employee', status).label
const statusSummary = computed(() => statusPresentation('employee', employee.value?.status))
const statusIconClass = computed(() => statusSummary.value.tone === 'progress' ? 'primary' : statusSummary.value.tone)

const fetchEmployeeDetail = async () => {
  if(!pageActive || !employeeId.value || !userStore.isAuthenticated)return false
  const version=++readVersion.detail, context=readContext()
  loading.value=true;loadError.value=''
  try {
    const response=await request.get(`/api/employees/${employeeId.value}`)
    if(!currentRead('detail',version,context))return false
    const data=readData(response)
    if(resourceId(data?.id)!==employeeId.value)throw new Error('人员编号未完整读取，请重新核对')
    if(employee.value.name!==data.name){readVersion.records++;collectionRecords.value=[];collectionError.value='';collectionLoading.value=false}
    employee.value=data
    return true
  } catch(error) {
    if(!currentRead('detail',version,context))return false
    if(accessDenied(error)){employee.value={};assignedDevices.value=[];collectionRecords.value=[];devicesKnown.value=false;readVersion.devices++;readVersion.records++;deviceLoading.value=false;collectionLoading.value=false}
    loadError.value=error.response?.data?.message || error.message || '人员详情暂不可读取'
    return false
  } finally { if(currentRead('detail',version,context))loading.value=false }
}

const fetchAssignedDevices = async () => {
  if(!pageActive || !employeeId.value || !userStore.isAuthenticated)return
  const version=++readVersion.devices, context=readContext()
  deviceLoading.value=true;deviceError.value=''
  try {
    const response=await request.get(`/api/employees/${employeeId.value}/devices`)
    if(!currentRead('devices',version,context))return
    const data=readData(response), ids=new Set()
    if(!Array.isArray(data))throw new Error('设备列表未完整读取')
    for(const row of data){const key=resourceId(row?.id);if(!key || ids.has(key))throw new Error('设备编号未完整读取');ids.add(key)}
    assignedDevices.value=data;devicesKnown.value=true
  } catch(error) {
    if(!currentRead('devices',version,context))return
    if(accessDenied(error)){assignedDevices.value=[];devicesKnown.value=false}
    deviceError.value=error.response?.data?.message || error.message || '设备列表暂不可读取'
  } finally { if(currentRead('devices',version,context))deviceLoading.value=false }
}
const goBack = () => {
  router.push({ name: 'employees' })
}

const editEmployee = () => {
  router.push({ name: 'employeeEdit', params: { id: employeeId.value } })
}

const assignDevices = () => assignmentPanel.value?.openFor(employee.value.id || employeeId.value)
const unassignDevice = deviceId => assignmentPanel.value?.openFor(employee.value.id || employeeId.value,{removeDeviceId:deviceId})
const fetchCollectionRecords = async () => {
  if(!pageActive || !employee.value.name || !userStore.isAuthenticated)return
  const version=++readVersion.records, context=readContext(), name=employee.value.name
  collectionLoading.value=true;collectionError.value=''
  try {
    const response=await request.get('/api/detection/tasks/by-collector',{params:{collector:name,page:1,size:50}})
    if(!currentRead('records',version,context) || employee.value.name!==name)return
    const data=readData(response), rows=Array.isArray(data)?data:data?.records
    if(!Array.isArray(rows) || rows.some(row=>!row || typeof row.taskId!=='string' || !row.taskId))throw new Error('采集记录未完整读取')
    collectionRecords.value=rows
  } catch(error) {
    if(!currentRead('records',version,context) || employee.value.name!==name)return
    if(accessDenied(error))collectionRecords.value=[]
    collectionError.value=error.response?.data?.message || error.message || '采集记录暂不可读取'
  } finally { if(currentRead('records',version,context))collectionLoading.value=false }
}

const refreshEmployee = async () => {
  if(await fetchEmployeeDetail()){fetchAssignedDevices();fetchCollectionRecords()}
}
watch([employeeId,actor],async()=>{
  Object.keys(readVersion).forEach(key=>readVersion[key]++)
  employee.value={};assignedDevices.value=[];collectionRecords.value=[];devicesKnown.value=false
  loadError.value='';deviceError.value='';collectionError.value='';loading.value=false;deviceLoading.value=false;collectionLoading.value=false
  if(!employeeId.value){loadError.value='人员编号无效，请返回列表核对';return}
  if(!userStore.isAuthenticated)return
  await refreshEmployee()
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

.employee-profile {
  display: flex;
  gap: 28px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.profile-avatar {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  color: var(--app-primary);
  background: var(--app-primary-soft);
  flex-shrink: 0;
}

.profile-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 36px;
  flex: 1;
  min-width: 0;
}

.profile-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.profile-label {
  font-size: 12px;
  color: var(--app-text-secondary);
}

.profile-value {
  font-weight: 600;
  color: var(--app-text);
  font-size: 15px;
}

.profile-remark {
  width: 100%;
  padding-top: 16px;
  border-top: 1px solid var(--app-border);
}

.profile-remark p {
  margin: 6px 0 0;
  color: var(--app-text-secondary);
  font-size: 14px;
  line-height: 1.6;
}

@media (max-width: 768px) {
  .profile-grid {
    grid-template-columns: 1fr;
    width: 100%;
  }
  .employee-profile {
    flex-direction: column;
  }
}

.profile-value { overflow-wrap:anywhere; }

</style>
