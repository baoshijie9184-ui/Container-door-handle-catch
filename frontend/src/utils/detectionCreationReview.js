const uuid=value=>typeof value==='string'&&/^[a-f0-9-]{36}$/.test(value)
const integer=value=>Number.isSafeInteger(value)&&value>=0
// Accept the existing raw DTOs and the project's Result envelope. HTTP 200 is not a business success.
export function transferPayload(value){
 if(value&&typeof value==='object'&&!Array.isArray(value)&&Object.hasOwn(value,'code')){
  if(value.code!==200){const error=new Error('检测创建核对未返回成功回执');error.status=Number.isInteger(value.code)&&value.code>=400&&value.code<600?value.code:502;throw error}
  return value.data
 }
 return value
}
export function transferFailureStatus(error){
 const http=error?.response?.status,code=error?.response?.data?.code
 return http>=400?http:code>=400&&code<600?code:error?.status
}
export function transferCapability(value){
 const caps=transferPayload(value)
 if(!caps||typeof caps!=='object'||Array.isArray(caps))throw new Error('核对能力响应无效')
 if(caps.enabled===false||caps.detectionCreationReviews===false)return 'DISABLED'
 if(caps.detectionCreationReviews===true)return 'SUPPORTED'
 if(caps.detectionCreationReviews!=null)throw new Error('核对能力响应无效')
 return 'UNKNOWN'
}
export function transferReadIssue(error,hasSnapshot=false){
 const status=transferFailureStatus(error),clear=[401,403,404].includes(status)
 if(status===404)return {clear:true,availability:'MISSING',message:'核对接口未提供或当前会话不可访问。请核对后端版本和账号范围；没有确认任何检测创建结果。'}
 if(status===401)return {clear:true,availability:'',message:'登录状态已失效，已清除旧核对资料，请重新登录后读取。不会重发原操作。'}
 if(status===403)return {clear:true,availability:'',message:'当前账号无权读取这些核对资料，已清除旧内容。不会重发原操作。'}
 return {clear,availability:'',message:'核对状态暂不可读取，请刷新后再操作。'+(hasSnapshot?'已显示内容仅为上次快照。':'')+'不会重发原操作。'}
}
export const transferDisabledMessage='此环境未启用检测创建核对。普通对话可继续使用；启用前需要核对后端配置与迁移。'
export const transferLabels={NEEDS_REVIEW:'待核对',QUEUED:'已提交检测',CANCELLED:'已终止',PREPARING:'准备中',UPLOADING:'传输中'}
export const checkLabels={QUEUED:'等待核对',RUNNING:'核对中',VERIFIED:'内容一致',INCOMPLETE:'内容不齐或不一致',UNCONFIRMED:'核对未完成',CANCELLED:'核对已终止'}
export function validTransferReview(value){return !!value&&uuid(value.commandId)&&typeof value.taskId==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(value.taskId)&&Object.hasOwn(transferLabels,value.status)&&integer(value.revision)&&integer(value.images)&&integer(value.acknowledged)&&value.acknowledged<=value.images&&typeof value.manifestAvailable==='boolean'&&typeof value.canFinalize==='boolean'&&(value.checkId==null||uuid(value.checkId))&&(value.checkStatus==null||Object.hasOwn(checkLabels,value.checkStatus))&&integer(value.checked)&&integer(value.verified)&&value.verified<=value.checked&&value.checked<=value.images}
export function canCheckTransfer(value){return value.status==='NEEDS_REVIEW'&&value.manifestAvailable&&!['QUEUED','RUNNING'].includes(value.checkStatus)}
export function transferDecision(action){return action==='FINALIZE'?'确认沿用原图片、参数和派发编号完成创建？提交时会重新核对账号与来源权限 不会重新上传图片':'确认终止此创建命令？已上传或结果不明的对象会保留 不删除文件 不释放尚未核实的传输预留'}
export const transferCount = value => integer(value) ? value.toLocaleString('zh-CN') : '未记录'
export function transferNextStep(row, verified) {
 if (!verified) return '请先刷新状态，核对当前版本后再操作。刷新不会重发原业务操作。'
 if (row.status === 'QUEUED') return '原命令已提交检测，不代表推理完成。实际结果请到检测记录查看。'
 if (row.status === 'CANCELLED') return '创建已终止，原对象及审计保留。不确定的传输仍保留预留，未被当作已删除。'
 if (row.status === 'PREPARING') return '正在准备创建资料。可刷新核对当前阶段，不要重复提交创建。'
 if (row.status === 'UPLOADING') return '原命令正在传输图片。可刷新核对状态，当前页面不会自动重传。'
 if (!row.manifestAvailable) return '旧命令没有完整目标清单，无法安全核对或完成创建；可本人确认终止并保留原证据。'
 if (['QUEUED', 'RUNNING'].includes(row.checkStatus)) return '已有只读核对等待或执行中。请刷新原核对状态，不要再次提交相同核对。'
 if (row.canFinalize) return '本次回执允许申请完成原创建，仍需本人明确确认；提交时会重新校验账号、来源、版本和核对证据。'
 if (row.checkStatus === 'VERIFIED') return '上次核对内容一致，但本次回执未允许完成创建。证据可能已过期或版本变化，请重新核对。'
 if (row.checkStatus === 'INCOMPLETE') return '上次核对内容不齐或不一致。请核对原资料；不会据此自动重传图片或重新创建。'
 if (row.checkStatus === 'UNCONFIRMED') return '上次核对未完成，不能据此判断图片未上传。可重新发起只读核对或明确终止原创建。'
 if (row.checkStatus === 'CANCELLED') return '上次核对已终止，原创建仍待处理。可重新只读核对，或明确终止原创建。'
 return '尚无可用于完成创建的核对回执，请先只读核对原传输结果。'
}
export function transferDecisionSnapshot(row, action) {
 return Object.freeze({ id: row.commandId, revision: row.revision, checkId: row.checkId ?? null, action })
}
export function transferDecisionMatches(decision, row) {
 return decision?.id === row.commandId && decision.revision === row.revision && decision.checkId === (row.checkId ?? null)
}
