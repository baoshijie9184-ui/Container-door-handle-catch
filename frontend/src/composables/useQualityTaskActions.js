import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  assignDetectionQualityTask,
  disposeDetectionTask,
  reviewDetectionTask,
  submitDetectionReworkResult
} from '../api/detection'
import {
  canReleaseDisposition,
  shouldDefaultRecheck
} from '../utils/qualityWorkflow'

const noop = async () => {}

export function useQualityTaskActions({
  taskStore,
  fetchTaskResults,
  refreshQualityQueue = noop,
  refreshDefectGallery = noop
}) {
  const reviewDialogVisible = ref(false)
  const reviewSubmitting = ref(false)
  const reviewTask = ref(null)
  const assignmentDialogVisible = ref(false)
  const assignmentSubmitting = ref(false)
  const assignmentTask = ref(null)
  const dispositionDialogVisible = ref(false)
  const dispositionSubmitting = ref(false)
  const dispositionTask = ref(null)
  const reworkDialogVisible = ref(false)
  const reworkSubmitting = ref(false)
  const reworkTask = ref(null)

  const reviewForm = reactive({
    reviewConclusion: 'CONFIRMED_DEFECT',
    severityLevel: 'MAJOR',
    confirmedDefectCount: 0,
    falsePositiveCount: 0,
    reviewRemark: ''
  })

  const assignmentForm = reactive({
    qualityStation: '质检站-1',
    assignee: '',
    dueAt: '',
    assignmentRemark: ''
  })

  const dispositionForm = reactive({
    dispositionAction: 'REWORK',
    recheckRequired: false,
    dispositionRemark: ''
  })

  const reworkForm = reactive({
    reworkResult: '',
    reworkOperator: '',
    recheckRequired: true,
    reworkRemark: ''
  })

  const applyTaskProgressUpdate = async (taskId, data, fallbackMessage) => {
    taskStore.updateTask(taskId, {
      flowStatus: data.flowStatus,
      qualityStation: data.qualityStation,
      assignee: data.assignee,
      assignmentRemark: data.assignmentRemark,
      assignedAt: data.assignedAt,
      dueAt: data.dueAt,
      reviewStatus: data.reviewStatus,
      reviewConclusion: data.reviewConclusion,
      severityLevel: data.severityLevel,
      confirmedDefectCount: data.confirmedDefectCount,
      falsePositiveCount: data.falsePositiveCount,
      reviewRemark: data.reviewRemark,
      reviewer: data.reviewer,
      reviewedAt: data.reviewedAt,
      dispositionStatus: data.dispositionStatus,
      dispositionAction: data.dispositionAction,
      dispositionRemark: data.dispositionRemark,
      dispositionOperator: data.dispositionOperator,
      disposedAt: data.disposedAt,
      recheckRequired: data.recheckRequired,
      reworkResult: data.reworkResult,
      reworkOperator: data.reworkOperator,
      reworkRemark: data.reworkRemark,
      reworkCompletedAt: data.reworkCompletedAt,
      message: data.message || fallbackMessage
    })
    await fetchTaskResults([taskId])
  }

  const openReviewDialog = (task) => {
    reviewTask.value = task
    reviewForm.reviewConclusion = task.reviewConclusion || 'CONFIRMED_DEFECT'
    reviewForm.severityLevel = task.severityLevel || 'MAJOR'
    reviewForm.confirmedDefectCount = task.confirmedDefectCount ?? 0
    reviewForm.falsePositiveCount = task.falsePositiveCount ?? 0
    reviewForm.reviewRemark = task.reviewRemark || ''
    reviewDialogVisible.value = true
  }

  const submitTaskReview = async () => {
    if (!reviewTask.value?.taskId) {
      ElMessage.error('请选择需要复核的任务')
      return
    }

    reviewSubmitting.value = true
    try {
      const response = await reviewDetectionTask(reviewTask.value.taskId, {
        reviewConclusion: reviewForm.reviewConclusion,
        severityLevel: reviewForm.severityLevel,
        confirmedDefectCount: reviewForm.confirmedDefectCount,
        falsePositiveCount: reviewForm.falsePositiveCount,
        reviewRemark: reviewForm.reviewRemark
      })
      if (response.data?.code === 200) {
        const data = response.data.data
        await applyTaskProgressUpdate(reviewTask.value.taskId, data, '人工复核已完成')
        await refreshQualityQueue()
        await refreshDefectGallery()
        reviewDialogVisible.value = false
        ElMessage.success('人工复核已提交')
      } else {
        ElMessage.error(response.data?.message || '人工复核提交失败')
      }
    } catch (error) {
      console.error('人工复核提交失败:', error)
      ElMessage.error(error.response?.data?.message || '人工复核提交失败')
    } finally {
      reviewSubmitting.value = false
    }
  }

  const openAssignmentDialog = (task) => {
    assignmentTask.value = task
    assignmentForm.qualityStation = task.qualityStation || task.result?.qualityStation || '质检站-1'
    assignmentForm.assignee = task.assignee || task.result?.assignee || ''
    assignmentForm.dueAt = task.dueAt || task.result?.dueAt || ''
    assignmentForm.assignmentRemark = task.assignmentRemark || task.result?.assignmentRemark || ''
    assignmentDialogVisible.value = true
  }

  const submitQualityAssignment = async () => {
    if (!assignmentTask.value?.taskId) {
      ElMessage.error('请选择需要分派的任务')
      return
    }
    if (!assignmentForm.qualityStation.trim() || !assignmentForm.assignee.trim()) {
      ElMessage.warning('请填写质检站点和责任人')
      return
    }

    assignmentSubmitting.value = true
    try {
      const response = await assignDetectionQualityTask(assignmentTask.value.taskId, {
        qualityStation: assignmentForm.qualityStation,
        assignee: assignmentForm.assignee,
        dueAt: assignmentForm.dueAt,
        assignmentRemark: assignmentForm.assignmentRemark
      })
      if (response.data?.code === 200) {
        await applyTaskProgressUpdate(assignmentTask.value.taskId, response.data.data, '质检任务已分派')
        await refreshQualityQueue()
        assignmentDialogVisible.value = false
        ElMessage.success('质检任务已分派')
      } else {
        ElMessage.error(response.data?.message || '质检分派失败')
      }
    } catch (error) {
      console.error('质检分派失败:', error)
      ElMessage.error(error.response?.data?.message || '质检分派失败')
    } finally {
      assignmentSubmitting.value = false
    }
  }

  const openDispositionDialog = (task) => {
    dispositionTask.value = task
    dispositionForm.dispositionAction = canReleaseDisposition(task) ? 'RELEASE' : 'REWORK'
    dispositionForm.recheckRequired = shouldDefaultRecheck(task)
    dispositionForm.dispositionRemark = task.dispositionRemark || ''
    dispositionDialogVisible.value = true
  }

  const submitTaskDisposition = async () => {
    if (!dispositionTask.value?.taskId) {
      ElMessage.error('请选择需要处置的任务')
      return
    }
    if (dispositionForm.dispositionAction === 'RELEASE' && !canReleaseDisposition(dispositionTask.value)) {
      ElMessage.warning('确认缺陷或待复检任务不能直接放行，请选择返工、复检、暂挂或报废')
      return
    }

    dispositionSubmitting.value = true
    try {
      const response = await disposeDetectionTask(dispositionTask.value.taskId, {
        dispositionAction: dispositionForm.dispositionAction,
        recheckRequired: dispositionForm.recheckRequired,
        dispositionRemark: dispositionForm.dispositionRemark
      })
      if (response.data?.code === 200) {
        await applyTaskProgressUpdate(dispositionTask.value.taskId, response.data.data, '质检处置已完成')
        await refreshQualityQueue()
        dispositionDialogVisible.value = false
        ElMessage.success('质检处置已提交')
      } else {
        ElMessage.error(response.data?.message || '质检处置提交失败')
      }
    } catch (error) {
      console.error('质检处置提交失败:', error)
      ElMessage.error(error.response?.data?.message || '质检处置提交失败')
    } finally {
      dispositionSubmitting.value = false
    }
  }

  const openReworkDialog = (task) => {
    reworkTask.value = task
    reworkForm.reworkResult = task.reworkResult || ''
    reworkForm.reworkOperator = task.reworkOperator || ''
    reworkForm.recheckRequired = task.recheckRequired !== false
    reworkForm.reworkRemark = task.reworkRemark || ''
    reworkDialogVisible.value = true
  }

  const submitTaskRework = async () => {
    if (!reworkTask.value?.taskId) {
      ElMessage.error('请选择需要回填返工结果的任务')
      return
    }
    if (!reworkForm.reworkResult.trim()) {
      ElMessage.warning('请填写返工结果')
      return
    }

    reworkSubmitting.value = true
    try {
      const response = await submitDetectionReworkResult(reworkTask.value.taskId, {
        reworkResult: reworkForm.reworkResult,
        reworkOperator: reworkForm.reworkOperator,
        reworkRemark: reworkForm.reworkRemark,
        recheckRequired: reworkForm.recheckRequired
      })
      if (response.data?.code === 200) {
        await applyTaskProgressUpdate(reworkTask.value.taskId, response.data.data, '返工结果已提交')
        await refreshQualityQueue()
        reworkDialogVisible.value = false
        ElMessage.success('返工结果已提交')
      } else {
        ElMessage.error(response.data?.message || '返工结果提交失败')
      }
    } catch (error) {
      console.error('返工结果提交失败:', error)
      ElMessage.error(error.response?.data?.message || '返工结果提交失败')
    } finally {
      reworkSubmitting.value = false
    }
  }

  return {
    reviewDialogVisible,
    reviewSubmitting,
    reviewTask,
    reviewForm,
    assignmentDialogVisible,
    assignmentSubmitting,
    assignmentTask,
    assignmentForm,
    dispositionDialogVisible,
    dispositionSubmitting,
    dispositionTask,
    dispositionForm,
    reworkDialogVisible,
    reworkSubmitting,
    reworkTask,
    reworkForm,
    applyTaskProgressUpdate,
    openReviewDialog,
    submitTaskReview,
    openAssignmentDialog,
    submitQualityAssignment,
    openDispositionDialog,
    submitTaskDisposition,
    openReworkDialog,
    submitTaskRework
  }
}
