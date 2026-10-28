import { createRouter, createWebHashHistory } from 'vue-router'
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
        path: 'inspection/workbench',
        name: 'inspectionWorkbench',
        component: () => import('../views/ImageDetection.vue'),
        meta: { title: '检测工作台', requiresAuth: true, detectionTab: 'workspace' }
      },
      {
        path: 'inspection/history',
        name: 'inspectionHistory',
        component: () => import('../views/ImageDetection.vue'),
        meta: { title: '检测记录', requiresAuth: true, detectionTab: 'history' }
      },
      {
        path: 'quality/queue',
        name: 'qualityQueue',
        component: () => import('../views/ImageDetection.vue'),
        meta: { title: '质检队列', requiresAuth: true, detectionTab: 'quality' }
      },
      {
        path: 'quality/reports',
        name: 'qualityReports',
        component: () => import('../views/QualityReports.vue'),
        meta: { title: '报告与审批', requiresAuth: true }
      },
      {
        path: 'quality/evidence',
        name: 'defectEvidence',
        component: () => import('../views/ImageDetection.vue'),
        meta: { title: '缺陷证据库', requiresAuth: true, detectionTab: 'defect-gallery' }
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
        meta: { title: '设备管理', requiresAuth: true, icon: 'Monitor' }
      },
      {
        path: 'devices/add',
        name: 'deviceAdd',
        component: () => import('../views/device/DeviceForm.vue'),
        meta: { title: '新增设备', requiresAuth: true, parent: '设备管理', parentPath: '/devices' }
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
        meta: { title: '编辑设备', requiresAuth: true, parent: '设备管理', parentPath: '/devices' }
      },
      {
        path: 'employees',
        name: 'employees',
        component: () => import('../views/employee/EmployeeList.vue'),
        meta: { title: '人员管理', requiresAuth: true, icon: 'User' }
      },
      {
        path: 'employees/add',
        name: 'employeeAdd',
        component: () => import('../views/employee/EmployeeForm.vue'),
        meta: { title: '新增人员', requiresAuth: true, parent: '人员管理', parentPath: '/employees' }
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
        meta: { title: '编辑人员', requiresAuth: true, parent: '人员管理', parentPath: '/employees' }
      },
      {
        path: 'models',
        name: 'models',
        component: () => import('../views/ModelList.vue'),
        meta: { title: '模型管理', requiresAuth: true, icon: 'Tickets' }
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
        path: 'manual',
        name: 'userManual',
        component: () => import('../views/UserManual.vue'),
        meta: { title: '用户使用手册', requiresAuth: true, icon: 'Files' }
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
      {path:'quality/knowledge',name:'qualityKnowledge',component:()=>import('../views/QualityKnowledge.vue'),meta:{title:'质检知识库',requiresAuth:true}},
      {path:'quality/digests',name:'qualityDigests',component:()=>import('../views/QualityDigests.vue'),meta:{title:'质检日报',requiresAuth:true,supervisorOnly:true}},
      {path:'agent/model-budgets',name:'agentModelBudgets',component:()=>import('../views/AgentModelBudgets.vue'),meta:{title:'模型额度',requiresAuth:true,supervisorOnly:true}},
      {path:'agent/model-config',name:'agentModelConfig',component:()=>import('../views/AgentModelConfig.vue'),meta:{title:'Agent 模型配置',requiresAuth:true,supervisorOnly:true}},
      {path:'operations/identity',name:'detectionIdentity',component:()=>import('../views/DetectionIdentity.vue'),meta:{title:'任务账号关联',requiresAuth:true,supervisorOnly:true}},
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
  workspace: '检测工作台',
  history: '检测记录',
  quality: '质检队列',
  'defect-gallery': '缺陷证据库',
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
  document.title = detectionTitle || to.meta.title || '集装箱门把手检测智能管理软件'

  if (to.meta.requiresAuth && !userStore.isAuthenticated) {
    const authenticated = userStore.hasCheckedAuth ? false : await userStore.checkAuth()
    if (!authenticated) {
      next({ name: 'login', query: { redirect: to.fullPath } })
      return
    }
  }

  if (to.meta.supervisorOnly && !['SUPERVISOR','ADMIN'].includes(userStore.role)) {
    next({name:'home'})
    return
  }
  if (from.name) startProgress()
  next()
})

router.afterEach((to, from, failure) => {
  finishProgress()
  if (!failure) clearNavigationFailure()
  if (failure && from.meta?.title) document.title = from.meta.title
})

router.onError((error, to, from) => {
  finishProgress()
  if (from?.meta?.title) document.title = from.meta.title
  recordNavigationFailure(to)
})

export default router
