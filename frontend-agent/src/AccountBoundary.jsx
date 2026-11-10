import React, { useEffect, useState } from 'react';
import { accountSession, onIdentitySignal } from '../../frontend/src/utils/accountContext';
import { accountFetch } from '../../frontend/src/utils/accountFetch';
import { createAccountTaskCache } from '../../frontend/src/utils/accountTaskCache';
import { createRealtimeChanges } from '../../frontend/src/utils/realtimeChanges';

globalThis.__doorhandleAccountFetch = accountFetch;
const taskCache=createAccountTaskCache({session:accountSession,storage:()=>globalThis.localStorage});
accountSession.onReset(previous=>taskCache.clear(previous.accountContext));
export function AccountBoundary({ children, loginHref }) {
  const [account, setAccount] = useState(accountSession.state), [status, setStatus] = useState('connecting');
  useEffect(() => {
    let alive=true, pending, pendingEpoch=-1;
    const check=()=>{
      const epoch=accountSession.state.epoch;
      if(pending&&pendingEpoch===epoch)return pending;
      pendingEpoch=epoch;
      const task=accountFetch('/api/auth/check',{cache:'no-store'}).then(async response=>{
        if(!response.ok){if(response.status===401&&accountSession.state.epoch===epoch)accountSession.clear('登录已失效，请重新登录');return false}
        const body=await response.json();if(!alive||accountSession.state.epoch!==epoch)return false;
        accountSession.accept(body.data||body,epoch);return true;
      }).catch(()=>false).finally(()=>{if(pending===task)pending=undefined});pending=task;return task;
    };
    const hub=createRealtimeChanges({session:accountSession,checkAuth:check});
    const off=accountSession.subscribe(value=>{if(alive)setAccount(value)}),statusOff=hub.subscribeStatus(value=>{if(alive)setStatus(value)});
    const signalOff=onIdentitySignal(check);
    globalThis.addEventListener('doorhandle-account-recheck',check);
    globalThis.addEventListener('focus',check);
    check().then(()=>hub.start());
    return()=>{alive=false;off();statusOff();signalOff();hub.dispose();globalThis.removeEventListener('doorhandle-account-recheck',check);globalThis.removeEventListener('focus',check)};
  },[]);
  if(!account.authenticated)return <main className="agent-account-gate"><h1>请确认当前登录身份</h1><p>{account.reason||'正在核对账号与登录上下文'}</p><a href={loginHref}>前往系统登录</a></main>;
  return <React.Fragment key={account.epoch}><div className="agent-collaboration-status" role="status">{account.user?.username} · {status==='connected'?'修改通知已连接':status==='polling'?'当前使用定期核对 每30秒确认身份':status==='unavailable'?'实时通知暂不可用':'正在恢复修改通知'} <a href="/#/operations/audit">修改记录</a></div>{children}</React.Fragment>;
}
