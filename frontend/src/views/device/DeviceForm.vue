<template>
  <div class="page-shell form-page managed-form-page">
    <PageHero :title="isEdit ? '编辑设备' : '新增设备'" description="维护设备登记与业务状态。设备分配、实时心跳和检测任务分别管理。" icon="Monitor">
      <template #actions><el-button @click="goBack"><AppIcon name="ArrowLeft" :size="16" />返回列表</el-button></template>
    </PageHero>
    <section class="managed-form-surface app-panel">
      <ManagedFormFeedback :phase="phase" :dirty="dirty" :loaded="loaded" :is-edit="isEdit" :resource-id="deviceId" :version="form.version" :receipt="receipt" :permission-error="permissionError" :load-error="loadError" :save-error="saveError" :validation-error="validationError" :lookup-notice="lookupNotice" :can-reload="supervisor && isEdit && !!deviceId" @reload="reload" />
      <el-form id="device-maintenance-form" ref="formRef" :model="form" :rules="rules" label-position="top" scroll-to-error :disabled="disabled" @submit.prevent="submit">
        <section class="managed-form-section" aria-labelledby="device-identity-heading">
          <div class="managed-form-section-heading"><AppIcon name="Monitor" :size="19" /><div><h2 id="device-identity-heading">设备识别信息</h2><p>编号用于查找设备，序列号用于核对实物；带星号为必填项。</p></div></div>
          <div class="device-form-grid">
            <el-form-item label="设备编号" prop="deviceCode"><el-input v-model="form.deviceCode" placeholder="填写设备登记编号" maxlength="20" show-word-limit /><p class="managed-field-help">4–20 个字符，保存时仍由服务端校验唯一性。</p></el-form-item>
            <el-form-item label="设备类型" prop="deviceType"><el-select v-model="form.deviceType" placeholder="选择设备业务类型"><el-option v-for="item in deviceTypeOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
            <el-form-item label="设备型号" prop="modelName"><el-input v-model="form.modelName" placeholder="填写实物型号或登记型号" /></el-form-item>
            <el-form-item label="序列号" prop="serialNumber"><el-input v-model="form.serialNumber" placeholder="填写实物序列号" /></el-form-item>
          </div>
        </section>
        <section class="managed-form-section" aria-labelledby="device-state-heading">
          <div class="managed-form-section-heading"><AppIcon name="Operation" :size="19" /><div><h2 id="device-state-heading">状态与维护</h2><p>以下为设备业务登记，不作为实时在线或现场可用证明。</p></div></div>
          <div class="device-form-grid">
            <el-form-item label="设备状态" prop="status"><el-select v-model="form.status" placeholder="选择业务状态"><el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
            <el-form-item label="最后维护时间（UTC+8）" prop="lastMaintenanceDate"><el-date-picker v-model="form.lastMaintenanceDate" type="datetime" placeholder="选择实际维护时间" value-format="YYYY-MM-DDTHH:mm:ss" /><p class="managed-field-help">仅更新维护时间登记，不自动生成维护工单。</p></el-form-item>
          </div>
        </section>
      </el-form>
        <div class="managed-form-actions">
          <p>{{ saved ? '资料已保存，可返回列表核对' : uncertain ? '保存结果待核对，请勿再次提交' : dirty ? '当前修改尚未保存' : '确认设备资料后保存' }}</p>
          <div><el-button v-if="isEdit" :disabled="loading || !supervisor || !deviceId" @click="reload"><AppIcon name="Refresh" :size="15" />重新读取</el-button><el-button :disabled="loading || uncertain || saved || !loaded || !!permissionError" @click="reset"><AppIcon name="Refresh" :size="15" />{{ isEdit ? '恢复已读取内容' : '恢复初始值' }}</el-button><el-button type="primary" native-type="submit" form="device-maintenance-form" :loading="phase==='SAVING' || phase==='VALIDATING'" :disabled="!canSubmit"><AppIcon name="CircleCheck" :size="16" />{{ saved ? '已保存' : '保存设备' }}</el-button></div>
        </div>

    </section>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import { useManagedForm } from '../../composables/useManagedForm'
import ManagedFormFeedback from '../../components/ManagedFormFeedback.vue'
const formRef=ref(null)
const {form,id:deviceId,isEdit,supervisor,phase,loading,loaded,permissionError,loadError,saveError,validationError,lookupNotice,receipt,uncertain,saved,dirty,disabled,canSubmit,reload,reset,submit,goBack,uniqueValidator}=useManagedForm({
  endpoint:'/api/devices',listRoute:'devices',label:'设备',formRef,
  defaults:()=>({version:null,deviceCode:'',deviceType:'',modelName:'',serialNumber:'',status:'',lastMaintenanceDate:null})
})
const validateDeviceCode=uniqueValidator('deviceCode','/api/devices/check-code','deviceCode','该设备编号',4)
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


</script>
