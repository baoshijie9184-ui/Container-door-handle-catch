import React,{useId} from 'react';
import {Network,FileText,Plus,X,MessageSquare,FileCheck} from 'lucide-react';
import {CHILD_FOLLOWUP_LIMIT,childTaskPresentation,childFollowupReady} from '../../frontend/src/utils/childTaskPresentation';
import '../../frontend/src/assets/agent-child-task.css';
export default function AgentChildTask({item,value='',busy,availableViews=[],onChange,onCommand,onCancel,onView}){
 const view=childTaskPresentation(item),text=typeof value==='string'?value:'',inputId=useId(),ready=childFollowupReady(text);
 return <section className="wb-child-task" aria-label="专业任务结果与追加要求">
  <p className="wb-child-state"><Network size={16} aria-hidden="true"/><span>{view.explanation}</span></p>
  {view.nextView&&availableViews.includes(view.nextView)&&<button type="button" disabled={busy} onClick={()=>onView?.(view.nextView)}>{view.nextView==='QUESTION'?<MessageSquare size={14} aria-hidden="true"/>:<FileCheck size={14} aria-hidden="true"/>}{view.nextLabel}</button>}
  <section className="wb-child-result" aria-label="最近保存的专业结果"><h4><FileText size={16} aria-hidden="true"/>最近保存的结果</h4>{view.output?<><p className="wb-child-result-note">{view.resultNote}</p><p className="wb-child-excerpt">{view.excerpt}</p><details><summary>展开已保存结果</summary><pre tabIndex={0} aria-label="已保存的专业结果，纯文本展示">{view.output}</pre></details></>:<p className="wb-note">本次读取没有返回可显示的专业结果，请结合执行轨迹核对，不补造分析结论。</p>}</section>
  {view.canAppend&&<form className="wb-child-followup" onSubmit={event=>{event.preventDefault();if(!busy&&view.canAppend&&ready)onCommand?.(text)}}><label htmlFor={inputId}>补充专业要求<textarea id={inputId} value={text} rows={3} maxLength={CHILD_FOLLOWUP_LIMIT} disabled={busy} aria-describedby={inputId+'-hint'} placeholder="填写本专业任务需要继续分析的范围或重点" onChange={event=>onChange?.(event.target.value)}/></label><p id={inputId+'-hint'} className="wb-note">{text.length} / {CHILD_FOLLOWUP_LIMIT} 字符。沿用原专业角色与工具权限；草稿仍在本页保留，提交结果请核对记录，不自动重发。</p><button type="submit" className="wb-button-primary" disabled={busy||!ready}><Plus size={14} aria-hidden="true"/>追加专业要求</button></form>}
  {view.canCancel&&<div className="wb-child-cancel"><p>取消所选专业任务不会回滚已完成的业务操作；主任务和其他专业任务的状态分别核对。</p><button type="button" className="wb-button-danger" disabled={busy} onClick={onCancel}><X size={14} aria-hidden="true"/>取消此专业任务</button></div>}
 </section>;
}
