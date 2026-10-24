import { beijingDateTime } from './beijingTime'
import { knownCount } from './countPresentation'

// Read-only labels for returned audit fields. No lifecycle or authorization inference.
const actions = {
  skill: {
    CREATE_DRAFT: '创建草稿', DOWNLOAD_LINK: '链接下载', UPGRADE_LINK: '链接升级',
    LINK_NO_CHANGE: '来源核对无变更', UNINSTALL_LINK: '移除链接登记', REVISE: '修订版本',
    EVAL: '规则评测', SUBMIT: '提交独立审核', PUBLISH: '审核发布', REJECT: '审核拒绝',
    ROLLBACK: '回退发布', ARCHIVE: '停用归档', COMMAND_LOAD: '斜杠命令读取',
    LOAD: '运行读取', AUTO_ARCHIVE: '自动归档', MARK_STALE: '标记待维护'
  },
  mcp: {
    PROPOSE: '提出安装', INSTALL: '安装登记', CANCEL_INSTALL: '撤销安装',
    REMOVE_REGISTRATION: '移除登记', ENABLE: '启用工具', DISABLE: '停用工具',
    PROBE: '握手探测', CALL: '网页调用', EXECUTION_OPEN: '开启执行',
    EXECUTION_RECONCILE: '核对执行退出', EXECUTION_EXIT: '记录退出与清理'
  }
}
const text = value => typeof value === 'string' ? value.trim() : ''
const runPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const mcpNotes = {
  'INSTALL:SUCCEEDED': '该次安装已完成；启用需单独操作，当前状态以上方登记为准。',
  'CANCEL_INSTALL:SUCCEEDED': '该次安装登记已撤销，文件保留；进程退出需单独核对。',
  'REMOVE_REGISTRATION:SUCCEEDED': '该次登记已移除，文件保留；退出与清理需单独核对。',
  'ENABLE:SUCCEEDED': '该时点已启用，当前启停状态以上方登记为准。',
  'DISABLE:SUCCEEDED': '该时点已停用，不据此确认子进程已退出。',
  'PROBE:SUCCEEDED': '握手探测通过，不代表网页抓取已完成。',
  'CALL:COMPLETED': '该次调用已结束，返回内容需在对应运行中核对。'
}

export function operationHistoryRows(records, kind) {
  if (!Array.isArray(records)) return null
  const occurrences = new Map()
  return records.map(value => {
    const complete = value != null && typeof value === 'object' && !Array.isArray(value)
    const row = complete ? value : {}
    const action = text(row.action_name), outcome = text(row.outcome)
    const labels = actions[kind] || {}
    const actionLabel = Object.prototype.hasOwnProperty.call(labels, action) ? labels[action] : action || '动作未记录'
    const rawTime = text(row.created_at), time = rawTime ? beijingDateTime(rawTime) : ''
    const version = knownCount(row.version_no), revision = knownCount(row.revision)
    const runId = text(row.run_id), callId = text(row.call_id), operationId = text(row.operation_id)
    const identity = JSON.stringify([action, outcome, rawTime, version, revision, runId, callId, operationId])
    const occurrence = occurrences.get(identity) || 0
    occurrences.set(identity, occurrence + 1)
    const fields = [
      revision != null ? { label: '记录中的修订号', value: revision } : null,
      operationId ? { label: '操作编号', value: operationId } : null,
      runId ? { label: '运行编号', value: runId } : null,
      callId ? { label: '调用编号', value: callId } : null
    ].filter(Boolean)
    return {
      key: identity + ':' + occurrence, complete, action, outcome,
      actionLabel,
      timeLabel: time ? time + ' · UTC+8' : rawTime ? '时间格式待核对' : '时间未记录',
      version: version != null && version > 0 ? version : null,
      fields, reason: text(row.reason), traceRunId: runPattern.test(runId) ? runId : '',
      note: kind === 'mcp' ? mcpNotes[action + ':' + outcome] || '' : ''
    }
  })
}
