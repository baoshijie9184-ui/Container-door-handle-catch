<template>
  <section v-if="visible" class="operation-panel provider-budget" aria-labelledby="provider-budget-title">
    <header class="budget-heading">
      <div><h2 id="provider-budget-title">{{ supervisor ? '厂家预算与员工限额' : '我的使用限额' }}</h2>
        <p class="operation-muted">百炼按模型扣 token，OpenAI 和 DeepSeek 分别共享各自的账户预算。</p></div>
      <el-button :loading="loading" @click="load">刷新用量</el-button>
    </header>
    <label v-if="supervisor" class="employee-picker">查看员工
      <el-select v-model="employee" filterable remote clearable :remote-method="search" :disabled="saving" placeholder="输入账号查找员工" @visible-change="openSearch" @change="switchEmployee">
        <el-option v-for="u in employees" :key="u.id" :value="u.id" :label="u.name"/>
      </el-select>
    </label>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <p v-if="loading && !view" role="status">正在读取额度…</p>
    <template v-if="view">
      <div class="budget-pools">
        <section v-for="group in sharedGroups" :key="group.key" class="pool-card">
          <header><div><h3>{{ group.name }}</h3><small>{{ group.label }}</small></div><strong>{{ group.unit }}</strong></header>
          <p class="shared-models">{{ group.models.map(id => id.slice(id.indexOf(':') + 1)).join('、') }}</p>
          <div v-if="supervisor" class="balance-row"><span>厂家账面可用</span><b>{{ field(group.pool,'available','待登记') }}</b></div>
          <div v-if="!supervisor || employee" class="balance-row"><span>员工限额</span><b>{{ field(group.member,'limit','未分配') }}</b></div>
          <dl v-if="group.member"><div><dt>已用</dt><dd>{{ field(group.member,'spent') }}</dd></div>
            <div><dt>预留</dt><dd>{{ field(group.member,'reserved') }}</dd></div>
            <div><dt>可用</dt><dd>{{ field(group.member,'available') }}</dd></div></dl>
          <details v-if="supervisor && group.pool"><summary>厂家预算明细</summary><p>总额 {{ group.pool.limit }} · 期初已用 {{ group.pool.openingUsed }} · 本站已用 {{ group.pool.spent }} · 预留 {{ group.pool.reserved }}</p></details>
          <div class="pool-actions" v-if="supervisor">
            <el-button size="small" @click="edit('NATIVE_POOL',group)">登记厂家额度</el-button>
            <el-button size="small" type="primary" plain :disabled="!employee" @click="edit('NATIVE_MEMBER',group)">分配员工限额</el-button>
            <el-button v-if="group.unit!=='TOKEN'" size="small" @click="edit('NATIVE_RATE',group)">模型单价</el-button>
          </div>
        </section>
      </div>
      <section v-if="bailianGroups.length" class="bailian-budget" aria-labelledby="bailian-budget-title">
        <div class="budget-heading bailian-heading">
          <div><h3 id="bailian-budget-title">阿里云百炼</h3>
            <p class="operation-muted">{{ bailianGroups.length }} 个模型 · 额度按模型独立计算，单位为 token</p>
          </div>
          <label class="model-search">筛选模型<input v-model.trim="modelQuery" type="search" placeholder="输入模型名称"></label>
        </div>
        <div class="ledger-wrap" tabindex="0" role="region" aria-label="百炼各模型额度">
          <table class="bailian-table">
            <thead><tr><th scope="col">模型</th><th scope="col">{{ supervisor ? '厂家可用' : '我的可用' }}</th>
              <th scope="col">已用</th><th scope="col">预留</th>
              <th v-if="!supervisor || employee" scope="col">{{ supervisor ? '员工限额 / 可用' : '我的限额' }}</th>
              <th v-if="supervisor" scope="col">管理</th></tr></thead>
            <tbody><tr v-for="group in matchingBailian" :key="group.key">
              <th scope="row">{{ group.label }}</th>
              <td><b>{{ tokenField(supervisor ? group.pool : group.member, 'available', supervisor ? '待登记' : '未分配') }}</b>
                <details v-if="supervisor && group.pool"><summary>预算明细</summary>
                  <p>总额 {{ tokenField(group.pool, 'limit') }} · 期初已用 {{ tokenField(group.pool, 'openingUsed') }}</p>
                </details></td>
              <td>{{ tokenField(supervisor ? group.pool : group.member, 'spent') }}</td>
              <td>{{ tokenField(supervisor ? group.pool : group.member, 'reserved') }}</td>
              <td v-if="!supervisor || employee">{{ tokenField(group.member, 'limit', '未分配') }}<template v-if="supervisor && group.member"> / {{ tokenField(group.member, 'available') }}</template></td>
              <td v-if="supervisor"><div class="row-actions">
                <el-button size="small" @click="edit('NATIVE_POOL',group)">登记额度</el-button>
                <el-button size="small" :disabled="!employee" @click="edit('NATIVE_MEMBER',group)">分配限额</el-button>
              </div></td>
            </tr></tbody>
          </table>
        </div>
        <p v-if="!matchingBailian.length" role="status" class="operation-muted">没有匹配“{{ modelQuery }}”的百炼模型。</p>
      </section>
      <div class="budget-heading"><h3>调用流水</h3><el-switch v-model="pendingOnly" active-text="只看待核对" @change="load()"/></div>
      <p v-if="!view.usage.length" class="operation-muted">当前账号还没有按厂家计量的调用。</p>
      <div v-else class="ledger-wrap"><table><thead><tr><th>时间</th><th>模型</th><th>输入 / 输出 token</th><th>本次消耗</th><th>状态</th><th v-if="supervisor">核对</th></tr></thead>
        <tbody><tr v-for="row in view.usage" :key="row.attempt"><td>{{ utcDisplay(row.time) }}</td><td>{{ row.model }}</td>
          <td>{{ row.inputTokens ?? '—' }} / {{ row.outputTokens ?? '—' }}</td><td>{{ row.cost ?? '—' }} {{ row.unit }}<small v-if="row.basis"> · {{ basisLabels[row.basis] }}</small></td><td>{{ statusLabels[row.status] || '待核对' }}</td><td v-if="supervisor"><el-button v-if="row.status==='NEEDS_REVIEW'" size="small" @click="openReview(row)">核对账单</el-button></td></tr></tbody></table></div>
      <el-button v-if="more" :loading="loading" @click="older">更早的调用</el-button>
    </template>
    <el-dialog v-model="reviewDialog" title="核对调用账单" width="min(540px,94vw)" :close-on-click-modal="false" :before-close="close">
      <form class="operation-form" @submit.prevent="confirmReview">
        <p>{{ reviewRow?.model }} · 调用 {{ reviewRow?.attempt }}</p>
        <label v-for="f in reviewFields" :key="f.key">{{ f.label }}<input v-model="review[f.key]" required :readonly="reviewRow?.[f.key+'Tokens'] != null" :disabled="saving" /></label>
        <label>账单确认消耗（{{ reviewRow?.unit }}）<input v-model="review.amount" required :disabled="saving" inputmode="decimal"/></label>
        <label>供应商账单或回执编号<input v-model="review.reference" required maxlength="250" :disabled="saving"/></label>
        <el-alert v-if="formError" type="error" :closable="false" :title="formError"/>
        <div class="pool-actions"><el-button :disabled="saving" @click="reviewDialog=false">返回</el-button><el-button native-type="submit" type="primary" :loading="saving">确认入账</el-button></div>
      </form>
    </el-dialog>
    <el-dialog v-model="dialog" :title="titles[draft.kind]" width="min(540px,94vw)" :close-on-click-modal="false" :before-close="close">
      <form class="operation-form" @submit.prevent="save">
        <p>{{ target?.name }}<template v-if="target?.vendor==='dashscope'"> · {{ target.label }}</template> · {{ target?.unit }}<template v-if="draft.kind==='NATIVE_MEMBER'"> · {{ employeeName }}</template></p>
        <template v-if="draft.kind==='NATIVE_RATE'">
          <label>模型<el-select v-model="draft.model" :disabled="saving" @change="loadForm"><el-option v-for="m in target?.models" :key="m" :label="m" :value="m"/></el-select></label>
          <p class="operation-muted">{{ target?.vendor==='deepseek' ? '填写每百万 token 的最高适用单价，用于调用前预留。按回执统计 token，人民币金额凭厂家账单核对。' : '填写当前模型每百万 token 的计价。调用按提交时的单价记录，金额以供应商账单核对。' }}</p>
          <label v-for="f in priceFields" :key="f.key">{{ f.label }}<input v-model="draft[f.key]" type="text" inputmode="decimal" required :disabled="saving"></label>
        </template>
        <template v-else>
          <label>{{ draft.kind==='NATIVE_POOL'?'厂家总额度':'该员工累计限额' }}（{{ target?.unit }}）<input v-model="draft.limit" type="text" inputmode="decimal" required :disabled="saving"></label>
          <label v-if="draft.kind==='NATIVE_POOL'">启用本账本前已用（{{ target?.unit }}）<input v-model="draft.openingUsed" type="text" inputmode="decimal" required :disabled="saving || draft.version>0"></label>
          <p v-if="draft.kind==='NATIVE_MEMBER'" class="operation-muted">修改累计上限会保留已有消耗和预留。</p>
        </template>
        <el-alert v-if="formError" type="error" :closable="false" :title="formError"/>
        <div class="pool-actions"><el-button :disabled="saving" @click="dialog=false">返回</el-button><el-button native-type="submit" type="primary" :loading="saving">保存配置</el-button></div>
      </form>
    </el-dialog>
  </section>
</template>
<script setup>
import { computed,onMounted,onBeforeUnmount,ref } from 'vue'
import { captureAccountRequest } from '../api/request'
import { useAccountOperationScope } from '../composables/useAccountOperationScope'
import { operationData,operationError,utcDisplay } from '../utils/qualityOperations'
import { createUiRequestId } from '../utils/requestIdentity'
const props=defineProps({supervisor:Boolean,models:{type:Array,default:()=>[]}})
const emit=defineEmits(['active'])
const api=captureAccountRequest(), base='/api/agent/provider-budgets'
const visible=ref(false),view=ref(null),error=ref(''),loading=ref(false)
const employees=ref([]),employee=ref(null),selectedName=ref(''),dialog=ref(false),target=ref(null)
const pendingOnly=ref(false),more=ref(false),reviewDialog=ref(false),reviewRow=ref(null),review=ref({})
const reviewFields=[{key:'input',label:'输入 token'},{key:'output',label:'输出 token'}]
const basisLabels={BILL:'账单核实',USAGE:'用量回执',TARIFF:'按登记单价'}
const saving=ref(false),formError=ref(''),draft=ref({}),pending=ref(null)
const titles={NATIVE_POOL:'登记厂家额度',NATIVE_MEMBER:'分配员工限额',NATIVE_RATE:'设置模型单价'}
const statusLabels={NATIVE_RELEASE:'已释放',NATIVE_SETTLE:'已结算',IN_PROGRESS:'进行中',NEEDS_REVIEW:'待核对'}
const priceFields=[{key:'input',label:'未缓存输入单价'},{key:'cached',label:'缓存输入单价'},{key:'output',label:'输出单价'}]
const modelQuery=ref('')
const names={openai:'OpenAI',dashscope:'阿里云百炼',deepseek:'DeepSeek'}
const units={openai:'USD',dashscope:'TOKEN',deepseek:'CNY'}
const scope=useAccountOperationScope(()=>{view.value=null;visible.value=false;reviewDialog.value=false;reviewRow.value=null;employee.value=null;selectedName.value='';employees.value=[];dialog.value=false;target.value=null;pending.value=null;error.value='';formError.value='';saving.value=false;emit('active',false)})
const read=scope.channel(),staffRead=scope.channel()
const employeeName=computed(()=>selectedName.value||String(employee.value||''))
const groups=computed(()=>{
  const map=new Map()
  const ids=[...props.models.map(m=>m.modelId),...(view.value?.accounts||[]).map(a=>a.key).filter(k=>k.includes(':'))]
  for(const id of new Set(ids)){
    const vendor=id.split(':')[0].replace('openai-official','openai')
    if(!names[vendor])continue
    const key=vendor==='dashscope'?id:vendor
    if(!map.has(key))map.set(key,{key,vendor,name:names[vendor],unit:units[vendor],models:[]})
    map.get(key).models.push(id)
  }
  const accounts=view.value?.accounts||[]
  return [...map.values()].map(g=>({...g,label:g.vendor==='dashscope'?g.models[0].split(':')[1]:'账户内模型共享',
    pool:accounts.find(a=>a.kind==='NATIVE_POOL' && a.key===g.key),
    member:accounts.find(a=>a.kind==='NATIVE_MEMBER' && a.key===g.key)}))
})
const sharedGroups=computed(()=>groups.value.filter(group=>group.vendor!=='dashscope'))
const bailianGroups=computed(()=>groups.value.filter(group=>group.vendor==='dashscope'))
const matchingBailian=computed(()=>bailianGroups.value.filter(group=>group.label.toLowerCase().includes(modelQuery.value.toLowerCase())))
const tokens=new Intl.NumberFormat('zh-CN')
function tokenField(account,key,empty='—'){
  const value=account?.[key]
  return value==null ? empty : tokens.format(BigInt(value))
}
function field(row,key,empty='—'){return row?.[key]??empty}
async function load(append=false){
  append=append===true && !!view.value?.usage?.length && more.value

  const stamp=read.begin();loading.value=true;error.value=''
  try{
    const data=operationData(await api.get(base,{params:{employeeId:employee.value||undefined,pending:pendingOnly.value,before:append?view.value.usage.at(-1).attempt:undefined},signal:stamp.signal}))
    if(read.current(stamp)){more.value=data.usage.length===50;if(append)data.usage=[...view.value.usage,...data.usage];view.value=data;visible.value=true;emit('active',true)}
  }catch(e){if(read.current(stamp)){view.value=null;const status=e.httpStatus||e.response?.status;visible.value=status!==404;error.value=operationError(e)}}
  finally{if(read.current(stamp))loading.value=false}
}
function older(){load(true)}
function openReview(row){reviewRow.value=row;review.value={input:String(row.inputTokens??''),output:String(row.outputTokens??''),amount:'',reference:''};formError.value='';pending.value=null;reviewDialog.value=true}
async function confirmReview(){
  if(saving.value)return
  const d=review.value,payload={input:Number(d.input),output:Number(d.output),amount:d.amount.trim(),reference:d.reference.trim()}
  if(![d.input,d.output].every(n=>/^\d+$/.test(n)&&Number.isSafeInteger(Number(n))) || !/^\d+(\.\d+)?$/.test(payload.amount) || !payload.reference){
    formError.value='请核对用量、金额与账单编号';return
  }
  const serial=JSON.stringify(payload)
  if(pending.value?.serial!==serial)pending.value={serial,id:createUiRequestId()}
  const stamp=scope.stamp();saving.value=true;formError.value=''
  try{operationData(await api.post(base+'/attempts/'+reviewRow.value.attempt+'/review',{...payload,requestId:pending.value.id},{headers:{'X-Budget-Action':'update'}}))
    if(scope.current(stamp)){reviewDialog.value=false;pending.value=null;await load()}}
  catch(e){if(scope.current(stamp))formError.value=operationError(e)}
  finally{if(scope.current(stamp))saving.value=false}
}
async function search(query){
  const stamp=staffRead.begin()
  try{const rows=operationData(await api.get(base+'/employees',{params:{query},signal:stamp.signal}));if(staffRead.current(stamp))employees.value=rows}
  catch(e){if(staffRead.current(stamp))error.value=operationError(e)}
}
function openSearch(open){if(open)search('')}
function switchEmployee(){selectedName.value=employees.value.find(x=>x.id===employee.value)?.name||'';view.value=null;load()}
function edit(kind,group){target.value=group;draft.value={kind,model:group.models[0]};loadForm();dialog.value=true}
function loadForm(){
  const d=draft.value,g=target.value
  const row=d.kind==='NATIVE_RATE'?view.value.accounts.find(a=>a.kind===d.kind&&a.key===d.model):d.kind==='NATIVE_MEMBER'?g.member:g.pool
  Object.assign(d,{limit:row?.limit??'',openingUsed:row?.openingUsed??'',version:row?.version??0,
    input:row?.rates?.input??'',cached:row?.rates?.cached??'',output:row?.rates?.output??''})
  formError.value='';pending.value=null
}
function close(done){if(!saving.value)done()}
async function save(){
  const d=draft.value
  if(saving.value || !target.value)return
  const payload={kind:d.kind,model:d.model,expectedVersion:d.version}
  if(d.kind==='NATIVE_MEMBER')payload.employeeId=employee.value
  const fields=d.kind==='NATIVE_RATE'?['input','cached','output']:d.kind==='NATIVE_POOL'?['limit','openingUsed']:['limit']
  const regex=target.value.unit==='TOKEN'?/^\d+$/:/^\d+(\.\d+)?$/
  for(const key of fields){
    payload[key]=String(d[key]).trim()
    if(!regex.test(payload[key])){formError.value='请填写有效的非负额度或单价，token 须为整数';return}
  }
  const serial=JSON.stringify(payload)
  if(pending.value?.serial!==serial)pending.value={serial,id:createUiRequestId()}
  const stamp=scope.stamp();saving.value=true;formError.value=''
  try{operationData(await api.put(base,{...payload,requestId:pending.value.id},{headers:{'X-Budget-Action':'update'}}))
    if(scope.current(stamp)){dialog.value=false;pending.value=null;await load()}}
  catch(e){if(scope.current(stamp))formError.value=operationError(e)}
  finally{if(scope.current(stamp))saving.value=false}
}
function onFocus(){
  if(document.visibilityState==='visible' && visible.value && !loading.value && !dialog.value && !reviewDialog.value && (view.value?.usage.length||0)<=50)load()
}
let timer
onMounted(()=>{
  load()
  window.addEventListener('focus',onFocus)
  timer=window.setInterval(onFocus,15000)
})
onBeforeUnmount(()=>{window.removeEventListener('focus',onFocus);window.clearInterval(timer)})
</script>
<style scoped>
.provider-budget{padding:22px;display:grid;gap:16px}.budget-heading,.pool-card header,.balance-row,.pool-actions{display:flex;align-items:center;justify-content:space-between;gap:10px}.budget-heading h2,.pool-card h3,.provider-budget h3,.provider-budget p{margin:0}.employee-picker{display:flex;align-items:center;gap:12px}.employee-picker .el-select{max-width:260px}.budget-pools{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(245px,100%),1fr));gap:12px}.pool-card{min-width:0;background:var(--app-surface-muted);border:1px solid var(--app-border);border-radius:10px;padding:16px;display:grid;align-content:start;gap:12px}.pool-card small,.pool-card dt,.pool-card details{color:var(--app-text-secondary)}.pool-card header strong{color:var(--app-primary)}.pool-card dl{display:flex;gap:16px;flex-wrap:wrap;margin:0}.pool-card dd{margin:0;font-variant-numeric:tabular-nums}.pool-card b{overflow-wrap:anywhere}.pool-actions{justify-content:flex-start;flex-wrap:wrap}.pool-actions :deep(.el-button){margin-left:0}.ledger-wrap{overflow:auto}.ledger-wrap table{width:100%;border-collapse:collapse}.ledger-wrap th,.ledger-wrap td{text-align:left;padding:10px;border-bottom:1px solid var(--app-border);font-variant-numeric:tabular-nums}.operation-form input{min-height:38px;border:1px solid var(--app-border);border-radius:6px;padding:0 10px;color:var(--app-text)}.provider-budget summary{cursor:pointer}.pool-card details p{margin-top:6px}
.shared-models,.bailian-heading p{color:var(--app-text-secondary);overflow-wrap:anywhere}
.bailian-budget{min-width:0;display:grid;gap:12px}
.bailian-heading{flex-wrap:wrap}
.model-search{display:flex;align-items:center;gap:8px;font-size:.875rem}
.model-search input{min-height:38px;padding:0 10px;border:1px solid var(--app-border);border-radius:6px;background:var(--app-surface);color:inherit}
.bailian-table{font-variant-numeric:tabular-nums}
.bailian-table thead{background:var(--app-surface-muted)}
.bailian-table tbody th{font-weight:600}
.bailian-table td,.bailian-table th{white-space:nowrap}
.bailian-table details{color:var(--app-text-secondary);font-size:.82rem}
.row-actions{display:flex;gap:6px}.row-actions :deep(.el-button){margin:0}
@media(max-width:600px){.model-search{flex-wrap:wrap}.model-search input{max-width:100%}.bailian-heading{align-items:flex-start}}
</style>
