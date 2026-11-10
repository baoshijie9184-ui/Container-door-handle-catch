import { onBeforeUnmount, ref, unref } from 'vue'
import { accountSession } from '../utils/accountContext'
import { createRealtimeChanges } from '../utils/realtimeChanges'
import { useUserStore } from '../stores/user'
let hub
export function realtimeHub() {
  if (!hub) hub = createRealtimeChanges({ session: accountSession, checkAuth: () => useUserStore().checkAuth() })
  return hub
}
export function useResourceChanges({ resourceType, resourceId, domains, isEditing = () => false, refresh, revalidate } = {}) {
  const changed = ref(false), change = ref(null), connection = ref('closed')
  const source = realtimeHub()
  const statusOff = source.subscribeStatus(value => { connection.value = value })
  let refreshing = false, queued = false, timer, disposed = false
  const reread = async () => {
    if (disposed) return
    if (refreshing) { queued = true; return }
    refreshing = true
    try {
      await revalidate?.()
      if(disposed)return
      if (isEditing() || !refresh) { changed.value = true; return }
      await refresh(); if (!disposed) changed.value = false
    } catch { if (!disposed) changed.value = true }
    finally { refreshing = false; if (queued && !disposed) { queued = false; timer = setTimeout(reread, 250) } }
  }
  const off = source.subscribe(event => {
    if (document.visibilityState === 'hidden') return
    if (event.type !== 'resync-required') {
      if (unref(resourceType) && event.resourceType !== unref(resourceType)) return
      if (unref(resourceId) && event.resourceId !== String(unref(resourceId))) return
      if (domains && !domains.includes(event.domain)) return
    }
    change.value = event
    if (isEditing()) changed.value = true
    clearTimeout(timer); timer = setTimeout(reread, 250)
  })
  source.start()
  onBeforeUnmount(() => { disposed = true; off(); statusOff(); clearTimeout(timer); queued = false })
  return { changed, change, connection, refreshLatest: async () => { await refresh?.(); changed.value = false } }
}
