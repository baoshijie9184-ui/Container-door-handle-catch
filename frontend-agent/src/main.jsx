import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfigProvider, Layout, Typography, Tag, message } from 'antd';
import { RobotOutlined } from '@ant-design/icons';
import { Bubble, Sender } from '@agentscope-ai/chat';
import './styles.css';

const API = import.meta.env.VITE_AGENT_API_URL || 'http://localhost:48080/agui/run';

function App() {
  const [items, setItems] = useState([{ key: 'welcome', role: 'assistant', content: '你好，我是门把手检测助手。可以帮你分析检测记录、定位异常或生成整改建议。' }]);
  const [loading, setLoading] = useState(false);

  async function submit(text) {
    const query = text.trim();
    if (!query || loading) return;
    setItems((old) => [...old, { key: crypto.randomUUID(), role: 'user', content: query }, { key: 'pending', role: 'assistant', content: '正在分析…', loading: true }]);
    setLoading(true);
    try {
      const response = await fetch(API, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' }, body: JSON.stringify({ threadId: crypto.randomUUID(), runId: crypto.randomUUID(), messages: [{ id: crypto.randomUUID(), role: 'user', content: query }], state: {}, tools: [], context: [] }) });
      if (!response.ok) throw new Error(`请求失败 (${response.status})`);
      const body = await response.text();
      const answer = body.split(/\n\n/).map((line) => line.replace(/^data:\s*/, '')).filter(Boolean).map((line) => { try { const e = JSON.parse(line); return e.delta || e.content || e.message?.content || ''; } catch { return ''; } }).join('') || body;
      setItems((old) => [...old.filter((item) => item.key !== 'pending'), { key: crypto.randomUUID(), role: 'assistant', content: answer }]);
    } catch (error) {
      setItems((old) => [...old.filter((item) => item.key !== 'pending'), { key: crypto.randomUUID(), role: 'assistant', content: `暂时无法连接 AgentScope：${error.message}`, msgStatus: 'error' }]);
      message.error('AgentScope 请求失败');
    } finally { setLoading(false); }
  }

  return <ConfigProvider theme={{ token: { colorPrimary: '#1677ff', borderRadius: 12 } }}><Layout className="agent-shell"><header className="agent-header"><RobotOutlined /><Typography.Title level={3}>DoorHandle Agent</Typography.Title><Tag color="blue">AgentScope Java 2.0</Tag></header><main className="agent-main"><section className="chat-panel"><div className="bubble-list"><Bubble.List items={items} /></div><Sender loading={loading} placeholder="输入检测问题，例如：分析最近一批次的异常记录" onSubmit={submit} /></section><aside><Typography.Title level={5}>能力范围</Typography.Title><p>检测记录分析</p><p>异常原因归纳</p><p>整改建议生成</p><Typography.Text type="secondary">接口：{API}</Typography.Text></aside></main></Layout></ConfigProvider>;
}

createRoot(document.getElementById('root')).render(<App />);
