<template>
  <div class="page-shell detail-page">
    <section class="page-hero">
      <div>
        <span class="page-hero-label">Device Detail</span>
        <h1 class="page-hero-title">{{ device?.deviceCode || '设备详情' }}</h1>
        <p class="page-hero-text">
          {{ device?.modelName || '' }} · {{ getDeviceTypeName(device?.deviceType) }}
        </p>
      </div>
      <div class="panel-actions">
        <el-button type="success" @click="viewUsageRecords">查看使用记录</el-button>
        <el-button type="primary" @click="editDevice">编辑设备</el-button>
        <el-popconfirm title="确定要删除此设备吗？" @confirm="deleteDevice">
          <template #reference>
            <el-button type="danger">删除设备</el-button>
          </template>
        </el-popconfirm>
        <el-button @click="goBack">返回列表</el-button>
      </div>
    </section>

    <!-- 状态摘要 -->
    <section v-if="device" class="stats-bar">
      <div class="stats-bar-item">
        <div class="stats-bar-icon" :class="statusIconClass">
          <span style="font-size:20px;font-weight:700">{{ (device.status === 'IN_USE' || device.status === '使用中') ? '✓' : (device.status === 'MAINTENANCE' || device.status === '维护中') ? '修' : (device.status === 'OFFLINE' || device.status === '离线') ? '✗' : '—' }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ getStatusName(device.status) }}</div>
          <div class="stats-bar-label">当前状态</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon info">
          <span style="font-size:20px;font-weight:700">{{ device.deviceType === 'IMAGE_CAPTURE' ? '采' : '检' }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ getDeviceTypeName(device.deviceType) }}</div>
          <div class="stats-bar-label">设备类型</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon primary">
          <span style="font-size:20px;font-weight:700">{{ device.employee ? '✓' : '—' }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ device.employee ? device.employee.name : '未分配' }}</div>
          <div class="stats-bar-label">当前使用人</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon warning">
          <span style="font-size:20px;font-weight:700">{{ device.lastMaintenanceDate ? '✓' : '—' }}</span>
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
            <p class="app-panel-subtitle">设备注册信息与时间戳</p>
          </div>
        </div>
      </template>
      <el-empty v-if="!device" description="未找到设备信息" />
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
          <el-tag :type="getStatusType(device.status)" effect="plain">
            {{ getStatusName(device.status) }}
          </el-tag>
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
          <el-button type="danger" plain size="small" @click="unassignDevice">解除分配</el-button>
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
            <p class="app-panel-subtitle">该设备的图片采集检测任务记录</p>
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
                  <span class="meta-label">采集人</span>
                  <span class="meta-value">{{ record.collector || '—' }}</span>
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
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '../../api/request'

const router = useRouter()
const route = useRoute()
const deviceId = route.params.id
const device = ref(null)
const loading = ref(false)
const collectionRecords = ref([])
const collectionLoading = ref(false)

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
  return new Date(dateStr).toLocaleString()
}

const fetchDevice = async () => {
  loading.value = true
  try {
    const response = await request.get(`/api/devices/${deviceId}`)
    if (response.data.code === 200) {
      device.value = response.data.data
    } else {
      ElMessage.error(response.data.message || '获取设备详情失败')
    }
  } catch (error) {
    console.error('获取设备详情失败:', error)
    ElMessage.error('获取设备详情失败')
  } finally {
    loading.value = false
  }
}

const viewUsageRecords = () => {
  if (device.value) {
    router.push({
      name: 'DeviceUsageRecords',
      query: { deviceCode: device.value.deviceCode, deviceId: device.value.id }
    })
  }
}

const editDevice = () => {
  router.push({ name: 'DeviceEdit', params: { id: deviceId } })
}

const deleteDevice = async () => {
  try {
    await request.delete(`/api/devices/${deviceId}`)
    ElMessage.success('设备删除成功')
    goBack()
  } catch (error) {
    console.error('删除设备失败:', error)
    ElMessage.error('删除设备失败')
  }
}

const goBack = () => {
  router.push({ name: 'DeviceManagement' })
}

const viewEmployee = (employeeId) => {
  router.push({ name: 'EmployeeDetail', params: { id: employeeId } })
}

const unassignDevice = async () => {
  try {
    const response = await request.delete(`/api/devices/${deviceId}/employee`)
    if (response.data.code === 200) {
      ElMessage.success('设备分配已解除')
      fetchDevice()
    } else {
      ElMessage.error(response.data.message || '解除设备分配失败')
    }
  } catch (error) {
    console.error('解除设备分配失败:', error)
    ElMessage.error('解除设备分配失败')
  }
}

const fetchCollectionRecords = async () => {
  if (!device.value?.deviceCode) return
  collectionLoading.value = true
  try {
    const response = await request.get('/api/detection/tasks/by-device', {
      params: { deviceName: device.value.deviceCode, page: 1, size: 50 }
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
  await fetchDevice()
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
