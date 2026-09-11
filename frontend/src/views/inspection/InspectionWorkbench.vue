<template>
  <div class="page-shell image-detection-container inspection-workbench-page">
    <section class="page-hero detection-hero command-panel">
      <div>
        <span class="industrial-kicker">Detection Workspace</span>
        <h1 class="page-hero-title">检测工作台</h1>
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

        <div class="workspace-grid">
          <el-card class="detection-card" header="检测输入" shadow="never">
            <el-form label-position="top">
              <el-form-item label="选择模型（可选）">
                <el-select
                  v-model="form.modelId"
                  placeholder="请选择模型，不选则使用默认模型"
                  clearable
                >
                  <el-option
                    v-for="model in modelList"
                    :key="model.modelId"
                    :value="model.modelId"
                    :label="`${model.modelName} (v${model.version})`"
                  >
                    {{ model.modelName }} (v{{ model.version }})
                  </el-option>
                </el-select>
              </el-form-item>

              <el-form-item label="置信度阈值">
                <el-slider v-model="form.threshold" :min="0" :max="1" :step="0.01" />
                <div class="threshold-text">当前阈值：{{ Math.round(form.threshold * 100) }}%</div>
              </el-form-item>

              <div class="input-grid">
                <div class="input-block">
                  <div class="input-block-title">单图检测</div>
                  <el-upload
                    v-model:file-list="fileList"
                    :auto-upload="false"
                    :on-change="handleUploadChange"
                    :on-remove="handleRemove"
                    accept=".jpg,.jpeg,.png"
                    list-type="picture"
                    :limit="1"
                  >
                    <el-button type="primary" class="wide-button">
                      <el-icon><Upload /></el-icon>
                      选择单张图片
                    </el-button>
                  </el-upload>
                  <el-button
                    type="default"
                    class="wide-button secondary-action"
                    :disabled="!form.imageFile"
                    :loading="loadingSingle"
                    @click="handleSingleDetection"
                  >
                    <el-icon><VideoPlay /></el-icon>
                    开始单图检测
                  </el-button>
                </div>
              </div>
            </el-form>
          </el-card>

          <el-card class="detection-card task-card" shadow="never">
            <template #header>
              <div class="card-title-row">
                <span>上传任务列表</span>
                <el-badge v-if="taskList.length" :value="taskList.length"  />
                <el-button size="small" link :loading="refreshingTasks" @click="refreshTaskList" title="刷新任务列表">
                  <template #icon><el-icon><Refresh /></el-icon></template>
                </el-button>
              </div>
            </template>
            <!-- 搜索栏 -->
            <div class="task-search-bar">
              <el-input
                v-model="taskSearchKeyword"
                placeholder="搜索任务ID或文件夹名…"
                clearable
                size="small"
                class="task-search-input"
              >
                <template #prefix><el-icon><Search /></el-icon></template>
              </el-input>
              <el-date-picker
                v-model="taskFilterDate"
                placeholder="选择日期"
                size="small"
                class="task-date-picker"
                value-format="YYYY-MM-DD"
                clearable
              />
            </div>
            <!-- 筛选标签 -->
            <div v-if="taskList.length" class="task-filter-bar">
              <el-radio-group v-model="taskFilter" size="small" >
                <el-radio-button value="all">全部</el-radio-button>
                <el-radio-button value="pending">待检测</el-radio-button>
                <el-radio-button value="running">检测中</el-radio-button>
                <el-radio-button value="done">已完成</el-radio-button>
                <el-radio-button value="failed">失败</el-radio-button>
              </el-radio-group>
            </div>
            <el-empty
              v-if="filteredTaskList.length === 0"
              :description="taskList.length ? '没有匹配的任务' : '暂无检测任务'"
              :image-size="64"
            >
              <template #default>
                <BusinessSeedEmptyHint
                  :title="taskList.length ? '没有匹配的任务' : '暂无检测任务'"
                  description="可上传图片生成检测任务；首次验收完整业务闭环时，也可启用业务预置数据。"
                />
                <router-link v-if="!taskList.length" to="/upload">
                  <el-button type="primary" size="small">前往上传图片</el-button>
                </router-link>
              </template>
            </el-empty>
            <div v-else class="task-list">
              <div
                v-for="task in filteredTaskList"
                :key="task.taskId"
                class="task-item"
                :class="{ 'task-item-selected': selectedTaskId === task.taskId }"
                @click="selectedTaskId = selectedTaskId === task.taskId ? null : task.taskId"
              >
                <!-- 可折叠行 -->
                <div class="task-item-main">
                  <div class="task-item-taskid">
                    <span class="taskid-label">任务ID</span>
                    <code class="taskid-value">{{ task.taskId }}</code>
                  </div>
                  <div class="task-item-row1">
                    <span class="task-item-folder">{{ task.folderName }}</span>
                    <span class="task-item-count">{{ task.imageCount }} 张</span>
                    <el-tag :type="taskTagType(task)" class="task-item-tag">{{ taskTagText(task) }}</el-tag>
                    <el-icon
                      class="task-expand-icon"
                      :class="{ 'task-expand-icon-open': selectedTaskId === task.taskId }"
                    >
                      <ArrowDown />
                    </el-icon>
                  </div>
                  <div class="task-item-capture">
                    <span v-if="task.batchNo">批次：{{ task.batchNo }}</span>
                    <span v-if="task.workOrderNo">工单：{{ task.workOrderNo }}</span>
                    <span v-if="task.flowStatus">流转：{{ flowStatusText(task.flowStatus) }}</span>
                    <span v-if="task.reviewStatus">复核：{{ reviewStatusText(task.reviewStatus) }}</span>
                    <span v-if="task.severityLevel">等级：{{ severityText(task.severityLevel) }}</span>
                  </div>
                  <div v-if="task.captureInfo" class="task-item-capture">
                    <span v-if="task.captureInfo.captureDate">{{ task.captureInfo.captureDate }}</span>
                    <span v-if="task.captureInfo.collector">{{ task.captureInfo.collector }}</span>
                    <span v-if="task.captureInfo.deviceName">{{ task.captureInfo.deviceName }}</span>
                  </div>
                  <el-progress
                    :percentage="task.progressPercent"
                    :stroke-width="5"
                    size="small"
                    :status="task.progressPercent === 100 && task.stage === 'completed' ? 'success' : (task.stage === 'failed' ? 'exception' : 'active')"
                    style="margin: 6px 0 2px;"
                  />
                  <div class="task-item-row2">
                    <span class="task-item-status" :class="{
                      'status-error': taskStatusDetail(task).type === 'error',
                      'status-warn': taskStatusDetail(task).type === 'warn',
                      'status-ok': taskStatusDetail(task).type === 'success'
                    }">
                      <el-icon v-if="taskStatusDetail(task).type === 'success'"><CircleCheck /></el-icon>
                      <el-icon v-else-if="taskStatusDetail(task).type === 'warn' || taskStatusDetail(task).type === 'error'"><Warning /></el-icon>
                      <el-icon v-else><Clock /></el-icon>
                      {{ taskStatusDetail(task).text }}
                    </span>
                    <span class="task-item-time">{{ formatRelativeTime(task.updatedAt) }} · {{ formatAbsoluteTime(task.updatedAt) }}</span>
                  </div>
                </div>

                <!-- 操作按钮 -->
                <div class="task-item-actions">
                  <el-button
                    v-if="task.stage === 'uploaded' && task.uploadedFiles.length"
                    type="primary"
                    size="small"
                    :loading="task.stage === 'queued' || task.stage === 'detecting'"
                    @click.stop="startTaskDetection(task, form.modelId, form.threshold)"
                  >
                    <el-icon><VideoPlay /></el-icon>开始检测
                  </el-button>
                  <el-tag v-if="task.stage === 'queued'" type="primary" style="font-size:12px">等待调度</el-tag>
                  <el-tag v-if="task.stage === 'detecting'" type="primary" style="font-size:12px">远程检测中</el-tag>
                  <el-button
                    v-if="task.stage === 'completed' || task.stage === 'failed'"
                    link
                    size="small"
                    type="primary"
                    @click.stop="openTraceDialog(task.taskId)"
                  >
                    追溯详情
                  </el-button>
                  <el-button
                    v-if="task.stage === 'completed' || task.stage === 'failed'"
                    link
                    size="small"
                    type="success"
                    @click.stop="downloadTaskQualityReport(task.taskId)"
                  >
                    导出报告
                  </el-button>
                  <el-button
                    v-if="task.stage === 'completed' || task.stage === 'failed'"
                    link
                    size="small"
                    type="danger"
                    @click.stop="removeTask(task.taskId)"
                  >
                    <el-icon><Delete /></el-icon>移除
                  </el-button>
                  <el-button
                    v-if="canAssignQualityTask(task)"
                    type="info"
                    size="small"
                    @click.stop="openAssignmentDialog(task)"
                  >
                    分派质检
                  </el-button>
                  <el-button
                    v-if="task.flowStatus === 'PENDING_REVIEW'"
                    type="success"
                    size="small"
                    @click.stop="openReviewDialog(task)"
                  >
                    确认复核
                  </el-button>
                  <el-button
                    v-if="canDisposeTask(task)"
                    type="warning"
                    size="small"
                    @click.stop="openDispositionDialog(task)"
                  >
                    质检处置
                  </el-button>
                  <el-button
                    v-if="task.flowStatus === 'REWORK_REQUIRED'"
                    type="primary"
                    size="small"
                    @click.stop="openReworkDialog(task)"
                  >
                    返工回填
                  </el-button>
                </div>

                <!-- 展开详情 -->
                <div v-if="selectedTaskId === task.taskId" class="task-item-detail">
                  <el-divider style="margin: 10px 0;" />
                  <el-steps :current="taskStepIndex(task)" :status="task.stage === 'failed' ? 'error' : 'process'" size="small" style="margin-bottom: 10px;">
                    <el-step title="已交给模型处理" :description="taskStepDesc(task, 0)" />
                    <el-step title="模型正在检测" :description="taskStepDesc(task, 1)" />
                    <el-step title="检测完成" :description="taskStepDesc(task, 2)" />
                  </el-steps>

                  <el-alert v-if="task.error" type="error" show-icon :message="task.error" style="margin-bottom: 10px;" />

                  <div v-if="task.logs.length" class="task-log-block">
                    <div class="task-log-head"><span>最近动态</span></div>
                    <div class="task-log-list">
                      <div v-for="log in task.logs" :key="log.id" class="task-log-item">
                        <span class="task-log-time">{{ log.time }}</span>
                        <span class="task-log-text">{{ log.text }}</span>
                      </div>
                    </div>
                  </div>

                  <!-- 检测结果 -->
                  <div v-if="task.result" class="task-result-inline">
                    <el-alert
                      :type="task.result.status === 'COMPLETED' ? 'success' : 'warning'"
                      :message="task.result.status === 'COMPLETED' ? '检测已完成' : '任务已结束'"
                      show-icon
                      style="margin-bottom: 12px;"
                    />
                    <el-descriptions bordered :column="1" size="small" :label-style="{ width: '100px', whiteSpace: 'nowrap' }" :content-style="{ wordBreak: 'break-all' }">
                      <el-descriptions-item label="任务编号"><code>{{ task.result.taskId }}</code></el-descriptions-item>
                      <el-descriptions-item label="复核状态">
                        <el-tag :type="reviewStatusTagType(task.reviewStatus || task.result.reviewStatus)">
                          {{ reviewStatusText(task.reviewStatus || task.result.reviewStatus) }}
                        </el-tag>
                      </el-descriptions-item>
                      <el-descriptions-item label="复核结论">
                        {{ reviewConclusionText(task.reviewConclusion || task.result.reviewConclusion) }}
                      </el-descriptions-item>
                      <el-descriptions-item label="严重等级">
                        <el-tag :type="severityTagType(task.severityLevel || task.result.severityLevel)">
                          {{ severityText(task.severityLevel || task.result.severityLevel) }}
                        </el-tag>
                      </el-descriptions-item>
                      <el-descriptions-item label="质检站点">
                        {{ task.qualityStation || task.result.qualityStation || '--' }}
                      </el-descriptions-item>
                      <el-descriptions-item label="责任人">
                        {{ task.assignee || task.result.assignee || '--' }}
                      </el-descriptions-item>
                      <el-descriptions-item label="质检截止">
                        {{ task.dueAt || task.result.dueAt || '--' }}
                      </el-descriptions-item>
                      <el-descriptions-item label="确认缺陷">
                        {{ task.confirmedDefectCount ?? task.result.confirmedDefectCount ?? 0 }} 个
                      </el-descriptions-item>
                      <el-descriptions-item label="误报反馈">
                        {{ task.falsePositiveCount ?? task.result.falsePositiveCount ?? 0 }} 个
                      </el-descriptions-item>
                      <el-descriptions-item v-if="task.reviewRemark || task.result.reviewRemark" label="复核备注">
                        {{ task.reviewRemark || task.result.reviewRemark }}
                      </el-descriptions-item>
                      <el-descriptions-item label="处置状态">
                        {{ dispositionStatusText(task.dispositionStatus || task.result.dispositionStatus) }}
                      </el-descriptions-item>
                      <el-descriptions-item v-if="task.dispositionAction || task.result.dispositionAction" label="处置动作">
                        {{ dispositionActionText(task.dispositionAction || task.result.dispositionAction) }}
                      </el-descriptions-item>
                      <el-descriptions-item v-if="task.reworkResult || task.result.reworkResult" label="返工结果">
                        {{ task.reworkResult || task.result.reworkResult }}
                      </el-descriptions-item>
                      <el-descriptions-item label="结果JSON">
                        <a v-if="task.result.resultJsonUrl" :href="task.result.resultJsonUrl" target="_blank">打开 detection_results.json</a>
                        <span v-else>暂无</span>
                      </el-descriptions-item>
                    </el-descriptions>
                    <div v-if="task.result.previewImages && task.result.previewImages.length" class="preview-grid" style="margin-top: 8px;">
                      <div v-for="item in task.result.previewImages.slice(0, 4)" :key="item.imageName" class="preview-card">
                        <div class="preview-title">{{ item.imageName }}</div>
                        <div class="preview-images">
                          <div class="preview-pane">
                            <span>标注图</span>
                            <img v-if="item.annotatedUrl" :src="item.annotatedUrl" :alt="item.imageName" />
                            <div v-else class="preview-empty">暂无</div>
                          </div>
                        </div>
                      </div>
                    </div>
                    <div v-if="task.result.statistics" class="stats-block" style="margin-top: 10px;">
                      <h4>检测统计</h4>
                      <el-table :data="buildTaskStatistics(task.result.statistics)" size="small" border>
                        <el-table-column prop="label" label="指标" width="160" show-overflow-tooltip />
                        <el-table-column prop="value" label="数值" width="120" />
                      </el-table>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </el-card>
        </div>

        <!-- 单图检测结果 -->
        <el-card v-if="detectionResult && !detectionResult.taskId" class="detection-card result-card" header="检测结果" shadow="never">
          <div class="single-result-layout">
            <div class="single-result-image">
              <img v-if="annotatedImageUrl" :src="annotatedImageUrl" alt="标注图像" />
              <el-empty v-else description="暂无标注图" />
            </div>
            <div class="single-result-meta">
              <el-descriptions bordered :column="1">
                <el-descriptions-item label="检测类别">
                  <el-tag :type="getCategoryType(detectionResult.category)">
                    {{ getCategoryText(detectionResult.category) }}
                  </el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="置信度">
                  {{ formatConfidence(detectionResult.confidence) }}
                </el-descriptions-item>
              </el-descriptions>
            </div>
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
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { ArrowDown, CircleCheck, Clock, Delete, Download, Refresh, Search, Upload, VideoPlay, Warning } from '@element-plus/icons-vue'
import {
  assignDetectionQualityTask,
  detectSingleImage,
  disposeDetectionTask,
  fetchAvailableModels,
  fetchBatchTraceReport,
  fetchDefectGallery,
  fetchDetectionTaskTrace,
  fetchQualityQueue,
  fetchQualityReport,
  fetchWorkOrderTraceReport,
  reviewDetectionTask,
  submitDetectionReworkResult
} from '../../api/detection'
import { useTaskStore, useUploadStore, usePollingStore, CATEGORY_LABELS, CATEGORY_COLORS, CATEGORY_ALIASES } from '../../stores/detectionTask'
import { useSingleImageUploadPreview } from '../../composables/useSingleImageUploadPreview'
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
const reviewDialogVisible = ref(false)
const reviewSubmitting = ref(false)
const reviewTask = ref(null)
const assignmentDialogVisible = ref(false)
const assignmentSubmitting = ref(false)
const assignmentTask = ref(null)
const dispositionDialogVisible = ref(false)
const dispositionSubmitting = ref(false)
const dispositionTask = ref(null)
const reworkDialogVisible = ref(false)
const reworkSubmitting = ref(false)
const reworkTask = ref(null)
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

const reviewForm = reactive({
  reviewConclusion: 'CONFIRMED_DEFECT',
  severityLevel: 'MAJOR',
  confirmedDefectCount: 0,
  falsePositiveCount: 0,
  reviewRemark: ''
})

const assignmentForm = reactive({
  qualityStation: '质检站-1',
  assignee: '',
  dueAt: '',
  assignmentRemark: ''
})

const dispositionForm = reactive({
  dispositionAction: 'REWORK',
  recheckRequired: false,
  dispositionRemark: ''
})

const reworkForm = reactive({
  reworkResult: '',
  reworkOperator: '',
  recheckRequired: true,
  reworkRemark: ''
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

watch(
  () => [route.path, route.query.tab],
  () => {
    syncTabFromRoute()
  }
)

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

const applyTaskProgressUpdate = async (taskId, data, fallbackMessage) => {
  taskStore.updateTask(taskId, {
    flowStatus: data.flowStatus,
    qualityStation: data.qualityStation,
    assignee: data.assignee,
    assignmentRemark: data.assignmentRemark,
    assignedAt: data.assignedAt,
    dueAt: data.dueAt,
    reviewStatus: data.reviewStatus,
    reviewConclusion: data.reviewConclusion,
    severityLevel: data.severityLevel,
    confirmedDefectCount: data.confirmedDefectCount,
    falsePositiveCount: data.falsePositiveCount,
    reviewRemark: data.reviewRemark,
    reviewer: data.reviewer,
    reviewedAt: data.reviewedAt,
    dispositionStatus: data.dispositionStatus,
    dispositionAction: data.dispositionAction,
    dispositionRemark: data.dispositionRemark,
    dispositionOperator: data.dispositionOperator,
    disposedAt: data.disposedAt,
    recheckRequired: data.recheckRequired,
    reworkResult: data.reworkResult,
    reworkOperator: data.reworkOperator,
    reworkRemark: data.reworkRemark,
    reworkCompletedAt: data.reworkCompletedAt,
    message: data.message || fallbackMessage
  })
  await fetchTaskResults([taskId])
}

const openReviewDialog = (task) => {
  reviewTask.value = task
  reviewForm.reviewConclusion = task.reviewConclusion || 'CONFIRMED_DEFECT'
  reviewForm.severityLevel = task.severityLevel || 'MAJOR'
  reviewForm.confirmedDefectCount = task.confirmedDefectCount ?? 0
  reviewForm.falsePositiveCount = task.falsePositiveCount ?? 0
  reviewForm.reviewRemark = task.reviewRemark || ''
  reviewDialogVisible.value = true
}

const submitTaskReview = async () => {
  if (!reviewTask.value?.taskId) {
    ElMessage.error('请选择需要复核的任务')
    return
  }

  reviewSubmitting.value = true
  try {
    const response = await reviewDetectionTask(reviewTask.value.taskId, {
      reviewConclusion: reviewForm.reviewConclusion,
      severityLevel: reviewForm.severityLevel,
      confirmedDefectCount: reviewForm.confirmedDefectCount,
      falsePositiveCount: reviewForm.falsePositiveCount,
      reviewRemark: reviewForm.reviewRemark
    })
    if (response.data?.code === 200) {
      const data = response.data.data
      await applyTaskProgressUpdate(reviewTask.value.taskId, data, '人工复核已完成')
      await refreshQualityQueueIfVisible()
      await refreshDefectGalleryIfVisible()
      reviewDialogVisible.value = false
      ElMessage.success('人工复核已提交')
    } else {
      ElMessage.error(response.data?.message || '人工复核提交失败')
    }
  } catch (error) {
    console.error('人工复核提交失败:', error)
    ElMessage.error(error.response?.data?.message || '人工复核提交失败')
  } finally {
    reviewSubmitting.value = false
  }
}

const openAssignmentDialog = (task) => {
  assignmentTask.value = task
  assignmentForm.qualityStation = task.qualityStation || task.result?.qualityStation || '质检站-1'
  assignmentForm.assignee = task.assignee || task.result?.assignee || ''
  assignmentForm.dueAt = task.dueAt || task.result?.dueAt || ''
  assignmentForm.assignmentRemark = task.assignmentRemark || task.result?.assignmentRemark || ''
  assignmentDialogVisible.value = true
}

const submitQualityAssignment = async () => {
  if (!assignmentTask.value?.taskId) {
    ElMessage.error('请选择需要分派的任务')
    return
  }
  if (!assignmentForm.qualityStation.trim() || !assignmentForm.assignee.trim()) {
    ElMessage.warning('请填写质检站点和责任人')
    return
  }

  assignmentSubmitting.value = true
  try {
    const response = await assignDetectionQualityTask(assignmentTask.value.taskId, {
      qualityStation: assignmentForm.qualityStation,
      assignee: assignmentForm.assignee,
      dueAt: assignmentForm.dueAt,
      assignmentRemark: assignmentForm.assignmentRemark
    })
    if (response.data?.code === 200) {
      await applyTaskProgressUpdate(assignmentTask.value.taskId, response.data.data, '质检任务已分派')
      await refreshQualityQueueIfVisible()
      assignmentDialogVisible.value = false
      ElMessage.success('质检任务已分派')
    } else {
      ElMessage.error(response.data?.message || '质检分派失败')
    }
  } catch (error) {
    console.error('质检分派失败:', error)
    ElMessage.error(error.response?.data?.message || '质检分派失败')
  } finally {
    assignmentSubmitting.value = false
  }
}

const openDispositionDialog = (task) => {
  dispositionTask.value = task
  dispositionForm.dispositionAction = canReleaseDisposition(task) ? 'RELEASE' : 'REWORK'
  dispositionForm.recheckRequired = task.reviewConclusion === 'NEEDS_RECHECK'
  dispositionForm.dispositionRemark = task.dispositionRemark || ''
  dispositionDialogVisible.value = true
}

const submitTaskDisposition = async () => {
  if (!dispositionTask.value?.taskId) {
    ElMessage.error('请选择需要处置的任务')
    return
  }
  if (dispositionForm.dispositionAction === 'RELEASE' && !canReleaseDisposition(dispositionTask.value)) {
    ElMessage.warning('确认缺陷或待复检任务不能直接放行，请选择返工、复检、暂挂或报废')
    return
  }

  dispositionSubmitting.value = true
  try {
    const response = await disposeDetectionTask(dispositionTask.value.taskId, {
      dispositionAction: dispositionForm.dispositionAction,
      recheckRequired: dispositionForm.recheckRequired,
      dispositionRemark: dispositionForm.dispositionRemark
    })
    if (response.data?.code === 200) {
      await applyTaskProgressUpdate(dispositionTask.value.taskId, response.data.data, '质检处置已完成')
      await refreshQualityQueueIfVisible()
      dispositionDialogVisible.value = false
      ElMessage.success('质检处置已提交')
    } else {
      ElMessage.error(response.data?.message || '质检处置提交失败')
    }
  } catch (error) {
    console.error('质检处置提交失败:', error)
    ElMessage.error(error.response?.data?.message || '质检处置提交失败')
  } finally {
    dispositionSubmitting.value = false
  }
}

const openReworkDialog = (task) => {
  reworkTask.value = task
  reworkForm.reworkResult = task.reworkResult || ''
  reworkForm.reworkOperator = task.reworkOperator || ''
  reworkForm.recheckRequired = task.recheckRequired !== false
  reworkForm.reworkRemark = task.reworkRemark || ''
  reworkDialogVisible.value = true
}

const submitTaskRework = async () => {
  if (!reworkTask.value?.taskId) {
    ElMessage.error('请选择需要回填返工结果的任务')
    return
  }
  if (!reworkForm.reworkResult.trim()) {
    ElMessage.warning('请填写返工结果')
    return
  }

  reworkSubmitting.value = true
  try {
    const response = await submitDetectionReworkResult(reworkTask.value.taskId, {
      reworkResult: reworkForm.reworkResult,
      reworkOperator: reworkForm.reworkOperator,
      reworkRemark: reworkForm.reworkRemark,
      recheckRequired: reworkForm.recheckRequired
    })
    if (response.data?.code === 200) {
      await applyTaskProgressUpdate(reworkTask.value.taskId, response.data.data, '返工结果已提交')
      await refreshQualityQueueIfVisible()
      reworkDialogVisible.value = false
      ElMessage.success('返工结果已提交')
    } else {
      ElMessage.error(response.data?.message || '返工结果提交失败')
    }
  } catch (error) {
    console.error('返工结果提交失败:', error)
    ElMessage.error(error.response?.data?.message || '返工结果提交失败')
  } finally {
    reworkSubmitting.value = false
  }
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
  const routeTab = String(route.query.tab || route.meta?.detectionTab || '')
  if (validTabs.includes(routeTab)) {
    activeTab.value = routeTab
  }
  const queryQueue = String(route.query.queue || '')
  if (qualityQueues.some(queue => queue.value === queryQueue)) {
    activeQualityQueue.value = queryQueue
  }
  const queryKeyword = route.query.keyword
  if (queryKeyword) {
    activeTab.value = 'history'
    historySearchKeyword.value = String(queryKeyword)
  }
  if (route.query.defectType) defectFilters.defectType = String(route.query.defectType)
  if (route.query.severityLevel) defectFilters.severityLevel = String(route.query.severityLevel)
  if (route.query.deviceName) defectFilters.deviceName = String(route.query.deviceName)
  if (route.query.batchNo && activeTab.value === 'defect-gallery') defectFilters.batchNo = String(route.query.batchNo)
  if (route.query.modelId) defectFilters.modelId = Number(route.query.modelId)

  fetchModels()
  await restoreFromSession()
  await fetchTaskList()
  fetchHistoryWithFilters()
  if (activeTab.value === 'quality') {
    loadQualityQueue()
  }
  if (activeTab.value === 'defect-gallery') {
    loadDefectGallery()
  }

  // 从上传页跳转过来时自动选中对应任务
  const queryTaskId = route.query.taskId
  if (queryTaskId) {
    selectedTaskId.value = String(queryTaskId)
  }

  const queryWorkOrderNo = route.query.workOrderNo
  if (queryWorkOrderNo && activeTab.value === 'work-order-trace') {
    activeTab.value = 'work-order-trace'
    workOrderTraceNo.value = String(queryWorkOrderNo)
    await loadWorkOrderTraceReport()
  }

  const queryBatchNo = route.query.batchNo
  if (queryBatchNo && activeTab.value === 'batch-trace') {
    activeTab.value = 'batch-trace'
    batchTraceNo.value = String(queryBatchNo)
    await loadBatchTraceReport()
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
