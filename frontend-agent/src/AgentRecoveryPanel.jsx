import React from 'react';
import {RefreshCw,Cpu,X} from 'lucide-react';
import {recoveryPresentation} from '../../frontend/src/utils/recoveryPresentation';
import {modelLabel} from '../../frontend/src/utils/composerResources';
import '../../frontend/src/assets/agent-recovery.css';

export default function AgentRecoveryPanel({item,state,choice='KEEP',busy,onChoice,onRefresh,onResume,onEnd}){
 const view=recoveryPresentation(item,state,choice);
 return <section className="wb-recovery-panel" aria-label="核对中断任务恢复">
  <h4><RefreshCw size={16} aria-hidden="true"/>核对恢复条件</h4>
  <p className="wb-recovery-note">恢复时重新核对账号、工具和业务条件。已完成工具结果保留，未知写结果先核对，不自动重做。</p>
  <dl className="wb-recovery-original"><div><dt>任务原模型</dt><dd>{view.originalModel}</dd></div><div><dt>任务配置版本</dt><dd>{view.originalVersion}</dd></div></dl>
  {state.capabilities?.modelConfig && view.supported && (view.main?<>
   <label className="wb-recovery-label">恢复时使用<select value={choice} disabled={busy} onChange={event=>onChoice(event.target.value)}>
    <option value="KEEP">保留任务原配置</option><option value="CURRENT_DEFAULT" disabled={!view.defaultKnown}>当前默认 · {state.recoveryDefault||'尚未核对'} · {view.currentVersion}</option>
    {view.absentChoice&&<option value={choice} disabled>所选模型尚未核对</option>}
    {view.models.map(model=><option key={model.id} value={model.id}>{modelLabel(model)} · {view.currentVersion}</option>)}
   </select></label>
   <button type="button" className="wb-recovery-refresh" disabled={busy||state.recoveryModelsLoading} onClick={onRefresh}><RefreshCw size={14} aria-hidden="true"/>{state.recoveryModelsLoading?'正在核对目录':'核对恢复模型'}</button>
   {state.recoveryModelError&&<p className="wb-error" role="alert">{state.recoveryModelError}</p>}
   <p className="wb-recovery-note">更换后，未结束的专业任务同步使用新版本；仍在执行的子任务需要先停止。</p>
  </>:<p className="wb-recovery-note">此专业任务沿用绑定配置。需要更换模型时，请先在主任务恢复区选择当前配置。</p>)}
  <p className="wb-recovery-choice"><Cpu size={15} aria-hidden="true"/><span>本次选择：{view.selected}</span></p>
  {view.reason&&<p className="wb-recovery-blocked" role="status">{view.reason}</p>}
  <button type="button" className="wb-button-primary wb-recovery-restore" disabled={busy||!view.canResume} onClick={onResume}><RefreshCw size={14} aria-hidden="true"/>核对并从检查点恢复</button>
  {view.supported&&<div className="wb-recovery-end"><p>{view.endNote}</p><button type="button" className="wb-button-danger" disabled={busy} onClick={onEnd}><X size={14} aria-hidden="true"/>结束此任务</button></div>}
 </section>;
}
