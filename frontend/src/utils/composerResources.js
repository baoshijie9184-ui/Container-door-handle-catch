import { captureWorkspaceFetch } from './captureWorkspaceFetch.js'

// Both chat entrances use session-owned files and versioned server preferences.
export const APPROVAL_MODES = [
  { value:'MANUAL', label:'请求人工审查', description:'每次工具调用前由你审查。' },
  { value:'DEFAULT', label:'默认', description:'日常操作直接运行，敏感业务沿用原有确认。' },
  { value:'AUTO', label:'自动', description:'按风险决定是否审查，外部网页抓取等操作先确认。' },
  { value:'FAST', label:'极速模式', description:'已授权的调用直接执行，业务审批与许可仍按原流程。' }
]
const initialApprovalMode = () => ({ mode:'DEFAULT', revision:0, ready:false, loading:false, unavailable:false, unverified:false, error:'', notice:'' })
export function approvalModeDetails(mode){return APPROVAL_MODES.find(option=>option.value===mode) || APPROVAL_MODES[1]}
function validApprovalSelection(value){
  if(!APPROVAL_MODES.some(option=>option.value===value?.mode)||!Number.isSafeInteger(value.revision)||value.revision<0){
    throw Error('审批模式回执无效，请重新读取')
  }
  return {mode:value.mode,revision:value.revision}
}

export function modelLabel(model){const provider={dashscope:'百炼',deepseek:'DeepSeek 直连',openai:'OpenAI'}[model.provider]||model.provider;return provider?`${model.model} · ${provider}`:model.model}
export function defaultModelLabel(state){const model=state.models.find(item=>item.id===state.defaultModelId);return model?'系统默认 · '+modelLabel(model):'系统默认'}
export function selectedModelMissing(state){return !!state.modelId&&!state.models.some(model=>model.id===state.modelId)}
function validSelection(value){if(typeof value?.modelId!=='string'||!Number.isSafeInteger(value.revision)||value.revision<0)throw Error('模型选择响应无效，请核对后再试');return value}
function catalogState(catalog){if(!Array.isArray(catalog?.models))throw Error('模型目录暂不可用');return {models:catalog.models.filter(m=>m.configured===true&&typeof m.id==='string'&&typeof m.model==='string'),defaultModelId:typeof catalog.selectedModel==='string'?catalog.selectedModel:'',fallbackEnabled:catalog.fallbackEnabled===true}}
export class ComposerResources {
 constructor({base='',fetcher=captureWorkspaceFetch(),onState=()=>{},onDraft=()=>{},storage}={}){Object.assign(this,{base,fetcher,onState,onDraft,storage});this.generation=0;this.pending=new Map();this.text='';this.edits=0;this.hydrated=false;this.state={ready:false,modelDisabled:false,filesEnabled:false,filesLoaded:false,files:[],models:[],defaultModelId:'',fallbackEnabled:false,modelId:'',revision:0,busy:false,error:'',modelError:false,modelNotice:'',approvalMode:initialApprovalMode()}}
 publish(value){this.state={...this.state,...value};this.onState(this.state);if(Object.hasOwn(value,'files'))this.persist()}
 draft(text){const value=typeof text==='string'?text:'';if(value!==this.text){this.text=value;this.edits++;this.persist()}}
 persist(){
  const setStorageWarning=message=>{if(this.state.storageWarning!==message)this.publish({storageWarning:message})};
  if(!this.hydrated||!this.draftKey){setStorageWarning(this.text||this.state.files.length?'草稿暂时只保留在当前页面，关闭前请复制文字备份':'');return}
  const warning=this.text.length>20000?'草稿超过 20000 字，仅当前页面保留':'';
  if(this.state.draftWarning!==warning)this.publish({draftWarning:warning});
  try{
   const storage=this.storage??globalThis.sessionStorage,pending=[...this.pending].filter(([key])=>JSON.parse(key)[0]===this.session).slice(-16);
   if(!storage)throw Error('DRAFT_STORAGE_UNAVAILABLE');
   if(warning)storage.removeItem(this.draftKey);
   else if(this.text||this.state.files.length||pending.length)storage.setItem(this.draftKey,JSON.stringify({version:1,text:this.text,files:this.state.files.map(file=>file.id),pending}));
   else storage.removeItem(this.draftKey);
   setStorageWarning('');
  }catch{setStorageWarning('浏览器未能暂存草稿，请保留页面并复制文字备份；未确认的操作请先核对，不要重复提交')}
 }
 path(){return '/api/agent/conversations/'+encodeURIComponent(this.session)}
 async request(path,options={}){
  const response=await this.fetcher(this.base+path,{credentials:'include',cache:'no-store',...options});
  const data=await response.json?.().catch(()=>null);
  const status=response.ok&&Number.isInteger(data?.code)&&data.code!==200?data.code:response.status;
  if(!response.ok||status>=400){
   const message={400:'文件类型或模型选择无效',401:'登录已失效，请重新登录',403:'当前账号无权访问此会话',404:'会话或服务入口不存在',409:'状态已变化，请重新读取模型选择',413:'文件大小、尺寸或账号配额超出限制',415:'文件格式、编码或内容无效，请核对后重新上传',429:'文件解析繁忙，请稍后重试'}[status];
   const preference=path.endsWith('/model-selection')||path.endsWith('/approval-mode');
   const fallback=status===409&&path.endsWith('/approval-mode')?'会话状态已变化，请核对当前审批模式':message;
   const error=Error(status===409&&preference&&typeof data?.message==='string'?data.message:fallback||'操作结果未确认，请刷新核对后手动重试');
   error.status=status;throw error
  }
  return data
 }
 async open(session){const generation=++this.generation;this.session=session;this.hydrated=false;this.draftKey=null;this.text='';this.edits=0;this.onDraft('');this.publish({draftWarning:'',ready:false,modelDisabled:false,filesEnabled:false,filesLoaded:false,files:[],models:[],defaultModelId:'',fallbackEnabled:false,modelId:'',revision:0,busy:false,error:'',modelError:false,modelNotice:'',approvalMode:initialApprovalMode()});if(!session)return;
  await Promise.all([this.readModels(generation),this.restoreDraft(session,generation),this.readApprovalMode(generation)])
 }
 async restoreDraft(session,generation){
  const [cap,identity]=await Promise.all([this.request('/api/agent/workbench/capabilities').catch(()=>null),this.request('/api/auth/check').catch(()=>null)]);
  if(generation!==this.generation)return;
  let cached=null,restored=[],warning='';const account=identity?.code===200?identity.data:null;
  if(typeof account?.username==='string'&&account.username){this.draftKey='doorhandle-composer:v1:'+JSON.stringify([account.userId??account.username,account.username,session]);try{const raw=(this.storage??globalThis.sessionStorage)?.getItem(this.draftKey);if(raw&&raw.length<48000){const value=JSON.parse(raw);if(value.version===1&&typeof value.text==='string'&&value.text.length<=20000&&Array.isArray(value.files)&&value.files.length<=8&&value.files.every(id=>typeof id==='string'&&/^[a-f0-9-]{36}$/.test(id)))cached=value}}catch{/* Unavailable storage does not disable chatting. */}}
  if(cached){if(Array.isArray(cached.pending))for(const entry of cached.pending.slice(0,16))try{const [key,id]=entry;if(typeof key==='string'&&key.length<1000&&JSON.parse(key)[0]===session&&typeof id==='string'&&/^[a-f0-9-]{36}$/.test(id))this.pending.set(key,id)}catch{/* Ignore invalid draft receipts. */}if(!this.edits){this.text=cached.text;this.onDraft(cached.text)}if(cached.files.length&&cap?.enabled===true&&cap.files===true){try{const workbench=await this.request(this.path()+'/workbench');if(generation!==this.generation)return;if(!Array.isArray(workbench.files))throw Error();restored=cached.files.flatMap(id=>{const file=workbench.files.find(file=>file.id===id);return file&&typeof file.name==='string'&&Number.isSafeInteger(file.bytes)?[{id,name:file.name,bytes:file.bytes}]:[]});if(restored.length!==cached.files.length)warning='部分附件已移除或权限已变化，未恢复引用'}catch{warning='附件草稿尚未核对，请刷新重试';this.draftKey=null}}}
  if(generation!==this.generation)return;this.hydrated=true;
  this.publish({filesLoaded:true,filesEnabled:cap?.enabled===true&&cap.files===true,files:restored,...(warning?{error:warning}:{})});
 }
 async readModels(generation,notice=''){
  try{
   const selection=await this.request(this.path()+'/model-selection');
   if(generation!==this.generation)return;
   if(selection?.enabled===false){this.publish({ready:false,modelDisabled:true,modelError:false,modelNotice:''});return}
   validSelection(selection);
   const catalog=catalogState(await this.request('/agui/models'));
   if(generation!==this.generation)return;
   this.publish({...catalog,ready:true,modelDisabled:false,modelId:selection.modelId,revision:selection.revision,modelError:false,modelNotice:notice});
   return true
  }catch(error){if(generation===this.generation)this.publish({ready:false,modelError:true,modelNotice:error.status===401||error.status===403?error.message:'模型选择读取失败，请重新读取'})}
 }
 clearModelReceipts(){for(const key of this.pending.keys()){const parts=JSON.parse(key);if(parts.length===3&&parts[0]===this.session)this.pending.delete(key)}}
 async refreshModels(){if(this.state.busy||!this.session)return;const generation=this.generation;this.publish({busy:true,error:'',modelNotice:''});
  try{if(await this.readModels(generation,'已核对当前会话的模型选择'))this.clearModelReceipts()}
  finally{if(generation===this.generation){this.persist();this.publish({busy:false})}}
 }
 async select(modelId){if(this.state.busy||!this.state.ready)throw Error('请等待当前操作');const generation=this.generation;const key=JSON.stringify([this.session,modelId,this.state.revision]);if(!this.pending.has(key))this.pending.set(key,crypto.randomUUID());this.persist();this.publish({busy:true,error:'',modelNotice:''});try{
  const data=validSelection(await this.request(this.path()+'/model-selection',{method:'POST',headers:{'Content-Type':'application/json','X-Agent-Action':'workbench'},body:JSON.stringify({modelId,revision:this.state.revision,requestId:this.pending.get(key)})}));this.pending.delete(key);if(generation===this.generation)this.publish({modelId:data.modelId,revision:data.revision,modelError:false,modelNotice:'已保存，仅对当前会话的新任务生效'});
  }catch(error){
  if(generation===this.generation){
   if(error.status===409){
    if(await this.readModels(generation,error.message))this.clearModelReceipts()
   }else this.publish({error:error.message,modelError:true,modelNotice:''})
  }
  throw error
 }finally{if(generation===this.generation){this.persist();this.publish({busy:false})}}}
 updateApprovalMode(value){this.publish({approvalMode:{...this.state.approvalMode,...value}})}
 async readApprovalMode(generation,notice=''){
  this.updateApprovalMode({loading:true,error:'',notice:''});
  try{
   const selection=validApprovalSelection(await this.request(this.path()+'/approval-mode'));
   if(generation===this.generation)this.updateApprovalMode({...selection,ready:true,loading:false,unavailable:false,unverified:false,error:'',notice});
  }catch(error){
   if(generation!==this.generation)return;
   const unavailable=error.status===404&&!this.state.approvalMode.unverified&&!this.state.approvalMode.ready;
   this.updateApprovalMode({ready:false,loading:false,unavailable,error:unavailable?'':'审批模式暂不可读取，请重新核对',notice:''});
  }
 }
 async refreshApprovalMode(){
  if(!this.session||this.state.busy||this.state.approvalMode.loading)return;
  await this.readApprovalMode(this.generation)
 }
 async selectApprovalMode(mode){
  const current=this.state.approvalMode;
  if(this.state.busy||!current.ready||current.loading||current.unverified)throw Error('请先核对当前审批模式');
  if(mode===current.mode)return;
  if(!APPROVAL_MODES.some(option=>option.value===mode))throw Error('审批模式无效');
  const generation=this.generation;
  this.publish({busy:true});
  this.updateApprovalMode({error:'',notice:''});
  try{
   const selection=validApprovalSelection(await this.request(this.path()+'/approval-mode',{
    method:'POST',headers:{'Content-Type':'application/json','X-Agent-Action':'workbench'},
    body:JSON.stringify({mode,revision:current.revision,requestId:crypto.randomUUID()})
   }));
   if(generation===this.generation){
    if(selection.mode!==mode||selection.revision<=current.revision)throw Error('审批模式回执不一致');
    this.updateApprovalMode({...selection,ready:true,unverified:false,notice:''})
   }
  }catch(error){
   if(generation===this.generation){
    if(error.status===409){
     this.updateApprovalMode({ready:false,unverified:true});
     await this.readApprovalMode(generation,error.message);
    }
    else{
     const unverified=![400,401,403,404].includes(error.status);
     this.updateApprovalMode({ready:false,unverified,error:unverified?'审批模式更新结果待核对，重新读取后可继续发送':error.message})
    }
   }
   throw error
  }finally{if(generation===this.generation)this.publish({busy:false})}
 }
 async upload(files){if(this.state.busy||!this.state.filesEnabled)throw Error('文件工作区暂不可用');const generation=this.generation;if(files.length+this.state.files.length>8)throw Error('一条消息最多附加 8 个文件');this.publish({busy:true,error:''});try{
  for(const file of files){if(generation!==this.generation)break;if(file.size>26214400)throw Error('每个文件最多 25 MB');const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer())),b=>b.toString(16).padStart(2,'0')).join('');if(generation!==this.generation)break;
   const key=JSON.stringify([this.session,file.name,file.size,digest]);if(!this.pending.has(key)){if(this.pending.size>=16)throw Error('存在未确认的上传，请先核对文件工作区');this.pending.set(key,crypto.randomUUID())}this.persist();
   const form=new FormData();form.set('requestId',this.pending.get(key));form.set('file',file);let data;try{data=await this.request(this.path()+'/files',{method:'POST',headers:{'X-Agent-Action':'workbench'},body:form})}catch(error){if([400,413,415,429].includes(error.status)){this.pending.delete(key);this.persist()}throw error}this.pending.delete(key);if(generation!==this.generation)break;if(!/^[a-f0-9-]{36}$/.test(data.id)||typeof data.name!=='string')throw Error('文件响应无效');this.publish({files:[...this.state.files.filter(f=>f.id!==data.id),{id:data.id,name:data.name,bytes:data.bytes}]});
  }
 }catch(error){if(generation===this.generation)this.publish({error:error.message});throw error}finally{if(generation===this.generation)this.publish({busy:false})}}
 remove(id){this.publish({files:this.state.files.filter(f=>f.id!==id)})}
 content(text){return [text.trim(),...this.state.files.filter(file=>!text.includes('@file:'+file.id)).map(file=>'@file:'+file.id)].filter(Boolean).join('\n')}
 clear(){this.text='';this.publish({files:[]})}
 close(){this.generation++}
}
