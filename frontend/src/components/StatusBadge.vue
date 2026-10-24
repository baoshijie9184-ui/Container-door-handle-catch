<template>
  <span class="business-status" :data-tone="presentation.tone" :title="presentation.label + (presentation.code ? ' · ' + presentation.code : '')">
    <AppIcon :name="presentation.icon" :size="13" /><span>{{ presentation.label }}</span>
  </span>
</template>
<script setup>
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import { statusPresentation } from '../utils/statusPresentation'
const props = defineProps({ domain: { type: String, required: true }, code: [String, Number], label: String })
const presentation = computed(() => statusPresentation(props.domain, props.code, props.label))
</script>
