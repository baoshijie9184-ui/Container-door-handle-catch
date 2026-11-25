<template>
  <div class="page-shell reports-page">
    <PageHero class="report-page-heading" :title="approvalOnly ? '待我审批' : isSupervisor ? '报告与审批' : '我的质检报告'">
      <template #actions>
        <el-button type="primary" :disabled="busy" @click="openCreate"><AppIcon name="Plus" :size="16" />新建报告草稿</el-button>
      </template>
    </PageHero>
    <el-alert v-if="reportChanged" title="报告资料可能已更新，当前编辑已保留" type="warning" :closable="false">
      <router-link :to="reportHistory">查看修改记录</router-link>
      <el-button text @click="readLatestReport">核对最新资料</el-button>
    </el-alert>
    <section class="table-panel report-collection" aria-labelledby="report-list-heading">
      <div class="collection-heading">
        <h2 id="report-list-heading">报告记录</h2>
        <div class="report-list-meta">
          <span>{{ loading ? '正在读取…' : error ? '本次读取失败' : total===null ? '' : `共 ${total} 条` }}</span>
          <el-button text size="small" :loading="loading" :disabled="busy" @click="load()">
            <AppIcon name="Refresh" :size="15" />刷新
          </el-button>
        </div>
      </div>
      <p v-if="relatedTaskId" class="report-query-note">
        关联检测任务 {{ relatedTaskId }}
        <router-link :to="{path:'/inspection/history',query:{keyword:relatedTaskId}}">返回检测记录</router-link>
        · <router-link to="/quality/reports">查看全部报告</router-link>
      </p>
      <form class="report-toolbar" @submit.prevent="search">
        <div class="report-filter-field report-keyword-field">
          <label for="report-keyword" class="sr-only">报告标题或任务编号</label>
          <el-input id="report-keyword" v-model="keyword" aria-label="查询任务编号或报告标题" placeholder="报告标题或任务编号" maxlength="128" clearable />
        </div>
        <div v-if="!approvalOnly" class="report-filter-field report-state-field">
          <label for="report-status" class="sr-only">审批状态</label>
          <el-select id="report-status" v-model="status" aria-label="审批状态" placeholder="全部状态" clearable>
            <el-option v-for="(label, value) in states" :key="value" :label="label" :value="value" />
          </el-select>
        </div>
        <div class="report-search-actions">
          <el-button native-type="submit" :loading="loading"><AppIcon name="Search" :size="16" />查询</el-button>
          <el-button v-if="keyword.trim() || (!approvalOnly && status)" text @click="resetSearch">重置</el-button>
          <router-link v-if="approvalOnly && !emptyApprovalQueue" to="/quality/reports">查看全部报告</router-link>
        </div>
      </form>
      <p v-if="filtersDirty && records.length" class="report-query-note" role="status">点击查询应用筛选。</p>
      <p v-if="listLoaded" class="report-applied-query" :class="{ 'sr-only':!appliedQuery.keyword && !appliedQuery.status && appliedPage === 1 }">
        已读取范围：{{ !appliedQuery.keyword && !appliedQuery.status ? '全部报告' : '' }}{{ appliedQuery.keyword ? `关键词“${appliedQuery.keyword}”` : '' }}{{ appliedQuery.keyword && appliedQuery.status ? ' · ' : '' }}{{ appliedQuery.status ? states[appliedQuery.status] || '指定状态' : '' }}{{ appliedPage > 1 ? ` · 第 ${appliedPage} 页` : '' }}
      </p>
      <el-alert v-if="error && records.length" :title="error + '；下方保留先前读取的记录，请重新查询核对。'" type="error" show-icon :closable="false" />
      <TableReadHint v-if="records.length" id="report-table-scroll-hint" class="report-table-hint" />
      <el-table :scrollbar-tabindex="0" role="region" aria-label="质检报告记录" :aria-describedby="records.length ? 'report-table-scroll-hint' : undefined" :data="records" v-loading="loading" row-key="reportId">
        <template #empty>
          <CollectionEmptyState
            :loading="loading" :error="error"
            :filtered="!!(requestedQuery.keyword || (!approvalOnly && requestedQuery.status))"
            :empty-title="approvalOnly ? '暂无待你审批的报告' : relatedTaskId ? '该任务暂无可查看的报告' : '暂无质检报告'"
            :empty-description="approvalOnly ? '可以查看全部报告及其审批结果。' : '选用已完成的检测任务，可以新建并提交报告。'"
            @retry="retryList" @reset="resetSearch"
          >
            <template v-if="emptyApprovalQueue" #empty-action>
              <router-link to="/quality/reports" custom v-slot="{ href, navigate }">
                <el-button tag="a" :href="href" type="primary" size="small" @click="navigate">查看全部报告</el-button>
              </router-link>
            </template>
          </CollectionEmptyState>
        </template>
        <el-table-column label="报告与状态" min-width="265">
          <template #default="{ row }">
            <div class="report-list-identity">
              <button type="button" :disabled="busy" @click="openDetail(row.reportId)">{{ row.title || '未命名报告' }}</button>
              <div class="report-list-status">
                <StatusBadge domain="report" :code="row.status" :label="states[row.status]" />
                <small>版本 {{ knownCount(row.version) ?? '未记录' }}</small>
              </div>
              <span>编写账号 {{ row.ownerUsername || '未记录' }}</span>
              <details><summary>报告编号</summary><code>{{ row.reportId }}</code></details>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="依据任务" min-width="205"><template #default="{ row }"><router-link v-if="row.taskId" class="report-task-link" :to="{ path:'/inspection/history', query:{ keyword:row.taskId } }" :title="row.taskId">{{ row.taskId }}</router-link><span v-else>未记录</span></template></el-table-column>
        <el-table-column label="最近更新" min-width="175"><template #default="{ row }"><span class="report-list-time">{{ reportTime(row.updatedAt) }}</span></template></el-table-column>
        <el-table-column v-if="userStore.capabilities?.changeHistory" label="最近修改" min-width="205"><template #default="{row}"><ResourceMutationSummary :latest="latestChanges[String(row.reportId)]" :revision="row.version" resource-type="QUALITY_REPORT" :resource-id="row.reportId" domain="QUALITY_REPORT" /></template></el-table-column>
        <el-table-column label="操作" fixed="right" width="100"><template #default="{ row }"><el-button size="small" :disabled="busy" @click="openDetail(row.reportId)"><AppIcon name="Search" :size="16" />查看</el-button></template></el-table-column>
      </el-table>
      <div v-if="error && records.length" class="report-list-retry"><el-button size="small" :loading="loading" @click="retryList"><AppIcon name="Refresh" :size="15" />重试上次读取</el-button></div>
      <div v-if="total!==null && (total>20 || page>1)" class="page-footer"><el-pagination :current-page="page" :page-size="20" :total="total" layout="prev, pager, next" :disabled="loading || !!error" @current-change="loadAppliedPage" /></div>
    </section>

    <el-dialog v-model="editorVisible" class="report-scroll-dialog report-editor-dialog" :title="editingId ? '编辑个人草稿' : '新建报告草稿'" width="min(650px, 94vw)" append-to-body :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
      <p v-if="editingId" class="report-editor-version">草稿版本 {{ knownCount(editingVersion) ?? '未记录' }}</p>
      <el-form id="quality-report-editor-form" label-position="top" @submit.prevent="saveDraft">
        <section class="report-editor-section" aria-labelledby="report-editor-source-heading"><h3 id="report-editor-source-heading"><AppIcon name="Tickets" :size="18" />报告依据</h3>
        <el-form-item label="检测任务编号" required>
          <el-select
            v-if="!editingId"
            id="quality-report-task"
            v-model="form.taskId"
            filterable
            allow-create
            default-first-option
            clearable
            :loading="candidateTasksLoading"
            :disabled="busy"
            placeholder="选择近期已完成检测任务，或直接输入任务编号"
            style="width:100%"
            @change="clearEditorFieldError('taskId')"
          >
            <el-option
              v-for="item in candidateTasks"
              :key="item.taskId"
              :label="item.label"
              :value="item.taskId"
            />
          </el-select>
          <el-input v-else id="quality-report-task" v-model="form.taskId" aria-label="输入已完成检测任务编号"
            :disabled="true" maxlength="128" />
          <p v-if="editorFieldError?.field === 'taskId'" id="quality-report-task-error" class="report-field-error" role="alert">{{ editorFieldError.message }}</p>
        </el-form-item>
        <p id="report-editor-source-note" class="report-editor-help"><template v-if="editingId">此草稿关联的任务编号固定。</template><template v-else>可从<router-link :to="{path:'/inspection/history',query:form.taskId.trim()?{keyword:form.taskId.trim()}:{}}">检测记录</router-link>查找已完成任务。</template></p></section>
        <section class="report-editor-section" aria-labelledby="report-editor-content-heading"><h3 id="report-editor-content-heading"><AppIcon name="Edit" :size="18" />标题与意见</h3>
        <el-form-item label="报告标题" required>
          <el-input id="quality-report-title" v-model="form.title" aria-label="报告标题"
            :aria-invalid="editorFieldError?.field === 'title' || undefined"
            :aria-describedby="editorFieldError?.field === 'title' ? 'quality-report-title-error' : undefined"
            placeholder="为本版报告填写清晰标题" maxlength="120" show-word-limit :disabled="busy"
            @update:model-value="clearEditorFieldError('title')" />
          <p v-if="editorFieldError?.field === 'title'" id="quality-report-title-error" class="report-field-error" role="alert">{{ editorFieldError.message }}</p>
        </el-form-item>
        <el-form-item label="编写意见" required>
          <el-input id="quality-report-narrative" v-model="form.narrative" type="textarea" :rows="7" maxlength="10000" show-word-limit
            aria-label="记录复核说明、风险和建议，检测数量以系统依据为准"
            :aria-invalid="editorFieldError?.field === 'narrative' || undefined"
            :aria-describedby="editorFieldError?.field === 'narrative' ? 'quality-report-narrative-error' : undefined"
            placeholder="记录复核说明、风险和建议，检测数量以系统依据为准" :disabled="busy"
            @update:model-value="clearEditorFieldError('narrative')" />
          <p v-if="editorFieldError?.field === 'narrative'" id="quality-report-narrative-error" class="report-field-error" role="alert">{{ editorFieldError.message }}</p>
        </el-form-item></section>
      </el-form>
      <template #footer>
        <el-alert v-if="reportConflict" class="report-dialog-feedback" :title="editorError" type="warning" :closable="false">
          <el-button text @click="reloadDraft">核对最新报告版本</el-button>
        </el-alert>
        <el-alert v-else-if="editorError" class="report-dialog-feedback" :title="editorError" type="error" :closable="false" />
        <div class="report-dialog-actions">
          <el-button :disabled="busy" @click="editorVisible = false"><AppIcon name="Close" :size="16" />取消</el-button>
          <el-button type="primary" native-type="submit" form="quality-report-editor-form" :loading="busy" :disabled="reportConflict"><AppIcon name="DocumentChecked" :size="16" />保存草稿</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" class="report-scroll-dialog" title="报告详情" width="min(920px, 96vw)" append-to-body :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
      <div v-loading="detailLoading">
        <CollectionEmptyState v-if="!detail" :loading="detailLoading" :error="detailError" empty-title="报告资料尚未读取" empty-description="请重新读取当前报告，核对本版内容及操作记录。" @retry="openDetail(detailRequestedId)" />
        <template v-if="detail">
          <header class="report-detail-heading"><h2>{{ detail.title }}</h2><div><StatusBadge domain="report" :code="detail.status" :label="states[detail.status]" /><span class="report-version">版本 {{ detail.version }}</span></div></header>
          <el-alert v-if="detail.decisionReason" :title="`审批意见：${detail.decisionReason}`" :type="detail.status === 'APPROVED' ? 'success' : 'warning'" :closable="false" />
          <p v-if="detail.deciderUsername" class="muted">审批账号 {{ detail.deciderUsername }} · {{ reportTime(detail.decidedAt) }}</p>
          <dl class="report-identity-strip"><div><dt>编写账号</dt><dd>{{ detail.ownerUsername || '未记录' }}</dd></div><div><dt>依据任务</dt><dd>{{ detail.taskId || '未记录' }}</dd></div><div><dt>报告编号</dt><dd>{{ detail.reportId }}</dd></div></dl>
          <div class="report-next-step"><AppIcon name="DocumentChecked" :size="17" /><p>{{ reportNextStep }}</p></div>
          <p v-if="detail.previousReportId" class="muted">修订自报告 {{ detail.previousReportId }}</p>
          <h3>编写意见</h3>
          <p class="narrative">{{ detail.narrative || '未记录编写意见' }}</p>
          <details class="report-basis-section" :open="detail.status === 'SUBMITTED'">
            <summary>本版检测依据</summary>
            <ReportBasis :source="detail.source" />
            <ReportSnapshotIdentity :key="detail.reportId+':'+detail.version" :report="detail" />
          </details>
          <details v-if="!reportDeliveryDisabled || eventsError || events.length" class="report-delivery" aria-label="报告状态同步">
            <summary>
              <AppIcon name="Connection" :size="16" />审批状态同步
              <span v-if="reportDeliveryDisabled"> · 投递未启用</span>
              <span v-if="eventsError"> · 读取未完成</span>
              <span v-else-if="!reportDeliveryDisabled && events.some(item=>['FAILED','RETRY'].includes(item.deliveryStatus))"> · 有待核对的发送记录</span>
            </summary>
            <div class="detail-heading">
              <p class="muted" v-if="reportDeliveryDisabled">本站未启用报告事件投递。下方显示已保存的发送和接收记录。</p>
              <p class="muted" v-else>发送状态与已记录的审批决定分别显示；失败会按原机制重试，重新发送不会再次审批。</p>
              <el-button size="small" :disabled="busy" :loading="eventsLoading" @click="loadEvents(detail.reportId)"><AppIcon name="Refresh" :size="15" />刷新同步状态</el-button>
            </div>
            <el-alert v-if="eventsError" :title="eventsError" type="error" :closable="false" />
            <el-table :scrollbar-tabindex="0" role="region" aria-label="报告同步状态更新" v-else :data="events" v-loading="eventsLoading" empty-text="本报告暂无已读取的同步状态更新" max-height="240">
              <el-table-column label="状态更新" min-width="110"><template #default="{ row }">{{ eventLabel(row.eventType) }}</template></el-table-column>
              <el-table-column label="发送状态" min-width="140"><template #default="{ row }"><StatusBadge domain="reportDelivery" :code="row.deliveryStatus" :label="reportDeliveryLabel(row.deliveryStatus)" /></template></el-table-column>
              <el-table-column label="尝试次数" width="90"><template #default="{row}">{{ knownCount(row.attempts) ?? '—' }}</template></el-table-column>
              <el-table-column label="接收结果" min-width="210"><template #default="{ row }"><el-tag v-if="row.clockStatus==='UNRESOLVED'" size="small" type="info">历史时间需核对</el-tag><span v-else>{{ row.consumedAt ? '已接收 · '+reportTime(row.consumedAt) : reportDeliveryDisabled ? '未记录接收' : '等待接收确认' }}</span></template></el-table-column>
              <el-table-column v-if="isSupervisor && !reportDeliveryDisabled" label="操作" width="110"><template #default="{ row }"><el-button v-if="['FAILED','RETRY'].includes(row.deliveryStatus)" size="small" :disabled="busy||eventsLoading||row.clockStatus==='UNRESOLVED'" @click="retryEvent(row)">重新发送</el-button></template></el-table-column>
            </el-table>
          </details>
          <ResourceChangeHistory v-if="userStore.capabilities?.changeHistory === true" resource-type="QUALITY_REPORT" :resource-id="detail.reportId" domain="QUALITY_REPORT" compact />
          <h3><AppIcon name="DocumentCopy" :size="18" />操作记录<span class="report-section-count">本次读取 {{ audits.length }} 条</span></h3>
          <el-table class="report-audit-table" :scrollbar-tabindex="0" role="region" aria-label="报告操作记录" :data="audits" max-height="260"><el-table-column prop="actorUsername" label="操作账号" min-width="140" /><el-table-column label="操作" min-width="90"><template #default="{ row }">{{ auditLabels[row.action] || row.action }}</template></el-table-column><el-table-column prop="reportVersion" label="版本" width="65" /><el-table-column label="来源" min-width="150"><template #default="{ row }"><router-link v-if="row.runId" :to="{ path: '/agent/trace', query: { runId: row.runId } }">助手运行轨迹</router-link><span v-else>业务页面</span></template></el-table-column><el-table-column prop="reason" label="意见" min-width="160" /><el-table-column label="时间" min-width="190"><template #default="{ row }">{{ row.clockStatus==='UNRESOLVED' && !row.createdAt ? '历史时区未确认' : reportTime(row.createdAt) }}</template></el-table-column></el-table>
          <div class="report-audit-mobile" role="region" aria-label="报告操作记录，可聚焦后使用方向键滚动" tabindex="0">
            <p v-if="audits.length" class="report-audit-reading-hint">按本次返回顺序展示，可聚焦后用方向键上下滚动。</p>
            <ol v-if="audits.length">
              <li v-for="(row,index) in audits" :key="row.id ?? index">
                <header><strong><AppIcon :name="auditIcons[row.action] || 'Document'" :size="15" />{{ auditLabels[row.action] || row.action || '操作未记录' }}</strong><span>版本 {{ knownCount(row.reportVersion) ?? '未记录' }}</span></header>
                <dl><div><dt>操作账号</dt><dd>{{ row.actorUsername || '未记录' }}</dd></div><div><dt>时间</dt><dd>{{ row.clockStatus==='UNRESOLVED' && !row.createdAt ? '历史时区未确认' : reportTime(row.createdAt) }}</dd></div><div><dt>来源</dt><dd><router-link v-if="row.runId" :to="{path:'/agent/trace',query:{runId:row.runId}}">助手运行轨迹<AppIcon name="ArrowRight" :size="13" /></router-link><span v-else>业务页面</span></dd></div><div><dt>意见</dt><dd>{{ row.reason || '未记录意见' }}</dd></div></dl>
              </li>
            </ol>
            <p v-else>本次未返回报告操作记录</p>
          </div>
        </template>
      </div>
      <template #footer>
        <el-alert v-if="detailError && detail" class="report-dialog-feedback" :title="detailError" type="error" :closable="false" />
        <div class="report-dialog-actions">
          <el-button :disabled="busy" @click="detailVisible=false">关闭详情</el-button>
          <template v-if="detail">
            <template v-if="own && detail.status === 'DRAFT'"><el-button :disabled="busy" @click="openEdit"><AppIcon name="Edit" :size="15" />编辑草稿</el-button><el-button type="primary" :loading="busy" @click="openTransition('submit')"><AppIcon name="DocumentChecked" :size="15" />提交主管审批</el-button></template>
            <el-button v-if="own && detail.status === 'SUBMITTED'" :disabled="busy" @click="openTransition('withdraw')">撤回申请</el-button>
            <el-button v-if="own && ['APPROVED', 'REJECTED', 'WITHDRAWN'].includes(detail.status)" :loading="busy" :type="detail.status === 'REJECTED' ? 'primary' : 'default'" @click="runCommand('revise')">创建修订草稿</el-button>
            <template v-if="isSupervisor && !own && detail.status === 'SUBMITTED'"><el-button type="primary" :disabled="busy" @click="openDecision('APPROVE')">审批通过</el-button><el-button type="danger" plain :disabled="busy" @click="openDecision('REJECT')">驳回报告</el-button></template>
            <template v-if="detail.status === 'APPROVED'"><el-select v-model="exportFormat" :disabled="busy" aria-label="报告导出格式" style="width:130px"><el-option label="Word" value="docx" /><el-option label="PDF" value="pdf" /><el-option label="Excel" value="xlsx" /><el-option label="Markdown" value="md" /></el-select><el-button :loading="busy" @click="download"><AppIcon name="Download" :size="15" />导出已审批报告</el-button></template>
          </template>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="transitionVisible" class="report-scroll-dialog" :title="transition === 'submit' ? '提交主管审批' : '撤回报告申请'" width="min(480px, 94vw)" append-to-body :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
      <p>{{ transition === 'submit' ? '提交后本版本的意见和检测依据将冻结，主管审批的是这份内容。' : '撤回后保留本次提交快照和审计，可以创建修订草稿。' }}</p>
      <div v-if="detail" class="report-operation-context"><strong>{{ detail.title }}</strong><p>版本 {{ detail.version }} · 编写账号 {{ detail.ownerUsername }}</p><small>依据任务 {{ detail.taskId }}</small></div>
      <template #footer><el-alert v-if="transitionError" class="report-dialog-feedback" :title="transitionError" type="warning" show-icon :closable="false" /><el-button :disabled="busy" @click="transitionVisible = false"><AppIcon name="Close" :size="16" />取消</el-button><el-button type="primary" :loading="busy" @click="runCommand(transition)">确认{{ transition === 'submit' ? '提交' : '撤回' }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="decisionVisible" class="report-scroll-dialog" :title="decision === 'APPROVE' ? '报告审批通过' : '驳回报告'" width="min(700px, 94vw)" append-to-body :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
      <p class="report-dialog-note"><AppIcon name="Lock" :size="16" />先预览本次决定与报告版本，再明确确认。此操作不代替检测任务放行。</p>
      <el-form label-position="top"><el-form-item label="审批意见" required><el-input v-model="reason" type="textarea" :rows="3" maxlength="500" show-word-limit aria-label="填写本次审批依据与意见" placeholder="填写本次审批依据与意见" :disabled="busy || !!preview" /></el-form-item></el-form>
      <div v-if="preview" class="approval-preview">
        <h3>确认审批内容</h3><p>{{ preview.report.title }} · 版本 {{ preview.report.version }}</p>
        <p>依据任务 {{ preview.report.taskId }} · 编写账号 {{ preview.report.ownerUsername }}</p>
        <ReportBasis :source="preview.report.source" />
        <ReportSnapshotIdentity :key="preview.report.reportId+':'+preview.report.version" :report="preview.report" />
        <p class="narrative">{{ preview.report.narrative }}</p>
        <p>决定：{{ decision === 'APPROVE' ? '审批通过' : '驳回' }} · {{ preview.reason }}</p>
        <p class="muted">审批记录将引用此快照，确认有效至 {{ reportTime(preview.expiresAt) }}</p>
      </div>
      <template #footer><el-alert v-if="decisionError" class="report-dialog-feedback" :title="decisionError" type="error" :closable="false" /><el-button :disabled="busy" @click="decisionVisible = false"><AppIcon name="Close" :size="16" />取消</el-button><el-button v-if="preview" :disabled="busy" @click="preview = null">修改意见</el-button><el-button v-if="!preview" :type="decision === 'APPROVE' ? 'primary' : 'danger'" :loading="busy" @click="prepareDecision">预览审批操作</el-button><el-button v-else :type="decision === 'APPROVE' ? 'primary' : 'danger'" :loading="busy" @click="confirmDecision">确认{{ decision === 'APPROVE' ? '审批通过' : '驳回报告' }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import ResourceChangeHistory from '../components/ResourceChangeHistory.vue'
import ResourceMutationSummary from '../components/ResourceMutationSummary.vue'
import { useLatestChanges } from '../composables/useLatestChanges'
import { resourceHistoryLink } from '../utils/changeHistory'
import { useResourceChanges } from '../composables/useResourceChanges'
import { ref, shallowRef, reactive, computed, nextTick, watch, onBeforeUnmount, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { captureAccountRequest } from '../api/request'
const request=captureAccountRequest()
import { useUserStore } from '../stores/user'
import { beijingDateTime } from '../utils/beijingTime'
import CollectionEmptyState from '../components/CollectionEmptyState.vue'
import ReportBasis from '../components/ReportBasis.vue'
import ReportSnapshotIdentity from '../components/ReportSnapshotIdentity.vue'
import { knownCount } from '../utils/countPresentation'

const reportTime = value => value ? beijingDateTime(value) || '时间格式未知' : '未记录'
const exportFormat = ref('md')
const route = useRoute(), userStore = useUserStore()
const states = { DRAFT: '个人草稿', SUBMITTED: '待审批', APPROVED: '审批通过', REJECTED: '已驳回', WITHDRAWN: '已撤回' }
const auditLabels = { CREATE: '创建草稿', EDIT: '保存草稿', SUBMIT: '提交审批', WITHDRAW: '撤回', REVISE: '创建修订', APPROVE: '审批通过', REJECT: '驳回', EXPORT: '导出', EVENT_RETRY: '重新发送状态' }
const auditIcons = { APPROVE:'CircleCheck', REJECT:'CircleClose', EXPORT:'Download', EDIT:'Edit', SUBMIT:'DocumentChecked', WITHDRAW:'RefreshLeft', REVISE:'DocumentCopy', EVENT_RETRY:'Refresh' }
const records = ref([]), status = ref(''), keyword = ref(''), page = ref(1), total = ref(null), loading = ref(false), error = ref('')
const { latest:latestChanges } = useLatestChanges(records,'QUALITY_REPORT','QUALITY_REPORT','reportId')
const appliedQuery = reactive({ keyword:'', status:'' })
const requestedQuery = reactive({ keyword:'', status:'', page:1 })
const listLoaded = ref(false), appliedPage = ref(1)
const filtersDirty = computed(() => keyword.value.trim()!==appliedQuery.keyword || (status.value||'')!==appliedQuery.status)
const busy = ref(false), detail = ref(null), detailVisible = ref(false), detailLoading = ref(false), detailError = ref(''), audits = ref([])
const events=ref([]),eventsError=ref(''),eventsLoading=ref(false)
const detailRequestedId=ref(''),transitionError=ref('')
const eventLabel=value=>({submitted:'提交审批',withdrawn:'撤回申请',approved:'审批通过',rejected:'驳回报告'}[value?.split('.')[2]]||'报告状态更新')
const reportConflict=ref(false)
const editorVisible = ref(false), editingId = ref(''), editingVersion = ref(null), editorError = ref('')
const editorFieldError = shallowRef(null)
const draftFields = {
  taskId: { id:'quality-report-task', required:'请填写检测任务编号' },
  title: { id:'quality-report-title', required:'请填写报告标题' },
  narrative: { id:'quality-report-narrative', required:'请填写编写意见' }
}
const draftSourceErrors = new Set([
  '任务编号不正确', '任务不存在或无访问权限', '只有已完成或部分失败的检测任务可以编写报告'
])
const draftVersionErrors = new Set(['报告版本已更新，请刷新后重试', '当前报告状态不允许此操作'])
const form = reactive({ taskId: '', title: '', narrative: '' })
const transitionVisible = ref(false), transition = ref('submit')
const decisionVisible = ref(false), decision = ref('APPROVE'), reason = ref(''), preview = ref(null), decisionError = ref('')
const isSupervisor = computed(() => userStore.role === 'SUPERVISOR')
const reportDeliveryDisabled = computed(() => userStore.capabilities?.reportEventDelivery === false)
function reportDeliveryLabel(status) {
  if (!reportDeliveryDisabled.value) return undefined
  if (['PENDING', 'PROCESSING', 'RETRY'].includes(status)) return '投递未启用'
  if (status === 'FAILED') return '发送失败'
}
const own = computed(() => detail.value?.ownerUserId != null && String(detail.value.ownerUserId) === String(userStore.identity?.userId))
const approvalOnly = computed(() => isSupervisor.value && route.query.awaitingMyApproval === '1')
const relatedTaskId = computed(() => typeof route.query.relatedTaskId === 'string' ? route.query.relatedTaskId : '')
const emptyApprovalQueue = computed(() => approvalOnly.value && listLoaded.value && total.value === 0
  && !records.value.length && !requestedQuery.keyword && !loading.value && !error.value)
const reportNextStep = computed(() => {
  const state = detail.value?.status
  if (state === 'DRAFT') return own.value ? '核对编写意见和检测依据后，可提交主管审批。' : '报告尚为草稿，需编写人提交后才能进入审批。'
  if (state === 'SUBMITTED') return own.value ? (isSupervisor.value ? '由其他主管审批。如需修改，先撤回申请。' : '需要修改时，先撤回申请，再创建修订草稿。') : isSupervisor.value ? '核对检测依据和编写意见，再填写审批决定。' : '等待主管审批。'
  if (state === 'APPROVED') return own.value ? '可导出当前版本，或创建修订草稿。' : '可导出当前版本。任务处置在检测记录中查看。'
  if (state === 'REJECTED') return '编写人可根据审批意见创建修订草稿。'
  if (state === 'WITHDRAWN') return '编写人可创建修订草稿。'
  return '报告状态尚未确认，请重新读取后核对可用操作。'
})
const headers = { 'X-Report-Action': 'update' }
const keys = new Map()
let loadGeneration = 0, detailGeneration = 0
const message = e => e.response?.data?.message || e.message || '操作失败，请刷新核对状态'
function unwrap(response) { if (response.data?.code !== 200) throw new Error(response.data?.message || '请求失败'); return response.data.data }
function reportRows(value, label) {
  if (!Array.isArray(value) || value.some(row => !row || typeof row !== 'object' || Array.isArray(row))) throw new Error(`${label}尚未完整读取`)
  return value
}
function withId(operation, payload) {
  const key = JSON.stringify([operation, payload])
  if (!keys.has(key)) keys.set(key, crypto.randomUUID())
  return { ...payload, requestId: keys.get(key) }
}
async function load(queryOverride) {
  const generation = ++loadGeneration; loading.value = true; error.value = ''
  const source = queryOverride && typeof queryOverride === 'object' ? queryOverride : listLoaded.value ? { ...appliedQuery, page:appliedPage.value } : requestedQuery
  const query={keyword:source.keyword || '',status:approvalOnly.value ? 'SUBMITTED' : source.status || ''}, requestedPage=source.page ?? page.value
  Object.assign(requestedQuery,query,{page:requestedPage})
  try { const data = unwrap(await request.get('/api/detection/reports', { params: { page: requestedPage, size: 20, status: query.status || undefined, keyword: query.keyword || undefined, relatedTaskId:relatedTaskId.value || undefined, awaitingMyApproval: approvalOnly.value || undefined } })); if (generation === loadGeneration) { if(!Array.isArray(data?.records)||data.records.some(row=>!row||typeof row.reportId!=='string')||knownCount(data.total)===null)throw Error('报告列表或数量尚未完整读取');records.value = data.records; total.value = knownCount(data.total);Object.assign(appliedQuery,query);appliedPage.value=requestedPage;page.value=requestedPage;listLoaded.value=true } }
  catch (e) { if (generation === loadGeneration) { if([401,403].includes(e.response?.status)){records.value=[];total.value=null;listLoaded.value=false}error.value = message(e) } }
  finally { if (generation === loadGeneration) loading.value = false }
}
function search() { load({ keyword:keyword.value.trim(), status:status.value || '', page:1 }) }
function loadAppliedPage(nextPage) { load({ ...appliedQuery, page:nextPage }) }
function retryList() { load({ ...requestedQuery }) }
function resetSearch() { keyword.value = ''; status.value = approvalOnly.value ? 'SUBMITTED' : ''; search() }
const candidateTasks = ref([]), candidateTasksLoading = ref(false)
async function loadCandidateTasks() {
  candidateTasksLoading.value = true
  try {
    const res = await request.get('/api/detection/board', { params: { page: 1, size: 20 } })
    const rows = res.data?.data?.records || res.data?.data?.items || (Array.isArray(res.data?.data) ? res.data.data : [])
    candidateTasks.value = rows
      .filter(r => r && (r.taskId || r.id) && ['COMPLETED', 'PARTIAL_FAILED', 'SUCCESS', 'DONE', 'VERIFIED', 'REVIEWED'].includes(String(r.modelStatus || r.status || r.detectionStatus || r.taskStatus || '').toUpperCase()))
      .map(r => {
        const id = String(r.taskId || r.id)
        const name = r.folderName || r.batchName || r.batchCode || r.workOrderNo || ''
        return { taskId: id, label: name ? `${name} (${id})` : id }
      })
  } catch {
    candidateTasks.value = []
  } finally {
    candidateTasksLoading.value = false
  }
}
function openCreate() { reportConflict.value=false; keys.clear(); editingId.value = ''; editingVersion.value = null; form.taskId = String(route.query.taskId || relatedTaskId.value); form.title = ''; form.narrative = ''; editorError.value = ''; editorFieldError.value = null; editorVisible.value = true; void loadCandidateTasks() }
function openEdit() { reportConflict.value=false; keys.clear(); editingId.value = detail.value.reportId; editingVersion.value = detail.value.version; Object.assign(form, { taskId: detail.value.taskId, title: detail.value.title, narrative: detail.value.narrative }); editorError.value = ''; editorFieldError.value = null; editorVisible.value = true }
function clearEditorFieldError(field) {
  if (editorFieldError.value?.field === field) editorFieldError.value = null
}
async function markEditorField(field, text) {
  const fieldError = { field, message:text }
  editorFieldError.value = fieldError
  await nextTick()
  if (!editorVisible.value || editorFieldError.value !== fieldError) return
  const input = document.getElementById(draftFields[field].id)
  input?.closest('.el-form-item')?.scrollIntoView({ block:'center' })
  input?.focus({ preventScroll:true })
}
async function saveDraft() {
  if (busy.value || reportConflict.value) return
  editorError.value = ''
  const incomplete = Object.keys(draftFields).find(field => !form[field].trim())
  if (incomplete) return markEditorField(incomplete, draftFields[incomplete].required)
  busy.value = true
  editorFieldError.value = null
  try {
    const payload = editingId.value ? withId(`edit:${editingId.value}`, { expectedVersion: editingVersion.value, title: form.title.trim(), narrative: form.narrative }) : withId('create', { taskId: form.taskId.trim(), title: form.title.trim(), narrative: form.narrative })
    const saved = unwrap(editingId.value ? await request.put(`/api/detection/reports/${editingId.value}`, payload, { headers }) : await request.post('/api/detection/reports', payload, { headers }))
    editorVisible.value = false; ElMessage.success('报告草稿已保存'); await load(); await openDetail(saved.reportId)
  } catch (e) {
    busy.value = false
    const failure = message(e)
    if (!editingId.value && draftSourceErrors.has(failure)) await markEditorField('taskId', failure)
    else {
      editorError.value = failure
      reportConflict.value = !!editingId.value && e.response?.status === 409 && draftVersionErrors.has(failure)
    }
  } finally { busy.value = false }
}
async function openDetail(id) {
  detailRequestedId.value=id
  const generation = ++detailGeneration; detailVisible.value = true; detailLoading.value = true; detailError.value = ''; detail.value = null; audits.value = [];events.value=[];eventsError.value=''
  try {
    const [report, audit] = await Promise.all([request.get(`/api/detection/reports/${id}`), request.get(`/api/detection/reports/${id}/audit`)])
    if (generation !== detailGeneration) return
    const reportData = unwrap(report), auditData = unwrap(audit)
    if (reportData?.reportId !== id) throw new Error('报告编号与当前选择不一致，请重新核对')
    const rows = reportRows(auditData, '报告操作记录')
    detail.value = reportData; audits.value = rows; loadEvents(id)
  }
  catch (e) { if (generation === detailGeneration) detailError.value = message(e) }
  finally { if (generation === detailGeneration) detailLoading.value = false }
}
async function loadEvents(id){
  const generation=detailGeneration;eventsLoading.value=true;eventsError.value=''
  try{const result=unwrap(await request.get(`/api/detection/reports/${id}/events`));if(generation===detailGeneration)events.value=reportRows(result,'报告同步记录')}
  catch(e){if(generation===detailGeneration){events.value=[];eventsError.value=message(e)}}finally{if(generation===detailGeneration)eventsLoading.value=false}
}
async function retryEvent(event){
  if(reportDeliveryDisabled.value||busy.value||!detail.value)return
  const generation=detailGeneration,id=detail.value.reportId;busy.value=true
  try{
    try{await ElMessageBox.confirm(`重新发送“${eventLabel(event.eventType)}”状态更新 不会重新执行审批`,'重新发送报告状态',{confirmButtonText:'确认重新发送',cancelButtonText:'取消'})}catch{return}
    if(reportDeliveryDisabled.value||generation!==detailGeneration)return
    const payload=withId(`retry-event:${event.eventId}`,{expectedAttempts:event.attempts,confirmed:true})
    const result=unwrap(await request.post(`/api/detection/reports/${id}/events/${event.eventId}/retry`,payload,{headers}));if(generation!==detailGeneration)return;events.value=reportRows(result,'报告同步记录')
    const auditResult=unwrap(await request.get(`/api/detection/reports/${id}/audit`))
    if(generation===detailGeneration){audits.value=reportRows(auditResult,'报告操作记录');ElMessage.success('已安排重新发送')}
  }catch(e){if(generation===detailGeneration){await loadEvents(id);eventsError.value=message(e)}}finally{busy.value=false}
}
function openTransition(action) { transition.value = action; transitionError.value=''; transitionVisible.value = true }
async function runCommand(action) {
  if (busy.value || !detail.value) return
  busy.value = true; detailError.value = '';transitionError.value=''
  try { const id = detail.value.reportId; const saved = unwrap(await request.post(`/api/detection/reports/${id}/${action}`, withId(`${action}:${id}`, { expectedVersion: detail.value.version }), { headers })); transitionVisible.value = false; await load(); await openDetail(saved.reportId); ElMessage.success('报告状态已更新') }
  catch (e) { if(transitionVisible.value)transitionError.value=message(e)+'；请核对当前报告状态，不会自动重发';else detailError.value = message(e) }
  finally { busy.value = false }
}
function openDecision(action) { decision.value = action; reason.value = ''; preview.value = null; decisionError.value = ''; decisionVisible.value = true }
async function prepareDecision() {
  if (busy.value || !detail.value) return
  if (!reason.value.trim()) {
    decisionError.value = '请填写审批意见'
    return
  }
  busy.value = true; decisionError.value = ''
  try { preview.value = unwrap(await request.post(`/api/detection/reports/${detail.value.reportId}/decision-preview`, { expectedVersion: detail.value.version, decision: decision.value, reason: reason.value.trim() }, { headers })) }
  catch (e) { decisionError.value = message(e) }
  finally { busy.value = false }
}
async function confirmDecision() {
  if (busy.value || !preview.value) return
  busy.value = true; decisionError.value = ''
  try {
    const p = preview.value; const saved = unwrap(await request.post(`/api/detection/reports/${p.report.reportId}/decision`, withId(`decide:${p.report.reportId}`, { expectedVersion: p.report.version, decision: p.decision, reason: p.reason, confirmationToken: p.confirmationToken }), { headers }))
    decisionVisible.value = false; preview.value = null; await load(); await openDetail(saved.reportId); ElMessage.success('审批决定已记录')
  } catch (e) { decisionError.value = message(e) }
  finally { busy.value = false }
}
async function download() {
  if (busy.value || !detail.value) return
  busy.value = true; detailError.value = ''
  try {
    const format=exportFormat.value, id=detail.value.reportId
    const response = await request.post(`/api/detection/reports/${id}/export`, null, { headers, params:{format}, responseType: 'blob' })
    const expected={md:'text/markdown',pdf:'application/pdf',docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',xlsx:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}[format]
    if (!(response.headers['content-type'] || '').startsWith(expected)) throw new Error('报告导出失败，请刷新核对状态')
    const url = URL.createObjectURL(response.data), link = document.createElement('a'); link.href = url; link.download = `${id}.${format}`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
    await openDetail(detail.value.reportId)
  } catch (e) { detailError.value = message(e) }
  finally { busy.value = false }
}
const {changed:reportChanged}=useResourceChanges({domains:['QUALITY_REPORT','DETECTION'],isEditing:()=>busy.value||editorVisible.value||decisionVisible.value||transitionVisible.value,refresh:()=>load()})
const reportHistory=computed(()=>resourceHistoryLink('QUALITY_REPORT',editingId.value||detail.value?.reportId,'QUALITY_REPORT'))
async function readLatestReport(){
 if(editorVisible.value||decisionVisible.value||transitionVisible.value){ElMessage.info('未提交内容已保留 请先完成或关闭编辑，再核对最新资料');return}
 await load();if(detailVisible.value&&detail.value?.reportId)await openDetail(detail.value.reportId);reportChanged.value=false
}
async function reloadDraft(){
 try{await ElMessageBox.confirm('加载新版本会替换当前未保存标题与意见。需要保留时请先复制草稿。','重新加载报告',{type:'warning',confirmButtonText:'加载最新版本',cancelButtonText:'保留草稿'})}catch{return}
 const id=editingId.value;await openDetail(id);if(detail.value?.reportId===id&&detail.value.status==='DRAFT'){openEdit();reportChanged.value=false}
}
function loadRouteFilter() {
  status.value = approvalOnly.value ? 'SUBMITTED' : Object.hasOwn(states,route.query.status) ? route.query.status : ''
  keyword.value = ''
  return load({ status:status.value, keyword:'', page:1 })
}
watch([()=>route.query.status, approvalOnly, relatedTaskId], ([,,nextTask], [,,previousTask]) => {
  if (nextTask !== previousTask) {
    records.value = []
    total.value = null
    listLoaded.value = false
  }
  void loadRouteFilter()
})
onMounted(async () => { if (!userStore.identity) await userStore.checkAuth(); await loadRouteFilter(); if (route.query.reportId) await openDetail(String(route.query.reportId)); else if (route.query.taskId) openCreate() })
onBeforeUnmount(()=>{detailGeneration++;loadGeneration++;events.value=[];eventsError.value='';keys.clear()})
</script>

<style scoped>
#app .reports-page { gap:16px; }
.report-page-heading { align-items:center; }
.report-page-heading :deep(.ui-page-symbol) { display:none; }
.report-collection > .collection-heading { padding:15px 20px 0; border:0; }
.report-list-meta { display:flex; align-items:center; gap:6px; color:var(--app-text-secondary); font-size:12px; }
.report-list-meta .el-button { color:var(--app-text-secondary); }
.report-toolbar { display:flex; flex-wrap:wrap; align-items:center; padding:12px 20px 16px; }
.report-filter-field { min-width:0; }
.report-keyword-field { width:min(100%,270px); }
.report-state-field { width:154px; }
.report-search-actions { display:flex; align-items:center; flex-wrap:wrap; gap:6px 10px; }
.report-search-actions .el-button + .el-button { margin-left:0; }
.report-search-actions a { color:var(--app-primary); font-size:13px; text-underline-offset:3px; }
.report-applied-query,.report-query-note { margin:0 20px 12px; color:var(--app-text-secondary); font-size:12px; line-height:1.7; overflow-wrap:anywhere; }
.report-collection > .page-footer { padding:10px 0; }
.report-scroll-dialog h3 { display:flex; align-items:center; gap:8px; margin-top:20px; color:var(--app-text); font-size:16px; }
.report-scroll-dialog h3 .el-icon { color:var(--app-primary); }
.detail-heading { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:10px; }
.report-list-identity { display:grid; justify-items:start; gap:6px; padding:6px 0; min-width:0; }
.report-list-identity > button { max-width:100%; padding:0; border:0; background:none; color:var(--app-text); font:inherit; font-size:14px; font-weight:600; text-align:left; line-height:1.65; overflow-wrap:anywhere; cursor:pointer; transition:color 160ms ease; }
.report-list-identity > button:hover { color:var(--app-primary); }
.report-list-identity > button:disabled { color:var(--app-text-secondary); cursor:wait; }
.report-list-identity > span,.report-list-identity details { max-width:100%; color:var(--app-text-secondary); font-size:12px; line-height:1.7; }
.report-list-identity summary { width:fit-content; cursor:pointer; }
.report-list-identity code { display:block; padding-top:5px; font-size:12px; overflow-wrap:anywhere; }
.report-list-status { display:flex; align-items:center; flex-wrap:wrap; gap:4px 8px; }
.report-list-status small { color:var(--app-text-secondary); font-size:12px; }
.report-list-time { color:var(--app-text-secondary); font-size:12px; font-variant-numeric:tabular-nums; }
.report-task-link { color:var(--app-primary); text-decoration:underline; text-underline-offset:3px; font-size:12px; overflow-wrap:anywhere; }
.report-list-retry { margin-top:14px; }
:is(.report-list-identity button,.report-list-identity summary,.report-task-link,.report-delivery summary):focus-visible { outline:2px solid var(--app-primary); outline-offset:4px; border-radius:3px; }
.report-dialog-note { display:flex; align-items:flex-start; gap:8px; margin:0 0 20px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.report-dialog-note .el-icon { flex:0 0 auto; margin-top:3px; color:var(--app-primary); }
.report-editor-version { margin:0 0 18px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.report-editor-section { padding:12px 0 4px; }
.report-editor-section + .report-editor-section { border-top:1px solid var(--app-border); }
.report-editor-section h3 { margin:0 0 18px; color:var(--app-text); font-size:14px; font-weight:600; line-height:1.8; }
.report-editor-help { margin:-4px 0 18px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; overflow-wrap:anywhere; }
.report-editor-help a { color:var(--app-primary); text-underline-offset:3px; }
.report-dialog-actions { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:8px; width:100%; }
.report-dialog-actions .el-button + .el-button { margin-left:0; }
.report-field-error { width:100%; margin:4px 0 0; color:var(--app-danger); font-size:12px; line-height:1.6; overflow-wrap:anywhere; }
.report-dialog-feedback { flex:0 0 100%; text-align:left; overflow-wrap:anywhere; }
.report-section-count { margin-left:auto; color:var(--app-text-secondary); font-size:12px; font-weight:400; }
.report-detail-heading { display:grid; gap:12px; margin:0 0 18px; min-width:0; }
.report-detail-heading h2 { margin:0; color:var(--app-text); font-size:19px; font-weight:650; line-height:1.7; overflow-wrap:anywhere; }
.report-detail-heading > div { display:flex; align-items:center; flex-wrap:wrap; gap:10px 16px; }
.report-detail-heading .report-version { color:var(--app-text-secondary); font-size:12px; font-variant-numeric:tabular-nums; }
.report-audit-mobile { display:none; min-width:0; max-height:360px; max-height:min(360px,50dvh); overflow:auto; overscroll-behavior:contain; scrollbar-gutter:stable; }
.report-audit-mobile ol { list-style:none; padding:0; margin:0; }
.report-audit-reading-hint { margin:0 0 12px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.report-audit-mobile li { padding:16px 0; border-top:1px solid var(--app-border); }
.report-audit-mobile li:first-child { padding-top:6px; border-top:0; }
.report-audit-mobile li > header { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px; }
.report-audit-mobile li > header strong { display:inline-flex; align-items:center; gap:6px; color:var(--app-text); font-size:13px; font-weight:600; }
.report-audit-mobile li > header .el-icon { color:var(--app-primary); }
.report-audit-mobile li > header > span { color:var(--app-text-secondary); font-size:12px; }
.report-audit-mobile dl { display:grid; gap:10px; margin:12px 0 0; }
.report-audit-mobile dl > div { min-width:0; }
.report-audit-mobile dt { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.report-audit-mobile dd { margin:3px 0 0; color:var(--app-text); font-size:13px; line-height:1.85; white-space:pre-wrap; overflow-wrap:anywhere; }
.report-audit-mobile a { display:inline-flex; align-items:center; gap:5px; color:var(--app-primary); text-underline-offset:3px; }
.report-audit-mobile a:hover { text-decoration:underline; }
.report-audit-mobile:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
.report-identity-strip { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.5fr) minmax(0,1.5fr); gap:16px; margin:18px 0; }
.report-identity-strip dt { font-size:12px; line-height:1.8; color:var(--app-text-secondary); }
.report-identity-strip dd { margin:5px 0 0; color:var(--app-text); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.report-next-step { display:flex; gap:9px; align-items:flex-start; padding:12px 14px; border-radius:8px; background:var(--app-primary-soft); color:var(--app-text-secondary); }
.report-next-step > .el-icon { color:var(--app-primary); margin-top:3px; flex:0 0 auto; }
.report-next-step p { margin:0; font-size:12px; line-height:1.85; }
.report-basis-section,.report-delivery { margin-top:16px; padding:12px 0; border-top:1px solid var(--app-border); }
.report-basis-section > summary,.report-delivery > summary { width:fit-content; max-width:100%; cursor:pointer; line-height:1.75; }
.report-basis-section > summary { color:var(--app-text); font-size:14px; font-weight:600; }
.report-delivery summary { color:var(--app-text-secondary); font-size:12px; }
.report-delivery summary .el-icon { margin-right:6px; vertical-align:middle; color:var(--app-primary); }
.report-delivery summary span { color:var(--app-warning); }
.report-operation-context { padding:14px 16px; margin:16px 0; border:1px solid var(--app-border); border-radius:8px; background:var(--app-primary-light); overflow-wrap:anywhere; }
.report-operation-context strong { color:var(--app-text); font-size:14px; line-height:1.8; }
.report-operation-context :is(p,small) { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
@media(max-width:640px) {
  #app .reports-page { gap:12px; }
  .report-page-heading { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; }
  .report-page-heading :deep(.page-hero-title) { font-size:20px; letter-spacing:0; }
  .report-page-heading :deep(.panel-actions) { margin:0; justify-content:flex-end; }
  .report-page-heading :deep(.panel-actions .el-button) { padding-inline:9px; }
  .report-collection > .collection-heading { padding:12px 14px 0; }
  #app .reports-page .report-toolbar { display:grid; grid-template-columns:minmax(0,1fr) auto; padding:10px 14px 12px; }
  .report-collection :deep(.el-table__empty-text) { width:min(100%,440px); }
  .report-keyword-field { grid-column:1/-1; width:100%; }
  .report-state-field { width:100%; }
  .report-search-actions { grid-column:2; justify-content:flex-end; }
  .report-applied-query,.report-query-note { margin-inline:14px; }
  .report-table-hint { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); white-space:nowrap; }
  .report-audit-mobile { display:block; }
  .report-audit-table { display:none; }
  .report-detail-heading h2 { font-size:16px; }
  .report-identity-strip { gap:8px; grid-template-columns:minmax(0,1fr); }
}
.source-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }.source-grid div { display: flex; flex-direction: column; gap: 6px; }
.source-grid span, .muted { font-size: 13px; color: #64748b; }.source-grid strong { font-weight: 500; overflow-wrap: anywhere; }
.narrative { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }
.approval-preview { border:0; border-top:2px solid var(--app-border-focus); padding:16px 0; border-radius:0; background:white; }
.approval-preview > h3 { margin:0 0 12px; font-size:16px; }
.approval-preview > p { color:var(--app-text-secondary); font-size:13px; line-height:1.85; overflow-wrap:anywhere; }
.el-button { transition: transform 160ms ease; }.el-button:active { transform: scale(.98); }
@media (prefers-reduced-motion: reduce) { .el-button,.report-list-identity > button { transition: none; }.el-button:active { transform: none; } }
</style>

<style>
.report-scroll-dialog.el-dialog { display:flex; flex-direction:column; margin-top:5vh; margin-bottom:5vh; max-height:90vh; max-height:90dvh; }
.report-scroll-dialog :is(.el-dialog__header,.el-dialog__footer) { flex-shrink:0; }
.report-scroll-dialog .el-dialog__title { display:block; padding-right:28px; font-size:17px; line-height:1.75; overflow-wrap:anywhere; }
.report-scroll-dialog .el-dialog__body { min-height:0; max-height:65vh; max-height:65dvh; overflow:auto; overscroll-behavior:contain; }
.report-scroll-dialog .el-dialog__footer { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:8px; }
.report-scroll-dialog .el-dialog__footer .el-button + .el-button { margin-left:0; }
.report-scroll-dialog :is(a,summary):focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; border-radius:3px; }
</style>
