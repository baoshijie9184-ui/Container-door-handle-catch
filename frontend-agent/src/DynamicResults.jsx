import React,{useEffect,useRef,useState} from 'react';
import {Alert,Button,Skeleton} from '@agentscope-ai/design';
import {Layers,RefreshCw} from 'lucide-react';
import {A2uiSurface} from './A2uiSurface';
import {A2UI_CATALOG,A2UI_VERSION,readA2uiMessages} from './a2uiState';
import {AgentResultCards} from './AgentResultCards';

export function DynamicResults({references,sessionId,onFollowUp,initialSurfaces,businessBase=''}) {
  const [detailsOpen,setDetailsOpen]=useState(false);
  const [surfaces,setSurfaces]=useState(initialSurfaces||{}),[loading,setLoading]=useState(false),[error,setError]=useState(''),[legacy,setLegacy]=useState(false);
  const generation=useRef(0),controller=useRef(null),reading=useRef(false),alive=useRef(true);
  const key=JSON.stringify([sessionId,references]);
  async function refresh() {
    if(reading.current||!references.length)return;
    const version=generation.current,abort=new AbortController();controller.current=abort;reading.current=true;setLoading(true);setError('');
    try {
      const response=await fetch('/agui/ui/resolve',{method:'POST',credentials:'include',cache:'no-store',signal:abort.signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({sessionId,cards:references})});
      if(!response.ok){const failure=Error('动态结果读取未完成');failure.status=response.status;throw failure;}
      const payload=await response.json();
      if(payload.version!==A2UI_VERSION||payload.catalogId!==A2UI_CATALOG)throw Error('此动态界面版本暂不支持');
      const next=readA2uiMessages(payload.messages);
      if(alive.current&&version===generation.current){setSurfaces(next);setLegacy(false);}
    } catch(failure) {
      if(!alive.current||version!==generation.current||failure.name==='AbortError')return;
      if([404,405].includes(failure.status)){setLegacy(true);setSurfaces({});}
      else {if([401,403].includes(failure.status))setSurfaces({});setError([401,403].includes(failure.status)?'当前账号无权读取结果，已清除动态界面。':'动态结果未更新；已展示的数据为上次快照，请重新读取。');}
    } finally {if(alive.current&&version===generation.current){setLoading(false);reading.current=false;}}
  }
  useEffect(()=>{alive.current=true;generation.current++;setSurfaces(initialSurfaces||{});setLegacy(false);setError('');reading.current=false;if(!initialSurfaces||!Object.keys(initialSurfaces).length)refresh();return()=>{alive.current=false;generation.current++;controller.current?.abort();};},[key]);
  useEffect(()=>{if(initialSurfaces&&Object.keys(initialSurfaces).length)setSurfaces(initialSurfaces);},[initialSurfaces]);
  async function action(event) {
    if(event.name==='REFRESH'){await refresh();return;}
    if(!onFollowUp)throw Error('请在可发送消息的会话中继续分析');
    const version=generation.current;
    const response=await fetch('/agui/ui/actions',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json','X-Agent-Action':'a2ui'},body:JSON.stringify({sessionId,cards:references,action:event})});
    if(!alive.current||version!==generation.current)return;
    if(!response.ok){if([401,403].includes(response.status))setSurfaces({});throw Error('交互未通过当前权限或参数校验，请刷新后核对');}
    const result=await response.json();
    if(!alive.current||version!==generation.current)return;
    if(typeof result.question!=='string'||!result.question.trim()||result.question.length>8000)throw Error('后续问题格式无效');
    await onFollowUp(result.question);
  }
  if(legacy)return <AgentResultCards references={references} businessBase={businessBase}/>;
  return <section className="dynamic-results" aria-label="交互式业务结果"><header><span><Layers size={15}/>分析结果</span><small>按当前账号读取</small></header>{loading&&!Object.keys(surfaces).length&&<Skeleton active paragraph={{rows:3}}/>}{Object.values(surfaces).map(surface=><A2uiSurface key={surface.surfaceId} surface={surface} onAction={action} onRetry={refresh} disabled={loading||!references.length}/>)}{references.length>0&&!error&&<details className="original-result-details" onToggle={event=>setDetailsOpen(event.currentTarget.open)}><summary>查看业务明细与操作入口</summary>{detailsOpen&&<AgentResultCards references={references} businessBase={businessBase}/>}</details>}{error&&<Alert type="warning" showIcon message={error} action={<Button size="small" iconSize={14} icon={<RefreshCw size={13}/>} onClick={refresh} disabled={loading}>重新读取</Button>}/>}</section>;
}
