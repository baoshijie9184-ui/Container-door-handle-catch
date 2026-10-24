import { beijingDateTime } from './beijingTime'
import { knownCount } from './countPresentation'

const domains = { DETECTION:'检测任务', QUALITY_REPORT:'质检报告', DEVICE:'设备', DEVICE_USAGE:'设备使用', EMPLOYEE:'人员', ORGANIZATION:'账号与组织', DETECTION_MODEL:'检测模型', DETECTION_MODEL_FILE:'模型文件', MODEL_CONFIG:'Agent 模型配置', DETECTION_IDENTITY_SOURCE:'任务身份来源' }
export const auditDomainOptions=Object.entries(domains).map(([value,label])=>({value,label}))
export const auditDomainLabel = value => domains[value] || value || '业务域未记录'
export const auditScopeLabel = value => ({ENTERPRISE:'企业业务',PRIVATE:'本人私有'})[value] || '范围未记录'
export const auditTime = value => value ? beijingDateTime(value) || '时间格式未知' : '未记录'
export const auditValue = value => value == null || value === '' ? '未记录' : value
export function deliveryBytes(row) {
  if(row.state==='REDIRECT_AUTHORIZED')return '未观测'
  if(['HEAD_AUTHORIZED','HEAD_COMPLETED'].includes(row.state))return 'HEAD 无正文'
  const bytes=knownCount(row.accepted_bytes_lower_bound)
  return bytes===null?'未知':'至少 '+bytes.toLocaleString('zh-CN')+' B'
}
export function deliveryExpectedBytes(row) {
  const bytes=knownCount(row.expected_bytes)
  return bytes===null?'未知':bytes.toLocaleString('zh-CN')+' B'
}
export function deliveryStateHint(state) {
  return ({
    AUTHORIZED:'记录显示读取已授权，尚无服务端响应完成回执。可刷新此列表核对，不据此判断文件已收到。',
    HEAD_AUTHORIZED:'本次只授权读取响应头，不包含文件正文。',
    HEAD_COMPLETED:'本次响应头处理已完成，没有传输文件正文。',
    STREAMING:'最近记录为服务端写出中，可刷新交付状态核对；这不是浏览器接收进度。',
    SERVER_COMPLETED:'服务端响应已完成。请在浏览器下载记录中确认文件，不能据此证明浏览器已经收到。',
    INTERRUPTED:'本次响应记录为中断，请核对原业务和浏览器下载记录；系统不会在此自动重复下载。',
    UNKNOWN:'结果尚未确认，请刷新交付记录核对。未知结果不作为重新执行业务操作的依据。',
    REDIRECT_AUTHORIZED:'仅签发了外部读取授权，后续 OSS 传输未在此观测。'
  })[state] || '交付状态尚未核对，请保留响应编号并刷新查看，不根据缺失记录推断结果。'
}
export function auditPageLink(domain) {
  return ({DEVICE:'/devices',DEVICE_USAGE:'/device-records',EMPLOYEE:'/employees',ORGANIZATION:'/organization',DETECTION:'/inspection/history',QUALITY_REPORT:'/quality/reports',DETECTION_MODEL:'/models',DETECTION_MODEL_FILE:'/models'})[domain] || ''
}
