import React, { useEffect, useRef, useState } from 'react';
import { Button } from 'antd';
import { RefreshCw } from 'lucide-react';
import { businessImagePreview } from '../../frontend/src/utils/agentActions.js';
import ProposalImageGallery from './ProposalImageGallery';
export function DetectionProposalImages({ taskId, count, proposalVersion, base = '', refreshKey }) {
  const scope = JSON.stringify([taskId, proposalVersion, base]);
  const [snapshot, setSnapshot] = useState(null), [error, setError] = useState(''), [loading, setLoading] = useState(false);
  const images = snapshot?.scope === scope ? snapshot.images : [];
  const generation = useRef(0), activeRead = useRef(null);
  function stopRead() { generation.current++; activeRead.current?.abort(); activeRead.current = null; }
  async function refresh() {
    stopRead(); setLoading(false); setError('');
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(taskId || '')) { setError('任务编号不完整，无法核对原图资料。'); return; }
    const version = ++generation.current, controller = new AbortController(); activeRead.current = controller; setLoading(true);
    try {
      const response = await fetch(base + '/api/agent/business-files/DETECTION/' + encodeURIComponent(taskId) + '/originals', { credentials: 'include', cache: 'no-store', signal: controller.signal });
      if (!response.ok) { const failure = new Error(); failure.status = response.status; throw failure; }
      const data = await response.json();
      if (version !== generation.current) return;
      if (!Array.isArray(data) || !data.every(image => image && image.resourceId === taskId && typeof image.name === 'string' && businessImagePreview(image))) throw new Error();
      setSnapshot({ scope, images: data });
    } catch (failure) {
      if (version !== generation.current || controller.signal.aborted) return;
      if ([401, 403, 404].includes(failure.status)) { setSnapshot(null); setError('当前账号无法读取该任务原图，请核对任务及文件权限。'); }
      else setError('原图资料暂不可读取。已显示资料仅为上次快照，请重新读取或到检测记录核对。');
    } finally { if (version === generation.current) { activeRead.current = null; setLoading(false); } }
  }
  useEffect(() => { refresh(); return stopRead; }, [taskId, proposalVersion, base, refreshKey]);
  return <section className="proposal-originals" aria-label="检测任务原图资料" aria-busy={loading}>
    <div className="proposal-originals-toolbar"><span>核对已有任务的原图</span><Button size="small" loading={loading} onClick={refresh}><RefreshCw size={14} aria-hidden="true"/>重新读取资料</Button></div>
    {loading && <p className="proposal-originals-note" role="status">{images.length ? '正在读取，当前保留上次原图资料快照。' : '正在读取原图资料…'}</p>}
    {error && <p className="proposal-originals-error" role="alert">{error}</p>}
    <ProposalImageGallery images={images} scopeKey={scope} base={base} label="任务原图"/>
    {images.length > 0 ? <p className="proposal-originals-note">本次返回 {images.length.toLocaleString('zh-CN')} 张预览，{Number.isSafeInteger(count) && count >= 0 ? `提议共 ${count.toLocaleString('zh-CN')} 张` : '提议图片总数未记录'}。检测范围仍以原卡片及其版本为准。</p> : snapshot?.scope === scope && !loading && !error && <p className="proposal-originals-note">本次没有返回可预览原图。请到检测记录核对，不能据此认为原任务没有图片。</p>}
  </section>;
}
