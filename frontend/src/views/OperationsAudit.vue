<template>
  <section class="page-shell operations-page"><PageHero icon="DocumentChecked" title="操作审计" description="核对业务变更与文件交付，按当前账号范围查看记录。时间统一使用 UTC+8。"><template #actions><el-button :loading="loading" @click="refresh"><AppIcon name="Refresh" />刷新已查业务范围</el-button></template></PageHero>
    <section class="toolbar-panel app-panel audit-filters" aria-label="筛选业务操作"><form class="audit-filter-form" @submit.prevent="search"><label for="audit-domain">业务域<el-select id="audit-domain" v-model="domain" filterable allow-create default-first-option clearable placeholder="选择业务域，留空查询全部"><el-option v-for="item in auditDomainOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></label><div class="management-filter-actions"><el-button type="primary" native-type="submit" :loading="loading"><AppIcon name="Search" :size="16" />查询</el-button><el-button @click="resetDomain"><AppIcon name="Refresh" :size="16" />重置</el-button></div></form><el-alert v-if="filterError" :title="filterError" type="warning" show-icon :closable="false" /></section>
    <p v-if="filtersDirty" class="audit-query-note" role="status">查询条件已修改，下方业务记录仍为“{{ appliedDomain ? auditDomainLabel(appliedDomain) : '全部业务域' }}”；点击查询后更新。</p>
    <el-alert v-if="error && rows.length" :title="error + '；下方保留先前读取的记录，请重新查询核对。'" type="error" :closable="false" role="alert" />
    <el-button v-if="error && rows.length" class="audit-retry" :loading="loading" @click="retryBusiness"><AppIcon name="Refresh" :size="14" />重读上次业务请求</el-button>
    <div class="audit-table table-panel">
      <div class="collection-heading"><h2><AppIcon name="Document" :size="18" />业务操作记录</h2><span>{{ loaded?'已加载 '+rows.length+' 条':'数量尚未核对' }} · {{ loaded ? appliedDomain ? auditDomainLabel(appliedDomain) : '全部业务域' : '范围尚未读取' }}</span></div>
      <el-table :data="rows" v-loading="loading" row-key="id">
        <template #empty><CollectionEmptyState :loading="loading" :error="error" :filtered="!!appliedDomain" empty-title="暂无可查看的业务操作" empty-description="这里只展示当前账号有权限读取的已登记审计记录。" @retry="retryBusiness" @reset="resetDomain" /></template>
        <el-table-column label="业务与动作" min-width="200"><template #default="{row}"><div class="audit-cell"><strong>{{ auditDomainLabel(row.domain) }}</strong><small>{{ row.action||'动作未记录' }}</small></div></template></el-table-column>
        <el-table-column label="资源" min-width="195"><template #default="{row}"><div class="audit-cell"><strong>{{ row.resource_id||'资源未记录' }}</strong><small>版本 {{ row.resource_version??'未知' }} · {{ auditScopeLabel(row.scope) }}</small></div></template></el-table-column>
        <el-table-column label="账号 ID" width="100"><template #default="{row}">{{ row.actor_user_id??'未记录' }}</template></el-table-column>
        <el-table-column label="记录结果" min-width="140"><template #default="{row}"><StatusBadge domain="audit" :code="row.result" /></template></el-table-column><el-table-column label="时间（UTC+8）" min-width="180"><template #default="{row}">{{ formatTime(row.created_at) }}</template></el-table-column>
        <el-table-column label="详情" width="88"><template #default="{row}"><el-button text type="primary" :aria-label="'查看审计 '+row.id" @click="openRecord(row,false)"><AppIcon name="Search" :size="14" />查看</el-button></template></el-table-column>
      </el-table>
    </div>
    <el-button v-if="rows.length&&more" :loading="loading" @click="load(true)"><AppIcon name="DocumentCopy" :size="16" />加载更早记录</el-button>
    <p v-if="loaded" class="audit-page-note">按编号由新到旧加载，数量仅指当前已读取记录，非全部历史总数。{{ more?'可继续加载更早记录。':'本次查询暂未返回更多记录。' }}</p>
    <section class="delivery-section" aria-label="文件交付记录">
      <header><div><h3><el-icon><DocumentChecked /></el-icon> 文件交付记录</h3><p>{{ deliveryLoaded?'已加载 '+deliveries.length+' 条':'数量尚未核对' }} · 按当前账号范围独立查询，不受上方业务域筛选影响</p></div><el-button :loading="deliveryLoading" @click="loadDeliveries(false)"><AppIcon name="Refresh" :size="16" />刷新交付状态</el-button></header>
      <el-alert v-if="deliveryError && deliveries.length" :title="deliveryError + '；以下保留先前读取的交付记录。'" type="error" :closable="false" role="alert"/>
      <el-button v-if="deliveryError && deliveries.length" class="audit-retry" :loading="deliveryLoading" @click="retryDelivery"><AppIcon name="Refresh" :size="14" />重读上次交付请求</el-button>
      <div class="audit-table"><el-table :data="deliveries" v-loading="deliveryLoading" row-key="delivery_id">
        <template #empty><CollectionEmptyState :loading="deliveryLoading" :error="deliveryError" empty-title="暂无可查看的交付记录" empty-description="文件响应登记后，可在这里核对服务端处理状态。" @retry="retryDelivery" /></template>
        <el-table-column label="业务资源" min-width="220"><template #default="{row}"><div class="audit-cell"><strong>{{ auditDomainLabel(row.domain) }}</strong><small>{{ row.resource_id||'资源未记录' }}</small></div></template></el-table-column>
        <el-table-column label="交付状态" min-width="180"><template #default="{row}"><StatusBadge domain="delivery" :code="row.state" /></template></el-table-column>
        <el-table-column label="服务端写出下界" min-width="145"><template #default="{row}">{{ deliveryBytes(row) }}</template></el-table-column>
        <el-table-column label="HTTP 状态" width="105"><template #default="{row}">{{ row.http_status??'未知' }}</template></el-table-column>
        <el-table-column label="更新时间（UTC+8）" min-width="185"><template #default="{row}">{{ formatTime(row.updated_at) }}</template></el-table-column>
        <el-table-column label="详情" width="88"><template #default="{row}"><el-button text type="primary" :aria-label="'查看文件响应 '+row.delivery_id" @click="openRecord(row,true)"><AppIcon name="Search" :size="14" />查看</el-button></template></el-table-column>
      </el-table></div>
      <el-button v-if="deliveries.length && deliveryMore" :loading="deliveryLoading" @click="loadDeliveries(true)">加载更早交付</el-button>
      <p class="audit-page-note">响应编号、文件编号、请求编号和预计内容大小可在详情核对。此处不会重新发起文件下载。</p>
    </section>
    <details class="audit-explanation"><summary><AppIcon name="Document" :size="15" />审计范围与文件响应说明</summary><p class="note">主管查看企业业务和本人私有审计，员工查看本人记录。服务端响应完成不代表浏览器收到文件；写出字节是服务端已返回的写调用计数，不用于流量计费。OSS 重定向仅表示授权签发，HEAD 无文件正文，206 为部分或多段响应；计数可能包含多段边界或错误响应内容，不等于文件净字节。</p></details>
    <el-dialog class="operations-audit-dialog" append-to-body v-model="detailOpen" :title="detailDelivery?'文件交付详情':'业务操作详情'" width="min(720px,94vw)"><AuditRecordDetails :record="selectedRecord" :delivery="detailDelivery" /><template #footer><el-button @click="detailOpen=false">关闭详情</el-button></template></el-dialog>
  </section>
</template>
<script setup>
import { ref,computed,watch,onBeforeUnmount } from 'vue'
import request from '@/api/request'
import { useUserStore } from '@/stores/user'
import CollectionEmptyState from '@/components/CollectionEmptyState.vue'
import { auditDomainOptions,auditDomainLabel,auditScopeLabel,auditTime,deliveryBytes } from '@/utils/auditPresentation'
import AuditRecordDetails from '@/components/AuditRecordDetails.vue'
import { DocumentChecked } from '@element-plus/icons-vue'
const userStore=useUserStore()
const actor=computed(()=>JSON.stringify([userStore.identity?.userId || userStore.username || '',userStore.role,userStore.isAuthenticated]))
const rows=ref([]),domain=ref(''),error=ref(''),loading=ref(false),more=ref(false),filterError=ref(''),appliedDomain=ref(''),loaded=ref(false)
const deliveries=ref([]),deliveryLoading=ref(false),deliveryError=ref(''),deliveryMore=ref(false),deliveryLoaded=ref(false)
const detailOpen=ref(false),selectedRecord=ref(null),detailDelivery=ref(false)
const formatTime=auditTime,maximum='9223372036854775807'
const draftDomain=()=>typeof domain.value==='string'?domain.value.trim():''
const filtersDirty=computed(()=>loaded.value && draftDomain()!==appliedDomain.value)
const channels={business:{rows,loading,error,more,loaded,version:0,pending:'',last:null},delivery:{rows:deliveries,loading:deliveryLoading,error:deliveryError,more:deliveryMore,loaded:deliveryLoaded,version:0,pending:'',last:null}}
let disposed=false
function recordId(value){
  const text=typeof value==='number' && Number.isSafeInteger(value) && value>0?String(value):typeof value==='string' && /^[1-9]\d*$/.test(value)?value:''
  return text && (text.length<maximum.length || text.length===maximum.length && text<=maximum)?text:''
}
const older=(a,b)=>a.length<b.length || a.length===b.length && a<b
function validateRows(value,before,delivery,existing=[]){
  if(!Array.isArray(value))throw new Error('审计记录未完整读取')
  const ids=new Set(),deliveryIds=new Set(existing.map(row=>row.delivery_id))
  let previous=before
  for(const row of value){
    const id=recordId(row?.id)
    if(!id || ids.has(id) || !older(id,previous))throw new Error('审计编号或记录顺序未完整读取，请重新核对')
    ids.add(id);previous=id
    if(delivery){const key=row.delivery_id;if(typeof key!=='string' || !key.trim() || deliveryIds.has(key))throw new Error('文件响应编号未完整读取');deliveryIds.add(key)}
  }
  return value
}
function closeDetails(){detailOpen.value=false;selectedRecord.value=null}
function clearChannel(kind){
  const channel=channels[kind]
  channel.rows.value=[];channel.more.value=false;channel.loaded.value=false
  if(detailOpen.value && detailDelivery.value===(kind==='delivery'))closeDetails()
}
function openRecord(row,delivery){
  const list=delivery?deliveries.value:rows.value
  if(!list.some(item=>recordId(item.id)===recordId(row?.id)))return
  selectedRecord.value=Object.freeze({...row});detailDelivery.value=delivery;detailOpen.value=true
}
async function readChannel(kind,spec){
  if(disposed || !userStore.isAuthenticated)return false
  const channel=channels[kind],key=JSON.stringify(spec),stamp=actor.value
  if(channel.loading.value && (spec.append || channel.pending===key))return false
  if(spec.append && (!channel.loaded.value || !channel.rows.value.length || recordId(channel.rows.value.at(-1).id)!==spec.before))return false
  if(kind==='business'){
    if(spec.query && (spec.query.length>48 || !/^[A-Za-z0-9_:./-]+$/.test(spec.query))){filterError.value='请选择已有业务域，或填写不超过 48 字符的登记代码（字母、数字、_ : . / -）；尚未执行新查询。';return false}
    filterError.value=''
  }
  const version=++channel.version
  const current=()=>!disposed && actor.value===stamp && version===channel.version
  channel.pending=key;channel.last=spec;channel.error.value='';channel.loading.value=true
    if(!spec.append && kind==='business' && spec.query!==appliedDomain.value)clearChannel(kind)
  try{
    const response=await request.get(kind==='delivery'?'/api/operations/audit/deliveries':'/api/operations/audit',{params:{before:spec.before,size:50,...(kind==='business' && spec.query?{domain:spec.query}:{})}})
    if(!current())return false
    // These two existing endpoints return raw arrays, not Result-wrapped DTOs.
    const next=validateRows(response.data,spec.before,kind==='delivery',spec.append?channel.rows.value:[])
    const previous=spec.append?channel.rows.value:[],seen=new Set(previous.map(row=>recordId(row.id)))
    channel.rows.value=[...previous,...next.filter(row=>!seen.has(recordId(row.id)))]
    channel.loaded.value=true;channel.more.value=next.length===50
    if(kind==='business')appliedDomain.value=spec.query
    return true
  }catch(failure){
    if(!current())return false
    if([401,403].includes(failure.response?.status)){clearChannel(kind);if(kind==='business')appliedDomain.value=''}
    channel.error.value=failure.response?.data?.message || failure.message || (kind==='delivery'?'交付审计暂不可读取，未重新下载文件':'业务审计暂不可读取，请重新核对')
    return false
  }finally{if(current())channel.loading.value=false}
}
const search=()=>readChannel('business',{append:false,before:maximum,query:draftDomain()})
const refresh=()=>readChannel('business',{append:false,before:maximum,query:loaded.value?appliedDomain.value:channels.business.last?.query ?? draftDomain()})
const resetDomain=()=>{domain.value='';return search()}
const retryBusiness=()=>readChannel('business',channels.business.last || {append:false,before:maximum,query:draftDomain()})
const retryDelivery=()=>readChannel('delivery',channels.delivery.last || {append:false,before:maximum,query:''})
function load(append=false){
  if(!append)return refresh()
  if(!more.value || !rows.value.length)return false
  return readChannel('business',{append:true,before:recordId(rows.value.at(-1).id),query:appliedDomain.value})
}
function loadDeliveries(append=false){
  if(append && (!deliveryMore.value || !deliveries.value.length))return false
  return readChannel('delivery',{append,before:append?recordId(deliveries.value.at(-1).id):maximum,query:''})
}
watch(actor,()=>{
  for(const kind of ['business','delivery']){const channel=channels[kind];channel.version++;channel.pending='';channel.last=null;channel.loading.value=false;channel.error.value='';clearChannel(kind)}
  domain.value='';appliedDomain.value='';filterError.value='';closeDetails()
  if(userStore.isAuthenticated){search();loadDeliveries(false)}
},{immediate:true,flush:'sync'})
onBeforeUnmount(()=>{disposed=true;channels.business.version++;channels.delivery.version++})
</script>
<style scoped>
.operations-page { gap:18px; min-width:0; }
.audit-filter-form { display:grid; grid-template-columns:minmax(220px,420px) minmax(0,1fr); align-items:end; gap:14px 20px; }
.audit-filter-form > label { display:grid; gap:7px; min-width:0; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.audit-filter-form .el-select { width:100%; }
.audit-table { min-width:0; overflow-x:auto; }
.audit-table .collection-heading { padding:16px 18px; }
.audit-cell { display:grid; gap:5px; min-width:0; line-height:1.8; padding:6px 0; }
.audit-cell strong { font-size:13px; font-weight:550; color:var(--app-text); overflow-wrap:anywhere; }
.audit-cell small { font-size:11px; color:var(--app-text-secondary); overflow-wrap:anywhere; }
.audit-query-note { padding:10px 14px; border-left:3px solid #adc8f7; background:var(--app-primary-soft); border-radius:0 6px 6px 0; color:var(--app-text-secondary); font-size:12px; line-height:1.85; margin:0; }
.audit-page-note { font-size:12px; color:var(--app-text-secondary); line-height:1.85; margin:0; overflow-wrap:anywhere; }
.audit-retry { align-self:flex-start; }
.delivery-section { display:grid; gap:16px; padding-top:24px; margin-top:6px; border-top:1px solid var(--app-border); min-width:0; }
.delivery-section > header { display:flex; align-items:flex-start; justify-content:space-between; flex-wrap:wrap; gap:12px 20px; }
.delivery-section > header > div { min-width:0; flex:1 1 300px; }
.delivery-section h3 { display:flex; align-items:center; gap:8px; margin:0; font-size:16px; font-weight:600; color:var(--app-text); line-height:1.7; }
.delivery-section h3 > .el-icon { color:var(--app-primary); flex-shrink:0; }
.delivery-section header p { color:var(--app-text-secondary); font-size:12px; line-height:1.85; margin:7px 0 0; overflow-wrap:anywhere; }
.delivery-section .audit-table { border:1px solid var(--app-border); border-radius:10px; background:#fff; }
.delivery-section > .el-button { justify-self:start; }
.audit-explanation { border-top:1px solid var(--app-border); padding-top:16px; }
.audit-explanation summary { display:flex; align-items:center; gap:7px; width:fit-content; color:var(--app-text-secondary); font-size:12px; line-height:1.85; cursor:pointer; }
.audit-explanation summary::after { content:'展开'; color:var(--app-primary); margin-left:6px; }
.audit-explanation[open] summary::after { content:'收起'; }
.audit-explanation summary:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; border-radius:3px; }
.note { max-width:80ch; color:var(--app-text-secondary); font-size:12px; line-height:1.9; margin:12px 0 0; }
@media(max-width:600px) { .audit-filter-form { grid-template-columns:minmax(0,1fr); } }
</style>
<style>
.operations-audit-dialog .el-dialog__body { max-height:70dvh; overflow-y:auto; overscroll-behavior:contain; }
@media(prefers-reduced-motion:reduce) { .operations-audit-dialog,.el-overlay:has(.operations-audit-dialog) { animation:none!important;transition:none!important; } }
</style>
