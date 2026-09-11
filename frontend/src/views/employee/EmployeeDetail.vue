<template>
  <div class="page-shell detail-page">
    <section class="page-hero">
      <div>
        <span class="page-hero-label">Employee Detail</span>
        <h1 class="page-hero-title">{{ employee.name || '人员详情' }}</h1>
        <p class="page-hero-text">
          {{ employee.employeeNumber || '' }} · {{ employee.department || '' }}
        </p>
      </div>
      <div class="panel-actions">
        <el-button type="primary" @click="editEmployee">编辑人员</el-button>
        <el-button @click="goBack">返回列表</el-button>
      </div>
    </section>

    <!-- 状态摘要 -->
    <section v-if="employee.id" class="stats-bar">
      <div class="stats-bar-item">
        <div class="stats-bar-icon" :class="statusIconClass">
          <span style="font-size:20px;font-weight:700">{{ employee.status === 'ACTIVE' ? '✓' : employee.status === 'VACATION' ? '休' : '离' }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ getStatusName(employee.status) }}</div>
          <div class="stats-bar-label">当前状态</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon info">
          <span style="font-size:20px;font-weight:700">{{ employee.employeeType === 'COLLECTION' ? '采' : employee.employeeType === 'DETECTION' ? '检' : '维' }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ getEmployeeTypeName(employee.employeeType) }}</div>
          <div class="stats-bar-label">人员类型</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon primary">
          <span style="font-size:20px;font-weight:700">{{ assignedDevices.length }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ assignedDevices.length }} 台</div>
          <div class="stats-bar-label">已分配设备</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon success">
          <span style="font-size:20px;font-weight:700">{{ employee.employeeNumber ? employee.employeeNumber.replace(/[^0-9]/g, '').slice(-3) : '—' }}</span>
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
            <p class="app-panel-subtitle">人员注册信息与联系方式</p>
          </div>
        </div>
      </template>
      <el-empty v-if="!employee.id" description="未找到人员信息" />
      <div v-else class="employee-profile">
        <div class="profile-avatar">
          {{ (employee.name || '?').slice(0, 1).toUpperCase() }}
        </div>
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
            <el-tag :type="getStatusType(employee.status)" effect="plain">
              {{ getStatusName(employee.status) }}
            </el-tag>
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
            <p class="app-panel-subtitle">该人员当前使用的设备列表</p>
          </div>
          <el-button type="primary" size="small" @click="assignDevices">分配设备</el-button>
        </div>
      </template>
      <div v-loading="deviceLoading">
        <el-table v-if="assignedDevices.length > 0" :data="assignedDevices" border>
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
              <el-tag :type="(row.status === 'IN_USE' || row.status === '使用中') ? 'success' : 'info'" size="small">
                {{ (row.status === 'IN_USE' || row.status === '使用中') ? '使用中' : (row.status === 'IDLE' || row.status === '未使用') ? '未使用' : row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="danger" @click="unassignDevice(row.id)">解除分配</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无分配的设备" :image-size="80" />
      </div>
    </el-card>

    <!-- 采集记录 -->
    <el-card v-if="employee.name">
      <template #header>
        <div class="panel-header">
          <div>
            <h3 class="app-panel-title">采集记录</h3>
            <p class="app-panel-subtitle">该人员的图片采集检测任务记录</p>
          </div>
          <el-button size="small" @click="fetchCollectionRecords" :loading="collectionLoading">刷新</el-button>
        </div>
      </template>
      <div v-loading="collectionLoading">
        <div v-if="collectionRecords.length > 0" class="record-list">
          <div v-for="record in collectionRecords" :key="record.taskId" class="record-card">
            <div class="record-card-header">
              <div class="record-card-title">
                <span class="record-folder">{{ record.folderName || record.taskId }}</span>
                <el-tag :type="record.status === 'COMPLETED' ? 'success' : record.status === 'FAILED' ? 'danger' : 'info'" size="small" effect="plain">
                  {{ record.status === 'COMPLETED' ? '已完成' : record.status === 'FAILED' ? '失败' : record.status }}
                </el-tag>
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
                  <span class="meta-label">设备</span>
                  <span class="meta-value">{{ record.deviceName || '—' }}</span>
                </div>
                <div class="record-meta-item">
                  <span class="meta-label">图片数量</span>
                  <span class="meta-value meta-highlight">{{ record.totalImages || 0 }} 张</span>
                </div>
                <div class="record-meta-item">
                  <span class="meta-label">创建时间</span>
                  <span class="meta-value">{{ record.createdAt || '—' }}</span>
                </div>
              </div>
              <div v-if="record.sourceOssPrefix" class="record-oss">
                <span class="meta-label">OSS 存储路径</span>
                <code class="oss-path">{{ record.sourceOssPrefix }}</code>
              </div>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无采集记录" :image-size="80" />
      </div>
    </el-card>

    <!-- 分配设备对话框 -->
    <el-dialog v-model="deviceDialog.visible" title="分配设备" width="560px">
      <el-form label-width="80px">
        <el-form-item label="选择设备">
          <el-select v-model="deviceDialog.selectedDeviceId" placeholder="请选择要分配的设备" style="width: 100%">
            <el-option
              v-for="device in deviceDialog.deviceOptions"
              :key="device.id"
              :label="`${device.deviceCode} - ${device.modelName}`"
              :value="device.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deviceDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="handleAssignDevice">确定分配</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '../../api/request'

const router = useRouter()
const route = useRoute()
const employeeId = route.params.id

const employee = ref({})
const loading = ref(true)
const assignedDevices = ref([])
const deviceLoading = ref(false)
const collectionRecords = ref([])
const collectionLoading = ref(false)

const deviceDialog = reactive({
  visible: false,
  deviceOptions: [],
  selectedDeviceId: null
})

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
  const option = employeeTypeOptions.find(opt => opt.value === type)
  return option ? option.label : type
}

const getEmployeeTypeTag = (type) => {
  if (type === 'DETECTION') return 'primary'
  if (type === 'COLLECTION') return 'success'
  if (type === 'MAINTENANCE') return 'warning'
  return 'info'
}

const getStatusName = (status) => {
  const option = statusOptions.find(opt => opt.value === status)
  return option ? option.label : status
}

const getStatusType = (status) => {
  const map = { ACTIVE: 'success', RESIGNED: 'danger', VACATION: 'warning' }
  return map[status] || 'info'
}

const statusIconClass = computed(() => {
  const t = getStatusType(employee.value?.status)
  return { success: t === 'success', warning: t === 'warning', danger: t === 'danger' }
})

const fetchEmployeeDetail = async () => {
  loading.value = true
  try {
    const response = await request.get(`/api/employees/${employeeId}`)
    if (response.data.code === 200) {
      employee.value = response.data.data
    } else {
      ElMessage.error(response.data.message || '获取人员详情失败')
    }
  } catch (error) {
    console.error('获取人员详情失败:', error)
    ElMessage.error('获取人员详情失败')
  } finally {
    loading.value = false
  }
}

const fetchAssignedDevices = async () => {
  deviceLoading.value = true
  try {
    const response = await request.get(`/api/employees/${employeeId}/devices`)
    if (response.data.code === 200) {
      assignedDevices.value = response.data.data || []
    } else {
      ElMessage.error(response.data.message || '获取设备列表失败')
    }
  } catch (error) {
    console.error('获取设备列表失败:', error)
    ElMessage.error('获取设备列表失败')
  } finally {
    deviceLoading.value = false
  }
}

const goBack = () => {
  router.push({ name: 'EmployeeManagement' })
}

const editEmployee = () => {
  router.push({ name: 'EmployeeEdit', params: { id: employeeId } })
}

const assignDevices = async () => {
  try {
    const response = await request.get('/api/devices/unassigned')
    if (response.data.code === 200) {
      deviceDialog.deviceOptions = response.data.data || []
      if (deviceDialog.deviceOptions.length === 0) {
        ElMessage.warning('当前没有可分配的设备')
      }
    } else {
      ElMessage.error(response.data.message || '获取可用设备失败')
      deviceDialog.deviceOptions = []
    }
    deviceDialog.selectedDeviceId = null
    deviceDialog.visible = true
  } catch (error) {
    console.error('加载设备数据失败:', error)
    ElMessage.error('加载设备数据失败')
  }
}

const handleAssignDevice = async () => {
  if (!deviceDialog.selectedDeviceId) {
    ElMessage.warning('请选择要分配的设备')
    return
  }
  try {
    const response = await request.post(
      `/api/employees/${employeeId}/assign-device/${deviceDialog.selectedDeviceId}`
    )
    if (response.data.code === 200) {
      ElMessage.success('设备分配成功')
      deviceDialog.visible = false
      fetchAssignedDevices()
    } else {
      ElMessage.error(response.data.message || '设备分配失败')
    }
  } catch (error) {
    console.error('设备分配失败:', error)
    ElMessage.error('设备分配失败')
  }
}

const unassignDevice = async (deviceId) => {
  try {
    const response = await request.delete(`/api/devices/${deviceId}/employee`)
    if (response.data.code === 200) {
      ElMessage.success('设备分配已解除')
      fetchAssignedDevices()
      if (deviceDialog.visible) {
        const unassignedRes = await request.get('/api/devices/unassigned')
        if (unassignedRes.data.code === 200) {
          deviceDialog.deviceOptions = unassignedRes.data.data || []
        }
      }
    } else {
      ElMessage.error(response.data.message || '解除设备分配失败')
    }
  } catch (error) {
    console.error('解除设备分配失败:', error)
    ElMessage.error('解除设备分配失败')
  }
}

const fetchCollectionRecords = async () => {
  if (!employee.value.name) return
  collectionLoading.value = true
  try {
    const response = await request.get('/api/detection/tasks/by-collector', {
      params: { collector: employee.value.name, page: 1, size: 50 }
    })
    if (response.data.code === 200) {
      const data = response.data.data || {}
      collectionRecords.value = data.records || data || []
    }
  } catch (error) {
    console.error('获取采集记录失败:', error)
  } finally {
    collectionLoading.value = false
  }
}

onMounted(async () => {
  await fetchEmployeeDetail()
  fetchAssignedDevices()
  fetchCollectionRecords()
})
</script>

<style scoped>
.detail-page {
  gap: 18px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.employee-profile {
  display: flex;
  gap: 28px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.profile-avatar {
  width: 64px;
  height: 64px;
  border-radius: 18px;
  display: grid;
  place-items: center;
  color: #fff;
  font-weight: 800;
  font-size: 24px;
  background: linear-gradient(135deg, var(--app-primary), #4f8bff);
  flex-shrink: 0;
}

.profile-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(180px, 1fr));
  gap: 14px 36px;
  flex: 1;
  min-width: 300px;
}

.profile-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.profile-label {
  font-size: 12px;
  color: var(--app-text-muted);
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
  }
  .employee-profile {
    flex-direction: column;
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
</style>
