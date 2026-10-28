import React,{Suspense,lazy,useState} from 'react';
import {Markdown} from '@agentscope-ai/chat';
import {Button,Tooltip} from 'antd';
import {Check,Copy,UserRound,Bot} from 'lucide-react';
import {businessDate} from '../../frontend/src/utils/beijingTime';
import {ExecutionTimeline} from './ExecutionTimeline';
const DynamicResults=lazy(()=>import('./DynamicResults').then(module=>({default:module.DynamicResults})));
export function WorkbenchMessage({text='',role='assistant',createdAt,status,references=[],sessionId,onFollowUp,surfaces,businessBase='',execution,runId,controlRun}) {
  const [copied,setCopied]=useState(false),[copyError,setCopyError]=useState('');
  const time=businessDate(createdAt);
  async function copy(){try{await navigator.clipboard.writeText(text);setCopied(true);setCopyError('');}catch{setCopyError('复制失败，请选择正文后复制');}}
  return <article className={`workbench-message ${role}`}><header><span className="message-role-icon">{role==='assistant'?<Bot size={15}/>:<UserRound size={15}/>}</span><strong>{role==='assistant'?'检测工作助手':'你'}</strong>{time&&!Number.isNaN(time.valueOf())&&<time dateTime={createdAt}>{time.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',timeZone:'Asia/Shanghai'})}</time>}{status&&<small>{status==='generating'?'正在生成':status==='error'?'未完成':status==='interrupted'?'已中断':''}</small>}</header>{role==='assistant'&&(execution||runId||controlRun)&&<ExecutionTimeline state={execution} sessionId={sessionId} runId={runId} controlRun={controlRun}/>}<div className="message-body">{text&&<Markdown content={text} cursor={status==='generating'}/>}</div>{(references.length>0||Object.keys(surfaces||{}).length>0)&&<Suspense fallback={<p className="a2ui-placeholder" role="status">正在加载分析结果</p>}><DynamicResults businessBase={businessBase} references={references} sessionId={sessionId} onFollowUp={onFollowUp} initialSurfaces={surfaces}/></Suspense>}<footer>{text&&<Tooltip title={copied?'已复制':'复制正文'}><Button type="text" size="small" aria-label={copied?'已复制正文':'复制正文'} icon={copied?<Check size={13}/>:<Copy size={13}/>} onClick={copy}>{copied?'已复制':'复制'}</Button></Tooltip>}{copyError&&<small role="status">{copyError}</small>}</footer></article>;
}
