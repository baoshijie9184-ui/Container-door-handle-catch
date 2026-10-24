import {useEffect} from 'react';
import '../../frontend/src/assets/agent-markdown.css';

// Keep AgentScope's Markdown, highlighting, citations and code actions intact.
// Only enhance the generated reading surfaces inside this transcript instance.
export function useReadableMessageRegions(transcriptRef,sessionId){
 useEffect(()=>{
  const root=transcriptRef.current;
  if(!root)return;
  let frame=null,active=true;
  function enhance(){
   frame=null;
   if(!active)return;
   for(const node of root.querySelectorAll('.conversation-messages table,.conversation-messages pre')){
    if(node.closest('svg'))continue;
    const table=node.tagName==='TABLE';
    node.classList.add(table?'agent-message-table':'agent-message-code');
    if(!node.hasAttribute('tabindex'))node.setAttribute('tabindex','0');
    if(!node.hasAttribute('aria-label'))node.setAttribute('aria-label',table?'消息表格，可在本区域滚动阅读':'消息代码，可在本区域滚动并选中复制');
   }
  }
  function schedule(){if(active && frame===null)frame=requestAnimationFrame(enhance)}
  enhance();
  const observer=typeof MutationObserver==='function'?new MutationObserver(schedule):null;
  observer?.observe(root,{childList:true,subtree:true});
  return()=>{active=false;observer?.disconnect();if(frame!==null)cancelAnimationFrame(frame)};
 },[transcriptRef,sessionId]);
}
