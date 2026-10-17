import React,{forwardRef,useEffect,useImperativeHandle,useRef,useState} from 'react';
import {Plus,FileText,X} from 'lucide-react';
import {ComposerResources} from '../../frontend/src/utils/composerResources.js';
export const ComposerToolbar=forwardRef(function Toolbar({sessionId,base,locked,onUpload},ref){
 const [state,setState]=useState({ready:false,files:[],models:[],modelId:'',busy:false,error:''});const input=useRef(null),client=useRef(null);
 if(!client.current)client.current=new ComposerResources({base,onState:setState});
 useEffect(()=>{client.current.open(sessionId);return()=>client.current.close()},[sessionId]);
 useImperativeHandle(ref,()=>({content:text=>client.current.content(text),clear:()=>client.current.clear(),busy:()=>client.current.state.busy}));
 async function upload(event){const files=Array.from(event.target.files||[]);event.target.value='';try{await client.current.upload(files);onUpload?.()}catch(error){client.current.publish({error:error.message})}}
 return <div className="composer-resources">
  {!!state.files.length&&<div className="composer-attachments" aria-label="待发送附件">{state.files.map(file=><div className="composer-attachment" key={file.id}><FileText size={14}/><span title={file.name}>{file.name}</span><button type="button" aria-label={'取消引用 '+file.name} onClick={()=>client.current.remove(file.id)}><X size={13}/></button></div>)}</div>}
  <div className="composer-resource-toolbar"><input type="file" hidden multiple ref={input} accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.md,.csv,.json,.html,.svg" onChange={upload}/><button type="button" aria-label="添加附件" title="上传会话私有文件" disabled={!state.ready||!state.filesEnabled||state.busy} onClick={()=>input.current.click()}><Plus size={19}/></button><select aria-label="使用模型" value={state.modelId} disabled={!state.ready||state.busy||locked} onChange={event=>client.current.select(event.target.value).catch(()=>{})}><option value="">系统默认 · 自动备用</option>{state.models.map(model=><option key={model.id} value={model.id}>{model.model}</option>)}</select>{state.busy&&<span role="status">正在保存</span>}</div>
  {state.error&&<p className="control-error" role="alert">{state.error}</p>}
 </div>
});
