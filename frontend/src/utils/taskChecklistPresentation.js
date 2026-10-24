import {taskStepStatus} from './workbenchPresentation'

// A saved checklist is a model/workflow record, not proof that business actions succeeded.
const groups={PENDING:'pending',TODO:'pending',QUEUED:'pending',IN_PROGRESS:'running',RUNNING:'running',COMPLETED:'completed',DONE:'completed',SUCCEEDED:'completed',FAILED:'failed',CANCELLED:'cancelled',CANCELED:'cancelled'}
const labels={pending:'待处理',running:'进行中',completed:'已完成',failed:'失败',cancelled:'已取消',unknown:'状态待核对'}
const runIdPattern=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i

export function taskChecklistPresentation(tasks,traceBase=''){
 const rows=(Array.isArray(tasks)?tasks:[]).map((task,index)=>{
  const code=taskStepStatus(task?.status),group=Object.hasOwn(groups,code)?groups[code]:'unknown'
  const evidence=typeof task?.evidenceCallId==='string'?task.evidenceCallId.trim():''
  const runId=typeof task?.evidenceRunId==='string' && runIdPattern.test(task.evidenceRunId)?task.evidenceRunId:''
  const title=typeof task?.title==='string' && task.title.trim()?task.title:'未记录步骤名称'
  return {key:JSON.stringify([index,title,evidence,runId]),ordinal:index+1,code:group==='unknown'?'UNKNOWN':code,rawCode:code,group,title,evidence,runId,href:evidence && runId?traceBase.replace(/\/$/,'')+'/#/agent/trace?runId='+encodeURIComponent(runId):''}
 })
 const counts=Object.keys(labels).map(key=>({key,label:labels[key],count:rows.filter(row=>row.group===key).length})).filter(group=>group.count)
 return {rows,counts,total:rows.length,withEvidence:rows.filter(row=>row.evidence).length}
}
