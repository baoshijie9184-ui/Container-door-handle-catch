export const CHILD_FOLLOWUP_LIMIT=4000
export function childTaskPresentation(item){
 const status=typeof item?.status==='string'?item.status:'',data=item?.data||{}
 const output=typeof data.result==='string'?data.result:''
 const states={
  COMPLETED:'专业任务已记录完成；可补充要求继续处理，业务结论仍以原任务和人工审批为准。',
  RUNNING:'专业任务正在执行。此时追加的要求会在当前执行结束后继续处理。',
  QUEUED:'专业任务正在等待执行。追加要求仍按原队列规则处理，不代表已经立即执行。',
  WAITING_INPUT:'专业任务正在等待必要信息，请先在待回答视图处理原问题；回答不授予业务操作权限。',
  WAITING_PLAN:'专业任务正在等待计划审阅，请先核对原计划范围。',
  NEEDS_REVIEW:'专业任务已中断待核对，请使用原检查点恢复区；未知写入结果不能自动重做。',
  CANCELLED:'此专业任务已记录取消，已完成操作不会自动回滚；主任务和其他子任务状态需分别核对。'
 }
 return {output,excerpt:output.replace(/\s+/g,' ').trim().slice(0,280),
  explanation:Object.hasOwn(states,status)?states[status]:'专业任务当前阶段尚未明确，请刷新并核对执行轨迹。',
  canAppend:['COMPLETED','RUNNING','QUEUED'].includes(status),
  canCancel:['QUEUED','RUNNING','WAITING_INPUT','WAITING_PLAN','NEEDS_REVIEW'].includes(status),
  resultNote:status==='COMPLETED'?'此处为最近保存的结果，不代替业务回执或人工复核。':'当前任务尚未记录完成，下方结果可能来自此前执行，不作为本轮完成证明。',
  nextView:status==='WAITING_INPUT'?'QUESTION':status==='WAITING_PLAN'?'PLAN':'',
  nextLabel:status==='WAITING_INPUT'?'查看待回答问题':status==='WAITING_PLAN'?'查看待审阅计划':''}
}
export function childFollowupReady(value){return typeof value==='string' && !!value.trim() && value.length<=CHILD_FOLLOWUP_LIMIT}
