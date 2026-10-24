// Observe the existing transcript's layout only. Following is owned by the reader's UI state.
// No polling, message mutation, focus changes, smooth scrolling or business operations.
export function observeTranscriptLayout(viewport, { isFollowing, follow }) {
  if (!viewport || typeof ResizeObserver !== 'function') return () => {}
  let active = true, frame = null
  const observed = new Set()
  function schedule() {
    if (!active || frame !== null || !isFollowing()) return
    frame = requestAnimationFrame(() => {
      frame = null
      if (active && viewport.isConnected && isFollowing() && viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop > 1) follow()
    })
  }
  const resize = new ResizeObserver(schedule)
  resize.observe(viewport)
  function syncChildren() {
    if (!active) return
    const children = new Set(viewport.children)
    for (const child of observed) if (!children.has(child)) { resize.unobserve(child);observed.delete(child) }
    for (const child of children) if (!observed.has(child)) { observed.add(child);resize.observe(child) }
    schedule()
  }
  // Child sizes cover late images, Markdown layout and native disclosure changes.
  // Only direct child replacement needs mutation observation; avoid streaming text scans.
  const mutation = typeof MutationObserver === 'function' ? new MutationObserver(syncChildren) : null
  mutation?.observe(viewport, { childList: true })
  syncChildren()
  return () => {
    active = false
    resize.disconnect();mutation?.disconnect();observed.clear()
    if (frame !== null) cancelAnimationFrame(frame)
  }
}
