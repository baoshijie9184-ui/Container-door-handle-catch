<template>
  <Transition name="global-notice">
    <section v-if="navigationFailure" class="global-error-bar global-navigation-error" role="alert" aria-labelledby="navigation-failure-title">
      <AppIcon name="Connection" :size="20" />
      <div class="global-error-content">
        <strong id="navigation-failure-title">页面未能打开</strong>
        <p v-if="navigationFailure.requiresReload">“{{ navigationFailure.title }}”的页面资源加载失败。请保留草稿后重新加载。</p>
        <p v-else>未能打开“{{ navigationFailure.title }}”。请检查连接后重试。</p>
        <div class="global-error-actions">
          <button v-if="navigationFailure.canRetry" type="button" :disabled="navigationFailure.retrying" :aria-busy="navigationFailure.retrying" @click="retryNavigation(router)"><AppIcon name="Refresh" :size="15" />{{ navigationFailure.retrying ? '正在打开页面' : navigationFailure.requiresReload ? '重新加载页面' : '重试打开页面' }}</button>
          <router-link to="/home"><AppIcon name="HomeFilled" :size="15" />返回首页</router-link>
        </div>
      </div>
      <button class="global-error-close" type="button" aria-label="收起页面加载失败提示" title="收起提示，不代表页面已恢复" :disabled="navigationFailure.retrying" @click="clearNavigationFailure"><AppIcon name="Close" :size="18" /></button>
    </section>
  </Transition>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { navigationFailure, clearNavigationFailure, retryNavigation } from '../utils/navigationFeedback'
const router = useRouter()
</script>
