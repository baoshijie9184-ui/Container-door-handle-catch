<template>
  <div class="business-seed-empty-hint">
    <span class="empty-hint-symbol"><AppIcon name="Files" :size="25" /></span>
    <p class="business-seed-empty-hint__title">{{ title }}</p>
    <p class="business-seed-empty-hint__desc">
      {{ description }}
    </p>
    <router-link v-if="manualLink" to="/manual" class="business-seed-empty-hint__link">
      查看使用手册
    </router-link>
  </div>
</template>

<script setup>
defineProps({
  title: {
    type: String,
    default: '没有查询到业务数据'
  },
  description: {
    type: String,
    default: '当前范围暂无记录。可以调整筛选条件，或创建新的业务记录后刷新。'
  },
  manualLink: {
    type: Boolean,
    default: true
  }
})
</script>

<style scoped>
.business-seed-empty-hint {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  max-width: 480px;
  padding: 24px 16px;
  text-align: center;
  color: #64748b;
  line-height: 1.6;
}
.empty-hint-symbol { display: grid; place-items: center; width: 52px; height: 52px; border-radius: 14px; background: var(--app-primary-soft); color: var(--app-primary); margin-bottom: 8px; }

.business-seed-empty-hint__title {
  margin: 0;
  color: #334155;
  font-weight: 700;
}

.business-seed-empty-hint__desc {
  margin: 0;
}

.business-seed-empty-hint__link {
  color: var(--app-primary);
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
}

.business-seed-empty-hint__link:hover {
  color: var(--app-primary-hover);
  text-decoration: underline;
}
</style>
