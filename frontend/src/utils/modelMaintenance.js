// Labels and actions come from the same rule used in the backend's quality report.
export function maintenanceFor(summary, category) {
  if (typeof category !== 'string') return null
  const code = category.trim().toLowerCase()
  for (const group of summary?.groups || []) {
    const match = group.categories.find(item => item.code.toLowerCase() === code || item.label === code)
    if (match) return { category:match.label, action:group.label }
  }
  return null
}

export function imageMaintenance(summary, evidence, pair) {
  if (!pair || !Array.isArray(evidence)) return []
  const result = new Map()
  for (const target of evidence) {
    if (!target?.defectType) continue
    const original = pair.original?.objectKey, annotation = pair.annotation?.objectKey
    const comparable = (original && target.sourceKey) || (annotation && target.previewKey)
    const matches = comparable
      ? (original && original === target.sourceKey) || (annotation && annotation === target.previewKey)
      : !pair.ambiguous && pair.name && target.imageName === pair.name
    if (!matches) continue
    const match = maintenanceFor(summary,target.defectType)
    const label = match?.category || target.defectType
    const row = result.get(label) || { label, action:match?.action || '待核对', count:0 }
    row.count++
    result.set(label,row)
  }
  return [...result.values()]
}
