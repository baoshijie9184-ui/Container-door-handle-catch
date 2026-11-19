<template>
  <div class="login-page">
    <section class="login-showcase" aria-label="系统介绍">
      <a class="login-brand" href="#/login" :title="SYSTEM_NAME" :aria-label="SYSTEM_NAME">
        <img src="/favicon.svg" width="40" height="40" alt="" />
        <span>{{ SYSTEM_SHORT_NAME }}<small>{{ SYSTEM_TAGLINE }}</small></span>
      </a>
      <div class="showcase-inner">
        <h1>集装箱门把手盖<br /><em>视觉质检</em></h1>
        <p>从原图采集到人工复核，追溯每一次质量判断。</p>
      </div>
    </section>
    <section class="login-panel" aria-labelledby="login-title">
      <div class="login-card">
        <span class="login-card-icon"><AppIcon name="Key" :size="24" /></span>
        <h2 id="login-title">登录工作空间</h2>
        <p class="login-card-desc">使用员工或主管账号，进入检测与质检工作台。</p>
        <el-alert v-if="loginError" id="login-error" ref="loginErrorRef" tabindex="-1" :title="loginError" type="error" :closable="false" show-icon role="alert" />
        <p v-if="!online" class="login-inline-note is-warning" role="status"><AppIcon name="Connection" :size="15" />浏览器报告网络已断开，请核对连接。恢复后不会自动提交登录。</p>
        <el-form ref="loginFormRef" :model="loginForm" :rules="rules" :disabled="loading || loginAccepted" label-position="top" class="login-form" :aria-busy="loading" @submit.prevent="handleLogin">
          <el-form-item label="用户名" prop="username">
            <el-input v-model="loginForm.username" name="username" placeholder="请输入用户名" size="large" :prefix-icon="UserIcon" autocomplete="username" autocapitalize="none" :spellcheck="false" :disabled="loading" :aria-describedby="loginError ? 'login-error' : undefined" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input v-model="loginForm.password" name="password" type="password" placeholder="请输入密码" size="large" show-password :prefix-icon="LockIcon" autocomplete="current-password" :disabled="loading" :aria-describedby="[loginError ? 'login-error' : '', capsLock ? 'login-caps-lock' : ''].filter(Boolean).join(' ') || undefined" @keydown="updateCapsLock" @keyup="updateCapsLock" @blur="capsLock = false" />
          </el-form-item>
          <p v-if="capsLock" id="login-caps-lock" class="login-inline-note is-warning" role="status"><AppIcon name="Warning" :size="15" />大写锁定已开启，请注意密码大小写</p>
          <div class="login-options"><el-checkbox v-model="rememberMe" :disabled="loading" aria-describedby="login-remember-note">记住账号</el-checkbox><el-button link type="primary" :disabled="loading" @click="showForgotDialog = true">忘记密码</el-button></div>
          <p id="login-remember-note" class="login-remember-note">仅记住用户名，不保存密码</p>
          <p v-if="!preferenceAvailable || !userStore.displayCacheAvailable" class="login-inline-note" role="status"><AppIcon name="Document" :size="14" />浏览器暂不能保存账号偏好，本次登录仍可继续</p>
          <el-button v-if="!loginAccepted" type="primary" :loading="loading" class="login-button" size="large" native-type="submit"><span>{{ loading ? '正在登录' : '登录系统' }}</span><AppIcon v-if="!loading" name="ArrowRight" :size="17" /></el-button>
          <router-link v-else class="login-open-workspace" to="/home">{{ loading ? '正在打开工作空间' : '重新打开工作空间' }}<AppIcon name="ArrowRight" :size="17" /></router-link>
        </el-form>
        <p class="login-card-footer"><AppIcon name="Lock" :size="14" />账号权限与操作记录随登录身份生效</p>
      </div>
      <span class="login-timezone"><AppIcon name="Clock" :size="14" />北京时间 · UTC+8</span>
    </section>
    <el-dialog v-model="showForgotDialog" title="找回密码" width="min(440px, 94vw)" class="login-password-help">
      <div class="password-help-heading"><AppIcon name="Key" :size="21" /><strong>联系企业主管或系统管理员</strong></div>
      <p class="password-help">请提供需要核对的用户名，由有权限的管理员处理账号与密码问题。当前页面不支持自行重置。</p>
      <template #footer><el-button type="primary" @click="showForgotDialog = false">知道了</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import {SYSTEM_NAME, SYSTEM_SHORT_NAME, SYSTEM_TAGLINE} from '@/utils/systemBrand'
import { ref, reactive, nextTick, onMounted, onUnmounted } from 'vue'
import { User as UserIcon, Lock as LockIcon } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { readAccountPreference, writeAccountPreference } from '@/utils/accountPreferences'

const router = useRouter()
const userStore = useUserStore()
const loading = ref(false)
const loginError = ref('')
const loginAccepted = ref(false)
const loginFormRef = ref(null)
const loginErrorRef = ref(null)
const online = ref(typeof navigator === 'undefined' || navigator.onLine !== false)
const capsLock = ref(false)
const preferenceAvailable = ref(true)
const rememberMe = ref(false)
const showForgotDialog = ref(false)
let pageActive = true

function updateNetwork() { online.value = navigator.onLine !== false }
function updateCapsLock(event) { capsLock.value = event.getModifierState?.('CapsLock') === true }

const loginForm = reactive({
  username: '',
  password: ''
})

onMounted(() => {
  window.addEventListener('online', updateNetwork)
  window.addEventListener('offline', updateNetwork)
  const saved = readAccountPreference('rememberedUser')
  preferenceAvailable.value = saved.available
  if (saved.value) {
    loginForm.username = saved.value
    rememberMe.value = true
  }
})
onUnmounted(() => {
  pageActive = false
  window.removeEventListener('online', updateNetwork)
  window.removeEventListener('offline', updateNetwork)
  loginForm.password = ''
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
  if (!loginFormRef.value || loading.value || loginAccepted.value) return
  loginError.value = ''
  loading.value = true

  try {
    await loginFormRef.value.validate()
  } catch {
    loading.value = false
    await nextTick()
    if (pageActive) loginFormRef.value?.$el?.querySelector('.el-form-item.is-error input')?.focus()
    return
  }
  if (!pageActive) return

  try {
    await userStore.login({ username: loginForm.username, password: loginForm.password })
    if (!pageActive) return
    loginAccepted.value = true
    preferenceAvailable.value = writeAccountPreference('rememberedUser', rememberMe.value ? loginForm.username : null)
    if (preferenceAvailable.value && userStore.displayCacheAvailable) ElMessage.success('登录成功，欢迎回来')
    else ElMessage.warning('已登录，浏览器暂不能保存账号偏好，下次可能需要重新填写用户名')
    await router.push('/home')
  } catch (error) {
    if (!pageActive) return
    loginError.value = loginAccepted.value ? '登录已完成，但工作空间暂未打开。请重新打开工作空间，不需要重复提交密码。' : error.message || '登录失败，请检查账号信息或稍后重试'
    await nextTick()
    loginErrorRef.value?.$el?.focus()
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(380px, 1fr);
  min-height: 100vh;
  min-height: 100dvh;
  padding: clamp(12px, 1.45vw, 24px);
  background: white;
}
.login-showcase { display:flex; flex-direction:column; justify-content:space-between; gap:24px; min-width:0; padding:clamp(24px,3.2vw,56px); border:1px solid var(--app-border); border-radius:20px; background:#f8f9fa; }
.login-showcase::before { content:''; order:1; flex:1 1 160px; min-height:100px; max-height:40vh; border-radius:12px; background:url('../assets/images/container-lock.webp') center 48% / cover; filter:grayscale(.93); }
.login-brand { display:inline-flex; align-items:center; align-self:flex-start; gap:12px; color:var(--app-text); font-size:17px; font-weight:650; }
.login-brand img { border-radius:10px; }
.login-brand small { display:block; margin-top:2px; font-size:11px; font-weight:450; letter-spacing:.08em; color:var(--app-text-muted); }
.showcase-inner { order:2; }
.showcase-inner h1 { margin:0; font-size:clamp(34px,3.8vw,62px); line-height:1.18; font-weight:650; letter-spacing:-.055em; color:var(--app-text); }
.showcase-inner em { color:var(--app-primary-deep); font-style:normal; }
.showcase-inner p { margin-top:16px; font-size:14px; line-height:1.85; color:var(--app-text-secondary); }
.login-panel { display: flex; flex-direction: column; justify-content: center; align-items: center; position: relative; min-width: 0; padding: 70px 32px; }
.login-card { width: 100%; max-width: 368px; animation: login-reveal 200ms ease both; }
.login-card-icon { display: grid; place-items: center; width: 46px; height: 46px; margin-bottom: 20px; background: var(--app-primary-soft); color: var(--app-primary); border-radius: 14px; }
.login-card h2 { font-size: clamp(28px, 2.4vw, 38px); line-height: 1.35; font-weight: 650; letter-spacing: -.045em; }
.login-card-desc { margin: 9px 0 30px; font-size: 14px; color: var(--app-text-secondary); }
.login-card .el-alert { margin-bottom: 20px; }
.login-form :deep(.el-form-item__label) { font-weight: 550; color: var(--app-text); }
.login-form :deep(.el-input__wrapper) { min-height: 48px; padding-inline: 15px; border-radius: 9px; border: 1px solid var(--app-border-strong); background: white; }
.login-form :deep(.el-input__wrapper.is-focus) { box-shadow: 0 0 0 1px var(--app-primary) inset, 0 0 0 3px var(--app-primary-glow); }
.login-form :deep(.el-form-item) { margin-bottom: 23px; }
.login-options { display:flex; align-items:center; justify-content:space-between; margin:0 0 3px; gap:12px; }
.login-remember-note { margin:0 0 18px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.login-inline-note { display:flex; align-items:flex-start; gap:7px; margin:0 0 15px; padding:9px 10px; border-radius:7px; color:var(--app-text-secondary); background:var(--app-info-soft); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.login-inline-note > .el-icon { flex:0 0 auto; margin-top:3px; }
.login-inline-note.is-warning { color:var(--app-warning); background:var(--app-warning-soft); }
.login-open-workspace { display:flex; align-items:center; justify-content:space-between; gap:12px; width:100%; min-height:46px; box-sizing:border-box; padding:11px 18px; border-radius:8px; color:white; background:var(--app-primary); font-size:14px; text-decoration:none; }
.login-open-workspace:hover { background:var(--app-primary-hover); }
.login-form :deep(.el-form-item.is-error .el-input__wrapper) { border-color:var(--app-danger); }
.login-card .el-alert:focus-visible { outline:2px solid var(--app-danger); outline-offset:3px; }
.password-help-heading { display:flex; align-items:center; gap:9px; margin:4px 0 12px; color:var(--app-text); font-size:14px; line-height:1.7; }
.password-help-heading > .el-icon { flex:0 0 auto; color:var(--app-primary); }
.login-page :is(button,a,input):focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
.login-button { width: 100%; height: 48px; border-radius: 9px; font-weight: 600; }
.login-button :deep(> span) { width: 100%; justify-content: space-between; }
.login-card-footer, .login-timezone { display: flex; align-items: center; gap: 7px; color: var(--app-text-muted); font-size: 12px; line-height: 1.8; }
.login-card-footer { margin-top: 22px; justify-content: center; }
.login-card-footer > .el-icon { flex-shrink:0; }
.login-timezone { position: absolute; bottom: 24px; font-size:12px; color:var(--app-text-secondary); }
.password-help { color: var(--app-text-secondary); line-height: 1.8; }
@keyframes login-reveal { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: none; } }
@media (max-width: 800px) {
  .login-page { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto 1fr; padding: 10px; }
  .login-showcase { padding:16px 20px; background:white; border:0; border-bottom:1px solid var(--app-border); border-radius:0; }
  .login-showcase::before { display:none; }
  .showcase-inner { display: none; }
  .login-panel { padding: 30px 16px 20px; }
  .login-card-desc { margin-bottom: 22px; }
  .login-timezone { position: static; margin-top: 32px; }
}
@media (max-height: 630px) and (min-width: 801px) {
  .login-panel { padding-block: 26px; }
  .login-timezone { position: static; margin-top: 20px; }
}
@media(prefers-reduced-motion: reduce) { .login-card { animation: none; } }
</style>
