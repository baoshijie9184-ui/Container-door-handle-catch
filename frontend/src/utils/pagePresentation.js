// Presentation metadata only: route guards and API permissions remain authoritative.
const sections = [
  ['/inspection/history', '检测记录', 'DocumentCopy', '检测业务'],
  ['/inspection', '检测工作台', 'Picture', '检测业务'],
  ['/quality/queue', '质检队列', 'CircleCheck', '质量管理'],
  ['/quality/reports', '报告与审批', 'Document', '质量管理'],
  ['/quality/evidence', '缺陷证据库', 'Picture', '质量管理'],
  ['/quality/work-order-trace', '工单追溯', 'Connection', '质量管理'],
  ['/quality/batch-trace', '批次追溯', 'Connection', '质量管理'],
  ['/device-records', '设备使用记录', 'DocumentCopy', '产线资源'],
  ['/devices', '设备管理', 'Monitor', '产线资源'],
  ['/employees', '人员管理', 'User', '产线资源'],
  ['/organization', '账号与组织', 'User', '产线资源'],
  ['/models', '检测模型', 'Tickets', '模型中心'],
  ['/operations/identity', '任务账号关联', 'Key', '业务治理'],
  ['/operations/audit', '操作审计', 'DocumentChecked', '业务治理'],
  ['/agent/chat', '智能对话', 'ChatDotRound', '智能助手'],
  ['/agent/trace', '执行追溯', 'Connection', '智能助手'],
  ['/agent/actions', '操作确认', 'CircleCheck', '智能助手'],
  ['/agent/skills', '技能管理', 'DocumentCopy', '智能助手'],
  ['/agent/markets', '资源市场', 'Search', '智能助手'],
  ['/agent/memory', '个人记忆', 'Collection', '智能助手'],
  ['/agent/mcp', 'MCP 工具', 'Operation', '智能助手'],
  ['/agent/model-config', '模型配置', 'Tickets', '智能助手'],
  ['/upload', '图片上传', 'Upload', '检测业务'],
  ['/manual', '使用手册', 'Files', '帮助'],
  ['/home', '首页总览', 'DataAnalysis', '工作空间'],
  ['/test-upload', '上传诊断', 'Upload', '诊断工具']
]

export const detectionPresentation = {
  workspace: { title: '检测工作台', icon: 'Picture', description: '选择图片与检测模型，查看任务进度和识别结果，完成后进入人工复核。' },
  history: { title: '检测记录', icon: 'DocumentCopy', description: '按时间、采集信息和任务状态查找结果，查看原图、标注与历史结论。' },
  quality: { title: '质检队列', icon: 'CircleCheck', description: '集中处理分派、复核和处置，核对责任人、截止时间及后续复检要求。' },
  'defect-gallery': { title: '缺陷证据库', icon: 'Picture', description: '对照缺陷图片与检测依据，定位需要人工确认的问题。' },
  'work-order-trace': { title: '工单追溯', icon: 'Connection', description: '按工单串联检测结果、复核结论和处置记录。' },
  'batch-trace': { title: '批次追溯', icon: 'Connection', description: '按采集批次查看质量分布、检测记录和处理进度。' }
}

export function pagePresentation(route) {
  const tab = String(route.query?.tab || route.meta?.detectionTab || 'workspace')
  if (route.path === '/detection' || route.meta?.detectionTab) {
    return { group: '检测与质检', ...(detectionPresentation[tab] || detectionPresentation.workspace) }
  }
  const entry = sections.find(([path]) => route.path === path || route.path.startsWith(path + '/'))
  return entry ? { title: route.meta?.title || entry[1], icon: entry[2], group: entry[3] }
    : { title: route.meta?.title || '工作空间', icon: 'Files', group: '工作空间' }
}
