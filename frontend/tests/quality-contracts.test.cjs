const assert = require('node:assert/strict')
const test = require('node:test')
const { readFrontendFile, readProjectFile } = require('./helpers/project-source.cjs')

test('candidate read permission suppresses task write hints until a fresh claimed task arrives', async () => {
  const code=readFrontendFile('src','utils','qualityWorkflow.js')
  const workflow=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
  const ready={qualityActions:[{action:'REVIEW',stateAllowed:true}],claimReadOnly:true}
  assert.equal(workflow.canReviewTask(ready),false)
  assert.match(workflow.qualityActionReason(ready,'REVIEW'),/先领取任务/)
  assert.equal(workflow.canReviewTask({...ready,claimReadOnly:false}),true)
})

test('tests\\quality-records-contract.test.cjs', () => {
  const recordsSource = readFrontendFile('src', 'utils', 'qualityRecords.js')
  const imageDetectionSource = readFrontendFile('src', 'views', 'ImageDetection.vue')
  const evidenceSource = readFrontendFile('src', 'components', 'TaskTracePanel.vue')
  const resultSource = readFrontendFile('src', 'components', 'TaskResultSnapshot.vue')

  for (const exportName of [
    'buildTraceEvidenceRows',
    'formatEvidenceConfidence',
    'formatPercentValue'
  ]) {
    assert.match(recordsSource, new RegExp(`export const ${exportName}`))
    if (exportName !== 'formatPercentValue') {
      assert.match(imageDetectionSource + evidenceSource + resultSource, new RegExp(exportName))
    }
  }

  assert.match(recordsSource, /原图/)
  assert.match(recordsSource, /标注图/)

  assert.doesNotMatch(imageDetectionSource, /const formatEvidenceConfidence =/)
  assert.doesNotMatch(imageDetectionSource, /const formatPercentValue =/)

  console.log('quality records contract assertions passed')
})

test('tests\\quality-workflow-contract.test.cjs', () => {
  const workflowSource = readFrontendFile('src', 'utils', 'qualityWorkflow.js')
  const imageDetectionSource = readFrontendFile('src', 'views', 'ImageDetection.vue')
  const actionsSource = readFrontendFile('src', 'composables', 'useQualityTaskActions.js')

  for (const exportName of [
    'canAssignQualityTask',
    'canReviewTask',
    'canDisposeTask',
    'canReleaseDisposition',
    'canSubmitReworkResult',
    'shouldDefaultRecheck'
  ]) {
    assert.match(workflowSource, new RegExp(`export const ${exportName}`))
    assert.match(imageDetectionSource + actionsSource, new RegExp(exportName))
  }
  for (const exportName of ['flowStatusText', 'reviewStatusText', 'dispositionActionText']) {
    assert.match(workflowSource, new RegExp(`export const ${exportName}`))
  }

  for (const status of [
    'PENDING_REVIEW',
    'REWORK_REQUIRED',
    'RECHECK_REQUIRED',
    'RELEASED',
    'SCRAPPED',
    'ARCHIVED'
  ]) {
    assert.match(workflowSource, new RegExp(status))
  }

  assert.match(workflowSource, /TERMINAL_FLOW_STATUSES/)
  assert.match(workflowSource, /DISPOSABLE_FLOW_STATUSES/)
  assert.match(workflowSource, /RELEASE_ALLOWED_CONCLUSIONS/)

  assert.doesNotMatch(imageDetectionSource, /const canDisposeTask =/)
  assert.doesNotMatch(imageDetectionSource, /const canAssignQualityTask =/)
  assert.doesNotMatch(imageDetectionSource, /const canReleaseDisposition =/)
  assert.doesNotMatch(imageDetectionSource, /const flowStatusText =/)

  console.log('quality workflow contract assertions passed')
})

test('verification uses the task board and old queue addresses lead back to verification', () => {
  const imageDetectionSource = readFrontendFile('src', 'views', 'ImageDetection.vue')
  const router = readFrontendFile('src', 'router', 'index.js')
  assert.doesNotMatch(imageDetectionSource, /name="quality"|useQualityQueue|fetchQualityQueue/)
  assert.match(router, /name:\s*'supervisorVerificationTasks'/)
  assert.match(router, /to.name === 'legacyQualityQueue'/)
  assert.match(router, /kind:\s*'verification'/)
})

test('tests\\use-quality-report-downloads-contract.test.cjs', () => {
  const composableSource = readFrontendFile('src', 'composables', 'useQualityReportDownloads.js')
  const imageDetectionSource = readFrontendFile('src', 'views', 'ImageDetection.vue')

  for (const name of [
    'safeFilePart',
    'reportTimestamp',
    'downloadJsonReport',
    'reportDownloading',
    'downloadTaskQualityReport',
    'downloadBatchTraceReport',
    'downloadWorkOrderTraceReport'
  ]) {
    assert.match(composableSource, new RegExp(name))
  }

  for (const name of [
    'reportDownloading',
    'downloadTaskQualityReport',
    'downloadBatchTraceReport',
    'downloadWorkOrderTraceReport'
  ]) {
    assert.match(imageDetectionSource, new RegExp(name))
  }

  assert.match(composableSource, /fetchQualityReport/)
  assert.match(composableSource, /quality-report-\$\{safeFilePart\(taskId\)\}-\$\{reportTimestamp\(\)\}\.json/)
  assert.match(composableSource, /batch-trace-\$\{safeFilePart\(batchNo\)\}-\$\{reportTimestamp\(\)\}\.json/)
  assert.match(composableSource, /work-order-trace-\$\{safeFilePart\(workOrderNo\)\}-\$\{reportTimestamp\(\)\}\.json/)
  assert.match(imageDetectionSource, /useQualityReportDownloads\(\{/)

  assert.doesNotMatch(imageDetectionSource, /fetchQualityReport/)
  assert.doesNotMatch(imageDetectionSource, /const safeFilePart = /)
  assert.doesNotMatch(imageDetectionSource, /const reportTimestamp = /)
  assert.doesNotMatch(imageDetectionSource, /const downloadJsonReport = /)
  assert.doesNotMatch(imageDetectionSource, /const downloadTaskQualityReport = async/)
  assert.doesNotMatch(imageDetectionSource, /const downloadBatchTraceReport = /)
  assert.doesNotMatch(imageDetectionSource, /const downloadWorkOrderTraceReport = /)

  console.log('use quality report downloads contract assertions passed')
})

test('tests\\use-quality-task-actions-contract.test.cjs', () => {
  const composableSource = readFrontendFile('src', 'composables', 'useQualityTaskActions.js')
  const qualityPages = [
    'WorkOrderTrace.vue',
    'BatchTrace.vue'
  ]

  for (const name of [
    'reviewDialogVisible',
    'reviewSubmitting',
    'reviewTask',
    'reviewForm',
    'assignmentDialogVisible',
    'assignmentSubmitting',
    'assignmentTask',
    'assignmentForm',
    'dispositionDialogVisible',
    'dispositionSubmitting',
    'dispositionTask',
    'dispositionForm',
    'reworkDialogVisible',
    'reworkSubmitting',
    'reworkTask',
    'reworkForm',
    'applyTaskProgressUpdate',
    'openReviewDialog',
    'submitTaskReview',
    'openAssignmentDialog',
    'submitQualityAssignment',
    'openDispositionDialog',
    'submitTaskDisposition',
    'openReworkDialog',
    'submitTaskRework'
  ]) {
    assert.match(composableSource, new RegExp(name))
  }

  assert.match(composableSource, /assignDetectionQualityTask/)
  assert.match(composableSource, /reviewDetectionTask/)
  assert.match(composableSource, /disposeDetectionTask/)
  assert.match(composableSource, /submitDetectionReworkResult/)
  assert.match(composableSource, /shouldDefaultRecheck/)

  for (const page of qualityPages) {
    const source = readFrontendFile('src', 'views', 'quality', page)
    assert.match(source, /useQualityTaskActions\(\{/)
    assert.match(source, /refreshQualityQueue: refreshQualityQueueIfVisible/)
    assert.doesNotMatch(source, /assignDetectionQualityTask/)
    assert.doesNotMatch(source, /reviewDetectionTask/)
    assert.doesNotMatch(source, /disposeDetectionTask/)
    assert.doesNotMatch(source, /submitDetectionReworkResult/)
    assert.doesNotMatch(source, /const reviewDialogVisible = ref/)
    assert.doesNotMatch(source, /const reviewForm = reactive/)
    assert.doesNotMatch(source, /const applyTaskProgressUpdate = async/)
    assert.doesNotMatch(source, /const openReviewDialog = /)
    assert.doesNotMatch(source, /const submitTaskReview = async/)
    assert.doesNotMatch(source, /const submitQualityAssignment = async/)
    assert.doesNotMatch(source, /const submitTaskDisposition = async/)
    assert.doesNotMatch(source, /const submitTaskRework = async/)
  }

  console.log('use quality task actions contract assertions passed')
})

test('tests\\use-trace-reports-contract.test.cjs', () => {
  const composableSource = readFrontendFile('src', 'composables', 'useTraceReports.js')
  const imageDetectionSource = readFrontendFile('src', 'views', 'ImageDetection.vue')

  for (const name of [
    'workOrderTraceNo',
    'workOrderTraceLoading',
    'workOrderTraceReport',
    'batchTraceNo',
    'batchTraceLoading',
    'batchTraceReport',
    'businessWorkOrderNos',
    'businessBatchNos',
    'ensureDefaultWorkOrderNo',
    'ensureDefaultBatchNo',
    'loadWorkOrderTraceReport',
    'loadBatchTraceReport',
    'loadBusinessWorkOrderTrace',
    'loadBusinessBatchTrace'
  ]) {
    assert.match(composableSource, new RegExp(name))
    assert.match(imageDetectionSource, new RegExp(name))
  }

  assert.match(composableSource, /fetchWorkOrderTraceReport/)
  assert.match(composableSource, /fetchBatchTraceReport/)
  assert.match(composableSource, /businessWorkOrderNos/)
  assert.match(composableSource, /businessBatchNos/)
  assert.match(imageDetectionSource, /useTraceReports\(\{ getAccountScope:/)

  assert.doesNotMatch(imageDetectionSource, /fetchWorkOrderTraceReport/)
  assert.doesNotMatch(imageDetectionSource, /fetchBatchTraceReport/)
  assert.doesNotMatch(imageDetectionSource, /const workOrderTraceNo = ref/)
  assert.doesNotMatch(imageDetectionSource, /const batchTraceNo = ref/)
  assert.doesNotMatch(imageDetectionSource, /const demoWorkOrderNos = \[/)
  assert.doesNotMatch(imageDetectionSource, /demoBatchNos/)
  assert.doesNotMatch(imageDetectionSource, /loadDemoWorkOrderTrace/)
  assert.doesNotMatch(imageDetectionSource, /loadDemoBatchTrace/)
  assert.doesNotMatch(imageDetectionSource, /const loadWorkOrderTraceReport = async/)
  assert.doesNotMatch(imageDetectionSource, /const loadBatchTraceReport = async/)

  console.log('use trace reports contract assertions passed')
})
