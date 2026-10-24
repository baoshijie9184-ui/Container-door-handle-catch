<template>
  <section class="wb-context-summary" aria-label="上下文记录与覆盖范围" :data-invalid="view.invalidated">
    <p class="wb-context-explanation"><AppIcon :name="view.invalidated ? 'Warning' : view.offloaded ? 'Files' : 'Document'" :size="16" /><span>{{ view.explanation }}</span></p>
    <dl class="wb-context-scope"><dt>记录所属范围</dt><dd>{{ view.scope }}</dd><template v-if="!view.offloaded"><dt>{{ view.cutoffLabel }}</dt><dd>{{ view.cutoff }}</dd></template></dl>
    <template v-if="!view.offloaded"><div class="wb-context-counts"><div><span>压缩前字符数</span><strong>{{ view.before }}</strong></div><div><span>压缩后字符数</span><strong>{{ view.after }}</strong></div></div><p class="wb-context-change">{{ view.change }}</p><p class="wb-note">按本条记录的字符数比较，不换算 Token、账单或可用上下文容量。</p></template>
    <template v-else><p class="wb-context-size"><span>已记录资料大小</span><strong>{{ view.bytes }} 字节</strong></p><button v-if="canOpenFile" type="button" class="wb-context-files" @click="$emit('open-files')"><AppIcon name="Files" :size="15" />在文件产物中查看</button><p v-else class="wb-note">当前文件列表没有可用入口，不能据此判断原资料已删除。可刷新工作台或查看执行轨迹。</p><p class="wb-note">打开文件区不会执行工具或业务操作；预览和下载仍由原接口重新鉴权。</p><details class="wb-context-identifiers"><summary>核对资料编号与内容摘要</summary><dl><dt>文件编号</dt><dd><code>{{ view.fileId || '编号未记录或格式未知' }}</code></dd><dt>SHA-256</dt><dd><code>{{ view.sha256 || '摘要未记录或格式未知' }}</code></dd></dl></details></template>
  </section>
</template>
<script setup>
import { computed } from 'vue'
import { contextPresentation } from '@/utils/contextPresentation'
import '@/assets/agent-context-summary.css'
const props=defineProps({item:{type:Object,required:true},files:{type:Array,default:()=>[]},filesEnabled:{type:Boolean,default:true}})
defineEmits(['open-files'])
const view=computed(()=>contextPresentation(props.item))
const canOpenFile=computed(()=>props.filesEnabled && !!view.value.fileId && props.files.some(file=>file?.id===view.value.fileId))
</script>
