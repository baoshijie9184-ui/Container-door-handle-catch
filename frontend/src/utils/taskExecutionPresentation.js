import {knownCount} from './countPresentation'
export function taskExecutionCode(task){
 if(typeof task?.status==='string' && task.status.trim())return task.status.trim().toUpperCase()
 const stages={uploading:'UPLOADING',uploaded:'UPLOADED',queued:'QUEUED',detecting:'DETECTING',completed:'COMPLETED',failed:'FAILED'}
 return Object.hasOwn(stages,task?.stage)?stages[task.stage]:'UNKNOWN'
}
export function taskExecutionProgress(task){
 const percentage=typeof task?.progressPercent==='number' && Number.isFinite(task.progressPercent) && task.progressPercent>=0 && task.progressPercent<=100 ? task.progressPercent : null
 const code=taskExecutionCode(task)
 const count=value=>knownCount(value)?.toLocaleString('zh-CN') ?? '未知'
 return {percentage,code,
  status:code==='FAILED'?'exception':code==='PARTIAL_FAILED'?'warning':code==='COMPLETED' && percentage===100?'success':undefined,
  total:count(task?.imageCount ?? task?.totalImages),
  uploaded:Array.isArray(task?.uploadedFiles)?task.uploadedFiles.length.toLocaleString('zh-CN'):'未知',
  message:typeof task?.message==='string'?task.message:'',
  error:typeof task?.error==='string' && task.error ? task.error : typeof task?.errorMessage==='string'?task.errorMessage:''}
}
