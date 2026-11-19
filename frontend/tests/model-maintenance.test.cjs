const test = require('node:test'), assert = require('node:assert/strict')
const {importFrontendModule}=require('./helpers/project-source.cjs')
const modulePromise=importFrontendModule('src','utils','modelMaintenance.js')
test('image advice matches the actual source even when two images share a file name',async()=>{
  const {imageMaintenance}=await modulePromise
  const summary={groups:[{label:'维修',categories:[{code:'Bent',label:'弯曲'}]},
    {label:'替换',categories:[{code:'Missing',label:'缺失'}]}]}
  const pair={name:'a.jpg',ambiguous:true,original:{objectKey:'detection/a/a.jpg'}}
  const targets=[{imageName:'a.jpg',sourceKey:pair.original.objectKey,defectType:'Bent'},
    {imageName:'a.jpg',sourceKey:'detection/b/a.jpg',defectType:'Missing'},
    {imageName:'a.jpg',defectType:'Bent'}]
  assert.deepEqual(imageMaintenance(summary,targets,pair),[{label:'弯曲',action:'维修',count:1}])
  assert.deepEqual(imageMaintenance(summary,[],pair),[])
})
