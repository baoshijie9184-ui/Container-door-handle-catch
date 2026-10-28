import { ref, watch, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchBatchTraceReport, fetchWorkOrderTraceReport, fetchTraceReferenceTasks } from '../api/detection'
import { readTraceReferences } from '../utils/traceReferences.js'

function readTraceReport(value, field, expected) {
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
    function stop() { generation++; controller?.abort(); controller = null; loading.value = false }
    function reset(clearQuery = false) { stop(); requested.value = ''; report.value = null; error.value = ''; if (clearQuery) query.value = '' }
    async function read(reference) {
      if (disposed) return
      const number = typeof reference === 'string' ? reference.trim() : query.value.trim()
      if (loading.value && requested.value === number) return
      stop(); requested.value = number
      if (!number) { report.value = null; error.value = `请输入${label}编号后查询`; ElMessage.warning(`请输入${label}编号`); return }
      const version = ++generation, owner = accountScope(), currentRead = new AbortController()
      controller = currentRead; loading.value = true; error.value = ''
      if (report.value?.[field] !== number) report.value = null
      try {
        const response = await api(number, { signal: currentRead.signal })
        if (disposed || version !== generation || owner !== accountScope()) return
        if (response.data?.code === 200) {
          report.value = readTraceReport(response.data.data, field, number)
          ElMessage.success(`已读取${label}追溯摘要`)
        } else {
          if ([401, 403, 404].includes(response.data?.code)) report.value = null
          error.value = typeof response.data?.message === 'string' ? response.data.message : `${label}追溯响应不完整，请重新查询核对`
        }
      } catch (failure) {
        if (disposed || version !== generation || owner !== accountScope() || currentRead.signal.aborted) return
        if ([401, 403, 404].includes(failure.response?.status)) report.value = null
        error.value = typeof failure.response?.data?.message === 'string' ? failure.response.data.message : `${label}追溯本次未能完整核实，请核对编号与当前账号范围后重新读取`
      } finally { if (!disposed && version === generation && owner === accountScope()) { controller = null; loading.value = false } }
    }
    return { read, reset, requested }
  }
  const workOrderReader = createReader({ field: 'workOrderNo', label: '工单', query: workOrderTraceNo, loading: workOrderTraceLoading, report: workOrderTraceReport, error: workOrderTraceError, api: fetchWorkOrderTraceReport })
  const batchReader = createReader({ field: 'batchNo', label: '批次', query: batchTraceNo, loading: batchTraceLoading, report: batchTraceReport, error: batchTraceError, api: fetchBatchTraceReport })
  const loadWorkOrderTraceReport = workOrderReader.read, loadBatchTraceReport = batchReader.read
  const refreshWorkOrderTraceReport = () => loadWorkOrderTraceReport(workOrderTraceReport.value?.workOrderNo)
  const refreshBatchTraceReport = () => loadBatchTraceReport(batchTraceReport.value?.batchNo)
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
    loadBusinessWorkOrderTrace, loadBusinessBatchTrace
  }
}
