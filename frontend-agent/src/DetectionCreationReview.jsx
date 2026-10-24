import React, { useEffect, useRef, useState } from 'react';
import { Button } from 'antd';
import { FileCheck, Search, TriangleAlert, ArrowUpRight } from 'lucide-react';
import StatusBadge from './StatusBadge';
import { validTransferReview, canCheckTransfer, transferDecision, transferCount, transferNextStep, transferDecisionSnapshot, transferDecisionMatches } from '../../frontend/src/utils/detectionCreationReview.js';
import { beijingDateTime } from '../../frontend/src/utils/beijingTime.js';
import { cardRoute } from '../../frontend/src/utils/agentCards.js';
import './DetectionCreationReview.css';
const operationNames = { CHECK: '只读核对', FINALIZE: '完成原创建', ABANDON: '终止创建' };
const formatTime = value => value ? beijingDateTime(value) || '时间未记录' : '时间未记录';

export function DetectionCreationReview({ sessionId, base = '', refreshKey, onChanged }) {
  const scope = JSON.stringify([sessionId, base]);
  const [snapshot, setSnapshot] = useState(null), [failure, setFailure] = useState(null), [loading, setLoading] = useState(false), [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState(new Map()), [decision, setDecision] = useState(null), [lastRequest, setLastRequest] = useState(null);
  const currentScope = useRef(null), scopeGeneration = useRef(0), readGeneration = useRef(0), activeRead = useRef(null), locked = useRef(new Map()), alive = useRef(true);
  const rows = snapshot?.scope === scope ? snapshot.rows : [], error = failure?.scope === scope ? failure.message : '';
  const selectedDecision = decision?.scope === scope ? decision : null;
  const endpoint = base + '/api/agent/conversations/' + encodeURIComponent(sessionId) + '/detection-creations';
  const setError = message => setFailure(message ? { scope, message } : null);
  function hasCurrentWrite() { return [...locked.current.values()].some(value => value.scope === scopeGeneration.current); }
  function stopRead() { readGeneration.current++; activeRead.current?.abort(); activeRead.current = null; }
  async function read(response) {
    let body;
    try { body = await response.json(); } catch { const invalid = new Error('核对回执格式暂不可核对'); invalid.status = response.status; throw invalid; }
    if (!response.ok) { const rejected = new Error(typeof body?.message === 'string' ? body.message : '核对状态暂不可用'); rejected.status = response.status; throw rejected; }
    return body;
  }
  async function refresh() {
    if (!sessionId || hasCurrentWrite()) return;
    stopRead(); const version = ++readGeneration.current, epoch = scopeGeneration.current, controller = new AbortController();
    activeRead.current = controller; setLoading(true); setVerified(false); setDecision(null); setError('');
    try {
      const data = await read(await fetch(endpoint, { credentials: 'include', cache: 'no-store', signal: controller.signal }));
      if (epoch !== scopeGeneration.current || version !== readGeneration.current) return;
      if (!Array.isArray(data) || !data.every(validTransferReview)) throw new Error();
      setSnapshot({ scope, rows: data }); setVerified(true);
    } catch (cause) {
      if (epoch !== scopeGeneration.current || version !== readGeneration.current || controller.signal.aborted) return;
      if ([401, 403, 404].includes(cause.status)) setSnapshot(null);
      setError('核对状态暂不可读取。已显示内容仅为上次快照，请刷新核对，不会重发原操作。');
    } finally { if (epoch === scopeGeneration.current && version === readGeneration.current) { activeRead.current = null; setLoading(false); } }
  }
  useEffect(() => {
    if (currentScope.current !== scope) { currentScope.current = scope; scopeGeneration.current++; setSnapshot(null); setDecision(null); setLastRequest(null); setFailure(null); setVerified(false); setLoading(false); }
    refresh(); return stopRead;
  }, [sessionId, base, refreshKey]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; scopeGeneration.current++; stopRead(); }; }, []);
  function choose(row, action) {
    if (!verified || activeRead.current || locked.current.has(row.commandId) || row.status !== 'NEEDS_REVIEW' || !['FINALIZE', 'ABANDON'].includes(action) || (action === 'FINALIZE' && !row.canFinalize)) return;
    setDecision(Object.freeze({ ...transferDecisionSnapshot(row, action), scope }));
  }
  async function send(row, action) {
    if (!verified || activeRead.current || locked.current.has(row.commandId) || row.status !== 'NEEDS_REVIEW' || !Object.hasOwn(operationNames, action)) return;
    if (action === 'CHECK' ? !canCheckTransfer(row) : !transferDecisionMatches(selectedDecision, row) || selectedDecision.action !== action || (action === 'FINALIZE' && !row.canFinalize)) return;
    const epoch = scopeGeneration.current, requestId = crypto.randomUUID();
    locked.current.set(row.commandId, { action, requestId, scope: epoch }); setBusy(new Map(locked.current)); setLastRequest({ scope, requestId, action }); setDecision(null); setError('');
    try {
      const data = await read(await fetch(endpoint + '/' + encodeURIComponent(row.commandId) + '/review', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'X-Agent-Action': 'workbench', 'X-Request-ID': requestId }, body: JSON.stringify({ requestId, revision: row.revision, action, ...(action === 'FINALIZE' ? { checkId: row.checkId } : {}) }) }));
      if (epoch !== scopeGeneration.current) return;
      if (!validTransferReview(data) || data.commandId !== row.commandId) throw new Error();
      setSnapshot(value => value?.scope === scope ? { scope, rows: value.rows.map(item => item.commandId === row.commandId ? data : item) } : value); onChanged?.();
    } catch (cause) {
      if (epoch !== scopeGeneration.current) return;
      setVerified(false); setLastRequest({ scope, requestId, action });
      if ([401, 403, 404].includes(cause.status)) setSnapshot(null);
      setError(cause.message || '操作结果尚未核实，请刷新原命令状态。保留本次请求编号，不会自动重发。');
    } finally {
      if (locked.current.get(row.commandId)?.requestId === requestId) { locked.current.delete(row.commandId); if (alive.current) setBusy(new Map(locked.current)); }
    }
  }
  if (!sessionId || !rows.length && !error) return null;
  return <section className="detection-transfer-reviews" aria-label="检测创建结果核对">
    <header className="transfer-heading"><strong><FileCheck size={17} aria-hidden="true"/>检测创建结果核对</strong><Button size="small" loading={loading} disabled={hasCurrentWrite()} onClick={refresh}>刷新状态</Button></header>
    <p className="transfer-intro">核对原创建命令的文件与回执，再决定是否完成创建。此处不重新上传图片。</p>
    {loading && <p className="transfer-read-note" role="status">正在读取，当前保留上次快照；读取完成前不能提交处置。</p>}
    {error && <p role="alert" className="transfer-error">{error}</p>}
    {error && lastRequest?.scope === scope && <p className="transfer-read-note">操作请求 {operationNames[lastRequest.action]} · 请求 <code>{lastRequest.requestId}</code>。请保留编号核对，不会自动重发。</p>}
    {rows.map(row => <article key={row.commandId} className="transfer-record" data-status={row.status} aria-busy={busy.has(row.commandId)}>
      <header className="transfer-record-heading"><div><small>检测任务</small><strong>{row.taskId}</strong></div><StatusBadge domain="detectionCreation" code={row.status}/></header>
      <dl className="transfer-metrics"><div><dt>目标图片清单</dt><dd>{row.manifestAvailable ? transferCount(row.images) + ' 张' : '清单不完整'}</dd></div><div><dt>存储已记录</dt><dd>{transferCount(row.acknowledged)} 张</dd></div><div><dt>核对内容一致</dt><dd>{row.checkStatus ? transferCount(row.verified) + ' 张' : '尚未核对'}</dd></div></dl>
      {row.checkStatus && <><div className="transfer-check-line"><StatusBadge domain="transferCheck" code={row.checkStatus}/><span>已检查 {transferCount(row.checked)} / {transferCount(row.images)} 张</span></div><p>最近核对 {formatTime(row.checkedAt)} UTC+8</p></>}
      <p className="transfer-next-step">{transferNextStep(row, verified)}</p>
      {busy.has(row.commandId) && <p className="transfer-read-note" role="status">{operationNames[busy.get(row.commandId).action]}已提交，正在等待原回执；不会重复发送。</p>}
      {row.status === 'QUEUED' && <a className="transfer-task-link" href={(base || globalThis.location?.origin || '') + cardRoute('TASKS', row.taskId)} target="_blank" rel="noopener noreferrer">查看检测任务<ArrowUpRight size={14} aria-hidden="true"/></a>}
      <details className="transfer-evidence"><summary>编号与核对依据</summary><dl><dt>创建命令</dt><dd><code>{row.commandId}</code></dd><dt>命令版本</dt><dd>V{row.revision}</dd><dt>核对记录</dt><dd><code>{row.checkId || '尚未记录'}</code></dd>{typeof row.reasonCode === 'string' && row.reasonCode && <><dt>原因代码</dt><dd><code>{row.reasonCode}</code></dd></>}</dl></details>
      {row.status === 'NEEDS_REVIEW' && <><p className="transfer-cost-note"><TriangleAlert size={15} aria-hidden="true"/><span>只读核对会读取目标图片并计算摘要，可能产生存储读取和流量费用。不会重传图片，完成创建仍需本人确认。</span></p><div className="transfer-buttons"><Button loading={busy.get(row.commandId)?.action === 'CHECK'} disabled={!verified || busy.has(row.commandId) || !canCheckTransfer(row)} onClick={() => send(row, 'CHECK')} icon={<Search size={14} aria-hidden="true"/>}>只读核对</Button><Button type="primary" disabled={!verified || busy.has(row.commandId) || !row.canFinalize} onClick={() => choose(row, 'FINALIZE')}>完成原创建</Button><Button danger disabled={!verified || busy.has(row.commandId)} onClick={() => choose(row, 'ABANDON')}>终止创建</Button></div></>}
      {selectedDecision?.id === row.commandId && <div className="transfer-decision" data-action={selectedDecision.action} role="group" aria-label="确认原创建命令的处置"><strong>{selectedDecision.action === 'FINALIZE' ? '确认完成原创建' : '确认终止原创建'} · V{selectedDecision.revision}</strong><p>{transferDecision(selectedDecision.action)}</p>{!transferDecisionMatches(selectedDecision, row) && <p role="status">记录已变化，请返回并重新核对，不沿用旧确认。</p>}<div className="transfer-decision-actions"><Button type="primary" danger={selectedDecision.action === 'ABANDON'} disabled={!verified || busy.has(row.commandId) || !transferDecisionMatches(selectedDecision, row)} onClick={() => send(row, selectedDecision.action)}>确认{selectedDecision.action === 'FINALIZE' ? '完成创建' : '终止'}</Button><Button onClick={() => setDecision(null)}>返回核对</Button></div></div>}
    </article>)}
    {rows.length > 0 && <p className="transfer-intro">本次读取 {transferCount(rows.length)} 条，接口最多返回 20 条；此处不代表全部创建历史。</p>}
  </section>;
}
