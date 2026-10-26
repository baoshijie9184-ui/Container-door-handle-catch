export const controlPhaseLabels={IDLE:'空闲',RUNNING:'执行中',PAUSE_REQUESTED:'等待安全切点暂停',PAUSED:'已暂停',REMOTE_RUNNING:'其他实例执行中',WAITING_PLAN:'等待计划审阅',WAITING_INPUT:'等待补充信息',WAITING_CHILD:'后台专业任务执行中',AWAITING_RECOVERY:'等待核对与恢复'}
export const inputStatusLabels={QUEUED:'待处理',STARTED:'已领取执行',APPLIED:'已交付安全切点',COMPLETED:'已完成',FAILED:'已停止或失败',CANCELLED:'已撤回',EXPIRED:'已过期'}
// The current/first message is not a visible backlog. Show only extra waiting input.
export function showConversationQueue(state){
 const count=(state?.inputs||[]).filter(item=>item.status==='QUEUED').length
 return state?.enabled===true && count>0 && (count>1 || !!state.run?.runId&&state.run.phase!=='IDLE')
}
export function normalizeControl(value,sessionId){
 const run=value?.run
 if(run?.sessionId!==sessionId||!Object.hasOwn(controlPhaseLabels,run.phase)||!Number.isSafeInteger(run.revision)||run.revision<0||typeof run.local!=='boolean'||typeof run.text!=='string'||run.text.length>64000||!Array.isArray(value.inputs)||value.inputs.length>50)throw Error('INVALID_CONTROL')
 const ids=new Set()
 const inputs=value.inputs.map(item=>{
  if(typeof item?.id!=='string'||!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(item.id)||ids.has(item.id)||!['NEXT_TURN','NEXT_STEP'].includes(item.mode)||!Object.hasOwn(inputStatusLabels,item.status)||!Number.isSafeInteger(item.revision)||item.revision<0||typeof item.content!=='string'||item.content.length>8000)throw Error('INVALID_INPUT')
  ids.add(item.id);return {id:item.id,mode:item.mode,status:item.status,revision:item.revision,content:item.content}
 })
 return {run:{sessionId,runId:typeof run.runId==='string'?run.runId:null,phase:run.phase,revision:run.revision,local:run.local,text:run.text},inputs}
}
// Reads may be repeated. Mutations are never retried automatically; an uncertain submit retains its request ID.
export class ConversationControlClient{
 constructor({base='/api/agent/conversations',entryPoint='CHAT',fetcher=(...args)=>globalThis.fetch(...args),onState=()=>{},onRefresh=()=>{}}={}){Object.assign(this,{base,entryPoint,fetcher,onState,onRefresh});this.generation=0;this.enabled=false;this.timer=null;this.session='';this.uncertain=new Map();this.writing=false}
 async request(path,body){
  const response=await this.fetcher(this.base+path,{credentials:'include',cache:'no-store',...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Agent-Action':'conversation-control'},body:JSON.stringify(body)})})
  if(!response.ok)throw Error(response.status===409?'状态已变化，请刷新核对；不会自动重试。':response.status===429?'待处理消息或本轮补充要求已达上限，请等待或撤回。':'操作结果未确认，请刷新核对；不会自动重试。')
  return response.json()
 }
 async open(session){
  clearTimeout(this.timer);const generation=++this.generation;this.session=session;this.state=null;this.fingerprint='';this.onState({enabled:false,run:null,inputs:[],error:''})
  if(!session)return
  try{this.queueEnabled=globalThis.sessionStorage?.getItem('conversation-queue:'+session)!=='off'}catch{this.queueEnabled=true}
  try{const capability=await this.request('/capabilities');if(generation!==this.generation)return;this.enabled=capability.enabled===true;
   if(this.enabled)await this.poll(generation)
  }catch{if(generation===this.generation){this.enabled=false;this.onState({enabled:false,run:null,inputs:[],error:''})}}
 }
 async poll(generation=this.generation){
  if(generation!==this.generation||!this.enabled)return
  const readVersion=this.readVersion=(this.readVersion||0)+1
  clearTimeout(this.timer)
  try{
   const data=normalizeControl(await this.request('/'+encodeURIComponent(this.session)+'/control'),this.session)
   if(generation!==this.generation||readVersion!==this.readVersion)return
   this.state=data;this.onState({enabled:true,...data,queueEnabled:this.queueEnabled!==false,error:''})
   const fingerprint=JSON.stringify([data.run.runId,data.run.phase,data.inputs.map(item=>[item.id,item.status,item.revision])])
   if(fingerprint!==this.fingerprint){this.fingerprint=fingerprint;this.onRefresh(this.session)}
  }catch{if(generation===this.generation&&readVersion===this.readVersion){this.state=null;this.onState({enabled:true,run:null,inputs:[],error:'执行状态暂不可用，已禁用控制操作，请刷新核对。'})}}
  finally{if(generation===this.generation&&readVersion===this.readVersion)this.timer=setTimeout(()=>this.poll(generation),2000)}
 }
 async write(path,body){if(this.writing)throw Error('正在提交，请稍候');this.writing=true;const generation=this.generation;
  try{const result=await this.request(path,body);if(generation===this.generation)await this.poll(generation);return result}finally{this.writing=false}
 }
 async submit(content,mode='NEXT_TURN'){
  if(this.writing)throw Error('正在提交，请稍候')
  if(!this.enabled||!this.state)throw Error('请先刷新执行状态')
  if(mode==='NEXT_TURN'&&this.queueEnabled===false&&(this.state.run.runId||this.state.inputs.some(item=>['QUEUED','STARTED'].includes(item.status))))throw Error('消息排队已关闭，请等待待发消息处理完毕，或开启排队后再发送')
  const signature=JSON.stringify([this.session,mode,content]);
  if(!this.uncertain.has(signature)){if(this.uncertain.size>=16)throw Error('存在未核实的提交，请先刷新核对');this.uncertain.set(signature,crypto.randomUUID())}
  const id=this.uncertain.get(signature)
  const result=await this.write('/'+encodeURIComponent(this.session)+'/inputs',{id,mode,content,entryPoint:this.entryPoint})
  if(this.uncertain.get(signature)===id)this.uncertain.delete(signature)
  return result
 }
 change(item,content){return this.write('/'+encodeURIComponent(this.session)+'/inputs/'+encodeURIComponent(item.id),{revision:item.revision,content})}
 setQueueEnabled(enabled){this.queueEnabled=enabled===true;try{globalThis.sessionStorage?.setItem('conversation-queue:'+this.session,this.queueEnabled?'on':'off')}catch{/* The current view still retains the choice. */}if(this.state)this.onState({enabled:this.enabled,...this.state,queueEnabled:this.queueEnabled,error:''})}
 steer(item){const run=this.state?.run;if(!run?.runId||run.phase==='IDLE')throw Error('当前没有可引导的任务，请刷新核对');return this.write('/'+encodeURIComponent(this.session)+'/inputs/'+encodeURIComponent(item.id)+'/steer',{revision:item.revision,runId:run.runId})}
 command(action){const run=this.state?.run;if(!run?.local||!run.runId)throw Error('当前实例无法控制此执行，请刷新核对');return this.write('/'+encodeURIComponent(this.session)+'/control',{runId:run.runId,action,revision:run.revision,confirmed:action==='cancel'})}
 close(){this.generation++;this.enabled=false;clearTimeout(this.timer);this.state=null}
}
