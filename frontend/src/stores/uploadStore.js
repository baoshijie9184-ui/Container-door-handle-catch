import { defineStore } from 'pinia'
import { ref } from 'vue'
import request from '../api/request'
import { accountSession } from '../utils/accountContext'
import { resourceVersion, mutationHeaders, responseResourceVersion } from '../utils/mutationVersion'
import { ElMessage } from 'element-plus'
import { useTaskStore } from './taskStore'
import { usePollingStore } from './pollingStore'

export const useUploadStore = defineStore('upload', () => {
  const uploadingToOss = ref(false)

  // ==================== OSS 上传（可跨页面继续执行） ====================

  const uploadBatchToOss = async (filesData, captureInfo) => {
    const account=accountSession.stamp(),current=()=>accountSession.current(account)
    accountSession.assert(account)
    // 立即提取所有数据（函数入口处），避免后续引用外部 reactive 对象
    // filesData: [{ file: File, fileName, contentType, relativePath }]
    // captureInfo: { captureDate, region, collector, deviceName, imageFolderName, imageCount, folderLabel }

    const taskStore = useTaskStore()
    const pollingStore = usePollingStore()

    if (!filesData.length) {
      ElMessage.error('请先选择图片文件夹')
      return
    }

    uploadingToOss.value = true

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
      const uploadVersion=responseResourceVersion(createResponse)
      const folderLabel = captureInfo.folderLabel || `${captureInfo.region || '未知'} / ${captureInfo.imageFolderName || '未命名'}`
      const task = taskStore.createTaskEntry(taskData.taskId, folderLabel, captureInfo.imageCount, captureInfo)
      task.version = uploadVersion
      task.batchNo = taskData.batchNo || ''
      task.workOrderNo = taskData.workOrderNo || ''
      task.flowStatus = taskData.flowStatus || 'UPLOADING'
      taskStore.taskList.unshift(task)
      taskStore.selectedTaskId = taskData.taskId
      taskStore.saveTaskList(account)
      taskStore.pushTaskLog(taskData.taskId, `开始上传 ${captureInfo.imageCount} 张原图到 OSS。`)

      const uploadedFiles = []
      const failedFiles = []
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
      let completedCount = 0

      const uploadOne = async (i) => {
        if(!current())return
        const uploadItem = taskData.uploadUrls[i]
        const item = filesData[i]
        if (!item) {
          failedFiles.push({ fileName: uploadItem?.fileName || `索引${i}`, reason: '前端文件数据缺失' })
          failedFileNameList.push(uploadItem?.fileName || `索引${i}`)
          completedCount++
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
          failedFiles.push({ fileName: uploadItem.fileName, reason: err.message || '上传失败' })
          failedFileNameList.push(uploadItem.fileName)
        }

        if(!current())return
        completedCount++
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

      // 上传完成，清理文件级状态
      taskStore.removeFileState(taskData.taskId,account)

      const allSuccess = failedFiles.length === 0
      taskStore.updateTask(taskData.taskId, {
        stage: 'queued',
        message: allSuccess
          ? `全部 ${uploadedFiles.length} 张原图已上传完成，正在自动提交检测。`
          : `上传完成：成功 ${uploadedFiles.length} 张，失败 ${failedFiles.length} 张，正在提交可用图片检测。`,
        progressPercent: 40,
        uploadedFiles,
        error: allSuccess ? '' : `${failedFiles.length} 张图片上传失败`
      })
      taskStore.pushTaskLog(taskData.taskId,
        allSuccess
          ? `原图上传完成，共 ${uploadedFiles.length} 张。`
          : `原图上传完成：成功 ${uploadedFiles.length} 张，失败 ${failedFiles.length} 张。`
      )
      ElMessage.success(allSuccess
        ? `OSS 上传完成，共 ${uploadedFiles.length} 张`
        : `OSS 上传完成：成功 ${uploadedFiles.length} 张，失败 ${failedFiles.length} 张`)
      taskStore.saveTaskList(account)
      pollingStore.ensurePolling()

      // 通知后端标记上传完成并自动提交检测调度（异步，不阻塞）
      request.post(`/api/detection/tasks/${taskData.taskId}/mark-uploaded`, {
        uploadedFiles: uploadedFiles.map(f => ({ fileName: f.fileName, objectKey: f.objectKey }))
      },{_accountStamp:account,headers:mutationHeaders(uploadVersion)}).then(response=>{if(current()){const version=responseResourceVersion(response);if(version!==null)taskStore.updateTask(taskData.taskId,{version,mutationVersion:version});taskStore.saveTaskList(account)}}).catch(err => {if(current())console.error('标记上传完成失败:', err)})
    } catch (error) {
      if(!current())return
      console.error('上传 OSS 失败:', error)
      ElMessage.error(`上传失败: ${error.message || '未知错误'}`)
    } finally {
      if(current())uploadingToOss.value = false
    }
  }

  // ==================== 断点续传 ====================

  const resumeUploadToOss = async (taskId, remainingFilesData) => {
    const account=accountSession.stamp(),current=()=>accountSession.current(account)
    accountSession.assert(account)
    // remainingFilesData: [{ file: File, fileName, contentType, relativePath }]
    const taskStore = useTaskStore()
    const pollingStore = usePollingStore()

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
      const prevFailed = taskStore.loadFileState(taskId)?.failed || []

      taskStore.pushTaskLog(taskId, `续传开始，剩余 ${totalCount} 张待上传。`)

      const uploadedFiles = [...prevUploaded]
      const failedFiles = []
      const completedFileNames = [...prevCompleted]
      const failedFileNameList = [...prevFailed]

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

      taskStore.removeFileState(taskId,account)

      const allSuccess = failedFileNameList.length === 0
      taskStore.updateTask(taskId, {
        stage: 'queued',
        message: allSuccess
          ? `全部 ${uploadedFiles.length} 张原图已上传完成，正在自动提交检测。`
          : `上传完成：成功 ${uploadedFiles.length} 张，失败 ${failedFileNameList.length} 张，正在提交可用图片检测。`,
        progressPercent: 40,
        uploadedFiles,
        error: allSuccess ? '' : `${failedFileNameList.length} 张图片上传失败`
      })
      taskStore.pushTaskLog(taskId,
        allSuccess
          ? `续传完成，共 ${uploadedFiles.length} 张原图已上传。`
          : `续传完成：成功 ${uploadedFiles.length} 张，失败 ${failedFileNameList.length} 张。`
      )
      ElMessage.success(allSuccess
        ? `续传完成，共 ${uploadedFiles.length} 张`
        : `续传完成：成功 ${uploadedFiles.length} 张，失败 ${failedFileNameList.length} 张`)
      taskStore.saveTaskList(account)
      pollingStore.ensurePolling()

      // 通知后端标记上传完成并自动提交检测调度（异步，不阻塞）
      request.post(`/api/detection/tasks/${taskId}/mark-uploaded`, {
        uploadedFiles: uploadedFiles.map(f => ({ fileName: f.fileName, objectKey: f.objectKey }))
      },{_accountStamp:account,headers:mutationHeaders(uploadVersion)}).then(response=>{if(current()){const version=responseResourceVersion(response);if(version!==null)taskStore.updateTask(taskId,{version,mutationVersion:version});taskStore.saveTaskList(account)}}).catch(err => {if(current())console.error('标记上传完成失败:', err)})
    } catch (error) {
      if(!current())return
      console.error('续传失败:', error)
      ElMessage.error(`续传失败: ${error.message || '未知错误'}`)
    } finally {
      if(current())uploadingToOss.value = false
    }
  }

  return {
    uploadingToOss,
    uploadBatchToOss,
    resumeUploadToOss
  }
})
