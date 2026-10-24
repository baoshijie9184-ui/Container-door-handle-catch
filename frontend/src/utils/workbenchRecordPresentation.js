// Read-only presentation of server-returned plans, questions and saved responses.
function prose(value, missing) {
  return typeof value === 'string' && value.trim() ? value : missing
}
function record(key, label, icon, text, note = '', values) {
  const content = values ? values.join('\n') : text
  return { key, label, icon, text, note, values, long:content.length > 480 || content.split(/\r?\n/).length > 7 }
}
export function workbenchInteractionRecords(item) {
  if (!['PLAN', 'QUESTION'].includes(item?.kind)) return []
  const plan = item.kind === 'PLAN', data = item.data || {}
  const rows = [record('body', plan ? '本版执行范围' : '问题内容', plan ? 'Document' : 'ChatDotRound', prose(data.text, '正文尚未完整读取，请刷新核对。'))]
  if (!plan && item.status === 'ANSWERED') {
    const values = Array.isArray(data.answer) && data.answer.length && data.answer.every(value => typeof value === 'string' && value.trim()) ? data.answer : undefined
    rows.push(record('answer', '已保存的回答', 'ChatDotRound', values ? '' : prose(data.answer, '回答内容尚未完整读取，请刷新核对。'), '这是已返回的回答记录，不是新的提交；普通回答不授予业务操作权限。', values))
  }
  if (plan && typeof data.feedback === 'string' && data.feedback.trim()) rows.push(record('feedback', '已保存的修订意见', 'Edit', data.feedback, '仅展示本记录中的修订意见，后续计划仍需按其版本单独审阅。'))
  return rows
}
