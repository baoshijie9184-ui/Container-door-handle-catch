<template>
  <section class="business-trace-query" :aria-label="kindLabel + '追溯查询'" :aria-busy="loading">
    <p class="business-trace-scope"><AppIcon name="Lock" :size="15" />{{ scopeLabel }} · 按完整{{ kindLabel }}编号读取关联任务</p>
    <form @submit.prevent="$emit('query')"><label :for="inputId">{{ kindLabel }}编号</label><div class="business-trace-input"><el-input :id="inputId" :model-value="modelValue" clearable :placeholder="'输入完整' + kindLabel + '编号'" :aria-label="'完整' + kindLabel + '编号'" @update:model-value="$emit('update:modelValue', $event)"><template #prefix><AppIcon name="Search" :size="16" /></template></el-input><el-button type="primary" native-type="submit" :loading="loading" :disabled="!modelValue.trim()"><AppIcon name="Search" :size="15" />查询{{ kindLabel }}</el-button></div></form>
    <div v-if="referenceNo" class="business-trace-result-scope"><div><span>{{ loading || error ? '上次已读结果' : '本次已读结果' }}</span><strong>{{ referenceNo }}</strong></div><el-button size="small" :loading="loading" @click="$emit('refresh')"><AppIcon name="Refresh" :size="14" />重新读取此结果</el-button></div>
    <p v-if="dirty" class="business-trace-draft-note" role="status">输入已修改，当前摘要仍属于{{ kindLabel }} {{ referenceNo }}。{{ loading ? '当前查询结束后，可查询新编号。' : '点击查询读取新编号。' }}<button type="button" @click="$emit('update:modelValue', referenceNo)">恢复已读编号</button></p>
    <p v-if="loading" class="business-trace-reading" role="status">正在读取{{ kindLabel }} {{ requestedNo || '编号未记录' }}。{{ report ? '当前保留上次摘要，不把旧数据当作本次查询已成功。' : '修改输入不会改变已经发出的查询。' }}</p>
    <el-alert v-if="error && report" :title="error" description="当前仍为上次已读摘要。可重新读取原结果，或按输入编号查询。" type="warning" :closable="false" show-icon />
    <p v-if="referenceLoading" class="business-trace-reading" role="status">正在读取最近任务中的{{ kindLabel }}编号</p>
    <p v-if="referenceError" class="business-trace-reading" role="status">{{ referenceError }}<button type="button" :disabled="referenceLoading" @click="$emit('refresh-references')">重新读取编号</button></p>
    <details v-if="references.length" class="business-trace-examples"><summary>最近任务中的{{ kindLabel }}</summary><p>来自当前账号最近 50 条检测任务，选择编号查看关联记录。</p><div><el-button v-for="reference in references" :key="reference" size="small" :disabled="loading" @click="$emit('reference', reference)">{{ reference }}</el-button></div></details>
    <CollectionEmptyState v-if="!report" :loading="loading" :error="error" :empty-title="'输入' + kindLabel + '编号查看追溯'" empty-description="这里只读取当前账号有权查看的关联业务；查无结果时请核对编号与权限范围。" @retry="$emit('query')" />
  </section>
</template>
<script setup>
import { computed, getCurrentInstance } from 'vue'
import AppIcon from './AppIcon.vue'
import CollectionEmptyState from './CollectionEmptyState.vue'
const props = defineProps({ modelValue: { type: String, default: '' }, kind: String, requestedNo: String, loading: Boolean, report: Object, error: String, references: { type: Array, default: () => [] }, referenceLoading: Boolean, referenceError: String, scopeLabel: { type: String, default: '当前账号有权查看的业务范围' } })
defineEmits(['update:modelValue', 'query', 'refresh', 'reference', 'refresh-references'])
const inputId = `business-trace-query-${getCurrentInstance().uid}`
const kindLabel = computed(() => props.kind === 'work-order' ? '工单' : '批次')
const referenceNo = computed(() => props.report?.[props.kind === 'work-order' ? 'workOrderNo' : 'batchNo'] || '')
const dirty = computed(() => !!referenceNo.value && props.modelValue.trim() !== referenceNo.value)
</script>
<style scoped>
.business-trace-query { min-width: 0; }
.business-trace-scope { display: flex; align-items: flex-start; gap: 7px; margin: 0 0 18px; color: var(--app-text-secondary, #475569); font-size: 12px; line-height: 1.8; }
.business-trace-scope > .el-icon { color: var(--app-primary, #2563eb); flex-shrink: 0; margin-top: 3px; }
.business-trace-query label { display: block; margin-bottom: 8px; color: var(--app-text, #0f172a); font-size: 13px; font-weight: 550; line-height: 1.7; }
.business-trace-input { display: flex; align-items: stretch; gap: 10px; }
.business-trace-input .el-input { flex: 1; min-width: 0; }
.business-trace-input > button { min-height: 38px; }
.business-trace-result-scope { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-top: 18px; padding-block: 14px; border-block: 1px solid var(--app-border, #e2e8f0); }
.business-trace-result-scope > div { display: grid; gap: 4px; min-width: 0; }
.business-trace-result-scope span { font-size: 12px; line-height: 1.8; color: var(--app-text-secondary, #475569); }
.business-trace-result-scope strong { color: var(--app-text, #0f172a); font-size: 14px; font-weight: 600; line-height: 1.8; overflow-wrap: anywhere; }
.business-trace-draft-note, .business-trace-reading { margin: 12px 0; padding: 10px 12px; border-left: 3px solid var(--app-primary, #2563eb); color: var(--app-text-secondary, #475569); background: var(--app-primary-soft, #eff6ff); font-size: 12px; line-height: 1.85; overflow-wrap: anywhere; }
.business-trace-draft-note button { border: 0; border-radius: 3px; background: transparent; color: var(--app-primary, #2563eb); padding: 0 4px; font: inherit; cursor: pointer; text-decoration: underline; text-underline-offset: 3px; }
.business-trace-reading button { margin-left: 8px; border: 0; background: transparent; padding: 0; color: var(--app-primary); font: inherit; cursor: pointer; text-decoration: underline; text-underline-offset: 3px; }
.business-trace-examples { margin: 16px 0 20px; }
.business-trace-examples > summary { width: fit-content; color: var(--app-text-secondary, #475569); font-size: 12px; line-height: 1.8; cursor: pointer; }
.business-trace-examples p { max-width: 80ch; margin: 10px 0; color: var(--app-text-secondary, #475569); font-size: 12px; line-height: 1.85; }
.business-trace-examples > div { display: flex; flex-wrap: wrap; gap: 8px; }
.business-trace-examples .el-button + .el-button { margin-left: 0; }
.business-trace-query > .el-alert { margin-block: 14px; }
.business-trace-query :is(button, summary):focus-visible { outline: 2px solid var(--app-primary, #2563eb); outline-offset: 3px; }
.business-trace-query :deep(.el-input__wrapper:focus-within) { outline: 2px solid var(--app-primary, #2563eb); outline-offset: 2px; }
@media (max-width: 580px) { .business-trace-input { flex-wrap: wrap; } .business-trace-input .el-input { flex-basis: 100%; } .business-trace-input > button { min-height: 36px; } }
</style>
