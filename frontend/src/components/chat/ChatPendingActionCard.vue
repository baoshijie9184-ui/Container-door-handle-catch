<template>
  <div class="pending-card">
    <div class="pending-header">
      <span class="pending-icon">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
      </span>
      <span class="pending-label">待确认操作</span>
    </div>
    <div class="pending-content">{{ message.content }}</div>
    <div class="pending-actions">
      <button class="pending-btn confirm" :disabled="busy" @click="$emit('confirm', message.actionId, true)">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
        {{ busy ? '执行中' : '确认执行' }}
      </button>
      <button class="pending-btn cancel" :disabled="busy" @click="$emit('confirm', message.actionId, false)">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
        取消
      </button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  message: { type: Object, required: true },
  busy: { type: Boolean, default: false }
})
</script>

<style scoped>
.pending-card {
  background: linear-gradient(135deg, #fffbeb 0%, #fefce8 100%);
  border: 1px solid rgba(251, 191, 36, 0.25);
  border-radius: 16px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(251, 191, 36, 0.06);
  animation: pending-in 0.3s cubic-bezier(0.4, 0, 0.2, 1) both;
}

@keyframes pending-in {
  from { opacity: 0; transform: scale(0.96); }
  to   { opacity: 1; transform: scale(1); }
}

.pending-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pending-icon {
  width: 28px;
  height: 28px;
  border-radius: 999px;
  background: rgba(251, 191, 36, 0.15);
  color: #d97706;
  display: flex;
  align-items: center;
  justify-content: center;
}

.pending-label {
  font-size: 13px;
  font-weight: 600;
  color: #92400e;
  letter-spacing: 0.03em;
}

.pending-content {
  margin-top: 12px;
  padding: 10px 14px;
  background: #fff;
  border-radius: 10px;
  color: #374151;
  font-size: 14px;
  line-height: 1.65;
  border: 1px solid rgba(0, 0, 0, 0.04);
}

.pending-actions {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}

.pending-btn {
  flex: 1;
  border: none;
  border-radius: 12px;
  padding: 10px 14px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: all 0.2s;
}

.pending-btn:disabled {
  cursor: not-allowed;
  opacity: 0.65;
  transform: none;
}

.pending-btn.confirm {
  background: linear-gradient(135deg, #4f6ef7, #3b5de7);
  color: #fff;
  box-shadow: 0 2px 8px rgba(47, 107, 255, 0.2);
}

.pending-btn.confirm:hover {
  box-shadow: 0 4px 14px rgba(47, 107, 255, 0.3);
  transform: translateY(-1px);
}

.pending-btn.cancel {
  background: #f1f5f9;
  color: #64748b;
}

.pending-btn.cancel:hover {
  background: #e2e8f0;
  color: #475569;
}
</style>
