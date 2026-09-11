<template>
  <div class="page-shell form-page">
    <section class="page-hero">
      <div>
        <span class="page-hero-label">{{ isEdit ? 'Edit Device' : 'New Device' }}</span>
        <h1 class="page-hero-title">{{ isEdit ? '编辑设备' : '新增设备' }}</h1>
        <p class="page-hero-text">
          {{ isEdit ? '修改设备信息，更新状态和维护记录。' : '注册新设备到系统，填写基本信息后即可投入使用。' }}
        </p>
      </div>
      <el-button @click="goBack">返回列表</el-button>
    </section>

    <el-card v-loading="loading">
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="120px"
        class="device-form"
      >
        <el-form-item label="设备编号" prop="deviceCode">
          <el-input v-model="form.deviceCode" placeholder="请输入设备编号" />
        </el-form-item>

        <el-form-item label="设备类型" prop="deviceType">
          <el-select v-model="form.deviceType" placeholder="请选择设备类型" style="width: 100%">
            <el-option v-for="item in deviceTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>

        <el-form-item label="设备型号" prop="modelName">
          <el-input v-model="form.modelName" placeholder="请输入设备型号" />
        </el-form-item>

        <el-form-item label="序列号" prop="serialNumber">
          <el-input v-model="form.serialNumber" placeholder="请输入序列号" />
        </el-form-item>

        <el-form-item label="设备状态" prop="status">
          <el-select v-model="form.status" placeholder="请选择设备状态" style="width: 100%">
            <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>

        <el-form-item label="维护日期" prop="lastMaintenanceDate">
          <el-date-picker
            v-model="form.lastMaintenanceDate"
            type="datetime"
            placeholder="选择最后维护日期"
            style="width: 100%"
            value-format="YYYY-MM-DDTHH:mm:ss"
          />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="submitForm(formRef)">保存</el-button>
          <el-button @click="resetForm(formRef)">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter, useRoute, onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../../api/request'
import { useUserStore } from '../../stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const deviceId = route.params.id
const formRef = ref(null)
const loading = ref(false)
const formChanged = ref(false)

const isEdit = computed(() => Boolean(deviceId))

const form = reactive({
  version: null,
  deviceCode: '',
  deviceType: '',
  modelName: '',
  serialNumber: '',
  status: '',
  lastMaintenanceDate: null
})

const validateDeviceCode = async (rule, value, callback) => {
  if (!value || value.length < 4) return
  try {
    const res = await request.get('/api/devices/check-code', {
      params: { deviceCode: value, excludeId: deviceId || undefined }
    })
    if (res.data.code === 200 && res.data.data) {
      callback(new Error('该设备编号已存在'))
    } else {
      callback()
    }
  } catch {
    callback()
  }
}

const rules = {
  deviceCode: [
    { required: true, message: '请输入设备编号', trigger: 'blur' },
    { min: 4, max: 20, message: '长度在 4 到 20 个字符', trigger: 'blur' },
    { validator: validateDeviceCode, trigger: 'blur' }
  ],
  deviceType: [
    { required: true, message: '请选择设备类型', trigger: 'change' }
  ],
  modelName: [
    { required: true, message: '请输入设备型号', trigger: 'blur' }
  ],
  serialNumber: [
    { required: true, message: '请输入序列号', trigger: 'blur' }
  ],
  status: [
    { required: true, message: '请选择设备状态', trigger: 'change' }
  ]
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

const fetchDevice = async () => {
  if (!isEdit.value) return
  loading.value = true
  try {
    const response = await request.get(`/api/devices/${deviceId}`)
    const deviceData = response.data.data
    if (deviceData) {
      Object.assign(form, deviceData)
    } else {
      ElMessage.error('未找到设备信息')
      goBack()
    }
  } catch (error) {
    console.error('获取设备详情失败:', error)
    ElMessage.error('获取设备详情失败')
    goBack()
  } finally {
    loading.value = false
  }
}

const submitForm = async (formEl) => {
  if (!formEl) return
  await formEl.validate(async (valid) => {
    if (valid) {
      loading.value = true
      try {
        let response
        if (isEdit.value) {
          response = await request.put(`/api/devices/${deviceId}`, form)
        } else {
          response = await request.post('/api/devices', form)
        }
        if (response.data && response.data.code === 200) {
          ElMessage.success(isEdit.value ? '设备更新成功' : '设备创建成功')
          formChanged.value = false
          goBack()
        } else {
          ElMessage.error(response.data.message || (isEdit.value ? '更新失败' : '创建失败'))
        }
      } catch (error) {
        console.error(isEdit.value ? '更新失败:' : '创建失败:', error)
        ElMessage.error(error.response?.data?.message || (isEdit.value ? '更新设备失败，请刷新后重试' : '创建设备失败'))
      } finally {
        loading.value = false
      }
    }
  })
}

const resetForm = (formEl) => {
  if (!formEl) return
  formEl.resetFields()
  if (isEdit.value) fetchDevice()
}

const goBack = () => {
  router.push({ name: 'devices' })
}

onMounted(async () => {
  if (!userStore.hasCheckedAuth) await userStore.checkAuth()
  if (!['SUPERVISOR', 'ADMIN'].includes(String(userStore.role || '').toUpperCase())) {
    ElMessage.warning('仅主管可以维护设备资料')
    formChanged.value = false
    return goBack()
  }
  await fetchDevice()
})

// 监听表单变化
import { watch } from 'vue'
watch(form, () => { formChanged.value = true }, { deep: true })

// 离开页面前确认
onBeforeRouteLeave(async (to, from, next) => {
  if (!formChanged.value) return next()
  try {
    await ElMessageBox.confirm('表单已修改但未保存，确定要离开吗？', '提示', {
      confirmButtonText: '确定离开',
      cancelButtonText: '取消',
      type: 'warning'
    })
    next()
  } catch {
    next(false)
  }
})
</script>

<style scoped>
.form-page {
  gap: 18px;
}

.device-form {
  max-width: 640px;
  margin: 0 auto;
}
</style>
