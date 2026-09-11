<template>
  <div class="login-page">
    <!-- 动态背景 -->
    <div class="login-backdrop">
      <div class="backdrop-overlay"></div>
      <div class="backdrop-grid"></div>
    </div>

    <!-- 左侧展示区 -->
    <section class="login-showcase">
      <div class="showcase-inner animate-fade-in-up">
        <span class="login-badge">DoorHandleCatch Console</span>
        <h1>集装箱门把手检测<br/>智能管理平台</h1>
        <p>
          统一管理检测任务、设备状态、人员分配与模型版本，让现场采集、缺陷识别与运维协同更高效。
        </p>

        <div class="showcase-grid">
          <div class="showcase-card animate-stagger-1">
            <div class="showcase-card-icon">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>
            </div>
            <strong>智能检测</strong>
            <span>AI 模型自动识别门把手弯曲、形变、锈蚀、缺失等六类缺陷</span>
          </div>
          <div class="showcase-card animate-stagger-2">
            <div class="showcase-card-icon">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            </div>
            <strong>运行总览</strong>
            <span>首页仪表盘实时展示检测趋势、设备状态和人员分布数据</span>
          </div>
          <div class="showcase-card animate-stagger-3">
            <div class="showcase-card-icon">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
            </div>
            <strong>协同管理</strong>
            <span>人员、设备与模型三位一体，减少跨系统切换和沟通成本</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 右侧登录面板 -->
    <section class="login-panel">
      <div class="login-card animate-scale-in">
        <div class="login-card-head">
          <span class="login-card-label">账号登录</span>
          <h2>进入控制台</h2>
          <p class="login-card-desc">使用管理员账号登录管理平台</p>
        </div>

        <el-form
          ref="loginFormRef"
          :model="loginForm"
          :rules="rules"
          label-position="top"
          class="login-form"
          @submit.prevent="handleLogin"
        >
          <el-form-item label="用户名" prop="username">
            <el-input
              v-model="loginForm.username"
              placeholder="请输入用户名"
              size="large"
              :prefix-icon="UserIcon"
              autocomplete="username"
            />
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input
              v-model="loginForm.password"
              type="password"
              placeholder="请输入密码"
              size="large"
              show-password
              :prefix-icon="LockIcon"
              autocomplete="current-password"
              @keyup.enter="handleLogin"
            />
          </el-form-item>

          <div class="login-options">
            <el-checkbox v-model="rememberMe">记住我</el-checkbox>
            <el-link type="primary" :underline="false" @click="showForgotDialog = true">忘记密码？</el-link>
          </div>

          <el-form-item class="login-form-actions">
            <el-button
              type="primary"
              :loading="loading"
              class="login-button"
              size="large"
              native-type="submit"
              @click="handleLogin"
            >
              <template v-if="!loading">登录系统</template>
            </el-button>
          </el-form-item>
        </el-form>

        <div class="login-card-footer">
          <span>集装箱门把手检测智能管理软件 v0.1</span>
        </div>
      </div>
    </section>

    <!-- 忘记密码弹窗 -->
    <el-dialog v-model="showForgotDialog" title="找回密码" width="400px">
      <p style="line-height:1.8;color:#475569;">
        如需重置密码，请联系系统管理员：<br/>
        <strong>邮箱：</strong>admin@doorhandle.com<br/>
        <strong>电话：</strong>400-800-8888
      </p>
      <template #footer>
        <el-button type="primary" @click="showForgotDialog = false">我知道了</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, shallowRef, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()
const loading = ref(false)
const loginFormRef = ref(null)
const rememberMe = ref(false)
const showForgotDialog = ref(false)

const UserIcon = shallowRef({ render() { return null } })
const LockIcon = shallowRef({ render() { return null } })

import('@element-plus/icons-vue').then(mod => {
  UserIcon.value = mod.User
  LockIcon.value = mod.Lock
})

const loginForm = reactive({
  username: '',
  password: ''
})

onMounted(() => {
  const saved = localStorage.getItem('rememberedUser')
  if (saved) {
    loginForm.username = saved
    rememberMe.value = true
  }
})

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: ['blur', 'change'] }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: ['blur', 'change'] }
  ]
}

const handleLogin = async () => {
  if (!loginFormRef.value) return

  try {
    await loginFormRef.value.validate()
  } catch {
    return
  }

  loading.value = true

  try {
    await userStore.login(loginForm)
    if (rememberMe.value) {
      localStorage.setItem('rememberedUser', loginForm.username)
    } else {
      localStorage.removeItem('rememberedUser')
    }
    ElMessage.success('登录成功，欢迎回来')
    router.push('/home')
  } catch (error) {
    ElMessage.error(error.message || '登录失败，请稍后重试')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* ═══════════════════════════════════════════════════════════
   登录页 — 全屏分栏布局
   ═══════════════════════════════════════════════════════════ */

.login-page {
  position: relative;
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(440px, 480px);
  overflow: hidden;
}

/* ── 动态背景 ── */

.login-backdrop {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
}

.backdrop-overlay {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(115deg, rgba(15, 23, 42, 0.82) 0%, rgba(15, 23, 42, 0.48) 55%, rgba(15, 23, 42, 0.3) 100%),
    url('@/assets/images/image.png') center / cover no-repeat;
}

.backdrop-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
  background-size: 60px 60px;
  mask-image: radial-gradient(ellipse at 30% 50%, black 40%, transparent 70%);
}

/* ── 左侧展示区 ── */

.login-showcase {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  padding: 72px 56px 72px 80px;
  color: #f1f5f9;
}

.showcase-inner {
  max-width: 600px;
}

.login-badge {
  display: inline-flex;
  align-items: center;
  padding: 6px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.15);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  backdrop-filter: blur(8px);
}

.login-showcase h1 {
  margin: 24px 0 16px;
  font-size: clamp(32px, 4.5vw, 48px);
  line-height: 1.12;
  font-weight: 800;
  letter-spacing: -0.025em;
  color: #ffffff;
}

.login-showcase p {
  max-width: 540px;
  margin: 0;
  color: rgba(226, 232, 240, 0.8);
  font-size: 15px;
  line-height: 1.8;
}

/* ── 特性卡片 ── */

.showcase-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-top: 40px;
}

.showcase-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 20px 18px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(12px);
  transition: all var(--app-transition-base);
}

.showcase-card:hover {
  background: rgba(255, 255, 255, 0.13);
  border-color: rgba(255, 255, 255, 0.2);
  transform: translateY(-2px);
}

.showcase-card-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.9);
}

.showcase-card strong {
  font-size: 14px;
  font-weight: 700;
  color: #ffffff;
}

.showcase-card span {
  color: rgba(203, 213, 225, 0.75);
  font-size: 12px;
  line-height: 1.65;
}

/* ── 右侧登录面板 ── */

.login-panel {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 36px;
}

.login-card {
  width: 100%;
  max-width: 400px;
  padding: 36px 32px 28px;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(20px);
  box-shadow:
    0 4px 24px rgba(15, 23, 42, 0.06),
    0 24px 80px rgba(15, 23, 42, 0.12);
}

.login-card-head {
  margin-bottom: 8px;
}

.login-card-head h2 {
  margin: 8px 0 4px;
  color: var(--app-text);
  font-size: 28px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.login-card-label {
  display: inline-flex;
  align-items: center;
  padding: 5px 12px;
  border-radius: 999px;
  background: var(--app-primary-soft);
  color: var(--app-primary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.login-card-desc {
  margin: 0;
  color: var(--app-text-muted);
  font-size: 13px;
}

/* ── 表单 ── */

.login-form {
  margin-top: 24px;
}

.login-form :deep(.el-form-item__label) {
  color: var(--app-text);
  font-weight: 600;
  font-size: 13px;
  padding-bottom: 4px;
}

.login-options {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.login-form-actions {
  margin-top: 8px;
  margin-bottom: 0;
}

.login-button {
  width: 100%;
  height: 48px;
  font-size: 15px;
  letter-spacing: 0.02em;
}

/* ── 底部 ── */

.login-card-footer {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--app-border);
  text-align: center;
}

.login-card-footer span {
  font-size: 12px;
  color: var(--app-text-muted);
}

/* ── 响应式 ── */

@media (max-width: 1100px) {
  .login-page {
    grid-template-columns: 1fr;
  }

  .login-showcase {
    padding: 60px 28px 16px;
    text-align: center;
  }

  .showcase-inner {
    max-width: none;
  }

  .login-showcase p {
    max-width: none;
  }

  .showcase-grid {
    grid-template-columns: 1fr;
    max-width: 400px;
    margin: 32px auto 0;
  }

  .login-panel {
    padding: 0 20px 32px;
    align-items: flex-start;
  }
}

@media (max-width: 640px) {
  .login-showcase {
    padding-top: 44px;
  }

  .login-showcase h1 {
    font-size: 28px;
  }

  .login-card {
    padding: 24px 20px 20px;
    border-radius: 20px;
  }
}
</style>
