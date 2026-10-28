import React,{Component,useId,useState} from 'react';
import {Alert,Button,Input,Progress,Table,Tabs,Tag,Tooltip} from '@agentscope-ai/design';
import {ArrowUpRight,ChartNoAxesCombined,RefreshCw,TriangleAlert} from 'lucide-react';
import {buildUiAction,resolveValue,updateModel} from './a2uiState';

const number=value=>typeof value==='number'&&Number.isFinite(value)?value:null;
const text=value=>value===null||value===undefined?'—':['string','number','boolean'].includes(typeof value)?String(value):'—';
const colors={neutral:'default',info:'blue',success:'green',warning:'gold',error:'red'};
class SurfaceBoundary extends Component {
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  componentDidUpdate(previous){if(this.state.failed&&previous.resetKey!==this.props.resetKey)this.setState({failed:false});}
  render(){return this.state.failed?<Alert type="warning" showIcon message="此动态界面暂不可展示，聊天正文仍可阅读" action={this.props.onRetry&&<Button size="small" onClick={this.props.onRetry}>重新读取</Button>}/>:this.props.children;}
}
function Bars({title,points}) {
  const [selected,setSelected]=useState(null);
  const valid=Array.isArray(points)?points.filter(point=>point&&typeof point.label==='string'&&number(point.value)!==null&&point.value>=0).slice(0,32):[];
  const max=Math.max(1,...valid.map(point=>point.value));
  return <figure className="a2ui-chart"><figcaption><ChartNoAxesCombined size={16}/><strong>{text(title)}</strong><span>{selected===null?'选择条目查看数值':`${valid[selected]?.label||''} ${valid[selected]?.value??''}`}</span></figcaption>{valid.length?<div className="a2ui-chart-bars">{valid.map((point,index)=><Tooltip key={index} title={`${point.label}：${point.value.toLocaleString('zh-CN')}`}><button type="button" className={selected===index?'selected':''} onClick={()=>setSelected(index)} onFocus={()=>setSelected(index)} aria-label={`${point.label}：${point.value}`}><span>{point.label}</span><i style={{width:`${point.value/max*100}%`}}/><strong>{point.value.toLocaleString('zh-CN')}</strong></button></Tooltip>)}</div>:<p className="a2ui-empty">本次没有可绘制的数值</p>}</figure>;
}
// A catalog is code owned by the application. JSON only selects registered components.
export const a2uiRegistry=Object.freeze({
  Text:({node,value})=>{const TagName=node.variant==='h3'?'h3':'p';return <TagName className={`a2ui-text ${node.variant||'body'}`}>{text(value(node.text))}</TagName>;},
  Column:({node,render})=><div className="a2ui-column">{node.children.map(render)}</div>,
  Row:({node,render})=><div className="a2ui-row">{node.children.map(render)}</div>,
  Form:({node,render})=><div className="a2ui-form" role="group" aria-label="分析条件">{node.children.map(render)}</div>,
  Card:({node,render})=><section className="a2ui-card">{node.title&&<h3>{text(node.title)}</h3>}{render(node.child)}</section>,
  Metric:({node,value})=><div className="a2ui-metric"><span>{text(value(node.label))}</span><strong>{typeof value(node.value)==='number'?value(node.value).toLocaleString('zh-CN'):text(value(node.value))}</strong>{node.note&&<small>{text(node.note)}</small>}</div>,
  DataTable:({node,value})=>{const source=value(node.rows),rows=Array.isArray(source)?source.filter(row=>row&&typeof row==='object'&&!Array.isArray(row)).slice(0,100).map((row,index)=>({...row,__workspaceRowKey:String(index)})):[];return <div className="a2ui-table"><Table size="small" pagination={false} rowKey="__workspaceRowKey" scroll={{x:'max-content'}} dataSource={rows} columns={node.columns.map(column=>({title:column.label,dataIndex:column.key,key:column.key,render:text}))} locale={{emptyText:'本次查询没有记录'}}/></div>;},
  BarChart:({node,value})=><Bars title={value(node.title)} points={value(node.points)}/>,
  Tabs:({node,render})=><Tabs size="small" destroyOnHidden={false} items={node.tabs.map((tab,index)=>({key:String(index),label:tab.title,children:render(tab.child)}))}/>,
  Progress:({node,value})=>{const done=number(value(node.value)),total=number(value(node.total));return <div className="a2ui-progress"><span>{text(value(node.label))}</span>{done!==null&&total!==null&&total>0?<><Progress percent={Math.min(100,Math.max(0,done/total*100))} showInfo={false}/><small>{done.toLocaleString('zh-CN')} / {total.toLocaleString('zh-CN')}</small></>:<small>进度尚未提供</small>}</div>;},
  Status:({node,value})=><Tag className="a2ui-status" data-tone={node.tone||'neutral'} color={colors[node.tone||'neutral']}>{text(value(node.label))}</Tag>,
  TextField:({node,value,write,disabled,fieldId})=><label className="a2ui-field" htmlFor={fieldId}><span>{text(value(node.label))}{node.required&&<small aria-hidden="true">必填</small>}</span><Input id={fieldId} aria-label={text(value(node.label))} aria-required={node.required||undefined} value={text(value(node.value))==='—'?'':text(value(node.value))} placeholder={node.placeholder} maxLength={500} disabled={disabled} onChange={event=>write(node.value.path,event.target.value)}/></label>,
  Button:({node,value,action,disabled})=><Button type={node.action.event.name==='FOLLOW_UP'?'primary':'default'} iconSize={14} icon={node.action.event.name==='REFRESH'?<RefreshCw size={14}/>:<ArrowUpRight size={14}/>} disabled={disabled} onClick={action}>{text(value(node.label))}</Button>,
});
function SurfaceContent({surface,onAction,disabled=false}) {
  const instanceId=useId();
  const [edits,setEdits]=useState({}),[error,setError]=useState(''),[sending,setSending]=useState(false);
  const editable=new Set(Object.values(surface.components).filter(node=>node.component==='TextField').map(node=>node.value.path));
  const model=Object.entries(edits).reduce((value,[path,text])=>editable.has(path)?updateModel(value,path,text):value,surface.dataModel);
  function write(path,value){try{updateModel(model,path,value);setEdits(previous=>({...previous,[path]:value}));setError('');}catch(failure){setError(failure.message);}}
  async function action(node) {
    if(sending||disabled)return;
    for(const component of Object.values(surface.components))if(node.action.event.name!=='REFRESH'&&component.component==='TextField'&&component.required&&!String(resolveValue(component.value,model)??'').trim()){setError('请填写必填的分析条件');return;}
    setSending(true);setError('');
    try{if(!onAction)throw Error('此界面暂不支持操作');await onAction(buildUiAction({...surface,dataModel:model},node));}
    catch(failure){setError(failure.message||'操作未确认，请核对后重试');}
    finally{setSending(false);}
  }
  function render(id) {
    const node=surface.components[id];
    if(!node)return <div key={id} className="a2ui-placeholder" role="status">正在接收界面组件</div>;
    const Renderer=Object.hasOwn(a2uiRegistry,node.component)?a2uiRegistry[node.component]:null;
    if(!Renderer||node.unsupported)return <div key={id} className="a2ui-unsupported"><TriangleAlert size={14}/>此组件暂不支持</div>;
    return <Renderer key={id} node={node} value={item=>resolveValue(item,model)} render={render} write={write} action={()=>action(node)} fieldId={`${instanceId}-${id}`} disabled={disabled||sending}/>;
  }
  return <section className="a2ui-surface" aria-label="动态分析结果" aria-busy={sending}>{render('root')}{error&&<Alert type="warning" showIcon message={error}/>}</section>;
}
export function A2uiSurface(props) {
  return <SurfaceBoundary key={props.surface.surfaceId} resetKey={props.surface} onRetry={props.onRetry}><SurfaceContent {...props}/></SurfaceBoundary>;
}
