<template>
  <el-button v-if="user.role==='INSPECTOR'" size="small" link type="primary" :loading="busy" :disabled="!pending&&!eligible" :title="eligible?'领取主管显式授权给本人的任务':'仅当前领取候选可以领取无人负责的待复核任务'" @click="claim">{{ pending?'重试原领取':'领取任务' }}</el-button>
</template>
<script setup>
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { captureAccountRequest } from '../api/request'
const request=captureAccountRequest()
import { useUserStore } from '../stores/user'
import { useAccountOperationScope } from '../composables/useAccountOperationScope'
import { captureTaskMutation, taskMutationPayload, resourceVersion } from '../utils/mutationVersion'
const props=defineProps({task:{type:Object,required:true}}),emit=defineEmits(['claimed'])
const user=useUserStore(),busy=ref(false),pending=ref(null)
const scope=useAccountOperationScope(()=>{pending.value=null;busy.value=false})
const pick=key=>props.task[key]??props.task.result?.[key]
const eligible=computed(()=>user.isAuthenticated&&user.capabilities?.mutations===true&&!!user.accountContext&&resourceVersion(props.task)!==null
  && Array.isArray(pick('claimCandidateUserIds'))&&pick('claimCandidateUserIds').some(id=>String(id)===String(user.userId))
  && !pick('assignee')&&!pick('assigneeUserId')&&['COMPLETED','PARTIAL_FAILED'].includes(pick('status'))&&pick('flowStatus')==='PENDING_REVIEW')
async function claim(){
 if(busy.value||user.role!=='INSPECTOR'||!pending.value&&!eligible.value)return
 const token=scope.stamp();busy.value=true
 try{
  if(!pending.value){
   const snapshot=captureTaskMutation(props.task)
   try{await ElMessageBox.confirm(`领取任务 ${snapshot.taskId} 后由本人账号负责复核`,'领取当前任务',{confirmButtonText:'确认领取',cancelButtonText:'保留原状态'})}catch{return}
   if(!scope.current(token))return
   pending.value=Object.freeze({taskId:snapshot.taskId,body:taskMutationPayload(snapshot,{})})
  }
  const command=pending.value,response=await request.post('/api/detection/tasks/'+encodeURIComponent(command.taskId)+'/claim',command.body)
  if(!scope.current(token))return
  if(response.data?.code!==200||String(response.data.data?.taskId)!==String(command.taskId))throw new Error(response.data?.message||'尚未收到匹配的领取回执')
  pending.value=null;ElMessage.success('已收到本人领取任务的回执');emit('claimed')
 }catch(error){
  if(!scope.current(token))return
  if([400,403,404,409].includes(error.response?.status)){pending.value=null;emit('claimed')}
  ElMessage.warning(error.response?.data?.message||error.message||'领取结果未确认 重试将沿用原请求编号')
 }finally{if(scope.current(token))busy.value=false}
}
</script>
