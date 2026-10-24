<template>
  <Transition name="global-notice">
    <section v-if="navigationFailure" class="global-error-bar global-navigation-error" role="alert" aria-labelledby="navigation-failure-title">
      <AppIcon name="Connection" :size="20" />
      <div class="global-error-content">
        <strong id="navigation-failure-title">页面未能打开</strong>
        <p>未能打开“{{ navigationFailure.title }}”。请检查连接后重试，或从首页重新进入。</p>
        <p>已提交操作请先核对记录。重新打开页面不会自动重发业务操作；离开当前页面前请保存草稿。</p>
        <div class="global-error-actions">
          <button v-if="navigationFailure.canRetry" type="button" :disabled="navigationFailure.retrying" :aria-busy="navigationFailure.retrying" @click="retryNavigation(router)"><AppIcon name="Refresh" :size="15" />{{ navigationFailure.retrying ? '正在打开页面' : '重试打开页面' }}</button>
          <router-link to="/home"><AppIcon name="HomeFilled" :size="15" />返回首页</router-link>
        </div>
        <details class="global-navigation-reload"><summary>重试仍失败时</summary><p>先保留未保存的输入，再刷新整个页面以重新读取页面资源。若仍无法打开，请联系维护人员。</p><div class="global-error-actions"><button type="button" @click="reloadPage"><AppIcon name="Refresh" :size="15" />确认刷新整个页面</button></div></details>
      </div>
      <button class="global-error-close" type="button" aria-label="收起页面加载失败提示" title="收起提示，不代表页面已恢复" :disabled="navigationFailure.retrying" @click="clearNavigationFailure"><AppIcon name="Close" :size="18" /></button>
    </section>
  </Transition>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { navigationFailure, clearNavigationFailure, retryNavigation } from '../utils/navigationFeedback'
const router = useRouter()
const reloadPage = () => window.location.reload()
</script>
