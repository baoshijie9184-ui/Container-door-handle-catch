<template>
  <div class="agent-operation-history">
    <p class="operation-scope">{{ scopeNote }}<span v-if="rows">本次返回 {{ rows.length }} 条，按服务端顺序显示。</span></p>
    <p v-if="rows === null" class="operation-unavailable"><AppIcon name="Search" :size="16" />记录未完整返回，请重新读取页面核对。</p>
    <p v-else-if="!rows.length" class="operation-empty"><AppIcon name="DocumentCopy" :size="17" />本次未返回操作记录，不据此推断从未操作。</p>
    <div v-else class="operation-reading" :class="{ 'is-scrollable': rows.length > 6 }" :tabindex="rows.length > 6 ? 0 : undefined" :role="rows.length > 6 ? 'region' : undefined" :aria-label="label">
      <ol class="operation-list" :aria-label="label">
        <li v-for="row in rows" :key="row.key" class="operation-record">
          <div class="operation-title">
            <AppIcon name="Document" :size="16" />
            <strong :title="row.action || undefined">{{ row.actionLabel }}</strong>
            <StatusBadge v-if="kind === 'mcp'" domain="mcpAudit" :code="row.outcome" />
            <span v-if="kind === 'skill'" class="operation-version">版本 {{ row.version ?? '未记录' }}</span>
          </div>
          <time class="operation-time">{{ row.timeLabel }}</time>
          <p v-if="!row.complete" class="operation-unavailable">此条记录结构不完整，未推断动作或结果。</p>
          <p v-if="row.note" class="operation-note">{{ row.note }}</p>
          <details v-if="row.reason || row.fields.length || row.traceRunId" class="operation-details">
            <summary>操作说明与关联编号</summary>
            <p v-if="row.reason" class="operation-reason" tabindex="0" :aria-label="row.actionLabel + '的完整操作说明'">{{ row.reason }}</p>
            <dl v-if="row.fields.length"><template v-for="field in row.fields" :key="field.label"><dt>{{ field.label }}</dt><dd>{{ field.value }}</dd></template></dl>
            <router-link v-if="row.traceRunId" class="operation-trace" :to="{ path: '/agent/trace', query: { runId: row.traceRunId } }"><AppIcon name="Connection" :size="15" />查看本人运行轨迹</router-link>
          </details>
        </li>
      </ol>
    </div>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { operationHistoryRows } from '@/utils/operationHistoryPresentation'
const props = defineProps({
  records: { type: Array, default: null },
  kind: { type: String, required: true },
  label: { type: String, default: '操作记录' },
  scopeNote: { type: String, default: '' }
})
const rows = computed(() => operationHistoryRows(props.records, props.kind))
</script>
<style scoped>
.agent-operation-history{min-width:0;color:var(--app-text);font-size:13px}
.agent-operation-history .operation-scope{display:grid;gap:3px;margin:10px 0 14px;font-size:12px;line-height:1.85;color:var(--app-text-secondary);overflow-wrap:anywhere}
.agent-operation-history .operation-unavailable,.agent-operation-history .operation-empty{display:flex;align-items:flex-start;gap:8px;margin:12px 0;line-height:1.85;color:var(--app-text-secondary);font-size:13px}
.operation-unavailable>.el-icon,.operation-empty>.el-icon{flex:none;margin-top:4px;color:var(--app-primary)}
.operation-reading{min-width:0;border-radius:6px}
.operation-reading.is-scrollable{max-height:440px;max-height:min(440px,60dvh);overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable;padding-right:6px}
.operation-list{list-style:none;padding:0;margin:0}
.operation-record{padding:16px 2px;border-top:1px solid var(--app-border);min-width:0}
.operation-title{display:flex;align-items:center;flex-wrap:wrap;gap:7px 10px;line-height:1.8}
.operation-title>.el-icon{color:var(--app-primary);flex:none}
.operation-title>strong{font-weight:600;overflow-wrap:anywhere;font-size:13px}
.operation-version{font-size:12px;color:var(--app-text-secondary);background:var(--app-info-soft);padding:1px 7px;border-radius:5px}
.operation-time{display:block;font-size:12px;line-height:1.85;margin:4px 0 0 26px;color:var(--app-text-secondary)}
.agent-operation-history .operation-note{font-size:12px;color:var(--app-text-secondary);line-height:1.85;margin:7px 0 0 26px;max-width:72ch}
.operation-details{margin:8px 0 0 26px}
.operation-details>summary{width:fit-content;max-width:100%;cursor:pointer;color:var(--app-text-secondary);font-size:12px;line-height:1.9;border-radius:3px;transition:color 180ms ease}
.operation-details>summary:hover{color:var(--app-primary)}
.agent-operation-history .operation-reason{white-space:pre-wrap;overflow-wrap:anywhere;max-height:240px;overflow:auto;overscroll-behavior:contain;margin:10px 0;padding:10px 12px;border-left:2px solid var(--app-border);font-size:13px;line-height:1.9;color:var(--app-text)}
.operation-details dl{display:grid;grid-template-columns:110px minmax(0,1fr);gap:7px 12px;margin:12px 0;font-size:12px;line-height:1.85}
.operation-details dt{color:var(--app-text-secondary)}
.operation-details dd{margin:0;overflow-wrap:anywhere;min-width:0;color:var(--app-text)}
.operation-details .operation-trace{display:inline-flex;align-items:center;gap:7px;font-size:12px;line-height:1.9;padding:5px 0;margin:0;color:var(--app-primary);text-decoration:none}
.operation-trace:hover{text-decoration:underline}
.agent-operation-history :is(.operation-reading,summary,.operation-reason,a):focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}
@media(max-width:540px){.operation-time,.operation-details,.agent-operation-history .operation-note{margin-left:0}.operation-details dl{grid-template-columns:1fr;gap:2px}.operation-details dd{margin-bottom:7px}.operation-title{align-items:flex-start}}
@media(prefers-reduced-motion:reduce){.operation-details>summary{transition:none}}
</style>
