import React,{useId,useMemo,useRef,useState} from 'react';
import {Copy,ArrowLeft,Search} from 'lucide-react';
import {forkCandidates,filterForkCandidates,forkLineage} from '../../frontend/src/utils/forkPresentation';
import '../../frontend/src/assets/agent-fork-panel.css';
export default function AgentForkPanel({sessionId,messages=[],lineage,known,loading,readError,busy,onFork,onSource}){
 const [query,setQuery]=useState(''),[selected,setSelected]=useState(null),queryId=useId();
 const root=useRef(null);
 function clearSelection(id){setSelected(null);root.current?.querySelector(`[data-fork-select="${id}"]`)?.focus({preventScroll:true})}
 const candidates=useMemo(()=>forkCandidates(messages),[messages]),visible=filterForkCandidates(candidates,query),source=forkLineage(lineage);
 const selectedReply=selected && selected.sessionId===sessionId?candidates.find(reply=>reply.id===selected.id && reply.signature===selected.signature):null;
 const ready=!busy && known && !loading && !readError;
 return <section ref={root} className="wb-fork-panel" aria-label="会话分支与回复切点">
  <p className="wb-fork-guide"><Copy size={17} aria-hidden="true"/><span>从已保存且已结束的回复创建独立分支。切点前的内容按原规则继承，原会话保留；有效审批、排队消息和正在执行的任务不继承，最终可用性由服务端核对。</span></p>
  {source?<section className="wb-fork-source" aria-label="本会话的来源"><strong>分支来源</strong><code>{source.id}</code><p>{source.cutoff?'来源回复 #'+source.cutoff:'来源切点未记录'}</p><button type="button" disabled={busy} onClick={()=>onSource?.(source.id)}><ArrowLeft size={14} aria-hidden="true"/>返回来源会话</button>{source.legacy&&<p className="wb-note">旧轮次缺少精确附件快照，同秒附件未自动继承，可重新上传或关联。</p>}</section>:known&&<p className="wb-note">本次没有返回分支来源记录，不推断更早会话的关系。</p>}
  <label className="wb-fork-query" htmlFor={queryId}>查找已保存回复<input id={queryId} type="search" value={query} placeholder="回复内容或消息编号" onChange={event=>setQuery(event.target.value)}/></label>
  <p className="wb-fork-count" role="status">显示 {visible.length} / {candidates.length} 个已加载切点，最多列出最近 20 个。这里只筛选当前对话资料。</p>
  {(!known||loading||readError)&&<p className="wb-note" role={readError?'alert':'status'}>{readError?'工作台未能核对当前状态，请刷新后再创建分支。':loading?'正在读取工作台，暂不可创建分支。':'工作台尚未完成读取。'}</p>}
  {!visible.length&&<div className="wb-fork-empty">{query.trim()?<Search size={23} aria-hidden="true"/>:<Copy size={23} aria-hidden="true"/>}<strong>{query.trim()?'没有匹配的已加载回复':'暂无可列出的已保存回复'}</strong><p>{query.trim()?'清空查找条件后可重新查看。':'请等待回复结束并保存，再重新读取会话。临时编号、占位消息和错误提示不会作为切点。'}</p>{query.trim()&&<button type="button" onClick={()=>setQuery('')}>清空查找条件</button>}</div>}
  {visible.map(reply=><section key={reply.id} className={'wb-fork-reply'+(selected?.id===reply.id?' is-selected':'')}>
   <header><strong>回复 #{reply.id}</strong><span>{reply.time?reply.time+' UTC+8':'回复时间未记录'}</span></header><p>{reply.excerpt||'此回复没有可显示的纯文本摘录，请先在对话中核对。'}</p>
   {reply.preview&&<details><summary>展开回复片段</summary><pre tabIndex={0} aria-label="回复纯文本片段">{reply.preview}</pre>{reply.truncated&&<p className="wb-note">较长回复只展示部分内容，完整内容请在原对话中核对。</p>}</details>}
   <button type="button" data-fork-select={reply.id} disabled={!ready} aria-pressed={selected?.id===reply.id} aria-expanded={selected?.id===reply.id} aria-controls={queryId+'-confirm-'+reply.id} onClick={()=>setSelected({sessionId,id:reply.id,signature:reply.signature})}><Copy size={14} aria-hidden="true"/>{selected?.id===reply.id?'已选此回复':'选择此回复创建分支'}</button>
   {selected?.id===reply.id && selected.sessionId===sessionId&&<section id={queryId+'-confirm-'+reply.id} className="wb-fork-confirm" aria-label="核对分支切点"><strong>所选切点：回复 #{selected.id}</strong>{selectedReply?<p>创建后打开新会话。原会话保持完整，新分支的后续修改相互独立。</p>:<p role="alert">此回复资料已变化，请重新选择后再创建。</p>}<div><button type="button" className="wb-button-primary" disabled={!ready||!selectedReply} onClick={()=>{if(ready&&selectedReply)onFork?.(selectedReply.id)}}>{busy?'正在等待工作台操作':'创建并打开分支'}</button><button type="button" disabled={busy} onClick={()=>clearSelection(reply.id)}>取消选择</button></div></section>}
  </section>)}
  {selected && selected.sessionId===sessionId && !visible.some(reply=>reply.id===selected.id)&&<p className="wb-note" role="status">所选回复不在当前可见范围，请重新选择可见回复后创建分支。</p>}
 </section>;
}
