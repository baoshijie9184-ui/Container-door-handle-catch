// Both entry points accept only known confirmation DTOs before enabling a write.
const token=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(value)
const states=new Set(['PENDING','APPROVED','EXECUTING','NEEDS_REVIEW','SUCCEEDED','REJECTED','CANCELLED','EXPIRED','INVALIDATED'])
export function agentImagePreview(image){
 const path=image?.previewPath
 if(image?.origin!=null){const origin=image.origin;if(!token(origin.taskId)||typeof origin.fileId!=='string'||!/^[a-f0-9-]{36}$/.test(origin.fileId)||typeof origin.resourceVersion!=='string'||!/^[a-f0-9]{64}$/.test(origin.resourceVersion))return '';const expected='/api/agent/business-files/DETECTION/'+origin.taskId+'/'+origin.fileId;return path===expected?expected:''}
 return typeof path==='string'&&/^\/api\/agent\/conversations\/[A-Za-z0-9_.-]{1,128}\/files\/[a-f0-9-]{36}\/image$/.test(path)?path:''
}
export function businessImagePreview(image){
 const path=image?.previewPath
 return typeof path==='string'&&/^\/api\/agent\/business-files\/DETECTION\/[A-Za-z0-9_-]{1,128}\/[a-f0-9-]{36}$/.test(path)?path:''
}
export function validAgentAction(value){
 if(!value||!token(value.actionId)||!Number.isSafeInteger(value.version)||value.version<1||!states.has(value.status))return false
 if(value.operation==='ASSIGN_QUALITY_TASK'){
  const c=value.command,pinned=c?.assigneeUserId!=null||c?.assigneeRevision!=null
  return token(c?.taskId)&&!!value.before&&typeof value.before==='object'&&typeof c.qualityStation==='string'&&typeof c.assignee==='string'&&(!pinned||Number.isSafeInteger(c.assigneeUserId)&&c.assigneeUserId>0&&/^[a-f0-9]{64}$/.test(c.assigneeRevision))
 }
 if(value.operation==='CREATE_DETECTION'){
  const p=value.creation
  return !!p&&Array.isArray(p.images)&&p.images.length>0&&p.images.length<=200&&p.images.every(image=>typeof image.name==='string'&&!!agentImagePreview(image)&&/^[a-f0-9]{64}$/.test(image.sha256))&&Number.isInteger(p.model?.id)&&p.model.id>0&&!!p.capture&&typeof p.capture.captureDate==='string'&&/^[a-f0-9]{64}$/.test(p.resourceVersion)&&Number.isFinite(p.threshold)&&p.threshold>=0&&p.threshold<=1
 }
 if(value.operation!=='RETRY_DETECTION')return false
 const p=value.retry
 return !!p&&token(p.taskId)&&/^[a-f0-9]{64}$/.test(p.resourceVersion)&&typeof p.status==='string'&&(p.flowStatus==null||typeof p.flowStatus==='string')&&typeof p.impact==='string'&&Number.isSafeInteger(p.imageCount)&&p.imageCount>0&&(!value.execution||value.execution.operation==='RETRY'&&value.execution.taskId===p.taskId&&token(value.execution.dispatchId)&&value.execution.status==='QUEUED')
}
