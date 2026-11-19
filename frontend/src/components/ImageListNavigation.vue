<template>
  <nav ref="navigation" class="image-list-navigation" tabindex="0" aria-label="图片翻页"
       aria-keyshortcuts="ArrowLeft ArrowRight Home End" @keydown="onKey">
    <button type="button" :disabled="index <= 0" @click="select(index - 1)"><AppIcon name="ArrowLeft" :size="15" />上一张</button>
    <span aria-live="polite" aria-atomic="true">第 {{ index + 1 }} / {{ total }} 张</span>
    <button type="button" :disabled="index >= total - 1" @click="select(index + 1)">下一张<AppIcon name="ArrowRight" :size="15" /></button>
  </nav>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({ index: { type: Number, required: true }, total: { type: Number, required: true } })
const emit = defineEmits(['select'])
const navigation = ref(null)
function select(index) {
  if (index < 0 || index >= props.total || index === props.index) return
  const button = document.activeElement
  emit('select', index)
  nextTick(() => {
    if (navigation.value?.contains(button) && button.disabled) navigation.value.focus({ preventScroll: true })
  })
}
function onKey(event) {
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
  const targets = { ArrowLeft: props.index - 1, ArrowRight: props.index + 1, Home: 0, End: props.total - 1 }
  if (!Object.hasOwn(targets, event.key)) return
  event.preventDefault()
  event.stopPropagation()
  select(targets[event.key])
}
defineExpose({ focus: () => navigation.value?.focus({ preventScroll: true }) })
</script>

<style scoped>
.image-list-navigation { display: inline-flex; align-items: center; flex-wrap: wrap; gap: 8px; border-radius: 8px; }
.image-list-navigation span { color: var(--app-text); font-size: 13px; font-variant-numeric: tabular-nums; }
.image-list-navigation button { display: inline-flex; align-items: center; gap: 4px; min-height: 34px; padding: 4px 9px; border: 1px solid var(--app-border); border-radius: 7px; color: var(--app-text); background: white; font: inherit; font-size: 13px; cursor: pointer; }
.image-list-navigation button:hover:enabled { color: var(--app-primary); background: var(--app-primary-soft); }
.image-list-navigation button:disabled { color: var(--app-text-muted); background: var(--app-surface-muted); cursor: default; }
.image-list-navigation:focus-visible, .image-list-navigation button:focus-visible { outline: 2px solid var(--app-primary); outline-offset: 2px; }
</style>
