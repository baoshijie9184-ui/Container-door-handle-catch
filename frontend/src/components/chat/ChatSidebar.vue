<template>
  <button v-if="compact && !collapsed" class="session-backdrop" type="button" aria-label="关闭会话列表" @click="collapsed = true"></button>
  <aside class="chat-sidebar" :class="{ collapsed: collapsed, compact: compact }" @keydown.esc="collapsed = true">
    <!-- 折叠按钮 -->
    <button class="sidebar-toggle" @click="collapsed = !collapsed" :title="collapsed ? '展开会话列表' : '收起会话列表'" :aria-label="collapsed ? '展开会话列表' : '收起会话列表'" :aria-expanded="!collapsed">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <polyline v-if="collapsed" points="9 18 15 12 9 6" />
        <polyline v-else points="15 18 9 12 15 6" />
      </svg>
    </button>

    <template v-if="!collapsed">
      <div class="sidebar-caption"><strong>DoorHandle <span class="sidebar-agent-label">Agent</span></strong><span>检测与质检工作空间</span></div>
      <!-- 新建按钮组 -->
      <div class="sidebar-header">
        <button class="new-session-btn" @click="store.newSession()">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          <span>新建对话</span>
        </button>
        <button class="new-project-btn" @click="openCreateProjectModal">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            <line x1="12" y1="11" x2="12" y2="17" />
            <line x1="9" y1="14" x2="15" y2="14" />
          </svg>
          <span>新建项目</span>
        </button>
      </div>

      <!-- 搜索框 -->
      <div class="sidebar-search">
        <div class="search-input-wrapper">
          <svg class="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索标题或摘要"
            aria-label="搜索已加载的对话标题或摘要"
            aria-describedby="sidebar-search-scope"
            class="search-input"
          />
          <button v-if="searchQuery" type="button" class="search-clear" aria-label="清除对话搜索" title="清除搜索" @click="clearSearch">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      <div class="sidebar-history-heading"><span>{{ searchQuery.trim() ? `匹配 ${searchResults.length} 条` : '对话历史' }}</span><button type="button" aria-label="重新读取会话列表" title="重新读取会话列表" :disabled="store.sessionsLoading" @click="store.loadSessionList()"><AppIcon name="Refresh" :size="15" /></button></div>
      <p id="sidebar-search-scope" class="sidebar-search-scope">仅搜索当前账号已加载的标题和摘要</p>
      <p v-if="store.sessionsError" class="sidebar-read-error" role="alert">{{ store.sessionsError }}</p>
      <p v-if="renameError" class="sidebar-read-error" role="alert">{{ renameError }}<button v-if="renameUncertain" type="button" @click="cancelEdit(); store.loadSessionList()">关闭编辑并重新读取</button></p>
      <!-- 会话列表 -->
      <div class="session-list" :aria-busy="store.sessionsLoading">
        <!-- 项目分组 -->
        <template v-if="!searchQuery.trim()">
          <!-- 有项目的会话 -->
          <template v-for="project in store.projects" :key="project.projectId">
            <div
              class="project-group"
              :class="{ 'drag-over': dragTargetProject === project.projectId }"
              @dragover.prevent="handleDragOver($event, project.projectId)"
              @dragleave="handleDragLeave"
              @drop="handleDrop($event, project.projectId)"
            >
              <div class="project-header">
                <button type="button" class="project-info project-disclosure" :aria-expanded="!!expandedProjects[project.projectId]" @click="toggleProject(project.projectId)">
                  <AppIcon :name="expandedProjects[project.projectId] ? 'ArrowDown' : 'ArrowRight'" :size="12" />
                  <span class="project-color" :style="{ background: project.color }"></span>
                  <span class="project-name">{{ project.name }}</span>
                  <span class="project-count">{{ getProjectSessions(project.projectId).length }}</span>
                </button>
                <div class="project-actions">
                  <button
                    class="project-menu-btn"
                    title="项目操作"
                    :aria-label="`项目操作：${project.name}`"
                    :aria-expanded="store.projectMenuOpenId === project.projectId"
                    @click.stop="store.toggleProjectMenu(project.projectId)"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                      <circle cx="12" cy="5" r="1" />
                      <circle cx="12" cy="12" r="1" />
                      <circle cx="12" cy="19" r="1" />
                    </svg>
                  </button>
                </div>
                <!-- 项目下拉菜单 -->
                <div class="project-menu" v-if="store.projectMenuOpenId === project.projectId" @click.stop>
                  <button class="menu-item" @click="openEditProjectModal(project)">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                    </svg>
                    <span>编辑项目</span>
                  </button>
                  <div class="menu-divider"></div>
                  <button class="menu-item menu-item-danger" @click="handleDeleteProject(project.projectId)">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                      <line x1="10" y1="11" x2="10" y2="17" />
                      <line x1="14" y1="11" x2="14" y2="17" />
                    </svg>
                    <span>删除项目</span>
                  </button>
                </div>
              </div>
              <div class="project-sessions" v-if="expandedProjects[project.projectId]">
                <div
                  v-for="sess in getProjectSessions(project.projectId)"
                  :key="sess.sessionId"
                  :data-session-id="sess.sessionId"
                  class="session-item"
                  :class="{
                    active: sess.sessionId === store.sessionId,
                    pinned: sess.pinned,
                    'dragging': draggingSessionId === sess.sessionId
                  }"
                  draggable="true"
                  @dragstart="handleDragStart($event, sess.sessionId)"
                  @dragend="handleDragEnd"
                >
                  <div class="session-item-main">
                    <button v-if="editingId !== sess.sessionId" type="button" class="session-open" :aria-current="sess.sessionId === store.sessionId ? 'page' : undefined" :title="sessionTimestampLabel(sess) + '（UTC+8）'" @click="handleSwitchSession(sess.sessionId)" @dblclick.stop="startEdit(sess)">
                    <span class="session-title">
                      <el-icon v-if="sess.pinned" class="pin-icon" aria-label="已置顶"><Position /></el-icon>
                      {{ sess.title || '新对话' }}
                    </span>
                    <span v-if="sessionPreview(sess)" class="session-preview">{{ sessionPreview(sess) }}</span>
                    <span class="session-meta">{{ sessionMetadata(sess, historyNow) }}</span>
                    </button>
                    <div class="session-title-edit" v-else @click.stop>
                      <input
                        :ref="el => setEditInputRef(el, sess.sessionId)"
                        v-model="editingTitle"
                        @blur="finishEdit(sess.sessionId)"
                        @keydown.enter="finishEdit(sess.sessionId)"
                        @keydown.escape="cancelEdit"
                        :maxlength="SESSION_TITLE_MAX_LENGTH"
                        class="title-edit-input"
                        aria-label="会话名称"
                        :disabled="renameBusy || renameUncertain"
                      />
                    </div>
                    <button v-if="sess.sourceSessionId && editingId !== sess.sessionId" type="button" class="session-source-link" title="返回分支来源会话" @click="handleSwitchSession(sess.sourceSessionId)"><AppIcon name="Connection" :size="12" />分支来源</button>
                  </div>
                  <!-- 更多操作按钮 -->
                  <div class="session-more-wrapper" v-if="editingId !== sess.sessionId">
                    <button
                      class="session-more-btn"
                      title="更多操作"
                      :aria-label="`会话操作：${sess.title || '新对话'}`"
                      :aria-expanded="store.menuOpenId === sess.sessionId"
                      @click.stop="store.toggleMenu(sess.sessionId)"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                        <circle cx="12" cy="5" r="1" />
                        <circle cx="12" cy="12" r="1" />
                        <circle cx="12" cy="19" r="1" />
                      </svg>
                    </button>
                    <!-- 下拉菜单 -->
                    <div class="session-menu" v-if="store.menuOpenId === sess.sessionId" @click.stop>
                      <button class="menu-item" @click="handleDownload(sess)">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                          <polyline points="7 10 12 15 17 10" />
                          <line x1="12" y1="15" x2="12" y2="3" />
                        </svg>
                        <span>下载记录</span>
                      </button>
                      <button class="menu-item" @click="startEdit(sess); store.closeMenu()">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                        </svg>
                        <span>重命名</span>
                      </button>
                      <button class="menu-item" @click="handlePin(sess)">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                          <path d="M12 17v5" />
                          <path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76z" />
                        </svg>
                        <span>{{ sess.pinned ? '取消置顶' : '置顶聊天' }}</span>
                      </button>
                      <!-- 移动到项目子菜单 -->
                      <div class="menu-item menu-item-submenu" v-if="store.projects.length > 1 || (store.projects.length === 1 && sess.projectId !== store.projects[0].projectId)">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                        </svg>
                        <span>移动到项目</span>
                        <svg class="submenu-arrow" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                          <polyline points="9 18 15 12 9 6" />
                        </svg>
                        <div class="submenu">
                          <button
                            v-for="p in store.projects.filter(p => p.projectId !== sess.projectId)"
                            :key="p.projectId"
                            class="submenu-item"
                            @click="handleMoveToProject(sess.sessionId, p.projectId)"
                          >
                            <span class="project-color-small" :style="{ background: p.color }"></span>
                            {{ p.name }}
                          </button>
                        </div>
                      </div>
                      <button class="menu-item" @click="handleRemoveFromProject(sess.sessionId)">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                          <path d="M3 6h18" />
                          <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                        </svg>
                        <span>移出项目</span>
                      </button>
                      <div class="menu-divider"></div>
                      <button class="menu-item menu-item-danger" @click="handleDelete(sess.sessionId)">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                          <polyline points="3 6 5 6 21 6" />
                          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                          <line x1="10" y1="11" x2="10" y2="17" />
                          <line x1="14" y1="11" x2="14" y2="17" />
                        </svg>
                        <span>删除</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- 未分组的会话 -->
          <div
            class="project-group"
            :class="{ 'drag-over': dragTargetProject === '__ungrouped__' }"
            @dragover.prevent="handleDragOver($event, '__ungrouped__')"
            @dragleave="handleDragLeave"
            @drop="handleDrop($event, '__ungrouped__')"
          >
            <div class="project-header">
              <button type="button" class="project-info project-disclosure" :aria-expanded="!!expandedProjects['__ungrouped__']" @click="toggleProject('__ungrouped__')">
                <AppIcon :name="expandedProjects['__ungrouped__'] ? 'ArrowDown' : 'ArrowRight'" :size="12" />
                <span class="project-name">未分组</span>
                <span class="project-count">{{ ungroupedSessions.length }}</span>
              </button>
            </div>
            <div class="project-sessions" v-if="expandedProjects['__ungrouped__']">
              <template v-for="group in ungroupedHistory" :key="group.key">
              <h3 class="session-date-heading">{{ group.label }}</h3>
              <div
                v-for="sess in group.sessions"
                :key="sess.sessionId"
                :data-session-id="sess.sessionId"
                class="session-item"
                :class="{
                  active: sess.sessionId === store.sessionId,
                  pinned: sess.pinned,
                  'dragging': draggingSessionId === sess.sessionId
                }"
                draggable="true"
                @dragstart="handleDragStart($event, sess.sessionId)"
                @dragend="handleDragEnd"
              >
                <div class="session-item-main">
                  <button v-if="editingId !== sess.sessionId" type="button" class="session-open" :aria-current="sess.sessionId === store.sessionId ? 'page' : undefined" :title="sessionTimestampLabel(sess) + '（UTC+8）'" @click="handleSwitchSession(sess.sessionId)" @dblclick.stop="startEdit(sess)">
                  <span class="session-title">
                    <el-icon v-if="sess.pinned" class="pin-icon" aria-label="已置顶"><Position /></el-icon>
                    {{ sess.title || '新对话' }}
                  </span>
                  <span v-if="sessionPreview(sess)" class="session-preview">{{ sessionPreview(sess) }}</span>
                  <span class="session-meta">{{ sessionMetadata(sess, historyNow) }}</span>
                  </button>
                  <div class="session-title-edit" v-else @click.stop>
                    <input
                      :ref="el => setEditInputRef(el, sess.sessionId)"
                      v-model="editingTitle"
                      @blur="finishEdit(sess.sessionId)"
                      @keydown.enter="finishEdit(sess.sessionId)"
                      @keydown.escape="cancelEdit"
                      :maxlength="SESSION_TITLE_MAX_LENGTH"
                      class="title-edit-input"
                      aria-label="会话名称"
                      :disabled="renameBusy || renameUncertain"
                    />
                  </div>
                  <button v-if="sess.sourceSessionId && editingId !== sess.sessionId" type="button" class="session-source-link" title="返回分支来源会话" @click="handleSwitchSession(sess.sourceSessionId)"><AppIcon name="Connection" :size="12" />分支来源</button>
                </div>
                <!-- 更多操作按钮 -->
                <div class="session-more-wrapper" v-if="editingId !== sess.sessionId">
                  <button
                    class="session-more-btn"
                    title="更多操作"
                    :aria-label="`会话操作：${sess.title || '新对话'}`"
                    :aria-expanded="store.menuOpenId === sess.sessionId"
                    @click.stop="store.toggleMenu(sess.sessionId)"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                      <circle cx="12" cy="5" r="1" />
                      <circle cx="12" cy="12" r="1" />
                      <circle cx="12" cy="19" r="1" />
                    </svg>
                  </button>
                  <!-- 下拉菜单 -->
                  <div class="session-menu" v-if="store.menuOpenId === sess.sessionId" @click.stop>
                    <button class="menu-item" @click="handleDownload(sess)">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="7 10 12 15 17 10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                      </svg>
                      <span>下载记录</span>
                    </button>
                    <button class="menu-item" @click="startEdit(sess); store.closeMenu()">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                      </svg>
                      <span>重命名</span>
                    </button>
                    <button class="menu-item" @click="handlePin(sess)">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                        <path d="M12 17v5" />
                        <path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76z" />
                      </svg>
                      <span>{{ sess.pinned ? '取消置顶' : '置顶聊天' }}</span>
                    </button>
                    <!-- 移动到项目子菜单 -->
                    <div class="menu-item menu-item-submenu" v-if="store.projects.length > 0">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                      </svg>
                      <span>移动到项目</span>
                      <svg class="submenu-arrow" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                        <polyline points="9 18 15 12 9 6" />
                      </svg>
                      <div class="submenu">
                        <button
                          v-for="p in store.projects"
                          :key="p.projectId"
                          class="submenu-item"
                          @click="handleMoveToProject(sess.sessionId, p.projectId)"
                        >
                          <span class="project-color-small" :style="{ background: p.color }"></span>
                          {{ p.name }}
                        </button>
                      </div>
                    </div>
                    <div class="menu-divider"></div>
                    <button class="menu-item menu-item-danger" @click="handleDelete(sess.sessionId)">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                        <polyline points="3 6 5 6 21 6" />
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                        <line x1="10" y1="11" x2="10" y2="17" />
                        <line x1="14" y1="11" x2="14" y2="17" />
                      </svg>
                      <span>删除</span>
                    </button>
                  </div>
                </div>
              </div>
              </template>
            </div>
          </div>
        </template>

        <!-- 搜索结果 -->
        <template v-else>
          <div
            v-for="sess in searchResults"
            :key="sess.sessionId"
            :data-session-id="sess.sessionId"
            class="session-item"
            :class="{ active: sess.sessionId === store.sessionId }"
          >
            <div class="session-item-main">
              <button type="button" class="session-open" :aria-current="sess.sessionId === store.sessionId ? 'page' : undefined" :title="sessionTimestampLabel(sess) + '（UTC+8）'" @click="handleSwitchSession(sess.sessionId)">
              <span class="session-title">
                <el-icon v-if="sess.pinned" class="pin-icon" aria-label="已置顶"><Position /></el-icon>
                {{ sess.title || '新对话' }}
              </span>
              <span v-if="sessionPreview(sess)" class="session-preview">{{ sessionPreview(sess) }}</span>
              <span class="session-meta">{{ sessionMetadata(sess, historyNow) }}</span>
              </button>
              <button v-if="sess.sourceSessionId" type="button" class="session-source-link" title="返回分支来源会话" @click="handleSwitchSession(sess.sourceSessionId)"><AppIcon name="Connection" :size="12" />分支来源</button>
            </div>
          </div>
        </template>

        <!-- 空状态 -->
        <div v-if="store.sessionsLoading && !store.sessions.length" class="session-empty" role="status">
          正在读取会话
        </div>
        <div v-else-if="!store.sessions.length && !store.sessionsError" class="session-empty">
          <AppIcon name="ChatDotRound" :size="24" /><strong>暂无会话历史</strong><span>新建对话，开始检测与质检工作</span>
        </div>
        <div v-else-if="searchQuery.trim() && !searchResults.length && !store.sessionsError" class="session-empty">
          <AppIcon name="Search" :size="24" /><strong>没有匹配的会话</strong><button type="button" @click="clearSearch">清空搜索</button>
        </div>
      </div>

      <!-- 创建/编辑项目弹窗 -->
      <div class="modal-overlay" v-if="showProjectModal" @click.self="closeProjectModal">
        <div class="modal-content">
          <h3 class="modal-title">{{ editingProject ? '编辑项目' : '创建项目' }}</h3>
          <div class="modal-form">
            <div class="form-group">
              <label>项目名称</label>
              <input v-model="projectForm.name" type="text" placeholder="输入项目名称" maxlength="50" />
            </div>
            <div class="form-group">
              <label>项目描述</label>
              <textarea v-model="projectForm.description" placeholder="输入项目描述（可选）" maxlength="200" rows="2"></textarea>
            </div>
            <div class="form-group">
              <label>项目颜色</label>
              <div class="color-picker">
                <div
                  v-for="color in projectColors"
                  :key="color"
                  class="color-option"
                  :class="{ selected: projectForm.color === color }"
                  :style="{ background: color }"
                  @click="projectForm.color = color"
                ></div>
              </div>
            </div>
          </div>
          <div class="modal-actions">
            <button class="btn-cancel" @click="closeProjectModal">取消</button>
            <button class="btn-confirm" @click="handleSaveProject" :disabled="!projectForm.name.trim()">
              {{ editingProject ? '保存' : '创建' }}
            </button>
          </div>
        </div>
      </div>
    </template>
  </aside>
</template>

<script setup>
import { ref, nextTick, computed, reactive, watch, onMounted, onUnmounted } from 'vue'
import { useChatAssistantStore } from '@/stores/chatAssistant'
import { Position } from '@element-plus/icons-vue'
import {businessTimestamp} from '@/utils/beijingTime'
import {SESSION_TITLE_MAX_LENGTH, sessionHistoryGroups, sessionMetadata, sessionPreview, sessionTimestampLabel} from '@/utils/sessionPresentation'

const props = defineProps({
  compact: {
    type: Boolean,
    default: false
  }
})

const store = useChatAssistantStore()
const collapsed = ref(props.compact)
const historyNow = ref(Date.now())
let historyClock
onMounted(() => { historyClock = window.setInterval(() => { historyNow.value = Date.now() }, 60000) })
onUnmounted(() => { window.clearInterval(historyClock) })

watch(() => props.compact, (compact) => {
  collapsed.value = compact
})

// 重命名相关
const editingId = ref(null)
const editingTitle = ref('')
const renameBusy = ref(false)
const renameError = ref('')
const renameUncertain = ref(false)
const editInputRefs = {}

const setEditInputRef = (el, sessionId) => {
  if (el) {
    editInputRefs[sessionId] = el
  } else {
    delete editInputRefs[sessionId]
  }
}

// 搜索相关
const searchQuery = ref('')

// 项目相关
const expandedProjects = reactive({ __ungrouped__: true })
const showProjectModal = ref(false)
const editingProject = ref(null)
const projectForm = reactive({
  name: '',
  description: '',
  color: '#2563eb'
})

const projectColors = [
  '#2563eb', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1'
]

// 拖拽相关
const draggingSessionId = ref(null)
const dragTargetProject = ref(null)

// 获取项目中的会话
const getProjectSessions = (projectId) => {
  let sessions = store.sessions.filter(s => s.projectId === projectId)

  if (searchQuery.value.trim()) {
    const query = searchQuery.value.trim().toLowerCase()
    sessions = sessions.filter(s =>
      (s.title && s.title.toLowerCase().includes(query)) ||
      (s.lastMessage && s.lastMessage.toLowerCase().includes(query))
    )
  }

  sessions.sort((a, b) => {
    if (a.pinned && !b.pinned) return -1
    if (!a.pinned && b.pinned) return 1
    return businessTimestamp(b.updatedAt) - businessTimestamp(a.updatedAt)
  })

  return sessions
}

// 未分组的会话
const ungroupedSessions = computed(() => {
  let sessions = store.sessions.filter(s => !s.projectId)

  if (searchQuery.value.trim()) {
    const query = searchQuery.value.trim().toLowerCase()
    sessions = sessions.filter(s =>
      (s.title && s.title.toLowerCase().includes(query)) ||
      (s.lastMessage && s.lastMessage.toLowerCase().includes(query))
    )
  }

  sessions.sort((a, b) => {
    if (a.pinned && !b.pinned) return -1
    if (!a.pinned && b.pinned) return 1
    return businessTimestamp(b.updatedAt) - businessTimestamp(a.updatedAt)
  })

  return sessions
})

// 搜索结果
const searchResults = computed(() => {
  if (!searchQuery.value.trim()) return []

  const query = searchQuery.value.trim().toLowerCase()
  const results = store.sessions.filter(s =>
    (s.title && s.title.toLowerCase().includes(query)) ||
    (s.lastMessage && s.lastMessage.toLowerCase().includes(query))
  )

  results.sort((a, b) => {
    if (a.pinned && !b.pinned) return -1
    if (!a.pinned && b.pinned) return 1
    return businessTimestamp(b.updatedAt) - businessTimestamp(a.updatedAt)
  })

  return results
})

const ungroupedHistory = computed(() => sessionHistoryGroups(ungroupedSessions.value, '', historyNow.value))

const toggleProject = (projectId) => {
  expandedProjects[projectId] = !expandedProjects[projectId]
}

const clearSearch = () => {
  searchQuery.value = ''
}

const handleSwitchSession = (sessionId) => {
  store.closeMenu()
  store.closeProjectMenu()
  store.switchSession(sessionId)
  if (props.compact) collapsed.value = true
}

const startEdit = (sess) => {
  if (renameBusy.value || renameUncertain.value) return
  renameError.value = ''
  editingId.value = sess.sessionId
  editingTitle.value = sess.title
  store.closeMenu()
  nextTick(() => {
    const input = editInputRefs[sess.sessionId]
    if (input) {
      input.focus()
      input.select()
    }
  })
}

const finishEdit = async (sessionId) => {
  if (renameBusy.value || renameUncertain.value || editingId.value !== sessionId) return
  const newTitle = editingTitle.value.trim()
  if (newTitle && newTitle !== store.sessions.find(s => s.sessionId === sessionId)?.title) {
    renameBusy.value = true
    renameError.value = ''
    try {
      const result = await store.renameCurrentSession(sessionId, newTitle)
      if (!result?.acknowledged) {
        renameUncertain.value = result?.uncertain === true
        renameError.value = renameUncertain.value ? '名称保存结果尚未核对，请先重新读取会话列表，不会自动重发。' : '名称未保存，请核对名称及当前账号权限。'
        return
      }
    } finally { renameBusy.value = false }
  }
  editingId.value = null
}

const cancelEdit = () => {
  if (renameBusy.value) return
  editingId.value = null
  renameError.value = ''
  renameUncertain.value = false
}

// 拖拽处理
const handleDragStart = (e, sessionId) => {
  draggingSessionId.value = sessionId
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', sessionId)
}

const handleDragEnd = () => {
  draggingSessionId.value = null
  dragTargetProject.value = null
}

const handleDragOver = (e, projectId) => {
  e.dataTransfer.dropEffect = 'move'
  dragTargetProject.value = projectId
}

const handleDragLeave = () => {
  dragTargetProject.value = null
}

const handleDrop = async (e, projectId) => {
  e.preventDefault()
  const sessionId = e.dataTransfer.getData('text/plain')

  if (sessionId) {
    // 查找会话当前所属项目
    const session = store.sessions.find(s => s.sessionId === sessionId)
    const currentProjectId = session?.projectId || null
    const targetProjectId = projectId === '__ungrouped__' ? null : projectId

    // 避免拖拽到同一项目
    if (currentProjectId === targetProjectId) {
      draggingSessionId.value = null
      dragTargetProject.value = null
      return
    }

    if (projectId === '__ungrouped__') {
      await store.removeFromProject(sessionId)
    } else {
      await store.moveToProject(sessionId, projectId)
      expandedProjects[projectId] = true
    }
  }

  draggingSessionId.value = null
  dragTargetProject.value = null
}

// 下载对话记录
const handleDownload = async (sess) => {
  store.closeMenu()
  try {
    const messages = await store.fetchSessionMessages(sess.sessionId)
    const content = messages.map(m => {
      const role = m.role === 'user' ? '用户' : '助手'
      const time = m.createdAt ? `[${m.createdAt}]` : ''
      return `${role} ${time}:\n${m.content}\n`
    }).join('\n---\n\n')

    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${sess.title || '对话记录'}.txt`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch (err) {
    console.error('下载对话记录失败:', err)
  }
}

// 置顶/取消置顶
const handlePin = async (sess) => {
  store.closeMenu()
  await store.togglePinSession(sess.sessionId, !sess.pinned)
}

// 删除会话
const handleDelete = async (sessionId) => {
  store.closeMenu()
  if (confirm('确定要删除这个对话吗？此操作不可恢复。')) {
    await store.deleteSession(sessionId)
  }
}

// 移动到项目
const handleMoveToProject = async (sessionId, projectId) => {
  store.closeMenu()
  await store.moveToProject(sessionId, projectId)
}

// 从项目移出
const handleRemoveFromProject = async (sessionId) => {
  store.closeMenu()
  await store.removeFromProject(sessionId)
}

// 项目弹窗
const openCreateProjectModal = () => {
  editingProject.value = null
  projectForm.name = ''
  projectForm.description = ''
  projectForm.color = '#2563eb'
  showProjectModal.value = true
}

const openEditProjectModal = (project) => {
  store.closeProjectMenu()
  editingProject.value = project
  projectForm.name = project.name
  projectForm.description = project.description || ''
  projectForm.color = project.color || '#2563eb'
  showProjectModal.value = true
}

const closeProjectModal = () => {
  showProjectModal.value = false
  editingProject.value = null
}

const handleSaveProject = async () => {
  if (!projectForm.name.trim()) return

  if (editingProject.value) {
    await store.updateProject(editingProject.value.projectId, {
      name: projectForm.name.trim(),
      description: projectForm.description.trim(),
      color: projectForm.color
    })
  } else {
    await store.createProject({
      name: projectForm.name.trim(),
      description: projectForm.description.trim(),
      color: projectForm.color
    })
  }

  closeProjectModal()
}

// 删除项目
const handleDeleteProject = async (projectId) => {
  store.closeProjectMenu()
  if (confirm('确定要删除这个项目吗？项目中的对话将移回未分组。')) {
    await store.deleteProject(projectId)
  }
}
</script>

<style scoped>
.chat-sidebar {
  width: 260px;
  flex-shrink: 0;
  background: #f8f9fc;
  border-right: 1px solid rgba(15, 23, 42, 0.06);
  display: flex;
  flex-direction: column;
  transition: width 0.22s ease;
  min-height: 0;
  position: relative;
}

.chat-sidebar.collapsed {
  width: 40px;
}

.chat-sidebar.compact:not(.collapsed) { position: absolute; inset: 0 auto 0 0; z-index: 32; width: min(260px, calc(100% - 40px)); box-shadow: 10px 0 30px #19315518; }
.session-backdrop { position: absolute; inset: 0; z-index: 31; background: #19315530; border: 0; cursor: pointer; }

.sidebar-toggle {
  position: absolute;
  right: -12px;
  top: 18px;
  width: 24px;
  height: 24px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  background: #fff;
  color: #64748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 5;
  padding: 0;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

.sidebar-toggle:hover {
  background: #f1f5f9;
  color: #334155;
}

.sidebar-header {
  padding: 16px 12px 8px;
  display: flex;
  gap: 6px;
}

.new-session-btn,
.new-project-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  color: #fff;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.2s;
}

.new-session-btn {
  background: linear-gradient(135deg, #2563eb, #3b5de7);
  box-shadow: 0 2px 6px rgba(79, 110, 247, 0.2);
}

.new-session-btn:hover {
  background: linear-gradient(135deg, #5f7ef9, #4b6de9);
  box-shadow: 0 3px 10px rgba(79, 110, 247, 0.3);
  transform: translateY(-1px);
}

.new-project-btn {
  background: #eaf0fb;
  color: #42608d;
  box-shadow: none;
}

.new-project-btn:hover {
  background: #dfe9fa;
  transform: translateY(-1px);
}

.sidebar-search {
  padding: 0 12px 8px;
}

.search-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 8px;
  color: #94a3b8;
  pointer-events: none;
}

.search-input {
  width: 100%;
  padding: 6px 28px 6px 28px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
  font-size: 12px;
  color: #334155;
  outline: none;
  transition: all 0.2s;
}

.search-input:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(79, 110, 247, 0.15);
}

.search-input::placeholder {
  color: #94a3b8;
}

.search-clear {
  position: absolute;
  right: 4px;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.search-clear:hover {
  background: #e2e8f0;
  color: #475569;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px;
}

/* 项目分组样式 */
.project-group {
  margin-bottom: 4px;
  border-radius: 8px;
  transition: all 0.2s;
}

.project-group.drag-over {
  background: rgba(79, 110, 247, 0.1);
  box-shadow: 0 0 0 2px rgba(79, 110, 247, 0.3);
}

.project-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.15s;
  position: relative;
}

.project-header:hover {
  background: rgba(0, 0, 0, 0.04);
}

.project-info {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.project-color {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.project-color-small {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.project-name {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.project-count {
  font-size: 11px;
  color: #94a3b8;
  background: #e2e8f0;
  padding: 1px 6px;
  border-radius: 10px;
  flex-shrink: 0;
}

.project-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.project-menu-btn {
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: all 0.15s;
}

.project-header:hover .project-menu-btn {
  opacity: 1;
}

.project-menu-btn:hover {
  background: #e2e8f0;
  color: #475569;
}

.project-menu {
  position: absolute;
  right: 0;
  top: 100%;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  padding: 4px;
  min-width: 140px;
  z-index: 10;
}

.project-arrow {
  color: #94a3b8;
  transition: transform 0.2s;
  flex-shrink: 0;
}

.project-arrow.expanded {
  transform: rotate(90deg);
}

.project-sessions {
  padding-left: 8px;
}

.session-item {
  display: flex;
  align-items: center;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
  margin-bottom: 1px;
}

.session-item:hover {
  background: rgba(79, 110, 247, 0.06);
}

.session-item.active {
  background: rgba(79, 110, 247, 0.12);
  box-shadow: inset 3px 0 0 #2563eb;
}

.session-item.dragging {
  opacity: 0.5;
  transform: scale(0.98);
}

.session-item-main {
  flex: 1;
  min-width: 0;
}

.session-title {
  font-size: 13px;
  font-weight: 500;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: default;
}

.session-title-edit {
  margin: -2px 0;
}

.title-edit-input {
  width: 100%;
  font-size: 13px;
  font-weight: 500;
  color: #1e293b;
  border: 1px solid #2563eb;
  border-radius: 4px;
  padding: 2px 6px;
  outline: none;
  background: #fff;
  box-shadow: 0 0 0 2px rgba(79, 110, 247, 0.15);
}

.session-preview {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-meta {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 2px;
}

.session-more-wrapper {
  position: relative;
  flex-shrink: 0;
}

.session-more-btn {
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: all 0.15s;
}

.session-item:hover .session-more-btn {
  opacity: 1;
}

.session-more-btn:hover {
  background: #e2e8f0;
  color: #475569;
}

.session-menu {
  position: absolute;
  right: 0;
  top: 100%;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  padding: 4px;
  min-width: 160px;
  z-index: 10;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #334155;
  cursor: pointer;
  font-size: 13px;
  transition: background 0.15s;
  text-align: left;
}

.menu-item:hover {
  background: #f1f5f9;
}

.menu-item-danger {
  color: #ef4444;
}

.menu-item-danger:hover {
  background: #fee2e2;
}

/* 子菜单样式 */
.menu-item-submenu {
  position: relative;
}

.submenu-arrow {
  margin-left: auto;
}

.submenu {
  display: none;
  position: absolute;
  left: -160px;
  top: 0;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  padding: 4px;
  min-width: 150px;
  z-index: 11;
}

.menu-item-submenu:hover .submenu {
  display: block;
}

.submenu-item {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 6px 10px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #334155;
  cursor: pointer;
  font-size: 12px;
  transition: background 0.15s;
  text-align: left;
}

.submenu-item:hover {
  background: #f1f5f9;
}

.menu-divider {
  height: 1px;
  background: #e2e8f0;
  margin: 4px 0;
}

.session-item.pinned {
  background: rgba(79, 110, 247, 0.04);
}

.pin-icon {
  font-size: 11px;
  margin-right: 2px;
}

.session-empty {
  text-align: center;
  color: #94a3b8;
  font-size: 12px;
  padding: 24px 0;
}

/* 弹窗样式 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal-content {
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  width: 320px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.15);
}

.modal-title {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 16px 0;
}

.modal-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-group label {
  font-size: 12px;
  font-weight: 500;
  color: #475569;
}

.form-group input,
.form-group textarea {
  padding: 8px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 13px;
  color: #334155;
  outline: none;
  transition: all 0.2s;
}

.form-group input:focus,
.form-group textarea:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(79, 110, 247, 0.15);
}

.form-group textarea {
  resize: vertical;
  min-height: 50px;
}

.color-picker {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.color-option {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.15s;
  border: 2px solid transparent;
}

.color-option:hover {
  transform: scale(1.1);
}

.color-option.selected {
  border-color: #1e293b;
  box-shadow: 0 0 0 2px #fff, 0 0 0 4px #1e293b;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}

.btn-cancel {
  padding: 8px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
  color: #475569;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s;
}

.btn-cancel:hover {
  background: #f1f5f9;
}

.btn-confirm {
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  background: #2563eb;
  color: #fff;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s;
}

.btn-confirm:hover {
  background: #3b5de7;
}

.btn-confirm:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.session-list::-webkit-scrollbar {
  width: 3px;
}

.session-list::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 999px;
}

.sidebar-history-heading { display: flex; align-items: center; justify-content: space-between; padding: 8px 14px 0; color: #475569; font-size: 12px; }
.sidebar-history-heading button { display: grid; place-items: center; width: 30px; height: 30px; border: 0; border-radius: 7px; background: transparent; color: #475569; cursor: pointer; transition: background-color 180ms, color 180ms; }
.sidebar-history-heading button:hover:not(:disabled) { background: #eff6ff; color: #2563eb; }
.sidebar-history-heading button:disabled { opacity: .5; cursor: wait; }
.sidebar-search-scope { margin: 4px 14px 8px; color: #64748b; font-size: 11px; line-height: 1.6; }
.sidebar-read-error { margin: 4px 12px 10px; padding: 9px 10px; border-radius: 8px; background: #fff7ed; color: #9a3412; font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.sidebar-read-error button { display: block; margin-top: 6px; border: 0; padding: 3px 0; color: #2563eb; background: transparent; font-size: inherit; text-align: left; cursor: pointer; }
.project-disclosure { flex: 1; min-width: 0; border: 0; padding: 4px 0; background: transparent; color: inherit; text-align: left; font: inherit; cursor: pointer; }
.project-disclosure .project-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-date-heading { margin: 14px 10px 5px; color: #64748b; font-size: 11px; font-weight: 500; }
.session-item { align-items: flex-start; transition: background-color 180ms, box-shadow 180ms; }
.session-open { display: flex; flex-direction: column; gap: 3px; width: 100%; min-width: 0; border: 0; padding: 3px 0; border-radius: 5px; color: #0f172a; background: transparent; text-align: left; font: inherit; cursor: pointer; }
.session-open .session-title, .session-open .session-preview, .session-open .session-meta { display: block; width: 100%; min-width: 0; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: inherit; }
.session-open .session-title { font-size: 13px; }
.session-open .session-preview { color: #475569; font-size: 12px; line-height: 1.6; }
.session-open .session-meta { color: #64748b; font-size: 11px; }
.session-item-main > .session-source-link { display: inline-flex; align-items: center; gap: 4px; margin: 4px 0 0; }
.session-empty { display: flex; flex-direction: column; align-items: center; gap: 10px; line-height: 1.8; }
.session-empty > .el-icon { color: #2563eb; }
.session-empty strong { font-weight: 550; color: #475569; }
.session-empty button { border: 0; border-radius: 6px; padding: 6px 10px; color: #2563eb; background: #eff6ff; cursor: pointer; }
.chat-sidebar button:focus-visible, .chat-sidebar input:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; }
.session-item:focus-within .session-more-btn { opacity: 1; }
@media (hover: none) { .session-more-btn { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .session-item, .sidebar-history-heading button { transition: none; } .session-item.dragging { transform: none; } }
</style>
