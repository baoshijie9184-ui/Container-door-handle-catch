<template>
  <div class="identity-account-picker" :aria-busy="loading">
    <el-select :model-value="selectedAccount?.userId" :disabled="disabled" filterable remote clearable popper-class="identity-account-menu"
      :remote-method="queueSearch" :loading="loading" placeholder="搜索账号名或用户 ID" :aria-label="label"
      loading-text="正在核对账号资料" :no-data-text="error ? '账号资料暂不可读取' : '没有匹配账号，可更换名称或 ID'" no-match-text="没有匹配账号，可更换名称或 ID"
      @visible-change="opened" @change="choose">
      <el-option v-for="account in displayed" :key="account.userId" :value="account.userId" class="identity-account-option"
        :label="`${account.username} · ID ${account.userId} · ${roleNames[account.role]}`">
        <span class="account-option"><strong>{{ account.username }}</strong><span>ID {{ account.userId }} · {{ roleNames[account.role] }}</span></span>
      </el-option>
    </el-select>
    <span v-if="selectedAccount" class="account-proof" :title="selectedAccount.revision"><el-icon aria-hidden="true"><User /></el-icon>已选账号快照 {{ selectedAccount.revision.slice(0, 12) }}</span>
    <span v-else-if="modelValue" class="account-error" role="status">目标快照不完整，请重新选择账号</span>
    <span v-if="error" class="account-error" role="alert">{{ error }}</span>
  </div>
</template>
<script setup>
import { computed, ref, onBeforeUnmount } from 'vue'
import { User } from '@element-plus/icons-vue'
import request from '@/api/request'
const props = defineProps({ modelValue: Object, disabled: Boolean, label: { type: String, default: '历史归属目标账号' } })
const emit = defineEmits(['update:modelValue'])
const roleNames = { ADMIN: '管理员', SUPERVISOR: '主管', INSPECTOR: '检测员', OPERATOR: '操作员' }
const options = ref([]), loading = ref(false), error = ref('')
let generation = 0, timer
const selectedAccount = computed(() => valid(props.modelValue) ? props.modelValue : null)
const displayed = computed(() => [...new Map([selectedAccount.value, ...options.value].filter(valid).map(value => [value.userId, value])).values()])
function valid(value) { return value && Number.isSafeInteger(value.userId) && value.userId > 0 && typeof value.username === 'string' && roleNames[value.role] && /^[a-f0-9]{64}$/.test(value.revision) }
function queueSearch(keyword) { generation++; clearTimeout(timer); loading.value = true; timer = setTimeout(() => search(keyword), 180) }
async function search(keyword = '') {
  const id = ++generation; loading.value = true; error.value = ''
  try {
    const { data } = await request.get('/api/detection/identity/accounts', { params: { keyword: String(keyword).slice(0, 64) } })
    if (id !== generation) return
    if (!Array.isArray(data?.records) || !data.records.every(valid)) throw Error()
    options.value = data.records
  } catch { if (id === generation) { options.value = []; error.value = '账号资料未能核对，请重新检索' } }
  finally { if (id === generation) loading.value = false }
}
function opened(visible) { if (visible) { clearTimeout(timer); search() } }
function choose(id) { const account = displayed.value.find(value => value.userId === id); emit('update:modelValue', account ? { ...account } : null) }
onBeforeUnmount(() => { generation++; clearTimeout(timer) })
</script>
<style scoped>
.identity-account-picker { min-width: 0; }
.el-select { width: 100%; }
.identity-account-option { height: auto; min-height: 34px; padding-block: 6px; line-height: 1.6; white-space: normal; }
.account-option { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; max-width: 100%; }
.account-option strong { min-width: 0; overflow-wrap: anywhere; font-size: 13px; font-weight: 550; }
.account-option > span { flex-shrink: 0; color: var(--app-text-secondary, #475569); font-size: 12px; }
.account-proof { display: flex; align-items: flex-start; gap: 5px; color: var(--app-text-secondary, #475569); font-size: 12px; line-height: 1.8; margin-top: 6px; overflow-wrap: anywhere; }
.account-proof .el-icon { flex-shrink: 0; margin-top: 4px; color: var(--app-primary, #2563eb); }
.account-error { display: block; color: #b91c1c; font-size: 12px; line-height: 1.8; margin-top: 6px; overflow-wrap: anywhere; }
:global(.identity-account-menu) { max-width: calc(100vw - 32px); }
@media (max-width: 640px) { .account-option { flex-direction: column; align-items: flex-start; gap: 0; line-height: 1.6; } .account-option strong { max-width: 100%; } }
</style>
