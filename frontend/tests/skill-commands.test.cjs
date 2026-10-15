const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const source = fs.readFileSync(path.join(__dirname, '../src/utils/skillCommands.js'), 'utf8')
const modulePromise = import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
const skill = (name, n=1) => ({name, skillId:'skill-00000000-0000-0000-0000-'+String(n).padStart(12,'0'), version:1, description:'经审核的任务查询经验'})

test('link-install completion is shown only when backend supports confirmation navigation', async () => {
  const {filterSkillCommands,skillCommandOptions}=await modulePromise
  assert.ok(!skillCommandOptions({skills:[],externalInstallSupported:false}).some(o=>o.value==='/skills install '))
  const catalog={skills:[],externalInstallSupported:true}
  assert.equal(filterSkillCommands(catalog,'/skills ins')[0].value,'/skills install ')
  assert.deepEqual(filterSkillCommands(catalog,'/skills install https://github.com/example'),[])
})

test('duplicate or reserved names require exact skill IDs and cannot replace built-in commands', async () => {
  const {skillCommandOptions}=await modulePromise
  const options=skillCommandOptions({skills:[skill('task-guide'),skill('task-guide',2),skill('skills',3)]})
  assert.equal(options.filter(o=>o.value==='/skills').length,1)
  assert.equal(options.filter(o=>o.selector).length,3)
  assert.ok(options.filter(o=>o.selector).every(o=>o.value.startsWith('/skill skill-')))
})
test('completion does not expose malformed entries or attempt to complete ordinary messages and question arguments', async () => {
  const {filterSkillCommands,skillCommandOptions}=await modulePromise
  const catalog={skills:[skill('task-guide'),{...skill('bad-guide'),skillId:'../private'},{...skill('wrong-role'),version:0}]}
  assert.equal(skillCommandOptions(catalog).filter(o=>o.selector).length,1)
  assert.equal(filterSkillCommands(catalog,'/ta')[0].value,'/task-guide ')
  assert.equal(filterSkillCommands(catalog,'/skill ta')[0].value,'/skill task-guide ')
  assert.deepEqual(filterSkillCommands(catalog,'查询任务'),[])
  assert.deepEqual(filterSkillCommands(catalog,'/task-guide 查询进度'),[])
  assert.ok(filterSkillCommands({skills:[]},'/').some(o=>o.value==='/help'))
})
