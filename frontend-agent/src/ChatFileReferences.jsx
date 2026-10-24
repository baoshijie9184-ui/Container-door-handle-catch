import React, { useEffect, useRef, useState } from 'react';
import { Modal, Button } from 'antd';
import { FileText, Image, ChartNoAxesCombined, LockKeyhole, Download } from 'lucide-react';
import { useReducedMotion, usePreviewEscape } from './useReducedMotion';
import { referencedFiles, readReferencedFile, readFilePreview } from '../../frontend/src/utils/chatFileReferences';
import { composerAttachment } from '../../frontend/src/utils/composerPresentation';
import '../../frontend/src/assets/chat-file-references.css';

const fileIcons = { Picture:Image, DataAnalysis:ChartNoAxesCombined, Document:FileText };
function ReferenceIcon({file}) { const Icon = file.unavailable ? LockKeyhole : fileIcons[composerAttachment(file).icon] || FileText; return <Icon size={18} aria-hidden="true"/>; }

export function ChatFileReferences({data}) {
  const {sessionId, ids, base = '', text = ''} = data;
  const reducedMotion = useReducedMotion(), pdfNavigation = useRef(null), pdfFocusPending = useRef(false);
  const [files,setFiles] = useState([]), [error,setError] = useState(''), [busy,setBusy] = useState(false), [loading,setLoading] = useState(false);
  const [preview,setPreview] = useState(null), [retry,setRetry] = useState(0), [imageError,setImageError] = useState('');
  const generation = useRef(0), abort = useRef(null), url = useRef(''), previewVersion = useRef(0), readLock = useRef(false);
  function revoke() { if (url.current) URL.revokeObjectURL(url.current); url.current = ''; }
  function closePreview() { previewVersion.current++; pdfFocusPending.current = false; setPreview(null); revoke(); }
  usePreviewEscape(!!preview,closePreview,'chat-file-preview-modal');
  useEffect(() => { if (preview?.kind === 'pdf' && !busy && pdfFocusPending.current) { pdfFocusPending.current = false; pdfNavigation.current?.focus(); } }, [preview?.kind,preview?.page,busy]);
  useEffect(() => {
    const version = ++generation.current;
    abort.current = new AbortController(); readLock.current = false;
    previewVersion.current++; pdfFocusPending.current = false;
    setFiles([]); setError(''); setBusy(false); setLoading(true); setPreview(null); revoke();
    referencedFiles(sessionId,ids,{base,signal:abort.current.signal})
      .then(value => { if (version === generation.current) setFiles(value); })
      .catch(cause => { if (version === generation.current && cause.name !== 'AbortError') setError(cause.message); })
      .finally(() => { if (version === generation.current) setLoading(false); });
    return () => { generation.current++; abort.current?.abort(); revoke(); };
  }, [sessionId,ids.join(','),base,retry]);

  async function read(file,download = false,page = 1) {
    if (readLock.current || !file || file.unavailable) return;
    readLock.current = true;
    const version = generation.current, previewRequest = download ? previewVersion.current : ++previewVersion.current;
    if (!download && preview?.kind === 'pdf') pdfFocusPending.current = true;
    setBusy(true); setError('');
    try {
      const options = {base,signal:abort.current?.signal,page};
      if (download) {
        const blob = await readReferencedFile(sessionId,file,options);
        if (version !== generation.current) return;
        const link = document.createElement('a'), href = URL.createObjectURL(blob);
        link.href = href; link.download = file.name; link.click(); setTimeout(() => URL.revokeObjectURL(href),1000);
        return;
      }
      const value = await readFilePreview(sessionId,file,options);
      if (version !== generation.current || previewRequest !== previewVersion.current) return;
      revoke(); setImageError('');
      if (value.kind !== 'text') url.current = URL.createObjectURL(value.kind === 'pdf' ? value.blob : new Blob([value.blob],{type:file.contentType}));
      pdfFocusPending.current = value.kind === 'pdf';
      setPreview({...value,file,url:url.current});
    } catch (cause) {
      if (version === generation.current && (download || previewRequest === previewVersion.current) && cause.name !== 'AbortError') {
        setError(cause.message);
        if ([401,403,404].includes(cause.status)) {
          setFiles(current => cause.status === 401 ? [] : current.map(value => value.id === file.id ? {id:file.id,unavailable:true} : value));
          closePreview();
        }
      }
    } finally { if (version === generation.current) { readLock.current = false; setBusy(false); } }
  }

  return <>
    {text && <p style={{whiteSpace:'pre-wrap'}}>{text}</p>}
    <section className="chat-file-references" aria-label="消息附件">
      {loading && <span role="status">正在读取附件信息</span>}
      {files.map(file => <article className="chat-file-card" key={file.id}>
        <ReferenceIcon file={file}/><span className="chat-file-label">{file.unavailable ? '资料已移除或无权访问' : file.name}{!file.unavailable && <small>{composerAttachment(file).type} · {composerAttachment(file).size}</small>}</span>
        {!file.unavailable && <><button type="button" disabled={busy} onClick={() => read(file)}>预览</button><button type="button" disabled={busy} onClick={() => read(file,true)}>下载</button></>}
      </article>)}
      {error && !preview && <p role="alert">{error} <button type="button" disabled={busy || loading} onClick={() => setRetry(value => value + 1)}>重新读取</button></p>}
    </section>
    <Modal rootClassName="chat-file-preview-modal" transitionName={reducedMotion ? '' : 'ant-zoom'} maskTransitionName={reducedMotion ? '' : 'ant-fade'} title={preview?.file?.name || '消息附件预览'} open={!!preview} footer={<div className="file-preview-actions"><Button onClick={closePreview}>关闭预览</Button><Button type="primary" disabled={busy || !preview?.file} icon={<Download size={15} aria-hidden="true"/>} onClick={() => read(preview.file,true)}>下载原文件</Button></div>} width="min(900px,90vw)" onCancel={closePreview}>
      <p className="file-preview-meta"><ReferenceIcon file={preview?.file || {}}/><span>{composerAttachment(preview?.file).type}</span><span>{composerAttachment(preview?.file).size}</span></p>
      {(error || imageError) && <p className="chat-reference-preview-error" role="alert">{error || imageError}</p>}
      {busy && <p role="status">正在读取文件，请稍候</p>}
      {preview?.kind === 'pdf' && <nav ref={pdfNavigation} tabIndex={-1} className="chat-file-pages" aria-label="PDF 页码"><button type="button" disabled={busy || preview.page === 1} onClick={() => read(preview.file,false,preview.page - 1)}>上一页</button><span role="status">第 {preview.page} / {preview.pages} 页</span><button type="button" disabled={busy || preview.page === preview.pages} onClick={() => read(preview.file,false,preview.page + 1)}>下一页</button><small>页面预览 · Agent 仅可读取文字层</small></nav>}
      <p className="chat-reference-preview-note">预览不执行文件内容；HTML/SVG 仅展示源码，PDF 显示页面图片。</p>
      {['image','pdf'].includes(preview?.kind) ? <img src={preview.url} className="chat-file-image" alt={preview.file?.name || '会话附件预览'} onError={() => setImageError('图片预览失败，请下载原文件核对')}/> : <pre className="chat-file-preview-text" tabIndex={0} aria-label="附件文本或源码预览">{preview?.text}</pre>}
    </Modal>
  </>;
}
