<template>
  <div class="page-shell form-page">
    <section class="page-hero">
      <div>
        <span class="page-hero-label">{{ isEdit ? 'Edit Employee' : 'New Employee' }}</span>
        <h1 class="page-hero-title">{{ isEdit ? '编辑人员' : '新增人员' }}</h1>
        <p class="page-hero-text">
          {{ isEdit ? '修改人员信息，更新岗位、状态和联系方式。' : '添加新人员到系统，填写基本信息后即可分配设备和任务。' }}
        </p>
      </div>
      <el-button @click="goBack">返回列表</el-button>
    </section>

    <el-card v-loading="loading">
      <el-form
        ref="formRef"
        :model="employeeForm"
        :rules="rules"
        label-width="100px"
      >
        <el-row :gutter="24">
          <el-col :span="12">
            <el-form-item label="姓名" prop="name">
              <el-input v-model="employeeForm.name" placeholder="请输入员工姓名" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="员工编号" prop="employeeNumber">
              <el-input v-model="employeeForm.employeeNumber" placeholder="请输入员工编号" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="24">
          <el-col :span="12">
            <el-form-item label="联系方式" prop="contact">
              <el-input v-model="employeeForm.contact" placeholder="请输入联系方式" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="性别">
              <el-select v-model="employeeForm.gender" placeholder="请选择性别" style="width: 100%">
                <el-option label="男" value="男" />
                <el-option label="女" value="女" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="24">
          <el-col :span="12">
            <el-form-item label="部门/班组" prop="department">
              <el-input v-model="employeeForm.department" placeholder="请输入部门/班组" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="人员类型" prop="employeeType">
              <el-select v-model="employeeForm.employeeType" placeholder="请选择人员类型" style="width: 100%">
                <el-option v-for="item in employeeTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="24">
          <el-col :span="12">
            <el-form-item label="入职日期">
              <el-date-picker
                v-model="employeeForm.hireDate"
                type="date"
                placeholder="请选择入职日期"
                format="YYYY-MM-DD"
                value-format="YYYY-MM-DD"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="状态" prop="status">
              <el-select v-model="employeeForm.status" placeholder="请选择状态" style="width: 100%">
                <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="备注">
          <el-input v-model="employeeForm.remark" type="textarea" :rows="3" placeholder="请输入备注信息（选填）" />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="submitForm">保存</el-button>
          <el-button @click="goBack">取消</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute, onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../../api/request'
import { useUserStore } from '../../stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const formRef = ref()
const loading = ref(false)
const formChanged = ref(false)

const isEdit = computed(() => !!route.params.id)

const employeeForm = reactive({
  version: null,
  name: '',
  employeeNumber: '',
  contact: '',
  gender: '男',
  department: '',
  employeeType: '',
  hireDate: new Date().toISOString().split('T')[0],
  status: 'ACTIVE',
  remark: ''
})

const employeeId = route.params.id

const validateEmployeeNumber = async (rule, value, callback) => {
  if (!value) return
  try {
    const res = await request.get('/api/employees/check-number', {
      params: { employeeNumber: value, excludeId: employeeId || undefined }
    })
    if (res.data.code === 200 && res.data.data) {
      callback(new Error('该员工编号已存在'))
    } else {
      callback()
    }
  } catch {
    callback()
  }
}

const validateContact = (rule, value, callback) => {
  if (!value) return callback()
  const phoneReg = /^1[3-9]\d{9}$/
  const emailReg = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  if (phoneReg.test(value) || emailReg.test(value)) {
    callback()
  } else {
    callback(new Error('请输入正确的手机号或邮箱'))
  }
}

const rules = {
  name: [
    { required: true, message: '请输入员工姓名', trigger: 'blur' },
    { min: 2, max: 20, message: '长度在 2 到 20 个字符', trigger: 'blur' }
  ],
  employeeNumber: [
    { required: true, message: '请输入员工编号', trigger: 'blur' },
    { validator: validateEmployeeNumber, trigger: 'blur' }
  ],
  contact: [
    { required: true, message: '请输入联系方式', trigger: 'blur' },
    { validator: validateContact, trigger: 'blur' }
  ],
  department: [
    { required: true, message: '请输入部门/班组', trigger: 'blur' }
  ],
  employeeType: [
    { required: true, message: '请选择人员类型', trigger: 'change' }
  ],
  status: [
    { required: true, message: '请选择状态', trigger: 'change' }
  ]
}

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

const fetchEmployeeDetail = async () => {
  if (!isEdit.value) return
  loading.value = true
  try {
    const response = await request.get(`/api/employees/${route.params.id}`)
    const employee = response.data.data
    employeeForm.name = employee.name
    employeeForm.employeeNumber = employee.employeeNumber
    employeeForm.contact = employee.contact
    employeeForm.gender = employee.gender
    employeeForm.department = employee.department
    employeeForm.employeeType = employee.employeeType
    employeeForm.hireDate = employee.hireDate
    employeeForm.status = employee.status
    employeeForm.remark = employee.remark
    employeeForm.version = employee.version
  } catch (error) {
    console.error('获取员工详情失败:', error)
    ElMessage.error('获取员工详情失败')
  } finally {
    loading.value = false
  }
}

const goBack = () => {
  router.push({ name: 'employees' })
}

const submitForm = async () => {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) {
      ElMessage.error('请完善表单信息')
      return
    }
    loading.value = true
    try {
      if (isEdit.value) {
        const response = await request.put(`/api/employees/${route.params.id}`, employeeForm)
        if (response.data?.code !== 200) throw new Error(response.data?.message || '员工信息更新失败')
        ElMessage.success('员工信息更新成功')
      } else {
        const response = await request.post('/api/employees', employeeForm)
        if (response.data?.code !== 200) throw new Error(response.data?.message || '员工添加失败')
        ElMessage.success('员工添加成功')
      }
      formChanged.value = false
      router.push({ name: 'employees' })
    } catch (error) {
      console.error('保存员工信息失败:', error)
      ElMessage.error(error.response?.data?.message || error.message || '保存员工信息失败')
    } finally {
      loading.value = false
    }
  })
}

onMounted(async () => {
  if (!userStore.hasCheckedAuth) await userStore.checkAuth()
  if (!['SUPERVISOR', 'ADMIN'].includes(String(userStore.role || '').toUpperCase())) {
    ElMessage.warning('仅主管可以维护员工资料')
    formChanged.value = false
    return goBack()
  }
  await fetchEmployeeDetail()
})

// 监听表单变化
watch(employeeForm, () => { formChanged.value = true }, { deep: true })

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

@media (max-width: 768px) {
  .el-col-12 {
    flex: 0 0 100%;
    max-width: 100%;
  }
}
</style>
