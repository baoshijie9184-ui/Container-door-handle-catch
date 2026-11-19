<template>
  <span class="chat-menu" @keydown.esc.capture="dismiss">
    <el-dropdown ref="menu" trigger="click" :placement="placement" :teleported="false" @command="emit('command', $event)">
      <button ref="trigger" type="button" class="chat-menu-button" aria-label="更多对话操作" title="更多对话操作">
        <el-icon :size="17" aria-hidden="true"><MoreFilled /></el-icon>
        <span v-if="showLabel">更多操作</span>
      </button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item v-if="tasksEnabled" command="tasks"><AppIcon name="List" :size="15" />任务操作</el-dropdown-item>
          <el-dropdown-item command="trace"><AppIcon name="Connection" :size="15" />执行追溯</el-dropdown-item>
          <el-dropdown-item command="memory"><AppIcon name="Collection" :size="15" />个人记忆</el-dropdown-item>
          <el-dropdown-item command="diagnostics" :disabled="chat.diagnosticsLoading || !chat.sessionId"><AppIcon name="DataAnalysis" :size="15" />助手诊断</el-dropdown-item>
          <el-dropdown-item command="retry" :disabled="chat.loading"><AppIcon name="Refresh" :size="15" />重试最后一条消息</el-dropdown-item>
          <el-dropdown-item command="clear" class="chat-header-clear-item" divided :disabled="chat.loading"><AppIcon name="Delete" :size="15" />清空对话</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </span>
</template>

<script setup>
import { ref } from 'vue'
import { MoreFilled } from '@element-plus/icons-vue'
import { useChatAssistantStore } from '@/stores/chatAssistant'

defineProps({ tasksEnabled: Boolean, showLabel: Boolean, placement: { type: String, default: 'bottom-end' } })
const emit = defineEmits(['command'])
const chat = useChatAssistantStore()
const menu = ref(null)
const trigger = ref(null)
function dismiss(event) {
  if (trigger.value?.getAttribute('aria-expanded') !== 'true') return
  event.preventDefault()
  event.stopPropagation()
  menu.value?.handleClose()
  trigger.value.focus({ preventScroll: true })
}
</script>

<style scoped>
.chat-menu-button {
  display: inline-flex; align-items: center; justify-content: center; min-width: 32px; height: 32px;
  padding: 0 6px; border: 0; border-radius: 8px; background: var(--app-surface-muted);
  color: var(--app-text-secondary); cursor: pointer;
}
.chat-menu-button:hover { background: var(--app-primary-soft); color: var(--app-primary); }
.chat-menu-button:focus-visible { outline: 2px solid var(--app-primary); outline-offset: -2px; }
</style>
