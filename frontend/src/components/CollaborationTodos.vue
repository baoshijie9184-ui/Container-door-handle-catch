<template>
  <section class="collaboration-todos app-panel" aria-labelledby="collaboration-todos-title">
    <header>
      <h2 id="collaboration-todos-title">{{ supervisor ? '协同审批待办' : '我的协同进展' }}</h2>
      <el-button text type="primary" :loading="loading" @click="refresh">刷新待办</el-button>
    </header>
    <div class="collaboration-todo-columns">
      <section v-for="group in groups" :key="group.key">
        <h3><AppIcon :name="group.icon" :size="17" />{{ group.label }}<span v-if="!group.error && group.total !== null">共 {{ group.total }} 条</span></h3>
        <p v-if="group.error" role="status">{{ group.error }}</p>
        <ul v-else-if="group.items.length">
          <li v-for="row in group.items" :key="row.id">
            <router-link :to="row.to"><strong>{{ row.title }}</strong><small>{{ row.description }}</small><AppIcon name="ArrowRight" :size="14" /></router-link>
          </li>
        </ul>
        <p v-else>{{ group.total === null ? '正在读取待办' : '暂无待办' }}</p>
        <router-link :to="group.to" class="collaboration-todo-all">
          {{ !group.error && group.total > group.items.length ? group.allLabel : group.link }}
        </router-link>
      </section>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useUserStore } from '../stores/user'
import { captureAccountRequest } from '../api/request'
import { useAccountOperationScope } from '../composables/useAccountOperationScope'
import { useResourceChanges } from '../composables/useResourceChanges'
import { knownCount } from '../utils/countPresentation'

const user = useUserStore(), supervisor = computed(() => user.role === 'SUPERVISOR'), loading = ref(false)
const request = captureAccountRequest()
const reports = ref({ items: [], total: null, error: '' })
const quota = ref({ items: [], total: null, error: '' })
const scope = useAccountOperationScope(() => {
  reports.value = { items: [], total: null, error: '' }
  quota.value = { items: [], total: null, error: '' }
})
const read = scope.channel()
const reportQuery = computed(() => ({ status: 'SUBMITTED', ...(supervisor.value ? { awaitingMyApproval: '1' } : {}) }))
const quotaQuery = computed(() => ({ scope: supervisor.value ? 'team' : 'mine', status: 'PENDING' }))

function readPreview(response, field) {
  const data = response.data?.code === 200 ? response.data.data : response.data
  const total = knownCount(data?.total)
  if (!Array.isArray(data?.[field]) || total === null || total < data[field].length || (total > 0 && !data[field].length)) {
    throw new Error('待办未完整读取')
  }
  return { items: data[field], total }
}

async function refresh() {
  const token = read.begin()
  loading.value = true
  const reportFilter = reportQuery.value
  const quotaFilter = quotaQuery.value
  await Promise.allSettled([
    request.get('/api/detection/reports', {
      params: { page: 1, size: 5, ...reportFilter }, signal: token.signal
    }).then(response => {
      const { items, total } = readPreview(response, 'records')
      if (read.current(token)) reports.value = {
        total, error: '', items: items.map(row => ({
          id: row.reportId, title: row.title || row.reportId,
          description: '待审批 · ' + (row.ownerUsername || '编写账号未记录'),
          to: { path: '/quality/reports', query: { ...reportFilter, reportId: row.reportId } }
        }))
      }
    }).catch(() => { if (read.current(token)) reports.value = { ...reports.value, error: '报告待办暂不可读取，请到报告页核对。' } }),
    request.get('/api/agent/model-quotas/applications', {
      params: { ...quotaFilter, includeTotal: true, limit: 5 }, signal: token.signal
    }).then(response => {
      const { items, total } = readPreview(response, 'items')
      if (read.current(token)) quota.value = {
        total, error: '', items: items.map(row => ({
          id: row.id, title: row.modelId, description: '申请追加 ' + row.requestedTokens + ' token',
          to: { path: '/agent/model-quotas', query: { ...quotaFilter, applicationId: row.id } }
        }))
      }
    }).catch(() => { if (read.current(token)) quota.value = { ...quota.value, error: '额度待办暂不可读取，请到额度页核对。' } })
  ])
  if (read.current(token)) loading.value = false
}

useResourceChanges({ domains: ['QUALITY_REPORT', 'LLM_QUOTA_APPLICATION', 'MODEL_BUDGET'], refresh })
onMounted(refresh)
const groups = computed(() => [{
  key: 'report', icon: 'DocumentChecked', label: supervisor.value ? '待审报告' : '待主管审批的报告', ...reports.value,
  to: { path: '/quality/reports', query: reportQuery.value }, link: '查看待审批报告', allLabel: '查看全部待审批报告'
}, {
  key: 'quota', icon: 'Cpu', label: supervisor.value ? '待审额度申请' : '待主管审批的额度申请', ...quota.value,
  to: { path: '/agent/model-quotas', query: quotaQuery.value }, link: '查看待审批申请', allLabel: '查看全部待审批申请'
}])
</script>
<style scoped>.collaboration-todos{padding:22px;margin:18px 0}.collaboration-todos>header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.collaboration-todos h2{font-size:18px;margin:0}.collaboration-todos p{font-size:12px;color:var(--app-text-secondary);line-height:1.8}.collaboration-todo-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:16px}
.collaboration-todo-columns>section{min-width:0;padding:14px 16px;background:var(--app-surface-muted);border-radius:9px}
.collaboration-todo-columns h3>.el-icon{color:var(--app-primary)}
.collaboration-todo-columns h3+p{margin-top:7px}.collaboration-todo-columns h3{display:flex;align-items:center;gap:7px;font-size:14px}.collaboration-todo-columns h3 span{font-size:12px;color:var(--app-text-secondary);font-weight:400;margin-left:auto}.collaboration-todo-columns ul{list-style:none;padding:0;margin:0}.collaboration-todo-columns li{border-top:1px solid var(--app-border)}.collaboration-todo-columns li a{display:grid;grid-template-columns:1fr auto;gap:6px;padding:13px 0;color:var(--app-text);text-decoration:none}.collaboration-todo-columns li strong{font-size:13px;font-weight:500}.collaboration-todo-columns li small{grid-row:2;color:var(--app-text-secondary)}.collaboration-todo-columns li .el-icon{grid-column:2;grid-row:1/3;align-self:center;color:var(--app-primary)}.collaboration-todo-all{display:inline-flex;margin-top:13px;color:var(--app-primary);font-size:12px}.collaboration-todos a:focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}@media(max-width:650px){.collaboration-todo-columns{grid-template-columns:1fr;gap:10px}.collaboration-todos{padding:15px}}</style>
