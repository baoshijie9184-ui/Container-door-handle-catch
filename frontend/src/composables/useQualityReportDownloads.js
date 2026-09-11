import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchQualityReport } from '../api/detection'

export const safeFilePart = (value) => String(value || 'unknown')
  .replace(/[\\/:*?"<>|\s]+/g, '-')
  .replace(/-+/g, '-')
  .replace(/^-|-$/g, '')

export const reportTimestamp = () => {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
}

export const downloadJsonReport = (payload, fileName) => {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function useQualityReportDownloads({
  batchTraceNo,
  batchTraceReport,
  workOrderTraceNo,
  workOrderTraceReport
}) {
  const reportDownloading = ref(false)

  const downloadTaskQualityReport = async (taskId) => {
    if (!taskId) {
      ElMessage.warning('缺少任务编号，无法导出报告')
      return
    }
    reportDownloading.value = true
    try {
      const response = await fetchQualityReport(taskId)
      if (response.data?.code === 200) {
        const report = response.data.data
        downloadJsonReport(report, `quality-report-${safeFilePart(taskId)}-${reportTimestamp()}.json`)
        ElMessage.success('质检报告已导出')
      } else {
        ElMessage.error(response.data?.message || '导出质检报告失败')
      }
    } catch (error) {
      console.error('导出质检报告失败:', error)
      ElMessage.error(error.response?.data?.message || '导出质检报告失败')
    } finally {
      reportDownloading.value = false
    }
  }

  const downloadBatchTraceReport = () => {
    if (!batchTraceReport.value) {
      ElMessage.warning('请先生成批次追溯报告')
      return
    }
    const batchNo = batchTraceReport.value.batchNo || batchTraceNo.value
    downloadJsonReport({
      ...batchTraceReport.value,
      exportedAt: new Date().toISOString(),
      exportedBy: 'DoorHandleCatch Web'
    }, `batch-trace-${safeFilePart(batchNo)}-${reportTimestamp()}.json`)
    ElMessage.success('批次追溯报告已导出')
  }

  const downloadWorkOrderTraceReport = () => {
    if (!workOrderTraceReport.value) {
      ElMessage.warning('请先生成工单追溯报告')
      return
    }
    const workOrderNo = workOrderTraceReport.value.workOrderNo || workOrderTraceNo.value
    downloadJsonReport({
      ...workOrderTraceReport.value,
      exportedAt: new Date().toISOString(),
      exportedBy: 'DoorHandleCatch Web'
    }, `work-order-trace-${safeFilePart(workOrderNo)}-${reportTimestamp()}.json`)
    ElMessage.success('工单追溯报告已导出')
  }

  return {
    reportDownloading,
    downloadTaskQualityReport,
    downloadBatchTraceReport,
    downloadWorkOrderTraceReport
  }
}
