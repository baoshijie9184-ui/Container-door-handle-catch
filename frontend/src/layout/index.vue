<template>
  <div class="layout-shell" :class="{ 'sidebar-collapsed': collapsed }">
    <button class="skip-link" type="button" @click="skipToMainContent">跳到主要内容</button>
    <aside class="layout-sidebar app-panel" aria-label="系统导航">
      <div class="brand-block">
        <button
          class="brand-mark"
          type="button"
          :aria-label="collapsed ? '展开菜单' : '收起菜单'"
          :aria-expanded="!collapsed"
          @click="collapsed = !collapsed"
        >
          DH
        </button>
        <div v-show="!collapsed" class="brand-text">
          <div class="brand-title">DoorHandle Catch</div>
          <div class="brand-subtitle">工业检测智能控制台</div>
        </div>
      </div>

      <div v-show="!collapsed" class="nav-section-label">业务导航</div>
      <el-menu :default-active="activeMenu" router :collapse="collapsed" class="nav-menu">
        <template v-for="group in navGroups" :key="group.key">
          <el-menu-item
            v-if="group.items.length === 1"
            :index="group.items[0].path"
            class="nav-root-item"
          >
            <el-icon><component :is="group.icon" /></el-icon>
            <template #title>
              <span>{{ group.items[0].label }}</span>
              <small v-if="group.desc" class="nav-item-desc">{{ group.desc }}</small>
            </template>
          </el-menu-item>
          <el-sub-menu v-else :index="group.key" class="nav-group">
            <template #title>
              <el-icon><component :is="group.icon" /></el-icon>
              <span>{{ group.label }}</span>
            </template>
            <el-menu-item
              v-for="item in group.items"
              :key="item.path"
              :index="item.path"
              class="nav-child-item"
            >
              <template #title>
                <span>{{ item.label }}</span>
                <small v-if="item.desc" class="nav-item-desc">{{ item.desc }}</small>
              </template>
            </el-menu-item>
          </el-sub-menu>
        </template>
      </el-menu>

      <div v-show="!collapsed" class="sidebar-footer">
        <div class="footer-card">
          <div class="footer-card-label">当前状态</div>
          <div class="footer-card-title">系统在线运行</div>
          <div class="footer-card-desc">统一管理模型、检测、设备和人员数据</div>
          <div class="footer-card-meter">
            <span></span>
          </div>
        </div>
      </div>
    </aside>

    <div class="layout-main">
      <header class="layout-header">
        <div class="header-left">
          <button
            class="collapse-btn"
            type="button"
            @click="collapsed = !collapsed"
            :title="collapsed ? '展开菜单' : '收起菜单'"
            :aria-label="collapsed ? '展开菜单' : '收起菜单'"
            :aria-expanded="!collapsed"
          >
            <span class="collapse-icon" :class="{ rotated: collapsed }">&#x2039;&#x2039;</span>
          </button>
          <div v-if="breadcrumbs.length" class="breadcrumb-nav">
            <template v-for="(crumb, idx) in breadcrumbs" :key="idx">
              <span v-if="idx > 0" class="breadcrumb-sep">/</span>
              <router-link
                v-if="crumb.path && idx < breadcrumbs.length - 1"
                :to="crumb.path"
                class="breadcrumb-link"
              >
                {{ crumb.label }}
              </router-link>
              <span v-else class="breadcrumb-current" aria-current="page">{{ crumb.label }}</span>
            </template>
          </div>
          <div v-else>
            <div class="header-caption">工业视觉检测平台</div>
            <h1 class="header-title">{{ currentPageTitle }}</h1>
          </div>
        </div>

        <div class="header-actions">
          <router-link to="/manual" class="manual-entry-link">
            <el-button class="manual-entry-btn" plain>
              <el-icon><Files /></el-icon>
              使用手册
            </el-button>
          </router-link>
          <div class="header-chip">
            <span class="chip-dot pulse-dot"></span>
            平台稳定运行
          </div>
          <div class="header-chip header-chip-blue">
            <span class="scan-line"></span>
            视觉检测链路就绪
          </div>
          <div class="user-box app-panel">
            <div class="user-avatar">{{ userInitial }}</div>
            <div class="user-meta">
              <div class="user-name">{{ userStore.username || '企业用户' }}</div>
              <div class="user-role">企业用户</div>
            </div>
            <el-button type="danger" plain size="small" @click="handleLogout">退出登录</el-button>
          </div>
        </div>
      </header>

      <main id="main-content" class="layout-content" tabindex="-1">
        <router-view v-slot="{ Component }">
          <transition name="page-slide">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>

      <!-- 回到顶部按钮 -->
      <button v-show="showBackTop" class="back-top-btn" type="button" @click="scrollToTop" title="回到顶部" aria-label="回到顶部">
        <span class="back-top-arrow">&#x203A;</span>
      </button>
    </div>

    <ChatAssistantLauncher @open="handleOpenAssistant" />
    <ChatAssistantDrawer />
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { useUserStore } from '@/stores/user'
import { useRouter, useRoute } from 'vue-router'
import { useChatAssistantStore } from '@/stores/chatAssistant'
import ChatAssistantDrawer from '@/components/chat/ChatAssistantDrawer.vue'
import ChatAssistantLauncher from '@/components/chat/ChatAssistantLauncher.vue'
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
  Operation
} from '@element-plus/icons-vue'

const userStore = useUserStore()
const chatAssistantStore = useChatAssistantStore()
const router = useRouter()
const route = useRoute()

const collapsed = ref(false)
const showBackTop = ref(false)

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
      { path: '/models/upload', label: '上传模型', desc: '导入新模型版本' }
    ]
  },
  {
    key: 'resources',
    label: '产线资源',
    icon: Operation,
    items: [
      { path: '/devices', label: '设备管理', desc: '采集与检测设备' },
      { path: '/device-records', label: '设备使用记录', desc: '设备调用与维护记录' },
      { path: '/employees', label: '人员管理', desc: '采集、检测、维修人员' }
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
const currentPageTitle = computed(() => currentNavItem.value?.label || route.meta.title || '数据总览')

// 面包屑导航
const breadcrumbs = computed(() => {
  const crumbs = [{ label: '首页', path: '/home' }]
  const meta = route.meta
  if (route.path === '/home') return []
  if (currentNavItem.value) {
    crumbs.push({ label: currentNavItem.value.group })
    crumbs.push({ label: currentNavItem.value.label })
    return crumbs
  }
  if (meta.parent) {
    crumbs.push({ label: meta.parent })
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
    main.scrollTo({ top: 0, behavior: 'smooth' })
  }
}

function skipToMainContent() {
  const main = document.querySelector('.layout-content')
  const mainContent = document.getElementById('main-content')
  if (!main || !mainContent) return
  mainContent.focus({ preventScroll: true })
  main.scrollTo({ top: 0, behavior: 'smooth' })
}

onMounted(() => {
  const main = document.querySelector('.layout-content')
  if (main) main.addEventListener('scroll', handleScroll, { passive: true })
})

onBeforeUnmount(() => {
  const main = document.querySelector('.layout-content')
  if (main) main.removeEventListener('scroll', handleScroll)
})
</script>

<style lang="scss" scoped>
.layout-shell {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  height: 100vh;
  padding: clamp(12px, 1.2vw, 18px);
  gap: clamp(12px, 1.2vw, 18px);
  overflow: hidden;
  transition: grid-template-columns 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  background:
    radial-gradient(circle at 16px 16px, rgba(37, 99, 235, 0.08) 1px, transparent 1px);
  background-size: 32px 32px;
}

.layout-shell.sidebar-collapsed {
  grid-template-columns: 80px minmax(0, 1fr);
}

.layout-sidebar {
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 18px;
  height: calc(100vh - 36px);
  padding: 20px 14px;
  overflow-y: auto;
  overflow-x: hidden;
  background:
    radial-gradient(circle at 15% 0%, rgba(14, 165, 233, 0.16), transparent 34%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(239, 246, 255, 0.86)),
    linear-gradient(135deg, rgba(37, 99, 235, 0.09), transparent 45%);
  border-color: rgba(37, 99, 235, 0.12);
  box-shadow: var(--app-shadow-command);
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 28px;
  padding: 8px 10px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.45);
  border: 1px solid rgba(37, 99, 235, 0.08);
}

.brand-mark {
  border: 0;
  width: 46px;
  height: 46px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  font-family: inherit;
  font-weight: 800;
  font-size: 17px;
  color: #fff;
  background:
    radial-gradient(circle at 28% 20%, rgba(255, 255, 255, 0.34), transparent 28%),
    linear-gradient(135deg, #0f2f57, var(--app-primary) 55%, var(--app-cyan));
  box-shadow: 0 14px 34px rgba(15, 47, 87, 0.32);
  cursor: pointer;
  flex-shrink: 0;
  transition: transform var(--app-transition-fast), box-shadow var(--app-transition-fast);

  &:hover {
    transform: scale(1.06);
    box-shadow: 0 16px 34px rgba(37, 99, 235, 0.36);
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
  font-size: 18px;
  font-weight: 800;
  color: var(--app-text);
  letter-spacing: -0.02em;
}

.brand-subtitle {
  margin-top: 4px;
  color: var(--app-primary);
  font-size: 12px;
  font-weight: 700;
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
  border-right: 0 !important;

  :deep(.el-menu-item) {
    height: 48px;
    line-height: 48px;
    margin: 4px 0;
    border-radius: 14px;
    color: var(--app-text-secondary);
    transition: all 0.2s;

    &:hover {
      background: rgba(15, 23, 42, 0.04);
      color: var(--app-text);
    }

    &.is-active {
      color: var(--app-primary) !important;
      background:
        linear-gradient(90deg, rgba(37, 99, 235, 0.16), rgba(14, 165, 233, 0.07), transparent) !important;
      border: 1px solid rgba(37, 99, 235, 0.10);
      font-weight: 800;
      box-shadow: inset 3px 0 0 var(--app-primary);
    }
  }

  :deep(.el-sub-menu__title) {
    height: 48px;
    line-height: 48px;
    margin: 4px 0;
    border-radius: 14px;
    color: var(--app-text-secondary);
    transition: all 0.2s;

    &:hover {
      background: rgba(15, 23, 42, 0.04);
      color: var(--app-text);
    }
  }

  :deep(.el-sub-menu.is-active > .el-sub-menu__title) {
    color: var(--app-primary) !important;
    background: rgba(37, 99, 235, 0.08) !important;
    font-weight: 800;
  }

  :deep(.el-menu--inline) {
    padding: 2px 0 8px 12px;
  }
}

.nav-child-item {
  min-height: 48px;
}

.nav-root-item,
.nav-child-item {
  :deep(.el-menu-tooltip__trigger),
  :deep(.el-tooltip__trigger) {
    width: 100%;
  }
}

.nav-item-desc {
  display: block;
  margin-top: 2px;
  color: var(--app-text-muted);
  font-size: 11px;
  font-weight: 600;
  line-height: 1.2;
  transform: translateY(-2px);
}

.layout-shell.sidebar-collapsed .nav-item-desc {
  display: none;
}

.sidebar-footer {
  margin-top: 18px;
}

.footer-card {
  padding: 16px;
  border-radius: var(--app-radius-md);
  background:
    radial-gradient(circle at 15% 15%, rgba(56, 189, 248, 0.28), transparent 36%),
    linear-gradient(135deg, #0f172a, #17395f 58%, #0f766e);
  color: #fff;
  box-shadow: var(--app-shadow-command);
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
  display: flex;
  flex-direction: column;
  height: calc(100vh - 36px);
  overflow: hidden;
  position: relative;
}

.layout-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: clamp(12px, 1.2vw, 18px);
  margin-bottom: clamp(12px, 1.2vw, 18px);
  padding: clamp(12px, 1.2vw, 18px) 8px 0;
  position: relative;
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
  transition: all 0.2s;

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
  transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1);
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
  font-size: clamp(24px, 2vw, 32px);
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
  font-size: 28px;
  font-weight: 800;
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
  min-width: 96px;
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
  flex: 1;
  overflow-y: auto;
  padding-right: 8px;
  padding-bottom: 18px;
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
  transition: all 0.25s;

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

@media (max-width: 1100px) {
  .layout-shell {
    grid-template-columns: 1fr;
    height: auto;
    overflow: visible;
  }

  .layout-shell.sidebar-collapsed {
    grid-template-columns: 1fr;
  }

  .layout-sidebar {
    position: static;
    top: auto;
    height: auto;
    padding: 18px;
    overflow: visible;
  }

  .layout-header {
    flex-direction: column;
  }

  .header-actions {
    width: 100%;
    flex-wrap: wrap;
  }

  .layout-main {
    height: auto;
    overflow: visible;
  }

  .layout-content {
    overflow: visible;
    padding-right: 0;
  }

  .back-top-btn {
    display: none;
  }
}

@media (max-width: 768px) {
  .layout-shell {
    padding: 12px;
    gap: 12px;
  }

  .header-title,
  .breadcrumb-current {
    font-size: 24px;
  }

  .user-box {
    width: 100%;
    justify-content: space-between;
  }

  .header-left {
    width: 100%;
  }

  .header-actions {
    align-items: stretch;
  }

  .header-chip {
    justify-content: center;
  }

  .brand-block {
    margin-bottom: 18px;
  }
}
</style>
