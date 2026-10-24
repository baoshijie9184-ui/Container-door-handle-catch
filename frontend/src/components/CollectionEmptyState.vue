<template>
  <section class="collection-empty" :aria-busy="loading" :role="error && !loading ? 'alert' : undefined">
    <span class="collection-empty-icon" :data-tone="error && !loading ? 'danger' : 'primary'"><AppIcon :name="loading ? 'Connection' : error ? 'Warning' : filtered ? 'Filter' : 'Files'" :size="25" /></span>
    <h3>{{ loading ? '正在读取记录' : error ? '记录暂不可读取' : filtered ? filteredTitle : emptyTitle }}</h3>
    <p v-if="loading" role="status">请稍候，加载完成后显示结果</p>
    <p v-else>{{ error || (filtered ? filteredDescription : emptyDescription) }}</p>
    <div v-if="!loading && (error || filtered)" class="collection-empty-actions">
      <el-button v-if="error" size="small" @click="$emit('retry')"><AppIcon name="Refresh" :size="15" />重新读取</el-button>
      <el-button v-if="filtered" size="small" :type="error ? 'default' : 'primary'" plain @click="$emit('reset')"><AppIcon name="Filter" :size="15" />清空筛选</el-button>
    </div>
  </section>
</template>

<script setup>
import AppIcon from './AppIcon.vue'
defineProps({
  loading: Boolean,
  error: { type: String, default: '' },
  filtered: Boolean,
  filteredTitle: { type: String, default: '没有匹配的记录' },
  filteredDescription: { type: String, default: '可以调整条件，或清空筛选后重新查看。' },
  emptyTitle: { type: String, default: '暂无记录' },
  emptyDescription: { type: String, default: '创建业务记录后，可在这里查看和处理。' }
})
defineEmits(['retry', 'reset'])
</script>

<style scoped>
.collection-empty { display: flex; flex-direction: column; align-items: center; gap: 9px; max-width: 480px; margin: auto; padding: 32px 18px; text-align: center; white-space: normal; line-height: 1.8; }
.collection-empty-icon { display: grid; place-items: center; width: 52px; height: 52px; margin-bottom: 4px; border: 1px solid #dce7fb; border-radius: 14px; color: var(--app-primary); background: var(--app-primary-soft); }
.collection-empty-icon[data-tone=danger] { color: var(--app-danger); border-color: #f5d5d9; background: var(--app-danger-soft); }
.collection-empty h3 { margin: 0; color: var(--app-text); font-size: 14px; font-weight: 650; }
.collection-empty p { margin: 0; color: var(--app-text-secondary); font-size: 12px; overflow-wrap: anywhere; }
.collection-empty-actions { display: flex; justify-content: center; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
.collection-empty-actions .el-button + .el-button { margin-left: 0; }
</style>
