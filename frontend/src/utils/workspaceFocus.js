const tabStops = 'button, [href], input, select, textarea, summary, [tabindex], [contenteditable="true"]'

function isVisible(element) {
  return element.getClientRects().length > 0 && getComputedStyle(element).visibility === 'visible'
}

export function hasForegroundDialog(panel, target = document.activeElement) {
  const focusedDialog = target?.closest?.('[role="dialog"]')
  if (focusedDialog && !focusedDialog.contains(panel)) return true
  return Array.from(document.querySelectorAll('[role="dialog"][aria-modal="true"]')).some(dialog =>
    !dialog.contains(panel) && isVisible(dialog))
}

export function keepTabInWorkspace(event, panel) {
  const stops = Array.from(panel.querySelectorAll(tabStops)).filter(element =>
    (element.tabIndex >= 0 || element.matches('details > summary:first-of-type:not([tabindex])')) &&
    !element.matches(':disabled') && !element.closest('[inert]') && isVisible(element))
  const first = stops[0]
  const last = stops.at(-1)
  if (!first) return
  const focus = document.activeElement
  if (panel.contains(focus) && focus !== (event.shiftKey ? first : last)) return
  event.preventDefault()
  const next = event.shiftKey ? last : first
  next.focus()
}
