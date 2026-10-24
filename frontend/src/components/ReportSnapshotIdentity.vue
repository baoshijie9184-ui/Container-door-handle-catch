<template>
  <details class="report-snapshot-identity">
    <summary><AppIcon name="DocumentCopy" :size="15" /><span>本版快照编号与校验摘要</span><AppIcon name="ArrowRight" :size="12" class="report-snapshot-chevron" /></summary>
    <dl><template v-for="field in fields" :key="field.label"><dt>{{ field.label }}</dt><dd>{{ field.value }}</dd></template></dl>
    <p>编号与摘要仅用于对照本版报告记录，不代表已重新核对原始任务。审批前仍需核对本版内容并明确确认。</p>
  </details>
</template>
<script setup>
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import { knownCount } from '@/utils/countPresentation'
const props=defineProps({report:{type:Object,required:true}})
const text=value=>typeof value==='string'&&value.trim()?value:'未记录'
const fields=computed(()=>[
  {label:'报告编号',value:text(props.report.reportId)},
  {label:'报告版本',value:knownCount(props.report.version)??'未记录'},
  {label:'依据任务编号',value:text(props.report.taskId)},
  {label:'依据内容摘要',value:text(props.report.sourceSha256)},
  {label:'报告快照摘要',value:text(props.report.snapshotSha256)}
])
</script>
<style scoped>
.report-snapshot-identity{margin:18px 0;padding:14px 0;border-top:1px solid var(--app-border);min-width:0}
.report-snapshot-identity>summary{display:flex;align-items:center;gap:7px;width:fit-content;max-width:100%;font-size:12px;line-height:1.85;color:var(--app-text-secondary);cursor:pointer;border-radius:3px;transition:color 180ms ease}
.report-snapshot-identity>summary>.el-icon{color:var(--app-primary);flex:none}
.report-snapshot-identity>summary>span{min-width:0;overflow-wrap:anywhere}
.report-snapshot-chevron{transition:transform 180ms ease}
.report-snapshot-identity[open]>summary .report-snapshot-chevron{transform:rotate(90deg)}
.report-snapshot-identity>summary:hover{color:var(--app-primary)}
.report-snapshot-identity dl{display:grid;grid-template-columns:130px minmax(0,1fr);gap:9px 16px;margin:14px 0;font-size:12px;line-height:1.85}
.report-snapshot-identity dt{color:var(--app-text-secondary)}
.report-snapshot-identity dd{margin:0;min-width:0;color:var(--app-text);overflow-wrap:anywhere}
.report-snapshot-identity p{margin:12px 0 0;font-size:12px;line-height:1.85;color:var(--app-text-secondary);max-width:72ch}
.report-snapshot-identity>summary:focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}
@media(max-width:540px){.report-snapshot-identity dl{grid-template-columns:1fr;gap:3px}.report-snapshot-identity dd{margin-bottom:7px}}
@media(prefers-reduced-motion:reduce){.report-snapshot-identity>summary,.report-snapshot-chevron{transition:none}}
</style>
