<template>
 <el-dropdown ref="menu" trigger="click" :placement="compact?'right-end':'bottom-end'" popper-class="app-account-popover" class="app-account-menu" :class="{'is-compact':compact}" @visible-change="opened=$event" @command="command">
  <button type="button" class="app-account-trigger" :class="{'is-compact':compact}" :aria-label="'账号菜单：'+accountName" :aria-expanded="opened" aria-haspopup="menu" :title="accountName">
   <span class="app-account-avatar" aria-hidden="true"><AppIcon name="User" :size="19" /></span>
   <span v-if="!compact" class="app-account-trigger-copy"><strong>{{ accountName }}</strong><small>{{ role || '角色未记录' }}</small></span>
   <AppIcon v-if="!compact" name="ArrowDown" :size="13" class="app-account-chevron" />
  </button>
  <template #dropdown><el-dropdown-menu>
   <el-dropdown-item disabled class="app-account-profile"><div><small>当前账号</small><strong>{{ accountName }}</strong><span>{{ role || '角色未记录' }}</span><span v-if="department">{{ department }}</span><small>{{ scope || '资料范围以当前授权为准' }}</small></div></el-dropdown-item>
   <el-dropdown-item command="home"><AppIcon name="HomeFilled" :size="16" />返回业务首页</el-dropdown-item>
   <el-dropdown-item command="manual"><AppIcon name="Files" :size="16" />使用手册</el-dropdown-item>
   <el-dropdown-item divided command="logout" class="app-account-logout"><AppIcon name="Close" :size="16" />退出登录</el-dropdown-item>
  </el-dropdown-menu></template>
 </el-dropdown>
</template>
<script setup>
import {computed,ref,watch} from 'vue'
import AppIcon from './AppIcon.vue'
const props=defineProps({username:String,role:String,department:String,scope:String,compact:Boolean})
const emit=defineEmits(['home','manual','logout'])
const menu=ref(null),opened=ref(false)
const accountName=computed(()=>typeof props.username==='string' && props.username.trim()?props.username:'账号未记录')
function command(value){if(['home','manual','logout'].includes(value))emit(value)}
watch(()=>[props.username,props.role,props.department,props.scope],()=>{menu.value?.handleClose();opened.value=false})
</script>
<style scoped>
.app-account-menu { flex:0 0 auto; min-width:0; max-width:240px; }
.app-account-trigger { display:flex; align-items:center; gap:8px; min-width:0; max-width:100%; min-height:36px; padding:2px 6px; border:1px solid transparent; border-radius:7px; background:transparent; color:var(--app-text); font:inherit; cursor:pointer; transition:background-color 160ms ease,border-color 160ms ease,transform 160ms ease; }
.app-account-trigger:hover { border-color:var(--app-border); background:var(--app-surface-hover); }
.app-account-trigger:active { transform:scale(.98); }
.app-account-avatar { display:grid; place-items:center; flex:0 0 28px; width:28px; height:28px; border-radius:7px; color:var(--app-text-secondary); background:var(--app-surface-muted); font-size:12px; font-weight:600; }
.app-account-trigger-copy { display:grid; gap:2px; min-width:0; text-align:left; }
.app-account-trigger-copy strong { max-width:clamp(80px,10vw,150px); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12px; font-weight:550; line-height:1.5; }
.app-account-trigger-copy small { color:var(--app-text-muted); font-size:11px; line-height:1.4; }
.app-account-chevron { flex-shrink:0; color:var(--app-text-secondary); transition:transform 180ms ease; }
.app-account-trigger[aria-expanded=true] .app-account-chevron { transform:rotate(180deg); }
.app-account-menu.is-compact { width:36px; max-width:36px; }
.app-account-trigger.is-compact { justify-content:center; width:36px; min-height:36px; padding:1px; }
.app-account-trigger:focus-visible { outline:2px solid var(--app-primary); outline-offset:3px; }
@media(max-width:640px) { .app-account-trigger:not(.is-compact) { gap:5px; padding:4px; }.app-account-trigger-copy { display:none; }.app-account-trigger:not(.is-compact) .app-account-avatar { width:30px; height:30px; flex-basis:30px; } }
@media(prefers-reduced-motion:reduce) { .app-account-trigger,.app-account-chevron { transition:none; }.app-account-trigger:active { transform:none; } }
</style>
<style>
.app-account-popover { max-width:calc(100vw - 24px); border-color:var(--app-border); border-radius:10px; background:var(--app-surface); box-shadow:var(--app-shadow-md); }
.app-account-popover .el-dropdown-menu { min-width:220px; max-width:min(290px,calc(100vw - 28px)); padding:6px; border-radius:10px; }
.app-account-popover .el-dropdown-menu__item { gap:8px; min-height:38px; padding:9px 12px; border-radius:6px; color:var(--app-text-secondary); font-size:13px; line-height:1.8; }
.app-account-popover .el-dropdown-menu__item .el-icon { flex-shrink:0; margin-right:0; }
.app-account-popover .el-dropdown-menu__item.app-account-profile { height:auto; min-height:0; margin-bottom:6px; padding-bottom:14px; border-bottom:1px solid var(--app-border); border-radius:0; color:var(--app-text-secondary); cursor:default; user-select:text; }
.app-account-popover .app-account-profile > div { display:grid; gap:4px; min-width:0; max-width:100%; white-space:normal; overflow-wrap:anywhere; }
.app-account-popover .app-account-profile strong { color:var(--app-text); font-size:14px; line-height:1.8; font-weight:600; }
.app-account-popover .app-account-profile :is(small,span) { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.app-account-popover .el-dropdown-menu__item.app-account-logout { color:var(--app-danger); }
.app-account-popover .app-account-logout:not(.is-disabled):is(:hover,:focus) { color:var(--app-danger); background:var(--app-danger-soft); }
.app-account-popover .el-dropdown-menu__item:not(.is-disabled):focus-visible { outline:2px solid var(--app-primary); outline-offset:-2px; }
</style>
