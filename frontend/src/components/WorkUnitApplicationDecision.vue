<template>
  <el-dialog :model-value="true" :title="title" width="min(460px, 94vw)" append-to-body
    :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving"
    @update:model-value="open => { if (!open) emit('close') }">
    <el-form label-position="top" @submit.prevent="submit">
      <p class="decision-summary"><strong>{{ application.workUnitId }}</strong> · 最多 {{ application.imageCount }} 张</p>
      <el-form-item v-if="rejecting" label="驳回原因" for="work-unit-rejection-reason">
        <el-input id="work-unit-rejection-reason" v-model="reason" type="textarea" :maxlength="1000"
          :disabled="!!command" show-word-limit />
      </el-form-item>
      <p v-else class="decision-summary">撤回后，申请记录仍可在这里查看。</p>
      <el-alert v-if="error" :title="error" type="error" :closable="false" role="alert" />
      <div class="decision-actions">
        <el-button :disabled="saving" @click="emit('close')">取消</el-button>
        <el-button type="danger" native-type="submit" :loading="saving"
          :disabled="blocked || (rejecting && !reason.trim())">
          {{ error && !blocked ? '重试' : rejecting ? '确认驳回' : '确认撤回' }}
        </el-button>
      </div>
    </el-form>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { captureAccountRequest } from '@/api/request'
import { decimalVersion } from '@/utils/mutationVersion'

const props = defineProps({ action: { type: String, required: true }, application: { type: Object, required: true } })
const emit = defineEmits(['close', 'completed', 'refresh'])
const api = captureAccountRequest()
const rejecting = computed(() => props.action === 'reject')
const title = computed(() => rejecting.value ? '驳回检测申请' : '撤回检测申请')
const reason = ref(''), saving = ref(false), error = ref(''), command = ref(null), blocked = ref(false)
let disposed = false

async function submit() {
  if (saving.value || blocked.value || (rejecting.value && !reason.value.trim())) return
  const version = decimalVersion(props.application.version)
  if (version === null) {
    blocked.value = true
    error.value = '申请版本尚未核对，请刷新后再操作。'
    emit('refresh')
    return
  }
  saving.value = true
  error.value = ''
  const id = props.application.workUnitId
  const endpoint = rejecting.value ? '/api/detection/supervisor/work-units' : '/api/detection/tasks/work-units'
  const status = rejecting.value ? 'REJECTED' : 'WITHDRAWN'
  try {
    command.value ??= {
      expectedVersion: Number(version), requestId: crypto.randomUUID(),
      ...(rejecting.value ? { reason: reason.value.trim() } : {})
    }
    const { data } = await api.post(`${endpoint}/${encodeURIComponent(id)}/${props.action}`, command.value)
    if (data?.code !== 200 || data.data?.workUnitId !== id || data.data?.status !== status) {
      throw Object.assign(new Error(data?.message || '操作结果暂未确认，请重试。'), { status: data?.code })
    }
    if (!disposed) emit('completed', data.data)
  } catch (cause) {
    if (disposed) return
    const code = cause.response?.data?.code ?? cause.response?.status ?? cause.status
    blocked.value = [400, 401, 403, 404, 409, 412, 422].includes(Number(code)) || cause.accountContextChanged === true
    error.value = cause.response?.data?.message || cause.message || '操作结果暂未确认，请重试。'
    if (blocked.value) emit('refresh')
  } finally {
    if (!disposed) saving.value = false
  }
}

onBeforeUnmount(() => { disposed = true })
</script>

<style scoped>
.decision-summary { margin: 0 0 14px; color: var(--app-text-secondary); overflow-wrap: anywhere; }
.decision-actions { display: flex; justify-content: flex-end; margin-top: 14px; }
</style>
