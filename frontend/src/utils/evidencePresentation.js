// Pair by an exact, unique image name. Do not infer a match from order or filename prefixes.
export function evidenceComparisonPairs(originals = [], annotations = []) {
  const buckets = new Map()
  for (const [side, images] of [['original', originals], ['annotation', annotations]]) {
    for (const [index, image] of (Array.isArray(images) ? images : []).entries()) {
      if (!image || typeof image !== 'object') continue
      const name = typeof image.imageName === 'string' && image.imageName.trim() ? image.imageName : ''
      const key = name ? 'name:' + name : side + ':' + index
      if (!buckets.has(key)) buckets.set(key, { name, original: [], annotation: [] })
      buckets.get(key)[side].push(image)
    }
  }
  const pairs = []
  for (const bucket of buckets.values()) {
    const ambiguous = bucket.original.length > 1 || bucket.annotation.length > 1
    if (ambiguous) {
      for (const side of ['original', 'annotation']) for (const [index, image] of bucket[side].entries()) {
        pairs.push({ name: bucket.name, [side]: image, singleSide: side, ordinal: index + 1, ambiguous: true })
      }
    } else pairs.push({ name: bucket.name, original: bucket.original[0], annotation: bucket.annotation[0], ambiguous: false })
  }
  return pairs.map((pair, index) => ({ ...pair, key: String(index), label: (pair.name || '名称未记录') + (pair.ambiguous ? `（${pair.singleSide === 'original' ? '原图' : '标注图'} ${pair.ordinal}，同名未匹配）` : '') }))
}

export function evidencePreviewUrl(image) {
  for (const candidate of [image?.previewUrl,image?.annotatedUrl]) {
    if (typeof candidate !== 'string' || !candidate.trim()) continue
    const value=candidate.trim()
    try {
      const url=new URL(value,globalThis.location?.href || 'http://localhost/')
      if (['http:','https:'].includes(url.protocol) && !url.username && !url.password) return value
    } catch { /* A malformed display address does not become a link. */ }
  }
  return ''
}
