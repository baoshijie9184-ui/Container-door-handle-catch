// Display metadata only. Eligibility and authorization are always determined by the server.
const entry = (label, tone = 'info', icon = 'Document') => ({ label, tone, icon })
const domains = {
  agentMode: { READ_ONLY:entry('只读查询','info','Search'), CONFIRMABLE:entry('操作需确认','info','Lock'), DRAFTS:entry('受控协作','info','Document'), DISABLED:entry('助手尚未启用','warning','Lock') },
  marketCapability: { AVAILABLE:entry('目录已核对','info','DocumentChecked'), INTERFACE_ONLY:entry('仅提供接口','warning','Connection'), UNVERIFIED:entry('尚待核对','info','Search'), OUT_OF_SCOPE:entry('目录范围之外','info','Document') },
  cardRead: { OK:entry('已重新读取','info','Refresh'), PARTIAL:entry('部分资料不可用','warning','Warning'), UNAVAILABLE:entry('暂不可读取','warning','Search') },
  detectionCreation: {
    PREPARING:entry('准备中','info','Files'), UPLOADING:entry('传输中','info','Upload'),
    NEEDS_REVIEW:entry('创建结果待核对','warning','Search'), QUEUED:entry('已提交检测','info','DocumentChecked'),
    CANCELLED:entry('创建已终止','neutral','Close')
  },
  transferCheck: {
    QUEUED:entry('等待核对','warning','Clock'), RUNNING:entry('核对中','info','Search'),
    VERIFIED:entry('内容一致','success','DocumentChecked'), INCOMPLETE:entry('内容不齐或不一致','warning','Warning'),
    UNCONFIRMED:entry('核对未完成','warning','Search'), CANCELLED:entry('核对已终止','neutral','Close')
  },
  singleDetection: {
    IDLE:entry('尚未选图','info','Picture'), READY:entry('已选择图片','info','Picture'),
    CREATING:entry('登记任务中','info','Tickets'), UPLOADING:entry('上传原图中','info','Upload'),
    UPLOADED:entry('原图已上传','info','Picture'), QUEUED:entry('等待检测','warning','Clock'),
    PENDING_DETECTION:entry('等待检测','warning','Clock'), DETECTING:entry('正在检测','info','Connection'),
    RUNNING:entry('正在检测','info','Connection'), COMPLETED:entry('检测结果已返回','success','CircleCheck'),
    PARTIAL_FAILED:entry('检测部分失败','warning','Warning'), FAILED:entry('检测失败','danger','Warning'),
    UNCONFIRMED:entry('结果待核对','warning','Search')
  },
  skillVersion: {
    DRAFT: entry('私人草稿'), EVALUATED: entry('规则通过', 'info', 'DocumentChecked'),
    SUBMITTED: entry('待主管审核', 'warning', 'Lock'), APPROVED: entry('已审核', 'success', 'CircleCheck'),
    REJECTED: entry('已驳回', 'danger', 'Warning')
  },
  skillMaintenance: { LEGACY: entry('历史上传已停用','info','Lock'), ARCHIVED: entry('已停用'), UNPUBLISHED: entry('未发布'), STALE: entry('待维护','warning','Clock'), ACTIVE: entry('发布在用','info','Collection'), UNKNOWN: entry('维护状态未记录','warning','Search') },
  skillRule: { PASSED: entry('规则通过','info','DocumentChecked'), FAILED: entry('规则未通过','danger','Warning'), UNKNOWN: entry('结果未记录','warning','Search') },
  mcpExecution: { OPENING: entry('正在连接','info','Connection'), RUNNING: entry('执行中','info','Connection'), STOPPING: entry('正在核对','warning','Search'), NEEDS_REVIEW: entry('待核对','warning','Search'), EXITED: entry('已退出 · 待清理','warning','Clock'), REMOVED: entry('已退出并清理','info','DocumentChecked') },
  mcpVersion: { INSTALLING: entry('准备中','info','Connection'), READY: entry('已保存','info','DocumentChecked'), NEEDS_REVIEW: entry('退出待核对','warning','Search'), CACHED: entry('缓存保留'), CLEANING: entry('清理中','warning','Clock'), CLEANUP_REVIEW: entry('清理待核对','warning','Search'), REMOVED: entry('已清理文件','info','DocumentChecked') },
  skillDownload: {
    NEEDS_REVIEW: entry('退出待核对', 'warning', 'Search'), DOWNLOADING: entry('下载中', 'info', 'Download'),
    DRAFT_CREATED: entry('已保存草稿', 'success', 'CircleCheck'), ERROR: entry('下载失败', 'danger', 'Warning'),
    DOWNLOADED: entry('正在创建草稿', 'info', 'Document'), NO_CHANGE: entry('无版本变化'),
    PURGING: entry('清理中', 'warning', 'Clock'), PURGED: entry('文件已清理', 'info', 'Document'),
    CLEANUP_ERROR: entry('清理待核对', 'warning', 'Search')
  },
  mcpInstallation: {
    NOT_INSTALLED: entry('未安装'), PENDING_CONFIRM: entry('待本人确认', 'warning', 'Lock'),
    INSTALLING: entry('安装中', 'info', 'Connection'), INSTALLED: entry('已安装', 'info', 'DocumentChecked'),
    ERROR: entry('安装失败', 'danger', 'Warning'), CANCELLED: entry('已取消安装'), UNINSTALLED: entry('已移除登记')
  },
  mcpEnabled: { ENABLED: entry('已启用', 'success', 'CircleCheck'), DISABLED: entry('未启用', 'info', 'Lock') },
  organizationBinding: { BIND: entry('关联员工','info','Connection'), UNBIND: entry('解除关联','warning','Lock'), REBIND: entry('更换员工','info','Connection') },
  usage: {
    IN_USE: entry('使用中', 'info', 'Monitor'), '使用中': entry('使用中', 'info', 'Monitor'), RETURNED: entry('已归还', 'info', 'CircleCheck'),
    '已归还': entry('已归还', 'info', 'CircleCheck')
  },
  detection: {
    UNKNOWN: entry('检测状态未记录','warning','Search'),
    UPLOADING: entry('上传中', 'info', 'Upload'), UPLOADED: entry('已上传', 'info', 'Picture'),
    QUEUED: entry('待检测', 'warning', 'Clock'), PENDING: entry('待检测', 'warning', 'Clock'),
    DETECTING: entry('检测中', 'info', 'Connection'), RUNNING: entry('检测中', 'info', 'Connection'),
    COMPLETED: entry('检测完成', 'success', 'CircleCheck'), PARTIAL_FAILED: entry('部分检测失败', 'warning', 'Warning'),
    FAILED: entry('检测失败', 'danger', 'Warning'), CANCELLED: entry('已取消')
  },
  review: {
    PENDING: entry('待复核', 'warning', 'Clock'), REVIEWING: entry('复核中', 'info', 'Search'),
    REVIEWED: entry('已复核', 'info', 'CircleCheck')
  },
  qualityDisposition: { PENDING: entry('待处置', 'warning', 'Clock'), DISPOSED: entry('已记录处置', 'info', 'DocumentChecked') },
  dispositionAction: {
    RELEASE: entry('正常放行处置', 'info', 'CircleCheck'), REWORK: entry('返工处理', 'warning', 'Edit'),
    RECHECK: entry('安排复检', 'warning', 'Search'), HOLD: entry('暂挂观察', 'warning', 'Clock'),
    SCRAP: entry('报废隔离', 'danger', 'Warning')
  },
  report: {
    DRAFT: entry('草稿'), SUBMITTED: entry('待审批', 'warning', 'Clock'),
    APPROVED: entry('已批准', 'success', 'CircleCheck'), REJECTED: entry('已驳回', 'danger', 'Close'),
    WITHDRAWN: entry('已撤回'), CANCELLED: entry('已取消')
  },
  switchState: { ENABLED: entry('启用', 'info', 'CircleCheck'), DISABLED: entry('停用', 'neutral', 'Lock') },
  modelConfig: {
    DRAFT: entry('待校验', 'warning', 'Edit'), VALIDATED: entry('已校验 · 待发布', 'info', 'DocumentChecked'),
    PUBLISHED: entry('已发布', 'success', 'CircleCheck'), RETIRED: entry('历史版本')
  },
  memoryConfig: {
    ENVIRONMENT: entry('沿用部署配置', 'info', 'Document'), PENDING: entry('应用中 · 需核对', 'warning', 'Clock'),
    APPLIED: entry('已应用', 'info', 'DocumentChecked')
  },
  modelProbe: {
    PASSED: entry('格式兼容通过', 'success', 'CircleCheck'), FAILED: entry('未通过 · 不自动重试', 'danger', 'Warning'),
    STARTED: entry('结果待核对 · 不自动重试', 'warning', 'Search')
  },
  traceExecution: {
    RUNNING: entry('运行中', 'info', 'Connection'), COMPLETED: entry('已完成', 'success', 'CircleCheck'),
    FAILED: entry('失败', 'danger', 'Warning'), CANCELLED: entry('已取消'), INTERRUPTED: entry('已中断', 'warning', 'Warning'),
    SUCCESS: entry('成功', 'success', 'CircleCheck'), ERROR: entry('异常', 'danger', 'Warning'), DENIED: entry('已拒绝', 'warning', 'Lock'),
    RECORDED: entry('仅有记录'), INCOMPLETE: entry('未记录终态', 'warning', 'Search'), PENDING: entry('等待结果', 'warning', 'Clock'),
    SKIPPED: entry('已跳过 · 未请求'), UNKNOWN: entry('状态未记录', 'warning', 'Search')
  },
  reviewConclusion: {
    CONFIRMED_DEFECT: entry('人工确认缺陷', 'warning', 'Search'), FALSE_POSITIVE: entry('人工判为误报', 'info', 'DocumentChecked'),
    NORMAL_RELEASE: entry('复核判为正常', 'info', 'CircleCheck'), NEEDS_RECHECK: entry('需进一步复查', 'warning', 'Search'),
    PASS: entry('历史复核通过', 'info', 'DocumentChecked'), DEFECT: entry('人工确认缺陷', 'warning', 'Search'),
    RECHECK: entry('需进一步复查', 'warning', 'Search'), REJECT: entry('复核拒绝', 'danger', 'Warning')
  },
  reportDelivery: {
    PENDING: entry('等待发送', 'warning', 'Clock'), PROCESSING: entry('发送中', 'info', 'Connection'),
    RETRY: entry('等待重试', 'warning', 'Clock'), DELIVERED: entry('已发送', 'info', 'DocumentChecked'),
    FAILED: entry('需检查后重试', 'danger', 'Warning')
  },
  executionPhase: {
    IDLE: entry('空闲'), RUNNING: entry('执行中', 'info', 'Connection'), PAUSE_REQUESTED: entry('等待安全切点暂停', 'warning', 'Clock'),
    PAUSED: entry('已暂停', 'warning', 'Clock'), REMOTE_RUNNING: entry('其他实例执行中', 'info', 'Connection'),
    WAITING_PLAN: entry('等待计划审阅', 'warning', 'DocumentChecked'), WAITING_INPUT: entry('等待补充信息', 'warning', 'ChatDotRound'),
    WAITING_CHILD: entry('后台专业任务执行中', 'info', 'Connection'), AWAITING_RECOVERY: entry('等待核对与恢复', 'warning', 'Search')
  },
  queuedInput: {
    QUEUED: entry('待处理', 'warning', 'Clock'), STARTED: entry('已领取执行', 'info', 'Connection'),
    APPLIED: entry('已交付安全切点', 'info', 'DocumentChecked'), COMPLETED: entry('已完成', 'success', 'CircleCheck'),
    FAILED: entry('已停止或失败', 'danger', 'Warning'), CANCELLED: entry('已撤回'), EXPIRED: entry('已过期', 'warning', 'Clock')
  },
  apiReceipt: {
    SUCCEEDED: entry('已收到接口回执', 'info', 'DocumentChecked'), REJECTED: entry('接口返回未成功', 'danger', 'Warning'),
    UNKNOWN: entry('结果待核对', 'warning', 'Search')
  },
  severity: {
    MINOR: entry('轻微', 'info', 'Document'), MAJOR: entry('一般', 'warning', 'Warning'),
    CRITICAL: entry('严重', 'danger', 'Warning')
  },
  modelFile: {
    RESERVED: entry('写入待核对', 'warning', 'Search'), FILE_READY: entry('文件就绪待登记', 'warning', 'Clock'),
    REGISTERED: entry('已登记', 'success', 'DocumentChecked'), RETAINED: entry('文件保留待回收', 'info', 'Files'),
    RETAINED_LEGACY: entry('旧文件待核对', 'warning', 'Search')
  },
  identityMapping: {
    ALREADY_ALIGNED: entry('已有 ID 关联', 'info', 'User'), MISSING_NAME: entry('历史名称缺失', 'warning', 'Search'),
    MISSING_NAME_CONFIRMED: entry('缺失名称已明确确认', 'info', 'DocumentChecked'), SOURCE_UNVERIFIED: entry('身份来源待核对', 'warning', 'Search'),
    ORIGINAL_ACCOUNT_UNAVAILABLE: entry('原账号不可用', 'warning', 'Lock'), UNMATCHED: entry('待手动核对', 'warning', 'Search'),
    DIFFERENT_CURRENT_ACCOUNT: entry('同名候选 ID 不同', 'warning', 'Warning'), CANDIDATE_ONLY: entry('仅有同名候选', 'warning', 'User')
  },
  memoryReview: {
    RUNNING: entry('正在分析', 'info', 'Connection'), READY: entry('分析已完成', 'info', 'DocumentChecked'),
    FAILED: entry('分析未完成', 'danger', 'Warning'), INTERRUPTED: entry('分析已中断', 'warning', 'Warning')
  },
  memoryRelation: {
    DUPLICATE: entry('可能重复', 'warning', 'DocumentCopy'), CONFLICT: entry('可能矛盾', 'warning', 'Warning'),
    RELATED: entry('相关但有区别', 'info', 'Connection'), DISTINCT: entry('不同信息', 'info', 'Document'),
    UNSURE: entry('需要人工判断', 'warning', 'Search')
  },
  memoryLifecycle: {
    ACTIVE: entry('正常使用', 'info', 'Collection'), EXCLUDED: entry('已停用 · 停止检索', 'info', 'Lock'),
    EXPIRED: entry('已过期 · 停止检索', 'warning', 'Clock'), REMOVED: entry('已核对记忆不存在', 'info', 'Search'),
    UNKNOWN: entry('治理状态未确认', 'warning', 'Search')
  },
  memoryCleanup: {
    NONE: entry('未启用自动清理'), READY: entry('等待到期清理', 'warning', 'Clock'),
    RUNNING: entry('清理中', 'info', 'Connection'), SUCCEEDED: entry('已核对记忆不存在', 'info', 'Search'),
    NEEDS_REVIEW: entry('清理结果待核对', 'warning', 'Search')
  },
  memoryAudit: {
    SUCCEEDED: entry('已完成', 'success', 'CircleCheck'), PENDING: entry('待处理', 'warning', 'Clock'),
    DISPATCHED: entry('处理中', 'info', 'Connection'), UNKNOWN: entry('结果待核对', 'warning', 'Search'),
    REJECTED: entry('未执行', 'info', 'Lock')
  },
  modelEvaluation: {
    UNASSESSED: entry('未登记评估'), EVALUATED: entry('已登记评估','info','DataAnalysis'),
    ROLLOUT: entry('已登记发布策略','info','Operation'), ROLLED_BACK: entry('已登记回滚策略','warning','Operation')
  },
  modelValidation: {
    PASSED: entry('基础校验通过', 'success', 'CircleCheck'), FAILED: entry('基础校验失败', 'danger', 'Warning'),
    PENDING: entry('待基础校验', 'warning', 'Clock')
  },
  model: {
    DRAFT: entry('草稿'), READY: entry('待发布', 'warning', 'Clock'), PUBLISHED: entry('已发布', 'success', 'CircleCheck'),
    ARCHIVED: entry('已归档'), DISABLED: entry('已停用'), FAILED: entry('失败', 'danger', 'Warning')
  },
  device: {
    IN_USE: entry('使用中', 'success', 'CircleCheck'), ONLINE: entry('在线', 'success', 'CircleCheck'),
    MAINTENANCE: entry('维护中', 'warning', 'Clock'), OFFLINE: entry('离线', 'info', 'Monitor'),
    UNUSED: entry('未使用', 'info', 'Monitor'), IDLE: entry('空闲', 'info', 'Monitor'),
    SCRAPPED: entry('已报废', 'danger', 'Warning')
  },
  employee: {
    ACTIVE: entry('在岗', 'success', 'CircleCheck'), ON_LEAVE: entry('休假', 'warning', 'Clock'),
    VACATION: entry('休假', 'warning', 'Clock'), RESIGNED: entry('已离职'), INACTIVE: entry('未在岗')
  },
  flow: {
    UPLOADING: entry('上传中', 'info', 'Upload'), PENDING_DETECTION: entry('待检测', 'warning', 'Clock'),
    DETECTING: entry('检测中', 'info', 'Connection'), PENDING_REVIEW: entry('待复核', 'warning', 'Clock'),
    REVIEWING: entry('复核中', 'info', 'Search'), CONFIRMED: entry('已确认', 'info', 'CircleCheck'),
    REWORK_REQUIRED: entry('待返工', 'warning', 'Clock'), RECHECK_REQUIRED: entry('待复检', 'warning', 'Clock'),
    RELEASED: entry('已放行', 'success', 'CircleCheck'), HOLD: entry('暂挂', 'warning', 'Clock'),
    SCRAPPED: entry('已报废', 'danger', 'Warning'), ARCHIVED: entry('已归档'), FAILED: entry('失败', 'danger', 'Warning')
  },
  audit: {
    PREPARED: entry('已准备', 'info', 'DocumentChecked'), STARTED: entry('已开始', 'info', 'Connection'), ACKNOWLEDGED: entry('已收到回执', 'info', 'DocumentChecked'),
    AUTHORIZED: entry('已授权 · 待写出', 'info', 'Lock'), HEAD_AUTHORIZED: entry('HEAD 已授权', 'info', 'Lock'), HEAD_COMPLETED: entry('HEAD 响应完成', 'info', 'DocumentChecked'),
    STREAMING: entry('服务端写出中', 'info', 'Connection'), SERVER_COMPLETED: entry('服务端响应完成', 'info', 'DocumentChecked'), INTERRUPTED: entry('响应中断', 'danger', 'Warning'), REDIRECT_AUTHORIZED: entry('已签发读取授权', 'info', 'Lock'),
    APPLIED: entry('已执行', 'success', 'CircleCheck'), SUCCESS: entry('成功', 'success', 'CircleCheck'),
    COMPLETED: entry('已完成', 'success', 'CircleCheck'), NO_CHANGE: entry('未变更'),
    REFUSED: entry('已拒绝', 'warning', 'Lock'), REJECTED: entry('已拒绝', 'warning', 'Lock'),
    FAILED: entry('失败', 'danger', 'Warning'), UNKNOWN: entry('待核对', 'warning', 'Search'),
    PENDING: entry('待处理', 'warning', 'Clock'), DISPATCHED: entry('已派发', 'info', 'Connection')
  },
  confirmation: {
    PENDING: entry('待确认', 'warning', 'Lock'), EXECUTING: entry('准备文件', 'info', 'Connection'),
    NEEDS_REVIEW: entry('待核对', 'warning', 'Search'), SUCCEEDED: entry('已执行', 'success', 'CircleCheck'),
    REJECTED: entry('已拒绝'), CANCELLED: entry('已取消'), EXPIRED: entry('已过期'), INVALIDATED: entry('已失效', 'warning', 'Warning')
  },
  delivery: {
    AUTHORIZED: entry('已授权，待写出', 'info', 'Lock'), HEAD_AUTHORIZED: entry('HEAD 已授权', 'info', 'Lock'),
    HEAD_COMPLETED: entry('HEAD 响应完成', 'success', 'CircleCheck'), STREAMING: entry('服务端写出中', 'info', 'Connection'),
    SERVER_COMPLETED: entry('服务端响应完成', 'success', 'CircleCheck'), INTERRUPTED: entry('响应中断', 'danger', 'Warning'),
    UNKNOWN: entry('结果待核对', 'warning', 'Search'), REDIRECT_AUTHORIZED: entry('已签发读取授权', 'info', 'Lock')
  },
  contextRecord: {
    ACTIVE: entry('摘要已保存', 'info', 'DocumentChecked'), INVALIDATED: entry('摘要已失效', 'warning', 'Warning'),
    OFFLOADED: entry('私有资料已保存', 'info', 'Files'), CONTEXT_STARTED: entry('正在生成摘要', 'info', 'Connection'),
    CONTEXT_COMPLETED: entry('已应用压缩', 'info', 'DocumentChecked'), CONTEXT_FAILED: entry('保留原上下文', 'warning', 'Warning'),
    CONTEXT_CANCELLED: entry('摘要已取消', 'info', 'Document'), UNKNOWN: entry('上下文状态待核对', 'warning', 'Search')
  },
  task: {
    UNAVAILABLE: entry('暂不可读取','warning','Search'),
    PENDING: entry('待处理', 'warning', 'Clock'), QUEUED: entry('排队中', 'warning', 'Clock'),
    RUNNING: entry('执行中', 'info', 'Connection'), COMPLETED: entry('已完成', 'success', 'CircleCheck'),
    SUCCEEDED: entry('已完成', 'success', 'CircleCheck'), FAILED: entry('失败', 'danger', 'Warning'),
    CANCELLED: entry('已取消'), CANCELED: entry('已取消'), PAUSED: entry('已暂停', 'warning', 'Clock'),
    WAITING_USER: entry('等待回答', 'warning', 'Clock'), NEEDS_REVIEW: entry('待核对', 'warning', 'Search'),
    UNKNOWN: entry('结果未知', 'warning', 'Search'), INTERRUPTED: entry('执行中断', 'warning', 'Warning'),
    READY: entry('待继续', 'warning', 'Clock'), WAITING_PLAN: entry('等待审阅', 'warning', 'Clock'),
    WAITING_INPUT: entry('等待回答', 'warning', 'Clock'), WAITING_CHILD: entry('等待专业任务', 'info', 'Connection'),
    APPROVED: entry('已批准', 'success', 'CircleCheck'), CHANGES_REQUESTED: entry('待修订', 'warning', 'Edit'),
    ANSWERED: entry('已回答', 'success', 'CircleCheck'), ACTIVE: entry('进行中', 'info', 'Connection'),
    REFERENCE_ONLY: entry('仅供参考'), DONE: entry('已完成', 'success', 'CircleCheck'),
    IN_PROGRESS: entry('进行中', 'info', 'Connection'), TODO: entry('待处理', 'warning', 'Clock')
  }
}
const aliases = { '使用中': 'IN_USE', '维护中': 'MAINTENANCE', '离线': 'OFFLINE', '未使用': 'UNUSED', '在岗': 'ACTIVE', '休假': 'ON_LEAVE', '离职': 'RESIGNED' }

export function statusPresentation(domain, code, label) {
  const raw = code == null ? '' : String(code).trim()
  const presentation = domains[domain]?.[aliases[raw] || raw]
  return { ...(presentation || entry(raw || '未知', raw ? 'info' : 'warning', raw ? 'Document' : 'Search')), label: label || presentation?.label || raw || '未知', code: raw }
}
