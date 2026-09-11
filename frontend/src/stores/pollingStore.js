import { defineStore } from 'pinia'
import request from '../api/request'
import { ElMessage } from 'element-plus'
import { useTaskStore } from './taskStore'

export const usePollingStore = defineStore('polling', () => {
  // ==================== 全局轮询管理 ====================

  // 单个全局定时器，管理所有任务的轮询
  let globalPollingTimer = null
  const POLLING_INTERVAL = 3000 // 3秒轮询一次

  // 启动全局轮询
  const startGlobalPolling = () => {
    if (globalPollingTimer) return // 已经在运行

    globalPollingTimer = setInterval(async () => {
      const taskStore = useTaskStore()
      const tasksToPoll = taskStore.taskList.filter(
        t => (t.stage === 'queued' || t.stage === 'detecting') && t.taskId
      )

      // 并发轮询所有进行中的任务
      const promises = tasksToPoll.map(t =>
        pollTaskForId(t.taskId).catch(err => {
          console.error(`轮询任务 ${t.taskId} 失败:`, err)
        })
      )

      await Promise.allSettled(promises)

      // 如果没有需要轮询的任务了，停止全局轮询
      if (tasksToPoll.length === 0) {
        stopGlobalPolling()
      }
    }, POLLING_INTERVAL)

  }

  // 停止全局轮询
  const stopGlobalPolling = () => {
    if (globalPollingTimer) {
      clearInterval(globalPollingTimer)
      globalPollingTimer = null
    }
  }

  // 确保全局轮询在有任务时运行
  const ensurePolling = () => {
    const taskStore = useTaskStore()
    const hasActiveTasks = taskStore.taskList.some(
      t => t.stage === 'queued' || t.stage === 'detecting'
    )

    if (hasActiveTasks && !globalPollingTimer) {
      startGlobalPolling()
    }
  }

  // ==================== 单个任务轮询 ====================

  const pollTaskForId = async (taskId) => {
    const taskStore = useTaskStore()
    const progressResponse = await request.get(`/api/detection/tasks/${taskId}`)
    if (!progressResponse.data || progressResponse.data.code !== 200) {
      throw new Error(progressResponse.data?.message || '查询任务进度失败')
    }

    const progress = progressResponse.data.data
    const progressStatus = progress.status || ''
    const progressStage = progress.stage || ''
    const normalizedStage = progressStatus === 'FAILED'
      ? 'failed'
      : ((progressStatus === 'COMPLETED' || progressStatus === 'PARTIAL_FAILED')
        ? 'completed'
        : (progressStage === 'QUEUED' || progressStatus === 'QUEUED' || progressStage === 'UPLOADED' || progressStatus === 'UPLOADED' ? 'queued' : 'detecting'))
    const percentMap = { queued: 40, detecting: 65, completed: 100, failed: 0 }

    taskStore.updateTask(taskId, {
      stage: normalizedStage,
      progressPercent: percentMap[normalizedStage] || progress.progressPercent || 0,
      message: progress.message || (normalizedStage === 'queued' ? '已交给模型处理，等待检测服务调度。' : (normalizedStage === 'detecting' ? '模型正在检测。' : '')),
      error: progressStatus === 'FAILED' ? (progress.message || '检测失败') : '',
      flowStatus: progress.flowStatus || '',
      reviewStatus: progress.reviewStatus || '',
      reviewConclusion: progress.reviewConclusion || '',
      severityLevel: progress.severityLevel || '',
      confirmedDefectCount: progress.confirmedDefectCount || 0,
      falsePositiveCount: progress.falsePositiveCount || 0,
      reviewRemark: progress.reviewRemark || '',
      reviewer: progress.reviewer || '',
      reviewedAt: progress.reviewedAt || '',
      qualityStation: progress.qualityStation || '',
      assignee: progress.assignee || '',
      assignmentRemark: progress.assignmentRemark || '',
      assignedAt: progress.assignedAt || '',
      dueAt: progress.dueAt || '',
      dispositionStatus: progress.dispositionStatus || '',
      dispositionAction: progress.dispositionAction || '',
      dispositionRemark: progress.dispositionRemark || '',
      dispositionOperator: progress.dispositionOperator || '',
      disposedAt: progress.disposedAt || '',
      recheckRequired: progress.recheckRequired || false,
      reworkResult: progress.reworkResult || '',
      reworkOperator: progress.reworkOperator || '',
      reworkRemark: progress.reworkRemark || '',
      reworkCompletedAt: progress.reworkCompletedAt || '',
      defectCount: progress.defectCount || 0,
      primaryDefectType: progress.primaryDefectType || '',
      maxDefectSeverity: progress.maxDefectSeverity || ''
    })

    if (progressStatus === 'COMPLETED' || progressStatus === 'PARTIAL_FAILED') {
      const resultResponse = await request.get(`/api/detection/tasks/${taskId}/result`)
      if (resultResponse.data && resultResponse.data.code === 200) {
        const result = resultResponse.data.data
        taskStore.updateTask(taskId, {
          result,
          stage: 'completed',
          progressPercent: 100,
          message: '检测完成。',
          reviewStatus: result.reviewStatus || progress.reviewStatus || '',
          reviewConclusion: result.reviewConclusion || progress.reviewConclusion || '',
          severityLevel: result.severityLevel || progress.severityLevel || '',
          confirmedDefectCount: result.confirmedDefectCount || progress.confirmedDefectCount || 0,
          falsePositiveCount: result.falsePositiveCount || progress.falsePositiveCount || 0,
          reviewRemark: result.reviewRemark || progress.reviewRemark || '',
          reviewer: result.reviewer || progress.reviewer || '',
          reviewedAt: result.reviewedAt || progress.reviewedAt || '',
          qualityStation: result.qualityStation || progress.qualityStation || '',
          assignee: result.assignee || progress.assignee || '',
          assignmentRemark: result.assignmentRemark || progress.assignmentRemark || '',
          assignedAt: result.assignedAt || progress.assignedAt || '',
          dueAt: result.dueAt || progress.dueAt || '',
          dispositionStatus: result.dispositionStatus || progress.dispositionStatus || '',
          dispositionAction: result.dispositionAction || progress.dispositionAction || '',
          dispositionRemark: result.dispositionRemark || progress.dispositionRemark || '',
          dispositionOperator: result.dispositionOperator || progress.dispositionOperator || '',
          disposedAt: result.disposedAt || progress.disposedAt || '',
          recheckRequired: result.recheckRequired || progress.recheckRequired || false,
          reworkResult: result.reworkResult || progress.reworkResult || '',
          reworkOperator: result.reworkOperator || progress.reworkOperator || '',
          reworkRemark: result.reworkRemark || progress.reworkRemark || '',
          reworkCompletedAt: result.reworkCompletedAt || progress.reworkCompletedAt || '',
          defectCount: result.defectCount || progress.defectCount || 0,
          primaryDefectType: result.primaryDefectType || progress.primaryDefectType || '',
          maxDefectSeverity: result.maxDefectSeverity || progress.maxDefectSeverity || '',
          defectEvidence: result.defectEvidence || []
        })
        taskStore.pushTaskLog(taskId, `远程检测任务 ${taskId} 已完成。`)
        ElMessage.success('远程检测任务已完成')
      }
      taskStore.saveTaskList()
    }

    if (progressStatus === 'FAILED') {
      taskStore.saveTaskList()
    }
  }

  // ==================== 检测任务启动 ====================

  const startTaskDetection = async (task, modelId, threshold) => {
    const taskStore = useTaskStore()

    if (!task.uploadedFiles || !task.uploadedFiles.length) {
      ElMessage.error('请先完成 OSS 原图上传')
      return
    }

    const taskId = task.taskId
    taskStore.updateTask(taskId, { stage: 'queued', message: `任务 ${taskId} 已提交，等待检测调度。`, progressPercent: 40 })
    taskStore.pushTaskLog(taskId, `任务 ${taskId} 已提交到 Kafka，等待检测服务消费。`)
    taskStore.saveTaskList()

    try {
      const response = await request.post(`/api/detection/tasks/${taskId}/uploaded`, {
        modelId: modelId || null,
        threshold: threshold,
        uploadedFiles: task.uploadedFiles
      })
      if (!response.data || response.data.code !== 200) {
        throw new Error(response.data?.message || '提交检测任务失败')
      }

      // 立即轮询一次
      await pollTaskForId(taskId)

      // 启动全局轮询（如果还没启动）
      startGlobalPolling()
    } catch (error) {
      console.error('远程检测失败:', error)
      taskStore.updateTask(taskId, { stage: 'failed', message: '检测任务执行失败。', error: error.message || '未知错误' })
      taskStore.saveTaskList()
      ElMessage.error(`检测失败: ${error.message || '未知错误'}`)
    }
  }

  // ==================== 从后端同步任务列表 ====================

  const fetchTaskList = async (page = 1, size = 50, keyword = '', status = '', filters = {}) => {
    const taskStore = useTaskStore()

    try {
      const params = { page, size }
      if (keyword) params.keyword = keyword
      if (status) params.status = status
      if (filters.collector) params.collector = filters.collector
      if (filters.deviceName) params.deviceName = filters.deviceName
      if (filters.region) params.region = filters.region
      const response = await request.get('/api/detection/tasks', { params })
      if (!response.data || response.data.code !== 200) return { records: [], total: 0 }

      const data = response.data.data || {}
      const backendTasks = data.records || data || []
      const total = data.total || backendTasks.length

      for (const bt of backendTasks) {
        const existingIdx = taskStore.findTaskIndex(bt.taskId)
        const stage = taskStore.normalizeStage(bt.status, bt.stage)

        if (existingIdx === -1) {
          // 后端有但本地没有 → 新增
          taskStore.taskList.push({
            taskId: bt.taskId,
            batchNo: bt.batchNo || '',
            workOrderNo: bt.workOrderNo || '',
            flowStatus: bt.flowStatus || '',
            reviewStatus: bt.reviewStatus || '',
            reviewConclusion: bt.reviewConclusion || '',
            severityLevel: bt.severityLevel || '',
            confirmedDefectCount: bt.confirmedDefectCount || 0,
            falsePositiveCount: bt.falsePositiveCount || 0,
            reviewRemark: bt.reviewRemark || '',
            reviewer: bt.reviewer || '',
            reviewedAt: bt.reviewedAt || '',
            qualityStation: bt.qualityStation || '',
            assignee: bt.assignee || '',
            assignmentRemark: bt.assignmentRemark || '',
            assignedAt: bt.assignedAt || '',
            dueAt: bt.dueAt || '',
            dispositionStatus: bt.dispositionStatus || '',
            dispositionAction: bt.dispositionAction || '',
            dispositionRemark: bt.dispositionRemark || '',
            dispositionOperator: bt.dispositionOperator || '',
            disposedAt: bt.disposedAt || '',
            recheckRequired: bt.recheckRequired || false,
            reworkResult: bt.reworkResult || '',
            reworkOperator: bt.reworkOperator || '',
            reworkRemark: bt.reworkRemark || '',
            reworkCompletedAt: bt.reworkCompletedAt || '',
            defectCount: bt.defectCount || 0,
            primaryDefectType: bt.primaryDefectType || '',
            maxDefectSeverity: bt.maxDefectSeverity || '',
            folderName: bt.folderName || '未知任务',
            imageCount: bt.totalImages || 0,
            progressPercent: bt.progressPercent || 0,
            stage,
            message: bt.message || '',
            error: bt.errorMessage || '',
            result: null,
            uploadedFiles: [],
            logs: [],
            updatedAt: bt.updatedAt || '',
            createdAt: bt.createdAt || '',
            finishedAt: bt.finishedAt || '',
            captureInfo: {
              captureDate: bt.captureDate || '',
              region: bt.region || '',
              collector: bt.collector || '',
              deviceName: bt.deviceName || '',
              imageFolderName: bt.imageFolderName || ''
            },
            sourceOssPrefix: bt.sourceOssPrefix || ''
          })
        } else {
          // 已存在 → 以后端状态为准更新
          const existing = taskStore.taskList[existingIdx]
          // 上传阶段保留前端逐文件真实进度，不被后端硬编码的 25% 覆盖
          const isUploadPhase = (stage === 'uploading' || stage === 'uploaded')
          const progressPercent = isUploadPhase
            ? existing.progressPercent
            : (bt.progressPercent != null ? bt.progressPercent : existing.progressPercent)
          taskStore.updateTask(bt.taskId, {
            stage,
            progressPercent,
            updatedAt: bt.updatedAt,
            createdAt: bt.createdAt || existing.createdAt,
            finishedAt: bt.finishedAt || existing.finishedAt,
            message: bt.message || existing.message,
            error: bt.errorMessage || existing.error,
            batchNo: bt.batchNo || existing.batchNo || '',
            workOrderNo: bt.workOrderNo || existing.workOrderNo || '',
            flowStatus: bt.flowStatus || existing.flowStatus || '',
            reviewStatus: bt.reviewStatus || existing.reviewStatus || '',
            reviewConclusion: bt.reviewConclusion || existing.reviewConclusion || '',
            severityLevel: bt.severityLevel || existing.severityLevel || '',
            confirmedDefectCount: bt.confirmedDefectCount ?? existing.confirmedDefectCount ?? 0,
            falsePositiveCount: bt.falsePositiveCount ?? existing.falsePositiveCount ?? 0,
            reviewRemark: bt.reviewRemark || existing.reviewRemark || '',
            reviewer: bt.reviewer || existing.reviewer || '',
            reviewedAt: bt.reviewedAt || existing.reviewedAt || '',
            qualityStation: bt.qualityStation || existing.qualityStation || '',
            assignee: bt.assignee || existing.assignee || '',
            assignmentRemark: bt.assignmentRemark || existing.assignmentRemark || '',
            assignedAt: bt.assignedAt || existing.assignedAt || '',
            dueAt: bt.dueAt || existing.dueAt || '',
            dispositionStatus: bt.dispositionStatus || existing.dispositionStatus || '',
            dispositionAction: bt.dispositionAction || existing.dispositionAction || '',
            dispositionRemark: bt.dispositionRemark || existing.dispositionRemark || '',
            dispositionOperator: bt.dispositionOperator || existing.dispositionOperator || '',
            disposedAt: bt.disposedAt || existing.disposedAt || '',
            recheckRequired: bt.recheckRequired ?? existing.recheckRequired ?? false,
            reworkResult: bt.reworkResult || existing.reworkResult || '',
            reworkOperator: bt.reworkOperator || existing.reworkOperator || '',
            reworkRemark: bt.reworkRemark || existing.reworkRemark || '',
            reworkCompletedAt: bt.reworkCompletedAt || existing.reworkCompletedAt || '',
            defectCount: bt.defectCount ?? existing.defectCount ?? 0,
            primaryDefectType: bt.primaryDefectType || existing.primaryDefectType || '',
            maxDefectSeverity: bt.maxDefectSeverity || existing.maxDefectSeverity || '',
            folderName: bt.folderName || existing.folderName,
            imageCount: bt.totalImages || existing.imageCount,
            captureInfo: {
              captureDate: bt.captureDate || existing.captureInfo?.captureDate || '',
              region: bt.region || existing.captureInfo?.region || '',
              collector: bt.collector || existing.captureInfo?.collector || '',
              deviceName: bt.deviceName || existing.captureInfo?.deviceName || '',
              imageFolderName: bt.imageFolderName || existing.captureInfo?.imageFolderName || ''
            },
            sourceOssPrefix: bt.sourceOssPrefix || existing.sourceOssPrefix || ''
          })
        }
      }

      taskStore.saveTaskList()

      // 确保全局轮询在有任务时运行
      ensurePolling()

      return { records: backendTasks, total }
    } catch (err) {
      console.error('从后端加载任务列表失败:', err)
      return { records: [], total: 0 }
    }
  }

  // ==================== 生命周期相关 ====================

  const restoreFromSession = async () => {
    const taskStore = useTaskStore()
    const saved = taskStore.loadTaskList()
    if (!saved.length) return

    taskStore.taskList = saved.map(t => ({
      ...t,
      result: null,
      updatedAt: t.updatedAt || '',
      createdAt: t.createdAt || '',
      finishedAt: t.finishedAt || ''
    }))
    // 确保全局轮询在有任务时运行
    ensurePolling()
    taskStore.saveTaskList()
  }

  // 批量获取任务结果（用于检测记录页面）
  const fetchTaskResults = async (taskIds) => {
    const taskStore = useTaskStore()
    const promises = taskIds.map(async (taskId) => {
      try {
        const res = await request.get(`/api/detection/tasks/${taskId}/result`)
        if (res.data && res.data.code === 200) {
          const result = res.data.data
          taskStore.updateTask(taskId, {
            result,
            reviewStatus: result.reviewStatus || '',
            reviewConclusion: result.reviewConclusion || '',
            severityLevel: result.severityLevel || '',
            confirmedDefectCount: result.confirmedDefectCount || 0,
            falsePositiveCount: result.falsePositiveCount || 0,
            reviewRemark: result.reviewRemark || '',
            reviewer: result.reviewer || '',
            reviewedAt: result.reviewedAt || '',
            qualityStation: result.qualityStation || '',
            assignee: result.assignee || '',
            assignmentRemark: result.assignmentRemark || '',
            assignedAt: result.assignedAt || '',
            dueAt: result.dueAt || '',
            dispositionStatus: result.dispositionStatus || '',
            dispositionAction: result.dispositionAction || '',
            dispositionRemark: result.dispositionRemark || '',
            dispositionOperator: result.dispositionOperator || '',
            disposedAt: result.disposedAt || '',
            recheckRequired: result.recheckRequired || false,
            reworkResult: result.reworkResult || '',
            reworkOperator: result.reworkOperator || '',
            reworkRemark: result.reworkRemark || '',
            reworkCompletedAt: result.reworkCompletedAt || '',
            defectCount: result.defectCount || 0,
            primaryDefectType: result.primaryDefectType || '',
            maxDefectSeverity: result.maxDefectSeverity || '',
            defectEvidence: result.defectEvidence || []
          })
        }
      } catch { /* 忽略 */ }
    })
    await Promise.allSettled(promises)
  }

  return {
    pollTaskForId,
    startTaskDetection,
    fetchTaskList,
    fetchTaskResults,
    restoreFromSession,
    stopGlobalPolling,
    ensurePolling
  }
})
