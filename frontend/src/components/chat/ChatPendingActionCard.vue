<template>
  <div class="pending-card" aria-label="历史待确认操作记录">
    <div class="pending-header">
      <span class="pending-icon">
        <AppIcon name="Lock" :size="16" />
      </span>
      <span class="pending-label">历史待确认操作</span>
    </div>
    <div class="pending-content">{{ message.content }}</div>
    <p class="pending-note">此处保留旧版操作记录，不在聊天中执行。请到对应业务页面重新核对。</p>
    <div class="pending-actions">
      <button type="button" class="pending-btn confirm" disabled title="旧版操作不可在聊天中执行">
        <AppIcon name="Document" :size="14" />
        请到业务页面执行
      </button>
      <button type="button" class="pending-btn cancel" :disabled="busy || !message.actionId" @click="$emit('confirm', message.actionId, false)">
        <AppIcon name="Close" :size="14" />
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
  background: var(--app-warning-light);
  border: 1px solid #f3e1b9;
  border-radius: 12px;
  padding: 16px;
  box-shadow: none;
  animation: pending-in 0.2s ease-out both;
}

@keyframes pending-in {
  from { opacity: 0; transform: translateY(3px); }
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
.pending-note { margin: 10px 0 0; color: var(--app-warning); font-size: 12px; line-height: 1.8; }

.pending-actions {
  display: flex;
  flex-wrap: wrap;
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
  transition: background-color .15s, color .15s, transform .15s;
}

.pending-btn:disabled {
  cursor: not-allowed;
  opacity: 0.65;
  transform: none;
}

.pending-btn.confirm {
  background: var(--app-info-soft);
  color: var(--app-text-secondary);
  box-shadow: none;
}

.pending-btn.confirm:hover:not(:disabled) {
  box-shadow: 0 4px 14px rgba(47, 107, 255, 0.3);
  transform: translateY(-1px);
}

.pending-btn.cancel {
  background: #f1f5f9;
  color: #64748b;
}

.pending-btn.cancel:hover:not(:disabled) {
  background: #e2e8f0;
  color: #475569;
}
@media(prefers-reduced-motion: reduce) { .pending-card { animation: none; }.pending-btn { transition: none; transform: none; } }
</style>
