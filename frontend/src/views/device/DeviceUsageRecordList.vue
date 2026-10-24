<template>
  <div class="page-shell usage-page">
    <PageHero title="设备使用记录" description="按历史快照查看使用员工、开始及结束时间。记录状态与设备实时在线状态分别核对。" icon="Clock">
      <template #actions>
        <el-button :loading="loading" @click="refreshRecords"><AppIcon name="Refresh" :size="16" />刷新记录</el-button>
        <el-button v-if="deviceCodeFromRoute || deviceIdFromRoute" @click="backToDeviceList"><AppIcon name="ArrowLeft" :size="16" />返回设备列表</el-button>
        <el-button v-if="isSupervisor" type="primary" :disabled="createLoading || !!routeError" @click="createRecord"><AppIcon name="Plus" :size="16" />新增记录</el-button>
      </template>
    </PageHero>
    <el-alert v-if="routeError" :title="routeError" type="error" show-icon :closable="false" />
    <div v-if="creationReceipt" class="usage-receipt" role="status"><StatusBadge domain="apiReceipt" :code="creationReceipt.state" /><p>{{ creationReceipt.message }}</p><router-link v-if="creationReceipt.deviceId" :to="{name:'deviceDetail',params:{id:creationReceipt.deviceId}}">核对设备资料<AppIcon name="ArrowRight" :size="14" /></router-link></div>

    <section class="toolbar-panel app-panel">
      <form class="usage-filter-grid" @submit.prevent="searchRecords">
        <div class="usage-filter-field"><label for="usage-device-code">设备编号</label><el-input id="usage-device-code" v-model="filters.deviceCode" placeholder="设备编号" clearable /></div>
        <div class="usage-filter-field"><label for="usage-employee-name">员工姓名</label><el-input id="usage-employee-name" v-model="filters.employeeName" placeholder="员工姓名" clearable /></div>
        <div class="usage-filter-field"><label for="usage-employee-number">员工编号</label><el-input id="usage-employee-number" v-model="filters.employeeNumber" placeholder="员工编号" clearable /></div>
        <div class="usage-filter-field"><label for="usage-status">使用状态</label><el-select id="usage-status" v-model="filters.status" placeholder="使用状态" clearable>
          <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select></div>
        <div class="usage-filter-field usage-time-field"><span>使用开始时间范围 · UTC+8</span><el-date-picker
          v-model="filters.startTimeRange"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          aria-label="使用开始时间范围，UTC+8"
          value-format="YYYY-MM-DD HH:mm:ss"
          class="date-range-picker"
        /></div>
        <div class="panel-actions">
          <el-button type="primary" native-type="submit" :loading="loading" :disabled="!!routeError"><AppIcon name="Search" :size="16" />查询</el-button>
          <el-button @click="resetFilters"><AppIcon name="Refresh" :size="16" />重置</el-button>
        </div>
      </form>
      <el-alert v-if="filterError" :title="filterError" type="warning" show-icon :closable="false" />
      <p v-if="queryDirty" class="usage-query-note" role="status">筛选条件尚未查询，列表仍保留上次查询结果。</p>
      <p v-if="deviceIdFromRoute" class="usage-query-note">当前限定设备 ID {{ deviceIdFromRoute }}，重置只清空附加条件；返回设备列表可重新选择。</p>
    </section>

    <section class="table-panel">
      <div class="collection-heading"><h2><AppIcon name="Clock" :size="18" />使用记录</h2><span>{{ loading ? '正在读取…' : listError ? '本次读取失败' : total==null?'总数尚未核对':`匹配 ${total} 条` }} · 时间 UTC+8</span></div>
      <p class="management-applied-query">已查询范围：{{ appliedDescription }}</p>
      <el-alert v-if="listError && records.length" :title="listError + '；下方保留先前读取的记录，请重新查询核对。'" type="error" show-icon :closable="false" />
      <el-button v-if="listError && records.length" class="management-retry" :loading="loading" @click="retryRecords"><AppIcon name="Refresh" :size="14" />重读上次请求</el-button>
      <TableReadHint v-if="records.length" />
      <el-table :scrollbar-tabindex="0" role="region" aria-label="设备使用记录" :data="records" v-loading="loading" row-key="id" border style="width: 100%">
        <template #empty>
          <CollectionEmptyState :loading="loading" :error="listError" :filtered="!!hasFilters" empty-title="暂无设备使用记录" :empty-description="deviceIdFromRoute ? '当前设备与已查询条件下未找到使用记录。' : '设备使用登记后，可在这里查看使用人与归还情况。'" @retry="retryRecords" @reset="resetFilters" />
        </template>
        <el-table-column label="设备资料" min-width="185"><template #default="{row}"><div class="usage-cell"><strong>{{ row.deviceCode||'设备编号未记录' }}</strong><small>{{ getDeviceTypeName(row.deviceType)||'类型未记录' }} · {{ row.modelName||'型号未记录' }}</small></div></template></el-table-column>
        <el-table-column label="使用人" min-width="140"><template #default="{row}"><div class="usage-cell"><strong>{{ row.employeeName||'姓名未记录' }}</strong><small>{{ row.employeeNumber||'员工编号未记录' }}</small></div></template></el-table-column>
        <el-table-column label="使用时间 · UTC+8" min-width="235"><template #default="{row}"><div class="usage-cell"><strong>开始 {{ formatDateTime(row.startTime) }}</strong><small>结束 {{ row.endTime ? formatDateTime(row.endTime) : ['IN_USE','使用中'].includes(row.status) ? '使用中，尚无结束时间' : '未记录' }}</small></div></template></el-table-column>
        <el-table-column label="使用状态" width="110">
          <template #default="{ row }">
            <StatusBadge domain="usage" :code="row.status" :label="getStatusLabel(row.status)" />
          </template>
        </el-table-column>
        <el-table-column label="详情" width="88"><template #default="{row}"><el-button text type="primary" :aria-label="'查看使用记录 '+row.id" @click="openDetails(row)"><AppIcon name="Search" :size="14" />查看</el-button></template></el-table-column>
      </el-table>

      <div v-if="total!==null" class="page-footer">
        <el-pagination
          :current-page="pagination.current"
          :page-size="pagination.size"
          :disabled="loading || !!listError || !!routeError"
          :page-sizes="[10, 20, 30, 50]"
          :pager-count="7"
          background
          layout="total, sizes, prev, pager, next, jumper"
          :total="total"
          @size-change="handleSizeChange"
          @current-change="handleCurrentChange"
        />
      </div>
    </section>

    <!-- 新增记录弹窗 -->
    <el-dialog class="usage-create-dialog" append-to-body v-model="dialogVisible" title="新增设备使用记录" width="min(560px,94vw)" :close-on-click-modal="!createLoading" :close-on-press-escape="!createLoading" :show-close="!createLoading">
      <p class="usage-form-note">保存会登记一条使用中记录，并更新设备状态与使用员工。先填写，再核对关系变化；不代表设备已在线或检测任务已经开始。</p>
      <el-alert v-if="optionsError" :title="optionsError" type="error" show-icon :closable="false" /><el-button v-if="optionsError" :loading="optionsLoading" @click="loadOptions">重新读取选项</el-button>
      <el-alert v-if="createError" :title="createError" type="error" show-icon :closable="false" />
      <p v-if="optionsLoading" role="status" class="usage-form-note">正在读取当前账号可选择的设备与员工…</p>
      <p v-else-if="optionsLoaded&&!optionsError" class="usage-form-note">本次读取 {{ deviceOptions.length }} 个设备、{{ employeeOptions.length }} 位员工，每类最多 999 项。搜索仅在本次候选内进行，未找到时请先核对原资料。</p>
      <el-form v-if="!createProposal" :model="createForm" :rules="createRules" ref="createFormRef" label-position="top" scroll-to-error :disabled="createLoading||!optionsLoaded||!!optionsError" @submit.prevent="prepareCreate">
        <el-form-item label="选择设备" prop="deviceId">
          <el-select v-model="createForm.deviceId" aria-label="请选择设备" placeholder="请选择设备" style="width:100%" filterable>
            <el-option v-for="d in deviceOptions" :key="d.id" :label="`${d.deviceCode || '编号未记录'} · ${d.modelName || '型号未记录'}${uncertainCreates.has(resourceId(d.id)) ? ' · 上次保存待核对' : ''}`" :value="resourceId(d.id)" :disabled="uncertainCreates.has(resourceId(d.id))" />
          </el-select>
        </el-form-item>
        <el-form-item label="选择员工" prop="employeeId">
          <el-select v-model="createForm.employeeId" aria-label="请选择员工" placeholder="请选择员工" style="width:100%" filterable>
            <el-option v-for="e in employeeOptions" :key="e.id" :label="`${e.name || '姓名未记录'} (${e.employeeNumber || '员工编号未记录'})`" :value="resourceId(e.id)" />
          </el-select>
        </el-form-item>
        <el-form-item label="开始时间（UTC+8）" prop="startTime">
          <el-date-picker v-model="createForm.startTime" type="datetime" aria-label="选择开始时间" placeholder="选择开始时间" style="width:100%" value-format="YYYY-MM-DDTHH:mm:ss" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="createForm.remarks" type="textarea" aria-label="可选备注" placeholder="可选备注" />
        </el-form-item>
      </el-form>
      <Transition name="usage-review"><section v-if="createProposal" ref="proposalRef" tabindex="-1" class="usage-create-review" aria-label="核对使用登记及设备关系变化">
        <h3><AppIcon name="DocumentChecked" :size="18" />核对登记与设备变更</h3>
        <dl class="usage-detail-facts"><dt>目标设备</dt><dd>{{ createProposal.deviceLabel }}<small>ID {{ createProposal.payload.deviceId }}</small></dd><dt>登记使用员工</dt><dd>{{ createProposal.employeeLabel }}<small>ID {{ createProposal.payload.employeeId }}</small></dd><dt>当前设备使用员工</dt><dd>{{ createProposal.ownerLabel }}</dd><dt>当前设备状态</dt><dd><StatusBadge domain="device" :code="createProposal.deviceStatus" /></dd><dt>实际开始时间 · UTC+8</dt><dd>{{ formatDateTime(createProposal.payload.startTime) }}</dd><dt>备注</dt><dd>{{ createProposal.payload.remarks || '未填写' }}</dd></dl>
        <el-alert :type="createProposal.reassign ? 'warning' : 'info'" :title="createProposal.reassign ? '保存将更换设备登记的当前使用员工，并将设备状态改为使用中；不会为原员工自动登记归还。' : '保存将设备状态更新为使用中，并登记所选员工；不是检测任务提交或在线确认。'" show-icon :closable="false" />
      </section></Transition>
      <p v-if="createLoading" role="status" class="usage-form-note">{{ createPhase==='SENDING' ? '正在等待保存回执，请勿重复提交' : '正在验证输入并核对当前设备与人员资料，尚未发送保存' }}</p>
      <template #footer>
        <el-button :disabled="createLoading" @click="dialogVisible = false"><AppIcon name="Close" :size="16" />取消</el-button>
        <el-button v-if="createProposal" :disabled="createLoading" @click="backToCreate">返回修改</el-button>
        <el-button v-if="createProposal" :type="createProposal.reassign ? 'danger' : 'primary'" :loading="createLoading" @click="handleCreate"><AppIcon name="DocumentChecked" :size="15" />确认保存并更新设备</el-button>
        <el-button v-else type="primary" :loading="createLoading" :disabled="!optionsLoaded||!!optionsError||uncertainCreates.has(resourceId(createForm.deviceId))" @click="prepareCreate"><AppIcon name="Search" :size="15" />核对登记</el-button>
      </template>
    </el-dialog>
    <el-dialog class="usage-detail-dialog" append-to-body v-model="detailVisible" title="设备使用记录详情" width="min(720px,94vw)">
      <template v-if="selectedRecord"><div class="usage-detail-heading"><AppIcon name="Monitor" :size="25" /><div><strong>{{ selectedRecord.deviceCode||'设备编号未记录' }}</strong><p>使用记录 {{ selectedRecord.id??'未记录' }}</p></div><StatusBadge domain="usage" :code="selectedRecord.status" :label="getStatusLabel(selectedRecord.status)" /></div><p class="usage-form-note">设备和员工资料为记录创建时的历史快照，可能与当前资料不同。</p>
       <dl class="usage-detail-facts"><template v-for="field in detailFacts" :key="field.label"><dt>{{ field.label }}</dt><dd>{{ field.value }}</dd></template></dl>
      </template>
      <template #footer><el-button v-if="resourceId(selectedRecord?.deviceId)" @click="router.push({name:'deviceDetail',params:{id:resourceId(selectedRecord.deviceId)}})"><AppIcon name="Monitor" :size="15" />当前设备资料</el-button><el-button v-if="resourceId(selectedRecord?.employeeId)" @click="router.push({name:'employeeDetail',params:{id:resourceId(selectedRecord.employeeId)}})"><AppIcon name="User" :size="15" />当前人员资料</el-button><el-button @click="detailVisible=false">关闭详情</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import request from '../../api/request'
import { beijingDateTime } from '@/utils/beijingTime'
import { useUserStore } from '@/stores/user'
import CollectionEmptyState from '@/components/CollectionEmptyState.vue'
import { knownCount } from '@/utils/countPresentation'

const router=useRouter(), route=useRoute(), userStore=useUserStore()
const resourceId=value=>typeof value==='number' && Number.isSafeInteger(value) && value>0 ? String(value) : typeof value==='string' && /^[1-9]\d*$/.test(value) ? value : ''
const deviceCodeFromRoute=computed(()=>typeof route.query.deviceCode==='string'?route.query.deviceCode:'')
const deviceIdFromRoute=computed(()=>resourceId(route.query.deviceId))
const routeError=computed(()=>route.query.deviceId!=null && !deviceIdFromRoute.value ? '链接中的设备 ID 无效，请返回设备列表重新选择，未改成全设备查询。' : route.query.deviceCode!=null && typeof route.query.deviceCode!=='string' ? '链接中的设备编号无效，请返回设备列表重新选择。' : '')
const actor=computed(()=>JSON.stringify([userStore.identity?.userId || userStore.username || '',userStore.role,userStore.isAuthenticated]))
const contextKey=computed(()=>JSON.stringify([route.query.deviceId,route.query.deviceCode,actor.value]))
const isSupervisor=computed(()=>userStore.isAuthenticated && userStore.role==='SUPERVISOR')
const records=ref([]), loading=ref(false), total=ref(null), listError=ref(''), filterError=ref('')
const appliedQuery=ref(null), requestedQuery=ref(null)
const pagination=reactive({current:1,size:10})
const filters=reactive({deviceCode:deviceCodeFromRoute.value,employeeName:'',employeeNumber:'',status:'',startTimeRange:[]})
const detailVisible=ref(false),selectedRecord=ref(null)
const statusOptions=[{value:'IN_USE',label:'使用中'},{value:'RETURNED',label:'已归还'}]
let disposed=false, listGeneration=0, optionsGeneration=0, createGeneration=0, pendingListKey=''
const active=context=>!disposed && contextKey.value===context
const currentList=(generation,context)=>active(context) && generation===listGeneration
function readData(response){
  if(response.data?.code!==200){const error=new Error(response.data?.message || '资料读取未成功');error.httpStatus=response.data?.code;throw error}
  return response.data.data
}
function resourceList(value){
  if(!Array.isArray(value))throw new Error('列表资料未完整读取')
  const ids=new Set()
  for(const row of value){const key=resourceId(row?.id);if(!key || ids.has(key))throw new Error('列表资源编号未完整读取');ids.add(key)}
  return value
}
const denied=error=>[401,403].includes(error.response?.status || error.httpStatus)
const getDeviceTypeName=type=>({DETECTION:'图像检测设备',IMAGE_CAPTURE:'图片采集设备'})[type] || type || '类型未记录'
const getStatusLabel=status=>({IN_USE:'使用中','使用中':'使用中',RETURNED:'已归还','已归还':'已归还'})[status] || status || '状态未记录'
const formatDateTime=value=>value?beijingDateTime(value) || '时间格式未知':'未记录'
function filterSnapshot(){
  return {deviceId:deviceIdFromRoute.value,deviceCode:filters.deviceCode.trim(),employeeName:filters.employeeName.trim(),employeeNumber:filters.employeeNumber.trim(),status:filters.status || '',startTimeRange:Array.isArray(filters.startTimeRange)?[...filters.startTimeRange]:[]}
}
const queryDirty=computed(()=>!!appliedQuery.value && JSON.stringify(appliedQuery.value.filters)!==JSON.stringify(filterSnapshot()))
const hasFilters=computed(()=>{
  const query=appliedQuery.value?.filters || filterSnapshot()
  return !!(query.deviceCode!==deviceCodeFromRoute.value || query.employeeName || query.employeeNumber || query.status || query.startTimeRange.length)
})
const appliedDescription=computed(()=>{
  if(!appliedQuery.value)return '尚未完成读取'
  const query=appliedQuery.value.filters
  return [query.deviceId?`设备 ID ${query.deviceId}`:'',query.deviceCode?`设备编号 ${query.deviceCode}`:'',query.employeeName?`员工姓名 ${query.employeeName}`:'',query.employeeNumber?`员工编号 ${query.employeeNumber}`:'',query.status?getStatusLabel(query.status):'',query.startTimeRange.length===2?`${query.startTimeRange[0]} 至 ${query.startTimeRange[1]}（UTC+8）`:''].filter(Boolean).join(' · ') || '当前账号可访问的全部使用记录'
})
function clearList(){records.value=[];total.value=null;detailVisible.value=false;selectedRecord.value=null}
async function fetchRecords(query){
  if(disposed || !userStore.isAuthenticated)return false
  if(routeError.value){listError.value=routeError.value;clearList();return false}
  const range=query.filters.startTimeRange
  if(range.length && (range.length!==2 || range.some(value=>typeof value!=='string' || !/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value)) || range[0]>range[1])){filterError.value='请填写完整、顺序正确的使用开始时间范围；尚未执行这组筛选。';return false}
  filterError.value=''
  const key=JSON.stringify(query), context=contextKey.value
  if(loading.value && key===pendingListKey)return false
  const generation=++listGeneration
  requestedQuery.value=query;pendingListKey=key
  if(key!==JSON.stringify(appliedQuery.value))clearList()
  loading.value=true;listError.value=''
  const params={page:query.page,size:query.size,...Object.fromEntries(Object.entries(query.filters).filter(([key,value])=>key!=='startTimeRange' && value!==''))}
  if(range.length===2){params.startTimeBegin=range[0];params.startTimeEnd=range[1]}
  try{
    const response=await request.get('/api/device-usage-records',{params})
    if(!currentList(generation,context))return false
    const data=readData(response),rows=resourceList(data?.records),count=knownCount(data.total)
    if(query.page>1 && !rows.length && count!==null && count<=(query.page-1)*query.size)return await fetchRecords({...query,page:1})
    records.value=rows;total.value=count;appliedQuery.value=query
    pagination.current=query.page;pagination.size=query.size
    return true
  }catch(error){
    if(!currentList(generation,context))return false
    if(denied(error)){clearList();appliedQuery.value=null}
    listError.value=error.response?.data?.message || error.message || '使用记录暂不可读取，请重新核对'
    return false
  }finally{if(currentList(generation,context))loading.value=false}
}
const searchRecords=()=>fetchRecords({page:1,size:pagination.size,filters:filterSnapshot()})
const refreshRecords=()=>fetchRecords(loading.value && requestedQuery.value ? requestedQuery.value : appliedQuery.value || requestedQuery.value || {page:1,size:pagination.size,filters:filterSnapshot()})
const retryRecords=()=>fetchRecords(requestedQuery.value || {page:1,size:pagination.size,filters:filterSnapshot()})
const handleSizeChange=size=>Number.isSafeInteger(size)&&size>0?fetchRecords({page:1,size,filters:appliedQuery.value?.filters || filterSnapshot()}):undefined
const handleCurrentChange=page=>Number.isSafeInteger(page)&&page>0?fetchRecords({page,size:pagination.size,filters:appliedQuery.value?.filters || filterSnapshot()}):undefined
function resetFilters(){filters.deviceCode=deviceCodeFromRoute.value;filters.employeeName='';filters.employeeNumber='';filters.status='';filters.startTimeRange=[];return searchRecords()}
const backToDeviceList=()=>router.push({name:'devices'})
function openDetails(row){if(!records.value.some(item=>resourceId(item.id)===resourceId(row?.id)))return;selectedRecord.value=Object.freeze({...row});detailVisible.value=true}
const detailFacts=computed(()=>{
  const row=selectedRecord.value || {}
  return [['设备 ID',row.deviceId],['设备类型',getDeviceTypeName(row.deviceType)],['设备型号',row.modelName],['设备序列号',row.serialNumber],['员工姓名',row.employeeName],['员工编号',row.employeeNumber],['员工 ID',row.employeeId],['联系方式',row.contact],['开始时间 · UTC+8',formatDateTime(row.startTime)],['结束时间 · UTC+8',row.endTime?formatDateTime(row.endTime):['IN_USE','使用中'].includes(row.status)?'使用中，尚无结束时间':'未记录'],['备注',row.remarks],['登记时间 · UTC+8',formatDateTime(row.createdTime)],['更新时间 · UTC+8',formatDateTime(row.updatedTime)]].map(([label,value])=>({label,value:value==null || value===''?'未记录':value}))
})

const dialogVisible=ref(false),createPhase=ref('IDLE'),createFormRef=ref(null),proposalRef=ref(null)
const createLoading=computed(()=>createPhase.value!=='IDLE')
const createError=ref(''),createProposal=ref(null),creationReceipt=ref(null),uncertainCreates=ref(new Map())
const deviceOptions=ref([]),employeeOptions=ref([]),optionsLoading=ref(false),optionsError=ref(''),optionsLoaded=ref(false)
const createForm=reactive({deviceId:null,employeeId:null,startTime:'',remarks:''})
const createRules={deviceId:[{required:true,message:'请选择设备',trigger:'change'}],employeeId:[{required:true,message:'请选择员工',trigger:'change'}],startTime:[{required:true,message:'请选择开始时间',trigger:'change'}]}
const currentCreate=(generation,context)=>active(context) && generation===createGeneration && dialogVisible.value && isSupervisor.value
async function createRecord(){
  if(disposed || !isSupervisor.value || createLoading.value || dialogVisible.value || routeError.value)return
  createGeneration++;createError.value='';createProposal.value=null;optionsLoaded.value=false;optionsError.value=''
  Object.assign(createForm,{deviceId:deviceIdFromRoute.value || null,employeeId:null,startTime:'',remarks:''})
  dialogVisible.value=true
  await nextTick()
  if(!dialogVisible.value || disposed)return
  createFormRef.value?.clearValidate()
  await loadOptions()
}
async function loadOptions(){
  if(disposed || optionsLoading.value || createLoading.value || !dialogVisible.value || !isSupervisor.value)return
  const generation=++optionsGeneration,context=contextKey.value
  optionsLoading.value=true;optionsLoaded.value=false;optionsError.value='';deviceOptions.value=[];employeeOptions.value=[];createProposal.value=null
  try{
    const [deviceRead,employeeRead]=await Promise.all([request.get('/api/devices',{params:{page:1,size:999}}),request.get('/api/employees',{params:{page:1,size:999}})])
    if(!active(context) || generation!==optionsGeneration || !dialogVisible.value)return
    const devices=resourceList(readData(deviceRead)?.records),employees=resourceList(readData(employeeRead)?.records)
    deviceOptions.value=devices;employeeOptions.value=employees;optionsLoaded.value=true
  }catch(error){
    if(active(context) && generation===optionsGeneration && dialogVisible.value)optionsError.value=error.response?.data?.message || error.message || '设备或人员候选暂不可读取'
  }finally{if(active(context) && generation===optionsGeneration)optionsLoading.value=false}
}
async function readCreateContext(payload){
  const [deviceRead,employeeRead,ownerRead]=await Promise.all([request.get(`/api/devices/${payload.deviceId}`),request.get(`/api/employees/${payload.employeeId}`),request.get(`/api/devices/${payload.deviceId}/employee`)])
  const device=readData(deviceRead),employee=readData(employeeRead),owner=readData(ownerRead)
  if(resourceId(device?.id)!==payload.deviceId || resourceId(employee?.id)!==payload.employeeId || owner!==null && !resourceId(owner?.id))throw new Error('目标设备、人员或当前使用人资料未完整读取')
  const signature=JSON.stringify([resourceId(device.id),device.version ?? null,device.deviceCode ?? null,device.modelName ?? null,device.deviceType ?? null,device.status ?? null,owner===null?null:[resourceId(owner.id),owner.name ?? null],resourceId(employee.id),employee.version ?? null,employee.name ?? null,employee.employeeNumber ?? null,employee.employeeType ?? null,employee.status ?? null])
  return {signature,deviceLabel:`${device.deviceCode || '编号未记录'} · ${device.modelName || '型号未记录'}`,employeeLabel:`${employee.name || '姓名未记录'}（${employee.employeeNumber || '编号未记录'}）`,ownerLabel:owner===null?'未分配':`${owner.name || '姓名未记录'}（ID ${resourceId(owner.id)}）`,deviceStatus:device.status,reassign:owner!==null && resourceId(owner.id)!==payload.employeeId}
}
async function prepareCreate(){
  if(disposed || !dialogVisible.value || !isSupervisor.value || createLoading.value || !optionsLoaded.value || optionsError.value || !createFormRef.value || createProposal.value)return
  const generation=++createGeneration,context=contextKey.value
  createPhase.value='VALIDATING';createError.value=''
  try{
    const valid=await createFormRef.value.validate().catch(()=>false)
    if(!currentCreate(generation,context) || !valid)return
    const payload=Object.freeze({deviceId:resourceId(createForm.deviceId),employeeId:resourceId(createForm.employeeId),startTime:createForm.startTime,remarks:createForm.remarks})
    if(!deviceOptions.value.some(row=>resourceId(row.id)===payload.deviceId) || !employeeOptions.value.some(row=>resourceId(row.id)===payload.employeeId))throw new Error('请选择本次已读取的设备与人员')
    if(uncertainCreates.value.has(payload.deviceId))throw new Error('该设备上次保存结果仍待核对，当前页面不再次提交')
    createPhase.value='VERIFYING'
    const details=await readCreateContext(payload)
    if(!currentCreate(generation,context))return
    createProposal.value=Object.freeze({...details,payload,generation,context})
    await nextTick()
    if(currentCreate(generation,context))proposalRef.value?.focus()
  }catch(error){
    if(currentCreate(generation,context))createError.value=`${error.response?.data?.message || error.message || '当前资料未核对完成'}；尚未发送保存。`
  }finally{if(currentCreate(generation,context))createPhase.value='IDLE'}
}
function backToCreate(){if(createLoading.value)return;createProposal.value=null;nextTick(()=>createFormRef.value?.clearValidate())}
function recordUnknown(proposal){
  uncertainCreates.value=new Map([...uncertainCreates.value,[proposal.payload.deviceId,proposal]])
  creationReceipt.value={state:'UNKNOWN',deviceId:proposal.payload.deviceId,message:`设备 ${proposal.deviceLabel} 的使用登记结果待核对，请刷新记录及设备资料；当前页面不会再次提交该设备的使用登记。`}
}
async function handleCreate(){
  const proposal=createProposal.value
  if(!proposal || createLoading.value || !currentCreate(proposal.generation,proposal.context) || uncertainCreates.value.has(proposal.payload.deviceId))return
  createPhase.value='VERIFYING';createError.value=''
  let sent=false
  try{
    const details=await readCreateContext(proposal.payload)
    if(!currentCreate(proposal.generation,proposal.context))return
    if(details.signature!==proposal.signature){createProposal.value=null;throw new Error('设备关系、状态或人员资料已变化，请重新核对登记')}
    createPhase.value='SENDING';sent=true
    const response=await request.post('/api/device-usage-records',proposal.payload)
    if(!currentCreate(proposal.generation,proposal.context))return
    // This existing endpoint acknowledges a void command with code 200; it does not return a record ID or Boolean.
    if(response.data?.code===200){
      creationReceipt.value={state:'SUCCEEDED',deviceId:proposal.payload.deviceId,message:`已收到设备 ${proposal.deviceLabel} 的使用登记成功回执；请核对刷新后的记录与设备关系。`}
      createPhase.value='IDLE';dialogVisible.value=false;refreshRecords();return
    }
    const error=new Error(response.data?.message || '接口未确认保存成功');error.httpStatus=response.data?.code;throw error
  }catch(error){
    if(!currentCreate(proposal.generation,proposal.context))return
    const status=error.response?.status || error.httpStatus
    const unknown=sent && (!status || status>=500)
    if(unknown){recordUnknown(proposal);createError.value='保存结果待核对，请关闭窗口后刷新记录及设备资料；当前页面不再次提交该设备。'}
    else createError.value=`${error.response?.data?.message || error.message || '保存未成功'}${sent?'；接口未确认保存成功。':'；尚未发送保存。'}`
    createProposal.value=null
  }finally{if(active(proposal.context) && proposal.generation===createGeneration)createPhase.value='IDLE'}
}
watch(dialogVisible,open=>{
  if(!open){optionsGeneration++;createGeneration++;optionsLoading.value=false;createPhase.value='IDLE';createProposal.value=null;deviceOptions.value=[];employeeOptions.value=[];optionsLoaded.value=false}
},{flush:'sync'})
watch(contextKey,(context,previous)=>{
  const sameActor=previous && JSON.parse(previous)[2]===actor.value
  if(sameActor && createPhase.value==='SENDING' && createProposal.value)recordUnknown(createProposal.value)
  if(!sameActor){uncertainCreates.value=new Map();creationReceipt.value=null}
  listGeneration++;optionsGeneration++;createGeneration++;pendingListKey=''
  clearList();loading.value=false;appliedQuery.value=null;requestedQuery.value=null;listError.value='';filterError.value=''
  dialogVisible.value=false;createPhase.value='IDLE';createProposal.value=null;createError.value='';optionsLoading.value=false;optionsLoaded.value=false;deviceOptions.value=[];employeeOptions.value=[];optionsError.value=''
  Object.assign(createForm,{deviceId:null,employeeId:null,startTime:'',remarks:''})
  pagination.current=1;filters.deviceCode=deviceCodeFromRoute.value;filters.employeeName='';filters.employeeNumber='';filters.status='';filters.startTimeRange=[]
  if(routeError.value){listError.value=routeError.value;return}
  if(userStore.isAuthenticated)searchRecords()
},{immediate:true,flush:'sync'})
onBeforeUnmount(()=>{disposed=true;listGeneration++;optionsGeneration++;createGeneration++})
</script>

<style scoped>
.usage-page {
  gap: 18px;
}

.usage-filter-grid {
  display: grid;
  grid-template-columns:repeat(4,minmax(0,1fr));
  gap: 14px 16px;
  align-items: end;
}

.usage-filter-grid .el-input,
.usage-filter-grid .el-select {
  width: 100%;
  max-width: 100%;
}

.date-range-picker {
  width: 100%;
  max-width: 100%;
}
.usage-filter-field{display:grid;gap:7px;min-width:0}.usage-filter-field>label,.usage-filter-field>span{font-size:12px;color:var(--app-text-secondary);font-weight:550}.usage-time-field{grid-column:span 2}.usage-filter-grid>.panel-actions{grid-column:span 2;justify-content:flex-start}.usage-query-note{font-size:12px;line-height:1.8;color:var(--app-text-secondary);margin:14px 0 0}.usage-cell{display:grid;gap:5px;line-height:1.8;padding:3px 0;min-width:0}.usage-cell strong{font-size:13px;font-weight:550;color:var(--app-text);overflow-wrap:anywhere}.usage-cell small{font-size:12px;color:var(--app-text-secondary);overflow-wrap:anywhere}.usage-form-note{font-size:12px;color:var(--app-text-secondary);line-height:1.9;margin:0 0 16px}.usage-detail-heading{display:flex;align-items:center;flex-wrap:wrap;gap:12px;padding-bottom:16px;border-bottom:1px solid var(--app-border)}.usage-detail-heading>.el-icon{color:var(--app-primary);padding:10px;box-sizing:content-box;border-radius:10px;background:var(--app-primary-soft)}.usage-detail-heading>div{flex:1;min-width:120px}.usage-detail-heading strong{font-size:17px;color:var(--app-text);overflow-wrap:anywhere}.usage-detail-heading p{font-size:12px;color:var(--app-text-secondary);margin:5px 0 0}.usage-detail-heading+.usage-form-note{margin:14px 0}.usage-detail-facts{display:grid;grid-template-columns:140px minmax(0,1fr);gap:12px 18px;font-size:13px;line-height:1.9}.usage-detail-facts dt{color:var(--app-text-secondary)}.usage-detail-facts dd{margin:0;min-width:0;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--app-text)}@media(max-width:860px){.usage-filter-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:540px){.usage-filter-grid{grid-template-columns:1fr}.usage-time-field,.usage-filter-grid>.panel-actions{grid-column:auto}.usage-detail-facts{grid-template-columns:1fr;gap:3px}.usage-detail-facts dd{margin-bottom:10px}}
.usage-receipt { display:flex; align-items:flex-start; flex-wrap:wrap; gap:10px 14px; padding:14px 16px; border:1px solid var(--app-border); border-radius:10px; background:var(--app-surface,#fff); }
.usage-receipt p { flex:1 1 260px; margin:0; color:var(--app-text-secondary); font-size:12px; line-height:1.9; overflow-wrap:anywhere; }
.usage-receipt a { display:inline-flex; align-items:center; gap:6px; color:var(--app-primary); font-size:12px; line-height:1.9; text-decoration:none; }
.usage-receipt a:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
.usage-create-review { outline-offset:4px; }
.usage-create-review h3 { display:flex; align-items:center; gap:8px; margin:4px 0 18px; font-size:15px; font-weight:600; color:var(--app-text); }
.usage-create-review h3 > .el-icon { color:var(--app-primary); }
.usage-create-review dd small { display:block; margin-top:4px; font-size:12px; color:var(--app-text-secondary); }
.usage-review-enter-active,.usage-review-leave-active { transition:opacity 180ms ease,transform 180ms ease; }
.usage-review-enter-from,.usage-review-leave-to { opacity:0;transform:translateY(4px); }
@media(prefers-reduced-motion:reduce) { .usage-review-enter-active,.usage-review-leave-active { transition:none;transform:none; } }
</style>
<style>
:is(.usage-create-dialog,.usage-detail-dialog) .el-dialog__body { max-height:70dvh; overflow-y:auto; overscroll-behavior:contain; }
:is(.usage-create-dialog,.usage-detail-dialog) .el-dialog__footer { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:8px; }
:is(.usage-create-dialog,.usage-detail-dialog) .el-dialog__footer .el-button + .el-button { margin-left:0; }
@media(prefers-reduced-motion:reduce) { :is(.usage-create-dialog,.usage-detail-dialog),.el-overlay:has(:is(.usage-create-dialog,.usage-detail-dialog)) { animation:none!important;transition:none!important; } }
</style>
