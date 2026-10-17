const test=require('node:test'),assert=require('node:assert/strict');
const {readFrontendFile}=require('./helpers/project-source.cjs');
const mod=import('data:text/javascript;base64,'+Buffer.from(readFrontendFile('src','utils','beijingTime.js')).toString('base64'));
test('business dates use UTC+8 regardless of browser host timezone and retain explicit offsets',async()=>{
 const {businessDate,beijingClock,relativeBeijingTime,beijingDateTime,beijingExportStamp}=await mod;
 for(const zone of ['UTC','America/Los_Angeles','Asia/Shanghai']){const original=process.env.TZ;process.env.TZ=zone;try{
  assert.equal(businessDate('2026-10-18 00:10:00').toISOString(),'2026-10-17T16:10:00.000Z');
  assert.equal(beijingClock('2026-10-17T16:10:00Z'),'00:10');assert.equal(beijingClock('2026-10-18T00:10:00+08:00'),'00:10');assert.equal(beijingClock('2026-10-18 00:10:00'),'00:10');
  assert.equal(beijingDateTime('2026-10-17T16:10:00Z'),'2026-10-18 00:10:00');assert.equal(beijingExportStamp(new Date('2026-10-17T16:10:00Z')),'20261018-001000');
  assert.equal(relativeBeijingTime('2026-10-18 00:10:00',Date.parse('2026-10-17T16:10:15Z')),'刚刚');assert.equal(relativeBeijingTime('2026-10-18 00:10:00',Date.parse('2026-10-17T16:15:00Z')),'5 分钟前');
 }finally{if(original===undefined)delete process.env.TZ;else process.env.TZ=original}}
 assert.equal(businessDate(''),null);assert.equal(businessDate('not-a-date'),null);assert.equal(businessDate('2026-10-18'),null);
 assert.notEqual(relativeBeijingTime('2026-10-18 04:10:00',Date.parse('2026-10-17T16:10:00Z')),'刚刚');
});
