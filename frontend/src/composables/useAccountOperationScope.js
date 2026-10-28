import { onBeforeUnmount, watch } from 'vue'
import { useUserStore } from '../stores/user'

// Read requests may be cancelled. Writes keep their request IDs and are never replayed here.
export function useAccountOperationScope(reset) {
  const user = useUserStore(), controllers = new Set()
  const owner = () => JSON.stringify([user.username, user.role, user.identity?.userId, user.isAuthenticated])
  let epoch = 0, disposed = false
  const stamp = () => ({ epoch, owner: owner() })
  const current = value => !disposed && value.epoch === epoch && value.owner === owner()
  const stop = () => { epoch++; controllers.forEach(controller => controller.abort()); controllers.clear() }
  watch(owner, () => { stop(); reset?.() }, { flush: 'sync' })
  onBeforeUnmount(() => { disposed = true; stop() })
  function channel() {
    let sequence = 0, controller
    return {
      begin() { if (controller) { controller.abort(); controllers.delete(controller) }; controller = new AbortController(); controllers.add(controller); return { ...stamp(), sequence: ++sequence, signal: controller.signal } },
      current(value) { return current(value) && value.sequence === sequence && !value.signal.aborted }
    }
  }
  return { stamp, current, channel }
}
