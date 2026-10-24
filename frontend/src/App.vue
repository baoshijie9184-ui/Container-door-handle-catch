<template>
  <div id="app" class="app-root">
    <div id="nprogress-bar" class="nprogress-bar" aria-hidden="true"></div>
    <div class="global-notices">
    <NavigationFailureNotice />
    <Transition name="global-notice">
      <div v-if="error" class="global-error-bar" role="alert">
        <AppIcon name="Warning" :size="20" />
        <div class="global-error-content"><strong>页面出现异常</strong><p>部分内容可能未显示，已提交操作请先核对记录，避免重复提交。</p><details><summary>查看错误说明</summary><pre>{{ error }}</pre></details></div>
        <router-link v-if="$route.path !== '/login'" class="global-error-home" to="/home"><AppIcon name="HomeFilled" :size="15" />返回首页</router-link>
        <button class="global-error-close" type="button" aria-label="收起页面异常提示" title="收起提示，不代表异常已修复" @click="error = ''"><AppIcon name="Close" :size="18" /></button>
      </div>
    </Transition>
    </div>
    <router-view v-slot="{ Component, route }">
      <transition :name="route.meta.transition || 'page-fade'" mode="out-in">
        <component :is="Component" :key="route.matched[0]?.path || route.path" />
      </transition>
    </router-view>
  </div>
</template>

<script setup>
import { ref, watch, onErrorCaptured } from 'vue'
import { useRoute } from 'vue-router'
import NavigationFailureNotice from './components/NavigationFailureNotice.vue'

const error = ref('')
const currentRoute = useRoute()
watch(() => currentRoute.path, () => { error.value = '' })

onErrorCaptured((err, instance, info) => {
  console.error('Captured application error:', err, info)
  error.value = typeof err?.message === 'string' && err.message.trim() ? err.message : '未返回可显示的异常说明，请联系维护人员核对。'
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
  background: var(--app-primary);
  border-radius: 0 3px 3px 0;
  transition: opacity 200ms ease;
  pointer-events: none;
}

.global-notices {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 9999;
  max-height: 55vh;
  max-height: 55dvh;
  overflow: auto;
  pointer-events: none;
}
.global-error-bar {
  position: relative;
  pointer-events: auto;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  max-height: 45vh;
  max-height: 45dvh;
  overflow: auto;
  padding: 16px 24px;
  background: var(--app-danger-soft);
  color: var(--app-text);
  border-bottom: 1px solid #f5d5d9;
  box-shadow: var(--app-shadow-sm);
}
.global-error-bar > .el-icon { flex-shrink:0; margin-top:2px; color:var(--app-danger); }
.global-error-content { flex:1; min-width:0; overflow-wrap:anywhere; font-size:13px; line-height:1.8; }
.global-error-content strong { font-size:14px; font-weight:600; }
.global-error-content p { margin:3px 0 7px; color:var(--app-text-secondary); }
.global-error-content summary { width:fit-content; color:var(--app-danger); font-size:12px; cursor:pointer; }
.global-error-content pre { max-height:180px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; margin:8px 0 0; font:12px/1.8 Consolas,monospace; color:var(--app-text-secondary); }
.global-error-home { display:inline-flex; align-items:center; gap:6px; flex-shrink:0; min-height:30px; color:var(--app-primary); font-size:12px; text-decoration:none; line-height:1.8; }
.global-error-bar :is(a,button,summary):focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
.global-navigation-error { background:var(--app-surface, #fff); border-bottom-color:var(--app-border); border-left:4px solid var(--app-primary); }
.global-navigation-error > .el-icon { color:var(--app-primary); }
.global-navigation-reload { margin-top:12px; }
.global-navigation-reload summary { color:var(--app-primary); }
.global-navigation-reload p { margin-top:8px; }
.global-error-actions { display:flex; flex-wrap:wrap; gap:8px 16px; margin-top:10px; }
.global-error-actions :is(button,a) { display:inline-flex; align-items:center; justify-content:center; gap:6px; min-height:34px; border:1px solid var(--app-border); border-radius:7px; padding:5px 10px; background:#fff; color:var(--app-primary); font:inherit; text-decoration:none; cursor:pointer; transition:background 180ms ease,transform 180ms ease; }
.global-error-actions :is(button,a):hover { background:var(--app-primary-soft); }
.global-error-actions :is(button,a):active { transform:scale(.98); }
.global-error-actions button:disabled,.global-error-close:disabled { opacity:.6; cursor:wait; transform:none; }

.global-error-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 30px;
  width: 30px;
  height: 30px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--app-text-secondary);
  font-size: 18px;
  cursor: pointer;
  transition: background 0.2s;
}

.global-error-close:hover {
  background: #fee2e2;
  color: var(--app-danger);
}
.global-notice-enter-active,.global-notice-leave-active { transition:opacity 180ms ease,transform 180ms ease; }
.global-notice-enter-from,.global-notice-leave-to { opacity:0; transform:translateY(-4px); }
@media(max-width:640px) { .global-error-bar { gap:8px; padding:12px; } .global-error-home { align-self:center; } }
@media(max-width:420px) { .global-error-home { flex-basis:52px; flex-shrink:1; flex-wrap:wrap; justify-content:center; text-align:center; } }
@media(prefers-reduced-motion:reduce) { .global-notice-enter-active,.global-notice-leave-active,.nprogress-bar,.global-error-close,.global-error-actions :is(button,a) { transition:none; transform:none; } }

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

/* The route uses out-in mode; both phases stay in the existing content flow. */
.page-slide-enter-active,
.page-slide-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
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
