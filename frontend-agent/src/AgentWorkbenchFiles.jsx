import React,{useMemo,useState} from 'react';
import {Files,Upload,FileCheck,FileText,Image,ChartNoAxesCombined,Network,Search,Download,Plus,Copy,Trash2,TriangleAlert,ChevronRight} from 'lucide-react';
import {composerAttachment} from '../../frontend/src/utils/composerPresentation';
import {workbenchFileGroups,workbenchFileMatches,workbenchFileSummary} from '../../frontend/src/utils/workbenchPresentation';
const icons={Files,Upload,DocumentChecked:FileCheck,Document:FileText,Picture:Image,DataAnalysis:ChartNoAxesCombined};
function FileIcon({name}){const Icon=icons[name]||FileText;return <Icon size={19} aria-hidden="true"/>}
export default function AgentWorkbenchFiles({files=[],businessFiles=[],known=false,loading=false,error='',busy=false,onPreview,onDownload,onReference,onCopy,onRemove,onPreviewBusiness}){
 const [query,setQuery]=useState('');
 const groups=useMemo(()=>workbenchFileGroups(files,query).filter(group=>group.files.length),[files,query]);
 const businessRows=useMemo(()=>businessFiles.filter(file=>workbenchFileMatches(file,query)),[businessFiles,query]);
 const summary=workbenchFileSummary(files);
 return <section className="wb-files" aria-label="当前会话资料" aria-busy={loading}>
  {known?<>
   <div className="wb-file-overview"><Files size={18} aria-hidden="true"/><div><strong>{summary.count} 个私有文件</strong><span>已关联大小 {summary.size}，非账号总用量</span></div></div>
   {error&&<p className="wb-note">读取未完成，以下保留上次已读取的资料，请刷新核对。</p>}
   {busy&&<p className="wb-file-operation" role="status"><Network size={15} aria-hidden="true"/>工作台操作处理中，文件操作暂不可用。</p>}
   {(files.length>0||businessFiles.length>0||query)&&<div className="wb-file-search"><label>查找会话资料<input type="search" maxLength={200} placeholder="文件名或编号" value={query} onChange={event=>setQuery(event.target.value)}/></label>{query&&<button type="button" onClick={()=>setQuery('')}>清空</button>}</div>}
   {businessRows.length>0&&<section className="wb-business-references" aria-label="业务资料引用"><h4><Network size={16} aria-hidden="true"/>业务资料引用 <small>{businessRows.length}</small></h4><p className="wb-note">使用现有业务权限读取，不计入上方私有文件大小。</p>{businessRows.map(file=><article key={file.kind+file.resourceId+file.fileId} className="wb-file-row" aria-label={'业务资料 '+(file.name||file.resourceId)}><div className="wb-file-heading"><span className="wb-file-icon">{file.kind==='REPORT'?<FileCheck size={19} aria-hidden="true"/>:<Image size={19} aria-hidden="true"/>}</span><div><strong>{file.name||'未记录文件名'}</strong><small>{file.kind==='REPORT'?'质检报告':'检测资料'} · {file.resourceId}</small></div></div><div className="wb-actions"><button type="button" disabled={busy} onClick={()=>onPreviewBusiness(file)}><Search size={14} aria-hidden="true"/>预览业务文件</button></div></article>)}</section>}
   {groups.map(folder=><details key={folder.key} open className="wb-file-tree">
    <summary><FileIcon name={folder.icon}/><span>{folder.label}</span><small>{folder.files.length}</small><ChevronRight size={12} className="wb-folder-chevron" aria-hidden="true"/></summary>
    <p className="wb-note">{folder.note}</p>
    {folder.files.map(file=><article key={file.id} className="wb-file-row" aria-label={'私有文件 '+(file.name||file.id)}>
     <div className="wb-file-heading"><span className="wb-file-icon"><FileIcon name={composerAttachment(file).icon}/></span><div><strong>{file.name||'未记录文件名'}</strong><small>{composerAttachment(file).type} · {composerAttachment(file).size}</small></div></div>
     <div className="wb-actions"><button type="button" disabled={busy} onClick={()=>onPreview(file)}><Search size={14} aria-hidden="true"/>预览</button><button type="button" disabled={busy} onClick={()=>onDownload(file)}><Download size={14} aria-hidden="true"/>下载</button>{!folder.readOnly&&<button type="button" disabled={busy} onClick={()=>onReference(file)}><Plus size={14} aria-hidden="true"/>引用</button>}</div>
     <details className="wb-file-more"><summary aria-label={(file.name||'文件')+'的编号与更多操作'}>更多</summary><p className="wb-file-id">文件编号 {file.id}</p>{!folder.readOnly&&<div className="wb-actions"><button type="button" disabled={busy} onClick={()=>onCopy(file)}><Copy size={14} aria-hidden="true"/>复制引用</button><button type="button" className="wb-button-danger" disabled={busy} onClick={()=>onRemove(file)}><Trash2 size={14} aria-hidden="true"/>移出会话</button></div>}</details>
    </article>)}
   </details>)}
   {!groups.length&&!businessRows.length&&<div className="wb-empty">{query.trim()?<Search size={24} aria-hidden="true"/>:<Files size={24} aria-hidden="true"/>}<strong>{query.trim()?'没有匹配的资料':'当前会话尚无资料'}</strong><p>{query.trim()?'可调整文件名或编号，或清空搜索。':'可以上传本人资料，或关联有权读取的检测任务与报告。'}</p>{query.trim()&&<button type="button" onClick={()=>setQuery('')}>清空搜索</button>}</div>}
  </>:<div className="wb-empty">{error?<TriangleAlert size={24} aria-hidden="true"/>:<Files size={24} aria-hidden="true"/>}<strong>{error?'资料暂不可读取':'正在读取会话资料'}</strong><p>{error?'请刷新核对，不根据空列表推断文件已删除。':'读取完成后显示已关联的文件与业务资料。'}</p></div>}
 </section>
}
