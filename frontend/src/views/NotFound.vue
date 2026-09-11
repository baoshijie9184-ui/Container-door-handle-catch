<template>
  <div class="not-found-page">
    <div class="nf-container">
      <div class="nf-code">404</div>
      <h1 class="nf-title">页面未找到</h1>
      <p class="nf-desc">
        您访问的页面不存在，可能已被移动或删除。<br />
        请检查链接是否正确，或返回首页继续操作。
      </p>
      <div class="nf-actions">
        <el-button type="primary" size="large" @click="goHome">
          返回首页
        </el-button>
        <el-button size="large" @click="goBack">
          返回上一页
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

function goHome() {
  router.push('/home')
}

function goBack() {
  router.back()
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
  max-width: 520px;
}

.nf-code {
  font-size: 120px;
  font-weight: 900;
  line-height: 1;
  background: linear-gradient(135deg, #2f6bff 0%, #12a87a 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
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
</style>
