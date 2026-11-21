import { captureAccountRequest } from '../api/request'
import { mutationHeaders, responseResourceVersion } from '../utils/mutationVersion'
import { beijingDateTime } from '../utils/beijingTime'
import { readAccountPreference } from '../utils/accountPreferences'

const POLL_INTERVAL_MS = 1500
const POLL_TIMEOUT_MS = 120000

const wait = (milliseconds) => new Promise(resolve => setTimeout(resolve, milliseconds))

const requireSuccess = (response, fallbackMessage) => {
  if (!response.data || response.data.code !== 200) {
    throw new Error(response.data?.message || fallbackMessage)
  }
  return response.data.data
}

const buildCaptureInfo = (file) => ({
  captureDate: beijingDateTime(new Date()).slice(0, 10),
  collector: readAccountPreference('username').value || 'web-user',
  deviceName: 'WEB-SINGLE-UPLOAD',
  imageFolderName: `single-${file.name}`
})

const toOssProxyUrl = (putUrl) => {
  const url = new URL(putUrl)
  return `/oss-upload${url.pathname}${url.search}`
}

const mapCompletedResult = (taskId, result, status) => {
  const summary = result.statistics?.singleImageResult
  const preview = result.previewImages?.[0]
  const confidenceMissing = summary?.confidence === null || summary?.confidence === undefined
  const noTargets = result.statistics?.noDetectionImages === 1 && result.statistics?.successfulImages === 1
  if ((!noTargets && (!summary?.category || confidenceMissing)) || !preview?.annotatedUrl) {
    throw new Error('远程结果不完整，请核对检测记录')
  }
  return {
    taskId,
    status,
    category: noTargets ? '未检出目标' : summary.category,
    targetCount: Object.values(result.statistics?.classCounts || {}).reduce((sum, n) => sum + Number(n), 0),
    modelMaintenance: result.modelMaintenance,
    confidence: noTargets ? null : Number(summary.confidence),
    annotatedImagePath: preview.annotatedUrl,
    processedImagePath: preview.originalUrl || '',
    source: 'KAFKA_REMOTE'
  }
}

export const detectSingleImageViaKafka = async ({ file, modelId, threshold, onStatus }) => {
  const request=captureAccountRequest()
  const createResponse = await request.post('/api/detection/tasks', {
    taskType: 'SINGLE',
    modelId: modelId || null,
    threshold,
    captureInfo: buildCaptureInfo(file),
    files: [{
      fileName: file.name,
      contentType: file.type || 'application/octet-stream',
      relativePath: file.name,
      fileSize: file.size
    }]
  })
  request.assert()
  const task = requireSuccess(createResponse, '准备单图检测失败')
  const uploadVersion=responseResourceVersion(createResponse)
  if (typeof task?.taskId === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(task.taskId)) onStatus?.({taskId:task.taskId,stage:'CREATING',message:'正在准备上传原图'})
  const upload = task?.uploadUrls?.[0]
  if (!task?.taskId || !upload?.putUrl || !upload?.objectKey) {
    throw new Error('未能取得完整的图片上传信息')
  }

  onStatus?.({ taskId: task.taskId, stage: 'UPLOADING', message: '正在上传原图' })
  await request.put(toOssProxyUrl(upload.putUrl), file, {
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
    timeout: 30000
  })

  request.assert()
  onStatus?.({ taskId: task.taskId, stage: 'QUEUED', message: '原图已上传，正在提交检测' })
  const uploadedResponse = await request.post(`/api/detection/tasks/${task.taskId}/uploaded`, {
    modelId: modelId || null,
    threshold,
    uploadedFiles: [{ fileName: upload.fileName, objectKey: upload.objectKey }]
  },{headers:mutationHeaders(uploadVersion)})
  requireSuccess(uploadedResponse, '提交图片检测失败')

  const deadline = Date.now() + POLL_TIMEOUT_MS
  while (Date.now() < deadline) {
    const progressResponse = await request.get(`/api/detection/tasks/${task.taskId}`)
    request.assert()
    const progress = requireSuccess(progressResponse, '读取检测进度失败') || {}
    onStatus?.({
      taskId: task.taskId,
      stage: progress.stage || progress.status,
      message: ''
    })
    if (progress.status === 'FAILED') {
      const failure = new Error(progress.errorMessage || '图片检测失败')
      failure.taskFailed = true
      throw failure
    }
    if (progress.status === 'COMPLETED' || progress.status === 'PARTIAL_FAILED') {
      const resultResponse = await request.get(`/api/detection/tasks/${task.taskId}/result`)
      const result = requireSuccess(resultResponse, '读取检测结果失败') || {}
      request.assert()
      return mapCompletedResult(task.taskId, result, progress.status)
    }
    await wait(POLL_INTERVAL_MS)
  }
  throw new Error('等待检测结果超时')
}
