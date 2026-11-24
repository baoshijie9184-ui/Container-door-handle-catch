<template>
  <div :class="boardRequest ? 'board-task-dialogs' : 'page-shell image-detection-container'">
    <template v-if="!boardRequest">
    <CollaborationRefreshNotice v-if="activeTab !== 'workspace'" :changed="collaborationChanged" :editing="collaborationEditing" :opened-version="collaborationOpenedTask?.version" :history-to="collaborationHistoryLink" @refresh="refreshCollaborationView" />
    <PageHero class="page-hero detection-hero command-panel">
      <div>
        <h1 class="page-hero-title">{{ workspacePresentation.title }}</h1>
      </div>
      <router-link v-if="activeTab === 'history'" class="upload-route" to="/upload"><AppIcon name="Upload" :size="16" />批量上传图片</router-link>
    </PageHero>

    <el-tabs v-model="activeTab" class="workspace-tabs" :class="{'single-test-tabs':activeTab === 'workspace'}" @tab-change="handleTabChange">
      <el-tab-pane name="workspace" label="单图检测与对比">
        <div class="workspace-grid">
          <el-card class="detection-card detection-input-card" shadow="never">
            <template #header>
              <div class="single-mode-header">
                <h2 class="detection-card-heading"><AppIcon name="Operation" :size="19" />单图检测</h2>
                <el-radio-group v-model="singleMode" aria-label="单图检测模式" :disabled="comparisonBusy || loadingSingle" size="small">
                  <el-radio-button value="compare">双模型对比</el-radio-button>
                  <el-radio-button value="single">单模型检测</el-radio-button>
                </el-radio-group>
              </div>
            </template>
            <SingleModelComparison v-if="activeTab === 'workspace'" v-show="singleMode === 'compare'"
              :key="comparisonScope" @busy="comparisonBusy=$event" />
            <el-form v-show="singleMode === 'single'" label-position="top">
              <div class="input-grid">
                <div class="input-block">
                  <div class="single-detection-workspace">
                    <div class="single-detection-controls">
                      <el-upload
                        v-model:file-list="fileList"
                        class="single-image-uploader"
                        drag
                        :auto-upload="false"
                        :on-change="handleUploadChange"
                        :on-remove="handleRemove"
                        accept=".jpg,.jpeg,.png"
                        list-type="picture"
                        :limit="1"
                        :disabled="loadingSingle"
                      >
                        <span class="single-file-target"><AppIcon name="Upload" :size="24" /><strong>选择单张图片</strong><small>或拖入 JPG、PNG 图片</small></span>
                      </el-upload>
                      <div
                        v-if="form.imageFile"
                        class="single-upload-file-name"
                        :title="form.imageFile.name"
                      >
                        <span>已选择文件</span>
                        <strong>{{ form.imageFile.name }}</strong>
                      </div>
                      <details class="detection-parameters">
                        <summary><AppIcon name="Operation" :size="16" /><strong>检测参数</strong><span>{{ form.modelId ? (selectedDetectionModel?.modelName || '模型 #'+form.modelId) : '自动选模型' }} · {{ Math.round(form.threshold * 100) }}%</span><AppIcon name="ArrowDown" :size="14" /></summary>
                        <div class="detection-settings">
                          <div>
                            <el-form-item label="选择模型（可选）">
                              <el-select
                                v-model="form.modelId"
                                aria-describedby="detection-model-choice-note"
                                aria-label="选择检测模型，不选则由服务端选择" placeholder="不选则由服务端选择"
                                :loading="modelsLoading" :disabled="loadingSingle"
                                :no-data-text="modelsError ? '目录读取失败，请重新读取' : modelsLoading || !modelsLoaded ? '正在核对模型目录' : '目录没有返回模型，可由服务端选择'"
                                clearable
                              >
                                <el-option
                                  v-for="model in modelList"
                                  :key="model.modelId"
                                  :value="model.modelId"
                                  :label="detectionModelOptionLabel(model)"
                                />
                              </el-select>
                            </el-form-item>
                            <p v-if="modelsError" class="detection-input-note is-warning" role="alert">{{ modelsError }}<button type="button" :disabled="modelsLoading || loadingSingle" @click="fetchModels">重新读取目录</button></p>
                            <div v-if="form.modelId" class="detection-model-selection"><AppIcon name="Tickets" :size="17" /><div><strong>{{ selectedDetectionModel?.modelName || '所选模型名称尚未核对' }}</strong><span>模型 #{{ form.modelId }} · 版本 {{ selectedDetectionModel?.version || '未记录' }}</span><span v-if="!selectedDetectionModel">本次目录未找到此编号，提交时仍需由服务端核对。</span><span v-else-if="modelsError">以上保留上次读取的目录资料。</span></div></div>
                            <p id="detection-model-choice-note" class="detection-input-note">{{ form.modelId ? '使用所选模型检测。' : '留空将自动选择模型。' }}</p>
                          </div>
                          <div>
                            <el-form-item label="置信度阈值">
                              <el-slider v-model="form.threshold" :disabled="loadingSingle" :min="0" :max="1" :step="0.01" :format-tooltip="value=>Math.round(value*100)+'%'" :format-value-text="value=>value.toFixed(2)+'，'+Math.round(value*100)+'%'" aria-label="本次检测置信度阈值，范围 0 至 1" aria-describedby="detection-threshold-note" />
                              <div class="threshold-text"><span>本次提交阈值</span><output aria-label="当前置信度阈值">{{ form.threshold.toFixed(2) }}<small>（{{ Math.round(form.threshold * 100) }}%）</small></output></div>
                              <p id="detection-threshold-note" class="detection-input-note">按模型分数筛选，仅对新提交生效。</p>
                            </el-form-item>
                          </div>
                        </div>
                      </details>
                      <el-button
                        type="primary"
                        class="wide-button secondary-action"
                        :disabled="!form.imageFile"
                        :loading="loadingSingle"
                        @click="handleSingleDetection"
                      >
                        <el-icon><VideoPlay /></el-icon>
                        开始单图检测
                      </el-button>
                    </div>

                    <section class="single-detection-result" :aria-busy="loadingSingle" aria-label="本次单图检测状态与结果">
                      <div class="single-result-heading">
                        <div>
                          <strong class="detection-card-heading"><AppIcon name="Picture" :size="17" />检测结果</strong>
                        </div>
                        <div class="single-result-tags">
                          <StatusBadge domain="singleDetection" :code="singleStageCode" />
                        </div>
                      </div>

                      <p v-if="loadingSingle && singleDetectionMessage" class="single-result-runtime" role="status">{{ singleDetectionMessage }}</p>
                      <dl v-if="singleSubmission" class="single-submission-summary"><div><dt>本次检测图片</dt><dd>{{ singleSubmission.fileName }}</dd></div><div><dt>检测模型</dt><dd>{{ singleSubmission.modelLabel }}</dd></div><div><dt>置信度阈值</dt><dd>{{ formatEvidenceConfidence(singleSubmission.threshold) }}</dd></div></dl>
                      <el-alert
                        v-if="singleStageCode === 'FAILED'"
                        type="error"
                        :closable="false"
                        show-icon
                        :title="singleDetectionMessage"
                        class="single-result-error"
                      />
                      <SingleDetectionEvidence v-if="detectionResult" :maintenance="detectionResult.modelMaintenance" :file-name="singleSubmission?.fileName || ''" :annotation-url="annotatedImageUrl" :local-preview="fileList[0]?.url || ''" :category-label="getCategoryText(detectionResult.category)" :category-tone="getCategoryType(detectionResult.category)" :confidence-label="formatConfidence(detectionResult.confidence)" />
                      <template v-else-if="fileList[0]?.url">
                        <div class="single-result-image single-result-preview">
                          <img :src="fileList[0].url" alt="待检测图片预览" />
                        </div>
                        <p v-if="singleStageCode !== 'FAILED'" class="single-result-hint">{{ loadingSingle ? '正在处理图片…' : '图片已选好，可以开始检测' }}</p>
                      </template>
                      <el-empty v-else description="请先选择图片并开始检测" :image-size="54" />
                    </section>
                  </div>
                </div>
              </div>
            </el-form>
          </el-card>

        </div>

      </el-tab-pane>

      <el-tab-pane lazy name="history" label="检测记录">
        <el-card class="detection-card history-page-card" shadow="never">
          <template #header><div class="card-title-row"><span><AppIcon name="Filter" :size="18" />筛选记录</span><el-tag type="info" effect="plain">{{ historyLoading ? '正在读取任务与结果' : historyError ? '本次读取未完成' : historyTotal!==null ? `共 ${historyTotal} 条` : historyLoaded ? '总数未提供' : '数量尚未读取' }}</el-tag><el-button size="small" :loading="historyLoading" @click="refreshHistory"><AppIcon name="Refresh" :size="15" />刷新已读范围</el-button></div></template>
          <p class="history-scope-note">
            <AppIcon name="Lock" :size="15" />
            <span v-if="historyCompletedResults">与首页一致的已完成正式任务，含部分失败。</span>
            <span v-else>{{ userStore.role==='SUPERVISOR' ? '企业业务范围' : userStore.role==='INSPECTOR' ? '本人及分派任务' : '当前账号有权访问的范围' }} · 检测结果与人工结论分别记录。</span>
            <router-link v-if="historyCompletedResults" :to="{ path: '/inspection/history', query: { ...route.query, completedResults: undefined } }">切换到全部记录</router-link>
          </p>
          <form class="history-query-form" @submit.prevent="onHistorySearch">
            <label for="history-keyword" class="history-query-keyword">任务、文件夹、工单或批次<el-input id="history-keyword" v-model="historySearchKeyword" clearable placeholder="输入编号或文件夹关键词"><template #prefix><AppIcon name="Search" :size="15" /></template></el-input></label>
            <div class="history-query-actions">
              <el-button type="primary" native-type="submit" :loading="historyLoading"><AppIcon name="Search" :size="15" />查询</el-button>
              <el-button native-type="button" :aria-expanded="historyMoreFiltersOpen" aria-controls="history-advanced-filters" @click="historyMoreFiltersOpen = !historyMoreFiltersOpen">
                <AppIcon name="Filter" :size="14" />更多筛选<span v-if="historyAdvancedCount">（{{ historyAdvancedCount }}）</span>
              </el-button>
              <el-button v-if="hasHistoryFilters" native-type="button" @click="onHistoryReset"><AppIcon name="Refresh" :size="15" />重置</el-button>
            </div>
            <div v-show="historyMoreFiltersOpen" id="history-advanced-filters" class="history-advanced-filters">
              <label for="history-collector">采集人员<el-input id="history-collector" v-model="historyFilterCollector" clearable placeholder="输入采集人员" /></label>
              <label for="history-device">设备名称<el-input id="history-device" v-model="historyFilterDevice" clearable placeholder="输入采集设备名称" /></label>
              <label for="history-region">采集区域<el-input id="history-region" v-model="historyFilterRegion" clearable placeholder="输入采集区域" /></label>
            </div>
          </form>
          <p v-if="historyLoaded" class="history-applied-query">已读取：{{ historyAppliedDescription }} · 第 {{ historyPage }} 页 · 本页 {{ historyRecords.length }} 条</p>
          <p v-if="historyFiltersDirty && historyRecords.length" class="history-filter-note" role="status">筛选已改，点击查询更新结果。</p>
          <el-alert v-if="historyError && historyRecords.length" :title="historyError+'；下方保留已读取资料，请重新核对。'" type="error" show-icon :closable="false" />
          <div v-if="historyError && historyRecords.length" class="history-retry"><el-button size="small" :loading="historyLoading" @click="retryHistoryRead"><AppIcon name="Refresh" :size="14" />重读上次查询</el-button></div>
          <CollectionEmptyState v-if="!historyRecords.length" :loading="historyLoading" :error="historyError" :filtered="historyLoaded ? Object.keys(historyAppliedFilters).length>0 : hasHistoryFilters" empty-title="暂无检测记录" empty-description="可从图片上传创建任务，或核对关键词与当前账号范围后重新查询。" @retry="retryHistoryRead" @reset="onHistoryReset" />
          <div v-else class="history-records-grid"><DetectionHistoryCard v-for="task in historyRecords" :key="task.taskId" :task="task" :latest-change="taskChanges[task.taskId]" :show-history="userStore.capabilities?.changeHistory" :cached="Array.isArray(taskStore.taskList) && taskStore.taskList.some(cached=>cached.taskId===task.taskId)" :cache-busy="historyCacheBusy" :refreshing="historyLoading" @trace="openTraceDialog" @browse-images="openImageBrowser" @refresh="refreshHistory" @remove-cache="clearHistoryTaskCache" /></div>
          <div v-if="historyTotal!==null" class="history-pagination"><el-pagination :current-page="historyPage" :page-size="historyPageSize" :total="historyTotal" :page-sizes="[10,20,50]" :disabled="historyLoading || !!historyError" layout="total, sizes, prev, pager, next, jumper" @current-change="onHistoryPageChange" @size-change="onHistorySizeChange" /></div>
        </el-card>
      </el-tab-pane>
      <el-tab-pane lazy name="work-order-trace" label="工单追溯">
        <el-card class="detection-card batch-trace-card" shadow="never">
          <template #header>
            <div class="card-title-row">
              <span><AppIcon name="Tickets" :size="18" />工单追溯</span>
              <el-button
                v-if="workOrderTraceReport"
                size="small"
                type="primary"
                plain
                :disabled="workOrderTraceLoading || !!workOrderTraceError"
                title="导出工单汇总与当前页明细（JSON）"
                @click="downloadWorkOrderTraceReport"
              >
                <el-icon><Download /></el-icon>
                导出汇总和当前页
              </el-button>
            </div>
          </template>

          <BusinessTraceQuery v-model="workOrderTraceNo" kind="work-order" :requested-no="workOrderTraceRequestedNo" :requested-page="workOrderTraceRequestedPage" :loading="workOrderTraceLoading" :report="workOrderTraceReport" :error="workOrderTraceError" :references="businessWorkOrderNos" :reference-loading="traceReferencesLoading" :reference-error="traceReferencesError" :scope-label="businessTraceScope" @query="loadWorkOrderTraceReport" @refresh="refreshWorkOrderTraceReport" @retry="retryWorkOrderTraceReport" @reference="loadBusinessWorkOrderTrace" @refresh-references="loadTraceReferences" />

          <TraceReportOverview v-if="workOrderTraceReport" :report="workOrderTraceReport" kind="work-order" :page-sizes="tracePageSizes" :report-downloading="reportDownloading" :loading="workOrderTraceLoading" @open-trace="openTraceDialog" @download-task="downloadTaskQualityReport" @page-change="changeWorkOrderTracePage" @size-change="changeWorkOrderTraceSize" />
        </el-card>
      </el-tab-pane>

      <el-tab-pane lazy name="batch-trace" label="批次追溯">
        <el-card class="detection-card batch-trace-card" shadow="never">
          <template #header>
            <div class="card-title-row">
              <span><AppIcon name="Collection" :size="18" />批次追溯</span>
              <el-button
                v-if="batchTraceReport"
                size="small"
                type="primary"
                plain
                :disabled="batchTraceLoading || !!batchTraceError"
                title="导出批次汇总与当前页明细（JSON）"
                @click="downloadBatchTraceReport"
              >
                <el-icon><Download /></el-icon>
                导出汇总和当前页
              </el-button>
            </div>
          </template>

          <BusinessTraceQuery v-model="batchTraceNo" kind="batch" :requested-no="batchTraceRequestedNo" :requested-page="batchTraceRequestedPage" :loading="batchTraceLoading" :report="batchTraceReport" :error="batchTraceError" :references="businessBatchNos" :reference-loading="traceReferencesLoading" :reference-error="traceReferencesError" :scope-label="businessTraceScope" @query="loadBatchTraceReport" @refresh="refreshBatchTraceReport" @retry="retryBatchTraceReport" @reference="loadBusinessBatchTrace" @refresh-references="loadTraceReferences" />

          <TraceReportOverview v-if="batchTraceReport" :report="batchTraceReport" kind="batch" :page-sizes="tracePageSizes" :report-downloading="reportDownloading" :loading="batchTraceLoading" @open-trace="openTraceDialog" @download-task="downloadTaskQualityReport" @page-change="changeBatchTracePage" @size-change="changeBatchTraceSize" />
        </el-card>
      </el-tab-pane>
    </el-tabs>
    </template>
    <el-dialog v-if="boardRequest && openingBoardDialog" :model-value="true" append-to-body title="读取任务" width="min(420px, 95vw)" @update:model-value="emit('dismiss')">
      <p :role="boardReadError ? 'alert' : 'status'">{{ boardReadError || '正在读取所选任务…' }}</p>
      <template #footer>
        <el-button @click="emit('dismiss')">返回列表</el-button>
        <el-button v-if="boardReadError" type="primary" @click="openBoardRequest">重新读取</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="reviewDialogVisible" :top="boardRequest ? '4dvh' : undefined" :append-to-body="!!boardRequest" class="quality-operation-dialog" :class="{ 'board-calibration-dialog': boardRequest }" :title="boardRequest ? '核对模型结果' : '人工复核'" width="min(1100px, 96vw)" :close-on-click-modal="!reviewSubmitting" :close-on-press-escape="!reviewSubmitting" :show-close="!reviewSubmitting">
      <QualityTaskContext :compact="!!boardRequest" :task="reviewTask" operation="review" />
      <div class="quality-review-layout" :class="{ 'has-evidence': reviewImages && (reviewImages.originals.length || reviewImages.annotations.length) }">
      <div v-if="reviewImages" :class="{'board-review-evidence':boardRequest}"><ModelMaintenanceSummary :summary="reviewImages.maintenance" />
      <EvidenceComparison edit-annotations :compact-compare="!!boardRequest" :task-id="reviewTask?.taskId" :maintenance="reviewImages.maintenance" :defects="reviewImages.defects" :originals="reviewImages.originals" :annotations="reviewImages.annotations" /></div>
      <div v-else class="quality-feedback-note" role="status"><AppIcon name="Picture" :size="16" />{{ reviewImageError || '正在读取本次任务的原图与标注图…' }}
        <el-button v-if="reviewImageError" link type="primary" @click="reviewImageAttempt++">重新读取图片</el-button>
      </div>
      <el-form :model="reviewForm" label-position="top" :class="{ 'board-calibration-form': boardRequest }" :disabled="reviewSubmitting||qualityActionAcknowledged.review||reviewTask?.mutationConflicted">
        <el-form-item label="复核结论">
          <el-select v-model="reviewForm.reviewConclusion" placeholder="请选择复核结论" style="width: 100%">
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
        <el-form-item class="calibration-notes" label="复核备注">
          <el-input
            v-model="reviewForm.reviewRemark"
            type="textarea"
            :rows="3"
            maxlength="300"
            show-word-limit
            aria-label="记录缺陷位置、人工判断依据或误报原因" placeholder="记录缺陷位置、人工判断依据或误报原因"
          />
        </el-form-item>
      </el-form>
      </div>
      <el-alert v-if="qualityActionErrors.review" :title="qualityActionErrors.review" type="warning" show-icon :closable="false" />
      <p v-if="!canReviewTask(reviewTask)" class="quality-feedback-note">{{ qualityActionReason(reviewTask,'REVIEW') }}</p>
      <template #footer>
        <el-button :disabled="reviewSubmitting||reviewTask?.mutationConflicted" @click="reviewDialogVisible = false"><AppIcon name="Close" :size="16" />取消</el-button>
        <el-button :disabled="reviewSubmitting||!reviewTask?.taskId" @click="openTraceDialog(reviewTask.taskId)"><AppIcon name="Search" :size="15" />核对任务依据</el-button>
        <el-button type="primary" :loading="reviewSubmitting" :disabled="!reviewForm.reviewConclusion||qualityActionAcknowledged.review||reviewTask?.mutationConflicted||!canReviewTask(reviewTask)" @click="submitTaskReview"><AppIcon name="DocumentChecked" :size="15" />提交复核</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="assignmentDialogVisible" :top="boardRequest ? '4dvh' : undefined" :append-to-body="!!boardRequest" class="quality-operation-dialog" :class="{ 'board-calibration-dialog': boardRequest }" :title="boardRequest ? (assignmentTask?.assignee ? '改派校验任务' : '分派校验任务') : '分派质检任务'" width="min(640px, 96vw)" :close-on-click-modal="!assignmentSubmitting" :close-on-press-escape="!assignmentSubmitting" :show-close="!assignmentSubmitting">
      <QualityTaskContext :compact="!!boardRequest" :task="assignmentTask" operation="assignment" />
      <el-form :model="assignmentForm" label-position="top" :disabled="assignmentSubmitting||qualityActionAcknowledged.assignment||assignmentTask?.mutationConflicted">
        <el-form-item label="质检站点">
          <el-input v-model="assignmentForm.qualityStation" aria-label="例如：质检站-1 / 产线A复核位" placeholder="例如：质检站-1 / 产线A复核位" />
        </el-form-item>
        <el-form-item label="责任人">
          <QualityAssigneePicker v-model="assignmentForm.assignee" v-model:user-id="assignmentForm.assigneeUserId" v-model:revision="assignmentForm.assigneeRevision" :disabled="assignmentSubmitting||qualityActionAcknowledged.assignment||assignmentTask?.mutationConflicted" />
        </el-form-item>
        <el-form-item label="截止时间">
          <el-date-picker
            v-model="assignmentForm.dueAt"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            format="YYYY-MM-DD HH:mm"
            aria-label="选择质检截止时间" placeholder="选择质检截止时间"
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
            aria-label="补充复核重点、缺陷疑点或产线要求" placeholder="补充复核重点、缺陷疑点或产线要求"
          />
        </el-form-item>
      </el-form>
      <el-alert v-if="qualityActionErrors.assignment" :title="qualityActionErrors.assignment" type="warning" show-icon :closable="false" />
      <p v-if="!canAssignQualityTask(assignmentTask)" class="quality-feedback-note">{{ qualityActionReason(assignmentTask,'ASSIGN') }}</p>
      <template #footer>
        <el-button :disabled="assignmentSubmitting||assignmentTask?.mutationConflicted" @click="assignmentDialogVisible = false"><AppIcon name="Close" :size="16" />取消</el-button>
        <el-button v-if="qualityActionErrors.assignment" :disabled="assignmentSubmitting||assignmentTask?.mutationConflicted" @click="openTraceDialog(assignmentTask.taskId)"><AppIcon name="Search" :size="15" />核对任务状态</el-button>
        <el-button type="primary" :loading="assignmentSubmitting" :disabled="qualityActionAcknowledged.assignment||assignmentTask?.mutationConflicted||!canAssignQualityTask(assignmentTask)" @click="submitQualityAssignment"><AppIcon name="User" :size="15" />确认分派</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dispositionDialogVisible" class="quality-operation-dialog" title="质检处置" width="min(640px, 96vw)" :close-on-click-modal="!dispositionSubmitting" :close-on-press-escape="!dispositionSubmitting" :show-close="!dispositionSubmitting">
      <QualityTaskContext :task="dispositionTask" operation="disposition" />
      <el-form :model="dispositionForm" label-position="top" :disabled="dispositionSubmitting||qualityActionAcknowledged.disposition||dispositionTask?.mutationConflicted">
        <el-form-item label="处置动作">
          <el-select v-model="dispositionForm.dispositionAction" style="width: 100%">
            <el-option label="正常放行" value="RELEASE" :disabled="!canReleaseDisposition(dispositionTask)" />
            <el-option label="返工处理" value="REWORK" />
            <el-option label="安排复检" value="RECHECK" />
            <el-option label="暂挂观察" value="HOLD" :disabled="dispositionTask?.dispositionAction === 'HOLD'" />
            <el-option label="报废隔离" value="SCRAP" />
          </el-select>
        </el-form-item>
        <el-form-item label="需要复检">
          <el-switch v-model="dispositionForm.recheckRequired" :disabled="['RELEASE', 'SCRAP', 'RECHECK'].includes(dispositionForm.dispositionAction)" /><span v-if="dispositionForm.dispositionAction === 'REWORK'" class="quality-flow-hint">先回填返工结果，再进入复检</span>
        </el-form-item>
        <el-form-item label="处置备注">
          <el-input
            v-model="dispositionForm.dispositionRemark"
            type="textarea"
            :rows="3"
            maxlength="1000"
            show-word-limit
            aria-label="记录处置依据、返工要求或隔离说明" placeholder="记录处置依据、返工要求或隔离说明"
          />
        </el-form-item>
      </el-form>
      <p v-if="!canReleaseDisposition(dispositionTask)" class="quality-feedback-note"><AppIcon name="Lock" :size="15" />当前条件不允许直接放行，请核对复核结论及复检要求，并选择其他可用处置。</p>
      <p v-if="dispositionForm.dispositionAction==='SCRAP'" class="quality-danger-note"><AppIcon name="Warning" :size="15" />本次将记录报废隔离处置，提交前请再次核对任务对象与隔离说明。</p>
      <el-alert v-if="qualityActionErrors.disposition" :title="qualityActionErrors.disposition" type="warning" show-icon :closable="false" />
      <p v-if="!canDisposeTask(dispositionTask)" class="quality-feedback-note">{{ qualityActionReason(dispositionTask,'DISPOSE') }}</p>
      <template #footer>
        <el-button :disabled="dispositionSubmitting||dispositionTask?.mutationConflicted" @click="dispositionDialogVisible = false"><AppIcon name="Close" :size="16" />取消</el-button>
        <el-button v-if="qualityActionErrors.disposition" :disabled="dispositionSubmitting||dispositionTask?.mutationConflicted" @click="openTraceDialog(dispositionTask.taskId)"><AppIcon name="Search" :size="15" />核对任务状态</el-button>
        <el-button :type="dispositionForm.dispositionAction==='SCRAP'?'danger':'primary'" :loading="dispositionSubmitting" :disabled="qualityActionAcknowledged.disposition||dispositionTask?.mutationConflicted||!canDisposeTask(dispositionTask)" @click="submitTaskDisposition"><AppIcon name="DocumentChecked" :size="15" />{{ dispositionForm.dispositionAction==='SCRAP'?'确认报废隔离':dispositionForm.dispositionAction==='RELEASE'?'确认正常放行':'提交处置' }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="reworkDialogVisible" class="quality-operation-dialog" title="返工结果回填" width="min(640px, 96vw)" :close-on-click-modal="!reworkSubmitting" :close-on-press-escape="!reworkSubmitting" :show-close="!reworkSubmitting">
      <QualityTaskContext :task="reworkTask" operation="rework" />
      <el-form :model="reworkForm" label-position="top" :disabled="reworkSubmitting||qualityActionAcknowledged.rework||reworkTask?.mutationConflicted">
        <el-form-item label="返工结果">
          <el-input
            v-model="reworkForm.reworkResult"
            type="textarea"
            :rows="3"
            aria-label="例如：已更换门把手锁扣并完成表面清理" placeholder="例如：已更换门把手锁扣并完成表面清理"
          />
        </el-form-item>
        <el-form-item label="返工人员">
          <el-input model-value="按当前登录账号记录" disabled />
        </el-form-item>
        <el-form-item label="需要复检">
          <el-switch v-model="reworkForm.recheckRequired" :disabled="(reworkTask?.recheckRequired ?? reworkTask?.result?.recheckRequired) === true" /><span v-if="(reworkTask?.recheckRequired ?? reworkTask?.result?.recheckRequired) === true" class="quality-flow-hint">原处置要求复检，回填后仍需实际检测</span>
        </el-form-item>
        <el-form-item label="返工备注">
          <el-input
            v-model="reworkForm.reworkRemark"
            type="textarea"
            :rows="3"
            aria-label="补充返工证据、复检要求或异常说明" placeholder="补充返工证据、复检要求或异常说明"
          />
        </el-form-item>
      </el-form>
      <el-alert v-if="qualityActionErrors.rework" :title="qualityActionErrors.rework" type="warning" show-icon :closable="false" />
      <p v-if="!canSubmitReworkResult(reworkTask)" class="quality-feedback-note">{{ qualityActionReason(reworkTask,'SUBMIT_REWORK') }}</p>
      <template #footer>
        <el-button :disabled="reworkSubmitting||reworkTask?.mutationConflicted" @click="reworkDialogVisible = false"><AppIcon name="Close" :size="16" />取消</el-button>
        <el-button v-if="qualityActionErrors.rework" :disabled="reworkSubmitting||reworkTask?.mutationConflicted" @click="openTraceDialog(reworkTask.taskId)"><AppIcon name="Search" :size="15" />核对任务状态</el-button>
        <el-button type="primary" :loading="reworkSubmitting" :disabled="qualityActionAcknowledged.rework||reworkTask?.mutationConflicted||!canSubmitReworkResult(reworkTask)" @click="submitTaskRework"><AppIcon name="DocumentChecked" :size="15" />提交返工结果</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="traceDialogVisible" class="task-trace-dialog" :title="browsingImages ? '浏览任务图片' : '任务追溯详情'" @opened="imageBrowser?.focusNavigation()" width="min(1100px, 96vw)" append-to-body>
      <template v-if="browsingImages">
        <CollectionEmptyState v-if="!traceDetail" :loading="traceLoading" :error="traceError" empty-title="尚未读取图片清单" @retry="refreshTrace" />
        <template v-else-if="traceDialogVisible">
          <p class="browser-task-id">任务 {{ traceDetail.taskId }}</p>
          <el-alert v-if="traceError" :title="traceError" type="warning" :closable="false" />
          <EvidenceComparison ref="imageBrowser" :maintenance="traceDetail.modelMaintenance" :defects="traceDetail.defectEvidence" :task-id="traceDetail.taskId" :originals="traceDetail.originalImages || []"
                              :annotations="traceDetail.previewImages || []" :initial-annotation-url="initialAnnotationUrl" />
        </template>
      </template>
      <TaskTracePanel v-else ref="tracePanel" :detail="traceDetail" :loading="traceLoading" :error="traceError" @refresh="refreshTrace" />
      <template #footer><div class="task-trace-footer"><span role="status">{{ traceLoading ? traceDetail ? '正在重新读取，保留上次资料' : '正在读取任务资料' : traceError ? traceDetail ? '读取未成功，仍为上次资料' : '任务详情尚未读取成功' : traceDetail ? '本次已读任务资料' : '尚未读取' }}</span><div><el-button v-if="traceDetail && !browsingImages" text @click="tracePanel?.showOverview()">回到概览</el-button><el-button :loading="traceLoading" :disabled="!traceRequestedId || reportDownloading" @click="refreshTrace"><AppIcon name="Refresh" :size="15" />重新读取</el-button><el-button @click="traceDialogVisible = false">关闭</el-button><el-button v-if="traceDetail?.taskId && !browsingImages" type="primary" :loading="reportDownloading" :disabled="traceLoading" @click="downloadTaskQualityReport(traceDetail.taskId)"><AppIcon name="Download" :size="15" />导出任务摘要</el-button></div></div></template>
    </el-dialog>
  </div>
</template>

<script setup>
import OssPreviewFailure from '@/components/OssPreviewFailure.vue'
import CollaborationRefreshNotice from '../components/CollaborationRefreshNotice.vue'
import { useResourceChanges } from '../composables/useResourceChanges'
import { useLatestChanges } from '../composables/useLatestChanges'
import { resourceHistoryLink } from '../utils/changeHistory'
import {captureAccountRequest} from '@/api/request'
import { accountSession } from '../utils/accountContext'
import ModelMaintenanceSummary from '@/components/ModelMaintenanceSummary.vue'
import QualityAssigneePicker from '@/components/QualityAssigneePicker.vue'
import QualityTaskContext from '@/components/QualityTaskContext.vue'
import EvidenceComparison from '@/components/EvidenceComparison.vue'
import TraceReportOverview from '@/components/TraceReportOverview.vue'
import BusinessTraceQuery from '@/components/BusinessTraceQuery.vue'
import DetectionHistoryCard from '@/components/DetectionHistoryCard.vue'
import { useUserStore } from '../stores/user'
import { beijingDateTime as formatBusinessTime } from '../utils/beijingTime'
import { detectionPresentation } from '../utils/pagePresentation'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Refresh, VideoPlay } from '@element-plus/icons-vue'
import { fetchDetectionTaskTrace } from '../api/detection'
import { fetchSingleImageModels, previewSingleImage } from '../services/singleImagePreview'
import { useTaskStore, usePollingStore, CATEGORY_LABELS, CATEGORY_COLORS, CATEGORY_ALIASES } from '../stores/detectionTask'
import { useSingleImageUploadPreview } from '../composables/useSingleImageUploadPreview'
import {
  canAssignQualityTask as stateCanAssignQualityTask,
  canDisposeTask,
  canReleaseDisposition,
  canReviewTask,
  canSubmitReworkResult,
  qualityActionReason,
  dispositionActionText,
  dispositionStatusText,
  reviewConclusionText
} from '../utils/qualityWorkflow'
import { formatEvidenceConfidence } from '../utils/qualityRecords'
import { useQualityTaskActions } from '../composables/useQualityTaskActions'
import { useTraceReports } from '../composables/useTraceReports'
import { useDetectionHistory } from '../composables/useDetectionHistory'
import { useQualityReportDownloads } from '../composables/useQualityReportDownloads'
import CollectionEmptyState from '../components/CollectionEmptyState.vue'
import TaskTracePanel from '../components/TaskTracePanel.vue'
import SingleModelComparison from '../components/SingleModelComparison.vue'
import SingleDetectionEvidence from '../components/SingleDetectionEvidence.vue'
import '@/assets/task-trace-dialog.css'

const props=defineProps({boardRequest:Object})
const emit=defineEmits(['dismiss'])
const userStore = useUserStore()
const singleMode = ref('compare')
const comparisonBusy = ref(false)
const comparisonScope = computed(() => JSON.stringify([userStore.identity?.userId, userStore.username, userStore.role, userStore.isAuthenticated]))
watch(comparisonScope, () => { comparisonBusy.value=false })
const businessTraceScope = computed(() => userStore.role === 'SUPERVISOR' ? '企业业务范围' : userStore.role === 'INSPECTOR' ? '本人及分派任务' : '当前账号有权查看的业务范围')
const taskStore = useTaskStore()
const pollingStore = usePollingStore()
const {
  removeTask, saveTaskList
} = taskStore
const { restoreFromSession, fetchTaskResults } = pollingStore
const {
  workOrderTraceNo,
  workOrderTraceLoading,
  workOrderTraceReport,
  workOrderTraceError,
  batchTraceNo,
  batchTraceLoading,
  batchTraceReport,
  batchTraceError,
  businessWorkOrderNos,
  businessBatchNos,
  traceReferencesLoading,
  traceReferencesError,
  loadTraceReferences,
  ensureDefaultWorkOrderNo,
  ensureDefaultBatchNo,
  loadWorkOrderTraceReport,
  loadBatchTraceReport,
  refreshWorkOrderTraceReport,
  workOrderTraceRequestedNo,
  workOrderTraceRequestedPage,
  retryWorkOrderTraceReport,
  changeWorkOrderTracePage,
  changeWorkOrderTraceSize,
  refreshBatchTraceReport,
  batchTraceRequestedNo,
  batchTraceRequestedPage,
  retryBatchTraceReport,
  changeBatchTracePage,
  changeBatchTraceSize,
  tracePageSizes,
  loadBusinessWorkOrderTrace,
  loadBusinessBatchTrace,
  forgetTasks:forgetTraceTasks
} = useTraceReports({ getAccountScope: () => [userStore.identity?.userId || userStore.username || '', userStore.role, userStore.isAuthenticated] })
const {
  historySearchKeyword,
  historyFilterCollector,
  historyFilterDevice,
  historyFilterRegion,
  historyCompletedResults,
  historyPage,
  historyPageSize,
  historyTotal,
  historyRecords,
  historyLoading,
  historyError,
  historyLoaded,
  historyFiltersDirty,
  historyAppliedFilters,
  hasHistoryFilters,
  fetchHistoryWithFilters,
  onHistorySearch,
  onHistoryReset,
  readHistoryFromRoute,
  onHistoryPageChange,
  onHistorySizeChange,
  refreshHistory,
  retryHistoryRead,
  forgetTasks:forgetHistoryTasks
} = useDetectionHistory(taskStore, pollingStore)
const historyAppliedDescription = computed(() => Object.entries(historyAppliedFilters.value).map(([key,value]) => `${({keyword:'关键词',collector:'采集人员',deviceName:'设备名称',region:'采集区域'})[key] || key}：${value}`).join(' · ') || '全部条件')
const historyMoreFiltersOpen = ref(false)
const historyAdvancedKeys = ['collector', 'deviceName', 'region']
const historyAdvancedCount = computed(() => historyAdvancedKeys.filter(key => historyAppliedFilters.value[key]).length)
watch(historyAdvancedKeys.map(key => () => historyAppliedFilters.value[key]), () => {
  if (historyAdvancedCount.value) historyMoreFiltersOpen.value = true
})
const historyCacheBusy = ref(false)
async function clearHistoryTaskCache(taskId) {
  if (historyCacheBusy.value || !taskId) return
  if (!Array.isArray(taskStore.taskList) || !taskStore.taskList.some(task => task.taskId === taskId)) return ElMessage.info('此任务当前没有本机任务缓存')
  const scope=JSON.stringify([userStore.identity?.userId || userStore.username || '',userStore.role,userStore.isAuthenticated])
  historyCacheBusy.value = true
  try {
    await ElMessageBox.confirm(`清除任务 ${taskId} 的本机缓存？后端记录继续保留，服务器检测不会被取消；重新查询可能再次缓存。`,'清除本机任务缓存',{type:'warning',confirmButtonText:'清除本机缓存',cancelButtonText:'保留缓存'})
    if (!detectionPageActive || scope!==JSON.stringify([userStore.identity?.userId || userStore.username || '',userStore.role,userStore.isAuthenticated])) return
    if (!taskStore.taskList.some(task=>task.taskId===taskId)) return ElMessage.info('此任务已不在当前本机缓存中，请重新读取核对')
    removeTask(taskId)
    ElMessage.success('已从本机任务缓存列表移出，后端记录保留')
  } catch (error) {
    if (detectionPageActive && !['cancel','close'].includes(error)) ElMessage.error('本机缓存清理未完成，请重新核对')
  } finally { historyCacheBusy.value = false }
}
const {
  reportDownloading,
  downloadTaskQualityReport,
  downloadBatchTraceReport,
  downloadWorkOrderTraceReport
} = useQualityReportDownloads({
  batchTraceNo,
  batchTraceReport,
  workOrderTraceNo,
  workOrderTraceReport,
  getAccountScope: () => [userStore.identity?.userId || userStore.username || '', userStore.role, userStore.isAuthenticated]
})

// ==================== 组件本地状态（UI 相关） ====================

const fileList = ref([])
const modelList = ref([])
const modelsLoading = ref(false), modelsLoaded = ref(false), modelsError = ref('')
let modelReadVersion = 0, singleRunVersion = 0, detectionPageActive = true
const detectionResult = ref(null)
const annotatedImageUrl = ref('')
const loadingSingle = ref(false)
let singleRequest
const singleDetectionStage = ref('IDLE')
const singleDetectionMessage = ref('')
const singleSubmission = ref(null)
const singleStageCode = computed(() => singleDetectionStage.value === 'IDLE' && form.imageFile ? 'READY' : String(singleDetectionStage.value || 'IDLE').toUpperCase())
const traceDialogVisible = ref(false)
const browsingImages = ref(false), initialAnnotationUrl = ref(''), imageBrowser = ref(null)
const traceLoading = ref(false)
const traceDetail = ref(null)
const traceError = ref(''), traceRequestedId = ref(''), tracePanel = ref(null)
let traceGeneration = 0, traceReadController
watch(traceDialogVisible, open => { if (!open) { traceGeneration++; traceReadController?.abort(); traceReadController = null; traceLoading.value = false } }, { flush:'sync' })
const displayBusinessTime = value => value ? formatBusinessTime(value) || '时间格式未知' : '未记录'
const route = useRoute()
watch(() => JSON.stringify([userStore.identity?.userId || userStore.username || '', userStore.role, userStore.isAuthenticated]), () => { traceGeneration++; traceReadController?.abort(); traceReadController = null; traceDetail.value = null; traceRequestedId.value = ''; traceError.value = ''; traceLoading.value = false; traceDialogVisible.value = false }, { flush: 'sync' })
const router = useRouter()
const activeTab = ref(route.query.keyword ? 'history' : route.meta.detectionTab || 'workspace')
const workspacePresentation = computed(() => detectionPresentation[activeTab.value] || detectionPresentation.workspace)
const validTabs = ['workspace', 'history', 'work-order-trace', 'batch-trace']
const tabRouteMap = {
  workspace: '/inspection/workbench',
  history: '/inspection/history',
  'work-order-trace': '/quality/work-order-trace',
  'batch-trace': '/quality/batch-trace'
}
const form = reactive({
  modelId: null,
  threshold: 0.5,
  imageFile: null
})
const selectedDetectionModel = computed(()=>modelList.value.find(model=>model.modelId===form.modelId))

const handleTabChange = async (tabName, { fromRoute = false } = {}) => {
  const startingRoute = route.fullPath
  if (tabName === 'workspace' && !modelsLoaded.value && !modelsLoading.value) fetchModels()
  if (tabName === 'history' && !historyLoaded.value && !historyLoading.value) fetchHistoryWithFilters(1)
  if (tabName === 'work-order-trace' && !workOrderTraceReport.value && !workOrderTraceLoading.value) {
    if (await ensureDefaultWorkOrderNo()) await loadWorkOrderTraceReport()
  }
  if (tabName === 'batch-trace' && !batchTraceReport.value && !batchTraceLoading.value) {
    if (await ensureDefaultBatchNo()) await loadBatchTraceReport()
  }
  const targetPath = tabRouteMap[tabName]
  if (!fromRoute && targetPath && route.path !== targetPath && route.fullPath === startingRoute) {
    const { tab, ...query } = route.query
    if (tabName !== 'history') {
      delete query.keyword
      delete query.completedResults
    }
    if (tabName !== 'work-order-trace') delete query.workOrderNo
    if (tabName !== 'batch-trace') delete query.batchNo
    router.replace({ path: targetPath, query })
  }
}

const syncTabFromRoute = async () => {
  const text = value => typeof value === 'string' ? value.trim() : ''
  const routeKeyword = text(route.query.keyword)
  const completedResults = route.query.completedResults === '1'
  const configuredTab = String(route.query.tab || route.meta?.detectionTab || '')
  if (!validTabs.includes(configuredTab) && route.path !== '/detection') return
  const routeTab = routeKeyword ? 'history' : configuredTab
  if (!validTabs.includes(routeTab)) return
  const changed = activeTab.value !== routeTab
  activeTab.value = routeTab
  if (routeTab === 'work-order-trace' && text(route.query.workOrderNo)) {
    const requested = text(route.query.workOrderNo)
    workOrderTraceNo.value = requested
    if (workOrderTraceReport.value?.workOrderNo !== requested) await loadWorkOrderTraceReport()
    return
  }
  if (routeTab === 'batch-trace' && text(route.query.batchNo)) {
    const requested = text(route.query.batchNo)
    batchTraceNo.value = requested
    if (batchTraceReport.value?.batchNo !== requested) await loadBatchTraceReport()
    return
  }
  if (routeTab === 'history') {
    const historyRead = readHistoryFromRoute(routeKeyword, completedResults)
    if (historyRead) {
      await historyRead
      return
    }
  }
  if (changed) await handleTabChange(routeTab, { fromRoute:true })
}

watch(
  () => [route.path, route.query.tab, route.query.workOrderNo, route.query.batchNo, route.query.keyword, route.query.completedResults],
  syncTabFromRoute
)

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
  annotatedImageUrl,
  isLocked: () => loadingSingle.value,
  onReset: () => {
    singleDetectionStage.value = 'IDLE'
    singleDetectionMessage.value = ''
    singleSubmission.value = null
  }
})

watch(() => JSON.stringify([userStore.identity?.userId || userStore.username || '', userStore.role, userStore.isAuthenticated]), () => {
  singleRunVersion++
  singleRequest?.abort()
  singleRequest = undefined
  loadingSingle.value = false
  handleRemove()
  form.modelId = null
  modelReadVersion++
  modelList.value = []
  modelsLoading.value = false
  modelsLoaded.value = false
  modelsError.value = '账号或权限已变化，请重新读取模型目录'
  singleDetectionMessage.value = ''
}, { flush:'sync' })

const handleSingleDetection = async () => {
  if (loadingSingle.value) return
  if (!form.imageFile) {
    ElMessage.error('请先选择图片')
    return
  }

  loadingSingle.value = true
  const runVersion = ++singleRunVersion
  const controller = new AbortController()
  singleRequest = controller
  const file = form.imageFile, modelId = form.modelId, threshold = form.threshold
  const model = modelList.value.find(row => row.modelId === modelId)
  singleSubmission.value = {fileName:file.name,threshold,modelLabel:modelId ? `${model?.modelName || '模型'} · #${modelId}${model?.version ? ' · '+model.version : ''}` : '自动选择模型'}
  detectionResult.value = null
  annotatedImageUrl.value = ''
  singleDetectionStage.value = 'DETECTING'
  singleDetectionMessage.value = '正在处理图片'

  try {
    const result = await previewSingleImage({ file, modelId, threshold, signal: controller.signal })
    if (!detectionPageActive || runVersion !== singleRunVersion) return
    detectionResult.value = result
    annotatedImageUrl.value = result.annotatedImagePath
    singleSubmission.value.modelLabel = `${result.modelName} · #${result.modelId} · ${result.version}`
    singleDetectionStage.value = 'COMPLETED'
    singleDetectionMessage.value = ''
  } catch (error) {
    if (!detectionPageActive || runVersion !== singleRunVersion) return
    singleDetectionStage.value = 'FAILED'
    singleDetectionMessage.value = error.message || '单图检测失败，请重试'
  } finally {
    if (singleRequest === controller) singleRequest = undefined
    if (detectionPageActive && runVersion === singleRunVersion) loadingSingle.value = false
  }
}

// ==================== 工具函数 ====================

const formatConfidence = (confidence) => {
  if (!['number','string'].includes(typeof confidence) || typeof confidence === 'string' && !confidence.trim()) return '—'
  const value = Number(confidence)
  return Number.isFinite(value) && value >= 0 && value <= 1 ? `${(value * 100).toFixed(2)}%` : '—'
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
  if (!detectionPageActive || modelsLoading.value) return
  const readVersion = ++modelReadVersion
  modelsLoading.value = true
  modelsError.value = ''
  try {
    const response = await fetchSingleImageModels()
    if (!detectionPageActive || readVersion !== modelReadVersion) return
    const rows = response.data?.data
    if (response.data?.code !== 200 || !Array.isArray(rows) || rows.some(row => !Number.isSafeInteger(row?.modelId) || row.modelId < 1)) throw new Error('模型目录返回内容不完整')
    modelList.value = rows
    modelsLoaded.value = true
  } catch (error) {
    if (!detectionPageActive || readVersion !== modelReadVersion) return
    if ([401,403].includes(error.response?.status)) { modelList.value = []; modelsLoaded.value = false }
    modelsError.value = '模型目录暂不可读取；留空可自动选择模型。'
  } finally { if (detectionPageActive && readVersion === modelReadVersion) modelsLoading.value = false }
}
const detectionModelOptionLabel = model => `${model.modelName || '未命名模型'}${model.version ? ' · '+model.version : ''} · #${model.modelId}`

// ==================== 生命周期 ====================

// All quality entry points share state guards and mutation feedback.
const {
  qualityActionErrors, qualityActionAcknowledged,
  reviewDialogVisible, reviewSubmitting, reviewTask, reviewForm,
  assignmentDialogVisible, assignmentSubmitting, assignmentTask, assignmentForm,
  dispositionDialogVisible, dispositionSubmitting, dispositionTask, dispositionForm,
  reworkDialogVisible, reworkSubmitting, reworkTask, reworkForm,
  openReviewDialog, submitTaskReview, openAssignmentDialog, submitQualityAssignment,
  openDispositionDialog, submitTaskDisposition, openReworkDialog, submitTaskRework
} = useQualityTaskActions({
  taskStore,
  fetchTaskResults,
})

function traceData(response,taskId) {
  const detail = response.data?.data
  return response.data?.code===200 && detail?.taskId===taskId &&
    ['timeline','originalImages','previewImages'].every(key=>detail[key]==null || Array.isArray(detail[key])) ? detail : null
}

const reviewImages=ref(null), reviewImageError=ref(''), reviewImageAttempt=ref(0)
watch([()=>reviewDialogVisible.value ? reviewTask.value?.taskId : null, ()=>userStore.accountContext, reviewImageAttempt],
  async ([taskId],previous,onCleanup) => {
    reviewImages.value=null
    reviewImageError.value=''
    if(!taskId)return
    const controller=new AbortController(), owner=accountSession.stamp()
    onCleanup(()=>controller.abort())
    try{
      const response=await fetchDetectionTaskTrace(taskId,{signal:controller.signal})
      if(controller.signal.aborted || !accountSession.current(owner))return
      const detail=traceData(response,taskId)
      if(!detail)throw Error('图片清单读取失败')
      const annotations=detail.previewImages || []
      const originals=detail.originalImages?.length ? detail.originalImages : annotations
        .filter(image=>image && typeof image.originalUrl==='string' && image.originalUrl)
        .map(image=>({imageName:image.imageName,objectKey:image.originalKey,previewUrl:image.originalUrl}))
      reviewImages.value={originals,annotations,maintenance:detail.modelMaintenance,defects:detail.defectEvidence}
    }catch{
      if(!controller.signal.aborted && accountSession.current(owner))reviewImageError.value='未能读取本次任务的图片。'
    }
  }, {flush:'sync'})

function openTraceDialog(taskId) {
  browsingImages.value = false
  return readTrace(taskId)
}
function openImageBrowser(taskId, annotationUrl = '') {
  browsingImages.value = true
  initialAnnotationUrl.value = annotationUrl
  return readTrace(taskId)
}
const refreshTrace = () => readTrace(traceRequestedId.value)
const readTrace = async (taskId) => {
  if (typeof taskId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(taskId)) return
  const generation = ++traceGeneration, sameTask = traceDialogVisible.value && traceDetail.value?.taskId === taskId
  traceReadController?.abort()
  const controller = new AbortController(); traceReadController = controller
  traceRequestedId.value = taskId; traceError.value = ''; traceDialogVisible.value = true; traceLoading.value = true
  if (!sameTask) traceDetail.value = null
  try {
    const response = await fetchDetectionTaskTrace(taskId, { signal: controller.signal })
    if (generation !== traceGeneration) return
    const detail = traceData(response,taskId)
    if (detail) {
      traceDetail.value = detail
      if (!sameTask) {
        await nextTick()
        if (generation === traceGeneration) {
          if (browsingImages.value) imageBrowser.value?.focusNavigation()
          else tracePanel.value?.resetScroll()
        }
      }
    } else {
      if ([401, 403, 404].includes(response.data?.code)) traceDetail.value = null
      traceError.value = response.data?.code === 200 ? '任务详情返回内容不完整或编号不匹配，请重新读取' : response.data?.message || '获取追溯详情失败'
    }
  } catch (failure) {
    if (generation !== traceGeneration || controller.signal.aborted) return
    if ([401, 403, 404].includes(failure.response?.status)) traceDetail.value = null
    traceError.value = failure.response?.data?.message || '任务资料暂不可读取，请重新核对服务与访问权限'
  } finally {
    if (generation === traceGeneration) { traceReadController = null; traceLoading.value = false }
  }
}

// Board dialogs use the same forms, access checks and mutations as the workbench.
const openingBoardDialog=ref(false), boardReadError=ref('')
const requestedDialogVisible=computed(()=>{
  if(!props.boardRequest)return false
  if(props.boardRequest.action==='assign')return assignmentDialogVisible.value
  if(props.boardRequest.action==='review')return reviewDialogVisible.value
  if(props.boardRequest.action==='disposition')return dispositionDialogVisible.value
  if(props.boardRequest.action==='rework')return reworkDialogVisible.value
  return traceDialogVisible.value
})
watch(requestedDialogVisible,(open,wasOpen)=>{
  if(wasOpen && !open && detectionPageActive)emit('dismiss')
})
async function openBoardRequest() {
  const {action,taskId}=props.boardRequest
  if(action==='images')return openImageBrowser(taskId)
  if(action==='trace')return openTraceDialog(taskId)
  openingBoardDialog.value=true
  boardReadError.value=''
  const owner=accountSession.stamp()
  try {
    const response=await captureAccountRequest().get('/api/detection/tasks/'+encodeURIComponent(taskId))
    if(!detectionPageActive || !accountSession.current(owner))return
    const row=response.data?.data
    if(response.data?.code!==200 || row?.taskId!==taskId)throw Error()
    if(action==='assign')openAssignmentDialog(row)
    else if(action==='disposition')openDispositionDialog(row,row.flowStatus==='CONFIRMED'&&row.reviewConclusion==='NEEDS_RECHECK'?'RECHECK':undefined)
    else if(action==='rework')openReworkDialog(row)
    else openReviewDialog(row)
    if(requestedDialogVisible.value)openingBoardDialog.value=false
    else boardReadError.value='任务状态或权限已变化，请返回列表查看最新进度。'
  } catch {
    if(detectionPageActive && accountSession.current(owner))boardReadError.value='暂时无法读取这项任务，请重试。'
  }
}

onMounted(async () => {
  if(props.boardRequest){await openBoardRequest();return}
  const initialNavigation = route.fullPath
  const routeTab = String(route.query.tab || route.meta?.detectionTab || '')
  if (validTabs.includes(routeTab)) {
    activeTab.value = routeTab
  }
  const queryWorkOrderNo = typeof route.query.workOrderNo === 'string' ? route.query.workOrderNo.trim() : ''
  const queryBatchNo = typeof route.query.batchNo === 'string' ? route.query.batchNo.trim() : ''
  if (queryWorkOrderNo && activeTab.value === 'work-order-trace') workOrderTraceNo.value = queryWorkOrderNo
  if (queryBatchNo && activeTab.value === 'batch-trace') batchTraceNo.value = queryBatchNo
  if (typeof route.query.keyword === 'string' && route.query.keyword.trim()) {
    activeTab.value = 'history'
  }

  if (activeTab.value === 'workspace') {
    fetchModels()
    return
  }
  await restoreFromSession()
  if (activeTab.value === 'history') readHistoryFromRoute(route.query.keyword, route.query.completedResults === '1', true)

  // 从上传页跳转过来时自动选中对应任务
  const queryTaskId = route.query.taskId
  if (queryTaskId && route.fullPath === initialNavigation) {
    const action=route.query.boardAction
    if (action==='trace') openTraceDialog(String(queryTaskId))
    if (action==='images') openImageBrowser(String(queryTaskId))
    if (action==='assign' || action==='review') {
      try {
        const response=await captureAccountRequest().get('/api/detection/tasks/'+encodeURIComponent(queryTaskId))
        if(route.fullPath===initialNavigation && response.data?.code===200) {
          const row=response.data.data
          if(action==='assign')openAssignmentDialog(row)
          else openReviewDialog(row)
        }
      } catch {ElMessage.error('任务已更新或无法访问，请返回任务列表核对')}
    }
  }

  if (route.fullPath === initialNavigation && queryWorkOrderNo && activeTab.value === 'work-order-trace') {
    activeTab.value = 'work-order-trace'
    workOrderTraceNo.value = String(queryWorkOrderNo)
    if (workOrderTraceReport.value?.workOrderNo !== queryWorkOrderNo) await loadWorkOrderTraceReport()
  }

  if (route.fullPath === initialNavigation && queryBatchNo && activeTab.value === 'batch-trace') {
    activeTab.value = 'batch-trace'
    batchTraceNo.value = String(queryBatchNo)
    if (batchTraceReport.value?.batchNo !== queryBatchNo) await loadBatchTraceReport()
  }
})

onBeforeUnmount(() => {
  detectionPageActive = false
  modelReadVersion++
  singleRunVersion++
  singleRequest?.abort()
  traceGeneration++
  traceReadController?.abort()
  // 不再停止轮询 — 轮询在 store 中，切换页面后继续
  // 只保存当前状态
  if(!props.boardRequest && activeTab.value !== 'workspace')saveTaskList()
})
const collaborationEditing=computed(()=>reviewDialogVisible.value||assignmentDialogVisible.value||dispositionDialogVisible.value||reworkDialogVisible.value||reviewSubmitting.value||assignmentSubmitting.value||dispositionSubmitting.value||reworkSubmitting.value)
async function refreshCollaborationView(){
  if(collaborationEditing.value)return false
  if(props.boardRequest)return true
  let updated=true
  if(activeTab.value==='history'){await refreshHistory();updated=!historyError.value}
  else if(activeTab.value==='work-order-trace'&&workOrderTraceReport.value)await refreshWorkOrderTraceReport()
  else if(activeTab.value==='batch-trace'&&batchTraceReport.value)await refreshBatchTraceReport()
  collaborationChanged.value=updated===false
  return updated
}
function discardInaccessibleTasks({requestedIds,missingIds,isCurrent}) {
  if(!isCurrent())return
  const account=accountSession.stamp(),requested=new Set(requestedIds)
  const ids=[...new Set(missingIds.filter(id=>requested.has(id)))].slice(0,100)
  if(!ids.length||!accountSession.current(account)||!isCurrent())return
  pollingStore.invalidateTaskReads()
  for(const forget of [forgetHistoryTasks,forgetTraceTasks]){
    if(!isCurrent()||!accountSession.current(account))return
    forget(ids)
  }
  if(isCurrent()&&accountSession.current(account))taskStore.forgetTaskAccess(ids,account)
}
const { latest:taskChanges } = useLatestChanges(computed(() => {
  if(props.boardRequest)return []
  const rows=activeTab.value==='history'?historyRecords.value
    :activeTab.value==='work-order-trace'?(workOrderTraceReport.value?.records||[])
      :activeTab.value==='batch-trace'?(batchTraceReport.value?.records||[]):[]
  return rows.map(task=>({taskId:task.taskId,version:task.version}))
}), 'DETECTION_TASK', 'DETECTION', 'taskId', {onInaccessible:discardInaccessibleTasks})
const collaborationOpenedTask = computed(() => {
  const opened = [[reviewTask,reviewDialogVisible],[assignmentTask,assignmentDialogVisible],
    [dispositionTask,dispositionDialogVisible],[reworkTask,reworkDialogVisible]].find(([task,visible]) => visible.value && task.value?.taskId)
  return opened?.[0].value || (traceDialogVisible.value ? traceDetail.value : null)
})
const collaborationHistoryLink = computed(() => resourceHistoryLink('DETECTION_TASK', collaborationOpenedTask.value?.taskId, 'DETECTION'))
const {changed:collaborationChanged}=useResourceChanges({resourceType:'DETECTION_TASK',isEditing:()=>collaborationEditing.value,refresh:refreshCollaborationView,revalidate:validateCollaborationAccess})
const canAssignQualityTask=task=>userStore.role==='SUPERVISOR'&&stateCanAssignQualityTask(task)
async function validateCollaborationAccess(){
 const groups=new Map()
 const add=(id,entry)=>{if(!id)return;if(!groups.has(id))groups.set(id,[]);groups.get(id).push(entry)}
 for(const [task,visible,form] of [[reviewTask,reviewDialogVisible,reviewForm],[assignmentTask,assignmentDialogVisible,assignmentForm],[dispositionTask,dispositionDialogVisible,dispositionForm],[reworkTask,reworkDialogVisible,reworkForm]]){
  if(visible.value&&task.value?.taskId)add(task.value.taskId,{task,visible,form})
 }
 if(traceDialogVisible.value&&traceDetail.value?.taskId)add(traceDetail.value.taskId,{trace:true})
 await Promise.allSettled([...groups].map(async([id,entries])=>{
  try{const response=await fetchDetectionTaskTrace(id);if(response.data?.code!==200)throw Object.assign(new Error('当前任务无权读取'),{httpStatus:response.data?.code})
   for(const entry of entries)if(entry.trace&&traceDetail.value?.taskId===id&&!collaborationEditing.value)traceDetail.value=response.data.data
  }catch(error){if(![401,403,404].includes(error.response?.status||error.httpStatus))return
   for(const entry of entries){if(entry.trace){if(traceDetail.value?.taskId===id){traceDetail.value=null;traceDialogVisible.value=false}}else if(entry.task.value?.taskId===id){entry.visible.value=false;entry.task.value=null;for(const key of Object.keys(entry.form))entry.form[key]=typeof entry.form[key]==='string'?'':null}}
   taskStore.removeTask(id)
  }
 }))
}
</script>

<style scoped>
.board-task-dialogs{display:contents}
.board-review-evidence{display:flex;flex-direction:column;gap:12px;min-width:0}
.board-review-evidence > .evidence-comparison{order:-1}
.board-calibration-form {
  display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); column-gap:12px; align-content:start;
}
.board-calibration-form :deep(.el-form-item) { min-width:0; }
.calibration-notes { grid-column:1/-1; }
:global(.board-calibration-dialog.el-dialog) { display:flex; flex-direction:column; max-height:92dvh; }
:global(.board-calibration-dialog .el-dialog__body) { min-height:0; max-height:none; overflow-y:auto; }
:global(.board-calibration-dialog .el-dialog__footer) {
  flex:none; padding-top:12px; border-top:1px solid var(--app-border); background:var(--app-surface);
}
@media (max-width:600px) {
  :global(.board-calibration-dialog .el-dialog__footer .el-button) { min-height:42px; }
  .board-calibration-form :deep(.el-select__placeholder),.board-calibration-form :deep(input),.board-calibration-form :deep(textarea) { font-size:16px; }
}
.image-detection-container {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 24px;
}

.browser-task-id { margin:0 0 12px; color:var(--app-text-secondary); font-size:12px; overflow-wrap:anywhere; }
.image-detection-container > * { min-width:0; }

.detection-hero {
  align-items: stretch;
}

.detection-flow-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 16px;
}

.workspace-tabs :deep(.el-tabs__content) {
  margin-top: 8px;
}

.workspace-tabs :deep(.el-tabs__header) {
  padding: 0 4px;
}

.single-test-tabs :deep(.el-tabs__header) { display:none; }

.workspace-tabs :deep(.el-tabs__item) {
  height: 48px;
}

.detection-card-heading { display:inline-flex; align-items:center; gap:9px; margin:0; font-size:16px; font-weight:650; color:var(--app-text); }
.detection-card-heading .el-icon { color:var(--app-primary); }
.detection-parameters {margin:12px 0;border-block:1px solid var(--app-border)}
.detection-parameters summary {display:flex;align-items:center;gap:7px;padding:11px 2px;font-size:13px;cursor:pointer;color:var(--app-text)}
.detection-parameters summary>span {margin-left:auto;color:var(--app-text-secondary);font-size:12px}
.detection-parameters summary::-webkit-details-marker {display:none}
.detection-parameters[open] summary>.el-icon:last-child {transform:rotate(180deg)}
.detection-parameters summary:focus-visible {outline:2px solid var(--app-primary)}
.detection-settings {display:grid;gap:10px;padding:8px 2px 12px}
.single-file-target {display:flex;flex-direction:column;align-items:center;gap:6px;color:var(--app-primary);font-size:15px}
.single-file-target small {font-size:12px;color:var(--app-text-secondary)}
.single-image-uploader :deep(.el-upload-dragger) {width:100%;padding:18px 12px;border-color:var(--app-border-focus);background:var(--app-primary-light)}
.detection-settings > div { min-width:0; }
.detection-settings :deep(.el-form-item) { margin-bottom:8px; }
.detection-settings .detection-input-note { margin-bottom:0; }
.single-mode-header { display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px }
.workspace-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 24px;
  align-items: start;
}

.detection-card {
  min-width: 0;
}

.input-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 20px;
}

.input-block {
  min-width: 0;
}

.input-block-title {
  margin-bottom: 12px;
  font-size: 14px;
  font-weight: 600;
  color: var(--app-text);
}

.wide-button {
  width: 100%;
}

.secondary-action {
  margin-top: 12px;
}

.single-detection-workspace {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(240px, 0.82fr) minmax(360px, 1.18fr);
  gap: 20px;
  align-items: stretch;
}

.single-detection-controls {
  min-width: 0;
}

.single-image-uploader {
  width: 100%;
}

.single-image-uploader :deep(.el-upload),
.single-image-uploader :deep(.el-upload-list) {
  width: 100%;
}

.single-image-uploader :deep(.el-upload-list__item) {
  min-height: 76px;
  height: auto;
  margin-top: 12px;
  padding: 8px 10px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.9);
}

.single-image-uploader :deep(.el-upload-list__item-name) {
  display: none;
}

.single-upload-file-name {
  display: grid;
  gap: 4px;
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 12px;
  background: rgba(239, 246, 255, 0.72);
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.single-upload-file-name span {
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.single-upload-file-name strong {
  color: #1e293b;
  font-size: 13px;
  line-height: 1.55;
}

.single-detection-result {
  min-width: 0;
  min-height: 208px;
  padding: 0 0 0 20px;
  border: 0;
  border-left: 1px solid var(--app-border);
  border-radius: 0;
  background: var(--app-surface);
}

.single-result-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.single-result-heading > div:first-child {
  display: grid;
  gap: 2px;
}

.single-result-heading strong {
  color: var(--app-text);
  font-size: 16px;
}

.single-result-tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.single-result-runtime {
  display: grid;
  gap: 5px;
  margin-bottom: 12px;
  padding: 9px 11px;
  border-radius: 10px;
  background: rgba(239, 246, 255, 0.76);
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
}

.single-result-error {
  margin-bottom: 12px;
}

.single-result-hint {
  margin: 12px 0 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
  text-align: center;
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
  display:flex;
  align-items:baseline;
  justify-content:space-between;
  flex-wrap:wrap;
  gap:6px 12px;
  width:100%;
  margin-top: 8px;
  color:var(--app-text-secondary);
  font-size:12px;
  line-height:1.8;
}
.threshold-text output { color:var(--app-primary); font-size:18px; font-weight:600; font-variant-numeric:tabular-nums; }
.threshold-text output small { color:var(--app-text-secondary); font-size:12px; font-weight:400; }

.card-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

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

.single-result-image {
  min-height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: 18px;
  background: #f8fafc;
}

.single-result-image img {
  width: 100%;
  max-height: 320px;
  object-fit: contain;
}

.single-result-preview img {
  max-height: 250px;
}

.history-page-card .card-title-row > span:first-child { display:inline-flex; align-items:center; gap:8px; }
.history-page-card .card-title-row > span:first-child .el-icon { color:var(--app-primary); }
.upload-route { display:inline-flex; align-items:center; gap:7px; padding:8px 12px; border:1px solid var(--app-border-strong); border-radius:8px; background:var(--app-surface); color:var(--app-primary-deep); font-size:13px; }
.upload-route:hover { border-color:var(--app-border-focus); }
.history-scope-note { display:flex; align-items:flex-start; gap:7px; margin:0 0 18px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.history-scope-note > .el-icon { color:var(--app-primary); flex-shrink:0; margin-top:3px; }
.history-query-form { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; align-items:end; margin-bottom:14px; }
.history-query-form label { display:grid; gap:7px; min-width:0; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.history-query-actions { display:flex; align-items:center; flex-wrap:wrap; gap:8px; min-height:32px; }
.history-query-actions .el-button + .el-button { margin-left:0; }
.history-advanced-filters { grid-column:1 / -1; display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; padding:10px 12px; border-radius:8px; background:var(--app-surface-muted); }
.history-applied-query { margin:0 0 14px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; overflow-wrap:anywhere; }
.history-filter-note { padding:10px 12px; margin:0 0 16px; border-radius:7px; background:var(--app-primary-soft); color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.history-records-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); align-items:start; gap:18px; }
.history-retry { margin:12px 0 18px; }
.history-pagination { display:flex; justify-content:flex-end; padding:20px 0 4px; }
.history-pagination :deep(.el-pagination) { flex-wrap:wrap; gap:8px; }
@media(max-width:1100px) { .history-records-grid { grid-template-columns:minmax(0,1fr); } }
@media(max-width:720px) { .history-query-form,.history-advanced-filters { grid-template-columns:minmax(0,1fr); } .history-pagination { justify-content:flex-start; } }
.path-text {
  color: #172033;
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

.trace-examples { margin:12px 0 20px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.trace-examples summary { width:fit-content; cursor:pointer; }
.trace-examples p { margin:9px 0; max-width:75ch; }
.trace-examples summary:focus-visible { outline:2px solid var(--app-primary); outline-offset:4px; border-radius:3px; }
.batch-trace-card .card-title-row > span:first-child { display:inline-flex; align-items:center; gap:8px; }
.batch-trace-card .card-title-row > span:first-child .el-icon { color:var(--app-primary); }
@media (max-width: 1080px) {
  .workspace-grid,
  .input-grid,
  .single-detection-workspace {
    grid-template-columns: 1fr;
  }

  .single-detection-result { padding:20px 0 0; border-left:0; border-top:1px solid var(--app-border); }
}

@media (max-width: 720px) {
  .batch-trace-search {
    grid-template-columns: 1fr;
  }
}

.detection-input-note { margin:0 0 14px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.detection-input-note.is-warning { padding:9px 11px; border-radius:8px; color:var(--app-warning); background:var(--app-warning-soft); }
.detection-input-note button { margin:4px 0 0; padding:2px 0; border:0; border-radius:4px; color:var(--app-primary); background:transparent; cursor:pointer; font:inherit; }
.detection-model-selection { display:flex; align-items:flex-start; flex-wrap:wrap; gap:8px 10px; width:100%; margin:0 0 10px; padding:11px 0; border-top:1px solid var(--app-border); border-bottom:1px solid var(--app-border); }
.detection-model-selection > .el-icon { flex:0 0 auto; margin-top:3px; color:var(--app-primary); }
.detection-model-selection > div { display:grid; gap:4px; min-width:0; flex:1 1 150px; }
.detection-model-selection strong { color:var(--app-text); font-size:13px; font-weight:550; line-height:1.8; overflow-wrap:anywhere; }
.detection-model-selection > div > span { color:var(--app-text-secondary); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.detection-model-selection > .business-status { flex:0 0 auto; }
.single-submission-summary { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:10px 18px; margin:0 0 16px; padding:12px 0; border-block:1px solid var(--app-border); }
.single-submission-summary > div { min-width:0; }.single-submission-summary > div:first-child { grid-column:1/-1; }
.single-submission-summary dt { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.single-submission-summary dd { margin:4px 0 0; color:var(--app-text); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.detection-input-note button:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
@media(max-width:480px) { .single-submission-summary { grid-template-columns:minmax(0,1fr); } }
</style>
