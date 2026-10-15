// Interpret only the installation page link; message text never supplies an arbitrary navigation target.
export function skillInstallNavigation(text, businessBase) {
  if (typeof text !== 'string') return null
  const match = /\[([^\]\r\n]{1,120})\]\((\/?#\/agent\/skills\?installUrl=[A-Za-z0-9%_.+-]{1,3000})\)/.exec(text)
  if (!match) return null
  try {
    const encoded = match[2].split('installUrl=')[1]
    const source = decodeURIComponent(encoded.replace(/\+/g, ' '))
    const url = new URL(source)
    const github = url.protocol === 'https:' && url.host === 'github.com' && !url.username && !url.password && !url.search && !url.hash &&
      /^\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/tree\/[A-Za-z0-9_.-]+\/(?:[A-Za-z0-9_.-]+\/)*[A-Za-z0-9_.-]+\/?$/.test(url.pathname)
    const modelscope = source === 'https://modelscope.cn/skills/@anthropics/skill-creator' || source === 'https://modelscope.cn/skills/@anthropics/skill-creator/'
    if (!github && !modelscope) return null
    const route = '#/agent/skills?installUrl=' + encodeURIComponent(source)
    const base = new URL(businessBase)
    if (!['http:', 'https:'].includes(base.protocol)) return null
    return { label: match[1], href: new URL(route, base).toString(), route, before: text.slice(0, match.index), after: text.slice(match.index + match[0].length) }
  } catch { return null }
}
