<template>
  <el-button v-if="isSupervisor" :icon="FolderChecked" @click="open">文件记录</el-button>
  <el-drawer v-model="visible" title="模型文件记录" size="min(960px, 100vw)">
    <div class="model-files">
      <p class="model-files-note">按请求编号核对上传结果。删除模型登记会保留文件，这里不执行物理删除。</p>
      <el-form class="model-files-query" label-position="top" @submit.prevent="load">
        <el-form-item label="请求编号">
          <el-input v-model="requestId" clearable maxlength="128" placeholder="留空查看最近 50 条" aria-label="文件操作请求编号" />
        </el-form-item>
        <el-button native-type="submit" type="primary" :loading="loading" :icon="Search">查询</el-button>
      </el-form>
      <p v-if="appliedRequest!==null" class="model-files-note">本次已查询：{{ appliedRequest || '最近记录' }}，每类最多返回 50 条，不代表全部历史。</p>
      <p v-if="queryDirty" class="model-files-note" role="status">请求编号已修改，尚未执行新的查询。</p>
      <p v-if="error" role="alert" class="model-files-error">{{ error }}</p>
      <p v-if="loading&&!result" role="status" class="model-files-note">正在读取文件记录…</p>
      <el-alert v-if="result && !result.enabled" title="文件意图登记尚未启用，历史文件不会自动补造记录" type="info" :closable="false" show-icon />
      <template v-if="result?.enabled">
        <el-tabs>
          <el-tab-pane :label="`上传记录（${result.uploads.length}）`">
            <TableReadHint v-if="result.uploads.length" />
            <el-table :scrollbar-tabindex="0" role="region" aria-label="已查询的模型上传文件记录" :data="result.uploads" row-key="fileId" v-loading="loading" empty-text="没有符合条件的上传记录">
              <el-table-column label="状态" min-width="155"><template #default="{row}"><StatusBadge domain="modelFile" :code="row.state" /></template></el-table-column>
              <el-table-column prop="requestId" label="请求编号" min-width="230" />
              <el-table-column prop="fileId" label="文件编号" min-width="230" />
              <el-table-column label="模型编号" min-width="100"><template #default="{row}">{{ row.modelId ?? '未确认' }}</template></el-table-column>
              <el-table-column label="记录长度" min-width="120"><template #default="{row}">{{ knownCount(row.bytes)==null ? '未知' : knownCount(row.bytes).toLocaleString('zh-CN') + ' B' }}</template></el-table-column>
              <el-table-column prop="sha256" label="SHA-256" min-width="270" />
              <el-table-column label="更新时间 · UTC+8" min-width="185"><template #default="{row}">{{ formatFileTime(row.updatedAt) }}</template></el-table-column>
            </el-table>
            <p class="model-files-note">预留状态可能包含未完成、部分写入或回执丢失，不能解释为没有文件。文件就绪不等于模型已登记。</p>
          </el-tab-pane>
          <el-tab-pane :label="`保留文件（${result.retained.length}）`">
            <TableReadHint v-if="result.retained.length" />
            <el-table :scrollbar-tabindex="0" role="region" aria-label="已查询的模型保留文件记录" :data="result.retained" row-key="retentionId" v-loading="loading" empty-text="没有符合条件的保留记录">
              <el-table-column label="状态" min-width="155"><template #default="{row}"><StatusBadge domain="modelFile" :code="row.state" /></template></el-table-column>
              <el-table-column prop="modelId" label="原模型编号" min-width="100" />
              <el-table-column prop="requestId" label="请求编号" min-width="230" />
              <el-table-column prop="retentionId" label="保留记录编号" min-width="230" />
              <el-table-column label="记录长度" min-width="120"><template #default="{row}">{{ knownCount(row.bytes)==null ? '未知' : knownCount(row.bytes).toLocaleString('zh-CN') + ' B' }}</template></el-table-column>
              <el-table-column label="更新时间 · UTC+8" min-width="185"><template #default="{row}">{{ formatFileTime(row.updatedAt) }}</template></el-table-column>
            </el-table>
            <p class="model-files-note">旧文件缺少已登记摘要时显示“旧文件待核对”。保留记录不是文件仍然存在或已成功回收的证明。</p>
          </el-tab-pane>
        </el-tabs>
      </template>
    </div>
  </el-drawer>
</template>

<script setup>
import { ref,computed,onBeforeUnmount,watch } from 'vue'
import { FolderChecked,Search } from '@element-plus/icons-vue'
import request from '@/api/request'
import { beijingDateTime } from '@/utils/beijingTime'
import { knownCount } from '@/utils/countPresentation'
import { useUserStore } from '@/stores/user'
import TableReadHint from '@/components/TableReadHint.vue'
const userStore=useUserStore()
const actor=computed(()=>JSON.stringify([userStore.identity?.userId || userStore.username || '',userStore.role,userStore.isAuthenticated]))
const isSupervisor=computed(()=>userStore.isAuthenticated && userStore.role==='SUPERVISOR')
const visible=ref(false),loading=ref(false),requestId=ref(''),error=ref(''),result=ref(null),appliedRequest=ref(null)
const queryDirty=computed(()=>appliedRequest.value!==null && appliedRequest.value!==requestId.value.trim())
let generation=0,disposed=false,pendingQuery=null
const formatFileTime=value=>value?beijingDateTime(value)||'时间未记录':'时间未记录'
function invalidate(){generation++;loading.value=false;result.value=null;error.value='';appliedRequest.value=null;pendingQuery=null}
function rowsValid(rows,key){
  if(!Array.isArray(rows))return false
  const ids=new Set()
  return rows.every(row=>{const id=row?.[key];if(typeof id!=='string' || !id.trim() || ids.has(id))return false;ids.add(id);return true})
}
async function load(){
  if(disposed || !visible.value || !isSupervisor.value)return
  const value=requestId.value.trim()
  if(loading.value && pendingQuery===value)return
  if(value && !/^[A-Za-z0-9_-]{1,128}$/.test(value)){error.value='请输入有效的请求编号，尚未执行新查询';return}
  const version=++generation,stamp=actor.value
  const current=()=>!disposed && visible.value && actor.value===stamp && version===generation
  error.value='';result.value=null;appliedRequest.value=null;pendingQuery=value;loading.value=true
  try{
    const response=await request.get('/api/models/file-operations',{params:{...(value?{requestId:value}:{}),size:50},headers:{'Cache-Control':'no-cache'}})
    if(!current())return
    const data=response.data?.data
    if(response.data?.code!==200 || typeof data?.enabled!=='boolean' || !rowsValid(data.uploads,'fileId') || !rowsValid(data.retained,'retentionId'))throw new Error('模型文件记录响应未完整读取')
    result.value=data;appliedRequest.value=value
  }catch(failure){if(current())error.value=failure.response?.status===403?'当前账号没有查看模型文件记录的权限':failure.response?.data?.message || failure.message || '文件记录查询失败，请稍后手动查询；不会重试上传或删除'}
  finally{if(current())loading.value=false}
}
function open(){if(disposed || !isSupervisor.value)return;visible.value=true;load()}
function openForRequest(value){if(disposed || !isSupervisor.value)return;requestId.value=typeof value==='string'?value:'';open()}
watch(visible,open=>{if(!open)invalidate()},{flush:'sync'})
watch(actor,()=>{invalidate();visible.value=false;requestId.value=''},{flush:'sync'})
onBeforeUnmount(()=>{disposed=true;invalidate()})
defineExpose({openForRequest})
</script>

<style scoped>
.model-files{min-width:0}.model-files-query{display:flex;align-items:flex-end;gap:12px;flex-wrap:wrap;margin:18px 0}.model-files-query :deep(.el-form-item){flex:1 1 280px;min-width:0;margin-bottom:0}.model-files-query :deep(.el-form-item__label){font-size:12px;line-height:1.85;color:var(--app-text-secondary);height:auto}.model-files-query>.el-button{margin:0;flex:none}.model-files-note{color:var(--app-text-secondary);font-size:12px;line-height:1.85;overflow-wrap:anywhere}.model-files-error{color:var(--app-danger);font-size:13px;line-height:1.85;overflow-wrap:anywhere}.model-files :deep(.el-table .cell){overflow-wrap:anywhere}.model-files :deep(.el-button){transition:transform .15s ease}.model-files :deep(.el-button:active){transform:scale(.98)}@media(prefers-reduced-motion:reduce){.model-files :deep(.el-button){transition:none;transform:none}}
</style>
