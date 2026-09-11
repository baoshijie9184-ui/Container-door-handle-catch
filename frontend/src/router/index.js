import { createRouter, createWebHashHistory } from 'vue-router'
import { useUserStore } from '../stores/user'

const routes = [
  {
    path: '/',
    component: () => import('../layout/index.vue'),
    redirect: '/home',
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
        meta: { title: '新增设备', requiresAuth: true, parent: '设备管理' }
      },
      {
        path: 'devices/:id',
        name: 'deviceDetail',
        component: () => import('../views/device/DeviceDetail.vue'),
        meta: { title: '设备详情', requiresAuth: true, parent: '设备管理' }
      },
      {
        path: 'devices/edit/:id',
        name: 'deviceEdit',
        component: () => import('../views/device/DeviceForm.vue'),
        meta: { title: '编辑设备', requiresAuth: true, parent: '设备管理' }
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
        meta: { title: '新增人员', requiresAuth: true, parent: '人员管理' }
      },
      {
        path: 'employees/:id',
        name: 'employeeDetail',
        component: () => import('../views/employee/EmployeeDetail.vue'),
        meta: { title: '人员详情', requiresAuth: true, parent: '人员管理' }
      },
      {
        path: 'employees/edit/:id',
        name: 'employeeEdit',
        component: () => import('../views/employee/EmployeeForm.vue'),
        meta: { title: '编辑人员', requiresAuth: true, parent: '人员管理' }
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
        meta: { title: '上传模型', requiresAuth: true, parent: '模型管理' }
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
        path: 'test-upload',
        name: 'testUpload',
        component: () => import('../views/TestUpload.vue'),
        meta: { title: '测试上传', requiresAuth: true, hidden: true }
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
function startProgress() {
  const bar = document.getElementById('nprogress-bar')
  if (!bar) return
  bar.style.width = '0%'
  bar.style.opacity = '1'
  let width = 0
  clearInterval(progressTimer)
  progressTimer = setInterval(() => {
    if (width >= 70) { clearInterval(progressTimer); return }
    width += (70 - width) * 0.15 + 2
    bar.style.width = `${Math.min(width, 70)}%`
  }, 120)
}
function finishProgress() {
  clearInterval(progressTimer)
  const bar = document.getElementById('nprogress-bar')
  if (!bar) return
  bar.style.width = '100%'
  setTimeout(() => { bar.style.opacity = '0' }, 200)
  setTimeout(() => { bar.style.width = '0%' }, 500)
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

  if (to.name === 'login' && userStore.isAuthenticated) {
    next({ name: 'home' })
    return
  }

  if (from.name) startProgress()
  next()
})

router.afterEach(() => {
  finishProgress()
})

export default router
