import {test} from 'node:test';
import assert from 'node:assert/strict';
import {A2UI_CATALOG,applyA2uiMessage,readA2uiMessages,resolveValue,updateModel,buildUiAction} from './a2uiState.js';
const envelope=(operation,value)=>({version:'v0.9.1',[operation]:value});
const create=()=>applyA2uiMessage({},envelope('createSurface',{surfaceId:'s1',catalogId:A2UI_CATALOG}));
const components=nodes=>envelope('updateComponents',{surfaceId:'s1',components:nodes});
test('creates, progressively updates, binds data, removes a field and deletes a surface',()=>{
  let state=create();state=applyA2uiMessage(state,components([{id:'root',component:'Column',children:['text']}]));
  state=applyA2uiMessage(state,components([{id:'text',component:'Text',text:{path:'/name'}}]));
  state=applyA2uiMessage(state,envelope('updateDataModel',{surfaceId:'s1',value:{name:'检测完成'}}));
  assert.equal(resolveValue(state.s1.components.text.text,state.s1.dataModel),'检测完成');
  state=applyA2uiMessage(state,envelope('updateDataModel',{surfaceId:'s1',path:'/name'}));assert.equal(state.s1.dataModel.name,undefined);
  assert.deepEqual(applyA2uiMessage(state,envelope('deleteSurface',{surfaceId:'s1'})),{});
});
test('rejects incompatible versions, catalogs, duplicate creation and missing surfaces',()=>{
  assert.throws(()=>applyA2uiMessage({},envelope('createSurface',{surfaceId:'s1',catalogId:'https://outside.test/catalog'})),/目录/);
  assert.throws(()=>applyA2uiMessage(create(),envelope('createSurface',{surfaceId:'s1',catalogId:A2UI_CATALOG})),/已存在/);
  assert.throws(()=>applyA2uiMessage({},components([])),/尚未创建/);
  assert.throws(()=>applyA2uiMessage({}, {version:'v1.0',createSurface:{}}),/版本/);
});
test('rejects recursive graphs, duplicate IDs and excessive component trees atomically',()=>{
  const state=create();assert.throws(()=>applyA2uiMessage(state,components([{id:'root',component:'Column',children:['root']}])),/循环/);assert.deepEqual(state.s1.components,{});
  assert.throws(()=>applyA2uiMessage(state,components([{id:'a',component:'Text',text:'a'},{id:'a',component:'Text',text:'b'}])),/重复/);
  assert.throws(()=>applyA2uiMessage(state,components(Array.from({length:97},(_,id)=>({id:String(id),component:'Text',text:''})))),/更新/);
});
test('blocks prototype pollution, executable attributes and unregistered action calls',()=>{
  assert.throws(()=>updateModel({},'/__proto__/polluted',true),/路径/);assert.equal({}.polluted,undefined);
  assert.throws(()=>applyA2uiMessage(create(),components([{id:'root',component:'Text',text:'x',dangerouslySetInnerHTML:{__html:'script'}}])),/属性/);
  assert.throws(()=>applyA2uiMessage(create(),components([{id:'root',component:'Button',label:'执行',action:{event:{name:'execute_code'}}}])),/交互/);
  assert.throws(()=>applyA2uiMessage(create(),envelope('updateDataModel',{surfaceId:'s1',value:JSON.parse('{"constructor":{"prototype":{"polluted":true}}}')})),/不安全/);
  assert.throws(()=>resolveValue({call:'eval',args:'code'},{}),/路径/);
  assert.throws(()=>updateModel({rows:[]},'/rows/4294967294','x'),/数组/);
  assert.throws(()=>updateModel({rows:[]},'/rows/length',1000000000),/数组/);
  assert.deepEqual(updateModel({rows:[1]},'/rows/1',2),{rows:[1,2]});
});
test('unknown components become isolated placeholders without stopping supported content',()=>{
  const state=applyA2uiMessage(create(),components([{id:'root',component:'Column',children:['safe','unknown']},{id:'safe',component:'Text',text:'仍可阅读'},{id:'unknown',component:'Iframe',url:'https://outside.test'}]));
  assert.equal(state.s1.components.unknown.unsupported,true);assert.equal(state.s1.components.safe.text,'仍可阅读');
});
test('builds an explicit action with current bound input, without forwarding the entire model',()=>{
  const surface={surfaceId:'s1',dataModel:{question:'复核任务',private:'do not send'}};
  const event=buildUiAction(surface,{id:'followup-0',component:'Button',action:{event:{name:'FOLLOW_UP',context:{referenceIndex:0,question:{path:'/question'}}}}},'2026-10-28T03:00:00Z');
  assert.deepEqual(event,{name:'FOLLOW_UP',surfaceId:'s1',sourceComponentId:'followup-0',timestamp:'2026-10-28T03:00:00Z',context:{referenceIndex:0,question:'复核任务'}});
});
test('checks all catalog component families and bounded rows data',()=>{
  const nodes=[{id:'root',component:'Column',children:['metric','table','chart','tabs','progress','status','form']},{id:'metric',component:'Metric',label:'图片',value:12},{id:'table',component:'DataTable',columns:[{key:'name',label:'名称'}],rows:{path:'/rows'}},{id:'chart',component:'BarChart',title:'缺陷',points:[]},{id:'tabs',component:'Tabs',tabs:[{title:'说明',child:'label'}]},{id:'label',component:'Text',text:'原始数据'},{id:'progress',component:'Progress',label:'处理',value:1,total:2},{id:'status',component:'Status',label:'处理中',tone:'info'},{id:'form',component:'Form',children:['field','button']},{id:'field',component:'TextField',label:'问题',value:{path:'/question'},required:true},{id:'button',component:'Button',label:'继续',action:{event:{name:'FOLLOW_UP',context:{question:{path:'/question'}}}}}];
  assert.equal(Object.keys(applyA2uiMessage(create(),components(nodes)).s1.components).length,nodes.length);
  assert.throws(()=>readA2uiMessages(Array(65).fill({})),/数量/);
});
