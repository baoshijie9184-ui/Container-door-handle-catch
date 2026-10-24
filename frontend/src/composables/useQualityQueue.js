import { ref, onBeforeUnmount } from 'vue'
import { fetchQualityQueue } from '../api/detection'
import { normalizeQualityQueueRecord } from '../utils/qualityRecords'
import { knownCount } from '../utils/countPresentation'

export const qualityQueues = [
  { label: '全部待处理', value: 'ALL_ACTIONABLE', hint: '复核/处置/异常' },
  { label: '待复核', value: 'PENDING_REVIEW', hint: '检测完成待确认' },
  { label: '待处置', value: 'PENDING_DISPOSITION', hint: '复核后需决策' },
  { label: '待返工', value: 'REWORK_REQUIRED', hint: '产线返修' },
  { label: '待复检', value: 'RECHECK_REQUIRED', hint: '二次确认' },
  { label: '暂挂', value: 'HOLD', hint: '人工保留' },
  { label: '失败', value: 'FAILED', hint: '异常处理' }
]

const resolvePageNumber = (page, fallback) => {
  const value = Number(page)
  return Number.isInteger(value) && value > 0 ? value : fallback
}

export function useQualityQueue() {
  const activeQualityQueue = ref('ALL_ACTIONABLE')
  const qualityQueueLoading = ref(false)
  const qualityQueueRecords = ref([])
  const qualityQueueTotal = ref(null)
  const qualityQueueError = ref('')
  const qualityQueueLoaded = ref(false)
  const qualityQueuePage = ref(1)
  const qualityQueuePageSize = ref(10)
  let generation = 0, requestedKey = '', active = true
  onBeforeUnmount(() => { active = false; generation++ })

  const loadQualityQueue = async (page = qualityQueuePage.value) => {
    if (!active) return
    const targetPage = resolvePageNumber(page, qualityQueuePage.value)
    const queue = activeQualityQueue.value, size = qualityQueuePageSize.value
    const request = ++generation, key = `${queue}:${targetPage}:${size}`
    if (key !== requestedKey) { qualityQueueRecords.value = []; qualityQueueTotal.value = null; qualityQueueLoaded.value = false }
    requestedKey = key
    qualityQueueLoading.value = true
    qualityQueueError.value = ''
    try {
      const response = await fetchQualityQueue(queue, targetPage, size)
      if (request !== generation || !active) return
      const data = response.data?.data
      if (response.data?.code !== 200 || !Array.isArray(data?.records) || data.records.some(row => !row || typeof row.taskId !== 'string')) throw new Error('质检队列返回内容不完整，请重新读取')
      qualityQueueRecords.value = data.records.map(normalizeQualityQueueRecord)
      qualityQueueTotal.value = knownCount(data.total)
      qualityQueuePage.value = targetPage
      qualityQueueLoaded.value = true
    } catch (error) {
      if (request !== generation || !active) return
      if ([401, 403].includes(error.response?.status)) { qualityQueueRecords.value = []; qualityQueueTotal.value = null; qualityQueueLoaded.value = false }
      qualityQueueError.value = '质检队列暂不可读取，请重新读取；已有记录可能不是最新状态。'
    } finally {
      if (request === generation && active) qualityQueueLoading.value = false
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

  return {
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
  }
}
