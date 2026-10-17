// Generation-scoped readers prevent a delayed response from leaking into a different run.
export const initialTraceState = () => ({ runs: [], selectedRun: null, events: [], messages: [], evidence: null, evidenceLoading: false, evidenceError: '',
  historyLoading: false, eventsLoading: false, messagesLoading: false, detailLoading: false,
  hasMoreRuns: false, hasMoreEvents: false, historyError: '', eventsError: '', detailError: '', messagesError: '' })
const message = (error, fallback) => error?.response?.status === 404 ? '该记录不存在或无访问权限' : error?.response?.data?.message || fallback
export function createTraceReader(api, state, normalize, completeness) {
  let listVersion = 0, runVersion = 0, messageVersion = 0, evidenceVersion = 0, disposed = false
  let eventsPending = false, refreshing = false
  const valid = version => !disposed && version === runVersion
  function clearSelection() {
    runVersion++; messageVersion++; evidenceVersion++; eventsPending = false; refreshing = false
    Object.assign(state, { selectedRun: null, events: [], messages: [], detailLoading: false, eventsLoading: false,
      messagesLoading: false, hasMoreEvents: false, detailError: '', eventsError: '', messagesError: '', evidence: null, evidenceLoading: false, evidenceError: '' })
  }
  async function loadEvidence(run = state.selectedRun, version = runVersion) {
    if (!run || !api.sources || disposed) return
    const request = ++evidenceVersion
    state.evidenceLoading = true; state.evidenceError = ''
    try {
      const response = await api.sources(run.runId)
      if (!valid(version) || request !== evidenceVersion) return
      const value = response.data
      if (value?.runId !== run.runId || !Array.isArray(value.sources) || value.sources.some(source => source?.runId !== run.runId)) throw new Error('INVALID_SOURCE_SCOPE')
      state.evidence = value
    } catch (error) {
      if (valid(version) && request === evidenceVersion) {
        if ([401,403,404].includes(error?.response?.status)) { clearSelection(); state.detailError = message(error, '来源不可访问') }
        else { state.evidence = null; state.evidenceError = message(error, '调研来源读取失败，请重试') }
      }
    } finally { if (valid(version) && request === evidenceVersion) state.evidenceLoading = false }
  }
  async function loadMessages(run, version) {
    const request = ++messageVersion
    state.messages = []; state.messagesLoading = true; state.messagesError = ''
    // Child execution IDs address workbench state, not standalone chat_session rows.
    if (run.entryPoint === 'CHILD') { state.messagesLoading = false; return }
    try {
      const response = await api.session(run.sessionId)
      if (!valid(version) || request !== messageVersion) return
      const session = response.data?.data
      if (!session || session.sessionId !== run.sessionId || !Array.isArray(session.messages)) throw new Error('INVALID_SESSION')
      state.messages = session.messages
    } catch (error) { if (valid(version) && request === messageVersion) state.messagesError = message(error, '会话上下文暂不可用') }
    finally { if (valid(version) && request === messageVersion) state.messagesLoading = false }
  }
  async function loadMore() {
    if (!state.selectedRun || eventsPending || disposed) return
    const version = runVersion, id = state.selectedRun.runId
    const after = completeness(state.events, state.selectedRun.lastSequence).cursor
    eventsPending = true; state.eventsLoading = true; state.eventsError = ''
    try {
      const response = await api.events(id, after)
      if (!valid(version)) return
      if (!Array.isArray(response.data)) throw new Error('INVALID_EVENTS')
      const rows = normalize(response.data)
      const merged = normalize([...state.events, ...rows])
      const next = completeness(merged, state.selectedRun.lastSequence)
      state.events = merged
      state.hasMoreEvents = rows.length === 100 || !next.complete
      if (next.cursor === after && !next.complete) state.eventsError = '事件尚未读全或存在序号缺口，请重试补读'
    } catch (error) {
      if (valid(version)) {
        if ([401,403,404].includes(error?.response?.status)) { clearSelection(); state.detailError = message(error, '记录不可访问') }
        else { state.hasMoreEvents = true; state.eventsError = message(error, '执行事件读取失败，请重试补读') }
      }
    }
    finally { if (valid(version)) { eventsPending = false; state.eventsLoading = false } }
  }
  async function select(id) {
    clearSelection()
    if (!id || disposed) return
    const version = runVersion
    state.detailLoading = true
    try {
      const response = await api.run(id)
      if (!valid(version)) return
      if (response.data?.runId !== id) throw new Error('INVALID_RUN')
      state.selectedRun = response.data
      await Promise.all([loadMore(), loadMessages(response.data, version), loadEvidence(response.data, version)])
    } catch (error) { if (valid(version)) state.detailError = message(error, '运行记录读取失败，请重试') }
    finally { if (valid(version)) state.detailLoading = false }
  }
  async function history({ sessionId, all = false, append = false } = {}) {
    const request = ++listVersion
    if (!append) { state.runs = []; state.hasMoreRuns = false }
    state.historyLoading = true; state.historyError = ''
    try {
      const response = await api.list({ ...(all ? {} : { sessionId }), limit: 20, ...(append ? { beforeRunId: state.runs.at(-1)?.runId } : {}) })
      if (disposed || request !== listVersion) return
      if (!Array.isArray(response.data)) throw new Error('INVALID_RUNS')
      const rows = response.data.filter(run => typeof run?.runId === 'string')
      const seen = new Set(append ? state.runs.map(run => run.runId) : [])
      state.runs = [...(append ? state.runs : []), ...rows.filter(run => { if (seen.has(run.runId)) return false; seen.add(run.runId); return true })]
      state.hasMoreRuns = rows.length === 20
    } catch (error) { if (!disposed && request === listVersion) state.historyError = message(error, '运行历史暂不可用，请刷新') }
    finally { if (!disposed && request === listVersion) state.historyLoading = false }
  }
  async function refresh() {
    if (!state.selectedRun || refreshing || state.detailLoading || eventsPending || disposed) return
    const version = runVersion, id = state.selectedRun.runId
    refreshing = true
    try {
      const response = await api.run(id)
      if (!valid(version)) return
      if (response.data?.runId !== id) throw new Error('INVALID_RUN')
      const statusChanged = state.selectedRun.status !== response.data.status
      state.selectedRun = response.data; state.detailError = ''
      const index = state.runs.findIndex(run => run.runId === id)
      if (index >= 0) state.runs[index] = response.data
      await Promise.all([loadMore(), loadEvidence(response.data, version), ...(statusChanged ? [loadMessages(response.data, version)] : [])])
    } catch (error) {
      if (valid(version)) {
        // Revoked ownership must clear previously rendered data as well as the detail pane.
        if ([401,403,404].includes(error?.response?.status)) { clearSelection(); state.detailError = message(error, '记录不可访问') }
        else state.detailError = message(error, '运行状态更新失败，请刷新')
      }
    } finally { if (valid(version)) refreshing = false }
  }
  function reset() { listVersion++; clearSelection(); Object.assign(state, { runs: [], hasMoreRuns: false, historyLoading: false, historyError: '' }) }
  function dispose() { reset(); disposed = true }
  return { history, select, loadMore, loadEvidence, refresh, reset, dispose }
}
