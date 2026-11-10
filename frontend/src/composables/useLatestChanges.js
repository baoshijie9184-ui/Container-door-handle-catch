import { ref, unref, watch } from 'vue'
import { captureAccountRequest } from '../api/request'
import { useUserStore } from '../stores/user'
import { useAccountOperationScope } from './useAccountOperationScope'

// Page-sized authorized metadata only. Never retain another account's historical identity.
export function useLatestChanges(records, resourceType, domain = resourceType, idField = 'id') {
  const latest = ref({}), user = useUserStore(), request = captureAccountRequest()
  const scope = useAccountOperationScope(() => { latest.value = {} }), reads = scope.channel()
  async function refresh() {
    const token = reads.begin()
    latest.value = {}
    if (!user.isAuthenticated || user.capabilities?.changeHistory !== true) return
    const keys = [...new Set((unref(records) || []).map(row => String(row[idField])))].slice(0, 100)
    if (!keys.length) return
    try {
      const response = await request.post('/api/operations/audit/changes/latest',
        keys.map(resourceId => ({ domain, resourceType, resourceId })), { signal: token.signal })
      if (!reads.current(token)) return
      const rows = response.data?.code === 200 ? response.data.data : response.data
      const seen = new Set(), allowed = new Set(keys)
      if (!Array.isArray(rows) || rows.some(row => {
        const key = row?.resource
        if (!key || key.domain !== domain || key.resourceType !== resourceType || !allowed.has(key.resourceId) || seen.has(key.resourceId)) return true
        seen.add(key.resourceId)
        return row.latest != null && (typeof row.latest.id !== 'string' || row.latest.resourceType !== resourceType || row.latest.resourceId !== key.resourceId)
      })) throw new Error('最近修改记录返回不完整')
      latest.value = Object.fromEntries(rows.map(row => [row.resource.resourceId, row.latest]))
    } catch {
      if (reads.current(token)) latest.value = {}
    }
  }
  watch([() => unref(records), () => user.capabilities?.changeHistory, () => user.accountContext, () => user.accountEpoch], refresh, { immediate: true })
  return { latest, refresh }
}
