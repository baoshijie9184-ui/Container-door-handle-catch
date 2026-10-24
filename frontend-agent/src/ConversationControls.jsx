import React,{forwardRef,useEffect,useImperativeHandle,useRef,useState} from 'react';
import {Button,Modal,Input,Dropdown} from 'antd';
import {Pause,Play,RefreshCw,CornerDownRight,ArrowRight,Trash2,Ellipsis,Pencil,ListX} from 'lucide-react';
import {ConversationControlClient,controlPhaseLabels,inputStatusLabels} from '../../frontend/src/utils/conversationControl.js';
import '../../frontend/src/assets/conversation-control.css';
import StatusBadge from './StatusBadge';
import {useReducedMotion} from './useReducedMotion';
export const ConversationControls=forwardRef(function Controls({sessionId,base,onSnapshot,onRefresh},ref){
 const [state,setState]=useState({enabled:false,run:null,inputs:[]}),[mode,setMode]=useState('NEXT_TURN'),[busy,setBusy]=useState(false),[error,setError]=useState(''),[edit,setEdit]=useState(null);
 const reducedMotion=useReducedMotion();
 const callbacks=useRef({onSnapshot,onRefresh});callbacks.current={onSnapshot,onRefresh};
 const ready=useRef(Promise.resolve());
 const client=useRef(null);if(!client.current)client.current=new ConversationControlClient({base,entryPoint:'AGUI',onState:value=>{setState(value);callbacks.current.onSnapshot(value)},onRefresh:session=>callbacks.current.onRefresh(session)});
 useEffect(()=>{setError('');setEdit(null);setBusy(false);ready.current=client.current.open(sessionId);return()=>client.current.close()},[sessionId]);
 async function mutate(action){const generation=client.current.generation;setBusy(true);setError('');try{return await action()}catch(cause){if(generation===client.current.generation)setError(cause.message);throw cause}finally{if(generation===client.current.generation)setBusy(false)}}
 function requestCancel(){const generation=client.current.generation,runId=client.current.state?.run?.runId;return Modal.confirm({transitionName:reducedMotion?'':'ant-zoom',maskTransitionName:reducedMotion?'':'ant-fade',title:'停止当前任务',content:'取消本轮执行，排队消息保留并在本轮结束后处理。如需停止后续消息，请先逐条撤回。已完成的工具操作不会回滚。',okText:'确认停止',cancelText:'继续执行',onOk:()=>{if(generation!==client.current.generation)return;if(runId!==client.current.state?.run?.runId){setError('当前任务已变化，请重新核对后操作');return}return command('cancel')}})}
 useImperativeHandle(ref,()=>({ready:async()=>{await ready.current;return client.current.enabled},submit:content=>mutate(()=>client.current.submit(content,mode)),cancel:requestCancel}),[mode]);
 async function command(action){try{await mutate(()=>client.current.command(action))}catch{/* Show the result and require a new explicit action. */}}
 const run=state.run,pending=state.inputs.filter(item=>item.status==='QUEUED').reverse();
 const currentEdit=state.inputs.find(item=>item.id===edit?.id),editStale=!currentEdit||currentEdit.status!=='QUEUED'||currentEdit.revision!==edit?.revision;
 if(!state.enabled||(!edit&&!pending.length&&!error&&!state.error&&(!run||run.phase==='IDLE')))return null;
 return <section className="conversation-controls" aria-label="Agent 执行控制">
  <details className="conversation-options"><summary>任务操作</summary>
  <div className="conversation-control-bar"><span role="status"><StatusBadge domain="executionPhase" code={run?.phase} label={run?controlPhaseLabels[run.phase]:'状态待核对'}/></span><div>
   {run?.local&&run.phase==='RUNNING'&&<Button size="small" icon={<Pause size={13}/>} disabled={busy} onClick={()=>command('pause')}>暂停任务</Button>}
   {run?.local&&['PAUSED','PAUSE_REQUESTED'].includes(run.phase)&&<Button size="small" icon={<Play size={13}/>} disabled={busy} onClick={()=>command('resume')}>继续任务</Button>}
   {run?.local&&run.runId&&<Button size="small" danger disabled={busy} onClick={requestCancel}>取消任务</Button>}
   <Button size="small" icon={<RefreshCw size={13}/>} disabled={busy} onClick={()=>client.current.poll()}>刷新</Button>
  </div></div>
  <details className="control-help"><summary>执行说明</summary><p className="control-note">暂停在安全切点生效，当前调用可能继续完成；仅在服务进程存活期间继续。排队输入 15 分钟有效，失败不自动重试。</p></details>
  <div className="conversation-delivery"><label htmlFor="independent-delivery-mode">发送方式</label><select id="independent-delivery-mode" value={mode} onChange={event=>setMode(event.target.value)}><option value="NEXT_TURN">排到下一轮</option><option value="NEXT_STEP">引导当前任务</option></select><span>{mode==='NEXT_STEP'?'下一推理切点交付；本轮已结束时转入下一轮':'当前任务结束后按顺序处理'}</span></div>
  {state.inputs.some(item=>item.status!=='QUEUED')&&<details className="control-help"><summary>最近交付记录</summary>{state.inputs.filter(item=>item.status!=='QUEUED').slice(0,3).map(item=><p key={item.id} className="control-receipt"><span>{item.mode==='NEXT_STEP'?'补充要求':'消息'}</span><StatusBadge domain="queuedInput" code={item.status} label={inputStatusLabels[item.status]}/><small>{item.id.slice(0,8)}</small></p>)}</details>}
  </details>
  {!edit&&(error||state.error)&&<p className="control-error" role="alert">{error||state.error}</p>}
  {state.queueEnabled===false&&<p className="queue-preference">消息排队已关闭，已有消息继续处理<button type="button" onClick={()=>client.current.setQueueEnabled(true)}>开启排队</button></p>}
  {!!pending.length&&<p className="queue-count" role="status">{pending.length} 条消息待处理</p>}
  {!!pending.length&&<ol className="conversation-queue" aria-label="待处理消息">{pending.map((item,index)=><li key={item.id}>
   <CornerDownRight className="queue-entry-icon" size={16} aria-hidden="true"/>
   <p className="queue-content" title={item.content}>{item.content}</p>
   {item.mode==='NEXT_STEP'?<span className="queue-steering-status">等待引导</span>:<button type="button" className="queue-steer" disabled={busy||!run?.runId} title="在当前任务的下一推理切点补充要求" onClick={()=>mutate(()=>client.current.steer(item)).catch(()=>{})}><ArrowRight size={14} aria-hidden="true"/>引导</button>}
   <button type="button" className="queue-icon-button" aria-label={'撤回第 '+(index+1)+' 条待处理消息'} title="撤回消息" disabled={busy} onClick={()=>mutate(()=>client.current.change(item,null)).catch(()=>{})}><Trash2 size={15} aria-hidden="true"/></button>
   <Dropdown trigger={['click']} disabled={busy} menu={{items:[{key:'edit',label:'编辑消息',icon:<Pencil size={14}/>},{key:'close-queue',label:'关闭排队',icon:<ListX size={14}/>,disabled:state.queueEnabled===false}],onClick:({key})=>{if(key==='edit'){setError('');setEdit({...item})}else client.current.setQueueEnabled(false)}}}><button type="button" className="queue-icon-button" aria-label="更多消息操作" title="更多消息操作" disabled={busy}><Ellipsis size={16} aria-hidden="true"/></button></Dropdown>
  </li>)}</ol>}

  <Modal rootClassName="queue-edit-modal" transitionName={reducedMotion?'':'ant-zoom'} maskTransitionName={reducedMotion?'':'ant-fade'} open={!!edit} title="编辑待处理消息" onCancel={()=>{if(!busy)setEdit(null)}} maskClosable={false} keyboard={!busy} closable={!busy} okText="保存修改" cancelText="取消" confirmLoading={busy} cancelButtonProps={{disabled:busy}} okButtonProps={{disabled:editStale||!edit?.content.trim()}} onOk={async()=>{if(busy||editStale||!edit?.content.trim())return;const generation=client.current.generation,snapshot=edit;try{await mutate(()=>client.current.change(snapshot,snapshot.content));if(generation===client.current.generation)setEdit(current=>current?.id===snapshot.id?null:current)}catch{/* Preserve draft. */}}}><p className="control-edit-note">{edit?.mode==='NEXT_STEP'?'此消息将在当前任务的安全切点交付':'此消息排到后续轮次处理'}。保存失败时保留草稿，不会自动重试。</p><Input.TextArea aria-label="待处理消息内容" rows={4} disabled={busy} showCount maxLength={edit?.mode==='NEXT_STEP'?4000:8000} value={edit?.content} onChange={event=>setEdit({...edit,content:event.target.value})}/>{editStale&&!busy&&<p className="control-error" role="status">原消息已变化、交付或尚未读取，请先复制编辑内容，再关闭并核对当前队列。</p>}{(error||state.error)&&<p className="control-error" role="alert">{error||state.error}</p>}</Modal>
 </section>
});
