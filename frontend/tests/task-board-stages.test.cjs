const test = require('node:test')
const assert = require('node:assert/strict')
const { importFrontendModule } = require('./helpers/project-source.cjs')

test('the recorded model outcome and human review are independent for each batch', async () => {
  const { modelStep, humanStep, canReview } = await importFrontendModule('src','utils','taskBoardStages.js')
  for (const [modelStatus, listPhase, reviewStatus, flow, model, human, actionable] of [
    ['READY','READY','PENDING','PENDING_DETECTION','待启动检测','未进入校验',false],
    ['DETECTING','DETECTING','PENDING','PENDING_REVIEW','检测中','未进入校验',false],
    ['FAILED','FAILED','PENDING','PENDING_REVIEW','检测失败','未进入校验',false],
    ['COMPLETED','MODEL_DONE',null,null,'检测完成','无校验记录',false],
    ['COMPLETED','MODEL_DONE','SKIPPED',null,'检测完成','已跳过校验',false],
    ['PARTIAL_FAILED','WAITING_CHECK','PENDING','PENDING_REVIEW','部分检测失败','待人工校验',true],
    ['COMPLETED','VERIFYING','PENDING','REVIEWING','检测完成','校验中',true],
    ['COMPLETED','CHECKED','REVIEWED','CONFIRMED','检测完成','校验完成',false],
    ['COMPLETED','FOLLOW_UP','REVIEWED','RECHECK_REQUIRED','检测完成','校验待跟进',false]
  ]) {
    const row = {modelStatus,listPhase,reviewStatus,flow}
    assert.equal(modelStep(row),model)
    assert.equal(humanStep(row),human)
    assert.equal(canReview(row),actionable)
  }
})
