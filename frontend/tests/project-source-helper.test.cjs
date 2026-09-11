const test = require('node:test')
const assert = require('node:assert/strict')

const { readFrontendFile, readProjectFile } = require('./helpers/project-source.cjs')

test('公共源码助手可以读取项目根目录和前端目录文件', () => {
  assert.match(readProjectFile('pom.xml'), /<artifactId>DoorHandleCatch<\/artifactId>/)
  assert.match(readFrontendFile('package.json'), /"name"\s*:\s*"door-handle-frontend"/)
  assert.throws(
    () => readFrontendFile('missing-contract-source.vue'),
    /ENOENT|missing-contract-source\.vue/
  )
})
