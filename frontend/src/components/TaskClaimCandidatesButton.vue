<template>
  <el-button v-if="user.role==='SUPERVISOR' && user.capabilities?.mutations===true" size="small" link type="primary" :disabled="!eligible" @click="open">领取候选</el-button>
  <el-dialog v-model="visible" title="授权任务领取候选" width="560px" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" append-to-body>
    <p class="candidate-note">仅所选检测账号可以看到并领取此任务 领取成功后自动撤销其他候选资格</p>
    <el-select v-model="selected" multiple filterable remote clearable :multiple-limit="16" :remote-method="search" :loading="loading" :disabled="busy||!!pending||conflict" aria-label="任务领取候选账号" placeholder="搜索并选择至多 16 个检测账号" @visible-change="value=>value&&search('')">
      <el-option v-for="option in options" :key="option.userId" :value="option.userId" :label="option.username+' · ID '+option.userId" />
    </el-select>
    <p class="candidate-note">清空选择并提交可撤销所有领取候选</p>
    <p v-if="notice" role="alert" class="candidate-error">{{ notice }}</p>
    <template #footer>
      <el-button :disabled="busy" @click="visible=false">保留原状态</el-button>
      <el-button type="primary" :loading="busy" :disabled="conflict||loading" @click="submit">{{ pending?'重试原授权':'确认候选授权' }}</el-button>
    </template>
  </el-dialog>
</template>
<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { captureAccountRequest } from '../api/request'
import { useUserStore } from '../stores/user'
import { useAccountOperationScope } from '../composables/useAccountOperationScope'
import { captureTaskMutation, taskMutationPayload, resourceVersion } from '../utils/mutationVersion'
const props=defineProps({task:{type:Object,required:true}}),emit=defineEmits(['authorized'])
const request=captureAccountRequest(),user=useUserStore()
const visible=ref(false),busy=ref(false),loading=ref(false),pending=ref(null),conflict=ref(false),notice=ref(''),selected=ref([]),options=ref([])
let snapshot,searchSequence=0
const scope=useAccountOperationScope(()=>{visible.value=false;pending.value=null;selected.value=[];options.value=[];notice.value='';busy.value=false;loading.value=false;searchSequence++})
const pick=key=>props.task[key]??props.task.result?.[key]
const eligible=computed(()=>user.isAuthenticated&&!!user.accountContext&&resourceVersion(props.task)!==null&&!pick('assignee')&&!pick('assigneeUserId')&&['COMPLETED','PARTIAL_FAILED'].includes(pick('status'))&&pick('flowStatus')==='PENDING_REVIEW')
function open(){
 if(!eligible.value||user.role!=='SUPERVISOR')return
 snapshot=captureTaskMutation(props.task);selected.value=[...(pick('claimCandidateUserIds')||[])].map(String)
 options.value=selected.value.map(userId=>({userId,username:'已授权账号'}));pending.value=null;conflict.value=false;notice.value='';visible.value=true
}
async function search(keyword=''){
 if(!visible.value||busy.value||pending.value||conflict.value)return
 const stamp=scope.stamp(),sequence=++searchSequence;loading.value=true
 try{
  const response=await request.get('/api/detection/quality-assignees',{params:{keyword:String(keyword).slice(0,50)}})
  if(!scope.current(stamp)||sequence!==searchSequence||!visible.value)return
  if(response.data?.code!==200||!Array.isArray(response.data.data))throw Error('无法读取当前合格的检测账号')
  const found=response.data.data.filter(row=>typeof row.username==='string'&&/^[1-9]\d{0,18}$/.test(String(row.userId))&&(typeof row.userId==='string'||Number.isSafeInteger(row.userId))).map(row=>({...row,userId:String(row.userId)}))
  options.value=[...options.value.filter(row=>selected.value.includes(row.userId)&&!found.some(item=>item.userId===row.userId)),...found]
 }catch(error){if(scope.current(stamp)&&sequence===searchSequence)notice.value=error.message||'账号查询未完成 请重新搜索'}
 finally{if(scope.current(stamp)&&sequence===searchSequence)loading.value=false}
}
async function submit(){
 if(busy.value||conflict.value||user.role!=='SUPERVISOR')return
 const stamp=scope.stamp();busy.value=true;notice.value=''
 try{
  if(!pending.value)pending.value=taskMutationPayload(snapshot,{candidateUserIds:Object.freeze([...selected.value])})
  const response=await request.post('/api/detection/tasks/'+encodeURIComponent(snapshot.taskId)+'/claim-candidates',pending.value)
  if(!scope.current(stamp))return
  if(response.data?.code!==200||String(response.data.data?.taskId)!==String(snapshot.taskId))throw Error(response.data?.message||'尚未收到匹配的授权回执')
  pending.value=null;visible.value=false;ElMessage.success('已保存任务领取候选');emit('authorized')
 }catch(error){
  if(!scope.current(stamp))return
  if([400,403,404,409].includes(error.response?.status)){pending.value=null;conflict.value=true;emit('authorized')}
  notice.value=error.response?.data?.message||error.message||'授权结果未确认 重试将沿用原请求编号'
  if(conflict.value)notice.value+=' 选择已保留 请关闭后重新读取任务'
 }finally{if(scope.current(stamp))busy.value=false}
}
</script>
<style scoped>
.el-select{width:100%}.candidate-note{font-size:13px;line-height:1.6;color:#596575;margin:0 0 14px}.candidate-error{color:#b91c1c;line-height:1.6}
</style>
