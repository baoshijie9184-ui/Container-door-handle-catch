<template>
  <el-dialog v-model="visible" title="人员设备分配" class="employee-assignment-dialog" width="min(820px, 96vw)" append-to-body :close-on-click-modal="!locked" :close-on-press-escape="!locked" :show-close="!locked">
    <div class="assignment-person"><span class="assignment-person-icon"><AppIcon name="User" :size="23" /></span><div><strong>{{ person?.name || '人员资料尚未读取' }}</strong><p>员工编号 {{ person?.employeeNumber || '未记录' }} · 人员 ID {{ employeeId || '未记录' }}</p><p v-if="person">{{ employeeTypeLabel(person.employeeType) }} · {{ person.department || '部门未记录' }}</p></div><StatusBadge v-if="person" domain="employee" :code="person.status" /></div>
    <div class="assignment-read-heading"><p>先选择设备，再核对目标人员与设备后确认。岗位不等同账号权限，提交仍由服务端校验。</p><el-button size="small" :loading="loading" :disabled="phase!=='IDLE'" @click="loadContext()"><AppIcon name="Refresh" :size="14" />重新读取关系</el-button></div>
    <el-alert v-if="personError" :title="personError" type="error" show-icon :closable="false" />
    <p v-if="phase!=='IDLE'" class="assignment-progress" role="status"><AppIcon name="Connection" :size="16" />{{ phase==='VERIFYING' ? '正在核对当前人员与设备关系，尚未发送变更' : '正在等待设备操作回执，请稍候' }}</p>
    <section v-if="receipt" class="assignment-receipt" :data-state="receipt.state" role="status"><StatusBadge domain="apiReceipt" :code="receipt.state" /><p>{{ receipt.message }}</p><router-link v-if="receipt.deviceId && !locked" :to="{name:'deviceDetail',params:{id:receipt.deviceId}}" @click="close">查看设备登记<AppIcon name="ArrowRight" :size="14" /></router-link></section>

    <section class="assignment-select-section" aria-label="选择未分配设备">
      <h3><AppIcon name="Monitor" :size="17" />未分配设备<span>{{ optionsLoaded ? `本次读取 ${deviceOptions.length} 项` : loading ? '读取中' : '数量尚未读取' }}</span></h3>
      <el-alert v-if="optionsError" :title="optionsError" type="error" show-icon :closable="false" />
      <label :for="selectId" class="assignment-select-label">选择设备<el-select :id="selectId" ref="selectRef" v-model="selectedDeviceId" filterable clearable :disabled="!canPrepare('ASSIGN') || locked || !!proposal" placeholder="搜索本次已读取的设备编号或型号" popper-class="employee-assignment-options" no-data-text="本次未读取到未分配设备"><el-option v-for="device in deviceOptions" :key="device.id" :label="deviceLabel(device)" :value="id(device.id)" :disabled="!!assignmentReason(device)"><div class="assignment-option"><strong>{{ deviceLabel(device) }}</strong><small>{{ deviceTypeLabel(device.deviceType) }} · {{ assignmentReason(device) || '可选择，仍需核对现场可用性' }}</small></div></el-option></el-select></label>
      <p class="assignment-note">未分配不代表实时在线或现场可用。搜索只筛选本次读取的候选，设备业务状态仍需核对。</p>
      <p v-if="person && person.status!=='ACTIVE'" class="assignment-limitation"><AppIcon name="Lock" :size="15" />{{ person.status ? '当前在岗状态不允许新增分配，已有关系仍可核对并解除。' : '在岗状态未核对，暂不能新增分配。' }}</p>
      <div v-if="selectedDevice" class="assignment-selection"><div><strong>{{ deviceLabel(selectedDevice) }}</strong><span>{{ deviceTypeLabel(selectedDevice.deviceType) }}</span></div><StatusBadge domain="device" :code="selectedDevice.status" /></div>
      <el-button type="primary" :disabled="!selectedDevice || !canPrepare('ASSIGN') || locked || !!proposal || !!assignmentReason(selectedDevice)" @click="prepare('ASSIGN',selectedDevice)"><AppIcon name="DocumentChecked" :size="15" />核对分配对象</el-button>
    </section>

    <section class="assignment-current-section" aria-label="已分配设备">
      <h3><AppIcon name="Collection" :size="17" />已分配设备<span>{{ assignedLoaded ? `${assignedDevices.length} 项` : loading ? '读取中' : '数量尚未读取' }}</span></h3>
      <el-alert v-if="assignedError" :title="assignedError" type="error" show-icon :closable="false" />
      <el-table :scrollbar-tabindex="0" role="region" aria-label="目标人员已分配设备" :data="assignedDevices" row-key="id" size="small" max-height="300" v-loading="loading"><template #empty><CollectionEmptyState :loading="loading" :error="assignedError" empty-title="本次未读取到已分配设备" empty-description="重新读取当前关系后，再决定分配或解除。" @retry="loadContext()" /></template><el-table-column label="设备与型号" min-width="215"><template #default="{row}"><div class="assignment-device-identity"><strong>{{ row.deviceCode || '编号未记录' }}</strong><span>{{ row.modelName || '型号未记录' }}</span><small>{{ deviceTypeLabel(row.deviceType) }}</small></div></template></el-table-column><el-table-column label="业务状态" min-width="125"><template #default="{row}"><StatusBadge domain="device" :code="row.status" /></template></el-table-column><el-table-column label="操作" min-width="145"><template #default="{row}"><StatusBadge v-if="uncertainDevices.has(id(row.id))" domain="apiReceipt" code="UNKNOWN" label="上次操作待核对" /><el-button v-else size="small" type="danger" plain :disabled="!canPrepare('UNASSIGN') || locked || !!proposal" @click="prepare('UNASSIGN',row)"><AppIcon name="Close" :size="14" />核对解除</el-button></template></el-table-column></el-table>
    </section>

    <Transition name="assignment-review"><section v-if="proposal" ref="proposalRef" tabindex="-1" class="assignment-proposal" :aria-label="proposal.action==='ASSIGN' ? '确认分配对象' : '确认解除对象'">
      <h3><AppIcon name="Lock" :size="17" />{{ proposal.action==='ASSIGN' ? '确认设备分配' : '确认解除分配' }}</h3>
      <dl><div><dt>目标人员</dt><dd>{{ proposal.employeeName }}<small>员工编号 {{ proposal.employeeNumber }} · ID {{ proposal.employeeId }}</small></dd></div><div><dt>目标设备</dt><dd>{{ proposal.deviceCode }}<small>{{ proposal.modelName }} · ID {{ proposal.deviceId }}</small></dd></div><div><dt>人员业务岗位</dt><dd>{{ employeeTypeLabel(proposal.employeeType) }}</dd></div><div><dt>设备记录状态</dt><dd><StatusBadge domain="device" :code="proposal.deviceStatus" /></dd></div></dl>
      <p>{{ proposal.action==='ASSIGN' ? '提交设备分配并按人员业务岗位更新设备状态；实际关系与状态以回执后重新读取为准。' : '解除目标人员与设备的分配关系，不删除人员或设备登记。' }}</p>
      <div class="assignment-proposal-actions"><el-button :disabled="locked" @click="backToSelection">返回选择</el-button><el-button :type="proposal.action==='ASSIGN' ? 'primary' : 'danger'" :loading="phase!=='IDLE'" :disabled="locked || !canPrepare(proposal.action)" @click="confirm"><AppIcon name="DocumentChecked" :size="15" />{{ proposal.action==='ASSIGN' ? '确认分配' : '确认解除分配' }}</el-button></div>
    </section></Transition>
    <template #footer><el-button :disabled="locked" @click="close">关闭分配窗口</el-button></template>
  </el-dialog>
</template>

<script setup>
import { computed, getCurrentInstance, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import request from '../api/request'
import { useUserStore } from '../stores/user'
import CollectionEmptyState from './CollectionEmptyState.vue'
const emit=defineEmits(['changed'])
const props=defineProps({contextKey:{type:String,default:''}})
const userStore=useUserStore()
const visible=ref(false), employeeId=ref(''), person=ref(null), personError=ref('')
const deviceOptions=ref([]), assignedDevices=ref([]), optionsLoaded=ref(false), assignedLoaded=ref(false)
const optionsError=ref(''), assignedError=ref(''), loading=ref(false), phase=ref('IDLE'), needsRead=ref(true)
const selectedDeviceId=ref(null), proposal=ref(null), receipt=ref(null), uncertainDevices=ref(new Map())
const selectRef=ref(null), proposalRef=ref(null), selectId='employee-device-select-'+getCurrentInstance().uid
let generation=0, disposed=false
const actor=computed(()=>JSON.stringify([userStore.identity?.userId || userStore.username || '',userStore.role,userStore.isAuthenticated]))
const supervisor=computed(()=>userStore.role==='SUPERVISOR' && userStore.isAuthenticated)
const locked=computed(()=>loading.value || phase.value!=='IDLE')
const ready=computed(()=>supervisor.value && person.value && !personError.value && !needsRead.value)
const canPrepare=action=>!!ready.value && (action==='ASSIGN' ? optionsLoaded.value&&!optionsError.value : assignedLoaded.value&&!assignedError.value)
const id=value=>typeof value==='number'&&Number.isSafeInteger(value)&&value>0?String(value):typeof value==='string'&&/^[1-9]\d*$/.test(value)?value:''
const selectedDevice=computed(()=>deviceOptions.value.find(device=>id(device.id)===selectedDeviceId.value) || null)
const employeeTypeLabel=value=>({DETECTION:'门把手检测人员',COLLECTION:'门把手图片采集人员',MAINTENANCE:'设备维护人员'})[value] || value || '岗位未记录'
const deviceTypeLabel=value=>({DETECTION:'图像检测设备',IMAGE_CAPTURE:'图片采集设备'})[value] || value || '类型未记录'
const deviceLabel=device=>`${device?.deviceCode || '编号未记录'} · ${device?.modelName || '型号未记录'}`
const current=(version,personId,actorId)=>!disposed && visible.value && version===generation && employeeId.value===personId && actor.value===actorId
function unwrap(response){if(response.data?.code!==200)throw new Error(response.data?.message || '资料读取未成功');return response.data.data}
function deviceList(value){
  if(!Array.isArray(value))throw new Error('设备资料未完整读取，请重新核对')
  const ids=new Set()
  for(const device of value){const key=id(device?.id);if(!key||ids.has(key))throw new Error('设备编号未完整读取，请重新核对');ids.add(key)}
  return value
}
function assignmentReason(device){
  if(!device)return '请选择设备'
  if(uncertainDevices.value.has(id(device.id)))return '上次操作结果待核对，当前页面不重发'
  if(!person.value || person.value.status!=='ACTIVE')return '人员在岗状态不允许新增分配'
  if(device.deviceType==='DETECTION'&&!['DETECTION','MAINTENANCE'].includes(person.value.employeeType))return '检测设备需分配给检测或维护岗位'
  if(device.deviceType==='IMAGE_CAPTURE'&&!['COLLECTION','MAINTENANCE'].includes(person.value.employeeType))return '采集设备需分配给采集或维护岗位'
  return ''
}
async function loadContext(removeDeviceId=''){
  if(disposed || !visible.value || phase.value!=='IDLE' || !employeeId.value)return
  const version=++generation, personId=employeeId.value, actorId=actor.value
  loading.value=true;needsRead.value=true;proposal.value=null;selectedDeviceId.value=null
  person.value=null;personError.value='';assignedDevices.value=[];deviceOptions.value=[]
  assignedLoaded.value=false;optionsLoaded.value=false;assignedError.value='';optionsError.value=''
  const reads=await Promise.allSettled([request.get(`/api/employees/${personId}`),request.get(`/api/employees/${personId}/devices`),request.get('/api/devices/unassigned')])
  if(!current(version,personId,actorId))return
  try{const data=unwrap(awaited(reads[0]));if(id(data?.id)!==personId)throw new Error('目标人员编号未完整读取');person.value=data}catch(error){personError.value=error.response?.data?.message || error.message || '人员资料暂不可读取'}
  try{assignedDevices.value=deviceList(unwrap(awaited(reads[1])));assignedLoaded.value=true}catch(error){assignedError.value=error.response?.data?.message || error.message || '已分配关系暂不可读取'}
  try{deviceOptions.value=deviceList(unwrap(awaited(reads[2])));optionsLoaded.value=true}catch(error){optionsError.value=error.response?.data?.message || error.message || '未分配设备暂不可读取'}
  loading.value=false;needsRead.value=!!personError.value
  if(removeDeviceId && canPrepare('UNASSIGN')){const device=assignedDevices.value.find(item=>id(item.id)===removeDeviceId);if(device)prepare('UNASSIGN',device);else receipt.value={state:'REJECTED',deviceId:removeDeviceId,message:'本次关系中未找到目标设备，未发送解除请求，请核对当前记录。'}}
}
function awaited(result){if(result.status==='rejected')throw result.reason;return result.value}
function prepare(action,device){
  if(!canPrepare(action) || locked.value || proposal.value || !id(device?.id) || uncertainDevices.value.has(id(device.id)))return
  const list=action==='ASSIGN'?deviceOptions.value:assignedDevices.value
  if(!list.some(item=>id(item.id)===id(device.id)) || action==='ASSIGN'&&assignmentReason(device))return
  proposal.value=Object.freeze({action,employeeId:employeeId.value,employeeName:person.value.name || '姓名未记录',employeeNumber:person.value.employeeNumber || '未记录',employeeType:person.value.employeeType,employeeStatus:person.value.status,deviceId:id(device.id),deviceCode:device.deviceCode || '编号未记录',modelName:device.modelName || '型号未记录',deviceStatus:device.status,deviceType:device.deviceType,version:generation,actor:actor.value})
  nextTick(()=>{if(proposal.value)proposalRef.value?.focus()})
}
async function confirm(){
  const target=proposal.value
  if(!target || !canPrepare(target.action) || locked.value || !current(target.version,target.employeeId,target.actor) || uncertainDevices.value.has(target.deviceId))return
  phase.value='VERIFYING';receipt.value=null
  let sent=false
  try{
    const [employeeRead,ownerRead,deviceRead]=await Promise.all([request.get(`/api/employees/${target.employeeId}`),request.get(`/api/devices/${target.deviceId}/employee`),request.get(`/api/devices/${target.deviceId}`)])
    if(!current(target.version,target.employeeId,target.actor) || !supervisor.value)return
    const employee=unwrap(employeeRead), owner=unwrap(ownerRead), device=unwrap(deviceRead)
    if(id(employee?.id)!==target.employeeId)throw new Error('人员资料已变化，请重新读取后核对')
    if(target.action==='ASSIGN' && (employee.status!=='ACTIVE' || employee.employeeType!==target.employeeType || owner!==null))throw new Error('人员岗位、在岗状态或设备关系已变化，请重新读取后核对')
    if(target.action==='UNASSIGN' && id(owner?.id)!==target.employeeId)throw new Error('当前设备使用人已变化，请重新读取后核对')
    if(id(device?.id)!==target.deviceId || device.deviceType!==target.deviceType || device.status!==target.deviceStatus)throw new Error('设备类型或业务状态已变化，请重新读取后核对')
    phase.value='SENDING';sent=true
    const response=target.action==='ASSIGN'?await request.post(`/api/employees/${target.employeeId}/assign-device/${target.deviceId}`):await request.delete(`/api/devices/${target.deviceId}/employee`)
    if(!current(target.version,target.employeeId,target.actor))return
    const body=response.data
    proposal.value=null;selectedDeviceId.value=null;needsRead.value=true
    if(body?.code===200 && body.data===true){
      receipt.value={state:'SUCCEEDED',deviceId:target.deviceId,message:`已收到${target.action==='ASSIGN'?'分配':'解除分配'}成功回执，请核对重新读取的关系与状态。`}
      emit('changed',{employeeId:target.employeeId,deviceId:target.deviceId,action:target.action})
      phase.value='IDLE';await loadContext()
    }else{
      const unknown=body?.code==null || body.code>=500 || body.code===200&&body.data!==false
      recordReceipt(target,unknown?'UNKNOWN':'REJECTED',unknown?'操作结果待核对，请重新读取关系或设备详情；当前页面不会对该设备重复发送变更。':body?.message || '接口未确认操作成功，请重新读取关系。')
    }
  }catch(error){
    if(!current(target.version,target.employeeId,target.actor))return
    proposal.value=null;selectedDeviceId.value=null;needsRead.value=true
    const unknown=sent && (!error.response?.status || error.response.status>=500)
    recordReceipt(target,unknown?'UNKNOWN':'REJECTED',unknown?'操作结果待核对，请重新读取关系或设备详情；不会自动重发。':sent?error.response?.data?.message || '接口未确认操作成功，请重新读取后核对。':`${error.response?.data?.message || error.message || '当前关系未核对完成'}；尚未发送本次变更。`)
  }finally{if(current(target.version,target.employeeId,target.actor))phase.value='IDLE'}
}
function recordReceipt(target,state,message){receipt.value={state,deviceId:target.deviceId,message};if(state==='UNKNOWN')uncertainDevices.value=new Map([...uncertainDevices.value,[target.deviceId,target]])}
function backToSelection(){if(locked.value)return;proposal.value=null;nextTick(()=>selectRef.value?.focus())}
function close(){if(!locked.value)visible.value=false}
async function openFor(value,options={}){
  if(disposed || phase.value!=='IDLE' || !supervisor.value || !id(value))return false
  generation++;employeeId.value=id(value);visible.value=true;receipt.value=null
  const previous=[...uncertainDevices.value.values()].find(item=>item.employeeId===employeeId.value)
  if(previous)receipt.value={state:'UNKNOWN',deviceId:previous.deviceId,message:'该设备上次操作结果仍待核对，当前页面不会重发；请重新读取当前关系。'}
  await loadContext(id(options.removeDeviceId))
  return true
}
watch(visible,open=>{if(!open){generation++;loading.value=false;phase.value='IDLE';proposal.value=null;selectedDeviceId.value=null;person.value=null;assignedDevices.value=[];deviceOptions.value=[]}},{flush:'sync'})
watch(actor,()=>{generation++;visible.value=false;loading.value=false;phase.value='IDLE';receipt.value=null;uncertainDevices.value=new Map()},{flush:'sync'})
watch(()=>props.contextKey,()=>{
  if(phase.value==='SENDING' && proposal.value)uncertainDevices.value=new Map([...uncertainDevices.value,[proposal.value.deviceId,proposal.value]])
  generation++;visible.value=false;loading.value=false;phase.value='IDLE';receipt.value=null
},{flush:'sync'})
onBeforeUnmount(()=>{disposed=true;generation++})
defineExpose({openFor})
</script>

<style>
.employee-assignment-dialog .el-dialog__body { max-height:70dvh; overflow-y:auto; overscroll-behavior:contain; }
.employee-assignment-dialog .assignment-person { display:flex; align-items:flex-start; gap:12px; padding-bottom:18px; border-bottom:1px solid var(--app-border); }
.employee-assignment-dialog .assignment-person-icon { display:grid; place-items:center; width:42px; height:42px; flex:0 0 42px; border-radius:10px; background:var(--app-primary-soft); color:var(--app-primary); }
.employee-assignment-dialog .assignment-person > div { flex:1; min-width:0; }
.employee-assignment-dialog .assignment-person strong { color:var(--app-text); font-size:16px; font-weight:600; line-height:1.7; }
.employee-assignment-dialog .assignment-person p { margin:5px 0 0; color:var(--app-text-secondary); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.employee-assignment-dialog .assignment-read-heading { display:flex; justify-content:space-between; align-items:flex-start; gap:14px; flex-wrap:wrap; margin:16px 0; }
.employee-assignment-dialog .assignment-read-heading p,.employee-assignment-dialog .assignment-note { margin:0; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.employee-assignment-dialog :is(.assignment-select-section,.assignment-current-section) { padding:18px 0; border-bottom:1px solid var(--app-border); }
.employee-assignment-dialog h3 { display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin:0 0 16px; color:var(--app-text); font-size:14px; font-weight:600; }
.employee-assignment-dialog h3 > .el-icon { color:var(--app-primary); }
.employee-assignment-dialog h3 > span { margin-left:auto; color:var(--app-text-secondary); font-size:11px; font-weight:400; }
.employee-assignment-dialog .assignment-select-label { display:grid; gap:8px; margin:14px 0 10px; color:var(--app-text-secondary); font-size:12px; }
.employee-assignment-dialog .assignment-select-label .el-select { width:100%; }
.employee-assignment-dialog .assignment-note { margin-bottom:14px; }
.employee-assignment-dialog .assignment-selection { display:flex; align-items:center; gap:12px; justify-content:space-between; margin:14px 0; padding:12px 14px; background:var(--app-bg); border-radius:8px; }
.employee-assignment-dialog .assignment-selection > div { display:grid; gap:6px; min-width:0; font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.employee-assignment-dialog .assignment-selection strong { color:var(--app-text); font-weight:550; }
.employee-assignment-dialog .assignment-selection > div > span { color:var(--app-text-secondary); }
.employee-assignment-dialog :is(.assignment-progress,.assignment-limitation) { display:flex; align-items:flex-start; gap:7px; color:var(--app-warning); font-size:12px; line-height:1.85; }
.employee-assignment-dialog :is(.assignment-progress,.assignment-limitation) > .el-icon { flex-shrink:0; margin-top:3px; }
.employee-assignment-dialog .assignment-receipt { padding:12px 14px; background:var(--app-primary-soft); border-radius:8px; }
.employee-assignment-dialog .assignment-receipt[data-state=UNKNOWN] { background:var(--app-warning-soft); }
.employee-assignment-dialog .assignment-receipt[data-state=REJECTED] { background:var(--app-danger-soft); }
.employee-assignment-dialog .assignment-receipt p { margin:8px 0; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.employee-assignment-dialog .assignment-receipt a { display:inline-flex; align-items:center; gap:6px; color:var(--app-primary); font-size:12px; line-height:1.8; text-decoration:none; }
.employee-assignment-dialog .assignment-device-identity { display:grid; gap:5px; min-width:0; padding:6px 0; line-height:1.8; }
.employee-assignment-dialog .assignment-device-identity strong { color:var(--app-text); font-size:12px; font-weight:550; }
.employee-assignment-dialog .assignment-device-identity :is(span,small) { color:var(--app-text-secondary); font-size:11px; overflow-wrap:anywhere; }
.employee-assignment-dialog .assignment-proposal { padding:18px 0; outline-offset:4px; }
.employee-assignment-dialog .assignment-proposal dl { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; margin:0; }
.employee-assignment-dialog .assignment-proposal dt { color:var(--app-text-secondary); font-size:11px; line-height:1.8; }
.employee-assignment-dialog .assignment-proposal dd { display:grid; gap:5px; margin:6px 0 0; color:var(--app-text); font-size:13px; line-height:1.8; overflow-wrap:anywhere; }
.employee-assignment-dialog .assignment-proposal dd small { color:var(--app-text-secondary); font-size:11px; }
.employee-assignment-dialog .assignment-proposal > p { margin:16px 0; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.employee-assignment-dialog .assignment-proposal-actions { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:8px; }
.employee-assignment-dialog .assignment-proposal-actions .el-button + .el-button { margin-left:0; }
.employee-assignment-dialog :is(a,[tabindex]):focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; border-radius:3px; }
.employee-assignment-options .el-select-dropdown__item { height:auto; min-height:52px; padding-block:8px; line-height:1.7; }
.employee-assignment-options .assignment-option { display:grid; gap:5px; max-width:100%; white-space:normal; overflow-wrap:anywhere; }
.employee-assignment-options .assignment-option strong { font-size:12px; font-weight:550; }
.employee-assignment-options .assignment-option small { font-size:11px; }
.assignment-review-enter-active,.assignment-review-leave-active { transition:opacity 180ms ease,transform 180ms ease; }
.assignment-review-enter-from,.assignment-review-leave-to { opacity:0;transform:translateY(4px); }
@media(max-width:600px) { .employee-assignment-dialog .assignment-person { flex-wrap:wrap; } .employee-assignment-dialog .assignment-proposal dl { grid-template-columns:minmax(0,1fr); } }
@media(prefers-reduced-motion:reduce) { .assignment-review-enter-active,.assignment-review-leave-active { transition:none!important;transform:none!important; } .employee-assignment-dialog,.el-overlay:has(.employee-assignment-dialog) { animation:none!important; transition:none!important; } }
</style>
