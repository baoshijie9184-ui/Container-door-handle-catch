import request from '../api/request'

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
  captureDate: new Date().toISOString().slice(0, 10),
  region: '单图检测',
  collector: localStorage.getItem('username') || 'web-user',
  deviceName: 'WEB-SINGLE-UPLOAD',
  imageFolderName: `single-${file.name}`
})

const toOssProxyUrl = (putUrl) => {
  const url = new URL(putUrl)
  return `/oss-upload${url.pathname}${url.search}`
}

const mapCompletedResult = (taskId, result) => {
  const summary = result.statistics?.singleImageResult
  const preview = result.previewImages?.[0]
  const confidenceMissing = summary?.confidence === null || summary?.confidence === undefined
  if (!summary?.category || confidenceMissing || !preview?.annotatedUrl) {
    throw new Error(`远程结果不完整，任务编号：${taskId}`)
  }
  return {
    taskId,
    category: summary.category,
    confidence: Number(summary.confidence),
    annotatedImagePath: preview.annotatedUrl,
    processedImagePath: preview.originalUrl || '',
    source: 'KAFKA_REMOTE'
  }
}

export const detectSingleImageViaKafka = async ({ file, modelId, threshold, onStatus }) => {
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
  const task = requireSuccess(createResponse, '创建单图 Kafka 任务失败')
  const upload = task?.uploadUrls?.[0]
  if (!task?.taskId || !upload?.putUrl || !upload?.objectKey) {
    throw new Error('创建单图 Kafka 任务失败：上传信息不完整')
  }

  onStatus?.({ taskId: task.taskId, stage: 'UPLOADING', message: '正在上传原图到 OSS' })
  await request.put(toOssProxyUrl(upload.putUrl), file, {
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
    timeout: 30000
  })

  onStatus?.({ taskId: task.taskId, stage: 'QUEUED', message: '原图已上传，正在提交 Kafka' })
  const uploadedResponse = await request.post(`/api/detection/tasks/${task.taskId}/uploaded`, {
    modelId: modelId || null,
    threshold,
    uploadedFiles: [{ fileName: upload.fileName, objectKey: upload.objectKey }]
  })
  requireSuccess(uploadedResponse, '提交 Kafka 检测任务失败')

  const deadline = Date.now() + POLL_TIMEOUT_MS
  while (Date.now() < deadline) {
    const progressResponse = await request.get(`/api/detection/tasks/${task.taskId}`)
    const progress = requireSuccess(progressResponse, '查询 Kafka 检测进度失败') || {}
    onStatus?.({
      taskId: task.taskId,
      stage: progress.stage || progress.status,
      message: progress.message || ''
    })
    if (progress.status === 'FAILED') {
      throw new Error(`${progress.errorMessage || progress.message || 'Kafka 远程检测失败'}，任务编号：${task.taskId}`)
    }
    if (progress.status === 'COMPLETED' || progress.status === 'PARTIAL_FAILED') {
      const resultResponse = await request.get(`/api/detection/tasks/${task.taskId}/result`)
      const result = requireSuccess(resultResponse, '获取 Kafka 远程检测结果失败') || {}
      return mapCompletedResult(task.taskId, result)
    }
    await wait(POLL_INTERVAL_MS)
  }
  throw new Error(`Kafka 远程检测超时，任务编号：${task.taskId}`)
}
