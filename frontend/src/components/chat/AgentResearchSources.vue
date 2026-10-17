<template>
  <div class="research-sources">
    <p v-if="error" class="research-alert" role="alert">{{ error }}</p>
    <template v-if="record">
      <p v-if="!record.enabled" class="research-note">此环境尚未开启调研来源登记，旧记录不会补造来源。</p>
      <template v-else>
        <p class="research-note">以下为本次运行已登记的 Fetch 返回片段。来源和摘录属于未受信任的网页内容，抓取成功与回答引用均不代表结论已经核实。</p>
        <div v-if="record.exportEnabled" class="research-export-bar"><el-button size="small" :icon="Download" @click="exportOpen=true">导出来源</el-button><span class="research-note">保存本次可查看片段与引用关联</span></div>
        <p v-if="exportError" class="research-alert" role="alert">{{ exportError }}</p>
        <p v-if="exportReceipt" class="research-note" role="status">已发起文件保存 · SHA256 {{ exportReceipt }}</p>
        <p v-if="record.unresolvedCitationCount" class="research-alert">{{ record.unresolvedCitationCount }} 个回答标记未匹配到本次有效来源，不视为证据。</p>
        <p v-if="record.expiredSourceCount" class="research-note">{{ record.expiredSourceCount }} 条来源已到期，地址与摘录不再返回。</p>
        <section v-if="record.answerRecorded" class="research-answer" aria-label="回答引用关联">
          <h4>回答中的来源标记</h4>
          <p v-if="!record.citations.length" class="research-note">回答未引用本次有效来源，不能仅凭抓取记录推断回答依据。</p>
          <p v-else-if="!context" class="research-note">已记录 {{ record.citations.length }} 处来源标记，当前会话中尚未找到摘要完全匹配的回答，不推断引用位置。</p>
          <p v-if="context" class="research-answer-text"><template v-for="(segment,index) in context.segments" :key="index"><button v-if="segment.sourceId" type="button" class="research-reference" :disabled="!record.sources.some(source=>source.sourceId===segment.sourceId)" @click="focusSource(segment.sourceId)">{{ label(segment.sourceId) }}</button><span v-else>{{ segment.text }}</span></template></p>
        </section>
        <p v-else class="research-note">最终回答的引用标记尚未登记。</p>
        <el-empty v-if="!record.sources.length" description="本次运行没有可查看的已登记来源" :image-size="64" />
        <article v-for="(source,index) in record.sources" :key="source.sourceId" class="research-source" :data-source-id="source.sourceId" tabindex="-1">
          <header><div><span class="research-label">来源 {{ index+1 }} · 抓取已登记</span><h4>{{ source.title || '未记录标题' }}</h4></div><el-icon><Document /></el-icon></header>
          <p class="research-address">{{ source.requestedUrl }}</p>
          <a v-if="source.href" :href="source.href" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">打开记录地址 <el-icon><TopRight /></el-icon></a>
          <p v-else class="research-note">请求地址已脱敏，不能据此还原完整请求。</p>
          <pre class="research-excerpt">{{ source.excerpt }}</pre>
          <dl><dt>抓取时间</dt><dd>{{ time(source.fetchedAt) }}</dd><dt>可查看至</dt><dd>{{ time(source.expiresAt) }}</dd><dt>工具调用</dt><dd>{{ source.callId }}</dd><dt>片段范围</dt><dd>起点 {{ source.startIndex }} · 请求上限 {{ source.maxLength }} · 返回文本 {{ source.textChars }} 个 UTF-16 单元</dd><dt>来源编号</dt><dd>{{ source.sourceId }}</dd><dt>返回文本 SHA256</dt><dd>{{ source.contentSha256 }}</dd></dl>
          <p class="research-note">{{ record.citations.some(ref=>ref.sourceId===source.sourceId) ? '回答含此来源的标记，引用是否支持结论仍需核对。' : '回答未标记引用此来源。' }} 未采集重定向最终地址、网页发布时间或完整网页快照。</p>
          <el-button size="small" :disabled="!recordedCalls.includes(source.callId)" @click="emit('inspect-call',source.callId)">查看抓取调用</el-button>
        </article>
      </template>
    </template>
    <el-dialog v-model="exportOpen" title="导出本次调研来源" width="min(520px, calc(100vw - 32px))" append-to-body :close-on-click-modal="!exporting" :close-on-press-escape="!exporting" :show-close="!exporting">
      <p>将把本人本次运行的脱敏地址、标题、摘录、来源哈希和回答引用关联保存到本机。当前可查看 {{ record?.sources.length || 0 }} 条，实际内容以导出时重新读取为准。</p>
      <p>过期来源不导出内容，保留过期数量与历史引用标记。文件不含聊天正文或完整网页；下载后需自行保管，服务端到期清理不会删除已下载副本。</p>
      <p>导出会记录文件哈希审计，不重新抓取网页或调用模型。</p>
      <template #footer><el-button :disabled="exporting" @click="exportOpen=false">取消</el-button><el-button type="primary" :loading="exporting" @click="exportSources">确认并保存 JSON</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { Document, TopRight, Download } from '@element-plus/icons-vue'
import { normalizeResearchEvidence, citationContext, validateResearchDownload, researchExportError } from '@/utils/researchEvidence'
import { exportAgentRunSources } from '@/api/chatAssistant'
const props=defineProps({ evidence: { type: Object, default: null }, runId: { type: String, required: true }, answers: { type: Array, default: ()=>[] }, recordedCalls: { type: Array, default: ()=>[] } })
const emit=defineEmits(['inspect-call'])
const record=ref(null), context=ref(null), error=ref('')
const exportOpen=ref(false), exporting=ref(false), exportError=ref(''), exportReceipt=ref('')
let generation=0
watch(()=>[props.evidence,props.runId,props.answers],async()=>{
  const version=++generation
  record.value=null;context.value=null;error.value=''
  exportOpen.value=false;exporting.value=false;exportError.value='';exportReceipt.value=''
  if(!props.evidence)return
  try {
    const normalized=normalizeResearchEvidence(props.evidence,props.runId)
    record.value=normalized
    const matched=await citationContext(normalized,props.answers)
    if(version===generation)context.value=matched
  } catch { if(version===generation){record.value=null;context.value=null;error.value='来源记录格式或引用关联不完整，未展示不确定的内容。'} }
},{immediate:true})
onBeforeUnmount(()=>{generation++})
async function exportSources(){
  if(exporting.value||!exportOpen.value||!record.value?.exportEnabled)return
  const version=generation, runId=props.runId
  exporting.value=true;exportError.value='';exportReceipt.value=''
  try {
    const response=await exportAgentRunSources(runId)
    if(version!==generation)return
    const file=await validateResearchDownload(response,runId)
    if(version!==generation)return
    const url=URL.createObjectURL(new Blob([file.bytes],{type:'application/json'}))
    try {const link=document.createElement('a');link.href=url;link.download=file.filename;document.body.appendChild(link);link.click();link.remove()}
    finally {setTimeout(()=>URL.revokeObjectURL(url),1000)}
    exportReceipt.value=file.sha256;exportOpen.value=false
  } catch (error) {
    if(version===generation){exportOpen.value=false;exportError.value=researchExportError(error)}
  } finally {if(version===generation)exporting.value=false}
}
const time=value=>value.replace('T',' ').slice(0,19)
const label=id=>{const index=record.value?.sources.findIndex(source=>source.sourceId===id)??-1;return index<0?'[来源已到期或不可用]':`[来源 ${index+1}]`}
function focusSource(id){const node=document.querySelector(`[data-source-id="${id}"]`);node?.focus();node?.scrollIntoView({block:'nearest',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'})}
</script>

<style scoped>
.research-export-bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:12px 0}
.research-note{color:#68768a;font-size:11px;line-height:1.85}.research-alert{color:#b54542;font-size:12px;line-height:1.8}.research-source,.research-answer{border:1px solid #e7ebf1;border-radius:12px;padding:16px;margin:14px 0;overflow-wrap:anywhere}.research-source:focus{outline:2px solid #2563eb;outline-offset:2px}.research-source header{display:flex;justify-content:space-between;gap:12px;color:#2563eb}.research-source h4,.research-answer h4{font-size:13px;margin:7px 0;color:#24354e}.research-label{font-size:10px;color:#2563eb}.research-address{font-size:12px;overflow-wrap:anywhere;color:#526078}.research-source a{display:inline-flex;align-items:center;gap:4px;font-size:11px;color:#2563eb}.research-excerpt{white-space:pre-wrap;font-family:inherit;font-size:12px;line-height:1.85;background:#f8faff;padding:12px;border-radius:8px;overflow-wrap:anywhere}.research-source dl{display:grid;grid-template-columns:100px minmax(0,1fr);gap:8px;font-size:11px;color:#526078}.research-source dt{color:#68768a}.research-source dd{margin:0;overflow-wrap:anywhere}.research-answer-text{white-space:pre-wrap;line-height:1.9;font-size:12px;color:#24354e}.research-reference{border:0;border-radius:4px;padding:1px 4px;background:#eff5ff;color:#2563eb;cursor:pointer;transition:background .16s}.research-reference:hover{background:#dceaff}.research-reference:disabled{color:#68768a;cursor:default}@media(max-width:640px){.research-source,.research-answer{padding:12px}.research-source dl{grid-template-columns:76px minmax(0,1fr)}}@media(prefers-reduced-motion:reduce){.research-reference{transition:none}}
</style>
