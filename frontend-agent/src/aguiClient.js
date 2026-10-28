// AG-UI transport only. Tool arguments and reasoning never become answer text.
export const A2UI_EVENT = 'doorhandle.a2ui.v1';
export function initialRunState() { return { phase:'connecting', messages:{}, tools:{}, steps:{}, notices:[], text:'' }; }
const id = value => typeof value === 'string' && value.length > 0 && value.length <= 160;
export function reduceRunEvent(state, event) {
  if (!event || typeof event.type !== 'string') throw Error('事件格式不正确');
  let next = { ...state };
  switch (event.type) {
    case 'RUN_STARTED': next.phase='running'; next.runId=event.runId; break;
    case 'RUN_FINISHED': next.phase='finished'; break;
    case 'RUN_ERROR': next.phase='error'; next.error=typeof event.message==='string'?event.message.slice(0,500):'执行失败'; break;
    case 'TEXT_MESSAGE_START':
      if(Object.keys(state.messages).length>=80&&!Object.hasOwn(state.messages,event.messageId))throw Error('本轮消息数量超过展示上限');
      if(id(event.messageId)&&!Object.hasOwn(state.messages,event.messageId)) next.messages={...state.messages,[event.messageId]:{text:'',status:'streaming'}};
      break;
    case 'TEXT_MESSAGE_CONTENT': {
      if(typeof event.delta!=='string') throw Error('文本事件格式不正确');
      const key=id(event.messageId)?event.messageId:'legacy-answer';
      if(Object.keys(state.messages).length>=80&&!Object.hasOwn(state.messages,key))throw Error('本轮消息数量超过展示上限');
      const previous=Object.hasOwn(state.messages,key)?state.messages[key]:{text:'',status:'streaming'};
      if(previous.status==='finished') break;
      if(state.text.length+event.delta.length>200000) throw Error('本轮回答超过展示上限');
      next.messages={...state.messages,[key]:{text:previous.text+event.delta,status:'streaming'}};
      next.text=Object.values(next.messages).map(item=>item.text).join('\n'); break;
    }
    case 'TEXT_MESSAGE_END':
      if(Object.hasOwn(state.messages,event.messageId)) next.messages={...state.messages,[event.messageId]:{...state.messages[event.messageId],status:'finished'}};
      break;
    case 'TOOL_CALL_START':
      if(id(event.toolCallId)&&id(event.toolCallName)&&Object.keys(state.tools).length<80)
        next.tools={...state.tools,[event.toolCallId]:{id:event.toolCallId,name:event.toolCallName,status:'calling'}};
      break;
    case 'TOOL_CALL_END':
      if(Object.hasOwn(state.tools,event.toolCallId)) next.tools={...state.tools,[event.toolCallId]:{...state.tools[event.toolCallId],status:'awaiting-result'}};
      break;
    case 'TOOL_CALL_RESULT':
      if(Object.hasOwn(state.tools,event.toolCallId)) next.tools={...state.tools,[event.toolCallId]:{...state.tools[event.toolCallId],status:'returned',result:typeof event.content==='string'?event.content.slice(0,1200):'已收到工具返回'}};
      break;
    case 'STEP_STARTED': case 'STEP_FINISHED':
      if(id(event.stepName)&&Object.keys(state.steps).length<40) next.steps={...state.steps,[event.stepName]:event.type==='STEP_STARTED'?'running':'finished'};
      break;
    case 'CUSTOM':
      if(event.name==='doorhandle.tool-status.v1'&&['failed','cancelled'].includes(event.value?.status)&&Object.hasOwn(state.tools,event.value?.toolCallId))next.tools={...state.tools,[event.value.toolCallId]:{...state.tools[event.value.toolCallId],status:event.value.status}};
      break;
    case 'TOOL_CALL_ARGS': case 'REASONING_START': case 'REASONING_END': break;
    default:
      if(!state.notices.includes(event.type)&&state.notices.length<8) next.notices=[...state.notices,event.type];
  }
  return next;
}

export async function readAnswer(response, onChange=()=>{}, onCards=()=>{}, options={}) {
  if(!response.ok) throw Error([401,403].includes(response.status)?'请先登录检测系统':`请求失败 (${response.status})`);
  if(!response.body) throw Error('服务未返回流式响应');
  const reader=response.body.getReader(),decoder=new TextDecoder('utf-8',{fatal:true});
  let buffer='',state=initialRunState(),terminal=false,ui=false,trailingCR=false;
  const aborted=()=>{reader.cancel().catch(()=>{});};
  options.signal?.addEventListener('abort',aborted,{once:true});
  function consume(frame) {
    if(terminal) return;
    const data=frame.split('\n').filter(line=>line.startsWith('data:')).map(line=>line.slice(5).replace(/^ /,'')).join('\n');
    if(!data.trim()) return;
    let event;try{event=JSON.parse(data);}catch{throw Error('流式事件未完整解析，已保留收到的回答');}
    state=reduceRunEvent(state,event);
    options.onEvent?.(event); options.onSnapshot?.(state);
    if(event.type==='TEXT_MESSAGE_CONTENT') onChange(state.text);
    if(event.type==='CUSTOM'&&event.name==='doorhandle.business-cards.v1') onCards(event.value);
    if(event.type==='CUSTOM'&&event.name===A2UI_EVENT) {ui=true;options.onA2ui?.(event.value);}
    if(event.type==='RUN_ERROR') throw Error(state.error);
    if(event.type==='RUN_FINISHED') terminal=true;
  }
  try {
    if(options.signal?.aborted) throw new DOMException('已停止接收','AbortError');
    while(!terminal) {
      const {value,done}=await reader.read();
      if(options.signal?.aborted) throw new DOMException('已停止接收','AbortError');
      let part=done?decoder.decode():decoder.decode(value,{stream:true});
      if(part){if(trailingCR&&part.startsWith('\n'))part=part.slice(1);trailingCR=part.endsWith('\r');buffer+=part.replace(/\r\n|\r/g,'\n');}
      let boundary;
      while((boundary=buffer.indexOf('\n\n'))>=0) {const frame=buffer.slice(0,boundary);if(frame.length>524288)throw Error('事件超过展示上限');consume(frame);buffer=buffer.slice(boundary+2);}
      if(buffer.length>524288) throw Error('事件超过展示上限');
      if(done) {if(buffer.trim())consume(buffer);break;}
    }
    if(!terminal) throw Error('连接中断，已保留收到的内容；请核对执行记录');
    if(!state.text&&!ui) throw Error('助手未返回可展示内容，请核对执行记录');
    return state.text;
  } finally {
    options.signal?.removeEventListener('abort',aborted);
    await reader.cancel().catch(()=>{});reader.releaseLock();
  }
}
