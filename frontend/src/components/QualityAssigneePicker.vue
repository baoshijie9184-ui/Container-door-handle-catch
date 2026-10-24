<template>
  <div class="assignee-picker">
    <el-select :model-value="userId ?? undefined" :disabled="disabled" filterable remote clearable :remote-method="queueSearch" :loading="loading"
      :placeholder="modelValue ? '原责任人 ' + modelValue + '，请重新选择账号' : '搜索并选择员工账号'"
      aria-label="质检责任人账号" @change="choose" @visible-change="opened">
      <el-option v-for="option in options" :key="option.userId" :value="option.userId" :label="option.username + ' · ID ' + option.userId" />
    </el-select>
    <span v-if="userId && revision" class="assignee-proof"><el-icon><User /></el-icon>账号 ID {{ userId }} · 已固定快照</span>
    <span v-if="error" role="alert" class="assignee-error">{{ error }}</span>
  </div>
</template>
<script setup>
import { ref,watch,onBeforeUnmount } from 'vue'
import { User } from '@element-plus/icons-vue'
import request from '@/api/request'
const props=defineProps({modelValue:String,userId:Number,revision:String,disabled:Boolean})
const emit=defineEmits(['update:modelValue','update:userId','update:revision'])
const options=ref([]),loading=ref(false),error=ref('')
let generation=0
let searchDelay
function queueSearch(keyword){if(props.disabled)return;generation++;options.value=[];loading.value=true;clearTimeout(searchDelay);searchDelay=setTimeout(()=>search(keyword),180)}
async function search(keyword=''){
  if(props.disabled)return
  const id=++generation;loading.value=true;error.value=''
  try{
    const response=await request.get('/api/detection/quality-assignees',{params:{keyword:String(keyword).slice(0,50)},headers:{'Cache-Control':'no-cache'}})
    if(id!==generation)return
    if(response.data?.code!==200 || !Array.isArray(response.data.data))throw Error()
    options.value=response.data.data.filter(row=>typeof row.username==='string'&&Number.isSafeInteger(row.userId)&&row.userId>0&&/^[a-f0-9]{64}$/.test(row.revision))
    if(response.data.data.length && !options.value.length)error.value='当前服务未返回可核对的账号 ID 与快照，请核对前后端版本'
  }catch{if(id===generation){options.value=[];error.value='无法核对员工账号，请重新查询'}}
  finally{if(id===generation)loading.value=false}
}
function opened(visible){if(visible&&!props.disabled){clearTimeout(searchDelay);search('')}}
function choose(id){
  if(props.disabled)return
  const account=options.value.find(row=>row.userId===id)
  emit('update:modelValue',account?.username||'');emit('update:userId',account?.userId??null);emit('update:revision',account?.revision??null)
}
watch(()=>props.disabled,disabled=>{if(disabled){generation++;clearTimeout(searchDelay);loading.value=false}})
onBeforeUnmount(()=>{generation++;clearTimeout(searchDelay)})
</script>
<style scoped>
.assignee-picker{width:100%;min-width:0}.assignee-picker .el-select{width:100%}.assignee-proof{display:flex;align-items:center;gap:6px;color:#215cc0;font-size:12px;margin-top:6px;overflow-wrap:anywhere}.assignee-error{display:block;color:#b91c1c;font-size:12px;margin-top:6px}
</style>
