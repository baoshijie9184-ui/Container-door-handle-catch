import { businessDate, beijingDateTime } from './beijingTime'
const types = {
  CREATED:{category:'任务登记',icon:'Tickets'}, DISPATCHED:{category:'检测记录',icon:'Picture'},
  FINISHED:{category:'检测记录',icon:'Document'}, ASSIGNED:{category:'人工处理',icon:'User'},
  REVIEWED:{category:'人工处理',icon:'Search'}, DISPOSED:{category:'人工处理',icon:'Document'},
  REWORK_COMPLETED:{category:'人工处理',icon:'Edit'}
}
const text = value => typeof value === 'string' ? value : ''
// A task summary is not an immutable audit log. Preserve every returned entry and its plain text.
export function taskTimelineGroups(events) {
  if (!Array.isArray(events)) return null
  const occurrences = new Map()
  const rows = events.map((value,index) => {
    const complete = value != null && typeof value === 'object' && !Array.isArray(value)
    const event = complete ? value : {}
    const type=text(event.eventType).trim(),name=text(event.eventName).trim(),operator=text(event.operator).trim(),description=text(event.description),rawTime=text(event.occurredAt)
    const knownType=Object.prototype.hasOwnProperty.call(types,type)?types[type]:null
    const timestamp=rawTime?businessDate(rawTime)?.getTime():null
    const identity=JSON.stringify([type,name,operator,rawTime])
    const occurrence=occurrences.get(identity)||0
    occurrences.set(identity,occurrence+1)
    return {index,key:identity+':'+occurrence,complete,type,name:name||'节点名称未记录',operator:operator||'未记录',description,
      category:knownType?.category||(type?'其他节点':'类型未记录'),icon:knownType?.icon||'Document',timestamp,
      timeLabel:timestamp!=null?beijingDateTime(rawTime):rawTime?'时间格式待核对':'时间未记录',rawTime,
      longDescription:description.length>240||description.split(/\r?\n/).length>4}
  })
  const dated=rows.filter(row=>row.timestamp!=null).sort((left,right)=>left.timestamp-right.timestamp||left.index-right.index)
  const undated=rows.filter(row=>row.timestamp==null)
  return [{key:'dated',label:'按已知时间排列',rows:dated},{key:'undated',label:'时间未核对的节点',rows:undated}].filter(group=>group.rows.length)
}
