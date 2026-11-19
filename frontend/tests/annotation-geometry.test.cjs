const test=require('node:test'), assert=require('node:assert/strict')
const {importFrontendModule}=require('./helpers/project-source.cjs')
const modulePromise=importFrontendModule('src','utils','annotationGeometry.js')
test('move preserves both extents when dragging past image boundaries',async()=>{
  const {moveBox}=await modulePromise, original=[10.5,20,45.5,60]
  assert.deepEqual(moveBox(original,'move',-400,600,100,80),[0,40,35,80])
  assert.deepEqual(original,[10.5,20,45.5,60])
})
test('each resize corner anchors the opposite side even when crossed',async()=>{
  const {moveBox}=await modulePromise, box=[10,20,40,60]
  assert.deepEqual(moveBox(box,'nw',50,100,100,80),[39,59,40,60])
  assert.deepEqual(moveBox(box,'se',100,100,100,80),[10,20,100,80])
  assert.deepEqual(moveBox(box,'ne',3,-4,100,80),[10,16,43,60])
  assert.deepEqual(moveBox(box,'sw',-6,7,100,80),[4,20,40,67])
})
