import { knownCount } from './countPresentation.js'
import { beijingDateTime } from './beijingTime.js'

export const TREND_TARGETS = [
  ['normal', '正常'], ['bent', '弯曲'], ['deformed', '形变'],
  ['rusty', '锈蚀'], ['missing', '缺失'], ['compromised', '结构损伤']
]

const countKeys = ['total', ...TREND_TARGETS.map(([key]) => key)]

export function detectionTrendRows(data, range, now = new Date()) {
  const periodPattern = { week: /^\d{4}-\d{2}-\d{2}$/, month: /^\d{4}-\d{2}$/, year: /^\d{4}$/ }[range]
  const byDate = new Map()
  for (const item of data) {
    if (!periodPattern.test(item?.date) || byDate.has(item.date)) throw new Error('检测趋势期间格式不一致')
    const taskCount = knownCount(item.taskCount)
    const classifiedTasks = knownCount(item.classifiedTasks)
    const classificationCoverage = taskCount !== null && classifiedTasks !== null && classifiedTasks <= taskCount
      ? `${classifiedTasks.toLocaleString('zh-CN')} / ${taskCount.toLocaleString('zh-CN')} 项有完整分类记录` : '未记录'
    const counts = Object.fromEntries(countKeys.map(key => [key, knownCount(item[key])]))
    byDate.set(item.date, { period: item.date, coverage: '有任务记录', classificationCoverage, ...counts })
  }

  const [year, monthNumber, day] = beijingDateTime(now).slice(0, 10).split('-').map(Number)
  const month = monthNumber - 1
  const utc = (y, m, d) => new Date(Date.UTC(y, m, d)).toISOString()
  let periods
  if (range === 'week') {
    periods = Array.from({ length: 7 }, (_, index) => utc(year, month, day - 6 + index).slice(0, 10))
  } else if (range === 'month') {
    periods = Array.from({ length: 12 }, (_, index) => utc(year, month - 11 + index, 1).slice(0, 7))
  } else {
    const sorted = [...byDate.keys()].sort()
    if (!sorted.length) return []
    const earliest = Number(sorted[0])
    const latest = Math.max(Number(sorted.at(-1)), year)
    periods = Array.from({ length: latest - earliest + 1 }, (_, index) => String(earliest + index))
  }
  // Include each calendar interval while keeping absent source measurements distinct from zero.
  return periods.map(period => byDate.get(period) ?? {
    period, coverage: '无已完成任务记录', classificationCoverage: '无任务', ...Object.fromEntries(countKeys.map(key => [key, null]))
  })
}
