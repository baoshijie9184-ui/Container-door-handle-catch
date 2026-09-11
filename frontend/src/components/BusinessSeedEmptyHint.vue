<template>
  <div class="business-seed-empty-hint">
    <p class="business-seed-empty-hint__title">{{ title }}</p>
    <p class="business-seed-empty-hint__desc">
      {{ description }}
    </p>
    <code>APP_BUSINESS_SEED_ENABLED=true</code>
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
    default: '如果是首次准备 demo/验收环境，可在后端启动前开启业务预置数据导入。'
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
  max-width: 520px;
  color: #64748b;
  line-height: 1.6;
}

.business-seed-empty-hint__title {
  margin: 0;
  color: #334155;
  font-weight: 700;
}

.business-seed-empty-hint__desc {
  margin: 0;
}

.business-seed-empty-hint code {
  padding: 4px 9px;
  border: 1px solid rgba(14, 165, 233, 0.22);
  border-radius: 999px;
  background: rgba(14, 165, 233, 0.08);
  color: #0369a1;
  font-size: 12px;
}

.business-seed-empty-hint__link {
  color: #0f766e;
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
}

.business-seed-empty-hint__link:hover {
  color: #115e59;
  text-decoration: underline;
}
</style>
