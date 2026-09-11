import { defineStore } from 'pinia'
import { ref } from 'vue'

export const CATEGORY_LABELS = {
  Normal: '正常',
  Bent: '弯曲',
  Deformed: '形变',
  Rusty: '锈蚀',
  Missing: '缺失',
  Compromised: '结构损伤'
}

export const CATEGORY_COLORS = {
  Normal: 'success',
  Bent: 'warning',
  Deformed: 'processing',
  Rusty: 'orange',
  Missing: 'error',
  Compromised: 'volcano'
}

export const CATEGORY_ALIASES = {
  正常: 'Normal',
  弯曲: 'Bent',
  形变: 'Deformed',
  锈蚀: 'Rusty',
  缺失: 'Missing',
  结构损伤: 'Compromised'
}

export const useTaskStore = defineStore('task', () => {
  const taskList = ref([])
  const selectedTaskId = ref(null)

  // ==================== localStorage 持久化 ====================

  // 节流标记，避免频繁写入
  let saveTimer = null
  let pendingSave = false

  const saveTaskList = () => {
    // 如果已有定时器等待，标记为待保存即可
    if (saveTimer) {
      pendingSave = true
      return
    }

    // 立即执行第一次保存
    doSave()

    // 设置节流定时器，2秒内的后续调用会被合并
    saveTimer = setTimeout(() => {
      if (pendingSave) {
        doSave()
        pendingSave = false
      }
      saveTimer = null
    }, 2000)
  }

  const doSave = () => {
    try {
      const savable = taskList.value.map(t => ({
        taskId: t.taskId,
        batchNo: t.batchNo,
        workOrderNo: t.workOrderNo,
        flowStatus: t.flowStatus,
        reviewStatus: t.reviewStatus,
        reviewConclusion: t.reviewConclusion,
        severityLevel: t.severityLevel,
        confirmedDefectCount: t.confirmedDefectCount,
        falsePositiveCount: t.falsePositiveCount,
        reviewRemark: t.reviewRemark,
        reviewer: t.reviewer,
        reviewedAt: t.reviewedAt,
        folderName: t.folderName,
        imageCount: t.imageCount,
        progressPercent: t.progressPercent,
        stage: t.stage,
        message: t.message,
        error: t.error,
        uploadedFiles: t.uploadedFiles,
        logs: t.logs,
        captureInfo: t.captureInfo,
        sourceOssPrefix: t.sourceOssPrefix || ''
      }))
      localStorage.setItem('taskList', JSON.stringify(savable))
    } catch (e) {
      console.error('[saveTaskList] 保存失败:', e)
    }
  }

  const loadTaskList = () => {
    try {
      const raw = localStorage.getItem('taskList')
      return raw ? JSON.parse(raw) : []
    } catch { return [] }
  }

  // -------- 文件级上传状态（task_<taskId>_files） --------

  const FILE_STATE_PREFIX = 'task_files_'

  const saveFileState = (taskId, state) => {
    try {
      localStorage.setItem(`${FILE_STATE_PREFIX}${taskId}`, JSON.stringify(state))
    } catch { /* localStorage 满了则忽略 */ }
  }

  const loadFileState = (taskId) => {
    try {
      const raw = localStorage.getItem(`${FILE_STATE_PREFIX}${taskId}`)
      return raw ? JSON.parse(raw) : null
    } catch { return null }
  }

  const removeFileState = (taskId) => {
    localStorage.removeItem(`${FILE_STATE_PREFIX}${taskId}`)
  }

  // 获取所有需要恢复的任务信息
  const getResumeTaskList = () => {
    const tasks = loadTaskList()
    return tasks
      .filter(t => t.stage === 'uploading')
      .map(t => {
        const fileState = loadFileState(t.taskId)
        const ci = t.captureInfo
        // 构建完整路径：采集时间 / 地区 / 采集员 / 采集设备 / 图片文件夹名称
        const fullPath = ci
          ? [ci.captureDate, ci.region, ci.collector, ci.deviceName, ci.imageFolderName].filter(Boolean).join(' / ')
          : t.folderName
        return {
          taskId: t.taskId,
          folderName: fullPath || t.folderName,
          imageCount: t.imageCount,
          uploadedCount: fileState ? fileState.completed.length : 0,
          failedCount: fileState ? fileState.failed.length : 0,
          totalCount: fileState ? fileState.total : t.imageCount
        }
      })
  }

  // ==================== 任务辅助函数 ====================

  const createTaskEntry = (taskId, folderName, imageCount, captureInfo) => ({
    taskId,
    batchNo: '',
    workOrderNo: '',
    flowStatus: 'UPLOADING',
    reviewStatus: 'PENDING',
    reviewConclusion: '',
    severityLevel: '',
    confirmedDefectCount: 0,
    falsePositiveCount: 0,
    reviewRemark: '',
    reviewer: '',
    reviewedAt: '',
    folderName,
    imageCount,
    progressPercent: 0,
    stage: 'uploading',
    message: '正在上传原图到 OSS...',
    error: '',
    result: null,
    uploadedFiles: [],
    pollingTimer: null,
    logs: [],
    createdAt: new Date().toLocaleString('zh-CN', { hour12: false }),
    updatedAt: new Date().toLocaleString('zh-CN', { hour12: false }),
    finishedAt: '',
    captureInfo: captureInfo || {}
  })

  const findTaskIndex = (taskId) => taskList.value.findIndex(t => t.taskId === taskId)

  const updateTask = (taskId, updates) => {
    const idx = findTaskIndex(taskId)
    if (idx === -1) return
    // 仅在 updates 未提供 updatedAt 时自动更新为当前时间
    if (!updates.updatedAt) {
      updates.updatedAt = new Date().toLocaleString('zh-CN', { hour12: false })
    }
    Object.assign(taskList.value[idx], updates)
  }

  const pushTaskLog = (taskId, text) => {
    const idx = findTaskIndex(taskId)
    if (idx === -1) return
    const task = taskList.value[idx]
    task.logs.unshift({
      id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
      time: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
      text
    })
    task.logs = task.logs.slice(0, 10)
    task.updatedAt = new Date().toLocaleString('zh-CN', { hour12: false })
  }

  const removeTask = (taskId) => {
    const idx = findTaskIndex(taskId)
    if (idx === -1) return
    const task = taskList.value[idx]
    if (task.pollingTimer) clearInterval(task.pollingTimer)
    taskList.value.splice(idx, 1)
    if (selectedTaskId.value === taskId) selectedTaskId.value = null
    saveTaskList()
  }

  // ==================== 状态/步骤工具函数 ====================

  const normalizeStage = (status, stage) => {
    const s = status || ''
    const st = stage || ''
    if (s === 'FAILED') return 'failed'
    if (s === 'COMPLETED' || s === 'PARTIAL_FAILED') return 'completed'
    if (st === 'DETECTING' || s === 'DETECTING') return 'detecting'
    if (st === 'QUEUED' || s === 'QUEUED') return 'queued'
    if (st === 'UPLOADED' || s === 'UPLOADED') return 'uploaded'
    if (st === 'UPLOADING' || s === 'UPLOADING') return 'uploading'
    return st?.toLowerCase() || 'unknown'
  }

  const taskTagColor = (task) => {
    if (task.stage === 'failed') return 'error'
    if (task.stage === 'completed') return 'success'
    if (task.stage === 'detecting' || task.stage === 'queued') return 'processing'
    if (task.stage === 'uploading') return 'orange'
    if (task.stage === 'uploaded') return 'blue'
    return 'default'
  }

  const taskTagType = (task) => {
    const color = taskTagColor(task)
    const map = {
      error: 'danger',
      processing: 'primary',
      orange: 'warning',
      blue: 'primary',
      default: 'info'
    }
    return map[color] || color
  }

  const taskTagText = (task) => {
    const map = {
      uploading: '上传中', uploaded: '待提交', queued: '已交给模型',
      detecting: '检测中', completed: '已完成', failed: '失败'
    }
    return map[task.stage] || '未知'
  }

  // 任务状态详情（进度条下方一行展示）
  const taskStatusDetail = (task) => {
    if (task.error) return { text: task.error, type: 'error' }
    const uploading = task.stage === 'uploading'
    const done = task.stage === 'completed' || task.stage === 'uploaded' || task.stage === 'queued' || task.stage === 'detecting'
    if (uploading || done) {
      const uploaded = task.uploadedFiles?.length || 0
      const total = task.imageCount || 0
      const failed = total - uploaded
      if (uploaded > 0 && failed > 0) return { text: `成功 ${uploaded} / 失败 ${failed} / 共 ${total} 张`, type: 'warn' }
      if (uploaded > 0) return { text: `已上传 ${uploaded} / ${total} 张`, type: 'info' }
      return { text: `共 ${total} 张`, type: 'info' }
    }
    if (task.result) {
      const s = task.result.successfulImages || 0
      const f = task.result.failedImages || 0
      return { text: `检测成功 ${s} 张，失败 ${f} 张`, type: f > 0 ? 'warn' : 'success' }
    }
    return { text: task.message || '', type: 'info' }
  }

  // 绝对时间格式化（到分钟）
  const formatAbsoluteTime = (dateStr) => {
    if (!dateStr) return ''
    try {
      const d = new Date(dateStr)
      if (isNaN(d.getTime())) return dateStr
      const month = String(d.getMonth() + 1).padStart(2, '0')
      const day = String(d.getDate()).padStart(2, '0')
      const hour = String(d.getHours()).padStart(2, '0')
      const min = String(d.getMinutes()).padStart(2, '0')
      return `${month}-${day} ${hour}:${min}`
    } catch { return dateStr }
  }

  // 相对时间格式化
  const formatRelativeTime = (dateStr) => {
    if (!dateStr) return ''
    try {
      const date = new Date(dateStr)
      if (isNaN(date.getTime())) return dateStr
      const now = new Date()
      const diffMs = now - date
      if (diffMs < 0) return formatAbsoluteTime(dateStr)
      const mins = Math.floor(diffMs / 60000)
      if (mins < 1) return '刚刚'
      if (mins < 60) return `${mins} 分钟前`
      const hours = Math.floor(mins / 60)
      if (hours < 24) return `${hours} 小时前`
      const days = Math.floor(hours / 24)
      if (days < 7) return `${days} 天前`
      return formatAbsoluteTime(dateStr)
    } catch { return dateStr }
  }

  const taskStepIndex = (task) => {
    if (task.stage === 'failed') return task.stage === 'queued' ? 0 : 1
    const map = { uploaded: 0, queued: 0, detecting: 1, completed: 3, failed: 2 }
    return map[task.stage] ?? -1
  }

  const taskStepDesc = (task, step) => {
    if (task.stage === 'failed') {
      if (step === 0) return ''
      if (step === 1) return '检测异常'
      return ''
    }
    const cur = taskStepIndex(task)
    if (cur >= 3) {
      if (step === 0) return '任务已提交'
      if (step === 1) return '模型推理完成'
      if (step === 2) return '结果已同步到 OSS'
      return ''
    }
    if (step === 0 && cur === 0) return '等待检测服务调度'
    if (step === 0 && cur > 0) return '已完成提交'
    if (step === 1 && cur === 1) return '正在执行模型推理'
    return ''
  }

  const buildTaskStatistics = (stats) => {
    const rows = []
    const classCounts = stats.classCounts || {}
    Object.keys(CATEGORY_LABELS).forEach((key) => {
      rows.push({ key: `class-${key}`, label: CATEGORY_LABELS[key], value: Number(classCounts[key] || 0) })
    })
    if (stats.noDetectionImages !== undefined) rows.push({ key: 'noDetectionImages', label: '未检出图片数', value: Number(stats.noDetectionImages || 0) })
    if (stats.missDetectionRate !== undefined) rows.push({ key: 'missDetectionRate', label: '漏检率', value: `${(Number(stats.missDetectionRate || 0) * 100).toFixed(2)}%` })
    if (stats.totalImages !== undefined) rows.push({ key: 'totalImages', label: '图片总数', value: Number(stats.totalImages || 0) })
    if (stats.successfulImages !== undefined) rows.push({ key: 'successfulImages', label: '成功图片数', value: Number(stats.successfulImages || 0) })
    if (stats.failedImages !== undefined) rows.push({ key: 'failedImages', label: '失败图片数', value: Number(stats.failedImages || 0) })
    return rows
  }

  return {
    taskList,
    selectedTaskId,
    saveTaskList,
    loadTaskList,
    saveFileState,
    loadFileState,
    removeFileState,
    getResumeTaskList,
    createTaskEntry,
    findTaskIndex,
    updateTask,
    pushTaskLog,
    removeTask,
    normalizeStage,
    taskTagColor,
    taskTagType,
    taskTagText,
    taskStatusDetail,
    formatAbsoluteTime,
    formatRelativeTime,
    taskStepIndex,
    taskStepDesc,
    buildTaskStatistics
  }
})
