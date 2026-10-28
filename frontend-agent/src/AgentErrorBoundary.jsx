import {SYSTEM_NAME,SYSTEM_SHORT_NAME,SYSTEM_TAGLINE,AGENT_WORKSPACE_NAME} from '../../frontend/src/utils/systemBrand';
import React from 'react';
import { ScanLine, RefreshCw, ArrowLeft, ChartNoAxesCombined, X } from 'lucide-react';
import './agent-error-boundary.css';

// A render failure is not a task cancellation or a business command receipt.
export class AgentErrorBoundary extends React.Component {
  state = { failed: false, confirmReload: false };
  heading = React.createRef();
  reloadToggle = React.createRef();

  static getDerivedStateFromError() {
    return { failed: true, confirmReload: false };
  }

  componentDidCatch() {
    this.heading.current?.focus({ preventScroll: true });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return <main className="agent-error-page" aria-labelledby="agent-error-title">
      <div className="agent-error-content">
        <a className="agent-error-brand" href={this.props.businessHref} title={SYSTEM_NAME} aria-label={SYSTEM_NAME}><ScanLine size={22} aria-hidden="true"/><span>{SYSTEM_SHORT_NAME}<span>{AGENT_WORKSPACE_NAME}</span></span></a>
        <div className="agent-error-heading"><span className="agent-error-symbol" aria-hidden="true"><X size={21}/></span><h1 id="agent-error-title" tabIndex={-1} ref={this.heading}>对话界面暂时无法显示</h1></div>
        <p>页面遇到显示异常。此提示不能确认后台任务是否结束，也不代表操作已取消。</p>
        <section className="agent-error-guidance" aria-label="继续操作前请核对">
          <h2>先核对，再继续</h2>
          <ul><li>已提交的任务和确认操作，请从执行追溯或业务页面检查结果，避免重复提交。</li><li>服务端已保存的会话可在界面恢复后重新读取；当前未保存的输入和附件选择可能丢失。</li></ul>
        </section>
        <nav className="agent-error-actions" aria-label="异常恢复操作">
          <button ref={this.reloadToggle} type="button" aria-expanded={this.state.confirmReload} aria-controls="agent-reload-confirm" onClick={()=>this.setState({confirmReload:!this.state.confirmReload})}><RefreshCw size={16} aria-hidden="true"/>重新加载界面</button>
          <a href={this.props.traceHref}><ChartNoAxesCombined size={16} aria-hidden="true"/>查看执行追溯</a>
          <a href={this.props.businessHref}><ArrowLeft size={16} aria-hidden="true"/>返回系统首页</a>
        </nav>
        <section id="agent-reload-confirm" hidden={!this.state.confirmReload} className="agent-reload-confirm" aria-label="确认重新加载界面">
          <p>重新加载会离开当前界面，请先保留仍可取得的未保存内容。页面刷新不会为你确认或重发原业务操作。</p>
          <div><button type="button" onClick={()=>window.location.reload()}>确认重新加载</button><button type="button" onClick={()=>this.setState({confirmReload:false},()=>this.reloadToggle.current?.focus({preventScroll:true}))}>暂不刷新</button></div>
        </section>
      </div>
    </main>;
  }
}
