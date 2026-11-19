<template>
  <section v-if="summary?.groups?.length" class="maintenance-summary" aria-label="模型维修建议">
    <header><h4>模型维修建议</h4><small>按检测目标计数</small></header>
    <dl>
      <div v-for="group in summary.groups" :key="group.code" :data-action="group.code">
        <dt>{{ group.label }}</dt>
        <dd><strong>{{ format(group.targetCount) }}</strong> 个</dd>
        <dd class="categories"><span v-for="item in group.categories" :key="item.code">{{ item.label }} {{ format(item.targetCount) }}</span></dd>
      </div>
    </dl>
    <p v-if="summary.groups.some(group => group.targetCount == null)">— 表示分类计数未完整记录。</p>
    <p v-if="summary.unmappedCategories?.length">未配置维修方式的类别：{{ summary.unmappedCategories.join('、') }}</p>
  </section>
</template>
<script setup>
defineProps({summary:Object})
const format = count => count == null ? '—' : Number(count).toLocaleString('zh-CN')
</script>
<style scoped>
.maintenance-summary { margin:12px 0 18px; color:var(--app-text); }
.maintenance-summary header { display:flex; gap:10px; align-items:baseline; margin-bottom:9px; }
.maintenance-summary h4 { margin:0; font-size:15px; }
.maintenance-summary small,.maintenance-summary p { color:var(--app-text-secondary); font-size:12px; }
.maintenance-summary dl { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(140px,100%),1fr)); gap:6px; margin:0; }
.maintenance-summary dl>div { border:1px solid var(--app-border); background:var(--app-surface-muted); border-radius:8px; padding:8px 10px; }
.maintenance-summary dt { font-size:13px; font-weight:600; }
.maintenance-summary dd { margin:2px 0 0; font-size:12px; }
.maintenance-summary strong { font-size:19px; font-variant-numeric:tabular-nums; }
.maintenance-summary [data-action=REPAIR] strong,.maintenance-summary [data-action=REPLACE] strong { color:var(--app-primary); }
.maintenance-summary .categories { display:flex; flex-wrap:wrap; gap:1px 8px; color:var(--app-text-secondary); }
</style>
