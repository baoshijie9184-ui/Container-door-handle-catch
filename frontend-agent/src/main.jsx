import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfigProvider, Layout, Typography, Tag, message } from 'antd';
import { RobotOutlined } from '@ant-design/icons';
import { Bubble, Sender } from '@agentscope-ai/chat';
import './styles.css';
import { readAnswer } from './aguiClient';

const API = import.meta.env.VITE_AGENT_API_URL || '/agui/run';
const LOGIN = import.meta.env.VITE_BUSINESS_LOGIN_URL || 'http://localhost:5173/login';

function App() {
  const [items, setItems] = useState([{ key: 'welcome', role: 'assistant', content: '你好，我是门把手检测助手。可以帮你分析检测记录、定位异常或生成整改建议。' }]);
  const [loading, setLoading] = useState(false);
  const [catalog, setCatalog] = useState(null);
  const [catalogError, setCatalogError] = useState('');
  const [threadId] = useState(() => crypto.randomUUID());
  useEffect(() => {
    const abort = new AbortController();
    fetch(API.replace(/\/run\/?$/, '/catalog'), { credentials: 'include', signal: abort.signal })
      .then(response => { if (!response.ok) throw new Error('请先登录检测系统，登录后刷新此页面'); return response.json(); })
      .then(setCatalog).catch(error => { if (error.name !== 'AbortError') setCatalogError(error.message); });
    return () => abort.abort();
  }, []);

  async function submit(text) {
    const query = text.trim();
    if (!query || loading || !catalog) return;
    const history = items.filter(item => item.key !== 'welcome' && item.key !== 'pending' && item.msgStatus !== 'error')
      .slice(-38).map(item => ({ id: item.key, role: item.role, content: item.content }));
    setItems((old) => [...old, { key: crypto.randomUUID(), role: 'user', content: query }, { key: 'pending', role: 'assistant', content: '正在分析…', loading: true }]);
    setLoading(true);
    try {
      const response = await fetch(API, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', 'X-Agent-Id': catalog.mainAgent }, body: JSON.stringify({ threadId, runId: crypto.randomUUID(), messages: [...history, { id: crypto.randomUUID(), role: 'user', content: query }] }) });
      const answer = await readAnswer(response, content => setItems(old => old.map(item => item.key === 'pending' ? { ...item, content, loading: false } : item)));
      setItems((old) => [...old.filter((item) => item.key !== 'pending'), { key: crypto.randomUUID(), role: 'assistant', content: answer }]);
    } catch (error) {
      setItems((old) => [...old.filter((item) => item.key !== 'pending'), { key: crypto.randomUUID(), role: 'assistant', content: `暂时无法连接 AgentScope：${error.message}`, msgStatus: 'error' }]);
      message.error('AgentScope 请求失败');
    } finally { setLoading(false); }
  }

  return <ConfigProvider theme={{ token: { colorPrimary: '#1677ff', borderRadius: 12 } }}><Layout className="agent-shell"><header className="agent-header"><RobotOutlined /><Typography.Title level={3}>{catalog?.role === 'SUPERVISOR' ? '主管工作助手' : '员工工作助手'}</Typography.Title><Tag color="blue">只读查询</Tag></header><main className="agent-main"><section className="chat-panel"><div className="bubble-list"><Bubble.List items={items} /></div><Sender disabled={!catalog} loading={loading} placeholder="输入检测问题，例如：查询最近的检测任务" onSubmit={submit} /></section><aside><Typography.Title level={5}>当前可用能力</Typography.Title>{catalog?.agents.map(agent => <p key={agent.id}>{agent.description}</p>)}{catalogError && <p>{catalogError}。<a href={LOGIN}>前往登录</a></p>}<Typography.Text type="secondary">创建、修改和审批请使用业务页面。</Typography.Text></aside></main></Layout></ConfigProvider>;
}

createRoot(document.getElementById('root')).render(<App />);
