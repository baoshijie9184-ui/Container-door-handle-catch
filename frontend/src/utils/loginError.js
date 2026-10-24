export function loginErrorMessage(error) {
  const status = error?.response?.status
  if (status === 401) return '用户名或密码错误'
  if (status === 429) return '登录尝试次数过多，请稍后再试'
  if (status === 403) return '登录请求被拒绝，请检查访问地址或联系管理员'
  if (status >= 500) return '登录服务暂不可用，请检查后端服务及服务器连接后重试'
  if (error?.code === 'ECONNABORTED' || error?.code === 'ETIMEDOUT') return '登录请求超时，请检查网络连接后重试'
  if (error?.request && !error.response) return '无法连接登录服务，请检查网络及服务器连接'
  const message = error?.response?.data?.message
  if (typeof message === 'string' && message.trim()) return `登录失败: ${message}`
  if (status) return `登录请求失败（HTTP ${status}），请稍后重试`
  return error?.message || '登录失败，请稍后重试'
}
