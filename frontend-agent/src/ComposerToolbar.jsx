import React,{forwardRef,useEffect,useId,useImperativeHandle,useRef,useState} from 'react';
import {Plus,FileText,Image as ImageIcon,ChartNoAxesCombined,Lock,X,Square,ArrowUp,WifiOff,TriangleAlert} from 'lucide-react';
import {APPROVAL_MODES,approvalModeDetails,ComposerResources,modelLabel,selectedModelMissing} from '../../frontend/src/utils/composerResources.js';
import {composerAttachment,composerDefaultModel,composerUploadHint,composerModelTitle} from '../../frontend/src/utils/composerPresentation';
import {canGuide} from '../../frontend/src/utils/conversationControl.js';
import '../../frontend/src/assets/composer-presentation.css';
export const ComposerToolbar=forwardRef(function Toolbar({sessionId,base,locked,onUpload,run,streaming=false,draft='',onDraft,onSend,onStop,disabled},ref){
 const [state,setState]=useState({ready:false,files:[],models:[],modelId:'',busy:false,error:''});const input=useRef(null),client=useRef(null);
 const [browserOffline,setBrowserOffline]=useState(()=>navigator.onLine===false);
 useEffect(()=>{const update=()=>setBrowserOffline(navigator.onLine===false);window.addEventListener('online',update);window.addEventListener('offline',update);return()=>{window.removeEventListener('online',update);window.removeEventListener('offline',update)}},[]);
 if(!client.current)client.current=new ComposerResources({base,onState:setState,onDraft:value=>onDraft?.(value)});
 useEffect(()=>{client.current.open(sessionId);return()=>client.current.close()},[sessionId]);
 useEffect(()=>{client.current.draft(draft)},[draft]);
 useImperativeHandle(ref,()=>({
  content:text=>client.current.content(text),
  clear:()=>client.current.clear(),
  busy:()=>client.current.state.busy||client.current.state.approvalMode.unverified
 }));
 const approvalMode=state.approvalMode;
 const approvalModeHintId=useId();
 const showApprovalMode=sessionId&&approvalMode&&!approvalMode.unavailable;
 const approvalModeHint=approvalMode?.error||approvalMode?.notice||
   (approvalMode?.ready?approvalModeDetails(approvalMode.mode).description:'正在读取当前会话的审批模式。');
 const blocksSend=state.busy||approvalMode?.unverified;
 async function upload(event){const files=Array.from(event.target.files||[]);event.target.value='';try{await client.current.upload(files);onUpload?.()}catch(error){client.current.publish({error:error.message})}}
 return <div className="composer-resources">
  {!!state.files.length&&<div className="composer-attachments" role="list" aria-label="本条消息的附件引用">{state.files.map(file=>{const meta=composerAttachment(file),Icon=meta.icon==='Picture'?ImageIcon:meta.icon==='DataAnalysis'?ChartNoAxesCombined:FileText;return <div className="composer-attachment" role="listitem" key={file.id}><span className="composer-file-icon"><Icon size={18} aria-hidden="true"/></span><span className="composer-file-copy"><strong title={file.name}>{file.name}</strong><small>{meta.type} · {meta.size}</small></span><button type="button" disabled={state.busy||disabled} aria-label={'取消本条消息的附件引用 '+file.name} title="仅取消本次引用，不删除会话文件" onClick={()=>client.current.remove(file.id)}><X size={13} aria-hidden="true"/></button></div>})}</div>}
  {!!state.files.length&&<p className="composer-a11y-only">发送时引用这些会话文件，取消引用不会删除文件</p>}
  {canGuide(run)&&<div className="composer-guidance"><button type="button" disabled={disabled||blocksSend||(!draft.trim()&&!state.files.length)} title="把补充要求发给当前 Agent" onClick={()=>onSend(draft,run.runId)}>引导当前任务</button></div>}
  <div className="composer-resource-toolbar">
   <div className="composer-tools">
    <input type="file" hidden multiple ref={input} accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.md,.csv,.json,.html,.svg" onChange={upload}/>
    <button type="button" aria-label="添加附件" title={composerUploadHint(state,disabled)} disabled={!state.filesEnabled||state.busy||disabled} onClick={()=>input.current.click()}><Plus size={19} aria-hidden="true"/></button>
   </div>
   <div className="composer-preferences" role="group" aria-label="模型与审批">
    <select className="composer-model" aria-label="使用模型" title={composerModelTitle(state,locked,disabled)} value={state.modelId} disabled={!state.ready||state.busy||locked||disabled} onChange={event=>client.current.select(event.target.value).catch(()=>{})}><option value="">{composerDefaultModel(state)}</option>{selectedModelMissing(state)&&<option value={state.modelId} disabled>{state.modelId}（已不可用）</option>}{state.models.map(model=><option key={model.id} value={model.id}>{modelLabel(model)}</option>)}</select>
    {showApprovalMode&&<div className="composer-approval-mode">
      <Lock size={15} aria-hidden="true" />
      <select aria-label="审批模式" aria-describedby={approvalModeHintId} title={approvalModeHint}
        value={approvalMode.ready?approvalMode.mode:''}
        disabled={!approvalMode.ready||approvalMode.loading||state.busy||locked||disabled}
        onChange={event=>client.current.selectApprovalMode(event.target.value).catch(()=>{})}>
        {!approvalMode.ready&&<option value="">{approvalMode.loading?'读取审批模式…':'审批模式未核对'}</option>}
        {APPROVAL_MODES.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
     </div>}
   </div>
   {state.busy&&<span className="composer-upload-status" role="status">处理中</span>}
   {streaming||run?.local&&run.runId&&!draft.trim()&&!state.files.length?<button type="button" className="gpt-stop" aria-label="停止任务" title="停止当前任务" onClick={onStop}><Square size={14} fill="currentColor" aria-hidden="true"/></button>:<button type="button" className="gpt-send" aria-label="发送消息" title="发送消息" disabled={disabled||blocksSend||(!draft.trim()&&!state.files.length)} onClick={()=>onSend(draft)}><ArrowUp size={18} aria-hidden="true"/></button>}
  </div>
  {state.error&&<p className="control-error" role="alert">{state.error}</p>}
  {(selectedModelMissing(state)||state.modelNotice||state.modelError)&&<div className="model-selection-feedback"><span role="status">{selectedModelMissing(state)?'原选模型已不在可用目录，请选择其他模型':state.modelNotice||''}</span>{state.modelError&&<button type="button" disabled={state.busy||disabled} onClick={()=>client.current.refreshModels()}>重新读取</button>}</div>}
  {showApprovalMode&&<div className={'model-selection-feedback composer-approval-feedback'+(!approvalMode.error&&!approvalMode.notice?' composer-a11y-only':'')}>
    <span id={approvalModeHintId} role="status">{approvalModeHint}</span>
    {approvalMode.error&&<button type="button" disabled={state.busy||approvalMode.loading} onClick={()=>client.current.refreshApprovalMode()}>重新读取审批模式</button>}
  </div>}
  {state.draftWarning&&<p className="command-hint" role="status">{state.draftWarning}</p>}
  {state.storageWarning&&<p className="composer-state-note" data-tone="warning" role="status"><TriangleAlert size={14} aria-hidden="true"/>{state.storageWarning}</p>}
  {browserOffline&&<p className="composer-state-note" data-tone="warning" role="status"><WifiOff size={14} aria-hidden="true"/>浏览器报告网络离线，当前输入保留；恢复连接后请手动发送，不会自动重发。</p>}
  {state.filesLoaded&&!state.filesEnabled&&<p className="composer-a11y-only">当前服务未启用会话文件上传</p>}
 </div>
});
