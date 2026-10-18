<template>
  <section class="memory-review-history">
    <header><h3>相似记忆审阅</h3><el-button :loading="historyLoading" @click="history">读取最近分析</el-button></header>
    <p>从记忆卡片选择查找相似 先对比正文 再决定是否停用 仅针对本人账号</p>
    <p v-if="historyError" role="alert">{{ historyError }}</p>
    <p v-else-if="!records.length">暂无分析记录 刷新和读取历史不会再次调用模型</p>
    <div v-for="entry in records" :key="entry.id" class="review-history-row"><span>{{ beijingDateTime(entry.createdAt) }} · {{ status(entry.status) }}</span><el-button size="small" @click="openHistory(entry.id)">查看对比</el-button></div>
    <el-dialog v-model="visible" title="相似记忆审阅" width="min(960px, calc(100vw - 32px))" class="memory-review-dialog" append-to-body :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" :before-close="close">
      <p v-if="error" role="alert" class="review-error">{{ error }}</p>
      <template v-if="!review">
        <p>本次会使用已配置的记忆模型比较最多五组候选 不会自动修改或删除记忆</p>
        <pre v-if="source" class="review-text">{{ source.memory }}</pre>
        <p>相似并不代表重复 请特别核对批次 时间 数值 否定词和适用范围 已关闭助手读取时不能发起 AI 对比</p>
        <el-button type="primary" :loading="saving" :disabled="!source||!!startId" @click="begin">开始分析</el-button>
        <el-button v-if="startId" :disabled="saving" @click="load(startId)">读取原分析结果</el-button>
      </template>
      <template v-else>
        <div class="review-toolbar"><span role="status">{{ status(review.status) }}</span><el-button :disabled="saving" @click="load(review.id)">读取结果核对</el-button></div>
        <p v-if="review.status==='RUNNING'">正在后台分析 关闭后可从最近分析继续查看 不会重复发起</p>
        <p v-if="['FAILED','INTERRUPTED'].includes(review.status)">本次未完成 请核对服务后重新发起分析 不会自动重试模型</p>
        <p v-if="review.sourceStale" class="review-error">原记忆已变化 停用或到期 本次建议失效 请重新分析</p>
        <p v-if="review.judgmentStatus==='UNAVAILABLE'" role="alert">模型暂未给出可核对的判断 候选仍保留 请自行对比 不表示没有重复</p>
        <p v-if="review.status==='READY'&&!review.candidates.length">本次近邻范围内没有可展示候选 不代表全库没有重复</p>
        <TransitionGroup name="review" tag="div">
          <article v-for="pair in review.candidates" :key="pair.id" class="review-pair">
            <h4>关系建议 {{ label(pair.label) }}</h4><p>建议仅供审阅 停用前请比较两条完整正文</p>
            <p v-if="pair.stale" class="review-error">候选已变化 停用或到期 不能继续使用原建议</p>
            <div class="review-grid"><section><h4>原记忆</h4><pre class="review-text">{{ review.source?.memory||'当前版本不可用于此审阅' }}</pre><small v-if="review.source?.sourceSessionId">来源会话 {{ review.source.sourceSessionId }}</small></section><section><h4>候选记忆</h4><pre class="review-text">{{ pair.item?.memory||'当前版本不可用于此审阅' }}</pre><small v-if="pair.item?.sourceSessionId">来源会话 {{ pair.item.sourceSessionId }}</small></section></div>
            <p v-if="decision(pair.id)">{{ choiceLabel(decision(pair.id).choice) }} · 已记录</p>
            <div v-else class="review-actions"><el-button :disabled="disabled(pair)" @click="propose(pair,'KEEP_SOURCE')">保留原记忆 停用候选</el-button><el-button :disabled="disabled(pair)" @click="propose(pair,'KEEP_CANDIDATE')">保留候选 停用原记忆</el-button><el-button :disabled="disabled(pair)" @click="propose(pair,'KEEP_BOTH')">保留两条</el-button></div>
          </article>
        </TransitionGroup>
        <p v-if="review.status==='READY'">候选来自本人账号最多二十条向量近邻 范围有限 不将相似度当作判断准确率</p>
        <p v-if="review.status==='READY'" class="review-usage"><template v-if="review.modelCalled===false">本次仅做精确文本比对 未调用语义模型</template><template v-else>记忆模型 {{ review.modelName||'未提供' }} · 模型耗时 {{ review.modelMillis==null?'未知':review.modelMillis+' ms' }} · 输入 Token {{ review.inputTokens??'未知' }} · 输出 Token {{ review.outputTokens??'未知' }} · 总 Token {{ review.totalTokens??'未知' }} · {{ review.usageSource==='PROVIDER'?'供应商报告值 不等同费用账单':'供应商未提供用量 不按零计算' }}</template></p>
        <section v-if="pending" class="review-confirm" aria-label="审阅处理预览"><h4>请确认 {{ choiceLabel(pending.choice) }}</h4><p>停用只影响后续长期记忆检索 原正文 聊天和已有有效期继续保留 可以在记忆卡片中恢复</p><el-button :disabled="saving" @click="pending=null">返回对比</el-button><el-button type="primary" :loading="saving" @click="confirm">确认处理</el-button></section>
      </template>
      <template #footer><el-button :disabled="saving" @click="visible=false">关闭</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import {onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {useUserStore} from '@/stores/user'
import {beijingDateTime} from '@/utils/beijingTime'
import {personalMemory,memoryReviews,memoryReview,startMemoryReview,resolveMemoryReview} from '@/api/agentMemory'
const emit=defineEmits(['updated']),user=useUserStore()
const visible=ref(false),saving=ref(false),source=ref(null),review=ref(null),error=ref(''),startId=ref(''),pending=ref(null),blocked=ref(false),uncertainId=ref(''),conflict=ref(false),records=ref([]),historyLoading=ref(false),historyError=ref('')
let generation=0,timer=null,pollDeadline=0
const status=value=>({RUNNING:'正在分析',READY:'分析已完成',FAILED:'分析未完成',INTERRUPTED:'分析已中断'}[value]||'等待分析')
const label=value=>({DUPLICATE:'可能重复',CONFLICT:'可能矛盾',RELATED:'相关但有区别',DISTINCT:'不同信息',UNSURE:'需要人工判断'}[value]||'需要人工判断')
const choiceLabel=value=>({KEEP_SOURCE:'保留原记忆并停用候选',KEEP_CANDIDATE:'保留候选并停用原记忆',KEEP_BOTH:'保留两条'}[value]||'待核对')
const decision=id=>review.value?.decisions?.find(row=>row.candidateId===id)
const disabled=pair=>saving.value||!!pending.value||blocked.value||review.value?.status!=='READY'||review.value.sourceStale||pair.stale
function reset(){generation++;clearTimeout(timer);source.value=null;review.value=null;pending.value=null;error.value='';startId.value='';blocked.value=false;uncertainId.value='';conflict.value=false;saving.value=false;historyLoading.value=false}
function close(done){if(!saving.value)done()}
async function history(){const actor=generation;historyLoading.value=true;try{const result=await memoryReviews();if(actor!==generation)return;if(!Array.isArray(result))throw new Error('分析历史暂不可用');records.value=result;historyError.value=''}catch(e){if(actor===generation){records.value=[];historyError.value=e.message}}finally{if(actor===generation)historyLoading.value=false}}
async function open(item){reset();visible.value=true;const actor=generation;saving.value=true;try{const current=await personalMemory(item.id);if(actor!==generation)return;if(!current.lifecycle)throw new Error('记忆审阅服务需要更新');source.value=current}catch(e){if(actor===generation)error.value=e.message}finally{if(actor===generation){saving.value=false;schedule()}}}
async function begin(){if(saving.value||!source.value||startId.value)return;const actor=generation;saving.value=true;error.value='';startId.value=crypto.randomUUID();try{const result=await startMemoryReview(source.value.id,{requestId:startId.value,expectedDigest:source.value.digest,expectedRevision:source.value.lifecycle.revision});if(actor!==generation)return;review.value=result;pollDeadline=Date.now()+120000;schedule();await history()}catch(e){if(actor===generation)error.value=e.message+' 请读取原分析结果核对 不会自动再次发起'}finally{if(actor===generation){saving.value=false;schedule()}}}
async function openHistory(id){reset();visible.value=true;pollDeadline=Date.now()+120000;await load(id)}
function schedule(){clearTimeout(timer);if(visible.value&&review.value?.status==='RUNNING'&&Date.now()<pollDeadline)timer=setTimeout(()=>load(review.value.id),2000)}
async function load(id){const actor=generation;if(saving.value)return;saving.value=true;try{const result=await memoryReview(id);if(actor!==generation)return;review.value=result;error.value='';if(uncertainId.value){if(result.decisions.some(row=>row.requestId===uncertainId.value)){blocked.value=false;uncertainId.value='';error.value='上次处理已核对 不会再次执行';emit('updated')}else if(conflict.value){blocked.value=false;uncertainId.value=''}else error.value='尚未找到对应处理回执 请稍后核对 不会自动重新提交'}schedule();await history()}catch(e){if(actor===generation){error.value=e.message;clearTimeout(timer);if([401,403].includes(e.status)){source.value=null;review.value=null;records.value=[]}}}finally{if(actor===generation){saving.value=false;schedule()}}}
function propose(pair,choice){if(disabled(pair))return;pending.value={requestId:crypto.randomUUID(),candidateId:pair.id,choice,expectedRevision:review.value.revision}}
async function confirm(){if(!pending.value||saving.value)return;const actor=generation,request={...pending.value,confirmed:true};saving.value=true;error.value='';try{const result=await resolveMemoryReview(review.value.id,request);if(actor!==generation)return;review.value=result;pending.value=null;emit('updated');await history()}catch(e){if(actor===generation){error.value=e.message+' 请读取结果核对';uncertainId.value=request.requestId;conflict.value=e.status===409;blocked.value=true;pending.value=null}}finally{if(actor===generation){saving.value=false;schedule()}}}
watch(visible,value=>{if(!value)clearTimeout(timer)})
watch(()=>user.username,()=>{reset();visible.value=false;records.value=[];historyError.value='';historyLoading.value=false;history()})
onBeforeUnmount(reset);onMounted(history);defineExpose({open})
</script>

<style scoped>
.memory-review-history{margin-top:20px;padding:20px;border:1px solid #dce6f4;border-radius:14px;background:white}.memory-review-history header,.review-history-row{display:flex;align-items:center;justify-content:space-between;gap:12px}.memory-review-history p,.review-history-row{font-size:13px;line-height:1.8;color:#5a6b82}.review-history-row{margin-top:10px;flex-wrap:wrap}.review-enter-active,.review-leave-active{transition:opacity .18s,transform .18s}.review-enter-from,.review-leave-to{opacity:0;transform:translateY(4px)}@media(prefers-reduced-motion:reduce){.review-enter-active,.review-leave-active{transition:none;transform:none}}
</style>
<style>
.memory-review-dialog .el-dialog__body{max-height:min(65vh,650px);overflow:auto}.memory-review-dialog p,.memory-review-dialog small{line-height:1.8;overflow-wrap:anywhere;color:#5a6b82}.memory-review-dialog .review-error{color:#b42318}.memory-review-dialog .review-pair,.memory-review-dialog .review-confirm{border:1px solid #dce6f4;border-radius:12px;padding:16px;margin:16px 0}.memory-review-dialog .review-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}.memory-review-dialog .review-text{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.8;max-height:240px;overflow:auto;background:#f7faff;padding:12px;border-radius:8px}.memory-review-dialog .review-actions,.memory-review-dialog .review-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px}.memory-review-dialog .el-button+.el-button{margin-left:0}@media(max-width:600px){.memory-review-dialog .review-grid{grid-template-columns:minmax(0,1fr)}.memory-review-dialog .review-pair{padding:12px}.memory-review-dialog .el-dialog__body{max-height:60vh}}
</style>
