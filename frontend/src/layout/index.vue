<template>
  <div class="layout-shell" :class="{ 'sidebar-collapsed': collapsed, 'is-agent-section': isAgentSection, 'is-agent-workspace': isAgentChatRoute, 'is-trace-workspace': route.path === '/agent/trace' }">
    <button class="skip-link" type="button" @click="skipToMainContent">跳到主要内容</button>
    <nav v-if="isAgentSection" class="agent-app-rail" aria-label="Agent 导航">
      <router-link to="/home" class="agent-rail-brand" aria-label="返回业务系统" title="返回业务系统"><el-icon><HomeFilled /></el-icon></router-link>
      <div class="agent-rail-links">
        <el-tooltip v-for="item in agentNavigation" :key="item.path" :content="item.label" placement="right" :show-after="300">
          <router-link :to="item.path" class="agent-rail-link" :class="{ selected: route.path === item.path }" :aria-current="route.path === item.path ? 'page' : undefined" :aria-label="item.label"><el-icon><component :is="item.icon" /></el-icon></router-link>
        </el-tooltip>
      </div>
      <router-link to="/manual" class="agent-rail-link" aria-label="使用手册" title="使用手册"><el-icon><Files /></el-icon></router-link>
      <AppAccountMenu compact :username="userStore.username" :role="accountPresentation.role" :department="userStore.identity?.departmentName" :scope="accountPresentation.scope" @home="router.push('/home')" @manual="router.push('/manual')" @logout="handleLogout" />
    </nav>
    <aside v-else id="system-sidebar" class="layout-sidebar app-panel" aria-label="系统导航">
      <div class="brand-block">
        <button
          class="brand-mark"
          type="button"
          :aria-label="collapsed ? '展开菜单' : '收起菜单'"
          :title="collapsed ? '展开菜单' : '收起菜单'"
          :aria-expanded="isMobile ? mobileNavVisible : !collapsed"
          aria-controls="system-sidebar"
          @click="toggleNavigation"
        >
          DH
        </button>
        <div v-show="!collapsed" class="brand-text">
          <div class="brand-title">DoorHandle Catch</div>
          <div class="brand-subtitle">工业检测智能控制台</div>
        </div>
      </div>

      <div v-show="!collapsed" class="nav-section-label">业务导航</div>
      <WorkspaceNavigation :groups="visibleNavGroups" :active="activeMenu" :collapsed="collapsed" />

      <div v-show="!collapsed" class="sidebar-footer">
        <div class="footer-card">
          <div class="footer-card-label">当前工作空间</div>
          <div class="footer-card-title">{{ accountPresentation.workspace }}</div>
          <div class="footer-card-desc">{{ accountPresentation.description }}</div>
        </div>
      </div>
    </aside>

    <el-drawer v-model="mobileNavVisible" title="工作空间导航" direction="ltr" size="min(310px, 88vw)" class="mobile-system-navigation">
      <div class="mobile-nav-scope"><AppIcon name="User" />{{ accountPresentation.role }} · {{ accountPresentation.scope }}</div>
      <WorkspaceNavigation id="mobile-system-menu" :groups="visibleNavGroups" :active="activeMenu" :collapsed="false" @navigate="mobileNavVisible = false" />
    </el-drawer>

    <div class="layout-main">
      <header v-if="!isAgentChatRoute" class="layout-header">
        <div class="header-left">
          <button
            class="collapse-btn"
            type="button"
            @click="toggleNavigation"
            :title="isMobile ? '打开系统导航' : collapsed ? '展开菜单' : '收起菜单'"
            :aria-label="isMobile ? '打开系统导航' : collapsed ? '展开菜单' : '收起菜单'"
            :aria-expanded="isMobile ? mobileNavVisible : !collapsed"
            :aria-controls="isMobile ? 'mobile-system-menu' : 'system-sidebar'"
          >
            <AppIcon :name="isMobile ? 'Menu' : collapsed ? 'Expand' : 'Fold'" :size="20" />
          </button>
          <AppBreadcrumbs v-if="breadcrumbs.length" :items="breadcrumbs" />
          <div v-else>
            <div class="header-caption">工业视觉检测平台</div>
            <span class="header-title">{{ currentPageTitle }}</span>
          </div>
        </div>

        <div class="header-actions">
          <span class="workspace-scope"><AppIcon name="User" :size="14" />{{ accountPresentation.scope }}</span>
          <router-link to="/manual" class="manual-entry-link">
            <el-icon aria-hidden="true"><Files /></el-icon>使用手册
          </router-link>
          <router-link v-if="!isAgentChatRoute" to="/agent/chat" class="assistant-entry-link" aria-label="AI 工作助手">
            <el-icon aria-hidden="true"><ChatDotRound /></el-icon><span>AI 工作助手</span>
          </router-link>
          <AppAccountMenu :username="userStore.username" :role="accountPresentation.role" :department="userStore.identity?.departmentName" :scope="accountPresentation.scope" @home="router.push('/home')" @manual="router.push('/manual')" @logout="handleLogout" />
        </div>
      </header>

      <main id="main-content" class="layout-content" tabindex="-1">
        <router-view v-slot="{ Component }">
          <transition name="page-slide" mode="out-in">
            <component :is="Component" :key="route.params.id || undefined" />
          </transition>
        </router-view>
      </main>

      <!-- 回到顶部按钮 -->
      <button v-show="showBackTop" class="back-top-btn" type="button" @click="scrollToTop" title="回到顶部" aria-label="回到顶部">
        <AppIcon name="ArrowUp" :size="19" />
      </button>
    </div>

    <ChatAssistantLauncher v-if="!isAgentSection" @open="handleOpenAssistant" />
    <ChatAssistantDrawer v-if="!isAgentChatRoute" />
  </div>
</template>

<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useUserStore } from '@/stores/user'
import { useRouter, useRoute } from 'vue-router'
import { useChatAssistantStore } from '@/stores/chatAssistant'
import '@/assets/agent-section.css'
import '@/assets/agent-unified.css'
import ChatAssistantDrawer from '@/components/chat/ChatAssistantDrawer.vue'
import ChatAssistantLauncher from '@/components/chat/ChatAssistantLauncher.vue'
import WorkspaceNavigation from '@/components/WorkspaceNavigation.vue'
import AppAccountMenu from '@/components/AppAccountMenu.vue'
import AppBreadcrumbs from '@/components/AppBreadcrumbs.vue'
import {
  HomeFilled,
  Tickets,
  Picture,
  Monitor,
  User,
  DocumentCopy,
  Upload,
  DataAnalysis,
  Search,
  Files,
  ChatDotRound,
  Operation
} from '@element-plus/icons-vue'

const userStore = useUserStore()
const chatAssistantStore = useChatAssistantStore()
const router = useRouter()
const route = useRoute()

const navigationSize = () => window.innerWidth <= 640 ? 'MOBILE' : window.innerWidth <= 1024 ? 'COMPACT' : 'DESKTOP'
const navigationRange = ref(navigationSize())
const collapsed = ref(navigationRange.value === 'COMPACT')
const isMobile = computed(() => navigationRange.value === 'MOBILE')
const mobileNavVisible = ref(false)
const updateNavigationWidth = () => {
  const next = navigationSize()
  if (next === navigationRange.value) return
  navigationRange.value = next
  if (next !== 'MOBILE') collapsed.value = next === 'COMPACT'
  mobileNavVisible.value = false
}
const toggleNavigation = () => {
  if (isMobile.value) mobileNavVisible.value = !mobileNavVisible.value
  else collapsed.value = !collapsed.value
}
watch(() => route.fullPath, () => { mobileNavVisible.value = false })
const showBackTop = ref(false)
const isAgentChatRoute = computed(() => route.path === '/agent/chat')
const isAgentSection = computed(() => route.path.startsWith('/agent/'))
const agentNavigation = computed(() => [
  { path:'/agent/chat', label:'智能对话', icon:ChatDotRound },
  { path:'/agent/trace', label:'执行追溯', icon:DataAnalysis },
  { path:'/agent/actions', label:'操作确认', icon:Tickets },
  { path:'/agent/skills', label:'技能管理', icon:DocumentCopy },
  { path:'/agent/markets', label:'资源市场', icon:Search },
  { path:'/agent/memory', label:'个人记忆', icon:User },
  { path:'/agent/mcp', label:'MCP 工具', icon:Monitor },
  ...(['SUPERVISOR','ADMIN'].includes(userStore.role) ? [{ path:'/agent/model-budgets', label:'模型额度', icon:DataAnalysis }] : []),
  ...(userStore.role === 'SUPERVISOR' ? [{ path:'/agent/model-config', label:'模型配置', icon:Operation }] : [])
])

const navGroups = [
  {
    key: 'overview',
    label: '运营总览',
    icon: HomeFilled,
    desc: '全局态势',
    items: [
      { path: '/home', label: '首页总览', desc: '平台运行态势' }
    ]
  },
  {
    key: 'inspection',
    label: '检测业务',
    icon: Picture,
    items: [
      { path: '/upload', label: '图像采集上传', desc: '原图入库与任务创建' },
      { path: '/inspection/workbench', label: '检测工作台', desc: '模型推理与任务执行' },
      { path: '/inspection/history', label: '检测记录', desc: '历史结果与报告' }
    ]
  },
  {
    key: 'quality',
    label: '质检追溯',
    icon: Search,
    items: [
      { path: '/quality/queue', label: '质检队列', desc: '待复核与处置闭环' },
      { path: '/quality/reports', label: '报告与审批', desc: '个人草稿与主管审批' },
      { path: '/quality/knowledge', label: '质检知识库', desc: '规范、版本与引用定位' },
      { path: '/quality/digests', label: '质检日报', desc: '定时统计与报告交付', supervisorOnly:true },
      { path: '/quality/evidence', label: '缺陷证据库', desc: '缺陷图片证据链' },
      { path: '/quality/work-order-trace', label: '工单追溯', desc: '按工单回溯检测链路' },
      { path: '/quality/batch-trace', label: '批次追溯', desc: '按批次追溯质量结果' }
    ]
  },
  {
    key: 'model',
    label: '模型中心',
    icon: Tickets,
    items: [
      { path: '/models', label: '模型管理', desc: '版本、发布、校验' },
      { path: '/models/upload', label: '上传模型', desc: '导入新模型版本', supervisorOnly:true }
    ]
  },
  {
    key: 'resources',
    label: '产线资源',
    icon: Operation,
    items: [
      { path: '/devices', label: '设备管理', desc: '采集与检测设备' },
      { path: '/device-records', label: '设备使用记录', desc: '设备调用与维护记录' },
      { path: '/employees', label: '人员管理', desc: '采集、检测、维修人员' },
      { path: '/organization', label: '账号与组织', desc: '个人身份与账号关联' }
    ]
  },
  {
    key: 'agent',
    label: 'Agent智能系统',
    icon: Operation,
    items: [
      { path: '/agent/chat', label: '智能对话助手', desc: '完整页面对话工作区' },
      { path: '/agent/model-config', label: 'Agent 模型配置', desc: '版本策略与连接凭证', supervisorOnly:true },
      { path: '/agent/model-budgets', label: '模型额度', desc: '每模型用量与供应商核对', supervisorOnly:true },
      { path: '/operations/identity', label: '任务账号关联', desc: '历史身份核对与迁移', supervisorOnly:true },
      { path: '/operations/audit', label: '操作审计', desc: '业务变更与交付记录' },
      { path: '/agent/trace', label: 'Agent执行追溯', desc: '查看调用过程与关联结果' },
      { path: '/agent/actions', label: '助手操作确认', desc: '核对分配提议与审计' },
      { path: '/agent/skills', label: 'Agent技能演化', desc: '经验提炼与审核发布' },
      { path: '/agent/markets', label: '资源市场', desc: '发现 Agent、MCP 与 Skill' },
      { path: '/agent/memory', label: '个人记忆', desc: '本人记忆与保存设置' },
      { path: '/agent/mcp', label: 'MCP工具', desc: '本人本地 Stdio 服务' }
    ]
  },
  {
    key: 'help',
    label: '帮助中心',
    icon: Files,
    desc: '快速了解系统用法',
    items: [
      { path: '/manual', label: '用户使用手册', desc: '模块说明与操作流程' }
    ]
  }
]

const visibleNavGroups = computed(()=>navGroups.map(group=>({...group,items:group.items.filter(item=>!item.supervisorOnly || ['SUPERVISOR','ADMIN'].includes(userStore.role))})).filter(group=>group.items.length))
const menuTitleMap = navGroups
  .flatMap(group => group.items.map(item => [item.path, { ...item, group: group.label }]))
  .reduce((map, [path, item]) => {
    map[path] = item
    return map
  }, {})

const activeMenu = computed(() => {
  const path = route.path
  const tab = route.query.tab ? String(route.query.tab) : ''
  if (path === '/detection' && tab) {
    const legacyMap = {
      workspace: '/inspection/workbench',
      history: '/inspection/history',
      quality: '/quality/queue',
      'defect-gallery': '/quality/evidence',
      'work-order-trace': '/quality/work-order-trace',
      'batch-trace': '/quality/batch-trace'
    }
    return legacyMap[tab] || '/inspection/workbench'
  }
  if (path === '/detection') return '/inspection/workbench'
  if (path.startsWith('/inspection/')) return path
  if (path.startsWith('/quality/')) return path
  if (path === '/device-records') return '/device-records'
  if (path.startsWith('/devices')) return '/devices'
  if (path.startsWith('/employees')) return '/employees'
  if (path === '/models/upload') return '/models/upload'
  if (path.startsWith('/models')) return '/models'
  return path
})

const currentNavItem = computed(() => menuTitleMap[activeMenu.value])
const currentPageTitle = computed(() => (route.meta.parent ? route.meta.title : currentNavItem.value?.label) || route.meta.title || '数据总览')
const accountPresentation = computed(() => {
  if(userStore.role==='SUPERVISOR')return {role:'企业主管',scope:'企业业务',workspace:'企业质量工作空间',description:'查看企业任务，安排复核与处置'}
  if(['INSPECTOR','OPERATOR'].includes(userStore.role))return {role:userStore.role==='INSPECTOR'?'检测员工':'业务员工',scope:'本人及分派任务',workspace:'我的检测工作空间',description:'查看本人及分派任务，跟进检测结果'}
  return {role:userStore.role==='ADMIN'?'管理员':'角色尚未确认',scope:'按账号授权范围',workspace:'当前账号工作空间',description:'资料范围和可用操作以当前账号授权为准'}
})

// 面包屑导航
const breadcrumbs = computed(() => {
  const crumbs = [{ label: '首页', path: '/home' }]
  const meta = route.meta
  if (route.path === '/home') return []
  if (meta.parent) {
    const parent=menuTitleMap[meta.parentPath] || Object.values(menuTitleMap).find(item=>item.label===meta.parent)
    if(parent?.group)crumbs.push({label:parent.group})
    crumbs.push({label:meta.parent,path:parent?.supervisorOnly&&userStore.role!=='SUPERVISOR'?undefined:meta.parentPath||parent?.path})
    if(meta.title&&meta.title!==meta.parent)crumbs.push({label:meta.title})
    return crumbs
  }
  if (currentNavItem.value) {
    crumbs.push({ label: currentNavItem.value.group })
    crumbs.push({ label: currentNavItem.value.label })
    return crumbs
  }
  if (meta.title && meta.title !== meta.parent) {
    crumbs.push({ label: meta.title })
  }
  return crumbs.length > 1 ? crumbs : []
})

const handleLogout = () => {
  userStore.logout()
  router.push('/login')
}

const handleOpenAssistant = () => {
  chatAssistantStore.open()
}

// 回到顶部
function handleScroll() {
  const main = document.querySelector('.layout-content')
  if (main) {
    showBackTop.value = main.scrollTop > 300
  }
}

function scrollToTop() {
  const main = document.querySelector('.layout-content')
  if (main) {
    main.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
  }
}

function skipToMainContent() {
  const main = document.querySelector('.layout-content')
  const mainContent = document.getElementById('main-content')
  if (!main || !mainContent) return
  mainContent.focus({ preventScroll: true })
  main.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
}

onMounted(() => {
  window.addEventListener('resize', updateNavigationWidth)
  const main = document.querySelector('.layout-content')
  if (main) main.addEventListener('scroll', handleScroll, { passive: true })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateNavigationWidth)
  const main = document.querySelector('.layout-content')
  if (main) main.removeEventListener('scroll', handleScroll)
})
</script>

<style scoped>
.layout-shell { display:grid; grid-template-columns:232px minmax(0,1fr); height:100vh; height:100dvh; overflow:hidden; background:var(--app-bg); transition:grid-template-columns var(--app-transition-base); }
.layout-shell.sidebar-collapsed { grid-template-columns:68px minmax(0,1fr); }
.layout-sidebar { display:flex; flex-direction:column; height:100%; min-height:0; padding:20px 12px 14px; overflow-y:auto; overflow-x:hidden; background:var(--app-bg-alt); border:0; border-right:1px solid var(--app-border); border-radius:0; box-shadow:none; }
.layout-sidebar::before { content:none; }
.brand-block { display:flex; align-items:center; gap:10px; min-height:40px; padding:0 7px; margin-bottom:30px; }
.brand-mark { display:grid; place-items:center; flex:0 0 32px; height:32px; padding:0; border:1px solid #181b2310; border-radius:9px; background:var(--app-text); color:white; font:700 13px var(--app-font); cursor:pointer; transition:transform var(--app-transition-fast),background var(--app-transition-fast); }
.brand-mark:hover { background:var(--app-primary); transform:scale(1.035); }
.brand-mark:active { transform:scale(.97); }
.brand-text { min-width:0; overflow:hidden; white-space:nowrap; }
.brand-title { font-size:14px; font-weight:650; letter-spacing:-.025em; color:var(--app-text); }
.brand-subtitle { margin-top:3px; font-size:11px; color:var(--app-text-muted); }
.nav-section-label { margin:0 12px 9px; color:var(--app-text-muted); font-size:11px; font-weight:500; }
.sidebar-footer { margin-top:auto; padding-top:26px; }
.footer-card { padding:14px 12px 4px; border-top:1px solid var(--app-border); }
.footer-card-label { margin-bottom:7px; font-size:11px; color:var(--app-text-muted); }
.footer-card-title { font-size:12px; font-weight:600; color:var(--app-text); }
.footer-card-desc { margin-top:5px; color:var(--app-text-muted); font-size:11px; line-height:1.7; }
.sidebar-collapsed .brand-block { justify-content:center; padding:0; }
.sidebar-collapsed .layout-sidebar { padding-inline:7px; }
.layout-main { display:flex; flex-direction:column; position:relative; min-width:0; min-height:0; overflow:hidden; }
.layout-header { display:flex; align-items:center; justify-content:space-between; flex:0 0 auto; min-height:58px; padding:8px var(--app-page-gutter); gap:16px; background:var(--app-surface); border-bottom:1px solid var(--app-border); }
.header-left,.header-actions { display:flex; align-items:center; gap:14px; min-width:0; }
.header-left { flex:1; }
.header-actions { flex:0 0 auto; }
.collapse-btn { display:grid; place-items:center; flex:0 0 30px; width:30px; height:30px; border:0; border-radius:6px; padding:0; color:var(--app-text-muted); background:transparent; cursor:pointer; }
.collapse-btn:hover { background:var(--app-surface-hover); color:var(--app-text); }
.header-caption { display:none; }
.header-title { margin:0; color:var(--app-text-secondary); font-size:13px; font-weight:500; }
.workspace-scope { display:inline-flex; align-items:center; gap:6px; padding-right:14px; border-right:1px solid var(--app-border); font-size:12px; color:var(--app-text-muted); white-space:nowrap; }
.assistant-entry-link { display:inline-flex; align-items:center; gap:7px; padding:6px 9px; border:1px solid var(--app-border); border-radius:6px; font-size:12px; font-weight:550; color:var(--app-text-secondary); background:white; white-space:nowrap; }
.assistant-entry-link:hover { color:var(--app-primary); background:var(--app-primary-soft); border-color:var(--app-border-focus); }
.layout-content { flex:1; min-width:0; min-height:0; padding:30px var(--app-page-gutter) 84px; overflow-y:auto; overscroll-behavior-y:contain; scroll-behavior:smooth; scrollbar-gutter:stable; }
.layout-content:focus { outline:none; }
.layout-content:focus-visible { outline:2px solid var(--app-primary); outline-offset:-2px; }
.is-agent-workspace .layout-content,.is-trace-workspace .layout-content { padding:0; overflow:hidden; }
.back-top-btn { display:grid; place-items:center; position:absolute; bottom:82px; right:24px; width:36px; height:36px; border:1px solid var(--app-border); border-radius:9px; background:white; color:var(--app-text-secondary); box-shadow:var(--app-shadow-sm); cursor:pointer; }
.back-top-btn:hover { background:var(--app-primary-soft); color:var(--app-primary); }
@media(max-width:1100px) { .workspace-scope { display:none; } .header-actions { gap:8px; } .manual-entry-link { display:none; } }
@media (max-width: 640px) {
  .layout-shell,.layout-shell.sidebar-collapsed { grid-template-columns:minmax(0,1fr); }
  .layout-sidebar { display:none; }
  .layout-header { min-height:54px; padding:9px 14px; gap:8px; }
  .header-left { gap:8px; } .header-actions { gap:4px; }
  .assistant-entry-link { padding:6px; width:30px; height:30px; justify-content:center; }
  .assistant-entry-link > span { display:none; }
  .layout-content { padding:22px 16px 78px; }
  .is-agent-workspace .layout-content,.is-trace-workspace .layout-content { padding:0; }
  .back-top-btn { bottom:78px; right:20px; }
}
@media(max-width:360px) { .assistant-entry-link { display:none; } }
@media(prefers-reduced-motion:reduce) { .layout-shell,.brand-mark { transition:none; } .brand-mark:hover { transform:none; } .layout-content { scroll-behavior:auto; } }
</style>
