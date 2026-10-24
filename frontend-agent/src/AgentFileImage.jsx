import React, { useEffect, useRef, useState } from 'react';
import { Image, Maximize2, Network, TriangleAlert, RefreshCw } from 'lucide-react';
import { previewImageDimensions, previewImageSizeLabel } from '../../frontend/src/utils/fileImagePresentation';
import '../../frontend/src/assets/file-image-reader.css';

export default function AgentFileImage(props) {
  const identity=JSON.stringify([props.src,props.name,props.kind]);
  return <ImageReader key={identity} {...props}/>;
}
function ImageReader({src='',name='',kind='',busy=false,downloadable=false}) {
  const [mode,setMode]=useState('fit'),[dimensions,setDimensions]=useState(null),[failed,setFailed]=useState(false),[attempt,setAttempt]=useState(0);
  const imageRef=useRef(null),viewportRef=useRef(null);
  useEffect(()=>{if(attempt>0)viewportRef.current?.focus({preventScroll:true});},[attempt]);
  function current(event) { return event.currentTarget===imageRef.current && event.currentTarget.getAttribute('src')===src; }
  function loaded(event) { if(!current(event))return;const value=previewImageDimensions(event.currentTarget.naturalWidth,event.currentTarget.naturalHeight);setDimensions(value);setFailed(!value); }
  function imageFailed(event) { if(current(event)){setDimensions(null);setFailed(true);} }
  function retry() { if(busy||!src)return;setMode('fit');setDimensions(null);setFailed(false);setAttempt(value=>value+1); }
  return <section className="file-image-reader" aria-label="图像预览阅读区">
    <div className="file-image-toolbar"><div role="group" aria-label="图像显示方式"><button type="button" aria-pressed={mode==='fit'} disabled={busy||!dimensions||failed} onClick={()=>setMode('fit')}><Image size={15} aria-hidden="true"/>适应窗口</button><button type="button" aria-pressed={mode==='actual'} disabled={busy||!dimensions||failed} onClick={()=>setMode('actual')}><Maximize2 size={15} aria-hidden="true"/>实际像素</button></div><span>{previewImageSizeLabel(dimensions,kind)}</span></div>
    {!!src&&!failed&&!dimensions&&<p className="file-image-status" role="status"><Network size={16} aria-hidden="true"/>正在显示预览图</p>}
    {failed||!src?<div className="file-image-unavailable" role="status"><TriangleAlert size={24} aria-hidden="true"/><strong>图像暂不可显示</strong><p>{downloadable?'可手动重新显示已读取的预览图，或使用下方下载入口核对原文件。':'可手动重新显示预览图，或关闭后重新读取会话资料核对。'}</p>{src&&<button type="button" disabled={busy} onClick={retry}><RefreshCw size={15} aria-hidden="true"/>重新显示预览图</button>}</div>:<div ref={viewportRef} className={'file-image-viewport'+(mode==='actual'?' is-actual':'')} tabIndex={0} aria-label={mode==='actual'?'实际像素预览，可使用方向键滚动图像':'适应窗口的图像预览'} aria-busy={!dimensions}><img key={attempt} ref={imageRef} className="file-image-content" src={src} alt={name||'会话资料预览图'} style={mode==='actual'&&dimensions?{width:dimensions.width+'px'}:undefined} onLoad={loaded} onError={imageFailed}/></div>}
    {dimensions&&!failed&&<p className="file-image-note">{mode==='actual'?'实际像素显示，可在图像区域内横向或纵向滚动。':'适应窗口会缩小大图，可切换实际像素查看细节。'}{kind==='pdf'&&<span>像素尺寸属于当前页面预览图，不是原 PDF 的页面尺寸。</span>}</p>}
  </section>;
}
