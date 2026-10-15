import React, { useEffect, useRef, useState } from 'react';
import { ReloadOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import { cardTitle, cardScope, cardRoute, reportStatus, metricLabels } from '../../frontend/src/utils/agentCards';

export function AgentResultCards({ text, references, businessBase }) {
  const [views, setViews] = useState([]), [loading, setLoading] = useState(false), [error, setError] = useState('');
  const generation = useRef(0);
  async function refresh() {
    const version = ++generation.current;
    setViews([]); setLoading(true); setError('');
    try {
      const response = await fetch(import.meta.env.VITE_AGENT_CARDS_URL || '/api/agent/cards/resolve', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cards: references }),
      });
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (version === generation.current) setViews(data.cards);
    } catch { if (version === generation.current) setError('卡片数据暂不可用 请检查登录状态后刷新'); }
    finally { if (version === generation.current) setLoading(false); }
  }
  useEffect(() => { refresh(); return () => { generation.current++; }; }, [references]);
  const date = value => value ? String(value).replace('T', ' ').slice(0, 19) : '—';
  const route = (type, id) => { const path = cardRoute(type, id); return path ? businessBase + path : undefined; };
  return <section className="agent-result" aria-label="助手业务结果">
    <p className="result-answer">{text}</p>
    <header className="result-heading"><span>业务数据按当前权限刷新</span><Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={refresh}>刷新卡片</Button></header>
    {error && <p role="alert" className="result-error">{error}</p>}
    {loading && !views.length && <p role="status">正在读取业务数据</p>}
    {views.map((card, index) => <article className="result-card" key={index + ':' + card.tool} aria-busy={loading}>
      <header><strong>{cardTitle(card)}</strong><span>{cardScope(card.scope)}</span></header>
      {card.type === 'METRICS' && <><p className="card-note">{date(card.from)} 至 {date(card.to)}</p><div className="card-metrics">{Object.entries(metricLabels).map(([key, label]) => <div key={key}><strong>{card.metrics?.[key] ?? '—'}</strong><span>{label}</span></div>)}</div></>}
      {card.type === 'TASKS' && card.items?.map(task => <div className="card-record" key={task.taskId}><a href={route('TASKS', task.taskId)}>{task.taskId}</a><p>状态 {task.status || '未知'} · 图片 {task.processedImages ?? 0}/{task.totalImages ?? 0} · 缺陷 {task.defectCount ?? 0}</p><p>设备 {task.deviceName || '未记录'} · 复核 {task.reviewStatus || '未复核'}</p></div>)}
      {card.type === 'REPORTS' && card.items?.map(report => <div className="card-record" key={report.reportId}><a href={route('REPORTS', report.reportId)}>{report.title}</a><p>{reportStatus(report.status)} · 版本 {report.version} · 任务 {report.taskId}</p>{report.status === 'DRAFT' && <p className="draft-note">私人草稿尚未提交或审批 请到报告页面核对</p>}<a href={route('REPORTS', report.reportId)}>查看报告</a></div>)}
      <p className={card.status === 'OK' ? 'card-note' : 'result-error'}>{card.message}</p><footer>更新 {date(card.updatedAt)}</footer>
    </article>)}
  </section>;
}
