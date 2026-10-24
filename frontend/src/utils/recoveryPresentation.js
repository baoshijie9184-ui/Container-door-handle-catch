import {recoveryInput} from './agentWorkbench'
import {modelLabel} from './composerResources'

const text=value=>typeof value==='string' && value.trim()?value:''
const version=value=>Number.isSafeInteger(value) && value>0?'V'+value.toLocaleString('zh-CN'):'版本未核对'
export function recoveryPresentation(item,state={},choice='KEEP'){
 const main=item?.kind==='EXECUTION',supported=main || item?.kind==='CHILD'
 const data=item?.data||{},models=(Array.isArray(state.recoveryModels)?state.recoveryModels:[]).filter(model=>text(model?.id) && text(model?.model))
 const chosen=models.find(model=>model.id===choice)
 const absentChoice=main && !['KEEP','CURRENT_DEFAULT'].includes(choice) && !chosen
 const selected=choice==='KEEP' || !main?'保留任务原配置':choice==='CURRENT_DEFAULT'?'当前默认 · '+(text(state.recoveryDefault)||'尚未核对'):chosen?modelLabel(chosen):'所选模型尚未核对'
 let reason=''
 if(!supported)reason='此类记录不提供检查点恢复，请查看原任务。'
 else if(state.capabilities?.recovery===false)reason='恢复功能当前关闭，记录继续保留供核对。'
 else if(state.error)reason='本次工作记录读取未完成，请先刷新核对。'
 else if(state.loaded===false)reason='工作记录尚未读取完成。'
 else try{recoveryInput(main?choice:'KEEP',state)}catch(cause){reason=cause.message}
 return {main,supported,models,absentChoice,selected,reason,canResume:!reason,
  originalModel:text(data.modelId)||text(data.modelDefault)||'具体模型未记录',originalVersion:version(data.modelConfigVersion),currentVersion:version(state.recoveryConfigVersion),
  defaultKnown:models.some(model=>model.id===state.recoveryDefault),
  endNote:main?'结束本任务及其活动子任务，已完成的业务操作不会回滚。':'结束此专业任务，已完成操作保留；主任务和其他专业任务需分别核对。'}
}
export function recoveryReviewError(item,state,choice,input){
 const current=(state.items||[]).find(row=>row.id===item.id)
 if(!current || current.revision!==item.revision || current.kind!==item.kind || current.status!=='NEEDS_REVIEW')return '任务记录已变化，请重新核对后再恢复'
 const review=recoveryPresentation(current,state,choice)
 if(review.reason)return review.reason
 try{if(JSON.stringify(recoveryInput(current.kind==='EXECUTION'?choice:'KEEP',state))!==JSON.stringify(input))return '恢复模型或配置版本已变化，请重新核对后再确认'}catch(cause){return cause.message}
 return ''
}
