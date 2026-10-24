import React,{useEffect,useMemo,useRef,useState} from 'react';
import {Modal,Button} from 'antd';
import {useReducedMotion,usePreviewEscape} from './useReducedMotion';
import {AgentWorkbenchClient,availableWorkbenchTabs,workbenchStatus,workbenchRows,tokenDisplay,recoveryInput} from '../../frontend/src/utils/agentWorkbench';
import {readFilePreview,boundedTextPreview} from '../../frontend/src/utils/chatFileReferences';
import '../../frontend/src/assets/agent-workbench.css';
import StatusBadge from './StatusBadge';
import AgentWorkbenchFiles from './AgentWorkbenchFiles';
import AgentUsageSummary from './AgentUsageSummary';
import AgentContextSummary from './AgentContextSummary';
import AgentForkPanel from './AgentForkPanel';
import AgentChildTask from './AgentChildTask';
import AgentTaskChecklist from './AgentTaskChecklist';
import AgentRecoveryPanel from './AgentRecoveryPanel';
import {recoveryReviewError} from '../../frontend/src/utils/recoveryPresentation';
import {contextStatusCode} from '../../frontend/src/utils/contextPresentation';
import WorkbenchInteraction from './WorkbenchInteraction';
import {composerAttachment} from '../../frontend/src/utils/composerPresentation';
import {FileText,FileCheck,Files,ListChecks,MessageSquare,Network,Activity,ChartNoAxesCombined,Clock,Copy,RefreshCw,Upload,Download,Image,TriangleAlert} from 'lucide-react';
import {workbenchKind,workbenchTabIcon,workbenchInteractionStatus,workbenchTitle,workbenchEmpty,workbenchTime,workbenchAnswer} from '../../frontend/src/utils/workbenchPresentation';
import '../../frontend/src/assets/chat-file-references.css';

const workbenchIcons={Document:FileText,DocumentChecked:FileCheck,Files,Tickets:ListChecks,ChatDotRound:MessageSquare,Connection:Network,Operation:Activity,DataAnalysis:ChartNoAxesCombined,Picture:Image,Clock,DocumentCopy:Copy,Refresh:RefreshCw,Upload,Warning:TriangleAlert};
function WorkbenchIcon({name,size=18}){const Icon=workbenchIcons[name]||FileText;return <Icon size={size} aria-hidden="true"/>}

export function AgentWorkbenchPanel({sessionId,base='',messages=[],onFork,onReference}){
 const reducedMotion=useReducedMotion();
 const pdfNavigation=useRef(null),pdfFocusPending=useRef(false);
 const [state,setState]=useState({enabled:false,items:[],files:[],capabilities:{}}),[tab,setTab]=useState('PLAN'),[busy,setBusy]=useState(false),[error,setError]=useState(''),[drafts,setDrafts]=useState({}),[preview,setPreview]=useState(null),[previewError,setPreviewError]=useState('');
 const client=useMemo(()=>new AgentWorkbenchClient({base,onState:setState}),[base]);const previewUrl=useRef(''),previewVersion=useRef(0),operationVersion=useRef(0),operationBusy=useRef(false);
 const [businessKind,setBusinessKind]=useState('DETECTION'),[businessId,setBusinessId]=useState('');
 const [recoveryChoices,setRecoveryChoices]=useState({});
 const recoveryChoicesRef=useRef({});
 function updateRecoveryChoice(id,value){recoveryChoicesRef.current={...recoveryChoicesRef.current,[id]:value};setRecoveryChoices(recoveryChoicesRef.current)}
 const workbenchTabs=useRef(null),workbenchViewFocus=useRef(null);
 function openWorkbenchView(view){if(!availableWorkbenchTabs(client.value.capabilities).some(([key])=>key===view))return;if(tab===view){workbenchTabs.current?.querySelector('[aria-pressed="true"]')?.focus({preventScroll:true});return}workbenchViewFocus.current={sessionId,generation:client.generation,view};setTab(view)}
 function openContextFiles(){openWorkbenchView('FILE')}
 useEffect(()=>{const pending=workbenchViewFocus.current;if(!pending)return;workbenchViewFocus.current=null;if(tab===pending.view && pending.sessionId===sessionId && pending.generation===client.generation)workbenchTabs.current?.querySelector('[aria-pressed="true"]')?.focus({preventScroll:true})},[tab,sessionId,client]);
 const closePreview=()=>{previewVersion.current++;pdfFocusPending.current=false;setPreview(null);if(previewUrl.current)URL.revokeObjectURL(previewUrl.current);previewUrl.current=''};
 usePreviewEscape(!!preview,closePreview,'workbench-file-preview-modal');
 useEffect(()=>{if(preview?.type==='pdf'&&!busy&&pdfFocusPending.current){pdfFocusPending.current=false;pdfNavigation.current?.focus()}},[preview?.type,preview?.page,busy]);
 useEffect(()=>{operationVersion.current++;operationBusy.current=false;setBusy(false);setError('');closePreview();setDrafts({});recoveryChoicesRef.current={};setRecoveryChoices({});setBusinessId('');client.open(sessionId);return()=>{operationVersion.current++;operationBusy.current=false;client.close()}},[client,sessionId]);
 useEffect(()=>()=>{if(previewUrl.current)URL.revokeObjectURL(previewUrl.current)},[]);
 async function run(action,previewing=false){if(operationBusy.current)return;const generation=client.generation,operation=++operationVersion.current;operationBusy.current=true;setBusy(true);setError('');try{const result=await action();return generation===client.generation&&operation===operationVersion.current?result:undefined}catch(cause){if(generation===client.generation&&operation===operationVersion.current){const message=cause.message||'操作结果尚未核对，请刷新资料';setError(message);if(previewing)setPreviewError(message);if([403,404].includes(cause.status))closePreview()}}finally{if(operation===operationVersion.current){operationBusy.current=false;setBusy(false)}}}
 function confirmWorkbench(options){return Modal.confirm({transitionName:reducedMotion?'':'ant-zoom',maskTransitionName:reducedMotion?'':'ant-fade',...options})}
 const act=(item,action,input={})=>run(()=>client.command(item,action,input));
 const recoveryPayload=item=>recoveryInput(item.kind==='EXECUTION'?(recoveryChoicesRef.current[item.id]||'KEEP'):'KEEP',client.value);
 function resume(item){
  if(operationBusy.current)return;
  try{
   const input=recoveryPayload(item),generation=client.generation;
   const submit=()=>{if(generation!==client.generation || operationBusy.current)return;const error=recoveryReviewError(item,client.value,recoveryChoicesRef.current[item.id]||'KEEP',input);if(error){setError(error);return}return act(item,'resume',input)};
   if(Object.hasOwn(input,'replacementModelId'))confirmWorkbench({title:'确认恢复模型',content:`将任务及未结束的专业任务改用 V${input.replacementConfigVersion} 的 ${input.replacementModelId||client.value.recoveryDefault}。已完成工具结果仍保留，未知写结果不会重新执行。`,okText:'确认更换并恢复',cancelText:'保留现状',onOk:submit});else submit();
  }catch(cause){setError(cause.message)}
 }
 function draft(id,value){setDrafts(current=>({...current,[id]:value}))}
 function removeFile(file){const generation=client.generation;confirmWorkbench({title:'移出会话资料',content:`从当前会话移出“${file.name}”？此操作解除本会话的文件引用，不代表后端文件已物理删除或账号配额已释放。`,okText:'移出当前会话',cancelText:'保留资料',okButtonProps:{danger:true},onOk:()=>{if(generation!==client.generation)return;const current=client.value.files.find(row=>row.id===file.id);if(!current){setError('资料列表已变化，请刷新后核对');return}return run(()=>client.remove(current))}})}
 function cancelTask(item){
  if(operationBusy.current)return;
  const generation=client.generation,interrupted=item.status==='NEEDS_REVIEW';
  confirmWorkbench({title:interrupted?'结束此任务':'取消任务',content:`取消任务 ${item.id}（V${item.revision}）及其活动子任务？已完成操作不会回滚，排队消息仍按原设置处理。`,okText:interrupted?'确认结束':'确认取消',cancelText:interrupted?'保留当前状态':'继续执行',okButtonProps:{danger:true},onOk:()=>{if(generation!==client.generation || operationBusy.current)return;const current=client.value.items.find(row=>row.id===item.id);if(!current || current.kind!=='EXECUTION' || current.revision!==item.revision){setError('任务记录已变化，请重新核对后再确认取消');return}return act(item,'cancel')}});
 }
 function cancelChild(item){if(operationBusy.current)return;const generation=client.generation;confirmWorkbench({title:'取消此专业任务',content:`取消所选专业任务 ${item.id}（V${item.revision}）？已完成的业务操作不会回滚，主任务和其他专业任务状态需分别核对。`,okText:'确认取消此任务',cancelText:'保留当前状态',okButtonProps:{danger:true},onOk:()=>{if(generation!==client.generation || operationBusy.current)return;const current=client.value.items.find(row=>row.id===item.id);if(!current || current.kind!=='CHILD' || current.revision!==item.revision){setError('子任务记录已变化，请重新核对后再确认取消');return}return act(item,'cancel')}})}
 async function show(file,download=false,page=1){if(operationBusy.current)return;const version=download?previewVersion.current:++previewVersion.current;if(!download&&preview?.type==='pdf')pdfFocusPending.current=true;await run(async()=>{const generation=client.generation;if(download){const blob=await client.content(file);if(generation!==client.generation)return;const href=URL.createObjectURL(blob),link=document.createElement('a');link.href=href;link.download=file.name;link.click();setTimeout(()=>URL.revokeObjectURL(href),1000);return}const value=await readFilePreview(sessionId,file,{base:client.base,fetcher:client.fetcher,limit:client.value.limits?.previewBytes,page});if(generation!==client.generation||version!==previewVersion.current)return;if(previewUrl.current)URL.revokeObjectURL(previewUrl.current);previewUrl.current=value.kind==='text'?'':URL.createObjectURL(value.kind==='pdf'?value.blob:new Blob([value.blob],{type:file.contentType}));pdfFocusPending.current=value.kind==='pdf';setPreviewError('');setPreview({...value,type:value.kind,file,name:file.name,url:previewUrl.current})},!download)}
 async function showBusiness(file){if(operationBusy.current)return;pdfFocusPending.current=false;const version=++previewVersion.current;await run(async()=>{const generation=client.generation;const value=['image/png','image/jpeg','image/webp'].includes(file.contentType)?{type:'image',url:client.base+file.previewPath}:{type:'text',text:await boundedTextPreview(await (await client.read(file.previewPath)).blob(),client.value.limits?.previewBytes)};if(generation===client.generation&&version===previewVersion.current){setPreviewError('');setPreview({...value,file,name:file.name})}},true)}
 if(!state.enabled||state.sessionId!==sessionId)return null;
 const rows=workbenchRows(state.items,tab);
 return <section className="agent-workbench" aria-label="Agent 持久工作台">
  <header><strong>任务工作台</strong><button type="button" disabled={busy} onClick={()=>client.poll()}><RefreshCw size={14} aria-hidden="true"/>刷新</button></header>
  <div role="status" aria-live="polite" aria-label="后台任务通知">{(state.notifications||[]).map(notice=><p key={notice.id} className="wb-note">{notice.text}</p>)}</div>
  <nav ref={workbenchTabs} aria-label="工作台视图">{availableWorkbenchTabs(state.capabilities).map(([key,label])=><button key={key} type="button" className={tab===key?'active':''} aria-pressed={tab===key} onClick={()=>setTab(key)}><WorkbenchIcon name={workbenchTabIcon(key)} size={14}/>{label}</button>)}</nav>
  {(error||state.error)&&<p role="alert" className="wb-error">{error||state.error}</p>}
  {tab==='RECOVERY'&&<p className="wb-note">仅能恢复已保存检查点的任务；未保存检查点的历史任务只能追溯，无法续跑。</p>}
  {tab==='FILE'?<>
   <label className="wb-upload"><span className="wb-upload-title"><WorkbenchIcon name="Upload"/>上传本人资料</span><input type="file" accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.md,.csv,.json,.html,.svg" disabled={busy||!state.loaded} onChange={event=>{const file=event.target.files?.[0];if(file)run(()=>client.upload(file));event.target.value=''}}/></label><p className="wb-note">单文件上限 {state.loaded?composerAttachment({bytes:state.limits?.maxFileBytes}).size:'尚未核对'} · HTML/SVG 仅查看源码</p>
   <details className="wb-business-link"><summary><Network size={15} aria-hidden="true"/>关联已有业务资料</summary><p className="wb-note">填写有权访问的任务或报告编号，每次读取重新鉴权。</p><form className="wb-business-form" onSubmit={event=>{event.preventDefault();if(!busy&&state.loaded&&businessId.trim())run(()=>client.attachBusiness(businessKind,businessId.trim()))}}><select aria-label="业务文件类型" disabled={busy||!state.loaded} value={businessKind} onChange={event=>setBusinessKind(event.target.value)}><option value="DETECTION">检测任务</option><option value="REPORT">质检报告</option></select><input aria-label="业务对象编号" placeholder="任务或报告编号" maxLength={128} disabled={busy||!state.loaded} value={businessId} onChange={event=>setBusinessId(event.target.value)}/><button type="submit" disabled={busy||!state.loaded||!businessId.trim()}>关联业务文件</button></form></details>
   <AgentWorkbenchFiles key={sessionId} files={state.files} businessFiles={state.businessFiles} known={state.loaded} loading={state.loading} error={state.error} busy={busy} onPreview={file=>show(file)} onDownload={file=>show(file,true)} onReference={file=>onReference?.('@file:'+file.id)} onCopy={file=>run(()=>navigator.clipboard.writeText('@file:'+file.id))} onRemove={removeFile} onPreviewBusiness={showBusiness}/>
  </>:tab==='FORK'?<AgentForkPanel key={sessionId} sessionId={sessionId} messages={messages} lineage={state.lineage} known={state.loaded} loading={state.loading} readError={state.error} busy={busy} onSource={onFork} onFork={async id=>{const result=await run(()=>client.fork(id));if(result)onFork?.(result.sessionId)}}/>:<>
   {rows.map(item=><article key={item.id} data-kind={item.kind}>
    <header><span className="wb-kind-icon"><WorkbenchIcon name={workbenchKind(item.kind).icon}/></span><strong>{workbenchTitle(item)}</strong><StatusBadge domain={item.kind==='CONTEXT'?'contextRecord':item.kind==='TASKS'?'checklistRecord':'task'} code={item.kind==='CONTEXT'?contextStatusCode(item):item.status} label={['CONTEXT','TASKS'].includes(item.kind)?undefined:workbenchInteractionStatus(item)||workbenchStatus[item.status]} /></header>
    <p className="wb-record-meta">{workbenchKind(item.kind).label} · 版本 {item.revision}{workbenchTime(item.updatedAt)&&<span> · 更新于 {workbenchTime(item.updatedAt)} UTC+8</span>}</p>
    {item.kind==='QUESTION'&&<p className="wb-purpose"><MessageSquare size={14} aria-hidden="true"/>补充任务信息，回答不等于业务授权</p>}{item.kind==='PLAN'&&<p className="wb-purpose"><FileCheck size={14} aria-hidden="true"/>审阅执行范围，业务操作仍需单独确认</p>}
    {typeof item.data.runId==='string'&&/^[a-f0-9-]{36}$/.test(item.data.runId)&&<a href={base+'/#/agent/trace?runId='+encodeURIComponent(item.data.runId)}>查看本次执行轨迹</a>}
    {['/detection','/agent/mcp','/agent/actions'].includes(item.data.managementPath)&&<a href={base+'/#'+item.data.managementPath}>打开原任务页面</a>}
    {item.data.text&&item.kind!=='CONTEXT'&&(['PLAN','QUESTION'].includes(item.kind)?<p className="wb-reading-text">{item.data.text}</p>:<pre tabIndex={0} aria-label="工作记录正文">{item.data.text}</pre>)}
    {item.kind==='EXECUTION'&&item.data.result&&<p className="wb-output">{item.data.result}</p>}
    {item.kind==='EXECUTION'&&['RUNNING','QUEUED','READY','WAITING_PLAN','WAITING_INPUT','WAITING_CHILD'].includes(item.status)&&<button disabled={busy} onClick={()=>cancelTask(item)}>取消任务</button>}
    <AgentTaskChecklist tasks={item.data.tasks} traceBase={base}/>
    {item.kind==='QUESTION'&&item.status==='ANSWERED'&&<div className="wb-answer"><strong>已提交的回答</strong><p>{workbenchAnswer(item.data.answer)}</p></div>}
    {item.kind==='PLAN'&&item.data.feedback&&<div className="wb-answer"><strong>修订意见</strong><p>{item.data.feedback}</p></div>}
    {['PLAN','QUESTION'].includes(item.kind)&&item.status==='PENDING'&&<WorkbenchInteraction item={item} value={drafts[item.id]??(item.data.questionType==='MULTIPLE'?[]:'')} busy={busy} onChange={value=>draft(item.id,value)} onCommand={(action,input)=>act(item,action,input)}/>}
    {item.kind==='CHILD'&&<AgentChildTask item={item} value={drafts[item.id]||''} busy={busy} recoveryShown={item.status==='NEEDS_REVIEW'} availableViews={availableWorkbenchTabs(state.capabilities).map(([key])=>key)} onChange={value=>draft(item.id,value)} onCommand={content=>act(item,'child-message',{content})} onCancel={()=>cancelChild(item)} onView={openWorkbenchView}/>}
    {item.kind==='USAGE'&&<AgentUsageSummary data={item.data}/>}
    {item.kind==='CONTEXT'&&<AgentContextSummary item={item} files={state.files} filesEnabled={state.capabilities.files!==false} onOpenFiles={openContextFiles}/>}
    {item.kind==='TOOL_TIMING'&&<p>工具批次耗时 {tokenDisplay(item.data.durationMs)} ms</p>}
    {item.status==='NEEDS_REVIEW'&&<AgentRecoveryPanel item={item} state={state} choice={recoveryChoices[item.id]||'KEEP'} busy={busy} onChoice={value=>updateRecoveryChoice(item.id,value)} onRefresh={()=>client.loadRecoveryModels()} onResume={()=>resume(item)} onEnd={()=>item.kind==='CHILD'?cancelChild(item):cancelTask(item)}/>}
   </article>)}
   {!rows.length&&<div className="wb-empty"><WorkbenchIcon name={workbenchEmpty(tab,state).icon} size={24}/><strong>{workbenchEmpty(tab,state).title}</strong><p>{workbenchEmpty(tab,state).description}</p></div>}
  </>}
  <Modal rootClassName="workbench-file-preview-modal" transitionName={reducedMotion?'':'ant-zoom'} maskTransitionName={reducedMotion?'':'ant-fade'} open={!!preview} title={preview?.name||'文件预览'} onCancel={closePreview} footer={<div className="file-preview-actions"><Button onClick={closePreview}>关闭预览</Button>{preview?.file?.id&&(state.files||[]).some(file=>file.id===preview.file.id)&&<Button type="primary" disabled={busy} icon={<Download size={15} aria-hidden="true"/>} onClick={()=>show(preview.file,true)}>下载原文件</Button>}</div>} width="min(900px,90vw)">
   <p className="file-preview-meta"><WorkbenchIcon name={composerAttachment(preview?.file).icon} size={18}/><span>{composerAttachment(preview?.file).type}</span><span>{composerAttachment(preview?.file).size}</span></p>
   {previewError&&<p className="wb-error" role="alert">{previewError}</p>}{busy&&<p role="status">正在读取文件，请稍候</p>}
   {preview?.type==='pdf'&&<nav ref={pdfNavigation} tabIndex={-1} className="chat-file-pages" aria-label="PDF 页码"><button type="button" disabled={busy||preview.page===1} onClick={()=>show(preview.file,false,preview.page-1)}>上一页</button><span role="status">第 {preview.page} / {preview.pages} 页</span><button type="button" disabled={busy||preview.page===preview.pages} onClick={()=>show(preview.file,false,preview.page+1)}>下一页</button><small>页面预览 · Agent 仅可读取文字层</small></nav>}
   <p className="wb-preview-note">预览不执行文件内容。HTML/SVG 按源码展示，PDF 显示页面图片；下载可保留原文件。</p>
   {['image','pdf'].includes(preview?.type)?<img src={preview.url} alt={(preview.name||'本人资料')+'页面预览'} className="wb-preview-image" onError={()=>setPreviewError('图片预览失败，请下载原文件核对')}/>:<pre className="chat-file-preview-text" tabIndex={0} aria-label="资料文本或源码预览">{preview?.text}</pre>}
  </Modal>
 </section>
}
