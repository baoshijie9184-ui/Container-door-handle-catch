<template>
  <section class="history-overview app-panel" aria-labelledby="history-overview-title">
    <header class="history-heading">
      <span class="history-icon"><AppIcon name="DataAnalysis" :size="21" /></span>
      <div><h2 id="history-overview-title">检测数据总览</h2><p>{{ period }} · 历史登记数据</p></div>
    </header>
    <dl class="history-metrics">
      <div class="history-volume"><dt>累计登记图片</dt><dd>{{ number(summary.imageCount) }}<small> 张</small></dd></div>
      <div><dt>历史批次</dt><dd>{{ number(summary.recordCount) }}</dd></div>
      <div><dt>登记目标</dt><dd>{{ number(summary.targetCount) }}</dd></div>
      <div><dt>检测模型</dt><dd>{{ number(summary.modelCount) }}</dd></div>
    </dl>
    <div class="history-chart-heading">
      <div class="history-chart-label"><h3>{{ measure.title }}</h3><span>单位：{{ measure.unit }}</span></div>
      <div class="history-switch" role="group" aria-label="年度图表指标">
        <button v-for="option in measures" :key="option.key" type="button" :aria-pressed="measure === option" @click="selected = option.key">{{ option.label }}</button>
      </div>
    </div>
    <div v-if="years.length" class="history-scroll" tabindex="0" role="region" :aria-label="measure.title + '，单位' + measure.unit">
      <ul class="year-chart">
        <li v-for="row in years" :key="row.year">
          <strong>{{ number(row[measure.key]) }}</strong>
          <span class="year-meter" aria-hidden="true"><i :style="{ height: barHeight(row[measure.key]) }" /></span>
          <span>{{ row.year }}</span>
        </li>
      </ul>
    </div>
    <p v-else>年度资料待登记</p>
    <details class="history-details"><summary>查看年度登记明细</summary>
      <div class="history-scroll" tabindex="0" role="region" aria-label="年度登记明细，可横向滚动">
        <table><thead><tr><th scope="col">年份</th><th scope="col">批次</th><th scope="col">图片</th><th scope="col">目标</th></tr></thead>
          <tbody><tr v-for="row in years" :key="row.year"><th scope="row">{{ row.year }}</th><td>{{ number(row.recordCount) }}</td><td>{{ number(row.imageCount) }}</td><td>{{ number(row.targetCount) }}</td></tr></tbody>
        </table>
      </div>
    </details>
  </section>
</template>
<script setup>
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { knownCount } from '../utils/countPresentation'

const props = defineProps({ summary: { type: Object, required: true } })
const number = value => knownCount(value)?.toLocaleString('zh-CN') ?? '—'
const measures = [
  { key: 'imageCount', label: '图片', title: '年度图片规模', unit: '张' },
  { key: 'targetCount', label: '目标', title: '年度登记目标数', unit: '个' }
]
const selected = ref('imageCount')
const measure = computed(() => measures.find(item => item.key === selected.value))
const years = computed(() => Array.isArray(props.summary.yearlyTotals)
  ? props.summary.yearlyTotals.filter(row => Number.isInteger(row?.year)).sort((a, b) => a.year - b.year)
  : [])
const peak = computed(() => Math.max(0, ...years.value.map(row => knownCount(row[measure.value.key]) ?? 0)))
const barHeight = value => peak.value ? ((knownCount(value) ?? 0) / peak.value * 100) + '%' : '0%'
const period = computed(() => {
  const first = String(props.summary.firstRecordedAt || '').match(/^\d{4}/)?.[0]
  const last = String(props.summary.lastRecordedAt || '').match(/^\d{4}/)?.[0]
  return first && last ? first === last ? first + ' 年' : first + '—' + last + ' 年' : '累计登记'
})
</script>
<style scoped>
.history-overview { min-width:0; margin:0; padding:22px; background:var(--app-surface); border:1px solid var(--app-border); border-radius:var(--app-radius-lg); box-shadow:var(--app-shadow-sm); }
.history-heading,.history-chart-heading,.history-switch { display:flex; align-items:center; }
.history-heading { gap:10px; }
.history-icon { display:grid; place-items:center; width:38px; height:38px; border-radius:11px; background:var(--app-primary-soft); color:var(--app-primary); }
.history-overview h2 { margin:0; font-size:17px; font-weight:650; color:var(--app-text); }
.history-overview p,.history-metrics dt { margin:3px 0 0; font-size:12px; color:var(--app-text-muted); }
.history-metrics { display:flex; flex-wrap:wrap; align-items:end; gap:10px 18px; margin:16px 0; padding-bottom:14px; border-bottom:1px solid var(--app-border); font-variant-numeric:tabular-nums; }
.history-metrics dd { margin:3px 0 0; font-size:16px; font-weight:650; color:var(--app-text); line-height:1.3; overflow-wrap:anywhere; }
.history-volume { margin-right:auto; }
.history-volume dd { font-size:clamp(25px,2.4vw,36px); letter-spacing:-.045em; }
.history-volume small { color:var(--app-text-muted); font-size:12px; font-weight:500; }
.history-chart-heading { justify-content:space-between; gap:8px; margin-bottom:10px; }
.history-chart-label { display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 8px; }
.history-chart-label > span { color:var(--app-text-muted); font-size:11px; }
.history-chart-heading h3 { margin:0; font-size:13px; font-weight:600; }
.history-switch { gap:2px; padding:3px; background:var(--app-surface-muted); border-radius:7px; }
.history-switch button { border:0; border-radius:5px; padding:4px 10px; background:transparent; color:var(--app-text-secondary); font:inherit; font-size:12px; cursor:pointer; }
.history-switch button[aria-pressed=true] { background:white; color:var(--app-primary-deep); font-weight:650; box-shadow:0 1px 4px #16345c20; }
.history-scroll { overflow-x:auto; }
.year-chart { display:grid; grid-auto-flow:column; grid-auto-columns:minmax(60px,1fr); gap:4px; margin:0; padding:0; list-style:none; }
.year-chart li { display:grid; grid-template-rows:auto 56px auto; gap:5px; text-align:center; font-size:11px; color:var(--app-text-muted); font-variant-numeric:tabular-nums; }
.year-chart strong { color:var(--app-text-secondary); font-weight:550; }
.year-meter { display:flex; align-items:end; justify-content:center; background:repeating-linear-gradient(to top,var(--app-border) 0 1px,transparent 1px 50%); }
.year-meter i { width:55%; max-width:40px; background:linear-gradient(to top,var(--app-primary-active),var(--el-color-primary-light-3)); border-radius:4px 4px 0 0; }
.history-details { margin-top:9px; font-size:12px; }
.history-details summary { width:fit-content; padding:4px 0; color:var(--app-primary); cursor:pointer; }
.history-details table { width:100%; border-collapse:collapse; white-space:nowrap; font-variant-numeric:tabular-nums; }
.history-details th,.history-details td { padding:8px; border-bottom:1px solid var(--app-border); text-align:right; }
.history-details th:first-child { text-align:left; }
.history-overview :is(summary,button,[tabindex]):focus-visible { outline:2px solid var(--app-primary); outline-offset:-2px; }
</style>
