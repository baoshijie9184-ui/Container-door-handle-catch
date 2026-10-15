import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Button, Select, ConfigProvider, Layout, Typography, Tag, message } from 'antd';
import { RobotOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { Bubble, Sender } from '@agentscope-ai/chat';
import './styles.css';
import { readAnswer } from './aguiClient';
import { AgentResultCards } from './AgentResultCards';
import { validCardReference } from '../../frontend/src/utils/agentCards';
import { skillCommandOptions } from '../../frontend/src/utils/skillCommands';
import { readSession, sessionItems } from './sessionClient';
import { skillInstallNavigation } from '../../frontend/src/utils/skillInstallNavigation';

const API = import.meta.env.VITE_AGENT_API_URL || '/agui/run';
const LOGIN = new URL(import.meta.env.VITE_BUSINESS_LOGIN_URL || 'http://127.0.0.1:3001/#/login', window.location.href).toString();
const ACTIONS = LOGIN.replace(/#.*$/, '') + '#/agent/actions';
const MEMORIES=LOGIN.replace(/#.*$/,'')+'#/agent/memory';
const REPORTS = LOGIN.replace(/#.*$/, '') + '#/quality/reports';
const COMMANDS = new URL('/api/agent/commands', new URL(API, window.location.href)).toString();
const SESSIONS = new URL('/api/chat-assistant/sessions',new URL(API,window.location.href)).toString();
const BusinessCardBubble = ({ data }) => <AgentResultCards {...data} />;
const SkillInstallLinkBubble=({data})=><p style={{whiteSpace:'pre-wrap'}}>{data.before}<a href={data.href}>{data.label}</a>{data.after}</p>;

function App() {
  const [items, setItems] = useState([{ key: 'welcome', role: 'assistant', content: '你好，我是门把手检测助手。可以帮你分析检测记录、定位异常或生成整改建议。' }]);
  const [loading, setLoading] = useState(false);
  const [catalog, setCatalog] = useState(null);
  const [catalogError, setCatalogError] = useState('');
  const [modelCatalog, setModelCatalog] = useState(null);
  const [draft, setDraft] = useState('');
  const [commandCatalog, setCommandCatalog] = useState(null);
  const [commandError, setCommandError] = useState('');
  const commandGeneration = useRef(0);
  async function refreshCommands(signal) {
    const generation = ++commandGeneration.current;
    setCommandCatalog(null);setCommandError('');
    try {const response=await fetch(COMMANDS,{credentials:'include',signal});if(!response.ok)throw new Error('技能目录暂不可用 可用 /help 查看命令帮助');const value=await response.json();if(generation===commandGeneration.current)setCommandCatalog(value);}
    catch(error){if(error.name!=='AbortError'&&generation===commandGeneration.current){setCommandCatalog(null);setCommandError(error.message);}}
  }
  const [threadId,setThreadId]=useState('');
  const [sessions,setSessions]=useState([]);
  const [sessionLoading,setSessionLoading]=useState(true);
  const [sessionError,setSessionError]=useState('');
  const currentSession=useRef('');
  const sessionGeneration=useRef(0);
  const busy=useRef(false);
  const cardView=(text,references)=>[{code:'BusinessResults',component:BusinessCardBubble,data:{text,references,businessBase:LOGIN.replace(/#.*$/,'')}}];
  async function loadSession(id) {
    if(busy.current)return;
    const generation=++sessionGeneration.current;
    setSessionLoading(true);setSessionError('');
    try{
      const list=await readSession(await fetch(SESSIONS,{credentials:'include',cache:'no-store'}));
      let selected=id||list[0]?.sessionId;
      const session=selected?await readSession(await fetch(SESSIONS+'/'+encodeURIComponent(selected),{credentials:'include',cache:'no-store'})):await readSession(await fetch(SESSIONS,{method:'POST',credentials:'include'}));
      if(generation!==sessionGeneration.current)return;
      currentSession.current=session.sessionId;setThreadId(session.sessionId);setSessions(list.some(s=>s.sessionId===session.sessionId)?list:[session,...list]);
      const url=new URL(window.location.href);url.searchParams.set('sessionId',session.sessionId);window.history.replaceState(null,'',url.pathname+url.search+url.hash);
      setItems(sessionItems(session.messages,cardView));
    }catch(error){if(generation===sessionGeneration.current){setSessionError(error.message);setItems([]);setThreadId('');currentSession.current='';setSessions([]);}}
    finally{if(generation===sessionGeneration.current)setSessionLoading(false);}
  }
  async function newSession(){
    if(busy.current||sessionLoading)return;
    setSessionLoading(true);
    try{const session=await readSession(await fetch(SESSIONS,{method:'POST',credentials:'include'}));await loadSession(session.sessionId);}
    catch(error){setSessionError(error.message);setSessionLoading(false);}
  }
  useEffect(() => {
    const abort = new AbortController();
    loadSession(new URLSearchParams(window.location.search).get('sessionId'));
    const focus=()=>{if(!busy.current)loadSession(currentSession.current);};window.addEventListener('focus',focus);
    refreshCommands(abort.signal);
    fetch(API.replace(/\/run\/?$/, '/catalog'), { credentials: 'include', signal: abort.signal })
      .then(response => { if (!response.ok) throw new Error('请先登录检测系统，登录后刷新此页面'); return response.json(); })
      .then(setCatalog).catch(error => { if (error.name !== 'AbortError') setCatalogError(error.message); });
    fetch(API.replace(/\/run\/?$/, '/models'), { credentials: 'include', signal: abort.signal })
      .then(response => { if (!response.ok) throw new Error('模型信息暂不可用'); return response.json(); })
      .then(setModelCatalog).catch(() => {});
    const modelRefresh = setInterval(() => {
      fetch(API.replace(/\/run\/?$/, '/models'), { credentials: 'include', signal: abort.signal })
        .then(response => { if (!response.ok) throw new Error('模型信息暂不可用'); return response.json(); })
        .then(setModelCatalog).catch(() => {});
    }, 30000);
    return () => { sessionGeneration.current++;commandGeneration.current++;clearInterval(modelRefresh); abort.abort();window.removeEventListener('focus',focus); };
  }, []);

  async function submit(text) {
    const query = text.trim();
    if (!query || busy.current || sessionLoading || !threadId || !catalog) return;
    busy.current=true;
    setDraft('');
    setItems((old) => [...old, { key: crypto.randomUUID(), role: 'user', content: query }, { key: 'pending', role: 'assistant', content: '正在分析…', loading: true }]);
    setLoading(true);
    try {
      const response = await fetch(API, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', 'X-Agent-Id': catalog.mainAgent }, body: JSON.stringify({ threadId, runId: crypto.randomUUID(), messages: [{ id: crypto.randomUUID(), role: 'user', content: query }] }) });
      let references = [];
      const answer = await readAnswer(response, content => setItems(old => old.map(item => item.key === 'pending' ? { ...item, content, loading: false } : item)), value => {
        if (value?.version === 1 && Array.isArray(value.cards) && value.cards.length <= 8 && value.cards.every(validCardReference)) references = value.cards;
      });
      setItems((old) => [...old.filter((item) => item.key !== 'pending'), { key: crypto.randomUUID(), role: 'assistant', text: answer,
        content: references.length ? '' : answer,
        cards: references.length ? [{ code: 'BusinessResults', component: BusinessCardBubble, data: { text: answer, references, businessBase: LOGIN.replace(/#.*$/, '') } }] : undefined }]);
    } catch (error) {
      setDraft(query);
      setItems((old) => [...old.filter((item) => item.key !== 'pending'), { key: crypto.randomUUID(), role: 'assistant', content: `暂时无法连接 AgentScope：${error.message}`, msgStatus: 'error' }]);
      message.error('AgentScope 请求失败');
    } finally { busy.current=false;setLoading(false);await loadSession(threadId); }
  }

  const displayedItems=items.map(item=>{if(item.role!=='assistant'||typeof item.content!=='string')return item;const link=skillInstallNavigation(item.content,LOGIN);return link?{...item,content:'',cards:[{code:'SkillInstallNavigation',component:SkillInstallLinkBubble,data:link}]}:item;});
  return <ConfigProvider theme={{ token: { colorPrimary: '#1677ff', borderRadius: 12 } }}><Layout className="agent-shell"><header className="agent-header"><RobotOutlined /><Typography.Title level={3}>{catalog?.role === 'SUPERVISOR' ? '主管工作助手' : '员工工作助手'}</Typography.Title><Tag color="blue">{catalog?.reportDraftsEnabled ? '查询与本人报告草稿' : catalog?.mode === 'CONFIRMABLE' ? '质检分配需确认' : '只读查询'}</Tag></header><main className="agent-main"><section className="chat-panel"><div className="session-toolbar"><Select aria-label="选择会话" value={threadId||undefined} options={sessions.map(s=>({value:s.sessionId,label:s.title||"智能助手对话"}))} onChange={loadSession} disabled={loading||sessionLoading} placeholder="选择会话" /><Button aria-label="新建对话" icon={<PlusOutlined aria-hidden="true" />} onClick={newSession} disabled={loading||sessionLoading}>新建对话</Button><Button icon={<ReloadOutlined />} aria-label="刷新会话" onClick={()=>loadSession(threadId)} disabled={loading||sessionLoading}>刷新</Button></div>{sessionError&&<p role="alert" className="session-error">{sessionError}</p>}<div className="bubble-list"><Bubble.List items={displayedItems} /></div><Sender disabled={!catalog||!threadId||sessionLoading} loading={loading} value={draft} onChange={setDraft} onFocus={()=>refreshCommands()} suggestions={skillCommandOptions(commandCatalog).map(item=>({value:item.value.slice(1).trim(),label:item.label+' · '+item.description}))} placeholder="输入问题 或输入 / 选择技能命令" onSubmit={submit} /><p className="command-hint">输入 / 选择命令 可用 /skills 查看技能 · 会话与主站共用 记忆按账号隔离</p>{commandError&&draft.startsWith('/')&&<p className="command-hint" role="status">{commandError}</p>}</section><aside>{modelCatalog && <section aria-label="模型配置"><Typography.Title level={5}>模型配置</Typography.Title>{modelCatalog.models.map(model => <p key={model.id}>{model.model} <Tag color={model.selected ? 'blue' : undefined}>{model.selected ? '默认模型' : model.configured ? '已配置' : '未配置'}</Tag>{model.healthState === 'OPEN' && <Tag color="red">暂时停用 · {model.retryAfterSeconds} 秒后重试</Tag>}{['HALF_OPEN', 'PROBE_READY'].includes(model.healthState) && <Tag color="blue">等待恢复验证</Tag>}</p>)}<Typography.Text type="secondary">{modelCatalog.fallbackEnabled ? `自动切换已开启 · ${modelCatalog.firstTokenTimeoutMs / 1000} 秒未响应时尝试备用模型` : '自动切换未开启'}</Typography.Text>{modelCatalog.fallbackEnabled && modelCatalog.fallbackModels?.length > 0 && <p>备用顺序：{modelCatalog.fallbackModels.map(id => id.slice(id.indexOf(':') + 1)).join(' → ')}</p>}</section>}<p><a href={MEMORIES}>个人记忆与保存设置</a></p><Typography.Title level={5}>当前可用能力</Typography.Title>{catalog?.agents.map(agent => <p key={agent.id}>{agent.description}</p>)}{catalogError && <p>{catalogError}。<a href={LOGIN}>前往登录</a></p>}{catalog?.mode === 'CONFIRMABLE' && <p>分配提议保存后仍未执行业务操作。<a href={ACTIONS}>查看并确认操作</a></p>}{catalog?.reportsEnabled && <p>助手可查询授权报告{catalog?.reportDraftsEnabled ? '并保存本人草稿' : ''}，提交和审批到<a href={REPORTS}>报告与审批</a>。</p>}<Typography.Text type="secondary">私人草稿尚未提交或审批，其他业务写入请使用业务页面。</Typography.Text></aside></main></Layout></ConfigProvider>;
}

createRoot(document.getElementById('root')).render(<App />);
