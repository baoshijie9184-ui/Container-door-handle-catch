import React,{useEffect,useMemo,useRef,useState} from 'react';
import {Modal} from 'antd';
import {useReducedMotion,usePreviewEscape} from './useReducedMotion';
import {AgentWorkbenchClient,availableWorkbenchTabs,workbenchStatus,workbenchRows,tokenDisplay} from '../../frontend/src/utils/agentWorkbench';
import {readFilePreview,boundedTextPreview} from '../../frontend/src/utils/chatFileReferences';
import '../../frontend/src/assets/agent-workbench.css';
import '../../frontend/src/assets/chat-file-references.css';

export function AgentWorkbenchPanel({sessionId,base='',messages=[],onFork,onReference}){
 const reducedMotion=useReducedMotion();
 const pdfNavigation=useRef(null);
 const [state,setState]=useState({enabled:false,items:[],files:[],capabilities:{}}),[tab,setTab]=useState('PLAN'),[busy,setBusy]=useState(false),[error,setError]=useState(''),[drafts,setDrafts]=useState({}),[preview,setPreview]=useState(null),[previewError,setPreviewError]=useState('');
 const client=useMemo(()=>new AgentWorkbenchClient({base,onState:setState}),[base]);const previewUrl=useRef(''),previewVersion=useRef(0);
 const [businessKind,setBusinessKind]=useState('DETECTION'),[businessId,setBusinessId]=useState('');
 const closePreview=()=>{previewVersion.current++;setPreview(null);if(previewUrl.current)URL.revokeObjectURL(previewUrl.current);previewUrl.current=''};
 usePreviewEscape(!!preview,closePreview,'workbench-file-preview-modal');
 useEffect(()=>{if(preview?.type==='pdf')pdfNavigation.current?.focus()},[preview?.type,preview?.page,busy]);
 useEffect(()=>{setError('');setPreview(null);setDrafts({});client.open(sessionId);return()=>client.close()},[client,sessionId]);
 useEffect(()=>()=>{if(previewUrl.current)URL.revokeObjectURL(previewUrl.current)},[]);
 async function run(action){setBusy(true);setError('');try{return await action()}catch(cause){setError(cause.message);if([403,404].includes(cause.status)){previewVersion.current++;setPreview(null);if(previewUrl.current)URL.revokeObjectURL(previewUrl.current)}}finally{setBusy(false)}}
 const act=(item,action,input={})=>run(()=>client.command(item,action,input));
 function draft(id,value){setDrafts(current=>({...current,[id]:value}))}
 async function show(file,download=false,page=1){const version=++previewVersion.current;await run(async()=>{const generation=client.generation;if(download){const blob=await client.content(file),href=URL.createObjectURL(blob),link=document.createElement('a');link.href=href;link.download=file.name;link.click();setTimeout(()=>URL.revokeObjectURL(href),1000);return}const value=await readFilePreview(sessionId,file,{base:client.base,fetcher:client.fetcher,limit:client.value.limits?.previewBytes,page});if(generation!==client.generation||version!==previewVersion.current)return;if(previewUrl.current)URL.revokeObjectURL(previewUrl.current);previewUrl.current=value.kind==='text'?'':URL.createObjectURL(value.kind==='pdf'?value.blob:new Blob([value.blob],{type:file.contentType}));setPreviewError('');setPreview({...value,type:value.kind,file,name:file.name,url:previewUrl.current})})}
 async function showBusiness(file){await run(async()=>{const generation=client.generation;const value=file.contentType.startsWith('image/')?{type:'image',url:client.base+file.previewPath}:{type:'text',text:await boundedTextPreview(await (await client.read(file.previewPath)).blob(),client.value.limits?.previewBytes)};if(generation===client.generation){setPreviewError('');setPreview({...value,name:file.name})}})}
 if(!state.enabled)return null;
 const rows=workbenchRows(state.items,tab);
 return <section className="agent-workbench" aria-label="Agent 持久工作台">
  <header><strong>任务工作台</strong><button type="button" disabled={busy} onClick={()=>client.poll()}>刷新</button></header>
  <div role="status" aria-live="polite" aria-label="后台任务通知">{(state.notifications||[]).map(notice=><p key={notice.id} className="wb-note">{notice.text}</p>)}</div>
  <nav aria-label="工作台视图">{availableWorkbenchTabs(state.capabilities).map(([key,label])=><button key={key} type="button" className={tab===key?'active':''} aria-pressed={tab===key} onClick={()=>setTab(key)}>{label}</button>)}</nav>
  {(error||state.error)&&<p role="alert" className="wb-error">{error||state.error}</p>}
  {tab==='RECOVERY'&&<p className="wb-note">仅可恢复启用后保存了 SDK 检查点的任务；旧版历史记录不可续跑</p>}
  {tab==='FILE'?<>
   <label className="wb-upload">上传资料<input type="file" accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.md,.csv,.json,.html,.svg" disabled={busy} onChange={event=>{const file=event.target.files?.[0];if(file)run(()=>client.upload(file));event.target.value=''}}/></label><p className="wb-note">本人文件 · 每文件最多 {Math.ceil((state.limits?.maxFileBytes||26214400)/1048576)} MB · HTML/SVG 仅查看源码</p>
   <div className="wb-business-form"><select aria-label="业务文件类型" value={businessKind} onChange={event=>setBusinessKind(event.target.value)}><option value="DETECTION">检测任务</option><option value="REPORT">质检报告</option></select><input aria-label="业务对象编号" placeholder="任务或报告编号" maxLength={128} value={businessId} onChange={event=>setBusinessId(event.target.value)}/><button disabled={busy||!businessId.trim()} onClick={()=>run(()=>client.attachBusiness(businessKind,businessId.trim()))}>关联业务文件</button></div>
   {(state.businessFiles||[]).map(file=><article key={file.kind+file.resourceId+file.fileId}><strong>业务引用 / {file.name}</strong><small>{file.resourceId} · 每次读取重新鉴权</small><button onClick={()=>showBusiness(file)}>预览业务文件</button></article>)}
   {['uploads','artifacts'].map(folder=><details key={folder} open className="wb-file-tree"><summary>{folder==='uploads'?'上传资料':'生成产物'}（{state.files.filter(file=>file.folder===folder).length}）</summary>{state.files.filter(file=>file.folder===folder).map(file=><article key={file.id}><strong>{file.name}</strong><small>{Math.ceil(file.bytes/1024)} KB</small><div className="wb-actions"><button onClick={()=>show(file)}>预览</button><button onClick={()=>show(file,true)}>下载</button><button onClick={()=>onReference?.('@file:'+file.id)}>引用</button><button onClick={()=>run(()=>navigator.clipboard.writeText('@file:'+file.id))}>复制引用</button><button disabled={busy} onClick={()=>run(()=>client.remove(file))}>移除</button></div></article>)}</details>)}
  </>:tab==='FORK'?<>
   <p className="wb-note">选择已完成回复创建独立分支，审批与排队消息不继承</p>
   {state.lineage&&<button onClick={()=>onFork?.(state.lineage.sourceSessionId)}>返回来源会话</button>}
   {messages.filter(item=>item.role==='assistant'&&(item.id||item.key)).slice(-20).map(item=><article key={item.id||item.key}><p>{(item.text||item.content||'').slice(0,120)}</p><button disabled={busy} onClick={async()=>{const result=await run(()=>client.fork(item.id||item.key));if(result)onFork?.(result.sessionId)}}>从此处创建分支</button></article>)}
  </>:<>
   {rows.map(item=><article key={item.id}>
    <header><strong>{item.data.title||item.data.specialist||item.kind}</strong><span>{workbenchStatus[item.status]||item.status}</span></header>
    {typeof item.data.runId==='string'&&/^[a-f0-9-]{36}$/.test(item.data.runId)&&<a href={base+'/#/agent/trace?runId='+encodeURIComponent(item.data.runId)}>查看本次执行轨迹</a>}
    {['/detection','/agent/mcp'].includes(item.data.managementPath)&&<a href={base+'/#'+item.data.managementPath}>打开原任务页面</a>}
    {item.data.text&&<pre>{item.data.text}</pre>}
    {item.kind==='EXECUTION'&&item.data.result&&<p>{item.data.result}</p>}
    {item.kind==='EXECUTION'&&['RUNNING','QUEUED','READY','WAITING_PLAN','WAITING_INPUT','WAITING_CHILD'].includes(item.status)&&<button disabled={busy} onClick={()=>Modal.confirm({title:'取消任务',content:'取消本任务及其活动子任务，已完成的操作不会回滚。排队消息仍按原设置处理。',okText:'确认取消',cancelText:'继续执行',onOk:()=>act(item,'cancel')})}>取消任务</button>}
    {Array.isArray(item.data.tasks)&&<ol>{item.data.tasks.map((task,index)=><li key={index}><span>{task.status}</span> {task.title}{task.evidenceCallId&&<small>证据 {task.evidenceCallId}</small>}</li>)}</ol>}
    {item.kind==='PLAN'&&item.status==='PENDING'&&<><textarea value={drafts[item.id]||''} onChange={event=>draft(item.id,event.target.value)} placeholder="修改意见（要求修订时填写）" aria-label="计划修改意见"/><div className="wb-actions"><button disabled={busy} onClick={()=>act(item,'approve-plan')}>批准计划</button><button disabled={busy||!drafts[item.id]?.trim()} onClick={()=>act(item,'revise-plan',{feedback:drafts[item.id]})}>要求修订</button><button disabled={busy} onClick={()=>act(item,'cancel')}>取消计划</button></div><p className="wb-note">计划批准不代替业务审批</p></>}
    {item.kind==='QUESTION'&&item.status==='PENDING'&&<>
     {item.data.questionType==='TEXT'?<textarea value={drafts[item.id]||''} onChange={event=>draft(item.id,event.target.value)} aria-label="问题回答"/>:item.data.questionType==='SINGLE'?<select value={drafts[item.id]||''} onChange={event=>draft(item.id,event.target.value)} aria-label="选择回答"><option disabled value="">请选择</option>{item.data.options.map(option=><option key={option} value={option}>{option}</option>)}</select>:item.data.options.map(option=><label key={option} className="wb-option"><input type="checkbox" checked={(drafts[item.id]||[]).includes(option)} onChange={event=>draft(item.id,event.target.checked?[...(drafts[item.id]||[]),option]:(drafts[item.id]||[]).filter(value=>value!==option))}/>{option}</label>)}
     <div className="wb-actions"><button disabled={busy} onClick={()=>act(item,'answer',{answer:drafts[item.id]})}>提交回答</button><button disabled={busy} onClick={()=>act(item,'cancel')}>取消问题</button></div>
    </>}
    {item.kind==='CHILD'&&<>{item.data.result&&<p>{item.data.result}</p>}{['COMPLETED','RUNNING','QUEUED'].includes(item.status)&&<><textarea aria-label="子 Agent 补充要求" value={drafts[item.id]||''} onChange={event=>draft(item.id,event.target.value)}/><button disabled={busy||!drafts[item.id]?.trim()} onClick={()=>act(item,'child-message',{content:drafts[item.id]})}>追加专业要求</button>{item.status!=='COMPLETED'&&<small>追加要求在当前执行结束后继续处理</small>}</>}{['QUEUED','RUNNING','WAITING_INPUT','WAITING_PLAN','NEEDS_REVIEW'].includes(item.status)&&<button disabled={busy} onClick={()=>act(item,'cancel')}>取消子任务</button>}</>}
    {item.kind==='USAGE'&&<dl><dt>模型 / 用途</dt><dd>{item.data.modelId||'未知模型'} · {item.data.purpose==='SESSION_TOTAL'?'全部执行':item.data.purpose==='CONTEXT_COMPACTION'?'上下文摘要':'Agent 推理'}</dd><dt>输入 / 输出 Token</dt><dd>{tokenDisplay(item.data.inputTokens)} / {tokenDisplay(item.data.outputTokens)}</dd><dt>数据依据</dt><dd>{item.data.basis==='PROVIDER_REPORTED'?'供应商报告':'供应商用量未知'}</dd><dt>模型 / 首响应耗时</dt><dd>{tokenDisplay(item.data.durationMs)} / {tokenDisplay(item.data.firstContentMs)} ms</dd><dt>系统 / 工具 / 历史估算（非账单）</dt><dd>{tokenDisplay(item.data.systemTokens)} / {tokenDisplay(item.data.toolsTokens)} / {tokenDisplay(item.data.messageTokens)}</dd></dl>}
    {item.kind==='CONTEXT'&&<dl><dt>上下文压缩</dt><dd>{item.data.phase}</dd><dt>压缩前 / 后字符数</dt><dd>{tokenDisplay(item.data.beforeChars)} / {tokenDisplay(item.data.afterChars)}</dd></dl>}
    {item.kind==='TOOL_TIMING'&&<p>工具批次耗时 {tokenDisplay(item.data.durationMs)} ms</p>}
    {item.status==='NEEDS_REVIEW'&&<><p className="wb-note">恢复会重新鉴权，未知写结果不会自动重做</p><button disabled={busy} onClick={()=>act(item,'resume')}>确认从检查点恢复</button><button disabled={busy} onClick={()=>act(item,'cancel')}>结束任务</button></>}
   </article>)}
   {!rows.length&&<p className="wb-note">当前视图暂无记录</p>}
  </>}
  <Modal rootClassName="workbench-file-preview-modal" transitionName={reducedMotion?'':'ant-zoom'} maskTransitionName={reducedMotion?'':'ant-fade'} open={!!preview} title={preview?.name||'文件预览'} onCancel={closePreview} footer={null} width="min(900px,90vw)">{previewError&&<p role="alert">{previewError}</p>}{preview?.type==='pdf'&&<nav ref={pdfNavigation} tabIndex={-1} className="chat-file-pages" aria-label="PDF 页码"><button disabled={busy||preview.page===1} onClick={()=>show(preview.file,false,preview.page-1)}>上一页</button><span>第 {preview.page} / {preview.pages} 页</span><button disabled={busy||preview.page===preview.pages} onClick={()=>show(preview.file,false,preview.page+1)}>下一页</button><small>页面预览 · Agent 仅可读取文字层</small></nav>}{['image','pdf'].includes(preview?.type)?<img src={preview.url} alt="本人工作区页面预览" className="wb-preview-image" onError={()=>setPreviewError('图片预览失败，请下载原文件核对')}/>:<pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{preview?.text}</pre>}</Modal>
 </section>
}
