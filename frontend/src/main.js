import { createApp, toRaw } from 'vue'
import { accountSession } from './utils/accountContext'
import { accountFetch } from './utils/accountFetch'
globalThis.__doorhandleAccountFetch = accountFetch
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
import TableReadHint from './components/TableReadHint.vue'
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
// Clear private store caches when the browser cookie switches account.
const copyState = value => {
  value = toRaw(value)
  if (Array.isArray(value)) return value.map(copyState)
  if (value instanceof Map) return new Map([...value].map(([key,item])=>[key,copyState(item)]))
  if (value instanceof Set) return new Set([...value].map(copyState))
  if (value && Object.getPrototypeOf(value)===Object.prototype) return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,copyState(item)]))
  return value
}
pinia.use(({store})=>{
  if(store.$id==='user')return
  const initial=copyState(store.$state)
  const off=accountSession.onReset(()=>store.$patch(copyState(initial)))
  const dispose=store.$dispose.bind(store)
  store.$dispose=()=>{off();dispose()}
})
app.use(pinia)
app.use(router)
app.use(ElementPlus, {
  locale: zhCn
})
app.component('AppIcon', AppIcon)
app.component('PageHero', PageHero)
app.component('StatusBadge', StatusBadge)
app.component('TableReadHint', TableReadHint)

// 挂载应用
app.mount('#app')

console.log('应用已挂载') 
