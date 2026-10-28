import { validCardReference } from '../../frontend/src/utils/agentCards.js';
import {messageRunId} from '../../frontend/src/utils/toolExecution.js';

export async function readSession(response) {
  if (!response.ok) throw new Error(response.status===401||response.status===403?'请先登录检测系统':`会话读取失败 (${response.status})`);
  const payload=await response.json();
  if(payload.code!==200||payload.data==null)throw new Error('会话不可用 请刷新或重新登录');
  return payload.data;
}

export function sessionItems(messages, renderCards) {
  return (Array.isArray(messages)?messages:[]).filter(item=>item&&(item.role==='user'||item.role==='assistant')).map(item=>{
    let text=typeof item.content==='string'?item.content:'';let references=[];
    if(item.messageType==='AGENT_CARDS'){
      try{const envelope=JSON.parse(text);if(envelope.version!==1||typeof envelope.text!=='string'||!Array.isArray(envelope.cards)||envelope.cards.length>8||!envelope.cards.every(validCardReference))return null;text=envelope.text;references=envelope.cards;}
      catch{return null;}
    }else if(item.messageType&&item.messageType!=='TEXT')return null;
    return {key:String(item.id),role:item.role,text,references,runId:messageRunId(item),createdAt:item.createdAt,content:references.length?'':text,cards:references.length?renderCards(text,references):undefined};
  }).filter(Boolean);
}
