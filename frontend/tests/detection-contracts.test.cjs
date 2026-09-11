const assert = require('node:assert/strict')
const test = require('node:test')
const { readFrontendFile, readProjectFile } = require('./helpers/project-source.cjs')

test('tests\\detection-category-contract.test.cjs', () => {
  const imageDetectionSource = readFrontendFile('src', 'views', 'ImageDetection.vue')
  const homeSource = readFrontendFile('src', 'views', 'Home.vue')
  const detectionTaskStoreSource = readFrontendFile('src', 'stores', 'taskStore.js')

  for (const pair of [
    ['Normal', '正常'],
    ['Bent', '弯曲'],
    ['Deformed', '形变'],
    ['Rusty', '锈蚀'],
    ['Missing', '缺失'],
    ['Compromised', '结构损伤']
  ]) {
    const [code, label] = pair
    assert.match(detectionTaskStoreSource, new RegExp(code))
    assert.match(detectionTaskStoreSource, new RegExp(label))
  }

  assert.match(imageDetectionSource, /CATEGORY_LABELS/)
  assert.match(imageDetectionSource, /CATEGORY_ALIASES/)
  assert.match(imageDetectionSource, /CATEGORY_COLORS/)

  assert.doesNotMatch(imageDetectionSource, /BSGXX:\s*'正常'/)
  assert.doesNotMatch(imageDetectionSource, /BSGZX:\s*'维修'/)
  assert.doesNotMatch(imageDetectionSource, /BSGGH:\s*'更换'/)

  assert.match(homeSource, /结构损伤/)
  assert.doesNotMatch(homeSource, /快速查看正常、维修、更换三类结果占比/)

  console.log('detection category contract assertions passed')
})

test('tests\\single-image-preview-contract.test.cjs', () => {
  const composableSource = readFrontendFile('src', 'composables', 'useSingleImageUploadPreview.js')

  assert.match(composableSource, /URL\.createObjectURL\(file\)/)
  assert.match(composableSource, /URL\.revokeObjectURL/)
  assert.match(composableSource, /handleUploadChange/)
  assert.match(composableSource, /uploadFile\.raw/)
  assert.match(composableSource, /onBeforeUnmount/)
  assert.match(composableSource, /onReset/)

  const pages = [
    ['src', 'views', 'ImageDetection.vue'],
    ['src', 'views', 'inspection', 'InspectionWorkbench.vue'],
    ['src', 'views', 'inspection', 'InspectionHistory.vue'],
    ['src', 'views', 'quality', 'QualityQueue.vue'],
    ['src', 'views', 'quality', 'DefectEvidenceGallery.vue'],
    ['src', 'views', 'quality', 'WorkOrderTrace.vue'],
    ['src', 'views', 'quality', 'BatchTrace.vue']
  ]

  for (const pagePath of pages) {
    const source = readFrontendFile(...pagePath)
    assert.match(source, /useSingleImageUploadPreview/)
    assert.doesNotMatch(source, /const beforeUpload = \(file\) =>/)
    assert.doesNotMatch(source, /originFileObj:\s*file/)
  }

  for (const pagePath of pages.slice(0, 2)) {
    const source = readFrontendFile(...pagePath)
    assert.match(source, /:auto-upload="false"/)
    assert.match(source, /:on-change="handleUploadChange"/)
    assert.match(source, /:limit="1"/)
    assert.match(source, /:on-remove="handleRemove"/)
    assert.doesNotMatch(source, /:remove="handleRemove"/)
    assert.doesNotMatch(source, /:before-upload=/)
    assert.doesNotMatch(source, /:max-count=/)
  }

  const activeDetectionPage = readFrontendFile('src', 'views', 'ImageDetection.vue')
  const kafkaService = readFrontendFile('src', 'services', 'singleImageKafkaDetection.js')
  assert.ok(kafkaService, 'single image Kafka detection service must exist')
  assert.match(kafkaService, /taskType:\s*'SINGLE'/)
  assert.match(kafkaService, /\/api\/detection\/tasks/)
  assert.match(kafkaService, /\/uploaded/)
  assert.match(kafkaService, /singleImageResult/)
  assert.match(kafkaService, /远程结果不完整/)
  assert.doesNotMatch(activeDetectionPage, /\bdetectSingleImage(?:\s*,|\s*\()/)
  assert.match(activeDetectionPage, /detectSingleImageViaKafka/)
  assert.match(activeDetectionPage, /singleDetectionTaskId/)
  assert.match(activeDetectionPage, /singleDetectionStage === 'FAILED'/)
  assert.match(activeDetectionPage, /Kafka 远程/)
  assert.match(activeDetectionPage, /class="single-detection-workspace"/)
  assert.match(activeDetectionPage, /class="single-detection-result"/)
  assert.match(activeDetectionPage, /class="single-upload-file-name"/)
  assert.match(activeDetectionPage, /v-loading="loadingSingle"/)
  assert.match(activeDetectionPage, /alt="单图检测标注结果"/)
  assert.match(activeDetectionPage, /alt="待检测图片预览"/)
  assert.match(activeDetectionPage, /请先选择图片并开始检测/)
  assert.doesNotMatch(activeDetectionPage, /class="detection-card result-card"/)
  assert.doesNotMatch(activeDetectionPage, /singleResultCard/)
  assert.doesNotMatch(activeDetectionPage, /scrollIntoView/)

  console.log('single image upload preview contract assertions passed')
})

test('tests\\use-defect-gallery-contract.test.cjs', () => {
  const composableSource = readFrontendFile('src', 'composables', 'useDefectGallery.js')
  const imageDetectionSource = readFrontendFile('src', 'views', 'ImageDetection.vue')

  for (const name of [
    'defectGalleryLoading',
    'defectGalleryRecords',
    'defectGalleryTotal',
    'defectGalleryPage',
    'defectGalleryPageSize',
    'defectFilters',
    'loadDefectGallery',
    'searchDefectGallery',
    'resetDefectGalleryFilters',
    'onDefectGallerySizeChange'
  ]) {
    assert.match(composableSource, new RegExp(name))
    assert.match(imageDetectionSource, new RegExp(name))
  }

  assert.match(composableSource, /fetchDefectGallery/)
  assert.match(composableSource, /buildDefectGalleryParams/)
  assert.match(composableSource, /defectType/)
  assert.match(composableSource, /severityLevel/)
  assert.match(composableSource, /deviceName/)
  assert.match(composableSource, /batchNo/)
  assert.match(composableSource, /modelId/)
  assert.match(imageDetectionSource, /useDefectGallery\(\)/)

  assert.doesNotMatch(imageDetectionSource, /fetchDefectGallery/)
  assert.doesNotMatch(imageDetectionSource, /const defectGalleryLoading = ref/)
  assert.doesNotMatch(imageDetectionSource, /const defectFilters = reactive/)
  assert.doesNotMatch(imageDetectionSource, /const buildDefectGalleryParams =/)
  assert.doesNotMatch(imageDetectionSource, /const loadDefectGallery = async/)
  assert.doesNotMatch(imageDetectionSource, /const resetDefectGalleryFilters =/)

  console.log('use defect gallery contract assertions passed')
})

test('tests\\use-detection-history-contract.test.cjs', () => {
  const composableSource = readFrontendFile('src', 'composables', 'useDetectionHistory.js')
  const imageDetectionSource = readFrontendFile('src', 'views', 'ImageDetection.vue')

  for (const name of [
    'historySearchKeyword',
    'historyFilterCollector',
    'historyFilterDevice',
    'historyFilterRegion',
    'historyPage',
    'historyPageSize',
    'historyTotal',
    'historyRecords',
    'historyLoading',
    'fetchHistoryWithFilters',
    'onHistorySearch',
    'onHistoryPageChange',
    'onHistorySizeChange'
  ]) {
    assert.match(composableSource, new RegExp(name))
    assert.match(imageDetectionSource, new RegExp(name))
  }

  assert.match(composableSource, /buildHistoryFilters/)
  assert.match(composableSource, /normalizeHistoryRecord/)
  assert.match(composableSource, /pollingStore\.fetchTaskList/)
  assert.match(composableSource, /pollingStore\.fetchTaskResults/)
  assert.match(imageDetectionSource, /useDetectionHistory\(taskStore, pollingStore\)/)

  assert.doesNotMatch(imageDetectionSource, /const historySearchKeyword = ref/)
  assert.doesNotMatch(imageDetectionSource, /const historyPage = ref/)
  assert.doesNotMatch(imageDetectionSource, /const historyRecords = ref/)
  assert.doesNotMatch(imageDetectionSource, /const fetchHistoryWithFilters = async/)
  assert.doesNotMatch(imageDetectionSource, /const onHistoryPageChange = /)
  assert.doesNotMatch(imageDetectionSource, /const completedTasks = computed/)

  console.log('use detection history contract assertions passed')
})
