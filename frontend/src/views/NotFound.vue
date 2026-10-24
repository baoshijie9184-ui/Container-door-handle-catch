<template>
  <section class="not-found-page" aria-labelledby="not-found-title">
    <div class="nf-container">
      <span class="nf-symbol"><AppIcon name="Search" :size="28" /></span>
      <div class="nf-code">404</div>
      <h1 id="not-found-title" class="nf-title">页面未找到</h1>
      <p class="nf-desc">
        当前地址没有对应页面，请核对链接，或从下方入口继续工作。
      </p>
      <div class="nf-actions">
        <el-button type="primary" size="large" @click="goHome">
          <AppIcon name="HomeFilled" />返回首页
        </el-button>
        <el-button v-if="previousPage" size="large" @click="goBack">
          <AppIcon name="ArrowLeft" />返回上一页
        </el-button>
      </div>
      <nav class="nf-shortcuts" aria-label="常用工作入口"><router-link to="/inspection/workbench"><AppIcon name="Picture" :size="16" />检测工作台</router-link><router-link to="/inspection/history"><AppIcon name="Tickets" :size="16" />检测记录</router-link><router-link to="/agent/chat"><AppIcon name="ChatDotRound" :size="16" />Agent 对话</router-link></nav>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const router = useRouter()
const route = useRoute()
const previousPage = computed(() => {
  if (!route.fullPath) return ''
  const back = router.options.history.state.back
  if (typeof back !== 'string' || !back.startsWith('/') || back.startsWith('//')) return ''
  const destination = router.resolve(back)
  return destination.fullPath !== route.fullPath && destination.matched.length && destination.name !== 'notFound' ? back : ''
})

function goHome() {
  router.replace('/home')
}

function goBack() {
  if (previousPage.value) router.back()
  else router.replace('/home')
}
</script>

<style scoped>
.not-found-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 200px);
  padding: 40px 24px;
}

.nf-container {
  text-align: center;
  max-width: 560px;
  min-width: 0;
}
.nf-symbol { width: 60px; height: 60px; margin: 0 auto 24px; display: grid; place-items: center; color: var(--app-primary); background: var(--app-primary-soft); border-radius: 16px; }

.nf-code {
  font-size: clamp(80px, 15vw, 112px);
  font-weight: 750;
  line-height: 1;
  color: var(--app-primary);
  letter-spacing: -0.02em;
}

.nf-title {
  margin: 16px 0 12px;
  font-size: 28px;
  font-weight: 800;
  color: var(--app-text);
}

.nf-desc {
  margin: 0 0 32px;
  color: var(--app-text-secondary);
  font-size: 15px;
  line-height: 1.8;
}

.nf-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
}
.nf-actions .el-button + .el-button { margin-left:0; }
.nf-shortcuts { display:flex; justify-content:center; flex-wrap:wrap; gap:12px 20px; margin-top:30px; padding-top:22px; border-top:1px solid var(--app-border); }
.nf-shortcuts a { display:inline-flex; align-items:center; gap:6px; border-radius:5px; padding:4px 0; color:var(--app-text-secondary); font-size:12px; line-height:1.8; text-decoration:none; }
.nf-shortcuts a:hover { color:var(--app-primary); }
.nf-shortcuts a:focus-visible { outline:2px solid var(--app-primary); outline-offset:4px; }
@media(max-width:480px) { .not-found-page { padding:30px 18px; }.nf-title { font-size:24px; }.nf-desc { font-size:13px; }.nf-actions > button { flex:1 1 auto; }.nf-shortcuts { gap:10px 16px; } }
</style>
