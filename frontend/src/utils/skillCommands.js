// 两套界面复用目录格式；菜单只补全输入，不执行安装、发布或业务操作。
const BASE = [
  { value: '/help', label: '/help', description: '查看命令帮助' },
  { value: '/skills', label: '/skills', description: '列出可用技能' },
  { value: '/skills manage', label: '/skills manage', description: '查看技能管理入口' },
  { value: '/skill ', label: '/skill 技能名 问题', description: '明确选择技能处理问题' }
]
const RESERVED = new Set(['help', 'skills', 'skill'])
export function skillCommandOptions(catalog) {
  const commands = catalog?.externalInstallSupported ? [...BASE, { value: '/skills install ', label: '/skills install 链接', description: '打开本人页面确认下载' }] : BASE
  const skills = Array.isArray(catalog?.skills) ? catalog.skills.filter(s =>
    typeof s?.name === 'string' && /^[a-z][a-z0-9-]{2,63}$/.test(s.name) &&
    typeof s.skillId === 'string' && /^skill-[a-f0-9-]{36}$/.test(s.skillId) &&
    typeof s.description === 'string' && Number.isInteger(s.version) && s.version > 0) : []
  const names = new Map()
  skills.forEach(s => names.set(s.name, (names.get(s.name) || 0) + 1))
  const seen = new Set()
  return [...commands, ...skills.filter(s => { if (seen.has(s.skillId)) return false; seen.add(s.skillId); return true }).map(s => {
    const unique = names.get(s.name) === 1 && !RESERVED.has(s.name)
    return { value: unique ? '/' + s.name + ' ' : '/skill ' + s.skillId + ' ',
      selector: unique ? s.name : s.skillId, label: '/' + s.name + (unique ? '' : ' · ' + s.skillId.slice(-8)),
      description: s.description.slice(0, 300) + ' · v' + s.version }
  })]
}
export function filterSkillCommands(catalog, draft) {
  if (typeof draft !== 'string' || !draft.startsWith('/')) return []
  const text = draft.toLowerCase()
  let options = skillCommandOptions(catalog)
  if (text.startsWith('/skill ')) {
    options = options.filter(o => o.selector).map(o => ({ ...o, value: '/skill ' + o.selector + ' ' }))
  } else if (/\s/.test(text) && !'/skills manage'.startsWith(text) && !'/skills install '.startsWith(text)) return []
  return options.filter(o => o.value.toLowerCase().startsWith(text)).slice(0, 10)
}
