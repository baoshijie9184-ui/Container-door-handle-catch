import { defineStore } from 'pinia'
import { ref } from 'vue'
import request from '../api/request'
import { loginErrorMessage } from '../utils/loginError'
import { readAccountPreference, writeAccountPreference } from '../utils/accountPreferences'
import { accountSession, identityChanged, onIdentitySignal } from '../utils/accountContext'

export const useUserStore = defineStore('user', () => {
  const hint = readAccountPreference('username')
  const username = ref(hint.value || ''), role = ref('INSPECTOR'), identity = ref(null), userId = ref(null)
  const accountContext = ref(''), accountEpoch = ref(accountSession.state.epoch), accountNotice = ref(''), capabilities = ref({})
  const displayCacheAvailable = ref(hint.available), isAuthenticated = ref(false), hasCheckedAuth = ref(false)
  let pendingCheck, checkEpoch = -1
  accountSession.subscribe(state => {
    accountEpoch.value = state.epoch; accountContext.value = state.accountContext; accountNotice.value = state.reason
    isAuthenticated.value = state.authenticated
    if (!state.authenticated) { username.value = ''; role.value = 'INSPECTOR'; identity.value = null; userId.value = null; capabilities.value = {} }
    else {
      username.value = state.user.username; role.value = state.user.role; identity.value = state.user.identity || null
      userId.value = state.user.userId || state.user.identity?.userId || null
      capabilities.value = state.user.capabilities || {}
    }
  })
  const clearSession = (reason = '') => { accountSession.clear(reason); hasCheckedAuth.value = true; writeAccountPreference('username', null); writeAccountPreference('role', null) }
  const checkAuth = () => {
    const epoch = accountSession.state.epoch
    if (pendingCheck && checkEpoch === epoch) return pendingCheck
    checkEpoch = epoch
    const task = request.get('/api/auth/check', { headers: { 'Cache-Control': 'no-cache' } }).then(response => {
      if (accountSession.state.epoch !== epoch) return false
      const data = response.data?.data || response.data
      accountSession.accept(data, epoch); hasCheckedAuth.value = true
      if (!writeAccountPreference('username', data.username)) displayCacheAvailable.value = false
      return true
    }).catch(error => {
      if (accountSession.state.epoch !== epoch) return false
      if (error.response?.status === 401 || error.accountContextChanged) clearSession(error.accountContextChanged ? error.message : '登录已失效，请重新登录')
      hasCheckedAuth.value = true
      return false
    }).finally(() => { if (pendingCheck === task) pendingCheck = undefined })
    pendingCheck = task; return task
  }
  const recheck = () => { clearSession('浏览器登录状态已变化，正在重新确认身份'); checkAuth() }
  onIdentitySignal(recheck)
  globalThis.addEventListener?.('doorhandle-account-recheck', checkAuth)
  globalThis.addEventListener?.('focus', checkAuth)
  globalThis.document?.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') checkAuth() })
  request.interceptors.response.use(response => response, error => {
    if (error.response?.status === 401 && !error.config?._accountAuth && accountSession.current(error.config?._accountStamp)) clearSession('登录已失效，请重新登录')
    return Promise.reject(error)
  })
  const login = async form => {
    clearSession('正在确认登录账号'); identityChanged()
    try {
      const response = await request.post('/api/auth/login', form)
      if (response.data?.code !== 200) throw new Error(response.data?.message || '登录失败')
      if (!await checkAuth()) throw new Error('登录身份未确认，请重试')
      identityChanged(); return { username: username.value }
    } catch (error) { throw new Error(loginErrorMessage(error)) }
  }
  const logout = async () => {
    const context = accountSession.state.accountContext
    clearSession('已退出本页面，正在撤销服务器会话'); identityChanged()
    try { await request.post('/api/auth/logout', null, { headers: { 'X-Account-Context': context } }); accountNotice.value = '当前登录会话已退出' }
    catch { accountNotice.value = '本页面已退出；服务器撤销尚未确认，请重新登录后核对' }
    finally { identityChanged() }
  }
  return { username, role, identity, userId, accountContext, accountEpoch, accountNotice, capabilities, displayCacheAvailable,
    isAuthenticated, hasCheckedAuth, login, logout, checkAuth, clearSession,
    initializeAuthHeader: () => { isAuthenticated.value = false } }
})
