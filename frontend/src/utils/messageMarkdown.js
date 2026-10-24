// Presentation-only Markdown subset. Consumers render text nodes, never model-supplied HTML.
// Raw HTML and images remain literal text; links never trigger requests during rendering.
export function messageLink(value) {
  if (typeof value !== 'string' || /[\s\u0000-\u001f\u007f]/.test(value)) return null
  if (/^\/?#\/[A-Za-z0-9/_?=&.%+\-]+$/.test(value)) return { href: value.replace(/^\//, ''), external: false }
  try {
    const url = new URL(value)
    if (url.protocol !== 'https:' || url.username || url.password) return null
    return { href: url.href, external: true }
  } catch { return null }
}

export function messageInline(value, depth = 0) {
  const text = String(value ?? '')
  if (depth >= 4) return [{ type: 'text', text }]
  const pattern = /(`+)([^`\n]+)\1|\*\*([^*\n]+)\*\*|__([^_\n]+)__|\*([^*\n]+)\*|_([^_\n]+)_|\[([^\]\n]+)\]\(([^\s)]+)\)/g
  const tokens = []
  let cursor = 0
  for (const match of text.matchAll(pattern)) {
    if (match.index > cursor) tokens.push({ type: 'text', text: text.slice(cursor, match.index) })
    const insideIdentifier = (match[4] || match[6]) && (/[A-Za-z0-9_\u4e00-\u9fff]/.test(text[match.index - 1] || '') || /[A-Za-z0-9_\u4e00-\u9fff]/.test(text[match.index + match[0].length] || ''))
    if (insideIdentifier) tokens.push({ type: 'text', text: match[0] })
    else if (match[1]) tokens.push({ type: 'code', text: match[2] })
    else if (match[3] || match[4]) tokens.push({ type: 'strong', children: messageInline(match[3] || match[4], depth + 1) })
    else if (match[5] || match[6]) tokens.push({ type: 'em', children: messageInline(match[5] || match[6], depth + 1) })
    else {
      const link = text[match.index - 1] === '!' ? null : messageLink(match[8])
      tokens.push(link ? { type: 'link', ...link, children: messageInline(match[7], depth + 1) } : { type: 'text', text: match[0] })
    }
    cursor = match.index + match[0].length
  }
  if (cursor < text.length) tokens.push({ type: 'text', text: text.slice(cursor) })
  return tokens
}

function tableCells(value) {
  let text = value.trim()
  if (text.startsWith('|')) text = text.slice(1)
  if (text.endsWith('|') && !text.endsWith('\\|')) text = text.slice(0, -1)
  const cells = []
  let cell = '', codeFence = '', index = 0
  while (index < text.length) {
    const char = text[index]
    if (char === '\\' && text[index + 1] === '|') { cell += '|'; index += 2; continue }
    if (char === '`') {
      const fence = /^`+/.exec(text.slice(index))[0]
      if (!codeFence) codeFence = fence
      else if (codeFence === fence) codeFence = ''
      cell += fence; index += fence.length; continue
    }
    if (char === '|' && !codeFence) { cells.push(cell.trim()); cell = '' }
    else cell += char
    index++
  }
  cells.push(cell.trim())
  return cells
}

const listItem = line => /^\s{0,3}([-+*]|\d{1,9}[.)])\s+(.+)$/.exec(line)
const fenceStart = line => /^\s{0,3}(`{3,}|~{3,})([^\s]*)\s*$/.exec(line)
const rule = line => /^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)
const heading = line => /^\s{0,3}(#{1,6})\s+(.+)$/.exec(line)
const quoted = line => /^\s{0,3}>\s?/.test(line)
function tableAlignment(line) {
  if (!line || !line.includes('|')) return null
  const cells = tableCells(line)
  return cells.length > 0 && cells.every(cell => /^:?-{3,}:?$/.test(cell))
    ? cells.map(cell => cell.startsWith(':') && cell.endsWith(':') ? 'center' : cell.endsWith(':') ? 'right' : 'left') : null
}

export function messageBlocks(value) {
  const lines = String(value ?? '').replace(/\r\n?/g, '\n').split('\n')
  const blocks = []
  let index = 0
  const tableAt = position => lines[position]?.includes('|') && tableAlignment(lines[position + 1])
  const boundary = position => !lines[position]?.trim() || fenceStart(lines[position]) || heading(lines[position]) || rule(lines[position]) || listItem(lines[position]) || quoted(lines[position]) || tableAt(position)
  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) { index++; continue }
    const id = index
    const fence = fenceStart(line)
    if (fence) {
      const content = []
      index++
      while (index < lines.length) {
        const close = /^\s{0,3}(`+|~+)\s*$/.exec(lines[index])
        if (close && close[1][0] === fence[1][0] && close[1].length >= fence[1].length) { index++; break }
        content.push(lines[index++])
      }
      blocks.push({ id, type: 'code', language: fence[2], text: content.join('\n') })
      continue
    }
    const title = heading(line)
    if (title) { blocks.push({ id, type: 'heading', level: title[1].length, text: title[2] }); index++; continue }
    if (rule(line)) { blocks.push({ id, type: 'rule' }); index++; continue }
    const alignments = tableAt(index)
    if (alignments) {
      const headers = tableCells(line)
      if (headers.length === alignments.length) {
        index += 2
        const rows = []
        while (index < lines.length && lines[index].trim() && lines[index].includes('|') && !fenceStart(lines[index])) {
          const cells = tableCells(lines[index])
          // Preserve unusual rows as normal text rather than discarding extra cells.
          if (cells.length !== headers.length) break
          rows.push(cells); index++
        }
        blocks.push({ id, type: 'table', headers, alignments, rows }); continue
      }
    }
    if (quoted(line)) {
      const content = []
      while (index < lines.length && quoted(lines[index])) content.push(lines[index++].replace(/^\s{0,3}>\s?/, ''))
      blocks.push({ id, type: 'quote', text: content.join('\n') }); continue
    }
    const first = listItem(line)
    if (first) {
      const ordered = /^\d/.test(first[1]), items = []
      while (index < lines.length) {
        const item = listItem(lines[index])
        if (!item || /^\d/.test(item[1]) !== ordered) break
        items.push(item[2]); index++
      }
      blocks.push({ id, type: 'list', ordered, start: ordered ? Number.parseInt(first[1], 10) : undefined, items }); continue
    }
    const content = [line]
    index++
    while (index < lines.length && !boundary(index)) content.push(lines[index++])
    blocks.push({ id, type: 'paragraph', text: content.join('\n') })
  }
  return blocks
}
