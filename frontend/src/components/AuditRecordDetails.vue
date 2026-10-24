<template>
  <section v-if="record" class="audit-record-details">
    <div class="audit-detail-summary"><span class="audit-detail-icon"><AppIcon :name="delivery?'Download':'DocumentChecked'" :size="23" /></span><div><strong>{{ auditDomainLabel(record.domain) }}</strong><p>{{ delivery?'文件响应记录':'业务变更记录' }} · {{ auditScopeLabel(record.scope) }}</p></div><StatusBadge :domain="delivery?'delivery':'audit'" :code="delivery?record.state:record.result" /></div>
    <p v-if="delivery" class="audit-detail-guidance" role="note">{{ deliveryStateHint(record.state) }}</p>
    <p v-else class="audit-detail-guidance">审计反映登记时的操作结果；资源后续可能已变化，请到原业务页面核对当前状态。</p>
    <dl class="audit-facts"><template v-for="field in facts" :key="field.label"><dt>{{ field.label }}</dt><dd>{{ field.value }}</dd></template></dl>
    <details v-if="delivery" class="audit-byte-explanation"><summary>如何理解写出字节</summary><p>字节数是服务端已返回的写调用计数下界，不是浏览器接收字节或流量账单。206 响应可能为部分或多段内容，计数可能包含多段边界及错误响应，不能当作文件净字节。</p></details>
    <p class="audit-snapshot-note">以上来自已加载列表的快照，未重新读取业务资源，不包含文件正文或私有地址。</p>
    <router-link v-if="auditPageLink(record.domain)" :to="auditPageLink(record.domain)" class="audit-source-link"><AppIcon name="ArrowRight" :size="15" />打开对应业务列表</router-link>
  </section>
</template>
<script setup>
import {computed} from 'vue'
import {auditDomainLabel,auditScopeLabel,auditTime,auditValue,deliveryBytes,deliveryExpectedBytes,deliveryStateHint,auditPageLink} from '@/utils/auditPresentation'
const props=defineProps({record:Object,delivery:Boolean})
const facts=computed(()=>{
 const row=props.record||{}
 const entries=props.delivery?
  [['响应编号',row.delivery_id],['账号 ID',row.actor_user_id],['资源编号',row.resource_id],['文件编号',row.file_id],['请求编号',row.correlation_id],['资源版本',row.resource_version],['交付修订',row.revision],['写调用记录下界',deliveryBytes(row)],['预计内容大小',deliveryExpectedBytes(row)],['HTTP 状态',row.http_status],['创建时间 · UTC+8',auditTime(row.created_at)],['更新时间 · UTC+8',auditTime(row.updated_at)]]:
  [['审计编号',row.id],['账号 ID',row.actor_user_id],['业务域代码',row.domain],['动作代码',row.action],['资源编号',row.resource_id],['资源版本',row.resource_version],['请求编号',row.request_id],['记录时间 · UTC+8',auditTime(row.created_at)]]
 return entries.map(([label,value])=>({label,value:auditValue(value)}))
})
</script>
<style scoped>
.audit-detail-summary{display:flex;align-items:flex-start;flex-wrap:wrap;gap:12px;padding-bottom:18px;border-bottom:1px solid var(--app-border)}.audit-detail-icon{width:42px;height:42px;border-radius:11px;background:var(--app-primary-soft);color:var(--app-primary);display:grid;place-items:center;flex:0 0 auto}.audit-detail-summary>div{flex:1;min-width:150px}.audit-detail-summary strong{font-size:16px;color:var(--app-text);overflow-wrap:anywhere}.audit-detail-summary p{font-size:12px;color:var(--app-text-secondary);margin:6px 0 0}.audit-detail-guidance{padding:12px 14px;border-left:3px solid #aec8f8;background:var(--app-primary-light);border-radius:0 7px 7px 0;color:var(--app-text-secondary);font-size:13px;line-height:1.9}.audit-facts{display:grid;grid-template-columns:130px minmax(0,1fr);gap:12px 18px;margin:20px 0;font-size:13px;line-height:1.85}.audit-facts dt{color:var(--app-text-secondary)}.audit-facts dd{min-width:0;margin:0;color:var(--app-text);overflow-wrap:anywhere;user-select:text}.audit-byte-explanation{padding-top:14px;border-top:1px solid var(--app-border);font-size:12px;line-height:1.9;color:var(--app-text-secondary)}.audit-byte-explanation summary{cursor:pointer;width:fit-content}.audit-snapshot-note{font-size:12px;line-height:1.9;color:var(--app-text-muted);margin-top:20px}.audit-source-link{display:inline-flex;gap:6px;align-items:center;color:var(--app-primary);font-size:13px;text-decoration:none;padding:6px 0}.audit-source-link:hover{text-decoration:underline}.audit-source-link:focus-visible,.audit-byte-explanation summary:focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}@media(max-width:540px){.audit-facts{grid-template-columns:1fr;gap:3px}.audit-facts dd{margin-bottom:10px}}
</style>
