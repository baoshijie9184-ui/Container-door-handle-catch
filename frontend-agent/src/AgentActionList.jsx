import React,{useEffect,useRef,useState} from 'react';
import {Button} from 'antd';
import StatusBadge from './StatusBadge';
import {ClipboardCheck,LockKeyhole,TriangleAlert} from 'lucide-react';
import {validAgentAction as valid} from '../../frontend/src/utils/agentActions.js';
import {beijingDateTime} from '../../frontend/src/utils/beijingTime.js';
import {DetectionProposalImages} from './DetectionProposalImages';
import {DetectionCreationReview} from './DetectionCreationReview';
import AgentActionAudit from './AgentActionAudit';
import ProposalImageGallery from './ProposalImageGallery';

const labels={PENDING:'待确认',APPROVED:'已批准',EXECUTING:'执行中',NEEDS_REVIEW:'待核对',SUCCEEDED:'已完成',REJECTED:'已拒绝',CANCELLED:'已取消',EXPIRED:'已过期',INVALIDATED:'已失效'};
const reasons={RESOURCE_CHANGED:'任务已变化 请重新生成提议',ROLE_REVOKED:'当前账号已无操作权限',EXECUTION_NEEDS_REVIEW:'上次检测结果待核对 未提交新的检测 不会自动重试',PARAMETERS_SUPERSEDED:'已有新的操作参数 原提议失效',POLICY_CHANGED:'规则已更新 请重新生成',CONFIRMATION_EXPIRED:'确认已过期 未执行操作',ORIGIN_RUN_TERMINATED:'原运行已终止 未执行操作',BUSINESS_PRECONDITION_CHANGED:'业务条件已变化 未执行操作',USER_REJECT:'用户已拒绝',USER_CANCEL:'用户已取消'};
reasons.USER_ABANDONED='本人已终止创建 原文件及不确定传输证据保留';
function CreationDetails({preview,result,base,scopeKey}){
 const p=preview;
 return <><ProposalImageGallery images={p.images} base={base} scopeKey={scopeKey} label="拟检测原图"/>
 <dl><dt>图片数量</dt><dd>{p.images.length} 张</dd><dt>采集日期</dt><dd>{p.capture.captureDate}</dd><dt>采集区域</dt><dd>{p.capture.region}</dd><dt>采集人</dt><dd>{p.capture.collector}</dd><dt>采集设备</dt><dd>{p.capture.deviceName}</dd><dt>批次文件夹</dt><dd>{p.capture.imageFolderName}</dd><dt>检测模型</dt><dd>{p.model.name} · {p.model.version}</dd><dt>阈值</dt><dd>{p.threshold}</dd><dt>提议版本</dt><dd>{p.resourceVersion}</dd>{result&&<><dt>检测任务</dt><dd>{result.taskId}</dd></>}</dl>
 <p>仅检测本卡片列出的会话上传或已关联业务原图 不自动复核、放行或审批报告</p></>;
}
export function AgentActionList({sessionId,base='',refreshKey}) {
 const [actions,setActions]=useState([]),[error,setError]=useState(''),[loading,setLoading]=useState(false);
 const [busy,setBusy]=useState(new Set()),[verified,setVerified]=useState(false);const locked=useRef(new Set()),generation=useRef(0),scope=useRef(null);
 const endpoint=base+'/api/agent/actions';
 async function read(response){
  let value;
  try { value=await response.json(); }
  catch { const failure=new Error('操作状态暂不可核对，请刷新');failure.status=response.status;throw failure; }
  if(!response.ok){const failure=new Error(response.status===503&&value?.message==='人工确认功能尚未启用'?'DISABLED':value?.message||'操作状态暂不可用 请刷新');failure.status=response.status;throw failure;}
  return value;
 }
 async function refresh(){const version=++generation.current;setLoading(true);setError('');setVerified(false);
  try{const value=await read(await fetch(endpoint+'?sessionId='+encodeURIComponent(sessionId),{credentials:'include',cache:'no-store'}));if(version!==generation.current)return;if(!Array.isArray(value)||!value.every(valid))throw new Error('操作记录格式异常 请刷新核对');setActions(value);setVerified(true);}
  catch(cause){if(version===generation.current){if(cause.message==='DISABLED')setActions([]);else {if([401,403].includes(cause.status))setActions([]);setError(cause.message);}}}
  finally{if(version===generation.current)setLoading(false);}
 }
 useEffect(()=>{const nextScope=JSON.stringify([sessionId,base]);if(scope.current!==nextScope){scope.current=nextScope;setActions([]);setError('');setVerified(false);}if(sessionId)refresh();return()=>{generation.current++}},[sessionId,base,refreshKey]);
 async function decide(action,decision){if(locked.current.has(action.actionId)||!verified)return;
  const version=generation.current;locked.current.add(action.actionId);setBusy(new Set(locked.current));setError('');
  try{const cancel=decision==='CANCEL';const value=await read(await fetch(endpoint+'/'+encodeURIComponent(action.actionId)+(cancel?'/cancel':'/confirm'),{method:'POST',credentials:'include',headers:{'Content-Type':'application/json','X-Agent-Action':cancel?'cancel':'confirm','X-Request-ID':action.actionId},body:JSON.stringify(cancel?{version:action.version}:{decision,version:action.version})}));
   if(version!==generation.current)return;if(!valid(value)||value.actionId!==action.actionId)throw new Error('操作结果未核实 请刷新');setActions(current=>current.map(item=>item.actionId===action.actionId?value:item));
  }catch(cause){if(version===generation.current){setVerified(false);setError(cause.message||'确认结果未核实 请刷新后再操作');}}
  finally{locked.current.delete(action.actionId);setBusy(new Set(locked.current));}
 }
 if(!sessionId)return null;
 return <><DetectionCreationReview sessionId={sessionId} base={base} refreshKey={refreshKey} onChanged={refresh}/>{(actions.length>0||error)&&<section className="agent-action-list" aria-label="助手操作确认"><header><strong><ClipboardCheck size={16} aria-hidden="true"/>助手操作确认</strong><Button size="small" aria-label="刷新" loading={loading} onClick={refresh}>刷新</Button></header>
 {error&&<p role="alert" className="action-error">{error}</p>}
 {loading&&<p className="action-read-feedback" role="status">{actions.length ? '正在核对操作状态，当前保留上次卡片；读取完成前不能确认。' : '正在读取操作提议…'}</p>}
 {!loading&&actions.length>0&&!verified&&<p className="action-read-feedback" role="status">当前卡片尚未重新核实，请刷新后再确认。刷新不会重发业务操作。</p>}
 {actions.map(action=>{const retry=action.operation==='RETRY_DETECTION',create=action.operation==='CREATE_DETECTION',p=action.retry;return <article key={action.actionId} data-operation={action.operation} data-status={action.status} aria-busy={busy.has(action.actionId)}>
  <header><strong><LockKeyhole size={16} aria-hidden="true"/>{create?'创建检测任务':retry?'重新检测任务':'分配质检任务'}</strong><StatusBadge domain="confirmation" code={action.status} label={action.status==='SUCCEEDED'?(retry||create?'已提交检测':'已分配'):labels[action.status]} /></header>
  <p className="action-review-meta">业务操作确认 · 提议 V{action.version}{action.status==='PENDING'&&<span> · 有效至 {beijingDateTime(action.expiresAt??null)||'时间未记录'} UTC+8</span>}</p>
  {action.status==='PENDING'&&<p className="action-impact"><TriangleAlert size={16} aria-hidden="true"/><span>{create?'确认将复制本卡片的已授权图片并创建检测任务。':retry?'确认将提交新的检测，并重置当前检测结果与复核处置。':'确认将修改下方任务的质检分配信息。'}请核对本卡片参数，计划批准或普通回答不代替此处确认。</span></p>}
  {retry&&<DetectionProposalImages taskId={p.taskId} count={p.imageCount} proposalVersion={action.version} base={base} refreshKey={generation.current}/>}
  {create?<CreationDetails preview={action.creation} result={action.creationResult} base={base} scopeKey={JSON.stringify([sessionId,action.actionId,action.version])}/>:<dl>{retry?<><dt>检测任务</dt><dd>{p.taskId}</dd><dt>提议时状态</dt><dd className="action-status-pair"><StatusBadge domain="detection" code={p.status}/>{p.flowStatus&&<StatusBadge domain="flow" code={p.flowStatus}/>}</dd><dt>沿用原图</dt><dd>{p.imageCount} 张</dd><dt>检测模型</dt><dd>{p.modelId??'未知'} · 阈值 {p.threshold??'未知'}</dd><dt>任务版本</dt><dd>{p.resourceVersion}</dd><dt>重试影响</dt><dd>{p.impact}</dd>{action.execution&&<><dt>新派发编号</dt><dd>{action.execution.dispatchId}</dd></>}</>:<><dt>检测任务</dt><dd>{action.command.taskId}</dd><dt>质检站点</dt><dd>{action.before.qualityStation||'未分配'} → {action.command.qualityStation}</dd><dt>责任人</dt><dd>{action.before.assignee||'未分配'} → {action.command.assignee}</dd><dt>责任人 ID</dt><dd>{action.before.assigneeUserId??'未知'} → {action.command.assigneeUserId??'未知'}</dd><dt>账号快照</dt><dd>{action.command.assigneeRevision||'历史提议未记录'}</dd>{action.result?.after&&<><dt>分派操作人</dt><dd>{action.result.after.assignedByName||'未知'} · ID {action.result.after.assignedByUserId??'未知'}</dd><dt>分派身份版本</dt><dd>{action.result.after.assignmentRevision??'未知'}</dd></>}<dt>截止时间</dt><dd>{beijingDateTime(action.command.dueAt??null)||'未设置'}</dd></>}</dl>}
  {create&&action.status==='EXECUTING'&&<p>已保存批准 正在准备检测文件 可刷新核对状态 不要重复提交</p>}
  {(retry||create)&&action.status==='SUCCEEDED'&&<p>已受理新的检测派发 不表示检测已完成 请到检测记录查看实际进度</p>}
  {action.reasonCode&&<p>{create&&action.reasonCode==='EXECUTION_NEEDS_REVIEW'?'图片传输或检测创建结果待核对 不会自动重传或重复提交':reasons[action.reasonCode]||'操作未执行 请重新核对'}</p>}
  {action.status==='PENDING'&&<div className="action-buttons"><Button type="primary" danger={retry} loading={busy.has(action.actionId)} disabled={busy.has(action.actionId)||!verified} onClick={()=>decide(action,'APPROVE')}>{create?'确认创建检测':retry?'确认重新检测':'确认分配'}</Button><Button disabled={busy.has(action.actionId)||!verified} onClick={()=>decide(action,'REJECT')}>拒绝</Button><Button disabled={busy.has(action.actionId)||!verified} onClick={()=>decide(action,'CANCEL')}>取消</Button></div>}
  <AgentActionAudit key={JSON.stringify([base,sessionId,action.actionId,action.version])} actionId={action.actionId} revision={action.version} operation={action.operation} scopeKey={sessionId} base={base} disabled={busy.has(action.actionId)}/>
 </article>})}</section>}</>;
}
