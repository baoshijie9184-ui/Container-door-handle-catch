import React, { useEffect, useRef, useState } from 'react';
import { Button, Dropdown, Input, Modal } from 'antd';
import { ArrowUpRight, ChartNoAxesCombined, Ellipsis, GitBranch, MessageSquare, Pencil, Pin, RefreshCw, Search, X } from 'lucide-react';
import { SESSION_TITLE_MAX_LENGTH, sessionHistoryGroups, sessionMetadata, sessionPreview, sessionTimestampLabel } from '../../frontend/src/utils/sessionPresentation';
import { useReducedMotion } from './useReducedMotion';
import './SessionHistory.css';

// These are the same account-scoped title and pin endpoints used by the Vue sidebar.
export function SessionHistory({ sessions, selectedId, disabled, currentTaskActive, loading, error, base, traceBase, businessBase, onSelect, onRefresh, onChanged }) {
  const [query, setQuery] = useState('');
  const [now, setNow] = useState(Date.now);
  const [editing, setEditing] = useState(null);
  const [title, setTitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [operationError, setOperationError] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const mutationBusy = useRef(false), generation = useRef(0);
  const reducedMotion = useReducedMotion();
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60000);
    return () => { window.clearInterval(timer); generation.current++; };
  }, []);
  const groups = sessionHistoryGroups(sessions, query, now);
  const count = groups.reduce((total, group) => total + group.sessions.length, 0);

  async function save(session, operation, payload) {
    if (mutationBusy.current || disabled) return;
    mutationBusy.current = true; setSaving(true); setOperationError(''); setUncertain(false);
    const version = generation.current;
    try {
      const response = await fetch(base + '/' + encodeURIComponent(session.sessionId) + '/' + operation, {
        method: 'PUT', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      if (version !== generation.current) return;
      if (!response.ok) throw new Error();
      const receipt = await response.json();
      if (version !== generation.current) return;
      if (receipt.code !== 200) throw new Error();
      onChanged(session.sessionId, payload);
      setEditing(null);
    } catch {
      if (version === generation.current) {
        setUncertain(true);
        setOperationError('操作结果尚未核对，请刷新会话列表。不会自动重新提交。');
      }
    } finally {
      mutationBusy.current = false;
      if (version === generation.current) setSaving(false);
    }
  }
  function openRename(session) {
    setEditing(session); setTitle(session.title || ''); setOperationError(''); setUncertain(false);
  }

  return <>
    <div className="session-search"><Input aria-label="搜索已加载会话" aria-describedby="session-history-search-scope" placeholder="搜索会话标题或摘要" value={query} onChange={event => setQuery(event.target.value)} prefix={<Search size={15} aria-hidden="true"/>} allowClear={{ clearIcon: <X size={13} aria-hidden="true"/> }}/></div>
    <p id="session-history-search-scope" className="session-search-scope">仅搜索当前账号已加载的标题和摘要</p>
    <div className="session-list-heading"><span>{query.trim() ? `匹配 ${count} 条` : '对话历史'}</span><Button type="text" title="重新读取会话列表" aria-label="重新读取会话列表" disabled={disabled || saving} loading={loading} onClick={onRefresh} icon={<RefreshCw size={14} aria-hidden="true"/>}/></div>
    {operationError && !editing && <p className="session-operation-error" role="alert">{operationError}</p>}
    {error && groups.length > 0 && <p className="session-operation-error" role="alert">{error} 请重新读取，当前列表可能不是最新状态。</p>}
    <div className="session-history" aria-busy={loading}>
      {groups.map(group => <section className="session-history-group" key={group.key} aria-label={group.label}><h2>{group.label}</h2>
        {group.sessions.map(session => <div className={`session-history-row ${session.sessionId === selectedId ? 'is-current' : ''}`} key={session.sessionId}>
          <button type="button" className={`session-item ${session.sessionId === selectedId ? 'selected' : ''}`} aria-current={session.sessionId === selectedId ? 'page' : undefined} disabled={disabled} title={(session.title || '新对话') + '\n' + sessionTimestampLabel(session) + '（UTC+8）'} onClick={() => onSelect(session.sessionId)}>
            {session.sourceSessionId ? <GitBranch size={15} aria-hidden="true"/> : <MessageSquare size={15} aria-hidden="true"/>}<span className="session-item-copy"><span className="session-item-title">{session.title || '新对话'}</span>{sessionPreview(session) && <span className="session-item-preview">{sessionPreview(session)}</span>}<span className="session-item-meta">{sessionMetadata(session, now)}</span></span>{session.pinned === true && <Pin size={12} aria-label="已置顶"/>}
          </button>
          <Dropdown trigger={['click']} menu={{ items: [
            { key: 'rename', label: '重命名', icon: <Pencil size={14}/> },
            { key: 'pin', label: session.pinned ? '取消置顶' : '置顶', icon: <Pin size={14}/> },
            { type: 'divider' },
            { key: 'trace', label: <a href={traceBase + '?sessionId=' + encodeURIComponent(session.sessionId)}>查看执行追溯</a>, icon: <ChartNoAxesCombined size={14}/> },
            { key: 'manage', label: <a href={businessBase + '#/agent/chat?sessionId=' + encodeURIComponent(session.sessionId)}>在主站管理会话</a>, icon: <ArrowUpRight size={14}/> },
          ], onClick: ({ key }) => { if (key === 'rename') openRename(session); if (key === 'pin') save(session, 'pin', { pinned: !session.pinned }); } }} disabled={disabled || saving}>
            <button className="session-more" type="button" aria-label={'会话操作：' + (session.title || '新对话')} title="会话操作" disabled={disabled || saving}><Ellipsis size={16} aria-hidden="true"/></button>
          </Dropdown>
          {session.sourceSessionId && <button className="session-source-link" type="button" disabled={disabled} title="返回来源会话" onClick={() => onSelect(session.sourceSessionId)}><GitBranch size={12} aria-hidden="true"/>分支来源</button>}
        </div>)}
      </section>)}
      {!groups.length && <div className="session-history-empty"><Search size={24} aria-hidden="true"/><strong>{loading ? '正在读取会话' : error ? '会话暂不可读取' : query.trim() ? '没有匹配的会话' : '暂无会话历史'}</strong><p>{error || (query.trim() ? '可以缩短关键词，或清空搜索查看已加载的会话' : '新建对话，开始检测与质检工作')}</p>{error ? <Button size="small" disabled={disabled || saving || loading} onClick={onRefresh}>重新读取</Button> : query.trim() && <Button size="small" onClick={() => setQuery('')}>清空搜索</Button>}</div>}
    </div>
    <Modal title="重命名会话" open={!!editing} onCancel={() => { if (!saving) setEditing(null); }} onOk={() => save(editing, 'title', { title: title.trim() })} okText="保存名称" cancelText="关闭" confirmLoading={saving} okButtonProps={{ disabled: !title.trim() || title.trim() === editing?.title || uncertain || disabled }} cancelButtonProps={{ disabled: saving }} closable={!saving} maskClosable={!saving} keyboard={!saving} transitionName={reducedMotion ? '' : 'ant-zoom'} maskTransitionName={reducedMotion ? '' : 'ant-fade'} destroyOnClose>
      <label className="session-title-label" htmlFor="session-title-editor">会话名称</label><Input id="session-title-editor" autoFocus value={title} maxLength={SESSION_TITLE_MAX_LENGTH} showCount disabled={saving || uncertain} onChange={event => setTitle(event.target.value)} onPressEnter={() => { if (title.trim() && !uncertain && !disabled && title.trim() !== editing?.title) save(editing, 'title', { title: title.trim() }); }}/>
      <p className="session-dialog-note">仅修改会话名称，历史消息和分支关系保留。{currentTaskActive ? '当前任务继续按原要求执行。' : ''}</p>
      {operationError && <p className="session-operation-error" role="alert">{operationError}</p>}
    </Modal>
  </>;
}
