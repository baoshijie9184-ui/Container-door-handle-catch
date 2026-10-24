import { computed, ref, onBeforeUnmount } from 'vue'
import { knownCount } from '../utils/countPresentation'

const terminalStatus = task => ['COMPLETED','PARTIAL_FAILED','FAILED'].includes(String(task.status || '').toUpperCase())
const normalizeHistoryRecord = (record, taskStore) => ({
  ...record,
  stage:taskStore.normalizeStage(record.status,record.stage),
  imageCount:knownCount(record.totalImages),
  result:null,
  resultReadError:'',
  resultLoading:terminalStatus(record),
  captureInfo:{captureDate:record.captureDate,region:record.region,collector:record.collector,deviceName:record.deviceName,imageFolderName:record.imageFolderName}
})

export function useDetectionHistory(taskStore, pollingStore) {
  const historySearchKeyword=ref(''), historyFilterCollector=ref(''), historyFilterDevice=ref(''), historyFilterRegion=ref('')
  const historyPage=ref(1), historyPageSize=ref(10), historyTotal=ref(null), historyRecords=ref([])
  const historyLoading=ref(false), historyError=ref(''), historyLoaded=ref(false)
  const appliedQuery=ref(null), requestedQuery=ref(null)
  let loadGeneration=0, disposed=false, pendingKey=''
  onBeforeUnmount(()=>{disposed=true;loadGeneration++})

  const buildHistoryFilters=()=>{
    const filters={}
    if(historySearchKeyword.value.trim())filters.keyword=historySearchKeyword.value.trim()
    if(historyFilterCollector.value.trim())filters.collector=historyFilterCollector.value.trim()
    if(historyFilterDevice.value.trim())filters.deviceName=historyFilterDevice.value.trim()
    if(historyFilterRegion.value.trim())filters.region=historyFilterRegion.value.trim()
    return filters
  }
  const hasHistoryFilters=computed(()=>Object.keys(buildHistoryFilters()).length>0)
  const historyFiltersDirty=computed(()=>!!appliedQuery.value&&JSON.stringify(buildHistoryFilters())!==JSON.stringify(appliedQuery.value.filters))
  const historyAppliedFilters=computed(()=>appliedQuery.value?.filters || {})
  const clearRecords=()=>{historyRecords.value=[];historyTotal.value=null;historyLoaded.value=false}

  const fetchHistoryWithFilters=async(page,size,filterOverride)=>{
    if(disposed)return
    const requestedPage=Number.isSafeInteger(Number(page))&&Number(page)>0?Number(page):historyPage.value
    const requestedSize=Number.isSafeInteger(Number(size))&&Number(size)>0?Number(size):historyPageSize.value
    const filters={...(filterOverride || buildHistoryFilters())}
    const query={page:requestedPage,size:requestedSize,filters}, key=JSON.stringify(query)
    if(historyLoading.value&&pendingKey===key)return
    const generation=++loadGeneration
    pendingKey=key;requestedQuery.value=query
    if(key!==JSON.stringify(appliedQuery.value))clearRecords()
    historyLoading.value=true;historyError.value=''
    try{
      const response=await pollingStore.fetchTaskList(requestedPage,requestedSize,filters.keyword || '','',filters)
      if(disposed||generation!==loadGeneration)return
      if(!response||response.ok!==true||!Array.isArray(response.records)){
        if([401,403].includes(response?.httpStatus)){clearRecords();appliedQuery.value=null}
        throw new Error(response?.message || '检测记录未完整读取，请重新核对')
      }
      historyRecords.value=response.records.map(record=>normalizeHistoryRecord(record,taskStore))
      historyTotal.value=knownCount(response.total)
      historyPage.value=requestedPage;historyPageSize.value=requestedSize
      appliedQuery.value=query;historyLoaded.value=true
      const completedIds=historyRecords.value.filter(terminalStatus).map(task=>task.taskId)
      if(!completedIds.length)return
      const receipts=await pollingStore.fetchTaskResults(completedIds)
      if(disposed||generation!==loadGeneration)return
      if(!Array.isArray(receipts))throw new Error('结果详情的读取回执未完整返回，请重新核对')
      if(receipts.some(receipt=>[401,403].includes(receipt?.httpStatus))){
        clearRecords();appliedQuery.value=null
        throw new Error('部分任务结果访问被拒绝，请重新核对账号与任务范围')
      }
      const results=new Map(receipts.filter(receipt=>receipt&&typeof receipt.taskId==='string').map(receipt=>[receipt.taskId,receipt]))
      historyRecords.value=historyRecords.value.map(task=>{
        if(!terminalStatus(task))return task
        const receipt=results.get(task.taskId)
        if(!receipt?.ok||receipt.result?.taskId!==task.taskId)return {...task,result:null,resultLoading:false,resultReadError:receipt?.message || '结果详情尚未完整读取'}
        const result=receipt.result
        return {...task,...result,stage:taskStore.normalizeStage(result.status,result.stage),imageCount:knownCount(result.totalImages),result,resultLoading:false,resultReadError:'',finishedAt:Object.prototype.hasOwnProperty.call(result,'detectionFinishedAt')?result.detectionFinishedAt:task.finishedAt,captureInfo:Object.prototype.hasOwnProperty.call(result,'captureInfo')?result.captureInfo:task.captureInfo}
      })
    }catch(error){
      if(!disposed&&generation===loadGeneration){
        historyError.value=error.message || '检测记录暂不可读取，请重新查询核对'
        historyRecords.value=historyRecords.value.map(task=>({...task,resultLoading:false}))
      }
    }finally{if(!disposed&&generation===loadGeneration)historyLoading.value=false}
  }
  const onHistorySearch=()=>fetchHistoryWithFilters(1,historyPageSize.value)
  const onHistoryReset=()=>{historySearchKeyword.value='';historyFilterCollector.value='';historyFilterDevice.value='';historyFilterRegion.value='';return onHistorySearch()}
  const onHistoryPageChange=page=>fetchHistoryWithFilters(page,historyPageSize.value,appliedQuery.value?.filters)
  const onHistorySizeChange=size=>fetchHistoryWithFilters(1,size,appliedQuery.value?.filters)
  const refreshHistory=()=>{
    const query=appliedQuery.value || requestedQuery.value
    return query?fetchHistoryWithFilters(query.page,query.size,query.filters):fetchHistoryWithFilters()
  }
  const retryHistoryRead=()=>{
    const query=requestedQuery.value
    return query?fetchHistoryWithFilters(query.page,query.size,query.filters):fetchHistoryWithFilters()
  }
  return {historySearchKeyword,historyFilterCollector,historyFilterDevice,historyFilterRegion,historyPage,historyPageSize,historyTotal,historyRecords,historyLoading,historyError,historyLoaded,hasHistoryFilters,historyFiltersDirty,historyAppliedFilters,buildHistoryFilters,fetchHistoryWithFilters,onHistorySearch,onHistoryReset,onHistoryPageChange,onHistorySizeChange,refreshHistory,retryHistoryRead}
}
