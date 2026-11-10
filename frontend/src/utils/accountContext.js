// Public accountContext detects stale pages. Only the HttpOnly cookie authenticates.
export function contextError(message = '登录账号已变化，请核对当前身份后重新打开页面') {
  return Object.assign(new Error(message), { code: 'ACCOUNT_CONTEXT_CHANGED', accountContextChanged: true })
}

export function createAccountContext() {
  let state = { epoch: 0, accountContext: '', authenticated: false, blocked: true, reason: '', user: null }
  let controller = new AbortController()
  const listeners = new Set(), resets = new Set()
  const publish = () => listeners.forEach(fn => fn({ ...state }))
  const identityScope = user => JSON.stringify(['bindingVersion','employeeId','employeeStatus','employeeType','departmentId','dataScope'].map(key=>user?.identity?.[key] ?? null))
  function clear(reason = '') {
    controller.abort(); controller = new AbortController()
    state = { epoch: state.epoch + 1, accountContext: '', authenticated: false, blocked: true, reason, user: null }
    resets.forEach(fn => fn()); publish()
    return state.epoch
  }
  return {
    get state() { return { ...state } },
    stamp() { return { epoch: state.epoch, accountContext: state.accountContext, signal: controller.signal } },
    current(stamp) { return stamp?.epoch === state.epoch && stamp?.accountContext === state.accountContext && !stamp.signal?.aborted },
    clear,
    accept(data, expectedEpoch = state.epoch) {
      if (expectedEpoch !== state.epoch) throw contextError()
      if (!data?.username || data.authenticated === false || !['SUPERVISOR', 'INSPECTOR'].includes(data.role)
          || data.accountContext != null && (typeof data.accountContext !== 'string' || data.accountContext.length > 256)) {
        clear('服务器尚未确认有效的账号上下文，已暂停业务操作')
        throw contextError('服务器尚未确认有效的账号上下文，已暂停业务操作')
      }
      const changed = state.authenticated && (state.accountContext !== (data.accountContext || '')
        || state.user?.role !== data.role || state.user?.username !== data.username || state.user?.userId !== data.userId
        || identityScope(state.user) !== identityScope(data))
      if (changed) clear('登录账号已变化，旧页面数据和未提交表单已清除')
      state = { ...state, accountContext: data.accountContext || '', authenticated: true, blocked: !data.accountContext,
        reason: data.accountContext ? state.reason : '当前服务器未确认安全账号上下文，允许读取，已暂停修改操作', user: data }
      publish(); return { ...state }
    },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn) },
    onReset(fn) { resets.add(fn); return () => resets.delete(fn) },
    assert(stamp) { if (!this.current(stamp)) throw contextError() },
  }
}

export const accountSession = createAccountContext()
const listeners = new Set()
let channel
function broadcastIdentity() {
  const message = { type: 'identity-invalidated', nonce: globalThis.crypto?.randomUUID?.() || String(Date.now()) }
  if (channel) channel.postMessage(message)
  else { try { globalThis.localStorage?.setItem('doorhandle-identity-signal', JSON.stringify(message)) } catch { /* Focus checks remain available. */ } }
}
if (typeof window !== 'undefined') {
  if (typeof BroadcastChannel !== 'undefined') {
    channel = new BroadcastChannel('doorhandle-account-context-v1')
    channel.onmessage = event => { if (event.data?.type === 'identity-invalidated') listeners.forEach(fn => fn()) }
  }
  window.addEventListener('storage', event => { if (event.key === 'doorhandle-identity-signal') listeners.forEach(fn => fn()) })
}
export function identityChanged() { broadcastIdentity() }
export function onIdentitySignal(fn) { listeners.add(fn); return () => listeners.delete(fn) }

// A caller's cancellation and the account lifetime both own a request/stream.
export function accountSignal(signal, lifetime) {
  if (!signal) return lifetime
  if (typeof AbortSignal.any === 'function') return AbortSignal.any([signal, lifetime])
  const merged = new AbortController()
  const abort = () => merged.abort()
  if (signal.aborted || lifetime.aborted) abort()
  else { signal.addEventListener('abort', abort, { once: true }); lifetime.addEventListener('abort', abort, { once: true }) }
  return merged.signal
}
