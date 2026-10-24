<template>
  <section class="collection-task-records" aria-label="已读取的采集任务">
    <div class="collection-records-tools">
      <label v-if="records.length > 6 || query" class="collection-records-search"><span>查找已读取记录</span><el-input v-model="query" clearable maxlength="200" placeholder="任务、名称、日期或地区" aria-label="查找已读取的采集任务，不查询服务器"><template #prefix><AppIcon name="Search" :size="16" /></template></el-input></label>
      <p class="collection-records-range" role="status">{{ trimmedQuery ? `匹配 ${visible.length} 条 / 已读取 ${records.length} 条` : `本次已读取 ${records.length} 条` }}<span>仅包含本页返回的记录，按原顺序显示。</span></p>
    </div>
    <div v-if="visible.length" class="collection-records-reading" :class="{ 'is-scrollable': visible.length > 5 }" :tabindex="visible.length > 5 ? 0 : undefined" :role="visible.length > 5 ? 'region' : undefined" aria-label="采集任务记录阅读区">
      <ol class="collection-records-list">
        <li v-for="item in visible" :key="item.key" class="collection-record">
          <article :aria-label="'采集任务 ' + item.record.taskId">
            <header class="collection-record-heading">
              <div><AppIcon name="Picture" :size="18" /><h4>{{ text(item.record.folderName) || item.record.taskId }}</h4></div>
              <StatusBadge domain="detection" :code="item.record.status" />
              <router-link class="collection-record-open" :aria-label="'查看任务 ' + item.record.taskId + ' 的检测记录'" :to="{path:'/inspection/history',query:{keyword:item.record.taskId}}"><AppIcon name="Search" :size="15" />查看检测记录</router-link>
            </header>
            <p class="collection-record-created">创建时间 {{ time(item.record.createdAt) }}<span v-if="hasTime(item.record.createdAt)"> · UTC+8</span></p>
            <dl class="collection-record-facts">
              <div><dt>采集日期</dt><dd>{{ text(item.record.captureDate) || '未记录' }}</dd></div>
              <div><dt>地区</dt><dd>{{ text(item.record.region) || '未记录' }}</dd></div>
              <div><dt>{{ counterpart === 'collector' ? '采集人登记' : '设备登记' }}</dt><dd>{{ text(counterpart === 'collector' ? item.record.collector : item.record.deviceName) || '未记录' }}</dd></div>
              <div><dt>任务登记图片数</dt><dd>{{ count(item.record.totalImages) }}</dd></div>
            </dl>
            <details class="collection-record-source"><summary>任务编号与存储登记</summary><dl><dt>任务编号</dt><dd>{{ item.record.taskId }}</dd><dt>存储登记</dt><dd>{{ text(item.record.sourceOssPrefix) || '本条未返回存储登记' }}</dd></dl><p>此处展示已读取的登记资料，图片与结果在检测记录中核对。</p></details>
          </article>
        </li>
      </ol>
    </div>
    <div v-else class="collection-records-no-match"><AppIcon name="Search" :size="20" /><p>{{ trimmedQuery ? '已读取的记录中没有匹配项' : '本次未返回采集记录' }}</p><el-button v-if="trimmedQuery" text type="primary" @click="query=''">清除筛选</el-button></div>
  </section>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import StatusBadge from './StatusBadge.vue'
import { beijingDateTime } from '@/utils/beijingTime'
import { knownCount } from '@/utils/countPresentation'
const props = defineProps({ records: { type: Array, required: true }, counterpart: { type: String, required: true }, contextKey: String })
const query = ref('')
const trimmedQuery = computed(() => query.value.trim().toLocaleLowerCase('zh-CN'))
const text = value => typeof value === 'string' ? value.trim() : ''
const time = value => text(value) ? beijingDateTime(value) || '时间格式待核对' : '未记录'
const hasTime = value => text(value) && !!beijingDateTime(value)
const count = value => { const number = knownCount(value); return number == null ? '数量未记录' : number.toLocaleString('zh-CN') + ' 张' }
const visible = computed(() => {
  const occurrences = new Map()
  return props.records.map(record => {
    const occurrence = occurrences.get(record.taskId) || 0
    occurrences.set(record.taskId, occurrence + 1)
    return { record, key: record.taskId + ':' + occurrence }
  }).filter(({record}) => !trimmedQuery.value || [record.taskId, record.folderName, record.captureDate, record.region, props.counterpart === 'collector' ? record.collector : record.deviceName].some(value => text(value).toLocaleLowerCase('zh-CN').includes(trimmedQuery.value)))
})
watch(() => props.contextKey, () => { query.value = '' }, { flush: 'sync' })
</script>
<style scoped>
.collection-task-records{min-width:0;color:var(--app-text)}
.collection-records-tools{display:flex;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;gap:12px 20px;margin:0 0 16px}
.collection-records-search{display:grid;gap:7px;flex:0 1 360px;max-width:100%;min-width:0;font-size:12px;line-height:1.8;color:var(--app-text-secondary)}
.collection-records-range{display:grid;gap:3px;margin:0;font-size:12px;line-height:1.85;color:var(--app-text-secondary)}
.collection-records-reading{border-radius:6px;min-width:0}
.collection-records-reading.is-scrollable{max-height:760px;max-height:min(760px,70dvh);overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable;padding-right:6px}
.collection-records-list{list-style:none;margin:0;padding:0}
.collection-record{padding:18px 2px;border-top:1px solid var(--app-border);min-width:0}
.collection-record-heading{display:flex;align-items:flex-start;flex-wrap:wrap;gap:8px 14px}
.collection-record-heading>div{display:flex;align-items:flex-start;gap:9px;min-width:0;flex:1 1 200px}
.collection-record-heading>div>.el-icon{flex:none;margin-top:3px;color:var(--app-primary)}
.collection-record-heading h4{margin:0;min-width:0;font-size:14px;line-height:1.8;font-weight:600;overflow-wrap:anywhere}
.collection-record-open{display:inline-flex;align-items:center;gap:6px;flex:none;color:var(--app-primary);font-size:12px;line-height:1.9;text-decoration:none;padding:2px 0}
.collection-record-open:hover{text-decoration:underline;text-underline-offset:3px}
.collection-record-created{margin:5px 0 14px 27px;color:var(--app-text-secondary);font-size:12px;line-height:1.85}
.collection-record-facts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px 20px;margin:0 0 12px 27px;font-size:13px;line-height:1.85}
.collection-record-facts>div{min-width:0}
.collection-record-facts dt,.collection-record-source dt{color:var(--app-text-secondary);font-size:12px}
.collection-record-facts dd{margin:3px 0 0;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.collection-record-source{margin-left:27px;font-size:12px;line-height:1.85}
.collection-record-source>summary{cursor:pointer;color:var(--app-text-secondary);width:fit-content;max-width:100%;border-radius:3px;transition:color 180ms ease}
.collection-record-source>summary:hover{color:var(--app-primary)}
.collection-record-source dl{display:grid;grid-template-columns:90px minmax(0,1fr);gap:8px 14px;margin:12px 0}
.collection-record-source dd{margin:0;overflow-wrap:anywhere;min-width:0;white-space:pre-wrap}
.collection-record-source p{margin:8px 0 0;color:var(--app-text-secondary);font-size:12px;line-height:1.85}
.collection-records-no-match{display:flex;align-items:center;justify-content:center;flex-wrap:wrap;gap:10px;padding:24px 12px;border-top:1px solid var(--app-border);color:var(--app-text-secondary);font-size:13px}
.collection-records-no-match>.el-icon{color:var(--app-primary)}
.collection-records-no-match p{margin:0;line-height:1.85}
.collection-task-records :is(.collection-records-reading,summary,a):focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}
@media(max-width:800px){.collection-record-facts{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:540px){.collection-records-search{flex-basis:100%}.collection-record-heading>div{flex-basis:100%}.collection-record-created,.collection-record-facts,.collection-record-source{margin-left:0}.collection-record-source dl{grid-template-columns:1fr;gap:3px}.collection-record-source dd{margin-bottom:7px}}
@media(prefers-reduced-motion:reduce){.collection-record-source>summary{transition:none}}
</style>
