import React from 'react';
import { FileText, MessageSquare, Pencil, Move } from 'lucide-react';
import { workbenchInteractionRecords } from '../../frontend/src/utils/workbenchRecordPresentation.js';
import '../../frontend/src/assets/workbench-interaction-record.css';

const icons={Document:FileText,ChatDotRound:MessageSquare,Edit:Pencil};
export default function WorkbenchInteractionRecord({item,part='all'}) {
 const records=workbenchInteractionRecords(item).filter(record=>part==='body'?record.key==='body':part==='response'?record.key!=='body':true);
 if(!records.length)return null;
 return <div className="wb-interaction-record" data-part={part}>{records.map(record=>{
  const Icon=icons[record.icon];
  return <section key={record.key} data-record={record.key}>
   <h4><Icon size={15} aria-hidden="true"/>{record.label}{record.values&&<span>{record.values.length} 项</span>}</h4>
   <div className={'wb-record-copy'+(record.long?' is-long':'')} tabIndex={record.long?0:undefined} role={record.long?'region':undefined} aria-label={record.long?record.label+'完整内容，版本 '+(item.revision??'未记录')+'，可使用方向键滚动':undefined}>{record.values?<ul>{record.values.map((value,index)=><li key={index}>{value}</li>)}</ul>:<p>{record.text}</p>}</div>
   {record.long&&<p className="wb-record-reading-hint"><Move size={13} aria-hidden="true"/>完整内容保留在上方阅读区，可聚焦后用方向键滚动</p>}
   {record.note&&<p className="wb-record-reading-hint">{record.note}</p>}
  </section>;
 })}</div>;
}
