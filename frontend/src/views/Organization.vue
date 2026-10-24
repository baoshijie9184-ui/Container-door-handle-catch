<template>
  <div class="page-shell organization-page">
    <PageHero title="账号与组织" description="核对个人员工身份，主管可维护账号关联和部门。">
      <template #actions><el-button :loading="loading" :disabled="saving" @click="refresh"><AppIcon name="Refresh" :size="16" />刷新身份与列表</el-button></template>
    </PageHero>

    <div v-if="mutationReceipt" class="organization-mutation-receipt" role="status"><StatusBadge domain="apiReceipt" :code="mutationReceipt.state" /><p>{{ mutationReceipt.message }}</p></div>
    <section class="toolbar-panel app-panel" aria-label="我的身份" v-loading="loading">
      <h2><AppIcon name="User" :size="19" />我的身份</h2>
      <div v-if="mine" class="identity-grid">
        <div><span>登录账号</span><strong>{{ mine.username }}</strong></div>
        <div><span>系统角色</span><strong>{{ roleLabel(mine.role) }}</strong></div>
        <div><span>员工</span><strong>{{ employeeLabel(mine) }}</strong></div>
        <div><span>部门 / 班组</span><strong>{{ departmentLabel(mine) }}</strong></div>
        <div><span>员工状态</span><strong><StatusBadge v-if="mine.employeeStatus" domain="employee" :code="mine.employeeStatus" :label="statusLabel(mine.employeeStatus)" /><span v-else>{{ mine.employeeId==null?'尚未关联':'状态未记录' }}</span></strong></div>
        <div><span>业务数据范围</span><strong>{{ scopeLabel(mine.dataScope) }}</strong></div>
      </div>
      <p v-if="mine" class="organization-scope-note"><AppIcon name="Lock" :size="15" />业务范围以当前账号授权为准，私人聊天、记忆和操作确认按账号隔离。</p>
      <el-alert v-if="error&&mine" :title="error+'；保留先前读取的身份，请刷新核对。'" type="error" :closable="false" show-icon />
      <CollectionEmptyState v-if="!mine" :loading="loading" :error="error" empty-title="身份尚未读取" empty-description="读取成功后显示员工关联及业务范围，不根据空资料推断账号权限。" @retry="retryLoad" />
    </section>

    <template v-if="isSupervisor">
      <section class="toolbar-panel" aria-labelledby="organization-department-heading">
        <div class="section-heading"><h2 id="organization-department-heading" ref="departmentHeadingRef" tabindex="-1"><AppIcon name="Collection" :size="19" />部门 / 班组 <small>{{ departmentsLoaded?'已读取 '+departments.length+' 个':'数量待核对' }}</small></h2><el-button type="primary" :disabled="loading||saving||!!error||!!departmentReadError" @click="openDepartment"><AppIcon name="Plus" :size="16" />新增部门</el-button></div>
        <el-alert v-if="departmentReadError&&departments.length" :title="departmentReadError+'；保留先前读取的部门。'" type="error" :closable="false" />
        <template v-if="departments.length">
          <label v-if="departments.length>6 || departmentQuery" class="department-local-query"><span><AppIcon name="Search" :size="14" />查找已读取部门</span><el-input ref="departmentSearchRef" v-model="departmentQuery" maxlength="200" clearable aria-label="按名称或编号查找本次已读取的部门" aria-describedby="organization-department-scope" placeholder="部门名称或 ID" /></label>
          <p id="organization-department-scope" class="department-query-scope" :role="departmentQuery.trim() ? 'status' : undefined">{{ departmentQuery.trim() ? '匹配 '+departmentMatches.length+' / 已读取 '+departments.length+' 个部门。' : '这里只显示当前已读取的部门登记。' }}查找不重新读取或修改部门，也不改变人员关联。</p>
          <div v-if="departmentMatches.length" class="department-read-region" :class="{'is-scrollable':departmentMatches.length>8}" :tabindex="departmentMatches.length>8 ? 0 : undefined" :role="departmentMatches.length>8 ? 'region' : undefined" :aria-label="departmentMatches.length>8 ? '本次已读取部门清单，可使用方向键滚动' : undefined"><ul class="department-tags" role="list"><li v-for="d in departmentMatches" :key="d.id" class="organization-department"><AppIcon name="Collection" :size="16" /><span>{{ d.name||'部门名称未记录' }}</span><small>部门 ID {{ d.id }}</small></li></ul></div>
          <CollectionEmptyState v-else filtered filtered-title="本次已读部门中没有匹配项" filtered-description="可按完整名称、部分名称或部门编号查找；不会自动新增部门。" @reset="clearDepartmentQuery" />
        </template>
        <CollectionEmptyState v-else :loading="loading" :error="departmentReadError||error" empty-title="尚未登记部门" empty-description="新增部门后，可在员工资料中选择关联；创建部门不会自动分配人员。" @retry="retryLoad" />
      </section>
      <section class="table-panel">
        <form class="account-toolbar" @submit.prevent="search">
          <h2><AppIcon name="Connection" :size="19" />账号员工关联</h2>
          <div class="organization-account-query"><label for="organization-account-query">登录账号</label><el-input id="organization-account-query" v-model="keyword" placeholder="查找登录账号" clearable /></div>
          <el-button :loading="loading" native-type="submit"><AppIcon name="Search" :size="16" />查询</el-button>
          <el-button v-if="keyword.trim()" @click="resetSearch">清空筛选</el-button>
        </form>
        <div class="collection-heading"><span>{{ total==null?'匹配总数尚未核对':'匹配 '+total+' 个账号' }} · 当前已加载 {{ accountsLoaded?accounts.length:'—' }} 个</span><span>当前查询 {{ accountsLoaded ? appliedKeyword||'全部账号' : '尚未完成读取' }}</span></div>
        <p v-if="accountsLoaded&&keyword.trim()!==appliedKeyword" class="organization-query-note" role="status">账号条件已修改，列表仍为上次查询结果，点击查询后更新。</p>
        <el-alert v-if="accountError&&accounts.length" :title="accountError+'；下方保留先前读取的账号，请重新核对。'" type="error" :closable="false" />
        <TableReadHint v-if="accounts.length" />
        <el-table :scrollbar-tabindex="0" role="region" aria-label="账号与人员关联" :data="accounts" v-loading="loading" row-key="userId">
          <template #empty><CollectionEmptyState :loading="loading" :error="accountError||error" :filtered="!!appliedKeyword" empty-title="暂无可查看账号" empty-description="这里只显示当前账号有权限查看的关联记录。" @retry="retryLoad" @reset="resetSearch" /></template>
          <el-table-column label="登录账号" min-width="175"><template #default="{row}"><div class="organization-account-cell"><strong>{{ row.username||'账号名称未记录' }}</strong><small>{{ roleLabel(row.role) }} · ID {{ row.userId }}</small></div></template></el-table-column>
          <el-table-column label="员工关联" min-width="200"><template #default="{ row }"><div class="organization-account-cell"><strong>{{ employeeLabel(row) }}</strong><small>关联版本 {{ row.bindingVersion??'未记录' }}</small></div></template></el-table-column>
          <el-table-column label="部门" min-width="140"><template #default="{ row }">{{ departmentLabel(row) }}</template></el-table-column>
          <el-table-column label="员工状态" min-width="110"><template #default="{ row }"><StatusBadge v-if="row.employeeStatus" domain="employee" :code="row.employeeStatus" :label="statusLabel(row.employeeStatus)" /><span v-else class="muted">{{ row.employeeId==null?'未关联':'状态未记录' }}</span></template></el-table-column>
          <el-table-column label="操作" min-width="220"><template #default="{ row }">
            <el-button size="small" type="primary" :disabled="loading||saving||!!error||!!accountError" @click="openBinding(row)"><AppIcon name="Connection" :size="15" />{{ row.employeeId==null?'关联员工':'调整关联' }}</el-button>
            <el-button size="small" :disabled="saving" @click="openAudit(row)"><AppIcon name="Document" :size="15" />变更记录</el-button>
          </template></el-table-column>
        </el-table>
        <div v-if="total!==null" class="page-footer"><el-pagination :current-page="page" :disabled="loading || !!error || !!accountError" :page-size="20" :total="total" layout="total, prev, pager, next" @current-change="changePage" /></div>
      </section>
    </template>

    <el-dialog class="organization-dialog" append-to-body v-model="bindingDialog" title="关联员工" width="min(540px, 94vw)" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
      <el-form v-if="selectedAccount" label-position="top" @submit.prevent="saveBinding">
        <div class="organization-binding-target"><AppIcon name="Key" :size="23" /><div><strong>{{ selectedAccount.username || '账号名称未记录' }}</strong><small>{{ roleLabel(selectedAccount.role) }} · 账号 ID {{ selectedAccount.userId }} · 版本 {{ selectedAccount.bindingVersion??'待核对' }}</small></div></div>
        <p class="muted">原关联：{{ employeeLabel(selectedAccount) }}</p>
        <el-form-item label="关联员工">
          <el-select v-model="selectedEmployee" filterable remote :remote-method="findEmployees" :loading="employeeLoading" clearable aria-label="输入姓名或从在岗员工中选择" placeholder="输入姓名或从在岗员工中选择" style="width:100%" :disabled="saving||bindingUncertain">
            <el-option v-for="e in employeeOptions" :key="e.id" :value="e.id" :label="`${e.name||'姓名未记录'} / ${e.employeeNumber||'编号未记录'} / ${e.department||'部门未记录'}`" />
          </el-select>
        </el-form-item>
        <p class="muted">清空员工后保存可解除关联。一个员工只能关联一个账号，账号角色和任务归属按原规则生效。</p>
        <p v-if="bindingChanged" class="organization-binding-change"><AppIcon :name="selectedEmployee==null?'Warning':'Connection'" :size="16" />{{ selectedEmployee==null?'将解除此账号的员工关联，不删除员工资料或历史记录。':'本次将使用所选员工编号 '+selectedEmployee+'，请核对姓名与编号。' }}</p>
        <p v-if="!bindingRevisionKnown" class="organization-binding-change">关联版本尚未核对，请关闭并刷新账号列表后再操作。</p>
        <p v-if="bindingUncertain" class="organization-binding-change">保存结果尚未确认，请先关闭并核对账号列表，不直接重复提交。</p>
        <el-alert v-if="employeeError" :title="employeeError" type="error" :closable="false" /><el-button v-if="employeeError" :disabled="saving||bindingUncertain" :loading="employeeLoading" @click="findEmployees(lastEmployeeQuery)">重新读取员工</el-button>
        <el-alert v-if="bindingError" :title="bindingError" :type="bindingUncertain ? 'warning' : 'error'" :closable="false" show-icon />
      </el-form>
      <template #footer><el-button :disabled="saving" @click="bindingDialog = false"><AppIcon name="Close" :size="16" />关闭</el-button><el-button v-if="bindingUncertain" @click="bindingDialog=false;refresh()">关闭并核对列表</el-button><el-button v-else :type="selectedEmployee==null&&bindingChanged?'danger':'primary'" :disabled="loading||!!error||!!accountError||!bindingChanged||employeeLoading||!!employeeError||!bindingRevisionKnown" :loading="saving" @click="saveBinding">{{ selectedEmployee==null&&bindingChanged?'解除员工关联':'保存员工关联' }}</el-button></template>
    </el-dialog>
    <el-dialog class="organization-dialog" append-to-body v-model="departmentDialog" title="新增部门 / 班组" width="min(480px, 94vw)" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
      <el-form label-position="top" @submit.prevent="createDepartment"><el-form-item label="部门 / 班组名称"><el-input v-model="departmentName" placeholder="填写部门或班组名称" maxlength="100" show-word-limit :disabled="saving||departmentUncertain" /></el-form-item></el-form>
      <p class="muted">创建后可在人员资料中选择该部门。</p>
      <el-alert v-if="departmentError" :title="departmentError" :type="departmentUncertain ? 'warning' : 'error'" :closable="false" /><p v-if="departmentUncertain" class="organization-binding-change">创建结果尚未核对，请先读取部门列表，避免重复创建。</p>
      <template #footer><el-button :disabled="saving" @click="departmentDialog = false"><AppIcon name="Close" :size="16" />关闭</el-button><el-button v-if="departmentUncertain" @click="departmentDialog=false;refresh()">关闭并核对部门</el-button><el-button v-else type="primary" :disabled="loading||!!error||!!departmentReadError||!departmentName.trim()" :loading="saving" @click="createDepartment">创建部门</el-button></template>
    </el-dialog>
    <el-dialog class="organization-dialog" append-to-body v-model="auditDialog" title="账号关联变更记录" width="min(720px, 94vw)">
      <div class="organization-audit-heading"><p class="muted">{{ auditUsername }} · 最近最多 50 条变更{{ auditLoaded?'，已加载 '+auditRows.length+' 条':'' }} · UTC+8</p><el-button :loading="auditLoading" @click="openAudit({username:auditUsername,userId:auditUserId})"><AppIcon name="Refresh" :size="15" />重新读取</el-button></div>
      <el-table :scrollbar-tabindex="0" role="region" aria-label="组织操作记录" :data="auditRows" v-loading="auditLoading">
        <template #empty><CollectionEmptyState :loading="auditLoading" :error="auditError" empty-title="暂无关联变更" empty-description="当前账号尚无已登记的员工关联变更记录。" @retry="openAudit({ username: auditUsername, userId: auditUserId })" /></template>
        <el-table-column label="操作" min-width="110"><template #default="{ row }"><StatusBadge domain="organizationBinding" :code="row.action" /></template></el-table-column>
        <el-table-column prop="actorUsername" label="操作账号" min-width="130" />
        <el-table-column label="员工 ID 变更" min-width="150"><template #default="{ row }">{{ row.beforeEmployeeId ?? '无' }} → {{ row.afterEmployeeId ?? '无' }}</template></el-table-column>
        <el-table-column label="版本" min-width="85"><template #default="{row}">{{ row.bindingVersion??'未记录' }}</template></el-table-column>
        <el-table-column label="时间（UTC+8）" min-width="190"><template #default="{row}">{{ formatTime(row.createdAt) }}</template></el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onBeforeUnmount, watch } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../api/request'
import { useUserStore } from '../stores/user'
import CollectionEmptyState from '../components/CollectionEmptyState.vue'
import { beijingDateTime } from '../utils/beijingTime'
import { knownCount } from '../utils/countPresentation'

const userStore = useUserStore()
const mine = ref(null), accounts = ref([]), departments = ref([]), total = ref(null), page = ref(1), keyword = ref('')
const loading = ref(false), error = ref(''), saving = ref(false)
const accountError=ref(''),departmentReadError=ref(''),accountsLoaded=ref(false),departmentsLoaded=ref(false),appliedKeyword=ref('')
const departmentQuery=ref(''),departmentSearchRef=ref(null),departmentHeadingRef=ref(null)
const actor=computed(()=>JSON.stringify([userStore.identity?.userId ?? null,userStore.username,userStore.role,userStore.isAuthenticated]))
const isSupervisor = computed(() => userStore.isAuthenticated && mine.value?.role === 'SUPERVISOR')
const lastLoad=ref(null),mutationReceipt=ref(null),uncertainBindings=ref(new Set()),uncertainDepartments=ref(new Set())
let accountGeneration=0
const currentAccount=scope=>active && accountGeneration===scope
const resourceId=value=>typeof value==='number' && Number.isSafeInteger(value) && value>0 ? String(value) : typeof value==='string' && /^[1-9]\d*$/.test(value)?value:''
function validList(value,key){
  if(!Array.isArray(value))throw new Error('列表未完整读取')
  const ids=new Set()
  for(const row of value){const id=resourceId(row?.[key]);if(!id || ids.has(id))throw new Error('列表资源编号未完整读取');ids.add(id)}
  return value
}
const departmentKey=value=>value.trim().normalize('NFC').toLowerCase()
const departmentMatches=computed(()=>{
  const query=departmentKey(departmentQuery.value)
  return query ? departments.value.filter(department=>departmentKey((typeof department.name==='string' ? department.name : '')+' '+department.id).includes(query)) : departments.value
})
async function clearDepartmentQuery(){
  const scope=actor.value
  departmentQuery.value=''
  await nextTick()
  if(active && actor.value===scope)(departmentSearchRef.value?.input || departmentHeadingRef.value)?.focus({preventScroll:true})
}
const bindingDialog = ref(false), selectedAccount = ref(null), selectedEmployee = ref(null), bindingError = ref('')
const employeeOptions = ref([]), employeeLoading = ref(false)
const employeeError=ref(''),lastEmployeeQuery=ref(''),bindingUncertain=ref(false)
const departmentDialog = ref(false), departmentName = ref('')
const departmentError=ref(''),departmentUncertain=ref(false)
const auditDialog = ref(false), auditRows = ref([]), auditLoading = ref(false), auditUsername = ref('')
const auditError = ref(''), auditUserId = ref(null)
const auditLoaded=ref(false)
const headers = { 'X-Organization-Action': 'update' }
let generation = 0, employeeGeneration = 0, auditGeneration = 0, active=true
const roleLabel = role => ({ SUPERVISOR: '主管', INSPECTOR: '检测员工', ADMIN: '管理员' })[role] || role || '未记录'
const statusLabel = status => ({ ACTIVE: '在岗', VACATION: '休假', RESIGNED: '离职' })[status] || status || '未关联'
const scopeLabel = scope => ({ SINGLE_ENTERPRISE: '全企业', OWNED_OR_ASSIGNED: '本人及分派任务' })[scope] || '范围尚未核对'
const formatTime = value => value ? beijingDateTime(value) || '时间格式未知' : '未记录'
function employeeLabel(identity){return identity?.employeeId==null?'未关联员工':`${identity.employeeName||'已关联员工，姓名未记录'} / ${identity.employeeNumber||'编号未记录'}`}
function departmentLabel(identity){return identity?.departmentName||(identity?.departmentId==null?'尚未关联部门':'部门名称未记录')}
const bindingChanged=computed(()=>!!selectedAccount.value&&String(selectedEmployee.value??'')!==String(selectedAccount.value.employeeId??''))
const bindingRevisionKnown=computed(()=>Number.isSafeInteger(selectedAccount.value?.bindingVersion)&&selectedAccount.value.bindingVersion>=0)
function unwrap(response) {
  if (response.data?.code !== 200) {const cause=new Error(response.data?.message || '请求未成功');const code=Number(response.data?.code);cause.confirmedRejection=code>=400&&code<500&&code!==408;throw cause}
  return response.data.data
}
const message = err => err.response?.data?.message || err.message || '请求失败，请重试'
const uncertainWrite=err=>!err.confirmedRejection&&(!err.response||err.response.status>=500||err.response.status===408)
function settledValue(result){if(result.status==='rejected')throw result.reason;return unwrap(result.value)}
async function load(queryOverride,pageOverride=page.value){
  if(!active || !userStore.isAuthenticated)return
  const query=typeof queryOverride==='string'?queryOverride:keyword.value.trim(),currentPage=pageOverride
  if(!Number.isSafeInteger(currentPage) || currentPage<1)return
  if(loading.value && lastLoad.value?.query===query && lastLoad.value.page===currentPage)return
  const current=++generation
  lastLoad.value={query,page:currentPage}
  if(query!==appliedKeyword.value || currentPage!==page.value){accounts.value=[];accountsLoaded.value=false;total.value=null}
  loading.value=true;error.value='';accountError.value='';departmentReadError.value=''
  try{
    const identity=unwrap(await request.get('/api/organization/me'))
    if(current!==generation)return
    if(!identity || typeof identity.username!=='string' || typeof identity.role!=='string' || identity.username!==userStore.username)throw new Error('当前账号身份尚未完整返回')
    mine.value=identity;userStore.identity=identity
    if(identity.role==='SUPERVISOR'){
      const [staff,depts]=await Promise.allSettled([request.get('/api/organization/accounts',{params:{page:currentPage,size:20,keyword:query || undefined}}),request.get('/api/organization/departments')])
      if(current!==generation)return
      try{
        const data=settledValue(staff),records=validList(data?.records,'userId'),count=knownCount(data.total)
        if(currentPage>1 && !records.length && count!==null && count<=(currentPage-1)*20){loading.value=false;return load(query,1)}
        accounts.value=records;total.value=count;accountsLoaded.value=true;appliedKeyword.value=query;page.value=currentPage
      }catch(err){if([401,403].includes(err.response?.status)){accounts.value=[];accountsLoaded.value=false;total.value=null}accountError.value=message(err)}
      try{departments.value=validList(settledValue(depts),'id');departmentsLoaded.value=true}catch(err){if([401,403].includes(err.response?.status)){departments.value=[];departmentsLoaded.value=false}departmentReadError.value=message(err)}
    }else{
      accounts.value=[];departments.value=[];total.value=null;accountsLoaded.value=false;departmentsLoaded.value=false;appliedKeyword.value=''
      employeeGeneration++;auditGeneration++;bindingDialog.value=false;departmentDialog.value=false;auditDialog.value=false
      selectedAccount.value=null;employeeOptions.value=[];auditRows.value=[]
    }
  }catch(err){
    if(current===generation){error.value=message(err);if([401,403].includes(err.response?.status)){mine.value=null;accounts.value=[];departments.value=[];total.value=null;accountsLoaded.value=false;departmentsLoaded.value=false}}
  }finally{if(current===generation)loading.value=false}
}
const refresh=()=>load(loading.value && lastLoad.value ? lastLoad.value.query : accountsLoaded.value?appliedKeyword.value:lastLoad.value?.query ?? keyword.value.trim(),loading.value && lastLoad.value?lastLoad.value.page:page.value)
const retryLoad=()=>load(lastLoad.value?.query ?? keyword.value.trim(),lastLoad.value?.page || page.value)
function search(){return load(keyword.value.trim(),1)}
function resetSearch(){keyword.value='';return search()}
function changePage(next){if(!loading.value && Number.isSafeInteger(next) && next>0)return load(appliedKeyword.value,next)}
async function findEmployees(name = '') {
  if(!active || !isSupervisor.value || !bindingDialog.value||saving.value||bindingUncertain.value)return
  const current = ++employeeGeneration
  employeeLoading.value = true;employeeError.value='';lastEmployeeQuery.value=name
  try {
    const data = unwrap(await request.get('/api/employees', { params: { page: 1, size: 100, status: 'ACTIVE', name: name || undefined } }))
    if (current === employeeGeneration) {
      const selected = employeeOptions.value.find(e => e.id === selectedEmployee.value)
      validList(data?.records,'id')
      const options = data.records
      employeeOptions.value = selected && !options.some(e => e.id === selected.id) ? [selected, ...options] : options
    }
  } catch (err) { if (current === employeeGeneration) employeeError.value=message(err)+'；请重新读取后再保存关联。' }
  finally { if (current === employeeGeneration) employeeLoading.value = false }
}
function openBinding(row) {
  if(loading.value||saving.value||error.value||accountError.value||!isSupervisor.value)return
  selectedAccount.value = { ...row }; selectedEmployee.value = row.employeeId ?? null
  employeeOptions.value = row.employeeId ? [{ id: row.employeeId, name: row.employeeName, employeeNumber: row.employeeNumber, department: row.departmentName }] : []
  bindingError.value = '';employeeError.value='';bindingUncertain.value=uncertainBindings.value.has(String(row.userId));bindingDialog.value = true; findEmployees()
}
async function saveBinding(){
  if(saving.value || loading.value || error.value || accountError.value || !selectedAccount.value || !isSupervisor.value || !bindingChanged.value || !bindingRevisionKnown.value || employeeLoading.value || employeeError.value || bindingUncertain.value)return
  const target=Object.freeze({userId:resourceId(selectedAccount.value.userId),employeeId:selectedEmployee.value==null?null:resourceId(selectedEmployee.value),version:selectedAccount.value.bindingVersion}),scope=accountGeneration
  if(!target.userId || target.employeeId==='')return
  saving.value=true;bindingError.value=''
  try{
    const result=unwrap(await request.put(`/api/organization/accounts/${target.userId}/employee`,{employeeId:target.employeeId,version:target.version},{headers}))
    if(!currentAccount(scope))return
    if(resourceId(result?.userId)!==target.userId || (target.employeeId===null?result.employeeId!=null:resourceId(result.employeeId)!==target.employeeId) || !Number.isSafeInteger(result.bindingVersion) || result.bindingVersion<0)throw new Error('未收到匹配的账号关联回执，结果待核对')
    mutationReceipt.value={state:'SUCCEEDED',message:`已收到账号 ID ${target.userId} 的关联更新回执，请核对列表及变更记录。`}
    bindingDialog.value=false;await refresh()
  }catch(err){if(currentAccount(scope)){bindingError.value=message(err);bindingUncertain.value=uncertainWrite(err);if(bindingUncertain.value){uncertainBindings.value=new Set([...uncertainBindings.value,target.userId]);mutationReceipt.value={state:'UNKNOWN',message:`账号 ID ${target.userId} 的关联结果待核对，当前页面不会重发；请读取列表与变更记录。`}}}}
  finally{if(currentAccount(scope))saving.value=false}
}
async function createDepartment(){
  if(saving.value || loading.value || error.value || departmentReadError.value || !isSupervisor.value || departmentUncertain.value)return
  const name=departmentName.value.trim(),scope=accountGeneration,key=departmentKey(name)
  if(!name)return ElMessage.warning('请输入部门名称')
  if(uncertainDepartments.value.has(key)){departmentUncertain.value=true;departmentError.value='该名称上次创建结果仍待核对，请读取部门列表，当前页面不重复提交。';return}
  saving.value=true;departmentError.value=''
  try{
    const result=unwrap(await request.post('/api/organization/departments',{name},{headers}))
    if(!currentAccount(scope))return
    if(!resourceId(result?.id) || typeof result.name!=='string' || result.name.trim()!==name)throw new Error('未收到可核对的部门登记回执')
    mutationReceipt.value={state:'SUCCEEDED',message:`已收到部门 ${result.name}（ID ${result.id}）的创建回执。人员关联仍在人员资料中维护。`}
    departmentDialog.value=false;departmentName.value='';await refresh()
  }catch(err){if(currentAccount(scope)){departmentError.value=message(err);departmentUncertain.value=uncertainWrite(err);if(departmentUncertain.value){uncertainDepartments.value=new Set([...uncertainDepartments.value,key]);mutationReceipt.value={state:'UNKNOWN',message:`部门 ${name} 的创建结果待核对，当前页面不会重复创建该名称；请重新读取部门列表。`}}}}
  finally{if(currentAccount(scope))saving.value=false}
}
function openDepartment(){if(loading.value || saving.value || error.value || departmentReadError.value || !isSupervisor.value)return;departmentName.value='';departmentError.value='';departmentUncertain.value=false;departmentDialog.value=true}
async function openAudit(row) {
  if(!active || !isSupervisor.value || !resourceId(row?.userId))return
  const current = ++auditGeneration
  auditUsername.value = row.username; auditUserId.value = row.userId; auditRows.value = []; auditError.value = ''; auditLoaded.value=false;auditDialog.value = true; auditLoading.value = true
  try {
    const data = unwrap(await request.get(`/api/organization/accounts/${row.userId}/audit`))
    if (current === auditGeneration) {if(!Array.isArray(data))throw Error('变更记录未完整返回');auditRows.value=data;auditLoaded.value=true}
  } catch (err) { if (current === auditGeneration) { auditError.value = message(err); ElMessage.error(auditError.value) } }
  finally { if (current === auditGeneration) auditLoading.value = false }
}
watch(actor,()=>{
  generation++;employeeGeneration++;auditGeneration++;accountGeneration++
  departmentQuery.value=''
  mine.value=null;accounts.value=[];departments.value=[];total.value=null;page.value=1;keyword.value='';loading.value=false;saving.value=false;error.value='';accountError.value='';departmentReadError.value='';accountsLoaded.value=false;departmentsLoaded.value=false;appliedKeyword.value='';lastLoad.value=null;mutationReceipt.value=null
  bindingDialog.value=false;departmentDialog.value=false;auditDialog.value=false;selectedAccount.value=null;selectedEmployee.value=null;employeeOptions.value=[];employeeLoading.value=false;employeeError.value='';bindingError.value='';bindingUncertain.value=false;departmentName.value='';departmentError.value='';departmentUncertain.value=false;auditRows.value=[];auditLoading.value=false;auditError.value='';auditUsername.value='';auditUserId.value=null;auditLoaded.value=false;uncertainBindings.value=new Set();uncertainDepartments.value=new Set()
  if(userStore.isAuthenticated)load('',1)
},{immediate:true,flush:'sync'})
watch(bindingDialog,open=>{if(!open){employeeGeneration++;employeeLoading.value=false}},{flush:'sync'})
watch(auditDialog,open=>{if(!open){auditGeneration++;auditLoading.value=false}},{flush:'sync'})
onBeforeUnmount(()=>{active=false;generation++;employeeGeneration++;auditGeneration++})
</script>

<style scoped>
.organization-page { gap: 18px; }
h2 { margin: 0 0 16px; font-size: 18px; color: #0f172a; }
.identity-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; }
.identity-grid div { display: flex; flex-direction: column; gap: 8px; }
.identity-grid > div > span, .muted { color: #64748b; font-size: 13px; }
.identity-grid strong { color: #0f172a; overflow-wrap: anywhere; }
.section-heading, .account-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.section-heading h2, .account-toolbar h2 { margin: 0; margin-right: auto; }
.account-toolbar .el-input { width: 220px; }
.department-tags { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 18px; list-style:none; margin:0; padding:0; }
.department-local-query { display:grid; gap:7px; margin:0 0 12px; max-width:420px; font-size:12px; line-height:1.8; color:var(--app-text-secondary); }
.department-local-query > span { display:flex; align-items:center; gap:6px; }
.department-query-scope { margin:0 0 14px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; overflow-wrap:anywhere; }
.department-read-region { min-width:0; }
.department-read-region.is-scrollable { max-height:260px; max-height:min(260px,45dvh); overflow:auto; overscroll-behavior:contain; padding:2px; scrollbar-gutter:stable; }
.department-read-region:focus-visible,#organization-department-heading:focus-visible { outline:2px solid var(--app-primary); outline-offset:-2px; border-radius:3px; }
@media(max-width:560px) { .department-tags { grid-template-columns:minmax(0,1fr); } }
.organization-scope-note{display:flex;align-items:flex-start;gap:7px;margin:16px 0 0;color:var(--app-text-secondary);font-size:12px;line-height:1.9}.organization-scope-note>.el-icon{flex:0 0 auto;margin-top:4px}.section-heading h2 small{font-size:12px;font-weight:400;color:var(--app-text-secondary);margin-left:4px}.organization-department{display:grid;grid-template-columns:20px minmax(0,1fr);gap:3px 8px;padding:12px 0;border-bottom:1px solid var(--app-border);font-size:13px;line-height:1.8;min-width:0}.organization-department>.el-icon{grid-row:1/span 2;align-self:start;margin-top:4px}.organization-department>small{grid-column:2}.organization-department>.el-icon{color:var(--app-primary)}.organization-department>span{overflow-wrap:anywhere;color:var(--app-text)}.organization-department>small{color:var(--app-text-secondary);font-size:12px}.organization-account-query{display:grid;gap:6px;min-width:0}.organization-account-query label{font-size:12px;color:var(--app-text-secondary)}.organization-account-query .el-input{max-width:100%}.account-toolbar{align-items:flex-end}.organization-account-cell{display:grid;gap:5px;padding:3px 0;line-height:1.8;min-width:0}.organization-account-cell strong{font-size:13px;font-weight:550;color:var(--app-text);overflow-wrap:anywhere}.organization-account-cell small{font-size:12px;color:var(--app-text-secondary);overflow-wrap:anywhere}.organization-query-note{font-size:12px;line-height:1.8;padding:10px 18px;margin:0;border-left:3px solid #abc7f8;color:var(--app-text-secondary);background:var(--app-primary-light)}.organization-binding-target{display:flex;align-items:flex-start;gap:12px;padding:0 0 16px;border-bottom:1px solid var(--app-border);margin-bottom:16px}.organization-binding-target>.el-icon{color:var(--app-primary);padding:10px;background:var(--app-primary-soft);border-radius:10px;box-sizing:content-box;flex-shrink:0}.organization-binding-target>div{display:grid;gap:7px;min-width:0}.organization-binding-target strong{font-size:17px;line-height:1.6;color:var(--app-text);overflow-wrap:anywhere}.organization-binding-target small{font-size:12px;line-height:1.8;color:var(--app-text-secondary);overflow-wrap:anywhere}.organization-binding-change{display:flex;gap:7px;align-items:flex-start;color:var(--app-text-secondary);padding:10px 12px;border-left:3px solid #ddac55;background:var(--app-warning-light);border-radius:0 6px 6px 0;font-size:12px;line-height:1.9}.organization-binding-change>.el-icon{flex-shrink:0;margin-top:4px;color:var(--app-warning)}.organization-audit-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.organization-audit-heading p{min-width:0;flex:1 1 260px;overflow-wrap:anywhere}.table-panel>.collection-heading{padding:13px 20px;font-size:12px;line-height:1.8}.organization-page :deep(.el-alert){margin-top:12px}
@media(max-width:640px){.identity-grid{grid-template-columns:minmax(0,1fr)}.organization-account-query{flex:1 1 100%}.organization-account-query .el-input{width:100%}.organization-department{width:100%;box-sizing:border-box}.organization-binding-target strong{font-size:16px}}
.el-button { transition: transform 160ms ease; }
.el-button:active { transform: scale(.98); }
@media (prefers-reduced-motion: reduce) { .el-button { transition: none; } .el-button:active { transform: none; } }
.organization-mutation-receipt { display:flex; align-items:flex-start; gap:12px; flex-wrap:wrap; padding:13px 16px; border:1px solid var(--app-border); border-radius:10px; background:#fff; }
.organization-mutation-receipt p { flex:1 1 260px; min-width:0; margin:0; color:var(--app-text-secondary); font-size:12px; line-height:1.85; overflow-wrap:anywhere; }
</style>
<style>
.organization-dialog .el-dialog__body { max-height:70dvh; overflow-y:auto; overscroll-behavior:contain; }
.organization-dialog .el-dialog__footer { display:flex; justify-content:flex-end; gap:8px; flex-wrap:wrap; }
.organization-dialog .el-dialog__footer .el-button + .el-button { margin-left:0; }
@media(prefers-reduced-motion:reduce) { .organization-dialog,.el-overlay:has(.organization-dialog) { animation:none!important;transition:none!important; } }
</style>
