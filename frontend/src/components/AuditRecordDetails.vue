<template>
  <section v-if="record" class="audit-record-details">
    <div class="audit-detail-summary"><span class="audit-detail-icon"><AppIcon :name="delivery?'Download':'DocumentChecked'" :size="23" /></span><div><strong>{{ auditDomainLabel(record.domain) }}</strong><p>{{ delivery?'文件响应记录':'业务变更记录' }} · {{ auditScopeLabel(record.scope) }}</p></div><StatusBadge :domain="delivery?'delivery':'audit'" :code="delivery?record.state:record.result" /></div>
    <p v-if="delivery" class="audit-detail-guidance" role="note">{{ deliveryStateHint(record.state) }}</p>
    <p v-else class="audit-detail-guidance">审计反映登记时的操作结果；资源后续可能已变化，请到原业务页面核对当前状态。</p>
    <div class="record-details">
      <section v-for="group in groups" :key="group.id" class="record-details-group" :aria-label="group.label">
        <h3 class="record-details-heading"><AppIcon :name="group.icon" :size="15" />{{ group.label }}</h3>
        <RecordedFactList :fields="group.fields" />
      </section>
      <details class="record-details-identifiers">
        <summary><AppIcon name="DocumentCopy" :size="15" /><span>{{ delivery ? '核对响应、文件与请求编号' : '核对审计与请求编号' }}</span><AppIcon class="record-details-chevron" name="ArrowDown" :size="13" /></summary>
        <RecordedFactList :fields="identifiers" />
      </details>
    </div>
    <details v-if="delivery" class="audit-byte-explanation"><summary>如何理解写出字节</summary><p>字节数是服务端已返回的写调用计数下界，不是浏览器接收字节或流量账单。206 响应可能为部分或多段内容，计数可能包含多段边界及错误响应，不能当作文件净字节。</p></details>
    <p class="audit-snapshot-note">以上来自已加载列表的快照，未重新读取业务资源，不包含文件正文或私有地址。</p>
    <router-link v-if="auditPageLink(record.domain)" :to="auditPageLink(record.domain)" class="audit-source-link"><AppIcon name="ArrowRight" :size="15" />打开对应业务列表</router-link>
  </section>
</template>
<script setup>
import {computed} from 'vue'
import {auditDomainLabel,auditScopeLabel,auditTime,auditValue,deliveryBytes,deliveryExpectedBytes,deliveryStateHint,auditPageLink} from '@/utils/auditPresentation'
import RecordedFactList from './RecordedFactList.vue'
import '@/assets/record-details.css'
const props=defineProps({record:Object,delivery:Boolean})
const fields=entries=>entries.map(([label,value])=>({label,value:auditValue(value)}))
const groups=computed(()=>{
  const row=props.record||{}
  return props.delivery ? [
    {id:'response',label:'响应与资源',icon:'Download',fields:fields([
      ['账号 ID',row.actor_user_id],['资源编号',row.resource_id],['资源版本',row.resource_version],['交付修订',row.revision],['HTTP 状态',row.http_status]
    ])},
    {id:'transfer',label:'服务端写出记录',icon:'Document',fields:fields([
      ['写调用记录下界',deliveryBytes(row)],['预计内容大小',deliveryExpectedBytes(row)],['创建时间 · UTC+8',auditTime(row.created_at)],['更新时间 · UTC+8',auditTime(row.updated_at)]
    ])}
  ] : [
    {id:'resource',label:'登记与资源',icon:'Document',fields:fields([
      ['账号 ID',row.actor_user_id],['资源编号',row.resource_id],['资源版本',row.resource_version],['记录时间 · UTC+8',auditTime(row.created_at)]
    ])},
    {id:'action',label:'动作信息',icon:'Operation',fields:fields([
      ['业务域代码',row.domain],['动作代码',row.action]
    ])}
  ]
})
const identifiers=computed(()=>{
  const row=props.record||{}
  return fields(props.delivery?
    [['响应编号',row.delivery_id],['文件编号',row.file_id],['请求编号',row.correlation_id]]:
    [['审计编号',row.id],['请求编号',row.request_id]])
    .map(field=>({...field,identifier:true}))
})
</script>
<style scoped>
.audit-detail-summary { display:flex; align-items:flex-start; flex-wrap:wrap; gap:12px; padding-bottom:18px; border-bottom:1px solid var(--app-border); }
.audit-detail-icon { display:grid; place-items:center; width:42px; height:42px; flex:none; border-radius:11px; background:var(--app-primary-soft); color:var(--app-primary); }
.audit-detail-summary > div { flex:1; min-width:min(150px,100%); }
.audit-detail-summary strong { font-size:16px; color:var(--app-text); overflow-wrap:anywhere; }
.audit-detail-summary p { margin:6px 0 0; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.audit-detail-guidance { padding:12px 14px; border-left:3px solid var(--app-border-focus); border-radius:0 7px 7px 0; background:var(--app-primary-light); color:var(--app-text-secondary); font-size:13px; line-height:1.9; }
.audit-byte-explanation { margin-top:16px; padding-top:14px; border-top:1px solid var(--app-border); color:var(--app-text-secondary); font-size:12px; line-height:1.9; }
.audit-byte-explanation summary { width:fit-content; cursor:pointer; }
.audit-snapshot-note { margin-top:20px; color:var(--app-text-secondary); font-size:12px; line-height:1.9; }
.audit-source-link { display:inline-flex; align-items:center; gap:6px; min-height:34px; padding:6px 0; color:var(--app-primary); font-size:13px; text-decoration:none; transition:color 180ms ease; }
.audit-source-link:hover { color:var(--app-primary-hover); text-decoration:underline; }
.audit-source-link:focus-visible,.audit-byte-explanation summary:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
@media(prefers-reduced-motion:reduce) { .audit-source-link { transition:none; } }
</style>
