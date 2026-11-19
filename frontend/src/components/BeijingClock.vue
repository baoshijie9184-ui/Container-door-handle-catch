<template><time class="beijing-clock" :datetime="now.toISOString()"><span>北京时间</span><b>{{ beijingDateTime(now) }}</b></time></template>
<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { beijingDateTime, subscribeClock } from '../utils/beijingTime'
import '../assets/beijing-clock.css'
const now = ref(new Date())
let stop
onMounted(() => { stop = subscribeClock(value => { now.value = value }) })
onBeforeUnmount(() => stop?.())
</script>
