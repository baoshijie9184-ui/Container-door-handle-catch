const assert = require('node:assert/strict')
const test = require('node:test')
const { importFrontendModule, readFrontendFile, readProjectFile } = require('./helpers/project-source.cjs')

test('application approvals include pending and approved requests without a bound batch', async () => {
  const { needsDetectionBatch } = await importFrontendModule('src', 'utils', 'workUnitApplications.js')
  const pending = {
    workUnitId: 'WU-' + 'a'.repeat(32), strategy: 'UNDETECTED_ONLY', status: 'WAITING',
    applicantUserId: 'DET-0001', assigneeUserId: null, sourceBatchId: null, batchId: null
  }
  const approved = { ...pending, status: 'ASSIGNED', assigneeUserId: pending.applicantUserId }
  const projections = [pending, approved,
    { ...approved, sourceBatchId: 'upload-1' },
    { ...approved, batchId: 'det_folder_1' },
    { ...approved, assigneeUserId: 'another-inspector' },
    { ...pending, strategy: 'OSS_FOLDER' },
    { ...pending, status: 'REJECTED' },
    { ...pending, status: 'WITHDRAWN' }]
  assert.deepEqual(projections.filter(needsDetectionBatch), [pending, approved])
})

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
  const previewService = readFrontendFile('src', 'services', 'singleImagePreview.js')
  const comparison = readFrontendFile('src', 'components', 'SingleModelComparison.vue')
  assert.match(previewService, /post\('\/api\/image-detection\/preview', file,/)
  assert.match(previewService, /data:image\/jpeg;base64,/)
  assert.doesNotMatch(previewService, /\/api\/detection\/tasks|\/uploaded|\/oss-upload|localStorage/)
  assert.match(activeDetectionPage, /await previewSingleImage\(/)
  assert.match(activeDetectionPage, /singleDetectionStage\.value = 'FAILED'/)
  assert.match(activeDetectionPage, /singleDetectionStage\.value = 'COMPLETED'/)
  assert.match(comparison, /await previewSingleImage\(/)
  assert.doesNotMatch(comparison, /taskId|查看检测记录/)
  assert.match(activeDetectionPage, /class="single-detection-workspace"/)
  assert.match(activeDetectionPage, /class="single-detection-result"/)
  assert.match(activeDetectionPage, /class="single-upload-file-name"/)
  assert.match(activeDetectionPage, /:aria-busy="loadingSingle"/)
  const singlePane = activeDetectionPage.split('<el-tab-pane name="workspace"')[1].split('</el-tab-pane>')[0]
  assert.doesNotMatch(singlePane, /上传任务列表|刷新任务列表|报告与审批|核对本次任务|single-result-task-id/)
  assert.doesNotMatch(readFrontendFile('src', 'components', 'SingleModelComparison.vue'), /查看任务记录/)
  assert.match(activeDetectionPage, /alt="待检测图片预览"/)
  assert.match(activeDetectionPage, /请先选择图片并开始检测/)
  assert.doesNotMatch(activeDetectionPage, /class="detection-card result-card"/)
  assert.doesNotMatch(activeDetectionPage, /singleResultCard/)
  assert.doesNotMatch(activeDetectionPage, /scrollIntoView/)

  console.log('single image upload preview contract assertions passed')
})

test('quality navigation and detection API expose task review and trace without the removed library', () => {
  const router = readFrontendFile('src', 'router', 'index.js')
  const api = readFrontendFile('src', 'api', 'detection.js')
  assert.doesNotMatch(router, /quality\/evidence|defect-gallery/)
  assert.doesNotMatch(api, /defect-gallery/)
  assert.match(router, /quality\/queue/)
  assert.match(api, /fetchDetectionTaskTrace/)
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

test('removing a linked detection-history keyword refreshes results and preserves manual filters', async () => {
  const key = '__historyRouteTest'
  globalThis[key] = {
    ref: value => ({ value }), computed: read => ({ get value() { return read() } }),
    onBeforeUnmount: () => {}, knownCount: value => value
  }
  try {
    const source = readFrontendFile('src', 'composables', 'useDetectionHistory.js')
      .replace("import { computed, ref, onBeforeUnmount } from 'vue'", `const {computed,ref,onBeforeUnmount}=globalThis[${JSON.stringify(key)}]`)
      .replace("import { knownCount } from '../utils/countPresentation'", `const {knownCount}=globalThis[${JSON.stringify(key)}]`)
    const { useDetectionHistory } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))
    const requests = []
    const history = useDetectionHistory({}, {
      async fetchTaskList(page, size, keyword, status, filters) {
        requests.push({ page, filters })
        return { ok: true, records: [], total: keyword === 'missing' ? 0 : 23 }
      }
    })

    await history.readHistoryFromRoute('missing', false, true)
    assert.equal(history.historyTotal.value, 0)
    await history.readHistoryFromRoute(undefined, false)
    assert.equal(history.historySearchKeyword.value, '')
    assert.equal(history.historyTotal.value, 23)
    assert.deepEqual(requests.at(-1), { page: 1, filters: {} })

    history.historyFilterRegion.value = '已提交地区'
    await history.readHistoryFromRoute('missing', true)
    await history.readHistoryFromRoute('missing', true)
    const linked = { page: 1, filters: { keyword: 'missing', region: '已提交地区', completedResults: true } }
    assert.deepEqual(requests.slice(-2), [linked, linked])
    history.historyFilterRegion.value = '地区草稿'
    history.historySearchKeyword.value = '关键词草稿'
    await history.readHistoryFromRoute(undefined, true)
    assert.deepEqual(requests.at(-1), { page: 1, filters: { region: '已提交地区', completedResults: true } })
    assert.equal(history.historySearchKeyword.value, '关键词草稿')
    assert.equal(history.historyFilterRegion.value, '地区草稿')
    assert.equal(history.historyFiltersDirty.value, true)

    await history.readHistoryFromRoute('missing', false)
    history.historySearchKeyword.value = '手工关键词'
    await history.onHistorySearch()
    await history.readHistoryFromRoute(undefined, false)
    await history.onHistorySearch()
    const manual = { page: 1, filters: { keyword: '手工关键词', region: '地区草稿' } }
    assert.deepEqual(requests.slice(-3), [manual, manual, manual])
  } finally {
    delete globalThis[key]
  }
})
