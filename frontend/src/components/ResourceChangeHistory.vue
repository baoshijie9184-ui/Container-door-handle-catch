<template>
  <section class="change-history app-panel" :aria-label="compact?'当前资源修改记录':'多人协同修改记录'">
    <header class="change-history-heading"><div><h2><AppIcon name="DocumentChecked" :size="18" />{{ compact?'修改记录':'多人协同修改记录' }}</h2><p>按当前资源权限查询 操作时身份和历史原值分别保留</p></div><el-button :loading="loading" @click="reload"><AppIcon name="Refresh" :size="15" />核对最新记录</el-button></header>
    <form v-if="!compact" class="change-history-filters" @submit.prevent="search">
      <label>业务域<el-select v-model="filters.domain" clearable placeholder="全部业务域"><el-option v-for="item in auditDomainOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
      <label>资源类型<el-input v-model="filters.resourceType" maxlength="64" placeholder="例如 DETECTION_TASK" clearable /></label>
      <label>资源编号<el-input v-model="filters.resourceId" maxlength="128" placeholder="与资源类型同时填写" clearable /></label>
      <label v-if="supervisor">操作账号 ID<el-input v-model="filters.actorUserId" maxlength="20" clearable /></label>
      <label v-if="supervisor">操作时角色<el-select v-model="filters.actorRole" clearable><el-option label="主管" value="SUPERVISOR"/><el-option label="检测人员" value="INSPECTOR"/></el-select></label>
      <label>操作<el-input v-model="filters.action" maxlength="48" clearable placeholder="例如 UPDATE" /></label>
      <label>开始时间（北京时间）<input v-model="filters.from" type="datetime-local" /></label><label>结束时间（北京时间）<input v-model="filters.to" type="datetime-local" /></label>
      <div class="change-filter-actions"><el-button type="primary" native-type="submit" :loading="loading">查询</el-button><el-button @click="reset">重置</el-button></div>
    </form>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <div v-if="changed" class="change-new-records" role="status"><span>有新的修改记录 当前历史位置已保留</span><el-button text type="primary" @click="reload">读取新记录</el-button></div>
    <p v-if="loaded" class="change-history-note">已读取 {{ rows.length }} 条{{ compact?'当前资源记录':'授权记录' }} 数量不代表全部历史</p>
    <ol v-if="rows.length" class="change-timeline" aria-label="修改时间线">
      <li v-for="row in rows" :key="row.id"><div class="change-timeline-heading"><strong>{{ historyActorName(row) }}</strong><span>{{ historyActorRole(row) }}</span><time>{{ auditTime(row.occurredAt) }}</time></div><p v-if="row.source?.type==='SYSTEM'" class="change-history-note">原发起人 {{ historyInitiator(row) }} · 实际由系统执行</p><div class="change-timeline-body"><span>{{ auditDomainLabel(row.domain) }} · {{ row.action || '动作未记录' }}</span><strong v-if="row.resourceId">{{ row.resourceId }}</strong><span>版本 {{ row.beforeVersion ?? '未知' }} → {{ row.afterVersion ?? '未知' }}</span><el-button text type="primary" :disabled="row.diffAvailable!==true" @click="open(row)">{{ row.diffAvailable?'查看字段对比':'历史未记录或无权读取字段对比' }}</el-button></div></li>
    </ol>
    <CollectionEmptyState v-else :loading="loading" :error="error" empty-title="暂无可查看的修改记录" empty-description="只展示当前账号有权限读取的已提交操作 旧记录不会补造历史原值" @retry="reload" />
    <el-button v-if="nextCursor" :loading="loading" @click="load(true)">加载更早记录</el-button>
    <el-dialog v-model="detailOpen" title="操作时快照与字段对比" width="min(860px,94vw)" append-to-body>
      <p v-if="detailLoading" role="status">正在核对当前资源与字段权限</p><el-alert v-if="detailError" :title="detailError" type="warning" :closable="false" />
      <template v-if="detail"><p class="change-detail-actor"><strong>{{ historyActorName(detail) }}</strong> · {{ historyActorRole(detail) }} · {{ auditTime(detail.occurredAt) }}</p><p v-if="detail.source?.type==='SYSTEM'">原发起人 {{ historyInitiator(detail) }} · 系统执行来源与原发起人分别记录</p><p>{{ detail.resourceType }} {{ detail.resourceId }} · {{ detail.action }} · 版本 {{ detail.beforeVersion ?? '未知' }} → {{ detail.afterVersion ?? '未知' }}</p>
        <div v-if="detail.diffAvailable && detail.changes?.length" class="change-diff-list"><section v-for="change in detail.changes" :key="change.field" class="change-diff"><h3>{{ change.label || change.field }}<small>{{ change.operation }}</small></h3><div><section><h4>修改前</h4><pre tabindex="0">{{ changeValue(change,'before') }}</pre></section><section><h4>修改后</h4><pre tabindex="0">{{ changeValue(change,'after') }}</pre></section></div></section></div>
        <p v-else>历史未记录字段对比 或本次没有可展示的字段变化</p><details><summary>核对事件与请求编号</summary><p>事件 {{ detail.eventId }}<br>请求 {{ detail.requestId || '未记录' }}</p></details>
      </template>
      <template #footer><el-button @click="detailOpen=false">关闭详情</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { ref, reactive, computed, watch, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { captureAccountRequest } from '../api/request'
const request=captureAccountRequest()
import { useUserStore } from '../stores/user'
import { useResourceChanges } from '../composables/useResourceChanges'
import { useAccountOperationScope } from '../composables/useAccountOperationScope'
import { auditDomainOptions, auditDomainLabel, auditTime } from '../utils/auditPresentation'
import { historyActorName, historyActorRole, historyInitiator, changeValue, readChangePage } from '../utils/changeHistory'
import CollectionEmptyState from './CollectionEmptyState.vue'
const props=defineProps({resourceType:String,resourceId:[String,Number],domain:String,compact:Boolean})
const route=useRoute(), user=useUserStore(), supervisor=computed(()=>user.role==='SUPERVISOR')
const empty=()=>({domain:props.domain||'',resourceType:props.resourceType||'',resourceId:String(props.resourceId||''),actorUserId:'',actorRole:'',action:'',from:'',to:''})
const filters=reactive(empty()), applied=ref({}), rows=ref([]),nextCursor=ref(null),loaded=ref(false),loading=ref(false),error=ref('')
const detail=ref(null),detailOpen=ref(false),detailLoading=ref(false),detailError=ref('')
const scope=useAccountOperationScope(()=>{rows.value=[];detail.value=null;detailOpen.value=false;loaded.value=false;nextCursor.value=null})
const listRead=scope.channel(),detailRead=scope.channel()
const {changed}=useResourceChanges({resourceType:computed(()=>props.resourceType),resourceId:computed(()=>props.resourceId),isEditing:()=>rows.value.length>0,refresh:()=>load(false),revalidate:validateDetailAccess})
function query(){
  const values={...filters}
  if (!!values.resourceType !== !!values.resourceId) throw new Error('资源类型和编号需要同时填写')
  if(values.actorUserId && !/^[1-9]\d{0,18}$/.test(values.actorUserId))throw new Error('操作账号 ID 须为正整数')
  if(values.from&&values.to&&values.from>values.to)throw new Error('开始时间不能晚于结束时间')
  return Object.fromEntries(Object.entries({...values,from:undefined,to:undefined,
    occurredFrom:values.from?new Date(values.from+':00+08:00').toISOString():undefined,
    occurredTo:values.to?new Date(values.to+':00+08:00').toISOString():undefined}).filter(([,v])=>v!==''&&v!==undefined))
}
async function load(append=false){
  if(!user.isAuthenticated)return
  if(user.capabilities?.changeHistory!==true){rows.value=[];error.value='当前环境尚未启用字段修改历史，可在下方核对已有基础审计';return}
  const token=listRead.begin();loading.value=true;error.value=''
  try{
    const result=readChangePage(await request.get('/api/operations/audit/changes',{params:{...applied.value,size:50,...(append&&nextCursor.value?{before:nextCursor.value}:{})},signal:token.signal}))
    if(!listRead.current(token))return
    const existing=append?rows.value:[],seen=new Set(existing.map(row=>row.id))
    rows.value=[...existing,...result.items.filter(row=>!seen.has(row.id))];nextCursor.value=result.nextCursor;loaded.value=true;changed.value=false
  }catch(failure){if(!listRead.current(token))return;if([401,403,404].includes(failure.response?.status)){rows.value=[];detail.value=null;detailOpen.value=false}error.value=failure.response?.data?.message||failure.message||'修改记录暂不可读取'}
  finally{if(listRead.current(token))loading.value=false}
}
function search(){try{applied.value=query();rows.value=[];nextCursor.value=null;return load(false)}catch(failure){error.value=failure.message}}
function reset(){Object.assign(filters,empty());return search()}
const reload=()=>load(false)
async function open(row){
  const token=detailRead.begin();detailOpen.value=true;detail.value=null;detailError.value='';detailLoading.value=true
  try{const response=await request.get('/api/operations/audit/changes/'+encodeURIComponent(row.id),{signal:token.signal});if(detailRead.current(token)){const value=response.data?.code===200?response.data.data:response.data;if(value?.id!==row.id)throw new Error('返回的修改记录不匹配');detail.value=value}}
  catch(failure){if(detailRead.current(token)){detail.value=null;detailError.value=failure.response?.data?.message||failure.message||'当前无权读取字段详情'}}finally{if(detailRead.current(token))detailLoading.value=false}
}
watch(()=>[props.resourceType,props.resourceId,props.domain,route.query.resourceType,route.query.resourceId,route.query.domain],()=>{Object.assign(filters,empty(),props.compact?{}:{resourceType:String(route.query.resourceType||''),resourceId:String(route.query.resourceId||''),domain:String(route.query.domain||'')});search()},{immediate:true})
onBeforeUnmount(()=>{detail.value=null})
async function validateDetailAccess(){
 if(!detailOpen.value||!detail.value?.id)return
 const id=detail.value.id,token=scope.stamp()
 try{const response=await request.get('/api/operations/audit/changes/'+encodeURIComponent(id));if(!scope.current(token)||detail.value?.id!==id)return;const value=response.data?.code===200?response.data.data:response.data;detail.value=value}
 catch(failure){if(scope.current(token)&&[401,403,404].includes(failure.response?.status)){detail.value=null;detailOpen.value=false;rows.value=[];nextCursor.value=null;error.value='当前资源权限已变化 已清除旧详情 请重新查询'}}
}
</script>
<style scoped>
.change-history{padding:22px;margin:18px 0}.change-history-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.change-history h2{display:flex;align-items:center;gap:8px;font-size:17px;margin:0}.change-history-heading p,.change-history-note{color:var(--app-text-secondary);font-size:12px;line-height:1.8}.change-history-filters{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px;margin:20px 0}.change-history-filters label{display:flex;flex-direction:column;gap:7px;font-size:12px;color:var(--app-text-secondary)}.change-history-filters input[type=datetime-local]{min-height:32px;border:1px solid var(--app-border);border-radius:5px;padding:0 8px;color:var(--app-text);background:var(--app-surface);min-width:0}.change-filter-actions{display:flex;align-items:flex-end;gap:8px}.change-new-records{display:flex;justify-content:space-between;align-items:center;background:var(--app-primary-light);padding:8px 14px;border-left:3px solid var(--app-primary);font-size:13px}.change-timeline{list-style:none;margin:14px 0;padding:0}.change-timeline>li{padding:18px 0;border-top:1px solid var(--app-border)}.change-timeline-heading{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:13px}.change-timeline-heading span,.change-timeline-heading time{color:var(--app-text-secondary);font-size:12px}.change-timeline-heading time{margin-left:auto}.change-timeline-body{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:8px;font-size:12px;color:var(--app-text-secondary)}.change-timeline-body strong{font-weight:500;color:var(--app-text);overflow-wrap:anywhere}.change-diff{margin:18px 0;border-top:1px solid var(--app-border);padding-top:12px}.change-diff h3{font-size:14px;margin:0 0 10px}.change-diff h3 small{font-size:11px;font-weight:400;color:var(--app-text-secondary);margin-left:10px}.change-diff>div{display:grid;grid-template-columns:1fr 1fr;gap:12px}.change-diff h4{font-size:12px;margin:0 0 5px;color:var(--app-text-secondary)}.change-diff pre{margin:0;padding:12px;background:var(--app-surface-muted);border:1px solid var(--app-border);border-radius:6px;max-height:240px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.8 inherit}.change-diff pre:focus-visible{outline:2px solid var(--app-primary)}@media(max-width:640px){.change-history{padding:15px}.change-history-heading{flex-direction:column}.change-diff>div{grid-template-columns:1fr}.change-timeline-heading time{margin-left:0;width:100%}}
</style>
