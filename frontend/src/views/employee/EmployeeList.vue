<template>
  <div class="page-shell employee-page">
    <section class="page-hero">
      <div>
        <span class="page-hero-label">Team Ops</span>
        <h1 class="page-hero-title">人员管理</h1>
        <p class="page-hero-text">
          管理采集、检测与维护岗位人员，并在同一界面完成设备分配与状态跟踪。
        </p>
      </div>

      <div class="panel-actions">
        <el-button v-if="isSupervisor" type="primary" @click="createEmployee">新增人员</el-button>
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
          <div class="stats-bar-label">人员总数</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon success">
          <span style="font-size:20px;font-weight:700">{{ statsActive }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ statsActive }}</div>
          <div class="stats-bar-label">在岗</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon warning">
          <span style="font-size:20px;font-weight:700">{{ statsVacation }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ statsVacation }}</div>
          <div class="stats-bar-label">休假</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon danger">
          <span style="font-size:20px;font-weight:700">{{ statsResigned }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ statsResigned }}</div>
          <div class="stats-bar-label">离职</div>
        </div>
      </div>
    </section>

    <section class="toolbar-panel">
      <div class="toolbar-grid employee-filter-grid">
        <el-input v-model="filters.name" placeholder="姓名" clearable />
        <el-input v-model="filters.employeeNumber" placeholder="员工编号" clearable />
        <el-input v-model="filters.contact" placeholder="联系方式" clearable />
        <el-input v-model="filters.department" placeholder="部门 / 班组" clearable />
        <el-select v-model="filters.employeeType" placeholder="人员类型" clearable>
          <el-option
            v-for="item in employeeTypeOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <el-select v-model="filters.status" placeholder="状态" clearable>
          <el-option
            v-for="item in statusOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <div class="panel-actions">
          <el-button type="primary" @click="fetchEmployees">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </div>
      </div>
    </section>

    <section class="table-panel">
      <el-table :data="employees" v-loading="loading" border style="width: 100%">
        <template #empty>
          <el-empty :description="hasFilters ? '没有匹配的人员，请调整筛选条件' : '暂无人员数据，点击上方按钮新增'" :image-size="80" />
        </template>
        <el-table-column prop="name" label="姓名" min-width="100" />
        <el-table-column prop="employeeNumber" label="员工编号" min-width="120" />
        <el-table-column prop="contact" label="联系方式" min-width="130" show-overflow-tooltip />
        <el-table-column prop="department" label="部门 / 班组" min-width="140" show-overflow-tooltip />
        <el-table-column label="人员类型" min-width="160">
          <template #default="{ row }">
            {{ getEmployeeTypeName(row.employeeType) }}
          </template>
        </el-table-column>
        <el-table-column prop="gender" label="性别" min-width="70" />
        <el-table-column label="状态" min-width="90">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" effect="plain">
              {{ getStatusName(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="入职日期" min-width="120">
          <template #default="{ row }">
            {{ row.hireDate || '暂无记录' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" fixed="right" min-width="280">
          <template #default="{ row }">
            <div class="operation-buttons">
              <el-button size="small" @click="viewEmployee(row.id)">
                工作详情
              </el-button>
              <el-button v-if="isSupervisor" size="small" type="primary" @click="editEmployee(row.id)">
                编辑
              </el-button>
              <el-button v-if="isSupervisor" size="small" type="success" @click="assignDevices(row.id)">
                分配设备
              </el-button>
              <el-popconfirm v-if="isSupervisor" title="确定删除该人员吗？" @confirm="deleteEmployee(row.id)">
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

    <el-dialog v-model="deviceDialog.visible" title="分配设备" width="680px">
      <div v-if="deviceDialog.visible" class="device-dialog-content">
        <div class="dialog-summary">
          <span>当前员工</span>
          <strong>{{ deviceDialog.employee?.name }}</strong>
        </div>

        <el-form label-width="90px">
          <el-form-item label="可选设备">
            <el-select v-model="deviceDialog.selectedDeviceId" placeholder="请选择设备" style="width: 100%">
              <el-option
                v-for="device in deviceDialog.deviceOptions"
                :key="device.id"
                :label="`${device.deviceCode} - ${device.modelName}`"
                :value="device.id"
              />
            </el-select>
          </el-form-item>
        </el-form>

        <h3 class="dialog-table-title">已分配设备</h3>

        <el-table :data="deviceDialog.assignedDevices" border>
          <el-table-column prop="deviceCode" label="设备编号" />
          <el-table-column label="设备类型">
            <template #default="{ row }">
              {{ row.deviceType === 'IMAGE_CAPTURE' ? '图片采集设备' : row.deviceType === 'DETECTION' ? '图像检测设备' : row.deviceType }}
            </template>
          </el-table-column>
          <el-table-column prop="modelName" label="设备型号" />
          <el-table-column label="状态">
            <template #default="{ row }">
              <el-tag :type="(row.status === 'IN_USE' || row.status === '使用中') ? 'success' : 'info'" size="small">
                {{ (row.status === 'IN_USE' || row.status === '使用中') ? '使用中' : (row.status === 'IDLE' || row.status === '未使用') ? '未使用' : row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130">
            <template #default="{ row }">
              <el-button size="small" type="danger" @click="unassignDevice(row.id)">
                解除分配
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <template #footer>
        <span class="dialog-footer">
          <el-button @click="deviceDialog.visible = false">取消</el-button>
          <el-button type="primary" @click="handleAssignDevice">确定</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import request from '../../api/request'
import { useUserStore } from '../../stores/user'

const router = useRouter()
const userStore = useUserStore()
const isSupervisor = computed(() => ['SUPERVISOR', 'ADMIN'].includes(String(userStore.role || '').toUpperCase()))
const employees = ref([])
const loading = ref(false)
const total = ref(0)

// 统计数据 — 单独请求全量数据
const statsLoading = ref(true)
const statsTotal = ref(0)
const statsActive = ref(0)
const statsVacation = ref(0)
const statsResigned = ref(0)

async function fetchEmployeeStats() {
  try {
    const response = await request.get('/api/employees/stats')
    if (response.data.code === 200) {
      const stats = response.data.data || {}
      statsTotal.value = Number(stats.total || 0)
      statsActive.value = Number(stats.active || 0)
      statsVacation.value = Number(stats.vacation || 0)
      statsResigned.value = Number(stats.resigned || 0)
    }
  } catch (e) {
    console.error('获取人员统计失败:', e)
  } finally {
    statsLoading.value = false
  }
}

const pagination = reactive({
  current: 1,
  size: 10
})

const filters = reactive({
  name: '',
  employeeNumber: '',
  contact: '',
  department: '',
  employeeType: '',
  status: ''
})

const deviceDialog = reactive({
  visible: false,
  employee: null,
  assignedDevices: [],
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

const hasFilters = computed(() => {
  return filters.name || filters.employeeNumber || filters.contact || filters.department || filters.employeeType || filters.status
})

const getEmployeeTypeName = (type) => {
  const typeMap = {
    DETECTION: '门把手检测人员',
    COLLECTION: '门把手图片采集人员',
    MAINTENANCE: '设备维护人员'
  }
  return typeMap[type] || type
}

const getStatusName = (status) => {
  const statusMap = {
    ACTIVE: '在岗',
    RESIGNED: '离职',
    VACATION: '休假'
  }
  return statusMap[status] || status
}

const getStatusType = (status) => {
  const statusMap = {
    ACTIVE: 'success',
    RESIGNED: 'danger',
    VACATION: 'warning'
  }
  return statusMap[status] || 'info'
}

const fetchEmployees = async () => {
  loading.value = true
  try {
    const params = { page: pagination.current, size: pagination.size }

    if (filters.name) params.name = filters.name
    if (filters.employeeNumber) params.employeeNumber = filters.employeeNumber
    if (filters.contact) params.contact = filters.contact
    if (filters.department) params.department = filters.department
    if (filters.employeeType) params.employeeType = filters.employeeType
    if (filters.status) params.status = filters.status

    const response = await request.get('/api/employees', { params })
    const result = response.data

    if (result.code === 200) {
      const pageData = result.data
      employees.value = pageData.records || []
      total.value = pageData.total || 0
    } else {
      ElMessage.error(result.message || '获取人员列表失败')
      employees.value = []
      total.value = 0
    }

    if (employees.value.length === 0 && pagination.current > 1) {
      pagination.current = 1
      fetchEmployees()
    }
  } catch (error) {
    console.error('获取人员列表失败:', error)
    ElMessage.error('获取人员列表失败')
    employees.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

const resetFilters = () => {
  filters.name = ''
  filters.employeeNumber = ''
  filters.contact = ''
  filters.department = ''
  filters.employeeType = ''
  filters.status = ''
  pagination.current = 1
  fetchEmployees()
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
  try {
    const response = await request.delete(`/api/employees/${id}`)
    if (response.data.code === 200) {
      ElMessage.success('人员删除成功')
      fetchEmployees()
    } else {
      ElMessage.error(response.data.message || '删除人员失败')
    }
  } catch (error) {
    console.error('删除人员失败:', error)
    ElMessage.error('删除人员失败')
  }
}

const assignDevices = async (employeeId) => {
  try {
    const employeeResponse = await request.get(`/api/employees/${employeeId}`)
    if (employeeResponse.data.code === 200) {
      deviceDialog.employee = employeeResponse.data.data
    } else {
      ElMessage.error(employeeResponse.data.message || '获取人员信息失败')
      return
    }

    const devicesResponse = await request.get(`/api/employees/${employeeId}/devices`)
    if (devicesResponse.data.code === 200) {
      deviceDialog.assignedDevices = devicesResponse.data.data || []
    } else {
      ElMessage.error(devicesResponse.data.message || '获取已分配设备失败')
      return
    }

    const unassignedResponse = await request.get('/api/devices/unassigned')
    if (unassignedResponse.data.code === 200) {
      deviceDialog.deviceOptions = unassignedResponse.data.data || []
      if (deviceDialog.deviceOptions.length === 0) {
        ElMessage.warning('当前没有可分配设备')
      }
    } else {
      ElMessage.error(unassignedResponse.data.message || '获取可分配设备失败')
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
    ElMessage.warning('请选择设备')
    return
  }

  try {
    const response = await request.post(
      `/api/employees/${deviceDialog.employee.id}/assign-device/${deviceDialog.selectedDeviceId}`
    )

    if (response.data.code === 200) {
      ElMessage.success('设备分配成功')
      deviceDialog.visible = false
      fetchEmployees()
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
      ElMessage.success('已解除设备分配')

      const devicesResponse = await request.get(`/api/employees/${deviceDialog.employee.id}/devices`)
      if (devicesResponse.data.code === 200) {
        deviceDialog.assignedDevices = devicesResponse.data.data || []
      }

      try {
        const unassignedResponse = await request.get('/api/devices/unassigned')
        if (unassignedResponse.data.code === 200) {
          deviceDialog.deviceOptions = unassignedResponse.data.data || []
        }
      } catch (err) {
        console.error('刷新可分配设备失败:', err)
      }
    } else {
      ElMessage.error(response.data.message || '解除设备分配失败')
    }
  } catch (error) {
    console.error('解除设备分配失败:', error)
    ElMessage.error('解除设备分配失败')
  }
}

const handleSizeChange = (size) => {
  pagination.size = size
  pagination.current = 1
  fetchEmployees()
}

const handleCurrentChange = (page) => {
  pagination.current = page
  fetchEmployees()
}

onMounted(() => {
  fetchEmployees()
  fetchEmployeeStats()
})
</script>

<style scoped>
.employee-page {
  gap: 18px;
}

.employee-filter-grid {
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
}

.device-dialog-content {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.dialog-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(45, 140, 255, 0.1), rgba(16, 185, 129, 0.08));
  color: #334155;
}

.dialog-summary span {
  color: #64748b;
  font-size: 13px;
}

.dialog-summary strong {
  color: #0f172a;
  font-size: 15px;
}

.dialog-table-title {
  margin: 0;
  color: #0f172a;
  font-size: 16px;
}
</style>
