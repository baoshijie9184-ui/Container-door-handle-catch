<template>
  <div class="page-shell image-detection-container">
    <PageHero class="page-hero detection-hero command-panel">
      <div>
        <span class="industrial-kicker">Detection Workspace</span>
        <h1 class="page-hero-title">{{ workspacePresentation.title }}</h1>
        <p class="page-hero-text">
          {{ workspacePresentation.description }}
        </p>
        <div class="detection-flow-chips">
          <router-link to="/upload"><AppIcon name="Upload" :size="14" />采集上传</router-link>
          <router-link to="/inspection/workbench"><AppIcon name="Picture" :size="14" />模型检测</router-link>
          <router-link to="/quality/queue"><AppIcon name="CircleCheck" :size="14" />人工质检</router-link>
        </div>
      </div>
      <div class="hero-side-note">
        <strong><AppIcon name="DocumentChecked" :size="16" />保留检测依据</strong>
        <span>模型结果供人工核对，放行、返工与报告审批按当前账号权限完成。</span>
      </div>
    </PageHero>

    <el-tabs v-model="activeTab" class="workspace-tabs" @tab-change="handleTabChange">
      <el-tab-pane name="workspace" label="检测工作台">
        <div class="workspace-grid">
          <el-card class="detection-card detection-input-card" header="检测输入" shadow="never">
            <el-form label-position="top">
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
                  >
                    <span class="detection-model-option"><span>{{ detectionModelOptionLabel(model) }}</span><StatusBadge domain="model" :code="model.status" /></span>
                  </el-option>
                </el-select>
              </el-form-item>
              <p v-if="modelsError" class="detection-input-note is-warning" role="alert">{{ modelsError }}<button type="button" :disabled="modelsLoading || loadingSingle" @click="fetchModels">重新读取目录</button></p>
              <div v-if="form.modelId" class="detection-model-selection"><AppIcon name="Tickets" :size="17" /><div><strong>{{ selectedDetectionModel?.modelName || '所选模型名称尚未核对' }}</strong><span>模型 #{{ form.modelId }} · 版本 {{ selectedDetectionModel?.version || '未记录' }}</span><span v-if="!selectedDetectionModel">本次目录未找到此编号，提交时仍需由服务端核对。</span><span v-else-if="modelsError">以上保留上次读取的目录资料。</span></div><StatusBadge v-if="selectedDetectionModel" domain="model" :code="selectedDetectionModel.status" /></div>
              <p id="detection-model-choice-note" class="detection-input-note">{{ form.modelId ? '已选模型仅作为本次提交参数，实际执行版本请核对任务记录。' : '未指定模型时由服务端按现有配置选择，实际模型以任务记录为准。' }}</p>

              <el-form-item label="置信度阈值">
                <el-slider v-model="form.threshold" :disabled="loadingSingle" :min="0" :max="1" :step="0.01" :format-tooltip="value=>Math.round(value*100)+'%'" :format-value-text="value=>value.toFixed(2)+'，'+Math.round(value*100)+'%'" aria-label="本次检测置信度阈值，范围 0 至 1" aria-describedby="detection-threshold-note" />
                <div class="threshold-text"><span>本次提交阈值</span><output aria-label="当前置信度阈值">{{ form.threshold.toFixed(2) }}<small>（{{ Math.round(form.threshold * 100) }}%）</small></output></div>
                <p id="detection-threshold-note" class="detection-input-note">阈值是模型分数的筛选条件，不是准确率或人工结论。本页设置用于下一次单图或待检测任务提交，不会改写已经提交的任务。</p>
              </el-form-item>

              <div class="input-grid">
                <div class="input-block">
                  <div class="input-block-title">单图检测</div>
                  <div class="single-detection-workspace">
                    <div class="single-detection-controls">
                      <el-upload
                        v-model:file-list="fileList"
                        class="single-image-uploader"
                        :auto-upload="false"
                        :on-change="handleUploadChange"
                        :on-remove="handleRemove"
                        accept=".jpg,.jpeg,.png"
                        list-type="picture"
                        :limit="1"
                        :disabled="loadingSingle"
                      >
                        <el-button type="primary" class="wide-button" :disabled="loadingSingle">
                          <el-icon><Upload /></el-icon>
                          选择单张图片
                        </el-button>
                      </el-upload>
                      <div
                        v-if="form.imageFile"
                        class="single-upload-file-name"
                        :title="form.imageFile.name"
                      >
                        <span>已选择文件</span>
                        <strong>{{ form.imageFile.name }}</strong>
                      </div>
                      <el-button
                        type="default"
                        class="wide-button secondary-action"
                        :disabled="!form.imageFile || singleStageCode === 'UNCONFIRMED'"
                        :aria-describedby="singleStageCode === 'UNCONFIRMED' ? 'single-result-reconcile-note' : undefined"
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
                          <strong>检测结果</strong>
                        </div>
                        <div class="single-result-tags">
                          <StatusBadge domain="singleDetection" :code="singleStageCode" />
                        </div>
                      </div>

                      <div v-if="singleDetectionTaskId || singleDetectionMessage" class="single-result-runtime">
                        <code v-if="singleDetectionTaskId" class="single-result-task-id">
                          {{ singleDetectionTaskId }}
                        </code>
                        <span v-if="singleDetectionMessage" role="status" aria-live="polite">{{ singleDetectionMessage }}</span>
                      </div>
                      <dl v-if="singleSubmission" class="single-submission-summary"><div><dt>本次提交图片</dt><dd>{{ singleSubmission.fileName }}</dd></div><div><dt>提交模型选项</dt><dd>{{ singleSubmission.modelLabel }}</dd></div><div><dt>提交阈值</dt><dd>{{ formatEvidenceConfidence(singleSubmission.threshold) }}</dd></div></dl>
                      <el-alert
                        v-if="['FAILED','UNCONFIRMED'].includes(singleStageCode)"
                        :type="singleStageCode === 'FAILED' ? 'error' : 'warning'"
                        :closable="false"
                        show-icon
                        :title="singleDetectionMessage"
                        class="single-result-error"
                      />
                      <p v-if="singleStageCode === 'UNCONFIRMED'" id="single-result-reconcile-note" class="detection-input-note">连接或结果读取未完成不等于任务失败，请先<router-link to="/inspection/history">查看检测记录</router-link>。本页不会自动重新提交；选择新图片会开始新的提交。</p>
                      <div v-if="singleDetectionTaskId" class="single-task-links"><button type="button" @click="openTraceDialog(singleDetectionTaskId)"><AppIcon name="Search" :size="14" />核对本次任务</button><router-link :to="{path:'/quality/reports',query:{taskId:singleDetectionTaskId}}">报告与审批</router-link></div>

                      <SingleDetectionEvidence v-if="detectionResult" :task-id="singleDetectionTaskId" :file-name="singleSubmission?.fileName || ''" :original-url="detectionResult.processedImagePath" :annotation-url="annotatedImageUrl" :local-preview="fileList[0]?.url || ''" :category-label="getCategoryText(detectionResult.category)" :category-tone="getCategoryType(detectionResult.category)" :confidence-label="formatConfidence(detectionResult.confidence)" />
                      <template v-else-if="fileList[0]?.url">
                        <div class="single-result-image single-result-preview">
                          <img :src="fileList[0].url" alt="待检测图片预览" />
                        </div>
                        <p class="single-result-hint">{{ loadingSingle ? '当前图片正在处理，提交参数已锁定，请等待或核对任务记录。' : singleStageCode === 'UNCONFIRMED' ? '原图保留，先核对已有任务；不要根据预览推断检测已完成。' : '图片已选入，核对模型与阈值后开始检测' }}</p>
                      </template>
                      <el-empty v-else description="请先选择图片并开始检测" :image-size="88" />
                    </section>
                  </div>
                </div>
              </div>
            </el-form>
          </el-card>

          <el-card class="detection-card task-card" shadow="never">
            <template #header>
              <div class="card-title-row">
                <span>上传任务列表</span>
                <el-badge v-if="taskList.length" :value="taskList.length"  />
                <el-button size="small" link :loading="refreshingTasks" @click="refreshTaskList" title="刷新任务列表" aria-label="刷新任务列表">
                  <template #icon><el-icon><Refresh /></el-icon></template>
                </el-button>
              </div>
            </template>
            <!-- 搜索栏 -->
            <div class="task-search-bar">
              <label class="workbench-task-filter" for="workbench-task-keyword"><span>任务或文件夹</span>
              <el-input
                id="workbench-task-keyword"
                ref="taskKeywordInput"
                v-model="taskSearchKeyword"
                maxlength="200"
                aria-label="搜索任务ID或文件夹名…" placeholder="搜索任务ID或文件夹名…"
                clearable
                size="small"
                class="task-search-input"
              >
                <template #prefix><el-icon><Search /></el-icon></template>
              </el-input>
              </label>
              <label class="workbench-task-filter" for="workbench-task-date"><span>最近更新日期 · UTC+8</span>
              <el-date-picker
                id="workbench-task-date"
                v-model="taskFilterDate"
                aria-label="按 UTC+8 最近更新日期筛选当前任务清单" placeholder="选择更新日期"
                size="small"
                class="task-date-picker"
                value-format="YYYY-MM-DD"
                clearable
              />
              </label>
            </div>
            <!-- 筛选标签 -->
            <div v-if="taskList.length" class="task-filter-bar">
              <el-radio-group v-model="taskFilter" size="small" aria-label="按已登记处理阶段筛选当前任务清单">
                <el-radio-button value="all">全部</el-radio-button>
                <el-radio-button value="pending">待检测</el-radio-button>
                <el-radio-button value="running">检测中</el-radio-button>
                <el-radio-button value="done">已完成</el-radio-button>
                <el-radio-button value="failed">失败</el-radio-button>
              </el-radio-group>
            </div>
            <div class="workbench-task-scope"><p>{{ businessTraceScope }} · 匹配 {{ filteredTaskList.length }} / 当前清单 {{ taskList.length }} 条。仅筛选本机记录与最近一次读取合并的清单，完整历史请查看<router-link to="/inspection/history">检测记录</router-link>。</p><button v-if="hasTaskFilters" type="button" @click="clearTaskFilters(true)"><AppIcon name="Filter" :size="14" />清空筛选</button></div>
            <p v-if="refreshingTasks && filteredTaskList.length" class="detection-input-note" role="status">正在读取任务记录，当前保留已有清单。</p>
            <el-alert v-if="taskReadError && filteredTaskList.length" :title="taskReadError+'；当前保留已有清单，请重新读取后核对。'" type="warning" :closable="false" show-icon />
            <template v-if="filteredTaskList.length===0"><CollectionEmptyState :loading="refreshingTasks || (!taskReadLoaded && !taskReadError)" :error="taskReadError" :filtered="hasTaskFilters" empty-title="当前清单暂无上传任务" empty-description="可上传图片创建任务；这里不是全部历史任务数量。" @retry="refreshTaskList" @reset="clearTaskFilters(true)" /><router-link v-if="!taskList.length && !refreshingTasks && taskReadLoaded && !taskReadError" class="workbench-upload-link" to="/upload"><AppIcon name="Upload" :size="16" />前往上传图片</router-link></template>
            <div v-else class="task-list">
              <div
                v-for="task in filteredTaskList"
                :key="task.taskId"
                class="task-item"
                :class="{ 'task-item-selected': selectedTaskId === task.taskId }"
              >
                <!-- 可折叠行 -->
                <div class="task-item-main">
                  <div class="task-item-taskid">
                    <span class="taskid-label">任务ID</span>
                    <code class="taskid-value">{{ task.taskId }}</code>
                  </div>
                  <button type="button" class="task-item-row1 task-item-toggle" :aria-expanded="selectedTaskId===task.taskId" :aria-controls="'workbench-task-detail-'+task.taskId" :aria-label="(selectedTaskId===task.taskId?'收起':'展开')+'任务详情：'+(task.folderName || task.taskId)" @click="selectedTaskId = selectedTaskId === task.taskId ? null : task.taskId">
                    <span class="task-item-folder">{{ task.folderName || '检测任务' }}</span>
                    <StatusBadge domain="detection" :code="taskExecutionCode(task)" />
                    <el-icon
                      class="task-expand-icon"
                      :class="{ 'task-expand-icon-open': selectedTaskId === task.taskId }"
                    >
                      <ArrowDown />
                    </el-icon>
                  </button>
                  <div class="task-item-capture">
                    <span v-if="task.batchNo">批次：{{ task.batchNo }}</span>
                    <span v-if="task.workOrderNo">工单：{{ task.workOrderNo }}</span>
                    <StatusBadge v-if="task.flowStatus" domain="flow" :code="task.flowStatus" :label="flowStatusText(task.flowStatus)" />
                    <span v-if="task.reviewStatus">复核：{{ reviewStatusText(task.reviewStatus) }}</span>
                    <span v-if="task.severityLevel">等级：{{ severityText(task.severityLevel) }}</span>
                  </div>
                  <div v-if="task.captureInfo" class="task-item-capture">
                    <span v-if="task.captureInfo.captureDate">{{ task.captureInfo.captureDate }}</span>
                    <span v-if="task.captureInfo.collector">{{ task.captureInfo.collector }}</span>
                    <span v-if="task.captureInfo.deviceName">{{ task.captureInfo.deviceName }}</span>
                  </div>
                  <TaskExecutionProgress :task="task" />
                  <QualityStageGuidance v-if="selectedTaskId === task.taskId" :task="task" />
                </div>

                <!-- 操作按钮 -->
                <div class="task-item-actions">
                  <el-button
                    v-if="task.stage === 'uploaded' && Array.isArray(task.uploadedFiles) && task.uploadedFiles.length"
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
                    导出任务摘要
                  </el-button>
                  <el-button
                    v-if="task.stage === 'completed' || task.stage === 'failed'"
                    link
                    size="small"
                    type="danger"
                    :disabled="historyCacheBusy" @click.stop="clearHistoryTaskCache(task.taskId)"
                  >
                    <el-icon><Delete /></el-icon>清除本机缓存
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
                    v-if="canReviewTask(task)"
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
                    v-if="canSubmitReworkResult(task)"
                    type="primary"
                    size="small"
                    @click.stop="openReworkDialog(task)"
                  >
                    返工回填
                  </el-button>
                </div>

                <!-- 展开详情 -->
                <Transition name="task-detail">
                <div v-if="selectedTaskId === task.taskId" :id="'workbench-task-detail-'+task.taskId" class="task-item-detail">
                  <details v-if="taskExecutionLogs(task).length" class="task-log-block">
                    <summary class="task-log-head">最近动态 · 本机记录 · UTC+8</summary>
                    <p class="task-log-note">仅展示本机已记录的动态，不代替服务器审计；只有时分秒的旧记录无法核对日期。</p>
                    <ol class="task-log-list">
                      <li v-for="log in taskExecutionLogs(task)" :key="log.key" class="task-log-item">
                        <span class="task-log-time">{{ log.time }}</span>
                        <span class="task-log-text">{{ log.text }}</span>
                      </li>
                    </ol>
                  </details>

                  <TaskResultSnapshot v-if="task.result" :task-id="task.taskId" :result="task.result" @trace="openTraceDialog" />
                  <p v-else-if="task.stage==='completed' || task.stage==='failed'" class="task-result-unread">本机未保存结果正文，可通过“追溯详情”重新读取。没有正文不代表服务器没有结果。</p>
                </div>
                </Transition>
              </div>
            </div>
          </el-card>
        </div>

      </el-tab-pane>

      <el-tab-pane name="history" label="检测记录">
        <el-card class="detection-card history-page-card" shadow="never">
          <template #header><div class="card-title-row"><span><AppIcon name="Tickets" :size="18" />检测记录</span><el-tag type="info" effect="plain">{{ historyLoading ? '正在读取任务与结果' : historyError ? '本次读取未完成' : historyTotal!==null ? `共 ${historyTotal} 条` : historyLoaded ? '总数未提供' : '数量尚未读取' }}</el-tag><el-button size="small" :loading="historyLoading" @click="refreshHistory"><AppIcon name="Refresh" :size="15" />刷新已读范围</el-button></div></template>
          <p class="history-scope-note"><AppIcon name="Lock" :size="15" />{{ userStore.role==='SUPERVISOR' ? '企业业务范围' : userStore.role==='INSPECTOR' ? '本人及分派任务' : '当前账号有权访问的范围' }} · 检测完成与人工复核、放行、报告审批分别记录。</p>
          <form class="history-query-form" @submit.prevent="onHistorySearch">
            <label for="history-keyword" class="history-query-keyword">任务、文件夹、工单或批次<el-input id="history-keyword" v-model="historySearchKeyword" clearable placeholder="输入编号或文件夹关键词"><template #prefix><AppIcon name="Search" :size="15" /></template></el-input></label>
            <label for="history-collector">采集人员<el-input id="history-collector" v-model="historyFilterCollector" clearable placeholder="输入采集人员" /></label>
            <label for="history-device">设备名称<el-input id="history-device" v-model="historyFilterDevice" clearable placeholder="输入采集设备名称" /></label>
            <label for="history-region">采集区域<el-input id="history-region" v-model="historyFilterRegion" clearable placeholder="输入采集区域" /></label>
            <div class="history-query-actions"><el-button type="primary" native-type="submit" :loading="historyLoading"><AppIcon name="Search" :size="15" />查询</el-button><el-button v-if="hasHistoryFilters" @click="onHistoryReset"><AppIcon name="Refresh" :size="15" />重置</el-button></div>
          </form>
          <p v-if="historyLoaded" class="history-applied-query">已读取：{{ historyAppliedDescription }} · 第 {{ historyPage }} 页 · 本页 {{ historyRecords.length }} 条</p>
          <p v-if="historyFiltersDirty && historyRecords.length" class="history-filter-note" role="status">输入条件已修改，下方仍为已读取范围；点击查询更新。刷新和翻页沿用已执行的条件。</p>
          <el-alert v-if="historyError && historyRecords.length" :title="historyError+'；下方保留已读取资料，请重新核对。'" type="error" show-icon :closable="false" />
          <div v-if="historyError && historyRecords.length" class="history-retry"><el-button size="small" :loading="historyLoading" @click="retryHistoryRead"><AppIcon name="Refresh" :size="14" />重读上次查询</el-button></div>
          <CollectionEmptyState v-if="!historyRecords.length" :loading="historyLoading" :error="historyError" :filtered="historyLoaded ? Object.keys(historyAppliedFilters).length>0 : hasHistoryFilters" empty-title="暂无检测记录" empty-description="可从图片上传创建任务，或核对关键词与当前账号范围后重新查询。" @retry="retryHistoryRead" @reset="onHistoryReset" />
          <div v-else class="history-records-grid"><DetectionHistoryCard v-for="task in historyRecords" :key="task.taskId" :task="task" :cached="Array.isArray(taskStore.taskList) && taskStore.taskList.some(cached=>cached.taskId===task.taskId)" :cache-busy="historyCacheBusy" :refreshing="historyLoading" @trace="openTraceDialog" @refresh="refreshHistory" @remove-cache="clearHistoryTaskCache" /></div>
          <div v-if="historyTotal!==null" class="history-pagination"><el-pagination :current-page="historyPage" :page-size="historyPageSize" :total="historyTotal" :page-sizes="[10,20,50]" :disabled="historyLoading || !!historyError" layout="total, sizes, prev, pager, next, jumper" @current-change="onHistoryPageChange" @size-change="onHistorySizeChange" /></div>
        </el-card>
      </el-tab-pane>
      <el-tab-pane name="quality" label="质检队列">
        <el-card class="detection-card quality-queue-card" shadow="never">
          <template #header>
            <div class="card-title-row">
              <span>质检队列</span>
              <el-tag type="info" effect="plain">{{ qualityQueueTotal === null ? '总数尚未核对' : `${qualityQueueTotal} 条待处理` }}</el-tag>
              <el-button size="small" :loading="qualityQueueLoading" @click="loadQualityQueue()">
                <el-icon><Refresh /></el-icon>
                刷新
              </el-button>
            </div>
          </template>

          <p class="quality-queue-scope"><AppIcon name="User" :size="15" />{{ userStore.role === 'SUPERVISOR' ? '企业业务范围' : userStore.role === 'INSPECTOR' ? '本人及分派任务' : '当前账号有权访问的范围' }} · 按所选处理阶段查看，不代表全部历史任务</p>
          <div class="quality-queue-tabs" role="group" aria-label="按质检处理阶段筛选">
            <button
              v-for="queue in qualityQueues"
              :key="queue.value"
              type="button"
              class="quality-queue-chip"
              :class="{ active: activeQualityQueue === queue.value }"
              :aria-pressed="activeQualityQueue === queue.value"
              @click="switchQualityQueue(queue.value)"
            >
              <span>{{ queue.label }}</span>
              <small>{{ queue.hint }}</small>
            </button>
          </div>
          <el-alert v-if="qualityQueueError && qualityQueueRecords.length" :title="qualityQueueError" type="warning" show-icon :closable="false" class="quality-queue-read-error" />

          <TableReadHint v-if="qualityQueueRecords.length" />
          <el-table :scrollbar-tabindex="0" role="region" aria-label="当前质检队列"
            v-loading="qualityQueueLoading"
            :data="qualityQueueRecords"
            size="small"
            border
            class="quality-queue-table"
          >
            <template #empty>
              <CollectionEmptyState :loading="qualityQueueLoading || (!qualityQueueLoaded && !qualityQueueError)" :error="qualityQueueError" :filtered="activeQualityQueue !== 'ALL_ACTIONABLE'" empty-title="当前队列暂无待处理任务" empty-description="检测完成后可在待复核阶段查看；放行与报告审批分别处理。" @retry="loadQualityQueue()" @reset="switchQualityQueue('ALL_ACTIONABLE')" />
            </template>
            <el-table-column label="任务与来源" min-width="215"><template #default="{ row }"><div class="quality-queue-task"><button type="button" @click="openTraceDialog(row.taskId)">{{ row.taskId }}</button><span>工单 {{ row.workOrderNo || '未记录' }}</span><span>批次 {{ row.batchNo || '未记录' }}</span><small>设备 {{ row.deviceName || '未记录' }}</small></div></template></el-table-column>
            <el-table-column label="流转" min-width="130">
              <template #default="{ row }"><StatusBadge domain="flow" :code="row.flowStatus" :label="flowStatusText(row.flowStatus)" /></template>
            </el-table-column>
            <el-table-column label="复核" min-width="115">
              <template #default="{ row }">
                <StatusBadge domain="review" :code="row.reviewStatus" :label="reviewStatusText(row.reviewStatus)" />
              </template>
            </el-table-column>
            <el-table-column label="缺陷" width="90">
              <template #default="{ row }">{{ traceCount(row.defectCount) }}</template>
            </el-table-column>
            <el-table-column label="等级" width="100">
              <template #default="{ row }">
                <el-tag :type="severityTagType(row.severityLevel || row.maxDefectSeverity)" effect="plain">
                  {{ severityText(row.severityLevel || row.maxDefectSeverity) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="责任与截止" min-width="180">
              <template #default="{ row }"><div class="quality-queue-responsibility"><strong>{{ row.assignee || '未分派' }}</strong><span>{{ row.dueAt ? formatBusinessTime(row.dueAt) || '时间格式未知' : '未设置截止时间' }}</span><small v-if="row.dueAt">北京时间 UTC+8</small></div></template>
            </el-table-column>
            <el-table-column label="下一步" min-width="235"><template #default="{ row }"><QualityStageGuidance :task="row" /></template></el-table-column>
            <el-table-column label="操作" width="330" fixed="right">
              <template #default="{ row }">
                <el-button link size="small" type="primary" @click="openTraceDialog(row.taskId)">追溯</el-button>
                <el-button link size="small" type="info" :disabled="reportDownloading" @click="downloadTaskQualityReport(row.taskId)">任务摘要</el-button>
                <el-tooltip v-if="userStore.role === 'SUPERVISOR'" :content="canAssignQualityTask(row) ? '选择责任人并确认分派' : qualityActionReason(row,'ASSIGN')" placement="top"><span><el-button link size="small" type="info" :disabled="!canAssignQualityTask(row)" @click="openAssignmentDialog(row)"><AppIcon name="User" :size="14" />分派</el-button></span></el-tooltip>
                <el-button
                  v-if="canReviewTask(row)"
                  link
                  size="small"
                  type="success"
                  @click="openReviewDialog(row)"
                >
                  复核
                </el-button>
                <el-button
                  v-if="canDisposeTask(row)"
                  link
                  size="small"
                  type="warning"
                  @click="openDispositionDialog(row)"
                >
                  处置
                </el-button>
                <el-button
                  v-if="canSubmitReworkResult(row)"
                  link
                  size="small"
                  type="primary"
                  @click="openReworkDialog(row)"
                >
                  返工
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <p class="quality-queue-scope">任务摘要是当前记录导出，正式报告仍需在“报告与审批”独立核对。</p>
          <div v-if="qualityQueueTotal !== null" class="quality-pagination">
            <el-pagination
              v-model:current-page="qualityQueuePage"
              v-model:page-size="qualityQueuePageSize"
              :total="qualityQueueTotal"
              :page-sizes="[10, 20, 50]"
              layout="total, sizes, prev, pager, next"
              @current-change="loadQualityQueue"
              @size-change="onQualityQueueSizeChange"
            />
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane name="defect-gallery" label="缺陷证据库">
        <el-card class="detection-card defect-gallery-card" shadow="never">
          <template #header>
            <div class="card-title-row">
              <span><AppIcon name="Picture" :size="18" />缺陷证据库</span>
              <el-tag type="info" effect="plain">{{ defectGalleryLoading ? '读取中' : defectGalleryError ? '数量待核对' : defectGalleryTotal === null ? '数量尚未读取' : defectGalleryTotal+' 条缺陷任务' }}</el-tag>
              <el-button size="small" :loading="defectGalleryLoading" @click="loadDefectGallery()">
                <el-icon><Refresh /></el-icon>
                刷新
              </el-button>
            </div>
          </template>

          <p class="defect-gallery-scope"><AppIcon name="Lock" :size="15" />{{ userStore.role === 'SUPERVISOR' ? '企业业务范围' : userStore.role === 'INSPECTOR' ? '本人及分派任务' : '当前账号有权访问的范围' }} · 每张卡片对应一个缺陷任务。检测证据条目与人工确认数量分别记录，预览图不代替人工复核。</p>
          <form class="defect-filter-bar" @submit.prevent="searchDefectGallery">
            <label for="defect-type-filter">主要缺陷类型<el-input id="defect-type-filter" v-model="defectFilters.defectType" placeholder="输入类别名，如 Rusty" clearable /></label>
            <label for="defect-severity-filter">严重等级<el-select id="defect-severity-filter" v-model="defectFilters.severityLevel" placeholder="全部等级" clearable>
              <el-option label="轻微 MINOR" value="MINOR" />
              <el-option label="一般 MAJOR" value="MAJOR" />
              <el-option label="严重 CRITICAL" value="CRITICAL" />
            </el-select></label>
            <label for="defect-device-filter">设备名称<el-input id="defect-device-filter" v-model="defectFilters.deviceName" placeholder="输入采集设备名称" clearable /></label>
            <label for="defect-batch-filter">批次编号<el-input id="defect-batch-filter" v-model="defectFilters.batchNo" placeholder="输入批次编号" clearable /></label>
            <label for="defect-model-filter">检测模型编号<el-input-number id="defect-model-filter" v-model="defectFilters.modelId" :min="1" :precision="0" placeholder="模型编号" controls-position="right" /></label>
            <div class="defect-filter-actions"><el-button type="primary" native-type="submit" :loading="defectGalleryLoading">
              <el-icon><Search /></el-icon>
              查询
            </el-button>
            <el-button @click="resetDefectGalleryFilters"><AppIcon name="Refresh" :size="16" />重置</el-button></div>
          </form>
          <p v-if="defectFiltersDirty && defectGalleryRecords.length" class="defect-gallery-filter-note" role="status">筛选条件已修改，当前仍为上次读取的结果。点击查询或刷新后更新，再进行翻页。</p>

          <el-alert v-if="defectGalleryError && defectGalleryRecords.length" :title="defectGalleryError + '；下方保留先前读取的记录，请刷新核对。'" type="error" show-icon :closable="false" />
          <CollectionEmptyState v-if="!defectGalleryRecords.length" :loading="defectGalleryLoading" :error="defectGalleryError" :filtered="hasDefectFilters" empty-title="暂无缺陷证据" empty-description="检测后，可在这里查找缺陷任务，并通过追溯详情对照图片与人工结论。" @retry="loadDefectGallery()" @reset="resetDefectGalleryFilters" />

          <div v-else v-loading="defectGalleryLoading" class="defect-gallery-grid">
            <article v-for="task in defectGalleryRecords" :key="task.taskId" class="defect-evidence-card" :aria-label="'缺陷任务 '+task.taskId">
              <div class="defect-card-image">
                <button v-if="resolveDefectPreview(task)" class="defect-preview-button" type="button" :aria-label="'查看任务 '+task.taskId+' 的图片对照'" @click="openTraceDialog(task.taskId)"><el-image :src="resolveDefectPreview(task)" :alt="'任务 '+task.taskId+' 证据预览'" fit="contain" loading="lazy"><template #error><div class="defect-preview-empty"><AppIcon name="Warning" :size="23" /><span>图片暂不可读取，可进入详情核对</span></div></template></el-image><span class="defect-preview-caption"><AppIcon name="Search" :size="14" />查看图片对照</span></button>
                <div v-else class="preview-empty"><AppIcon name="Picture" :size="24" /><span>本次未读取到可用预览</span></div>
              </div>
              <div class="defect-card-body">
                <header class="defect-card-identity"><span>缺陷任务</span><button type="button" :aria-label="'查看缺陷任务 '+task.taskId" @click="openTraceDialog(task.taskId)">{{ task.taskId }}</button><StatusBadge domain="detection" :code="task.status" /></header>
                <section class="defect-card-section" aria-label="检测记录">
                  <h4><AppIcon name="Picture" :size="15" />检测记录</h4>
                  <dl class="defect-card-facts"><div><dt>主要缺陷</dt><dd>{{ task.primaryDefectType ? getCategoryText(task.primaryDefectType) : '未记录' }}<small v-if="task.primaryDefectType && getCategoryText(task.primaryDefectType)!==task.primaryDefectType">{{ task.primaryDefectType }}</small></dd></div><div><dt>检测证据条目</dt><dd>{{ traceCount(task.defectCount) }} 条</dd></div><div class="defect-fact-wide"><dt>检测记录最高等级</dt><dd><StatusBadge domain="severity" :code="task.maxDefectSeverity" :label="task.maxDefectSeverity ? severityText(task.maxDefectSeverity) : '等级未记录'" /></dd></div></dl>
                </section>
                <section class="defect-card-section" aria-label="人工复核记录">
                  <h4><AppIcon name="Search" :size="15" />人工复核<StatusBadge domain="review" :code="task.reviewStatus" :label="task.reviewStatus ? reviewStatusText(task.reviewStatus) : '复核状态未记录'" /></h4>
                  <dl v-if="task.reviewStatus==='REVIEWED'" class="defect-card-facts"><div class="defect-fact-wide"><dt>复核结论</dt><dd><StatusBadge domain="reviewConclusion" :code="task.reviewConclusion" /></dd></div><div><dt>人工确认缺陷</dt><dd>{{ traceCount(task.confirmedDefectCount) }} 个</dd></div><div><dt>误报反馈</dt><dd>{{ traceCount(task.falsePositiveCount) }} 个</dd></div><div class="defect-fact-wide"><dt>人工评定等级</dt><dd><StatusBadge domain="severity" :code="task.severityLevel" /></dd></div></dl>
                  <p v-if="task.reviewStatus==='REVIEWED'" class="defect-card-note">复核时间：{{ task.reviewedAt ? displayBusinessTime(task.reviewedAt)+' UTC+8' : '未记录' }}</p>
                  <p v-else class="defect-card-note">{{ ['PENDING','REVIEWING'].includes(task.reviewStatus) ? '等待人工复核完成，检测记录不代替人工结论。' : '当前复核状态及结论请在追溯详情中核对。' }}</p>
                </section>
                <dl class="defect-card-responsibility"><div><dt>责任人</dt><dd>{{ task.assignee || '未记录' }}</dd></div><div><dt>截止（UTC+8）</dt><dd>{{ task.dueAt ? displayBusinessTime(task.dueAt) : '未记录' }}</dd></div></dl>
                <details class="defect-card-disclosure"><summary>任务来源<AppIcon name="ArrowDown" :size="13" /></summary><dl class="defect-card-facts"><div class="defect-fact-wide"><dt>采集设备</dt><dd>{{ task.deviceName || '未记录' }}</dd></div><div class="defect-fact-wide"><dt>批次编号</dt><dd>{{ task.batchNo || '未记录' }}</dd></div><div class="defect-fact-wide"><dt>工单编号</dt><dd>{{ task.workOrderNo || '未记录' }}</dd></div></dl></details>
                <details v-if="Array.isArray(task.defectEvidence) && task.defectEvidence.length" class="defect-card-disclosure"><summary>本次返回证据 {{ task.defectEvidence.length.toLocaleString('zh-CN') }} 条<AppIcon name="ArrowDown" :size="13" /></summary><p class="defect-card-note">以下显示前 {{ Math.min(task.defectEvidence.length,3) }} 条摘录，置信度为模型记录，不代表人工确认。</p><ol class="defect-evidence-excerpts"><li v-for="(evidence,evidenceIndex) in task.defectEvidence.slice(0,3)" :key="evidenceIndex"><strong>{{ evidence.imageName || '图片名称未记录' }}</strong><span>{{ evidence.defectType ? getCategoryText(evidence.defectType) : '类型未记录' }} · 模型置信度 {{ formatEvidenceConfidence(evidence.confidence) }}</span></li></ol></details>
                <QualityStageGuidance :task="task" />
                <div class="defect-card-actions">
                  <el-button size="small" type="primary" plain @click="openTraceDialog(task.taskId)"><AppIcon name="Search" :size="15" />追溯详情</el-button>
                  <el-button size="small" plain :disabled="reportDownloading" @click="downloadTaskQualityReport(task.taskId)"><AppIcon name="Download" :size="15" />任务摘要</el-button>
                  <el-tooltip :content="canReviewTask(task) ? '核对图片与结论后提交人工复核' : qualityActionReason(task,'REVIEW')" placement="top"><span :tabindex="canReviewTask(task) ? undefined : 0" :aria-label="canReviewTask(task) ? undefined : qualityActionReason(task,'REVIEW')"><el-button
                    :disabled="!canReviewTask(task)"
                    size="small"
                    type="warning"
                    plain
                    @click="openReviewDialog(normalizeQualityQueueRecord(task))"
                  >
                    复核
                  </el-button></span></el-tooltip>
                </div>
              </div>
            </article>
          </div>

          <div v-if="defectGalleryTotal!==null" class="quality-pagination">
            <el-pagination
              v-model:current-page="defectGalleryPage"
              v-model:page-size="defectGalleryPageSize"
              :total="defectGalleryTotal"
              :page-sizes="[8, 12, 24]"
              :disabled="defectGalleryLoading || defectFiltersDirty || !!defectGalleryError"
              layout="total, sizes, prev, pager, next"
              @current-change="loadDefectGallery"
              @size-change="onDefectGallerySizeChange"
            />
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane name="work-order-trace" label="工单追溯">
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
                title="导出当前已读工单摘要（JSON），不重新查询"
                @click="downloadWorkOrderTraceReport"
              >
                <el-icon><Download /></el-icon>
                导出已读工单摘要
              </el-button>
            </div>
          </template>

          <BusinessTraceQuery v-model="workOrderTraceNo" kind="work-order" :requested-no="workOrderTraceRequestedNo" :loading="workOrderTraceLoading" :report="workOrderTraceReport" :error="workOrderTraceError" :examples="businessWorkOrderNos" :scope-label="businessTraceScope" @query="loadWorkOrderTraceReport" @refresh="refreshWorkOrderTraceReport" @example="loadBusinessWorkOrderTrace" />

          <TraceReportOverview v-if="workOrderTraceReport" :report="workOrderTraceReport" kind="work-order" :report-downloading="reportDownloading" @open-trace="openTraceDialog" @download-task="downloadTaskQualityReport" />
        </el-card>
      </el-tab-pane>

      <el-tab-pane name="batch-trace" label="批次追溯">
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
                title="导出当前已读批次摘要（JSON），不重新查询"
                @click="downloadBatchTraceReport"
              >
                <el-icon><Download /></el-icon>
                导出已读批次摘要
              </el-button>
            </div>
          </template>

          <BusinessTraceQuery v-model="batchTraceNo" kind="batch" :requested-no="batchTraceRequestedNo" :loading="batchTraceLoading" :report="batchTraceReport" :error="batchTraceError" :examples="businessBatchNos" :scope-label="businessTraceScope" @query="loadBatchTraceReport" @refresh="refreshBatchTraceReport" @example="loadBusinessBatchTrace" />

          <TraceReportOverview v-if="batchTraceReport" :report="batchTraceReport" kind="batch" :report-downloading="reportDownloading" @open-trace="openTraceDialog" @download-task="downloadTaskQualityReport" />
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="reviewDialogVisible" class="quality-operation-dialog" title="人工复核" width="min(1100px, 96vw)" :close-on-click-modal="!reviewSubmitting" :close-on-press-escape="!reviewSubmitting" :show-close="!reviewSubmitting">
      <QualityTaskContext :task="reviewTask" operation="review" />
      <div class="quality-review-layout" :class="{ 'has-evidence': reviewEvidence.originals.length || reviewEvidence.annotations.length }">
      <EvidenceComparison v-if="reviewEvidence.originals.length || reviewEvidence.annotations.length" :task-id="reviewTask?.taskId" :originals="reviewEvidence.originals" :annotations="reviewEvidence.annotations" />
      <p v-else class="quality-feedback-note"><AppIcon name="Picture" :size="16" />当前未读取到可对照图片，请先查看任务追溯并核对原始资料。</p>
      <el-form :model="reviewForm" label-position="top" :disabled="reviewSubmitting||qualityActionAcknowledged.review">
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
            aria-label="记录缺陷位置、人工判断依据或误报原因" placeholder="记录缺陷位置、人工判断依据或误报原因"
          />
        </el-form-item>
      </el-form>
      </div>
      <el-alert v-if="qualityActionErrors.review" :title="qualityActionErrors.review" type="warning" show-icon :closable="false" />
      <p v-if="!canReviewTask(reviewTask)" class="quality-feedback-note">{{ qualityActionReason(reviewTask,'REVIEW') }}</p>
      <template #footer>
        <el-button :disabled="reviewSubmitting" @click="reviewDialogVisible = false"><AppIcon name="Close" :size="16" />取消</el-button>
        <el-button :disabled="reviewSubmitting||!reviewTask?.taskId" @click="openTraceDialog(reviewTask.taskId)"><AppIcon name="Search" :size="15" />核对任务依据</el-button>
        <el-button type="primary" :loading="reviewSubmitting" :disabled="qualityActionAcknowledged.review||!canReviewTask(reviewTask)" @click="submitTaskReview"><AppIcon name="DocumentChecked" :size="15" />提交复核</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="assignmentDialogVisible" class="quality-operation-dialog" title="分派质检任务" width="min(640px, 96vw)" :close-on-click-modal="!assignmentSubmitting" :close-on-press-escape="!assignmentSubmitting" :show-close="!assignmentSubmitting">
      <QualityTaskContext :task="assignmentTask" operation="assignment" />
      <el-form :model="assignmentForm" label-position="top" :disabled="assignmentSubmitting||qualityActionAcknowledged.assignment">
        <el-form-item label="质检站点">
          <el-input v-model="assignmentForm.qualityStation" aria-label="例如：质检站-1 / 产线A复核位" placeholder="例如：质检站-1 / 产线A复核位" />
        </el-form-item>
        <el-form-item label="责任人">
          <QualityAssigneePicker v-model="assignmentForm.assignee" v-model:user-id="assignmentForm.assigneeUserId" v-model:revision="assignmentForm.assigneeRevision" :disabled="assignmentSubmitting||qualityActionAcknowledged.assignment" />
        </el-form-item>
        <el-form-item label="截止时间 · UTC+8">
          <el-date-picker
            v-model="assignmentForm.dueAt"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            format="YYYY-MM-DD HH:mm"
            aria-label="选择质检截止时间，北京时间 UTC+8" placeholder="选择质检截止时间（UTC+8）"
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
        <el-button :disabled="assignmentSubmitting" @click="assignmentDialogVisible = false"><AppIcon name="Close" :size="16" />取消</el-button>
        <el-button v-if="qualityActionErrors.assignment" :disabled="assignmentSubmitting" @click="openTraceDialog(assignmentTask.taskId)"><AppIcon name="Search" :size="15" />核对任务状态</el-button>
        <el-button type="primary" :loading="assignmentSubmitting" :disabled="qualityActionAcknowledged.assignment||!canAssignQualityTask(assignmentTask)" @click="submitQualityAssignment"><AppIcon name="User" :size="15" />确认分派</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dispositionDialogVisible" class="quality-operation-dialog" title="质检处置" width="min(640px, 96vw)" :close-on-click-modal="!dispositionSubmitting" :close-on-press-escape="!dispositionSubmitting" :show-close="!dispositionSubmitting">
      <QualityTaskContext :task="dispositionTask" operation="disposition" />
      <el-form :model="dispositionForm" label-position="top" :disabled="dispositionSubmitting||qualityActionAcknowledged.disposition">
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
        <el-button :disabled="dispositionSubmitting" @click="dispositionDialogVisible = false"><AppIcon name="Close" :size="16" />取消</el-button>
        <el-button v-if="qualityActionErrors.disposition" :disabled="dispositionSubmitting" @click="openTraceDialog(dispositionTask.taskId)"><AppIcon name="Search" :size="15" />核对任务状态</el-button>
        <el-button :type="dispositionForm.dispositionAction==='SCRAP'?'danger':'primary'" :loading="dispositionSubmitting" :disabled="qualityActionAcknowledged.disposition||!canDisposeTask(dispositionTask)" @click="submitTaskDisposition"><AppIcon name="DocumentChecked" :size="15" />{{ dispositionForm.dispositionAction==='SCRAP'?'确认报废隔离':dispositionForm.dispositionAction==='RELEASE'?'确认正常放行':'提交处置' }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="reworkDialogVisible" class="quality-operation-dialog" title="返工结果回填" width="min(640px, 96vw)" :close-on-click-modal="!reworkSubmitting" :close-on-press-escape="!reworkSubmitting" :show-close="!reworkSubmitting">
      <QualityTaskContext :task="reworkTask" operation="rework" />
      <el-form :model="reworkForm" label-position="top" :disabled="reworkSubmitting||qualityActionAcknowledged.rework">
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
        <el-button :disabled="reworkSubmitting" @click="reworkDialogVisible = false"><AppIcon name="Close" :size="16" />取消</el-button>
        <el-button v-if="qualityActionErrors.rework" :disabled="reworkSubmitting" @click="openTraceDialog(reworkTask.taskId)"><AppIcon name="Search" :size="15" />核对任务状态</el-button>
        <el-button type="primary" :loading="reworkSubmitting" :disabled="qualityActionAcknowledged.rework||!canSubmitReworkResult(reworkTask)" @click="submitTaskRework"><AppIcon name="DocumentChecked" :size="15" />提交返工结果</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="traceDialogVisible" class="task-trace-dialog" title="任务追溯详情" width="min(1100px, 96vw)" append-to-body>
      <TaskTracePanel ref="tracePanel" :detail="traceDetail" :loading="traceLoading" :error="traceError" @refresh="openTraceDialog(traceRequestedId)" />
      <template #footer><div class="task-trace-footer"><span role="status">{{ traceLoading ? traceDetail ? '正在重新读取，保留上次资料' : '正在读取任务资料' : traceError ? traceDetail ? '读取未成功，仍为上次资料' : '任务详情尚未读取成功' : traceDetail ? '本次已读任务资料' : '尚未读取' }}</span><div><el-button v-if="traceDetail" text @click="tracePanel?.showOverview()">回到概览</el-button><el-button :loading="traceLoading" :disabled="!traceRequestedId || reportDownloading" @click="openTraceDialog(traceRequestedId)"><AppIcon name="Refresh" :size="15" />重新读取</el-button><el-button @click="traceDialogVisible = false">关闭</el-button><el-button v-if="traceDetail?.taskId" type="primary" :loading="reportDownloading" :disabled="traceLoading" @click="downloadTaskQualityReport(traceDetail.taskId)"><AppIcon name="Download" :size="15" />导出任务摘要</el-button></div></div></template>
    </el-dialog>
  </div>
</template>

<script setup>
import QualityAssigneePicker from '@/components/QualityAssigneePicker.vue'
import QualityStageGuidance from '@/components/QualityStageGuidance.vue'
import QualityTaskContext from '@/components/QualityTaskContext.vue'
import EvidenceComparison from '@/components/EvidenceComparison.vue'
import TraceReportOverview from '@/components/TraceReportOverview.vue'
import BusinessTraceQuery from '@/components/BusinessTraceQuery.vue'
import DetectionHistoryCard from '@/components/DetectionHistoryCard.vue'
import { knownCount } from '@/utils/countPresentation'
import { useUserStore } from '../stores/user'
import { beijingDateTime as formatBusinessTime } from '../utils/beijingTime'
import { detectionPresentation } from '../utils/pagePresentation'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Delete, Download, Refresh, Search, Upload, VideoPlay, Warning } from '@element-plus/icons-vue'
import {
  fetchAvailableModels,
  fetchDetectionTaskTrace,
} from '../api/detection'
import { detectSingleImageViaKafka } from '../services/singleImageKafkaDetection'
import { useTaskStore, useUploadStore, usePollingStore, CATEGORY_LABELS, CATEGORY_COLORS, CATEGORY_ALIASES } from '../stores/detectionTask'
import { useSingleImageUploadPreview } from '../composables/useSingleImageUploadPreview'
import {
  canAssignQualityTask,
  canDisposeTask,
  canReleaseDisposition,
  canReviewTask,
  canSubmitReworkResult,
  qualityActionReason,
  dispositionActionText,
  dispositionStatusText,
  flowStatusText,
  reviewConclusionText,
  reviewStatusTagType,
  reviewStatusText,
  severityTagType,
  severityText
} from '../utils/qualityWorkflow'
import {
  formatEvidenceConfidence,
  normalizeQualityQueueRecord,
  resolveDefectPreview
} from '../utils/qualityRecords'
import { useQualityTaskActions } from '../composables/useQualityTaskActions'
import { useQualityQueue } from '../composables/useQualityQueue'
import { useDefectGallery } from '../composables/useDefectGallery'
import { useTraceReports } from '../composables/useTraceReports'
import { useDetectionHistory } from '../composables/useDetectionHistory'
import { useQualityReportDownloads } from '../composables/useQualityReportDownloads'
import CollectionEmptyState from '../components/CollectionEmptyState.vue'
import TaskTracePanel from '../components/TaskTracePanel.vue'
import SingleDetectionEvidence from '../components/SingleDetectionEvidence.vue'
import TaskExecutionProgress from '../components/TaskExecutionProgress.vue'
import TaskResultSnapshot from '../components/TaskResultSnapshot.vue'
import {taskExecutionCode,taskExecutionLogs} from '../utils/taskExecutionPresentation'
import '@/assets/task-trace-dialog.css'

const userStore = useUserStore()
const businessTraceScope = computed(() => userStore.role === 'SUPERVISOR' ? '企业业务范围' : userStore.role === 'INSPECTOR' ? '本人及分派任务' : '当前账号有权查看的业务范围')
const taskStore = useTaskStore()
const uploadStore = useUploadStore()
const pollingStore = usePollingStore()
const { taskList, selectedTaskId } = storeToRefs(taskStore)
const {
  removeTask, saveTaskList
} = taskStore
const { startTaskDetection, stopAllPolling, restoreFromSession, fetchTaskList, fetchTaskResults } = pollingStore
const {
  activeQualityQueue,
  qualityQueueLoading,
  qualityQueueRecords,
  qualityQueueTotal,
  qualityQueueError,
  qualityQueueLoaded,
  qualityQueuePage,
  qualityQueuePageSize,
  qualityQueues,
  loadQualityQueue,
  switchQualityQueue,
  onQualityQueueSizeChange
} = useQualityQueue()
const {
  defectGalleryLoading,
  defectGalleryError,
  hasDefectFilters,
  defectFiltersDirty,
  defectGalleryRecords,
  defectGalleryTotal,
  defectGalleryPage,
  defectGalleryPageSize,
  defectFilters,
  loadDefectGallery,
  searchDefectGallery,
  resetDefectGalleryFilters,
  onDefectGallerySizeChange
} = useDefectGallery()
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
  ensureDefaultWorkOrderNo,
  ensureDefaultBatchNo,
  loadWorkOrderTraceReport,
  loadBatchTraceReport,
  refreshWorkOrderTraceReport,
  workOrderTraceRequestedNo,
  refreshBatchTraceReport,
  batchTraceRequestedNo,
  loadBusinessWorkOrderTrace,
  loadBusinessBatchTrace
} = useTraceReports({ getAccountScope: () => [userStore.identity?.userId || userStore.username || '', userStore.role, userStore.isAuthenticated] })
const {
  historySearchKeyword,
  historyFilterCollector,
  historyFilterDevice,
  historyFilterRegion,
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
  onHistoryPageChange,
  onHistorySizeChange,
  refreshHistory,
  retryHistoryRead
} = useDetectionHistory(taskStore, pollingStore)
const historyAppliedDescription = computed(() => Object.entries(historyAppliedFilters.value).map(([key,value]) => `${({keyword:'关键词',collector:'采集人员',deviceName:'设备名称',region:'采集区域'})[key] || key}：${value}`).join(' · ') || '全部条件')
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
let modelReadVersion = 0, singleRunVersion = 0, taskReadVersion = 0, detectionPageActive = true
const refreshingTasks = ref(false), taskReadLoaded = ref(false), taskReadError = ref('')
const detectionResult = ref(null)
const annotatedImageUrl = ref('')
const loadingSingle = ref(false)
const singleDetectionTaskId = ref('')
const singleDetectionStage = ref('IDLE')
const singleDetectionMessage = ref('')
const singleSubmission = ref(null)
const singleStageCode = computed(() => singleDetectionStage.value === 'IDLE' && form.imageFile ? 'READY' : String(singleDetectionStage.value || 'IDLE').toUpperCase())
const taskFilter = ref('all')
const taskSearchKeyword = ref('')
const taskFilterDate = ref('')
const taskKeywordInput = ref(null)
const hasTaskFilters = computed(()=>!!(taskSearchKeyword.value.trim() || taskFilterDate.value || taskFilter.value!=='all'))
const clearTaskFilters = (restoreFocus=false)=>{
  taskSearchKeyword.value='';taskFilterDate.value='';taskFilter.value='all'
  if(restoreFocus){const version=taskReadVersion;nextTick(()=>{if(detectionPageActive && version===taskReadVersion)taskKeywordInput.value?.input?.focus({preventScroll:true})})}
}
const traceDialogVisible = ref(false)
const traceLoading = ref(false)
const traceDetail = ref(null)
const traceError = ref(''), traceRequestedId = ref(''), tracePanel = ref(null)
let traceGeneration = 0, traceReadController
watch(traceDialogVisible, open => { if (!open) { traceGeneration++; traceReadController?.abort(); traceReadController = null; traceLoading.value = false } }, { flush:'sync' })
const displayBusinessTime = value => value ? formatBusinessTime(value) || '时间格式未知' : '未记录'
const route = useRoute()
watch(() => JSON.stringify([userStore.identity?.userId || userStore.username || '', userStore.role, userStore.isAuthenticated]), () => { traceGeneration++; traceReadController?.abort(); traceReadController = null; traceDetail.value = null; traceRequestedId.value = ''; traceError.value = ''; traceLoading.value = false; traceDialogVisible.value = false }, { flush: 'sync' })
const router = useRouter()
const activeTab = ref('workspace')
const workspacePresentation = computed(() => detectionPresentation[activeTab.value] || detectionPresentation.workspace)
const validTabs = ['workspace', 'history', 'quality', 'defect-gallery', 'work-order-trace', 'batch-trace']
const tabRouteMap = {
  workspace: '/inspection/workbench',
  history: '/inspection/history',
  quality: '/quality/queue',
  'defect-gallery': '/quality/evidence',
  'work-order-trace': '/quality/work-order-trace',
  'batch-trace': '/quality/batch-trace'
}
const form = reactive({
  modelId: null,
  threshold: 0.5,
  imageFile: null
})
const selectedDetectionModel = computed(()=>modelList.value.find(model=>model.modelId===form.modelId))

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
      return date && formatBusinessTime(date).startsWith(taskFilterDate.value)
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

const traceCount = value => knownCount(value)?.toLocaleString('zh-CN') ?? '—'

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

const handleTabChange = async (tabName, { fromRoute = false } = {}) => {
  const startingRoute = route.fullPath
  if (tabName === 'quality' && !qualityQueueRecords.value.length) {
    await loadQualityQueue(1)
  }
  if (tabName === 'defect-gallery' && !defectGalleryRecords.value.length) {
    await loadDefectGallery(1)
  }
  if (tabName === 'work-order-trace' && !workOrderTraceReport.value && !workOrderTraceLoading.value) {
    ensureDefaultWorkOrderNo()
    await loadWorkOrderTraceReport()
  }
  if (tabName === 'batch-trace' && !batchTraceReport.value && !batchTraceLoading.value) {
    ensureDefaultBatchNo()
    await loadBatchTraceReport()
  }
  const targetPath = tabRouteMap[tabName]
  if (!fromRoute && targetPath && route.path !== targetPath && route.fullPath === startingRoute) {
    const { tab, ...query } = route.query
    if (tabName !== 'history') delete query.keyword
    if (tabName !== 'work-order-trace') delete query.workOrderNo
    if (!['batch-trace','defect-gallery'].includes(tabName)) delete query.batchNo
    router.replace({ path: targetPath, query })
  }
}

const syncTabFromRoute = async () => {
  const text = value => typeof value === 'string' ? value.trim() : ''
  const routeKeyword = text(route.query.keyword)
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
  if (routeTab === 'history' && routeKeyword) {
    historySearchKeyword.value = routeKeyword
    historyPage.value = 1
    await fetchHistoryWithFilters(1)
    return
  }
  if (changed) await handleTabChange(routeTab, { fromRoute:true })
}

watch(
  () => [route.path, route.query.tab, route.query.queue, route.query.workOrderNo, route.query.batchNo, route.query.keyword],
  () => {
    const requestedQueue = String(route.query.queue || '')
    if (qualityQueues.some(queue => queue.value === requestedQueue) && activeQualityQueue.value !== requestedQueue) {
      activeQualityQueue.value = requestedQueue
      if (activeTab.value === 'quality') loadQualityQueue(1)
    }
    syncTabFromRoute()
  }
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
    singleDetectionTaskId.value = ''
    singleDetectionStage.value = 'IDLE'
    singleDetectionMessage.value = ''
    singleSubmission.value = null
  }
})

watch(() => JSON.stringify([userStore.identity?.userId || userStore.username || '', userStore.role, userStore.isAuthenticated]), () => {
  singleRunVersion++
  loadingSingle.value = false
  handleRemove()
  form.modelId = null
  modelReadVersion++
  modelList.value = []
  modelsLoading.value = false
  modelsLoaded.value = false
  modelsError.value = '账号或权限已变化，请重新读取模型目录'
  taskReadVersion++
  refreshingTasks.value=false;taskReadLoaded.value=false;taskReadError.value='账号或权限已变化，请重新读取任务列表'
  clearTaskFilters()
  singleDetectionMessage.value = '已清除本页原图与结果，原任务请到当前账号有权查看的检测记录核对。'
}, { flush:'sync' })

const handleSingleDetection = async () => {
  if (loadingSingle.value || singleStageCode.value === 'UNCONFIRMED') return
  if (!form.imageFile) {
    ElMessage.error('请先选择图片')
    return
  }

  loadingSingle.value = true
  const runVersion = ++singleRunVersion
  const file = form.imageFile, modelId = form.modelId, threshold = form.threshold
  const model = modelList.value.find(row => row.modelId === modelId)
  singleSubmission.value = {fileName:file.name,threshold,modelLabel:modelId ? `${model?.modelName || '模型'} · #${modelId}${model?.version ? ' · '+model.version : ''}` : '由服务端选择，实际以任务记录为准'}
  detectionResult.value = null
  annotatedImageUrl.value = ''
  singleDetectionTaskId.value = ''
  singleDetectionStage.value = 'CREATING'
  singleDetectionMessage.value = '正在登记单图检测任务'

  try {
    const result = await detectSingleImageViaKafka({
      file, modelId, threshold,
      onStatus: ({ taskId, stage, message }) => {
        if (!detectionPageActive || runVersion !== singleRunVersion) return
        singleDetectionTaskId.value = taskId || singleDetectionTaskId.value
        singleDetectionStage.value = stage || singleDetectionStage.value
        singleDetectionMessage.value = message || singleDetectionMessage.value
      }
    })
    if (!detectionPageActive || runVersion !== singleRunVersion) return
    detectionResult.value = result
    annotatedImageUrl.value = result.annotatedImagePath
    singleDetectionTaskId.value = result.taskId
    singleDetectionStage.value = result.status === 'PARTIAL_FAILED' ? 'PARTIAL_FAILED' : 'COMPLETED'
    singleDetectionMessage.value = result.status === 'PARTIAL_FAILED' ? '检测返回部分失败，请核对任务记录' : '单图检测结果已返回，人工复核与报告审批仍需分别完成'
    if (result.status === 'PARTIAL_FAILED') ElMessage.warning('检测结果包含失败项，请核对任务')
    else ElMessage.success('单图检测结果已返回')
  } catch (error) {
    if (!detectionPageActive || runVersion !== singleRunVersion) return
    singleDetectionStage.value = error.taskFailed === true ? 'FAILED' : 'UNCONFIRMED'
    singleDetectionMessage.value = error.message || '单图检测提交或结果尚未核对'
  } finally {
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
  if (!detectionPageActive) return
  const readVersion = ++modelReadVersion
  modelsLoading.value = true
  modelsError.value = ''
  try {
    const response = await fetchAvailableModels()
    if (!detectionPageActive || readVersion !== modelReadVersion) return
    const rows = response.data?.data
    if (response.data?.code !== 200 || !Array.isArray(rows) || rows.some(row => !Number.isSafeInteger(row?.modelId) || row.modelId < 1)) throw new Error('模型目录返回内容不完整')
    modelList.value = rows
    modelsLoaded.value = true
  } catch (error) {
    if (!detectionPageActive || readVersion !== modelReadVersion) return
    if ([401,403].includes(error.response?.status)) { modelList.value = []; modelsLoaded.value = false }
    modelsError.value = '模型目录暂不可读取；未指定模型时仍由服务端按原配置选择，请核对任务记录。'
  } finally { if (detectionPageActive && readVersion === modelReadVersion) modelsLoading.value = false }
}
const detectionModelOptionLabel = model => `${model.modelName || '未命名模型'}${model.version ? ' · '+model.version : ''} · #${model.modelId}`

// ==================== 生命周期 ====================

const readWorkbenchTasks = async (notify=false) => {
  if(!detectionPageActive || refreshingTasks.value || !userStore.isAuthenticated)return false
  const version=++taskReadVersion,actor=JSON.stringify([userStore.identity?.userId || userStore.username || '',userStore.role,userStore.isAuthenticated])
  const current=()=>detectionPageActive && version===taskReadVersion && actor===JSON.stringify([userStore.identity?.userId || userStore.username || '',userStore.role,userStore.isAuthenticated])
  refreshingTasks.value = true
  taskReadError.value=''
  try {
    const result=await fetchTaskList()
    if(!current())return false
    if(!result?.ok)throw new Error(result?.message || '任务记录暂不可读取')
    taskReadLoaded.value=true
    if(notify)ElMessage.success('任务记录已读取并合并到当前清单')
    return true
  } catch (e) {
    if(current())taskReadError.value=e.message || '任务记录暂不可读取'
    return false
  } finally {
    if(current())refreshingTasks.value = false
  }
}
const refreshTaskList = ()=>readWorkbenchTasks(true)

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
  refreshQualityQueue: refreshQualityQueueIfVisible,
  refreshDefectGallery: refreshDefectGalleryIfVisible
})

const reviewEvidence = computed(() => {
  const task = reviewTask.value
  const previews = task?.previewImages || task?.result?.previewImages || []
  const originals = task?.originalImages || task?.result?.originalImages || []
  const annotations = Array.isArray(previews) ? previews.filter(image => image && typeof image === 'object') : []
  return {
    annotations,
    originals: Array.isArray(originals) && originals.length ? originals : annotations
      .filter(image => typeof image.originalUrl === 'string' && image.originalUrl)
      .map(image => ({ imageName: image.imageName, previewUrl: image.originalUrl }))
  }
})

const openTraceDialog = async (taskId) => {
  if (typeof taskId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(taskId)) return
  const generation = ++traceGeneration, sameTask = traceDetail.value?.taskId === taskId
  traceReadController?.abort()
  const controller = new AbortController(); traceReadController = controller
  traceRequestedId.value = taskId; traceError.value = ''; traceDialogVisible.value = true; traceLoading.value = true
  if (!sameTask) traceDetail.value = null
  try {
    const response = await fetchDetectionTaskTrace(taskId, { signal: controller.signal })
    if (generation !== traceGeneration) return
    const detail = response.data?.data
    if (response.data?.code === 200 && detail && typeof detail === 'object' && !Array.isArray(detail) && detail.taskId === taskId && ['timeline','originalImages','previewImages'].every(key => detail[key] == null || Array.isArray(detail[key]))) {
      traceDetail.value = detail
      if (!sameTask) { await nextTick(); if (generation === traceGeneration) tracePanel.value?.resetScroll() }
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

onMounted(async () => {
  const initialNavigation = route.fullPath
  const routeTab = String(route.query.tab || route.meta?.detectionTab || '')
  if (validTabs.includes(routeTab)) {
    activeTab.value = routeTab
  }
  const queryQueue = String(route.query.queue || '')
  if (qualityQueues.some(queue => queue.value === queryQueue)) {
    activeQualityQueue.value = queryQueue
  }
  const queryWorkOrderNo = typeof route.query.workOrderNo === 'string' ? route.query.workOrderNo.trim() : ''
  const queryBatchNo = typeof route.query.batchNo === 'string' ? route.query.batchNo.trim() : ''
  if (queryWorkOrderNo && activeTab.value === 'work-order-trace') workOrderTraceNo.value = queryWorkOrderNo
  if (queryBatchNo && activeTab.value === 'batch-trace') batchTraceNo.value = queryBatchNo
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
  await readWorkbenchTasks()
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
  taskReadVersion++
  traceGeneration++
  traceReadController?.abort()
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
  grid-template-columns: minmax(0, 1fr);
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
  grid-template-columns: minmax(0, 1fr);
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
  pointer-events: none;
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
  min-height: 320px;
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

.single-result-task-id {
  color: #1d4ed8;
  font-size: 11px;
  overflow-wrap: anywhere;
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
  display:grid;
  grid-template-columns:minmax(0,1fr) minmax(165px,.85fr);
  gap:12px;
  margin-bottom:14px;
}
.workbench-task-filter { display:grid; gap:6px; min-width:0; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.workbench-task-filter :is(.task-search-input,.task-date-picker) { width:100%; min-width:0; }
.workbench-task-filter :deep(.el-date-editor.el-input) { width:100%; }
.workbench-task-scope { display:flex; align-items:flex-start; flex-wrap:wrap; gap:8px 12px; margin:10px 0 14px; min-width:0; }
.workbench-task-scope p { flex:1 1 200px; min-width:0; margin:0; color:var(--app-text-secondary); font-size:12px; line-height:1.85; overflow-wrap:anywhere; }
.workbench-task-scope a { color:var(--app-primary); text-decoration:underline; text-underline-offset:3px; }
.workbench-task-scope button { display:inline-flex; align-items:center; gap:5px; border:0; border-radius:4px; padding:2px 0; background:transparent; color:var(--app-primary); font:inherit; font-size:12px; line-height:1.8; cursor:pointer; transition:color 180ms ease; }
.workbench-upload-link { display:flex; align-items:center; justify-content:center; gap:6px; width:fit-content; max-width:100%; margin:0 auto 20px; padding:8px 12px; border-radius:6px; background:var(--app-primary); color:white; text-decoration:none; font-size:13px; line-height:1.8; transition:background-color 180ms ease; }
.workbench-upload-link:hover { background:var(--app-primary-hover); }
.workbench-task-scope :is(button,a):focus-visible,.workbench-upload-link:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
@media(max-width:560px) { .task-search-bar { grid-template-columns:minmax(0,1fr); } }
@media(prefers-reduced-motion:reduce) { .workbench-task-scope button,.workbench-upload-link { transition:none; } }

.task-filter-bar {
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--app-border);
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
  border-radius: 12px;
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  transition: border-color 180ms ease, background-color 180ms ease;
}

.task-item:hover {
  border-color: rgba(37, 99, 235, 0.20);
  background: #fff;
  box-shadow: none;
}

.task-item-selected,
.task-item-selected:hover {
  border-color: var(--app-primary);
  background: var(--app-surface);
  box-shadow: none;
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
  font-size: 12px;
  color: var(--app-text-secondary);
  flex-shrink: 0;
}

.taskid-value {
  font-size: 12px;
  color: var(--app-primary);
  background: var(--app-primary-soft);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: 'SF Mono', 'Consolas', monospace;
  white-space: normal;
  overflow-wrap:anywhere;
}

.task-item-row1 {
  display: flex;
  align-items: center;
  gap: 8px;
}
.task-item-toggle { width:100%; min-width:0; padding:6px 0; border:0; background:transparent; text-align:left; font:inherit; cursor:pointer; }
.task-item-toggle:hover .task-item-folder { color:var(--app-primary); }
.task-item-toggle:focus-visible { outline:2px solid var(--app-primary); outline-offset:4px; border-radius:4px; }
.task-item-toggle > .business-status { flex-shrink:0; }

.task-item-folder {
  font-weight: 600;
  color: var(--app-text);
  font-size: 14px;
  flex: 1;
  min-width:0;
  white-space:normal;
  overflow-wrap:anywhere;
}

.task-item-capture {
  display: flex;
  gap: 12px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--app-text-secondary);
  flex-wrap: wrap;
}

.task-expand-icon {
  font-size: 12px;
  color: var(--app-text-secondary);
  transition: transform 180ms ease;
  flex-shrink: 0;
}

.task-expand-icon-open {
  transform: rotate(180deg);
  color: var(--app-primary);
}

.task-item-actions {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--app-border);
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
  min-width: 0;
  padding-block: 4px;
}
.task-detail-enter-active,.task-detail-leave-active { transition:opacity 180ms ease; }
.task-detail-enter-from,.task-detail-leave-to { opacity:0; }
.task-result-unread { margin:14px 0 0; color:var(--app-text-secondary); font-size:12px; line-height:1.9; overflow-wrap:anywhere; }

.task-log-block {
  margin: 12px 0;
  padding: 12px 0;
  border-bottom: 1px solid var(--app-border);
}

.task-log-head {
  width:fit-content;
  color:var(--app-primary);
  font-size:12px;
  line-height:1.8;
  cursor:pointer;
}
.task-log-head:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
.task-log-note { margin:10px 0; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }

.task-log-list {
  display: grid;
  gap: 6px;
  padding:0;
  margin:10px 0 0;
  list-style:none;
}

.task-log-item {
  display:grid;
  grid-template-columns:minmax(0,155px) minmax(0,1fr);
  gap:6px 14px;
  font-size: 12px;
  line-height:1.8;
  color:var(--app-text-secondary);
}

.task-log-time {
  color:var(--app-text-secondary);
  font-variant-numeric:tabular-nums;
  overflow-wrap:anywhere;
}

.task-log-text {
  min-width:0;
  color:var(--app-text);
  white-space:pre-wrap;
  overflow-wrap:anywhere;
}
@media(max-width:480px) { .task-log-item { grid-template-columns:minmax(0,1fr); gap:2px; padding-block:6px; } }
@media(prefers-reduced-motion:reduce) { .task-expand-icon,.task-item,.task-detail-enter-active,.task-detail-leave-active { transition:none; } }

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
  transition: border-color 180ms ease, background-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
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
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  align-items: end;
  margin-bottom: 16px;
}

.defect-filter-bar > label { display:grid; gap:7px; min-width:0; font-size:12px; color:var(--app-text-secondary); line-height:1.8; }
.defect-filter-bar :deep(.el-select),.defect-filter-bar :deep(.el-input-number) { width:100%; }
.defect-filter-actions { display:flex; align-items:center; flex-wrap:wrap; gap:8px; min-height:32px; }
.defect-filter-actions .el-button + .el-button { margin-left:0; }
.defect-gallery-scope { display:flex; align-items:flex-start; gap:7px; margin:0 0 18px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.defect-gallery-scope > .el-icon { color:var(--app-primary); flex-shrink:0; margin-top:3px; }
.defect-gallery-filter-note { color:var(--app-text-secondary); font-size:12px; line-height:1.85; margin:0 0 16px; padding:10px 12px; background:var(--app-primary-soft); border-radius:7px; }
.defect-card-image > .preview-empty { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:10px; color:var(--app-text-secondary); font-size:12px; }
.defect-gallery-card .card-title-row > span:first-child { display:inline-flex; align-items:center; gap:8px; }
.defect-gallery-card .card-title-row > span:first-child .el-icon { color:var(--app-primary); }

.defect-gallery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}

.defect-evidence-card {
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  background: var(--app-surface);
  box-shadow: none;
  transition: border-color 180ms ease;
}

.defect-evidence-card:hover {
  border-color: rgba(37, 99, 235, 0.22);
  box-shadow: none;
}

.defect-card-image {
  height: 190px;
  background: var(--app-surface-muted);
  display: flex;
  align-items: center;
  justify-content: center;
}

.defect-card-image img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.defect-card-body {
  padding: 14px;
}

.defect-card-identity { display:flex; flex-wrap:wrap; align-items:center; gap:8px; min-width:0; }
.defect-card-identity > span:not(.business-status) { color:var(--app-text-secondary); font-size:12px; }
.defect-card-identity > button { flex:1 1 100%; min-width:0; padding:0; border:0; border-radius:3px; text-align:left; background:transparent; color:var(--app-primary); font:600 12px/1.8 Consolas,monospace; overflow-wrap:anywhere; cursor:pointer; }
.defect-card-section { margin-top:14px; padding-top:14px; border-top:1px solid var(--app-border); min-width:0; }
.defect-card-section h4 { display:flex; flex-wrap:wrap; align-items:center; gap:7px; margin:0 0 10px; color:var(--app-text); font-size:13px; line-height:1.8; font-weight:600; }
.defect-card-section h4 > .el-icon { color:var(--app-primary); flex-shrink:0; }
.defect-card-facts { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px 14px; margin:10px 0; }
.defect-card-facts > div { min-width:0; }
.defect-card-facts .defect-fact-wide { grid-column:1/-1; }
.defect-card-facts dt { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.defect-card-facts dd { margin:4px 0 0; color:var(--app-text); font-size:13px; line-height:1.8; overflow-wrap:anywhere; }
.defect-card-facts dd > small { display:block; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.defect-card-note { margin:10px 0; color:var(--app-text-secondary); font-size:12px; line-height:1.85; overflow-wrap:anywhere; }
.defect-card-disclosure { margin:12px 0; }
.defect-card-disclosure > summary { display:inline-flex; align-items:center; gap:6px; max-width:100%; padding:3px 0; color:var(--app-primary); font-size:12px; line-height:1.8; cursor:pointer; list-style:none; }
.defect-card-disclosure > summary::-webkit-details-marker { display:none; }
.defect-card-disclosure > summary > .el-icon { flex-shrink:0; transition:transform 180ms ease; }
.defect-card-disclosure[open] > summary > .el-icon { transform:rotate(180deg); }
.defect-evidence-excerpts { padding-left:18px; margin:10px 0; }
.defect-evidence-excerpts > li { padding:6px 0; color:var(--app-text-secondary); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.defect-evidence-excerpts strong { display:block; color:var(--app-text); font-size:12px; font-weight:550; }
.defect-evidence-excerpts span { display:block; }
.defect-card-body :is(button,a,summary):focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
@media(prefers-reduced-motion:reduce) { .defect-evidence-card,.defect-card-disclosure > summary > .el-icon { transition:none; } }

.defect-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
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
.history-scope-note { display:flex; align-items:flex-start; gap:7px; margin:0 0 18px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.history-scope-note > .el-icon { color:var(--app-primary); flex-shrink:0; margin-top:3px; }
.history-query-form { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; align-items:end; margin-bottom:18px; }
.history-query-form > label { display:grid; gap:7px; min-width:0; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.history-query-keyword { grid-column:span 2; }
.history-query-actions { display:flex; align-items:center; flex-wrap:wrap; gap:8px; min-height:32px; }
.history-query-actions .el-button + .el-button { margin-left:0; }
.history-applied-query { margin:0 0 14px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; overflow-wrap:anywhere; }
.history-filter-note { padding:10px 12px; margin:0 0 16px; border-radius:7px; background:var(--app-primary-soft); color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.history-records-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); align-items:start; gap:18px; }
.history-retry { margin:12px 0 18px; }
.history-pagination { display:flex; justify-content:flex-end; padding:20px 0 4px; }
.history-pagination :deep(.el-pagination) { flex-wrap:wrap; gap:8px; }
@media(max-width:1100px) { .history-records-grid { grid-template-columns:minmax(0,1fr); } }
@media(max-width:720px) { .history-query-form { grid-template-columns:minmax(0,1fr); } .history-query-keyword { grid-column:auto; } .history-pagination { justify-content:flex-start; } }
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
  .single-detection-workspace,
  .defect-filter-bar {
    grid-template-columns: 1fr;
  }

  .defect-filter-bar { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .single-detection-result { padding:20px 0 0; border-left:0; border-top:1px solid var(--app-border); }
}

@media (max-width: 720px) {
  .batch-trace-search,
  .defect-filter-bar {
    grid-template-columns: 1fr;
  }

  .defect-gallery-grid {
    grid-template-columns: 1fr;
  }
}

.quality-queue-scope { display:flex; align-items:flex-start; gap:7px; margin:8px 0 14px; color:var(--app-text-muted); font-size:12px; line-height:1.8; }
.quality-queue-scope > .el-icon { flex:0 0 auto; margin-top:3px; color:var(--app-primary); }
.quality-queue-read-error { margin-bottom:14px; }
.quality-queue-task, .quality-queue-responsibility { display:grid; gap:4px; min-width:0; }
.quality-queue-task button { width:fit-content; max-width:100%; padding:0; border:0; border-radius:3px; background:transparent; color:var(--app-primary); font-size:12px; font-weight:550; line-height:1.8; text-align:left; overflow-wrap:anywhere; cursor:pointer; }
.quality-queue-task button:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
.quality-queue-task span, .quality-queue-responsibility span { color:var(--app-text-secondary); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.quality-queue-task small, .quality-queue-responsibility small { color:var(--app-text-muted); font-size:11px; line-height:1.7; overflow-wrap:anywhere; }
.quality-queue-responsibility strong { color:var(--app-text); font-size:13px; font-weight:550; overflow-wrap:anywhere; }
.quality-queue-chip.active { background:var(--app-primary-soft); border-color:#aac3f6; box-shadow:none; transform:none; }
.quality-queue-chip:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
.detection-input-note { margin:0 0 14px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.detection-input-note.is-warning { padding:9px 11px; border-radius:8px; color:var(--app-warning); background:var(--app-warning-soft); }
.detection-input-note button { margin:4px 0 0; padding:2px 0; border:0; border-radius:4px; color:var(--app-primary); background:transparent; cursor:pointer; font:inherit; }
.detection-model-option { display:flex; align-items:center; gap:10px; min-width:0; }.detection-model-option > span:first-child { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.detection-model-option > .business-status { flex:0 0 auto; font-size:12px; }
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
.single-task-links { display:flex; align-items:center; flex-wrap:wrap; gap:8px 18px; margin:0 0 16px; }
.single-task-links > :is(a,button) { display:inline-flex; align-items:center; gap:5px; border:0; border-radius:5px; padding:5px 0; color:var(--app-primary); background:transparent; font-size:12px; font-family:inherit; text-decoration:none; cursor:pointer; }
.single-task-links > :is(a,button):focus-visible, .detection-input-note button:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
@media(max-width:480px) { .single-submission-summary { grid-template-columns:minmax(0,1fr); } }
@media(max-width:580px) { .quality-queue-scope { font-size:11px; }.quality-pagination { justify-content:flex-start; overflow-x:auto; padding-bottom:5px; } }
</style>
