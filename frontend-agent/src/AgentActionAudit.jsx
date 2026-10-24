import React, { useEffect, useId, useRef, useState } from 'react';
import { Button } from 'antd';
import { ClipboardCheck, RefreshCw } from 'lucide-react';
import StatusBadge from './StatusBadge';
import { beijingDateTime } from '../../frontend/src/utils/beijingTime.js';
import { validActionAudit, actionAuditEvent, actionAuditResult, actionAuditRole, actionAuditReason } from '../../frontend/src/utils/agentActionAudit.js';
import '../../frontend/src/assets/agent-action-audit.css';

export default function AgentActionAudit({ actionId, revision, operation, scopeKey, base = '', disabled }) {
  const panelId = useId();
  const [open, setOpen] = useState(false), [loading, setLoading] = useState(false), [records, setRecords] = useState(null), [error, setError] = useState('');
  const generation = useRef(0), activeRead = useRef(null);
  const formatTime = value => value ? beijingDateTime(value) || '时间未记录' : '时间未记录';
  function stopRead() { generation.current++; activeRead.current?.abort(); activeRead.current = null; }
  useEffect(() => {
    stopRead(); setOpen(false); setLoading(false); setRecords(null); setError('');
    return stopRead;
  }, [actionId, revision, scopeKey, base]);
  async function load() {
    if (disabled || activeRead.current) return;
    const version = ++generation.current, controller = new AbortController();
    activeRead.current = controller; setLoading(true); setError('');
    try {
      const response = await fetch(base + '/api/agent/actions/' + encodeURIComponent(actionId) + '/audit', { credentials: 'include', cache: 'no-store', signal: controller.signal });
      if ([401, 403, 404].includes(response.status)) { const denied = new Error(); denied.status = response.status; throw denied; }
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (version !== generation.current) return;
      if (!validActionAudit(data)) throw new Error();
      setRecords(data);
    } catch (failure) {
      if (version !== generation.current || controller.signal.aborted) return;
      if ([401, 403, 404].includes(failure.status)) { setRecords(null); setError('当前账号无法读取该操作的审计，请核对权限及原记录。'); }
      else setError('审计暂不可读取；已读内容仅为上次快照，请重新读取核对。不会重发业务操作。');
    } finally { if (version === generation.current) { activeRead.current = null; setLoading(false); } }
  }
  function toggle() {
    if (disabled) return;
    if (open) { stopRead(); setLoading(false); setOpen(false); }
    else { setOpen(true); load(); }
  }
  return <div className="action-audit">
    <Button className="action-audit-toggle" type="text" disabled={disabled} aria-expanded={open} aria-controls={panelId} onClick={toggle}><ClipboardCheck size={15} aria-hidden="true"/>{open ? '收起审计' : '查看审计'}</Button>
    {open && <section id={panelId} className="action-audit-panel" aria-busy={loading} aria-labelledby={panelId + '-title'}>
      <header className="action-audit-heading"><strong id={panelId + '-title'}>操作审计时间线</strong><Button size="small" loading={loading} disabled={disabled} onClick={load}><RefreshCw size={14} aria-hidden="true"/>重新读取</Button></header>
      <p className="action-audit-hint">提议 <code>{actionId}</code> · V{revision}。仅展示本次已读审计；读取失败不代表业务操作失败。</p>
      {loading && <p className="action-audit-read-state" role="status">{records ? '正在读取，当前保留上次审计快照。' : '正在读取原操作的审计记录…'}</p>}
      {error && <p className="action-audit-error" role="alert">{error}</p>}
      {records && <><p className="action-audit-count">本次已读取 {records.length.toLocaleString('zh-CN')} 条 · 时间均为 UTC+8</p>
        {records.length > 0 ? <ol className="action-audit-events" tabIndex={0} aria-label="操作审计记录，可滚动阅读">{records.map(event => <li key={event.id} data-result={event.result}>
          <div className="action-audit-event-heading"><strong>{actionAuditEvent(event.eventType)}</strong><StatusBadge domain="confirmation" code={event.result} label={actionAuditResult(event.result, operation)}/></div>
          <p className="action-audit-event-meta"><time>{formatTime(event.occurredAt)}</time><span>{actionAuditRole(event.actorRole)}</span></p>
          {event.reasonCode && <p className="action-audit-reason">{actionAuditReason(event.reasonCode)}</p>}
        </li>)}</ol> : !loading && !error && <p className="action-audit-empty">本次未读到审计事件，可重新读取核对。不据此判断原操作没有执行。</p>}
      </>}
    </section>}
  </div>;
}
