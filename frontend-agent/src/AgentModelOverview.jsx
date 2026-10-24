import React,{useState} from 'react';
import {Cpu,KeyRound,RefreshCw,Search,TriangleAlert,X,Workflow} from 'lucide-react';
import StatusBadge from './StatusBadge';
import {agentConfigText,agentConfigFlag,agentConfigNumber,agentConfigDuration,agentFallbackOrder,agentModelCircuit,agentCapabilityLabel} from '../../frontend/src/utils/agentCatalogPresentation';
import '../../frontend/src/assets/agent-service-overview.css';

export default function AgentModelOverview({catalog,modelCatalog,catalogLoading,modelLoading,catalogError,modelError,authRequired,onRefresh,loginHref,traceHref,actionsHref,reportsHref}){
  const [query,setQuery]=useState('');
  const models=Array.isArray(modelCatalog?.models)?modelCatalog.models:[];
  const agents=Array.isArray(catalog?.agents)?catalog.agents:[];
  const matching=models.filter(model=>[model.id,model.model,model.provider].map(value=>agentConfigText(value,'')).join(' ').toLowerCase().includes(query.trim().toLowerCase()));
  const order=agentFallbackOrder(modelCatalog?.fallbackModels),version=agentConfigNumber(modelCatalog?.configVersion);
  return <div className="agent-service-overview">
    <header className="agent-service-heading"><h3><Cpu size={18} aria-hidden="true"/>模型与能力</h3><button type="button" disabled={catalogLoading || modelLoading} onClick={onRefresh}><RefreshCw size={14} aria-hidden="true"/>重新读取配置</button></header>
    <p className="agent-service-note">这里展示当前服务配置。会话模型在输入区选择，实际调用和备用切换请查看执行记录。</p>
    <section className="agent-service-config" aria-label="模型目录与备用设置" aria-busy={modelLoading}>
      <h4><KeyRound size={16} aria-hidden="true"/>服务模型配置</h4>
      {modelLoading && <p className="agent-service-note" role="status">{modelCatalog?'正在重新读取，下方为上次目录快照':'正在读取模型目录与备用设置'}</p>}
      {modelError && <p className="agent-service-error" role="alert">{modelError}{modelCatalog?'；下方保留上次读取的配置，请重新核对。':''}</p>}
      {modelCatalog ? <>
        <dl className="agent-service-facts"><div><dt>服务默认候选</dt><dd>{agentConfigText(modelCatalog.selectedModel)}</dd></div><div><dt>配置版本</dt><dd>{version===null?'未记录':version}</dd></div><div><dt>自动备用</dt><dd>{agentConfigFlag(modelCatalog.fallbackEnabled)}</dd></div><div><dt>备用首段响应阈值</dt><dd>{agentConfigDuration(modelCatalog.firstTokenTimeoutMs)}</dd></div></dl>
        <p className="agent-service-note">阈值是备用配置，不是已测延迟。凭证配置和熔断状态不证明当前连通性或余额。</p>
        {modelCatalog.fallbackEnabled===true && <section className="agent-service-fallback" aria-label="已登记备用顺序"><h5>已登记备用顺序</h5>{order?.length?<ol>{order.map(id=><li key={id}>{id}</li>)}</ol>:<p className="agent-service-note">{order===null?'备用顺序未完整读取':'本次目录未返回备用候选，请到模型配置核对'}</p>}</section>}
        <label className="agent-model-search" htmlFor="agent-service-model-search">查找本次目录中的模型<span><Search size={14} aria-hidden="true"/><input id="agent-service-model-search" value={query} placeholder="模型、接入名称或编号" onChange={event=>setQuery(event.target.value)} onKeyDown={event=>{if(event.key==='Escape' && query){event.preventDefault();event.stopPropagation();setQuery('');}}}/>{query && <button type="button" aria-label="清除模型搜索" onClick={()=>setQuery('')}><X size={14} aria-hidden="true"/></button>}</span></label>
        <p className="agent-service-count">本次目录 {models.length} 项{query.trim()?'，匹配 '+matching.length+' 项':''}</p>
        <ul className="agent-model-records">{matching.map(model=>{const circuit=agentModelCircuit(model);return <li key={model.id}><div className="agent-model-record-heading"><span className="agent-model-symbol"><Cpu size={17} aria-hidden="true"/></span><div><strong>{agentConfigText(model.model,'模型名未记录')}</strong><small>{agentConfigText(model.provider,'接入未记录')}</small></div>{model.selected===true && <span className="agent-service-label" data-tone="primary">服务默认</span>}</div><div className="agent-model-flags"><span className="agent-service-label" data-tone="info">{model.configured===true?'已配置':model.configured===false?'未配置':'配置状态未记录'}</span><span className="agent-service-label" data-tone={circuit.tone}>{circuit.label}</span></div>{circuit.note && <p className="agent-service-note">{circuit.note}</p>}<details className="agent-model-source"><summary>模型登记详情</summary><dl><dt>模型编号</dt><dd>{model.id}</dd><dt>协议</dt><dd>{agentConfigText(model.protocol)}</dd></dl></details></li>})}</ul>
        {!matching.length && <p className="agent-service-empty"><Search size={17} aria-hidden="true"/>{query.trim()?'本次目录中没有匹配项，可清除搜索再查看。':'本次目录没有返回模型条目。'}</p>}
      </> : !modelLoading && !modelError && <p className="agent-service-note">模型目录尚未读取</p>}
    </section>
    <section className="agent-service-config" aria-label="当前账号能力目录" aria-busy={catalogLoading}>
      <h4><Workflow size={16} aria-hidden="true"/>当前账号的登记能力</h4>
      {catalogLoading && <p className="agent-service-note" role="status">正在读取当前账号能力目录</p>}
      {catalogError && <p className="agent-service-error" role="alert">{catalogError}</p>}
      {catalog ? <><div className="agent-service-mode"><StatusBadge domain="agentMode" code={catalog.mode}/><span>本次目录 {agents.length} 项</span></div><ul className="agent-capability-records">{agents.map(agent=><li key={agent.id}><strong>{agentCapabilityLabel(agent)}</strong><p>{agentConfigText(agent.description,'能力说明未记录')}</p></li>)}</ul>{catalog.mode==='CONFIRMABLE' && <p className="agent-service-note">操作提议保存后仍需单独确认。<a href={actionsHref}>查看操作确认</a></p>}{catalog.reportsEnabled===true && <p className="agent-service-note">可查询授权报告{catalog.reportDraftsEnabled===true?'并保存本人草稿':''}，提交与审批在<a href={reportsHref}>报告与审批</a>进行。</p>}<p className="agent-service-note">能力目录不代替账号权限、业务条件或人工确认，私人草稿尚未提交或审批。</p></> : !catalogLoading && !catalogError && <p className="agent-service-note">能力目录尚未读取</p>}
    </section>
    {authRequired && <p className="agent-service-error" role="alert"><TriangleAlert size={14} aria-hidden="true"/>当前目录需要重新验证账号。<a href={loginHref}>前往登录</a></p>}
    <a className="agent-service-trace" href={traceHref}>查看实际执行模型与路由</a>
  </div>;
}
