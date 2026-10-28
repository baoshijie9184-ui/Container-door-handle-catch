// A2UI 0.9.1 envelope subset with a negotiated, application-owned catalog.
export const A2UI_VERSION='v0.9.1';
export const A2UI_CATALOG='urn:doorhandle:a2ui:workspace:1';
const forbidden=new Set(['__proto__','prototype','constructor']);
const fields={Text:['text','variant'],Column:['children'],Row:['children'],Card:['child','title'],Metric:['label','value','note'],DataTable:['columns','rows'],BarChart:['title','points'],TextField:['label','value','placeholder','required'],Form:['children'],Button:['label','action'],Tabs:['tabs'],Progress:['label','value','total'],Status:['label','tone']};
export const A2UI_COMPONENTS=Object.freeze(Object.keys(fields));
const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const assert=(condition,message)=>{if(!condition)throw Error(message);};
const identifier=value=>typeof value==='string'&&/^[A-Za-z0-9_.:-]{1,128}$/.test(value)&&!forbidden.has(value);
export function inspectJson(value) {
  let nodes=0;
  function visit(item,depth) {
    assert(++nodes<=12000&&depth<=16,'界面数据结构超过上限');
    if(typeof item==='string')assert(item.length<=16000,'界面文字超过上限');
    else if(typeof item==='number')assert(Number.isFinite(item),'界面数值无效');
    else if(item!==null&&typeof item==='object') {
      assert(Array.isArray(item)||Object.getPrototypeOf(item)===Object.prototype||Object.getPrototypeOf(item)===null,'界面对象类型无效');
      for(const key of Object.keys(item)) {assert(!forbidden.has(key),'界面包含不安全字段');visit(item[key],depth+1);}
    } else assert(item===null||typeof item==='boolean','界面数据类型无效');
  }
  visit(value,0);assert(JSON.stringify(value).length<=262144,'界面数据超过上限');return value;
}
export function pointerParts(path) {
  assert(typeof path==='string'&&path.startsWith('/')&&path.length<=300,'数据路径无效');
  if(path==='/')return [];
  const parts=path.slice(1).split('/').map(key=>{assert(!/~(?![01])/.test(key),'数据路径转义无效');return key.replace(/~1/g,'/').replace(/~0/g,'~');});
  assert(parts.length<=8&&parts.every(key=>key&&!forbidden.has(key)),'数据路径无效');return parts;
}
export function resolveValue(value,model) {
  if(!object(value))return value;
  assert(Object.keys(value).length===1&&typeof value.path==='string','仅支持显式数据路径');
  return pointerParts(value.path).reduce((current,key)=>current&&Object.hasOwn(current,key)?current[key]:undefined,model);
}
export function updateModel(model,path,value,remove=false) {
  const parts=pointerParts(path),next=structuredClone(model);
  if(!parts.length) {if(remove)return {};assert(object(value),'界面根数据必须是对象');return structuredClone(inspectJson(value));}
  const arrayIndex=(container,key,append=false)=>{if(Array.isArray(container))assert(/^(0|[1-9]\d*)$/.test(key)&&Number(key)<=(append?container.length:container.length-1)&&Number(key)<12000,'数组路径超出范围');};
  let current=next;
  for(const key of parts.slice(0,-1)){assert(object(current)||Array.isArray(current),'数据父节点不是容器');arrayIndex(current,key);if(!Object.hasOwn(current,key))current[key]={};current=current[key];}
  assert(object(current)||Array.isArray(current),'数据父节点不是容器');
  const key=parts.at(-1);arrayIndex(current,key,!remove);if(remove){if(Array.isArray(current))current.splice(Number(key),1);else delete current[key];}else current[key]=structuredClone(inspectJson(value));
  inspectJson(next);return next;
}
function dynamic(value,kind) {
  if(object(value)){assert(Object.keys(value).length===1,'动态值无效');pointerParts(value.path);return;}
  assert(typeof value===kind,'组件属性类型无效');
}
function validateComponent(component) {
  assert(object(component)&&identifier(component.id)&&typeof component.component==='string','组件定义无效');
  const allowed=Object.hasOwn(fields,component.component)?fields[component.component]:null;
  if(!allowed)return {...component,unsupported:true};
  assert(Object.keys(component).every(key=>['id','component',...allowed].includes(key)),'组件包含未允许的属性');
  const kind=component.component;
  if(['Column','Row','Form'].includes(kind)) assert(Array.isArray(component.children)&&component.children.length<=48&&component.children.every(identifier),'子组件列表无效');
  if(kind==='Card')assert(identifier(component.child),'卡片内容无效');
  if(kind==='Text') {dynamic(component.text,'string');assert(component.variant===undefined||['body','caption','h3'].includes(component.variant),'文字样式无效');}
  if(kind==='Metric'){dynamic(component.label,'string');assert(['string','number'].includes(typeof component.value)||object(component.value),'统计值无效');if(object(component.value))dynamic(component.value,'number');}
  if(kind==='Status'){dynamic(component.label,'string');assert(['neutral','info','success','warning','error'].includes(component.tone||'neutral'),'状态颜色无效');}
  if(kind==='Progress'){dynamic(component.label,'string');dynamic(component.value,'number');dynamic(component.total,'number');}
  if(kind==='DataTable') {assert(Array.isArray(component.columns)&&component.columns.length>0&&component.columns.length<=8,'表格列无效');for(const column of component.columns)assert(object(column)&&Object.keys(column).every(key=>['key','label'].includes(key))&&identifier(column.key)&&typeof column.label==='string','表格列定义无效');assert(Array.isArray(component.rows)||object(component.rows),'表格数据无效');if(object(component.rows))dynamic(component.rows,'object');}
  if(kind==='BarChart'){dynamic(component.title,'string');assert(Array.isArray(component.points)||object(component.points),'图表数据无效');if(object(component.points))dynamic(component.points,'object');}
  if(kind==='Tabs'){assert(Array.isArray(component.tabs)&&component.tabs.length>0&&component.tabs.length<=8,'选项卡无效');for(const tab of component.tabs)assert(object(tab)&&Object.keys(tab).every(key=>['title','child'].includes(key))&&typeof tab.title==='string'&&identifier(tab.child),'选项卡定义无效');}
  if(kind==='TextField'){dynamic(component.label,'string');assert(object(component.value),'输入框必须绑定数据路径');dynamic(component.value,'string');assert(component.required===undefined||typeof component.required==='boolean','输入条件无效');}
  if(kind==='Button'){
    dynamic(component.label,'string');const event=component.action?.event;
    assert(object(component.action)&&Object.keys(component.action).length===1&&object(event)&&Object.keys(event).every(key=>['name','context'].includes(key))&&['REFRESH','FOLLOW_UP'].includes(event.name),'此交互尚未支持');
    assert(event.context===undefined||object(event.context),'交互上下文无效');
    for(const value of Object.values(event.context||{}))if(object(value))dynamic(value,'string');
  }
  return {...component};
}
function children(node) {return node.unsupported?[]:node.children|| (node.child?[node.child]:node.tabs?.map(tab=>tab.child)||[]);}
function verifyGraph(components) {
  const active=new Set(),done=new Set();let edges=0;
  function visit(key,depth){assert(depth<=16,'组件嵌套超过上限');if(done.has(key)||!Object.hasOwn(components,key))return;assert(!active.has(key),'组件存在循环引用');active.add(key);for(const child of children(components[key])){assert(++edges<=512,'组件引用超过上限');visit(child,depth+1);}active.delete(key);done.add(key);}
  for(const key of Object.keys(components))visit(key,0);
}
export function applyA2uiMessage(state,message) {
  inspectJson(message);assert(object(message)&&message.version===A2UI_VERSION,'界面协议版本暂不支持');
  const keys=Object.keys(message).filter(key=>key!=='version');assert(keys.length===1&&['createSurface','updateComponents','updateDataModel','deleteSurface'].includes(keys[0]),'界面事件无效');
  const operation=keys[0],payload=message[operation];assert(object(payload)&&identifier(payload.surfaceId),'界面编号无效');
  const surfaceId=payload.surfaceId,current=Object.hasOwn(state,surfaceId)?state[surfaceId]:null;
  if(operation==='deleteSurface'){assert(Object.keys(payload).length===1,'删除事件无效');const next={...state};delete next[surfaceId];return next;}
  if(operation==='createSurface') {
    assert(!current&&Object.keys(state).length<8,'界面已存在或数量超过上限');
    assert(Object.keys(payload).every(key=>['surfaceId','catalogId','sendDataModel'].includes(key))&&payload.catalogId===A2UI_CATALOG&&payload.sendDataModel!==true,'此界面组件目录尚未支持');
    return {...state,[surfaceId]:{surfaceId,components:{},dataModel:{}}};
  }
  assert(current,'界面尚未创建');
  if(operation==='updateComponents') {
    assert(Object.keys(payload).every(key=>['surfaceId','components'].includes(key))&&Array.isArray(payload.components)&&payload.components.length<=96,'组件更新无效');
    const components={...current.components},seen=new Set();
    for(const component of payload.components){const checked=validateComponent(component);assert(!seen.has(checked.id),'组件编号重复');seen.add(checked.id);components[checked.id]=checked;}
    assert(Object.keys(components).length<=96,'组件数量超过上限');verifyGraph(components);
    return {...state,[surfaceId]:{...current,components}};
  }
  assert(Object.keys(payload).every(key=>['surfaceId','path','value'].includes(key)),'数据更新包含未知字段');
  return {...state,[surfaceId]:{...current,dataModel:updateModel(current.dataModel,payload.path||'/',payload.value,!Object.hasOwn(payload,'value'))}};
}
export function readA2uiMessages(messages) {
  assert(Array.isArray(messages)&&messages.length<=64,'界面事件数量无效');
  return messages.reduce(applyA2uiMessage,{});
}
export function buildUiAction(surface,component,timestamp=new Date().toISOString()) {
  assert(component.component==='Button'&&component.action?.event,'交互来源无效');
  const event=component.action.event,context={};
  for(const [key,value] of Object.entries(event.context||{})) context[key]=resolveValue(value,surface.dataModel)??'';
  inspectJson(context);
  return {name:event.name,surfaceId:surface.surfaceId,sourceComponentId:component.id,timestamp,context};
}
