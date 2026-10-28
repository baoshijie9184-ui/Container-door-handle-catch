<template>
  <section class="history-overview app-panel" aria-labelledby="history-overview-title">
    <div class="history-lead">
      <div class="history-kicker"><AppIcon name="DataAnalysis" :size="16" />历史累计</div>
      <h2 id="history-overview-title">检测数据总览</h2>
      <p class="history-period">{{ period }} · 历史登记数据</p>
      <div class="history-image-count"><strong>{{ number(summary.imageCount) }}</strong><span>张</span></div>
      <p class="history-caption">累计登记图片</p>
      <div class="history-metrics">
        <div><strong>{{ number(summary.recordCount) }}</strong><span>历史批次</span></div>
        <div><strong>{{ number(summary.targetCount) }}</strong><span>登记目标</span></div>
        <div><strong>{{ number(summary.modelCount) }}</strong><span>检测模型</span></div>
      </div>
    </div>
    <div class="history-years">
      <div class="history-years-heading"><h3>年度图片规模</h3><span>张</span></div>
      <div v-for="row in years" :key="row.year" class="history-year">
        <span>{{ row.year }}</span><div class="history-track" aria-hidden="true"><div :style="{width: width(row.imageCount)}" /></div><strong>{{ number(row.imageCount) }}</strong>
      </div>
      <p v-if="!years.length" class="history-caption">年度资料待登记</p>
      <details class="history-details"><summary>查看年度登记明细</summary>
        <div class="history-table-scroll" tabindex="0" role="region" aria-label="年度登记明细，可横向滚动">
          <table><thead><tr><th scope="col">年份</th><th scope="col">批次</th><th scope="col">图片</th><th scope="col">目标</th></tr></thead>
            <tbody><tr v-for="row in years" :key="row.year"><th scope="row">{{ row.year }}</th><td>{{ number(row.recordCount) }}</td><td>{{ number(row.imageCount) }}</td><td>{{ number(row.targetCount) }}</td></tr></tbody>
          </table>
        </div>
      </details>
    </div>
  </section>
</template>
<script setup>
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import { knownCount } from '../utils/countPresentation'

const props = defineProps({ summary: { type: Object, required: true } })
const number = value => knownCount(value)?.toLocaleString('zh-CN') ?? '—'
const years = computed(() => Array.isArray(props.summary.yearlyTotals) ? props.summary.yearlyTotals.filter(row => Number.isInteger(row?.year) && knownCount(row.imageCount) !== null) : [])
const peak = computed(() => Math.max(0, ...years.value.map(row => knownCount(row.imageCount))))
const width = value => peak.value ? `${knownCount(value) / peak.value * 100}%` : '0%'
const period = computed(() => {
  const first = String(props.summary.firstRecordedAt || '').match(/^\d{4}/)?.[0]
  const last = String(props.summary.lastRecordedAt || '').match(/^\d{4}/)?.[0]
  return first && last ? first === last ? `${first} 年` : `${first}—${last} 年` : '累计登记'
})
</script>
<style scoped>
.history-overview { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:48px; margin:0; padding:28px 30px; overflow:hidden; background:var(--app-surface); border:1px solid var(--app-border); border-radius:12px; box-shadow:none; }
.history-lead,.history-years { min-width:0; }
.history-kicker { display:flex; align-items:center; gap:7px; font-size:12px; font-weight:550; color:var(--app-text-secondary); }
h2 { margin:9px 0 0; font-size:18px; font-weight:600; letter-spacing:-.025em; color:var(--app-text); }
.history-period,.history-caption { color:var(--app-text-muted); font-size:12px; line-height:1.8; }
.history-period { margin:5px 0 18px; }
.history-image-count { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }
.history-image-count strong { font-size:clamp(36px,3.8vw,54px); font-weight:600; line-height:1.12; letter-spacing:-.045em; font-variant-numeric:tabular-nums; color:var(--app-text); }
.history-image-count span { font-size:13px; color:var(--app-text-muted); }
.history-caption { margin:6px 0 0; }
.history-metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); margin-top:24px; padding-top:18px; border-top:1px solid var(--app-border); gap:14px; }
.history-metrics>div { display:grid; gap:5px; min-width:0; }
.history-metrics strong { font-size:18px; font-weight:600; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; color:var(--app-text); }
.history-metrics span { color:var(--app-text-muted); font-size:12px; }
.history-years { padding-left:30px; border-left:1px solid var(--app-border); }
.history-years-heading { display:flex; align-items:center; justify-content:space-between; margin:0 0 20px; }
.history-years-heading h3 { margin:0; font-size:13px; font-weight:550; }
.history-years-heading>span { font-size:11px; color:var(--app-text-muted); }
.history-year { display:grid; grid-template-columns:36px minmax(24px,1fr) 82px; align-items:center; gap:12px; margin:18px 0; font-size:12px; font-variant-numeric:tabular-nums; }
.history-year>span { color:var(--app-text-muted); }
.history-year>strong { text-align:right; font-weight:500; }
.history-track { height:6px; border-radius:3px; overflow:hidden; background:var(--app-surface-hover); }
.history-track>div { height:100%; background:var(--app-primary); border-radius:3px; transition:width var(--app-transition-slow); }
.history-details { margin-top:18px; font-size:12px; }
.history-details summary { width:fit-content; padding:4px 0; color:var(--app-primary); cursor:pointer; }
.history-table-scroll { overflow-x:auto; margin-top:10px; }
.history-details table { width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; white-space:nowrap; }
.history-details th,.history-details td { padding:9px 10px; border-bottom:1px solid var(--app-border); text-align:right; }
.history-details th:first-child { text-align:left; }
.history-details thead th { font-weight:550; color:var(--app-text-secondary); }
.history-details summary:focus-visible,.history-table-scroll:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
@media(max-width:950px) { .history-overview { gap:24px; padding:24px; } .history-years { padding-left:24px; } }
@media(max-width:620px) { .history-overview { grid-template-columns:1fr; gap:26px; padding:20px; } .history-years { padding:20px 0 0; border-left:0; border-top:1px solid var(--app-border); } .history-image-count strong { font-size:clamp(34px,10vw,46px); } .history-metrics { gap:10px; } .history-metrics strong { font-size:16px; } }
@media(prefers-reduced-motion:reduce) { .history-track>div { transition:none; } }
</style>
