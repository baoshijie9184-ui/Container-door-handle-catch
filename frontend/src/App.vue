<template>
  <div id="app" class="app-root">
    <div id="nprogress-bar" class="nprogress-bar"></div>
    <div v-if="error" class="global-error-bar">
      <span>{{ error }}</span>
      <button class="global-error-close" @click="error = ''">&times;</button>
    </div>
    <router-view v-slot="{ Component, route }">
      <transition :name="route.meta.transition || 'page-fade'" mode="out-in">
        <component :is="Component" :key="route.path" />
      </transition>
    </router-view>
  </div>
</template>

<script setup>
import { ref, onErrorCaptured } from 'vue'

const error = ref('')

onErrorCaptured((err, instance, info) => {
  console.error('Captured application error:', err, info)
  error.value = `应用错误: ${err.message}`
  return false
})
</script>

<style>
.app-root {
  min-height: 100vh;
}

/* NProgress 风格进度条 */
.nprogress-bar {
  position: fixed;
  top: 0;
  left: 0;
  z-index: 10000;
  height: 3px;
  width: 0%;
  opacity: 0;
  background: linear-gradient(90deg, var(--app-primary), var(--app-success));
  border-radius: 0 3px 3px 0;
  transition: opacity 0.3s ease;
  pointer-events: none;
}

.global-error-bar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 14px 24px;
  background: linear-gradient(90deg, var(--app-danger), #ff6b6b);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  box-shadow: 0 8px 32px rgba(239, 91, 91, 0.28);
}

.global-error-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid rgba(255,255,255,0.4);
  border-radius: 50%;
  background: transparent;
  color: #fff;
  font-size: 18px;
  cursor: pointer;
  transition: background 0.2s;
}

.global-error-close:hover {
  background: rgba(255,255,255,0.18);
}

/* 页面过渡动画 */
.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}

.page-fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.page-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* 页面过渡：同时进出，绝对定位避免抖动 */
.page-slide-enter-active,
.page-slide-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.page-slide-enter-active {
  position: relative;
  z-index: 1;
}

.page-slide-leave-active {
  position: absolute;
  width: 100%;
  z-index: 0;
}

.page-slide-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.page-slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

/* 滚动条美化 */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: rgba(15, 23, 42, 0.14);
  border-radius: 999px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(15, 23, 42, 0.24);
}
</style>
