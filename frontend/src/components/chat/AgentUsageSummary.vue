<template>
  <section class="wb-usage" aria-label="模型用量与上下文估算">
    <p class="wb-usage-purpose">{{ workbenchUsagePurpose(data.purpose) }}</p><p class="wb-usage-model">{{ data.modelId || '模型未记录' }}</p>
    <div class="wb-token-pair"><div><span>输入 Token</span><strong>{{ tokenDisplay(data.inputTokens) }}</strong></div><div><span>输出 Token</span><strong>{{ tokenDisplay(data.outputTokens) }}</strong></div></div>
    <p class="wb-note"><AppIcon :name="data.basis==='PROVIDER_REPORTED'?'DocumentChecked':'Warning'" :size="14" />{{ data.basis==='PROVIDER_REPORTED'?'供应商报告值，不推算费用':'供应商用量不完整或未知，不按零计算' }}</p>
    <dl class="wb-usage-timing"><dt>已记录模型耗时</dt><dd>{{ traceDuration(data.durationMs) }}</dd><dt>首段内容耗时</dt><dd>{{ traceDuration(data.firstContentMs) }}</dd></dl>
    <details class="wb-context-estimates"><summary>上下文构成估算（非账单）</summary><dl><dt>系统提示</dt><dd>{{ tokenDisplay(data.systemTokens) }}</dd><dt>工具定义</dt><dd>{{ tokenDisplay(data.toolsTokens) }}</dd><dt>历史消息</dt><dd>{{ tokenDisplay(data.messageTokens) }}</dd></dl><p class="wb-note">按已记录文本估算，不是供应商报告或上下文容量占比。缺失值保持未知。</p></details>
  </section>
</template>
<script setup>
import {tokenDisplay} from '@/utils/agentWorkbench'
import {traceDuration} from '@/utils/agentTrace'
import {workbenchUsagePurpose} from '@/utils/workbenchPresentation'
defineProps({data:{type:Object,required:true}})
</script>
