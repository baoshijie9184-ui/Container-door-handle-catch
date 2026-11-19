// The visible navigation groups are the source of pages for the current account.
const keywords = {
  '/inspection/tasks': '任务总表 我的任务 接单 派发检测 质检任务 OSS 文件夹 进度',
  '/upload': '批量上传 上传图片 上传文件夹 图像采集 创建任务',
  '/inspection/workbench': '单图检测 开始检测 检测图片 阈值',
  '/inspection/history': '看图 浏览图片 历史任务 检测结果 原图 标注',
  '/quality/queue': '领任务 领取 复核图片 处理待办 质检队列',
  '/quality/reports': '编写报告 质检报告 查看报告',
  '/employees': '查人 查员工 员工名册 查工号 人员目录',
  '/devices': '找设备 设备台账 设备目录 查设备',
  '/models': '检测模型 模型版本',
  '/agent/chat': '问助手 聊天 AI 对话',
  '/agent/model-quotas': '我的额度 查额度 使用量 余额 token 大模型',
  '/agent/model-config': '配置连接 密钥 API'
}

const actions = {
  browse: { label:'浏览检测图片', icon:'Picture', path:'/inspection/history' },
  upload: { label:'批量上传图片', icon:'Upload', path:'/upload' },
  detect: { label:'单图检测', icon:'Search', path:'/inspection/workbench' },
  quality: { label:'处理质检待办', icon:'CircleCheck', path:'/quality/queue' },
  reports: { label:'查看质检报告', icon:'DocumentChecked', path:'/quality/reports' },
  quotas: { label:'查看我的额度', icon:'DataAnalysis', path:'/agent/model-quotas' },
  assign: { label:'分派质检任务', keywords:'分派任务 分配任务 分派人员 指派质检', icon:'User', path:'/quality/queue' },
  budgets: { label:'分配员工额度', keywords:'分配额度 员工限额 设置预算 分配限额', icon:'DataAnalysis', path:'/agent/model-quotas' },
  approve: { label:'审批质检报告', keywords:'审批报告 审核报告 待审批', icon:'DocumentChecked', path:'/quality/reports', query:{status:'SUBMITTED'} }
}
export function homeActions(supervisor) {
  return (supervisor ? ['assign','approve','budgets','browse'] : ['upload','browse','quality','reports']).map(key => actions[key])
}
export function actionLocation(item) {
  return { path:item.path, query:item.query }
}
export function findWorkspaceActions(groups, role, search) {
  const terms = search.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const pages = groups.flatMap(group => group.items.map(item => ({
    ...item, group:group.label, symbol:group.icon, keywords:keywords[item.path] || ''
  })))
  const visible = new Map(pages.map(page => [page.path,page]))
  const extra = [...homeActions(role==='SUPERVISOR'),actions.detect,actions.quotas]
  if (role==='SUPERVISOR') {
    extra.push({label:'新增人员',icon:'User',path:'/employees/add',parent:'/employees',keywords:'登记员工 添加人员'},
               {label:'新增设备',icon:'Monitor',path:'/devices/add',parent:'/devices',keywords:'登记设备 添加设备'})
  }
  const shortcuts = extra.filter(item => visible.has(item.parent || item.path)).map(item => ({...item,group:'常用操作'}))
  const matches = item => {
    const text = [item.label,item.group,item.desc,item.keywords].filter(Boolean).join(' ').toLowerCase()
    return terms.every(term => text.includes(term))
  }
  return [...shortcuts,...pages].filter(matches)
}
