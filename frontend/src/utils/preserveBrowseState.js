// Automatic reads must not move a reader's place or undo a newer user action.
export async function preserveBrowseState(read, { documentRef = globalThis.document, afterRender = async () => {}, isCurrent = () => true } = {}) {
  if (!documentRef) return read()
  const active = documentRef.activeElement
  const selection = typeof active?.selectionStart === 'number' && typeof active?.selectionEnd === 'number'
    ? { start: active.selectionStart, end: active.selectionEnd, direction: active.selectionDirection } : null
  const elements = [...new Set([documentRef.scrollingElement,
    ...Array.from(documentRef.querySelectorAll?.('.el-scrollbar__wrap, .el-dialog__body, .el-drawer__body, [role="region"], [data-collaboration-scroll], .layout-content') || []).slice(0, 64)])]
  const positions = elements.filter(element => element?.isConnected).map(element => ({ element, top: element.scrollTop, left: element.scrollLeft }))
  let interacted = false
  const view = documentRef.defaultView
  const url = () => view?.location?.href || documentRef.URL || ''
  const openedUrl = url()
  let navigationVersion = 0
  const navigated = () => { navigationVersion++ }
  for (const type of ['popstate', 'hashchange']) view?.addEventListener?.(type, navigated)
  view?.navigation?.addEventListener?.('currententrychange', navigated)
  const changed = () => { interacted = true }
  const events = ['pointerdown', 'wheel', 'touchmove', 'keydown', 'input']
  for (const type of events) documentRef.addEventListener(type, changed, { capture: true, passive: true })
  try {
    const result = await read()
    await afterRender()
    if (!interacted && navigationVersion === 0 && url() === openedUrl && isCurrent()) {
      const current = documentRef.activeElement
      if (active?.isConnected && (current === active || current === documentRef.body || current === documentRef.documentElement)) {
        if (current !== active) active.focus?.({ preventScroll: true })
        if (selection && documentRef.activeElement === active) {
          try { active.setSelectionRange(selection.start, selection.end, selection.direction) } catch { /* Non-text inputs have no selection range. */ }
        }
      }
      for (const { element, top, left } of positions) if (element.isConnected) {
        if (element.scrollTop !== top) element.scrollTop = top
        if (element.scrollLeft !== left) element.scrollLeft = left
      }
    }
    return result
  } finally {
    for (const type of events) documentRef.removeEventListener(type, changed, { capture: true })
    for (const type of ['popstate', 'hashchange']) view?.removeEventListener?.(type, navigated)
    view?.navigation?.removeEventListener?.('currententrychange', navigated)
  }
}
