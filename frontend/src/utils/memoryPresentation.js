import { businessDate, beijingDateTime } from './beijingTime'

export function memoryLifecycleCode(lifecycle, now = Date.now()) {
  if (!lifecycle) return 'UNKNOWN'
  if (lifecycle.cleanupState === 'SUCCEEDED') return 'REMOVED'
  if (lifecycle.expiresAt) {
    const expiry = businessDate(lifecycle.expiresAt)
    if (!expiry) return 'UNKNOWN'
    if (expiry.getTime() <= now) return 'EXPIRED'
  }
  if (lifecycle.state === 'EXCLUDED') return 'EXCLUDED'
  return lifecycle.state === 'ACTIVE' ? 'ACTIVE' : 'UNKNOWN'
}

export function memoryTime(value) { return value ? beijingDateTime(value) || '时间未记录' : '时间未记录' }
