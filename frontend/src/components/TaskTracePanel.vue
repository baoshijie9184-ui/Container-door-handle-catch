<template>
  <div ref="root" class="task-trace-panel" :aria-busy="loading">
    <CollectionEmptyState v-if="!detail" :loading="loading" :error="error" empty-title="尚未读取任务详情" empty-description="读取完成后可核对图片、人工复核和处置记录。" @retry="$emit('refresh')" />
    <template v-else>
      <header class="task-trace-heading"><span class="task-trace-symbol"><AppIcon name="Tickets" :size="22" /></span><div><h3>{{ detail.taskId }}</h3><p>本次已读任务资料，检测、人工复核、放行与报告审批分别核对。</p></div></header>
      <p v-if="loading" class="task-trace-read-note" role="status">正在重新读取，当前保留上次资料；读取成功后再核对最新状态。</p>
      <el-alert v-if="error" :title="error" description="当前仍是上次已读资料，不能据此判断本次读取已成功。" type="warning" :closable="false" show-icon />
      <nav ref="navigation" class="task-trace-navigation" aria-label="任务详情分区"><button v-for="section in sections" :key="section.key" type="button" @click="go(section.key)"><AppIcon :name="section.icon" :size="15" />{{ section.label }}</button></nav>
      <section :ref="node => targets.overview = node" tabindex="-1" aria-label="任务概览">
        <QualityStageGuidance :task="detail" />
        <dl class="task-trace-responsibility"><div><dt>记录责任人</dt><dd>{{ detail.assignee || '未记录责任人' }}</dd></div><div><dt>质检截止 · UTC+8</dt><dd>{{ time(detail.dueAt) }}</dd></div><div><dt>分派时间 · UTC+8</dt><dd>{{ time(detail.assignedAt) }}</dd></div></dl>
        <p v-if="Number.isSafeInteger(detail.assignmentRevision) && detail.assignmentRevision >= 0" class="task-trace-version">已读分派版本 V{{ detail.assignmentRevision }}</p>
        <p v-if="detail.assignmentRemark" class="task-trace-assignment-note"><strong>分派说明</strong>{{ detail.assignmentRemark }}</p>
        <dl class="task-trace-image-counts"><div><dt>记录图片总数</dt><dd>{{ count(detail.totalImages) }}</dd></div><div><dt>检测成功图片</dt><dd>{{ count(detail.successfulImages) }}</dd></div><div><dt>检测失败图片</dt><dd :data-error="detail.failedImages > 0">{{ count(detail.failedImages) }}</dd></div></dl>
      </section>
      <section :ref="node => targets.images = node" tabindex="-1" aria-label="图片对照"><EvidenceComparison :task-id="detail.taskId" :originals="detail.originalImages || []" :annotations="detail.previewImages || []" /></section>
      <section :ref="node => targets.records = node" tabindex="-1" aria-label="任务及人工处理资料"><TaskTraceDetails :detail="detail" /></section>
      <section :ref="node => targets.timeline = node" tabindex="-1" aria-label="已记录流程节点"><TaskTraceTimeline :key="detail.taskId" :events="detail.timeline" /></section>
      <details class="task-trace-disclosure"><summary><AppIcon name="Document" :size="16" /><span>存储与结果记录</span><AppIcon name="ArrowDown" :size="14" class="task-trace-chevron" /></summary><dl class="task-trace-storage"><div><dt>工作流编号</dt><dd><code>{{ detail.workflowUuid || '未记录' }}</code></dd></div><div><dt>原图存储前缀</dt><dd><code>{{ detail.sourceOssPrefix || '未记录' }}</code></dd></div><div><dt>结果存储前缀</dt><dd><code>{{ detail.resultOssPrefix || '未记录' }}</code></dd></div><div><dt>结果 JSON</dt><dd><a v-if="resultLink" :href="resultLink" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ detail.resultJsonKey || '打开原结果记录' }}<AppIcon name="TopRight" :size="13" /></a><code v-else>{{ detail.resultJsonKey || '未记录' }}</code></dd></div></dl></details>
      <details class="task-trace-disclosure"><summary><AppIcon name="Files" :size="16" /><span>原图与标注资料清单</span><small>{{ fileRows.length.toLocaleString('zh-CN') }} 条</small><AppIcon name="ArrowDown" :size="14" class="task-trace-chevron" /></summary><p class="task-trace-files-note">这里只展示本次已返回的文件记录，不表示图片已成功打开；原图与标注的匹配请在上方图片对照中核对。</p><div class="task-trace-files"><el-table :scrollbar-tabindex="0" role="region" aria-label="本次返回的原图与标注文件记录" :data="fileRows" size="small" max-height="320" empty-text="本次没有返回可展示文件记录"><el-table-column prop="type" label="类型" width="90"/><el-table-column label="文件名" min-width="180"><template #default="{ row }">{{ row.imageName || '名称未记录' }}</template></el-table-column><el-table-column label="存储对象标识" min-width="260"><template #default="{ row }"><code>{{ row.objectKey || '未记录' }}</code></template></el-table-column><el-table-column label="原预览" width="110"><template #default="{ row }"><a v-if="previewUrl(row)" :href="previewUrl(row)" :aria-label="'打开原预览：' + (row.imageName || '名称未记录')" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">打开<AppIcon name="TopRight" :size="13" /></a><span v-else>不可用</span></template></el-table-column></el-table></div></details>
    </template>
  </div>
</template>
<script setup>
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import CollectionEmptyState from './CollectionEmptyState.vue'
import QualityStageGuidance from './QualityStageGuidance.vue'
import EvidenceComparison from './EvidenceComparison.vue'
import TaskTraceDetails from './TaskTraceDetails.vue'
import TaskTraceTimeline from './TaskTraceTimeline.vue'
import { knownCount } from '@/utils/countPresentation'
import { beijingDateTime } from '@/utils/beijingTime'
import { buildTraceEvidenceRows } from '@/utils/qualityRecords'
import { evidencePreviewUrl } from '@/utils/evidencePresentation'
const props = defineProps({ detail: Object, loading: Boolean, error: String })
defineEmits(['refresh'])
const root = ref(null), navigation = ref(null), targets = {}
const sections = [{ key: 'overview', label: '任务概览', icon: 'Tickets' }, { key: 'images', label: '图片对照', icon: 'Picture' }, { key: 'records', label: '任务记录', icon: 'DocumentChecked' }, { key: 'timeline', label: '流程节点', icon: 'Clock' }]
const count = value => knownCount(value)?.toLocaleString('zh-CN') ?? '—'
const time = value => value ? beijingDateTime(value) || '时间格式未知' : '未记录'
const fileRows = computed(() => buildTraceEvidenceRows(props.detail))
const previewUrl = evidencePreviewUrl
const resultLink = computed(() => evidencePreviewUrl({ previewUrl: props.detail?.resultJsonUrl }))
function go(key, smooth = true) {
  const target = targets[key], body = root.value?.closest('.el-dialog__body')
  if (!target || !body) return
  const top = Math.max(0, body.scrollTop + target.getBoundingClientRect().top - body.getBoundingClientRect().top - (navigation.value?.offsetHeight || 0) - 16)
  target.focus({ preventScroll: true })
  body.scrollTo({ top, behavior: smooth && !window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'smooth' : 'auto' })
}
defineExpose({ showOverview: () => go('overview', false), resetScroll: () => root.value?.closest('.el-dialog__body')?.scrollTo({ top: 0, behavior: 'auto' }) })
</script>
<style scoped>
.task-trace-panel { min-height: 180px; min-width: 0; color: var(--app-text, #0f172a); }
.task-trace-heading { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 16px; }
.task-trace-heading > div { min-width: 0; }
.task-trace-symbol { display: grid; place-items: center; flex: 0 0 42px; width: 42px; height: 42px; border-radius: 10px; background: var(--app-primary-soft, #eff6ff); color: var(--app-primary, #2563eb); }
.task-trace-heading h3 { margin: 0; font-size: 17px; font-weight: 650; line-height: 1.7; overflow-wrap: anywhere; }
.task-trace-heading p { margin: 5px 0 0; font-size: 12px; line-height: 1.85; color: var(--app-text-secondary, #475569); }
.task-trace-read-note { margin: 12px 0; padding: 10px 12px; border-left: 3px solid var(--app-primary, #2563eb); background: var(--app-primary-soft, #eff6ff); font-size: 12px; line-height: 1.8; color: var(--app-text-secondary, #475569); }
.task-trace-navigation { position: sticky; top: 0; z-index: 2; display: flex; flex-wrap: wrap; gap: 6px; margin-block: 16px; padding-block: 9px; border-block: 1px solid var(--app-border, #e2e8f0); background: #fff; }
.task-trace-navigation button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 34px; padding: 6px 10px; border: 0; border-radius: 6px; color: var(--app-text-secondary, #475569); background: transparent; font: inherit; font-size: 12px; cursor: pointer; transition: color 180ms ease, background-color 180ms ease; }
.task-trace-navigation button:hover { color: var(--app-primary, #2563eb); background: var(--app-primary-soft, #eff6ff); }
.task-trace-responsibility { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 16px 0 0; }
.task-trace-responsibility > div { min-width: 0; }
.task-trace-responsibility dt { font-size: 12px; line-height: 1.8; color: var(--app-text-secondary, #475569); }
.task-trace-responsibility dd { margin: 5px 0 0; font-size: 13px; line-height: 1.8; overflow-wrap: anywhere; }
.task-trace-version { margin: 10px 0; font-size: 12px; line-height: 1.8; color: var(--app-text-secondary, #475569); }
.task-trace-assignment-note { display: grid; gap: 5px; margin-block: 14px; padding-left: 12px; border-left: 2px solid var(--app-border, #e2e8f0); white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; line-height: 1.85; color: var(--app-text-secondary, #475569); }
.task-trace-assignment-note strong { font-weight: 550; color: var(--app-text, #0f172a); }
.task-trace-image-counts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 18px 0 20px; padding-block: 18px; border-block: 1px solid var(--app-border, #e2e8f0); }
.task-trace-image-counts dt { font-size: 12px; line-height: 1.8; color: var(--app-text-secondary, #475569); }
.task-trace-image-counts dd { margin: 7px 0 0; font-size: 24px; font-weight: 650; line-height: 1.4; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.task-trace-image-counts [data-error="true"] { color: var(--app-danger, #b91c1c); }
.task-trace-disclosure { border-block-start: 1px solid var(--app-border, #e2e8f0); padding-block: 14px; }
.task-trace-disclosure > summary { display: flex; align-items: center; gap: 7px; list-style: none; color: var(--app-text-secondary, #475569); font-size: 12px; line-height: 1.8; cursor: pointer; }
.task-trace-disclosure > summary::-webkit-details-marker { display: none; }
.task-trace-disclosure > summary > small { font-size: 12px; margin-left: auto; }
.task-trace-disclosure > summary > .task-trace-chevron { margin-left: auto; transition: transform 180ms ease; color: var(--app-primary, #2563eb); }
.task-trace-disclosure[open] > summary > .task-trace-chevron { transform: rotate(180deg); }
.task-trace-storage { display: grid; gap: 14px; margin: 16px 0 0; }
.task-trace-storage > div { display: grid; grid-template-columns: 100px minmax(0, 1fr); gap: 12px; }
.task-trace-storage dt { font-size: 12px; line-height: 1.8; color: var(--app-text-secondary, #475569); }
.task-trace-storage dd { margin: 0; min-width: 0; font-size: 12px; line-height: 1.85; }
.task-trace-panel code { font-size: 12px; line-height: 1.8; white-space: normal; overflow-wrap: anywhere; }
.task-trace-panel a { display: inline-flex; align-items: baseline; gap: 5px; color: var(--app-primary, #2563eb); text-underline-offset: 3px; overflow-wrap: anywhere; }
.task-trace-panel a:hover { text-decoration: underline; }
.task-trace-files-note { margin: 14px 0; font-size: 12px; line-height: 1.8; color: var(--app-text-secondary, #475569); }
.task-trace-files { min-width: 0; overflow: auto; border-block: 1px solid var(--app-border, #e2e8f0); }
.task-trace-files :deep(.cell) { line-height: 1.8; overflow-wrap: anywhere; }
.task-trace-panel :is(button, summary, a, section[tabindex]):focus-visible { outline: 2px solid var(--app-primary, #2563eb); outline-offset: 3px; }
@media (max-width: 580px) { .task-trace-responsibility { grid-template-columns: minmax(0, 1fr); } .task-trace-storage > div { grid-template-columns: minmax(0, 1fr); gap: 4px; } .task-trace-navigation button { flex: 1 1 auto; min-height: 36px; } .task-trace-image-counts dd { font-size: 21px; } }
@media (prefers-reduced-motion: reduce) { .task-trace-navigation button, .task-trace-chevron { transition: none; } }
</style>
