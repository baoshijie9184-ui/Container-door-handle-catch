const test=require('node:test'),assert=require('node:assert/strict');
const {readFrontendFile}=require('./helpers/project-source.cjs');
const mod=import('data:text/javascript;base64,'+Buffer.from(readFrontendFile('src','utils','agentActions.js')).toString('base64'));
const retry=()=>({actionId:'action-1',version:1,status:'PENDING',operation:'RETRY_DETECTION',retry:{taskId:'task-1',resourceVersion:'a'.repeat(64),status:'FAILED',flowStatus:null,impact:'clears previous results',imageCount:2}});
test('a known retry DTO permits absent legacy flow and binds any completion receipt to its exact task',async()=>{
 const {validAgentAction:valid}=await mod;const value=retry();assert.equal(valid(value),true);
 value.status='SUCCEEDED';value.execution={taskId:'other',operation:'RETRY',dispatchId:'dispatch-1',status:'QUEUED'};assert.equal(valid(value),false);
 value.execution.taskId='task-1';assert.equal(valid(value),true);value.execution.status='COMPLETED';assert.equal(valid(value),false);
});
test('missing payload, unknown operation/status, invalid IDs and stale DTO shapes fail closed',async()=>{
 const {validAgentAction:valid}=await mod;
 for(const value of [undefined,null,{},[],{code:404,message:'not found'},{...retry(),version:0},{...retry(),status:'PAID'},{...retry(),operation:'RUN_SHELL'},{...retry(),retry:null},{...retry(),actionId:'../foreign'},{...retry(),retry:{...retry().retry,imageCount:0}},{...retry(),retry:{...retry().retry,resourceVersion:'old'}}])assert.equal(valid(value),false);
});
test('old assignment cards remain supported without permitting a retry to be interpreted as assignment',async()=>{
 const {validAgentAction:valid}=await mod;
 const value={actionId:'old-1',version:2,status:'SUCCEEDED',operation:'ASSIGN_QUALITY_TASK',command:{taskId:'task-1',qualityStation:'A',assignee:'alice'},before:{}};
 assert.equal(valid(value),true);assert.equal(valid({...value,before:null}),false);assert.equal(valid({...value,operation:'RETRY_DETECTION'}),false);
});
