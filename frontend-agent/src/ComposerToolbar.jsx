import React,{forwardRef,useEffect,useImperativeHandle,useRef,useState} from 'react';
import {Plus,FileText,X,ShieldCheck,MessageSquareText,Square,ArrowUp} from 'lucide-react';
import {ComposerResources} from '../../frontend/src/utils/composerResources.js';
export const ComposerToolbar=forwardRef(function Toolbar({sessionId,base,locked,onUpload,run,draft='',onDraft,onSend,onStop,disabled},ref){
 const [state,setState]=useState({ready:false,files:[],models:[],modelId:'',busy:false,error:''});const input=useRef(null),client=useRef(null);
 if(!client.current)client.current=new ComposerResources({base,onState:setState,onDraft:value=>onDraft?.(value)});
 useEffect(()=>{client.current.open(sessionId);return()=>client.current.close()},[sessionId]);
 useEffect(()=>{client.current.draft(draft)},[draft]);
 useImperativeHandle(ref,()=>({content:text=>client.current.content(text),clear:()=>client.current.clear(),busy:()=>client.current.state.busy}));
 async function upload(event){const files=Array.from(event.target.files||[]);event.target.value='';try{await client.current.upload(files);onUpload?.()}catch(error){client.current.publish({error:error.message})}}
 return <div className="composer-resources">
  {!!state.files.length&&<div className="composer-attachments" aria-label="待发送附件">{state.files.map(file=><div className="composer-attachment" key={file.id}><FileText size={14}/><span title={file.name}>{file.name}</span><button type="button" aria-label={'取消引用 '+file.name} onClick={()=>client.current.remove(file.id)}><X size={13}/></button></div>)}</div>}
  <div className="composer-resource-toolbar"><input type="file" hidden multiple ref={input} accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.md,.csv,.json,.html,.svg" onChange={upload}/><button type="button" aria-label="添加附件" title="上传会话私有文件" disabled={!state.ready||!state.filesEnabled||state.busy||disabled} onClick={()=>input.current.click()}><Plus size={19}/></button><span className="composer-permission" title="工具按当前账号权限执行，敏感操作仍需人工确认"><ShieldCheck size={15}/><span>按账号权限</span></span><select aria-label="使用模型" value={state.modelId} disabled={!state.ready||state.busy||locked||disabled} onChange={event=>client.current.select(event.target.value).catch(()=>{})}><option value="">系统默认</option>{state.models.map(model=><option key={model.id} value={model.id}>{model.model}</option>)}</select><span className="composer-context" title="使用本会话历史与已授权的资料"><MessageSquareText size={15}/><span>会话上下文</span></span>{state.busy&&<span role="status">正在保存</span>}{run?.local&&run.runId&&!draft.trim()&&!state.files.length?<button type="button" className="gpt-stop" aria-label="停止任务" onClick={onStop}><Square size={14} fill="currentColor"/></button>:<button type="button" className="gpt-send" aria-label="发送消息" disabled={disabled||state.busy||(!draft.trim()&&!state.files.length)} onClick={()=>onSend(draft)}><ArrowUp size={18}/></button>}</div>
  {state.error&&<p className="control-error" role="alert">{state.error}</p>}
  {state.draftWarning&&<p className="command-hint" role="status">{state.draftWarning}</p>}
 </div>
});
