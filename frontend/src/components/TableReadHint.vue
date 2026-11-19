<template>
 <p class="table-read-hint"><AppIcon name="Rank" :size="15" /><span>横向滚动或用方向键查看更多列。</span></p>
</template>
<script setup>
import AppIcon from './AppIcon.vue'
</script>
<style scoped>
@supports selector(:has(+ .el-table)) {
  .table-read-hint:has(+ .el-table:not(.el-table--scrollable-x)) { display:none; }
}
</style>
