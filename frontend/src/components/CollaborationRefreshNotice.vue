<template>
  <Transition name="collaboration-feedback">
    <section v-if="changed" class="collaboration-refresh" role="status">
      <AppIcon name="Warning" :size="18" />
      <div><strong>资料可能已更新</strong><p>{{ editing ? '当前草稿与读取版本已保留 关闭编辑后可核对新版本' : '当前筛选和浏览位置已保留 可重新读取授权范围内的资料' }}</p></div>
      <el-button :disabled="editing" @click="$emit('refresh')">核对最新资料</el-button>
      <router-link :to="historyTo">查看修改记录</router-link>
    </section>
  </Transition>
</template>
<script setup>
defineProps({changed:Boolean,editing:Boolean,historyTo:{type:[String,Object],default:()=>({path:'/operations/audit',query:{domain:'DETECTION'}})}})
defineEmits(['refresh'])
</script>
<style scoped>
.collaboration-refresh{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:13px 16px;margin:12px 0;border:1px solid var(--app-border);border-left:3px solid var(--app-primary);border-radius:6px;background:var(--app-surface);font-size:13px}.collaboration-refresh>div{flex:1;min-width:220px}.collaboration-refresh strong{font-weight:550}.collaboration-refresh p{margin:4px 0 0;color:var(--app-text-secondary);font-size:12px;line-height:1.7}.collaboration-refresh a{color:var(--app-primary);font-size:12px}.collaboration-refresh a:focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}.collaboration-feedback-enter-active,.collaboration-feedback-leave-active{transition:opacity 160ms ease,transform 160ms ease}.collaboration-feedback-enter-from,.collaboration-feedback-leave-to{opacity:0;transform:translateY(-3px)}@media(prefers-reduced-motion:reduce){.collaboration-feedback-enter-active,.collaboration-feedback-leave-active{transition:none;transform:none}}
</style>
