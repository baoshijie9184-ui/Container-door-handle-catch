import React, { useEffect, useRef, useState } from 'react';
import { ReloadOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import { Markdown } from '@agentscope-ai/chat';
import StatusBadge from './StatusBadge';
import { ChartNoAxesCombined, ClipboardList, FileCheck, FileText, Files, Layers, Monitor, TriangleAlert, RefreshCw, ChevronDown } from 'lucide-react';
import { beijingDateTime } from '../../frontend/src/utils/beijingTime';
import './AgentModelOperations.css';
import { readResolvedAgentCards, cardIcon, cardCount, cardVersion, cardEmptyText, cardTitle, cardScope, cardRoute, reportStatus, metricLabels, cardDeviceFields, modelStatus, alertStatus, alertLevel, alertType, modelOperationMetrics, modelOperationLegacyMetrics, modelOperationDetails } from '../../frontend/src/utils/agentCards';
const resultIcons = { Tickets:ClipboardList, DataAnalysis:ChartNoAxesCombined, DocumentChecked:FileCheck, Monitor, Warning:TriangleAlert, Collection:Layers, Document:FileText };
function ResultCardIcon({card}) { const Icon = resultIcons[cardIcon(card)] || FileText; return <Icon size={19} aria-hidden="true"/>; }

export function AgentResultCards({ text, references = [], businessBase = '' }) {
  const [views, setViews] = useState([]), [loading, setLoading] = useState(false), [error, setError] = useState('');
  const generation = useRef(0);
  const readBusy = useRef(false);
  const activeRead = useRef(null);
  const snapshot = useRef([]);
  const referenceKey = JSON.stringify(references);
  async function refresh() {
    if (!references.length || readBusy.current) return;
    readBusy.current = true;
    const version = ++generation.current;
    const controller = new AbortController();
    activeRead.current = controller;
    setLoading(true); setError('');
    try {
      const response = await fetch(import.meta.env.VITE_AGENT_CARDS_URL || '/api/agent/cards/resolve', {
        method: 'POST', credentials: 'include', signal:controller.signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cards: references }),
      });
      if (!response.ok) { const failure = new Error('业务卡片读取未完成'); failure.status = response.status; throw failure; }
      const data = await response.json();
      if (version === generation.current) { const next = readResolvedAgentCards(data, references); snapshot.current = next; setViews(next); }
    } catch (failure) {
      if (version !== generation.current) return;
      if (failure.status === 401 || failure.status === 403) {
        snapshot.current = []; setViews([]);
        setError(failure.status === 401 ? '登录状态已失效，已清除旧卡片；请核对账号后重新读取。' : '当前账号无法读取这些卡片，已清除旧数据；请核对访问权限。');
      } else setError(snapshot.current.length ? '本次读取未完成，以下保留上次读取的快照，不代表当前业务状态。可重新读取，不会重新执行业务操作。' : '业务卡片暂未读出，请重新读取。此操作只核对业务资料，不重新调用模型或执行审批。');
    }
    finally { if (version === generation.current) { activeRead.current = null; readBusy.current = false; setLoading(false); } }
  }
  useEffect(() => { readBusy.current = false; snapshot.current = []; setViews([]); setError(''); setLoading(false); refresh(); return () => { generation.current++; activeRead.current?.abort(); activeRead.current = null; }; }, [referenceKey]);
  const date = value => value ? beijingDateTime(value) || '时间格式未知' : '—';
  const route = (type, id) => { const path = cardRoute(type, id); return path ? businessBase + path : undefined; };
  return <section className="agent-result" aria-label="助手业务结果">
    <div className="result-answer"><Markdown content={text || ''}/></div>
    {references.length > 0 && <><p className="result-freshness-note">回答保留生成时的内容，下方卡片按当前权限重新读取。</p><header className="result-heading"><span><Layers size={16} aria-hidden="true"/>业务卡片<span className="result-read-count">已有 {views.length} / {references.length} 张回执</span></span><Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={refresh}>重新读取</Button></header></>}
    {error ? <p role="alert" className="result-read-feedback" data-tone="warning"><TriangleAlert size={16} aria-hidden="true"/><span>{error}</span></p> : references.length > 0 && <p role="status" className="result-read-feedback" data-tone={loading ? 'loading' : 'info'}>{loading ? <RefreshCw size={16} aria-hidden="true"/> : <FileCheck size={16} aria-hidden="true"/>}<span>{loading ? views.length ? '正在重新核对，以下仍为上次读取的快照。' : '正在按当前账号权限读取业务数据。' : '下方为最近一次读取的快照，业务操作仍需进入对应页面核对。'}</span></p>}
    {views.map((card, index) => <article className="result-card" key={index + ':' + card.tool} aria-busy={loading}>
      <header><span className="result-card-symbol"><ResultCardIcon card={card}/></span><div className="result-card-heading"><strong>{cardTitle(card)}</strong><small>{cardScope(card.scope)||'访问范围未返回'}</small></div><StatusBadge domain="cardRead" code={card.status}/></header>
      {card.type === 'METRICS' && <><p className="card-note">按任务创建时间 · {date(card.from)} 至 {date(card.to)} · UTC+8</p><div className="card-metrics">{Object.entries(metricLabels).map(([key, label]) => <div key={key}><strong>{cardCount(card.metrics?.[key])}</strong><span>{label}</span></div>)}</div></>}
      {card.type === 'TASKS' && card.items?.map(task => <div className="card-record" key={task.taskId}><a href={route('TASKS', task.taskId)}>{task.taskId}</a><p><StatusBadge domain="detection" code={task.status}/> · 已处理 / 总图片 {cardCount(task.processedImages)} / {cardCount(task.totalImages)} · 缺陷 {cardCount(task.defectCount)}</p><p>设备 {task.deviceName || '未记录'} · <StatusBadge domain="review" code={task.reviewStatus}/></p></div>)}
      {card.type === 'REPORTS' && card.items?.map(report => <div className="card-record" key={report.reportId}><a href={route('REPORTS', report.reportId)}>{report.title||'未命名报告'}</a><p><StatusBadge domain="report" code={report.status} label={reportStatus(report.status)}/> · 版本 {cardVersion(report.version)} · 任务 {report.taskId||'未记录'}</p>{report.status === 'DRAFT' && <p className="draft-note">私人草稿尚未提交或审批 请到报告页面核对</p>}<a href={route('REPORTS', report.reportId)}>查看报告</a></div>)}
      {card.type === 'DEVICES' && <>{card.items?.map(device => <div className="card-record" key={device.deviceId}><a href={route('DEVICES', device.deviceId)}>{device.deviceCode || '设备 ' + device.deviceId}</a><dl className="card-device-states">{cardDeviceFields.map(field=><div key={field.key}><dt>{field.label}</dt><dd><StatusBadge domain={field.domain} code={device[field.key]}/></dd></div>)}</dl><a href={route('DEVICES', device.deviceId)}>查看设备</a></div>)}<p className="card-note">状态来自本次读取的设备记录，不是持续监控或当前健康证明。</p></>}
      {card.type === 'DEVICE_ALERTS' && <>{card.items?.map(alert => <div className="card-record" key={alert.alertId}><div className="card-alert-heading"><strong>{alert.alertCode || '告警 ' + alert.alertId}</strong><StatusBadge domain="deviceAlert" code={alert.status} label={alertStatus(alert.status)}/></div><div className="card-alert-classification"><span>{alertType(alert.type)}</span><StatusBadge domain="deviceAlertLevel" code={alert.level} label={alertLevel(alert.level)}/></div><p>设备 {alert.deviceCode || '未记录'}</p><dl className="card-record-facts"><dt>发生 · UTC+8</dt><dd>{date(alert.createdAt)}</dd><dt>记录更新 · UTC+8</dt><dd>{date(alert.updatedAt)}</dd></dl><details className="card-alert-identity"><summary>核对告警编号与类型代码<ChevronDown className="card-alert-chevron" size={13} aria-hidden="true"/></summary><dl className="card-record-facts"><dt>告警 ID</dt><dd>{alert.alertId}</dd><dt>设备 ID</dt><dd>{alert.deviceId||'未记录'}</dd><dt>类型代码</dt><dd>{alert.type||'未记录'}</dd></dl></details>{route('DEVICES', alert.deviceId) ? <a href={route('DEVICES', alert.deviceId)}>查看设备</a> : <p>设备关联已不可用</p>}</div>)}<p className="card-note">按告警记录展示，不代表设备当前仍故障或已修复。</p></>}
      {card.type === 'MODELS' && card.items?.map(model => <div className="card-record" key={model.modelId}><a href={route('MODELS', String(model.modelId))}>{model.name || '模型 ' + model.modelId}</a><p>版本 {model.version || '未记录'} · {modelStatus(model.status)} · {model.defaultModel === true ? '默认模型' : model.defaultModel === false ? '非默认模型' : '默认状态未知'}</p><a href={route('MODELS', String(model.modelId))}>查看模型</a></div>)}
      {card.type === 'MODEL_OPERATIONS' && card.items?.map(item => <div className="card-record model-operation" key={item.model.modelId}>
        <a href={route('MODEL_OPERATIONS', String(item.model.modelId))}>{item.model.name || '模型 ' + item.model.modelId}</a>
        <p>版本 {item.model.version || '未记录'} · {modelStatus(item.model.status)}</p>
        <div className="card-metrics operation-metrics">{modelOperationMetrics(item).map(metric => <div key={metric.label}><strong>{metric.value}</strong><span>{metric.label} 登记值</span></div>)}</div>
        {!!modelOperationLegacyMetrics(item).length && <details className="operation-disclosure"><summary>其他历史指标</summary><dl className="operation-details">{modelOperationLegacyMetrics(item).map(metric=><div key={metric.label}><dt>{metric.label}</dt><dd>{metric.value}</dd></div>)}</dl></details>}
        <details className="operation-disclosure"><summary>查看发布配置与登记信息</summary><dl className="operation-details">{modelOperationDetails(item).map(row => <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl></details>
        {!!item.invalidFields?.length && <p className="result-error">部分登记字段异常 请到模型页面核对</p>}
        <p className="card-note">指标为登记值，未检出率排除执行失败，Normal 检出也算检出。FPS 测试环境见模型详情；发布策略为配置记录，实际分流尚未核验。</p>
        <a href={route('MODEL_OPERATIONS', String(item.model.modelId))}>查看模型</a>
      </div>)}
      {card.type!=='METRICS'&&!card.items.length&&<p className="card-empty">{card.status==='OK'?<Files size={18} aria-hidden="true"/>:<TriangleAlert size={18} aria-hidden="true"/>}{cardEmptyText(card)}</p>}
      {card.message&&<p className={card.status === 'OK' ? 'card-note' : 'result-error'}>{card.message}</p>}<footer>卡片读取时间 {date(card.updatedAt)} · UTC+8</footer>
    </article>)}
  </section>;
}
