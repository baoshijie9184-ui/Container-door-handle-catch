<template>
 <details class="chart-data-details">
  <summary><AppIcon name="DataAnalysis" :size="15" /><span>{{ title }}</span><small>{{ loading?'正在读取':readError?'本次读取未完成':loaded?'已读 '+rows.length.toLocaleString('zh-CN')+' 行':'尚未读取' }}</small><AppIcon name="ArrowDown" :size="13" class="chart-data-chevron" /></summary>
  <p v-if="readError" class="chart-data-error" role="status">{{ readError }}{{ rows.length?' 下方仅供核对，可能包含先前读取的值或缺失字段。':'' }}</p>
  <p class="chart-data-basis">使用已读取的统计值，不额外查询；图例显隐不改变明细范围。缺失数量显示“—”，不代表零。</p>
  <div v-if="rows.length" class="chart-data-scroll" tabindex="0" role="region" :aria-label="title+'，可在此区域滚动查看'">
   <table><caption>{{ scope || '统计范围尚未记录' }}</caption><thead><tr><th v-for="column in columns" :key="column.key" scope="col" :class="{'is-numeric':column.numeric}">{{ column.label }}</th></tr></thead><tbody><tr v-for="(row,index) in rows" :key="index"><td v-for="column in columns" :key="column.key" :class="{'is-numeric':column.numeric}">{{ value(row,column) }}</td></tr></tbody></table>
  </div>
  <p v-else class="chart-data-basis">{{ loading?'正在读取所选范围的统计。':!loaded?'尚未读取到可核对的明细。':readError?'本次没有可展示的已读明细。':'本次统计范围没有返回记录。' }}</p>
 </details>
</template>
<script setup>
import AppIcon from './AppIcon.vue'
import {knownCount} from '@/utils/countPresentation'
defineProps({title:{type:String,default:'查看图表数据'},scope:String,rows:{type:Array,default:()=>[]},columns:{type:Array,required:true},loaded:Boolean,loading:Boolean,readError:String})
function value(row,column){const raw=row?.[column.key];return column.numeric?knownCount(raw)?.toLocaleString('zh-CN')??'—':typeof raw==='string' && raw.trim()?raw:'未记录'}
</script>
<style scoped>
.chart-data-details { margin:14px 0 0; padding-top:12px; border-top:1px solid var(--app-border); min-width:0; }
.chart-data-details > summary { display:flex; align-items:center; flex-wrap:wrap; gap:6px; width:fit-content; max-width:100%; color:var(--app-primary); font-size:12px; line-height:1.9; cursor:pointer; list-style:none; }
.chart-data-details > summary::-webkit-details-marker { display:none; }
.chart-data-details > summary > .el-icon { flex-shrink:0; }
.chart-data-details > summary small { color:var(--app-text-secondary); font-size:12px; }
.chart-data-chevron { transition:transform 180ms ease; }
.chart-data-details[open] .chart-data-chevron { transform:rotate(180deg); }
.chart-data-basis,.chart-data-error { margin:10px 0; color:var(--app-text-secondary); font-size:12px; line-height:1.85; overflow-wrap:anywhere; }
.chart-data-error { color:var(--app-warning); }
.chart-data-scroll { max-width:100%; max-height:320px; overflow:auto; overscroll-behavior:contain; scrollbar-gutter:stable; }
.chart-data-scroll table { width:100%; border-collapse:collapse; color:var(--app-text); font-size:12px; line-height:1.85; }
.chart-data-scroll caption { padding:8px 0 12px; color:var(--app-text-secondary); text-align:left; overflow-wrap:anywhere; }
.chart-data-scroll :is(th,td) { min-width:100px; padding:8px 10px; border-bottom:1px solid var(--app-border); text-align:left; vertical-align:top; overflow-wrap:anywhere; }
.chart-data-scroll th { position:sticky; top:0; z-index:1; background:var(--app-surface-muted); color:var(--app-text-secondary); font-weight:600; }
.chart-data-scroll .is-numeric { text-align:right; font-variant-numeric:tabular-nums; }
.chart-data-details :is(summary,.chart-data-scroll):focus-visible { outline:2px solid var(--app-primary); outline-offset:2px; border-radius:3px; }
@media(prefers-reduced-motion:reduce) { .chart-data-chevron { transition:none; } }
</style>
