<template>
  <el-button @click="openAlerts"><AppIcon name="Warning" :size="16" />采集告警</el-button>
  <el-drawer v-model="visible" title="采集告警" size="min(900px, 100vw)" append-to-body destroy-on-close>
    <div class="capture-alert-toolbar">
      <label for="capture-alert-status">处理状态</label>
      <el-select id="capture-alert-status" v-model="filters.status" placeholder="全部状态" @change="search">
        <el-option label="全部状态" value="" />
        <el-option v-for="status in alertStatuses" :key="status" :label="alertStatus(status)" :value="status" />
      </el-select>
      <el-button :loading="loading" @click="refresh"><AppIcon name="Refresh" :size="15" />刷新</el-button>
      <span v-if="!loading && !error && total !== null" class="capture-alert-count" role="status">共 {{ total }} 条</span>
    </div>
    <el-alert
      v-if="error && records.length"
      :title="`本次读取失败，当前显示上次读取结果。${error}`"
      type="error"
      show-icon
      :closable="false"
    />
    <TableReadHint v-if="records.length" />
    <el-table v-loading="loading" :data="records" row-key="id" :scrollbar-tabindex="0" role="region" aria-label="采集告警记录">
      <template #empty>
        <CollectionEmptyState
          :loading="loading"
          :error="error"
          :filtered="hasFilters"
          empty-title="暂无采集告警"
          empty-description="采集端登记告警后会显示在这里。"
          @retry="retry"
          @reset="reset"
        />
      </template>
      <el-table-column label="设备编号" prop="deviceCode" min-width="130" show-overflow-tooltip />
      <el-table-column label="告警" min-width="220">
        <template #default="{ row }">
          <div>{{ alertType(row.alertType) }}</div>
          <div v-if="row.alertMessage" class="capture-alert-message">{{ row.alertMessage }}</div>
        </template>
      </el-table-column>
      <el-table-column label="级别" min-width="86">
        <template #default="{ row }"><StatusBadge domain="deviceAlertLevel" :code="row.alertLevel" /></template>
      </el-table-column>
      <el-table-column label="处理状态" min-width="115">
        <template #default="{ row }"><StatusBadge domain="deviceAlert" :code="row.status" /></template>
      </el-table-column>
      <el-table-column label="登记时间" min-width="158">
        <template #default="{ row }">{{ row.createdAt ? beijingDateTime(row.createdAt) || '—' : '—' }}</template>
      </el-table-column>
    </el-table>
    <div v-if="total > pagination.size" class="page-footer">
      <el-pagination
        :current-page="pagination.current"
        :page-size="pagination.size"
        :total="total"
        :disabled="loading || !!error"
        layout="prev, pager, next"
        @current-change="changePage"
      />
    </div>
  </el-drawer>
</template>

<script setup>
import { ref, watch } from 'vue'
import CollectionEmptyState from '../../components/CollectionEmptyState.vue'
import { useManagedList } from '../../composables/useManagedList'
import { useUserStore } from '../../stores/user'
import { alertStatus, alertType } from '../../utils/agentCards'
import { beijingDateTime } from '../../utils/beijingTime'

const user = useUserStore()
const visible = ref(false)
const alertStatuses = ['OPEN', 'ACKNOWLEDGED', 'RESOLVED']
const canViewAlerts = () => user.isAuthenticated && user.role === 'SUPERVISOR'
const accountScope = () => JSON.stringify([user.accountEpoch, user.accountContext, user.role, user.isAuthenticated])

watch(accountScope, () => { visible.value = false }, { flush: 'sync' })

const { records, total, loading, error, filters, pagination, hasFilters, search, reset, refresh, retry, changePage } =
  useManagedList('/api/devices/capture-alerts', ['status'], {
    scope: accountScope,
    canRead: () => visible.value && canViewAlerts()
  })
pagination.size = 20

function openAlerts() {
  if (!canViewAlerts()) return
  visible.value = true
  reset()
}
</script>

<style scoped>
.capture-alert-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.capture-alert-toolbar .el-select {
  width: 130px;
}

.capture-alert-count,
.capture-alert-message {
  color: var(--app-text-secondary);
}

.capture-alert-message {
  font-size: 13px;
  overflow-wrap: anywhere;
}
</style>
