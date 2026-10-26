import { knownCount } from './countPresentation'

// Use counts from the same persisted result, never confidence or legacy rates.
export function noDetectionSummary(result) {
  const stats = result?.statistics
  if (!stats || typeof stats !== 'object' || Array.isArray(stats)) {
    return { value: '未记录', description: '结果未提供整图未检出计数，不能从置信度推算。' }
  }
  const missing = stats.noDetectionImages == null
  const count = knownCount(stats.noDetectionImages)
  const successful = knownCount(result.successfulImages ?? stats.successfulImages)
  const failed = knownCount(result.failedImages ?? stats.failedImages)
  const total = knownCount(result.totalImages ?? stats.totalImages)
  const invalid = count === null && !missing ||
    ['successfulImages', 'failedImages', 'totalImages'].some(key => {
      const root = result[key], nested = stats[key]
      return root != null && knownCount(root) === null || nested != null && knownCount(nested) === null ||
        root != null && nested != null && knownCount(root) !== knownCount(nested)
    }) || count !== null && successful !== null && count > successful ||
    total !== null && successful !== null && (successful > total ||
      failed !== null && (!Number.isSafeInteger(successful + failed) || successful + failed !== total))
  if (invalid) return { value: '待核对', description: '图片计数无效或不一致，暂不计算比例。' }
  if (missing || successful === null) return { value: '未记录', description: '缺少未检出或成功检测图片数，暂不计算比例。' }
  const status = String(result.status || '').toUpperCase()
  if (!['COMPLETED', 'PARTIAL_FAILED', 'FAILED'].includes(status)) {
    return { value: '待完成', description: '任务尚未结束或结束状态未记录，暂不计算最终比例。' }
  }
  if (successful === 0) return { value: '无法统计', description: '没有成功完成检测的图片；检测失败不作为未检出。' }
  const description = `${count.toLocaleString('zh-CN')} 张未检出 / ${successful.toLocaleString('zh-CN')} 张成功检测；${failed === null ? '失败张数未记录' : `${failed.toLocaleString('zh-CN')} 张检测失败另列`}。`
  return { value: `${(count / successful * 100).toFixed(2)}%`, description }
}
