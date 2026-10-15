const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const source=fs.readFileSync(path.join(__dirname,'../src/utils/skillInstallNavigation.js'),'utf8')
const modulePromise=import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
test('installation links use configured business site and preserve encoded source without triggering download',async()=>{
  const {skillInstallNavigation}=await modulePromise
  const url='https://modelscope.cn/skills/@anthropics/skill-creator'
  const result=skillInstallNavigation('尚未下载 [确认下载](/#/agent/skills?installUrl='+encodeURIComponent(url)+') 审核后启用','https://business.example/#/login')
  assert.equal(result.label,'确认下载');assert.equal(new URL(result.href).origin,'https://business.example');assert.equal(new URLSearchParams(result.route.split('?')[1]).get('installUrl'),url)
  assert.equal(result.before,'尚未下载 ');assert.equal(result.after,' 审核后启用')
})
test('unrelated text private sources credentials and arbitrary pages cannot become installation links',async()=>{
  const {skillInstallNavigation}=await modulePromise
  for(const url of ['http://127.0.0.1/secret','https://github.com@evil.example/a/b','javascript:alert(1)','https://github.com/a/b/tree/main/skill?token=secret'])
    assert.equal(skillInstallNavigation('[安装](#/agent/skills?installUrl='+encodeURIComponent(url)+')','https://business.example'),null)
  assert.equal(skillInstallNavigation('[其他](#/quality/reports)','https://business.example'),null)
})
