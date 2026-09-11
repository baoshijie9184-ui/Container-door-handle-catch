<template>
  <div class="model-upload-container">
    <h1>ONNX 模型上传</h1>
    <el-card class="upload-card">
      <el-form :model="form" :rules="rules" ref="uploadFormRef" label-width="120px">
        <el-form-item label="模型文件" prop="file">
          <el-upload
            class="upload-demo"
            ref="uploadRef"
            drag
            :auto-upload="false"
            :limit="1"
            :on-change="handleFileChange"
            :on-exceed="handleExceed"
            :on-remove="handleRemove"
            accept=".onnx"
          >
            <el-icon class="el-icon--upload"><upload-filled /></el-icon>
            <div class="el-upload__text">
              拖拽文件到此处或 <em>点击上传</em>
            </div>
            <template #tip>
              <div class="el-upload__tip">
                仅支持 .onnx 文件，大小不超过 500MB
              </div>
            </template>
          </el-upload>
        </el-form-item>

        <el-form-item label="模型名称" prop="modelName">
          <el-input v-model="form.modelName" placeholder="请输入模型名称"></el-input>
        </el-form-item>

        <el-form-item label="版本号" prop="version">
          <el-input v-model="form.version" placeholder="请输入版本号"></el-input>
        </el-form-item>

        <el-form-item label="更新说明">
          <el-input type="textarea" v-model="form.updateDescription" placeholder="请输入更新说明"></el-input>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="loading" @click="submitUpload">上传模型</el-button>
        </el-form-item>

        <!-- 上传进度 -->
        <el-form-item v-if="uploadProgress > 0 && uploadProgress < 100">
          <el-progress :percentage="uploadProgress" :stroke-width="10" status="active" />
          <div class="progress-text">正在上传... {{ uploadProgress }}%</div>
        </el-form-item>
      </el-form>

      <div v-if="lastUploadResult" class="result-panel">
        <div class="result-header">
          <div>
            <div class="result-label">上传结果</div>
            <h3>{{ lastUploadResult.modelName }} <span>v{{ lastUploadResult.version }}</span></h3>
          </div>
          <el-tag :type="validationTypeMap[lastUploadResult.validationStatus] || 'info'" size="large">
            {{ validationLabelMap[lastUploadResult.validationStatus] || lastUploadResult.validationStatus || '未知' }}
          </el-tag>
        </div>

        <div class="result-grid">
          <div class="result-item">
            <span class="result-item-label">模型状态</span>
            <span class="result-item-value">{{ statusLabelMap[lastUploadResult.status] || lastUploadResult.status || '--' }}</span>
          </div>
          <div class="result-item">
            <span class="result-item-label">上传人</span>
            <span class="result-item-value">{{ lastUploadResult.creator || '--' }}</span>
          </div>
          <div class="result-item">
            <span class="result-item-label">上传时间</span>
            <span class="result-item-value">{{ formatDateTime(lastUploadResult.uploadTime) || '--' }}</span>
          </div>
          <div class="result-item">
            <span class="result-item-label">下一步建议</span>
            <span class="result-item-value">{{ nextStepText(lastUploadResult) }}</span>
          </div>
        </div>

        <div class="result-block">
          <div class="result-item-label">校验说明</div>
          <div class="result-message">{{ lastUploadResult.validationMessage || '暂无校验说明' }}</div>
        </div>

        <div class="result-block">
          <div class="result-item-label">模型路径</div>
          <div class="result-message">{{ lastUploadResult.modelPath || '--' }}</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage, ElNotification } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import request from '../api/request'

const uploadFormRef = ref(null)
const uploadRef = ref(null)
const loading = ref(false)
const uploadProgress = ref(0)
const lastUploadResult = ref(null)

const validationLabelMap = {
  PASSED: '基础校验通过',
  FAILED: '校验失败',
  PENDING: '待校验'
}

const validationTypeMap = {
  PASSED: 'success',
  FAILED: 'danger',
  PENDING: 'warning'
}

const statusLabelMap = {
  READY: '待发布',
  PUBLISHED: '已发布',
  DISABLED: '已停用',
  ARCHIVED: '已归档',
  DRAFT: '草稿'
}

const form = reactive({
  file: null,
  modelName: '',
  version: '',
  updateDescription: ''
})

const rules = {
  file: [
    { required: true, message: '请选择 ONNX 模型文件', trigger: 'change' }
  ],
  modelName: [
    { required: true, message: '请输入模型名称', trigger: 'blur' }
  ],
  version: [
    { required: true, message: '请输入版本号', trigger: 'blur' }
  ]
}

const handleFileChange = (file) => {
  if (file.raw.type !== 'application/octet-stream' && !file.name.endsWith('.onnx')) {
    ElMessage.error('只能上传 .onnx 格式的模型文件！')
    uploadRef.value.clearFiles()
    form.file = null
    return false
  }
  if (file.size / 1024 / 1024 > 500) {
    ElMessage.error('模型文件大小不能超过 500MB！')
    uploadRef.value.clearFiles()
    form.file = null
    return false
  }
  form.file = file.raw
}

const handleExceed = () => {
  ElMessage.warning('一次只能上传一个模型文件，请先移除现有文件再上传！')
}

const handleRemove = () => {
  form.file = null
}

const formatDateTime = (dateTime) => {
  if (!dateTime) return ''

  const date = new Date(dateTime)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')

  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
}

const nextStepText = (model) => {
  if (!model) return '--'
  if (model.validationStatus === 'FAILED') return '请修正模型文件后重新上传'
  if (model.status === 'READY') return '基础校验已通过，建议前往模型管理页发布或设为默认'
  if (model.status === 'PUBLISHED') return '模型已可投入使用'
  return '可前往模型管理页继续处理'
}

const submitUpload = async () => {
  const valid = await uploadFormRef.value.validate()
  if (!valid) {
    return
  }

  if (!form.file) {
    ElMessage.error('请选择要上传的模型文件')
    return
  }

  loading.value = true
  uploadProgress.value = 0
  const formData = new FormData()
  formData.append('file', form.file)
  formData.append('modelName', form.modelName)
  formData.append('version', form.version)
  formData.append('updateDescription', form.updateDescription)

  try {
    const response = await request.post('/api/models/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      },
      onUploadProgress: (progressEvent) => {
        if (progressEvent.total) {
          uploadProgress.value = Math.round((progressEvent.loaded * 100) / progressEvent.total)
        }
      }
    })
    lastUploadResult.value = response.data?.data || null
    ElNotification.success({
      title: '成功',
      message: lastUploadResult.value?.validationMessage || '模型上传成功！',
      duration: 3000
    })
    // 重置表单
    uploadFormRef.value.resetFields()
    uploadRef.value.clearFiles()
    form.file = null
    uploadProgress.value = 0
  } catch (error) {
    ElMessage.error(error.response?.data?.message || '模型上传失败，请稍后重试')
    uploadProgress.value = 0
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
.model-upload-container {
  padding: 20px;

  h1 {
    text-align: center;
    color: #333;
    margin-bottom: 30px;
  }

  .upload-card {
    max-width: 800px;
    margin: 0 auto;
    padding: 30px;
  }

  .upload-demo {
    width: 100%;
  }

  .progress-text {
    margin-top: 6px;
    font-size: 13px;
    color: #606266;
    text-align: center;
  }

  .result-panel {
    margin-top: 24px;
    padding: 22px;
    border-radius: 18px;
    background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
    border: 1px solid #e2e8f0;
  }

  .result-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    margin-bottom: 18px;

    h3 {
      margin: 6px 0 0;
      color: #0f172a;
      font-size: 22px;

      span {
        font-size: 15px;
        color: #64748b;
        font-weight: 600;
      }
    }
  }

  .result-label {
    font-size: 12px;
    color: #0f766e;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .result-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px 18px;
    margin-bottom: 18px;
  }

  .result-item {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .result-item-label {
    font-size: 12px;
    color: #64748b;
  }

  .result-item-value {
    color: #0f172a;
    font-weight: 600;
    line-height: 1.5;
  }

  .result-block {
    margin-top: 14px;
  }

  .result-message {
    margin-top: 6px;
    padding: 10px 12px;
    border-radius: 12px;
    background: #f8fafc;
    color: #334155;
    line-height: 1.6;
    word-break: break-all;
  }
}
</style> 
