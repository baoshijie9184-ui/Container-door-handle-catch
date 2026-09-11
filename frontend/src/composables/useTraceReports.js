import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchBatchTraceReport, fetchWorkOrderTraceReport } from '../api/detection'
import { businessBatchNos, businessWorkOrderNos } from '../config/businessTracePresets'

export function useTraceReports() {
  const workOrderTraceNo = ref('')
  const workOrderTraceLoading = ref(false)
  const workOrderTraceReport = ref(null)
  const batchTraceNo = ref('')
  const batchTraceLoading = ref(false)
  const batchTraceReport = ref(null)

  const ensureDefaultWorkOrderNo = () => {
    workOrderTraceNo.value = workOrderTraceNo.value || businessWorkOrderNos[0]
  }

  const ensureDefaultBatchNo = () => {
    batchTraceNo.value = batchTraceNo.value || businessBatchNos[0]
  }

  const loadWorkOrderTraceReport = async () => {
    const workOrderNo = workOrderTraceNo.value.trim()
    if (!workOrderNo) {
      ElMessage.warning('请输入工单号')
      return
    }
    workOrderTraceLoading.value = true
    workOrderTraceReport.value = null
    try {
      const response = await fetchWorkOrderTraceReport(workOrderNo)
      if (response.data?.code === 200) {
        workOrderTraceReport.value = response.data.data
        ElMessage.success('工单追溯报告已生成')
      } else {
        ElMessage.error(response.data?.message || '获取工单追溯失败')
      }
    } catch (error) {
      console.error('获取工单追溯失败:', error)
      ElMessage.error(error.response?.data?.message || '获取工单追溯失败')
    } finally {
      workOrderTraceLoading.value = false
    }
  }

  const loadBatchTraceReport = async () => {
    const batchNo = batchTraceNo.value.trim()
    if (!batchNo) {
      ElMessage.warning('请输入批次号')
      return
    }
    batchTraceLoading.value = true
    batchTraceReport.value = null
    try {
      const response = await fetchBatchTraceReport(batchNo)
      if (response.data?.code === 200) {
        batchTraceReport.value = response.data.data
        ElMessage.success('批次追溯报告已生成')
      } else {
        ElMessage.error(response.data?.message || '获取批次追溯失败')
      }
    } catch (error) {
      console.error('获取批次追溯失败:', error)
      ElMessage.error(error.response?.data?.message || '获取批次追溯失败')
    } finally {
      batchTraceLoading.value = false
    }
  }

  const loadBusinessWorkOrderTrace = async (workOrderNo) => {
    workOrderTraceNo.value = workOrderNo
    await loadWorkOrderTraceReport()
  }

  const loadBusinessBatchTrace = async (batchNo) => {
    batchTraceNo.value = batchNo
    await loadBatchTraceReport()
  }

  return {
    workOrderTraceNo,
    workOrderTraceLoading,
    workOrderTraceReport,
    batchTraceNo,
    batchTraceLoading,
    batchTraceReport,
    businessWorkOrderNos,
    businessBatchNos,
    ensureDefaultWorkOrderNo,
    ensureDefaultBatchNo,
    loadWorkOrderTraceReport,
    loadBatchTraceReport,
    loadBusinessWorkOrderTrace,
    loadBusinessBatchTrace
  }
}
