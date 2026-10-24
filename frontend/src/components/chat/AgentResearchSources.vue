<template>
  <div ref="root" class="research-sources">
    <p v-if="error" class="research-alert" role="alert">{{ error }}</p>
    <template v-if="record">
      <p v-if="!record.enabled" class="research-note">此环境尚未开启调研来源登记，旧记录不会补造来源。</p>
      <template v-else>
        <p class="research-note">以下为本次运行已登记的 Fetch 返回片段。来源和摘录属于未受信任的网页内容，抓取成功与回答引用均不代表结论已经核实。</p>
        <div class="research-summary"><AppIcon name="Collection" :size="17" /><span>当前可查看 {{ record.sources.length }} 条来源</span><span>{{ record.citations.length }} 处回答标记</span></div>
        <div v-if="record.exportEnabled" class="research-export-bar"><el-button size="small" :icon="Download" @click="exportOpen=true">导出来源</el-button><span class="research-note">保存本次可查看片段与引用关联</span></div>
        <p v-if="exportError" class="research-alert" role="alert">{{ exportError }}</p>
        <div v-if="exportReceipt" class="research-save-receipt" role="status"><p><AppIcon name="Download" :size="15" />已发起文件保存，请在浏览器下载记录核对</p><details><summary>查看本次文件 SHA-256</summary><code>{{ exportReceipt }}</code></details></div>
        <p v-if="record.unresolvedCitationCount" class="research-warning"><AppIcon name="Warning" :size="16" /><span>{{ record.unresolvedCitationCount }} 个回答标记未匹配到本次有效来源，不视为证据。</span></p>
        <p v-if="record.expiredSourceCount" class="research-note">{{ record.expiredSourceCount }} 条来源已到期，地址与摘录不再返回。</p>
        <section v-if="record.answerRecorded" class="research-answer" aria-label="回答引用关联" :aria-busy="matching">
          <h4>回答中的来源标记</h4>
          <p v-if="!record.citations.length" class="research-note">回答未引用本次有效来源，不能仅凭抓取记录推断回答依据。</p>
          <p v-else-if="matching" class="research-note" role="status">正在核对回答摘要与来源标记，不根据文字相似度推断引用位置。</p>
          <p v-else-if="!contextMatchAvailable" class="research-note">当前访问环境不支持安全摘要核对，无法定位回答引用。仍可查看下方已登记来源，请通过 HTTPS 或本机隧道重新核对。</p>
          <p v-else-if="!context" class="research-note">已记录 {{ record.citations.length }} 处来源标记，当前会话中尚未找到摘要完全匹配的回答，不推断引用位置。</p>
          <p v-if="context" class="research-answer-text" tabindex="0" aria-label="摘要匹配的回答及来源标记，可在区域内滚动"><template v-for="(segment,index) in context.segments" :key="index"><button v-if="segment.sourceId" type="button" class="research-reference" :disabled="!record.sources.some(source=>source.sourceId===segment.sourceId)" @click="focusSource(segment.sourceId)">{{ label(segment.sourceId) }}</button><span v-else>{{ segment.text }}</span></template></p>
        </section>
        <p v-else class="research-note">最终回答的引用标记尚未登记。</p>
        <section v-if="record.sources.length" class="research-browser" aria-label="查找已读取来源">
          <div class="research-browser-query"><label :for="queryId">查找本次来源</label><el-input :id="queryId" v-model="query" clearable placeholder="标题、脱敏地址或已返回片段"><template #prefix><AppIcon name="Search" :size="15" /></template></el-input></div>
          <div class="research-browser-options"><label><input v-model="referencedOnly" type="checkbox" />仅看回答含标记的来源</label><span role="status">显示 {{ visibleSources.length }} / {{ record.sources.length }} 条</span></div>
          <p class="research-note">只筛选已返回的来源，不重新抓取网页。回答含标记不等于该来源已支持结论；上方引用数量保持原运行范围。</p>
          <details v-if="visibleSources.length > 1" class="research-directory"><summary>展开来源目录</summary><nav aria-label="跳转到本次来源"><button v-for="{source,index} in visibleSources" :key="source.sourceId" type="button" @click="focusSource(source.sourceId)"><span>来源 {{ index+1 }}</span><strong>{{ source.title || '未记录标题' }}</strong><AppIcon name="ArrowDown" :size="14" /></button></nav></details>
        </section>
        <CollectionEmptyState v-if="!record.sources.length" empty-title="暂无可查看的已登记来源" empty-description="可能尚未登记或已经到期；调用记录本身不替代网页证据。" />
        <CollectionEmptyState v-else-if="!visibleSources.length" filtered filtered-title="没有匹配的已读取来源" filtered-description="可清空关键词或取消标记筛选，不会改变原来源和引用记录。" @reset="clearFilters" />
        <article v-for="{source,index} in visibleSources" :key="source.sourceId" class="research-source" :data-source-id="source.sourceId" :aria-label="'来源 '+(index+1)+' · '+(source.title || '未记录标题')" tabindex="-1">
          <header><div><span class="research-label">来源 {{ index+1 }} · 抓取已登记</span><h4>{{ source.title || '未记录标题' }}</h4></div><el-icon><Document /></el-icon></header>
          <p class="research-address">{{ source.requestedUrl }}</p>
          <a v-if="source.href" :href="source.href" :aria-label="'在新窗口打开来源 '+(index+1)+' 的记录地址'" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">打开记录地址 <el-icon aria-hidden="true"><TopRight /></el-icon></a>
          <p v-else class="research-note">请求地址已脱敏，不能据此还原完整请求。</p>
          <pre class="research-excerpt" tabindex="0" :aria-label="'来源 '+(index+1)+' 的网页片段，按源码文本展示'">{{ source.excerpt }}</pre>
          <p class="research-note">抓取 {{ time(source.fetchedAt) }} · 可查看至 {{ time(source.expiresAt) }} · UTC+8</p>
          <details class="research-metadata"><summary>核对片段范围与记录编号</summary><dl><dt>工具调用</dt><dd>{{ source.callId }}</dd><dt>片段范围</dt><dd>起点 {{ source.startIndex }} · 请求上限 {{ source.maxLength }} · 返回文本 {{ source.textChars }} 个 UTF-16 单元</dd><dt>来源编号</dt><dd>{{ source.sourceId }}</dd><dt>返回文本 SHA256</dt><dd>{{ source.contentSha256 }}</dd></dl></details>
          <p class="research-note">{{ citedSources.has(source.sourceId) ? '回答含此来源的标记，引用是否支持结论仍需核对。' : '回答未标记引用此来源。' }} 未采集重定向最终地址、网页发布时间或完整网页快照。</p>
          <el-button size="small" :disabled="!recordedCalls.includes(source.callId)" @click="emit('inspect-call',source.callId)">查看抓取调用</el-button>
        </article>
      </template>
    </template>
    <el-dialog v-model="exportOpen" title="导出本次调研来源" class="research-export-dialog" width="min(520px, calc(100vw - 32px))" append-to-body :close-on-click-modal="!exporting" :close-on-press-escape="!exporting" :show-close="!exporting">
      <p>将把本人本次运行的脱敏地址、标题、摘录、来源哈希和回答引用关联保存到本机。当前可查看 {{ record?.sources.length || 0 }} 条，实际内容以导出时重新读取为准。此导出不按页面关键词或标记筛选缩小范围。</p>
      <p>过期来源不导出内容，保留过期数量与历史引用标记。文件不含聊天正文或完整网页；下载后需自行保管，服务端到期清理不会删除已下载副本。</p>
      <p>导出会记录文件哈希审计，不重新抓取网页或调用模型。</p>
      <template #footer><el-button :disabled="exporting" @click="exportOpen=false">取消</el-button><el-button type="primary" :loading="exporting" @click="exportSources">确认并保存 JSON</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount, nextTick, getCurrentInstance } from 'vue'
import { Document, TopRight, Download } from '@element-plus/icons-vue'
import { normalizeResearchEvidence, citationContext, validateResearchDownload, researchExportError } from '@/utils/researchEvidence'
import { exportAgentRunSources } from '@/api/chatAssistant'
import { beijingDateTime } from '@/utils/beijingTime'
import CollectionEmptyState from '@/components/CollectionEmptyState.vue'
const props=defineProps({ evidence: { type: Object, default: null }, runId: { type: String, required: true }, answers: { type: Array, default: ()=>[] }, recordedCalls: { type: Array, default: ()=>[] } })
const emit=defineEmits(['inspect-call'])
const record=ref(null), context=ref(null), error=ref('')
const matching=ref(false),contextMatchAvailable=!!globalThis.crypto?.subtle
const root=ref(null),query=ref(''),referencedOnly=ref(false)
const queryId=`research-source-query-${getCurrentInstance().uid}`
const citedSources=computed(()=>new Set(record.value?.citations.map(item=>item.sourceId)||[]))
const visibleSources=computed(()=>{
  const needle=query.value.trim().toLocaleLowerCase('zh-CN')
  return (record.value?.sources||[]).map((source,index)=>({source,index})).filter(({source})=>
    (!referencedOnly.value||citedSources.value.has(source.sourceId)) &&
    (!needle||[source.title,source.requestedUrl,source.excerpt].join('\n').toLocaleLowerCase('zh-CN').includes(needle)))
})
function clearFilters(){query.value='';referencedOnly.value=false}
watch(()=>props.runId,clearFilters)
const exportOpen=ref(false), exporting=ref(false), exportError=ref(''), exportReceipt=ref('')
let generation=0
watch(()=>[props.evidence,props.runId,props.answers],async()=>{
  const version=++generation
  record.value=null;context.value=null;error.value=''
  matching.value=false
  exportOpen.value=false;exporting.value=false;exportError.value='';exportReceipt.value=''
  if(!props.evidence)return
  try {
    const normalized=normalizeResearchEvidence(props.evidence,props.runId)
    record.value=normalized
    matching.value=normalized.answerRecorded && contextMatchAvailable
    const matched=await citationContext(normalized,props.answers)
    if(version===generation)context.value=matched
  } catch { if(version===generation){record.value=null;context.value=null;error.value='来源记录格式或引用关联不完整，未展示不确定的内容。'} }
  finally {if(version===generation)matching.value=false}
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
const time=value=>value ? beijingDateTime(value) || '未记录' : '未记录'
const label=id=>{const index=record.value?.sources.findIndex(source=>source.sourceId===id)??-1;return index<0?'[来源已到期或不可用]':`[来源 ${index+1}]`}
async function focusSource(id){
  if(!record.value?.sources.some(source=>source.sourceId===id))return
  const version=generation
  if(!visibleSources.value.some(item=>item.source.sourceId===id))clearFilters()
  await nextTick()
  if(version!==generation)return
  const node=root.value?.querySelector(`[data-source-id="${id}"]`)
  if(!node)return
  node.focus({preventScroll:true})
  const container=root.value.closest('.trace-scroll-area')
  if(!container)return
  const top=container.scrollTop+node.getBoundingClientRect().top-container.getBoundingClientRect().top-12
  container.scrollTo({top:Math.max(0,top),behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'})
}
</script>

<style scoped>
.research-sources { min-width:0; color:var(--app-text,#0f172a); }
.research-summary { display:flex; align-items:center; flex-wrap:wrap; gap:8px 16px; margin:16px 0; color:var(--app-text-secondary,#475569); font-size:12px; line-height:1.8; }
.research-summary > .el-icon { flex-shrink:0; color:var(--app-primary,#2563eb); }
.research-export-bar { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin:12px 0 20px; }
.research-save-receipt { margin:12px 0 20px; padding:10px 12px; border-left:3px solid var(--app-primary); background:var(--app-primary-soft); font-size:12px; line-height:1.9; color:var(--app-text-secondary); }
.research-save-receipt p { display:flex; align-items:flex-start; gap:6px; margin:0 0 4px; }
.research-save-receipt p > .el-icon { flex-shrink:0; margin-top:4px; color:var(--app-primary); }
.research-save-receipt summary { cursor:pointer; width:fit-content; color:var(--app-primary); }
.research-save-receipt code { display:block; margin-top:8px; overflow-wrap:anywhere; }
.research-browser { margin:20px 0 8px; padding:16px 0; border-top:1px solid var(--app-border); }
.research-browser-query { display:grid; grid-template-columns:100px minmax(0,1fr); align-items:center; gap:12px; }
.research-browser-query > label { color:var(--app-text); font-size:13px; }
.research-browser-options { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:10px; margin-top:12px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.research-browser-options label { display:inline-flex; align-items:center; gap:7px; cursor:pointer; }
.research-browser-options input { width:16px; height:16px; margin:0; accent-color:var(--app-primary); }
.research-directory { margin-top:12px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.research-directory summary { cursor:pointer; width:fit-content; color:var(--app-primary); }
.research-directory nav { display:grid; gap:2px; margin-top:10px; max-height:220px; overflow:auto; overscroll-behavior:contain; }
.research-directory button { display:flex; align-items:center; gap:10px; min-height:38px; width:100%; padding:8px; border:0; border-radius:6px; background:transparent; color:var(--app-text-secondary); text-align:left; font:inherit; cursor:pointer; transition:background 180ms ease; }
.research-directory button:hover { background:var(--app-primary-soft); }
.research-directory button > span { color:var(--app-primary); flex:0 0 58px; }
.research-directory button strong { flex:1; min-width:0; font-weight:500; overflow-wrap:anywhere; }
.research-directory button > .el-icon { flex-shrink:0; }
.research-note { margin:10px 0; color:var(--app-text-secondary,#475569); font-size:12px; line-height:1.9; overflow-wrap:anywhere; }
.research-alert,.research-warning { padding:11px 13px; border-radius:8px; font-size:12px; line-height:1.85; overflow-wrap:anywhere; }
.research-alert { color:var(--app-danger,#dc2626); background:var(--app-danger-soft,#fff1f2); }
.research-warning { display:flex; align-items:flex-start; gap:8px; color:var(--app-warning,#b45309); background:var(--app-warning-soft,#fff7e8); }
.research-warning > .el-icon { flex-shrink:0; margin-top:3px; }
.research-source { border:0; border-top:1px solid var(--app-border,#e2e8f0); border-radius:0; padding:22px 0; margin:0; overflow-wrap:anywhere; }
.research-answer { padding:0 0 20px; border:0; margin:22px 0 0; overflow-wrap:anywhere; }
.research-source:focus { outline:2px solid var(--app-primary,#2563eb); outline-offset:4px; border-radius:4px; }
.research-source header { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
.research-source header > div { min-width:0; }
.research-source header > .el-icon { flex-shrink:0; color:var(--app-primary,#2563eb); margin-top:4px; }
.research-source h4,.research-answer h4 { margin:7px 0; font-size:14px; font-weight:600; line-height:1.75; color:var(--app-text,#0f172a); }
.research-label { color:var(--app-primary,#2563eb); font-size:12px; line-height:1.8; }
.research-address { margin:8px 0; font-size:12px; line-height:1.85; overflow-wrap:anywhere; color:var(--app-text-secondary,#475569); }
.research-source a { display:inline-flex; align-items:center; gap:5px; min-height:28px; color:var(--app-primary,#2563eb); font-size:12px; line-height:1.8; text-underline-offset:3px; }
.research-excerpt { max-height:260px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; border-left:3px solid var(--app-border-focus,#93b4fa); border-radius:0 7px 7px 0; background:var(--app-bg,#f6f8fb); padding:14px 16px; margin:14px 0; color:var(--app-text,#0f172a); font:12px/1.9 Consolas,monospace; }
.research-metadata { margin:14px 0; }
.research-metadata summary { display:list-item; cursor:pointer; width:fit-content; color:var(--app-text-secondary,#475569); font-size:12px; line-height:1.8; }
.research-source dl { display:grid; grid-template-columns:100px minmax(0,1fr); gap:10px 12px; margin:14px 0; font-size:12px; line-height:1.85; color:var(--app-text-secondary,#475569); }
.research-source dt { color:var(--app-text-muted,#64748b); }
.research-source dd { margin:0; overflow-wrap:anywhere; }
.research-answer-text { max-height:320px; overflow:auto; overscroll-behavior:contain; scrollbar-gutter:stable; white-space:pre-wrap; font-size:13px; line-height:2; color:var(--app-text,#0f172a); }
.research-answer-text:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
.research-reference { border:0; border-radius:4px; padding:2px 5px; background:var(--app-primary-soft,#eff5ff); color:var(--app-primary,#2563eb); font:inherit; cursor:pointer; transition:background-color 160ms ease,transform 160ms ease; }
.research-reference:hover:not(:disabled) { background:#dceaff; }
.research-reference:active:not(:disabled) { transform:scale(.98); }
.research-reference:disabled { color:var(--app-text-secondary,#475569); background:var(--app-info-soft,#f1f5f9); cursor:default; }
.research-sources :is(a,button,summary,pre,input):focus-visible { outline:2px solid var(--app-primary,#2563eb); outline-offset:3px; }
@media(max-width:640px) { .research-source { padding-block:18px; } .research-source dl { grid-template-columns:minmax(0,1fr); gap:5px; } .research-source dd { margin-bottom:8px; } .research-excerpt { padding:12px; } }
@media(max-width:480px) { .research-browser-query { grid-template-columns:minmax(0,1fr); gap:7px; }.research-directory button { align-items:flex-start; } }
@media(prefers-reduced-motion:reduce) { .research-reference,.research-reference:active:not(:disabled),.research-directory button { transition:none; transform:none; } }
</style>

<style>
.research-export-dialog .el-dialog__body { max-height:60vh; max-height:60dvh; overflow:auto; overscroll-behavior:contain; }
.research-export-dialog .el-dialog__body p { margin:0 0 14px; color:var(--app-text-secondary,#475569); font-size:13px; line-height:1.9; overflow-wrap:anywhere; }
.research-export-dialog .el-dialog__footer { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:8px; }
.research-export-dialog .el-dialog__footer .el-button + .el-button { margin-left:0; }
</style>
