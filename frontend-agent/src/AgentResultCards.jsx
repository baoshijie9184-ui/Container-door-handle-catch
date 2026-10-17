import React, { useEffect, useRef, useState } from 'react';
import { ReloadOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import './AgentModelOperations.css';
import { cardTitle, cardScope, cardRoute, reportStatus, metricLabels, modelStatus, deviceStatus, alertStatus, alertLevel, alertType, modelOperationMetrics, modelOperationDetails } from '../../frontend/src/utils/agentCards';

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
      {card.type === 'DEVICES' && card.items?.map(device => <div className="card-record" key={device.deviceId}><a href={route('DEVICES', device.deviceId)}>{device.deviceCode || '设备 ' + device.deviceId}</a><p>{deviceStatus(device.status)} · {deviceStatus(device.onlineStatus)}</p><p>PLC {deviceStatus(device.plcStatus)} · 相机 {deviceStatus(device.cameraStatus)} · 采集 {deviceStatus(device.captureStatus)}</p><a href={route('DEVICES', device.deviceId)}>查看设备</a></div>)}
      {card.type === 'DEVICE_ALERTS' && <>{card.items?.map(alert => <div className="card-record" key={alert.alertId}><strong>{alert.alertCode || '告警 ' + alert.alertId}</strong><p>{alertType(alert.type)} · {alertLevel(alert.level)} · {alertStatus(alert.status)}</p><p>设备 {alert.deviceCode || '未记录'}</p><p>发生 {date(alert.createdAt)} · 记录更新 {date(alert.updatedAt)}</p>{route('DEVICES', alert.deviceId) ? <a href={route('DEVICES', alert.deviceId)}>查看设备</a> : <p>设备关联已不可用</p>}</div>)}<p className="card-note">按告警记录展示 不代表设备当前仍故障或已修复</p></>}
      {card.type === 'MODELS' && card.items?.map(model => <div className="card-record" key={model.modelId}><a href={route('MODELS', String(model.modelId))}>{model.name || '模型 ' + model.modelId}</a><p>版本 {model.version || '未记录'} · {modelStatus(model.status)} · {model.defaultModel === true ? '默认模型' : model.defaultModel === false ? '非默认模型' : '默认状态未知'}</p><a href={route('MODELS', String(model.modelId))}>查看模型</a></div>)}
      {card.type === 'MODEL_OPERATIONS' && card.items?.map(item => <div className="card-record model-operation" key={item.model.modelId}>
        <a href={route('MODEL_OPERATIONS', String(item.model.modelId))}>{item.model.name || '模型 ' + item.model.modelId}</a>
        <p>版本 {item.model.version || '未记录'} · {modelStatus(item.model.status)}</p>
        <div className="card-metrics operation-metrics">{modelOperationMetrics(item).map(metric => <div key={metric.label}><strong>{metric.value}</strong><span>{metric.label} 登记值</span></div>)}</div>
        <details className="operation-disclosure"><summary>查看发布配置与登记信息</summary><dl className="operation-details">{modelOperationDetails(item).map(row => <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl></details>
        {!!item.invalidFields?.length && <p className="result-error">部分登记字段异常 请到模型页面核对</p>}
        <p className="card-note">指标为登记值 发布策略为配置记录 实际分流尚未核验</p>
        <a href={route('MODEL_OPERATIONS', String(item.model.modelId))}>查看模型</a>
      </div>)}
      <p className={card.status === 'OK' ? 'card-note' : 'result-error'}>{card.message}</p><footer>更新 {date(card.updatedAt)}</footer>
    </article>)}
  </section>;
}
