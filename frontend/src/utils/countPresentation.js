// Missing statistics are unknown, including when a successful response omits a field.
export function knownCount(value) {
  if (typeof value !== 'number' && typeof value !== 'string') return null
  if (typeof value === 'string' && !value.trim()) return null
  const count = Number(value)
  return Number.isSafeInteger(count) && count >= 0 ? count : null
}
