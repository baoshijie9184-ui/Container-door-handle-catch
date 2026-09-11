import request from './request'

export const detectSingleImage = (formData) => request.post('/api/image-detection/upload', formData)

export const fetchAvailableModels = () => request.get('/api/models')

export const advanceDetectionTaskFlow = (taskId, target) => request.post(`/api/detection/tasks/${taskId}/flow`, null, {
  params: { target }
})

export const assignDetectionQualityTask = (taskId, payload) => request.post(`/api/detection/tasks/${taskId}/assignment`, payload)

export const reviewDetectionTask = (taskId, payload) => request.post(`/api/detection/tasks/${taskId}/review`, payload)

export const disposeDetectionTask = (taskId, payload) => request.post(`/api/detection/tasks/${taskId}/disposition`, payload)

export const submitDetectionReworkResult = (taskId, payload) => request.post(`/api/detection/tasks/${taskId}/rework-result`, payload)

export const fetchQualityQueue = (queue, page = 1, size = 20) => request.get('/api/detection/tasks/quality-queue', {
  params: { queue, page, size }
})

export const fetchQualityReport = (taskId) => request.get(`/api/detection/tasks/${taskId}/quality-report`)

export const fetchDefectGallery = (params = {}) => request.get('/api/detection/tasks/defect-gallery', {
  params
})

export const fetchDetectionTaskTrace = (taskId) => request.get(`/api/detection/tasks/${taskId}/trace`)

export const fetchBatchTraceReport = (batchNo) => request.get('/api/detection/tasks/batch-trace', {
  params: { batchNo }
})

export const fetchWorkOrderTraceReport = (workOrderNo) => request.get('/api/detection/tasks/work-order-trace', {
  params: { workOrderNo }
})
