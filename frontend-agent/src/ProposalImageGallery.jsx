import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Modal } from 'antd';
import { Image as ImageIcon, Search, TriangleAlert, RefreshCw } from 'lucide-react';
import { proposalImageRows } from '../../frontend/src/utils/proposalImages.js';
import { useReducedMotion, usePreviewEscape } from './useReducedMotion';
import '../../frontend/src/assets/proposal-image-gallery.css';

export default function ProposalImageGallery({ images = [], scopeKey = '', label = '提议原图', base = '' }) {
  const rows = useMemo(() => proposalImageRows(images, JSON.stringify([scopeKey, base])), [images, scopeKey, base]);
  const signature = JSON.stringify(rows.map(row => row.key));
  const [failed, setFailed] = useState(new Set()), [loaded, setLoaded] = useState(new Set()), [attempts, setAttempts] = useState({});
  const [selection, setSelection] = useState(null), [zoomError, setZoomError] = useState(false), [zoomLoaded, setZoomLoaded] = useState(false), [zoomAttempt, setZoomAttempt] = useState(0);
  const reducedMotion = useReducedMotion();
  const selectedIndex = selection?.signature === signature ? selection.index : -1, current = rows[selectedIndex];
  const latest = useRef(null); latest.current = { keys: new Set(rows.map(row => row.key)), key: current?.key, attempt: zoomAttempt };
  useEffect(() => { setSelection(null); setFailed(new Set()); setLoaded(new Set()); setAttempts({}); }, [signature]);
  function mark(key, success) { if (!latest.current.keys.has(key)) return; if (success) setLoaded(values => new Set([...values, key])); else setFailed(values => new Set([...values, key])); }
  function retry(row) { if (!row.path || !latest.current.keys.has(row.key)) return; setAttempts(value => ({ ...value, [row.key]: (value[row.key] || 0) + 1 })); setFailed(value => new Set([...value].filter(key => key !== row.key))); setLoaded(value => new Set([...value].filter(key => key !== row.key))); }
  function select(index) { if (!Number.isInteger(index) || !rows[index]?.path) return; setSelection({ signature, index }); setZoomError(false); setZoomLoaded(false); setZoomAttempt(0); }
  function close() { setSelection(null); setZoomError(false); setZoomLoaded(false); }
  function zoomEvent(event, success) { if (event.currentTarget.dataset.key !== latest.current.key || Number(event.currentTarget.dataset.attempt) !== latest.current.attempt) return; if (success) setZoomLoaded(true); else setZoomError(true); }
  usePreviewEscape(!!current, close, 'proposal-image-modal');
  if (!rows.length) return null;
  return <section className="proposal-gallery" aria-label={label}>
    <div className="proposal-gallery-heading"><strong><ImageIcon size={15} aria-hidden="true"/>{label}</strong><span>{rows.length.toLocaleString('zh-CN')} 张预览资料</span></div>
    <div className="proposal-gallery-grid" tabIndex={0} aria-label={label + '缩略图，可滚动阅读'}>{rows.map((row, index) => <figure key={row.key}>
      {row.path && !failed.has(row.key) ? <button type="button" className="proposal-image-button" aria-haspopup="dialog" aria-label={'放大图片 ' + row.name} onClick={() => select(index)}><img key={attempts[row.key] || 0} src={base + row.path} alt={row.name} loading="lazy" decoding="async" referrerPolicy="no-referrer" onLoad={() => mark(row.key, true)} onError={() => mark(row.key, false)}/><span className="proposal-image-overlay">{loaded.has(row.key) ? <Search size={14} aria-hidden="true"/> : <RefreshCw size={14} aria-hidden="true"/>}{loaded.has(row.key) ? '放大核对' : '正在读取'}</span></button> : <div className="proposal-image-fallback"><TriangleAlert size={21} aria-hidden="true"/><span>{row.path ? '预览暂不可读取' : '预览地址待核对'}</span>{row.path && <Button size="small" onClick={() => retry(row)}>重新读取</Button>}</div>}
      <figcaption><strong>{row.name}</strong><span>{row.source}</span></figcaption>
    </figure>)}</div>
    <Modal open={!!current} title="检测原图核对" rootClassName="proposal-image-modal" width="min(1000px, 94vw)" transitionName={reducedMotion ? '' : 'ant-zoom'} maskTransitionName={reducedMotion ? '' : 'ant-fade'} onCancel={close} footer={<div className="proposal-preview-actions"><div><Button disabled={selectedIndex <= 0 || !rows[selectedIndex - 1]?.path} onClick={() => select(selectedIndex - 1)}>上一张</Button><Button disabled={selectedIndex < 0 || !rows[selectedIndex + 1]?.path} onClick={() => select(selectedIndex + 1)}>下一张</Button></div><Button onClick={close}>关闭图片</Button></div>}>
      {current && <><div className="proposal-image-details"><strong>{current.name}</strong><span>{current.source}{current.taskId && ' · 任务 ' + current.taskId} · 第 {selectedIndex + 1} / {rows.length} 张</span></div>
        <p className="proposal-preview-note">此处仅查看原图资料，关闭或翻页不会批准检测。请回到卡片核对图片范围、参数及提议版本后明确确认。</p>
        {zoomError ? <div className="proposal-image-fallback proposal-zoom-fallback" role="alert"><TriangleAlert size={26} aria-hidden="true"/><strong>图片暂不可读取</strong><span>请核对登录与文件权限，或重新读取原预览。</span><Button onClick={() => { setZoomAttempt(value => value + 1); setZoomError(false); setZoomLoaded(false); }}><RefreshCw size={14} aria-hidden="true"/>重新读取图片</Button></div> : <div className="proposal-zoom-frame">{!zoomLoaded && <p role="status" className="proposal-preview-note">正在读取原图…</p>}<img key={current.key + ':' + zoomAttempt} src={base + current.path} alt={current.name} data-key={current.key} data-attempt={zoomAttempt} referrerPolicy="no-referrer" onLoad={event => zoomEvent(event, true)} onError={event => zoomEvent(event, false)}/></div>}
        {current.hash && <details className="proposal-image-digest"><summary>内容摘要 SHA-256</summary><code>{current.hash}</code></details>}
      </>}
    </Modal>
  </section>;
}
