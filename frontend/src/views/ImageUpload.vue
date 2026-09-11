<template>
  <div class="page-shell upload-container">
    <section class="page-hero upload-hero">
      <div>
        <span class="page-hero-label">Upload Workspace</span>
        <h1 class="page-hero-title">图片上传</h1>
        <p class="page-hero-text">
          选择本地图片文件夹，填写采集信息，上传原图到 OSS。上传完成后前往「图像检测」页提交检测任务。
        </p>
      </div>
    </section>

    <!-- 断点续传提示卡片 -->
    <el-alert
      v-if="resumeTaskInfo"
      type="warning"
      show-icon
      closable
      style="border-radius: 16px;"
      @close="dismissResume"
    >
      <template #default>
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;">
          <div>
            <strong>检测到未完成的上传任务</strong>
            <div style="margin-top: 4px; font-size: 13px; color: #5b6475;">
              「{{ resumeTaskInfo.folderName }}」
              已完成 {{ resumeTaskInfo.uploadedCount }}/{{ resumeTaskInfo.totalCount }} 张，
              {{ resumeTaskInfo.failedCount > 0 ? `失败 ${resumeTaskInfo.failedCount} 张，` : '' }}
              请重新选择同一文件夹继续上传。
            </div>
          </div>
          <div style="display: flex; gap: 8px;">
            <el-button type="primary" size="small" @click="triggerResumeFolderSelect">
              选择文件夹继续
            </el-button>
            <el-button size="small" @click="dismissResume">放弃</el-button>
          </div>
        </div>
      </template>
    </el-alert>

    <!-- 续传专用隐藏文件选择器 -->
    <input
      ref="resumeFolderInput"
      type="file"
      webkitdirectory
      directory
      multiple
      style="display: none"
      @change="handleResumeFolderSelect"
    />

    <div class="upload-grid">
      <!-- 上传表单 -->
      <el-card class="upload-card" header="上传配置" shadow="never">
        <el-form label-position="top">
          <div class="input-block">
            <div class="input-block-title">选择图片文件夹</div>
            <input
              ref="folderInput"
              type="file"
              webkitdirectory
              directory
              multiple
              style="display: none"
              @change="handleFolderSelect"
            />
            <el-button type="primary" class="wide-button" @click="triggerFolderSelect">
              <el-icon><FolderOpened /></el-icon>
              选择图片文件夹
            </el-button>

            <div class="folder-summary" v-if="folderInfo.imageCount">
              <div>文件夹层级：{{ folderInfo.name }}</div>
              <div>图片数：{{ folderInfo.imageCount }} 张</div>
            </div>

            <el-alert
              v-if="folderInfo.imageCount"
              type="info"
              show-icon
              message="文件夹结构：采集时间 / 地区 / 采集员 / 采集设备 / 图片文件夹名称 / 图片"
              style="margin-top: 12px;"
            />
          </div>

          <div v-if="folderInfo.imageCount" class="capture-meta-form">
            <el-form-item label="采集日期">
              <el-date-picker
                v-model="folderInfo.captureDate"
                value-format="YYYY-MM-DD"
                placeholder="选择采集日期"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="地区">
              <el-input v-model="folderInfo.region" placeholder="例如 上海" />
            </el-form-item>
            <el-form-item label="采集员">
              <el-select
                v-model="folderInfo.collector"
                placeholder="选择采集员"
                filterable
                :filter-option="(input, option) => option.label.toLowerCase().includes(input.toLowerCase())"
                :loading="loadingEmployees"
                clearable
              >
                <el-option
                  v-for="emp in employeeList"
                  :key="emp.id"
                  :value="emp.name"
                  :label="`${emp.name} (${emp.employeeNumber || ''})`"
                >
                  <span>{{ emp.name }}</span>
                  <span style="color: #8b95a5; margin-left: 8px; font-size: 12px;">{{ emp.employeeNumber }}</span>
                </el-option>
              </el-select>
            </el-form-item>
            <el-form-item label="采集设备">
              <el-select
                v-model="folderInfo.deviceName"
                placeholder="选择采集设备"
                filterable
                :filter-option="(input, option) => option.label.toLowerCase().includes(input.toLowerCase())"
                :loading="loadingDevices"
                clearable
              >
                <el-option
                  v-for="dev in deviceList"
                  :key="dev.id"
                  :value="dev.deviceCode"
                  :label="`${dev.deviceCode} ${dev.modelName || ''}`"
                >
                  <span>{{ dev.deviceCode }}</span>
                  <span style="color: #8b95a5; margin-left: 8px; font-size: 12px;">{{ dev.modelName }}</span>
                </el-option>
              </el-select>
            </el-form-item>
            <el-form-item label="图片文件夹名称">
              <el-input v-model="folderInfo.imageFolderName" placeholder="例如 批次A" />
            </el-form-item>
          </div>

          <el-button
            type="primary"
            class="wide-button upload-action"
            :disabled="!folderInfo.imageCount || uploadingToOss"
            :loading="uploadingToOss"
            @click="handleUploadBatch"
            size="large"
          >
            <el-icon><UploadFilled /></el-icon>
            {{ uploadingToOss ? '正在上传...' : '上传原图到 OSS' }}
          </el-button>

          <div v-if="uploadingTask" class="upload-progress-card">
            <div class="upload-progress-header">
              <span>{{ uploadingTask.folderName }}</span>
              <span>{{ uploadingTask.imageCount }} 张</span>
            </div>
            <el-progress
              :percentage="uploadingTask.progressPercent"
              status="active"
              :stroke-width="8"
            />
            <p class="upload-progress-msg">{{ uploadingTask.message }}</p>
          </div>

        </el-form>
      </el-card>

      <!-- 上传历史 -->
      <el-card class="upload-card history-card" shadow="never">
        <template #header>
          <div class="card-title-row">
            <span>上传历史</span>
            <el-badge v-if="taskList.length" :value="taskList.length"  />
            <el-button size="small" link :loading="refreshing" @click="refreshHistory" title="刷新上传历史">
              <template #icon><el-icon><Refresh /></el-icon></template>
            </el-button>
          </div>
        </template>
        <!-- 搜索和筛选栏 -->
        <div class="history-search-bar">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索任务ID或文件夹名…"
            clearable
            size="small"
            class="history-search-input"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-select
            v-model="statusFilter"
            placeholder="全部状态"
            clearable
            size="small"
            class="history-status-select"
          >
            <el-option label="全部状态" value="" />
            <el-option label="上传中" value="UPLOADING" />
            <el-option label="已上传" value="UPLOADED" />
            <el-option label="检测中" value="DETECTING" />
            <el-option label="已完成" value="COMPLETED" />
            <el-option label="失败" value="FAILED" />
          </el-select>
          <el-date-picker
            v-model="filterDate"
            placeholder="选择日期"
            size="small"
            class="history-date-picker"
            value-format="YYYY-MM-DD"
            clearable
          />
        </div>
        <el-empty
          v-if="uploadHistory.length === 0"
          description="暂无上传记录，选择文件夹开始上传"
          :image-size="64"
        />
        <div v-else class="history-list">
          <div
            v-for="task in uploadHistory"
            :key="task.taskId"
            class="history-item"
          >
            <!-- 任务ID -->
            <div class="history-item-taskid">
              <span class="taskid-label">任务ID</span>
              <code class="taskid-value">{{ task.taskId }}</code>
            </div>
            <!-- 第一行：名称 + 数量 + 状态 -->
            <div class="history-item-row1">
              <span class="history-item-folder">{{ task.folderName }}</span>
              <span class="history-item-count">{{ task.imageCount }} 张</span>
              <el-tag :type="taskStore.taskTagType(task)" class="history-item-tag">
                {{ taskStore.taskTagText(task) }}
              </el-tag>
            </div>
            <!-- 采集信息（如果有） -->
            <div v-if="task.captureInfo" class="history-item-capture">
              <span v-if="task.captureInfo.captureDate">{{ task.captureInfo.captureDate }}</span>
              <span v-if="task.captureInfo.collector">{{ task.captureInfo.collector }}</span>
              <span v-if="task.captureInfo.deviceName">{{ task.captureInfo.deviceName }}</span>
            </div>
            <!-- 进度条（仅上传中显示） -->
            <el-progress
              v-if="task.stage === 'uploading'"
              :percentage="task.progressPercent"
              :stroke-width="6"
              size="small"
              style="margin: 6px 0 2px;"
            />
            <!-- 第二行：状态详情 + 时间 -->
            <div class="history-item-row2">
              <span
                class="history-item-status"
                :class="{
                  'status-error': taskStore.taskStatusDetail(task).type === 'error',
                  'status-warn': taskStore.taskStatusDetail(task).type === 'warn',
                  'status-ok': taskStore.taskStatusDetail(task).type === 'success'
                }"
              >
                <el-icon v-if="taskStore.taskStatusDetail(task).type === 'success'"><CircleCheck /></el-icon>
                <el-icon v-else-if="taskStore.taskStatusDetail(task).type === 'warn' || taskStore.taskStatusDetail(task).type === 'error'"><Warning /></el-icon>
                <el-icon v-else><Clock /></el-icon>
                {{ taskStore.taskStatusDetail(task).text }}
              </span>
              <span class="history-item-time">
                上传时间：
                <el-icon style="margin-right: 2px; font-size: 11px;"><Calendar /></el-icon>
                {{ formatUploadTime(task.updatedAt || task.createdAt) }}
              </span>
            </div>
            <!-- 操作按钮 -->
            <div class="history-item-actions">
              <router-link
                v-if="task.stage === 'uploaded' || task.stage === 'queued' || task.stage === 'detecting' || task.stage === 'completed'"
                :to="`/inspection/workbench?taskId=${task.taskId}`"
              >
                <el-button link size="small">
                  <el-icon><Right /></el-icon>前往检测
                </el-button>
              </router-link>
              <el-button link size="small" type="danger" @click="taskStore.removeTask(task.taskId)">
                <el-icon><Delete /></el-icon>移除
              </el-button>
            </div>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, toRaw } from 'vue'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { Calendar, CircleCheck, Clock, Delete, FolderOpened, Refresh, Right, Search, UploadFilled, Warning } from '@element-plus/icons-vue'
import { fetchDevicesForSelect, fetchEmployeesForSelect } from '../api/resourceOptions'
import { useTaskStore, useUploadStore, usePollingStore } from '../stores/detectionTask'

const taskStore = useTaskStore()
const uploadStore = useUploadStore()
const pollingStore = usePollingStore()
const { uploadingToOss } = storeToRefs(uploadStore)
const { taskList } = storeToRefs(taskStore)

const folderInput = ref(null)
const resumeFolderInput = ref(null)
const employeeList = ref([])
const deviceList = ref([])
const loadingEmployees = ref(false)
const loadingDevices = ref(false)

// 断点续传相关状态
const resumeTaskInfo = ref(null) // { taskId, folderName, uploadedCount, totalCount }

// 搜索相关状态
const searchKeyword = ref('')
const statusFilter = ref('')
const filterDate = ref('')

const folderInfo = reactive({
  name: '',
  imageCount: 0,
  captureDate: '',
  region: '',
  collector: '',
  deviceName: '',
  imageFolderName: '',
  files: []
})

// 当前正在上传的任务
const uploadingTask = computed(() => {
  return taskList.value.find(t => t.stage === 'uploading') || null
})

// 上传历史：根据搜索条件过滤
const uploadHistory = computed(() => {
  let list = [...taskList.value]

  // 关键字过滤
  const kw = searchKeyword.value.trim().toLowerCase()
  if (kw) {
    list = list.filter(t =>
      (t.taskId && t.taskId.toLowerCase().includes(kw)) ||
      (t.folderName && t.folderName.toLowerCase().includes(kw))
    )
  }

  // 日期过滤
  if (filterDate.value) {
    list = list.filter(t => {
      const date = t.updatedAt || t.createdAt
      return date && date.startsWith(filterDate.value)
    })
  }

  // 状态过滤
  if (statusFilter.value) {
    // statusFilter 存的是后端状态值如 UPLOADING，stage 是前端映射值如 uploading
    const statusMap = {
      'UPLOADING': 'uploading',
      'UPLOADED': 'uploaded',
      'DETECTING': 'detecting',
      'COMPLETED': 'completed',
      'FAILED': 'failed'
    }
    const targetStage = statusMap[statusFilter.value] || statusFilter.value.toLowerCase()
    list = list.filter(t => t.stage === targetStage)
  }

  // 按 taskId 倒序（taskId 含时间戳，稳定不跳）
  list.sort((a, b) => (b.taskId || '').localeCompare(a.taskId || ''))

  return list
})

const triggerFolderSelect = () => {
  folderInput.value?.click()
}

const handleFolderSelect = (event) => {
  const files = Array.from(event.target.files || [])
  const imageFiles = files.filter(file => ['image/jpeg', 'image/png', 'image/jpg'].includes(file.type))
  if (!imageFiles.length) {
    ElMessage.warning('所选文件夹中没有可用图片')
    return
  }

  const firstPath = imageFiles[0].webkitRelativePath || imageFiles[0].name
  const firstSegments = firstPath.split('/').filter(Boolean)
  const dirSegments = firstSegments.length > 1 ? firstSegments.slice(0, -1) : firstSegments

  const autoParse = dirSegments.length >= 5
  folderInfo.name = dirSegments.slice(0, Math.min(dirSegments.length, 5)).join(' / ')
  folderInfo.imageCount = imageFiles.length
  folderInfo.captureDate = autoParse ? (dirSegments[0] || '') : ''
  folderInfo.region = autoParse ? (dirSegments[1] || '') : ''
  folderInfo.collector = autoParse ? (dirSegments[2] || '') : ''
  folderInfo.deviceName = autoParse ? (dirSegments[3] || '') : ''
  folderInfo.imageFolderName = autoParse ? (dirSegments[4] || '') : ''

  if (!autoParse) {
    ElMessage.info('未能自动解析文件夹结构，请手动填写采集信息')
  }
  folderInfo.files = imageFiles.map(file => ({
    file,
    fileName: file.name,
    contentType: file.type || 'image/jpeg',
    relativePath: file.webkitRelativePath || file.name,
    fileSize: file.size
  }))
}

const handleUploadBatch = () => {
  if (!folderInfo.files.length) {
    ElMessage.error('请先选择图片文件夹')
    return
  }
  if (!folderInfo.captureDate || !folderInfo.region || !folderInfo.collector || !folderInfo.deviceName || !folderInfo.imageFolderName) {
    ElMessage.error('请先确认采集日期、地区、采集员、采集设备和图片文件夹名称')
    return
  }

  const filesData = folderInfo.files.map(item => ({
    file: toRaw(item.file),
    fileName: item.fileName,
    contentType: item.contentType,
    relativePath: item.relativePath,
    fileSize: item.fileSize
  }))

  const captureInfo = {
    captureDate: folderInfo.captureDate,
    region: folderInfo.region,
    collector: folderInfo.collector,
    deviceName: folderInfo.deviceName,
    imageFolderName: folderInfo.imageFolderName,
    imageCount: folderInfo.imageCount,
    folderLabel: `${folderInfo.region || '未知'} / ${folderInfo.imageFolderName || '未命名'}`
  }

  uploadStore.uploadBatchToOss(filesData, captureInfo)

  // 重置表单
  resetBatchState()
}

const resetBatchState = () => {
  folderInfo.name = ''
  folderInfo.imageCount = 0
  folderInfo.captureDate = ''
  folderInfo.region = ''
  folderInfo.collector = ''
  folderInfo.deviceName = ''
  folderInfo.imageFolderName = ''
  folderInfo.files = []
}

// ==================== 断点续传 ====================

const triggerResumeFolderSelect = () => {
  resumeFolderInput.value?.click()
}

const handleResumeFolderSelect = (event) => {
  const files = Array.from(event.target.files || [])
  const imageFiles = files.filter(file => ['image/jpeg', 'image/png', 'image/jpg'].includes(file.type))
  if (!imageFiles.length) {
    ElMessage.warning('所选文件夹中没有可用图片')
    return
  }

  const info = resumeTaskInfo.value
  if (!info) return

  // 加载已完成的文件列表
  const fileState = taskStore.loadFileState(info.taskId)
  const completedNames = new Set(fileState?.completed || [])

  // 按文件名匹配，筛选出未完成的文件
  const remainingFiles = imageFiles.filter(f => !completedNames.has(f.name))
  const skippedCount = imageFiles.length - remainingFiles.length

  if (!remainingFiles.length) {
    ElMessage.success('所有文件已上传完成，无需续传')
    taskStore.removeFileState(info.taskId)
    resumeTaskInfo.value = null
    return
  }

  ElMessage.info(`匹配到 ${skippedCount} 个已完成文件，剩余 ${remainingFiles.length} 个待上传`)

  // 使用原任务的捕获信息（从 taskList 中获取）
  const originalTask = taskList.value.find(t => t.taskId === info.taskId)
  const filesData = remainingFiles.map(file => ({
    file: file, // File 对象不需要 toRaw，resumeUploadToOss 内部处理
    fileName: file.name,
    contentType: file.type || 'image/jpeg',
    relativePath: file.webkitRelativePath || file.name,
    fileSize: file.size
  }))

  // 开始续传
  uploadStore.resumeUploadToOss(info.taskId, filesData)
  resumeTaskInfo.value = null
}

// 格式化上传时间显示
const formatUploadTime = (dateStr) => {
  if (!dateStr) return ''
  // dateStr 格式: 2026-05-26T17:20:06 或 2026-05-26T17:20:06.xxx
  const match = dateStr.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/)
  if (match) {
    return `${match[1]} ${match[2]}`
  }
  return dateStr.substring(0, 16)
}

const dismissResume = () => {
  const info = resumeTaskInfo.value
  if (info) {
    taskStore.removeFileState(info.taskId)
    // 更新任务状态为失败
    const task = taskList.value.find(t => t.taskId === info.taskId)
    if (task && task.stage === 'uploading') {
      taskStore.updateTask(info.taskId, { stage: 'failed', message: '用户放弃续传', error: '用户放弃续传' })
      taskStore.saveTaskList()
    }
  }
  resumeTaskInfo.value = null
}

// ==================== 数据加载 ====================

const fetchEmployees = async () => {
  loadingEmployees.value = true
  try {
    const res = await fetchEmployeesForSelect()
    if (res.data?.code === 200) {
      const page = res.data.data
      employeeList.value = page.records || page || []
    }
  } catch (err) {
    console.error('加载员工列表失败:', err)
  } finally {
    loadingEmployees.value = false
  }
}

const fetchDevices = async () => {
  loadingDevices.value = true
  try {
    const res = await fetchDevicesForSelect()
    if (res.data?.code === 200) {
      const data = res.data.data
      deviceList.value = data.records || data || []
    }
  } catch (err) {
    console.error('加载设备列表失败:', err)
  } finally {
    loadingDevices.value = false
  }
}

// ==================== 生命周期 ====================

const refreshing = ref(false)
const refreshHistory = async () => {
  refreshing.value = true
  try {
    await pollingStore.fetchTaskList()
    ElMessage.success('上传历史已刷新')
  } catch (e) {
    ElMessage.error('刷新失败')
  } finally {
    refreshing.value = false
  }
}

onMounted(async () => {
  // 并行加载：任务列表 + 员工/设备选项
  await Promise.all([
    pollingStore.restoreFromSession(),
    pollingStore.fetchTaskList(),
    fetchEmployees(),
    fetchDevices()
  ])
  // 检查是否有未完成的上传任务
  const resumeList = taskStore.getResumeTaskList()
  if (resumeList.length > 0) {
    resumeTaskInfo.value = resumeList[0]
  }
})
</script>

<style scoped>
.upload-container {
  display: grid;
  gap: 24px;
}

.upload-grid {
  display: grid;
  grid-template-columns: 2fr 3fr;
  gap: 16px;
  align-items: start;
}

.upload-card {
  border-radius: 24px;
  box-shadow: 0 18px 42px rgba(15, 23, 42, 0.08);
  align-self: start;
  min-width: 0;
  width: 100%;
}

.input-block {
  padding: 18px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.95), rgba(255, 255, 255, 0.9));
  margin-bottom: 16px;
}

.input-block-title {
  margin-bottom: 14px;
  font-size: 16px;
  font-weight: 600;
  color: #172033;
}

.wide-button {
  width: 100%;
}

.upload-action {
  margin-top: 16px;
}

.folder-summary {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 14px;
  background: #f8fafc;
  color: #475569;
  line-height: 1.8;
}

.capture-meta-form {
  margin-top: 16px;
}

.capture-meta-form :deep(.el-form-item) {
  margin-bottom: 12px;
}

.threshold-text {
  margin-top: 8px;
  color: #5b6475;
}

.upload-progress-card {
  margin-top: 20px;
  padding: 16px;
  border-radius: 16px;
  background: #f0f6ff;
  border: 1px solid rgba(22, 119, 255, 0.15);
}

.upload-progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  font-weight: 600;
  color: #172033;
}

.upload-progress-msg {
  margin-top: 8px;
  color: #5b6475;
  font-size: 13px;
}

.history-card {
  display: flex;
  flex-direction: column;
}

.history-card :deep(.el-card-body) {
  flex: 1;
  padding: 16px;
}

.history-card :deep(.el-empty) {
  margin-top: 40px;
}

.card-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.history-search-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.history-search-input {
  flex: 1;
}

.history-status-select {
  width: 110px;
}

.history-date-picker {
  width: 130px;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.history-item {
  padding: 14px 16px;
  border-radius: 14px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  background: #fafbfc;
  transition: all 0.18s;
}

.history-item:hover {
  border-color: rgba(22, 119, 255, 0.18);
  background: rgba(22, 119, 255, 0.015);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
}

.history-item-taskid {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.taskid-label {
  font-size: 11px;
  color: #94a3b8;
  flex-shrink: 0;
}

.taskid-value {
  font-size: 11px;
  color: #5b6475;
  background: rgba(15, 23, 42, 0.04);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: 'SF Mono', 'Consolas', monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-item-row1 {
  display: flex;
  align-items: center;
  gap: 8px;
}

.history-item-folder {
  flex: 1;
  font-weight: 600;
  color: #172033;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-item-capture {
  display: flex;
  gap: 12px;
  margin-top: 4px;
  font-size: 12px;
  color: #8b95a5;
  flex-wrap: wrap;
}

.history-item-capture span::before {
  content: '·';
  margin-right: 4px;
}

.history-item-capture span:first-child::before {
  content: '';
  margin-right: 0;
}

.history-item-count {
  font-size: 12px;
  color: #8b95a5;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.history-item-tag {
  flex-shrink: 0;
  font-size: 12px;
  line-height: 20px;
}

.history-item-row2 {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
  gap: 8px;
}

.history-item-status {
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #5b6475;
}

.history-item-status.status-error { color: #e84749; }
.history-item-status.status-warn { color: #d48806; }
.history-item-status.status-ok { color: #389e0d; }

.history-item-time {
  font-size: 11px;
  color: #b0b8c4;
  white-space: nowrap;
  flex-shrink: 0;
}

.history-item-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid rgba(15, 23, 42, 0.04);
}

.history-item-actions :deep(.el-button.is-link) {
  padding: 0 8px;
  font-size: 12px;
  height: 28px;
}

@media (max-width: 900px) {
  .upload-grid {
    grid-template-columns: 1fr;
  }
}
</style>
