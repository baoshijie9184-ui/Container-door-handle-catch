import { shallowRef } from 'vue'

// Kept in memory only. Do not put route queries, error bodies or credentials in the notice.
export const navigationFailure = shallowRef(null)
let failureSequence = 0
let failedDestination = ''

export function isRouteAssetError(error) {
  return /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Unable to preload CSS for/i.test(error?.message || '')
}

// Replace the hash without notifying the old router, then fetch a fresh entry document.
export function reloadRoute(router, destination) {
  const { fullPath } = router.resolve(destination)
  window.history.replaceState(null, '', '#' + fullPath)
  window.location.reload()
}

export function recordNavigationFailure(to, error) {
  failedDestination = typeof to?.fullPath === 'string' && to.fullPath.startsWith('/') && !to.fullPath.startsWith('//') ? to.fullPath : ''
  navigationFailure.value = {
    id: ++failureSequence,
    title: typeof to?.meta?.title === 'string' ? to.meta.title : '目标页面',
    canRetry: !!failedDestination,
    requiresReload: isRouteAssetError(error),
    retrying: false
  }
}

export function clearNavigationFailure() {
  navigationFailure.value = null
  failedDestination = ''
}

export async function retryNavigation(router) {
  const failure = navigationFailure.value
  if (!failure?.canRetry || failure.retrying || !failedDestination) return
  const destination = failedDestination
  navigationFailure.value = { ...failure, retrying: true }
  try {
    if (failure.requiresReload) {
      reloadRoute(router, destination)
      return
    }
    await router.push(destination)
  } catch {
    // router.onError owns the next notice; do not retry or replay any business operation.
  } finally {
    if (navigationFailure.value?.id === failure.id) {
      navigationFailure.value = { ...navigationFailure.value, retrying: false }
    }
  }
}
