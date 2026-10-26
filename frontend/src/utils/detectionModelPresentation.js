import {beijingDateTime} from './beijingTime.js'
import {knownCount} from './countPresentation.js'
export const modelTime=value=>value?beijingDateTime(value)||'时间格式未知':'未记录'
export function modelMetricNumber(value){if(!['number','string'].includes(typeof value)||typeof value==='string'&&!value.trim())return undefined;const number=Number(value);return Number.isFinite(number)&&number>=0&&number<=1?number:undefined}
export const modelPrimaryMetricFields = [['mapScore','mAP（AP）']]
export const modelLegacyMetricFields = [['precisionScore','Precision'],['recallScore','Recall'],['f1Score','F1']]
export function modelMetric(value){const number=modelMetricNumber(value);return number==null?'—':(number*100).toFixed(2)+'%'}
export function modelMilliseconds(value){const number=knownCount(value);return number==null?'未记录':number.toLocaleString('zh-CN')+' ms'}
export const MODEL_FPS_MAX = 99999999.9999
export function modelFpsNumber(value){
 if(!['number','string'].includes(typeof value)||typeof value==='string'&&!value.trim())return undefined
 const number=Number(value)
 return Number.isFinite(number)&&number>0&&number<=MODEL_FPS_MAX?number:undefined
}
export const modelFps=value=>value==null?'未记录':modelFpsNumber(value)==null?'待核对':modelFpsNumber(value).toLocaleString('zh-CN',{maximumFractionDigits:4})+' 张/秒'
export function modelTrainingImages(value){const number=knownCount(value);return value==null?'未记录':number==null||number===0?'待核对':number.toLocaleString('zh-CN')+' 张'}
export function modelNoDetection(model={}){
 const images=knownCount(model.evaluationImageCount),empty=knownCount(model.noDetectionImageCount)
 if(model.evaluationImageCount==null||model.noDetectionImageCount==null)return {value:'未记录',description:'成功评估图片数与整图未检出图片数需同时登记'}
 if(images==null||empty==null||empty>images)return {value:'待核对',description:'图片计数无效或不一致'}
 if(images===0)return {value:'无法统计',description:'没有成功评估的图片'}
 return {value:(empty/images*100).toFixed(2)+'%',description:`${empty.toLocaleString('zh-CN')} / ${images.toLocaleString('zh-CN')} 张成功评估图片`}
}
export const modelUsage=value=>knownCount(value)?.toLocaleString('zh-CN')??'—'
export function modelStrategy(model={}){
 const label=({FULL:'全量',CANARY:'灰度',AB_TEST:'A/B 对比',ROLLBACK:'回滚'})[model.deploymentStrategy]
 if(!label)return model.deploymentStrategy||'策略未记录'
 if(model.deploymentStrategy==='CANARY'){const percent=knownCount(model.canaryPercent);return label+' · '+(percent!=null&&percent<=100?percent+'%':'比例未记录')}
 if(model.deploymentStrategy==='AB_TEST')return label+' · '+(model.abGroup||'分组未记录')
 if(model.deploymentStrategy==='ROLLBACK')return label+' · 来源 '+(model.rollbackFromModelId??'未记录')
 return label
}
export function modelDefault(value){if(value===true||value===1)return '是';if(value===false||value===0)return '否';return '未记录'}
export function modelNextStep(model={}){
 if(model.status==='ARCHIVED')return '模型已归档，可核对历史资料与操作记录。'
 if(model.validationStatus==='FAILED')return '基础校验未通过，请核对文件和校验说明，必要时重新校验。'
 if(model.validationStatus!=='PASSED')return '基础校验结果尚未确认，请先核对文件及检查记录。'
 if(model.status==='PUBLISHED')return '模型已发布，具体任务使用哪个版本仍以检测任务记录为准。'
 return '基础校验已通过。效果评估、模型发布与默认选择仍需分别核对。'
}
