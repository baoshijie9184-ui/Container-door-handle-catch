<template>
  <div class="config-value">
    <p v-if="rows === null && ['models','fallbackModels'].includes(field)" class="config-value-empty">列表未记录</p>
    <p v-else-if="Array.isArray(rows) && !rows.length" class="config-value-empty">{{ field==='models' ? '列表为空' : '未配置备用模型' }}</p>
    <div v-else-if="Array.isArray(rows)" class="config-value-reading" :class="{'is-scrollable':rows.length>5}" :tabindex="rows.length>5 ? 0 : undefined" :role="rows.length>5 ? 'region' : undefined" :aria-label="label">
      <ul v-if="field==='models'" class="config-value-models"><li v-for="(row,index) in rows" :key="index"><span>{{ row.id || '模型编号未记录' }}</span><StatusBadge domain="switchState" :code="row.enabled===true?'ENABLED':row.enabled===false?'DISABLED':'UNKNOWN'" :label="row.enabled===true?'登记启用':row.enabled===false?'登记停用':'状态未记录'" /></li></ul>
      <ol v-else class="config-value-order"><li v-for="(id,index) in rows" :key="index">{{ id || '模型编号未记录' }}</li></ol>
    </div>
    <p v-else class="config-value-scalar">{{ modelConfigScalar(field,value) }}</p>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { modelConfigValue, modelConfigScalar } from '@/utils/modelConfigPresentation'
const props=defineProps({field:{type:String,required:true},value:null,label:{type:String,default:'模型策略值'}})
const rows=computed(()=>['models','fallbackModels'].includes(props.field)?modelConfigValue(props.field,props.value):undefined)
</script>
<style scoped>
.config-value{min-width:0;color:var(--app-text);font-size:13px;line-height:1.85}
.config-value :is(.config-value-scalar,.config-value-empty){margin:0;overflow-wrap:anywhere;white-space:pre-wrap}
.config-value-empty{color:var(--app-text-secondary)}
.config-value-reading{border-radius:4px;min-width:0}
.config-value-reading.is-scrollable{max-height:240px;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable;padding-right:6px}
.config-value-models{list-style:none;padding:0;margin:0}
.config-value-models>li{display:flex;align-items:flex-start;justify-content:space-between;gap:8px 12px;flex-wrap:wrap;padding:8px 0;border-bottom:1px solid var(--app-border)}
.config-value-models>li:first-child{padding-top:0}
.config-value-models>li:last-child{border-bottom:0}
.config-value-models>li>span:first-child{min-width:0;flex:1 1 130px;overflow-wrap:anywhere}
.config-value-order{margin:0;padding:0 0 0 25px}
.config-value-order>li{padding:4px 0 4px 3px;overflow-wrap:anywhere}
.config-value-order>li::marker{color:var(--app-primary);font-variant-numeric:tabular-nums}
.config-value-reading:focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}
</style>
