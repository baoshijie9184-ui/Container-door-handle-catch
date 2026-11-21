const test = require('node:test')
const assert = require('node:assert/strict')
const { importFrontendModule } = require('./helpers/project-source.cjs')

const files = [{relativePath:'批次/门左/a.jpg'}, {relativePath:'批次/门右/a.jpg'}]

test('imports capture fields and attaches notes to full folder-relative paths', async () => {
  const { folderRoot, parseUploadMetadata } = await importFrontendModule('src', 'utils', 'uploadMetadata.js')
  const root = folderRoot(files)
  assert.equal(root, '批次')
  const input = {
    schemaVersion:1,
    captureInfo:{captureDate:'2026-11-21',collector:'EMP-01'},
    notes:'批次登记',
    images:[{path:'门右/a.jpg',notes:'右侧',attributes:{位置:'右门'}}]
  }
  assert.deepEqual(parseUploadMetadata('\uFEFF'+JSON.stringify(input),files,root), {
    captureInfo:input.captureInfo,notes:input.notes,images:input.images
  })
})

test('rejects invalid dates, unknown keys and image references outside the chosen batch', async () => {
  const { parseUploadMetadata } = await importFrontendModule('src', 'utils', 'uploadMetadata.js')
  const parse = data => parseUploadMetadata(JSON.stringify(data),files,'批次')
  assert.throws(()=>parse({captureInfo:{captureDate:'2026-02-31'}}), /有效/)
  assert.throws(()=>parse({captureInfo:{city:'武汉市'}}), /未识别/)
  assert.throws(()=>parse({images:[{path:'a.jpg'}]}), /相对路径/)
  assert.throws(()=>parse({images:[{path:'../a.jpg'}]}), /相对路径/)
  assert.throws(()=>parse({images:[{path:'门左/a.jpg'},{path:'门左/a.jpg'}]}), /重复/)
  assert.throws(()=>parse({images:[{path:'门左/a.jpg',attributes:{位置:{latitude:10}}}]}), /文本/)
})
