<template>
  <section class="memory-page app-panel">
    <header><div><h2><AgentSectionIcon kind="memory" />个人记忆</h2><p>管理助手保存的本人长期记忆 不包含其他账号的私人信息</p></div><el-button :loading="loading" :disabled="busy||editor.visible||policy.visible" @click="refresh"><AppIcon name="Refresh" :size="16" />刷新</el-button></header>
    <p v-if="error" role="alert" class="memory-error">{{ error }}</p>
    <section class="memory-settings" aria-label="长期记忆设置">
      <h3><AgentSectionIcon kind="memory" small />记忆设置</h3>
      <template v-if="settings">
        <label><span>允许助手读取长期记忆<small>关闭后不再将已保存的长期记忆加入回答参考</small></span><el-switch v-model="form.readEnabled" aria-label="允许读取长期记忆" :disabled="busy" /></label>
        <label><span>自动保存新的长期记忆<small>关闭后跳过新记忆提取 现有聊天记录和记忆继续保留</small></span><el-switch v-model="form.saveEnabled" aria-label="自动保存长期记忆" :disabled="busy" /></label>
        <div class="memory-settings-actions"><el-button type="primary" :loading="busy" :disabled="loading||!changed" @click="saveSettings"><AppIcon name="CircleCheck" :size="15" />保存设置</el-button><span v-if="changed" role="status">有尚未保存的设置，刷新会恢复已保存值</span><span v-else>两个聊天入口共用此设置</span></div><p>已经开始的保存不因关闭开关而撤销</p>
      </template>
      <p v-else>设置暂不可用 请刷新后重试</p>
    </section>
    <section class="memory-list" aria-label="本人已保存记忆" v-loading="loading">
      <div class="memory-list-heading"><h3><AgentSectionIcon kind="memory" small />已保存记忆</h3><span>{{ loading && !items.length ? '正在读取' : listError && !items.length ? '读取未完成' : `已读取 ${items.length} 条` }}{{ items.length && hasMore ? '，还有更多' : '' }}</span></div><p>编辑或删除前请核对正文 原聊天记录继续保留 如需停止后续提取 请关闭自动保存</p>
      <CollectionEmptyState v-if="!items.length" :loading="loading" :error="listError" empty-title="暂无已保存记忆" empty-description="助手完成长期记忆提炼后，可在这里核对正文、纠正或停用。" @retry="refresh" />
      <p v-if="listError&&items.length" class="memory-error" role="alert">{{ listError }} · 已显示记录不代表全部记忆，请稍后重新读取。</p>
      <TransitionGroup name="memory" tag="div">
        <article v-for="item in items" :key="item.id" class="memory-item">
          <div class="memory-item-status"><StatusBadge domain="memoryLifecycle" :code="memoryLifecycleCode(item.lifecycle,clock)" /><small v-if="item.lifecycle?.expiresAt">有效期 {{ memoryTime(item.lifecycle.expiresAt) }} UTC+8</small></div>
          <p class="memory-content">{{ item.memory }}</p><footer><span>更新 {{ memoryTime(item.updatedAt||item.createdAt) }}<template v-if="item.updatedAt||item.createdAt"> UTC+8</template></span><div class="memory-actions"><el-button :disabled="busy||loading||editor.visible||policy.visible" @click="duplicatePanel.open(item)"><AppIcon name="Search" :size="15" />查找相似</el-button><el-button :disabled="busy||loading||editor.visible||policy.visible" @click="openPolicy(item)"><AppIcon name="Clock" :size="15" />有效期与停用</el-button><el-button :disabled="busy||loading||editor.visible||policy.visible" @click="edit(item)"><AppIcon name="Edit" :size="15" />编辑记忆</el-button><el-button type="danger" plain :disabled="busy||loading||editor.visible||policy.visible" @click="remove(item)"><AppIcon name="Delete" :size="15" />删除记忆</el-button></div></footer>
        </article>
      </TransitionGroup>
      <div class="memory-pagination"><span>已显示 {{ items.length }} 条{{ hasMore?' · 还有更多记忆':'' }}</span><el-button v-if="hasMore" :loading="loading" :disabled="loading||busy||editor.visible||policy.visible" @click="loadMore">读取更多</el-button></div>
      <p v-if="items.length">列表变化后可刷新重新核对 编辑或删除完成后回到首批记录</p>
    </section>
    <MemoryDuplicateReview ref="duplicatePanel" @updated="refresh" />
    <details class="memory-lifecycle-history">
      <summary><AppIcon name="Clock" :size="16" />有效期与清理记录</summary>
      <p v-if="lifecycleError" class="memory-error" role="alert">{{ lifecycleError }}</p>
      <p v-else-if="loading&&!lifecycleHistory.length">正在读取清理记录…</p>
      <p v-else-if="!lifecycleHistory.length">尚无已读取的有效期与清理记录</p>
      <article v-for="entry in lifecycleHistory" :key="entry.memoryId" class="memory-history-entry"><div class="memory-item-status"><StatusBadge domain="memoryLifecycle" :code="memoryLifecycleCode(entry,clock)" /><StatusBadge domain="memoryCleanup" :code="entry.cleanupState" /></div><small class="memory-record-id">记忆 {{ entry.memoryId }}</small><p v-if="entry.expiresAt">{{ memoryTime(entry.expiresAt) }} UTC+8 到期</p><el-button v-if="entry.cleanupState==='NEEDS_REVIEW'" size="small" :disabled="busy||loading" @click="verifyCleanup(entry)"><AppIcon name="Search" :size="15" />核对清理结果</el-button></article>
      <p v-if="cleanupMessage" role="status">{{ cleanupMessage }}</p><p>到期后停止供助手检索 只有勾选自动清理并确认才会删除这条记忆 聊天与历史记录继续保留</p>
    </details>
    <details class="memory-audit">
      <summary><AppIcon name="DocumentChecked" :size="16" />本人最近操作记录</summary>
      <p v-if="auditError" class="memory-error" role="alert">{{ auditError }}</p>
      <p v-else-if="loading&&!audit.length">正在读取操作记录…</p><p v-else-if="!audit.length">暂无已读取的操作记录</p>
      <div v-for="record in audit" :key="record.id" class="memory-audit-entry"><div><strong>{{ action(record.action) }}</strong><small>{{ memoryTime(record.createdAt) }}<template v-if="record.createdAt"> UTC+8</template></small></div><StatusBadge domain="memoryAudit" :code="record.outcome" /><el-button v-if="record.action==='AUTOSAVE'&&record.requestId&&['DISPATCHED','UNKNOWN'].includes(record.outcome)" size="small" :disabled="busy||loading" @click="verifyExtraction(record)"><AppIcon name="Search" :size="15" />核对提炼结果</el-button></div>
      <p v-if="receiptMessage" role="status">{{ receiptMessage }}</p><p>核对只读取原提炼回执 不会重新执行保存 操作记录不保存记忆正文</p>
    </details>
    <el-dialog v-model="policy.visible" title="记忆有效期与停用" class="memory-policy-dialog" width="min(640px, calc(100vw - 32px))" append-to-body :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" :before-close="closeEditor">
      <p class="memory-original">{{ policy.item?.memory }}</p>
      <template v-if="!policy.preview">
        <label class="memory-policy-field">检索状态<el-select v-model="policy.state" aria-label="记忆检索状态" :disabled="busy"><el-option label="正常使用" value="ACTIVE"/><el-option label="停用错误或重复记忆" value="EXCLUDED"/></el-select></label>
        <label class="memory-policy-field">有效期 北京时间<input v-model="policy.expiry" type="datetime-local" aria-label="记忆有效期 北京时间" :disabled="busy"/></label><p>留空表示长期保留 停用与过期的记忆不会进入后续检索 已进入上下文的内容无法撤回</p>
        <el-checkbox v-model="policy.autoDelete" :disabled="busy">到期后自动删除这条记忆</el-checkbox><p>需要有效期并再次确认 不选择时仅停止检索 以后仍可延长有效期或手动删除</p>
      </template>
      <div v-else class="memory-policy-preview"><p>检索状态 {{ policy.state==='ACTIVE'?'正常使用':'停用' }}</p><p>有效期 {{ policy.expiry?policy.expiry.replace('T',' ')+' 北京时间':'长期保留' }}</p><p>{{ policy.autoDelete?'到期后自动删除这条记忆 删除后无法在此恢复 聊天与历史记录继续保留':'到期不自动删除 仍可在个人记忆页管理' }}</p></div>
      <p v-if="policy.error" class="memory-error" role="alert">{{ policy.error }}</p><p v-if="!validPolicy&&!policy.needsReload">有效期须为未来十年内的北京时间 自动删除需要有效期</p>
      <template #footer><div class="memory-editor-buttons"><el-button :disabled="busy" @click="policy.visible=false"><AppIcon name="Close" :size="16" />取消</el-button><el-button v-if="policy.needsReload" :loading="busy" @click="reloadPolicy">重新读取当前版本</el-button><template v-else><el-button v-if="policy.preview" :disabled="busy" @click="policy.preview=false">返回修改</el-button><el-button v-if="!policy.preview" type="primary" :disabled="busy||!validPolicy" @click="policy.preview=true">预览设置</el-button><el-button v-else type="primary" :loading="busy" :disabled="!validPolicy" @click="savePolicy">确认设置</el-button></template></div></template>
    </el-dialog>
    <el-dialog v-model="editor.visible" title="编辑长期记忆" class="memory-edit-dialog" width="min(640px, calc(100vw - 32px))" append-to-body :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" :before-close="closeEditor">
      <p>修改影响后续长期记忆检索 原聊天记录继续保留</p><p v-if="editor.item?.lifecycle?.state==='EXCLUDED'||editor.item?.lifecycle?.expiresAt&&businessTimestamp(editor.item.lifecycle.expiresAt)<=clock">这条记忆已停用或到期 修改正文不会自动恢复 请通过有效期与停用重新确认</p>
      <h4>当前原文</h4><p class="memory-original">{{ editor.item?.memory }}</p>
      <h4>{{ editor.preview?'待保存正文':'修改正文' }}</h4>
      <p v-if="editor.preview" class="memory-preview">{{ editor.memory.trim() }}</p>
      <el-input v-else v-model="editor.memory" type="textarea" :rows="6" maxlength="4000" show-word-limit aria-label="修改记忆正文" :disabled="busy" />
      <p v-if="editor.error" role="alert" class="memory-error">{{ editor.error }}</p>
      <p v-if="editor.needsReload">草稿已保留 请先重新读取原文 核对结果后再预览确认</p>
      <template #footer>
        <div class="memory-editor-buttons">
          <el-button :disabled="busy" @click="editor.visible=false"><AppIcon name="Close" :size="16" />取消</el-button>
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
import AgentSectionIcon from "@/components/chat/AgentSectionIcon.vue"
import {computed,onBeforeUnmount,onMounted,reactive,ref,watch} from 'vue'
import {ElMessage,ElMessageBox} from 'element-plus'
import MemoryDuplicateReview from '@/components/agent/MemoryDuplicateReview.vue'
import CollectionEmptyState from '@/components/CollectionEmptyState.vue'
import {memoryLifecycleCode,memoryTime} from '@/utils/memoryPresentation'
const duplicatePanel=ref(null)
import {useUserStore} from '@/stores/user'
import {beijingDateTime,businessTimestamp} from '@/utils/beijingTime'
import {memoryPreferences,memoryList,memoryAudit,personalMemory,changeMemoryPreferences,deletePersonalMemory,updatePersonalMemory,verifyMemoryExtraction,memoryLifecycle,changeMemoryLifecycle,verifyMemoryCleanup} from '@/api/agentMemory'
const user=useUserStore(),loading=ref(false),busy=ref(false),error=ref(''),listError=ref(''),settings=ref(null),items=ref([]),audit=ref([]),hasMore=ref(false),nextOffset=ref(null)
const auditError=ref('')
const limit=50,editor=reactive({visible:false,item:null,memory:'',preview:false,error:'',needsReload:false})
const form=reactive({readEnabled:true,saveEnabled:true});let generation=0,identity=0
const receiptMessage=ref(''),lifecycleHistory=ref([]),lifecycleError=ref(''),cleanupMessage=ref(''),clock=ref(Date.now());let clockTimer
const policy=reactive({visible:false,item:null,state:'ACTIVE',expiry:'',autoDelete:false,preview:false,error:'',needsReload:false})
const validPolicy=computed(()=>{const expires=policy.expiry?businessTimestamp(policy.expiry+':00+08:00'):null;return !!policy.item&&!policy.needsReload&&(!policy.autoDelete||!!expires)&&(!policy.expiry||expires>clock.value&&expires<clock.value+3650*86400000)})
async function openPolicy(item){const actor=identity;busy.value=true;try{const current=await personalMemory(item.id);if(actor!==identity)return;if(!current.lifecycle)throw new Error('记忆治理服务需更新 请稍后重试');Object.assign(policy,{visible:true,item:current,state:current.lifecycle.state,expiry:current.lifecycle.expiresAt?beijingDateTime(current.lifecycle.expiresAt).replace(' ','T').slice(0,16):'',autoDelete:current.lifecycle.autoDelete,preview:false,error:'',needsReload:false})}catch(e){if(actor===identity)error.value=e.message}finally{if(actor===identity)busy.value=false}}
async function reloadPolicy(){const actor=identity;busy.value=true;try{const current=await personalMemory(policy.item.id);if(actor!==identity)return;if(!current.lifecycle)throw new Error('记忆治理服务暂不可用');policy.item=current;policy.needsReload=false;policy.preview=false;policy.error='当前正文与版本已更新 请核对保留的设置草稿 再预览确认'}catch(e){if(actor===identity)policy.error=e.message}finally{if(actor===identity)busy.value=false}}
async function savePolicy(){if(busy.value||!policy.preview||!validPolicy.value)return;const actor=identity;busy.value=true;policy.error='';try{await changeMemoryLifecycle(policy.item.id,{requestId:crypto.randomUUID(),expectedDigest:policy.item.digest,expectedRevision:policy.item.lifecycle.revision,state:policy.state,expiresAt:policy.expiry?policy.expiry+':00+08:00':null,autoDelete:policy.autoDelete,confirmed:true});if(actor!==identity)return;policy.visible=false;ElMessage.success('记忆设置已提交 当前状态以刷新结果为准');await refresh()}catch(e){if(actor===identity){policy.error=e.message;policy.needsReload=e.status===409||e.status===404||!e.status||e.status>=500;policy.preview=false}}finally{if(actor===identity)busy.value=false}}
async function verifyCleanup(entry){const actor=identity;busy.value=true;try{const result=await verifyMemoryCleanup(entry.memoryId);if(actor!==identity)return;cleanupMessage.value=result.cleanupState==='SUCCEEDED'?'已核对记忆不存在 不会再次删除':'清理结果仍需核对 不会自动重新删除';await refresh()}catch(e){if(actor===identity)cleanupMessage.value=e.message}finally{if(actor===identity)busy.value=false}}
const changed=computed(()=>settings.value&&(form.readEnabled!==settings.value.readEnabled||form.saveEnabled!==settings.value.saveEnabled))
const canSave=computed(()=>editor.item&&editor.memory.trim().length>0&&editor.memory.length<=4000&&editor.memory.trim()!==editor.item.memory&&!editor.needsReload)
const action=value=>({DELETE:'删除记忆',UPDATE:'编辑记忆',AUTOSAVE:'自动提炼记忆',LIFECYCLE:'修改有效期与停用',REVIEW_DECISION:'审阅相似记忆',PREFERENCE_CHANGED:'修改设置'}[value]||'记忆操作')
async function verifyExtraction(record){const actor=identity;busy.value=true;receiptMessage.value='';try{const receipt=await verifyMemoryExtraction(record.requestId);if(actor!==identity)return;receiptMessage.value=receipt.status==='SUCCEEDED'?'提炼已完成 已核对 '+receipt.affectedMemories+' 条结果':receipt.status==='RUNNING'?'提炼尚未获得完成回执 请稍后核对':'提炼结果需要人工核对 不会自动重新执行';await refresh()}catch(e){if(actor===identity)receiptMessage.value=e.message}finally{if(actor===identity)busy.value=false}}
async function refresh(){
  const current=++generation;loading.value=true;error.value='';listError.value='';auditError.value=''
  const results=await Promise.allSettled([memoryPreferences(),memoryList(limit),memoryAudit(),memoryLifecycle()])
  if(current!==generation)return
  if(results[0].status==='fulfilled'){settings.value=results[0].value;Object.assign(form,{readEnabled:settings.value.readEnabled,saveEnabled:settings.value.saveEnabled})}else{settings.value=null;error.value=results[0].reason.message}
  if(results[1].status==='fulfilled'){items.value=results[1].value.items;hasMore.value=results[1].value.hasMore;nextOffset.value=results[1].value.nextOffset}else{items.value=[];hasMore.value=false;nextOffset.value=null;listError.value=results[1].reason.message}
  if(results[2].status==='fulfilled')audit.value=results[2].value;else{audit.value=[];auditError.value=results[2].reason.message}
  if(results[3].status==='fulfilled'){lifecycleHistory.value=results[3].value;lifecycleError.value=''}else{lifecycleHistory.value=[];lifecycleError.value=results[3].reason.message}
  loading.value=false
}
async function loadMore(){
  if(loading.value||busy.value||!hasMore.value||nextOffset.value==null)return
  const current=generation;loading.value=true;listError.value=''
  try{const data=await memoryList(limit,nextOffset.value);if(current!==generation)return;items.value=[...new Map([...items.value,...data.items].map(item=>[item.id,item])).values()];hasMore.value=data.hasMore;nextOffset.value=data.nextOffset}catch(e){if(current===generation)listError.value=e.message}finally{if(current===generation)loading.value=false}
}
async function saveSettings(){if(busy.value||loading.value||!settings.value||!changed.value)return;const current=generation,actor=identity;busy.value=true;error.value='';try{await changeMemoryPreferences({expectedRevision:settings.value.revision,...form});if(current!==generation)return;ElMessage.success('记忆设置已保存');await refresh()}catch(e){if(current===generation)error.value=e.message}finally{if(actor===identity)busy.value=false}}
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
function clearPrivateState(){generation++;identity++;receiptMessage.value='';cleanupMessage.value='';lifecycleHistory.value=[];lifecycleError.value='';Object.assign(policy,{visible:false,item:null,state:'ACTIVE',expiry:'',autoDelete:false,preview:false,error:'',needsReload:false});items.value=[];audit.value=[];settings.value=null;hasMore.value=false;nextOffset.value=null;busy.value=false;Object.assign(editor,{visible:false,item:null,memory:'',preview:false,error:'',needsReload:false})}
watch(()=>user.username,()=>{auditError.value='';clearPrivateState();refresh()})
onBeforeUnmount(()=>{clearInterval(clockTimer);clearPrivateState()})
onMounted(()=>{clockTimer=setInterval(()=>clock.value=Date.now(),30000);refresh()})
</script>
<style scoped>
.memory-page{padding:24px 24px 100px}.memory-page>header,.memory-item footer{display:flex;align-items:center;justify-content:space-between;gap:16px}.memory-page h2,.memory-page h3{color:#152942}.memory-page p,.memory-settings small{font-size:13px;color:#5a6b82;line-height:1.8}.memory-settings,.memory-list,.memory-audit{padding:20px;margin-top:20px;border:1px solid #dce6f4;border-radius:14px;background:#fff}.memory-settings label{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:12px 0}.memory-settings small{display:block}.memory-item{padding:16px;margin:12px 0;border:1px solid #e0e9f5;border-radius:12px;background:#f7faff;overflow-wrap:anywhere}.memory-item .memory-content{white-space:pre-wrap;font-size:14px;color:#24364e}.memory-item footer span{font-size:12px;color:#6c7b90}.memory-lifecycle-history{padding:20px;margin-top:20px;border:1px solid #dce6f4;border-radius:14px;overflow-wrap:anywhere}.memory-lifecycle-history summary{cursor:pointer}.memory-lifecycle-history,.memory-audit{scroll-margin-block:100px}.memory-error{color:#b42318!important}.memory-audit summary{cursor:pointer}.memory-enter-active,.memory-leave-active,.memory-move{transition:opacity .18s ease,transform .18s ease}.memory-enter-from,.memory-leave-to{opacity:0;transform:translateY(5px)}.memory-page :deep(button){transition:transform .15s ease}.memory-page :deep(button:hover:not(:disabled)){transform:scale(1.02)}.memory-page :deep(button:active:not(:disabled)){transform:scale(.98)}@media(prefers-reduced-motion:reduce){.memory-enter-active,.memory-leave-active,.memory-move,.memory-page :deep(button){transition:none;transform:none!important}}@media(max-width:600px){.memory-page,.memory-settings,.memory-list,.memory-audit{padding:12px}.memory-page{padding-bottom:100px}.memory-page>header{align-items:flex-start}.memory-item footer{flex-wrap:wrap}}
</style>

<style scoped>
.memory-list-heading { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; }
.memory-list-heading h3 { margin: 0; }
.memory-list-heading > span, .memory-settings-actions > span { font-size: 12px; color: var(--app-text-secondary); line-height: 1.8; }
.memory-settings-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 12px; }
.memory-item-status { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; margin-bottom: 8px; }
.memory-item-status > small { color: var(--app-text-muted); font-size: 11px; line-height: 1.8; }
.memory-history-entry { margin: 14px 0; padding: 14px 0; border-bottom: 1px solid var(--app-border); }
.memory-history-entry:last-of-type { border-bottom: 0; }
.memory-record-id { display: block; margin-top: 8px; color: var(--app-text-muted); font-size: 11px; overflow-wrap: anywhere; }
.memory-audit-entry { display: flex; align-items: center; flex-wrap: wrap; gap: 10px 16px; padding: 14px 0; border-bottom: 1px solid var(--app-border); }
.memory-audit-entry:last-of-type { border-bottom: 0; }
.memory-audit-entry > div { flex: 1 1 180px; min-width: 0; display: grid; gap: 5px; }
.memory-audit-entry strong { color: var(--app-text); font-size: 13px; font-weight: 550; }
.memory-audit-entry small { color: var(--app-text-muted); font-size: 11px; overflow-wrap: anywhere; }
.memory-audit summary, .memory-lifecycle-history summary { width: fit-content; max-width: 100%; color: var(--app-text); font-weight: 550; line-height: 1.8; }
.memory-audit summary .el-icon, .memory-lifecycle-history summary .el-icon { margin-right: 6px; vertical-align: middle; color: var(--app-primary); }
</style>
<style>
.memory-edit-dialog .memory-original,.memory-edit-dialog .memory-preview{white-space:pre-wrap;overflow-wrap:anywhere;max-height:240px;overflow:auto;padding:12px;border:1px solid #dce6f4;border-radius:8px;background:#f7faff;color:#24364e}.memory-edit-dialog .memory-error{color:#b42318}.memory-editor-buttons{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px}.memory-editor-buttons .el-button+.el-button{margin-left:0}.memory-pagination{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:13px;color:#5a6b82}.memory-actions{display:flex;flex-wrap:wrap;gap:8px}.memory-actions .el-button+.el-button{margin-left:0}
</style>

<style>
.memory-policy-dialog .memory-policy-field{display:flex;flex-direction:column;gap:8px;margin:16px 0}.memory-policy-dialog input[type="datetime-local"]{min-width:0;width:100%;box-sizing:border-box;padding:10px;border:1px solid #dce6f4;border-radius:8px;font:inherit}.memory-policy-dialog p{font-size:13px;line-height:1.8;overflow-wrap:anywhere}.memory-policy-dialog .memory-original{white-space:pre-wrap;max-height:180px;overflow:auto;padding:12px;background:#f7faff;border-radius:8px}.memory-policy-dialog .memory-error{color:#b42318}.memory-policy-dialog .memory-policy-preview{padding:12px;border:1px solid #dce6f4;border-radius:8px}
</style>
