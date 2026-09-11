<template>
  <div class="page-shell model-page">
    <section class="page-hero">
      <div>
        <span class="page-hero-label">Model Registry</span>
        <h1 class="page-hero-title">ONNX 模型管理</h1>
        <p class="page-hero-text">
          集中维护上传模型、版本说明与历史记录，方便模型回溯、替换和统一管理。
        </p>
      </div>

      <div class="panel-actions">
        <el-button type="primary" @click="handleUpload">上传模型</el-button>
      </div>
    </section>

    <section class="toolbar-panel">
      <el-form :inline="true" :model="searchForm" class="toolbar-grid">
        <el-form-item label="模型 ID">
          <el-input v-model="searchForm.modelId" placeholder="请输入模型 ID" clearable />
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model="searchForm.modelName" placeholder="请输入模型名称" clearable />
        </el-form-item>
        <el-form-item label="版本号">
          <el-input v-model="searchForm.version" placeholder="请输入版本号" clearable />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="searchForm.status" placeholder="全部状态" clearable style="width: 140px">
            <el-option label="草稿" value="DRAFT" />
            <el-option label="待发布" value="READY" />
            <el-option label="已发布" value="PUBLISHED" />
            <el-option label="已停用" value="DISABLED" />
            <el-option label="已归档" value="ARCHIVED" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSearch">查询</el-button>
          <el-button @click="resetSearch">重置</el-button>
        </el-form-item>
      </el-form>
    </section>

    <section v-if="defaultModel" class="default-model-banner">
      <div>
        <div class="default-model-label">当前默认模型</div>
        <div class="default-model-name">
          {{ defaultModel.modelName }}
          <span class="default-model-version">v{{ defaultModel.version }}</span>
        </div>
      </div>
      <div class="default-model-meta">
        <span>状态：{{ statusLabelMap[defaultModel.status] || defaultModel.status }}</span>
        <span>使用次数：{{ defaultModel.usageCount ?? 0 }}</span>
        <span>最近使用：{{ formatDateTime(defaultModel.lastUsedAt) || '--' }}</span>
      </div>
    </section>

    <!-- 统计摘要 -->
    <section v-if="!loading && total > 0" class="stats-bar">
      <div class="stats-bar-item">
        <div class="stats-bar-icon primary">
          <span style="font-size:20px;font-weight:700">{{ total }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ total }}</div>
          <div class="stats-bar-label">模型总数</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon success">
          <span style="font-size:20px;font-weight:700">{{ publishedCount }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ publishedCount }}</div>
          <div class="stats-bar-label">已发布模型</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon warning">
          <span style="font-size:20px;font-weight:700">{{ totalUsageCount }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ totalUsageCount }}</div>
          <div class="stats-bar-label">累计使用次数</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon slate">
          <span style="font-size:20px;font-weight:700">{{ evaluatedCount }}</span>
        </div>
        <div>
          <div class="stats-bar-value">{{ evaluatedCount }}</div>
          <div class="stats-bar-label">已评估模型</div>
        </div>
      </div>
    </section>

    <section class="table-panel">
      <el-table :data="modelList" v-loading="loading" border style="width: 100%">
        <template #empty>
          <el-empty :description="hasSearch ? '没有匹配的模型，请调整搜索条件' : '暂无模型数据，点击上方按钮上传'" :image-size="80" />
        </template>
        <el-table-column prop="modelId" label="模型 ID" width="220" />
        <el-table-column prop="modelName" label="模型名称" min-width="180" show-overflow-tooltip />
        <el-table-column prop="version" label="版本号" width="120" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusTypeMap[row.status] || 'info'">
              {{ statusLabelMap[row.status] || row.status || '未知' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="默认模型" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.isDefault" type="success">默认</el-tag>
            <span v-else>--</span>
          </template>
        </el-table-column>
        <el-table-column prop="usageCount" label="使用次数" width="100" />
        <el-table-column label="最近使用" min-width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.lastUsedAt) || '--' }}
          </template>
        </el-table-column>
        <el-table-column label="校验状态" width="120">
          <template #default="{ row }">
            <el-tag :type="validationTypeMap[row.validationStatus] || 'info'">
              {{ validationLabelMap[row.validationStatus] || row.validationStatus || '未知' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="MLOps" width="130">
          <template #default="{ row }">
            <el-tag :type="mlopsStatusTypeMap[row.mlopsStatus] || 'info'">
              {{ mlopsStatusLabelMap[row.mlopsStatus] || row.mlopsStatus || '未评估' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="mAP/F1" width="130">
          <template #default="{ row }">
            {{ formatMetric(row.mapScore) }} / {{ formatMetric(row.f1Score) }}
          </template>
        </el-table-column>
        <el-table-column label="部署策略" width="130">
          <template #default="{ row }">
            {{ deploymentStrategyLabelMap[row.deploymentStrategy] || row.deploymentStrategy || '全量' }}
            <span v-if="row.deploymentStrategy === 'CANARY'"> {{ row.canaryPercent ?? 0 }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="上传时间" min-width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.uploadTime) }}
          </template>
        </el-table-column>
        <el-table-column prop="updateDescription" label="更新说明" min-width="220" show-overflow-tooltip />
        <el-table-column label="操作" width="420" fixed="right">
          <template #default="{ row }">
            <div class="operation-buttons">
              <el-button size="small" @click="handleViewDetails(row)">详情</el-button>
              <el-button size="small" @click="handleEdit(row)">编辑</el-button>
              <el-button size="small" type="primary" plain @click="openEvaluationDialog(row)">评估</el-button>
              <el-button size="small" type="primary" plain @click="openRolloutDialog(row)">部署</el-button>
              <el-button v-if="row.status !== 'PUBLISHED'" size="small" type="success" @click="handleLifecycleAction(row.modelId, 'publish')">发布</el-button>
              <el-button v-if="!row.isDefault && row.status === 'PUBLISHED'" size="small" type="warning" @click="handleLifecycleAction(row.modelId, 'set-default')">设为默认</el-button>
              <el-button v-if="row.status !== 'ARCHIVED'" size="small" type="primary" plain @click="handleLifecycleAction(row.modelId, 'validate')">重新校验</el-button>
              <el-button v-if="row.status === 'PUBLISHED'" size="small" @click="handleLifecycleAction(row.modelId, 'disable')">停用</el-button>
              <el-button v-if="row.status !== 'ARCHIVED'" size="small" @click="handleLifecycleAction(row.modelId, 'archive')">归档</el-button>
              <el-popconfirm v-if="!row.usageCount" title="确定删除该模型吗？" @confirm="handleDelete(row.modelId)">
                <template #reference>
                  <el-button size="small" type="danger">删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="page-footer">
        <el-pagination
          v-model:current-page="pagination.current"
          v-model:page-size="pagination.size"
          :page-sizes="[10, 20, 30, 50]"
          layout="total, sizes, prev, pager, next, jumper"
          :total="total"
          @size-change="handleSizeChange"
          @current-change="handleCurrentChange"
        />
      </div>
    </section>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogType === 'add' ? '上传模型' : '编辑模型'"
      width="680px"
    >
      <el-form ref="modelFormRef" :model="modelForm" label-width="100px" :rules="rules">
        <el-form-item label="模型名称" prop="modelName">
          <el-input v-model="modelForm.modelName" placeholder="请输入模型名称" />
        </el-form-item>
        <el-form-item label="版本号" prop="version">
          <el-input v-model="modelForm.version" placeholder="请输入版本号" />
        </el-form-item>
        <el-form-item v-if="dialogType === 'add'" label="模型文件" prop="modelPath">
          <el-upload
            ref="uploadRef"
            action="#"
            :auto-upload="false"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
            :before-upload="beforeUpload"
            :limit="1"
          >
            <el-button type="primary">选择文件</el-button>
            <template #tip>
              <div class="upload-tip">仅支持上传 `.onnx` 格式文件。</div>
            </template>
          </el-upload>
          <div v-if="selectedFile" class="selected-file">已选择：{{ selectedFile.name }}</div>
        </el-form-item>
        <el-form-item label="更新说明" prop="updateDescription">
          <el-input
            v-model="modelForm.updateDescription"
            type="textarea"
            :rows="4"
            placeholder="请输入更新说明"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <span class="dialog-footer">
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" @click="submitForm">确定</el-button>
        </span>
      </template>
    </el-dialog>

    <el-drawer v-model="detailDrawerVisible" title="模型详情" size="520px">
      <template v-if="detailModel">
        <div class="detail-section">
          <div class="detail-grid">
            <div class="detail-item">
              <span class="detail-label">模型名称</span>
              <span class="detail-value">{{ detailModel.modelName }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">版本号</span>
              <span class="detail-value">{{ detailModel.version }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">状态</span>
              <el-tag :type="statusTypeMap[detailModel.status] || 'info'">
                {{ statusLabelMap[detailModel.status] || detailModel.status || '未知' }}
              </el-tag>
            </div>
            <div class="detail-item">
              <span class="detail-label">默认模型</span>
              <span class="detail-value">{{ detailModel.isDefault ? '是' : '否' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">上传人</span>
              <span class="detail-value">{{ detailModel.creator || '--' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">上传时间</span>
              <span class="detail-value">{{ formatDateTime(detailModel.uploadTime) || '--' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">发布时间</span>
              <span class="detail-value">{{ formatDateTime(detailModel.publishedAt) || '--' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">最近使用</span>
              <span class="detail-value">{{ formatDateTime(detailModel.lastUsedAt) || '--' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">使用次数</span>
              <span class="detail-value">{{ detailModel.usageCount ?? 0 }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">校验状态</span>
              <span class="detail-value">{{ detailModel.validationStatus || '--' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">MLOps 状态</span>
              <span class="detail-value">{{ mlopsStatusLabelMap[detailModel.mlopsStatus] || detailModel.mlopsStatus || '--' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">测试集</span>
              <span class="detail-value">{{ detailModel.evaluationDataset || '--' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Precision / Recall</span>
              <span class="detail-value">{{ formatMetric(detailModel.precisionScore) }} / {{ formatMetric(detailModel.recallScore) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">mAP / F1</span>
              <span class="detail-value">{{ formatMetric(detailModel.mapScore) }} / {{ formatMetric(detailModel.f1Score) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">推理耗时</span>
              <span class="detail-value">{{ detailModel.avgInferenceMs ? `${detailModel.avgInferenceMs} ms` : '--' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">部署策略</span>
              <span class="detail-value">{{ deploymentStrategyLabelMap[detailModel.deploymentStrategy] || detailModel.deploymentStrategy || '--' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">灰度/A-B</span>
              <span class="detail-value">{{ detailModel.canaryPercent ?? '--' }}% / {{ detailModel.abGroup || '--' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">回滚来源</span>
              <span class="detail-value">{{ detailModel.rollbackFromModelId ? `#${detailModel.rollbackFromModelId}` : '--' }}</span>
            </div>
          </div>
          <div class="detail-block">
            <div class="detail-label">模型路径</div>
            <div class="detail-multiline">{{ detailModel.modelPath || '--' }}</div>
          </div>
          <div class="detail-block">
            <div class="detail-label">更新说明</div>
            <div class="detail-multiline">{{ detailModel.updateDescription || '--' }}</div>
          </div>
          <div class="detail-block">
            <div class="detail-label">校验说明</div>
            <div class="detail-multiline">{{ detailModel.validationMessage || '--' }}</div>
          </div>
          <div class="detail-block">
            <div class="detail-label">兼容性说明</div>
            <div class="detail-multiline">{{ detailModel.compatibilityNote || '--' }}</div>
          </div>
        </div>

        <div class="detail-section">
          <div class="detail-header">
            <h3>操作日志</h3>
          </div>
          <el-table :data="operationLogs" v-loading="operationLoading" border size="small">
            <template #empty>
              <el-empty description="暂无操作日志" :image-size="60" />
            </template>
            <el-table-column prop="operationType" label="操作类型" width="120" />
            <el-table-column prop="operator" label="操作人" width="120" />
            <el-table-column label="操作时间" min-width="180">
              <template #default="{ row }">
                {{ formatDateTime(row.operationTime) || '--' }}
              </template>
            </el-table-column>
            <el-table-column prop="remark" label="备注" min-width="200" show-overflow-tooltip />
          </el-table>
        </div>
      </template>
    </el-drawer>

    <el-dialog v-model="evaluationDialogVisible" title="记录模型评估" width="620px">
      <el-form :model="evaluationForm" label-width="120px">
        <el-form-item label="测试集名称">
          <el-input v-model="evaluationForm.evaluationDataset" placeholder="例如 door-handle-val-2026Q2" />
        </el-form-item>
        <el-form-item label="Precision">
          <el-input-number v-model="evaluationForm.precisionScore" :min="0" :max="1" :step="0.0001" :precision="4" style="width: 100%" />
        </el-form-item>
        <el-form-item label="Recall">
          <el-input-number v-model="evaluationForm.recallScore" :min="0" :max="1" :step="0.0001" :precision="4" style="width: 100%" />
        </el-form-item>
        <el-form-item label="mAP">
          <el-input-number v-model="evaluationForm.mapScore" :min="0" :max="1" :step="0.0001" :precision="4" style="width: 100%" />
        </el-form-item>
        <el-form-item label="F1">
          <el-input-number v-model="evaluationForm.f1Score" :min="0" :max="1" :step="0.0001" :precision="4" style="width: 100%" />
        </el-form-item>
        <el-form-item label="平均推理耗时">
          <el-input-number v-model="evaluationForm.avgInferenceMs" :min="0" :precision="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="兼容性说明">
          <el-input v-model="evaluationForm.compatibilityNote" type="textarea" :rows="3" placeholder="例如 ONNX Runtime 版本、CPU/GPU、输入尺寸兼容性" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="evaluationDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="mlopsSubmitting" @click="submitEvaluation">保存评估</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="rolloutDialogVisible" title="配置部署策略" width="560px">
      <el-form :model="rolloutForm" label-width="110px">
        <el-form-item label="部署策略">
          <el-select v-model="rolloutForm.deploymentStrategy" style="width: 100%">
            <el-option label="全量发布" value="FULL" />
            <el-option label="灰度发布" value="CANARY" />
            <el-option label="A/B 对比" value="AB_TEST" />
            <el-option label="模型回滚" value="ROLLBACK" />
          </el-select>
        </el-form-item>
        <el-form-item label="灰度比例">
          <el-slider v-model="rolloutForm.canaryPercent" :min="0" :max="100" show-input />
        </el-form-item>
        <el-form-item label="A/B 分组">
          <el-select v-model="rolloutForm.abGroup" clearable style="width: 100%">
            <el-option label="A 组" value="A" />
            <el-option label="B 组" value="B" />
          </el-select>
        </el-form-item>
        <el-form-item label="回滚来源">
          <el-input-number v-model="rolloutForm.rollbackFromModelId" :min="1" :precision="0" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rolloutDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="mlopsSubmitting" @click="submitRollout">保存策略</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import request from '../api/request'
import { ElMessage } from 'element-plus'

const modelList = ref([])
const loading = ref(false)
const total = ref(0)
const selectedFile = ref(null)
const detailDrawerVisible = ref(false)
const detailModel = ref(null)
const operationLogs = ref([])
const operationLoading = ref(false)
const evaluationDialogVisible = ref(false)
const rolloutDialogVisible = ref(false)
const mlopsSubmitting = ref(false)
const activeMlopsModelId = ref(null)

const pagination = reactive({
  current: 1,
  size: 10
})

const searchForm = reactive({
  modelId: '',
  modelName: '',
  version: '',
  status: ''
})

const statusLabelMap = {
  READY: '待发布',
  PUBLISHED: '已发布',
  DISABLED: '已停用',
  ARCHIVED: '已归档',
  DRAFT: '草稿'
}

const statusTypeMap = {
  READY: 'warning',
  PUBLISHED: 'success',
  DISABLED: 'info',
  ARCHIVED: 'danger',
  DRAFT: ''
}

const validationLabelMap = {
  PASSED: '已通过',
  FAILED: '失败',
  PENDING: '待校验'
}

const validationTypeMap = {
  PASSED: 'success',
  FAILED: 'danger',
  PENDING: 'warning'
}

const mlopsStatusLabelMap = {
  UNASSESSED: '未评估',
  EVALUATED: '已评估',
  ROLLOUT: '发布策略',
  ROLLED_BACK: '已回滚'
}

const mlopsStatusTypeMap = {
  UNASSESSED: 'info',
  EVALUATED: 'success',
  ROLLOUT: 'warning',
  ROLLED_BACK: 'danger'
}

const deploymentStrategyLabelMap = {
  FULL: '全量',
  CANARY: '灰度',
  AB_TEST: 'A/B',
  ROLLBACK: '回滚'
}

const dialogVisible = ref(false)
const dialogType = ref('add')
const modelForm = reactive({
  modelId: null,
  modelName: '',
  version: '',
  modelPath: '',
  updateDescription: ''
})
const modelFormRef = ref(null)
const uploadRef = ref(null)

const evaluationForm = reactive({
  evaluationDataset: '',
  precisionScore: 0,
  recallScore: 0,
  mapScore: 0,
  f1Score: 0,
  avgInferenceMs: 0,
  compatibilityNote: ''
})

const rolloutForm = reactive({
  deploymentStrategy: 'FULL',
  canaryPercent: 100,
  abGroup: '',
  rollbackFromModelId: null
})

const rules = {
  modelName: [
    { required: true, message: '请输入模型名称', trigger: 'blur' }
  ],
  version: [
    { required: true, message: '请输入版本号', trigger: 'blur' }
  ],
  updateDescription: [
    { required: true, message: '请输入更新说明', trigger: 'blur' }
  ]
}

const hasSearch = computed(() => {
  return searchForm.modelId || searchForm.modelName || searchForm.version || searchForm.status
})

const defaultModel = computed(() => modelList.value.find((item) => item.isDefault) || null)
const publishedCount = computed(() => modelList.value.filter((item) => item.status === 'PUBLISHED').length)
const evaluatedCount = computed(() => modelList.value.filter((item) => item.mlopsStatus && item.mlopsStatus !== 'UNASSESSED').length)
const totalUsageCount = computed(() => modelList.value.reduce((sum, item) => sum + (item.usageCount || 0), 0))

const formatMetric = (value) => {
  if (value === undefined || value === null || value === '') return '--'
  return Number(value).toFixed(4)
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

const fetchModelList = () => {
  loading.value = true

  const params = {
    page: pagination.current,
    size: pagination.size,
    modelId: searchForm.modelId || undefined,
    modelName: searchForm.modelName || undefined,
    version: searchForm.version || undefined,
    status: searchForm.status || undefined
  }

  request.get('/api/model-info', { params })
    .then((response) => {
      if (response.data.code === 200) {
        modelList.value = response.data.data.records || []
        total.value = response.data.data.total || 0
      } else {
        ElMessage.error(response.data.message || '获取模型列表失败')
      }
    })
    .catch((error) => {
      console.error('获取模型列表失败:', error)
      ElMessage.error('获取模型列表失败')
    })
    .finally(() => {
      loading.value = false
    })
}

const handleSearch = () => {
  pagination.current = 1
  fetchModelList()
}

const resetSearch = () => {
  searchForm.modelId = ''
  searchForm.modelName = ''
  searchForm.version = ''
  searchForm.status = ''
  pagination.current = 1
  fetchModelList()
}

const handleSizeChange = (size) => {
  pagination.size = size
  fetchModelList()
}

const handleCurrentChange = (current) => {
  pagination.current = current
  fetchModelList()
}

const handleUpload = () => {
  dialogType.value = 'add'
  resetModelForm()
  dialogVisible.value = true
}

const handleEdit = (row) => {
  dialogType.value = 'edit'
  Object.assign(modelForm, row)
  dialogVisible.value = true
}

const handleViewDetails = (row) => {
  detailModel.value = { ...row }
  operationLogs.value = []
  detailDrawerVisible.value = true
  fetchModelDetail(row.modelId)
  fetchOperationLogs(row.modelId)
}

const openEvaluationDialog = (row) => {
  activeMlopsModelId.value = row.modelId
  evaluationForm.evaluationDataset = row.evaluationDataset || ''
  evaluationForm.precisionScore = Number(row.precisionScore || 0)
  evaluationForm.recallScore = Number(row.recallScore || 0)
  evaluationForm.mapScore = Number(row.mapScore || 0)
  evaluationForm.f1Score = Number(row.f1Score || 0)
  evaluationForm.avgInferenceMs = Number(row.avgInferenceMs || 0)
  evaluationForm.compatibilityNote = row.compatibilityNote || ''
  evaluationDialogVisible.value = true
}

const openRolloutDialog = (row) => {
  activeMlopsModelId.value = row.modelId
  rolloutForm.deploymentStrategy = row.deploymentStrategy || 'FULL'
  rolloutForm.canaryPercent = Number(row.canaryPercent ?? 100)
  rolloutForm.abGroup = row.abGroup || ''
  rolloutForm.rollbackFromModelId = row.rollbackFromModelId || null
  rolloutDialogVisible.value = true
}

const fetchModelDetail = (modelId) => {
  request.get(`/api/model-info/${modelId}`)
    .then((response) => {
      if (response.data.code === 200) {
        detailModel.value = response.data.data
      } else {
        ElMessage.error(response.data.message || '获取模型详情失败')
      }
    })
    .catch((error) => {
      console.error('获取模型详情失败:', error)
      ElMessage.error('获取模型详情失败')
    })
}

const handleDelete = (modelId) => {
  loading.value = true

  request.delete(`/api/models/${modelId}`)
    .then((response) => {
      if (response.data.code === 200) {
        ElMessage.success('删除成功')
        fetchModelList()
      } else {
        ElMessage.error(response.data.message || '删除失败')
      }
    })
    .catch((error) => {
      console.error('删除失败:', error)
      ElMessage.error('删除失败')
    })
    .finally(() => {
      loading.value = false
    })
}

const fetchOperationLogs = (modelId) => {
  operationLoading.value = true
  request.get(`/api/models/${modelId}/operations`)
    .then((response) => {
      if (response.data.code === 200) {
        operationLogs.value = response.data.data || []
      } else {
        ElMessage.error(response.data.message || '获取操作日志失败')
      }
    })
    .catch((error) => {
      console.error('获取操作日志失败:', error)
      ElMessage.error('获取操作日志失败')
    })
    .finally(() => {
      operationLoading.value = false
    })
}

const lifecycleActionMap = {
  publish: { url: 'publish', success: '发布成功' },
  'set-default': { url: 'set-default', success: '默认模型已切换' },
  validate: { url: 'validate', success: '重新校验完成' },
  disable: { url: 'disable', success: '停用成功' },
  archive: { url: 'archive', success: '归档成功' }
}

const handleLifecycleAction = (modelId, action) => {
  const config = lifecycleActionMap[action]
  if (!config) return

  loading.value = true
  request.post(`/api/models/${modelId}/${config.url}`)
    .then((response) => {
      if (response.data.code === 200) {
        ElMessage.success(config.success)
        fetchModelList()
        if (detailDrawerVisible.value && detailModel.value?.modelId === modelId) {
          fetchModelDetail(modelId)
          fetchOperationLogs(modelId)
        }
      } else {
        ElMessage.error(response.data.message || '操作失败')
      }
    })
    .catch((error) => {
      console.error('模型状态操作失败:', error)
      ElMessage.error(error.response?.data?.message || '操作失败')
    })
    .finally(() => {
      loading.value = false
    })
}

const submitEvaluation = () => {
  if (!activeMlopsModelId.value) return
  mlopsSubmitting.value = true
  request.post(`/api/model-info/${activeMlopsModelId.value}/evaluation`, evaluationForm)
    .then((response) => {
      if (response.data.code === 200) {
        ElMessage.success('模型评估指标已保存')
        evaluationDialogVisible.value = false
        fetchModelList()
        if (detailDrawerVisible.value && detailModel.value?.modelId === activeMlopsModelId.value) {
          fetchModelDetail(activeMlopsModelId.value)
        }
      } else {
        ElMessage.error(response.data.message || '保存模型评估失败')
      }
    })
    .catch((error) => {
      console.error('保存模型评估失败:', error)
      ElMessage.error('保存模型评估失败')
    })
    .finally(() => {
      mlopsSubmitting.value = false
    })
}

const submitRollout = () => {
  if (!activeMlopsModelId.value) return
  mlopsSubmitting.value = true
  request.post(`/api/model-info/${activeMlopsModelId.value}/rollout`, rolloutForm)
    .then((response) => {
      if (response.data.code === 200) {
        ElMessage.success('模型部署策略已保存')
        rolloutDialogVisible.value = false
        fetchModelList()
        if (detailDrawerVisible.value && detailModel.value?.modelId === activeMlopsModelId.value) {
          fetchModelDetail(activeMlopsModelId.value)
        }
      } else {
        ElMessage.error(response.data.message || '保存部署策略失败')
      }
    })
    .catch((error) => {
      console.error('保存部署策略失败:', error)
      ElMessage.error('保存部署策略失败')
    })
    .finally(() => {
      mlopsSubmitting.value = false
    })
}

const resetModelForm = () => {
  modelForm.modelId = null
  modelForm.modelName = ''
  modelForm.version = ''
  modelForm.modelPath = ''
  modelForm.updateDescription = ''
  selectedFile.value = null

  if (modelFormRef.value) {
    modelFormRef.value.resetFields()
  }

  if (uploadRef.value) {
    uploadRef.value.clearFiles()
  }
}

const beforeUpload = (file) => {
  const isONNX = file.name.endsWith('.onnx')
  if (!isONNX) {
    ElMessage.error('仅支持上传 ONNX 格式文件')
  }
  return isONNX
}

const handleFileChange = (file) => {
  selectedFile.value = file.raw
}

const handleFileRemove = () => {
  selectedFile.value = null
}

const submitForm = () => {
  if (!modelFormRef.value) return

  modelFormRef.value.validate((valid) => {
    if (!valid) {
      ElMessage.warning('请完善表单信息')
      return false
    }

    if (dialogType.value === 'add') {
      if (!selectedFile.value) {
        ElMessage.warning('请先选择模型文件')
        return
      }

      const formData = new FormData()
      formData.append('file', selectedFile.value)
      formData.append('modelName', modelForm.modelName)
      formData.append('version', modelForm.version)
      formData.append('updateDescription', modelForm.updateDescription || '')

      loading.value = true

      request.post('/api/models/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      })
        .then((response) => {
          if (response.data.code === 200) {
            ElMessage.success('模型上传成功')
            dialogVisible.value = false
            fetchModelList()
          } else {
            ElMessage.error(response.data.message || '模型上传失败')
          }
        })
        .catch((error) => {
          console.error('模型上传失败:', error)
          ElMessage.error(`上传失败：${error.message || '网络错误'}`)
        })
        .finally(() => {
          loading.value = false
        })
    } else {
      request.put(`/api/model-info/${modelForm.modelId}`, modelForm)
        .then((response) => {
          if (response.data.code === 200) {
            ElMessage.success('更新成功')
            dialogVisible.value = false
            fetchModelList()
          } else {
            ElMessage.error(response.data.message || '更新失败')
          }
        })
        .catch((error) => {
          console.error('更新失败:', error)
          ElMessage.error('更新失败')
        })
    }
  })
}

onMounted(() => {
  fetchModelList()
})
</script>

<style scoped>
.model-page {
  gap: 18px;
}

.upload-tip {
  color: #64748b;
  font-size: 13px;
}

.selected-file {
  margin-top: 8px;
  color: #0f766e;
  font-size: 14px;
  font-weight: 600;
}

.default-model-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 18px 22px;
  border-radius: 18px;
  background: linear-gradient(135deg, #ecfeff 0%, #f8fafc 100%);
  border: 1px solid rgba(14, 165, 233, 0.18);
}

.default-model-label {
  font-size: 12px;
  color: #0f766e;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.default-model-name {
  margin-top: 6px;
  font-size: 24px;
  font-weight: 700;
  color: #0f172a;
}

.default-model-version {
  font-size: 16px;
  color: #475569;
  font-weight: 600;
}

.default-model-meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 14px;
  color: #334155;
  font-size: 13px;
}

.detail-section {
  margin-bottom: 24px;
}

.detail-header h3 {
  margin: 0 0 12px;
  font-size: 16px;
  color: #0f172a;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 18px;
  margin-bottom: 18px;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.detail-label {
  font-size: 12px;
  color: #64748b;
}

.detail-value {
  font-size: 14px;
  color: #0f172a;
  font-weight: 600;
}

.detail-block {
  margin-bottom: 14px;
}

.detail-multiline {
  margin-top: 6px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
  color: #334155;
  line-height: 1.6;
  word-break: break-all;
}
</style>
