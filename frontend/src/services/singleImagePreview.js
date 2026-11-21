import { captureAccountRequest } from '../api/request'

export const fetchSingleImageModels = () => captureAccountRequest().get('/api/models/single-test-models')

export async function previewSingleImage({ file, modelId, threshold, signal }) {
  if (!file?.size || file.size > 10 * 1024 * 1024 || !['image/jpeg', 'image/png'].includes(file.type)) {
    throw new Error('请选择 10 MB 以内的 JPG 或 PNG 图片')
  }

  const response = await captureAccountRequest().post('/api/image-detection/preview', file, {
    params: { modelId, threshold },
    headers: { 'Content-Type': file.type },
    timeout: 105000,
    signal
  })
  const { code, data, message } = response.data || {}
  if (code !== 200) throw new Error(message || '单图检测失败，请重试')
  if (!data?.annotationBase64 || !Number.isInteger(data.targetCount) || (modelId && modelId !== data.modelId)) {
    throw new Error('单图检测结果不完整，请重试')
  }
  const { annotationBase64, ...result } = data
  return { ...result, annotatedImagePath: `data:image/jpeg;base64,${annotationBase64}` }
}
