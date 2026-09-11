import { ref } from 'vue'

const normalizeHistoryRecord = (record = {}, taskStore) => {
  const localTask = taskStore.taskList.find(task => task.taskId === record.taskId)
  if (localTask) return localTask
  return {
    ...record,
    imageCount: record.totalImages || 0,
    result: null,
    captureInfo: {
      captureDate: record.captureDate || '',
      region: record.region || '',
      collector: record.collector || '',
      deviceName: record.deviceName || '',
      imageFolderName: record.imageFolderName || ''
    }
  }
}

export function useDetectionHistory(taskStore, pollingStore) {
  const historySearchKeyword = ref('')
  const historyFilterCollector = ref('')
  const historyFilterDevice = ref('')
  const historyFilterRegion = ref('')
  const historyPage = ref(1)
  const historyPageSize = ref(10)
  const historyTotal = ref(0)
  const historyRecords = ref([])
  const historyLoading = ref(false)

  const buildHistoryFilters = () => {
    const filters = {}
    if (historySearchKeyword.value.trim()) filters.keyword = historySearchKeyword.value.trim()
    if (historyFilterCollector.value.trim()) filters.collector = historyFilterCollector.value.trim()
    if (historyFilterDevice.value.trim()) filters.deviceName = historyFilterDevice.value.trim()
    if (historyFilterRegion.value.trim()) filters.region = historyFilterRegion.value.trim()
    return filters
  }

  const fetchHistoryWithFilters = async (page, size) => {
    historyLoading.value = true
    try {
      const p = page || historyPage.value
      const s = size || historyPageSize.value
      const result = await pollingStore.fetchTaskList(p, s, '', '', buildHistoryFilters())
      if (result) {
        historyRecords.value = (result.records || []).map(record => normalizeHistoryRecord(record, taskStore))
        historyTotal.value = result.total || 0

        const completedIds = historyRecords.value
          .filter(task => task.stage === 'completed' || task.stage === 'failed')
          .map(task => task.taskId)
        if (completedIds.length) {
          await pollingStore.fetchTaskResults(completedIds)
          historyRecords.value = historyRecords.value.map(task => {
            const updated = taskStore.taskList.find(item => item.taskId === task.taskId)
            return updated || task
          })
        }
      }
    } finally {
      historyLoading.value = false
    }
  }

  const onHistorySearch = () => {
    historyPage.value = 1
    fetchHistoryWithFilters(1)
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

  return {
    historySearchKeyword,
    historyFilterCollector,
    historyFilterDevice,
    historyFilterRegion,
    historyPage,
    historyPageSize,
    historyTotal,
    historyRecords,
    historyLoading,
    buildHistoryFilters,
    fetchHistoryWithFilters,
    onHistorySearch,
    onHistoryPageChange,
    onHistorySizeChange
  }
}
