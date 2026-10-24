import { ref, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchQualityReport } from '../api/detection'
import {beijingExportStamp} from '../utils/beijingTime'

export const safeFilePart = (value) => String(value || 'unknown')
  .replace(/[\\/:*?"<>|\s]+/g, '-')
  .replace(/-+/g, '-')
  .replace(/^-|-$/g, '')

export const reportTimestamp = () => beijingExportStamp()

export const downloadJsonReport = (payload, fileName) => {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function useQualityReportDownloads({
  batchTraceNo,
  batchTraceReport,
  workOrderTraceNo,
  workOrderTraceReport,
  getAccountScope = () => null
}) {
  const reportDownloading = ref(false)
  const actorScope = () => JSON.stringify(getAccountScope())
  let disposed = false
  onBeforeUnmount(() => { disposed = true })

  const downloadTaskQualityReport = async (taskId) => {
    if (disposed || reportDownloading.value) return
    if (!taskId) {
      ElMessage.warning('缺少任务编号，无法下载任务摘要')
      return
    }
    const actor = actorScope()
    reportDownloading.value = true
    try {
      const response = await fetchQualityReport(taskId)
      if (disposed || actor !== actorScope()) return
      if (response.data?.code === 200) {
        const report = response.data.data
        if (!report || report.taskId !== taskId) throw new Error('返回的任务摘要与当前选择不一致，请重新核对')
        downloadJsonReport(report, `quality-report-${safeFilePart(taskId)}-${reportTimestamp()}.json`)
        ElMessage.success('已发起任务摘要下载')
      } else {
        ElMessage.error(response.data?.message || '任务摘要读取失败')
      }
    } catch (error) {
      if (!disposed && actor === actorScope()) ElMessage.error(error.response?.data?.message || error.message || '任务摘要下载未发起，请重新核对')
    } finally {
      reportDownloading.value = false
    }
  }

  const downloadBatchTraceReport = () => {
    if (disposed) return
    if (!batchTraceReport.value) {
      ElMessage.warning('请先读取批次追溯摘要')
      return
    }
    const batchNo = batchTraceReport.value.batchNo || batchTraceNo.value
    downloadJsonReport({
      ...batchTraceReport.value,
      exportedAt: new Date().toISOString(),
      exportedBy: 'DoorHandleCatch Web'
    }, `batch-trace-${safeFilePart(batchNo)}-${reportTimestamp()}.json`)
    ElMessage.success('已发起本次批次摘要下载')
  }

  const downloadWorkOrderTraceReport = () => {
    if (disposed) return
    if (!workOrderTraceReport.value) {
      ElMessage.warning('请先读取工单追溯摘要')
      return
    }
    const workOrderNo = workOrderTraceReport.value.workOrderNo || workOrderTraceNo.value
    downloadJsonReport({
      ...workOrderTraceReport.value,
      exportedAt: new Date().toISOString(),
      exportedBy: 'DoorHandleCatch Web'
    }, `work-order-trace-${safeFilePart(workOrderNo)}-${reportTimestamp()}.json`)
    ElMessage.success('已发起本次工单摘要下载')
  }

  return {
    reportDownloading,
    downloadTaskQualityReport,
    downloadBatchTraceReport,
    downloadWorkOrderTraceReport
  }
}
