<template>
  <section class="memory-page app-panel">
    <header><div><h2>个人记忆</h2><p>管理助手保存的本人长期记忆 不包含其他账号的私人信息</p></div><el-button :loading="loading" :disabled="busy||editor.visible" @click="refresh">刷新</el-button></header>
    <p v-if="error" role="alert" class="memory-error">{{ error }}</p>
    <section class="memory-settings" aria-label="长期记忆设置">
      <h3>记忆设置</h3>
      <template v-if="settings">
        <label><span>允许助手读取长期记忆<small>关闭后不再将已保存的长期记忆加入回答参考</small></span><el-switch v-model="form.readEnabled" aria-label="允许读取长期记忆" :disabled="busy" /></label>
        <label><span>自动保存新的长期记忆<small>关闭后跳过新记忆提取 现有聊天记录和记忆继续保留</small></span><el-switch v-model="form.saveEnabled" aria-label="自动保存长期记忆" :disabled="busy" /></label>
        <el-button type="primary" :loading="busy" :disabled="loading||!changed" @click="saveSettings">保存设置</el-button><p>两个聊天入口使用同一设置 已经开始的保存不因关闭开关而撤销</p>
      </template>
      <p v-else>设置暂不可用 请刷新后重试</p>
    </section>
    <section class="memory-list" aria-label="本人已保存记忆" v-loading="loading">
      <h3>已保存记忆</h3><p>编辑或删除前请核对正文 原聊天记录继续保留 如需停止后续提取 请关闭自动保存</p>
      <el-empty v-if="!items.length&&!loading" :description="listError?'记忆服务暂不可用':'暂无已保存记忆'" />
      <p v-if="listError" class="memory-error" role="alert">{{ listError }}</p>
      <TransitionGroup name="memory" tag="div">
        <article v-for="item in items" :key="item.id" class="memory-item">
          <p class="memory-content">{{ item.memory }}</p><footer><span>更新 {{ item.updatedAt||item.createdAt||'时间未记录' }}</span><div class="memory-actions"><el-button :disabled="busy||loading||editor.visible" @click="edit(item)">编辑记忆</el-button><el-button type="danger" plain :disabled="busy||loading||editor.visible" @click="remove(item)">删除记忆</el-button></div></footer>
        </article>
      </TransitionGroup>
      <div class="memory-pagination"><span>已显示 {{ items.length }} 条{{ hasMore?' · 还有更多记忆':'' }}</span><el-button v-if="hasMore" :loading="loading" :disabled="loading||busy||editor.visible" @click="loadMore">读取更多</el-button></div>
      <p v-if="items.length">列表变化后可刷新重新核对 编辑或删除完成后回到首批记录</p>
    </section>
    <details class="memory-audit"><summary>本人最近操作记录</summary><p v-if="!audit.length">暂无操作记录</p><p v-for="record in audit" :key="record.id">{{ record.createdAt }} · {{ action(record.action) }} · {{ outcome(record.outcome) }}</p><p>操作记录只保留状态和版本 不保存记忆正文</p></details>
    <el-dialog v-model="editor.visible" title="编辑长期记忆" class="memory-edit-dialog" width="min(640px, calc(100vw - 32px))" append-to-body :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" :before-close="closeEditor">
      <p>修改影响后续长期记忆检索 原聊天记录继续保留</p>
      <h4>当前原文</h4><p class="memory-original">{{ editor.item?.memory }}</p>
      <h4>{{ editor.preview?'待保存正文':'修改正文' }}</h4>
      <p v-if="editor.preview" class="memory-preview">{{ editor.memory.trim() }}</p>
      <el-input v-else v-model="editor.memory" type="textarea" :rows="6" maxlength="4000" show-word-limit aria-label="修改记忆正文" :disabled="busy" />
      <p v-if="editor.error" role="alert" class="memory-error">{{ editor.error }}</p>
      <p v-if="editor.needsReload">草稿已保留 请先重新读取原文 核对结果后再预览确认</p>
      <template #footer>
        <div class="memory-editor-buttons">
          <el-button :disabled="busy" @click="editor.visible=false">取消</el-button>
          <el-button v-if="editor.needsReload" :loading="busy" @click="reloadEditor">重新读取当前版本</el-button>
          <template v-else>
            <el-button v-if="editor.preview" :disabled="busy" @click="editor.preview=false">返回修改</el-button>
            <el-button v-if="!editor.preview" type="primary" :disabled="!canSave||busy" @click="editor.preview=true">预览修改</el-button>
            <el-button v-else type="primary" :loading="busy" :disabled="!canSave" @click="saveMemory">确认保存</el-button>
          </template>
        </div>
      </template>
    </el-dialog>
  </section>
</template>
<script setup>
import {computed,onBeforeUnmount,onMounted,reactive,ref,watch} from 'vue'
import {ElMessage,ElMessageBox} from 'element-plus'
import {useUserStore} from '@/stores/user'
import {memoryPreferences,memoryList,memoryAudit,personalMemory,changeMemoryPreferences,deletePersonalMemory,updatePersonalMemory} from '@/api/agentMemory'
const user=useUserStore(),loading=ref(false),busy=ref(false),error=ref(''),listError=ref(''),settings=ref(null),items=ref([]),audit=ref([]),hasMore=ref(false),nextOffset=ref(null)
const limit=50,editor=reactive({visible:false,item:null,memory:'',preview:false,error:'',needsReload:false})
const form=reactive({readEnabled:true,saveEnabled:true});let generation=0,identity=0
const changed=computed(()=>settings.value&&(form.readEnabled!==settings.value.readEnabled||form.saveEnabled!==settings.value.saveEnabled))
const canSave=computed(()=>editor.item&&editor.memory.trim().length>0&&editor.memory.length<=4000&&editor.memory.trim()!==editor.item.memory&&!editor.needsReload)
const outcome=value=>({SUCCEEDED:'已完成',PENDING:'待处理',DISPATCHED:'处理中',UNKNOWN:'结果待核对',REJECTED:'未执行'}[value]||'待核对')
const action=value=>({DELETE:'删除记忆',UPDATE:'编辑记忆',PREFERENCE_CHANGED:'修改设置'}[value]||'记忆操作')
async function refresh(){
  const current=++generation;loading.value=true;error.value='';listError.value=''
  const results=await Promise.allSettled([memoryPreferences(),memoryList(limit),memoryAudit()])
  if(current!==generation)return
  if(results[0].status==='fulfilled'){settings.value=results[0].value;Object.assign(form,{readEnabled:settings.value.readEnabled,saveEnabled:settings.value.saveEnabled})}else{settings.value=null;error.value=results[0].reason.message}
  if(results[1].status==='fulfilled'){items.value=results[1].value.items;hasMore.value=results[1].value.hasMore;nextOffset.value=results[1].value.nextOffset}else{items.value=[];hasMore.value=false;nextOffset.value=null;listError.value=results[1].reason.message}
  if(results[2].status==='fulfilled')audit.value=results[2].value;else{audit.value=[];error.value=error.value||results[2].reason.message}
  loading.value=false
}
async function loadMore(){
  if(loading.value||busy.value||!hasMore.value||nextOffset.value==null)return
  const current=generation;loading.value=true;listError.value=''
  try{const data=await memoryList(limit,nextOffset.value);if(current!==generation)return;items.value=[...new Map([...items.value,...data.items].map(item=>[item.id,item])).values()];hasMore.value=data.hasMore;nextOffset.value=data.nextOffset}catch(e){if(current===generation)listError.value=e.message}finally{if(current===generation)loading.value=false}
}
async function saveSettings(){const current=generation,actor=identity;busy.value=true;error.value='';try{await changeMemoryPreferences({expectedRevision:settings.value.revision,...form});if(current!==generation)return;ElMessage.success('记忆设置已保存');await refresh()}catch(e){if(current===generation)error.value=e.message}finally{if(actor===identity)busy.value=false}}
function edit(item){Object.assign(editor,{visible:true,item:{...item},memory:item.memory,preview:false,error:'',needsReload:false})}
function closeEditor(done){if(!busy.value)done()}
async function reloadEditor(){
  const current=generation,actor=identity;busy.value=true
  try{const item=await personalMemory(editor.item.id);if(current!==generation)return;editor.item=item;editor.needsReload=false;editor.preview=false;editor.error='当前原文已更新 请重新核对 草稿保持不变'}catch(e){if(current===generation)editor.error=e.message}finally{if(actor===identity)busy.value=false}
}
async function saveMemory(){
  if(!canSave.value||!editor.preview||busy.value)return
  const current=generation,actor=identity;busy.value=true;editor.error=''
  try{await updatePersonalMemory(editor.item.id,{expectedDigest:editor.item.digest,memory:editor.memory.trim(),requestId:crypto.randomUUID(),confirmed:true});if(current!==generation)return;editor.visible=false;ElMessage.success('本人记忆已更新');await refresh()}catch(e){if(current===generation){editor.error=e.message;editor.needsReload=e.status===409||e.status===404||!e.status||e.status>=500;editor.preview=false}}finally{if(actor===identity)busy.value=false}
}
async function remove(item){
  if(busy.value||loading.value)return
  const current=generation,actor=identity;busy.value=true;error.value=''
  try{
    try{await ElMessageBox.confirm('将删除：'+item.memory.slice(0,160)+'。删除后不会再用于长期记忆检索，聊天记录仍然保留。','删除长期记忆',{confirmButtonText:'确认删除',cancelButtonText:'取消',type:'warning'})}catch{return}
    if(current!==generation)return
    await deletePersonalMemory(item.id,{expectedDigest:item.digest,requestId:crypto.randomUUID(),confirmed:true});if(current!==generation)return;ElMessage.success('本人记忆已删除');await refresh()
  }catch(e){if(current===generation){await refresh();if(actor===identity)error.value=e.message}}finally{if(actor===identity)busy.value=false}
}
function clearPrivateState(){generation++;identity++;items.value=[];audit.value=[];settings.value=null;hasMore.value=false;nextOffset.value=null;busy.value=false;Object.assign(editor,{visible:false,item:null,memory:'',preview:false,error:'',needsReload:false})}
watch(()=>user.username,()=>{clearPrivateState();refresh()})
onBeforeUnmount(clearPrivateState)
onMounted(refresh)
</script>
<style scoped>
.memory-page{padding:24px}.memory-page>header,.memory-item footer{display:flex;align-items:center;justify-content:space-between;gap:16px}.memory-page h2,.memory-page h3{color:#152942}.memory-page p,.memory-settings small{font-size:13px;color:#5a6b82;line-height:1.8}.memory-settings,.memory-list,.memory-audit{padding:20px;margin-top:20px;border:1px solid #dce6f4;border-radius:14px;background:#fff}.memory-settings label{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:12px 0}.memory-settings small{display:block}.memory-item{padding:16px;margin:12px 0;border:1px solid #e0e9f5;border-radius:12px;background:#f7faff;overflow-wrap:anywhere}.memory-item .memory-content{white-space:pre-wrap;font-size:14px;color:#24364e}.memory-item footer span{font-size:12px;color:#6c7b90}.memory-error{color:#b42318!important}.memory-audit summary{cursor:pointer}.memory-enter-active,.memory-leave-active,.memory-move{transition:opacity .18s ease,transform .18s ease}.memory-enter-from,.memory-leave-to{opacity:0;transform:translateY(5px)}.memory-page :deep(button){transition:transform .15s ease}.memory-page :deep(button:hover:not(:disabled)){transform:scale(1.02)}.memory-page :deep(button:active:not(:disabled)){transform:scale(.98)}@media(prefers-reduced-motion:reduce){.memory-enter-active,.memory-leave-active,.memory-move,.memory-page :deep(button){transition:none;transform:none!important}}@media(max-width:600px){.memory-page,.memory-settings,.memory-list,.memory-audit{padding:12px}.memory-page>header{align-items:flex-start}.memory-item footer{flex-wrap:wrap}}
</style>
<style>
.memory-edit-dialog .memory-original,.memory-edit-dialog .memory-preview{white-space:pre-wrap;overflow-wrap:anywhere;max-height:240px;overflow:auto;padding:12px;border:1px solid #dce6f4;border-radius:8px;background:#f7faff;color:#24364e}.memory-edit-dialog .memory-error{color:#b42318}.memory-editor-buttons{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px}.memory-editor-buttons .el-button+.el-button{margin-left:0}.memory-pagination{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:13px;color:#5a6b82}.memory-actions{display:flex;flex-wrap:wrap;gap:8px}.memory-actions .el-button+.el-button{margin-left:0}
</style>
