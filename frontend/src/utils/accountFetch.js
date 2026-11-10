import { accountSession, accountSignal, contextError } from './accountContext'
import { createUiRequestId } from './requestIdentity'

const nativeFetch = (...args) => globalThis.fetch(...args)
export async function accountFetch(input, options = {}) {
  const url = new URL(typeof input === 'string' ? input : input.url, globalThis.location?.href || 'http://localhost')
  const auth = /^\/api\/auth\/(check|login|refresh|logout)$/.test(url.pathname)
  const stamp = accountSession.stamp()
  if (!auth && !accountSession.state.authenticated) throw contextError()
  const headers = new Headers(options.headers || (typeof input !== 'string' ? input.headers : undefined))
  const method = (options.method || (typeof input !== 'string' ? input.method : 'GET') || 'GET').toUpperCase()
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    if (!auth && !stamp.accountContext) throw contextError('当前服务器尚未提供安全账号上下文，请更新登录身份后再修改')
    if (stamp.accountContext) headers.set('X-Account-Context', stamp.accountContext)
    let requestId
    if (typeof options.body === 'string') { try { requestId = JSON.parse(options.body)?.requestId } catch { /* Multipart/raw bodies use a header. */ } }
    if (!headers.has('X-Request-ID')) headers.set('X-Request-ID', requestId || createUiRequestId())
  }
  const response = await nativeFetch(input, { ...options, headers, credentials: 'include',
    signal: auth ? options.signal : accountSignal(options.signal, stamp.signal) })
  if (!auth) accountSession.assert(stamp)
  if (!auth && response.status === 401) {
    accountSession.clear('登录已失效，请重新登录')
    globalThis.dispatchEvent?.(new Event('doorhandle-account-recheck'))
  }
  if (!auth && response.status === 409) {
    const data = await response.clone().json().catch(() => null)
    if (data?.code === 'ACCOUNT_CONTEXT_CHANGED') { accountSession.clear('登录账号已变化，请重新确认身份'); throw contextError() }
  }
  return response
}
