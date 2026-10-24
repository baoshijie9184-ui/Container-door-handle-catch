import { businessDate, beijingDateTime, relativeBeijingTime } from './beijingTime'
import { knownCount } from './countPresentation'
export const SESSION_TITLE_MAX_LENGTH = 50

const groups = [
  ['pinned', '置顶'], ['today', '今天'], ['yesterday', '昨天'],
  ['week', '最近七天'], ['older', '更早'], ['other', '其他时间']
]

export function sessionHistoryGroups(sessions, search = '', now = Date.now()) {
  const query = String(search || '').trim().toLocaleLowerCase('zh-CN')
  const today = Math.floor((now + 8 * 3600000) / 86400000)
  const buckets = new Map(groups.map(([key]) => [key, []]))
  const rows = (Array.isArray(sessions) ? sessions : []).filter(session => session?.sessionId &&
    (!query || [session.title, session.lastMessage].some(value => typeof value === 'string' && value.toLocaleLowerCase('zh-CN').includes(query))))
  const timestamp = session => businessDate(session.updatedAt || session.createdAt)?.getTime() ?? -Infinity
  rows.sort((a, b) => timestamp(b) - timestamp(a))
  for (const session of rows) {
    const date = businessDate(session.updatedAt || session.createdAt)
    const age = date ? today - Math.floor((date.getTime() + 8 * 3600000) / 86400000) : -1
    const key = session.pinned === true ? 'pinned' : age === 0 ? 'today' : age === 1 ? 'yesterday' : age >= 2 && age < 7 ? 'week' : age >= 7 ? 'older' : 'other'
    buckets.get(key).push(session)
  }
  return groups.map(([key, label]) => ({ key, label, sessions: buckets.get(key) })).filter(group => group.sessions.length)
}

export function sessionTimestampLabel(session) {
  const value = session.updatedAt || session.createdAt
  return value ? beijingDateTime(value) || '时间格式未知' : '时间未记录'
}

export function sessionPreview(session) {
  // A sidebar excerpt is plain text, never rendered as Markdown or HTML.
  return typeof session?.lastMessage === 'string' ? session.lastMessage.replace(/\s+/g, ' ').trim().slice(0, 180) : ''
}

export function sessionMetadata(session, now = Date.now()) {
  const count = knownCount(session?.messageCount)
  const time = relativeBeijingTime(session?.updatedAt || session?.createdAt, now)
  return [count === null ? '' : `${count} 条消息`, time || '时间未记录'].filter(Boolean).join(' · ')
}
