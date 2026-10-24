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
      <el-dropdown trigger="click" placement="right-end">
        <button type="button" class="agent-rail-account" :aria-label="'账号菜单 '+userStore.username" :title="userStore.username">{{ userInitial }}</button>
        <template #dropdown><el-dropdown-menu><el-dropdown-item disabled>{{ userStore.username }}</el-dropdown-item><el-dropdown-item @click="router.push('/home')">返回业务系统</el-dropdown-item><el-dropdown-item divided @click="handleLogout">退出登录</el-dropdown-item></el-dropdown-menu></template>
      </el-dropdown>
    </nav>
    <aside v-else id="system-sidebar" class="layout-sidebar app-panel" aria-label="系统导航">
      <div class="brand-block">
        <button
          class="brand-mark"
          type="button"
          :aria-label="collapsed ? '展开菜单' : '收起菜单'"
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
          <nav v-if="breadcrumbs.length" class="breadcrumb-nav" aria-label="当前页面路径">
            <template v-for="(crumb, idx) in breadcrumbs" :key="idx">
              <span v-if="idx > 0" class="breadcrumb-sep" aria-hidden="true">/</span>
              <router-link
                v-if="crumb.path && idx < breadcrumbs.length - 1"
                :to="crumb.path"
                class="breadcrumb-link"
              >
                {{ crumb.label }}
              </router-link>
              <span v-else class="breadcrumb-current" :aria-current="idx===breadcrumbs.length-1 ? 'page' : undefined">{{ crumb.label }}</span>
            </template>
          </nav>
          <div v-else>
            <div class="header-caption">工业视觉检测平台</div>
            <h1 class="header-title">{{ currentPageTitle }}</h1>
          </div>
        </div>

        <div class="header-actions">
          <span class="workspace-scope"><AppIcon name="User" :size="14" />{{ accountPresentation.scope }}</span>
          <router-link to="/manual" class="manual-entry-link">
            <el-icon aria-hidden="true"><Files /></el-icon>使用手册
          </router-link>
          <router-link v-if="!isAgentChatRoute" to="/agent/chat" class="assistant-entry-link">
            <el-icon><ChatDotRound /></el-icon> AI 工作助手
          </router-link>
          <div class="user-box app-panel">
            <div class="user-avatar">{{ userInitial }}</div>
            <div class="user-meta">
              <div class="user-name">{{ userStore.username || '企业用户' }}</div>
              <div class="user-role" :title="accountPresentation.role+(userStore.identity?.departmentName ? ' · '+userStore.identity.departmentName : '')">{{ accountPresentation.role }}<template v-if="userStore.identity?.departmentName"> · {{ userStore.identity.departmentName }}</template></div>
            </div>
            <el-button type="danger" plain size="small" @click="handleLogout">退出登录</el-button>
          </div>
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

    <ChatAssistantLauncher v-if="!isAgentChatRoute && route.path !== '/agent/trace'" @open="handleOpenAssistant" />
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

const visibleNavGroups = computed(()=>navGroups.map(group=>({...group,items:group.items.filter(item=>!item.supervisorOnly || userStore.role==='SUPERVISOR')})).filter(group=>group.items.length))
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

const userInitial = computed(() => {
  const name = userStore.username || 'A'
  return name.slice(0, 1).toUpperCase()
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

<style lang="scss" scoped>
.layout-shell {
  display: grid;
  grid-template-columns: 244px minmax(0, 1fr);
  height: 100vh;
  height: 100dvh;
  padding: 0;
  gap: 0;
  overflow: hidden;
  transition: grid-template-columns var(--app-transition-base);
  background: var(--app-bg);
}

.layout-shell.sidebar-collapsed {
  grid-template-columns: 80px minmax(0, 1fr);
}
.layout-shell.sidebar-collapsed .brand-block { padding-inline: 0; justify-content: center; }
.layout-shell.sidebar-collapsed .layout-sidebar { padding-inline:8px; }

.layout-sidebar {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: 20px 14px;
  overflow-y: auto;
  overflow-x: hidden;
  background: #ffffff;
  border: 0;
  border-right: 1px solid var(--app-border);
  border-radius: 0;
  box-shadow: none;
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
  padding: 6px 8px;
}

.brand-mark {
  border: 0;
  width: 42px;
  height: 42px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-family: inherit;
  font-weight: 800;
  font-size: 17px;
  color: #fff;
  background: var(--app-primary);
  box-shadow: none;
  cursor: pointer;
  flex-shrink: 0;
  transition: transform var(--app-transition-fast), box-shadow var(--app-transition-fast);

  &:hover {
    transform: scale(1.025);
    box-shadow: none;
  }

  &:focus-visible {
    outline: 3px solid rgba(37, 99, 235, 0.32);
    outline-offset: 3px;
  }
}

.brand-text {
  overflow: hidden;
  white-space: nowrap;
}

.brand-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--app-text);
  letter-spacing: -0.02em;
}

.brand-subtitle {
  margin-top: 4px;
  color: var(--app-primary);
  font-size: 10px;
  font-weight: 500;
}

.nav-section-label {
  margin: 8px 12px 10px;
  font-size: 12px;
  letter-spacing: 0.08em;
  color: var(--app-primary);
  font-weight: 800;
  white-space: nowrap;
  overflow: hidden;
}

.nav-menu {
  flex: 1;
  min-width: 0;
}

.sidebar-footer {
  margin-top: auto;
  padding-top: 20px;
}

.footer-card {
  padding: 16px;
  border-radius: var(--app-radius-md);
  background: #f5f8ff;
  color: #334155;
  border: 1px solid #e7eefb;
  overflow: hidden;
}

.footer-card-label {
  font-size: 11px;
  opacity: 0.65;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.footer-card-title {
  margin-top: 8px;
  font-size: 16px;
  font-weight: 700;
}

.footer-card-desc {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  opacity: 0.7;
}

.footer-card-meter {
  display: none;
  height: 6px;
  margin-top: 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.16);
  overflow: hidden;
}

.footer-card-meter span {
  display: block;
  width: 78%;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #22c55e, #38bdf8);
}

.layout-main {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  position: relative;
}

.layout-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
  gap: 16px;
  min-height: 84px;
  padding: 16px 28px;
  background: #ffffff;
  border-bottom: 1px solid var(--app-border);
}

.header-left {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  flex: 1;
  min-width: 0;
}

.collapse-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.86);
  box-shadow: var(--app-shadow-xs);
  cursor: pointer;
  flex-shrink: 0;
  margin-top: 4px;
  transition: background-color 180ms ease, border-color 180ms ease, box-shadow 180ms ease;

  &:hover {
    background: rgba(47, 107, 255, 0.08);
    border-color: rgba(47, 107, 255, 0.24);
  }

  &:focus-visible {
    outline: 3px solid rgba(37, 99, 235, 0.22);
    outline-offset: 3px;
  }
}

.collapse-icon {
  font-size: 16px;
  color: var(--app-text-secondary);
  transition: transform var(--app-transition-base);
  line-height: 1;

  &.rotated {
    transform: rotate(180deg);
  }
}

.header-caption {
  font-size: 12px;
  letter-spacing: 0.08em;
  color: var(--app-primary);
  font-weight: 800;
  text-transform: uppercase;
}

.header-title {
  margin: 8px 0 0;
  font-size: 21px;
  line-height: 1.15;
  color: var(--app-text);
  letter-spacing: -0.03em;
}

/* 面包屑导航 */
.breadcrumb-nav {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding-top: 4px;
}

.breadcrumb-sep {
  color: var(--app-text-muted);
  font-size: 14px;
  user-select: none;
}

.breadcrumb-link {
  font-size: 14px;
  color: var(--app-text-secondary);
  text-decoration: none;
  transition: color 0.2s;

  &:hover {
    color: var(--app-primary);
  }

  &:focus-visible {
    outline-offset: 4px;
  }
}

.breadcrumb-current {
  font-size: 21px;
  font-weight: 700;
  color: var(--app-text);
  line-height: 1.15;
  letter-spacing: -0.025em;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}

.manual-entry-link {
  text-decoration: none;
}

.manual-entry-btn {
  min-height: 40px;
  border-radius: 999px;
  border-color: rgba(37, 99, 235, 0.18);
  color: var(--app-primary);
  background: rgba(255, 255, 255, 0.82);
  font-weight: 800;
  box-shadow: var(--app-shadow-xs);
}

.header-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(5, 150, 105, 0.16);
  color: var(--app-steel);
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
  box-shadow: var(--app-shadow-xs);
  backdrop-filter: blur(14px);
}

.header-chip-blue {
  border-color: rgba(14, 165, 233, 0.18);
  background: rgba(239, 246, 255, 0.78);
}

.scan-line {
  width: 22px;
  height: 8px;
  border-radius: 999px;
  background:
    linear-gradient(90deg, transparent, var(--app-cyan), transparent);
  box-shadow: 0 0 14px rgba(14, 165, 233, 0.32);
}

.chip-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: var(--app-success);
  box-shadow: 0 0 0 6px rgba(18, 168, 122, 0.12);
}

.user-box {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 12px;
  border-color: rgba(37, 99, 235, 0.10);
}

.user-avatar {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  color: #fff;
  font-weight: 700;
  font-size: 15px;
  background: linear-gradient(135deg, var(--app-primary-deep), var(--app-primary), var(--app-cyan));
}

.user-meta {
  min-width: 70px;
}

.user-name {
  font-weight: 700;
  color: var(--app-text);
}

.user-role {
  margin-top: 4px;
  color: var(--app-text-secondary);
  font-size: 12px;
}

.layout-content {
  min-width: 0;
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
  scroll-behavior: smooth;
}

/* 回到顶部按钮 */
.back-top-btn {
  position: absolute;
  bottom: 24px;
  right: 16px;
  z-index: 50;
  width: 46px;
  height: 46px;
  border-radius: 14px;
  border: 1px solid rgba(15, 23, 42, 0.1);
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(12px);
  box-shadow: 0 8px 24px rgba(16, 35, 63, 0.1);
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: background-color 200ms ease, border-color 200ms ease, box-shadow 200ms ease;

  &:hover {
    background: var(--app-primary);
    border-color: var(--app-primary);
    box-shadow: 0 12px 28px rgba(47, 107, 255, 0.28);
  }

  &:focus-visible {
    outline: 3px solid rgba(37, 99, 235, 0.24);
    outline-offset: 3px;
  }
}

.back-top-arrow {
  font-size: 20px;
  color: var(--app-text-secondary);
  transform: rotate(-90deg);
  line-height: 1;
  transition: color 0.25s;

  .back-top-btn:hover & {
    color: #fff;
  }
}

 .assistant-entry-link { display: inline-flex; align-items: center; gap: 7px; color: var(--app-primary); font-weight: 600; padding: 8px 12px; border-radius: 10px; background: #eff5ff; white-space: nowrap; transition: background .18s, transform .18s; }
.assistant-entry-link:hover { background: #e2edff; transform: translateY(-1px); }
.is-agent-workspace .layout-content, .is-trace-workspace .layout-content { overflow: hidden; padding: 18px 22px; }
@media (max-width: 1200px) { .manual-entry-link { display: none; } .header-actions { gap: 10px; } }
@media (max-width: 1024px) {
  .sidebar-collapsed .layout-sidebar { padding: 16px 8px; }
  .sidebar-collapsed .brand-block { padding: 4px; justify-content: center; }
  .layout-header { padding: 14px 18px; }
  .layout-content { padding: 20px; }
}
@media (max-width: 640px) {
  .layout-shell, .layout-shell.sidebar-collapsed { grid-template-columns: 56px minmax(0, 1fr); }
  .layout-sidebar { padding: 12px 4px; }
  .brand-mark { width: 36px; height: 36px; border-radius: 11px; font-size: 13px; }
  .brand-block { padding: 0; margin-bottom: 16px; }
  .layout-header { min-height: 68px; padding: 12px; gap: 8px; }
  .header-caption, .breadcrumb-link, .breadcrumb-sep, .user-meta, .assistant-entry-link { display: none; }
  .header-title, .breadcrumb-current { font-size: 17px; }
  .header-actions { gap: 4px; }
  .user-box { padding: 0; border: 0; box-shadow: none; gap: 6px; background: transparent; }
  .user-avatar { width: 30px; height: 30px; font-size: 12px; }
  .user-box :deep(.el-button) { padding: 6px; font-size: 11px; }
  .layout-content { padding: 12px; }
  .is-agent-workspace .layout-content, .is-trace-workspace .layout-content { padding: 8px; }
  .back-top-btn { display: none; }
}
</style>

<style scoped>
.brand-title { font-size: 15px; letter-spacing: -.02em; }
.brand-subtitle { font-size: 12px; }
.layout-header { min-height: 76px; background: white; border-bottom: 1px solid var(--app-border); }
.header-actions { gap: 14px; }
.workspace-scope { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; font-size: 12px; color: var(--app-text-secondary); }
.breadcrumb-nav { flex-wrap: wrap; gap: 6px; }
.breadcrumb-current { color: var(--app-text); font-weight: 600; }
.layout-content { padding: 28px 32px; }
.user-box { border: 0; background: transparent; box-shadow: none; padding: 0; gap: 10px; }
.user-avatar { width: 34px; height: 34px; font-size: 13px; background: var(--app-primary-soft); color: var(--app-primary); border-radius: 10px; }
.user-role { margin-top: 1px; font-size: 12px; }
.user-box .el-button--danger { border-color: transparent; background: transparent; }
.footer-card { box-shadow: none; border: 0; background: var(--app-bg); padding: 15px; }
.footer-card-meter { display: none; }
.back-top-btn { border-radius: 12px; width: 40px; height: 40px; box-shadow: var(--app-shadow-sm); color: var(--app-text-secondary); }
.back-top-btn:hover { color: white; }
@media(min-width: 641px) and (max-width: 1024px) {
  .workspace-scope { display: none; }
  .layout-content { padding: 22px; }
}
@media(max-width: 640px) {
  .layout-shell, .layout-shell.sidebar-collapsed { grid-template-columns: minmax(0, 1fr); }
  .layout-sidebar { display: none; }
  .collapse-btn { display: inline-flex; flex: 0 0 34px; width: 34px; height: 34px; }
  .layout-header { min-height: 62px; padding: 10px 12px; }
  .header-left { min-width: 0; gap: 10px; }
  .breadcrumb-current { font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 38vw; }
  .workspace-scope, .manual-entry-link, .user-box .user-avatar { display: none; }
  .header-actions { gap: 8px; }
  .layout-content { padding: 18px 14px; }
}
@media(prefers-reduced-motion: reduce) { .layout-shell, .brand-mark, .back-top-btn { transition: none; } .brand-mark:hover { transform:none; } }
</style>
