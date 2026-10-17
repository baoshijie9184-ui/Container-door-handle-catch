// Research material is untrusted plain text. Only explicit IDs and exact answer hashes establish associations.
const sourceId = /^src-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const digest = /^[0-9a-f]{64}$/
const integer = (value, max) => Number.isSafeInteger(value) && value >= 0 && value <= max
export function researchExportError(error) {
  if (error?.response?.status === 429) {
    const value = error.response.headers?.['retry-after']
    const seconds = typeof value === 'string' && /^\d{1,4}$/.test(value) ? Number(value) : 0
    return seconds >= 1 && seconds <= 3600
      ? `本账号导出过于频繁，请等待约 ${seconds} 秒后重新确认；不会自动重试。`
      : '本账号导出过于频繁，请稍后重新确认；不会自动重试。'
  }
  return '来源文件未保存或结果未确认，服务端可能已记录导出审计。请通过 HTTPS 或本机隧道访问，核对后再确认重试；不会自动重试。'
}
export function researchUrl(value) {
  try {
    const url = new URL(value)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || !url.hostname.includes('.')) return null
    const host = url.hostname.toLowerCase()
    if (host === 'localhost' || host.endsWith('.local') || host.endsWith('.localhost')) return null
    if (/^(0|10|127|169\.254|192\.168)\./.test(host) || /^172\.(1[6-9]|2\d|3[01])\./.test(host)) return null
    return url.href
  } catch { return null }
}
export function normalizeResearchEvidence(value, runId) {
  if (value?.runId !== runId || typeof value.enabled !== 'boolean' || !Array.isArray(value.sources) || value.sources.length > 20 || !Array.isArray(value.citations) || value.citations.length > 200) throw new Error('INVALID_EVIDENCE')
  const seen = new Set()
  const sources = value.sources.map(row => {
    if (!sourceId.test(row?.sourceId) || seen.has(row.sourceId) || row.runId !== runId || !digest.test(row.contentSha256)
      || typeof row.requestedUrl !== 'string' || row.requestedUrl.length > 2048 || !researchUrl(row.requestedUrl)
      || typeof row.queryOmitted !== 'boolean' || typeof row.urlRedacted !== 'boolean'
      || typeof row.title !== 'string' || row.title.length > 160 || typeof row.excerpt !== 'string' || row.excerpt.length > 1000
      || typeof row.callId !== 'string' || row.callId.length > 160 || !integer(row.textChars, 50000)
      || !integer(row.startIndex, 1000000) || !integer(row.maxLength, 20000) || row.maxLength < 1
      || typeof row.fetchedAt !== 'string' || !Number.isFinite(Date.parse(row.fetchedAt))
      || typeof row.expiresAt !== 'string' || !Number.isFinite(Date.parse(row.expiresAt))) throw new Error('INVALID_SOURCE')
    seen.add(row.sourceId)
    return { sourceId: row.sourceId, runId, callId: row.callId, requestedUrl: row.requestedUrl,
      queryOmitted: row.queryOmitted, urlRedacted: row.urlRedacted, title: row.title, excerpt: row.excerpt,
      contentSha256: row.contentSha256, textChars: row.textChars, startIndex: row.startIndex, maxLength: row.maxLength,
      fetchedAt: row.fetchedAt, expiresAt: row.expiresAt, href: row.urlRedacted ? null : researchUrl(row.requestedUrl) }
  })
  let previousEnd = 0
  const citations = value.citations.map(row => {
    if (!sourceId.test(row?.sourceId) || !integer(row.start, 200000) || !integer(row.end, 200000) || row.end <= row.start || row.start < previousEnd) throw new Error('INVALID_CITATION')
    previousEnd = row.end
    return { sourceId: row.sourceId, start: row.start, end: row.end }
  })
  if (typeof value.answerRecorded !== 'boolean' || (value.answerRecorded && !digest.test(value.answerSha256))
    || (!value.answerRecorded && (citations.length || value.answerSha256 != null))
    || !integer(value.unresolvedCitationCount, 200) || !integer(value.expiredSourceCount, 20)
    || (!value.enabled && (sources.length || citations.length || value.answerRecorded))) throw new Error('INVALID_ANSWER_REFERENCE')
  return { runId, enabled: value.enabled, exportEnabled: value.enabled && value.exportEnabled === true, sources, citations, answerSha256: value.answerSha256 || null,
    answerRecorded: value.answerRecorded, unresolvedCitationCount: value.unresolvedCitationCount, expiredSourceCount: value.expiredSourceCount }
}
// Validate exact downloaded bytes before saving; the audit hash is not a digital signature.
export async function validateResearchDownload(response, runId, subtle = globalThis.crypto?.subtle) {
  const bytes = response?.data
  if (!(bytes instanceof ArrayBuffer) || bytes.byteLength < 1 || bytes.byteLength > 524288 || !subtle) throw new Error('INVALID_EXPORT')
  const file = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes))
  const id = response.headers?.['x-export-id'], hash = response.headers?.['x-content-sha256']
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id)
    || !digest.test(hash) || file.version !== 1 || file.exportId !== id
    || typeof file.exportedAt !== 'string' || !Number.isFinite(Date.parse(file.exportedAt))) throw new Error('INVALID_EXPORT')
  const evidence = normalizeResearchEvidence(file.evidence, runId)
  if (!evidence.enabled) throw new Error('INVALID_EXPORT')
  const actual = Array.from(new Uint8Array(await subtle.digest('SHA-256', bytes)), value => value.toString(16).padStart(2, '0')).join('')
  if (actual !== hash) throw new Error('INVALID_EXPORT_HASH')
  return { filename: `research-${id}.json`, sha256: hash, bytes }
}
export async function citationContext(evidence, candidates, subtle = globalThis.crypto?.subtle) {
  if (!evidence?.answerRecorded || !subtle || !Array.isArray(candidates)) return null
  for (const text of candidates) {
    if (typeof text !== 'string' || text.length > 200000) continue
    const hash = Array.from(new Uint8Array(await subtle.digest('SHA-256', new TextEncoder().encode(text))), value => value.toString(16).padStart(2,'0')).join('')
    if (hash !== evidence.answerSha256) continue
    let cursor = 0
    const segments = []
    for (const ref of evidence.citations) {
      if (text.slice(ref.start, ref.end) !== `[source:${ref.sourceId}]` || ref.start < cursor) throw new Error('INVALID_CITATION_POSITION')
      if (ref.start > cursor) segments.push({ text: text.slice(cursor, ref.start) })
      segments.push({ text: text.slice(ref.start, ref.end), sourceId: ref.sourceId })
      cursor = ref.end
    }
    if (cursor < text.length) segments.push({ text: text.slice(cursor) })
    return { segments }
  }
  return null
}
