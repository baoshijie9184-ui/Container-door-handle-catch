<template>
  <div class="login-page">
    <section class="login-showcase" aria-label="系统介绍">
      <a class="login-brand" href="#/login"><span class="login-brand-mark"><AppIcon name="Picture" :size="23" /></span><span>DoorHandle Catch<small>集装箱门把手质量管理</small></span></a>
      <div class="showcase-inner">
        <span class="login-product-label">工业视觉检测与协作</span>
        <h1>从一张原图<br />到有据可查的质量结论</h1>
        <p>连接图片采集、缺陷检测、人工复核与报告，让现场团队在同一个工作空间协作。</p>
        <HandleInspectionGraphic />
        <div class="login-capabilities">
          <span><AppIcon name="Picture" :size="17" />图片检测</span>
          <span><AppIcon name="CircleCheck" :size="17" />人工质检</span>
          <span><AppIcon name="ChatDotRound" :size="17" />智能助手</span>
        </div>
      </div>
      <p class="login-scope-note"><AppIcon name="Lock" :size="15" />员工查看本人及分派任务，主管查看企业业务</p>
    </section>
    <section class="login-panel" aria-labelledby="login-title">
      <div class="login-card">
        <span class="login-card-icon"><AppIcon name="User" :size="25" /></span>
        <h2 id="login-title">登录工作空间</h2>
        <p class="login-card-desc">使用你的员工或主管账号继续</p>
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
      <span class="login-timezone">业务时间统一使用北京时间 UTC+8</span>
    </section>
    <el-dialog v-model="showForgotDialog" title="找回密码" width="min(440px, 94vw)" class="login-password-help">
      <div class="password-help-heading"><AppIcon name="Key" :size="21" /><strong>联系企业主管或系统管理员</strong></div>
      <p class="password-help">请提供需要核对的用户名，由有权限的管理员处理账号与密码问题。当前页面不支持自行重置。</p>
      <template #footer><el-button type="primary" @click="showForgotDialog = false">知道了</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, nextTick, onMounted, onUnmounted } from 'vue'
import { User as UserIcon, Lock as LockIcon } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import HandleInspectionGraphic from '@/components/HandleInspectionGraphic.vue'
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
.login-page { min-height: 100vh; min-height: 100dvh; display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(400px, 1fr); background: white; }
.login-showcase { display: flex; flex-direction: column; padding: 38px clamp(28px, 6vw, 90px); background: #f6f8fb; border-right: 1px solid var(--app-border); }
.login-brand { display: flex; align-items: center; gap: 11px; font-size: 17px; font-weight: 700; color: var(--app-text); }
.login-brand-mark { display: grid; place-items: center; width: 43px; height: 43px; background: var(--app-primary); border-radius: 12px; color: white; }
.login-brand small { display: block; font-weight: 400; font-size: 11px; margin-top: 3px; color: var(--app-text-muted); }
.showcase-inner { max-width: 560px; margin-block: auto; padding-block: 38px; }
.login-product-label { color: var(--app-primary); font-size: 12px; font-weight: 600; }
.showcase-inner h1 { margin: 18px 0 16px; color: var(--app-text); font-size: clamp(28px, 3vw, 42px); font-weight: 700; letter-spacing: -.04em; line-height: 1.38; }
.showcase-inner > p { color: var(--app-text-secondary); font-size: 14px; line-height: 1.9; max-width: 39em; }
.login-capabilities { display: flex; flex-wrap: wrap; gap: 18px; }
.login-capabilities span, .login-scope-note, .login-card-footer { display: flex; align-items: center; gap: 7px; color: var(--app-text-secondary); font-size: 12px; }
.login-capabilities .el-icon { color: var(--app-primary); }
.login-scope-note { font-size: 11px; padding-top: 18px; border-top: 1px solid var(--app-border); }
.login-panel { position: relative; display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 52px 32px; }
.login-card { width: 100%; max-width: 365px; animation: login-reveal 200ms ease both; }
.login-card-icon { width: 49px; height: 49px; display: grid; place-items: center; background: var(--app-primary-soft); color: var(--app-primary); border-radius: 14px; margin-bottom: 22px; }
.login-card h2 { font-size: 27px; font-weight: 700; letter-spacing: -.025em; }
.login-card-desc { margin: 8px 0 26px; font-size: 13px; color: var(--app-text-muted); }
.login-card .el-alert { margin-bottom: 20px; }
.login-form :deep(.el-input__wrapper) { min-height: 46px; box-shadow: 0 0 0 1px var(--app-border) inset; background: white; }
.login-form :deep(.el-input__wrapper.is-focus) { box-shadow: 0 0 0 1px var(--app-primary) inset, 0 0 0 3px #2563eb10; }
.login-form :deep(.el-form-item) { margin-bottom: 23px; }
.login-options { display:flex; align-items:center; justify-content:space-between; margin:0 0 3px; gap:12px; }
.login-remember-note { margin:0 0 18px; color:var(--app-text-muted); font-size:11px; line-height:1.7; }
.login-inline-note { display:flex; align-items:flex-start; gap:7px; margin:0 0 15px; padding:9px 10px; border-radius:7px; color:var(--app-text-secondary); background:var(--app-info-soft); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.login-inline-note > .el-icon { flex:0 0 auto; margin-top:3px; }
.login-inline-note.is-warning { color:var(--app-warning); background:var(--app-warning-soft); }
.login-open-workspace { display:flex; align-items:center; justify-content:space-between; gap:12px; width:100%; min-height:46px; box-sizing:border-box; padding:11px 18px; border-radius:8px; color:white; background:var(--app-primary); font-size:14px; text-decoration:none; }
.login-open-workspace:hover { background:var(--app-primary-hover); }
.login-form :deep(.el-form-item.is-error .el-input__wrapper) { box-shadow:0 0 0 1px var(--app-danger) inset; }
.login-card .el-alert:focus-visible { outline:2px solid var(--app-danger); outline-offset:3px; }
.password-help-heading { display:flex; align-items:center; gap:9px; margin:4px 0 12px; color:var(--app-text); font-size:14px; line-height:1.7; }
.password-help-heading > .el-icon { flex:0 0 auto; color:var(--app-primary); }
.login-page :is(button,a,input):focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
.login-button { width: 100%; height: 46px; justify-content: space-between; padding-inline: 18px; box-shadow: none; }
.login-card-footer { margin-top: 24px; justify-content: center; font-size: 11px; line-height: 1.7; }
.login-timezone { position: absolute; bottom: 24px; font-size: 11px; color: var(--app-text-muted); }
.password-help { color: var(--app-text-secondary); line-height: 1.8; }
@keyframes login-reveal { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: none; } }
@media(max-width: 850px) { .login-page { grid-template-columns: 1fr; } .login-showcase { padding: 24px; border-right: 0; border-bottom: 1px solid var(--app-border); } .showcase-inner, .login-scope-note { display: none; } .login-panel { padding: 44px 24px 70px; flex: 1; } .login-brand { font-size: 15px; } .login-card h2 { font-size: 25px; } }
@media(max-width:420px) { .login-panel { padding-inline:20px; }.login-card-footer { align-items:flex-start; }.login-card-footer .el-icon { flex:0 0 auto; margin-top:3px; }.login-timezone { position:static; margin-top:30px; text-align:center; line-height:1.7; } }
@media(prefers-reduced-motion: reduce) { .login-card { animation: none; } }
</style>
