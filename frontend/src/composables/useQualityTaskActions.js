import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  assignDetectionQualityTask,
  disposeDetectionTask,
  reviewDetectionTask,
  submitDetectionReworkResult
} from '../api/detection'
import {
  canReleaseDisposition,
  canAssignQualityTask,
  canReviewTask,
  canDisposeTask,
  canSubmitReworkResult,
  qualityActionReason,
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
  const qualityActionErrors = reactive({review:'',assignment:'',disposition:'',rework:''})
  const qualityActionAcknowledged = reactive({review:false,assignment:false,disposition:false,rework:false})
  const resetFeedback = action => { qualityActionErrors[action]=''; qualityActionAcknowledged[action]=false }
  const actionFailure = (action,message) => {
    const text=qualityActionAcknowledged[action]
      ? '接口已返回成功，后续刷新未完成。请核对任务状态，不要再次提交本次操作。'
      : `${message || '操作结果尚未确认'}；未获得明确回执时请先核对任务状态，不要直接重复提交。`
    qualityActionErrors[action]=text
    ElMessage.warning(text)
  }

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
    assigneeUserId: null,
    assigneeRevision: null,
    expectedAssignmentRevision: null,
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

  watch(() => dispositionForm.dispositionAction, (action) => {
    if (action === 'RECHECK') dispositionForm.recheckRequired = true
    if (['RELEASE', 'SCRAP'].includes(action)) dispositionForm.recheckRequired = false
  }, { flush: 'sync' })

  const allowed = (task, action, predicate) => {
    if (predicate(task)) return true
    ElMessage.warning(qualityActionReason(task, action))
    return false
  }

  const applyTaskProgressUpdate = async (taskId, data, fallbackMessage) => {
    taskStore.updateTask(taskId, {
      flowStatus: data.flowStatus,
      qualityActions: data.qualityActions,
      qualityStation: data.qualityStation,
      assignee: data.assignee,
      assignmentRevision: data.assignmentRevision,
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
      // Explicit clearing must survive even if the following result refresh fails.
      dispositionStatus: data.dispositionStatus ?? '',
      dispositionAction: data.dispositionAction ?? '',
      dispositionRemark: data.dispositionRemark ?? '',
      dispositionOperator: data.dispositionOperator ?? '',
      disposedAt: data.disposedAt ?? '',
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
    if (!allowed(task, 'REVIEW', canReviewTask)) return
    resetFeedback('review')
    reviewTask.value = task
    reviewForm.reviewConclusion = task.reviewConclusion || 'CONFIRMED_DEFECT'
    reviewForm.severityLevel = task.severityLevel || 'MAJOR'
    reviewForm.confirmedDefectCount = task.confirmedDefectCount ?? 0
    reviewForm.falsePositiveCount = task.falsePositiveCount ?? 0
    reviewForm.reviewRemark = task.reviewRemark || ''
    reviewDialogVisible.value = true
  }

  const submitTaskReview = async () => {
    if (reviewSubmitting.value || qualityActionAcknowledged.review) return
    if (!reviewTask.value?.taskId) {
      ElMessage.error('请选择需要复核的任务')
      return
    }

    if (!allowed(reviewTask.value, 'REVIEW', canReviewTask)) return
    reviewSubmitting.value = true
    qualityActionErrors.review=''
    try {
      const response = await reviewDetectionTask(reviewTask.value.taskId, {
        reviewConclusion: reviewForm.reviewConclusion,
        severityLevel: reviewForm.severityLevel,
        confirmedDefectCount: reviewForm.confirmedDefectCount,
        falsePositiveCount: reviewForm.falsePositiveCount,
        reviewRemark: reviewForm.reviewRemark
      })
      if (response.data?.code === 200) {
        qualityActionAcknowledged.review=true
        const data = response.data.data
        await applyTaskProgressUpdate(reviewTask.value.taskId, data, '人工复核已完成')
        await refreshQualityQueue()
        await refreshDefectGallery()
        reviewDialogVisible.value = false
        ElMessage.success('人工复核已提交')
      } else {
        actionFailure('review',response.data?.message || '人工复核未返回成功回执')
      }
    } catch (error) {
      actionFailure('review',error.response?.data?.message)
    } finally {
      reviewSubmitting.value = false
    }
  }

  const openAssignmentDialog = (task) => {
    if (!allowed(task, 'ASSIGN', canAssignQualityTask)) return
    resetFeedback('assignment')
    assignmentTask.value = task
    assignmentForm.qualityStation = task.qualityStation || task.result?.qualityStation || '质检站-1'
    assignmentForm.assignee = task.assignee || task.result?.assignee || ''
    assignmentForm.assigneeUserId = null
    assignmentForm.assigneeRevision = null
    assignmentForm.expectedAssignmentRevision = task.assignmentRevision ?? task.result?.assignmentRevision ?? null
    assignmentForm.dueAt = task.dueAt || task.result?.dueAt || ''
    assignmentForm.assignmentRemark = task.assignmentRemark || task.result?.assignmentRemark || ''
    assignmentDialogVisible.value = true
  }

  const submitQualityAssignment = async () => {
    if (assignmentSubmitting.value || qualityActionAcknowledged.assignment) return
    if (!assignmentTask.value?.taskId) {
      ElMessage.error('请选择需要分派的任务')
      return
    }
    if (!assignmentForm.qualityStation.trim() || !assignmentForm.assignee.trim()) {
      ElMessage.warning('请填写质检站点和责任人')
      return
    }
    if(!assignmentForm.assigneeUserId || !assignmentForm.assigneeRevision){ElMessage.warning('请从员工账号列表重新选择责任人，以固定账号 ID');return}

    if (!allowed(assignmentTask.value, 'ASSIGN', canAssignQualityTask)) return
    assignmentSubmitting.value = true
    qualityActionErrors.assignment=''
    try {
      const response = await assignDetectionQualityTask(assignmentTask.value.taskId, {
        qualityStation: assignmentForm.qualityStation,
        assignee: assignmentForm.assignee,
        assigneeUserId: assignmentForm.assigneeUserId,
        assigneeRevision: assignmentForm.assigneeRevision,
        expectedAssignmentRevision: assignmentForm.expectedAssignmentRevision,
        dueAt: assignmentForm.dueAt,
        assignmentRemark: assignmentForm.assignmentRemark
      })
      if (response.data?.code === 200) {
        qualityActionAcknowledged.assignment=true
        await applyTaskProgressUpdate(assignmentTask.value.taskId, response.data.data, '质检任务已分派')
        await refreshQualityQueue()
        assignmentDialogVisible.value = false
        ElMessage.success('质检任务已分派')
      } else {
        actionFailure('assignment',response.data?.message || '质检分派未返回成功回执')
      }
    } catch (error) {
      actionFailure('assignment',error.response?.data?.message)
    } finally {
      assignmentSubmitting.value = false
    }
  }

  const openDispositionDialog = (task) => {
    if (!allowed(task, 'DISPOSE', canDisposeTask)) return
    resetFeedback('disposition')
    dispositionTask.value = task
    dispositionForm.dispositionAction = canReleaseDisposition(task) ? 'RELEASE' : 'REWORK'
    dispositionForm.recheckRequired = shouldDefaultRecheck(task)
    dispositionForm.dispositionRemark = task.dispositionRemark || ''
    dispositionDialogVisible.value = true
  }

  const submitTaskDisposition = async () => {
    if (dispositionSubmitting.value || qualityActionAcknowledged.disposition) return
    if (!dispositionTask.value?.taskId) {
      ElMessage.error('请选择需要处置的任务')
      return
    }
    if (dispositionForm.dispositionAction === 'RELEASE' && !canReleaseDisposition(dispositionTask.value)) {
      ElMessage.warning('确认缺陷或待复检任务不能直接放行，请选择返工、复检、暂挂或报废')
      return
    }

    if (!allowed(dispositionTask.value, 'DISPOSE', canDisposeTask)) return
    if (dispositionTask.value?.dispositionAction === 'HOLD' && dispositionForm.dispositionAction === 'HOLD') {
      ElMessage.warning('任务已经暂挂，请选择后续处置或关闭窗口保留现状')
      return
    }
    if (['RELEASE', 'SCRAP'].includes(dispositionForm.dispositionAction) && dispositionForm.recheckRequired) {
      ElMessage.warning('放行或报废不能同时安排复检，请重新核对处置方式')
      return
    }
    dispositionSubmitting.value = true
    qualityActionErrors.disposition=''
    try {
      const response = await disposeDetectionTask(dispositionTask.value.taskId, {
        dispositionAction: dispositionForm.dispositionAction,
        recheckRequired: dispositionForm.recheckRequired,
        dispositionRemark: dispositionForm.dispositionRemark
      })
      if (response.data?.code === 200) {
        qualityActionAcknowledged.disposition=true
        await applyTaskProgressUpdate(dispositionTask.value.taskId, response.data.data, '质检处置已完成')
        await refreshQualityQueue()
        dispositionDialogVisible.value = false
        ElMessage.success('质检处置已提交')
      } else {
        actionFailure('disposition',response.data?.message || '质检处置未返回成功回执')
      }
    } catch (error) {
      actionFailure('disposition',error.response?.data?.message)
    } finally {
      dispositionSubmitting.value = false
    }
  }

  const openReworkDialog = (task) => {
    if (!allowed(task, 'SUBMIT_REWORK', canSubmitReworkResult)) return
    resetFeedback('rework')
    reworkTask.value = task
    reworkForm.reworkResult = task.reworkResult || ''
    reworkForm.reworkOperator = task.reworkOperator || ''
    reworkForm.recheckRequired = (task.recheckRequired ?? task.result?.recheckRequired) !== false
    reworkForm.reworkRemark = task.reworkRemark || ''
    reworkDialogVisible.value = true
  }

  const submitTaskRework = async () => {
    if (reworkSubmitting.value || qualityActionAcknowledged.rework) return
    if (!reworkTask.value?.taskId) {
      ElMessage.error('请选择需要回填返工结果的任务')
      return
    }
    if (!reworkForm.reworkResult.trim()) {
      ElMessage.warning('请填写返工结果')
      return
    }

    if (!allowed(reworkTask.value, 'SUBMIT_REWORK', canSubmitReworkResult)) return
    if ((reworkTask.value.recheckRequired ?? reworkTask.value.result?.recheckRequired) === true && !reworkForm.recheckRequired) {
      ElMessage.warning('原处置已要求返工后复检，不能跳过')
      return
    }
    reworkSubmitting.value = true
    qualityActionErrors.rework=''
    try {
      const response = await submitDetectionReworkResult(reworkTask.value.taskId, {
        reworkResult: reworkForm.reworkResult,
        reworkRemark: reworkForm.reworkRemark,
        recheckRequired: reworkForm.recheckRequired
      })
      if (response.data?.code === 200) {
        qualityActionAcknowledged.rework=true
        await applyTaskProgressUpdate(reworkTask.value.taskId, response.data.data, '返工结果已提交')
        await refreshQualityQueue()
        reworkDialogVisible.value = false
        ElMessage.success('返工结果已提交')
      } else {
        actionFailure('rework',response.data?.message || '返工结果未返回成功回执')
      }
    } catch (error) {
      actionFailure('rework',error.response?.data?.message)
    } finally {
      reworkSubmitting.value = false
    }
  }

  return {
    qualityActionErrors,
    qualityActionAcknowledged,
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
