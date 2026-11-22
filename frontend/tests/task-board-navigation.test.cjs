const test = require('node:test')
const assert = require('node:assert/strict')
const { importFrontendModule } = require('./helpers/project-source.cjs')
const navigation = importFrontendModule('src', 'utils', 'taskBoardNavigation.js')

test('the employee inbox defaults to actionable work while existing targeted links retain their scope', async () => {
  const { employeeInbox } = await navigation
  assert.equal(employeeInbox({}), true)
  for (const query of [{keyword:'批次'}, {phase:'DONE'}, {directory:'detection/班次/'}, {assignedTaskId:'abc'}, {page:'2'}, {inbox:'0'}]) {
    assert.equal(employeeInbox(query), false)
  }
  assert.equal(employeeInbox({inbox:'1',keyword:'班次',page:'2'}), true)
  assert.equal(employeeInbox({boardAction:'review',taskId:'abc'}), true)
})

test('a board action keeps the list scope, page and search on close, with no external target', async () => {
  const { listLocation } = await navigation
  const filters = {inbox:'1',phase:'VERIFYING',keyword:'检测 A',page:'3'}
  const query = {...filters, boardAction:'review', taskId:'det_12'}
  assert.deepEqual(listLocation({path:'/inspection/tasks',query,hash:''}),{path:'/inspection/tasks',query:filters,hash:''})
  assert.equal(query.boardAction, 'review')
})

test('only suitable dialogs open from upload lists and employee lists', async () => {
  const { boardDialog } = await navigation
  for (const [action, supervisor, uploads, valid] of [
    ['images',false,true,true], ['images',false,false,false], ['assign',false,false,false],
    ['assign',true,false,true], ['assign',true,true,false], ['review',false,false,true],
    ['disposition',false,false,true], ['rework',true,false,true], ['rework',false,true,false],
    ['trace',true,false,true], ['unknown',true,false,false]
  ]) {
    assert.deepEqual(boardDialog({boardAction:action,taskId:'det-12'},supervisor,uploads), valid ? {action,taskId:'det-12'} : null)
  }
  for(const taskId of ['', ['x','y'], 'evil/path', null, 'a'.repeat(129)]) assert.equal(boardDialog({boardAction:'trace',taskId},true,false),null)
})

test('上传记录的进度入口直接打开同一批次并保留可返回的列表',async()=>{
  const {assignedTrace,boardDialog,listLocation,employeeInbox}=await navigation
  const route=assignedTrace('sample_batch')
  assert.deepEqual(boardDialog(route.query,false,false),{action:'trace',taskId:'sample_batch'})
  assert.equal(employeeInbox(route.query),false)
  assert.deepEqual(listLocation(route).query,{keyword:'sample_batch',inbox:'0'})
})
