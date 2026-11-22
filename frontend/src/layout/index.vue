<template>
  <div class="layout-shell" :class="{ 'sidebar-collapsed': collapsed, 'is-agent-section': isAgentSection, 'is-agent-workspace': isAgentChatRoute, 'is-trace-workspace': route.path === '/agent/trace' }">
    <button class="skip-link" type="button" @click="skipToMainContent">跳到主要内容</button>
    <nav v-if="isAgentSection" class="agent-app-rail" aria-label="Agent 导航">
      <router-link to="/home" class="agent-rail-brand" aria-label="返回业务系统" title="返回业务系统"><el-icon><HomeFilled /></el-icon></router-link>
      <button type="button" class="rail-find" aria-label="查找功能" title="查找功能" @click="finder.open()"><AppIcon name="Search" /><span>查找功能</span></button>
      <div class="agent-rail-links">
        <router-link v-for="item in agentNavigation" :key="item.path" :to="item.path" class="agent-rail-link"
          :class="{ selected: route.path === item.path }" :aria-current="route.path === item.path ? 'page' : undefined"
          :aria-label="item.label" :title="item.label">
          <AppIcon :name="item.icon" /><span class="rail-item-name">{{ item.label }}</span>
        </router-link>
        <el-dropdown trigger="click" placement="right-start" popper-class="agent-more-menu" @command="openAgentManagement">
          <button type="button" class="agent-rail-link agent-more-button" :class="{ selected: agentManagementActive }"
            aria-label="更多助手功能" title="更多助手功能">
            <AppIcon name="MoreFilled" /><span class="rail-item-name">更多</span>
          </button>
          <template #dropdown>
            <el-dropdown-menu aria-label="助手管理">
              <el-dropdown-item v-for="item in agentManagement" :key="item.path" :command="item.path"
                :class="{ 'is-current': route.path === item.path }" :aria-current="route.path === item.path ? 'page' : undefined">
                <AppIcon :name="item.icon" :size="16" />{{ item.label }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <AppAccountMenu compact :username="userStore.username" :role="accountPresentation.role" :department="userStore.identity?.departmentName" :scope="accountPresentation.scope" @home="router.push('/home')" @logout="handleLogout" />
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
          <img src="/favicon.svg" width="36" height="36" alt="" />
        </button>
        <div v-show="!collapsed" class="brand-text" :title="SYSTEM_NAME" :aria-label="SYSTEM_NAME">
          <div class="brand-title">{{ SYSTEM_SHORT_NAME }}</div>
        </div>
      </div>

      <button type="button" class="sidebar-finder" aria-label="查找功能" title="查找功能" @click="finder.open()">
        <AppIcon name="Search" :size="17" /><span v-if="!collapsed">查找功能</span><kbd v-if="!collapsed">{{ finderShortcut }}</kbd>
      </button>
      <WorkspaceNavigation :groups="sidebarNavGroups" home-group="inspection" :active="activeMenu" :collapsed="collapsed" />

      <ChatAssistantLauncher v-if="!isMobile" :compact="collapsed" @open="handleOpenAssistant" />
    </aside>

    <el-drawer v-model="mobileNavVisible" title="工作空间导航" direction="ltr" size="min(310px, 88vw)" class="mobile-system-navigation">
      <div class="mobile-nav-scope"><AppIcon name="User" />{{ accountPresentation.role }} · {{ accountPresentation.scope }}</div>
      <button type="button" class="sidebar-finder drawer-assistant" @click="mobileNavVisible=false;handleOpenAssistant()"><AppIcon name="ChatDotRound" />打开侧边助手</button>
      <WorkspaceNavigation id="mobile-system-menu" :groups="sidebarNavGroups" home-group="inspection" :active="activeMenu" :collapsed="false" @navigate="mobileNavVisible = false" />
    </el-drawer>

    <div class="layout-main">
      <header v-if="!isAgentChatRoute" class="layout-header">
        <div class="header-left">
          <button v-if="!isAgentSection"
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
          <button v-if="isMobile && !isAgentSection" type="button" class="mobile-find" aria-label="查找功能" @click="finder.open()"><AppIcon name="Search" /></button>
          <AppBreadcrumbs v-if="breadcrumbs.length" :items="breadcrumbs" />
          <div v-else>
            <div class="header-caption">工业视觉检测平台</div>
            <span class="header-title">{{ currentPageTitle }}</span>
          </div>
        </div>

        <RealtimeStatus />
        <div class="header-actions">
          <BeijingClock />
          <span class="workspace-scope"><AppIcon name="User" :size="14" />{{ accountPresentation.scope }}</span>
          <router-link v-if="!isAgentSection" to="/agent/chat" class="assistant-entry-link" aria-label="AI 工作助手">
            <el-icon aria-hidden="true"><ChatDotRound /></el-icon><span>AI 工作助手</span>
          </router-link>
          <AppAccountMenu :username="userStore.username" :role="accountPresentation.role" :department="userStore.identity?.departmentName" :scope="accountPresentation.scope" @home="router.push('/home')" @logout="handleLogout" />
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

    <WorkspaceFinder ref="finder" :groups="visibleNavGroups" :role="userStore.role" />
    <ChatAssistantDrawer v-if="!isAgentChatRoute" />
  </div>
</template>

<script setup>
import BeijingClock from '@/components/BeijingClock.vue'
import RealtimeStatus from '../components/RealtimeStatus.vue'
import {SYSTEM_NAME,SYSTEM_SHORT_NAME} from '@/utils/systemBrand'
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useUserStore } from '@/stores/user'
import { useRouter, useRoute } from 'vue-router'
import { useChatAssistantStore } from '@/stores/chatAssistant'
import '@/assets/agent-section.css'
import '@/assets/agent-unified.css'
import ChatAssistantDrawer from '@/components/chat/ChatAssistantDrawer.vue'
import ChatAssistantLauncher from '@/components/chat/ChatAssistantLauncher.vue'
import WorkspaceFinder from '@/components/WorkspaceFinder.vue'
import WorkspaceNavigation from '@/components/WorkspaceNavigation.vue'
import AppAccountMenu from '@/components/AppAccountMenu.vue'
import AppBreadcrumbs from '@/components/AppBreadcrumbs.vue'
import {
  HomeFilled,
  Tickets,
  Picture,
  Search,
  ChatDotRound,
  Operation
} from '@element-plus/icons-vue'

const finder = ref(null)
const finderShortcut = /Mac|iPad|iPhone/.test(navigator.platform) ? '⌘ K' : 'Ctrl K'
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
// Each business destination starts with its title, actions and search controls.
watch(() => route.path, () => {
  document.getElementById('main-content')?.scrollTo({top:0,left:0,behavior:'instant'})
}, {flush:'post'})
const showBackTop = ref(false)
const isAgentChatRoute = computed(() => route.path === '/agent/chat')
const isAgentSection = computed(() => route.path.startsWith('/agent/'))

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
      { path: '/upload', label: '上传图片', desc: '批量上传原图' },
      { path: '/inspection/uploads/mine', label: '我的上传记录', desc: '查看本人上传的图片批次' },
      { path: '/inspection/uploads/all', label: '全部上传记录', desc: '按员工工号查找上传记录' },
      { path: '/inspection/tasks', label: '我的任务', desc: '受派检测和人工校验', inspectorOnly: true },
      { path: '/inspection/uploads/dispatch', label: '待派检测', desc: '选择文件夹派发检测任务', supervisorOnly: true },
      { path: '/inspection/tasks/detection', label: '检测任务列表', desc: '检测派单与模型进度', supervisorOnly: true },
      { path: '/inspection/tasks/verification', label: '校验任务列表', desc: '分派校验与核对检测结果', supervisorOnly: true },
      { path: '/inspection/history', label: '检测记录', desc: '历史结果与报告' },
      { path: '/inspection/workbench', label: '单图检测与对比', desc: '单张图片与双模型对比' }
    ]
  },
  {
    key: 'quality',
    label: '质检追溯',
    icon: Search,
    items: [
      { path: '/quality/reports', label: '报告与审批', desc: '个人草稿与主管审批' },
      { path: '/quality/digests', label: '质检日报', desc: '定时统计与报告交付', supervisorOnly:true },
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
      { path: '/organization', label: '账号与组织', desc: '个人身份与账号关联' },
      { path: '/operations/identity', label: '任务账号关联', desc: '历史身份核对与迁移', supervisorOnly:true },
      { path: '/operations/audit', label: '操作审计', desc: '业务变更与交付记录' }
    ]
  },
  {
    key: 'agent',
    label: '智能助手',
    icon: Operation,
    items: [
      { path: '/agent/chat', label: '对话', icon: 'ChatDotRound', desc: '与智能助手对话' },
      { path: '/agent/actions', label: '待确认', icon: 'CircleCheck', desc: '处理助手操作确认' },
      { path: '/agent/skills', label: '技能管理', icon: 'Collection', advanced: true, desc: '经验提炼、安装与审核发布' },
      { path: '/agent/mcp', label: 'MCP 工具', icon: 'Connection', advanced: true, desc: '安装和管理本人 Fetch 工具' },
      { path: '/agent/memory', label: '个人记忆', icon: 'User', advanced: true, desc: '本人记忆与保存设置' },
      { path: '/agent/model-quotas', label: '模型与额度', icon: 'Cpu', advanced: true, desc: '可用模型、个人额度与申请审批' },
      { path: '/agent/trace', label: '执行追溯', icon: 'DataAnalysis', advanced: true, desc: '查看调用过程与关联结果' },
      { path: '/agent/markets', label: '资源市场', icon: 'Compass', advanced: true, desc: '发现 Agent、MCP 与 Skill' },
      { path: '/agent/model-budgets', label: '企业额度', icon: 'Tickets', advanced: true, desc: '企业用量与供应商核对', supervisorOnly:true },
      { path: '/agent/model-config', label: '模型配置', icon: 'Setting', advanced: true, desc: '版本策略与连接凭证', supervisorOnly:true }
    ]
  }
]

const visibleNavGroups = computed(()=>{
  const supervisor=['SUPERVISOR','ADMIN'].includes(userStore.role)
  return navGroups.map(group=>({...group,items:group.items.filter(item=>supervisor ? !item.inspectorOnly : !item.supervisorOnly)})).filter(group=>group.items.length)
})
const sidebarNavGroups = computed(() => visibleNavGroups.value.map(group => group.key === 'agent'
  ? { ...group, items: group.items.filter(item => !item.advanced) }
  : group))
const agentItems = computed(() => visibleNavGroups.value.find(group => group.key === 'agent')?.items || [])
const agentNavigation = computed(() => agentItems.value.filter(item => !item.advanced))
const agentManagement = computed(() => agentItems.value.filter(item => item.advanced))
const agentManagementActive = computed(() => agentManagement.value.some(item => item.path === route.path))
function openAgentManagement(path) {
  if (agentManagement.value.some(item => item.path === path)) router.push(path)
}
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
.layout-sidebar { display:flex; flex-direction:column; height:100%; min-height:0; padding:20px 12px 14px; overflow-y:auto; overflow-x:hidden; --nav-label:var(--app-text-secondary); --nav-muted:var(--app-text-muted); --nav-hover:var(--app-surface-muted);
  --nav-selected:var(--app-primary-soft); --nav-accent:var(--app-primary);
  background:white; border:0; border-right:1px solid var(--app-border); border-radius:0; box-shadow:none; }
.layout-sidebar::before { content:none; }
.brand-block { display:flex; align-items:center; gap:10px; min-height:40px; padding:0 7px; margin-bottom:16px; }
.brand-mark { display:grid; place-items:center; flex:0 0 36px; height:36px; padding:0; border:0; border-radius:9px; color:white; background:transparent; cursor:pointer; }
.brand-mark:hover { box-shadow:0 0 0 2px var(--nav-accent); }
.brand-mark:focus-visible { outline:2px solid var(--nav-accent); }
.brand-text { min-width:0; overflow:hidden; white-space:nowrap; }
.brand-title { font-size:15px; font-weight:650; letter-spacing:-.02em; color:var(--app-text); }
.sidebar-collapsed .brand-block { justify-content:center; padding:0; }
.sidebar-collapsed .layout-sidebar { padding-inline:7px; }
.layout-main { display:flex; flex-direction:column; position:relative; min-width:0; min-height:0; overflow:hidden; }
.layout-header { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,auto) auto; align-items:center; flex:0 0 auto; min-height:62px; padding:8px var(--app-page-gutter); gap:16px; background:var(--app-surface); border-bottom:1px solid var(--app-border); }
.header-left,.header-actions { display:flex; align-items:center; gap:14px; min-width:0; }
.layout-header > .collaboration-status { max-width:28em; }
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
@media(max-width:1100px) { .workspace-scope { display:none; } .header-actions { gap:8px; } }
@media (min-width:641px) and (max-width:960px) {
  .layout-header { grid-template-columns:minmax(0,1fr) auto; gap:3px 12px; }
  .layout-header > .collaboration-status { grid-column:1/-1; grid-row:2; max-width:none; }
  .layout-header > .header-actions { grid-column:2; grid-row:1; }
}
@media (max-width: 640px) {
  .layout-shell,.layout-shell.sidebar-collapsed { grid-template-columns:minmax(0,1fr); }
  .layout-sidebar { display:none; }
  .layout-header { grid-template-columns:minmax(0,1fr) auto; min-height:54px; padding:9px 14px; gap:6px 8px; }
  .header-left { grid-column:1; grid-row:1; gap:8px; }
  .header-actions { grid-column:2; grid-row:1; gap:4px; }
  .layout-header > .collaboration-status { grid-column:1/-1; grid-row:2; max-width:none; }
  .assistant-entry-link { padding:6px; width:30px; height:30px; justify-content:center; }
  .assistant-entry-link > span { display:none; }
  .layout-content { padding:22px 16px 78px; }
  .is-agent-workspace .layout-content,.is-trace-workspace .layout-content { padding:0; }
  .back-top-btn { bottom:78px; right:20px; }
}
@media(prefers-reduced-motion:reduce) { .layout-shell,.brand-mark { transition:none; } .brand-mark:hover { transform:none; } .layout-content { scroll-behavior:auto; } }
.sidebar-finder,.mobile-find,.rail-find {font:inherit;cursor:pointer;color:var(--app-text-secondary);border:1px solid var(--app-border);background:var(--app-surface-muted);border-radius:8px}
.sidebar-finder {display:flex;align-items:center;gap:10px;padding:9px 11px;margin:0 2px 14px;font-size:14px;text-align:left}
.sidebar-finder kbd {margin-left:auto;padding:1px 4px;border:1px solid var(--app-border);border-radius:4px;font:11px/1.5 system-ui;background:white}
.mobile-find,.rail-find {display:grid;place-items:center;min-width:32px;min-height:34px}
.rail-find {flex-shrink:0;padding:6px;gap:3px}
.rail-find span,.rail-item-name {display:none}
.sidebar-collapsed .sidebar-finder {justify-content:center;padding:9px 0}
:is(.rail-find,.sidebar-finder,.mobile-find):hover {color:var(--app-primary);border-color:var(--app-border-focus)}
:is(.rail-find,.sidebar-finder,.mobile-find):focus-visible {outline:2px solid var(--app-primary);outline-offset:2px}
@media(min-width:1050px) {
  #app .layout-shell.is-agent-section {grid-template-columns:124px minmax(0,1fr)}
  .agent-app-rail {align-items:stretch;gap:8px}
  .agent-app-rail .agent-rail-brand,.agent-app-rail :deep(.app-account-menu) {align-self:center}
  .agent-app-rail .agent-rail-brand {margin-bottom:6px}
  .rail-find,.agent-rail-link {display:flex;align-items:center;justify-content:flex-start;gap:7px;padding:8px;width:100%;min-height:38px;height:auto;border-radius:7px;box-sizing:border-box}
  .rail-find span,.rail-item-name {display:inline;font-size:13px;white-space:nowrap}
  .agent-rail-links {gap:3px}
}
</style>
