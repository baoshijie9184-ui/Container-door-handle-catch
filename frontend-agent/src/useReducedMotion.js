import {useEffect,useRef,useState} from 'react';

export function useReducedMotion(){
 const [reduced,setReduced]=useState(()=>globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches===true);
 useEffect(()=>{const query=globalThis.matchMedia?.('(prefers-reduced-motion: reduce)');if(!query)return;const update=()=>setReduced(query.matches);update();query.addEventListener('change',update);return()=>query.removeEventListener('change',update)},[]);
 return reduced;
}

// 翻页禁用按钮或响应式布局可能暂时把焦点移到 body；只关闭最上层的本人预览。
export function usePreviewEscape(open,close,rootClass){
 const callback=useRef(close);callback.current=close;
 useEffect(()=>{if(!open)return;const escape=event=>{
  if(event.key!=='Escape'||event.isComposing)return;
  const visible=[...document.querySelectorAll('.ant-modal-wrap')].filter(node=>node.getClientRects().length>0).sort((a,b)=>(Number(getComputedStyle(a).zIndex)||0)-(Number(getComputedStyle(b).zIndex)||0));
  if(!visible.at(-1)?.closest('.'+rootClass))return;
  event.preventDefault();event.stopPropagation();callback.current();
 };document.addEventListener('keydown',escape,true);return()=>document.removeEventListener('keydown',escape,true)},[open,rootClass]);
}
