import React,{useEffect,useRef,useState} from 'react';
import {Check,CheckCircle2,ChevronRight,Copy,LoaderCircle,MinusCircle,XCircle} from 'lucide-react';
import {ToolExecutionReader,toolRows,toolSummary,toolTitle,toolStatus,toolTime} from '../../frontend/src/utils/toolExecution';
import '../../frontend/src/assets/tool-execution.css';

function ToolRow({tool,active}) {
  if(!active&&['calling','awaiting-result'].includes(tool.status))tool={...tool,status:'unconfirmed'};
  const [copyState,setCopyState]=useState('');
  const running=['calling','awaiting-result'].includes(tool.status),Icon=running?LoaderCircle:tool.status==='returned'?CheckCircle2:tool.status==='failed'?XCircle:MinusCircle;
  async function copy(){try{await navigator.clipboard.writeText([toolTitle(tool.name),tool.name,toolStatus(tool.status),'调用编号 '+tool.id,tool.agent?'执行助手 '+tool.agent:'',toolTime(tool.durationMs)].filter(Boolean).join('\n'));setCopyState('已复制调用记录');}catch{setCopyState('复制未完成，请手动选择调用记录');}}
  return <details className="tool-call"><summary><span className={`tool-call-state ${running?'is-spinning':''}`} data-status={tool.status}><Icon size={15} aria-hidden="true"/></span><span className="tool-call-label">{toolTitle(tool.name)}</span><span className="tool-call-status">{toolStatus(tool.status)}</span><span className="tool-call-description" title={tool.name}>{tool.name}</span>{toolTime(tool.durationMs)&&<span className="tool-call-duration">{toolTime(tool.durationMs)}</span>}</summary><div className="tool-call-detail"><header><span>工具调用记录</span><button type="button" className="tool-call-copy" aria-label="复制工具调用记录" title="复制调用记录" onClick={copy}>{copyState.startsWith('已复制')?<Check size={13}/>:<Copy size={13}/>}</button></header><dl><dt>工具</dt><dd>{tool.name}</dd><dt>调用编号</dt><dd>{tool.id}</dd><dt>状态</dt><dd>{toolStatus(tool.status)}</dd>{tool.agent&&<><dt>执行助手</dt><dd>{tool.agent}</dd></>}{toolTime(tool.durationMs)&&<><dt>记录耗时</dt><dd>{toolTime(tool.durationMs)}</dd></>}</dl><p>{tool.result|| (tool.status==='failed'?'本次调用返回失败，详细原因请核对执行追溯。':tool.status==='returned'?'已收到工具返回，业务结论以回复和业务记录为准。':'仅展示服务端已经记录的执行状态。')}</p>{copyState&&<p role="status">{copyState}</p>}</div></details>;
}
export function ExecutionTimeline({state,sessionId,runId,controlRun}) {
  const [saved,setSaved]=useState({events:[],known:false,complete:true}),[open,setOpen]=useState(false);
  const reader=useRef(null),source=runId||controlRun?.runId||'',phase=state?.phase||controlRun?.phase||saved.phase||'finished';
  const active=['connecting','running','RUNNING','REMOTE_RUNNING','WAITING_CHILD','PAUSE_REQUESTED'].includes(phase);
  useEffect(()=>{const client=new ToolExecutionReader({onChange:setSaved});reader.current=client;setOpen(false);setSaved(client.open(sessionId,source,active));return()=>client.close();},[sessionId,source]);
  useEffect(()=>{if(reader.current){reader.current.active=active;if(active)reader.current.read();}},[active]);
  const rows=saved.denied?[]:toolRows(saved.events,state?.tools),known=!!state||saved.known;
  if(!rows.length&&!source&&!active)return null;
  const summary=toolSummary(rows,phase,{known,complete:state?.phase==='finished'||!source||saved.complete,truncated:saved.truncated||Object.keys(state?.tools||{}).length>=80});
  return <details className="execution-timeline tool-execution" open={open} onToggle={event=>{const value=event.currentTarget.open;setOpen(value);if(value&&source&&!saved.known)reader.current?.read();}}><summary className="tool-execution-heading"><span className="tool-execution-toggle"><ChevronRight size={13} aria-hidden="true"/></span><strong>{summary}</strong>{active&&<LoaderCircle size={13} className="is-spinning" aria-label="执行中"/>}</summary><div className="tool-execution-body">{rows.map(tool=><ToolRow key={tool.id} tool={tool} active={active}/>)}{!rows.length&&<p className="tool-execution-notice">{saved.error?'执行记录尚未读取':active?'等待服务端工具回执':'本轮尚未读到工具调用记录'}</p>}{saved.error&&<p className="tool-execution-notice" role="status">{saved.error}{!saved.denied&&<button type="button" className="tool-execution-reload" onClick={()=>reader.current?.read()}>重新读取</button>}</p>}{saved.truncated&&<p className="tool-execution-notice">当前仅展示已读取的近期记录</p>}</div></details>;
}
