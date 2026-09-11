<template>
  <div class="page-shell form-page">
    <section class="page-hero">
      <div>
        <span class="page-hero-label">File Upload Test</span>
        <h1 class="page-hero-title">文件上传测试</h1>
        <p class="page-hero-text">
          测试图片上传与检测功能，选择图片后提交进行检测。
        </p>
      </div>
    </section>

    <el-card>
      <el-form :model="form" :rules="rules" ref="formRef" label-width="120px">
        <el-form-item label="上传图片">
          <el-upload
            ref="uploadRef"
            action="/api/detection/upload"
            :auto-upload="false"
            :on-change="handleChange"
            :on-remove="handleRemove"
            :file-list="fileList"
            multiple
            accept="image/*"
            list-type="picture-card"
          >
            <el-icon><Plus /></el-icon>
          </el-upload>
        </el-form-item>

        <el-form-item label="模型ID" prop="modelId">
          <el-input v-model="form.modelId" placeholder="输入模型ID" />
        </el-form-item>

        <el-form-item label="输出格式" prop="outputFormat">
          <el-radio-group v-model="form.outputFormat">
            <el-radio label="YOLO">YOLO</el-radio>
            <el-radio label="COCO">COCO</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="置信度阈值">
          <el-slider v-model="form.confidenceThreshold" :min="0.1" :max="1" :step="0.05" />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="loading" @click="submitForm">提交检测</el-button>
          <el-button @click="resetForm">重置</el-button>
        </el-form-item>
      </el-form>

      <div v-if="response" class="response-container">
        <h3>响应结果:</h3>
        <pre>{{ JSON.stringify(response, null, 2) }}</pre>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import request from '../api/request'

const formRef = ref(null)
const uploadRef = ref(null)
const fileList = ref([])
const response = ref(null)
const loading = ref(false)

const form = reactive({
  modelId: '1',
  outputFormat: 'YOLO',
  confidenceThreshold: 0.5
})

const rules = {
  modelId: [
    { required: true, message: '请输入模型ID', trigger: 'blur' }
  ],
  outputFormat: [
    { required: true, message: '请选择输出格式', trigger: 'change' }
  ]
}

const handleChange = () => true

const handleRemove = () => {}

const submitForm = async () => {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch { return }

  if (!uploadRef.value) {
    ElMessage.warning('上传组件未初始化')
    return
  }

  const files = uploadRef.value.uploadFiles
  if (!files || files.length === 0) {
    ElMessage.warning('请选择至少一张图片')
    return
  }

  loading.value = true
  try {
    const formData = new FormData()
    files.forEach(file => {
      if (file.raw) formData.append('files', file.raw)
    })
    formData.append('modelId', form.modelId)
    formData.append('outputFormat', form.outputFormat)
    formData.append('confidenceThreshold', form.confidenceThreshold)

    const result = await request.post('/api/detection/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })

    response.value = result.data
    ElMessage.success('上传成功')
  } catch (error) {
    response.value = error.response?.data || { error: error.message }
    ElMessage.error(error.response?.data?.message || '上传失败')
  } finally {
    loading.value = false
  }
}

const resetForm = () => {
  if (uploadRef.value) uploadRef.value.clearFiles()
  fileList.value = []
  response.value = null
}
</script>

<style scoped>
.form-page {
  gap: 18px;
}

.response-container {
  margin-top: 20px;
  padding: 16px;
  background-color: #f5f7fa;
  border-radius: 8px;
}

pre {
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
