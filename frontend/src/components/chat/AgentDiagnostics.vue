<template>
  <el-dialog :model-value="modelValue" title="助手诊断" class="agent-diagnostics-dialog" width="min(720px, 94vw)" append-to-body @update:model-value="$emit('update:modelValue',$event)">
    <p v-if="loading" class="diagnostics-reading" role="status">正在读取服务配置与当前会话的执行记录</p>
    <section class="diagnostics-service agent-service-config" aria-label="当前服务配置" :aria-busy="loading">
      <h3><AppIcon name="Connection" :size="17" />当前服务配置</h3>
      <el-alert v-if="healthError" :title="healthError" type="error" show-icon :closable="false" />
      <template v-else-if="healthLoaded && health">
        <div class="diagnostics-mode"><StatusBadge domain="agentMode" :code="health.mode" /><span>{{ agentConfigText(health.framework,'框架未记录') }}</span></div>
        <dl class="diagnostics-model agent-service-facts"><div><dt>服务默认候选</dt><dd>{{ agentConfigText(health.defaultModel) }}</dd></div></dl>
        <p class="diagnostics-note">这是当前服务配置。某次任务的实际模型和备用切换以执行轨迹为准。</p>
        <details class="diagnostics-flags"><summary>查看记录与报告配置</summary><dl><div><dt>运行日志</dt><dd>{{ enabledLabel(health.runJournalEnabled) }}</dd></div><div><dt>报告能力</dt><dd>{{ enabledLabel(health.reportsEnabled) }}</dd></div><div><dt>报告草稿</dt><dd>{{ enabledLabel(health.reportDraftsEnabled) }}</dd></div></dl><p class="diagnostics-note">配置开启不代替账号权限、业务条件或人工确认，也不表示供应商当前可连通。</p></details>
      </template>
      <p v-else class="diagnostics-note">{{ loading ? '服务配置读取中…' : '服务配置尚未读取，可点击下方重新读取。' }}</p>
    </section>
    <AgentRecentExecution :session-id="sessionId" :trace="trace" :loaded="traceLoaded" :loading="loading" :error="traceError" @refresh="$emit('refresh')" @navigate="navigate" />
    <template #footer><el-button :loading="loading" @click="$emit('refresh')"><AppIcon name="Refresh" :size="15" />重新读取诊断</el-button><el-button @click="$emit('update:modelValue',false)">关闭诊断</el-button></template>
  </el-dialog>
</template>

<script setup>
import AgentRecentExecution from './AgentRecentExecution.vue'
import {agentConfigText,agentConfigFlag} from '@/utils/agentCatalogPresentation'
import '@/assets/agent-service-overview.css'
defineProps({ modelValue:Boolean, sessionId:String, health:Object, healthLoaded:Boolean, healthError:String, trace:Object, traceLoaded:Boolean, traceError:String, loading:Boolean })
const emit = defineEmits(['update:modelValue','refresh','navigate'])
const enabledLabel = agentConfigFlag
const navigate = () => { emit('update:modelValue',false); emit('navigate') }
</script>

<style>
.agent-diagnostics-dialog.el-dialog { display:flex; flex-direction:column; margin-top:5vh; margin-bottom:5vh; max-height:90vh; max-height:90dvh; }
.agent-diagnostics-dialog :is(.el-dialog__header,.el-dialog__footer) { flex-shrink:0; }
.agent-diagnostics-dialog .el-dialog__title { display:block; padding-right:28px; overflow-wrap:anywhere; }
.agent-diagnostics-dialog .el-dialog__body { min-height:0; max-height:65vh; max-height:65dvh; overflow-y:auto; overscroll-behavior:contain; }
.agent-diagnostics-dialog .el-dialog__footer { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:8px; }
.agent-diagnostics-dialog .el-dialog__footer .el-button + .el-button { margin-left:0; }
.agent-diagnostics-dialog .diagnostics-service { padding-bottom:20px; margin-bottom:22px; border-bottom:1px solid var(--app-border); }
.agent-diagnostics-dialog .diagnostics-service > h3 { display:flex; align-items:center; gap:8px; margin:0 0 16px; color:var(--app-text); font-size:14px; font-weight:600; }
.agent-diagnostics-dialog .diagnostics-service > h3 .el-icon { color:var(--app-primary); }
.agent-diagnostics-dialog .diagnostics-mode { display:flex; align-items:center; flex-wrap:wrap; gap:12px; color:var(--app-text-secondary); font-size:12px; }
.agent-diagnostics-dialog .diagnostics-model { display:grid;grid-template-columns:minmax(0,1fr); margin:18px 0 10px; }
.agent-diagnostics-dialog .diagnostics-model dt { color:var(--app-text-secondary); font-size:12px; }
.agent-diagnostics-dialog .diagnostics-model dd { margin:7px 0 0; color:var(--app-text); font-size:14px; line-height:1.8; font-weight:550; overflow-wrap:anywhere; }
.agent-diagnostics-dialog :is(.diagnostics-note,.diagnostics-reading) { color:var(--app-text-secondary); font-size:12px; line-height:1.85; margin:10px 0; }
.agent-diagnostics-dialog .diagnostics-flags { margin-top:16px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.agent-diagnostics-dialog .diagnostics-flags summary { cursor:pointer; width:fit-content; }
.agent-diagnostics-dialog .diagnostics-flags dl { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; margin:15px 0; }
.agent-diagnostics-dialog .diagnostics-flags dd { margin:5px 0 0; color:var(--app-text); }
.agent-diagnostics-dialog summary:focus-visible { outline:2px solid var(--app-primary); outline-offset:4px; border-radius:3px; }
@media(max-width:480px) { .agent-diagnostics-dialog .diagnostics-flags dl { grid-template-columns:minmax(0,1fr); gap:10px; } }
@media(prefers-reduced-motion:reduce) { .agent-diagnostics-dialog,.el-overlay:has(.agent-diagnostics-dialog) { animation:none!important; transition:none!important; } }
</style>
