<template>
  <div class="image-miss-rate">
    <div class="rate-heading">
      <span>图片漏检率</span>
      <strong v-if="!included.length" class="rate-missing">{{ hasInvalid ? '待核对' : '未记录' }}</strong>
    </div>
    <div v-for="group in included" :key="JSON.stringify([group.modelVersion, group.threshold])" class="rate-group">
      <div class="rate-line">
        <span>{{ group.displayVersion ?? group.modelVersion }} · 阈值 {{ group.threshold }}</span>
        <strong>{{ rate(group) }}</strong>
      </div>
      <p>未检出 {{ number(group.missedImages) }} 张 / 成功检测 {{ number(group.successfulImages) }} 张</p>
    </div>
    <p v-if="included.length && covered < taskCount">计入 {{ number(covered) }} / {{ number(taskCount) }} 次任务，其余记录缺少可核对的计数或检测参数。</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { knownCount } from '../utils/countPresentation'

const props = defineProps({ groups: { type: Array, default: () => [] }, taskCount: Number })
const included = computed(() => props.groups.filter(group => knownCount(group.countedTasks) > 0))
const covered = computed(() => included.value.reduce((n, group) => n + Number(group.countedTasks), 0))
const hasInvalid = computed(() => props.groups.some(group => knownCount(group.invalidTasks) > 0))
const number = value => knownCount(value)?.toLocaleString('zh-CN') ?? '—'

function rate(group) {
  const missed = knownCount(group.missedImages)
  const successful = knownCount(group.successfulImages)
  if (missed === null || successful === null || missed > successful) return '待核对'
  return successful === 0 ? '无成功图片' : (100 * missed / successful).toFixed(2) + '%'
}
</script>

<style scoped>
.image-miss-rate { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--app-border); color: var(--app-text-secondary); font-size: 12px; }
.rate-heading, .rate-line { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.rate-heading { color: var(--app-text); font-weight: 600; }
.rate-group { margin-top: 6px; }
.rate-line span { overflow-wrap: anywhere; }
.rate-line strong { color: var(--app-text); font-size: 18px; font-variant-numeric: tabular-nums; }
.rate-missing { color: var(--app-text-secondary); font-weight: 500; }
.image-miss-rate p { margin: 4px 0 0; line-height: 1.6; }
</style>
