import React,{forwardRef,useEffect,useImperativeHandle,useRef,useState} from 'react';
import {Plus,FileText,Image as ImageIcon,ChartNoAxesCombined,X,ShieldCheck,MessageSquareText,Square,ArrowUp,WifiOff,TriangleAlert} from 'lucide-react';
import {ComposerResources,modelLabel,selectedModelMissing} from '../../frontend/src/utils/composerResources.js';
import {composerAttachment,composerDefaultModel,composerUploadHint} from '../../frontend/src/utils/composerPresentation';
import '../../frontend/src/assets/composer-presentation.css';
export const ComposerToolbar=forwardRef(function Toolbar({sessionId,base,locked,onUpload,run,draft='',onDraft,onSend,onStop,disabled},ref){
 const [state,setState]=useState({ready:false,files:[],models:[],modelId:'',busy:false,error:''});const input=useRef(null),client=useRef(null);
 const [browserOffline,setBrowserOffline]=useState(()=>navigator.onLine===false);
 useEffect(()=>{const update=()=>setBrowserOffline(navigator.onLine===false);window.addEventListener('online',update);window.addEventListener('offline',update);return()=>{window.removeEventListener('online',update);window.removeEventListener('offline',update)}},[]);
 if(!client.current)client.current=new ComposerResources({base,onState:setState,onDraft:value=>onDraft?.(value)});
 useEffect(()=>{client.current.open(sessionId);return()=>client.current.close()},[sessionId]);
 useEffect(()=>{client.current.draft(draft)},[draft]);
 useImperativeHandle(ref,()=>({content:text=>client.current.content(text),clear:()=>client.current.clear(),busy:()=>client.current.state.busy}));
 async function upload(event){const files=Array.from(event.target.files||[]);event.target.value='';try{await client.current.upload(files);onUpload?.()}catch(error){client.current.publish({error:error.message})}}
 return <div className="composer-resources">
  {!!state.files.length&&<div className="composer-attachments" role="list" aria-label="本条消息的附件引用">{state.files.map(file=>{const meta=composerAttachment(file),Icon=meta.icon==='Picture'?ImageIcon:meta.icon==='DataAnalysis'?ChartNoAxesCombined:FileText;return <div className="composer-attachment" role="listitem" key={file.id}><span className="composer-file-icon"><Icon size={18} aria-hidden="true"/></span><span className="composer-file-copy"><strong title={file.name}>{file.name}</strong><small>{meta.type} · {meta.size}</small></span><button type="button" disabled={state.busy||disabled} aria-label={'取消本条消息的附件引用 '+file.name} title="仅取消本次引用，不删除会话文件" onClick={()=>client.current.remove(file.id)}><X size={13} aria-hidden="true"/></button></div>})}</div>}
  {!!state.files.length&&<p className="composer-attachment-note">发送时引用这些会话文件，取消引用不会删除文件</p>}
  <div className="composer-resource-toolbar">
   <input type="file" hidden multiple ref={input} accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.md,.csv,.json,.html,.svg" onChange={upload}/>
   <button type="button" aria-label="添加附件" title={composerUploadHint(state,disabled)} disabled={!state.ready||!state.filesEnabled||state.busy||disabled} onClick={()=>input.current.click()}><Plus size={19} aria-hidden="true"/></button>
   <span className="composer-permission" title="工具按当前账号权限执行，敏感操作仍需人工确认"><ShieldCheck size={15} aria-hidden="true"/><span>按账号权限</span></span>
   <select aria-label="使用模型" title={locked?'当前任务使用的模型已固定，结束后可切换':'仅对当前会话的新任务生效'} value={state.modelId} disabled={!state.ready||state.busy||locked||disabled} onChange={event=>client.current.select(event.target.value).catch(()=>{})}><option value="">{composerDefaultModel(state)}</option>{selectedModelMissing(state)&&<option value={state.modelId} disabled>原选模型已不可用，请重新选择</option>}{state.models.map(model=><option key={model.id} value={model.id}>{modelLabel(model)}</option>)}</select>
   <span className="composer-context" title="使用本会话历史与已授权的资料"><MessageSquareText size={15} aria-hidden="true"/><span>会话上下文</span></span>
   {state.busy&&<span role="status">处理中</span>}
   {run?.local&&run.runId&&!draft.trim()&&!state.files.length?<button type="button" className="gpt-stop" aria-label="停止任务" title="停止当前任务" onClick={onStop}><Square size={14} fill="currentColor" aria-hidden="true"/></button>:<button type="button" className="gpt-send" aria-label="发送消息" title="发送消息" disabled={disabled||state.busy||(!draft.trim()&&!state.files.length)} onClick={()=>onSend(draft)}><ArrowUp size={18} aria-hidden="true"/></button>}
  </div>
  {state.error&&<p className="control-error" role="alert">{state.error}</p>}
  <div className="model-selection-feedback"><span role="status">{locked?'任务结束后可切换模型':selectedModelMissing(state)?'原选模型已不在可用目录，请选择其他模型':state.modelNotice||''}</span>{state.ready&&state.fallbackEnabled&&<span>请求失败时可使用备用模型，实际调用见执行轨迹</span>}{state.modelError&&<button type="button" disabled={state.busy||disabled} onClick={()=>client.current.refreshModels()}>核对模型选择</button>}</div>
  {state.draftWarning&&<p className="command-hint" role="status">{state.draftWarning}</p>}
  {state.storageWarning&&<p className="composer-state-note" data-tone="warning" role="status"><TriangleAlert size={14} aria-hidden="true"/>{state.storageWarning}</p>}
  {browserOffline&&<p className="composer-state-note" data-tone="warning" role="status"><WifiOff size={14} aria-hidden="true"/>浏览器报告网络离线，当前输入保留；恢复连接后请手动发送，不会自动重发。</p>}
  {state.ready&&!state.filesEnabled&&<p className="composer-state-note">当前服务未启用会话文件上传</p>}
 </div>
});
