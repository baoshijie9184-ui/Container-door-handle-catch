<template>
  <section class="page-shell application-history">
    <PageHero title="检测申请记录" icon="DocumentChecked">
      <template #actions>
        <el-button :loading="loading" @click="refresh"><AppIcon name="Refresh" :size="16" />刷新</el-button>
      </template>
    </PageHero>

    <form class="toolbar-panel history-filters" aria-label="筛选检测申请" @submit.prevent="applyFilters">
      <label for="application-keyword">
        员工工号或申请号
        <el-input id="application-keyword" v-model="filters.keyword" clearable maxlength="64" placeholder="输入员工工号或申请号" />
      </label>
      <label for="application-task-id">
        任务编号
        <el-input id="application-task-id" v-model="filters.taskId" clearable maxlength="64" placeholder="输入完整原上传或派单任务编号" />
      </label>
      <div class="management-filter-actions">
        <el-button type="primary" native-type="submit" :loading="loading"><AppIcon name="Search" :size="16" />查询</el-button>
        <el-button v-if="hasFilters || Object.keys(appliedFilters).length" @click="resetFilters">重置</el-button>
      </div>
    </form>
    <el-alert v-if="filterError" :title="filterError" type="warning" :closable="false" />
    <p v-if="filtersDirty" class="application-notice" role="status">已修改查询条件，点击查询后更新记录。</p>

    <div class="table-panel">
      <div class="collection-heading">
        <h2>申请列表</h2>
        <span>{{ loading ? '正在读取…' : error ? '本次读取失败' : total === null ? '' : `共 ${total} 条` }}</span>
      </div>
      <el-alert v-if="error && records.length" :title="error + '；下方保留上次已读取的记录。'" type="error" :closable="false" />
      <TableReadHint v-if="records.length" />
      <el-table :data="records" row-key="workUnitId" v-loading="loading" role="region"
        aria-label="检测申请记录" :scrollbar-tabindex="0">
        <template #empty>
          <CollectionEmptyState :loading="loading" :error="error" :filtered="hasFilters"
            empty-title="暂无检测申请记录" empty-description="员工提交检测申请后，可在这里查看处理结果。"
            @retry="retry" @reset="resetFilters" />
        </template>
        <el-table-column label="申请" min-width="248">
          <template #default="{row}">
            <div class="history-cell">
              <strong>{{ row.applicantUserId || '工号未记录' }}</strong>
              <small>申请 {{ knownCount(row.imageCount) ?? '—' }} 张 · {{ formatTime(row.createdAt) }}</small>
              <code>{{ row.workUnitId }}</code>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="处理结果" min-width="220">
          <template #default="{row}">
            <div class="history-cell">
              <StatusBadge domain="report" :code="applicationState(row).badge" :label="applicationState(row).label" />
              <small v-if="row.decisionAccount">处理账号 {{ row.decisionAccount }}<template v-if="row.decisionAt"> · {{ formatTime(row.decisionAt) }}</template></small>
              <small v-else-if="row.decisionAt">{{ formatTime(row.decisionAt) }}</small>
              <small v-else-if="row.assignedAt">分配时间 {{ formatTime(row.assignedAt) }}</small>
              <small v-if="row.decisionReason">{{ row.decisionReason }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="原上传记录" min-width="238">
          <template #default="{row}">
            <router-link v-if="row.sourceAvailable && row.sourceBatchId"
              :to="{ path:'/inspection/uploads/all', query:{ keyword:row.sourceBatchId } }">{{ row.sourceBatchId }}</router-link>
            <code v-else-if="row.sourceBatchId">{{ row.sourceBatchId }}</code>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="正式派单与追溯" min-width="245">
          <template #default="{row}">
            <div class="history-cell">
              <router-link v-if="row.taskAvailable && row.batchId"
                :to="{ path:'/inspection/history', query:{ keyword:row.batchId } }">{{ row.batchId }}</router-link>
              <code v-else-if="row.batchId">{{ row.batchId }}</code>
              <span v-else>—</span>
              <router-link v-if="row.workOrderNo"
                :to="{ path:'/quality/work-order-trace', query:{ workOrderNo:row.workOrderNo } }">工单追溯</router-link>
              <router-link v-if="row.taskAvailable && row.batchId"
                :to="{ path:'/quality/reports', query:{ relatedTaskId:row.batchId } }">关联报告</router-link>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="total !== null && (total > pagination.size || pagination.current > 1)" class="page-footer">
        <el-pagination :current-page="pagination.current" :page-size="pagination.size" :total="total"
          :disabled="loading || !!error" layout="prev, pager, next" @current-change="changePage" />
      </div>
    </div>
  </section>
</template>

<script setup>
import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '../../components/AppIcon.vue'
import CollectionEmptyState from '../../components/CollectionEmptyState.vue'
import PageHero from '../../components/PageHero.vue'
import StatusBadge from '../../components/StatusBadge.vue'
import TableReadHint from '../../components/TableReadHint.vue'
import { useManagedList } from '../../composables/useManagedList'
import { useUserStore } from '../../stores/user'
import { beijingDateTime } from '../../utils/beijingTime'
import { knownCount } from '../../utils/countPresentation'

const route = useRoute(), router = useRouter(), user = useUserStore()
const ids = /^[A-Za-z0-9_-]{1,64}$/
const { records, total, loading, error, filterError, filters, pagination, hasFilters, filtersDirty, appliedFilters,
  search, refresh, retry, changePage } = useManagedList('/api/detection/supervisor/work-units/history', ['keyword', 'taskId'], {
  canRead: () => user.isAuthenticated && user.role === 'SUPERVISOR',
  validateFilters: values => values.keyword?.length > 64 ? '请输入不超过 64 个字符的工号或申请号。'
    : values.taskId && !ids.test(values.taskId) ? '请输入完整任务编号，可使用字母、数字、下划线与连字符。' : ''
})
pagination.size = 20

const text = value => typeof value === 'string' ? value.trim() : ''
const formatTime = value => beijingDateTime(value).slice(0, 16) || '时间未记录'
watch(() => [route.query.keyword, route.query.taskId], ([keyword, taskId]) => {
  filters.keyword = text(keyword)
  filters.taskId = text(taskId)
  void search()
}, { immediate: true })

function applyFilters() {
  const keyword = text(filters.keyword), taskId = text(filters.taskId)
  if (keyword === text(route.query.keyword) && taskId === text(route.query.taskId)) return search()
  return router.replace({ name: 'detectionApplicationHistory', query: { keyword: keyword || undefined, taskId: taskId || undefined } })
}

function resetFilters() {
  filters.keyword = ''
  filters.taskId = ''
  return applyFilters()
}

const states = {
  REJECTED: { badge: 'REJECTED', label: '已驳回' },
  WITHDRAWN: { badge: 'WITHDRAWN', label: '已撤回' },
  WAITING: { badge: 'SUBMITTED', label: '待审批' },
  ASSIGNED: { badge: 'SUBMITTED', label: '已分配' },
  PROCESSING: { badge: 'SUBMITTED', label: '处理中' },
  SUBMITTED: { badge: 'SUBMITTED', label: '已提交' },
  COMPLETED: { badge: 'APPROVED', label: '已完成' },
  CANCELLED: { badge: 'CANCELLED', label: '已取消' }
}
function applicationState(row) {
  if (row.status === 'ASSIGNED' && row.batchId && row.sourceBatchId) return { badge:'APPROVED', label:'已派单' }
  if (row.status === 'ASSIGNED' && row.assigneeUserId === row.applicantUserId && !row.batchId && !row.sourceBatchId) {
    return { badge:'SUBMITTED', label:'待补原图' }
  }
  return states[row.status] || { badge:'UNKNOWN', label:'状态待核对' }
}
</script>

<style scoped>
.application-history { min-width: 0; }
.history-filters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)) auto; gap: 14px; align-items: end; }
.history-filters label { display: grid; min-width: 0; gap: 6px; color: var(--app-text-secondary); font-size: 13px; }
.history-cell { display: grid; justify-items: start; min-width: 0; gap: 4px; padding: 6px 0; }
.table-panel :is(a, code), .history-cell small { overflow-wrap: anywhere; }
.history-cell small, .application-notice { color: var(--app-text-secondary); }
.application-notice { margin: 0; font-size: 13px; }
@media (max-width: 770px) {
  .history-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .history-filters .management-filter-actions { grid-column: 1 / -1; }
}
@media (max-width: 470px) { .history-filters { grid-template-columns: minmax(0, 1fr); } }
</style>
