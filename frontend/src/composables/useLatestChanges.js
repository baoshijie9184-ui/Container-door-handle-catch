import { ref, unref, watch } from 'vue'
import { captureAccountRequest } from '../api/request'
import { useUserStore } from '../stores/user'
import { useAccountOperationScope } from './useAccountOperationScope'
import { useResourceChanges } from './useResourceChanges'

// Page-sized authorized metadata only. Never retain another account's historical identity.
export function useLatestChanges(records, resourceType, domain = resourceType, idField = 'id') {
  const latest = ref({}), user = useUserStore(), request = captureAccountRequest()
  const scope = useAccountOperationScope(() => { latest.value = {} }), reads = scope.channel()
  async function refresh() {
    const token = reads.begin()
    latest.value = {}
    if (!user.isAuthenticated || user.capabilities?.changeHistory !== true) return
    const type = unref(resourceType), area = unref(domain) || type
    if (!type || !area) return
    const keys = [...new Set((unref(records) || []).map(row => String(row[idField])))].slice(0, 100)
    if (!keys.length) return
    try {
      const response = await request.post('/api/operations/audit/changes/latest',
        keys.map(resourceId => ({ domain:area, resourceType:type, resourceId })), { signal: token.signal })
      if (!reads.current(token)) return
      const rows = response.data?.code === 200 ? response.data.data : response.data
      const seen = new Set(), allowed = new Set(keys)
      if (!Array.isArray(rows) || rows.some(row => {
        const key = row?.resource
        if (!key || key.domain !== area || key.resourceType !== type || !allowed.has(key.resourceId) || seen.has(key.resourceId)) return true
        seen.add(key.resourceId)
        return row.latest != null && (typeof row.latest.id !== 'string' || row.latest.resourceType !== type || row.latest.resourceId !== key.resourceId)
      })) throw new Error('最近修改记录返回不完整')
      latest.value = Object.fromEntries(rows.map(row => [row.resource.resourceId, row.latest]))
    } catch {
      if (reads.current(token)) latest.value = {}
    }
  }
  watch([() => unref(records), () => unref(resourceType), () => unref(domain), () => user.capabilities?.changeHistory, () => user.accountContext, () => user.accountEpoch], refresh, { immediate: true })
  // This channel updates only authorized metadata. An open business editor keeps
  // its original draft, expected version and command ID while summaries advance.
  useResourceChanges({ resourceType, refresh })
  return { latest, refresh }
}
