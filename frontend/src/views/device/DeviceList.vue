<template>
  <div class="page-shell device-page">
    <section class="page-hero">
      <div>
        <span class="page-hero-label">Device Center</span>
        <h1 class="page-hero-title">设备管理</h1>
        <p class="page-hero-text">
          集中查看采集设备、检测设备、维护状态与当前使用人，提升现场调度效率。
        </p>
      </div>

      <div class="panel-actions">
        <el-button v-if="isSupervisor" type="primary" @click="createDevice">新增设备</el-button>
      </div>
    </section>

    <!-- 统计摘要 — 单独请求全量数据确保准确 -->
    <section v-if="!statsLoading" class="stats-bar">
      <div class="stats-bar-item">
        <div class="stats-bar-icon primary">
          <span style="font-size:20px;font-weight:700">{{ statsTotal }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ statsTotal }}</div>
          <div class="stats-bar-label">设备总数</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon success">
          <span style="font-size:20px;font-weight:700">{{ statsInUse }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ statsInUse }}</div>
          <div class="stats-bar-label">使用中</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon warning">
          <span style="font-size:20px;font-weight:700">{{ statsMaintenance }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ statsMaintenance }}</div>
          <div class="stats-bar-label">维护中</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon danger">
          <span style="font-size:20px;font-weight:700">{{ statsUnused }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ statsUnused }}</div>
          <div class="stats-bar-label">未使用</div>
        </div>
      </div>
    </section>

    <section class="toolbar-panel">
      <div class="toolbar-grid device-filter-grid">
        <el-input v-model="filters.deviceCode" placeholder="设备编号" clearable />
        <el-select v-model="filters.deviceType" placeholder="设备类型" clearable>
          <el-option
            v-for="item in deviceTypeOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <el-input v-model="filters.modelName" placeholder="设备型号" clearable />
        <el-input v-model="filters.serialNumber" placeholder="序列号" clearable />
        <el-select v-model="filters.status" placeholder="设备状态" clearable>
          <el-option
            v-for="item in statusOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <div class="panel-actions">
          <el-button type="primary" @click="fetchDevices">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </div>
      </div>
    </section>

    <section class="table-panel">
      <el-table :data="devices" v-loading="loading" border style="width: 100%">
        <template #empty>
          <el-empty :description="hasFilters ? '没有匹配的设备，请调整筛选条件' : '暂无设备数据，点击上方按钮新增'" :image-size="80" />
        </template>
        <el-table-column prop="deviceCode" label="设备编号" min-width="120" />
        <el-table-column label="设备类型" min-width="110">
          <template #default="{ row }">
            {{ getDeviceTypeName(row.deviceType) }}
          </template>
        </el-table-column>
        <el-table-column prop="modelName" label="设备型号" min-width="140" show-overflow-tooltip />
        <el-table-column prop="serialNumber" label="序列号" min-width="150" show-overflow-tooltip />
        <el-table-column label="设备状态" min-width="90">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" effect="plain">
              {{ getStatusName(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="当前使用员工" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.status === 'UNUSED' || row.status === 'NOT_IN_USE'">暂无</span>
            <span v-else-if="row.employee">{{ row.employee.employeeNumber || row.employee.name }}</span>
            <span v-else>暂无</span>
          </template>
        </el-table-column>
        <el-table-column label="最后维护时间" min-width="150">
          <template #default="{ row }">
            {{ row.lastMaintenanceDate ? formatDate(row.lastMaintenanceDate) : '暂无记录' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="260" fixed="right">
          <template #default="{ row }">
            <div class="operation-buttons">
              <el-button size="small" @click="viewDevice(row.id)">
                工作详情
              </el-button>
              <el-button size="small" type="success" @click="viewDeviceUsageRecords(row)">
                使用记录
              </el-button>
              <el-button v-if="isSupervisor" size="small" type="primary" @click="editDevice(row.id)">
                编辑
              </el-button>
              <el-popconfirm v-if="isSupervisor" title="确定删除该设备吗？" @confirm="deleteDevice(row.id)">
                <template #reference>
                  <el-button size="small" type="danger">删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="total > 0" class="page-footer">
        <el-pagination
          v-model:current-page="pagination.current"
          v-model:page-size="pagination.size"
          :page-sizes="[10, 20, 30, 50]"
          :pager-count="7"
          background
          layout="total, sizes, prev, pager, next, jumper"
          :total="total"
          @size-change="handleSizeChange"
          @current-change="handleCurrentChange"
        />
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {beijingDateTime} from '@/utils/beijingTime'
import { ElMessage } from 'element-plus'

import request from '../../api/request'
import { useUserStore } from '../../stores/user'

const router = useRouter()
const userStore = useUserStore()
const isSupervisor = computed(() => ['SUPERVISOR', 'ADMIN'].includes(String(userStore.role || '').toUpperCase()))
const devices = ref([])
const loading = ref(false)
const total = ref(0)

// 统计数据 — 单独请求全量数据
const statsLoading = ref(true)
const statsTotal = ref(0)
const statsInUse = ref(0)
const statsOnline = ref(0)
const statsMaintenance = ref(0)
const statsUnused = ref(0)

function matchStatus(status, keywords) {
  const v = String(status || '').toUpperCase()
  return keywords.some(k => v.includes(String(k).toUpperCase()))
}

async function fetchDeviceStats() {
  try {
    const response = await request.get('/api/devices/stats')
    if (response.data.code === 200) {
      const stats = response.data.data || {}
      statsTotal.value = Number(stats.total || 0)
      statsInUse.value = Number(stats.inUse || 0)
      statsOnline.value = Number(stats.inUse || 0)
      statsMaintenance.value = Number(stats.maintenance || 0)
      statsUnused.value = Number(stats.idle || 0)
    }
  } catch (e) {
    console.error('获取设备统计失败:', e)
  } finally {
    statsLoading.value = false
  }
}

const pagination = reactive({
  current: 1,
  size: 10
})

const filters = reactive({
  deviceCode: '',
  deviceType: '',
  modelName: '',
  serialNumber: '',
  status: ''
})

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

const hasFilters = computed(() => {
  return filters.deviceCode || filters.deviceType || filters.modelName || filters.serialNumber || filters.status
})

const getDeviceTypeName = (type) => {
  const option = deviceTypeOptions.find((opt) => opt.value === type)
  return option ? option.label : type
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

const getStatusType = (status) => {
  const typeMap = {
    IN_USE: 'success',
    '使用中': 'success',
    UNUSED: 'info',
    NOT_IN_USE: 'info',
    IDLE: 'info',
    '未使用': 'info',
    '空闲': 'info',
    MAINTENANCE: 'warning',
    '维护中': 'warning',
    OFFLINE: 'danger',
    '离线': 'danger'
  }
  return typeMap[status] || 'info'
}

const formatDate = value => value?beijingDateTime(value):''

const fetchDevices = async () => {
  loading.value = true
  try {
    const params = {
      page: pagination.current,
      size: pagination.size,
      ...filters
    }

    const response = await request.get('/api/devices', { params })

    if (response.data.code === 200) {
      const data = response.data.data
      devices.value = data.records || []
      total.value = data.total || 0
    } else {
      ElMessage.error(response.data.message || '获取设备列表失败')
    }
  } catch (error) {
    console.error('获取设备列表失败:', error)
    ElMessage.error('获取设备列表失败')
  } finally {
    loading.value = false
  }
}

const resetFilters = () => {
  filters.deviceCode = ''
  filters.deviceType = ''
  filters.modelName = ''
  filters.serialNumber = ''
  filters.status = ''
  pagination.current = 1
  fetchDevices()
}

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
  try {
    await request.delete(`/api/devices/${id}`)
    ElMessage.success('设备删除成功')
    fetchDevices()
  } catch (error) {
    console.error('删除设备失败:', error)
    ElMessage.error('删除设备失败')
  }
}

const handleSizeChange = (size) => {
  pagination.size = size
  pagination.current = 1
  fetchDevices()
}

const handleCurrentChange = (page) => {
  pagination.current = page
  fetchDevices()
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

.device-filter-grid {
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
}
</style>
