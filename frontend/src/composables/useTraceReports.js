import { ref, watch, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchBatchTraceReport, fetchWorkOrderTraceReport, fetchTraceReferenceTasks } from '../api/detection'
import { readTraceReferences } from '../utils/traceReferences.js'

const TRACE_PAGE_SIZE = 20
const TRACE_PAGE_SIZES = [10, TRACE_PAGE_SIZE, 50]

function readTraceReport(value, field, expected, requestedPage, requestedSize) {
  if (!value || value[field] !== expected || !Array.isArray(value.records)) throw new Error('追溯摘要未完整读取，请重新查询核对')
  const taskIds = new Set()
  for (const record of value.records) {
    if (!record || typeof record.taskId !== 'string' || !record.taskId.trim() || taskIds.has(record.taskId)) throw new Error('追溯任务明细未完整读取，请重新查询核对')
    taskIds.add(record.taskId)
  }
  for (const key of ['summary','inspection','quality','distribution','timeRange']) {
    if (value[key] != null && (typeof value[key] !== 'object' || Array.isArray(value[key]))) throw new Error('追溯汇总结构未完整读取，请重新查询核对')
  }
  for (const key of ['batchNos','regions','collectors','devices','models','workOrders']) {
    const entries = value.summary?.[key]
    if (entries != null && (!Array.isArray(entries) || entries.some(entry => typeof entry !== 'string' || !entry.trim()))) throw new Error('追溯来源信息未完整读取，请重新查询核对')
  }
  const { page, size, total } = value
  if ([page, size, total].some(entry => entry !== undefined)
    && (page !== requestedPage || size !== requestedSize || !Number.isSafeInteger(total) || total < 0
      || value.records.length > Math.min(size, Math.max(0, total - (page - 1) * size)))) {
    throw new Error('追溯明细分页信息不完整，请重新读取')
  }
  return value
}

export function useTraceReports({ getAccountScope = () => null } = {}) {
  const workOrderTraceNo = ref(''), workOrderTraceLoading = ref(false), workOrderTraceReport = ref(null), workOrderTraceError = ref('')
  const batchTraceNo = ref(''), batchTraceLoading = ref(false), batchTraceReport = ref(null), batchTraceError = ref('')
  const accountScope = () => JSON.stringify(getAccountScope())
  const businessWorkOrderNos = ref([]), businessBatchNos = ref([])
  const traceReferencesLoading = ref(false), traceReferencesLoaded = ref(false), traceReferencesError = ref('')
  let referenceGeneration = 0, referenceController, referenceRequest
  let disposed = false
  function resetReferences() {
    referenceGeneration++; referenceController?.abort(); referenceController = null; referenceRequest = null
    businessWorkOrderNos.value = []; businessBatchNos.value = []
    traceReferencesLoading.value = false; traceReferencesLoaded.value = false; traceReferencesError.value = ''
  }
  async function loadTraceReferences() {
    if (disposed) return
    if (traceReferencesLoading.value) return referenceRequest
    const generation = ++referenceGeneration, owner = accountScope(), controller = new AbortController()
    referenceController = controller; traceReferencesLoading.value = true; traceReferencesError.value = ''
    referenceRequest = (async () => {
      try {
        const response = await fetchTraceReferenceTasks({ signal: controller.signal })
        if (disposed || generation !== referenceGeneration || owner !== accountScope()) return
        const references = readTraceReferences(response.data)
        businessWorkOrderNos.value = references.workOrders; businessBatchNos.value = references.batches
        traceReferencesLoaded.value = true
      } catch (failure) {
        if (disposed || generation !== referenceGeneration || controller.signal.aborted || owner !== accountScope()) return
        businessWorkOrderNos.value = []; businessBatchNos.value = []; traceReferencesLoaded.value = false
        traceReferencesError.value = '最近任务编号暂不可读取，可手工输入已有编号查询'
      } finally {
        if (!disposed && generation === referenceGeneration && owner === accountScope()) {
          traceReferencesLoading.value = false; referenceController = null; referenceRequest = null
        }
      }
    })()
    return referenceRequest
  }
  function createReader({ field, label, query, loading, report, error, api }) {
    let generation = 0, controller
    const requested = ref('')
    const requestedPage = ref(1)
    let requestedSize = TRACE_PAGE_SIZE
    function stop() { generation++; controller?.abort(); controller = null; loading.value = false }
    function reset(clearQuery = false) { stop(); requested.value = ''; requestedPage.value = 1; requestedSize = TRACE_PAGE_SIZE; report.value = null; error.value = ''; if (clearQuery) query.value = '' }
    async function read(reference, page = 1, size = TRACE_PAGE_SIZE) {
      if (disposed) return
      const number = typeof reference === 'string' ? reference.trim() : query.value.trim()
      if (loading.value && requested.value === number && requestedPage.value === page && requestedSize === size) return
      stop(); requested.value = number; requestedPage.value = page; requestedSize = size
      if (!number) { report.value = null; error.value = `请输入${label}编号后查询`; ElMessage.warning(`请输入${label}编号`); return }
      const version = ++generation, owner = accountScope(), currentRead = new AbortController()
      controller = currentRead; loading.value = true; error.value = ''
      if (report.value?.[field] !== number) report.value = null
      const isCurrent = () => !disposed && version === generation && owner === accountScope()
      async function fetchPage(target) {
        const response = await api(number, { signal: currentRead.signal, params: { page: target, size } })
        if (!isCurrent()) return
        const payload = response.data
        if (payload?.code !== 200) {
          const message = typeof payload?.message === 'string' ? payload.message : `${label}追溯响应不完整，请重新查询核对`
          throw Object.assign(new Error(message), { traceCode: payload?.code })
        }
        return readTraceReport(payload.data, field, number, target, size)
      }
      try {
        let result = await fetchPage(page)
        if (!isCurrent()) return
        if (result.page > 1 && (result.page - 1) * result.size >= result.total) {
          requestedPage.value = 1
          result = await fetchPage(1)
          if (!isCurrent()) return
        }
        report.value = result
        if (page === 1) ElMessage.success(`已读取${label}追溯摘要`)
      } catch (failure) {
        if (!isCurrent() || currentRead.signal.aborted) return
        if ([401, 403, 404].includes(failure.response?.status ?? failure.traceCode)) report.value = null
        error.value = failure.response?.data?.message || failure.message || `${label}追溯读取失败，请重新查询核对`
      } finally { if (isCurrent()) { controller = null; loading.value = false } }
    }
    function changePage(page) {
      const value = report.value
      if (!loading.value && value?.page && Number.isSafeInteger(page) && page > 0 && page !== value.page) return read(value[field], page, value.size)
    }
    function changeSize(size) {
      const value = report.value
      if (!loading.value && value?.page && TRACE_PAGE_SIZES.includes(size) && size !== value.size) return read(value[field], 1, size)
    }
    const refresh = () => read(report.value?.[field], report.value?.page ?? 1, report.value?.size ?? TRACE_PAGE_SIZE)
    const retry = () => read(requested.value, requestedPage.value, requestedSize)
    function forgetTasks(ids) {
      const denied = new Set(ids)
      if (!report.value?.records.some(task => denied.has(task.taskId) || denied.has(task.sourceTaskId))) return
      stop()
      report.value = null
      error.value = '关联任务的访问范围已变化，请重新读取'
    }
    return { read, reset, requested, requestedPage, changePage, changeSize, refresh, retry, forgetTasks }
  }
  const workOrderReader = createReader({ field: 'workOrderNo', label: '工单', query: workOrderTraceNo, loading: workOrderTraceLoading, report: workOrderTraceReport, error: workOrderTraceError, api: fetchWorkOrderTraceReport })
  const batchReader = createReader({ field: 'batchNo', label: '批次', query: batchTraceNo, loading: batchTraceLoading, report: batchTraceReport, error: batchTraceError, api: fetchBatchTraceReport })
  const loadWorkOrderTraceReport = workOrderReader.read, loadBatchTraceReport = batchReader.read
  const refreshWorkOrderTraceReport = workOrderReader.refresh
  const refreshBatchTraceReport = batchReader.refresh
  const ensureDefaultWorkOrderNo = async () => {
    if (!traceReferencesLoaded.value) await loadTraceReferences()
    workOrderTraceNo.value = workOrderTraceNo.value || businessWorkOrderNos.value[0] || ''
    return !!workOrderTraceNo.value
  }
  const ensureDefaultBatchNo = async () => {
    if (!traceReferencesLoaded.value) await loadTraceReferences()
    batchTraceNo.value = batchTraceNo.value || businessBatchNos.value[0] || ''
    return !!batchTraceNo.value
  }
  async function loadBusinessWorkOrderTrace(number) { if (disposed || workOrderTraceLoading.value) return; workOrderTraceNo.value = number; await loadWorkOrderTraceReport() }
  async function loadBusinessBatchTrace(number) { if (disposed || batchTraceLoading.value) return; batchTraceNo.value = number; await loadBatchTraceReport() }
  watch(accountScope, () => { workOrderReader.reset(true); batchReader.reset(true); resetReferences() }, { flush: 'sync' })
  onBeforeUnmount(() => { disposed = true; workOrderReader.reset(); batchReader.reset(); resetReferences() })
  return {
    workOrderTraceNo, workOrderTraceLoading, workOrderTraceReport, workOrderTraceError,
    batchTraceNo, batchTraceLoading, batchTraceReport, batchTraceError,
    businessWorkOrderNos, businessBatchNos, ensureDefaultWorkOrderNo, ensureDefaultBatchNo,
    traceReferencesLoading, traceReferencesError, loadTraceReferences,
    loadWorkOrderTraceReport, loadBatchTraceReport, refreshWorkOrderTraceReport, refreshBatchTraceReport,
    workOrderTraceRequestedNo: workOrderReader.requested, batchTraceRequestedNo: batchReader.requested,
    workOrderTraceRequestedPage: workOrderReader.requestedPage, batchTraceRequestedPage: batchReader.requestedPage,
    changeWorkOrderTracePage: workOrderReader.changePage, changeBatchTracePage: batchReader.changePage,
    changeWorkOrderTraceSize: workOrderReader.changeSize, changeBatchTraceSize: batchReader.changeSize,
    tracePageSizes: TRACE_PAGE_SIZES,
    retryWorkOrderTraceReport: workOrderReader.retry, retryBatchTraceReport: batchReader.retry,
    loadBusinessWorkOrderTrace, loadBusinessBatchTrace,
    forgetTasks: ids=>{workOrderReader.forgetTasks(ids);batchReader.forgetTasks(ids)}
  }
}
