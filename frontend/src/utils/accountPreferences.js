// These existing keys contain display hints only. Authentication stays in HttpOnly cookies.
const displayKeys = new Set(['username', 'role', 'rememberedUser'])
export function readAccountPreference(key) {
  if (!displayKeys.has(key)) return { available: false, value: null }
  try { return { available: true, value: window.localStorage.getItem(key) } }
  catch { return { available: false, value: null } }
}
export function writeAccountPreference(key, value) {
  if (!displayKeys.has(key)) return false
  try {
    if (value == null) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
    return true
  } catch { return false }
}
