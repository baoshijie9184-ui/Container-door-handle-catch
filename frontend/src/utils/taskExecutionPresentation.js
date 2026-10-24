import {knownCount} from './countPresentation'
import {beijingDateTime} from './beijingTime'
export function taskExecutionCode(task){
 if(typeof task?.status==='string' && task.status.trim())return task.status.trim().toUpperCase()
 // A cached completed stage covers both COMPLETED and PARTIAL_FAILED.
 // Only a result belonging to this task can supply the missing outcome.
 if(task?.stage==='completed' && typeof task.taskId==='string' && task.result?.taskId===task.taskId && typeof task.result.status==='string' && task.result.status.trim())return task.result.status.trim().toUpperCase()
 const stages={uploading:'UPLOADING',uploaded:'UPLOADED',queued:'QUEUED',detecting:'DETECTING',completed:'RESULT_RECORDED',failed:'EXECUTION_FAILED'}
 return Object.hasOwn(stages,task?.stage)?stages[task.stage]:'UNKNOWN'
}
export function taskExecutionProgress(task){
 const percentage=typeof task?.progressPercent==='number' && Number.isFinite(task.progressPercent) && task.progressPercent>=0 && task.progressPercent<=100 ? task.progressPercent : null
 const code=taskExecutionCode(task)
 const count=value=>knownCount(value)?.toLocaleString('zh-CN') ?? '未知'
 return {percentage,code,
  status:code==='FAILED' || code==='EXECUTION_FAILED'?'exception':code==='PARTIAL_FAILED' || code==='RESULT_RECORDED'?'warning':code==='COMPLETED' && percentage===100?'success':undefined,
  total:count(task?.imageCount ?? task?.totalImages),
  uploaded:Array.isArray(task?.uploadedFiles)?task.uploadedFiles.length.toLocaleString('zh-CN'):'未知',
  message:typeof task?.message==='string'?task.message:'',
  error:typeof task?.error==='string' && task.error ? task.error : typeof task?.errorMessage==='string'?task.errorMessage:''}
}
export function taskExecutionLogs(task){
 const logs=Array.isArray(task?.logs)?task.logs:[]
 return logs.filter(log=>log && typeof log==='object' && typeof log.text==='string' && log.text.trim()).map((log,index)=>({
  key:index,
  text:log.text,
  time:typeof log.time==='string' && /^(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d$/.test(log.time)?log.time+'（日期未记录）':log.time?beijingDateTime(log.time)||'时间格式未知':'时间未记录'
 }))
}
