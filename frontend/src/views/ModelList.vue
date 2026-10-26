<template>
  <div class="page-shell model-page">
    <PageHero title="检测模型管理" description="核对模型版本、基础校验和已登记的效果指标，模型发布与默认选择分别管理。">
      <template #actions>
        <el-button :loading="loading" @click="fetchModelList"><AppIcon name="Refresh" :size="16" />刷新已查范围</el-button>
        <ModelFileJournal />
        <el-button v-if="isSupervisor" type="primary" :disabled="mutationBusy" @click="handleUpload"><AppIcon name="Upload" :size="16" />上传模型</el-button>
      </template>
    </PageHero>

    <p class="management-scope-note"><AppIcon name="Tickets" :size="16" /><span>这里维护图片检测模型，基础校验、评估资料、发布和默认选择分别记录。对话 LLM 使用独立配置。</span></p>
    <section class="toolbar-panel app-panel">
      <form class="management-filter-form model-filter-form" @submit.prevent="handleSearch">
        <label for="detection-model-filter-id">模型 ID<el-input id="detection-model-filter-id" v-model="searchForm.modelId" placeholder="正整数编号" inputmode="numeric" clearable /></label>
        <label for="detection-model-filter-name">模型名称<el-input id="detection-model-filter-name" v-model="searchForm.modelName" placeholder="按登记名称查询" clearable /></label>
        <label for="detection-model-filter-version">版本号<el-input id="detection-model-filter-version" v-model="searchForm.version" placeholder="按登记版本查询" clearable /></label>
        <label for="detection-model-filter-status">发布状态<el-select id="detection-model-filter-status" v-model="searchForm.status" placeholder="全部状态" clearable><el-option v-for="(label,code) in statusLabelMap" :key="code" :label="label" :value="code" /></el-select></label>
        <div class="management-filter-actions"><el-button type="primary" native-type="submit" :loading="loading"><AppIcon name="Search" :size="16" />查询</el-button><el-button @click="resetSearch"><AppIcon name="Refresh" :size="16" />重置</el-button></div>
      </form>
      <el-alert v-if="filterError" :title="filterError" type="warning" show-icon :closable="false" />
    </section>
    <el-alert v-if="modelCommandError" :title="modelCommandError" :type="modelCommandUncertain ? 'warning' : 'error'" show-icon :closable="false" />
    <p v-if="lifecyclePending" class="model-list-note" role="status"><AppIcon name="Connection" :size="15" />正在等待模型管理操作回执，完成后核对列表和日志。</p>

    <section v-if="defaultModel && !loading && !listError" class="default-model-banner">
      <div>
        <div class="default-model-label">当前列表中的默认模型</div>
        <div class="default-model-name">
          {{ defaultModel.modelName }}
          <span class="default-model-version">版本 {{ defaultModel.version||'未记录' }}</span>
        </div>
      </div>
      <div class="default-model-meta">
        <StatusBadge domain="model" :code="defaultModel.status" />
        <span>使用次数 {{ modelUsage(defaultModel.usageCount) }}</span>
        <span>最近使用 {{ formatDateTime(defaultModel.lastUsedAt) }} · UTC+8</span>
      </div>
    </section>

    <!-- 统计摘要 -->
    <section v-if="!loading && !listError && total > 0" class="stats-bar">
      <div class="stats-bar-item">
        <div class="stats-bar-icon primary">
          <AppIcon name="Tickets" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ total }}</div>
          <div class="stats-bar-label">匹配模型数</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon success">
          <AppIcon name="CircleCheck" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ publishedCount }}</div>
          <div class="stats-bar-label">本页已发布</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon warning">
          <AppIcon name="DataAnalysis" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ totalUsageCount??'—' }}</div>
          <div class="stats-bar-label">本页使用次数</div>
        </div>
      </div>
      <div class="stats-bar-item">
        <div class="stats-bar-icon slate">
          <AppIcon name="DocumentChecked" :size="22" />
        </div>
        <div>
          <div class="stats-bar-value">{{ evaluatedCount }}</div>
          <div class="stats-bar-label">本页已登记 AP</div>
        </div>
      </div>
    </section>

    <section class="table-panel">
      <div class="collection-heading"><h2><AppIcon name="Collection" :size="18" />模型记录</h2><span>{{ loading ? '正在读取…' : listError ? '本次读取失败' : total==null?'总数尚未核对':`匹配 ${total} 条` }}</span></div>
      <p class="management-applied-query">已查询范围：{{ appliedDescription }}。本页统计不代表全部模型统计，时间 UTC+8。</p>
      <p v-if="filtersDirty" class="management-query-note" role="status">筛选内容尚未查询，翻页和刷新继续沿用已执行的条件。</p>
      <el-button v-if="listError && modelList.length" class="management-retry" :loading="loading" @click="retryModelList"><AppIcon name="Refresh" :size="14" />重读上次请求</el-button>
      <el-alert v-if="listError && modelList.length" :title="listError + '；下方保留先前读取的记录，请重新查询核对。'" type="error" show-icon :closable="false" />
      <TableReadHint v-if="modelList.length" />
      <el-table :scrollbar-tabindex="0" role="region" aria-label="检测模型记录" row-key="modelId" :data="modelList" v-loading="loading" border style="width: 100%">
        <template #empty>
          <CollectionEmptyState :loading="loading" :error="listError" :filtered="listLoaded ? Object.keys(appliedFilters).length>0 : !!hasSearch" empty-title="暂无检测模型" :empty-description="isSupervisor?'可使用上方上传入口登记模型，发布后供检测任务选择。':'当前账号可查看已登记模型，需要新增时请联系主管。'" @retry="retryModelList" @reset="resetSearch" />
        </template>
        <el-table-column label="模型与版本" min-width="230"><template #default="{row}"><div class="model-record-cell"><strong>{{ row.modelName||'模型名称未记录' }}</strong><small>版本 {{ row.version||'未记录' }} · ID {{ row.modelId }}</small><span v-if="modelDefault(row.isDefault)==='是'" class="model-default-marker"><AppIcon name="CircleCheck" :size="13" />默认模型</span></div></template></el-table-column>
        <el-table-column label="训练资料" min-width="210"><template #default="{row}"><div class="model-record-cell"><strong>{{ modelTrainingImages(row.trainingImageCount) }}</strong><small>完成 {{ modelTime(row.trainingCompletedAt) }} · UTC+8</small></div></template></el-table-column>
        <el-table-column label="漏检率 / 速度" min-width="180"><template #default="{row}"><div class="model-record-cell"><strong>整图未检出 {{ modelNoDetection(row).value }}</strong><small>{{ modelNoDetection(row).description }}</small><small>实测 {{ modelFps(row.inferenceFps) }}</small></div></template></el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <StatusBadge domain="model" :code="row.status" :label="statusLabelMap[row.status]" />
          </template>
        </el-table-column>
        <el-table-column label="基础校验" min-width="150">
          <template #default="{ row }">
            <StatusBadge domain="modelValidation" :code="row.validationStatus" />
          </template>
        </el-table-column>
        <el-table-column label="评估资料" min-width="185">
          <template #default="{ row }">
            <div class="model-record-cell"><StatusBadge domain="modelEvaluation" :code="row.mlopsStatus" /><small>mAP（AP）{{ formatMetric(row.mapScore) }}</small></div>
          </template>
        </el-table-column>
        <el-table-column label="登记策略与使用" min-width="190">
          <template #default="{ row }">
            <div class="model-record-cell"><strong>{{ modelStrategy(row) }}</strong><small>已记使用 {{ modelUsage(row.usageCount) }} 次</small><small>最近 {{ formatDateTime(row.lastUsedAt) }}</small></div>
          </template>
        </el-table-column>
        <el-table-column label="操作" :width="isSupervisor?220:88">
          <template #default="{ row }">
            <div class="operation-buttons">
              <el-button size="small" text type="primary" :aria-label="'查看模型 '+row.modelId+' 详情'" @click="handleViewDetails(row)"><AppIcon name="Search" :size="14" />详情</el-button>
              <StatusBadge v-if="modelUncertain(row.modelId)" domain="apiReceipt" code="UNKNOWN" label="上次操作待核对" /><el-button v-if="isSupervisor" size="small" :disabled="controlsBusy || modelUncertain(row.modelId)" @click="openEvaluationDialog(row)">评估</el-button>
              <el-dropdown v-if="isSupervisor" trigger="click" :disabled="controlsBusy || modelUncertain(row.modelId)" @command="command=>handleRowCommand(row,command)"><el-button size="small" :disabled="controlsBusy || modelUncertain(row.modelId)" :aria-label="'模型 '+row.modelId+' 的更多操作'">更多<AppIcon name="ArrowDown" :size="12" /></el-button><template #dropdown><el-dropdown-menu>
                <el-dropdown-item command="edit">编辑版本资料</el-dropdown-item><el-dropdown-item command="rollout">配置登记策略</el-dropdown-item>
                <el-dropdown-item v-if="!['PUBLISHED','ARCHIVED'].includes(row.status)" command="publish" divided>发布模型</el-dropdown-item><el-dropdown-item v-if="modelDefault(row.isDefault)==='否'&&row.status==='PUBLISHED'" command="set-default">设为默认模型</el-dropdown-item>
                <el-dropdown-item v-if="row.status!=='ARCHIVED'" command="validate">重新基础校验</el-dropdown-item><el-dropdown-item v-if="row.status==='PUBLISHED'" command="disable">停用模型</el-dropdown-item><el-dropdown-item v-if="row.status!=='ARCHIVED'" command="archive">归档模型</el-dropdown-item>
                <el-dropdown-item command="delete" divided :disabled="knownCount(row.usageCount)!==0||modelDefault(row.isDefault)!=='否'" :title="knownCount(row.usageCount)!==0?'使用次数未核对或已有使用记录':modelDefault(row.isDefault)!=='否'?'默认状态未核对或仍为默认模型':'删除登记，文件保留待回收'"><span class="model-delete-menu"><AppIcon name="Delete" :size="14" />删除登记</span></el-dropdown-item>
              </el-dropdown-menu></template></el-dropdown>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="total!==null" class="page-footer">
        <el-pagination
          :current-page="pagination.current"
          :page-size="pagination.size" :disabled="loading || !!listError"
          :page-sizes="[10, 20, 30, 50]"
          layout="total, sizes, prev, pager, next, jumper"
          :total="total"
          @size-change="handleSizeChange"
          @current-change="handleCurrentChange"
        />
      </div>
    </section>

    <el-dialog
      class="model-maintenance-dialog"
      v-model="dialogVisible"
      title="编辑模型资料"
      width="min(680px,94vw)"
      :close-on-click-modal="!editSubmitting" :close-on-press-escape="!editSubmitting" :show-close="!editSubmitting"
    >
      <p class="model-list-note">修改版本名称与说明，不替换模型文件。更换文件请使用专用上传页登记新模型。</p>
      <el-alert v-if="editError" :title="editError" :type="editUncertain ? 'warning' : 'error'" :closable="false" />
      <p v-if="editUncertain" class="model-list-note">保存结果尚未核对，请先关闭并刷新列表或详情，当前表单不重复提交。</p>
      <el-form ref="modelFormRef" :model="modelForm" label-position="top" :rules="rules" :disabled="editSubmitting||editUncertain" @submit.prevent="submitForm">
        <el-form-item label="模型名称" prop="modelName">
          <el-input v-model="modelForm.modelName" aria-label="请输入模型名称" placeholder="请输入模型名称" />
        </el-form-item>
        <el-form-item label="版本号" prop="version">
          <el-input v-model="modelForm.version" aria-label="请输入版本号" placeholder="请输入版本号" />
        </el-form-item>
        <el-form-item label="更新说明" prop="updateDescription">
          <el-input
            v-model="modelForm.updateDescription"
            type="textarea"
            :rows="4"
            aria-label="请输入更新说明" placeholder="请输入更新说明"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <span class="dialog-footer">
          <el-button :disabled="editSubmitting" @click="dialogVisible = false"><AppIcon name="Close" :size="16" />关闭</el-button>
          <el-button type="primary" :disabled="editUncertain" :loading="editSubmitting" @click="submitForm">保存版本资料</el-button>
        </span>
      </template>
    </el-dialog>

    <el-drawer v-model="detailDrawerVisible" title="检测模型详情" size="min(740px,96vw)">
      <CollectionEmptyState v-if="!detailModel" :loading="detailLoading" :error="detailError" empty-title="模型详情尚未读取" empty-description="可重新读取相同模型，或关闭后从列表重新选择。" @retry="fetchModelDetail(selectedModelId)" />
      <template v-if="detailModel">
        <DetectionModelDetails :key="String(detailModel.modelId)+':'+String(detailModel.version ?? '')" :model="detailModel" />

        <div class="detail-section">
          <div class="detail-header">
            <h3><AppIcon name="DocumentCopy" :size="17" />操作日志</h3><el-button size="small" :loading="operationLoading" @click="fetchOperationLogs(selectedModelId)"><AppIcon name="Refresh" :size="14" />重新读取</el-button>
          </div>
          <el-alert v-if="operationError&&operationLogs.length" :title="operationError+'；保留先前读取的日志。'" type="error" :closable="false" />
          <el-table :scrollbar-tabindex="0" role="region" aria-label="检测模型操作日志" :data="operationLogs" v-loading="operationLoading" border size="small">
            <template #empty>
              <CollectionEmptyState :loading="operationLoading" :error="operationError" empty-title="暂无已登记的操作日志" empty-description="日志缺失不代表没有执行过操作，请结合当前模型状态核对。" @retry="fetchOperationLogs(selectedModelId)" />
            </template>
            <el-table-column prop="operationType" label="操作类型" width="120" />
            <el-table-column prop="operator" label="操作人" width="120" />
            <el-table-column label="操作时间（UTC+8）" min-width="185">
              <template #default="{ row }">
                {{ formatDateTime(row.operationTime) || '--' }}
              </template>
            </el-table-column>
            <el-table-column prop="remark" label="备注" min-width="200" show-overflow-tooltip />
          </el-table>
        </div>
      </template>
    </el-drawer>

    <el-dialog class="model-maintenance-dialog" v-model="evaluationDialogVisible" title="训练与评估资料" width="min(620px,94vw)" :close-on-click-modal="!mlopsSubmitting" :close-on-press-escape="!mlopsSubmitting" :show-close="!mlopsSubmitting">
      <p class="model-command-context">{{ activeMlopsLabel }}</p><p class="model-list-note">登记已有训练和评估结果，不在此运行训练、评测或测速。输入 0 至 1 的数值，例如 0.6774 显示为 67.74%；留空不补零。请注明 val / test 数据集，AP50、AP75 不能填入 AP。新增训练、计数和 FPS 字段留空表示保留已有登记，不会清除。</p><el-alert v-if="mlopsError" :title="mlopsError" :type="mlopsUncertain ? 'warning' : 'error'" :closable="false" /><p v-if="mlopsUncertain" class="model-list-note">结果尚未确认，请先关闭并刷新详情核对，不直接重复保存。</p>
      <el-form :model="evaluationForm" label-position="top" :disabled="mlopsSubmitting||mlopsUncertain" @submit.prevent="submitEvaluation" class="model-metrics-form">
        <el-form-item label="训练图片数量（原始训练集，不含重复增强）">
          <el-input-number v-model="evaluationForm.trainingImageCount" :min="1" :max="2147483647" :precision="0" aria-label="训练图片数量" style="width:100%" />
        </el-form-item>
        <el-form-item label="训练完成日期时间（UTC+8）">
          <el-date-picker v-model="evaluationForm.trainingCompletedAt" type="datetime" format="YYYY-MM-DD HH:mm:ss" value-format="YYYY-MM-DDTHH:mm:ss" placeholder="选择实际训练完成时间" aria-label="训练完成日期时间 UTC+8" style="width:100%" />
        </el-form-item>
        <el-form-item label="评估数据集（注明 val / test）">
          <el-input v-model="evaluationForm.evaluationDataset" aria-label="例如 door-handle-test" placeholder="例如 door-handle-test" />
        </el-form-item>
        <el-form-item label="mAP / AP（0–1）">
          <el-input-number v-model="evaluationForm.mapScore" :min="0" :max="1" :step="0.0001" :precision="4" style="width: 100%" />
        </el-form-item>
        <el-form-item label="成功评估图片数（排除执行失败）"><el-input-number v-model="evaluationForm.evaluationImageCount" :min="0" :max="2147483647" :precision="0" aria-label="成功评估图片数" style="width:100%" /></el-form-item>
        <el-form-item label="整图未检出图片数（所有类别均未检出）"><el-input-number v-model="evaluationForm.noDetectionImageCount" :min="0" :max="2147483647" :precision="0" aria-label="整图未检出图片数" style="width:100%" /></el-form-item>
        <p class="model-list-note" role="status">整图未检出率：{{ modelNoDetection(evaluationForm).value }} · {{ modelNoDetection(evaluationForm).description }}。Normal 检出也算检出；两项计数一起登记，比例自动计算。</p>
        <el-form-item label="实测每秒检测图片速度 FPS（张/秒）"><el-input-number v-model="evaluationForm.inferenceFps" :min="0.0001" :max="MODEL_FPS_MAX" :precision="4" aria-label="实测每秒检测图片速度 FPS" style="width:100%" /></el-form-item>
        <details class="operation-disclosure"><summary>其他历史指标（兼容已有登记）</summary><p class="model-list-note">已有数值仍保留，非当前主评估指标；不要用 AP 代填。</p><el-form-item v-for="[key,label] in modelLegacyMetricFields" :key="key" :label="label"><el-input-number v-model="evaluationForm[key]" :min="0" :max="1" :step="0.0001" :precision="4" style="width:100%" /></el-form-item></details>
        <el-form-item label="平均推理耗时（毫秒）">
          <el-input-number v-model="evaluationForm.avgInferenceMs" :min="0" :precision="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="测试环境与兼容性说明（有 FPS 时必填）">
          <el-input v-model="evaluationForm.compatibilityNote" type="textarea" :rows="3" maxlength="500" show-word-limit aria-label="测试环境与兼容性说明" placeholder="记录 PyTorch 版本、CPU/GPU 型号、输入尺寸、batch、样本数、阈值、计时是否包含预处理和后处理" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="mlopsSubmitting" @click="evaluationDialogVisible = false"><AppIcon name="Close" :size="16" />关闭</el-button>
        <el-button type="primary" :disabled="mlopsUncertain" :loading="mlopsSubmitting" @click="submitEvaluation">保存评估资料</el-button>
      </template>
    </el-dialog>

    <el-dialog class="model-maintenance-dialog" v-model="rolloutDialogVisible" title="配置模型登记策略" width="min(560px,94vw)" :close-on-click-modal="!mlopsSubmitting" :close-on-press-escape="!mlopsSubmitting" :show-close="!mlopsSubmitting">
      <p class="model-command-context">{{ activeMlopsLabel }}</p><p class="model-list-note">原登记：{{ modelStrategy(activeMlopsSnapshot||{}) }}。以下为拟保存配置；保存不代表实际流量分配、推理切换或服务器部署已经完成。</p><el-alert v-if="mlopsError" :title="mlopsError" :type="mlopsUncertain ? 'warning' : 'error'" :closable="false" /><p v-if="mlopsUncertain" class="model-list-note">结果尚未确认，请先关闭并刷新详情核对，不直接重复保存。</p>
      <el-form :model="rolloutForm" label-position="top" :disabled="mlopsSubmitting||mlopsUncertain" @submit.prevent="submitRollout">
        <el-form-item label="部署策略">
          <el-select v-model="rolloutForm.deploymentStrategy" style="width: 100%">
            <el-option label="全量发布" value="FULL" />
            <el-option label="灰度发布" value="CANARY" />
            <el-option label="A/B 对比" value="AB_TEST" />
            <el-option label="模型回滚" value="ROLLBACK" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="rolloutForm.deploymentStrategy==='CANARY'" label="灰度比例（%）">
          <el-input-number v-model="rolloutForm.canaryPercent" :min="0" :max="100" :precision="0" placeholder="填写登记比例" style="width:100%" />
        </el-form-item>
        <el-form-item v-if="rolloutForm.deploymentStrategy==='AB_TEST'" label="A/B 分组">
          <el-select v-model="rolloutForm.abGroup" clearable style="width: 100%">
            <el-option label="A 组" value="A" />
            <el-option label="B 组" value="B" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="rolloutForm.deploymentStrategy==='ROLLBACK'" label="回滚来源模型 ID">
          <el-input-number v-model="rolloutForm.rollbackFromModelId" :min="1" :precision="0" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="mlopsSubmitting" @click="rolloutDialogVisible = false"><AppIcon name="Close" :size="16" />关闭</el-button>
        <el-button type="primary" :disabled="mlopsUncertain" :loading="mlopsSubmitting" @click="submitRollout">保存登记策略</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { validResourceId } from '@/utils/agentCards'
import request from '../api/request'
import { ElMessage, ElMessageBox } from 'element-plus'
import ModelFileJournal from '@/components/ModelFileJournal.vue'
import CollectionEmptyState from '@/components/CollectionEmptyState.vue'
import DetectionModelDetails from '@/components/DetectionModelDetails.vue'
import {useUserStore} from '@/stores/user'
import {knownCount} from '@/utils/countPresentation'
import {useManagedList} from '@/composables/useManagedList'
import {modelTime,modelMetric,modelMetricNumber,modelUsage,modelDefault,modelStrategy,modelLegacyMetricFields,modelFps,modelFpsNumber,modelTrainingImages,modelNoDetection,MODEL_FPS_MAX} from '@/utils/detectionModelPresentation'
const userStore=useUserStore()
const isSupervisor=computed(()=>userStore.isAuthenticated && userStore.role==='SUPERVISOR')
const actor=computed(()=>JSON.stringify([userStore.identity?.userId || userStore.username || '',userStore.role,userStore.isAuthenticated]))

const {records:modelList,total,loading,error:listError,loaded:listLoaded,filterError,filters:searchForm,pagination,hasFilters:hasSearch,filtersDirty,appliedFilters,search:handleSearch,reset:resetSearch,refresh:fetchModelList,retry:retryModelList,changePage:handleCurrentChange,changeSize:handleSizeChange}=useManagedList('/api/model-info',['modelId','modelName','version','status'],{
  idField:'modelId',scope:actor,canRead:()=>userStore.isAuthenticated,
  validateFilters:filters=>filters.modelId && !validResourceId(String(filters.modelId),'MODELS') ? '请填写有效的正整数模型 ID；尚未执行这组筛选。' : ''
})
let pageActive=true,accountGeneration=0
const currentAccount=scope=>pageActive && accountGeneration===scope
const uncertainModelIds=ref(new Set())
const modelCommandUncertain=ref(false)
const modelUncertain=id=>uncertainModelIds.value.has(String(id))
function markUncertain(id){uncertainModelIds.value=new Set([...uncertainModelIds.value,String(id)])}
const appliedDescription=computed(()=>Object.entries(appliedFilters.value).map(([key,value])=>`${({modelId:'模型 ID',modelName:'名称',version:'版本',status:'状态'})[key]}：${key==='status'?statusLabelMap[value] || value:value}`).join(' · ') || (listLoaded.value?'全部条件':'尚未完成读取'))
const detailDrawerVisible = ref(false)
const detailModel = ref(null)
const detailLoading = ref(false)
const detailError = ref('')
const selectedModelId = ref(null)
const route = useRoute()
const router=useRouter()
let detailGeneration = 0,detailReadVersion=0,operationReadVersion=0
const operationLogs = ref([])
const operationLoading = ref(false)
const operationError=ref('')
const evaluationDialogVisible = ref(false)
const rolloutDialogVisible = ref(false)
const mlopsSubmitting = ref(false)
const activeMlopsModelId = ref(null)
const activeMlopsSnapshot=ref(null),mlopsError=ref(''),mlopsUncertain=ref(false)
const editSubmitting=ref(false),editError=ref(''),editUncertain=ref(false),lifecyclePending=ref(false),modelCommandError=ref('')
const mutationBusy=computed(()=>mlopsSubmitting.value||editSubmitting.value||lifecyclePending.value)
const controlsBusy=computed(()=>loading.value||mutationBusy.value)
const activeMlopsLabel=computed(()=>{const model=activeMlopsSnapshot.value;return model?`${model.modelName||'模型名称未记录'} · 版本 ${model.version||'未记录'} · ID ${model.modelId}`:'模型资料尚未核对'})

const statusLabelMap = {
  READY: '待发布',
  PUBLISHED: '已发布',
  DISABLED: '已停用',
  ARCHIVED: '已归档',
  DRAFT: '草稿'
}

const dialogVisible = ref(false)
const modelForm = reactive({
  modelId: null,
  modelName: '',
  version: '',
  modelPath: '',
  updateDescription: ''
})
const modelFormRef = ref(null)

const evaluationForm = reactive({
  trainingImageCount:undefined,trainingCompletedAt:undefined,evaluationImageCount:undefined,noDetectionImageCount:undefined,inferenceFps:undefined,
  evaluationDataset: '',
  precisionScore: undefined,
  recallScore: undefined,
  mapScore: undefined,
  f1Score: undefined,
  avgInferenceMs: undefined,
  compatibilityNote: ''
})

const rolloutForm = reactive({
  deploymentStrategy: 'FULL',
  canaryPercent: 100,
  abGroup: '',
  rollbackFromModelId: null
})

const rules = {
  modelName: [
    { required: true, message: '请输入模型名称', trigger: 'blur' }
  ],
  version: [
    { required: true, message: '请输入版本号', trigger: 'blur' }
  ],
  updateDescription: [
    { required: true, message: '请输入更新说明', trigger: 'blur' }
  ]
}

const defaultModel = computed(() => modelList.value.find((item) => modelDefault(item.isDefault)==='是') || null)
const publishedCount = computed(() => modelList.value.filter((item) => item.status === 'PUBLISHED').length)
const evaluatedCount = computed(() => modelList.value.filter(item=>modelMetricNumber(item.mapScore)!=null).length)
const totalUsageCount = computed(() => modelList.value.every(item=>knownCount(item.usageCount)!=null)?modelList.value.reduce((sum,item)=>sum+knownCount(item.usageCount),0):null)

const formatMetric=modelMetric
const formatDateTime=modelTime

const handleUpload = () => {
  if(!isSupervisor.value)return
  router.push('/models/upload')
}

const handleEdit = (row) => {
  if(!isSupervisor.value||mutationBusy.value||modelUncertain(row.modelId))return
  Object.assign(modelForm,{modelId:row.modelId,modelName:row.modelName||'',version:row.version||'',modelPath:row.modelPath||'',updateDescription:row.updateDescription||''})
  editError.value='';editUncertain.value=false
  dialogVisible.value = true
}

const handleViewDetails = (row) => {
  detailGeneration++
  selectedModelId.value = row.modelId
  detailModel.value = null
  detailError.value = ''
  operationLogs.value = []
  operationError.value=''
  detailDrawerVisible.value = true
  fetchModelDetail(row.modelId)
  fetchOperationLogs(row.modelId)
}

const openEvaluationDialog = (row) => {
  if(!isSupervisor.value||mutationBusy.value||modelUncertain(row.modelId))return
  activeMlopsModelId.value = row.modelId
  activeMlopsSnapshot.value={...row};mlopsError.value='';mlopsUncertain.value=false
  evaluationForm.evaluationDataset = row.evaluationDataset || ''
  evaluationForm.precisionScore = modelMetricNumber(row.precisionScore)
  evaluationForm.recallScore = modelMetricNumber(row.recallScore)
  evaluationForm.mapScore = modelMetricNumber(row.mapScore)
  evaluationForm.f1Score = modelMetricNumber(row.f1Score)
  evaluationForm.avgInferenceMs = knownCount(row.avgInferenceMs)??undefined
  evaluationForm.trainingImageCount = knownCount(row.trainingImageCount) || undefined
  evaluationForm.trainingCompletedAt = row.trainingCompletedAt ? modelTime(row.trainingCompletedAt).replace(' ','T') : undefined
  evaluationForm.evaluationImageCount = knownCount(row.evaluationImageCount) ?? undefined
  evaluationForm.noDetectionImageCount = knownCount(row.noDetectionImageCount) ?? undefined
  evaluationForm.inferenceFps = modelFpsNumber(row.inferenceFps)
  evaluationForm.compatibilityNote = row.compatibilityNote || ''
  evaluationDialogVisible.value = true
}

const openRolloutDialog = (row) => {
  if(!isSupervisor.value||mutationBusy.value||modelUncertain(row.modelId))return
  activeMlopsModelId.value = row.modelId
  activeMlopsSnapshot.value={...row};mlopsError.value='';mlopsUncertain.value=false
  rolloutForm.deploymentStrategy = row.deploymentStrategy || ''
  rolloutForm.canaryPercent = knownCount(row.canaryPercent)??undefined
  rolloutForm.abGroup = row.abGroup || ''
  rolloutForm.rollbackFromModelId = row.rollbackFromModelId || null
  rolloutDialogVisible.value = true
}

const fetchModelDetail = (modelId) => {
  const generation = detailGeneration
  const requestVersion=++detailReadVersion
  detailLoading.value = true
  request.get(`/api/model-info/${modelId}`)
    .then((response) => {
      if (generation !== detailGeneration || selectedModelId.value !== modelId || requestVersion!==detailReadVersion) return
      if (response.data.code === 200) {
        const model=response.data.data
        if(!model||typeof model!=='object'||Array.isArray(model)||String(model.modelId)!==String(modelId))throw Error('模型详情未完整返回')
        detailModel.value = model
      } else {
        detailModel.value = null
        const code = Number(response.data?.code)
        detailError.value = code === 404 ? '未找到此模型，请返回列表重新查询' : code === 403 ? '当前账号无权读取此模型，请核对账号范围' : '模型详情未读取成功，请重新读取核对'
      }
    })
    .catch(() => {
      if (generation !== detailGeneration || selectedModelId.value !== modelId || requestVersion!==detailReadVersion) return
      detailModel.value = null
      detailError.value = '模型详情暂不可用 请稍后重新打开'
    })
    .finally(() => { if (generation === detailGeneration && requestVersion===detailReadVersion) detailLoading.value = false })
}

const handleDelete=async(modelId)=>{
  if(!isSupervisor.value || mutationBusy.value || modelUncertain(modelId))return
  const scope=accountGeneration
  lifecyclePending.value=true;modelCommandError.value='';modelCommandUncertain.value=false
  try{
    const response=await request.delete(`/api/models/${modelId}`)
    if(!currentAccount(scope))return
    requireModelReceipt(response)
    ElMessage.success('已收到模型登记删除回执，文件保留待回收')
    if(String(selectedModelId.value)===String(modelId))detailDrawerVisible.value=false
    fetchModelList()
  }catch(cause){
    if(currentAccount(scope)){modelCommandUncertain.value=isUncertain(cause);if(modelCommandUncertain.value)markUncertain(modelId);modelCommandError.value=`模型 ID ${modelId}：${cause.response?.data?.message || cause.message || '删除结果未确认'}；请核对模型列表与文件记录，不会自动重试。`}
  }finally{if(currentAccount(scope))lifecyclePending.value=false}
}
const fetchOperationLogs = (modelId) => {
  const generation = detailGeneration
  const requestVersion=++operationReadVersion
  operationLoading.value = true
  operationError.value=''
  request.get(`/api/models/${modelId}/operations`)
    .then((response) => {
      if (generation !== detailGeneration || selectedModelId.value !== modelId || requestVersion!==operationReadVersion) return
      if (response.data.code === 200) {
        if(!Array.isArray(response.data.data))throw Error('操作日志未完整返回')
        operationLogs.value = response.data.data
      } else {
        operationError.value=response.data.message || '获取操作日志失败'
      }
    })
    .catch((error) => {
      if (generation !== detailGeneration || selectedModelId.value !== modelId || requestVersion!==operationReadVersion) return
      console.error('获取操作日志失败:', error)
      operationError.value='操作日志暂不可读取，请重新读取核对'
    })
    .finally(() => {
      if (generation === detailGeneration && requestVersion===operationReadVersion) operationLoading.value = false
    })
}

const lifecycleActionMap = {
  publish: { url: 'publish', success: '发布成功' },
  'set-default': { url: 'set-default', success: '默认模型已切换' },
  validate: { url: 'validate', success: '重新校验完成' },
  disable: { url: 'disable', success: '停用成功' },
  archive: { url: 'archive', success: '归档成功' }
}
async function handleRowCommand(row,command){
  if(!isSupervisor.value || controlsBusy.value || modelUncertain(row.modelId))return
  if(command==='edit')return handleEdit(row)
  if(command==='rollout')return openRolloutDialog(row)
  modelCommandUncertain.value=false
  const scope=accountGeneration,modelId=row.modelId
  const snapshot=JSON.stringify([row.modelName,row.version,row.status,row.isDefault,row.usageCount])
  const title=`${row.modelName || '未命名模型'} · 版本 ${row.version || '未记录'}（ID ${modelId}）`
  if(command==='delete' && (knownCount(row.usageCount)!==0 || modelDefault(row.isDefault)!=='否'))return
  const prompts={delete:`删除 ${title} 的登记？文件会保留待回收，不在此物理删除。`,publish:`发布 ${title}？具体任务使用哪个模型以任务记录为准。`,'set-default':`将 ${title} 登记为默认检测模型？请确认版本与基础校验结果。`,disable:`停用 ${title}？请先核对该模型是否仍被业务使用。`,archive:`归档 ${title}？请先核对历史使用与后续模型选择。`}
  if(prompts[command]){
    try{await ElMessageBox.confirm(prompts[command],'核对模型操作',{type:['delete','disable','archive'].includes(command)?'warning':'info',confirmButtonText:command==='delete'?'删除登记':'确认操作',cancelButtonText:'保留当前状态'})}catch{return}
    if(!currentAccount(scope) || !isSupervisor.value || mutationBusy.value)return
    const latest=modelList.value.find(item=>String(item.modelId)===String(modelId))
    if(!latest || JSON.stringify([latest.modelName,latest.version,latest.status,latest.isDefault,latest.usageCount])!==snapshot){modelCommandError.value='本页模型资料已变化，尚未发送操作，请重新读取后核对。';return}
  }
  if(command==='delete')return handleDelete(modelId)
  if(Object.hasOwn(lifecycleActionMap,command))return handleLifecycleAction(modelId,command)
}
function refreshAfterCommand(modelId){
  fetchModelList()
  if(detailDrawerVisible.value && String(selectedModelId.value)===String(modelId)){fetchModelDetail(selectedModelId.value);fetchOperationLogs(selectedModelId.value)}
}
const handleLifecycleAction=async(modelId,action)=>{
  if(!isSupervisor.value || mutationBusy.value || modelUncertain(modelId))return
  const config=lifecycleActionMap[action]
  if(!config)return
  const scope=accountGeneration
  lifecyclePending.value=true;modelCommandError.value='';modelCommandUncertain.value=false
  try{
    const response=await request.post(`/api/models/${modelId}/${config.url}`)
    if(!currentAccount(scope))return
    requireModelReceipt(response,modelId)
    const data=response.data.data,expected={publish:'PUBLISHED',disable:'DISABLED',archive:'ARCHIVED'}[action]
    if(expected && data.status!==expected || action==='set-default' && modelDefault(data.isDefault)!=='是'){const cause=new Error('已收到模型资料，但目标状态尚未确认');cause.uncertain=true;throw cause}
    if(action==='validate' && data.validationStatus!=='PASSED')ElMessage.warning('已收到基础校验回执，请核对校验状态与说明')
    else ElMessage.success(`已收到回执：${config.success}`)
    refreshAfterCommand(modelId)
  }catch(cause){
    if(currentAccount(scope)){modelCommandUncertain.value=isUncertain(cause);if(modelCommandUncertain.value)markUncertain(modelId);modelCommandError.value=`模型 ID ${modelId}：${cause.response?.data?.message || cause.message || '操作回执未确认'}；请刷新模型资料与日志核对。`}
  }finally{if(currentAccount(scope))lifecyclePending.value=false}
}
function requireModelReceipt(response,modelId){
  if(response.data?.code===200){
    // Metadata edits and delete acknowledge void commands; lifecycle endpoints return ModelInfo.
    if(modelId!=null && (!validResourceId(String(response.data.data?.modelId),'MODELS') || String(response.data.data.modelId)!==String(modelId))){const cause=new Error('未收到匹配的模型编号回执');cause.uncertain=true;throw cause}
    return
  }
  const cause=new Error(response.data?.message || '模型操作回执尚未确认'),code=Number(response.data?.code)
  cause.uncertain=!(code>=400 && code<500 && code!==408)
  throw cause
}
function isUncertain(cause){return cause.uncertain ?? (!cause.response || cause.response.status>=500 || cause.response.status===408)}
async function saveModelAssessment(kind){
  if(!activeMlopsModelId.value || !isSupervisor.value || mutationBusy.value || mlopsUncertain.value || modelUncertain(activeMlopsModelId.value))return
  const modelId=activeMlopsModelId.value,payload=Object.freeze({...(kind==='evaluation'?evaluationForm:rolloutForm)}),scope=accountGeneration
  if(kind==='evaluation'){
    const train=payload.trainingImageCount,images=payload.evaluationImageCount,empty=payload.noDetectionImageCount
    if(payload.mapScore!=null && modelMetricNumber(payload.mapScore)==null){mlopsError.value='mAP / AP 必须在 0–1 之间，尚未保存';return}
    if(train!=null && (!Number.isInteger(train)||train<1||train>2147483647)){mlopsError.value='训练图片数量须为正整数，尚未保存';return}
    if((images==null)!==(empty==null) || images!=null && (![images,empty].every(value=>Number.isInteger(value)&&value>=0&&value<=2147483647)||empty>images)){mlopsError.value='请同时填写成功评估与整图未检出图片数，未检出数不能超过成功数';return}
    if(payload.inferenceFps!=null && (modelFpsNumber(payload.inferenceFps)==null||!payload.compatibilityNote?.trim())){mlopsError.value='FPS 须大于零，且需注明设备、输入尺寸、batch 和计时范围';return}
    if(payload.trainingCompletedAt && modelTime(payload.trainingCompletedAt)==='时间格式未知'){mlopsError.value='训练完成日期格式无效，尚未保存';return}
  }
  if(kind==='rollout'){
    const percent=knownCount(payload.canaryPercent)
    if(!['FULL','CANARY','AB_TEST','ROLLBACK'].includes(payload.deploymentStrategy)){mlopsError.value='请选择要登记的策略，尚未发送保存';return}
    if(payload.deploymentStrategy==='CANARY' && (percent==null || percent>100 || !Number.isInteger(percent))){mlopsError.value='请填写 0–100 的整数登记比例，尚未发送保存';return}
    if(payload.deploymentStrategy==='AB_TEST' && !['A','B'].includes(payload.abGroup)){mlopsError.value='请选择 A/B 分组，尚未发送保存';return}
    if(payload.deploymentStrategy==='ROLLBACK' && !validResourceId(String(payload.rollbackFromModelId),'MODELS')){mlopsError.value='请填写有效的回滚来源模型 ID，尚未发送保存';return}
  }
  mlopsSubmitting.value=true;mlopsError.value=''
  try{
    const response=await request.post(`/api/model-info/${modelId}/${kind}`,payload)
    if(!currentAccount(scope))return
    requireModelReceipt(response)
    if(kind==='evaluation')evaluationDialogVisible.value=false;else rolloutDialogVisible.value=false
    ElMessage.success(kind==='evaluation'?'模型评估资料已保存':'模型登记策略已保存')
    refreshAfterCommand(modelId)
  }catch(cause){if(currentAccount(scope)){mlopsError.value=cause.response?.data?.message || cause.message || '保存结果尚未核对';mlopsUncertain.value=isUncertain(cause);if(mlopsUncertain.value)markUncertain(modelId)}}
  finally{if(currentAccount(scope))mlopsSubmitting.value=false}
}
const submitEvaluation=()=>saveModelAssessment('evaluation')
const submitRollout=()=>saveModelAssessment('rollout')
const submitForm=async()=>{
  if(!modelFormRef.value || !isSupervisor.value || mutationBusy.value || editUncertain.value || modelUncertain(modelForm.modelId))return
  const modelId=modelForm.modelId,scope=accountGeneration,payload=Object.freeze({modelName:modelForm.modelName,version:modelForm.version,updateDescription:modelForm.updateDescription})
  editSubmitting.value=true;editError.value=''
  try{
    const valid=await modelFormRef.value.validate().catch(()=>false)
    if(!currentAccount(scope) || !isSupervisor.value || !valid)return
    const response=await request.put(`/api/model-info/${modelId}`,payload)
    if(!currentAccount(scope))return
    requireModelReceipt(response)
    dialogVisible.value=false;ElMessage.success('模型版本资料已保存');refreshAfterCommand(modelId)
  }catch(cause){if(currentAccount(scope)){editError.value=cause.response?.data?.message || cause.message || '保存结果尚未核对';editUncertain.value=isUncertain(cause);if(editUncertain.value)markUncertain(modelId)}}
  finally{if(currentAccount(scope))editSubmitting.value=false}
}

watch(actor,()=>{
  accountGeneration++;detailGeneration++;detailDrawerVisible.value=false;detailModel.value=null;selectedModelId.value=null;operationLogs.value=[];detailLoading.value=false;operationLoading.value=false;detailError.value='';operationError.value=''
  dialogVisible.value=false;evaluationDialogVisible.value=false;rolloutDialogVisible.value=false;activeMlopsModelId.value=null;activeMlopsSnapshot.value=null
  Object.assign(modelForm,{modelId:null,modelName:'',version:'',modelPath:'',updateDescription:''})
  Object.assign(evaluationForm,{trainingImageCount:undefined,trainingCompletedAt:undefined,evaluationImageCount:undefined,noDetectionImageCount:undefined,inferenceFps:undefined,evaluationDataset:'',precisionScore:undefined,recallScore:undefined,mapScore:undefined,f1Score:undefined,avgInferenceMs:undefined,compatibilityNote:''})
  Object.assign(rolloutForm,{deploymentStrategy:'',canaryPercent:undefined,abGroup:'',rollbackFromModelId:null})
  mlopsSubmitting.value=false;editSubmitting.value=false;lifecyclePending.value=false;mlopsError.value='';editError.value='';modelCommandError.value='';mlopsUncertain.value=false;editUncertain.value=false;uncertainModelIds.value=new Set();modelCommandUncertain.value=false
},{flush:'sync'})
watch(detailDrawerVisible, visible => {
  if (!visible) {
    detailGeneration++
    selectedModelId.value = null
    detailModel.value = null
    operationLogs.value = []
    detailLoading.value = false
    operationLoading.value = false
    detailError.value = ''
    operationError.value=''
  }
}, { flush: 'sync' })
watch(() => route.query.modelId, id => {
  if (validResourceId(id, 'MODELS')) handleViewDetails({ modelId: Number(id) })
  else {
    detailDrawerVisible.value = false
    if (id != null) ElMessage.warning('模型编号不合法 请从模型列表重新选择')
  }
}, { immediate: true })
onBeforeUnmount(() => { pageActive=false;detailGeneration++;accountGeneration++ })
onMounted(() => {
  fetchModelList()
})
</script>

<style scoped>
.model-page {
  gap: 18px;
}

.upload-tip {
  color: #64748b;
  font-size: 13px;
}

.selected-file {
  margin-top: 8px;
  color: #0f766e;
  font-size: 14px;
  font-weight: 600;
}

.default-model-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 18px 22px;
  border-radius: 10px;
  background: var(--app-surface);
  border: 1px solid #d5e3fc;
  border-left: 4px solid var(--app-primary);
}

.default-model-label {
  font-size: 12px;
  color: var(--app-primary);
}

.default-model-name {
  margin-top: 6px;
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
}

.default-model-version {
  font-size: 16px;
  color: #475569;
  font-weight: 600;
}

.default-model-meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 14px;
  color: #334155;
  font-size: 13px;
}

.detail-section {
  margin-bottom: 24px;
}

.detail-header h3 {
  margin: 0 0 12px;
  font-size: 16px;
  color: #0f172a;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 18px;
  margin-bottom: 18px;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.detail-label {
  font-size: 12px;
  color: #64748b;
}

.detail-value {
  font-size: 14px;
  color: #0f172a;
  font-weight: 600;
}

.detail-block {
  margin-bottom: 14px;
}

.detail-multiline {
  margin-top: 6px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
  color: #334155;
  line-height: 1.6;
  word-break: break-all;
}
.model-record-cell{display:grid;gap:5px;line-height:1.8;min-width:0;padding:4px 0}.model-record-cell strong{font-size:13px;font-weight:550;color:var(--app-text);overflow-wrap:anywhere}.model-record-cell small{font-size:11px;color:var(--app-text-secondary);overflow-wrap:anywhere}.model-default-marker{display:inline-flex;align-items:center;gap:5px;width:fit-content;color:var(--app-primary);font-size:11px}.model-delete-menu{display:inline-flex;align-items:center;gap:7px;color:var(--app-danger)}.model-list-note{font-size:12px;line-height:1.9;color:var(--app-text-secondary);margin:12px 0 16px;overflow-wrap:anywhere}.table-panel>.model-list-note{padding:0 20px}.model-list-note>.el-icon{color:var(--app-primary);vertical-align:middle;margin-right:5px}.model-command-context{padding:12px 14px;background:var(--app-primary-soft);border-radius:8px;color:var(--app-text);font-size:13px;line-height:1.85;overflow-wrap:anywhere}.detail-header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:24px 0 12px;flex-wrap:wrap}.detail-header h3{display:flex;align-items:center;gap:8px;margin:0}.detail-header h3>.el-icon{color:var(--app-primary)}.operation-buttons{display:flex;align-items:center;flex-wrap:wrap;gap:6px}.operation-buttons>.el-button{margin-left:0}.default-model-name{overflow-wrap:anywhere;line-height:1.6}.default-model-meta{align-items:center;font-size:12px;line-height:1.85}.default-model-meta>span{min-width:0;overflow-wrap:anywhere}@media(max-width:700px){.default-model-banner{flex-direction:column;align-items:stretch;padding:16px}.default-model-meta{justify-content:flex-start;gap:8px 14px}.default-model-name{font-size:18px}}
.model-filter-form { grid-template-columns:repeat(4,minmax(0,1fr)); }
.model-filter-form .management-filter-actions { grid-column:1/-1; justify-content:flex-end; }
@media(max-width:900px) { .model-filter-form { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media(max-width:600px) { .model-filter-form { grid-template-columns:minmax(0,1fr); } }
</style>

<style>
.model-maintenance-dialog.el-dialog { display:flex; flex-direction:column; max-height:90vh; max-height:90dvh; margin-block:5vh; }
.model-maintenance-dialog :is(.el-dialog__header,.el-dialog__footer) { flex-shrink:0; }
.model-maintenance-dialog .el-dialog__body { min-height:0; max-height:65vh; max-height:65dvh; overflow:auto; overscroll-behavior:contain; }
.model-maintenance-dialog .el-dialog__footer,.model-maintenance-dialog .dialog-footer { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:8px; }
.model-maintenance-dialog .el-dialog__footer .el-button + .el-button { margin-left:0; }
.model-maintenance-dialog summary { cursor:pointer; font-size:12px; line-height:1.8; color:var(--app-primary); margin-bottom:12px; }
.model-maintenance-dialog summary:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
</style>
