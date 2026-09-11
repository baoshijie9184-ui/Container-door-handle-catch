<template>
  <div class="page-shell image-detection-container work-order-trace-page">
    <section class="page-hero detection-hero command-panel">
      <div>
        <span class="industrial-kicker">Detection Workspace</span>
        <h1 class="page-hero-title">工单追溯</h1>
        <p class="page-hero-text">
          这一版已经切到“OSS 直传原图 + Java 编排任务 + 远程 FastAPI 检测 + OSS 回传结果”的新链路。
        </p>
        <div class="detection-flow-chips">
          <span class="metric-chip">OSS 原图直传</span>
          <span class="metric-chip">远程模型推理</span>
          <span class="metric-chip">质检复核闭环</span>
        </div>
      </div>
      <div class="hero-side-note">
        <strong>操作建议</strong>
        <span>单图检测走本地直传接口；批量检测先上传到 OSS，再触发远程检测任务。</span>
      </div>
    </section>

        <el-card class="detection-card batch-trace-card" shadow="never">
          <template #header>
            <div class="card-title-row">
              <span>工单追溯</span>
              <el-tag v-if="workOrderTraceReport" type="success" effect="plain">
                {{ workOrderTraceReport.workOrderNo }}
              </el-tag>
              <el-button
                v-if="workOrderTraceReport"
                size="small"
                type="success"
                plain
                @click="downloadWorkOrderTraceReport"
              >
                <el-icon><Download /></el-icon>
                导出工单报告
              </el-button>
            </div>
          </template>

          <div class="batch-trace-search">
            <el-input
              v-model="workOrderTraceNo"
              placeholder="输入工单号，例如 WO-20260611-001"
              clearable
              size="large"
              @keyup.enter="loadWorkOrderTraceReport"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-button type="primary" size="large" :loading="workOrderTraceLoading" @click="loadWorkOrderTraceReport">
              查询工单
            </el-button>
          </div>
          <div class="trace-sample-row">
            <span>常用工单：</span>
            <el-button
              v-for="order in businessWorkOrderNos"
              :key="order"
              size="small"
              plain
              @click="loadBusinessWorkOrderTrace(order)"
            >
              {{ order }}
            </el-button>
          </div>

          <el-empty
            v-if="!workOrderTraceReport && !workOrderTraceLoading"
            description="输入工单号，或点击上方常用工单，可查看该工单覆盖的批次、设备、缺陷和质检闭环"
            :image-size="88"
          >
            <BusinessSeedEmptyHint
              title="暂无工单追溯结果"
              description="可点击常用工单查询；如果仍无结果，请先导入业务预置数据。"
            />
          </el-empty>

          <div v-else v-loading="workOrderTraceLoading" class="batch-trace-body">
            <template v-if="workOrderTraceReport">
              <div class="batch-summary-band">
                <div>
                  <span>工单</span>
                  <strong>{{ workOrderTraceReport.workOrderNo }}</strong>
                </div>
                <div>
                  <span>覆盖批次</span>
                  <strong>{{ workOrderTraceReport.summary?.batchNos?.length || 0 }}</strong>
                </div>
                <div>
                  <span>覆盖区域</span>
                  <strong>{{ (workOrderTraceReport.summary?.regions || []).join('、') || '--' }}</strong>
                </div>
                <div>
                  <span>生成时间</span>
                  <strong>{{ workOrderTraceReport.generatedAt || '--' }}</strong>
                </div>
              </div>

              <el-row :gutter="14" class="batch-metrics">
                <el-col :xs="12" :sm="8" :md="4">
                  <el-statistic title="任务数" :value="workOrderTraceReport.summary?.taskCount || 0" />
                </el-col>
                <el-col :xs="12" :sm="8" :md="4">
                  <el-statistic title="图片总数" :value="workOrderTraceReport.inspection?.totalImages || 0" />
                </el-col>
                <el-col :xs="12" :sm="8" :md="4">
                  <el-statistic title="缺陷数" :value="workOrderTraceReport.inspection?.defectCount || 0" />
                </el-col>
                <el-col :xs="12" :sm="8" :md="4">
                  <el-statistic title="确认缺陷" :value="workOrderTraceReport.inspection?.confirmedDefectCount || 0" />
                </el-col>
                <el-col :xs="12" :sm="8" :md="4">
                  <el-statistic title="缺陷率" :value="formatPercentValue(workOrderTraceReport.inspection?.defectRate)" suffix="%" />
                </el-col>
                <el-col :xs="12" :sm="8" :md="4">
                  <el-statistic title="闭环率" :value="formatPercentValue(workOrderTraceReport.quality?.closureRate)" suffix="%" />
                </el-col>
              </el-row>

              <div class="batch-section-grid">
                <div class="batch-panel">
                  <h3>质检闭环</h3>
                  <div class="batch-quality-list">
                    <div><span>待复核</span><strong>{{ workOrderTraceReport.quality?.pendingReview || 0 }}</strong></div>
                    <div><span>已复核</span><strong>{{ workOrderTraceReport.quality?.reviewed || 0 }}</strong></div>
                    <div><span>已处置</span><strong>{{ workOrderTraceReport.quality?.disposed || 0 }}</strong></div>
                    <div><span>需返工</span><strong>{{ workOrderTraceReport.quality?.reworkRequired || 0 }}</strong></div>
                    <div><span>需复检</span><strong>{{ workOrderTraceReport.quality?.recheckRequired || 0 }}</strong></div>
                    <div><span>已关闭</span><strong>{{ workOrderTraceReport.quality?.closed || 0 }}</strong></div>
                  </div>
                </div>

                <div class="batch-panel">
                  <h3>工单上下文</h3>
                  <div class="batch-context-tags">
                    <el-tag v-for="batch in workOrderTraceReport.summary?.batchNos || []" :key="`wo-batch-${batch}`" type="success" effect="plain">
                      批次 {{ batch }}
                    </el-tag>
                    <el-tag v-for="device in workOrderTraceReport.summary?.devices || []" :key="`wo-device-${device}`" effect="plain">
                      设备 {{ device }}
                    </el-tag>
                    <el-tag v-for="collector in workOrderTraceReport.summary?.collectors || []" :key="`wo-collector-${collector}`" type="warning" effect="plain">
                      采集员 {{ collector }}
                    </el-tag>
                    <el-tag v-for="model in workOrderTraceReport.summary?.models || []" :key="`wo-model-${model}`" type="info" effect="plain">
                      模型 {{ model }}
                    </el-tag>
                  </div>
                  <div class="batch-time-range">
                    <span>创建：{{ workOrderTraceReport.timeRange?.createdFrom || '--' }} 至 {{ workOrderTraceReport.timeRange?.createdTo || '--' }}</span>
                    <span>检测完成：{{ workOrderTraceReport.timeRange?.finishedTo || '--' }}</span>
                    <span>最近更新：{{ workOrderTraceReport.timeRange?.lastUpdatedAt || '--' }}</span>
                  </div>
                </div>
              </div>

              <div class="batch-section-grid">
                <div class="batch-panel">
                  <h3>缺陷分布</h3>
                  <el-table :data="mapDistributionRows(workOrderTraceReport.distribution?.defectType)" size="small" border empty-text="暂无缺陷">
                    <el-table-column prop="name" label="缺陷类型" min-width="140" />
                    <el-table-column prop="count" label="数量" width="90" />
                  </el-table>
                </div>
                <div class="batch-panel">
                  <h3>批次分布</h3>
                  <el-table :data="mapDistributionRows(workOrderTraceReport.distribution?.status)" size="small" border empty-text="暂无状态">
                    <el-table-column prop="name" label="任务状态" min-width="140" />
                    <el-table-column prop="count" label="数量" width="90" />
                  </el-table>
                </div>
              </div>

              <div class="batch-panel">
                <h3>工单任务明细</h3>
                <el-table :data="workOrderTraceReport.records || []" size="small" border max-height="360">
                  <el-table-column prop="taskId" label="任务编号" min-width="180" show-overflow-tooltip />
                  <el-table-column prop="batchNo" label="批次" min-width="150" show-overflow-tooltip />
                  <el-table-column prop="deviceName" label="设备" min-width="120" show-overflow-tooltip />
                  <el-table-column label="状态" width="110">
                    <template #default="{ row }">
                      <el-tag :type="row.status === 'FAILED' ? 'danger' : 'success'" effect="plain">{{ row.status || '--' }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="流转" min-width="140">
                    <template #default="{ row }">{{ flowStatusText(row.flowStatus) }}</template>
                  </el-table-column>
                  <el-table-column prop="defectCount" label="缺陷" width="80" />
                  <el-table-column prop="maxDefectSeverity" label="最高等级" width="110" />
                  <el-table-column label="操作" width="170" fixed="right">
                    <template #default="{ row }">
                      <el-button link size="small" type="primary" @click="openTraceDialog(row.taskId)">追溯详情</el-button>
                      <el-button link size="small" type="success" @click="downloadTaskQualityReport(row.taskId)">报告</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </div>
            </template>
          </div>
        </el-card>
    <el-dialog v-model="reviewDialogVisible" title="人工复核" width="560px">
      <el-alert
        v-if="reviewTask"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 14px;"
        :message="`任务 ${reviewTask.taskId} 将记录质检结论、严重等级与误报反馈。`"
      />
      <el-form :model="reviewForm" label-width="110px">
        <el-form-item label="复核结论">
          <el-select v-model="reviewForm.reviewConclusion" style="width: 100%">
            <el-option label="确认缺陷" value="CONFIRMED_DEFECT" />
            <el-option label="误报" value="FALSE_POSITIVE" />
            <el-option label="正常放行" value="NORMAL_RELEASE" />
            <el-option label="需二次复查" value="NEEDS_RECHECK" />
          </el-select>
        </el-form-item>
        <el-form-item label="严重等级">
          <el-select v-model="reviewForm.severityLevel" style="width: 100%">
            <el-option label="轻微" value="MINOR" />
            <el-option label="一般" value="MAJOR" />
            <el-option label="严重" value="CRITICAL" />
          </el-select>
        </el-form-item>
        <el-form-item label="确认缺陷数">
          <el-input-number v-model="reviewForm.confirmedDefectCount" :min="0" :precision="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="误报数量">
          <el-input-number v-model="reviewForm.falsePositiveCount" :min="0" :precision="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="复核备注">
          <el-input
            v-model="reviewForm.reviewRemark"
            type="textarea"
            :rows="3"
            maxlength="300"
            show-word-limit
            placeholder="记录缺陷位置、人工判断依据或误报原因"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviewDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="reviewSubmitting" @click="submitTaskReview">提交复核</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="assignmentDialogVisible" title="分派质检任务" width="560px">
      <el-alert
        v-if="assignmentTask"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 14px;"
        :message="`任务 ${assignmentTask.taskId} 将分派到质检站点，后续由责任人完成复核与处置。`"
      />
      <el-form :model="assignmentForm" label-width="110px">
        <el-form-item label="质检站点">
          <el-input v-model="assignmentForm.qualityStation" placeholder="例如：质检站-1 / 产线A复核位" />
        </el-form-item>
        <el-form-item label="责任人">
          <el-input v-model="assignmentForm.assignee" placeholder="请输入质检责任人" />
        </el-form-item>
        <el-form-item label="截止时间">
          <el-date-picker
            v-model="assignmentForm.dueAt"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            format="YYYY-MM-DD HH:mm"
            placeholder="选择质检截止时间"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="分派备注">
          <el-input
            v-model="assignmentForm.assignmentRemark"
            type="textarea"
            :rows="3"
            maxlength="1000"
            show-word-limit
            placeholder="补充复核重点、缺陷疑点或产线要求"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="assignmentDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="assignmentSubmitting" @click="submitQualityAssignment">确认分派</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dispositionDialogVisible" title="质检处置" width="560px">
      <el-alert
        v-if="dispositionTask"
        type="warning"
        show-icon
        :closable="false"
        style="margin-bottom: 14px;"
        :message="`任务 ${dispositionTask.taskId} 已完成复核，请选择放行、返工、复检、暂挂或报废。`"
      />
      <el-form :model="dispositionForm" label-width="110px">
        <el-form-item label="处置动作">
          <el-select v-model="dispositionForm.dispositionAction" style="width: 100%">
            <el-option label="正常放行" value="RELEASE" :disabled="!canReleaseDisposition(dispositionTask)" />
            <el-option label="返工处理" value="REWORK" />
            <el-option label="安排复检" value="RECHECK" />
            <el-option label="暂挂观察" value="HOLD" />
            <el-option label="报废隔离" value="SCRAP" />
          </el-select>
        </el-form-item>
        <el-form-item label="需要复检">
          <el-switch v-model="dispositionForm.recheckRequired" />
        </el-form-item>
        <el-form-item label="处置备注">
          <el-input
            v-model="dispositionForm.dispositionRemark"
            type="textarea"
            :rows="3"
            maxlength="1000"
            show-word-limit
            placeholder="记录处置依据、返工要求或隔离说明"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dispositionDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="dispositionSubmitting" @click="submitTaskDisposition">提交处置</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="reworkDialogVisible" title="返工结果回填" width="560px">
      <el-alert
        v-if="reworkTask"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 14px;"
        :message="`任务 ${reworkTask.taskId} 当前待返工，请回填返工结果并决定是否进入复检。`"
      />
      <el-form :model="reworkForm" label-width="110px">
        <el-form-item label="返工结果">
          <el-input
            v-model="reworkForm.reworkResult"
            type="textarea"
            :rows="3"
            placeholder="例如：已更换门把手锁扣并完成表面清理"
          />
        </el-form-item>
        <el-form-item label="返工人员">
          <el-input v-model="reworkForm.reworkOperator" placeholder="不填则使用当前登录用户" />
        </el-form-item>
        <el-form-item label="需要复检">
          <el-switch v-model="reworkForm.recheckRequired" />
        </el-form-item>
        <el-form-item label="返工备注">
          <el-input
            v-model="reworkForm.reworkRemark"
            type="textarea"
            :rows="3"
            placeholder="补充返工证据、复检要求或异常说明"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reworkDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="reworkSubmitting" @click="submitTaskRework">提交返工结果</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="traceDialogVisible" title="任务追溯详情" width="860px">
      <div v-loading="traceLoading" class="trace-dialog-body">
        <template v-if="traceDetail">
          <el-descriptions bordered :column="2" size="small" class="trace-section">
            <el-descriptions-item label="任务编号"><code>{{ traceDetail.taskId }}</code></el-descriptions-item>
            <el-descriptions-item label="工作流">{{ traceDetail.workflowUuid || '--' }}</el-descriptions-item>
            <el-descriptions-item label="批次">{{ traceDetail.batchNo || '--' }}</el-descriptions-item>
            <el-descriptions-item label="工单">{{ traceDetail.workOrderNo || '--' }}</el-descriptions-item>
            <el-descriptions-item label="流转状态">{{ flowStatusText(traceDetail.flowStatus) }}</el-descriptions-item>
            <el-descriptions-item label="检测状态">{{ traceDetail.status || '--' }}</el-descriptions-item>
            <el-descriptions-item label="采集日期">{{ traceDetail.captureDate || '--' }}</el-descriptions-item>
            <el-descriptions-item label="地区">{{ traceDetail.region || '--' }}</el-descriptions-item>
            <el-descriptions-item label="采集人">{{ traceDetail.collector || '--' }}</el-descriptions-item>
            <el-descriptions-item label="设备">{{ traceDetail.deviceName || '--' }}</el-descriptions-item>
            <el-descriptions-item label="图片批次">{{ traceDetail.imageFolderName || '--' }}</el-descriptions-item>
            <el-descriptions-item label="质检站点">{{ traceDetail.qualityStation || '--' }}</el-descriptions-item>
            <el-descriptions-item label="责任人">{{ traceDetail.assignee || '--' }}</el-descriptions-item>
            <el-descriptions-item label="分派时间">{{ traceDetail.assignedAt || '--' }}</el-descriptions-item>
            <el-descriptions-item label="质检截止">{{ traceDetail.dueAt || '--' }}</el-descriptions-item>
            <el-descriptions-item label="模型">
              {{ traceDetail.modelId ? `#${traceDetail.modelId}` : '--' }}
              <span v-if="traceDetail.modelVersion"> / {{ traceDetail.modelVersion }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="置信度阈值">{{ traceDetail.threshold ?? '--' }}</el-descriptions-item>
            <el-descriptions-item label="复核结论">{{ reviewConclusionText(traceDetail.reviewConclusion) }}</el-descriptions-item>
            <el-descriptions-item label="严重等级">
              <el-tag :type="severityTagType(traceDetail.severityLevel)">{{ severityText(traceDetail.severityLevel) }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="缺陷/误报">
              {{ traceDetail.confirmedDefectCount || 0 }} / {{ traceDetail.falsePositiveCount || 0 }}
            </el-descriptions-item>
            <el-descriptions-item label="复核人">{{ traceDetail.reviewer || '--' }}</el-descriptions-item>
            <el-descriptions-item v-if="traceDetail.reviewRemark" label="复核备注" :span="2">
              {{ traceDetail.reviewRemark }}
            </el-descriptions-item>
          </el-descriptions>

          <div class="trace-section trace-paths">
            <div>
              <span>原图路径</span>
              <code>{{ traceDetail.sourceOssPrefix || '--' }}</code>
            </div>
            <div>
              <span>结果路径</span>
              <code>{{ traceDetail.resultOssPrefix || '--' }}</code>
            </div>
            <div>
              <span>结果 JSON</span>
              <a v-if="traceDetail.resultJsonUrl" :href="traceDetail.resultJsonUrl" target="_blank">{{ traceDetail.resultJsonKey }}</a>
              <code v-else>{{ traceDetail.resultJsonKey || '--' }}</code>
            </div>
          </div>

          <el-row :gutter="12" class="trace-section">
            <el-col :span="8">
              <el-statistic title="图片总数" :value="traceDetail.totalImages || 0" />
            </el-col>
            <el-col :span="8">
              <el-statistic title="成功" :value="traceDetail.successfulImages || 0" />
            </el-col>
            <el-col :span="8">
              <el-statistic title="失败" :value="traceDetail.failedImages || 0" />
            </el-col>
          </el-row>

          <div class="trace-section">
            <h4>证据图片</h4>
            <el-table :data="traceEvidenceRows" size="small" border max-height="220">
              <el-table-column prop="type" label="类型" width="90" />
              <el-table-column prop="imageName" label="文件名" min-width="160" show-overflow-tooltip />
              <el-table-column prop="objectKey" label="OSS Key" min-width="260" show-overflow-tooltip />
              <el-table-column label="预览" width="90">
                <template #default="{ row }">
                  <a v-if="row.previewUrl" :href="row.previewUrl" target="_blank">打开</a>
                  <span v-else>--</span>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <div class="trace-section">
            <h4>追溯时间线</h4>
            <el-timeline>
              <el-timeline-item
                v-for="event in traceDetail.timeline || []"
                :key="`${event.eventType}-${event.occurredAt}`"
                :timestamp="event.occurredAt"
              >
                <strong>{{ event.eventName }}</strong>
                <div class="trace-event-meta">{{ event.operator }} · {{ event.description }}</div>
              </el-timeline-item>
            </el-timeline>
          </div>
        </template>
      </div>
      <template #footer>
        <el-button @click="traceDialogVisible = false">关闭</el-button>
        <el-button
          v-if="traceDetail?.taskId"
          type="success"
          :loading="reportDownloading"
          @click="downloadTaskQualityReport(traceDetail.taskId)"
        >
          <el-icon><Download /></el-icon>
          导出质检报告
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { ArrowDown, CircleCheck, Clock, Delete, Download, Refresh, Search, Upload, VideoPlay, Warning } from '@element-plus/icons-vue'
import {
  detectSingleImage,
  fetchAvailableModels,
  fetchBatchTraceReport,
  fetchDefectGallery,
  fetchDetectionTaskTrace,
  fetchQualityQueue,
  fetchQualityReport,
  fetchWorkOrderTraceReport,
} from '../../api/detection'
import { useTaskStore, useUploadStore, usePollingStore, CATEGORY_LABELS, CATEGORY_COLORS, CATEGORY_ALIASES } from '../../stores/detectionTask'
import { useSingleImageUploadPreview } from '../../composables/useSingleImageUploadPreview'
import { useQualityTaskActions } from '../../composables/useQualityTaskActions'
import { businessBatchNos, businessWorkOrderNos } from '../../config/businessTracePresets'
import BusinessSeedEmptyHint from '../../components/BusinessSeedEmptyHint.vue'

const taskStore = useTaskStore()
const uploadStore = useUploadStore()
const pollingStore = usePollingStore()
const { taskList, selectedTaskId } = storeToRefs(taskStore)
const {
  removeTask, taskTagType, taskTagText, taskStatusDetail, formatRelativeTime, formatAbsoluteTime,
  taskStepIndex, taskStepDesc,
  buildTaskStatistics, saveTaskList
} = taskStore
const { startTaskDetection, stopAllPolling, restoreFromSession, fetchTaskList, fetchTaskResults } = pollingStore

// ==================== 组件本地状态（UI 相关） ====================

const fileList = ref([])
const modelList = ref([])
const detectionResult = ref(null)
const annotatedImageUrl = ref('')
const loadingSingle = ref(false)
const taskFilter = ref('all')
const taskSearchKeyword = ref('')
const taskFilterDate = ref('')
const traceDialogVisible = ref(false)
const traceLoading = ref(false)
const traceDetail = ref(null)
const reportDownloading = ref(false)
const route = useRoute()
const router = useRouter()
const activeTab = ref('workspace')
const validTabs = ['workspace', 'history', 'quality', 'defect-gallery', 'work-order-trace', 'batch-trace']
const tabRouteMap = {
  workspace: '/inspection/workbench',
  history: '/inspection/history',
  quality: '/quality/queue',
  'defect-gallery': '/quality/evidence',
  'work-order-trace': '/quality/work-order-trace',
  'batch-trace': '/quality/batch-trace'
}
const activeQualityQueue = ref('ALL_ACTIONABLE')
const qualityQueueLoading = ref(false)
const qualityQueueRecords = ref([])
const qualityQueueTotal = ref(0)
const qualityQueuePage = ref(1)
const qualityQueuePageSize = ref(10)
const defectGalleryLoading = ref(false)
const defectGalleryRecords = ref([])
const defectGalleryTotal = ref(0)
const defectGalleryPage = ref(1)
const defectGalleryPageSize = ref(8)
const workOrderTraceNo = ref('')
const workOrderTraceLoading = ref(false)
const workOrderTraceReport = ref(null)
const batchTraceNo = ref('')
const batchTraceLoading = ref(false)
const batchTraceReport = ref(null)

const form = reactive({
  modelId: null,
  threshold: 0.5,
  imageFile: null
})

const defectFilters = reactive({
  defectType: '',
  severityLevel: '',
  deviceName: '',
  batchNo: '',
  modelId: null
})

const qualityQueues = [
  { label: '全部待处理', value: 'ALL_ACTIONABLE', hint: '复核/处置/异常' },
  { label: '待复核', value: 'PENDING_REVIEW', hint: '检测完成待确认' },
  { label: '待处置', value: 'PENDING_DISPOSITION', hint: '复核后需决策' },
  { label: '待返工', value: 'REWORK_REQUIRED', hint: '产线返修' },
  { label: '待复检', value: 'RECHECK_REQUIRED', hint: '二次确认' },
  { label: '暂挂', value: 'HOLD', hint: '人工保留' },
  { label: '失败', value: 'FAILED', hint: '异常处理' }
]

// 筛选任务列表
const filteredTaskList = computed(() => {
  let list = [...taskList.value]

  // 关键字搜索
  const kw = taskSearchKeyword.value.trim().toLowerCase()
  if (kw) {
    list = list.filter(t =>
      (t.taskId && t.taskId.toLowerCase().includes(kw)) ||
      (t.folderName && t.folderName.toLowerCase().includes(kw))
    )
  }

  // 日期过滤
  if (taskFilterDate.value) {
    list = list.filter(t => {
      const date = t.updatedAt || t.createdAt
      return date && date.startsWith(taskFilterDate.value)
    })
  }

  // 状态过滤
  if (taskFilter.value !== 'all') {
    if (taskFilter.value === 'pending') list = list.filter(t => t.stage === 'uploaded')
    else if (taskFilter.value === 'running') list = list.filter(t => t.stage === 'queued' || t.stage === 'detecting')
    else if (taskFilter.value === 'done') list = list.filter(t => t.stage === 'completed')
    else if (taskFilter.value === 'failed') list = list.filter(t => t.stage === 'failed')
  }

  // 按 taskId 倒序（稳定不跳）
  list.sort((a, b) => (b.taskId || '').localeCompare(a.taskId || ''))

  return list
})

// 已完成/部分失败的任务（检测记录用），按完成时间倒序
const completedTasks = computed(() =>
  taskList.value
    .filter(t => t.stage === 'completed' || t.stage === 'failed' || (t.result && t.stage !== 'uploading'))
    .sort((a, b) => {
      const ta = a.finishedAt || a.createdAt || ''
      const tb = b.finishedAt || b.createdAt || ''
      return tb.localeCompare(ta)
    })
)

const traceEvidenceRows = computed(() => {
  const detail = traceDetail.value
  if (!detail) return []
  const originals = (detail.originalImages || []).map(item => ({ ...item, type: '原图' }))
  const previews = (detail.previewImages || []).map(item => ({ ...item, type: '标注图' }))
  return [...originals, ...previews]
})

const formatPercentValue = (value) => {
  const number = Number(value || 0)
  return Math.round(number * 1000) / 10
}

const mapDistributionRows = (distribution) => {
  if (!distribution) return []
  return Object.entries(distribution)
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => Number(b.count || 0) - Number(a.count || 0))
}

const safeFilePart = (value) => String(value || 'unknown')
  .replace(/[\\/:*?"<>|\s]+/g, '-')
  .replace(/-+/g, '-')
  .replace(/^-|-$/g, '')

const reportTimestamp = () => {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
}

const downloadJsonReport = (payload, fileName) => {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

const downloadTaskQualityReport = async (taskId) => {
  if (!taskId) {
    ElMessage.warning('缺少任务编号，无法导出报告')
    return
  }
  reportDownloading.value = true
  try {
    const response = await fetchQualityReport(taskId)
    if (response.data?.code === 200) {
      const report = response.data.data
      downloadJsonReport(report, `quality-report-${safeFilePart(taskId)}-${reportTimestamp()}.json`)
      ElMessage.success('质检报告已导出')
    } else {
      ElMessage.error(response.data?.message || '导出质检报告失败')
    }
  } catch (error) {
    console.error('导出质检报告失败:', error)
    ElMessage.error(error.response?.data?.message || '导出质检报告失败')
  } finally {
    reportDownloading.value = false
  }
}

const downloadBatchTraceReport = () => {
  if (!batchTraceReport.value) {
    ElMessage.warning('请先生成批次追溯报告')
    return
  }
  const batchNo = batchTraceReport.value.batchNo || batchTraceNo.value
  downloadJsonReport({
    ...batchTraceReport.value,
    exportedAt: new Date().toISOString(),
    exportedBy: 'DoorHandleCatch Web'
  }, `batch-trace-${safeFilePart(batchNo)}-${reportTimestamp()}.json`)
  ElMessage.success('批次追溯报告已导出')
}

const downloadWorkOrderTraceReport = () => {
  if (!workOrderTraceReport.value) {
    ElMessage.warning('请先生成工单追溯报告')
    return
  }
  const workOrderNo = workOrderTraceReport.value.workOrderNo || workOrderTraceNo.value
  downloadJsonReport({
    ...workOrderTraceReport.value,
    exportedAt: new Date().toISOString(),
    exportedBy: 'DoorHandleCatch Web'
  }, `work-order-trace-${safeFilePart(workOrderNo)}-${reportTimestamp()}.json`)
  ElMessage.success('工单追溯报告已导出')
}

// 搜索
const historySearchKeyword = ref('')
const onHistorySearch = () => {
  historyPage.value = 1
  fetchHistoryWithFilters(1)
}

// 高级筛选
const historyFilterCollector = ref('')
const historyFilterDevice = ref('')
const historyFilterRegion = ref('')

// 服务端分页
const historyPage = ref(1)
const historyPageSize = ref(10)
const historyTotal = ref(0)
const historyRecords = ref([])
const historyLoading = ref(false)

const fetchHistoryWithFilters = async (page, size) => {
  historyLoading.value = true
  try {
    const p = page || historyPage.value
    const s = size || historyPageSize.value
    const filters = {}
    if (historySearchKeyword.value.trim()) filters.keyword = historySearchKeyword.value.trim()
    if (historyFilterCollector.value.trim()) filters.collector = historyFilterCollector.value.trim()
    if (historyFilterDevice.value.trim()) filters.deviceName = historyFilterDevice.value.trim()
    if (historyFilterRegion.value.trim()) filters.region = historyFilterRegion.value.trim()
    const result = await fetchTaskList(p, s, '', '', filters)
    if (result) {
      historyRecords.value = (result.records || []).map(bt => {
        const localTask = taskStore.taskList.find(t => t.taskId === bt.taskId)
        return localTask || {
          ...bt,
          imageCount: bt.totalImages || 0,
          result: null,
          captureInfo: {
            captureDate: bt.captureDate || '',
            region: bt.region || '',
            collector: bt.collector || '',
            deviceName: bt.deviceName || '',
            imageFolderName: bt.imageFolderName || ''
          }
        }
      })
      historyTotal.value = result.total || 0

      // 并行获取已完成任务的结果详情
      const completedIds = historyRecords.value
        .filter(t => t.stage === 'completed' || t.stage === 'failed')
        .map(t => t.taskId)
      if (completedIds.length) {
        await fetchTaskResults(completedIds)
        // 更新记录以反映新获取的结果
        historyRecords.value = historyRecords.value.map(t => {
          const updated = taskStore.taskList.find(u => u.taskId === t.taskId)
          return updated || t
        })
      }
    }
  } finally {
    historyLoading.value = false
  }
}

const onHistoryPageChange = (page, size) => {
  historyPage.value = page
  fetchHistoryWithFilters(page, size)
}

const onHistorySizeChange = (size) => {
  historyPageSize.value = size
  historyPage.value = 1
  fetchHistoryWithFilters(1, size)
}

const normalizeQualityQueueRecord = (record) => ({
  ...record,
  stage: record.stage ? record.stage.toLowerCase() : (record.status === 'FAILED' ? 'failed' : 'completed'),
  imageCount: record.totalImages || record.imageCount || 0,
  result: record.result || null,
  captureInfo: {
    captureDate: record.captureDate || '',
    region: record.region || '',
    collector: record.collector || '',
    deviceName: record.deviceName || '',
    imageFolderName: record.imageFolderName || ''
  }
})

const resolvePageNumber = (page, fallback) => {
  const value = Number(page)
  return Number.isInteger(value) && value > 0 ? value : fallback
}

const loadQualityQueue = async (page = qualityQueuePage.value) => {
  const targetPage = resolvePageNumber(page, qualityQueuePage.value)
  qualityQueueLoading.value = true
  try {
    const response = await fetchQualityQueue(activeQualityQueue.value, targetPage, qualityQueuePageSize.value)
    if (response.data?.code === 200) {
      const data = response.data.data || {}
      qualityQueueRecords.value = (data.records || []).map(normalizeQualityQueueRecord)
      qualityQueueTotal.value = Number(data.total || 0)
      qualityQueuePage.value = targetPage
    } else {
      ElMessage.error(response.data?.message || '获取质检队列失败')
    }
  } catch (error) {
    console.error('获取质检队列失败:', error)
    ElMessage.error(error.response?.data?.message || '获取质检队列失败')
  } finally {
    qualityQueueLoading.value = false
  }
}

const switchQualityQueue = (queue) => {
  activeQualityQueue.value = queue
  qualityQueuePage.value = 1
  loadQualityQueue(1)
}

const onQualityQueueSizeChange = (size) => {
  qualityQueuePageSize.value = size
  qualityQueuePage.value = 1
  loadQualityQueue(1)
}

const refreshQualityQueueIfVisible = async () => {
  if (activeTab.value === 'quality') {
    await loadQualityQueue(qualityQueuePage.value)
  }
}

const refreshDefectGalleryIfVisible = async () => {
  if (activeTab.value === 'defect-gallery') {
    await loadDefectGallery(defectGalleryPage.value)
  }
}

const {
  reviewDialogVisible,
  reviewSubmitting,
  reviewTask,
  reviewForm,
  assignmentDialogVisible,
  assignmentSubmitting,
  assignmentTask,
  assignmentForm,
  dispositionDialogVisible,
  dispositionSubmitting,
  dispositionTask,
  dispositionForm,
  reworkDialogVisible,
  reworkSubmitting,
  reworkTask,
  reworkForm,
  openReviewDialog,
  submitTaskReview,
  openAssignmentDialog,
  submitQualityAssignment,
  openDispositionDialog,
  submitTaskDisposition,
  openReworkDialog,
  submitTaskRework
} = useQualityTaskActions({
  taskStore,
  fetchTaskResults,
  refreshQualityQueue: refreshQualityQueueIfVisible,
  refreshDefectGallery: refreshDefectGalleryIfVisible
})

const handleTabChange = async (tabName) => {
  if (tabName === 'quality' && !qualityQueueRecords.value.length) {
    await loadQualityQueue(1)
  }
  if (tabName === 'defect-gallery' && !defectGalleryRecords.value.length) {
    await loadDefectGallery(1)
  }
  if (tabName === 'work-order-trace' && !workOrderTraceReport.value && !workOrderTraceLoading.value) {
    workOrderTraceNo.value = workOrderTraceNo.value || businessWorkOrderNos[0]
    await loadWorkOrderTraceReport()
  }
  if (tabName === 'batch-trace' && !batchTraceReport.value && !batchTraceLoading.value) {
    batchTraceNo.value = batchTraceNo.value || businessBatchNos[0]
    await loadBatchTraceReport()
  }
  const targetPath = tabRouteMap[tabName]
  if (targetPath && route.path !== targetPath) {
    const { tab, ...query } = route.query
    router.replace({ path: targetPath, query })
  }
}

const syncTabFromRoute = async () => {
  const routeTab = String(route.query.tab || route.meta?.detectionTab || '')
  if (validTabs.includes(routeTab) && activeTab.value !== routeTab) {
    activeTab.value = routeTab
    await handleTabChange(routeTab)
  }
}

const buildDefectGalleryParams = (page = defectGalleryPage.value) => {
  const targetPage = resolvePageNumber(page, defectGalleryPage.value)
  const params = {
    page: targetPage,
    size: defectGalleryPageSize.value
  }
  if (defectFilters.defectType.trim()) params.defectType = defectFilters.defectType.trim()
  if (defectFilters.severityLevel) params.severityLevel = defectFilters.severityLevel
  if (defectFilters.deviceName.trim()) params.deviceName = defectFilters.deviceName.trim()
  if (defectFilters.batchNo.trim()) params.batchNo = defectFilters.batchNo.trim()
  if (defectFilters.modelId) params.modelId = defectFilters.modelId
  return params
}

const loadDefectGallery = async (page = defectGalleryPage.value) => {
  const targetPage = resolvePageNumber(page, defectGalleryPage.value)
  defectGalleryLoading.value = true
  try {
    const response = await fetchDefectGallery(buildDefectGalleryParams(targetPage))
    if (response.data?.code === 200) {
      const data = response.data.data || {}
      defectGalleryRecords.value = data.records || []
      defectGalleryTotal.value = Number(data.total || 0)
      defectGalleryPage.value = targetPage
    } else {
      ElMessage.error(response.data?.message || '获取缺陷证据库失败')
    }
  } catch (error) {
    console.error('获取缺陷证据库失败:', error)
    ElMessage.error(error.response?.data?.message || '获取缺陷证据库失败')
  } finally {
    defectGalleryLoading.value = false
  }
}

const searchDefectGallery = () => {
  defectGalleryPage.value = 1
  loadDefectGallery(1)
}

const resetDefectGalleryFilters = () => {
  defectFilters.defectType = ''
  defectFilters.severityLevel = ''
  defectFilters.deviceName = ''
  defectFilters.batchNo = ''
  defectFilters.modelId = null
  searchDefectGallery()
}

const onDefectGallerySizeChange = (size) => {
  defectGalleryPageSize.value = size
  defectGalleryPage.value = 1
  loadDefectGallery(1)
}

const resolveDefectPreview = (task) => {
  const preview = task.previewImages?.find(item => item.annotatedUrl || item.previewUrl)
  if (preview) return preview.annotatedUrl || preview.previewUrl
  const evidencePreviewKey = task.defectEvidence?.find(item => item.previewUrl || item.annotatedUrl)
  if (evidencePreviewKey) return evidencePreviewKey.previewUrl || evidencePreviewKey.annotatedUrl
  const original = task.originalImages?.find(item => item.previewUrl)
  return original?.previewUrl || ''
}

const formatEvidenceConfidence = (value) => {
  const number = Number(value)
  if (Number.isNaN(number)) return '--'
  return `${Math.round(number * 1000) / 10}%`
}

const getStatType = (key) => {
  const types = {
    'class-Normal': 'success',
    'class-Bent': 'warning',
    'class-Deformed': 'primary',
    'class-Rusty': 'warning',
    'class-Missing': 'danger',
    'class-Compromised': 'danger'
  }
  return types[key] || 'info'
}

// ==================== 单图检测 ====================

const { handleUploadChange, handleRemove } = useSingleImageUploadPreview({
  form,
  fileList,
  detectionResult,
  annotatedImageUrl
})

const handleSingleDetection = async () => {
  if (!form.imageFile) {
    ElMessage.error('请先选择图片')
    return
  }

  loadingSingle.value = true
  detectionResult.value = null
  annotatedImageUrl.value = ''

  try {
    const formData = new FormData()
    formData.append('imageFile', form.imageFile, form.imageFile.name)
    if (form.modelId) {
      formData.append('modelId', String(form.modelId))
    }

    const response = await detectSingleImage(formData)
    if (!response.data || response.data.code !== 200) {
      throw new Error(response.data?.message || '单图检测失败')
    }

    detectionResult.value = response.data.data
    annotatedImageUrl.value = response.data.data.annotatedImagePath || response.data.data.processedImagePath || ''
  } catch (error) {
    console.error('单图检测失败:', error)
    ElMessage.error(`单图检测失败: ${error.message || '未知错误'}`)
  } finally {
    loadingSingle.value = false
  }
}

// ==================== 工具函数 ====================

const formatConfidence = (confidence) => {
  if (confidence === undefined || confidence === null) {
    return '0.00%'
  }
  return `${(Number(confidence) * 100).toFixed(2)}%`
}

const normalizeCategory = (category) => {
  if (!category) return ''
  return CATEGORY_ALIASES[category] || category
}

const getCategoryType = (category) => {
  const typeMap = {
    success: 'success',
    processing: 'primary',
    orange: 'warning',
    error: 'danger',
    volcano: 'danger',
    default: 'info'
  }
  return typeMap[CATEGORY_COLORS[normalizeCategory(category)]] || 'info'
}

const getCategoryText = (category) => {
  const normalized = normalizeCategory(category)
  return CATEGORY_LABELS[normalized] || normalized || category || '未知'
}

const fetchModels = async () => {
  try {
    const response = await fetchAvailableModels()
    if (response.data.code === 200) {
      modelList.value = response.data.data || []
    }
  } catch (error) {
    console.error('获取模型列表失败:', error)
  }
}

// ==================== 生命周期 ====================

const refreshingTasks = ref(false)
const refreshTaskList = async () => {
  refreshingTasks.value = true
  try {
    await fetchTaskList()
    ElMessage.success('任务列表已刷新')
  } catch (e) {
    ElMessage.error('刷新失败')
  } finally {
    refreshingTasks.value = false
  }
}

const flowStatusText = (status) => {
  const map = {
    UPLOADING: '上传中',
    PENDING_DETECTION: '待检测',
    DETECTING: '检测中',
    PENDING_REVIEW: '待复核',
    REVIEWING: '复核中',
    CONFIRMED: '已确认',
    ARCHIVED: '已归档',
    FAILED: '失败'
  }
  return map[status] || status || '--'
}

const dispositionStatusText = (status) => {
  const map = {
    PENDING: '待处置',
    DISPOSED: '已处置'
  }
  return map[status] || status || '--'
}

const dispositionActionText = (action) => {
  const map = {
    RELEASE: '正常放行',
    REWORK: '返工处理',
    RECHECK: '安排复检',
    HOLD: '暂挂观察',
    SCRAP: '报废隔离'
  }
  return map[action] || action || '--'
}

const reviewStatusText = (status) => {
  const map = {
    PENDING: '待复核',
    REVIEWED: '已复核',
    SKIPPED: '已跳过'
  }
  return map[status] || status || '--'
}

const reviewStatusTagType = (status) => {
  const map = {
    PENDING: 'warning',
    REVIEWED: 'success',
    SKIPPED: 'info'
  }
  return map[status] || 'info'
}

const reviewConclusionText = (conclusion) => {
  const map = {
    CONFIRMED_DEFECT: '确认缺陷',
    FALSE_POSITIVE: '误报',
    NORMAL_RELEASE: '正常放行',
    NEEDS_RECHECK: '需二次复查'
  }
  return map[conclusion] || conclusion || '--'
}

const severityText = (severity) => {
  const map = {
    MINOR: '轻微',
    MAJOR: '一般',
    CRITICAL: '严重'
  }
  return map[severity] || severity || '--'
}

const severityTagType = (severity) => {
  const map = {
    MINOR: 'info',
    MAJOR: 'warning',
    CRITICAL: 'danger'
  }
  return map[severity] || 'info'
}

const canReleaseDisposition = (task) => {
  const conclusion = task?.reviewConclusion || task?.result?.reviewConclusion
  return ['NORMAL_RELEASE', 'FALSE_POSITIVE'].includes(conclusion)
}

const canAssignQualityTask = (task) => {
  const status = task.status || task.result?.status
  const stage = task.stage
  const flowStatus = task.flowStatus || task.result?.flowStatus
  return (stage === 'completed' || status === 'COMPLETED' || status === 'PARTIAL_FAILED') &&
    !['RELEASED', 'SCRAPPED', 'ARCHIVED'].includes(flowStatus)
}

const canDisposeTask = (task) => {
  const reviewStatus = task.reviewStatus || task.result?.reviewStatus
  const dispositionStatus = task.dispositionStatus || task.result?.dispositionStatus
  const flowStatus = task.flowStatus || task.result?.flowStatus
  return (task.stage === 'completed' || task.status === 'COMPLETED' || task.status === 'PARTIAL_FAILED') &&
    reviewStatus === 'REVIEWED' &&
    dispositionStatus !== 'DISPOSED' &&
    ['CONFIRMED', 'HOLD'].includes(flowStatus)
}

const openTraceDialog = async (taskId) => {
  traceDialogVisible.value = true
  traceLoading.value = true
  traceDetail.value = null
  try {
    const response = await fetchDetectionTaskTrace(taskId)
    if (response.data?.code === 200) {
      traceDetail.value = response.data.data
    } else {
      ElMessage.error(response.data?.message || '获取追溯详情失败')
    }
  } catch (error) {
    console.error('获取追溯详情失败:', error)
    ElMessage.error(error.response?.data?.message || '获取追溯详情失败')
  } finally {
    traceLoading.value = false
  }
}

const loadWorkOrderTraceReport = async () => {
  const workOrderNo = workOrderTraceNo.value.trim()
  if (!workOrderNo) {
    ElMessage.warning('请输入工单号')
    return
  }
  workOrderTraceLoading.value = true
  workOrderTraceReport.value = null
  try {
    const response = await fetchWorkOrderTraceReport(workOrderNo)
    if (response.data?.code === 200) {
      workOrderTraceReport.value = response.data.data
      ElMessage.success('工单追溯报告已生成')
    } else {
      ElMessage.error(response.data?.message || '获取工单追溯失败')
    }
  } catch (error) {
    console.error('获取工单追溯失败:', error)
    ElMessage.error(error.response?.data?.message || '获取工单追溯失败')
  } finally {
    workOrderTraceLoading.value = false
  }
}

const loadBatchTraceReport = async () => {
  const batchNo = batchTraceNo.value.trim()
  if (!batchNo) {
    ElMessage.warning('请输入批次号')
    return
  }
  batchTraceLoading.value = true
  batchTraceReport.value = null
  try {
    const response = await fetchBatchTraceReport(batchNo)
    if (response.data?.code === 200) {
      batchTraceReport.value = response.data.data
      ElMessage.success('批次追溯报告已生成')
    } else {
      ElMessage.error(response.data?.message || '获取批次追溯失败')
    }
  } catch (error) {
    console.error('获取批次追溯失败:', error)
    ElMessage.error(error.response?.data?.message || '获取批次追溯失败')
  } finally {
    batchTraceLoading.value = false
  }
}

const loadBusinessWorkOrderTrace = async (workOrderNo) => {
  workOrderTraceNo.value = workOrderNo
  await loadWorkOrderTraceReport()
}

const loadBusinessBatchTrace = async (batchNo) => {
  batchTraceNo.value = batchNo
  await loadBatchTraceReport()
}

onMounted(async () => {
  const queryWorkOrderNo = route.query.workOrderNo
  if (queryWorkOrderNo) {
    workOrderTraceNo.value = String(queryWorkOrderNo)
    await loadWorkOrderTraceReport()
  }
})

onBeforeUnmount(() => {
  // 不再停止轮询 — 轮询在 store 中，切换页面后继续
  // 只保存当前状态
  saveTaskList()
})
</script>

<style scoped>
.image-detection-container {
  display: grid;
  gap: 24px;
}

.detection-hero {
  align-items: stretch;
}

.detection-flow-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 16px;
}

.hero-side-note {
  position: relative;
  z-index: 1;
  min-width: 260px;
  max-width: 360px;
  display: grid;
  gap: 8px;
  align-content: center;
  padding: 18px;
  border-radius: 18px;
  color: #e8f4ff;
  background:
    radial-gradient(circle at 18% 0%, rgba(56, 189, 248, 0.30), transparent 36%),
    linear-gradient(135deg, #0f2f57, #17416f);
  box-shadow: var(--app-shadow-command);
}

.hero-side-note strong {
  font-size: 16px;
}

.hero-side-note span {
  color: rgba(232, 244, 255, 0.78);
  line-height: 1.7;
}

.workspace-tabs :deep(.el-tabs__content) {
  margin-top: 8px;
}

.workspace-tabs :deep(.el-tabs__header) {
  padding: 0 4px;
}

.workspace-tabs :deep(.el-tabs__item) {
  height: 48px;
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(0, 7fr) minmax(0, 13fr);
  gap: 24px;
  align-items: start;
}

.detection-card {
  min-width: 0;
  border-radius: 24px;
  border-color: rgba(37, 99, 235, 0.10);
  box-shadow: var(--app-shadow-command);
}

.detection-card :deep(.el-card__header) {
  background:
    linear-gradient(90deg, rgba(239, 246, 255, 0.82), rgba(255, 255, 255, 0));
  padding-bottom: 10px !important;
}

.input-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

.input-block {
  position: relative;
  overflow: hidden;
  padding: 18px;
  border: 1px solid rgba(37, 99, 235, 0.10);
  border-radius: 18px;
  background:
    radial-gradient(circle at right top, rgba(14, 165, 233, 0.12), transparent 38%),
    linear-gradient(180deg, rgba(248, 250, 252, 0.95), rgba(255, 255, 255, 0.9));
}

.input-block::after {
  content: "";
  position: absolute;
  right: -26px;
  bottom: -30px;
  width: 88px;
  height: 88px;
  border: 1px solid rgba(37, 99, 235, 0.08);
  border-radius: 999px;
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

.secondary-action {
  margin-top: 12px;
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

.task-card {
  overflow: hidden;
}

.card-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* 筛选标签栏 */
.task-search-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}

.task-search-input {
  flex: 1;
}

.task-date-picker {
  width: 130px;
}

.task-filter-bar {
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
}

.task-filter-bar :deep(.el-radio-button__inner) {
  min-width: 80px;
  text-align: center;
}

.task-list {
  display: grid;
  gap: 10px;
}

.task-item {
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid rgba(37, 99, 235, 0.08);
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.96), rgba(248, 251, 255, 0.92));
  cursor: pointer;
  transition: all 0.18s;
}

.task-item:hover {
  border-color: rgba(37, 99, 235, 0.20);
  background: #fff;
  box-shadow: var(--app-shadow-sm);
  transform: translateY(-1px);
}

.task-item-selected {
  border-color: var(--app-primary);
  background: linear-gradient(135deg, #eff6ff, #ffffff);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.10);
}

.task-item-main {
  display: grid;
  gap: 0;
}

.task-item-taskid {
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
  color: var(--app-primary);
  background: var(--app-primary-soft);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: 'SF Mono', 'Consolas', monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-item-row1 {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-item-folder {
  font-weight: 600;
  color: var(--app-text);
  font-size: 14px;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-item-capture {
  display: flex;
  gap: 12px;
  margin-top: 4px;
  font-size: 12px;
  color: #8b95a5;
  flex-wrap: wrap;
}

.task-item-capture span::before {
  content: '·';
  margin-right: 4px;
}

.task-item-capture span:first-child::before {
  content: '';
  margin-right: 0;
}

.task-item-count {
  color: #8b95a5;
  font-size: 12px;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.task-item-tag {
  flex-shrink: 0;
  font-size: 12px;
  line-height: 20px;
}

.task-expand-icon {
  font-size: 12px;
  color: #b0b8c4;
  transition: transform 0.25s;
  flex-shrink: 0;
}

.task-expand-icon-open {
  transform: rotate(180deg);
  color: #1677ff;
}

.task-item-row2 {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
  gap: 8px;
}

.task-item-status {
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

.task-item-status.status-error { color: #e84749; }
.task-item-status.status-warn { color: #d48806; }
.task-item-status.status-ok { color: #389e0d; }

.task-item-time {
  font-size: 11px;
  color: #b0b8c4;
  white-space: nowrap;
  flex-shrink: 0;
}

.task-item-actions {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(37, 99, 235, 0.08);
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
}

.task-item-actions :deep(.el-button.is-link) {
  padding: 0 8px;
  font-size: 12px;
  height: 28px;
}

.task-item-detail {
  margin-top: 0;
  overflow: hidden;
}

/* 展开详情中的表格使用固定布局，防止内容列宽度不一致 */
.task-item-detail :deep(.el-descriptions__table) {
  table-layout: fixed;
  width: 100%;
}

/* 步骤条描述文本截断，防止撑开步骤宽度 */
.task-item-detail :deep(.el-step__description) {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-result-inline {
  margin-top: 8px;
}

.task-log-block {
  margin: 12px 0;
  padding: 12px 14px;
  border-radius: 12px;
  background: linear-gradient(135deg, #f8fbff, #f8fafc);
  border: 1px solid rgba(37, 99, 235, 0.08);
}

.task-log-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  color: #5b6475;
  font-size: 13px;
  font-weight: 500;
}

.task-log-list {
  display: grid;
  gap: 6px;
}

.task-log-item {
  display: flex;
  gap: 10px;
  font-size: 12px;
  color: #475569;
}

.task-log-time {
  min-width: 64px;
  color: #94a3b8;
  flex-shrink: 0;
}

.task-log-text {
  color: #475569;
}

.result-card {
  margin-top: 24px;
}

.stats-block {
  margin-top: 16px;
}

.stats-block h4 {
  margin-bottom: 12px;
  color: #172033;
}

.quality-queue-card {
  overflow: hidden;
}

.quality-queue-tabs {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.quality-queue-chip {
  border: 1px solid rgba(37, 99, 235, 0.10);
  background:
    radial-gradient(circle at right top, rgba(14, 165, 233, 0.08), transparent 42%),
    linear-gradient(135deg, #ffffff, #f8fafc);
  border-radius: 16px;
  padding: 11px 12px;
  text-align: left;
  cursor: pointer;
  transition: all 0.18s ease;
}

.quality-queue-chip span {
  display: block;
  color: #172033;
  font-size: 13px;
  font-weight: 800;
}

.quality-queue-chip small {
  display: block;
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
}

.quality-queue-chip.active {
  border-color: rgba(37, 99, 235, 0.42);
  background:
    radial-gradient(circle at right top, rgba(14, 165, 233, 0.16), transparent 42%),
    linear-gradient(135deg, #eff6ff, #ffffff);
  box-shadow: 0 12px 26px rgba(37, 99, 235, 0.1);
  transform: translateY(-1px);
}

.quality-queue-table {
  margin-top: 8px;
}

.quality-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.defect-filter-bar {
  display: grid;
  grid-template-columns: minmax(180px, 1.2fr) minmax(150px, 0.9fr) minmax(150px, 1fr) minmax(150px, 1fr) minmax(130px, 0.8fr) auto auto;
  gap: 10px;
  align-items: center;
  margin-bottom: 16px;
}

.defect-gallery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}

.defect-evidence-card {
  overflow: hidden;
  border: 1px solid rgba(37, 99, 235, 0.10);
  border-radius: 18px;
  background:
    linear-gradient(135deg, #ffffff, #f8fbff);
  box-shadow: var(--app-shadow-sm);
  transition: all var(--app-transition-fast);
}

.defect-evidence-card:hover {
  border-color: rgba(37, 99, 235, 0.22);
  box-shadow: var(--app-shadow-command);
  transform: translateY(-2px);
}

.defect-card-image {
  height: 190px;
  background:
    repeating-linear-gradient(45deg, rgba(37, 99, 235, 0.045) 0 1px, transparent 1px 14px),
    linear-gradient(135deg, rgba(15, 23, 42, 0.05), rgba(37, 99, 235, 0.08)),
    #f8fafc;
  display: flex;
  align-items: center;
  justify-content: center;
}

.defect-card-image img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.defect-card-body {
  padding: 14px;
}

.defect-card-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.defect-card-title code {
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 800;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.defect-card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.defect-card-meta span {
  padding: 4px 7px;
  border-radius: 999px;
  background: var(--app-surface-blueprint);
  color: #475569;
  font-size: 11px;
  font-weight: 650;
}

.defect-evidence-list {
  display: grid;
  gap: 5px;
  margin-top: 10px;
  color: #64748b;
  font-size: 12px;
}

.defect-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.preview-grid {
  display: grid;
  gap: 16px;
  margin-top: 20px;
}

.preview-card {
  padding: 16px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.92);
}

.preview-title {
  margin-bottom: 12px;
  font-weight: 600;
  color: #172033;
}

.preview-images {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.preview-pane {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.preview-pane span {
  font-size: 12px;
  color: #5b6475;
}

.preview-pane img,
.single-result-image img {
  width: 100%;
  border-radius: 14px;
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.preview-empty {
  padding: 28px 12px;
  border-radius: 12px;
  background: #f8fafc;
  color: #94a3b8;
  text-align: center;
}

.single-result-layout {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 20px;
}

.single-result-image {
  min-height: 280px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 18px;
  background: #f8fafc;
}

/* 检测记录筛选栏 */
.history-filter-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
  align-items: center;
}

.history-filter-input {
  width: 160px;
}

/* 检测记录卡片 */
.history-grid {
  display: grid;
  gap: 14px;
}

.history-pagination {
  display: flex;
  justify-content: center;
  padding: 16px 0 4px;
}

.history-record-card {
  padding: 18px 20px;
  border-radius: 16px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  background: #fafbfc;
  transition: all 0.18s;
}

.history-record-card:hover {
  border-color: rgba(22, 119, 255, 0.15);
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
}

.record-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.record-header-left {
  flex: 1;
  min-width: 0;
}

.record-folder {
  font-weight: 600;
  color: #172033;
  font-size: 15px;
}

.record-taskid {
  font-size: 12px;
  color: #8b95a5;
  font-family: monospace;
  margin-top: 2px;
}

.record-capture {
  display: flex;
  gap: 12px;
  margin-top: 4px;
  font-size: 12px;
  color: #8b95a5;
  flex-wrap: wrap;
}

.record-capture span::before {
  content: '·';
  margin-right: 4px;
}

.record-capture span:first-child::before {
  content: '';
  margin-right: 0;
}

.record-oss-path {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  font-size: 11px;
}

.oss-path-label {
  color: #94a3b8;
  flex-shrink: 0;
}

.oss-path-value {
  font-size: 11px;
  color: #1677ff;
  background: rgba(22, 119, 255, 0.06);
  padding: 1px 6px;
  border-radius: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.record-stats {
  margin-bottom: 12px;
  padding: 12px 0;
  border-top: 1px solid rgba(15, 23, 42, 0.04);
  border-bottom: 1px solid rgba(15, 23, 42, 0.04);
}

.record-stats :deep(.el-statistic__head) {
  font-size: 12px;
  margin-bottom: 2px;
}

.record-classes {
  margin-bottom: 10px;
}

.record-preview {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding: 4px 0 8px;
  margin-bottom: 10px;
}

.record-preview-img {
  width: 72px;
  height: 72px;
  border-radius: 10px;
  object-fit: cover;
  border: 1px solid rgba(15, 23, 42, 0.08);
  flex-shrink: 0;
  background: #f0f0f0;
}

.record-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 10px;
  border-top: 1px solid rgba(15, 23, 42, 0.04);
}

.record-task-id {
  font-size: 11px;
  color: #b0b8c4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.record-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.record-actions :deep(.el-button.is-link) {
  padding: 0 8px;
  font-size: 12px;
  height: 28px;
}

.path-text {
  color: #172033;
}

.trace-dialog-body {
  min-height: 180px;
}

.trace-section {
  margin-bottom: 16px;
}

.trace-section h4 {
  margin: 0 0 10px;
  color: #172033;
}

.trace-paths {
  display: grid;
  gap: 8px;
  padding: 12px;
  border-radius: 12px;
  background: #f8fafc;
}

.trace-paths div {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 8px;
  align-items: center;
}

.trace-paths span {
  color: #64748b;
  font-size: 12px;
}

.trace-paths code,
.trace-paths a {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #1677ff;
}

.trace-event-meta {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.batch-trace-card {
  overflow: hidden;
}

.batch-trace-search {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  margin-bottom: 10px;
}

.trace-sample-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 18px;
  color: #64748b;
  font-size: 13px;
}

.batch-trace-body {
  min-height: 220px;
}

.batch-summary-band {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  padding: 16px;
  margin-bottom: 16px;
  border-radius: 20px;
  color: #fff;
  background:
    radial-gradient(circle at top left, rgba(255, 255, 255, 0.28), transparent 34%),
    linear-gradient(135deg, #0f766e 0%, #164e63 56%, #172554 100%);
}

.batch-summary-band div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.batch-summary-band span {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.72);
}

.batch-summary-band strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
}

.batch-metrics {
  margin-bottom: 16px;
}

.batch-metrics :deep(.el-col) {
  margin-bottom: 12px;
}

.batch-metrics :deep(.el-statistic) {
  padding: 14px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 16px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}

.batch-section-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}

.batch-panel {
  padding: 16px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.86);
}

.batch-panel h3 {
  margin: 0 0 12px;
  font-size: 15px;
  color: #172033;
}

.batch-quality-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.batch-quality-list div {
  display: grid;
  gap: 4px;
  padding: 10px;
  border-radius: 12px;
  background: #f8fafc;
}

.batch-quality-list span,
.batch-time-range span {
  font-size: 12px;
  color: #64748b;
}

.batch-quality-list strong {
  font-size: 20px;
  color: #0f172a;
}

.batch-context-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.batch-time-range {
  display: grid;
  gap: 6px;
}

@media (max-width: 1080px) {
  .workspace-grid,
  .input-grid,
  .single-result-layout,
  .preview-images,
  .defect-filter-bar,
  .batch-section-grid {
    grid-template-columns: 1fr;
  }

  .batch-summary-band {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .batch-trace-search,
  .defect-filter-bar,
  .batch-summary-band,
  .batch-quality-list {
    grid-template-columns: 1fr;
  }

  .defect-gallery-grid {
    grid-template-columns: 1fr;
  }
}
</style>
