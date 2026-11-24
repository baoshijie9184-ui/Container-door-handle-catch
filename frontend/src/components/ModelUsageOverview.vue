<template>
  <section class="model-usage" aria-label="模型使用量排行">
    <div class="usage-heading">
      <div class="usage-total">
        <strong>{{ number(total) }}</strong><span>{{ selected.unit }} · {{ rows.length }} 个模型</span>
      </div>
      <div class="usage-switch" role="group" aria-label="模型用量统计指标">
        <button v-for="(item, key) in metrics" :key="key" type="button" :aria-pressed="key === metric" @click="metric = key">{{ item.label }}</button>
      </div>
    </div>
    <ol class="usage-rows" :aria-label="selected.label + '从高到低'">
      <li v-for="row in rows" :key="row.modelId" class="usage-row">
        <span class="usage-model-name">{{ row.modelName }}</span>
        <span class="usage-track" aria-hidden="true">
          <span v-if="maximum > 0 && row.value !== null" class="usage-bar" :style="{width: `${100 * row.value / maximum}%`}" />
        </span>
        <span class="usage-value">{{ number(row.value) }}<small v-if="row.value !== null"> {{ selected.unit }}</small></span>
      </li>
    </ol>
    <ChartDataDetails title="查看模型使用明细" :columns="columns" :rows="rows" scope="按模型汇总已完成及部分失败的检测任务，同一图片的多次检测按实际执行分别计数" loaded />
    <details class="usage-rates">
      <summary>查看各模型图片漏检率</summary>
      <div class="usage-rate-grid">
        <section v-for="row in rows" :key="row.modelId" class="usage-rate-card">
          <h4>{{ row.modelName }}</h4>
          <ModelImageMissRate :groups="row.imageRateGroups" :task-count="row.taskCount" />
        </section>
      </div>
      <p>漏检率按模型版本和阈值计算，分母为成功检测图片。失败图片单独计数。</p>
    </details>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import ChartDataDetails from './ChartDataDetails.vue'
import ModelImageMissRate from './ModelImageMissRate.vue'
import { knownCount } from '@/utils/countPresentation'

const props = defineProps({ models: { type: Array, required: true } })
const metrics = { taskCount: { label: '任务数', unit: '项' }, totalImages: { label: '图片数', unit: '张' } }
const columns = [
  { key: 'modelName', label: '模型' },
  { key: 'modelNumber', label: '模型编号' },
  { key: 'taskCount', label: '任务数（项）', numeric: true },
  { key: 'totalImages', label: '图片数（张）', numeric: true }
]
const metric = ref('taskCount')
const selected = computed(() => metrics[metric.value])
const number = value => knownCount(value)?.toLocaleString('zh-CN') ?? '—'
const businessLabel = (value, fallback) => typeof value === 'string' && value.trim() && !/测试|\btest\b/i.test(value) ? value : fallback
const rows = computed(() => props.models.map(item => ({
  ...item,
  modelName: businessLabel(item.modelName, `模型 #${item.modelId}`),
  modelNumber: String(item.modelId),
  taskCount: knownCount(item.taskCount),
  totalImages: knownCount(item.totalImages),
  value: knownCount(item[metric.value]),
  imageRateGroups: Array.isArray(item.imageRateGroups) ? item.imageRateGroups.map(group => ({
    ...group, displayVersion: businessLabel(group.modelVersion, '历史版本')
  })) : []
})).sort((a, b) => (b.value ?? -1) - (a.value ?? -1) || a.modelName.localeCompare(b.modelName, 'zh-CN')))
const maximum = computed(() => rows.value[0]?.value ?? 0)
const total = computed(() => rows.value.some(row => row.value === null) ? null : rows.value.reduce((sum, row) => sum + row.value, 0))
</script>

<style scoped>
.usage-heading { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:14px; }
.usage-total { display:flex; gap:9px; align-items:baseline; color:var(--app-text-secondary); font-size:13px; }
.usage-total strong { color:var(--app-text); font-size:29px; font-weight:650; font-variant-numeric:tabular-nums; }
.usage-switch { display:inline-flex; gap:3px; padding:3px; border-radius:8px; background:var(--app-surface-muted); }
.usage-switch button { border:0; border-radius:6px; background:transparent; color:var(--app-text-secondary); padding:6px 13px; font-family:inherit; font-size:14px; cursor:pointer; }
.usage-switch button[aria-pressed='true'] { background:var(--app-surface); color:var(--app-primary-deep); box-shadow:var(--app-shadow-sm); font-weight:600; }
.usage-switch button:focus-visible { outline:2px solid var(--app-primary); outline-offset:2px; }
.usage-rows { margin:0; padding:0; list-style:none; }
.usage-row { display:grid; grid-template-columns:minmax(150px,28%) minmax(0,1fr) minmax(96px,auto); align-items:center; gap:16px; min-height:46px; padding:8px 0; border-bottom:1px solid var(--app-border); }
.usage-model-name { color:var(--app-text); font-weight:550; font-size:14px; overflow-wrap:anywhere; }
.usage-track { height:9px; border-radius:6px; background:var(--app-surface-muted); overflow:hidden; }
.usage-bar { display:block; height:100%; border-radius:6px; background:var(--app-primary); }
.usage-row:not(:first-child) .usage-bar { opacity:.72; }
.usage-value { text-align:right; color:var(--app-text); font-size:14px; font-weight:650; font-variant-numeric:tabular-nums; }
.usage-value small { margin-left:3px; color:var(--app-text-secondary); font-size:12px; font-weight:400; }
.usage-rates { border-top:1px solid var(--app-border); margin-top:14px; padding-top:10px; }
.usage-rates summary { width:fit-content; color:var(--app-primary); cursor:pointer; font-size:13px; }
.usage-rates p { color:var(--app-text-secondary); font-size:13px; }
.usage-rate-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr)); gap:12px; margin-top:12px; }
.usage-rate-card { min-width:0; padding:12px; border:1px solid var(--app-border); border-radius:8px; }
.usage-rate-card h4 { margin:0; color:var(--app-text); overflow-wrap:anywhere; }
@media(max-width:640px) { .usage-row { grid-template-columns:minmax(90px,40%) minmax(0,1fr) auto; gap:8px; } }
</style>
