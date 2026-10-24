import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import request from '../api/request'
import { useUserStore } from '../stores/user'

const resourceId=value=>typeof value==='number' && Number.isSafeInteger(value) && value>0 ? String(value) : typeof value==='string' && /^[1-9]\d*$/.test(value) ? value : ''
const versionKnown=value=>typeof value==='number' && Number.isSafeInteger(value) && value>=0

// UI state for the existing versioned employee/device forms, not a command-receipt store.
export function useManagedForm({endpoint,defaults,formRef,listRoute,label}) {
  const route=useRoute(),router=useRouter(),userStore=useUserStore()
  const form=reactive(defaults()),keys=Object.keys(form)
  const blankEdit=()=>{const initial=defaults();return Object.fromEntries(keys.map(key=>[key,typeof initial[key]==='string'?'':null]))}
  const id=computed(()=>resourceId(route.params.id))
  const isEdit=computed(()=>route.params.id!=null && route.params.id!=='')
  const actor=computed(()=>JSON.stringify([userStore.identity?.userId || userStore.username || '',userStore.role,userStore.isAuthenticated]))
  const context=computed(()=>JSON.stringify([route.name,route.params.id,actor.value]))
  const supervisor=computed(()=>userStore.isAuthenticated && userStore.role==='SUPERVISOR')
  const permissionError=computed(()=>userStore.hasCheckedAuth && !supervisor.value ? '仅已登录的主管可以维护这份资料，业务岗位不代表账号权限。' : '')
  const phase=ref('IDLE'),loaded=ref(false),loadError=ref(''),saveError=ref(''),validationError=ref(''),lookupNotice=ref('')
  const receipt=ref(null),conflict=ref(false),uncertain=ref(false),saved=ref(false),baseline=ref(null)
  let generation=0,disposed=false
  const uniqueVersions=new Map()
  const current=(stamp,version)=>!disposed && context.value===stamp && generation===version
  const snapshot=()=>Object.fromEntries(keys.map(key=>[key,form[key] ?? null]))
  const dirty=computed(()=>baseline.value!==null && JSON.stringify(snapshot())!==baseline.value)
  const loading=computed(()=>phase.value!=='IDLE')
  const disabled=computed(()=>!supervisor.value || !loaded.value || loading.value || !!loadError.value || conflict.value || uncertain.value || saved.value)
  const canSubmit=computed(()=>!disabled.value)
  const goBack=()=>router.push({name:listRoute})
  function dataOf(response) {
    if(response.data?.code!==200){const error=new Error(response.data?.message || '接口未确认操作成功');error.httpStatus=response.data?.code;throw error}
    return response.data.data
  }
  async function read() {
    if(disposed || !supervisor.value || loading.value || !isEdit.value || !id.value)return false
    const stamp=context.value,version=++generation,target=id.value
    phase.value='READING';loadError.value=''
    try {
      const response=await request.get(`${endpoint}/${target}`)
      if(!current(stamp,version))return false
      const data=dataOf(response)
      if(resourceId(data?.id)!==target || !versionKnown(data.version))throw new Error('资料编号或版本未完整读取，请重新核对')
      const empty=blankEdit()
      // New-record defaults must not invent legacy dates, gender or status on an edit.
      for(const key of keys)form[key]=data[key] ?? empty[key]
      baseline.value=JSON.stringify(snapshot());loaded.value=true;conflict.value=false
      if(!uncertain.value){saveError.value='';receipt.value=null}
      lookupNotice.value='';validationError.value=''
      await nextTick()
      if(current(stamp,version))formRef.value?.clearValidate()
      return true
    } catch(error) {
      if(!current(stamp,version))return false
      if([401,403].includes(error.response?.status || error.httpStatus)){Object.assign(form,blankEdit());baseline.value=null;loaded.value=false}
      loadError.value=error.response?.data?.message || error.message || '资料暂不可读取；已有输入保留，请重新读取或返回列表核对。'
      return false
    } finally {if(current(stamp,version))phase.value='IDLE'}
  }
  async function confirmDiscard(message) {
    if(!dirty.value)return true
    try{await ElMessageBox.confirm(message,'核对未保存的修改',{confirmButtonText:'放弃修改并继续',cancelButtonText:'继续编辑',type:'warning'});return true}catch{return false}
  }
  async function reload() {
    if(loading.value || disposed)return
    const stamp=context.value,version=generation
    if(!await confirmDiscard('重新读取成功后，会用服务器资料替换当前未保存的修改。'))return
    if(current(stamp,version))return read()
  }
  async function reset() {
    if(loading.value || disposed || baseline.value===null || uncertain.value || saved.value)return
    const stamp=context.value,version=generation
    if(!await confirmDiscard(isEdit.value?'恢复上次读取的资料会放弃当前修改，不会重新查询服务器。':'恢复初始填写值会放弃当前未保存的修改。'))return
    if(!current(stamp,version))return
    Object.assign(form,JSON.parse(baseline.value));validationError.value='';lookupNotice.value=''
    await nextTick()
    if(current(stamp,version))formRef.value?.clearValidate()
  }
  async function submit() {
    if(!canSubmit.value || !formRef.value)return
    const stamp=context.value,version=generation,target=id.value,editing=isEdit.value
    phase.value='VALIDATING';validationError.value='';saveError.value='';receipt.value=null
    let sent=false,acknowledged=false
    try {
      const valid=await formRef.value.validate().catch(()=>false)
      if(!current(stamp,version))return
      if(!valid){validationError.value='请核对已标记的字段，尚未发送保存。';return}
      if(!supervisor.value || editing && (!target || !versionKnown(form.version)))throw new Error('账号、资料编号或版本未核对完成，请重新读取')
      const payload=Object.freeze(snapshot())
      phase.value='SAVING';sent=true
      const response=editing?await request.put(`${endpoint}/${target}`,payload):await request.post(endpoint,payload)
      if(!current(stamp,version))return
      const data=dataOf(response),returnedId=resourceId(data?.id)
      if(!returnedId || editing && returnedId!==target){const error=new Error('未收到可核对的资料编号');error.unknown=true;throw error}
      receipt.value={state:'SUCCEEDED',resourceId:returnedId,message:`已收到${label}${editing?'更新':'新增'}成功回执。`}
      baseline.value=JSON.stringify(snapshot());saved.value=true;acknowledged=true
    } catch(error) {
      if(!current(stamp,version))return
      const status=error.response?.status || error.httpStatus
      const unknown=sent && (error.unknown || !status || status>=500)
      if(unknown)uncertain.value=true
      if(status===409)conflict.value=true
      saveError.value=unknown?'保存结果待核对，当前页面不再次提交。请到列表或详情重新读取；离开页面不会取消服务器已接收的请求。':`${error.response?.data?.message || error.message || '保存未成功'}${sent ? status===409?'；原草稿保留，请核对业务条件并重新读取版本。':'；接口未确认保存成功。':'；尚未发送保存。'}`
      receipt.value={state:unknown?'UNKNOWN':'REJECTED',message:saveError.value}
    } finally {if(current(stamp,version))phase.value='IDLE'}
    if(acknowledged && current(stamp,version)){
      const navigationFailed=()=>{if(current(stamp,version))saveError.value='资料已保存，返回列表未完成，可使用返回列表按钮。'}
      router.push({name:listRoute}).then(failure=>{if(failure)navigationFailed()}).catch(navigationFailed)
    }
  }
  function uniqueValidator(field,url,param,labelText,minLength=1) {
    return (_rule,value,callback)=>{
      const version=(uniqueVersions.get(field) || 0)+1,stamp=context.value,scope=generation,target=id.value
      uniqueVersions.set(field,version);lookupNotice.value=''
      if(typeof value!=='string' || value.length<minLength || !supervisor.value)return callback()
      // Use the callback contract only; do not also return a validation Promise.
      request.get(url,{params:{[param]:value,excludeId:target || undefined}}).then(response=>{
        if(!current(stamp,scope) || uniqueVersions.get(field)!==version || form[field]!==value)return callback()
        const exists=dataOf(response)
        if(typeof exists!=='boolean')throw new Error('编号校验回执不完整')
        callback(exists?new Error(`${labelText}已存在`):undefined)
      }).catch(()=>{
        if(current(stamp,scope) && uniqueVersions.get(field)===version && form[field]===value)lookupNotice.value='编号可用性暂未核对，未将其判断为可用；最终保存仍由服务端校验。'
        callback()
      })
    }
  }
  async function guardLeave() {
    if(disposed || !supervisor.value || !dirty.value && !uncertain.value && phase.value!=='SAVING')return true
    const stamp=context.value
    try{
      await ElMessageBox.confirm(uncertain.value || phase.value==='SAVING'?'保存请求已发送或结果待核对，离开不会取消服务器操作；请之后到列表核对。':'当前修改尚未保存，确定放弃并离开吗？','核对当前操作',{confirmButtonText:'离开页面',cancelButtonText:'留在此页',type:'warning'})
      return true
    }catch{return disposed || context.value!==stamp}
  }
  onBeforeRouteLeave(guardLeave)
  onBeforeRouteUpdate((to,from)=>to.name===from.name && to.params.id===from.params.id ? true : guardLeave())
  watch(context,()=>{
    generation++;uniqueVersions.clear();phase.value='IDLE';loaded.value=false;baseline.value=null
    Object.assign(form,isEdit.value?blankEdit():defaults());loadError.value='';saveError.value='';validationError.value='';lookupNotice.value='';receipt.value=null;conflict.value=false;uncertain.value=false;saved.value=false
    if(isEdit.value && !id.value){loadError.value='资料编号无效，请返回列表重新选择';return}
    if(!supervisor.value)return
    if(isEdit.value)read()
    else {loaded.value=true;baseline.value=JSON.stringify(snapshot())}
  },{immediate:true,flush:'sync'})
  onBeforeUnmount(()=>{disposed=true;generation++;uniqueVersions.clear()})
  return {form,id,isEdit,actor,supervisor,phase,loading,loaded,permissionError,loadError,saveError,validationError,lookupNotice,receipt,conflict,uncertain,saved,dirty,disabled,canSubmit,read,reload,reset,submit,goBack,uniqueValidator}
}
