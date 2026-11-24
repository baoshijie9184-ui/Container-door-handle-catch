import { createRouter, createWebHashHistory } from 'vue-router'
import {systemPageTitle} from '../utils/systemBrand'
import { useUserStore } from '../stores/user'
import { recordNavigationFailure, clearNavigationFailure } from '../utils/navigationFeedback'

const routes = [
  {
    path: '/',
    component: () => import('../layout/index.vue'),
    redirect: '/login',
    meta: { requiresAuth: true },
    children: [
      {
        path: '/home',
        name: 'home',
        component: () => import('../views/Home.vue'),
        meta: { title: '首页总览', icon: 'HomeFilled' }
      },
      {
        path: 'upload',
        name: 'upload',
        component: () => import('../views/ImageUpload.vue'),
        meta: { title: '图片上传', requiresAuth: true, icon: 'Upload' }
      },
      {
        path: 'detection',
        name: 'detection',
        component: () => import('../views/ImageDetection.vue'),
        meta: { title: '图像检测', requiresAuth: true, hidden: true, detectionTab: 'workspace' }
      },
      {
        path: 'inspection/uploads', name: 'imageUploadRecords',
        component: () => import('../views/FolderTaskBoard.vue'),
        beforeEnter: to => {
          const { scope, ...query } = to.query
          const mine = scope === 'mine' || (scope !== 'team' && useUserStore().role !== 'SUPERVISOR')
          return { name: mine ? 'myUploadRecords' : 'allUploadRecords', query, hash: to.hash, replace: true }
        },
        meta: { title: '图片上传记录', requiresAuth: true }
      },
      {
        path: 'inspection/uploads/dispatch', name: 'awaitingDetectionDispatch',
        component: () => import('../views/FolderTaskBoard.vue'),
        meta: { title:'待派检测的文件夹', requiresAuth:true, supervisorOnly:true, uploadScope:'team', awaitingDispatch:true }
      },
      {
        path: 'inspection/uploads/mine', name: 'myUploadRecords',
        component: () => import('../views/FolderTaskBoard.vue'),
        meta: { title: '我的上传记录', requiresAuth: true, uploadScope: 'mine' }
      },
      {
        path: 'inspection/uploads/all', name: 'allUploadRecords',
        component: () => import('../views/FolderTaskBoard.vue'),
        meta: { title: '全部上传记录', requiresAuth: true, uploadScope: 'team' }
      },
      {
        path: 'inspection/tasks', name: 'folderTaskBoard',
        component: () => import('../views/FolderTaskBoard.vue'),
        meta: { title: '任务总表', requiresAuth: true }
      },
      {
        path: 'inspection/tasks/detection', name: 'supervisorDetectionTasks',
        component: () => import('../views/FolderTaskBoard.vue'),
        meta: { title: '检测任务列表', requiresAuth: true, supervisorOnly: true, taskList: 'detection' }
      },
      {
        path: 'inspection/tasks/verification', name: 'supervisorVerificationTasks',
        component: () => import('../views/FolderTaskBoard.vue'),
        meta: { title: '校验任务列表', requiresAuth: true, supervisorOnly: true, taskList: 'verification' }
      },
      {
        path: 'inspection/applications', name: 'detectionApplicationHistory',
        component: () => import('../views/inspection/DetectionApplicationHistory.vue'),
        meta: { title: '检测申请记录', requiresAuth: true, supervisorOnly: true }
      },
      {
        path: 'inspection/historical-ledger', name: 'historicalDetectionLedger',
        component: () => import('../views/inspection/HistoricalDetectionLedger.vue'),
        meta: { title: '历史检测台账', employeeTitle: '我的历史台账', requiresAuth: true }
      },
      {
        path: 'inspection/workbench',
        name: 'inspectionWorkbench',
        component: () => import('../views/ImageDetection.vue'),
        meta: { title: '单图检测与对比', requiresAuth: true, detectionTab: 'workspace' }
      },
      {
        path: 'inspection/history',
        name: 'inspectionHistory',
        component: () => import('../views/ImageDetection.vue'),
        meta: { title: '检测记录', requiresAuth: true, detectionTab: 'history' }
      },
      {
        path: 'quality/queue',
        name: 'legacyQualityQueue',
        meta: { requiresAuth: true, hidden: true }
      },
      {
        path: 'quality/reports',
        name: 'qualityReports',
        component: () => import('../views/QualityReports.vue'),
        meta: { title: '报告与审批', requiresAuth: true }
      },
      {
        path: 'quality/work-order-trace',
        name: 'workOrderTrace',
        component: () => import('../views/ImageDetection.vue'),
        meta: { title: '工单追溯', requiresAuth: true, detectionTab: 'work-order-trace' }
      },
      {
        path: 'quality/batch-trace',
        name: 'batchTrace',
        component: () => import('../views/ImageDetection.vue'),
        meta: { title: '批次追溯', requiresAuth: true, detectionTab: 'batch-trace' }
      },
      {
        path: 'devices',
        name: 'devices',
        component: () => import('../views/device/DeviceList.vue'),
        meta: { title: '设备管理', employeeTitle: '设备目录', requiresAuth: true, icon: 'Monitor' }
      },
      {
        path: 'devices/add',
        name: 'deviceAdd',
        component: () => import('../views/device/DeviceForm.vue'),
        meta: { title: '新增设备', requiresAuth: true, supervisorOnly: true, parent: '设备管理', parentPath: '/devices' }
      },
      {
        path: 'devices/:id',
        name: 'deviceDetail',
        component: () => import('../views/device/DeviceDetail.vue'),
        meta: { title: '设备详情', requiresAuth: true, parent: '设备管理', parentPath: '/devices' }
      },
      {
        path: 'devices/edit/:id',
        name: 'deviceEdit',
        component: () => import('../views/device/DeviceForm.vue'),
        meta: { title: '编辑设备', requiresAuth: true, supervisorOnly: true, parent: '设备管理', parentPath: '/devices' }
      },
      {
        path: 'employees',
        name: 'employees',
        component: () => import('../views/employee/EmployeeList.vue'),
        meta: { title: '人员管理', employeeTitle: '人员目录', requiresAuth: true, icon: 'User' }
      },
      {
        path: 'employees/add',
        name: 'employeeAdd',
        component: () => import('../views/employee/EmployeeForm.vue'),
        meta: { title: '新增人员', requiresAuth: true, supervisorOnly: true, parent: '人员管理', parentPath: '/employees' }
      },
      {
        path: 'organization',
        name: 'organization',
        component: () => import('../views/Organization.vue'),
        meta: { title: '账号与组织', requiresAuth: true, icon: 'User' }
      },
      {
        path: 'employees/:id',
        name: 'employeeDetail',
        component: () => import('../views/employee/EmployeeDetail.vue'),
        meta: { title: '人员详情', requiresAuth: true, parent: '人员管理', parentPath: '/employees' }
      },
      {
        path: 'employees/edit/:id',
        name: 'employeeEdit',
        component: () => import('../views/employee/EmployeeForm.vue'),
        meta: { title: '编辑人员', requiresAuth: true, supervisorOnly: true, parent: '人员管理', parentPath: '/employees' }
      },
      {
        path: 'models',
        name: 'models',
        component: () => import('../views/ModelList.vue'),
        meta: { title: '模型管理', employeeTitle: '检测模型目录', requiresAuth: true, icon: 'Tickets' }
      },
      {
        path: 'models/upload',
        name: 'modelUpload',
        component: () => import('../views/ModelUpload.vue'),
        meta: { title: '上传模型', requiresAuth: true, supervisorOnly:true, parent: '模型管理', parentPath: '/models' }
      },
      {
        path: 'device-records',
        name: 'deviceRecords',
        component: () => import('../views/device/DeviceUsageRecordList.vue'),
        meta: { title: '设备使用记录', requiresAuth: true, icon: 'DocumentCopy' }
      },
      {
        path: 'agent/chat',
        name: 'agentChat',
        component: () => import('../views/AgentChat.vue'),
        meta: { title: '智能对话助手', requiresAuth: true, icon: 'Operation' }
      },
      {
        path: 'agent/trace',
        name: 'agentTrace',
        component: () => import('../views/AgentTrace.vue'),
        meta: { title: 'Agent执行追溯', requiresAuth: true, icon: 'Operation' }
      },
      {
        path: 'agent/actions',
        name: 'agentActions',
        component: () => import('../views/AgentActions.vue'),
        meta: { title: '助手操作确认', requiresAuth: true, icon: 'Operation' }
      },
      {
        path: 'agent/skills', name: 'agentSkills', component: () => import('../views/AgentSkills.vue'),
        meta: { title: 'Agent技能演化', requiresAuth: true, icon: 'Operation' }
      },
      {
        path: 'agent/markets', name: 'agentMarkets', component: () => import('../views/AgentMarkets.vue'),
        meta: { title: '资源市场', requiresAuth: true, icon: 'Operation' }
      },
      {path:'quality/digests',name:'qualityDigests',component:()=>import('../views/QualityDigests.vue'),meta:{title:'质检日报',requiresAuth:true,supervisorOnly:true,requiresCapability:'qualityDigests'}},
      {path:'agent/model-quotas',name:'agentLlmManagement',component:()=>import('../views/AgentLlmManagement.vue'),meta:{title:'LLM模型管理',requiresAuth:true}},
      {path:'agent/model-budgets',name:'agentModelBudgets',component:()=>import('../views/AgentModelBudgets.vue'),meta:{title:'企业模型额度',requiresAuth:true,supervisorOnly:true}},
      {path:'agent/model-config',name:'agentModelConfig',component:()=>import('../views/AgentModelConfig.vue'),meta:{title:'Agent 模型配置',requiresAuth:true,supervisorOnly:true,requiresCapability:'agentModelConfig'}},
      {path:'operations/identity',name:'detectionIdentity',component:()=>import('../views/DetectionIdentity.vue'),meta:{title:'任务账号关联',requiresAuth:true,supervisorOnly:true,requiresCapability:'detectionIdentity'}},
      {path:'operations/audit',name:'operationsAudit',component:()=>import('../views/OperationsAudit.vue'),meta:{title:'操作审计',requiresAuth:true}},
      {path:'agent/memory',name:'agentMemory',component:()=>import('../views/AgentMemory.vue'),meta:{title:'个人记忆',requiresAuth:true}},
      { path:'agent/mcp',name:'agentMcp',component:()=>import('../views/AgentMcp.vue'),meta:{title:'MCP 工具',requiresAuth:true,icon:'Operation'} },
      {
        path: 'test-upload',
        name: 'testUpload',
        component: () => import('../views/TestUpload.vue'),
        meta: { title: '兼容上传诊断', requiresAuth: true, hidden: true }
      },
      {
        path: '/:pathMatch(.*)*',
        name: 'notFound',
        component: () => import('../views/NotFound.vue'),
        meta: { title: '页面未找到', hidden: true }
      }
    ]
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/Login.vue'),
    meta: { title: '登录', requiresAuth: false }
  }
]

const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes
})

const detectionTabTitles = {
  workspace: '单图检测与对比',
  history: '检测记录',
  'work-order-trace': '工单追溯',
  'batch-trace': '批次追溯'
}

// 页面加载进度条
let progressTimer = null
let progressFadeTimer = null
let progressResetTimer = null
function clearProgressTimers() {
  clearInterval(progressTimer)
  clearTimeout(progressFadeTimer)
  clearTimeout(progressResetTimer)
}
function startProgress() {
  clearProgressTimers()
  const bar = document.getElementById('nprogress-bar')
  if (!bar) return
  bar.style.width = '0%'
  bar.style.opacity = '1'
  let width = 0
  progressTimer = setInterval(() => {
    if (width >= 70) { clearInterval(progressTimer); return }
    width += (70 - width) * 0.15 + 2
    bar.style.width = `${Math.min(width, 70)}%`
  }, 120)
}
function finishProgress() {
  clearProgressTimers()
  const bar = document.getElementById('nprogress-bar')
  if (!bar) return
  bar.style.width = '100%'
  progressFadeTimer = setTimeout(() => { bar.style.opacity = '0' }, 200)
  progressResetTimer = setTimeout(() => { bar.style.width = '0%' }, 400)
}

router.beforeEach(async (to, from, next) => {
  const userStore = useUserStore()
  const detectionTitle = to.path === '/detection' ? detectionTabTitles[String(to.query.tab || 'workspace')] : ''

  if (to.meta.requiresAuth && !userStore.isAuthenticated) {
    const authenticated = userStore.hasCheckedAuth ? false : await userStore.checkAuth()
    if (!authenticated) {
      next({ name: 'login', query: { redirect: to.fullPath } })
      return
    }
  }

  const supervisor = ['SUPERVISOR','ADMIN'].includes(userStore.role)
  document.title = systemPageTitle(detectionTitle || (!supervisor && to.meta.employeeTitle) || to.meta.title)
  const tab = to.query.tab || to.meta.detectionTab
  if (to.name === 'legacyQualityQueue' || (to.path === '/detection' && tab === 'quality')) {
    const query = supervisor ? {} : { inbox: '1', kind: 'verification' }
    if (typeof to.query.keyword === 'string') query.keyword = to.query.keyword
    next({ name: supervisor ? 'supervisorVerificationTasks' : 'folderTaskBoard', query, replace: true })
    return
  }
  const taskId = to.query.taskId
  if (to.meta.detectionTab && tab === 'workspace' && typeof taskId === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(taskId)) {
    const action = ['images', 'review', 'assign'].includes(to.query.boardAction) ? to.query.boardAction : 'trace'
    next({ path: action === 'images' ? '/inspection/uploads/all' : '/inspection/tasks',
      query: { keyword: taskId, taskId, boardAction: action }, replace: true })
    return
  }
  if (to.meta.supervisorOnly && !supervisor) {
    next({name:'home'})
    return
  }
  if (from.name) startProgress()
  next()
})

router.afterEach((to, from, failure) => {
  finishProgress()
  if (!failure) clearNavigationFailure()
  if (failure && from.meta?.title) document.title = systemPageTitle(from.meta.title)
})

router.onError((error, to, from) => {
  finishProgress()
  if (from?.meta?.title) document.title = systemPageTitle(from.meta.title)
  recordNavigationFailure(to, error)
})

export default router
