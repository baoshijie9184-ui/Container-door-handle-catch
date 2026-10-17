// Both chat entrances use session-owned files and a versioned server model preference.
export class ComposerResources {
 constructor({base='',fetcher=(...args)=>fetch(...args),onState=()=>{}}={}){Object.assign(this,{base,fetcher,onState});this.generation=0;this.pending=new Map();this.state={ready:false,files:[],models:[],modelId:'',revision:0,busy:false,error:''}}
 publish(value){this.state={...this.state,...value};this.onState(this.state)}
 path(){return '/api/agent/conversations/'+encodeURIComponent(this.session)}
 async request(path,options={}){const response=await this.fetcher(this.base+path,{credentials:'include',cache:'no-store',...options});if(!response.ok)throw Error(response.status===409?'状态已变化，请刷新模型选择后再试':response.status===413?'文件大小或账号配额超出限制':response.status===400?'文件类型或模型选择无效':'操作结果未确认，请刷新核对后手动重试');return response.json()}
 async open(session){const generation=++this.generation;this.session=session;this.publish({ready:false,files:[],models:[],modelId:'',revision:0,busy:false,error:''});if(!session)return;try{
  const [cap,catalog,selection]=await Promise.all([this.request('/api/agent/workbench/capabilities'),this.request('/agui/models'),this.request(this.path()+'/model-selection')]);
  if(generation!==this.generation)return;if(!cap.enabled)return;
  if(typeof selection.modelId!=='string'||!Number.isSafeInteger(selection.revision)||!Array.isArray(catalog.models))throw Error('模型选择格式无效');
  this.publish({ready:true,filesEnabled:cap.files===true,models:catalog.models.filter(m=>m.configured===true&&typeof m.id==='string'&&typeof m.model==='string'),modelId:selection.modelId,revision:selection.revision});
 }catch{/* Older backends keep their text composer. */}}
 async select(modelId){if(this.state.busy||!this.state.ready)throw Error('请等待当前操作');const generation=this.generation;const key=JSON.stringify([this.session,modelId,this.state.revision]);if(!this.pending.has(key))this.pending.set(key,crypto.randomUUID());this.publish({busy:true,error:''});try{
  const data=await this.request(this.path()+'/model-selection',{method:'POST',headers:{'Content-Type':'application/json','X-Agent-Action':'workbench'},body:JSON.stringify({modelId,revision:this.state.revision,requestId:this.pending.get(key)})});this.pending.delete(key);if(generation===this.generation)this.publish({modelId:data.modelId,revision:data.revision});
 }catch(error){if(generation===this.generation)this.publish({error:error.message});throw error}finally{if(generation===this.generation)this.publish({busy:false})}}
 async upload(files){if(this.state.busy||!this.state.ready||!this.state.filesEnabled)throw Error('文件工作区暂不可用');const generation=this.generation;if(files.length+this.state.files.length>8)throw Error('一条消息最多附加 8 个文件');this.publish({busy:true,error:''});try{
  for(const file of files){if(generation!==this.generation)break;if(file.size>26214400)throw Error('每个文件最多 25 MB');const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer())),b=>b.toString(16).padStart(2,'0')).join('');if(generation!==this.generation)break;
   const key=JSON.stringify([this.session,file.name,file.size,digest]);if(!this.pending.has(key)){if(this.pending.size>=16)throw Error('存在未确认的上传，请先核对文件工作区');this.pending.set(key,crypto.randomUUID())}
   const form=new FormData();form.set('requestId',this.pending.get(key));form.set('file',file);const data=await this.request(this.path()+'/files',{method:'POST',headers:{'X-Agent-Action':'workbench'},body:form});this.pending.delete(key);if(generation!==this.generation)break;if(!/^[a-f0-9-]{36}$/.test(data.id)||typeof data.name!=='string')throw Error('文件响应无效');this.publish({files:[...this.state.files.filter(f=>f.id!==data.id),{id:data.id,name:data.name,bytes:data.bytes}]});
  }
 }catch(error){if(generation===this.generation)this.publish({error:error.message});throw error}finally{if(generation===this.generation)this.publish({busy:false})}}
 remove(id){this.publish({files:this.state.files.filter(f=>f.id!==id)})}
 content(text){return [text.trim(),...this.state.files.filter(file=>!text.includes('@file:'+file.id)).map(file=>'@file:'+file.id)].filter(Boolean).join('\n')}
 clear(){this.publish({files:[]})}
 close(){this.generation++}
}
