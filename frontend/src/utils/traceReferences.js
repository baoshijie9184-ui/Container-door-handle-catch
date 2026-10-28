// Only identifiers from a complete, account-scoped task response can become shortcuts.
export function readTraceReferences(body) {
  const records = body?.data?.records
  if (body?.code !== 200 || !Array.isArray(records) || records.length > 50) throw new Error('最近任务未完整读取')
  const seen = new Set()
  for (const row of records) {
    if (!row || typeof row.taskId !== 'string' || !row.taskId.trim() || seen.has(row.taskId)) throw new Error('任务编号未完整读取')
    seen.add(row.taskId)
  }
  const numbers = field => [...new Set(records.map(row => row[field]).filter(value => typeof value === 'string' && value.trim() && value.length <= 128).map(value => value.trim()))].slice(0, 6)
  return { workOrders: numbers('workOrderNo'), batches: numbers('batchNo') }
}
