import React from 'react';
import {Files,FileText,TriangleAlert} from 'lucide-react';
import {contextPresentation} from '../../frontend/src/utils/contextPresentation';
import '../../frontend/src/assets/agent-context-summary.css';
export default function AgentContextSummary({item,files=[],filesEnabled=true,onOpenFiles}){
 const view=contextPresentation(item),canOpenFile=filesEnabled && !!view.fileId && files.some(file=>file?.id===view.fileId);
 const Icon=view.invalidated?TriangleAlert:view.offloaded?Files:FileText;
 return <section className="wb-context-summary" aria-label="上下文记录与覆盖范围" data-invalid={view.invalidated}>
  <p className="wb-context-explanation"><Icon size={16} aria-hidden="true"/><span>{view.explanation}</span></p>
  <dl className="wb-context-scope"><dt>记录所属范围</dt><dd>{view.scope}</dd>{!view.offloaded&&<><dt>{view.cutoffLabel}</dt><dd>{view.cutoff}</dd></>}</dl>
  {!view.offloaded?<><div className="wb-context-counts"><div><span>压缩前字符数</span><strong>{view.before}</strong></div><div><span>压缩后字符数</span><strong>{view.after}</strong></div></div><p className="wb-context-change">{view.change}</p><p className="wb-note">按本条记录的字符数比较，不换算 Token、账单或可用上下文容量。</p></>:<>
   <p className="wb-context-size"><span>已记录资料大小</span><strong>{view.bytes} 字节</strong></p>
   {canOpenFile?<button type="button" className="wb-context-files" onClick={onOpenFiles}><Files size={15} aria-hidden="true"/>在文件产物中查看</button>:<p className="wb-note">当前文件列表没有可用入口，不能据此判断原资料已删除。可刷新工作台或查看执行轨迹。</p>}
   <p className="wb-note">打开文件区不会执行工具或业务操作；预览和下载仍由原接口重新鉴权。</p>
   <details className="wb-context-identifiers"><summary>核对资料编号与内容摘要</summary><dl><dt>文件编号</dt><dd><code>{view.fileId||'编号未记录或格式未知'}</code></dd><dt>SHA-256</dt><dd><code>{view.sha256||'摘要未记录或格式未知'}</code></dd></dl></details>
  </>}
 </section>;
}
