<template><span>{{ message || fallback }}</span></template>
<script setup>
import { ref, watch } from 'vue'
import { accountFetch } from '../utils/accountFetch'

const props = defineProps({ src: String, fallback: { type: String, default: '图片暂不可读取' } })
const message = ref('')
const reasons = {
  BILLING_OVERDUE: '阿里云账号余额不足，OSS 图片服务已受限。请联系主管处理欠费。',
  DISABLED: '阿里云 OSS 账号或存储空间已停用，请主管核对服务状态。',
  NOT_CONFIGURED: '当前环境尚未配置 OSS 图片预览。',
  CONFIGURATION: 'OSS 图片存储配置无效，请主管核对。',
  ACCESS_DENIED: 'OSS 拒绝了这张图片的读取请求。',
  MISSING: '这张图片在 OSS 中不存在。',
  EMPTY: 'OSS 返回了空文件。',
  UNREACHABLE: '暂时无法连接 OSS 图片服务。',
  READABLE: 'OSS 中的文件可读取，请重试或核对图片格式。'
}
watch(() => props.src, async (src, previous, cleanup) => {
  message.value = ''
  if (!src) return
  const controller = new AbortController()
  cleanup(() => controller.abort())
  try {
    const url = new URL(src, window.location.href)
    if (url.origin !== window.location.origin || url.pathname !== '/api/oss/preview' || !url.searchParams.has('key')) return
    url.pathname = '/api/oss/preview-status'
    const response = await accountFetch(url.pathname + url.search, { signal: controller.signal, cache: 'no-store' })
    const data = await response.json()
    if (controller.signal.aborted) return
    if (response.status === 403 || data.code === 403) message.value = '当前账号无权查看这张图片。'
    else if (response.ok) message.value = reasons[data.reason] || ''
  } catch { /* Keep the generic image error when the diagnostic request is unavailable. */ }
}, { immediate: true })
</script>
