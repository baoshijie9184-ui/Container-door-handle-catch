import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import './assets/design-tokens.css'
import './assets/status-badge.css'
import './assets/theme.scss'
import './assets/system-ui.css'
import AppIcon from './components/AppIcon.vue'
import PageHero from './components/PageHero.vue'
import StatusBadge from './components/StatusBadge.vue'
import App from './App.vue'
import router from './router'
import './api/request'

// 全局错误处理
window.addEventListener('error', (event) => {
  console.error('全局JS错误:', event.error)
})

window.addEventListener('unhandledrejection', (event) => {
  console.error('未处理的Promise错误:', event.reason)
})

// 创建应用
const app = createApp(App)

// 全局错误处理
app.config.errorHandler = (err, vm, info) => {
  console.error('Vue错误处理:', err, info)
}

// 创建并使用插件
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(ElementPlus, {
  locale: zhCn
})
app.component('AppIcon', AppIcon)
app.component('PageHero', PageHero)
app.component('StatusBadge', StatusBadge)

// 挂载应用
app.mount('#app')

console.log('应用已挂载') 
