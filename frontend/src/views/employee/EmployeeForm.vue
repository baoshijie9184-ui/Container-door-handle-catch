<template>
  <div class="page-shell form-page managed-form-page">
    <PageHero :title="isEdit ? '编辑人员' : '新增人员'" description="维护业务人员登记、部门与岗位。登录账号及权限在账号与组织页面单独管理。" icon="User">
      <template #actions><el-button @click="goBack"><AppIcon name="ArrowLeft" :size="16" />返回列表</el-button></template>
    </PageHero>
    <section class="managed-form-surface app-panel">
      <ManagedFormFeedback :phase="phase" :dirty="dirty" :loaded="loaded" :is-edit="isEdit" :resource-id="employeeId" :version="employeeForm.version" :receipt="receipt" :permission-error="permissionError" :load-error="loadError" :save-error="saveError" :validation-error="validationError" :lookup-notice="lookupNotice" :can-reload="supervisor && isEdit && !!employeeId" @reload="reload" />
      <div class="managed-department-state"><el-alert v-if="departmentError" :title="departmentError" type="error" show-icon :closable="false" /><el-button v-if="departmentError" size="small" :loading="departmentLoading" :disabled="loading || !supervisor" @click="loadDepartments"><AppIcon name="Refresh" :size="14" />重新读取部门</el-button></div>
      <el-form id="employee-maintenance-form" ref="formRef" :model="employeeForm" :rules="rules" label-position="top" scroll-to-error :disabled="disabled" @submit.prevent="submitForm">
        <section class="managed-form-section" aria-labelledby="employee-identity-heading">
          <div class="managed-form-section-heading"><AppIcon name="User" :size="19" /><div><h2 id="employee-identity-heading">身份与联系方式</h2><p>员工编号用于识别业务人员；登记姓名不作为账号授权依据。</p></div></div>
          <div class="device-form-grid">
            <el-form-item label="姓名" prop="name"><el-input v-model="employeeForm.name" placeholder="填写业务人员姓名" maxlength="20" show-word-limit /></el-form-item>
            <el-form-item label="员工编号" prop="employeeNumber"><el-input v-model="employeeForm.employeeNumber" placeholder="填写员工登记编号" aria-describedby="employee-number-help" /><p id="employee-number-help" class="managed-field-help">编号是否重复以保存时的服务端校验为准。</p></el-form-item>
            <el-form-item label="联系方式" prop="contact"><el-input v-model="employeeForm.contact" placeholder="填写手机号或邮箱" autocomplete="off" aria-describedby="employee-contact-help" /><p id="employee-contact-help" class="managed-field-help">用于业务联系，不会创建登录账号。</p></el-form-item>
            <el-form-item label="性别"><el-select v-model="employeeForm.gender" placeholder="选择已登记性别"><el-option label="男" value="男" /><el-option label="女" value="女" /></el-select></el-form-item>
          </div>
        </section>
        <section class="managed-form-section" aria-labelledby="employee-position-heading">
          <div class="managed-form-section-heading"><AppIcon name="Collection" :size="19" /><div><h2 id="employee-position-heading">部门与业务岗位</h2><p>业务岗位参与设备分配校验，不授予登录角色或主管权限。</p></div></div>
          <div class="device-form-grid">
            <el-form-item label="部门 / 班组" prop="departmentId"><el-select v-model="departmentModel" :disabled="departmentLoading || !departmentsLoaded || !!departmentError" :loading="departmentLoading" filterable placeholder="选择已有部门或班组"><el-option v-if="departmentModel && !departments.some(item=>resourceId(item.id)===departmentModel)" :value="departmentModel" :label="`原登记 ${employeeForm.department || departmentModel}（待核对）`" disabled /><el-option v-for="item in departments" :key="item.id" :label="item.name || '部门名称未记录'" :value="resourceId(item.id)" /></el-select><p class="managed-field-help">{{ departmentLoading ? '正在读取部门' : departmentsLoaded ? `本次读取 ${departments.length} 项，搜索仅在已读取项内进行` : '部门候选尚未读取' }}<router-link v-if="supervisor" :to="{name:'organization'}">维护部门</router-link></p></el-form-item>
            <el-form-item label="人员业务岗位" prop="employeeType"><el-select v-model="employeeForm.employeeType" placeholder="选择业务岗位"><el-option v-for="item in employeeTypeOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
            <el-form-item label="入职日期"><el-date-picker v-model="employeeForm.hireDate" type="date" placeholder="选择入职日期" format="YYYY-MM-DD" value-format="YYYY-MM-DD" /><p class="managed-field-help">保存日历日期，不按时区转换日期。</p></el-form-item>
            <el-form-item label="在岗状态" prop="status"><el-select v-model="employeeForm.status" placeholder="选择在岗状态"><el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select><p class="managed-field-help">已有分配设备时，改为非在岗状态需先完成设备归还。</p></el-form-item>
          </div>
        </section>
        <section class="managed-form-section" aria-labelledby="employee-note-heading"><div class="managed-form-section-heading"><AppIcon name="Document" :size="19" /><div><h2 id="employee-note-heading">补充说明</h2><p>当前接口不会持久保存备注，请勿用于重要交接。</p></div></div><el-form-item label="备注（当前不持久保存）"><el-input v-model="employeeForm.remark" type="textarea" :rows="3" placeholder="临时填写内容不会保存在人员档案中" /></el-form-item></section>
      </el-form>
        <div class="managed-form-actions"><p>{{ saved ? '资料已保存，可返回列表核对' : uncertain ? '保存结果待核对，请勿再次提交' : dirty ? '当前修改尚未保存' : '确认人员资料后保存' }}</p><div><el-button v-if="isEdit" :disabled="loading || !supervisor || !employeeId" @click="reload"><AppIcon name="Refresh" :size="15" />重新读取</el-button><el-button :disabled="loading || uncertain || saved || !loaded || !!permissionError" @click="reset"><AppIcon name="Refresh" :size="15" />{{ isEdit ? '恢复已读取内容' : '恢复初始值' }}</el-button><el-button type="primary" native-type="submit" form="employee-maintenance-form" :loading="phase==='SAVING' || phase==='VALIDATING'" :disabled="!canSubmit || departmentLoading || !departmentsLoaded || !!departmentError"><AppIcon name="CircleCheck" :size="16" />{{ saved ? '已保存' : '保存人员' }}</el-button></div></div>

    </section>
  </div>
</template>
<script setup>
import { ref,computed,watch,onBeforeUnmount } from 'vue'
import request from '../../api/request'
import { beijingDateTime } from '../../utils/beijingTime'
import { useManagedForm } from '../../composables/useManagedForm'
import ManagedFormFeedback from '../../components/ManagedFormFeedback.vue'
const formRef=ref(null)
const {form:employeeForm,id:employeeId,isEdit,actor,supervisor,phase,loading,loaded,permissionError,loadError,saveError,validationError,lookupNotice,receipt,uncertain,saved,dirty,disabled,canSubmit,reload,reset,submit,goBack,uniqueValidator}=useManagedForm({
  endpoint:'/api/employees',listRoute:'employees',label:'人员',formRef,
  defaults:()=>({version:null,name:'',employeeNumber:'',contact:'',gender:'男',department:'',departmentId:null,employeeType:'',hireDate:beijingDateTime().slice(0,10),status:'ACTIVE',remark:''})
})
const resourceId=value=>typeof value==='number' && Number.isSafeInteger(value) && value>0 ? String(value) : typeof value==='string' && /^[1-9]\d*$/.test(value) ? value : ''
const departments=ref([]),departmentLoading=ref(false),departmentsLoaded=ref(false),departmentError=ref('')
let departmentVersion=0,pageActive=true
const departmentModel=computed({get:()=>resourceId(employeeForm.departmentId),set:value=>{employeeForm.departmentId=value || null;const department=departments.value.find(item=>resourceId(item.id)===value);if(department)employeeForm.department=department.name}})
const validateEmployeeNumber=uniqueValidator('employeeNumber','/api/employees/check-number','employeeNumber','该员工编号')
const validateDepartment=(_rule,value,callback)=>{
  if(!value)return callback()
  if(!departmentsLoaded.value || departmentError.value)return callback(new Error('请先重新读取部门候选'))
  callback(departments.value.some(item=>resourceId(item.id)===resourceId(value))?undefined:new Error('原部门不在当前候选中，请核对后重新选择'))
}
async function loadDepartments(){
  if(!pageActive || !supervisor.value || departmentLoading.value || phase.value==='SAVING' || phase.value==='VALIDATING')return
  const version=++departmentVersion,stamp=actor.value
  departmentLoading.value=true;departmentError.value='';departmentsLoaded.value=false;departments.value=[]
  const current=()=>pageActive && departmentVersion===version && actor.value===stamp
  try{
    const response=await request.get('/api/organization/departments')
    if(!current())return
    if(response.data?.code!==200 || !Array.isArray(response.data.data))throw new Error(response.data?.message || '部门候选未完整读取')
    const ids=new Set()
    for(const row of response.data.data){const key=resourceId(row?.id);if(!key || ids.has(key))throw new Error('部门编号未完整读取');ids.add(key)}
    departments.value=response.data.data;departmentsLoaded.value=true
  }catch(error){if(current())departmentError.value=error.response?.data?.message || error.message || '部门暂不可读取，已有表单输入保留'}
  finally{if(current())departmentLoading.value=false}
}
const submitForm=()=>{
  if(departmentLoading.value || !departmentsLoaded.value || departmentError.value)return
  return submit()
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
  departmentId: [
    { required: true, message: '请选择部门/班组', trigger: 'change' },
    { validator: validateDepartment, trigger: 'change' }
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


watch(actor,()=>{departmentVersion++;departmentLoading.value=false;departmentsLoaded.value=false;departments.value=[];departmentError.value='';if(supervisor.value)loadDepartments()},{immediate:true,flush:'sync'})
onBeforeUnmount(()=>{pageActive=false;departmentVersion++})
</script>
