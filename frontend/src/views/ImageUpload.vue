<template>
  <div class="page-shell upload-container">
    <PageHero class="page-hero upload-hero">
      <div>
        <span class="page-hero-label">Upload Workspace</span>
        <h1 class="page-hero-title">图片上传</h1>
        <p class="page-hero-text">
          选择图片并核对采集信息。原图上传后，现有流程会自动提交检测；请到工作台核对实际进度与模型记录。
        </p>
      </div>
    </PageHero>

    <ol class="upload-flow" aria-label="图片上传与检测步骤">
      <li><span class="upload-flow-icon"><AppIcon name="Picture" :size="20" /></span><div><strong>1 选择图片</strong><p>选择文件夹并核对采集信息</p></div></li>
      <li><span class="upload-flow-icon"><AppIcon name="Upload" :size="20" /></span><div><strong>2 上传原图</strong><p>核对上传进度及自动提交回执</p></div></li>
      <li><span class="upload-flow-icon"><AppIcon name="Search" :size="20" /></span><div><strong>3 核对检测</strong><p><router-link to="/inspection/workbench">查看实际进度与模型记录</router-link></p></div></li>
    </ol>

    <!-- 断点续传提示卡片 -->
    <el-alert
      v-if="resumeTaskInfo"
      type="warning"
      show-icon
      :closable="!uploadingToOss"
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
            <el-button type="primary" size="small" :disabled="uploadingToOss" @click="triggerResumeFolderSelect">
              选择文件夹继续
            </el-button>
            <el-button size="small" :disabled="uploadingToOss" @click="dismissResume">放弃续传</el-button>
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
            <div class="input-block-title"><el-icon aria-hidden="true"><FolderOpened /></el-icon>选择图片文件夹</div>
            <p id="upload-image-format" class="upload-format-note">支持 JPG、JPEG、PNG 图片，可从文件夹中批量选择</p>
            <input
              ref="folderInput"
              type="file"
              webkitdirectory
              directory
              multiple
              style="display: none"
              @change="handleFolderSelect"
            />
            <el-button type="primary" class="wide-button" aria-describedby="upload-image-format" :disabled="uploadingToOss" @click="triggerFolderSelect">
              <el-icon><FolderOpened /></el-icon>
              选择图片文件夹
            </el-button>

            <dl class="folder-summary" v-if="folderInfo.imageCount"><div><dt>所选文件夹层级</dt><dd>{{ folderInfo.name }}</dd></div><div><dt>图片数量</dt><dd>{{ folderInfo.imageCount }} 张</dd></div></dl>
            <p v-if="selectionNotice" class="upload-selection-note">{{ selectionNotice }}</p>

            <el-alert
              v-if="folderInfo.imageCount"
              type="info"
              show-icon
              title="可识别文件夹层级中的采集信息，请在上传前核对"
              style="margin-top: 12px;"
            />
            <SelectedImageFiles v-if="folderInfo.files.length" :files="folderInfo.files" :scope-key="accountScope()" />
          </div>

          <div v-if="folderInfo.imageCount" class="capture-meta-form" role="group" aria-labelledby="upload-capture-heading" aria-describedby="upload-capture-scope">
            <h2 id="upload-capture-heading" class="capture-meta-heading"><AppIcon name="Document" :size="17" />采集信息</h2>
            <el-form-item label="采集日期" required>
              <el-date-picker
                v-model="folderInfo.captureDate"
                :disabled="uploadingToOss || uploadAttempted"
                value-format="YYYY-MM-DD"
                aria-label="采集日期" placeholder="选择采集日期"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="地区" required>
              <el-input v-model="folderInfo.region" :disabled="uploadingToOss || uploadAttempted" aria-label="采集地区" placeholder="例如 上海" />
            </el-form-item>
            <el-form-item label="采集员" required>
              <el-select
                v-model="folderInfo.collector"
                aria-label="选择采集员" placeholder="选择采集员"
                filterable
                :disabled="uploadingToOss || uploadAttempted"
                :no-data-text="employeeError ? '候选读取失败，请重新读取' : loadingEmployees || !employeeLoaded ? '正在核对候选' : '当前已加载范围无候选'"
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
                  <span class="capture-option-detail">{{ emp.employeeNumber }}</span>
                </el-option>
              </el-select>
              <p v-if="employeeError" class="capture-read-error" role="alert">{{ employeeError }}<button type="button" :disabled="loadingEmployees || uploadingToOss" @click="fetchEmployees">重新读取</button></p>
            </el-form-item>
            <el-form-item label="采集设备" required>
              <el-select
                v-model="folderInfo.deviceName"
                aria-label="选择采集设备" placeholder="选择采集设备"
                filterable
                :disabled="uploadingToOss || uploadAttempted"
                :no-data-text="deviceError ? '候选读取失败，请重新读取' : loadingDevices || !deviceLoaded ? '正在核对候选' : '当前已加载范围无候选'"
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
                  <span class="capture-option-detail">{{ dev.modelName }}</span>
                </el-option>
              </el-select>
              <p v-if="deviceError" class="capture-read-error" role="alert">{{ deviceError }}<button type="button" :disabled="loadingDevices || uploadingToOss" @click="fetchDevices">重新读取</button></p>
            </el-form-item>
            <el-form-item label="图片文件夹名称" required>
              <el-input v-model="folderInfo.imageFolderName" :disabled="uploadingToOss || uploadAttempted" aria-label="图片文件夹名称" placeholder="例如 批次A" />
            </el-form-item>
          </div>
          <p v-if="folderInfo.imageCount" id="upload-capture-scope" class="upload-selection-note">人员与设备候选仅为本次已加载范围。采集信息作为来源记录，不改变账号身份或质检分派。</p>

          <p v-if="folderInfo.imageCount" class="upload-readiness" :data-ready="!missingCaptureFields.length"><AppIcon :name="missingCaptureFields.length ? 'Warning' : 'CircleCheck'" :size="16" />{{ missingCaptureFields.length ? '还需补全：'+missingCaptureFields.join('、') : '采集信息已填写，请核对后上传' }}</p>
          <el-button
            type="primary"
            class="wide-button upload-action"
            :disabled="!folderInfo.imageCount || uploadingToOss || !!missingCaptureFields.length || uploadAttempted"
            :loading="uploadingToOss"
            @click="handleUploadBatch"
            size="large"
          >
            <el-icon><UploadFilled /></el-icon>
            {{ uploadingToOss ? '正在上传原图…' : uploadAttempted ? '本次上传已发起' : '上传原图' }}
          </el-button>
          <div v-if="uploadAttempted" class="upload-attempt-note" role="status"><AppIcon name="Search" :size="17" /><div><strong>请在上传历史核对本次结果</strong><p>已发起不等于全部上传或检测完成。此处保留所选图片与采集信息，不自动重复提交；如需新建任务，请重新选择文件夹。</p><button type="button" :disabled="uploadingToOss" @click="resetBatchState">清空本次选择</button></div></div>

          <Transition name="upload-feedback"><div v-if="uploadingTask" class="upload-progress-card">
            <div class="upload-progress-header">
              <span>{{ uploadingTask.folderName }}</span>
              <span>{{ uploadingTask.imageCount }} 张</span>
            </div>
            <el-progress
              :percentage="uploadingTask.progressPercent"
              :stroke-width="8"
            />
            <p class="upload-progress-msg">{{ uploadingTask.message }}</p>
          </div></Transition>

        </el-form>
      </el-card>

      <!-- 上传历史 -->
      <el-card class="upload-card history-card" shadow="never">
        <template #header>
          <div class="card-title-row">
            <span>上传历史</span>
            <el-badge v-if="taskList.length" :value="taskList.length"  />
            <el-button size="small" link :loading="refreshing || historyLoading" @click="refreshHistory" title="刷新上传历史" aria-label="刷新上传历史">
              <template #icon><el-icon><Refresh /></el-icon></template>
            </el-button>
          </div>
        </template>
        <!-- 搜索和筛选栏 -->
        <div class="history-search-bar">
          <label class="upload-history-filter" for="upload-history-keyword"><span>任务或文件夹</span>
          <el-input
            id="upload-history-keyword"
            v-model="searchKeyword"
            aria-label="搜索任务ID或文件夹名…" placeholder="搜索任务ID或文件夹名…"
            clearable
            size="small"
            class="history-search-input"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          </label>
          <label class="upload-history-filter" for="upload-history-status"><span>处理阶段</span>
          <el-select
            id="upload-history-status"
            v-model="statusFilter"
            aria-label="全部状态" placeholder="全部状态"
            clearable
            size="small"
            class="history-status-select"
          >
            <el-option label="全部状态" value="" />
            <el-option label="上传中" value="UPLOADING" />
            <el-option label="已上传" value="UPLOADED" />
            <el-option label="已排队" value="QUEUED" />
            <el-option label="检测中" value="DETECTING" />
            <el-option label="已完成" value="COMPLETED" />
            <el-option label="失败" value="FAILED" />
          </el-select>
          </label>
          <label class="upload-history-filter" for="upload-history-date"><span>最近更新日期（UTC+8）</span>
          <el-date-picker
            id="upload-history-date"
            v-model="filterDate"
            aria-label="选择日期" placeholder="选择日期"
            size="small"
            class="history-date-picker"
            value-format="YYYY-MM-DD"
            clearable
          />
          </label>
        </div>
        <p class="upload-history-cache-note">筛选仅作用于当前已加载记录。清除本机缓存不删除后端任务或图片，也不取消服务器检测；重新读取后可能再次显示。</p>
        <div class="upload-history-scope"><span>{{ historyLoading ? '正在核对上传记录…' : `已加载 ${taskList.length} 条，当前匹配 ${uploadHistory.length} 条` }}</span><el-button v-if="hasHistoryFilters" link size="small" @click="resetHistoryFilters">清空筛选</el-button></div>
        <el-alert v-if="historyError && uploadHistory.length" :title="historyError + '；以下为先前已加载的记录，请刷新核对。'" type="error" show-icon :closable="false" />
        <CollectionEmptyState
          v-if="uploadHistory.length === 0"
          :loading="historyLoading"
          :error="historyError"
          :filtered="hasHistoryFilters"
          empty-title="暂无上传记录"
          empty-description="选择图片文件夹并核对采集信息后，点击上传原图开始。"
          @retry="refreshHistory"
          @reset="resetHistoryFilters"
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
                最近更新（UTC+8）：
                <el-icon style="margin-right: 2px; font-size: 11px;"><Calendar /></el-icon>
                {{ formatUploadTime(task.updatedAt || task.createdAt) }}
              </span>
            </div>
            <!-- 操作按钮 -->
            <div class="history-item-actions">
              <router-link
                v-if="task.stage === 'uploaded' || task.stage === 'queued' || task.stage === 'detecting' || task.stage === 'completed'"
                :to="`/inspection/workbench?taskId=${task.taskId}`"
                class="upload-next-link"
              >
                <el-icon aria-hidden="true"><Right /></el-icon>前往检测
              </router-link>
              <el-button link size="small" :loading="removeCacheBusy===task.taskId" :disabled="uploadingToOss || !!removeCacheBusy" @click="removeCachedUploadTask(task)">
                <el-icon><Delete /></el-icon>清除本机缓存
              </el-button>
            </div>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref, toRaw } from 'vue'
import { storeToRefs } from 'pinia'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Calendar, CircleCheck, Clock, Delete, FolderOpened, Refresh, Right, Search, UploadFilled, Warning } from '@element-plus/icons-vue'
import { fetchDevicesForSelect, fetchEmployeesForSelect } from '../api/resourceOptions'
import { useTaskStore, useUploadStore, usePollingStore } from '../stores/detectionTask'
import { beijingDateTime } from '../utils/beijingTime'
import CollectionEmptyState from '../components/CollectionEmptyState.vue'
import SelectedImageFiles from '../components/SelectedImageFiles.vue'
import { useUserStore } from '../stores/user'

const taskStore = useTaskStore()
const userStore = useUserStore()
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
const employeeError = ref(''), deviceError = ref(''), selectionNotice = ref(''), uploadAttempted = ref(false)
const employeeLoaded = ref(false), deviceLoaded = ref(false)
let pageActive = true, employeeRequest = 0, deviceRequest = 0
const removeCacheBusy=ref('')
const accountScope=()=>JSON.stringify([userStore.identity?.userId || userStore.username || '',userStore.role,userStore.isAuthenticated])
async function removeCachedUploadTask(task){
  const taskId=task?.taskId
  if(!pageActive || uploadingToOss.value || removeCacheBusy.value || typeof taskId!=='string' || !/^[A-Za-z0-9_-]{1,128}$/.test(taskId))return
  const scope=accountScope()
  removeCacheBusy.value=taskId
  try {
    await ElMessageBox.confirm(`清除任务 ${taskId} 的本机缓存？后端任务与图片继续保留，服务器检测不会取消；重新读取后可能再次显示。`,'清除本机任务缓存',{type:'warning',confirmButtonText:'清除本机缓存',cancelButtonText:'保留缓存'})
    if(!pageActive || scope!==accountScope() || uploadingToOss.value)return
    if(!taskList.value.some(row=>row.taskId===taskId)){ElMessage.info('此任务已不在当前本机缓存中，请重新读取核对');return}
    taskStore.removeTask(taskId)
    ElMessage.success('已清除本机任务缓存，后端任务与图片保留')
  } catch(error){if(pageActive && scope===accountScope() && !['cancel','close'].includes(error))ElMessage.error('本机缓存清理未完成，请重新读取核对')}
  finally {removeCacheBusy.value=''}
}
onBeforeUnmount(() => { pageActive = false; employeeRequest++; deviceRequest++ })

// 断点续传相关状态
const resumeTaskInfo = ref(null) // { taskId, folderName, uploadedCount, totalCount }

// 搜索相关状态
const searchKeyword = ref('')
const statusFilter = ref('')
const filterDate = ref('')
const hasHistoryFilters = computed(() => !!(searchKeyword.value.trim() || statusFilter.value || filterDate.value))
const historyLoading = ref(true)
const historyError = ref('')
const resetHistoryFilters = () => { searchKeyword.value = ''; statusFilter.value = ''; filterDate.value = '' }

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

const missingCaptureFields = computed(() => [
  ['captureDate', '采集日期'], ['region', '地区'], ['collector', '采集员'],
  ['deviceName', '采集设备'], ['imageFolderName', '图片文件夹名称']
].filter(([key]) => !String(folderInfo[key] || '').trim()).map(([, label]) => label))

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
      return date && beijingDateTime(date).startsWith(filterDate.value)
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
  if (uploadingToOss.value) return
  folderInput.value?.click()
}

const handleFolderSelect = (event) => {
  if (uploadingToOss.value) return
  const files = Array.from(event.target.files || [])
  const imageFiles = files.filter(file => ['image/jpeg', 'image/png', 'image/jpg'].includes(file.type))
  if (!imageFiles.length) {
    ElMessage.warning('所选文件夹中没有可用图片')
    return
  }
  uploadAttempted.value = false
  selectionNotice.value = `本次选入 ${imageFiles.length} 张图片${files.length > imageFiles.length ? `，另有 ${files.length - imageFiles.length} 个文件未列入本次上传` : ''}`

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
  if (uploadingToOss.value || uploadAttempted.value) return
  if (!folderInfo.files.length) {
    ElMessage.error('请先选择图片文件夹')
    return
  }
  if (missingCaptureFields.value.length) {
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

  uploadAttempted.value = true
  uploadStore.uploadBatchToOss(filesData, captureInfo)
}

const resetBatchState = () => {
  if (uploadingToOss.value) return
  uploadAttempted.value = false
  selectionNotice.value = ''
  if (folderInput.value) folderInput.value.value = ''
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
  if (uploadingToOss.value) return
  resumeFolderInput.value?.click()
}

const handleResumeFolderSelect = (event) => {
  if (uploadingToOss.value) return
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
  return dateStr ? beijingDateTime(dateStr) || '时间格式未知' : '未记录'
}

const dismissResume = () => {
  if (uploadingToOss.value) return
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
  if (!pageActive) return
  const request = ++employeeRequest
  loadingEmployees.value = true
  employeeError.value = ''
  try {
    const res = await fetchEmployeesForSelect()
    if (!pageActive || request !== employeeRequest) return
    const page = res.data?.data, rows = Array.isArray(page) ? page : page?.records
    if (res.data?.code !== 200 || !Array.isArray(rows) || rows.some(row => !row || typeof row.name !== 'string')) throw new Error('员工候选格式不完整')
    employeeList.value = rows
    employeeLoaded.value = true
  } catch (err) {
    if (!pageActive || request !== employeeRequest) return
    if ([401, 403].includes(err.response?.status)) { employeeList.value = []; employeeLoaded.value = false }
    employeeError.value = '采集员候选暂不可读取，原有采集信息保留。'
  } finally {
    if (pageActive && request === employeeRequest) loadingEmployees.value = false
  }
}

const fetchDevices = async () => {
  if (!pageActive) return
  const request = ++deviceRequest
  loadingDevices.value = true
  deviceError.value = ''
  try {
    const res = await fetchDevicesForSelect()
    if (!pageActive || request !== deviceRequest) return
    const data = res.data?.data, rows = Array.isArray(data) ? data : data?.records
    if (res.data?.code !== 200 || !Array.isArray(rows) || rows.some(row => !row || typeof row.deviceCode !== 'string')) throw new Error('设备候选格式不完整')
    deviceList.value = rows
    deviceLoaded.value = true
  } catch (err) {
    if (!pageActive || request !== deviceRequest) return
    if ([401, 403].includes(err.response?.status)) { deviceList.value = []; deviceLoaded.value = false }
    deviceError.value = '采集设备候选暂不可读取，原有采集信息保留。'
  } finally {
    if (pageActive && request === deviceRequest) loadingDevices.value = false
  }
}

// ==================== 生命周期 ====================

const refreshing = ref(false)
const loadUploadHistory = async () => {
  if (!pageActive) return false
  historyLoading.value = true
  try {
    const result = await pollingStore.fetchTaskList()
    if (!pageActive) return false
    if (!result?.ok) throw new Error(result?.message || '上传记录暂不可读取')
    historyError.value = ''
    return true
  } catch (error) {
    if (pageActive) historyError.value = error.message || '上传记录暂不可读取，请刷新核对'
    return false
  } finally {
    if (pageActive) historyLoading.value = false
  }
}
const refreshHistory = async () => {
  if (refreshing.value || historyLoading.value) return
  refreshing.value = true
  try {
    if (await loadUploadHistory()) ElMessage.success('上传历史已刷新')
  } finally {
    refreshing.value = false
  }
}

onMounted(async () => {
  // 并行加载：任务列表 + 员工/设备选项
  await Promise.all([
    pollingStore.restoreFromSession(),
    loadUploadHistory(),
    fetchEmployees(),
    fetchDevices()
  ])
  if (!pageActive) return
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
  padding: 0 0 16px;
  border-bottom: 1px solid var(--app-border);
  margin-bottom: 16px;
}

.input-block-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 7px;
  font-size: 15px;
  font-weight: 600;
  color: var(--app-text);
}
.input-block-title > .el-icon { flex:0 0 auto; color:var(--app-primary); }

.wide-button {
  width: 100%;
}

.upload-action {
  margin-top: 16px;
}

.folder-summary {
  margin-top: 14px;
  color: var(--app-text);
  padding: 0;
  font-size: 12px;
  line-height: 1.8;
}
.folder-summary > div { display:grid; gap:3px; margin-top:9px; min-width:0; }
.folder-summary dt { color:var(--app-text-secondary); }
.folder-summary dd { margin:0; overflow-wrap:anywhere; }
.capture-meta-heading { display:flex; align-items:center; gap:7px; margin:0 0 14px; font-size:15px; font-weight:600; line-height:1.8; color:var(--app-text); }
.capture-meta-heading > .el-icon { flex:0 0 auto; color:var(--app-primary); }
.capture-option-detail { color:var(--app-text-secondary); margin-left:8px; font-size:12px; }

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
  display: grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.upload-history-filter { display:grid; gap:7px; min-width:0; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.upload-history-filter:first-child { grid-column:1/-1; }
.upload-history-filter :is(.history-search-input,.history-status-select,.history-date-picker) { width:100%; min-width:0; }
.upload-history-filter :deep(.el-date-editor.el-input) { width:100%; }
.upload-history-cache-note { margin:0 0 14px; color:var(--app-text-secondary); font-size:12px; line-height:1.9; }

.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.history-item {
  padding: 16px 0;
  border-radius: 0;
  border: 0;
  border-bottom:1px solid var(--app-border);
  background: var(--app-surface);
}
.history-item:last-child { border-bottom:0; }

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
@media(max-width:480px) { .history-search-bar { grid-template-columns:minmax(0,1fr); }.upload-history-filter:first-child { grid-column:auto; } }
.upload-selection-note { margin:10px 0 14px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.capture-read-error { flex-basis:100%; margin:8px 0 0; color:var(--app-warning); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.capture-read-error button, .upload-attempt-note button { display:inline-flex; align-items:center; border:0; border-radius:4px; padding:3px 0; margin-left:8px; color:var(--app-primary); background:transparent; font:inherit; cursor:pointer; }
.upload-attempt-note { display:flex; align-items:flex-start; gap:9px; margin-top:14px; padding:13px; border-radius:9px; color:var(--app-text-secondary); background:var(--app-primary-light); font-size:12px; line-height:1.85; }
.upload-attempt-note > .el-icon { flex:0 0 auto; margin-top:3px; color:var(--app-primary); }
.upload-attempt-note > div { min-width:0; }.upload-attempt-note strong { font-size:12px; color:var(--app-text); font-weight:550; }
.upload-attempt-note p { margin:5px 0 0; overflow-wrap:anywhere; }.upload-attempt-note button { margin:5px 0 0; }
.capture-read-error button:disabled, .upload-attempt-note button:disabled { color:var(--app-text-muted); opacity:.6; cursor:default; }
.capture-read-error button:focus-visible, .upload-attempt-note button:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
</style>
