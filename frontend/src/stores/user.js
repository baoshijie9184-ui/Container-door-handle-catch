import { defineStore } from 'pinia'
import { ref } from 'vue'
import request from '../api/request'
import { ElMessage } from 'element-plus'
import router from '../router'
import { loginErrorMessage } from '../utils/loginError'
import { readAccountPreference, writeAccountPreference } from '../utils/accountPreferences'

export const useUserStore = defineStore('user', () => {
  const usernameHint = readAccountPreference('username')
  const roleHint = readAccountPreference('role')
  const username = ref(usernameHint.value || '')
  const role = ref(roleHint.value || 'INSPECTOR')
  const displayCacheAvailable = ref(usernameHint.available && roleHint.available)
  const saveDisplayHint = (key, value) => {
    if (!writeAccountPreference(key, value)) displayCacheAvailable.value = false
  }
  const identity = ref(null)
  const isAuthenticated = ref(false)
  const hasCheckedAuth = ref(false)
  let redirectingToLogin = false

  const clearSession = () => {
    username.value = ''
    role.value = 'INSPECTOR'
    identity.value = null
    isAuthenticated.value = false
    hasCheckedAuth.value = true
    saveDisplayHint('username', null)
    saveDisplayHint('role', null)
  }

  // Cookie-only 登录态由后端 HttpOnly Cookie 保存，前端只维护显示状态。
  const initializeAuthHeader = () => {
    isAuthenticated.value = false
  }

  // 添加axios响应拦截器处理认证错误
  request.interceptors.response.use(
    response => response,
    error => {
      console.error('请求错误:', error.response?.status, error.message)
      const requestUrl = error.config?.url || ''
      const isAuthEndpoint = ['/api/auth/login', '/api/auth/logout', '/api/auth/check'].includes(requestUrl)
      if (error.response?.status === 401 && !isAuthEndpoint) {
        clearSession()
        if (!redirectingToLogin && router.currentRoute.value.name !== 'login') {
          redirectingToLogin = true
          ElMessage.warning('登录已过期，请重新登录')
          router.push('/login').finally(() => {
            redirectingToLogin = false
          })
        }
      }
      return Promise.reject(error)
    }
  )

  // 调用初始化方法
  initializeAuthHeader()

  const login = async (loginForm) => {
    try {
      const response = await request.post('/api/auth/login', loginForm)
      
      if (!response.data || response.data.code !== 200) {
        throw new Error(response.data?.message || '登录失败')
      }
      
      const responseData = response.data.data
      if (!responseData || !responseData.username) {
        throw new Error('登录失败，未获取到有效的用户信息')
      }
      
      const newUsername = responseData.username || loginForm.username
      
      username.value = newUsername
      isAuthenticated.value = true
      hasCheckedAuth.value = true
      redirectingToLogin = false
      
      saveDisplayHint('username', newUsername)

      // 登录后向服务端刷新角色和员工身份，避免沿用上一账号的缓存角色。
      await checkAuth()
      if (!isAuthenticated.value) throw new Error('登录状态验证失败，请重试')

      return {
        username: newUsername
      }
    } catch (error) {
      console.error('登录错误:', error)
      throw new Error(loginErrorMessage(error))
    }
  }

  const logout = async () => {
    try {
      await request.post('/api/auth/logout')
    } catch {
      // 本地登录态仍需清理，避免网络故障阻止用户退出。
    } finally {
      clearSession()
    }
  }

  // 通过 HttpOnly Cookie 向后端确认登录态，避免前端保存可读 token。
  const checkAuth = async () => {
    try {
      const response = await request.get('/api/auth/check')
      const data = response.data?.data || {}
      if (data.username) {
        username.value = data.username
        saveDisplayHint('username', data.username)
      }
      if (data.role) { role.value = data.role; saveDisplayHint('role', data.role) }
      identity.value = data.identity || null
      isAuthenticated.value = true
      hasCheckedAuth.value = true
      return true
    } catch (error) {
      if (error.response && error.response.status === 401) {
        clearSession()
      }
      isAuthenticated.value = false
      hasCheckedAuth.value = true
      return false
    }
  }

  return {
    username,
    role,
    identity,
    displayCacheAvailable,
    isAuthenticated,
    hasCheckedAuth,
    login,
    logout,
    initializeAuthHeader,
    checkAuth
  }
}) 
