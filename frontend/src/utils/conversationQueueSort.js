// Capture IDs and revisions at pickup so a second tab or a claimed message cannot be overwritten.
export function queueMove(rows, from, to) {
  const order = rows.map(({ id, revision }) => ({ id, revision }))
  const source = order.findIndex(row => row.id === from)
  const target = order.findIndex(row => row.id === to)
  if (source < 0 || target < 0 || source === target) return null
  order.splice(target, 0, order.splice(source, 1)[0])
  return order
}

export function queueSorting(getRows, save) {
  let drag = null
  let marked = null
  function clear() {
    if (marked) delete marked.dataset.dropEdge
    marked = null
  }
  function end() { clear(); drag = null }
  function move(rows, from, to) {
    const order = queueMove(rows, from, to)
    if (order) save(order)
  }
  function adjacent(id, offset) {
    const rows = getRows()
    const index = rows.findIndex(row => row.id === id)
    if (index >= 0) move(rows, id, rows[index + offset]?.id)
  }
  return {
    end, adjacent,
    start(event) {
      end()
      const id = event.target.closest('.queue-grip')?.closest('li')?.dataset.queueId
      const rows = getRows()
      if (!id || rows.length < 2 || !rows.some(row => row.id === id)) return
      drag = { id, rows }
      event.dataTransfer.effectAllowed = 'move'
      event.dataTransfer.setData('text/plain', id)
    },
    over(event) {
      if (!drag) return
      const target = event.target.closest('li[data-queue-id]')
      const to = drag.rows.findIndex(row => row.id === target?.dataset.queueId)
      if (to < 0) return
      event.preventDefault()
      event.dataTransfer.dropEffect = 'move'
      clear()
      if (target.dataset.queueId === drag.id) return
      marked = target
      marked.dataset.dropEdge = to < drag.rows.findIndex(row => row.id === drag.id) ? 'top' : 'bottom'
    },
    drop(event) {
      if (!drag) return
      event.preventDefault()
      const target = event.target.closest('li[data-queue-id]')?.dataset.queueId
      const { rows, id } = drag
      end()
      move(rows, id, target)
    }
  }
}
