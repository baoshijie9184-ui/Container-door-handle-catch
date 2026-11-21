const test = require('node:test')
const assert = require('node:assert/strict')
const { importFrontendModule } = require('./helpers/project-source.cjs')

test('isolated batch names omit the generated suffix while navigation can use the original key', async () => {
  const { imageFolderLabel, recordFolderLabel } = await importFrontendModule('src', 'utils', 'imageFolderLabel.js')
  const batch = '车间 A_早班_det_20261120_123405_abc01234'
  for (const role of ['员工上传/DET-0001', '主管上传/SUP-0001']) {
    const path = 'detection/图片上传/' + role + '/' + batch + '/'
    assert.equal(imageFolderLabel(path), '车间 A_早班')
    assert.equal(imageFolderLabel(path + 'Original/'), '车间 A_早班')
    assert.equal(recordFolderLabel({ taskType:'OSS_FOLDER', folder:batch, prefix:path }), '车间 A_早班')
  }
  assert.equal(imageFolderLabel('detection/旧目录/' + batch + '/Original/'), batch)
})

test('registered names take precedence and legacy, unnamed and shared records have compact labels', async () => {
  const { recordFolderLabel } = await importFrontendModule('src', 'utils', 'imageFolderLabel.js')
  assert.equal(recordFolderLabel({ folder:'门把手检测批次 15', prefix:'detection/旧目录/内部名称/Original/' }), '门把手检测批次 15')
  assert.equal(recordFolderLabel({ prefix:'detection/历史批次/originals/' }), '历史批次')
  assert.equal(recordFolderLabel({ prefix:'C:\\旧设备\\上传\\夜班\\' }), '夜班')
  assert.equal(recordFolderLabel({ folder:'员工目录/班次乙', prefix:null }), '班次乙')
  assert.equal(recordFolderLabel({ folder:null, prefix:null }), '未命名文件夹')
  assert.equal(recordFolderLabel({ folderName:'上海市 / 检测组 / 早班' }), '早班')
  assert.equal(recordFolderLabel({ captureInfo:{imageFolderName:'晚班'},folderName:'旧名' }), '晚班')
  assert.equal(recordFolderLabel({ sourceOssPrefix:'detection/旧数据/夜班/Original/' }), '夜班')
})
