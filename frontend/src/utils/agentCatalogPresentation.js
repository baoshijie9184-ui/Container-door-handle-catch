const record=value=>value && typeof value==='object' && !Array.isArray(value)
export const agentConfigText=(value,fallback='未记录')=>typeof value==='string' && value.trim()?value.trim():fallback
export const agentConfigFlag=value=>value===true?'已开启':value===false?'未开启':'未记录'
const capabilities={'detection-quality':'检测与质检','resource-management':'设备与人员','model-ops':'检测模型资料','department-analytics':'部门业务分析','detection-task':'本人检测任务','quality-review':'质检查询','device-status':'设备状态','personal-analytics':'本人业务分析','report-assistant':'报告助手'}
export const agentCapabilityLabel=agent=>agentConfigText(agent.name,agentConfigText(agent.label,capabilities[agent.id] || agent.id))
export const agentConfigNumber=value=>typeof value==='number' && Number.isSafeInteger(value) && value>=0?value:null
export function agentConfigDuration(value){
  const number=agentConfigNumber(value)
  if(number===null)return '未记录'
  return number>=1000?(number/1000).toLocaleString('zh-CN',{maximumFractionDigits:3})+' 秒':number+' ms'
}
function identifiedRows(value,key,message){
  if(!Array.isArray(value))throw new Error(message)
  const ids=new Set()
  for(const row of value){const id=record(row)?agentConfigText(row[key],''):'';if(!id || row[key]!==id || ids.has(id))throw new Error(message);ids.add(id)}
}
export function readAgentRoleCatalog(value){
  if(!record(value) || !agentConfigText(value.mainAgent,'') || value.mainAgent!==agentConfigText(value.mainAgent))throw new Error('能力目录未完整读取，请重新核对')
  identifiedRows(value.agents,'id','能力条目未完整读取，请重新核对')
  return value
}
export function readAgentModelCatalog(value){
  if(!record(value))throw new Error('模型目录未完整读取，请重新核对')
  identifiedRows(value.models,'id','模型条目未完整读取，请重新核对')
  return value
}
export function agentFallbackOrder(value){
  if(!Array.isArray(value) || value.some(item=>typeof item!=='string' || !item.trim() || item!==item.trim()) || new Set(value).size!==value.length)return null
  return value
}
export function agentModelCircuit(model){
  if(model.healthState==='OPEN')return {tone:'warning',label:'熔断等待',note:agentConfigNumber(model.retryAfterSeconds)===null?'恢复等待时间未记录':'目录快照中的恢复等待：'+model.retryAfterSeconds+' 秒'}
  if(['HALF_OPEN','PROBE_READY'].includes(model.healthState))return {tone:'warning',label:'恢复待核对',note:'恢复探测与供应商可用性仍需核对'}
  if(model.healthState==='CLOSED')return {tone:'info',label:'熔断未触发',note:''}
  return {tone:'info',label:'熔断状态未记录',note:''}
}
