import {beijingDateTime} from './beijingTime'
export const skillTime=value=>value?beijingDateTime(value)||'时间格式未知':'未记录'
export function skillMaintenance(row){
 const active=Array.isArray(row?.versions)?row.versions.find(version=>version.version===row.activeVersion):null
 if(active?.evidence?.sourceType==='EXTERNAL_UPLOAD')return {code:'LEGACY',label:'历史上传已停用'}
 if(row?.lifecycle==='ARCHIVED')return {code:'ARCHIVED',label:'已停用'}
 if(row?.activeVersion==null)return {code:'UNPUBLISHED',label:'未发布'}
 if(row.lifecycle==='STALE')return {code:'STALE',label:'待维护'}
 if(row.lifecycle==='ACTIVE')return {code:'ACTIVE',label:'发布在用'}
 return {code:'UNKNOWN',label:'维护状态未记录'}
}
export function readSkillView(value){
 if(!value||typeof value.skillId!=='string'||!Array.isArray(value.versions)||!Array.isArray(value.evaluations)||!Array.isArray(value.audit)
  ||value.versions.some(version=>!version||!Array.isArray(version.tools)||!version.evidence||typeof version.evidence!=='object'||Array.isArray(version.evidence)))throw Error('技能资料未完整返回，请重新读取；未推断审核或工具权限')
 return value
}
export function skillRuleState(value){return value===true?'PASSED':value===false?'FAILED':'UNKNOWN'}
export const skillRuleLabel=value=>({PINNED_SOURCE_AND_FILE_DIGEST:'固定来源与文件摘要',LICENSE_PRESERVED:'许可证保留',CONTENT_BOUNDS:'内容范围与长度',NO_ADDITIONAL_TOOLS:'未增加越界工具',NO_SECRETS_OR_PERMISSION_BYPASS:'敏感信息及权限绕过规则',ROLE_TOOL_ALLOWLIST:'角色工具白名单',SOURCE_SUCCESSFUL_TOOLS:'来源成功工具匹配',NO_EXECUTABLE_OR_SECRET_PATTERNS:'可执行内容及敏感模式规则',SDK_SKILL_METADATA:'SDK 技能元数据'})[value]||value
