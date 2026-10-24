import { beijingDateTime } from './beijingTime'
export function forkMessageId(value) {
  if (typeof value !== 'number' && (typeof value !== 'string' || !/^[1-9]\d*$/.test(value))) return ''
  const number = Number(value)
  return Number.isSafeInteger(number) && number > 0 ? String(number) : ''
}
function replyText(message) {
  if (typeof message.text === 'string') return message.text
  if (typeof message.content !== 'string') return ''
  if (message.messageType === 'AGENT_CARDS') {
    try {const value=JSON.parse(message.content);return value?.version===1 && typeof value.text==='string' ? value.text : ''} catch {return ''}
  }
  return !message.messageType || message.messageType === 'TEXT' ? message.content : ''
}
export function forkCandidates(messages) {
  const rows=[]
  const occurrences=new Map()
  for (const message of Array.isArray(messages)?messages:[]) {
    if (!message || message.role!=='assistant' || message.streaming===true || message.loading===true || message.statusPlaceholder===true || message.msgStatus==='error') continue
    const id=forkMessageId(message.id ?? message.key)
    if (!id) continue
    const text=replyText(message),time=typeof message.createdAt==='string'?beijingDateTime(message.createdAt):''
    occurrences.set(id,(occurrences.get(id)||0)+1)
    rows.push({id,text,excerpt:text.replace(/\s+/g,' ').trim().slice(0,180),preview:text.slice(0,4000),truncated:text.length>4000,time,signature:JSON.stringify([id,text,time])})
  }
  return rows.filter(row=>occurrences.get(row.id)===1).slice(-20)
}
export function filterForkCandidates(rows,query='') {
  const needle=query.trim().toLocaleLowerCase('zh-CN')
  return rows.filter(row=>!needle || [row.id,row.text].join('\n').toLocaleLowerCase('zh-CN').includes(needle))
}
export function forkLineage(value) {
  return typeof value?.sourceSessionId==='string' && /^[A-Za-z0-9_-]{1,128}$/.test(value.sourceSessionId)
    ? {id:value.sourceSessionId,cutoff:forkMessageId(value.throughMessageId),legacy:value.legacyFileBoundary===true} : null
}
