<template>
  <section class="page-shell historical-ledger">
    <PageHero :title="scope === 'all' ? '全部历史台账' : '我的历史台账'" icon="Tickets"
      description="旧台账仅保留检测汇总，未保存原图和结果文件。">
      <template #actions>
        <div v-if="isSupervisor" class="ledger-scope" role="group" aria-label="台账查看范围">
          <el-button :type="scope === 'mine' ? 'primary' : 'default'" :aria-pressed="scope === 'mine'"
            @click="switchScope('mine')">我的台账</el-button>
          <el-button :type="scope === 'all' ? 'primary' : 'default'" :aria-pressed="scope === 'all'"
            @click="switchScope('all')">全部台账</el-button>
        </div>
        <el-button :loading="loading" @click="refresh"><AppIcon name="Refresh" :size="16" />刷新</el-button>
      </template>
    </PageHero>

    <div class="table-panel">
      <div class="collection-heading">
        <h2>台账记录</h2>
        <span>{{ loading ? '正在读取…' : error ? '本次读取失败' : total === null ? '' : `共 ${total} 条` }}</span>
      </div>
      <el-alert v-if="error && records.length" :title="error + '；下方保留上次已读取的记录。'" type="error" :closable="false" />
      <TableReadHint v-if="records.length" />
      <el-table :data="records" row-key="id" role="region" aria-label="历史台账记录" :scrollbar-tabindex="0" v-loading="loading">
        <template #empty>
          <CollectionEmptyState :loading="loading" :error="error"
            :empty-title="scope === 'mine' ? '暂无分派到本账号的台账' : '暂无历史台账'"
            :empty-description="scope === 'mine' ? '分派到本账号后会显示在这里。' : ''"
            @retry="retry" />
        </template>
        <el-table-column label="原记录编号" min-width="115">
          <template #default="{row}"><code>{{ row.id }}</code></template>
        </el-table-column>
        <el-table-column label="原检测时间" min-width="194">
          <template #default="{row}">
            <div class="ledger-cell">
              <span>开始 {{ timestamp(row.startTime) }}</span>
              <small>完成 {{ timestamp(row.finishedAt) }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="模型" min-width="163">
          <template #default="{row}">
            <div class="ledger-cell">
              <span>{{ row.modelName || (row.modelId == null ? '未记录' : '模型 ' + row.modelId) }}</span>
              <small v-if="row.modelName && row.modelId != null">编号 {{ row.modelId }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="检测图片" min-width="100" align="right">
          <template #default="{row}">{{ count(row.detectedImages) }}</template>
        </el-table-column>
        <el-table-column label="主管责任" min-width="144">
          <template #default="{row}">
            <div class="ledger-cell">
              <span>{{ row.supervisorName || row.supervisorUsername || '未分派' }}</span>
              <small v-if="row.supervisorName && row.supervisorUsername && row.supervisorName !== row.supervisorUsername">
                {{ row.supervisorUsername }}
              </small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="检测责任" min-width="154">
          <template #default="{row}">
            <div class="ledger-cell">
              <span>{{ row.inspectorName || row.inspectorEmployeeNumber || row.inspectorUsername || '未分派' }}</span>
              <small v-if="row.inspectorName && row.inspectorEmployeeNumber && row.inspectorName !== row.inspectorEmployeeNumber">
                {{ row.inspectorEmployeeNumber }}
              </small>
              <small v-if="row.inspectorUsername && row.inspectorEmployeeNumber && row.inspectorUsername !== row.inspectorEmployeeNumber">
                登录账号 {{ row.inspectorUsername }}
              </small>
              <small v-else-if="!row.inspectorUsername && (row.inspectorName || row.inspectorEmployeeNumber)">
                未绑定登录账号
              </small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="分派时间" min-width="165">
          <template #default="{row}">{{ timestamp(row.assignedAt) }}</template>
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
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '../../components/AppIcon.vue'
import CollectionEmptyState from '../../components/CollectionEmptyState.vue'
import PageHero from '../../components/PageHero.vue'
import TableReadHint from '../../components/TableReadHint.vue'
import { useManagedList } from '../../composables/useManagedList'
import { useUserStore } from '../../stores/user'
import { beijingDateTime } from '../../utils/beijingTime'
import { knownCount } from '../../utils/countPresentation'

const route = useRoute(), router = useRouter(), user = useUserStore()
const isSupervisor = computed(() => user.role === 'SUPERVISOR')
const scope = computed(() => isSupervisor.value && route.query.scope === 'all' ? 'all' : 'mine')
const account = () => JSON.stringify([user.accountEpoch, user.accountContext, user.role, user.isAuthenticated])
const { records, total, loading, error, filters, pagination, search, refresh, retry, changePage } =
  useManagedList('/api/detection/historical-ledger', ['scope'], { scope: account, canRead: () => user.isAuthenticated })
pagination.size = 20

watch([scope, account], () => {
  filters.scope = scope.value
  void search()
}, { immediate:true })

function switchScope(next) {
  if (!isSupervisor.value || next === scope.value) return
  return router.replace({ name:'historicalDetectionLedger', query:{ scope:next === 'all' ? 'all' : undefined } })
}

const timestamp = value => beijingDateTime(value) || '—'
const count = value => knownCount(value)?.toLocaleString('zh-CN') ?? '—'
</script>

<style scoped>
.historical-ledger { min-width:0; }
.ledger-scope { display:flex; flex-wrap:wrap; gap:6px; }
.ledger-cell { display:grid; gap:3px; min-width:0; padding:4px 0; overflow-wrap:anywhere; }
.ledger-cell small { color:var(--app-text-secondary); }
</style>
