import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchQualityQueue } from '../api/detection'
import { normalizeQualityQueueRecord } from '../utils/qualityRecords'

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
  const qualityQueueTotal = ref(0)
  const qualityQueuePage = ref(1)
  const qualityQueuePageSize = ref(10)

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

  return {
    activeQualityQueue,
    qualityQueueLoading,
    qualityQueueRecords,
    qualityQueueTotal,
    qualityQueuePage,
    qualityQueuePageSize,
    qualityQueues,
    loadQualityQueue,
    switchQualityQueue,
    onQualityQueueSizeChange
  }
}
