import { beijingDateTime } from './beijingTime.js'

// Read only the existing immutable assignment proposal, never the current task.
const fields = [
  ['qualityStation', '质检站点'], ['assignee', '责任人'],
  ['assigneeUserId', '责任人 ID'], ['dueAt', '截止时间 · UTC+8'],
  ['assignmentRemark', '分派备注']
]
function value(source, key, proposed) {
  if (!source || !Object.prototype.hasOwnProperty.call(source, key) || source[key] === undefined) return '未记录'
  const raw = source[key]
  if (key === 'assigneeUserId') return Number.isSafeInteger(raw) && raw > 0 ? String(raw) : '未记录'
  if (raw === null || raw === '') {
    if (key === 'dueAt') return '未设置'
    if (key === 'assignmentRemark') return '未填写'
    return proposed ? '未填写' : '未分配'
  }
  if (typeof raw !== 'string') return '资料格式待核对'
  return key === 'dueAt' ? beijingDateTime(raw) || `时间格式待核对：${raw}` : raw
}
function cell(text) {
  const points = Array.from(text), lines = text.split(/\r?\n/)
  const folded = points.length > 240 || lines.length > 5
  return { text, folded, preview: folded ? Array.from(lines.slice(0, 4).join('\n')).slice(0, 220).join('') + '…' : text }
}
export function assignmentReviewRows(before, command) {
  return fields.map(([key, label]) => ({ key, label, before: cell(value(before, key, false)), proposed: cell(value(command, key, true)) }))
}
