import React from 'react';
import { CheckCircle2, FileCheck, MessageSquare, Pencil } from 'lucide-react';
import { WORKBENCH_RESPONSE_LIMIT, workbenchQuestionType, workbenchQuestionOptions, workbenchAnswerReady } from '../../frontend/src/utils/workbenchPresentation';

export default function WorkbenchInteraction({ item, value = '', busy, onChange, onCommand }) {
  const text = typeof value === 'string' ? value : '';
  const type = workbenchQuestionType(item.data);
  const options = type === 'UNKNOWN' ? [] : workbenchQuestionOptions(item.data);
  const ready = workbenchAnswerReady(item.data, value);
  const command = (action, input) => { if (!busy) onCommand(action, input); };
  const selected = option => type === 'SINGLE' ? value === option : Array.isArray(value) && value.includes(option);
  function choose(option, checked) {
    if (busy) return;
    if (type === 'SINGLE') onChange(option);
    else { const current = Array.isArray(value) ? value : []; onChange(checked ? [...current.filter(value => value !== option), option] : current.filter(value => value !== option)); }
  }
  return <div className="wb-interaction" data-interaction={item.kind} aria-busy={busy}>
    {item.kind === 'PLAN' ? <>
      <details className="wb-plan-feedback">
        <summary><Pencil size={14} aria-hidden="true"/>填写修订意见</summary>
        <label className="wb-input-label">需要调整的范围或步骤<textarea value={text} disabled={busy} maxLength={WORKBENCH_RESPONSE_LIMIT} rows={3} placeholder="填写后可要求修订，计划修改后需要重新审阅" onChange={event => onChange(event.target.value)}/></label>
        <p className="wb-input-hint">{text.length} / {WORKBENCH_RESPONSE_LIMIT} 字符</p>
      </details>
      <p className="wb-decision-scope"><FileCheck size={15} aria-hidden="true"/>批准当前 V{item.revision ?? '未知'} 执行范围，检测、分派等业务确认仍独立进行</p>
      {text.trim() && <p className="wb-input-hint">修订意见尚未提交；批准计划仍按当前正文执行。</p>}
      <div className="wb-actions"><button type="button" className="wb-button-primary" disabled={busy} onClick={() => command('approve-plan')}><CheckCircle2 size={14} aria-hidden="true"/>批准计划</button><button type="button" disabled={busy || !text.trim() || text.length > WORKBENCH_RESPONSE_LIMIT} onClick={() => command('revise-plan', { feedback: text })}>要求修订</button><button type="button" className="wb-button-quiet" disabled={busy} onClick={() => command('cancel')}>取消计划</button></div>
    </> : item.kind === 'QUESTION' && <form onSubmit={event => { event.preventDefault(); if (ready) command('answer', { answer: value }); }}>
      <fieldset className="wb-question-fields" disabled={busy}>
        <legend>{type === 'TEXT' ? '填写回答' : type === 'SINGLE' ? '选择一项' : type === 'MULTIPLE' ? '选择一项或多项' : '问题格式待核对'}</legend>
        {type === 'TEXT' ? <><textarea value={text} maxLength={WORKBENCH_RESPONSE_LIMIT} rows={4} aria-label="问题回答" placeholder="补充完成任务所需的信息" onChange={event => onChange(event.target.value)}/><p className="wb-input-hint">{text.length} / {WORKBENCH_RESPONSE_LIMIT} 字符</p></> : options.length > 0 ? <div className="wb-answer-options">{options.map(option => <label key={option} className={'wb-answer-option' + (selected(option) ? ' is-selected' : '')}><input type={type === 'SINGLE' ? 'radio' : 'checkbox'} name={'workbench-question-' + item.id} value={option} checked={selected(option)} onChange={event => choose(option, event.target.checked)}/><span>{option}</span></label>)}</div> : <p className="wb-note">问题类型或选项不完整，请刷新核对；不会猜测回答。</p>}
      </fieldset>
      <p className="wb-input-hint">{type === 'MULTIPLE' ? `已选择 ${Array.isArray(value) ? value.length : 0} 项 · ` : ''}提交后继续原任务，回答不授予业务操作权限</p>
      <div className="wb-actions"><button type="submit" className="wb-button-primary" disabled={busy || !ready}><MessageSquare size={14} aria-hidden="true"/>提交回答</button><button type="button" className="wb-button-quiet" disabled={busy} onClick={() => command('cancel')}>取消问题</button></div>
    </form>}
  </div>;
}
