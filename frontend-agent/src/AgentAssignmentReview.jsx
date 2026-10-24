import React from 'react';
import { UserRound, FileText, ChevronDown } from 'lucide-react';
import { assignmentReviewRows } from '../../frontend/src/utils/assignmentReviewPresentation.js';
import '../../frontend/src/assets/assignment-review.css';

const sides = [{key:'before',label:'提议前登记'},{key:'proposed',label:'拟分派设置'}];
export default function AgentAssignmentReview({action}) {
 const rows=assignmentReviewRows(action.before,action.command),after=action.result?.after;
 return <section className="assignment-review" aria-label="质检分派参数对照">
  <h4><UserRound size={16} aria-hidden="true"/>质检分派参数</h4>
  <p className="assignment-review-note">对照本提议保存的原登记与拟修改值，未重新读取任务当前状态。账号权限和任务版本仍在确认时重新核对。</p>
  <dl className="assignment-review-facts"><dt>检测任务</dt><dd>{action.command.taskId}</dd></dl>
  <div className="assignment-review-columns" aria-hidden="true"><span>提议前登记</span><span>拟分派设置</span></div>
  {rows.map(row=><div className="assignment-review-row" key={row.key}><h5>{row.label}</h5><div className="assignment-review-pair">{sides.map(side=><div className="assignment-review-value" data-side={side.key} key={side.key}><span className="assignment-review-side">{side.label}</span><p className={row[side.key].folded?'assignment-review-excerpt':undefined}>{row[side.key].preview}</p>{row[side.key].folded&&<details className="assignment-review-full"><summary>{side.label}完整内容</summary><pre tabIndex={0} aria-label={row.label+' · '+side.label+'完整内容'}>{row[side.key].text}</pre></details>}</div>)}</div></div>)}
  <details className="assignment-review-registration"><summary><FileText size={14} aria-hidden="true"/>账号快照与分派回执登记<ChevronDown className="assignment-review-chevron" size={13} aria-hidden="true"/></summary><dl className="assignment-review-facts"><dt>拟分派账号快照</dt><dd>{action.command.assigneeRevision||'历史提议未记录'}</dd>{after&&<><dt>分派操作人</dt><dd>{after.assignedByName||'未记录'}</dd><dt>操作人 ID</dt><dd>{after.assignedByUserId??'未记录'}</dd><dt>分派身份版本</dt><dd>{after.assignmentRevision??'未记录'}</dd></>}</dl><p className="assignment-review-note">这里仅展示已返回的登记资料；当前操作结果以上方状态及审计为准。</p></details>
 </section>;
}
