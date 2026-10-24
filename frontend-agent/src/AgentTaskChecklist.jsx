import React,{useId} from 'react';
import {ListChecks,ArrowUpRight} from 'lucide-react';
import StatusBadge from './StatusBadge';
import {taskChecklistPresentation} from '../../frontend/src/utils/taskChecklistPresentation';
import '../../frontend/src/assets/agent-task-checklist.css';

export default function AgentTaskChecklist({tasks,traceBase=''}){
 const headingId=useId(),view=taskChecklistPresentation(tasks,traceBase);
 if(!view.total)return null;
 return <section className="wb-checklist" aria-labelledby={headingId}>
  <header><h4 id={headingId}><ListChecks size={16} aria-hidden="true"/>任务步骤</h4><span>本次已读 {view.total.toLocaleString('zh-CN')} 项</span></header>
  <ul className="wb-checklist-counts" aria-label="本次清单各阶段数量">{view.counts.map(group=><li key={group.key} data-phase={group.key}>{group.label} <strong>{group.count.toLocaleString('zh-CN')}</strong></li>)}</ul>
  <p className="wb-checklist-note">步骤状态以本次已读清单为准，不代替业务回执或人工审批。{view.withEvidence?'已记录证据编号 '+view.withEvidence.toLocaleString('zh-CN')+' 项，可逐项展开核对。':'本次清单尚未提供执行证据编号。'}</p>
  <div className={'wb-checklist-scroll'+(view.total>6?' is-long':'')} role={view.total>6?'region':undefined} tabIndex={view.total>6?0:undefined} aria-label={view.total>6?'任务步骤，长清单可在此区域滚动阅读':undefined}>
   <ol className="wb-checklist-rows">{view.rows.map(step=><li key={step.key}>
    <span className="wb-checklist-ordinal" aria-hidden="true">{step.ordinal}</span>
    <div className="wb-checklist-step"><div className="wb-checklist-title"><strong>{step.title}</strong><StatusBadge domain="task" code={step.code} label={step.group==='unknown'?'步骤状态待核对':undefined}/></div>
     {step.group==='unknown'&&<p className="wb-checklist-note">原状态：{step.rawCode||'未记录'}</p>}
     {step.evidence&&<details className="wb-checklist-evidence"><summary>执行证据编号</summary><p>{step.evidence}</p>{step.href?<a href={step.href} target="_blank" rel="noopener noreferrer">查看证据所属执行<ArrowUpRight size={13} aria-hidden="true"/></a>:<p className="wb-checklist-note">未提供可打开的执行编号，可从本任务执行轨迹继续核对。</p>}</details>}
    </div>
   </li>)}</ol>
  </div>
 </section>;
}
