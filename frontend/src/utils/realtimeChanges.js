// One EventSource per account/browser origin where Web Locks + BroadcastChannel exist.
// Browsers without cross-tab arbitration use polling, with a zero-SSE connection budget.
export function createRealtimeChanges({ session, checkAuth, url = '/api/realtime/changes',
  environment = globalThis, now = () => Date.now() }) {
  const subscribers = new Set(), statuses = new Set(), seen = new Map(), versions = new Map()
  let stream, relay, releaseLock, lockPending = false, timer, context = '', lastEvent = 0, lastValidation = 0
  let status = 'closed', stopped = true, leader = false, generation = 0, checking, rebuilding = false, suspended = false
  let shared = !!(environment.navigator?.locks && environment.BroadcastChannel)
  const enabled = () => shared && !!environment.EventSource && session.state.user?.capabilities?.realtime === true
    && session.state.user?.capabilities?.sessionTracking === true
  function setStatus(value, broadcast = true) {
    status = value; statuses.forEach(fn => fn(value))
    if (broadcast && leader) relay?.postMessage({ kind: 'status', context, status: value, at: now() })
  }
  function notify(value) { subscribers.forEach(fn => fn(value)) }
  function resync(reason) { notify({ type: 'resync-required', reason }) }
  function accept(type, data) {
    if (!data || data.accountContext !== context) return
    lastEvent = now()
    if (type === 'heartbeat') { setStatus('connected', false); return }
    if (type === 'resync-required') { resync(data?.reason || 'reconnected'); return }
    if (type !== 'resource-changed') return
    if (data.schemaVersion != null && data.schemaVersion !== 1 || !data.eventId || !data.resourceType || !data.resourceId) { resync('unknown-event'); return }
    const id = String(data.eventId)
    if (seen.has(id)) return
    seen.set(id, true); if (seen.size > 512) seen.delete(seen.keys().next().value)
    const key = JSON.stringify([data.resourceType, data.resourceId]), version = data.resourceVersion ?? data.afterVersion
    if (version != null && /^\d+$/.test(String(version))) {
      const incoming = BigInt(version), previous = versions.get(key)
      if (previous !== undefined && incoming <= previous) return
      if (previous !== undefined && incoming > previous + 1n) resync('version-gap')
      versions.set(key, incoming); if (versions.size > 512) versions.delete(versions.keys().next().value)
    } else resync('unknown-version')
    // Notification payloads are locators. They are never applied to a form or treated as write receipts.
    notify({ ...data, type })
  }
  async function authenticate() {
    if (!checking) checking = Promise.resolve().then(checkAuth).finally(() => { checking = null })
    return checking
  }
  function closeStream() { stream?.close(); stream = undefined }
  function connect() {
    if (stopped || suspended || !enabled() || !leader || stream || !session.state.authenticated || session.state.accountContext !== context) return
    const stamp = generation
    lastEvent = now(); setStatus('connecting')
    const source = new environment.EventSource(url, { withCredentials: true }); stream = source
    source.onopen = () => { if (stamp === generation && source === stream) setStatus('connected') }
    for (const type of ['resource-changed', 'heartbeat', 'resync-required']) source.addEventListener(type, event => {
      if (stamp !== generation || source !== stream) return
      let data
      try { data = JSON.parse(event.data) } catch { resync('invalid-event'); return }
      accept(type, data); relay?.postMessage({ kind: 'event', context, type, data })
    })
    source.onerror = async () => {
      if (stamp !== generation || source !== stream) return
      setStatus('reconnecting')
      // EventSource hides the HTTP status. An ordinary authenticated read decides validity.
      await authenticate().catch(() => false)
      if (stamp !== generation) return
      if (!session.state.authenticated || session.state.accountContext !== context) stop()
      else if (source.readyState === 2) { suspended = true; closeStream(); setStatus('unavailable') }
      // A healthy account uses EventSource's own reconnect; no second retry timer.
    }
  }
  async function elect() {
    if (stopped || suspended || !enabled() || lockPending || leader) return
    if (!shared) { leader = true; connect(); return }
    lockPending = true
    const stamp = generation, expected = context
    try {
      await environment.navigator.locks.request('doorhandle-changes:' + expected, { ifAvailable: true }, async lock => {
        if (!lock || stopped || stamp !== generation) return
        leader = true; connect()
        await new Promise(resolve => { releaseLock = resolve })
      })
    } catch {
      if (stamp === generation) { shared = false; closeStream(); relay?.close(); relay = undefined; setStatus('polling', false) }
    } finally { if (stamp === generation) { lockPending = false; leader = false } }
  }
  async function tick() {
    if (stopped) return
    if (!leader) elect()
    if (leader) relay?.postMessage({ kind: 'status', context, status, at: now() })
    if (enabled() && !suspended && now() - lastEvent >= 60000 && !rebuilding) {
      rebuilding = true; setStatus('reconnecting')
      const stamp = generation
      try { await authenticate().catch(() => false); if (stamp === generation && leader) { closeStream(); connect() } }
      finally { rebuilding = false }
    }
    if (environment.document?.visibilityState !== 'hidden' && now() - lastValidation >= 30000) {
      lastValidation = now(); await authenticate().catch(() => false); if (!stopped) resync('visible-validation')
    }
  }
  function stop() {
    stopped = true; generation++; closeStream(); releaseLock?.(); releaseLock = undefined
    relay?.close(); relay = undefined; leader = false; lockPending = false; checking = undefined
    environment.clearInterval(timer); timer = undefined; context = ''; seen.clear(); versions.clear(); setStatus('closed', false)
  }
  function start() {
    const next = session.state.accountContext
    if (!session.state.authenticated || !next) { stop(); return }
    if (!stopped && context === next) {
      if (!enabled() && status !== 'polling') { stop(); start() }
      else if (enabled() && status === 'polling') { stop(); start() }
      return
    }
    stop(); stopped = false; suspended = false; context = next; lastEvent = now(); lastValidation = now()
    if (shared && enabled()) {
      relay = new environment.BroadcastChannel('doorhandle-changes:' + context)
      relay.onmessage = event => {
        if (stopped || event.data?.context !== context) return
        if (event.data.kind === 'event') accept(event.data.type, event.data.data)
        if (event.data.kind === 'status' && !leader) { lastEvent = now(); setStatus(event.data.status, false) }
      }
    }
    setStatus(enabled() ? 'connecting' : 'polling'); elect(); timer = environment.setInterval(tick, 5000)
  }
  const unsubscribe = session.subscribe(start)
  const visible = async () => {
    if (environment.document?.visibilityState === 'hidden' || stopped) return
    await authenticate().catch(() => false); if (!stopped) { resync('visible'); tick() }
  }
  environment.addEventListener?.('online', visible)
  environment.addEventListener?.('focus', visible)
  environment.document?.addEventListener('visibilitychange', visible)
  return {
    start, stop, tick, retry() { suspended = false; if (leader) connect(); else elect() }, get status() { return status }, get shared() { return shared },
    subscribe(fn) { subscribers.add(fn); return () => subscribers.delete(fn) },
    subscribeStatus(fn) { statuses.add(fn); fn(status); return () => statuses.delete(fn) },
    dispose() { stop(); unsubscribe(); subscribers.clear(); statuses.clear(); environment.removeEventListener?.('online', visible); environment.removeEventListener?.('focus', visible); environment.document?.removeEventListener('visibilitychange', visible) },
  }
}
