// Shared presentation/read boundary for Vue and React. Never derive receipts from prose.
const valid=value=>typeof value==='string'&&/^[A-Za-z0-9_:.-]{1,160}$/.test(value);
const states={TOOL_STARTED:'calling',TOOL_COMPLETED:'returned',TOOL_ERROR:'failed',TOOL_CANCELLED:'cancelled'};
const terminal=new Set(['COMPLETED','ERROR','CANCELLED','INTERRUPTED','finished','error','cancelled','IDLE']);
const labels={read_workspace_file:'读取文件',read_context_file:'读取上下文文件',list_workspace_files:'查看会话文件',create_artifact:'生成文件',get_task_detail:'读取任务',get_my_detection_tasks:'查询检测任务',search_detection_tasks:'检索任务',get_quality_records:'读取质检记录',get_department_work_metrics:'读取工作统计',get_my_work_metrics:'读取工作统计',update_task_list:'更新任务清单',submit_plan:'提交计划',ask_user_question:'请求用户补充',start_background_task:'启动专业任务',get_background_task:'读取专业任务',fetch:'读取网页'};
export const toolTitle=name=>labels[name]||(/^delegate_/.test(name)?'调用专业助手':/report/.test(name)?'处理报告':/knowledge|search/.test(name)?'检索资料':'调用工具');
export const toolStatus=status=>({calling:'正在调用','awaiting-result':'等待返回',returned:'已返回',failed:'运行失败',cancelled:'已取消',unconfirmed:'未收到返回'})[status]||'状态待核对';
export const toolTime=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0?(value>=1000?(value/1000).toLocaleString('zh-CN',{maximumFractionDigits:2})+' 秒':Math.round(value)+' ms'):'';
export function toolRows(events=[],live={}) {
  const rows=new Map();
  for(const event of Array.isArray(events)?events.slice(-800):[]) {
    const p=event?.payload||event,kind=event?.type;
    if(!Object.hasOwn(states,kind)||!valid(p?.callId)||!valid(p?.tool))continue;
    const previous=rows.get(p.callId);
    rows.set(p.callId,{...previous,id:p.callId,name:p.tool,status:states[kind],agent:valid(p.agent)?p.agent:previous?.agent||'',durationMs:typeof p.durationMs==='number'?p.durationMs:previous?.durationMs});
  }
  for(const item of Object.values(live||{})) {
    if(!valid(item?.id)||!valid(item?.name)||!['calling','awaiting-result','returned','failed','cancelled'].includes(item.status))continue;
    const previous=rows.get(item.id);
    // An older stream snapshot cannot overwrite a durable terminal receipt.
    if(previous&&['returned','failed','cancelled'].includes(previous.status)&&['calling','awaiting-result'].includes(item.status))continue;
    rows.set(item.id,{...previous,id:item.id,name:item.name,status:item.status,result:typeof item.result==='string'?item.result.slice(0,1200):previous?.result||'',agent:previous?.agent||''});
  }
  return Array.from(rows.values()).slice(-200);
}
export function toolSummary(rows,phase,{complete=true,truncated=false,known=false}={}) {
  const failed=rows.filter(row=>row.status==='failed').length,waiting=rows.some(row=>['calling','awaiting-result'].includes(row.status));
  if(!rows.length)return terminal.has(phase)?known?'本轮未记录工具调用':'查看工具执行记录':'正在处理';
  const prefix=truncated?'最近记录工具':!complete?'已记录工具':!terminal.has(phase)&&waiting?'正在执行工具':'执行工具';
  return `${prefix} ${rows.length} 次${failed?`，其中 ${failed} 次失败`:''}`;
}
export function messageRunId(message) {
  if(valid(message?.runId))return message.runId;
  if(message?.messageType!=='AGENT_CARDS'||typeof message.content!=='string')return '';
  try{const value=JSON.parse(message.content);return value.version===1&&valid(value.runId)?value.runId:'';}catch{return '';}
}

export class ToolExecutionReader {
  constructor({fetcher=(...args)=>globalThis.fetch(...args),onChange=()=>{}}={}){Object.assign(this,{fetcher,onChange});this.version=0;this.timer=null;this.controller=null;}
  open(sessionId,runId,active=false){this.close();this.session=sessionId;this.runId=runId;this.active=active;this.events=[];this.cursor=0;this.state={events:[],phase:active?'RUNNING':'finished',known:false,complete:false,error:'',denied:false};if(active)this.read();return this.state;}
  publish(patch){this.state={...this.state,...patch};this.onChange(this.state);}
  async read(){
    if(this.pending||!valid(this.runId)||typeof this.session!=='string'||!this.session)return;
    const version=this.version,controller=new AbortController();this.controller=controller;this.pending=true;
    clearTimeout(this.timer);
    const get=async path=>{const response=await this.fetcher(path,{credentials:'include',cache:'no-store',signal:controller.signal});if(!response.ok){const error=Error('执行记录暂不可读取');error.denied=[401,403,404].includes(response.status);throw error;}return response.json();};
    try{
      const base='/api/agent/runs/'+encodeURIComponent(this.runId),run=await get(base);
      if(version!==this.version)return;
      if(run.runId!==this.runId||run.sessionId!==this.session){const error=Error('执行记录与当前会话不匹配');error.denied=true;throw error;}
      if(!Number.isSafeInteger(run.lastSequence)||run.lastSequence<0)throw Error('执行事件序号无效');
      let pages=0;
      while(this.cursor<run.lastSequence&&pages++<8){
        const events=await get(base+'/events?after='+this.cursor+'&limit=100');if(version!==this.version)return;
        if(!Array.isArray(events)||events.length>100)throw Error('执行事件格式无效');
        const before=this.cursor;
        for(const event of events){if(!Number.isSafeInteger(event?.sequence)||event.sequence<=this.cursor)continue;this.cursor=event.sequence;if(Object.hasOwn(states,event.type))this.events=[...this.events,event].slice(-800);}
        if(before===this.cursor)break;
      }
      this.publish({events:this.events,phase:run.status,known:true,complete:this.cursor>=run.lastSequence,truncated:this.events.length>=800||new Set(this.events.map(event=>(event.payload||event).callId)).size>200,error:'',denied:false});
    }catch(error){if(version===this.version&&error.name!=='AbortError'){if(error.denied){this.events=[];this.cursor=0;}this.publish({events:this.events,error:error.denied?'当前账号无权读取此执行，已清除记录':'执行记录未更新，请重新读取',denied:!!error.denied,complete:false});}}
    finally{if(version===this.version){this.pending=false;if(this.active&&!this.state.denied&&!terminal.has(this.state.phase))this.timer=setTimeout(()=>this.read(),2000);}}
  }
  close(){this.version++;this.controller?.abort();clearTimeout(this.timer);this.pending=false;}
}
