import { defineStore } from 'pinia'
import { ref } from 'vue'
import request from '../api/request'
import { accountSession } from '../utils/accountContext'
import { resourceVersion, mutationHeaders, responseResourceVersion } from '../utils/mutationVersion'
import { createUiRequestId } from '../utils/requestIdentity'
import { ElMessage } from 'element-plus'
import { useTaskStore } from './taskStore'
import { usePollingStore } from './pollingStore'

export const useUploadStore = defineStore('upload', () => {
  const uploadingToOss = ref(false)
  const activeUploadTaskId = ref(null)

  accountSession.onReset(() => { uploadingToOss.value=false; activeUploadTaskId.value=null })

  async function confirmUpload(taskId, account) {
    accountSession.assert(account)
    const taskStore = useTaskStore()
    const task = taskStore.taskList.find(item => item.taskId===taskId)
    const command = task?.uploadConfirmation
    if (!command || !task.uploadedFiles?.length) return
    taskStore.updateTask(taskId,{message:'正在保存批次资料并确认上传'})
    try {
      const response = await request.post(`/api/detection/tasks/${taskId}/mark-uploaded`, {
        uploadedFiles:task.uploadedFiles.map(({fileName,objectKey})=>({fileName,objectKey}))
      },{_accountStamp:account,timeout:70000,headers:mutationHeaders(command.version,command.requestId)})
      accountSession.assert(account)
      if (response.data?.code!==200) throw new Error(response.data?.message || '上传确认尚未完成')
      const version = responseResourceVersion(response) ?? resourceVersion(task)
      taskStore.updateTask(taskId,{version,mutationVersion:version,stage:'queued',progressPercent:40,
        message:`已提交 ${task.uploadedFiles.length} 张原图检测`})
      taskStore.updateTask(taskId,{uploadConfirmation:null})
      taskStore.removeFileState(taskId,account)
      taskStore.saveTaskList(account,{immediate:true})
      usePollingStore().ensurePolling()
      ElMessage.success(`上传已确认，共 ${task.uploadedFiles.length} 张原图`)
    } catch (error) {
      if (!accountSession.current(account)) return
      taskStore.updateTask(taskId,{message:error.response?.data?.message || error.message || '上传确认尚未完成'})
      taskStore.saveTaskList(account,{immediate:true})
      ElMessage.warning('原图已上传，请从此批次重试上传确认')
    }
  }

  async function finishTransfer(taskId, uploadedFiles, failedCount, version, account) {
    const taskStore = useTaskStore()
    const error = failedCount ? `${failedCount} 张原图上传失败` : ''
    if (!uploadedFiles.length) {
      taskStore.updateTask(taskId,{error,message:'尚无成功上传的原图，请续传'})
      taskStore.saveTaskList(account,{immediate:true})
      ElMessage.warning('尚无成功上传的原图，请续传')
      return
    }
    const uploadConfirmation={version,requestId:createUiRequestId()}
    taskStore.updateTask(taskId,{uploadedFiles,uploadConfirmation,error})
    taskStore.pushTaskLog(taskId,`已上传 ${uploadedFiles.length} 张原图${failedCount ? `，${failedCount} 张失败` : ''}。`)
    taskStore.saveTaskList(account,{immediate:true})
    await confirmUpload(taskId,account)
  }

  async function retryUploadConfirmation(taskId) {
    if (uploadingToOss.value) return
    const account=accountSession.stamp()
    accountSession.assert(account)
    uploadingToOss.value=true
    activeUploadTaskId.value=taskId
    try {
      await confirmUpload(taskId,account)
    } finally {
      if(accountSession.current(account)) { uploadingToOss.value=false; activeUploadTaskId.value=null }
    }
  }

  // ==================== OSS 上传（可跨页面继续执行） ====================

  const uploadBatchToOss = async (filesData, captureInfo, onRegistered, metadata) => {
    const account=accountSession.stamp(),current=()=>accountSession.current(account)
    accountSession.assert(account)
    // 立即提取所有数据（函数入口处），避免后续引用外部 reactive 对象
    // filesData: [{ file: File, fileName, contentType, relativePath }]
    // captureInfo: { captureDate, region, collector, deviceName, imageFolderName, imageCount, folderLabel }

    const taskStore = useTaskStore()

    if (!filesData.length) {
      ElMessage.error('请先选择图片文件夹')
      return
    }

    uploadingToOss.value = true
    activeUploadTaskId.value = null

    try {
      const createResponse = await request.post('/api/detection/tasks', {
        taskType: 'BATCH',
        captureInfo: {
          captureDate: captureInfo.captureDate,
          region: captureInfo.region,
          collector: captureInfo.collector,
          deviceName: captureInfo.deviceName,
          imageFolderName: captureInfo.imageFolderName
        },
        metadata,
        files: filesData.map(item => ({
          fileName: item.fileName,
          contentType: item.contentType,
          relativePath: item.relativePath,
          fileSize: item.fileSize
        }))
      },{_accountStamp:account})

      accountSession.assert(account)
      if (!createResponse.data || createResponse.data.code !== 200) {
        throw new Error(createResponse.data?.message || '创建检测任务失败')
      }

      const taskData = createResponse.data.data
      activeUploadTaskId.value = taskData.taskId
      const uploadVersion=responseResourceVersion(createResponse)
      const folderLabel = captureInfo.folderLabel || `${captureInfo.region || '未知'} / ${captureInfo.imageFolderName || '未命名'}`
      const task = taskStore.createTaskEntry(taskData.taskId, folderLabel, captureInfo.imageCount, captureInfo)
      task.version = uploadVersion
      task.batchNo = taskData.batchNo || ''
      task.workOrderNo = taskData.workOrderNo || ''
      task.flowStatus = taskData.flowStatus || 'UPLOADING'
      taskStore.taskList.unshift(task)
      taskStore.selectedTaskId = taskData.taskId
      onRegistered?.(taskData.taskId)
      taskStore.saveTaskList(account)
      taskStore.pushTaskLog(taskData.taskId, `开始上传 ${captureInfo.imageCount} 张原图到 OSS。`)

      const uploadedFiles = []
      const totalCount = taskData.uploadUrls.length
      const completedFileNames = []
      const failedFileNameList = []

      // 初始化文件级状态
      taskStore.saveFileState(taskData.taskId, {
        total: totalCount,
        completed: [],
        failed: [],
        currentIndex: 0
      },account)

      // 并发上传池：同时上传 CONCURRENCY 个文件
      const CONCURRENCY = 10
      let nextIndex = 0

      const uploadOne = async (i) => {
        if(!current())return
        const uploadItem = taskData.uploadUrls[i]
        const item = filesData[i]
        if (!item) {
          failedFileNameList.push(uploadItem?.fileName || `索引${i}`)
          return
        }

        const ossUrl = new URL(uploadItem.putUrl)
        const proxyUrl = `/oss-upload${ossUrl.pathname}${ossUrl.search}`

        try {
          await request.put(proxyUrl, item.file, {
            headers: { 'Content-Type': item.contentType },
            timeout: 30000, _accountStamp:account
          })
          if(!current())return
          uploadedFiles.push({ fileName: uploadItem.fileName, objectKey: uploadItem.objectKey })
          completedFileNames.push(uploadItem.fileName)
        } catch (err) {
          if(!current())return
          const status = err.response?.status || '无响应'
          console.error(`[上传失败] ${uploadItem.fileName}: HTTP ${status}`, err.message)
          failedFileNameList.push(uploadItem.fileName)
        }

        if(!current())return
        const totalDone = completedFileNames.length + failedFileNameList.length
        const progressPercent = Math.round(2 + (totalDone / totalCount) * 31)
        const failInfo = failedFileNameList.length > 0 ? `，${failedFileNameList.length} 张失败` : ''
        taskStore.updateTask(taskData.taskId, {
          progressPercent,
          message: `已上传 ${completedFileNames.length}/${totalCount}${failInfo}`
        })
        taskStore.saveFileState(taskData.taskId, {
          total: totalCount,
          completed: completedFileNames,
          failed: failedFileNameList,
          currentIndex: totalDone
        },account)
        taskStore.saveTaskList(account)
      }

      const worker = async () => {
        while (current() && nextIndex < totalCount) {
          const i = nextIndex++
          await uploadOne(i)
        }
      }

      const workers = Array.from({ length: Math.min(CONCURRENCY, totalCount) }, () => worker())
      await Promise.all(workers)
      accountSession.assert(account)

      await finishTransfer(taskData.taskId,uploadedFiles,failedFileNameList.length,uploadVersion,account)
    } catch (error) {
      if(!current())return
      console.error('上传 OSS 失败:', error)
      ElMessage.error(error.response?.data?.message || error.message || '上传未完成')
    } finally {
      if(current()) { uploadingToOss.value = false; activeUploadTaskId.value = null }
    }
  }

  // ==================== 断点续传 ====================

  const resumeUploadToOss = async (taskId, remainingFilesData) => {
    const account=accountSession.stamp(),current=()=>accountSession.current(account)
    accountSession.assert(account)
    // remainingFilesData: [{ file: File, fileName, contentType, relativePath }]
    const taskStore = useTaskStore()

    if (!remainingFilesData.length) {
      ElMessage.warning('没有需要续传的文件')
      return
    }

    const existingTask = taskStore.taskList.find(t => t.taskId === taskId)
    if (!existingTask) {
      ElMessage.error('任务不存在，无法续传')
      return
    }

    uploadingToOss.value = true
    activeUploadTaskId.value = taskId

    try {
      // 请求后端生成新的预签名 URL（旧的可能已过期）
      const resumeResponse = await request.post(`/api/detection/tasks/${taskId}/upload-urls/resume`, {
        files: remainingFilesData.map(item => ({
          fileName: item.fileName,
          contentType: item.contentType,
          relativePath: item.relativePath,
          fileSize: item.fileSize
        }))
      },{_accountStamp:account,headers:mutationHeaders(resourceVersion(existingTask))})

      accountSession.assert(account)
      if (!resumeResponse.data || resumeResponse.data.code !== 200) {
        throw new Error(resumeResponse.data?.message || '续传请求失败')
      }

      const resumeData = resumeResponse.data.data
      const uploadVersion=responseResourceVersion(resumeResponse)
      taskStore.updateTask(taskId,{version:uploadVersion,mutationVersion:uploadVersion})
      const totalCount = resumeData.uploadUrls.length
      const prevUploaded = existingTask.uploadedFiles || []
      const prevCompleted = prevUploaded.map(f => f.fileName)

      taskStore.pushTaskLog(taskId, `续传开始，剩余 ${totalCount} 张待上传。`)

      const uploadedFiles = [...prevUploaded]
      const completedFileNames = [...prevCompleted]
      const failedFileNameList = []

      taskStore.saveFileState(taskId, {
        total: existingTask.imageCount,
        completed: completedFileNames,
        failed: failedFileNameList,
        currentIndex: existingTask.imageCount - totalCount
      },account)

      // 并发上传池
      const CONCURRENCY = 10
      let nextIndex = 0

      const uploadOne = async (i) => {
        if(!current())return
        const uploadItem = resumeData.uploadUrls[i]
        const item = remainingFilesData[i]
        if (!item) {
          failedFileNameList.push(uploadItem?.fileName || `索引${i}`)
          return
        }

        const ossUrl = new URL(uploadItem.putUrl)
        const proxyUrl = `/oss-upload${ossUrl.pathname}${ossUrl.search}`

        try {
          await request.put(proxyUrl, item.file, {
            headers: { 'Content-Type': item.contentType },
            timeout: 30000, _accountStamp:account
          })
          if(!current())return
          uploadedFiles.push({ fileName: uploadItem.fileName, objectKey: uploadItem.objectKey })
          completedFileNames.push(uploadItem.fileName)
        } catch (err) {
          if(!current())return
          console.error(`[续传失败] ${uploadItem.fileName}:`, err.message)
          failedFileNameList.push(uploadItem.fileName)
        }

        if(!current())return
        const totalDone = completedFileNames.length + failedFileNameList.length
        const overallProgress = Math.round((totalDone / existingTask.imageCount) * 34)
        const failInfo = failedFileNameList.length > 0 ? `，${failedFileNameList.length} 张失败` : ''
        taskStore.updateTask(taskId, {
          progressPercent: overallProgress,
          message: `已上传 ${completedFileNames.length}/${existingTask.imageCount}${failInfo}`
        })
        taskStore.saveFileState(taskId, {
          total: existingTask.imageCount,
          completed: completedFileNames,
          failed: failedFileNameList,
          currentIndex: totalDone
        },account)
        taskStore.saveTaskList(account)
      }

      const worker = async () => {
        while (current() && nextIndex < totalCount) {
          const i = nextIndex++
          await uploadOne(i)
        }
      }

      await Promise.all(Array.from({ length: Math.min(CONCURRENCY, totalCount) }, () => worker()))
      accountSession.assert(account)

      await finishTransfer(taskId,uploadedFiles,failedFileNameList.length,uploadVersion,account)
    } catch (error) {
      if(!current())return
      console.error('续传失败:', error)
      ElMessage.error(`续传失败: ${error.message || '未知错误'}`)
    } finally {
      if(current()) { uploadingToOss.value = false; activeUploadTaskId.value = null }
    }
  }

  return {
    uploadingToOss,
    activeUploadTaskId,
    uploadBatchToOss,
    resumeUploadToOss,
    retryUploadConfirmation
  }
})
