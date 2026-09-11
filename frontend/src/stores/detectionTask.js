/**
 * 检测任务 Store - 统一导出入口
 * 拆分为三个独立 store：
 * - taskStore: 任务状态管理、常量、工具函数
 * - uploadStore: OSS 上传逻辑
 * - pollingStore: 轮询逻辑、任务启动
 */

// 导出常量（保持向后兼容）
export { CATEGORY_LABELS, CATEGORY_COLORS, CATEGORY_ALIASES } from './taskStore'

// 导出各个 store
export { useTaskStore } from './taskStore'
export { useUploadStore } from './uploadStore'
export { usePollingStore } from './pollingStore'

// 为了向后兼容，提供一个组合的 useDetectionTaskStore
import { useTaskStore } from './taskStore'
import { useUploadStore } from './uploadStore'
import { usePollingStore } from './pollingStore'

/**
 * @deprecated 请使用 useTaskStore、useUploadStore、usePollingStore
 */
export const useDetectionTaskStore = () => {
  const taskStore = useTaskStore()
  const uploadStore = useUploadStore()
  const pollingStore = usePollingStore()

  return {
    // taskStore
    ...taskStore,
    // uploadStore
    ...uploadStore,
    // pollingStore
    ...pollingStore
  }
}
