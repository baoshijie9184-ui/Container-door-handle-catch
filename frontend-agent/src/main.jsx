import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Button, Select, ConfigProvider, Layout, message } from 'antd';
import { RobotOutlined, PlusOutlined } from '@ant-design/icons';
import { PanelLeft, PanelRight, ArrowUpRight, ArrowDown, ScanLine, ClipboardCheck, ChartNoAxesCombined, Compass, BrainCircuit, ArrowLeft, X, ShieldCheck, Blocks, Plug, RefreshCw } from 'lucide-react';
import { Bubble, Sender } from '@agentscope-ai/chat';
import '../../frontend/src/assets/design-tokens.css';
import '../../frontend/src/assets/status-badge.css';
import './styles.css';
import '../../frontend/src/assets/agent-appearance.css';
import '../../frontend/src/assets/agent-unified.css';
import { readAnswer } from './aguiClient';
import { AgentResultCards } from './AgentResultCards';
import { validCardReference } from '../../frontend/src/utils/agentCards';
import { skillCommandOptions } from '../../frontend/src/utils/skillCommands';
import { readSession, sessionItems } from './sessionClient';
import { ConversationControls } from './ConversationControls';
import {ComposerToolbar} from './ComposerToolbar';
import {ChatFileReferences} from './ChatFileReferences';
import {splitFileReferences} from '../../frontend/src/utils/chatFileReferences';
import { AgentWorkbenchPanel } from './AgentWorkbenchPanel';
import { AgentActionList } from './AgentActionList';
import { skillInstallNavigation } from '../../frontend/src/utils/skillInstallNavigation';
import { SessionHistory } from './SessionHistory';
import AgentModelOverview from './AgentModelOverview';
import StatusBadge from './StatusBadge';
import {readAgentRoleCatalog,readAgentModelCatalog} from '../../frontend/src/utils/agentCatalogPresentation';
import { AgentErrorBoundary } from './AgentErrorBoundary';
import {useReadableMessageRegions} from './useReadableMessageRegions';

const API = import.meta.env.VITE_AGENT_API_URL || '/agui/run';
const LOGIN = new URL(import.meta.env.VITE_BUSINESS_LOGIN_URL || '/#/login', window.location.href).toString();
const ACTIONS = LOGIN.replace(/#.*$/, '') + '#/agent/actions';
const MEMORIES=LOGIN.replace(/#.*$/,'')+'#/agent/memory';
const BUSINESS = LOGIN.replace(/#.*$/, '') + '#/home';
const TRACE = LOGIN.replace(/#.*$/, '') + '#/agent/trace';
const REPORTS = LOGIN.replace(/#.*$/, '') + '#/quality/reports';
const OPERATIONS_AUDIT = LOGIN.replace(/#.*$/, '') + '#/operations/audit';
const COMMANDS = new URL('/api/agent/commands', new URL(API, window.location.href)).toString();
const SESSIONS = new URL('/api/chat-assistant/sessions',new URL(API,window.location.href)).toString();
const CONVERSATION_CONTROLS = new URL('/api/agent/conversations',new URL(API,window.location.href)).toString();
const BusinessCardBubble = ({ data }) => <AgentResultCards {...data} />;
const SkillInstallLinkBubble=({data})=><p style={{whiteSpace:'pre-wrap'}}>{data.before}<a href={data.href}>{data.label}</a>{data.after}</p>;

function App() {
  const [items, setItems] = useState([]);
  const [controlState,setControlState]=useState({enabled:false,run:null});
  const controlsRef=useRef(null);
  const resourcesRef=useRef(null);
  const [sidebarOpen, setSidebarOpen] = useState(window.innerWidth > 900);
  const [infoOpen, setInfoOpen] = useState(false);
  const [infoTab,setInfoTab]=useState('workspace');
  useEffect(()=>{if(['WAITING_PLAN','WAITING_INPUT','AWAITING_RECOVERY'].includes(controlState.run?.phase)){setInfoOpen(true);setInfoTab('workspace')}},[controlState.run?.phase]);
  const senderRef = useRef(null);
  const infoToggleRef = useRef(null);
  const sidebarToggleRef = useRef(null);
  const transcriptRef = useRef(null);
  const followTranscript = useRef(true);
  const [showTranscriptReturn, setShowTranscriptReturn] = useState(false);
  function handleTranscriptScroll(event) {
    const el = event.currentTarget;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 72;
    followTranscript.current = nearBottom;
    setShowTranscriptReturn(!nearBottom);
  }
  function returnToLatest() {
    followTranscript.current = true;
    setShowTranscriptReturn(false);
    if (transcriptRef.current) transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
  }
  useEffect(() => {
    const resize = () => { if (window.innerWidth <= 900) { setSidebarOpen(false); setInfoOpen(false); } };
    const dismiss = event => { if(event.target?.closest?.('[role="dialog"]')||document.querySelector('.ant-modal-wrap:not([style*="display: none"])'))return; if (event.key === 'Escape') {
      if (infoOpen) { setInfoOpen(false); infoToggleRef.current?.focus(); }
      else if (sidebarOpen && window.innerWidth <= 900) { setSidebarOpen(false); sidebarToggleRef.current?.focus(); }
    } };
    window.addEventListener('resize', resize); window.addEventListener('keydown', dismiss);
    return () => { window.removeEventListener('resize', resize); window.removeEventListener('keydown', dismiss); };
  }, [infoOpen, sidebarOpen]);
  useEffect(() => {
    if (followTranscript.current && transcriptRef.current) transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
  }, [items, controlState.run?.text]);

  const [loading, setLoading] = useState(false);
  const [catalog, setCatalog] = useState(null);
  const [catalogError, setCatalogError] = useState('');
  const [modelCatalog, setModelCatalog] = useState(null);
  const [catalogLoading,setCatalogLoading]=useState(true),[modelCatalogLoading,setModelCatalogLoading]=useState(true);
  const [modelCatalogError,setModelCatalogError]=useState('');
  const [catalogAuthRequired,setCatalogAuthRequired]=useState(false),[modelAuthRequired,setModelAuthRequired]=useState(false);
  const catalogRequests=useRef({roles:null,models:null}),catalogVersions=useRef({roles:0,models:0}),catalogAlive=useRef(true),catalogAbort=useRef(null);
  function readServiceCatalog(kind,signal=catalogAbort.current?.signal){
    if(!catalogAlive.current || signal?.aborted)return Promise.resolve();
    const existing=catalogRequests.current[kind];
    if(existing && existing.signal===signal)return existing.promise;
    const version=++catalogVersions.current[kind],pending={signal,promise:null};
    catalogRequests.current[kind]=pending;
    const model=kind==='models',setReading=model?setModelCatalogLoading:setCatalogLoading,setError=model?setModelCatalogError:setCatalogError,setAuth=model?setModelAuthRequired:setCatalogAuthRequired;
    const active=()=>catalogAlive.current && catalogVersions.current[kind]===version && !signal?.aborted;
    setReading(true);setError('');
    if(!model)setCatalog(null);
    pending.promise=(async()=>{
      try{
        const response=await fetch(API.replace(/\/run\/?$/,model?'/models':'/catalog'),{credentials:'include',signal,cache:'no-store'});
        if(!response.ok){const failure=new Error(model?'模型目录暂不可读取':'能力目录暂不可读取');failure.status=response.status;throw failure;}
        const value=(model?readAgentModelCatalog:readAgentRoleCatalog)(await response.json());
        if(active()){setAuth(false);(model?setModelCatalog:setCatalog)(value);}
      }catch(failure){
        if(active() && failure.name!=='AbortError'){
          const denied=[401,403].includes(failure.status);
          setAuth(denied);setError(denied?'当前账号需要重新登录或核对目录访问权限':failure instanceof TypeError?'网络请求未完成，请手动重新读取目录':failure instanceof SyntaxError?'目录响应未完整解析，请重新读取':failure.message || (model?'模型目录读取失败，请重新核对':'能力目录读取失败，请重新核对'));
          if(denied)(model?setModelCatalog:setCatalog)(null);
        }
      }finally{
        if(catalogRequests.current[kind]===pending)catalogRequests.current[kind]=null;
        if(active())setReading(false);
      }
    })();
    return pending.promise;
  }
  const refreshServiceCatalogs=()=>Promise.allSettled([readServiceCatalog('roles'),readServiceCatalog('models')]);
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
  useReadableMessageRegions(transcriptRef,threadId);
  const [sessions,setSessions]=useState([]);
  const [sessionLoading,setSessionLoading]=useState(true);
  const [sessionError,setSessionError]=useState('');
  const currentSession=useRef('');
  const sessionGeneration=useRef(0);
  const sessionMetadataVersion=useRef(0);
  const busy=useRef(false);
  const cardView=(text,references)=>[{code:'BusinessResults',component:BusinessCardBubble,data:{text,references,businessBase:LOGIN.replace(/#.*$/,'')}}];
  async function refreshControlHistory(sessionId){try{
    const session=await readSession(await fetch(SESSIONS+'/'+encodeURIComponent(sessionId),{credentials:'include',cache:'no-store'}));
    if(currentSession.current===sessionId)setItems(sessionItems(session.messages,cardView));
  }catch{if(currentSession.current===sessionId)setSessionError('会话消息暂不可读取，请刷新核对')}}
  async function loadSession(id) {
    if(busy.current)return;
    const generation=++sessionGeneration.current;
    const metadataVersion=sessionMetadataVersion.current;
    const refreshingCurrent = !!id && id === currentSession.current;
    if (!refreshingCurrent) setSessionLoading(true);
    setSessionError('');
    try{
      const list=await readSession(await fetch(SESSIONS,{credentials:'include',cache:'no-store'}));
      let selected=id||list[0]?.sessionId;
      const session=selected?await readSession(await fetch(SESSIONS+'/'+encodeURIComponent(selected),{credentials:'include',cache:'no-store'})):await readSession(await fetch(SESSIONS,{method:'POST',credentials:'include'}));
      if(generation!==sessionGeneration.current)return;
      if(currentSession.current!==session.sessionId){setDraft('');followTranscript.current=true;setShowTranscriptReturn(false);}currentSession.current=session.sessionId;setThreadId(session.sessionId);
      const nextSessions=list.some(s=>s.sessionId===session.sessionId)?list:[session,...list];
      setSessions(current=>metadataVersion===sessionMetadataVersion.current?nextSessions:nextSessions.map(row=>{const latest=current.find(value=>value.sessionId===row.sessionId);return latest?{...row,title:latest.title,pinned:latest.pinned}:row;}));
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
    catalogAlive.current=true;catalogAbort.current=abort;
    readServiceCatalog('roles',abort.signal);readServiceCatalog('models',abort.signal);
    const modelRefresh=setInterval(()=>readServiceCatalog('models',abort.signal),30000);
    return () => { catalogAlive.current=false;catalogVersions.current.roles++;catalogVersions.current.models++;catalogRequests.current={roles:null,models:null};sessionGeneration.current++;commandGeneration.current++;clearInterval(modelRefresh); abort.abort();window.removeEventListener('focus',focus); };
  }, []);

  async function submit(text) {
    if(resourcesRef.current?.busy() || catalogAuthRequired || modelAuthRequired)return;
    const query = resourcesRef.current?.content(text)||text.trim();
    const selectedSession=currentSession.current
    const controlled=await controlsRef.current?.ready()
    if(selectedSession!==currentSession.current)return
    if(controlled){
      if(!query)return;returnToLatest();const sessionId=currentSession.current;setDraft('');
      try{await controlsRef.current.submit(query);if(currentSession.current===sessionId)resourcesRef.current?.clear()}catch{if(currentSession.current===sessionId)setDraft(current=>current||query)}return;
    }
    if (!query || busy.current || sessionLoading || !threadId || !catalog) return;
    returnToLatest();
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
      resourcesRef.current?.clear();
      setItems((old) => [...old.filter((item) => item.key !== 'pending'), { key: crypto.randomUUID(), role: 'assistant', text: answer,
        content: references.length ? '' : answer,
        cards: references.length ? [{ code: 'BusinessResults', component: BusinessCardBubble, data: { text: answer, references, businessBase: LOGIN.replace(/#.*$/, '') } }] : undefined }]);
    } catch (error) {
      setDraft(query);
      setItems((old) => [...old.filter((item) => item.key !== 'pending'), { key: crypto.randomUUID(), role: 'assistant', content: `暂时无法连接 AgentScope：${error.message}`, msgStatus: 'error' }]);
      message.error('AgentScope 请求失败');
    } finally { busy.current=false;setLoading(false);await loadSession(threadId); }
  }

  const visibleItems=controlState.run?.text&&controlState.run.phase!=='IDLE'?[...items,{key:'control-preview',role:'assistant',content:controlState.run.text}]:items;
  const displayedItems=visibleItems.map(item=>{if(typeof item.content!=='string')return item;const files=splitFileReferences(item.content,item.role);if(files.ids.length)return {...item,content:'',cards:[{code:'ChatFileReferences',component:ChatFileReferences,data:{...files,sessionId:threadId,base:new URL(API,window.location.href).origin}}]};if(item.role!=='assistant')return item;const link=skillInstallNavigation(item.content,LOGIN);return link?{...item,content:'',cards:[{code:'SkillInstallNavigation',component:SkillInstallLinkBubble,data:link}]}:item;});
  const activeSession = sessions.find(session => session.sessionId === threadId);
  const prompts = [
    { icon: ScanLine, title: '查看检测进度', description: '最近任务与处理状态', query: '查询最近的检测任务和处理进度' },
    { icon: ClipboardCheck, title: '梳理质检记录', description: '整理有权限查看的质检结果', query: '查询我有权限查看的质检记录' },
    { icon: ChartNoAxesCombined, title: '了解工作统计', description: '本周检测与缺陷情况', query: '查询本周工作统计和缺陷数量' },
    { icon: Compass, title: '找到业务入口', description: '批次、工单与报告入口', query: '显示系统业务地图和功能入口' },
  ];
  const prepareQuestion = query => { setDraft(query); senderRef.current?.focus?.(); };
  const workspaceResources=[
    {title:'技能 Skills',note:'查看技能与安装记录',path:'/agent/skills',icon:Blocks},
    {title:'固定 Fetch MCP',note:'查看本人安装、启用与执行状态',path:'/agent/mcp',icon:Plug},
    {title:'资源市场',note:'查看外部资源目录与接入条件',path:'/agent/markets',icon:Compass},
    {title:'个人记忆',note:'查看和管理本人记忆',path:'/agent/memory',icon:BrainCircuit},
    {title:'执行与调研',note:'工具轨迹、模型路由与来源',path:'/agent/trace'+(threadId?'?sessionId='+encodeURIComponent(threadId):''),icon:ChartNoAxesCombined},
  ];
  const infoTabKey=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const index=event.key==='Home'?0:event.key==='End'?1:infoTab==='workspace'?1:0;setInfoTab(index?'models':'workspace');event.currentTarget.querySelectorAll('[role="tab"]')[index]?.focus();};
  return <ConfigProvider theme={{ token: { colorPrimary: '#2563eb', colorSuccess: '#15803d', colorWarning: '#b45309', colorError: '#dc2626', colorText: '#0f172a', colorTextSecondary: '#475569', colorBorder: '#e2e8f0', borderRadius: 8, fontFamily: '"Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif', motionDurationMid: '0.2s' } }}>
    <Layout className={`agent-shell ${sidebarOpen ? 'with-sessions' : ''} ${infoOpen ? 'with-info' : ''}`}>
      <nav id="agent-sessions" className="session-sidebar" aria-label="对话历史" hidden={!sidebarOpen}>
        <a className="agent-brand" href={BUSINESS}><span className="brand-symbol"><ScanLine size={20} /></span><span>DoorHandle<strong>智能工作空间</strong></span></a>
        <Button className="new-session" aria-label="新建对话" type="primary" icon={<PlusOutlined aria-hidden="true" />} onClick={newSession} disabled={loading||sessionLoading}>新建对话</Button>
        <SessionHistory sessions={sessions} selectedId={threadId} disabled={loading||sessionLoading} loading={sessionLoading} error={sessionError} currentTaskActive={!!controlState.run&&controlState.run.phase!=='IDLE'} base={SESSIONS} traceBase={TRACE} businessBase={LOGIN.replace(/#.*$/,'')} onSelect={id=>{loadSession(id);if(window.innerWidth<=900)setSidebarOpen(false);}} onRefresh={()=>loadSession(threadId)} onChanged={(id,patch)=>{sessionMetadataVersion.current++;setSessions(current=>current.map(session=>session.sessionId===id?{...session,...patch}:session));}}/>
        <div className="sidebar-links"><a href={TRACE+(threadId?'?sessionId='+encodeURIComponent(threadId):'')}><ChartNoAxesCombined size={16} />执行追溯</a><a href={MEMORIES}><BrainCircuit size={16} />个人记忆</a><a href={REPORTS}><ClipboardCheck size={16} />报告与审批</a><a href={OPERATIONS_AUDIT}><ShieldCheck size={16} />操作与交付审计</a><a href={BUSINESS}><ArrowLeft size={16} />返回业务系统</a></div>
        <p className="account-note"><ShieldCheck size={14} />会话与记忆按账号隔离</p>
      </nav>
      {!sidebarOpen&&<nav className="agent-rail" aria-label="Agent 快捷导航"><Button type="text" aria-label="展开会话列表" icon={<PanelLeft size={18}/>} onClick={()=>setSidebarOpen(true)}/><Button type="text" aria-label="新建对话" disabled={loading||sessionLoading} icon={<PlusOutlined/>} onClick={newSession}/><div/><a href={TRACE+(threadId?'?sessionId='+encodeURIComponent(threadId):'')} aria-label="执行追溯"><ChartNoAxesCombined size={18}/></a><a href={BUSINESS} aria-label="返回业务系统"><ArrowLeft size={18}/></a></nav>}
      {sidebarOpen && <button className="sidebar-scrim" aria-label="收起会话列表" onClick={()=>setSidebarOpen(false)} />}
      <main className="agent-main">
        <header className="agent-header">
          <Button ref={sidebarToggleRef} type="text" aria-label={sidebarOpen?'收起会话列表':'展开会话列表'} aria-expanded={sidebarOpen} aria-controls="agent-sessions" icon={<PanelLeft size={18} />} onClick={()=>setSidebarOpen(!sidebarOpen)} />
          <div className="conversation-heading"><h1>{activeSession?.title||'智能对话助手'}</h1><span>{catalog?.role === 'SUPERVISOR' ? '主管工作助手' : catalog ? '员工工作助手' : '检测与质检工作助手'}</span></div>
          {catalog && <span className="capability-tag"><StatusBadge domain="agentMode" code={catalog.mode}/></span>}
          <Button ref={infoToggleRef} className="info-toggle" type="text" aria-label={infoOpen?'收起助手信息':'查看助手信息'} aria-expanded={infoOpen} aria-controls="agent-info" icon={<PanelRight size={18} />} onClick={()=>setInfoOpen(!infoOpen)} />
        </header>
        <section className="chat-panel" aria-label="智能对话">
          <div className="session-toolbar"><Select aria-label="选择会话" value={threadId||undefined} options={sessions.map(s=>({value:s.sessionId,label:s.title||"智能助手对话"}))} onChange={loadSession} disabled={loading||sessionLoading} placeholder="选择会话" /><Button aria-label="新建对话" icon={<PlusOutlined aria-hidden="true" />} onClick={newSession} disabled={loading||sessionLoading}>新建</Button></div>
          {sessionError&&<p role="alert" className="session-error">{sessionError} <a href={LOGIN}>前往登录</a> · <button onClick={()=>loadSession(threadId)}>重试</button></p>}
          <div ref={transcriptRef} className="bubble-list" onScroll={handleTranscriptScroll}>
            {!items.length && !sessionLoading && <div className="chat-welcome"><span className="welcome-symbol"><RobotOutlined /></span><span className="welcome-eyebrow">DOORHANDLE ASSISTANT</span><h2>今天，想先解决什么？</h2><p>查看检测结果、追溯质检任务，或一起梳理下一步</p><div className="welcome-prompts">{prompts.map(({icon: Icon,...prompt})=><button type="button" key={prompt.title} disabled={!catalog||!threadId} onClick={()=>prepareQuestion(prompt.query)}><span className="prompt-icon"><Icon size={19} /></span><strong>{prompt.title}</strong><span>{prompt.description}</span><ArrowUpRight className="prompt-arrow" size={15} /></button>)}</div></div>}
            {sessionLoading ? <p className="loading-note" role="status">正在加载你的对话…</p> : items.length > 0 && <Bubble.List classNames={{wrapper: 'conversation-transcript', list: 'conversation-messages'}} items={displayedItems} />}
          </div>
          {showTranscriptReturn && items.length > 0 && <div className="transcript-return"><button type="button" onClick={returnToLatest}><ArrowDown size={16} aria-hidden="true"/>回到最新消息</button></div>}
          {(catalogError || catalogAuthRequired || modelAuthRequired) && <p className="agent-service-error agent-service-gate" role="alert">{catalogError || modelCatalogError || '正在核对目录访问权限'}<button type="button" disabled={catalogLoading || modelCatalogLoading} onClick={refreshServiceCatalogs}><RefreshCw size={13} aria-hidden="true"/>重新读取目录</button>{(catalogAuthRequired || modelAuthRequired) && <a href={LOGIN}>前往登录</a>}</p>}
          <ConversationControls ref={controlsRef} sessionId={threadId} base={CONVERSATION_CONTROLS} onSnapshot={setControlState} onRefresh={refreshControlHistory}/>
          <div className="composer-area"><div className="resource-input"><Sender className="harness-composer-sender" actions={()=>null} styles={{input:{minHeight:64}}} ref={senderRef} disabled={!catalog||!threadId||sessionLoading||catalogAuthRequired||modelAuthRequired} loading={loading} value={draft} onChange={setDraft} onFocus={()=>refreshCommands()} suggestions={skillCommandOptions(commandCatalog).map(item=>({value:item.value.slice(1).trim(),label:item.label+' · '+item.description}))} placeholder="输入问题 或输入 / 选择技能命令" onSubmit={submit} /><ComposerToolbar ref={resourcesRef} sessionId={threadId} base={new URL(API,window.location.href).origin} locked={loading||!!controlState.run&&controlState.run.phase!=='IDLE'} run={controlState.run} draft={draft} onDraft={setDraft} onSend={submit} onStop={()=>controlsRef.current?.cancel()} disabled={!catalog||!threadId||sessionLoading||catalogAuthRequired||modelAuthRequired} onUpload={()=>setDraft(value=>value||'查看这些附件')}/></div><p className="command-hint">Enter 发送 · Shift + Enter 换行 · / 选择技能</p>{commandError&&draft.startsWith('/')&&<p className="command-hint" role="status">{commandError}</p>}</div>
        </section>
      </main>
      <aside id="agent-info" className="agent-info" aria-label="助手信息" hidden={!infoOpen}>
        <header className="info-heading"><strong>助手信息</strong><Button type="text" aria-label="关闭助手信息" icon={<X size={17} />} onClick={()=>{setInfoOpen(false);infoToggleRef.current?.focus();}} /></header>
        <div className="workspace-tabs" role="tablist" aria-label="助手信息视图" onKeyDown={infoTabKey}><button type="button" id="workspace-tab" role="tab" aria-selected={infoTab==='workspace'} aria-controls="workspace-content" tabIndex={infoTab==='workspace'?0:-1} onClick={()=>setInfoTab('workspace')}>工作区</button><button type="button" id="models-tab" role="tab" aria-selected={infoTab==='models'} aria-controls="models-content" tabIndex={infoTab==='models'?0:-1} onClick={()=>setInfoTab('models')}>模型与能力</button></div>
        <section id="workspace-content" role="tabpanel" aria-labelledby="workspace-tab" hidden={infoTab!=='workspace'}><div className="workspace-session"><span>当前会话</span><strong>{activeSession?.title||'新对话'}</strong></div><AgentWorkbenchPanel sessionId={threadId} base={new URL(API,window.location.href).origin} messages={items} onFork={loadSession} onReference={value=>{if(/^@file:[a-f0-9-]{36}$/.test(value)){setDraft(current=>(current?current.trimEnd()+' ':'')+value+' ');senderRef.current?.focus()}}}/><AgentActionList sessionId={threadId} base={new URL(API,window.location.href).origin} refreshKey={loading}/><p className="workspace-section-label">资源与能力</p>{workspaceResources.map(({icon:Icon,...resource})=><a className="workspace-resource" key={resource.path} href={new URL('#'+resource.path,LOGIN).toString()}><span className="workspace-resource-icon"><Icon size={17}/></span><span><strong>{resource.title}</strong><small>{resource.note}</small></span><ArrowUpRight size={13}/></a>)}<p className="info-note workspace-privacy"><ShieldCheck size={14}/>会话与记忆按账号隔离<br/>需要确认的操作请在确认页面核对</p></section>
        <div id="models-content" role="tabpanel" aria-labelledby="models-tab" hidden={infoTab!=='models'}>
          <AgentModelOverview catalog={catalog} modelCatalog={modelCatalog} catalogLoading={catalogLoading} modelLoading={modelCatalogLoading} catalogError={catalogError} modelError={modelCatalogError} authRequired={catalogAuthRequired || modelAuthRequired} onRefresh={refreshServiceCatalogs} loginHref={LOGIN} traceHref={TRACE+(threadId?'?sessionId='+encodeURIComponent(threadId):'')} actionsHref={ACTIONS} reportsHref={REPORTS}/>
        </div>
      </aside>
    </Layout>
  </ConfigProvider>;

}

createRoot(document.getElementById('root')).render(<AgentErrorBoundary businessHref={BUSINESS} traceHref={TRACE}><App /></AgentErrorBoundary>);
