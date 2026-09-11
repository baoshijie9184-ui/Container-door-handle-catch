<template>
  <div class="page-shell usage-page">
    <section class="page-hero">
      <div>
        <span class="page-hero-label">Usage Records</span>
        <h1 class="page-hero-title">
          {{ deviceCodeFromRoute ? `设备 ${deviceCodeFromRoute} 使用记录` : '设备使用记录' }}
        </h1>
        <p class="page-hero-text">
          查看设备历史使用情况，包括使用人、使用时间和归还状态。
        </p>
      </div>
      <div class="panel-actions">
        <el-button v-if="deviceCodeFromRoute" @click="backToDeviceList">返回设备列表</el-button>
        <el-button type="primary" @click="createRecord">新增记录</el-button>
      </div>
    </section>

    <section class="toolbar-panel app-panel">
      <div class="toolbar-grid usage-filter-grid">
        <el-input v-model="filters.deviceCode" placeholder="设备编号" clearable />
        <el-input v-model="filters.employeeName" placeholder="员工姓名" clearable />
        <el-input v-model="filters.employeeNumber" placeholder="员工编号" clearable />
        <el-select v-model="filters.status" placeholder="使用状态" clearable>
          <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-date-picker
          v-model="filters.startTimeRange"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          value-format="YYYY-MM-DD HH:mm:ss"
          class="date-range-picker"
        />
        <div class="panel-actions">
          <el-button type="primary" @click="fetchRecords">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </div>
      </div>
    </section>

    <section class="table-panel">
      <el-table :data="records" v-loading="loading" border style="width: 100%">
        <template #empty>
          <el-empty :description="hasFilters ? '没有匹配的使用记录，请调整筛选条件' : '暂无设备使用记录'" :image-size="80" />
        </template>
        <el-table-column prop="deviceCode" label="设备编号" width="130" />
        <el-table-column label="设备类型" width="130">
          <template #default="{ row }">
            {{ getDeviceTypeName(row.deviceType) }}
          </template>
        </el-table-column>
        <el-table-column prop="modelName" label="设备型号" min-width="130" show-overflow-tooltip />
        <el-table-column prop="serialNumber" label="序列号" min-width="130" show-overflow-tooltip />
        <el-table-column prop="employeeName" label="员工姓名" width="100" />
        <el-table-column prop="employeeNumber" label="员工编号" width="120" />
        <el-table-column prop="contact" label="联系方式" min-width="130" show-overflow-tooltip />
        <el-table-column label="使用开始时间" min-width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.startTime) }}
          </template>
        </el-table-column>
        <el-table-column label="使用结束时间" min-width="180">
          <template #default="{ row }">
            {{ row.endTime ? formatDateTime(row.endTime) : '未归还' }}
          </template>
        </el-table-column>
        <el-table-column label="使用状态" width="110">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" effect="plain">
              {{ getStatusLabel(row.status) }}
            </el-tag>
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

    <!-- 新增记录弹窗 -->
    <el-dialog v-model="dialogVisible" title="新增设备使用记录" width="560px">
      <el-form :model="createForm" :rules="createRules" ref="createFormRef" label-width="100px">
        <el-form-item label="选择设备" prop="deviceId">
          <el-select v-model="createForm.deviceId" placeholder="请选择设备" style="width:100%" filterable>
            <el-option v-for="d in deviceOptions" :key="d.id" :label="`${d.deviceCode} - ${d.modelName}`" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="选择员工" prop="employeeId">
          <el-select v-model="createForm.employeeId" placeholder="请选择员工" style="width:100%" filterable>
            <el-option v-for="e in employeeOptions" :key="e.id" :label="`${e.name} (${e.employeeNumber})`" :value="e.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="开始时间" prop="startTime">
          <el-date-picker v-model="createForm.startTime" type="datetime" placeholder="选择开始时间" style="width:100%" value-format="YYYY-MM-DDTHH:mm:ss" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="createForm.remarks" type="textarea" placeholder="可选备注" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="createLoading" @click="handleCreate">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '../../api/request'
import { formatDate } from '@/utils/format'

const router = useRouter()
const route = useRoute()
const records = ref([])
const loading = ref(false)
const total = ref(0)

const deviceCodeFromRoute = ref(route.query.deviceCode || '')
const deviceIdFromRoute = ref(route.query.deviceId || '')

const pagination = reactive({ current: 1, size: 10 })

const filters = reactive({
  deviceCode: '',
  employeeName: '',
  employeeNumber: '',
  status: '',
  startTimeRange: []
})

if (deviceCodeFromRoute.value) {
  filters.deviceCode = deviceCodeFromRoute.value
}

const statusOptions = [
  { value: 'IN_USE', label: '使用中' },
  { value: 'RETURNED', label: '已归还' }
]

const hasFilters = computed(() => {
  return filters.deviceCode || filters.employeeName || filters.employeeNumber || filters.status || (filters.startTimeRange && filters.startTimeRange.length > 0)
})

const getDeviceTypeName = (type) => {
  if (type === 'DETECTION') return '图像检测设备'
  if (type === 'IMAGE_CAPTURE') return '图片采集设备'
  return type
}

const getStatusType = (status) => {
  if (status === 'IN_USE' || status === '使用中') return 'success'
  if (status === 'RETURNED' || status === '已归还') return 'info'
  return 'info'
}

const getStatusLabel = (status) => {
  if (status === 'IN_USE' || status === '使用中') return '使用中'
  if (status === 'RETURNED' || status === '已归还') return '已归还'
  return status
}

const formatDateTime = (dateTime) => {
  if (!dateTime) return ''
  return formatDate(new Date(dateTime), 'YYYY-MM-DD HH:mm:ss')
}

const handleSizeChange = (size) => {
  pagination.size = size
  pagination.current = 1
  fetchRecords()
}

const handleCurrentChange = (current) => {
  pagination.current = current
  fetchRecords()
}

const fetchRecords = () => {
  loading.value = true
  const params = {
    page: pagination.current,
    size: pagination.size,
    deviceId: deviceIdFromRoute.value || undefined,
    deviceCode: filters.deviceCode || undefined,
    employeeName: filters.employeeName || undefined,
    employeeNumber: filters.employeeNumber || undefined,
    status: filters.status || undefined
  }

  if (filters.startTimeRange && filters.startTimeRange.length === 2) {
    params.startTimeBegin = filters.startTimeRange[0]
    params.startTimeEnd = filters.startTimeRange[1]
  }

  request.get('/api/device-usage-records', { params })
    .then(response => {
      if (response.data.code === 200) {
        records.value = response.data.data.records || []
        total.value = response.data.data.total || 0
      } else {
        ElMessage.error(response.data.message || '获取使用记录失败')
      }
    })
    .catch(error => {
      console.error('获取使用记录失败:', error)
      ElMessage.error('获取使用记录失败')
    })
    .finally(() => { loading.value = false })
}

const resetFilters = () => {
  filters.deviceCode = deviceCodeFromRoute.value || ''
  filters.employeeName = ''
  filters.employeeNumber = ''
  filters.status = ''
  filters.startTimeRange = []
  fetchRecords()
}

const backToDeviceList = () => {
  router.push('/devices')
}

const dialogVisible = ref(false)
const createLoading = ref(false)
const createFormRef = ref(null)
const deviceOptions = ref([])
const employeeOptions = ref([])

const createForm = reactive({
  deviceId: null,
  employeeId: null,
  startTime: '',
  remarks: ''
})

const createRules = {
  deviceId: [{ required: true, message: '请选择设备', trigger: 'change' }],
  employeeId: [{ required: true, message: '请选择员工', trigger: 'change' }],
  startTime: [{ required: true, message: '请选择开始时间', trigger: 'change' }]
}

const createRecord = async () => {
  // 加载设备和员工选项
  try {
    const [devRes, empRes] = await Promise.all([
      request.get('/api/devices', { params: { page: 1, size: 999 } }),
      request.get('/api/employees', { params: { page: 1, size: 999 } })
    ])
    deviceOptions.value = devRes.data.data?.records || []
    employeeOptions.value = empRes.data.data?.records || []
  } catch { /* ignore */ }
  createForm.deviceId = deviceIdFromRoute.value ? Number(deviceIdFromRoute.value) : null
  createForm.employeeId = null
  createForm.startTime = ''
  createForm.remarks = ''
  dialogVisible.value = true
}

const handleCreate = async () => {
  if (!createFormRef.value) return
  try {
    await createFormRef.value.validate()
  } catch { return }

  createLoading.value = true
  try {
    const res = await request.post('/api/device-usage-records', createForm)
    if (res.data.code === 200) {
      ElMessage.success('记录创建成功')
      dialogVisible.value = false
      fetchRecords()
    } else {
      ElMessage.error(res.data.message || '创建失败')
    }
  } catch (e) {
    ElMessage.error('创建失败')
  } finally {
    createLoading.value = false
  }
}

onMounted(() => {
  fetchRecords()
})
</script>

<style scoped>
.usage-page {
  gap: 18px;
}

.usage-filter-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.usage-filter-grid .el-input,
.usage-filter-grid .el-select {
  width: 180px;
  max-width: 100%;
}

.date-range-picker {
  width: 360px;
  max-width: 100%;
}
</style>
