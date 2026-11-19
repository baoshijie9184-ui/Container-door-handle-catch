const test=require('node:test'), assert=require('node:assert/strict')
const {importFrontendModule}=require('./helpers/project-source.cjs')
const actions=importFrontendModule('src','utils','workspaceActions.js')
test('常用操作按角色和实际菜单过滤，支持用户常用的动作词',async()=>{
  const {findWorkspaceActions,homeActions}=await actions
  const groups=[{label:'业务',items:[
    {path:'/inspection/history',label:'检测记录'},
    {path:'/employees',label:'人员管理'},
    {path:'/quality/reports',label:'报告与审批'},
    {path:'/agent/model-quotas',label:'模型与额度'}
  ]}]
  assert.equal(findWorkspaceActions(groups,'INSPECTOR','看图')[0].path,'/inspection/history')
  assert.equal(findWorkspaceActions(groups,'SUPERVISOR','查人')[0].path,'/employees')
  assert.deepEqual(findWorkspaceActions(groups,'INSPECTOR','分配员工额度'),[])
  assert.deepEqual(findWorkspaceActions(groups,'INSPECTOR','新增人员'),[])
  assert.equal(findWorkspaceActions(groups,'SUPERVISOR','审批质检报告')[0].query.status,'SUBMITTED')
  assert.deepEqual(findWorkspaceActions([],'SUPERVISOR',''),[])
  assert.ok(homeActions(false).every(a=>!a.label.includes('审批')))
})
