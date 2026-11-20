const actions = ['images', 'trace', 'assign', 'review']

export function boardDialog(query, supervisor, uploads) {
  const { boardAction: action, taskId } = query
  if (!actions.includes(action) || typeof taskId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(taskId)) return null
  if (uploads !== (action === 'images') || (action === 'assign' && !supervisor)) return null
  return { action, taskId }
}

export function listLocation(route) {
  const { boardAction, taskId, ...query } = route.query
  return { path: route.path, query, hash: route.hash }
}

export function employeeInbox(query) {
  if (query.inbox !== undefined) return query.inbox === '1'
  // Existing links to a task, search or filtered archive still open the full accessible list.
  return !['assignedTaskId', 'keyword', 'directory', 'phase', 'page'].some(key => query[key])
}
