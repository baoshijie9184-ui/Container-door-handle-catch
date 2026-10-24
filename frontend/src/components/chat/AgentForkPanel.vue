<template>
  <section ref="root" class="wb-fork-panel" aria-label="会话分支与回复切点">
    <p class="wb-fork-guide"><AppIcon name="DocumentCopy" :size="17" /><span>从已保存且已结束的回复创建独立分支。切点前的内容按原规则继承，原会话保留；有效审批、排队消息和正在执行的任务不继承，最终可用性由服务端核对。</span></p>
    <section v-if="source" class="wb-fork-source" aria-label="本会话的来源"><strong>分支来源</strong><code>{{ source.id }}</code><p>{{ source.cutoff ? '来源回复 #'+source.cutoff : '来源切点未记录' }}</p><button type="button" :disabled="busy" @click="$emit('source',source.id)"><AppIcon name="ArrowLeft" :size="14" />返回来源会话</button><p v-if="source.legacy" class="wb-note">旧轮次缺少精确附件快照，同秒附件未自动继承，可重新上传或关联。</p></section>
    <p v-else-if="known" class="wb-note">本次没有返回分支来源记录，不推断更早会话的关系。</p>
    <label class="wb-fork-query" :for="queryId">查找已保存回复<input :id="queryId" v-model="query" type="search" placeholder="回复内容或消息编号" /></label>
    <p class="wb-fork-count" role="status">显示 {{ visible.length }} / {{ candidates.length }} 个已加载切点，最多列出最近 20 个。这里只筛选当前对话资料。</p>
    <p v-if="!known || loading || readError" class="wb-note" :role="readError ? 'alert' : 'status'">{{ readError ? '工作台未能核对当前状态，请刷新后再创建分支。' : loading ? '正在读取工作台，暂不可创建分支。' : '工作台尚未完成读取。' }}</p>
    <div v-if="!visible.length" class="wb-fork-empty"><AppIcon :name="query.trim() ? 'Search' : 'DocumentCopy'" :size="23" /><strong>{{ query.trim() ? '没有匹配的已加载回复' : '暂无可列出的已保存回复' }}</strong><p>{{ query.trim() ? '清空查找条件后可重新查看。' : '请等待回复结束并保存，再重新读取会话。临时编号、占位消息和错误提示不会作为切点。' }}</p><button v-if="query.trim()" type="button" @click="query=''">清空查找条件</button></div>
    <section v-for="reply in visible" :key="reply.id" class="wb-fork-reply" :class="{'is-selected':selected?.id===reply.id}">
      <header><strong>回复 #{{ reply.id }}</strong><span>{{ reply.time ? reply.time+' UTC+8' : '回复时间未记录' }}</span></header><p>{{ reply.excerpt || '此回复没有可显示的纯文本摘录，请先在对话中核对。' }}</p>
      <details v-if="reply.preview"><summary>展开回复片段</summary><pre tabindex="0" aria-label="回复纯文本片段">{{ reply.preview }}</pre><p v-if="reply.truncated" class="wb-note">较长回复只展示部分内容，完整内容请在原对话中核对。</p></details>
      <button type="button" :data-fork-select="reply.id" :disabled="busy || !known || loading || !!readError" :aria-pressed="selected?.id===reply.id" :aria-expanded="selected?.id===reply.id" :aria-controls="queryId+'-confirm-'+reply.id" @click="selected={sessionId,id:reply.id,signature:reply.signature}"><AppIcon name="DocumentCopy" :size="14" />{{ selected?.id===reply.id ? '已选此回复' : '选择此回复创建分支' }}</button>
      <section v-if="selected?.id===reply.id && selected.sessionId===sessionId" :id="queryId+'-confirm-'+reply.id" class="wb-fork-confirm" aria-label="核对分支切点"><strong>所选切点：回复 #{{ selected.id }}</strong><p v-if="!selectedReply" role="alert">此回复资料已变化，请重新选择后再创建。</p><p v-else>创建后打开新会话。原会话保持完整，新分支的后续修改相互独立。</p><div><button type="button" class="wb-button-primary" :disabled="busy || !known || loading || !!readError || !selectedReply" @click="createFork">{{ busy ? '正在等待工作台操作' : '创建并打开分支' }}</button><button type="button" :disabled="busy" @click="clearSelection(reply.id)">取消选择</button></div></section>
    </section>
    <p v-if="selected && selected.sessionId===sessionId && !visible.some(reply=>reply.id===selected.id)" class="wb-note" role="status">所选回复不在当前可见范围，请重新选择可见回复后创建分支。</p>
  </section>
</template>
<script setup>
import {computed,getCurrentInstance,ref,watch} from 'vue'
import {forkCandidates,filterForkCandidates,forkLineage} from '@/utils/forkPresentation'
import '@/assets/agent-fork-panel.css'
const props=defineProps({sessionId:String,messages:{type:Array,default:()=>[]},lineage:Object,known:Boolean,loading:Boolean,readError:String,busy:Boolean})
const emit=defineEmits(['fork','source'])
const root=ref(null),query=ref(''),selected=ref(null),queryId=`fork-reply-query-${getCurrentInstance().uid}`
const candidates=computed(()=>forkCandidates(props.messages)),visible=computed(()=>filterForkCandidates(candidates.value,query.value)),source=computed(()=>forkLineage(props.lineage))
const selectedReply=computed(()=>selected.value && selected.value.sessionId===props.sessionId ? candidates.value.find(reply=>reply.id===selected.value.id && reply.signature===selected.value.signature) : null)
watch(()=>props.sessionId,()=>{query.value='';selected.value=null},{flush:'sync'})
function createFork(){if(!props.busy && props.known && !props.loading && !props.readError && selectedReply.value)emit('fork',selectedReply.value.id)}
function clearSelection(id){selected.value=null;root.value?.querySelector(`[data-fork-select="${id}"]`)?.focus({preventScroll:true})}
</script>
