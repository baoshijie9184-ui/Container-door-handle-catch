<template><el-button size="small" :disabled="user.capabilities?.sessionTracking!==true||user.capabilities?.mutations!==true" @click="open">登录权限</el-button><el-dialog v-model="visible" title="账号登录权限" width="min(520px,94vw)" append-to-body :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy"><p>{{ account.username }} · 账号 {{ account.userId }}</p><p class="access-note">岗位档案与登录权限分别管理 仅主管和符合资格的检测人员可登录</p><el-alert v-if="error" :title="error" type="warning" :closable="false"/><form v-if="snapshot" class="access-form" @submit.prevent="save"><label>系统角色<el-select v-model="draft.role" :disabled="busy||!!command||conflict"><el-option label="主管" value="SUPERVISOR"/><el-option label="检测人员" value="INSPECTOR"/></el-select></label><label>允许登录<el-switch v-model="draft.enabled" :disabled="busy||!!command||conflict"/></label><p class="access-note">读取时版本 {{ snapshot.version }} 本人和最后一名主管的保护由服务端再次核对</p><p v-if="command" class="access-note">结果未确认 重试沿用请求 {{ command.requestId }}</p><div class="access-actions"><el-button :disabled="busy" @click="visible=false">返回</el-button><el-button v-if="conflict" :disabled="busy" @click="open">重新读取权限</el-button><el-button native-type="submit" type="primary" :loading="busy" :disabled="conflict">{{ command?'重试原操作':'确认保存权限' }}</el-button></div></form></el-dialog></template>
<script setup>
import { reactive, ref } from 'vue'
import { useUserStore } from '../stores/user'
import { captureAccountRequest } from '../api/request'
const request=captureAccountRequest()
import { useAccountOperationScope } from '../composables/useAccountOperationScope'
import { createUiRequestId } from '../utils/requestIdentity'
import { decimalVersion } from '../utils/mutationVersion'
const props=defineProps({account:{type:Object,required:true}}),emit=defineEmits(['updated'])
const user=useUserStore()
const visible=ref(false),snapshot=ref(null),busy=ref(false),error=ref(''),command=ref(null),conflict=ref(false),draft=reactive({enabled:true,role:'INSPECTOR'})
const scope=useAccountOperationScope(()=>{visible.value=false;snapshot.value=null;command.value=null}),reader=scope.channel()
const unwrap=response=>response.data?.code===200?response.data.data:response.data
async function open(){
 if(busy.value)return
 const token=reader.begin();visible.value=true;error.value='';snapshot.value=null;command.value=null;conflict.value=false
 try{const value=unwrap(await request.get('/api/accounts/'+encodeURIComponent(props.account.userId)+'/access',{signal:token.signal}));if(!reader.current(token))return;const version=decimalVersion(value?.accountVersion??value?.version);if(version===null||!['SUPERVISOR','INSPECTOR'].includes(value.role)||typeof value.enabled!=='boolean')throw new Error('账号权限与版本未完整读取');snapshot.value=Object.freeze({...value,version});Object.assign(draft,{enabled:value.enabled,role:value.role})}
 catch(failure){if(reader.current(token))error.value=failure.response?.data?.message||failure.message||'账号权限暂不可读取'}
}
async function save(){
 if(busy.value||!snapshot.value||conflict.value)return
 if(user.capabilities?.sessionTracking!==true||user.capabilities?.mutations!==true){error.value='当前环境尚未启用账号协同管理';return}
 if(!command.value)command.value=Object.freeze({...draft,expectedVersion:snapshot.value.version,requestId:createUiRequestId()})
 const token=scope.stamp();busy.value=true;error.value=''
 try{await request.post('/api/accounts/'+encodeURIComponent(props.account.userId)+'/access',command.value);if(!scope.current(token))return;command.value=null;visible.value=false;emit('updated')}
 catch(failure){if(!scope.current(token))return;error.value=failure.response?.data?.message||failure.message||'结果尚未确认，请使用原请求核对或重试';if(failure.response?.status===409){command.value=null;conflict.value=true}else if([400,403,404].includes(failure.response?.status)){command.value=null;if([403,404].includes(failure.response?.status)){snapshot.value=null}}}
 finally{if(scope.current(token))busy.value=false}
}
</script>
<style scoped>.access-note{font-size:12px;color:var(--app-text-secondary);line-height:1.8}.access-form label{display:flex;flex-direction:column;align-items:flex-start;gap:8px;margin:18px 0;font-size:13px}.access-actions{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap}</style>
