<template>
  <el-menu ref="menu" :default-active="active" router :collapse="collapsed" class="nav-menu" @select="$emit('navigate')">
    <template v-for="group in groups" :key="group.key">
      <el-menu-item v-if="group.items.length === 1" :index="group.items[0].path" :title="group.items[0].label" :aria-current="active===group.items[0].path ? 'page' : undefined">
        <el-icon aria-hidden="true"><component :is="group.icon" /></el-icon>
        <template #title><span>{{ group.items[0].label }}</span></template>
      </el-menu-item>
      <el-sub-menu v-else :index="group.key" :aria-label="group.label" popper-class="workspace-nav-popover">
        <template #title><el-icon aria-hidden="true"><component :is="group.icon" /></el-icon><span>{{ group.label }}</span></template>
        <el-menu-item v-for="item in group.items" :key="item.path" :index="item.path" :title="item.desc || item.label" :aria-current="active===item.path ? 'page' : undefined">
          <span>{{ item.label }}</span>
        </el-menu-item>
      </el-sub-menu>
    </template>
  </el-menu>
</template>
<script setup>
import {computed,nextTick,ref,watch} from 'vue'
const props=defineProps({ groups: { type: Array, required: true }, active: String, collapsed: Boolean })
defineEmits(['navigate'])
const menu=ref(null)
const activeGroup=computed(()=>props.groups.find(group=>group.items.length>1&&group.items.some(item=>item.path===props.active))?.key)
watch(()=>[props.active,props.collapsed,activeGroup.value],async()=>{
  const key=activeGroup.value,path=props.active
  if(!key||props.collapsed)return
  await nextTick()
  if(!props.collapsed&&activeGroup.value===key&&props.active===path)menu.value?.open(key)
},{immediate:true,flush:'post'})
</script>
<style scoped>
.nav-menu { width: 100%; border: 0; background: transparent; }
.nav-menu :deep(.el-menu-item), .nav-menu :deep(.el-sub-menu__title) { height: 44px; line-height: 44px; border-radius: 8px; margin: 3px 0; font-size: 13px; transition: background var(--app-transition-fast), color var(--app-transition-fast); }
.nav-menu :deep(.el-menu-item .el-icon), .nav-menu :deep(.el-sub-menu__title .el-icon) { font-size: 19px; color: var(--app-text-muted); }
.nav-menu :deep(.el-menu-item.is-active) { background: var(--app-primary-soft); color: var(--app-primary); font-weight: 650; }
.nav-menu :deep(.el-menu-item.is-active .el-icon) { color: var(--app-primary); }
.nav-menu :deep(.el-sub-menu.is-active > .el-sub-menu__title),.nav-menu :deep(.el-sub-menu.is-active > .el-sub-menu__title .el-icon) { color:var(--app-primary); }
.nav-menu :deep(.el-sub-menu.is-active > .el-sub-menu__title) { font-weight:600; }
.nav-menu :deep(.el-sub-menu .el-menu-item) { min-width: 0; height: 39px; line-height: 39px; font-size: 12px; }
.nav-menu :deep(.el-sub-menu .el-menu) { background: transparent; }
.nav-menu :deep(.el-menu-item:focus-visible),.nav-menu :deep(.el-sub-menu__title:focus-visible) { outline:2px solid var(--app-primary); outline-offset:-2px; }
@media(prefers-reduced-motion:reduce) { .nav-menu :deep(.el-menu-item),.nav-menu :deep(.el-sub-menu__title) { transition:none; } }
</style>

<style>
.workspace-nav-popover { max-width:calc(100vw - 24px); --el-menu-bg-color:var(--app-surface,#fff); --el-menu-text-color:var(--app-text-secondary,#475569); --el-menu-active-color:var(--app-primary,#2563eb); }
.workspace-nav-popover .el-menu--popup { min-width:200px; max-width:min(280px,calc(100vw - 32px)); padding:5px; border:1px solid var(--app-border,#e2e8f0); border-radius:9px; background:var(--app-surface,#fff); box-shadow:var(--app-shadow-md); }
.workspace-nav-popover .el-menu-item { height:auto; min-height:40px; padding:10px 14px; border-radius:6px; font-size:13px; line-height:1.7; white-space:normal; overflow-wrap:anywhere; transition:background-color 160ms ease,color 160ms ease; }
.workspace-nav-popover .el-menu-item.is-active { background:var(--app-primary-soft,#eff5ff); color:var(--app-primary,#2563eb); font-weight:600; }
.workspace-nav-popover .el-menu-item:focus-visible { outline:2px solid var(--app-primary,#2563eb); outline-offset:-2px; }
@media(prefers-reduced-motion:reduce) { .workspace-nav-popover .el-menu-item { transition:none; } }
</style>
