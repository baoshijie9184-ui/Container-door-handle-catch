<template>
  <div class="page-shell upload-container">
    <PageHero title="图片上传" />
    <InspectionFlowNav />

    <!-- 断点续传提示卡片 -->
    <el-alert
      v-if="resumeTaskInfo && !uploadingToOss"
      class="resume-alert"
      type="warning"
      show-icon
      :closable="false"
    >
      <template #default>
        <div class="resume-content">
          <div>
            <strong>继续上传</strong>
            <p>
              「{{ recordFolderLabel(resumeTaskInfo) }}」
              已完成 {{ resumeTaskInfo.uploadedCount }}/{{ resumeTaskInfo.totalCount }} 张，
              {{ resumeTaskInfo.failedCount > 0 ? `失败 ${resumeTaskInfo.failedCount} 张，` : '' }}
              请重新选择同一文件夹继续上传。
            </p>
          </div>
          <div class="resume-actions">
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
      <el-card class="upload-card upload-editor" shadow="never">
        <template #header><h2 class="upload-card-title">新建上传批次</h2></template>
        <el-form label-position="top" @submit.prevent>
          <section aria-label="本次上传图片">
            <input
              ref="folderInput"
              type="file"
              webkitdirectory
              directory
              multiple
              hidden
              @change="handleFolderSelect"
            />
            <button v-if="!folderInfo.imageCount" type="button" class="folder-picker" aria-labelledby="upload-folder-label" aria-describedby="upload-image-format" :disabled="uploadingToOss" @click="triggerFolderSelect">
              <span class="folder-picker-icon"><el-icon><FolderOpened /></el-icon></span>
              <strong id="upload-folder-label">选择图片文件夹</strong>
              <span id="upload-image-format">支持 JPG、JPEG、PNG，会自动读取文件夹内的 metadata.json</span>
            </button>
            <template v-else>
              <div class="selected-folder">
                <span class="selected-folder-icon"><el-icon><FolderOpened /></el-icon></span>
                <div class="selected-folder-name">
                  <strong :title="folderInfo.name">{{ imageFolderLabel(folderInfo.name) || folderInfo.imageFolderName || '所选文件夹' }}</strong>
                  <span>{{ folderInfo.imageCount }} 张图片</span>
                </div>
                <el-button class="replace-folder" :disabled="uploadingToOss" @click="triggerFolderSelect">更换文件夹</el-button>
              </div>
              <p v-if="selectionNotice" class="upload-selection-note" role="status">{{ selectionNotice }}</p>
              <SelectedImageFiles :key="selectionVersion" :files="folderInfo.files" :scope-key="accountScope()" />
            </template>
          </section>

          <section v-if="folderInfo.imageCount" class="capture-options" aria-labelledby="upload-capture-heading">
            <div class="capture-options-header">
              <h3 id="upload-capture-heading" class="capture-meta-heading">采集信息</h3>
              <el-button link type="primary" aria-controls="upload-capture-fields" :aria-expanded="captureExpanded" @click="captureExpanded=!captureExpanded">{{ captureExpanded ? '收起采集信息' : '编辑采集信息' }}</el-button>
            </div>
            <div class="capture-json-row">
              <input ref="metadataInput" type="file" accept="application/json,.json" hidden @change="chooseMetadata" />
              <div class="capture-json-state">
                <AppIcon name="Document" :size="16" />
                <span v-if="metadataReading" role="status">正在读取 JSON…</span>
                <span v-else-if="metadataName" role="status">已导入 {{ metadataName }}<template v-if="batchMetadata.images.length"> · {{ batchMetadata.images.length }} 张有图片资料</template></span>
                <span v-else>采集资料 JSON</span>
              </div>
              <div class="capture-json-actions">
                <el-button link type="primary" :disabled="uploadingToOss || uploadAttempted || metadataReading" @click="metadataInput?.click()">{{ metadataName ? '更换 JSON' : '导入 JSON' }}</el-button>
                <el-button v-if="!metadataName" link :disabled="metadataReading" @click="downloadTemplate">下载模板</el-button>
                <el-button v-if="metadataName || metadataError" link :disabled="uploadingToOss || uploadAttempted" @click="clearMetadata">移除 JSON</el-button>
              </div>
            </div>
            <p v-if="metadataError" class="capture-read-error" role="alert">{{ metadataError }}</p>
            <dl v-if="!captureExpanded" class="capture-summary">
              <div><dt>采集日期</dt><dd>{{ folderInfo.captureDate || '待填写' }}</dd></div>
              <div><dt>城市</dt><dd>{{ folderInfo.region || '待填写' }}</dd></div>
              <div><dt>采集员</dt><dd>{{ collectorLabel || '待填写' }}</dd></div>
              <div><dt>采集设备</dt><dd>{{ folderInfo.deviceName || '待填写' }}</dd></div>
              <div class="capture-batch-name"><dt>批次名称</dt><dd>{{ folderInfo.imageFolderName || '待填写' }}</dd></div>
            </dl>
            <div v-show="captureExpanded" id="upload-capture-fields" class="capture-meta-form" role="group" aria-labelledby="upload-capture-heading">
              <el-form-item label="采集日期" required>
                <el-date-picker
                  v-model="folderInfo.captureDate"
                  :disabled="uploadingToOss || uploadAttempted"
                  value-format="YYYY-MM-DD"
                  aria-label="采集日期" placeholder="选择采集日期"
                  />
              </el-form-item>
              <el-form-item label="城市" required>
                <el-select v-model="folderInfo.region" filterable aria-label="采集城市" placeholder="选择采集城市"
                  :loading="loadingCities" :disabled="uploadingToOss || uploadAttempted || !collectionCities.length">
                  <el-option v-for="city in collectionCities" :key="city" :label="city" :value="city" />
                </el-select>
                <p v-if="cityError" class="capture-read-error" role="alert">采集城市读取失败<button type="button" @click="loadCities">重新读取</button></p>
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
                    :value="emp.employeeNumber"
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
              <el-form-item label="批次名称" required class="capture-batch-name">
                <el-input v-model="folderInfo.imageFolderName" :disabled="uploadingToOss || uploadAttempted" aria-label="图片文件夹名称" placeholder="输入批次名称" />
              </el-form-item>
            </div>
          </section>

          <div v-if="folderInfo.imageCount || uploadingToOss" class="upload-footer">
            <div v-if="folderInfo.imageCount && (!uploadAttempted || uploadingToOss)" class="upload-submit-row">
              <p v-if="missingCaptureFields.length" id="upload-readiness" class="upload-readiness" role="status"><AppIcon name="Warning" :size="16" />请补全{{ missingCaptureFields.join('、') }}</p>
              <el-button type="primary" class="upload-action" size="large"
                :aria-describedby="missingCaptureFields.length ? 'upload-readiness' : undefined"
                :disabled="uploadingToOss || metadataReading || !!metadataError || !!missingCaptureFields.length || uploadAttempted"
                :loading="uploadingToOss" @click="handleUploadBatch">
                <el-icon v-if="!uploadingToOss"><UploadFilled /></el-icon>
                {{ uploadingToOss ? '正在上传原图…' : '上传原图并提交检测' }}
              </el-button>
            </div>
            <Transition name="upload-feedback"><div v-if="uploadingTask" class="upload-progress-card">
              <div class="upload-progress-header">
                <span>{{ recordFolderLabel(uploadingTask) }}</span>
                <span>{{ uploadingTask.imageCount }} 张</span>
              </div>
              <el-progress :percentage="uploadingTask.progressPercent" :stroke-width="8" />
              <p class="upload-progress-msg">{{ uploadingTask.message }}</p>
            </div></Transition>
            <div v-if="uploadAttempted && !uploadingToOss" class="upload-attempt-note" role="status">
              <router-link :to="{path:'/inspection/uploads/mine',query:registeredTaskId ? {keyword:registeredTaskId} : {}}">{{ registeredTaskId ? '查看本次上传记录' : '查看我的上传记录' }}</router-link>
              <el-button @click="resetBatchState">清空本次选择</el-button>
            </div>
          </div>

        </el-form>
      </el-card>

      <!-- 上传历史 -->
      <el-card class="upload-card history-card" shadow="never">
        <template #header>
          <div class="card-title-row">
            <h2 class="upload-card-title">最近上传</h2>
            <el-button class="refresh-history" size="small" :loading="refreshing || historyLoading" @click="refreshHistory" title="刷新上传历史" aria-label="刷新上传历史">
              <template #icon><el-icon><Refresh /></el-icon></template>
            </el-button>
          </div>
        </template>
        <!-- 搜索和筛选栏 -->
        <div class="history-search-bar">
          <el-input
            id="upload-history-keyword"
            v-model="searchKeyword"
            aria-label="搜索任务ID或文件夹名…" placeholder="搜索任务ID或文件夹名…"
            clearable
            class="history-search-input"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button aria-controls="upload-history-filters" :aria-expanded="advancedFiltersOpen" @click="advancedFiltersOpen=!advancedFiltersOpen">
            <AppIcon name="Filter" :size="15" />筛选
          </el-button>
        </div>
        <div v-show="advancedFiltersOpen" id="upload-history-filters" class="history-fields">
          <label class="upload-history-filter" for="upload-history-status"><span>处理阶段</span>
            <el-select id="upload-history-status" v-model="statusFilter" aria-label="全部状态" placeholder="全部状态" clearable>
              <el-option label="全部状态" value="" />
              <el-option label="上传中" value="UPLOADING" />
              <el-option label="已上传" value="UPLOADED" />
              <el-option label="已排队" value="QUEUED" />
              <el-option label="检测中" value="DETECTING" />
              <el-option label="已完成" value="COMPLETED" />
              <el-option label="失败" value="FAILED" />
            </el-select>
          </label>
          <label class="upload-history-filter" for="upload-history-date"><span>最近更新日期</span>
            <el-date-picker id="upload-history-date" v-model="filterDate" aria-label="选择日期" placeholder="选择日期" value-format="YYYY-MM-DD" clearable />
          </label>
        </div>
        <div class="upload-history-scope">
          <span role="status">{{ historyLoading ? '正在读取…' : hasHistoryFilters ? `匹配 ${uploadHistory.length} 条已加载记录` : `已加载 ${uploadTasks.length} 条` }}</span>
          <el-button v-if="hasHistoryFilters && uploadHistory.length" link size="small" @click="resetHistoryFilters">清空筛选</el-button>
        </div>
        <el-alert v-if="historyError && uploadHistory.length" :title="historyError + '；以下为先前已加载的记录，请刷新核对。'" type="error" show-icon :closable="false" />
        <CollectionEmptyState
          v-if="uploadHistory.length === 0"
          :loading="historyLoading"
          :error="historyError"
          :filtered="hasHistoryFilters"
          empty-title="暂无上传记录"
          empty-description="上传批次后可在这里查看进度。"
          @retry="refreshHistory"
          @reset="resetHistoryFilters"
        />
        <div v-else class="history-list">
          <div
            v-for="task in visibleHistory"
            :key="task.taskId"
            class="history-item"
          >
            <!-- 第一行：名称 + 数量 + 状态 -->
            <div class="history-item-row1">
              <span class="history-item-folder" :title="recordFolderLabel(task)">{{ recordFolderLabel(task) }}</span>
              <el-tag :type="taskStore.taskTagType(task)" class="history-item-tag">
                {{ taskStore.taskTagText(task) }}
              </el-tag>
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
                {{ formatUploadTime(task.updatedAt || task.createdAt) }}
              </span>
            </div>
            <!-- 操作按钮 -->
            <div class="history-item-actions">
              <FolderMetadataLink :task-id="task.taskId" />
              <el-button v-if="task.stage === 'uploading' && task.uploadConfirmation" link type="primary"
                :loading="uploadingToOss && activeUploadTaskId===task.taskId" :disabled="uploadingToOss"
                @click="uploadStore.retryUploadConfirmation(task.taskId)">重试上传确认</el-button>
              <router-link
                v-if="task.stage === 'uploaded' || task.stage === 'queued' || task.stage === 'detecting' || task.stage === 'completed'"
                :to="assignedTrace(task.taskId)"
                class="upload-next-link"
              >
                <el-icon aria-hidden="true"><Right /></el-icon>{{ task.stage === 'completed' ? '查看检测结果' : '查看检测进度' }}
              </router-link>
              <el-button link size="small" :loading="removeCacheBusy===task.taskId" :disabled="uploadingToOss || !!removeCacheBusy" @click="removeCachedUploadTask(task)">
                <el-icon><Delete /></el-icon>清除本机缓存
              </el-button>
            </div>
          </div>
        </div>
        <div class="history-footer">
          <el-button v-if="uploadHistory.length > historyPreviewSize" link @click="showFullHistory=!showFullHistory">{{ showFullHistory ? '收起记录' : '显示更多已加载记录' }}</el-button>
          <router-link class="upload-next-link" to="/inspection/uploads/all">全部上传记录<AppIcon name="ArrowRight" :size="14" /></router-link>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import InspectionFlowNav from '@/components/InspectionFlowNav.vue'
import { assignedTrace } from '@/utils/taskBoardNavigation'
import FolderMetadataLink from '@/components/FolderMetadataLink.vue'
import { imageFolderLabel, recordFolderLabel } from '@/utils/imageFolderLabel'
import { downloadMetadata, folderRoot, MAX_METADATA_BYTES, parseUploadMetadata } from '@/utils/uploadMetadata'
import { computed, onMounted, onBeforeUnmount, reactive, ref, toRaw } from 'vue'
import { storeToRefs } from 'pinia'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleCheck, Clock, Delete, FolderOpened, Refresh, Right, Search, UploadFilled, Warning } from '@element-plus/icons-vue'
import { fetchCollectionCities, fetchDevicesForSelect, fetchEmployeesForSelect } from '../api/resourceOptions'
import { useTaskStore, useUploadStore, usePollingStore } from '../stores/detectionTask'
import { isBatchUploadTask } from '../stores/taskStore'
import { beijingDateTime, businessTimestamp } from '../utils/beijingTime'
import CollectionEmptyState from '../components/CollectionEmptyState.vue'
import SelectedImageFiles from '../components/SelectedImageFiles.vue'
import { useUserStore } from '../stores/user'

const taskStore = useTaskStore()
const userStore = useUserStore()
const uploadStore = useUploadStore()
const pollingStore = usePollingStore()
const { uploadingToOss, activeUploadTaskId } = storeToRefs(uploadStore)
const { taskList } = storeToRefs(taskStore)

const folderInput = ref(null)
const metadataInput = ref(null)
const resumeFolderInput = ref(null)
const batchMetadata=ref({notes:'',images:[]}), metadataName=ref(''), metadataError=ref(''), metadataReading=ref(false)
const captureExpanded=ref(true), selectionVersion=ref(0)
let metadataRead=0
const collectionCities = ref([])
const loadingCities = ref(false)
const cityError = ref(false)
let folderCityHint = ''
const employeeList = ref([])
const deviceList = ref([])
const loadingEmployees = ref(false)
const loadingDevices = ref(false)
const employeeError = ref(''), deviceError = ref(''), selectionNotice = ref(''), uploadAttempted = ref(false)
const registeredTaskId = ref('')
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
const advancedFiltersOpen = ref(false)
const showFullHistory = ref(false)
const historyPreviewSize = 4
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

const collectorLabel = computed(() => {
  const employee = employeeList.value.find(item => item.employeeNumber === folderInfo.collector)
  return employee ? `${employee.name}（${employee.employeeNumber}）` : folderInfo.collector
})

const missingCaptureFields = computed(() => [
  ['captureDate', '采集日期'], ['region', '城市'], ['collector', '采集员'],
  ['deviceName', '采集设备'], ['imageFolderName', '批次名称']
].filter(([key]) => {
  if (!String(folderInfo[key] || '').trim()) return true
  if (key==='region') return !collectionCities.value.includes(folderInfo.region)
  if (!metadataName.value) return false
  if (key==='collector') return !employeeList.value.some(item=>item.employeeNumber===folderInfo.collector)
  if (key==='deviceName') return !deviceList.value.some(item=>item.deviceCode===folderInfo.deviceName)
  return false
}).map(([, label]) => label))

// 当前正在上传的任务
const uploadingTask = computed(() => {
  return uploadingToOss.value && activeUploadTaskId.value
    ? taskList.value.find(task => task.taskId === activeUploadTaskId.value && task.stage === 'uploading') || null
    : null
})

const uploadTasks = computed(() => taskList.value.filter(task => isBatchUploadTask(task) || (!task.taskType && task.uploadConfirmation)))

// 上传历史：根据搜索条件过滤
const uploadHistory = computed(() => {
  let list = [...uploadTasks.value]

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

  list.sort((a, b) => businessTimestamp(b.createdAt) - businessTimestamp(a.createdAt) || b.taskId.localeCompare(a.taskId))

  return list
})
const visibleHistory = computed(() => showFullHistory.value ? uploadHistory.value : uploadHistory.value.slice(0, historyPreviewSize))

function cityFromFolder(value) {
  return collectionCities.value.find(city => city === value || city.slice(0, -1) === value) || ''
}

async function loadCities() {
  if (loadingCities.value) return
  loadingCities.value = true
  cityError.value = false
  try {
    const { data } = await fetchCollectionCities()
    if (data?.code !== 200 || !Array.isArray(data.data) || !data.data.length) throw new Error()
    if (!pageActive) return
    collectionCities.value = data.data
    folderInfo.region = cityFromFolder(folderInfo.region || folderCityHint) || folderInfo.region
  } catch {
    if (pageActive) cityError.value = true
  } finally {
    loadingCities.value = false
  }
}

const triggerFolderSelect = () => {
  if (uploadingToOss.value || !folderInput.value) return
  folderInput.value.value = ''
  folderInput.value.click()
}

function clearMetadata() {
  metadataRead++
  metadataName.value='';metadataError.value='';metadataReading.value=false
  batchMetadata.value={notes:'',images:[]}
  captureExpanded.value=true
}

async function readMetadata(file) {
  const read=++metadataRead, scope=accountScope()
  const current=()=>pageActive && read===metadataRead && scope===accountScope()
  metadataReading.value=true
  metadataError.value=''
  try {
    if (file.size>MAX_METADATA_BYTES) throw new Error('JSON 文件不能超过 256 KB')
    const contents=await file.text()
    if (!current()) return
    const {captureInfo,notes,images}=parseUploadMetadata(contents,folderInfo.files,folderRoot(folderInfo.files))
    if (captureInfo.region) captureInfo.region=cityFromFolder(captureInfo.region) || captureInfo.region
    Object.assign(folderInfo,captureInfo)
    batchMetadata.value={notes,images}
    metadataName.value=file.name
    captureExpanded.value=missingCaptureFields.value.length>0
  } catch (error) {
    if (current()) metadataError.value=error.message || 'JSON 文件暂不可读取'
  } finally {
    if (current()) metadataReading.value=false
  }
}

function chooseMetadata(event) {
  const file=event.target.files?.[0]
  event.target.value=''
  if (file && !uploadingToOss.value && !uploadAttempted.value) readMetadata(file)
}

function downloadTemplate() {
  const {captureDate,region,collector,deviceName,imageFolderName,files}=folderInfo
  const root=folderRoot(files)
  downloadMetadata({schemaVersion:1,captureInfo:{captureDate,region,collector,deviceName,imageFolderName},notes:'',
    images:files.map(file=>({path:root ? file.relativePath.slice(root.length+1) : file.relativePath,notes:''}))})
}

const handleFolderSelect = (event) => {
  if (uploadingToOss.value) return
  const files = Array.from(event.target.files || [])
  const imageFiles = files.filter(file => ['image/jpeg', 'image/png', 'image/jpg'].includes(file.type))
  if (!imageFiles.length) {
    ElMessage.warning('所选文件夹中没有可用图片')
    return
  }
  clearMetadata()
  selectionVersion.value++
  uploadAttempted.value = false
  registeredTaskId.value = ''

  // Only the shared directory describes the selection when several subfolders are chosen.
  const dirSegments = (imageFiles[0].webkitRelativePath || '').split('/').slice(0, -1)
  for (const entry of imageFiles) {
    const parts = (entry.webkitRelativePath || '').split('/').slice(0, -1)
    let shared = 0
    while (shared < dirSegments.length && dirSegments[shared] === parts[shared]) shared++
    dirSegments.length = shared
  }
  const autoParse = dirSegments.length >= 5
  folderInfo.name = dirSegments.join('/')
  folderInfo.imageCount = imageFiles.length
  folderInfo.captureDate = autoParse ? (dirSegments[0] || '') : ''
  folderCityHint = autoParse ? dirSegments[1] : ''
  folderInfo.region = cityFromFolder(folderCityHint)
  const collectorField = autoParse ? dirSegments[2] : ''
  const candidates = employeeList.value.filter(person => person.employeeNumber===collectorField || person.name===collectorField)
  folderInfo.collector = candidates.length===1 ? candidates[0].employeeNumber : ''
  folderInfo.deviceName = autoParse ? (dirSegments[3] || '') : ''
  folderInfo.imageFolderName = autoParse ? (dirSegments[4] || '') : ''

  folderInfo.files = imageFiles.map(file => ({
    file,
    fileName: file.name,
    contentType: file.type || 'image/jpeg',
    relativePath: file.webkitRelativePath || file.name,
    fileSize: file.size
  }))
  const root=folderRoot(folderInfo.files)
  const metadata=files.filter(file => (file.webkitRelativePath || file.name).toLowerCase()===(root ? `${root}/metadata.json` : 'metadata.json').toLowerCase())
  const skipped=files.length-imageFiles.length-metadata.length
  selectionNotice.value=skipped ? `${skipped} 个其他文件未列入上传` : ''
  if (metadata.length===1) readMetadata(metadata[0])
  if (metadata.length>1) metadataError.value='文件夹内有多个同名 JSON，请选择其中一份导入'
}

const handleUploadBatch = () => {
  if (uploadingToOss.value || uploadAttempted.value || metadataReading.value || metadataError.value) return
  if (!folderInfo.files.length) {
    ElMessage.error('请先选择图片文件夹')
    return
  }
  if (missingCaptureFields.value.length) {
    ElMessage.error('请先确认采集日期、城市、采集员、采集设备和图片文件夹名称')
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
  const scope = accountScope()
  uploadStore.uploadBatchToOss(filesData, captureInfo, taskId => {
    if (pageActive && scope === accountScope()) registeredTaskId.value = taskId
  }, { rootDirectory:folderRoot(filesData), ...toRaw(batchMetadata.value) })
}

const resetBatchState = () => {
  if (uploadingToOss.value) return
  clearMetadata()
  uploadAttempted.value = false
  registeredTaskId.value = ''
  selectionNotice.value = ''
  if (folderInput.value) folderInput.value.value = ''
  folderInfo.name = ''
  folderInfo.imageCount = 0
  folderInfo.captureDate = ''
  folderCityHint = ''
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
    fetchDevices(),
    loadCities()
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
.upload-container { display:grid; }

.upload-grid {
  display:grid;
  grid-template-columns:minmax(0,1.55fr) minmax(0,1fr);
  align-items:start;
  gap:20px;
}

.upload-card { min-width:0; }
.upload-card-title {
  margin:0;
  color:var(--app-text);
  font-size:var(--app-font-section);
  font-weight:650;
}

.resume-alert { border-radius:var(--app-radius-sm); }
.resume-alert :deep(.el-alert__content) { flex:1; }
.resume-content,.resume-actions {
  display:flex;
  align-items:center;
  flex-wrap:wrap;
  gap:8px 12px;
}
.resume-content { justify-content:space-between; padding-right:12px; }
.resume-content p { margin:3px 0 0; overflow-wrap:anywhere; }
.resume-actions :deep(.el-button) { margin:0; }

.folder-picker {
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:center;
  gap:9px;
  width:100%;
  min-height:184px;
  padding:24px;
  border:1px dashed var(--app-border-focus);
  border-radius:var(--app-radius-md);
  background:var(--app-primary-light);
  color:var(--app-primary-deep);
  font:inherit;
  text-align:center;
  cursor:pointer;
}
.folder-picker:hover:not(:disabled) {
  border-color:var(--app-primary);
  background:var(--app-primary-soft);
}
.folder-picker:disabled { cursor:not-allowed; opacity:.6; }
.folder-picker strong { font-size:16px; font-weight:650; }
#upload-image-format { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.folder-picker-icon,.selected-folder-icon {
  display:grid;
  place-items:center;
  flex:none;
  width:44px;
  height:44px;
  border-radius:var(--app-radius-sm);
  color:var(--app-primary);
  background:var(--app-primary-soft);
  font-size:23px;
}
.selected-folder {
  display:flex;
  align-items:center;
  gap:12px;
  padding:12px;
  border:1px solid var(--app-border);
  border-radius:var(--app-radius-sm);
  background:var(--app-primary-light);
}
.selected-folder-name {
  display:grid;
  flex:1;
  gap:3px;
  min-width:0;
}
.selected-folder-name strong {
  font-size:14px;
  font-weight:650;
  color:var(--app-text);
  overflow-wrap:anywhere;
}
.selected-folder-name span { font-size:12px; color:var(--app-text-secondary); }
.upload-selection-note { margin:9px 0 0; color:var(--app-text-secondary); font-size:12px; }

.capture-options {
  margin-top:14px;
  padding-top:14px;
  border-top:1px solid var(--app-border);
  container-type:inline-size;
}
.capture-options-header,.capture-json-row,.capture-json-state,.capture-json-actions {
  display:flex;
  align-items:center;
  flex-wrap:wrap;
  gap:6px 12px;
}
.capture-options-header,.capture-json-row { justify-content:space-between; }
.capture-meta-heading { margin:0; color:var(--app-text); font-size:15px; font-weight:650; }
.capture-json-row {
  margin-top:7px;
  padding:4px 10px;
  border-radius:var(--app-radius-sm);
  background:var(--app-surface-muted);
}
.capture-json-state {
  flex:1 1 180px;
  align-items:flex-start;
  flex-wrap:nowrap;
  gap:7px;
  min-width:0;
  color:var(--app-text-secondary);
  font-size:12px;
  line-height:1.8;
  overflow-wrap:anywhere;
}
.capture-json-state > .el-icon { flex:none; margin-top:3px; color:var(--app-primary); }
.capture-json-actions :deep(.el-button) { margin:0; }
.capture-option-detail { margin-left:8px; color:var(--app-text-secondary); font-size:12px; }
.capture-summary,.capture-meta-form {
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:10px 16px;
  margin:14px 0 0;
}
.capture-summary { grid-template-columns:repeat(4,minmax(0,1fr)); }
.capture-summary > div { min-width:0; }
.capture-summary dt { color:var(--app-text-secondary); font-size:12px; }
.capture-summary dd {
  margin:4px 0 0;
  font-size:13px;
  font-weight:550;
  color:var(--app-text);
  overflow-wrap:anywhere;
}
.capture-batch-name { grid-column:1/-1; }
.capture-meta-form :deep(.el-form-item) { min-width:0; margin:0; }
.capture-meta-form :deep(.el-form-item__label) { margin-bottom:6px; }
.capture-meta-form :deep(.el-select),.capture-meta-form :deep(.el-date-editor.el-input) { width:100%; }
.capture-read-error {
  flex-basis:100%;
  margin:7px 0 0;
  color:var(--app-warning);
  font-size:12px;
  line-height:1.8;
  overflow-wrap:anywhere;
}
.capture-read-error button {
  margin-left:7px;
  padding:3px 0;
  border:0;
  background:transparent;
  color:var(--app-primary);
  font:inherit;
  cursor:pointer;
}
.capture-read-error button:disabled { color:var(--app-text-muted); cursor:default; }

.upload-footer { margin-top:18px; padding-top:14px; border-top:1px solid var(--app-border); }
.upload-submit-row,.upload-attempt-note {
  display:flex;
  align-items:center;
  justify-content:flex-end;
  flex-wrap:wrap;
  gap:8px 12px;
}
.upload-readiness {
  display:flex;
  align-items:flex-start;
  flex:1 1 200px;
  gap:6px;
  margin:0;
  color:var(--app-warning);
  font-size:12px;
  line-height:1.8;
}
.upload-readiness > .el-icon { flex:none; margin-top:3px; }
.upload-action { min-width:176px; }
.upload-attempt-note { justify-content:space-between; }
.upload-attempt-note a { font-size:13px; }

.upload-progress-card {
  display:grid;
  gap:8px;
  padding:13px;
  border:1px solid var(--app-border);
  border-radius:var(--app-radius-sm);
  background:var(--app-primary-light);
}
.upload-submit-row + .upload-progress-card { margin-top:12px; }
.upload-progress-header {
  display:flex;
  align-items:center;
  justify-content:space-between;
  flex-wrap:wrap;
  gap:8px;
  color:var(--app-text);
  font-weight:600;
  overflow-wrap:anywhere;
}
.upload-progress-msg { margin:0; color:var(--app-text-secondary); font-size:12px; }
.upload-feedback-enter-active,.upload-feedback-leave-active { transition:opacity var(--app-transition-base); }
.upload-feedback-enter-from,.upload-feedback-leave-to { opacity:0; }

.card-title-row,.history-search-bar,.upload-history-scope,.history-footer {
  display:flex;
  align-items:center;
  gap:8px;
}
.card-title-row,.upload-history-scope { justify-content:space-between; }
.refresh-history:not(.is-loading) { width:32px; padding-inline:0; }
.history-search-input { min-width:0; }
.history-search-bar > .el-button { margin:0; }
.history-fields {
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:9px;
  margin-top:10px;
}
.upload-history-filter { display:grid; gap:5px; min-width:0; color:var(--app-text-secondary); font-size:12px; }
.upload-history-filter :deep(.el-date-editor.el-input) { width:100%; }
.upload-history-scope {
  min-height:28px;
  margin-top:6px;
  color:var(--app-text-secondary);
  font-size:12px;
}
.history-card :deep(.collection-empty) { min-height:180px; padding:18px 12px; }
.history-list { margin-top:2px; }
.history-item {
  padding:12px 0 9px;
  border-top:1px solid var(--app-border);
}
.history-item-row1,.history-item-row2,.history-item-actions {
  display:flex;
  align-items:center;
  flex-wrap:wrap;
  gap:6px 8px;
}
.history-item-row1 { justify-content:space-between; }
.history-item-folder {
  flex:1 1 160px;
  min-width:0;
  color:var(--app-text);
  font-size:14px;
  font-weight:600;
  overflow-wrap:anywhere;
}
.history-item-tag { flex:none; }
.history-item-row2 { margin-top:6px; color:var(--app-text-secondary); font-size:12px; }
.history-item-status { display:inline-flex; align-items:flex-start; gap:4px; min-width:0; overflow-wrap:anywhere; }
.history-item-status > .el-icon { flex:none; margin-top:2px; }
.history-item-status.status-error { color:var(--app-danger); }
.history-item-status.status-warn { color:var(--app-warning); }
.history-item-status.status-ok { color:var(--app-success); }
.history-item-time { margin-left:auto; }
.history-item-actions { gap:4px 8px; margin-top:4px; }
.history-item-actions :deep(.el-button) { margin:0; padding-inline:4px; font-size:12px; }
.upload-next-link {
  display:inline-flex;
  align-items:center;
  gap:5px;
  min-height:30px;
  padding:0 4px;
  border-radius:var(--app-radius-xs);
  color:var(--app-primary);
  font-size:12px;
  text-decoration:none;
}
.upload-next-link:hover { background:var(--app-primary-soft); }
.history-footer {
  justify-content:flex-end;
  flex-wrap:wrap;
  padding-top:9px;
  border-top:1px solid var(--app-border);
}
.history-footer > .el-button { margin-right:auto; }

@container (max-width:480px) {
  .capture-summary { grid-template-columns:repeat(2,minmax(0,1fr)); }
}
@media (max-width:1000px) {
  .upload-grid { grid-template-columns:minmax(0,1fr); }
}
@media (max-width:500px) {
  .upload-grid { gap:16px; }
  .folder-picker { min-height:158px; padding:15px; }
  .selected-folder { gap:8px; padding:9px; }
  .selected-folder-icon { width:34px; height:34px; font-size:19px; }
  .replace-folder { padding-inline:8px; font-size:12px; }
  .capture-meta-form { gap:9px; }
  .capture-json-row { padding:6px 9px; }
  .upload-submit-row { align-items:stretch; flex-direction:column; }
  .upload-readiness { flex:auto; }
  .upload-action { width:100%; }
  .history-item-time { margin-left:0; }
}
@media (prefers-reduced-motion:reduce) {
  .upload-feedback-enter-active,.upload-feedback-leave-active { transition:none; }
}
</style>
