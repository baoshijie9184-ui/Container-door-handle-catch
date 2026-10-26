import { beijingDateTime } from './beijingTime'
import { composerAttachment } from './composerPresentation'

// Display metadata only. Execution state and available commands remain server-owned.
const kinds = {
  PLAN: { label: '执行计划', icon: 'DocumentChecked' },
  TASKS: { label: '任务清单', icon: 'Tickets' },
  QUESTION: { label: '任务提问', icon: 'ChatDotRound' },
  CHILD: { label: '专业子任务', icon: 'Connection' },
  EXECUTION: { label: '后台任务', icon: 'Operation' },
  EXTERNAL_JOB: { label: '关联业务任务', icon: 'Connection' },
  USAGE: { label: '模型用量', icon: 'DataAnalysis' },
  CONTEXT: { label: '上下文资料', icon: 'Files' },
  TOOL_TIMING: { label: '工具耗时', icon: 'Clock' },
  FORK_SNAPSHOT: { label: '分支计划快照', icon: 'DocumentCopy' }
}

const emptyViews = {
  PLAN: { title: '暂无计划或任务清单', description: '复杂任务生成计划后在这里审阅，简单查询可直接执行。', icon: 'DocumentChecked' },
  QUESTION: { title: '暂无待回答的问题', description: 'Agent 需要补充必要信息时会在这里提问。回答不代替业务授权。', icon: 'ChatDotRound' },
  CHILD: { title: '暂无专业子任务', description: '专业委派后，可在这里查看结果、追加要求或取消子任务。', icon: 'Connection' },
  EXECUTION: { title: '暂无后台任务', description: '长时间任务和关联业务任务会在这里显示其实际状态。', icon: 'Operation' },
  USAGE: { title: '暂无已记录的用量', description: '执行后显示供应商用量、上下文及耗时，缺失数据保持未知。', icon: 'DataAnalysis' },
  RECOVERY: { title: '暂无待核对的中断任务', description: '出现可核对的中断记录后，在这里查看恢复选项。', icon: 'Refresh' }
}

export function workbenchKind(kind) { return kinds[kind] || { label: '工作记录', icon: 'Document' } }
export function workbenchTabIcon(tab) { return ({ FILE:'Files', FORK:'DocumentCopy', RECOVERY:'Refresh' })[tab] || workbenchKind(tab).icon }
export function workbenchInteractionStatus(item) {
  if (item?.status === 'PENDING') return item.kind === 'PLAN' ? '待审阅' : item.kind === 'QUESTION' ? '待回答' : undefined
}
export function workbenchTitle(item) { return item?.data?.title || item?.data?.specialist || workbenchKind(item?.kind).label }
export function workbenchEmpty(tab,state) {
  if(state?.error)return {title:'工作记录暂不可读取',description:'读取未完成，请刷新核对，不根据空列表推断任务未执行。',icon:'Warning'}
  if(state?.loaded===false)return {title:'正在读取工作记录',description:'读取完成后显示本会话已保存的计划、任务与用量。',icon:'Connection'}
  return emptyViews[tab] || { title: '暂无工作记录', description: '当前视图的记录会在这里显示。', icon: 'Files' }
}
export function workbenchTime(value) { return value ? beijingDateTime(value) : '' }
export function taskStepStatus(status) { return typeof status === 'string' ? status.toUpperCase() : '' }
export function taskListSummary(tasks) {
  if (!Array.isArray(tasks) || !tasks.length) return ''
  const completed = tasks.filter(task => ['DONE', 'COMPLETED'].includes(taskStepStatus(task?.status))).length
  const failed = tasks.filter(task => taskStepStatus(task?.status) === 'FAILED').length
  return `已完成 ${completed} / ${tasks.length} 个步骤${failed ? `，失败 ${failed} 个` : ''}`
}
export function workbenchAnswer(answer) {
  if (typeof answer === 'string') return answer || '未记录回答内容'
  if (Array.isArray(answer) && answer.every(value => typeof value === 'string')) return answer.join('、') || '未记录回答内容'
  return '未记录回答内容'
}

// Mirror the existing question/feedback input bounds for display and submit state.
// These checks never grant permission; the original versioned command remains authoritative.
export const WORKBENCH_RESPONSE_LIMIT = 4000
export function workbenchQuestionType(data) {
  return ['TEXT','SINGLE','MULTIPLE'].includes(data?.questionType) ? data.questionType : 'UNKNOWN'
}
export function workbenchQuestionOptions(data) {
  const options = data?.options
  return Array.isArray(options) && options.length >= 2 && options.length <= 8 &&
    options.every(option => typeof option === 'string' && option.trim() && option.length <= 200) &&
    new Set(options).size === options.length ? options : []
}
export function workbenchAnswerReady(data, answer) {
  const type = workbenchQuestionType(data)
  if (type === 'TEXT') return typeof answer === 'string' && !!answer.trim() && answer.length <= WORKBENCH_RESPONSE_LIMIT
  const options = workbenchQuestionOptions(data)
  if (!options.length) return false
  if (type === 'SINGLE') return typeof answer === 'string' && options.includes(answer)
  return type === 'MULTIPLE' && Array.isArray(answer) && answer.length > 0 &&
    new Set(answer).size === answer.length && answer.every(value => options.includes(value))
}

export function workbenchFileGroups(files = [], query = '') {
  const rows = Array.isArray(files) ? files : []
  const folders = [
    { key:'uploads', label:'上传资料', icon:'Upload', note:'本人上传，按文件编号引用' },
    { key:'artifacts', label:'生成产物', icon:'DocumentChecked', note:'Agent 生成的报告与数据文件' },
    { key:'context', label:'上下文资料', icon:'Files', note:'执行记录使用的私有资料，暂不提供手动移出' }
  ]
  if(rows.some(file => !folders.some(folder => folder.key === file.folder))) folders.push({key:'other',label:'未分类资料',icon:'Files',note:'分类尚未核对，可预览或下载'})
  return folders.map(folder => ({...folder,readOnly:['context','other'].includes(folder.key),files:rows.filter(file => (folder.key==='other' ? !['uploads','artifacts','context'].includes(file.folder) : file.folder===folder.key) && workbenchFileMatches(file,query))}))
}
export function workbenchFileMatches(file, query = '') {
  const needle = query.trim().toLowerCase()
  return !needle || [file?.name,file?.id,file?.resourceId,file?.fileId].filter(value=>typeof value==='string').join(' ').toLowerCase().includes(needle)
}
// Group only the references returned for this session. No additional reads or permission inference.
// Keep first-seen order so workbench refreshes do not reorder the reader's current list.
export function workbenchBusinessFileGroups(files = [], query = '') {
  const groups = new Map()
  for (const file of Array.isArray(files) ? files : []) {
    if (!file || !['DETECTION','REPORT'].includes(file.kind) || typeof file.resourceId !== 'string') continue
    const key = JSON.stringify([file.kind,file.resourceId])
    if (!groups.has(key)) groups.set(key,{
      key,resourceId:file.resourceId,label:file.kind==='REPORT'?'质检报告':'检测任务',
      icon:file.kind==='REPORT'?'DocumentChecked':'Picture',total:0,files:[]
    })
    const group = groups.get(key)
    group.total += 1
    if (workbenchFileMatches(file,query)) group.files.push(file)
  }
  return [...groups.values()].filter(group=>group.files.length)
}
export function workbenchFileSummary(files = []) {
  const rows = Array.isArray(files) ? files : []
  const bytes = rows.every(file => Number.isSafeInteger(file?.bytes) && file.bytes>=0) ? rows.reduce((sum,file)=>sum+file.bytes,0) : null
  return {count:rows.length,size:composerAttachment({bytes:Number.isSafeInteger(bytes)?bytes:null}).size}
}
export function workbenchUsagePurpose(purpose) {
  return ({SESSION_TOTAL:'本会话已记录汇总',CONTEXT_COMPACTION:'上下文摘要',AGENT_REASONING:'Agent 推理'})[purpose] || purpose || '用途未记录'
}
