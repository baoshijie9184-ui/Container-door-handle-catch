<template>
  <section class="bailian-budget" aria-labelledby="bailian-budget-title">
    <header class="section-title">
      <span class="section-icon"><AppIcon name="Collection" :size="19" /></span>
      <div><h3 id="bailian-budget-title">阿里云百炼</h3><p>{{ supervisor ? '厂家预算' : '我的限额' }} · 每个模型独立核算</p></div>
    </header>

    <div class="quota-stats" role="group" aria-label="按额度状态筛选模型">
      <button v-for="item in filters" :key="item.key" type="button" class="stat"
              :aria-pressed="category === item.key" @click="category = item.key">
        <span>{{ item.label }}</span><strong>{{ item.count }}<small>个</small></strong>
      </button>
    </div>

    <div class="catalog">
      <div class="catalog-tools">
        <label class="model-search">
          <AppIcon name="Search" :size="16" />
          <input v-model.trim="query" type="search" aria-label="筛选模型" placeholder="搜索模型名称">
        </label>
        <span>单位：token</span>
      </div>
      <div class="table-scroll" tabindex="0" role="region" aria-label="百炼各模型额度">
        <table class="bailian-table">
          <thead><tr>
            <th scope="col">模型名称</th><th scope="col">剩余额度 / 总额</th>
            <th scope="col" class="numeric">已用</th><th scope="col" class="numeric">预留</th>
            <th v-if="supervisor && employee" scope="col">员工限额 / 可用</th>
            <th scope="col">额度状态</th><th v-if="supervisor" scope="col">管理</th>
          </tr></thead>
          <tbody><tr v-for="row in pageRows" :key="row.group.key">
            <th scope="row">{{ row.group.label }}</th>
            <td class="balance-cell">
              <div v-if="row.account" class="balance-meter">
                <div class="meter-track" aria-hidden="true"><i :style="{ width: row.remainingPercent + '%' }" /></div>
                <span><b>{{ formatTokens(row.account.available) }}</b> / {{ formatTokens(row.account.limit) }}</span>
              </div>
              <span v-else class="muted">—</span>
            </td>
            <td class="numeric">{{ formatTokens(row.used) }}
              <details v-if="supervisor && Number(row.account?.openingUsed) > 0">
                <summary>含期初用量</summary><p>期初 {{ formatTokens(row.account.openingUsed) }} · 本站 {{ formatTokens(row.account.spent) }}</p>
              </details>
            </td>
            <td class="numeric">{{ formatTokens(row.account?.reserved) }}</td>
            <td v-if="supervisor && employee">{{ row.group.member ? formatTokens(row.group.member.limit) + ' / ' + formatTokens(row.group.member.available) : '未分配' }}</td>
            <td><span class="quota-status" :class="{ available: row.available > 0 }">{{ row.status }}</span></td>
            <td v-if="supervisor"><div class="row-actions">
              <el-button link type="primary" @click="emit('configure', 'NATIVE_POOL', row.group)">登记额度</el-button>
              <el-button link type="primary" :disabled="!employee" @click="emit('configure', 'NATIVE_MEMBER', row.group)">分配限额</el-button>
            </div></td>
          </tr></tbody>
        </table>
      </div>
      <div v-if="!filteredRows.length" class="empty" role="status">
        <span>{{ query ? '没有匹配“' + query + '”的百炼模型' : '当前筛选条件下没有模型' }}</span>
        <el-button link type="primary" @click="clearFilters">清除筛选</el-button>
      </div>
      <footer class="catalog-footer">
        <span aria-live="polite">共 {{ filteredRows.length }} 条<span v-if="filteredRows.length"> · 显示 {{ pageOffset + 1 }}–{{ pageOffset + pageRows.length }} 条</span></span>
        <div class="page-controls">
          <span>{{ pageSize }} 条 / 页</span>
          <el-pagination v-if="pageCount > 1" v-model:current-page="page" :page-size="pageSize"
                         :total="filteredRows.length" layout="prev, pager, next" background aria-label="百炼模型分页" />
        </div>
      </footer>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  groups: { type: Array, required: true },
  supervisor: Boolean,
  employee: [Number, String],
})
const emit = defineEmits(['configure'])
const query = ref('')
const category = ref('all')
const page = ref(1)
const pageSize = 5
const numbers = new Intl.NumberFormat('zh-CN')
const formatTokens = value => value == null ? '—' : numbers.format(value)

const rows = computed(() => props.groups.map(group => {
  const account = props.supervisor ? group.pool : group.member
  const used = account ? Number(account.openingUsed ?? 0) + Number(account.spent) : null
  const limit = Number(account?.limit)
  const available = account ? Number(account.available) : null
  const remainingPercent = limit > 0 ? Math.max(0, Math.min(100, 100 * available / limit)) : 0
  let status = props.supervisor ? '待登记' : '未分配'
  if (account) {
    status = available > 0 ? '可用' : '无可用额度'
    if (available < 0) status = '已超额'
  }
  return { group, account, used, limit, available, remainingPercent, status }
}))

const categories = [
  { key: 'all', label: '全部模型', matches: () => true },
  { key: 'half', label: '已用超过 50%', matches: row => row.limit > 0 && row.used * 2 > row.limit },
  { key: 'high', label: '已用超过 80%', matches: row => row.limit > 0 && row.used * 5 > row.limit * 4 },
  { key: 'empty', label: '无可用额度', matches: row => row.available !== null && row.available <= 0 },
]
const filters = computed(() => categories.map(item => ({ ...item, count: rows.value.filter(item.matches).length })))
const filteredRows = computed(() => {
  const active = categories.find(item => item.key === category.value)
  const search = query.value.toLowerCase()
  return rows.value.filter(row => active.matches(row) && row.group.label.toLowerCase().includes(search))
})
const pageCount = computed(() => Math.ceil(filteredRows.value.length / pageSize))
const pageOffset = computed(() => (page.value - 1) * pageSize)
const pageRows = computed(() => filteredRows.value.slice(pageOffset.value, pageOffset.value + pageSize))
watch([query, category, () => props.employee], () => { page.value = 1 })
watch(pageCount, count => { page.value = Math.min(page.value, Math.max(1, count)) })
function clearFilters() {
  query.value = ''
  category.value = 'all'
}
</script>

<style scoped>
.bailian-budget { min-width:0; display:grid; gap:16px; }
.section-title,.catalog-tools,.catalog-footer,.page-controls,.model-search,.row-actions { display:flex; align-items:center; }
.section-title { gap:10px; }
.section-icon { display:grid; place-items:center; width:38px; height:38px; border-radius:10px; background:var(--app-primary-soft); color:var(--app-primary); }
.section-title h3 { margin:0; font-size:18px; line-height:1.4; }
.section-title p { margin:2px 0 0; color:var(--app-text-secondary); font-size:13px; }
.quota-stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
.stat { display:grid; align-content:space-between; gap:12px; padding:16px 18px; border:1px solid var(--app-border); border-radius:12px; background:var(--app-surface-muted); color:var(--app-text-secondary); font:inherit; text-align:left; cursor:pointer; }
.stat:hover { border-color:var(--app-border-focus); }
.stat[aria-pressed="true"] { border-color:var(--app-primary); background:var(--app-primary-soft); color:var(--app-primary-deep); }
.stat > span { font-size:13px; font-weight:550; }
.stat strong { font-size:clamp(24px,2.2vw,32px); line-height:1; color:var(--app-text); font-variant-numeric:tabular-nums; }
.stat small { margin-left:5px; font-size:12px; font-weight:400; color:var(--app-text-secondary); }
.catalog { min-width:0; border:1px solid var(--app-border); border-radius:12px; }
.catalog-tools,.catalog-footer { justify-content:space-between; gap:10px; padding:12px 16px; color:var(--app-text-secondary); font-size:12px; }
.model-search { width:min(100%,260px); gap:8px; padding:0 12px; border:1px solid var(--app-border-strong); border-radius:8px; color:var(--app-text-muted); }
.model-search:focus-within { border-color:var(--app-primary); outline:2px solid var(--app-primary-soft); }
.model-search input { width:100%; min-width:0; height:36px; padding:0; border:0; outline:0; background:transparent; color:var(--app-text); font:inherit; font-size:13px; }
.table-scroll { overflow-x:auto; }
.bailian-table { width:100%; border-collapse:collapse; font-size:13px; font-variant-numeric:tabular-nums; }
.bailian-table th,.bailian-table td { padding:12px 16px; text-align:left; white-space:nowrap; }
.bailian-table thead th { background:var(--app-surface-muted); color:var(--app-text-secondary); font-size:12px; font-weight:600; }
.bailian-table tbody :is(td,th) { border-bottom:1px solid var(--app-border); }
.bailian-table tbody th { font-weight:600; }
.bailian-table tbody tr:hover { background:var(--app-primary-light); }
.bailian-table .numeric { text-align:right; }
.balance-meter { display:grid; gap:5px; min-width:110px; max-width:220px; }
.balance-meter span,.bailian-table details,.muted { color:var(--app-text-secondary); font-size:12px; }
.balance-meter b { color:var(--app-text); font-size:13px; font-weight:650; }
.meter-track { overflow:hidden; height:5px; border-radius:5px; background:var(--app-border); }
.meter-track i { display:block; height:100%; border-radius:inherit; background:var(--app-primary); }
.quota-status { display:inline-flex; align-items:center; gap:6px; color:var(--app-text-secondary); }
.quota-status::before { content:''; width:6px; height:6px; background:var(--app-text-muted); border-radius:50%; }
.quota-status.available::before { background:var(--app-primary); }
.row-actions { gap:12px; }.row-actions :deep(.el-button) { margin:0; min-height:32px; }
.bailian-table summary { cursor:pointer; }
.empty { display:flex; align-items:center; justify-content:center; flex-wrap:wrap; gap:12px; padding:26px 12px; color:var(--app-text-secondary); }
.page-controls { gap:12px; }
@media(max-width:760px) {
  .quota-stats { grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
  .stat { gap:10px; padding:13px; }
  .catalog-tools,.catalog-footer { flex-wrap:wrap; padding:10px; }
  .bailian-table th,.bailian-table td { padding:10px 12px; }
}
</style>
