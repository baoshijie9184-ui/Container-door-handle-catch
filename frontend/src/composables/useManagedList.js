import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import request from '../api/request'
import { knownCount } from '../utils/countPresentation'

// Read-only state for existing operational collection endpoints.
export function useManagedList(endpoint, filterKeys, options={}) {
  const filters = reactive(Object.fromEntries(filterKeys.map(key => [key,''])))
  const pagination = reactive({current:1,size:10})
  const records = ref([]), total = ref(null), loading = ref(false), error = ref(''), loaded = ref(false), filterError=ref('')
  const applied = ref(null), requested = ref(null)
  let generation=0, disposed=false, pendingKey=''
  onBeforeUnmount(()=>{disposed=true;generation++})
  const snapshot=()=>Object.fromEntries(filterKeys.flatMap(key=>{
    const value=typeof filters[key]==='string'?filters[key].trim():filters[key]
    return value==null||value===''?[]:[[key,value]]
  }))
  const hasFilters=computed(()=>Object.keys(snapshot()).length>0)
  const filtersDirty=computed(()=>!!applied.value&&JSON.stringify(snapshot())!==JSON.stringify(applied.value.filters))
  const appliedFilters=computed(()=>applied.value?.filters || {})
  const clear=()=>{records.value=[];total.value=null;loaded.value=false}

  async function read(query) {
    if(disposed || options.canRead && !options.canRead())return false
    filterError.value=options.validateFilters?.(query.filters) || ''
    if(filterError.value)return false
    const params={page:query.page,size:query.size,...query.filters}, key=JSON.stringify(params)
    if(loading.value&&pendingKey===key)return false
    const version=++generation
    pendingKey=key;requested.value=query
    if(key!==JSON.stringify(applied.value?{page:applied.value.page,size:applied.value.size,...applied.value.filters}:null))clear()
    loading.value=true;error.value=''
    try{
      const response=await request.get(endpoint,{params})
      if(disposed||version!==generation)return false
      const body=response.data
      if(body?.code!==200){const failure=new Error(body?.message || '列表读取未成功');failure.httpStatus=body?.code;throw failure}
      const data=body.data
      if(!Array.isArray(data?.records))throw new Error('列表记录未完整读取，请重新核对')
      const ids=new Set()
      for(const row of data.records){
        const id=row?.[options.idField || 'id']
        const valid=typeof id==='number'?Number.isSafeInteger(id)&&id>0:typeof id==='string'&&/^[1-9]\d*$/.test(id)
        if(!valid||ids.has(String(id)))throw new Error('列表资源编号未完整读取，请重新核对')
        ids.add(String(id))
      }
      const count=knownCount(data.total)
      if(query.page>1&&!data.records.length&&count!==null&&count<=(query.page-1)*query.size)return await read({...query,page:1})
      records.value=data.records;total.value=count;loaded.value=true;applied.value=query
      pagination.current=query.page;pagination.size=query.size
      return true
    }catch(failure){
      if(!disposed&&version===generation){
        if([401,403].includes(failure.response?.status || failure.httpStatus)){clear();applied.value=null}
        error.value=failure.response?.data?.message || failure.message || '列表暂不可读取，请重新核对'
      }
      return false
    }finally{if(!disposed&&version===generation)loading.value=false}
  }
  const search=()=>read({page:1,size:pagination.size,filters:snapshot()})
  const reset=()=>{for(const key of filterKeys)filters[key]='';return search()}
  const refresh=()=>read(loading.value&&requested.value ? requested.value : applied.value || requested.value || {page:pagination.current,size:pagination.size,filters:snapshot()})
  const retry=()=>read(requested.value || {page:pagination.current,size:pagination.size,filters:snapshot()})
  const changePage=page=>Number.isSafeInteger(Number(page))&&Number(page)>0?read({page:Number(page),size:pagination.size,filters:applied.value?.filters || snapshot()}):Promise.resolve(false)
  const changeSize=size=>Number.isSafeInteger(Number(size))&&Number(size)>0?read({page:1,size:Number(size),filters:applied.value?.filters || snapshot()}):Promise.resolve(false)
  if(options.scope)watch(options.scope,()=>{
    generation++;pendingKey='';loading.value=false;error.value='';filterError.value='';clear();applied.value=null;requested.value=null;pagination.current=1
    for(const key of filterKeys)filters[key]=''
    if(!disposed && (!options.canRead || options.canRead()))search()
  },{flush:'sync'})
  return {records,total,loading,error,loaded,filterError,filters,pagination,hasFilters,filtersDirty,appliedFilters,search,reset,refresh,retry,changePage,changeSize}
}
